# backend/app/routers/stats.py
"""Stats router — player statistics endpoints.

Powers the Stats page (CDC section 12, D-039).

Endpoints:
    GET /stats/players — aggregated player stats for a competition + period.

Data source: mart_player_stats_ui (gold dbt model, materialized as a
PostgreSQL table via export_silver_to_pg.py + dbt prod target).

Design notes:
    - Filtering by position/club/availability is intentionally left to the
      frontend (D-044). This endpoint returns all players for the requested
      (competition_id, period) pair.
    - If league_id is provided, each player row is enriched with a
      pool_status field ('mine' | 'drafted' | 'free') derived from the
      roster_players table.
    - Fantasy points columns use raw_points (no captain multiplier) — the
      stats page is global, captain designation is roster-specific.
"""

from __future__ import annotations

import logging
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.dependencies import get_current_user_id, get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stats", tags=["stats"])

# Valid period values — mirrors the 'period' column in mart_player_stats_ui.
PeriodType = Literal["1w", "2w", "4w", "season"]

# Valid pool status values returned to the frontend.
PoolStatusType = Literal["mine", "drafted", "free"]


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class PlayerStatsRow(BaseModel):
    """Aggregated stats for a single player over a given period.

    All counting stats are totals over the period (not per-match averages),
    except avg_points which is the mean fantasy score per round played.

    Kicker stats (conversions_made, penalties_made) are raw totals — not
    filtered by is_kicker. The frontend decides how to display them.
    """

    player_id: UUID
    competition_id: UUID
    period: PeriodType
    player_name: str
    position_type: str
    nationality: str | None
    club: str | None
    availability_status: str
    pool_status: PoolStatusType = Field(
        default="free",
        description="'mine' = on current user's roster, "
        "'drafted' = on another roster, "
        "'free' = available in waiver pool. "
        "Only meaningful when league_id is provided.",
    )
    rounds_played: int

    # Fantasy points
    total_points: float
    avg_points: float

    # Attack (D-039)
    tries: int
    try_assists: int
    metres_carried: int
    kick_assists: int
    line_breaks: int
    catch_from_kick: int
    conversions_made: int
    penalties_made: int

    # Defence (D-039)
    tackles: int
    turnovers_won: int
    lineouts_won: int
    lineouts_lost: int
    turnovers_conceded: int
    missed_tackles: int
    handling_errors: int
    penalties_conceded: int
    yellow_cards: int
    red_cards: int

    # Trend vs previous equivalent period
    trend: Literal["up", "down", "stable"]


class PlayerStatsResponse(BaseModel):
    """Full response for GET /stats/players."""

    competition_id: UUID
    period: PeriodType
    players: list[PlayerStatsRow]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_roster_player_ids(
    league_id: UUID,
    user_id: str,
    supabase,
) -> tuple[set[str], set[str]]:
    """Return two sets of player UUIDs for pool_status enrichment.

    Queries roster_players for all rosters in the given league to
    determine which players are drafted and which belong to the
    current user's roster.

    Args:
        league_id: UUID of the target league.
        user_id: Authenticated user's UUID string.
        supabase: Supabase client instance.

    Returns:
        Tuple of (my_player_ids, all_drafted_ids) where:
            my_player_ids    — UUIDs of players on the current user's roster
            all_drafted_ids  — UUIDs of ALL drafted players in the league
                               (includes my_player_ids)

    Raises:
        HTTPException 500 on database error.
    """
    try:
        # Fetch all rosters in the league with their owner user_id.
        rosters_result = await (
            supabase.table("rosters")
            .select("id, user_id")
            .eq("league_id", str(league_id))
            .execute()
        )
    except Exception as exc:
        logger.error("DB error fetching rosters for league %s: %s", league_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error while fetching roster data.",
        ) from exc

    rosters = rosters_result.data or []
    if not rosters:
        return set(), set()

    roster_ids = [r["id"] for r in rosters]
    # Identify current user's roster (may be None if user has no roster yet)
    my_roster_id: str | None = next(
        (r["id"] for r in rosters if r["user_id"] == user_id), None
    )

    try:
        # Fetch all player assignments across all rosters in the league.
        rp_result = await (
            supabase.table("roster_slots")
            .select("roster_id, player_id")
            .in_("roster_id", roster_ids)
            .execute()
        )
    except Exception as exc:
        logger.error("DB error fetching roster_slots for league %s: %s", league_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error while fetching roster players.",
        ) from exc

    assignments = rp_result.data or []
    my_player_ids: set[str] = set()
    all_drafted_ids: set[str] = set()

    for assignment in assignments:
        pid = assignment["player_id"]
        all_drafted_ids.add(pid)
        if my_roster_id and assignment["roster_id"] == my_roster_id:
            my_player_ids.add(pid)

    return my_player_ids, all_drafted_ids


