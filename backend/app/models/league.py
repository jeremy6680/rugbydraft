# backend/app/models/league.py
"""
Pydantic schemas for the League entity.

A league is a fantasy rugby competition between 2-N managers,
using a snake draft system to build rosters.

These schemas mirror the `leagues` and related tables defined
in db/migrations/001_initial_schema.sql.

Key rules from the CDC:
    - competition_type determines draft eligibility constraints
    - League status follows a strict lifecycle: pending → drafting → active → completed
    - Draft mode: snake (real-time timer) or assisted (commissioner enters picks)
    - Manager count limits depend on competition (e.g. Six Nations: 2-6 managers)
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class CompetitionType(StrEnum):
    """
    Type of rugby competition — determines roster composition constraints.

    international:
        Managers can draft players of any nationality freely.
        Constraint: maximum 8 players from the same nation per roster.
        Example: Six Nations (30-player roster across 6 nations),
                 Rugby Championship.

    club:
        Managers can draft players from any club freely.
        Constraint: maximum 6 players from the same club per roster.
        Example: Top 14, Premiership, Champions Cup.
    """

    INTERNATIONAL = "international"
    CLUB = "club"


class LeagueStatus(StrEnum):
    """
    League lifecycle status — mirrors the league_status enum in PostgreSQL.

    pending    — league created, waiting for managers to join
    drafting   — snake draft in progress (FastAPI authority of state)
    active     — draft complete, season in progress
    completed  — season ended, league archived
    """

    PENDING = "pending"
    DRAFTING = "drafting"
    ACTIVE = "active"
    COMPLETED = "completed"


class DraftMode(StrEnum):
    """
    Draft mode — determines how picks are made.

    snake:
        Real-time snake draft with server-side timer.
        Each manager picks within their time window.
        Autodraft activates on timeout.

    assisted:
        Commissioner enters picks manually, no timer.
        Used as fallback when managers cannot be simultaneously connected.
        All picks are stamped with timestamp + "entered by commissioner".
    """

    SNAKE = "snake"
    ASSISTED = "assisted"


class PlanRequired(StrEnum):
    """
    Minimum subscription plan required to join or create a league.

    free    — international competitions (Six Nations, Rugby Championship)
    pro     — club competitions (Top 14, Premiership, Super Rugby)
    """

    FREE = "free"
    PRO = "pro"


class LeagueBase(BaseModel):
    """Fields shared across all League schemas."""

    name: str = Field(
        ...,
        min_length=3,
        max_length=100,
        description="League name chosen by the commissioner.",
    )
    competition_id: UUID = Field(
        ...,
        description="Reference to the competition (Six Nations, Top 14, etc.).",
    )
    draft_mode: DraftMode = Field(
        default=DraftMode.SNAKE,
        description="Snake (real-time timer) or Assisted (commissioner enters picks).",
    )
    pick_time_seconds: int = Field(
        default=60,
        ge=30,
        le=300,
        description=(
            "Seconds per pick in snake draft mode. CDC default: 60s. Range: 30–300s."
        ),
    )
    max_managers: int = Field(
        ...,
        ge=2,
        le=12,
        description=(
            "Maximum number of managers. "
            "Must respect competition limits (e.g. Six Nations: 2–6)."
        ),
    )


class LeagueCreate(LeagueBase):
    """
    Schema for creating a new league.

    commissioner_id is extracted from the JWT — not from the request body.
    status always starts as 'pending' — set server-side, not by the client.
    plan_required is derived from the competition — not set by the client.
    """

    commissioner_id: UUID = Field(
        ...,
        description="User ID of the commissioner. Extracted from JWT.",
    )


class LeagueRead(LeagueBase):
    """
    Full league representation returned by the API.

    Includes lifecycle status, manager count, and plan requirement.
    """

    id: UUID
    commissioner_id: UUID
    status: LeagueStatus
    plan_required: PlanRequired
    current_managers: int = Field(
        default=0,
        description="Number of managers currently joined.",
    )
    draft_started_at: datetime | None = None
    draft_completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LeagueUpdate(BaseModel):
    """
    Fields that can be updated by the commissioner before the draft starts.

    Once status transitions to 'drafting', most fields are locked.
    Status transitions are managed by the draft engine — not via this schema.
    """

    name: str | None = Field(default=None, min_length=3, max_length=100)
    draft_mode: DraftMode | None = Field(default=None)
    pick_time_seconds: int | None = Field(default=None, ge=30, le=300)
    max_managers: int | None = Field(default=None, ge=2, le=12)


class LeagueSummary(BaseModel):
    """
    Lightweight league representation for dashboard and list endpoints.

    Shows essential info without full detail — used when a user
    views all their active leagues on the dashboard.
    """

    id: UUID
    name: str
    status: LeagueStatus
    draft_mode: DraftMode
    current_managers: int
    max_managers: int
    plan_required: PlanRequired

    model_config = {"from_attributes": True}


class ManagerInLeague(BaseModel):
    """
    Represents a manager's membership in a league.

    Mirrors the `league_managers` join table.
    Used in LeagueRead to list all managers in a league.
    """

    user_id: UUID
    display_name: str
    joined_at: datetime
    draft_position: int | None = Field(
        default=None,
        description=(
            "Manager's position in the snake draft order. "
            "Assigned when draft starts — null until then."
        ),
    )

    model_config = {"from_attributes": True}
