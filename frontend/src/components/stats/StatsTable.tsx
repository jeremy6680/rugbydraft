// frontend/src/components/stats/StatsTable.tsx

"use client";

/**
 * StatsTable — sortable player stats table with column group tabs.
 *
 * Column groups (tabs):
 *   points     — total_points, avg_points, rounds_played, trend
 *   attack     — tries, try_assists, metres_carried, kick_assists,
 *                line_breaks, catch_from_kick, conversions_made, penalties_made
 *   defence    — tackles, turnovers_won, lineouts_won, lineouts_lost,
 *                turnovers_conceded, missed_tackles, handling_errors,
 *                penalties_conceded
 *   discipline — yellow_cards, red_cards
 *
 * The player identity column (name, position, club, status) is always visible.
 * Sorting is client-side — clicking a column header toggles asc/desc.
 *
 * Scoring system v2 — DECISIONS.md D-039.
 */

import { useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  TrendingUp,
  TrendingDown,
  Minus,
} from "lucide-react";
import { useTranslations } from "next-intl";

import type {
  PlayerStatsRow,
  StatsColumnGroup,
  StatsTrend,
} from "@/types/stats";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type SortKey = keyof PlayerStatsRow;
type SortDirection = "asc" | "desc";

interface SortState {
  key: SortKey;
  direction: SortDirection;
}

// ---------------------------------------------------------------------------
// Column definitions per group
// ---------------------------------------------------------------------------

interface ColumnDef {
  key: SortKey;
  labelKey: string; // i18n key in stats namespace
  numeric: boolean;
  decimals?: number;
}

const COLUMN_GROUPS: Record<StatsColumnGroup, ColumnDef[]> = {
  points: [
    { key: "avg_points", labelKey: "colAvgPoints", numeric: true, decimals: 1 },
    {
      key: "total_points",
      labelKey: "colTotalPoints",
      numeric: true,
      decimals: 1,
    },
    { key: "rounds_played", labelKey: "colRoundsPlayed", numeric: true },
  ],
  attack: [
    { key: "tries", labelKey: "colTries", numeric: true },
    { key: "try_assists", labelKey: "colTryAssists", numeric: true },
    { key: "metres_carried", labelKey: "colMetres", numeric: true },
    { key: "kick_assists", labelKey: "colKickAssists", numeric: true },
    { key: "line_breaks", labelKey: "colLineBreaks", numeric: true },
    { key: "catch_from_kick", labelKey: "colCatchFromKick", numeric: true },
    { key: "conversions_made", labelKey: "colConversions", numeric: true },
    { key: "penalties_made", labelKey: "colPenalties", numeric: true },
  ],
  defence: [
    { key: "tackles", labelKey: "colTackles", numeric: true },
    { key: "turnovers_won", labelKey: "colTurnoversWon", numeric: true },
    { key: "lineouts_won", labelKey: "colLineoutsWon", numeric: true },
    { key: "lineouts_lost", labelKey: "colLineoutsLost", numeric: true },
    {
      key: "turnovers_conceded",
      labelKey: "colTurnoversConceded",
      numeric: true,
    },
    { key: "missed_tackles", labelKey: "colMissedTackles", numeric: true },
    { key: "handling_errors", labelKey: "colHandlingErrors", numeric: true },
    {
      key: "penalties_conceded",
      labelKey: "colPenaltiesConceded",
      numeric: true,
    },
  ],
  discipline: [
    { key: "yellow_cards", labelKey: "colYellowCards", numeric: true },
    { key: "red_cards", labelKey: "colRedCards", numeric: true },
  ],
};

// Default sort: avg_points descending
const DEFAULT_SORT: SortState = { key: "avg_points", direction: "desc" };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Availability status badge colours. */
function availabilityClass(status: string): string {
  switch (status) {
    case "injured":
      return "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400";
    case "suspended":
      return "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400";
    case "doubtful":
      return "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400";
    default:
      return "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400";
  }
}

/** Pool status badge colours. */
function poolStatusClass(status: string): string {
  switch (status) {
    case "mine":
      return "bg-primary/15 text-primary";
    case "drafted":
      return "bg-muted text-muted-foreground";
    default:
      return "bg-accent/20 text-accent-foreground";
  }
}

