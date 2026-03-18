# STRUCTURE.md — RugbyDraft

> Repository structure explained.
> Updated at each phase — reflects the current state of the codebase.
> Last updated: 2026-03-18 (Phase 1 — Foundations)

---

## Overview

```
rugbydraft/
├── .github/workflows/     # CI/CD — GitHub Actions
├── backend/               # FastAPI — Python backend, draft authority of state
├── db/                    # PostgreSQL migrations
├── dbt_project/           # dbt Core — data pipeline (bronze/silver/gold)
├── docs/                  # Technical docs (CDC gitignored)
├── frontend/              # Next.js 15 — created in Phase 4
├── scripts/               # Utility and validation scripts
├── CONTEXT.md             # Project overview, stack, key decisions summary
├── DECISIONS.md           # Architectural decisions log
├── NEXT_STEPS.md          # Phase-by-phase task checklist
├── STRUCTURE.md           # This file
├── .env.example           # All required environment variables documented
└── README.md              # Public-facing project description
```

---

## .github/workflows/

GitHub Actions CI/CD pipelines.

| File              | Trigger   | What it runs                                   |
| ----------------- | --------- | ---------------------------------------------- |
| `ci-python.yml`   | Push / PR | ruff (lint) + pytest                           |
| `ci-frontend.yml` | Push / PR | TypeScript lint + axe-core accessibility tests |
| `ci-dbt.yml`      | Push / PR | dbt test (silver layer)                        |

> Draft engine tests and scoring tests are mandatory — PRs cannot be merged if they fail.

---

## backend/

FastAPI Python backend. **Authority of state for the snake draft.**

Supabase Realtime is a broadcast channel only — all state mutations go
through FastAPI first, then are broadcast to clients.

```
backend/
├── app/
│   ├── main.py            # FastAPI app entrypoint — mounts routers, middleware
│   │                      # CORS + SlowAPI + AuthMiddleware assembled here
│   ├── config.py          # App settings loaded from environment variables
│   │                      # via pydantic-settings. Never hardcode secrets.
│   ├── middleware/
│   │   ├── __init__.py
│   │   └── auth.py        # JWT verification middleware (Supabase Auth tokens)
│   │                      # Global opt-out model — all routes protected by default
│   │                      # Public routes whitelisted in PUBLIC_PATHS
│   ├── routers/
│   │   ├── __init__.py
│   │   └── health.py      # GET /health — liveness probe (public, no JWT)
│   └── models/            # Pydantic models — to be completed in Phase 2
│       ├── __init__.py
│       ├── user.py
│       ├── player.py
│       └── league.py
├── tests/
│   ├── __init__.py
│   └── test_health.py     # 8 tests — health endpoint + auth middleware
├── pytest.ini             # pytest config — asyncio strict mode
├── requirements.txt       # Production dependencies (pinned to minor version)
└── requirements-dev.txt   # Dev/CI dependencies (pytest, ruff, mypy)
```

### Key architectural notes

- `config.py` uses `pydantic-settings` — missing required env vars cause
  immediate startup failure with a clear error message.
- `middleware/auth.py` is global opt-out — every route is protected unless
  explicitly added to `PUBLIC_PATHS`.
- `routers/health.py` returns HTTP 200 always — `status: degraded` when DB
  is unreachable, so Coolify only restarts on total process failure.
- Python 3.13 required — pydantic-core (Rust/PyO3) does not yet support 3.14.

### Connector architecture

The data source is abstracted behind `BaseRugbyConnector`. Switching
providers requires changing one file and one environment variable:

```
RUGBY_DATA_SOURCE=mock        # Phase 1 — no real provider yet
RUGBY_DATA_SOURCE=api_sports  # Future — if selected
RUGBY_DATA_SOURCE=statscore   # Future — if selected
RUGBY_DATA_SOURCE=sportradar  # Future — if selected
```

See `DECISIONS.md` D-012 for the provider selection status.

---

## db/

Database migrations and tests.

| File                                | Description                                                                                  |
| ----------------------------------- | -------------------------------------------------------------------------------------------- |
| `migrations/001_initial_schema.sql` | Full PostgreSQL schema: 21 tables, enums, RLS policies, GRANT statements, indexes, triggers. |
| `tests/test_rls_policies.sql`       | Manual RLS validation tests. Run in Supabase SQL Editor. Covers 7 isolation scenarios.       |

Migrations are plain SQL files, applied manually via the Supabase SQL
editor or psql. No ORM migration tool in V1 — keep it simple and explicit.

---

## dbt_project/

dbt Core data pipeline. Medallion architecture: bronze → silver → gold.

```
dbt_project/
├── models/
│   ├── bronze/            # Raw data as ingested — no transformation
│   │   ├── raw_matches.sql
│   │   ├── raw_player_stats.sql
│   │   ├── raw_fixtures.sql
│   │   └── raw_player_availability.sql
│   └── silver/            # Cleaned, typed, validated data
│       ├── stg_players.sql
│       ├── stg_matches.sql
│       ├── stg_match_stats.sql
│       ├── stg_fixtures.sql
│       └── stg_player_availability.sql
│   # gold/ — added in Phase 3 (fantasy points, leaderboard, player value)
├── tests/                 # dbt schema tests (not_null, unique, relationships)
├── dbt_project.yml        # dbt project configuration
└── profiles.yml.example   # Connection profile template (never commit profiles.yml)
```

### Medallion layers

| Layer  | Purpose                                   | Engine              |
| ------ | ----------------------------------------- | ------------------- |
| Bronze | Raw data from connector, stored as-is     | DuckDB (batch)      |
| Silver | Cleaned, typed, deduplicated              | DuckDB (batch)      |
| Gold   | Fantasy points, leaderboard, player value | DuckDB → PostgreSQL |

Gold layer is added in Phase 3 once the data provider is confirmed.

---

## docs/

Technical documentation. The CDC (`cdc*.md`, `cdc*.docx`) is gitignored
here — it is confidential and must never appear in the public repo.

---

## scripts/

Utility scripts. Not part of the application — run manually or in CI.

| File              | Purpose                                                                    |
| ----------------- | -------------------------------------------------------------------------- |
| `validate_api.py` | Phase 0 — tests a rugby data provider against the required stats checklist |

---

## frontend/

> **Not yet created.** Will be initialized with `create-next-app` in Phase 4.

Stack: Next.js 15 (App Router) + TypeScript + Tailwind CSS v4 + shadcn/ui

- Framer Motion + next-intl.

Key conventions (enforced from day one):

- Zero hardcoded UI strings — all text via `t('key')` from next-intl
- All translation strings in `messages/fr.json` (V1 — French only)
- Locale stored on `users.locale`, not in the URL path

---

## Environment variables

All required variables are documented in `.env.example`.
Never commit `.env` or any file containing real secrets.

See `.env.example` for the full list with descriptions.
