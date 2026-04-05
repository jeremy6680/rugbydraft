// frontend/src/components/stats/StatsPageClient.tsx

"use client";

/**
 * StatsPageClient — interactive shell for the Stats page.
 *
 * Owns: period state, filter state, data fetch (via usePlayerStats).
 * Renders: StatsFiltersBar + StatsTable.
 *
 * Separated from the Server Component page to keep the RSC boundary clean.
 */

import { usePlayerStats } from "@/hooks/usePlayerStats";
import { StatsFiltersBar } from "./StatsFiltersBar";
import { StatsTable } from "./StatsTable";

interface StatsPageClientProps {
  competitionId: string;
  leagueId?: string;
}

export function StatsPageClient({
  competitionId,
  leagueId,
}: StatsPageClientProps) {
  const {
    filteredPlayers,
    period,
    filters,
    isLoading,
    error,
    setPeriod,
    setFilters,
    availablePositions,
    availableClubs,
  } = usePlayerStats({ competitionId, leagueId });

  return (
    <div className="space-y-6">
      <StatsFiltersBar
        period={period}
        filters={filters}
        availablePositions={availablePositions}
        availableClubs={availableClubs}
        onPeriodChange={setPeriod}
        onFiltersChange={setFilters}
      />
      <StatsTable
        players={filteredPlayers}
        isLoading={isLoading}
        error={error}
      />
    </div>
  );
}
