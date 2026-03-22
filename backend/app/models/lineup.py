"""
Pydantic models for weekly lineup management.

Covers:
- LineupPlayerInput: a single player in a lineup submission
- LineupSubmission: full lineup for a round (15 starters + captain + kicker)
- CaptainUpdate: change captain designation
- KickerUpdate: change kicker designation
- LineupPlayer: a player as returned by the API (includes lock status)
- LineupResponse: full lineup as returned by the API
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class LineupPlayerInput(BaseModel):
    """A single player in a lineup submission request.

    The `position` field is required for all players:
    - For single-position players: must match their natural position.
    - For multi-position players: the manager's choice for this round.
      Validated against players.positions[] in the service layer.
    """

    player_id: UUID
    position: str = Field(
        ...,
        description="Position played this round. Must be in the player's positions[].",
    )


class LineupSubmission(BaseModel):
    """Full lineup submission for a given round.

    Rules enforced by the service layer (not here):
    - Exactly 15 starters required.
    - Captain must be in the starter list.
    - Kicker must be in the starter list.
    - All players must belong to the roster.
    - No player on IR slot can be a starter.
    - Position must be valid for each player.
    """

    starters: list[LineupPlayerInput] = Field(
        ...,
        min_length=15,
        max_length=15,
        description="Exactly 15 starter players.",
    )
    captain_player_id: UUID = Field(
        ...,
        description="Player designated as captain. Must be in starters.",
    )
    kicker_player_id: UUID = Field(
        ...,
        description="Player designated as kicker. Must be in starters.",
    )

    @model_validator(mode="after")
    def captain_and_kicker_must_be_starters(self) -> "LineupSubmission":
        """Ensure captain and kicker are in the starter list."""
        starter_ids = {s.player_id for s in self.starters}
        if self.captain_player_id not in starter_ids:
            raise ValueError("Captain must be in the starter list.")
        if self.kicker_player_id not in starter_ids:
            raise ValueError("Kicker must be in the starter list.")
        return self


class CaptainUpdate(BaseModel):
    """Request body for changing the captain designation.

    Lock rule (enforced by service):
    - Blocked if the current captain's team has already kicked off.
    - Blocked if the new captain's team has already kicked off.
    """

    player_id: UUID = Field(..., description="Player to designate as new captain.")


class KickerUpdate(BaseModel):
    """Request body for changing the kicker designation.

    Lock rule (enforced by service):
    - Blocked once the current kicker's team has kicked off.
    - Cannot be changed until next round.
    """

    player_id: UUID = Field(..., description="Player to designate as new kicker.")


class LineupPlayer(BaseModel):
    """A single player as returned in a lineup response.

    `is_locked` is True if the player's team kick_off_time < NOW().
    `locked_at` is the actual kick_off_time stored at lock time (None if not yet locked).
    """

    player_id: UUID
    player_name: str
    club: str
    position: str
    is_captain: bool
    is_kicker: bool
    is_locked: bool
    locked_at: datetime | None = None


class LineupResponse(BaseModel):
    """Full lineup for a given round as returned by the API.

    `is_fully_locked` is True when all 15 starters are locked
    (i.e. all their teams have kicked off). At that point no changes are possible.
    """

    roster_id: UUID
    round_id: UUID
    round_number: int
    starters: list[LineupPlayer]
    bench: list[LineupPlayer]
    captain_player_id: UUID | None = None
    kicker_player_id: UUID | None = None
    is_fully_locked: bool = Field(
        default=False,
        description="True when all starters' teams have kicked off.",
    )

    @model_validator(mode="after")
    def compute_fully_locked(self) -> "LineupResponse":
        """Set is_fully_locked if all starters are locked."""
        if self.starters:
            self.is_fully_locked = all(p.is_locked for p in self.starters)
        return self
