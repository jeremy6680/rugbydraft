# airflow/dags/post_match_pipeline.py
"""Post-match pipeline DAG.

Orchestrates the full scoring pipeline after weekend matches:
    detect → ingest → bronze+silver (DuckDB) → export → gold (PostgreSQL)
    → atomic commit → notify

Schedule: every 30 minutes on Saturday and Sunday.
Data source: controlled by RUGBY_DATA_SOURCE env var (default: mock).

Dependencies between tasks are strict — any failure stops the pipeline.
Production data (fantasy_scores) is never partially updated (D-003).
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Any

import httpx
from airflow import DAG
from airflow.operators.python import PythonOperator, ShortCircuitOperator

# Custom operators — loaded from airflow/plugins/operators/
from operators.dbt_operator import DbtRunOperator
from operators.atomic_commit_operator import AtomicCommitOperator


# ---------------------------------------------------------------------------
# DAG default arguments
# ---------------------------------------------------------------------------

DEFAULT_ARGS: dict[str, Any] = {
    "owner": "rugbydraft",
    "depends_on_past": False,
    "email_on_failure": False,  # no SMTP in local dev
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
    # Start date in the past so Airflow does not backfill on first deploy
    "start_date": datetime(2025, 1, 1),
}

# ---------------------------------------------------------------------------
# Helper functions (called by PythonOperator tasks)
# ---------------------------------------------------------------------------

# Add project root to sys.path so connectors and scripts are importable.
# This mirrors the PYTHONPATH set in the Dockerfile.
_PROJECT_ROOT = "/opt/airflow/project"
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def detect_finished_matches(**context: Any) -> bool:
    """Check for finished matches that have not yet been scored.

    Loads the active connector (mock or real provider) and queries for
    matches that ended since the last pipeline run.

    Pushes 'round_id' to XCom if matches are found.

    Returns:
        True if unscored finished matches exist (pipeline continues).
        False if no matches found (ShortCircuitOperator stops the DAG run).
    """
    # Dynamically load the connector based on env var
    data_source = os.getenv("RUGBY_DATA_SOURCE", "mock")
    connector = _load_connector(data_source)

    finished = connector.get_finished_unscored_matches()

    if not finished:
        context["task_instance"].log.info(
            "No finished unscored matches found — skipping pipeline run."
        )
        return False

    # Push round_id to XCom for downstream tasks
    # Use the round_id from the first finished match (all matches in a run
    # belong to the same round by construction)
    round_id = finished[0]["round_id"]
    context["task_instance"].xcom_push(key="round_id", value=round_id)
    context["task_instance"].log.info(
        "Found %d finished match(es) for round_id=%s", len(finished), round_id
    )
    return True


def ingest_match_stats(**context: Any) -> None:
    """Fetch player-level match statistics and write to data/raw/.

    Reads round_id from XCom (set by detect_finished_matches).
    Calls the active connector's fetch_match_stats() method.
    Writes raw JSON files consumed by dbt bronze models.

    Retries: 3 attempts with exponential backoff (see DAG task config).
    """
    data_source = os.getenv("RUGBY_DATA_SOURCE", "mock")
    connector = _load_connector(data_source)

    round_id = context["task_instance"].xcom_pull(
        task_ids="detect_finished_matches", key="round_id"
    )

    context["task_instance"].log.info(
        "Ingesting match stats for round_id=%s via connector=%s",
        round_id,
        data_source,
    )

    connector.fetch_match_stats(round_id=round_id)

    context["task_instance"].log.info(
        "Ingest complete — raw JSON files written to data/raw/"
    )


def export_silver_to_pg(**context: Any) -> None:
    """Export dbt silver tables from DuckDB to PostgreSQL pipeline_stg_* tables.

    Runs scripts/export_silver_to_pg.py as a subprocess.
    This is the bridge between dbt silver (DuckDB) and dbt gold (PostgreSQL).
    See DECISIONS.md D-030.
    """
    script_path = os.path.join(_PROJECT_ROOT, "scripts", "export_silver_to_pg.py")

    context["task_instance"].log.info("Running export_silver_to_pg.py")

    result = subprocess.run(
        [sys.executable, script_path],
        capture_output=True,
        text=True,
    )

    # Log full output for debugging
    for line in result.stdout.splitlines():
        context["task_instance"].log.info("[export] %s", line)

    if result.returncode != 0:
        raise RuntimeError(
            f"export_silver_to_pg.py failed.\n"
            f"Stderr: {result.stderr[:1000]}"
        )

    context["task_instance"].log.info("Silver → PostgreSQL export complete")


def notify_scores_ready(**context: Any) -> None:
    """Notify FastAPI that scores are ready for the completed round.

    POSTs to FASTAPI_INTERNAL_URL/internal/pipeline/notify.
    FastAPI then broadcasts to Supabase Realtime so the frontend
    removes the 'scores being processed' indicator.

    Failure here does NOT block the pipeline — scores are already
    committed. Notification failure is logged as a warning only.
    """
    round_id = context["task_instance"].xcom_pull(
        task_ids="detect_finished_matches", key="round_id"
    )

    fastapi_url = os.getenv(
        "FASTAPI_INTERNAL_URL", "http://host.docker.internal:8000"
    )
    secret = os.getenv("PIPELINE_NOTIFY_SECRET", "")
    endpoint = f"{fastapi_url}/internal/pipeline/notify"

    context["task_instance"].log.info(
        "Notifying FastAPI at %s for round_id=%s", endpoint, round_id
    )

    try:
        response = httpx.post(
            endpoint,
            json={"round_id": round_id, "status": "complete"},
            headers={"X-Pipeline-Secret": secret},
            timeout=10.0,
        )
        response.raise_for_status()
        context["task_instance"].log.info(
            "FastAPI notified successfully (status=%d)", response.status_code
        )
    except httpx.HTTPError as exc:
        # Notification failure is non-blocking — scores are already in production
        context["task_instance"].log.warning(
            "Failed to notify FastAPI (non-blocking): %s", exc
        )


def _load_connector(data_source: str) -> Any:
    """Dynamically load the active rugby data connector.

    Args:
        data_source: Value of RUGBY_DATA_SOURCE env var ('mock' or provider name).

    Returns:
        An instance of a BaseRugbyConnector subclass.

    Raises:
        ImportError: If the connector module cannot be found.
        ValueError: If data_source is not a recognised connector name.
    """
    connector_map = {
        "mock": ("connectors.mock", "MockRugbyConnector"),
        # Real provider connectors added here when confirmed (D-012)
        # "statscore": ("connectors.statscore", "StatscoreConnector"),
        # "dsg": ("connectors.dsg", "DSGConnector"),
    }

    if data_source not in connector_map:
        raise ValueError(
            f"Unknown data source: '{data_source}'. "
            f"Valid options: {list(connector_map.keys())}"
        )

    module_path, class_name = connector_map[data_source]
    module = importlib.import_module(module_path)
    connector_class = getattr(module, class_name)
    return connector_class()


# ---------------------------------------------------------------------------
# DAG definition
# ---------------------------------------------------------------------------

with DAG(
    dag_id="post_match_pipeline",
    description="Detect → ingest → bronze+silver → gold → atomic commit → notify",
    # Every 30 minutes on Saturday (6) and Sunday (0)
    schedule_interval="*/30 * * * 6,0",
    default_args=DEFAULT_ARGS,
    # Do not backfill missed runs on first deploy
    catchup=False,
    # Only one run at a time — prevents concurrent pipeline runs
    max_active_runs=1,
    tags=["pipeline", "scoring", "post-match"],
) as dag:

    # ------------------------------------------------------------------
    # Task 1: detect finished unscored matches
    # ShortCircuitOperator: stops all downstream tasks if returns False
    # ------------------------------------------------------------------
    detect = ShortCircuitOperator(
        task_id="detect_finished_matches",
        python_callable=detect_finished_matches,
        provide_context=True,
    )

    # ------------------------------------------------------------------
    # Task 2: ingest raw match stats from data provider
    # 3 retries with exponential backoff — API calls can fail transiently
    # ------------------------------------------------------------------
    ingest = PythonOperator(
        task_id="ingest_match_stats",
        python_callable=ingest_match_stats,
        provide_context=True,
        retries=3,
        retry_delay=timedelta(minutes=1),
        retry_exponential_backoff=True,
        max_retry_delay=timedelta(minutes=10),
    )

    # ------------------------------------------------------------------
    # Task 3: dbt bronze + silver in DuckDB
    # ------------------------------------------------------------------
    dbt_bronze_silver = DbtRunOperator(
        task_id="dbt_bronze_silver",
        target="ci",
        select="bronze silver",
    )

    # ------------------------------------------------------------------
    # Task 4: export silver tables DuckDB → PostgreSQL pipeline_stg_*
    # ------------------------------------------------------------------
    export_silver = PythonOperator(
        task_id="export_silver_to_pg",
        python_callable=export_silver_to_pg,
        provide_context=True,
    )

    # ------------------------------------------------------------------
    # Task 5: dbt gold in PostgreSQL (fantasy points + leaderboard)
    # ------------------------------------------------------------------
    dbt_gold = DbtRunOperator(
        task_id="dbt_gold",
        target="prod",
        select="gold",
    )

    # ------------------------------------------------------------------
    # Task 6: atomic commit staging → production
    # round_id pulled from XCom via Jinja template
    # ------------------------------------------------------------------
    commit = AtomicCommitOperator(
        task_id="atomic_commit",
        round_id="{{ ti.xcom_pull(task_ids='detect_finished_matches', key='round_id') }}",
    )

    # ------------------------------------------------------------------
    # Task 7: notify FastAPI — non-blocking, failure does not fail the DAG
    # ------------------------------------------------------------------
    notify = PythonOperator(
        task_id="notify_scores_ready",
        python_callable=notify_scores_ready,
        provide_context=True,
    )

    # ------------------------------------------------------------------
    # Task dependencies — strict linear chain
    # ------------------------------------------------------------------
    detect >> ingest >> dbt_bronze_silver >> export_silver >> dbt_gold >> commit >> notify