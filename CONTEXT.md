# CONTEXT.md — RugbyDraft

> Source of truth: `docs/cdc_v3.1.docx` (confidential, gitignored)
> Last updated: 2026-03-18

---

## What is RugbyDraft?

RugbyDraft is a fantasy rugby platform with a **snake draft system**, playable between friends on major international and club competitions. Unlike existing games (Six Nations Fantasy, etc.), each player can only belong to one roster per league — the draft guarantees exclusivity.

Points are calculated from real match stats via an external API. A premium feature offers an AI coaching staff (CrewAI) that analyses the past week and recommends the lineup for the coming weekend.

**Domain:** rugbydraft.app (rugbydraft.com is taken — code name kept for now)

---

## Business model

| Plan     | Monthly      | Annual       | Access                                                                                                         |
| -------- | ------------ | ------------ | -------------------------------------------------------------------------------------------------------------- |
| Free     | 0 €          | 0 €          | Six Nations + Top 14. Unlimited leagues as manager. Commissioner on 1 active league max.                       |
| Pro      | 2,99 €/month | 24,99 €/year | All Free + Rugby Championship, Premiership, Super Rugby Pacific. Unlimited commissioner leagues. 2-week trial. |
| Pro + AI | 3,99 €/month | 34,99 €/year | All Pro + AI Coaching Staff on 1 league of choice (Tuesday + Thursday reports).                                |

**Break-even:** revised — see DECISIONS.md D-013 (DSG pricing impact).

> DSG confirmed at €125/month (Six Nations + Top 14). V2 add-on: +€100/month for Rugby Championship, Premiership,
> Super Rugby Pacific. This significantly raises the break-even threshold.
> See financial validation below.

---

## Tech stack

| Layer             | Technology                                                            |
| ----------------- | --------------------------------------------------------------------- |
| Frontend          | Next.js 15 (App Router) + Tailwind CSS v4 + shadcn/ui + Framer Motion |
| i18n              | next-intl — V1 FR only, i18n-ready from Phase 1                       |
| Backend           | FastAPI (Python) — **authority of state for the draft**               |
| Database          | PostgreSQL via Supabase cloud (Auth + Realtime WebSocket)             |
| Realtime          | Supabase Realtime — broadcast channel only, not source of truth       |
| Data pipeline     | DuckDB + dbt Core (medallion: bronze/silver/gold)                     |
| Orchestration     | Airflow (post_match_pipeline only) + Cron Coolify (daily tasks)       |
| Rugby data source | DSG                                                                   |
| AI Staff          | CrewAI + Claude API claude-sonnet-4-5 (private repo)                  |
| Payments          | Stripe — monthly cancellable or annual (private repo)                 |
| Infra             | Hetzner CPX21 (8 GB RAM) + Coolify + Docker Compose                   |
| CI/CD             | GitHub Actions — ruff + pytest + axe-core + TS lint                   |

---

## Repositories

| Repo                            | Visibility | Contents                                                    |
| ------------------------------- | ---------- | ----------------------------------------------------------- |
| `jeremy6680/rugbydraft`         | Public     | Data pipeline, draft engine, scoring, frontend, tests, docs |
| `jeremy6680/rugbydraft-private` | Private    | Stripe, Staff IA CrewAI, Airflow IA DAGs, prod infra        |

**Gitignored on public repo:** `docs/cdc*.md`, `docs/cdc*.docx`, `.env*` (except `.env.example`)

---

## Competitions

### V1 — Free

- Six Nations (international, 6 teams, 2–6 managers)
- Top 14 (club, 14 teams, 2–14 managers)

### V2 — Pro

- Super Rugby (club, 11 teams, 2-10 managers)
- Rugby Championship (international, 4 teams, 2–4 managers)
- Premiership (club, 10 teams, 2-4 managers)

### V2 — Pro + AI

- No other competition

**Architecture:** `competition_type` = `international` (nationality constraint) or `club` (club constraint). Adding a competition never requires modifying business logic.

> **Phase 0 finding:** API-Sports Rugby does not provide player-level match statistics. Provider selection is in progress (Statscore, DSG contacted; Sportradar trial available). See DECISIONS.md D-012. This does not block Phase 1.

---

## Scoring system (summary)

**Attack:** +0.1/metre carried, +1 kick assist, +2 try assist, +5 try,
+1 line break, +0.5 catch from kick, +2 conversion made (kicker only),
+3 penalty kick made (kicker only).

