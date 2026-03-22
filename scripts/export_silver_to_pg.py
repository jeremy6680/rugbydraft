"""
scripts/export_silver_to_pg.py
===============================
Exports dbt silver tables from DuckDB to PostgreSQL (Supabase).

This script is the bridge between the DuckDB pipeline (bronze + silver)
and the PostgreSQL gold models. It runs as step 3 of the Airflow
post_match_pipeline DAG, after `dbt run --target ci --select bronze silver`
and before `dbt run --target prod --select gold`.

Architecture (D-030):
    bronze + silver  →  DuckDB (read_json_auto, local files)
    export           →  this script (DuckDB → PostgreSQL)
    gold             →  PostgreSQL (joins silver + application tables)

Tables exported:
    stg_match_stats          →  pipeline_stg_match_stats
    stg_matches              →  pipeline_stg_matches
    stg_players              →  pipeline_stg_players
    stg_fixtures             →  pipeline_stg_fixtures
    stg_player_availability  →  pipeline_stg_player_availability

The destination tables are prefixed with `pipeline_` to distinguish them
from application tables managed by FastAPI. They are always replaced in
full on each pipeline run (if_exists='replace') — no incremental logic.

Usage:
    # From the project root:
    python scripts/export_silver_to_pg.py

    # With explicit DuckDB path:
    DUCKDB_PATH=data/rugbydraft.duckdb python scripts/export_silver_to_pg.py

Environment variables required (same as .env):
    DUCKDB_PATH           Path to the DuckDB file (default: data/rugbydraft.duckdb)
    SUPABASE_DB_HOST      PostgreSQL host (db.<ref>.supabase.co)
    SUPABASE_DB_USER      PostgreSQL user (postgres)
    SUPABASE_DB_PASSWORD  PostgreSQL password
"""

import logging
import os
import sys
import time
from typing import Final

import duckdb
import pandas as pd
import sqlalchemy
from sqlalchemy import text

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Silver tables to export. Order does not matter — no FK dependencies
# between these tables in the pipeline schema.
SILVER_TABLES: Final[list[str]] = [
    "stg_match_stats",
    "stg_matches",
    "stg_players",
    "stg_fixtures",
    "stg_player_availability",
]

# Prefix used for destination tables in PostgreSQL.
# Avoids naming conflicts with application tables.
PIPELINE_PREFIX: Final[str] = "pipeline_"

# Default DuckDB file path (relative to project root).
DEFAULT_DUCKDB_PATH: Final[str] = "data/rugbydraft.duckdb"

# dbt silver schema name in DuckDB.
# Must match the schema configured in dbt_project.yml for the ci target.
DUCKDB_SILVER_SCHEMA: Final[str] = "main_silver"


def get_duckdb_path() -> str:
    """Return the DuckDB file path from environment or default.

    Returns:
        Absolute or relative path to the DuckDB database file.

    Raises:
        SystemExit: If the file does not exist.
    """
    path = os.environ.get("DUCKDB_PATH", DEFAULT_DUCKDB_PATH)
    if not os.path.exists(path):
        log.error("DuckDB file not found: %s", path)
        log.error(
            "Run the dbt silver pipeline first: "
            "dbt run --target ci --select bronze silver"
        )
        sys.exit(1)
    return path


def get_pg_engine() -> sqlalchemy.engine.Engine:
    """Build a SQLAlchemy engine for PostgreSQL (Supabase).

    Reads credentials from environment variables. Raises SystemExit if any
    required variable is missing.

    Returns:
        SQLAlchemy Engine connected to the Supabase PostgreSQL instance.
    """
    required_vars = ["SUPABASE_DB_HOST", "SUPABASE_DB_USER", "SUPABASE_DB_PASSWORD"]
    missing = [v for v in required_vars if not os.environ.get(v)]
    if missing:
        log.error("Missing required environment variables: %s", ", ".join(missing))
        log.error("Set them in .env and run: set -a && source .env && set +a")
        sys.exit(1)

    host = os.environ["SUPABASE_DB_HOST"]
    user = os.environ["SUPABASE_DB_USER"]
    password = os.environ["SUPABASE_DB_PASSWORD"]

    url = (
        f"postgresql+psycopg2://{user}:{password}@{host}:5432/postgres?sslmode=require"
    )
    return sqlalchemy.create_engine(url, pool_pre_ping=True)


