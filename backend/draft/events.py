# backend/draft/events.py
"""
Typed broadcast event payloads for the RugbyDraft draft engine.

Each event corresponds to a state change in the DraftEngine.
These payloads are serialised to JSON and broadcast via Supabase
Realtime to all clients subscribed to the draft channel.

Channel naming convention: "draft:{league_id}"

Event types:
    draft.started          — draft kicked off, initial state sent
    draft.pick_made        — a pick (manual or autodraft) was recorded
    draft.turn_changed     — it is now a different manager's turn
    draft.manager_connected    — a manager joined or reconnected
    draft.manager_disconnected — a manager left
    draft.completed        — all picks made, draft is over

Timer synchronisation note (D-001):
    We do NOT broadcast a tick every second. Instead, draft.turn_changed
    includes `turn_started_at` (server monotonic time) and `pick_duration`.
    Clients compute their own countdown: pick_duration - (now - turn_started_at).
    This pattern is called "clock synchronisation" — far fewer messages,
    immune to dropped ticks.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Base event
# ---------------------------------------------------------------------------


@dataclass
class DraftEvent:
    """Base class for all draft broadcast events.

    Attributes:
        event_type: Machine-readable event identifier (e.g. "draft.pick_made").
        league_id: The league this event belongs to.
        server_time: Unix timestamp (float) of when the event was created.
    """

    event_type: str
    league_id: str
    server_time: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Serialise event to a JSON-compatible dict."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Concrete event types
# ---------------------------------------------------------------------------


@dataclass
class DraftStartedEvent(DraftEvent):
    """Broadcast when the draft transitions from PENDING to IN_PROGRESS.

    Attributes:
        managers: Ordered manager list after the random draw.
        total_picks: Total number of picks (managers × 30 rounds).
        current_manager_id: Manager who picks first.
        pick_duration: Seconds per pick slot.
        autodraft_managers: Managers already in autodraft (never connected).
    """

    event_type: str = field(default="draft.started", init=False)
    managers: list[str] = field(default_factory=list)
    total_picks: int = 0
    current_manager_id: Optional[str] = None
    pick_duration: float = 120.0
    autodraft_managers: list[str] = field(default_factory=list)


@dataclass
class DraftPickMadeEvent(DraftEvent):
    """Broadcast immediately after a pick is recorded (manual or autodraft).

    Attributes:
        pick_number: The absolute pick number that was just made.
        manager_id: Manager who made the pick.
        player_id: Player who was drafted.
        autodrafted: True if the system picked (timer expired or manual autodraft).
        autodraft_source: "preference_list" | "default_value" | None.
    """

    event_type: str = field(default="draft.pick_made", init=False)
    pick_number: int = 0
    manager_id: str = ""
    player_id: str = ""
    autodrafted: bool = False
    autodraft_source: Optional[str] = None


@dataclass
class DraftTurnChangedEvent(DraftEvent):
    """Broadcast when the pick slot advances to the next manager.

    Clients use turn_started_at + pick_duration to drive their local
    countdown timer — no tick broadcasts needed.

    Attributes:
        current_pick_number: New pick number (just incremented).
        current_manager_id: Manager whose turn it now is.
        pick_duration: Seconds allowed for this pick.
        turn_started_at: Server Unix timestamp when this turn began.
    """

    event_type: str = field(default="draft.turn_changed", init=False)
    current_pick_number: int = 0
    current_manager_id: Optional[str] = None
    pick_duration: float = 120.0
    turn_started_at: float = field(default_factory=time.time)


@dataclass
class DraftManagerConnectedEvent(DraftEvent):
    """Broadcast when a manager connects or reconnects.

    Attributes:
        manager_id: The manager who connected.
        connected_managers: All currently connected managers.
        autodraft_deactivated: True if autodraft was turned off on reconnect.
    """

    event_type: str = field(default="draft.manager_connected", init=False)
    manager_id: str = ""
    connected_managers: list[str] = field(default_factory=list)
    autodraft_deactivated: bool = False


@dataclass
class DraftManagerDisconnectedEvent(DraftEvent):
    """Broadcast when a manager disconnects.

    Attributes:
        manager_id: The manager who disconnected.
        connected_managers: Remaining connected managers.
    """

    event_type: str = field(default="draft.manager_disconnected", init=False)
    manager_id: str = ""
    connected_managers: list[str] = field(default_factory=list)


@dataclass
class DraftCompletedEvent(DraftEvent):
    """Broadcast when all picks have been made and the draft is over.

    Attributes:
        total_picks: Total number of picks made.
    """

    event_type: str = field(default="draft.completed", init=False)
    total_picks: int = 0