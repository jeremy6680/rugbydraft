/**
 * RosterSlotGrid — displays the 15 starter slots in jersey number order.
 *
 * Layout:
 * - Mobile: single column list
 * - Desktop: 3-column grid grouped by forward / halfback / back lines
 *
 * CDC §6.1: 15 fixed starter positions.
 * CDC §6.5: Only starters score points.
 */

"use client";

import { useTranslations } from "next-intl";
import { RosterPlayerCard } from "./RosterPlayerCard";
import { STARTER_POSITIONS } from "@/types/roster";
import type {
  RosterSlot,
  WeeklyLineupEntry,
  RosterSelection,
  PositionType,
} from "@/types/roster";

// ---------------------------------------------------------------------------
// Position group labels — used as section headers on desktop
// Jersey numbers: forwards 1–8, halfbacks 9–10, backs 11–15
// ---------------------------------------------------------------------------

const POSITION_GROUPS = [
  { label: "Avants", jerseyRange: [1, 8] as [number, number] },
  { label: "Demis", jerseyRange: [9, 10] as [number, number] },
  { label: "Trois-quarts", jerseyRange: [11, 15] as [number, number] },
] as const;

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface RosterSlotGridProps {
  /** All roster slots — filtered to starters only inside this component. */
  slots: RosterSlot[];
  /** Lineup entries for the current round, keyed by player_id. */
  lineupByPlayerId: Map<string, WeeklyLineupEntry>;
  /** Currently selected slot (for swap / captain / kicker flow). */
  selection: RosterSelection | null;
  /** Whether any save is in progress. */
  isSaving: boolean;
  /** Callback when a card is clicked. */
  onSelect: (selection: RosterSelection) => void;
  /** Callback when a multi-position player changes their active position. */
  onPositionChange: (playerId: string, position: PositionType) => void;
}

// ---------------------------------------------------------------------------
// Empty slot placeholder
// Shown when a starter slot has no player — defensive, post-draft this
// should not occur, but avoids crashes if data is incomplete.
// ---------------------------------------------------------------------------

function EmptySlot({ jerseyNumber }: { jerseyNumber: number }) {
  const t = useTranslations();
  return (
    <div
      aria-label={t("roster.slot.empty", { number: jerseyNumber })}
      className="flex items-center justify-center rounded-lg border border-dashed border-deep-200 bg-deep-50 p-3 text-xs text-deep-400"
    >
      #{jerseyNumber} — {t("roster.slot.vacant")}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function RosterSlotGrid({
  slots,
  lineupByPlayerId,
  selection,
  isSaving,
  onSelect,
  onPositionChange,
}: RosterSlotGridProps) {
  const t = useTranslations();

  // Build an ordered array of starter slots indexed by slot_index (1-based).
  // slot_index matches jersey number for starters.
  const starterSlots = slots.filter((s) => s.slot_type === "starter");

  // Map slot_index → RosterSlot for O(1) lookup when rendering.
  const slotByIndex = new Map<number, RosterSlot>(
    starterSlots.map((s) => [s.slot_index ?? 0, s]),
  );

  return (
    <section aria-label={t("roster.starters.title")}>
      {/* Section header */}
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-deep-500">
          {t("roster.starters.title")}
        </h2>
        <span className="text-xs text-deep-400">{starterSlots.length}/15</span>
      </div>

      {/* 
        Desktop: 3-column grid grouped by position line.
        Mobile: single column — groups shown as labelled sections.
      */}
      <div className="space-y-4">
        {POSITION_GROUPS.map(({ label, jerseyRange }) => {
          const [from, to] = jerseyRange;
          // Jersey numbers in this group, 1-based.
          const jerseyNumbers = Array.from(
            { length: to - from + 1 },
            (_, i) => from + i,
          );

          return (
            <div key={label}>
              {/* Group label */}
              <p className="mb-2 text-xs font-medium text-deep-400">{label}</p>

              {/* 
                Mobile: 1 column.
                Desktop: 2 or 3 columns depending on group size.
                - Avants (8 players): 4 cols on lg, 2 on md
                - Demis (2 players): 2 cols
                - Backs (5 players): 3 cols on lg, 2 on md  
              */}
              <div
                className={
                  jerseyNumbers.length >= 5
                    ? "grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3"
                    : "grid grid-cols-1 gap-2 sm:grid-cols-2"
                }
              >
                {jerseyNumbers.map((jersey) => {
                  const slot = slotByIndex.get(jersey);

                  if (!slot) {
                    return <EmptySlot key={jersey} jerseyNumber={jersey} />;
                  }

                  const lineupEntry =
                    lineupByPlayerId.get(slot.player.id) ?? null;

                  return (
                    <div key={slot.id} className="relative">
                      {/* Jersey number label — small, top-left corner */}
                      <span
                        aria-hidden="true"
                        className="absolute -left-0.5 -top-0.5 z-10 flex h-5 w-5 items-center justify-center rounded-br-md rounded-tl-lg bg-deep-100 text-xs font-bold text-deep-500"
                      >
                        {jersey}
                      </span>

                      <RosterPlayerCard
                        isSaving={isSaving}
                        isSelected={selection?.slot_id === slot.id}
                        lineupEntry={lineupEntry}
                        slot={slot}
                        onPositionChange={onPositionChange}
                        onSelect={onSelect}
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
