# backend/app/routers/health.py
"""
Health check endpoint.

GET /health — liveness probe for Coolify and any load balancer.
Returns application status and database connectivity.

This route is in PUBLIC_PATHS (no JWT required) — see middleware/auth.py.
"""

import asyncpg
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import settings

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
async def health_check() -> JSONResponse:
    """
    Check application and database health.

    Performs a lightweight SELECT 1 against PostgreSQL to verify connectivity.
    Always returns HTTP 200 — the 'status' field indicates actual health:
      - 'ok'       — everything nominal
      - 'degraded' — app is running but database is unreachable

    Returns:
        JSONResponse with keys: status, version, database.
    """
    db_status = await _check_database()

    overall_status = "ok" if db_status == "ok" else "degraded"

    return JSONResponse(
        status_code=200,
        content={
            "status": overall_status,
            "version": settings.app_version,
            "database": db_status,
        },
    )


async def _check_database() -> str:
    """
    Attempt a minimal query against PostgreSQL.

    Opens a single connection, runs SELECT 1, closes immediately.
    Does not use a connection pool — health checks should be lightweight
    and independent of the app's connection pool state.

    Returns:
        'ok' if the query succeeds, 'unreachable' on any error.
    """
    try:
        # Open a throwaway connection — not from the app pool
        conn = await asyncpg.connect(
            dsn=settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
        )
        await conn.execute("SELECT 1")
        await conn.close()
        return "ok"
    except Exception:
        # Any error (wrong credentials, network, timeout) → degraded
        # We intentionally swallow the exception here — health endpoints
        # must never expose internal error details to the outside world.
        return "unreachable"
