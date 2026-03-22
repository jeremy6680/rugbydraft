"""
Infirmary router — FastAPI endpoints for IR slot management.

Endpoints:
    PUT  /ir/place/{roster_id}/{player_id}       — place a player in IR
    PUT  /ir/reintegrate/{roster_id}/{player_id} — reintegrate a recovered player
    GET  /ir/alerts/{league_id}                  — list overdue IR slots for a league

All state mutations go through ir_rules.py (pure validation) before any DB write.
The router owns all I/O — ir_rules.py stays pure and testable.

Auth: all endpoints require a valid JWT (global middleware).
Authorization: only the roster owner can place/reintegrate players.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import AsyncClient

from app.dependencies import get_current_user_id, get_supabase_client
from infirmary.ir_rules import (
    MAX_IR_SLOTS,
    IRError,
    IRSlotSnapshot,
    get_overdue_ir_slots,
    validate_ir_placement,
    validate_ir_reintegration,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ir", tags=["infirmary"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_roster_owner(
    roster_id: str,
    supabase: AsyncClient,
) -> str:
    """Return the user_id that owns a roster.

    Args:
        roster_id: UUID of the roster.
        supabase: Async Supabase client.

    Returns:
        user_id string.

    Raises:
        HTTPException 404: If roster does not exist.
    """
    response = (
        await supabase.table("rosters")
        .select("user_id")
        .eq("id", roster_id)
        .single()
        .execute()
    )
    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "roster_not_found", "roster_id": roster_id},
        )
    return response.data["user_id"]


async def _build_ir_snapshot(
    roster_id: str,
    supabase: AsyncClient,
) -> IRSlotSnapshot:
    """Build an IRSlotSnapshot from the current DB state.

    Fetches all IR slots for the roster and cross-references with
    pipeline_stg_player_availability to identify recovered players.

    Args:
        roster_id: UUID of the roster.
        supabase: Async Supabase client.

    Returns:
        IRSlotSnapshot with current_ir_player_ids and recovered_player_ids.
    """
    # Fetch active IR slots for this roster
    ir_response = (
        await supabase.table("weekly_lineups")
        .select("player_id")
        .eq("roster_id", roster_id)
        .eq("slot_type", "ir")
        .execute()
    )
    ir_player_ids: set[str] = {row["player_id"] for row in (ir_response.data or [])}

    # Cross-reference with pipeline availability to find recovered players
    recovered_ids: set[str] = set()
    if ir_player_ids:
        avail_response = (
            await supabase.table("pipeline_stg_player_availability")
            .select("player_id, status")
            .in_("player_id", list(ir_player_ids))
            .execute()
        )
        recovered_ids = {
            row["player_id"]
            for row in (avail_response.data or [])
            if row["status"] == "available"
        }

    return IRSlotSnapshot(
        roster_id=roster_id,
        current_ir_player_ids=ir_player_ids,
        recovered_player_ids=recovered_ids,
    )


def _map_ir_error_to_http(error: IRError) -> HTTPException:
    """Map a typed IRError to the appropriate HTTPException.

    Uses the .code attribute as the machine-readable error key —
    the frontend maps this to messages/fr.json for display.

    Args:
        error: Any IRError subclass.

    Returns:
        HTTPException with status 422 and error code in detail.
    """
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": error.code, "message": error.message},
    )


# ---------------------------------------------------------------------------
# PUT /ir/place/{roster_id}/{player_id}
# ---------------------------------------------------------------------------


@router.put(
    "/place/{roster_id}/{player_id}",
    status_code=status.HTTP_200_OK,
    summary="Place a player in the IR slot",
    response_description="Player successfully placed in IR.",
)
async def place_player_in_ir(
    roster_id: str,
    player_id: str,
    current_user_id: str = Depends(get_current_user_id),
    supabase: AsyncClient = Depends(get_supabase_client),
) -> dict:
    """Place an injured or suspended player in the IR slot.

    The player must be currently on the roster (not free agent).
    The player must have status 'injured' or 'suspended' in the pipeline.
    IR capacity must not be exceeded (max 3 slots).

    A player in IR:
    - Scores no points (lineup_service enforces this).
    - Does not count toward coverage constraints.
    - Frees a roster spot for a waiver claim.

    Args:
        roster_id: UUID of the roster.
        player_id: UUID of the player to place in IR.

    Returns:
        Confirmation dict with roster_id, player_id, ir_slot_count.

    Raises:
        403: Caller does not own this roster.
        404: Roster not found.
        422: Player already in IR, capacity exceeded, or player not injured.
    """
    # Authorization — only the roster owner can place players in IR
    owner_id = await _get_roster_owner(roster_id, supabase)
    if owner_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "not_roster_owner"},
        )

    # Verify the player is actually injured or suspended in the pipeline
    avail_response = (
        await supabase.table("pipeline_stg_player_availability")
        .select("status")
        .eq("player_id", player_id)
        .order("updated_at", desc=True)
        .limit(1)
        .execute()
    )
    avail_rows = avail_response.data or []
    if not avail_rows or avail_rows[0]["status"] not in ("injured", "suspended"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "ir_player_not_injured",
                "message": (
                    f"Player {player_id} is not injured or suspended. "
                    "Only injured or suspended players can be placed in IR."
                ),
            },
        )

    # Build snapshot and validate placement (pure rules)
    snapshot = await _build_ir_snapshot(roster_id, supabase)
    try:
        validate_ir_placement(player_id, snapshot)
    except IRError as exc:
        raise _map_ir_error_to_http(exc) from exc

    # Write IR slot to DB
    await (
        supabase.table("weekly_lineups")
        .update({"slot_type": "ir", "ir_recovery_deadline": None})
        .eq("roster_id", roster_id)
        .eq("player_id", player_id)
        .execute()
    )

    logger.info(
        "IR: player %s placed in IR for roster %s by user %s.",
        player_id,
        roster_id,
        current_user_id,
    )

    return {
        "roster_id": roster_id,
        "player_id": player_id,
        "ir_slot_count": len(snapshot.current_ir_player_ids) + 1,
        "ir_slot_max": MAX_IR_SLOTS,
    }


# ---------------------------------------------------------------------------
# PUT /ir/reintegrate/{roster_id}/{player_id}
# ---------------------------------------------------------------------------


@router.put(
    "/reintegrate/{roster_id}/{player_id}",
    status_code=status.HTTP_200_OK,
    summary="Reintegrate a recovered player from IR",
    response_description="Player successfully reintegrated.",
)
async def reintegrate_player_from_ir(
    roster_id: str,
    player_id: str,
    current_user_id: str = Depends(get_current_user_id),
    supabase: AsyncClient = Depends(get_supabase_client),
) -> dict:
    """Reintegrate a recovered player from IR back to the active roster.

    The player must be in IR and marked as recovered in the pipeline.
    Reintegration clears ir_recovery_deadline, lifting any waiver/trade block.

    Args:
        roster_id: UUID of the roster.
        player_id: UUID of the player to reintegrate.

    Returns:
        Confirmation dict with roster_id, player_id, remaining_ir_slots.

    Raises:
        403: Caller does not own this roster.
        404: Roster not found.
        422: Player not in IR or still injured/suspended.
    """
    # Authorization
    owner_id = await _get_roster_owner(roster_id, supabase)
    if owner_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "not_roster_owner"},
        )

    # Build snapshot and validate reintegration (pure rules)
    snapshot = await _build_ir_snapshot(roster_id, supabase)
    try:
        validate_ir_reintegration(player_id, snapshot)
    except IRError as exc:
        raise _map_ir_error_to_http(exc) from exc

    # Clear IR slot — slot_type back to 'bench', deadline cleared
    await (
        supabase.table("weekly_lineups")
        .update({"slot_type": "bench", "ir_recovery_deadline": None})
        .eq("roster_id", roster_id)
        .eq("player_id", player_id)
        .execute()
    )

    logger.info(
        "IR: player %s reintegrated for roster %s by user %s.",
        player_id,
        roster_id,
        current_user_id,
    )

    remaining_slots = MAX_IR_SLOTS - (len(snapshot.current_ir_player_ids) - 1)

    return {
        "roster_id": roster_id,
        "player_id": player_id,
        "remaining_ir_slots": remaining_slots,
        "ir_slot_max": MAX_IR_SLOTS,
    }


# ---------------------------------------------------------------------------
# GET /ir/alerts/{league_id}
# ---------------------------------------------------------------------------


@router.get(
    "/alerts/{league_id}",
    status_code=status.HTTP_200_OK,
    summary="List overdue IR reintegration alerts for a league",
    response_description="List of rosters with overdue IR deadlines.",
)
async def get_ir_alerts(
    league_id: str,
    current_user_id: str = Depends(get_current_user_id),
    supabase: AsyncClient = Depends(get_supabase_client),
) -> dict:
    """Return all IR slots with an overdue reintegration deadline in a league.

    Used by the dashboard to display the alert:
    "Player X recovered — reintegrate within X days."

    Any authenticated league member can read alerts (not restricted to owner).
    The frontend filters to show only the current manager's own alerts.

    Args:
        league_id: UUID of the league.

    Returns:
        Dict with:
        - alerts: list of overdue IR slots (roster_id, player_id, deadline, days_overdue)
        - total: count of overdue slots

    Raises:
        404: League not found.
    """
    now = datetime.now(timezone.utc)

    # Verify league exists
    league_response = (
        await supabase.table("leagues")
        .select("id")
        .eq("id", league_id)
        .single()
        .execute()
    )
    if not league_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "league_not_found", "league_id": league_id},
        )

    # Fetch all IR slots with a non-null deadline in this league
    response = (
        await supabase.table("weekly_lineups")
        .select("roster_id, player_id, ir_recovery_deadline, rosters!inner(league_id)")
        .eq("slot_type", "ir")
        .not_.is_("ir_recovery_deadline", "null")
        .eq("rosters.league_id", league_id)
        .execute()
    )

    slots = response.data or []

    # Filter to overdue slots using pure function
    overdue = get_overdue_ir_slots(
        [
            {
                "roster_id": s["roster_id"],
                "player_id": s["player_id"],
                "ir_recovery_deadline": datetime.fromisoformat(
                    s["ir_recovery_deadline"]
                ),
            }
            for s in slots
        ],
        now=now,
    )

    # Enrich with days_overdue for the frontend display
    alerts = [
        {
            "roster_id": slot["roster_id"],
            "player_id": slot["player_id"],
            "ir_recovery_deadline": slot["ir_recovery_deadline"].isoformat(),
            "days_overdue": (now - slot["ir_recovery_deadline"]).days,
        }
        for slot in overdue
    ]

    return {"alerts": alerts, "total": len(alerts)}
