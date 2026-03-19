# backend/app/main.py
"""
RugbyDraft API — FastAPI application entrypoint.

Assembles middleware, routers, and startup configuration.
No business logic here — this file is wiring only.

Run locally with:
    uvicorn app.main:app --reload --port 8000
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.config import settings
from app.middleware.auth import AuthMiddleware
from app.routers import health

# ── Rate limiter setup ────────────────────────────────────────────────────────
# Uses the client IP address as the rate limit key.
# Limit: 100 requests/minute per IP (CDC spec).
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[f"{settings.rate_limit_per_minute}/minute"],
)

# ── FastAPI instance ──────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "RugbyDraft API — fantasy rugby platform with snake draft system. "
        "FastAPI is the authority of state for the draft. "
        "Supabase Realtime is a broadcast channel only."
    ),
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
# Phase 2: app.include_router(draft.router, prefix="/draft")
# Phase 2: app.include_router(leagues.router, prefix="/leagues")
# Phase 3: app.include_router(players.router, prefix="/players")
