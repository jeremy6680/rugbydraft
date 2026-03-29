// frontend/src/hooks/usePlayerStats.ts

"use client";

/**
 * usePlayerStats — fetch + client-side filtering for the Stats page.
 *
 * Fetches all player stats for a competition + period from FastAPI.
 * Filtering by position, club, availability, and search is done
 * client-side (D-044: period is the only server-side parameter).
 *
 * Mock data is active when USE_MOCK = true (Phase 4 dev — empty DB).
 * Remove the mock flag once the dbt pipeline has populated mart_player_stats_ui.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { createBrowserSupabaseClient } from "@/lib/supabase/client";
import type {
  PlayerStatsResponse,
  PlayerStatsRow,
  StatsPeriod,
  StatsFilters,
} from "@/types/stats";
import { DEFAULT_STATS_FILTERS } from "@/types/stats";

// ---------------------------------------------------------------------------
// Mock flag — set to false once mart_player_stats_ui is populated
// ---------------------------------------------------------------------------

const USE_MOCK = true;

// ---------------------------------------------------------------------------
// Mock data — representative sample covering all positions and stat types
// ---------------------------------------------------------------------------

const MOCK_PLAYERS: PlayerStatsRow[] = [
  {
    player_id: "00000000-0000-0000-0000-000000000001",
    competition_id: "00000000-0000-0000-0000-000000000099",
    period: "season",
    player_name: "Antoine Dupont",
    position_type: "scrum_half",
    nationality: "France",
    club: "Stade Toulousain",
    availability_status: "available",
    pool_status: "free",
    rounds_played: 4,
    total_points: 87.5,
    avg_points: 21.9,
    tries: 3,
    try_assists: 5,
    metres_carried: 210,
    kick_assists: 2,
    line_breaks: 8,
    catch_from_kick: 3,
    conversions_made: 0,
    penalties_made: 0,
    tackles: 22,
    turnovers_won: 4,
    lineouts_won: 0,
    lineouts_lost: 0,
    turnovers_conceded: 2,
    missed_tackles: 3,
    handling_errors: 1,
    penalties_conceded: 2,
    yellow_cards: 0,
    red_cards: 0,
    trend: "up",
  },
  {
    player_id: "00000000-0000-0000-0000-000000000002",
    competition_id: "00000000-0000-0000-0000-000000000099",
    period: "season",
    player_name: "Romain Ntamack",
    position_type: "fly_half",
    nationality: "France",
    club: "Stade Toulousain",
    availability_status: "available",
    pool_status: "drafted",
    rounds_played: 4,
    total_points: 74.0,
    avg_points: 18.5,
    tries: 1,
    try_assists: 3,
    metres_carried: 95,
    kick_assists: 1,
    line_breaks: 3,
    catch_from_kick: 1,
    conversions_made: 8,
    penalties_made: 6,
    tackles: 18,
    turnovers_won: 2,
    lineouts_won: 0,
    lineouts_lost: 0,
    turnovers_conceded: 1,
    missed_tackles: 2,
    handling_errors: 0,
    penalties_conceded: 1,
    yellow_cards: 0,
    red_cards: 0,
    trend: "stable",
  },
  {
    player_id: "00000000-0000-0000-0000-000000000003",
    competition_id: "00000000-0000-0000-0000-000000000099",
    period: "season",
    player_name: "Grégory Alldritt",
    position_type: "number_8",
    nationality: "France",
    club: "La Rochelle",
    availability_status: "available",
    pool_status: "mine",
    rounds_played: 4,
    total_points: 68.0,
    avg_points: 17.0,
    tries: 2,
    try_assists: 1,
    metres_carried: 320,
    kick_assists: 0,
    line_breaks: 5,
    catch_from_kick: 0,
    conversions_made: 0,
    penalties_made: 0,
    tackles: 45,
    turnovers_won: 5,
    lineouts_won: 3,
    lineouts_lost: 1,
    turnovers_conceded: 3,
    missed_tackles: 4,
    handling_errors: 2,
    penalties_conceded: 3,
    yellow_cards: 1,
    red_cards: 0,
    trend: "up",
  },
  {
    player_id: "00000000-0000-0000-0000-000000000004",
    competition_id: "00000000-0000-0000-0000-000000000099",
    period: "season",
    player_name: "Cyril Baille",
    position_type: "prop",
    nationality: "France",
    club: "Stade Toulousain",
    availability_status: "injured",
    pool_status: "drafted",
    rounds_played: 2,
    total_points: 28.5,
    avg_points: 14.3,
    tries: 1,
    try_assists: 0,
    metres_carried: 88,
    kick_assists: 0,
    line_breaks: 1,
    catch_from_kick: 0,
    conversions_made: 0,
    penalties_made: 0,
    tackles: 28,
    turnovers_won: 2,
    lineouts_won: 8,
    lineouts_lost: 2,
    turnovers_conceded: 1,
    missed_tackles: 2,
    handling_errors: 1,
    penalties_conceded: 4,
    yellow_cards: 0,
    red_cards: 0,
    trend: "down",
  },
  {
    player_id: "00000000-0000-0000-0000-000000000005",
    competition_id: "00000000-0000-0000-0000-000000000099",
    period: "season",
    player_name: "Thomas Ramos",
    position_type: "fullback",
    nationality: "France",
    club: "Stade Toulousain",
    availability_status: "available",
    pool_status: "free",
    rounds_played: 4,
    total_points: 61.5,
    avg_points: 15.4,
    tries: 2,
    try_assists: 2,
    metres_carried: 175,
    kick_assists: 0,
    line_breaks: 6,
    catch_from_kick: 7,
    conversions_made: 10,
    penalties_made: 8,
    tackles: 15,
    turnovers_won: 1,
    lineouts_won: 0,
    lineouts_lost: 0,
    turnovers_conceded: 0,
    missed_tackles: 1,
    handling_errors: 0,
    penalties_conceded: 1,
    yellow_cards: 0,
    red_cards: 0,
    trend: "up",
  },
  {
    player_id: "00000000-0000-0000-0000-000000000006",
    competition_id: "00000000-0000-0000-0000-000000000099",
    period: "season",
    player_name: "Paul Willemse",
    position_type: "lock",
    nationality: "France",
    club: "Montpellier",
    availability_status: "suspended",
    pool_status: "free",
    rounds_played: 3,
    total_points: 35.0,
    avg_points: 11.7,
    tries: 1,
    try_assists: 0,
    metres_carried: 145,
    kick_assists: 0,
    line_breaks: 2,
    catch_from_kick: 0,
    conversions_made: 0,
    penalties_made: 0,
    tackles: 38,
    turnovers_won: 3,
    lineouts_won: 12,
    lineouts_lost: 3,
    turnovers_conceded: 2,
    missed_tackles: 3,
    handling_errors: 2,
    penalties_conceded: 5,
    yellow_cards: 1,
    red_cards: 1,
    trend: "down",
  },
];

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

interface UsePlayerStatsOptions {
  competitionId: string;
  leagueId?: string;
}

interface UsePlayerStatsResult {
  /** Full unfiltered player list for the current period. */
  allPlayers: PlayerStatsRow[];
  /** Filtered + sorted player list ready to render. */
  filteredPlayers: PlayerStatsRow[];
  period: StatsPeriod;
  filters: StatsFilters;
  isLoading: boolean;
  error: string | null;
  /** Change the active period — triggers a new API fetch. */
  setPeriod: (period: StatsPeriod) => void;
  /** Update one or more filter fields. */
  setFilters: (partial: Partial<StatsFilters>) => void;
  /** List of all distinct positions in the current dataset (for filter chips). */
  availablePositions: string[];
  /** List of all distinct clubs/nationalities in the current dataset. */
  availableClubs: string[];
}

