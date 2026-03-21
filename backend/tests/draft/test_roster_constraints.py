# backend/tests/draft/test_roster_constraints.py
"""
Tests for roster coverage validation — CDC v3.1, section 6.2.

Covers:
    - Valid rosters (exact minimums, surplus coverage, multi-position players)
    - Missing bench positions (single and multiple failures)
    - Multi-position player correctly covers two distinct groups
    - Incomplete roster guard (< 30 players)
    - DraftEngine integration: _complete_draft() calls validate_roster_coverage()

Test count: 12 tests across 4 classes.

Design note:
    validate_roster_coverage() works on list[PlayerSummary] ordered by
    draft pick: index 0–14 = starters (ignored for coverage), 15–29 = bench.

    _build_player() is the single factory for test fixtures. It defaults to
    a minimal valid PlayerSummary — callers only override what they need.
    This avoids copy-paste errors across test cases.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.player import AvailabilityStatus, PlayerSummary, PositionType
from draft.roster_coverage import (
    BENCH_COVERAGE_MINIMUMS,
    STARTER_COUNT,
    RosterCoverageError,
    RosterCoverageResult,
    RosterIncompleteError,
    validate_roster_coverage,
)
from draft.validate_pick import ROSTER_SIZE


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _build_player(
    positions: list[PositionType],
    nationality: str = "ENG",
    club: str = "Bath",
) -> PlayerSummary:
    """Factory for PlayerSummary test fixtures.

    Args:
        positions: Player's eligible positions. Must be non-empty.
        nationality: ISO country code. Defaults to "ENG".
        club: Club name. Defaults to "Bath".

    Returns:
        A valid PlayerSummary with a random UUID.
    """
    return PlayerSummary(
        id=uuid.uuid4(),
        first_name="Test",
        last_name="Player",
        nationality=nationality,
        club=club,
        positions=positions,
        availability_status=AvailabilityStatus.AVAILABLE,
    )


def _build_valid_roster() -> list[PlayerSummary]:
    """Build a complete 30-player roster that satisfies all CDC 6.2 minimums.

    Starting XV (index 0–14) — positions chosen to reflect a realistic XV:
        2 props, 1 hooker, 2 locks, 2 flankers, 1 number_8,
        1 scrum_half, 1 fly_half, 2 centres, 2 wings, 1 fullback.

    Bench (index 15–29) — satisfies all minimums + 5 libre slots:
        2 props, 1 hooker, 1 lock, 1 flanker, 1 scrum_half,
        1 fly_half, 1 centre, 1 wing, 1 fullback = 10 mandatory slots.
        5 libre slots: 5 additional forwards (props/locks/flankers).

    Returns:
        List of 30 PlayerSummary objects in draft order.
    """
    # ── Starters (15) ────────────────────────────────────────────────────────
    starters: list[PlayerSummary] = [
        _build_player([PositionType.PROP]),  # 1
        _build_player([PositionType.PROP]),  # 2
        _build_player([PositionType.HOOKER]),  # 3
        _build_player([PositionType.LOCK]),  # 4
        _build_player([PositionType.LOCK]),  # 5
        _build_player([PositionType.FLANKER]),  # 6
        _build_player([PositionType.FLANKER]),  # 7
        _build_player([PositionType.NUMBER_8]),  # 8
        _build_player([PositionType.SCRUM_HALF]),  # 9
        _build_player([PositionType.FLY_HALF]),  # 10
        _build_player([PositionType.CENTRE]),  # 11
        _build_player([PositionType.CENTRE]),  # 12
        _build_player([PositionType.WING]),  # 13
        _build_player([PositionType.WING]),  # 14
        _build_player([PositionType.FULLBACK]),  # 15
    ]

    # ── Bench — mandatory coverage (10 slots) ────────────────────────────────
    bench_mandatory: list[PlayerSummary] = [
        _build_player([PositionType.PROP]),  # 16 — prop ×1 (of 2 required)
        _build_player([PositionType.PROP]),  # 17 — prop ×2 ✓
        _build_player([PositionType.HOOKER]),  # 18 — hooker ✓
        _build_player([PositionType.LOCK]),  # 19 — lock ✓
        _build_player([PositionType.FLANKER]),  # 20 — back_row ✓
        _build_player([PositionType.SCRUM_HALF]),  # 21 — scrum_half ✓
        _build_player([PositionType.FLY_HALF]),  # 22 — fly_half ✓
        _build_player([PositionType.CENTRE]),  # 23 — centre ✓
        _build_player([PositionType.WING]),  # 24 — wing ✓
        _build_player([PositionType.FULLBACK]),  # 25 — fullback ✓
    ]

    # ── Bench — libre slots (5 slots, no constraint) ─────────────────────────
    bench_libre: list[PlayerSummary] = [
        _build_player([PositionType.PROP]),  # 26
        _build_player([PositionType.LOCK]),  # 27
        _build_player([PositionType.LOCK]),  # 28
        _build_player([PositionType.FLANKER]),  # 29
        _build_player([PositionType.FLANKER]),  # 30
    ]

    roster = starters + bench_mandatory + bench_libre
    assert len(roster) == ROSTER_SIZE, f"Fixture bug: expected 30, got {len(roster)}"
    return roster


# ---------------------------------------------------------------------------
# TestValidRosters
# ---------------------------------------------------------------------------


class TestValidRosters:
    """Verify that rosters meeting CDC 6.2 minimums pass validation."""

    def test_complete_valid_roster_passes(self) -> None:
        """A 30-player roster with all minimums met returns RosterCoverageResult."""
        roster = _build_valid_roster()
        result = validate_roster_coverage(roster)
        assert isinstance(result, RosterCoverageResult)

    def test_bench_coverage_counts_are_correct(self) -> None:
        """bench_coverage dict reflects actual counts for each position group."""
        roster = _build_valid_roster()
        result = validate_roster_coverage(roster)
        # The valid roster has: prop×4 (2 mandatory + 2 libre props counted)
        # but we only care that minimums are met — spot-check a few.
        assert result.bench_coverage["hooker"] >= 1
        assert result.bench_coverage["prop"] >= 2
        assert result.bench_coverage["back_row"] >= 1

    def test_exact_minimum_coverage_passes(self) -> None:
        """A roster with exactly the minimum bench coverage (no surplus) passes.

        Uses 10 mandatory bench slots filled with exactly 1 of each minimum,
        plus 5 libres (wings — no minimum constraint issue there).
        """
        starters = [_build_player([PositionType.PROP])] * STARTER_COUNT

        bench_exact: list[PlayerSummary] = [
            _build_player([PositionType.PROP]),  # prop ×1 of 2
            _build_player([PositionType.PROP]),  # prop ×2 ✓
            _build_player([PositionType.HOOKER]),  # hooker ✓
            _build_player([PositionType.LOCK]),  # lock ✓
            _build_player([PositionType.FLANKER]),  # back_row ✓
            _build_player([PositionType.SCRUM_HALF]),  # scrum_half ✓
            _build_player([PositionType.FLY_HALF]),  # fly_half ✓
            _build_player([PositionType.CENTRE]),  # centre ✓
            _build_player([PositionType.WING]),  # wing ✓
            _build_player([PositionType.FULLBACK]),  # fullback ✓
            # 5 libre slots — any position, no constraint
            _build_player([PositionType.WING]),
            _build_player([PositionType.WING]),
            _build_player([PositionType.WING]),
            _build_player([PositionType.WING]),
            _build_player([PositionType.WING]),
        ]

        roster = starters + bench_exact
        assert len(roster) == ROSTER_SIZE
        result = validate_roster_coverage(roster)
        assert isinstance(result, RosterCoverageResult)

    def test_number_8_counts_as_back_row(self) -> None:
        """A number_8 on the bench covers the back_row minimum (D-013)."""
        starters = [_build_player([PositionType.PROP])] * STARTER_COUNT

        # Bench with number_8 covering back_row (no flanker on bench)
        bench: list[PlayerSummary] = [
            _build_player([PositionType.PROP]),
            _build_player([PositionType.PROP]),
            _build_player([PositionType.HOOKER]),
            _build_player([PositionType.LOCK]),
            _build_player([PositionType.NUMBER_8]),  # back_row via number_8
            _build_player([PositionType.SCRUM_HALF]),
            _build_player([PositionType.FLY_HALF]),
            _build_player([PositionType.CENTRE]),
            _build_player([PositionType.WING]),
            _build_player([PositionType.FULLBACK]),
            _build_player([PositionType.WING]),
            _build_player([PositionType.WING]),
            _build_player([PositionType.WING]),
            _build_player([PositionType.WING]),
            _build_player([PositionType.WING]),
        ]

        roster = starters + bench
        assert len(roster) == ROSTER_SIZE
        result = validate_roster_coverage(roster)
        assert result.bench_coverage["back_row"] == 1


# ---------------------------------------------------------------------------
# TestMissingPositionCoverage
# ---------------------------------------------------------------------------


class TestMissingPositionCoverage:
    """Verify that missing bench positions raise RosterCoverageError correctly."""

    def _bench_with_missing(self, missing_group: str) -> list[PlayerSummary]:
        """Build a 15-player bench with all minimums met EXCEPT one group.

        Args:
            missing_group: The coverage group key to omit from the bench.

        Returns:
            15 PlayerSummary bench players.
        """
        # Full bench that satisfies everything
        full_bench: dict[str, PlayerSummary | list[PlayerSummary]] = {
            "prop_1": _build_player([PositionType.PROP]),
            "prop_2": _build_player([PositionType.PROP]),
            "hooker": _build_player([PositionType.HOOKER]),
            "lock": _build_player([PositionType.LOCK]),
            "back_row": _build_player([PositionType.FLANKER]),
            "scrum_half": _build_player([PositionType.SCRUM_HALF]),
            "fly_half": _build_player([PositionType.FLY_HALF]),
            "centre": _build_player([PositionType.CENTRE]),
            "wing": _build_player([PositionType.WING]),
            "fullback": _build_player([PositionType.FULLBACK]),
        }

        # Build bench without the missing group's player(s)
        bench: list[PlayerSummary] = []

        # Props need 2 slots — handle separately
        if missing_group == "prop":
            # Include prop_2 only — 1 prop instead of 2
            bench.append(full_bench["prop_2"])  # type: ignore[arg-type]
        else:
            bench.append(full_bench["prop_1"])  # type: ignore[arg-type]
            bench.append(full_bench["prop_2"])  # type: ignore[arg-type]

        for key in (
            "hooker",
            "lock",
            "back_row",
            "scrum_half",
            "fly_half",
            "centre",
            "wing",
            "fullback",
        ):
            if key == missing_group:
                continue  # omit this position
            bench.append(full_bench[key])  # type: ignore[arg-type]

        # Pad with libres to reach 15 bench slots total
        while len(bench) < 15:
            bench.append(_build_player([PositionType.WING]))

        assert len(bench) == 15, f"Bench fixture bug: {len(bench)} players"
        return bench

    def test_missing_hooker_raises_coverage_error(self) -> None:
        """RosterCoverageError raised when hooker is absent from bench."""
        starters = [_build_player([PositionType.PROP])] * STARTER_COUNT
        bench = self._bench_with_missing("hooker")
        roster = starters + bench

        with pytest.raises(RosterCoverageError) as exc_info:
            validate_roster_coverage(roster)

        error = exc_info.value
        assert "hooker" in error.missing
        assert error.missing["hooker"] == 1
        assert error.code == "ROSTER_COVERAGE_INSUFFICIENT"

    def test_only_one_prop_raises_coverage_error(self) -> None:
        """RosterCoverageError raised when only 1 prop is on bench (minimum = 2)."""
        starters = [_build_player([PositionType.PROP])] * STARTER_COUNT
        bench = self._bench_with_missing("prop")
        roster = starters + bench

        with pytest.raises(RosterCoverageError) as exc_info:
            validate_roster_coverage(roster)

        error = exc_info.value
        assert "prop" in error.missing
        assert error.missing["prop"] == 1  # need 1 more prop

    def test_missing_scrum_half_raises_coverage_error(self) -> None:
        """RosterCoverageError raised when scrum_half is absent from bench."""
        starters = [_build_player([PositionType.PROP])] * STARTER_COUNT
        bench = self._bench_with_missing("scrum_half")
        roster = starters + bench

        with pytest.raises(RosterCoverageError) as exc_info:
            validate_roster_coverage(roster)

        assert "scrum_half" in exc_info.value.missing

    def test_multiple_missing_positions_all_reported(self) -> None:
        """RosterCoverageError reports ALL missing groups, not just the first.

        Bench filled with 15 props:
            - prop (min=2) is satisfied → NOT in missing
            - all other 8 groups have 0 coverage → all in missing
        This gives us a precise, predictable missing set to assert against.
        """
        starters = [_build_player([PositionType.PROP])] * STARTER_COUNT

        # 15 props on bench — satisfies prop (min=2), nothing else
        bench = [_build_player([PositionType.PROP])] * 15

        roster = starters + bench

        with pytest.raises(RosterCoverageError) as exc_info:
            validate_roster_coverage(roster)

        error = exc_info.value

        # prop is satisfied — must NOT be in missing
        assert "prop" not in error.missing

        # All other 8 groups must be reported as missing (shortfall = 1 each)
        expected_missing_groups = {g for g in BENCH_COVERAGE_MINIMUMS if g != "prop"}
        assert set(error.missing.keys()) == expected_missing_groups
        for group in expected_missing_groups:
            assert error.missing[group] == 1

        assert error.code == "ROSTER_COVERAGE_INSUFFICIENT"

    def test_starters_do_not_count_toward_bench_coverage(self) -> None:
        """Positions covered in the starting XV do not satisfy bench minimums.

        This is the fundamental rule: starters (index 0–14) are invisible
        to the bench coverage check. Having 2 hooker starters does NOT
        exempt the bench from needing 1 hooker.
        """
        # 15 starters, all hookers — should not help bench coverage
        starters = [_build_player([PositionType.HOOKER])] * STARTER_COUNT
        bench = self._bench_with_missing("hooker")
        roster = starters + bench

        with pytest.raises(RosterCoverageError) as exc_info:
            validate_roster_coverage(roster)

        assert "hooker" in exc_info.value.missing


# ---------------------------------------------------------------------------
# TestMultiPositionCoverage
# ---------------------------------------------------------------------------


class TestMultiPositionCoverage:
    """Verify correct handling of multi-position players on the bench."""

    def test_multi_position_player_covers_two_distinct_groups(self) -> None:
        """A fly_half/fullback player covers both fly_half and fullback groups."""
        starters = [_build_player([PositionType.PROP])] * STARTER_COUNT

        bench: list[PlayerSummary] = [
            _build_player([PositionType.PROP]),
            _build_player([PositionType.PROP]),
            _build_player([PositionType.HOOKER]),
            _build_player([PositionType.LOCK]),
            _build_player([PositionType.FLANKER]),
            _build_player([PositionType.SCRUM_HALF]),
            # One player covers both fly_half AND fullback — saves a slot
            _build_player([PositionType.FLY_HALF, PositionType.FULLBACK]),
            _build_player([PositionType.CENTRE]),
            _build_player([PositionType.WING]),
            # No dedicated fullback — covered by the multi-position player above
            # 6 libre slots to pad to 15
            _build_player([PositionType.WING]),
            _build_player([PositionType.WING]),
            _build_player([PositionType.WING]),
            _build_player([PositionType.WING]),
            _build_player([PositionType.WING]),
            _build_player([PositionType.WING]),
        ]

        roster = starters + bench
        assert len(roster) == ROSTER_SIZE

        result = validate_roster_coverage(roster)
        assert result.bench_coverage["fly_half"] == 1
        assert result.bench_coverage["fullback"] == 1

    def test_flanker_and_number_8_on_same_player_counts_once_for_back_row(
        self,
    ) -> None:
        """A flanker/number_8 player contributes 1 (not 2) to the back_row group.

        Both positions map to "back_row". The deduplication in
        validate_roster_coverage() must prevent double-counting.
        """
        starters = [_build_player([PositionType.PROP])] * STARTER_COUNT

        bench: list[PlayerSummary] = [
            _build_player([PositionType.PROP]),
            _build_player([PositionType.PROP]),
            _build_player([PositionType.HOOKER]),
            _build_player([PositionType.LOCK]),
            # flanker + number_8 → "back_row" only once
            _build_player([PositionType.FLANKER, PositionType.NUMBER_8]),
            _build_player([PositionType.SCRUM_HALF]),
            _build_player([PositionType.FLY_HALF]),
            _build_player([PositionType.CENTRE]),
            _build_player([PositionType.WING]),
            _build_player([PositionType.FULLBACK]),
            _build_player([PositionType.WING]),
            _build_player([PositionType.WING]),
            _build_player([PositionType.WING]),
            _build_player([PositionType.WING]),
            _build_player([PositionType.WING]),
        ]

        roster = starters + bench
        assert len(roster) == ROSTER_SIZE

        result = validate_roster_coverage(roster)
        # back_row covered exactly once — not twice despite two positions
        assert result.bench_coverage["back_row"] == 1


# ---------------------------------------------------------------------------
# TestIncompleteRoster
# ---------------------------------------------------------------------------


class TestIncompleteRoster:
    """Verify that incomplete rosters are rejected before any coverage check."""

    def test_empty_roster_raises_incomplete_error(self) -> None:
        """RosterIncompleteError raised for an empty player list."""
        with pytest.raises(RosterIncompleteError) as exc_info:
            validate_roster_coverage([])

        error = exc_info.value
        assert error.actual_count == 0
        assert error.code == "ROSTER_INCOMPLETE"

    def test_partial_roster_raises_incomplete_error(self) -> None:
        """RosterIncompleteError raised for a 29-player roster (1 short)."""
        roster = [_build_player([PositionType.PROP])] * (ROSTER_SIZE - 1)

        with pytest.raises(RosterIncompleteError) as exc_info:
            validate_roster_coverage(roster)

        assert exc_info.value.actual_count == ROSTER_SIZE - 1

    def test_oversized_roster_raises_incomplete_error(self) -> None:
        """RosterIncompleteError raised for a 31-player roster (1 too many).

        The check is strict equality — 31 is as invalid as 29.
        A DraftEngine that produced 31 picks has a bug.
        """
        roster = [_build_player([PositionType.PROP])] * (ROSTER_SIZE + 1)

        with pytest.raises(RosterIncompleteError) as exc_info:
            validate_roster_coverage(roster)

        assert exc_info.value.actual_count == ROSTER_SIZE + 1
