# NEXT_STEPS.md — RugbyDraft

> Current status: Phase 4 in progress — feat/scoring-d050 complete, ready for Phase 4 PR.
> Last updated: 2026-04-05

---

## ✅ Phase 0 — API Validation (complete)

**Status:** DSG confirmed as data provider. All blocking stats validated. Scoring system revised.
**Last updated:** 2026-03-23

### Completed

- [x] Created free API-Sports account and obtained API key
- [x] Built validation script (`scripts/validate_api.py`)
- [x] Tested API-Sports Rugby on Six Nations 2024 season
- [x] **Finding: API-Sports provides scores only — no player-level stats endpoint exists**
- [x] Investigated alternative providers (Sportradar, DSG, Statscore, stats.sixnationsrugby.com)
- [x] Contacted Data Sports Group (DSG) — 2026-03-18
- [x] Contacted Statscore — 2026-03-18, received initial reply, sent detailed requirements
- [x] DSG trial activated — 2026-03-21 (2 weeks, Top 14 + player stats)
- [x] Phase 0 validation script run on match 3798425 (Clermont vs Toulouse, Top 14 2025/26)
- [x] **All blocking stats confirmed ✅ — see `docs/dsg_api_reference.md`**
- [x] Scoring system revised for DSG coverage — see D-038
- [x] Provider decision documented — D-037 (supersedes D-012)
- [x] Cost model updated — break-even revised to ~100 paying subscribers (see D-037)
- [x] `CONTEXT.md` scoring summary updated
- [x] `docs/dsg_api_reference.md` created (gitignored — confidential)

---

## ✅ Phase 1 — Foundations (complete)

**Estimated duration:** 2–3 weeks
**Objective:** Project skeleton, database schema, data pipeline up to silver layer, CI/CD, i18n structure.

> **Note on data pipeline:** implement `BaseRugbyConnector` + a mock connector for testing. Do NOT hardcode API-Sports as the only implementation. The real connector will be added once the provider is confirmed (before Phase 3).

### Repositories & structure

- [x] Create public repo `jeremy6680/rugbydraft`
- [x] Set up folder structure
- [x] Add `.gitignore` — includes `docs/cdc*.md`, `docs/cdc*.docx`, `.env*`
- [x] Copy `CONTEXT.md`, `DECISIONS.md`, `NEXT_STEPS.md` to repo root
- [x] Create `STRUCTURE.md`
- [x] Create `.env.example` with all required variables documented
- [x] Update `README.md` — public description, no mention of business model or Staff IA
- [ ] Create private repo `jeremy6680/rugbydraft-private` — Phase 5, not needed yet

### Database (Supabase)

- [x] Create Supabase project
- [x] Write full PostgreSQL schema (all tables from CDC section 18)
- [x] Enable Row Level Security on all tables
- [x] Create initial migrations (plain SQL files in `db/migrations/`)
- [x] Test RLS policies: a user can only access their own league data

### Data pipeline — Bronze/Silver

- [x] Implement `connectors/base.py` — `BaseRugbyConnector` ABC
- [x] Implement `connectors/mock.py` — stub connector returning fixture data for testing
- [x] Set `RUGBY_DATA_SOURCE=mock` in `.env.example` (updated to real provider once confirmed)
- [x] dbt project init (`dbt init rugbydraft`)
- [x] Bronze models: `raw_matches`, `raw_player_stats`, `raw_fixtures`, `raw_player_availability`
- [x] Silver models: `stg_players`, `stg_matches`, `stg_match_stats`, `stg_fixtures`, `stg_player_availability`
- [x] dbt tests on silver models (not_null, unique on key fields)
- [x] `connectors/dsg.py` — DSGConnector: XML parser, HTTP Basic Auth,
      penalties_made computed (goals - conversion_goals), cards joined
      from bookings node, tries joined from scores node
- [ ] Cron Coolify: `daily_fixtures` (06:00) and `daily_availability` (08:00)

### Backend skeleton

- [x] FastAPI project init
- [x] Supabase Auth integration (JWT verification middleware)
- [x] Basic health endpoint `GET /health`
- [x] Pydantic models for core entities (Player, League, User)
- [x] Rate limiting with slowapi (100 req/min per IP)

### Frontend skeleton

