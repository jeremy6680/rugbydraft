// frontend/src/app/[locale]/(protected)/stats/page.tsx

/**
 * Stats page — Server Component.
 *
 * Fetches competition_id from the user's active league (server-side).
 * Passes it to the StatsPageClient which owns all interactive state.
 *
 * The page is accessible during draft (read-only stats tab — CDC §12).
 * No leagueId is required — stats are global per competition.
 * leagueId is passed optionally to enrich pool_status per player.
 */

import { getTranslations } from "next-intl/server";
import { StatsPageClient } from "@/components/stats/StatsPageClient";

// For now, competition_id is hardcoded to the mock value used in usePlayerStats.
// TODO: resolve competition_id from the user's active league once the DB is populated.
const MOCK_COMPETITION_ID = "00000000-0000-0000-0000-000000000099";

export default async function StatsPage() {
  const t = await getTranslations("stats");

  return (
    <main className="mx-auto max-w-screen-xl px-4 py-6 sm:px-6 lg:px-8">
      <h1 className="mb-6 text-2xl font-bold tracking-tight">{t("title")}</h1>
      <StatsPageClient
        competitionId={MOCK_COMPETITION_ID}
        leagueId={undefined}
      />
    </main>
  );
}
