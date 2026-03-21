# backend/tests/draft/test_assisted.py
"""
Tests for the Assisted Draft mode (CDC v3.1, section 7.5).

Scenarios covered:
    1. Enable assisted mode — commissioner activates, timer cancelled.
    2. Enable assisted mode — non-commissioner is rejected (403).
    3. Enable assisted mode — idempotency: already active raises error.
    4. Enable assisted mode — completed draft raises error.
    5. Submit assisted pick — commissioner enters valid pick.
    6. Submit assisted pick — pick recorded with entered_by_commissioner=True.
    7. Submit assisted pick — audit log entry created correctly.
    8. Submit assisted pick — non-commissioner is rejected.
    9. Submit assisted pick — wrong manager_id (out of turn) is rejected.
    10. Submit assisted pick — assisted mode not active is rejected.
    11. Audit log — get_assisted_audit_log() returns entries in order.
    12. Audit log — empty when no assisted picks made.
    13. Broadcast — DraftAssistedModeEnabledEvent emitted on enable.
    14. Broadcast — DraftPickMadeEvent carries entered_by_commissioner=True.
    15. Full flow — all picks in a 2-manager draft via assisted mode.

These tests use DraftEngine directly — no HTTP layer needed.
HTTP error mapping is tested separately in test_draft_assisted_router.py (Phase 4).
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.models.league import CompetitionType
from app.models.player import AvailabilityStatus, PlayerSummary, PositionType
from draft.assisted import (
    AssistedModeAlreadyActiveError,
    AssistedModeNotActiveError,
    NotCommissionerError,
)
from draft.broadcaster import MockBroadcaster
from draft.engine import DraftEngine, DraftStatus, PickRecord
from draft.events import DraftAssistedModeEnabledEvent, DraftPickMadeEvent
from draft.validate_pick import NotYourTurnError


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COMMISSIONER = "commissioner-uuid"
MANAGER_1 = "manager-1-uuid"
MANAGER_2 = "manager-2-uuid"
ROGUE_USER = "rogue-user-uuid"

# Nationality pool — enough variety to never hit MAX_PER_NATION (8) in tests
_NATIONALITIES = [
    "FRA", "ENG", "IRL", "SCO", "WAL", "ITA", "NZL", "AUS", "RSA", "ARG"
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_player_pool(size: int = 120) -> list[PlayerSummary]:
    """Create a player pool with varied nationalities and clubs.

    Args:
        size: Number of players to generate. Default 120 (enough for 2×30 + margin).

    Returns:
        List of PlayerSummary with unique UUIDs.
    """
    return [
        PlayerSummary(
            id=uuid4(),
            first_name="Test",
            last_name=f"Player{i}",
            nationality=_NATIONALITIES[i % len(_NATIONALITIES)],
            club=f"Club_{i % 15}",  # 15 clubs — never hits MAX_PER_CLUB (6)
            positions=[PositionType.PROP],
            availability_status=AvailabilityStatus.AVAILABLE,
        )
        for i in range(size)
    ]


def make_engine(
    manager_ids: list[str] | None = None,
    commissioner_id: str = COMMISSIONER,
    pick_duration: float = 120.0,
    pool_size: int = 120,
) -> tuple[DraftEngine, MockBroadcaster]:
    """Create a DraftEngine with a MockBroadcaster and commissioner set.

    Args:
        manager_ids: List of manager IDs. Defaults to [MANAGER_1, MANAGER_2].
        commissioner_id: ID of the league commissioner.
        pick_duration: Seconds per pick. Use short values for timer tests.
        pool_size: Number of players in the pool.

    Returns:
        (engine, broadcaster) tuple.
    """
    broadcaster = MockBroadcaster()
    managers = manager_ids or [MANAGER_1, MANAGER_2]
    engine = DraftEngine(
        league_id="test-league-assisted",
        manager_ids=managers,
        available_players=make_player_pool(pool_size),
        competition_type=CompetitionType.INTERNATIONAL,
        commissioner_id=commissioner_id,
        pick_duration=pick_duration,
        broadcaster=broadcaster,
    )
    return engine, broadcaster


# ---------------------------------------------------------------------------
# Test class 1 — Enable assisted mode
# ---------------------------------------------------------------------------


class TestEnableAssistedMode:
    """Tests for DraftEngine.enable_assisted_mode()."""

    @pytest.mark.asyncio
    async def test_commissioner_can_enable_assisted_mode(self) -> None:
        """Commissioner enables assisted mode — state updated, timer cancelled."""
        engine, _ = make_engine(pick_duration=120.0)
        await engine.start_draft(connected_manager_ids={MANAGER_1, MANAGER_2})

        # Timer should be running (normal mode)
        assert engine._current_timer is not None

        await engine.enable_assisted_mode(commissioner_id=COMMISSIONER)

        snapshot = engine.get_state_snapshot()
        assert snapshot.assisted_mode is True
        # Timer must be cancelled in assisted mode
        assert engine._current_timer is None

        # Cleanup: no timer to cancel
        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_non_commissioner_cannot_enable_assisted_mode(self) -> None:
        """A non-commissioner user is rejected with NotCommissionerError."""
        engine, _ = make_engine()
        await engine.start_draft(connected_manager_ids={MANAGER_1, MANAGER_2})

        with pytest.raises(NotCommissionerError):
            await engine.enable_assisted_mode(commissioner_id=ROGUE_USER)

        # State must be unchanged
        assert engine._state.assisted_mode is False

        if engine._current_timer is not None:
            engine._current_timer.cancel()
        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_enable_assisted_mode_is_idempotency_guarded(self) -> None:
        """Calling enable_assisted_mode twice raises AssistedModeAlreadyActiveError."""
        engine, _ = make_engine()
        await engine.start_draft(connected_manager_ids={MANAGER_1, MANAGER_2})
        await engine.enable_assisted_mode(commissioner_id=COMMISSIONER)

        with pytest.raises(AssistedModeAlreadyActiveError):
            await engine.enable_assisted_mode(commissioner_id=COMMISSIONER)

        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_cannot_enable_assisted_mode_on_completed_draft(self) -> None:
        """Enabling assisted mode on a completed draft raises RuntimeError."""
        engine, _ = make_engine(pick_duration=0.001, pool_size=120)
        # No managers connected → full autodraft → completes quickly
        await engine.start_draft(connected_manager_ids=set())
        await asyncio.sleep(1.5)  # wait for all 60 picks

        snapshot = engine.get_state_snapshot()
        assert snapshot.status == DraftStatus.COMPLETED

        with pytest.raises(RuntimeError, match="completed"):
            await engine.enable_assisted_mode(commissioner_id=COMMISSIONER)

    @pytest.mark.asyncio
    async def test_enable_on_pending_draft_is_allowed(self) -> None:
        """Assisted mode can be enabled before the draft starts (PENDING status)."""
        engine, _ = make_engine()
        # Do NOT call start_draft — draft remains PENDING

        await engine.enable_assisted_mode(commissioner_id=COMMISSIONER)

        assert engine._state.assisted_mode is True


# ---------------------------------------------------------------------------
# Test class 2 — Submit assisted pick
# ---------------------------------------------------------------------------


class TestSubmitAssistedPick:
    """Tests for DraftEngine.submit_assisted_pick()."""

    async def _start_assisted(
        self,
        engine: DraftEngine,
    ) -> None:
        """Helper: start draft + enable assisted mode."""
        await engine.start_draft(connected_manager_ids={MANAGER_1, MANAGER_2})
        await engine.enable_assisted_mode(commissioner_id=COMMISSIONER)

    @pytest.mark.asyncio
    async def test_valid_assisted_pick_is_recorded(self) -> None:
        """Commissioner submits a valid pick — PickRecord returned."""
        engine, _ = make_engine()
        await self._start_assisted(engine)

        current_manager = engine.get_state_snapshot().current_manager_id
        assert current_manager is not None
        player = engine._available_players[0]

        record = await engine.submit_assisted_pick(
            commissioner_id=COMMISSIONER,
            manager_id=current_manager,
            player_id=str(player.id),
        )

        assert isinstance(record, PickRecord)
        assert record.pick_number == 1
        assert record.manager_id == current_manager
        assert record.player_id == str(player.id)
        assert record.autodrafted is False

        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_assisted_pick_sets_entered_by_commissioner_flag(self) -> None:
        """Pick recorded via assisted mode must have entered_by_commissioner=True."""
        engine, _ = make_engine()
        await self._start_assisted(engine)

        current_manager = engine.get_state_snapshot().current_manager_id
        player = engine._available_players[0]

        record = await engine.submit_assisted_pick(
            commissioner_id=COMMISSIONER,
            manager_id=current_manager,
            player_id=str(player.id),
        )

        # The flag on the returned record
        assert record.entered_by_commissioner is True

        # The flag in the state picks list
        snapshot = engine.get_state_snapshot()
        pick_in_state = next(p for p in snapshot.picks if p.pick_number == 1)
        assert pick_in_state.entered_by_commissioner is True

        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_assisted_pick_creates_audit_log_entry(self) -> None:
        """Each assisted pick must create one entry in the audit log."""
        engine, _ = make_engine()
        await self._start_assisted(engine)

        current_manager = engine.get_state_snapshot().current_manager_id
        player = engine._available_players[0]

        await engine.submit_assisted_pick(
            commissioner_id=COMMISSIONER,
            manager_id=current_manager,
            player_id=str(player.id),
        )

        audit_log = engine.get_assisted_audit_log()
        assert len(audit_log) == 1

        entry = audit_log[0]
        assert entry.pick_number == 1
        assert entry.manager_id == current_manager
        assert entry.player_id == str(player.id)
        assert entry.commissioner_id == COMMISSIONER
        assert entry.timestamp > 0.0

        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_non_commissioner_cannot_submit_assisted_pick(self) -> None:
        """A non-commissioner user cannot submit an assisted pick."""
        engine, _ = make_engine()
        await self._start_assisted(engine)

        current_manager = engine.get_state_snapshot().current_manager_id
        player = engine._available_players[0]

        with pytest.raises(NotCommissionerError):
            await engine.submit_assisted_pick(
                commissioner_id=ROGUE_USER,
                manager_id=current_manager,
                player_id=str(player.id),
            )

        # No pick recorded, no audit entry
        assert engine.get_assisted_audit_log() == []

        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_assisted_pick_wrong_manager_raises_not_your_turn(self) -> None:
        """Commissioner submitting for the wrong manager is rejected (turn order enforced)."""
        engine, _ = make_engine()
        await self._start_assisted(engine)

        current_manager = engine.get_state_snapshot().current_manager_id
        wrong_manager = (
            MANAGER_2 if current_manager == MANAGER_1 else MANAGER_1
        )
        player = engine._available_players[0]

        with pytest.raises(NotYourTurnError):
            await engine.submit_assisted_pick(
                commissioner_id=COMMISSIONER,
                manager_id=wrong_manager,
                player_id=str(player.id),
            )

        # State must be unchanged
        assert engine.get_state_snapshot().current_pick_number == 1

        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_assisted_pick_requires_assisted_mode_active(self) -> None:
        """submit_assisted_pick() without enabling assisted mode raises error."""
        engine, _ = make_engine()
        await engine.start_draft(connected_manager_ids={MANAGER_1, MANAGER_2})
        # NOT calling enable_assisted_mode

        current_manager = engine.get_state_snapshot().current_manager_id
        player = engine._available_players[0]

        with pytest.raises(AssistedModeNotActiveError):
            await engine.submit_assisted_pick(
                commissioner_id=COMMISSIONER,
                manager_id=current_manager,
                player_id=str(player.id),
            )

        if engine._current_timer is not None:
            engine._current_timer.cancel()
        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_assisted_pick_advances_pick_number(self) -> None:
        """Assisted pick increments current_pick_number exactly like a normal pick."""
        engine, _ = make_engine()
        await self._start_assisted(engine)

        current_manager = engine.get_state_snapshot().current_manager_id
        player = engine._available_players[0]

        await engine.submit_assisted_pick(
            commissioner_id=COMMISSIONER,
            manager_id=current_manager,
            player_id=str(player.id),
        )

        assert engine.get_state_snapshot().current_pick_number == 2

        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_assisted_pick_removes_player_from_pool(self) -> None:
        """Drafted player must be removed from the available pool."""
        engine, _ = make_engine()
        await self._start_assisted(engine)

        current_manager = engine.get_state_snapshot().current_manager_id
        player = engine._available_players[0]
        player_id = str(player.id)

        await engine.submit_assisted_pick(
            commissioner_id=COMMISSIONER,
            manager_id=current_manager,
            player_id=player_id,
        )

        remaining_ids = {str(p.id) for p in engine._available_players}
        assert player_id not in remaining_ids

        await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# Test class 3 — Audit log
# ---------------------------------------------------------------------------


class TestAuditLog:
    """Tests for DraftEngine.get_assisted_audit_log()."""

    @pytest.mark.asyncio
    async def test_audit_log_empty_when_no_assisted_picks(self) -> None:
        """Audit log is empty when assisted mode was never activated."""
        engine, _ = make_engine()
        await engine.start_draft(connected_manager_ids={MANAGER_1, MANAGER_2})

        assert engine.get_assisted_audit_log() == []

        if engine._current_timer is not None:
            engine._current_timer.cancel()
        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_audit_log_entries_are_in_pick_order(self) -> None:
        """Multiple assisted picks must appear in the log in pick order."""
        engine, _ = make_engine()
        await engine.start_draft(connected_manager_ids={MANAGER_1, MANAGER_2})
        await engine.enable_assisted_mode(commissioner_id=COMMISSIONER)

        # Submit 3 picks in order
        for _ in range(3):
            current_manager = engine.get_state_snapshot().current_manager_id
            assert current_manager is not None
            player = engine._available_players[0]
            await engine.submit_assisted_pick(
                commissioner_id=COMMISSIONER,
                manager_id=current_manager,
                player_id=str(player.id),
            )

        audit_log = engine.get_assisted_audit_log()
        assert len(audit_log) == 3

        # Entries must be ordered by pick_number
        pick_numbers = [entry.pick_number for entry in audit_log]
        assert pick_numbers == sorted(pick_numbers)
        assert pick_numbers == [1, 2, 3]

        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_audit_log_returns_copy(self) -> None:
        """get_assisted_audit_log() returns a copy — mutations don't affect state."""
        engine, _ = make_engine()
        await engine.start_draft(connected_manager_ids={MANAGER_1, MANAGER_2})
        await engine.enable_assisted_mode(commissioner_id=COMMISSIONER)

        current_manager = engine.get_state_snapshot().current_manager_id
        player = engine._available_players[0]
        await engine.submit_assisted_pick(
            commissioner_id=COMMISSIONER,
            manager_id=current_manager,
            player_id=str(player.id),
        )

        log_copy = engine.get_assisted_audit_log()
        log_copy.clear()  # mutate the copy

        # Internal state must be unaffected
        assert len(engine._state.assisted_audit_log) == 1

        await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# Test class 4 — Broadcast events
