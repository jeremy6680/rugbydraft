// frontend/src/components/draft/DraftStatusBanner.tsx
/**
 * DraftStatusBanner — contextual status bar for the Draft Room.
 *
 * Displays the current draft situation to the authenticated user:
 *   - "C'est votre tour !"       — when it is the user's turn to pick
 *   - "Autodraft activé"         — when the user's autodraft is running
 *   - "En attente de {manager}"  — when another manager is picking
 *   - "Draft terminé !"          — when all picks are complete
 *
 * Props:
 *   isMyTurn          — derived from useDraftRealtime
 *   isAutodraftActive — derived from useDraftRealtime
 *   isDraftActive     — derived from useDraftRealtime
 *   currentManagerId  — snapshot.current_manager_id (null when completed)
 *   managerNames      — map of managerId → display name (fetched server-side)
 *   currentPickNumber — for the pick counter label
 *   totalPicks        — for the pick counter label
 */

"use client";

import { motion, AnimatePresence } from "framer-motion";
import { useTranslations } from "next-intl";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface DraftStatusBannerProps {
  isMyTurn: boolean;
  isAutodraftActive: boolean;
  isDraftActive: boolean;
  /** Manager whose turn it currently is. null when draft is completed. */
  currentManagerId: string | null;
  /** Map of managerId → display name. Used to show "En attente de X". */
  managerNames: Record<string, string>;
  currentPickNumber: number;
  totalPicks: number;
}

// ---------------------------------------------------------------------------
// Banner variant config
// ---------------------------------------------------------------------------

type BannerVariant = "my-turn" | "autodraft" | "waiting" | "completed";

interface BannerConfig {
  variant: BannerVariant;
  message: string;
  /** Tailwind classes for background + text */
  containerClass: string;
  /** Accessible role — "status" for non-urgent, "alert" for urgent */
  role: "status" | "alert";
  /** Whether Framer Motion should pulse this banner */
  shouldPulse: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function DraftStatusBanner({
  isMyTurn,
  isAutodraftActive,
  isDraftActive,
  currentManagerId,
  managerNames,
  currentPickNumber,
  totalPicks,
}: DraftStatusBannerProps) {
  const t = useTranslations("draft");

  // --- Resolve current manager display name ---
  const currentManagerName =
    currentManagerId != null
      ? (managerNames[currentManagerId] ?? t("unknownManager"))
      : null;

  // --- Determine banner config ---
  const config = resolveBannerConfig({
    isMyTurn,
    isAutodraftActive,
    isDraftActive,
    currentManagerName,
    t,
  });

  return (
    <div className="flex flex-col items-center gap-1 w-full px-4">
      {/* Pick counter — always visible during draft */}
      {isDraftActive && (
        <p className="text-xs text-muted-foreground tabular-nums">
          {t("pickNumber", { pick: currentPickNumber })}
          <span className="opacity-50"> / {totalPicks}</span>
        </p>
      )}

      {/* Status banner — animates on variant change */}
      <AnimatePresence mode="wait">
        <motion.div
          key={config.variant}
          role={config.role}
          aria-live={config.role === "alert" ? "assertive" : "polite"}
          aria-atomic="true"
          className={`
            w-full max-w-sm rounded-xl px-5 py-3
            flex items-center justify-center gap-2
            text-sm font-semibold text-center
            ${config.containerClass}
          `}
          // Enter animation — slide down + fade in
          initial={{ opacity: 0, y: -8 }}
          animate={
            config.shouldPulse
              ? {
                  opacity: 1,
                  y: 0,
                  // Gentle pulse to draw attention on "your turn"
                  boxShadow: [
                    "0 0 0px rgba(26,92,56,0)",
                    "0 0 16px rgba(26,92,56,0.5)",
                    "0 0 0px rgba(26,92,56,0)",
                  ],
                }
              : { opacity: 1, y: 0 }
          }
          exit={{ opacity: 0, y: 8 }}
          transition={{ duration: 0.25, ease: "easeOut" }}
        >
          {/* Icon dot */}
          <StatusDot variant={config.variant} />

          {/* Message */}
          <span>{config.message}</span>
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

// ---------------------------------------------------------------------------
// resolveBannerConfig — pure function, fully testable
// ---------------------------------------------------------------------------

function resolveBannerConfig({
  isMyTurn,
  isAutodraftActive,
  isDraftActive,
  currentManagerName,
  t,
}: {
  isMyTurn: boolean;
  isAutodraftActive: boolean;
  isDraftActive: boolean;
  currentManagerName: string | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  t: (key: string, values?: Record<string, any>) => string;
}): BannerConfig {
  // Priority order matters: completed > my-turn > autodraft > waiting
  if (!isDraftActive) {
    return {
      variant: "completed",
      message: t("draftComplete"),
      containerClass:
        "bg-[#C9A227]/15 text-[#C9A227] border border-[#C9A227]/30",
      role: "status",
      shouldPulse: false,
    };
  }

  if (isMyTurn) {
    return {
      variant: "my-turn",
      message: t("yourTurn"),
      containerClass: "bg-primary/15 text-primary border border-primary/40",
      role: "alert",
      shouldPulse: true,
    };
  }

  if (isAutodraftActive) {
    return {
      variant: "autodraft",
      message: t("autodraftActive"),
      containerClass: "bg-muted text-muted-foreground border border-border",
      role: "status",
      shouldPulse: false,
    };
  }

  // Default: waiting for another manager
  return {
    variant: "waiting",
    message: currentManagerName
      ? t("waitingFor", { manager: currentManagerName })
      : t("loading"),
    containerClass: "bg-card text-foreground border border-border",
    role: "status",
    shouldPulse: false,
  };
}

// ---------------------------------------------------------------------------
// StatusDot — small coloured indicator dot
// ---------------------------------------------------------------------------

function StatusDot({ variant }: { variant: BannerVariant }) {
  const dotClass: Record<BannerVariant, string> = {
    "my-turn": "bg-primary animate-pulse",
    autodraft: "bg-muted-foreground",
    waiting: "bg-border",
    completed: "bg-[#C9A227]",
  };

  return (
    <span
      aria-hidden="true"
      className={`flex-shrink-0 w-2 h-2 rounded-full ${dotClass[variant]}`}
    />
  );
}
