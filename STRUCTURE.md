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
│   ├── config.py          # App settings loaded from environment variables
│   │                      # via pydantic-settings. Never hardcode secrets.
│   ├── middleware/
│   │   └── auth.py        # JWT verification middleware (Supabase Auth tokens)
│   ├── routers/
│   │   └── health.py      # GET /health — liveness probe
│   ├── models/            # Pydantic models for request/response validation
│   │   ├── user.py        # User schema
│   │   ├── player.py      # Player schema (includes positions[] multi-position)
│   │   └── league.py      # League schema
│   └── connectors/        # Rugby data source abstraction layer
│       ├── base.py        # BaseRugbyConnector — abstract base class (ABC)
│       └── mock.py        # MockRugbyConnector — stub returning fixture data
│                          # Used during development until provider is confirmed
├── tests/
│   └── test_health.py     # Health endpoint smoke test
├── requirements.txt       # Production dependencies
└── requirements-dev.txt   # Dev dependencies (pytest, ruff, httpx...)
```

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

Plain SQL migration files for PostgreSQL (Supabase).

```
db/
└── migrations/
    └── 001_initial_schema.sql   # Full PostgreSQL schema: 21 tables, enums, RLS policies, indexes, triggers.
                                 # Includes RLS policies on all tables
```

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
