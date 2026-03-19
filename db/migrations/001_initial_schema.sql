-- =============================================================================
-- RugbyDraft — Initial PostgreSQL Schema
-- Migration: 001_initial_schema.sql
-- Date: 2026-03-18
-- Description: Full schema for RugbyDraft V1.
--              Includes all tables, enums, RLS policies, and indexes.
--              ai_reports table is intentionally excluded (private repo, Phase 5).
--              Stripe columns exist in users but are populated by private repo only.
-- =============================================================================

-- Enable required PostgreSQL extensions
-- uuid-ossp: UUID generation (uuid_generate_v4)
-- pgcrypto:  Cryptographic functions (used for access code generation)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";


-- =============================================================================
-- ENUMS
-- =============================================================================

-- Subscription plan for a user
CREATE TYPE plan_type AS ENUM ('free', 'pro', 'pro_ai');

-- Competition scope: international (nationality constraints) or club (club constraints)
CREATE TYPE competition_type AS ENUM ('international', 'club');

-- Competition lifecycle status
CREATE TYPE competition_status AS ENUM ('upcoming', 'active', 'completed');

-- Player availability for a given competition
CREATE TYPE player_availability_status AS ENUM (
    'available',    -- Fit and selectable
    'injured',      -- Out with injury
    'suspended',    -- Serving a ban
    'doubt'         -- Questionable, may or may not play
);

-- Draft lifecycle status
CREATE TYPE draft_status AS ENUM (
    'pending',      -- Scheduled but not started
    'active',       -- Currently running
    'completed',    -- All picks made, rosters valid
    'cancelled'     -- Abandoned before completion
);

-- Roster slot type (starter, bench, or infirmary)
CREATE TYPE slot_type AS ENUM ('starter', 'bench', 'ir');

-- Player positions — all 8 positions from CDC section 6.1
CREATE TYPE position_type AS ENUM (
    'prop',             -- Pilier
    'hooker',           -- Talonneur
    'lock',             -- Deuxième ligne
    'flanker',          -- Troisième ligne
    'number_8',         -- Numéro 8 (third row, distinct from flanker for roster constraints)
    'scrum_half',       -- Demi de mêlée
    'fly_half',         -- Demi d'ouverture
    'centre',           -- Centre
    'wing',             -- Ailier
    'fullback'          -- Arrière
);

-- Waiver request lifecycle
CREATE TYPE waiver_status AS ENUM ('pending', 'processed', 'cancelled');

-- Trade proposal lifecycle
CREATE TYPE trade_status AS ENUM (
    'pending',      -- Awaiting receiver response
    'accepted',     -- Accepted, awaiting veto window
    'rejected',     -- Rejected by receiver
    'vetoed',       -- Blocked by commissioner
    'completed',    -- Executed, rosters updated
    'cancelled'     -- Withdrawn by proposer
);

