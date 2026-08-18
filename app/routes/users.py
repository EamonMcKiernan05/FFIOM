"""User and Fantasy Team API routes.

All state-changing endpoints derive the user from the JWT token (C3 IDOR fix).
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Form, Header
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Optional, Annotated

from app.database import get_db, get_bound_db, get_current_season
from app.models import (
    User, FantasyTeam, SquadPlayer, Player, Gameweek,
    FantasyTeamHistory, Team,
)
from app.schemas import (
    UserCreate, UserResponse, FantasyTeamResponse, SquadPlayerResponse,
    ChipStatus, CaptainRequest, ChipRequest, PlayerHistoryEntry,
)
from app.scoring import (
    get_chip_status, activate_chip, cancel_chip, calculate_selling_price,
    auto_sub_squad, check_chip_availability,
)
from app.utils.passwords import hash_password, verify_password
from app.utils.squad import create_default_squad
from app.auth import create_access_token, get_current_user_from_token

router = APIRouter(prefix="/api/users", tags=["users"])


def _get_owned_team(db: Session, user: User, team_id: Optional[int] = None) -> FantasyTeam:
    """Get the authenticated user's fantasy team, with ownership check.

    If team_id is provided, verifies it belongs to the user.
    Otherwise returns the user's primary team.
    """
    query = db.query(FantasyTeam).filter(FantasyTeam.user_id == user.id)
    if team_id is not None:
        query = query.filter(FantasyTeam.id == team_id)
    ft = query.first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")
    return ft


@router.get("/me")
def get_current_user(
    user: User = Depends(get_current_user_from_token),
    db: Session = Depends(get_bound_db),
):
    """Get current user and their fantasy team (used by frontend)."""
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user.id).first()

    team_data = None
    if ft:
        current_gw = db.query(Gameweek).filter(
            Gameweek.closed == False
        ).order_by(Gameweek.number.asc()).first()
        team_data = {
            "id": ft.id,
            "user_id": ft.user_id,
            "name": ft.name,
            "season": ft.season,
            "budget": ft.budget,
            "budget_remaining": ft.budget_remaining,
            "total_points": ft.total_points,
            "overall_rank": ft.overall_rank,
            "league_rank": ft.league_rank,
            "free_transfers": ft.free_transfers,
            "free_transfers_next_gw": ft.free_transfers_next_gw,
            "current_gw_transfers": ft.current_gw_transfers,
            "transfer_deadline_exceeded": ft.transfer_deadline_exceeded,
            "active_chip": ft.active_chip,
            "supported_club_id": ft.supported_club_id,
            "supported_club_name": ft.supported_club.name if ft.supported_club else None,
            "chip_status": get_chip_status(ft, current_gw.number if current_gw else 1),
        }

    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        },
        "team": team_data,
    }


def _serialize_squad_player(sp):
    return {
        "id": sp.id,
        "player_id": sp.player_id,
        "player": {
            "id": sp.player.id,
            "name": sp.player.name,
            "team_id": sp.player.team_id,
            "price": sp.player.price,
            "team": {"id": sp.player.team.id, "name": sp.player.team.name} if sp.player.team else None,
            "is_injured": sp.player.is_injured,
            "injury_status": sp.player.injury_status,
            "form": sp.player.form,
            "selected_by_percent": sp.player.selected_by_percent,
            "total_points_season": sp.player.total_points_season,
        },
        "position_slot": sp.position_slot,
        "is_captain": sp.is_captain,
        "is_vice_captain": sp.is_vice_captain,
        "is_starting": sp.is_starting,
        "total_points": sp.total_points,
        "gw_points": sp.gw_points,
        "was_autosub": sp.was_autosub,
        "bench_priority": sp.bench_priority,
        "purchase_price": sp.purchase_price,
        "selling_price": sp.selling_price,
    }


@router.get("/squad")
def get_my_squad(
    user: User = Depends(get_current_user_from_token),
    db: Session = Depends(get_bound_db),
):
    """Get squad players for the authenticated user's fantasy team."""
    ft = _get_owned_team(db, user)
    squad = db.query(SquadPlayer).filter(SquadPlayer.fantasy_team_id == ft.id).all()
    return [_serialize_squad_player(sp) for sp in squad]


