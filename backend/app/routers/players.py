# backend/app/routers/players.py
"""
Players router — endpoints for the player pool.

Endpoints:
    GET /players  — list all players (optionally filtered by league)

Used by:
    - Draft Room page (server-side fetch of full player pool)
    - Stats page (browsing all players)

Phase 4 scope: returns all players from the database.
Future: filter by competition_id derived from league settings.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from supabase import AsyncClient

from app.dependencies import get_supabase_client
from app.models.player import PlayerSummary

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/players",
    tags=["players"],
)


@router.get(
    "",
    response_model=list[PlayerSummary],
    status_code=status.HTTP_200_OK,
    summary="List all players in the pool",
    description=(
        "Returns all players available for drafting. "
        "Ordered by last_name ascending. "
        "Future: filter by competition_id via league_id parameter."
    ),
)
async def list_players(
    request: Request,
    league_id: str | None = Query(
        default=None,
        description="Optional league UUID. Reserved for future filtering.",
    ),
    supabase: AsyncClient = Depends(get_supabase_client),
) -> list[PlayerSummary]:
    """Return all players with their current availability status.

    Args:
        request: FastAPI request (auth state set by middleware).
        league_id: Optional — reserved for future competition filtering.
        supabase: Injected Supabase async client.

    Returns:
        List of PlayerSummary objects ordered by last_name.

    Raises:
        HTTPException 401: If not authenticated.
        HTTPException 500: If the database query fails.
    """
    # Auth check — middleware sets user_id, we just verify it's present.
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    try:
        # Fetch players with their positions via join.
        # player_positions is a junction table: player_id, position_type.
        response = (
            await supabase.table("players")
            .select(
                "id, first_name, last_name, nationality, club, "
                "availability_status, "
                "player_positions(position_type)"
            )
            .order("last_name", desc=False)
            .execute()
        )
    except Exception as exc:
        logger.error("Failed to fetch players: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch player pool.",
        ) from exc

    # Map raw rows to PlayerSummary.
    # player_positions is a list of dicts: [{"position_type": "prop"}, ...]
    players: list[PlayerSummary] = []
    for row in response.data:
        positions = [p["position_type"] for p in (row.get("player_positions") or [])]
        if not positions:
            # Skip players with no positions — data integrity issue.
            logger.warning("Player %s has no positions — skipping from pool", row["id"])
            continue

        players.append(
            PlayerSummary(
                id=row["id"],
                first_name=row["first_name"],
                last_name=row["last_name"],
                nationality=row["nationality"],
                club=row["club"],
                positions=positions,
                availability_status=row["availability_status"],
            )
        )

    logger.info("list_players: returning %d players", len(players))
    return players
