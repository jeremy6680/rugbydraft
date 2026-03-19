# tests/draft/test_engine.py
"""
Unit tests for the DraftEngine.

These tests cover the full orchestration layer:
    - Draft start: random draw, autodraft for absent managers
    - Manual pick: validation, state update, timer cancel
    - Timeout: autodraft triggered, manager stays in autodraft
    - "Manager never connected": full autodraft from pick 1
    - Reconnection: state snapshot, autodraft deactivated on reconnect
    - Draft completion: status set to COMPLETED

All tests use short pick_duration (0.05s) to avoid slow CI runs.
Players are created with unique IDs to simulate a real player pool.
"""

import asyncio
from uuid import uuid4

import pytest

from app.models.league import CompetitionType
from app.models.player import AvailabilityStatus, PlayerSummary, PositionType
from draft.engine import (
    DRAFT_NUM_ROUNDS,
    DraftEngine,
    DraftStatus,
    PickRecord,
)
from draft.validate_pick import NotYourTurnError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SHORT_DURATION = 0.05  # seconds — fast enough for CI


def make_player(
    nationality: str = "FRA",
    club: str = "Club A",
) -> PlayerSummary:
    """Create a unique PlayerSummary for testing."""
    return PlayerSummary(
        id=uuid4(),
        first_name="Test",
        last_name="Player",
        nationality=nationality,
        club=club,
        positions=[PositionType.PROP],
        availability_status=AvailabilityStatus.AVAILABLE,
    )


# Nationality pool — enough variety to never hit MAX_PER_NATION (8) in tests
_NATIONALITIES = ["FRA", "ENG", "IRE", "SCO", "WAL", "ITA", "NZL", "AUS", "RSA", "ARG"]

def make_player_pool(
    size: int,
    nationalities: list[str] | None = None,
) -> list[PlayerSummary]:
    """Create a pool of unique players with varied nationalities."""
    players = []
    nat_pool = nationalities or _NATIONALITIES
    for i in range(size):
        # Rotate through nationalities to avoid hitting MAX_PER_NATION
        nat = nat_pool[i % len(nat_pool)]
        players.append(make_player(nationality=nat, club=f"Club {i}"))
    return players


def make_engine(
    manager_ids: list[str] | None = None,
    pool_size: int = 200,
    pick_duration: float = SHORT_DURATION,
    nationalities: list[str] | None = None,
) -> DraftEngine:
    """Create a DraftEngine with a large enough player pool."""
    managers = manager_ids or ["M1", "M2", "M3"]
    players = make_player_pool(pool_size, nationalities=nationalities)
    return DraftEngine(
        league_id="league-test",
        manager_ids=managers,
        available_players=players,
        competition_type=CompetitionType.INTERNATIONAL,
        pick_duration=pick_duration,
    )


# ---------------------------------------------------------------------------
# Draft start
# ---------------------------------------------------------------------------