@router.get("/{user_id}/squad")
def get_squad_public(
    user_id: int,
    db: Session = Depends(get_bound_db),
):
    """Get squad players for a user's fantasy team (public read-only view)."""
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="Fantasy team not found")

    squad = db.query(SquadPlayer).filter(SquadPlayer.fantasy_team_id == ft.id).all()
    return [_serialize_squad_player(sp) for sp in squad]


@router.get("/chips")
def get_my_chips(
    user: User = Depends(get_current_user_from_token),
    db: Session = Depends(get_bound_db),
):
    """Return chip status for the authenticated user's team."""
    ft = _get_owned_team(db, user)
    types = ["wildcard", "free_hit", "bench_boost", "triple_captain"]
    out = []
    for t in types:
        used = getattr(ft, f"{t}_used", False)
        out.append({
            "type": t,
            "used": used,
            "active": ft.active_chip == t,
            "available": not used,
        })
    return out


@router.post("/chips/activate/{chip_type}")
def activate_chip_route(
    chip_type: str,
    user: User = Depends(get_current_user_from_token),
    db: Session = Depends(get_bound_db),
):
    """Activate a chip on the authenticated user's team."""
    ft = _get_owned_team(db, user)

    current_gw = db.query(Gameweek).filter(
        Gameweek.closed == False
    ).order_by(Gameweek.number.asc()).first()
    gw_num = current_gw.number if current_gw else 1

    available, message = check_chip_availability(ft, chip_type, gw_num)
    if not available:
        raise HTTPException(status_code=400, detail=message)

    success, message = activate_chip(ft, chip_type, gw_num)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    db.commit()
    return {"status": "activated", "message": message, "chip": chip_type}


@router.post("/chips/cancel/{chip_type}")
def cancel_chip_route(
    chip_type: str,
    user: User = Depends(get_current_user_from_token),
    db: Session = Depends(get_bound_db),
):
    """Cancel a chip on the authenticated user's team."""
    ft = _get_owned_team(db, user)

    if chip_type == "free_hit":
        raise HTTPException(status_code=400, detail="Free Hit cannot be cancelled once confirmed")

    current_gw = db.query(Gameweek).filter(
        Gameweek.closed == False
    ).order_by(Gameweek.number.asc()).first()
    gw_num = current_gw.number if current_gw else 1

    success, message = cancel_chip(ft, chip_type, gw_num)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    db.commit()
    return {"status": "cancelled", "message": message, "chip": chip_type}


@router.post("/captain/{squad_id}")
def set_captain_by_squad(
    squad_id: int,
    user: User = Depends(get_current_user_from_token),
    db: Session = Depends(get_bound_db),
):
    """Set captain on the authenticated user's team."""
    ft = _get_owned_team(db, user)

    target = db.query(SquadPlayer).filter(
        SquadPlayer.id == squad_id,
        SquadPlayer.fantasy_team_id == ft.id,
    ).first()
    if not target:
        raise HTTPException(status_code=400, detail="Player not in your squad")
    if not target.is_starting:
        raise HTTPException(status_code=400, detail="Captain must be in starting XI")

    squad = db.query(SquadPlayer).filter(SquadPlayer.fantasy_team_id == ft.id).all()
    for sp in squad:
        if sp.id != squad_id and sp.is_captain:
            sp.is_captain = False
        if sp.id == squad_id and sp.is_vice_captain:
            sp.is_vice_captain = False
    target.is_captain = True
    db.commit()
    return {"status": "ok", "captain_id": squad_id}


