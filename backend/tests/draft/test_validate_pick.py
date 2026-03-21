# tests/draft/test_validate_pick.py
"""
Unit tests for pick validation logic.

All tests are synchronous — validate_pick() is a pure function.
No async, no DB, no FastAPI required.

Coverage:
    - Turn validation: correct turn, wrong manager
    - Player availability: already drafted, injured, suspended
    - Roster constraints: full roster, nationality limit, club limit
    - Happy path: valid pick passes all layers silently
"""

from uuid import uuid4

import pytest

from app.models.league import CompetitionType
from app.models.player import AvailabilityStatus, PlayerSummary, PositionType
from draft.snake_order import generate_snake_order
from draft.validate_pick import (
    MAX_PER_CLUB,
    MAX_PER_NATION,
    ROSTER_SIZE,
    ClubLimitError,
    NationalityLimitError,
    NotYourTurnError,
    PickValidationError,
    PlayerAlreadyDraftedError,
    PlayerUnavailableError,
    RosterFullError,
    RosterSnapshot,
    validate_pick,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def make_player(
    nationality: str = "FRA",
    club: str = "Stade Toulousain",
    status: AvailabilityStatus = AvailabilityStatus.AVAILABLE,
) -> PlayerSummary:
    """Create a minimal PlayerSummary for testing."""
    return PlayerSummary(
        id=uuid4(),
        first_name="Antoine",
        last_name="Dupont",
        nationality=nationality,
        club=club,
        positions=[PositionType.SCRUM_HALF],
        availability_status=status,
    )


def make_roster(
    manager_id: str = "M1",
    player_ids: list[str] | None = None,
    nationalities: list[str] | None = None,
    clubs: list[str] | None = None,
) -> RosterSnapshot:
    """Create a RosterSnapshot for testing."""
    ids = frozenset(player_ids or [])
    return RosterSnapshot(
        manager_id=manager_id,
        player_ids=ids,
        nationalities=nationalities or [],
        clubs=clubs or [],
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestValidatePickHappyPath:
    """Valid picks must pass silently (return None)."""

    def test_valid_pick_international(self) -> None:
        """First pick of a draft — all constraints satisfied."""
        managers = ["M1", "M2", "M3"]
        order = generate_snake_order(managers, num_rounds=30)
        player = make_player(nationality="FRA", club="Stade Toulousain")
        player_id = str(player.id)
        roster = make_roster(manager_id="M1")

        result = validate_pick(
            manager_id="M1",
            player_id=player_id,
            current_pick_number=1,
            draft_order=order,
            drafted_player_ids=frozenset(),
            player=player,
            roster=roster,
            competition_type=CompetitionType.INTERNATIONAL,
        )
        assert result is None

    def test_valid_pick_club_competition(self) -> None:
        """Valid pick in a club competition."""
        managers = ["M1", "M2"]
        order = generate_snake_order(managers, num_rounds=30)
        player = make_player(nationality="FRA", club="Stade Toulousain")
        player_id = str(player.id)
        roster = make_roster(manager_id="M1")

        result = validate_pick(
            manager_id="M1",
            player_id=player_id,
            current_pick_number=1,
            draft_order=order,
            drafted_player_ids=frozenset(),
            player=player,
            roster=roster,
            competition_type=CompetitionType.CLUB,
        )
        assert result is None

    def test_valid_pick_mid_draft(self) -> None:
        """Valid pick in the middle of a draft (snake reversal)."""
        managers = ["M1", "M2", "M3"]
        order = generate_snake_order(managers, num_rounds=30)
        # Pick 4 belongs to M3 (first pick of round 2, snake reversed)
        player = make_player()
        player_id = str(player.id)
        roster = make_roster(manager_id="M3")

        result = validate_pick(
            manager_id="M3",
            player_id=player_id,
            current_pick_number=4,
            draft_order=order,
            drafted_player_ids=frozenset(),
            player=player,
            roster=roster,
            competition_type=CompetitionType.INTERNATIONAL,
        )
        assert result is None


# ---------------------------------------------------------------------------
# Layer 1: Turn validation
# ---------------------------------------------------------------------------


class TestTurnValidation:
    """Tests for NotYourTurnError."""

    def test_wrong_manager_raises(self) -> None:
        """M2 trying to pick on M1's turn must fail."""
        managers = ["M1", "M2", "M3"]
        order = generate_snake_order(managers, num_rounds=30)
        player = make_player()
        roster = make_roster(manager_id="M2")

        with pytest.raises(NotYourTurnError) as exc_info:
            validate_pick(
                manager_id="M2",  # not M1's turn
                player_id=str(player.id),
                current_pick_number=1,  # M1's turn
                draft_order=order,
                drafted_player_ids=frozenset(),
                player=player,
                roster=roster,
                competition_type=CompetitionType.INTERNATIONAL,
            )

        err = exc_info.value
        assert err.code == "NOT_YOUR_TURN"
        assert "M2" in err.message
        assert "M1" in err.message

    def test_not_your_turn_is_pick_validation_error(self) -> None:
        """NotYourTurnError must be a subclass of PickValidationError."""
        managers = ["M1", "M2"]
        order = generate_snake_order(managers, num_rounds=30)
        player = make_player()
        roster = make_roster(manager_id="M2")

        with pytest.raises(PickValidationError):
            validate_pick(
                manager_id="M2",
                player_id=str(player.id),
                current_pick_number=1,
                draft_order=order,
                drafted_player_ids=frozenset(),
                player=player,
                roster=roster,
                competition_type=CompetitionType.INTERNATIONAL,
            )

    def test_correct_manager_snake_round(self) -> None:
        """Correct manager on a snake (reversed) round must pass turn check."""
        managers = ["M1", "M2", "M3"]
        order = generate_snake_order(managers, num_rounds=30)
        # Pick 6: last pick of round 2 — belongs to M1 (snake reversed)
        player = make_player()
        roster = make_roster(manager_id="M1")

        # Should not raise NotYourTurnError
        try:
            validate_pick(
                manager_id="M1",
                player_id=str(player.id),
                current_pick_number=6,
                draft_order=order,
                drafted_player_ids=frozenset(),
                player=player,
                roster=roster,
                competition_type=CompetitionType.INTERNATIONAL,
            )
        except NotYourTurnError:
            pytest.fail("NotYourTurnError raised unexpectedly for correct manager")


# ---------------------------------------------------------------------------
# Layer 2: Player availability
# ---------------------------------------------------------------------------


class TestPlayerAvailability:
    """Tests for PlayerAlreadyDraftedError and PlayerUnavailableError."""

    def test_already_drafted_player_raises(self) -> None:
        managers = ["M1", "M2"]
        order = generate_snake_order(managers, num_rounds=30)
        player = make_player()
        player_id = str(player.id)
        roster = make_roster(manager_id="M1")

        with pytest.raises(PlayerAlreadyDraftedError) as exc_info:
            validate_pick(
                manager_id="M1",
                player_id=player_id,
                current_pick_number=1,
                draft_order=order,
                drafted_player_ids=frozenset([player_id]),  # already drafted
                player=player,
                roster=roster,
                competition_type=CompetitionType.INTERNATIONAL,
            )

        err = exc_info.value
        assert err.code == "PLAYER_ALREADY_DRAFTED"
        assert player_id in err.message

    def test_injured_player_raises(self) -> None:
        managers = ["M1", "M2"]
        order = generate_snake_order(managers, num_rounds=30)
        player = make_player(status=AvailabilityStatus.INJURED)
        roster = make_roster(manager_id="M1")

        with pytest.raises(PlayerUnavailableError) as exc_info:
            validate_pick(
                manager_id="M1",
                player_id=str(player.id),
                current_pick_number=1,
                draft_order=order,
                drafted_player_ids=frozenset(),
                player=player,
                roster=roster,
                competition_type=CompetitionType.INTERNATIONAL,
            )

        err = exc_info.value
        assert err.code == "PLAYER_UNAVAILABLE"
        assert "injured" in err.message

    def test_suspended_player_raises(self) -> None:
        managers = ["M1", "M2"]
        order = generate_snake_order(managers, num_rounds=30)
        player = make_player(status=AvailabilityStatus.SUSPENDED)
        roster = make_roster(manager_id="M1")

        with pytest.raises(PlayerUnavailableError) as exc_info:
            validate_pick(
                manager_id="M1",
                player_id=str(player.id),
                current_pick_number=1,
                draft_order=order,
                drafted_player_ids=frozenset(),
                player=player,
                roster=roster,
                competition_type=CompetitionType.INTERNATIONAL,
            )

        err = exc_info.value
        assert err.code == "PLAYER_UNAVAILABLE"
        assert "suspended" in err.message


# ---------------------------------------------------------------------------
# Layer 3: Roster constraints
# ---------------------------------------------------------------------------


class TestRosterConstraints:
    """Tests for RosterFullError, NationalityLimitError, ClubLimitError."""

    def test_full_roster_raises(self) -> None:
        """Cannot pick when roster already has ROSTER_SIZE players."""
        managers = ["M1", "M2"]
        order = generate_snake_order(managers, num_rounds=30)
        player = make_player()

        # Build a full roster (30 fake player IDs)
        full_ids = frozenset(str(uuid4()) for _ in range(ROSTER_SIZE))
        roster = make_roster(
            manager_id="M1",
            player_ids=list(full_ids),
            nationalities=["FRA"] * ROSTER_SIZE,
            clubs=["Club A"] * ROSTER_SIZE,
        )

        with pytest.raises(RosterFullError) as exc_info:
            validate_pick(
                manager_id="M1",
                player_id=str(player.id),
                current_pick_number=1,
                draft_order=order,
                drafted_player_ids=frozenset(),
                player=player,
                roster=roster,
                competition_type=CompetitionType.INTERNATIONAL,
            )

        err = exc_info.value
        assert err.code == "ROSTER_FULL"

    def test_nationality_limit_raises_at_max(self) -> None:
        """Cannot draft a 9th French player in an international competition."""
        managers = ["M1", "M2"]
        order = generate_snake_order(managers, num_rounds=30)
        player = make_player(nationality="FRA")

        roster = make_roster(
            manager_id="M1",
            player_ids=[str(uuid4()) for _ in range(MAX_PER_NATION)],
            nationalities=["FRA"] * MAX_PER_NATION,  # already at the limit
            clubs=["Club A"] * MAX_PER_NATION,
        )

        with pytest.raises(NationalityLimitError) as exc_info:
            validate_pick(
                manager_id="M1",
                player_id=str(player.id),
                current_pick_number=1,
                draft_order=order,
                drafted_player_ids=frozenset(),
                player=player,
                roster=roster,
                competition_type=CompetitionType.INTERNATIONAL,
            )

        err = exc_info.value
        assert err.code == "NATIONALITY_LIMIT_EXCEEDED"
        assert "FRA" in err.message

    def test_nationality_limit_not_raised_just_below_max(self) -> None:
        """7 French players in roster — 8th French player must be allowed."""
        managers = ["M1", "M2"]
        order = generate_snake_order(managers, num_rounds=30)
        player = make_player(nationality="FRA")

        roster = make_roster(
            manager_id="M1",
            player_ids=[str(uuid4()) for _ in range(MAX_PER_NATION - 1)],
            nationalities=["FRA"] * (MAX_PER_NATION - 1),
            clubs=["Club A"] * (MAX_PER_NATION - 1),
        )

        # Must not raise NationalityLimitError
        try:
            validate_pick(
                manager_id="M1",
                player_id=str(player.id),
                current_pick_number=1,
                draft_order=order,
                drafted_player_ids=frozenset(),
                player=player,
                roster=roster,
                competition_type=CompetitionType.INTERNATIONAL,
            )
        except NationalityLimitError:
            pytest.fail("NationalityLimitError raised too early (at max-1)")

    def test_club_limit_raises_at_max(self) -> None:
        """Cannot draft a 7th Toulouse player in a club competition."""
        managers = ["M1", "M2"]
        order = generate_snake_order(managers, num_rounds=30)
        player = make_player(club="Stade Toulousain")

        roster = make_roster(
            manager_id="M1",
            player_ids=[str(uuid4()) for _ in range(MAX_PER_CLUB)],
            nationalities=["FRA"] * MAX_PER_CLUB,
            clubs=["Stade Toulousain"] * MAX_PER_CLUB,  # already at the limit
        )

        with pytest.raises(ClubLimitError) as exc_info:
            validate_pick(
                manager_id="M1",
                player_id=str(player.id),
                current_pick_number=1,
                draft_order=order,
                drafted_player_ids=frozenset(),
                player=player,
                roster=roster,
                competition_type=CompetitionType.CLUB,
            )

        err = exc_info.value
        assert err.code == "CLUB_LIMIT_EXCEEDED"
        assert "Stade Toulousain" in err.message

    def test_club_limit_not_applied_in_international(self) -> None:
        """Club limit must NOT apply in international competitions."""
        managers = ["M1", "M2"]
        order = generate_snake_order(managers, num_rounds=30)
        player = make_player(nationality="NZL", club="Blues")

        # 6 Blues players already — fine for international
        roster = make_roster(
            manager_id="M1",
            player_ids=[str(uuid4()) for _ in range(MAX_PER_CLUB)],
            nationalities=["NZL"] * MAX_PER_CLUB,
            clubs=["Blues"] * MAX_PER_CLUB,
        )

        try:
            validate_pick(
                manager_id="M1",
                player_id=str(player.id),
                current_pick_number=1,
                draft_order=order,
                drafted_player_ids=frozenset(),
                player=player,
                roster=roster,
                competition_type=CompetitionType.INTERNATIONAL,
            )
        except ClubLimitError:
            pytest.fail("ClubLimitError must not apply in international competition")

    def test_nationality_limit_not_applied_in_club(self) -> None:
        """Nationality limit must NOT apply in club competitions."""
        managers = ["M1", "M2"]
        order = generate_snake_order(managers, num_rounds=30)
        player = make_player(nationality="FRA", club="Stade Toulousain")

        # 8 French players already — fine for club competition (no nationality limit)
        # But we keep club count below MAX_PER_CLUB to avoid ClubLimitError
        roster = make_roster(
            manager_id="M1",
            player_ids=[str(uuid4()) for _ in range(MAX_PER_NATION)],
            nationalities=["FRA"] * MAX_PER_NATION,
            clubs=["Stade Toulousain"] * (MAX_PER_CLUB - 1),  # 5 < 6 — under club limit
        )

        try:
            validate_pick(
                manager_id="M1",
                player_id=str(player.id),
                current_pick_number=1,
                draft_order=order,
                drafted_player_ids=frozenset(),
                player=player,
                roster=roster,
                competition_type=CompetitionType.CLUB,
            )
        except NationalityLimitError:
            pytest.fail("NationalityLimitError must not apply in club competition")


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


class TestErrorHierarchy:
    """All custom errors must inherit from PickValidationError."""

    def test_all_errors_are_pick_validation_errors(self) -> None:
        assert issubclass(NotYourTurnError, PickValidationError)
        assert issubclass(PlayerAlreadyDraftedError, PickValidationError)
        assert issubclass(PlayerUnavailableError, PickValidationError)
        assert issubclass(RosterFullError, PickValidationError)
        assert issubclass(NationalityLimitError, PickValidationError)
        assert issubclass(ClubLimitError, PickValidationError)

    def test_errors_have_code_attribute(self) -> None:
        """Each error must carry a machine-readable code."""
        errors = [
            NotYourTurnError("M1", "M2"),
            PlayerAlreadyDraftedError("player-123"),
            PlayerUnavailableError("player-123", AvailabilityStatus.INJURED),
            RosterFullError("M1"),
            NationalityLimitError("FRA", 8),
            ClubLimitError("Stade Toulousain", 6),
        ]
        for err in errors:
            assert hasattr(err, "code"), f"{type(err).__name__} missing .code"
            assert hasattr(err, "message"), f"{type(err).__name__} missing .message"
            assert err.code != "", f"{type(err).__name__} has empty .code"
