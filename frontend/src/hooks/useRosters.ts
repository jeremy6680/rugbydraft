/**
 * useRoster — data hook for the roster management page.
 *
 * Responsibilities:
 * - Fetch roster slots (permanent structure, not round-specific)
 * - Fetch weekly lineup for the current round
 * - Compute bench coverage status (CDC §6.2)
 * - Expose updateLineup() for atomic lineup mutations
 * - Poll for lock status updates during match windows
 * - Handle optimistic UI updates with rollback on error
 *
 * Architecture note:
 * FastAPI is the authority of state. This hook never writes to Supabase
 * directly — all mutations go through POST /lineup/{leagueId}/update.
 */

"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";
import type {
  RosterCoverageStatus,
  RosterResponse,
  RosterSelection,
  RosterView,
  LineupUpdatePayload,
  OptimisticLineupChange,
  PositionCoverage,
  PositionType,
  WeeklyLineupResponse,
} from "@/types/roster";
import { BENCH_COVERAGE_MINIMUMS } from "@/types/roster";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Polling interval for lock status refresh during active match windows (ms). */
const LOCK_POLL_INTERVAL_MS = 30_000;

/** Backend API base URL from environment. */
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

// ---------------------------------------------------------------------------
// State shape
// ---------------------------------------------------------------------------

interface RosterState {
  /** Permanent roster structure (starters + bench + IR). Null = not loaded. */
  roster: RosterResponse | null;
  /** Weekly lineup for the current round. Null = not loaded. */
  lineup: WeeklyLineupResponse | null;
  /** Computed from bench slots — recalculated on every roster change. */
  coverage: RosterCoverageStatus | null;
  /** Which mobile tab is active. */
  activeView: RosterView;
  /** Player currently selected for an action (captain/kicker/swap). */
  selection: RosterSelection | null;
  /** Pending optimistic change (cleared on server confirmation or rollback). */
  pendingChange: OptimisticLineupChange | null;
  /** Loading state for initial data fetch. */
  isLoading: boolean;
  /** Loading state for lineup mutation (POST). */
  isSaving: boolean;
  /** Error message to display in the UI. Null when no error. */
  error: string | null;
}

const initialState: RosterState = {
  roster: null,
  lineup: null,
  coverage: null,
  activeView: "starters",
  selection: null,
  pendingChange: null,
  isLoading: true,
  isSaving: false,
  error: null,
};

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

type RosterAction =
  | {
      type: "LOAD_SUCCESS";
      roster: RosterResponse;
      lineup: WeeklyLineupResponse;
    }
  | { type: "LOAD_ERROR"; error: string }
  | { type: "LINEUP_REFRESH"; lineup: WeeklyLineupResponse }
  | { type: "SET_VIEW"; view: RosterView }
  | { type: "SET_SELECTION"; selection: RosterSelection | null }
  | { type: "SAVE_START"; change: OptimisticLineupChange }
  | { type: "SAVE_SUCCESS"; lineup: WeeklyLineupResponse }
  | { type: "SAVE_ERROR"; error: string; previousLineup: WeeklyLineupResponse };

// ---------------------------------------------------------------------------
// Reducer
// ---------------------------------------------------------------------------

function rosterReducer(state: RosterState, action: RosterAction): RosterState {
  switch (action.type) {
    case "LOAD_SUCCESS":
      return {
        ...state,
        roster: action.roster,
        lineup: action.lineup,
        coverage: computeCoverage(action.roster, action.lineup),
        isLoading: false,
        error: null,
      };

    case "LOAD_ERROR":
      return { ...state, isLoading: false, error: action.error };

    case "LINEUP_REFRESH":
      // Triggered by the lock status poller — updates lineup without
      // resetting any other UI state (view, selection, etc.)
      return {
        ...state,
        lineup: action.lineup,
        // Recompute coverage only if roster is loaded (should always be true here).
        coverage: state.roster
          ? computeCoverage(state.roster, action.lineup)
          : state.coverage,
      };

    case "SET_VIEW":
      return { ...state, activeView: action.view, selection: null };

    case "SET_SELECTION":
      return { ...state, selection: action.selection };

    case "SAVE_START":
      return {
        ...state,
        isSaving: true,
        pendingChange: action.change,
        error: null,
      };

    case "SAVE_SUCCESS":
      return {
        ...state,
        isSaving: false,
        pendingChange: null,
        lineup: action.lineup,
        coverage: state.roster
          ? computeCoverage(state.roster, action.lineup)
          : state.coverage,
        selection: null,
      };

    case "SAVE_ERROR":
      // Roll back to the lineup state before the optimistic change.
      return {
        ...state,
        isSaving: false,
        pendingChange: null,
        lineup: action.previousLineup,
        error: action.error,
      };

    default:
      return state;
  }
}

// ---------------------------------------------------------------------------
// Pure helper: compute bench coverage (CDC §6.2)
// ---------------------------------------------------------------------------

