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
full on each pipeline run — no incremental logic.

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

import io
import logging
import os
import sys
import time
from typing import Final

import duckdb
import psycopg2
import psycopg2.extensions

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

SILVER_TABLES: Final[list[str]] = [
    "stg_match_stats",
    "stg_matches",
    "stg_players",
    "stg_fixtures",
    "stg_player_availability",
]

PIPELINE_PREFIX: Final[str] = "pipeline_"
DEFAULT_DUCKDB_PATH: Final[str] = "data/rugbydraft.duckdb"
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


def get_pg_conn() -> psycopg2.extensions.connection:
    """Build a psycopg2 connection to PostgreSQL (Supabase).

    Reads credentials from environment variables. Raises SystemExit if any
    required variable is missing.

    Returns:
        Open psycopg2 connection.
    """
    required_vars = ["SUPABASE_DB_HOST", "SUPABASE_DB_USER", "SUPABASE_DB_PASSWORD"]
    missing = [v for v in required_vars if not os.environ.get(v)]
    if missing:
        log.error("Missing required environment variables: %s", ", ".join(missing))
        log.error("Set them in .env and run: set -a && source .env && set +a")
        sys.exit(1)

    return psycopg2.connect(
        host=os.environ["SUPABASE_DB_HOST"],
        port=5432,
        dbname="postgres",
        user=os.environ["SUPABASE_DB_USER"],
        password=os.environ["SUPABASE_DB_PASSWORD"],
        sslmode="require",
    )


def export_table(
    duck_conn: duckdb.DuckDBPyConnection,
    pg_conn: psycopg2.extensions.connection,
    table_name: str,
) -> int:
    """Export one silver table from DuckDB to PostgreSQL.

    Strategy:
      1. Read full table from DuckDB into a pandas DataFrame.
      2. DROP + CREATE the destination table in PostgreSQL using TEXT columns
         — guarantees schema always matches DuckDB silver, avoids stale columns.
      3. Stream rows via cur.copy_expert() (CSV over stdin) — fastest bulk
         insert, no pandas/SQLAlchemy version dependency.
      4. On any error: rollback the transaction so subsequent tables are
         not blocked by a failed transaction state.

    Args:
        duck_conn: Open DuckDB connection.
        pg_conn: Open psycopg2 connection.
        table_name: Silver table name (without schema prefix).

    Returns:
        Number of rows exported.

    Raises:
        SystemExit: If the silver table does not exist in DuckDB.
        Exception: Re-raises after rollback on PostgreSQL errors.
    """
    destination = f"{PIPELINE_PREFIX}{table_name}"
    qualified = f"{DUCKDB_SILVER_SCHEMA}.{table_name}"

    log.info("Exporting %s → %s ...", qualified, destination)
    t0 = time.monotonic()

    # Step 1: read from DuckDB.
    try:
        df = duck_conn.execute(f"SELECT * FROM {qualified}").fetchdf()
    except duckdb.CatalogException:
        log.error(
            "Table %s not found in DuckDB. "
            "Run: dbt run --target ci --select bronze silver",
            qualified,
        )
        sys.exit(1)

    row_count = len(df)
    columns = list(df.columns)

    if row_count == 0:
        log.warning(
            "%s is empty — exporting empty table. "
            "This is expected when using the mock connector.",
            table_name,
        )

    # Step 2: DROP + CREATE with TEXT columns.
    # TEXT for all columns: silver values are string/int/bool/float — all
    # safely representable as TEXT. dbt gold casts them via PostgreSQL
    # implicit conversion when needed.
    col_defs = ", ".join(f'"{col}" TEXT' for col in columns)

    try:
        with pg_conn.cursor() as cur:
            cur.execute(f'DROP TABLE IF EXISTS public."{destination}"')
            cur.execute(f'CREATE TABLE public."{destination}" ({col_defs})')

            if row_count > 0:
                # Step 3: stream via copy_expert (CSV from StringIO buffer).
                # copy_expert() is the correct psycopg2 API for COPY FROM STDIN.
                # cur.execute("COPY ... FROM STDIN") is forbidden — copy_expert only.
                buffer = io.StringIO()
                df.to_csv(buffer, index=False, header=False, na_rep="")
                buffer.seek(0)

                col_list = ", ".join(f'"{c}"' for c in columns)
                cur.copy_expert(
                    f'COPY public."{destination}" ({col_list}) '
                    f"FROM STDIN WITH (FORMAT CSV, NULL '')",
                    buffer,
                )

        pg_conn.commit()

    except Exception as exc:
        # Step 4: rollback on error so subsequent table exports are not
        # blocked by the aborted transaction state.
        pg_conn.rollback()
        raise exc

    elapsed = time.monotonic() - t0
    log.info("  ✓ %d rows exported in %.2fs", row_count, elapsed)
    return row_count


def verify_export(
    pg_conn: psycopg2.extensions.connection,
    table_name: str,
) -> bool:
    """Verify the exported table exists and has rows in PostgreSQL.

    Args:
        pg_conn: Open psycopg2 connection.
        table_name: Silver table name (without prefix).

    Returns:
        True if the table exists and is readable, False otherwise.
    """
    destination = f"{PIPELINE_PREFIX}{table_name}"
    try:
        with pg_conn.cursor() as cur:
            cur.execute(f'SELECT COUNT(*) FROM public."{destination}"')
            count = cur.fetchone()[0]
        log.info("  ✓ Verified %s: %d rows in PostgreSQL", destination, count)
        return True
    except Exception as exc:  # noqa: BLE001
        pg_conn.rollback()
        log.error("  ✗ Verification failed for %s: %s", destination, exc)
        return False


def main() -> None:
    """Export all silver tables from DuckDB to PostgreSQL.

    Raises:
        SystemExit: On any fatal error.
    """
    log.info("=" * 60)
    log.info("export_silver_to_pg — DuckDB → PostgreSQL bridge")
    log.info("=" * 60)

    duckdb_path = get_duckdb_path()
    log.info("DuckDB source: %s", duckdb_path)

    pg_conn = get_pg_conn()
    log.info("PostgreSQL target: %s", os.environ["SUPABASE_DB_HOST"])

    duck_conn = duckdb.connect(duckdb_path, read_only=True)

    total_rows = 0
    failed_tables: list[str] = []

    for table_name in SILVER_TABLES:
        try:
            rows = export_table(duck_conn, pg_conn, table_name)
            total_rows += rows
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001
            log.error("Unexpected error exporting %s: %s", table_name, exc)
            failed_tables.append(table_name)

    duck_conn.close()

    log.info("-" * 60)
    log.info("Verifying exports in PostgreSQL...")
    all_ok = all(verify_export(pg_conn, t) for t in SILVER_TABLES)

    pg_conn.close()

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
