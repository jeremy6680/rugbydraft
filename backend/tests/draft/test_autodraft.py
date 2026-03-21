# tests/draft/test_autodraft.py
"""
Unit tests for the autodraft pick selection algorithm.

All tests are synchronous — select_autodraft_pick() is a pure function.

Coverage:
    - Preference list: first valid player selected
    - Preference list: skips already-drafted or unavailable players
    - Preference list: skips players violating roster constraints
    - Default value: selects highest-value player when preference list empty
    - Default value: skips players violating roster constraints
    - Priority: preference list always wins over default value
    - Empty pool: AutodraftError raised
    - AutodraftResult: correct source field in each case
"""

from uuid import uuid4

import pytest

from app.models.league import CompetitionType
from app.models.player import AvailabilityStatus, PlayerSummary, PositionType
from draft.autodraft import AutodraftError, AutodraftResult, select_autodraft_pick
from draft.validate_pick import MAX_PER_CLUB, MAX_PER_NATION, RosterSnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_player(
    player_id: str | None = None,
    nationality: str = "FRA",
    club: str = "Stade Toulousain",
    status: AvailabilityStatus = AvailabilityStatus.AVAILABLE,
) -> PlayerSummary:
    """Create a PlayerSummary for testing."""
    from uuid import UUID

    uid = UUID(player_id) if player_id else uuid4()
    return PlayerSummary(
        id=uid,
        first_name="Test",
        last_name="Player",
        nationality=nationality,
        club=club,
        positions=[PositionType.PROP],
        availability_status=status,
    )


def make_roster(
    manager_id: str = "M1",
    size: int = 0,
    nationalities: list[str] | None = None,
    clubs: list[str] | None = None,
) -> RosterSnapshot:
    """Create a RosterSnapshot with a given number of players."""
    player_ids = frozenset(str(uuid4()) for _ in range(size))
    return RosterSnapshot(
        manager_id=manager_id,
        player_ids=player_ids,
        nationalities=nationalities or [],
        clubs=clubs or [],
    )


# ---------------------------------------------------------------------------
# Preference list selection
# ---------------------------------------------------------------------------


