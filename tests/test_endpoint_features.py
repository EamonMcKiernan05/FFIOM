"""Integration tests for new FPL features - endpoints.

Tests for:
- Notifications endpoint
- H2H leagues
- Team details update
- Scoring progress
- Chip activation/cancellation
"""
import pytest
from datetime import datetime, date, timedelta

from app.models import User, FantasyTeam, Gameweek, Fixture, MiniLeague, MiniLeagueMember, Chip, PlayerGameweekPoints, FantasyTeamHistory


class TestNotificationsEndpoint:
    """Test notifications endpoint - returns dynamic notifications."""

    def test_get_notifications_empty(self, client, test_db):
        """Get notifications returns empty list when no data exists."""
        db, session = test_db
        user = User(username="testuser", email="test@test.com", password_hash="hashed")
        session.add(user)
        session.flush()
        team = FantasyTeam(user=user, name="Test Team", season="2025-26")
        session.add(team)
        session.commit()

        from app.auth import create_access_token
        token = create_access_token(user.id, user.username)
        response = client.get("/api/notifications", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        data = response.json()
        assert "notifications" in data
        assert "total_count" in data

    def test_get_notifications_with_gw_history(self, client, test_db):
        """Notifications include GW result notifications."""
        db, session = test_db
        user = User(username="testuser", email="test@test.com", password_hash="hashed")
        session.add(user)
        session.flush()
        team = FantasyTeam(user=user, name="Test Team", season="2025-26")
        gw = Gameweek(number=1, season="2025-26", start_date=date(2025, 8, 1),
                      deadline=datetime(2025, 8, 7, 11, 30), closed=True, scored=True)
        session.add_all([team, gw])
        session.flush()

        history = FantasyTeamHistory(fantasy_team=team, gameweek=gw, points=65, total_points=65, rank=1)
        session.add(history)
        session.commit()

        from app.auth import create_access_token
        token = create_access_token(user.id, user.username)
        response = client.get("/api/notifications", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        data = response.json()
        assert "notifications" in data

    def test_mark_all_notifications_read(self, client, test_db):
        """Mark all notifications as read."""
        db, session = test_db
        user = User(username="testuser", email="test@test.com", password_hash="hashed")
        session.add(user)
        session.flush()
        team = FantasyTeam(user=user, name="Test Team", season="2025-26")
        session.add(team)
        session.commit()

        from app.auth import create_access_token
        token = create_access_token(user.id, user.username)
        response = client.post("/api/notifications/mark-all-read", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "all_marked_read"

    def test_get_upcoming_deadlines(self, client, test_db):
        """Get upcoming deadlines."""
        db, session = test_db
        future_deadline = datetime.now() + timedelta(days=7)
        gw = Gameweek(number=1, season="2025-26", start_date=date(2025, 8, 1),
                      deadline=future_deadline, closed=False)
        session.add(gw)
        session.commit()

        response = client.get("/api/notifications/upcoming-deadlines")
        assert response.status_code == 200
        data = response.json()
        assert "upcoming_deadlines" in data


class TestGameweekRecapEndpoint:
    """Test gameweek recap endpoint."""

    def test_gameweek_recap_not_found(self, client, test_db):
        """GW recap returns 404 for non-existent gameweek."""
        response = client.get("/api/gameweeks/99999/recap")
        assert response.status_code == 404

    def test_current_gw_info(self, client, test_db):
        """Get current gameweek info."""
        db, session = test_db
        future_deadline = datetime.now() + timedelta(days=7)
        gw = Gameweek(number=1, season="2025-26", start_date=date(2025, 8, 1),
                      deadline=future_deadline, closed=False)
        session.add(gw)
        session.commit()

        response = client.get("/api/gameweek-history/current-gw-info")
        assert response.status_code == 200
        data = response.json()
        assert "gameweek_number" in data
        assert data["gameweek_number"] == 1


class TestH2HLeaguesEndpoint:
    """Test H2H leagues endpoint."""

    def test_h2h_leagues_empty(self, client, test_db):
        """List H2H leagues returns empty when none exist."""
        response = client.get("/api/h2h/leagues")
        assert response.status_code == 200
        data = response.json()
        assert "leagues" in data
        assert len(data["leagues"]) == 0

    def test_create_h2h_league(self, client, test_db):
        """Create an H2H league (C2: requires auth; admin = caller)."""
        db, session = test_db
        user = User(username="h2hcreator", email="h2hc@test.com", password_hash="hashed")
        session.add(user)
        session.flush()
        team = FantasyTeam(user=user, name="Creator FC", season="2025-26")
        session.add(team)
        session.commit()

        from app.auth import create_access_token
        token = create_access_token(user.id, user.username)

        response = client.post(
            "/api/h2h/leagues?name=Test+H2H+League&format_type=knockout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "league_id" in data
        assert data["name"] == "Test H2H League"
        assert data["format_type"] == "knockout"

        from app.models import H2hLeague
        league = session.query(H2hLeague).filter(H2hLeague.id == data["league_id"]).first()
        assert league.admin_user_id == user.id

    def test_h2h_bracket_not_found(self, client, test_db):
        """H2H bracket returns 404 for non-existent league."""
        response = client.get("/api/h2h-bracket/99999")
        assert response.status_code == 404


class TestTeamDetailsEndpoint:
    """Test team details edit endpoint."""

    def test_update_team_name(self, client, test_db):
        """Team-name mutator via user_id param was removed in the auth remediation;
        profile updates go through /api/account (token-scoped)."""
        db, session = test_db
        user = User(username="testuser", email="test@test.com", password_hash="hashed")
        session.add(user)
        session.flush()
        team = FantasyTeam(user=user, name="Test Team", season="2025-26")
        session.add(team)
        session.commit()

        from app.auth import create_access_token
        token = create_access_token(user.id, user.username)
        response = client.put(
            "/api/account",
            json={"display_name": "New Team Name"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["user"]["display_name"] == "New Team Name"

    def test_get_team_details(self, client, test_db):
        """Get team details."""
        db, session = test_db
        user = User(username="testuser", email="test@test.com", password_hash="hashed")
        session.add(user)
        session.flush()
        team = FantasyTeam(user=user, name="Test Team", season="2025-26")
        session.add(team)
        session.commit()

        response = client.get(f"/api/users/{user.id}/team")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Team"


class TestScoringProgressEndpoint:
    """Test scoring progress in gameweek data."""

    def test_scoring_progress_in_gameweek(self, client, test_db):
        """Scoring progress returned in gameweek data."""
        db, session = test_db
        future_deadline = datetime.now() + timedelta(days=7)
        gw = Gameweek(number=1, season="2025-26", start_date=date(2025, 8, 1),
                      deadline=future_deadline, closed=False)
        session.add(gw)
        session.flush()

        # Create fixtures (2 played, 2 not)
        for i in range(4):
            fix = Fixture(gameweek=gw, home_team_name=f"Home {i}",
                          away_team_name=f"Away {i}", played=(i < 2),
                          date=future_deadline)
            session.add(fix)
        session.commit()

        # Get current gameweek which includes scoring_progress
        response = client.get("/api/gameweeks/current")
        assert response.status_code == 200
        data = response.json()
        assert "scoring_progress" in data
        assert data["scoring_progress"]["total_fixtures"] == 4
        assert data["scoring_progress"]["completed_fixtures"] == 2
        assert data["scoring_progress"]["percentage"] == 50.0


class TestChipEndpoint:
    """Test chip activation/cancellation endpoints."""

    def test_activate_chip(self, client, test_db):
        """Activate a chip."""
        db, session = test_db
        user = User(username="testuser", email="test@test.com", password_hash="hashed")
        session.add(user)
        session.flush()
        team = FantasyTeam(user=user, name="Test Team", season="2025-26")
        gw = Gameweek(number=1, season="2025-26", start_date=date(2025, 8, 1),
                      deadline=datetime.now() + timedelta(days=7), closed=False)
        session.add_all([team, gw])
        session.commit()

        from app.auth import create_access_token
        token = create_access_token(user.id, user.username)
        response = client.post(
            "/api/users/chips/activate/wildcard",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

    def test_get_chips(self, client, test_db):
        """Get chip status for user."""
        db, session = test_db
        user = User(username="testuser", email="test@test.com", password_hash="hashed")
        session.add(user)
        session.flush()
        team = FantasyTeam(user=user, name="Test Team", season="2025-26")
        session.add(team)
        session.commit()

        from app.auth import create_access_token
        token = create_access_token(user.id, user.username)
        response = client.get("/api/users/chips", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        chips = response.json()
        chips_list = chips["chips"] if isinstance(chips, dict) and "chips" in chips else chips
        assert isinstance(chips_list, list) and len(chips_list) >= 1
        assert all("type" in c for c in chips_list)


class TestC1AdminGating:
    """C1 fix: state-mutating gameworld endpoints require an admin token."""

    def test_mutators_reject_anonymous(self, client):
        for method, path in [
            ("post", "/api/gameweeks/create"),
            ("post", "/api/gameweeks/1/simulate-results"),
            ("post", "/api/gameweeks/1/close"),
            ("post", "/api/gameweeks/1/score"),
            ("post", "/api/gameweeks/1/update-scores"),
            ("post", "/api/gameweeks/simulate-and-score"),
            ("post", "/api/leaderboard/calculate-ranks"),
            ("post", "/api/fixtures/calculate-difficulties"),
            ("post", "/api/players/sync"),
            ("post", "/api/prices/process-price-changes"),
        ]:
            r = getattr(client, method)(path)
            assert r.status_code in (401, 403), f"{path} -> {r.status_code}"

    def test_non_admin_rejected(self, client, test_db):
        db, session = test_db
        user = User(username="pleb", email="pleb@test.com", password_hash="hashed")
        session.add(user)
        session.commit()
        from app.auth import create_access_token
        token = create_access_token(user.id, user.username)
        r = client.post("/api/gameweeks/create?number=99", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403


class TestC2H2hAuth:
    """C2 fix: H2H module derives identity from token, join is real, fixtures gated."""

    def _mk_user_team(self, session, username):
        user = User(username=username, email=f"{username}@test.com", password_hash="hashed")
        session.add(user)
        session.flush()
        team = FantasyTeam(user=user, name=f"{username} FC", season="2025-26")
        session.add(team)
        session.commit()
        from app.auth import create_access_token
        return user, team, create_access_token(user.id, user.username)

    def test_create_requires_auth(self, client):
        r = client.post("/api/h2h/leagues?name=Test")
        assert r.status_code in (401, 403)

    def test_create_sets_admin_to_caller(self, client, test_db):
        db, session = test_db
        user, team, token = self._mk_user_team(session, "h2hadmin")
        r = client.post("/api/h2h/leagues?name=LeagueX",
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        from app.models import H2hLeague, H2hParticipant
        league = session.query(H2hLeague).filter(H2hLeague.name == "LeagueX").first()
        assert league.admin_user_id == user.id
        # creator auto-joins as participant
        p = session.query(H2hParticipant).filter(
            H2hParticipant.h2h_league_id == league.id,
            H2hParticipant.fantasy_team_id == team.id,
        ).first()
        assert p is not None

    def test_join_is_real_and_needs_code(self, client, test_db):
        db, session = test_db
        admin, _, atoken = self._mk_user_team(session, "h2hadmin2")
        joiner, jteam, jtoken = self._mk_user_team(session, "h2hjoiner")
        created = client.post("/api/h2h/leagues?name=LeagueY",
                              headers={"Authorization": f"Bearer {atoken}"}).json()

        # wrong code rejected
        r = client.post(f"/api/h2h/leagues/{created['league_id']}/join?code=WRONG",
                        headers={"Authorization": f"Bearer {jtoken}"})
        assert r.status_code == 403

        from app.models import H2hParticipant
        before = session.query(H2hParticipant).filter(
            H2hParticipant.h2h_league_id == created["league_id"]).count()
        r = client.post(f"/api/h2h/leagues/{created['league_id']}/join?code={created['code']}",
                        headers={"Authorization": f"Bearer {jtoken}"})
        assert r.status_code == 200
        after = session.query(H2hParticipant).filter(
            H2hParticipant.h2h_league_id == created["league_id"]).count()
        assert after == before + 1

    def test_generate_fixtures_admin_only(self, client, test_db):
        db, session = test_db
        admin, _, atoken = self._mk_user_team(session, "h2hadmin3")
        other, _, otoken = self._mk_user_team(session, "h2hother")
        created = client.post("/api/h2h/leagues?name=LeagueZ",
                              headers={"Authorization": f"Bearer {atoken}"}).json()
        r = client.post(f"/api/h2h/leagues/{created['league_id']}/generate-fixtures",
                        headers={"Authorization": f"Bearer {otoken}"})
        assert r.status_code == 403

    def test_my_matches_rejects_anonymous(self, client):
        r = client.get("/api/h2h/leagues/1/my-matches")
        assert r.status_code in (401, 403)


class TestC7IdorScoping:
    """C7 fix: private data requires the owner's token."""

    def _mk(self, session, username):
        user = User(username=username, email=f"{username}@test.com", password_hash="hashed")
        session.add(user)
        session.flush()
        team = FantasyTeam(user=user, name=f"{username} FC", season="2025-26")
        session.add(team)
        session.commit()
        from app.auth import create_access_token
        return user, team, create_access_token(user.id, user.username)

    def test_public_user_profile_has_no_email(self, client, test_db):
        db, session = test_db
        user, _, _ = self._mk(session, "profileuser")
        r = client.get(f"/api/users/{user.id}")
        assert r.status_code == 200
        assert "email" not in r.json()
        assert "email_verified" not in r.json()

    def test_transfer_history_requires_owner(self, client, test_db):
        db, session = test_db
        owner, team, otok = self._mk(session, "histowner")
        other, _, xtok = self._mk(session, "histother")

        # anonymous
        assert client.get(f"/api/gameweek-history/transfer-history/{team.id}").status_code in (401, 403)
        # non-owner
        r = client.get(f"/api/gameweek-history/transfer-history/{team.id}",
                       headers={"Authorization": f"Bearer {xtok}"})
        assert r.status_code == 403
        # owner OK
        r = client.get(f"/api/gameweek-history/transfer-history/{team.id}",
                       headers={"Authorization": f"Bearer {otok}"})
        assert r.status_code == 200

    def test_gw_breakdown_requires_owner(self, client, test_db):
        db, session = test_db
        owner, team, otok = self._mk(session, "gwowner")
        other, _, xtok = self._mk(session, "gwother")
        from app.models import Gameweek
        gw = Gameweek(number=1, season="2025-26", start_date=date(2025, 8, 1),
                      deadline=datetime.now() + timedelta(days=7), closed=False)
        session.add(gw)
        session.commit()

        r = client.get(f"/api/gameweek-history/{team.id}/{gw.id}",
                       headers={"Authorization": f"Bearer {xtok}"})
        assert r.status_code == 403

    def test_captain_hints_requires_owner(self, client, test_db):
        db, session = test_db
        owner, _, otok = self._mk(session, "capowner")
        other, _, xtok = self._mk(session, "capother")

        r = client.get(f"/api/captain/hints/{owner.id}",
                       headers={"Authorization": f"Bearer {xtok}"})
        assert r.status_code == 403


class TestC8SquadRules:
    """C8 fix: registration creates a default squad; adds consume transfers."""

    def _register(self, client, username, with_players=True):
        """Register via the API. If with_players, seed active players first."""
        r = client.post("/api/auth/register", json={
            "username": username,
            "email": f"{username}@test.com",
            "password": "Passw0rdSecure!",
        })
        assert r.status_code == 200, r.text
        return r.json()

    def test_registration_creates_default_squad(self, client, test_db):
        db, session = test_db
        # Seed enough cheap active players for a 13-man squad
        from app.models import Player
        for i in range(15):
            session.add(Player(name=f"P{i}", team_id=1 if i < 3 else 2,
                               price=1.0, is_active=True))
        session.commit()

        data = self._register(client, "squaduser")
        assert data.get("team"), "registration should return team payload"

        token = data["access_token"]
        squad = client.get("/api/users/squad",
                           headers={"Authorization": f"Bearer {token}"}).json()
        players = squad if isinstance(squad, list) else squad.get("squad", [])
        assert len(players) > 0, "default squad should be created at registration"

    def test_add_player_consumes_transfer_and_enforces_max(self, client, test_db):
        db, session = test_db
        user = User(username="adduser", email="add@test.com", password_hash="hashed")
        session.add(user)
        session.flush()
        team = FantasyTeam(user=user, name="Add FC", season="2025-26",
                           free_transfers=1, budget=90.0, budget_remaining=90.0)
        session.add(team)
        session.flush()
        from app.models import Player, SquadPlayer
        # distinct players so the (team, player) unique constraint holds
        squad_players = [Player(name=f"Sq{i}", team_id=1 + (i % 3), price=5.0, is_active=True)
                         for i in range(13)]
        p_in = Player(name="In Guy", team_id=4, price=5.0, is_active=True)
        session.add_all(squad_players + [p_in])
        session.flush()
        for i, pl in enumerate(squad_players):
            sp = SquadPlayer(fantasy_team=team, player_id=pl.id, position_slot=i + 1,
                             is_starting=i < 10, purchase_price=5.0)
            session.add(sp)
        session.commit()
        p_out = squad_players[0]

        token_data = {"access_token": __import__("app.auth", fromlist=["create_access_token"]).create_access_token(user.id, user.username)}
        headers = {"Authorization": f"Bearer {token_data['access_token']}"}

        # First swap: consumes the 1 free transfer
        r = client.post("/api/transfers/player", json={
            "player_in_id": p_in.id, "player_out_id": p_out.id,
        }, headers=headers)
        assert r.status_code == 200, r.text
        second_out = squad_players[1]
        body = r.json()
        assert body["free_transfers"] == 0

        # Second swap now exceeds available transfers: must report a real hit
        r2 = client.post("/api/transfers/player", json={
            "player_in_id": None, "player_out_id": second_out.id,
        }, headers=headers)
        # either rejected by max-transfers rule or reports a -4 hit — never silently free
        if r2.status_code == 200:
            assert r2.json()["points_hit"] == 4
        else:
            assert r2.status_code == 400
