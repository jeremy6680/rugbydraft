/**
 * RosterPlayerCard — single player card for the roster management page.
 *
 * Displays player info, availability status, role badges (captain/kicker),
 * lock indicator, and handles selection for lineup actions.
 *
 * Used in: RosterSlotGrid (starters), RosterBenchGrid (bench), RosterIRPanel (IR).
 *
 * CDC references:
 * - §6.3: Multi-position selector (locked at kick-off)
 * - §6.4: IR players — non-interactive, no points
 * - §6.5: Captain (×1.5) and kicker designations
 * - §6.6: Progressive lock per player
 */

"use client";

import { useTranslations } from "next-intl";
import { motion } from "framer-motion";
import type {
  RosterSlot,
  WeeklyLineupEntry,
  RosterSelection,
  PositionType,
} from "@/types/roster";
import { POSITION_LABELS } from "@/types/roster";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface RosterPlayerCardProps {
  /** The roster slot (player + slot metadata). */
  slot: RosterSlot;
  /**
   * The lineup entry for this player this round.
   * Null if no lineup has been set yet (e.g. first round, round not started).
   */
  lineupEntry: WeeklyLineupEntry | null;
  /** Whether this card is currently selected for an action. */
  isSelected: boolean;
  /** Whether any save is in progress (disables all interactions). */
  isSaving: boolean;
  /**
   * Callback when the card is clicked for a lineup action.
   * Not called when the card is locked or IR.
   */
  onSelect: (selection: RosterSelection) => void;
  /**
   * Callback when the user changes the active position for a multi-position player.
   * Only available when player.positions.length > 1 and not locked.
   */
  onPositionChange: (playerId: string, position: PositionType) => void;
  /** Whether to show the compact version (used in DraftOrderPanel-style lists). */
  compact?: boolean;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Availability status badge — coloured pill. */
function AvailabilityBadge({
  status,
  t,
}: {
  status: RosterSlot["availability_status"];
  t: ReturnType<typeof useTranslations>;
}) {
  if (status === "available") return null;

  const styles: Record<string, string> = {
    injured: "bg-red-100 text-red-700 border border-red-200",
    suspended: "bg-orange-100 text-orange-700 border border-orange-200",
    doubtful: "bg-yellow-100 text-yellow-700 border border-yellow-200",
  };

  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${styles[status] ?? ""}`}
    >
      {t(`roster.availability.${status}`)}
    </span>
  );
}

/** Lock indicator — shown when the player's match has kicked off. */
function LockIndicator() {
  return (
    <span
      aria-label="Verrouillé"
      className="inline-flex items-center justify-center text-sm"
      role="img"
    >
      🔒
    </span>
  );
}

/** Captain badge. */
function CaptainBadge() {
  return (
    <span
      aria-label="Capitaine"
      className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-crimson-600 text-xs font-bold text-white"
    >
      C
    </span>
  );
}

/** Kicker badge. */
function KickerBadge() {
  return (
    <span
      aria-label="Botteur"
      className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-lime-500 text-xs font-bold text-deep-900"
    >
      B
    </span>
  );
}

/**
 * Position selector for multi-position players.
 * Only rendered when the player can play multiple positions AND is not locked.
 */
function MultiPositionSelector({
  playerId,
  positions,
  activePosition,
  onChange,
  t,
}: {
  playerId: string;
  positions: PositionType[];
  activePosition: PositionType;
  onChange: (playerId: string, pos: PositionType) => void;
  t: ReturnType<typeof useTranslations>;
}) {
  return (
    <select
      aria-label={t("roster.multiPosition.label")}
      className="mt-1 w-full rounded border border-deep-200 bg-white px-2 py-1 text-xs text-deep-700 focus:outline-none focus:ring-2 focus:ring-crimson-400"
      value={activePosition}
      onClick={(e) => e.stopPropagation()} // Prevent card selection when clicking select
      onChange={(e) => onChange(playerId, e.target.value as PositionType)}
    >
      {positions.map((pos) => (
        <option key={pos} value={pos}>
          {POSITION_LABELS[pos]}
        </option>
      ))}
    </select>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function RosterPlayerCard({
  slot,
  lineupEntry,
  isSelected,
  isSaving,
  onSelect,
  onPositionChange,
  compact = false,
}: RosterPlayerCardProps) {
  const t = useTranslations();

  const { player, slot_type, availability_status } = slot;
  const isIR = slot_type === "ir";
  const isLocked = lineupEntry?.is_locked ?? false;
  const isCaptain = lineupEntry?.is_captain ?? false;
  const isKicker = lineupEntry?.is_kicker ?? false;
  const isInteractive = !isIR && !isSaving;

  // The active position: lineup override if set, else first natural position.
  const activePosition: PositionType =
    (lineupEntry?.position as PositionType | undefined) ??
    (player.positions[0] as PositionType);

  const isMultiPosition = player.positions.length > 1;

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  function handleCardClick() {
    if (!isInteractive) return;

    // Determine what action this click initiates.
    // The parent (RosterManagement) decides what to do with the selection.
    onSelect({
      player_id: player.id,
      slot_id: slot.id,
      // Default mode: swap. Captain/kicker are set via the dedicated bar.
      mode: slot_type === "starter" ? "swap_to_bench" : "swap_to_starter",
    });
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      handleCardClick();
    }
  }

  // ---------------------------------------------------------------------------
  // Style computation
  // ---------------------------------------------------------------------------

  const cardBase =
    "relative flex flex-col gap-1 rounded-lg border p-3 transition-all duration-150";

  const cardVariant = isIR
    ? "border-deep-200 bg-deep-50 opacity-60 cursor-default"
    : isSelected
      ? "border-crimson-500 bg-rose-50 shadow-md cursor-pointer"
      : availability_status !== "available"
        ? "border-deep-200 bg-white cursor-pointer opacity-80"
        : "border-deep-200 bg-white hover:border-crimson-300 hover:shadow-sm cursor-pointer";

  const cardClass = `${cardBase} ${cardVariant} ${compact ? "py-2" : ""}`;

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <motion.div
      animate={{ opacity: 1, y: 0 }}
      aria-disabled={isIR || isSaving}
      aria-label={`${player.first_name} ${player.last_name}${isCaptain ? ", capitaine" : ""}${isKicker ? ", botteur" : ""}${isLocked ? ", verrouillé" : ""}`}
      aria-pressed={isSelected}
      className={cardClass}
      initial={{ opacity: 0, y: 4 }}
      role={isInteractive ? "button" : "listitem"}
      tabIndex={isInteractive ? 0 : -1}
      transition={{ duration: 0.15 }}
      onClick={handleCardClick}
      onKeyDown={handleKeyDown}
    >
      {/* Top row: name + badges */}
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-semibold text-deep-900">
          {player.first_name} {player.last_name}
        </span>

        {/* Role + lock badges — right aligned */}
        <div className="flex shrink-0 items-center gap-1">
          {isCaptain && <CaptainBadge />}
          {isKicker && <KickerBadge />}
          {isLocked && <LockIndicator />}
        </div>
      </div>

      {/* Bottom row: position + club + availability */}
      {!compact && (
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-deep-500">
              {POSITION_LABELS[activePosition]}
            </span>
            {player.club && (
              <>
                <span className="text-deep-300">·</span>
                <span className="truncate text-xs text-deep-400">
                  {player.club}
                </span>
              </>
            )}
          </div>

          <AvailabilityBadge status={availability_status} t={t} />
        </div>
      )}

      {/* Multi-position selector — only for multi-position players, not locked */}
      {isMultiPosition && !isLocked && !isIR && (
        <MultiPositionSelector
          activePosition={activePosition}
          playerId={player.id}
          positions={player.positions as PositionType[]}
          t={t}
          onChange={onPositionChange}
        />
      )}

      {/* Selected indicator — left border accent */}
      {isSelected && (
        <span
          aria-hidden="true"
          className="absolute inset-y-0 left-0 w-1 rounded-l-lg bg-crimson-500"
        />
      )}
    </motion.div>
  );
}
