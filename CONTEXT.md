# CONTEXT.md — RugbyDraft

> Source of truth: `docs/cdc_v3.1.docx` (confidential, gitignored)
> Last updated: 2026-03-16

---

## What is RugbyDraft?

RugbyDraft is a fantasy rugby platform with a **snake draft system**, playable between friends on major international and club competitions. Unlike existing games (Six Nations Fantasy, etc.), each player can only belong to one roster per league — the draft guarantees exclusivity.

Points are calculated from real match stats via an external API. A premium feature offers an AI coaching staff (CrewAI) that analyses the past week and recommends the lineup for the coming weekend.

**Domain:** rugbydraft.app (rugbydraft.com is taken — code name kept for now)

---

## Business model

| Plan | Monthly | Annual | Access |
|---|---|---|---|
| Free | 0 € | 0 € | International competitions (Six Nations, Rugby Championship, Nations Championship). Unlimited leagues as manager. Commissioner on 1 active league max. |
| Pro | 2 €/month | 18 €/year | All Free + national/continental competitions (Top 14 V1, Premiership, Super Rugby, Champions Cup V2+). Unlimited commissioner leagues. 4-week free trial. |
| Pro+IA | 3 €/month | 25 €/year | All Pro + CrewAI Staff IA on 1 league of choice (Tuesday + Thursday reports). |

**Break-even:** ~28 Pro+IA subscribers (mix 40% monthly / 60% annual).

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 15 (App Router) + Tailwind CSS v4 + shadcn/ui + Framer Motion |
| i18n | next-intl — V1 FR only, i18n-ready from Phase 1 |
| Backend | FastAPI (Python) — **authority of state for the draft** |
| Database | PostgreSQL via Supabase cloud (Auth + Realtime WebSocket) |
| Realtime | Supabase Realtime — broadcast channel only, not source of truth |
| Data pipeline | DuckDB + dbt Core (medallion: bronze/silver/gold) |
| Orchestration | Airflow (post_match_pipeline only) + Cron Coolify (daily tasks) |
| AI Staff | CrewAI + Claude API claude-sonnet-4-5 (private repo) |
| Payments | Stripe — monthly cancellable or annual (private repo) |
| Infra | Hetzner CPX21 (8 GB RAM) + Coolify + Docker Compose |
| CI/CD | GitHub Actions — ruff + pytest + axe-core + TS lint |

---

## Repositories

| Repo | Visibility | Contents |
|---|---|---|
| `jeremy6680/rugbydraft` | Public | Data pipeline, draft engine, scoring, frontend, tests, docs |
| `jeremy6680/rugbydraft-private` | Private | Stripe, Staff IA CrewAI, Airflow IA DAGs, prod infra |

**Gitignored on public repo:** `docs/cdc*.md`, `docs/cdc*.docx`, `.env*` (except `.env.example`)

---

## Competitions

### V1 — Free (international)
- Six Nations (6 teams, 2–6 managers)
- Rugby Championship (4 teams, 2–4 managers) — *if API stats OK*
- Nations Championship (12+ teams, 2–12 managers) — *if API stats OK*

### V1 — Pro (club)
- Top 14 (phase régulière)

### V2 — Pro (club)
- Premiership, Champions Cup, Super Rugby Pacific

**Architecture:** `competition_type` = `international` (nationality constraint) or `club` (club constraint). Adding a competition never requires modifying business logic.

> **BLOCKING prerequisite before any development:** manually test API-Sports Standard on the current Six Nations. Verify field by field: tackles, turnovers, metres, try assists. If key stats are systematically missing, revise the scoring system before coding.

---

## Scoring system (summary)

**Attack:** +0.1/metre, +1 offload, +2 try assist, +5 try, +3 drop (all starters), +2 conversion made / -0.5 missed (kicker only), +3 penalty made / -1 missed (kicker only), +2 50/22 (if API).

**Defence:** +0.5 tackle, +1 dominant tackle (if API), +2 turnover, +2 lineout steal (if API), -1 penalty conceded, -2 yellow card, -3 red card.

**Captain:** ×1.5 multiplier (rounded up to nearest 0.5), applied after all points calculated.

Conditional stats use `COALESCE(stat, 0)` in dbt — auto-activated on API upgrade.

---

## Key architectural decisions (summary)

See `DECISIONS.md` for full rationale.

- **FastAPI is the authority of state for the draft.** Supabase Realtime is a broadcast channel only.
- **Airflow only for `post_match_pipeline`.** Daily tasks use Cron Coolify / APScheduler.
- **Staging → atomic commit** for fantasy_scores: scores are written to `fantasy_scores_staging` first, then committed in a single PostgreSQL transaction.
- **API-Sports Standard from day one** (never the free tier — 100 req/day is insufficient for a weekend of matches).
- **next-intl from Phase 1**, FR only in V1 — zero hardcoded UI strings allowed.
- **Language and competition access are independent dimensions.** Locale = display preference. Competitions = accessible by plan (Free/Pro), not by language.

---

## Roadmap summary

| Phase | Estimated duration | Status |
|---|---|---|
| Phase 0 — API validation | 3–5 days | 🔴 Not started — BLOCKING |
| Phase 1 — Foundations | 2–3 weeks | 🔴 Not started |
| Phase 2 — Draft engine | 3–4 weeks | 🔴 Not started |
| Phase 3 — Gameplay | 2–3 weeks | 🔴 Not started |
| Phase 4 — Frontend MVP | 3–4 weeks | 🔴 Not started |
| Phase 5 — Premium (private) | 2–3 weeks | 🔴 Not started |
| Phase 6 — Top 14 & polish | 2 weeks | 🔴 Not started |
| Phase 7 — EN (V2) | TBD | 🔵 Future |
| Phase 8 — ES/IT (V3) | TBD | 🔵 Future |

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

> You are the development assistant for RugbyDraft (rugbydraft.app), a fantasy rugby app with snake draft. The reference document is docs/cdc_v3.1.docx (confidential). Key architectural principle: FastAPI is the authority of state for the draft — Supabase Realtime is a broadcast channel only. Stack: Next.js 15 + FastAPI + PostgreSQL (Supabase) + DuckDB + dbt + Airflow + CrewAI. Solo developer. Follow CONTEXT.md, DECISIONS.md, NEXT_STEPS.md as living documentation. All code and comments in English.
