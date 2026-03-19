"""
connectors/mock.py — Mock rugby data connector for development and testing.

Returns realistic fixture data (Six Nations 2026) without any API calls.
Used when RUGBY_DATA_SOURCE=mock (Phase 1 default).

Switch to a real provider: implement BaseRugbyConnector + change env var.
See DECISIONS.md D-012 for provider selection status.
"""

from datetime import date, datetime, timezone

from connectors.base import (
    BaseRugbyConnector,
    Fixture,
    MatchResult,
    MatchStatus,
    PlayerAvailability,
    PlayerAvailabilityStatus,
    PlayerMatchStats,
    PositionType,
)

# ---------------------------------------------------------------------------
# Static fixture data — Six Nations 2026 (realistic, not lorem ipsum)
# ---------------------------------------------------------------------------

# Competition identifier used throughout the mock dataset
_COMPETITION_ID = "six_nations_2026"
_COMPETITION_NAME = "Six Nations 2026"

# Team identifiers
_TEAMS = {
    "FRA": "France",
    "ENG": "England",
    "IRL": "Ireland",
    "SCO": "Scotland",
    "WAL": "Wales",
    "ITA": "Italy",
}

# ---------------------------------------------------------------------------
# Mock player pool — 36 players across 6 nations (6 per team)
# Covers all position types for roster constraint testing (CDC section 6)
# ---------------------------------------------------------------------------

_PLAYERS: list[dict] = [
    # --- France ---
    {
        "id": "p001",
        "name": "Cyril Baille",
        "team": "FRA",
        "position": PositionType.PROP,
    },
    {
        "id": "p002",
        "name": "Julien Marchand",
        "team": "FRA",
        "position": PositionType.HOOKER,
    },
    {
        "id": "p003",
        "name": "Thibaud Flament",
        "team": "FRA",
        "position": PositionType.LOCK,
    },
    {
        "id": "p004",
        "name": "François Cros",
        "team": "FRA",
        "position": PositionType.FLANKER,
    },
    {
        "id": "p005",
        "name": "Gregory Alldritt",
        "team": "FRA",
        "position": PositionType.NUMBER_8,
    },
    {
        "id": "p006",
        "name": "Thomas Ramos",
        "team": "FRA",
        "position": PositionType.FULLBACK,
    },
    # --- England ---
    {"id": "p007", "name": "Ellis Genge", "team": "ENG", "position": PositionType.PROP},
    {
        "id": "p008",
        "name": "Jamie George",
        "team": "ENG",
        "position": PositionType.HOOKER,
    },
    {"id": "p009", "name": "Maro Itoje", "team": "ENG", "position": PositionType.LOCK},
    {
        "id": "p010",
        "name": "Tom Curry",
        "team": "ENG",
        "position": PositionType.FLANKER,
    },
    {
        "id": "p011",
        "name": "Ben Earl",
        "team": "ENG",
        "position": PositionType.NUMBER_8,
    },
    {
        "id": "p012",
        "name": "Marcus Smith",
        "team": "ENG",
        "position": PositionType.FLY_HALF,
    },
    # --- Ireland ---
    {
        "id": "p013",
        "name": "Andrew Porter",
        "team": "IRL",
        "position": PositionType.PROP,
    },
    {
        "id": "p014",
        "name": "Ronan Kelleher",
        "team": "IRL",
        "position": PositionType.HOOKER,
    },
    {"id": "p015", "name": "James Ryan", "team": "IRL", "position": PositionType.LOCK},
    {
        "id": "p016",
        "name": "Josh van der Flier",
        "team": "IRL",
        "position": PositionType.FLANKER,
    },
    {
        "id": "p017",
        "name": "Caelan Doris",
        "team": "IRL",
        "position": PositionType.NUMBER_8,
    },
    {
        "id": "p018",
        "name": "Jonathan Sexton",
        "team": "IRL",
        "position": PositionType.FLY_HALF,
    },
    # --- Scotland ---
    {
        "id": "p019",
        "name": "Pierre Schoeman",
        "team": "SCO",
        "position": PositionType.PROP,
    },
    {
        "id": "p020",
        "name": "George Turner",
        "team": "SCO",
        "position": PositionType.HOOKER,
    },
    {"id": "p021", "name": "Jonny Gray", "team": "SCO", "position": PositionType.LOCK},
    {
        "id": "p022",
        "name": "Hamish Watson",
        "team": "SCO",
        "position": PositionType.FLANKER,
    },
    {
        "id": "p023",
        "name": "Matt Fagerson",
        "team": "SCO",
        "position": PositionType.NUMBER_8,
    },
    {
        "id": "p024",
        "name": "Finn Russell",
        "team": "SCO",
        "position": PositionType.FLY_HALF,
    },
    # --- Wales ---
    {
        "id": "p025",
        "name": "Gareth Thomas",
        "team": "WAL",
        "position": PositionType.PROP,
    },
    {"id": "p026", "name": "Dewi Lake", "team": "WAL", "position": PositionType.HOOKER},
    {"id": "p027", "name": "Adam Beard", "team": "WAL", "position": PositionType.LOCK},
    {
        "id": "p028",
        "name": "Tommy Reffell",
        "team": "WAL",
        "position": PositionType.FLANKER,
    },
    {
        "id": "p029",
        "name": "Taulupe Faletau",
        "team": "WAL",
        "position": PositionType.NUMBER_8,
    },
    {
        "id": "p030",
        "name": "Dan Biggar",
        "team": "WAL",
        "position": PositionType.FLY_HALF,
    },
    # --- Italy ---
    {
        "id": "p031",
        "name": "Danilo Fischetti",
        "team": "ITA",
        "position": PositionType.PROP,
    },
    {
        "id": "p032",
        "name": "Gianmarco Lucchesi",
        "team": "ITA",
        "position": PositionType.HOOKER,
    },
    {
        "id": "p033",
        "name": "Niccolò Cannone",
        "team": "ITA",
        "position": PositionType.LOCK,
    },
    {
        "id": "p034",
        "name": "Michele Lamaro",
        "team": "ITA",
        "position": PositionType.FLANKER,
    },
    {
        "id": "p035",
        "name": "Lorenzo Cannone",
        "team": "ITA",
        "position": PositionType.NUMBER_8,
    },
    {
        "id": "p036",
        "name": "Paolo Garbisi",
        "team": "ITA",
        "position": PositionType.FLY_HALF,
    },
]

