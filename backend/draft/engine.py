# backend/draft/engine.py
"""
DraftEngine — authority of state for the RugbyDraft snake draft.

This is the central orchestrator of Phase 2. It wires together:
    - snake_order.py  — pick ordering
    - timer.py        — server-side countdown
    - validate_pick.py — pick validation
    - autodraft.py    — automatic pick selection

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

Broadcast (Supabase Realtime):
    _broadcast() is a stub in Phase 2. It will be wired to Supabase
    Realtime in the next step. All state-changing methods call it so
    the wiring is already in place.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Optional

from app.models.league import CompetitionType
from app.models.player import PlayerSummary
from draft.autodraft import AutodraftError, AutodraftResult, select_autodraft_pick
from draft.snake_order import generate_snake_order
from draft.timer import DEFAULT_PICK_DURATION_SECONDS, DraftTimer
from draft.validate_pick import (
    PickValidationError,
    RosterSnapshot,
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
        timestamp: asyncio loop time when the pick was recorded.
    """

    pick_number: int
    manager_id: str
    player_id: str
    autodrafted: bool = False
    autodraft_source: Optional[str] = None
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
    time_remaining: float                 # seconds, 0.0 if completed
    picks: list[PickRecord]
    autodraft_managers: list[str]
    connected_managers: list[str]


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
            pick_duration=120.0,
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
        pick_duration: float = DEFAULT_PICK_DURATION_SECONDS,
        preference_lists: Optional[dict[str, list[str]]] = None,
    ) -> None:
        """Initialise the DraftEngine. Does NOT start the draft.

        Call start_draft() explicitly to begin.

        Args:
            league_id: The league this draft belongs to.
            manager_ids: All manager IDs. Will be shuffled for the draw.
            available_players: Full player pool, pre-sorted by value_score desc.
            competition_type: International or club (determines constraints).
            pick_duration: Seconds per pick. Default: 120s (CDC v3.1).
            preference_lists: Optional dict of manager_id → ordered player IDs.
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

        # Current active timer — one per pick slot
        self._current_timer: Optional[DraftTimer] = None

        # Concurrency lock — prevents simultaneous pick submissions
        self._lock = asyncio.Lock()

        logger.info(
            "DraftEngine created: league=%s, managers=%s, total_picks=%d",
            league_id,
            shuffled,
            self._state.total_picks,
        )

    # ------------------------------------------------------------------
    # Public interface
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

            await self._broadcast()
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

            await self._broadcast()
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

            # Give control back if reconnecting during own turn before pick is made.
            # Two cases:
            #   1. Manual mode: timer is running (time_remaining > 0)
            #   2. Autodraft mode: create_task() was scheduled but not yet executed
            #      — detectable because current_manager_id is still this manager
            #      and no pick has been recorded for this pick_number yet.
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
                logger.info(
                    "Manager '%s' reconnected during their turn — autodraft deactivated",
                    manager_id,
                )
                # Start the timer now that manager is taking manual control
                self._current_timer = DraftTimer(
                    duration=self._state.pick_duration,
                    on_expire=self._on_timer_expired,
                )
                self._current_timer.start()

            await self._broadcast()
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
            await self._broadcast()

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
        )

    # ------------------------------------------------------------------
    # Internal — turn management
    # ------------------------------------------------------------------

    async def _start_current_turn(self) -> None:
        """Start the timer (or autodraft) for the current pick slot.

        If the current manager is in autodraft mode, execute autodraft
        immediately without starting a timer.
        """
        if self._state.is_completed:
            await self._complete_draft()
            return

        current_manager = self._state.current_manager_id
        assert current_manager is not None

        if current_manager in self._state.autodraft_managers:
            # Schedule autodraft as a new Task to avoid deep recursion
            # when all managers are in autodraft (up to 90 consecutive picks).
            # create_task() yields control back to the event loop between picks.
            logger.debug(
                "Pick %d: manager '%s' is in autodraft — scheduling pick",
                self._state.current_pick_number,
                current_manager,
            )
            asyncio.create_task(self._run_autodraft_for_current_pick())
        else:
            # Start the countdown timer for this pick slot
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
        """Callback fired by DraftTimer when the pick time runs out.

        Acquires the lock, triggers autodraft, marks the manager as
        autodraft for remaining picks, and advances to the next turn.
        """
        async with self._lock:
            if self._state.status != DraftStatus.IN_PROGRESS:
                # Draft completed or cancelled between timer start and expiry
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
        """Execute autodraft for the current pick slot.

        Must be called while the lock is held (or from within a
        method that already holds it).

        Selects a player via select_autodraft_pick(), records the pick,
        and advances to the next turn.
        """
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
            # Data integrity issue — log and halt the draft
            logger.error(
                "AutodraftError on pick %d for manager '%s': %s",
                self._state.current_pick_number,
                current_manager,
                exc,
            )
            raise

        self._record_pick(
            player_id=result.player_id,
            player=result.player,
            autodrafted=True,
            autodraft_source=result.source,
        )

        await self._broadcast()
        await self._advance_to_next_turn()

    async def _advance_to_next_turn(self) -> None:
        """Increment the pick counter and start the next turn.

        Must be called while the lock is held.
        """
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
            "Draft completed: league=%s, total_picks=%d",
            self._state.league_id,
            len(self._state.picks),
        )
        await self._broadcast()

    # ------------------------------------------------------------------
    # Internal — state mutation helpers
    # ------------------------------------------------------------------

    def _record_pick(
        self,
        player_id: str,
        player: PlayerSummary,
        autodrafted: bool,
        autodraft_source: Optional[str] = None,
    ) -> PickRecord:
        """Record a pick and update all derived state.

        Updates:
            - picks history
            - drafted_player_ids (adds player)
            - available_players (removes player)
            - rosters (adds player to current manager's roster)

        Args:
            player_id: The drafted player's ID.
            player: Full PlayerSummary.
            autodrafted: Whether this was an autodraft pick.
            autodraft_source: 'preference_list' or 'default_value', or None.

        Returns:
            The created PickRecord.
        """
        current_manager = self._state.current_manager_id
        assert current_manager is not None

        loop = asyncio.get_event_loop()
        record = PickRecord(
            pick_number=self._state.current_pick_number,
            manager_id=current_manager,
            player_id=player_id,
            autodrafted=autodrafted,
            autodraft_source=autodraft_source,
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
            "Pick %d recorded: manager='%s' player='%s' autodrafted=%s",
            record.pick_number,
            current_manager,
            player_id,
            autodrafted,
        )

        return record

    def _get_available_player(self, player_id: str) -> PlayerSummary:
        """Look up a player in the available pool by ID.

        Args:
            player_id: The player ID to look up.

        Returns:
            The PlayerSummary if found.

        Raises:
            PickValidationError (PlayerAlreadyDraftedError): If not in pool.
        """
        from draft.validate_pick import PlayerAlreadyDraftedError

        for player in self._available_players:
            if str(player.id) == player_id:
                return player
        raise PlayerAlreadyDraftedError(player_id)

    # ------------------------------------------------------------------
    # Internal — broadcast stub
    # ------------------------------------------------------------------

    async def _broadcast(self) -> None:
        """Broadcast current state to all connected clients.

        STUB — wired to Supabase Realtime in the next step.
        All state-changing methods call this so the integration
        point is already in place.
        """
        # TODO: wire to Supabase Realtime channel broadcast
        pass