# ---------------------------------------------------------------------------


class TestAssistedBroadcastEvents:
    """Tests that assisted mode emits the correct typed events."""

    @pytest.mark.asyncio
    async def test_enable_assisted_mode_emits_event(self) -> None:
        """enable_assisted_mode() must broadcast DraftAssistedModeEnabledEvent."""
        engine, broadcaster = make_engine()
        await engine.start_draft(connected_manager_ids={MANAGER_1, MANAGER_2})
        broadcaster.reset()  # ignore start events

        await engine.enable_assisted_mode(commissioner_id=COMMISSIONER)

        events = broadcaster.events_of_type("draft.assisted_mode_enabled")
        assert len(events) == 1

        event = events[0]
        assert isinstance(event, DraftAssistedModeEnabledEvent)
        assert event.league_id == "test-league-assisted"
        assert event.commissioner_id == COMMISSIONER
        assert event.current_pick_number == 1

        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_assisted_pick_emits_pick_made_with_commissioner_flag(self) -> None:
        """Assisted pick must broadcast DraftPickMadeEvent with entered_by_commissioner=True."""
        engine, broadcaster = make_engine()
        await engine.start_draft(connected_manager_ids={MANAGER_1, MANAGER_2})
        await engine.enable_assisted_mode(commissioner_id=COMMISSIONER)
        broadcaster.reset()  # focus on the pick event only

        current_manager = engine.get_state_snapshot().current_manager_id
        player = engine._available_players[0]

        await engine.submit_assisted_pick(
            commissioner_id=COMMISSIONER,
            manager_id=current_manager,
            player_id=str(player.id),
        )

        pick_events = broadcaster.events_of_type("draft.pick_made")
        assert len(pick_events) == 1

        event = pick_events[0]
        assert isinstance(event, DraftPickMadeEvent)
        assert event.entered_by_commissioner is True
        assert event.autodrafted is False
        assert event.manager_id == current_manager

        await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# Test class 5 — Full flow
