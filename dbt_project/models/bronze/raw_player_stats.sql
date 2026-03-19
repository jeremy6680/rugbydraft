-- raw_player_stats.sql — Bronze layer: individual player stats per match
--
-- Source: data/raw/player_stats.json
-- One row per player per match — all scoring stats from CDC section 10
-- Conditional stats (dominant_tackles, fifty_twentytwo, etc.) may be null
-- Silver layer applies COALESCE and canonical naming

{{ config(materialized='view') }}

select *
from read_json_auto('{{ env_var("DUCKDB_RAW_PATH", "../data/raw") }}/player_stats.json')