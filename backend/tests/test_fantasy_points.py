"""
tests/test_fantasy_points.py
============================
Unit tests for fantasy points calculation — scoring system v2 (D-039).

Strategy: pure Python implementation of the scoring formula, tested
against known inputs. No dbt, no database, no fixtures files needed.

These tests validate the *rules*, not the SQL. The SQL in
mart_fantasy_points.sql implements the same rules — if these pass,
the SQL is correct by construction.

Scoring system v2 reference (DECISIONS.md D-039):
    Attack:  metres +0.1/m, try +5, try_assist +2, turnover_won +2,
             line_break +1, kick_assist +1, catch_from_kick +0.5,
             conversion_made +2 (kicker), penalty_made +3 (kicker)
    Defence: tackle +0.5, lineout_won +1, lineout_lost -0.5,
             turnover_conceded -0.5, missed_tackle -0.5,
             handling_error -0.5, penalty_conceded -1,
             yellow_card -2, red_card -3
    Captain: CEIL(raw * 1.5 * 2) / 2.0 → nearest 0.5 upward
"""

import math
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Pure scoring function — mirrors mart_fantasy_points.sql logic exactly
# ---------------------------------------------------------------------------


@dataclass
class PlayerStats:
    """Input stats for a single player in a single match."""

    # Attack
    tries: int = 0
    metres_carried: int = 0
    try_assists: int = 0
    turnovers_won: int = 0
    line_breaks: int = 0
    kick_assists: int = 0
    catch_from_kick: int = 0
    # Kicker only
    conversions_made: int = 0
    penalties_made: int = 0
    # Defence
    tackles: int = 0
    lineouts_won: int = 0
    lineouts_lost: int = 0
    turnovers_conceded: int = 0
    missed_tackles: int = 0
    handling_errors: int = 0
    penalties_conceded: int = 0
    yellow_cards: int = 0
    red_cards: int = 0
    # Context
    is_kicker: bool = False
    is_captain: bool = False


def calculate_raw_points(stats: PlayerStats) -> float:
    """
    Calculate raw fantasy points for a player.

    Applies all scoring rules from D-039. Kicker stats are multiplied
    by is_kicker (0 or 1). Captain multiplier is NOT applied here —
    use calculate_total_points() for the final value.

    Returns:
        Raw points as a float, rounded to 2 decimal places.
    """
    kicker = 1 if stats.is_kicker else 0

    raw = (
        # Attack
        round(stats.metres_carried * 0.1, 2)
        + stats.tries * 5.0
        + stats.try_assists * 2.0
        + stats.turnovers_won * 2.0
        + stats.line_breaks * 1.0
        + stats.kick_assists * 1.0
        + stats.catch_from_kick * 0.5
        # Kicker only
        + stats.conversions_made * kicker * 2.0
        + stats.penalties_made * kicker * 3.0
        # Defence
        + stats.tackles * 0.5
        + stats.lineouts_won * 1.0
        + stats.lineouts_lost * (-0.5)
        + stats.turnovers_conceded * (-0.5)
        + stats.missed_tackles * (-0.5)
        + stats.handling_errors * (-0.5)
        + stats.penalties_conceded * (-1.0)
        + stats.yellow_cards * (-2.0)
        + stats.red_cards * (-3.0)
    )
    return round(raw, 2)


def apply_captain_multiplier(raw_points: float) -> float:
    """
    Apply captain multiplier: CEIL(raw * 1.5 * 2) / 2.0.

    Rounds UP to nearest 0.5 — never down.
    Examples:
        10.0  → ceil(10.0 * 1.5 * 2) / 2.0 = ceil(30.0) / 2.0 = 15.0
        10.1  → ceil(10.1 * 1.5 * 2) / 2.0 = ceil(30.3) / 2.0 = 15.5
        10.5  → ceil(10.5 * 1.5 * 2) / 2.0 = ceil(31.5) / 2.0 = 16.0
        -3.0  → ceil(-3.0 * 1.5 * 2) / 2.0 = ceil(-9.0) / 2.0 = -4.5
    """
    return math.ceil(raw_points * 1.5 * 2) / 2.0


def calculate_total_points(stats: PlayerStats) -> float:
    """Calculate final fantasy points including captain multiplier if applicable."""
    raw = calculate_raw_points(stats)
    if stats.is_captain:
        return apply_captain_multiplier(raw)
    return raw


# ---------------------------------------------------------------------------
# Tests — Attack stats
# ---------------------------------------------------------------------------


