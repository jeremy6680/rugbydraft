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
**Status:** Superseded by D-037 (2026-03-23) — DSG confirmed, provider selection closed.

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

## D-018 — AppShell: middleware-first auth, intlMiddleware response as base

**Date:** 2026-03-19
**Status:** Accepted

**Context:** Implementing route protection required combining Supabase Auth
session refresh with next-intl locale routing in a single middleware.ts.
Two approaches were tested.

**Problem encountered:** Running Supabase first (writing cookies to a
NextResponse.next()) then calling intlMiddleware(request) discarded the
session cookies — next-intl creates a new response object, ignoring the
previous one. Result: getUser() in the protected layout found no session
and redirected to login even after successful authentication.

**Decision:** Run intlMiddleware(request) first to obtain its response
object, then write Supabase session cookies onto that same response.
This guarantees both locale rewrites and session cookies survive on the
single response returned to the browser.

**Additional fix:** The auth/callback route.ts was writing session cookies
onto the Next.js cookieStore rather than the redirect response. Cookies
written to cookieStore in a Route Handler are not reliably sent to the
browser. Fixed by constructing the NextResponse.redirect() first and
writing cookies directly onto it before returning.

**Consequences:**

- middleware.ts order is: intlMiddleware → Supabase getUser → route guard
- auth/callback/route.ts writes cookies onto redirectResponse, not cookieStore
- /auth/callback is excluded from the middleware matcher entirely

---

## D-019 — Snake order as a pure function, tested before FastAPI integration

**Date:** 2026-03-19
**Status:** Accepted

**Context:** The snake draft order algorithm is the foundational invariant of the
draft engine. It needs to be correct before any FastAPI or database integration.

**Options considered:**

- A) Write the algorithm directly inside the DraftEngine class (FastAPI layer).
- B) Extract it as a pure Python function, tested in full isolation first.

**Decision:** Option B — pure function in `backend/draft/snake_order.py`,
tested with 33 unit tests before any integration.

**Rationale:**

- A pure function `f(managers, num_rounds) → list[str]` is deterministic and
  trivially testable with no infrastructure (no DB, no server, no async).
- A bug in pick ordering (wrong manager gets a turn) would be catastrophic
  and hard to debug inside a running FastAPI server.
- The function is reused as-is by the DraftEngine — no duplication.
- 33 tests cover 2–6 managers, full 30-round drafts, edge cases, and error paths.

**Consequences:**

- `snake_order.py` has zero external dependencies — pure Python stdlib.
- `get_pick_owner(pick_number, managers)` is O(1): no need to generate
  the full order to answer "who picks now?".
- The DraftEngine will call these functions directly — no reimplementation.

---

## D-020 — DraftTimer as an isolated asyncio class, tested before DraftEngine integration

**Date:** 2026-03-19
**Status:** Accepted

**Context:** The server-side pick timer is a critical component — expiration
triggers autodraft automatically. It must be reliable before being wired into
the DraftEngine.

**Options considered:**

- A) Implement the timer directly inside the DraftEngine class.
- B) Extract it as a standalone asyncio class, tested in isolation first.

**Decision:** Option B — `DraftTimer` in `backend/draft/timer.py`, tested
with 22 unit tests before any DraftEngine integration.

**Rationale:**

- `asyncio.Task` + `asyncio.sleep` runs inside the FastAPI event loop —
  zero thread overhead, clean cancellation via `Task.cancel()`.
- `asyncio.get_event_loop().time()` (monotonic clock) is used for
  `time_remaining` — immune to system clock changes and NTP adjustments.
- The `on_expire` callback is async, allowing the DraftEngine to await
  downstream effects (autodraft, Realtime broadcast) without blocking.
- `asyncio.coroutine` was removed in Python 3.11 — tests use `async def`
  dummy coroutines instead.
- 22 tests cover: init, start, expiration, cancellation, idempotency,
  and the CDC reconnection protocol (section 7.4).

**Consequences:**

- One `DraftTimer` instance per active pick slot.
- The DraftEngine creates a new timer when a pick slot opens and calls
  `cancel()` when the manager picks before expiration.
- `time_remaining` is queryable at any point — used in the reconnection
  state snapshot sent to reconnecting clients.

---

## D-021 — Pick validation as a pure function with typed exceptions

**Date:** 2026-03-19
**Status:** Accepted

**Context:** Pick validation is the guard layer between a manager's pick request
and the DraftEngine accepting it. It must be reliable, explicit, and testable
before being wired into FastAPI.

**Decision:** `validate_pick()` in `backend/draft/validate_pick.py` — pure
function, no I/O, typed exceptions per failure reason, tested with 17 unit tests.

**Three validation layers (in order):**

1. Turn validation — is it this manager's turn? (NotYourTurnError)
2. Player availability — not drafted, not injured/suspended (PlayerAlreadyDraftedError, PlayerUnavailableError)
3. Roster constraints — not full, nationality/club limits respected (RosterFullError, NationalityLimitError, ClubLimitError)

**Rationale:**

- Typed exceptions (one per failure reason) give the DraftEngine precise
  control: each maps to a distinct HTTP 422 code + i18n key for the frontend.
- The `.code` attribute on each exception is machine-readable — the frontend
  uses it as a key for `messages/fr.json` error display.
- Validation stops at the first failure — no need to collect all errors
  in a draft context (the manager must fix one issue at a time).
- A `RosterSnapshot` dataclass isolates the validation input from DB objects.

**Bug found during tests:** `test_nationality_limit_not_applied_in_club` was
constructing a roster with 8 players from the same club (exceeding MAX_PER_CLUB=6),
causing a spurious ClubLimitError. Fixed by capping test clubs at MAX_PER_CLUB-1.
Lesson: test fixtures must not violate unrelated constraints.

**Consequences:**

- The DraftEngine wraps `validate_pick()` in a try/except and maps each
  exception type to the appropriate HTTP response + Realtime broadcast.
- `RosterSnapshot` is built from the DraftState in memory — no DB query
  needed at pick validation time.
