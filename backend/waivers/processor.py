"""Waiver cycle processor — pure functions, no I/O.

Processes a full waiver cycle: given a list of pending claims and the
current priority ordering, returns the resolution for each claim.

Rules:
- Claims are processed in waiver priority order (lowest-ranked manager first).
- Each manager can receive at most one player per cycle.
- Once a player is claimed, they are removed from the free pool for all
  subsequent claims in the same cycle.
- Ghost teams have no claims — filtered out before reaching this module.
"""

from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class ClaimStatus(str, Enum):
    """Resolution status for a single waiver claim after cycle processing."""

    PENDING = "pending"  # Not yet processed (pre-cycle state)
    GRANTED = "granted"  # Player successfully claimed
    DENIED = "denied"  # Player already taken by a higher-priority manager
    SKIPPED = "skipped"  # Manager already received a player this cycle


@dataclass(frozen=True)
class PendingClaim:
    """A single waiver claim awaiting processing.

    Attributes:
        waiver_id: UUID of the waiver row in the database.
        member_id: UUID of the league member who submitted the claim.
        add_player_id: UUID of the free agent to claim.
        drop_player_id: UUID of the player to drop, or None if no drop needed.
        member_priority: Waiver priority for this manager (1 = highest).
            Sourced from compute_waiver_priority() output.
        claim_rank: Manager's own ordering of their claims (1 = most wanted).
            Allows a manager to submit multiple claims with a preference order.
    """

    waiver_id: str
    member_id: str
    add_player_id: str
    drop_player_id: str | None
    member_priority: int
    claim_rank: int


@dataclass(frozen=True)
class ClaimResult:
    """Resolution of a single waiver claim after cycle processing.

    Attributes:
        waiver_id: UUID of the processed waiver row.
        member_id: UUID of the league member.
        add_player_id: UUID of the player that was (or would have been) claimed.
        drop_player_id: UUID of the player dropped, or None.
        status: Final status after processing.
    """

    waiver_id: str
    member_id: str
    add_player_id: str
    drop_player_id: str | None
    status: ClaimStatus


@dataclass
class CycleResult:
    """Full output of a waiver cycle run.

    Attributes:
        results: Resolution for every pending claim processed this cycle.
        granted_count: Number of claims that were granted.
        denied_count: Number of claims that were denied.
        skipped_count: Number of claims skipped (manager already served).
    """

    results: list[ClaimResult] = field(default_factory=list)

    @property
    def granted_count(self) -> int:
        """Number of granted claims."""
        return sum(1 for r in self.results if r.status == ClaimStatus.GRANTED)

    @property
    def denied_count(self) -> int:
        """Number of denied claims."""
        return sum(1 for r in self.results if r.status == ClaimStatus.DENIED)

    @property
    def skipped_count(self) -> int:
        """Number of skipped claims."""
        return sum(1 for r in self.results if r.status == ClaimStatus.SKIPPED)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def process_waiver_cycle(
    pending_claims: list[PendingClaim],
    free_player_ids: set[str],
) -> CycleResult:
    """Process a full waiver cycle and return the resolution for each claim.

    Claims are processed in waiver priority order (member_priority ASC),
    then by the manager's own preference order (claim_rank ASC).

    Each manager receives at most one player per cycle. Once a player is
    granted, they are removed from free_player_ids for all subsequent claims.

    This function does not mutate the database. The caller (waiver_service)
    is responsible for persisting results and updating roster_slots.

    Args:
        pending_claims: All claims with status=PENDING for this cycle.
            Must already have member_priority populated from the current
            standings (compute_waiver_priority output).
        free_player_ids: Set of player UUIDs not currently on any roster
            in this league. This set is copied internally — the original
            is not mutated.

    Returns:
        CycleResult with a ClaimResult for every input claim.
    """
    if not pending_claims:
        return CycleResult()

    # Work on a local copy — do not mutate the caller's set
    available: set[str] = set(free_player_ids)

    # Track which managers have already received a player this cycle
    served_members: set[str] = set()

    # Sort: primary = member_priority ASC (1 = best priority = served first)
    #       secondary = claim_rank ASC (manager's own preference order)
    sorted_claims = sorted(
        pending_claims,
        key=lambda c: (c.member_priority, c.claim_rank),
    )

    results: list[ClaimResult] = []

    for claim in sorted_claims:
        # This manager already received a player this cycle
        if claim.member_id in served_members:
            results.append(
                ClaimResult(
                    waiver_id=claim.waiver_id,
                    member_id=claim.member_id,
                    add_player_id=claim.add_player_id,
                    drop_player_id=claim.drop_player_id,
                    status=ClaimStatus.SKIPPED,
                )
            )
            continue

        # The player this manager wants has already been claimed
        if claim.add_player_id not in available:
            results.append(
                ClaimResult(
                    waiver_id=claim.waiver_id,
                    member_id=claim.member_id,
                    add_player_id=claim.add_player_id,
                    drop_player_id=claim.drop_player_id,
                    status=ClaimStatus.DENIED,
                )
            )
            continue

        # Grant the claim
        available.discard(claim.add_player_id)
        served_members.add(claim.member_id)
        results.append(
            ClaimResult(
                waiver_id=claim.waiver_id,
                member_id=claim.member_id,
                add_player_id=claim.add_player_id,
                drop_player_id=claim.drop_player_id,
                status=ClaimStatus.GRANTED,
            )
        )

    return CycleResult(results=results)
