/**
 * RosterManagement — main orchestrator for the roster management page.
 *
 * Assembles all roster sub-components, consumes useRoster hook,
 * handles mobile tab navigation and starter ↔ bench swap flow.
 *
 * Layout:
 * - Mobile: tab bar (Titulaires / Remplaçants / Infirmerie) + CaptainKickerBar
 * - Desktop: 3-column layout (starters | bench | IR) + CaptainKickerBar above
 *
 * Swap flow:
 * 1. User clicks a starter → selection set to {mode: "swap_to_bench", ...}
 * 2. User clicks a bench player → updateLineup called with the swap pair
 * 3. User clicks the same player again → deselect
 */

"use client";

import { useCallback, useMemo } from "react";
import { useTranslations } from "next-intl";
import { motion, AnimatePresence } from "framer-motion";

import { useRoster } from "@/hooks/useRosters";
import { RosterSlotGrid } from "./RosterSlotGrid";
import { RosterBenchGrid } from "./RosterBenchGrid";
import { RosterIRPanel } from "./RosterIRPanel";
import { RosterCaptainKickerBar } from "./RosterCaptainKickerBar";

import type {
  RosterSelection,
  RosterSlot,
  RosterView,
  PositionType,
  LineupUpdatePayload,
  WeeklyLineupEntry,
} from "@/types/roster";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface RosterManagementProps {
  leagueId: string;
  roundId: string;
  /** Current user ID — used to gate edit actions (own roster only). */
  currentUserId: string;
}

// ---------------------------------------------------------------------------
// Mobile tab bar
// ---------------------------------------------------------------------------

const TABS: { view: RosterView; labelKey: string }[] = [
  { view: "starters", labelKey: "roster.tabs.starters" },
  { view: "bench", labelKey: "roster.tabs.bench" },
  { view: "ir", labelKey: "roster.tabs.ir" },
];

