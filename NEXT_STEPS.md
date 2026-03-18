# NEXT_STEPS.md — RugbyDraft

> Current status: Pre-development — CDC v3.1 validated.
> Last updated: 2026-03-16

---

## 🔴 Phase 0 — API Validation (BLOCKING — do this first)

**Estimated duration:** 3–5 days
**Objective:** Validate that API-Sports Standard provides the stats required by the scoring system before writing a single line of application code.

### Steps

- [ ] Subscribe to API-Sports Standard (~12 €/month)
- [ ] Make manual requests on the current Six Nations:
  - `GET /rugby/fixtures?league=...&season=2026` — verify match list and statuses
  - `GET /rugby/fixtures/statistics?fixture=...` — verify available stat fields
- [ ] Complete the validation checklist (DECISIONS.md D-005):
  - [ ] Tackles per player
  - [ ] Turnovers won per player
  - [ ] Metres carried per player
  - [ ] Try assists per player
  - [ ] Conversions / penalties (kicker stats)
  - [ ] Yellow / red cards
  - [ ] Penalties conceded per player
  - [ ] Match status polling (live / finished) — test on a live match
  - [ ] Conditional: 50/22, dominant tackle, lineout steal
- [ ] Document findings in `docs/api_validation.md`
- [ ] **Decision:** if blocking stats missing → revise scoring system. If only conditional stats missing → note in DECISIONS.md and proceed.

---

## 🔴 Phase 1 — Foundations

**Estimated duration:** 2–3 weeks
**Objective:** Project skeleton, database schema, data pipeline up to silver layer, CI/CD, i18n structure.

### Repositories & structure

- [ ] Create public repo `jeremy6680/rugbydraft`
- [ ] Create private repo `jeremy6680/rugbydraft-private`
- [ ] Set up folder structure (see `STRUCTURE.md` once created)
- [ ] Add `.gitignore` — include `docs/cdc*.md`, `docs/cdc*.docx`, `.env*`
- [ ] Copy `CONTEXT.md`, `DECISIONS.md`, `NEXT_STEPS.md` to repo root
- [ ] Create `STRUCTURE.md`
- [ ] Create `.env.example` with all required variables documented

### Database (Supabase)

- [ ] Create Supabase project
- [ ] Write full PostgreSQL schema (all tables from CDC section 18)
- [ ] Enable Row Level Security on all tables
- [ ] Create initial migrations (Supabase migrations or plain SQL files in `db/migrations/`)
- [ ] Test RLS policies: a user can only access their own league data

### Data pipeline — Bronze/Silver

- [ ] Implement `connectors/base.py` — `BaseRugbyConnector` ABC
- [ ] Implement `connectors/api_sports.py` — API-Sports Standard
- [ ] Set `RUGBY_DATA_SOURCE=api_sports` in `.env.example`
- [ ] dbt project init (`dbt init rugbydraft`)
- [ ] Bronze models: `raw_matches`, `raw_player_stats`, `raw_fixtures`, `raw_player_availability`
- [ ] Silver models: `stg_players`, `stg_matches`, `stg_match_stats`, `stg_fixtures`, `stg_player_availability`
- [ ] dbt tests on silver models (not_null, unique on key fields)
- [ ] Cron Coolify: `daily_fixtures` (06:00) and `daily_availability` (08:00)

### Backend skeleton

- [ ] FastAPI project init
- [ ] Supabase Auth integration (JWT verification middleware)
- [ ] Basic health endpoint `GET /health`
- [ ] Pydantic models for core entities (Player, League, User)
- [ ] Rate limiting with slowapi (100 req/min per IP)

### Frontend skeleton

- [ ] `npx create-next-app@latest` with App Router + TypeScript + Tailwind v4
- [ ] Install and configure next-intl
- [ ] Create `messages/fr.json` with initial keys
- [ ] Supabase Auth UI integration (Google OAuth + magic link)
- [ ] Basic layout: bottom nav bar (mobile), sidebar (desktop)
- [ ] shadcn/ui install + theme configuration (green #1A5C38)

### CI/CD

- [ ] GitHub Actions: ruff + pytest on push
- [ ] GitHub Actions: axe-core on PRs (basic pages)
- [ ] GitHub Actions: TypeScript lint

---

## Phase 2 — Draft Engine

**Estimated duration:** 3–4 weeks
**Prerequisite:** Phase 1 complete, PostgreSQL schema live.

### Core draft logic

- [ ] Snake draft order algorithm (N managers, 2N picks per cycle)
- [ ] Server-side timer (FastAPI manages countdown, not clients)
- [ ] Pick validation: correct manager, correct turn, player available
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
**Prerequisite:** Phase 2 complete.

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

- [ ] Top 14 connector (API-Sports Standard — verify coverage first)
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

## Immediate next action

**→ Validate API-Sports Standard on the current Six Nations (Phase 0).**

Everything else depends on this. Do not set up repos, write schema, or install anything until the scoring system is confirmed feasible with the available data.
