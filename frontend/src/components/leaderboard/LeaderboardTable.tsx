// frontend/src/components/leaderboard/LeaderboardTable.tsx

"use client";

/**
 * LeaderboardTable — full standings table with Realtime updates.
 *
 * Orchestrates useLeaderboard (fetch + Supabase Realtime) and renders
 * the standings as an accessible table. Handles loading, error, and
 * empty states explicitly.
 */

import { motion, AnimatePresence } from "framer-motion";
import { RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";

import { useLeaderboard } from "@/hooks/useLeaderboard";
import type { LeagueStandingsResponse } from "@/types/leaderboard";
import { LeaderboardRow } from "./LeaderboardRow";

interface LeaderboardTableProps {
  leagueId: string;
  currentUserId: string;
  initialData: LeagueStandingsResponse | null;
}

/** Formats a Date as a relative "X min ago" string (French). */
function formatRelativeTime(date: Date): string {
  const diffMs = Date.now() - date.getTime();
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return "à l'instant";
  if (diffMin < 60) return `il y a ${diffMin} min`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `il y a ${diffH}h`;
  return `il y a ${Math.floor(diffH / 24)}j`;
}

export function LeaderboardTable({
  leagueId,
  currentUserId,
  initialData,
}: LeaderboardTableProps) {
  const t = useTranslations("leaderboard");
  const { standings, updatedAt, isLoading, isRefreshing, error } =
    useLeaderboard({ leagueId, initialData });

  // ---------------------------------------------------------------------------
  // Loading state — only shown when there is no initial data at all
  // ---------------------------------------------------------------------------

  if (isLoading) {
    return (
      <div
        className="flex items-center justify-center py-24 text-muted-foreground"
        aria-live="polite"
        aria-busy="true"
      >
        <RefreshCw className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
        {t("loading")}
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
        <p className="font-semibold">{t("error_title")}</p>
        <p className="mt-1 text-sm text-muted-foreground">{t("error_retry")}</p>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Empty state — draft not started yet
  // ---------------------------------------------------------------------------

  if (standings.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border py-16 text-center text-muted-foreground">
        <p className="text-sm">{t("empty_state")}</p>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Main table
  // ---------------------------------------------------------------------------

  return (
    <div className="space-y-3">
      {/* Refresh indicator — appears briefly during background re-fetch */}
      <AnimatePresence>
        {isRefreshing && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="flex items-center gap-2 text-xs text-muted-foreground"
            aria-live="polite"
            aria-label={t("refreshing")}
          >
            <RefreshCw className="h-3 w-3 animate-spin" aria-hidden="true" />
            {t("refreshing")}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Standings table */}
      <div className="overflow-x-auto rounded-lg border border-border">
        <table
          className="w-full border-collapse text-sm"
          aria-label={t("table_aria_label")}
        >
          <thead>
            <tr className="border-b border-border bg-muted/50 text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <th className="w-12 px-4 py-3 text-center" scope="col">
                {t("col_rank")}
              </th>
              <th className="px-4 py-3" scope="col">
                {t("col_manager")}
              </th>
              <th className="px-4 py-3 text-center" scope="col">
                {t("col_record")}
              </th>
              <th className="px-4 py-3 text-right" scope="col">
                {t("col_points")}
              </th>
            </tr>
          </thead>
          <tbody>
            {standings.map((entry, index) => (
              <LeaderboardRow
                key={entry.member_id}
                entry={entry}
                currentUserId={currentUserId}
                index={index}
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* Last updated timestamp */}
      {updatedAt && (
        <p className="text-right text-xs text-muted-foreground">
          {t("last_updated", { time: formatRelativeTime(updatedAt) })}
        </p>
      )}
    </div>
  );
}
