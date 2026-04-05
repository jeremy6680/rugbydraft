// frontend/src/components/draft/DraftPickConfirmModal.tsx
/**
 * DraftPickConfirmModal — confirmation dialog before submitting a pick.
 *
 * Opened by DraftRoom when the user clicks a player card.
 * Closed by DraftRoom on confirm (success) or user cancellation.
 *
 * Responsibilities:
 *   - Show the selected player's details
 *   - Show remaining time so the user can assess urgency
 *   - Call onConfirm() when the user validates — parent handles the HTTP call
 *   - Show a loading state while the pick is being submitted
 *   - Trap focus inside the modal (WCAG 2.1 — 2.4.3 Focus Order)
 *
 * Architecture note:
 *   This component does NOT call the FastAPI endpoint directly.
 *   The parent (DraftRoom) owns the fetch logic and passes isSubmitting
 *   as a prop so this component can show a loading state.
 */

"use client";

import { useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useTranslations } from "next-intl";
import { X } from "lucide-react";
import type { PlayerSummary, PositionType } from "@/types/player";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface DraftPickConfirmModalProps {
  /** The player the user wants to pick. null = modal is closed. */
  player: PlayerSummary | null;
  /** Seconds remaining on the timer — shown for urgency context. */
  timeRemaining: number;
  /** True while the pick HTTP request is in flight. */
  isSubmitting: boolean;
  /** Called when the user confirms the pick. */
  onConfirm: () => void;
  /** Called when the user cancels or presses Escape. */
  onCancel: () => void;
}

// ---------------------------------------------------------------------------
// Position label map (full names for the modal — more space available)
// ---------------------------------------------------------------------------

