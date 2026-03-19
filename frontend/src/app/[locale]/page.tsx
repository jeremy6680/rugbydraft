import { useTranslations } from "next-intl";

/**
 * Temporary home page — Phase 1 skeleton.
 * Will be replaced by the real dashboard in Phase 4.
 * Purpose: verify that next-intl translations load correctly
 * and that design system tokens are applied.
 */
export default function Home() {
  /* useTranslations reads from messages/fr.json via the locale
   * detected by the middleware and provided by LocaleLayout */
  const t = useTranslations();

  return (
    <main className="flex min-h-svh flex-col items-center justify-center gap-8 p-8">
      {/* Brand identity — uses next-intl translations */}
      <div className="flex flex-col items-center gap-2">
        <h1 className="text-4xl font-bold text-primary">
          {t("common.appName")}
        </h1>
        <p className="text-muted-foreground">{t("common.appTagline")}</p>
      </div>

      {/* Color palette verification */}
      <div className="flex flex-wrap gap-3 justify-center">
        <div className="h-12 w-24 rounded-md bg-primary flex items-center justify-center">
          <span className="text-xs text-primary-foreground font-mono">
            primary
          </span>
        </div>
        <div className="h-12 w-24 rounded-md bg-secondary flex items-center justify-center">
          <span className="text-xs text-secondary-foreground font-mono">
            secondary
          </span>
        </div>
        <div className="h-12 w-24 rounded-md bg-accent flex items-center justify-center">
          <span className="text-xs text-accent-foreground font-mono">
            accent
          </span>
        </div>
        <div className="h-12 w-24 rounded-md bg-muted flex items-center justify-center">
          <span className="text-xs text-muted-foreground font-mono">muted</span>
        </div>
        <div className="h-12 w-24 rounded-md bg-destructive flex items-center justify-center">
          <span className="text-xs text-destructive-foreground font-mono">
            destructive
          </span>
        </div>
      </div>

      {/* next-intl verification — nav translations */}
      <div className="rounded-lg border bg-card p-6 text-card-foreground shadow-sm w-full max-w-sm">
        <p className="text-sm font-medium mb-3">next-intl ✓</p>
        <ul className="text-xs text-muted-foreground space-y-1">
          <li>{t("nav.dashboard")}</li>
          <li>{t("nav.draft")}</li>
          <li>{t("nav.roster")}</li>
          <li>{t("nav.leaderboard")}</li>
        </ul>
      </div>
    </main>
  );
}