class TestDraftStart:
    """Tests for DraftEngine.start_draft()."""

    @pytest.mark.asyncio
    async def test_status_is_in_progress_after_start(self) -> None:
        engine = make_engine()
        await engine.start_draft(connected_manager_ids={"M1", "M2", "M3"})
        snapshot = engine.get_state_snapshot()
        assert snapshot.status == DraftStatus.IN_PROGRESS
        # Cleanup: wait for timer to avoid dangling tasks
        await asyncio.sleep(SHORT_DURATION * 3)

    @pytest.mark.asyncio
    async def test_cannot_start_twice(self) -> None:
        engine = make_engine()
        await engine.start_draft(connected_manager_ids={"M1", "M2", "M3"})
        with pytest.raises(RuntimeError, match="Cannot start draft"):
            await engine.start_draft(connected_manager_ids={"M1"})
        await asyncio.sleep(SHORT_DURATION * 3)

    @pytest.mark.asyncio
    async def test_disconnected_managers_get_autodraft(self) -> None:
        """Managers not connected at draft start are immediately autodrafted."""
        engine = make_engine(manager_ids=["M1", "M2", "M3"])
        # Only M1 is connected — M2 and M3 get autodraft
        await engine.start_draft(connected_manager_ids={"M1"})
        snapshot = engine.get_state_snapshot()
        assert "M2" in snapshot.autodraft_managers
        assert "M3" in snapshot.autodraft_managers
        assert "M1" not in snapshot.autodraft_managers
        await asyncio.sleep(SHORT_DURATION * 3)

    @pytest.mark.asyncio
    async def test_all_managers_connected_no_autodraft(self) -> None:
        """If all managers are connected, none start in autodraft."""
        engine = make_engine(manager_ids=["M1", "M2"])
        await engine.start_draft(connected_manager_ids={"M1", "M2"})
        snapshot = engine.get_state_snapshot()
        assert snapshot.autodraft_managers == []
        await asyncio.sleep(SHORT_DURATION * 3)


# ---------------------------------------------------------------------------
# Manual pick
# ---------------------------------------------------------------------------


class TestManualPick:
    """Tests for DraftEngine.submit_pick()."""

    @pytest.mark.asyncio
    async def test_valid_pick_advances_pick_number(self) -> None:
        engine = make_engine(manager_ids=["M1", "M2"])
        await engine.start_draft(connected_manager_ids={"M1", "M2"})

        # Find who picks first
        snapshot = engine.get_state_snapshot()
        first_manager = snapshot.current_manager_id
        assert first_manager is not None

        # Grab any available player
        player = engine._available_players[0]
        await engine.submit_pick(
            manager_id=first_manager,
            player_id=str(player.id),
        )

        snapshot = engine.get_state_snapshot()
        assert snapshot.current_pick_number == 2
        await asyncio.sleep(SHORT_DURATION * 3)

    @pytest.mark.asyncio
    async def test_pick_recorded_in_history(self) -> None:
        engine = make_engine(manager_ids=["M1", "M2"])
        await engine.start_draft(connected_manager_ids={"M1", "M2"})

        first_manager = engine.get_state_snapshot().current_manager_id
        player = engine._available_players[0]
        record = await engine.submit_pick(
            manager_id=first_manager,
            player_id=str(player.id),
        )

        assert isinstance(record, PickRecord)
        assert record.pick_number == 1
        assert record.manager_id == first_manager
        assert record.player_id == str(player.id)
        assert record.autodrafted is False
        await asyncio.sleep(SHORT_DURATION * 3)

    @pytest.mark.asyncio
    async def test_wrong_manager_raises_not_your_turn(self) -> None:
        engine = make_engine(manager_ids=["M1", "M2"])
        await engine.start_draft(connected_manager_ids={"M1", "M2"})

        snapshot = engine.get_state_snapshot()
        first_manager = snapshot.current_manager_id
        # Pick the OTHER manager
        wrong_manager = "M2" if first_manager == "M1" else "M1"
        player = engine._available_players[0]

        with pytest.raises(NotYourTurnError):
            await engine.submit_pick(
                manager_id=wrong_manager,
                player_id=str(player.id),
            )
        await asyncio.sleep(SHORT_DURATION * 3)

    @pytest.mark.asyncio
    async def test_player_removed_from_pool_after_pick(self) -> None:
        engine = make_engine(manager_ids=["M1", "M2"])
        await engine.start_draft(connected_manager_ids={"M1", "M2"})

        first_manager = engine.get_state_snapshot().current_manager_id
        player = engine._available_players[0]
        player_id = str(player.id)

        await engine.submit_pick(manager_id=first_manager, player_id=player_id)

        remaining_ids = {str(p.id) for p in engine._available_players}
        assert player_id not in remaining_ids
        await asyncio.sleep(SHORT_DURATION * 3)


