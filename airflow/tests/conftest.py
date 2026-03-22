# airflow/tests/conftest.py
"""pytest configuration — path setup for DAG and plugin imports.

This file is loaded by pytest before any test module.
It adds airflow/plugins/ and airflow/dags/ to sys.path so that:
- 'from operators.dbt_operator import ...' resolves in the DAG
- 'import post_match_pipeline' resolves in the test fixture
"""

from __future__ import annotations

import sys
from pathlib import Path

# Repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]

# airflow/plugins/ — makes 'operators.*' importable
_PLUGINS_DIR = _REPO_ROOT / "airflow" / "plugins"

# airflow/dags/ — makes 'post_match_pipeline' importable
_DAGS_DIR = _REPO_ROOT / "airflow" / "dags"

# Project root — makes 'connectors.*' and 'scripts.*' importable
_PROJECT_ROOT = _REPO_ROOT

for path in [str(_PLUGINS_DIR), str(_DAGS_DIR), str(_PROJECT_ROOT)]:
    if path not in sys.path:
        sys.path.insert(0, path)