# RugbyDraft

A fantasy rugby platform with a **snake draft system**, playable between
friends on major international and club competitions.

Unlike existing fantasy games, each player can only belong to one roster
per league — the draft guarantees exclusivity. Points are calculated from
real match statistics via an external API.

**Domain:** [rugbydraft.app](https://rugbydraft.app) _(coming soon)_

---

## Stack

| Layer         | Technology                                            |
| ------------- | ----------------------------------------------------- |
| Frontend      | Next.js 15 (App Router) + Tailwind CSS v4 + shadcn/ui |
| Backend       | FastAPI (Python)                                      |
| Database      | PostgreSQL via Supabase (Auth + Realtime)             |
| Data pipeline | DuckDB + dbt Core (medallion architecture)            |
| Orchestration | Airflow (post-match pipeline) + Coolify cron          |
| i18n          | next-intl — French (V1), English (V2)                 |
| Infra         | Hetzner CPX21 + Coolify + Docker Compose              |
| CI/CD         | GitHub Actions                                        |

---

## Architecture highlights

- **FastAPI is the authority of state for the snake draft.**
  Supabase Realtime is a broadcast channel only — never a source of truth.
- **Connector-agnostic data pipeline** via `BaseRugbyConnector`.
  Switching rugby data providers requires changing one file and one
  environment variable.
- **Medallion architecture** (bronze → silver → gold) with atomic commit
  pattern for fantasy scores.
- **i18n-ready from day one** — zero hardcoded UI strings, next-intl
  configured in Phase 1.

---

## Project structure

See [STRUCTURE.md](./STRUCTURE.md) for a detailed explanation of the
repository layout.

---

## Documentation

| File                             | Purpose                                        |
| -------------------------------- | ---------------------------------------------- |
| [CONTEXT.md](./CONTEXT.md)       | Project overview, stack, key decisions summary |
| [DECISIONS.md](./DECISIONS.md)   | Architectural decisions log                    |
| [NEXT_STEPS.md](./NEXT_STEPS.md) | Phase-by-phase development checklist           |
| [STRUCTURE.md](./STRUCTURE.md)   | Repository structure explained                 |

---

## Development status

| Phase   | Description    | Status         |
| ------- | -------------- | -------------- |
| Phase 0 | API validation | ✅ Complete    |
| Phase 1 | Foundations    | 🟡 In progress |
| Phase 2 | Draft engine   | ⬜ Not started |
| Phase 3 | Gameplay       | ⬜ Not started |
| Phase 4 | Frontend MVP   | ⬜ Not started |

---

## Getting started

_Setup instructions will be added as the project progresses._

---

## License
