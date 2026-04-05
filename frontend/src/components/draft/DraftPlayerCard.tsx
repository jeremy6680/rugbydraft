// frontend/src/components/draft/DraftPlayerCard.tsx
/**
 * DraftPlayerCard — single player card in the Draft Room player pool.
 *
 * States:
 *   available  — selectable, full opacity, click triggers onSelect
 *   drafted    — greyed out, non-interactive, shows "Drafté" badge
 *   injured    — greyed out, non-interactive, shows "Blessé" badge
 *   suspended  — greyed out, non-interactive, shows "Suspendu" badge
 *
 * The card is rendered as a <button> when available (keyboard accessible)
 * and as a <div role="listitem"> when unavailable (not focusable).
 */

"use client";

import { useTranslations } from "next-intl";
import type { PlayerSummary, PositionType } from "@/types/player";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface DraftPlayerCardProps {
  player: PlayerSummary;
  /** True if this player has already been picked in this draft. */
  isDrafted: boolean;
  /** Called when the user confirms they want to pick this player. */
  onSelect: (player: PlayerSummary) => void;
}

// ---------------------------------------------------------------------------
// Position label map — short display names for badges
// ---------------------------------------------------------------------------

const POSITION_SHORT: Record<PositionType, string> = {
  prop: "PIL",
  hooker: "TAL",
  lock: "2L",
  flanker: "3L",
  number_8: "N°8",
  scrum_half: "DM",
  fly_half: "DO",
  centre: "CTR",
  wing: "AIL",
  fullback: "ARR",
};

// Colour per position group — forwards vs backs
const POSITION_COLOUR: Record<PositionType, string> = {
  prop: "bg-emerald-900/40 text-emerald-300",
  hooker: "bg-emerald-900/40 text-emerald-300",
  lock: "bg-emerald-900/40 text-emerald-300",
  flanker: "bg-emerald-900/40 text-emerald-300",
  number_8: "bg-emerald-900/40 text-emerald-300",
  scrum_half: "bg-sky-900/40 text-sky-300",
  fly_half: "bg-sky-900/40 text-sky-300",
  centre: "bg-sky-900/40 text-sky-300",
  wing: "bg-sky-900/40 text-sky-300",
  fullback: "bg-sky-900/40 text-sky-300",
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function DraftPlayerCard({
  player,
  isDrafted,
  onSelect,
}: DraftPlayerCardProps) {
  const t = useTranslations("draft");

  const isUnavailable =
    isDrafted ||
    player.availability_status === "injured" ||
    player.availability_status === "suspended";

  const displayName = `${player.first_name} ${player.last_name}`;

  // Resolve unavailability badge label
  function getBadgeLabel(): string | null {
    if (isDrafted) return t("picked");
    if (player.availability_status === "injured") return t("injured");
    if (player.availability_status === "suspended") return t("suspended");
    return null;
  }

  const badgeLabel = getBadgeLabel();

  // ---------------------------------------------------------------------------
  // Shared card content (used in both button and div variants)
  // ---------------------------------------------------------------------------

  const cardContent = (
    <>
      {/* Left: avatar initials */}
      <div
        aria-hidden="true"
        className={`
          flex-shrink-0 w-10 h-10 rounded-full
          flex items-center justify-center
          text-xs font-bold uppercase tracking-wide
          ${
            isUnavailable
              ? "bg-muted text-muted-foreground"
              : "bg-primary/20 text-primary"
          }
        `}
      >
        {player.first_name[0]}
        {player.last_name[0]}
      </div>

      {/* Centre: name + club + nationality */}
      <div className="flex-1 min-w-0">
        <p
          className={`
          text-sm font-semibold truncate leading-tight
          ${isUnavailable ? "text-muted-foreground" : "text-foreground"}
        `}
        >
          {displayName}
        </p>
        <p className="text-xs text-muted-foreground truncate mt-0.5">
          {player.club}
          <span className="mx-1 opacity-40">·</span>
          {player.nationality}
        </p>
      </div>

      {/* Right: position badges + status badge */}
      <div className="flex flex-col items-end gap-1 flex-shrink-0">
        {/* Position badges — show all positions (multi-position players) */}
        <div className="flex gap-1 flex-wrap justify-end">
          {player.positions.map((pos) => (
            <span
              key={pos}
              className={`
                text-[10px] font-semibold px-1.5 py-0.5 rounded
                ${
                  isUnavailable
                    ? "bg-muted text-muted-foreground"
                    : POSITION_COLOUR[pos]
                }
              `}
            >
              {POSITION_SHORT[pos]}
            </span>
          ))}
        </div>

        {/* Unavailability badge */}
        {badgeLabel && (
          <span className="text-[10px] font-medium text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
            {badgeLabel}
          </span>
        )}
      </div>
    </>
  );

  // ---------------------------------------------------------------------------
  // Available — render as interactive button
  // ---------------------------------------------------------------------------

  if (!isUnavailable) {
    return (
      <button
        type="button"
        onClick={() => onSelect(player)}
        className="
          w-full flex items-center gap-3 px-4 py-3
          rounded-xl border border-border bg-card
          hover:border-primary/50 hover:bg-primary/5
          active:bg-primary/10
          focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-1
          transition-colors duration-150 text-left
        "
        aria-label={`Sélectionner ${displayName}`}
      >
        {cardContent}
      </button>
    );
  }

  // ---------------------------------------------------------------------------
  // Unavailable — render as non-interactive div
  // ---------------------------------------------------------------------------

  return (
    <div
      role="listitem"
      aria-disabled="true"
      className="
        w-full flex items-center gap-3 px-4 py-3
        rounded-xl border border-border/50 bg-card/50
        opacity-50 cursor-not-allowed
      "
    >
      {cardContent}
    </div>
  );
}
