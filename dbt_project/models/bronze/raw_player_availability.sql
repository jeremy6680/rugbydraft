-- raw_player_availability.sql — Bronze layer: player availability status
--
-- Source: data/raw/player_availability.json
-- Updated daily by daily_availability cron (08:00 UTC via Coolify)
-- Statuses: fit / injured / suspended / doubtful / unavailable

{{ config(materialized='view') }}

select *
from read_json_auto('{{ env_var("DUCKDB_RAW_PATH", "../data/raw") }}/player_availability.json')