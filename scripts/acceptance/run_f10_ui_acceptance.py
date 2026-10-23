"""Drive the isolated F10 environment with Playwright MCP + Chrome and save evidence."""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import sys
import time
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.acceptance import run_f10_acceptance as harness  # noqa: E402
from scripts.acceptance.mcp_client import PlaywrightMcp  # noqa: E402
from scripts.acceptance.run_acceptance import evaluate  # noqa: E402

EVIDENCE_DIR = ROOT / "docs" / "evidence" / "assets" / "f10"
MCP_OUTPUT = pathlib.Path("/tmp/dsh-playwright-mcp")
RESULT_FILE = EVIDENCE_DIR / "acceptance-results.json"
results: list[dict[str, Any]] = []


def check(name: str, passed: bool, detail: str) -> None:
    results.append({"check": name, "passed": bool(passed), "detail": detail})
    print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}", flush=True)


def wait_for(client: PlaywrightMcp, text: str, timeout: float = 12) -> str:
    deadline = time.monotonic() + timeout
    body = ""
    while time.monotonic() < deadline:
        body = str(evaluate(client, "document.body.innerText"))
        if text in body:
            return body
        time.sleep(0.5)
    return body


def click_text(client: PlaywrightMcp, text: str) -> bool:
    return bool(
        evaluate(
            client,
            """(() => {
              const wanted = %s;
              const target = Array.from(document.querySelectorAll('button,a'))
                .find((item) => item.textContent.trim().includes(wanted) && !item.disabled);
              if (!target) return false;
              target.click();
              return true;
            })()""".replace("%s", json.dumps(text, ensure_ascii=False)),
        )
    )


