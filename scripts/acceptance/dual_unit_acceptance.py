#!/usr/bin/env python3
"""Real UI acceptance for the two dedicated execution units.

Browser actions go through the project's Playwright MCP stdio client (real Chrome), not through
Playwright Python page automation.  Task state, unit ownership/leases and profile/instance
evidence are read from PostgreSQL; activity intervals come from Temporal history.

The script is read-only on the platform: it submits the authorized small samples and observes.
It never prints cookies, passwords or platform response bodies.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from temporalio.api.enums.v1 import EventType
from temporalio.client import Client

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "qa"))

from juxing_main_mcp import Driver  # noqa: E402

XINGTU_UNIT = "unit-local-mac-02"
JUXING_UNIT = "unit-local-mac-03-juxing"
TERMINAL = {"COMPLETED", "PARTIAL_COMPLETED", "FAILED", "FAILED_VALIDATION", "CANCELLED"}
ACTIVITY = "collect_segment_v1"


def dsn() -> str:
    value = os.environ.get("XINGTU_DATABASE_URL")
    if not value:
        raise SystemExit("XINGTU_DATABASE_URL required")
    return value


def iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def sample_units(conn: psycopg.Connection[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in conn.execute(
            """SELECT unit_id,state,mode,owner,generation,session_version,
            current_root_task_id,browser_stopped,browser_instance_id,browser_started_at,lease_until
            FROM execution_units WHERE unit_id IN (%s,%s) ORDER BY unit_id""",
            (XINGTU_UNIT, JUXING_UNIT),
        ).fetchall()
    ]


class Sampler:
    def __init__(self, out: Path, started_at: datetime) -> None:
        self.out = out
        self.started_at = started_at
        self.path = out / "samples.jsonl"
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="dual-unit-sampler", daemon=True)

    def begin(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with (
            self.path.open("w", encoding="utf-8") as stream,
            psycopg.connect(dsn(), row_factory=dict_row) as conn,
        ):
            while not self._stop.is_set():
                payload: dict[str, Any] = {"ts": datetime.now(UTC).isoformat(), "units": []}
                try:
                    payload["units"] = sample_units(conn)
                    rows = conn.execute(
                        """SELECT root_task_id,platform,state,unit_id,created_at,updated_at
                        FROM root_tasks WHERE created_at >= %s ORDER BY created_at""",
                        (self.started_at,),
                    ).fetchall()
                    payload["tasks"] = [
                        {**dict(row), "root_task_id": str(row["root_task_id"])} for row in rows
                    ]
                except Exception as exc:  # noqa: BLE001 - sampling must not kill the UI run
                    payload["error"] = type(exc).__name__
                stream.write(json.dumps(payload, default=str) + "\n")
                stream.flush()
                self._stop.wait(1.0)


def wait_terminal(
    conn: psycopg.Connection[dict[str, Any]], roots: list[str], timeout: float
) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = conn.execute(
            "SELECT root_task_id,state,unit_id,platform,payload->>'failure_reason' AS failure_reason "
            "FROM root_tasks WHERE root_task_id=ANY(%s::uuid[])",
            (roots,),
        ).fetchall()
        current = {str(row["root_task_id"]): dict(row) for row in rows}
        if len(current) == len(roots) and all(
            item["state"] in TERMINAL for item in current.values()
        ):
            return current
        time.sleep(3)
    return current


async def activity_intervals(roots: list[str]) -> dict[str, list[dict[str, Any]]]:
    client = await Client.connect(os.environ.get("XINGTU_TEMPORAL_ADDRESS", "127.0.0.1:57233"))
    result: dict[str, list[dict[str, Any]]] = {}
    for root in roots:
        handle = client.get_workflow_handle(f"collect/{root}")
        history = await handle.fetch_history()
        starts: dict[int, dict[str, Any]] = {}
        pairs: list[dict[str, Any]] = []
        for event in history.events:
            if event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_STARTED:
                # CollectionWorkflow executes exactly one activity type, collect_segment_v1;
                # the started event does not carry the activity type in this SDK build, and the
                # scheduled event does. Every started/completed pair here is therefore that
                # activity (including Temporal retries, which share the scheduled event id).
                attrs = event.activity_task_started_event_attributes
                starts[event.event_id] = {
                    "scheduled_event_id": attrs.scheduled_event_id,
                    "started_at": event.event_time.ToDatetime(tzinfo=UTC),
                    "attempt": attrs.attempt,
                }
            elif event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_COMPLETED:
                attrs = event.activity_task_completed_event_attributes
                started = starts.get(attrs.started_event_id)
                if not started:
                    continue
                pairs.append(
                    {
                        "scheduled_event_id": started["scheduled_event_id"],
                        "attempt": started["attempt"],
                        "started_at": started["started_at"],
                        "completed_at": event.event_time.ToDatetime(tzinfo=UTC),
                    }
                )
        result[root] = pairs
    return result


def union_interval(pairs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not pairs:
        return None
    starts = [p["started_at"] for p in pairs]
    ends = [p["completed_at"] for p in pairs]
    return {"started_at": min(starts), "completed_at": max(ends)}


def intervals_overlap(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    if not left or not right:
        return False
    return left["started_at"] < right["completed_at"] and right["started_at"] < left["completed_at"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=["pair", "two-each"], default="pair")
    parser.add_argument("--base", default="http://127.0.0.1:5173")
    parser.add_argument("--out", type=Path, default=ROOT / ".runtime/dual-unit-acceptance/pair")
    parser.add_argument("--timeout", type=float, default=900)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True, mode=0o700)
    started_at = datetime.now(UTC)
    sampler = Sampler(args.out, started_at)
    sampler.begin()
    roots: list[str] = []
    driver: Driver | None = None
    try:
        driver = Driver(args.base, args.out / "mcp", headless=True)
        driver.login()
        if args.scenario == "pair":
            roots.append(driver.submit_xingtu())
            roots.append(driver.submit_juxing())
        else:
            roots.append(driver.submit_xingtu())
            roots.append(driver.submit_xingtu())
            roots.append(driver.submit_juxing())
            roots.append(driver.submit_juxing())
        print("roots", roots, flush=True)
        with psycopg.connect(dsn(), row_factory=dict_row) as conn:
            final = wait_terminal(conn, roots, args.timeout)
        sampler.stop()
        intervals = asyncio.run(activity_intervals(roots))
        by_root = {root: union_interval(intervals.get(root, [])) for root in roots}
        report: dict[str, Any] = {
            "scenario": args.scenario,
            "started_at": started_at.isoformat(),
            "roots": roots,
            "final": final,
            "activity": {
                root: {
                    "pairs": [
                        {k: iso(v) if isinstance(v, datetime) else v for k, v in pair.items()}
                        for pair in intervals.get(root, [])
                    ],
                    "union": {
                        k: iso(v) if isinstance(v, datetime) else v
                        for k, v in (by_root[root] or {}).items()
                    },
                }
                for root in roots
            },
            "samples": str(sampler.path),
        }
        report["checks"] = {}
        if args.scenario == "pair" and len(roots) == 2:
            report["checks"]["cross_platform_overlap"] = intervals_overlap(
                by_root[roots[0]], by_root[roots[1]]
            )
        if args.scenario == "two-each" and len(roots) == 4:
            report["checks"]["xingtu_serial"] = not intervals_overlap(
                by_root[roots[0]], by_root[roots[1]]
            )
            report["checks"]["juxing_serial"] = not intervals_overlap(
                by_root[roots[2]], by_root[roots[3]]
            )
            report["checks"]["cross_platform_overlap"] = intervals_overlap(
                by_root[roots[0]], by_root[roots[2]]
            )
        (args.out / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str), flush=True)
        return 0 if all(report["checks"].values()) else 1
    finally:
        sampler.stop()
        if driver is not None:
            with suppress(Exception):
                driver.mcp.close()


if __name__ == "__main__":
    raise SystemExit(main())
