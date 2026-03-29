// frontend/src/components/stats/StatsFiltersBar.tsx

"use client";

/**
 * StatsFiltersBar — period selector + client-side filters for the Stats page.
 *
 * Controls:
 * - Period tabs : 1w | 2w | 4w | season
 * - Search input : player name
 * - Position chips : one per position available in the dataset
 * - Pool filter chips : tous | libres | mon équipe
 * - Club/nationality select : derived from the current dataset
 *
 * All filters are applied client-side (D-044).
 * The period selector triggers a new API fetch via setPeriod().
 */

import { Search, X } from "lucide-react";
import { useTranslations } from "next-intl";

import type { StatsPeriod, StatsFilters, StatsPoolFilter } from "@/types/stats";

// ---------------------------------------------------------------------------
// Position display labels — mirrors draft positions (fr.json draft.positions)
// ---------------------------------------------------------------------------

const POSITION_LABELS: Record<string, string> = {
  prop: "Pilier",
  hooker: "Talonneur",
  lock: "2e ligne",
  flanker: "3e ligne aile",
  number_8: "Numéro 8",
  scrum_half: "Demi de mêlée",
  fly_half: "Demi d'ouverture",
  centre: "Centre",
  wing: "Ailier",
  fullback: "Arrière",
};

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface StatsFiltersBarProps {
  period: StatsPeriod;
  filters: StatsFilters;
  availablePositions: string[];
  availableClubs: string[];
  onPeriodChange: (period: StatsPeriod) => void;
  onFiltersChange: (partial: Partial<StatsFilters>) => void;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Single period tab button. */
function PeriodTab({
  value,
  label,
  active,
  onClick,
}: {
  value: StatsPeriod;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={[
        "rounded-md px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active
          ? "bg-primary text-primary-foreground"
          : "text-muted-foreground hover:bg-muted hover:text-foreground",
      ].join(" ")}
    >
      {label}
    </button>
  );
}

/** Single filter chip (position or pool status). */
function FilterChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={[
        "rounded-full px-3 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active
          ? "bg-primary text-primary-foreground"
          : "border border-border bg-background text-muted-foreground hover:bg-muted hover:text-foreground",
      ].join(" ")}
    >
      {label}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function StatsFiltersBar({
  period,
  filters,
  availablePositions,
  availableClubs,
  onPeriodChange,
  onFiltersChange,
}: StatsFiltersBarProps) {
  const t = useTranslations("stats");

  const periods: { value: StatsPeriod; label: string }[] = [
    { value: "1w", label: t("period1w") },
    { value: "2w", label: t("period2w") },
    { value: "4w", label: t("period4w") },
    { value: "season", label: t("periodSeason") },
  ];

  const poolFilters: { value: StatsPoolFilter; label: string }[] = [
    { value: "all", label: t("filterAll") },
    { value: "free", label: t("filterFree") },
    { value: "mine", label: t("filterMine") },
  ];

  /** True if any filter other than period is active. */
  const hasActiveFilters =
    filters.search.trim() !== "" ||
    filters.position !== "" ||
    filters.clubOrNationality !== "" ||
    filters.poolFilter !== "all";

  function clearAllFilters() {
    onFiltersChange({
      search: "",
      position: "",
      clubOrNationality: "",
      poolFilter: "all",
    });
  }

  return (
    <div className="space-y-3">
      {/* ── Row 1: Period tabs ── */}
      <div
        className="flex flex-wrap gap-1 rounded-lg border border-border bg-muted/30 p-1"
        role="group"
        aria-label={t("periodLabel")}
      >
        {periods.map(({ value, label }) => (
          <PeriodTab
            key={value}
            value={value}
            label={label}
            active={period === value}
            onClick={() => onPeriodChange(value)}
          />
        ))}
      </div>

      {/* ── Row 2: Search + club/nationality select ── */}
      <div className="flex flex-wrap gap-2">
        {/* Search */}
        <div className="relative min-w-48 flex-1">
          <Search
            className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <input
            type="search"
            placeholder={t("searchPlaceholder")}
            value={filters.search}
            onChange={(e) => onFiltersChange({ search: e.target.value })}
            className="h-9 w-full rounded-md border border-border bg-background pl-9 pr-3 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={t("searchPlaceholder")}
          />
        </div>

        {/* Club / nationality select */}
        {availableClubs.length > 0 && (
          <select
            value={filters.clubOrNationality}
            onChange={(e) =>
              onFiltersChange({ clubOrNationality: e.target.value })
            }
            className="h-9 rounded-md border border-border bg-background px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={t("filterClubNationality")}
          >
            <option value="">{t("filterClubNationality")}</option>
            {availableClubs.map((club) => (
              <option key={club} value={club.toLowerCase()}>
                {club}
              </option>
            ))}
          </select>
        )}

        {/* Clear all filters button */}
        {hasActiveFilters && (
          <button
            type="button"
            onClick={clearAllFilters}
            className="flex h-9 items-center gap-1.5 rounded-md border border-border px-3 text-sm text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={t("clearFilters")}
          >
            <X className="h-3.5 w-3.5" aria-hidden="true" />
            {t("clearFilters")}
          </button>
        )}
      </div>

      {/* ── Row 3: Position chips ── */}
      {availablePositions.length > 0 && (
        <div
          className="flex flex-wrap gap-1.5"
          role="group"
          aria-label={t("filterPosition")}
        >
          <FilterChip
            label={t("allPositions")}
            active={filters.position === ""}
            onClick={() => onFiltersChange({ position: "" })}
          />
          {availablePositions.map((pos) => (
            <FilterChip
              key={pos}
              label={POSITION_LABELS[pos] ?? pos}
              active={filters.position === pos}
              onClick={() =>
                onFiltersChange({
                  position: filters.position === pos ? "" : pos,
                })
              }
            />
          ))}
        </div>
      )}

      {/* ── Row 4: Pool status chips ── */}
      <div
        className="flex flex-wrap gap-1.5"
        role="group"
        aria-label={t("filterPoolLabel")}
      >
        {poolFilters.map(({ value, label }) => (
          <FilterChip
            key={value}
            label={label}
            active={filters.poolFilter === value}
            onClick={() => onFiltersChange({ poolFilter: value })}
          />
        ))}
      </div>
    </div>
  );
}