/** Trend icon. */
function TrendIcon({ trend }: { trend: StatsTrend }) {
  if (trend === "up")
    return (
      <TrendingUp className="h-4 w-4 text-green-500" aria-label="En hausse" />
    );
  if (trend === "down")
    return (
      <TrendingDown className="h-4 w-4 text-red-500" aria-label="En baisse" />
    );
  return (
    <Minus className="h-4 w-4 text-muted-foreground" aria-label="Stable" />
  );
}

/** Sort a player list by key + direction. */
function sortPlayers(
  players: PlayerStatsRow[],
  { key, direction }: SortState,
): PlayerStatsRow[] {
  return [...players].sort((a, b) => {
    const aVal = a[key];
    const bVal = b[key];
    // String sort (player_name)
    if (typeof aVal === "string" && typeof bVal === "string") {
      return direction === "asc"
        ? aVal.localeCompare(bVal, "fr")
        : bVal.localeCompare(aVal, "fr");
    }
    // Numeric sort
    const aNum = Number(aVal ?? 0);
    const bNum = Number(bVal ?? 0);
    return direction === "asc" ? aNum - bNum : bNum - aNum;
  });
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Column header with sort controls. */
function SortableHeader({
  label,
  columnKey,
  sort,
  onSort,
}: {
  label: string;
  columnKey: SortKey;
  sort: SortState;
  onSort: (key: SortKey) => void;
}) {
  const isActive = sort.key === columnKey;
  return (
    <th scope="col" className="px-3 py-2 text-right">
      <button
        type="button"
        onClick={() => onSort(columnKey)}
        className={[
          "flex w-full items-center justify-end gap-1 text-xs font-medium uppercase tracking-wide transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          isActive
            ? "text-primary"
            : "text-muted-foreground hover:text-foreground",
        ].join(" ")}
        aria-sort={
          isActive
            ? sort.direction === "asc"
              ? "ascending"
              : "descending"
            : "none"
        }
      >
        {label}
        {isActive ? (
          sort.direction === "asc" ? (
            <ArrowUp className="h-3 w-3 shrink-0" aria-hidden="true" />
          ) : (
            <ArrowDown className="h-3 w-3 shrink-0" aria-hidden="true" />
          )
        ) : (
          <ArrowUpDown
            className="h-3 w-3 shrink-0 opacity-40"
            aria-hidden="true"
          />
        )}
      </button>
    </th>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface StatsTableProps {
  players: PlayerStatsRow[];
  isLoading: boolean;
  error: string | null;
}

export function StatsTable({ players, isLoading, error }: StatsTableProps) {
  const t = useTranslations("stats");

  const [activeGroup, setActiveGroup] = useState<StatsColumnGroup>("points");
  const [sort, setSort] = useState<SortState>(DEFAULT_SORT);

  const handleSort = useCallback((key: SortKey) => {
    setSort(
      (prev) =>
        prev.key === key
          ? { key, direction: prev.direction === "asc" ? "desc" : "asc" }
          : { key, direction: "desc" }, // new column: always start desc
    );
  }, []);

  const columns = COLUMN_GROUPS[activeGroup];
  const sortedPlayers = sortPlayers(players, sort);

  const groupTabs: { value: StatsColumnGroup; labelKey: string }[] = [
    { value: "points", labelKey: "groupPoints" },
    { value: "attack", labelKey: "groupAttack" },
    { value: "defence", labelKey: "groupDefence" },
    { value: "discipline", labelKey: "groupDiscipline" },
  ];

  // ---------------------------------------------------------------------------
  // Loading skeleton
  // ---------------------------------------------------------------------------

  if (isLoading) {
    return (
      <div className="space-y-2" aria-busy="true" aria-label={t("loading")}>
        {Array.from({ length: 8 }).map((_, i) => (
          <div
            key={i}
            className="h-12 animate-pulse rounded-md bg-muted"
            style={{ opacity: 1 - i * 0.1 }}
          />
        ))}
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Error state
  // ---------------------------------------------------------------------------

  if (error) {
    return (
      <div
        className="rounded-lg border border-destructive/50 bg-destructive/10 px-6 py-8 text-center text-destructive"
        role="alert"
      >
        <p className="font-semibold">{t("errorTitle")}</p>
        <p className="mt-1 text-sm text-muted-foreground">{error}</p>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Empty state
  // ---------------------------------------------------------------------------

  if (players.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border py-16 text-center text-muted-foreground">
        <p className="text-sm">{t("noStats")}</p>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Table
  // ---------------------------------------------------------------------------

  return (
    <div className="space-y-3">
      {/* Column group tabs */}
      <div
        className="flex flex-wrap gap-1 rounded-lg border border-border bg-muted/30 p-1"
        role="tablist"
        aria-label={t("columnGroupLabel")}
      >
        {groupTabs.map(({ value, labelKey }) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={activeGroup === value}
            onClick={() => {
              setActiveGroup(value);
              // Reset sort to avg_points when switching groups
              setSort(DEFAULT_SORT);
            }}
            className={[
              "rounded-md px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              activeGroup === value
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            ].join(" ")}
          >
            {t(labelKey)}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-lg border border-border">
        <table
          className="w-full border-collapse text-sm"
          aria-label={t("tableAriaLabel")}
        >
          <thead>
            <tr className="border-b border-border bg-muted/50">
              {/* Fixed identity column */}
              <th
                scope="col"
                className="sticky left-0 z-10 min-w-48 bg-muted/50 px-4 py-2 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground"
              >
                <button
                  type="button"
                  onClick={() => handleSort("player_name")}
                  className="flex items-center gap-1 transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  aria-sort={
                    sort.key === "player_name"
                      ? sort.direction === "asc"
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                >
                  {t("colPlayer")}
                  <ArrowUpDown
                    className="h-3 w-3 opacity-40"
                    aria-hidden="true"
                  />
                </button>
              </th>

              {/* Trend column (always visible) */}
              <th
                scope="col"
                className="px-3 py-2 text-center text-xs font-medium uppercase tracking-wide text-muted-foreground"
              >
                {t("colTrend")}
              </th>

              {/* Dynamic columns for the active group */}
              {columns.map((col) => (
                <SortableHeader
                  key={col.key}
                  label={t(col.labelKey)}
                  columnKey={col.key}
                  sort={sort}
                  onSort={handleSort}
                />
              ))}
            </tr>
          </thead>

          <tbody>
            <AnimatePresence mode="wait">
              {sortedPlayers.map((player, index) => (
                <motion.tr
                  key={player.player_id}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.15, delay: index * 0.02 }}
                  className="border-b border-border transition-colors last:border-0 hover:bg-muted/40"
                >
                  {/* Identity cell — sticky */}
                  <td className="sticky left-0 z-10 bg-background px-4 py-3 hover:bg-muted/40">
                    <div className="flex flex-col gap-0.5">
                      {/* Name + pool status */}
                      <div className="flex items-center gap-2">
                        <span className="font-medium leading-tight">
                          {player.player_name}
                        </span>
                        <span
                          className={[
                            "rounded-full px-1.5 py-0.5 text-xs font-medium",
                            poolStatusClass(player.pool_status),
                          ].join(" ")}
                        >
                          {t(`poolStatus.${player.pool_status}`)}
                        </span>
                      </div>
                      {/* Position + club + availability */}
                      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                        <span>{player.position_type}</span>
                        {player.club && (
                          <>
                            <span aria-hidden="true">·</span>
                            <span>{player.club}</span>
                          </>
                        )}
                        {player.availability_status !== "available" && (
                          <>
                            <span aria-hidden="true">·</span>
                            <span
                              className={[
                                "rounded px-1 py-0.5 text-xs",
                                availabilityClass(player.availability_status),
                              ].join(" ")}
                            >
                              {t(`availability.${player.availability_status}`)}
                            </span>
                          </>
                        )}
                      </div>
                    </div>
                  </td>

                  {/* Trend cell */}
                  <td className="px-3 py-3 text-center">
                    <TrendIcon trend={player.trend} />
                  </td>

                  {/* Dynamic stat cells */}
                  {columns.map((col) => {
                    const raw = player[col.key];
                    const value =
                      col.decimals !== undefined
                        ? Number(raw).toFixed(col.decimals)
                        : String(raw ?? 0);

                    return (
                      <td
                        key={col.key}
                        className="px-3 py-3 text-right tabular-nums font-mono text-sm"
                      >
                        {value}
                      </td>
                    );
                  })}
                </motion.tr>
              ))}
            </AnimatePresence>
          </tbody>
        </table>
      </div>

      {/* Row count */}
      <p className="text-right text-xs text-muted-foreground">
        {t("rowCount", { count: players.length })}
      </p>
    </div>
  );
}