# ---------------------------------------------------------------------------
# Mock fixtures — one finished match, one upcoming
# ---------------------------------------------------------------------------

_MATCH_FINISHED_ID = "m001"
_MATCH_UPCOMING_ID = "m002"

_FIXTURES_DATA: list[dict] = [
    {
        "external_id": _MATCH_FINISHED_ID,
        "competition_id": _COMPETITION_ID,
        "competition_name": _COMPETITION_NAME,
        "home_team_id": "FRA",
        "home_team_name": "France",
        "away_team_id": "ENG",
        "away_team_name": "England",
        "kickoff_utc": datetime(2026, 2, 1, 15, 15, tzinfo=timezone.utc),
        "status": MatchStatus.FINISHED,
        "home_score": 24,
        "away_score": 17,
        "season": "2026",
        "round_number": 1,
    },
    {
        "external_id": _MATCH_UPCOMING_ID,
        "competition_id": _COMPETITION_ID,
        "competition_name": _COMPETITION_NAME,
        "home_team_id": "IRL",
        "home_team_name": "Ireland",
        "away_team_id": "SCO",
        "away_team_name": "Scotland",
        "kickoff_utc": datetime(2026, 2, 8, 14, 0, tzinfo=timezone.utc),
        "status": MatchStatus.SCHEDULED,
        "home_score": None,
        "away_score": None,
        "season": "2026",
        "round_number": 2,
    },
]

# ---------------------------------------------------------------------------
# Mock player stats — for the finished match (France 24 - 17 England, round 1)
# Covers all scoring stats from CDC section 10 for pipeline testing
# ---------------------------------------------------------------------------

