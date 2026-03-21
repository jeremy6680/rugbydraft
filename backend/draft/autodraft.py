# backend/draft/autodraft.py
"""
Autodraft pick selection algorithm for RugbyDraft.

Autodraft activates in three cases (CDC v3.1, section 7.3):
    1. Timer expiration — manager did not pick within their time window.
    2. Manager never connected — full autodraft from draft start.
    3. Manual activation — manager chose to let the system pick for them.

Selection logic (two priority levels):
    1. Preference list — the manager's personal ranked list of player IDs.
       The first player in the list who is available AND passes roster
       constraints is selected.
    2. Default value algorithm — if the preference list is empty or
       exhausted, pick the highest-value available player that passes
       roster constraints.

This module is intentionally pure: no I/O, no database, no FastAPI.
The caller (DraftEngine) is responsible for:
    - Pre-sorting available_players by value_score descending.
    - Building the RosterSnapshot from the in-memory DraftState.
    - Calling validate_pick() after selection to confirm the pick.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.models.league import CompetitionType
from app.models.player import PlayerSummary
from draft.validate_pick import PickValidationError, RosterSnapshot, _validate_roster_constraints

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AutodraftError(Exception):
    """Raised when autodraft cannot find any valid player to pick.

    This should never happen in a well-formed draft (the player pool
    always has enough available players for all rosters). If it does,
    it indicates a data integrity issue — the DraftEngine must log it
    and halt the draft.
    """

    def __init__(self, manager_id: str, reason: str) -> None:
        super().__init__(
            f"Autodraft failed for manager '{manager_id}': {reason}"
        )
        self.manager_id = manager_id
        self.reason = reason


# ---------------------------------------------------------------------------
# Input / output types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AutodraftResult:
    """The result of an autodraft selection.

    Attributes:
        player_id: The ID of the selected player.
        player: Full PlayerSummary of the selected player.
        source: How the player was selected — 'preference_list' or 'default_value'.
    """

    player_id: str
    player: PlayerSummary
    source: str  # "preference_list" | "default_value"


# ---------------------------------------------------------------------------
# Core autodraft function
# ---------------------------------------------------------------------------


def select_autodraft_pick(
    manager_id: str,
    preference_list: list[str],
    available_players: list[PlayerSummary],
    roster: RosterSnapshot,
    competition_type: CompetitionType,
) -> AutodraftResult:
    """Select the best available player for an autodraft pick.

    Selection algorithm:
        1. Scan the preference_list in order. For each player ID in the list,
           check if they are available (in available_players) and pass roster
           constraints. Return the first match.
        2. If no preference match found, scan available_players in order
           (pre-sorted by value_score descending by the caller). Return the
           first player that passes roster constraints.

    Args:
        manager_id: ID of the manager for whom we are autodrafting.
        preference_list: Ordered list of player IDs the manager ranked
                         manually. May be empty.
        available_players: All players not yet drafted, not injured/suspended.
                           Must be pre-sorted by value_score descending.
        roster: Current state of the manager's roster (for constraint checks).
        competition_type: International or club (determines which limit applies).

    Returns:
        AutodraftResult with the selected player and selection source.

    Raises:
        AutodraftError: If no valid player can be found (data integrity issue).
    """
    # Build a lookup map for O(1) access by player ID
    player_map: dict[str, PlayerSummary] = {
        str(p.id): p for p in available_players
    }

    # ── Priority 1: preference list ───────────────────────────────────────────
    result = _select_from_preference_list(
        manager_id=manager_id,
        preference_list=preference_list,
        player_map=player_map,
        roster=roster,
        competition_type=competition_type,
    )
    if result is not None:
        logger.debug(
            "Autodraft [%s]: selected '%s' from preference list",
            manager_id,
            result.player_id,
        )
        return result

    # ── Priority 2: default value algorithm ───────────────────────────────────
    result = _select_by_default_value(
        manager_id=manager_id,
        available_players=available_players,
        roster=roster,
        competition_type=competition_type,
    )
    if result is not None:
        logger.debug(
            "Autodraft [%s]: selected '%s' by default value",
            manager_id,
            result.player_id,
        )
        return result

    # ── No valid player found — data integrity issue ──────────────────────────
    raise AutodraftError(
        manager_id=manager_id,
        reason=(
            f"No valid player found in pool of {len(available_players)} "
            f"available players after checking all roster constraints."
        ),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _select_from_preference_list(
    manager_id: str,
    preference_list: list[str],
    player_map: dict[str, PlayerSummary],
    roster: RosterSnapshot,
    competition_type: CompetitionType,
) -> AutodraftResult | None:
    """Scan the preference list and return the first valid pick.

    A player is valid if:
        - They are in the available player pool (not drafted, not injured).
        - They pass roster constraints (not full, within nation/club limits).

    Args:
        manager_id: Manager ID (for logging and AutodraftResult).
        preference_list: Ordered list of preferred player IDs.
        player_map: Dict of available players keyed by player ID.
        roster: Current roster snapshot.
        competition_type: International or club.

    Returns:
        AutodraftResult if a valid player is found, None otherwise.
    """
    for player_id in preference_list:
        player = player_map.get(player_id)

        if player is None:
            # Player is not available (already drafted or unavailable) — skip
            continue

        if _passes_roster_constraints(player, roster, competition_type):
            return AutodraftResult(
                player_id=player_id,
                player=player,
                source="preference_list",
            )

    return None


def _select_by_default_value(
    manager_id: str,
    available_players: list[PlayerSummary],
    roster: RosterSnapshot,
    competition_type: CompetitionType,
) -> AutodraftResult | None:
    """Select the highest-value available player that passes constraints.

    available_players must be pre-sorted by value_score descending.
    This function iterates in order and returns the first valid player.

    Args:
        manager_id: Manager ID (for AutodraftResult).
        available_players: Players sorted by value_score descending.
        roster: Current roster snapshot.
        competition_type: International or club.

    Returns:
        AutodraftResult if a valid player is found, None otherwise.
    """
    for player in available_players:
        if _passes_roster_constraints(player, roster, competition_type):
            return AutodraftResult(
                player_id=str(player.id),
                player=player,
                source="default_value",
            )

    return None


def _passes_roster_constraints(
    player: PlayerSummary,
    roster: RosterSnapshot,
    competition_type: CompetitionType,
) -> bool:
    """Return True if adding this player keeps the roster within all constraints.

    Reuses _validate_roster_constraints() from validate_pick — single
    source of truth for roster rules. Catches PickValidationError and
    returns False instead of propagating.

    Note: RosterFullError is intentionally NOT caught here. If the roster
    is full, autodraft should never have been triggered — it indicates
    a logic error in the DraftEngine. We let it propagate.

    Args:
        player: Candidate player.
        roster: Current roster snapshot.
        competition_type: International or club.

    Returns:
        True if constraints pass, False if nationality/club limit would be exceeded.
    """
    try:
        _validate_roster_constraints(player, roster, competition_type)
        return True
    except PickValidationError:
        return False