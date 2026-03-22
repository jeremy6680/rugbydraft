# airflow/tests/test_dag_structure.py
"""Structural tests for the post_match_pipeline DAG.

These tests verify DAG integrity without requiring a live Airflow instance,
database connection, or Docker environment. They run in CI via pytest.

What is tested:
- DAG loads without import errors
- All expected tasks are present
- Task dependencies match the specified execution order
- No cycles exist in the task graph
- Retry configuration on ingest task is correct
- ShortCircuitOperator is used for detect task
- AtomicCommitOperator is used for commit task
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup — mirrors the Docker container PYTHONPATH
# ---------------------------------------------------------------------------

# Repo root (three levels up from this file)
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Add project root so connectors/ and scripts/ are importable
_PROJECT_ROOT = _REPO_ROOT
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Add airflow/plugins so operators/ is importable (mirrors Airflow plugin loading)
_PLUGINS_DIR = _REPO_ROOT / "airflow" / "plugins"
if str(_PLUGINS_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGINS_DIR))

# Add airflow/dags so the DAG module is importable directly
_DAGS_DIR = _REPO_ROOT / "airflow" / "dags"
if str(_DAGS_DIR) not in sys.path:
    sys.path.insert(0, str(_DAGS_DIR))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def dag():
    """Load and return the post_match_pipeline DAG.

    Uses environment variable stubs so the DAG loads without a live
    Airflow metadata database or data provider credentials.
    """
    env_stubs = {
        "RUGBY_DATA_SOURCE": "mock",
        "DBT_TARGET": "ci",
        "SUPABASE_DB_HOST": "localhost",
        "SUPABASE_DB_PORT": "5432",
        "SUPABASE_DB_NAME": "rugbydraft_test",
        "SUPABASE_DB_USER": "test",
        "SUPABASE_DB_PASSWORD": "test",
        "FASTAPI_INTERNAL_URL": "http://localhost:8000",
        "PIPELINE_NOTIFY_SECRET": "test-secret",
    }

    with patch.dict(os.environ, env_stubs):
        # Import the DAG module — this executes the DAG definition at module level
        import post_match_pipeline as dag_module  # noqa: PLC0415

        # Airflow registers DAGs in a global DagBag on import
        # We retrieve ours directly from the module's globals
        loaded_dag = dag_module.dag
    return loaded_dag


# ---------------------------------------------------------------------------
# DAG-level tests
# ---------------------------------------------------------------------------

class TestDagLoads:
    """Verify the DAG loads cleanly without import or definition errors."""

    def test_dag_id(self, dag):
        """DAG id must match the expected identifier."""
        assert dag.dag_id == "post_match_pipeline"

    def test_dag_has_no_import_errors(self, dag):
        """DAG must not carry import errors."""
        # Airflow sets dag.fileloc on successful load
        assert dag.fileloc is not None

    def test_catchup_disabled(self, dag):
        """catchup must be False — no backfill on first deploy."""
        assert dag.catchup is False

    def test_max_active_runs(self, dag):
        """Only one concurrent run allowed — prevents pipeline collisions."""
        assert dag.max_active_runs == 1

    def test_schedule_interval(self, dag):
        """Pipeline runs every 30 minutes on weekends only."""
        assert dag.schedule_interval == "*/30 * * * 6,0"


# ---------------------------------------------------------------------------
# Task presence tests
# ---------------------------------------------------------------------------

EXPECTED_TASK_IDS = [
    "detect_finished_matches",
    "ingest_match_stats",
    "dbt_bronze_silver",
    "export_silver_to_pg",
    "dbt_gold",
    "atomic_commit",
    "notify_scores_ready",
]


class TestTaskPresence:
    """Verify all expected tasks exist in the DAG."""

    def test_task_count(self, dag):
        """DAG must contain exactly the expected number of tasks."""
        assert len(dag.tasks) == len(EXPECTED_TASK_IDS)

    @pytest.mark.parametrize("task_id", EXPECTED_TASK_IDS)
    def test_task_exists(self, dag, task_id):
        """Each expected task must be present in the DAG."""
        task_ids = {task.task_id for task in dag.tasks}
        assert task_id in task_ids, (
            f"Task '{task_id}' not found in DAG. "
            f"Found tasks: {sorted(task_ids)}"
        )


# ---------------------------------------------------------------------------
# Task dependency tests
# ---------------------------------------------------------------------------

class TestTaskDependencies:
    """Verify the execution order is correct and strictly linear."""

    def _get_task(self, dag, task_id: str):
        """Helper to retrieve a task by id."""
        return dag.get_task(task_id)

    def test_detect_has_no_upstream(self, dag):
        """detect_finished_matches is the entry point — no upstream tasks."""
        task = self._get_task(dag, "detect_finished_matches")
        assert len(task.upstream_task_ids) == 0

    def test_ingest_depends_on_detect(self, dag):
        """ingest_match_stats must run after detect_finished_matches."""
        task = self._get_task(dag, "ingest_match_stats")
        assert "detect_finished_matches" in task.upstream_task_ids

    def test_dbt_bronze_silver_depends_on_ingest(self, dag):
        """dbt_bronze_silver must run after ingest_match_stats."""
        task = self._get_task(dag, "dbt_bronze_silver")
        assert "ingest_match_stats" in task.upstream_task_ids

    def test_export_silver_depends_on_dbt_bronze_silver(self, dag):
        """export_silver_to_pg must run after dbt_bronze_silver."""
        task = self._get_task(dag, "export_silver_to_pg")
        assert "dbt_bronze_silver" in task.upstream_task_ids

    def test_dbt_gold_depends_on_export_silver(self, dag):
        """dbt_gold must run after export_silver_to_pg."""
        task = self._get_task(dag, "dbt_gold")
        assert "export_silver_to_pg" in task.upstream_task_ids

    def test_atomic_commit_depends_on_dbt_gold(self, dag):
        """atomic_commit must run after dbt_gold."""
        task = self._get_task(dag, "atomic_commit")
        assert "dbt_gold" in task.upstream_task_ids

    def test_notify_depends_on_atomic_commit(self, dag):
        """notify_scores_ready must run after atomic_commit."""
        task = self._get_task(dag, "notify_scores_ready")
        assert "atomic_commit" in task.upstream_task_ids

    def test_notify_has_no_downstream(self, dag):
        """notify_scores_ready is the terminal task — no downstream tasks."""
        task = self._get_task(dag, "notify_scores_ready")
        assert len(task.downstream_task_ids) == 0

    def test_no_cycles(self, dag):
            """DAG must be acyclic — Airflow requirement."""
            # In Airflow 2.7, cycle detection is done via topological sort.
            # If the DAG contains a cycle, this raises a CycleError.
            from airflow.utils.dag_cycle_tester import check_cycle
            try:
                check_cycle(dag)
            except Exception as exc:  # noqa: BLE001
                pytest.fail(f"DAG contains a cycle: {exc}")


# ---------------------------------------------------------------------------
# Task configuration tests
# ---------------------------------------------------------------------------

class TestTaskConfiguration:
    """Verify critical task-level settings."""

    def test_ingest_retries(self, dag):
        """ingest_match_stats must have 3 retries for API resilience."""
        task = dag.get_task("ingest_match_stats")
        assert task.retries == 3

    def test_ingest_exponential_backoff(self, dag):
        """ingest_match_stats must use exponential backoff."""
        task = dag.get_task("ingest_match_stats")
        assert task.retry_exponential_backoff is True

    def test_detect_is_short_circuit(self, dag):
        """detect_finished_matches must be a ShortCircuitOperator."""
        from airflow.operators.python import ShortCircuitOperator
        task = dag.get_task("detect_finished_matches")
        assert isinstance(task, ShortCircuitOperator)

    def test_dbt_bronze_silver_target(self, dag):
        """dbt_bronze_silver must target 'ci' (DuckDB)."""
        from operators.dbt_operator import DbtRunOperator
        task = dag.get_task("dbt_bronze_silver")
        assert isinstance(task, DbtRunOperator)
        assert task.target == "ci"
        assert "bronze" in task.select
        assert "silver" in task.select

    def test_dbt_gold_target(self, dag):
        """dbt_gold must target 'prod' (PostgreSQL)."""
        from operators.dbt_operator import DbtRunOperator
        task = dag.get_task("dbt_gold")
        assert isinstance(task, DbtRunOperator)
        assert task.target == "prod"
        assert "gold" in task.select

    def test_atomic_commit_operator_type(self, dag):
        """atomic_commit must use AtomicCommitOperator."""
        from operators.atomic_commit_operator import AtomicCommitOperator
        task = dag.get_task("atomic_commit")
        assert isinstance(task, AtomicCommitOperator)

    def test_atomic_commit_round_id_template(self, dag):
        """atomic_commit must pull round_id from XCom via Jinja template."""
        task = dag.get_task("atomic_commit")
        assert "xcom_pull" in task.round_id
        assert "detect_finished_matches" in task.round_id