"""Waiver endpoints — FastAPI router.

Endpoints:
    POST   /leagues/{league_id}/waivers          — submit a claim
    GET    /leagues/{league_id}/waivers          — list own claims for a round
    DELETE /leagues/{league_id}/waivers/{id}     — cancel a pending claim
    POST   /leagues/{league_id}/waivers/process  — trigger cycle (scheduler only)
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.dependencies import get_current_user_id, get_supabase_client
from app.services.waiver_service import (
    cancel_claim,
    get_member_claims,
    process_cycle,
    submit_claim,
)
from waivers.validate_claim import (
    DropPlayerNotOwnedError,
    GhostTeamCannotClaimError,
    IRBlockingRuleError,
    PlayerNotFreeError,
    WaiverWindowClosedError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/leagues/{league_id}/waivers", tags=["waivers"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class WaiverClaimIn(BaseModel):
    """Body for POST /leagues/{league_id}/waivers."""

    round_id: str = Field(..., description="UUID of the current competition round.")
    add_player_id: str = Field(..., description="UUID of the free agent to claim.")
    drop_player_id: str | None = Field(
        None,
        description="UUID of the rostered player to drop. Omit if a roster slot is available.",
    )
    claim_rank: int = Field(
        1,
        ge=1,
        le=20,
        description="Manager's preference order (1 = top priority). Max 20 claims per cycle.",
    )


class WaiverClaimOut(BaseModel):
    """Response for a single waiver claim."""

    id: str
    league_id: str
    round_id: str
    member_id: str
    add_player_id: str
    drop_player_id: str | None
    claim_rank: int
    priority: int
    status: str
    created_at: datetime


class CycleSummaryOut(BaseModel):
    """Response for POST /leagues/{league_id}/waivers/process."""

    league_id: str
    round_id: str
    granted: int
    denied: int
    skipped: int


class ProcessCycleIn(BaseModel):
    """Body for POST /leagues/{league_id}/waivers/process."""

    round_id: str = Field(..., description="UUID of the round to process.")
    scheduler_secret: str = Field(
        ...,
        description="Shared secret to authenticate the scheduler call.",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=WaiverClaimOut,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a waiver claim",
)
async def submit_waiver_claim(
    league_id: str,
    body: WaiverClaimIn,
    user_id: str = Depends(get_current_user_id),
    db=Depends(get_supabase_client),
) -> WaiverClaimOut:
    """Submit a waiver claim for the authenticated manager.

    Validates the claim against all business rules (window, IR block,
    player availability) and persists it as pending.

    Raises 422 on business rule violations with a human-readable message.
    """
    # Resolve member_id from user_id + league_id
    member_id = await _resolve_member_id(db, league_id=league_id, user_id=user_id)

    try:
        created = await submit_claim(
            db,
            league_id=league_id,
            round_id=body.round_id,
            member_id=member_id,
            add_player_id=body.add_player_id,
            drop_player_id=body.drop_player_id,
            claim_rank=body.claim_rank,
        )
    except WaiverWindowClosedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    except GhostTeamCannotClaimError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except IRBlockingRuleError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    except PlayerNotFreeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except DropPlayerNotOwnedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )

    return WaiverClaimOut(**created)


@router.get(
    "",
    response_model=list[WaiverClaimOut],
    summary="List own waiver claims",
)
async def list_waiver_claims(
    league_id: str,
    round_id: str | None = Query(None, description="Filter by round UUID."),
    user_id: str = Depends(get_current_user_id),
    db=Depends(get_supabase_client),
) -> list[WaiverClaimOut]:
    """Return the authenticated manager's waiver claims for a league.

    Optionally filtered by round_id.
    """
    member_id = await _resolve_member_id(db, league_id=league_id, user_id=user_id)

    claims = await get_member_claims(
        db,
        league_id=league_id,
        member_id=member_id,
        round_id=round_id,
    )
    return [WaiverClaimOut(**c) for c in claims]


@router.delete(
    "/{waiver_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel a pending waiver claim",
)
async def cancel_waiver_claim(
    league_id: str,
    waiver_id: str,
    user_id: str = Depends(get_current_user_id),
    db=Depends(get_supabase_client),
) -> None:
    """Cancel a pending waiver claim.

    Only the owner of the claim can cancel it. Only pending claims
    can be cancelled — granted/denied/skipped are immutable.
    """
    member_id = await _resolve_member_id(db, league_id=league_id, user_id=user_id)

    try:
        await cancel_claim(db, waiver_id=waiver_id, member_id=member_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )


@router.post(
    "/process",
    response_model=CycleSummaryOut,
    summary="Trigger waiver cycle processing (scheduler only)",
)
async def trigger_waiver_cycle(
    league_id: str,
    body: ProcessCycleIn,
    db=Depends(get_supabase_client),
) -> CycleSummaryOut:
    """Process the waiver cycle for a league.

    Called by the Cron Coolify scheduler on Wednesday evening.
    Protected by a shared secret (WAIVER_SCHEDULER_SECRET env var).

    Not authenticated via JWT — the scheduler does not have a user session.
    Uses service role Supabase client injected via get_supabase_client().
    """
    from app.config import settings

    if body.scheduler_secret != settings.waiver_scheduler_secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid scheduler secret."
        )

    summary = await process_cycle(
        db,
        league_id=league_id,
        round_id=body.round_id,
    )

    return CycleSummaryOut(league_id=league_id, round_id=body.round_id, **summary)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _resolve_member_id(db, *, league_id: str, user_id: str) -> str:
    """Resolve the league_members.id for a given user in a league.

    Raises 403 if the user is not a member of this league.
    """
    response = await (
        db.table("league_members")
        .select("id")
        .eq("league_id", league_id)
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    if not response.data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this league.",
        )
    return response.data["id"]
