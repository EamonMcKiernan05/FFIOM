"""Tests for FFIOM scoring (position-free model).

Positions were removed — there is no reliable position data for IoM
leagues, so scoring is uniform across all players.
"""
import pytest
from datetime import datetime, date, timedelta
from app.scoring import (
    calculate_player_points,
    calculate_bps,
    award_bonus_points,
    calculate_transfer_hit,
    calculate_gameweek_score,
    calculate_selling_price,
    calculate_form,
    calculate_free_transfers,
    auto_sub_squad,
)


class TestScoring:
    """Position-free gameweek scoring."""

    def test_minutes_60_plus(self):
        assert calculate_player_points(minutes_played=90) == 2

    def test_minutes_under_60(self):
        assert calculate_player_points(minutes_played=30) == 1

    def test_no_minutes(self):
        assert calculate_player_points(minutes_played=0) == 0

    def test_goal(self):
        assert calculate_player_points(goals_scored=1, minutes_played=90) == 6

    def test_goals_uniform(self):
        # 4 pts per goal regardless of who scores
        assert calculate_player_points(goals_scored=2, minutes_played=90) == 10

    def test_assist(self):
        assert calculate_player_points(assists=1, minutes_played=90) == 5

    def test_clean_sheet(self):
        assert calculate_player_points(clean_sheet=True, minutes_played=90) == 6

    def test_saves_threshold(self):
        assert calculate_player_points(saves=3, minutes_played=90) == 3

    def test_saves_below_threshold(self):
        assert calculate_player_points(saves=2, minutes_played=90) == 2

    def test_penalty_save(self):
        assert calculate_player_points(penalties_saved=1, minutes_played=90) == 7

    def test_yellow_card(self):
        assert calculate_player_points(yellow_card=True, minutes_played=90) == 1

    def test_red_card(self):
        assert calculate_player_points(red_card=True, minutes_played=90) == -1

    def test_own_goal(self):
        assert calculate_player_points(own_goal=True, minutes_played=90) == 0

    def test_penalty_missed(self):
        assert calculate_player_points(penalties_missed=1, minutes_played=90) == 0

    def test_penalty_goal_bonus(self):
        pts = calculate_player_points(goals_scored=1, was_penalty_goal=True, minutes_played=90)
        assert pts == 8  # 2 + 4 + 2

    def test_goals_conceded_penalty(self):
        assert calculate_player_points(goals_conceded=2, minutes_played=90) == 1

    def test_goals_conceded_odd(self):
        assert calculate_player_points(goals_conceded=3, minutes_played=90) == 1

    def test_defensive_contributions_threshold(self):
        assert calculate_player_points(defensive_contributions=12, minutes_played=90) == 4

    def test_defensive_contributions_below(self):
        assert calculate_player_points(defensive_contributions=11, minutes_played=90) == 2

    def test_bonus_points(self):
        assert calculate_player_points(minutes_played=90, bonus_points=3) == 5

    def test_combined(self):
        pts = calculate_player_points(
            goals_scored=1, assists=1, clean_sheet=True,
            minutes_played=90, yellow_card=True,
        )
        assert pts == 2 + 4 + 3 + 4 - 1  # 12


class TestBPS:
    """Bonus Points System (position-free)."""

    def test_bps_goal(self):
        assert calculate_bps(goals_scored=1) == 8

    def test_bps_assist(self):
        assert calculate_bps(assists=1) == 8

    def test_bps_clean_sheet(self):
        assert calculate_bps(clean_sheet=True) == 5

    def test_bps_saves(self):
        assert calculate_bps(saves=3) == 6

    def test_bps_negative(self):
        assert calculate_bps(yellow_card=True, goals_conceded=2) == 0  # clamped at 0

    def test_award_bonus_top3(self):
        players = [
            {"player_id": 1, "bps": 30},
            {"player_id": 2, "bps": 20},
            {"player_id": 3, "bps": 10},
            {"player_id": 4, "bps": 5},
        ]
        bonuses = award_bonus_points(players)
        assert bonuses[1] == 3
        assert bonuses[2] == 2
        assert bonuses[3] == 1
        assert 4 not in bonuses or bonuses.get(4, 0) == 0