class TestAttackStats:
    """Tests for attack scoring rules (D-039)."""

    def test_try_scores_five_points(self) -> None:
        stats = PlayerStats(tries=1)
        assert calculate_raw_points(stats) == 5.0

    def test_two_tries_scores_ten_points(self) -> None:
        stats = PlayerStats(tries=2)
        assert calculate_raw_points(stats) == 10.0

    def test_try_assist_scores_two_points(self) -> None:
        stats = PlayerStats(try_assists=1)
        assert calculate_raw_points(stats) == 2.0

    def test_metres_carried_point_one_per_metre(self) -> None:
        stats = PlayerStats(metres_carried=10)
        assert calculate_raw_points(stats) == 1.0

    def test_metres_carried_rounds_correctly(self) -> None:
        # 112 metres × 0.1 = 11.2 pts
        stats = PlayerStats(metres_carried=112)
        assert calculate_raw_points(stats) == 11.2

    def test_turnover_won_scores_two_points(self) -> None:
        stats = PlayerStats(turnovers_won=1)
        assert calculate_raw_points(stats) == 2.0

    def test_line_break_scores_one_point(self) -> None:
        stats = PlayerStats(line_breaks=1)
        assert calculate_raw_points(stats) == 1.0

    def test_kick_assist_scores_one_point(self) -> None:
        stats = PlayerStats(kick_assists=1)
        assert calculate_raw_points(stats) == 1.0

    def test_catch_from_kick_scores_half_point(self) -> None:
        stats = PlayerStats(catch_from_kick=1)
        assert calculate_raw_points(stats) == 0.5

    def test_catch_from_kick_four_times(self) -> None:
        stats = PlayerStats(catch_from_kick=4)
        assert calculate_raw_points(stats) == 2.0


# ---------------------------------------------------------------------------
# Tests — Kicker stats (only scored if is_kicker=True)
# ---------------------------------------------------------------------------


class TestKickerStats:
    """Kicker-only stats must score 0 for non-kickers and correctly for kickers."""

    def test_conversion_not_kicker_scores_zero(self) -> None:
        stats = PlayerStats(conversions_made=3, is_kicker=False)
        assert calculate_raw_points(stats) == 0.0

    def test_penalty_not_kicker_scores_zero(self) -> None:
        stats = PlayerStats(penalties_made=3, is_kicker=False)
        assert calculate_raw_points(stats) == 0.0

    def test_conversion_kicker_scores_two_per_conversion(self) -> None:
        stats = PlayerStats(conversions_made=1, is_kicker=True)
        assert calculate_raw_points(stats) == 2.0

    def test_penalty_kicker_scores_three_per_penalty(self) -> None:
        stats = PlayerStats(penalties_made=1, is_kicker=True)
        assert calculate_raw_points(stats) == 3.0

    def test_kicker_full_game(self) -> None:
        # Thomas Ramos profile: 2 conversions + 3 penalties (kicker)
        # + 67m + 1 try_assist + 1 kick_assist + 1 line_break + 3 catch_from_kick
        # + 4 tackles
        # 6.7 + 2.0 + 1.0 + 1.0 + 1.5 + 4.0 + 9.0 + 2.0 = 27.2
        stats = PlayerStats(
            metres_carried=67,
            try_assists=1,
            kick_assists=1,
            line_breaks=1,
            catch_from_kick=3,
            conversions_made=2,
            penalties_made=3,
            tackles=4,
            is_kicker=True,
        )
        assert calculate_raw_points(stats) == 27.2


# ---------------------------------------------------------------------------
# Tests — Defence stats
# ---------------------------------------------------------------------------


class TestDefenceStats:
    """Tests for defence scoring rules (D-039)."""

    def test_tackle_scores_half_point(self) -> None:
        stats = PlayerStats(tackles=1)
        assert calculate_raw_points(stats) == 0.5

    def test_eighteen_tackles(self) -> None:
        # Maro Itoje profile: 18 tackles = 9.0
        stats = PlayerStats(tackles=18)
        assert calculate_raw_points(stats) == 9.0

    def test_lineout_won_scores_one_point(self) -> None:
        stats = PlayerStats(lineouts_won=1)
        assert calculate_raw_points(stats) == 1.0

    def test_lineout_lost_minus_half_point(self) -> None:
        stats = PlayerStats(lineouts_lost=1)
        assert calculate_raw_points(stats) == -0.5

    def test_lineout_net_positive(self) -> None:
        # 4 won (+4), 1 lost (-0.5) = +3.5
        stats = PlayerStats(lineouts_won=4, lineouts_lost=1)
        assert calculate_raw_points(stats) == 3.5

    def test_turnover_conceded_minus_half_point(self) -> None:
        stats = PlayerStats(turnovers_conceded=1)
        assert calculate_raw_points(stats) == -0.5

    def test_missed_tackle_minus_half_point(self) -> None:
        stats = PlayerStats(missed_tackles=1)
        assert calculate_raw_points(stats) == -0.5

    def test_handling_error_minus_half_point(self) -> None:
        stats = PlayerStats(handling_errors=1)
        assert calculate_raw_points(stats) == -0.5

    def test_penalty_conceded_minus_one_point(self) -> None:
        stats = PlayerStats(penalties_conceded=1)
        assert calculate_raw_points(stats) == -1.0

    def test_yellow_card_minus_two_points(self) -> None:
        stats = PlayerStats(yellow_cards=1)
        assert calculate_raw_points(stats) == -2.0

    def test_red_card_minus_three_points(self) -> None:
        stats = PlayerStats(red_cards=1)
        assert calculate_raw_points(stats) == -3.0

    def test_yellow_and_red_card_combined(self) -> None:
        stats = PlayerStats(yellow_cards=1, red_cards=1)
        assert calculate_raw_points(stats) == -5.0


