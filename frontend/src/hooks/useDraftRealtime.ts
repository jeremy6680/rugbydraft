// frontend/src/hooks/useDraftRealtime.ts
/**
 * useDraftRealtime — React hook for the RugbyDraft Draft Room.
 *
 * Responsibilities:
 *   1. Fetch initial state  — POST /draft/{leagueId}/connect on mount.
 *   2. Supabase Realtime    — subscribe to channel "draft:{leagueId}",
 *                             listen for "state_update" broadcast events.
 *   3. Cleanup              — POST /draft/{leagueId}/disconnect + unsubscribe
 *                             on unmount.
 *
 * Architecture principle (D-001):
 *   FastAPI is the authority of state. This hook NEVER writes state directly
 *   to Supabase. It only reads broadcasts and calls FastAPI endpoints.
 *
 * Timer note:
 *   This hook does NOT manage a visual countdown. It exposes time_remaining
 *   from the latest snapshot. The DraftTimer component owns the local
 *   setInterval and resets it whenever this hook provides a new snapshot.
 *
 * @param leagueId      - The league whose draft to connect to.
 * @param currentUserId - The authenticated user's Supabase UUID.
 *                        Used to derive isMyTurn and isAutodraftActive.
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { RealtimeChannel } from "@supabase/supabase-js"; // FIXED
import { createBrowserSupabaseClient } from "@/lib/supabase/client";
import type {
  DraftRealtimePayload,
  DraftStateSnapshot,
  DraftUIState,
} from "@/types/draft";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** FastAPI base URL — injected from env at build time. */
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Polling interval (ms) used as fallback when Supabase Realtime is
 * unavailable. Polls GET /draft/{leagueId}/state every N ms.
 * Disabled when Realtime is connected.
 */
const POLLING_INTERVAL_MS = 5_000;

// ---------------------------------------------------------------------------
// API helpers — thin fetch wrappers, no business logic
// ---------------------------------------------------------------------------

/**
 * Call POST /draft/{leagueId}/connect.
 * Returns the full state snapshot and registers the manager as connected.
 *
 * @throws Error on non-2xx response.
 */
async function connectToDraft(
  leagueId: string,
  authToken: string,
): Promise<DraftStateSnapshot> {
  const response = await fetch(`${API_BASE_URL}/draft/${leagueId}/connect`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${authToken}`,
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Failed to connect to draft: ${response.status} ${detail}`);
  }

  return response.json() as Promise<DraftStateSnapshot>;
}

/**
 * Call POST /draft/{leagueId}/disconnect.
 * Fire-and-forget — uses keepalive fetch to survive page unload.
 */
