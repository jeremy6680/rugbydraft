-- Migration 003: add external_id columns to players and real_matches
-- Bridge between silver pipeline IDs and PostgreSQL UUIDs (D-031).

ALTER TABLE players      ADD COLUMN IF NOT EXISTS external_id TEXT;
ALTER TABLE real_matches ADD COLUMN IF NOT EXISTS external_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_players_external_id
    ON players (external_id) WHERE external_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_real_matches_external_id
    ON real_matches (external_id) WHERE external_id IS NOT NULL;