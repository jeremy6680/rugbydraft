# backend/draft/assisted.py
"""
Assisted Draft logic for the RugbyDraft snake draft engine.

Assisted Draft (Draft Assistée) is a fallback mode where the commissioner
enters picks manually on behalf of all managers, with no timer.

CDC v3.1, section 7.5:
    - Activated by the commissioner via a dedicated action.
    - The commissioner enters picks one by one, in snake order, with no timer.
    - Every pick is stamped with a timestamp and marked "entered by commissioner".
    - The resulting roster is identical to a standard synchronous draft.
    - The audit log is visible to all managers.

This module is intentionally pure: no I/O, no database, no FastAPI, no asyncio.
All types and validation functions live here and are called by DraftEngine.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class AssistedPickAuditEntry:
    """A single entry in the assisted draft audit log.

    Created for every pick made while assisted_mode is active.
    Persisted to draft_picks.entered_by_commissioner in the DB.

    Attributes:
        pick_number: Absolute pick number (1-indexed), same as PickRecord.
        manager_id: Manager whose turn it was (from draft order).
        player_id: Player who was picked.
        commissioner_id: User ID of the commissioner who entered the pick.
        timestamp: Unix time when the pick was recorded.
    """

    pick_number: int
    manager_id: str
    player_id: str
    commissioner_id: str
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


class AssistedDraftError(Exception):
    """Base class for assisted draft errors.

    Attributes:
        message: Human-readable description.
        code: Machine-readable code for frontend i18n lookup.
    """

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class AssistedModeNotActiveError(AssistedDraftError):
    """Raised when a commissioner tries to submit an assisted pick
    but assisted mode is not active."""

    def __init__(self) -> None:
        super().__init__(
            message="Assisted mode is not active on this draft.",
            code="ASSISTED_MODE_NOT_ACTIVE",
        )


class NotCommissionerError(AssistedDraftError):
    """Raised when a non-commissioner user attempts an assisted-only action."""

    def __init__(self, user_id: str) -> None:
        super().__init__(
            message=f"User '{user_id}' is not the commissioner of this league.",
            code="NOT_COMMISSIONER",
        )


class AssistedModeAlreadyActiveError(AssistedDraftError):
    """Raised when the commissioner tries to enable assisted mode
    but it is already active."""

    def __init__(self) -> None:
        super().__init__(
            message="Assisted mode is already active.",
            code="ASSISTED_MODE_ALREADY_ACTIVE",
        )


# ---------------------------------------------------------------------------
# Pure validation functions
# ---------------------------------------------------------------------------


def validate_commissioner(user_id: str, commissioner_id: str) -> None:
    """Check that the user performing the action is the league commissioner.

    Args:
        user_id: ID of the user attempting the action.
        commissioner_id: ID of the actual league commissioner.

    Raises:
        NotCommissionerError: If user_id does not match commissioner_id.
    """
    if user_id != commissioner_id:
        raise NotCommissionerError(user_id)


def validate_assisted_mode_active(assisted_mode: bool) -> None:
    """Check that assisted mode is currently active.

    Args:
        assisted_mode: Current value of DraftState.assisted_mode.

    Raises:
        AssistedModeNotActiveError: If assisted mode is not active.
    """
    if not assisted_mode:
        raise AssistedModeNotActiveError()


def validate_assisted_mode_not_already_active(assisted_mode: bool) -> None:
    """Check that assisted mode is NOT already active (used before enabling).

    Args:
        assisted_mode: Current value of DraftState.assisted_mode.

    Raises:
        AssistedModeAlreadyActiveError: If assisted mode is already active.
    """
    if assisted_mode:
        raise AssistedModeAlreadyActiveError()


def build_audit_entry(
    pick_number: int,
    manager_id: str,
    player_id: str,
    commissioner_id: str,
    timestamp: Optional[float] = None,
) -> AssistedPickAuditEntry:
    """Build an audit log entry for a commissioner-entered pick.

    Args:
        pick_number: Absolute pick number in the draft.
        manager_id: Manager whose turn it was.
        player_id: Player selected.
        commissioner_id: User ID of the commissioner who made the entry.
        timestamp: Unix timestamp. Defaults to now if not provided.

    Returns:
        AssistedPickAuditEntry ready to be appended to the audit log.
    """
    return AssistedPickAuditEntry(
        pick_number=pick_number,
        manager_id=manager_id,
        player_id=player_id,
        commissioner_id=commissioner_id,
        timestamp=timestamp if timestamp is not None else time.time(),
    )
