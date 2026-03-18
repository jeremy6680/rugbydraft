# DECISIONS.md — RugbyDraft

> Architectural and technical decisions log.
> Format: context → options considered → decision → rationale → consequences.
> Last updated: 2026-03-16

---

## D-001 — FastAPI as draft authority of state

**Date:** 2026-03-16
**Status:** Accepted

**Context:** The snake draft requires a shared, authoritative state (current pick number, timer, picks made) accessible in real time by all connected clients. Two approaches were considered.

**Options considered:**
- A) Supabase Realtime as source of truth — clients write directly to the DB, Realtime broadcasts changes.
- B) FastAPI manages state in memory, Supabase Realtime broadcasts updates from FastAPI.

**Decision:** Option B — FastAPI is the authority of state. Supabase Realtime is a broadcast channel only.

**Rationale:**
- Prevents race conditions: two clients picking simultaneously would be inconsistent if the DB is the authority.
- The timer lives server-side (FastAPI) — it cannot be trusted to a client.
- Reconnection protocol is clean: client reconnects → FastAPI sends full current state snapshot.
- Supabase Realtime is used for what it's good at (low-latency broadcast), not as a transaction manager.

**Consequences:**
- FastAPI must maintain draft state in memory (or in a fast store like Redis if scaling requires it).
- All pick validations happen in FastAPI before any DB write.
- If FastAPI restarts mid-draft, state is lost — document recovery procedure in Phase 2.

---

## D-002 — Orchestration: Airflow only for post_match_pipeline

**Date:** 2026-03-16
**Status:** Accepted

**Context:** The project requires several scheduled tasks: fetching fixtures daily, processing post-match stats on weekends, checking player availability daily, and running AI staff reports twice a week.

**Options considered:**
- A) Airflow for all tasks.
- B) APScheduler/Cron for all tasks.
- C) Airflow for the complex DAG only, Cron/APScheduler for simple tasks.

**Decision:** Option C.

| Task | Scheduler | Rationale |
|---|---|---|
| `post_match_pipeline` | Airflow | Complex dependencies, retry logic, monitoring needed — portfolio value |
| `daily_fixtures` | Cron Coolify | Single HTTP call + dbt run, no inter-task dependencies |
| `daily_availability` | Cron Coolify | Same — simple fetch + update |
| `staff_ai_tuesday/thursday` | Airflow | Complex (CrewAI multi-agent), retry needed, private repo |

**Rationale:**
- Airflow on ~600 MB RAM on a CPX21 is manageable but non-trivial. Running it for trivial cron jobs wastes resources and increases the attack surface.
- `post_match_pipeline` is genuinely complex: detect → ingest → bronze → dbt silver → dbt gold → staging → atomic commit → notify. Dependencies between tasks are critical.
- Portfolio signal: Airflow on a real, justified use case is more impressive than Airflow for everything.

**Consequences:**
- Two orchestration systems to maintain. Acceptable given the clear separation.
- If Coolify cron fails silently, there's no Airflow alerting for those tasks — add a simple health check endpoint.

---

## D-003 — Staging → atomic commit for fantasy_scores

**Date:** 2026-03-16
**Status:** Accepted

**Context:** The `post_match_pipeline` runs every 30 minutes on weekends. If it fails mid-way (e.g., after writing some scores but before completing all), users would see partial or inconsistent leaderboards.

**Decision:** Fantasy scores are written to `fantasy_scores_staging` first (same schema as `fantasy_scores`). A single PostgreSQL transaction copies staging → production once the full pipeline succeeds.

**Rationale:**
- PostgreSQL transaction rollback is automatic on failure — no manual cleanup.
- Users see either the full updated leaderboard or the previous one. Never a partial state.
- A "scores being processed" indicator is shown while the pipeline runs.

**Consequences:**
- Adds one table (`fantasy_scores_staging`) to the schema.
- The atomic commit step must be the last task in the Airflow DAG.
- Staging table should be truncated at the start of each pipeline run.

---

## D-004 — API-Sports Standard from day one (no free tier in production)

**Date:** 2026-03-16
**Status:** Accepted

**Context:** API-Sports offers a free tier (100 requests/day) and a Standard tier (~12 €/month). A typical weekend of Six Nations matches requires several hundred requests for full stats.

**Decision:** API-Sports Standard is used from day one of the beta. The free tier is never used in real conditions.

**Rationale:**
- 100 req/day is insufficient for a weekend (multiple matches, polling every 30 minutes).
- Building the pipeline against the free tier would require reworking rate limiting assumptions later.
- 12 €/month is a fixed, predictable cost that fits within the break-even model.

**Consequences:**
- 12 €/month cost from the first day of beta (~10 weeks × 12 € = ~120 € pre-revenue).
- This cost should be included explicitly in the Ulule campaign budget.

---

## D-005 — API validation as Phase 0 (blocking)

**Date:** 2026-03-16
**Status:** Accepted

**Context:** The scoring system relies on specific stats (tackles, turnovers, metres, try assists, 50/22, dominant tackles). These stats must be available via the chosen API. If they are not, the scoring system must be revised before any code is written.

