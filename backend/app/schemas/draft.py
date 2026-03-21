# backend/app/schemas/draft.py
"""
Pydantic response schemas for the draft endpoints.

These schemas define the shape of data returned by the draft API.
They are separate from the internal DraftState / DraftStateSnapshot
dataclasses used by the DraftEngine — this separation allows the
API contract to evolve independently of the engine internals.

Naming convention:
    *Response  — outbound schema (API → client)
    *Request   — inbound schema (client → API)  [added as needed]
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from draft.engine import DraftStatus


# ---------------------------------------------------------------------------
# Pick record
# ---------------------------------------------------------------------------


class PickRecordResponse(BaseModel):
    """A single pick recorded in the draft history.

    Attributes:
        pick_number: Absolute pick number, 1-indexed.
        manager_id: Manager who made (or had autodrafted for) this pick.
        player_id: ID of the drafted player.
        autodrafted: True if the system made this pick (timer expired
                     or manual autodraft activation).
        autodraft_source: How autodraft selected the player.
                          "preference_list" | "default_value" | None.
        timestamp: asyncio loop time when the pick was recorded.
    """

    pick_number: int = Field(..., ge=1, description="Absolute pick number, 1-indexed.")
    manager_id: str = Field(..., description="Manager who made this pick.")
    player_id: str = Field(..., description="ID of the drafted player.")
    autodrafted: bool = Field(
        default=False,
        description="True if autodraft made this pick.",
    )
    autodraft_source: Optional[str] = Field(
        default=None,
        description="'preference_list' | 'default_value' | None.",
    )
    timestamp: float = Field(
        default=0.0,
        description="asyncio loop time when the pick was recorded.",
    )
    entered_by_commissioner: bool = Field(
        default=False,
        description="True if this pick was entered by the commissioner in assisted mode.",
    )

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Draft state snapshot (reconnection response)
# ---------------------------------------------------------------------------


class DraftStateSnapshotResponse(BaseModel):
    """Full draft state snapshot returned on client reconnection.

    Sent by GET /draft/{league_id}/state and POST /draft/{league_id}/connect.
    Contains everything the client needs to reconstruct its local view of
    the draft without any further queries.

    Timer synchronisation note (D-001):
        The client recomputes time_remaining from this snapshot.
        There is no server tick broadcast — the client uses the
        snapshot's time_remaining directly on reconnect.

    Attributes:
        league_id: The league this draft belongs to.
        status: Current draft lifecycle status.
        current_pick_number: Pick slot currently being filled (1-indexed).
        total_picks: Total number of picks in this draft.
        current_manager_id: Manager whose turn it is. None if completed.
        time_remaining: Seconds left on the current pick timer.
                        0.0 if draft is completed or in autodraft.
        picks: All picks made so far, in order.
        autodraft_managers: Manager IDs currently in autodraft mode.
        connected_managers: Manager IDs currently connected.
    """

    league_id: str = Field(..., description="The league this draft belongs to.")
    status: DraftStatus = Field(..., description="Current draft lifecycle status.")
    current_pick_number: int = Field(
        ..., ge=1, description="Pick slot being filled (1-indexed)."
    )
    total_picks: int = Field(..., ge=1, description="Total picks in this draft.")
    current_manager_id: Optional[str] = Field(
        default=None,
        description="Manager whose turn it is. None if draft completed.",
    )
    time_remaining: float = Field(
        ...,
        ge=0.0,
        description=(
            "Seconds left on the current pick timer. "
            "0.0 if completed or in autodraft mode."
        ),
    )
    picks: list[PickRecordResponse] = Field(
        default_factory=list,
        description="All picks made so far, in chronological order.",
    )
    autodraft_managers: list[str] = Field(
        default_factory=list,
        description="Manager IDs currently in autodraft mode.",
    )
    connected_managers: list[str] = Field(
        default_factory=list,
        description="Manager IDs currently connected.",
    )

    model_config = {"from_attributes": True}