# STRUCTURE.md — RugbyDraft

> Repository structure explained.
> Updated at each phase — reflects the current state of the codebase.
> Last updated: 2026-03-23 (feat/scoring-v2-dsg — scoring system v2, DSG field mapping)

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
│   ├── dependencies.py    # Shared FastAPI deps: get_current_user_id, get_supabase_client
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
│   │   ├── health.py          # GET /health — liveness probe (public, no JWT)
│   │   ├── leagues.py         # GET /leagues/{league_id}/standings
│   │   │                      # StandingEntry, LeagueStandingsResponse
│   │   │                      # Membership guard + JOIN users for display_name
│   │   ├── lineup.py          # 4 endpoints: GET/PUT lineup, PATCH captain/kicker
│   │   ├── trades.py          # 8 endpoints: POST /trades, GET /trades/{id},
│   │   │                      # GET /leagues/{league_id}/trades,
│   │   │                      # POST /{id}/accept, POST /{id}/reject,
│   │   │                      # POST /{id}/cancel, POST /{id}/veto,
│   │   │                      # POST /complete-expired (cron internal)
│   │   ├── infirmary.py       # 3 endpoints: PUT /ir/place, PUT /ir/reintegrate,
│   │   │                      # GET /ir/alerts — IR slot management (CDC §6.4)
│   │   ├── waivers.py         # 4 endpoints: POST/GET claims, DELETE cancel, POST process
│   │   ├── draft.py           # POST /connect, POST /disconnect, GET /state
│   │   └── draft_assisted.py  # POST /assisted/enable, POST /assisted/pick
│   │                          # GET /assisted/log — commissioner-only (403 if not)
│   ├── services/
│   │   ├── lineup_service.py  # Business logic: lock validation, IR exclusion, multi-position, CDC 6.6 edge cases
│   │   ├── waiver_service.py  # Waiver I/O: submit, cancel, list, process cycle
│   │   └── trade_service.py   # Trade I/O: create, accept, reject, cancel,
│   │                          # veto, complete_expired, get, list
│   ├── schemas/
│   │ ├── **init**.py
│   │ └── draft.py             # Pydantic response models for draft endpoints (D-025)
│   │                          # DraftStateSnapshotResponse, PickRecordResponse
│   │                          # Mirrors internal DraftStateSnapshot dataclass
│   └── models/                # Pydantic models — to be completed in Phase 2
│       ├── __init__.py
│       ├── user.py
│       ├── player.py
│       ├── league.py
│       └── lineup.py        # Pydantic models: LineupSubmission, LineupResponse, CaptainUpdate, KickerUpdate
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
│   ├── ghost_team.py        # Ghost team generation — pure functions, no I/O (CDC s.11)
│   │                        # GhostTeam dataclass (frozen), create_ghost_teams(n)
│   │                        # ghost_teams_needed(manager_count) — bracket completion logic
│   │                        # is_ghost_id() — single source of truth for ghost detection
│   │                        # generate_ghost_name(), generate_ghost_avatar()
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
│   ├── roster_coverage.py   # Post-draft roster coverage validation (CDC 6.2)
│   │                        # validate_roster_coverage(): pure function, no I/O
│   │                        # RosterCoverageResult, RosterCoverageError,
│   │                        # RosterIncompleteError — called by _complete_draft()
│   ├── engine.py            # DraftEngine — authority of state (D-001)
│   │                        # Orchestrates snake_order, timer, validate_pick, autodraft
│   │                        # broadcaster injected via __init__ (default: MockBroadcaster)
│   │                        # DraftState, DraftStateSnapshot, PickRecord, DraftStatus
│   │                        # asyncio.Lock prevents race conditions on submit_pick()
│   └── registry.py          # DraftRegistry — thread-safe dict league_id → DraftEngine
│                            # Stored as app.state.draft_registry (FastAPI lifespan)
│                            # register(), get(), remove(), active_league_ids()
├── trades/
│   ├── __init__.py          # Trade system package marker
│   ├── window.py            # Pure: trade window open/closed check
│   │                        # TradeWindowContext, is_trade_window_open(),
│   │                        # midseason_cutoff_round() — double check date + round
│   ├── validate_trade.py    # Pure: 7-rule proposal validation
│   │                        # TradeParty, TradeProposal, validate_trade()
│   │                        # Typed exceptions: TradeWindowClosedError,
│   │                        # TradeSelfTradeError, TradeGhostTeamError,
│   │                        # TradeFormatError, TradeOwnershipError,
│   │                        # TradeDuplicatePlayerError, TradeIRBlockError
│   └── processor.py         # Pure: state machine for all trade transitions
│                            # TradeRecord, TradePlayerEntry, TradeStatus
│                            # propose_trade(), accept_trade(), reject_trade()
│                            # cancel_trade(), commissioner_veto(), complete_trade()
│                            # VETO_WINDOW_HOURS = 24
├── infirmary/
│   ├── __init__.py          # Infirmary package marker
│   ├── ir_rules.py          # Pure infirmary business rules (CDC §6.4)
│   │                        # IRSlotSnapshot, validate_ir_placement,
│   │                        # validate_ir_reintegration, get_overdue_ir_slots
│   │                        # Constants: MAX_IR_SLOTS=3, IR_REINTEGRATION_DEADLINE_DAYS=7
│   │                        # Exceptions: IRCapacityError, IRPlayerAlreadyInIRError,
│   │                        # IRPlayerNotRecoveredError
│   └── ir_scheduler.py      # APScheduler daily job (09:00 UTC)
│                            # run_ir_recovery_scan(): detect recoveries,
│                            # write ir_recovery_deadline, broadcast Realtime alert
│                            # register_ir_jobs(): called from FastAPI lifespan
├── waivers/
│   ├── __init__.py          # Waiver system package marker
│   ├── window.py            # Pure: waiver window open/closed (Tue 07:00 → Wed 23:59:59)
│   ├── priority.py          # Pure: priority ordering from league standings
│   ├── validate_claim.py    # Pure: 5-rule claim validation (window, ghost, IR, free, owned)
│   └── processor.py         # Pure: full cycle processing — granted/denied/skipped
├── tests/
│   ├── __init__.py
│   ├── test_fantasy_points.py  # 39 tests — scoring system v2 (D-039): attack, defence,
│   │                           # captain multiplier, kicker-only, full player profiles
│   ├── test_health.py       # 8 tests — health endpoint + auth middleware
│   ├── test_lineup.py       # 14 tests: Pydantic, lock, IR, multi-position, captain/kicker CDC 6.6
│   ├── test_reconnection.py # 4 tests — reconnection protocol (D-025)
│   │                        # reconnect during own turn, after timer expired,
│   │                        # while other manager picks, GET state no side effects
│   ├── test_trades.py       # 59 tests — window, validation (7 rules),
│   │                        # processor (all state transitions)
│   └── draft/
│       ├── __init__.py              # Draft tests package marker
│       ├── test_snake_order.py      # 33 unit tests for snake_order.py
│       ├── test_timer.py            # 22 unit tests for timer.py (pytest-asyncio)
│       ├── test_validate_pick.py    # 17 unit tests for validate_pick.py
│       ├── test_autodraft.py        # 16 unit tests for autodraft.py
│       ├── test_ghost_team.py       # 41 unit tests for ghost_team.py
│       │                            # TestIsGhostId, TestGenerateGhostName,
│       │                            # TestGenerateGhostAvatar, TestCreateGhostTeams,
│       │                            # TestGhostTeamsNeeded
│       ├── test_engine.py           # 53 unit tests for engine.py + ghost team integration
│       ├── test_assisted.py         # 19 tests — Assisted Draft mode (D-026)
│       │                            # TestEnableAssistedMode (5), TestSubmitAssistedPick (8)
│       │                            # TestAuditLog (3), TestAssistedBroadcastEvents (2)
│       │                            # TestFullAssistedDraftFlow (1)
│       └── test_roster_constraints.py # 14 tests — bench coverage validation
│                                    # TestValidRosters (4), TestMissingPositionCoverage (5)
│                                    # TestMultiPositionCoverage (2), TestIncompleteRoster (3)
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
├── base.py          # BaseRugbyConnector ABC + PlayerMatchStats (scoring v2 — D-039)
├── mock.py          # MockRugbyConnector — realistic test data, scoring v2 fields
├── dsg.py           # DSGConnector — XML parser, HTTP Basic Auth + authkey,
│                    # 3-pass strategy: try_counts + card_map + player_stats
│                    # penalties_made = goals - conversion_goals (computed here)
│                    # position string → PositionType enum mapping
└── requirements.txt # Connector dependencies (pydantic, httpx)
└── tests/
    ├── __init__.py
    └── test_dsg_connector.py  # 33 unit tests — pure XML parsing, no HTTP
