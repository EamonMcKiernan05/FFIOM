"""Fantasy Football Isle of Man - Main application entry point."""
import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.database import init_db, init_binds
from app.scheduler import start_scheduler, shutdown_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    logger.info("Starting Fantasy Football IOM...")
    init_db()
    init_binds()
    start_scheduler()
    yield
    shutdown_scheduler()
    logger.info("Shutdown complete.")


app = FastAPI(
    title="Fantasy Football Isle of Man",
    description="FPL-style fantasy football for Isle of Man leagues",
    version="2.0.0",
    lifespan=lifespan,
)

# C5: Restrict CORS to the actual frontend origin (was wildcard + credentials)
_allowed_origin = os.environ.get("APP_BASE_URL", "http://localhost:8000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_allowed_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


# Import and include ALL routers
from app.routes import (
    players,
    teams,
    users,
    gameweeks,
    leaderboard,
    transfers,
    mini_leagues,
    h2h,
    prices,
    gameweek_recap,
    transfers_tracking,
    fixtures,
    team_value,
    gameweek_history,
    captain_hints,
    admin,
    notifications,
    h2h_bracket,
)
from app.routes import auth as auth_routes
from app.routes import account as account_routes

app.include_router(players.router)
app.include_router(teams.router)
app.include_router(users.router)
app.include_router(gameweeks.router)
app.include_router(leaderboard.router)
app.include_router(transfers.router)
app.include_router(mini_leagues.router)
app.include_router(h2h.router)
app.include_router(prices.router)
app.include_router(gameweek_recap.router)
app.include_router(transfers_tracking.router)
app.include_router(fixtures.router)
app.include_router(team_value.router)
app.include_router(gameweek_history.router)
app.include_router(captain_hints.router)
app.include_router(admin.router)
app.include_router(notifications.router)
app.include_router(h2h_bracket.router)
app.include_router(auth_routes.router)
app.include_router(account_routes.router)


# --- Page routes (server-rendered HTML) ---

# HTML shells must never be cached hard: they reference the JS/CSS bundle
# URLs, and a stale shell pins users to stale JS (the Aug 2026 transfers
# outage: browsers held a pre-fix pages.js for hours). no-cache forces a
# revalidation every visit; the static assets themselves keep their
# ?v=... cache-busting and 4h edge cache.
def _html_response(path: str) -> FileResponse:
    return FileResponse(
        path,
        headers={"Cache-Control": "no-cache, must-revalidate", "Vary": "Accept"},
    )


@app.get("/")
async def index(request: Request):
    return _html_response("static/index.html")


@app.get("/login")
async def login_page(request: Request):
    return _html_response("static/pages/login.html")


@app.get("/register")
async def register_page(request: Request):
    return _html_response("static/pages/register.html")


@app.get("/my-team")
async def my_team_page(request: Request):
    return _html_response("static/pages/my-team.html")


@app.get("/transfers")
async def transfers_page(request: Request):
    return _html_response("static/pages/transfers.html")


@app.get("/leaderboard")
async def leaderboard_page(request: Request):
    return _html_response("static/pages/leaderboard.html")


@app.get("/leagues")
async def leagues_page(request: Request):
    return _html_response("static/pages/leagues.html")


@app.get("/players")
async def players_page(request: Request):
    return _html_response("static/pages/players.html")


@app.get("/fixtures")
async def fixtures_page(request: Request):
    return _html_response("static/pages/fixtures.html")


@app.get("/dream-team")
async def dream_team_page(request: Request):
    return _html_response("static/pages/dream-team.html")


@app.get("/history")
async def history_page(request: Request):
    return _html_response("static/pages/history.html")


@app.get("/rankings")
async def rankings_page(request: Request):
    return _html_response("static/pages/rankings.html")


@app.get("/gameweeks")
async def gameweeks_page(request: Request):
    return _html_response("static/pages/gameweeks.html")


@app.get("/help")
async def help_page(request: Request):
    return _html_response("static/pages/help.html")


# --- API health/status ---

@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "fantasy-football-iom"}


@app.get("/api/gameweeks/current")
def get_current_gameweek():
    from app.database import get_bound_db
    from app.models import Gameweek
    db = next(get_bound_db())
    gw = db.query(Gameweek).filter(
        Gameweek.closed == False
    ).order_by(Gameweek.number.asc()).first()
    if not gw:
        return {"gameweek": None}
    return {
        "gameweek": {
            "id": gw.id,
            "number": gw.number,
            "season": gw.season,
            "deadline": gw.deadline.isoformat() if gw.deadline else None,
            "closed": gw.closed,
            "scored": gw.scored,
        }
    }
