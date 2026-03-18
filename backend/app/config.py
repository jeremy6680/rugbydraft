# backend/app/config.py
"""
Application settings loaded from environment variables.

All secrets and configuration come from the environment — never hardcoded.
Uses pydantic-settings for type validation and early failure on missing variables.

Usage:
    from app.config import settings
    print(settings.supabase_url)
"""

from functools import lru_cache

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings validated at startup.

    Reads from environment variables (case-insensitive).
    A .env file is supported for local development — never commit it.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,  # DATABASE_URL and database_url are equivalent
    )

    # ── Application ───────────────────────────────────────────────────────────
    app_name: str = Field(default="RugbyDraft API")
    app_version: str = Field(default="0.1.0")
    debug: bool = Field(default=False)

    # ── Supabase ──────────────────────────────────────────────────────────────
    supabase_url: str = Field(
        ...,  # required — no default
        description="Supabase project URL (e.g. https://xxxx.supabase.co)",
    )
    supabase_anon_key: str = Field(
        ...,
        description="Supabase anon/public key — safe to expose to clients",
    )
    supabase_service_role_key: str = Field(
        ...,
        description="Supabase service role key — NEVER expose to clients",
    )
    supabase_jwt_secret: str = Field(
        ...,
        description="JWT secret used to verify Supabase Auth tokens",
    )

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = Field(
        ...,
        description=(
            "Async PostgreSQL connection string. "
            "Format: postgresql+asyncpg://user:password@host:port/db"
        ),
    )

    # ── Rugby data source ─────────────────────────────────────────────────────
    rugby_data_source: str = Field(
        default="mock",
        description=(
            "Active rugby data connector. "
            "Options: mock | api_sports | statscore | sportradar"
        ),
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    cors_origins: list[str] = Field(
        default=["http://localhost:3000"],
        description="Allowed CORS origins. Add production domain before deploy.",
    )

    # ── Rate limiting ─────────────────────────────────────────────────────────
    rate_limit_per_minute: int = Field(
        default=100,
        description="Maximum requests per minute per IP (CDC spec).",
    )

    @field_validator("rugby_data_source")
    @classmethod
    def validate_data_source(cls, value: str) -> str:
        """Reject unknown connector names at startup."""
        allowed = {"mock", "api_sports", "statscore", "sportradar"}
        if value not in allowed:
            raise ValueError(
                f"RUGBY_DATA_SOURCE='{value}' is not valid. "
                f"Choose from: {', '.join(sorted(allowed))}"
            )
        return value


@lru_cache
def get_settings() -> Settings:
    """
    Return cached application settings.

    Uses lru_cache so the .env file is read only once — not on every request.
    In tests, call get_settings.cache_clear() to reset between test cases.
    """
    return Settings()


# Module-level singleton — import this in other modules
settings = get_settings()