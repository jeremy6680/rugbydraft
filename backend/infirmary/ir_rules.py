"""
Infirmary business rules — pure functions, no I/O.

Implements CDC §6.4:
- IR slot capacity: 3 players maximum simultaneously.
- Auto-notification on recovery / suspension end (triggered by scheduler).
- 1-week reintegration deadline before waiver/trade blocking activates.
- A player in IR scores no points and does not count toward coverage constraints.

All functions are pure — no database calls, no side effects.
The router and scheduler import these functions and handle all I/O.
"""

from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Constants (single source of truth — CDC §6.4)
# ---------------------------------------------------------------------------

MAX_IR_SLOTS: int = 3
"""Maximum number of players allowed in IR simultaneously."""

IR_REINTEGRATION_DEADLINE_DAYS: int = 7
"""Days after recovery before waiver/trade blocking activates."""


# ---------------------------------------------------------------------------
# Exceptions (one per failure reason — same pattern as validate_pick.py)
# ---------------------------------------------------------------------------


class IRError(Exception):
    """Base class for all infirmary errors.

    Attributes:
        code: Machine-readable error code used as i18n key in the frontend.
        message: Human-readable description (English, for logs).
    """

    code: str = "ir_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class IRCapacityError(IRError):
    """Raised when placing a player would exceed MAX_IR_SLOTS."""

    code = "ir_capacity_exceeded"


class IRPlayerAlreadyInIRError(IRError):
    """Raised when the player is already in the IR slot."""

    code = "ir_player_already_in_ir"


class IRPlayerNotRecoveredError(IRError):
    """Raised when trying to reintegrate a player who is still injured."""

    code = "ir_player_not_recovered"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IRSlotSnapshot:
    """Immutable snapshot of a roster's current IR state.

    Passed to validation functions — decouples rules from DB objects.

    Attributes:
        roster_id: UUID of the roster owning these IR slots.
        current_ir_player_ids: Set of player IDs currently in IR.
        recovered_player_ids: Set of player IDs marked as recovered
            (available for reintegration).
    """

    roster_id: str
    current_ir_player_ids: set[str]
    recovered_player_ids: set[str]


# ---------------------------------------------------------------------------
# Pure rule functions
# ---------------------------------------------------------------------------


def calculate_recovery_deadline(recovery_date: datetime) -> datetime:
    """Return the reintegration deadline for a recovered player.

    The deadline is recovery_date + IR_REINTEGRATION_DEADLINE_DAYS.
    Always returned as UTC-aware datetime.

    Args:
        recovery_date: The date/time the player was marked as recovered.
            If naive (no tzinfo), assumed to be UTC.

    Returns:
        UTC-aware datetime representing the reintegration deadline.

    Example:
        >>> from datetime import datetime, timezone
        >>> recovery = datetime(2026, 3, 22, 9, 0, tzinfo=timezone.utc)
        >>> calculate_recovery_deadline(recovery)
        datetime.datetime(2026, 3, 29, 9, 0, tzinfo=datetime.timezone.utc)
    """
    if recovery_date.tzinfo is None:
        recovery_date = recovery_date.replace(tzinfo=timezone.utc)
    return recovery_date + timedelta(days=IR_REINTEGRATION_DEADLINE_DAYS)


def is_reintegration_overdue(
    ir_recovery_deadline: datetime,
    now: datetime | None = None,
) -> bool:
    """Return True if the reintegration deadline has passed.

    Args:
        ir_recovery_deadline: The deadline timestamp (from weekly_lineups).
            If naive, assumed to be UTC.
        now: Current timestamp. Defaults to datetime.now(UTC).
            Injectable for deterministic testing.

    Returns:
        True if now > ir_recovery_deadline, False otherwise.

    Example:
        >>> from datetime import datetime, timezone, timedelta
        >>> deadline = datetime(2026, 3, 22, 9, 0, tzinfo=timezone.utc)
        >>> is_reintegration_overdue(deadline, now=deadline + timedelta(seconds=1))
        True
        >>> is_reintegration_overdue(deadline, now=deadline - timedelta(seconds=1))
        False
    """
    if now is None:
        now = datetime.now(timezone.utc)
    if ir_recovery_deadline.tzinfo is None:
        ir_recovery_deadline = ir_recovery_deadline.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now > ir_recovery_deadline


def validate_ir_placement(
    player_id: str,
    snapshot: IRSlotSnapshot,
) -> None:
    """Validate that a player can be placed in the IR slot.

    Checks (in order):
    1. Player is not already in IR (IRPlayerAlreadyInIRError).
    2. IR capacity is not exceeded (IRCapacityError).

    Does NOT check whether the player is actually injured — that is the
    connector's responsibility (stg_player_availability). The router
    verifies availability status before calling this function.

    Args:
        player_id: ID of the player to place in IR.
        snapshot: Current IR state of the roster.

    Raises:
        IRPlayerAlreadyInIRError: If the player is already in IR.
        IRCapacityError: If placing this player would exceed MAX_IR_SLOTS.
    """
    if player_id in snapshot.current_ir_player_ids:
        raise IRPlayerAlreadyInIRError(
            f"Player {player_id} is already in the IR slot "
            f"for roster {snapshot.roster_id}."
        )

    if len(snapshot.current_ir_player_ids) >= MAX_IR_SLOTS:
        raise IRCapacityError(
            f"IR capacity exceeded for roster {snapshot.roster_id}: "
            f"{len(snapshot.current_ir_player_ids)}/{MAX_IR_SLOTS} slots used. "
            f"Reintegrate a player before adding {player_id}."
        )


def validate_ir_reintegration(
    player_id: str,
    snapshot: IRSlotSnapshot,
) -> None:
    """Validate that a player can be reintegrated from IR.

    Checks (in order):
    1. Player is currently in IR (IRPlayerAlreadyInIRError used as "not in IR").
    2. Player is marked as recovered (IRPlayerNotRecoveredError).

    Args:
        player_id: ID of the player to reintegrate.
        snapshot: Current IR state of the roster.

    Raises:
        IRError: If the player is not in IR.
        IRPlayerNotRecoveredError: If the player is still injured/suspended.
    """
    if player_id not in snapshot.current_ir_player_ids:
        raise IRError(
            f"Player {player_id} is not in IR for roster {snapshot.roster_id}. "
            "Cannot reintegrate."
        )

    if player_id not in snapshot.recovered_player_ids:
        raise IRPlayerNotRecoveredError(
            f"Player {player_id} is still injured or suspended. "
            "Cannot reintegrate until recovery is confirmed."
        )


def get_overdue_ir_slots(
    ir_slots: list[dict],
    now: datetime | None = None,
) -> list[dict]:
    """Filter IR slots whose reintegration deadline has passed.

    Called by the daily scheduler to build the list of rosters to block.

    Args:
        ir_slots: List of dicts with keys:
            - roster_id (str)
            - player_id (str)
            - ir_recovery_deadline (datetime)
        now: Current timestamp. Defaults to datetime.now(UTC).

    Returns:
        Subset of ir_slots where is_reintegration_overdue() is True.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    return [
        slot
        for slot in ir_slots
        if slot.get("ir_recovery_deadline") is not None
        and is_reintegration_overdue(slot["ir_recovery_deadline"], now=now)
    ]
