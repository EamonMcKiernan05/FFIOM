import logging
"""Authentication API routes for Fantasy Football IOM.

Security fixes applied:
- C7: PKCE code_verifier stored in signed HTTP-only cookie, not in state param
- H1: Rate limiting on login/register/refresh endpoints
- H4: Legacy form-login endpoint removed
- M2: datetime.utcnow() replaced with datetime.now(timezone.utc)
"""
import os
import json
import time
import secrets
import hashlib
import base64
from datetime import datetime, timezone, timedelta
from typing import Optional
from collections import defaultdict

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_bound_db, get_current_season
from app.utils.squad import create_default_squad
from app.models import User, RefreshToken, Player
from app.schemas import (
    UserCreate, LoginRequest, RefreshRequest, TokenResponse, UserResponse,
)
from app.auth import (
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
    revoke_refresh_token,
    revoke_all_user_tokens,
    get_current_user_from_token,
    SECRET_KEY,
)
from app.utils.passwords import hash_password, verify_password
from app.auth_linking import resolve_or_create_user, create_email_identity

router = APIRouter(prefix="/api/auth", tags=["auth"])


# --- H1: Simple in-memory rate limiter ---

_rate_limit_store: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 10  # max requests per window


def _check_rate_limit(key: str, max_requests: int = RATE_LIMIT_MAX):
    """Check and enforce rate limit for a given key (IP + endpoint)."""
    now = time.time()
    # Prune old entries
    _rate_limit_store[key] = [
        t for t in _rate_limit_store[key] if now - t < RATE_LIMIT_WINDOW
    ]
    if len(_rate_limit_store[key]) >= max_requests:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later.",
        )
    _rate_limit_store[key].append(now)


def _get_rate_limit_key(request: Request, endpoint: str) -> str:
    """Build a rate limit key from client IP and endpoint."""
    client_ip = request.client.host if request.client else "unknown"
    return f"{client_ip}:{endpoint}"


# --- C7: Signed cookie helpers for PKCE verifier ---

def _sign_cookie(value: str) -> str:
    """Create a signed cookie value: base64(value).signature"""
    encoded = base64.urlsafe_b64encode(value.encode()).decode()
    sig = hashlib.sha256(f"{encoded}:{SECRET_KEY}".encode()).hexdigest()[:32]
    return f"{encoded}.{sig}"


def _verify_cookie(cookie_value: str) -> Optional[str]:
    """Verify and extract a signed cookie value."""
    if not cookie_value or "." not in cookie_value:
        return None
    encoded, sig = cookie_value.rsplit(".", 1)
    expected_sig = hashlib.sha256(f"{encoded}:{SECRET_KEY}".encode()).hexdigest()[:32]
    if sig != expected_sig:
        return None
    try:
        return base64.urlsafe_b64decode(encoded.encode()).decode()
    except Exception:
        return None


# --- Registration ---

@router.post("/register", response_model=dict)
def register(
    user_data: UserCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_bound_db),
):
    """Register a new user and return auth tokens."""
    _check_rate_limit(_get_rate_limit_key(request, "register"), max_requests=5)

    from sqlalchemy import or_
    existing = db.query(User).filter(
        or_(User.username == user_data.username, User.email == user_data.email)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email taken")

    new_user = User(
        username=user_data.username,
        email=user_data.email,
        password_hash=hash_password(user_data.password),
        email_verified=False,
        display_name=user_data.username,
    )
    db.add(new_user)
    db.flush()

    create_email_identity(db, new_user.id, user_data.email)

    # Create fantasy team (season auto-advances via get_current_season)
    from app.models import FantasyTeam
    team_name = (user_data.team_name or f"{user_data.username}'s Team").strip()
    ft = FantasyTeam(
        user_id=new_user.id,
        name=team_name,
        season=get_current_season(db),
        budget=90.0,
        budget_remaining=90.0,
        free_transfers=1,
        free_transfers_next_gw=1,
    )
    db.add(ft)
    db.flush()

    # C8 fix: give new users a default 13-player squad so they start with a
    # legal squad instead of an empty one.
    try:
        players = db.query(Player).filter(Player.is_active == True).all()
        if players:
            create_default_squad(ft, players, db)
            db.flush()
    except Exception as exc:
        db.rollback()
        logger.warning("Default squad creation failed for user %s: %s", new_user.id, exc)

    db.commit()

    access_token = create_access_token(new_user.id, new_user.username)
    refresh_token = create_refresh_token(
        new_user.id,
        user_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        db=db,
    )

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=7 * 24 * 3600,
        path="/api/auth",
    )

    team_payload = {
        "id": ft.id,
        "name": ft.name,
        "budget": ft.budget,
        "budget_remaining": ft.budget_remaining,
        "season": ft.season,
    }

    return {
        **TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        ).model_dump(),
        "user": {
            "id": new_user.id,
            "username": new_user.username,
            "email": new_user.email,
            "email_verified": new_user.email_verified,
        },
        "team": team_payload,
    }


