"""Trade endpoints for RugbyDraft.

All business logic is delegated to trade_service.py.
This router handles:
  - Authentication (JWT via get_current_user_id)
  - League membership verification (manager must belong to the league)
  - HTTP error mapping (typed processor exceptions → HTTP status codes)
  - Request/response serialisation (Pydantic models)

Route summary:
  POST   /trades                        — propose a new trade
  GET    /trades/{trade_id}             — get a single trade
  GET    /leagues/{league_id}/trades    — list all trades in a league
  POST   /trades/{trade_id}/accept      — receiver accepts
  POST   /trades/{trade_id}/reject      — receiver rejects
  POST   /trades/{trade_id}/cancel      — proposer cancels
  POST   /trades/{trade_id}/veto        — commissioner vetoes
  POST   /trades/complete-expired       — cron: complete veto-expired trades
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from supabase import Client

from app.dependencies import get_current_user_id, get_supabase_client
from app.models.trade import (
    TradeListResponse,
    TradeProposalInput,
    TradeResponse,
    TradeVetoInput,
)
from trades.processor import (
    TradeInvalidStatusError,
    TradeProcessorError,
    TradeStatus,
    TradeVetoNotEnabledError,
    TradeVetoReasonRequiredError,
    TradeVetoWindowExpiredError,
)
from trades.validate_trade import (
    TradeDuplicatePlayerError,
    TradeFormatError,
    TradeGhostTeamError,
    TradeIRBlockError,
    TradeOwnershipError,
    TradeSelfTradeError,
    TradeValidationError,
    TradeWindowClosedError,
)
from app.services.trade_service import (
    accept_trade_proposal,
    cancel_trade_proposal,
    complete_expired_veto_trades,
    create_trade,
    get_trade,
    list_league_trades,
    reject_trade_proposal,
    veto_trade_proposal,
)

router = APIRouter(prefix="/trades", tags=["trades"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_member_id(supabase: Client, user_id: str, league_id: str) -> str:
    """Resolve a user UUID to their league_members UUID in a given league.

    Every authenticated action needs the member_id (league_members.id),
    not the user_id (users.id). This is the single place where we do
    that resolution.

    Args:
        supabase: Injected Supabase client.
        user_id: The authenticated user's UUID (from JWT).
        league_id: The league UUID.

    Returns:
        The league_members.id UUID for this user in this league.

    Raises:
        HTTPException 403: If the user is not a member of the league.
    """
    result = (
        supabase.table("league_members")
        .select("id")
        .eq("user_id", user_id)
        .eq("league_id", league_id)
        .eq("is_ghost_team", False)
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this league.",
        )
    return result.data["id"]


def _handle_trade_errors(exc: Exception) -> HTTPException:
    """Map typed trade exceptions to HTTP responses.

    Centralised mapping so each endpoint doesn't repeat the same
    try/except blocks.

    Args:
        exc: The exception raised by the service or processor.

    Returns:
        An HTTPException with the appropriate status code and detail.
    """

    # 409 Conflict — business rule violation, state is valid but action blocked.
    if isinstance(exc, (TradeWindowClosedError, TradeIRBlockError)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    # 422 Unprocessable — format or ownership issues.
    if isinstance(
        exc, (TradeFormatError, TradeOwnershipError, TradeDuplicatePlayerError)
    ):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )

    # 403 Forbidden — ghost team, self-trade, wrong requester.
    if isinstance(
        exc, (TradeGhostTeamError, TradeSelfTradeError, TradeInvalidStatusError)
    ):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))

    # 400 Bad Request — veto-specific errors.
    if isinstance(
        exc,
        (
            TradeVetoNotEnabledError,
            TradeVetoWindowExpiredError,
            TradeVetoReasonRequiredError,
        ),
    ):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # 404 Not Found — trade or league does not exist.
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    # 500 fallback — should never happen if processor is correct.
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="An unexpected error occurred.",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=TradeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Propose a new trade",
)
async def propose_trade_endpoint(
    body: TradeProposalInput,
    league_id: str = Query(..., description="The league UUID"),
    user_id: str = Depends(get_current_user_id),
    supabase: Client = Depends(get_supabase_client),
) -> TradeResponse:
    """Propose a trade to another manager in the same league.

    The authenticated user is the proposer. The receiver_member_id
    in the request body must belong to the same league.

    Returns 201 with the new trade in PENDING status.
    """
    # Resolve proposer's member_id (also validates league membership).
    proposer_member_id = _get_member_id(supabase, user_id, league_id)

    try:
        return create_trade(
            supabase=supabase,
            league_id=league_id,
            proposer_member_id=proposer_member_id,
            receiver_member_id=body.receiver_member_id,
            proposer_player_ids=body.proposer_player_ids,
            receiver_player_ids=body.receiver_player_ids,
        )
    except (TradeValidationError, TradeProcessorError, ValueError) as exc:
        raise _handle_trade_errors(exc) from exc


@router.get(
    "/{trade_id}",
    response_model=TradeResponse,
    summary="Get a single trade by ID",
)
async def get_trade_endpoint(
    trade_id: str,
    user_id: str = Depends(get_current_user_id),
    supabase: Client = Depends(get_supabase_client),
) -> TradeResponse:
    """Fetch a single trade record.

    Visible to all members of the league the trade belongs to
    (enforced by RLS on the trades table).
    """
    try:
        return get_trade(supabase=supabase, trade_id=trade_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/league/{league_id}",
    response_model=TradeListResponse,
    summary="List all trades in a league",
)
async def list_trades_endpoint(
    league_id: str,
    trade_status: TradeStatus | None = Query(
        default=None,
        alias="status",
        description="Filter by trade status",
    ),
    user_id: str = Depends(get_current_user_id),
    supabase: Client = Depends(get_supabase_client),
) -> TradeListResponse:
    """List all trades in a league, optionally filtered by status.

    Used for the trade log page — visible to all managers (CDC §9.2).
    RLS ensures only league members can access this data.
    """
    # Verify league membership before listing.
    _get_member_id(supabase, user_id, league_id)

    return list_league_trades(
        supabase=supabase,
        league_id=league_id,
        status=trade_status,
    )


@router.post(
    "/{trade_id}/accept",
    response_model=TradeResponse,
    summary="Accept a trade proposal",
)
async def accept_trade_endpoint(
    trade_id: str,
    user_id: str = Depends(get_current_user_id),
    supabase: Client = Depends(get_supabase_client),
) -> TradeResponse:
    """Receiver accepts a PENDING trade proposal.

    The service verifies that the authenticated user is the receiver.
    Returns the updated trade (ACCEPTED if veto enabled, COMPLETED if not).
    """
    # We need the league_id to resolve member_id — fetch it from the trade.
    try:
        trade = get_trade(supabase=supabase, trade_id=trade_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    member_id = _get_member_id(supabase, user_id, trade.league_id)

    try:
        return accept_trade_proposal(
            supabase=supabase,
            trade_id=trade_id,
            requester_member_id=member_id,
        )
    except (TradeProcessorError, ValueError) as exc:
        raise _handle_trade_errors(exc) from exc


@router.post(
    "/{trade_id}/reject",
    response_model=TradeResponse,
    summary="Reject a trade proposal",
)
async def reject_trade_endpoint(
    trade_id: str,
    user_id: str = Depends(get_current_user_id),
    supabase: Client = Depends(get_supabase_client),
) -> TradeResponse:
    """Receiver rejects a PENDING trade proposal.

    The service verifies that the authenticated user is the receiver.
    """
    try:
        trade = get_trade(supabase=supabase, trade_id=trade_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    member_id = _get_member_id(supabase, user_id, trade.league_id)

    try:
        return reject_trade_proposal(
            supabase=supabase,
            trade_id=trade_id,
            requester_member_id=member_id,
        )
    except (TradeProcessorError, ValueError) as exc:
        raise _handle_trade_errors(exc) from exc


@router.post(
    "/{trade_id}/cancel",
    response_model=TradeResponse,
    summary="Cancel a trade proposal",
)
async def cancel_trade_endpoint(
    trade_id: str,
    user_id: str = Depends(get_current_user_id),
    supabase: Client = Depends(get_supabase_client),
) -> TradeResponse:
    """Proposer cancels their own PENDING trade proposal.

    The processor verifies that the requester is the proposer.
    """
    try:
        trade = get_trade(supabase=supabase, trade_id=trade_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    member_id = _get_member_id(supabase, user_id, trade.league_id)

    try:
        return cancel_trade_proposal(
            supabase=supabase,
            trade_id=trade_id,
            requester_member_id=member_id,
        )
    except (TradeProcessorError, ValueError) as exc:
        raise _handle_trade_errors(exc) from exc


@router.post(
    "/{trade_id}/veto",
    response_model=TradeResponse,
    summary="Commissioner vetoes an accepted trade",
)
async def veto_trade_endpoint(
    trade_id: str,
    body: TradeVetoInput,
    user_id: str = Depends(get_current_user_id),
    supabase: Client = Depends(get_supabase_client),
) -> TradeResponse:
    """Commissioner blocks an ACCEPTED trade within the 24h veto window.

    The commissioner must provide a reason (CDC §9.2).
    The reason and timestamp are logged and visible to all managers.
    """
    try:
        trade = get_trade(supabase=supabase, trade_id=trade_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    member_id = _get_member_id(supabase, user_id, trade.league_id)

    try:
        return veto_trade_proposal(
            supabase=supabase,
            trade_id=trade_id,
            commissioner_member_id=member_id,
            league_id=trade.league_id,
            reason=body.reason,
        )
    except (TradeProcessorError, TradeValidationError, ValueError) as exc:
        raise _handle_trade_errors(exc) from exc


@router.post(
    "/complete-expired",
    summary="Complete all trades whose veto window has expired",
    status_code=status.HTTP_200_OK,
)
async def complete_expired_trades_endpoint(
    supabase: Client = Depends(get_supabase_client),
) -> dict[str, int]:
    """Complete all ACCEPTED trades whose 24h veto deadline has passed.

    Called by Coolify cron — not a user-facing endpoint.
    No authentication required (internal only — protect via network policy
    or a shared secret header in production).

    Returns a count of trades completed in this run.
    """
    completed = complete_expired_veto_trades(supabase=supabase)
    return {"completed": completed}
