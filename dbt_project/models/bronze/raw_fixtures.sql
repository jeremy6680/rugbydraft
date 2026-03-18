-- raw_fixtures.sql — Bronze layer: fixtures as ingested from the rugby data connector
--
-- Source: data/raw/fixtures.json (written by scripts/ingest_mock.py or real connector)
-- No transformation — column names and types are provider-native
-- Silver layer (stg_fixtures) applies cleaning, typing, and canonical naming

{{ config(materialized='view') }}

select *
from read_json_auto('{{ env_var("DUCKDB_RAW_PATH", "../data/raw") }}/fixtures.json')