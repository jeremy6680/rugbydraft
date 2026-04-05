# backend/app/routers/leagues.py

"""League router — league-level endpoints.

Provides standings and future league management endpoints.
All routes are protected by JWT middleware (global opt-out model).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.dependencies import get_current_user_id, get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/leagues", tags=["leagues"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class StandingEntry(BaseModel):
    """A single manager's standing in a league."""

    rank: int
    member_id: UUID
    display_name: str
    wins: int
    losses: int
    total_points: float


class LeagueStandingsResponse(BaseModel):
    """Full standings for a league, ordered by rank ascending."""

    league_id: UUID
    standings: List[StandingEntry]
    updated_at: datetime | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _assert_league_member(
    league_id: UUID,
    user_id: str,
    supabase,
) -> None:
    """Raise 403 if the current user is not a member of the league.

    Args:
        league_id: The league to check membership for.
        user_id: The authenticated user's UUID (string).
        supabase: Supabase client instance.

    Raises:
        HTTPException: 403 if the user is not a member of the league.
        HTTPException: 500 on unexpected database error.
    """
    try:
        result = await (
            supabase.table("league_members")
            .select("id")
            .eq("league_id", str(league_id))
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
    except Exception as exc:
        logger.error("DB error checking league membership: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error while checking league membership.",
        ) from exc

    if result.data is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this league.",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/{league_id}/standings",
    response_model=LeagueStandingsResponse,
    summary="Get league standings",
    description=(
        "Returns the current standings for a league, ordered by rank. "
        "Requires the caller to be a member of the league."
    ),
)
async def get_league_standings(
    league_id: UUID,
    user_id: str = Depends(get_current_user_id),
    supabase=Depends(get_supabase_client),
) -> LeagueStandingsResponse:
    """Return standings for the given league.

    Membership is checked explicitly before querying standings.
    standings are joined with users to resolve display names.

    Args:
        league_id: UUID of the target league (path parameter).
        user_id: Injected by JWT middleware via get_current_user_id.
        supabase: Injected Supabase client.

    Returns:
        LeagueStandingsResponse with standings ordered by rank ascending.

    Raises:
        HTTPException: 403 if the caller is not a league member.
        HTTPException: 404 if no standings exist yet for this league.
        HTTPException: 500 on database error.
    """
    # Guard: caller must be a league member
    await _assert_league_member(league_id, user_id, supabase)

    # Fetch standings joined with user display names
    try:
        result = await (
            supabase.table("league_standings")
            .select(
                "rank, member_id, wins, losses, total_points, updated_at, "
                "users!member_id(display_name)"
            )
            .eq("league_id", str(league_id))
            .order("rank", desc=False)
            .execute()
        )
    except Exception as exc:
        logger.error("DB error fetching standings for league %s: %s", league_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error while fetching standings.",
        ) from exc

    rows = result.data or []

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No standings found for this league. "
            "The draft may not have started yet.",
        )

    # Resolve updated_at: take the most recent timestamp across all rows
    # (standings are updated atomically by the pipeline, so they should
    # all share the same timestamp — but we take max() defensively)
    updated_at: datetime | None = None
    for row in rows:
        if row.get("updated_at"):
            row_ts = datetime.fromisoformat(row["updated_at"])
            if updated_at is None or row_ts > updated_at:
                updated_at = row_ts

    standings = [
        StandingEntry(
            rank=row["rank"],
            member_id=UUID(row["member_id"]),
            # Supabase join returns nested object: users!member_id
            display_name=row.get("users", {}).get("display_name", "Unknown"),
            wins=row["wins"],
            losses=row["losses"],
            total_points=float(row["total_points"]),
        )
        for row in rows
    ]

    return LeagueStandingsResponse(
        league_id=league_id,
        standings=standings,
        updated_at=updated_at,
    )
