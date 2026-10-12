UV := $(if $(wildcard .bootstrap/bin/uv),.bootstrap/bin/uv,uv)
PY := .venv/bin/python
COMPOSE := docker compose --env-file .runtime/development.env -f deploy/compose.yaml
DEFAULT_UNIT_CONFIG := .runtime/units/local-dev-mac-02.json
# The API, the intake worker and the collection worker all need the private M3 environment.
# Missing the model credentials used to leave UI submissions waiting in RECEIVED forever, so the
# run targets load both files explicitly instead of relying on the operator's shell.
LOAD_ENV := set -a; . ./.runtime/m3-app.env; if [ -f .runtime/deepseek.env ]; then . ./.runtime/deepseek.env; fi; set +a;
export PLAYWRIGHT_BROWSERS_PATH := $(CURDIR)/.runtime/browsers
# macOS marks `_`-prefixed files hidden and CPython >= 3.13.5 skips hidden .pth files, which
# silently breaks uv's `_editable_impl_*.pth`.  Keeping the package root on PYTHONPATH makes the
# documented check/test targets work regardless of that environment defect.
export PYTHONPATH := $(CURDIR)/backend/src
.PHONY: help setup dev stop m3-check m3-up api intake-worker collection-worker frontend-install frontend-dev frontend-check frontend-build test-product-e2e lint format-check typecheck test-unit test-integration test-contract test-e2e check migrate smoke-live smoke-local
help:
	@$(PY) scripts/commands.py help
setup:
	$(UV) sync --frozen --cache-dir .runtime/uv-cache
	.venv/bin/playwright install chromium
	npm --prefix frontend ci --no-audit --no-fund
	$(PY) scripts/commands.py init-env
dev:
	$(COMPOSE) up -d
stop:
	$(COMPOSE) stop
m3-check:
	$(PY) scripts/m3_up.py --check --unit-config "$(if $(UNIT_CONFIG),$(UNIT_CONFIG),$(DEFAULT_UNIT_CONFIG))"
m3-up:
	$(PY) scripts/m3_up.py --unit-config "$(if $(UNIT_CONFIG),$(UNIT_CONFIG),$(DEFAULT_UNIT_CONFIG))" $(M3_UP_FLAGS)
api:
	$(LOAD_ENV) .venv/bin/xingtu-api
intake-worker:
	@test -n "$(UNIT_CONFIG)" || (echo "UNIT_CONFIG required" >&2; exit 2)
	$(LOAD_ENV) .venv/bin/xingtu-product intake-worker --unit-config "$(UNIT_CONFIG)"
collection-worker:
	@test -n "$(UNIT_CONFIG)" || (echo "UNIT_CONFIG required" >&2; exit 2)
	$(LOAD_ENV) .venv/bin/xingtu worker --config "$(UNIT_CONFIG)"
frontend-install:
	npm --prefix frontend ci --no-audit --no-fund
frontend-dev:
	npm --prefix frontend run dev
frontend-check:
	npm --prefix frontend run lint
	npm --prefix frontend test
frontend-build:
	npm --prefix frontend run build
test-product-e2e:
	$(PY) -m pytest tests/e2e/test_product_frontend.py -q
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
	PYTHONPATH=$(CURDIR):$(CURDIR)/backend/src .venv/bin/pytest tests/e2e -q
check: lint format-check typecheck test-unit frontend-check frontend-build
migrate:
	.venv/bin/xingtu migrate --environment "$(ENVIRONMENT)"
smoke-live:
	$(PY) scripts/commands.py smoke-live
smoke-local:
	$(PY) scripts/local_smoke.py --config "$(UNIT_CONFIG)" --root-task-id "$(ROOT_TASK_ID)" --timeout-seconds "$(if $(TIMEOUT_SECONDS),$(TIMEOUT_SECONDS),900)"
