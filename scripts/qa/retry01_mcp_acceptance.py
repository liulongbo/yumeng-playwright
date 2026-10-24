#!/usr/bin/env python3
"""RETRY-01 acceptance driven by **Playwright MCP** (browser_* tools) + system Chrome.

The DSH session did not expose MCP tools directly, so this driver starts the locally installed
@playwright/mcp server over stdio (the same package the two running DSH MCP servers use) and
performs every UI action and assertion through its `browser_*` tools.  No Playwright Python page
automation is used here; only the MCP protocol.

Phases:
    preflight  login; labels/messages/counts of 5 real tasks; screenshots; console errors
    api        negative API checks for completed + security-challenge tasks (through the page)
    continue   real 继续采集 via MCP on 383474a1; dialog dismiss/accept; terminal poll; DB diff
    backfill   real 补采缺失字段 via MCP on 2cf27cbe; terminal poll; DB diff
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp_client import MCPError, PlaywrightMCP  # noqa: E402
from retry01_e2e import TASKS, db_snapshot, load_credentials, now  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:5173"
OUT = ROOT / ".runtime/qa/retry01-mcp"
SHOTS = ROOT / "docs/evidence/assets/retry01-mcp"
SERVER_OUT = OUT / "server"
TERMINAL = {"COMPLETED", "PARTIAL_COMPLETED", "FAILED", "FAILED_VALIDATION", "CANCELLED"}
WAITING = {
    "WAITING_FOR_LOGIN",
    "WAITING_FOR_ACCOUNT",
    "WAITING_FOR_VERIFICATION",
    "WAITING_FOR_RESOURCE",
}


def save(phase: str, data: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{phase}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def find_ref(snapshot: str, needle: str) -> str | None:
    for line in snapshot.splitlines():
        if needle in line:
            match = re.search(r"\[ref=([A-Za-z0-9]+)\]", line)
            if match:
                return match.group(1)
    return None


def retry_label(snapshot: str) -> str | None:
    for line in snapshot.splitlines():
        if "- button" not in line:
            continue
        for label in ("继续采集", "补采缺失字段", "重试失败步骤"):
            if label in line:
                return line.split('"')[1]
    return None


def task_text(snapshot: str) -> str:
    return "\n".join(
        line
        for line in snapshot.splitlines()
        if line.lstrip().startswith(("- text:", "- paragraph", "- generic"))
    )


def evaluate(mcp: PlaywrightMCP, function: str, filename: str) -> Any:
    path = OUT / filename
    if path.exists():
        path.unlink()
    mcp.call("browser_evaluate", {"function": function, "filename": str(path)})
    if not path.exists():
        raise MCPError(f"evaluate did not write {path}")
    return json.loads(path.read_text())


def wait_for(mcp: PlaywrightMCP, predicate, timeout: float = 30.0, interval: float = 0.5) -> Any:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    return last


def wait_path(mcp: PlaywrightMCP, fragment: str, timeout: float = 30.0) -> None:
    wait_for(
        mcp,
        lambda: (
            fragment in mcp.call_text("browser_evaluate", {"function": "() => location.pathname"})
        ),
        timeout=timeout,
    )


def login(mcp: PlaywrightMCP) -> dict[str, Any]:
    _, password = load_credentials()
    mcp.call_text("browser_navigate", {"url": f"{BASE}/login"})
    snapshot = mcp.call_text("browser_snapshot")
    user_ref = find_ref(snapshot, "产品账号")
    pass_ref = find_ref(snapshot, "密码 显示密码")
    button_ref = find_ref(snapshot, "安全登录")
    if not (user_ref and pass_ref and button_ref):
        raise MCPError("login controls not found in snapshot")
    mcp.call("browser_type", {"target": user_ref, "text": "media-a"})
    mcp.call("browser_type", {"target": pass_ref, "text": password})
    mcp.call("browser_click", {"target": button_ref, "element": "安全登录"})
    wait_path(mcp, "/tasks")
    me = evaluate(mcp, "async () => await (await fetch('/api/auth/me')).json()", "me.json")
    # The CSRF token must never be part of saved evidence; keep only the display facts.
    (OUT / "me.json").unlink(missing_ok=True)
    return {"username": me.get("username"), "display_name": me.get("display_name")}


def open_task(mcp: PlaywrightMCP, root: str) -> str:
    mcp.call_text("browser_navigate", {"url": f"{BASE}/tasks/{root}"})
    wait_for(
        mcp,
        lambda: "TASK DETAIL" in mcp.call_text("browser_snapshot"),
        timeout=20,
    )
    time.sleep(0.8)
    return mcp.call_text("browser_snapshot")


def shot(mcp: PlaywrightMCP, name: str) -> str:
    path = SHOTS / f"{name}.png"
    mcp.call("browser_take_screenshot", {"filename": str(path), "fullPage": True})
    return str(path.relative_to(ROOT))


def click_retry(mcp: PlaywrightMCP, snapshot: str) -> tuple[str, str | None]:
    label = retry_label(snapshot)
    if not label:
        raise MCPError("retry button not found")
    ref = find_ref(snapshot, f'button "{label}"')
    assert ref
    result = mcp.call_text("browser_click", {"target": ref, "element": label})
    dialog = re.search(r'dialog with message "(.*?)"', result)
    return label, dialog.group(1) if dialog else None


def handle_dialog(mcp: PlaywrightMCP, *, accept: bool) -> str:
    return mcp.call_text("browser_handle_dialog", {"accept": accept})


def retry_requests(mcp: PlaywrightMCP) -> list[str]:
    text = mcp.call_text("browser_network_requests", {"filter": "/retry"})
    return [line for line in text.splitlines() if "/retry" in line]


def poll_task(
    mcp: PlaywrightMCP, root: str, phase: str, timeout: float
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    transitions: list[dict[str, Any]] = []
    deadline = time.time() + timeout
    waiting_since: float | None = None
    while time.time() < deadline:
        current = evaluate(
            mcp,
            f"async () => await (await fetch('/api/tasks/{root}')).json()",
            f"status-{phase}.json",
        )
        transitions.append(
            {"at": now(), "status": current["status"], "counts": current.get("counts")}
        )
        if current["status"] in TERMINAL:
            return current, transitions
        if current["status"] in WAITING:
            waiting_since = waiting_since or time.time()
            if time.time() - waiting_since > 120:
                return current, transitions
        else:
            waiting_since = None
        time.sleep(8)
    return (
        evaluate(
            mcp,
            f"async () => await (await fetch('/api/tasks/{root}')).json()",
            f"status-{phase}.json",
        ),
        transitions,
    )


def phase_preflight(mcp: PlaywrightMCP) -> int:
    result: dict[str, Any] = {"phase": "preflight", "at": now(), "transport": "playwright-mcp"}
    result["user"] = login(mcp).get("username")
    result["tasks"] = {}
    expectations = {
        "continue": ("继续采集（还差 1 位）", "不会重新采集已入库达人"),
        "backfill": ("补采缺失字段（1 位）", "不会新增达人"),
        "completed": (None, None),
        "challenge": (None, "安全验证"),
        "update": ("重试失败步骤", None),
    }
    for name, (expected_label, message_part) in expectations.items():
        root = TASKS[name]
        snapshot = open_task(mcp, root)
        detail = evaluate(
            mcp,
            f"async () => await (await fetch('/api/tasks/{root}')).json()",
            f"detail-{name}.json",
        )
        label = retry_label(snapshot)
        attention = next(
            (
                line.split("]: ", 1)[1]
                for line in snapshot.splitlines()
                if line.lstrip().startswith("- paragraph")
                and any(key in line for key in ("已采到", "安全验证", "没有更多", "无需"))
            ),
            "",
        )
        ok = label == expected_label if expected_label is not None else label is None
        if message_part:
            ok = ok and message_part in snapshot
        result["tasks"][name] = {
            "root_task_id": root,
            "status": detail["status"],
            "counts": detail["counts"],
            "allowed_actions": detail["allowed_actions"],
            "retry_plan": detail.get("retry_plan"),
            "button": label,
            "attention": attention,
            "assert_ok": ok,
            "screenshot": shot(mcp, f"preflight-{name}"),
            "db": db_snapshot(root),
        }
    result["console_errors"] = mcp.call_text(
        "browser_console_messages", {"level": "error", "all": True}
    )
    save("preflight", result)
    print(json.dumps({k: v["assert_ok"] for k, v in result["tasks"].items()}, ensure_ascii=False))
    return 0 if all(v["assert_ok"] for v in result["tasks"].values()) else 2


def phase_api(mcp: PlaywrightMCP) -> int:
    login(mcp)
    result: dict[str, Any] = {"phase": "api", "at": now(), "checks": {}}
    for name in ("completed", "challenge"):
        root = TASKS[name]
        function = (
            "async () => {"
            f" const task = await (await fetch('/api/tasks/{root}')).json();"
            " const me = await (await fetch('/api/auth/me')).json();"
            f" const response = await fetch('/api/tasks/{root}/retry', {{"
            "   method: 'POST',"
            "   headers: {"
            "     'Content-Type': 'application/json',"
            "     'X-CSRF-Token': me.csrf_token,"
            "     'Idempotency-Key': crypto.randomUUID(),"
            "   },"
            "   body: JSON.stringify({expected_version: task.version}),"
            " });"
            " return {http_status: response.status, body: await response.json(),"
            "   task_status: task.status, allowed_actions: task.allowed_actions};"
            " }"
        )
        result["checks"][name] = evaluate(mcp, function, f"api-{name}.json")
    save("api", result)
    print(json.dumps(result["checks"], ensure_ascii=False))
    return 0 if all(item["http_status"] >= 400 for item in result["checks"].values()) else 2


def run_real_retry(mcp: PlaywrightMCP, phase: str, root: str, timeout: float) -> int:
    login(mcp)
    before = db_snapshot(root)
    snapshot = open_task(mcp, root)
    # Screenshot before the click: once the confirm dialog is open, MCP screenshot is not allowed.
    before_shot = shot(mcp, f"{phase}-before")
    label, dialog = click_retry(mcp, snapshot)
    result: dict[str, Any] = {
        "phase": phase,
        "at": now(),
        "transport": "playwright-mcp",
        "root_task_id": root,
        "button": label,
        "button_ok": label.startswith("继续采集" if phase == "continue" else "补采缺失字段"),
        "dialog": dialog,
        "before": before,
        "screenshot_before": before_shot,
    }
    # Dismiss first: the UI must not send a request when the user cancels.
    handle_dialog(mcp, accept=False)
    time.sleep(0.5)
    result["cancel_requests"] = retry_requests(mcp)
    result["cancel_sent_no_request"] = not result["cancel_requests"]

    # Accept: this is the real retry.
    label2, dialog2 = click_retry(mcp, mcp.call_text("browser_snapshot"))
    handle_dialog(mcp, accept=True)
    time.sleep(1)
    result["accept_requests"] = retry_requests(mcp)
    result["accept_sent_request"] = len(result["accept_requests"]) == 1
    final, transitions = poll_task(mcp, root, phase, timeout)
    open_task(mcp, root)
    result.update(
        {
            "transitions": transitions,
            "status_after": final["status"],
            "counts_after": final["counts"],
            "retry_plan_after": final.get("retry_plan"),
            "failure_reason_after": final.get("failure_reason"),
            "button_after": retry_label(mcp.call_text("browser_snapshot")),
            "screenshot_after": shot(mcp, f"{phase}-after"),
            "after": db_snapshot(root),
            "finished_at": now(),
            "console_errors": mcp.call_text(
                "browser_console_messages", {"level": "error", "all": True}
            ),
        }
    )
    save(phase, result)
    print(
        json.dumps(
            {
                "phase": phase,
                "button": label,
                "dialog": dialog,
                "status_after": final["status"],
                "valid_before": before["valid_count"],
                "valid_after": final["counts"]["valid_count"],
                "cancel_no_request": result["cancel_sent_no_request"],
                "accept_one_request": result["accept_sent_request"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if result["button_ok"] and result["cancel_sent_no_request"] else 2


def phase_create(mcp: PlaywrightMCP) -> int:
    """Normal first collection through the product form (AC-10) via MCP."""
    login(mcp)
    mcp.call_text("browser_navigate", {"url": f"{BASE}/tasks/new"})
    wait_for(
        mcp,
        lambda: "目标达人数量" in mcp.call_text("browser_snapshot"),
        timeout=30,
    )
    mcp.call(
        "browser_type",
        {
            "target": 'input[placeholder="例如：宠物、母婴辅食、户外露营"]',
            "text": "宠物",
        },
    )
    mcp.call(
        "browser_type",
        {"target": 'input[type="number"][step="1"]', "text": "1"},
    )
    mcp.call(
        "browser_click",
        {"target": 'button:has-text("提交采集任务")', "element": "提交采集任务"},
    )
    root = None
    for _ in range(60):
        time.sleep(1)
        path = mcp.call_text("browser_evaluate", {"function": "() => location.pathname"})
        match = re.search(r"/tasks/([0-9a-f-]{36})", path)
        if match:
            root = match.group(1)
            break
    if not root:
        raise MCPError("task creation did not navigate to a task detail page")
    final, transitions = poll_task(mcp, root, "create", 900)
    open_task(mcp, root)
    detail = evaluate(
        mcp,
        f"async () => await (await fetch('/api/tasks/{root}')).json()",
        "create-detail.json",
    )
    result = {
        "phase": "create",
        "at": now(),
        "transport": "playwright-mcp",
        "root_task_id": root,
        "transitions": transitions,
        "status": final["status"],
        "counts": final["counts"],
        "failure_reason": final.get("failure_reason"),
        "retry_plan": final.get("retry_plan"),
        "button": retry_label(mcp.call_text("browser_snapshot")),
        "screenshot": shot(mcp, "create-after"),
        "db": db_snapshot(root),
        "detail": detail,
        "console_errors": mcp.call_text(
            "browser_console_messages", {"level": "error", "all": True}
        ),
    }
    save("create", result)
    print(
        json.dumps(
            {
                "root": root,
                "status": result["status"],
                "counts": result["counts"],
                "button": result["button"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if final["status"] in TERMINAL else 2


def phase_status(mcp: PlaywrightMCP) -> int:
    """Capture the final state of the backfill task after the unit recovery."""
    login(mcp)
    root = TASKS["backfill"]
    snapshot = open_task(mcp, root)
    detail = evaluate(
        mcp,
        f"async () => await (await fetch('/api/tasks/{root}')).json()",
        "status-backfill-final.json",
    )
    units = evaluate(
        mcp,
        "async () => await (await fetch('/api/execution-units')).json()",
        "units-final.json",
    )
    result = {
        "phase": "backfill-final",
        "at": now(),
        "transport": "playwright-mcp",
        "root_task_id": root,
        "status": detail["status"],
        "counts": detail["counts"],
        "retry_plan": detail.get("retry_plan"),
        "failure_reason": detail.get("failure_reason"),
        "button": retry_label(snapshot),
        "attention": next(
            (
                line.split("]: ", 1)[1]
                for line in snapshot.splitlines()
                if line.lstrip().startswith("- paragraph") and "已采到" in line
            ),
            "",
        ),
        "units": units,
        "screenshot": shot(mcp, "backfill-final"),
        "db": db_snapshot(root),
        "console_errors": mcp.call_text(
            "browser_console_messages", {"level": "error", "all": True}
        ),
    }
    save("backfill-final", result)
    print(
        json.dumps(
            {
                "status": result["status"],
                "button": result["button"],
                "valid": result["counts"]["valid_count"],
                "snapshots": result["db"]["snapshots"]["count"],
                "unit": result["units"][0]["state"] if result["units"] else None,
            },
            ensure_ascii=False,
        )
    )
    return 0


PHASES = {
    "preflight": phase_preflight,
    "api": phase_api,
    "continue": lambda mcp: run_real_retry(mcp, "continue", TASKS["continue"], 600),
    "backfill": lambda mcp: run_real_retry(mcp, "backfill", TASKS["backfill"], 600),
    "status": phase_status,
    "create": phase_create,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=sorted(PHASES))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    server_log = ROOT / ".runtime/logs/retry01-mcp-server.log"
    server_log.parent.mkdir(parents=True, exist_ok=True)
    mcp = PlaywrightMCP(SERVER_OUT, headless=True, log_path=server_log)
    try:
        info = mcp.initialize()
        print(
            json.dumps(
                {
                    "server": info.get("serverInfo"),
                    "tools": len(mcp.tools()),
                },
                ensure_ascii=False,
            )
        )
        return PHASES[args.phase](mcp)
    finally:
        mcp.close()


if __name__ == "__main__":
    sys.exit(main())
