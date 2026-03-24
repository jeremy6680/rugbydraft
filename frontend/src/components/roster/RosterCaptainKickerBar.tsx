/**
 * RosterCaptainKickerBar — captain and kicker designation UI.
 *
 * Displays current captain and kicker, with buttons to change them.
 * Lock status is enforced: cannot change if the player's match has kicked off.
 *
 * On mobile: sticky bar at the bottom of the roster view (above BottomNav).
 * On desktop: inline section above the starter grid.
 *
 * CDC §6.5:
 * - Captain: ×1.5 multiplier (rounded up to nearest 0.5). Must be a starter.
 * - Kicker: only kicker scores on penalties and conversions.
 * CDC §6.6:
 * - Captain cannot be changed after their team's kick-off.
 * - Kicker cannot be changed after their match this round.
 */

"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { motion, AnimatePresence } from "framer-motion";
import type {
  RosterSlot,
  WeeklyLineupEntry,
  LineupUpdatePayload,
  PositionType,
} from "@/types/roster";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface RosterCaptainKickerBarProps {
  /** Starter slots only — captain must be a starter. */
  starterSlots: RosterSlot[];
  /** All bench slots — kicker can be starter or bench. */
  benchSlots: RosterSlot[];
  /** Lineup entries keyed by player_id. */
  lineupByPlayerId: Map<string, WeeklyLineupEntry>;
  /** Whether any save is in progress. */
  isSaving: boolean;
  /** Whether the entire round is complete (all matches played). */
  roundComplete: boolean;
  /**
   * Callback to submit a lineup update.
   * We only send captain_player_id or kicker_player_id — other fields
   * are kept as-is by sending null for slot_swaps and empty overrides.
   */
  onUpdate: (payload: LineupUpdatePayload) => Promise<void>;
  /** Current round ID — required for the payload. */
  roundId: string;
}

// ---------------------------------------------------------------------------
// Helper: build a minimal LineupUpdatePayload for captain/kicker only
// ---------------------------------------------------------------------------

function buildSingleFieldPayload(
  roundId: string,
  field: "captain" | "kicker",
  playerId: string | null,
): LineupUpdatePayload {
  return {
    round_id: roundId,
    captain_player_id: field === "captain" ? playerId : undefined!,
    kicker_player_id: field === "kicker" ? playerId : undefined!,
    position_overrides: {},
    slot_swaps: [],
  };
}

// ---------------------------------------------------------------------------
// Player picker modal — full-screen on mobile, popover on desktop
// ---------------------------------------------------------------------------

interface PlayerPickerProps {
  title: string;
  slots: RosterSlot[];
  lineupByPlayerId: Map<string, WeeklyLineupEntry>;
  currentPlayerId: string | null;
  /** If true, only unlocked players are selectable. */
  onSelect: (playerId: string) => void;
  onClose: () => void;
}

