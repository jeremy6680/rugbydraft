-- =============================================================================
-- stg_match_stats
-- =============================================================================
-- Silver layer: individual player stats per match.
--
-- Source: bronze.raw_player_stats
--
-- The connector (DSG or mock) resolves all provider-specific field names
-- before writing to data/raw/player_stats.json. This model receives clean,
-- already-normalised fields matching the PlayerMatchStats contract.
--
-- DSG specifics handled in connectors/dsg.py (not here):
--   - tries: extracted from DSG scores event node
--   - yellow_cards/red_cards: extracted from DSG bookings node
--   - penalties_made: derived as goals - conversion_goals
--   - kick_assists: mapped from DSG try_kicks field
--
-- DuckDB note: 'renamed' CTE used before 'staged' to avoid alias collision —
-- DuckDB cannot alias a column with the same name in the same SELECT clause.
--
-- Conditional stats use COALESCE(stat, 0):
--   line_breaks, catch_from_kick, lineouts_won, lineouts_lost,
--   kick_assists, handling_errors, turnovers_conceded
--
-- Edge case (CDC 6.6): is_first_match_of_round = false rows are kept here
-- but excluded in the gold layer (mart_fantasy_points WHERE clause).
--
-- Scoring system: v2 — see DECISIONS.md D-039
-- =============================================================================

{{ config(materialized='table') }}

with source as (
    select * from {{ ref('raw_player_stats') }}
),

-- Rename columns before casting to avoid DuckDB alias collision.
-- DuckDB cannot reference a column and alias it with the same name
-- in the same SELECT clause — intermediate renaming solves this.
renamed as (
    select
        external_match_id,
        external_player_id,
        player_name,
        team_id,
        position_played,
        minutes_played,
        tries,
        try_assists,
        metres_carried,
        kick_assists,
        line_breaks,
        catch_from_kick,
        conversions_made        as raw_conversions_made,
        penalties_made          as raw_penalties_made,
        tackles,
        turnovers_won           as raw_turnovers_won,
        lineouts_won,
        lineouts_lost,
        turnovers_conceded,
        missed_tackles,
        handling_errors,
        penalties_conceded,
        yellow_cards,
        red_cards,
        is_first_match_of_round
    from source
),

staged as (
    select
        -- Identifiers
        cast(external_match_id      as varchar)     as match_external_id,
        cast(external_player_id     as varchar)     as player_external_id,
        cast(player_name            as varchar)     as player_name,
        cast(team_id                as varchar)     as team_external_id,
        cast(position_played        as varchar)     as position_played,
        cast(minutes_played         as integer)     as minutes_played,

        -- Attack (D-039)
        coalesce(cast(tries             as integer), 0) as tries,
        coalesce(cast(try_assists       as integer), 0) as try_assists,
        coalesce(cast(metres_carried    as integer), 0) as metres_carried,
        coalesce(cast(kick_assists      as integer), 0) as kick_assists,
        coalesce(cast(line_breaks       as integer), 0) as line_breaks,
        coalesce(cast(catch_from_kick   as integer), 0) as catch_from_kick,

        -- Kicker stats (D-039)
        -- Connector delivers conversions_made and penalties_made directly.
        -- DSG connector derives penalties_made = goals - conversion_goals.
        -- Silver passes them through — gold applies kicker_flag filter.
        coalesce(cast(raw_conversions_made  as integer), 0) as conversions_made,
        coalesce(cast(raw_penalties_made    as integer), 0) as penalties_made,

        -- Defence (D-039)
        coalesce(cast(tackles               as integer), 0) as tackles,
        coalesce(cast(raw_turnovers_won     as integer), 0) as turnovers_won,
        coalesce(cast(lineouts_won          as integer), 0) as lineouts_won,
        coalesce(cast(lineouts_lost         as integer), 0) as lineouts_lost,
        coalesce(cast(turnovers_conceded    as integer), 0) as turnovers_conceded,
        coalesce(cast(missed_tackles        as integer), 0) as missed_tackles,
        coalesce(cast(handling_errors       as integer), 0) as handling_errors,
        coalesce(cast(penalties_conceded    as integer), 0) as penalties_conceded,
        coalesce(cast(yellow_cards          as integer), 0) as yellow_cards,
        coalesce(cast(red_cards             as integer), 0) as red_cards,

        -- Round deduplication flag (CDC 6.6)
        cast(is_first_match_of_round as boolean)    as is_first_match_of_round

    from renamed
)

select * from staged