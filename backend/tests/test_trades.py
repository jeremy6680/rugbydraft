"""Tests for the trade system — window, validation, and processor.

All tested modules are pure (no I/O) — no mocking required.
trade_service.py is covered by integration tests in Phase 4.

Run with:
    pytest backend/tests/test_trades.py -v
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from trades.processor import (
    TradeInvalidStatusError,
    TradeRecord,
    TradeStatus,
    TradeVetoNotEnabledError,
    TradeVetoReasonRequiredError,
    TradeVetoWindowExpiredError,
    accept_trade,
    cancel_trade,
    commissioner_veto,
    complete_trade,
    propose_trade,
    reject_trade,
)
from trades.validate_trade import (
    TradeDuplicatePlayerError,
    TradeFormatError,
    TradeGhostTeamError,
    TradeIRBlockError,
    TradeOwnershipError,
    TradeParty,
    TradeProposal,
    TradeSelfTradeError,
    TradeWindowClosedError,
    validate_trade,
)
from trades.window import (
    TradeWindowContext,
    is_trade_window_open,
    midseason_cutoff_round,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_now() -> datetime:
    """Fixed UTC datetime for all processor tests."""
    return datetime(2025, 2, 15, 12, 0, 0, tzinfo=timezone.utc)


def _make_window_ctx(
    *,
    today: date = date(2025, 2, 15),
    trade_deadline: date = date(2025, 3, 1),
    current_round: int = 2,
    total_rounds: int = 5,
) -> TradeWindowContext:
    """Build a TradeWindowContext with sensible defaults (window open)."""
    return TradeWindowContext(
        today=today,
        trade_deadline=trade_deadline,
        current_round=current_round,
        total_rounds=total_rounds,
    )


def _make_party(
    member_id: str = "member-a",
    player_ids: frozenset[str] | None = None,
    is_ghost_team: bool = False,
    roster_player_ids: frozenset[str] | None = None,
    has_unintegrated_ir_player: bool = False,
) -> TradeParty:
    """Build a TradeParty with sensible defaults."""
    if player_ids is None:
        player_ids = frozenset(["player-1"])
    if roster_player_ids is None:
        # By default the party owns the players they are giving away.
        roster_player_ids = player_ids
    return TradeParty(
        member_id=member_id,
        player_ids=player_ids,
        is_ghost_team=is_ghost_team,
        roster_player_ids=roster_player_ids,
        has_unintegrated_ir_player=has_unintegrated_ir_player,
    )


def _make_proposal(
    *,
    proposer: TradeParty | None = None,
    receiver: TradeParty | None = None,
    window_ctx: TradeWindowContext | None = None,
) -> TradeProposal:
    """Build a fully valid TradeProposal with sensible defaults."""
    return TradeProposal(
        proposer=proposer or _make_party("member-a", frozenset(["player-1"])),
        receiver=receiver or _make_party("member-b", frozenset(["player-2"])),
        window_ctx=window_ctx or _make_window_ctx(),
    )


def _make_pending_record(
    *,
    veto_enabled: bool = False,
    proposer_id: str = "member-a",
    receiver_id: str = "member-b",
) -> TradeRecord:
    """Create a PENDING TradeRecord via propose_trade()."""
    proposal = _make_proposal(
        proposer=_make_party(proposer_id, frozenset(["player-1"])),
        receiver=_make_party(receiver_id, frozenset(["player-2"])),
    )
    return propose_trade(
        proposal=proposal,
        trade_id="trade-001",
        league_id="league-001",
        veto_enabled=veto_enabled,
        now=_make_now(),
    )


# ---------------------------------------------------------------------------
# TestTradeWindow
# ---------------------------------------------------------------------------


class TestMidseasonCutoffRound:
    """Tests for midseason_cutoff_round()."""

    def test_six_nations_five_rounds(self) -> None:
        """Six Nations: 5 rounds → cutoff at round 3."""
        assert midseason_cutoff_round(5) == 3

    def test_rugby_championship_four_rounds(self) -> None:
        """Rugby Championship: 4 rounds → cutoff at round 2."""
        assert midseason_cutoff_round(4) == 2

    def test_top14_regular_season(self) -> None:
        """Top 14: 26 rounds → cutoff at round 13."""
        assert midseason_cutoff_round(26) == 13

    def test_odd_total_rounds(self) -> None:
        """7 rounds → ceil(7/2) = 4."""
        assert midseason_cutoff_round(7) == 4

    def test_even_total_rounds(self) -> None:
        """6 rounds → ceil(6/2) = 3."""
        assert midseason_cutoff_round(6) == 3

    def test_single_round(self) -> None:
        """Edge case: 1-round competition → cutoff at round 1."""
        assert midseason_cutoff_round(1) == 1


class TestIsTradeWindowOpen:
    """Tests for is_trade_window_open()."""

    def test_window_open(self) -> None:
        """Happy path: date and round both within bounds."""
        ctx = _make_window_ctx()
        open_, reason = is_trade_window_open(ctx)
        assert open_ is True
        assert reason == ""

    def test_closed_by_date(self) -> None:
        """Deadline passed: window closed regardless of round."""
        ctx = _make_window_ctx(
            today=date(2025, 3, 5),
            trade_deadline=date(2025, 3, 1),
            current_round=2,
        )
        open_, reason = is_trade_window_open(ctx)
        assert open_ is False
        assert "deadline" in reason

    def test_closed_on_deadline_day(self) -> None:
        """Deadline day itself: window closed (today >= deadline)."""
        ctx = _make_window_ctx(
            today=date(2025, 3, 1),
            trade_deadline=date(2025, 3, 1),
        )
        open_, reason = is_trade_window_open(ctx)
        assert open_ is False

    def test_closed_by_round(self) -> None:
        """Round past mid-season: window closed regardless of date."""
        ctx = _make_window_ctx(
            today=date(2025, 2, 15),
            trade_deadline=date(2025, 3, 1),
            current_round=4,  # ceil(5/2) = 3, so round 4 is past cutoff
            total_rounds=5,
        )
        open_, reason = is_trade_window_open(ctx)
        assert open_ is False
        assert "mid-season" in reason

    def test_open_at_cutoff_round(self) -> None:
        """Round exactly at cutoff: window still open."""
        ctx = _make_window_ctx(
            current_round=3,  # ceil(5/2) = 3 — last allowed round
            total_rounds=5,
        )
        open_, _ = is_trade_window_open(ctx)
        assert open_ is True

    def test_date_check_takes_priority(self) -> None:
        """Date check runs first — even if round is valid, deadline failure wins."""
        ctx = _make_window_ctx(
            today=date(2025, 4, 1),
            trade_deadline=date(2025, 3, 1),
            current_round=1,  # round is fine
        )
        open_, reason = is_trade_window_open(ctx)
        assert open_ is False
        assert "deadline" in reason


# ---------------------------------------------------------------------------
# TestValidateTrade — one class per rule
# ---------------------------------------------------------------------------


class TestRule1Window:
    """Rule 1 — trade window must be open."""

    def test_raises_when_window_closed_by_date(self) -> None:
        ctx = _make_window_ctx(
            today=date(2025, 4, 1),
            trade_deadline=date(2025, 3, 1),
        )
        with pytest.raises(TradeWindowClosedError):
            validate_trade(_make_proposal(window_ctx=ctx))

    def test_raises_when_window_closed_by_round(self) -> None:
        ctx = _make_window_ctx(current_round=4, total_rounds=5)
        with pytest.raises(TradeWindowClosedError):
            validate_trade(_make_proposal(window_ctx=ctx))

    def test_passes_when_window_open(self) -> None:
        validate_trade(_make_proposal())  # no exception


class TestRule2SelfTrade:
    """Rule 2 — proposer cannot trade with themselves."""

    def test_raises_on_self_trade(self) -> None:
        proposal = _make_proposal(
            proposer=_make_party("member-a", frozenset(["player-1"])),
            receiver=_make_party("member-a", frozenset(["player-2"])),
        )
        with pytest.raises(TradeSelfTradeError):
            validate_trade(proposal)

    def test_passes_different_members(self) -> None:
        validate_trade(_make_proposal())  # no exception


class TestRule3GhostTeam:
    """Rule 3 — ghost teams cannot trade."""

    def test_raises_when_proposer_is_ghost(self) -> None:
        proposal = _make_proposal(
            proposer=_make_party("ghost-a", is_ghost_team=True),
        )
        with pytest.raises(TradeGhostTeamError):
            validate_trade(proposal)

    def test_raises_when_receiver_is_ghost(self) -> None:
        proposal = _make_proposal(
            receiver=_make_party("ghost-b", is_ghost_team=True),
        )
        with pytest.raises(TradeGhostTeamError):
            validate_trade(proposal)

    def test_passes_no_ghost(self) -> None:
        validate_trade(_make_proposal())  # no exception


class TestRule4Format:
    """Rule 4 — each side sends 1, 2, or 3 players."""

    @pytest.mark.parametrize("count", [1, 2, 3])
    def test_valid_proposer_counts(self, count: int) -> None:
        ids = frozenset(f"p-{i}" for i in range(count))
        proposal = _make_proposal(
            proposer=_make_party("member-a", ids),
        )
        validate_trade(proposal)  # no exception

    @pytest.mark.parametrize("count", [1, 2, 3])
    def test_valid_receiver_counts(self, count: int) -> None:
        ids = frozenset(f"r-{i}" for i in range(count))
        proposal = _make_proposal(
            receiver=_make_party("member-b", ids),
        )
        validate_trade(proposal)  # no exception

    def test_raises_when_proposer_sends_zero(self) -> None:
        proposal = _make_proposal(
            proposer=_make_party("member-a", frozenset()),
        )
        with pytest.raises(TradeFormatError):
            validate_trade(proposal)

    def test_raises_when_proposer_sends_four(self) -> None:
        ids = frozenset(["p1", "p2", "p3", "p4"])
        proposal = _make_proposal(
            proposer=_make_party("member-a", ids, roster_player_ids=ids),
        )
        with pytest.raises(TradeFormatError):
            validate_trade(proposal)

    def test_raises_when_receiver_sends_four(self) -> None:
        ids = frozenset(["r1", "r2", "r3", "r4"])
        proposal = _make_proposal(
            receiver=_make_party("member-b", ids, roster_player_ids=ids),
        )
        with pytest.raises(TradeFormatError):
            validate_trade(proposal)

    def test_valid_2v3_format(self) -> None:
        """Asymmetric trade — 2 players for 3."""
        p_ids = frozenset(["p1", "p2"])
        r_ids = frozenset(["r1", "r2", "r3"])
        proposal = _make_proposal(
            proposer=_make_party("member-a", p_ids, roster_player_ids=p_ids),
            receiver=_make_party("member-b", r_ids, roster_player_ids=r_ids),
        )
        validate_trade(proposal)  # no exception


class TestRule5Ownership:
    """Rule 5 — players must belong to the giving party."""

    def test_raises_when_proposer_does_not_own_player(self) -> None:
        proposal = _make_proposal(
            proposer=_make_party(
                "member-a",
                player_ids=frozenset(["player-x"]),
                roster_player_ids=frozenset(["player-other"]),  # doesn't own x
            ),
        )
        with pytest.raises(TradeOwnershipError):
            validate_trade(proposal)

    def test_raises_when_receiver_does_not_own_player(self) -> None:
        proposal = _make_proposal(
            receiver=_make_party(
                "member-b",
                player_ids=frozenset(["player-y"]),
                roster_player_ids=frozenset(["player-other"]),
            ),
        )
        with pytest.raises(TradeOwnershipError):
            validate_trade(proposal)

    def test_passes_when_both_own_their_players(self) -> None:
        validate_trade(_make_proposal())  # no exception


class TestRule6Duplicates:
    """Rule 6 — same player cannot appear on both sides."""

    def test_raises_when_same_player_both_sides(self) -> None:
        shared = frozenset(["player-shared"])
        proposal = _make_proposal(
            proposer=_make_party("member-a", shared, roster_player_ids=shared),
            receiver=_make_party("member-b", shared, roster_player_ids=shared),
        )
        with pytest.raises(TradeDuplicatePlayerError):
            validate_trade(proposal)

    def test_passes_no_overlap(self) -> None:
        validate_trade(_make_proposal())  # no exception


class TestRule7IRBlock:
    """Rule 7 — IR block applies to both parties."""

    def test_raises_when_proposer_has_ir_block(self) -> None:
        proposal = _make_proposal(
            proposer=_make_party("member-a", has_unintegrated_ir_player=True),
        )
        with pytest.raises(TradeIRBlockError):
            validate_trade(proposal)

    def test_raises_when_receiver_has_ir_block(self) -> None:
        proposal = _make_proposal(
            receiver=_make_party(
                "member-b",
                player_ids=frozenset(["player-2"]),  # différent de player-1
                has_unintegrated_ir_player=True,
            ),
        )
        with pytest.raises(TradeIRBlockError):
            validate_trade(proposal)

    def test_passes_no_ir_block(self) -> None:
        validate_trade(_make_proposal())  # no exception


# ---------------------------------------------------------------------------
# TestTradeProcessor
# ---------------------------------------------------------------------------


class TestProposeTrace:
    """Tests for propose_trade()."""

    def test_creates_pending_record(self) -> None:
        record = _make_pending_record()
        assert record.status == TradeStatus.PENDING
        assert record.trade_id == "trade-001"
        assert record.proposer_id == "member-a"
        assert record.receiver_id == "member-b"

    def test_player_entries_correct(self) -> None:
        record = _make_pending_record()
        assert len(record.players) == 2
        from_a = next(p for p in record.players if p.from_member_id == "member-a")
        from_b = next(p for p in record.players if p.from_member_id == "member-b")
        assert from_a.player_id == "player-1"
        assert from_a.to_member_id == "member-b"
        assert from_b.player_id == "player-2"
        assert from_b.to_member_id == "member-a"

    def test_veto_fields_none_on_creation(self) -> None:
        record = _make_pending_record(veto_enabled=True)
        assert record.veto_deadline is None
        assert record.veto_reason is None
        assert record.veto_at is None

    def test_validation_error_propagates(self) -> None:
        """propose_trade() re-raises validate_trade() errors."""
        closed_ctx = _make_window_ctx(current_round=4, total_rounds=5)
        proposal = _make_proposal(window_ctx=closed_ctx)
        with pytest.raises(TradeWindowClosedError):
            propose_trade(
                proposal=proposal,
                trade_id="t-001",
                league_id="l-001",
                veto_enabled=False,
                now=_make_now(),
            )


class TestAcceptTrade:
    """Tests for accept_trade()."""

    def test_accept_without_veto_completes_immediately(self) -> None:
        record = _make_pending_record(veto_enabled=False)
        updated = accept_trade(record, _make_now())
        assert updated.status == TradeStatus.COMPLETED
        assert updated.veto_deadline is None

    def test_accept_with_veto_opens_window(self) -> None:
        now = _make_now()
        record = _make_pending_record(veto_enabled=True)
        updated = accept_trade(record, now)
        assert updated.status == TradeStatus.ACCEPTED
        assert updated.veto_deadline == now + timedelta(hours=24)

    def test_raises_if_not_pending(self) -> None:
        record = _make_pending_record()
        rejected = reject_trade(record)
        with pytest.raises(TradeInvalidStatusError):
            accept_trade(rejected, _make_now())


class TestRejectTrade:
    """Tests for reject_trade()."""

    def test_reject_pending_trade(self) -> None:
        record = _make_pending_record()
        updated = reject_trade(record)
        assert updated.status == TradeStatus.REJECTED

    def test_raises_if_not_pending(self) -> None:
        record = _make_pending_record()
        cancelled = cancel_trade(record, requester_id="member-a")
        with pytest.raises(TradeInvalidStatusError):
            reject_trade(cancelled)


class TestCancelTrade:
    """Tests for cancel_trade()."""

    def test_proposer_can_cancel(self) -> None:
        record = _make_pending_record()
        updated = cancel_trade(record, requester_id="member-a")
        assert updated.status == TradeStatus.CANCELLED

    def test_receiver_cannot_cancel(self) -> None:
        record = _make_pending_record()
        with pytest.raises(TradeInvalidStatusError):
            cancel_trade(record, requester_id="member-b")

    def test_raises_if_not_pending(self) -> None:
        record = _make_pending_record()
        rejected = reject_trade(record)
        with pytest.raises(TradeInvalidStatusError):
            cancel_trade(rejected, requester_id="member-a")


class TestCommissionerVeto:
    """Tests for commissioner_veto()."""

    def _accepted_record(self) -> tuple[TradeRecord, datetime]:
        now = _make_now()
        record = _make_pending_record(veto_enabled=True)
        accepted = accept_trade(record, now)
        return accepted, now

    def test_valid_veto(self) -> None:
        accepted, now = self._accepted_record()
        vetoed = commissioner_veto(
            record=accepted,
            commissioner_id="commissioner-1",
            league_commissioner_id="commissioner-1",
            reason="Trade is clearly unbalanced.",
            now=now,
        )
        assert vetoed.status == TradeStatus.VETOED
        assert vetoed.veto_reason == "Trade is clearly unbalanced."
        assert vetoed.veto_at == now

    def test_raises_when_veto_not_enabled(self) -> None:
        record = _make_pending_record(veto_enabled=False)
        # accept() without veto → COMPLETED immediately, so we can't test the
        # veto_enabled guard via the normal flow. Manually construct an ACCEPTED
        # record with veto_enabled=False to hit the guard directly.
        from dataclasses import replace as dc_replace

        fake_accepted = dc_replace(record, status=TradeStatus.ACCEPTED)
        with pytest.raises(TradeVetoNotEnabledError):
            commissioner_veto(
                record=fake_accepted,
                commissioner_id="commissioner-1",
                league_commissioner_id="commissioner-1",
                reason="Reason.",
                now=_make_now(),
            )

    def test_raises_when_not_commissioner(self) -> None:
        accepted, now = self._accepted_record()
        with pytest.raises(TradeInvalidStatusError):
            commissioner_veto(
                record=accepted,
                commissioner_id="some-other-member",
                league_commissioner_id="commissioner-1",
                reason="Reason.",
                now=now,
            )

    def test_raises_when_reason_is_blank(self) -> None:
        accepted, now = self._accepted_record()
        with pytest.raises(TradeVetoReasonRequiredError):
            commissioner_veto(
                record=accepted,
                commissioner_id="commissioner-1",
                league_commissioner_id="commissioner-1",
                reason="   ",
                now=now,
            )

    def test_raises_when_veto_window_expired(self) -> None:
        accepted, now = self._accepted_record()
        # Move time past the 24h deadline.
        future = now + timedelta(hours=25)
        with pytest.raises(TradeVetoWindowExpiredError):
            commissioner_veto(
                record=accepted,
                commissioner_id="commissioner-1",
                league_commissioner_id="commissioner-1",
                reason="Reason.",
                now=future,
            )

    def test_raises_when_trade_not_accepted(self) -> None:
        record = _make_pending_record(veto_enabled=True)
        with pytest.raises(TradeInvalidStatusError):
            commissioner_veto(
                record=record,  # still PENDING
                commissioner_id="commissioner-1",
                league_commissioner_id="commissioner-1",
                reason="Reason.",
                now=_make_now(),
            )


class TestCompleteTrade:
    """Tests for complete_trade()."""

    def test_completes_after_veto_window(self) -> None:
        now = _make_now()
        record = _make_pending_record(veto_enabled=True)
        accepted = accept_trade(record, now)
        # Move past the 24h window.
        future = now + timedelta(hours=25)
        completed = complete_trade(accepted, future)
        assert completed.status == TradeStatus.COMPLETED

    def test_raises_if_veto_window_not_expired(self) -> None:
        now = _make_now()
        record = _make_pending_record(veto_enabled=True)
        accepted = accept_trade(record, now)
        # Try to complete while still within the window.
        too_early = now + timedelta(hours=12)
        with pytest.raises(TradeVetoWindowExpiredError):
            complete_trade(accepted, too_early)

    def test_raises_if_not_accepted(self) -> None:
        record = _make_pending_record()
        with pytest.raises(TradeInvalidStatusError):
            complete_trade(record, _make_now())
