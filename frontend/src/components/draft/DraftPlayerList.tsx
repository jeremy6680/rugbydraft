// frontend/src/components/draft/DraftPlayerList.tsx
/**
 * DraftPlayerList — scrollable, filterable player pool for the Draft Room.
 *
 * Features:
 *   - Text search (name, club, nationality)
 *   - Position filter (single position or "all")
 *   - Shows available players first, drafted/unavailable players at the bottom
 *   - Passes onSelect up to the parent (DraftRoom) which opens the confirm modal
 *
 * Performance note:
 *   Filtering is done client-side on the full player list (300–500 players).
 *   useMemo ensures the filtered list is only recomputed when the filter
 *   values or the picked set changes — not on every render.
 */

"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Search } from "lucide-react";
import DraftPlayerCard from "@/components/draft/DraftPlayerCard";
import type { PlayerSummary, PositionType } from "@/types/player";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface DraftPlayerListProps {
  players: PlayerSummary[];
  /** Set of player IDs already picked in this draft. */
  pickedPlayerIds: Set<string>;
  /** Called when the user clicks a player card. */
  onSelect: (player: PlayerSummary) => void;
  /** If false, all cards are non-interactive (not the user's turn). */
  isMyTurn: boolean;
}

// ---------------------------------------------------------------------------
// Position filter options — "all" + all position types
// ---------------------------------------------------------------------------

type PositionFilter = "all" | PositionType;

const POSITION_FILTERS: { value: PositionFilter; label: string }[] = [
  { value: "all", label: "Tous" },
  { value: "prop", label: "Piliers" },
  { value: "hooker", label: "Talonneurs" },
  { value: "lock", label: "2e lignes" },
  { value: "flanker", label: "3e lignes" },
  { value: "number_8", label: "N°8" },
  { value: "scrum_half", label: "Demis mêlée" },
  { value: "fly_half", label: "Demis ouv." },
  { value: "centre", label: "Centres" },
  { value: "wing", label: "Ailiers" },
  { value: "fullback", label: "Arrières" },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function DraftPlayerList({
  players,
  pickedPlayerIds,
  onSelect,
  isMyTurn,
}: DraftPlayerListProps) {
  const t = useTranslations("draft");

  const [searchQuery, setSearchQuery] = useState("");
  const [positionFilter, setPositionFilter] = useState<PositionFilter>("all");

  // ---------------------------------------------------------------------------
  // Filtered + sorted player list — memoised for performance
  // ---------------------------------------------------------------------------

  const filteredPlayers = useMemo(() => {
    const query = searchQuery.toLowerCase().trim();

    const filtered = players.filter((player) => {
      // Position filter
      if (
        positionFilter !== "all" &&
        !player.positions.includes(positionFilter)
      ) {
        return false;
      }

      // Text search — name, club, nationality
      if (query) {
        const fullName =
          `${player.first_name} ${player.last_name}`.toLowerCase();
        const matches =
          fullName.includes(query) ||
          player.club.toLowerCase().includes(query) ||
          player.nationality.toLowerCase().includes(query);
        if (!matches) return false;
      }

      return true;
    });

    // Sort: available first, then drafted/unavailable
    return filtered.sort((a, b) => {
      const aUnavailable =
        pickedPlayerIds.has(a.id) || a.availability_status !== "available";
      const bUnavailable =
        pickedPlayerIds.has(b.id) || b.availability_status !== "available";

      if (aUnavailable && !bUnavailable) return 1;
      if (!aUnavailable && bUnavailable) return -1;
      // Alphabetical within each group
      return a.last_name.localeCompare(b.last_name, "fr");
    });
  }, [players, pickedPlayerIds, searchQuery, positionFilter]);

  const availableCount = useMemo(
    () =>
      players.filter(
        (p) =>
          !pickedPlayerIds.has(p.id) && p.availability_status === "available",
      ).length,
    [players, pickedPlayerIds],
  );

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="flex flex-col h-full">
      {/* ── Search + filter bar ── */}
      <div className="flex-shrink-0 px-4 pt-3 pb-2 space-y-2 border-b border-border">
        {/* Search input */}
        <div className="relative">
          <Search
            aria-hidden="true"
            className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground"
          />
          <input
            type="search"
            placeholder={t("searchPlayer")}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="
              w-full pl-9 pr-4 py-2 text-sm
              bg-muted rounded-lg border border-transparent
              focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent
              placeholder:text-muted-foreground
              transition-colors
            "
            aria-label={t("searchPlayer")}
          />
        </div>

        {/* Position filter chips — horizontal scroll on mobile */}
        <div
          className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-none"
          role="group"
          aria-label={t("filterPosition")}
        >
          {POSITION_FILTERS.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              onClick={() => setPositionFilter(value)}
              className={`
                flex-shrink-0 text-xs font-medium px-3 py-1.5 rounded-full
                border transition-colors duration-150
                focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-1
                ${
                  positionFilter === value
                    ? "bg-primary text-primary-foreground border-primary"
                    : "bg-card text-muted-foreground border-border hover:border-primary/40 hover:text-foreground"
                }
              `}
              aria-pressed={positionFilter === value}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Result count */}
        <p className="text-xs text-muted-foreground">
          <span className="font-medium text-foreground">{availableCount}</span>
          {" joueurs disponibles"}
          {filteredPlayers.length !== players.length && (
            <span className="opacity-60">
              {" · "}
              {filteredPlayers.length} affichés
            </span>
          )}
        </p>
      </div>

      {/* ── Player list — scrollable ── */}
      <div
        className="flex-1 overflow-y-auto px-4 py-2 space-y-2"
        role="list"
        aria-label="Liste des joueurs"
      >
        {filteredPlayers.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <p className="text-muted-foreground text-sm">Aucun joueur trouvé</p>
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery("")}
                className="mt-2 text-xs text-primary underline underline-offset-4"
              >
                Effacer la recherche
              </button>
            )}
          </div>
        ) : (
          filteredPlayers.map((player) => (
            <DraftPlayerCard
              key={player.id}
              player={player}
              isDrafted={pickedPlayerIds.has(player.id)}
              onSelect={isMyTurn ? onSelect : () => {}}
            />
          ))
        )}
      </div>
    </div>
  );
}
