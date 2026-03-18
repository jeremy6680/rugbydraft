# backend/tests/test_health.py
"""
Smoke tests for the health endpoint and authentication middleware.

Tests:
    - GET /health is publicly accessible (no JWT required)
    - GET /health returns expected response shape
    - A protected route returns 401 when no token is provided
    - A protected route returns 401 when token is malformed
"""

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings, settings
from app.main import app

# ── Test client ───────────────────────────────────────────────────────────────
# TestClient wraps the FastAPI app and handles the ASGI lifecycle.
# No real server is started — requests are handled in-process.
client = TestClient(app, raise_server_exceptions=False)


# ── Health endpoint ───────────────────────────────────────────────────────────


def test_health_returns_200() -> None:
    """GET /health must return HTTP 200 regardless of database status."""
    response = client.get("/health")
    assert response.status_code == 200


def test_health_response_shape() -> None:
    """GET /health must return the expected JSON keys."""
    response = client.get("/health")
    body = response.json()

    assert "status" in body
    assert "version" in body
    assert "database" in body


def test_health_status_is_valid_value() -> None:
    """status field must be either 'ok' or 'degraded'."""
    response = client.get("/health")
    body = response.json()

    assert body["status"] in {"ok", "degraded"}


def test_health_version_matches_settings() -> None:
    """version field must match the value configured in settings."""
    response = client.get("/health")
    body = response.json()

    assert body["version"] == settings.app_version


# ── Authentication middleware ─────────────────────────────────────────────────


def test_protected_route_without_token_returns_401() -> None:
    """
    Any route not in PUBLIC_PATHS must return 401 when no token is provided.

    We use a non-existent route (/protected-test) to avoid coupling this test
    to any real business route that might change. The middleware runs before
    the router, so 401 is returned before FastAPI checks if the route exists.
    """
    response = client.get("/protected-test")
    assert response.status_code == 401


def test_protected_route_with_malformed_token_returns_401() -> None:
    """A malformed Bearer token must return 401."""
    response = client.get(
        "/protected-test",
        headers={"Authorization": "Bearer this-is-not-a-valid-jwt"},
    )
    assert response.status_code == 401


def test_protected_route_with_missing_bearer_prefix_returns_401() -> None:
    """Authorization header without 'Bearer ' prefix must return 401."""
    response = client.get(
        "/protected-test",
        headers={"Authorization": "some-token-without-bearer-prefix"},
    )
    assert response.status_code == 401


def test_health_error_response_shape_on_401() -> None:
    """401 responses must follow the standard error shape."""
    response = client.get("/protected-test")
    body = response.json()

    assert "error" in body
    assert "detail" in body
    assert body["error"] == "unauthorized"