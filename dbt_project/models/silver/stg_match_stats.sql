-- stg_match_stats.sql — Silver layer: individual player stats per match
--
-- Source: bronze.raw_player_stats
-- Applies COALESCE on all conditional stats (CDC section 10):
--   - If provider supplies the stat → used as-is
--   - If provider does not supply it → defaults to 0 (scores 0 points)
--   - No code change needed when upgrading to a richer provider
--
-- Edge case (CDC 6.6): rows where is_first_match_of_round = false are kept
-- here but excluded in the gold layer (mart_fantasy_points).

{{ config(materialized='table') }}

with source as (
    select * from {{ ref('raw_player_stats') }}
),

staged as (
    select
        -- Match and player identifiers
        cast(external_match_id      as varchar)     as match_external_id,
        cast(external_player_id     as varchar)     as player_external_id,
        cast(player_name            as varchar)     as player_name,
        cast(team_id                as varchar)     as team_external_id,
        cast(position_played        as varchar)     as position_played,
        cast(minutes_played         as integer)     as minutes_played,

        -- Attack stats (CDC 10.1)
        cast(tries                  as integer)     as tries,
        cast(try_assists            as integer)     as try_assists,
        -- metres_carried: COALESCE — provider may not supply (+0.1/metre)
        coalesce(cast(metres_carried    as integer), 0) as metres_carried,
        -- offloads: COALESCE — provider may not supply (+1 each)
        coalesce(cast(offloads          as integer), 0) as offloads,
        cast(drop_goals             as integer)     as drop_goals,

        -- Kicker stats — only scored if player is designated kicker in roster
        -- Kicker designation is managed in FastAPI/PostgreSQL, not in dbt
        cast(conversions_made       as integer)     as conversions_made,
        cast(conversions_missed     as integer)     as conversions_missed,
        cast(penalties_made         as integer)     as penalties_made,
        cast(penalties_missed       as integer)     as penalties_missed,

        -- Conditional attack stat (CDC 10.1 — requires provider support)
        coalesce(cast(fifty_twentytwo   as integer), 0) as fifty_twentytwo,

        -- Defence stats (CDC 10.2)
        -- tackles: COALESCE — provider may not supply (+0.5 each)
        coalesce(cast(tackles           as integer), 0) as tackles,
        -- dominant_tackles: COALESCE — conditional (+1 each)
        coalesce(cast(dominant_tackles  as integer), 0) as dominant_tackles,
        -- turnovers_won: COALESCE — provider may not supply (+2 each)
        coalesce(cast(turnovers_won     as integer), 0) as turnovers_won,
        -- lineout_steals: COALESCE — conditional (+2 each)
        coalesce(cast(lineout_steals    as integer), 0) as lineout_steals,
        -- penalties_conceded: COALESCE — provider may not supply (-1 each)
        coalesce(cast(penalties_conceded as integer), 0) as penalties_conceded,
        cast(yellow_cards           as integer)     as yellow_cards,
        cast(red_cards              as integer)     as red_cards,

        -- Edge case flag (CDC 6.6): player plays two matches in same round
        -- Gold layer excludes stats where this is false
        cast(is_first_match_of_round as boolean)   as is_first_match_of_round

    from source
)

select * from staged