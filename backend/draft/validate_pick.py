# backend/draft/validate_pick.py
"""
Pick validation logic for the RugbyDraft snake draft engine.

This module is intentionally pure: no I/O, no database, no FastAPI.
All validation rules come from CDC v3.1, sections 6 and 7.

Three validation layers (applied in order):
    1. Turn validation   — is it this manager's turn?
    2. Player validation — is the player available to be drafted?
    3. Roster validation — will the roster remain valid after this pick?

Each layer raises a typed exception on failure. The DraftEngine catches
these exceptions and maps them to HTTP 422 responses + Realtime broadcast.

Constants (CDC v3.1, section 6 + D-016):
    ROSTER_SIZE         = 30 (15 starters + 15 bench)
    MAX_PER_NATION      = 8  (international competitions)
    MAX_PER_CLUB        = 6  (club competitions)
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.league import CompetitionType
from app.models.player import AvailabilityStatus, PlayerSummary


# ---------------------------------------------------------------------------
# Constants (CDC v3.1 section 6, D-016)
# ---------------------------------------------------------------------------

ROSTER_SIZE: int = 30  # 15 starters + 15 bench per roster
MAX_PER_NATION: int = 8  # max players from same nation (international)
MAX_PER_CLUB: int = 6  # max players from same club (club competition)


# ---------------------------------------------------------------------------
# Typed exceptions — one per validation failure reason
# ---------------------------------------------------------------------------


class PickValidationError(Exception):
    """Base class for all pick validation errors.

    Attributes:
        message: Human-readable error description (for API response body).
        code: Machine-readable error code (for frontend i18n key lookup).
    """

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class NotYourTurnError(PickValidationError):
    """Raised when the manager submits a pick outside their turn."""

    def __init__(self, manager_id: str, expected_manager_id: str) -> None:
        super().__init__(
            message=(
                f"It is not manager '{manager_id}'s turn. "
                f"Expected: '{expected_manager_id}'."
            ),
            code="NOT_YOUR_TURN",
        )


class PlayerAlreadyDraftedError(PickValidationError):
    """Raised when the requested player has already been drafted."""

    def __init__(self, player_id: str) -> None:
        super().__init__(
            message=f"Player '{player_id}' has already been drafted.",
            code="PLAYER_ALREADY_DRAFTED",
        )


class PlayerUnavailableError(PickValidationError):
    """Raised when the player is injured or suspended."""

    def __init__(self, player_id: str, status: AvailabilityStatus) -> None:
        super().__init__(
            message=(
                f"Player '{player_id}' is not available for drafting "
                f"(status: {status})."
            ),
            code="PLAYER_UNAVAILABLE",
        )


class RosterFullError(PickValidationError):
    """Raised when the manager's roster is already at ROSTER_SIZE."""

    def __init__(self, manager_id: str) -> None:
        super().__init__(
            message=(f"Manager '{manager_id}' roster is full ({ROSTER_SIZE} players)."),
            code="ROSTER_FULL",
        )


class NationalityLimitError(PickValidationError):
    """Raised when drafting this player would exceed MAX_PER_NATION."""

    def __init__(self, nationality: str, current_count: int) -> None:
        super().__init__(
            message=(
                f"Cannot draft another '{nationality}' player: "
                f"{current_count}/{MAX_PER_NATION} already in roster."
            ),
            code="NATIONALITY_LIMIT_EXCEEDED",
        )


class ClubLimitError(PickValidationError):
    """Raised when drafting this player would exceed MAX_PER_CLUB."""

    def __init__(self, club: str, current_count: int) -> None:
        super().__init__(
            message=(
                f"Cannot draft another '{club}' player: "
                f"{current_count}/{MAX_PER_CLUB} already in roster."
            ),
            code="CLUB_LIMIT_EXCEEDED",
        )


# ---------------------------------------------------------------------------
# Roster snapshot — input to validation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RosterSnapshot:
    """Lightweight view of a manager's current roster for validation purposes.

    Contains only the data needed to check constraints — no DB objects.

    Attributes:
        manager_id: The manager who owns this roster.
        player_ids: Set of player IDs already drafted by this manager.
        nationalities: List of nationalities of drafted players
                       (one entry per player, duplicates allowed).
        clubs: List of clubs of drafted players
               (one entry per player, duplicates allowed).
    """

    manager_id: str
    player_ids: frozenset[str]
    nationalities: list[str]
    clubs: list[str]

    @property
    def size(self) -> int:
        """Number of players currently in this roster."""
        return len(self.player_ids)

    def nation_count(self, nationality: str) -> int:
        """Count how many players from a given nationality are in the roster."""
        return self.nationalities.count(nationality)

    def club_count(self, club: str) -> int:
        """Count how many players from a given club are in the roster."""
        return self.clubs.count(club)


