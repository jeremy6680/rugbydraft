// frontend/src/components/draft/DraftRoom.tsx
/**
 * DraftRoom — main Draft Room component. Assembles all draft sub-components.
 *
 * This is a Client Component ("use client") because it:
 *   - subscribes to Supabase Realtime via useDraftRealtime
 *   - manages local UI state (selected player, submitting, panel open)
 *   - handles user interactions (pick confirmation)
 *
 * Props:
 *   leagueId      — the league whose draft to display
 *   currentUserId — authenticated user's Supabase UUID (from Server Component)
 *   players       — full player pool (fetched server-side, passed as prop)
 *   managerNames  — map of managerId → display name (fetched server-side)
 *
 * Architecture (D-001):
 *   FastAPI is the authority of state. This component NEVER writes to
 *   Supabase directly. All state changes go through FastAPI endpoints,
 *   which then broadcast updates via Supabase Realtime.
 *
 * Data flow:
 *   useDraftRealtime → DraftUIState (snapshot, isMyTurn, etc.)
 *   snapshot.picks   → pickedPlayerIds (Set) + playerMap (Map)
 *   snapshot.draft_order → upcomingOrder (computed)
 *   user clicks card → selectedPlayer state
 *   user confirms   → POST /draft/{leagueId}/pick → snapshot updates via Realtime
 */

