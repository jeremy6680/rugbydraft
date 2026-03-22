-- =============================================================================
-- Migration 002 — Phase 3: Gameplay additions
-- =============================================================================
-- Adds columns and tables required for Phase 3 (Gameplay).
--
-- What this migration adds:
--   1. drafts.manager_order JSONB        (D-029: engine reconstruction after restart)
--   2. weekly_lineups                    (CDC 6.5: per-round lineup + progressive lock)
--   3. waivers                           (CDC 9.1: waiver claims)
--   4. trades + trade_players            (CDC 9.2: bilateral player trades)
--   5. fantasy_scores_staging            (D-003: atomic commit pattern)
--   6. RLS policies on all new tables    (security baseline)
--   7. Performance indexes
--   8. GRANT statements
--
-- Prerequisites:
--   - 001_initial_schema.sql applied (fantasy_scores, rosters, players,
--     leagues, league_members, competition_rounds, drafts must exist)
--
-- Compatibility note:
--   CREATE POLICY IF NOT EXISTS is not supported by Supabase's PG build.
--   All policies use DO $$ BEGIN ... EXCEPTION WHEN duplicate_object THEN NULL END $$
--   for safe re-runs.
--
-- Safe to re-run: all statements use IF NOT EXISTS or DO $$ wrappers.
-- Apply via Supabase SQL Editor or:
--   psql $DATABASE_URL -f 002_phase3_additions.sql
-- =============================================================================


-- =============================================================================
-- 1. drafts.manager_order
-- =============================================================================
-- Stores the shuffled manager order drawn at draft start as a JSON array of
-- league_member UUIDs. This is the canonical source of truth for the snake
-- draft order for the entire season.
--
-- Without this column, a FastAPI restart mid-draft loses the randomised order
-- and cannot reconstruct the same snake sequence (D-029).
--
-- Example value: ["uuid-m3", "uuid-m1", "uuid-m4", "uuid-m2"]
-- Set once at draft launch (POST /draft/{league_id}/start), never mutated.
-- =============================================================================

ALTER TABLE drafts
    ADD COLUMN IF NOT EXISTS manager_order JSONB;

COMMENT ON COLUMN drafts.manager_order IS
    'Shuffled manager order drawn at draft start. JSON array of league_member '
    'UUIDs in the order they will pick in round 1. Required to reconstruct '
    'generate_snake_order() after a FastAPI restart mid-draft (D-029). '
    'Set once at launch, never mutated.';


-- =============================================================================
-- 2. weekly_lineups
-- =============================================================================
-- One row per (roster, round, player). Tracks starter/bench/IR slot, captain
-- and kicker designation, multi-position choice, and the progressive lock.
--
-- Progressive lock (CDC 6.5, 6.6):
--   locked_at IS NULL     -> not yet locked; captain/kicker/position can change
--   locked_at IS NOT NULL -> locked since kick-off of player's team match;
--                            is_captain/is_kicker/position are immutable this round
--
-- Key rules from CDC:
--   - Only starters score points (slot_type = 'starter').
--   - Exactly one captain per roster per round, must be a starter.
--   - Exactly one designated kicker per roster per round.
--   - Captain: x1.5 multiplier rounded up to nearest 0.5 (CDC 10.3).
--   - Kicker: only they score conversions and penalty kicks (CDC 10.1).
--   - Drops (+3) are open to all starters regardless of is_kicker.
--   - Multi-position players choose their position per round (CDC 6.3);
--     choice locks at kick-off of their team's match.
-- =============================================================================

CREATE TABLE IF NOT EXISTS weekly_lineups (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    -- The roster this lineup entry belongs to.
    roster_id       UUID        NOT NULL REFERENCES rosters(id) ON DELETE CASCADE,

    -- The competition round this lineup applies to.
    round_id        UUID        NOT NULL REFERENCES competition_rounds(id) ON DELETE CASCADE,

    -- The player in this slot.
    player_id       UUID        NOT NULL REFERENCES players(id) ON DELETE RESTRICT,

    -- 'starter': scores points this round.
    -- 'bench':   does not score; available as cover if a starter is injured.
    -- 'ir':      infirmary; does not score; does not count toward coverage (CDC 6.4).
    slot_type       TEXT        NOT NULL CHECK (slot_type IN ('starter', 'bench', 'ir')),

    -- Captain designation. Exactly one TRUE per (roster_id, round_id).
    -- Must be a starter (slot_type = 'starter'). Enforced at API level.
    is_captain      BOOLEAN     NOT NULL DEFAULT FALSE,

    -- Kicker designation. Exactly one TRUE per (roster_id, round_id).
    -- Only this player scores conversions (+2/-0.5) and penalties (+3/-1).
    -- Drops (+3) are open to all starters regardless of this flag (CDC 10.1).
    is_kicker       BOOLEAN     NOT NULL DEFAULT FALSE,

    -- Position chosen for this round (multi-position players only, CDC 6.3).
    -- NULL for single-position players (position from players.positions[0] applies).
    -- Locked at kick-off -- must not change after locked_at is set.
    position        TEXT,

    -- Progressive lock timestamp. NULL = not yet locked.
    -- Set to the kick-off timestamp of the player's team match in this round.
    -- After this: is_captain, is_kicker, position, slot_type are immutable.
    -- Note: a round can span multiple match days -- each player locks independently.
    locked_at       TIMESTAMPTZ,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- One entry per player per round per roster.
    UNIQUE (roster_id, round_id, player_id)
);

