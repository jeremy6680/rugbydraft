-- =============================================================================
-- Migration 005 — Infirmary: ir_recovery_deadline column
-- =============================================================================
-- Adds ir_recovery_deadline to weekly_lineups to track the 1-week reintegration
-- deadline for recovered players (CDC §6.4).
--
-- NULL  = player still injured/suspended (no active deadline)
-- NOT NULL = player recovered; manager must reintegrate before this timestamp
--            or waivers/trades are blocked.
--
-- Populated by the daily ir_scheduler APScheduler job (not by the client).
-- =============================================================================

ALTER TABLE weekly_lineups
    ADD COLUMN IF NOT EXISTS ir_recovery_deadline TIMESTAMPTZ DEFAULT NULL;

-- Index: the scheduler queries all rows where deadline is not null and in the past
-- to build the "overdue" list. This scan runs daily — this index keeps it O(log n).
CREATE INDEX IF NOT EXISTS idx_weekly_lineups_ir_recovery_deadline
    ON weekly_lineups (ir_recovery_deadline)
    WHERE ir_recovery_deadline IS NOT NULL;

COMMENT ON COLUMN weekly_lineups.ir_recovery_deadline IS
    'Timestamp after which waiver/trade blocking activates for this IR slot. '
    'NULL = player still injured. Set by ir_scheduler when recovery is detected. '
    'Cleared (set back to NULL) when the player is reintegrated by the manager.';