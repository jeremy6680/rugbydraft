# STRUCTURE.md — RugbyDraft

> Repository structure explained.
> Updated at each phase — reflects the current state of the codebase.
> Last updated: 2026-03-19 (Phase 2 — Draft Engine, broadcast wiring)

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
│   │   ├── draft.py           # POST /connect, POST /disconnect, GET /state
│   │   └── draft_assisted.py  # POST /assisted/enable, POST /assisted/pick
│   │                          # GET /assisted/log — commissioner-only (403 if not)
│   ├── schemas/
│   │ ├── **init**.py
│   │ └── draft.py # Pydantic response models for draft endpoints (D-025)
│   │ # DraftStateSnapshotResponse, PickRecordResponse
│   │ # Mirrors internal DraftStateSnapshot dataclass
│   └── models/            # Pydantic models — to be completed in Phase 2
│       ├── __init__.py
│       ├── user.py
│       ├── player.py
│       └── league.py
├── draft/
│   ├── __init__.py          # Draft engine package marker
│   ├── snake_order.py       # Pure snake draft order algorithm (no I/O)
│   │                        # Functions: generate_snake_order, get_pick_owner,
│   │                        # build_pick_slots, get_manager_picks
│   ├── timer.py             # Server-side pick countdown (asyncio.Task)
│   │                        # DraftTimer: start(), cancel(), time_remaining
│   │                        # on_expire callback triggers autodraft
│   ├── validate_pick.py     # Pure pick validation — 3 layers, typed exceptions
│   │                        # validate_pick(), RosterSnapshot, PickValidationError
│   │                        # Constants: ROSTER_SIZE=30, MAX_PER_NATION=8, MAX_PER_CLUB=6
│   ├── autodraft.py         # Autodraft pick selection algorithm (pure function)
│   │                        # select_autodraft_pick(): preference list → default value
│   │                        # AutodraftResult, AutodraftError
│   ├── events.py            # Typed broadcast event dataclasses (D-024)
│   │                        # DraftStartedEvent, DraftPickMadeEvent, DraftTurnChangedEvent
│   │                        # DraftManagerConnectedEvent, DraftManagerDisconnectedEvent
│   │                        # DraftCompletedEvent — all extend DraftEvent base class
│   ├── broadcaster.py       # Broadcast layer — Supabase Realtime (D-024)
│   │                        # BroadcasterProtocol (PEP 544), MockBroadcaster (tests),
│   │                        # SupabaseBroadcaster (production, channel per league)
│   ├── assisted.py          # Assisted Draft pure logic (CDC 7.5)
│   │                        # AssistedPickAuditEntry, AssistedDraftError subtypes
│   │                        # validate_commissioner, validate_assisted_mode_active
│   │                        # build_audit_entry — all pure functions, no I/O
│   ├── engine.py            # DraftEngine — authority of state (D-001)
│   │                        # Orchestrates snake_order, timer, validate_pick, autodraft
│   │                        # broadcaster injected via __init__ (default: MockBroadcaster)
│   │                        # DraftState, DraftStateSnapshot, PickRecord, DraftStatus
│   │                        # asyncio.Lock prevents race conditions on submit_pick()
│   └── registry.py          # DraftRegistry — thread-safe dict league_id → DraftEngine
│                            # Stored as app.state.draft_registry (FastAPI lifespan)
│                            # register(), get(), remove(), active_league_ids()
├── tests/
│   ├── __init__.py
│   ├── test_health.py       # 8 tests — health endpoint + auth middleware
│   ├── test_reconnection.py # 4 tests — reconnection protocol (D-025)
│   │                        # reconnect during own turn, after timer expired,
│   │                        # while other manager picks, GET state no side effects
│   └── draft/
│       ├── __init__.py              # Draft tests package marker
│       ├── test_snake_order.py      # 33 unit tests for snake_order.py
│       ├── test_timer.py            # 22 unit tests for timer.py (pytest-asyncio)
│       ├── test_validate_pick.py    # 17 unit tests for validate_pick.py
│       ├── test_autodraft.py        # 16 unit tests for autodraft.py
│       └── test_engine.py           # 26 unit tests for engine.py + broadcast events
│       └── test_assisted.py     # 19 tests — Assisted Draft mode (D-026)
│                                # TestEnableAssistedMode (5), TestSubmitAssistedPick (8)
│                                # TestAuditLog (3), TestAssistedBroadcastEvents (2)
│                                # TestFullAssistedDraftFlow (1)
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

## connectors/

Connector implementations for rugby data sources.
All connectors implement `BaseRugbyConnector` — switching providers
requires changing one file and one environment variable.

```
connectors/
├── __init__.py
├── base.py          # BaseRugbyConnector ABC — defines the connector contract
├── mock.py          # MockRugbyConnector — returns fixture data for testing
└── requirements.txt # Connector dependencies (pydantic) — used by CI and pipeline
```

