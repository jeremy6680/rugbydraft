# backend/app/routers/dashboard.py

"""Dashboard router — user dashboard endpoint.

Returns all active leagues for the authenticated user,
enriched with standings, last round score, and alerts.

CDC reference: §5.2 — Dashboard personnel.

Design: single BFF-style endpoint aggregating all per-league data to avoid
N+1 round trips from the frontend. Sequential Supabase queries in V1
(asyncio.gather deferred until profiling confirms benefit — Supabase Python
SDK is synchronous under the hood so true parallelism is not guaranteed).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.dependencies import get_current_user_id, get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

AlertType = Literal[
    "player_injured",
    "player_recovered",
    "waiver_open",
    "trade_proposed",
    "ai_report_ready",
]


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class DashboardAlert(BaseModel):
    """A single alert surfaced on the dashboard card for a league."""

    alert_type: AlertType
    detail: str | None = None
    created_at: str | None = None


class DashboardLeague(BaseModel):
    """Summary of one active league for the dashboard card."""

    league_id: UUID
    league_name: str
    competition_name: str
    competition_id: UUID
    current_rank: int | None = None
    total_managers: int
    last_round_number: int | None = None
    last_round_points: float | None = None
    next_opponent: str | None = None
    draft_id: UUID | None = None
    draft_status: Literal["pending", "active"] | None = None
    league_status: Literal["upcoming", "drafting", "active", "completed"]
    is_commissioner: bool
    alerts: list[DashboardAlert]


class DashboardResponse(BaseModel):
    """Full dashboard response for the authenticated user."""

    user_id: UUID
    leagues: list[DashboardLeague]
    fetched_at: str


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _fetch_user_leagues(user_id: str, supabase) -> list[dict]:
    """Fetch all non-archived leagues for the user with competition info.

    Note: filtering on joined table columns (leagues.status) is not supported
    by the PostgREST SDK — the archived filter is applied in Python after fetch.
    """
    try:
        result = await (
            supabase.table("league_members")
            .select(
                "league_id,"
                "leagues!inner(id,name,is_archived,commissioner_id,competition_id,"
                "competitions!inner(id,name))"
            )
            .eq("user_id", user_id)
            .execute()
        )

    except Exception as exc:
        logger.error("DB error fetching leagues for user %s: %s", user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error while fetching user leagues.",
        ) from exc

    # Filter out archived leagues in Python — PostgREST does not support
    # .neq() filtering on columns of joined (embedded) tables.
    rows = result.data or []
    return [row for row in rows if not row.get("leagues", {}).get("is_archived", False)]


async def _fetch_standings_bulk(
    league_ids: list[str], supabase
) -> dict[str, list[dict]]:
    """Fetch standings for multiple leagues in a single query."""
    if not league_ids:
        return {}
    try:
        result = await (
            supabase.table("league_standings")
            .select("league_id,member_id,rank,total_points,wins,losses")
            .in_("league_id", league_ids)
            .execute()
        )
    except Exception as exc:
        logger.warning("Could not fetch standings (non-fatal): %s", exc)
        return {}

    standings: dict[str, list[dict]] = {}
    for row in result.data or []:
        standings.setdefault(row["league_id"], []).append(row)
    return standings


async def _fetch_last_round_scores(
    league_ids: list[str], user_id: str, supabase
) -> dict[str, tuple[int, float]]:
    """Fetch the most recently completed round score per league for the user."""
    if not league_ids:
        return {}
    try:
        result = await (
            supabase.table("fantasy_scores")
            .select("league_id,points,competition_rounds!inner(round_number)")
            .in_("league_id", league_ids)
            .eq("user_id", user_id)
            .order("competition_rounds.round_number", desc=True)
            .execute()
        )
    except Exception as exc:
        logger.warning("Could not fetch last round scores (non-fatal): %s", exc)
        return {}

    scores: dict[str, tuple[int, float]] = {}
    for row in result.data or []:
        lid = row["league_id"]
        if lid in scores:
            continue
        rounds = row.get("competition_rounds", {})
        rn = rounds.get("round_number") if isinstance(rounds, dict) else None
        if rn is not None:
            scores[lid] = (int(rn), float(row["points"]))
    return scores


async def _fetch_alerts(
    league_ids: list[str], user_id: str, supabase
) -> dict[str, list[DashboardAlert]]:
    """Aggregate active alerts for the user across all their leagues."""
    alerts: dict[str, list[DashboardAlert]] = {lid: [] for lid in league_ids}

    # --- 1. Injured / recovered players on the user's roster ---
    try:
        rosters_result = await (
            supabase.table("rosters")
            .select("id,league_id")
            .in_("league_id", league_ids)
            .eq("user_id", user_id)
            .execute()
        )
        my_rosters: dict[str, str] = {
            r["id"]: r["league_id"] for r in (rosters_result.data or [])
        }

        if my_rosters:
            rp_result = await (
                supabase.table("roster_players")
                .select(
                    "roster_id,players!inner(name,player_availability!inner(status))"
                )
                .in_("roster_id", list(my_rosters.keys()))
                .in_(
                    "players.player_availability.status",
                    ["injured", "suspended", "recovered"],
                )
                .execute()
            )
            for row in rp_result.data or []:
                lid = my_rosters.get(row["roster_id"])
                if not lid:
                    continue
                player = row.get("players", {})
                pa = player.get("player_availability", {})
                if not isinstance(pa, dict):
                    continue
                pa_status = pa.get("status")
                player_name = player.get("name", "")
                if pa_status in ("injured", "suspended"):
                    alerts[lid].append(
                        DashboardAlert(alert_type="player_injured", detail=player_name)
                    )
                elif pa_status == "recovered":
                    alerts[lid].append(
                        DashboardAlert(
                            alert_type="player_recovered", detail=player_name
                        )
                    )
    except Exception as exc:
        logger.warning("Could not fetch injury alerts (non-fatal): %s", exc)

    # --- 2. Waiver window open ---
    try:
        from waivers.window import is_waiver_window_open

        if is_waiver_window_open():
            for lid in league_ids:
                alerts[lid].append(DashboardAlert(alert_type="waiver_open"))
    except Exception as exc:
        logger.warning("Could not check waiver window (non-fatal): %s", exc)

    # --- 3. Pending trade proposals targeting this user ---
    try:
        trades_result = await (
            supabase.table("trades")
            .select("league_id,proposed_at")
            .in_("league_id", league_ids)
            .eq("receiver_user_id", user_id)
            .eq("status", "pending")
            .execute()
        )
        for row in trades_result.data or []:
            lid = row["league_id"]
            if lid in alerts:
                alerts[lid].append(
                    DashboardAlert(
                        alert_type="trade_proposed",
                        created_at=row.get("proposed_at"),
                    )
                )
    except Exception as exc:
        logger.warning("Could not fetch trade alerts (non-fatal): %s", exc)

    return alerts


async def _fetch_active_drafts(league_ids: list[str], supabase) -> dict[str, dict]:
    """Fetch pending or active draft info for the given leagues."""
    if not league_ids:
        return {}
    try:
        result = await (
            supabase.table("drafts")
            .select("id,league_id,status")
            .in_("league_id", league_ids)
            .in_("status", ["pending", "active"])
            .execute()
        )
    except Exception as exc:
        logger.warning("Could not fetch draft data (non-fatal): %s", exc)
        return {}

    return {
        row["league_id"]: {"draft_id": row["id"], "status": row["status"]}
        for row in (result.data or [])
    }


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=DashboardResponse,
    summary="Get user dashboard",
    description=(
        "Returns all active leagues for the authenticated user, enriched with "
        "current rank, last round score, and alerts (injuries, waivers, trades). "
        "Returns an empty leagues list if the user has no active leagues. "
        "CDC §5.2: Dashboard personnel."
    ),
)
async def get_dashboard(
    user_id: UUID = Depends(get_current_user_id),
    supabase=Depends(get_supabase_client),
) -> DashboardResponse:
    """Aggregate dashboard data for the authenticated user."""
    user_id_str = str(user_id)

    member_rows = await _fetch_user_leagues(user_id_str, supabase)

    if not member_rows:
        return DashboardResponse(
            user_id=user_id,
            leagues=[],
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    league_ids: list[str] = [row["league_id"] for row in member_rows]

    standings_map = await _fetch_standings_bulk(league_ids, supabase)
    last_scores_map = await _fetch_last_round_scores(league_ids, user_id_str, supabase)
    alerts_map = await _fetch_alerts(league_ids, user_id_str, supabase)
    drafts_map = await _fetch_active_drafts(league_ids, supabase)

    leagues: list[DashboardLeague] = []

    for row in member_rows:
        lid = row["league_id"]
        league_data: dict = row.get("leagues", {})
        competition_data: dict = league_data.get("competitions", {})

        league_standings = standings_map.get(lid, [])
        total_managers = len(league_standings)
        my_standing = next(
            (s for s in league_standings if s.get("member_id") == user_id_str), None
        )
        current_rank = int(my_standing["rank"]) if my_standing else None

        last_score = last_scores_map.get(lid)
        last_round_number = last_score[0] if last_score else None
        last_round_points = last_score[1] if last_score else None

        draft_info = drafts_map.get(lid, {})
        raw_draft_id = draft_info.get("draft_id")
        raw_draft_status = draft_info.get("status")

        competition_id_str: str = competition_data.get(
            "id", "00000000-0000-0000-0000-000000000000"
        )

        # league_status derived from draft_info since leagues table has no status column.
        # is_archived is excluded above, so any remaining league is active or upcoming.
        if draft_info.get("status") == "active":
            league_status = "drafting"
        elif draft_info.get("status") == "pending":
            league_status = "upcoming"
        else:
            league_status = "active"  # Default: league exists, draft complete

        leagues.append(
            DashboardLeague(
                league_id=UUID(lid),
                league_name=league_data.get("name", ""),
                competition_name=competition_data.get("name", ""),
                competition_id=UUID(competition_id_str),
                current_rank=current_rank,
                total_managers=total_managers,
                last_round_number=last_round_number,
                last_round_points=last_round_points,
                next_opponent=None,  # TODO: Phase 4 follow-up
                draft_id=UUID(raw_draft_id) if raw_draft_id else None,
                draft_status=raw_draft_status,
                league_status=league_status,
                is_commissioner=(league_data.get("commissioner_id") == user_id_str),
                alerts=alerts_map.get(lid, []),
            )
        )

    logger.info(
        "get_dashboard: user=%s → %d active league(s)", user_id_str, len(leagues)
    )

    return DashboardResponse(
        user_id=user_id,
        leagues=leagues,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )
