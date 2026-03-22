# airflow/plugins/operators/dbt_operator.py
"""Custom Airflow operators for dbt commands.

Wraps dbt CLI calls with structured error reporting and logging.
Supports dbt run and dbt test with configurable target and model selection.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from airflow.models import BaseOperator
from airflow.utils.decorators import apply_defaults


class DbtRunOperator(BaseOperator):
    """Run dbt models for a given target and selection.

    Args:
        target: dbt target name from profiles.yml ('ci' or 'prod').
        select: dbt node selection expression (e.g. 'bronze silver' or 'gold').
        project_dir: Absolute path to the dbt project directory.
            Defaults to /opt/airflow/project/dbt_project.
        profiles_dir: Absolute path to the directory containing profiles.yml.
            Defaults to project_dir.

    Example:
        DbtRunOperator(
            task_id="dbt_bronze_silver",
            target="ci",
            select="bronze silver",
        )
    """

    # Template fields allow Jinja templating in DAG params (e.g. {{ ds }})
    template_fields = ("select",)

    # UI color in Airflow graph view — blue for dbt run
    ui_color = "#1a73e8"

    @apply_defaults
    def __init__(
        self,
        target: str,
        select: str,
        project_dir: str = "/opt/airflow/project/dbt_project",
        profiles_dir: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.target = target
        self.select = select
        self.project_dir = project_dir
        self.profiles_dir = profiles_dir or project_dir

    def execute(self, context: dict[str, Any]) -> None:
        """Execute dbt run and raise on failure with parsed error output."""
        command = [
            "dbt",
            "run",
            "--target", self.target,
            "--select", self.select,
            "--project-dir", self.project_dir,
            "--profiles-dir", self.profiles_dir,
            "--no-use-colors",  # cleaner logs in Airflow UI
        ]

        self.log.info("Running dbt: %s", " ".join(command))
        self._run_dbt_command(command)

    def _run_dbt_command(self, command: list[str]) -> None:
        """Run a dbt CLI command and parse output for errors.

        Args:
            command: Full dbt CLI command as a list of strings.

        Raises:
            RuntimeError: If dbt exits with a non-zero return code.
                Includes parsed error lines from dbt output for clarity.
        """
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=self.project_dir,
        )

        # Always log full dbt output — visible in Airflow task logs
        for line in result.stdout.splitlines():
            self.log.info("[dbt] %s", line)

        if result.returncode != 0:
            # Extract ERROR lines from dbt output for the exception message
            error_lines = [
                line for line in result.stdout.splitlines()
                if "ERROR" in line or "error" in line.lower()
            ]
            stderr_summary = result.stderr[:500] if result.stderr else ""

            raise RuntimeError(
                f"dbt run failed (target={self.target}, select={self.select}).\n"
                f"Errors:\n" + "\n".join(error_lines) + "\n"
                f"Stderr: {stderr_summary}"
            )

        self.log.info(
            "dbt run succeeded (target=%s, select=%s)", self.target, self.select
        )


class DbtTestOperator(BaseOperator):
    """Run dbt tests for a given target and selection.

    Args:
        target: dbt target name from profiles.yml ('ci' or 'prod').
        select: dbt node selection expression.
        project_dir: Absolute path to the dbt project directory.
        profiles_dir: Absolute path to profiles.yml directory.

    Example:
        DbtTestOperator(
            task_id="dbt_test_silver",
            target="ci",
            select="silver",
        )
    """

    template_fields = ("select",)

    # UI color — orange for dbt test
    ui_color = "#f9a825"

    @apply_defaults
    def __init__(
        self,
        target: str,
        select: str,
        project_dir: str = "/opt/airflow/project/dbt_project",
        profiles_dir: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.target = target
        self.select = select
        self.project_dir = project_dir
        self.profiles_dir = profiles_dir or project_dir

    def execute(self, context: dict[str, Any]) -> None:
        """Execute dbt test and raise on failure with parsed test results."""
        command = [
            "dbt",
            "test",
            "--target", self.target,
            "--select", self.select,
            "--project-dir", self.project_dir,
            "--profiles-dir", self.profiles_dir,
            "--no-use-colors",
        ]

        self.log.info("Running dbt test: %s", " ".join(command))

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=self.project_dir,
        )

        for line in result.stdout.splitlines():
            self.log.info("[dbt test] %s", line)

        if result.returncode != 0:
            # Extract FAIL lines from dbt test output
            fail_lines = [
                line for line in result.stdout.splitlines()
                if "FAIL" in line or "ERROR" in line
            ]
            raise RuntimeError(
                f"dbt test failed (target={self.target}, select={self.select}).\n"
                f"Failed tests:\n" + "\n".join(fail_lines)
            )

        self.log.info(
            "dbt test passed (target=%s, select=%s)", self.target, self.select
        )