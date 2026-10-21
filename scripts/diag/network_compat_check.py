"""Read-only network compatibility probe for the Mac collection node.

Checks current interface/route/DNS, Tailscale path, TCP reachability, PostgreSQL,
Temporal pollers, MinIO GET, launchd Worker and ExecutionUnit.  No business writes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
import psycopg
from botocore.config import Config
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[2]
sys_path = str(ROOT / "backend" / "src")
import sys  # noqa: E402

if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

from xingtu.worker_health import check_queues  # noqa: E402


def run(cmd: list[str], timeout: float = 15.0) -> dict[str, Any]:
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {
            "cmd": " ".join(cmd),
            "exit": proc.returncode,
            "elapsed_s": round(time.monotonic() - started, 3),
            "stdout": proc.stdout.strip()[:4000],
            "stderr": proc.stderr.strip()[:1000],
        }
    except subprocess.TimeoutExpired:
        return {
            "cmd": " ".join(cmd),
            "timeout": True,
            "elapsed_s": round(time.monotonic() - started, 3),
        }
    except Exception as exc:  # noqa: BLE001
        return {"cmd": " ".join(cmd), "error": type(exc).__name__}


def tcp_probe(host: str, port: int, samples: int = 3) -> dict[str, Any]:
    import socket

    times: list[float] = []
    errors: list[str] = []
    for _ in range(samples):
        sock = socket.socket()
        sock.settimeout(8)
        started = time.monotonic()
        try:
            sock.connect((host, port))
            times.append(round((time.monotonic() - started) * 1000, 1))
        except Exception as exc:  # noqa: BLE001
            errors.append(type(exc).__name__)
        finally:
            sock.close()
    return {
        "host": host,
        "port": port,
        "ok": len(times),
        "fail": len(errors),
        "times_ms": times,
        "errors": errors,
    }


def db_probe(dsn: str) -> dict[str, Any]:
    started = time.monotonic()
    try:
        with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=8) as conn:
            one = conn.execute("SELECT 1 AS ok").fetchone()
            unit = conn.execute(
                "SELECT unit_id,state,generation,owner,browser_stopped,last_heartbeat_at "
                "FROM execution_units WHERE unit_id='unit-local-mac-02'"
            ).fetchone()
            active = conn.execute(
                "SELECT count(*) n FROM root_tasks WHERE state IN "
                "('QUEUED','SEARCHING','COLLECTING','PERSISTING','CANCELLING')"
            ).fetchone()
            total = conn.execute("SELECT count(*) n FROM root_tasks").fetchone()
        return {
            "ok": True,
            "elapsed_s": round(time.monotonic() - started, 3),
            "select1": one,
            "unit": {k: str(v) for k, v in unit.items()} if unit else None,
            "active_roots": active["n"] if active else None,
            "root_tasks_total": total["n"] if total else None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "elapsed_s": round(time.monotonic() - started, 3),
            "error": type(exc).__name__,
            "detail": str(exc)[:300],
        }


def minio_probe() -> dict[str, Any]:
    bucket = os.environ.get("XINGTU_S3_COVER_BUCKET", "xingtu-covers")
    endpoint = os.environ.get("XINGTU_S3_ENDPOINT", "http://100.86.124.51:9000")
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    started = time.monotonic()
    try:
        with psycopg.connect(
            os.environ["XINGTU_DATABASE_URL"], row_factory=dict_row, connect_timeout=8
        ) as conn:
            row = conn.execute(
                "SELECT object_id,byte_size FROM media_objects WHERE kind='cover' "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            config=Config(
                proxies={}, retries={"max_attempts": 1}, connect_timeout=8, read_timeout=45
            ),
        )
        t = time.monotonic()
        body = client.get_object(Bucket=bucket, Key=row["object_id"])["Body"].read()
        elapsed = time.monotonic() - t
        return {
            "ok": True,
            "elapsed_s": round(time.monotonic() - started, 3),
            "get_s": round(elapsed, 3),
            "bytes": len(body),
            "kib_s": round(len(body) / elapsed / 1024, 1) if elapsed else None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "elapsed_s": round(time.monotonic() - started, 3),
            "error": type(exc).__name__,
            "detail": str(exc)[:300],
        }


async def temporal_probe(address: str) -> dict[str, Any]:
    started = time.monotonic()
    try:
        result = await check_queues(address, ["xingtu-unit-local-mac-02"], timeout_seconds=15)
        health = result["xingtu-unit-local-mac-02"]
        return {
            "ok": health.alive is not None,
            "elapsed_s": round(time.monotonic() - started, 3),
            "alive": health.alive,
            "fresh_pollers": health.fresh_pollers,
            "poller_entries": health.poller_entries,
            "freshest_age_seconds": health.freshest_age_seconds,
            "error": health.error,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "elapsed_s": round(time.monotonic() - started, 3),
            "error": type(exc).__name__,
        }


def launchd_probe() -> dict[str, Any]:
    out = run(["launchctl", "print", f"gui/{os.getuid()}/com.yumeng.xingtu.collection-worker"], 10)
    text = out.get("stdout", "")
    fields: dict[str, Any] = {}
    for line in text.splitlines():
        stripped = line.strip()
        for key in ("state =", "pid =", "runs ="):
            if stripped.startswith(key):
                fields[key.split()[0]] = stripped.split("=", 1)[1].strip()
    return {"ok": out.get("exit") == 0, **fields, "raw": text[:1000]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    dsn = os.environ["XINGTU_DATABASE_URL"]
    address = os.environ["XINGTU_TEMPORAL_ADDRESS"]
    result: dict[str, Any] = {
        "label": args.label,
        "checked_at": datetime.now(UTC).isoformat(),
        "interface": run(["ifconfig", "en0"], 5),
        "network": run(["scutil", "--nwi"], 5),
        "route": run(["route", "-n", "get", "default"], 5),
        "dns": run(["scutil", "--dns"], 5),
        "tailscale_status": run(["tailscale", "status"], 10),
        "tailscale_ping": run(["tailscale", "ping", "--c", "2", "100.86.124.51"], 14),
        "tailscale_netcheck": run(["tailscale", "netcheck"], 25),
        "tcp": {str(port): tcp_probe("100.86.124.51", port) for port in (5432, 7233, 9000)},
        "postgres": db_probe(dsn),
        "minio": minio_probe(),
        "temporal": asyncio.run(temporal_probe(address)),
        "launchd": launchd_probe(),
    }
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    print(
        json.dumps(
            {k: v for k, v in result.items() if k not in {"dns", "interface", "network", "route"}},
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