- Constants `MAX_PER_NATION=8` and `MAX_PER_CLUB=6` are defined here (D-016).

---

## D-022 — Autodraft as a pure function, reusing validate_pick constraints

**Date:** 2026-03-19
**Status:** Accepted

**Context:** Autodraft must respect the same roster constraints as a manual pick
(nationality/club limits). Two approaches were considered for constraint checking.

**Options considered:**

- A) Duplicate the constraint logic inside autodraft.py.
- B) Reuse \_validate_roster_constraints() from validate_pick.py directly.

**Decision:** Option B — autodraft calls \_validate_roster_constraints() as a
single source of truth for roster rules. The internal helper is imported directly.

**Rationale:**

- Zero duplication: constraint logic lives in one place only.
- If MAX_PER_NATION or MAX_PER_CLUB change, autodraft picks up the change
  automatically — no second file to update.
- \_passes_roster_constraints() wraps the call in a try/except and returns
  a bool — clean interface for the autodraft iteration loop.
- Note: RosterFullError is intentionally NOT caught in autodraft — if the
  roster is full, autodraft should never have been triggered (DraftEngine bug).

**Selection algorithm:**

1. Preference list (manager's personal ranking) — first available valid player.
2. Default value (available_players pre-sorted by value_score desc by DraftEngine)
   — first player that passes constraints.

**Consequences:**

- available_players must be pre-sorted by value_score descending by the caller
  (DraftEngine). autodraft.py does not sort — separation of responsibilities.
- AutodraftResult.source = "preference_list" | "default_value" — logged for
  audit trail and future analytics.
- AutodraftError (no valid player found) indicates a data integrity issue —
  DraftEngine must halt the draft and alert the commissioner.

---

## D-023 — DraftEngine: asyncio.create_task() for autodraft to prevent recursion

**Date:** 2026-03-19
**Status:** Accepted

**Context:** When all managers are in autodraft, \_start_current_turn() →
\_run_autodraft_for_current_pick() → \_advance_to_next_turn() → \_start_current_turn()
creates a synchronous recursive call chain up to N_managers × 30 levels deep.
This caused RecursionError / AutodraftError in tests and made start_draft()
block until the entire draft completed.

**Decision:** In \_start_current_turn(), autodraft picks are scheduled via
asyncio.create_task() instead of direct await. This yields control back to
the event loop between each pick, breaking the recursion.

**Consequences:**

- start_draft() returns immediately even if all managers are in autodraft.
- connect_manager() can deactivate autodraft between picks (reconnection protocol).
- The lock must be re-acquired inside \_run_autodraft_for_current_pick() since
  it is now called from a separate Task.

**Bug found during tests — reconnection with autodraft:**
connect_manager() originally checked self.\_current_timer is not None to
detect "own turn with time remaining". But in autodraft mode there is no
timer — the condition silently failed. Fixed by checking pick_not_yet_made
(no pick recorded for current_pick_number) instead. When a manager reconnects
during their autodraft turn before the task executes, we discard them from
autodraft_managers and start a real timer for manual control.

**Bug found during tests — homogeneous player pool:**
make_player_pool() in tests generated all players with nationality="FRA".
After 8 picks, MAX_PER_NATION was hit and AutodraftError was raised.
Fixed by rotating through 10 nationalities in the test pool.
Both bugs were in the tests, not in the engine logic.

---

## D-024 — Broadcaster as injected dependency, Protocol over ABC

**Date:** 2026-03-19
**Status:** Accepted

**Context:** The DraftEngine needs to broadcast state changes to Supabase
Realtime after every mutation. Two questions arose: (1) how to decouple the
engine from the Supabase SDK for testing, and (2) whether to use ABC or Protocol.

**Options considered:**

- A) Hardcode Supabase calls inside DraftEngine.\_broadcast().
- B) Inject a broadcaster via the constructor — Protocol interface.
- C) Inject a broadcaster via the constructor — ABC interface.

**Decision:** Option B — BroadcasterProtocol (PEP 544 structural typing).
Injected via DraftEngine.**init**(broadcaster=...), defaulting to MockBroadcaster.

**Rationale:**

- Injection: DraftEngine has no knowledge of Supabase. In tests, MockBroadcaster
  captures events with zero I/O. In production, SupabaseBroadcaster is passed in.
- Protocol over ABC: duck typing is more idiomatic Python 3.10+. Any class with
  async broadcast(event) satisfies the interface — no explicit inheritance needed.
  @runtime_checkable allows isinstance() checks for FastAPI DI validation.
- MockBroadcaster default: the engine is safe to instantiate anywhere (scripts,
  tests, local dev) without a Supabase connection.

**Broadcast failure is non-fatal:** SupabaseBroadcaster.broadcast() catches all
exceptions and logs them. A Realtime outage must never crash the draft — clients
call GET /draft/{id}/state for a full snapshot (reconnection protocol, D-001).

**Clock synchronisation over tick streaming:** DraftTurnChangedEvent includes
turn_started_at + pick_duration. Clients compute the countdown locally:
remaining = pick_duration - (now - turn_started_at). No per-second tick
broadcast needed — far fewer messages, immune to dropped ticks.

**New files:**

- backend/draft/events.py — typed DraftEvent dataclasses (6 event types)
- backend/draft/broadcaster.py — BroadcasterProtocol, MockBroadcaster, SupabaseBroadcaster

**Consequences:**

- DraftEngine.**init**() gains a broadcaster parameter (optional, default MockBroadcaster).
- \_broadcast(event: DraftEvent) replaces the stub \_broadcast() — callers pass typed events.
- 8 new tests in test_engine.py validate the broadcast contract (event types + payloads).
- Total test count: 114 → 122 after this step (26 in test_engine.py alone).

---

## D-025 — Reconnection protocol: DraftRegistry + 3 FastAPI endpoints

**Date:** 2026-03-20
**Status:** Accepted

**Context:** The reconnection logic already lived in `connect_manager()` inside
the DraftEngine (D-001, D-023). What was missing was the FastAPI layer to expose
it: a registry to find active engines by league_id, and endpoints for clients to
call on reconnection.

