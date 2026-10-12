"""Development command helpers. No implicit live traffic or fixed application passwords."""

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    command = sys.argv[1]
    if command == "help":
        print("""make setup            Install frozen dependencies; create local random env
make dev / stop       Start/stop isolated Compose dependencies; never starts live collection
make m3-check         Read-only M3 preflight: env, DB, migrations, Temporal, registry, unit,
                      model credentials and model availability
make m3-up            Start API + Intake Worker (M3_UP_FLAGS="--with-collection --with-frontend"
                      adds the collection worker and the UI), then gate on a live consumer
make api              Start the authenticated M3 FastAPI process (loads .runtime/m3-app.env)
make intake-worker    Start P1 Temporal worker; requires UNIT_CONFIG and model credentials
make collection-worker Start the P2 per-unit Temporal worker; requires UNIT_CONFIG
                      Both workers must run for a UI submission to reach collection.
make frontend-dev     Start the React/Vite product UI with /api development proxy
make frontend-build   Type-check and build the production frontend bundle
make check            Backend static/unit + frontend type/component/build checks
make test-product-e2e Real Chromium + synthetic API product login/submission/results loop
make test-integration PostgreSQL tests; XINGTU_TEST_DATABASE_URL must name xingtu_test*
make test-contract    Synthetic browser tests; installed Chromium required
make test-e2e         Local Temporal server + test PostgreSQL; may download official test server
make migrate ENVIRONMENT=development|test  Requires explicit XINGTU_DATABASE_URL; changes DB
make smoke-live       Requires UNIT_CONFIG, PLAN, ACTOR, IDEMPOTENCY_KEY; validated target <= 3
make smoke-local      Dev harness: real Activity+workflow on the Temporal test server
                      Requires UNIT_CONFIG, ROOT_TASK_ID, XINGTU_DATABASE_URL; not production
.venv/bin/xingtu --help  Internal collection command interface
.venv/bin/xingtu-product --help  Product-user administration and P1 worker
See docs/development.md for services, configuration, gates and unfinished live verification.""")
    elif command == "init-env":
        path = ROOT / ".runtime/development.env"
        path.parent.mkdir(exist_ok=True, mode=0o700)
        if path.exists():
            print("existing environment preserved")
            return
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as stream:
            for key in (
                "APP_DB_PASSWORD",
                "TEMPORAL_DB_PASSWORD",
                "S3_ROOT_PASSWORD",
                "XINGTU_LOGIN_HMAC_KEY",
            ):
                stream.write(f"{key}={secrets.token_urlsafe(32)}\n")
        print("private development environment created; credentials not printed")
    elif command == "smoke-live":
        required = ["UNIT_CONFIG", "PLAN", "ACTOR", "IDEMPOTENCY_KEY"]
        if any(not os.environ.get(name) for name in required):
            raise SystemExit("UNIT_CONFIG, PLAN, ACTOR, IDEMPOTENCY_KEY required")
        plan = json.loads(Path(os.environ["PLAN"]).read_text())
        if type(plan.get("target_count")) is not int or not 1 <= plan["target_count"] <= 3:
            raise SystemExit("live smoke requires explicit target_count 1..3")
        subprocess.run(
            [
                str(ROOT / ".venv/bin/xingtu"),
                "start",
                "--plan",
                os.environ["PLAN"],
                "--config",
                os.environ["UNIT_CONFIG"],
                "--actor",
                os.environ["ACTOR"],
                "--key",
                os.environ["IDEMPOTENCY_KEY"],
            ],
            check=True,
        )
    else:
        raise SystemExit("unknown helper")


if __name__ == "__main__":
    main()
