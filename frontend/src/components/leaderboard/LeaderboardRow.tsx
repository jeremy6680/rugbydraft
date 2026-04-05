// frontend/src/components/leaderboard/LeaderboardRow.tsx

"use client";

/**
 * LeaderboardRow — a single row in the league standings table.
 *
 * Pure presentational component — no state, no side effects.
 * Highlights the current user's row. Displays medal icons for top 3.
 */

import { motion } from "framer-motion";
import { useTranslations } from "next-intl";

import type { StandingEntry } from "@/types/leaderboard";

interface LeaderboardRowProps {
  entry: StandingEntry;
  /** UUID of the currently authenticated manager. */
  currentUserId: string;
  /** Row index for staggered animation delay. */
  index: number;
}

/** Medal icon for top 3 ranks. Returns null for rank > 3. */
function RankBadge({ rank }: { rank: number }) {
  if (rank === 1) return <span aria-label="1er">🥇</span>;
  if (rank === 2) return <span aria-label="2ème">🥈</span>;
  if (rank === 3) return <span aria-label="3ème">🥉</span>;
  return (
    <span className="text-sm font-semibold text-muted-foreground">{rank}</span>
  );
}

export function LeaderboardRow({
  entry,
  currentUserId,
  index,
}: LeaderboardRowProps) {
  const t = useTranslations("leaderboard");

  const isCurrentUser = entry.member_id === currentUserId;

  return (
    <motion.tr
      key={entry.member_id}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, delay: index * 0.04 }}
      className={[
        "border-b border-border transition-colors",
        isCurrentUser ? "bg-primary/10 font-semibold" : "hover:bg-muted/50",
      ].join(" ")}
      // Accessibility: mark the current user's row for screen readers
      aria-current={isCurrentUser ? "true" : undefined}
    >
      {/* Rank */}
      <td className="w-12 px-4 py-3 text-center">
        <RankBadge rank={entry.rank} />
      </td>

      {/* Manager name */}
      <td className="px-4 py-3">
        <span className="flex items-center gap-2">
          {entry.display_name}
          {isCurrentUser && (
            <span
              className="rounded-full bg-primary px-2 py-0.5 text-xs text-primary-foreground"
              aria-label={t("you_badge_label")}
            >
              {t("you_badge")}
            </span>
          )}
        </span>
      </td>

      {/* Win / Loss record */}
      <td className="px-4 py-3 text-center tabular-nums">
        <span className="text-green-600 dark:text-green-400">
          {entry.wins}V
        </span>
        {" / "}
        <span className="text-red-500 dark:text-red-400">{entry.losses}D</span>
      </td>

      {/* Total points */}
      <td className="px-4 py-3 text-right tabular-nums font-mono text-sm">
        {entry.total_points.toFixed(1)}
        <span className="ml-1 text-xs text-muted-foreground">
          {t("points_unit")}
        </span>
      </td>
    </motion.tr>
  );
}