"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { ListOrdered } from "lucide-react";
import { useDraftRealtime } from "@/hooks/useDraftRealtime";
import DraftTimer from "@/components/draft/DraftTimer";
import DraftStatusBanner from "@/components/draft/DraftStatusBanner";
import DraftPlayerList from "@/components/draft/DraftPlayerList";
import DraftOrderPanel, {
  type UpcomingSlot,
} from "@/components/draft/DraftOrderPanel";
import DraftPickConfirmModal from "@/components/draft/DraftPickConfirmModal";
import type { PlayerSummary } from "@/types/player";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Number of upcoming slots to display in DraftOrderPanel
const UPCOMING_SLOTS_SHOWN = 8;

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface DraftRoomProps {
  leagueId: string;
  currentUserId: string;
  /** Full player pool — fetched server-side by the page component. */
  players: PlayerSummary[];
  /** managerId → display name — fetched server-side by the page component. */
  managerNames: Record<string, string>;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function DraftRoom({
  leagueId,
  currentUserId,
  players,
  managerNames,
}: DraftRoomProps) {
  const t = useTranslations("draft");

  // ── Realtime state from hook ──────────────────────────────────────────────
  const {
    snapshot,
    isLoading,
    error,
    isMyTurn,
    isAutodraftActive,
    isDraftActive,
  } = useDraftRealtime(leagueId, currentUserId);

  // ── Local UI state ────────────────────────────────────────────────────────

  /** Player selected for pick confirmation. null = modal closed. */
  const [selectedPlayer, setSelectedPlayer] = useState<PlayerSummary | null>(
    null,
  );

  /** True while POST /pick request is in flight. */
  const [isSubmitting, setIsSubmitting] = useState(false);

  /** Pick submission error message. null = no error. */
  const [pickError, setPickError] = useState<string | null>(null);

  /** Mobile: whether the order panel bottom sheet is open. */
  const [isOrderPanelOpen, setIsOrderPanelOpen] = useState(false);

  // ── Derived data from snapshot ────────────────────────────────────────────

  /**
   * Set of player IDs already picked — O(1) lookup for DraftPlayerList.
   * Recomputed only when snapshot.picks changes.
   */
  const pickedPlayerIds = useMemo<Set<string>>(() => {
    if (!snapshot) return new Set();
    return new Set(snapshot.picks.map((p) => p.player_id));
  }, [snapshot?.picks]); // eslint-disable-line react-hooks/exhaustive-deps

  /**
   * Map of playerId → PlayerSummary — used by DraftOrderPanel to resolve
   * player names in the pick history.
   */
  const playerMap = useMemo<Map<string, PlayerSummary>>(() => {
    return new Map(players.map((p) => [p.id, p]));
  }, [players]);

  /**
   * Upcoming snake order slots for DraftOrderPanel.
   * Shows the current pick + next N slots from snapshot.draft_order.
   *
   * Note: snapshot does not directly expose draft_order (it's internal to
   * FastAPI). We reconstruct the upcoming slots from current_pick_number
   * and manager_names. For now we derive a simple round-robin from
   * connected_managers — a future improvement would expose draft_order
   * in the snapshot.
   *
   * For the MVP, we show the current manager highlighted + next managers
   * derived from the picks already made (to infer order).
   */
  const upcomingOrder = useMemo<UpcomingSlot[]>(() => {
    if (!snapshot) return [];

    // Build upcoming slots starting from current_pick_number.
    // We can't infer full snake order from the snapshot alone —
    // we show at most the current pick slot.
    // TODO: expose draft_order in DraftStateSnapshotResponse (Phase 4 follow-up).
    const slots: UpcomingSlot[] = [];

    if (snapshot.current_manager_id) {
      slots.push({
        pickNumber: snapshot.current_pick_number,
        managerId: snapshot.current_manager_id,
      });
    }

    return slots;
  }, [snapshot]);

  // ── Pick submission ───────────────────────────────────────────────────────

  /**
   * Submit the confirmed pick to FastAPI.
   * Called by DraftPickConfirmModal when the user clicks "Confirmer".
   */
  const handleConfirmPick = useCallback(async () => {
    if (!selectedPlayer) return;

    setIsSubmitting(true);
    setPickError(null);

    try {
      // Retrieve current session token.
      // We import dynamically to keep this component free of Supabase imports
      // at the top level — the auth token is only needed on pick submission.
      const { createBrowserSupabaseClient } =
        await import("@/lib/supabase/client");
      const supabase = createBrowserSupabaseClient();
      const {
        data: { session },
      } = await supabase.auth.getSession();

      if (!session?.access_token) {
        setPickError(t("errorSessionExpired"));
        setIsSubmitting(false);
        return;
      }

      const response = await fetch(`${API_BASE_URL}/draft/${leagueId}/pick`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${session.access_token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ player_id: selectedPlayer.id }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        const detail =
          typeof data.detail === "string" ? data.detail : t("errorPickFailed");
        setPickError(detail);
        setIsSubmitting(false);
        return;
      }

      // Pick accepted — close modal.
      // The snapshot will update automatically via Supabase Realtime broadcast.
      setSelectedPlayer(null);
      setPickError(null);
    } catch {
      setPickError(t("errorPickFailed"));
    } finally {
      setIsSubmitting(false);
    }
  }, [selectedPlayer, leagueId, t]);

  const handleCancelPick = useCallback(() => {
    if (!isSubmitting) {
      setSelectedPlayer(null);
      setPickError(null);
    }
  }, [isSubmitting]);

  // ── Loading state ─────────────────────────────────────────────────────────

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div
            className="w-8 h-8 rounded-full border-2 border-primary border-t-transparent animate-spin"
            aria-hidden="true"
          />
          <p className="text-sm text-muted-foreground">{t("connecting")}</p>
        </div>
      </div>
    );
  }

  // ── Error state ───────────────────────────────────────────────────────────

  if (error && !snapshot) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="text-center space-y-3 max-w-sm">
          <p className="text-sm font-medium text-destructive">{error}</p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="
              text-sm text-primary underline underline-offset-4
              hover:text-primary/80 transition-colors
            "
          >
            {t("retry")}
          </button>
        </div>
      </div>
    );
  }

  // ── Main render ───────────────────────────────────────────────────────────

  const timeRemaining = snapshot?.time_remaining ?? 0;

  return (
    <>
      {/* ── Pick confirmation modal (portal-like, sits above everything) ── */}
      <DraftPickConfirmModal
        player={selectedPlayer}
        timeRemaining={timeRemaining}
        isSubmitting={isSubmitting}
        onConfirm={handleConfirmPick}
        onCancel={handleCancelPick}
      />

      {/* ── Pick error toast — shown below the status banner ── */}
      {pickError && (
        <div
          role="alert"
          aria-live="assertive"
          className="
            fixed top-4 left-1/2 -translate-x-1/2 z-30
            bg-destructive text-destructive-foreground
            text-sm font-medium px-4 py-2 rounded-lg shadow-lg
            max-w-xs text-center
          "
        >
          {pickError}
        </div>
      )}

      {/*
       * ── Main layout ──
       * Mobile:  single column, full height flex
       * Desktop: two columns — sidebar (order panel) + main area
       */}
      <div className="flex h-full overflow-hidden">
        {/* ── Desktop sidebar: DraftOrderPanel ── */}
        <aside
          className="hidden md:flex md:flex-col md:w-72 md:flex-shrink-0 border-r border-border overflow-hidden"
          aria-label="Ordre du draft"
        >
          <DraftOrderPanel
            upcomingOrder={upcomingOrder}
            picks={snapshot?.picks ?? []}
            currentManagerId={snapshot?.current_manager_id ?? null}
            currentUserId={currentUserId}
            managerNames={managerNames}
            playerMap={playerMap}
          />
        </aside>

        {/* ── Main area ── */}
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Status + Timer header */}
          <header className="flex-shrink-0 px-4 pt-4 pb-3 border-b border-border space-y-3">
            <DraftStatusBanner
              isMyTurn={isMyTurn}
              isAutodraftActive={isAutodraftActive}
              isDraftActive={isDraftActive}
              currentManagerId={snapshot?.current_manager_id ?? null}
              managerNames={managerNames}
              currentPickNumber={snapshot?.current_pick_number ?? 1}
              totalPicks={snapshot?.total_picks ?? 0}
            />

            {/* Timer — shown only when it's the user's turn and not autodraft */}
            {isMyTurn && !isAutodraftActive && (
              <div className="flex justify-center">
                <DraftTimer
                  timeRemaining={timeRemaining}
                  isActive={isMyTurn && isDraftActive && !isAutodraftActive}
                  className="w-32"
                />
              </div>
            )}
          </header>

          {/* Player list — scrollable main zone */}
          <main
            id="main-content"
            className="flex-1 overflow-hidden"
            aria-label="Liste des joueurs disponibles"
          >
            <DraftPlayerList
              players={players}
              pickedPlayerIds={pickedPlayerIds}
              onSelect={setSelectedPlayer}
              isMyTurn={isMyTurn}
            />
          </main>

          {/* Mobile: "Ordre" button — opens order panel bottom sheet */}
          <div className="md:hidden flex-shrink-0 border-t border-border px-4 py-3">
            <button
              type="button"
              onClick={() => setIsOrderPanelOpen(true)}
              className="
                w-full flex items-center justify-center gap-2
                py-2.5 rounded-xl border border-border
                text-sm font-medium text-muted-foreground
                hover:text-foreground hover:border-primary/40
                focus:outline-none focus:ring-2 focus:ring-primary
                transition-colors
              "
            >
              <ListOrdered className="w-4 h-4" aria-hidden="true" />
              {t("viewOrder")}
            </button>
          </div>
        </div>
      </div>

      {/* ── Mobile: Order panel bottom sheet ── */}
      {isOrderPanelOpen && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-30 bg-black/50 md:hidden"
            onClick={() => setIsOrderPanelOpen(false)}
            aria-hidden="true"
          />
          {/* Sheet */}
          <div
            className="
              fixed inset-x-0 bottom-0 z-40 md:hidden
              bg-card border-t border-border rounded-t-2xl
              h-[70vh] overflow-hidden
            "
            role="dialog"
            aria-modal="true"
            aria-label="Ordre du draft"
          >
            {/* Drag handle */}
            <div className="flex justify-center pt-3 pb-1" aria-hidden="true">
              <div className="w-10 h-1 rounded-full bg-muted-foreground/30" />
            </div>
            <DraftOrderPanel
              upcomingOrder={upcomingOrder}
              picks={snapshot?.picks ?? []}
              currentManagerId={snapshot?.current_manager_id ?? null}
              currentUserId={currentUserId}
              managerNames={managerNames}
              playerMap={playerMap}
            />
          </div>
        </>
      )}
    </>
  );
}
