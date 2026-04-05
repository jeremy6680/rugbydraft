# backend/app/main.py
"""
RugbyDraft API — FastAPI application entrypoint.

Assembles middleware, routers, and startup configuration.
No business logic here — this file is wiring only.

Run locally with:
    uvicorn app.main:app --reload --port 8000
"""

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from supabase import acreate_client
from supabase._async.client import AsyncClient

from app.config import settings
from app.middleware.auth import AuthMiddleware
from app.routers import draft, draft_assisted, health, leagues, trades, waivers
from app.routers.dashboard import router as dashboard_router
from app.routers.infirmary import router as infirmary_router
from app.routers.lineup import router as lineup_router
from app.routers.players import router as players_router
from app.routers.stats import router as stats_router
from draft.registry import DraftRegistry
from infirmary.ir_scheduler import get_scheduler, register_ir_jobs

# ── Supabase client — module-level instance for scheduler ─────────────────────
# Injected into APScheduler jobs at startup.
# Request-scoped client (get_supabase_client) is used by routers instead.
supabase_client: AsyncClient | None = None

# ── Rate limiter setup ────────────────────────────────────────────────────────
# Uses the client IP address as the rate limit key.
# Limit: 100 requests/minute per IP (CDC spec).
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[f"{settings.rate_limit_per_minute}/minute"],
)

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:     %(name)s — %(message)s",
)


# ── Lifespan — startup / shutdown ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan context manager.

    Initialises shared singletons at startup and cleans up on shutdown.
    Using lifespan instead of @app.on_event (deprecated since FastAPI 0.93).

    Startup:
        - DraftRegistry: in-memory store of active DraftEngine instances.
        - Supabase async client for APScheduler IR jobs.
        - APScheduler: registers and starts IR maintenance jobs.

    Shutdown:
        - APScheduler graceful shutdown.
    """
    global supabase_client

    # Startup
    app.state.draft_registry = DraftRegistry()

    # Supabase async client for scheduler (not request-scoped)
    supabase_client = await acreate_client(
        settings.supabase_url,
        settings.supabase_service_role_key,  # service role — scheduler bypasses RLS
    )

    scheduler = get_scheduler()
    register_ir_jobs(scheduler, supabase_client)
    scheduler.start()
    yield  # application runs here

    # Shutdown
    if scheduler.running:
        scheduler.shutdown()


# ── FastAPI instance ──────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "RugbyDraft API — fantasy rugby platform with snake draft system. "
        "FastAPI is the authority of state for the draft. "
        "Supabase Realtime is a broadcast channel only."
    ),
    lifespan=lifespan,
    # Disable docs in production — enable only in debug mode
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
)

# ── Attach rate limiter to app state ──────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Middleware — order matters (applied bottom-up) ────────────────────────────
# 1. CORS — must be outermost to handle preflight OPTIONS requests first
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Rate limiting
app.add_middleware(SlowAPIMiddleware)

# 3. JWT authentication — innermost, runs after CORS and rate limiting
app.add_middleware(AuthMiddleware)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(draft.router)
app.include_router(draft_assisted.router)
app.include_router(leagues.router)
app.include_router(trades.router)
app.include_router(waivers.router)
app.include_router(lineup_router)
app.include_router(infirmary_router)
app.include_router(players_router)
app.include_router(stats_router)
app.include_router(dashboard_router)

# ── Custom OpenAPI schema — Bearer auth scheme for Swagger UI ─────────────────

# Routes that are publicly accessible — no JWT required.
# Must match exactly the paths registered in AuthMiddleware.PUBLIC_PATHS.
_PUBLIC_PATHS = {"/health", "/openapi.json", "/docs", "/redoc"}


def custom_openapi() -> dict[str, Any]:
    """Override the default OpenAPI schema to inject BearerAuth security scheme.

    Applies BearerAuth globally to all protected operations.
    Public paths (listed in _PUBLIC_PATHS) are explicitly excluded.

    The schema is generated once and cached on app.openapi_schema.
    """
    if app.openapi_schema:
        return app.openapi_schema  # type: ignore[return-value]

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    # Inject the HTTP Bearer security scheme into components
    schema.setdefault("components", {})
    schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": (
                "Supabase JWT — obtain via supabase.auth.getSession() "
                "or the magic-link flow. Paste the access_token value here."
            ),
        }
    }

    # Apply BearerAuth to all operations except public paths
    for path, path_item in schema.get("paths", {}).items():
        for operation in path_item.values():
            if isinstance(operation, dict):
                if path in _PUBLIC_PATHS:
                    # Explicitly mark public routes as requiring no auth
                    operation["security"] = []
                else:
                    operation.setdefault("security", [{"BearerAuth": []}])

    app.openapi_schema = schema
    return schema  # type: ignore[return-value]


app.openapi = custom_openapi  # type: ignore[method-assign]
