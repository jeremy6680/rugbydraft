# backend/draft/timer.py
"""
Server-side draft timer for RugbyDraft.

The timer runs as an asyncio Task inside the FastAPI event loop.
It is the authoritative countdown for each pick slot — clients receive
the remaining time via Supabase Realtime broadcast but never control it.

Business rules (CDC v3.1, section 7.2):
- Pick duration is configurable by the commissioner: 30s to 3 minutes.
- Default: 2 minutes (120 seconds).
- On expiration: autodraft is triggered automatically.
- On cancel (manager picked before expiration): timer is stopped cleanly.

Design principles:
- No I/O, no database, no FastAPI dependency — pure asyncio.
- Testable in isolation with short durations (e.g. 0.1s).
- The on_expire callback is async to allow awaiting downstream effects
  (e.g. triggering autodraft, broadcasting state).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Optional

logger = logging.getLogger(__name__)

# Default pick duration in seconds (CDC v3.1, section 7.2)
DEFAULT_PICK_DURATION_SECONDS: int = 120

# Allowed range for commissioner-configured pick duration
MIN_PICK_DURATION_SECONDS: int = 30
MAX_PICK_DURATION_SECONDS: int = 180


class DraftTimer:
    """Server-side countdown timer for a single draft pick slot.

    Each pick slot gets its own DraftTimer instance. The DraftEngine
    is responsible for creating and cancelling timers as picks are made.

    Usage:
        async def on_expire():
            await trigger_autodraft(...)

        timer = DraftTimer(duration=120, on_expire=on_expire)
        timer.start()

        # Manager picks before expiration:
        timer.cancel()

        # Query remaining time at any point:
        remaining = timer.time_remaining

    Attributes:
        duration: Total duration of this timer in seconds.
        on_expire: Async callback invoked when the timer reaches zero.
    """

    def __init__(
        self,
        duration: float,
        on_expire: Callable[[], Awaitable[None]],
    ) -> None:
        """Initialise the timer. Does NOT start the countdown.

        Call start() explicitly to begin the countdown.

        Args:
            duration: Countdown duration in seconds. Must be > 0.
            on_expire: Async callable invoked when time runs out.
                       Must be awaitable (async def).

        Raises:
            ValueError: If duration <= 0.
        """
        if duration <= 0:
            raise ValueError(f"duration must be > 0, got {duration}")

        self.duration: float = duration
        self.on_expire: Callable[[], Awaitable[None]] = on_expire

        # Internal state — not exposed directly
        self._task: Optional[asyncio.Task[None]] = None
        self._started_at: Optional[float] = None  # loop.time() snapshot
        self._cancelled: bool = False
        self._expired: bool = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the countdown.

        Schedules the countdown coroutine as an asyncio Task.
        Must be called from within a running event loop.

        Raises:
            RuntimeError: If start() is called more than once.
            RuntimeError: If there is no running event loop.
        """
        if self._task is not None:
            raise RuntimeError("DraftTimer.start() called more than once")

        loop = asyncio.get_event_loop()
        self._started_at = loop.time()
        self._task = asyncio.ensure_future(self._countdown())
        logger.debug("DraftTimer started: duration=%.1fs", self.duration)

    def cancel(self) -> None:
        """Cancel the timer before it expires.

        Safe to call even if the timer has already expired or was never
        started — it will simply be a no-op in those cases.
        """
        if self._task is not None and not self._task.done():
            self._task.cancel()
            self._cancelled = True
            logger.debug("DraftTimer cancelled with %.2fs remaining", self.time_remaining)

    @property
    def time_remaining(self) -> float:
        """Return the number of seconds remaining on the countdown.

        Returns:
            Seconds remaining, clamped to [0.0, duration].
            Returns 0.0 if the timer has not been started yet,
            has already expired, or was cancelled.
        """
        if self._started_at is None:
            # Not started yet
            return self.duration

        if self._cancelled or self._expired:
            return 0.0

        elapsed = asyncio.get_event_loop().time() - self._started_at
        remaining = self.duration - elapsed
        return max(0.0, remaining)

    @property
    def is_running(self) -> bool:
        """Return True if the countdown is active (started, not done)."""
        return (
            self._task is not None
            and not self._task.done()
            and not self._cancelled
        )

    @property
    def is_expired(self) -> bool:
        """Return True if the timer ran to zero and triggered on_expire."""
        return self._expired

    @property
    def is_cancelled(self) -> bool:
        """Return True if the timer was cancelled before expiration."""
        return self._cancelled

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _countdown(self) -> None:
        """Internal coroutine: sleep for duration, then fire on_expire.

        Uses asyncio.sleep which yields control back to the event loop —
        FastAPI can continue handling requests during the countdown.

        If cancelled (via Task.cancel()), asyncio raises CancelledError
        inside the sleep, which we catch and swallow cleanly.
        """
        try:
            await asyncio.sleep(self.duration)
            self._expired = True
            logger.debug("DraftTimer expired — triggering on_expire callback")
            await self.on_expire()
        except asyncio.CancelledError:
            # Timer was cancelled cleanly (manager picked) — not an error
            logger.debug("DraftTimer: CancelledError caught cleanly")