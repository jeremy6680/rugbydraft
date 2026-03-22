"""Trade service for RugbyDraft.

Handles all I/O between FastAPI and Supabase for the trade system.
Business logic lives in trades/processor.py and trades/validate_trade.py —
this service only fetches, maps, calls, and persists.

Supabase client is injected via FastAPI dependency injection (get_supabase_client).
All datetime comparisons use UTC — never local time.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from supabase import Client

from app.models.trade import TradeListResponse, TradeResponse
from trades.processor import (
    TradeRecord,
    TradePlayerEntry,
    TradeStatus,
    accept_trade,
    cancel_trade,
    commissioner_veto,
    complete_trade,
    propose_trade,
    reject_trade,
)
from trades.validate_trade import (
    TradeParty,
    TradeProposal,
)
from trades.window import TradeWindowContext


# ---------------------------------------------------------------------------
# Internal helpers — DB → domain object mapping
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    """Return current UTC datetime. Centralised for easy mocking in tests."""
    return datetime.now(tz=timezone.utc)


def _today_utc() -> date:
    """Return current UTC date. Centralised for easy mocking in tests."""
    return _now_utc().date()


def _record_to_response(
    record: TradeRecord, completed_at: datetime | None = None
) -> TradeResponse:
    """Convert a TradeRecord dataclass to a TradeResponse Pydantic model.

    Args:
        record: The domain object from the processor.
        completed_at: Timestamp when the trade was completed, if applicable.
            Stored separately in the DB — not part of TradeRecord.

    Returns:
        A TradeResponse ready for serialisation.
    """
    return TradeResponse(
        trade_id=record.trade_id,
        league_id=record.league_id,
        proposer_id=record.proposer_id,
        receiver_id=record.receiver_id,
        status=record.status,
        players=[
            {
                "player_id": p.player_id,
                "from_member_id": p.from_member_id,
                "to_member_id": p.to_member_id,
            }
            for p in record.players
        ],
        veto_enabled=record.veto_enabled,
        veto_deadline=record.veto_deadline,
        veto_reason=record.veto_reason,
        veto_at=record.veto_at,
        completed_at=completed_at,
        created_at=record.created_at,
    )


def _row_to_record(trade_row: dict, player_rows: list[dict]) -> TradeRecord:
    """Reconstruct a TradeRecord from raw Supabase rows.

    Args:
        trade_row: A single row from the `trades` table.
        player_rows: All rows from `trade_players` for this trade.

    Returns:
        A fully populated TradeRecord.
    """
    players = tuple(
        TradePlayerEntry(
            player_id=row["player_id"],
            from_member_id=row["from_member_id"],
            to_member_id=row["to_member_id"],
        )
        for row in player_rows
    )

    def _parse_dt(value: str | None) -> datetime | None:
        """Parse an ISO 8601 string from Supabase into a UTC datetime."""
        if value is None:
            return None
        dt = datetime.fromisoformat(value)
        # Supabase returns timezone-aware strings — ensure UTC.
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    return TradeRecord(
        trade_id=trade_row["id"],
        league_id=trade_row["league_id"],
        proposer_id=trade_row["proposer_id"],
        receiver_id=trade_row["receiver_id"],
        status=TradeStatus(trade_row["status"]),
        players=players,
        veto_enabled=trade_row["veto_enabled"],
        veto_deadline=_parse_dt(trade_row.get("veto_deadline")),
        veto_reason=trade_row.get("veto_reason"),
        veto_at=_parse_dt(trade_row.get("veto_at")),
        created_at=_parse_dt(trade_row["created_at"]),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Internal helpers — Supabase queries
# ---------------------------------------------------------------------------


def _fetch_trade_record(supabase: Client, trade_id: str) -> TradeRecord:
    """Fetch a trade and its players from Supabase, return a TradeRecord.

    Args:
        supabase: Injected Supabase client.
        trade_id: The trade UUID to fetch.

    Returns:
        A fully populated TradeRecord.

    Raises:
        ValueError: If the trade is not found.
    """
    trade_result = (
        supabase.table("trades").select("*").eq("id", trade_id).single().execute()
    )
    if not trade_result.data:
        raise ValueError(f"Trade {trade_id} not found.")

    player_result = (
        supabase.table("trade_players").select("*").eq("trade_id", trade_id).execute()
    )

    return _row_to_record(trade_result.data, player_result.data or [])


def _fetch_member_roster_player_ids(
    supabase: Client, member_id: str, league_id: str
) -> frozenset[str]:
    """Fetch all player IDs currently on a member's active roster (not IR).

    IR players are excluded — a player on IR cannot be traded (they are
    not in the active roster and their slot_type is 'ir').

    Args:
        supabase: Injected Supabase client.
        member_id: The league member UUID.
        league_id: The league UUID (ensures cross-league isolation, KB-005 fix).

    Returns:
        frozenset of player UUIDs on the member's active roster.
    """
    result = (
        supabase.table("roster_slots")
        .select("player_id, rosters!inner(member_id, league_id)")
        .eq("rosters.member_id", member_id)
        .eq("rosters.league_id", league_id)
        .neq("slot_type", "ir")
        .execute()
    )
    return frozenset(row["player_id"] for row in (result.data or []))


def _fetch_has_unintegrated_ir_player(
    supabase: Client, member_id: str, league_id: str
) -> bool:
    """Check whether a manager has a recovered IR player not yet reintegrated.

    CDC §6.4: the manager has 1 week after recovery to reintegrate.
    After that, waivers and trades are blocked.

    A player is considered "unintegrated" when:
      - slot_type = 'ir' on their roster slot
      - player_availability.status = 'available' (recovered)
      - player_availability.injury_since + 7 days < today

    Args:
        supabase: Injected Supabase client.
        member_id: The league member UUID.
        league_id: The league UUID.

    Returns:
        True if at least one such player exists, False otherwise.
    """
    today = _today_utc()

    # Fetch all IR slot players for this member in this league.
    ir_result = (
        supabase.table("roster_slots")
        .select("player_id, rosters!inner(member_id, league_id)")
        .eq("rosters.member_id", member_id)
        .eq("rosters.league_id", league_id)
        .eq("slot_type", "ir")
        .execute()
    )

    if not ir_result.data:
        return False

    ir_player_ids = [row["player_id"] for row in ir_result.data]

    # Check availability status for each IR player.
    for player_id in ir_player_ids:
        avail_result = (
            supabase.table("player_availability")
            .select("status, injury_since")
            .eq("player_id", player_id)
            .maybe_single()
            .execute()
        )
        if not avail_result.data:
            continue

        avail = avail_result.data
        if avail["status"] != "available":
            # Still injured or suspended — not a blocking case.
            continue

        # Player has recovered. Check if the 1-week deadline has passed.
        if avail["injury_since"] is None:
            continue

        injury_since = date.fromisoformat(avail["injury_since"])
        days_since_recovery = (today - injury_since).days

        # CDC §6.4: 1 week (7 days) grace period after recovery.
        if days_since_recovery > 7:
            return True

    return False


def _fetch_window_context(supabase: Client, league_id: str) -> TradeWindowContext:
    """Build a TradeWindowContext from the league and competition data.

    Args:
        supabase: Injected Supabase client.
        league_id: The league UUID.

    Returns:
        A fully populated TradeWindowContext.

    Raises:
        ValueError: If the league or competition data is not found.
    """
    # Fetch league with its competition's round data.
    league_result = (
        supabase.table("leagues")
        .select(
            "id, trade_deadline, "
            "competitions!inner(id, "
            "competition_rounds(round_number, start_date, end_date, total_rounds))"
        )
        .eq("id", league_id)
        .single()
        .execute()
    )

    if not league_result.data:
        raise ValueError(f"League {league_id} not found.")

    league = league_result.data
    competition = league["competitions"]
    rounds = competition.get("competition_rounds", [])

    if not rounds:
        raise ValueError(f"No competition rounds found for league {league_id}.")

    today = _today_utc()

    # Determine the current round: the round whose window contains today,
    # or the last completed round if we are between rounds.
    current_round = 1
    total_rounds = rounds[0]["total_rounds"]

    for r in sorted(rounds, key=lambda x: x["round_number"]):
        round_start = date.fromisoformat(r["start_date"])
        round_end = date.fromisoformat(r["end_date"])
        if round_start <= today <= round_end:
            current_round = r["round_number"]
            break
        if today > round_end:
            current_round = r["round_number"]

    trade_deadline = date.fromisoformat(league["trade_deadline"])

    return TradeWindowContext(
        today=today,
        trade_deadline=trade_deadline,
        current_round=current_round,
        total_rounds=total_rounds,
    )


def _fetch_is_ghost_team(supabase: Client, member_id: str) -> bool:
    """Check whether a league member is a ghost team.

    Args:
        supabase: Injected Supabase client.
        member_id: The league member UUID.

    Returns:
        True if the member is a ghost team.
    """
    result = (
        supabase.table("league_members")
        .select("is_ghost_team")
        .eq("id", member_id)
        .single()
        .execute()
    )
    if not result.data:
        return False
    return bool(result.data["is_ghost_team"])


def _persist_new_trade(supabase: Client, record: TradeRecord) -> None:
    """Insert a new trade and its player entries into Supabase.

    Uses service role — bypasses RLS insert policy on trade_players.

    Args:
        supabase: Injected Supabase client (service role).
        record: The TradeRecord returned by propose_trade().
    """
    # Insert the trade row.
    supabase.table("trades").insert(
        {
            "id": record.trade_id,
            "league_id": record.league_id,
            "proposer_id": record.proposer_id,
            "receiver_id": record.receiver_id,
            "status": record.status.value,
            "veto_enabled": record.veto_enabled,
            "veto_deadline": None,
            "veto_reason": None,
            "veto_at": None,
            "created_at": record.created_at.isoformat(),
        }
    ).execute()

    # Insert all player entries.
    supabase.table("trade_players").insert(
        [
            {
                "id": str(uuid.uuid4()),
                "trade_id": record.trade_id,
                "player_id": p.player_id,
                "from_member_id": p.from_member_id,
                "to_member_id": p.to_member_id,
                # direction: 'out' from the from_member's perspective.
                "direction": "out",
                "member_id": p.from_member_id,
            }
            for p in record.players
        ]
    ).execute()


def _update_trade_status(
    supabase: Client,
    record: TradeRecord,
    completed_at: datetime | None = None,
) -> None:
    """Persist a trade status transition to Supabase.

    Args:
        supabase: Injected Supabase client (service role).
        record: The updated TradeRecord from the processor.
        completed_at: Timestamp to write into completed_at column, if applicable.
    """
    payload: dict = {
        "status": record.status.value,
        "veto_deadline": (
            record.veto_deadline.isoformat() if record.veto_deadline else None
        ),
        "veto_reason": record.veto_reason,
        "veto_at": record.veto_at.isoformat() if record.veto_at else None,
    }
    if completed_at is not None:
        payload["completed_at"] = completed_at.isoformat()

    supabase.table("trades").update(payload).eq("id", record.trade_id).execute()


def _apply_completed_trade(supabase: Client, record: TradeRecord) -> None:
    """Move players between rosters when a trade is COMPLETED.

    For each player entry, update the roster_slots table:
    reassign the player from the giving member's roster to the
    receiving member's roster.

    This is not atomic (KB-004 pattern) — a proper PostgreSQL RPC
    function should wrap this in Phase 4. Acceptable for V1.

    Args:
        supabase: Injected Supabase client (service role).
        record: A TradeRecord in COMPLETED status.
    """
    for player_entry in record.players:
        # Find the source roster (from_member in this league).
        from_roster = (
            supabase.table("rosters")
            .select("id")
            .eq("member_id", player_entry.from_member_id)
            .eq("league_id", record.league_id)
            .single()
            .execute()
        )
        to_roster = (
            supabase.table("rosters")
            .select("id")
            .eq("member_id", player_entry.to_member_id)
            .eq("league_id", record.league_id)
            .single()
            .execute()
        )

        if not from_roster.data or not to_roster.data:
            continue

        from_roster_id = from_roster.data["id"]
        to_roster_id = to_roster.data["id"]

        # Reassign the player slot to the receiving roster.
        supabase.table("roster_slots").update({"roster_id": to_roster_id}).eq(
            "roster_id", from_roster_id
        ).eq("player_id", player_entry.player_id).execute()


# ---------------------------------------------------------------------------
# Public service functions — called by the router
# ---------------------------------------------------------------------------


def create_trade(
    supabase: Client,
    league_id: str,
    proposer_member_id: str,
    receiver_member_id: str,
    proposer_player_ids: list[str],
    receiver_player_ids: list[str],
) -> TradeResponse:
    """Validate and create a new trade proposal.

    Fetches all required context from Supabase, builds the TradeProposal,
    calls propose_trade(), persists the result.

    Args:
        supabase: Injected Supabase client.
        league_id: The league UUID.
        proposer_member_id: The proposing manager's member UUID.
        receiver_member_id: The receiving manager's member UUID.
        proposer_player_ids: Player UUIDs the proposer is giving.
        receiver_player_ids: Player UUIDs the proposer wants in return.

    Returns:
        TradeResponse of the newly created PENDING trade.

    Raises:
        TradeValidationError subclasses: if any rule fails.
        ValueError: if league/member data is not found.
    """
    now = _now_utc()

    # Fetch all context needed for validation.
    window_ctx = _fetch_window_context(supabase, league_id)

    proposer_roster = _fetch_member_roster_player_ids(
        supabase, proposer_member_id, league_id
    )
    receiver_roster = _fetch_member_roster_player_ids(
        supabase, receiver_member_id, league_id
    )
    proposer_ir_block = _fetch_has_unintegrated_ir_player(
        supabase, proposer_member_id, league_id
    )
    receiver_ir_block = _fetch_has_unintegrated_ir_player(
        supabase, receiver_member_id, league_id
    )
    proposer_is_ghost = _fetch_is_ghost_team(supabase, proposer_member_id)
    receiver_is_ghost = _fetch_is_ghost_team(supabase, receiver_member_id)

    # Fetch league veto setting.
    league_result = (
        supabase.table("leagues")
        .select("settings")
        .eq("id", league_id)
        .single()
        .execute()
    )
    veto_enabled: bool = (
        league_result.data.get("settings", {}).get("veto_enabled", False)
        if league_result.data
        else False
    )

    # Build the proposal for the processor.
    proposal = TradeProposal(
        proposer=TradeParty(
            member_id=proposer_member_id,
            player_ids=frozenset(proposer_player_ids),
            is_ghost_team=proposer_is_ghost,
            roster_player_ids=proposer_roster,
            has_unintegrated_ir_player=proposer_ir_block,
        ),
        receiver=TradeParty(
            member_id=receiver_member_id,
            player_ids=frozenset(receiver_player_ids),
            is_ghost_team=receiver_is_ghost,
            roster_player_ids=receiver_roster,
            has_unintegrated_ir_player=receiver_ir_block,
        ),
        window_ctx=window_ctx,
    )

    # Call the processor — raises TradeValidationError on failure.
    trade_id = str(uuid.uuid4())
    record = propose_trade(
        proposal=proposal,
        trade_id=trade_id,
        league_id=league_id,
        veto_enabled=veto_enabled,
        now=now,
    )

    # Persist.
    _persist_new_trade(supabase, record)

    return _record_to_response(record)


def accept_trade_proposal(
    supabase: Client, trade_id: str, requester_member_id: str
) -> TradeResponse:
    """Receiver accepts a PENDING trade.

    Args:
        supabase: Injected Supabase client.
        trade_id: The trade UUID.
        requester_member_id: Must match trade.receiver_id.

    Returns:
        Updated TradeResponse (ACCEPTED or COMPLETED).

    Raises:
        TradeInvalidStatusError: Wrong status or wrong requester.
        ValueError: Trade not found.
    """
    now = _now_utc()
    record = _fetch_trade_record(supabase, trade_id)

    # Authorisation: only the receiver can accept.
    if requester_member_id != record.receiver_id:
        from trades.processor import TradeInvalidStatusError

        raise TradeInvalidStatusError(
            f"Only the receiver ({record.receiver_id}) can accept this trade."
        )

    updated = accept_trade(record, now)
    completed_at = now if updated.status == TradeStatus.COMPLETED else None
    _update_trade_status(supabase, updated, completed_at=completed_at)

    if updated.status == TradeStatus.COMPLETED:
        _apply_completed_trade(supabase, updated)

    return _record_to_response(updated, completed_at=completed_at)


def reject_trade_proposal(
    supabase: Client, trade_id: str, requester_member_id: str
) -> TradeResponse:
    """Receiver rejects a PENDING trade.

    Args:
        supabase: Injected Supabase client.
        trade_id: The trade UUID.
        requester_member_id: Must match trade.receiver_id.

    Returns:
        Updated TradeResponse in REJECTED status.
    """
    record = _fetch_trade_record(supabase, trade_id)

    if requester_member_id != record.receiver_id:
        from trades.processor import TradeInvalidStatusError

        raise TradeInvalidStatusError(
            f"Only the receiver ({record.receiver_id}) can reject this trade."
        )

    updated = reject_trade(record)
    _update_trade_status(supabase, updated)
    return _record_to_response(updated)


def cancel_trade_proposal(
    supabase: Client, trade_id: str, requester_member_id: str
) -> TradeResponse:
    """Proposer cancels their own PENDING trade.

    Args:
        supabase: Injected Supabase client.
        trade_id: The trade UUID.
        requester_member_id: Must match trade.proposer_id.

    Returns:
        Updated TradeResponse in CANCELLED status.
    """
    record = _fetch_trade_record(supabase, trade_id)
    updated = cancel_trade(record, requester_id=requester_member_id)
    _update_trade_status(supabase, updated)
    return _record_to_response(updated)


def veto_trade_proposal(
    supabase: Client,
    trade_id: str,
    commissioner_member_id: str,
    league_id: str,
    reason: str,
) -> TradeResponse:
    """Commissioner vetoes an ACCEPTED trade within the 24h window.

    Args:
        supabase: Injected Supabase client.
        trade_id: The trade UUID.
        commissioner_member_id: Must be the league commissioner.
        league_id: The league UUID (used to verify commissioner identity).
        reason: Mandatory free-text reason (CDC §9.2).

    Returns:
        Updated TradeResponse in VETOED status.
    """
    now = _now_utc()
    record = _fetch_trade_record(supabase, trade_id)

    # Fetch the league commissioner ID.
    league_result = (
        supabase.table("leagues")
        .select("commissioner_id")
        .eq("id", league_id)
        .single()
        .execute()
    )
    if not league_result.data:
        raise ValueError(f"League {league_id} not found.")

    league_commissioner_id: str = league_result.data["commissioner_id"]

    updated = commissioner_veto(
        record=record,
        commissioner_id=commissioner_member_id,
        league_commissioner_id=league_commissioner_id,
        reason=reason,
        now=now,
    )
    _update_trade_status(supabase, updated)
    return _record_to_response(updated)


def complete_expired_veto_trades(supabase: Client) -> int:
    """Complete all ACCEPTED trades whose veto deadline has expired.

    Called by a scheduled cron job (Coolify) — not triggered by a user action.
    Scans all ACCEPTED trades and completes those past their veto_deadline.

    Returns:
        Number of trades completed in this run.
    """
    now = _now_utc()

    # Fetch all ACCEPTED trades with an expired veto deadline.
    result = (
        supabase.table("trades")
        .select("id")
        .eq("status", TradeStatus.ACCEPTED.value)
        .lt("veto_deadline", now.isoformat())
        .execute()
    )

    if not result.data:
        return 0

    completed_count = 0
    for row in result.data:
        trade_id = row["id"]
        record = _fetch_trade_record(supabase, trade_id)
        updated = complete_trade(record, now)
        _update_trade_status(supabase, updated, completed_at=now)
        _apply_completed_trade(supabase, updated)
        completed_count += 1

    return completed_count


def get_trade(supabase: Client, trade_id: str) -> TradeResponse:
    """Fetch a single trade by ID.

    Args:
        supabase: Injected Supabase client.
        trade_id: The trade UUID.

    Returns:
        TradeResponse for the requested trade.

    Raises:
        ValueError: If the trade is not found.
    """
    record = _fetch_trade_record(supabase, trade_id)
    return _record_to_response(record)


def list_league_trades(
    supabase: Client,
    league_id: str,
    status: TradeStatus | None = None,
) -> TradeListResponse:
    """List all trades in a league, optionally filtered by status.

    Used for the trade log page (visible to all managers, CDC §9.2).

    Args:
        supabase: Injected Supabase client.
        league_id: The league UUID.
        status: Optional status filter.

    Returns:
        TradeListResponse with all matching trades.
    """
    query = (
        supabase.table("trades")
        .select("*")
        .eq("league_id", league_id)
        .order("created_at", desc=True)
    )
    if status is not None:
        query = query.eq("status", status.value)

    result = query.execute()
    trades = result.data or []

    responses: list[TradeResponse] = []
    for trade_row in trades:
        player_result = (
            supabase.table("trade_players")
            .select("*")
            .eq("trade_id", trade_row["id"])
            .execute()
        )
        record = _row_to_record(trade_row, player_result.data or [])
        completed_at_raw = trade_row.get("completed_at")
        completed_at = (
            datetime.fromisoformat(completed_at_raw).astimezone(timezone.utc)
            if completed_at_raw
            else None
        )
        responses.append(_record_to_response(record, completed_at=completed_at))

    return TradeListResponse(trades=responses, total=len(responses))
