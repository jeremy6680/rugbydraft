"""
connectors/base.py — Abstract Base Class for rugby data connectors.

Defines the contract that every data source implementation must fulfill.
Switching providers = implementing this interface + changing RUGBY_DATA_SOURCE env var.

Supported providers (planned):
    - mock       → connectors/mock.py (Phase 1 — no real API)
    - statscore  → connectors/statscore.py (if selected)
    - sportradar → connectors/sportradar.py (if selected)
    - dsg        → connectors/dsg.py (if selected)
"""

from abc import ABC, abstractmethod
from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums — shared vocabulary across all connectors
# ---------------------------------------------------------------------------


class MatchStatus(str, Enum):
    """Status of a rugby match."""

    SCHEDULED = "scheduled"
    LIVE = "live"
    FINISHED = "finished"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"


class PlayerAvailabilityStatus(str, Enum):
    """Availability status of a player for selection."""

    FIT = "fit"
    INJURED = "injured"
    SUSPENDED = "suspended"
    DOUBTFUL = "doubtful"
    UNAVAILABLE = "unavailable"


class PositionType(str, Enum):
    """
    Rugby positions — maps to the position_type enum in PostgreSQL schema.

    Roster composition (CDC section 6.1 & 6.2):
        Starters (15): prop x2, hooker x1, lock x2, flanker x2, number_8 x1,
                        scrum_half x1, fly_half x1, centre x2, wing x2, fullback x1
        Bench (15):    same constraints apply with minimums per position
    """

    PROP = "prop"
    HOOKER = "hooker"
    LOCK = "lock"
    FLANKER = "flanker"
    NUMBER_8 = "number_8"  # D-013: distinct from flanker — see DECISIONS.md
    SCRUM_HALF = "scrum_half"
    FLY_HALF = "fly_half"
    CENTRE = "centre"
    WING = "wing"
    FULLBACK = "fullback"


# ---------------------------------------------------------------------------
# Output models — typed data returned by all connector methods
# ---------------------------------------------------------------------------


class Fixture(BaseModel):
    """
    An upcoming or completed match.
    Used by daily_fixtures cron and post_match_pipeline.
    """

    external_id: str = Field(description="Provider-specific unique match identifier")
    competition_id: str = Field(description="Provider-specific competition identifier")
    competition_name: str
    home_team_id: str
    home_team_name: str
    away_team_id: str
    away_team_name: str
    kickoff_utc: datetime = Field(description="Kick-off time in UTC")
    status: MatchStatus
    # Only populated when status == FINISHED
    home_score: int | None = None
    away_score: int | None = None
    season: str = Field(description="e.g. '2025-2026' or '2026'")
    round_number: int | None = Field(
        default=None,
        description="Round/matchday number within the competition",
    )


class PlayerAvailability(BaseModel):
    """
    Current availability status of a player.
    Used by daily_availability cron.
    """

    external_player_id: str = Field(description="Provider-specific player identifier")
    player_name: str
    team_id: str
    team_name: str
    status: PlayerAvailabilityStatus
    # Optional context — not all providers supply these
    return_date: date | None = Field(
        default=None,
        description="Estimated return date (injuries/suspensions). None if unknown.",
    )
    suspension_matches: int | None = Field(
        default=None,
        description="Number of matches remaining in suspension. None if not applicable.",
    )
    notes: str | None = Field(
        default=None,
        description="Free-text note from provider (e.g. 'shoulder knock, assessed Monday')",
    )


class MatchResult(BaseModel):
    """
    Final result and team-level stats for a completed match.
    Used by post_match_pipeline to confirm match is scoreable.
    """

    external_id: str = Field(description="Provider-specific unique match identifier")
    competition_id: str
    home_team_id: str
    away_team_id: str
    home_score: int
    away_score: int
    kickoff_utc: datetime
    round_number: int | None = None
    status: (
        MatchStatus  # Should always be FINISHED when returned by get_match_results()
    )


