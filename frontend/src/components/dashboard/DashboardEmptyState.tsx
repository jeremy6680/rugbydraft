// frontend/src/components/dashboard/DashboardEmptyState.tsx

/**
 * DashboardEmptyState — displayed when the user has no active leagues.
 *
 * CDC §5.2: the dashboard shows a join/create CTA when leagues is empty.
 * CDC §5.3: leagues are joined via invite code or email.
 */

import { useTranslations } from "next-intl";
import { useLocale } from "next-intl";
import Link from "next/link";
import { Users, PlusCircle } from "lucide-react";

export function DashboardEmptyState() {
  const t = useTranslations("dashboard");
  const locale = useLocale();

  return (
    <div className="flex flex-col items-center justify-center py-24 px-6 text-center">
      {/* Icon */}
      <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-full bg-muted">
        <Users className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
      </div>

      {/* Message */}
      <h2 className="mb-2 text-xl font-semibold text-foreground">
        {t("noLeagues")}
      </h2>
      <p className="mb-8 max-w-sm text-sm text-muted-foreground">
        {t("noLeaguesHint")}
      </p>

      {/* CTAs */}
      <div className="flex flex-col gap-3 sm:flex-row">
        <Link
          href={`/${locale}/league/join`}
          className="inline-flex items-center justify-center gap-2 rounded-lg border border-border bg-background px-6 py-3 text-sm font-medium text-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          <Users className="h-4 w-4" aria-hidden="true" />
          {t("joinLeague")}
        </Link>

        <Link
          href={`/${locale}/league/create`}
          className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-6 py-3 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          <PlusCircle className="h-4 w-4" aria-hidden="true" />
          {t("createLeague")}
        </Link>
      </div>
    </div>
  );
}