COMMENT ON TABLE weekly_lineups IS
    'Per-player lineup for each competition round (CDC 6.5). '
    'Progressive lock: locked_at set at kick-off of the player team match. '
    'Once locked, is_captain / is_kicker / position / slot_type are immutable. '
    'Only starters (slot_type=starter) score fantasy points.';

-- Keep updated_at current on every mutation.
-- CREATE OR REPLACE is safe if the function already exists from migration 001.
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Guard: only create the trigger if it does not already exist.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'set_weekly_lineups_updated_at'
          AND tgrelid = 'weekly_lineups'::regclass
    ) THEN
        CREATE TRIGGER set_weekly_lineups_updated_at
            BEFORE UPDATE ON weekly_lineups
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;

-- Fetch full lineup for a roster in a given round (most common query).
CREATE INDEX IF NOT EXISTS idx_weekly_lineups_roster_round
    ON weekly_lineups (roster_id, round_id);

-- Check if a specific player appears in any lineup for a round.
CREATE INDEX IF NOT EXISTS idx_weekly_lineups_round_player
    ON weekly_lineups (round_id, player_id);

-- Find the captain for a round (scoring pipeline lookup).
CREATE INDEX IF NOT EXISTS idx_weekly_lineups_captain
    ON weekly_lineups (round_id, is_captain)
    WHERE is_captain = TRUE;

-- Find the designated kicker for a roster in a round (scoring pipeline lookup).
CREATE INDEX IF NOT EXISTS idx_weekly_lineups_kicker
    ON weekly_lineups (roster_id, round_id, is_kicker)
    WHERE is_kicker = TRUE;


-- =============================================================================
-- 3. waivers
-- =============================================================================
-- A waiver claim: manager drops one player and claims a free agent.
--
-- Window (CDC 9.1):
--   Opens:     Tuesday morning (after Staff IA reports run at 07:00)
--   Closes:    Wednesday evening
--   Processed: Wednesday evening, in priority order
--
-- Priority: lowest-ranked manager gets priority 1 (processes first).
-- Stored as a snapshot at claim time; processor uses it as-is.
--
-- Blocking rule: manager with unintegrated recovered IR player (> 1 week)
-- cannot submit a new claim. Enforced at API level (POST /waivers).
--
-- Status flow: pending -> approved | rejected
-- =============================================================================

CREATE TABLE IF NOT EXISTS waivers (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    league_id           UUID        NOT NULL REFERENCES leagues(id) ON DELETE CASCADE,
    round_id            UUID        NOT NULL REFERENCES competition_rounds(id) ON DELETE CASCADE,

    -- The manager making the claim.
    member_id           UUID        NOT NULL REFERENCES league_members(id) ON DELETE CASCADE,

    -- Player being dropped from this manager's roster (returned to free pool).
    drop_player_id      UUID        NOT NULL REFERENCES players(id) ON DELETE RESTRICT,

    -- Free agent being claimed (must not be on any roster in this league).
    add_player_id       UUID        NOT NULL REFERENCES players(id) ON DELETE RESTRICT,

    -- Priority at claim time. 1 = highest priority (lowest-ranked manager).
    -- Recalculated from current standings at the start of each waiver window.
    priority            SMALLINT    NOT NULL,

    -- Claim workflow status.
    status              TEXT        NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'approved', 'rejected')),

    -- Human-readable rejection reason when status = 'rejected'.
    rejection_reason    TEXT,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Timestamp when the waiver cycle processed this claim. NULL = not yet run.
    processed_at        TIMESTAMPTZ
);

COMMENT ON TABLE waivers IS
    'Waiver claims (CDC 9.1). Window: Tuesday morning to Wednesday evening. '
    'Priority = snapshot of manager standings rank (1 = highest priority). '
    'Blocking: manager with unintegrated recovered IR player cannot claim.';

