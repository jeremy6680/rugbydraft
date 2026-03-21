# tests/draft/test_snake_order.py
"""
Unit tests for the snake draft order algorithm.

Tests are mandatory and PRs cannot be merged if they fail (NEXT_STEPS.md).
All business rules are taken from CDC v3.1, section 7.1.

Coverage:
- generate_snake_order: 2, 3, 4, 5, 6 managers
- get_pick_owner: consistency with generate_snake_order
- build_pick_slots: structure and indexing
- get_manager_picks: correct pick numbers per manager
- Error cases: empty list, invalid pick number, unknown manager
"""

import pytest

from draft.snake_order import (
    PickSlot,
    build_pick_slots,
    generate_snake_order,
    get_manager_picks,
    get_pick_owner,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def assert_snake_invariants(managers: list[str], num_rounds: int) -> None:
    """Assert structural invariants that must hold for any valid snake order.

    Invariants:
    1. Total length = len(managers) × num_rounds.
    2. Each manager appears exactly num_rounds times.
    3. Round 1 matches original manager order.
    4. Round 2 is the reverse of round 1 (the snake).
    5. Round 3 matches round 1 again.
    """
    order = generate_snake_order(managers, num_rounds)
    n = len(managers)

    # Invariant 1: correct total length
    assert len(order) == n * num_rounds, (
        f"Expected {n * num_rounds} picks, got {len(order)}"
    )

    # Invariant 2: each manager appears exactly num_rounds times
    for manager in managers:
        count = order.count(manager)
        assert count == num_rounds, (
            f"Manager {manager} appears {count} times, expected {num_rounds}"
        )

    # Invariant 3: round 1 is original order
    assert order[:n] == managers, "Round 1 should match original order"

    # Invariant 4: round 2 is reversed
    if num_rounds >= 2:
        assert order[n : 2 * n] == list(reversed(managers)), (
            "Round 2 should be reversed (snake)"
        )

    # Invariant 5: round 3 matches round 1
    if num_rounds >= 3:
        assert order[2 * n : 3 * n] == managers, "Round 3 should match round 1"


# ---------------------------------------------------------------------------
# generate_snake_order — core algorithm
# ---------------------------------------------------------------------------


class TestGenerateSnakeOrder:
    """Tests for generate_snake_order()."""

    def test_two_managers_two_rounds(self) -> None:
        """2 managers, 2 rounds: A B | B A."""
        managers = ["A", "B"]
        result = generate_snake_order(managers, num_rounds=2)
        assert result == ["A", "B", "B", "A"]

    def test_two_managers_invariants(self) -> None:
        assert_snake_invariants(["A", "B"], num_rounds=30)

    def test_three_managers_one_cycle(self) -> None:
        """3 managers, 2 rounds: A B C | C B A."""
        managers = ["A", "B", "C"]
        result = generate_snake_order(managers, num_rounds=2)
        assert result == ["A", "B", "C", "C", "B", "A"]

    def test_three_managers_three_rounds(self) -> None:
        """3 managers, 3 rounds: A B C | C B A | A B C."""
        managers = ["A", "B", "C"]
        result = generate_snake_order(managers, num_rounds=3)
        assert result == ["A", "B", "C", "C", "B", "A", "A", "B", "C"]

    def test_three_managers_invariants(self) -> None:
        assert_snake_invariants(["A", "B", "C"], num_rounds=30)

    def test_four_managers_invariants(self) -> None:
        assert_snake_invariants(["A", "B", "C", "D"], num_rounds=30)

    def test_five_managers_invariants(self) -> None:
        assert_snake_invariants(["A", "B", "C", "D", "E"], num_rounds=30)

    def test_six_managers_invariants(self) -> None:
        assert_snake_invariants(["A", "B", "C", "D", "E", "F"], num_rounds=30)

    def test_six_managers_first_round(self) -> None:
        """First round must preserve the original order for 6 managers."""
        managers = ["M1", "M2", "M3", "M4", "M5", "M6"]
        result = generate_snake_order(managers, num_rounds=1)
        assert result == managers

    def test_six_managers_second_round_is_reversed(self) -> None:
        """Second round must be fully reversed for 6 managers."""
        managers = ["M1", "M2", "M3", "M4", "M5", "M6"]
        result = generate_snake_order(managers, num_rounds=2)
        assert result[6:] == list(reversed(managers))

    def test_single_manager(self) -> None:
        """Edge case: 1 manager always picks."""
        result = generate_snake_order(["solo"], num_rounds=30)
        assert result == ["solo"] * 30

    def test_real_world_30_rounds(self) -> None:
        """Simulate a full RugbyDraft draft: 4 managers, 30 rounds."""
        managers = ["M1", "M2", "M3", "M4"]
        result = generate_snake_order(managers, num_rounds=30)
        assert len(result) == 120  # 4 × 30
        assert result.count("M1") == 30
        assert result.count("M4") == 30

    def test_empty_managers_raises(self) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            generate_snake_order([], num_rounds=30)

    def test_zero_rounds_raises(self) -> None:
        with pytest.raises(ValueError, match="num_rounds must be >= 1"):
            generate_snake_order(["A", "B"], num_rounds=0)

    def test_negative_rounds_raises(self) -> None:
        with pytest.raises(ValueError, match="num_rounds must be >= 1"):
            generate_snake_order(["A", "B"], num_rounds=-1)


# ---------------------------------------------------------------------------
# get_pick_owner — O(1) lookup
# ---------------------------------------------------------------------------


class TestGetPickOwner:
    """Tests for get_pick_owner()."""

    def test_consistency_with_generate(self) -> None:
        """get_pick_owner must return the same result as generate_snake_order[i]."""
        managers = ["A", "B", "C", "D"]
        full_order = generate_snake_order(managers, num_rounds=30)

        for pick_number, expected_owner in enumerate(full_order, start=1):
            result = get_pick_owner(pick_number, managers)
            assert result == expected_owner, (
                f"Pick {pick_number}: expected {expected_owner}, got {result}"
            )

    def test_first_pick_is_first_manager(self) -> None:
        managers = ["X", "Y", "Z"]
        assert get_pick_owner(1, managers) == "X"

    def test_last_pick_of_round_1_is_last_manager(self) -> None:
        managers = ["X", "Y", "Z"]
        assert get_pick_owner(3, managers) == "Z"

    def test_first_pick_of_round_2_is_last_manager(self) -> None:
        """Round 2 starts with the last manager (snake reversal)."""
        managers = ["X", "Y", "Z"]
        assert get_pick_owner(4, managers) == "Z"

    def test_last_pick_of_round_2_is_first_manager(self) -> None:
        managers = ["X", "Y", "Z"]
        assert get_pick_owner(6, managers) == "X"

    def test_pick_number_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="pick_number must be >= 1"):
            get_pick_owner(0, ["A", "B"])

    def test_pick_number_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="pick_number must be >= 1"):
            get_pick_owner(-5, ["A", "B"])

    def test_empty_managers_raises(self) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            get_pick_owner(1, [])