# --- Login ---

@router.post("/login", response_model=dict)
def login(
    credentials: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_bound_db),
):
    """Login with username/email and password."""
    _check_rate_limit(_get_rate_limit_key(request, "login"), max_requests=5)

    from sqlalchemy import or_
    user = db.query(User).filter(
        or_(User.username == credentials.username, User.email == credentials.username)
    ).first()

    if not user or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_access_token(user.id, user.username)
    refresh_token = create_refresh_token(
        user.id,
        user_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        db=db,
    )

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=7 * 24 * 3600,
        path="/api/auth",
    )

    return {
        **TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
        ).model_dump(),
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "email_verified": user.email_verified,
        },
    }


# --- Token refresh ---

@router.post("/refresh", response_model=TokenResponse)
def refresh_token(
    request: Request,
    response: Response,
    refresh_request: Optional[RefreshRequest] = None,
    db: Session = Depends(get_bound_db),
):
    """Refresh an access token using a refresh token.

    Accepts the refresh token from the request body or from the
    HTTP-only cookie (H3: preferred method).
    """
    _check_rate_limit(_get_rate_limit_key(request, "refresh"), max_requests=10)

    raw_token = None

    # Try cookie first (H3: HttpOnly cookie transport)
    cookie_token = request.cookies.get("refresh_token")
    if cookie_token:
        raw_token = cookie_token

    # Fall back to request body
    if not raw_token and refresh_request:
        raw_token = refresh_request.refresh_token

    if not raw_token:
        raise HTTPException(status_code=401, detail="No refresh token provided")

    # H5: Pass user-agent for client binding verification
    user_agent = request.headers.get("user-agent")
    user = verify_refresh_token(raw_token, user_agent=user_agent, db=db)

    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    # Rotate: revoke old, issue new
    revoke_refresh_token(raw_token, db=db)

    new_access = create_access_token(user.id, user.username)
    new_refresh = create_refresh_token(
        user.id,
        user_ip=request.client.host if request.client else None,
        user_agent=user_agent,
        db=db,
    )

    response.set_cookie(
        key="refresh_token",
        value=new_refresh,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=7 * 24 * 3600,
        path="/api/auth",
    )

    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh,
    )


# --- Logout ---

@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user_from_token),
    db: Session = Depends(get_bound_db),
):
    """Logout: revoke the presented refresh token and all of the user's tokens."""
    cookie_token = request.cookies.get("refresh_token")
    if cookie_token:
        revoke_refresh_token(cookie_token, db=db)

    revoked = revoke_all_user_tokens(user.id, db=db)

    response.delete_cookie(key="refresh_token", path="/api/auth")
    return {"status": "logged_out", "revoked_tokens": revoked}


# --- Google OAuth ---

@router.get("/google")
def google_oauth_start(request: Request, response: Response):
    """Start Google OAuth flow.

    C7: PKCE code_verifier is stored in a signed HTTP-only cookie,
    NOT embedded in the state parameter.
    """
    from app.auth_google import generate_pkce_pair, get_google_auth_url

    code_verifier, code_challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(32)

    # Store code_verifier + state in signed HTTP-only cookie
    cookie_data = json.dumps({
        "cv": code_verifier,
        "st": state,
        "exp": time.time() + 600,  # 10 min expiry
    })
    signed = _sign_cookie(cookie_data)

    response.set_cookie(
        key="oauth_state",
        value=signed,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=600,
        path="/api/auth/google",
    )

    auth_url = get_google_auth_url(code_challenge, state=state)
    return RedirectResponse(url=auth_url)


