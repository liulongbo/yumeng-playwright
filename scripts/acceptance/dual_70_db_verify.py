#!/usr/bin/env python3
"""Read-only PostgreSQL verification for one DUAL-70-01 root task.

The acceptance judgement is the number of *distinct, valid creators persisted for this task*, never
the candidate count, page row count or attempt count.  This script therefore reconciles the task
records, the checkpoint and the published tables independently, and reports aggregate field
coverage without printing creator names or platform ids.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

import psycopg

ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DUAL-70-01 read-only DB verification")
    parser.add_argument("--root-task-id", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--baseline-root-tasks", type=int, default=None)
    parser.add_argument("--database-url", default=os.environ.get("XINGTU_DATABASE_URL"))
    return parser.parse_args()


def one(conn: psycopg.Connection[dict[str, Any]], sql: str, params: tuple[Any, ...]) -> Any:
    row = conn.execute(sql, params).fetchone()
    return None if row is None else next(iter(row.values()))


def scalar(conn: psycopg.Connection[dict[str, Any]], sql: str, params: tuple[Any, ...]) -> Any:
    row = conn.execute(sql, params).fetchone()
    return None if row is None else dict(row)


def main() -> int:
    args = parse_args()
    if not args.database_url:
        raise SystemExit("XINGTU_DATABASE_URL or --database-url required")
    root = args.root_task_id
    with psycopg.connect(args.database_url, row_factory=psycopg.rows.dict_row) as conn:
        task = scalar(
            conn,
            "SELECT root_task_id, platform, state, task_kind, created_at, completed_at, payload "
            "FROM root_tasks WHERE root_task_id=%s",
            (root,),
        )
        if task is None:
            raise SystemExit("root task not found")
        requirement = scalar(
            conn,
            "SELECT payload FROM requirements WHERE root_task_id=%s",
            (root,),
        )
        plan = scalar(
            conn,
            "SELECT payload FROM filter_plans WHERE root_task_id=%s",
            (root,),
        )
        checkpoint_row = scalar(
            conn,
            "SELECT c.payload FROM task_checkpoints c JOIN tasks t ON t.task_id=c.task_id "
            "WHERE t.root_task_id=%s AND t.kind='P2-1'",
            (root,),
        )
        checkpoint = (checkpoint_row or {}).get("payload") or {}
        creator_counts = scalar(
            conn,
            "SELECT count(*) AS total_rows, count(DISTINCT tc.creator_id) AS distinct_creators, "
            "count(DISTINCT pc.platform_creator_id) AS distinct_platform_ids, "
            "count(*) FILTER (WHERE tc.valid) AS valid_rows "
            "FROM task_creators tc JOIN platform_creators pc USING(creator_id) "
            "WHERE tc.root_task_id=%s",
            (root,),
        )
        duplicate_positions = one(
            conn,
            "SELECT count(*) FROM (SELECT first_position FROM task_creators "
            "WHERE root_task_id=%s GROUP BY first_position HAVING count(*)>1) duplicated",
            (root,),
        )
        snapshots = scalar(
            conn,
            "SELECT count(*) AS snapshots, count(DISTINCT creator_id) AS distinct_creators "
            "FROM creator_snapshots WHERE root_task_id=%s",
            (root,),
        )
        platform_rows = conn.execute(
            "SELECT pc.platform, count(*) AS rows FROM task_creators tc "
            "JOIN platform_creators pc USING(creator_id) WHERE tc.root_task_id=%s GROUP BY 1",
            (root,),
        ).fetchall()
        featured = one(
            conn, "SELECT count(*) FROM featured_collections WHERE root_task_id=%s", (root,)
        )
        raw_evidence = one(conn, "SELECT count(*) FROM raw_evidence WHERE root_task_id=%s", (root,))
        snapshot_collections = one(
            conn,
            "SELECT count(*) FROM snapshot_collections sc "
            "JOIN creator_snapshots cs ON cs.snapshot_id=sc.creator_snapshot_id "
            "WHERE cs.root_task_id=%s",
            (root,),
        )
        projection_rows = None
        if task["platform"] == "douyin_xingtu":
            projection_rows = one(
                conn,
                "SELECT count(*) FROM douyin_xingtu_creator_current cur "
                "JOIN task_creators tc ON tc.creator_id=cur.creator_id "
                "WHERE tc.root_task_id=%s AND tc.valid",
                (root,),
            )
        else:
            projection_rows = one(
                conn,
                "SELECT count(*) FROM douyin_xingtu_creator_current cur "
                "JOIN task_creators tc ON tc.creator_id=cur.creator_id "
                "WHERE tc.root_task_id=%s",
                (root,),
            )
        dispatches = scalar(
            conn,
            "SELECT count(*) AS segments, json_agg(json_build_object("
            "'segment', segment, 'sent', sent) ORDER BY segment) AS detail "
            "FROM task_dispatches WHERE root_task_id=%s",
            (root,),
        )
        attempts = scalar(
            conn,
            "SELECT count(*) AS attempts, json_agg(json_build_object("
            "'segment', segment, 'created_at', created_at) ORDER BY segment) AS detail "
            "FROM task_attempts WHERE root_task_id=%s",
            (root,),
        )
        unit_id = (task["payload"] or {}).get("execution_unit_id")
        unit = (
            scalar(
                conn,
                "SELECT unit_id, state, current_root_task_id, browser_stopped "
                "FROM execution_units WHERE unit_id=%s",
                (unit_id,),
            )
            if unit_id
            else None
        )
        before_root_tasks = one(
            conn,
            "SELECT count(*) FROM root_tasks WHERE created_at < %s",
            (task["created_at"],),
        )
        # Aggregate field/module coverage from published snapshots without printing values.
        module_coverage: Counter[str] = Counter()
        complete_counts: Counter[str] = Counter()
        field_status: Counter[str] = Counter()
        for row in conn.execute(
            "SELECT payload FROM creator_snapshots WHERE root_task_id=%s", (root,)
        ).fetchall():
            payload = row["payload"] or {}
            for key, module in (payload.get("modules") or {}).items():
                module_coverage[key] += 1
                if module.get("complete"):
                    complete_counts[key] += 1
                for field in module.get("fields") or []:
                    field_status[f"{key}.{field.get('status')}"] += 1

    cp = checkpoint or {}
    requirement_payload = (requirement or {}).get("payload") or {}
    plan_payload = (plan or {}).get("payload") or {}
    task_payload = task["payload"] or {}
    payload_plan = task_payload.get("plan") or {}
    counts = {
        "target_count": plan_payload.get("target_count") or payload_plan.get("target_count"),
        "valid_count": task_payload.get("valid_count"),
        "discovered_count": len(cp.get("candidates") or []),
        "profile_complete_count": task_payload.get("profile_complete_count"),
        "featured_complete_count": task_payload.get("featured_complete_count"),
        "pipeline_complete": task_payload.get("pipeline_complete"),
        "failure_reason": task_payload.get("failure_reason"),
    }
    result = {
        "schema_version": "dual-70-db-verify.v1",
        "root_task_id": root,
        "platform": task["platform"],
        "state": task["state"],
        "task_kind": task["task_kind"],
        "created_at": str(task["created_at"]),
        "completed_at": str(task["completed_at"]) if task["completed_at"] else None,
        "targets": {
            "requirement": requirement_payload.get("target_count"),
            "plan": plan_payload.get("target_count"),
            "payload_plan": payload_plan.get("target_count"),
        },
        "counts": counts,
        "persistence": {
            "task_creators": creator_counts,
            "duplicate_first_positions": duplicate_positions,
            "snapshots": snapshots,
            "platform_rows": {row["platform"]: row["rows"] for row in platform_rows},
            "featured_collections": featured,
            "raw_evidence": raw_evidence,
            "snapshot_collections": snapshot_collections,
            "xingtu_projection_rows": projection_rows,
        },
        "checkpoint": {
            "candidates": len(cp.get("candidates") or []),
            "candidate_identities": len(
                {
                    (candidate.get("ref") or {}).get("platform_creator_id")
                    for candidate in (cp.get("candidates") or [])
                }
            ),
            "scanned_ids": len(cp.get("scanned_ids") or []),
            "visited_cursors": cp.get("visited_cursors"),
            "processed_operations": len(cp.get("processed_operations") or []),
            "exhausted": cp.get("exhausted"),
            "search_stop_reason": cp.get("search_stop_reason"),
            "no_progress_pages": cp.get("no_progress_pages"),
            "active_seconds": cp.get("active_seconds"),
            "failure_counts": cp.get("failure_counts"),
        },
        "snapshot_coverage": {
            "modules_present": dict(module_coverage),
            "modules_complete": dict(complete_counts),
            "field_status_counts": dict(field_status),
        },
        "dispatches": dispatches,
        "attempts": attempts,
        "unit": unit,
        "history": {
            "root_tasks_before_this_task": before_root_tasks,
            "baseline_root_tasks": args.baseline_root_tasks,
            "baseline_not_decreased": (
                before_root_tasks >= args.baseline_root_tasks
                if args.baseline_root_tasks is not None
                else None
            ),
        },
    }
    result["verdict"] = {
        "target_is_70": all(
            value == 70 for value in result["targets"].values() if value is not None
        ),
        "valid_count_is_70": result["counts"]["valid_count"] == 70,
        "persisted_distinct_is_70": creator_counts is not None
        and creator_counts.get("distinct_creators") == 70,
        "snapshot_distinct_is_70": snapshots is not None
        and snapshots.get("distinct_creators") == 70,
        "no_duplicate_positions": duplicate_positions == 0,
        "no_cross_platform_rows": (
            len(platform_rows) == 1 and platform_rows[0]["platform"] == task["platform"]
        ),
        "terminal": task["state"] in {"COMPLETED", "PARTIAL_COMPLETED"},
        "unit_released": bool(unit)
        and unit.get("state") == "READY"
        and unit.get("current_root_task_id") is None
        and bool(unit.get("browser_stopped")),
    }
    result["verdict"]["all_count_checks_pass"] = all(
        result["verdict"][key]
        for key in (
            "target_is_70",
            "valid_count_is_70",
            "persisted_distinct_is_70",
            "snapshot_distinct_is_70",
            "no_duplicate_positions",
            "no_cross_platform_rows",
        )
    )
    args.out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    try:
        args.out.chmod(0o600)
    except OSError:
        pass
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("root_task_id", "platform", "state", "counts", "verdict")
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["verdict"]["all_count_checks_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
