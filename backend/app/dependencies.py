# backend/app/dependencies.py
"""
FastAPI shared dependencies.

Provides reusable dependency functions for injection via Depends():
- get_current_user_id: extract authenticated user UUID from request.state.user
  (set by AuthMiddleware after JWT verification via jose)
- get_supabase_client: instantiate an async Supabase client authenticated
  with the user's JWT so RLS policies apply automatically on every query.

Pattern: consistent with existing routers — user identity comes from
request.state.user["sub"], injected by AuthMiddleware before route handlers.
"""

from uuid import UUID

from fastapi import HTTPException, Request, status
from supabase._async.client import AsyncClient
from supabase.lib.client_options import ClientOptions

from app.config import settings


def get_current_user_id(request: Request) -> UUID:
    """Extract the authenticated user's UUID from request state.

    AuthMiddleware sets request.state.user (decoded JWT payload) after
    verifying the token. The user's UUID is in the "sub" claim.

    Args:
        request: FastAPI Request object.

    Returns:
        UUID of the authenticated user.

    Raises:
        HTTPException 401: if user payload is not set on request state.
    """
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    return UUID(user["sub"])


async def get_supabase_client(request: Request) -> AsyncClient:
    """Instantiate an async Supabase client authenticated with the user's JWT.

    Passes the bearer token from the Authorization header to the Supabase
    client so RLS policies evaluate against the user's identity — not the
    service role. This means a manager can only read/write their own data.

    We create a new client per request (lightweight — no connection pooling
    in supabase-py). The JWT is already verified by AuthMiddleware so we
    trust it here without re-checking.

    Args:
        request: FastAPI Request object.

    Returns:
        AsyncClient instance scoped to the authenticated user.

    Raises:
        HTTPException 401: if Authorization header is missing.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header.",
        )
    token = auth_header.removeprefix("Bearer ").strip()

    # Import here to avoid circular imports at module load time
    from supabase import acreate_client

    client: AsyncClient = await acreate_client(
        supabase_url=settings.supabase_url,
        supabase_key=settings.supabase_anon_key,
        options=ClientOptions(headers={"Authorization": f"Bearer {token}"}),
    )
    return client
