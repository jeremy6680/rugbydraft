"""DSG (Data Sports Group) rugby data connector.

Implements BaseRugbyConnector for the DSG API v3.

Authentication — three layers (all required):
    1. Query param:    authkey=<DSG_AUTHKEY>
    2. HTTP Basic Auth: Authorization: Basic base64(username:password)
    3. IP whitelist:   configured server-side by DSG, no code needed here

Reference: docs/dsg_api_reference.md (gitignored — confidential)
API base:  https://dsg-api.com/clients/jeremym/rugby/

Design decisions:
    - We parse XML (not JSON via ftype=json). DSG XML is the canonical
      format, fully documented, and validated in Phase 0. The JSON
      conversion is an undocumented layer — we avoid it.
    - All stat attributes default to 0 via _int_attr() — DSG uses empty
      string ("") for absent stats, not a missing attribute.
    - Cards (yellow/red) live in <events><bookings>, NOT <player_stats>.
      They are joined by people_id before building PlayerMatchStats.
    - Tries live in <events><scores> type="try", also joined by people_id.
    - penalties_made is computed here: goals - conversion_goals.
      DSG's `goals` field = all successful kicks at goal (penalties + conversions).
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone

import httpx

from connectors.base import (
    BaseRugbyConnector,
    Fixture,
    MatchResult,
    MatchStatus,
    PlayerAvailability,
    PlayerMatchStats,
    PositionType,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Position mapping — DSG string → PositionType enum
# ---------------------------------------------------------------------------

# Validated against match_id 3798425 (Clermont vs Toulouse, Top 14 2025/26).
# DSG position strings are free-text — extend this map if new values appear
# in other competitions. Unknown values fall back to None (logged as warning).
_DSG_POSITION_MAP: dict[str, PositionType] = {
    "Prop": PositionType.PROP,
    "Hooker": PositionType.HOOKER,
    "Lock": PositionType.LOCK,
    "Flanker": PositionType.FLANKER,
    "Back Row": PositionType.FLANKER,  # DSG uses "Back Row" for 6/7/8
    "No8": PositionType.NUMBER_8,
    "Number 8": PositionType.NUMBER_8,
    "Scrum Half": PositionType.SCRUM_HALF,
    "Fly Half": PositionType.FLY_HALF,
    "Centre": PositionType.CENTRE,
    "Wing": PositionType.WING,
    "Full Back": PositionType.FULLBACK,
    "Fullback": PositionType.FULLBACK,
}

# DSG match status → MatchStatus enum (base.py contract)
_DSG_STATUS_MAP: dict[str, MatchStatus] = {
    "Fixture": MatchStatus.SCHEDULED,
    "Playing": MatchStatus.LIVE,
    "Played": MatchStatus.FINISHED,
    "Postponed": MatchStatus.POSTPONED,
    "Cancelled": MatchStatus.CANCELLED,
}


# ---------------------------------------------------------------------------
# DSGConnector
# ---------------------------------------------------------------------------


class DSGConnector(BaseRugbyConnector):
    """Connector for the Data Sports Group (DSG) rugby API.

    Parses DSG XML responses and maps field names to the PlayerMatchStats
    contract defined in BaseRugbyConnector.

    Example:
        connector = DSGConnector(
            base_url=settings.dsg_url,
            username=settings.dsg_username,
            password=settings.dsg_password,
            authkey=settings.dsg_authkey,
        )
        stats = connector.get_player_stats("3798425")
        connector.close()
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        authkey: str,
    ) -> None:
        """Initialise the DSG connector with credentials.

        Args:
            base_url: DSG API base URL.
                      e.g. "https://dsg-api.com/clients/jeremym/rugby"
            username: HTTP Basic Auth username (DSG_USERNAME in .env).
            password: HTTP Basic Auth password (DSG_PASSWORD in .env).
            authkey:  DSG authkey query param (DSG_AUTHKEY in .env).
        """
        self._base_url = base_url.rstrip("/")
        self._authkey = authkey
        # A single reusable httpx.Client with Basic Auth pre-configured.
        # timeout=30s: DSG full-match responses with player stats can be large.
        self._client = httpx.Client(
            auth=(username, password),
            timeout=30.0,
        )

    # ------------------------------------------------------------------
    # BaseRugbyConnector — public interface
    # ------------------------------------------------------------------

    def get_fixtures(
        self,
        competition_ids: list[str] | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[Fixture]:
        """Fetch all fixtures for the given competition season(s).

        DSG requires a season_id (not a competition_id) for the season
        listing endpoint. The caller (Airflow DAG / cron script) is
        responsible for resolving competition_id → season_id via
        get_seasons before calling this method.

        In practice, the daily_fixtures cron passes season_ids directly
        via the ingest script (scripts/ingest_dsg.py). This method
        accepts competition_ids for interface compliance but uses them
        as season_ids when calling DSG.

        Args:
            competition_ids: List of DSG season_ids to fetch.
                             None = no-op, returns empty list.
            from_date: Unused — DSG season endpoint returns all matches.
            to_date:   Unused — DSG season endpoint returns all matches.

        Returns:
            Combined list of Fixture objects from all requested seasons.
        """
        if not competition_ids:
            logger.warning(
                "DSG get_fixtures: no season_ids provided, returning empty list"
            )
            return []

        all_fixtures: list[Fixture] = []
        for season_id in competition_ids:
            logger.info("DSG get_fixtures: fetching season_id=%s", season_id)
            xml_text = self._fetch_season_xml(season_id)
            fixtures = self._parse_fixtures(xml_text)
            all_fixtures.extend(fixtures)
            logger.info(
                "DSG get_fixtures: season_id=%s → %d fixtures",
                season_id,
                len(fixtures),
            )

        return all_fixtures

    def get_player_availability(
        self,
        team_ids: list[str] | None = None,
    ) -> list[PlayerAvailability]:
        """DSG does not provide a player availability endpoint.

        DSG publishes injury/suspension data only through the fixture
        and match detail responses — not via a dedicated availability
        feed. For V1, availability is managed manually via the FastAPI
        admin interface (CDC §6.4 — infirmary rules).

        This method is implemented as a no-op stub to satisfy the
        BaseRugbyConnector contract.

        Args:
            team_ids: Ignored.

        Returns:
            Always returns an empty list.
        """
        logger.info(
            "DSG get_player_availability: DSG has no availability endpoint — returning []"
        )
        return []

    def get_match_results(
        self,
        competition_ids: list[str] | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[MatchResult]:
        """Fetch results for completed matches in the given season(s).

        Re-uses the season listing endpoint (type=season) and filters
        for matches with status="Played". This is how the Airflow DAG
        detects which matches need scoring each weekend.

        Args:
            competition_ids: List of DSG season_ids to check.
                             None = no-op, returns empty list.
            from_date: Unused — DSG season endpoint returns all matches.
            to_date:   Unused — DSG season endpoint returns all matches.

        Returns:
            List of MatchResult objects with status == FINISHED.
        """
        if not competition_ids:
            return []

        results: list[MatchResult] = []
        for season_id in competition_ids:
            xml_text = self._fetch_season_xml(season_id)
            results.extend(self._parse_match_results(xml_text))

        return results

    def get_player_stats(self, match_id: str) -> list[PlayerMatchStats]:
        """Fetch full player statistics for a single completed match.

        Calls: GET /get_matches?type=match&id={match_id}&detailed=yes

        The <player_stats> node is only populated when status="Played".
        Returns an empty list (with a warning) for non-finished matches.

        Args:
            match_id: DSG match_id string (e.g. "3798425").

        Returns:
            List of PlayerMatchStats, one per player who appeared.
            Empty list if the match is not yet finished.

        Raises:
            httpx.HTTPStatusError: on 4xx/5xx response from DSG.
            xml.etree.ElementTree.ParseError: on malformed XML.
        """
        logger.info("DSG get_player_stats: match_id=%s", match_id)
        xml_text = self._fetch_match_xml(match_id)
        return self._parse_player_stats(xml_text)

    def close(self) -> None:
        """Close the underlying httpx client and release connections.

        Call this when the connector is no longer needed — typically at
        the end of an Airflow task or a cron script run.
        """
        self._client.close()

    def __enter__(self) -> "DSGConnector":
        """Support use as a context manager."""
        return self

    def __exit__(self, *args: object) -> None:
        """Close client on context manager exit."""
        self.close()

    def __repr__(self) -> str:
        """Return a safe string representation — credentials are never shown."""
        return f"DSGConnector(base_url={self._base_url!r})"

    # ------------------------------------------------------------------
    # HTTP fetch helpers (thin wrappers — no parsing logic here)
    # ------------------------------------------------------------------

    def _fetch_season_xml(self, season_id: str) -> str:
        """Fetch the season listing XML from DSG.

        Args:
            season_id: DSG season_id string.

        Returns:
            Raw XML response text.

        Raises:
            httpx.HTTPStatusError: on non-2xx response.
        """
        response = self._client.get(
            f"{self._base_url}/get_matches",
            params={
                "type": "season",
                "id": season_id,
                "authkey": self._authkey,
            },
        )
        response.raise_for_status()
        return response.text

    def _fetch_match_xml(self, match_id: str) -> str:
        """Fetch the full match detail XML (with player stats) from DSG.

        Args:
            match_id: DSG match_id string.

        Returns:
            Raw XML response text.

        Raises:
            httpx.HTTPStatusError: on non-2xx response.
        """
        response = self._client.get(
            f"{self._base_url}/get_matches",
            params={
                "type": "match",
                "id": match_id,
                "detailed": "yes",
                "authkey": self._authkey,
            },
        )
        response.raise_for_status()
        return response.text

    # ------------------------------------------------------------------
    # XML parsers — pure functions, no HTTP, fully unit-testable
    # ------------------------------------------------------------------

    def _parse_fixtures(self, xml_text: str) -> list[Fixture]:
        """Parse a DSG season listing XML response into Fixture objects.

        Args:
            xml_text: Raw XML string from /get_matches?type=season

        Returns:
            List of Fixture objects for all matches in the season.
        """
        root = ET.fromstring(xml_text)
        fixtures: list[Fixture] = []

        # Extract competition metadata once (same for all matches in response)
        competition_el = root.find(".//competition")
        competition_id = (
            competition_el.get("competition_id", "")
            if competition_el is not None
            else ""
        )
        competition_name = (
            competition_el.get("name", "") if competition_el is not None else ""
        )

        season_el = root.find(".//season")
        season_title = season_el.get("title", "") if season_el is not None else ""

        for match_el in root.iter("match"):
            match_id = match_el.get("match_id", "")
            if not match_id:
                logger.warning(
                    "DSG _parse_fixtures: <match> with no match_id — skipping"
                )
                continue

            raw_status = match_el.get("status", "Fixture")
            status = _DSG_STATUS_MAP.get(raw_status, MatchStatus.SCHEDULED)
            if raw_status not in _DSG_STATUS_MAP:
                logger.warning(
                    "DSG _parse_fixtures: unknown status %r for match %s — defaulting to SCHEDULED",
                    raw_status,
                    match_id,
                )

            # Parse kick-off datetime — prefer UTC fields
            kickoff_utc = self._parse_kickoff_utc(match_el)

            # Scores — only populated for Played matches
            home_score: int | None = None
            away_score: int | None = None
            if status == MatchStatus.FINISHED:
                home_score = self._int_attr(match_el, "score_a")
                away_score = self._int_attr(match_el, "score_b")

            # Round/gameweek from <match_extra>
            round_number = self._get_gameweek(match_el)

            fixture = Fixture(
                external_id=match_id,
                competition_id=competition_id,
                competition_name=competition_name,
                home_team_id=match_el.get("team_a_id", ""),
                home_team_name=match_el.get("team_a_name", ""),
                away_team_id=match_el.get("team_b_id", ""),
                away_team_name=match_el.get("team_b_name", ""),
                kickoff_utc=kickoff_utc,
                status=status,
                home_score=home_score,
                away_score=away_score,
                season=season_title,
                round_number=round_number,
            )
            fixtures.append(fixture)

        logger.info("DSG _parse_fixtures: parsed %d fixtures", len(fixtures))
        return fixtures

    def _parse_match_results(self, xml_text: str) -> list[MatchResult]:
        """Parse a DSG season XML and extract only completed match results.

        Filters for status="Played" only. Used by get_match_results() to
        detect which matches need scoring.

        Args:
            xml_text: Raw XML string from /get_matches?type=season

        Returns:
            List of MatchResult objects (status == FINISHED).
        """
        root = ET.fromstring(xml_text)
        results: list[MatchResult] = []

        competition_el = root.find(".//competition")
        competition_id = (
            competition_el.get("competition_id", "")
            if competition_el is not None
            else ""
        )

        for match_el in root.iter("match"):
            if match_el.get("status") != "Played":
                continue

            match_id = match_el.get("match_id", "")
            if not match_id:
                continue

            kickoff_utc = self._parse_kickoff_utc(match_el)

            result = MatchResult(
                external_id=match_id,
                competition_id=competition_id,
                home_team_id=match_el.get("team_a_id", ""),
                away_team_id=match_el.get("team_b_id", ""),
                home_score=self._int_attr(match_el, "score_a"),
                away_score=self._int_attr(match_el, "score_b"),
                kickoff_utc=kickoff_utc,
                round_number=self._get_gameweek(match_el),
                status=MatchStatus.FINISHED,
            )
            results.append(result)

        return results

    def _parse_player_stats(self, xml_text: str) -> list[PlayerMatchStats]:
        """Parse a DSG single-match XML response into PlayerMatchStats.

        Three-pass strategy:
            Pass 1 — build try_counts dict from <events><scores> type="try"
            Pass 2 — build card_map dict from <events><bookings>
            Pass 3 — iterate <player_stats><people> → build PlayerMatchStats

        Cards and tries are NOT in <player_stats> — they are in sibling
        event nodes and must be joined by people_id.

        Args:
            xml_text: Raw XML from /get_matches?type=match&detailed=yes

        Returns:
            List of PlayerMatchStats. Empty list if match not finished.
        """
        root = ET.fromstring(xml_text)

        match_el = root.find(".//match")
        if match_el is None:
            logger.warning("DSG _parse_player_stats: no <match> element found")
            return []

        # Guard: only score completed matches
        status = match_el.get("status", "")
        if status != "Played":
            logger.info(
                "DSG _parse_player_stats: match %s has status=%r — no stats to parse",
                match_el.get("match_id", "?"),
                status,
            )
            return []

        match_id = match_el.get("match_id", "unknown")

        # Pass 1: try counts per player (people_id → int)
        try_counts = self._extract_try_counts(match_el)

        # Pass 2: cards per player (people_id → set of card type strings)
        card_map = self._extract_card_map(match_el)

        # Pass 3: parse each <people> element
        player_stats_el = match_el.find("player_stats")
        if player_stats_el is None:
            logger.warning(
                "DSG _parse_player_stats: no <player_stats> node in match %s", match_id
            )
            return []

        results: list[PlayerMatchStats] = []
        for people_el in player_stats_el.findall("people"):
            stats = self._parse_one_player(
                people_el=people_el,
                match_id=match_id,
                try_counts=try_counts,
                card_map=card_map,
            )
            results.append(stats)

        logger.info(
            "DSG _parse_player_stats: match %s → %d player records",
            match_id,
            len(results),
        )
        return results

    # ------------------------------------------------------------------
    # Event extraction helpers — called before iterating <player_stats>
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_try_counts(match_el: ET.Element) -> dict[str, int]:
        """Build people_id → try count from <events><scores> type="try".

        Args:
            match_el: The <match> XML element.

        Returns:
            Dict of DSG people_id string → number of tries scored.
        """
        counts: dict[str, int] = {}
        scores_el = match_el.find(".//events/scores")
        if scores_el is None:
            return counts
        for event in scores_el.findall("event"):
            if event.get("type") == "try":
                pid = event.get("people_id", "")
                if pid:
                    counts[pid] = counts.get(pid, 0) + 1
        return counts

    @staticmethod
    def _extract_card_map(match_el: ET.Element) -> dict[str, set[str]]:
        """Build people_id → card type set from <events><bookings>.

        A player can receive both a yellow and a red in the same match
        (second yellow → red escalation), hence we use a set.

        Args:
            match_el: The <match> XML element.

        Returns:
            Dict of DSG people_id string → set containing
            "yellow_card" and/or "red_card".
        """
        card_map: dict[str, set[str]] = {}
        bookings_el = match_el.find(".//events/bookings")
        if bookings_el is None:
            return card_map
        for event in bookings_el.findall("event"):
            card_type = event.get("type", "")
            pid = event.get("people_id", "")
            if card_type in {"yellow_card", "red_card"} and pid:
                card_map.setdefault(pid, set()).add(card_type)
        return card_map

    # ------------------------------------------------------------------
    # Single player parser
    # ------------------------------------------------------------------

    def _parse_one_player(
        self,
        people_el: ET.Element,
        match_id: str,
        try_counts: dict[str, int],
        card_map: dict[str, set[str]],
    ) -> PlayerMatchStats:
        """Parse a single <people> element into a PlayerMatchStats.

        penalties_made is computed here:
            penalties_made = goals - conversion_goals
        where goals = all successful kicks at goal (penalties + conversions).

        Args:
            people_el: A <people> element from <player_stats>.
            match_id: DSG match_id (for the external_match_id field).
            try_counts: Pre-built from _extract_try_counts().
            card_map: Pre-built from _extract_card_map().

        Returns:
            A fully populated PlayerMatchStats instance.
        """
        pid = people_el.get("people_id", "")
        cards = card_map.get(pid, set())

        # Kicker stats — compute penalties_made from DSG raw fields:
        #   goals            = total successful kicks at goal (PK made + conv made)
        #   conversion_goals = conversions made only
        #   → penalties_made = goals - conversion_goals
        goals = self._int_attr(people_el, "goals")
        conversion_goals = self._int_attr(people_el, "conversion_goals")
        penalties_made = max(
            0, goals - conversion_goals
        )  # max(0,...) guards against data anomalies

        # Position — map DSG string to PositionType enum (None if unknown)
        raw_position = people_el.get("position", "")
        position_played = _DSG_POSITION_MAP.get(raw_position)
        if raw_position and position_played is None:
            logger.warning(
                "DSG _parse_one_player: unknown position %r for player %s in match %s",
                raw_position,
                pid,
                match_id,
            )

        return PlayerMatchStats(
            # --- Identity ---
            external_match_id=match_id,
            external_player_id=pid,
            player_name=people_el.get("common_name") or people_el.get("short_name", ""),
            team_id=people_el.get("team_id", ""),
            position_played=position_played,
            minutes_played=None,  # DSG does not provide minutes_played directly
            # --- Attack ---
            tries=try_counts.get(pid, 0),
            try_assists=self._int_attr(people_el, "try_assists"),
            metres_carried=self._int_attr(people_el, "carries_metres") or None,
            kick_assists=self._int_attr(people_el, "try_kicks") or None,
            line_breaks=self._int_attr(people_el, "line_breaks") or None,
            catch_from_kick=self._int_attr(people_el, "catch_from_kick") or None,
            # --- Kicker ---
            conversions_made=conversion_goals,
            penalties_made=penalties_made,
            # --- Defence ---
            tackles=self._int_attr(people_el, "tackles") or None,
            turnovers_won=self._int_attr(people_el, "turnover_won") or None,
            lineouts_won=self._int_attr(people_el, "lineouts_won") or None,
            lineouts_lost=self._int_attr(people_el, "lineouts_lost") or None,
            turnovers_conceded=self._int_attr(people_el, "turnovers_conceded") or None,
            missed_tackles=self._int_attr(people_el, "missed_tackles") or None,
            handling_errors=self._int_attr(people_el, "handling_error") or None,
            penalties_conceded=self._int_attr(people_el, "penalties_conceded") or None,
            # --- Discipline (from bookings node) ---
            yellow_cards=1 if "yellow_card" in cards else 0,
            red_cards=1 if "red_card" in cards else 0,
        )

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _int_attr(element: ET.Element, attr: str) -> int:
        """Safely parse an XML attribute as int, defaulting to 0.

        DSG represents absent/null stats as empty string (""), not as a
        missing attribute. Both cases (missing attr and empty string)
        return 0.

        Args:
            element: The XML element to read from.
            attr: The attribute name to parse.

        Returns:
            Integer value, or 0 if absent, empty, or unparseable.
        """
        raw = element.get(attr, "")
        if not raw:
            return 0
        try:
            return int(raw)
        except ValueError:
            logger.warning(
                "DSG _int_attr: cannot parse attr=%r value=%r as int — defaulting to 0",
                attr,
                raw,
            )
            return 0

    @staticmethod
    def _parse_kickoff_utc(match_el: ET.Element) -> datetime:
        """Parse kick-off datetime from a <match> element, preferring UTC fields.

        DSG provides both local (date/time) and UTC (date_utc/time_utc) fields.
        We always prefer UTC. Falls back to local date at midnight UTC if
        time fields are absent.

        Args:
            match_el: The <match> XML element.

        Returns:
            timezone-aware datetime in UTC.
        """
        date_str = match_el.get("date_utc") or match_el.get("date", "")
        time_str = match_el.get("time_utc") or match_el.get("time", "")

        if not date_str:
            # No date at all — return epoch as sentinel, log warning
            logger.warning(
                "DSG _parse_kickoff_utc: no date found for match %s",
                match_el.get("match_id", "?"),
            )
            return datetime(1970, 1, 1, tzinfo=timezone.utc)

        # Build ISO string and parse — handle both "HH:MM:SS" and missing time
        iso_str = f"{date_str}T{time_str}" if time_str else f"{date_str}T00:00:00"
        try:
            dt = datetime.fromisoformat(iso_str)
            # DSG UTC fields are already UTC — attach tzinfo if naive
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            logger.warning(
                "DSG _parse_kickoff_utc: cannot parse datetime %r for match %s — using epoch",
                iso_str,
                match_el.get("match_id", "?"),
            )
            return datetime(1970, 1, 1, tzinfo=timezone.utc)

    @staticmethod
    def _get_gameweek(match_el: ET.Element) -> int | None:
        """Extract gameweek number from <match_extra gameweek="...">.

        Args:
            match_el: The <match> XML element.

        Returns:
            Gameweek integer, or None if absent or unparseable.
        """
        match_extra = match_el.find("match_extra")
        if match_extra is None:
            return None
        raw = match_extra.get("gameweek", "")
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None