_PLAYER_STATS_DATA: list[dict] = [
    # France players
    {
        "external_match_id": _MATCH_FINISHED_ID,
        "external_player_id": "p001",  # Cyril Baille
        "player_name": "Cyril Baille",
        "team_id": "FRA",
        "position_played": PositionType.PROP,
        "minutes_played": 80,
        "tries": 0,
        "try_assists": 0,
        "metres_carried": 45,
        "offloads": 1,
        "drop_goals": 0,
        "conversions_made": 0,
        "conversions_missed": 0,
        "penalties_made": 0,
        "penalties_missed": 0,
        "fifty_twentytwo": None,  # provider does not supply
        "tackles": 8,
        "dominant_tackles": None,  # provider does not supply
        "turnovers_won": 1,
        "lineout_steals": None,  # provider does not supply
        "penalties_conceded": 1,
        "yellow_cards": 0,
        "red_cards": 0,
        "is_first_match_of_round": True,
    },
    {
        "external_match_id": _MATCH_FINISHED_ID,
        "external_player_id": "p005",  # Gregory Alldritt — big game
        "player_name": "Gregory Alldritt",
        "team_id": "FRA",
        "position_played": PositionType.NUMBER_8,
        "minutes_played": 80,
        "tries": 1,
        "try_assists": 1,
        "metres_carried": 112,
        "offloads": 3,
        "drop_goals": 0,
        "conversions_made": 0,
        "conversions_missed": 0,
        "penalties_made": 0,
        "penalties_missed": 0,
        "fifty_twentytwo": None,
        "tackles": 12,
        "dominant_tackles": None,
        "turnovers_won": 2,
        "lineout_steals": None,
        "penalties_conceded": 0,
        "yellow_cards": 0,
        "red_cards": 0,
        "is_first_match_of_round": True,
    },
    {
        "external_match_id": _MATCH_FINISHED_ID,
        "external_player_id": "p006",  # Thomas Ramos — kicker
        "player_name": "Thomas Ramos",
        "team_id": "FRA",
        "position_played": PositionType.FULLBACK,
        "minutes_played": 80,
        "tries": 0,
        "try_assists": 0,
        "metres_carried": 67,
        "offloads": 1,
        "drop_goals": 0,
        # Kicker stats — meaningful only if Ramos is designated kicker in roster
        "conversions_made": 2,
        "conversions_missed": 1,
        "penalties_made": 3,
        "penalties_missed": 0,
        "fifty_twentytwo": None,
        "tackles": 4,
        "dominant_tackles": None,
        "turnovers_won": 0,
        "lineout_steals": None,
        "penalties_conceded": 0,
        "yellow_cards": 0,
        "red_cards": 0,
        "is_first_match_of_round": True,
    },
    # England players
    {
        "external_match_id": _MATCH_FINISHED_ID,
        "external_player_id": "p009",  # Maro Itoje
        "player_name": "Maro Itoje",
        "team_id": "ENG",
        "position_played": PositionType.LOCK,
        "minutes_played": 80,
        "tries": 0,
        "try_assists": 0,
        "metres_carried": 28,
        "offloads": 0,
        "drop_goals": 0,
        "conversions_made": 0,
        "conversions_missed": 0,
        "penalties_made": 0,
        "penalties_missed": 0,
        "fifty_twentytwo": None,
        "tackles": 18,
        "dominant_tackles": None,
        "turnovers_won": 1,
        "lineout_steals": None,
        "penalties_conceded": 2,
        "yellow_cards": 1,  # -2 pts
        "red_cards": 0,
        "is_first_match_of_round": True,
    },
    {
        "external_match_id": _MATCH_FINISHED_ID,
        "external_player_id": "p012",  # Marcus Smith — try + kicker
        "player_name": "Marcus Smith",
        "team_id": "ENG",
        "position_played": PositionType.FLY_HALF,
        "minutes_played": 80,
        "tries": 1,
        "try_assists": 1,
        "metres_carried": 55,
        "offloads": 2,
        "drop_goals": 1,  # +3 pts (all starters)
        "conversions_made": 1,
        "conversions_missed": 1,
        "penalties_made": 2,
        "penalties_missed": 1,
        "fifty_twentytwo": None,
        "tackles": 3,
        "dominant_tackles": None,
        "turnovers_won": 0,
        "lineout_steals": None,
        "penalties_conceded": 1,
        "yellow_cards": 0,
        "red_cards": 0,
        "is_first_match_of_round": True,
    },
]

# ---------------------------------------------------------------------------
# Mock availability data — mix of statuses for alert testing
# ---------------------------------------------------------------------------

_AVAILABILITY_DATA: list[dict] = [
    # Fit players (explicit — some providers omit fit players)
    {
        "external_player_id": "p001",
        "player_name": "Cyril Baille",
        "team_id": "FRA",
        "team_name": "France",
        "status": PlayerAvailabilityStatus.FIT,
        "return_date": None,
        "suspension_matches": None,
        "notes": None,
    },
    {
        "external_player_id": "p005",
        "player_name": "Gregory Alldritt",
        "team_id": "FRA",
        "team_name": "France",
        "status": PlayerAvailabilityStatus.FIT,
        "return_date": None,
        "suspension_matches": None,
        "notes": None,
    },
    # Injured — triggers infirmary alert on dashboard
    {
        "external_player_id": "p003",
        "player_name": "Thibaud Flament",
        "team_id": "FRA",
        "team_name": "France",
        "status": PlayerAvailabilityStatus.INJURED,
        "return_date": date(2026, 2, 22),
        "suspension_matches": None,
        "notes": "Knee injury sustained in training. Expected return Round 3.",
    },
    # Suspended — tests suspension_matches field
    {
        "external_player_id": "p009",
        "player_name": "Maro Itoje",
        "team_id": "ENG",
        "team_name": "England",
        "status": PlayerAvailabilityStatus.SUSPENDED,
        "return_date": None,
        "suspension_matches": 1,
        "notes": "Yellow card accumulation — suspended for Round 2.",
    },
    # Doubtful — tests the doubtful status path
    {
        "external_player_id": "p017",
        "player_name": "Caelan Doris",
        "team_id": "IRL",
        "team_name": "Ireland",
        "status": PlayerAvailabilityStatus.DOUBTFUL,
        "return_date": None,
        "suspension_matches": None,
        "notes": "HIA protocol — will be assessed on Thursday.",
    },
]


