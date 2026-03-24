// frontend/src/components/draft/DraftTimer.tsx
/**
 * DraftTimer — visual countdown for the Draft Room.
 *
 * Responsibilities:
 *   - Display a live countdown in seconds.
 *   - Manage a local setInterval that decrements every second.
 *   - Reset the local countdown whenever timeRemaining changes
 *     (i.e. when a new snapshot arrives from useDraftRealtime).
 *   - Apply urgency colours and a Framer Motion pulse animation
 *     when time is running low.
 *
 * Timer authority (D-001):
 *   FastAPI owns the real timer. This component only displays a local
 *   approximation that is resynchronised on every Realtime snapshot.
 *   If the client is 1–2 seconds off, it does not matter — FastAPI
 *   decides when the timer actually expires.
 *
 * Urgency thresholds:
 *   > 30s  → neutral  (muted foreground)
 *   10–30s → warning  (gold #C9A227)
 *   < 10s  → critical (red + pulse animation)
 */

"use client";

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useTranslations } from "next-intl";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface DraftTimerProps {
  /**
   * Seconds remaining as reported by the latest server snapshot.
   * Whenever this prop changes, the local countdown resets to this value.
   */
  timeRemaining: number;
  /**
   * Whether the timer should be counting down.
   * False when: draft is completed, not yet started, or active manager
   * is in autodraft mode (timer is irrelevant to the user).
   */
  isActive: boolean;
  /**
   * Optional CSS class applied to the outermost element.
   */
  className?: string;
}

// ---------------------------------------------------------------------------
// Urgency thresholds
// ---------------------------------------------------------------------------

type UrgencyLevel = "normal" | "warning" | "critical";

function getUrgency(seconds: number): UrgencyLevel {
  if (seconds < 10) return "critical";
  if (seconds <= 30) return "warning";
  return "normal";
}

// Tailwind classes per urgency level.
// Uses CSS variables defined in globals.css / shadcn theme for "normal",
// and the CDC palette colours for "warning" and "critical".
const URGENCY_STYLES: Record<UrgencyLevel, string> = {
  normal: "text-muted-foreground",
  warning: "text-[#C9A227]", // CDC gold
  critical: "text-destructive", // shadcn --destructive (red)
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function DraftTimer({
  timeRemaining,
  isActive,
  className = "",
}: DraftTimerProps) {
  const t = useTranslations("draft");

  // Local countdown — initialised from the server value, decremented every second.
  const [localTime, setLocalTime] = useState<number>(
    Math.max(0, Math.round(timeRemaining)),
  );

  // Ref to the interval so we can clear it on cleanup / reset.
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ---------------------------------------------------------------------------
  // Resync: whenever the server sends a new timeRemaining, reset local counter.
  // This is the key synchronisation mechanism — see D-001.
  // ---------------------------------------------------------------------------

  useEffect(() => {
    setLocalTime(Math.max(0, Math.round(timeRemaining)));
  }, [timeRemaining]);

  // ---------------------------------------------------------------------------
  // Countdown interval — runs only when isActive and time > 0.
  // ---------------------------------------------------------------------------

  useEffect(() => {
    // Clear any existing interval before (re)starting.
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }

    if (!isActive || localTime <= 0) return;

    intervalRef.current = setInterval(() => {
      setLocalTime((prev) => {
        if (prev <= 1) {
          // Reached zero — clear interval, let FastAPI handle the autodraft.
          if (intervalRef.current !== null) {
            clearInterval(intervalRef.current);
            intervalRef.current = null;
          }
          return 0;
        }
        return prev - 1;
      });
    }, 1_000);

    // Cleanup on effect teardown (isActive changes, component unmounts).
    return () => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    // localTime intentionally excluded: we only (re)start the interval when
    // isActive changes or the server resets the timer (timeRemaining effect).
  }, [isActive, timeRemaining]);

  // ---------------------------------------------------------------------------
  // Derived display values
  // ---------------------------------------------------------------------------

  const urgency = getUrgency(localTime);
  const isCritical = urgency === "critical";

  // Format as "m:ss" when >= 60 seconds, plain seconds otherwise.
  const displayTime =
    localTime >= 60
      ? `${Math.floor(localTime / 60)}:${String(localTime % 60).padStart(2, "0")}`
      : t("timeRemaining", { seconds: localTime });

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (!isActive) {
    return null;
  }

  return (
    <div
      className={`flex flex-col items-center gap-1 ${className}`}
      // WCAG 2.1 — live region so screen readers announce countdown changes.
      // "off" prevents per-second announcements (too noisy).
      // We switch to "assertive" at critical threshold via aria-live on inner.
      aria-label={`Temps restant : ${localTime} secondes`}
    >
      {/* Countdown number with urgency colour */}
      <AnimatePresence mode="wait">
        <motion.span
          key={localTime} // remount on each second to trigger enter animation
          className={`
            font-mono text-4xl font-bold tabular-nums leading-none
            ${URGENCY_STYLES[urgency]}
          `}
          // Pulse animation only in critical phase — subtle scale + opacity.
          animate={
            isCritical
              ? {
                  scale: [1, 1.08, 1],
                  opacity: [1, 0.85, 1],
                }
              : { scale: 1, opacity: 1 }
          }
          transition={
            isCritical
              ? { duration: 0.4, ease: "easeInOut" }
              : { duration: 0.15 }
          }
          // Screen readers — announce assertively only when critical.
          aria-live={isCritical ? "assertive" : "off"}
          aria-atomic="true"
        >
          {displayTime}
        </motion.span>
      </AnimatePresence>

      {/* Progress bar — drains from full to empty */}
      <TimerProgressBar
        timeRemaining={localTime}
        totalTime={timeRemaining > localTime ? timeRemaining : localTime}
        urgency={urgency}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// TimerProgressBar — sub-component
// ---------------------------------------------------------------------------

/**
 * A thin horizontal bar that visually drains as the timer counts down.
 * Width is animated by Framer Motion for smoothness.
 */
interface TimerProgressBarProps {
  timeRemaining: number;
  totalTime: number;
  urgency: UrgencyLevel;
}

const PROGRESS_BAR_COLOUR: Record<UrgencyLevel, string> = {
  normal: "bg-primary", // CDC green #1A5C38 via shadcn --primary
  warning: "bg-[#C9A227]", // CDC gold
  critical: "bg-destructive", // shadcn red
};

function TimerProgressBar({
  timeRemaining,
  totalTime,
  urgency,
}: TimerProgressBarProps) {
  // Percentage width — clamp between 0 and 100.
  const pct =
    totalTime > 0
      ? Math.min(100, Math.max(0, (timeRemaining / totalTime) * 100))
      : 0;

  return (
    // Track — full-width grey background
    <div
      className="w-full h-1.5 rounded-full bg-muted overflow-hidden"
      role="progressbar"
      aria-valuenow={Math.round(timeRemaining)}
      aria-valuemin={0}
      aria-valuemax={Math.round(totalTime)}
      aria-label="Temps restant"
    >
      {/* Fill — animated width */}
      <motion.div
        className={`h-full rounded-full ${PROGRESS_BAR_COLOUR[urgency]}`}
        animate={{ width: `${pct}%` }}
        transition={{ duration: 0.8, ease: "linear" }}
      />
    </div>
  );
}
