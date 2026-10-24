#!/usr/bin/env python3
"""RETRY-01 real UI regression with Playwright + system Chrome.

The session has no Playwright MCP tool, so this driver uses the same Playwright browser
automation directly against the project's local stack (frontend :5173 -> API :8000) and the
installed Google Chrome, which is the documented local-stage browser.

Phases (each writes JSON + screenshots under docs/evidence/assets/retry01):

    preflight  login, read the five target tasks, assert retry labels/messages, screenshots
    continue   real "继续采集" on 383474a1 (valid 2 / target 3, both counted creators incomplete)
    backfill   real "补采缺失字段" on 2cf27cbe (valid 1 / target 1, profile incomplete)
    create     normal first collection: one new target=1 task through the product form

Only the explicitly selected phase runs; no phase cancels, deletes or edits collected data.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from playwright.sync_api import Page, sync_playwright
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:5173"
OUT = ROOT / ".runtime/qa/retry01"
SHOTS = ROOT / "docs/evidence/assets/retry01"

TASKS = {
    "continue": "383474a1-40b6-4343-ac22-9a4efcdc6af7",
    "backfill": "2cf27cbe-2f86-4eb3-b70e-19b959874d21",
    "completed": "666114c3-7b84-4943-8849-dc1ce3caf33d",
    "challenge": "5542896c-d4fc-45e1-a5c4-a9e487f87a72",
    "update": "d1813612-a73a-424d-b5e2-c10cc60156f3",
    "backfill_alt": "f3aba74e-a9cc-4b05-822f-6ce3f76576d6",
}

TERMINAL = {"COMPLETED", "PARTIAL_COMPLETED", "FAILED", "FAILED_VALIDATION", "CANCELLED"}
WAITING = {
    "WAITING_FOR_LOGIN",
    "WAITING_FOR_ACCOUNT",
    "WAITING_FOR_VERIFICATION",
    "WAITING_FOR_RESOURCE",
}


def now() -> str:
    return datetime.now(UTC).astimezone().isoformat(timespec="seconds")


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / ".runtime/m3-app.env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def load_credentials() -> tuple[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / ".runtime/qa-credentials.env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    return "media-a", env["QA_MEDIA_A_PASSWORD"]


# ---------------------------------------------------------------- database facts


def db_snapshot(root: str) -> dict[str, Any]:
    dsn = load_env()["XINGTU_DATABASE_URL"]
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        row = conn.execute(
            """SELECT r.state,r.version,r.updated_at,r.completed_at,r.payload,
                      cp.payload AS checkpoint
               FROM root_tasks r
               LEFT JOIN tasks t ON t.root_task_id=r.root_task_id AND t.kind='P2-1'
               LEFT JOIN task_checkpoints cp USING(task_id)
               WHERE r.root_task_id=%s""",
            (root,),
        ).fetchone()
        assert row, root
        payload = row["payload"]
        checkpoint = row["checkpoint"] or {}
        candidates = []
        for candidate in checkpoint.get("candidates", []):
            candidates.append(
                {
                    "id": candidate["ref"]["platform_creator_id"],
                    "state": candidate.get("state"),
                    "valid": candidate.get("valid"),
                    "failure_reason": candidate.get("failure_reason"),
                    "modules": {
                        key: {
                            "observation_id": module.get("module_observation_id"),
                            "status": module.get("status"),
                        }
                        for key, module in (candidate.get("modules") or {}).items()
                    },
                    "module_history": len(candidate.get("observation_history") or []),
                    "collections": {
                        key: {
                            "observation_id": collection.get("collection_observation_id"),
                            "status": collection.get("status"),
                        }
                        for key, collection in (candidate.get("collections") or {}).items()
                    },
                    "collection_history": len(candidate.get("collection_history") or []),
                    "snapshot_count": len(candidate.get("snapshot_ids") or []),
                }
            )
        snapshots = conn.execute(
            "SELECT count(*) AS n, max(created_at) AS last FROM creator_snapshots "
            "WHERE root_task_id=%s",
            (root,),
        ).fetchone()
        audit = [
            item["action"]
            for item in conn.execute(
                "SELECT action FROM audit_logs WHERE root_task_id=%s ORDER BY id DESC LIMIT 8",
                (root,),
            ).fetchall()
        ]
        return {
            "root_task_id": root,
            "state": row["state"],
            "version": row["version"],
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
            "valid_count": payload.get("valid_count"),
            "profile_complete_count": payload.get("profile_complete_count"),
            "featured_complete_count": payload.get("featured_complete_count"),
            "pipeline_complete": payload.get("pipeline_complete"),
            "failure_reason": payload.get("failure_reason"),
            "task_kind": payload.get("task_kind"),
            "checkpoint": {
                "cursor": checkpoint.get("cursor"),
                "search_generation": checkpoint.get("search_generation"),
                "exhausted": checkpoint.get("exhausted"),
                "processed_operations": len(checkpoint.get("processed_operations") or []),
                "navigation_count": checkpoint.get("navigation_count"),
                "observed_requests": checkpoint.get("observed_requests"),
                "scanned_ids": len(checkpoint.get("scanned_ids") or []),
                "failure_counts": checkpoint.get("failure_counts"),
            },
            "candidates": candidates,
            "snapshots": {
                "count": snapshots["n"],
                "last": snapshots["last"].isoformat() if snapshots["last"] else None,
            },
            "audit": audit,
        }


# ---------------------------------------------------------------- UI helpers


def login(page: Page) -> dict[str, Any]:
    username, password = load_credentials()
    page.goto(f"{BASE}/login", wait_until="networkidle")
    page.get_by_placeholder("请输入账号").fill(username)
    page.get_by_placeholder("请输入密码").fill(password)
    page.get_by_role("button", name="安全登录").click()
    page.wait_for_url(re.compile(r".*/tasks.*"), timeout=30_000)
    return page.evaluate("fetch('/api/auth/me').then(r=>r.json())")


def api(page: Page, path: str) -> dict[str, Any]:
    response = page.context.request.get(f"{BASE}{path}")
    assert response.ok, (path, response.status, response.text())
    return response.json()


def post_json(
    page: Page, path: str, body: dict[str, Any], headers: dict[str, str]
) -> tuple[int, dict[str, Any]]:
    response = page.context.request.post(f"{BASE}{path}", data=body, headers=headers)
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001 - error bodies are JSON in production, but keep it robust
        payload = {"raw": response.text()}
    return response.status, payload


def task_detail(page: Page, root: str) -> dict[str, Any]:
    return api(page, f"/api/tasks/{root}")


def retry_button(page: Page):
    return page.get_by_role("button", name=re.compile(r"^(继续采集|补采缺失字段|重试失败步骤)"))


def attention_text(page: Page) -> str:
    panel = page.locator(".attention-panel p").first
    return panel.inner_text() if panel.count() else ""


def shot(page: Page, name: str) -> str:
    path = SHOTS / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return str(path.relative_to(ROOT))


def save(phase: str, data: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{phase}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def new_page(browser, width: int = 1440, height: int = 1000) -> Page:
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()
    page.set_default_timeout(20_000)
    return page


# ---------------------------------------------------------------- phases


def phase_preflight(browser) -> int:
    page = new_page(browser)
    console_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    user = login(page)
    units = api(page, "/api/execution-units")
    result: dict[str, Any] = {
        "phase": "preflight",
        "at": now(),
        "user": user.get("username"),
        "units": [
            {
                "unit_id": unit["unit_id"],
                "state": unit["state"],
                "worker_status": unit["worker_status"],
                "browser_status": unit["browser_status"],
                "verification_state": unit["verification_state"],
            }
            for unit in units
        ],
        "tasks": {},
        "console_errors": console_errors,
    }

    expectations = {
        "continue": ("继续采集（还差 1 位）", "不会重新采集已入库达人"),
        "backfill": ("补采缺失字段（1 位）", "不会新增达人"),
        "completed": (None, None),
        "challenge": (None, "安全验证"),
        "update": ("重试失败步骤", None),
    }
    for name, (label, message_part) in expectations.items():
        root = TASKS[name]
        detail = task_detail(page, root)
        page.goto(f"{BASE}/tasks/{root}", wait_until="networkidle")
        page.wait_for_timeout(700)
        button_text = retry_button(page).inner_text() if retry_button(page).count() else None
        attention = attention_text(page)
        result["tasks"][name] = {
            "root_task_id": root,
            "status": detail["status"],
            "counts": detail["counts"],
            "allowed_actions": detail["allowed_actions"],
            "failure_reason": detail.get("failure_reason"),
            "retry_plan": detail.get("retry_plan"),
            "button": button_text,
            "attention": attention,
            "screenshot": shot(page, f"preflight-{name}"),
            "db": db_snapshot(root),
        }
        ok = True
        if label is None:
            ok = button_text is None
        else:
            ok = button_text == label
        if message_part is not None:
            ok = ok and message_part in attention
        result["tasks"][name]["assert_ok"] = ok
    save("preflight", result)
    print(json.dumps({k: v["assert_ok"] for k, v in result["tasks"].items()}, ensure_ascii=False))
    print(json.dumps(result["units"], ensure_ascii=False))
    return 0 if all(v["assert_ok"] for v in result["tasks"].values()) else 2


def _run_retry(browser, phase: str, root: str, timeout_seconds: int) -> int:
    page = new_page(browser)
    console_errors: list[str] = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    login(page)
    before = db_snapshot(root)
    detail = task_detail(page, root)
    page.goto(f"{BASE}/tasks/{root}", wait_until="networkidle")
    page.wait_for_timeout(700)
    button = retry_button(page)
    label = button.inner_text()
    expected = "继续采集" if phase == "continue" else "补采缺失字段"
    result: dict[str, Any] = {
        "phase": phase,
        "at": now(),
        "root_task_id": root,
        "button": label,
        "button_ok": label.startswith(expected),
        "status_before": detail["status"],
        "retry_plan_before": detail.get("retry_plan"),
        "attention": attention_text(page),
        "before": before,
        "screenshot_before": shot(page, f"{phase}-before"),
        "console_errors": console_errors,
    }

    # Cancel path first: the confirmation must appear and no request may be sent.
    dialogs: list[str] = []
    decisions = {"accept": False}

    def on_dialog(dialog) -> None:
        dialogs.append(dialog.message)
        dialog.accept() if decisions["accept"] else dialog.dismiss()

    page.on("dialog", on_dialog)
    posts: list[str] = []
    page.on(
        "request",
        lambda request: (
            posts.append(request.url)
            if request.method == "POST" and "/retry" in request.url
            else None
        ),
    )
    button.click()
    page.wait_for_timeout(500)
    result["confirm_text"] = dialogs[0] if dialogs else None
    result["cancel_sent_no_request"] = len(posts) == 0
    page.wait_for_timeout(300)

    decisions["accept"] = True
    button.click()
    page.wait_for_timeout(300)
    result["accept_sent_request"] = len(posts) == 1
    transitions: list[dict[str, Any]] = []
    deadline = time.time() + timeout_seconds
    waiting_since: float | None = None
    while time.time() < deadline:
        current = task_detail(page, root)
        transitions.append({"at": now(), "status": current["status"], "counts": current["counts"]})
        if current["status"] in TERMINAL:
            break
        if current["status"] in WAITING:
            waiting_since = waiting_since or time.time()
            if time.time() - waiting_since > 120:
                result["blocked_waiting"] = current["status"]
                break
        else:
            waiting_since = None
        page.wait_for_timeout(10_000)
    final = task_detail(page, root)
    page.goto(f"{BASE}/tasks/{root}", wait_until="networkidle")
    page.wait_for_timeout(1000)
    result.update(
        {
            "transitions": transitions,
            "status_after": final["status"],
            "counts_after": final["counts"],
            "retry_plan_after": final.get("retry_plan"),
            "failure_reason_after": final.get("failure_reason"),
            "button_after": retry_button(page).inner_text() if retry_button(page).count() else None,
            "attention_after": attention_text(page),
            "screenshot_after": shot(page, f"{phase}-after"),
            "after": db_snapshot(root),
            "finished_at": now(),
        }
    )
    save(phase, result)
    print(
        json.dumps(
            {
                "phase": phase,
                "button": label,
                "status_after": final["status"],
                "before": before["valid_count"],
                "after": final["counts"]["valid_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if result["button_ok"] and result["cancel_sent_no_request"] else 2


def phase_continue(browser) -> int:
    return _run_retry(browser, "continue", TASKS["continue"], timeout_seconds=900)


def phase_backfill(browser) -> int:
    return _run_retry(browser, "backfill", TASKS["backfill"], timeout_seconds=900)


def phase_api(browser) -> int:
    """Negative API checks that must not start a collection."""
    page = new_page(browser)
    login(page)
    me = api(page, "/api/auth/me")
    headers = {"X-CSRF-Token": me["csrf_token"], "Origin": BASE}
    result: dict[str, Any] = {"phase": "api", "at": now(), "checks": {}}
    for name in ("completed", "challenge"):
        root = TASKS[name]
        detail = task_detail(page, root)
        status, body = post_json(
            page,
            f"/api/tasks/{root}/retry",
            {"expected_version": detail["version"]},
            headers,
        )
        result["checks"][name] = {
            "task_status": detail["status"],
            "allowed_actions": detail["allowed_actions"],
            "retry_plan": detail.get("retry_plan"),
            "http_status": status,
            "error": body.get("code") or body.get("message"),
        }
    save("api", result)
    print(json.dumps(result["checks"], ensure_ascii=False))
    ok = all(item["http_status"] >= 400 for item in result["checks"].values())
    return 0 if ok else 2


def phase_create(browser) -> int:
    page = new_page(browser)
    login(page)
    page.goto(f"{BASE}/tasks/new", wait_until="networkidle")
    page.wait_for_timeout(1500)
    page.get_by_placeholder(re.compile(r"例如：宠物")).fill("宠物")
    target = page.locator('input[type="number"][step="1"]').first
    target.fill("1")
    page.get_by_role("button", name="提交采集任务").click()
    page.wait_for_url(re.compile(r".*/tasks/[0-9a-f-]{36}"), timeout=60_000)
    root = page.url.rstrip("/").split("/")[-1]
    transitions: list[dict[str, Any]] = []
    deadline = time.time() + 900
    while time.time() < deadline:
        current = task_detail(page, root)
        transitions.append({"at": now(), "status": current["status"], "counts": current["counts"]})
        if current["status"] in TERMINAL:
            break
        page.wait_for_timeout(10_000)
    final = task_detail(page, root)
    page.goto(f"{BASE}/tasks/{root}", wait_until="networkidle")
    page.wait_for_timeout(800)
    result = {
        "phase": "create",
        "at": now(),
        "root_task_id": root,
        "transitions": transitions,
        "status_after": final["status"],
        "counts_after": final["counts"],
        "failure_reason_after": final.get("failure_reason"),
        "retry_plan_after": final.get("retry_plan"),
        "screenshot": shot(page, "create-after"),
        "db": db_snapshot(root),
    }
    save("create", result)
    print(
        json.dumps(
            {"root": root, "status": result["status_after"], "counts": result["counts_after"]},
            ensure_ascii=False,
        )
    )
    return 0 if final["status"] in TERMINAL else 2


PHASES = {
    "preflight": phase_preflight,
    "api": phase_api,
    "continue": phase_continue,
    "backfill": phase_backfill,
    "create": phase_create,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=sorted(PHASES))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".runtime/browsers"))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            return PHASES[args.phase](browser)
        finally:
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
