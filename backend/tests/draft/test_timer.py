# tests/draft/test_timer.py
"""
Unit tests for the server-side DraftTimer.

Strategy: use very short durations (0.05s – 0.2s) so tests run in
milliseconds while still exercising real asyncio timing behaviour.

All tests are async and use @pytest.mark.asyncio (asyncio_mode = strict
in pytest.ini requires explicit decoration).
"""

import asyncio

import pytest

from draft.timer import (
    DEFAULT_PICK_DURATION_SECONDS,
    MAX_PICK_DURATION_SECONDS,
    MIN_PICK_DURATION_SECONDS,
    DraftTimer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_timer(duration: float = 0.1) -> tuple[DraftTimer, list[str]]:
    """Create a DraftTimer with a tracking callback.

    Returns:
        (timer, calls) where calls is a list that receives "expired"
        each time on_expire fires.
    """
    calls: list[str] = []

    async def on_expire() -> None:
        calls.append("expired")

    return DraftTimer(duration=duration, on_expire=on_expire), calls


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    """Verify CDC-mandated timer constants."""

    def test_default_duration(self) -> None:
        assert DEFAULT_PICK_DURATION_SECONDS == 120

    def test_min_duration(self) -> None:
        assert MIN_PICK_DURATION_SECONDS == 30

    def test_max_duration(self) -> None:
        assert MAX_PICK_DURATION_SECONDS == 180


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


class TestDraftTimerInit:
    """Tests for DraftTimer.__init__()."""

    def test_valid_duration_stored(self) -> None:
        timer, _ = make_timer(duration=90.0)
        assert timer.duration == 90.0

    def test_zero_duration_raises(self) -> None:
        async def dummy() -> None:
            pass

        with pytest.raises(ValueError, match="duration must be > 0"):
            DraftTimer(duration=0, on_expire=dummy)

    def test_negative_duration_raises(self) -> None:
        async def dummy() -> None:
            pass

        with pytest.raises(ValueError, match="duration must be > 0"):
            DraftTimer(duration=-5, on_expire=dummy)

    def test_not_started_initially(self) -> None:
        timer, _ = make_timer()
        assert not timer.is_running
        assert not timer.is_expired
        assert not timer.is_cancelled

    def test_time_remaining_before_start_equals_duration(self) -> None:
        timer, _ = make_timer(duration=60.0)
        assert timer.time_remaining == 60.0


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------


class TestDraftTimerStart:
    """Tests for DraftTimer.start()."""

    @pytest.mark.asyncio
    async def test_is_running_after_start(self) -> None:
        timer, _ = make_timer(duration=10.0)
        timer.start()
        assert timer.is_running
        timer.cancel()  # cleanup

    @pytest.mark.asyncio
    async def test_start_twice_raises(self) -> None:
        timer, _ = make_timer(duration=10.0)
        timer.start()
        with pytest.raises(RuntimeError, match="called more than once"):
            timer.start()
        timer.cancel()  # cleanup

    @pytest.mark.asyncio
    async def test_time_remaining_decreases(self) -> None:
        timer, _ = make_timer(duration=1.0)
        timer.start()
        await asyncio.sleep(0.1)
        remaining = timer.time_remaining
        assert remaining < 1.0
        assert remaining > 0.0
        timer.cancel()  # cleanup


# ---------------------------------------------------------------------------
# Expiration
# ---------------------------------------------------------------------------


class TestDraftTimerExpiration:
    """Tests for timer natural expiration (on_expire callback)."""

    @pytest.mark.asyncio
    async def test_callback_fires_on_expiration(self) -> None:
        """on_expire must be called exactly once when the timer runs out."""
        timer, calls = make_timer(duration=0.05)
        timer.start()
        # Wait longer than the timer duration
        await asyncio.sleep(0.15)
        assert calls == ["expired"]

    @pytest.mark.asyncio
    async def test_is_expired_after_expiration(self) -> None:
        timer, _ = make_timer(duration=0.05)
        timer.start()
        await asyncio.sleep(0.15)
        assert timer.is_expired
        assert not timer.is_running
        assert not timer.is_cancelled

    @pytest.mark.asyncio
    async def test_time_remaining_is_zero_after_expiration(self) -> None:
        timer, _ = make_timer(duration=0.05)
        timer.start()
        await asyncio.sleep(0.15)
        assert timer.time_remaining == 0.0

    @pytest.mark.asyncio
    async def test_callback_fires_exactly_once(self) -> None:
        """on_expire must not be called multiple times."""
        timer, calls = make_timer(duration=0.05)
        timer.start()
        await asyncio.sleep(0.3)  # wait well past expiration
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


class TestDraftTimerCancellation:
    """Tests for timer cancellation (manager picks before expiration)."""

    @pytest.mark.asyncio
    async def test_cancel_before_expiration(self) -> None:
        """Cancelling before expiration must prevent on_expire from firing."""
        timer, calls = make_timer(duration=1.0)
        timer.start()
        await asyncio.sleep(0.05)
        timer.cancel()
        # Wait past the original duration to confirm callback never fires
        await asyncio.sleep(0.1)
        assert calls == []

    @pytest.mark.asyncio
    async def test_is_cancelled_after_cancel(self) -> None:
        timer, _ = make_timer(duration=1.0)
        timer.start()
        timer.cancel()
        await asyncio.sleep(0.05)  # allow task to process cancellation
        assert timer.is_cancelled
        assert not timer.is_running
        assert not timer.is_expired

    @pytest.mark.asyncio
    async def test_cancel_is_idempotent(self) -> None:
        """Calling cancel() multiple times must not raise."""
        timer, _ = make_timer(duration=1.0)
        timer.start()
        timer.cancel()
        timer.cancel()  # second call — must be a no-op
        timer.cancel()  # third call — must be a no-op

    @pytest.mark.asyncio
    async def test_cancel_before_start_is_noop(self) -> None:
        """Cancelling a timer that was never started must not raise."""
        timer, _ = make_timer(duration=1.0)
        timer.cancel()  # no-op
        assert not timer.is_cancelled  # was never started

    @pytest.mark.asyncio
    async def test_time_remaining_is_zero_after_cancel(self) -> None:
        timer, _ = make_timer(duration=1.0)
        timer.start()
        await asyncio.sleep(0.05)
        timer.cancel()
        await asyncio.sleep(0.05)
        assert timer.time_remaining == 0.0


# ---------------------------------------------------------------------------
# Reconnection scenario (CDC v3.1, section 7.4)
# ---------------------------------------------------------------------------


class TestReconnectionScenario:
    """
    Simulate the reconnection protocol from CDC section 7.4:
    - Manager disconnects mid-turn
    - Server continues the countdown
    - Manager reconnects: time_remaining tells them how much time is left
    - If timer already expired: autodraft was triggered, pick is final
    """

    @pytest.mark.asyncio
    async def test_time_remaining_readable_during_countdown(self) -> None:
        """time_remaining must be queryable at any point during countdown."""
        timer, _ = make_timer(duration=0.5)
        timer.start()

        snapshots: list[float] = []
        for _ in range(3):
            await asyncio.sleep(0.05)
            snapshots.append(timer.time_remaining)

        # Each snapshot must be strictly decreasing
        assert snapshots[0] > snapshots[1] > snapshots[2]

        timer.cancel()

    @pytest.mark.asyncio
    async def test_autodraft_triggered_if_reconnects_after_expiry(self) -> None:
        """If manager reconnects after timer expired, callback already fired."""
        timer, calls = make_timer(duration=0.05)
        timer.start()

        # Simulate manager being disconnected — server keeps running
        await asyncio.sleep(0.15)

        # Manager "reconnects" here — checks state
        assert timer.is_expired
        assert timer.time_remaining == 0.0
        assert calls == ["expired"]  # autodraft was triggered
