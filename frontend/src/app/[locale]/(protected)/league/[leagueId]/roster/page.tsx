/**
 * Roster management page — Server Component.
 *
 * Fetches the current round ID server-side to avoid a client-side
 * waterfall (roster fetch depends on knowing the current round).
 *
 * Passes leagueId + roundId to RosterManagement (Client Component tree).
 */

import { getTranslations } from "next-intl/server";
import { createServerSupabaseClient } from "@/lib/supabase/server";
import { RosterManagement } from "@/components/roster/RosterManagement";
import { redirect } from "next/navigation";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface RosterPageProps {
  params: Promise<{ locale: string; leagueId: string }>;
}

// ---------------------------------------------------------------------------
// Current round fetch — server-side
// ---------------------------------------------------------------------------

async function getCurrentRoundId(
  leagueId: string,
  accessToken: string,
): Promise<string | null> {
  const apiBase = process.env.API_URL ?? "";

  try {
    const res = await fetch(`${apiBase}/leagues/${leagueId}/current-round`, {
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      // Revalidate every 60s — round changes at most once per week.
      next: { revalidate: 60 },
    });

    if (!res.ok) return null;

    const data = (await res.json()) as { round_id: string };
    return data.round_id;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default async function RosterPage({ params }: RosterPageProps) {
  const { leagueId } = await params;
  const t = await getTranslations();

  // Get the current user session server-side.
  const supabase = await createServerSupabaseClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/fr/login");
  }

  // Fetch current round ID server-side to avoid client waterfall.
  const {
    data: { session },
  } = await supabase.auth.getSession();

  const roundId = session
    ? await getCurrentRoundId(leagueId, session.access_token)
    : null;

  // If no active round, show an informational state.
  // (Competition not started yet, or between seasons.)
  if (!roundId) {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center p-8 text-center">
        <p className="text-sm text-deep-500">{t("roster.noActiveRound")}</p>
      </main>
    );
  }

  return (
    <main className="flex min-h-screen flex-col">
      {/* Page title — visible on desktop, hidden on mobile (tab bar takes over) */}
      <header className="hidden border-b border-deep-200 px-4 py-3 sm:block">
        <h1 className="text-base font-semibold text-deep-900">
          {t("roster.pageTitle")}
        </h1>
      </header>

      <RosterManagement
        currentUserId={user.id}
        leagueId={leagueId}
        roundId={roundId}
      />
    </main>
  );
}
