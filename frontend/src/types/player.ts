// frontend/src/types/player.ts
/**
 * TypeScript types for rugby player entities.
 *
 * Mirror the Pydantic schemas in backend/app/models/player.py.
 * PlayerSummary is the main type used in the Draft Room player list.
 */

// ---------------------------------------------------------------------------
// Enums — mirror backend StrEnums
// ---------------------------------------------------------------------------

/**
 * Rugby player positions.
 * Mirrors PositionType in backend/app/models/player.py.
 */
export type PositionType =
  | "prop"
  | "hooker"
  | "lock"
  | "flanker"
  | "number_8"
  | "scrum_half"
  | "fly_half"
  | "centre"
  | "wing"
  | "fullback";

/**
 * Player availability status.
 * Mirrors AvailabilityStatus in backend/app/models/player.py.
 */
export type AvailabilityStatus = "available" | "injured" | "suspended";

// ---------------------------------------------------------------------------
// Player entity
// ---------------------------------------------------------------------------

/**
 * Lightweight player used in list endpoints and the Draft Room pool.
 * Mirrors PlayerSummary in backend/app/models/player.py.
 */
export interface PlayerSummary {
  id: string; // UUID serialised as string by FastAPI
  first_name: string;
  last_name: string;
  nationality: string; // ISO 3166-1 alpha-2/3 (e.g. "FR", "ENG")
  club: string;
  positions: PositionType[];
  availability_status: AvailabilityStatus;
}
