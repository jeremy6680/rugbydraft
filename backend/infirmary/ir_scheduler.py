"""
IR scheduler — daily APScheduler job for infirmary deadline management.

Runs once daily at 09:00 UTC. Responsibilities:
1. Detect recovered players in IR slots (cross-reference with pipeline availability data).
2. Write ir_recovery_deadline = recovery_date + 7 days on weekly_lineups rows
   where the player is recovered but deadline is not yet set.
3. Broadcast a Realtime notification to league channels for each affected roster.

This job does NOT block waivers or trades directly — that logic lives in
validate_claim.py and validate_trade.py, which read ir_recovery_deadline at
request time. The scheduler only writes the deadline.

Architecture note (D-002): APScheduler handles all daily tasks.
Airflow is reserved for post_match_pipeline only.
"""

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from supabase import AsyncClient

from infirmary.ir_rules import calculate_recovery_deadline

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scheduler instance (singleton — mounted on FastAPI lifespan)
# ---------------------------------------------------------------------------

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    """Return the global APScheduler instance, creating it if needed."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="UTC")
    return _scheduler


# ---------------------------------------------------------------------------
# Core job
# ---------------------------------------------------------------------------


async def run_ir_recovery_scan(supabase: AsyncClient) -> dict:
    """Detect recovered IR players and write reintegration deadlines.

    Queries weekly_lineups for all active IR slots where:
    - slot_type = 'ir'
    - ir_recovery_deadline IS NULL (deadline not yet set)

    For each such slot, checks stg_player_availability (silver pipeline)
    to see if the player's status is 'available' (recovered).

    If recovered:
    - Writes ir_recovery_deadline = recovery_date + 7 days.
    - Broadcasts a Realtime notification to league:{league_id} channel.

    Args:
        supabase: Async Supabase client (injected — never instantiated here).

    Returns:
        Summary dict with counts for observability:
        {
            "scanned": int,       # total active IR slots checked
            "deadlines_set": int, # new deadlines written
            "errors": int,        # slots that failed (logged individually)
        }
    """
    now = datetime.now(timezone.utc)
    summary = {"scanned": 0, "deadlines_set": 0, "errors": 0}

    # ------------------------------------------------------------------
    # Step 1 — Fetch all active IR slots without a deadline
    # ------------------------------------------------------------------
    try:
        response = (
            await supabase.table("weekly_lineups")
            .select(
                "id, roster_id, player_id, ir_recovery_deadline, rosters(league_id)"
            )
            .eq("slot_type", "ir")
            .is_("ir_recovery_deadline", "null")
            .execute()
        )
        ir_slots = response.data or []
    except Exception:
        logger.exception("IR scheduler: failed to fetch IR slots from weekly_lineups.")
        return summary

    summary["scanned"] = len(ir_slots)

    if not ir_slots:
        logger.info("IR scheduler: no active IR slots without deadline. Nothing to do.")
        return summary

    logger.info("IR scheduler: scanning %d IR slot(s).", len(ir_slots))

    # ------------------------------------------------------------------
    # Step 2 — For each slot, check pipeline availability
    # ------------------------------------------------------------------
    for slot in ir_slots:
        player_id: str = slot["player_id"]
        lineup_id: str = slot["id"]
        roster_id: str = slot["roster_id"]
        league_id: str | None = (slot.get("rosters") or {}).get("league_id")

        try:
            avail_response = (
                await supabase.table("pipeline_stg_player_availability")
                .select("status, updated_at")
                .eq("player_id", player_id)
                .order("updated_at", desc=True)
                .limit(1)
                .execute()
            )
            rows = avail_response.data or []

            if not rows:
                # No availability data — player status unknown, skip.
                logger.debug(
                    "IR scheduler: no availability data for player %s. Skipping.",
                    player_id,
                )
                continue

            status: str = rows[0]["status"]
            updated_at_raw: str = rows[0]["updated_at"]

            if status != "available":
                # Player still injured or suspended — no deadline yet.
                logger.debug(
                    "IR scheduler: player %s status=%s — not yet recovered.",
                    player_id,
                    status,
                )
                continue

            # ----------------------------------------------------------
            # Step 3 — Player is recovered: write deadline
            # ----------------------------------------------------------
            recovery_date = datetime.fromisoformat(updated_at_raw)
            deadline = calculate_recovery_deadline(recovery_date)

            await (
                supabase.table("weekly_lineups")
                .update({"ir_recovery_deadline": deadline.isoformat()})
                .eq("id", lineup_id)
                .execute()
            )

            summary["deadlines_set"] += 1
            logger.info(
                "IR scheduler: deadline set for player %s (roster %s) → %s.",
                player_id,
                roster_id,
                deadline.isoformat(),
            )

            # ----------------------------------------------------------
            # Step 4 — Broadcast Realtime notification to league channel
            # ----------------------------------------------------------
            if league_id:
                await _broadcast_recovery_alert(
                    supabase=supabase,
                    league_id=league_id,
                    roster_id=roster_id,
                    player_id=player_id,
                    deadline=deadline,
                    now=now,
                )

        except Exception:
            logger.exception(
                "IR scheduler: error processing IR slot for player %s.", player_id
            )
            summary["errors"] += 1

    logger.info(
        "IR scheduler: scan complete — scanned=%d, deadlines_set=%d, errors=%d.",
        summary["scanned"],
        summary["deadlines_set"],
        summary["errors"],
    )
    return summary


async def _broadcast_recovery_alert(
    supabase: AsyncClient,
    league_id: str,
    roster_id: str,
    player_id: str,
    deadline: datetime,
    now: datetime,
) -> None:
    """Broadcast a recovery alert to the league Realtime channel.

    Frontend listens on channel 'league:{league_id}' and displays
    the dashboard alert: "Player X recovered — reintegrate within X days."

    Args:
        supabase: Async Supabase client.
        league_id: League UUID — determines the Realtime channel.
        roster_id: Roster UUID of the affected manager.
        player_id: Player UUID who recovered.
        deadline: Reintegration deadline (UTC).
        now: Current timestamp for days_remaining calculation.
    """
    days_remaining = (deadline - now).days

    payload = {
        "event": "ir_recovery_alert",
        "roster_id": roster_id,
        "player_id": player_id,
        "ir_recovery_deadline": deadline.isoformat(),
        "days_remaining": days_remaining,
    }

    try:
        await supabase.channel(f"league:{league_id}").send_broadcast(
            event="ir_recovery_alert",
            payload=payload,
        )
        logger.debug(
            "IR scheduler: broadcast sent to league:%s for player %s.",
            league_id,
            player_id,
        )
    except Exception:
        # Non-fatal — deadline is already written to DB.
        # The frontend will still see the alert on next page load via the API.
        logger.warning(
            "IR scheduler: broadcast failed for league:%s player %s. "
            "Deadline is written — alert will appear on next API poll.",
            league_id,
            player_id,
        )


# ---------------------------------------------------------------------------
# Scheduler registration (called from FastAPI lifespan)
# ---------------------------------------------------------------------------


def register_ir_jobs(scheduler: AsyncIOScheduler, supabase: AsyncClient) -> None:
    """Register all IR-related APScheduler jobs.

    Called once during FastAPI startup (lifespan context).
    The scheduler is started by the caller — this function only adds jobs.

    Args:
        scheduler: The global AsyncIOScheduler instance.
        supabase: Async Supabase client (shared with the app).

    Jobs registered:
        ir_recovery_scan — daily at 09:00 UTC.
    """
    scheduler.add_job(
        func=run_ir_recovery_scan,
        trigger=CronTrigger(hour=9, minute=0, timezone="UTC"),
        kwargs={"supabase": supabase},
        id="ir_recovery_scan",
        name="Daily IR recovery scan",
        replace_existing=True,
        misfire_grace_time=3600,  # 1 hour grace — if server was down at 09:00
    )
    logger.info("IR scheduler: ir_recovery_scan job registered (daily 09:00 UTC).")
