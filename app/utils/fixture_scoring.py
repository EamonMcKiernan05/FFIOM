"""Fixture scoring utilities - shared between scheduler and gameweek routes."""
import random
from datetime import timedelta
from typing import Optional

from app.models import Fixture, Player, PlayerGameweekPoints, Team
from app.scoring import calculate_player_points


def generate_player_points_for_fixture(
    db, gw_id: int, fixture,
):
    """Generate PlayerGameweekPoints for a single played fixture.
    
    Handles both normal fixtures and walkovers.
    Returns count of new PGP records created.
    """
    is_walkover = fixture.home_score is None or fixture.away_score is None
    
    if is_walkover:
        return _generate_walkover_points(db, gw_id, fixture)
    return _generate_fixture_points(db, gw_id, fixture)


def _generate_walkover_points(db, gw_id: int, fixture) -> int:
    """Award walkover points (2 pts) to all players of both teams."""
    home_team = db.query(Team).filter(Team.name == fixture.home_team_name).first()
    away_team = db.query(Team).filter(Team.name == fixture.away_team_name).first()
    created = 0
    
    for team, is_home in [(home_team, True), (away_team, False)]:
        if not team:
            continue
        
        team_players = db.query(Player).filter(
            Player.team_id == team.id,
            Player.is_active == True,
        ).all()
        
        opponent = fixture.away_team_name if is_home else fixture.home_team_name
        
        for player in team_players:
            existing = db.query(PlayerGameweekPoints).filter(
                PlayerGameweekPoints.player_id == player.id,
                PlayerGameweekPoints.gameweek_id == gw_id,
            ).first()
            if existing:
                continue
            
            pgp = PlayerGameweekPoints(
                player_id=player.id,
                gameweek_id=gw_id,
                opponent_team=opponent,
                was_home=is_home,
                minutes_played=0,
                did_play=True,
                goals_scored=0,
                clean_sheet=False,
                goals_conceded=0,
                base_points=2,
                total_points=2,
                bps_score=0,
            )
            db.add(pgp)
            created += 1
    
    return created


def _generate_fixture_points(db, gw_id: int, fixture) -> int:
    """Generate PlayerGameweekPoints for a normal fixture with scores.
    
    Simulates individual player stats based on team-level data
    (goals, assists, minutes, saves) since FullTime API only gives team scores.
    Returns count of new PGP records created.
    """
    created = 0
    
    for team_id, goals_scored, goals_conceded, is_home in [
        (fixture.home_team_id, fixture.home_score or 0, fixture.away_score or 0, True),
        (fixture.away_team_id, fixture.away_score or 0, fixture.home_score or 0, False),
    ]:
        if team_id is None:
            continue
        
        team_players = db.query(Player).filter(
            Player.team_id == team_id,
            Player.is_active == True,
        ).all()
        
        for player in team_players:
            existing = db.query(PlayerGameweekPoints).filter(
                PlayerGameweekPoints.player_id == player.id,
                PlayerGameweekPoints.gameweek_id == gw_id,
            ).first()
            if existing:
                continue
            
            apps = player.apps or 1
            player_goals = max(0, int((player.goals or 0) * (goals_scored / max(5, player.goals or 5))))
            player_assists = max(0, int((player.assists or 0) * (goals_scored / 5)))
            player_goals = min(player_goals, goals_scored)
            player_assists = min(player_assists, goals_scored)
            
            clean_sheet = (goals_conceded == 0)
            saves = max(2, goals_conceded + random.randint(1, 4)) if goals_conceded else random.randint(0, 3)

            minutes = 90 if random.random() < 0.8 else random.choice([30, 45, 60, 75])

            points = calculate_player_points(
                goals_scored=player_goals,
                assists=player_assists,
                clean_sheet=clean_sheet,
                goals_conceded=goals_conceded,
                saves=saves,
                minutes_played=minutes,
                bonus_points=0,
            )
            
            opponent = fixture.away_team_name if is_home else fixture.home_team_name
            
            pgp = PlayerGameweekPoints(
                player_id=player.id,
                gameweek_id=gw_id,
                opponent_team=opponent,
                was_home=is_home,
                minutes_played=minutes,
                did_play=True,
                goals_scored=player_goals,
                assists=player_assists,
                clean_sheet=clean_sheet,
                goals_conceded=goals_conceded,
                saves=saves,
                base_points=points,
                total_points=points,
                bps_score=0,
                influence_gw=round(random.uniform(5, 25), 1),
                creativity_gw=round(random.uniform(5, 25), 1),
                threat_gw=round(random.uniform(5, 30), 1),
            )
            db.add(pgp)
            created += 1
    
    return created


def score_fixtures_for_gameweek(db, gw_id: int) -> dict:
    """Score all played fixtures for a gameweek.
    
    Generates PlayerGameweekPoints for all played fixtures.
    Returns dict with counts.
    """
    fixtures = db.query(Fixture).filter(
        Fixture.gameweek_id == gw_id,
        Fixture.played == True,
    ).all()
    
    if not fixtures:
        return {"player_points_created": 0, "walkover_fixtures": 0}
    
    created = 0
    walkover_count = 0
    
    for fixture in fixtures:
        is_walkover = fixture.home_score is None or fixture.away_score is None
        if is_walkover:
            walkover_count += 1
        
        result = generate_player_points_for_fixture(db, gw_id, fixture)
        created += result
    
    db.flush()
    return {"player_points_created": created, "walkover_fixtures": walkover_count}


def format_countdown(td: Optional[timedelta], label: str = "Deadline") -> str:
    """Format a timedelta as a countdown string.
    
    Shared between gameweeks.py and gameweek_history.py to avoid duplication.
    
    Args:
        td: Time delta or None
        label: Label for the expired state
    
    Returns:
        Formatted string like "2d 3h 15m" or "Expired"
    """
    if td is None or td.total_seconds() < 0:
        return f"{label} passed"
    
    total_seconds = int(td.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    
    return " ".join(parts)
