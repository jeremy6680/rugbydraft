// frontend/src/types/leaderboard.ts

/**
 * TypeScript mirror of the FastAPI LeagueStandingsResponse schema.
 * Keep in sync with backend/app/routers/leagues.py.
 */

/** A single manager's standing in a league. */
export interface StandingEntry {
  rank: number;
  member_id: string;
  display_name: string;
  wins: number;
  losses: number;
  total_points: number;
}

/** Full standings response from GET /leagues/{league_id}/standings. */
export interface LeagueStandingsResponse {
  league_id: string;
  standings: StandingEntry[];
  updated_at: string | null;
}