/**
 * Compute bench coverage status from the current roster and lineup.
 *
 * A bench player "covers" a position if:
 * 1. Their natural position matches (from PlayerSummary.positions[]), OR
 * 2. They have a position override in the lineup that matches.
 *
 * Multi-position players (CDC §6.3) can cover multiple positions.
 *
 * @param roster - Current roster response
 * @param lineup - Current weekly lineup response
 * @returns Coverage status per required position + overall flag
 */
function computeCoverage(
  roster: RosterResponse,
  lineup: WeeklyLineupResponse,
): RosterCoverageStatus {
  // Build a map of player_id → active position for this round.
  // If the player has a lineup override, use that; otherwise use
  // their first natural position.
  const activePositions = new Map<string, PositionType[]>();

  for (const slot of roster.slots) {
    if (slot.slot_type !== "bench") continue;

    // Collect all positions this bench player can cover.
    // PlayerSummary.positions is an array (multi-position support).
    const naturalPositions = slot.player.positions as PositionType[];

    // Check if there is a lineup entry with a position override.
    const lineupEntry = lineup.entries.find(
      (e) => e.player_id === slot.player.id,
    );
    const effectivePositions = lineupEntry
      ? [lineupEntry.position, ...naturalPositions]
      : naturalPositions;

    // Deduplicate (override may equal the natural position).
    activePositions.set(slot.player.id, [...new Set(effectivePositions)]);
  }

  // Compute coverage count per required position.
  const positions: PositionCoverage[] = Object.entries(
    BENCH_COVERAGE_MINIMUMS,
  ).map(([pos, required]) => {
    const position = pos as PositionType;
    let current_count = 0;

    for (const [, playerPositions] of activePositions) {
      if (playerPositions.includes(position)) {
        current_count++;
      }
    }

    return {
      position,
      required: required ?? 1,
      current_count,
      is_covered: current_count >= (required ?? 1),
    };
  });

  const uncovered_count = positions.filter((p) => !p.is_covered).length;

  return {
    positions,
    all_covered: uncovered_count === 0,
    uncovered_count,
  };
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export interface UseRosterReturn {
  // Data
  roster: RosterResponse | null;
  lineup: WeeklyLineupResponse | null;
  coverage: RosterCoverageStatus | null;
  // UI state
  activeView: RosterView;
  selection: RosterSelection | null;
  // Loading / saving
  isLoading: boolean;
  isSaving: boolean;
  error: string | null;
  // Actions
  setView: (view: RosterView) => void;
  setSelection: (selection: RosterSelection | null) => void;
  updateLineup: (payload: LineupUpdatePayload) => Promise<void>;
  clearError: () => void;
}

/**
 * Main data hook for the roster management page.
 *
 * @param leagueId - UUID of the league
 * @param roundId  - UUID of the current competition round
 */
export function useRoster(leagueId: string, roundId: string): UseRosterReturn {
  const [state, dispatch] = useReducer(rosterReducer, initialState);
  const supabase = createBrowserSupabaseClient();

  // Keep a ref to the current lineup for rollback in SAVE_ERROR.
  // We cannot use state directly inside the async save callback
  // because it would capture a stale closure.
  const lineupRef = useRef<WeeklyLineupResponse | null>(null);
  lineupRef.current = state.lineup;

  // Ref to the lock-status polling timer.
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ---------------------------------------------------------------------------
  // Auth helper — get the current session token for API calls
  // ---------------------------------------------------------------------------

  const getAuthHeader = useCallback(async (): Promise<
    Record<string, string>
  > => {
    const {
      data: { session },
    } = await supabase.auth.getSession();

    if (!session) {
      throw new Error("No active session — user must be authenticated.");
    }

    return {
      Authorization: `Bearer ${session.access_token}`,
      "Content-Type": "application/json",
    };
  }, [supabase]);

  // ---------------------------------------------------------------------------
  // Initial data load — parallel fetch of roster + lineup
  // ---------------------------------------------------------------------------

  const loadData = useCallback(async () => {
    try {
      const headers = await getAuthHeader();

      // Parallel fetch: roster and lineup do not depend on each other.
      const [rosterRes, lineupRes] = await Promise.all([
        fetch(`${API_BASE}/roster/${leagueId}`, { headers }),
        fetch(`${API_BASE}/lineup/${leagueId}/${roundId}`, { headers }),
      ]);

      // Surface HTTP errors before attempting JSON parse.
      if (!rosterRes.ok) {
        throw new Error(`Roster fetch failed: ${rosterRes.status}`);
      }
      if (!lineupRes.ok) {
        throw new Error(`Lineup fetch failed: ${lineupRes.status}`);
      }

      const [roster, lineup]: [RosterResponse, WeeklyLineupResponse] =
        await Promise.all([rosterRes.json(), lineupRes.json()]);

      dispatch({ type: "LOAD_SUCCESS", roster, lineup });
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Erreur de chargement du roster.";
      dispatch({ type: "LOAD_ERROR", error: message });
    }
  }, [leagueId, roundId, getAuthHeader]);

  // ---------------------------------------------------------------------------
  // Lock status poller — refreshes lineup during active match windows
  //
  // Why poll and not Supabase Realtime?
  // Lock status changes when a real match kicks off — these events are driven
  // by the Airflow pipeline, not by user actions. Realtime channels are for
  // user-triggered draft events. Polling every 30s is accurate enough and
  // avoids over-engineering. If a more reactive UX is needed in V2, a
  // Supabase Realtime subscription on real_matches.status can replace this.
  // ---------------------------------------------------------------------------

  const pollLockStatus = useCallback(async () => {
    // Do not poll if the round is already complete or data isn't loaded.
    if (state.lineup?.round_complete) return;

    try {
      const headers = await getAuthHeader();
      const res = await fetch(`${API_BASE}/lineup/${leagueId}/${roundId}`, {
        headers,
      });
      if (!res.ok) return; // Silent fail — poller, not critical path

      const lineup: WeeklyLineupResponse = await res.json();
      dispatch({ type: "LINEUP_REFRESH", lineup });
    } catch {
      // Poller failures are silent — next tick will retry.
    }
  }, [leagueId, roundId, getAuthHeader, state.lineup?.round_complete]);

  // ---------------------------------------------------------------------------
  // Effects
  // ---------------------------------------------------------------------------

  // Initial load on mount + when leagueId/roundId change.
  useEffect(() => {
    void loadData();
  }, [loadData]);

  // Start/stop lock status poller.
  // Polling is active only when a round is in progress (not complete).
  useEffect(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }

    if (!state.lineup?.round_complete && state.lineup !== null) {
      pollTimerRef.current = setInterval(
        () => void pollLockStatus(),
        LOCK_POLL_INTERVAL_MS,
      );
    }

    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
      }
    };
  }, [state.lineup?.round_complete, state.lineup, pollLockStatus]);

  // ---------------------------------------------------------------------------
  // Actions exposed to components
  // ---------------------------------------------------------------------------

  const setView = useCallback((view: RosterView) => {
    dispatch({ type: "SET_VIEW", view });
  }, []);

  const setSelection = useCallback((selection: RosterSelection | null) => {
    dispatch({ type: "SET_SELECTION", selection });
  }, []);

  const clearError = useCallback(() => {
    dispatch({
      type: "SAVE_ERROR",
      error: "",
      previousLineup: lineupRef.current!,
    });
  }, []);

  /**
   * Submit a lineup update to the backend.
   *
   * Flow:
   * 1. Dispatch SAVE_START (sets isSaving = true, stores optimistic change type)
   * 2. POST to /lineup/{leagueId}/update
   * 3a. On success: dispatch SAVE_SUCCESS with server-confirmed lineup
   * 3b. On error: dispatch SAVE_ERROR — rolls back to lineupRef.current
   *
   * The rollback uses lineupRef (not state) to avoid stale closure issues
   * inside this async callback.
   */
  const updateLineup = useCallback(
    async (payload: LineupUpdatePayload): Promise<void> => {
      // Determine the change type for the optimistic update record.
      const changeType =
        payload.captain_player_id !== undefined
          ? "captain"
          : payload.kicker_player_id !== undefined
            ? "kicker"
            : payload.slot_swaps.length > 0
              ? "swap"
              : "position_override";

      dispatch({
        type: "SAVE_START",
        change: { type: changeType, applied_at: Date.now() },
      });

      try {
        const headers = await getAuthHeader();
        const res = await fetch(`${API_BASE}/lineup/${leagueId}/update`, {
          method: "POST",
          headers,
          body: JSON.stringify(payload),
        });

        if (!res.ok) {
          // Parse the FastAPI error detail if available.
          const errorBody = await res.json().catch(() => null);
          const detail =
            errorBody?.detail ?? `Erreur ${res.status} — modification refusée.`;
          throw new Error(detail);
        }

        const confirmedLineup: WeeklyLineupResponse = await res.json();
        dispatch({ type: "SAVE_SUCCESS", lineup: confirmedLineup });
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Erreur lors de la sauvegarde.";
        // Roll back to the lineup as it was before SAVE_START.
        dispatch({
          type: "SAVE_ERROR",
          error: message,
          previousLineup: lineupRef.current!,
        });
      }
    },
    [leagueId, getAuthHeader],
  );

  // ---------------------------------------------------------------------------
  // Return
  // ---------------------------------------------------------------------------

  return {
    roster: state.roster,
    lineup: state.lineup,
    coverage: state.coverage,
    activeView: state.activeView,
    selection: state.selection,
    isLoading: state.isLoading,
    isSaving: state.isSaving,
    error: state.error,
    setView,
    setSelection,
    updateLineup,
    clearError,
  };
}