@router.post("/vice-captain/{squad_id}")
def set_vice_captain_by_squad(
    squad_id: int,
    user: User = Depends(get_current_user_from_token),
    db: Session = Depends(get_bound_db),
):
    """Set vice-captain on the authenticated user's team."""
    ft = _get_owned_team(db, user)

    target = db.query(SquadPlayer).filter(
        SquadPlayer.id == squad_id,
        SquadPlayer.fantasy_team_id == ft.id,
    ).first()
    if not target:
        raise HTTPException(status_code=400, detail="Player not in your squad")
    if not target.is_starting:
        raise HTTPException(status_code=400, detail="Vice-captain must be in starting XI")

    squad = db.query(SquadPlayer).filter(SquadPlayer.fantasy_team_id == ft.id).all()
    for sp in squad:
        if sp.id != squad_id and sp.is_vice_captain:
            sp.is_vice_captain = False
        if sp.id == squad_id and sp.is_captain:
            sp.is_captain = False
    target.is_vice_captain = True
    db.commit()
    return {"status": "ok", "vice_captain_id": squad_id}


@router.post("/squad/{squad_id}/bench")
def bench_squad_player(
    squad_id: int,
    user: User = Depends(get_current_user_from_token),
    db: Session = Depends(get_bound_db),
):
    """Move a player to the bench, swapping with the highest-priority bench player."""
    ft = _get_owned_team(db, user)

    sp = db.query(SquadPlayer).filter(
        SquadPlayer.id == squad_id,
        SquadPlayer.fantasy_team_id == ft.id,
    ).first()
    if not sp:
        raise HTTPException(status_code=400, detail="Player not in squad")
    if not sp.is_starting:
        return {"status": "noop", "message": "Already on bench"}

    squad = db.query(SquadPlayer).filter(SquadPlayer.fantasy_team_id == ft.id).all()

    # Pick the highest-priority bench player (any position)
    bench = sorted(
        [b for b in squad if not b.is_starting],
        key=lambda b: b.bench_priority or 99,
    )

    if not bench:
        raise HTTPException(status_code=400, detail="No bench players available")

    candidate = bench[0]

    sp.is_starting = False
    candidate.is_starting = True
    if sp.is_captain:
        sp.is_captain = False
        candidate.is_captain = True
    if sp.is_vice_captain:
        sp.is_vice_captain = False
        candidate.is_vice_captain = True
    db.commit()
    return {"status": "ok", "benched": squad_id, "promoted": candidate.id}


@router.post("/squad/{squad_id}/start")
def start_squad_player(
    squad_id: int,
    user: User = Depends(get_current_user_from_token),
    db: Session = Depends(get_bound_db),
):
    """Promote a benched player to start, swapping with the lowest-scoring starter."""
    ft = _get_owned_team(db, user)

    sp = db.query(SquadPlayer).filter(
        SquadPlayer.id == squad_id,
        SquadPlayer.fantasy_team_id == ft.id,
    ).first()
    if not sp:
        raise HTTPException(status_code=400, detail="Player not in squad")
    if sp.is_starting:
        return {"status": "noop", "message": "Already starting"}

    squad = db.query(SquadPlayer).filter(SquadPlayer.fantasy_team_id == ft.id).all()
    starters = [s for s in squad if s.is_starting]

    if not starters:
        raise HTTPException(status_code=400, detail="No starters to swap with")

    # Drop the lowest-scoring starter (any position)
    candidate = min(starters, key=lambda s: s.gw_points or 0)

    sp.is_starting = True
    candidate.is_starting = False
    if candidate.is_captain:
        candidate.is_captain = False
        sp.is_captain = True
    if candidate.is_vice_captain:
        candidate.is_vice_captain = False
        sp.is_vice_captain = True
    db.commit()
    return {"status": "ok", "promoted": squad_id, "benched": candidate.id}