- [x] `npx create-next-app@latest` with App Router + TypeScript + Tailwind v4
- [x] Install and configure next-intl
- [x] Create `messages/fr.json` with initial keys
- [x] Supabase Auth UI integration (magic link — Google OAuth deferred to pre-Phase 4)
- [x] shadcn/ui install + theme configuration (Figma palette — see D-017)
- [x] `frontend/.env.example` created — env vars split: frontend vs backend
- [x] Basic layout: bottom nav bar (mobile), sidebar (desktop) — AppShell pattern
- [x] Route protection middleware (redirect to /fr/login if unauthenticated)

### CI/CD

- [x] GitHub Actions: ruff + pytest — `ci-python.yml`
- [x] GitHub Actions: TypeScript lint + axe-core — `ci-frontend.yml`
- [x] GitHub Actions: dbt pipeline (bronze → silver) — `ci-dbt.yml`

---

## ✅ Phase 2 — Draft Engine (complete)

**Estimated duration:** 3–4 weeks
**Prerequisite:** Phase 1 complete ✅, PostgreSQL schema live ✅.

### Core draft logic

- [x] Snake draft order algorithm (N managers, 2N picks per cycle)
- [x] Server-side timer (FastAPI manages countdown, not clients)
- [x] Pick validation: correct manager, correct turn, player available
- [x] Autodraft algorithm: pick from preference list, or by default value score
- [x] Timeout → auto-activate autodraft for remaining picks
- [x] "Manager never connected" → full autodraft from draft start

### Realtime (Supabase Realtime as broadcast)

- [x] FastAPI broadcasts state updates to Supabase Realtime channel
- [ ] Client subscribes to channel, renders state received from server
      → **Phase 4 (Frontend)** — Next.js `useEffect` + `supabase.channel()` subscription
- ~~Never write draft state directly from client to DB~~
  → Architectural principle (D-001), not a task. Guaranteed by design: only FastAPI writes to the DB.

### Reconnection protocol (see DECISIONS.md D-001)

- [x] On reconnect: FastAPI sends full state snapshot (picks made, current pick, time remaining)
- [x] If manager reconnects during their turn with time remaining: they can pick
- [x] If timer expired during disconnection: autodraft pick is final
- [x] Document recovery procedure for FastAPI restart mid-draft

### Draft Assistée (fallback mode)

- [x] Commissioner UI: "Switch to Assisted Draft" button
- [x] Commissioner enters picks one by one, no timer
- [x] Audit log: each pick stamped with timestamp + "entered by commissioner"
- [x] Log visible to all managers

### Ghost team

- [x] Ghost team creation when manager count is odd or below competition minimum
- [x] Random name generator
- [x] Autodraft with default value algorithm
- [x] Ghost team excluded from waivers and trades

### Tests (mandatory — PRs blocked if failing)

- [x] Snake order for 2, 3, 4, 5, 6 managers
- [x] Timer timeout → autodraft activation
- [x] Client reconnection during pick
- [x] Client reconnection after pick (timer expired)
- [x] Draft Assistée: picks logged correctly
- [x] Roster constraint validation (coverage minimums)

---

## 🟡 Phase 3 — Gameplay (in progress)

**Estimated duration:** 2–3 weeks
**Prerequisite:** Phase 2 complete + data provider confirmed (D-012).

### Database migrations

- [x] Migration 002: `weekly_lineups`, `waivers`, `trades`, `trade_players`,
      `fantasy_scores_staging`, `drafts.manager_order` — all with RLS + indexes
- [x] Migration 003: `players.external_id`, `real_matches.external_id`
      — bridge between silver pipeline IDs and PostgreSQL UUIDs (D-031)
- [x] `weekly_lineups.slot_type` column added (ALTER TABLE — was missing from 001)

### Data pipeline — Gold

- [x] Dual-target dbt architecture: DuckDB (ci) + PostgreSQL (prod) — D-030
- [x] `scripts/export_silver_to_pg.py` — DuckDB → PostgreSQL bridge for gold models
- [x] `dbt_project/models/sources.yml` — all PostgreSQL sources declared
- [x] `mart_fantasy_points`: full CDC scoring — captain ×1.5 (nearest 0.5),
      kicker-only stats, COALESCE on all stats, double-match dedup via
      `is_first_match_of_round` (CDC 6.6)
- [x] `mart_roster_scores`: aggregate points per roster per round
- [x] `mart_leaderboard`: standings with wins/losses, DENSE_RANK, tiebreaker
- [x] `mart_player_pool`: free/drafted/injured/suspended status per league
- [x] `mart_player_value`: default value score for autodraft (recency-weighted)
- [x] `dbt run --target prod --select gold` passes — 5/5 models ✅
- [ ] `dbt test --target prod --select gold` — run after seeding real data

