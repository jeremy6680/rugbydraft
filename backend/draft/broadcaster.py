# backend/draft/broadcaster.py
"""
Broadcast layer for the RugbyDraft draft engine.

Architecture principle (D-001):
    FastAPI is the authority of state. Supabase Realtime is a broadcast
    channel only. The DraftEngine calls broadcast() after every state
    mutation — clients receive updates but never write state directly.

Design:
    BroadcasterProtocol — structural interface (PEP 544 Protocol).
    SupabaseBroadcaster — production implementation using supabase-py v2.
    MockBroadcaster     — test implementation that captures calls, no I/O.

Channel naming convention: "draft:{league_id}"

Usage (production):
    broadcaster = SupabaseBroadcaster(supabase_client, league_id="abc123")
    await broadcaster.connect()

    engine = DraftEngine(..., broadcaster=broadcaster)
    await engine.start_draft(...)

    await broadcaster.disconnect()

Usage (tests):
    broadcaster = MockBroadcaster()
    engine = DraftEngine(..., broadcaster=broadcaster)
    await engine.start_draft(...)
    assert broadcaster.last_event_type() == "draft.started"
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from draft.events import DraftEvent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocol — structural interface for the DraftEngine
# ---------------------------------------------------------------------------


@runtime_checkable
class BroadcasterProtocol(Protocol):
    """Structural interface expected by the DraftEngine.

    Any class implementing async broadcast(event) satisfies this protocol —
    no explicit inheritance required (PEP 544 duck typing).

    The @runtime_checkable decorator allows isinstance() checks at runtime,
    useful for debugging and FastAPI dependency injection.
    """

    async def broadcast(self, event: DraftEvent) -> None:
        """Broadcast a draft event to all subscribed clients.

        Args:
            event: A typed DraftEvent subclass (DraftPickMadeEvent, etc.).
                   Serialised to JSON via event.to_dict() before sending.
        """
        ...


# ---------------------------------------------------------------------------
# MockBroadcaster — for tests
# ---------------------------------------------------------------------------


class MockBroadcaster:
    """Test implementation — captures broadcast calls without any I/O.

    Usage in tests:
        broadcaster = MockBroadcaster()
        engine = DraftEngine(..., broadcaster=broadcaster)
        await engine.start_draft(...)

        # Assert that specific events were broadcast
        assert broadcaster.event_count() == 1
        assert broadcaster.last_event_type() == "draft.started"
        assert broadcaster.events[0].league_id == "test-league"

    Attributes:
        events: List of all DraftEvent instances received, in order.
    """

    def __init__(self) -> None:
        self.events: list[DraftEvent] = []

    async def broadcast(self, event: DraftEvent) -> None:
        """Capture the event — no network call, no side effects.

        Args:
            event: The DraftEvent to capture.
        """
        self.events.append(event)
        logger.debug(
            "MockBroadcaster: captured event '%s' for league '%s'",
            event.event_type,
            event.league_id,
        )

    # -- Convenience helpers for test assertions --

    def event_count(self) -> int:
        """Return the total number of events captured."""
        return len(self.events)

    def last_event(self) -> DraftEvent | None:
        """Return the most recently captured event, or None if empty."""
        return self.events[-1] if self.events else None

    def last_event_type(self) -> str | None:
        """Return the event_type of the last captured event, or None."""
        last = self.last_event()
        return last.event_type if last is not None else None

    def events_of_type(self, event_type: str) -> list[DraftEvent]:
        """Return all events of a given event_type.

        Args:
            event_type: e.g. "draft.pick_made"

        Returns:
            Filtered list, preserving original order.
        """
        return [e for e in self.events if e.event_type == event_type]

    def reset(self) -> None:
        """Clear all captured events — useful between test assertions."""
        self.events.clear()


# ---------------------------------------------------------------------------
# SupabaseBroadcaster — production implementation
# ---------------------------------------------------------------------------


class SupabaseBroadcaster:
    """Production broadcaster using Supabase Realtime channels.

    One instance per active draft. The channel is opened once (connect)
    and reused for the entire draft lifetime to avoid per-message overhead.

    Channel name: "draft:{league_id}" — clients subscribe to this channel
    to receive all events for their draft.

    Args:
        client: An authenticated supabase AsyncClient instance.
        league_id: The league ID — used to name the channel.

    Raises:
        RuntimeError: If broadcast() is called before connect().
    """

    def __init__(self, client, league_id: str) -> None:
        """Initialise the broadcaster. Does NOT open the channel.

        Call connect() explicitly before starting the draft.

        Args:
            client: supabase.AsyncClient (created by create_async_client()).
            league_id: The league this broadcaster serves.
        """
        self._client = client
        self._league_id = league_id
        self._channel_name = f"draft:{league_id}"
        self._channel = None  # set in connect()

    async def connect(self) -> None:
        """Open the Realtime channel and subscribe.

        Must be called once before any broadcast() calls.
        Safe to call again (no-op if already connected).
        """
        if self._channel is not None:
            logger.debug(
                "SupabaseBroadcaster.connect(): channel '%s' already open",
                self._channel_name,
            )
            return

        self._channel = self._client.channel(self._channel_name)
        await self._channel.subscribe()
        logger.info(
            "SupabaseBroadcaster: channel '%s' open",
            self._channel_name,
        )

    async def disconnect(self) -> None:
        """Close the Realtime channel.

        Call this when the draft ends or the FastAPI process shuts down.
        Safe to call if not connected (no-op).
        """
        if self._channel is None:
            return

        await self._client.remove_channel(self._channel)
        self._channel = None
        logger.info(
            "SupabaseBroadcaster: channel '%s' closed",
            self._channel_name,
        )

    async def broadcast(self, event: DraftEvent) -> None:
        """Send a draft event to all clients subscribed to this channel.

        Serialises the event to a JSON-compatible dict via event.to_dict()
        and sends it as a Supabase Realtime broadcast message.

        Args:
            event: A typed DraftEvent subclass.

        Raises:
            RuntimeError: If connect() has not been called.
        """
        if self._channel is None:
            raise RuntimeError(
                f"SupabaseBroadcaster.broadcast() called before connect() "
                f"on channel '{self._channel_name}'"
            )

        payload = event.to_dict()
        try:
            await self._channel.send_broadcast(event.event_type, payload)
            logger.debug(
                "Broadcast '%s' on channel '%s'",
                event.event_type,
                self._channel_name,
            )
        except Exception as exc:
            # Log but do NOT raise — a broadcast failure must never crash the draft.
            # The client can always call GET /draft/{id}/state for a full snapshot.
            logger.error(
                "Broadcast failed for event '%s' on channel '%s': %s",
                event.event_type,
                self._channel_name,
                exc,
            )
