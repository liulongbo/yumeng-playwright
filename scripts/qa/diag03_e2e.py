#!/usr/bin/env python3
"""DIAG-03 real acceptance: continue task 8013a009 from 20/24 to 24/24 via MCP + Chrome.

Uses the same Playwright MCP stdio client and system Chrome as the RETRY-01 acceptance, but
keeps its own evidence directory.  The driver:

1. logs in to the product frontend and opens the failed task;
2. asserts the goal-aware label and confirmation, then performs the real retry;
3. polls the task API until a terminal state (or records a human-verification block);
4. verifies the API/DB/UI counts, page-two evidence and non-revisits;
5. writes JSON + screenshots under docs/evidence/assets/diag03 and .runtime/qa/diag03.

Only the directly needed write (the existing task retry) is performed.  No task is created or
deleted, no creator is deleted, and no platform challenge is bypassed.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import retry01_mcp_acceptance as acc  # noqa: E402
from mcp_client import PlaywrightMCP  # noqa: E402
from retry01_e2e import load_env  # noqa: E402

ROOT_TASK = "8013a009-c058-441e-a99f-9976c7d48df0"
BASE = "http://127.0.0.1:5173"
OUT = ROOT / ".runtime/qa/diag03"
SHOTS = ROOT / "docs/evidence/assets/diag03"
TERMINAL = {"COMPLETED", "PARTIAL_COMPLETED", "FAILED", "FAILED_VALIDATION", "CANCELLED"}
WAITING = {
    "WAITING_FOR_LOGIN",
    "WAITING_FOR_ACCOUNT",
    "WAITING_FOR_VERIFICATION",
    "WAITING_FOR_RESOURCE",
}

# Let the imported helpers write their JSON/screenshots to this task's evidence directory.
acc.OUT = OUT
acc.SHOTS = SHOTS


def now() -> str:
    return datetime.now(UTC).astimezone().isoformat(timespec="seconds")


def save(name: str, data: dict[str, Any]) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    return path


def evaluate(mcp: PlaywrightMCP, function: str, filename: str) -> Any:
    return acc.evaluate(mcp, function, filename)


def shot(mcp: PlaywrightMCP, name: str) -> str:
    return acc.shot(mcp, name)


def db_facts(root: str) -> dict[str, Any]:
    dsn = load_env()["XINGTU_DATABASE_URL"]
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        task = conn.execute(
            """SELECT r.state,r.version,r.updated_at,r.completed_at,r.payload,
                      cp.payload AS checkpoint
               FROM root_tasks r
               LEFT JOIN tasks t ON t.root_task_id=r.root_task_id AND t.kind='P2-1'
               LEFT JOIN task_checkpoints cp USING(task_id)
               WHERE r.root_task_id=%s""",
            (root,),
        ).fetchone()
        assert task, root
        payload = task["payload"]
        checkpoint = task["checkpoint"] or {}
        candidates = checkpoint.get("candidates", [])
        attempts = conn.execute(
            "SELECT attempt_id,segment,created_at FROM task_attempts "
            "WHERE root_task_id=%s ORDER BY segment",
            (root,),
        ).fetchall()
        audit = conn.execute(
            "SELECT action,created_at FROM audit_logs WHERE root_task_id=%s "
            "ORDER BY created_at DESC LIMIT 5",
            (root,),
        ).fetchall()
        creators = conn.execute(
            "SELECT count(*) AS n,count(DISTINCT creator_id) AS distinct_creators,"
            "min(first_position) AS min_pos,max(first_position) AS max_pos "
            "FROM task_creators WHERE root_task_id=%s AND valid=true",
            (root,),
        ).fetchone()
        snapshots = conn.execute(
            "SELECT count(*) AS n,count(DISTINCT creator_id) AS distinct_creators "
            "FROM creator_snapshots WHERE root_task_id=%s",
            (root,),
        ).fetchone()
        task_creator_ids = conn.execute(
            "SELECT tc.first_position,pc.platform_creator_id,tc.latest_snapshot_id "
            "FROM task_creators tc JOIN platform_creators pc USING(creator_id) "
            "WHERE tc.root_task_id=%s ORDER BY tc.first_position",
            (root,),
        ).fetchall()
        new_positions = [row for row in task_creator_ids if int(row["first_position"]) >= 20]
        duplicate_task_creators = conn.execute(
            "SELECT count(*) AS n FROM (SELECT creator_id FROM task_creators "
            "WHERE root_task_id=%s GROUP BY creator_id HAVING count(*)>1) d",
            (root,),
        ).fetchone()
        unit = conn.execute(
            "SELECT state,owner,lease_until,browser_stopped,current_root_task_id "
            "FROM execution_units WHERE unit_id=%s",
            (payload.get("execution_unit_id"),),
        ).fetchone()
    return {
        "task": {
            "state": task["state"],
            "version": task["version"],
            "updated_at": task["updated_at"],
            "completed_at": task["completed_at"],
            "valid_count": payload.get("valid_count"),
            "target_count": payload.get("target_count"),
            "failure_reason": payload.get("failure_reason"),
            "segment": payload.get("segment"),
            "profile_complete_count": payload.get("profile_complete_count"),
            "featured_complete_count": payload.get("featured_complete_count"),
            "featured_status": payload.get("featured_status"),
        },
        "checkpoint": {
            "candidates": len(candidates),
            "valid_candidates": sum(1 for c in candidates if c.get("valid")),
            "cursor": checkpoint.get("cursor"),
            "visited_cursors": checkpoint.get("visited_cursors"),
            "exhausted": checkpoint.get("exhausted"),
            "search_generation": checkpoint.get("search_generation"),
            "no_progress_pages": checkpoint.get("no_progress_pages"),
            "processed_operations": checkpoint.get("processed_operations"),
            "scanned_ids": len(checkpoint.get("scanned_ids") or []),
            "pending_page": checkpoint.get("pending_page") is not None,
            "failure_counts": checkpoint.get("failure_counts"),
            "search_stop_reason": checkpoint.get("search_stop_reason"),
        },
        "attempts": attempts,
        "audit": audit,
        "task_creators": creators,
        "creator_snapshots": snapshots,
        "task_creator_ids": task_creator_ids,
        "new_page_creators": new_positions,
        "duplicate_task_creator_rows": duplicate_task_creators["n"],
        "unit": unit,
    }


def chrome_profile_history(since: datetime, limit: int = 100) -> list[dict[str, Any]]:
    """Read the unit profile's Chrome History after ``since``; never mutate it."""

    profile = ROOT / ".runtime/profiles/unit-local-mac-02/Default/History"
    if not profile.exists():
        return []
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "History"
        shutil.copy2(profile, copy)
        for suffix in ("-wal", "-shm"):
            sidecar = profile.with_name(profile.name + suffix)
            if sidecar.exists():
                shutil.copy2(sidecar, copy.with_name(copy.name + suffix))
        with sqlite3.connect(str(copy)) as conn:
            rows = conn.execute(
                "SELECT url,title,last_visit_time FROM urls "
                "WHERE last_visit_time > 0 ORDER BY last_visit_time DESC LIMIT ?",
                (limit,),
            ).fetchall()
    # Chrome stores microseconds since 1601-01-01 UTC.
    chrome_epoch = 11644473600
    threshold = int(since.timestamp()) + chrome_epoch
    result = []
    for url, title, visit_time in rows:
        visited = datetime.fromtimestamp((visit_time / 1_000_000) - chrome_epoch, UTC)
        if int(visit_time / 1_000_000) < threshold:
            continue
        result.append({"url": url, "title": title, "visited_at": visited.isoformat()})
    return result


