-- stg_players.sql — Silver layer: player reference data
--
-- Source: bronze.raw_fixtures (player pool extracted from fixture team data)
-- In Phase 1 (mock): player list is embedded in the mock connector _PLAYERS dict
-- and written to data/raw/fixtures.json as context.
--
-- Note: in Phase 3, a dedicated get_players() method will be added to
-- BaseRugbyConnector and this model will source from raw_players.json instead.
-- For now, we extract distinct players from player_stats as the source of truth.

{{ config(materialized='table') }}

with source as (
    select * from {{ ref('raw_player_stats') }}
),

-- Extract distinct players from match stats
-- One row per player (deduplicated by external_player_id)
deduped as (
    select
        external_player_id,
        player_name,
        team_id,
        position_played,
        row_number() over (
            partition by external_player_id
            order by external_match_id
        ) as rn
    from source
),

staged as (
    select
        cast(external_player_id as varchar) as player_external_id,
        cast(player_name        as varchar) as player_name,
        cast(team_id            as varchar) as team_external_id,
        cast(position_played    as varchar) as position_type

    from deduped
    where rn = 1
)

select * from staged