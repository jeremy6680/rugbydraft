/**
 * RosterIRPanel — displays IR slots (infirmary).
 *
 * CDC §6.4:
 * - Max 3 players in IR simultaneously.
 * - IR players score no points and don't count for coverage.
 * - Manager has 1 week to reintegrate a recovered player.
 * - After 1 week without action: waivers and trades are blocked.
 *
 * Reintegration action is separate from lineup updates —
 * it calls PUT /ir/reintegrate (backend/app/routers/infirmary.py).
 */

"use client";

import { useTranslations } from "next-intl";
import { motion, AnimatePresence } from "framer-motion";
import type { RosterSlot } from "@/types/roster";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** IR capacity per CDC §6.4. */
const IR_CAPACITY = 3;

/**
 * After this many days without reintegrating a recovered player,
 * waivers and trades are blocked (CDC §6.4).
 */
const IR_REINTEGRATION_DEADLINE_DAYS = 7;

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface RosterIRPanelProps {
  /** All roster slots — filtered to IR only inside this component. */
  slots: RosterSlot[];
  /**
   * Whether any save is currently in progress.
   * Disables reintegration buttons while saving.
   */
  isSaving: boolean;
  /**
   * Callback to reintegrate a player from IR back to bench.
   * Calls PUT /ir/reintegrate via the parent.
   */
  onReintegrate: (slotId: string, playerId: string) => void;
}

// ---------------------------------------------------------------------------
// IR player card — simplified, non-interactive for lineup
// ---------------------------------------------------------------------------

function IRPlayerCard({
  slot,
  isSaving,
  onReintegrate,
}: {
  slot: RosterSlot;
  isSaving: boolean;
  onReintegrate: (slotId: string, playerId: string) => void;
}) {
  const t = useTranslations();
  const { player, availability_status } = slot;

  // Determine if this player has been in IR long enough to block waivers.
  // In a real implementation, the backend would send a `recovered_at` field.
  // For now we flag visually based on availability_status === "available"
  // (meaning the player recovered but is still in IR — needs reintegration).
  const isRecovered = availability_status === "available";

  return (
    <motion.div
      animate={{ opacity: 1, x: 0 }}
      className={`flex items-center justify-between gap-3 rounded-lg border p-3 ${
        isRecovered ? "border-red-300 bg-red-50" : "border-deep-200 bg-deep-50"
      }`}
      exit={{ opacity: 0, x: -8 }}
      initial={{ opacity: 0, x: -8 }}
      transition={{ duration: 0.2 }}
    >
      {/* Left: player info */}
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold text-deep-900">
          {player.first_name} {player.last_name}
        </p>
        <div className="mt-0.5 flex items-center gap-1.5">
          <span className="text-xs text-deep-400">{player.club}</span>
          {/* Recovered alert */}
          {isRecovered && (
            <span className="rounded-full bg-red-100 px-1.5 py-0.5 text-xs font-medium text-red-700">
              {t("roster.ir.recovered")}
            </span>
          )}
          {/* Still injured/suspended */}
          {!isRecovered && (
            <span className="rounded-full bg-orange-100 px-1.5 py-0.5 text-xs font-medium text-orange-700">
              {t(`roster.availability.${availability_status}`)}
            </span>
          )}
        </div>
      </div>

      {/* Right: reintegrate button */}
      <button
        aria-label={t("roster.ir.reintegrate.label", {
          name: `${player.first_name} ${player.last_name}`,
        })}
        className="shrink-0 rounded-lg bg-crimson-600 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-crimson-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-crimson-400 disabled:cursor-not-allowed disabled:opacity-50"
        disabled={isSaving}
        onClick={() => onReintegrate(slot.id, player.id)}
      >
        {t("roster.ir.reintegrate.action")}
      </button>
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// Empty IR slot — shown when IR has fewer than 3 players
// ---------------------------------------------------------------------------

function EmptyIRSlot({ index }: { index: number }) {
  const t = useTranslations();
  return (
    <div
      aria-label={t("roster.ir.empty")}
      className="flex items-center justify-center rounded-lg border border-dashed border-deep-200 bg-deep-50 p-3 text-xs text-deep-400"
    >
      {t("roster.ir.slot", { number: index + 1 })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function RosterIRPanel({
  slots,
  isSaving,
  onReintegrate,
}: RosterIRPanelProps) {
  const t = useTranslations();

  const irSlots = slots.filter((s) => s.slot_type === "ir");
  const emptySlotCount = IR_CAPACITY - irSlots.length;

  // Alert: at least one recovered player not yet reintegrated.
  const hasRecoveredBlocking = irSlots.some(
    (s) => s.availability_status === "available",
  );

  return (
    <section aria-label={t("roster.ir.title")}>
      {/* Section header */}
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-deep-500">
          {t("roster.ir.title")}
        </h2>
        <span className="text-xs text-deep-400">
          {irSlots.length}/{IR_CAPACITY}
        </span>
      </div>

      {/* Blocking alert — waivers and trades are frozen */}
      {hasRecoveredBlocking && (
        <motion.div
          animate={{ opacity: 1, y: 0 }}
          className="mb-3 flex items-start gap-2 rounded-lg border border-red-300 bg-red-50 p-3"
          initial={{ opacity: 0, y: -4 }}
          role="alert"
          transition={{ duration: 0.2 }}
        >
          <span aria-hidden="true" className="mt-0.5 shrink-0 text-sm">
            ⚠️
          </span>
          <p className="text-xs text-red-700">{t("roster.ir.blockingAlert")}</p>
        </motion.div>
      )}

      {/* IR slots */}
      <div className="space-y-2">
        <AnimatePresence>
          {irSlots.map((slot) => (
            <IRPlayerCard
              key={slot.id}
              isSaving={isSaving}
              slot={slot}
              onReintegrate={onReintegrate}
            />
          ))}
        </AnimatePresence>

        {/* Empty slots — fill up to IR_CAPACITY */}
        {Array.from({ length: emptySlotCount }, (_, i) => (
          <EmptyIRSlot key={`empty-${i}`} index={irSlots.length + i} />
        ))}
      </div>

      {/* Info note about IR rules */}
      <p className="mt-3 text-xs text-deep-400">
        {t("roster.ir.rulesNote", {
          deadline: IR_REINTEGRATION_DEADLINE_DAYS,
        })}
      </p>
    </section>
  );
}