const POSITION_LABEL: Record<PositionType, string> = {
  prop: "Pilier",
  hooker: "Talonneur",
  lock: "Deuxième ligne",
  flanker: "Troisième ligne",
  number_8: "Numéro 8",
  scrum_half: "Demi de mêlée",
  fly_half: "Demi d'ouverture",
  centre: "Centre",
  wing: "Ailier",
  fullback: "Arrière",
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function DraftPickConfirmModal({
  player,
  timeRemaining,
  isSubmitting,
  onConfirm,
  onCancel,
}: DraftPickConfirmModalProps) {
  const t = useTranslations("draft");
  const tCommon = useTranslations("common");
  // Ref for focus trap — the confirm button receives focus on open.
  const confirmButtonRef = useRef<HTMLButtonElement>(null);

  // ---------------------------------------------------------------------------
  // Focus management — move focus to confirm button when modal opens.
  // This satisfies WCAG 2.4.3 (Focus Order) and 2.1.1 (Keyboard).
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (player) {
      // Small delay to allow AnimatePresence to mount the element first.
      const timer = setTimeout(() => {
        confirmButtonRef.current?.focus();
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [player]);

  // ---------------------------------------------------------------------------
  // Keyboard handler — close on Escape (WCAG 2.1.1)
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (!player) return;

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape" && !isSubmitting) {
        onCancel();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [player, isSubmitting, onCancel]);

  // ---------------------------------------------------------------------------
  // Urgency colour for the timer display
  // ---------------------------------------------------------------------------

  const timerClass =
    timeRemaining < 10
      ? "text-destructive font-bold"
      : timeRemaining <= 30
        ? "text-[#C9A227] font-semibold"
        : "text-muted-foreground";

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <AnimatePresence>
      {player && (
        <>
          {/* Backdrop */}
          <motion.div
            key="backdrop"
            className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={isSubmitting ? undefined : onCancel}
            aria-hidden="true"
          />

          {/* Modal panel */}
          <motion.div
            key="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="modal-title"
            aria-describedby="modal-description"
            className="
              fixed z-50 inset-x-4 bottom-6
              md:inset-auto md:top-1/2 md:left-1/2
              md:-translate-x-1/2 md:-translate-y-1/2
              md:w-full md:max-w-sm
              bg-card border border-border rounded-2xl shadow-2xl
              overflow-hidden
            "
            initial={{ opacity: 0, y: 24, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 16, scale: 0.97 }}
            transition={{ duration: 0.22, ease: "easeOut" }}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-5 pt-5 pb-3">
              <h2
                id="modal-title"
                className="text-base font-bold text-foreground"
              >
                {t("pickConfirmTitle")}
              </h2>

              {/* Close button */}
              <button
                type="button"
                onClick={onCancel}
                disabled={isSubmitting}
                className="
                  w-8 h-8 flex items-center justify-center rounded-full
                  text-muted-foreground hover:text-foreground hover:bg-muted
                  focus:outline-none focus:ring-2 focus:ring-primary
                  disabled:opacity-40 disabled:cursor-not-allowed
                  transition-colors
                "
                aria-label={tCommon("close")}
              >
                <X className="w-4 h-4" aria-hidden="true" />
              </button>
            </div>

            {/* Player info */}
            <div id="modal-description" className="px-5 pb-4">
              {/* Player card — summary */}
              <div className="flex items-center gap-4 p-4 rounded-xl bg-primary/8 border border-primary/20">
                {/* Avatar initials */}
                <div
                  aria-hidden="true"
                  className="
                    flex-shrink-0 w-12 h-12 rounded-full
                    bg-primary/20 text-primary
                    flex items-center justify-center
                    text-sm font-bold uppercase
                  "
                >
                  {player.first_name[0]}
                  {player.last_name[0]}
                </div>

                {/* Details */}
                <div className="flex-1 min-w-0">
                  <p className="font-bold text-foreground text-base leading-tight">
                    {player.first_name}{" "}
                    <span className="uppercase">{player.last_name}</span>
                  </p>
                  <p className="text-sm text-muted-foreground mt-0.5 truncate">
                    {player.club}
                    <span className="mx-1.5 opacity-40">·</span>
                    {player.nationality}
                  </p>
                  {/* Position(s) */}
                  <div className="flex gap-1.5 mt-1.5 flex-wrap">
                    {player.positions.map((pos) => (
                      <span
                        key={pos}
                        className="text-xs font-medium text-primary bg-primary/10 px-2 py-0.5 rounded-full"
                      >
                        {POSITION_LABEL[pos]}
                      </span>
                    ))}
                  </div>
                </div>
              </div>

              {/* Timer warning */}
              {timeRemaining > 0 && (
                <p className={`text-xs text-center mt-3 ${timerClass}`}>
                  {t("timeRemaining", { seconds: Math.round(timeRemaining) })}
                  {" restantes"}
                </p>
              )}
            </div>

            {/* Action buttons */}
            <div className="flex gap-3 px-5 pb-5">
              {/* Cancel */}
              <button
                type="button"
                onClick={onCancel}
                disabled={isSubmitting}
                className="
                  flex-1 py-3 rounded-xl
                  text-sm font-semibold text-muted-foreground
                  bg-muted hover:bg-muted/80
                  focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-1
                  disabled:opacity-40 disabled:cursor-not-allowed
                  transition-colors
                "
              >
                {tCommon("cancel")}
              </button>

              {/* Confirm — receives focus on open */}
              <button
                ref={confirmButtonRef}
                type="button"
                onClick={onConfirm}
                disabled={isSubmitting}
                aria-busy={isSubmitting}
                className="
                  flex-1 py-3 rounded-xl
                  text-sm font-semibold text-primary-foreground
                  bg-primary hover:bg-primary/90 active:bg-primary/80
                  focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-1
                  disabled:opacity-60 disabled:cursor-not-allowed
                  transition-colors
                "
              >
                {isSubmitting ? (
                  <span className="flex items-center justify-center gap-2">
                    <svg
                      className="animate-spin h-4 w-4"
                      viewBox="0 0 24 24"
                      fill="none"
                      aria-hidden="true"
                    >
                      <circle
                        className="opacity-25"
                        cx="12"
                        cy="12"
                        r="10"
                        stroke="currentColor"
                        strokeWidth="4"
                      />
                      <path
                        className="opacity-75"
                        fill="currentColor"
                        d="M4 12a8 8 0 018-8v8H4z"
                      />
                    </svg>
                    {t("pickSubmitting")}
                  </span>
                ) : (
                  t("pickConfirm", {
                    player: `${player.first_name} ${player.last_name}`,
                  })
                )}
              </button>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
