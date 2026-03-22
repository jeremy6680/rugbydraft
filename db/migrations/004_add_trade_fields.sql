-- Migration 004: add missing columns and indexes to trades table
-- Adds veto_at, cancelled_at, completed_at for full audit trail (D-035).
-- Adds performance indexes for trade_service polling queries.
--
-- Safe to run multiple times (IF NOT EXISTS / IF NOT EXISTS on indexes).

-- ---------------------------------------------------------------------------
-- 1. Add missing audit timestamp columns
-- ---------------------------------------------------------------------------

ALTER TABLE trades
    ADD COLUMN IF NOT EXISTS veto_at       TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS cancelled_at  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS completed_at  TIMESTAMPTZ;

-- ---------------------------------------------------------------------------
-- 2. Add check constraint on status
-- Enforces the state machine at DB level — catches any bug that bypasses
-- the processor and writes directly to the DB.
-- ---------------------------------------------------------------------------

ALTER TABLE trades
    DROP CONSTRAINT IF EXISTS trades_status_check;

ALTER TABLE trades
    ADD CONSTRAINT trades_status_check
    CHECK (status IN (
        'pending',
        'accepted',
        'rejected',
        'cancelled',
        'completed',
        'vetoed'
    ));

-- ---------------------------------------------------------------------------
-- 3. Add check constraint on trade_players direction
-- ---------------------------------------------------------------------------

ALTER TABLE trade_players
    DROP CONSTRAINT IF EXISTS trade_players_direction_check;

ALTER TABLE trade_players
    ADD CONSTRAINT trade_players_direction_check
    CHECK (direction IN ('out', 'in'));

-- ---------------------------------------------------------------------------
-- 4. Performance indexes
-- ---------------------------------------------------------------------------

-- Polling query: find all ACCEPTED trades with expired veto deadline.
-- trade_service runs this every few minutes.
CREATE INDEX IF NOT EXISTS idx_trades_status
    ON trades (status);

-- Most common query: "all trades in this league" (leaderboard, log page).
CREATE INDEX IF NOT EXISTS idx_trades_league_status
    ON trades (league_id, status);

-- Proposer inbox: "my pending trades".
CREATE INDEX IF NOT EXISTS idx_trades_proposer_status
    ON trades (proposer_id, status);

-- Receiver inbox: "trades waiting for my response".
CREATE INDEX IF NOT EXISTS idx_trades_receiver_status
    ON trades (receiver_id, status);

-- trade_players lookup: all players involved in a given trade.
CREATE INDEX IF NOT EXISTS idx_trade_players_trade_id
    ON trade_players (trade_id);

-- ---------------------------------------------------------------------------
-- 5. Row Level Security — trades
-- A manager can see all trades in leagues they belong to.
-- A manager can only propose trades as themselves.
-- A manager can only accept/reject trades addressed to them.
-- ---------------------------------------------------------------------------

ALTER TABLE trades ENABLE ROW LEVEL SECURITY;

-- Read: visible to all members of the league (for the trade log, CDC §9.2).
DROP POLICY IF EXISTS trades_select_policy ON trades;
CREATE POLICY trades_select_policy ON trades
    FOR SELECT
    USING (
        league_id IN (
            SELECT league_id
            FROM league_members
            WHERE user_id = auth.uid()
        )
    );

-- Insert: only the proposer themselves (proposer_id must match auth.uid()).
DROP POLICY IF EXISTS trades_insert_policy ON trades;
CREATE POLICY trades_insert_policy ON trades
    FOR INSERT
    WITH CHECK (
        proposer_id IN (
            SELECT id FROM league_members
            WHERE user_id = auth.uid()
              AND league_id = trades.league_id
        )
    );

-- Update: only FastAPI service role (via supabase_service_role_key).
-- All status transitions go through FastAPI processor — never direct client writes.
DROP POLICY IF EXISTS trades_update_policy ON trades;
CREATE POLICY trades_update_policy ON trades
    FOR UPDATE
    USING (
        current_setting('role') = 'service_role'
    );

-- ---------------------------------------------------------------------------
-- 6. Row Level Security — trade_players
-- Readable by all league members (same logic as trades).
-- Writable only by service role.
-- ---------------------------------------------------------------------------

ALTER TABLE trade_players ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS trade_players_select_policy ON trade_players;
CREATE POLICY trade_players_select_policy ON trade_players
    FOR SELECT
    USING (
        trade_id IN (
            SELECT id FROM trades
            WHERE league_id IN (
                SELECT league_id
                FROM league_members
                WHERE user_id = auth.uid()
            )
        )
    );

DROP POLICY IF EXISTS trade_players_insert_policy ON trade_players;
CREATE POLICY trade_players_insert_policy ON trade_players
    FOR INSERT
    WITH CHECK (
        current_setting('role') = 'service_role'
    );

DROP POLICY IF EXISTS trade_players_update_policy ON trade_players;
CREATE POLICY trade_players_update_policy ON trade_players
    FOR UPDATE
    USING (
        current_setting('role') = 'service_role'
    );