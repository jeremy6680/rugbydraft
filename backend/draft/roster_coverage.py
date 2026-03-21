# backend/draft/roster_coverage.py
"""
Post-draft roster coverage validation for RugbyDraft.

This module checks that a completed 30-player roster satisfies the
minimum bench coverage requirements defined in CDC v3.1, section 6.2.

Design:
    - Pure function: no I/O, no database, no FastAPI.
    - Called by DraftEngine._complete_draft() after all 30 picks are made.
    - Works on list[PlayerSummary] — does NOT modify RosterSnapshot
      (which tracks only nationality/club for pick-time validation).

CDC v3.1, section 6.2 — minimum bench coverage:
    prop:       2  (pilier — any prop, left or right, counts)
    hooker:     1  (talonneur)
    lock:       1  (deuxième ligne)
    back_row:   1  (flanker OR number_8 — any third-row forward counts)
    scrum_half: 1  (demi de mêlée)
    fly_half:   1  (demi d'ouverture)
    centre:     1  (centre)
    wing:       1  (ailier)
    fullback:   1  (arrière)
    ─────────────────
    TOTAL min:  10 out of 15 bench slots

The 5 remaining bench slots are position-free ("libres").

Multi-position players:
    A player with positions=[fly_half, fullback] contributes +1 to both
    the fly_half group and the fullback group. Coverage counts can therefore
    exceed 1 for a single player — this is intentional and correct.

Incomplete roster:
    Calling validate_roster_coverage() on fewer than ROSTER_SIZE (30) players
    raises RosterIncompleteError. Coverage validation only makes sense on a
    completed draft.

Position order (starters vs bench):
    The function expects players ordered by draft sequence: picks 1–15 are
    starters, picks 16–30 are bench. Only bench players are checked against
    BENCH_COVERAGE_MINIMUMS.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.player import PlayerSummary, PositionType
from draft.validate_pick import ROSTER_SIZE


# ---------------------------------------------------------------------------
# Constants — CDC v3.1 section 6.2
# ---------------------------------------------------------------------------

# Starters occupy the first 15 draft picks. Bench = picks 16–30.
STARTER_COUNT: int = 15

# Minimum bench players required per position group (CDC v3.1, section 6.2).
# Only groups listed here have a minimum. The 5 "libres" slots are unconstrained.
BENCH_COVERAGE_MINIMUMS: dict[str, int] = {
    "prop": 2,
    "hooker": 1,
    "lock": 1,
    "back_row": 1,   # flanker OR number_8 (D-013)
    "scrum_half": 1,
    "fly_half": 1,
    "centre": 1,
    "wing": 1,
    "fullback": 1,
}

# Maps each PositionType enum value to its coverage group name.
# D-013: number_8 is a distinct enum value but counts as "back_row" here.
# A position not listed here (should not exist) is silently ignored.
_POSITION_TO_GROUP: dict[PositionType, str] = {
    PositionType.PROP: "prop",
    PositionType.HOOKER: "hooker",
    PositionType.LOCK: "lock",
    PositionType.FLANKER: "back_row",
    PositionType.NUMBER_8: "back_row",  # D-013
    PositionType.SCRUM_HALF: "scrum_half",
    PositionType.FLY_HALF: "fly_half",
    PositionType.CENTRE: "centre",
    PositionType.WING: "wing",
    PositionType.FULLBACK: "fullback",
}


# ---------------------------------------------------------------------------
# Result and exception types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RosterCoverageResult:
    """Returned by validate_roster_coverage() when the roster is valid.

    Attributes:
        bench_coverage: Actual count per position group among bench players.
                        Informational — useful for frontend roster builder UI.
                        Example: {"prop": 3, "hooker": 1, "lock": 2, ...}
    """

    bench_coverage: dict[str, int]


class RosterCoverageError(Exception):
    """Raised when the roster does not meet bench coverage minimums.

    Unlike PickValidationError (stops at first failure), this error
    collects ALL missing positions. At draft completion, the commissioner
    needs the full picture — partial feedback would require multiple
    iterations to diagnose.

    In practice, this error should only be triggered by autodraft filling
    a roster without enough positional diversity. A human manager is
    guided by the frontend's real-time coverage indicator.

    Attributes:
        missing: Dict of position_group → shortfall count.
                 Example: {"prop": 1, "hooker": 1} means 1 prop and
                 1 hooker are missing from the bench minimums.
        message: Human-readable summary.
        code: Machine-readable error code for frontend i18n key lookup.
    """

    def __init__(self, missing: dict[str, int]) -> None:
        self.missing = missing
        self.code = "ROSTER_COVERAGE_INSUFFICIENT"
        positions_str = ", ".join(
            f"{group} (need {count} more)"
            for group, count in sorted(missing.items())
        )
        self.message = (
            f"Bench coverage insufficient: {positions_str}. "
            "The roster does not meet CDC section 6.2 minimums."
        )
        super().__init__(self.message)


class RosterIncompleteError(Exception):
    """Raised when validate_roster_coverage() is called on a partial roster.

    This indicates a DraftEngine bug: _complete_draft() must only be called
    after all 30 picks have been recorded.

    Attributes:
        actual_count: Number of players actually present.
        code: Machine-readable error code.
    """

    def __init__(self, actual_count: int) -> None:
        self.actual_count = actual_count
        self.code = "ROSTER_INCOMPLETE"
        self.message = (
            f"Cannot validate coverage: expected {ROSTER_SIZE} players, "
            f"got {actual_count}."
        )
        super().__init__(self.message)


# ---------------------------------------------------------------------------
# Core validation function
# ---------------------------------------------------------------------------


def validate_roster_coverage(players: list[PlayerSummary]) -> RosterCoverageResult:
    """Validate that a completed 30-player roster meets bench coverage minimums.

    Only the bench players (index 15–29, i.e. picks 16–30) are checked.
    Starters (index 0–14) are ignored for coverage purposes — the CDC does
    not impose minimums on the starting XV composition at draft time.

    A multi-position player contributes to every group their positions map
    to. A flanker/number_8 covers "back_row" once (not twice — each player
    is counted once per group they belong to, regardless of how many of
    their positions map to the same group).

    All coverage failures are collected before raising — no early exit.

    Args:
        players: 30 PlayerSummary objects, ordered by draft pick number.
                 Index 0 = pick 1 (starter), index 14 = pick 15 (starter),
                 index 15 = pick 16 (first bench pick), index 29 = pick 30.

    Returns:
        RosterCoverageResult — bench_coverage dict with actual counts.

    Raises:
        RosterIncompleteError: If len(players) != ROSTER_SIZE (30).
        RosterCoverageError: If any BENCH_COVERAGE_MINIMUMS requirement is unmet.
    """
    if len(players) != ROSTER_SIZE:
        raise RosterIncompleteError(actual_count=len(players))

    # Only bench players participate in coverage validation.
    bench_players: list[PlayerSummary] = players[STARTER_COUNT:]

    # Count coverage per group. A multi-position player contributes once per
    # distinct group (a flanker/number_8 with both positions still maps to
    # "back_row" only once — deduplicated via set conversion below).
    bench_coverage: dict[str, int] = {group: 0 for group in BENCH_COVERAGE_MINIMUMS}

    for player in bench_players:
        # Deduplicate groups for this player: a player with positions
        # [flanker, number_8] maps both to "back_row" — count once, not twice.
        covered_groups: set[str] = set()
        for position in player.positions:
            group = _POSITION_TO_GROUP.get(position)
            if group is not None and group in bench_coverage:
                covered_groups.add(group)
        for group in covered_groups:
            bench_coverage[group] += 1

    # Collect ALL unmet minimums before raising (full-picture error reporting).
    missing: dict[str, int] = {
        group: minimum - bench_coverage.get(group, 0)
        for group, minimum in BENCH_COVERAGE_MINIMUMS.items()
        if bench_coverage.get(group, 0) < minimum
    }

    if missing:
        raise RosterCoverageError(missing=missing)

    return RosterCoverageResult(bench_coverage=bench_coverage)