class TestSellingPrice:
    def test_sell_at_purchase_when_current_lower(self):
        # Price decreased: sell at current price, no half rule
        assert calculate_selling_price(5.0, 4.5) == 4.5

    def test_sell_half_profit(self):
        assert calculate_selling_price(5.0, 6.0) == 5.5


class TestForm:
    def test_form_average(self):
        assert calculate_form([5, 10, 3, 8, 4]) == 6.0

    def test_form_empty(self):
        assert calculate_form([]) == 0.0


class TestFreeTransfers:
    def test_no_transfers_rolls_over(self):
        # 1 unused, 0 made -> 1 + 1 = 2 next GW
        assert calculate_free_transfers(1, 0) == 2

    def test_carry_over_max(self):
        # Capped at max_free (5)
        assert calculate_free_transfers(5, 0) == 5

    def test_wildcard_resets(self):
        assert calculate_free_transfers(3, 5, is_wildcard=True) == 1


class TestTransferHits:
    def test_free_transfer(self):
        assert calculate_transfer_hit(1, 1) == 0

    def test_extra_transfer(self):
        assert calculate_transfer_hit(3, 1) == 8  # 2 extra * 4

    def test_wildcard(self):
        assert calculate_transfer_hit(10, 0, is_wildcard=True) == 0

    def test_no_hit_within_free(self):
        assert calculate_transfer_hit(2, 3) == 0


class TestGameweekScore:
    def test_basic_team_score(self):
        squad = [
            {"id": 1, "base_points": 6, "is_starting": True, "did_play": True},
            {"id": 2, "base_points": 5, "is_starting": True, "did_play": True},
            {"id": 3, "base_points": 0, "is_starting": False, "did_play": True},
        ]
        result = calculate_gameweek_score(
            squad_points=squad,
            captain_id=1,
            vice_captain_id=2,
        )
        assert result["total_points"] == 17  # 6*2 (captain) + 5

    def test_vice_captain_when_captain_dnp(self):
        squad = [
            {"id": 1, "base_points": 6, "is_starting": True, "did_play": False},
            {"id": 2, "base_points": 5, "is_starting": True, "did_play": True},
        ]
        result = calculate_gameweek_score(
            squad_points=squad,
            captain_id=1,
            vice_captain_id=2,
        )
        assert result["total_points"] == 10  # vice doubles: 5*2


class TestAutoSub:
    def _squad(self):
        return [
            {"id": 1, "player_id": 1, "is_starting": True, "bench_priority": 99},
            {"id": 2, "player_id": 2, "is_starting": True, "bench_priority": 99},
            {"id": 3, "player_id": 3, "is_starting": False, "bench_priority": 1},
            {"id": 4, "player_id": 4, "is_starting": False, "bench_priority": 2},
        ]

    def test_no_subs_needed(self):
        squad = self._squad()
        result = auto_sub_squad(squad, non_playing_ids=[])
        assert [sp["is_starting"] for sp in result] == [True, True, False, False]

    def test_starter_out_bench_in(self):
        squad = self._squad()
        result = auto_sub_squad(squad, non_playing_ids=[1])
        by_id = {sp["player_id"]: sp for sp in result}
        assert by_id[1]["is_starting"] is False
        assert by_id[3]["is_starting"] is True
        assert by_id[3]["was_autosub"] is True

    def test_bench_priority_order(self):
        squad = self._squad()
        result = auto_sub_squad(squad, non_playing_ids=[1, 2])
        by_id = {sp["player_id"]: sp for sp in result}
        assert by_id[3]["is_starting"] is True
        assert by_id[4]["is_starting"] is True

    def test_nonplaying_bench_skipped(self):
        squad = self._squad()
        result = auto_sub_squad(squad, non_playing_ids=[1, 3])
        by_id = {sp["player_id"]: sp for sp in result}
        assert by_id[3]["is_starting"] is False  # also didn't play
        assert by_id[4]["is_starting"] is True
