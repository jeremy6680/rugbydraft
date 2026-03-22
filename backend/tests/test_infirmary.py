"""
Tests for infirmary business rules (ir_rules.py).

All tests are pure — no database, no HTTP, no side effects.
Coverage: capacity validation, deadline calculation, overdue detection,
reintegration validation, get_overdue_ir_slots filtering.
"""

from datetime import datetime, timedelta, timezone

import pytest

from infirmary.ir_rules import (
    IR_REINTEGRATION_DEADLINE_DAYS,
    MAX_IR_SLOTS,
    IRCapacityError,
    IRError,
    IRPlayerAlreadyInIRError,
    IRPlayerNotRecoveredError,
    IRSlotSnapshot,
    calculate_recovery_deadline,
    get_overdue_ir_slots,
    is_reintegration_overdue,
    validate_ir_placement,
    validate_ir_reintegration,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UTC = timezone.utc
NOW = datetime(2026, 3, 22, 9, 0, tzinfo=UTC)


def _snapshot(
    current: list[str] | None = None,
    recovered: list[str] | None = None,
    roster_id: str = "roster-001",
) -> IRSlotSnapshot:
    """Build an IRSlotSnapshot with sensible defaults."""
    return IRSlotSnapshot(
        roster_id=roster_id,
        current_ir_player_ids=set(current or []),
        recovered_player_ids=set(recovered or []),
    )


# ---------------------------------------------------------------------------
# calculate_recovery_deadline
# ---------------------------------------------------------------------------


class TestCalculateRecoveryDeadline:
    def test_adds_seven_days(self) -> None:
        recovery = datetime(2026, 3, 22, 9, 0, tzinfo=UTC)
        deadline = calculate_recovery_deadline(recovery)
        assert deadline == datetime(2026, 3, 29, 9, 0, tzinfo=UTC)

    def test_uses_constant_not_hardcoded(self) -> None:
        """Deadline must use IR_REINTEGRATION_DEADLINE_DAYS, not a magic number."""
        recovery = datetime(2026, 1, 1, tzinfo=UTC)
        deadline = calculate_recovery_deadline(recovery)
        assert deadline == recovery + timedelta(days=IR_REINTEGRATION_DEADLINE_DAYS)

    def test_naive_datetime_treated_as_utc(self) -> None:
        naive = datetime(2026, 3, 22, 9, 0)  # no tzinfo
        deadline = calculate_recovery_deadline(naive)
        assert deadline.tzinfo == UTC

    def test_returns_utc_aware(self) -> None:
        recovery = datetime(2026, 3, 22, tzinfo=UTC)
        deadline = calculate_recovery_deadline(recovery)
        assert deadline.tzinfo is not None


# ---------------------------------------------------------------------------
# is_reintegration_overdue
# ---------------------------------------------------------------------------


class TestIsReintegrationOverdue:
    def test_overdue_when_now_after_deadline(self) -> None:
        deadline = NOW
        assert is_reintegration_overdue(deadline, now=NOW + timedelta(seconds=1))

    def test_not_overdue_when_now_before_deadline(self) -> None:
        deadline = NOW
        assert not is_reintegration_overdue(deadline, now=NOW - timedelta(seconds=1))

    def test_not_overdue_exactly_at_deadline(self) -> None:
        """Boundary: now == deadline is NOT overdue (strict greater than)."""
        assert not is_reintegration_overdue(NOW, now=NOW)

    def test_naive_deadline_treated_as_utc(self) -> None:
        naive_deadline = datetime(2026, 3, 22, 9, 0)
        aware_now = datetime(2026, 3, 22, 9, 0, 1, tzinfo=UTC)
        assert is_reintegration_overdue(naive_deadline, now=aware_now)

    def test_naive_now_treated_as_utc(self) -> None:
        aware_deadline = datetime(2026, 3, 22, 9, 0, tzinfo=UTC)
        naive_now = datetime(2026, 3, 22, 9, 0, 1)
        assert is_reintegration_overdue(aware_deadline, now=naive_now)


# ---------------------------------------------------------------------------
# validate_ir_placement
# ---------------------------------------------------------------------------


class TestValidateIRPlacement:
    def test_valid_placement_empty_ir(self) -> None:
        """No exception when IR is empty."""
        validate_ir_placement("player-A", _snapshot())

    def test_valid_placement_two_slots_used(self) -> None:
        """No exception when 2/3 slots used."""
        snap = _snapshot(current=["player-B", "player-C"])
        validate_ir_placement("player-A", snap)

    def test_raises_when_player_already_in_ir(self) -> None:
        snap = _snapshot(current=["player-A"])
        with pytest.raises(IRPlayerAlreadyInIRError) as exc_info:
            validate_ir_placement("player-A", snap)
        assert exc_info.value.code == "ir_player_already_in_ir"

    def test_raises_when_capacity_exceeded(self) -> None:
        """3/3 slots used — next placement must raise IRCapacityError."""
        snap = _snapshot(current=["player-A", "player-B", "player-C"])
        with pytest.raises(IRCapacityError) as exc_info:
            validate_ir_placement("player-D", snap)
        assert exc_info.value.code == "ir_capacity_exceeded"

    def test_capacity_check_uses_constant(self) -> None:
        """Capacity check must rely on MAX_IR_SLOTS, not a hardcoded 3."""
        full_slots = [f"player-{i}" for i in range(MAX_IR_SLOTS)]
        snap = _snapshot(current=full_slots)
        with pytest.raises(IRCapacityError):
            validate_ir_placement("player-overflow", snap)

    def test_already_in_ir_checked_before_capacity(self) -> None:
        """If player is already in IR AND IR is full, IRPlayerAlreadyInIRError wins."""
        snap = _snapshot(current=["player-A", "player-B", "player-C"])
        with pytest.raises(IRPlayerAlreadyInIRError):
            validate_ir_placement("player-A", snap)


# ---------------------------------------------------------------------------
# validate_ir_reintegration
# ---------------------------------------------------------------------------


class TestValidateIRReintegration:
    def test_valid_reintegration(self) -> None:
        """No exception: player in IR and marked recovered."""
        snap = _snapshot(current=["player-A"], recovered=["player-A"])
        validate_ir_reintegration("player-A", snap)

    def test_raises_when_player_not_in_ir(self) -> None:
        snap = _snapshot(current=["player-B"])
        with pytest.raises(IRError):
            validate_ir_reintegration("player-A", snap)

    def test_raises_when_player_still_injured(self) -> None:
        """Player is in IR but not yet recovered."""
        snap = _snapshot(current=["player-A"], recovered=[])
        with pytest.raises(IRPlayerNotRecoveredError) as exc_info:
            validate_ir_reintegration("player-A", snap)
        assert exc_info.value.code == "ir_player_not_recovered"

    def test_not_in_ir_takes_priority_over_not_recovered(self) -> None:
        """Player neither in IR nor recovered — IRError (not in IR) wins."""
        snap = _snapshot(current=[], recovered=[])
        with pytest.raises(IRError):
            validate_ir_reintegration("player-A", snap)


# ---------------------------------------------------------------------------
# get_overdue_ir_slots
# ---------------------------------------------------------------------------


class TestGetOverdueIRSlots:
    def _make_slot(
        self,
        roster_id: str,
        player_id: str,
        deadline: datetime | None,
    ) -> dict:
        return {
            "roster_id": roster_id,
            "player_id": player_id,
            "ir_recovery_deadline": deadline,
        }

    def test_returns_empty_when_no_slots(self) -> None:
        assert get_overdue_ir_slots([], now=NOW) == []

    def test_returns_empty_when_all_null_deadlines(self) -> None:
        """NULL deadline = player still injured, never overdue."""
        slots = [self._make_slot("r-1", "p-1", None)]
        assert get_overdue_ir_slots(slots, now=NOW) == []

    def test_returns_overdue_slot(self) -> None:
        deadline = NOW - timedelta(days=1)
        slot = self._make_slot("r-1", "p-1", deadline)
        result = get_overdue_ir_slots([slot], now=NOW)
        assert result == [slot]

    def test_ignores_non_overdue_slot(self) -> None:
        deadline = NOW + timedelta(days=1)
        slot = self._make_slot("r-1", "p-1", deadline)
        assert get_overdue_ir_slots([slot], now=NOW) == []

    def test_filters_mixed_list(self) -> None:
        overdue = self._make_slot("r-1", "p-1", NOW - timedelta(hours=1))
        not_overdue = self._make_slot("r-2", "p-2", NOW + timedelta(hours=1))
        still_injured = self._make_slot("r-3", "p-3", None)
        result = get_overdue_ir_slots([overdue, not_overdue, still_injured], now=NOW)
        assert result == [overdue]

    def test_returns_all_overdue_when_multiple(self) -> None:
        slots = [
            self._make_slot("r-1", "p-1", NOW - timedelta(days=2)),
            self._make_slot("r-2", "p-2", NOW - timedelta(days=1)),
        ]
        result = get_overdue_ir_slots(slots, now=NOW)
        assert len(result) == 2

    def test_boundary_exactly_at_deadline_not_overdue(self) -> None:
        """Consistent with is_reintegration_overdue: now == deadline is NOT overdue."""
        slot = self._make_slot("r-1", "p-1", NOW)
        assert get_overdue_ir_slots([slot], now=NOW) == []