# ---------------------------------------------------------------------------


class TestFullAssistedDraftFlow:
    """End-to-end test: complete a draft entirely via assisted mode."""

    @pytest.mark.asyncio
    async def test_full_draft_via_assisted_mode_completes(self) -> None:
        """Commissioner enters all 60 picks for a 2-manager draft.

        Verifies:
            - Draft reaches COMPLETED status.
            - All 60 picks have entered_by_commissioner=True.
            - Audit log has exactly 60 entries.
            - No picks are autodrafted.
        """
        engine, _ = make_engine(pool_size=120)
        await engine.start_draft(connected_manager_ids={MANAGER_1, MANAGER_2})
        await engine.enable_assisted_mode(commissioner_id=COMMISSIONER)

        total_picks = engine.get_state_snapshot().total_picks  # 60

        for _ in range(total_picks):
            snapshot = engine.get_state_snapshot()
            if snapshot.status == DraftStatus.COMPLETED:
                break

            current_manager = snapshot.current_manager_id
            assert current_manager is not None, "current_manager_id should not be None mid-draft"

            player = engine._available_players[0]
            await engine.submit_assisted_pick(
                commissioner_id=COMMISSIONER,
                manager_id=current_manager,
                player_id=str(player.id),
            )

        final_snapshot = engine.get_state_snapshot()
        assert final_snapshot.status == DraftStatus.COMPLETED
        assert len(final_snapshot.picks) == total_picks

        # Every pick must be commissioner-entered
        assert all(p.entered_by_commissioner for p in final_snapshot.picks)

        # No pick should be autodrafted
        assert all(not p.autodrafted for p in final_snapshot.picks)

        # Audit log must match exactly
        audit_log = engine.get_assisted_audit_log()
        assert len(audit_log) == total_picks

        # Audit log pick numbers must match snapshot pick numbers
        audit_pick_numbers = {entry.pick_number for entry in audit_log}
        snapshot_pick_numbers = {p.pick_number for p in final_snapshot.picks}
        assert audit_pick_numbers == snapshot_pick_numbers