```

| File               | Purpose                                                                      |
| ------------------ | ---------------------------------------------------------------------------- |
| `base.py`          | Abstract base class — PlayerMatchStats updated for DSG field mapping (D-039) |
| `mock.py`          | Stub connector — updated with scoring v2 fields for test coverage            |
| `requirements.txt` | Pinned dependencies for CI cache stability                                   |

DSG connector (`connectors/dsg.py`) — implemented. See KB-008 (resolved).

---

## db/

Database migrations and tests.

| File                                      | Description                                                                                                                                              |
| ----------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `migrations/001_initial_schema.sql`       | Full PostgreSQL schema: 21 tables, enums, RLS policies, GRANT statements, indexes, triggers.                                                             |
| `migrations/002_phase3_additions.sql`     | Phase 3 tables: `weekly_lineups`, `waivers`, `trades`, `trade_players`, `fantasy_scores_staging`. Column: `drafts.manager_order`. RLS on all new tables. |
| `migrations/003_add_external_ids.sql`     | `players.external_id` and `real_matches.external_id` — bridge between silver pipeline IDs and PostgreSQL UUIDs (D-031).                                  |
| `migrations/004_add_trade_fields.sql`     | Phase 3 — trade fields additions.                                                                                                                        |
| `migrations/005_ir_recovery_deadline.sql` | Phase 3 — `ir_recovery_deadline` column on `weekly_lineups`. Index on non-null deadlines.                                                                |

Migrations are plain SQL files, applied manually via the Supabase SQL
editor or psql. No ORM migration tool in V1 — keep it simple and explicit.

---

## dbt_project/

dbt Core data pipeline. Medallion architecture: bronze → silver → gold.

```
dbt_project/
├── models/
│   ├── sources.yml                     # All PostgreSQL tables used as sources in gold models.
│   │                                   # Two categories: application tables (FastAPI) and
│   │                                   # pipeline staging tables (pipeline_stg_* from export script).
│   ├── bronze/                         # Raw data as ingested — no transformation, views
│   │   ├── raw_matches.sql             # Completed match results
│   │   ├── raw_player_stats.sql        # Individual player stats per match
│   │   ├── raw_fixtures.sql            # Upcoming and recent fixtures
│   │   └── raw_player_availability.sql # Player injury/suspension status
│   ├── silver/                         # Cleaned, typed, validated data — tables
│   │   ├── stg_players.sql             # Player reference data
│   │   ├── stg_matches.sql             # Finished matches only
│   │   ├── stg_match_stats.sql         # Stats with DSG field mapping (D-039) — scoring v2
│   │   ├── stg_fixtures.sql            # All fixtures, canonical column names
│   │   └── stg_player_availability.sql # Availability with typed fields
│   └── gold/                           # Fantasy points, leaderboard, player value — tables
│       ├── _gold_models.yml            # Schema tests for all gold models
│       ├── mart_fantasy_points.sql     # Points per starter per round (full CDC scoring)
│       ├── mart_roster_scores.sql      # Aggregate points per roster per round
│       ├── mart_leaderboard.sql        # League standings with DENSE_RANK + tiebreakers
│       ├── mart_player_pool.sql        # Player availability per league (free/drafted/injured)
│       ├── mart_player_value.sql       # Default value score for autodraft + ghost team
│       └── mart_player_stats_ui.sql   # Stats per player per period (1w/2w/4w/season)
│                                      # Powers the Stats page — avg_points, trend, all scoring stats
├── tests/                              # dbt schema tests (not_null, unique, accepted_values)
├── models/schema.yml                   # Test definitions for bronze and silver layers
├── dbt_project.yml                     # dbt project configuration
├── profiles.yml.example                # Dual-target: ci (DuckDB, dev/CI) + prod (PostgreSQL/Supabase, Airflow)
│                                       # See D-030. Copy to profiles.yml and fill SUPABASE_DB_* vars.
├── requirements.txt                    # Pipeline dependencies — dbt-duckdb (pinned)

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