# ---------------------------------------------------------------------------
# Timeout → autodraft
# ---------------------------------------------------------------------------


class TestTimeoutAutodraft:
    """Tests for timer expiration triggering autodraft."""

    @pytest.mark.asyncio
    async def test_timeout_triggers_autodraft_pick(self) -> None:
        """When the timer expires, a pick must be recorded automatically."""
        engine = make_engine(manager_ids=["M1", "M2"], pick_duration=SHORT_DURATION)
        await engine.start_draft(connected_manager_ids={"M1", "M2"})

        # Wait for timer to expire + autodraft to complete
        await asyncio.sleep(SHORT_DURATION * 4)

        snapshot = engine.get_state_snapshot()
        assert snapshot.current_pick_number > 1
        assert len(snapshot.picks) >= 1
        assert snapshot.picks[0].autodrafted is True

    @pytest.mark.asyncio
    async def test_timeout_marks_manager_as_autodraft(self) -> None:
        """After a timeout, the manager must be in autodraft for remaining picks."""
        engine = make_engine(manager_ids=["M1", "M2"], pick_duration=SHORT_DURATION)
        await engine.start_draft(connected_manager_ids={"M1", "M2"})

        # Wait for first timer to expire
        await asyncio.sleep(SHORT_DURATION * 4)

        snapshot = engine.get_state_snapshot()
        first_manager = snapshot.picks[0].manager_id
        assert first_manager in snapshot.autodraft_managers

    @pytest.mark.asyncio
    async def test_full_autodraft_completes_draft(self) -> None:
        """With 2 managers, all autodrafted, draft must complete."""
        # 2 managers × 30 rounds = 60 picks
        # With very short duration this completes in well under 1 second
        engine = make_engine(
            manager_ids=["M1", "M2"],
            pool_size=200,
            pick_duration=0.001,  # 1ms per pick
        )
        # No managers connected → full autodraft
        await engine.start_draft(connected_manager_ids=set())

        # Wait for all 60 autodraft picks to complete
        await asyncio.sleep(1.0)

        snapshot = engine.get_state_snapshot()
        assert snapshot.status == DraftStatus.COMPLETED
        assert len(snapshot.picks) == 60  # 2 managers × 30 rounds


# ---------------------------------------------------------------------------
# "Manager never connected" → full autodraft
# ---------------------------------------------------------------------------


class TestManagerNeverConnected:
    """Tests for the "never connected" autodraft scenario (CDC 7.3)."""

    @pytest.mark.asyncio
    async def test_never_connected_manager_gets_autodrafted(self) -> None:
        """A manager who never connects must have all picks autodrafted."""
        engine = make_engine(
            manager_ids=["M1", "M2"],
            pool_size=200,
            pick_duration=0.001,
        )
        # Only M1 connected — M2 never connects
        await engine.start_draft(connected_manager_ids={"M1"})
        await asyncio.sleep(1.0)

        snapshot = engine.get_state_snapshot()
        assert snapshot.status == DraftStatus.COMPLETED

        # All M2 picks must be autodrafted
        m2_picks = [p for p in snapshot.picks if p.manager_id == "M2"]
        assert len(m2_picks) == 30  # 30 rounds
        assert all(p.autodrafted for p in m2_picks)

    @pytest.mark.asyncio
    async def test_never_connected_manager_in_autodraft_from_start(self) -> None:
        """Manager not connected at start must be in autodraft_managers immediately."""
        engine = make_engine(manager_ids=["M1", "M2"])
        await engine.start_draft(connected_manager_ids={"M1"})  # M2 absent

        snapshot = engine.get_state_snapshot()
        assert "M2" in snapshot.autodraft_managers
        await asyncio.sleep(SHORT_DURATION * 3)


# ---------------------------------------------------------------------------
# Reconnection protocol (CDC 7.4)
# ---------------------------------------------------------------------------


