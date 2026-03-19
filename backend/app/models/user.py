# backend/app/models/user.py
"""
Pydantic schemas for the User entity.

These are request/response validation schemas — not ORM models.
They mirror the `users` table defined in db/migrations/001_initial_schema.sql.

Naming convention:
    UserBase    — shared fields (no id, no timestamps)
    UserCreate  — fields required to create a user (POST)
    UserRead    — full user representation returned by the API (GET)
    UserUpdate  — fields that can be updated (PATCH — all optional)
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class UserBase(BaseModel):
    """Fields shared across all User schemas."""

    display_name: str = Field(
        ...,
        min_length=2,
        max_length=50,
        description="Public display name shown in leagues and leaderboards.",
    )
    locale: str = Field(
        default="fr",
        pattern=r"^[a-z]{2}$",
        description="UI locale preference (ISO 639-1 code). Default: 'fr'.",
    )
    avatar_url: str | None = Field(
        default=None,
        description="URL to user avatar image. Optional.",
    )


class UserCreate(UserBase):
    """
    Schema for creating a new user profile.

    The supabase_id comes from the verified JWT — never from the request body.
    plan is always 'free' at creation — upgraded via Stripe webhook.
    """

    supabase_id: UUID = Field(
        ...,
        description="UUID from Supabase Auth. Extracted from JWT, not user input.",
    )


class UserRead(UserBase):
    """
    Full user representation returned by the API.

    Excludes supabase_id — internal identifier, never exposed to clients.
    """

    id: UUID
    plan: str = Field(
        description="Subscription plan: 'free' | 'pro' | 'pro_ia'.",
    )
    ai_league_id: UUID | None = Field(
        default=None,
        description="League where AI staff reports are active (Pro+IA only).",
    )
    created_at: datetime
    updated_at: datetime

    # Enable ORM mode — allows creating UserRead from SQLAlchemy/asyncpg objects
    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    """
    Fields that can be updated via PATCH /users/{id}.

    All fields are optional — only provided fields are updated.
    plan and supabase_id cannot be updated via the API.
    """

    display_name: str | None = Field(
        default=None,
        min_length=2,
        max_length=50,
    )
    locale: str | None = Field(
        default=None,
        pattern=r"^[a-z]{2}$",
    )
    avatar_url: str | None = Field(default=None)
    ai_league_id: UUID | None = Field(default=None)
