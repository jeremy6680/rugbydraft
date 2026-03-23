-- =============================================================================
-- stg_match_stats
-- =============================================================================
-- Silver layer: individual player stats per match.
--
-- Source: bronze.raw_player_stats
--
-- DSG field mapping (D-039):
--   - tries and cards are NOT in player_stats — they come from separate
--     event nodes (scores, bookings). See stg_score_events and
--     stg_booking_events for those.
--   - goals = all successful kicks at goal (penalties + conversions)
--   - conversion_goals = conversions made only
--   - penalties_made is derived in gold: goals - conversion_goals
--   - kick_assists = try_kicks (DSG field: kick leading directly to a try)
--
-- Conditional stats use COALESCE(stat, 0):
--   line_breaks, catch_from_kick, lineouts_won, lineouts_lost,
--   kick_assists, handling_error, turnovers_conceded
--   These may be absent from the DSG response on low-activity matches.
--
-- Non-conditional stats (always present in DSG player_stats node):
--   tackles, metres_carried, turnovers_won (turnover_won in DSG),
--   try_assists, penalties_conceded
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

staged as (
    select
        -- ----------------------------------------------------------------
        -- Identifiers
        -- ----------------------------------------------------------------
        cast(external_match_id      as varchar)     as match_external_id,
        cast(external_player_id     as varchar)     as player_external_id,
        cast(player_name            as varchar)     as player_name,
        cast(team_id                as varchar)     as team_external_id,
        cast(position_played        as varchar)     as position_played,
        cast(minutes_played         as integer)     as minutes_played,

        -- ----------------------------------------------------------------
        -- Attack stats (D-039)
        -- tries: NOT here — comes from stg_score_events (DSG scores node)
        -- ----------------------------------------------------------------
        coalesce(cast(metres_carried    as integer), 0) as metres_carried,
        coalesce(cast(try_assists       as integer), 0) as try_assists,
        -- kick_assists: DSG field try_kicks = kick leading directly to a try
        coalesce(cast(kick_assists      as integer), 0) as kick_assists,
        -- Conditional attack stats
        coalesce(cast(line_breaks       as integer), 0) as line_breaks,
        coalesce(cast(catch_from_kick   as integer), 0) as catch_from_kick,

        -- ----------------------------------------------------------------
        -- Kicker stats (D-039)
        -- goals = all successful kicks at goal (penalties + conversions)
        -- conversion_goals = conversions made only
        -- penalties_made is derived in gold: goals - conversion_goals
        -- Kicker designation managed in FastAPI/PostgreSQL, not in dbt.
        -- ----------------------------------------------------------------
        coalesce(cast(goals             as integer), 0) as goals,
        coalesce(cast(conversion_goals  as integer), 0) as conversion_goals,

        -- ----------------------------------------------------------------
        -- Defence stats (D-039)
        -- yellow_cards/red_cards: NOT here — come from stg_booking_events
        -- ----------------------------------------------------------------
        coalesce(cast(tackles           as integer), 0) as tackles,
        -- DSG field name: turnover_won (singular) — aliased for consistency
        coalesce(cast(turnover_won      as integer), 0) as turnovers_won,
        -- Conditional defence stats
        coalesce(cast(lineouts_won      as integer), 0) as lineouts_won,
        coalesce(cast(lineouts_lost     as integer), 0) as lineouts_lost,
        coalesce(cast(turnovers_conceded as integer), 0) as turnovers_conceded,
        coalesce(cast(missed_tackles    as integer), 0) as missed_tackles,
        coalesce(cast(handling_error    as integer), 0) as handling_errors,
        coalesce(cast(penalties_conceded as integer), 0) as penalties_conceded,

        -- ----------------------------------------------------------------
        -- Round deduplication flag (CDC 6.6)
        -- Gold layer excludes rows where this is false.
        -- ----------------------------------------------------------------
        cast(is_first_match_of_round as boolean)    as is_first_match_of_round

    from source
)

select * from staged