class TestReconnectionProtocol:
    """Tests for the reconnection state snapshot and autodraft deactivation."""

    @pytest.mark.asyncio
    async def test_reconnect_returns_full_snapshot(self) -> None:
        """connect_manager() must return a complete DraftStateSnapshot."""
        engine = make_engine(manager_ids=["M1", "M2"])
        await engine.start_draft(connected_manager_ids={"M1", "M2"})

        snapshot = await engine.connect_manager("M1")
        assert snapshot.league_id == "league-test"
        assert snapshot.status == DraftStatus.IN_PROGRESS
        assert snapshot.current_pick_number == 1
        assert snapshot.total_picks == 60  # 2 × 30
        await asyncio.sleep(SHORT_DURATION * 3)

    @pytest.mark.asyncio
    async def test_reconnect_during_own_turn_deactivates_autodraft(self) -> None:
        """Reconnecting during own turn must deactivate autodraft."""
        # M1 connected, M2 absent → M2 gets autodraft
        # Timer is long enough (1s) that M2's turn hasn't expired yet
        engine = make_engine(manager_ids=["M1", "M2"], pick_duration=1.0)
        await engine.start_draft(connected_manager_ids={"M1"})

        # M2 is in autodraft — find if it's M2's turn yet or wait for it
        # Pick 1 belongs to whoever was drawn first — could be M1 or M2
        # We need M2's first turn: either pick 1 or pick 2
        snapshot = engine.get_state_snapshot()

        # Submit M1's pick manually if M1 goes first, to get to M2's turn
        first_manager = snapshot.current_manager_id
        assert first_manager is not None

        if first_manager != "M2":
            # M1 goes first — pick manually, then M2's turn starts
            player = engine._available_players[0]
            await engine.submit_pick(
                manager_id=first_manager,
                player_id=str(player.id),
            )

        # Now it should be M2's turn — M2 reconnects
        snapshot = engine.get_state_snapshot()
        assert snapshot.current_manager_id == "M2"
        assert "M2" in snapshot.autodraft_managers

        await engine.connect_manager("M2")

        snapshot = engine.get_state_snapshot()
        assert "M2" not in snapshot.autodraft_managers

        # Cleanup
        if engine._current_timer:
            engine._current_timer.cancel()
        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_snapshot_time_remaining_is_positive(self) -> None:
        """time_remaining must be > 0 shortly after a turn starts."""
        engine = make_engine(manager_ids=["M1", "M2"], pick_duration=1.0)
        await engine.start_draft(connected_manager_ids={"M1", "M2"})

        snapshot = engine.get_state_snapshot()
        assert snapshot.time_remaining > 0.0

        engine._current_timer.cancel() if engine._current_timer else None
        await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# Draft completion
# ---------------------------------------------------------------------------


class TestDraftCompletion:
    """Tests for draft completion state."""

    @pytest.mark.asyncio
    async def test_completed_draft_has_correct_pick_count(self) -> None:
        """Completed draft must have exactly N_managers × 30 picks."""
        engine = make_engine(
            manager_ids=["M1", "M2", "M3"],
            pool_size=200,
            pick_duration=0.001,
        )
        await engine.start_draft(connected_manager_ids=set())
        await asyncio.sleep(2.0)

        snapshot = engine.get_state_snapshot()
        assert snapshot.status == DraftStatus.COMPLETED
        assert len(snapshot.picks) == 90  # 3 × 30

    @pytest.mark.asyncio
    async def test_completed_draft_current_manager_is_none(self) -> None:
        """After completion, current_manager_id must be None."""
        engine = make_engine(
            manager_ids=["M1", "M2"],
            pool_size=200,
            pick_duration=0.001,
        )
        await engine.start_draft(connected_manager_ids=set())
        await asyncio.sleep(1.0)

        snapshot = engine.get_state_snapshot()
        assert snapshot.status == DraftStatus.COMPLETED
        assert snapshot.current_manager_id is None