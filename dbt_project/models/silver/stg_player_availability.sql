-- stg_player_availability.sql — Silver layer: player availability status
--
-- Source: bronze.raw_player_availability
-- Updated daily by daily_availability cron (08:00 UTC via Coolify)
-- Used by: dashboard alerts, waiver/trade blocking rules (CDC 9.1, 9.2)

{{ config(materialized='table') }}

with source as (
    select * from {{ ref('raw_player_availability') }}
),

staged as (
    select
        cast(external_player_id     as varchar)     as player_external_id,
        cast(player_name            as varchar)     as player_name,
        cast(team_id                as varchar)     as team_external_id,
        cast(team_name              as varchar)     as team_name,
        cast(status                 as varchar)     as availability_status,

        -- Optional fields — null if provider does not supply
        cast(return_date            as date)        as return_date,
        cast(suspension_matches     as integer)     as suspension_matches,
        cast(notes                  as varchar)     as notes

    from source
)

select * from staged