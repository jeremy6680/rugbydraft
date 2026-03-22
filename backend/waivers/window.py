"""Waiver window logic — pure functions, no I/O.

The waiver window opens every Tuesday at 07:00 and closes every Wednesday
at 23:59:59 (Europe/Paris timezone, following the AI staff report schedule).

These times are intentionally constants (not DB-configurable in V1).
Commissioner-level per-league configuration is deferred to a future phase.
"""

from datetime import datetime, time
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WAIVER_TIMEZONE = ZoneInfo("Europe/Paris")

# Waiver window opens Tuesday 07:00 (after Staff IA Tuesday report, CDC 13.2)
WAIVER_OPEN_WEEKDAY = 1  # Monday=0, Tuesday=1
WAIVER_OPEN_TIME = time(7, 0, 0)

# Waiver window closes Wednesday 23:59:59
WAIVER_CLOSE_WEEKDAY = 2  # Wednesday=2
WAIVER_CLOSE_TIME = time(23, 59, 59)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_waiver_window_open(now: datetime | None = None) -> bool:
    """Return True if the waiver window is currently open.

    The waiver window is open from Tuesday 07:00 to Wednesday 23:59:59
    (Europe/Paris). This function is timezone-aware: if ``now`` is naive,
    it is assumed to already be in Europe/Paris. If it is tz-aware, it is
    converted to Europe/Paris before comparison.

    Args:
        now: The current datetime. Defaults to datetime.now(WAIVER_TIMEZONE).
             Injected explicitly in tests to avoid time-dependent failures.

    Returns:
        True if the waiver window is open, False otherwise.
    """
    if now is None:
        now = datetime.now(WAIVER_TIMEZONE)
    elif now.tzinfo is not None:
        now = now.astimezone(WAIVER_TIMEZONE)

    weekday = now.weekday()
    current_time = now.time()

    # Tuesday after WAIVER_OPEN_TIME
    if weekday == WAIVER_OPEN_WEEKDAY and current_time >= WAIVER_OPEN_TIME:
        return True

    # Wednesday before or at WAIVER_CLOSE_TIME
    if weekday == WAIVER_CLOSE_WEEKDAY and current_time <= WAIVER_CLOSE_TIME:
        return True

    return False


def assert_waiver_window_open(now: datetime | None = None) -> None:
    """Raise WaiverWindowClosedError if the waiver window is not open.

    Convenience wrapper for use in validators and service layer.

    Args:
        now: The current datetime. Defaults to datetime.now(WAIVER_TIMEZONE).

    Raises:
        WaiverWindowClosedError: If the waiver window is currently closed.
    """
    if not is_waiver_window_open(now):
        raise WaiverWindowClosedError(
            "Waiver window is closed. Claims are only accepted "
            "from Tuesday 07:00 to Wednesday 23:59:59 (Paris time)."
        )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class WaiverWindowClosedError(Exception):
    """Raised when a waiver claim is submitted outside the waiver window."""