def _resolve_pool_status(
    player_id: str,
    my_player_ids: set[str],
    all_drafted_ids: set[str],
) -> PoolStatusType:
    """Determine pool_status for a single player.

    Args:
        player_id: UUID string of the player.
        my_player_ids: UUIDs on the current user's roster.
        all_drafted_ids: UUIDs of all drafted players in the league.

    Returns:
        'mine' | 'drafted' | 'free'
    """
    if player_id in my_player_ids:
        return "mine"
    if player_id in all_drafted_ids:
        return "drafted"
    return "free"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/players",
    response_model=PlayerStatsResponse,
    summary="Get aggregated player statistics",
    description=(
        "Returns pre-aggregated player stats for the given competition and "
        "period. Stats source: mart_player_stats_ui (gold dbt model). "
        "Ordered by avg_points descending. "
        "Position/club/availability filtering is done client-side."
        "Providing league_id enriches each player with pool_status "
        "('mine' | 'drafted' | 'free')."
    ),
)
async def get_player_stats(
    competition_id: UUID = Query(
        ...,
        description="UUID of the competition to fetch stats for.",
    ),
    period: PeriodType = Query(
        default="season",
        description="Aggregation period: 1w | 2w | 4w | season.",
    ),
    league_id: UUID | None = Query(
        default=None,
        description=(
            "Optional. When provided, enriches each player row with "
            "pool_status ('mine' | 'drafted' | 'free') for the given league."
        ),
    ),
    user_id: str = Depends(get_current_user_id),
    supabase=Depends(get_supabase_client),
) -> PlayerStatsResponse:
    """Return aggregated player stats for a competition + period.

    Queries mart_player_stats_ui directly (gold dbt table in PostgreSQL).
    Optionally enriches with pool_status if league_id is provided.

    Args:
        competition_id: UUID of the competition (query param).
        period: One of '1w' | '2w' | '4w' | 'season' (query param).
        league_id: Optional league UUID for pool_status enrichment.
        user_id: Injected by JWT middleware.
        supabase: Injected Supabase client.

    Returns:
        PlayerStatsResponse with all players ordered by avg_points desc.

    Raises:
        HTTPException 404: No stats found for this competition/period.
        HTTPException 500: Database error.
    """
    # Step 1: fetch stats rows from mart_player_stats_ui.
    try:
        result = await (
            supabase.table("mart_player_stats_ui")
            .select("*")
            .eq("competition_id", str(competition_id))
            .eq("period", period)
            .order("avg_points", desc=True)
            .execute()
        )
    except Exception as exc:
        logger.error(
            "DB error fetching stats for competition %s period %s: %s",
            competition_id,
            period,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error while fetching player statistics.",
        ) from exc

    rows = result.data or []

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No statistics found for competition {competition_id} "
                f"and period '{period}'. "
                "The pipeline may not have run yet for this competition."
            ),
        )

    # Step 2: resolve pool_status if league_id provided.
    my_player_ids: set[str] = set()
    all_drafted_ids: set[str] = set()

    if league_id is not None:
        my_player_ids, all_drafted_ids = await _get_roster_player_ids(
            league_id, user_id, supabase
        )

    # Step 3: map rows to PlayerStatsRow.
    players: list[PlayerStatsRow] = []
    for row in rows:
        pid = row["player_id"]
        players.append(
            PlayerStatsRow(
                player_id=UUID(pid),
                competition_id=UUID(row["competition_id"]),
                period=row["period"],
                player_name=row["player_name"],
                position_type=row["position_type"],
                nationality=row.get("nationality"),
                club=row.get("club"),
                availability_status=row["availability_status"],
                pool_status=_resolve_pool_status(pid, my_player_ids, all_drafted_ids),
                rounds_played=int(row["rounds_played"]),
                total_points=float(row["total_points"]),
                avg_points=float(row["avg_points"]),
                tries=int(row["tries"]),
                try_assists=int(row["try_assists"]),
                metres_carried=int(row["metres_carried"]),
                kick_assists=int(row["kick_assists"]),
                line_breaks=int(row["line_breaks"]),
                catch_from_kick=int(row["catch_from_kick"]),
                conversions_made=int(row["conversions_made"]),
                penalties_made=int(row["penalties_made"]),
                tackles=int(row["tackles"]),
                turnovers_won=int(row["turnovers_won"]),
                lineouts_won=int(row["lineouts_won"]),
                lineouts_lost=int(row["lineouts_lost"]),
                turnovers_conceded=int(row["turnovers_conceded"]),
                missed_tackles=int(row["missed_tackles"]),
                handling_errors=int(row["handling_errors"]),
                penalties_conceded=int(row["penalties_conceded"]),
                yellow_cards=int(row["yellow_cards"]),
                red_cards=int(row["red_cards"]),
                trend=row["trend"],
            )
        )

    logger.info(
        "get_player_stats: competition=%s period=%s → %d players",
        competition_id,
        period,
        len(players),
    )

    return PlayerStatsResponse(
        competition_id=competition_id,
        period=period,
        players=players,
    )
