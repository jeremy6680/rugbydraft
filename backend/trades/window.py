"""Trade window management for RugbyDraft.

A trade is only valid if BOTH conditions are true:
  1. today < trade_deadline (date stored on the league at creation)
  2. current_round <= ceil(total_rounds / 2)  (mid-season cutoff, CDC §8.3)

Both checks are required because:
  - Rounds can be postponed: date alone could allow trades past the intended cutoff.
  - The calendar can shift: round_number alone could block trades during an
    unexpected mid-season break.

This module is pure — no I/O, no database calls.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class TradeWindowContext:
    """All data needed to evaluate whether the trade window is open.

    Attributes:
        today: The current date (injected for testability — never call date.today()
            inside business logic).
        trade_deadline: Pre-computed deadline stored on the league at creation.
            Equals start_date + ceil(total_rounds / 2) rounds * 7 days (approximately).
            Authoritative date-based cutoff.
        current_round: The round currently in progress (or the last completed round).
            Used as the round-based cutoff check.
        total_rounds: Total number of rounds in the competition (e.g. 5 for Six Nations).
    """

    today: date
    trade_deadline: date
    current_round: int
    total_rounds: int


def midseason_cutoff_round(total_rounds: int) -> int:
    """Return the last round during which trades are allowed.

    CDC §8.3: trades are blocked after ceil(total_rounds / 2).
    A trade submitted during round N is allowed if N <= ceil(total_rounds / 2).

    Args:
        total_rounds: Total number of rounds in the competition.

    Returns:
        The last round (inclusive) during which trades are open.

    Examples:
        >>> midseason_cutoff_round(5)   # Six Nations: rounds 1-3 open
        3
        >>> midseason_cutoff_round(4)   # Rugby Championship: rounds 1-2 open
        2
        >>> midseason_cutoff_round(26)  # Top 14 regular season: rounds 1-13 open
        13
    """
    return math.ceil(total_rounds / 2)


def is_trade_window_open(ctx: TradeWindowContext) -> tuple[bool, str]:
    """Check whether the trade window is currently open.

    Both the date check and the round check must pass.
    Returns a (bool, reason) tuple so the caller can surface a precise error
    message to the manager — same pattern as waiver validate_claim.

    Args:
        ctx: All data needed to evaluate the window.

    Returns:
        (True, "") if the window is open.
        (False, human-readable reason) if the window is closed.

    Examples:
        >>> ctx = TradeWindowContext(
        ...     today=date(2025, 2, 15),
        ...     trade_deadline=date(2025, 3, 1),
        ...     current_round=2,
        ...     total_rounds=5,
        ... )
        >>> is_trade_window_open(ctx)
        (True, "")
    """
    # Check 1 — date-based cutoff
    if ctx.today >= ctx.trade_deadline:
        return (
            False,
            f"Trade window closed: deadline was {ctx.trade_deadline.isoformat()}.",
        )

    # Check 2 — round-based cutoff (CDC §8.3)
    cutoff = midseason_cutoff_round(ctx.total_rounds)
    if ctx.current_round > cutoff:
        return (
            False,
            (
                f"Trade window closed: past mid-season cutoff "
                f"(round {ctx.current_round} > {cutoff})."
            ),
        )

    return True, ""