**Decision:** Phase 0 (3–5 days) is a manual validation of API-Sports Standard on the current Six Nations. It is blocking for all subsequent phases.

**Validation checklist:**
- [ ] Tackles per player per match
- [ ] Turnovers won per player per match
- [ ] Metres carried per player per match
- [ ] Try assists per player per match
- [ ] 50/22 kicks (conditional — note if missing)
- [ ] Dominant tackles (conditional — note if missing)
- [ ] Lineout steals (conditional — note if missing)
- [ ] Yellow/red cards
- [ ] Penalties conceded per player
- [ ] Conversions and penalties (kicker stats)
- [ ] Match status (live / finished) polling reliability

**Decision rule:** if tackles, turnovers, metres, or try assists are systematically missing → revise scoring system before Phase 1. Conditional stats (50/22, dominant tackle, lineout steal) can be dropped without blocking.

---

## D-006 — next-intl from Phase 1, FR only in V1

**Date:** 2026-03-16
**Status:** Accepted

**Context:** The app will support FR (V1), EN (V2), ES and IT (V3). Retrofitting i18n onto an existing codebase is a major refactoring effort.

**Decision:** next-intl is installed and configured in Phase 1. All UI strings go through `t('key')` from day one. Only `messages/fr.json` is populated in V1.

**Rules:**
- Zero hardcoded UI strings in components — enforced in PR review.
- URLs have no language prefix (`/leagues`, not `/fr/leagues`). Locale is stored on `users.locale`.
- Competition names, player names, club names are NOT translated (kept as-is).
- Position names ARE translated (Hooker → Talonneur → Tallonatore).
- AI staff reports are generated in the user's locale (locale parameter passed to CrewAI).

**Rationale:**
- ~20% additional work in Phase 1 avoids a full refactoring before V2.
- next-intl is the standard for Next.js 15 App Router — no exotic dependency.

---

## D-007 — Language and competition access are independent dimensions

**Date:** 2026-03-16
**Status:** Accepted

**Context:** Early CDC versions incorrectly linked language (locale) to competition access (e.g., "Premiership accessible in EN version only").

**Decision:** Locale = display preference only. Competition access = determined by plan (Free/Pro), never by locale.

**Example:** A user with `locale=es` on a Free plan can play Six Nations, Rugby Championship, Nations Championship. The same user on a Pro plan can also play Top 14, Premiership, Super Rugby — regardless of their locale setting.

---

## D-008 — Supabase cloud over self-hosted in V1

**Date:** 2026-03-16
**Status:** Accepted

**Context:** Supabase can be self-hosted on the Hetzner VPS or used as a managed cloud service.

**Decision:** Supabase cloud (free tier) in V1. Self-hosted if cloud limits are reached.

**Rationale:**
- Self-hosting Supabase adds ~500 MB RAM and significant operational complexity (Docker stack, updates, backups).
- Supabase cloud free tier supports ~500 active users — sufficient for beta and early launch.
- Auth and Realtime are managed services on cloud — no ops burden.
- Migration path to self-hosted is documented and reversible.

---

## D-009 — Free tier limited to international competitions

**Date:** 2026-03-16
**Status:** Accepted

**Context:** Earlier versions had fully unlimited Free (all competitions and features), with Pro reserved only for AI staff.

**Decision:** International competitions (Six Nations, Rugby Championship, Nations Championship) are Free. Club competitions (Top 14, Premiership, Super Rugby, Champions Cup) are Pro only. AI Staff is Pro+IA only.

**Rationale:**
- Pure "everything free except IA" gave no incentive to upgrade for users who don't want AI coaching.
- International competitions are genuinely compelling on their own — Free users have real value.
- Club competitions (Top 14 especially for the French market) are the natural conversion lever for engaged users.
- Pro commissioner limit: unlimited (previously 3 — removed, as more leagues = more Free users in the funnel).

---

## D-010 — Ghost team waiver pool interaction

**Date:** 2026-03-16
**Status:** Accepted

**Context:** Section 11 specifies that injured players from ghost teams are automatically released to the waiver pool after 7 days. Section 9.1 specifies that a manager with an unintegrated recovered player is blocked from waivers.

**Decision:** Ghost team player releases are processed outside the normal waiver window and priority system. They do not trigger the infirmary blocking rule for other managers.

**Rationale:**
- Ghost team releases are automatic maintenance events, not competitive actions.
- They should not create unfair timing advantages or block legitimate manager actions.

---

## D-011 — Commissioner limit: Free = 1 active league, Pro/Pro+IA = unlimited

**Date:** 2026-03-16
**Status:** Accepted

**Context:** Earlier v3.0 had Pro limited to 3 commissioner leagues.

**Decision:** Pro and Pro+IA have unlimited commissioner leagues. Free is limited to 1 active league as commissioner. "Active" = not archived (completed seasons do not count toward the quota).

**Rationale:**
- A Pro commissioner creating many leagues brings more Free users into the funnel — good for growth.
- The 3-league limit was arbitrary and created friction without a clear business justification.
- The real conversion lever for Pro is competition access (Top 14, etc.), not the number of leagues.
