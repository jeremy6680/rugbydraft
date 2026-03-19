import { useTranslations } from "next-intl";

/**
 * Dashboard page — placeholder for Phase 1 skeleton.
 * Will be replaced by the real dashboard in Phase 4.
 * Purpose: verify that the AppShell layout wraps correctly.
 */
export default function DashboardPage() {
  const t = useTranslations();

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-bold text-foreground">
        {t("dashboard.title")}
      </h1>
      <p className="text-muted-foreground">{t("dashboard.noLeagues")}</p>
    </div>
  );
}