class TestPreferenceListSelection:
    """Autodraft selects from preference list when possible."""

    def test_selects_first_preferred_available_player(self) -> None:
        """First player in preference list that is available must be selected."""
        p1 = make_player()
        p2 = make_player()
        preference_list = [str(p1.id), str(p2.id)]
        available = [p1, p2]
        roster = make_roster()

        result = select_autodraft_pick(
            manager_id="M1",
            preference_list=preference_list,
            available_players=available,
            roster=roster,
            competition_type=CompetitionType.INTERNATIONAL,
        )

        assert result.player_id == str(p1.id)
        assert result.source == "preference_list"

    def test_skips_drafted_player_in_preference_list(self) -> None:
        """If first preferred player is already drafted, skip to next."""
        p1 = make_player()
        p2 = make_player()
        preference_list = [str(p1.id), str(p2.id)]
        # p1 is NOT in available_players (already drafted)
        available = [p2]
        roster = make_roster()

        result = select_autodraft_pick(
            manager_id="M1",
            preference_list=preference_list,
            available_players=available,
            roster=roster,
            competition_type=CompetitionType.INTERNATIONAL,
        )

        assert result.player_id == str(p2.id)
        assert result.source == "preference_list"

    def test_skips_preference_player_violating_nationality_limit(self) -> None:
        """If preferred player would exceed nationality limit, skip to next."""
        # p1 is French but roster already has MAX_PER_NATION French players
        p1 = make_player(nationality="FRA")
        p2 = make_player(nationality="ENG")
        preference_list = [str(p1.id), str(p2.id)]
        available = [p1, p2]

        roster = make_roster(
            size=MAX_PER_NATION,
            nationalities=["FRA"] * MAX_PER_NATION,
            clubs=["Club A"] * MAX_PER_NATION,
        )

        result = select_autodraft_pick(
            manager_id="M1",
            preference_list=preference_list,
            available_players=available,
            roster=roster,
            competition_type=CompetitionType.INTERNATIONAL,
        )

        # p1 (FRA) skipped — p2 (ENG) selected
        assert result.player_id == str(p2.id)
        assert result.source == "preference_list"

    def test_skips_preference_player_violating_club_limit(self) -> None:
        """If preferred player would exceed club limit, skip to next."""
        p1 = make_player(club="Stade Toulousain")
        p2 = make_player(club="Racing 92")
        preference_list = [str(p1.id), str(p2.id)]
        available = [p1, p2]

        roster = make_roster(
            size=MAX_PER_CLUB,
            nationalities=["FRA"] * MAX_PER_CLUB,
            clubs=["Stade Toulousain"] * MAX_PER_CLUB,
        )

        result = select_autodraft_pick(
            manager_id="M1",
            preference_list=preference_list,
            available_players=available,
            roster=roster,
            competition_type=CompetitionType.CLUB,
        )

        assert result.player_id == str(p2.id)
        assert result.source == "preference_list"

    def test_empty_preference_list_falls_back_to_default(self) -> None:
        """Empty preference list must fall through to default value algorithm."""
        p1 = make_player()
        available = [p1]
        roster = make_roster()

        result = select_autodraft_pick(
            manager_id="M1",
            preference_list=[],  # empty
            available_players=available,
            roster=roster,
            competition_type=CompetitionType.INTERNATIONAL,
        )

        assert result.player_id == str(p1.id)
        assert result.source == "default_value"

    def test_exhausted_preference_list_falls_back_to_default(self) -> None:
        """All preferred players drafted — must fall back to default value."""
        p1 = make_player()
        p2 = make_player()
        preference_list = [str(p1.id)]  # only p1 preferred
        # p1 is NOT available (drafted) — p2 is available
        available = [p2]
        roster = make_roster()

        result = select_autodraft_pick(
            manager_id="M1",
            preference_list=preference_list,
            available_players=available,
            roster=roster,
            competition_type=CompetitionType.INTERNATIONAL,
        )

        assert result.player_id == str(p2.id)
        assert result.source == "default_value"


# ---------------------------------------------------------------------------
# Default value selection
# ---------------------------------------------------------------------------


class TestDefaultValueSelection:
    """Autodraft selects by value when preference list is empty/exhausted."""

    def test_selects_first_in_sorted_list(self) -> None:
        """First player in available_players (highest value) must be selected."""
        p1 = make_player()  # highest value — first in list
        p2 = make_player()
        p3 = make_player()
        available = [p1, p2, p3]  # pre-sorted by caller
        roster = make_roster()

        result = select_autodraft_pick(
            manager_id="M1",
            preference_list=[],
            available_players=available,
            roster=roster,
            competition_type=CompetitionType.INTERNATIONAL,
        )

        assert result.player_id == str(p1.id)
        assert result.source == "default_value"

    def test_skips_player_violating_nationality_limit(self) -> None:
        """Default value must skip players violating nationality constraints."""
        p1 = make_player(nationality="FRA")  # would violate limit
        p2 = make_player(nationality="ENG")  # valid
        available = [p1, p2]

        roster = make_roster(
            size=MAX_PER_NATION,
            nationalities=["FRA"] * MAX_PER_NATION,
            clubs=["Club A"] * MAX_PER_NATION,
        )

        result = select_autodraft_pick(
            manager_id="M1",
            preference_list=[],
            available_players=available,
            roster=roster,
            competition_type=CompetitionType.INTERNATIONAL,
        )

        assert result.player_id == str(p2.id)
        assert result.source == "default_value"

    def test_skips_player_violating_club_limit(self) -> None:
        """Default value must skip players violating club constraints."""
        p1 = make_player(club="Stade Toulousain")  # would violate limit
        p2 = make_player(club="Racing 92")  # valid
        available = [p1, p2]

        roster = make_roster(
            size=MAX_PER_CLUB,
            nationalities=["FRA"] * MAX_PER_CLUB,
            clubs=["Stade Toulousain"] * MAX_PER_CLUB,
        )

        result = select_autodraft_pick(
            manager_id="M1",
            preference_list=[],
            available_players=available,
            roster=roster,
            competition_type=CompetitionType.CLUB,
        )

        assert result.player_id == str(p2.id)
        assert result.source == "default_value"