@router.post("/register")
def register(user: UserCreate, db: Session = Depends(get_bound_db)):
    """Register a new user, create their fantasy team, and return an auth token.

    DEPRECATED: Use /api/auth/register instead. Kept for backward compatibility.
    """
    existing = db.query(User).filter(
        or_(User.username == user.username, User.email == user.email)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email taken")

    new_user = User(
        username=user.username,
        email=user.email,
        password_hash=hash_password(user.password),
        email_verified=False,
        display_name=user.username,
    )
    db.add(new_user)
    db.flush()

    # Create email identity
    from app.auth_linking import create_email_identity
    create_email_identity(db, new_user.id, user.email)

    team_name = (user.team_name or f"{user.username}'s Team").strip()
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
    db.commit()
    db.refresh(ft)

    return {
        "access_token": create_access_token(new_user.id, new_user.username),
        "token_type": "bearer",
        "user": {
            "id": new_user.id,
            "username": new_user.username,
            "email": new_user.email,
            "created_at": new_user.created_at.isoformat() if new_user.created_at else None,
        },
        "team": {
            "id": ft.id,
            "user_id": ft.user_id,
            "name": ft.name,
            "budget_remaining": ft.budget_remaining,
            "season": ft.season,
        },
    }


@router.post("/login")
def login(username: Annotated[str, Form()], password: Annotated[str, Form()], db: Session = Depends(get_bound_db)):
    """Login a user and return a JWT access token.

    DEPRECATED: Use /api/auth/login instead. Kept for backward compatibility.
    """
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return {
        "access_token": create_access_token(user.id, user.username),
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }
    }


@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: int, db: Session = Depends(get_bound_db)):
    """Get user details (public profile)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# --- Fantasy Team routes ---

@router.get("/{user_id}/team", response_model=dict)
def get_fantasy_team(user_id: int, db: Session = Depends(get_bound_db)):
    """Get a user's fantasy team with full squad (public read-only view)."""
    ft = db.query(FantasyTeam).filter(FantasyTeam.user_id == user_id).first()
    if not ft:
        raise HTTPException(status_code=404, detail="No fantasy team found")

    squad = db.query(SquadPlayer).filter(
        SquadPlayer.fantasy_team_id == ft.id
    ).all()

    # Get current gameweek number for chip status
    current_gw = db.query(Gameweek).filter(
        Gameweek.closed == False
    ).order_by(Gameweek.number.asc()).first()

    return {
        "id": ft.id,
        "name": ft.name,
        "total_points": ft.total_points,
        "overall_rank": ft.overall_rank,
        "league_rank": ft.league_rank,
        "free_transfers": ft.free_transfers,
        "free_transfers_next_gw": ft.free_transfers_next_gw,
        "budget_remaining": ft.budget_remaining,
        "current_gw_transfers": ft.current_gw_transfers,
        "transfer_deadline_exceeded": ft.transfer_deadline_exceeded,
        "season": ft.season,
        "supported_club_id": ft.supported_club_id,
        "supported_club_name": ft.supported_club.name if ft.supported_club else None,
        "chip_status": get_chip_status(ft, current_gw.number if current_gw else 1),
        "squad": [
            {
                "id": sp.id,
                "player_id": sp.player_id,
                "player": {
                    "id": sp.player.id,
                    "name": sp.player.name,
                    "team_id": sp.player.team_id,
                    "price": sp.player.price,
                },
                "position_slot": sp.position_slot,
                "is_captain": sp.is_captain,
                "is_vice_captain": sp.is_vice_captain,
                "is_starting": sp.is_starting,
                "total_points": sp.total_points,
                "gw_points": sp.gw_points,
                "was_autosub": sp.was_autosub,
                "bench_priority": sp.bench_priority,
                "purchase_price": sp.purchase_price,
            }
            for sp in squad
        ],
    }


@router.post("/team/create", response_model=dict)
def create_fantasy_team(
    team_name: str = "My Team",
    user: User = Depends(get_current_user_from_token),
    db: Session = Depends(get_bound_db),
):
    """Create a new fantasy team for the authenticated user."""
    # Check if team already exists
    existing = db.query(FantasyTeam).filter(
        FantasyTeam.user_id == user.id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Team already exists")

    ft = FantasyTeam(
        user_id=user.id,
        name=team_name,
        season=get_current_season(db),
        budget=90.0,
        budget_remaining=90.0,
        free_transfers=1,
        free_transfers_next_gw=1,
    )
    db.add(ft)
    db.commit()
    db.refresh(ft)

    return {
        "id": ft.id,
        "user_id": ft.user_id,
        "name": ft.name,
        "budget_remaining": ft.budget_remaining,
        "season": ft.season,
    }