@router.get("/google/callback")
def google_oauth_callback(
    request: Request,
    response: Response,
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_bound_db),
):
    """Handle Google OAuth callback.

    C7: Retrieves PKCE code_verifier from signed cookie, not from state.
    """
    if error:
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    # Retrieve and verify the signed cookie
    cookie_value = request.cookies.get("oauth_state")
    cookie_data_str = _verify_cookie(cookie_value) if cookie_value else None

    if not cookie_data_str:
        raise HTTPException(status_code=400, detail="Missing or invalid OAuth state cookie")

    try:
        cookie_data = json.loads(cookie_data_str)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Corrupt OAuth state cookie")

    # Check expiry
    if cookie_data.get("exp", 0) < time.time():
        raise HTTPException(status_code=400, detail="OAuth state expired")

    # Verify state matches
    if cookie_data.get("st") != state:
        raise HTTPException(status_code=400, detail="OAuth state mismatch")

    code_verifier = cookie_data.get("cv")
    if not code_verifier:
        raise HTTPException(status_code=400, detail="Missing PKCE verifier")

    # Exchange code for tokens
    from app.auth_google import exchange_code_for_tokens, verify_google_id_token

    try:
        tokens = exchange_code_for_tokens(code, code_verifier)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {e}")

    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(status_code=400, detail="No ID token received")

    try:
        claims = verify_google_id_token(id_token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"ID token verification failed: {e}")

    # Resolve or create user
    user, action = resolve_or_create_user(
        db=db,
        provider="google",
        provider_id=claims["sub"],
        email=claims.get("email", ""),
        email_verified=claims.get("email_verified", False),
        profile_data={
            "name": claims.get("name", ""),
            "picture": claims.get("picture", ""),
        },
    )

    db.commit()

    # Create fantasy team for new users (season auto-advances via get_current_season)
    if action == "created":
        from app.models import FantasyTeam
        ft = FantasyTeam(
            user_id=user.id,
            name=f"{user.username}'s Team",
            season=get_current_season(db),
            budget=90.0,
            budget_remaining=90.0,
            free_transfers=1,
            free_transfers_next_gw=1,
        )
        db.add(ft)
        db.commit()

    # Issue tokens
    access_token = create_access_token(user.id, user.username)
    refresh_token = create_refresh_token(
        user.id,
        user_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        db=db,
    )

    # Clear the OAuth cookie
    response.delete_cookie(key="oauth_state", path="/api/auth/google")

    # Set refresh token cookie
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=7 * 24 * 3600,
        path="/api/auth",
    )

    # Redirect to frontend with access token
    base_url = os.environ.get("APP_BASE_URL", "http://localhost:8000")
    redirect_url = f"{base_url}/my-team?token={access_token}"
    return RedirectResponse(url=redirect_url)


# --- Email verification ---

@router.post("/verify-email")
def request_email_verification(
    user: User = Depends(get_current_user_from_token),
    db: Session = Depends(get_bound_db),
):
    """Request an email verification email.

    H6: Currently logs the verification URL to stdout.
    TODO: Integrate a real email provider (SMTP, Resend, SendGrid).
    """
    if user.email_verified:
        return {"status": "already_verified"}

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    # Store verification token (reuse RefreshToken model or add a new one)
    # For now, store in a simple way
    from app.models import EmailVerificationToken
    ev = EmailVerificationToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db.add(ev)
    db.commit()

    base_url = os.environ.get("APP_BASE_URL", "http://localhost:8000")
    verify_url = f"{base_url}/api/auth/verify-email/{raw_token}"

    # H6: Log to stdout (replace with real email sending)
    print(f"[EMAIL VERIFICATION] To: {user.email} | URL: {verify_url}")

    return {
        "status": "verification_sent",
        "message": "Verification email sent (check server logs in development).",
    }


@router.get("/verify-email/{token}")
def verify_email(
    token: str,
    db: Session = Depends(get_bound_db),
):
    """Verify an email address using the token from the verification email."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    from app.models import EmailVerificationToken
    ev = db.query(EmailVerificationToken).filter(
        EmailVerificationToken.token_hash == token_hash,
        EmailVerificationToken.expires_at > datetime.now(timezone.utc),
        EmailVerificationToken.used == False,
    ).first()

    if not ev:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")

    user = db.query(User).filter(User.id == ev.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.email_verified = True
    ev.used = True
    db.commit()

    base_url = os.environ.get("APP_BASE_URL", "http://localhost:8000")
    return RedirectResponse(url=f"{base_url}/account?verified=true")


# --- Current user ---

@router.get("/me", response_model=UserResponse)
def get_me(user: User = Depends(get_current_user_from_token)):
    """Get the current authenticated user's profile."""
    return user

logger = logging.getLogger(__name__)