# ---------------------------------------------------------------------------
# build_pick_slots — rich structure
# ---------------------------------------------------------------------------


class TestBuildPickSlots:
    """Tests for build_pick_slots()."""

    def test_returns_correct_count(self) -> None:
        slots = build_pick_slots(["A", "B", "C"], num_rounds=4)
        assert len(slots) == 12  # 3 × 4

    def test_all_are_pick_slot_instances(self) -> None:
        slots = build_pick_slots(["A", "B"], num_rounds=2)
        for slot in slots:
            assert isinstance(slot, PickSlot)

    def test_pick_numbers_are_sequential(self) -> None:
        slots = build_pick_slots(["A", "B", "C"], num_rounds=3)
        pick_numbers = [s.pick_number for s in slots]
        assert pick_numbers == list(range(1, 10))

    def test_round_numbers_correct(self) -> None:
        """Round numbers must go 1, 1, 1, 2, 2, 2, ... for 3 managers."""
        slots = build_pick_slots(["A", "B", "C"], num_rounds=3)
        rounds = [s.round_number for s in slots]
        assert rounds == [1, 1, 1, 2, 2, 2, 3, 3, 3]

    def test_position_in_round_correct(self) -> None:
        """Positions within each round must go 1, 2, 3, 1, 2, 3, ..."""
        slots = build_pick_slots(["A", "B", "C"], num_rounds=3)
        positions = [s.position_in_round for s in slots]
        assert positions == [1, 2, 3, 1, 2, 3, 1, 2, 3]

    def test_manager_ids_match_generate(self) -> None:
        managers = ["P1", "P2", "P3", "P4"]
        slots = build_pick_slots(managers, num_rounds=30)
        order = generate_snake_order(managers, num_rounds=30)
        slot_managers = [s.manager_id for s in slots]
        assert slot_managers == order


# ---------------------------------------------------------------------------
# get_manager_picks
# ---------------------------------------------------------------------------


class TestGetManagerPicks:
    """Tests for get_manager_picks()."""

    def test_two_managers_picks(self) -> None:
        """With 2 managers, 4 rounds: A picks 1, 4, 5, 8 — B picks 2, 3, 6, 7."""
        picks_a = get_manager_picks("A", ["A", "B"], num_rounds=4)
        picks_b = get_manager_picks("B", ["A", "B"], num_rounds=4)
        assert picks_a == [1, 4, 5, 8]
        assert picks_b == [2, 3, 6, 7]

    def test_manager_has_correct_number_of_picks(self) -> None:
        managers = ["M1", "M2", "M3", "M4", "M5"]
        for manager in managers:
            picks = get_manager_picks(manager, managers, num_rounds=30)
            assert len(picks) == 30, f"{manager} should have 30 picks"

    def test_all_picks_covered(self) -> None:
        """All pick numbers 1..N×rounds must appear exactly once across all managers."""
        managers = ["A", "B", "C", "D"]
        all_picks: list[int] = []
        for m in managers:
            all_picks.extend(get_manager_picks(m, managers, num_rounds=30))
        assert sorted(all_picks) == list(range(1, 121))

    def test_unknown_manager_raises(self) -> None:
        with pytest.raises(ValueError, match="not found in managers list"):
            get_manager_picks("ghost", ["A", "B"], num_rounds=30)
