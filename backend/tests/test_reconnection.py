# backend/tests/test_reconnection.py
"""
Tests for the reconnection protocol (CDC v3.1, section 7.4, D-001).

Scenarios covered:
    1. Manager reconnects during their turn with time remaining
       → autodraft deactivated, timer started, they can pick manually.
    2. Manager reconnects after their timer expired
       → autodraft pick is final, snapshot reflects it.
    3. Manager reconnects while another manager is picking
       → snapshot returned, no side effects on autodraft state.
    4. GET /state returns correct snapshot without side effects
       → connected_managers unchanged after a state poll.

These tests use the DraftEngine directly — no HTTP layer needed.
The reconnection logic lives in connect_manager(), not in the router.
The router tests (HTTPException paths, auth) are in test_draft_router.py.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.models.league import CompetitionType
from app.models.player import AvailabilityStatus, PlayerSummary, PositionType
from draft.broadcaster import MockBroadcaster
from draft.engine import DraftEngine, DraftStatus
from draft.events import DraftManagerConnectedEvent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_NATIONALITIES = ["FRA", "ENG", "IRL", "SCO", "WAL", "ITA", "NZL", "AUS", "ARG", "RSA"]
_CLUBS = [f"Club_{chr(65 + i)}" for i in range(15)]  # Club_A … Club_O


def make_player_pool(n: int = 60) -> list[PlayerSummary]:
    """Build a player pool with varied nationalities and clubs.

    Rotates through 10 nationalities and 15 clubs to avoid hitting
    MAX_PER_NATION (8) or MAX_PER_CLUB (6) during a short test draft.

    Args:
        n: Number of players to generate. Default 60 (2 managers × 30 rounds).

    Returns:
        List of PlayerSummary instances with unique UUIDs.
    """
    return [
        PlayerSummary(
            id=uuid4(),
            first_name="Test",
            last_name=f"Player{i}",
            nationality=_NATIONALITIES[i % len(_NATIONALITIES)],
            club=_CLUBS[i % len(_CLUBS)],
            positions=[PositionType.PROP],
            availability_status=AvailabilityStatus.AVAILABLE,
        )
        for i in range(n)
    ]


def make_engine(
    manager_ids: list[str],
    pick_duration: float = 120.0,
    preference_lists: dict | None = None,
) -> tuple[DraftEngine, MockBroadcaster]:
    """Create a DraftEngine with a MockBroadcaster for testing.

    Args:
        manager_ids: Manager IDs to include. Order will be shuffled by engine.
        pick_duration: Seconds per pick. Use 0.05s for timer-expiry tests.
        preference_lists: Optional preference lists per manager.

    Returns:
        (engine, broadcaster) tuple.
    """
    broadcaster = MockBroadcaster()
    engine = DraftEngine(
        league_id="test-league",
        manager_ids=manager_ids,
        available_players=make_player_pool(60),
        competition_type=CompetitionType.INTERNATIONAL,
        pick_duration=pick_duration,
        preference_lists=preference_lists or {},
        broadcaster=broadcaster,
    )
    return engine, broadcaster


# ---------------------------------------------------------------------------
# Test 1 — Reconnect during own turn with time remaining
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconnect_during_own_turn_deactivates_autodraft() -> None:
    """Manager reconnects during their turn before autodraft fires.

    Setup:
        - 2 managers. Only M2 is connected at draft start.
        - M1 is therefore in autodraft from the start.
        - If M1 is first in the shuffled order, we reconnect M1 before
          the autodraft task fires and verify deactivation.
        - If M2 is first (shuffle puts M2 first), M1 is not yet on turn —
          we skip the deactivation assertion and just verify the snapshot
          is consistent (no autodraft deactivation expected).

    Key timing detail:
        asyncio.create_task() schedules the autodraft coroutine but does
        NOT execute it until the event loop gets control via an await with
        actual duration. connect_manager() under its lock runs before the
        task can fire — this is the reconnection window.
    """
    engine, broadcaster = make_engine(
        manager_ids=["M1", "M2"],
        pick_duration=60.0,
    )

    # M1 not connected at start → M1 enters autodraft.
    await engine.start_draft(connected_manager_ids={"M2"})

    # M1 is always in autodraft regardless of shuffle order.
    assert "M1" in engine._state.autodraft_managers, (
        "M1 should be in autodraft_managers — it was not connected at start"
    )

    first_manager = engine._state.current_manager_id
    assert first_manager is not None

    if first_manager == "M1":
        # M1 is first in the draft order — it's their turn and they're in autodraft.
        # Reconnect M1 before the autodraft task fires.
        snapshot = await engine.connect_manager("M1")

        # Autodraft must be deactivated for M1.
        assert "M1" not in snapshot.autodraft_managers, (
            "Autodraft should be deactivated after M1 reconnects during their turn"
        )

        # Still M1's turn.
        assert snapshot.current_manager_id == "M1"

        # A manual timer must now be running.
        assert engine._current_timer is not None, (
            "A manual timer should be started after autodraft deactivation"
        )

        # Broadcast event must flag autodraft_deactivated=True.
        connected_events = broadcaster.events_of_type("draft.manager_connected")
        assert len(connected_events) >= 1
        last_connected: DraftManagerConnectedEvent = connected_events[-1]  # type: ignore[assignment]
        assert last_connected.autodraft_deactivated is True
        assert last_connected.manager_id == "M1"

        # Clean up.
        engine._current_timer.cancel()

    else:
        # M2 is first — M1 is in autodraft but not yet on turn.
        # Reconnect M1 — no deactivation expected (not their turn yet).
        snapshot = await engine.connect_manager("M1")

        # M1 should still be in autodraft (not their turn).
        assert "M1" in snapshot.autodraft_managers, (
            "M1 should remain in autodraft — it is not their turn yet"
        )
        assert snapshot.current_manager_id == "M2"

        # autodraft_deactivated must be False.
        connected_events = broadcaster.events_of_type("draft.manager_connected")
        last_connected: DraftManagerConnectedEvent = connected_events[-1]  # type: ignore[assignment]
        assert last_connected.autodraft_deactivated is False

        # Clean up.
        if engine._current_timer is not None:
            engine._current_timer.cancel()


# ---------------------------------------------------------------------------
# Test 2 — Reconnect after timer expired (autodraft pick is final)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconnect_after_timer_expired_pick_is_final() -> None:
    """Manager reconnects after their timer expired — autodraft pick is final.

    Setup:
        - 2 managers, both connected at start.
        - Very short pick duration (0.05s) → timer fires almost immediately.
        - Wait 0.3s for at least one autodraft pick to be recorded.

    Expected:
        - At least one autodraft pick in engine._state.picks.
        - Snapshot shows pick #1 is already recorded.
        - current_pick_number has advanced beyond 1.
        - DraftManagerConnectedEvent with autodraft_deactivated=False
          (pick already made — nothing to reclaim).
    """
    engine, broadcaster = make_engine(
        manager_ids=["M1", "M2"],
        pick_duration=0.05,  # 50ms — timer fires almost immediately
    )

    await engine.start_draft(connected_manager_ids={"M1", "M2"})

    # Wait for the timer to expire and autodraft to execute.
    await asyncio.sleep(0.3)

    autodraft_picks = [p for p in engine._state.picks if p.autodrafted]
    assert len(autodraft_picks) >= 1, (
        "Expected at least one autodraft pick after timer expiry"
    )

    first_manager = engine._state.draft_order[0]

    # Reconnect — pick is already made, nothing to reclaim.
    snapshot = await engine.connect_manager(first_manager)

    assert 1 in [p.pick_number for p in snapshot.picks], (
        "Pick #1 should already be recorded in the snapshot"
    )
    assert snapshot.current_pick_number > 1, (
        "current_pick_number should have advanced after autodraft pick"
    )

    connected_events = broadcaster.events_of_type("draft.manager_connected")
    last_connected: DraftManagerConnectedEvent = connected_events[-1]  # type: ignore[assignment]
    assert last_connected.autodraft_deactivated is False


# ---------------------------------------------------------------------------
# Test 3 — Reconnect while another manager is picking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconnect_while_other_manager_picks_no_side_effects() -> None:
    """Manager reconnects while it is someone else's turn.

    Setup:
        - 2 managers, both connected at start (long timer — no expiry).
        - Identify who is NOT the current manager and reconnect them.

    Expected:
        - No autodraft deactivation.
        - DraftManagerConnectedEvent with autodraft_deactivated=False.
        - current_manager_id unchanged in snapshot.
        - Reconnecting manager appears in connected_managers.
    """
    engine, broadcaster = make_engine(
        manager_ids=["M1", "M2"],
        pick_duration=120.0,
    )

    await engine.start_draft(connected_manager_ids={"M1", "M2"})

    first_manager = engine._state.current_manager_id
    assert first_manager is not None

    other_manager = "M2" if first_manager == "M1" else "M1"

    snapshot = await engine.connect_manager(other_manager)

    assert other_manager not in snapshot.autodraft_managers, (
        "Reconnecting while not on turn must not touch autodraft state"
    )
    assert snapshot.current_manager_id == first_manager, (
        "Current manager must be unchanged after other manager reconnects"
    )
    assert other_manager in snapshot.connected_managers

    connected_events = broadcaster.events_of_type("draft.manager_connected")
    last_connected: DraftManagerConnectedEvent = connected_events[-1]  # type: ignore[assignment]
    assert last_connected.autodraft_deactivated is False

    # Clean up timer.
    if engine._current_timer is not None:
        engine._current_timer.cancel()


# ---------------------------------------------------------------------------
# Test 4 — get_state_snapshot() has no side effects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_state_snapshot_no_side_effects() -> None:
    """get_state_snapshot() returns correct data without any side effects.

    The GET /draft/{league_id}/state endpoint calls get_state_snapshot() —
    a read-only method. It must NOT register callers as connected, must NOT
    broadcast any events, and must NOT modify any state.

    Setup:
        - 2 managers, only M2 connected at start.
        - Call get_state_snapshot() (simulates GET /state polling).

    Expected:
        - No new events broadcast after the call.
        - connected_managers unchanged.
        - current_pick_number unchanged.
        - Snapshot accurately reflects draft state (M1 absent from connected).
    """
    engine, broadcaster = make_engine(
        manager_ids=["M1", "M2"],
        pick_duration=120.0,
    )

    await engine.start_draft(connected_manager_ids={"M2"})

    events_before = broadcaster.event_count()
    connected_before = set(engine._state.connected_managers)
    pick_number_before = engine._state.current_pick_number

    # Read-only call — simulates GET /state.
    snapshot = engine.get_state_snapshot()

    assert broadcaster.event_count() == events_before, (
        "get_state_snapshot() must not broadcast any events"
    )
    assert set(snapshot.connected_managers) == connected_before, (
        "get_state_snapshot() must not modify connected_managers"
    )
    assert snapshot.current_pick_number == pick_number_before
    assert snapshot.status == DraftStatus.IN_PROGRESS
    assert snapshot.league_id == "test-league"
    assert "M1" not in snapshot.connected_managers

    # Clean up.
    if engine._current_timer is not None:
        engine._current_timer.cancel()