def screenshot(client: PlaywrightMcp, name: str) -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    MCP_OUTPUT.mkdir(parents=True, exist_ok=True)
    source = MCP_OUTPUT / f"f10-{name}.png"
    client.call(
        "browser_take_screenshot",
        {"filename": str(source), "fullPage": True, "type": "png"},
        timeout=120,
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not source.exists():
        time.sleep(0.2)
    if not source.exists():
        raise RuntimeError(f"screenshot not produced: {name}")
    shutil.copyfile(source, EVIDENCE_DIR / f"{name}.png")


def login(client: PlaywrightMcp, base: str) -> None:
    qa = harness.read_env(ROOT / ".runtime" / "qa-credentials.env")
    password = qa["QA_MEDIA_A_PASSWORD"]
    client.call("browser_navigate", {"url": f"{base}/login"}, timeout=120)
    time.sleep(0.8)
    current = evaluate(client, "location.pathname")
    if str(current).startswith("/tasks"):
        check("AUTH-01", True, f"existing isolated session redirected to {current!r}")
        return
    client.call(
        "browser_fill_form",
        {
            "fields": [
                {
                    "name": "产品账号",
                    "type": "textbox",
                    "target": 'input[autocomplete="username"]',
                    "value": "f10-operator",
                },
                {
                    "name": "密码",
                    "type": "textbox",
                    "target": ".password-field input",
                    "value": password,
                },
            ]
        },
        timeout=60,
    )
    client.call(
        "browser_click",
        {"element": "安全登录", "target": ".login-button"},
        timeout=60,
    )
    wait_for(client, "任务中心", timeout=15)
    state = evaluate(
        client,
        "(() => ({path: location.pathname, heading: document.querySelector('h1')?.textContent}))()",
    )
    passed = state.get("path") == "/tasks"
    check("AUTH-01", passed, f"login result={state!r}")
    if not passed:
        raise RuntimeError("isolated product login failed")


def main() -> int:
    state = harness.load_state()
    base = state["frontend_url"]
    root = state["root_task_id"]
    harness.repository(state).heartbeat(state["unit"], state["attempt_id"], state["generation"])
    with PlaywrightMcp() as client:
        server = client.initialize().get("serverInfo", {})
        tools = {item["name"] for item in client.list_tools()}
        check(
            "MCP-01",
            "browser_navigate" in tools and "browser_take_screenshot" in tools,
            f"server={server}, tools={len(tools)}, browser=chrome",
        )
        login(client, base)

        client.call("browser_navigate", {"url": f"{base}/tasks/{root}"}, timeout=120)
        body = wait_for(client, "户外")
        check("TASK-01", "户外" in body, "task detail renders exact keyword 户外")
        check("TASK-02", "21" in body, "task detail renders target count 21")
        check(
            "TASK-03",
            "等待安全验证" in body or "平台要求安全验证" in body,
            "task detail renders WAITING_FOR_VERIFICATION",
        )
        screenshot(client, "01-task-waiting-verification")

        client.call("browser_navigate", {"url": f"{base}/execution-units"}, timeout=120)
        body = wait_for(client, state["unit"])
        check("UNIT-01", "1 个执行单元需要人工验证" in body, "open event count is 1")
        check("UNIT-02", "等待人工验证" in body, "unit waiting label is visible")
        check("UNIT-03", "•••" in body, "account and line references are masked")
        check("UNIT-04", "PLATFORM_SECURITY_CHALLENGE" in body, "actionable reason is visible")
        screenshot(client, "02-unit-waiting")

        check("TAKEOVER-01", click_text(client, "接管浏览器"), "takeover request button clicked")
        body = wait_for(client, "正在确认原浏览器实例仍在线")
        check("TAKEOVER-02", "正在确认原浏览器实例仍在线" in body, "REQUESTED state rendered")
        harness.activate()
        body = wait_for(client, "人工验证中")
        check("TAKEOVER-03", "人工验证中" in body, "ACTIVE state rendered")
        check(
            "TAKEOVER-04",
            all(item in body for item in ("outdoor-01", "outdoor-02", "outdoor-03")),
            "three manual probe creators rendered without automatic navigation",
        )
        check(
            "TAKEOVER-05",
            "系统已暂停自动页面检测与采集操作" in body,
            "mutual-exclusion notice rendered",
        )
        local_takeover = evaluate(
            client,
            """(() => ({
              guidance: document.body.innerText.includes('请切换到本机原 Chrome 窗口'),
              viewerCount: document.querySelectorAll('.takeover-viewer iframe').length,
            }))()""",
        )
        check(
            "TAKEOVER-06",
            bool(local_takeover.get("guidance")) and local_takeover.get("viewerCount") == 0,
            f"local original-Chrome guidance={local_takeover!r}",
        )
        screenshot(client, "03-takeover-active")

        check("REAPPEAR-01", click_text(client, "仍有验证/无法完成"), "feedback opened")
        body = wait_for(client, "滑块或交互验证再次出现")
        check("REAPPEAR-02", "滑块或交互验证再次出现" in body, "reason selector rendered")
        check("REAPPEAR-03", click_text(client, "提交状态"), "reappearance submitted")
        time.sleep(1)
        inspected = json.loads(capture_inspect())
        check(
            "REAPPEAR-04",
            inspected["verification"]["reappearance_count"] == 1,
            f"backend count={inspected['verification']['reappearance_count']}",
        )

        check("VERIFY-01", click_text(client, "我已完成验证"), "completion submitted")
        body = wait_for(client, "正在检查验证、账号与受保护业务页面")
        check("VERIFY-02", "正在检查验证、账号与受保护业务页面" in body, "VERIFYING rendered")
        screenshot(client, "04-system-verifying")
        harness.fail_verification()
        body = wait_for(client, "本次接管已结束")
        check(
            "VERIFY-03", "SECURITY_CHALLENGE_STILL_PRESENT" in body, "failed check reason rendered"
        )
        inspected = json.loads(capture_inspect())
        check(
            "VERIFY-04",
            inspected["verification"]["reappearance_count"] == 2,
            "failed stable check increments reappearance count without resuming",
        )
        screenshot(client, "05-challenge-still-present")

        closed = bool(
            evaluate(
                client,
                """(() => {
                  const button = document.querySelector('button[aria-label="关闭接管工作区"]');
                  if (!button) return false;
                  button.click();
                  return true;
                })()""",
            )
        )
        check("RETRY-01", closed, "failed workspace closed")
        body = wait_for(client, "接管浏览器")
        check(
            "RETRY-02", click_text(client, "接管浏览器"), "second takeover requested in same window"
        )
        wait_for(client, "正在确认原浏览器实例仍在线")
        harness.activate()
        body = wait_for(client, "人工验证中")
        check("RETRY-03", "人工验证中" in body, "second takeover became ACTIVE")
        check("RESUME-01", click_text(client, "我已完成验证"), "second completion submitted")
        wait_for(client, "正在检查验证、账号与受保护业务页面")
        harness.resume()
        body = wait_for(client, "验证通过，任务已恢复")
        check("RESUME-02", "验证通过，任务已恢复" in body, "RESUMED state rendered")
        screenshot(client, "06-resumed")

        inspected = json.loads(capture_inspect())
        check("RESUME-03", inspected["task_state"] == "COLLECTING", "task resumed to COLLECTING")
        check("RESUME-04", inspected["unit"]["mode"] == "collect", "unit returned to collect mode")
        check(
            "RESUME-05", inspected["unit"]["session_version"] == 1, "session version advanced once"
        )
        check("RESUME-06", inspected["verification"]["state"] == "RESOLVED", "event resolved")

        console = client.text_of(client.call("browser_console_messages", {}, timeout=60))
        network = client.text_of(client.call("browser_network_requests", {}, timeout=60))
        console_errors = re.search(r"Errors:\s*(\d+)", console)
        check(
            "OBS-01",
            bool(console_errors and int(console_errors.group(1)) == 0),
            f"browser console summary={console_errors.group(0) if console_errors else 'missing'}",
        )
        check(
            "OBS-02",
            "=> [4" not in network and "=> [5" not in network,
            "no failed HTTP requests recorded",
        )

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": state["run_id"],
        "root_task_id": root,
        "keyword": "户外",
        "target_count": 21,
        "checks": results,
        "passed": sum(1 for item in results if item["passed"]),
        "failed": sum(1 for item in results if not item["passed"]),
    }
    RESULT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": payload["passed"], "failed": payload["failed"]}))
    return 0 if payload["failed"] == 0 else 1


def capture_inspect() -> str:
    state = harness.load_state()
    repo = harness.repository(state)
    task = repo.get(state["root_task_id"])
    unit = repo.unit(state["unit"])
    with repo.connect() as conn:
        event = conn.execute(
            "SELECT state,reason,reappearance_count FROM verification_events WHERE event_id=%s",
            (state["event_id"],),
        ).fetchone()
    takeover = harness.latest_takeover(repo)
    return json.dumps(
        {
            "task_state": task.state,
            "unit": {
                "mode": unit["mode"],
                "session_version": unit["session_version"],
            },
            "verification": dict(event) if event else None,
            "takeover": dict(takeover) if takeover else None,
        },
        default=str,
    )


if __name__ == "__main__":
    raise SystemExit(main())