**Decision:** Three components added:

1. `backend/draft/registry.py` — `DraftRegistry`: thread-safe dict
   `league_id → DraftEngine`, stored as `app.state.draft_registry` in the
   FastAPI lifespan. Mutations (register, remove) protected by asyncio.Lock.
   Reads (get) are lock-free (GIL + atomic dict lookup sufficient in CPython).

2. `backend/app/schemas/draft.py` — `DraftStateSnapshotResponse` and
   `PickRecordResponse`: Pydantic response models mirroring the internal
   DraftStateSnapshot dataclass. Separation of API contract from engine internals.

3. `backend/app/routers/draft.py` — three endpoints:
   - `POST /draft/{league_id}/connect` — calls `connect_manager()`, returns snapshot.
     Deactivates autodraft and starts a manual timer if reconnecting during own turn.
   - `POST /draft/{league_id}/disconnect` — calls `disconnect_manager()`, returns 200.
   - `GET /draft/{league_id}/state` — calls `get_state_snapshot()`, read-only.
     Polling fallback when Supabase Realtime is unavailable.

**FastAPI lifespan pattern:** `app.state.draft_registry = DraftRegistry()` is
initialised in `@asynccontextmanager async def lifespan(app)` — the modern
FastAPI pattern replacing deprecated `@app.on_event("startup")`.

**HTTP 204 note:** FastAPI 0.115.12 raises an AssertionError when a POST endpoint
declares `status_code=204` without `response_class=Response` — and even with it
in some configurations. Decision: use HTTP 200 with `response_model=None` for
disconnect. Functionally equivalent; avoids framework friction.

**Test timing note (asyncio.create_task):** Test 1 (reconnect during own turn)
initially used `await asyncio.sleep(0)` to schedule the autodraft task without
executing it. In CPython 3.13, `sleep(0)` is sufficient to execute the task
in some event loop configurations, causing the pick to be made before reconnect.
Fixed by removing the sleep entirely — `connect_manager()` under its lock runs
before the scheduled task can execute, which is the exact reconnection window
the test is validating.

**Consequences:**

- `app/main.py` gains a lifespan context manager — `DraftRegistry` initialised at startup.
- `draft.router` activated in `main.py` (was commented as "Phase 2").
- 4 new tests in `tests/test_reconnection.py` — all pass (126/126 total).
- New files: `registry.py`, `schemas/draft.py`, `routers/draft.py`.
- Total test count: 122 → 126.

---

## D-026 — Assisted Draft: commissioner_id in DraftState, audit log in memory

**Date:** 2026-03-20
**Status:** Accepted

**Context:** The Assisted Draft mode (CDC v3.1, section 7.5) requires (1) authorising
only the league commissioner to activate the mode and submit picks, and (2) an audit
log of all commissioner-entered picks, visible to all managers.

Two architectural questions arose:

**Question 1 — Where does assisted_mode state live?**

- Option A: Only in the DB (`drafts.is_assisted_mode`) — survives FastAPI restart,
  but requires a DB query on every pick to check the flag.
- Option B: Only in `DraftState` (in memory) — consistent with all other draft state,
  lost on FastAPI restart.
- Option C: Both — `DraftState.assisted_mode` (runtime authority) + persisted to
  `drafts.is_assisted_mode` on enable (for restart recovery).

**Decision:** Option B for V1. The `drafts.is_assisted_mode` column already exists
in the schema (001_initial_schema.sql) and will be used for restart recovery in a
future phase. In V1, restart mid-assisted-draft is an edge case without a documented
recovery procedure (tracked in NEXT_STEPS.md).

**Rationale:** Consistent with D-001 — FastAPI is the authority of state. All runtime
draft state lives in `DraftState`. Adding a DB sync on every `enable_assisted_mode()`
call would complicate the engine without providing value until restart recovery is
implemented.

**Question 2 — Where does the audit log live?**

- Option A: DB only (`draft_picks.entered_by_commissioner`) — survives restart,
  requires a DB query to serve GET /assisted/log.
- Option B: In memory (`DraftState.assisted_audit_log`) + DB column as persistence
  — GET /assisted/log served from memory during active draft, from DB after completion.

**Decision:** Option B for V1. The `draft_picks.entered_by_commissioner` column
already exists in the schema. In V1, the in-memory audit log is authoritative during
an active draft. Persistence to DB is implemented when the pick persistence layer
(Phase 3) is built.

**commissioner_id in DraftState:** Added as a required field (with default
`"commissioner-default"` for tests). The commissioner is set at engine creation and
never changes — it does not need to be updatable.

**New files:**

- `backend/draft/assisted.py` — pure logic: typed errors, `AssistedPickAuditEntry`,
  pure validation functions (`validate_commissioner`, `validate_assisted_mode_active`, etc.)
- `backend/app/routers/draft_assisted.py` — 3 endpoints:
  POST /assisted/enable, POST /assisted/pick, GET /assisted/log
- `backend/tests/draft/test_assisted.py` — 19 tests across 5 classes

**Changes to existing files:**

- `draft/engine.py` — `DraftState` gains `assisted_mode`, `assisted_audit_log`,
  `commissioner_id`. `DraftEngine` gains `enable_assisted_mode()`,
  `submit_assisted_pick()`, `get_assisted_audit_log()`. `_record_pick()` gains
  `entered_by_commissioner` flag. `_start_current_turn()` is assisted-mode aware
  (no timer started in assisted mode).
- `draft/events.py` — `DraftPickMadeEvent` gains `entered_by_commissioner` field.
  New event: `DraftAssistedModeEnabledEvent`.
- `app/schemas/draft.py` — `PickRecordResponse` gains `entered_by_commissioner` field.
- `app/main.py` — `draft_assisted.router` mounted.
- `tests/draft/test_engine.py` and `tests/test_reconnection.py` — `make_engine()`
  helpers updated with `commissioner_id="test-commissioner"`.

**Consequences:**

