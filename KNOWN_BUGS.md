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
**Update 2026-03-23:** confirmed this bug produces invalid SQL (`not in ()`)
in some dbt-duckdb versions, causing test failures — not just warnings.
Fixed by removing the `config:` wrapper from all `accepted_values` tests
in `schema.yml`. Use `values:` directly under `accepted_values:`.

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

## KB-007 — IR endpoints have no integration tests

**Status:** Known / acceptable for V1
**Affects:** `app/routers/infirmary.py` — PUT /ir/place, PUT /ir/reintegrate, GET /ir/alerts

The three infirmary endpoints are covered by unit tests on the pure rules
(test_infirmary.py, 26 tests) but have no integration tests mocking the
Supabase client. Manual testing was not performed due to missing seed data.

**Fix:** Add integration tests with a mocked AsyncClient before Phase 4.
Same pattern as KB-004 and KB-006.

---

## KB-008 — Silver models not yet updated for DSG field mapping (scoring v2)

**Status:** ✅ Resolved — 2026-03-23
**Resolution:** `connectors/dsg.py` implemented. DSGConnector parses DSG XML
responses and maps all field names to the `PlayerMatchStats` contract.
`connectors/tests/test_dsg_connector.py` — 33 tests passing.
The silver model `stg_match_stats.sql` references DSG field names that are
now correctly produced by the DSG connector.

---

## KB-009 — FastAPI JWT middleware uses HS256, Supabase project uses ES256

**Status:** ✅ Resolved — 2026-03-30
**Affects:** `app/middleware/auth.py`

**Symptom:** All protected FastAPI endpoints returned HTTP 401 in local dev.
Token header confirmed `alg: ES256` but middleware hardcoded `JWT_ALGORITHM = "HS256"`.

**Root cause:** Supabase changed the default JWT signing algorithm to ES256
for projects created after mid-2024. ES256 requires JWKS public key verification,
not a symmetric secret.

**Fix applied:**

- `app/middleware/auth.py` rewritten — ES256 path fetches the Supabase JWKS
  public key from `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`, caches it
  in memory, refreshes on signature failure (key rotation). HS256 path preserved
  as opt-in via `SUPABASE_JWT_ALGORITHM=HS256`.
- `app/config.py` — `supabase_jwt_algorithm` field added (default: `ES256`).
- `.env.example` — `SUPABASE_JWT_ALGORITHM=ES256` documented.
- `backend/tests/test_auth.py` — 8 new tests (ES256 valid/invalid/expired/JWKS
  failure/key rotation, HS256 valid/invalid/expired). All passing.

---

## KB-010 — export_silver_to_pg.py: pandas incompatible with SQLAlchemy 2.x

**Status:** ✅ Resolved — 2026-03-29
**Affects:** `scripts/export_silver_to_pg.py`

**Symptom:** `'Engine' object has no attribute 'cursor'` / `'Connection' object
has no attribute 'cursor'` on every table export. All tables fail, verification
reports stale row counts from previous run.

**Root cause:** pandas `to_sql()` dropped support for raw SQLAlchemy Engine/Connection
objects in versions that predate SQLAlchemy 2.x compatibility. The installed pandas
version treated the SQLAlchemy object as a DBAPI2 connection and failed.

**Fix:** Replaced pandas `to_sql()` + SQLAlchemy entirely with `psycopg2` direct
connection + `cur.copy_expert()` (COPY FROM STDIN CSV). Faster, zero version
dependency, schema always rebuilt from DuckDB silver on each run (DROP + CREATE TEXT).

**Secondary fix:** All `pipeline_stg_*` columns are now TEXT in PostgreSQL.
Gold models that read from these tables must cast numeric columns explicitly,
e.g. `ms.tries::integer`. `is_first_match_of_round` must be compared as
`= 'true'` (string), not `= true` (boolean).

**Also fixed:** `DUCKDB_PATH` in `.env` was set to `../data/rugbydraft.duckdb`
(relative to `dbt_project/`) — corrected to `data/rugbydraft.duckdb`
(relative to project root, the only valid launch directory).

---

## KB-011 — leagues.py and stats.py use sync .execute() on AsyncClient

**Date:** 2026-04-02
**Severity:** Latent — will crash when called with real data

**Context:** `get_supabase_client()` returns an `AsyncClient` (via `acreate_client`).
All `.execute()` calls on `AsyncClient` must be awaited. `dashboard.py` was fixed.
`leagues.py` and `stats.py` still call `.execute()` without `await`.

**Impact:** These endpoints will raise `AttributeError: 'coroutine' object has no
attribute 'data'` when called with a real authenticated session.

**Fix:** Add `await` before every `.execute()` call in both files. Same pattern
applied in `dashboard.py`.

**Priority:** Fix before testing leaderboard or stats pages with real data.

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
