// frontend/src/components/dashboard/DashboardAlertBadge.tsx

/**
 * DashboardAlertBadge — renders a single alert chip on a league card.
 *
 * Each alert_type maps to an i18n key and a semantic colour.
 * The detail field (player name, etc.) is interpolated into the label.
 *
 * CDC §5.2 alert types:
 *   player_injured   — orange
 *   player_recovered — green (action required)
 *   waiver_open      — blue
 *   trade_proposed   — purple
 *   ai_report_ready  — lime (Pro+IA only — Phase 5)
 */

import { useTranslations } from "next-intl";
import type { DashboardAlert } from "@/types/dashboard";

interface DashboardAlertBadgeProps {
  alert: DashboardAlert;
}

/** Map each alert type to a Tailwind colour scheme (bg + text). */
const ALERT_COLOURS: Record<
  DashboardAlert["alert_type"],
  { bg: string; text: string }
> = {
  player_injured: {
    bg: "bg-amber-100 dark:bg-amber-950",
    text: "text-amber-800 dark:text-amber-200",
  },
  player_recovered: {
    bg: "bg-green-100 dark:bg-green-950",
    text: "text-green-800 dark:text-green-200",
  },
  waiver_open: {
    bg: "bg-blue-100 dark:bg-blue-950",
    text: "text-blue-800 dark:text-blue-200",
  },
  trade_proposed: {
    bg: "bg-purple-100 dark:bg-purple-950",
    text: "text-purple-800 dark:text-purple-200",
  },
  ai_report_ready: {
    bg: "bg-lime-100 dark:bg-lime-950",
    text: "text-lime-800 dark:text-lime-200",
  },
};

export function DashboardAlertBadge({ alert }: DashboardAlertBadgeProps) {
  const t = useTranslations("dashboard.alerts");
  const colours = ALERT_COLOURS[alert.alert_type];

  // i18n key: dashboard.alerts.player_injured, dashboard.alerts.waiver_open, etc.
  // detail is passed as the interpolation variable {name} when applicable.
  const label = alert.detail
    ? t(alert.alert_type, { name: alert.detail })
    : t(alert.alert_type);

  return (
    <span
      className={`
        inline-flex items-center rounded-full px-2.5 py-0.5
        text-xs font-medium
        ${colours.bg} ${colours.text}
      `}
    >
      {label}
    </span>
  );
}