function MobileTabBar({
  activeView,
  onViewChange,
  t,
}: {
  activeView: RosterView;
  onViewChange: (v: RosterView) => void;
  t: ReturnType<typeof useTranslations>;
}) {
  return (
    <div
      aria-label={t("roster.tabs.label")}
      className="flex border-b border-deep-200 bg-white"
      role="tablist"
    >
      {TABS.map(({ view, labelKey }) => (
        <button
          key={view}
          aria-controls={`panel-${view}`}
          aria-selected={activeView === view}
          className={`flex-1 py-2.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-crimson-400 ${
            activeView === view
              ? "border-b-2 border-crimson-500 text-crimson-700"
              : "text-deep-500 hover:text-deep-800"
          }`}
          role="tab"
          tabIndex={activeView === view ? 0 : -1}
          onClick={() => onViewChange(view)}
        >
          {t(labelKey)}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Loading skeleton
// ---------------------------------------------------------------------------

function RosterSkeleton() {
  return (
    <div className="space-y-3 p-4" aria-busy="true" aria-label="Chargement…">
      {Array.from({ length: 6 }, (_, i) => (
        <div
          key={i}
          className="h-16 animate-pulse rounded-lg bg-deep-100"
          style={{ animationDelay: `${i * 60}ms` }}
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Error state
// ---------------------------------------------------------------------------

function RosterError({
  message,
  onRetry,
  t,
}: {
  message: string;
  onRetry: () => void;
  t: ReturnType<typeof useTranslations>;
}) {
  return (
    <div
      className="flex flex-col items-center gap-4 p-8 text-center"
      role="alert"
    >
      <p className="text-sm text-deep-600">{message}</p>
      <button
        className="rounded-lg bg-crimson-600 px-4 py-2 text-sm font-semibold text-white hover:bg-crimson-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-400"
        onClick={onRetry}
      >
        {t("common.retry")}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function RosterManagement({
  leagueId,
  roundId,
  currentUserId: _currentUserId, // reserved for future read-only mode
}: RosterManagementProps) {
  const t = useTranslations();

  const {
    roster,
    lineup,
    coverage,
    activeView,
    selection,
    isLoading,
    isSaving,
    error,
    setView,
    setSelection,
    updateLineup,
    clearError,
  } = useRoster(leagueId, roundId);

  // ---------------------------------------------------------------------------
  // Derived data — computed once, passed down to children
  // ---------------------------------------------------------------------------

  /**
   * Map player_id → WeeklyLineupEntry for O(1) lookups in child components.
   * Recomputed only when lineup.entries changes.
   */
  const lineupByPlayerId = useMemo(() => {
    if (!lineup) return new Map<string, WeeklyLineupEntry>();
    return new Map<string, WeeklyLineupEntry>(
      lineup.entries.map((e: WeeklyLineupEntry) => [e.player_id, e]),
    );
  }, [lineup]);

  const starterSlots = useMemo(
    () =>
      roster?.slots.filter((s: RosterSlot) => s.slot_type === "starter") ?? [],
    [roster],
  );

  const benchSlots = useMemo(
    () =>
      roster?.slots.filter((s: RosterSlot) => s.slot_type === "bench") ?? [],
    [roster],
  );

  // ---------------------------------------------------------------------------
  // Swap flow
  //
  // Clicking a card sets a selection. Clicking a second card of the
  // opposite type (starter ↔ bench) triggers the swap.
  // Clicking the same card again deselects.
  // ---------------------------------------------------------------------------

  const handleSelect = useCallback(
    (incoming: RosterSelection) => {
      // Deselect if same card clicked twice.
      if (selection?.slot_id === incoming.slot_id) {
        setSelection(null);
        return;
      }

      // No prior selection → just select.
      if (!selection) {
        setSelection(incoming);
        return;
      }

      // Two selections of opposite types → trigger swap.
      const isOpposite =
        (selection.mode === "swap_to_bench" &&
          incoming.mode === "swap_to_starter") ||
        (selection.mode === "swap_to_starter" &&
          incoming.mode === "swap_to_bench");

      if (isOpposite) {
        const payload: LineupUpdatePayload = {
          round_id: roundId,
          captain_player_id: null,
          kicker_player_id: null,
          position_overrides: {},
          slot_swaps: [
            {
              from_slot_id: selection.slot_id,
              to_slot_id: incoming.slot_id,
            },
          ],
        };
        void updateLineup(payload);
        setSelection(null);
        return;
      }

      // Same type clicked (starter → starter or bench → bench) → replace selection.
      setSelection(incoming);
    },
    [selection, setSelection, updateLineup, roundId],
  );

  const handlePositionChange = useCallback(
    (playerId: string, position: PositionType) => {
      const payload: LineupUpdatePayload = {
        round_id: roundId,
        captain_player_id: null,
        kicker_player_id: null,
        position_overrides: { [playerId]: position },
        slot_swaps: [],
      };
      void updateLineup(payload);
    },
    [updateLineup, roundId],
  );

  /**
   * Reintegrate a player from IR back to bench.
   * Calls PUT /ir/reintegrate directly (separate from lineup updates).
   */
  const handleReintegrate = useCallback(
    async (slotId: string, playerId: string) => {
      try {
        const res = await fetch(`${API_BASE}/ir/reintegrate`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ slot_id: slotId, player_id: playerId }),
        });
        if (!res.ok) throw new Error(`Reintegration failed: ${res.status}`);
        // Reload roster data after successful reintegration.
        // A full page reload is acceptable here — IR changes are infrequent.
        window.location.reload();
      } catch (err) {
        console.error("Reintegration error:", err);
      }
    },
    [],
  );

  // ---------------------------------------------------------------------------
  // Render: loading
  // ---------------------------------------------------------------------------

  if (isLoading) return <RosterSkeleton />;

  // ---------------------------------------------------------------------------
  // Render: error
  // ---------------------------------------------------------------------------

  if (error && !roster) {
    return (
      <RosterError
        message={error}
        t={t}
        onRetry={() => window.location.reload()}
      />
    );
  }

  if (!roster || !lineup) return null;

  // ---------------------------------------------------------------------------
  // Render: main
  // ---------------------------------------------------------------------------

  return (
    <div className="flex min-h-0 flex-col">
      {/*
        CaptainKickerBar:
        - Mobile: fixed bottom bar (handled inside the component itself)
        - Desktop: shown here above the grid
      */}
      <div className="hidden sm:block sm:px-4 sm:pt-4">
        <RosterCaptainKickerBar
          benchSlots={benchSlots}
          isSaving={isSaving}
          lineupByPlayerId={lineupByPlayerId}
          roundComplete={lineup.round_complete}
          roundId={roundId}
          starterSlots={starterSlots}
          onUpdate={updateLineup}
        />
      </div>

      {/* Mobile tab bar */}
      <div className="sm:hidden">
        <MobileTabBar activeView={activeView} t={t} onViewChange={setView} />
      </div>

      {/*
        Error toast — shown when save fails but roster is still loaded.
        Appears at the top of the content area.
      */}
      <AnimatePresence>
        {error && roster && (
          <motion.div
            animate={{ opacity: 1, y: 0 }}
            className="mx-4 mt-3 flex items-center justify-between gap-2 rounded-lg border border-red-300 bg-red-50 px-3 py-2"
            exit={{ opacity: 0, y: -4 }}
            initial={{ opacity: 0, y: -4 }}
            role="alert"
            transition={{ duration: 0.2 }}
          >
            <p className="text-xs text-red-700">{error}</p>
            <button
              aria-label={t("common.dismiss")}
              className="shrink-0 text-xs text-red-500 underline"
              onClick={clearError}
            >
              {t("common.dismiss")}
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/*
        Content area.
        Mobile: one panel at a time, animated slide.
        Desktop: 3-column grid, all panels visible.
      */}

      {/* Mobile panels */}
      <div className="flex-1 overflow-y-auto p-4 sm:hidden">
        <AnimatePresence mode="wait">
          {activeView === "starters" && (
            <motion.div
              key="starters"
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -8 }}
              initial={{ opacity: 0, x: 8 }}
              transition={{ duration: 0.15 }}
            >
              <RosterSlotGrid
                isSaving={isSaving}
                lineupByPlayerId={lineupByPlayerId}
                selection={selection}
                slots={roster.slots}
                onPositionChange={handlePositionChange}
                onSelect={handleSelect}
              />
            </motion.div>
          )}

          {activeView === "bench" && (
            <motion.div
              key="bench"
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -8 }}
              initial={{ opacity: 0, x: 8 }}
              transition={{ duration: 0.15 }}
            >
              <RosterBenchGrid
                coverage={coverage}
                isSaving={isSaving}
                lineupByPlayerId={lineupByPlayerId}
                selection={selection}
                slots={roster.slots}
                onPositionChange={handlePositionChange}
                onSelect={handleSelect}
              />
            </motion.div>
          )}

          {activeView === "ir" && (
            <motion.div
              key="ir"
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -8 }}
              initial={{ opacity: 0, x: 8 }}
              transition={{ duration: 0.15 }}
            >
              <RosterIRPanel
                isSaving={isSaving}
                slots={roster.slots}
                onReintegrate={handleReintegrate}
              />
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Desktop: 3-column layout — all panels always visible */}
      <div className="hidden flex-1 gap-6 overflow-y-auto p-4 sm:grid sm:grid-cols-3">
        <RosterSlotGrid
          isSaving={isSaving}
          lineupByPlayerId={lineupByPlayerId}
          selection={selection}
          slots={roster.slots}
          onPositionChange={handlePositionChange}
          onSelect={handleSelect}
        />
        <RosterBenchGrid
          coverage={coverage}
          isSaving={isSaving}
          lineupByPlayerId={lineupByPlayerId}
          selection={selection}
          slots={roster.slots}
          onPositionChange={handlePositionChange}
          onSelect={handleSelect}
        />
        <RosterIRPanel
          isSaving={isSaving}
          slots={roster.slots}
          onReintegrate={handleReintegrate}
        />
      </div>

      {/* Mobile CaptainKickerBar — rendered inside its own component as fixed */}
      <div className="sm:hidden">
        <RosterCaptainKickerBar
          benchSlots={benchSlots}
          isSaving={isSaving}
          lineupByPlayerId={lineupByPlayerId}
          roundComplete={lineup.round_complete}
          roundId={roundId}
          starterSlots={starterSlots}
          onUpdate={updateLineup}
        />
      </div>
    </div>
  );
}