| File               | Purpose                                                      |
| ------------------ | ------------------------------------------------------------ |
| `base.py`          | Abstract base class — all connectors must implement this     |
| `mock.py`          | Stub connector returning hardcoded data — used in Phase 1 CI |
| `requirements.txt` | Pinned dependencies for CI cache stability                   |

Real connector implementations (`statscore.py`, `sportradar.py`, etc.)
will be added in Phase 3 once the provider is confirmed (D-012).

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
│   ├── bronze/            # Raw data as ingested — no transformation, views
│   │   ├── raw_matches.sql             # Completed match results
│   │   ├── raw_player_stats.sql        # Individual player stats per match
│   │   ├── raw_fixtures.sql            # Upcoming and recent fixtures
│   │   └── raw_player_availability.sql # Player injury/suspension status
│   └── silver/            # Cleaned, typed, validated data — tables
│       ├── stg_players.sql             # Player reference data
│       ├── stg_matches.sql             # Finished matches only
│       ├── stg_match_stats.sql         # Stats with COALESCE on conditional fields
│       ├── stg_fixtures.sql            # All fixtures, canonical column names
│       └── stg_player_availability.sql # Availability with typed fields
│   # gold/ — added in Phase 3 (fantasy points, leaderboard, player value)
├── tests/                 # dbt schema tests (not_null, unique, accepted_values)
├── models/schema.yml      # Test definitions for bronze and silver layers
├── dbt_project.yml        # dbt project configuration
├── profiles.yml.example   # Connection profile template (never commit profiles.yml)
├── requirements.txt           # Pipeline dependencies — dbt-duckdb (pinned)

```

### Medallion layers

| Layer  | Purpose                                   | Materialized | Engine              |
| ------ | ----------------------------------------- | ------------ | ------------------- |
| Bronze | Raw data from connector, stored as-is     | Views        | DuckDB              |
| Silver | Cleaned, typed, deduplicated              | Tables       | DuckDB              |
| Gold   | Fantasy points, leaderboard, player value | Tables       | DuckDB → PostgreSQL |

Gold layer is added in Phase 3 once the data provider is confirmed.

### Ingestion script

`scripts/ingest_mock.py` calls the active connector and writes JSON files
to `data/raw/`. These files are the source for bronze models via `read_json_auto()`.

Run order:

1. `python3 scripts/ingest_mock.py` — fetch + write JSON
2. `dbt run` (from `dbt_project/`) — bronze → silver transformation
3. `dbt test` — validate silver layer

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

Stack: Next.js 15 (App Router) + TypeScript + Tailwind CSS v4 + shadcn/ui + next-intl

Initialized in Phase 1. Located in `frontend/` subdirectory of the public repo.

### Key conventions

- Zero hardcoded UI strings — all text via `t('key')` from next-intl
- All translation strings in `messages/fr.json` (V1 — French only)
- Locale is part of the URL path: `/fr/dashboard`, `/fr/draft`, etc.
- `NEXT_PUBLIC_` prefix required for any env var accessed browser-side
- Frontend env vars live in `frontend/.env.local` (never at repo root)

### Structure

```
frontend/
├── messages/
│   └── fr.json                        # All French UI strings — never hardcode in components
├── public/                             # Static assets (favicons, images)
├── src/
│   ├── app/
│   │   ├── auth/
│   │   │   └── callback/
│   │   │       └── route.ts           # Supabase Auth callback — exchanges code for session
│   │   └── [locale]/                  # next-intl dynamic locale segment
│   │       ├── layout.tsx             # Root layout: fonts, NextIntlClientProvider, body styles
│   │       ├── page.tsx               # Temp home page (Phase 1 skeleton)
│   │       ├── (protected)/           # Route group — authenticated pages only
│   │       │   ├── layout.tsx         # Session guard (getUser) + AppShell wrapper
│   │       │   └── dashboard/
│   │       │       └── page.tsx       # Dashboard placeholder (replaced in Phase 4)
│   │       └── login/
│   │           └── page.tsx           # Login page: split-screen brand + magic link form
│   ├── components/
│   │   ├── auth/
│   │   │   └── LoginForm.tsx          # Magic link form — Client Component
│   │   └── layout/
│   │       ├── AppShell.tsx           # Layout wrapper: Sidebar + main + BottomNav
│   │       ├── BottomNav.tsx          # Mobile fixed bottom nav — 5 items, Client Component
│   │       └── Sidebar.tsx            # Desktop sticky sidebar — collapsible, Client Component
│   ├── i18n/
│   │   ├── routing.ts                 # next-intl: supported locales, defaultLocale
│   │   └── request.ts                 # next-intl: server-side locale resolution
│   └── lib/
│       └── supabase/
│           ├── client.ts              # createBrowserSupabaseClient — Client Components
│           └── server.ts              # createServerSupabaseClient — Server Components
├── middleware.ts                       # next-intl routing + Supabase session refresh + route protection
├── .env.example
├── next.config.ts
└── tsconfig.json
```

---

## Environment variables

All required variables are documented in `.env.example`.
Never commit `.env` or any file containing real secrets.

See `.env.example` for the full list with descriptions.
