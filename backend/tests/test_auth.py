# backend/tests/test_auth.py
"""
Unit tests for the JWT authentication middleware.

Tests the cryptographic verification layer specifically:
    - ES256 token signed with a valid EC P-256 key pair → accepted
    - ES256 token with wrong signature → 401
    - ES256 token expired → 401 with expiry message
    - ES256 JWKS fetch failure → 401 (no server crash)
    - ES256 JWKS key rotation → cache invalidated, fresh key fetched, token accepted
    - HS256 token signed with the correct secret → accepted
    - HS256 token signed with the wrong secret → 401
    - HS256 token expired → 401 with expiry message

Middleware behaviour already covered in test_health.py (missing token, malformed
token, missing Bearer prefix, public route passthrough) is NOT duplicated here.

Key generation strategy:
    Real EC P-256 key pairs are generated in-process using the `cryptography`
    library (already installed as a dependency of python-jose[cryptography]).
    JWKS responses are mocked via pytest-mock / unittest.mock to avoid any
    network calls in CI.
"""

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ec import (
    SECP256R1,
    generate_private_key,
)
from fastapi.testclient import TestClient
from jose import jwt

# ── Helpers — key generation ──────────────────────────────────────────────────


def _generate_ec_key_pair() -> tuple[Any, dict[str, Any]]:
    """
    Generate a fresh EC P-256 key pair and return it as (private_key, jwk_dict).

    The JWK dict is the format Supabase returns from its JWKS endpoint.
    We build it manually from the raw key components (x, y coordinates).

    Returns:
        Tuple of (private_key object, JWK public key as dict).
    """
    import base64

    private_key = generate_private_key(SECP256R1())
    public_key = private_key.public_key()
    public_numbers = (
        public_key.public_key().public_numbers()
        if hasattr(public_key, "public_key")
        else public_key.public_numbers()
    )

    def _b64url(n: int) -> str:
        """Encode a big-endian integer as base64url (no padding)."""
        byte_length = (n.bit_length() + 7) // 8
        return (
            base64.urlsafe_b64encode(n.to_bytes(byte_length, "big"))
            .rstrip(b"=")
            .decode()
        )

    jwk = {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64url(public_numbers.x),
        "y": _b64url(public_numbers.y),
        "kid": str(uuid4()),
        "use": "sig",
    }
    return private_key, jwk


def _sign_es256(private_key: Any, payload: dict[str, Any]) -> str:
    """
    Sign a JWT payload with ES256 using the given EC private key.

    Args:
        private_key: EC private key object from cryptography.
        payload: JWT claims dict (sub, exp, role, etc.).

    Returns:
        Encoded JWT string.
    """
    # python-jose can sign with a cryptography private key object directly
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return jwt.encode(payload, pem, algorithm="ES256")


def _make_payload(expired: bool = False) -> dict[str, Any]:
    """
    Build a minimal Supabase-like JWT payload.

    Args:
        expired: If True, sets exp in the past (token is expired).

    Returns:
        JWT claims dict.
    """
    now = int(time.time())
    return {
        "sub": str(uuid4()),
        "role": "authenticated",
        "iat": now - 10,
        "exp": (now - 5) if expired else (now + 3600),
    }


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_jwks_cache() -> None:
    """
    Reset the in-memory JWKS cache before every test.

    Without this, a cached key from one test would bleed into the next,
    causing false positives or false negatives.
    """
    import app.middleware.auth as auth_module

    auth_module._jwks_cache = None
    yield
    auth_module._jwks_cache = None


@pytest.fixture()
def ec_key_pair() -> tuple[Any, dict[str, Any]]:
    """Return a fresh EC P-256 key pair as (private_key, jwk_dict)."""
    return _generate_ec_key_pair()


@pytest.fixture()
def mock_jwks_fetch(ec_key_pair: tuple[Any, dict[str, Any]]) -> dict[str, Any]:
    """
    Patch _fetch_jwks so it returns the test JWK without any HTTP call.

    Returns:
        The JWK dict used for signing, so tests can reference it.
    """
    _, jwk = ec_key_pair
    return jwk


# ── Helpers — mock JWKS response ─────────────────────────────────────────────


def _mock_httpx_response(jwk: dict[str, Any]) -> MagicMock:
    """
    Build a mock httpx.Response that returns a JWKS payload.

    Args:
        jwk: The JWK dict to include in the 'keys' array.

    Returns:
        MagicMock configured to behave like a successful httpx.Response.
    """
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"keys": [jwk]}
    return mock_response


# ── ES256 tests ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_es256_valid_token_is_accepted(
    ec_key_pair: tuple[Any, dict[str, Any]],
) -> None:
    """
    A valid ES256 token signed with the correct key must be accepted.

    The middleware must inject the decoded payload into request.state.user
    and call the next handler (we verify via a 404, not a 401).
    """
    from app.main import app

    private_key, jwk = ec_key_pair
    token = _sign_es256(private_key, _make_payload())
    mock_response = _mock_httpx_response(jwk)

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client

        with patch("app.config.settings") as mock_settings:
            mock_settings.supabase_url = "https://test.supabase.co"
            mock_settings.supabase_jwt_algorithm = "ES256"

            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(
                "/some-protected-route",
                headers={"Authorization": f"Bearer {token}"},
            )

    # 404 means the middleware accepted the token and passed to the router
    # (the route doesn't exist, but auth succeeded)
    assert response.status_code != 401, (
        f"Expected token to be accepted (non-401), got {response.status_code}: "
        f"{response.json()}"
    )


