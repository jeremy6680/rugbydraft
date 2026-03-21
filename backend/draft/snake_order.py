# backend/draft/snake_order.py
"""
Snake draft order algorithm for RugbyDraft.

This module implements the core snake draft ordering logic.
It is intentionally kept pure (no I/O, no database, no FastAPI)
so it can be tested in isolation and reused by the DraftEngine.

Business rules (CDC v3.1, section 7.1):
- Round 1: Manager 1 → 2 → ... → N
- Round 2: Manager N → ... → 2 → 1
- Round 3: Manager 1 → 2 → ... → N
- Each round reverses direction ("snake" pattern).
- Total picks = len(managers) × num_rounds.
- In RugbyDraft: num_rounds = 30 (15 starters + 15 bench per roster).
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PickSlot:
    """Represents a single pick slot in the draft order.

    Attributes:
        pick_number: Absolute pick number, 1-indexed (e.g. 1 for the first pick).
        round_number: Round number, 1-indexed (e.g. 1 for the first round).
        position_in_round: Position within the round, 1-indexed.
        manager_id: ID of the manager who owns this pick.
    """

    pick_number: int
    round_number: int
    position_in_round: int
    manager_id: str


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------


def generate_snake_order(
    managers: list[str],
    num_rounds: int,
) -> list[str]:
    """Generate the full snake draft order as a flat list of manager IDs.

    Each element in the returned list corresponds to one pick slot.
    The index of the list is the 0-indexed pick number.

    Example with managers=["A", "B", "C"] and num_rounds=2:
        Round 1: A, B, C  (left to right)
        Round 2: C, B, A  (right to left — snake)
        Returns: ["A", "B", "C", "C", "B", "A"]

    Args:
        managers: Ordered list of manager IDs after the random draw.
                  The order of this list defines pick priority in round 1.
        num_rounds: Total number of rounds in the draft.
                    In RugbyDraft: 30 (15 starters + 15 bench).

    Returns:
        Flat list of manager IDs, one per pick, in draft order.

    Raises:
        ValueError: If managers list is empty or num_rounds < 1.
    """
    if not managers:
        raise ValueError("managers list cannot be empty")
    if num_rounds < 1:
        raise ValueError(f"num_rounds must be >= 1, got {num_rounds}")

    order: list[str] = []

    for round_index in range(num_rounds):
        # Even rounds (0, 2, 4...): left to right (original order)
        # Odd rounds (1, 3, 5...): right to left (reversed — the "snake")
        if round_index % 2 == 0:
            order.extend(managers)
        else:
            order.extend(reversed(managers))

    return order


def get_pick_owner(pick_number: int, managers: list[str]) -> str:
    """Return the manager ID who owns a given pick number (1-indexed).

    This is a O(1) computation — no need to generate the full order.

    Args:
        pick_number: The pick number, 1-indexed (first pick = 1).
        managers: Ordered list of manager IDs (same order as the draft draw).

    Returns:
        The manager ID who owns this pick.

    Raises:
        ValueError: If pick_number < 1 or managers list is empty.
    """
    if not managers:
        raise ValueError("managers list cannot be empty")
    if pick_number < 1:
        raise ValueError(f"pick_number must be >= 1, got {pick_number}")

    n = len(managers)
    # Convert to 0-indexed for the modulo arithmetic
    zero_indexed = pick_number - 1
    round_index = zero_indexed // n
    position_in_round = zero_indexed % n

    # Snake: odd rounds go right-to-left
    if round_index % 2 == 1:
        position_in_round = n - 1 - position_in_round

    return managers[position_in_round]


def build_pick_slots(
    managers: list[str],
    num_rounds: int,
) -> list[PickSlot]:
    """Build the full list of PickSlot objects for a draft.

    Useful for rich display (draft board) and audit logging.

    Args:
        managers: Ordered list of manager IDs after the random draw.
        num_rounds: Total number of rounds in the draft.

    Returns:
        List of PickSlot, one per pick, in draft order.

    Raises:
        ValueError: Propagated from generate_snake_order.
    """
    order = generate_snake_order(managers, num_rounds)
    slots: list[PickSlot] = []

    n = len(managers)
    for i, manager_id in enumerate(order):
        pick_number = i + 1  # 1-indexed
        round_number = (i // n) + 1  # 1-indexed
        position_in_round = (i % n) + 1  # 1-indexed
        slots.append(
            PickSlot(
                pick_number=pick_number,
                round_number=round_number,
                position_in_round=position_in_round,
                manager_id=manager_id,
            )
        )

    return slots


def get_manager_picks(
    manager_id: str,
    managers: list[str],
    num_rounds: int,
) -> list[int]:
    """Return all pick numbers owned by a given manager.

    Args:
        manager_id: The manager to query.
        managers: Ordered list of manager IDs.
        num_rounds: Total number of rounds.

    Returns:
        Sorted list of 1-indexed pick numbers belonging to this manager.

    Raises:
        ValueError: If manager_id is not in managers.
    """
    if manager_id not in managers:
        raise ValueError(f"manager_id '{manager_id}' not found in managers list")

    order = generate_snake_order(managers, num_rounds)
    return [i + 1 for i, m in enumerate(order) if m == manager_id]