- `DraftEngine.__init__()` gains `commissioner_id: str = "commissioner-default"`.
  Default value preserves backward compatibility with existing tests.
- HTTP 403 for non-commissioner actions (not 401 — the user is authenticated,
  just not authorised for this specific resource).
- HTTP 409 Conflict for mode guard errors (already active / not active) — more
  precise than 422 which is reserved for data validation failures.
- Total test count: 126 → 145 (19 new tests in test_assisted.py).

---

## D-027 — Ghost team identity as a structural property, not a runtime state

**Date:** 2026-03-21
**Status:** Accepted

**Context:** Ghost teams (CDC section 11) are computer-managed teams that fill
the bracket when the manager count is odd or below the competition minimum.
They must always autodraft — never receive a timer, never take manual control.
Two approaches were considered for implementing this constraint.

**Options considered:**

- A) Add ghost team IDs to `autodraft_managers` at draft start, like a
  manager who never connected. Reuse the existing autodraft path entirely.
- B) Treat ghost status as a structural property of the manager ID
  (`ghost_manager_ids: frozenset[str]` on `DraftState`), separate from
  the dynamic `autodraft_managers` set.

**Decision:** Option B — ghost status is a structural (immutable) property,
not a dynamic runtime state.

**Rationale:**

- `autodraft_managers` is a dynamic set: managers enter it when their timer
  expires, and leave it when they reconnect. Ghost teams must never leave it.
  Mixing structural and dynamic state in the same set creates a latent bug:
  `connect_manager()` calls `autodraft_managers.discard(manager_id)`, which
  would silently give a ghost team manual control if Option A were used.
- A `frozenset` signals immutability to readers: ghost status never changes
  during a draft. `autodraft_managers` changes constantly.
- `is_ghost_id()` in `ghost_team.py` is the single source of truth for ghost
  detection — one import, one check, used in `_start_current_turn()` and
  `connect_manager()`.

**Implementation:**

- `backend/draft/ghost_team.py` — `GhostTeam` dataclass, `create_ghost_teams()`,
  `ghost_teams_needed()`, `is_ghost_id()`, `generate_ghost_name()`.
- `DraftState.ghost_manager_ids: frozenset[str]` — immutable after init.
- `DraftStateSnapshot.ghost_manager_ids: list[str]` — exposed to the frontend
  so it can render ghost teams differently (no timer, special avatar, etc.).
- `_start_current_turn()`: `is_ghost_id(current_manager)` → immediate
  `asyncio.create_task(autodraft)`, no timer started.
- `connect_manager()`: `not is_ghost_id(manager_id)` guard prevents ghost
  teams from ever deactivating their autodraft status.

**Consequences:**

- Phase 3 waiver/trade blocking: `is_ghost_id()` is already importable
  anywhere. The waiver and trade endpoints simply call it as a guard.
- Phase 3 IR release: ghost team injured player auto-release (D-010) will
  use the same `is_ghost_id()` check to identify the source team.
- Ghost teams have no preference list — `_preference_lists.get(ghost_id, [])`
  returns `[]`, so autodraft always falls through to `default_value` source.
  This is correct per CDC section 11.

---

## D-028 — Post-draft roster coverage validation: warning, not hard block

**Date:** 2026-03-21
**Status:** Accepted

**Context:** CDC v3.1 section 6.2 defines minimum bench coverage requirements
(e.g. 2 props, 1 hooker, 1 lock, etc.). The question was: should a coverage
failure at draft completion block the draft from completing, or log a warning
and let the draft complete anyway?

**Options considered:**

- A) Hard block — refuse to mark the draft as COMPLETED if any roster fails
  coverage. Commissioner must manually correct the roster before proceeding.
- B) Warning only — mark the draft COMPLETED regardless, log the coverage
  failure, notify the commissioner. Picks are final.

**Decision:** Option B — warning only in V1.

**Rationale:**