# ---------------------------------------------------------------------------
# MockRugbyConnector — implements BaseRugbyConnector with static data
# ---------------------------------------------------------------------------


class MockRugbyConnector(BaseRugbyConnector):
    """
    Mock implementation of BaseRugbyConnector for development and testing.

    Returns static Six Nations 2026 data — no API calls, no network dependency.
    All filtering parameters are respected (same behaviour as a real connector).

    Usage:
        connector = MockRugbyConnector()
        fixtures = connector.get_fixtures()
        stats = connector.get_player_stats("m001")
    """

    def get_fixtures(
        self,
        competition_ids: list[str] | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[Fixture]:
        """Return mock fixtures, optionally filtered by competition or date range."""
        fixtures = [Fixture(**f) for f in _FIXTURES_DATA]

        if competition_ids is not None:
            fixtures = [f for f in fixtures if f.competition_id in competition_ids]

        if from_date is not None:
            fixtures = [f for f in fixtures if f.kickoff_utc.date() >= from_date]

        if to_date is not None:
            fixtures = [f for f in fixtures if f.kickoff_utc.date() <= to_date]

        # Return ordered by kick-off time ascending (same contract as real providers)
        return sorted(fixtures, key=lambda f: f.kickoff_utc)

    def get_player_availability(
        self,
        team_ids: list[str] | None = None,
    ) -> list[PlayerAvailability]:
        """Return mock player availability, optionally filtered by team."""
        availability = [PlayerAvailability(**a) for a in _AVAILABILITY_DATA]

        if team_ids is not None:
            availability = [a for a in availability if a.team_id in team_ids]

        return availability

    def get_match_results(
        self,
        competition_ids: list[str] | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[MatchResult]:
        """Return mock match results (finished matches only)."""
        # Build MatchResult from fixtures where status == FINISHED
        results = []
        for f_data in _FIXTURES_DATA:
            fixture = Fixture(**f_data)
            if fixture.status != MatchStatus.FINISHED:
                continue

            results.append(
                MatchResult(
                    external_id=fixture.external_id,
                    competition_id=fixture.competition_id,
                    home_team_id=fixture.home_team_id,
                    away_team_id=fixture.away_team_id,
                    home_score=fixture.home_score,  # type: ignore[arg-type]
                    away_score=fixture.away_score,  # type: ignore[arg-type]
                    kickoff_utc=fixture.kickoff_utc,
                    round_number=fixture.round_number,
                    status=MatchStatus.FINISHED,
                )
            )

        if competition_ids is not None:
            # MatchResult does not carry competition_id filter — filter via fixture
            finished_ids = {
                Fixture(**f).external_id
                for f in _FIXTURES_DATA
                if Fixture(**f).competition_id in competition_ids
            }
            results = [r for r in results if r.external_id in finished_ids]

        if from_date is not None:
            results = [r for r in results if r.kickoff_utc.date() >= from_date]

        if to_date is not None:
            results = [r for r in results if r.kickoff_utc.date() <= to_date]

        return results

    def get_player_stats(
        self,
        match_id: str,
    ) -> list[PlayerMatchStats]:
        """
        Return mock player stats for a given match.

        Args:
            match_id: Must be a known mock match ID (e.g. 'm001').

        Returns:
            List of PlayerMatchStats for all players in the match.

        Raises:
            ValueError: If match_id is not found in mock data.
        """
        # Only the finished match has stats
        if match_id != _MATCH_FINISHED_ID:
            raise ValueError(
                f"No stats available for match '{match_id}'. "
                f"Mock data only covers match '{_MATCH_FINISHED_ID}' (finished). "
                f"Match '{_MATCH_UPCOMING_ID}' is scheduled — stats not yet available."
            )

        return [PlayerMatchStats(**s) for s in _PLAYER_STATS_DATA]
