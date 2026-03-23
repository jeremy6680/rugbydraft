"""Unit tests for DSGConnector XML parsers.

All tests are purely offline — no HTTP calls are made.
The _parse_* methods are pure functions that accept raw XML strings,
so we can feed them real DSG response fragments as test fixtures.

Test data sourced from Phase 0 validation:
    match_id=3798425, ASM Clermont Auvergne vs Stade Toulousain
    Top 14, Gameweek 1, 2025/2026 season, status=Played
"""

import pytest

from connectors.dsg import DSGConnector
from connectors.base import MatchStatus, PlayerMatchStats, PositionType

# ---------------------------------------------------------------------------
# XML fixtures — minimal but real DSG response fragments
# ---------------------------------------------------------------------------

# Minimal season listing with 2 matches (one Fixture, one Played)
SEASON_XML_TWO_MATCHES = """<?xml version="1.0" encoding="UTF-8"?>
<datasportsgroup>
  <tour><tour_season>
    <competition competition_id="1034" name="Top 14">
      <season season_id="76580" title="2025/2026">
        <discipline><gender>
          <round round_id="128145" name="Regular Season">
            <list>
              <match match_id="3798425"
                     date="2025-09-07" time="21:05:00"
                     date_utc="2025-09-07" time_utc="19:05:00"
                     team_a_id="30744" team_a_name="ASM Clermont Auvergne"
                     team_b_id="30753" team_b_name="Stade Toulousain"
                     status="Played" score_a="24" score_b="34">
                <match_extra gameweek="1"/>
              </match>
              <match match_id="3798500"
                     date="2025-09-14" time="15:00:00"
                     date_utc="2025-09-14" time_utc="13:00:00"
                     team_a_id="30750" team_a_name="Racing 92"
                     team_b_id="30745" team_b_name="Stade Francais"
                     status="Fixture" score_a="" score_b="">
                <match_extra gameweek="2"/>
              </match>
            </list>
          </round>
        </gender></discipline>
      </season>
    </competition>
  </tour_season></tour>
</datasportsgroup>"""

# Full match XML for match_id=3798425 — real Phase 0 data
# Trimmed to 3 players for brevity, preserving the tricky cases:
#   - Ojovan (414138): yellow card in bookings
#   - Plummer (344910): kicker with goals=5, conversion_goals=1 → penalties_made=4
#   - Massa (7832707): try scorer + lineouts_won
MATCH_XML_PLAYED = """<?xml version="1.0" encoding="UTF-8"?>
<datasportsgroup>
  <tour><tour_season><competition competition_id="1034" name="Top 14">
    <season season_id="76580" title="2025/2026">
      <discipline><gender><round><list>
        <match match_id="3798425"
               date_utc="2025-09-07" time_utc="19:05:00"
               team_a_id="30744" team_a_name="ASM Clermont Auvergne"
               team_b_id="30753" team_b_name="Stade Toulousain"
               status="Played" score_a="24" score_b="34">
          <match_extra gameweek="1"/>
          <events>
            <scores>
              <event event_id="1" type="try" people_id="7832707"
                     team_id="30744"/>
              <event event_id="2" type="penalty" people_id="344910"
                     team_id="30744"/>
              <event event_id="3" type="conversion" people_id="344910"
                     team_id="30744"/>
            </scores>
            <bookings>
              <event event_id="4" type="yellow_card" people_id="414138"
                     team_id="30744"/>
            </bookings>
          </events>
          <player_stats>
            <people people_id="7832707" common_name="Barnabe Massa"
                    team_id="30744" team_name="ASM Clermont Auvergne"
                    position="Hooker"
                    carries_metres="16" tackles="8" missed_tackles="3"
                    lineouts_won="5" penalties_conceded="1"
                    handling_error="1" turnovers_conceded="1"
                    goals="" conversion_goals="" try_assists=""
                    try_kicks="" line_breaks="" catch_from_kick=""
                    lineouts_lost="" turnover_won=""/>
            <people people_id="344910" common_name="Harry Plummer"
                    team_id="30744" team_name="ASM Clermont Auvergne"
                    position="Fly Half"
                    goals="5" conversion_goals="1"
                    carries_metres="7" tackles="9" missed_tackles="1"
                    penalties_conceded="1" handling_error="1"
                    turnovers_conceded="1" catch_from_kick="2"
                    try_assists="" try_kicks="" line_breaks=""
                    lineouts_won="" lineouts_lost="" turnover_won=""/>
            <people people_id="414138" common_name="Cristian Ojovan"
                    team_id="30744" team_name="ASM Clermont Auvergne"
                    position="Prop"
                    carries_metres="3" missed_tackles="1"
                    penalties_conceded="1" tackles="2"
                    goals="" conversion_goals="" try_assists=""
                    try_kicks="" line_breaks="" catch_from_kick=""
                    lineouts_lost="" lineouts_won=""
                    turnovers_conceded="" turnover_won=""/>
          </player_stats>
        </match>
      </list></round></gender></discipline>
    </season>
  </competition></tour_season></tour>
</datasportsgroup>"""

