# backend/draft/engine.py
"""
DraftEngine — authority of state for the RugbyDraft snake draft.

This is the central orchestrator of Phase 2. It wires together:
    - snake_order.py  — pick ordering
    - timer.py        — server-side countdown
    - validate_pick.py — pick validation
    - autodraft.py    — automatic pick selection
    - broadcaster.py  — Supabase Realtime broadcast (D-001)
    - assisted.py     — Assisted Draft fallback mode (CDC 7.5)

Architecture principle (D-001):
    FastAPI is the authority of state. Supabase Realtime is a broadcast
    channel only. All state mutations happen here, in memory, under an
    asyncio.Lock to prevent race conditions.

Autodraft activation (CDC v3.1, section 7.3):
    - Timer expiration → autodraft for this pick, manager stays in autodraft
      for all remaining picks.
    - Manager never connected at draft start → full autodraft from pick 1.
    - Manual activation → manager opts in before or during the draft.

Reconnection protocol (CDC v3.1, section 7.4, D-001):
    - On reconnect, the client receives a full DraftStateSnapshot.
    - If the manager reconnects during their turn with time remaining,
      they can take control (autodraft deactivated).
    - If the timer already expired, the autodraft pick is final.

Assisted Draft (CDC v3.1, section 7.5):
    - Commissioner activates assisted mode via enable_assisted_mode().
    - Commissioner submits picks via submit_assisted_pick().
    - No timer in assisted mode — picks are entered at the commissioner's pace.
    - Every assisted pick is appended to the audit log (AssistedPickAuditEntry).
    - The resulting roster is identical to a standard synchronous draft.

Broadcast (Supabase Realtime):
    Every state-changing method calls _broadcast(event) with a typed
    DraftEvent. In production, a SupabaseBroadcaster is injected.
    In tests, a MockBroadcaster captures events without any I/O.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Optional

from app.models.league import CompetitionType
from app.models.player import PlayerSummary
from draft.assisted import (
    AssistedDraftError,
    AssistedPickAuditEntry,
    AssistedModeAlreadyActiveError,
    build_audit_entry,
    validate_assisted_mode_active,
    validate_assisted_mode_not_already_active,
    validate_commissioner,
)
from draft.autodraft import AutodraftError, AutodraftResult, select_autodraft_pick
from draft.broadcaster import BroadcasterProtocol, MockBroadcaster
from draft.events import (
    DraftAssistedModeEnabledEvent,
    DraftCompletedEvent,
    DraftEvent,
    DraftManagerConnectedEvent,
    DraftManagerDisconnectedEvent,
    DraftPickMadeEvent,
    DraftStartedEvent,
    DraftTurnChangedEvent,
)
from draft.snake_order import generate_snake_order
from draft.timer import DEFAULT_PICK_DURATION_SECONDS, DraftTimer
from draft.validate_pick import (
    PickValidationError,
    RosterSnapshot,
    _validate_player_availability,
    _validate_roster_constraints,
    validate_pick,
)

logger = logging.getLogger(__name__)

# Total number of rounds per draft (CDC v3.1, section 6: 15 starters + 15 bench)
DRAFT_NUM_ROUNDS: int = 30


# ---------------------------------------------------------------------------
# State types
# ---------------------------------------------------------------------------


class DraftStatus(StrEnum):
    """Lifecycle status of a draft session."""

    PENDING = "pending"          # created, not yet started
    IN_PROGRESS = "in_progress"  # draft running
    COMPLETED = "completed"      # all picks made


@dataclass
class PickRecord:
    """A single pick recorded in the draft history.

    Attributes:
        pick_number: Absolute pick number, 1-indexed.
        manager_id: Manager who made (or had autodrafted for) this pick.
        player_id: ID of the drafted player.
        autodrafted: True if the pick was made by autodraft.
        autodraft_source: 'preference_list', 'default_value', or None.
        entered_by_commissioner: True if submitted via assisted mode.
        timestamp: asyncio loop time when the pick was recorded.
    """

    pick_number: int
    manager_id: str
    player_id: str
    autodrafted: bool = False
    autodraft_source: Optional[str] = None
    entered_by_commissioner: bool = False  # NEW: assisted mode flag
    timestamp: float = 0.0


@dataclass
class DraftStateSnapshot:
    """Immutable snapshot of the draft state for reconnecting clients.

    Sent by FastAPI when a client reconnects (CDC v3.1, section 7.4).
    Contains everything the client needs to render the current state.
    """

    league_id: str
    status: DraftStatus
    current_pick_number: int
    total_picks: int
    current_manager_id: Optional[str]    # None if draft completed
    time_remaining: float                 # seconds, 0.0 if completed or assisted mode
    picks: list[PickRecord]
    autodraft_managers: list[str]
    connected_managers: list[str]
    assisted_mode: bool = False                              # NEW: assisted mode flag
    assisted_audit_log: list[AssistedPickAuditEntry] = field(  # NEW: full audit log
        default_factory=list
    )


@dataclass
class DraftState:
    """Full in-memory draft state. Mutated only by DraftEngine methods.

    Never expose this object directly to clients — use DraftStateSnapshot.
    """

    league_id: str
    managers: list[str]              # ordered after random draw
    draft_order: list[str]           # flat snake order list
    competition_type: CompetitionType
    pick_duration: float             # seconds per pick
    commissioner_id: str = "commissioner-default",
    status: DraftStatus = DraftStatus.PENDING
    current_pick_number: int = 1
    picks: list[PickRecord] = field(default_factory=list)

    # Rosters: manager_id → RosterSnapshot (rebuilt on each pick)
    rosters: dict[str, RosterSnapshot] = field(default_factory=dict)

    # All player IDs drafted so far (across all managers)
    drafted_player_ids: frozenset[str] = frozenset()

    # Managers currently in autodraft mode
    autodraft_managers: set[str] = field(default_factory=set)

    # Managers currently connected (WebSocket / Realtime subscription active)
    connected_managers: set[str] = field(default_factory=set)

    # NEW: Assisted Draft mode (CDC v3.1, section 7.5)
    assisted_mode: bool = False
    assisted_audit_log: list[AssistedPickAuditEntry] = field(default_factory=list)

    @property
    def total_picks(self) -> int:
        """Total number of picks in this draft."""
        return len(self.draft_order)

    @property
    def is_completed(self) -> bool:
        """True if all picks have been made."""
        return self.current_pick_number > self.total_picks

    @property
    def current_manager_id(self) -> Optional[str]:
        """Manager ID whose turn it is. None if draft completed."""
        if self.is_completed:
            return None
        return self.draft_order[self.current_pick_number - 1]


# ---------------------------------------------------------------------------
# DraftEngine
# ---------------------------------------------------------------------------


class DraftEngine:
    """Authoritative state manager for a single league's snake draft.

    One DraftEngine instance per active draft. Stored in FastAPI's
    application state (or a registry dict keyed by league_id).

    Thread safety: all public async methods acquire self._lock before
    mutating state. This prevents race conditions when two clients
    submit picks simultaneously.

    Usage:
        engine = DraftEngine(
            league_id="abc123",
            manager_ids=["M1", "M2", "M3"],
            available_players=players,
            competition_type=CompetitionType.INTERNATIONAL,
            commissioner_id="M1",
            pick_duration=120.0,
            broadcaster=SupabaseBroadcaster(client, "abc123"),
        )
        await engine.start_draft(connected_manager_ids={"M1", "M3"})
        await engine.submit_pick(manager_id="M1", player_id="player-uuid")
        snapshot = engine.get_state_snapshot()
    """

    def __init__(
        self,
        league_id: str,
        manager_ids: list[str],
        available_players: list[PlayerSummary],
        competition_type: CompetitionType,
        commissioner_id: str,
        pick_duration: float = DEFAULT_PICK_DURATION_SECONDS,
        preference_lists: Optional[dict[str, list[str]]] = None,
        broadcaster: Optional[BroadcasterProtocol] = None,
    ) -> None:
        """Initialise the DraftEngine. Does NOT start the draft.

        Call start_draft() explicitly to begin.

        Args:
            league_id: The league this draft belongs to.
            manager_ids: All manager IDs. Will be shuffled for the draw.
            available_players: Full player pool, pre-sorted by value_score desc.
            competition_type: International or club (determines constraints).
            commissioner_id: User ID of the league commissioner. Required to
                             authorise assisted mode actions.
            pick_duration: Seconds per pick. Default: 120s (CDC v3.1).
            preference_lists: Optional dict of manager_id → ordered player IDs.
            broadcaster: Broadcast implementation. Defaults to MockBroadcaster
                         (no-op safe for tests and local development).
        """
        # Shuffle managers for random draw (CDC v3.1, section 7.2)
        shuffled = manager_ids.copy()
        random.shuffle(shuffled)

        draft_order = generate_snake_order(shuffled, num_rounds=DRAFT_NUM_ROUNDS)

        self._state = DraftState(
            league_id=league_id,
            managers=shuffled,
            draft_order=draft_order,
            competition_type=competition_type,
            commissioner_id=commissioner_id,
            pick_duration=pick_duration,
            rosters={
                m: RosterSnapshot(
                    manager_id=m,
                    player_ids=frozenset(),
                    nationalities=[],
                    clubs=[],
                )
                for m in shuffled
            },
        )

        # Player pool — sorted by value_score desc (caller's responsibility)
        self._available_players: list[PlayerSummary] = list(available_players)

        # Preference lists — default to empty list per manager
        self._preference_lists: dict[str, list[str]] = preference_lists or {}

        # Current active timer — one per pick slot (None in assisted mode)
        self._current_timer: Optional[DraftTimer] = None

        # Concurrency lock — prevents simultaneous pick submissions
        self._lock = asyncio.Lock()

        # Broadcaster — defaults to MockBroadcaster (safe no-op)
        self._broadcaster: BroadcasterProtocol = broadcaster or MockBroadcaster()

        logger.info(
            "DraftEngine created: league=%s, managers=%s, total_picks=%d, commissioner=%s",
            league_id,
            shuffled,
            self._state.total_picks,
            commissioner_id,
        )

    # ------------------------------------------------------------------
    # Public interface — standard draft
    # ------------------------------------------------------------------

    async def start_draft(
        self,
        connected_manager_ids: set[str],
    ) -> None:
        """Start the draft.

        Managers not in connected_manager_ids are immediately placed in
        autodraft mode (CDC v3.1, section 7.3: "manager never connected").

        Args:
            connected_manager_ids: Set of manager IDs currently connected.

        Raises:
            RuntimeError: If the draft is not in PENDING status.
        """
        async with self._lock:
            if self._state.status != DraftStatus.PENDING:
                raise RuntimeError(
                    f"Cannot start draft with status '{self._state.status}'"
                )

            self._state.status = DraftStatus.IN_PROGRESS
            self._state.connected_managers = set(connected_manager_ids)

            # Mark disconnected managers as autodraft immediately
            for manager_id in self._state.managers:
                if manager_id not in connected_manager_ids:
                    self._state.autodraft_managers.add(manager_id)
                    logger.info(
                        "Manager '%s' not connected at draft start — autodraft activated",
                        manager_id,
                    )

            logger.info(
                "Draft started: league=%s, autodraft_managers=%s",
                self._state.league_id,
                self._state.autodraft_managers,
            )

            await self._broadcast(DraftStartedEvent(
                league_id=self._state.league_id,
                managers=list(self._state.managers),
                total_picks=self._state.total_picks,
                current_manager_id=self._state.current_manager_id,
                pick_duration=self._state.pick_duration,
                autodraft_managers=list(self._state.autodraft_managers),
            ))
            await self._start_current_turn()

    async def submit_pick(
        self,
        manager_id: str,
        player_id: str,
    ) -> PickRecord:
        """Submit a manual pick for a manager.

        Validates the pick, records it, cancels the timer, and advances
        to the next turn.

        Args:
            manager_id: The manager submitting the pick.
            player_id: The player being picked.

        Returns:
            The recorded PickRecord.

        Raises:
            PickValidationError: If any validation layer fails.
            RuntimeError: If the draft is not IN_PROGRESS.
        """
        async with self._lock:
            if self._state.status != DraftStatus.IN_PROGRESS:
                raise RuntimeError(
                    f"Cannot submit pick — draft status is '{self._state.status}'"
                )

            # Find the player in the available pool
            player = self._get_available_player(player_id)
            roster = self._state.rosters[manager_id]

            # Validate — raises PickValidationError on failure
            validate_pick(
                manager_id=manager_id,
                player_id=player_id,
                current_pick_number=self._state.current_pick_number,
                draft_order=self._state.draft_order,
                drafted_player_ids=self._state.drafted_player_ids,
                player=player,
                roster=roster,
                competition_type=self._state.competition_type,
            )

            # Cancel the running timer — manager picked in time
            if self._current_timer is not None:
                self._current_timer.cancel()
                self._current_timer = None

            # Record the pick and advance state
            record = self._record_pick(
                player_id=player_id,
                player=player,
                autodrafted=False,
            )

            await self._broadcast(DraftPickMadeEvent(
                league_id=self._state.league_id,
                pick_number=record.pick_number,
                manager_id=record.manager_id,
                player_id=record.player_id,
                autodrafted=False,
            ))
            await self._advance_to_next_turn()

            return record

    async def connect_manager(self, manager_id: str) -> DraftStateSnapshot:
        """Register a manager as connected and return the full state snapshot.

        If the manager reconnects during their own turn and no pick has been
        made yet (timer running or autodraft task pending), they can take
        control (autodraft deactivated).

        Args:
            manager_id: The reconnecting manager.

        Returns:
            Full DraftStateSnapshot for the client to render.
        """
        async with self._lock:
            self._state.connected_managers.add(manager_id)

            autodraft_deactivated = False

            # Give control back if reconnecting during own turn before pick is made.
            is_own_turn = (
                self._state.status == DraftStatus.IN_PROGRESS
                and self._state.current_manager_id == manager_id
                and manager_id in self._state.autodraft_managers
            )
            pick_not_yet_made = not any(
                p.pick_number == self._state.current_pick_number
                for p in self._state.picks
            )

            if is_own_turn and pick_not_yet_made:
                self._state.autodraft_managers.discard(manager_id)
                autodraft_deactivated = True
                logger.info(
                    "Manager '%s' reconnected during their turn — autodraft deactivated",
                    manager_id,
                )
                # Start the timer now that manager is taking manual control.
                # Note: in assisted mode, no timer is started — commissioner drives pace.
                if not self._state.assisted_mode:
                    self._current_timer = DraftTimer(
                        duration=self._state.pick_duration,
                        on_expire=self._on_timer_expired,
                    )
                    self._current_timer.start()

            await self._broadcast(DraftManagerConnectedEvent(
                league_id=self._state.league_id,
                manager_id=manager_id,
                connected_managers=list(self._state.connected_managers),
                autodraft_deactivated=autodraft_deactivated,
            ))
            return self.get_state_snapshot()

    async def disconnect_manager(self, manager_id: str) -> None:
        """Register a manager as disconnected.

        The draft continues uninterrupted. If the timer expires while
        disconnected, autodraft fires normally.

        Args:
            manager_id: The disconnecting manager.
        """
        async with self._lock:
            self._state.connected_managers.discard(manager_id)
            logger.info("Manager '%s' disconnected", manager_id)

            await self._broadcast(DraftManagerDisconnectedEvent(
                league_id=self._state.league_id,
                manager_id=manager_id,
                connected_managers=list(self._state.connected_managers),
            ))

    async def activate_autodraft(self, manager_id: str) -> None:
        """Manually activate autodraft for a manager.

        Args:
            manager_id: Manager opting into autodraft.
        """
        async with self._lock:
            self._state.autodraft_managers.add(manager_id)
            logger.info("Manager '%s' activated autodraft manually", manager_id)

            # If it's currently their turn, trigger autodraft immediately
            if (
                self._state.status == DraftStatus.IN_PROGRESS
                and self._state.current_manager_id == manager_id
            ):
                await self._run_autodraft_for_current_pick()

    # ------------------------------------------------------------------
    # Public interface — Assisted Draft (CDC v3.1, section 7.5)
    # ------------------------------------------------------------------

    async def enable_assisted_mode(self, commissioner_id: str) -> None:
        """Switch the draft to Assisted Draft mode.

        In assisted mode:
            - The server-side timer is cancelled and will not restart.
            - The commissioner submits all picks via submit_assisted_pick().
            - All picks are logged with entered_by_commissioner=True.

        Can only be called by the league commissioner, and only while
        the draft is IN_PROGRESS or PENDING.

        Args:
            commissioner_id: User ID of the person requesting the switch.

        Raises:
            NotCommissionerError: If caller is not the league commissioner.
            AssistedModeAlreadyActiveError: If already in assisted mode.
            RuntimeError: If the draft is COMPLETED.
        """
        async with self._lock:
            if self._state.status == DraftStatus.COMPLETED:
                raise RuntimeError("Cannot enable assisted mode on a completed draft.")

            # Authorisation: only the commissioner can flip this switch
            validate_commissioner(commissioner_id, self._state.commissioner_id)

            # Idempotency guard
            validate_assisted_mode_not_already_active(self._state.assisted_mode)

            # Cancel the running timer — no timer in assisted mode
            if self._current_timer is not None:
                self._current_timer.cancel()
                self._current_timer = None

            self._state.assisted_mode = True

            logger.info(
                "Assisted mode enabled: league=%s, by commissioner=%s",
                self._state.league_id,
                commissioner_id,
            )

            await self._broadcast(DraftAssistedModeEnabledEvent(
                league_id=self._state.league_id,
                commissioner_id=commissioner_id,
                current_pick_number=self._state.current_pick_number,
            ))

    async def submit_assisted_pick(
        self,
        commissioner_id: str,
        manager_id: str,
        player_id: str,
    ) -> PickRecord:
        """Submit a pick on behalf of a manager in Assisted Draft mode.

        The commissioner specifies which manager this pick belongs to.
        The pick must follow the snake order — manager_id must match the
        current pick slot (same turn validation as normal picks).

        Player availability and roster constraints are still enforced:
        the resulting roster must be identical to a standard draft.

        No timer is involved — the commissioner sets the pace.

        Args:
            commissioner_id: User ID of the commissioner entering the pick.
            manager_id: Manager whose turn it is (must match draft order).
            player_id: Player being drafted.

        Returns:
            The recorded PickRecord (with entered_by_commissioner=True).

        Raises:
            NotCommissionerError: If caller is not the league commissioner.
            AssistedModeNotActiveError: If assisted mode is not active.
            PickValidationError: If turn, player, or roster validation fails.
            RuntimeError: If the draft is not IN_PROGRESS.
        """
        async with self._lock:
            if self._state.status != DraftStatus.IN_PROGRESS:
                raise RuntimeError(
                    f"Cannot submit assisted pick — draft status is '{self._state.status}'"
                )

            # Authorisation: only the commissioner can submit assisted picks
            validate_commissioner(commissioner_id, self._state.commissioner_id)

            # Mode guard: assisted mode must be active
            validate_assisted_mode_active(self._state.assisted_mode)

            # Find the player — raises PlayerAlreadyDraftedError if not found
            player = self._get_available_player(player_id)
            roster = self._state.rosters[manager_id]

            # Full pick validation: turn + player + roster constraints.
            # We reuse validate_pick() entirely — the turn check ensures the
            # commissioner submits picks in the correct snake order.
            validate_pick(
                manager_id=manager_id,
                player_id=player_id,
                current_pick_number=self._state.current_pick_number,
                draft_order=self._state.draft_order,
                drafted_player_ids=self._state.drafted_player_ids,
                player=player,
                roster=roster,
                competition_type=self._state.competition_type,
            )

            # Record the pick with the commissioner flag
            record = self._record_pick(
                player_id=player_id,
                player=player,
                autodrafted=False,
                entered_by_commissioner=True,
            )

            # Append to the audit log
            audit_entry = build_audit_entry(
                pick_number=record.pick_number,
                manager_id=manager_id,
                player_id=player_id,
                commissioner_id=commissioner_id,
            )
            self._state.assisted_audit_log.append(audit_entry)

            logger.info(
                "Assisted pick %d recorded: manager='%s' player='%s' by commissioner='%s'",
                record.pick_number,
                manager_id,
                player_id,
                commissioner_id,
            )

            await self._broadcast(DraftPickMadeEvent(
                league_id=self._state.league_id,
                pick_number=record.pick_number,
                manager_id=record.manager_id,
                player_id=record.player_id,
                autodrafted=False,
                entered_by_commissioner=True,
            ))
            await self._advance_to_next_turn()

            return record

    def get_assisted_audit_log(self) -> list[AssistedPickAuditEntry]:
        """Return the full assisted draft audit log.

        Safe to call without the lock (read-only, returns a copy).

        Returns:
            List of AssistedPickAuditEntry, ordered by pick number.
        """
        return list(self._state.assisted_audit_log)

    def get_state_snapshot(self) -> DraftStateSnapshot:
        """Return an immutable snapshot of the current draft state.

        Used for reconnection protocol and API responses.
        Safe to call without the lock (read-only).
        """
        return DraftStateSnapshot(
            league_id=self._state.league_id,
            status=self._state.status,
            current_pick_number=self._state.current_pick_number,
            total_picks=self._state.total_picks,
            current_manager_id=self._state.current_manager_id,
            time_remaining=(
                self._current_timer.time_remaining
                if self._current_timer is not None
                else 0.0
            ),
            picks=list(self._state.picks),
            autodraft_managers=list(self._state.autodraft_managers),
            connected_managers=list(self._state.connected_managers),
            assisted_mode=self._state.assisted_mode,
            assisted_audit_log=list(self._state.assisted_audit_log),
        )

    # ------------------------------------------------------------------
    # Internal — turn management
    # ------------------------------------------------------------------

    async def _start_current_turn(self) -> None:
        """Start the timer (or autodraft) for the current pick slot.

        In assisted mode, no timer is started — the commissioner drives pace.
        Broadcasts DraftTurnChangedEvent so clients can update their UI.
        """
        if self._state.is_completed:
            await self._complete_draft()
            return

        current_manager = self._state.current_manager_id
        assert current_manager is not None

        await self._broadcast(DraftTurnChangedEvent(
            league_id=self._state.league_id,
            current_pick_number=self._state.current_pick_number,
            current_manager_id=current_manager,
            pick_duration=self._state.pick_duration,
            turn_started_at=time.time(),
        ))

        # In assisted mode: no timer, no autodraft — commissioner enters picks
        if self._state.assisted_mode:
            logger.debug(
                "Pick %d: assisted mode — waiting for commissioner input (manager '%s')",
                self._state.current_pick_number,
                current_manager,
            )
            return

        if current_manager in self._state.autodraft_managers:
            logger.debug(
                "Pick %d: manager '%s' is in autodraft — scheduling pick",
                self._state.current_pick_number,
                current_manager,
            )
            asyncio.create_task(self._run_autodraft_for_current_pick())
        else:
            self._current_timer = DraftTimer(
                duration=self._state.pick_duration,
                on_expire=self._on_timer_expired,
            )
            self._current_timer.start()
            logger.debug(
                "Pick %d: timer started for manager '%s' (%.0fs)",
                self._state.current_pick_number,
                current_manager,
                self._state.pick_duration,
            )

    async def _on_timer_expired(self) -> None:
        """Callback fired by DraftTimer when the pick time runs out."""
        async with self._lock:
            if self._state.status != DraftStatus.IN_PROGRESS:
                return

            # In assisted mode the timer should never be running — guard anyway
            if self._state.assisted_mode:
                return

            current_manager = self._state.current_manager_id
            if current_manager is None:
                return

            logger.info(
                "Pick %d: timer expired for manager '%s' — triggering autodraft",
                self._state.current_pick_number,
                current_manager,
            )

            # Mark manager as autodraft for all remaining picks (CDC 7.3)
            self._state.autodraft_managers.add(current_manager)
            await self._run_autodraft_for_current_pick()

    async def _run_autodraft_for_current_pick(self) -> None:
        """Execute autodraft for the current pick slot."""
        current_manager = self._state.current_manager_id
        assert current_manager is not None

        roster = self._state.rosters[current_manager]
        preference_list = self._preference_lists.get(current_manager, [])

        try:
            result: AutodraftResult = select_autodraft_pick(
                manager_id=current_manager,
                preference_list=preference_list,
                available_players=self._available_players,
                roster=roster,
                competition_type=self._state.competition_type,
            )
        except AutodraftError as exc:
            logger.error(
                "AutodraftError on pick %d for manager '%s': %s",
                self._state.current_pick_number,
                current_manager,
                exc,
            )
            raise

        record = self._record_pick(
            player_id=result.player_id,
            player=result.player,
            autodrafted=True,
            autodraft_source=result.source,
        )

        await self._broadcast(DraftPickMadeEvent(
            league_id=self._state.league_id,
            pick_number=record.pick_number,
            manager_id=record.manager_id,
            player_id=record.player_id,
            autodrafted=True,
            autodraft_source=result.source,
        ))
        await self._advance_to_next_turn()

    async def _advance_to_next_turn(self) -> None:
        """Increment the pick counter and start the next turn."""
        self._state.current_pick_number += 1

        if self._state.is_completed:
            await self._complete_draft()
        else:
            await self._start_current_turn()

    async def _complete_draft(self) -> None:
        """Mark the draft as completed and broadcast the final state."""
        self._state.status = DraftStatus.COMPLETED
        self._current_timer = None
        logger.info(
            "Draft completed: league=%s, total_picks=%d, assisted_mode=%s",
            self._state.league_id,
            len(self._state.picks),
            self._state.assisted_mode,
        )
        await self._broadcast(DraftCompletedEvent(
            league_id=self._state.league_id,
            total_picks=len(self._state.picks),
        ))

    # ------------------------------------------------------------------
    # Internal — state mutation helpers
    # ------------------------------------------------------------------

    def _record_pick(
        self,
        player_id: str,
        player: PlayerSummary,
        autodrafted: bool,
        autodraft_source: Optional[str] = None,
        entered_by_commissioner: bool = False,  # NEW
    ) -> PickRecord:
        """Record a pick and update all derived state."""
        current_manager = self._state.current_manager_id
        assert current_manager is not None

        loop = asyncio.get_event_loop()
        record = PickRecord(
            pick_number=self._state.current_pick_number,
            manager_id=current_manager,
            player_id=player_id,
            autodrafted=autodrafted,
            autodraft_source=autodraft_source,
            entered_by_commissioner=entered_by_commissioner,
            timestamp=loop.time(),
        )
        self._state.picks.append(record)

        # Update global drafted set
        self._state.drafted_player_ids = (
            self._state.drafted_player_ids | {player_id}
        )

        # Remove from available pool
        self._available_players = [
            p for p in self._available_players if str(p.id) != player_id
        ]

        # Update this manager's roster snapshot
        old_roster = self._state.rosters[current_manager]
        self._state.rosters[current_manager] = RosterSnapshot(
            manager_id=current_manager,
            player_ids=old_roster.player_ids | {player_id},
            nationalities=old_roster.nationalities + [player.nationality],
            clubs=old_roster.clubs + [player.club],
        )

        logger.info(
            "Pick %d recorded: manager='%s' player='%s' autodrafted=%s commissioner=%s",
            record.pick_number,
            current_manager,
            player_id,
            autodrafted,
            entered_by_commissioner,
        )

        return record

    def _get_available_player(self, player_id: str) -> PlayerSummary:
        """Look up a player in the available pool by ID."""
        from draft.validate_pick import PlayerAlreadyDraftedError

        for player in self._available_players:
            if str(player.id) == player_id:
                return player
        raise PlayerAlreadyDraftedError(player_id)

    # ------------------------------------------------------------------
    # Internal — broadcast
    # ------------------------------------------------------------------

    async def _broadcast(self, event: DraftEvent) -> None:
        """Forward a typed event to the broadcaster.

        A broadcast failure must NEVER crash the draft — the client
        can always call GET /draft/{id}/state for a full snapshot.

        Args:
            event: A typed DraftEvent subclass to send.
        """
        await self._broadcaster.broadcast(event)