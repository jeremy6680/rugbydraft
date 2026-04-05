// frontend/src/components/draft/DraftOrderPanel.tsx
/**
 * DraftOrderPanel — snake order and pick history panel.
 *
 * Displays two sections:
 *   1. "Prochain ordre" — the upcoming pick slots for the current and
 *      next round, highlighting whose turn it currently is.
 *   2. "Historique" — all picks made so far, most recent first,
 *      with player name, manager name, and autodraft indicator.
 *
 * This is a pure display component — no state, no side effects.
 * All data comes from the DraftRoom parent via props.
 *
 * Layout:
 *   - Desktop: fixed sidebar panel, full height, scrollable history
 *   - Mobile: rendered inside a bottom sheet or tab (handled by DraftRoom)
 */

"use client";

import { useTranslations } from "next-intl";
import { Bot, User } from "lucide-react";
import type { PickRecord } from "@/types/draft";
import type { PlayerSummary } from "@/types/player";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface DraftOrderPanelProps {
  /** Ordered list of manager IDs in snake pick order for upcoming slots. */
  upcomingOrder: UpcomingSlot[];
  /** All picks made so far — passed in reverse (most recent first). */
  picks: PickRecord[];
  /** The manager whose turn it currently is. */
  currentManagerId: string | null;
  /** The authenticated user's ID — used to highlight "you" in the order. */
  currentUserId: string;
  /** Map of managerId → display name. */
  managerNames: Record<string, string>;
  /** Map of playerId → PlayerSummary — for resolving pick display names. */
  playerMap: Map<string, PlayerSummary>;
}

/**
 * A single upcoming pick slot in the snake order.
 */
export interface UpcomingSlot {
  pickNumber: number;
  managerId: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function DraftOrderPanel({
  upcomingOrder,
  picks,
  currentManagerId,
  currentUserId,
  managerNames,
  playerMap,
}: DraftOrderPanelProps) {
  const t = useTranslations("draft");

  // Picks in reverse chronological order (most recent first)
  const recentPicks = [...picks].reverse();

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* ── Section 1: Upcoming order ── */}
      <section
        aria-labelledby="order-heading"
        className="flex-shrink-0 p-4 border-b border-border"
      >
        <h2
          id="order-heading"
          className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3"
        >
          {t("upcomingOrder")}
        </h2>

        <ol className="space-y-1" aria-label="Ordre des prochains picks">
          {upcomingOrder.slice(0, 8).map((slot) => {
            const isActive = slot.managerId === currentManagerId;
            const isMe = slot.managerId === currentUserId;
            const name = managerNames[slot.managerId] ?? t("unknownManager");

            return (
              <li
                key={slot.pickNumber}
                className={`
                  flex items-center gap-3 px-3 py-2 rounded-lg
                  text-sm transition-colors duration-150
                  ${
                    isActive
                      ? "bg-primary/15 border border-primary/30 text-primary font-semibold"
                      : "text-muted-foreground"
                  }
                `}
                aria-current={isActive ? "true" : undefined}
              >
                {/* Pick number */}
                <span
                  className={`
                    flex-shrink-0 w-6 h-6 rounded-full text-xs font-bold
                    flex items-center justify-center
                    ${
                      isActive
                        ? "bg-primary text-primary-foreground"
                        : "bg-muted text-muted-foreground"
                    }
                  `}
                  aria-hidden="true"
                >
                  {slot.pickNumber}
                </span>

                {/* Manager name */}
                <span className="flex-1 truncate">
                  {isMe ? `${name} (vous)` : name}
                </span>

                {/* "En cours" indicator */}
                {isActive && (
                  <span
                    className="flex-shrink-0 w-2 h-2 rounded-full bg-primary animate-pulse"
                    aria-label="En cours"
                  />
                )}
              </li>
            );
          })}
        </ol>
      </section>

      {/* ── Section 2: Pick history ── */}
      <section
        aria-labelledby="history-heading"
        className="flex-1 overflow-y-auto p-4"
      >
        <h2
          id="history-heading"
          className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3"
        >
          {t("pickHistory")}
          {picks.length > 0 && (
            <span className="ml-2 font-normal normal-case">
              ({picks.length})
            </span>
          )}
        </h2>

        {picks.length === 0 ? (
          <p className="text-xs text-muted-foreground text-center py-6">
            {t("noPicksYet")}
          </p>
        ) : (
          <ol className="space-y-1.5" aria-label="Historique des picks">
            {recentPicks.map((pick) => {
              const managerName =
                managerNames[pick.manager_id] ?? t("unknownManager");
              const player = playerMap.get(pick.player_id);
              const playerName = player
                ? `${player.first_name} ${player.last_name}`
                : t("unknownPlayer");
              const isMe = pick.manager_id === currentUserId;

              return (
                <li
                  key={pick.pick_number}
                  className="flex items-start gap-2.5 px-3 py-2 rounded-lg bg-card border border-border/50"
                >
                  {/* Pick number badge */}
                  <span
                    className="flex-shrink-0 mt-0.5 w-5 h-5 rounded bg-muted text-muted-foreground text-[10px] font-bold flex items-center justify-center"
                    aria-hidden="true"
                  >
                    {pick.pick_number}
                  </span>

                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    {/* Player name */}
                    <p className="text-sm font-medium text-foreground truncate">
                      {playerName}
                    </p>

                    {/* Manager name + autodraft/commissioner indicator */}
                    <div className="flex items-center gap-1 mt-0.5">
                      {pick.autodrafted ? (
                        <Bot
                          className="w-3 h-3 text-muted-foreground flex-shrink-0"
                          aria-label="Autodraft"
                        />
                      ) : (
                        <User
                          className="w-3 h-3 text-muted-foreground flex-shrink-0"
                          aria-hidden="true"
                        />
                      )}
                      <span className="text-xs text-muted-foreground truncate">
                        {isMe ? `${managerName} (vous)` : managerName}
                        {pick.entered_by_commissioner && (
                          <span className="ml-1 opacity-60">
                            · {t("enteredByCommissioner")}
                          </span>
                        )}
                      </span>
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </section>
    </div>
  );
}
