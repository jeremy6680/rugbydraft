# tests/test_lineup.py
"""
Tests for weekly lineup management — service layer.

Covers:
- Starter/bench/IR slot validation
- Progressive lock (kick_off_time < NOW) via D-032
- Captain change rules (CDC 6.6)
- Kicker lock rules (CDC 6.6)
- Multi-position player validation
- Ownership enforcement

Strategy: mock the Supabase client entirely — no real DB calls.
All DB responses are controlled fixtures so tests are fast and deterministic.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.models.lineup import (
    CaptainUpdate,
    KickerUpdate,
    LineupPlayerInput,
    LineupSubmission,
)
from app.services.lineup_service import (
    LineupLockError,
    LineupService,
    LineupValidationError,
)

# ---------------------------------------------------------------------------
# Helpers — fixed UUIDs for reproducible tests
# ---------------------------------------------------------------------------

ROSTER_ID = uuid4()
ROUND_ID = uuid4()
USER_ID = uuid4()
LEAGUE_MEMBER_ID = uuid4()

PLAYER_DUPONT = uuid4()  # scrum-half, Toulouse — match at 15:00 (past)
PLAYER_NTAMACK = uuid4()  # fly-half, Toulouse — same match (past)
PLAYER_ALLDRITT = uuid4()  # number_8, La Rochelle — match at 17:00 (future)
PLAYER_PENAUD = uuid4()  # wing, Toulouse — same match as Dupont (past)
PLAYER_RAMOS = uuid4()  # multi-position: fly-half OR fullback, Toulouse

NOW = datetime(2030, 1, 1, 16, 0, 0, tzinfo=timezone.utc)
PAST_KICKOFF = NOW - timedelta(hours=1)  # 15:00 — Toulouse match already started
FUTURE_KICKOFF = NOW + timedelta(hours=1)  # 17:00 — La Rochelle not yet started


# ---------------------------------------------------------------------------
# Fixtures — mock Supabase client
# ---------------------------------------------------------------------------


def make_mock_client() -> MagicMock:
    """Return a MagicMock that mimics the supabase-py async client interface.

    Each .table().select().eq()...execute() chain is mocked to return
    a MagicMock with a .data attribute. Individual tests override .data
    as needed.
    """
    client = MagicMock()
    # Default: every query returns empty data
    execute_result = MagicMock()
    execute_result.data = []
    async_execute = AsyncMock(return_value=execute_result)

    # Make the full chain chainable and async at .execute()
    chain = MagicMock()
    chain.execute = async_execute
    chain.eq = MagicMock(return_value=chain)
    chain.in_ = MagicMock(return_value=chain)
    chain.single = MagicMock(return_value=chain)
    chain.update = MagicMock(return_value=chain)
    chain.upsert = MagicMock(return_value=chain)

    client.table = MagicMock(return_value=chain)
    client._chain = chain  # expose for per-test overrides
    return client


def make_roster_slots(include_ir: bool = False) -> list[dict]:
    """Return a standard set of roster slots for tests.

    15 starters + 8 bench. Optionally adds 1 IR slot.
    Uses a minimal subset of the full 23-man squad.
    """
    starters = [
        {
            "player_id": str(PLAYER_DUPONT),
            "slot_type": "starter",
            "players": {
                "id": str(PLAYER_DUPONT),
                "name": "Antoine Dupont",
                "club": "Toulouse",
                "positions": ["scrum_half"],
            },
        },
        {
            "player_id": str(PLAYER_NTAMACK),
            "slot_type": "starter",
            "players": {
                "id": str(PLAYER_NTAMACK),
                "name": "Romain Ntamack",
                "club": "Toulouse",
                "positions": ["fly_half"],
            },
        },
        {
            "player_id": str(PLAYER_RAMOS),
            "slot_type": "starter",
            "players": {
                "id": str(PLAYER_RAMOS),
                "name": "Thomas Ramos",
                "club": "Toulouse",
                "positions": ["fly_half", "fullback"],
            },
        },
        {
            "player_id": str(PLAYER_ALLDRITT),
            "slot_type": "starter",
            "players": {
                "id": str(PLAYER_ALLDRITT),
                "name": "Gregory Alldritt",
                "club": "La Rochelle",
                "positions": ["number_8"],
            },
        },
    ]
    # Pad to 15 starters with generic players
    for i in range(11):
        starters.append(
            {
                "player_id": str(uuid4()),
                "slot_type": "starter",
                "players": {
                    "id": str(uuid4()),
                    "name": f"Player {i}",
                    "club": "La Rochelle",
                    "positions": ["prop"],
                },
            }
        )
    bench = [
        {
            "player_id": str(uuid4()),
            "slot_type": "bench",
            "players": {
                "id": str(uuid4()),
                "name": f"Bench {i}",
                "club": "Bordeaux",
                "positions": ["prop"],
            },
        }
        for i in range(8)
    ]
    slots = starters + bench
    if include_ir:
        slots.append(
            {
                "player_id": str(PLAYER_PENAUD),
                "slot_type": "ir",
                "players": {
                    "id": str(PLAYER_PENAUD),
                    "name": "Damian Penaud",
                    "club": "Toulouse",
                    "positions": ["wing"],
                },
            }
        )
    return slots


def make_kickoffs() -> dict[str, datetime]:
    """Return kick_off_time mapping for test clubs."""
    return {
        "Toulouse": PAST_KICKOFF,  # already started
        "La Rochelle": FUTURE_KICKOFF,  # not yet started
        "Bordeaux": FUTURE_KICKOFF,
    }


def make_valid_submission(slots: list[dict]) -> LineupSubmission:
    """Build a valid LineupSubmission from the given roster slots.

    Uses the first starter as captain and kicker.
    """
    starters = [s for s in slots if s["slot_type"] == "starter"][:15]
    starter_inputs = [
        LineupPlayerInput(
            player_id=UUID(s["player_id"]),
            position=s["players"]["positions"][0],
        )
        for s in starters
    ]
    captain_id = UUID(starters[0]["player_id"])
    kicker_id = UUID(starters[0]["player_id"])
    return LineupSubmission(
        starters=starter_inputs,
        captain_player_id=captain_id,
        kicker_player_id=kicker_id,
    )


# ---------------------------------------------------------------------------
# Pydantic model tests (no DB needed)
# ---------------------------------------------------------------------------


class TestLineupSubmissionModel:
    """Test Pydantic validation on LineupSubmission."""

    def test_captain_not_in_starters_raises(self) -> None:
        """Captain must be in the starter list — Pydantic validator."""
        starters = [
            LineupPlayerInput(player_id=uuid4(), position="prop") for _ in range(15)
        ]
        with pytest.raises(ValueError, match="Captain must be in the starter list"):
            LineupSubmission(
                starters=starters,
                captain_player_id=uuid4(),  # not in starters
                kicker_player_id=starters[0].player_id,
            )

    def test_kicker_not_in_starters_raises(self) -> None:
        """Kicker must be in the starter list — Pydantic validator."""
        starters = [
            LineupPlayerInput(player_id=uuid4(), position="prop") for _ in range(15)
        ]
        with pytest.raises(ValueError, match="Kicker must be in the starter list"):
            LineupSubmission(
                starters=starters,
                captain_player_id=starters[0].player_id,
                kicker_player_id=uuid4(),  # not in starters
            )

    def test_fewer_than_15_starters_raises(self) -> None:
        """Exactly 15 starters required."""
        starters = [
            LineupPlayerInput(player_id=uuid4(), position="prop") for _ in range(14)
        ]
        with pytest.raises(ValueError):
            LineupSubmission(
                starters=starters,
                captain_player_id=starters[0].player_id,
                kicker_player_id=starters[0].player_id,
            )

    def test_valid_submission_passes(self) -> None:
        """A correctly formed submission should not raise."""
        starters = [
            LineupPlayerInput(player_id=uuid4(), position="prop") for _ in range(15)
        ]
        submission = LineupSubmission(
            starters=starters,
            captain_player_id=starters[0].player_id,
            kicker_player_id=starters[1].player_id,
        )
        assert len(submission.starters) == 15


# ---------------------------------------------------------------------------
# Service tests — lock validation (D-032)
# ---------------------------------------------------------------------------


class TestLockValidation:
    """Test progressive lock logic: kick_off_time < NOW."""

    @pytest.mark.asyncio
    async def test_submit_lineup_with_locked_player_raises(self) -> None:
        """Submitting a lineup when any player's team has kicked off must raise LineupLockError."""
        slots = make_roster_slots()
        # Submission includes Dupont (Toulouse — PAST_KICKOFF)
        submission = make_valid_submission(slots)

        service = LineupService(client=make_mock_client())

        # Mock all DB calls
        with (
            patch.object(service, "_assert_ownership", new=AsyncMock()),
            patch.object(
                service,
                "_fetch_players",
                new=AsyncMock(
                    return_value=[
                        {
                            "id": str(s["player_id"]),
                            "name": s["players"]["name"],
                            "club": s["players"]["club"],
                            "positions": s["players"]["positions"],
                        }
                        for s in slots
                        if s["slot_type"] == "starter"
                    ]
                ),
            ),
            patch.object(
                service, "_fetch_roster_slots", new=AsyncMock(return_value=slots)
            ),
            patch.object(
                service,
                "_fetch_kickoff_times",
                new=AsyncMock(return_value=make_kickoffs()),
            ),
            patch("app.services.lineup_service.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = NOW
            mock_dt.fromisoformat = datetime.fromisoformat

            with pytest.raises(LineupLockError, match="already locked"):
                await service.submit_lineup(
                    roster_id=ROSTER_ID,
                    round_id=ROUND_ID,
                    user_id=USER_ID,
                    submission=submission,
                )

    @pytest.mark.asyncio
    async def test_submit_lineup_all_future_kickoffs_passes(self) -> None:
        """Submitting a lineup when all teams haven't kicked off yet must succeed."""
        slots = make_roster_slots()
        # Replace Toulouse players with La Rochelle (future kick_off)
        for slot in slots:
            slot["players"]["club"] = "La Rochelle"
        submission = make_valid_submission(slots)

        service = LineupService(client=make_mock_client())

        with (
            patch.object(service, "_assert_ownership", new=AsyncMock()),
            patch.object(
                service,
                "_fetch_players",
                new=AsyncMock(
                    return_value=[
                        {
                            "id": str(s["player_id"]),
                            "name": s["players"]["name"],
                            "club": "La Rochelle",
                            "positions": s["players"]["positions"],
                        }
                        for s in slots
                        if s["slot_type"] == "starter"
                    ]
                ),
            ),
            patch.object(
                service, "_fetch_roster_slots", new=AsyncMock(return_value=slots)
            ),
            patch.object(
                service,
                "_fetch_kickoff_times",
                new=AsyncMock(return_value=make_kickoffs()),
            ),
            patch.object(service, "_upsert_lineup_rows", new=AsyncMock()),
            patch.object(service, "get_lineup", new=AsyncMock()),
            patch("app.services.lineup_service.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = NOW
            mock_dt.fromisoformat = datetime.fromisoformat

            # Should not raise
            await service.submit_lineup(
                roster_id=ROSTER_ID,
                round_id=ROUND_ID,
                user_id=USER_ID,
                submission=submission,
            )


# ---------------------------------------------------------------------------
# Service tests — IR player exclusion
# ---------------------------------------------------------------------------


class TestIRExclusion:
    """IR players cannot be submitted as starters."""

    @pytest.mark.asyncio
    async def test_ir_player_in_starter_list_raises(self) -> None:
        """A player on IR slot must be rejected from the starter list."""
        slots = make_roster_slots(include_ir=True)

        # Build a submission that tries to include the IR player (Penaud)
        starters = [s for s in slots if s["slot_type"] == "starter"][:14]
        # Add the IR player as the 15th starter
        ir_slot = next(s for s in slots if s["slot_type"] == "ir")
        starters.append(ir_slot)

        starter_inputs = [
            LineupPlayerInput(
                player_id=UUID(s["player_id"]),
                position=s["players"]["positions"][0],
            )
            for s in starters
        ]
        submission = LineupSubmission(
            starters=starter_inputs,
            captain_player_id=UUID(starters[0]["player_id"]),
            kicker_player_id=UUID(starters[0]["player_id"]),
        )

        service = LineupService(client=make_mock_client())

        with (
            patch.object(service, "_assert_ownership", new=AsyncMock()),
            patch.object(
                service, "_fetch_roster_slots", new=AsyncMock(return_value=slots)
            ),
            patch.object(
                service,
                "_fetch_players",
                new=AsyncMock(
                    return_value=[
                        {
                            "id": str(s["player_id"]),
                            "name": s["players"]["name"],
                            "club": s["players"]["club"],
                            "positions": s["players"]["positions"],
                        }
                        for s in starters
                    ]
                ),
            ),
            patch.object(
                service,
                "_fetch_kickoff_times",
                new=AsyncMock(return_value=make_kickoffs()),
            ),
        ):
            with pytest.raises(LineupValidationError, match="not eligible"):
                await service.submit_lineup(
                    roster_id=ROSTER_ID,
                    round_id=ROUND_ID,
                    user_id=USER_ID,
                    submission=submission,
                )


# ---------------------------------------------------------------------------
# Service tests — multi-position validation
# ---------------------------------------------------------------------------


class TestMultiPosition:
    """Position choice must be in the player's positions[] array."""

    @pytest.mark.asyncio
    async def test_invalid_position_for_multiposition_player_raises(self) -> None:
        """Thomas Ramos can play fly_half or fullback — not prop."""
        slots = make_roster_slots()
        starters = [s for s in slots if s["slot_type"] == "starter"][:15]

        starter_inputs = []
        for s in starters:
            # Force Ramos into an invalid position
            if s["player_id"] == str(PLAYER_RAMOS):
                pos = "prop"  # not in ["fly_half", "fullback"]
            else:
                pos = s["players"]["positions"][0]
            starter_inputs.append(
                LineupPlayerInput(player_id=UUID(s["player_id"]), position=pos)
            )

        submission = LineupSubmission(
            starters=starter_inputs,
            captain_player_id=UUID(starters[0]["player_id"]),
            kicker_player_id=UUID(starters[0]["player_id"]),
        )

        service = LineupService(client=make_mock_client())

        with (
            patch.object(service, "_assert_ownership", new=AsyncMock()),
            patch.object(
                service, "_fetch_roster_slots", new=AsyncMock(return_value=slots)
            ),
            patch.object(
                service,
                "_fetch_players",
                new=AsyncMock(
                    return_value=[
                        {
                            "id": str(s["player_id"]),
                            "name": s["players"]["name"],
                            "club": s["players"]["club"],
                            "positions": s["players"]["positions"],
                        }
                        for s in starters
                    ]
                ),
            ),
            patch.object(
                service,
                "_fetch_kickoff_times",
                new=AsyncMock(return_value=make_kickoffs()),
            ),
        ):
            with pytest.raises(LineupValidationError, match="not valid for player"):
                await service.submit_lineup(
                    roster_id=ROSTER_ID,
                    round_id=ROUND_ID,
                    user_id=USER_ID,
                    submission=submission,
                )

    @pytest.mark.asyncio
    async def test_valid_position_for_multiposition_player_passes(self) -> None:
        """Thomas Ramos playing fullback is valid."""
        slots = make_roster_slots()

        # Patch all clubs to La Rochelle (FUTURE_KICKOFF) at the slot level
        # so the lock check sees no locked players.
        slots_la_rochelle = [
            {**slot, "players": {**slot["players"], "club": "La Rochelle"}}
            for slot in slots
        ]

        starters = [s for s in slots_la_rochelle if s["slot_type"] == "starter"][:15]
        starter_inputs = [
            LineupPlayerInput(
                player_id=UUID(s["player_id"]),
                position="fullback"
                if s["player_id"] == str(PLAYER_RAMOS)
                else s["players"]["positions"][0],
            )
            for s in starters
        ]
        submission = LineupSubmission(
            starters=starter_inputs,
            captain_player_id=UUID(starters[0]["player_id"]),
            kicker_player_id=UUID(starters[0]["player_id"]),
        )

        service = LineupService(client=make_mock_client())

        with (
            patch.object(service, "_assert_ownership", new=AsyncMock()),
            patch.object(
                service,
                "_fetch_roster_slots",
                new=AsyncMock(return_value=slots_la_rochelle),
            ),
            patch.object(
                service,
                "_fetch_players",
                new=AsyncMock(
                    return_value=[
                        {
                            "id": str(s["player_id"]),
                            "name": s["players"]["name"],
                            "club": "La Rochelle",
                            "positions": s["players"]["positions"],
                        }
                        for s in starters
                    ]
                ),
            ),
            patch.object(
                service,
                "_fetch_kickoff_times",
                new=AsyncMock(return_value=make_kickoffs()),
            ),
            patch.object(service, "_upsert_lineup_rows", new=AsyncMock()),
            patch.object(service, "get_lineup", new=AsyncMock()),
        ):
            await service.submit_lineup(
                roster_id=ROSTER_ID,
                round_id=ROUND_ID,
                user_id=USER_ID,
                submission=submission,
            )


# ---------------------------------------------------------------------------
# Service tests — captain update (CDC 6.6)
# ---------------------------------------------------------------------------


class TestCaptainUpdate:
    """Captain change rules from CDC section 6.6."""

    @pytest.mark.asyncio
    async def test_change_captain_when_current_captain_played_raises(self) -> None:
        """Cannot change captain if the current captain's team has already kicked off."""
        # Current captain is Dupont (Toulouse — PAST_KICKOFF)
        lineup_rows = [
            {"player_id": str(PLAYER_DUPONT), "is_captain": True, "is_kicker": False},
            {
                "player_id": str(PLAYER_ALLDRITT),
                "is_captain": False,
                "is_kicker": False,
            },
        ]
        dupont_data = {
            "id": str(PLAYER_DUPONT),
            "name": "Antoine Dupont",
            "club": "Toulouse",
            "positions": ["scrum_half"],
        }
        service = LineupService(client=make_mock_client())

        with (
            patch.object(service, "_assert_ownership", new=AsyncMock()),
            patch.object(
                service, "_fetch_lineup_rows", new=AsyncMock(return_value=lineup_rows)
            ),
            patch.object(
                service,
                "_fetch_kickoff_times",
                new=AsyncMock(return_value=make_kickoffs()),
            ),
            patch.object(
                service, "_fetch_single_player", new=AsyncMock(return_value=dupont_data)
            ),
            patch("app.services.lineup_service.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = NOW

            with pytest.raises(LineupLockError, match="current captain"):
                await service.update_captain(
                    roster_id=ROSTER_ID,
                    round_id=ROUND_ID,
                    user_id=USER_ID,
                    update=CaptainUpdate(player_id=PLAYER_ALLDRITT),
                )

    @pytest.mark.asyncio
    async def test_change_captain_to_locked_player_raises(self) -> None:
        """Cannot designate a player whose team has already kicked off as captain."""
        # Current captain is Alldritt (La Rochelle — FUTURE_KICKOFF) — OK
        # New captain would be Dupont (Toulouse — PAST_KICKOFF) — blocked
        lineup_rows = [
            {"player_id": str(PLAYER_ALLDRITT), "is_captain": True, "is_kicker": False},
            {"player_id": str(PLAYER_DUPONT), "is_captain": False, "is_kicker": False},
        ]
        alldritt_data = {
            "id": str(PLAYER_ALLDRITT),
            "name": "Gregory Alldritt",
            "club": "La Rochelle",
            "positions": ["number_8"],
        }
        dupont_data = {
            "id": str(PLAYER_DUPONT),
            "name": "Antoine Dupont",
            "club": "Toulouse",
            "positions": ["scrum_half"],
        }
        service = LineupService(client=make_mock_client())
        slots = make_roster_slots()

        with (
            patch.object(service, "_assert_ownership", new=AsyncMock()),
            patch.object(
                service, "_fetch_lineup_rows", new=AsyncMock(return_value=lineup_rows)
            ),
            patch.object(
                service,
                "_fetch_kickoff_times",
                new=AsyncMock(return_value=make_kickoffs()),
            ),
            # First call → current captain (Alldritt), second call → new captain (Dupont)
            patch.object(
                service,
                "_fetch_single_player",
                new=AsyncMock(side_effect=[alldritt_data, dupont_data]),
            ),
            patch.object(
                service, "_fetch_roster_slots", new=AsyncMock(return_value=slots)
            ),
            patch("app.services.lineup_service.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = NOW

            with pytest.raises(LineupLockError, match="already kicked off"):
                await service.update_captain(
                    roster_id=ROSTER_ID,
                    round_id=ROUND_ID,
                    user_id=USER_ID,
                    update=CaptainUpdate(player_id=PLAYER_DUPONT),
                )

    @pytest.mark.asyncio
    async def test_change_captain_between_matches_valid(self) -> None:
        """CDC 6.6: change captain from unlocked to unlocked player — must succeed."""
        # Current captain Alldritt (La Rochelle — future), new captain also future
        lineup_rows = [
            {"player_id": str(PLAYER_ALLDRITT), "is_captain": True, "is_kicker": False},
            {"player_id": str(uuid4()), "is_captain": False, "is_kicker": False},
        ]
        new_captain_id = uuid4()
        alldritt_data = {
            "id": str(PLAYER_ALLDRITT),
            "name": "Gregory Alldritt",
            "club": "La Rochelle",
            "positions": ["number_8"],
        }
        new_captain_data = {
            "id": str(new_captain_id),
            "name": "Will Skelton",
            "club": "La Rochelle",
            "positions": ["lock"],
        }
        slots = make_roster_slots()
        # Add new_captain to slots as starter
        slots.append(
            {
                "player_id": str(new_captain_id),
                "slot_type": "starter",
                "players": new_captain_data,
            }
        )

        service = LineupService(client=make_mock_client())

        with (
            patch.object(service, "_assert_ownership", new=AsyncMock()),
            patch.object(
                service, "_fetch_lineup_rows", new=AsyncMock(return_value=lineup_rows)
            ),
            patch.object(
                service,
                "_fetch_kickoff_times",
                new=AsyncMock(return_value=make_kickoffs()),
            ),
            patch.object(
                service,
                "_fetch_single_player",
                new=AsyncMock(side_effect=[alldritt_data, new_captain_data]),
            ),
            patch.object(
                service, "_fetch_roster_slots", new=AsyncMock(return_value=slots)
            ),
            patch.object(service, "_set_captain", new=AsyncMock()),
            patch.object(service, "get_lineup", new=AsyncMock()),
            patch("app.services.lineup_service.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = NOW
            # Should not raise
            await service.update_captain(
                roster_id=ROSTER_ID,
                round_id=ROUND_ID,
                user_id=USER_ID,
                update=CaptainUpdate(player_id=new_captain_id),
            )


# ---------------------------------------------------------------------------
# Service tests — kicker update (CDC 6.6)
# ---------------------------------------------------------------------------


class TestKickerUpdate:
    """Kicker lock rules from CDC section 6.6."""

    @pytest.mark.asyncio
    async def test_change_kicker_after_match_raises(self) -> None:
        """Cannot change kicker once their team has kicked off."""
        # Current kicker is Ntamack (Toulouse — PAST_KICKOFF)
        lineup_rows = [
            {"player_id": str(PLAYER_NTAMACK), "is_captain": False, "is_kicker": True},
        ]
        ntamack_data = {
            "id": str(PLAYER_NTAMACK),
            "name": "Romain Ntamack",
            "club": "Toulouse",
            "positions": ["fly_half"],
        }
        service = LineupService(client=make_mock_client())

        with (
            patch.object(service, "_assert_ownership", new=AsyncMock()),
            patch.object(
                service, "_fetch_lineup_rows", new=AsyncMock(return_value=lineup_rows)
            ),
            patch.object(
                service,
                "_fetch_kickoff_times",
                new=AsyncMock(return_value=make_kickoffs()),
            ),
            patch.object(
                service,
                "_fetch_single_player",
                new=AsyncMock(return_value=ntamack_data),
            ),
            patch("app.services.lineup_service.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = NOW

            with pytest.raises(LineupLockError, match="kicker"):
                await service.update_kicker(
                    roster_id=ROSTER_ID,
                    round_id=ROUND_ID,
                    user_id=USER_ID,
                    update=KickerUpdate(player_id=PLAYER_ALLDRITT),
                )

    @pytest.mark.asyncio
    async def test_change_kicker_before_match_passes(self) -> None:
        """Kicker change is allowed when current kicker's team hasn't kicked off."""
        # Current kicker is Alldritt (La Rochelle — FUTURE_KICKOFF)
        new_kicker_id = uuid4()
        lineup_rows = [
            {"player_id": str(PLAYER_ALLDRITT), "is_captain": False, "is_kicker": True},
        ]
        alldritt_data = {
            "id": str(PLAYER_ALLDRITT),
            "name": "Gregory Alldritt",
            "club": "La Rochelle",
            "positions": ["number_8"],
        }
        new_kicker_data = {
            "id": str(new_kicker_id),
            "name": "Jules Plisson",
            "club": "La Rochelle",
            "positions": ["fly_half"],
        }
        slots = make_roster_slots()
        slots.append(
            {
                "player_id": str(new_kicker_id),
                "slot_type": "starter",
                "players": new_kicker_data,
            }
        )

        service = LineupService(client=make_mock_client())

        with (
            patch.object(service, "_assert_ownership", new=AsyncMock()),
            patch.object(
                service, "_fetch_lineup_rows", new=AsyncMock(return_value=lineup_rows)
            ),
            patch.object(
                service,
                "_fetch_kickoff_times",
                new=AsyncMock(return_value=make_kickoffs()),
            ),
            patch.object(
                service,
                "_fetch_single_player",
                new=AsyncMock(side_effect=[alldritt_data, new_kicker_data]),
            ),
            patch.object(
                service, "_fetch_roster_slots", new=AsyncMock(return_value=slots)
            ),
            patch.object(service, "_set_kicker", new=AsyncMock()),
            patch.object(service, "get_lineup", new=AsyncMock()),
            patch("app.services.lineup_service.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = NOW
            await service.update_kicker(
                roster_id=ROSTER_ID,
                round_id=ROUND_ID,
                user_id=USER_ID,
                update=KickerUpdate(player_id=new_kicker_id),
            )
