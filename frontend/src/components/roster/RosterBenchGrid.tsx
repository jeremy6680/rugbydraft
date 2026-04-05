/**
 * RosterBenchGrid — displays the 15 bench slots with coverage indicators.
 *
 * Layout:
 * - Mobile: list + coverage bar below
 * - Desktop: 3-column grid + coverage bar below
 *
 * CDC §6.2: minimum bench coverage constraints per position.
 * The coverage bar is computed frontend-side (useRoster hook) and
 * validated backend-side on save.
 */

"use client";

import { useTranslations } from "next-intl";
import { RosterPlayerCard } from "./RosterPlayerCard";
import { POSITION_LABELS } from "@/types/roster";
import type {
  RosterSlot,
  WeeklyLineupEntry,
  RosterSelection,
  RosterCoverageStatus,
  PositionType,
} from "@/types/roster";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface RosterBenchGridProps {
  /** All roster slots — filtered to bench only inside this component. */
  slots: RosterSlot[];
  /** Lineup entries for the current round, keyed by player_id. */
  lineupByPlayerId: Map<string, WeeklyLineupEntry>;
  /** Coverage status computed by useRoster. */
  coverage: RosterCoverageStatus | null;
  /** Currently selected slot. */
  selection: RosterSelection | null;
  /** Whether any save is in progress. */
  isSaving: boolean;
  /** Callback when a card is clicked. */
  onSelect: (selection: RosterSelection) => void;
  /** Callback when a multi-position player changes their active position. */
  onPositionChange: (playerId: string, position: PositionType) => void;
}

// ---------------------------------------------------------------------------
// Coverage bar — one badge per required position
// ---------------------------------------------------------------------------

function CoverageBadge({
  position,
  current,
  required,
  isCovered,
}: {
  position: PositionType;
  current: number;
  required: number;
  isCovered: boolean;
}) {
  return (
    <div
      aria-label={`${POSITION_LABELS[position]}: ${current}/${required}`}
      className={`flex flex-col items-center gap-0.5 rounded-lg border px-2 py-1.5 text-center transition-colors ${
        isCovered
          ? "border-lime-300 bg-lime-50 text-lime-700"
          : "border-red-300 bg-red-50 text-red-700"
      }`}
      role="status"
      title={`${POSITION_LABELS[position]}: ${current}/${required}`}
    >
      {/* Count fraction */}
      <span className="text-sm font-bold leading-none">
        {current}/{required}
      </span>
      {/* Abbreviated position label */}
      <span className="text-xs leading-none opacity-80">
        {POSITION_LABELS[position].split(" ")[0]}
      </span>
      {/* Covered / uncovered icon */}
      <span aria-hidden="true" className="text-xs">
        {isCovered ? "✓" : "✗"}
      </span>
    </div>
  );
}

function CoverageBar({ coverage }: { coverage: RosterCoverageStatus }) {
  const t = useTranslations();

  return (
    <div className="mt-4 rounded-xl border border-deep-200 bg-deep-50 p-3">
      {/* Header */}
      <div className="mb-2 flex items-center justify-between">
        <p className="text-xs font-semibold uppercase tracking-wide text-deep-500">
          {t("roster.coverage.title")}
        </p>
        {coverage.all_covered ? (
          <span className="rounded-full bg-lime-100 px-2 py-0.5 text-xs font-medium text-lime-700">
            {t("roster.coverage.ok")}
          </span>
        ) : (
          <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
            {t("roster.coverage.uncovered", {
              count: coverage.uncovered_count,
            })}
          </span>
        )}
      </div>

      {/* Badge grid — wraps on mobile */}
      <div
        aria-label={t("roster.coverage.detail")}
        className="flex flex-wrap gap-2"
        role="list"
      >
        {coverage.positions.map((pos) => (
          <div key={pos.position} role="listitem">
            <CoverageBadge
              current={pos.current_count}
              isCovered={pos.is_covered}
              position={pos.position}
              required={pos.required}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function RosterBenchGrid({
  slots,
  lineupByPlayerId,
  coverage,
  selection,
  isSaving,
  onSelect,
  onPositionChange,
}: RosterBenchGridProps) {
  const t = useTranslations();

  const benchSlots = slots
    .filter((s) => s.slot_type === "bench")
    // Sort by slot_index — bench slots 1–15.
    .sort((a, b) => (a.slot_index ?? 0) - (b.slot_index ?? 0));

  return (
    <section aria-label={t("roster.bench.title")}>
      {/* Section header */}
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-deep-500">
          {t("roster.bench.title")}
        </h2>
        <span className="text-xs text-deep-400">{benchSlots.length}/15</span>
      </div>

      {/* Bench grid — 1 col mobile, 2–3 col desktop */}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {benchSlots.map((slot) => {
          const lineupEntry = lineupByPlayerId.get(slot.player.id) ?? null;

          return (
            <RosterPlayerCard
              key={slot.id}
              isSaving={isSaving}
              isSelected={selection?.slot_id === slot.id}
              lineupEntry={lineupEntry}
              slot={slot}
              onPositionChange={onPositionChange}
              onSelect={onSelect}
            />
          );
        })}
      </div>

      {/* Coverage bar — always rendered, even when coverage is null (loading) */}
      {coverage ? (
        <CoverageBar coverage={coverage} />
      ) : (
        <div className="mt-4 h-20 animate-pulse rounded-xl bg-deep-100" />
      )}
    </section>
  );
}