def export_table(
    duck_conn: duckdb.DuckDBPyConnection,
    pg_engine: sqlalchemy.engine.Engine,
    table_name: str,
) -> int:
    """Export one silver table from DuckDB to PostgreSQL.

    Reads the full table from DuckDB and writes it to PostgreSQL using
    pandas `to_sql` with `if_exists='replace'`. The destination table is
    always fully replaced — no incremental logic.

    Args:
        duck_conn: Open DuckDB connection.
        pg_engine: SQLAlchemy engine for PostgreSQL.
        table_name: Silver table name (without schema prefix).

    Returns:
        Number of rows exported.

    Raises:
        SystemExit: If the silver table does not exist in DuckDB (silver
            pipeline has not been run yet).
    """
    destination = f"{PIPELINE_PREFIX}{table_name}"
    qualified = f"{DUCKDB_SILVER_SCHEMA}.{table_name}"

    log.info("Exporting %s → %s ...", qualified, destination)
    t0 = time.monotonic()

    try:
        df: pd.DataFrame = duck_conn.execute(f"SELECT * FROM {qualified}").df()
    except duckdb.CatalogException:
        log.error(
            "Table %s not found in DuckDB. "
            "Run: dbt run --target ci --select bronze silver",
            qualified,
        )
        sys.exit(1)

    row_count = len(df)

    if row_count == 0:
        log.warning(
            "%s is empty — exporting empty table. "
            "This is expected when using the mock connector.",
            table_name,
        )

    # Write to PostgreSQL. Replaces the table entirely on each run.
    # chunksize prevents memory issues on large DataFrames.
    df.to_sql(
        name=destination,
        con=pg_engine,
        schema="public",
        if_exists="replace",
        index=False,
        chunksize=1000,
        method="multi",  # batch inserts — faster than row-by-row
    )

    elapsed = time.monotonic() - t0
    log.info("  ✓ %d rows exported in %.2fs", row_count, elapsed)
    return row_count


def verify_export(
    pg_engine: sqlalchemy.engine.Engine,
    table_name: str,
) -> bool:
    """Verify the exported table exists and has rows in PostgreSQL.

    Args:
        pg_engine: SQLAlchemy engine for PostgreSQL.
        table_name: Silver table name (without prefix).

    Returns:
        True if the table exists and is readable, False otherwise.
    """
    destination = f"{PIPELINE_PREFIX}{table_name}"
    try:
        with pg_engine.connect() as conn:
            result = conn.execute(text(f'SELECT COUNT(*) FROM public."{destination}"'))
            count = result.scalar()
        log.info("  ✓ Verified %s: %d rows in PostgreSQL", destination, count)
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("  ✗ Verification failed for %s: %s", destination, exc)
        return False


def main() -> None:
    """Export all silver tables from DuckDB to PostgreSQL.

    Raises:
        SystemExit: On any fatal error (missing file, missing env vars,
            DuckDB table not found, PostgreSQL connection failure).
    """
    log.info("=" * 60)
    log.info("export_silver_to_pg — DuckDB → PostgreSQL bridge")
    log.info("=" * 60)

    duckdb_path = get_duckdb_path()
    log.info("DuckDB source: %s", duckdb_path)

    pg_engine = get_pg_engine()
    log.info("PostgreSQL target: %s", os.environ["SUPABASE_DB_HOST"])

    # Open DuckDB connection (read-only — we never write to DuckDB here).
    duck_conn = duckdb.connect(duckdb_path, read_only=True)

    total_rows = 0
    failed_tables: list[str] = []

    for table_name in SILVER_TABLES:
        try:
            rows = export_table(duck_conn, pg_engine, table_name)
            total_rows += rows
        except SystemExit:
            # export_table calls sys.exit on fatal errors — re-raise.
            raise
        except Exception as exc:  # noqa: BLE001
            log.error("Unexpected error exporting %s: %s", table_name, exc)
            failed_tables.append(table_name)

    duck_conn.close()

    # Verify all exports landed correctly in PostgreSQL.
    log.info("-" * 60)
    log.info("Verifying exports in PostgreSQL...")
    all_ok = all(verify_export(pg_engine, t) for t in SILVER_TABLES)

    log.info("=" * 60)
    if failed_tables:
        log.error("Export FAILED for: %s", ", ".join(failed_tables))
        sys.exit(1)

    if not all_ok:
        log.error("Export verification FAILED — check PostgreSQL connection.")
        sys.exit(1)

    log.info(
        "Export complete. %d total rows across %d tables.",
        total_rows,
        len(SILVER_TABLES),
    )
    log.info("Next step: dbt run --target prod --select gold")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
