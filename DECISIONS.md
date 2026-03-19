# DECISIONS.md — RugbyDraft

> Architectural and technical decisions log.
> Format: context → options considered → decision → rationale → consequences.
> Last updated: 2026-03-18

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

| Task                        | Scheduler    | Rationale                                                              |
| --------------------------- | ------------ | ---------------------------------------------------------------------- |
| `post_match_pipeline`       | Airflow      | Complex dependencies, retry logic, monitoring needed — portfolio value |
| `daily_fixtures`            | Cron Coolify | Single HTTP call + dbt run, no inter-task dependencies                 |
| `daily_availability`        | Cron Coolify | Same — simple fetch + update                                           |
| `staff_ai_tuesday/thursday` | Airflow      | Complex (CrewAI multi-agent), retry needed, private repo               |

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

## D-004 — API-Sports ruled out as data source (Phase 0 finding)

**Date:** 2026-03-18
**Status:** Accepted (replaces original D-004)

**Context:** API-Sports Rugby was the planned primary data source (originally estimated at ~12 €/month). Phase 0 testing revealed it does not provide player-level match statistics.

**Finding:** API-Sports Rugby only returns match scores, team results, and standings. The `/games/statistics` endpoint does not exist. There are no player-level stats (tackles, metres, turnovers, try assists) available at any price tier. This is a structural limitation of the product, not a plan restriction.

**Additional findings:**

- The paid PRO plan costs 15 $/month (not 12 € as estimated in CDC v3.1) — minor impact.
- The free plan is limited to seasons 2022–2024 (cannot access current season data).
- League ID for Six Nations is 51 (not 39 as assumed).

**Decision:** API-Sports Rugby is abandoned as the primary data source. The connector abstraction (`BaseRugbyConnector`) remains the correct architecture — the implementation will target a different provider (TBD, see D-012).

**Consequences:**

- CDC v3.1 cost estimates for the data source need revision once a provider is confirmed.
- `connectors/api_sports.py` will still be implemented in Phase 1 as a fixtures/availability source (match schedule, scores), but cannot be used for fantasy scoring.

---

## D-005 — API validation as Phase 0 (blocking)

**Date:** 2026-03-16
**Status:** Partially complete — provider search in progress

**Context:** The scoring system relies on specific stats (tackles, turnovers, metres, try assists, 50/22, dominant tackles). These stats must be available via the chosen API before any application code is written.

**Validation checklist — API-Sports (tested 2026-03-18):**

- [x] Match status (live / finished) — ✅ available via `/games`
- [ ] Tackles per player per match — ❌ endpoint does not exist
- [ ] Turnovers won per player per match — ❌ endpoint does not exist
- [ ] Metres carried per player per match — ❌ endpoint does not exist
- [ ] Try assists per player per match — ❌ endpoint does not exist
- [ ] Conversions / penalties (kicker stats) — ❌ endpoint does not exist
- [ ] Yellow/red cards per player — ❌ endpoint does not exist
- [ ] Penalties conceded per player — ❌ endpoint does not exist
- [ ] Conditional: 50/22, dominant tackle, lineout steal — ❌ endpoint does not exist

**Result: API-Sports FAILED validation.** Player-level stats are structurally absent.

**Providers currently under evaluation:**

- Statscore — contacted 2026-03-18, awaiting response with data depth details
- Data Sports Group (DSG) — contacted 2026-03-18, awaiting pricing and sandbox access
- Sportradar Rugby — trial available (30 days free), player stats confirmed in documentation

**Decision rule (unchanged):** if blocking stats missing from chosen provider → revise scoring system before Phase 1. Phase 1 foundations (repos, schema, CI/CD, frontend skeleton) can proceed in parallel while provider is being confirmed.

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

---

## D-012 — Data source strategy: connector-agnostic architecture, provider TBD

**Date:** 2026-03-18
**Status:** Accepted — provider selection pending

**Context:** API-Sports Rugby failed Phase 0 validation (no player-level stats). A new provider must be selected before Phase 3 (gameplay/scoring pipeline). Phase 1 and Phase 2 can proceed without a confirmed provider.

**Options under evaluation:**

| Provider                  | Player stats         | Price             | Status                  |
| ------------------------- | -------------------- | ----------------- | ----------------------- |
| API-Sports Rugby          | ❌ None              | 15 $/month        | ❌ Ruled out            |
| Sportradar Rugby          | ✅ Confirmed in docs | ~500-1000 $/month | 🟡 Trial available      |
| Data Sports Group (DSG)   | ✅ Claimed           | Unknown           | 🟡 Contacted 2026-03-18 |
| Statscore                 | ✅ Claimed           | Unknown           | 🟡 Contacted 2026-03-18 |
| stats.sixnationsrugby.com | ✅ Confirmed         | Unknown           | ❌ 401 — partners only  |

**Decision:** Proceed with Phase 1 immediately. The `BaseRugbyConnector` abstraction means the provider choice does not affect the pipeline architecture, dbt models, or FastAPI. The connector implementation is the only thing that changes.

**Provider selection criteria:**

1. Player-level stats confirmed: tackles, metres, turnovers, try assists, kicker stats per match
2. Coverage: Six Nations + Top 14 minimum
3. Price: ideally < 50 €/month at launch, negotiable as user base grows
4. Data sample or sandbox available before commitment

**Decision deadline:** Before starting Phase 3 (gameplay pipeline). Phases 1 and 2 are unaffected.

**Consequences:**

