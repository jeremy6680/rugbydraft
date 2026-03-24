# backend/app/main.py
"""
RugbyDraft API — FastAPI application entrypoint.

Assembles middleware, routers, and startup configuration.
No business logic here — this file is wiring only.

Run locally with:
    uvicorn app.main:app --reload --port 8000
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.config import settings
from app.middleware.auth import AuthMiddleware
from app.routers import draft, draft_assisted, health, trades, waivers
from app.routers.lineup import router as lineup_router
from app.routers.infirmary import router as infirmary_router
from app.routers.players import router as players_router  # noqa: E402

from draft.registry import DraftRegistry
from infirmary.ir_scheduler import get_scheduler, register_ir_jobs

from supabase._async.client import AsyncClient
from supabase import acreate_client

# ── Supabase client — module-level instance for scheduler ─────────────────────
# Injected into APScheduler jobs at startup.
# Request-scoped client (get_supabase_client) is used by routers instead.
import logging

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
          All draft endpoints retrieve engines from here.

    Shutdown:
        - No explicit cleanup needed for the registry — active drafts are
          in-memory only and do not require graceful teardown in V1.
          (In production, consider persisting draft state to DB on shutdown.)
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
    # Shutdown (placeholder — no cleanup needed in V1)


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
# slowapi requires the limiter to be on app.state.limiter
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
app.include_router(trades.router)
app.include_router(waivers.router)
app.include_router(lineup_router)
app.include_router(infirmary_router)
app.include_router(players_router)

# Phase 3: app.include_router(leagues.router, prefix="/leagues")
