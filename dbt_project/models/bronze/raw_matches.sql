-- raw_matches.sql — Bronze layer: completed match results as ingested
--
-- Source: data/raw/match_results.json
-- Contains only finished matches (status == 'finished')
-- Used by post_match_pipeline to detect which matches need scoring

{{ config(materialized='view') }}

select *
from read_json_auto('{{ env_var("DUCKDB_RAW_PATH", "../data/raw") }}/match_results.json')