# ---------------------------------------------------------------------------
# Core validation function
# ---------------------------------------------------------------------------


def validate_pick(
    manager_id: str,
    player_id: str,
    current_pick_number: int,
    draft_order: list[str],
    drafted_player_ids: frozenset[str],
    player: PlayerSummary,
    roster: RosterSnapshot,
    competition_type: CompetitionType,
) -> None:
    """Validate a pick attempt in the snake draft.

    Applies three validation layers in order. Raises a typed exception
    at the first failure — subsequent layers are not evaluated.

    Args:
        manager_id: ID of the manager attempting the pick.
        player_id: ID of the player being picked.
        current_pick_number: The current pick number in the draft (1-indexed).
        draft_order: Full flat snake order list from generate_snake_order().
                     Index 0 = pick 1, index 1 = pick 2, etc.
        drafted_player_ids: Set of player IDs already picked by any manager.
        player: PlayerSummary object with availability, nationality, club.
        roster: RosterSnapshot of the picking manager's current roster.
        competition_type: International (nation limit) or Club (club limit).

    Returns:
        None — returns silently if all validations pass.

    Raises:
        NotYourTurnError: Manager is not the one expected at current_pick_number.
        PlayerAlreadyDraftedError: Player has already been picked.
        PlayerUnavailableError: Player is injured or suspended.
        RosterFullError: Manager's roster has reached ROSTER_SIZE.
        NationalityLimitError: Would exceed MAX_PER_NATION for international.
        ClubLimitError: Would exceed MAX_PER_CLUB for club competition.
    """
    # ── Layer 1: Turn validation ──────────────────────────────────────────────
    _validate_turn(manager_id, current_pick_number, draft_order)

    # ── Layer 2: Player availability validation ───────────────────────────────
    _validate_player_availability(player_id, drafted_player_ids, player)

    # ── Layer 3: Roster constraint validation ─────────────────────────────────
    _validate_roster_constraints(player, roster, competition_type)


# ---------------------------------------------------------------------------
# Internal validation helpers
# ---------------------------------------------------------------------------


def _validate_turn(
    manager_id: str,
    current_pick_number: int,
    draft_order: list[str],
) -> None:
    """Check that it is this manager's turn to pick.

    Args:
        manager_id: The manager attempting the pick.
        current_pick_number: 1-indexed current pick in the draft.
        draft_order: Full flat snake order (0-indexed list).

    Raises:
        NotYourTurnError: If the expected manager differs from manager_id.
    """
    # draft_order is 0-indexed: pick N is at index N-1
    expected_manager_id = draft_order[current_pick_number - 1]
    if manager_id != expected_manager_id:
        raise NotYourTurnError(manager_id, expected_manager_id)


def _validate_player_availability(
    player_id: str,
    drafted_player_ids: frozenset[str],
    player: PlayerSummary,
) -> None:
    """Check that the player is available to be drafted.

    Two sub-checks:
        1. Not already drafted by any manager.
        2. Not injured or suspended.

    Args:
        player_id: The player being picked.
        drafted_player_ids: All players already drafted in this league.
        player: PlayerSummary with availability_status.

    Raises:
        PlayerAlreadyDraftedError: Player is already in a roster.
        PlayerUnavailableError: Player is injured or suspended.
    """
    if player_id in drafted_player_ids:
        raise PlayerAlreadyDraftedError(player_id)

    if player.availability_status != AvailabilityStatus.AVAILABLE:
        raise PlayerUnavailableError(player_id, player.availability_status)


def _validate_roster_constraints(
    player: PlayerSummary,
    roster: RosterSnapshot,
    competition_type: CompetitionType,
) -> None:
    """Check that adding this player keeps the roster within all constraints.

    Checks (in order):
        1. Roster not already full (ROSTER_SIZE = 30).
        2. For international: nationality count <= MAX_PER_NATION.
        3. For club: club count <= MAX_PER_CLUB.

    Args:
        player: The player being considered.
        roster: Current state of the picking manager's roster.
        competition_type: Determines which limit applies.

    Raises:
        RosterFullError: Roster already has ROSTER_SIZE players.
        NationalityLimitError: Would exceed MAX_PER_NATION.
        ClubLimitError: Would exceed MAX_PER_CLUB.
    """
    if roster.size >= ROSTER_SIZE:
        raise RosterFullError(roster.manager_id)

    if competition_type == CompetitionType.INTERNATIONAL:
        current_count = roster.nation_count(player.nationality)
        if current_count >= MAX_PER_NATION:
            raise NationalityLimitError(player.nationality, current_count)

    elif competition_type == CompetitionType.CLUB:
        current_count = roster.club_count(player.club)
        if current_count >= MAX_PER_CLUB:
            raise ClubLimitError(player.club, current_count)
