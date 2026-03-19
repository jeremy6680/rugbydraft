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
