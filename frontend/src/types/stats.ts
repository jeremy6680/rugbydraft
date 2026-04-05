// frontend/src/types/stats.ts

/**
 * TypeScript types for the Stats page.
 *
 * Mirror of the FastAPI PlayerStatsRow and PlayerStatsResponse models.
 * Scoring system v2 — see DECISIONS.md D-039.
 */

// ---------------------------------------------------------------------------
// Enums / literals
// ---------------------------------------------------------------------------

/** Aggregation period — mirrors the 'period' column in mart_player_stats_ui. */
export type StatsPeriod = "1w" | "2w" | "4w" | "season";

/**
 * Pool status for a player within a specific league.
 * Only meaningful when the stats endpoint is called with a league_id.
 */
export type PoolStatus = "mine" | "drafted" | "free";

/** Trend direction vs the previous equivalent period. */
export type StatsTrend = "up" | "down" | "stable";

/** Filter for which players to display. */
export type StatsPoolFilter = "all" | "free" | "mine";

// ---------------------------------------------------------------------------
// Core data shape
// ---------------------------------------------------------------------------

/**
 * Aggregated stats for a single player over a given period.
 *
 * All counting stats are totals over the period (not per-match averages),
 * except avg_points which is the mean fantasy score per round played.
 *
 * Kicker stats (conversions_made, penalties_made) are raw totals for all
 * players — the kicker_flag rule applies only to fantasy point calculation,
 * not to the display of raw stats.
 */
export interface PlayerStatsRow {
  player_id: string;
  competition_id: string;
  period: StatsPeriod;
  player_name: string;
  position_type: string;
  nationality: string | null;
  club: string | null;
  availability_status: string;
  pool_status: PoolStatus;
  rounds_played: number;

  // Fantasy points
  total_points: number;
  avg_points: number;

  // Attack (D-039)
  tries: number;
  try_assists: number;
  metres_carried: number;
  kick_assists: number;
  line_breaks: number;
  catch_from_kick: number;
  conversions_made: number;
  penalties_made: number;

  // Defence (D-039)
  tackles: number;
  turnovers_won: number;
  lineouts_won: number;
  lineouts_lost: number;
  turnovers_conceded: number;
  missed_tackles: number;
  handling_errors: number;
  penalties_conceded: number;
  yellow_cards: number;
  red_cards: number;

  trend: StatsTrend;
}

/** Full API response from GET /stats/players. */
export interface PlayerStatsResponse {
  competition_id: string;
  period: StatsPeriod;
  players: PlayerStatsRow[];
}

// ---------------------------------------------------------------------------
// UI filter state
// ---------------------------------------------------------------------------

/**
 * All active filters on the Stats page.
 * Applied client-side on the full player list (D-044).
 */
export interface StatsFilters {
  /** Search string matched against player_name (case-insensitive). */
  search: string;
  /** Position filter — empty string = all positions. */
  position: string;
  /** Club or nationality filter — empty string = all. */
  clubOrNationality: string;
  /** Pool status filter. */
  poolFilter: StatsPoolFilter;
}

export const DEFAULT_STATS_FILTERS: StatsFilters = {
  search: "",
  position: "",
  clubOrNationality: "",
  poolFilter: "all",
};

// ---------------------------------------------------------------------------
// Column group definitions (for the tabbed table UI)
// ---------------------------------------------------------------------------

/**
 * Column group tabs shown in StatsTable.
 * Each group corresponds to a section of D-039 scoring actions.
 */
export type StatsColumnGroup = "points" | "attack" | "defence" | "discipline";
