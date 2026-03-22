# airflow/plugins/operators/atomic_commit_operator.py
"""Atomic commit operator: fantasy_scores_staging → fantasy_scores.

Implements the staging → production pattern described in D-003.
Executes a single PostgreSQL transaction:
  1. DELETE production rows for the target round
  2. INSERT from staging into production
  3. TRUNCATE staging table

If any step fails, PostgreSQL rolls back automatically.
Production data is never partially updated.
"""

from __future__ import annotations

import os
from typing import Any

import psycopg2
import psycopg2.extras
from airflow.models import BaseOperator
from airflow.utils.decorators import apply_defaults


# SQL executed inside the atomic transaction.
# Uses a single round_id parameter to scope the operation.
_SQL_DELETE_PRODUCTION = """
    DELETE FROM fantasy_scores
    WHERE round_id = %(round_id)s;
"""

_SQL_INSERT_FROM_STAGING = """
    INSERT INTO fantasy_scores (
        id,
        roster_id,
        player_id,
        round_id,
        league_id,
        base_points,
        captain_bonus,
        total_points,
        is_captain,
        is_kicker,
        stat_snapshot,
        created_at
    )
    SELECT
        id,
        roster_id,
        player_id,
        round_id,
        league_id,
        base_points,
        captain_bonus,
        total_points,
        is_captain,
        is_kicker,
        stat_snapshot,
        created_at
    FROM fantasy_scores_staging
    WHERE round_id = %(round_id)s;
"""

_SQL_TRUNCATE_STAGING = """
    TRUNCATE TABLE fantasy_scores_staging;
"""

_SQL_SET_PIPELINE_STATUS = """
    INSERT INTO pipeline_status (round_id, status, updated_at)
    VALUES (%(round_id)s, %(status)s, NOW())
    ON CONFLICT (round_id)
    DO UPDATE SET status = EXCLUDED.status, updated_at = EXCLUDED.updated_at;
"""


class AtomicCommitOperator(BaseOperator):
    """Atomically promote fantasy scores from staging to production.

    Reads connection parameters from environment variables:
        SUPABASE_DB_HOST, SUPABASE_DB_PORT, SUPABASE_DB_NAME,
        SUPABASE_DB_USER, SUPABASE_DB_PASSWORD

    Args:
        round_id: The competition round UUID to commit scores for.
            Passed as a string; can use Jinja templating.

    Example:
        AtomicCommitOperator(
            task_id="atomic_commit",
            round_id="{{ ti.xcom_pull(task_ids='detect_finished_matches', key='round_id') }}",
        )

    Raises:
        RuntimeError: If required environment variables are missing.
        psycopg2.Error: If the PostgreSQL transaction fails (auto-rollback).
    """

    # round_id supports Jinja templating from XCom
    template_fields = ("round_id",)

    # UI color — green for the final commit step
    ui_color = "#34a853"

    @apply_defaults
    def __init__(
        self,
        round_id: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.round_id = round_id

    def execute(self, context: dict[str, Any]) -> None:
        """Execute the atomic staging → production transaction.

        Args:
            context: Airflow task context (contains XCom, execution_date, etc.)

        Raises:
            RuntimeError: If DB connection env vars are missing.
            psycopg2.Error: On any PostgreSQL error — triggers auto-rollback.
        """
        conn = self._get_connection()

        try:
            with conn:
                # conn as context manager: commits on exit, rolls back on exception
                with conn.cursor() as cur:
                    self.log.info(
                        "Starting atomic commit for round_id=%s", self.round_id
                    )

                    # Step 1: set pipeline status to 'processing'
                    # Frontend polls this to show "scores being processed" indicator
                    cur.execute(
                        _SQL_SET_PIPELINE_STATUS,
                        {"round_id": self.round_id, "status": "processing"},
                    )
                    self.log.info("Pipeline status set to 'processing'")

                    # Step 2: delete existing production scores for this round
                    # (re-run safety: pipeline can run multiple times on same round)
                    cur.execute(_SQL_DELETE_PRODUCTION, {"round_id": self.round_id})
                    deleted_count = cur.rowcount
                    self.log.info(
                        "Deleted %d existing production rows for round_id=%s",
                        deleted_count,
                        self.round_id,
                    )

                    # Step 3: insert from staging into production
                    cur.execute(_SQL_INSERT_FROM_STAGING, {"round_id": self.round_id})
                    inserted_count = cur.rowcount
                    self.log.info(
                        "Inserted %d rows from staging into fantasy_scores",
                        inserted_count,
                    )

                    if inserted_count == 0:
                        # Warn but don't fail — round may have no scored players yet
                        self.log.warning(
                            "No rows inserted for round_id=%s — staging may be empty",
                            self.round_id,
                        )

                    # Step 4: truncate staging table (cleanup for next pipeline run)
                    cur.execute(_SQL_TRUNCATE_STAGING)
                    self.log.info("Staging table truncated")

                    # Step 5: mark pipeline as complete
                    cur.execute(
                        _SQL_SET_PIPELINE_STATUS,
                        {"round_id": self.round_id, "status": "complete"},
                    )
                    self.log.info("Pipeline status set to 'complete'")

            # Transaction committed — log summary
            self.log.info(
                "Atomic commit succeeded: %d rows promoted to production "
                "(round_id=%s, deleted_before=%d)",
                inserted_count,
                self.round_id,
                deleted_count,
            )

        except psycopg2.Error as exc:
            # psycopg2 rolls back automatically when conn context manager exits
            # on exception — production data is safe.
            self.log.error(
                "Atomic commit FAILED for round_id=%s — rollback applied. Error: %s",
                self.round_id,
                exc,
            )
            raise

        finally:
            conn.close()

    def _get_connection(self) -> psycopg2.extensions.connection:
        """Build a psycopg2 connection from environment variables.

        Returns:
            Open psycopg2 connection with autocommit=False.

        Raises:
            RuntimeError: If any required env var is missing.
        """
        required_vars = [
            "SUPABASE_DB_HOST",
            "SUPABASE_DB_PORT",
            "SUPABASE_DB_NAME",
            "SUPABASE_DB_USER",
            "SUPABASE_DB_PASSWORD",
        ]
        missing = [v for v in required_vars if not os.getenv(v)]
        if missing:
            raise RuntimeError(
                f"Missing required environment variables: {', '.join(missing)}. "
                "Set them in airflow/.env before running the atomic commit task."
            )

        conn = psycopg2.connect(
            host=os.environ["SUPABASE_DB_HOST"],
            port=int(os.environ["SUPABASE_DB_PORT"]),
            dbname=os.environ["SUPABASE_DB_NAME"],
            user=os.environ["SUPABASE_DB_USER"],
            password=os.environ["SUPABASE_DB_PASSWORD"],
            # Connection timeout — fail fast rather than hang
            connect_timeout=10,
            # Explicit autocommit=False — we manage the transaction manually
            options="-c default_transaction_isolation=serializable",
        )
        conn.autocommit = False
        return conn