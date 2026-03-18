-- stg_fixtures.sql — Silver layer: cleaned and typed fixtures
--
-- Source: bronze.raw_fixtures
-- Canonical column names — independent of data provider field naming
-- Used by: daily_fixtures cron output, draft engine (competition/round context)

{{ config(materialized='table') }}

with source as (
    select * from {{ ref('raw_fixtures') }}
),

staged as (
    select
        -- Identifiers
        cast(external_id        as varchar)     as fixture_external_id,
        cast(competition_id     as varchar)     as competition_external_id,
        cast(competition_name   as varchar)     as competition_name,

        -- Teams
        cast(home_team_id       as varchar)     as home_team_external_id,
        cast(home_team_name     as varchar)     as home_team_name,
        cast(away_team_id       as varchar)     as away_team_external_id,
        cast(away_team_name     as varchar)     as away_team_name,

        -- Timing
        cast(kickoff_utc        as timestamptz) as kickoff_utc,
        cast(season             as varchar)     as season,
        cast(round_number       as integer)     as round_number,

        -- Status
        cast(status             as varchar)     as status,

        -- Scores (null when match not yet finished)
        cast(home_score         as integer)     as home_score,
        cast(away_score         as integer)     as away_score

    from source
)

select * from staged