class PlayerMatchStats(BaseModel):
    """
    Individual player statistics for a single match.
    Used by post_match_pipeline to calculate fantasy points.

    Scoring system v2 (D-039):
        Attack:  metres (+0.1/m), try_assists (+2), tries (+5),
                 kick_assists (+1), line_breaks (+1),
                 catch_from_kick (+0.5),
                 conversions_made (+2, kicker only),
                 penalties_made (+3, kicker only)
        Defence: tackles (+0.5), turnovers_won (+2),
                 lineouts_won (+1, thrower), lineouts_lost (-0.5, thrower),
                 turnovers_conceded (-0.5), missed_tackles (-0.5),
                 handling_errors (-0.5), penalties_conceded (-1),
                 yellow_cards (-2), red_cards (-3)

    DSG field notes:
        - tries: from DSG scores event node (type="try"), resolved by connector
        - yellow_cards/red_cards: from DSG bookings node, resolved by connector
        - goals: all successful kicks at goal (penalties + conversions)
        - conversion_goals: conversions made only
        - penalties_made derived in connector: goals - conversion_goals
        - kick_assists: DSG field try_kicks (kick leading directly to a try)

    Conditional stats (may be None if provider does not supply):
        line_breaks, catch_from_kick, lineouts_won, lineouts_lost,
        kick_assists, handling_errors, turnovers_conceded
        → dbt uses COALESCE(stat, 0) — they score 0 if absent.
    """

    external_match_id: str
    external_player_id: str
    player_name: str
    team_id: str
    position_played: PositionType | None = Field(
        default=None,
        description="Position actually played in this match.",
    )
    minutes_played: int | None = None

    # --- Attack stats ---
    tries: int = Field(default=0, ge=0)
    try_assists: int = Field(default=0, ge=0)
    metres_carried: int | None = Field(
        default=None,
        description="Metres carried with ball in hand. None if provider does not supply.",
    )
    # Conditional — COALESCE to 0 in dbt if None
    kick_assists: int | None = Field(
        default=None,
        description="DSG try_kicks: kick leading directly to a try. +1 pt.",
    )
    line_breaks: int | None = Field(
        default=None,
        description="Line breaks made. +1 pt each.",
    )
    catch_from_kick: int | None = Field(
        default=None,
        description="Catches under kick. +0.5 pt each.",
    )

    # Kicker stats — scored only if player is designated kicker in the roster.
    # Kicker designation is managed in FastAPI/PostgreSQL, not in dbt.
    conversions_made: int = Field(default=0, ge=0)
    penalties_made: int = Field(default=0, ge=0)

    # --- Defence stats ---
    tackles: int | None = None
    turnovers_won: int | None = None
    # Conditional — COALESCE to 0 in dbt if None
    lineouts_won: int | None = Field(
        default=None,
        description="Lineouts won as thrower (any position). +1 pt each.",
    )
    lineouts_lost: int | None = Field(
        default=None,
        description="Lineouts lost as thrower (any position). -0.5 pt each.",
    )
    turnovers_conceded: int | None = Field(
        default=None,
        description="Turnovers conceded. -0.5 pt each.",
    )
    missed_tackles: int | None = Field(
        default=None,
        description="Missed tackles. -0.5 pt each.",
    )
    handling_errors: int | None = Field(
        default=None,
        description="Handling errors. -0.5 pt each.",
    )
    penalties_conceded: int | None = None
    yellow_cards: int = Field(default=0, ge=0)
    red_cards: int = Field(default=0, ge=0)

    # Edge case (CDC 6.6): player plays two matches in same round
    is_first_match_of_round: bool = Field(
        default=True,
        description=(
            "False if player already played a match this round. "
            "dbt gold layer ignores stats where this is False."
        ),
    )


# ---------------------------------------------------------------------------
# Abstract Base Class — the connector contract
# ---------------------------------------------------------------------------


class BaseRugbyConnector(ABC):
    """
    Abstract base class for all rugby data source connectors.

    Every provider implementation must subclass this and implement all
    abstract methods. The pipeline code only ever calls these 4 methods —
    the provider implementation is fully hidden behind this interface.

    Usage:
        connector = MockRugbyConnector()           # Phase 1
        connector = StatscoreConnector(api_key)    # Phase 3+ (if selected)

        fixtures = connector.get_fixtures()        # Same call, different impl
    """

    @abstractmethod
    def get_fixtures(
        self,
        competition_ids: list[str] | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[Fixture]:
        """
        Fetch upcoming and recent fixtures.

        Called by: daily_fixtures cron (06:00 UTC via Coolify)

        Args:
            competition_ids: Filter by competition. None = all tracked competitions.
            from_date: Start of date range. None = provider default (usually today).
            to_date: End of date range. None = provider default (usually +14 days).

        Returns:
            List of Fixture objects, ordered by kickoff_utc ascending.
        """
        ...

    @abstractmethod
    def get_player_availability(
        self,
        team_ids: list[str] | None = None,
    ) -> list[PlayerAvailability]:
        """
        Fetch current player availability (injuries, suspensions).

        Called by: daily_availability cron (08:00 UTC via Coolify)

        Args:
            team_ids: Filter by team. None = all tracked teams.

        Returns:
            List of PlayerAvailability objects for all tracked players.
            Players with status FIT may be omitted by some providers —
            implementations must normalize this (return FIT for missing players
            if the provider uses an absence-means-fit model).
        """
        ...

    @abstractmethod
    def get_match_results(
        self,
        competition_ids: list[str] | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[MatchResult]:
        """
        Fetch results for completed matches.

        Called by: post_match_pipeline (Airflow DAG, weekends)

        Args:
            competition_ids: Filter by competition. None = all tracked competitions.
            from_date: Start of date range. None = today.
            to_date: End of date range. None = today.

        Returns:
            List of MatchResult objects with status == FINISHED.
            The pipeline uses this to detect which matches need scoring.
        """
        ...

    @abstractmethod
    def get_player_stats(
        self,
        match_id: str,
    ) -> list[PlayerMatchStats]:
        """
        Fetch individual player statistics for a single completed match.

        Called by: post_match_pipeline, once per finished match per round.

        Args:
            match_id: Provider-specific match identifier (external_id from Fixture).

        Returns:
            List of PlayerMatchStats, one entry per player who appeared in the match.
            Both starting XV and substitutes are included (bench players score 0
            unless they come on — minute tracking is handled by minutes_played).

        Raises:
            NotImplementedError: Must be implemented by every subclass.
            ValueError: If match_id is not found or match is not yet finished.
        """
        ...