function disconnectFromDraft(leagueId: string, authToken: string): void {
  fetch(`${API_BASE_URL}/draft/${leagueId}/disconnect`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${authToken}`,
      "Content-Type": "application/json",
    },
    keepalive: true,
  }).catch(() => {
    // Intentionally silenced — disconnect is best-effort.
    // FastAPI handles missing disconnects via timer expiry.
  });
}

/**
 * Call GET /draft/{leagueId}/state — polling fallback.
 * No side effects (does not register as connected).
 *
 * @throws Error on non-2xx response.
 */
async function fetchDraftState(
  leagueId: string,
  authToken: string,
): Promise<DraftStateSnapshot> {
  const response = await fetch(`${API_BASE_URL}/draft/${leagueId}/state`, {
    headers: {
      Authorization: `Bearer ${authToken}`,
    },
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(
      `Failed to fetch draft state: ${response.status} ${detail}`,
    );
  }

  return response.json() as Promise<DraftStateSnapshot>;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useDraftRealtime(
  leagueId: string,
  currentUserId: string,
): DraftUIState {
  // --- State ---
  const [snapshot, setSnapshot] = useState<DraftStateSnapshot | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Tracks whether Supabase Realtime is currently connected.
  // When false, the polling fallback activates.
  const [isRealtimeConnected, setIsRealtimeConnected] = useState(false);

  // Stable refs — avoid re-running effects when these change.
  const authTokenRef = useRef<string | null>(null);
  const pollingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ---------------------------------------------------------------------------
  // Fetch auth token once — reused for all API calls.
  // ---------------------------------------------------------------------------

  const getAuthToken = useCallback(async (): Promise<string | null> => {
    if (authTokenRef.current) return authTokenRef.current;

    const supabase = createBrowserSupabaseClient();
    const {
      data: { session },
    } = await supabase.auth.getSession();

    if (session?.access_token) {
      authTokenRef.current = session.access_token;
    }

    return authTokenRef.current;
  }, []);

  // ---------------------------------------------------------------------------
  // Polling fallback — active only when Realtime is disconnected.
  // ---------------------------------------------------------------------------

  const stopPolling = useCallback(() => {
    if (pollingTimerRef.current !== null) {
      clearInterval(pollingTimerRef.current);
      pollingTimerRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    stopPolling();

    pollingTimerRef.current = setInterval(async () => {
      const token = await getAuthToken();
      if (!token) return;

      try {
        const state = await fetchDraftState(leagueId, token);
        setSnapshot(state);
        setError(null);
      } catch (err) {
        console.warn("[useDraftRealtime] polling error:", err);
      }
    }, POLLING_INTERVAL_MS);
  }, [leagueId, getAuthToken, stopPolling]);

  // ---------------------------------------------------------------------------
  // Main effect — connect, subscribe, cleanup.
  // ---------------------------------------------------------------------------

  useEffect(() => {
    const abortController = new AbortController();
    let channelSubscription: RealtimeChannel | null = null; // FIXED

    async function init() {
      setIsLoading(true);
      setError(null);

      // --- Step 1: Get auth token ---
      const token = await getAuthToken();
      if (!token) {
        setError("Session expirée. Veuillez vous reconnecter.");
        setIsLoading(false);
        return;
      }

      if (abortController.signal.aborted) return;

      // --- Step 2: Connect and get initial snapshot ---
      try {
        const initialSnapshot = await connectToDraft(leagueId, token);
        if (abortController.signal.aborted) return;

        setSnapshot(initialSnapshot);
        setIsLoading(false);
      } catch (err) {
        if (abortController.signal.aborted) return;
        setError(
          err instanceof Error
            ? err.message
            : "Impossible de rejoindre le draft.",
        );
        setIsLoading(false);
        startPolling();
        return;
      }

      // --- Step 3: Subscribe to Supabase Realtime ---
      const supabase = createBrowserSupabaseClient();
      const channelName = `draft:${leagueId}`;

      channelSubscription = supabase
        .channel(channelName)
        .on(
          "broadcast",
          { event: "state_update" },
          (message: { payload: DraftRealtimePayload["payload"] }) => {
            setSnapshot(message.payload);
            setError(null);
          },
        )
        .on("system", {}, (status: { event: string }) => {
          if (status.event === "SUBSCRIBED") {
            setIsRealtimeConnected(true);
            stopPolling();
          } else if (
            status.event === "CLOSED" ||
            status.event === "CHANNEL_ERROR"
          ) {
            setIsRealtimeConnected(false);
            startPolling();
          }
        })
        .subscribe();
    }

    init();

    return () => {
      abortController.abort();
      stopPolling();

      if (authTokenRef.current) {
        disconnectFromDraft(leagueId, authTokenRef.current);
      }

      if (channelSubscription) {
        const supabase = createBrowserSupabaseClient();
        supabase.removeChannel(channelSubscription);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leagueId]);

  // ---------------------------------------------------------------------------
  // Stop polling when Realtime reconnects.
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (isRealtimeConnected) {
      stopPolling();
    }
  }, [isRealtimeConnected, stopPolling]);

  // ---------------------------------------------------------------------------
  // Derived UI state
  // ---------------------------------------------------------------------------

  const isMyTurn =
    snapshot?.status === "in_progress" &&
    snapshot.current_manager_id === currentUserId;

  const isAutodraftActive =
    snapshot?.autodraft_managers.includes(currentUserId) ?? false;

  const isDraftActive = snapshot?.status === "in_progress"; // FIXED

  return {
    snapshot,
    isLoading,
    error,
    isMyTurn,
    isAutodraftActive,
    isDraftActive,
  };
}