function PlayerPicker({
  title,
  slots,
  lineupByPlayerId,
  currentPlayerId,
  onSelect,
  onClose,
}: PlayerPickerProps) {
  const t = useTranslations();

  return (
    <>
      {/* Backdrop */}
      <motion.div
        animate={{ opacity: 1 }}
        aria-hidden="true"
        className="fixed inset-0 z-40 bg-deep-900/60"
        initial={{ opacity: 0 }}
        transition={{ duration: 0.15 }}
        onClick={onClose}
      />

      {/* Panel — slides up from bottom on mobile */}
      <motion.div
        animate={{ y: 0 }}
        aria-label={title}
        aria-modal="true"
        className="fixed bottom-0 left-0 right-0 z-50 max-h-[70vh] overflow-y-auto rounded-t-2xl bg-white p-4 shadow-2xl sm:bottom-auto sm:left-1/2 sm:top-1/2 sm:w-96 sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-2xl"
        initial={{ y: "100%" }}
        role="dialog"
        transition={{ type: "spring", damping: 30, stiffness: 300 }}
        onKeyDown={(e) => e.key === "Escape" && onClose()}
      >
        {/* Header */}
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-deep-900">{title}</h3>
          <button
            aria-label={t("common.close")}
            className="rounded-lg p-1 text-deep-400 hover:bg-deep-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-400"
            onClick={onClose}
          >
            ✕
          </button>
        </div>

        {/* Player list */}
        <ul className="space-y-1" role="listbox">
          {slots.map((slot) => {
            const entry = lineupByPlayerId.get(slot.player.id);
            const isLocked = entry?.is_locked ?? false;
            const isCurrent = slot.player.id === currentPlayerId;

            return (
              <li key={slot.id} role="option" aria-selected={isCurrent}>
                <button
                  aria-disabled={isLocked}
                  className={`flex w-full items-center justify-between rounded-lg px-3 py-2.5 text-left text-sm transition-colors ${
                    isCurrent
                      ? "bg-crimson-50 font-semibold text-crimson-700"
                      : isLocked
                        ? "cursor-not-allowed opacity-40"
                        : "hover:bg-deep-50 text-deep-800"
                  }`}
                  disabled={isLocked}
                  onClick={() => {
                    if (!isLocked) {
                      onSelect(slot.player.id);
                      onClose();
                    }
                  }}
                >
                  <span>
                    {slot.player.first_name} {slot.player.last_name}
                  </span>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-deep-400">
                      {slot.player.club}
                    </span>
                    {isLocked && (
                      <span aria-label={t("roster.locked")} role="img">
                        🔒
                      </span>
                    )}
                    {isCurrent && (
                      <span aria-label={t("roster.current")} role="img">
                        ✓
                      </span>
                    )}
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      </motion.div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Single designation card — used for both captain and kicker
// ---------------------------------------------------------------------------

interface DesignationCardProps {
  label: string;
  description: string;
  playerName: string | null;
  playerClub: string | null;
  isLocked: boolean;
  isDisabled: boolean;
  accentClass: string;
  badgeLabel: string;
  onChangClick: () => void;
  t: ReturnType<typeof useTranslations>;
}

function DesignationCard({
  label,
  description,
  playerName,
  playerClub,
  isLocked,
  isDisabled,
  accentClass,
  badgeLabel,
  onChangClick,
  t,
}: DesignationCardProps) {
  return (
    <div
      className={`flex flex-1 items-center justify-between gap-3 rounded-xl border p-3 ${accentClass}`}
    >
      <div className="min-w-0">
        {/* Role label + badge */}
        <div className="mb-0.5 flex items-center gap-1.5">
          <span className="text-xs font-bold uppercase tracking-wide opacity-70">
            {label}
          </span>
          <span className="rounded bg-white/50 px-1 text-xs font-bold">
            {badgeLabel}
          </span>
        </div>

        {/* Current player */}
        {playerName ? (
          <div>
            <p className="truncate text-sm font-semibold">{playerName}</p>
            {playerClub && (
              <p className="truncate text-xs opacity-60">{playerClub}</p>
            )}
          </div>
        ) : (
          <p className="text-xs opacity-60">{t("roster.designation.none")}</p>
        )}

        {/* Lock message */}
        {isLocked && (
          <p className="mt-0.5 text-xs opacity-70">
            🔒 {t("roster.designation.locked")}
          </p>
        )}
      </div>

      {/* Change button */}
      <button
        aria-label={`${t("roster.designation.change")} ${label.toLowerCase()}`}
        className="shrink-0 rounded-lg bg-white/80 px-3 py-1.5 text-xs font-semibold transition-colors hover:bg-white disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/50"
        disabled={isDisabled || isLocked}
        onClick={onChangClick}
      >
        {t("roster.designation.change")}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function RosterCaptainKickerBar({
  starterSlots,
  benchSlots,
  lineupByPlayerId,
  isSaving,
  roundComplete,
  onUpdate,
  roundId,
}: RosterCaptainKickerBarProps) {
  const t = useTranslations();

  // Which picker is open: "captain", "kicker", or null.
  const [pickerOpen, setPickerOpen] = useState<"captain" | "kicker" | null>(
    null,
  );

  // ---------------------------------------------------------------------------
  // Derive current captain and kicker from lineup entries
  // ---------------------------------------------------------------------------

  const captainEntry = [...lineupByPlayerId.values()].find((e) => e.is_captain);
  const kickerEntry = [...lineupByPlayerId.values()].find((e) => e.is_kicker);

  const captainSlot = captainEntry
    ? starterSlots.find((s) => s.player.id === captainEntry.player_id)
    : null;

  // Kicker can be starter or bench.
  const allSlots = [...starterSlots, ...benchSlots];
  const kickerSlot = kickerEntry
    ? allSlots.find((s) => s.player.id === kickerEntry.player_id)
    : null;

  const isCaptainLocked = captainEntry?.is_locked ?? false;
  const isKickerLocked = kickerEntry?.is_locked ?? false;
  const isDisabled = isSaving || roundComplete;

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  async function handleCaptainSelect(playerId: string) {
    await onUpdate(buildSingleFieldPayload(roundId, "captain", playerId));
  }

  async function handleKickerSelect(playerId: string) {
    await onUpdate(buildSingleFieldPayload(roundId, "kicker", playerId));
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <>
      {/*
        On mobile: sticky bar above BottomNav (bottom-16 = 4rem = height of BottomNav).
        On desktop: static inline section.
        The `sm:relative sm:bottom-auto` resets the sticky positioning on desktop.
      */}
      <div
        aria-label={t("roster.captainKicker.title")}
        className="fixed bottom-16 left-0 right-0 z-30 border-t border-deep-200 bg-white/95 px-3 py-2 backdrop-blur-sm sm:relative sm:bottom-auto sm:left-auto sm:right-auto sm:z-auto sm:border-0 sm:bg-transparent sm:p-0 sm:backdrop-blur-none"
      >
        {/* Label — desktop only */}
        <p className="mb-2 hidden text-xs font-semibold uppercase tracking-wide text-deep-500 sm:block">
          {t("roster.captainKicker.title")}
        </p>

        {/* Two cards side by side */}
        <div className="flex gap-2">
          {/* Captain card — crimson theme */}
          <DesignationCard
            accentClass="border-crimson-200 bg-crimson-50 text-crimson-900"
            badgeLabel="×1.5"
            description={t("roster.captain.description")}
            isDisabled={isDisabled}
            isLocked={isCaptainLocked}
            label={t("roster.captain.label")}
            playerClub={captainSlot?.player.club ?? null}
            playerName={
              captainSlot
                ? `${captainSlot.player.first_name} ${captainSlot.player.last_name}`
                : null
            }
            t={t}
            onChangClick={() => setPickerOpen("captain")}
          />

          {/* Kicker card — lime theme */}
          <DesignationCard
            accentClass="border-lime-300 bg-lime-50 text-lime-900"
            badgeLabel="PEN/TRF"
            description={t("roster.kicker.description")}
            isDisabled={isDisabled}
            isLocked={isKickerLocked}
            label={t("roster.kicker.label")}
            playerClub={kickerSlot?.player.club ?? null}
            playerName={
              kickerSlot
                ? `${kickerSlot.player.first_name} ${kickerSlot.player.last_name}`
                : null
            }
            t={t}
            onChangClick={() => setPickerOpen("kicker")}
          />
        </div>
      </div>

      {/* Captain picker */}
      <AnimatePresence>
        {pickerOpen === "captain" && (
          <PlayerPicker
            currentPlayerId={captainEntry?.player_id ?? null}
            lineupByPlayerId={lineupByPlayerId}
            slots={starterSlots} // Captain must be a starter
            title={t("roster.captain.pickerTitle")}
            onClose={() => setPickerOpen(null)}
            onSelect={handleCaptainSelect}
          />
        )}
      </AnimatePresence>

      {/* Kicker picker */}
      <AnimatePresence>
        {pickerOpen === "kicker" && (
          <PlayerPicker
            currentPlayerId={kickerEntry?.player_id ?? null}
            lineupByPlayerId={lineupByPlayerId}
            slots={allSlots} // Kicker can be starter or bench
            title={t("roster.kicker.pickerTitle")}
            onClose={() => setPickerOpen(null)}
            onSelect={handleKickerSelect}
          />
        )}
      </AnimatePresence>
    </>
  );
}
