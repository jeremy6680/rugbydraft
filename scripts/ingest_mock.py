"""
scripts/ingest_mock.py — Ingest mock connector data into data/raw/ as JSON files.

Calls MockRugbyConnector (or any BaseRugbyConnector) and writes the output
to data/raw/*.json. These files are then read by dbt bronze models via DuckDB.

Usage:
    python3 scripts/ingest_mock.py

Environment variables:
    RUGBY_DATA_SOURCE   — connector to use (default: mock)
    DUCKDB_RAW_PATH     — output directory (default: data/raw)

This script is the entry point for the daily_fixtures and daily_availability
crons (Coolify), and for the post_match_pipeline (Airflow).
In Phase 1, it always uses the mock connector.
"""

import json
import os
import sys
from pathlib import Path

# Add repo root to path so connectors/ is importable regardless of working directory
sys.path.insert(0, str(Path(__file__).parent.parent))

from connectors.mock import MockRugbyConnector
from connectors.base import BaseRugbyConnector


def get_connector() -> BaseRugbyConnector:
    """
    Return the appropriate connector based on RUGBY_DATA_SOURCE env var.

    Currently only 'mock' is implemented. Real connectors will be added
    in Phase 3 once the data provider is confirmed (DECISIONS.md D-012).
    """
    source = os.getenv("RUGBY_DATA_SOURCE", "mock")

    if source == "mock":
        return MockRugbyConnector()

    raise NotImplementedError(
        f"Connector '{source}' is not yet implemented. "
        f"Supported values: mock. "
        f"Real connectors will be added in Phase 3 once provider is confirmed."
    )


def write_json(data: list, path: Path) -> None:
    """Serialize a list of Pydantic models to JSON and write to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)

    # model_dump() serializes Pydantic v2 models — handles datetime, enums, etc.
    serialized = [
        item.model_dump(mode="json") if hasattr(item, "model_dump") else item
        for item in data
    ]

    with open(path, "w", encoding="utf-8") as f:
        json.dump(serialized, f, indent=2, ensure_ascii=False, default=str)

    print(f"  ✓ {path} ({len(serialized)} records)")


def main() -> None:
    """Run ingestion: fetch all data from connector and write to data/raw/."""
    raw_path = Path(os.getenv("DUCKDB_RAW_PATH", "data/raw"))

    print(f"Rugby data source: {os.getenv('RUGBY_DATA_SOURCE', 'mock')}")
    print(f"Output directory:  {raw_path}")
    print()

    connector = get_connector()

    # --- Fixtures (daily_fixtures cron) ---
    print("Fetching fixtures...")
    fixtures = connector.get_fixtures()
    write_json(fixtures, raw_path / "fixtures.json")

    # --- Player availability (daily_availability cron) ---
    print("Fetching player availability...")
    availability = connector.get_player_availability()
    write_json(availability, raw_path / "player_availability.json")

    # --- Match results (post_match_pipeline) ---
    print("Fetching match results...")
    results = connector.get_match_results()
    write_json(results, raw_path / "match_results.json")

    # --- Player stats for each finished match (post_match_pipeline) ---
    print("Fetching player stats...")
    all_stats = []
    for result in results:
        match_stats = connector.get_player_stats(result.external_id)
        all_stats.extend(match_stats)

    write_json(all_stats, raw_path / "player_stats.json")

    print()
    print(
        "Ingestion complete. Run 'dbt run' from dbt_project/ to process bronze → silver."
    )


if __name__ == "__main__":
    main()
