#!/usr/bin/env python3
"""Real-browser (Playwright MCP + Chrome) driver for the DUAL-70-01 acceptance.

It logs into the product UI, submits exactly one real collection task through the same form a
media user uses, waits for the terminal state, and records the UI/API evidence.  It deliberately
does not call the product API to create the task: the acceptance requires the real business entry.

The script is idempotent per invocation through explicit ``--resume-task-id``: a long 70-creator
task can be polled again without creating a second task.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "qa"))

from kjx_full_mcp import MCPPage  # noqa: E402
from mcp_client import PlaywrightMCP  # noqa: E402

DEFAULT_BASE = "http://127.0.0.1:5173"
CREDS = ROOT / ".runtime/qa-credentials.env"
TERMINAL = {
    "COMPLETED",
    "PARTIAL_COMPLETED",
    "FAILED",
    "FAILED_VALIDATION",
    "CANCELLED",
    "EXPIRED",
}


def load_password(path: Path) -> str:
    for line in path.read_text().splitlines():
        if line.startswith("QA_MEDIA_A_PASSWORD="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("QA_MEDIA_A_PASSWORD missing")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DUAL-70-01 UI task driver")
    parser.add_argument("--platform", choices=["douyin_xingtu", "kuaishou_juxing"], required=True)
    parser.add_argument("--target", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--keyword", default=None)
    parser.add_argument("--content-type", default="maternal_child")
    parser.add_argument("--poll-timeout-seconds", type=int, default=6 * 3600)
    parser.add_argument("--poll-interval-seconds", type=float, default=30.0)
    parser.add_argument("--resume-task-id", default=None)
    parser.add_argument(
        "--resume-failed",
        action="store_true",
        help="with --resume-task-id: click the real UI retry/continue action on a FAILED task",
    )
    parser.add_argument("--headless", action="store_true", default=False)
    parser.add_argument("--skip-create", action="store_true")
    parser.add_argument(
        "--continue-on-pause",
        action="store_true",
        help="on PAUSED_BUDGET only: click the existing UI continue action after logging state",
    )
    return parser.parse_args()


class Driver:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.out = args.out
        self.out.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state_path = self.out / "state.json"
        self.state: dict[str, Any] = (
            json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        )
        self.state.setdefault("polls", [])
        self.mcp = PlaywrightMCP(
            self.out / "mcp-output",
            headless=args.headless,
            log_path=self.out / "mcp-server.log",
        )
        self.mcp.initialize()
        self.page = MCPPage(self.mcp, self.out)

    def save(self) -> None:
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2))
        self.state_path.chmod(0o600)

    def ev(self, js: str, name: str) -> Any:
        return self.page.ev(js, name)

    def api(self, path: str, name: str) -> dict[str, Any] | None:
        js = (
            "(async () => { const r = await fetch("
            + json.dumps(path)
            + ", {headers: {Accept: 'application/json'}});"
            " let body = null; try { body = await r.json(); } catch (e) { body = null; }"
            " return {status: r.status, body: body}; })()"
        )
        data = self.ev(js, name)
        if data.get("status") != 200:
            return None
        return data.get("body")

    def login(self) -> None:
        self.mcp.call_text("browser_navigate", {"url": f"{self.args.base}/login"}, timeout=120)
        if not self.page.wait_text("产品账号", tries=40):
            raise RuntimeError("login page did not render")
        self.mcp.call(
            "browser_type",
            {"target": "input[autocomplete=username]", "text": "media-a"},
            timeout=60,
        )
        self.mcp.call(
            "browser_type",
            {"target": ".password-field input", "text": load_password(CREDS)},
            timeout=60,
        )
        self.mcp.call("browser_click", {"target": "button.login-button"}, timeout=60)
        if not self.page.wait_text("任务中心", tries=60):
            raise RuntimeError("login did not reach the task center")
        self.state["logged_in_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self.save()

    def set_input(self, selector: str, value: str, name: str) -> Any:
        js = (
            "() => { const input = document.querySelector("
            + json.dumps(selector)
            + "); if (!input) return null;"
            " const setter = Object.getOwnPropertyDescriptor("
            "window.HTMLInputElement.prototype,'value').set;"
            " setter.call(input, " + json.dumps(value) + ");"
            " input.dispatchEvent(new Event('input', {bubbles:true}));"
            " input.dispatchEvent(new Event('change', {bubbles:true}));"
            " return {value: input.value, min: input.min, max: input.max}; }"
        )
        return self.ev(js, name)

    def wait_task_id(self, timeout: float = 120) -> str:
        started = time.time()
        while time.time() - started < timeout:
            path = self.ev("() => location.pathname", "submit-path")
            match = re.match(r"^/tasks/([0-9a-f-]{36})$", str(path))
            if match:
                return match.group(1)
            time.sleep(0.5)
        body = self.ev("() => document.body.innerText.slice(0, 3000)", "submit-body")
        raise RuntimeError(f"task id not observed; path/body={body[:1000]}")

    def create(self) -> str:
        self.mcp.call_text("browser_navigate", {"url": f"{self.args.base}/tasks/new"}, timeout=120)
        if not self.page.wait_text("采集平台", tries=40):
            raise RuntimeError("new task page did not render")
        label = "巨量星图" if self.args.platform == "douyin_xingtu" else "磁力聚星"
        if not self.page.click_text(label):
            raise RuntimeError(f"platform radio missing: {label}")
        if self.args.platform == "douyin_xingtu":
            if not self.page.wait_text("内容关键词", tries=40):
                raise RuntimeError("xingtu form did not render")
            keyword = self.args.keyword or "宠物"
            self.mcp.call(
                "browser_type",
                {
                    "target": "input[placeholder='例如：宠物、母婴辅食、户外露营']",
                    "text": keyword,
                },
                timeout=60,
            )
        else:
            if not self.page.wait_text("内容类型", tries=40):
                raise RuntimeError("juxing form did not render")
            keyword = self.args.keyword or "母婴"
            self.mcp.call(
                "browser_type",
                {"target": "input[placeholder='例如：母婴']", "text": keyword},
                timeout=60,
            )
            self.mcp.call(
                "browser_select_option",
                {"target": "select[aria-label='内容类型']", "values": [self.args.content_type]},
                timeout=60,
            )
        target = self.set_input(".number-field input", str(self.args.target), "target-input")
        form = self.page.extract("form-before-submit")
        self.state["form"] = {
            "platform": self.args.platform,
            "keyword": keyword,
            "target": target,
            "text": form.get("text", "")[:4000],
            "inputs": form.get("inputs"),
        }
        self.save()
        if not target or str(target.get("value")) != str(self.args.target):
            raise RuntimeError(f"target input was not set: {target}")
        if target.get("max") not in (None, "", "200"):
            raise RuntimeError(f"unexpected target max attribute: {target.get('max')}")
        self.page.shot("01-form")
        self.mcp.call("browser_click", {"target": "button.submit-button"}, timeout=60)
        task_id = self.wait_task_id()
        self.state["task_id"] = task_id
        self.state["submitted_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self.state["target"] = self.args.target
        self.save()
        return task_id

    def task(self, task_id: str, name: str) -> dict[str, Any] | None:
        return self.api(f"/api/tasks/{task_id}", name)

    def poll(self, task_id: str) -> dict[str, Any]:
        started = time.time()
        last: dict[str, Any] | None = None
        while time.time() - started < self.args.poll_timeout_seconds:
            data = self.task(task_id, f"poll-{int(time.time())}")
            if data is None:
                entry = {
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "error": "task detail unavailable (session or API)",
                }
                self.state["polls"].append(entry)
                self.save()
                # A long task can outlive the UI cookie; re-login once and continue.
                try:
                    self.login()
                except Exception as exc:  # noqa: BLE001
                    self.state["polls"].append({"at": entry["at"], "login_error": str(exc)})
                    self.save()
                time.sleep(self.args.poll_interval_seconds)
                continue
            status = data.get("status")
            counts = data.get("counts") or {}
            entry = {
                "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "elapsed_seconds": round(time.time() - started, 1),
                "status": status,
                "stage": data.get("stage"),
                "target": counts.get("target_count"),
                "valid": counts.get("valid_count"),
                "discovered": counts.get("discovered_count"),
                "profile_complete": counts.get("profile_complete_count"),
                "failure_reason": data.get("failure_reason"),
                "challenge": (data.get("challenge") or {}).get("state"),
            }
            self.state["polls"].append(entry)
            self.state["last_task"] = data
            self.save()
            last = data
            if status in TERMINAL:
                return data
            if status == "PAUSED_BUDGET" and self.args.continue_on_pause:
                self.state.setdefault("pauses", []).append(entry)
                self.save()
                # The budget pause action lives on the task detail page, not the task center.
                self.mcp.call_text(
                    "browser_navigate",
                    {"url": f"{self.args.base}/tasks/{task_id}"},
                    timeout=120,
                )
                self.page.wait_text("有效入库", tries=40)
                clicked = self.page.click_text("继续任务") or self.page.click_text("继续采集")
                if clicked:
                    time.sleep(2)
                    # The product may use an in-page confirmation for the retry path.
                    for label in ("确认继续", "确认", "继续"):
                        if self.page.click_text(label, occurrence=0):
                            break
                    self.state["pauses"][-1]["continue_clicked"] = True
                    self.save()
                else:
                    self.state["pauses"][-1]["continue_clicked"] = False
                    self.save()
            time.sleep(self.args.poll_interval_seconds)
        if last is None:
            raise RuntimeError("task polling produced no detail")
        self.state["poll_timeout"] = True
        self.save()
        return last

    def record_ui(self, task_id: str) -> None:
        self.mcp.call_text(
            "browser_navigate", {"url": f"{self.args.base}/tasks/{task_id}"}, timeout=120
        )
        self.page.wait_text("有效入库", tries=40)
        detail = self.page.extract("task-detail")
        api_detail = self.task(task_id, "task-detail-api") or {}
        creators = self.api(f"/api/tasks/{task_id}/creators?limit=100", "task-creators") or {}
        # Load more until the API-reported valid count is visible, bounded for 70.
        for index in range(4):
            if self.page.click_text("查看更多达人"):
                time.sleep(1.5)
                self.page.extract(f"task-detail-after-more-{index}")
            else:
                break
        self.state["ui"] = {
            "path": detail.get("path"),
            "text": detail.get("text", "")[:6000],
            "buttons": detail.get("buttons"),
            "inputs": detail.get("inputs"),
            "api": api_detail,
            "creators_api": {
                "items": len(creators.get("items") or []),
                "next_cursor": creators.get("next_cursor"),
            },
        }
        self.page.shot("02-task-detail")
        self.save()

    def resume_failed(self, task_id: str) -> None:
        """Click the real UI retry/continue action on a FAILED collection task.

        The UI renders ``继续采集（还差 N 位）`` when the derived retry scope is continue; the click
        opens the browser's native confirmation dialog.  No API shortcut is used here: this is the
        same business entry a media user clicks.
        """

        self.mcp.call_text(
            "browser_navigate", {"url": f"{self.args.base}/tasks/{task_id}"}, timeout=120
        )
        if not self.page.wait_text("有效入库", tries=40):
            raise RuntimeError("task detail did not render")
        snapshot = self.mcp.call_text("browser_snapshot")
        label = next(
            (
                line.split('"')[1]
                for line in snapshot.splitlines()
                if "- button" in line and "继续采集" in line and '"' in line
            ),
            None,
        )
        if not label:
            raise RuntimeError("continue/retry button not found on failed task")
        self.page.click_text("继续采集")
        dialog: str | None = None
        try:
            dialog = self.mcp.call_text("browser_handle_dialog", {"accept": True})
        except Exception:  # noqa: BLE001 - a custom confirmation may not be a native dialog
            pass
        deadline = time.time() + 30
        status = "FAILED"
        while time.time() < deadline:
            data = self.task(task_id, f"resume-{int(time.time())}") or {}
            status = str(data.get("status") or "FAILED")
            if status != "FAILED":
                break
            time.sleep(2)
        self.state["resume"] = {
            "label": label,
            "dialog": dialog,
            "status_after_click": status,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        self.save()
        if status == "FAILED":
            raise RuntimeError("retry action did not leave FAILED; inspect the UI dialog")

    def run(self) -> int:
        self.login()
        task_id = self.args.resume_task_id
        if task_id and self.args.resume_failed:
            self.resume_failed(task_id)
        if not task_id and not self.args.skip_create:
            task_id = self.create()
        if not task_id:
            raise SystemExit("--resume-task-id or task creation required")
        final = self.poll(task_id)
        self.record_ui(task_id)
        self.state["final"] = final
        self.state["final_status"] = final.get("status")
        self.save()
        print(
            json.dumps(
                {
                    "task_id": task_id,
                    "platform": self.args.platform,
                    "target": self.args.target,
                    "status": final.get("status"),
                    "counts": final.get("counts"),
                    "failure_reason": final.get("failure_reason"),
                    "out": str(self.out),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if final.get("status") in {"COMPLETED", "PARTIAL_COMPLETED"} else 1

    def close(self) -> None:
        try:
            self.mcp.close()
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    args = parse_args()
    driver = Driver(args)
    try:
        return driver.run()
    finally:
        driver.close()


if __name__ == "__main__":
    raise SystemExit(main())