| File                     | Purpose                                                                                                                                                                                                     |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `validate_api.py`        | Phase 0 — tests a rugby data provider against the required stats checklist                                                                                                                                  |
| `export_silver_to_pg.py` | Phase 3 — exports dbt silver tables from DuckDB to PostgreSQL as `pipeline_stg_*` tables. Bridge step between dbt silver (DuckDB) and dbt gold (PostgreSQL). Runs as step 3 of Airflow post_match_pipeline. |
| `ingest_mock.py`         | Phase 1 — calls active connector and writes JSON to `data/raw/`. Entry point for daily crons and post_match_pipeline. Updated for scoring v2 fields.                                                        |

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
│   │       │   ├── dashboard/
│   │       │   │   └── page.tsx       # Dashboard placeholder (replaced in Phase 4)
│   │       │   ├── draft/
│   │       │   │   └── [draftId]/
│   │       │   │       └── page.tsx   # Draft Room page — Server Component
│   │       │   │                      # Fetches players + manager names server-side,
│   │       │   │                      # passes currentUserId + data to DraftRoom (D-040)
│   │       │   └── league/
│   │       │       └── [leagueId]/
│   │       │           ├── leaderboard/
│   │       │           │   └── page.tsx   # Leaderboard page — Server Component
│   │       │           │                  # SSR fetch (revalidate: 60s), passes initialData
│   │       │           │                  # to LeaderboardTable for Realtime hydration
│   │       │           └── roster/
│   │       │               └── page.tsx   # Roster page — Server Component
│   │       │                              # Fetches current round server-side (revalidate: 60s)
│   │       │                              # Passes leagueId + roundId to RosterManagement
│   │       └── login/
│   │           └── page.tsx           # Login page: split-screen brand + magic link form
│   ├── components/
│   │   ├── auth/
│   │   │   └── LoginForm.tsx          # Magic link form — Client Component
│   │   ├── draft/
│   │   │   ├── DraftRoom.tsx          # Main orchestrator — mobile-first layout
│   │   │   │                          # Sidebar desktop / bottom sheet mobile
│   │   │   ├── DraftTimer.tsx         # Countdown with urgency colours + Framer Motion pulse
│   │   │   │                          # Resyncs from server snapshot on each broadcast
│   │   │   ├── DraftStatusBanner.tsx  # Contextual banner: your turn / waiting /
│   │   │   │                          # autodraft / completed — animated with Framer Motion
│   │   │   ├── DraftPlayerCard.tsx    # Single player card: available (button) /
│   │   │   │                          # drafted / injured / suspended (div, non-interactive)
│   │   │   ├── DraftPlayerList.tsx    # Filterable scrollable pool:
│   │   │   │                          # text search + position chips, memoised sort
│   │   │   ├── DraftOrderPanel.tsx    # Snake order upcoming slots + full pick history
│   │   │   └── DraftPickConfirmModal.tsx  # Pick confirmation dialog:
│   │   │                                  # focus trap, Escape key, Framer Motion
│   │   ├── roster/
│   │   │   ├── RosterManagement.tsx       # Main orchestrator — mobile tabs / desktop 3-col grid
│   │   │   │                              # Swap flow: 2-click starter ↔ bench, updateLineup dispatch
│   │   │   ├── RosterPlayerCard.tsx       # Player card atom: lock/captain/kicker/IR states
│   │   │   │                              # Multi-position selector (locked at kick-off)
│   │   │   ├── RosterSlotGrid.tsx         # 15 starter slots in jersey order, grouped by line
│   │   │   ├── RosterBenchGrid.tsx        # Bench slots + coverage bar (CDC §6.2 minimums)
│   │   │   ├── RosterIRPanel.tsx          # IR slots (max 3), reintegration CTA, blocking alert
│   │   │   └── RosterCaptainKickerBar.tsx # Captain (×1.5) + kicker designation
│   │   │                                  # Mobile: fixed bottom bar. Desktop: inline.
│   │   ├── leaderboard/
│   │   │   ├── LeaderboardTable.tsx       # Standings table orchestrator — loading/error/empty states
│   │   │   │                              # Assembles useLeaderboard + LeaderboardRow
│   │   │   └── LeaderboardRow.tsx         # Single row atom — medal icons (top 3), current user highlight
│   │   │                                  # Framer Motion staggered entry animation
│   │   └── layout/
│   │       ├── AppShell.tsx           # Layout wrapper: Sidebar + main + BottomNav
│   │       ├── BottomNav.tsx          # Mobile fixed bottom nav — 5 items, Client Component
│   │       └── Sidebar.tsx            # Desktop sticky sidebar — collapsible, Client Component
│   ├── hooks/
│   │   ├── useDraftRealtime.ts        # Supabase Realtime subscription + polling fallback
│   │   │                              # Calls POST /connect on mount, POST /disconnect on unmount
│   │   │                              # Polling every 5s when Realtime disconnected
│   │   ├── useRosters.ts              # Roster + lineup fetch, coverage computation,
│   │   │                              # lock status polling (30s), optimistic updates + rollback
│   │   └── useLeaderboard.ts          # Standings fetch + Supabase Realtime Postgres Changes
│   │                                  # Re-fetch strategy on CDC event, polling fallback 60s
│   ├── i18n/
│   │   ├── routing.ts                 # next-intl: supported locales, defaultLocale
│   │   └── request.ts                 # next-intl: server-side locale resolution
│   ├── lib/
│   │   └── supabase/
│   │       ├── client.ts              # createBrowserSupabaseClient — Client Components
│   │       └── server.ts              # createServerSupabaseClient — Server Components
│   └── types/
│       ├── draft.ts                   # TypeScript mirror of FastAPI draft schemas
│       │                              # DraftStateSnapshot, PickRecord, DraftUIState
│       ├── leaderboard.ts             # StandingEntry, LeagueStandingsResponse
│       │                              # TypeScript mirror of FastAPI leagues.py schemas
│       ├── player.ts                  # TypeScript mirror of PlayerSummary (backend)
│       └── roster.ts                  # RosterSlot, WeeklyLineupEntry, LineupUpdatePayload
│                                      # RosterCoverageStatus, STARTER_POSITIONS, BENCH_COVERAGE_MINIMUMS
├── proxy.ts                           # next-intl routing + Supabase session refresh
│                                      # + route protection (renamed from middleware.ts — KB-002)
├── .env.example
├── next.config.ts
└── tsconfig.json
```

---

## Environment variables

All required variables are documented in `.env.example`.
Never commit `.env` or any file containing real secrets.

See `.env.example` for the full list with descriptions.

---

## airflow/

Airflow 2.7.2 — orchestrates the `post_match_pipeline` DAG only.
All other scheduled tasks use Cron Coolify (see DECISIONS.md D-002).

### Layout

| Path                                          | Purpose                                                                            |
| --------------------------------------------- | ---------------------------------------------------------------------------------- |
| `dags/post_match_pipeline.py`                 | Main DAG: detect → ingest → bronze+silver → export → gold → atomic commit → notify |
| `plugins/operators/dbt_operator.py`           | Custom `DbtRunOperator` and `DbtTestOperator`                                      |
| `plugins/operators/atomic_commit_operator.py` | Atomic PostgreSQL transaction: staging → fantasy_scores                            |
| `tests/conftest.py`                           | pytest path setup — loads plugins and dags dirs before test imports                |
| `tests/test_dag_structure.py`                 | 29 structural tests — task presence, dependencies, configuration                   |
| `tests/requirements-test.txt`                 | Test-only deps (apache-airflow, pendulum<3, psycopg2, httpx, pytest)               |
| `Dockerfile`                                  | Custom image: apache/airflow:2.7.2 + dbt + duckdb + psycopg2                       |
| `docker-compose.yml`                          | Local setup: LocalExecutor, airflow-postgres metadata DB, UI on :8080              |
| `requirements.txt`                            | Extra pip deps added on top of the base image                                      |
| `.env.example`                                | Environment variable template for local dev                                        |

### Run order (local)

```bash
# One-time setup
cd airflow/
docker compose up airflow-init

# Start
docker compose up -d

# UI
open http://localhost:8080  # admin / admin
```

### Test setup (no Docker needed)

```bash
# Dedicated venv — Python 3.11 required (Airflow 2.7 + pendulum 2.x constraint)
python -m venv .venv-airflow
source .venv-airflow/bin/activate
pip install -r airflow/tests/requirements-test.txt
pytest airflow/tests/test_dag_structure.py -v
```
