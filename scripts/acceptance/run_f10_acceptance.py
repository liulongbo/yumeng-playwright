"""F10 isolated acceptance environment and deterministic challenge simulator.

The harness never opens the configured Xingtu profile.  It creates a random PostgreSQL schema,
starts API/frontend processes on dedicated ports and seeds one synthetic task whose exact request
is keyword ``户外`` and target count ``21``.  State transitions use the production repository
methods; only the platform-side challenge signal and verification result are synthetic.

Usage:
    .venv/bin/python scripts/acceptance/run_f10_acceptance.py prepare
    .venv/bin/python scripts/acceptance/run_f10_acceptance.py activate
    .venv/bin/python scripts/acceptance/run_f10_acceptance.py fail-verification
    .venv/bin/python scripts/acceptance/run_f10_acceptance.py resume
    .venv/bin/python scripts/acceptance/run_f10_acceptance.py inspect
    .venv/bin/python scripts/acceptance/run_f10_acceptance.py cleanup
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import time
from datetime import timedelta
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from xingtu.domain import Candidate, CreatorRef, Filter, FilterPlan, TaskStatus, uid  # noqa: E402
from xingtu.product_auth import PasswordService  # noqa: E402
from xingtu.product_repository import ProductRepository  # noqa: E402
from xingtu.repository import Repository  # noqa: E402

RUNTIME = ROOT / ".runtime" / "f10-acceptance"
STATE_FILE = RUNTIME / "state.json"
LOG_DIR = RUNTIME / "logs"
API_PORT = 8100
FRONTEND_PORT = 5273
SCHEMA_PREFIX = "f10_accept_"


def read_env(path: pathlib.Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def base_env() -> dict[str, str]:
    values = read_env(ROOT / ".runtime" / "m3-app.env")
    required = {"XINGTU_DATABASE_URL", "XINGTU_REDIS_URL", "XINGTU_LOGIN_HMAC_KEY"}
    missing = sorted(required - values.keys())
    if missing:
        raise SystemExit("missing acceptance prerequisites: " + ", ".join(missing))
    return values


def isolated_dsn(schema: str) -> str:
    params: dict[str, Any] = conninfo_to_dict(base_env()["XINGTU_DATABASE_URL"])
    existing = str(params.get("options") or "")
    # Do not include ``public``: Repository.migrate probes unqualified ``schema_migrations``.
    # Falling through to the development schema would skip isolated migrations and could write
    # acceptance rows into the real development tables.
    params["options"] = (existing + f" -csearch_path={schema}").strip()
    return make_conninfo(**params)


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        raise SystemExit("F10 acceptance environment is not prepared")
    return cast(dict[str, Any], json.loads(STATE_FILE.read_text()))


def save_state(state: dict[str, Any]) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    STATE_FILE.chmod(0o600)


def repository(state: dict[str, Any]) -> Repository:
    return Repository(isolated_dsn(state["schema"]))


def wait_http(url: str, expected: int = 200, timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    last = "no response"
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2) as response:  # noqa: S310 - loopback acceptance URL
                if response.status == expected:
                    return
                last = f"HTTP {response.status}"
        except HTTPError as error:
            if error.code == expected:
                return
            last = f"HTTP {error.code}"
        except (URLError, TimeoutError, OSError) as error:
            last = str(getattr(error, "reason", error))
        time.sleep(0.5)
    raise RuntimeError(f"{url} did not become ready: {last}")


def start_process(name: str, command: list[str], environment: dict[str, str]) -> int:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = (LOG_DIR / f"{name}.log").open("ab")
    process = subprocess.Popen(  # noqa: S603 - fixed project commands only
        command,
        cwd=ROOT,
        env=environment,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return process.pid


def latest_takeover(repo: Repository) -> dict[str, Any] | None:
    with repo.connect() as conn:
        row = conn.execute(
            "SELECT * FROM browser_takeover_sessions ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def prepare() -> None:
    if STATE_FILE.exists():
        raise SystemExit("existing F10 acceptance state must be cleaned first")
    run_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uid().replace("-", "")[:8]
    schema = SCHEMA_PREFIX + run_id.lower()
    unit = "f10-accept-" + run_id[-8:]
    base = base_env()
    base_dsn = base["XINGTU_DATABASE_URL"]
    with psycopg.connect(base_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    state: dict[str, Any] = {"run_id": run_id, "schema": schema, "unit": unit}
    save_state(state)
    try:
        repo = repository(state)
        repo.migrate(ROOT / "migrations")
        profile = str(RUNTIME / run_id / "synthetic-browser-profile")
        repo.register_unit(
            unit,
            "acceptance-account-" + run_id,
            "acceptance-line-" + run_id,
            profile,
            network_mode="local_development",
            expected_account_id="acceptance-account-id",
        )
        with repo.connect() as conn:
            conn.execute("UPDATE execution_units SET state='READY' WHERE unit_id=%s", (unit,))
        plan = FilterPlan(
            capability_version="f10-acceptance.synthetic.v1",
            target_count=21,
            filters=[
                Filter(field="keyword", operator="eq", value="户外", source_fields=["keyword"])
            ],
        )
        root_task_id = repo.create(
            plan,
            unit,
            "f10-acceptance-" + run_id,
            "f10-acceptance",
            adapter_version="synthetic-f10-v1",
            contract_version="synthetic-f10-v1",
            modules=["basic"],
        )
        task = repo.get(root_task_id)
        generation, session_version = repo.acquire(unit, task.attempt_id, root_task_id=root_task_id)
        browser_instance_id = uid()
        repo.register_browser_instance(unit, task.attempt_id, generation, browser_instance_id)
        repo.transition_collect_to_maintenance(
            unit,
            task.attempt_id,
            generation,
            session_version,
            "PLATFORM_SECURITY_CHALLENGE",
            "f10-acceptance",
            maintenance_ttl=timedelta(minutes=30),
        )
        with repo.edit(root_task_id) as (record, _):
            record.state = TaskStatus.WAITING_FOR_VERIFICATION
            record.checkpoint.candidates = [
                Candidate(
                    ref=CreatorRef(
                        platform_creator_id=f"outdoor-{number:02d}",
                        verified_homepage=f"https://synthetic.invalid/outdoor-{number:02d}",
                        first_position=number,
                    )
                )
                for number in range(1, 4)
            ]
        event = repo.create_verification_event(
            unit=unit,
            root_task_id=root_task_id,
            generation=generation,
            browser_instance_id=browser_instance_id,
            timeout_seconds=1800,
        )

        qa = read_env(ROOT / ".runtime" / "qa-credentials.env")
        password = qa.get("QA_MEDIA_A_PASSWORD")
        if not password:
            raise RuntimeError("QA_MEDIA_A_PASSWORD is missing")
        products = ProductRepository(repo)
        products.create_user(
            "f10-operator", "F10 验收员", PasswordService().hash(password), actor="acceptance"
        )

        state.update(
            {
                "root_task_id": root_task_id,
                "attempt_id": task.attempt_id,
                "generation": generation,
                "session_version": session_version,
                "browser_instance_id": browser_instance_id,
                "event_id": str(event["event_id"]),
                "api_url": f"http://127.0.0.1:{API_PORT}",
                "frontend_url": f"http://127.0.0.1:{FRONTEND_PORT}",
            }
        )

        child_env = dict(os.environ)
        child_env.update(base)
        child_env["NO_PROXY"] = "127.0.0.1,localhost"
        child_env["no_proxy"] = "127.0.0.1,localhost"
        child_env.update(
            {
                "PYTHONPATH": str(ROOT / "backend" / "src"),
                "XINGTU_DATABASE_URL": isolated_dsn(schema),
                "XINGTU_API_PORT": str(API_PORT),
                "XINGTU_API_HOST": "127.0.0.1",
                "XINGTU_SECURE_COOKIE": "0",
                "XINGTU_ALLOWED_ORIGINS": f"http://127.0.0.1:{FRONTEND_PORT}",
                "XINGTU_RUNTIME_ROOT": str(RUNTIME / run_id / "app"),
                "XINGTU_COVER_KIND": "local",
                "XINGTU_COVER_DIRECTORY": str(RUNTIME / run_id / "app" / "covers"),
            }
        )
        state["api_pid"] = start_process(
            "api", [str(ROOT / ".venv" / "bin" / "xingtu-api")], child_env
        )
        frontend_env = dict(child_env)
        frontend_env["XINGTU_FRONTEND_API_TARGET"] = f"http://127.0.0.1:{API_PORT}"
        state["frontend_pid"] = start_process(
            "frontend",
            [
                "npm",
                "--prefix",
                str(ROOT / "frontend"),
                "run",
                "dev",
                "--",
                "--host",
                "127.0.0.1",
                "--port",
                str(FRONTEND_PORT),
                "--strictPort",
            ],
            frontend_env,
        )
        save_state(state)
        wait_http(state["api_url"] + "/api/auth/me", expected=401)
        wait_http(state["frontend_url"] + "/login")
        print(
            json.dumps(
                {
                    k: state[k]
                    for k in ("run_id", "unit", "root_task_id", "api_url", "frontend_url")
                },
                ensure_ascii=False,
            )
        )
    except Exception:
        cleanup(ignore_missing=True)
        raise


def activate() -> None:
    state = load_state()
    repo = repository(state)
    repo.heartbeat(state["unit"], state["attempt_id"], state["generation"])
    row = repo.activate_browser_takeover(
        unit=state["unit"],
        owner=state["attempt_id"],
        generation=state["generation"],
        browser_instance_id=state["browser_instance_id"],
    )
    if not row:
        raise SystemExit("no REQUESTED takeover to activate")
    print(json.dumps({"takeover_id": str(row["takeover_id"]), "state": row["state"]}))


def fail_verification() -> None:
    state = load_state()
    repo = repository(state)
    repo.heartbeat(state["unit"], state["attempt_id"], state["generation"])
    row = latest_takeover(repo)
    if not row or row["state"] != "VERIFYING":
        raise SystemExit("latest takeover is not VERIFYING")
    repo.finish_browser_takeover(
        str(row["takeover_id"]),
        resumed=False,
        failure_reason="SECURITY_CHALLENGE_STILL_PRESENT",
    )
    print(json.dumps({"takeover_id": str(row["takeover_id"]), "state": "FAILED"}))


def resume() -> None:
    state = load_state()
    repo = repository(state)
    repo.heartbeat(state["unit"], state["attempt_id"], state["generation"])
    row = latest_takeover(repo)
    if not row or row["state"] != "VERIFYING":
        raise SystemExit("latest takeover is not VERIFYING")
    repo.promote_maintenance_to_collect(
        state["unit"],
        state["attempt_id"],
        state["generation"],
        state["session_version"],
        "acceptance-account-id",
        "f10-acceptance",
        account_verified=True,
        protected_page_verified=True,
        line_verified=True,
    )
    repo.finish_browser_takeover(str(row["takeover_id"]), resumed=True)
    with repo.edit(state["root_task_id"]) as (task, _):
        task.state = TaskStatus.COLLECTING
    print(json.dumps({"takeover_id": str(row["takeover_id"]), "state": "RESUMED"}))


def inspect() -> None:
    state = load_state()
    repo = repository(state)
    task = repo.get(state["root_task_id"])
    unit = repo.unit(state["unit"])
    with repo.connect() as conn:
        event = conn.execute(
            "SELECT state,reason,reappearance_count FROM verification_events WHERE event_id=%s",
            (state["event_id"],),
        ).fetchone()
    takeover = latest_takeover(repo)
    keyword = next(item.value for item in task.plan.filters if item.field == "keyword")
    output = {
        "run_id": state["run_id"],
        "root_task_id": state["root_task_id"],
        "keyword": keyword,
        "target_count": task.plan.target_count,
        "task_state": task.state,
        "checkpoint_candidate_count": len(task.checkpoint.candidates),
        "unit": {
            "unit_id": unit["unit_id"],
            "state": unit["state"],
            "mode": unit["mode"],
            "generation": unit["generation"],
            "session_version": unit["session_version"],
            "browser_stopped": unit["browser_stopped"],
        },
        "verification": dict(event) if event else None,
        "takeover": (
            {
                "takeover_id": str(takeover["takeover_id"]),
                "state": takeover["state"],
                "failure_reason": takeover["failure_reason"],
            }
            if takeover
            else None
        ),
    }
    print(json.dumps(output, ensure_ascii=False, default=str, indent=2))


def stop_pid(pid: int | None) -> None:
    if not pid:
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.2)
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def cleanup(*, ignore_missing: bool = False) -> None:
    if not STATE_FILE.exists():
        if ignore_missing:
            return
        raise SystemExit("nothing to clean")
    state = load_state()
    schema = state.get("schema", "")
    if not schema.startswith(SCHEMA_PREFIX):
        raise RuntimeError("refusing to remove a non-acceptance schema")
    stop_pid(state.get("frontend_pid"))
    stop_pid(state.get("api_pid"))
    with psycopg.connect(base_env()["XINGTU_DATABASE_URL"], autocommit=True) as conn:
        conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
    run_dir = RUNTIME / state["run_id"]
    if run_dir.is_dir() and run_dir.parent == RUNTIME:
        shutil.rmtree(run_dir)
    STATE_FILE.unlink(missing_ok=True)
    print(json.dumps({"cleaned": True, "schema": schema, "ports": [API_PORT, FRONTEND_PORT]}))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=["prepare", "activate", "fail-verification", "resume", "inspect", "cleanup"],
    )
    action = parser.parse_args().action
    {
        "prepare": prepare,
        "activate": activate,
        "fail-verification": fail_verification,
        "resume": resume,
        "inspect": inspect,
        "cleanup": cleanup,
    }[action]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