-- Fetch all pending claims for a league+round (waiver cycle processor).
CREATE INDEX IF NOT EXISTS idx_waivers_league_round_status
    ON waivers (league_id, round_id, status);

-- Check if a manager already has a pending claim this round.
CREATE INDEX IF NOT EXISTS idx_waivers_member_round_status
    ON waivers (member_id, round_id, status);

-- Find all pending claims targeting a specific free agent (conflict detection).
CREATE INDEX IF NOT EXISTS idx_waivers_add_player_round
    ON waivers (add_player_id, round_id, status)
    WHERE status = 'pending';


-- =============================================================================
-- 4. trades + trade_players
-- =============================================================================
-- Bilateral player exchange between two managers (CDC 9.2).
-- Formats: 1v1, 1v2, 1v3 (no pick trading -- explicitly forbidden in CDC).
-- Window: competition start -> ceil(total_rounds / 2). Blocked after mid-season.
--
-- Commissioner veto (optional per-league):
--   If leagues.settings->>'veto_enabled' = 'true', commissioner has 24h to veto
--   after acceptance. Must provide a written reason (veto_reason).
--
-- Status flow:
--   proposed -> accepted -> completed
--   proposed -> rejected
--   accepted -> vetoed   (commissioner intervened within veto_deadline)
-- =============================================================================

CREATE TABLE IF NOT EXISTS trades (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    league_id       UUID        NOT NULL REFERENCES leagues(id) ON DELETE CASCADE,

    -- The manager who initiated the proposal.
    proposer_id     UUID        NOT NULL REFERENCES league_members(id) ON DELETE CASCADE,

    -- The manager receiving the proposal.
    receiver_id     UUID        NOT NULL REFERENCES league_members(id) ON DELETE CASCADE,

    -- Trade lifecycle status.
    status          TEXT        NOT NULL DEFAULT 'proposed'
                        CHECK (status IN (
                            'proposed',
                            'accepted',
                            'rejected',
                            'completed',
                            'vetoed'
                        )),

    -- Veto deadline. NULL if veto option not enabled on this league.
    -- Set to responded_at + INTERVAL '24 hours' on transition to 'accepted'.
    veto_deadline   TIMESTAMPTZ,

    -- Commissioner written justification. Required when status = 'vetoed'.
    veto_reason     TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- When receiver accepted or rejected (NULL until they respond).
    responded_at    TIMESTAMPTZ,

    -- When roster_slots were actually swapped (NULL until status = 'completed').
    completed_at    TIMESTAMPTZ
);

COMMENT ON TABLE trades IS
    'Bilateral player trades (CDC 9.2). Window: start to ceil(total_rounds/2). '
    'Formats: 1v1, 1v2, 1v3. No pick trading. '
    'Veto: commissioner has 24h if leagues.settings.veto_enabled = true.';

-- One row per player involved in a trade.
-- 1v2 = 3 rows (1 out + 2 in). 1v3 = 4 rows (1 out + 3 in).
CREATE TABLE IF NOT EXISTS trade_players (
    id          UUID    PRIMARY KEY DEFAULT gen_random_uuid(),

    trade_id    UUID    NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
    player_id   UUID    NOT NULL REFERENCES players(id) ON DELETE RESTRICT,

    -- Direction from the proposer perspective:
    --   'out': player leaves proposer roster (goes to receiver).
    --   'in':  player arrives at proposer roster (comes from receiver).
    direction   TEXT    NOT NULL CHECK (direction IN ('out', 'in')),

    -- Current owner before the trade executes. Used to validate ownership.
    member_id   UUID    NOT NULL REFERENCES league_members(id) ON DELETE CASCADE
);

COMMENT ON TABLE trade_players IS
    'Individual players in a trade (CDC 9.2). '
    'direction=out: leaves proposer. direction=in: joins proposer. '
    'member_id = current owner before trade executes.';

CREATE INDEX IF NOT EXISTS idx_trades_league_status
    ON trades (league_id, status);

CREATE INDEX IF NOT EXISTS idx_trades_proposer
    ON trades (proposer_id, status);

CREATE INDEX IF NOT EXISTS idx_trades_receiver
    ON trades (receiver_id, status);

CREATE INDEX IF NOT EXISTS idx_trade_players_trade
    ON trade_players (trade_id);

CREATE INDEX IF NOT EXISTS idx_trade_players_player
    ON trade_players (player_id);


