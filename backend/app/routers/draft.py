# backend/app/routers/draft.py
"""
Draft router — FastAPI endpoints for the snake draft protocol.

Endpoints:
    POST /draft/{league_id}/connect     — register as connected, get snapshot
    POST /draft/{league_id}/disconnect  — register as disconnected
    GET  /draft/{league_id}/state       — get full state snapshot (polling fallback)
    POST /draft/{league_id}/pick        — submit a manual pick

Architecture (D-001):
    All state mutations go through the DraftEngine, retrieved from the
    DraftRegistry stored in app.state.draft_registry. Supabase is never
    queried for draft state during an active draft.

Authentication:
    JWT is verified by AuthMiddleware (runs before these handlers).
    manager_id is extracted from request.state.user_id (set by middleware).

Reconnection protocol (CDC v3.1, section 7.4):
    1. Client reconnects → POST /connect → gets DraftStateSnapshotResponse
    2. If it was the manager's turn with time remaining → autodraft deactivated,
       timer restarted, they can pick manually.
    3. If timer already expired → autodraft pick is final, snapshot reflects it.
    4. GET /state is the fallback if Supabase Realtime is unavailable.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.schemas.draft import DraftStateSnapshotResponse, PickRecordResponse
from draft.engine import DraftStateSnapshot
from draft.registry import DraftRegistry
from draft.validate_pick import (
    NotYourTurnError,
    PickValidationError,
    PlayerAlreadyDraftedError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/draft",
    tags=["draft"],
)


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class PickRequest(BaseModel):
    """Request body for POST /draft/{league_id}/pick.

    Attributes:
        player_id: UUID of the player being drafted.
    """

    player_id: str = Field(
        ...,
        description="UUID of the player to draft.",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_registry(request: Request) -> DraftRegistry:
    """Extract the DraftRegistry from FastAPI application state.

    Args:
        request: The incoming FastAPI request.

    Returns:
        The shared DraftRegistry instance.
    """
    return request.app.state.draft_registry


def _get_manager_id(request: Request) -> str:
    """Extract the authenticated manager ID from the request state.

    Set by AuthMiddleware after JWT verification.

    Args:
        request: The incoming FastAPI request.

    Returns:
        The manager's user ID string.

    Raises:
        HTTPException 401: If the user_id is not set (unauthenticated).
    """
    manager_id: str | None = getattr(request.state, "user_id", None)
    if not manager_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    return manager_id


def _snapshot_to_response(snapshot: DraftStateSnapshot) -> DraftStateSnapshotResponse:
    """Convert an internal DraftStateSnapshot dataclass to a Pydantic response.

    Args:
        snapshot: The internal snapshot from DraftEngine.get_state_snapshot().

    Returns:
        A Pydantic DraftStateSnapshotResponse ready for JSON serialisation.
    """
    return DraftStateSnapshotResponse(
        league_id=snapshot.league_id,
        status=snapshot.status,
        current_pick_number=snapshot.current_pick_number,
        total_picks=snapshot.total_picks,
        current_manager_id=snapshot.current_manager_id,
        time_remaining=snapshot.time_remaining,
        picks=[
            PickRecordResponse(
                pick_number=p.pick_number,
                manager_id=p.manager_id,
                player_id=p.player_id,
                autodrafted=p.autodrafted,
                autodraft_source=p.autodraft_source,
                timestamp=p.timestamp,
            )
            for p in snapshot.picks
        ],
        autodraft_managers=snapshot.autodraft_managers,
        connected_managers=snapshot.connected_managers,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/{league_id}/connect",
    response_model=DraftStateSnapshotResponse,
    status_code=status.HTTP_200_OK,
    summary="Connect to a draft",
    description=(
        "Register the authenticated manager as connected and return the full "
        "draft state snapshot. If it is currently the manager's turn and no "
        "pick has been made yet, autodraft is deactivated and a manual timer "
        "is started so they can pick. "
        "Call this on every page load or WebSocket reconnection."
    ),
)
async def connect_to_draft(
    league_id: str,
    request: Request,
) -> DraftStateSnapshotResponse:
    """Connect a manager to an active draft and return the state snapshot.

    Args:
        league_id: The league whose draft to connect to.
        request: FastAPI request (carries auth state and app state).

    Returns:
        Full draft state snapshot.

    Raises:
        HTTPException 401: If not authenticated.
        HTTPException 404: If no active draft exists for this league.
    """
    manager_id = _get_manager_id(request)
    registry = _get_registry(request)

    engine = registry.get(league_id)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active draft for league '{league_id}'.",
        )

    logger.info(
        "Manager '%s' connecting to draft for league '%s'",
        manager_id,
        league_id,
    )

    snapshot = await engine.connect_manager(manager_id)
    return _snapshot_to_response(snapshot)


@router.post(
    "/{league_id}/disconnect",
    status_code=status.HTTP_200_OK,
    response_model=None,
    summary="Disconnect from a draft",
    description=(
        "Register the authenticated manager as disconnected. "
        "The draft continues uninterrupted — if the timer expires while "
        "disconnected, autodraft fires normally. "
        "Call this on page unload or WebSocket close."
    ),
)
async def disconnect_from_draft(
    league_id: str,
    request: Request,
) -> None:
    """Disconnect a manager from an active draft.

    Args:
        league_id: The league whose draft to disconnect from.
        request: FastAPI request (carries auth state and app state).

    Raises:
        HTTPException 401: If not authenticated.
        HTTPException 404: If no active draft exists for this league.
    """
    manager_id = _get_manager_id(request)
    registry = _get_registry(request)

    engine = registry.get(league_id)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active draft for league '{league_id}'.",
        )

    logger.info(
        "Manager '%s' disconnecting from draft for league '%s'",
        manager_id,
        league_id,
    )

    await engine.disconnect_manager(manager_id)


@router.get(
    "/{league_id}/state",
    response_model=DraftStateSnapshotResponse,
    status_code=status.HTTP_200_OK,
    summary="Get full draft state snapshot",
    description=(
        "Return the complete current state of a draft without side effects. "
        "Use as a polling fallback when Supabase Realtime is unavailable, "
        "or to verify state after reconnection. "
        "Does NOT register the caller as connected — call POST /connect for that."
    ),
)
async def get_draft_state(
    league_id: str,
    request: Request,
) -> DraftStateSnapshotResponse:
    """Return a read-only snapshot of the current draft state.

    No side effects — does not register the caller as connected.
    Safe to call at any frequency as a polling fallback.

    Args:
        league_id: The league whose draft state to retrieve.
        request: FastAPI request (carries auth state and app state).

    Returns:
        Full draft state snapshot.

    Raises:
        HTTPException 401: If not authenticated.
        HTTPException 404: If no active draft exists for this league.
    """
    _get_manager_id(request)
    registry = _get_registry(request)

    engine = registry.get(league_id)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active draft for league '{league_id}'.",
        )

    snapshot = engine.get_state_snapshot()
    return _snapshot_to_response(snapshot)


@router.post(
    "/{league_id}/pick",
    response_model=DraftStateSnapshotResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit a manual pick",
    description=(
        "Submit a pick for the authenticated manager. "
        "The manager must be the current active picker — FastAPI validates "
        "turn order, player availability, and roster constraints. "
        "Returns the updated full state snapshot after the pick is recorded. "
        "The new state is also broadcast via Supabase Realtime to all clients."
    ),
)
async def submit_pick(
    league_id: str,
    body: PickRequest,
    request: Request,
) -> DraftStateSnapshotResponse:
    """Submit a manual player pick for the authenticated manager.

    Validates:
        - Manager is authenticated (JWT).
        - An active draft exists for this league.
        - It is this manager's turn (NotYourTurnError → 409).
        - The player is available (PlayerAlreadyDraftedError → 409).
        - Roster constraints are satisfied (PickValidationError → 422).

    Args:
        league_id: The league whose draft to pick in.
        body: Contains the player_id to draft.
        request: FastAPI request (carries auth state and app state).

    Returns:
        Full updated draft state snapshot.

    Raises:
        HTTPException 401: If not authenticated.
        HTTPException 404: If no active draft exists for this league.
        HTTPException 409: If it is not the manager's turn or player already drafted.
        HTTPException 422: If the pick violates roster constraints.
    """
    manager_id = _get_manager_id(request)
    registry = _get_registry(request)

    engine = registry.get(league_id)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active draft for league '{league_id}'.",
        )

    logger.info(
        "Manager '%s' submitting pick: player_id='%s' league='%s'",
        manager_id,
        body.player_id,
        league_id,
    )

    try:
        snapshot = await engine.submit_pick(
            manager_id=manager_id,
            player_id=body.player_id,
        )
    except NotYourTurnError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except PlayerAlreadyDraftedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except PickValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return _snapshot_to_response(snapshot)