# ---------------------------------------------------------------------------
# Priority: preference list wins over default value
# ---------------------------------------------------------------------------


class TestPreferencePriority:
    """Preference list must always take priority over default value."""

    def test_preferred_player_wins_over_first_in_pool(self) -> None:
        """Even if p2 is first in pool (highest value), p1 wins if preferred."""
        p1 = make_player()  # preferred, lower value — second in pool
        p2 = make_player()  # not preferred, higher value — first in pool
        preference_list = [str(p1.id)]
        available = [p2, p1]  # p2 is "higher value" (first in sorted list)
        roster = make_roster()

        result = select_autodraft_pick(
            manager_id="M1",
            preference_list=preference_list,
            available_players=available,
            roster=roster,
            competition_type=CompetitionType.INTERNATIONAL,
        )

        assert result.player_id == str(p1.id)
        assert result.source == "preference_list"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestAutodraftErrors:
    """AutodraftError raised when no valid player can be found."""

    def test_empty_pool_raises_autodraft_error(self) -> None:
        """Empty available_players must raise AutodraftError."""
        with pytest.raises(AutodraftError) as exc_info:
            select_autodraft_pick(
                manager_id="M1",
                preference_list=[],
                available_players=[],
                roster=make_roster(),
                competition_type=CompetitionType.INTERNATIONAL,
            )

        err = exc_info.value
        assert err.manager_id == "M1"
        assert "M1" in str(err)

    def test_all_players_violate_constraints_raises(self) -> None:
        """If all available players violate constraints, raise AutodraftError."""
        # All players are French — roster already at nation limit
        players = [make_player(nationality="FRA") for _ in range(5)]
        roster = make_roster(
            size=MAX_PER_NATION,
            nationalities=["FRA"] * MAX_PER_NATION,
            clubs=["Club A"] * MAX_PER_NATION,
        )

        with pytest.raises(AutodraftError):
            select_autodraft_pick(
                manager_id="M1",
                preference_list=[],
                available_players=players,
                roster=roster,
                competition_type=CompetitionType.INTERNATIONAL,
            )


# ---------------------------------------------------------------------------
# AutodraftResult structure
# ---------------------------------------------------------------------------


class TestAutodraftResult:
    """AutodraftResult must always contain valid, consistent data."""

    def test_result_is_autodraft_result_instance(self) -> None:
        p1 = make_player()
        result = select_autodraft_pick(
            manager_id="M1",
            preference_list=[],
            available_players=[p1],
            roster=make_roster(),
            competition_type=CompetitionType.INTERNATIONAL,
        )
        assert isinstance(result, AutodraftResult)

    def test_result_player_matches_player_id(self) -> None:
        """result.player.id must match result.player_id."""
        p1 = make_player()
        result = select_autodraft_pick(
            manager_id="M1",
            preference_list=[],
            available_players=[p1],
            roster=make_roster(),
            competition_type=CompetitionType.INTERNATIONAL,
        )
        assert result.player_id == str(result.player.id)

    def test_source_is_preference_list(self) -> None:
        p1 = make_player()
        result = select_autodraft_pick(
            manager_id="M1",
            preference_list=[str(p1.id)],
            available_players=[p1],
            roster=make_roster(),
            competition_type=CompetitionType.INTERNATIONAL,
        )
        assert result.source == "preference_list"

    def test_source_is_default_value(self) -> None:
        p1 = make_player()
        result = select_autodraft_pick(
            manager_id="M1",
            preference_list=[],
            available_players=[p1],
            roster=make_roster(),
            competition_type=CompetitionType.INTERNATIONAL,
        )
        assert result.source == "default_value"
