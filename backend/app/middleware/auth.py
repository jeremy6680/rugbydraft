# backend/app/middleware/auth.py
"""
JWT authentication middleware for FastAPI.

Verifies Supabase Auth tokens on every request except whitelisted public routes.
On success, injects the decoded JWT payload into request.state.user so route
handlers can access the authenticated user's ID and role without re-decoding.

Security model: opt-out (all routes protected by default).
Public routes must be explicitly added to PUBLIC_PATHS.
"""

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from jose import ExpiredSignatureError, JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings

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

# Supabase uses HS256 by default for JWT signing
JWT_ALGORITHM = "HS256"


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware that enforces JWT authentication globally.

    Supabase Auth issues JWTs signed with SUPABASE_JWT_SECRET (HS256).
    This middleware verifies the signature, expiry, and structure of the token
    before any route handler executes.

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
            The HTTP response — either from the route handler or a 401 error.
        """
        # Allow public routes through without any token check
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        # Extract the Bearer token from the Authorization header
        authorization: str | None = request.headers.get("Authorization")
        if not authorization or not authorization.startswith("Bearer "):
            return _unauthorized("Missing or malformed Authorization header.")

        token = authorization.removeprefix("Bearer ").strip()

        # Verify and decode the JWT
        try:
            payload: dict[str, Any] = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=[JWT_ALGORITHM],
                # Supabase sets audience to "authenticated" for logged-in users
                options={"verify_aud": False},
            )
        except ExpiredSignatureError:
            return _unauthorized("Token has expired. Please sign in again.")
        except JWTError:
            # Covers invalid signature, malformed token, missing claims, etc.
            return _unauthorized("Invalid token.")

        # Inject the decoded payload into request state so route handlers
        # can access user ID, role, etc. without re-decoding.
        # Example in a route: user_id = request.state.user["sub"]
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