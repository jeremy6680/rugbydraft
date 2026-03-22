"""Pydantic models for trade endpoints.

Conventions:
  - *Input  — request body validation (what the client sends)
  - *Response — response serialisation (what the API returns)

All datetimes are UTC, serialised as ISO 8601 strings.
player_ids are lists in HTTP JSON but converted to frozenset
in the service layer before reaching the processor.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator

from trades.processor import TradeStatus


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

# CDC §9.2: each side sends 1, 2, or 3 players.
MIN_PLAYERS_PER_SIDE: int = 1
MAX_PLAYERS_PER_SIDE: int = 3


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------


class TradeProposalInput(BaseModel):
    """Request body for POST /trades — propose a new trade.

    Attributes:
        receiver_member_id: The league member UUID of the manager receiving
            the proposal.
        proposer_player_ids: Player UUIDs the proposer is giving away (1–3).
        receiver_player_ids: Player UUIDs the proposer wants in return (1–3).
    """

    receiver_member_id: Annotated[str, Field(min_length=1)]
    proposer_player_ids: Annotated[
        list[str],
        Field(
            min_length=MIN_PLAYERS_PER_SIDE,
            max_length=MAX_PLAYERS_PER_SIDE,
        ),
    ]
    receiver_player_ids: Annotated[
        list[str],
        Field(
            min_length=MIN_PLAYERS_PER_SIDE,
            max_length=MAX_PLAYERS_PER_SIDE,
        ),
    ]

    @field_validator("proposer_player_ids", "receiver_player_ids")
    @classmethod
    def no_duplicate_player_ids(cls, v: list[str]) -> list[str]:
        """Reject duplicate player IDs within the same side."""
        if len(v) != len(set(v)):
            raise ValueError("Duplicate player IDs are not allowed on the same side.")
        return v

    @model_validator(mode="after")
    def no_cross_side_duplicates(self) -> TradeProposalInput:
        """Reject player IDs that appear on both sides."""
        overlap = set(self.proposer_player_ids) & set(self.receiver_player_ids)
        if overlap:
            raise ValueError(
                f"Player ID(s) {overlap} appear on both sides of the trade."
            )
        return self


class TradeVetoInput(BaseModel):
    """Request body for POST /trades/{trade_id}/veto.

    Attributes:
        reason: Mandatory free-text reason for the veto (CDC §9.2).
            Must not be blank — enforced at Pydantic level before
            reaching the processor.
    """

    reason: Annotated[str, Field(min_length=1, max_length=1000)]

    @field_validator("reason")
    @classmethod
    def reason_not_blank(cls, v: str) -> str:
        """Reject whitespace-only reasons."""
        if not v.strip():
            raise ValueError("Veto reason cannot be blank or whitespace only.")
        return v.strip()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class TradePlayerResponse(BaseModel):
    """One player entry in a trade response.

    Attributes:
        player_id: The player UUID.
        from_member_id: The member giving this player away.
        to_member_id: The member receiving this player.
    """

    player_id: str
    from_member_id: str
    to_member_id: str


class TradeResponse(BaseModel):
    """Full trade record returned by all trade endpoints.

    Returned by: POST /trades, GET /trades/{id},
    POST /trades/{id}/accept, POST /trades/{id}/reject,
    POST /trades/{id}/cancel, POST /trades/{id}/veto.

    Attributes:
        trade_id: UUID of the trade.
        league_id: The league this trade belongs to.
        proposer_id: Member UUID of the proposer.
        receiver_id: Member UUID of the receiver.
        status: Current trade status.
        players: All player entries with direction.
        veto_enabled: Whether commissioner veto is active on this league.
        veto_deadline: When the veto window closes (None if veto not enabled
            or trade not yet accepted).
        veto_reason: Commissioner's reason if status is VETOED.
        veto_at: When the veto was cast (None unless VETOED).
        completed_at: When the trade took effect (None unless COMPLETED).
        created_at: When the trade was proposed.
    """

    trade_id: str
    league_id: str
    proposer_id: str
    receiver_id: str
    status: TradeStatus
    players: list[TradePlayerResponse]
    veto_enabled: bool
    veto_deadline: datetime | None
    veto_reason: str | None
    veto_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TradeListResponse(BaseModel):
    """Paginated list of trades for GET /trades.

    Attributes:
        trades: List of trade records.
        total: Total number of trades matching the query (for pagination).
    """

    trades: list[TradeResponse]
    total: int
