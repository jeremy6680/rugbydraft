# backend/app/routers/draft_assisted.py
"""
Assisted Draft router — FastAPI endpoints for commissioner fallback mode.

Implements CDC v3.1, section 7.5 (Draft Assistée).

Endpoints:
    POST /draft/{league_id}/assisted/enable  — commissioner activates assisted mode
    POST /draft/{league_id}/assisted/pick    — commissioner submits a pick for a manager
    GET  /draft/{league_id}/assisted/log     — read audit log (visible to all managers)

Who can call what:
    - /enable and /pick: commissioner only (validated by DraftEngine).
    - /log: any authenticated user in the league (read-only, public within league).

Authentication:
    JWT verified by AuthMiddleware. User ID extracted from request.state.user_id.
    Commissioner identity is validated by the DraftEngine (not by this router) —
    the engine checks against the commissioner_id stored in DraftState.

Design note:
    This router contains no business logic. It only:
        1. Extracts the authenticated user ID from the request.
        2. Retrieves the DraftEngine from the registry.
        3. Delegates to engine methods.
        4. Maps domain errors to HTTP status codes.
    Business rules live in draft/engine.py and draft/assisted.py.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.schemas.draft import PickRecordResponse
from draft.assisted import (
    AssistedModeAlreadyActiveError,
    AssistedModeNotActiveError,
    AssistedPickAuditEntry,
    NotCommissionerError,
)
from draft.registry import DraftRegistry
from draft.validate_pick import PickValidationError

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/draft",
    tags=["draft-assisted"],
)


# ---------------------------------------------------------------------------
# Request / Response schemas (local to this router)
# ---------------------------------------------------------------------------


class AssistedPickRequest(BaseModel):
    """Request body for POST /draft/{league_id}/assisted/pick.

    Attributes:
        manager_id: Manager whose turn it is in the snake order.
        player_id: Player being drafted.
    """

    manager_id: str = Field(
        ...,
        description="Manager whose turn it is (must match current snake order slot).",
    )
    player_id: str = Field(
        ...,
        description="UUID of the player being drafted.",
    )


class AssistedPickAuditEntryResponse(BaseModel):
    """A single entry in the assisted draft audit log.

    Mirrors AssistedPickAuditEntry from draft/assisted.py.
    Returned by GET /draft/{league_id}/assisted/log.

    Attributes:
        pick_number: Absolute pick number (1-indexed).
        manager_id: Manager whose turn it was.
        player_id: Player who was picked.
        commissioner_id: User ID of the commissioner who entered the pick.
        timestamp: Unix timestamp when the pick was recorded.
    """

    pick_number: int = Field(..., ge=1)
    manager_id: str
    player_id: str
    commissioner_id: str
    timestamp: float

    model_config = {"from_attributes": True}


class AssistedAuditLogResponse(BaseModel):
    """Response body for GET /draft/{league_id}/assisted/log.

    Attributes:
        league_id: The league this log belongs to.
        assisted_mode: Whether assisted mode is currently active.
        entries: All commissioner-entered picks in order.
    """

    league_id: str
    assisted_mode: bool
    entries: list[AssistedPickAuditEntryResponse]


# ---------------------------------------------------------------------------
# Helpers (same pattern as draft.py)
# ---------------------------------------------------------------------------


def _get_registry(request: Request) -> DraftRegistry:
    """Extract the DraftRegistry from FastAPI application state."""
    return request.app.state.draft_registry


def _get_user_id(request: Request) -> str:
    """Extract the authenticated user ID from the request state.

    Set by AuthMiddleware after JWT verification.

    Raises:
        HTTPException 401: If the user_id is not set (unauthenticated).
    """
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    return user_id


def _audit_entry_to_response(
    entry: AssistedPickAuditEntry,
) -> AssistedPickAuditEntryResponse:
    """Convert an internal AssistedPickAuditEntry to a Pydantic response."""
    return AssistedPickAuditEntryResponse(
        pick_number=entry.pick_number,
        manager_id=entry.manager_id,
        player_id=entry.player_id,
        commissioner_id=entry.commissioner_id,
        timestamp=entry.timestamp,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/{league_id}/assisted/enable",
    status_code=status.HTTP_200_OK,
    response_model=None,
    summary="Enable Assisted Draft mode",
    description=(
        "Commissioner-only. Switches the draft to Assisted Draft mode "
        "(CDC v3.1, section 7.5). The server-side timer is cancelled. "
        "All subsequent picks must be submitted via POST /assisted/pick. "
        "Cannot be called on a completed draft or if already active."
    ),
)
async def enable_assisted_mode(
    league_id: str,
    request: Request,
) -> dict:
    """Activate Assisted Draft mode for a league draft.

    Args:
        league_id: The league whose draft to switch to assisted mode.
        request: FastAPI request (carries auth state and app state).

    Returns:
        Confirmation JSON: {"message": "Assisted mode enabled.", "league_id": ...}

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 403: Caller is not the league commissioner.
        HTTPException 404: No active draft for this league.
        HTTPException 409: Assisted mode is already active.
        HTTPException 422: Draft is completed.
    """
    user_id = _get_user_id(request)
    registry = _get_registry(request)

    engine = registry.get(league_id)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active draft for league '{league_id}'.",
        )

    try:
        await engine.enable_assisted_mode(commissioner_id=user_id)
    except NotCommissionerError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        ) from exc
    except AssistedModeAlreadyActiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.message,
        ) from exc
    except RuntimeError as exc:
        # Draft is completed
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    logger.info(
        "Assisted mode enabled for league '%s' by user '%s'",
        league_id,
        user_id,
    )

    return {"message": "Assisted mode enabled.", "league_id": league_id}


@router.post(
    "/{league_id}/assisted/pick",
    response_model=PickRecordResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit an assisted pick",
    description=(
        "Commissioner-only. Submit a pick on behalf of a manager in Assisted "
        "Draft mode. The manager_id must match the current snake order slot. "
        "Player availability and roster constraints are still enforced. "
        "Every pick is logged with a timestamp and commissioner_id."
    ),
)
async def submit_assisted_pick(
    league_id: str,
    request: Request,
    body: AssistedPickRequest = Body(...),
) -> PickRecordResponse:
    """Submit a pick on behalf of a manager (Assisted Draft mode).

    Args:
        league_id: The league whose draft this pick belongs to.
        request: FastAPI request (carries auth state and app state).
        body: manager_id + player_id to pick.

    Returns:
        The recorded PickRecordResponse (with entered_by_commissioner=True).

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 403: Caller is not the league commissioner.
        HTTPException 404: No active draft for this league.
        HTTPException 409: Assisted mode is not active (enable it first).
        HTTPException 422: Turn, player, or roster validation failed.
    """
    user_id = _get_user_id(request)
    registry = _get_registry(request)

    engine = registry.get(league_id)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active draft for league '{league_id}'.",
        )

    try:
        record = await engine.submit_assisted_pick(
            commissioner_id=user_id,
            manager_id=body.manager_id,
            player_id=body.player_id,
        )
    except NotCommissionerError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        ) from exc
    except AssistedModeNotActiveError as exc:
        # Commissioner forgot to call /enable first
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.message,
        ) from exc
    except PickValidationError as exc:
        # Turn mismatch, player already drafted, roster constraints, etc.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    logger.info(
        "Assisted pick %d submitted for league '%s': manager='%s' player='%s'",
        record.pick_number,
        league_id,
        body.manager_id,
        body.player_id,
    )

    return PickRecordResponse(
        pick_number=record.pick_number,
        manager_id=record.manager_id,
        player_id=record.player_id,
        autodrafted=record.autodrafted,
        autodraft_source=record.autodraft_source,
        entered_by_commissioner=record.entered_by_commissioner,
        timestamp=record.timestamp,
    )


@router.get(
    "/{league_id}/assisted/log",
    response_model=AssistedAuditLogResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Assisted Draft audit log",
    description=(
        "Read-only. Returns the full audit log of commissioner-entered picks "
        "for a draft. Visible to all authenticated users (CDC v3.1 section 7.5: "
        "'log visible to all managers'). Returns an empty list if assisted mode "
        "was never activated or no assisted picks have been made yet."
    ),
)
async def get_assisted_audit_log(
    league_id: str,
    request: Request,
) -> AssistedAuditLogResponse:
    """Return the audit log of all commissioner-entered picks.

    Safe to call at any frequency — read-only, no side effects.

    Args:
        league_id: The league whose draft audit log to retrieve.
        request: FastAPI request (carries auth state and app state).

    Returns:
        AssistedAuditLogResponse with all entries in pick order.

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 404: No active draft for this league.
    """
    _get_user_id(request)  # authentication check only
    registry = _get_registry(request)

    engine = registry.get(league_id)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active draft for league '{league_id}'.",
        )

    audit_log = engine.get_assisted_audit_log()
    snapshot = engine.get_state_snapshot()

    return AssistedAuditLogResponse(
        league_id=league_id,
        assisted_mode=snapshot.assisted_mode,
        entries=[_audit_entry_to_response(e) for e in audit_log],
    )
