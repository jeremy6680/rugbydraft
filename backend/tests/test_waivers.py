"""Tests for the waiver system — pure logic only.

Covers:
    - waivers/window.py       — waiver window open/closed
    - waivers/priority.py     — priority ordering and tiebreakers
    - waivers/validate_claim.py — all 5 business rules
    - waivers/processor.py    — full cycle processing scenarios

No database access. All tests are synchronous (pure functions only).
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from waivers.priority import (
    ManagerStanding,
    WaiverPrioritySlot,
    compute_waiver_priority,
    get_member_priority,
)
from waivers.processor import (
    ClaimStatus,
    CycleResult,
    PendingClaim,
    process_waiver_cycle,
)
from waivers.validate_claim import (
    DropPlayerNotOwnedError,
    GhostTeamCannotClaimError,
    IRBlockingRuleError,
    PlayerNotFreeError,
    WaiverClaimRequest,
    WaiverWindowClosedError,
    validate_claim,
)
from waivers.window import is_waiver_window_open

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TZ = ZoneInfo("Europe/Paris")

# Reference datetimes — fixed, never depend on real wall clock
TUESDAY_10H = datetime(2026, 3, 24, 10, 0, tzinfo=TZ)  # window open
TUESDAY_06H = datetime(2026, 3, 24, 6, 59, tzinfo=TZ)  # window closed (before open)
WEDNESDAY_22H = datetime(2026, 3, 25, 22, 0, tzinfo=TZ)  # window open
THURSDAY_00H = datetime(2026, 3, 26, 0, 0, tzinfo=TZ)  # window closed
MONDAY_10H = datetime(2026, 3, 23, 10, 0, tzinfo=TZ)  # window closed


def make_claim(**overrides) -> WaiverClaimRequest:
    """Return a valid WaiverClaimRequest with sensible defaults."""
    defaults = dict(
        member_id="member-1",
        league_id="league-1",
        add_player_id="player-X",
        drop_player_id="player-Y",
        is_ghost_team=False,
        has_unintegrated_recovered_ir_player=False,
        add_player_is_free=True,
        drop_player_is_owned=True,
    )
    return WaiverClaimRequest(**{**defaults, **overrides})


def make_pending(
    waiver_id: str,
    member_id: str,
    add_player_id: str,
    member_priority: int,
    claim_rank: int = 1,
    drop_player_id: str | None = None,
) -> PendingClaim:
    """Return a PendingClaim with the given fields."""
    return PendingClaim(
        waiver_id=waiver_id,
        member_id=member_id,
        add_player_id=add_player_id,
        drop_player_id=drop_player_id,
        member_priority=member_priority,
        claim_rank=claim_rank,
    )


# ---------------------------------------------------------------------------
# TestWaiverWindow
# ---------------------------------------------------------------------------


class TestWaiverWindow:
    """Tests for waivers/window.py — is_waiver_window_open()."""

    def test_tuesday_morning_is_open(self):
        assert is_waiver_window_open(TUESDAY_10H) is True

    def test_tuesday_before_open_time_is_closed(self):
        assert is_waiver_window_open(TUESDAY_06H) is False

    def test_wednesday_evening_is_open(self):
        assert is_waiver_window_open(WEDNESDAY_22H) is True

    def test_thursday_midnight_is_closed(self):
        assert is_waiver_window_open(THURSDAY_00H) is False

    def test_monday_is_closed(self):
        assert is_waiver_window_open(MONDAY_10H) is False

    def test_tuesday_exactly_at_open_time_is_open(self):
        exactly_open = datetime(2026, 3, 24, 7, 0, 0, tzinfo=TZ)
        assert is_waiver_window_open(exactly_open) is True

    def test_wednesday_at_close_time_is_open(self):
        exactly_close = datetime(2026, 3, 25, 23, 59, 59, tzinfo=TZ)
        assert is_waiver_window_open(exactly_close) is True

    def test_utc_datetime_is_converted_correctly(self):
        """A UTC datetime passed in should be converted to Europe/Paris."""
        from datetime import timezone

        # Tuesday 10:00 Paris = Tuesday 08:00 UTC
        utc_tuesday = datetime(2026, 3, 24, 8, 0, tzinfo=timezone.utc)
        assert is_waiver_window_open(utc_tuesday) is True


# ---------------------------------------------------------------------------
# TestWaiverPriority
# ---------------------------------------------------------------------------


class TestWaiverPriority:
    """Tests for waivers/priority.py — compute_waiver_priority()."""

    def test_worst_ranked_manager_gets_priority_one(self):
        standings = [
            ManagerStanding("A", rank=1, season_total_points=100.0),
            ManagerStanding("B", rank=2, season_total_points=80.0),
        ]
        result = compute_waiver_priority(standings)
        assert result[0].member_id == "B"
        assert result[0].priority == 1

    def test_four_managers_correct_order(self):
        standings = [
            ManagerStanding("A", rank=1, season_total_points=120.0),
            ManagerStanding("B", rank=3, season_total_points=80.0),
            ManagerStanding("C", rank=2, season_total_points=95.0),
            ManagerStanding("D", rank=3, season_total_points=75.0),
        ]
        result = compute_waiver_priority(standings)
        ids = [s.member_id for s in result]
        assert ids == ["D", "B", "C", "A"]

    def test_tiebreaker_fewer_points_wins(self):
        """Same rank — fewer points gets higher priority."""
        standings = [
            ManagerStanding("X", rank=2, season_total_points=90.0),
            ManagerStanding("Y", rank=2, season_total_points=70.0),
        ]
        result = compute_waiver_priority(standings)
        assert result[0].member_id == "Y"

    def test_priority_numbers_are_one_based(self):
        standings = [
            ManagerStanding("A", rank=1, season_total_points=100.0),
            ManagerStanding("B", rank=2, season_total_points=80.0),
            ManagerStanding("C", rank=3, season_total_points=60.0),
        ]
        result = compute_waiver_priority(standings)
        priorities = [s.priority for s in result]
        assert priorities == [1, 2, 3]

    def test_empty_standings_returns_empty_list(self):
        assert compute_waiver_priority([]) == []

    def test_single_manager(self):
        standings = [ManagerStanding("solo", rank=1, season_total_points=50.0)]
        result = compute_waiver_priority(standings)
        assert len(result) == 1
        assert result[0].priority == 1
        assert result[0].member_id == "solo"

    def test_get_member_priority_found(self):
        slots = [
            WaiverPrioritySlot(priority=1, member_id="D"),
            WaiverPrioritySlot(priority=2, member_id="C"),
        ]
        assert get_member_priority("D", slots) == 1
        assert get_member_priority("C", slots) == 2

    def test_get_member_priority_not_found_returns_last_plus_one(self):
        slots = [WaiverPrioritySlot(priority=1, member_id="A")]
        assert get_member_priority("unknown", slots) == 2


# ---------------------------------------------------------------------------
# TestValidateClaim
# ---------------------------------------------------------------------------


class TestValidateClaim:
    """Tests for waivers/validate_claim.py — all 5 business rules."""

    def test_valid_claim_passes(self):
        validate_claim(make_claim(), now=TUESDAY_10H)  # no exception

    def test_closed_window_raises(self):
        with pytest.raises(WaiverWindowClosedError):
            validate_claim(make_claim(), now=MONDAY_10H)

    def test_ghost_team_raises(self):
        with pytest.raises(GhostTeamCannotClaimError):
            validate_claim(make_claim(is_ghost_team=True), now=TUESDAY_10H)

    def test_ir_blocking_rule_raises(self):
        with pytest.raises(IRBlockingRuleError):
            validate_claim(
                make_claim(has_unintegrated_recovered_ir_player=True),
                now=TUESDAY_10H,
            )

    def test_player_not_free_raises(self):
        with pytest.raises(PlayerNotFreeError):
            validate_claim(make_claim(add_player_is_free=False), now=TUESDAY_10H)

    def test_drop_player_not_owned_raises(self):
        with pytest.raises(DropPlayerNotOwnedError):
            validate_claim(make_claim(drop_player_is_owned=False), now=TUESDAY_10H)

    def test_no_drop_skips_ownership_check(self):
        """drop_player_id=None — ownership flag is irrelevant."""
        validate_claim(
            make_claim(drop_player_id=None, drop_player_is_owned=False),
            now=TUESDAY_10H,
        )  # no exception

    def test_window_check_runs_before_ghost_check(self):
        """Closed window should be raised even for ghost teams (fail-fast order)."""
        with pytest.raises(WaiverWindowClosedError):
            validate_claim(make_claim(is_ghost_team=True), now=MONDAY_10H)

    def test_ir_block_runs_before_player_free_check(self):
        """IR block should be raised before player availability check."""
        with pytest.raises(IRBlockingRuleError):
            validate_claim(
                make_claim(
                    has_unintegrated_recovered_ir_player=True,
                    add_player_is_free=False,
                ),
                now=TUESDAY_10H,
            )


# ---------------------------------------------------------------------------
# TestProcessWaiverCycle
# ---------------------------------------------------------------------------


class TestProcessWaiverCycle:
    """Tests for waivers/processor.py — process_waiver_cycle()."""

    def test_empty_claims_returns_empty_result(self):
        result = process_waiver_cycle([], free_player_ids={"player-X"})
        assert isinstance(result, CycleResult)
        assert result.granted_count == 0
        assert len(result.results) == 0

    def test_single_claim_granted(self):
        claims = [make_pending("w1", "M1", "player-X", member_priority=1)]
        result = process_waiver_cycle(claims, free_player_ids={"player-X"})
        assert result.granted_count == 1
        assert result.results[0].status == ClaimStatus.GRANTED

    def test_higher_priority_wins_contention(self):
        """D (priority 1) and B (priority 2) both want player-X. D wins."""
        claims = [
            make_pending("w1", "D", "player-X", member_priority=1),
            make_pending("w2", "B", "player-X", member_priority=2),
        ]
        result = process_waiver_cycle(claims, free_player_ids={"player-X"})
        by_id = {r.waiver_id: r for r in result.results}
        assert by_id["w1"].status == ClaimStatus.GRANTED
        assert by_id["w2"].status == ClaimStatus.DENIED

    def test_one_player_per_manager_per_cycle(self):
        """Manager gets rank-1 claim — rank-2 is skipped."""
        claims = [
            make_pending("w1", "M1", "player-X", member_priority=1, claim_rank=1),
            make_pending("w2", "M1", "player-Y", member_priority=1, claim_rank=2),
        ]
        result = process_waiver_cycle(claims, free_player_ids={"player-X", "player-Y"})
        by_id = {r.waiver_id: r for r in result.results}
        assert by_id["w1"].status == ClaimStatus.GRANTED
        assert by_id["w2"].status == ClaimStatus.SKIPPED

    def test_fallback_to_second_choice_after_denial(self):
        """B wants player-X (rank 1, taken by D) then player-Y (rank 2, free). B gets Y."""
        claims = [
            make_pending("w1", "D", "player-X", member_priority=1, claim_rank=1),
            make_pending("w2", "B", "player-X", member_priority=2, claim_rank=1),
            make_pending("w3", "B", "player-Y", member_priority=2, claim_rank=2),
        ]
        result = process_waiver_cycle(claims, free_player_ids={"player-X", "player-Y"})
        by_id = {r.waiver_id: r for r in result.results}
        assert by_id["w1"].status == ClaimStatus.GRANTED
        assert by_id["w2"].status == ClaimStatus.DENIED
        assert by_id["w3"].status == ClaimStatus.GRANTED

    def test_player_unavailable_from_start(self):
        """Player not in free_player_ids — claim is denied immediately."""
        claims = [make_pending("w1", "M1", "player-X", member_priority=1)]
        result = process_waiver_cycle(claims, free_player_ids=set())
        assert result.results[0].status == ClaimStatus.DENIED

    def test_free_player_ids_not_mutated(self):
        """The original free_player_ids set must not be modified."""
        free = {"player-X", "player-Y"}
        original = set(free)
        claims = [make_pending("w1", "M1", "player-X", member_priority=1)]
        process_waiver_cycle(claims, free_player_ids=free)
        assert free == original

    def test_counts_are_correct(self):
        """granted + denied + skipped counts match individual results."""
        claims = [
            make_pending("w1", "D", "player-X", member_priority=1, claim_rank=1),
            make_pending(
                "w2", "D", "player-Y", member_priority=1, claim_rank=2
            ),  # skipped
            make_pending(
                "w3", "B", "player-X", member_priority=2, claim_rank=1
            ),  # denied
            make_pending(
                "w4", "B", "player-Y", member_priority=2, claim_rank=2
            ),  # denied (Y taken? no—D skipped Y)
        ]
        # D gets player-X (rank 1), player-Y claim skipped.
        # B wants player-X (denied), then player-Y (granted — D didn't take it).
        result = process_waiver_cycle(claims, free_player_ids={"player-X", "player-Y"})
        assert result.granted_count == 2  # D gets X, B gets Y
        assert result.denied_count == 1  # B denied on X
        assert result.skipped_count == 1  # D skipped on Y
