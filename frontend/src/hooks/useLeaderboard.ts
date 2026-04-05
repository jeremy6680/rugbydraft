// frontend/src/hooks/useLeaderboard.ts

"use client";

/**
 * useLeaderboard — fetch + Supabase Realtime Postgres Changes subscription.
 *
 * Fetches standings from FastAPI on mount, then subscribes to league_standings
 * mutations via Supabase Realtime CDC. Falls back to polling every 60s if
 * Realtime is unavailable.
 *
 * The re-fetch strategy (instead of applying raw Realtime payloads) ensures
 * consistency when multiple rows change in a single pipeline commit.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { createBrowserSupabaseClient } from "@/lib/supabase/client";
import type {
  LeagueStandingsResponse,
  StandingEntry,
} from "@/types/leaderboard";

// Polling interval when Realtime is unavailable (ms)
const FALLBACK_POLL_INTERVAL_MS = 60_000;

interface UseLeaderboardOptions {
  /** UUID of the league to watch. */
  leagueId: string;
  /** Initial standings pre-fetched server-side (avoids loading flash). */
  initialData: LeagueStandingsResponse | null;
}

interface UseLeaderboardResult {
  standings: StandingEntry[];
  updatedAt: Date | null;
  isLoading: boolean;
  error: string | null;
  /** True when a Realtime update is being applied (brief re-fetch). */
  isRefreshing: boolean;
}

export function useLeaderboard({
  leagueId,
  initialData,
}: UseLeaderboardOptions): UseLeaderboardResult {
  const [standings, setStandings] = useState<StandingEntry[]>(
    initialData?.standings ?? [],
  );
  const [updatedAt, setUpdatedAt] = useState<Date | null>(
    initialData?.updated_at ? new Date(initialData.updated_at) : null,
  );
  const [isLoading, setIsLoading] = useState<boolean>(initialData === null);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Ref to track Realtime connection status for fallback polling
  const realtimeConnected = useRef<boolean>(false);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ---------------------------------------------------------------------------
  // Fetch standings from FastAPI
  // ---------------------------------------------------------------------------

  const fetchStandings = useCallback(
    async (isBackground: boolean = false) => {
      if (isBackground) {
        setIsRefreshing(true);
      } else {
        setIsLoading(true);
      }
      setError(null);

      try {
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL}/leagues/${leagueId}/standings`,
          {
            // No-cache: standings must always be fresh after a Realtime event
            cache: "no-store",
            headers: {
              "Content-Type": "application/json",
            },
            // Include cookies so the JWT is forwarded automatically
            credentials: "include",
          },
        );

        if (!res.ok) {
          // 404 = draft not started yet, not an error worth showing
          if (res.status === 404) {
            setStandings([]);
            return;
          }
          throw new Error(`HTTP ${res.status}`);
        }

        const data: LeagueStandingsResponse = await res.json();
        setStandings(data.standings);
        setUpdatedAt(data.updated_at ? new Date(data.updated_at) : null);
      } catch (err) {
        const message =
          err instanceof Error
            ? err.message
            : "Unknown error fetching standings";
        setError(message);
      } finally {
        setIsLoading(false);
        setIsRefreshing(false);
      }
    },
    [leagueId],
  );

  // ---------------------------------------------------------------------------
  // Fallback polling — activates when Realtime is not connected
  // ---------------------------------------------------------------------------

  const startPolling = useCallback(() => {
    if (pollIntervalRef.current) return; // already polling
    pollIntervalRef.current = setInterval(() => {
      if (!realtimeConnected.current) {
        fetchStandings(true);
      }
    }, FALLBACK_POLL_INTERVAL_MS);
  }, [fetchStandings]);

  const stopPolling = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  }, []);

  // ---------------------------------------------------------------------------
  // Supabase Realtime Postgres Changes subscription
  // ---------------------------------------------------------------------------

  useEffect(() => {
    // Fetch on mount if no initial data was provided
    if (initialData === null) {
      fetchStandings(false);
    }

    const supabase = createBrowserSupabaseClient();

    const channel = supabase
      .channel(`leaderboard:${leagueId}`)
      .on(
        "postgres_changes",
        {
          event: "*", // INSERT, UPDATE, DELETE
          schema: "public",
          table: "league_standings",
          filter: `league_id=eq.${leagueId}`,
        },
        () => {
          // A row changed — re-fetch the full standings from FastAPI.
          // We ignore the raw payload: rank may have changed for multiple
          // managers simultaneously, so a partial patch is unsafe.
          fetchStandings(true);
        },
      )
      .on("system", { event: "connected" }, () => {
        realtimeConnected.current = true;
        stopPolling();
      })
      .on("system", { event: "disconnected" }, () => {
        realtimeConnected.current = false;
        startPolling();
      })
      .subscribe((status) => {
        if (status === "SUBSCRIBED") {
          realtimeConnected.current = true;
          stopPolling();
        } else if (status === "CHANNEL_ERROR" || status === "TIMED_OUT") {
          realtimeConnected.current = false;
          startPolling();
        }
      });

    // Cleanup on unmount or leagueId change
    return () => {
      supabase.removeChannel(channel);
      stopPolling();
      realtimeConnected.current = false;
    };
  }, [leagueId, initialData, fetchStandings, startPolling, stopPolling]);

  return { standings, updatedAt, isLoading, isRefreshing, error };
}