-- =============================================================================
-- 5. fantasy_scores_staging
-- =============================================================================
-- Staging table for the atomic commit pattern (D-003).
--
-- The post_match_pipeline writes ALL calculated scores here first.
-- Only when the full pipeline succeeds does a single PostgreSQL transaction:
--
--   BEGIN;
--     DELETE FROM fantasy_scores WHERE round_id = $round_id;
--     INSERT INTO fantasy_scores
--       (id, roster_id, round_id, player_id,
--        points_breakdown, raw_points, captain_multiplier, total_points)
--     SELECT
--       id, roster_id, round_id, player_id,
--       points_breakdown, raw_points, captain_multiplier, total_points
--     FROM fantasy_scores_staging
--     WHERE round_id = $round_id;
--     TRUNCATE fantasy_scores_staging;
--   COMMIT;
--
-- If the pipeline fails before that transaction: staging is truncated at the
-- next pipeline run. Production (fantasy_scores) is never partially updated.
--
-- Schema matches fantasy_scores exactly (same columns, same types).
-- Extra column pipeline_run_id is excluded from the INSERT ... SELECT above.
--
-- total_points formula (CDC 10.3):
--   Captain : CEIL(raw_points * 1.5 * 2) / 2.0  (rounds up to nearest 0.5)
--   Others  : raw_points  (no rounding needed)
-- =============================================================================

CREATE TABLE IF NOT EXISTS fantasy_scores_staging (
    id                  UUID          PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Columns match fantasy_scores exactly.
    roster_id           UUID          NOT NULL REFERENCES rosters(id) ON DELETE CASCADE,
    round_id            UUID          NOT NULL REFERENCES competition_rounds(id) ON DELETE CASCADE,
    player_id           UUID          NOT NULL REFERENCES players(id) ON DELETE RESTRICT,
    points_breakdown    JSONB         NOT NULL DEFAULT '{}',
    raw_points          NUMERIC(6, 2) NOT NULL DEFAULT 0,
    captain_multiplier  NUMERIC(3, 2) NOT NULL DEFAULT 1.00,
    total_points        NUMERIC(6, 2) NOT NULL DEFAULT 0,

    -- Staging-only: UUID generated once per pipeline run.
    -- All rows from the same run share this ID. Useful for debugging.
    pipeline_run_id     UUID,

    created_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    UNIQUE (roster_id, round_id, player_id)
);

COMMENT ON TABLE fantasy_scores_staging IS
    'Staging table for atomic fantasy score commit (D-003). '
    'Pipeline writes here; on full success a single transaction copies to '
    'fantasy_scores and truncates staging. On failure, staging is truncated '
    'at next pipeline start -- production data is always untouched. '
    'pipeline_run_id tracks which run wrote each row for debugging.';

CREATE INDEX IF NOT EXISTS idx_fantasy_scores_staging_round
    ON fantasy_scores_staging (round_id);

CREATE INDEX IF NOT EXISTS idx_fantasy_scores_staging_roster_round
    ON fantasy_scores_staging (roster_id, round_id);


-- =============================================================================
-- 6. Row Level Security
-- =============================================================================
-- All new tables get RLS enabled. Supabase service role (used by FastAPI)
-- bypasses RLS automatically. The anon role has no access.
--
-- fantasy_scores_staging: no policies created = deny all for authenticated.
-- FastAPI backend (service role) is the only writer/reader for that table.
-- =============================================================================

ALTER TABLE weekly_lineups          ENABLE ROW LEVEL SECURITY;
ALTER TABLE waivers                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE trades                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE trade_players           ENABLE ROW LEVEL SECURITY;
ALTER TABLE fantasy_scores_staging  ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------
-- weekly_lineups policies
-- ---------------------------------------------------------------------------

