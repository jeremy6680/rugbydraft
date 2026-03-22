# KNOWN_BUGS.md — RugbyDraft

> Created when needed, removed when empty.
> Last updated: 2026-03-19

---

## KB-001 — dbt 1.11.7 false deprecation warning on `accepted_values`

**Status:** Known / ignored
**Affects:** `dbt test` output only — no functional impact
**Symptom:** `MissingArgumentsPropertyInGenericTestDeprecation` warning on
`accepted_values` tests in `models/schema.yml`, even though the syntax is correct
for dbt 1.11.
**Root cause:** Bug in dbt-duckdb 1.10.1 / dbt-core 1.11.7 interaction.
The warning fires incorrectly — tests pass (PASS=29).
**Workaround:** None needed. Tests are valid and passing.
**Fix:** Will resolve on dbt-core or dbt-duckdb upgrade.

---

## KB-002 — Next.js 16: `middleware.ts` convention deprecated in favour of `proxy.ts`

**Status:** Known / deferred to Phase 2
**Affects:** Build output warning only — middleware functions correctly
**Symptom:** Build warning:
`⚠ The "middleware" file convention is deprecated. Please use "proxy" instead.`
**Root cause:** Next.js 16 renamed the middleware file convention from
`middleware.ts` to `proxy.ts`. The existing file still works but triggers
a deprecation warning on every build and in CI logs.
**Workaround:** None needed. All route protection and session refresh logic
functions correctly.
**Fix:** Before Phase 2, rename `frontend/src/middleware.ts` → `frontend/src/proxy.ts`
and verify all imports and the `matcher` export still work correctly.

---

## BUG-003 — test_health.py fails without Supabase env vars + Settings mismatch

**Discovered:** 2026-03-21
**Status:** Open — non-blocking for Phase 2
**Affects:** `backend/tests/test_health.py` (collection error)

### Symptoms

Running `pytest backend/` fails at collection with two distinct errors:

1. `ValidationError` — required fields missing: `supabase_url`,
   `supabase_anon_key`, `supabase_service_role_key`, `supabase_jwt_secret`,
   `database_url`. pytest does not auto-load `.env` — these vars are absent
   when running tests locally without explicit env injection.

2. `extra_forbidden` — fields present in `.env` but removed from `Settings`:
   `api_host`, `api_port`, `app_env`, `duckdb_path`. The `Settings` model
   uses `model_config = {"extra": "forbid"}` — any unknown field crashes
   at import time.

### Root cause

- `app/config.py` instantiates `settings = get_settings()` at **module level**
  (line 111). Any import of `app.config` in a test triggers the full
  `Settings()` constructor, which requires all env vars to be present.
- `.env` contains variables that were removed from `Settings` at some point
  but never cleaned up.

### Fix (Phase 3 or before first deploy)

Two independent fixes needed:

1. **pytest env loading** — add `pytest-dotenv` or a `conftest.py` fixture
   that loads `.env.test` before collection. This is the standard pattern
   for FastAPI + pydantic-settings projects.

2. **Settings / .env sync** — remove `api_host`, `api_port`, `app_env`,
   `duckdb_path` from `.env` (or re-add them to `Settings` if they are
   still needed).

### Workaround

Run draft tests directly — they do not import `app.config`:

```bash
pytest backend/tests/draft/ backend/tests/test_reconnection.py -v
```

---

## KB-004 — Waiver cycle: roster writes are not atomic (no PostgreSQL transaction)

**Status:** Known / acceptable for V1
**Affects:** `waiver_service._apply_granted_claim()`

Three sequential Supabase writes (delete drop_player, insert add_player,
update waiver status) are not wrapped in a single PostgreSQL transaction.
A failure between writes would leave the roster in an inconsistent state.

**Fix:** Implement a PostgreSQL RPC function `apply_granted_waiver(waiver_id)`
that wraps all three writes in a single transaction. Deferred to Phase 4
when DB RPC functions are introduced.

---

## KB-005 — `_player_is_free` does not filter by league_id correctly

**Status:** Known / acceptable for V1
**Affects:** `waiver_service._player_is_free()`

The current implementation queries `roster_slots` without joining through
`rosters` to filter by `league_id`. A player could be flagged as "not free"
if they appear in a roster of a different league.

**Fix:** Replace with a Supabase RPC call or a raw SQL query that joins
`roster_slots → rosters` and filters on `rosters.league_id`. Deferred to
Phase 4.

---

## KB-006 — \_apply_completed_trade() is not atomic

**Status:** Known / acceptable for V1
**Affects:** `trade_service._apply_completed_trade()`

Multiple sequential Supabase writes (one per player entry) are not wrapped
in a single PostgreSQL transaction. A failure mid-way would leave some
players transferred and others not.

**Fix:** Implement a PostgreSQL RPC function `apply_completed_trade(trade_id)`
that wraps all roster_slots updates in a single transaction. Deferred to
Phase 4 alongside KB-004 (waiver atomic fix).

---

## LIMITATION-001 — FastAPI restart mid-draft causes full state loss

**Discovered:** 2026-03-21
**Status:** Open — accepted for Phase 2, must be fixed before Phase 3 beta

**Description:** DraftEngine state is in-memory only. A FastAPI restart
(crash, deploy, OOM) during a live draft loses timer state, autodraft
state, and connected manager set. Picks already recorded in `draft_picks`
are safe.

**Recovery:** Commissioner switches to Assisted Draft manually (CDC 7.5).
Full procedure documented in DECISIONS.md D-028.

**Blockers before fix:**

- `drafts.manager_order` JSONB column missing from schema (migration needed)
- `reconstruct_engine_from_db()` not yet implemented in `DraftRegistry`

**Target:** Phase 3 — before first real draft.
