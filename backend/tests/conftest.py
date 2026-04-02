# backend/tests/conftest.py
"""
pytest configuration for the RugbyDraft backend test suite.

Loads backend/.env before any test module is imported, ensuring pydantic-settings
finds the correct environment variables regardless of the directory from which
pytest is launched (repo root or backend/).

This fixes KB-003: Settings() fails at collection time when pytest is run from
the repo root, because pydantic-settings picks up the root .env (pipeline vars)
instead of backend/.env (FastAPI vars).
"""

import os
from pathlib import Path

# Resolve the absolute path to backend/.env — works regardless of cwd
_BACKEND_DIR = Path(__file__).resolve().parent.parent  # backend/
_ENV_FILE = _BACKEND_DIR / ".env"

# Load backend/.env into os.environ before any module-level settings are read.
# We do this manually (no pytest-dotenv dependency) to keep the fix self-contained.
if _ENV_FILE.exists():
    with open(_ENV_FILE) as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                # Don't override vars already set in the environment (CI/CD)
                if key not in os.environ:
                    os.environ[key] = value
