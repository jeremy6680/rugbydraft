"""
Lineup router — weekly lineup management endpoints.

Endpoints:
- GET  /lineup/{roster_id}/round/{round_id}          → get current lineup
- PUT  /lineup/{roster_id}/round/{round_id}          → submit full lineup
- PATCH /lineup/{roster_id}/round/{round_id}/captain → update captain
- PATCH /lineup/{roster_id}/round/{round_id}/kicker  → update kicker

All mutations go through LineupService — no business logic in this layer.
HTTP error mapping:
  LineupOwnershipError  → 403
  LineupLockError       → 409
  LineupValidationError → 422
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_current_user_id, get_supabase_client
from app.models.lineup import (
    CaptainUpdate,
    KickerUpdate,
    LineupResponse,
    LineupSubmission,
)
from app.services.lineup_service import (
    LineupLockError,
    LineupOwnershipError,
    LineupService,
    LineupValidationError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/lineup",
    tags=["lineup"],
)


# ---------------------------------------------------------------------------
# Dependency — instantiate LineupService with the authenticated Supabase client
# ---------------------------------------------------------------------------


def get_lineup_service(
    client=Depends(get_supabase_client),
) -> LineupService:
    """FastAPI dependency: return a LineupService bound to the user's Supabase client.

    The client carries the user's JWT so RLS policies apply automatically.
    """
    return LineupService(client=client)


# ---------------------------------------------------------------------------
# Error mapping helper
# ---------------------------------------------------------------------------


def _handle_lineup_error(exc: Exception) -> None:
    """Map lineup service exceptions to appropriate HTTP responses.

    Args:
        exc: Exception raised by the lineup service.

    Raises:
        HTTPException: with the appropriate status code and detail message.
    """
    if isinstance(exc, LineupOwnershipError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
    if isinstance(exc, LineupLockError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    if isinstance(exc, LineupValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    # Unexpected error — log and return 500
    logger.exception("Unexpected error in lineup router: %s", exc)
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="An unexpected error occurred. Please try again.",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/{roster_id}/round/{round_id}",
    response_model=LineupResponse,
    summary="Get current lineup for a roster/round",
    description=(
        "Returns the full lineup with lock status per player. "
        "is_locked=True means the player's team has already kicked off "
        "and no changes are possible for that player."
    ),
)
async def get_lineup(
    roster_id: UUID,
    round_id: UUID,
    service: LineupService = Depends(get_lineup_service),
) -> LineupResponse:
    """Return the current weekly lineup for a roster and round.

    Args:
        roster_id: UUID of the roster (path parameter).
        round_id: UUID of the competition round (path parameter).
        service: LineupService injected by FastAPI.

    Returns:
        LineupResponse with starters, bench, captain, kicker, lock status.
    """
    try:
        return await service.get_lineup(roster_id=roster_id, round_id=round_id)
    except Exception as exc:
        _handle_lineup_error(exc)


@router.put(
    "/{roster_id}/round/{round_id}",
    response_model=LineupResponse,
    summary="Submit full lineup for a round",
    description=(
        "Submit exactly 15 starters with their positions, captain, and kicker. "
        "Replaces any previously submitted lineup for this round. "
        "Blocked if any submitted player's team has already kicked off."
    ),
)
async def submit_lineup(
    roster_id: UUID,
    round_id: UUID,
    submission: LineupSubmission,
    user_id: UUID = Depends(get_current_user_id),
    service: LineupService = Depends(get_lineup_service),
) -> LineupResponse:
    """Submit a complete 15-player lineup for a round.

    Args:
        roster_id: UUID of the roster (path parameter).
        round_id: UUID of the competition round (path parameter).
        submission: Lineup payload with 15 starters, captain, kicker.
        user_id: UUID of the authenticated user (from JWT).
        service: LineupService injected by FastAPI.

    Returns:
        Updated LineupResponse after persisting the lineup.
    """
    try:
        return await service.submit_lineup(
            roster_id=roster_id,
            round_id=round_id,
            user_id=user_id,
            submission=submission,
        )
    except Exception as exc:
        _handle_lineup_error(exc)


@router.patch(
    "/{roster_id}/round/{round_id}/captain",
    response_model=LineupResponse,
    summary="Change captain designation",
    description=(
        "Designate a new captain for this round. "
        "Blocked if the current captain's team has already kicked off (CDC 6.6). "
        "The new captain must be a starter in the submitted lineup."
    ),
)
async def update_captain(
    roster_id: UUID,
    round_id: UUID,
    update: CaptainUpdate,
    user_id: UUID = Depends(get_current_user_id),
    service: LineupService = Depends(get_lineup_service),
) -> LineupResponse:
    """Change the captain designation for a round.

    Args:
        roster_id: UUID of the roster (path parameter).
        round_id: UUID of the competition round (path parameter).
        update: CaptainUpdate payload with new captain's player_id.
        user_id: UUID of the authenticated user (from JWT).
        service: LineupService injected by FastAPI.

    Returns:
        Updated LineupResponse with new captain flag.
    """
    try:
        return await service.update_captain(
            roster_id=roster_id,
            round_id=round_id,
            user_id=user_id,
            update=update,
        )
    except Exception as exc:
        _handle_lineup_error(exc)


@router.patch(
    "/{roster_id}/round/{round_id}/kicker",
    response_model=LineupResponse,
    summary="Change kicker designation",
    description=(
        "Designate a new kicker for this round. "
        "Blocked once the current kicker's team has kicked off (CDC 6.6). "
        "Cannot be changed until the next round. "
        "The new kicker must be a starter in the submitted lineup."
    ),
)
async def update_kicker(
    roster_id: UUID,
    round_id: UUID,
    update: KickerUpdate,
    user_id: UUID = Depends(get_current_user_id),
    service: LineupService = Depends(get_lineup_service),
) -> LineupResponse:
    """Change the kicker designation for a round.

    Args:
        roster_id: UUID of the roster (path parameter).
        round_id: UUID of the competition round (path parameter).
        update: KickerUpdate payload with new kicker's player_id.
        user_id: UUID of the authenticated user (from JWT).
        service: LineupService injected by FastAPI.

    Returns:
        Updated LineupResponse with new kicker flag.
    """
    try:
        return await service.update_kicker(
            roster_id=roster_id,
            round_id=round_id,
            user_id=user_id,
            update=update,
        )
    except Exception as exc:
        _handle_lineup_error(exc)