- Coverage failures in practice only occur via autodraft (human managers
  are guided by the frontend's real-time coverage indicator in Phase 4).
- Blocking the draft would strand all managers in a completed-but-not-completed
  state with no UI to fix it — worse UX than a warning.
- The autodraft algorithm (Phase 2) does not yet enforce coverage minimums
  when selecting players. Enforcing coverage at autodraft selection time
  is the correct long-term fix — deferred to Phase 3 or V2 (see consequences).
- Picks are final by design (CDC v3.1, section 7) — no rollback mechanism exists.

**Consequences:**

- `DraftEngine._complete_draft()` calls `validate_roster_coverage()` per manager
  and logs `WARNING` on failure. The draft completes regardless.
- A `TODO` comment marks the broadcast point for Phase 4:
  `RosterCoverageWarningEvent` will alert the commissioner in the UI.
- Future improvement (V2): autodraft `select_autodraft_pick()` should enforce
  coverage minimums in its selection loop, not just nationality/club limits.
  This would prevent coverage failures from occurring at all.

---

## D-029 — FastAPI restart mid-draft: recovery procedure

**Date:** 2026-03-21
**Status:** Accepted

**Context:** DraftEngine state is held entirely in memory (D-001). If the
FastAPI process restarts mid-draft (crash, deploy, OOM kill), all in-memory
state is lost. Clients will attempt to reconnect but the engine is gone.
This is the highest-severity operational risk in Phase 2.

**The problem in detail:**

```
Draft running: pick 14/90, timer ticking for manager M2.
FastAPI process killed (OOM / deploy / crash).
M2's browser is still open — timer ticks down client-side.
M1 submits a pick → 503 / connection refused.
Supabase Realtime channel goes silent.
All managers see a frozen draft room.
```

**What is persisted vs lost:**

| Data                  | Persisted                                | Lost on restart    |
| --------------------- | ---------------------------------------- | ------------------ |
| Picks already made    | ✅ `draft_picks` table                   | —                  |
| Current pick number   | ✅ `drafts.current_pick_number`          | —                  |
| Draft status          | ✅ `drafts.status`                       | —                  |
| Assisted audit log    | ✅ `draft_picks.entered_by_commissioner` | —                  |
| In-memory timer state | ❌ —                                     | ✅ lost            |
| Autodraft manager set | ❌ —                                     | ✅ lost            |
| Connected manager set | ❌ —                                     | ✅ lost            |
| Available player pool | ❌ —                                     | ✅ rebuilt from DB |

**Decision:** Manual recovery procedure in V1. Automated recovery deferred to V2.

**V1 recovery procedure (commissioner-initiated):**

1. **Detect the restart** — clients see Realtime channel go silent +
   HTTP 503 on pick submission. FastAPI health endpoint (`GET /health`)
   returns 200 once the process is back up.

2. **Commissioner switches to Assisted Draft** — once FastAPI is back,
   the commissioner calls `POST /draft/{league_id}/assisted/enable`.
   This is the intended fallback for any draft disruption (CDC v3.1, section 7.5).

3. **Engine reconstruction** — the `DraftRegistry` is empty after restart.
   The first call to any draft endpoint triggers engine reconstruction:
   - Read `drafts` table: status, current_pick_number, pick_duration,
     competition_type, commissioner_id.
   - Read `draft_picks` table: all picks already made → rebuild
     `drafted_player_ids`, `rosters`, `picks` list.
   - Read `league_members` table: manager list, ghost team IDs.
   - Reconstruct `draft_order` via `generate_snake_order()` with the
     same shuffled manager order (stored in `drafts.manager_order` — JSONB).
   - Set `assisted_mode = True` immediately (step 2 above).
   - All managers start as disconnected — they reconnect via `POST /connect`.

4. **Resume** — commissioner enters remaining picks via Assisted Draft.
   No timer, no autodraft race condition. Audit log shows the restart gap.

**Implementation status:** Reconstruction logic (`reconstruct_engine_from_db()`)
is NOT implemented in Phase 2. The procedure above defines the contract —
implementation is a Phase 3 prerequisite before first real draft.

**What must be added to the DB schema before Phase 3:**

- `drafts.manager_order` — JSONB array storing the shuffled manager order
  after the random draw. Without this, `generate_snake_order()` cannot
  produce the same draft order after a restart.
  → Migration required: `ALTER TABLE drafts ADD COLUMN manager_order JSONB`.

**Consequences:**

- Phase 2 drafts (localhost testing, demo) accept the restart risk — data
  loss is acceptable at this stage.
- Before first real draft (Phase 3 / beta): `reconstruct_engine_from_db()`
  must be implemented and tested, and `drafts.manager_order` migration applied.
- The `TODO` in `DraftRegistry` marks the reconstruction hook point.
- CI test required in Phase 3: simulate restart at pick N, reconstruct,
  verify remaining picks complete correctly.

---

---

---

## D-030 — dbt dual-target: DuckDB (ci) + PostgreSQL (prod)

**Date:** 2026-03-22
**Status:** Accepted

**Context:** Gold models need to join dbt silver models with PostgreSQL
application tables (`weekly_lineups`, `rosters`, `league_members`, etc.).
Bronze models use `read_json_auto()` — a DuckDB-only function. Running
bronze or silver on PostgreSQL is structurally impossible.

**Options considered:**

- A) All layers on PostgreSQL in prod. DuckDB for dev/CI only.
- B) DuckDB for bronze+silver, Python export DuckDB→PG, gold on PostgreSQL.
- C) DuckDB `postgres_scanner` extension (experimental, unreliable in 1.x).

**Decision:** Option B — DuckDB for bronze+silver, PostgreSQL for gold,
with `scripts/export_silver_to_pg.py` as the bridge.

**Rationale:**

- Option A is impossible: `read_json_auto()` is DuckDB-only. Bronze models
  cannot run on PostgreSQL.
- Option C is experimental and has known issues on complex joins and NUMERIC
  types in DuckDB 1.x. Rejected for production use.
- Option B is the correct split: DuckDB for what it's good at (reading
  connector JSON files efficiently), PostgreSQL for what it's good at
  (joining application state with scoring data).

**Implementation:**

- `profiles.yml` has two outputs:
  - `ci` (default): DuckDB — runs bronze + silver. No Supabase needed.
  - `prod`: PostgreSQL (Supabase) — runs gold only.
- `scripts/export_silver_to_pg.py`: reads the 5 silver tables from DuckDB,
  writes them to PostgreSQL as `pipeline_stg_*` tables. Runs between the
  dbt silver step and the dbt gold step in the Airflow DAG.
- Gold models use `{{ source('postgres', 'pipeline_stg_*') }}` for silver
  data and `{{ source('postgres', '...') }}` for application tables.

**Airflow DAG sequence (post_match_pipeline):**

```
1. ingest               → JSON in data/raw/          (Python)
2. dbt run --target ci  → bronze + silver in DuckDB  (dbt)
3. export_silver_to_pg  → pipeline_stg_* in PG       (Python)
4. dbt run --target prod --select gold → gold in PG  (dbt)
5. atomic commit        → staging → fantasy_scores   (Python)
```

**CI sequence (GitHub Actions, no Supabase):**

```
dbt run --target ci --select bronze silver
dbt test --target ci --select bronze silver
```

Gold models excluded from CI — they require a live Supabase connection.

**Consequences:**

- `profiles.yml.example` updated with `ci` and `prod` targets.
- `dbt_project/models/sources.yml` declares all PostgreSQL sources.
- `dbt-postgres` added to `dbt_project/requirements.txt`.
- `scripts/export_silver_to_pg.py` is a required step in the Airflow DAG.
- The 5 `pipeline_stg_*` tables in PostgreSQL are disposable —
  they are fully replaced on every pipeline run.

---

## D-031 — external_id columns on players and real_matches

**Date:** 2026-03-22
**Status:** Accepted

**Context:** Silver models identify players and matches via `external_id`
strings from the data provider (e.g. `player_external_id`, `match_external_id`).
PostgreSQL application tables use UUIDs (`players.id`, `real_matches.id`).
Gold models need to join these two worlds — there was no bridge column.

