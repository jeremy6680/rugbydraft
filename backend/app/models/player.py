# backend/app/models/player.py
"""
Pydantic schemas for the Player entity.

Players are rugby players available in the draft pool.
A player can have multiple positions (multi-position rule from CDC section 4).

These schemas mirror the `players` and `player_positions` tables defined
in db/migrations/001_initial_schema.sql.

Key decisions:
    - D-013: number_8 is a distinct position type from flanker
    - Availability status uses the same enum as the DB (available/injured/suspended)
    - positions is a non-empty list — a player must have at least one position
"""

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class PositionType(StrEnum):
    """
    Rugby player positions — mirrors the position_type enum in PostgreSQL.

    Forwards (1-8):
        prop, hooker, lock, flanker, number_8

    Backs (9-15):
        scrum_half, fly_half, centre, wing, fullback
    """

    # ── Forwards ──────────────────────────────────────────────────────────────
    PROP = "prop"
    HOOKER = "hooker"
    LOCK = "lock"
    FLANKER = "flanker"
    NUMBER_8 = "number_8"  # D-013: distinct from flanker

    # ── Backs ─────────────────────────────────────────────────────────────────
    SCRUM_HALF = "scrum_half"
    FLY_HALF = "fly_half"
    CENTRE = "centre"
    WING = "wing"
    FULLBACK = "fullback"


class AvailabilityStatus(StrEnum):
    """
    Player availability status — mirrors the availability_status enum in PostgreSQL.

    available   — fit to play, eligible for draft and lineups
    injured     — on the IR list, cannot be in active lineup
    suspended   — serving a ban, cannot be in active lineup
    """

    AVAILABLE = "available"
    INJURED = "injured"
    SUSPENDED = "suspended"


class PlayerBase(BaseModel):
    """Fields shared across all Player schemas."""

    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    nationality: str = Field(
        ...,
        pattern=r"^[A-Z]{2,3}$",
        description="ISO 3166-1 alpha-2 or alpha-3 country code (e.g. 'FR', 'ENG').",
    )
    club: str = Field(..., max_length=100)
    positions: list[PositionType] = Field(
        ...,
        min_length=1,
        description="Player's eligible positions. At least one required.",
    )
    photo_url: str | None = Field(default=None)

    @field_validator("positions")
    @classmethod
    def positions_must_be_unique(cls, value: list[PositionType]) -> list[PositionType]:
        """Reject duplicate positions in the list."""
        if len(value) != len(set(value)):
            raise ValueError("positions list must not contain duplicates.")
        return value


class PlayerCreate(PlayerBase):
    """
    Schema for creating a new player record.

    Used by the data pipeline (connector → bronze → silver) when ingesting
    players from the rugby data provider. Not exposed as a public API endpoint.
    """

    external_id: str = Field(
        ...,
        description=(
            "Player ID from the rugby data provider. "
            "Used to match records on subsequent ingestions."
        ),
    )
    date_of_birth: date | None = Field(default=None)


class PlayerRead(PlayerBase):
    """
    Full player representation returned by the API.

    Includes availability status and draft eligibility flag.
    external_id is excluded — internal pipeline identifier, not for clients.
    """

    id: UUID
    availability_status: AvailabilityStatus = Field(
        default=AvailabilityStatus.AVAILABLE,
    )
    date_of_birth: date | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PlayerUpdate(BaseModel):
    """
    Fields that can be updated via PATCH /players/{id}.

    Typically used by the pipeline to update availability status,
    club transfers, or photo URL. All fields optional.
    """

    club: str | None = Field(default=None, max_length=100)
    positions: list[PositionType] | None = Field(default=None, min_length=1)
    availability_status: AvailabilityStatus | None = Field(default=None)
    photo_url: str | None = Field(default=None)

    @field_validator("positions")
    @classmethod
    def positions_must_be_unique(
        cls, value: list[PositionType] | None
    ) -> list[PositionType] | None:
        """Reject duplicate positions if provided."""
        if value is not None and len(value) != len(set(value)):
            raise ValueError("positions list must not contain duplicates.")
        return value


class PlayerSummary(BaseModel):
    """
    Lightweight player representation for list endpoints and draft room.

    Used when returning many players at once — avoids sending full details
    for every player in the pool (potentially 300+ players).
    """

    id: UUID
    first_name: str
    last_name: str
    nationality: str
    club: str
    positions: list[PositionType]
    availability_status: AvailabilityStatus

    model_config = {"from_attributes": True}