- Phase 1 connector implementation will build `BaseRugbyConnector` + a mock/stub implementation for testing.
- `connectors/api_sports.py` may still be implemented for fixture fetching (schedule, match status) if the chosen provider doesn't cover this use case cheaply.
- CDC v3.1 cost estimates will need revision once a provider is confirmed.

---

## D-013 — `number_8` as distinct position type from `flanker`

**Date:** 2026-03-18
**Status:** Accepted

**Context:** The CDC defines "3 third-row forwards" without distinguishing number 8 from flankers. In rugby, the number 8 is structurally distinct from flankers in terms of physical profile and, in some scoring systems, role-specific stats.

**Decision:** `position_type` enum separates `number_8` from `flanker`. This gives full positional granularity from day one.

**Rationale:**

- Roster constraint validation is more precise (can enforce "at least 1 number 8 on bench" if needed in V2).
- No cost: the extra enum value has zero impact on application logic.
- Reversible: merging back into a generic `back_row` type is a simple migration if needed.

**Consequences:**

- Player data must assign positions correctly: flankers get `flanker`, the number 8 gets `number_8`.
- The mock connector must respect this distinction in fixture data.

---

## D-014 — Circular FK between `users` and `leagues` resolved via ALTER TABLE

**Date:** 2026-03-18
**Status:** Accepted

**Context:** `users.ai_league_id` references `leagues`, but `leagues.commissioner_id` references `users`. Neither table can be created first with both FK constraints.

**Decision:** Create `users` first without the `ai_league_id` FK, create `leagues`, then add the FK with `ALTER TABLE users ADD CONSTRAINT ...`.

**Rationale:** Standard PostgreSQL pattern for circular references. Clean, readable, no workaround needed.

**Consequences:** Migration order must be respected. The `ALTER TABLE` must come after `leagues` creation in every future migration that recreates these tables.

---

## D-015 — RLS requires both GRANT and policies (Supabase)

**Date:** 2026-03-18
**Status:** Accepted

**Context:** During RLS testing, all authenticated queries returned `permission denied`
despite correct RLS policies being in place.

**Finding:** PostgreSQL enforces two independent access control layers:

1. `GRANT` — controls whether a role can access the table at all.
2. RLS policies — control which rows that role can see.

Without `GRANT SELECT` on a table, RLS policies never evaluate — the query
fails at the permission check. Both layers are required.

**Decision:** All tables have explicit `GRANT` statements for the `authenticated`
and `service_role` roles. `fantasy_scores_staging` intentionally has no grant
for `authenticated` — `permission denied` is the correct behaviour for clients.

**Consequences:** Any new table added to the schema requires both an RLS policy
AND a `GRANT` statement. This is documented as a checklist item for future migrations.

---

## D-016 — Roster composition constraints: fixed in V1, configurable in V2

**Date:** 2026-03-18
**Status:** Accepted

**Context:** The CDC defines maximum players per nation/club in a roster:

- International competitions: maximum 8 players from the same nation
- Club competitions: maximum 6 players from the same club

The question was whether these limits should be fixed constants or
configurable per league by the commissioner.

**Options considered:**

- A) Fixed constants — hardcoded in the draft engine validation logic
- B) Configurable per league — stored as fields on the `leagues` table,
  editable by the commissioner before the draft starts

**Decision:** Option A in V1. Option B deferred to V2 if demand is confirmed.

**Rationale:**

- Configurable limits require additional DB fields, commissioner UI,
  and draft engine logic that reads config instead of constants.
- The majority of commissioners will never change these defaults.
- V1 scope must stay focused — this is a nice-to-have, not a core feature.
- Adding configurable limits in V2 is a non-breaking migration
  (add columns with defaults matching the current hardcoded values).

**Consequences:**

- `MAX_PLAYERS_PER_NATION = 8` and `MAX_PLAYERS_PER_CLUB = 6` will be
  defined as constants in the draft engine (Phase 2).
- Validation happens in FastAPI at pick time — not in Pydantic models.
- If a commissioner requests custom limits in beta feedback → implement in V2.

---

## D-017 — Brand color palette updated from CDC specification

**Date:** 2026-03-19
**Status:** Decided

### Context

The CDC (v3.1) specified `#1A5C38` (forest green) as the primary brand color.
During Phase 1 frontend skeleton, a full color palette was designed in Figma
("RugbyDraft Color Palette") with a revised brand direction.

### Decision

The Figma palette supersedes the CDC color specification. The four brand colors are:

- **Crimson** `#872138` — primary (CTA, active states, brand identity)
- **Rose** `#F2CAD3` — accent (hover states, soft backgrounds)
- **Deep** `#21080E` — foreground (text, dark surfaces)
- **Lime** `#99BF36` — secondary (scores, positive highlights, secondary CTA)

Each color has a 7-shade scale defined in Figma and mapped to CSS custom properties
in `frontend/src/app/globals.css` via Tailwind v4 `@theme inline`.

The CDC document is **not updated** (confidential, gitignored). This entry is the
source of truth for the color decision going forward.

### Rationale

The crimson/lime combination creates a stronger visual identity for a rugby app
(intensity, energy, sport) compared to the original forest green. The complete
7-shade palette enables a consistent design system across all components without
needing to hardcode hex values outside of `globals.css`.

### Impact

- `frontend/src/app/globals.css` — CSS custom properties + Tailwind v4 theme mapping
- `frontend/src/app/[locale]/login/page.tsx` — uses brand colors directly
- CDC section on colors is superseded by this decision — do not revert to `#1A5C38`

---
