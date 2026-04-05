// frontend/src/app/[locale]/(protected)/dashboard/page.tsx

/**
 * Dashboard page — Server Component.
 *
 * Fetches the user's active leagues from FastAPI server-side.
 * Three rendering paths:
 *   1. Zero leagues   → renders DashboardEmptyState (join/create CTAs)
 *   2. One league     → redirect to /league/[leagueId]/leaderboard (D-047)
 *   3. Multiple leagues → renders league cards grid
 *
 * CDC §5.2: Dashboard personnel.
 * Decision D-047: single-league auto-redirect.
 */

import { redirect } from "next/navigation";
import { getTranslations, getLocale } from "next-intl/server";
import { PlusCircle, Users } from "lucide-react";
import Link from "next/link";

import { createServerSupabaseClient } from "@/lib/supabase/server";
import { DashboardEmptyState } from "@/components/dashboard/DashboardEmptyState";
import { DashboardLeagueCard } from "@/components/dashboard/DashboardLeagueCard";
import type { DashboardResponse } from "@/types/dashboard";

// ---------------------------------------------------------------------------
// Server-side fetch
// ---------------------------------------------------------------------------

async function fetchDashboard(
  accessToken: string,
): Promise<DashboardResponse | null> {
  try {
    const res = await fetch(`${process.env.API_URL}/dashboard`, {
      headers: {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json",
      },
      next: { revalidate: 30 },
    });

    if (!res.ok) {
      console.error(`[dashboard/page] fetch failed: HTTP ${res.status}`);
      return null;
    }

    return res.json();
  } catch (err) {
    console.error("[dashboard/page] fetch error:", err);
    return null;
  }
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default async function DashboardPage() {
  const t = await getTranslations("dashboard");
  const locale = await getLocale();

  const supabase = await createServerSupabaseClient();

  // Use getUser() — revalidates the JWT with Supabase Auth server.
  // More reliable than getSession() in Server Components (Next.js 15):
  // getSession() only reads the local cookie without network revalidation,
  // which can return null depending on cookie timing. getUser() always
  // performs a network call and returns a valid token when authenticated.
  // Same pattern used in (protected)/layout.tsx.
  const {
    data: { user },
  } = await supabase.auth.getUser();

  // If no user, the protected layout would have already redirected.
  // This is a safety net — should never happen in practice.
  if (!user) {
    redirect(`/${locale}/login`);
  }

  // Extract the access token from the session for FastAPI calls.
  // getSession() is safe here after getUser() confirmed the session exists.
  const {
    data: { session },
  } = await supabase.auth.getSession();

  const accessToken = session?.access_token ?? "";

  const data =
    accessToken.length > 0 ? await fetchDashboard(accessToken) : null;

  const leagues = data?.leagues ?? [];

  // D-047: single active league → redirect server-side (no client flash).
  if (leagues.length === 1) {
    redirect(`/${locale}/league/${leagues[0].league_id}/leaderboard`);
  }

  return (
    <main className="mx-auto max-w-3xl px-4 py-8 sm:px-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">
          {t("title")}
        </h1>

        {leagues.length > 0 && (
          <div className="flex items-center gap-2">
            <Link
              href={`/${locale}/league/join`}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-background px-3 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              <Users className="h-4 w-4" aria-hidden="true" />
              {t("joinLeague")}
            </Link>
            <Link
              href={`/${locale}/league/create`}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              <PlusCircle className="h-4 w-4" aria-hidden="true" />
              {t("createLeague")}
            </Link>
          </div>
        )}
      </div>

      {leagues.length === 0 && <DashboardEmptyState />}

      {leagues.length > 1 && (
        <section aria-label={t("myLeagues")}>
          <div className="grid gap-4 sm:grid-cols-2">
            {leagues.map((league) => (
              <DashboardLeagueCard key={league.league_id} league={league} />
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
