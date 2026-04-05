/**
 * Types for roster management and weekly lineup.
 *
 * Mirrors FastAPI Pydantic schemas from backend/app/routers/lineup.py
 * and backend/app/models/lineup.py.
 *
 * CDC references:
 * - Section 6.1: Starter slots (15 players, fixed positions)
 * - Section 6.2: Bench slots (15 players, minimum coverage constraints)
 * - Section 6.4: IR slots (3 players max)
 * - Section 6.5: Weekly lineup rules (captain, kicker, progressive lock)
 * - Section 6.6: Lock edge cases (multi-position, double match, kicker change)
 */

import type { PlayerSummary } from "./player";

// ---------------------------------------------------------------------------
// Position types — mirrors backend position_type enum
// ---------------------------------------------------------------------------

export type PositionType =
  | "prop"
  | "hooker"
  | "lock"
  | "flanker"
  | "number_8"
  | "scrum_half"
  | "fly_half"
  | "centre"
  | "wing"
  | "fullback";

/** French display labels for each position. Used as a fallback alongside i18n keys. */
export const POSITION_LABELS: Record<PositionType, string> = {
  prop: "Pilier",
  hooker: "Talonneur",
  lock: "Deuxième ligne",
  flanker: "Troisième ligne",
  number_8: "Numéro 8",
  scrum_half: "Demi de mêlée",
  fly_half: "Demi d'ouverture",
  centre: "Centre",
  wing: "Ailier",
  fullback: "Arrière",
};

/**
 * CDC §6.1 — The 15 starter slots in jersey number order.
 * Index 0 = jersey #1 (loosehead prop), index 14 = jersey #15 (fullback).
 * Used to render the starter grid in the correct order without extra logic.
 */
export const STARTER_POSITIONS: PositionType[] = [
  "prop", // 1 — pilier gauche
  "hooker", // 2 — talonneur
  "prop", // 3 — pilier droit
  "lock", // 4 — deuxième ligne
  "lock", // 5 — deuxième ligne
  "flanker", // 6 — troisième ligne aile
  "flanker", // 7 — troisième ligne aile
  "number_8", // 8 — numéro 8
  "scrum_half", // 9 — demi de mêlée
  "fly_half", // 10 — demi d'ouverture
  "wing", // 11 — ailier gauche
  "centre", // 12 — centre
  "centre", // 13 — centre
  "wing", // 14 — ailier droit
  "fullback", // 15 — arrière
];

/**
 * CDC §6.2 — Minimum bench coverage per position.
 * At least these many bench players must cover each listed position.
 * The remaining 5 bench slots are free (no position constraint).
 *
 * Note: "flanker" coverage is shared with number_8 in practice
 * (back row interchangeability). Kept separate here for precision.
 */
export const BENCH_COVERAGE_MINIMUMS: Partial<Record<PositionType, number>> = {
  prop: 2,
  hooker: 1,
  lock: 1,
  flanker: 1,
  scrum_half: 1,
  fly_half: 1,
  centre: 1,
  wing: 1,
  fullback: 1,
};

// ---------------------------------------------------------------------------
// Player availability — mirrors player_availability.status enum
// ---------------------------------------------------------------------------

export type PlayerAvailabilityStatus =
  | "available"
  | "injured"
  | "suspended"
  | "doubtful";

// ---------------------------------------------------------------------------
// Roster slot — one player in the roster (permanent structure, not per-round)
// ---------------------------------------------------------------------------

/** The three zones in a roster. */
export type SlotType = "starter" | "bench" | "ir";

export interface RosterSlot {
  /** UUID — roster_slots.id */
  id: string;
  /** Full player data including all positions they can play. */
  player: PlayerSummary;
  /** Which zone this player is in. */
  slot_type: SlotType;
  /**
   * Slot index within starters (1–15) or bench (1–15).
   * Maps to jersey number for starters (index 1 = jersey #1).
   * Null for IR slots (no fixed ordering).
   */
  slot_index: number | null;
  /** Real-world availability from player_availability table. */
  availability_status: PlayerAvailabilityStatus;
}

// ---------------------------------------------------------------------------
// Weekly lineup entry — one player's assignment for a given round
// ---------------------------------------------------------------------------

export interface WeeklyLineupEntry {
  /** UUID — weekly_lineups.id */
  id: string;
  /** References RosterSlot.player.id */
  player_id: string;
  /**
   * Active position for this round.
   * For multi-position players: chosen by the manager before kick-off.
   * For single-position players: always their natural position.
   * CDC §6.3: choice locked at kick-off of the player's team.
   */
  position: PositionType;
  /**
   * True if this player is the captain this round.
   * CDC §6.5: captain scores ×1.5 (rounded up to nearest 0.5).
   * Captain must be a starter — validated backend-side.
   */
  is_captain: boolean;
  /**
   * True if this player is the designated kicker this round.
   * CDC §6.5: only the kicker scores on penalties and conversions.
   * Drops are open to all players.
   */
  is_kicker: boolean;
  /**
   * ISO 8601 timestamp of when this entry was locked.
   * Set to the kick-off time of the player's team match.
   * Null if the player's team has not kicked off yet this round.
   * CDC §6.5: progressive lock — each player locks individually.
   */
  locked_at: string | null;
  /**
   * Whether this entry is currently locked (i.e. locked_at <= now).
   * Pre-computed by the backend to avoid client clock drift issues.
   * When true: position, captain, kicker changes are forbidden.
   */
  is_locked: boolean;
}