def creator_homepage_visits(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in history if "author-homepage" in row["url"]]


def wait_terminal(
    mcp: PlaywrightMCP, root: str, timeout: float
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str | None]:
    transitions: list[dict[str, Any]] = []
    deadline = time.time() + timeout
    last: dict[str, Any] | None = None
    while time.time() < deadline:
        current = evaluate(
            mcp,
            f"async () => await (await fetch('/api/tasks/{root}')).json()",
            "status-diag03.json",
        )
        last = current
        transitions.append(
            {"at": now(), "status": current.get("status"), "counts": current.get("counts")}
        )
        if current.get("status") in TERMINAL:
            return current, transitions, None
        if current.get("status") in WAITING:
            return current, transitions, current.get("status")
        time.sleep(5)
    return last, transitions, "TIMEOUT"


def ui_rows(mcp: PlaywrightMCP, filename: str) -> dict[str, Any]:
    return evaluate(
        mcp,
        """() => ({
          rows: document.querySelectorAll('.creator-row').length,
          hasMore: Array.from(document.querySelectorAll('button'))
            .some((button) => button.innerText.includes('查看更多达人')),
          bodyHas24: document.body.innerText.includes('24 / 24'),
          bodyHasFailed: document.body.innerText.includes('执行失败'),
        })""",
        filename,
    )


def wait_rows(mcp: PlaywrightMCP, minimum: int = 1, timeout: float = 15) -> dict[str, Any]:
    deadline = time.time() + timeout
    rows = ui_rows(mcp, "ui-rows-wait.json")
    while rows["rows"] < minimum and time.time() < deadline:
        time.sleep(0.5)
        rows = ui_rows(mcp, "ui-rows-wait.json")
    return rows