### Airflow — post_match_pipeline

- [x] DAG: detect → ingest → bronze → dbt silver → dbt gold → write to `fantasy_scores_staging` → atomic commit → notify
- [x] Atomic commit: single PostgreSQL transaction `fantasy_scores_staging` → `fantasy_scores`
- [ ] "Scores being processed" indicator while pipeline runs (frontend — Phase 4)
- [x] Retry: 3 attempts with exponential backoff on API failure

### Weekly lineup management

- [x] Starter/bench/IR slot management API
- [x] Progressive lock: per-match, not per-round (locked at kick-off of player's team match)
- [x] Lock validation: cannot change captain/kicker after their team's kick-off
- [x] Multi-position player: position choice locked at kick-off

### Edge cases (from CDC section 6.6)

- [x] Player plays two matches in same round → only first match counts
- [x] Captain change between two matches in same round → allowed until captain's team kick-off
- [x] Kicker change after first match → blocked until next round

### Waivers

- [x] Waiver window: Tuesday morning → Wednesday evening
- [x] Priority: lowest-ranked manager first
- [x] Priority reset after each cycle
- [x] Blocking rule: manager with unintegrated recovered IR player cannot claim waivers
- [x] Waiver priority ordering
- [x] Waiver block: IR player not reintegrated

### Trades

- [x] Trade window: start of competition → mid-season (`ceil(total_rounds / 2)`)
- [x] Formats: 1v1, 1v2, 1v3 (symmetric — each side sends 1, 2, or 3 players)
- [x] Commissioner veto: 24h window, must provide reason (text field), log visible to all
- [x] Trade blocking rule: same as waivers (unintegrated IR player)
- [x] Trades blocked after mid-season

### Infirmary rules

- [x] IR slot capacity: 3 players max
- [x] Auto-notification on recovery / suspension end
- [x] 1-week reintegration deadline before waiver/trade blocking activates
- [x] Alert on dashboard: "Player X recovered — reintegrate within X days"

### Tests

- [x] Fantasy points calculation: captain multiplier, kicker-only stats, COALESCE
- [x] Edge case: double match in same round
- [x] Waiver priority ordering
- [x] Waiver block: IR player not reintegrated
- [x] Trade window enforcement (mid-season cutoff)

---

### Deferred integration tests (Phase 4)

- [ ] Atomic commit: simulate pipeline failure mid-run, verify production data unchanged
- [ ] IR endpoints: integration tests with mocked AsyncClient (KB-007)
- [ ] Waiver apply: atomic write test (KB-004)
- [ ] Trade apply: atomic write test (KB-006)

---

## Phase 4 — Frontend MVP

**Estimated duration:** 3–4 weeks
**Prerequisite:** Phase 3 complete.

- [x] Draft Room — full-screen mobile-first, real-time timer, player list, pick confirmation
  - [x] `src/types/draft.ts` — TypeScript mirror of FastAPI schemas
  - [x] `src/types/player.ts` — TypeScript mirror of PlayerSummary
  - [x] `src/hooks/useDraftRealtime.ts` — Supabase Realtime + polling fallback + connect/disconnect
  - [x] `src/components/draft/DraftTimer.tsx` — countdown with urgency colours + Framer Motion
  - [x] `src/components/draft/DraftStatusBanner.tsx` — contextual status (your turn / waiting / autodraft / done)
  - [x] `src/components/draft/DraftPlayerCard.tsx` — player card, available/drafted/injured states
  - [x] `src/components/draft/DraftPlayerList.tsx` — filterable scrollable pool (search + position chips)
  - [x] `src/components/draft/DraftOrderPanel.tsx` — snake order + pick history
  - [x] `src/components/draft/DraftPickConfirmModal.tsx` — confirmation modal, focus trap, keyboard
  - [x] `src/components/draft/DraftRoom.tsx` — main orchestrator, mobile-first layout
  - [x] `src/app/[locale]/(protected)/draft/[draftId]/page.tsx` — Server Component, parallel data fetch
  - [x] `backend/app/routers/draft.py` — added `POST /{league_id}/pick` endpoint
  - [x] `backend/app/routers/players.py` — new `GET /players` endpoint
  - [x] `messages/fr.json` — all draft i18n keys added
  - [x] framer-motion installed
- [x] Roster management page — starters / bench / IR, weekly lineup, captain + kicker designation
  - [x] `src/types/roster.ts` — TypeScript types (RosterSlot, WeeklyLineupEntry, LineupUpdatePayload, etc.)
  - [x] `src/hooks/useRosters.ts` — fetch + mutations + coverage computation + lock polling
  - [x] `src/components/roster/RosterPlayerCard.tsx` — player card, lock/captain/kicker/IR states
  - [x] `src/components/roster/RosterSlotGrid.tsx` — 15 starter slots, jersey order, position groups
  - [x] `src/components/roster/RosterBenchGrid.tsx` — bench slots + coverage bar (CDC §6.2)
  - [x] `src/components/roster/RosterIRPanel.tsx` — IR slots, reintegration button, blocking alert
  - [x] `src/components/roster/RosterCaptainKickerBar.tsx` — captain/kicker designation, player picker
  - [x] `src/components/roster/RosterManagement.tsx` — orchestrator, swap flow, mobile tabs
  - [x] `src/app/[locale]/(protected)/league/[leagueId]/roster/page.tsx` — Server Component, current round fetch
  - [x] `messages/fr.json` — all roster i18n keys added
  - [x] `src/components/layout/Sidebar.tsx` — fixed hydration mismatch (localStorage + Turbopack)
- [x] Leaderboard — live updates via Supabase Realtime
  - [x] `src/types/leaderboard.ts` — TypeScript mirror of LeagueStandingsResponse
  - [x] `src/hooks/useLeaderboard.ts` — fetch + Supabase Realtime Postgres Changes + polling fallback
  - [x] `src/components/leaderboard/LeaderboardRow.tsx` — row atom, medal icons, current user highlight
  - [x] `src/components/leaderboard/LeaderboardTable.tsx` — full table, loading/error/empty states
  - [x] `src/app/[locale]/(protected)/league/[leagueId]/leaderboard/page.tsx` — Server Component, SSR fetch
  - [x] `backend/app/routers/leagues.py` — GET /leagues/{league_id}/standings
  - [x] `messages/fr.json` — all leaderboard i18n keys added
- [x] Stats page — all filters (status, nationality/club, position, period, multi-criteria)
  - [x] `dbt_project/models/gold/mart_player_stats_ui.sql` — gold model updated: all D-039 stats,
        total_points + avg_points, 4 periods (1w/2w/4w/season), trend computation
  - [x] `backend/app/routers/stats.py` — GET /stats/players (competition_id + period + league_id)
        pool_status enrichment (mine/drafted/free), PlayerStatsRow + PlayerStatsResponse
  - [x] `backend/app/main.py` — stats_router registered
  - [x] `src/types/stats.ts` — PlayerStatsRow, PlayerStatsResponse, StatsFilters,
        StatsPeriod, PoolStatus, StatsTrend, StatsColumnGroup
  - [x] `src/hooks/usePlayerStats.ts` — fetch + mock data + client-side filtering (D-044, D-045)
  - [x] `src/components/stats/StatsFiltersBar.tsx` — period tabs, search, position chips,
        pool status chips, club/nationality select, clear all
  - [x] `src/components/stats/StatsTable.tsx` — 4 column groups (points/attack/defence/discipline),
        sortable headers, sticky identity column, trend icons, Framer Motion rows
  - [x] `src/components/stats/StatsPageClient.tsx` — Client Component shell
  - [x] `src/app/[locale]/(protected)/stats/page.tsx` — Server Component page
  - [x] `messages/fr.json` — all stats i18n keys added
  - [ ] TODO: set USE_MOCK = false in usePlayerStats.ts once DSG pipeline populates DB
  - [ ] TODO: resolve competition_id from user's active league in stats/page.tsx (currently hardcoded mock UUID)
  - [ ] TODO: add prev_season period to mart_player_stats_ui (deferred — see D-044)
- [x] Dashboard page — multi-league hub, empty state, single-league auto-redirect (D-047)
  - [x] `backend/app/routers/dashboard.py` — GET /dashboard (BFF aggregator)
  - [x] `frontend/src/types/dashboard.ts` — TypeScript mirror
  - [x] `frontend/src/components/dashboard/DashboardEmptyState.tsx`
  - [x] `frontend/src/components/dashboard/DashboardAlertBadge.tsx`
  - [x] `frontend/src/components/dashboard/DashboardLeagueCard.tsx`
  - [x] `frontend/src/app/[locale]/(protected)/dashboard/page.tsx`
  - [x] `messages/fr.json` — all dashboard i18n keys added
  - [x] `backend/.env` — SUPABASE_ANON_KEY populated (was placeholder)
  - [x] TODO: league card → tested with real league data (seed 002_test_league.sql)
  - [ ] TODO: next_opponent field (deferred — requires schedule query)
- [x] Swagger UI — Bearer auth scheme (`custom_openapi` in `main.py`, public paths excluded)
- [ ] Season archive page — past results per league
- [ ] Deploy to Hetzner via Coolify: `rugbydraft.app` live with HTTPS
- [ ] Full axe-core accessibility audit — WCAG 2.1 AA
- [ ] Core Web Vitals: FCP < 1s, total load < 2s
- [ ] Lighthouse ≥ 90

---

## Phase 5 — Premium (private repo)

**Estimated duration:** 2–3 weeks
**Prerequisite:** Phase 4 complete.

- [ ] Stripe integration: monthly (3 €) + annual (25 €) plans
- [ ] Free trial: 4 weeks on Pro plan at signup
- [ ] Plan middleware: FastAPI checks `users.plan` on every Pro/Pro+IA route
- [ ] Webhooks: `invoice.paid`, `customer.subscription.deleted`, `customer.subscription.updated`
- [ ] Stripe customer portal: cancel, receipts, switch monthly/annual
- [ ] Staff IA: CrewAI 5-agent setup (physical trainer, video analyst, recruiter, journalist, assistant coach)
- [ ] Tuesday DAG: context preparation → CrewAI run → store in `ai_reports` → in-app + email notification
- [ ] Thursday DAG: same with real lineup data
- [ ] Retry on Claude API failure: 3 attempts × 15 min spacing → "delayed report" notification
- [ ] Report rendered in user's locale (locale parameter passed to CrewAI)

---

## Phase 6 — Top 14 & Polish

**Estimated duration:** 2 weeks
**Prerequisite:** Phase 5 complete.

- [ ] Top 14 connector (verify coverage with confirmed data provider first)
- [ ] Pro plan gate on Top 14 leagues
- [ ] Season archiving: `league_archives` table populated at end of competition
- [ ] Full accessibility audit (axe-core + manual review)
- [ ] Performance audit (Core Web Vitals, Lighthouse)
- [ ] Closed beta: invite Ulule backers (Commissaires Fondateurs first, then all backers)
- [ ] Collect feedback, fix critical bugs

---

## Future phases

### Phase 7 — EN (V2)

- Translate `messages/en.json`
- EN community outreach (Reddit rugby, Twitter)
- Premiership + Super Rugby Pacific connectors

### Phase 8 — ES/IT (V3)

- `messages/es.json` + `messages/it.json`
- Super Rugby Americas connector
- Italian Top 12 connector

---

## Ulule campaign timing

Launch Ulule **after Phase 2** (draft engine working). Rationale: the snake draft in real-time is the core differentiator — a 60-second demo video of two browser windows drafting simultaneously is the most compelling pitch possible, even from localhost.

See `docs/ulule_campaign.md` for the full campaign draft.

---

## Immediate next actions

**→ Phase 4 in progress:** Draft Room ✅ Roster ✅ Leaderboard ✅ Stats page ✅ Dashboard ✅ Swagger UI ✅ feat/scoring-d050 ✅ — next: Phase 4 PR

**→ Next session (priority 1):** open Phase 4 PR — merge `phase/4-frontend` into `main`.

**→ Phase 1 remaining:** Cron Coolify config (after first deploy to Hetzner)

**→ Phase 4 deferred:** all integration tests (KB-004, KB-006, KB-007)

**→ Phase 4 deferred:** USE_MOCK = false in usePlayerStats + real competition_id in
stats page (after first DSG pipeline run)

**→ TODO (Phase 4 follow-up):** expose `draft_order` in `DraftStateSnapshotResponse`
so `DraftOrderPanel` can show the full upcoming snake order (not just current slot).

**→ TODO (future):** add `prev_season` period to `mart_player_stats_ui` — requires
`previous_competition_id` on the `competitions` table.

**→ TODO (V2):** evaluate `defenders_beaten`, `drop_goals_converted`,
`drop_goal_missed` for scoring inclusion (DSG fields confirmed present — deferred
pending game-design validation, see D-050).

**→ Business:** DSG billing is annual upfront (1 500 € / 12 months).
Launch Ulule campaign to validate project before signing. Break-even ~100 paying
subscribers (see D-037).