// ---------------------------------------------------------------------------
// Roster response — GET /roster/{league_id}
// ---------------------------------------------------------------------------

export interface RosterResponse {
  /** UUID — rosters.id */
  roster_id: string;
  /** UUID — leagues.id */
  league_id: string;
  /**
   * All roster slots: starters (up to 15) + bench (up to 15) + IR (up to 3).
   * CDC §6.4: IR capacity is 3 players max.
   * Total roster size: up to 33 (30 active + 3 IR).
   */
  slots: RosterSlot[];
}

// ---------------------------------------------------------------------------
// Weekly lineup response — GET /lineup/{league_id}/{round_id}
// ---------------------------------------------------------------------------

export interface WeeklyLineupResponse {
  /** UUID — rosters.id */
  roster_id: string;
  /** UUID — competition_rounds.id */
  round_id: string;
  /** Display number, e.g. 14 for "Journée 14". */
  round_number: number;
  /**
   * One entry per player in the roster for this round.
   * Includes both starters and bench players.
   * IR players are excluded (they score no points — CDC §6.4).
   */
  entries: WeeklyLineupEntry[];
  /**
   * Set of player IDs whose team has already kicked off this round.
   * Used by the UI to render lock indicators quickly without
   * comparing each entry's locked_at to Date.now().
   */
  locked_player_ids: string[];
  /**
   * True when all matches in the round are complete.
   * Disables all lineup editing — the round is closed.
   */
  round_complete: boolean;
}

// ---------------------------------------------------------------------------
// Lineup update payload — POST /lineup/{league_id}/update
// ---------------------------------------------------------------------------

/**
 * Single payload for all lineup changes in one round.
 *
 * Design decision: one atomic POST instead of separate endpoints per action.
 * Rationale: prevents race conditions if the user makes rapid changes
 * (e.g. captain change + position override simultaneously).
 * The backend validates the entire payload before committing any change.
 */
export interface LineupUpdatePayload {
  /** The round being updated. */
  round_id: string;
  /**
   * New captain player ID. Null to remove the captain designation.
   * Backend enforces: captain must be a starter (not bench, not IR).
   * CDC §6.6: cannot change if captain's team has already kicked off.
   */
  captain_player_id: string | null;
  /**
   * New kicker player ID. Null to remove the kicker designation.
   * CDC §6.6: cannot change after the kicker has played their match.
   */
  kicker_player_id: string | null;
  /**
   * Position overrides for multi-position players this round.
   * Key: player_id, Value: chosen PositionType.
   * Only send entries where the manager changed the position.
   * CDC §6.3: locked at kick-off of the player's team.
   */
  position_overrides: Record<string, PositionType>;
  /**
   * Starter ↔ bench swaps.
   * Each entry is a pair of slot IDs to swap.
   * Backend validates each swap: neither player can be locked.
   */
  slot_swaps: Array<{
    /** slot_id of the player moving to bench. */
    from_slot_id: string;
    /** slot_id of the player moving to starter. */
    to_slot_id: string;
  }>;
}

// ---------------------------------------------------------------------------
// Coverage status — computed on the frontend, validated on the backend
// CDC §6.2: minimum bench coverage constraints
// ---------------------------------------------------------------------------

export interface PositionCoverage {
  position: PositionType;
  /** How many bench players can cover this position (natural or multi-position). */
  current_count: number;
  /** Minimum required per CDC §6.2. */
  required: number;
  /** True when current_count >= required. */
  is_covered: boolean;
}

export interface RosterCoverageStatus {
  /** Coverage detail per required position. */
  positions: PositionCoverage[];
  /** True only when every required position is covered. */
  all_covered: boolean;
  /** Count of uncovered positions — useful for summary badge. */
  uncovered_count: number;
}

// ---------------------------------------------------------------------------
// UI-only state — not persisted, lives in component/hook state
// ---------------------------------------------------------------------------

/**
 * Which tab panel is active on mobile.
 * On desktop, all panels are visible simultaneously.
 */
export type RosterView = "starters" | "bench" | "ir" | "lineup";

/**
 * A player currently selected for an action in the UI.
 * Used to orchestrate captain/kicker designation and starter ↔ bench swaps.
 */
export interface RosterSelection {
  /** The selected player. */
  player_id: string;
  /** Their current slot. */
  slot_id: string;
  /** What action is being performed. */
  mode: "set_captain" | "set_kicker" | "swap_to_starter" | "swap_to_bench";
}

/**
 * Optimistic update state — a change the user made locally that hasn't
 * been confirmed by the backend yet. Used to give instant UI feedback
 * while the POST /lineup/update is in flight.
 */
export interface OptimisticLineupChange {
  type: "captain" | "kicker" | "swap" | "position_override";
  /** Timestamp of the optimistic change — used to discard stale updates. */
  applied_at: number;
}
