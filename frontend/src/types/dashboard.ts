// frontend/src/types/dashboard.ts

/**
 * TypeScript mirror of backend/app/routers/dashboard.py Pydantic models.
 * Keep in sync with the FastAPI DashboardResponse schema.
 *
 * CDC reference: §5.2 — Dashboard personnel.
 */

// ---------------------------------------------------------------------------
// Alert types
// ---------------------------------------------------------------------------

export type AlertType =
  | "player_injured"
  | "player_recovered"
  | "waiver_open"
  | "trade_proposed"
  | "ai_report_ready";

export interface DashboardAlert {
  alert_type: AlertType;
  /** Player name, waiver deadline, etc. — used in i18n interpolation. */
  detail: string | null;
  /** ISO 8601 UTC. Null if not tracked. */
  created_at: string | null;
}

// ---------------------------------------------------------------------------
// League summary
// ---------------------------------------------------------------------------

export type LeagueStatus = "upcoming" | "drafting" | "active" | "completed";
export type DraftStatus = "pending" | "active";

export interface DashboardLeague {
  league_id: string;
  league_name: string;
  competition_name: string;
  competition_id: string;

  /** Null before standings are computed (draft not started). */
  current_rank: number | null;
  total_managers: number;

  /** Null before the first round is scored. */
  last_round_number: number | null;
  last_round_points: number | null;

  /** Deferred — requires schedule query (Phase 4 follow-up). */
  next_opponent: string | null;

  /** Populated only when the league has a pending or active draft. */
  draft_id: string | null;
  draft_status: DraftStatus | null;

  league_status: LeagueStatus;
  is_commissioner: boolean;
  alerts: DashboardAlert[];
}

// ---------------------------------------------------------------------------
// Dashboard response
// ---------------------------------------------------------------------------

export interface DashboardResponse {
  user_id: string;
  /** Empty array when the user has no active leagues. */
  leagues: DashboardLeague[];
  /** ISO 8601 UTC — server response time. */
  fetched_at: string;
}
