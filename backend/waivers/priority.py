"""Waiver priority ordering — pure functions, no I/O.

Priority rule (CDC 9.1): lowest-ranked manager gets highest waiver priority.
Tiebreaker: lowest season_total_points (mirrors DENSE_RANK tiebreaker in
mart_leaderboard).

Ghost teams are excluded from waiver priority — they never claim waivers
(CDC section 11). Filtering ghost teams out is the caller's responsibility;
these functions operate on whatever list is passed in.
"""

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ManagerStanding:
    """Snapshot of one manager's league standing used for priority ordering.

    Attributes:
        member_id: UUID string identifying the league member.
        rank: Dense rank within the league (1 = first place). Sourced from
            mart_leaderboard.rank. Lower rank = better position = lower
            waiver priority.
        season_total_points: Cumulative fantasy points. Used as tiebreaker
            when two managers share the same rank: fewer points = higher
            waiver priority.
    """

    member_id: str
    rank: int
    season_total_points: float


@dataclass(frozen=True)
class WaiverPrioritySlot:
    """One entry in the ordered waiver priority list.

    Attributes:
        priority: 1-based position in the waiver queue (1 = highest priority).
        member_id: UUID string identifying the league member.
    """

    priority: int
    member_id: str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_waiver_priority(
    standings: list[ManagerStanding],
) -> list[WaiverPrioritySlot]:
    """Compute the ordered waiver priority list from current league standings.

    Managers are sorted by ascending rank (highest rank number = worst position
    = highest waiver priority). Tiebreaker: ascending season_total_points
    (fewest points = higher priority within the same rank).

    Args:
        standings: List of ManagerStanding snapshots. Must not include ghost
            teams — filter them before calling this function.

    Returns:
        Ordered list of WaiverPrioritySlot, priority 1 = highest priority
        (served first). Empty list if standings is empty.

    Example:
        >>> standings = [
        ...     ManagerStanding("A", rank=1, season_total_points=120.0),
        ...     ManagerStanding("B", rank=3, season_total_points=80.0),
        ...     ManagerStanding("C", rank=2, season_total_points=95.0),
        ...     ManagerStanding("D", rank=3, season_total_points=75.0),
        ... ]
        >>> compute_waiver_priority(standings)
        [
            WaiverPrioritySlot(priority=1, member_id="D"),  # rank 3, fewer pts
            WaiverPrioritySlot(priority=2, member_id="B"),  # rank 3, more pts
            WaiverPrioritySlot(priority=3, member_id="C"),  # rank 2
            WaiverPrioritySlot(priority=4, member_id="A"),  # rank 1
        ]
    """
    sorted_standings = sorted(
        standings,
        key=lambda s: (-(s.rank), s.season_total_points),
    )

    return [
        WaiverPrioritySlot(priority=i + 1, member_id=s.member_id)
        for i, s in enumerate(sorted_standings)
    ]


def get_member_priority(
    member_id: str,
    priority_list: list[WaiverPrioritySlot],
) -> int:
    """Return the waiver priority (1-based) for a given member.

    Args:
        member_id: UUID string of the league member.
        priority_list: Output of compute_waiver_priority().

    Returns:
        Priority integer (1 = highest). Returns len(priority_list) + 1
        (last position) if the member is not found — defensive fallback,
        should not happen in normal operation.
    """
    for slot in priority_list:
        if slot.member_id == member_id:
            return slot.priority

    # Defensive fallback — member not in standings (should not occur)
    return len(priority_list) + 1
