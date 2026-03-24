// frontend/src/app/[locale]/(protected)/draft/[draftId]/page.tsx
/**
 * Draft Room page — Server Component.
 *
 * Responsibilities:
 *   1. Retrieve the authenticated user's ID (server-side, from Supabase session).
 *   2. Fetch the full player pool from the FastAPI backend (server-side).
 *   3. Fetch manager display names for this league from Supabase (server-side).
 *   4. Pass all data as props to DraftRoom (Client Component).
 *
 * Why fetch server-side?
 *   - Player pool (300+ records) should not trigger a loading spinner in the
 *     Draft Room — it must be ready on first paint.
 *   - Manager names come from Supabase tables protected by RLS — the server
 *     client uses the user's JWT and can read them directly.
 *   - currentUserId is needed by DraftRoom for isMyTurn logic — passing it
 *     from a Server Component avoids an extra client-side auth.getSession() call.
 *
 * Architecture (D-001):
 *   This page does NOT fetch draft state — that is handled by useDraftRealtime
 *   inside DraftRoom via POST /draft/{leagueId}/connect + Supabase Realtime.
 */

import { redirect } from "next/navigation";
import { getLocale } from "next-intl/server";
import { createServerSupabaseClient } from "@/lib/supabase/server";
import DraftRoom from "@/components/draft/DraftRoom";
import type { PlayerSummary } from "@/types/player";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ---------------------------------------------------------------------------
// Page props
// ---------------------------------------------------------------------------

interface DraftPageProps {
  params: Promise<{
    locale: string;
    draftId: string; // maps to league_id in the draft engine
  }>;
}

// ---------------------------------------------------------------------------
// Server-side data fetchers
// ---------------------------------------------------------------------------

/**
 * Fetch the full player pool from the FastAPI backend.
 * Uses the user's JWT for authentication.
 * Returns an empty array on failure (Draft Room handles empty gracefully).
 */
async function fetchPlayers(authToken: string): Promise<PlayerSummary[]> {
  try {
    const response = await fetch(`${API_BASE_URL}/players`, {
      headers: {
        Authorization: `Bearer ${authToken}`,
      },
      // next.js fetch cache: revalidate every 60s.
      // Players change rarely (transfers, injuries) — 60s is acceptable.
      next: { revalidate: 60 },
    });

    if (!response.ok) {
      console.error(
        "[DraftPage] fetchPlayers failed:",
        response.status,
        await response.text(),
      );
      return [];
    }

    return response.json() as Promise<PlayerSummary[]>;
  } catch (err) {
    console.error("[DraftPage] fetchPlayers error:", err);
    return [];
  }
}

/**
 * Fetch display names for all managers in this league.
 * Reads from league_members joined with users via Supabase.
 * Returns empty object on failure — DraftRoom falls back to "Manager inconnu".
 */
async function fetchManagerNames(
  leagueId: string,
  supabase: Awaited<ReturnType<typeof createServerSupabaseClient>>,
): Promise<Record<string, string>> {
  try {
    // league_members links user_id to league_id.
    // users table holds display_name (set at signup).
    const { data, error } = await supabase
      .from("league_members")
      .select("user_id, users(display_name)")
      .eq("league_id", leagueId);

    if (error || !data) {
      console.error("[DraftPage] fetchManagerNames error:", error);
      return {};
    }

    // Build map: user_id → display_name
    const names: Record<string, string> = {};
    for (const row of data) {
      const displayName =
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (row as any).users?.display_name ?? "Manager";
      names[row.user_id] = displayName;
    }

    return names;
  } catch (err) {
    console.error("[DraftPage] fetchManagerNames error:", err);
    return {};
  }
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default async function DraftPage({ params }: DraftPageProps) {
  const { draftId } = await params;
  const locale = await getLocale();

  // --- Session verification ---
  // The (protected) layout already redirects unauthenticated users,
  // but we need the user.id to pass to DraftRoom.
  const supabase = await createServerSupabaseClient();
  const {
    data: { user },
    error: authError,
  } = await supabase.auth.getUser();

  if (!user || authError) {
    redirect(`/${locale}/login`);
  }

  // --- Parallel data fetching ---
  // Fetch players and manager names concurrently — no dependency between them.
  const {
    data: { session },
  } = await supabase.auth.getSession();

  const authToken = session?.access_token ?? "";

  const [players, managerNames] = await Promise.all([
    fetchPlayers(authToken),
    fetchManagerNames(draftId, supabase),
  ]);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    // Full-screen layout for the Draft Room — overrides the AppShell padding.
    // The Draft Room manages its own internal layout (sidebar + main area).
    <div className="h-full overflow-hidden">
      <DraftRoom
        leagueId={draftId}
        currentUserId={user.id}
        players={players}
        managerNames={managerNames}
      />
    </div>
  );
}