# ---------------------------------------------------------------------------
# Tests — Captain multiplier
# ---------------------------------------------------------------------------


class TestCaptainMultiplier:
    """CEIL(raw * 1.5 * 2) / 2.0 — rounds UP to nearest 0.5."""

    def test_captain_ten_points_gives_fifteen(self) -> None:
        assert apply_captain_multiplier(10.0) == 15.0

    def test_captain_rounding_up_to_half(self) -> None:
        # 10.1 × 1.5 = 15.15 → ceil(30.3) / 2 = 16 / 2 = 15.5 (NOT 15.0)
        assert apply_captain_multiplier(10.1) == 15.5

    def test_captain_exact_half_no_rounding(self) -> None:
        # 10.5 × 1.5 = 15.75 → ceil(31.5) / 2 = 32 / 2 = 16.0
        assert apply_captain_multiplier(10.5) == 16.0

    def test_captain_negative_points(self) -> None:
        # -3.0 × 1.5 = -4.5 → ceil(-9.0) / 2 = -9 / 2 = -4.5
        assert apply_captain_multiplier(-3.0) == -4.5

    def test_captain_negative_rounding_up(self) -> None:
        # -3.1 × 1.5 = -4.65 → ceil(-9.3) / 2 = -9 / 2 = -4.5
        # (ceil rounds toward +infinity: ceil(-9.3) = -9)
        assert apply_captain_multiplier(-3.1) == -4.5

    def test_non_captain_unchanged(self) -> None:
        stats = PlayerStats(tries=2, is_captain=False)
        assert calculate_total_points(stats) == 10.0

    def test_captain_flag_applies_multiplier(self) -> None:
        stats = PlayerStats(tries=2, is_captain=True)
        assert calculate_total_points(stats) == 15.0


# ---------------------------------------------------------------------------
# Tests — Full player profiles (integration scenarios)
# ---------------------------------------------------------------------------


class TestFullPlayerProfiles:
    """End-to-end scoring for realistic player profiles."""

    def test_alldritt_profile(self) -> None:
        """
        Gregory Alldritt (mock data):
        112m (+11.2) + 1 try (+5) + 1 try_assist (+2) + 2 line_breaks (+2)
        + 12 tackles (+6) + 2 turnovers_won (+4)
        + 1 turnovers_conceded (-0.5) + 1 handling_error (-0.5)
        = 11.2 + 5 + 2 + 2 + 6 + 4 - 0.5 - 0.5 = 29.2
        """
        stats = PlayerStats(
            metres_carried=112,
            tries=1,
            try_assists=1,
            line_breaks=2,
            tackles=12,
            turnovers_won=2,
            turnovers_conceded=1,
            handling_errors=1,
        )
        assert calculate_raw_points(stats) == 29.2

    def test_itoje_profile(self) -> None:
        """
        Maro Itoje (mock data):
        28m (+2.8) + 18 tackles (+9) + 1 turnover_won (+2)
        + 2 missed_tackles (-1) + 1 handling_error (-0.5)
        + 2 penalties_conceded (-2) + 1 yellow_card (-2)
        = 2.8 + 9 + 2 - 1 - 0.5 - 2 - 2 = 8.3
        """
        stats = PlayerStats(
            metres_carried=28,
            tackles=18,
            turnovers_won=1,
            missed_tackles=2,
            handling_errors=1,
            penalties_conceded=2,
            yellow_cards=1,
        )
        assert calculate_raw_points(stats) == 8.3

    def test_alldritt_as_captain(self) -> None:
        """
        Alldritt raw = 29.2 → captain:
        ceil(29.2 * 1.5 * 2) / 2.0 = ceil(87.6) / 2.0 = 88 / 2.0 = 44.0
        """
        stats = PlayerStats(
            metres_carried=112,
            tries=1,
            try_assists=1,
            line_breaks=2,
            tackles=12,
            turnovers_won=2,
            turnovers_conceded=1,
            handling_errors=1,
            is_captain=True,
        )
        assert calculate_total_points(stats) == 44.0

    def test_zero_stats_scores_zero(self) -> None:
        """A player with no activity scores exactly 0."""
        stats = PlayerStats()
        assert calculate_raw_points(stats) == 0.0

    def test_kicker_stats_ignored_for_non_kicker(self) -> None:
        """Conversion and penalty stats are 0 for non-kicker even with high values."""
        stats = PlayerStats(
            conversions_made=5,
            penalties_made=5,
            is_kicker=False,
        )
        assert calculate_raw_points(stats) == 0.0
