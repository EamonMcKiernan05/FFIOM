"""Tests for FFIOM features: chips, team value, countdown, gameweek score.

Position-free model — no position data anywhere.
"""
import pytest
from datetime import datetime, date, timedelta
from app.scoring import (
    calculate_player_points,
    calculate_bps,
    calculate_transfer_hit,
    calculate_gameweek_score,
    calculate_selling_price,
    calculate_form,
    check_chip_availability,
    activate_chip,
    cancel_chip,
    get_chip_status,
)


class TestTeamValueCalculations:
    """Selling price follows the FPL half-increase rule."""

    def test_selling_price_no_increase(self):
        assert calculate_selling_price(5.0, 5.0) == 5.0

    def test_selling_price_half_increase(self):
        assert calculate_selling_price(7.5, 7.8) == 7.6

    def test_selling_price_price_drop(self):
        assert calculate_selling_price(5.0, 4.5) == 4.5

    def test_selling_price_large_increase(self):
        assert calculate_selling_price(5.0, 7.0) == 6.0

    def test_selling_price_small_increase_rounds_down(self):
        assert calculate_selling_price(5.0, 5.2) == 5.1


class TestDeadlineCountdown:
    def test_days_hours_mins(self):
        from app.routes.gameweek_history import _format_countdown
        td = timedelta(days=2, hours=5, minutes=30)
        assert _format_countdown(td) == "2d 5h 30m 0s"

    def test_hours_only(self):
        from app.routes.gameweek_history import _format_countdown
        td = timedelta(hours=3, minutes=15)
        assert _format_countdown(td) == "3h 15m 0s"

    def test_expired(self):
        from app.routes.gameweek_history import _format_countdown
        assert _format_countdown(timedelta(seconds=-10)) == "Expired"


class TestBenchBoostScoring:
    def test_bench_boost_all_players_count(self):
        squad_points = [
            {"id": i, "base_points": 5 + i, "is_starting": i < 11, "did_play": True}
            for i in range(1, 16)
        ]
        result = calculate_gameweek_score(
            squad_points=squad_points,
            captain_id=1,
            vice_captain_id=2,
            chip="bench_boost",
        )
        assert result["bench_points"] > 0
        assert result["chip"] == "bench_boost"

    def test_triple_captain_multiplier(self):
        squad_points = [
            {"id": 1, "base_points": 10, "is_starting": True, "did_play": True},
            {"id": 2, "base_points": 5, "is_starting": True, "did_play": True},
        ]
        result = calculate_gameweek_score(
            squad_points=squad_points,
            captain_id=1,
            vice_captain_id=2,
            chip="triple_captain",
        )
        # Captain 10*3 + VC 5 = 35
        assert result["total_points"] == 35


class _FakeTeam:
    """Minimal stand-in for FantasyTeam chip fields."""
    def __init__(self):
        self.active_chip = None
        self.wildcard_used = False
        self.free_hit_used = False
        self.bench_boost_used = False
        self.triple_captain_used = False


class TestChipAvailability:
    def test_wildcard_available_when_unused(self):
        ok, _ = check_chip_availability(_FakeTeam(), "wildcard", 3)
        assert ok is True

    def test_wildcard_blocked_when_used(self):
        t = _FakeTeam()
        t.wildcard_used = True
        ok, _ = check_chip_availability(t, "wildcard", 3)
        assert ok is False

    def test_blocked_when_another_chip_active(self):
        t = _FakeTeam()
        t.active_chip = "bench_boost"
        ok, _ = check_chip_availability(t, "wildcard", 3)
        assert ok is False


class TestChipActivation:
    def test_activate_and_status(self):
        t = _FakeTeam()
        ok, _ = activate_chip(t, "wildcard", 3)
        assert ok is True
        assert t.active_chip == "wildcard"
        assert t.wildcard_used is True
        status = get_chip_status(t, 3)
        assert status["active_chip"] == "wildcard"

    def test_cancel_chip(self):
        t = _FakeTeam()
        activate_chip(t, "bench_boost", 3)
        ok, _ = cancel_chip(t, "bench_boost", 3)
        assert ok is True
        assert t.active_chip is None
        assert t.bench_boost_used is False

    def test_free_hit_cannot_be_cancelled(self):
        t = _FakeTeam()
        activate_chip(t, "free_hit", 3)
        ok, _ = cancel_chip(t, "free_hit", 3)
        assert ok is False


class TestScoringAccuracy:
    """Position-free scoring spot checks."""

    def test_goal_and_assist(self):
        assert calculate_player_points(goals_scored=1, assists=1, minutes_played=90) == 9

    def test_clean_sheet_full_game(self):
        assert calculate_player_points(clean_sheet=True, minutes_played=90) == 6

    def test_hattrick(self):
        assert calculate_player_points(goals_scored=3, minutes_played=90) == 14


class TestBPSAccuracy:
    def test_goal_bps(self):
        assert calculate_bps(goals_scored=1) == 8

    def test_full_match(self):
        bps = calculate_bps(goals_scored=1, assists=1, minutes_played=90, clean_sheet=True)
        assert bps == 8 + 8 + 5 + 5  # goal + assist + cs + minutes (90-15)//15=5


class TestTransferHits:
    def test_free_transfer(self):
        assert calculate_transfer_hit(1, 1) == 0

    def test_extra_transfer(self):
        assert calculate_transfer_hit(3, 1) == 8

    def test_wildcard(self):
        assert calculate_transfer_hit(10, 0, is_wildcard=True) == 0


class TestForm:
    def test_form(self):
        assert calculate_form([4, 6, 8]) == 6.0
