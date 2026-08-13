"""Database configuration for Fantasy Football Isle of Man.

Dual-database setup:
- Game DB (default): user accounts, fantasy teams, transfers, mini-leagues
- FFIOM-DB (read): player stats, prices, fixtures (source of truth)
"""
import os
import logging
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, declarative_base

logger = logging.getLogger(__name__)

# Database URLs
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./data/fantasy_iom.db")
FFIOM_DB_PATH = os.environ.get("FFIOM_DB_PATH", "")

# Game DB engine (user data, fantasy teams)
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)

# Enable WAL mode for better concurrent read performance
# NOTE: PRAGMA foreign_keys must stay OFF on the game DB. Player/Team/
# Gameweek/Fixture rows live in FFIOM-DB (a separate SQLite file), so the
# game DB's `players` table is always empty and any FK to players.id can
# never be satisfied here. Enforcing FKs turns every squad/transfer write
# into an IntegrityError (see transfers page bug, Aug 2026).
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# FFIOM-DB session (read-only player/fixture data)
FfiomSessionLocal = None
ffiom_engine = None

# Bound session that can access both DBs via SQLAlchemy binds
BoundSessionLocal = None


def init_binds():
    """Initialize the bound session with FFIOM-DB model binds.

    Routes Player/Team/Gameweek/Fixture models to the FFIOM-DB engine
    and all other models to the game DB engine.
    """
    global BoundSessionLocal, FfiomSessionLocal, ffiom_engine

    if not FFIOM_DB_PATH or not os.path.exists(FFIOM_DB_PATH):
        logger.warning(f"FFIOM-DB not found at {FFIOM_DB_PATH}, using game DB only")
        BoundSessionLocal = SessionLocal
        return

    # Create the FFIOM-DB engine
    ffiom_engine = create_engine(
        f"sqlite:///{FFIOM_DB_PATH}",
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )
    FfiomSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=ffiom_engine
    )

    # Configure model-to-engine binds
    from app import models  # noqa: F401

    binds = {
        models.Player: ffiom_engine,
        models.Team: ffiom_engine,
        models.Gameweek: ffiom_engine,
        models.Fixture: ffiom_engine,
    }

    BoundSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine, binds=binds
    )

    logger.info(f"FFIOM-DB binds configured from {FFIOM_DB_PATH}")


def get_db():
    """Get a game DB session (user data only)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_bound_db():
    """Get a bound DB session (game DB + FFIOM-DB binds).

    Player/Team/Gameweek/Fixture queries route to FFIOM-DB.
    All other models use the game DB.
    """
    if BoundSessionLocal is None:
        init_binds()
    db = BoundSessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_ffiom_db():
    """Get a read-only FFIOM-DB session."""
    if FfiomSessionLocal is None:
        init_binds()
    if FfiomSessionLocal is None:
        yield from get_db()
        return
    db = FfiomSessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize the game database schema."""
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    logger.info("Game database initialized")


def _safe_drop_all():
    """M3: Guarded drop_all using env var instead of stack inspection."""
    if os.environ.get("ALLOW_DB_DROP", "").lower() not in ("true", "1", "yes"):
        raise RuntimeError(
            "drop_all is disabled. Set ALLOW_DB_DROP=true to enable (test environments only)."
        )
    Base.metadata.drop_all(bind=engine)
    logger.warning("All tables dropped (ALLOW_DB_DROP was set)")


Base.metadata._original_drop_all = Base.metadata.drop_all
Base.metadata.drop_all = lambda *a, **kw: _safe_drop_all()


def get_current_season(db=None):
    """Return the most recent season that has gameweeks (e.g. '2026-27').

    Used as the default season for read endpoints so the UI auto-advances to
    the active season instead of a hardcoded value that goes stale.

    Queries via the Gameweek model so the FFIOM-DB bind routing applies
    (a raw text() query would hit the empty game DB).
    """
    from sqlalchemy import func
    from app.models import Gameweek

    owns_session = db is None
    if owns_session:
        if BoundSessionLocal is None:
            init_binds()
        db = BoundSessionLocal()
    try:
        season = db.query(func.max(Gameweek.season)).scalar()
        return season or "2025-26"
    finally:
        if owns_session:
            db.close()