-- Write + read own roster.
DO $$
BEGIN
    CREATE POLICY "weekly_lineups_own_roster_all"
        ON weekly_lineups
        FOR ALL
        TO authenticated
        USING (
            EXISTS (
                SELECT 1
                FROM rosters r
                JOIN league_members lm ON lm.id = r.member_id
                WHERE r.id = weekly_lineups.roster_id
                  AND lm.user_id = auth.uid()
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1
                FROM rosters r
                JOIN league_members lm ON lm.id = r.member_id
                WHERE r.id = weekly_lineups.roster_id
                  AND lm.user_id = auth.uid()
            )
        );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Read all lineups in own league (opponents' starters are public information).
DO $$
BEGIN
    CREATE POLICY "weekly_lineups_league_members_read"
        ON weekly_lineups
        FOR SELECT
        TO authenticated
        USING (
            EXISTS (
                SELECT 1
                FROM rosters r
                JOIN league_members lm_owner ON lm_owner.id = r.member_id
                JOIN league_members lm_self  ON lm_self.league_id = lm_owner.league_id
                WHERE r.id = weekly_lineups.roster_id
                  AND lm_self.user_id = auth.uid()
            )
        );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ---------------------------------------------------------------------------
-- waivers policies
-- ---------------------------------------------------------------------------

-- Full access to own claims.
DO $$
BEGIN
    CREATE POLICY "waivers_own_claims_all"
        ON waivers
        FOR ALL
        TO authenticated
        USING (
            EXISTS (
                SELECT 1
                FROM league_members lm
                WHERE lm.id = waivers.member_id
                  AND lm.user_id = auth.uid()
            )
        )
        WITH CHECK (
            EXISTS (
                SELECT 1
                FROM league_members lm
                WHERE lm.id = waivers.member_id
                  AND lm.user_id = auth.uid()
            )
        );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- All league members can see waiver activity in their league (transparency).
DO $$
BEGIN
    CREATE POLICY "waivers_league_members_read"
        ON waivers
        FOR SELECT
        TO authenticated
        USING (
            EXISTS (
                SELECT 1
                FROM league_members lm_owner
                JOIN league_members lm_self
                  ON lm_self.league_id = lm_owner.league_id
                WHERE lm_owner.id = waivers.member_id
                  AND lm_self.user_id = auth.uid()
            )
        );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ---------------------------------------------------------------------------
-- trades policies
-- ---------------------------------------------------------------------------

-- All league members can read all trades (trade log is public within league).
DO $$
BEGIN
    CREATE POLICY "trades_league_members_read"
        ON trades
        FOR SELECT
        TO authenticated
        USING (
            EXISTS (
                SELECT 1
                FROM league_members lm
                WHERE lm.league_id = trades.league_id
                  AND lm.user_id = auth.uid()
            )
        );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Only the proposer can create a trade.
DO $$
BEGIN
    CREATE POLICY "trades_proposer_insert"
        ON trades
        FOR INSERT
        TO authenticated
        WITH CHECK (
            EXISTS (
                SELECT 1
                FROM league_members lm
                WHERE lm.id = trades.proposer_id
                  AND lm.user_id = auth.uid()
            )
        );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Proposer or receiver can update (accept / reject / veto flow).
-- Field-level validation is enforced at the FastAPI layer.
DO $$
BEGIN
    CREATE POLICY "trades_participants_update"
        ON trades
        FOR UPDATE
        TO authenticated
        USING (
            EXISTS (
                SELECT 1
                FROM league_members lm
                WHERE lm.id IN (trades.proposer_id, trades.receiver_id)
                  AND lm.user_id = auth.uid()
            )
        );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ---------------------------------------------------------------------------
-- trade_players policies
-- ---------------------------------------------------------------------------

-- Any league member can read all trade_players for trades in their league.
DO $$
BEGIN
    CREATE POLICY "trade_players_league_members_read"
        ON trade_players
        FOR SELECT
        TO authenticated
        USING (
            EXISTS (
                SELECT 1
                FROM trades t
                JOIN league_members lm ON lm.league_id = t.league_id
                WHERE t.id = trade_players.trade_id
                  AND lm.user_id = auth.uid()
            )
        );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Only the trade proposer can insert trade_players rows.
DO $$
BEGIN
    CREATE POLICY "trade_players_proposer_insert"
        ON trade_players
        FOR INSERT
        TO authenticated
        WITH CHECK (
            EXISTS (
                SELECT 1
                FROM trades t
                JOIN league_members lm ON lm.id = t.proposer_id
                WHERE t.id = trade_players.trade_id
                  AND lm.user_id = auth.uid()
            )
        );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- fantasy_scores_staging: no policies.
-- RLS is enabled but no policy = deny all for authenticated role by default.
-- FastAPI uses service role which bypasses RLS entirely.


-- =============================================================================
-- 7. GRANT statements
-- =============================================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON weekly_lineups  TO authenticated;
GRANT SELECT, INSERT, UPDATE         ON waivers         TO authenticated;
GRANT SELECT, INSERT, UPDATE         ON trades          TO authenticated;
GRANT SELECT, INSERT                 ON trade_players   TO authenticated;
-- fantasy_scores_staging: intentionally omitted -- service role only.


-- =============================================================================
-- End of migration 002 -- Phase 3 additions
-- =============================================================================
-- Tables created : weekly_lineups, waivers, trades, trade_players,
--                  fantasy_scores_staging
-- Column added   : drafts.manager_order
-- RLS enabled on : all 5 new tables
-- Apply          : Supabase SQL Editor or psql $DATABASE_URL -f 002_phase3_additions.sql
-- =============================================================================