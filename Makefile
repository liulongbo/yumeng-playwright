UV := $(if $(wildcard .bootstrap/bin/uv),.bootstrap/bin/uv,uv)
PY := .venv/bin/python
COMPOSE := docker compose --env-file .runtime/development.env -f deploy/compose.yaml
export PLAYWRIGHT_BROWSERS_PATH := $(CURDIR)/.runtime/browsers
.PHONY: help setup dev stop lint format-check typecheck test-unit test-integration test-contract test-e2e check migrate smoke-live smoke-local
help:
	@$(PY) scripts/commands.py help
setup:
	$(UV) sync --frozen --cache-dir .runtime/uv-cache
	.venv/bin/playwright install chromium
	$(PY) scripts/commands.py init-env
dev:
	$(COMPOSE) up -d
stop:
	$(COMPOSE) stop
lint:
	.venv/bin/ruff check backend conftest.py tests scripts
format-check:
	.venv/bin/ruff format --check backend conftest.py tests scripts
typecheck:
	.venv/bin/mypy backend/src
test-unit:
	.venv/bin/pytest backend/tests/unit -q
test-integration:
	.venv/bin/pytest backend/tests/integration -q
test-contract:
	.venv/bin/pytest backend/tests/contract -q
test-e2e:
	.venv/bin/pytest tests/e2e -q
check: lint format-check typecheck test-unit
migrate:
	.venv/bin/xingtu migrate --environment "$(ENVIRONMENT)"
smoke-live:
	$(PY) scripts/commands.py smoke-live
smoke-local:
	$(PY) scripts/local_smoke.py --config "$(UNIT_CONFIG)" --root-task-id "$(ROOT_TASK_ID)" --timeout-seconds "$(if $(TIMEOUT_SECONDS),$(TIMEOUT_SECONDS),900)"
