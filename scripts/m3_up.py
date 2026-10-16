"""Start (or verify) the complete M3 runtime: API, intake worker and optional collection worker.

Why this exists
---------------
A product submission only leaves ``RECEIVED`` while a *running* intake worker consumes
``intake_dispatches``. That process is not part of ``make dev`` and was previously absent from the
documented startup recipe, so a task submitted from the UI could wait forever with no error at
all. This supervisor makes the required processes a single, checked action:

* ``--check`` runs the preflight only (safe, read-only, no process is started);
* the default mode starts the processes, waits until the Temporal task queues report a **fresh**
  consumer, prints a status table and then supervises until interrupted.

The readiness gate deliberately does not use the poller *count*: Temporal keeps disconnected
pollers listed for minutes, so only a fresh ``last_access_time`` proves a live consumer.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import signal
import socket
import subprocess
import sys
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
LOG_DIR = RUNTIME / "logs"
M3_ENV = RUNTIME / "m3-app.env"
MODEL_ENV = RUNTIME / "deepseek.env"
DEFAULT_UNIT_CONFIG = RUNTIME / "units" / "local-dev-mac-02.json"
DEFAULT_UNIT_ID = "unit-local-mac-02"
API_PORT = 8000
FRONTEND_PORT = 5173
READINESS_TIMEOUT_SECONDS = 40.0
BRACKETED_IPV6 = re.compile(r"^\[.*\]$")


@dataclass
class Check:
    code: str
    ok: bool
    detail: str

    def render(self) -> str:
        return f"[{'ok ' if self.ok else 'FAIL'}] {self.code:<32} {self.detail}"


@dataclass
class Preflight:
    checks: list[Check] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    unit_id: str = DEFAULT_UNIT_ID
    queues: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def add(self, code: str, ok: bool, detail: str = "") -> bool:
        self.checks.append(Check(code, ok, detail))
        return ok


def load_env_file(path: Path, env: dict[str, str], *, required: bool) -> bool:
    if not path.exists():
        return not required
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value
    return True


def normalise_no_proxy(env: dict[str, str]) -> str | None:
    """Drop bracketed IPv6 entries, which httpx 0.28 cannot parse.

    The host shell in this environment sets ``no_proxy=...,::1,[::1]``. httpx raises
    ``InvalidURL: Invalid port: ':1]'`` before any request leaves the process, so the model check
    and the adapter call fail with a confusing error. Removing the bracketed form keeps the same
    bypass intent (``::1`` is still listed) and makes outbound HTTPS work.
    """
    for key in ("no_proxy", "NO_PROXY"):
        raw = env.get(key)
        if not raw:
            continue
        entries = [item.strip() for item in raw.split(",") if item.strip()]
        cleaned = [item for item in entries if not BRACKETED_IPV6.match(item)]
        if len(cleaned) != len(entries):
            value = ",".join(cleaned)
            env["no_proxy"] = value
            env["NO_PROXY"] = value
            # httpx reads the real process environment, not this dict, so keep both in sync.
            os.environ["no_proxy"] = value
            os.environ["NO_PROXY"] = value
            return f"removed {len(entries) - len(cleaned)} bracketed IPv6 entry from no_proxy"
    return None


def api_health_ok(port: int = API_PORT) -> bool:
    """The documented healthcheck is an unauthenticated 401 from GET /api/auth/me."""
    try:
        return httpx.get(f"http://127.0.0.1:{port}/api/auth/me", timeout=3).status_code == 401
    except Exception:  # noqa: BLE001
        return False


def port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex((host, port)) == 0


def latest_migration() -> int:
    versions = []
    for path in (ROOT / "migrations").glob("*.sql"):
        match = re.match(r"^(\d+)", path.name)
        if match:
            versions.append(int(match.group(1)))
    return max(versions) if versions else 0


def run_preflight(unit_config: Path, *, with_collection: bool) -> Preflight:
    from xingtu.contracts import PlatformRegistry
    from xingtu.runtime import load_unit

    pre = Preflight()
    env: dict[str, str] = dict(os.environ)
    pre.env = env

    pre.add(
        "M3_ENV_FILE",
        load_env_file(M3_ENV, env, required=True),
        str(M3_ENV.relative_to(ROOT)),
    )
    if not load_env_file(MODEL_ENV, env, required=False):
        pre.checks.append(
            Check(
                "MODEL_ENV_FILE",
                True,
                f"{MODEL_ENV.relative_to(ROOT)} absent; relying on the current environment",
            )
        )
    else:
        pre.checks.append(Check("MODEL_ENV_FILE", True, f"{MODEL_ENV.relative_to(ROOT)} loaded"))
    pre.env = env

    proxy_note = normalise_no_proxy(env)
    if proxy_note:
        pre.checks.append(Check("NO_PROXY_SANITISED", True, proxy_note))

    dsn = env.get("XINGTU_DATABASE_URL", "")
    if not pre.add("DATABASE_URL", bool(dsn), "XINGTU_DATABASE_URL present" if dsn else "missing"):
        return pre
    try:
        import psycopg

        with psycopg.connect(dsn) as conn:
            row = conn.execute("SELECT max(version) FROM schema_migrations").fetchone()
        applied = int(row[0]) if row and row[0] is not None else 0
        pre.add("DATABASE_REACHABLE", True, "connected; schema_migrations read")
        expected = latest_migration()
        pre.add(
            "MIGRATIONS_APPLIED", applied >= expected, f"applied={applied} expected>={expected}"
        )
    except Exception as exc:  # noqa: BLE001
        pre.add("DATABASE_REACHABLE", False, f"{type(exc).__name__}: {str(exc)[:90]}")
        return pre

    temporal = env.get("XINGTU_TEMPORAL_ADDRESS", "127.0.0.1:57233")
    try:
        asyncio.run(_temporal_reachable(temporal))
        pre.add("TEMPORAL_REACHABLE", True, temporal)
    except Exception as exc:  # noqa: BLE001
        pre.add("TEMPORAL_REACHABLE", False, f"{type(exc).__name__}: {str(exc)[:90]}")

    registry_path = Path(
        env.get("XINGTU_REGISTRY_PATH", str(ROOT / "contracts" / "douyin_xingtu.verified.json"))
    )
    try:
        registry = PlatformRegistry.model_validate_json(registry_path.read_text())
        registry.require_enabled(live=True)
        pre.add(
            "REGISTRY_VERIFIED_LIVE",
            True,
            f"{registry_path.name} capabilities={registry.capabilities.version}",
        )
    except Exception as exc:  # noqa: BLE001
        pre.add("REGISTRY_VERIFIED_LIVE", False, f"{type(exc).__name__}: {str(exc)[:90]}")

    if not unit_config.exists():
        pre.add("UNIT_CONFIG", False, f"{unit_config} missing")
        return pre
    try:
        unit = load_unit(unit_config)
        pre.unit_id = unit.unit_id
        pre.add("UNIT_CONFIG", True, f"unit_id={unit.unit_id}")
    except Exception as exc:  # noqa: BLE001
        pre.add("UNIT_CONFIG", False, f"{type(exc).__name__}: {str(exc)[:90]}")
        return pre

    try:
        import psycopg

        with psycopg.connect(dsn) as conn:
            row = conn.execute(
                "SELECT state FROM execution_units WHERE unit_id=%s", (pre.unit_id,)
            ).fetchone()
        if row is None:
            pre.add("EXECUTION_UNIT_REGISTERED", False, f"{pre.unit_id} not registered")
        else:
            pre.add("EXECUTION_UNIT_REGISTERED", True, f"{pre.unit_id} state={row[0]}")
            pre.add(
                "EXECUTION_UNIT_READY",
                row[0] == "READY",
                "READY" if row[0] == "READY" else f"state={row[0]} blocks promotion",
            )
    except Exception as exc:  # noqa: BLE001
        pre.add("EXECUTION_UNIT_REGISTERED", False, f"{type(exc).__name__}: {str(exc)[:90]}")

    api_key = env.get("DEEPSEEK_API_KEY", "")
    if not pre.add(
        "DEEPSEEK_API_KEY",
        bool(api_key),
        "present" if api_key else "missing; the intake worker exits with DEEPSEEK_API_KEY_REQUIRED",
    ):
        return pre

    model = env.get("XINGTU_DEEPSEEK_MODEL", "deepseek-flash")
    base_url = env.get("XINGTU_DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    try:
        pre.add("MODEL_AVAILABLE", *_model_check(base_url, model, api_key))
    except Exception as exc:  # noqa: BLE001
        pre.add("MODEL_AVAILABLE", False, f"{type(exc).__name__}: {str(exc)[:90]}")

    pre.queues = ["xingtu-intake"] + ([f"xingtu-{pre.unit_id}"] if with_collection else [])
    return pre


def _model_check(base_url: str, model: str, api_key: str, *, attempts: int = 3) -> tuple[bool, str]:
    """Verify the configured model, tolerating a transient network hiccup.

    A local proxy can drop a single request (observed: RemoteProtocolError). Retrying keeps a
    fail-safe preflight from blocking startup on a blip, while a real misconfiguration still fails
    after the bounded attempts.
    """
    last = "unknown error"
    for attempt in range(1, attempts + 1):
        try:
            response = httpx.get(
                base_url + "/models",
                headers={"Authorization": "Bearer " + api_key},
                timeout=20,
                trust_env=True,
            )
        except Exception as exc:  # noqa: BLE001 - transient transport failures are retried
            last = f"{type(exc).__name__}: {str(exc)[:70]}"
        else:
            if response.status_code != 200:
                last = f"provider status {response.status_code}"
                if response.status_code in {401, 402, 403}:
                    break
            else:
                models = [item.get("id") for item in response.json().get("data", [])]
                return (model in models), f"{model} (available={models})"
        if attempt < attempts:
            time.sleep(1.5)
    return False, f"{last} (after {attempts} attempts)"


async def _temporal_reachable(address: str) -> None:
    from temporalio.client import Client

    await asyncio.wait_for(Client.connect(address), timeout=8)


async def _readiness(
    address: str, queues: list[str], timeout: float
) -> tuple[bool, dict[str, Any]]:
    from xingtu.worker_health import check_queues

    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        results = await check_queues(address, queues)
        last = {
            queue: {
                "alive": health.alive,
                "fresh_pollers": health.fresh_pollers,
                "poller_entries": health.poller_entries,
                "freshest_age_seconds": health.freshest_age_seconds,
                "error": health.error,
            }
            for queue, health in results.items()
        }
        if all(entry["alive"] for entry in last.values()):
            return True, last
        await asyncio.sleep(1.0)
    return False, last


class Supervisor:
    def __init__(self) -> None:
        self.children: dict[str, subprocess.Popen[bytes]] = {}
        LOG_DIR.mkdir(parents=True, exist_ok=True)

    def start(
        self,
        name: str,
        command: list[str],
        env: dict[str, str],
        *,
        cwd: Path = ROOT,
    ) -> None:
        handle = (LOG_DIR / f"{name}.log").open("ab")
        self.children[name] = subprocess.Popen(
            command, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT
        )

    def alive(self) -> list[str]:
        return [name for name, proc in self.children.items() if proc.poll() is None]

    def dead(self) -> list[str]:
        return [name for name, proc in self.children.items() if proc.poll() is not None]

    def stop(self) -> None:
        for proc in self.children.values():
            if proc.poll() is None:
                proc.terminate()
        for proc in self.children.values():
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

    def tail(self, name: str, lines: int = 12) -> str:
        path = LOG_DIR / f"{name}.log"
        if not path.exists():
            return f"(no log for {name})"
        return "\n".join(path.read_text(errors="replace").splitlines()[-lines:])


def _on_signal(signum: int, frame: object) -> None:
    """Turn SIGTERM into KeyboardInterrupt so the children are always stopped on exit."""
    del signum, frame
    raise KeyboardInterrupt


def main() -> int:
    # The supervisor is usually started from a pipe (make/CI), where stdout is block buffered and
    # the readiness verdict would only appear on exit.
    with suppress(Exception):
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
    signal.signal(signal.SIGTERM, _on_signal)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="preflight only; start nothing")
    parser.add_argument("--with-collection", action="store_true", help="also start the P2 worker")
    parser.add_argument("--with-frontend", action="store_true", help="also start the Vite UI")
    parser.add_argument("--unit-config", type=Path, default=DEFAULT_UNIT_CONFIG)
    parser.add_argument("--timeout", type=float, default=READINESS_TIMEOUT_SECONDS)
    args = parser.parse_args()

    pre = run_preflight(args.unit_config, with_collection=args.with_collection)
    print("=== M3 preflight ===")
    for check in pre.checks:
        print("  " + check.render())

    if not pre.ok:
        failed = [check.code for check in pre.checks if not check.ok]
        print("\nPREFLIGHT_FAILED: " + ", ".join(failed))
        print("No process was started. Fix the failing checks and re-run.")
        return 2
    if args.check:
        print("\nPREFLIGHT_OK: all required prerequisites are satisfied.")
        return 0

    env = dict(pre.env)
    env.setdefault("PYTHONUNBUFFERED", "1")
    supervisor = Supervisor()
    api_running = port_open("127.0.0.1", API_PORT)
    frontend_running = port_open("127.0.0.1", FRONTEND_PORT)
    started: list[str] = []

    try:
        if api_running:
            note = "healthcheck 401 confirmed" if api_health_ok() else "healthcheck NOT recognised"
            print(f"  [reuse] api already listening on 127.0.0.1:{API_PORT} ({note})")
        else:
            supervisor.start("api", [str(ROOT / ".venv/bin/xingtu-api")], env)
            started.append("api")
        supervisor.start(
            "intake-worker",
            [
                str(ROOT / ".venv/bin/xingtu-product"),
                "intake-worker",
                "--unit-config",
                str(args.unit_config),
            ],
            env,
        )
        started.append("intake-worker")
        if args.with_collection:
            supervisor.start(
                "collection-worker",
                [
                    str(ROOT / ".venv/bin/xingtu"),
                    "worker",
                    "--config",
                    str(args.unit_config),
                ],
                env,
            )
            started.append("collection-worker")
        if args.with_frontend and not frontend_running:
            supervisor.start("frontend", ["npm", "run", "dev"], env, cwd=ROOT / "frontend")
            started.append("frontend")

        address = env.get("XINGTU_TEMPORAL_ADDRESS", "127.0.0.1:57233")
        ok, observed = asyncio.run(_readiness(address, pre.queues, args.timeout))
        print("\n=== consumer readiness ===")
        for queue, entry in observed.items():
            print(
                f"  {queue:<28} alive={entry['alive']} fresh_pollers={entry['fresh_pollers']} "
                f"poller_entries={entry['poller_entries']} "
                f"freshest_age={entry['freshest_age_seconds']} error={entry['error']}"
            )
        if not ok:
            print("\nREADINESS_FAILED: no fresh consumer observed for " + ", ".join(pre.queues))
            for name in list(supervisor.children):
                print(f"--- {name} (last lines) ---\n{supervisor.tail(name)}")
            return 3

        print(
            "\nREADY: " + ", ".join(started) + f". Logs in {LOG_DIR.relative_to(ROOT)}/. "
            "Press Ctrl-C to stop the processes started here."
        )
        while supervisor.alive():
            time.sleep(2)
            for name in supervisor.dead():
                print(f"PROCESS_EXITED: {name}\n{supervisor.tail(name)}")
                return 4
        return 0
    except KeyboardInterrupt:
        print("\nstopping…")
        return 0
    finally:
        supervisor.stop()


if __name__ == "__main__":
    sys.exit(main())
