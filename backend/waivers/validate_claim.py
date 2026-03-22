"""Waiver claim validation — pure functions, no I/O.

Validates a single waiver claim against all business rules (CDC 9.1).
All contextual data (IR status, player availability, roster membership)
is passed in as arguments — no database access in this module.

Validation order (fail-fast, cheapest checks first):
    1. Waiver window is open
    2. Claimant is not a ghost team
    3. No unintegrated recovered IR player (blocking rule)
    4. Player to add is free (not in any roster in this league)
    5. Player to drop is owned by the claimant (if a drop is requested)
"""

from dataclasses import dataclass
from datetime import datetime


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WaiverClaimRequest:
    """Input data for a single waiver claim validation.

    Attributes:
        member_id: UUID of the league member submitting the claim.
        league_id: UUID of the league.
        add_player_id: UUID of the free agent the manager wants to add.
        drop_player_id: UUID of the rostered player to drop in exchange.
            None if the manager has a roster slot available without dropping.
        is_ghost_team: True if this member is a ghost team.
        has_unintegrated_recovered_ir_player: True if the manager has a
            player in IR whose availability status is 'available' and whose
            recovery was confirmed more than 7 days ago. Resolved by the
            service layer before calling validate_claim().
        add_player_is_free: True if add_player_id is not in any roster
            in this league. Resolved by the service layer.
        drop_player_is_owned: True if drop_player_id is in this manager's
            roster. Always True when drop_player_id is None (no drop needed).
    """

    member_id: str
    league_id: str
    add_player_id: str
    drop_player_id: str | None
    is_ghost_team: bool
    has_unintegrated_recovered_ir_player: bool
    add_player_is_free: bool
    drop_player_is_owned: bool


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class WaiverClaimError(Exception):
    """Base class for all waiver claim validation errors."""


class WaiverWindowClosedError(WaiverClaimError):
    """Claim submitted outside the Tuesday 07:00 — Wednesday 23:59:59 window."""


class GhostTeamCannotClaimError(WaiverClaimError):
    """Ghost teams are excluded from waiver participation (CDC section 11)."""


class IRBlockingRuleError(WaiverClaimError):
    """Manager has a recovered IR player not reintegrated for more than 7 days.

    The manager must move the recovered player from IR to starter or bench
    before submitting any waiver claim (CDC 9.1).
    """


class PlayerNotFreeError(WaiverClaimError):
    """The player to add is already on a roster in this league."""


class DropPlayerNotOwnedError(WaiverClaimError):
    """The player to drop is not in this manager's roster."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_claim(
    claim: WaiverClaimRequest,
    now: datetime | None = None,
) -> None:
    """Validate a waiver claim against all business rules.

    Raises the appropriate WaiverClaimError subclass on the first
    failing rule (fail-fast). Returns None on success.

    Args:
        claim: The claim request with all contextual flags pre-resolved
            by the service layer.
        now: Current datetime for window check. Defaults to
            datetime.now(WAIVER_TIMEZONE). Injected explicitly in tests.

    Raises:
        WaiverWindowClosedError: Outside the waiver window.
        GhostTeamCannotClaimError: Claimant is a ghost team.
        IRBlockingRuleError: Manager has an unintegrated recovered IR player.
        PlayerNotFreeError: The player to add is already rostered.
        DropPlayerNotOwnedError: The player to drop is not owned by claimant.
    """
    # Rule 1 — waiver window (import here to avoid circular dependency)
    from waivers.window import is_waiver_window_open

    if not is_waiver_window_open(now):
        raise WaiverWindowClosedError(
            "Waiver claims are only accepted from Tuesday 07:00 to "
            "Wednesday 23:59:59 (Paris time)."
        )

    # Rule 2 — ghost team exclusion
    if claim.is_ghost_team:
        raise GhostTeamCannotClaimError(
            f"Member {claim.member_id} is a ghost team and cannot claim waivers."
        )

    # Rule 3 — IR blocking rule
    if claim.has_unintegrated_recovered_ir_player:
        raise IRBlockingRuleError(
            "You have a recovered player in IR who has not been reintegrated "
            "for more than 7 days. Reintegrate them before claiming waivers."
        )

    # Rule 4 — player to add must be free
    if not claim.add_player_is_free:
        raise PlayerNotFreeError(
            f"Player {claim.add_player_id} is already on a roster in this league."
        )

    # Rule 5 — player to drop must be owned (only if a drop is requested)
    if claim.drop_player_id is not None and not claim.drop_player_is_owned:
        raise DropPlayerNotOwnedError(
            f"Player {claim.drop_player_id} is not in your roster."
        )