export function usePlayerStats({
  competitionId,
  leagueId,
}: UsePlayerStatsOptions): UsePlayerStatsResult {
  const [allPlayers, setAllPlayers] = useState<PlayerStatsRow[]>([]);
  const [period, setPeriodState] = useState<StatsPeriod>("season");
  const [filters, setFiltersState] = useState<StatsFilters>(
    DEFAULT_STATS_FILTERS,
  );
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const supabase = createBrowserSupabaseClient();

  // ---------------------------------------------------------------------------
  // Fetch
  // ---------------------------------------------------------------------------

  const fetchStats = useCallback(
    async (activePeriod: StatsPeriod) => {
      setIsLoading(true);
      setError(null);

      // Dev mock — bypass API when DB is empty
      if (USE_MOCK) {
        // Simulate network latency
        await new Promise((resolve) => setTimeout(resolve, 400));
        // Stamp all mock rows with the active period
        setAllPlayers(
          MOCK_PLAYERS.map((p) => ({ ...p, period: activePeriod })),
        );
        setIsLoading(false);
        return;
      }

      try {
        const {
          data: { session },
        } = await supabase.auth.getSession();

        if (!session) {
          setError("Session expirée. Veuillez vous reconnecter.");
          return;
        }

        const params = new URLSearchParams({
          competition_id: competitionId,
          period: activePeriod,
        });
        if (leagueId) params.set("league_id", leagueId);

        const res = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL}/stats/players?${params}`,
          {
            headers: {
              Authorization: `Bearer ${session.access_token}`,
              "Content-Type": "application/json",
            },
          },
        );

        if (!res.ok) {
          if (res.status === 404) {
            // Pipeline hasn't run yet — show empty state, not an error
            setAllPlayers([]);
            return;
          }
          throw new Error(`HTTP ${res.status}`);
        }

        const data: PlayerStatsResponse = await res.json();
        setAllPlayers(data.players);
      } catch (err) {
        const message =
          err instanceof Error
            ? err.message
            : "Erreur de chargement des stats.";
        setError(message);
      } finally {
        setIsLoading(false);
      }
    },
    [competitionId, leagueId, supabase],
  );

  // Fetch on mount and whenever period changes
  useEffect(() => {
    void fetchStats(period);
  }, [period, fetchStats]);

  // ---------------------------------------------------------------------------
  // Period setter — triggers re-fetch
  // ---------------------------------------------------------------------------

  const setPeriod = useCallback((newPeriod: StatsPeriod) => {
    setPeriodState(newPeriod);
    // fetchStats is triggered by the useEffect above on period change
  }, []);

  // ---------------------------------------------------------------------------
  // Filter setter
  // ---------------------------------------------------------------------------

  const setFilters = useCallback((partial: Partial<StatsFilters>) => {
    setFiltersState((prev) => ({ ...prev, ...partial }));
  }, []);

  // ---------------------------------------------------------------------------
  // Client-side filtering (D-044)
  // ---------------------------------------------------------------------------

  const filteredPlayers = useMemo(() => {
    let result = allPlayers;

    // Search filter — player name
    if (filters.search.trim()) {
      const query = filters.search.toLowerCase();
      result = result.filter((p) =>
        p.player_name.toLowerCase().includes(query),
      );
    }

    // Position filter
    if (filters.position) {
      result = result.filter((p) => p.position_type === filters.position);
    }

    // Club or nationality filter
    if (filters.clubOrNationality) {
      const val = filters.clubOrNationality.toLowerCase();
      result = result.filter(
        (p) =>
          p.club?.toLowerCase() === val || p.nationality?.toLowerCase() === val,
      );
    }

    // Pool status filter
    if (filters.poolFilter !== "all") {
      result = result.filter((p) => {
        if (filters.poolFilter === "free") return p.pool_status === "free";
        if (filters.poolFilter === "mine") return p.pool_status === "mine";
        return true;
      });
    }

    return result;
  }, [allPlayers, filters]);

  // ---------------------------------------------------------------------------
  // Derived lists for filter chips
  // ---------------------------------------------------------------------------

  const availablePositions = useMemo(
    () => [...new Set(allPlayers.map((p) => p.position_type))].sort(),
    [allPlayers],
  );

  const availableClubs = useMemo(
    () =>
      [
        ...new Set(
          allPlayers.map((p) => p.club ?? p.nationality ?? "").filter(Boolean),
        ),
      ].sort(),
    [allPlayers],
  );

  return {
    allPlayers,
    filteredPlayers,
    period,
    filters,
    isLoading,
    error,
    setPeriod,
    setFilters,
    availablePositions,
    availableClubs,
  };
}