**Decision:** Add `external_id TEXT` to `players` and `real_matches`.
Populated by the connector ingestion script when creating/updating records.

**Migration:** `db/migrations/003_add_external_ids.sql`

```sql
ALTER TABLE players     ADD COLUMN IF NOT EXISTS external_id TEXT;
ALTER TABLE real_matches ADD COLUMN IF NOT EXISTS external_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_players_external_id
    ON players (external_id) WHERE external_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_real_matches_external_id
    ON real_matches (external_id) WHERE external_id IS NOT NULL;
```

**Join pattern in gold models:**

```sql
inner join players p
    on p.external_id = pipeline_stg_players.player_external_id
inner join real_matches rm
    on rm.external_id = pipeline_stg_matches.match_external_id
```

**Consequences:**

- Connector implementations must set `external_id` when upserting players
  and matches. The mock connector must be updated to include external IDs
  in fixture data.
- `external_id` is nullable (INDEX WHERE NOT NULL) — existing rows without
  a provider ID are not affected.
- The silver export script (`export_silver_to_pg.py`) does not need to
  change — it exports the full silver tables as-is.

---

## D-032 — Airflow version pinned to 2.7.2 (pendulum constraint)

**Date:** 2026-03-22
**Status:** Accepted

**Context:** Airflow 2.8 and 2.9 were yanked from PyPI. Airflow 2.7.2 is
the last available 2.x release. Airflow 2.x requires pendulum 2.x, but pip
resolves pendulum 3.x by default — which breaks `pendulum.tz.timezone()`.

**Decision:** Pin `apache-airflow==2.7.2` and `pendulum>=2.0,<3.0` in both
`airflow/requirements.txt` and `airflow/tests/requirements-test.txt`.

**Rationale:** Airflow 3.x breaks the 2.x operator API (removes
`provide_context`, `apply_defaults`, restructures BaseOperator). Migrating
to Airflow 3.x would require a full rewrite of all custom operators. Not
justified at this stage.

**Consequences:**

- Airflow structural tests require a dedicated Python 3.11 venv (`.venv-airflow`)
  because Airflow 2.7.2 + pendulum 2.x install cleanly on 3.11.
- `.venv-airflow/` added to `.gitignore`.
- `airflow/tests/requirements-test.txt` pins both `apache-airflow` and `pendulum`.
- Migration to Airflow 3.x deferred to a future phase if needed.

---

## D-033 — Lock authority for weekly lineup: kick_off_time < NOW()

**Date:** 2026-03-22
**Status:** Accepted

**Context:** Weekly lineups must be locked progressively per match, not globally
per round (CDC 6.5). The question is what determines whether a player is locked:
the `kick_off_time` timestamp or the `status` field on `real_matches`.

**Options considered:**

- A) Compare `real_matches.kick_off_time < NOW()` — pure timestamp comparison.
- B) Use `real_matches.status = 'live'` — depends on the pipeline updating status.

**Decision:** Option A — `kick_off_time < NOW()` is the lock authority.

**Rationale:**

- Independent of the pipeline: lock activates at the exact scheduled time
  regardless of whether the post_match_pipeline has run yet.
- No race condition: a pipeline delay cannot accidentally keep a player unlocked
  past their kick_off.
- `status` remains useful for display (showing "live" badge) but never for
  access control decisions.

**Consequences:**

- `_fetch_kickoff_times()` in `LineupService` queries `real_matches.kick_off_time`
  once per service call and maps club → datetime.
- `locked_at` stored in `weekly_lineups` is set by the pipeline at kick_off,
  not by the user submission.
- If a kick_off_time is corrected after the fact (rare), locked_at in
  weekly_lineups retains the original value — acceptable for V1.

---

## D-034 — Waiver window: Europe/Paris, Tuesday 07:00 → Wednesday 23:59:59

**Date:** 2026-03-22
**Status:** Accepted

**Context:** CDC 9.1 specifies "Tuesday morning → Wednesday evening" without
exact times. The Staff IA Tuesday report triggers at 07:00 (CDC 13.2) —
the waiver window opens immediately after.

**Decision:** Window opens Tuesday 07:00, closes Wednesday 23:59:59,
Europe/Paris timezone.

**Rationale:** "Tuesday morning" is a local concept for French users.
Using UTC would shift the window by one hour in summer (CEST = UTC+2),
making "Tuesday morning" mean 09:00 local time — confusing.
zoneinfo.ZoneInfo("Europe/Paris") handles DST automatically.

**Consequences:**

- `WAIVER_OPEN_TIME` and `WAIVER_CLOSE_TIME` are module-level constants
  in `waivers/window.py` — easy to make per-league configurable in a
  future phase if needed.
- The scheduler (Cron Coolify) must be configured in Europe/Paris timezone
  to match this window.

---

## D-035 — Trade format: symmetric 1-3 players per side

**Date:** 2026-03-22
**Status:** Accepted

**Context:** CDC §9.2 states "1 joueur contre 1, 2 ou 3 joueurs". This was
initially misread as "proposer always sends exactly 1 player". The intended
meaning (confirmed by the product owner) is symmetric: each side sends
1, 2, or 3 players.

**Decision:** Both proposer and receiver send between 1 and 3 players.
Valid formats: 1v1, 1v2, 1v3, 2v1, 2v2, 2v3, 3v1, 3v2, 3v3.

**Rationale:** Consistent with fantasy US apps (ESPN, Sleeper) which
inspired the trade mechanic. A 2v2 or 3v1 trade is a legitimate strategy.

**Consequences:** `_check_format()` in `validate_trade.py` validates
both sides symmetrically.

---

## D-036 — Trade veto audit: veto_at + veto_reason columns on trades table

**Date:** 2026-03-22
**Status:** Accepted

**Context:** CDC §9.2 requires the commissioner veto to be logged with a
reason visible to all managers. The question was whether to use a separate
audit table or columns on the existing `trades` table.

**Decision:** Add `veto_reason TEXT` and `veto_at TIMESTAMPTZ` directly
to the `trades` table (migration 004). Also add `cancelled_at` and
`completed_at` for full transition traceability.

