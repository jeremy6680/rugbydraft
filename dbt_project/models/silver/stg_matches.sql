-- stg_matches.sql — Silver layer: completed match results
--
-- Source: bronze.raw_matches
-- Only contains finished matches (status == 'finished')
-- Used by: post_match_pipeline to identify matches requiring score calculation

{{ config(materialized='table') }}

with source as (
    select * from {{ ref('raw_matches') }}
),

staged as (
    select
        cast(external_id        as varchar)     as match_external_id,
        cast(competition_id     as varchar)     as competition_external_id,
        cast(home_team_id       as varchar)     as home_team_external_id,
        cast(away_team_id       as varchar)     as away_team_external_id,
        cast(home_score         as integer)     as home_score,
        cast(away_score         as integer)     as away_score,
        cast(kickoff_utc        as timestamptz) as kickoff_utc,
        cast(round_number       as integer)     as round_number,
        cast(status             as varchar)     as status

    from source

    -- Silver only contains finished matches — upstream guarantee from connector
    where cast(status as varchar) = 'finished'
)

select * from staged