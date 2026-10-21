"""Measure the hybrid Worker -> PostgreSQL link without changing business data.

Why
---
The 2026-10-20 hybrid regression was not a browser slowdown: the Worker reads and rewrites the
whole JSONB checkpoint on every collection step, and the cloud PostgreSQL is reached through the
Tencent Cloud public egress (Tailscale direct).  This probe separates three numbers that the
Worker log alone cannot:

* per-query latency on one existing connection (RTT / server);
* full-checkpoint transfer time (the old ``Repository.get`` path);
* small progress-write time, measured on a session-local TEMP TABLE so no production row is
  modified.

It is read-only with respect to application tables.  The write benchmark only creates a TEMP
TABLE in this session and rolls it back.

Usage
-----
    set -a; source .runtime/cloud-worker.env; set +a
    .venv/bin/python scripts/diag/hybrid_db_latency.py --root-task-id <uuid>

Or omit ``--root-task-id`` to select the newest task with a non-trivial checkpoint.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from xingtu.repository import Repository  # noqa: E402


def _summary(values: list[float]) -> dict[str, float]:
    return {
        "min_ms": round(min(values), 1),
        "median_ms": round(statistics.median(values), 1),
        "max_ms": round(max(values), 1),
    }


def _timed(fn, samples: int) -> tuple[dict[str, float], Any]:
    values: list[float] = []
    result: Any = None
    for _ in range(samples):
        started = time.monotonic()
        result = fn()
        values.append((time.monotonic() - started) * 1000)
    return _summary(values), result


def _newest_task(conn) -> str:
    row = conn.execute(
        """SELECT r.root_task_id FROM root_tasks r
           JOIN task_checkpoints c ON c.task_id=(r.payload->>'task_id')::uuid
           ORDER BY length(c.payload::text) DESC, r.created_at DESC LIMIT 1"""
    ).fetchone()
    if not row:
        raise SystemExit("no task with a checkpoint found")
    return str(row["root_task_id"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root-task-id", default=None)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    dsn = os.environ.get("XINGTU_DATABASE_URL")
    if not dsn:
        raise SystemExit("XINGTU_DATABASE_URL is required")
    repo = Repository(dsn)

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        root = args.root_task_id or _newest_task(conn)
        task_row = conn.execute(
            """SELECT r.state, r.version, pg_column_size(r.payload) AS root_bytes,
                      pg_column_size(c.payload) AS checkpoint_bytes,
                      length(c.payload::text) AS checkpoint_text_bytes,
                      (c.payload->>'active_seconds')::float8 AS active_seconds
               FROM root_tasks r
               JOIN task_checkpoints c ON c.task_id=(r.payload->>'task_id')::uuid
               WHERE r.root_task_id=%s""",
            (root,),
        ).fetchone()
        if task_row is None:
            raise SystemExit(f"task not found: {root}")
        candidate = conn.execute(
            """SELECT cand->'ref'->>'platform_creator_id' AS identity
               FROM task_checkpoints c
               JOIN root_tasks r ON c.task_id=(r.payload->>'task_id')::uuid
               CROSS JOIN LATERAL jsonb_array_elements(c.payload->'candidates') cand
               WHERE r.root_task_id=%s ORDER BY (cand->>'valid')::bool DESC LIMIT 1""",
            (root,),
        ).fetchone()
        identity = candidate["identity"] if candidate else None

    connect_summary, _ = _timed(
        lambda: _connect_probe(dsn),
        args.samples,
    )
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        small_summary, _ = _timed(lambda: conn.execute("SELECT 1").fetchone(), args.samples)
        text_bytes = int(task_row["checkpoint_text_bytes"])
        transfer_summary, _ = _timed(
            lambda: conn.execute("SELECT repeat('x', %s) AS body", (text_bytes,)).fetchone(),
            max(1, args.samples // 2),
        )
    get_summary, _ = _timed(lambda: repo.get(root), max(1, args.samples // 2))
    module_summary = valid_summary = None
    if identity:
        module_summary, module_map = _timed(
            lambda: repo.candidate_module_complete(root, identity), args.samples
        )
        valid_summary, valid = _timed(lambda: repo.candidate_valid(root, identity), args.samples)
    else:
        module_map, valid = {}, None

    # Session-local write benchmark: copy the actual payload into a TEMP TABLE, then run the same
    # server-side jsonb update shape the new progress path uses.  No application row is written.
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        payload = conn.execute(
            """SELECT c.payload FROM task_checkpoints c
               JOIN root_tasks r ON c.task_id=(r.payload->>'task_id')::uuid
               WHERE r.root_task_id=%s""",
            (root,),
        ).fetchone()["payload"]
        conn.execute("CREATE TEMP TABLE hybrid_probe(payload jsonb, revision bigint)")
        conn.execute("INSERT INTO hybrid_probe VALUES(%s, 1)", (Jsonb(payload),))

        def progress_update() -> None:
            conn.execute(
                """UPDATE hybrid_probe SET revision=revision+1,
                   payload=jsonb_set(payload,'{revision}',
                     to_jsonb(coalesce((payload->>'revision')::bigint,0)+1),true)
                   || jsonb_build_object(
                     'active_seconds',coalesce((payload->>'active_seconds')::float8,0)+%s,
                     'observed_requests',coalesce((payload->>'observed_requests')::bigint,0)+%s,
                     'module_seconds',jsonb_set(
                       coalesce(payload->'module_seconds','{}'::jsonb),ARRAY[%s],
                       to_jsonb(coalesce((payload->'module_seconds'->>%s)::float8,0)+%s),true))
                   RETURNING (payload->>'active_seconds')::float8 AS active""",
                (0.5, 1, "probe", "probe", 0.25),
            ).fetchone()

        progress_summary, _ = _timed(progress_update, args.samples)
        conn.rollback()

    report = {
        "probe": "hybrid_db_latency",
        "root_task_id": root,
        "task_state": task_row["state"],
        "checkpoint": {
            "column_bytes": int(task_row["checkpoint_bytes"] or 0),
            "text_bytes": text_bytes,
            "active_seconds": task_row["active_seconds"],
        },
        "candidate": {"identity": identity, "modules": module_map, "valid": valid},
        "latency": {
            "connect_and_select1": connect_summary,
            "select1_reused_connection": small_summary,
            "full_checkpoint_read": get_summary,
            "same_bytes_transfer": transfer_summary,
            "candidate_module_complete": module_summary,
            "candidate_valid": valid_summary,
            "progress_update_temp_table": progress_summary,
        },
        "note": (
            "full_checkpoint_read uses Repository.get and includes connect + root + checkpoint; "
            "progress_update_temp_table is session-local and does not modify application rows."
        ),
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"task {root} state={task_row['state']}")
        print(
            f"checkpoint text={text_bytes / 1024:.0f} KiB "
            f"column={report['checkpoint']['column_bytes'] / 1024:.0f} KiB"
        )
        for name, value in report["latency"].items():
            if value:
                print(
                    f"{name:32s} median={value['median_ms']:8.1f} ms  "
                    f"min={value['min_ms']:.1f} max={value['max_ms']:.1f}"
                )
    return 0


def _connect_probe(dsn: str) -> None:
    with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=10) as conn:
        conn.execute("SELECT 1").fetchone()


if __name__ == "__main__":
    raise SystemExit(main())
