# backend/app/middleware/auth.py
"""
JWT authentication middleware for FastAPI.

Verifies Supabase Auth tokens on every request except whitelisted public routes.
Supports ES256 (JWKS-based, current Supabase default for projects created after
mid-2024) and HS256 (legacy symmetric secret, older Supabase projects).

Algorithm selection is automatic:
- ES256 (default): fetches the public key from Supabase JWKS endpoint once,
  caches it in memory, refreshes on signature failure (key rotation).
- HS256 (fallback): uses SUPABASE_JWT_SECRET directly. Only activated when
  SUPABASE_JWT_ALGORITHM=HS256 is set explicitly in the environment.

On success, injects the decoded JWT payload into request.state.user so route
handlers can access the authenticated user's ID and role without re-decoding.

Security model: opt-out (all routes protected by default).
Public routes must be explicitly added to PUBLIC_PATHS.
"""

import logging
from typing import Any

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse
from jose import ExpiredSignatureError, JWTError, jwt
from jose.exceptions import JWKError
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings

logger = logging.getLogger(__name__)

# ── Public routes — no JWT required ──────────────────────────────────────────
# Add a path here only if it genuinely needs to be unauthenticated.
# Keep this list short and intentional.
PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
    }
)

# ── JWKS key cache ────────────────────────────────────────────────────────────
# Stores the fetched JWKS public key dict in memory.
# None = not yet fetched. Refreshed on signature failure (key rotation).
_jwks_cache: dict[str, Any] | None = None


async def _fetch_jwks() -> dict[str, Any]:
    """
    Fetch the JWKS public key set from Supabase and cache it.

    Supabase exposes its public keys at:
        {SUPABASE_URL}/auth/v1/.well-known/jwks.json

    The response contains a 'keys' array. We take the first key (Supabase
    only publishes one active signing key at a time).

    Returns:
        The first JWK dict from the JWKS response.

    Raises:
        RuntimeError: If the JWKS endpoint cannot be reached or returns
                      an unexpected response.
    """
    global _jwks_cache

    jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
    logger.info("Fetching JWKS from %s", jwks_url)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(jwks_url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Failed to fetch JWKS from Supabase: {exc}") from exc

    data = response.json()
    keys = data.get("keys", [])
    if not keys:
        raise RuntimeError(f"JWKS response contains no keys: {data}")

    # Cache and return the first (and typically only) key
    _jwks_cache = keys[0]
    logger.info("JWKS key cached (kid=%s)", _jwks_cache.get("kid", "unknown"))
    return _jwks_cache


async def _get_jwks_key() -> dict[str, Any]:
    """
    Return the cached JWKS key, fetching it first if not yet loaded.

    Returns:
        The JWK dict for the active Supabase signing key.
    """
    if _jwks_cache is None:
        return await _fetch_jwks()
    return _jwks_cache


async def _verify_token_es256(token: str) -> dict[str, Any]:
    """
    Verify a JWT signed with ES256 using the Supabase JWKS public key.

    Implements a single retry on JWKError / invalid signature to handle
    Supabase key rotation: if the cached key fails, we refresh the cache
    and try once more before giving up.

    Args:
        token: Raw JWT string (without 'Bearer ' prefix).

    Returns:
        Decoded JWT payload dict.

    Raises:
        ExpiredSignatureError: If the token has expired.
        JWTError: If the token is malformed or signature is invalid after retry.
    """
    global _jwks_cache

    key = await _get_jwks_key()

    try:
        return jwt.decode(
            token,
            key,
            algorithms=["ES256"],
            options={"verify_aud": False},
        )
    except (JWKError, JWTError) as first_exc:
        # Expiry is definitive — no point retrying with a fresh key
        if isinstance(first_exc, ExpiredSignatureError):
            raise

        logger.warning(
            "ES256 verification failed with cached key — refreshing JWKS and retrying. "
            "Error: %s",
            first_exc,
        )
        # Invalidate cache and force a fresh fetch
        _jwks_cache = None
        try:
            key = await _fetch_jwks()
            return jwt.decode(
                token,
                key,
                algorithms=["ES256"],
                options={"verify_aud": False},
            )
        except Exception as retry_exc:
            logger.error("ES256 verification failed after JWKS refresh: %s", retry_exc)
            raise JWTError(
                "Invalid token signature (ES256, after key refresh)."
            ) from retry_exc


def _verify_token_hs256(token: str) -> dict[str, Any]:
    """
    Verify a JWT signed with HS256 using the Supabase JWT secret.

    Used only when SUPABASE_JWT_ALGORITHM=HS256 is set explicitly.
    This covers older Supabase projects and local Supabase (supabase start).

    Args:
        token: Raw JWT string (without 'Bearer ' prefix).

    Returns:
        Decoded JWT payload dict.

    Raises:
        ExpiredSignatureError: If the token has expired.
        JWTError: If the token is malformed or signature is invalid.
    """
    return jwt.decode(
        token,
        settings.supabase_jwt_secret,
        algorithms=["HS256"],
        options={"verify_aud": False},
    )


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware that enforces JWT authentication globally.

    Algorithm is selected based on the SUPABASE_JWT_ALGORITHM setting:
    - ES256 (default): JWKS-based verification, async key fetch on first request.
    - HS256: symmetric secret verification, synchronous.

    Attributes:
        None beyond BaseHTTPMiddleware internals.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        """
        Intercept every request and verify JWT unless route is public.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or route handler in the chain.

        Returns:
            JSONResponse (401) if auth fails, otherwise the route response.
        """
        # Allow public routes through without any token check
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        # Extract the Bearer token from the Authorization header
        authorization: str | None = request.headers.get("Authorization")
        if not authorization or not authorization.startswith("Bearer "):
            return _unauthorized("Missing or malformed Authorization header.")

        token = authorization.removeprefix("Bearer ").strip()

        # Decode and verify the JWT using the configured algorithm
        try:
            if settings.supabase_jwt_algorithm.upper() == "HS256":
                payload: dict[str, Any] = _verify_token_hs256(token)
            else:
                # Default: ES256 with JWKS public key verification
                payload = await _verify_token_es256(token)
        except ExpiredSignatureError:
            return _unauthorized("Token has expired. Please sign in again.")
        except (JWTError, RuntimeError) as exc:
            logger.warning("JWT verification failed: %s", exc)
            return _unauthorized("Invalid token.")

        # Inject decoded payload into request state.
        # Usage in a route handler: user_id = request.state.user["sub"]
        request.state.user = payload

        return await call_next(request)


def _unauthorized(detail: str) -> JSONResponse:
    """
    Build a consistent 401 Unauthorized response.

    Args:
        detail: Human-readable explanation of why authentication failed.

    Returns:
        JSONResponse with status 401 and a standard error body.
    """
    return JSONResponse(
        status_code=401,
        content={"error": "unauthorized", "detail": detail},
    )
