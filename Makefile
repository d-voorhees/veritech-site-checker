SHELL := /bin/bash

# Path to the Python virtualenv used for API/runner commands. Defaults to a
# local dev venv (see README.md's "Local setup").
VENV ?= apps/api/.venv
PYTHON := $(abspath $(VENV))/bin/python
ALEMBIC := $(abspath $(VENV))/bin/alembic

.PHONY: dev test lint migrate seed fly-init fly-deploy fly-migrate fly-status fly-logs fly-scan-runner-test

## Local development (native, no Docker, no Redis) ---------------------------------

dev:
	@echo "Starting api (uvicorn --reload :8000) and web (next dev :3000)."
	@echo "Requires Postgres already running locally — see README.md."
	@echo "Starting a scan locally runs the scan-runner as a plain background"
	@echo "subprocess (no Fly account needed) — see app/services/scan_orchestrator.py."
	@trap 'kill 0' EXIT INT TERM; \
	(cd apps/api && PYTHONPATH=. $(PYTHON) -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload) & \
	(cd apps/web && npm run dev) & \
	wait

## Quality ------------------------------------------------------------------------

test:
	$(PYTHON) -m pytest -q
	cd apps/web && npm run test --if-present

lint:
	cd apps/api && $(PYTHON) -m ruff check app
	cd apps/api && $(PYTHON) -m mypy app --ignore-missing-imports || true
	cd apps/web && npm run lint

## Database -------------------------------------------------------------------------

migrate:
	cd apps/api && $(ALEMBIC) upgrade head

seed:
	cd apps/api && PYTHONPATH=. $(PYTHON) -m app.seed $(ARGS)

## Fly.io deployment (remote build — no local Docker required) ----------------------
## See docs/fly-deployment.md and docs/fly-operations.md for full detail.

fly-init:
	@echo "One-time setup — see deploy/fly/README.md and docs/fly-deployment.md for the"
	@echo "full walkthrough (Postgres provisioning, all required 'flyctl secrets set' calls)."
	@: "$${FLY_APP_NAME:?Set FLY_APP_NAME first}"
	flyctl apps create "$$FLY_APP_NAME"

fly-deploy:
	./scripts/deploy-fly.sh $(ARGS)

fly-migrate:
	./scripts/migrate-fly.sh

fly-status:
	@: "$${FLY_APP_NAME:?Set FLY_APP_NAME first}"
	flyctl status --app "$$FLY_APP_NAME"
	@echo
	flyctl machine list --app "$$FLY_APP_NAME"

fly-logs:
	@: "$${FLY_APP_NAME:?Set FLY_APP_NAME first}"
	flyctl logs --app "$$FLY_APP_NAME"

fly-scan-runner-test:
	./scripts/fly-scan-runner-test.sh