**Rationale:** Trade volume is low (at most a few dozen per league per
season). A separate audit table would be overkill. All transition data
fits cleanly on a single row. The log page queries one table with no joins.

**Consequences:**

- Migration 004 adds 4 columns to `trades` via ALTER TABLE.
- `TradeRecord` (processor) carries these fields in memory.
- `trade_service._update_trade_status()` persists them on each transition.

---

## D-037 — DSG confirmed as data provider (resolution of D-012)

**Date:** 2026-03-23
**Status:** Accepted

**Context:** D-012 left the provider selection open pending validation.
Phase 0 validation was completed on 2026-03-22 using DSG match 3798425
(Clermont vs Toulouse, Top 14 2025/26). All blocking stats confirmed.
D-012 status is now: Superseded by D-037.

**Decision:** Data Sports Group (DSG) is the confirmed provider for RugbyDraft V1.

| Property   | Value                                                 |
| ---------- | ----------------------------------------------------- |
| Base URL   | https://dsg-api.com/clients/jeremym/rugby/            |
| V1 price   | €125/month — Six Nations + Top 14                     |
| V2 add-on  | +€100/month — Premiership, Super Rugby, Champions Cup |
| Trial      | 2 weeks (activated 2026-03-21)                        |
| Rate limit | 10,000 calls/hour — no management needed in V1        |
| Contact    | Rajesh D'Souza — rajesh@datasportsgroup.com           |

**Impact on cost model:** Fixed infrastructure costs rise from ~€30/month to ~€143/month.
Break-even threshold revised to ~100 paying subscribers (mix 70% Pro / 30% Pro+AI).
Ulule campaign target revised to €3,000 minimum (18 months runway at zero subscribers).
V2 competitions will only be activated when subscriber base justifies +€100/month add-on
(estimated threshold: ~160 paying subscribers).

**Rationale:** No alternative at an accessible price point. Statscore: €1,000/month minimum.
Sportradar: enterprise tier only. DSG is the sole viable option confirmed to provide
player-level stats for Six Nations + Top 14 at indie startup pricing.

---

## D-038 — Scoring system revision following DSG coverage mapping

**Date:** 2026-03-23
**Status:** Superseded by D-039 (2026-03-23)

**Context:** Phase 0 DSG validation confirmed which stats are available.
Two stats from the original scoring system (CDC v3.1 section 6) are absent from DSG.
Four additional stats available in DSG were not in the original system.

**Decision:**

Removed (not available in DSG):

- 50/22 kicks (+2 pts) — `dsg field: none`
- Dominant tackles (+1 pt) — `dsg field: none`

Added (available in DSG, improve differentiation):

- Missed tackle (-0.5 pts) — `dsg field: missed_tackles`
- Handling error (-0.5 pts) — `dsg field: handling_error`
- Line break (+1 pt) — `dsg field: line_breaks`
- Catch from kick (+0.5 pts) — `dsg field: catch_from_kick`

All four added stats use `COALESCE(stat, 0)` in dbt (conditional stats — may be absent
from API response on low-activity matches).

**Rationale:**

- 50/22 is rare (1–2 per match maximum), creates minimal differentiation, and is absent from DSG.
- Dominant tackles are a derived/subjective stat, not tracked individually by DSG.
- Missed tackles penalise poor defenders — strategically meaningful, well-represented per match.
- Handling errors penalise sloppy ball carriers — balances the offload bonus.
- Line breaks reward incisive ball carriers — particularly differentiating for backs.
- Catch from kick rewards fullbacks and wingers under pressure — fills a gap for positional identity.
- Net effect: more granular differentiation between positions, especially backs vs forwards.

**Files impacted:** `dbt/models/gold/mart_fantasy_points.sql`,
`CONTEXT.md` (scoring summary section), `docs/cdc_v31.md` (section 6).

---

---

## D-039 — Scoring system final revision (supersedes D-038)

**Date:** 2026-03-23
**Status:** Accepted

**Context:** After full analysis of the DSG raw XML response (match 3798425,
Clermont vs Toulouse), several scoring rules from D-038 required further
revision: missing DSG fields confirmed absent, new fields discovered,
and game-design adjustments made to balance positional identity.

**Changes from D-038:**

Removed:

- Offload (+1) — `offloads` field absent from DSG `player_stats` node
- Drop goal (+3) — `try_kicks` confirmed as kick assist, not drop goal
- Conversion missed (-0.5) — no `goals_attempted` field in DSG; missed kicks cannot be calculated
- Penalty missed (-1) — same reason as above

Added:

- Kick assist (+1) — `try_kicks` field confirmed as kick leading directly to a try
- Lineout lost (-0.5) — `lineouts_lost` field present in DSG schema (COALESCE — may be empty)
- Turnovers conceded (-0.5) — `turnovers_conceded` field confirmed present

Revised values:

- Turnover won: +2 (confirmed, was ambiguous in D-038)
- Line break: +1 (was +0.5 in D-038 — increased for positional differentiation)
- Penalty kick made: formula revised — `goals - conversion_goals` gives penalty
  kicks made (DSG `goals` = all successful kicks at goal)

Revised rules:

- Lineout won/lost: attributed to the **thrower** (any position), not restricted
  to starting hooker. DSG already attributes `lineouts_won`/`lineouts_lost` to
  the throwing player. A quick throw by a back is legitimately credited.

**Final scoring table:**