def click_more(mcp: PlaywrightMCP) -> bool:
    snapshot = mcp.call_text("browser_snapshot")
    ref = acc.find_ref(snapshot, "查看更多达人")
    if not ref:
        return False
    mcp.call("browser_click", {"target": ref, "element": "查看更多达人"})
    for _ in range(20):
        time.sleep(0.5)
        rows = ui_rows(mcp, "ui-rows-more.json")
        if rows["rows"] > 20 or not rows["hasMore"]:
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=ROOT_TASK)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--headless", action="store_true", default=True)
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    mcp = PlaywrightMCP(
        OUT / "server",
        headless=args.headless,
        log_path=ROOT / ".runtime/logs/diag03-mcp-server.log",
    )
    result: dict[str, Any] = {
        "root_task_id": args.root,
        "at": now(),
        "transport": "playwright-mcp",
        "root": str(ROOT),
    }
    try:
        info = mcp.initialize()
        result["mcp"] = {"server": info.get("serverInfo"), "tools": len(mcp.tools())}
        acc.login(mcp)
        before = db_facts(args.root)
        snapshot = acc.open_task(mcp, args.root)
        detail_before = evaluate(
            mcp,
            f"async () => await (await fetch('/api/tasks/{args.root}')).json()",
            "detail-before.json",
        )
        result["before"] = before
        result["detail_before"] = detail_before
        result["button_before"] = acc.retry_label(snapshot)
        result["screenshot_before"] = shot(mcp, "continue-before")
        result["ui_before"] = wait_rows(mcp, 20)

        label, dialog = acc.click_retry(mcp, snapshot)
        result["button_clicked"] = label
        result["dialog"] = dialog
        acc.handle_dialog(mcp, accept=True)
        time.sleep(1)
        result["retry_requests"] = acc.retry_requests(mcp)
        retry_started = datetime.now(UTC)
        result["retry_started_at"] = retry_started.isoformat()

        final, transitions, blocked = wait_terminal(mcp, args.root, args.timeout)
        result["transitions"] = transitions
        result["blocked_status"] = blocked
        result["final"] = final
        if blocked:
            result["outcome"] = "BLOCKED"
            save("continue-blocked", result)
            print(json.dumps({"outcome": "BLOCKED", "status": blocked}, ensure_ascii=False))
            return 2

        after = db_facts(args.root)
        result["after"] = after
        acc.open_task(mcp, args.root)
        result["button_after"] = acc.retry_label(mcp.call_text("browser_snapshot"))
        result["screenshot_after"] = shot(mcp, "continue-after")
        result["ui_after_initial"] = wait_rows(mcp, 20)
        result["more_clicked"] = click_more(mcp)
        result["ui_after_more"] = ui_rows(mcp, "ui-rows-after-more.json")
        result["screenshot_after_more"] = shot(mcp, "continue-after-more")
        result["console_errors"] = mcp.call_text(
            "browser_console_messages", {"level": "error", "all": True}
        )
        result["units"] = evaluate(
            mcp,
            "async () => await (await fetch('/api/execution-units')).json()",
            "units-after.json",
        )
        history = chrome_profile_history(retry_started)
        result["unit_profile_history"] = creator_homepage_visits(history)
        result["unit_profile_history_all"] = history[:20]
        result["finished_at"] = now()

        old_ids = {row["platform_creator_id"] for row in before["task_creator_ids"]}
        new_ids = {row["platform_creator_id"] for row in after["new_page_creators"]}
        visited_ids: set[str] = set()
        for row in result["unit_profile_history"]:
            match = re.search(r"/douyin-video/(\d+)", row["url"])
            if match:
                visited_ids.add(match.group(1))
        result["history_creator_ids"] = sorted(visited_ids)

        final_status = (final or {}).get("status")
        counts = (final or {}).get("counts") or {}
        checks = {
            "not_failed": final_status != "FAILED",
            "valid_24": counts.get("valid_count") == 24,
            "target_24": counts.get("target_count") == 24,
            "attempts_increased": len(after["attempts"]) > len(before["attempts"]),
            "four_new_page_creators": len(after["new_page_creators"]) == 4,
            "new_creator_ids_recorded": len(new_ids) == 4,
            "task_creators_24": after["task_creators"]["n"] == 24,
            "no_duplicate_task_creators": after["duplicate_task_creator_rows"] == 0,
            "page_two_processed": len(after["checkpoint"]["processed_operations"] or []) >= 2,
            "no_revisit_counted_creators": not (visited_ids & old_ids),
            "ui_24_after_more": result["ui_after_more"]["rows"] == 24,
            "ui_not_execution_failed": not result["ui_after_more"]["bodyHasFailed"],
        }
        result["checks"] = checks
        result["outcome"] = "PASS" if all(checks.values()) else "PARTIAL"
        # Keep the structured evidence next to the screenshots as well.
        (SHOTS / "continue-evidence.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str)
        )
        save("continue", result)
        print(
            json.dumps(
                {
                    "outcome": result["outcome"],
                    "status": final_status,
                    "counts": counts,
                    "checks": checks,
                    "button_before": result["button_before"],
                    "button_after": result["button_after"],
                },
                ensure_ascii=False,
            )
        )
        return 0 if result["outcome"] == "PASS" else 2
    except Exception as exc:  # noqa: BLE001 - persist the failure for the report
        result["outcome"] = "ERROR"
        result["error"] = f"{type(exc).__name__}: {exc}"
        save("continue-error", result)
        print(json.dumps({"outcome": "ERROR", "error": result["error"]}, ensure_ascii=False))
        return 3
    finally:
        mcp.close()


if __name__ == "__main__":
    sys.exit(main())