-- Direction of a player in a trade (from proposer's perspective)
CREATE TYPE trade_direction AS ENUM ('out', 'in');


-- =============================================================================
-- COMPETITIONS
-- =============================================================================

CREATE TABLE competitions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT NOT NULL,                          -- e.g. "Six Nations 2026"
    slug            TEXT NOT NULL UNIQUE,                   -- e.g. "six-nations-2026" — for URLs
    type            competition_type NOT NULL,              -- international or club
    season          TEXT NOT NULL,                          -- e.g. "2026"
    is_premium      BOOLEAN NOT NULL DEFAULT FALSE,         -- TRUE = Pro plan required
    status          competition_status NOT NULL DEFAULT 'upcoming',
    total_rounds    INT NOT NULL,                           -- Total number of rounds in the competition
    -- Constraint settings: max players from same nationality (international) or same club (club)
    -- NULL means no constraint. Stored at competition level, overridable at league level via settings JSONB.
    default_nationality_limit INT,                         -- international competitions
    default_club_limit        INT,                         -- club competitions
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE competitions IS 'Rugby competitions supported by the platform (Six Nations, Top 14, etc.)';
COMMENT ON COLUMN competitions.is_premium IS 'TRUE = requires Pro or Pro+IA plan to create or join leagues';
COMMENT ON COLUMN competitions.default_nationality_limit IS 'Max players from same nationality per roster. Overridable per league.';


-- =============================================================================
-- COMPETITION ROUNDS
-- =============================================================================

CREATE TABLE competition_rounds (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    competition_id  UUID NOT NULL REFERENCES competitions(id) ON DELETE CASCADE,
    round_number    INT NOT NULL,
    label           TEXT,                                   -- Optional display label, e.g. "Round 1", "Semi-finals"
    start_date      DATE,
    end_date        DATE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (competition_id, round_number)
);

COMMENT ON TABLE competition_rounds IS 'Individual rounds (matchdays) within a competition';


-- =============================================================================
-- REAL MATCHES
-- =============================================================================

-- Match status from the data provider
CREATE TYPE match_status AS ENUM (
    'scheduled',    -- Future match, not yet started
    'live',         -- Currently in progress
    'finished',     -- Final score confirmed
    'postponed',    -- Rescheduled
    'cancelled'     -- Will not be played
);

CREATE TABLE real_matches (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    competition_round_id    UUID NOT NULL REFERENCES competition_rounds(id) ON DELETE CASCADE,
    external_id             TEXT,                           -- Provider's match ID (for API sync)
    home_team               TEXT NOT NULL,
    away_team               TEXT NOT NULL,
    kickoff_at              TIMESTAMPTZ,                    -- Used for progressive lineup lock
    status                  match_status NOT NULL DEFAULT 'scheduled',
    home_score              INT,
    away_score              INT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE real_matches IS 'Real-world rugby matches. kickoff_at drives progressive lineup locking.';
COMMENT ON COLUMN real_matches.external_id IS 'ID used to identify this match in the external data provider API';


-- =============================================================================
-- PLAYERS
-- =============================================================================

CREATE TABLE players (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    external_id     TEXT,                                   -- Provider's player ID
    name            TEXT NOT NULL,
    nationality     TEXT,                                   -- ISO 3166-1 alpha-2, e.g. "FR", "NZ"
    club            TEXT,                                   -- Club name (relevant for club competitions)
    -- positions is an array because players can have multiple positions
    -- e.g. Thomas Ramos: ARRAY['fly_half', 'fullback']
    -- Indexed with GIN for efficient containment queries
    positions       position_type[] NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_players_positions ON players USING GIN (positions);
CREATE INDEX idx_players_nationality ON players (nationality);
CREATE INDEX idx_players_club ON players (club);
CREATE INDEX idx_players_external_id ON players (external_id);

COMMENT ON TABLE players IS 'All rugby players eligible for drafting. positions[] supports multi-position players.';
COMMENT ON COLUMN players.positions IS 'Array of positions. Multi-position players can be played in any of their positions per round.';


-- =============================================================================
-- PLAYER AVAILABILITY
-- =============================================================================

CREATE TABLE player_availability (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    player_id       UUID NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    competition_id  UUID NOT NULL REFERENCES competitions(id) ON DELETE CASCADE,
    status          player_availability_status NOT NULL DEFAULT 'available',
    injury_since    DATE,                                   -- Date when injury/suspension started
    expected_return DATE,                                   -- Estimated return date (nullable)
    notes           TEXT,                                   -- Optional context (injury type, etc.)
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (player_id, competition_id)
);

COMMENT ON TABLE player_availability IS 'Player injury and suspension tracking per competition';


-- =============================================================================
-- USERS
-- =============================================================================
-- Extends Supabase Auth (auth.users) with application-specific profile data.
-- The id column MUST match auth.users.id (set on user creation via trigger or RPC).
-- Stripe columns are populated by the private repo in Phase 5 only.
-- =============================================================================

CREATE TABLE users (
    -- References the Supabase auth user — same UUID
    id                  UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email               TEXT NOT NULL UNIQUE,
    display_name        TEXT,
    avatar_url          TEXT,

    -- i18n: user's display locale preference (independent of competition access)
    -- See DECISIONS.md D-006, D-007
    locale              TEXT NOT NULL DEFAULT 'fr',        -- BCP 47 tag: 'fr', 'en', 'es', 'it'

    -- Subscription plan — populated by Stripe webhooks (private repo, Phase 5)
    -- Default 'free'. plan_expires_at is NULL for lifetime free or active subscriptions.
    plan                plan_type NOT NULL DEFAULT 'free',
    plan_expires_at     TIMESTAMPTZ,                       -- NULL = no expiry (free or valid sub)
    stripe_customer_id  TEXT,                              -- Stripe customer ID (private repo)

    -- Staff AI: which league has AI staff enabled (max 1 league, Pro+IA plan only)
    -- NULL = AI staff not active on any league
    ai_league_id        UUID,                              -- FK added after leagues table (see ALTER below)

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE users IS 'User profiles extending Supabase Auth. Stripe columns populated by private repo in Phase 5.';
COMMENT ON COLUMN users.locale IS 'BCP 47 locale for UI display. Independent of competition access (see D-007).';
COMMENT ON COLUMN users.plan IS 'Subscription plan. Defaults to free. Updated by Stripe webhooks.';
COMMENT ON COLUMN users.ai_league_id IS 'League where AI staff is active. Max 1 per Pro+IA user. NULL = inactive.';


-- =============================================================================
-- LEAGUES
-- =============================================================================

CREATE TABLE leagues (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                TEXT NOT NULL,
    competition_id      UUID NOT NULL REFERENCES competitions(id),
    commissioner_id     UUID NOT NULL REFERENCES users(id),
    -- visibility: 'private' (invite/code only) or 'public' (directory listing, V2)
    visibility          TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'public')),
    -- 6-character alphanumeric access code for private leagues
    access_code         TEXT UNIQUE,
    -- Flexible league settings stored as JSONB:
    -- { pick_timer_seconds: 120, nationality_limit: 4, club_limit: null,
    --   trade_veto_enabled: true, min_managers: 2, max_managers: 6 }
    settings            JSONB NOT NULL DEFAULT '{}',
    is_archived         BOOLEAN NOT NULL DEFAULT FALSE,    -- TRUE once competition ends
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_leagues_competition_id ON leagues (competition_id);
CREATE INDEX idx_leagues_commissioner_id ON leagues (commissioner_id);

COMMENT ON TABLE leagues IS 'A league is a group of managers playing a competition together.';
COMMENT ON COLUMN leagues.settings IS 'JSONB config: pick_timer_seconds, nationality_limit, club_limit, trade_veto_enabled, etc.';
COMMENT ON COLUMN leagues.is_archived IS 'TRUE when the competition season ends. Archived leagues do not count toward commissioner quota.';

-- Now that leagues exists, add the FK from users.ai_league_id
ALTER TABLE users
    ADD CONSTRAINT fk_users_ai_league
    FOREIGN KEY (ai_league_id) REFERENCES leagues(id) ON DELETE SET NULL;


-- =============================================================================
-- LEAGUE MEMBERS
-- =============================================================================

CREATE TABLE league_members (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    league_id       UUID NOT NULL REFERENCES leagues(id) ON DELETE CASCADE,
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,  -- NULL for ghost teams
    is_ghost_team   BOOLEAN NOT NULL DEFAULT FALSE,
    -- Ghost team display name, e.g. "Les Fantômes de Cardiff"
    ghost_name      TEXT,
    joined_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (league_id, user_id)
);

COMMENT ON TABLE league_members IS 'Users (or ghost teams) participating in a league.';
COMMENT ON COLUMN league_members.user_id IS 'NULL for ghost teams (is_ghost_team = TRUE).';
COMMENT ON COLUMN league_members.ghost_name IS 'Display name for ghost teams, randomly generated.';


-- =============================================================================
-- LEAGUE FIXTURES
-- =============================================================================
-- Head-to-head matchups between league members for each round.
-- Drawn at random just before draft opens (CDC section 7.6).
-- =============================================================================

CREATE TABLE league_fixtures (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    league_id           UUID NOT NULL REFERENCES leagues(id) ON DELETE CASCADE,
    round_number        INT NOT NULL,
    home_member_id      UUID NOT NULL REFERENCES league_members(id),
    away_member_id      UUID NOT NULL REFERENCES league_members(id),
    -- Scores are denormalized here for quick leaderboard queries.
    -- Source of truth is fantasy_scores.
    home_score          NUMERIC(8, 2),
    away_score          NUMERIC(8, 2),
    CHECK (home_member_id <> away_member_id)
);

CREATE INDEX idx_league_fixtures_league_round ON league_fixtures (league_id, round_number);

COMMENT ON TABLE league_fixtures IS 'Head-to-head schedule for a league. Drawn before draft. Scores denormalized for performance.';


-- =============================================================================
-- DRAFTS
-- =============================================================================

CREATE TABLE drafts (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    league_id               UUID NOT NULL UNIQUE REFERENCES leagues(id) ON DELETE CASCADE,
    status                  draft_status NOT NULL DEFAULT 'pending',
    scheduled_at            TIMESTAMPTZ,                   -- When the draft is scheduled to start
    started_at              TIMESTAMPTZ,                   -- Actual start time
    completed_at            TIMESTAMPTZ,
    pick_timer_seconds      INT NOT NULL DEFAULT 120       -- From league settings, denormalized here
                            CHECK (pick_timer_seconds BETWEEN 30 AND 180),
    -- Total picks = total roster size × number of members
    total_picks             INT NOT NULL,
    current_pick_number     INT NOT NULL DEFAULT 0,        -- 0 = draft not started
    is_assisted_mode        BOOLEAN NOT NULL DEFAULT FALSE, -- TRUE = commissioner enters picks manually
    -- Snake order: JSON array of member IDs in round 1 order
    -- e.g. ["uuid-1", "uuid-2", "uuid-3"]
    -- The snake algorithm mirrors this order for even rounds.
    draft_order             JSONB,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE drafts IS 'One draft per league. FastAPI manages state in memory; this table persists the final record.';
COMMENT ON COLUMN drafts.draft_order IS 'JSON array of member UUIDs in round-1 order. Snake algorithm mirrors for even rounds.';
COMMENT ON COLUMN drafts.is_assisted_mode IS 'If TRUE, commissioner enters all picks manually with no timer.';


-- =============================================================================
-- DRAFT PICKS
-- =============================================================================

CREATE TABLE draft_picks (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    draft_id                UUID NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
    pick_number             INT NOT NULL,                  -- Global pick number (1-based)
    round_number            INT NOT NULL,                  -- Round within the draft
    member_id               UUID NOT NULL REFERENCES league_members(id),
    player_id               UUID NOT NULL REFERENCES players(id),
    picked_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_autodraft            BOOLEAN NOT NULL DEFAULT FALSE, -- TRUE if picked by autodraft algorithm
    entered_by_commissioner BOOLEAN NOT NULL DEFAULT FALSE, -- TRUE in assisted mode
    UNIQUE (draft_id, pick_number),
    UNIQUE (draft_id, player_id)                           -- A player can only be picked once per draft
);

CREATE INDEX idx_draft_picks_draft_id ON draft_picks (draft_id);
CREATE INDEX idx_draft_picks_member_id ON draft_picks (member_id);

COMMENT ON TABLE draft_picks IS 'Immutable pick log. Each pick recorded with metadata (autodraft, commissioner entry).';


-- =============================================================================
-- ROSTERS
-- =============================================================================
-- One roster per league member. Created when draft completes.
-- =============================================================================

CREATE TABLE rosters (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    league_id       UUID NOT NULL REFERENCES leagues(id) ON DELETE CASCADE,
    member_id       UUID NOT NULL REFERENCES league_members(id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (league_id, member_id)
);

COMMENT ON TABLE rosters IS 'One roster per member per league. Built from draft picks.';


-- =============================================================================
-- ROSTER SLOTS
-- =============================================================================
-- The current state of the roster: who is starter, bench, or on IR.
-- This changes over the season via waivers and trades.
-- =============================================================================

CREATE TABLE roster_slots (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    roster_id       UUID NOT NULL REFERENCES rosters(id) ON DELETE CASCADE,
    player_id       UUID NOT NULL REFERENCES players(id),
    slot_type       slot_type NOT NULL DEFAULT 'bench',
    -- IR capacity: max 3 players per roster (enforced at application level)
    added_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (roster_id, player_id)
);

CREATE INDEX idx_roster_slots_roster_id ON roster_slots (roster_id);

COMMENT ON TABLE roster_slots IS 'Current player assignments on a roster (starter/bench/ir). Max 3 IR slots enforced in app.';


-- =============================================================================
-- WEEKLY LINEUPS
-- =============================================================================
-- The lineup a manager submits for a specific round.
-- Locking is progressive: locked per match kickoff, not per round.
-- =============================================================================

CREATE TABLE weekly_lineups (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    roster_id       UUID NOT NULL REFERENCES rosters(id) ON DELETE CASCADE,
    round_id        UUID NOT NULL REFERENCES competition_rounds(id),
    player_id       UUID NOT NULL REFERENCES players(id),
    -- For multi-position players: the position they play THIS round
    -- Must be one of player.positions[]
    position        position_type NOT NULL,
    is_captain      BOOLEAN NOT NULL DEFAULT FALSE,        -- Captain: ×1.5 multiplier
    is_kicker       BOOLEAN NOT NULL DEFAULT FALSE,        -- Designated kicker: scores on penalties/conversions
    -- Locked at kickoff of the player's team match
    locked_at       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (roster_id, round_id, player_id)
);

CREATE INDEX idx_weekly_lineups_roster_round ON weekly_lineups (roster_id, round_id);

COMMENT ON TABLE weekly_lineups IS 'Per-round lineup submission. Progressive lock at kickoff. Captain and kicker flags here.';
COMMENT ON COLUMN weekly_lineups.position IS 'Position played this round. For multi-position players, chosen by manager before kickoff.';
COMMENT ON COLUMN weekly_lineups.locked_at IS 'Set to kickoff_at of the player''s team match. NULL = not yet locked.';


-- =============================================================================
-- WAIVERS
-- =============================================================================

CREATE TABLE waivers (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    league_id       UUID NOT NULL REFERENCES leagues(id) ON DELETE CASCADE,
    round_id        UUID NOT NULL REFERENCES competition_rounds(id),
    member_id       UUID NOT NULL REFERENCES league_members(id),
    -- drop_player_id: player being released to the pool (can be NULL for pure additions)
    drop_player_id  UUID REFERENCES players(id),
    -- add_player_id: player being claimed from the pool
    add_player_id   UUID NOT NULL REFERENCES players(id),
    -- Priority at time of submission: lower rank = higher priority (worst team picks first)
    priority        INT NOT NULL,
    status          waiver_status NOT NULL DEFAULT 'pending',
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at    TIMESTAMPTZ
);

CREATE INDEX idx_waivers_league_round ON waivers (league_id, round_id);

COMMENT ON TABLE waivers IS 'Waiver requests. Processed Wednesday morning in priority order (lowest ranked first).';
COMMENT ON COLUMN waivers.priority IS 'Lower value = higher priority. Recalculated after each waiver cycle from league standings.';


-- =============================================================================
-- TRADES
-- =============================================================================

CREATE TABLE trades (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    league_id       UUID NOT NULL REFERENCES leagues(id) ON DELETE CASCADE,
    proposer_id     UUID NOT NULL REFERENCES league_members(id),
    receiver_id     UUID NOT NULL REFERENCES league_members(id),
    status          trade_status NOT NULL DEFAULT 'pending',
    -- Commissioner veto window: 24h after trade acceptance (if trade_veto_enabled in league settings)
    veto_deadline   TIMESTAMPTZ,
    -- Commissioner must provide a reason when vetoing
    veto_reason     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (proposer_id <> receiver_id)
);

CREATE INDEX idx_trades_league_id ON trades (league_id);
CREATE INDEX idx_trades_proposer ON trades (proposer_id);
CREATE INDEX idx_trades_receiver ON trades (receiver_id);

COMMENT ON TABLE trades IS 'Trade proposals between managers. Blocked after mid-season (enforced in app).';
COMMENT ON COLUMN trades.veto_deadline IS '24h after acceptance if commissioner veto is enabled. NULL = veto not enabled.';


-- =============================================================================
-- TRADE PLAYERS
-- =============================================================================
-- The players involved in a trade. A trade can be 1v1, 1v2, or 1v3.
-- =============================================================================

CREATE TABLE trade_players (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    trade_id        UUID NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
    player_id       UUID NOT NULL REFERENCES players(id),
    -- direction: 'out' from proposer, 'in' to proposer (from proposer's perspective)
    direction       trade_direction NOT NULL,
    member_id       UUID NOT NULL REFERENCES league_members(id)
);

COMMENT ON TABLE trade_players IS 'Players involved in a trade. direction is from proposer''s perspective.';


-- =============================================================================
-- FANTASY SCORES
-- =============================================================================
-- Production scores table. Only updated via atomic commit from staging.
-- Never written to directly by the pipeline during processing.
-- =============================================================================

CREATE TABLE fantasy_scores (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    roster_id           UUID NOT NULL REFERENCES rosters(id) ON DELETE CASCADE,
    round_id            UUID NOT NULL REFERENCES competition_rounds(id),
    player_id           UUID NOT NULL REFERENCES players(id),
    -- Detailed breakdown of points per action category (for stats display)
    -- e.g. { "tries": 5, "tackles": 2.5, "conversions": 4, "penalties_missed": -1 }
    points_breakdown    JSONB NOT NULL DEFAULT '{}',
    raw_points          NUMERIC(8, 2) NOT NULL DEFAULT 0,   -- Before captain multiplier
    captain_multiplier  NUMERIC(4, 2) NOT NULL DEFAULT 1.0, -- 1.0 or 1.5
    total_points        NUMERIC(8, 2) NOT NULL DEFAULT 0,   -- raw_points × captain_multiplier (rounded to 0.5)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (roster_id, round_id, player_id)
);

CREATE INDEX idx_fantasy_scores_roster_round ON fantasy_scores (roster_id, round_id);
CREATE INDEX idx_fantasy_scores_player_round ON fantasy_scores (player_id, round_id);

COMMENT ON TABLE fantasy_scores IS 'Fantasy points per player per round. Written ONLY via atomic commit from fantasy_scores_staging.';
COMMENT ON COLUMN fantasy_scores.points_breakdown IS 'JSONB breakdown of points per action. Used for stats display page.';
COMMENT ON COLUMN fantasy_scores.captain_multiplier IS '1.0 for standard players, 1.5 for captain (rounded up to nearest 0.5).';


-- =============================================================================
-- FANTASY SCORES STAGING
-- =============================================================================
-- Identical structure to fantasy_scores. The pipeline writes here first.
-- Once the full run succeeds, a single transaction copies staging → fantasy_scores.
-- See DECISIONS.md D-003.
-- =============================================================================

CREATE TABLE fantasy_scores_staging (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    roster_id           UUID NOT NULL REFERENCES rosters(id) ON DELETE CASCADE,
    round_id            UUID NOT NULL REFERENCES competition_rounds(id),
    player_id           UUID NOT NULL REFERENCES players(id),
    points_breakdown    JSONB NOT NULL DEFAULT '{}',
    raw_points          NUMERIC(8, 2) NOT NULL DEFAULT 0,
    captain_multiplier  NUMERIC(4, 2) NOT NULL DEFAULT 1.0,
    total_points        NUMERIC(8, 2) NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (roster_id, round_id, player_id)
);

COMMENT ON TABLE fantasy_scores_staging IS 'Staging table for the atomic commit pattern. Truncated at pipeline start, committed to fantasy_scores on success.';


-- =============================================================================
-- LEAGUE STANDINGS
-- =============================================================================

CREATE TABLE league_standings (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    league_id       UUID NOT NULL REFERENCES leagues(id) ON DELETE CASCADE,
    member_id       UUID NOT NULL REFERENCES league_members(id),
    wins            INT NOT NULL DEFAULT 0,
    losses          INT NOT NULL DEFAULT 0,
    draws           INT NOT NULL DEFAULT 0,
    total_points    NUMERIC(10, 2) NOT NULL DEFAULT 0,      -- Sum of all fantasy points across rounds
    rank            INT,                                    -- Current rank in the league (NULL until first round)
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (league_id, member_id)
);

CREATE INDEX idx_league_standings_league ON league_standings (league_id, rank);

COMMENT ON TABLE league_standings IS 'Running standings per league. Updated after each round via atomic commit.';


-- =============================================================================
-- LEAGUE ARCHIVES
-- =============================================================================

CREATE TABLE league_archives (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    league_id       UUID NOT NULL REFERENCES leagues(id) ON DELETE CASCADE,
    season          TEXT NOT NULL,                          -- e.g. "2026"
    -- Full final standings snapshot stored as JSONB for historical display
    -- e.g. [{ rank: 1, member_id: "...", display_name: "...", total_points: 142.5 }]
    final_standings JSONB NOT NULL DEFAULT '[]',
    archived_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (league_id, season)
);

COMMENT ON TABLE league_archives IS 'End-of-season snapshot. Persisted indefinitely for user history (CDC section 5.4).';


-- =============================================================================
-- UPDATED_AT TRIGGER FUNCTION
-- =============================================================================
-- Automatically updates the updated_at column on any UPDATE.
-- Applied to all tables that have an updated_at column.
-- =============================================================================

CREATE OR REPLACE FUNCTION trigger_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to all tables with updated_at
CREATE TRIGGER set_updated_at BEFORE UPDATE ON competitions
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

CREATE TRIGGER set_updated_at BEFORE UPDATE ON real_matches
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

CREATE TRIGGER set_updated_at BEFORE UPDATE ON players
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

CREATE TRIGGER set_updated_at BEFORE UPDATE ON player_availability
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

CREATE TRIGGER set_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

CREATE TRIGGER set_updated_at BEFORE UPDATE ON leagues
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

CREATE TRIGGER set_updated_at BEFORE UPDATE ON drafts
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

CREATE TRIGGER set_updated_at BEFORE UPDATE ON weekly_lineups
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

CREATE TRIGGER set_updated_at BEFORE UPDATE ON trades
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

CREATE TRIGGER set_updated_at BEFORE UPDATE ON fantasy_scores
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

CREATE TRIGGER set_updated_at BEFORE UPDATE ON fantasy_scores_staging
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

CREATE TRIGGER set_updated_at BEFORE UPDATE ON league_standings
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


-- =============================================================================
-- ROW LEVEL SECURITY (RLS)
-- =============================================================================
-- Security is enforced at the database level, not only at the application level.
-- Every table has RLS enabled. Policies follow the principle of least privilege.
-- Service role (used by FastAPI and pipelines) bypasses RLS.
-- Authenticated users can only see data they are entitled to.
-- =============================================================================

-- Enable RLS on all tables
ALTER TABLE competitions           ENABLE ROW LEVEL SECURITY;
ALTER TABLE competition_rounds     ENABLE ROW LEVEL SECURITY;
ALTER TABLE real_matches           ENABLE ROW LEVEL SECURITY;
ALTER TABLE players                ENABLE ROW LEVEL SECURITY;
ALTER TABLE player_availability    ENABLE ROW LEVEL SECURITY;
ALTER TABLE users                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE leagues                ENABLE ROW LEVEL SECURITY;
ALTER TABLE league_members         ENABLE ROW LEVEL SECURITY;
ALTER TABLE league_fixtures        ENABLE ROW LEVEL SECURITY;
ALTER TABLE drafts                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE draft_picks            ENABLE ROW LEVEL SECURITY;
ALTER TABLE rosters                ENABLE ROW LEVEL SECURITY;
ALTER TABLE roster_slots           ENABLE ROW LEVEL SECURITY;
ALTER TABLE weekly_lineups         ENABLE ROW LEVEL SECURITY;
ALTER TABLE waivers                ENABLE ROW LEVEL SECURITY;
ALTER TABLE trades                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE trade_players          ENABLE ROW LEVEL SECURITY;
ALTER TABLE fantasy_scores         ENABLE ROW LEVEL SECURITY;
ALTER TABLE fantasy_scores_staging ENABLE ROW LEVEL SECURITY;
ALTER TABLE league_standings       ENABLE ROW LEVEL SECURITY;
ALTER TABLE league_archives        ENABLE ROW LEVEL SECURITY;

-- ---------------------------------------------------------------------------
-- PUBLIC READ: competitions, competition_rounds, real_matches, players
-- All authenticated users can read these — they are platform-wide reference data.
-- ---------------------------------------------------------------------------

CREATE POLICY "Authenticated users can read competitions"
    ON competitions FOR SELECT
    TO authenticated
    USING (TRUE);

CREATE POLICY "Authenticated users can read competition_rounds"
    ON competition_rounds FOR SELECT
    TO authenticated
    USING (TRUE);

CREATE POLICY "Authenticated users can read real_matches"
    ON real_matches FOR SELECT
    TO authenticated
    USING (TRUE);

CREATE POLICY "Authenticated users can read players"
    ON players FOR SELECT
    TO authenticated
    USING (TRUE);

CREATE POLICY "Authenticated users can read player_availability"
    ON player_availability FOR SELECT
    TO authenticated
    USING (TRUE);

-- ---------------------------------------------------------------------------
-- USERS: each user can read and update their own profile only
-- ---------------------------------------------------------------------------

CREATE POLICY "Users can read own profile"
    ON users FOR SELECT
    TO authenticated
    USING (auth.uid() = id);

CREATE POLICY "Users can update own profile"
    ON users FOR UPDATE
    TO authenticated
    USING (auth.uid() = id)
    WITH CHECK (auth.uid() = id);

-- INSERT is handled by the new user trigger (service role), not directly by the client.

-- ---------------------------------------------------------------------------
-- LEAGUES: members can read their leagues; commissioner can update/delete
-- ---------------------------------------------------------------------------

CREATE POLICY "League members can read their leagues"
    ON leagues FOR SELECT
    TO authenticated
    USING (
        id IN (
            SELECT league_id FROM league_members
            WHERE user_id = auth.uid()
        )
        OR commissioner_id = auth.uid()
    );

CREATE POLICY "Commissioner can update their league"
    ON leagues FOR UPDATE
    TO authenticated
    USING (commissioner_id = auth.uid())
    WITH CHECK (commissioner_id = auth.uid());

-- League creation is gated by plan check in FastAPI — not at DB level.
CREATE POLICY "Authenticated users can create leagues"
    ON leagues FOR INSERT
    TO authenticated
    WITH CHECK (commissioner_id = auth.uid());

-- ---------------------------------------------------------------------------
-- LEAGUE MEMBERS: visible to all members of the same league
-- ---------------------------------------------------------------------------

CREATE POLICY "League members can read all members of their leagues"
    ON league_members FOR SELECT
    TO authenticated
    USING (
        league_id IN (
            SELECT league_id FROM league_members
            WHERE user_id = auth.uid()
        )
    );

-- ---------------------------------------------------------------------------
-- LEAGUE FIXTURES: readable by league members
-- ---------------------------------------------------------------------------

CREATE POLICY "League members can read fixtures of their leagues"
    ON league_fixtures FOR SELECT
    TO authenticated
    USING (
        league_id IN (
            SELECT league_id FROM league_members
            WHERE user_id = auth.uid()
        )
    );

-- ---------------------------------------------------------------------------
-- DRAFTS: readable by league members
-- ---------------------------------------------------------------------------

CREATE POLICY "League members can read their draft"
    ON drafts FOR SELECT
    TO authenticated
    USING (
        league_id IN (
            SELECT league_id FROM league_members
            WHERE user_id = auth.uid()
        )
    );

-- ---------------------------------------------------------------------------
-- DRAFT PICKS: readable by all members; write via FastAPI (service role only)
-- ---------------------------------------------------------------------------

CREATE POLICY "League members can read draft picks of their draft"
    ON draft_picks FOR SELECT
    TO authenticated
    USING (
        draft_id IN (
            SELECT d.id FROM drafts d
            JOIN league_members lm ON lm.league_id = d.league_id
            WHERE lm.user_id = auth.uid()
        )
    );

-- ---------------------------------------------------------------------------
-- ROSTERS: a manager can read all rosters in their league
-- (seeing others' rosters is intentional — it's a social game)
-- ---------------------------------------------------------------------------

CREATE POLICY "League members can read all rosters in their league"
    ON rosters FOR SELECT
    TO authenticated
    USING (
        league_id IN (
            SELECT league_id FROM league_members
            WHERE user_id = auth.uid()
        )
    );

-- ---------------------------------------------------------------------------
-- ROSTER SLOTS: readable by league members; manager can edit their own
-- ---------------------------------------------------------------------------

CREATE POLICY "League members can read roster slots in their league"
    ON roster_slots FOR SELECT
    TO authenticated
    USING (
        roster_id IN (
            SELECT r.id FROM rosters r
            JOIN league_members lm ON lm.id = r.member_id
            WHERE lm.user_id = auth.uid()
                OR r.league_id IN (
                    SELECT league_id FROM league_members WHERE user_id = auth.uid()
                )
        )
    );

-- ---------------------------------------------------------------------------
-- WEEKLY LINEUPS: manager can read all lineups in their league,
-- but can only INSERT/UPDATE their own (before lock)
-- ---------------------------------------------------------------------------

CREATE POLICY "League members can read all lineups in their league"
    ON weekly_lineups FOR SELECT
    TO authenticated
    USING (
        roster_id IN (
            SELECT r.id FROM rosters r
            WHERE r.league_id IN (
                SELECT league_id FROM league_members WHERE user_id = auth.uid()
            )
        )
    );

CREATE POLICY "Manager can manage their own lineup"
    ON weekly_lineups FOR ALL
    TO authenticated
    USING (
        roster_id IN (
            SELECT r.id FROM rosters r
            JOIN league_members lm ON lm.id = r.member_id
            WHERE lm.user_id = auth.uid()
        )
    )
    WITH CHECK (
        roster_id IN (
            SELECT r.id FROM rosters r
            JOIN league_members lm ON lm.id = r.member_id
            WHERE lm.user_id = auth.uid()
        )
    );

-- ---------------------------------------------------------------------------
-- WAIVERS: manager can see and manage their own waivers
-- ---------------------------------------------------------------------------

CREATE POLICY "Manager can read own waivers"
    ON waivers FOR SELECT
    TO authenticated
    USING (
        member_id IN (
            SELECT id FROM league_members WHERE user_id = auth.uid()
        )
    );

CREATE POLICY "Manager can submit their own waivers"
    ON waivers FOR INSERT
    TO authenticated
    WITH CHECK (
        member_id IN (
            SELECT id FROM league_members WHERE user_id = auth.uid()
        )
    );

-- ---------------------------------------------------------------------------
-- TRADES: both proposer and receiver can read; proposer can insert
-- ---------------------------------------------------------------------------

CREATE POLICY "Trade participants can read their trades"
    ON trades FOR SELECT
    TO authenticated
    USING (
        proposer_id IN (SELECT id FROM league_members WHERE user_id = auth.uid())
        OR receiver_id IN (SELECT id FROM league_members WHERE user_id = auth.uid())
    );

CREATE POLICY "Manager can propose trades"
    ON trades FOR INSERT
    TO authenticated
    WITH CHECK (
        proposer_id IN (
            SELECT id FROM league_members WHERE user_id = auth.uid()
        )
    );

-- ---------------------------------------------------------------------------
-- TRADE PLAYERS: readable to trade participants
-- ---------------------------------------------------------------------------

CREATE POLICY "Trade participants can read trade players"
    ON trade_players FOR SELECT
    TO authenticated
    USING (
        trade_id IN (
            SELECT t.id FROM trades t
            WHERE t.proposer_id IN (SELECT id FROM league_members WHERE user_id = auth.uid())
               OR t.receiver_id IN (SELECT id FROM league_members WHERE user_id = auth.uid())
        )
    );

-- ---------------------------------------------------------------------------
-- FANTASY SCORES: readable by league members
-- ---------------------------------------------------------------------------

CREATE POLICY "League members can read fantasy scores in their league"
    ON fantasy_scores FOR SELECT
    TO authenticated
    USING (
        roster_id IN (
            SELECT r.id FROM rosters r
            WHERE r.league_id IN (
                SELECT league_id FROM league_members WHERE user_id = auth.uid()
            )
        )
    );

-- staging table: no client access — service role only
-- (RLS enabled but no permissive client policy = effectively blocked for clients)

-- ---------------------------------------------------------------------------
-- LEAGUE STANDINGS: readable by league members
-- ---------------------------------------------------------------------------

CREATE POLICY "League members can read standings of their leagues"
    ON league_standings FOR SELECT
    TO authenticated
    USING (
        league_id IN (
            SELECT league_id FROM league_members WHERE user_id = auth.uid()
        )
    );

-- ---------------------------------------------------------------------------
-- LEAGUE ARCHIVES: readable by former/current members
-- ---------------------------------------------------------------------------

CREATE POLICY "Users can read archives of leagues they participated in"
    ON league_archives FOR SELECT
    TO authenticated
    USING (
        league_id IN (
            SELECT league_id FROM league_members WHERE user_id = auth.uid()
        )
    );


-- =============================================================================
-- NEW USER TRIGGER
-- =============================================================================
-- When a user signs up via Supabase Auth, automatically create their profile
-- in public.users. This avoids a race condition between auth signup and
-- the first API call.
-- =============================================================================

CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.users (id, email, locale)
    VALUES (
        NEW.id,
        NEW.email,
        COALESCE(NEW.raw_user_meta_data->>'locale', 'fr')
    )
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION handle_new_user();

COMMENT ON FUNCTION handle_new_user IS 'Creates public.users profile on Supabase Auth signup. Locale defaults to fr.';


-- =============================================================================
-- SECURITY DEFINER HELPER FUNCTIONS
-- =============================================================================
-- These functions break circular RLS dependencies between leagues and
-- league_members. Without SECURITY DEFINER, policies that subquery
-- league_members from within a leagues policy (and vice versa) cause
-- infinite recursion.
-- SECURITY DEFINER = runs as function owner (postgres), bypassing RLS.
-- This is the standard Supabase pattern for this problem.
-- =============================================================================

CREATE OR REPLACE FUNCTION get_my_league_ids()
RETURNS SETOF UUID
LANGUAGE sql
SECURITY DEFINER
STABLE
AS $$
    SELECT league_id
    FROM league_members
    WHERE user_id = auth.uid();
$$;

CREATE OR REPLACE FUNCTION get_my_member_ids()
RETURNS SETOF UUID
LANGUAGE sql
SECURITY DEFINER
STABLE
AS $$
    SELECT id
    FROM league_members
    WHERE user_id = auth.uid();
$$;

COMMENT ON FUNCTION get_my_league_ids IS
    'Returns league IDs the current user belongs to. SECURITY DEFINER bypasses RLS to avoid circular policy recursion.';

COMMENT ON FUNCTION get_my_member_ids IS
    'Returns league_member IDs for the current user. SECURITY DEFINER bypasses RLS to avoid circular policy recursion.';


-- =============================================================================
-- RLS POLICIES (corrected — replaces naive subquery versions above)
-- =============================================================================
-- Drop the recursive policies created earlier in this file and recreate them
-- using the SECURITY DEFINER helpers.
-- =============================================================================

-- LEAGUES
DROP POLICY IF EXISTS "League members can read their leagues" ON leagues;
CREATE POLICY "League members can read their leagues"
    ON leagues FOR SELECT
    TO authenticated
    USING (
        id IN (SELECT get_my_league_ids())
        OR commissioner_id = auth.uid()
    );

-- LEAGUE MEMBERS
DROP POLICY IF EXISTS "League members can read all members of their leagues" ON league_members;
CREATE POLICY "League members can read all members of their leagues"
    ON league_members FOR SELECT
    TO authenticated
    USING (
        league_id IN (SELECT get_my_league_ids())
    );

-- LEAGUE FIXTURES
DROP POLICY IF EXISTS "League members can read fixtures of their leagues" ON league_fixtures;
CREATE POLICY "League members can read fixtures of their leagues"
    ON league_fixtures FOR SELECT
    TO authenticated
    USING (
        league_id IN (SELECT get_my_league_ids())
    );

-- DRAFTS
DROP POLICY IF EXISTS "League members can read their draft" ON drafts;
CREATE POLICY "League members can read their draft"
    ON drafts FOR SELECT
    TO authenticated
    USING (
        league_id IN (SELECT get_my_league_ids())
    );

-- DRAFT PICKS
DROP POLICY IF EXISTS "League members can read draft picks of their draft" ON draft_picks;
CREATE POLICY "League members can read draft picks of their draft"
    ON draft_picks FOR SELECT
    TO authenticated
    USING (
        draft_id IN (
            SELECT id FROM drafts
            WHERE league_id IN (SELECT get_my_league_ids())
        )
    );

-- ROSTERS
DROP POLICY IF EXISTS "League members can read all rosters in their league" ON rosters;
CREATE POLICY "League members can read all rosters in their league"
    ON rosters FOR SELECT
    TO authenticated
    USING (
        league_id IN (SELECT get_my_league_ids())
    );

-- ROSTER SLOTS
DROP POLICY IF EXISTS "League members can read roster slots in their league" ON roster_slots;
CREATE POLICY "League members can read roster slots in their league"
    ON roster_slots FOR SELECT
    TO authenticated
    USING (
        roster_id IN (
            SELECT id FROM rosters
            WHERE league_id IN (SELECT get_my_league_ids())
        )
    );

-- WEEKLY LINEUPS
DROP POLICY IF EXISTS "League members can read all lineups in their league" ON weekly_lineups;
CREATE POLICY "League members can read all lineups in their league"
    ON weekly_lineups FOR SELECT
    TO authenticated
    USING (
        roster_id IN (
            SELECT id FROM rosters
            WHERE league_id IN (SELECT get_my_league_ids())
        )
    );

DROP POLICY IF EXISTS "Manager can manage their own lineup" ON weekly_lineups;
CREATE POLICY "Manager can manage their own lineup"
    ON weekly_lineups FOR ALL
    TO authenticated
    USING (
        roster_id IN (
            SELECT r.id FROM rosters r
            WHERE r.member_id IN (SELECT get_my_member_ids())
        )
    )
    WITH CHECK (
        roster_id IN (
            SELECT r.id FROM rosters r
            WHERE r.member_id IN (SELECT get_my_member_ids())
        )
    );

-- WAIVERS
DROP POLICY IF EXISTS "Manager can read own waivers" ON waivers;
CREATE POLICY "Manager can read own waivers"
    ON waivers FOR SELECT
    TO authenticated
    USING (
        member_id IN (SELECT get_my_member_ids())
    );

DROP POLICY IF EXISTS "Manager can submit their own waivers" ON waivers;
CREATE POLICY "Manager can submit their own waivers"
    ON waivers FOR INSERT
    TO authenticated
    WITH CHECK (
        member_id IN (SELECT get_my_member_ids())
    );

-- TRADES
DROP POLICY IF EXISTS "Trade participants can read their trades" ON trades;
CREATE POLICY "Trade participants can read their trades"
    ON trades FOR SELECT
    TO authenticated
    USING (
        proposer_id IN (SELECT get_my_member_ids())
        OR receiver_id IN (SELECT get_my_member_ids())
    );

DROP POLICY IF EXISTS "Manager can propose trades" ON trades;
CREATE POLICY "Manager can propose trades"
    ON trades FOR INSERT
    TO authenticated
    WITH CHECK (
        proposer_id IN (SELECT get_my_member_ids())
    );

-- TRADE PLAYERS
DROP POLICY IF EXISTS "Trade participants can read trade players" ON trade_players;
CREATE POLICY "Trade participants can read trade players"
    ON trade_players FOR SELECT
    TO authenticated
    USING (
        trade_id IN (
            SELECT id FROM trades
            WHERE proposer_id IN (SELECT get_my_member_ids())
               OR receiver_id IN (SELECT get_my_member_ids())
        )
    );

-- FANTASY SCORES
DROP POLICY IF EXISTS "League members can read fantasy scores in their league" ON fantasy_scores;
CREATE POLICY "League members can read fantasy scores in their league"
    ON fantasy_scores FOR SELECT
    TO authenticated
    USING (
        roster_id IN (
            SELECT id FROM rosters
            WHERE league_id IN (SELECT get_my_league_ids())
        )
    );

-- LEAGUE STANDINGS
DROP POLICY IF EXISTS "League members can read standings of their leagues" ON league_standings;
CREATE POLICY "League members can read standings of their leagues"
    ON league_standings FOR SELECT
    TO authenticated
    USING (
        league_id IN (SELECT get_my_league_ids())
    );

-- LEAGUE ARCHIVES
DROP POLICY IF EXISTS "Users can read archives of leagues they participated in" ON league_archives;
CREATE POLICY "Users can read archives of leagues they participated in"
    ON league_archives FOR SELECT
    TO authenticated
    USING (
        league_id IN (SELECT get_my_league_ids())
    );


-- =============================================================================
-- GRANTS
-- =============================================================================
-- RLS controls which ROWS a role can access.
-- GRANT controls whether a role can access the TABLE at all.
-- Both are required — GRANT without RLS = full table access,
-- RLS without GRANT = permission denied before RLS even evaluates.
-- =============================================================================

-- Reference data: all authenticated users can read
GRANT SELECT ON competitions TO authenticated;
GRANT SELECT ON competition_rounds TO authenticated;
GRANT SELECT ON real_matches TO authenticated;
GRANT SELECT ON players TO authenticated;
GRANT SELECT ON player_availability TO authenticated;

-- User profiles: read and update own row only (RLS enforces)
GRANT SELECT, UPDATE ON users TO authenticated;

-- Leagues: members read, commissioner updates (RLS enforces)
GRANT SELECT, INSERT, UPDATE ON leagues TO authenticated;

-- League members: read only (FastAPI manages membership)
GRANT SELECT ON league_members TO authenticated;

-- League fixtures: read only
GRANT SELECT ON league_fixtures TO authenticated;

-- Drafts: read only (FastAPI manages draft state)
GRANT SELECT ON drafts TO authenticated;

-- Draft picks: read only (FastAPI writes via service_role)
GRANT SELECT ON draft_picks TO authenticated;

-- Rosters: read only (FastAPI builds rosters after draft)
GRANT SELECT ON rosters TO authenticated;

-- Roster slots: read only (FastAPI manages slot changes)
GRANT SELECT ON roster_slots TO authenticated;

-- Weekly lineups: managers read all, write their own (RLS enforces)
GRANT SELECT, INSERT, UPDATE ON weekly_lineups TO authenticated;

-- Waivers: managers read and submit their own (RLS enforces)
GRANT SELECT, INSERT ON waivers TO authenticated;

-- Trades: participants read, proposer inserts (RLS enforces)
GRANT SELECT, INSERT, UPDATE ON trades TO authenticated;
GRANT SELECT, INSERT ON trade_players TO authenticated;

-- Fantasy scores: read only (pipeline writes via service_role)
GRANT SELECT ON fantasy_scores TO authenticated;

-- fantasy_scores_staging: NO grant to authenticated — service_role only
-- (intentionally omitted — permission denied is the correct behaviour)

-- Standings and archives: read only
GRANT SELECT ON league_standings TO authenticated;
GRANT SELECT ON league_archives TO authenticated;

-- service_role: full access on all tables (bypasses RLS anyway)
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;


-- =============================================================================
-- END OF MIGRATION
-- =============================================================================