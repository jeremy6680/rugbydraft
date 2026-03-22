# Makefile — RugbyDraft development shortcuts
# Run from the repo root.

.PHONY: lint format test test-draft test-waivers ci

# ── Lint + format (run before every commit) ──────────────────────────────────

lint:
	ruff check backend/ connectors/ scripts/ --fix
	ruff format backend/ connectors/ scripts/

format: lint

# ── Tests ─────────────────────────────────────────────────────────────────────

test-draft:
	pytest backend/tests/draft/ backend/tests/test_reconnection.py -v --tb=short

test-waivers:
	pytest backend/tests/test_waivers.py -v --tb=short

test:
	pytest backend/tests/draft/ backend/tests/test_reconnection.py backend/tests/test_waivers.py -v --tb=short

# ── Full CI check (mirrors GitHub Actions) ───────────────────────────────────

ci:
	ruff check backend/ connectors/ scripts/
	ruff format --check backend/ connectors/ scripts/
	pytest backend/tests/draft/ backend/tests/test_reconnection.py backend/tests/test_waivers.py --tb=short -q