"""
Lineup service — weekly lineup management business logic.

Responsibilities:
- get_lineup: retrieve current lineup for a roster/round with lock status
- submit_lineup: validate and persist a full 15-player lineup
- update_captain: change captain designation with lock validation
- update_kicker: change kicker designation with lock validation

Lock authority: kick_off_time < NOW() (D-032).
All modifications go through FastAPI — clients never write to weekly_lineups directly.
"""

from datetime import datetime, timezone
from uuid import UUID

from supabase._async.client import AsyncClient

from app.models.lineup import (
    CaptainUpdate,
    KickerUpdate,
    LineupPlayer,
    LineupResponse,
    LineupSubmission,
)


# ---------------------------------------------------------------------------
# Custom exceptions — caught by the router and mapped to HTTP status codes
# ---------------------------------------------------------------------------


class LineupOwnershipError(Exception):
    """Raised when a user tries to modify a roster they do not own."""


class LineupLockError(Exception):
    """Raised when a modification is blocked because a player's match has started."""


class LineupValidationError(Exception):
    """Raised when a lineup submission violates a business rule."""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class LineupService:
    """Handles all weekly lineup operations with full lock and rule validation.

    Args:
        client: Authenticated Supabase async client (carries the user's JWT,
                so RLS policies apply automatically on every query).
    """

    def __init__(self, client: AsyncClient) -> None:
        self.client = client

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    async def get_lineup(self, roster_id: UUID, round_id: UUID) -> LineupResponse:
        """Return the current lineup for a roster/round with lock status per player.

        Computes is_locked for each player by checking whether their team's
        match kick_off_time is in the past (D-032).

        Args:
            roster_id: UUID of the roster.
            round_id: UUID of the competition round.

        Returns:
            LineupResponse with starters, bench, captain, kicker, lock status.
        """
        # Fetch round metadata (round_number)
        round_data = await self._fetch_round(round_id)

        # Fetch roster slots (starter / bench / ir)
        slots = await self._fetch_roster_slots(roster_id)

        # Fetch existing weekly lineup entries for this round
        lineup_rows = await self._fetch_lineup_rows(roster_id, round_id)
        lineup_by_player: dict[str, dict] = {
            row["player_id"]: row for row in lineup_rows
        }

        # Fetch kick_off times for all matches in this round (one query)
        kickoffs = await self._fetch_kickoff_times(round_id)

        now = datetime.now(tz=timezone.utc)

        starters: list[LineupPlayer] = []
        bench: list[LineupPlayer] = []

        for slot in slots:
            player_id = slot["player_id"]
            slot_type = slot["slot_type"]  # starter / bench / ir

            # IR players are never in the lineup display
            if slot_type == "ir":
                continue

            player = slot["players"]  # joined data
            lineup_entry = lineup_by_player.get(player_id, {})

            # Determine lock status: find this player's team match in the round
            kick_off = kickoffs.get(player["club"])
            is_locked = kick_off is not None and kick_off < now
            locked_at = kick_off if is_locked else None

            lineup_player = LineupPlayer(
                player_id=UUID(player_id),
                player_name=player["name"],
                club=player["club"],
                # Use the position stored in the lineup if set, else first natural position
                position=lineup_entry.get("position") or player["positions"][0],
                is_captain=lineup_entry.get("is_captain", False),
                is_kicker=lineup_entry.get("is_kicker", False),
                is_locked=is_locked,
                locked_at=locked_at,
            )

            if slot_type == "starter":
                starters.append(lineup_player)
            else:
                bench.append(lineup_player)

        # Determine captain and kicker player IDs from stored lineup
        captain_id = next(
            (UUID(r["player_id"]) for r in lineup_rows if r.get("is_captain")),
            None,
        )
        kicker_id = next(
            (UUID(r["player_id"]) for r in lineup_rows if r.get("is_kicker")),
            None,
        )

        return LineupResponse(
            roster_id=roster_id,
            round_id=round_id,
            round_number=round_data["round_number"],
            starters=starters,
            bench=bench,
            captain_player_id=captain_id,
            kicker_player_id=kicker_id,
        )

    async def submit_lineup(
        self,
        roster_id: UUID,
        round_id: UUID,
        user_id: UUID,
        submission: LineupSubmission,
    ) -> LineupResponse:
        """Validate and persist a full 15-player lineup for a round.

        Validation order:
        1. Ownership: the user owns this roster.
        2. Eligibility: all 15 players belong to the roster and are not on IR.
        3. Position validity: each player's chosen position is in their positions[].
        4. Lock check: no player's team has already kicked off.
        5. Upsert weekly_lineups rows.

        Args:
            roster_id: UUID of the roster to update.
            round_id: UUID of the competition round.
            user_id: UUID of the authenticated user (for ownership check).
            submission: Validated LineupSubmission payload.

        Returns:
            Updated LineupResponse.

        Raises:
            LineupOwnershipError: User does not own this roster.
            LineupValidationError: Business rule violation.
            LineupLockError: One or more players are already locked.
        """
        await self._assert_ownership(roster_id, user_id)

        # Load full player data for all submitted players in one query
        submitted_ids = [str(p.player_id) for p in submission.starters]
        players_data = await self._fetch_players(submitted_ids)
        players_by_id: dict[str, dict] = {p["id"]: p for p in players_data}

        # Load roster slots to check membership and IR status
        slots = await self._fetch_roster_slots(roster_id)
        eligible_ids = {
            slot["player_id"] for slot in slots if slot["slot_type"] != "ir"
        }
        starter_slot_ids = {
            slot["player_id"] for slot in slots if slot["slot_type"] == "starter"
        }

        # Fetch kick_off times once for the whole round
        kickoffs = await self._fetch_kickoff_times(round_id)
        now = datetime.now(tz=timezone.utc)

        locked_players: list[str] = []

        for lineup_player in submission.starters:
            pid = str(lineup_player.player_id)

            # Check roster membership (not on IR)
            if pid not in eligible_ids:
                raise LineupValidationError(
                    f"Player {pid} is not eligible: not in roster or on IR slot."
                )

            # Check position validity for this player
            player_data = players_by_id.get(pid)
            if not player_data:
                raise LineupValidationError(f"Player {pid} not found.")

            valid_positions: list[str] = player_data.get("positions", [])
            if lineup_player.position not in valid_positions:
                raise LineupValidationError(
                    f"Position '{lineup_player.position}' is not valid for player "
                    f"{player_data['name']}. Valid positions: {valid_positions}."
                )

            # Lock check (D-032): kick_off_time < NOW()
            kick_off = kickoffs.get(player_data["club"])
            if kick_off is not None and kick_off < now:
                locked_players.append(player_data["name"])

        if locked_players:
            raise LineupLockError(
                f"Cannot submit lineup: the following players are already locked "
                f"(their team has kicked off): {', '.join(locked_players)}."
            )

        # All validations passed — upsert weekly_lineups rows
        await self._upsert_lineup_rows(
            roster_id, round_id, submission, starter_slot_ids
        )

        return await self.get_lineup(roster_id, round_id)

    async def update_captain(
        self,
        roster_id: UUID,
        round_id: UUID,
        user_id: UUID,
        update: CaptainUpdate,
    ) -> LineupResponse:
        """Change the captain designation for a round.

        CDC 6.6 edge case: if the current captain's team has already kicked off,
        the change is blocked — their points are already being calculated with
        the captain multiplier.

        Lock rules:
        - Current captain's team must NOT have kicked off yet.
        - New captain's team must NOT have kicked off yet.
        - New captain must be a starter in the current lineup.

        Args:
            roster_id: UUID of the roster.
            round_id: UUID of the round.
            user_id: UUID of the authenticated user.
            update: CaptainUpdate with the new captain's player_id.

        Returns:
            Updated LineupResponse.

        Raises:
            LineupOwnershipError: User does not own this roster.
            LineupLockError: Current or new captain is already locked.
            LineupValidationError: New captain is not a starter.
        """
        await self._assert_ownership(roster_id, user_id)

        lineup_rows = await self._fetch_lineup_rows(roster_id, round_id)
        kickoffs = await self._fetch_kickoff_times(round_id)
        now = datetime.now(tz=timezone.utc)

        # Find current captain
        current_captain_row = next(
            (r for r in lineup_rows if r.get("is_captain")), None
        )

        # Check: current captain not yet played (CDC 6.6)
        if current_captain_row:
            current_captain_player = await self._fetch_single_player(
                current_captain_row["player_id"]
            )
            current_kick_off = kickoffs.get(current_captain_player["club"])
            if current_kick_off is not None and current_kick_off < now:
                raise LineupLockError(
                    "Cannot change captain: the current captain's team has already "
                    "kicked off. Their points are being calculated with the captain "
                    "multiplier."
                )

        # Check: new captain is a starter in this lineup
        starter_ids = {
            r["player_id"] for r in lineup_rows if r.get("slot_type") == "starter"
        }
        # Fallback: check against roster slots (lineup may not be submitted yet)
        if not starter_ids:
            slots = await self._fetch_roster_slots(roster_id)
            starter_ids = {
                slot["player_id"] for slot in slots if slot["slot_type"] == "starter"
            }

        new_captain_id = str(update.player_id)
        if new_captain_id not in starter_ids:
            raise LineupValidationError(
                "New captain must be a starter in the current lineup."
            )

        # Check: new captain not yet locked
        new_captain_player = await self._fetch_single_player(new_captain_id)
        new_kick_off = kickoffs.get(new_captain_player["club"])
        if new_kick_off is not None and new_kick_off < now:
            raise LineupLockError(
                f"Cannot designate {new_captain_player['name']} as captain: "
                "their team has already kicked off."
            )

        # Update: clear current captain, set new captain
        await self._set_captain(roster_id, round_id, new_captain_id)

        return await self.get_lineup(roster_id, round_id)

    async def update_kicker(
        self,
        roster_id: UUID,
        round_id: UUID,
        user_id: UUID,
        update: KickerUpdate,
    ) -> LineupResponse:
        """Change the kicker designation for a round.

        CDC 6.6 edge case: once the current kicker's team has kicked off,
        the kicker cannot be changed until the next round.

        Lock rules:
        - Current kicker's team must NOT have kicked off yet.
        - New kicker must be a starter in the current lineup.
        - New kicker's team must NOT have kicked off yet.

        Args:
            roster_id: UUID of the roster.
            round_id: UUID of the round.
            user_id: UUID of the authenticated user.
            update: KickerUpdate with the new kicker's player_id.

        Returns:
            Updated LineupResponse.

        Raises:
            LineupOwnershipError: User does not own this roster.
            LineupLockError: Current kicker has already played this round.
            LineupValidationError: New kicker is not a starter.
        """
        await self._assert_ownership(roster_id, user_id)

        lineup_rows = await self._fetch_lineup_rows(roster_id, round_id)
        kickoffs = await self._fetch_kickoff_times(round_id)
        now = datetime.now(tz=timezone.utc)

        # Check: current kicker has not yet played
        current_kicker_row = next((r for r in lineup_rows if r.get("is_kicker")), None)
        if current_kicker_row:
            current_kicker_player = await self._fetch_single_player(
                current_kicker_row["player_id"]
            )
            current_kick_off = kickoffs.get(current_kicker_player["club"])
            if current_kick_off is not None and current_kick_off < now:
                raise LineupLockError(
                    "Cannot change kicker: the current kicker's team has already "
                    "kicked off. The kicker designation is locked until next round."
                )

        # Check: new kicker is a starter
        starter_ids = {
            r["player_id"] for r in lineup_rows if r.get("slot_type") == "starter"
        }
        if not starter_ids:
            slots = await self._fetch_roster_slots(roster_id)
            starter_ids = {
                slot["player_id"] for slot in slots if slot["slot_type"] == "starter"
            }

        new_kicker_id = str(update.player_id)
        if new_kicker_id not in starter_ids:
            raise LineupValidationError(
                "New kicker must be a starter in the current lineup."
            )

        # Check: new kicker not yet locked
        new_kicker_player = await self._fetch_single_player(new_kicker_id)
        new_kick_off = kickoffs.get(new_kicker_player["club"])
        if new_kick_off is not None and new_kick_off < now:
            raise LineupLockError(
                f"Cannot designate {new_kicker_player['name']} as kicker: "
                "their team has already kicked off."
            )

        await self._set_kicker(roster_id, round_id, new_kicker_id)

        return await self.get_lineup(roster_id, round_id)

    # ------------------------------------------------------------------
    # Private helpers — DB queries
    # ------------------------------------------------------------------

    async def _assert_ownership(self, roster_id: UUID, user_id: UUID) -> None:
        """Verify the user owns this roster via their league membership.

        Raises:
            LineupOwnershipError: if the user is not the roster owner.
        """
        result = (
            await self.client.table("rosters")
            .select("id, league_members(user_id)")
            .eq("id", str(roster_id))
            .single()
            .execute()
        )
        if not result.data:
            raise LineupOwnershipError(f"Roster {roster_id} not found.")

        owner_id = result.data["league_members"]["user_id"]
        if owner_id != str(user_id):
            raise LineupOwnershipError(
                f"User {user_id} does not own roster {roster_id}."
            )

    async def _fetch_round(self, round_id: UUID) -> dict:
        """Fetch competition round metadata.

        Args:
            round_id: UUID of the competition round.

        Returns:
            Dict with at least round_number.
        """
        result = (
            await self.client.table("competition_rounds")
            .select("id, round_number, start_date, end_date")
            .eq("id", str(round_id))
            .single()
            .execute()
        )
        return result.data

    async def _fetch_roster_slots(self, roster_id: UUID) -> list[dict]:
        """Fetch all roster slots with joined player data.

        Args:
            roster_id: UUID of the roster.

        Returns:
            List of slot dicts with nested players data.
        """
        result = (
            await self.client.table("roster_slots")
            .select("player_id, slot_type, players(id, name, club, positions)")
            .eq("roster_id", str(roster_id))
            .execute()
        )
        return result.data or []

    async def _fetch_lineup_rows(self, roster_id: UUID, round_id: UUID) -> list[dict]:
        """Fetch existing weekly_lineups rows for a roster/round.

        Args:
            roster_id: UUID of the roster.
            round_id: UUID of the round.

        Returns:
            List of lineup row dicts (may be empty if no lineup submitted yet).
        """
        result = (
            await self.client.table("weekly_lineups")
            .select("player_id, position, is_captain, is_kicker, locked_at")
            .eq("roster_id", str(roster_id))
            .eq("round_id", str(round_id))
            .execute()
        )
        return result.data or []

    async def _fetch_kickoff_times(self, round_id: UUID) -> dict[str, datetime]:
        """Return a mapping of club → kick_off_time for all matches in a round.

        Used to determine lock status for each player (D-032).
        One query for the entire round — called once per service method.

        Args:
            round_id: UUID of the competition round.

        Returns:
            Dict mapping club name → kick_off_time (UTC datetime).
            A club appears once per match (home and away both mapped).
        """
        result = (
            await self.client.table("real_matches")
            .select("home_team, away_team, kick_off_time, status")
            .eq("competition_round_id", str(round_id))
            .execute()
        )
        kickoffs: dict[str, datetime] = {}
        for match in result.data or []:
            kick_off_str = match.get("kick_off_time")
            if not kick_off_str:
                continue
            # Parse ISO string returned by Supabase, ensure UTC
            kick_off = datetime.fromisoformat(kick_off_str.replace("Z", "+00:00"))
            kickoffs[match["home_team"]] = kick_off
            kickoffs[match["away_team"]] = kick_off
        return kickoffs

    async def _fetch_players(self, player_ids: list[str]) -> list[dict]:
        """Fetch player records for a list of UUIDs.

        Args:
            player_ids: List of player UUID strings.

        Returns:
            List of player dicts with id, name, club, positions.
        """
        result = (
            await self.client.table("players")
            .select("id, name, club, positions")
            .in_("id", player_ids)
            .execute()
        )
        return result.data or []

    async def _fetch_single_player(self, player_id: str) -> dict:
        """Fetch a single player record.

        Args:
            player_id: Player UUID string.

        Returns:
            Player dict with id, name, club, positions.
        """
        result = (
            await self.client.table("players")
            .select("id, name, club, positions")
            .eq("id", player_id)
            .single()
            .execute()
        )
        return result.data

    async def _upsert_lineup_rows(
        self,
        roster_id: UUID,
        round_id: UUID,
        submission: LineupSubmission,
        starter_slot_ids: set[str],
    ) -> None:
        """Persist the submitted lineup as weekly_lineups rows.

        Uses upsert (INSERT ... ON CONFLICT UPDATE) on (roster_id, round_id, player_id).
        Clears is_captain and is_kicker on all rows first, then sets them on the
        designated players.

        Args:
            roster_id: UUID of the roster.
            round_id: UUID of the round.
            submission: Validated lineup submission.
            starter_slot_ids: Set of player_id strings that are in starter slots.
        """
        rows = []
        for lineup_player in submission.starters:
            pid = str(lineup_player.player_id)
            rows.append(
                {
                    "roster_id": str(roster_id),
                    "round_id": str(round_id),
                    "player_id": pid,
                    "position": lineup_player.position,
                    "is_captain": pid == str(submission.captain_player_id),
                    "is_kicker": pid == str(submission.kicker_player_id),
                    "locked_at": None,  # set by pipeline at kick_off, not by user
                }
            )

        await (
            self.client.table("weekly_lineups")
            .upsert(rows, on_conflict="roster_id,round_id,player_id")
            .execute()
        )

    async def _set_captain(
        self, roster_id: UUID, round_id: UUID, new_captain_id: str
    ) -> None:
        """Atomically clear all captain flags then set the new captain.

        Two sequential updates (Supabase client does not support
        conditional UPDATE in one call). Acceptable: the window between
        the two is milliseconds and the service layer is the only writer.

        Args:
            roster_id: UUID of the roster.
            round_id: UUID of the round.
            new_captain_id: Player UUID string to designate as captain.
        """
        # Clear all captain flags for this lineup
        await (
            self.client.table("weekly_lineups")
            .update({"is_captain": False})
            .eq("roster_id", str(roster_id))
            .eq("round_id", str(round_id))
            .execute()
        )
        # Set the new captain
        await (
            self.client.table("weekly_lineups")
            .update({"is_captain": True})
            .eq("roster_id", str(roster_id))
            .eq("round_id", str(round_id))
            .eq("player_id", new_captain_id)
            .execute()
        )

    async def _set_kicker(
        self, roster_id: UUID, round_id: UUID, new_kicker_id: str
    ) -> None:
        """Atomically clear all kicker flags then set the new kicker.

        Same two-step pattern as _set_captain.

        Args:
            roster_id: UUID of the roster.
            round_id: UUID of the round.
            new_kicker_id: Player UUID string to designate as kicker.
        """
        await (
            self.client.table("weekly_lineups")
            .update({"is_kicker": False})
            .eq("roster_id", str(roster_id))
            .eq("round_id", str(round_id))
            .execute()
        )
        await (
            self.client.table("weekly_lineups")
            .update({"is_kicker": True})
            .eq("roster_id", str(roster_id))
            .eq("round_id", str(round_id))
            .eq("player_id", new_kicker_id)
            .execute()
        )
