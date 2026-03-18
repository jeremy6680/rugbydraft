# KNOWN_BUGS.md — RugbyDraft

> Created when needed, removed when empty.
> Last updated: 2026-03-18

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