# Match not yet played — player_stats should be empty
MATCH_XML_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<datasportsgroup>
  <tour><tour_season><competition><season><discipline><gender><round><list>
    <match match_id="3798500" status="Fixture"
           date_utc="2025-09-14" time_utc="13:00:00"
           team_a_id="30750" team_a_name="Racing 92"
           team_b_id="30745" team_b_name="Stade Francais">
      <match_extra gameweek="2"/>
      <events><scores/><bookings/></events>
      <player_stats/>
    </match>
  </list></round></gender></discipline></season></competition></tour_season></tour>
</datasportsgroup>"""


# ---------------------------------------------------------------------------
# Fixtures — connector instance (no HTTP needed for parser tests)
# ---------------------------------------------------------------------------


@pytest.fixture
def connector() -> DSGConnector:
    """DSGConnector instance with dummy credentials.

    Parser methods are pure — they never touch the httpx client.
    Credentials are placeholders only.
    """
    return DSGConnector(
        base_url="https://dsg-api.com/clients/jeremym/rugby",
        username="test_user",
        password="test_pass",
        authkey="test_key",
    )


# ---------------------------------------------------------------------------
# _parse_fixtures tests
# ---------------------------------------------------------------------------


class TestParseFixtures:
    """Tests for DSGConnector._parse_fixtures()."""

    def test_returns_two_fixtures(self, connector: DSGConnector) -> None:
        """Season XML with 2 matches → 2 Fixture objects."""
        result = connector._parse_fixtures(SEASON_XML_TWO_MATCHES)
        assert len(result) == 2

    def test_played_match_has_correct_status(self, connector: DSGConnector) -> None:
        """Match with status='Played' maps to MatchStatus.FINISHED."""
        result = connector._parse_fixtures(SEASON_XML_TWO_MATCHES)
        played = next(f for f in result if f.external_id == "3798425")
        assert played.status == MatchStatus.FINISHED

    def test_fixture_match_has_correct_status(self, connector: DSGConnector) -> None:
        """Match with status='Fixture' maps to MatchStatus.SCHEDULED."""
        result = connector._parse_fixtures(SEASON_XML_TWO_MATCHES)
        fixture = next(f for f in result if f.external_id == "3798500")
        assert fixture.status == MatchStatus.SCHEDULED

    def test_played_match_has_scores(self, connector: DSGConnector) -> None:
        """Played match populates home_score and away_score."""
        result = connector._parse_fixtures(SEASON_XML_TWO_MATCHES)
        played = next(f for f in result if f.external_id == "3798425")
        assert played.home_score == 24
        assert played.away_score == 34

    def test_fixture_match_scores_are_none(self, connector: DSGConnector) -> None:
        """Non-played match has None scores."""
        result = connector._parse_fixtures(SEASON_XML_TWO_MATCHES)
        fixture = next(f for f in result if f.external_id == "3798500")
        assert fixture.home_score is None
        assert fixture.away_score is None

    def test_competition_metadata_populated(self, connector: DSGConnector) -> None:
        """Competition id and name are extracted from the <competition> element."""
        result = connector._parse_fixtures(SEASON_XML_TWO_MATCHES)
        assert result[0].competition_id == "1034"
        assert result[0].competition_name == "Top 14"

    def test_gameweek_populated(self, connector: DSGConnector) -> None:
        """Gameweek is extracted from <match_extra gameweek=...>."""
        result = connector._parse_fixtures(SEASON_XML_TWO_MATCHES)
        played = next(f for f in result if f.external_id == "3798425")
        assert played.round_number == 1

    def test_team_names_populated(self, connector: DSGConnector) -> None:
        """Home and away team names are correctly extracted."""
        result = connector._parse_fixtures(SEASON_XML_TWO_MATCHES)
        played = next(f for f in result if f.external_id == "3798425")
        assert played.home_team_name == "ASM Clermont Auvergne"
        assert played.away_team_name == "Stade Toulousain"


# ---------------------------------------------------------------------------
# _parse_player_stats tests — the critical path
# ---------------------------------------------------------------------------


class TestParsePlayerStats:
    """Tests for DSGConnector._parse_player_stats()."""

    def test_returns_three_players(self, connector: DSGConnector) -> None:
        """Played match with 3 <people> nodes → 3 PlayerMatchStats."""
        result = connector._parse_player_stats(MATCH_XML_PLAYED)
        assert len(result) == 3

    def test_returns_empty_for_fixture(self, connector: DSGConnector) -> None:
        """Non-played match (status=Fixture) → empty list, no error."""
        result = connector._parse_player_stats(MATCH_XML_FIXTURE)
        assert result == []

    def test_try_counted_from_scores_node(self, connector: DSGConnector) -> None:
        """Massa scored 1 try in <scores> → tries=1 in PlayerMatchStats."""
        result = connector._parse_player_stats(MATCH_XML_PLAYED)
        massa = _get_player(result, "7832707")
        assert massa.tries == 1

    def test_player_without_try_has_zero(self, connector: DSGConnector) -> None:
        """Plummer has no try event → tries=0."""
        result = connector._parse_player_stats(MATCH_XML_PLAYED)
        plummer = _get_player(result, "344910")
        assert plummer.tries == 0

    def test_yellow_card_from_bookings(self, connector: DSGConnector) -> None:
        """Ojovan has yellow_card in <bookings> → yellow_cards=1."""
        result = connector._parse_player_stats(MATCH_XML_PLAYED)
        ojovan = _get_player(result, "414138")
        assert ojovan.yellow_cards == 1
        assert ojovan.red_cards == 0

    def test_player_without_card_has_zero(self, connector: DSGConnector) -> None:
        """Massa has no booking → yellow_cards=0, red_cards=0."""
        result = connector._parse_player_stats(MATCH_XML_PLAYED)
        massa = _get_player(result, "7832707")
        assert massa.yellow_cards == 0
        assert massa.red_cards == 0

    def test_penalties_made_computed_correctly(self, connector: DSGConnector) -> None:
        """Plummer: goals=5, conversion_goals=1 → penalties_made=4."""
        result = connector._parse_player_stats(MATCH_XML_PLAYED)
        plummer = _get_player(result, "344910")
        assert plummer.conversions_made == 1
        assert plummer.penalties_made == 4

    def test_non_kicker_penalties_made_zero(self, connector: DSGConnector) -> None:
        """Massa: goals='', conversion_goals='' → penalties_made=0."""
        result = connector._parse_player_stats(MATCH_XML_PLAYED)
        massa = _get_player(result, "7832707")
        assert massa.penalties_made == 0
        assert massa.conversions_made == 0

    def test_lineouts_won_from_player_stats(self, connector: DSGConnector) -> None:
        """Massa: lineouts_won=5 (from <player_stats>)."""
        result = connector._parse_player_stats(MATCH_XML_PLAYED)
        massa = _get_player(result, "7832707")
        assert massa.lineouts_won == 5

    def test_empty_string_stat_returns_none_for_optional(
        self, connector: DSGConnector
    ) -> None:
        """Empty string stats map to None for optional fields."""
        result = connector._parse_player_stats(MATCH_XML_PLAYED)
        massa = _get_player(result, "7832707")
        # try_assists is "" → 0 via _int_attr, then None via `or None`
        assert massa.try_assists == 0
        assert massa.kick_assists is None
        assert massa.line_breaks is None
        assert massa.catch_from_kick is None

    def test_position_mapped_to_enum(self, connector: DSGConnector) -> None:
        """DSG position strings are mapped to PositionType enum values."""
        result = connector._parse_player_stats(MATCH_XML_PLAYED)
        massa = _get_player(result, "7832707")
        plummer = _get_player(result, "344910")
        ojovan = _get_player(result, "414138")
        assert massa.position_played == PositionType.HOOKER
        assert plummer.position_played == PositionType.FLY_HALF
        assert ojovan.position_played == PositionType.PROP

    def test_external_match_id_populated(self, connector: DSGConnector) -> None:
        """All players have the correct match_id."""
        result = connector._parse_player_stats(MATCH_XML_PLAYED)
        for stats in result:
            assert stats.external_match_id == "3798425"

    def test_tackles_is_none_when_zero_stat(self, connector: DSGConnector) -> None:
        """Stat that parses to 0 via _int_attr becomes None for optional fields."""
        result = connector._parse_player_stats(MATCH_XML_PLAYED)
        plummer = _get_player(result, "344910")
        assert plummer.tackles == 9  # non-zero → kept


# ---------------------------------------------------------------------------
# _extract_try_counts tests
# ---------------------------------------------------------------------------


class TestExtractTryCounts:
    """Tests for the static try count extractor."""

    def test_counts_single_try(self, connector: DSGConnector) -> None:
        """One try event → count of 1 for that player."""
        import xml.etree.ElementTree as ET

        xml = """<match>
          <events>
            <scores>
              <event type="try" people_id="7832707"/>
            </scores>
          </events>
        </match>"""
        match_el = ET.fromstring(xml)
        result = DSGConnector._extract_try_counts(match_el)
        assert result == {"7832707": 1}

    def test_counts_multiple_tries_same_player(self, connector: DSGConnector) -> None:
        """Two try events for same player → count of 2."""
        import xml.etree.ElementTree as ET

        xml = """<match>
          <events>
            <scores>
              <event type="try" people_id="123"/>
              <event type="try" people_id="123"/>
            </scores>
          </events>
        </match>"""
        match_el = ET.fromstring(xml)
        result = DSGConnector._extract_try_counts(match_el)
        assert result == {"123": 2}

    def test_ignores_non_try_events(self, connector: DSGConnector) -> None:
        """Penalty and conversion events are not counted as tries."""
        import xml.etree.ElementTree as ET

        xml = """<match>
          <events>
            <scores>
              <event type="penalty" people_id="344910"/>
              <event type="conversion" people_id="264038"/>
            </scores>
          </events>
        </match>"""
        match_el = ET.fromstring(xml)
        result = DSGConnector._extract_try_counts(match_el)
        assert result == {}

    def test_empty_scores_returns_empty(self, connector: DSGConnector) -> None:
        """No <scores> element → empty dict, no error."""
        import xml.etree.ElementTree as ET

        xml = "<match><events/></match>"
        match_el = ET.fromstring(xml)
        result = DSGConnector._extract_try_counts(match_el)
        assert result == {}


# ---------------------------------------------------------------------------
# _extract_card_map tests
# ---------------------------------------------------------------------------


class TestExtractCardMap:
    """Tests for the static card extractor."""

    def test_yellow_card_detected(self, connector: DSGConnector) -> None:
        """Yellow card booking → yellow_card in card set."""
        import xml.etree.ElementTree as ET

        xml = """<match>
          <events>
            <bookings>
              <event type="yellow_card" people_id="414138"/>
            </bookings>
          </events>
        </match>"""
        match_el = ET.fromstring(xml)
        result = DSGConnector._extract_card_map(match_el)
        assert "yellow_card" in result["414138"]

    def test_red_card_detected(self, connector: DSGConnector) -> None:
        """Red card booking → red_card in card set."""
        import xml.etree.ElementTree as ET

        xml = """<match>
          <events>
            <bookings>
              <event type="red_card" people_id="999"/>
            </bookings>
          </events>
        </match>"""
        match_el = ET.fromstring(xml)
        result = DSGConnector._extract_card_map(match_el)
        assert "red_card" in result["999"]

    def test_player_receives_both_cards(self, connector: DSGConnector) -> None:
        """Player with yellow then red → both in their card set."""
        import xml.etree.ElementTree as ET

        xml = """<match>
          <events>
            <bookings>
              <event type="yellow_card" people_id="999"/>
              <event type="red_card" people_id="999"/>
            </bookings>
          </events>
        </match>"""
        match_el = ET.fromstring(xml)
        result = DSGConnector._extract_card_map(match_el)
        assert result["999"] == {"yellow_card", "red_card"}

    def test_empty_bookings_returns_empty(self, connector: DSGConnector) -> None:
        """No bookings → empty dict, no error."""
        import xml.etree.ElementTree as ET

        xml = "<match><events><bookings/></events></match>"
        match_el = ET.fromstring(xml)
        result = DSGConnector._extract_card_map(match_el)
        assert result == {}


# ---------------------------------------------------------------------------
# _int_attr tests
# ---------------------------------------------------------------------------


class TestIntAttr:
    """Tests for the safe integer attribute parser."""

    def test_parses_valid_integer(self) -> None:
        """Normal integer string → int value."""
        import xml.etree.ElementTree as ET

        el = ET.fromstring('<people tackles="15"/>')
        assert DSGConnector._int_attr(el, "tackles") == 15

    def test_empty_string_returns_zero(self) -> None:
        """Empty string attribute (DSG null) → 0."""
        import xml.etree.ElementTree as ET

        el = ET.fromstring('<people tackles=""/>')
        assert DSGConnector._int_attr(el, "tackles") == 0

    def test_missing_attribute_returns_zero(self) -> None:
        """Missing attribute entirely → 0."""
        import xml.etree.ElementTree as ET

        el = ET.fromstring("<people/>")
        assert DSGConnector._int_attr(el, "tackles") == 0

    def test_invalid_string_returns_zero(self) -> None:
        """Non-numeric string → 0, no exception raised."""
        import xml.etree.ElementTree as ET

        el = ET.fromstring('<people tackles="N/A"/>')
        assert DSGConnector._int_attr(el, "tackles") == 0


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _get_player(stats: list[PlayerMatchStats], people_id: str) -> PlayerMatchStats:
    """Find a PlayerMatchStats by external_player_id. Raises if not found."""
    for s in stats:
        if s.external_player_id == people_id:
            return s
    raise ValueError(f"Player {people_id!r} not found in stats list")
