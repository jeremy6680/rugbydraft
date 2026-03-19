# NEXT_STEPS.md — RugbyDraft

> Current status: Phase 1 complete. Phase 2 ready to start.
> Last updated: 2026-03-19

---

## 🟡 Phase 0 — API Validation (in progress)

**Status:** API-Sports tested and ruled out. Alternative providers under evaluation.

### Completed

- [x] Created free API-Sports account and obtained API key
- [x] Built validation script (`scripts/validate_api.py`)
- [x] Tested API-Sports Rugby on Six Nations 2024 season
- [x] **Finding: API-Sports provides scores only — no player-level stats endpoint exists**
- [x] Investigated alternative providers (Sportradar, DSG, Statscore, stats.sixnationsrugby.com)
- [x] Contacted Data Sports Group (DSG) — 2026-03-18
- [x] Contacted Statscore — 2026-03-18, received initial reply, sent detailed requirements

### Pending — provider selection

- [ ] Await DSG response with pricing and data sample
- [ ] Await Statscore response confirming player-level stat availability
- [ ] If budget is confirmed feasible: request sandbox/trial access and run validation script against new provider
- [ ] If all providers exceed budget: evaluate Sportradar 30-day free trial + simplified scoring system as fallback
- [ ] Document final provider decision in `DECISIONS.md` D-012
- [ ] Update cost estimates in CDC if provider cost differs from original ~12 €/month assumption

### Decision rule (unchanged)

If blocking stats (tackles, turnovers, metres, try assists) are confirmed available → proceed to Phase 3 with full scoring system.
If no affordable provider found → implement simplified scoring (tries, kicker stats, cards) on API-Sports and document the tradeoff in DECISIONS.md.

**Phase 0 does NOT block Phase 1.** Repos, schema, CI/CD, frontend skeleton, and draft engine are all independent of the data source choice.

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

## 🔴 Phase 2 — Draft Engine (next)

**Estimated duration:** 3–4 weeks
**Prerequisite:** Phase 1 complete ✅, PostgreSQL schema live ✅.

### Core draft logic

- [x] Snake draft order algorithm (N managers, 2N picks per cycle)
- [x] Server-side timer (FastAPI manages countdown, not clients)
- [x] Pick validation: correct manager, correct turn, player available
- [ ] Autodraft algorithm: pick from preference list, or by default value score
- [ ] Timeout → auto-activate autodraft for remaining picks
- [ ] "Manager never connected" → full autodraft from draft start

### Realtime (Supabase Realtime as broadcast)

- [ ] FastAPI broadcasts state updates to Supabase Realtime channel
- [ ] Client subscribes to channel, renders state received from server
- [ ] Never write draft state directly from client to DB

### Reconnection protocol (see DECISIONS.md D-001)

- [ ] On reconnect: FastAPI sends full state snapshot (picks made, current pick, time remaining)
- [ ] If manager reconnects during their turn with time remaining: they can pick
- [ ] If timer expired during disconnection: autodraft pick is final
- [ ] Document recovery procedure for FastAPI restart mid-draft

### Draft Assistée (fallback mode)

- [ ] Commissioner UI: "Switch to Assisted Draft" button
- [ ] Commissioner enters picks one by one, no timer
- [ ] Audit log: each pick stamped with timestamp + "entered by commissioner"
- [ ] Log visible to all managers

### Ghost team

- [ ] Ghost team creation when manager count is odd or below competition minimum
- [ ] Random name generator
- [ ] Autodraft with default value algorithm
- [ ] Ghost team excluded from waivers and trades

### Tests (mandatory — PRs blocked if failing)

- [ ] Snake order for 2, 3, 4, 5, 6 managers
- [ ] Timer timeout → autodraft activation
- [ ] Client reconnection during pick
- [ ] Client reconnection after pick (timer expired)
- [ ] Draft Assistée: picks logged correctly
- [ ] Roster constraint validation (coverage minimums)

---

## Phase 3 — Gameplay

**Estimated duration:** 2–3 weeks
**Prerequisite:** Phase 2 complete + data provider confirmed (D-012).

### Data pipeline — Gold

- [ ] `mart_fantasy_points`: scoring logic per player per round
  - Captain ×1.5 (rounded up to nearest 0.5)
  - Kicker stats only for designated kicker
  - `COALESCE(stat, 0)` for all conditional stats
- [ ] `mart_roster_scores`: aggregate points per roster per round
- [ ] `mart_leaderboard`: standings per league
- [ ] `mart_player_pool`: available players per league
- [ ] `mart_player_value`: default value score for autodraft

### Airflow — post_match_pipeline

- [ ] DAG: detect → ingest → bronze → dbt silver → dbt gold → write to `fantasy_scores_staging` → atomic commit → notify
- [ ] Atomic commit: single PostgreSQL transaction `fantasy_scores_staging` → `fantasy_scores`
- [ ] "Scores being processed" indicator while pipeline runs
- [ ] Retry: 3 attempts with exponential backoff on API failure

### Weekly lineup management

- [ ] Starter/bench/IR slot management API
- [ ] Progressive lock: per-match, not per-round (locked at kick-off of player's team match)
- [ ] Lock validation: cannot change captain/kicker after their team's kick-off
- [ ] Multi-position player: position choice locked at kick-off

### Edge cases (from CDC section 6.6)

- [ ] Player plays two matches in same round → only first match counts
- [ ] Captain change between two matches in same round → allowed until captain's team kick-off
- [ ] Kicker change after first match → blocked until next round

### Waivers

- [ ] Waiver window: Tuesday morning → Wednesday evening
- [ ] Priority: lowest-ranked manager first
- [ ] Priority reset after each cycle
- [ ] Blocking rule: manager with unintegrated recovered IR player cannot claim waivers

### Trades

- [ ] Trade window: start of competition → mid-season (`ceil(total_rounds / 2)`)
- [ ] Formats: 1v1, 1v2, 1v3
- [ ] Commissioner veto: 24h window, must provide reason (text field), log visible to all
- [ ] Trade blocking rule: same as waivers (unintegrated IR player)
- [ ] Trades blocked after mid-season

### Infirmary rules

- [ ] IR slot capacity: 3 players max
- [ ] Auto-notification on recovery / suspension end
- [ ] 1-week reintegration deadline before waiver/trade blocking activates
- [ ] Alert on dashboard: "Player X recovered — reintegrate within X days"

### Tests

- [ ] Fantasy points calculation: captain multiplier, kicker-only stats, COALESCE
- [ ] Edge case: double match in same round
- [ ] Waiver priority ordering
- [ ] Waiver block: IR player not reintegrated
- [ ] Trade window enforcement (mid-season cutoff)
- [ ] Atomic commit: simulate pipeline failure mid-run, verify production data unchanged

---

## Phase 4 — Frontend MVP

**Estimated duration:** 3–4 weeks
**Prerequisite:** Phase 3 complete.

- [ ] Draft Room — full-screen mobile-first, real-time timer, player list, pick confirmation
- [ ] Roster management page — starters / bench / IR, weekly lineup, captain + kicker designation
- [ ] Leaderboard — live updates via Supabase Realtime
- [ ] Stats page — all filters (status, nationality/club, position, period, multi-criteria)
- [ ] Dashboard — all active leagues, alerts, next opponent
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

**→ Phase 0 (parallel):** await responses from Statscore and DSG.
**→ Phase 2:** snake draft order algorithm — first step is the pure Python function, tested in isolation before any FastAPI integration.
**→ Phase 1 — remaining:** Cron Coolify config (after first deploy to Hetzner).