**Defence:** +0.5 tackle, +2 turnover won, +1 lineout won (thrower),
-0.5 lineout lost (thrower), -0.5 missed tackle, -0.5 turnovers conceded,
-0.5 handling error, -1 penalty conceded, -2 yellow card, -3 red card.

**Captain:** ×1.5 multiplier (rounded up to nearest 0.5), applied after all points calculated.

Conditional stats use `COALESCE(stat, 0)` in dbt:
`line_breaks`, `catch_from_kick`, `lineouts_won`, `lineouts_lost`,
`try_kicks`, `handling_error`, `turnovers_conceded`.

> Provider confirmed: **Data Sports Group (DSG)** — €125/month for Six Nations + Top 14.
> Extra €100/month for Super Rugby, Premiership, Champions Cup (V2).
> Scoring system v2 finalized on 2026-03-23. See DECISIONS.md D-039 and docs/dsg_api_reference.md.

---

## Key architectural decisions (summary)

See `DECISIONS.md` for full rationale.

- **FastAPI is the authority of state for the draft.** Supabase Realtime is a broadcast channel only.
- **Airflow only for `post_match_pipeline`.** Daily tasks use Cron Coolify / APScheduler.
- **Staging → atomic commit** for fantasy_scores: scores are written to `fantasy_scores_staging` first, then committed in a single PostgreSQL transaction.
- **Rugby data source is DSG** (D-037). Architecture is connector-agnostic via `BaseRugbyConnector`. API-Sports ruled out — no player-level stats. Scoring system v2 finalized — see D-039.
- **next-intl from Phase 1**, FR only in V1 — zero hardcoded UI strings allowed.
- **Language and competition access are independent dimensions.** Locale = display preference. Competitions = accessible by plan (Free/Pro), not by language.

---

## Roadmap summary

| Phase                       | Estimated duration | Status                                            |
| --------------------------- | ------------------ | ------------------------------------------------- |
| Phase 0 — API validation    | 3–5 days           | ✅ Complete — DSG confirmed, scoring v2 finalized |
| Phase 1 — Foundations       | 2–3 weeks          | ✅ Complete                                       |
| Phase 2 — Draft engine      | 3–4 weeks          | ✅ Complete                                       |
| Phase 3 — Gameplay          | 2–3 weeks          | ✅ Complete                                       |
| Phase 4 — Frontend MVP      | 3–4 weeks          | 🟡 Ready to start                                 |
| Phase 5 — Premium (private) | 2–3 weeks          | 🔴 Not started                                    |
| Phase 6 — Top 14 & polish   | 2 weeks            | 🔴 Not started                                    |
| Phase 7 — EN (V2)           | TBD                | 🔵 Future                                         |
| Phase 8 — ES/IT (V3)        | TBD                | 🔵 Future                                         |

**Total estimated V1:** 16–20 weeks solo. MVP (Phase 1–4): ~10 weeks.

---

## Project conventions

- **Language:** all code, comments, identifiers and documentation in English.
- **Git:** one branch per phase/feature, Conventional Commits (`feat(scope): description`).
- **Code style:** Black + Ruff (Python), Prettier (TS/JS), type hints everywhere, Google-style docstrings.
- **Tests:** pytest (Python) + axe-core (accessibility). Draft engine and scoring tests are mandatory — PRs cannot be merged if they fail.
- **Accessibility:** WCAG 2.1 AA minimum, axe-core in CI.
- **Living docs:** `CONTEXT.md`, `DECISIONS.md`, `NEXT_STEPS.md`, `STRUCTURE.md` — updated at each phase.

---

## Claude Desktop project prompt

> You are the development assistant for RugbyDraft (rugbydraft.app), a fantasy rugby app with snake draft. The reference document is docs/cdc_v3.1.docx (confidential). Key architectural principle: FastAPI is the authority of state for the draft — Supabase Realtime is a broadcast channel only. Stack: Next.js 15 + FastAPI + PostgreSQL (Supabase) + DuckDB + dbt + Airflow + CrewAI. Rugby data source: TBD (API-Sports ruled out — no player-level stats). Architecture uses BaseRugbyConnector abstraction — provider swap = one file + one env variable. Solo developer. Follow CONTEXT.md, DECISIONS.md, NEXT_STEPS.md as living documentation. All code and comments in English.