| Action                | Points | DSG field                 | Applies to            |
| --------------------- | ------ | ------------------------- | --------------------- |
| Metre carried (per m) | +0.1   | carries_metres            | All                   |
| Try scored            | +5     | scores (event type="try") | All                   |
| Try assist            | +2     | try_assists               | All                   |
| Turnover won          | +2     | turnover_won              | All                   |
| Line break            | +1     | line_breaks               | All                   |
| Kick assist           | +1     | try_kicks                 | All                   |
| Catch from kick       | +0.5   | catch_from_kick           | All                   |
| Tackle                | +0.5   | tackles                   | All                   |
| Lineout won           | +1     | lineouts_won              | Thrower (all)         |
| Lineout lost          | -0.5   | lineouts_lost             | Thrower (all)         |
| Turnovers conceded    | -0.5   | turnovers_conceded        | All                   |
| Missed tackle         | -0.5   | missed_tackles            | All                   |
| Handling error        | -0.5   | handling_error            | All                   |
| Penalty conceded      | -1     | penalties_conceded        | All                   |
| Yellow card           | -2     | bookings (yellow_card)    | All                   |
| Red card              | -3     | bookings (red_card)       | All                   |
| Conversion made       | +2     | conversion_goals          | Kicker only           |
| Penalty kick made     | +3     | goals - conversion_goals  | Kicker only           |
| Captain multiplier    | ×1.5   | —                         | Captain (nearest 0.5) |

Conditional stats (COALESCE to 0 if absent from API response):
`line_breaks`, `catch_from_kick`, `lineouts_won`, `lineouts_lost`,
`try_kicks`, `handling_error`, `turnovers_conceded`

**Files impacted:**

- `dbt_project/models/gold/mart_fantasy_points.sql`
- `CONTEXT.md` (scoring summary section)
- `docs/dsg_api_reference.md` (section 6 — field mapping)
- `docs/cdc_v31.md` (section 6 — scoring rules)

---

## D-040 — Draft Room: currentUserId passed as prop from Server Component

**Date:** 2026-03-24
**Status:** Accepted

**Context:** The Draft Room (`DraftRoom.tsx`) is a Client Component that needs
the authenticated user's UUID to compute `isMyTurn` and `isAutodraftActive`.
Three options were considered.

**Options considered:**

- A) Pass `currentUserId` as prop from the Server Component page (`page.tsx`).
- B) Hook `useUser()` calling `supabase.auth.getUser()` client-side on mount.
- C) React Context Provider (`AuthProvider`) wrapping the protected layout.

**Decision:** Option A — prop from Server Component.

**Rationale:**

- The page Server Component already calls `supabase.auth.getUser()` for the
  session check. Passing `user.id` as a prop costs zero extra requests.
- Option B would trigger an extra client-side network call on every Draft Room
  mount — unnecessary latency in a latency-sensitive UI.
- Option C is overkill for V1 — only one Client Component currently needs the
  user ID. Can migrate to Context if more components require it.

**Consequences:**

- `user.id` is visible in React DevTools props — acceptable (UUID is not secret).
- If other Client Components need the user ID, add a Context Provider at that point.

---

## D-041 — POST /draft/{league_id}/pick endpoint added in Phase 4

**Date:** 2026-03-24
**Status:** Accepted

**Context:** The `DraftEngine.submit_pick()` method existed since Phase 2 but
had no HTTP endpoint. The Draft Room frontend required this endpoint to submit
manual picks.

**Decision:** Added `POST /draft/{league_id}/pick` to `backend/app/routers/draft.py`.

**Error mapping:**

- `NotYourTurnError` → HTTP 409 Conflict
- `PlayerAlreadyDraftedError` → HTTP 409 Conflict
- `PickValidationError` → HTTP 422 Unprocessable Entity

**Consequences:**

- The endpoint returns the full updated `DraftStateSnapshotResponse` — the client
  gets the new state immediately without waiting for the Realtime broadcast.
  (Belt-and-suspenders: Realtime also broadcasts, but the HTTP response is faster.)

---

## D-042 — Roster page: single atomic POST for all lineup changes

**Date:** 2026-03-24
**Status:** Accepted

**Context:** The roster management page allows multiple simultaneous changes
in one editing session: captain designation, kicker designation, position
overrides for multi-position players, and starter ↔ bench swaps. The question
was whether to use one endpoint per action type or a single consolidated POST.

**Options considered:**

- A) One endpoint per action: `PATCH /lineup/captain`, `PATCH /lineup/kicker`,
  `POST /lineup/swap`, `PATCH /lineup/position`
- B) Single atomic POST: `POST /lineup/{leagueId}/update` with a
  `LineupUpdatePayload` containing all change types in one request.

**Decision:** Option B — single atomic POST.

**Rationale:**

- Prevents race conditions if the user makes rapid successive changes
  (e.g. captain change + position override within the same render cycle).
- The backend validates the entire payload before committing any change —
  partial failure is impossible.
- Simpler frontend state: one `isSaving` flag, one optimistic update,
  one rollback path.
- Fewer HTTP round trips.

**Consequences:**

- `LineupUpdatePayload` carries all change types. Fields not being changed
  are sent as null / empty arrays — the backend ignores them.
- The backend `POST /lineup/{leagueId}/update` must validate each field
  independently and return the full confirmed `WeeklyLineupResponse`.

---

## D-043 — Sidebar hydration: useEffect init pattern replacing lazy useState

**Date:** 2026-03-24
**Status:** Accepted

**Context:** `Sidebar.tsx` persists collapsed state in localStorage. The
original implementation used a lazy `useState` initializer that called
`localStorage` directly — this caused a hydration mismatch under
Next.js 15 / Turbopack because the lazy initializer runs during SSR
where `localStorage` is undefined.

**Decision:** Replace lazy initializer with `useState<boolean | null>(null)`

- `useEffect` that reads localStorage once after mount. `null` means
  "not yet mounted" — renders a same-width placeholder div instead of the
  real sidebar until localStorage is read.

**Rationale:**

- `useEffect` is guaranteed to run only on the client, never during SSR.
- The placeholder div has the same width as the default expanded sidebar
  (`w-60`) — no layout shift on first paint.
- `isCollapsed === null` replaces a separate `mounted` boolean flag —
  one piece of state instead of two.

**Consequences:**

- Any component that reads browser-only APIs (localStorage, sessionStorage,
  window) must follow this same pattern: `useState(null)` + `useEffect` init.
- The sidebar flashes its placeholder for one frame on cold load if the
  user had it collapsed — imperceptible in practice.
