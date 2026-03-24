// frontend/src/types/draft.ts
/**
 * TypeScript types for the RugbyDraft snake draft system.
 *
 * These types mirror exactly the Pydantic response schemas defined in:
 *   backend/app/schemas/draft.py
 *   backend/draft/engine.py  (DraftStatus enum)
 *
 * Contract: any change to the FastAPI schemas MUST be reflected here.
 * Consumed by: hooks/useDraftRealtime.ts + all DraftRoom components.
 */

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

/**
 * Lifecycle status of a draft session.
 * Mirrors DraftStatus (StrEnum) in backend/draft/engine.py.
 */
export type DraftStatus = "pending" | "in_progress" | "completed";

/**
 * Source of an autodraft pick selection.
 * null when the pick was made manually.
 */
export type AutodraftSource = "preference_list" | "default_value" | null;

// ---------------------------------------------------------------------------
// Core API entities
// ---------------------------------------------------------------------------

/**
 * A single pick recorded in the draft history.
 * Mirrors PickRecordResponse in backend/app/schemas/draft.py.
 */
export interface PickRecord {
  /** Absolute pick number, 1-indexed. */
  pick_number: number;
  /** Manager who made (or had autodrafted for) this pick. */
  manager_id: string;
  /** ID of the drafted player. */
  player_id: string;
  /** True if autodraft made this pick. */
  autodrafted: boolean;
  /** How autodraft selected the player. null if not an autodraft pick. */
  autodraft_source: AutodraftSource;
  /** asyncio loop time when the pick was recorded (server timestamp). */
  timestamp: number;
  /** True if the commissioner entered this pick in assisted mode. */
  entered_by_commissioner: boolean;
}

/**
 * Full draft state snapshot returned by the FastAPI draft endpoints.
 *
 * Returned by:
 *   POST /draft/{league_id}/connect  — on page load or reconnection
 *   GET  /draft/{league_id}/state    — polling fallback
 * Also broadcast via Supabase Realtime after every state change.
 *
 * Mirrors DraftStateSnapshotResponse in backend/app/schemas/draft.py.
 *
 * Timer synchronisation note (D-001):
 *   FastAPI is the authority of state. The client uses time_remaining
 *   from this snapshot to initialise its local countdown display.
 *   On reconnection, the client resets its timer to this value.
 */
export interface DraftStateSnapshot {
  /** The league this draft belongs to. */
  league_id: string;
  /** Current draft lifecycle status. */
  status: DraftStatus;
  /** Pick slot currently being filled (1-indexed). */
  current_pick_number: number;
  /** Total number of picks in this draft (managers × 30). */
  total_picks: number;
  /** Manager whose turn it is. null when draft is completed. */
  current_manager_id: string | null;
  /**
   * Seconds left on the current pick timer.
   * 0.0 when draft is completed or the active manager is in autodraft.
   */
  time_remaining: number;
  /** All picks made so far, in chronological order. */
  picks: PickRecord[];
  /** Manager IDs currently in autodraft mode. */
  autodraft_managers: string[];
  /** Manager IDs currently connected to the draft. */
  connected_managers: string[];
}

// ---------------------------------------------------------------------------
// Supabase Realtime broadcast event
// ---------------------------------------------------------------------------

/**
 * Shape of the Supabase Realtime broadcast payload.
 *
 * FastAPI broadcasts on channel "draft:{league_id}", event "state_update".
 * The hook useDraftRealtime listens for this event and updates local state.
 *
 * The payload IS the snapshot — the client replaces its state entirely
 * on each broadcast (no partial merge).
 */
export interface DraftRealtimePayload {
  type: "state_update";
  payload: DraftStateSnapshot;
}

// ---------------------------------------------------------------------------
// UI-layer derived state (client-side only, not from the API)
// ---------------------------------------------------------------------------

/**
 * Derived state computed by useDraftRealtime from the raw DraftStateSnapshot.
 * These convenience values keep component render logic clean and declarative.
 */
export interface DraftUIState {
  /** The raw snapshot from the server. null before first fetch. */
  snapshot: DraftStateSnapshot | null;
  /** True while the initial snapshot is being fetched on mount. */
  isLoading: boolean;
  /** Non-null string if a fetch or Realtime connection error occurred. */
  error: string | null;
  /** True if the current authenticated user is the active picker. */
  isMyTurn: boolean;
  /** True if the current user has autodraft activated. */
  isAutodraftActive: boolean;
  /** True if the draft is still accepting picks (status === "in_progress"). */
  isDraftActive: boolean;
}
