// frontend/src/app/[locale]/(protected)/league/[leagueId]/leaderboard/page.tsx

/**
 * Leaderboard page — Server Component.
 *
 * Fetches standings server-side for instant render (no loading flash).
 * Passes initial data to LeaderboardTable which subscribes to Realtime updates.
 *
 * Auth: protected by (protected)/layout.tsx — getUser() is guaranteed.
 */

import { getTranslations } from "next-intl/server";
import { Trophy } from "lucide-react";

import { createServerSupabaseClient } from "@/lib/supabase/server";
import { LeaderboardTable } from "@/components/leaderboard/LeaderboardTable";
import type { LeagueStandingsResponse } from "@/types/leaderboard";

interface LeaderboardPageProps {
  params: Promise<{
    locale: string;
    leagueId: string;
  }>;
}

/**
 * Fetch standings from FastAPI server-side.
 * Returns null on error — LeaderboardTable handles the empty/error state.
 */
async function fetchStandingsServerSide(
  leagueId: string,
  accessToken: string,
): Promise<LeagueStandingsResponse | null> {
  try {
    const res = await fetch(
      `${process.env.API_URL}/leagues/${leagueId}/standings`,
      {
        headers: {
          Authorization: `Bearer ${accessToken}`,
          "Content-Type": "application/json",
        },
        // Revalidate every 60s — standings change only post-match
        next: { revalidate: 60 },
      },
    );

    if (!res.ok) {
      // 404 = no standings yet (draft not started) — not an error
      if (res.status === 404) return null;
      console.error(
        `[leaderboard/page] standings fetch failed: HTTP ${res.status}`,
      );
      return null;
    }

    return res.json();
  } catch (err) {
    console.error("[leaderboard/page] standings fetch error:", err);
    return null;
  }
}

export default async function LeaderboardPage({
  params,
}: LeaderboardPageProps) {
  const { leagueId } = await params;
  const t = await getTranslations("leaderboard");

  // Retrieve the current user's session server-side
  const supabase = await createServerSupabaseClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  const accessToken = session?.access_token ?? "";
  const currentUserId = session?.user?.id ?? "";
  console.log(
    "[debug] accessToken:",
    accessToken ? accessToken.slice(0, 20) + "..." : "EMPTY",
  );
  console.log("[debug] currentUserId:", currentUserId);
  // Parallel: fetch standings (non-blocking — null fallback on error)
  const initialData = accessToken
    ? await fetchStandingsServerSide(leagueId, accessToken)
    : null;

  return (
    <main className="mx-auto max-w-2xl px-4 py-8">
      {/* Page header */}
      <div className="mb-6 flex items-center gap-3">
        <Trophy className="h-6 w-6 text-primary" aria-hidden="true" />
        <h1 className="text-2xl font-bold tracking-tight">{t("page_title")}</h1>
      </div>

      {/* Standings table — handles loading/error/empty internally */}
      <LeaderboardTable
        leagueId={leagueId}
        currentUserId={currentUserId}
        initialData={initialData}
      />
    </main>
  );
}