@pytest.mark.asyncio
async def test_es256_wrong_signature_returns_401(
    ec_key_pair: tuple[Any, dict[str, Any]],
) -> None:
    """
    An ES256 token signed with a different key must return 401.

    We sign with key_a but the JWKS mock returns key_b's JWK.
    """
    from app.main import app

    private_key_a, _ = ec_key_pair
    _, jwk_b = _generate_ec_key_pair()  # different key pair

    token = _sign_es256(private_key_a, _make_payload())
    mock_response = _mock_httpx_response(jwk_b)  # wrong public key

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client

        with patch("app.config.settings") as mock_settings:
            mock_settings.supabase_url = "https://test.supabase.co"
            mock_settings.supabase_jwt_algorithm = "ES256"

            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(
                "/some-protected-route",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


@pytest.mark.asyncio
async def test_es256_expired_token_returns_401(
    ec_key_pair: tuple[Any, dict[str, Any]],
) -> None:
    """An ES256 token with exp in the past must return 401 with expiry detail."""
    from app.main import app

    private_key, jwk = ec_key_pair
    token = _sign_es256(private_key, _make_payload(expired=True))
    mock_response = _mock_httpx_response(jwk)

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client

        with patch("app.config.settings") as mock_settings:
            mock_settings.supabase_url = "https://test.supabase.co"
            mock_settings.supabase_jwt_algorithm = "ES256"

            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(
                "/some-protected-route",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert response.status_code == 401
    body = response.json()
    assert body["error"] == "unauthorized"
    assert "expired" in body["detail"].lower()


@pytest.mark.asyncio
async def test_es256_jwks_fetch_failure_returns_401() -> None:
    """
    If the JWKS endpoint is unreachable, the middleware must return 401.

    The server must not crash — RuntimeError from _fetch_jwks is caught
    and converted to a 401 response.
    """
    import httpx
    from app.main import app

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client

        with patch("app.config.settings") as mock_settings:
            mock_settings.supabase_url = "https://test.supabase.co"
            mock_settings.supabase_jwt_algorithm = "ES256"

            client = TestClient(app, raise_server_exceptions=False)
            # Any token — it won't be verified because JWKS fetch fails first
            response = client.get(
                "/some-protected-route",
                headers={"Authorization": "Bearer some.fake.token"},
            )

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


@pytest.mark.asyncio
async def test_es256_key_rotation_refreshes_cache(
    ec_key_pair: tuple[Any, dict[str, Any]],
) -> None:
    """
    When the cached JWKS key is stale (key rotation), the middleware must:
    1. Fail verification with the old key
    2. Invalidate the cache
    3. Fetch the new key
    4. Succeed with the new key

    We simulate rotation by:
    - Pre-seeding the cache with key_a's JWK
    - Signing the token with key_b
    - Configuring the JWKS mock to return key_b's JWK on the retry fetch
    """
    import app.middleware.auth as auth_module
    from app.main import app

    _, old_jwk = ec_key_pair  # key_a — stale cached key
    private_key_b, new_jwk = _generate_ec_key_pair()  # key_b — new active key

    # Pre-seed the cache with the old (now stale) key
    auth_module._jwks_cache = old_jwk

    # Sign with the new key — this will fail on first attempt (wrong cached key)
    token = _sign_es256(private_key_b, _make_payload())
    mock_response = _mock_httpx_response(new_jwk)

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_class.return_value = mock_client

        with patch("app.config.settings") as mock_settings:
            mock_settings.supabase_url = "https://test.supabase.co"
            mock_settings.supabase_jwt_algorithm = "ES256"

            client = TestClient(app, raise_server_exceptions=False)
            response = client.get(
                "/some-protected-route",
                headers={"Authorization": f"Bearer {token}"},
            )

    # Token should be accepted after the retry with the refreshed key
    assert response.status_code != 401, (
        f"Expected token accepted after key rotation retry, "
        f"got {response.status_code}: {response.json()}"
    )
    # Cache must now hold the new key
    assert auth_module._jwks_cache == new_jwk


# ── HS256 tests ───────────────────────────────────────────────────────────────


def test_hs256_valid_token_is_accepted() -> None:
    """
    A valid HS256 token signed with the configured secret must be accepted.

    Uses SUPABASE_JWT_ALGORITHM=HS256 to activate the legacy path.
    """
    from app.main import app

    secret = "test-hs256-secret-for-unit-tests"
    payload = _make_payload()
    token = jwt.encode(payload, secret, algorithm="HS256")

    with patch("app.middleware.auth.settings") as mock_settings:
        mock_settings.supabase_jwt_algorithm = "HS256"
        mock_settings.supabase_jwt_secret = secret

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(
            "/some-protected-route",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code != 401, (
        f"Expected HS256 token to be accepted, got {response.status_code}: "
        f"{response.json()}"
    )


def test_hs256_wrong_secret_returns_401() -> None:
    """An HS256 token signed with the wrong secret must return 401."""
    from app.main import app

    token = jwt.encode(_make_payload(), "wrong-secret", algorithm="HS256")

    with patch("app.middleware.auth.settings") as mock_settings:
        mock_settings.supabase_jwt_algorithm = "HS256"
        mock_settings.supabase_jwt_secret = "correct-secret"

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(
            "/some-protected-route",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_hs256_expired_token_returns_401() -> None:
    """An HS256 token with exp in the past must return 401 with expiry detail."""
    from app.main import app

    secret = "test-hs256-secret"
    token = jwt.encode(_make_payload(expired=True), secret, algorithm="HS256")

    with patch("app.middleware.auth.settings") as mock_settings:
        mock_settings.supabase_jwt_algorithm = "HS256"
        mock_settings.supabase_jwt_secret = secret

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(
            "/some-protected-route",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 401
    body = response.json()
    assert body["error"] == "unauthorized"
    assert "expired" in body["detail"].lower()
