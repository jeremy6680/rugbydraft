// frontend/src/components/dashboard/DashboardLeagueCard.tsx

/**
 * DashboardLeagueCard — summary card for one active league.
 *
 * Displays: league name, competition, rank, last round score, alerts.
 * Clicking the card navigates to the league's leaderboard.
 * If a draft is active/pending, a prominent CTA links to the Draft Room.
 *
 * CDC §5.2: each league shows rank, last weekend score, next opponent,
 * and alerts.
 */

import Link from "next/link";
import { useTranslations, useLocale } from "next-intl";
import { Trophy, Zap, ChevronRight, Shield } from "lucide-react";

import type { DashboardLeague } from "@/types/dashboard";
import { DashboardAlertBadge } from "./DashboardAlertBadge";

interface DashboardLeagueCardProps {
  league: DashboardLeague;
}

export function DashboardLeagueCard({ league }: DashboardLeagueCardProps) {
  const t = useTranslations("dashboard");
  const locale = useLocale();

  const leagueHref = `/${locale}/league/${league.league_id}/leaderboard`;
  const draftHref = league.draft_id
    ? `/${locale}/draft/${league.draft_id}`
    : null;

  const hasDraftAccess =
    league.draft_id &&
    (league.draft_status === "active" || league.draft_status === "pending");

  return (
    <article
      className="
        relative rounded-xl border border-border bg-card
        p-5 shadow-sm transition-shadow
        hover:shadow-md focus-within:ring-2 focus-within:ring-primary
      "
      aria-label={league.league_name}
    >
      {/* Commissioner badge */}
      {league.is_commissioner && (
        <span
          className="
            absolute right-4 top-4
            inline-flex items-center gap-1
            rounded-full bg-primary/10 px-2 py-0.5
            text-xs font-medium text-primary
          "
          title={t("commissionerBadge")}
        >
          <Shield className="h-3 w-3" aria-hidden="true" />
          {t("commissioner")}
        </span>
      )}

      {/* Header: league name + competition */}
      <Link
        href={leagueHref}
        className="block focus:outline-none"
        aria-label={`${league.league_name} — ${t("goToLeague")}`}
      >
        <h2 className="pr-20 text-base font-semibold text-foreground leading-tight">
          {league.league_name}
        </h2>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {league.competition_name}
        </p>
      </Link>

      {/* Stats row: rank + last round score */}
      <div className="mt-4 flex items-center gap-6">
        {/* Rank */}
        <div className="flex items-center gap-1.5">
          <Trophy
            className="h-4 w-4 text-muted-foreground"
            aria-hidden="true"
          />
          <span className="text-sm text-muted-foreground">{t("rank")}</span>
          <span className="text-sm font-semibold text-foreground">
            {league.current_rank !== null
              ? `${league.current_rank}/${league.total_managers}`
              : "—"}
          </span>
        </div>

        {/* Last round score */}
        {league.last_round_number !== null &&
          league.last_round_points !== null && (
            <div className="text-sm text-muted-foreground">
              <span>
                {t("currentRound", { round: league.last_round_number })}
              </span>
              {" · "}
              <span className="font-semibold text-foreground">
                {league.last_round_points.toFixed(1)}{" "}
                <span className="font-normal text-muted-foreground">
                  {t("points")}
                </span>
              </span>
            </div>
          )}
      </div>

      {/* Alerts row */}
      {league.alerts.length > 0 && (
        <div
          className="mt-3 flex flex-wrap gap-1.5"
          aria-label={t("alertsLabel")}
        >
          {league.alerts.map((alert, idx) => (
            <DashboardAlertBadge
              key={`${alert.alert_type}-${idx}`}
              alert={alert}
            />
          ))}
        </div>
      )}

      {/* Draft CTA — shown only when a draft is active or pending */}
      {hasDraftAccess && draftHref && (
        <Link
          href={draftHref}
          className="
            mt-4 flex w-full items-center justify-center gap-2
            rounded-lg bg-primary px-4 py-2.5
            text-sm font-medium text-primary-foreground
            transition-colors hover:bg-primary/90
            focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary
          "
        >
          <Zap className="h-4 w-4" aria-hidden="true" />
          {league.draft_status === "active"
            ? t("draftInProgress")
            : t("draftUpcoming")}
        </Link>
      )}

      {/* Footer link to leaderboard */}
      {!hasDraftAccess && (
        <Link
          href={leagueHref}
          className="
            mt-4 flex items-center justify-end gap-1
            text-xs text-muted-foreground
            hover:text-foreground transition-colors
          "
          tabIndex={-1}
          aria-hidden="true"
        >
          {t("goToLeague")}
          <ChevronRight className="h-3 w-3" aria-hidden="true" />
        </Link>
      )}
    </article>
  );
}
