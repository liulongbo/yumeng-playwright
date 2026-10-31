#!/usr/bin/env python3
"""JUXING-MAIN-01 main-station real-user acceptance over Playwright MCP + Chrome.

Every browser action goes through the locally installed @playwright/mcp server's ``browser_*``
tools (MCP stdio), not Playwright Python page automation.  The driver logs into 5173 through the
real login form, submits exactly one juxing task (母婴 / 母婴亲子 / target=1) and one xingtu task
(宠物 / target=1), polls both through the product API with the same UI session, and records the
task center, library, detail and execution-unit evidence.

It is idempotent: task ids are stored in ``.runtime/juxing-main/mcp/state.json`` and a re-run never
submits the same real task twice.  This script is acceptance tooling; it is not required by the
product at runtime.
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
sys.path.insert(0, str(ROOT / "scripts/qa"))

from kjx_full_mcp import Book, MCPPage  # noqa: E402
from mcp_client import PlaywrightMCP  # noqa: E402

DEFAULT_BASE = "http://127.0.0.1:5173"
DEFAULT_OUT = ROOT / ".runtime/juxing-main/mcp"
CREDS = ROOT / ".runtime/qa-credentials.env"
TERMINAL = {"COMPLETED", "PARTIAL_COMPLETED", "FAILED", "FAILED_VALIDATION", "CANCELLED", "EXPIRED"}
EXECUTING = {"SEARCHING", "COLLECTING", "PERSISTING", "RETRY_WAIT", "CANCELLING"}


def load_password(path: Path) -> str:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values["QA_MEDIA_A_PASSWORD"]


class Driver:
    def __init__(
        self, base: str, out: Path, *, headless: bool = True, expect_juxing_tasks: int = 0
    ) -> None:
        self.base = base.rstrip("/")
        self.expect_juxing_tasks = expect_juxing_tasks
        self.out = out
        self.out.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state_path = self.out / "state.json"
        self.state: dict[str, Any] = (
            json.loads(self.state_path.read_text())
            if self.state_path.exists()
            else {"tasks": {}, "polls": []}
        )
        self.book = Book()
        self.mcp = PlaywrightMCP(
            self.out / "mcp-output",
            headless=headless,
            log_path=self.out / "mcp-server.log",
        )
        self.mcp.initialize()
        self.page = MCPPage(self.mcp, self.out)

    # -- infrastructure -------------------------------------------------------------------
    def save(self) -> None:
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2))

    def check(
        self, case: str, ok: bool, actual: str, evidence: str, *, kind: str = "UI 交互"
    ) -> bool:
        return self.book.check(case, ok, actual, evidence, kind=kind)

    def add(
        self, case: str, status: str, actual: str, evidence: str, *, kind: str = "UI 交互"
    ) -> None:
        self.book.add(case, status, actual, evidence, kind=kind)

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
            self.add(
                f"JXM-API-{name}",
                "FAIL",
                f"{path} -> HTTP {data.get('status')}",
                name,
                kind="API 回读",
            )
            return None
        return data.get("body")

    def shot(self, name: str) -> str:
        return self.page.shot(name)

    def login(self) -> None:
        self.mcp.call_text("browser_navigate", {"url": f"{self.base}/login"}, timeout=120)
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
        path = self.ev("() => location.pathname", "login-path")
        self.check(
            "JXM-UI-01",
            True,
            f"media-a 真实登录进入任务中心，path={path}",
            "login-after",
        )
        self.shot("01-login-task-center")

    # -- setup ----------------------------------------------------------------------------
    def setup_checks(self) -> None:
        self.mcp.call_text("browser_navigate", {"url": f"{self.base}/tasks"}, timeout=120)
        if not self.page.wait_text("任务中心", tries=40):
            raise RuntimeError("task center did not render")
        options = self.ev(
            "() => { const s=document.querySelector(\"select[aria-label='按平台筛选']\");"
            " return s ? [...s.options].map(o => ({value:o.value,label:o.textContent})) : null; }",
            "task-platform-options",
        )
        self.check(
            "JXM-TC-02A",
            bool(options)
            and [o["value"] for o in options] == ["", "douyin_xingtu", "kuaishou_juxing"],
            f"平台筛选选项={options}",
            "task-platform-options",
        )
        self.page.mcp.call(
            "browser_select_option",
            {"target": "select[aria-label='按平台筛选']", "values": ["kuaishou_juxing"]},
            timeout=60,
        )
        time.sleep(2)
        juxing_tasks = (
            self.api("/api/tasks?limit=20&platform=kuaishou_juxing", "setup-juxing-tasks") or {}
        )
        self.check(
            "JXM-TC-02B",
            len(juxing_tasks.get("items", [])) == self.expect_juxing_tasks,
            f"切换聚星筛选后主站聚星任务数={len(juxing_tasks.get('items', []))}"
            f"（预期 {self.expect_juxing_tasks}）",
            "02-juxing-filter-empty",
        )
        self.shot("02-juxing-filter-empty")
        self.page.mcp.call(
            "browser_select_option",
            {"target": "select[aria-label='按平台筛选']", "values": ["douyin_xingtu"]},
            timeout=60,
        )
        time.sleep(2)
        xingtu_tasks = (
            self.api("/api/tasks?limit=20&platform=douyin_xingtu", "setup-xingtu-tasks") or {}
        )
        self.check(
            "JXM-TC-02C",
            len(xingtu_tasks.get("items", [])) > 0,
            f"星图筛选返回 {len(xingtu_tasks.get('items', []))} 条（第一页）",
            "03-xingtu-filter",
        )
        self.shot("03-xingtu-filter")

        self.mcp.call_text("browser_navigate", {"url": f"{self.base}/tasks/new"}, timeout=120)
        if not self.page.wait_text("采集平台", tries=40):
            raise RuntimeError("new task page did not render")
        radios = self.ev(
            "() => [...document.querySelectorAll('[role=radio]')].map(b => ({text:b.innerText,"
            " checked:b.getAttribute('aria-checked'), disabled:b.disabled}))",
            "platform-radios",
        )
        self.check(
            "JXM-UI-03",
            len(radios) == 2 and all(not r["disabled"] for r in radios),
            f"平台选项={radios}",
            "04-platform-radios",
        )
        self.shot("04-platform-radios")

    # -- submissions ----------------------------------------------------------------------
    def _set_input(self, selector: str, value: str, name: str) -> None:
        js = (
            "() => { const input = document.querySelector("
            + json.dumps(selector)
            + "); if (!input) return null;"
            " const setter = Object.getOwnPropertyDescriptor("
            "window.HTMLInputElement.prototype,'value').set;"
            " setter.call(input, " + json.dumps(value) + ");"
            " input.dispatchEvent(new Event('input', {bubbles:true}));"
            " input.dispatchEvent(new Event('change', {bubbles:true}));"
            " return input.value; }"
        )
        self.ev(js, name)

    def _wait_task_id(self, prefix: str, timeout: float = 90) -> str:
        started = time.time()
        while time.time() - started < timeout:
            path = self.ev("() => location.pathname", f"{prefix}-path")
            match = re.match(r"^/tasks/([0-9a-f-]{36})$", str(path))
            if match:
                return match.group(1)
            time.sleep(0.5)
        body = self.ev("() => document.body.innerText.slice(0, 2000)", f"{prefix}-submit-body")
        raise RuntimeError(f"{prefix}: task id not observed; body={body[:500]}")

    def submit_juxing(self) -> str:
        self.mcp.call_text("browser_navigate", {"url": f"{self.base}/tasks/new"}, timeout=120)
        if not self.page.wait_text("磁力聚星", tries=40):
            raise RuntimeError("new task page did not render")
        if not self.page.click_text("磁力聚星"):
            raise RuntimeError("juxing platform radio missing")
        if not self.page.wait_text("内容类型", tries=40):
            raise RuntimeError("juxing form did not render")
        self.mcp.call(
            "browser_type",
            {"target": "input[placeholder='例如：母婴']", "text": "母婴"},
            timeout=60,
        )
        self.mcp.call(
            "browser_select_option",
            {"target": "select[aria-label='内容类型']", "values": ["maternal_child"]},
            timeout=60,
        )
        self._set_input(".number-field input", "1", "juxing-target")
        form = self.page.extract("05-juxing-form")
        text = form.get("text", "")
        self.check(
            "JXM-UI-05",
            "母婴亲子" in text and "30" in text and "内容类型" in text,
            "聚星表单渲染已验证字段与目标上限 30",
            "05-juxing-form",
        )
        self.check(
            "JXM-UI-04",
            not any(marker in text for marker in ("连接用户数", "学历", "黄v认证", "观众画像")),
            "聚星表单不出现星图专属筛选区块",
            "05-juxing-form",
        )
        self.shot("05-juxing-form")
        self.mcp.call("browser_click", {"target": "button.submit-button"}, timeout=60)
        task_id = self._wait_task_id("juxing")
        self.state["tasks"]["juxing"] = {"id": task_id, "submitted_at": time.time()}
        self.save()
        self.check(
            "JXM-JX-01",
            bool(task_id),
            f"真实 UI 提交聚星任务 id={task_id}，条件=母婴/母婴亲子/target=1",
            "05-juxing-form",
        )
        return task_id

    def submit_xingtu(self) -> str:
        self.mcp.call_text("browser_navigate", {"url": f"{self.base}/tasks/new"}, timeout=120)
        if not self.page.wait_text("巨量星图", tries=40):
            raise RuntimeError("new task page did not render")
        if not self.page.click_text("巨量星图"):
            raise RuntimeError("xingtu platform radio missing")
        if not self.page.wait_text("内容关键词", tries=40):
            raise RuntimeError("xingtu form did not render")
        self.mcp.call(
            "browser_type",
            {"target": "input[placeholder='例如：宠物、母婴辅食、户外露营']", "text": "宠物"},
            timeout=60,
        )
        self._set_input(".number-field input", "1", "xingtu-target")
        self.shot("06-xingtu-form")
        self.mcp.call("browser_click", {"target": "button.submit-button"}, timeout=60)
        task_id = self._wait_task_id("xingtu")
        self.state["tasks"]["xingtu"] = {"id": task_id, "submitted_at": time.time()}
        self.save()
        self.check(
            "JXM-XT-01",
            bool(task_id),
            f"真实 UI 提交星图任务 id={task_id}，条件=宠物/target=1",
            "06-xingtu-form",
        )
        return task_id

    # -- polling --------------------------------------------------------------------------
    def _task(self, task_id: str, name: str) -> dict[str, Any]:
        return self.api(f"/api/tasks/{task_id}", name) or {}

    def _unit(self, name: str) -> dict[str, Any]:
        units = self.api("/api/execution-units", name) or []
        for unit in units:
            if unit.get("unit_id") == "unit-local-mac-02":
                return unit
        return {}

    def poll(self, timeout_seconds: int) -> dict[str, Any]:
        ids = {key: value["id"] for key, value in self.state["tasks"].items()}
        started = time.time()
        polls: list[dict[str, Any]] = []
        last: dict[str, Any] = {}
        while time.time() - started < timeout_seconds:
            entry: dict[str, Any] = {"at": time.strftime("%H:%M:%S"), "tasks": {}, "unit": {}}
            for key, task_id in ids.items():
                data = self._task(task_id, f"poll-{key}")
                counts = data.get("counts") or {}
                entry["tasks"][key] = {
                    "status": data.get("status"),
                    "stage": data.get("stage"),
                    "platform": data.get("platform"),
                    "valid": counts.get("valid_count"),
                    "profile": counts.get("profile_complete_count"),
                    "target": counts.get("target_count"),
                    "failure": data.get("failure_reason"),
                }
                last[key] = data
            unit = self._unit("poll-unit")
            entry["unit"] = {
                "state": unit.get("state"),
                "current_root_task_id": unit.get("current_root_task_id"),
                "platforms": unit.get("platforms"),
                "verification_state": unit.get("verification_state"),
                "worker_status": unit.get("worker_status"),
            }
            polls.append(entry)
            statuses = {key: entry["tasks"][key]["status"] for key in ids}
            current = entry["unit"]["current_root_task_id"]
            print(
                f"[poll] {entry['at']} statuses={statuses} unit_current={current}",
                flush=True,
            )
            if statuses and all(status in TERMINAL for status in statuses.values()):
                break
            if any(status == "WAITING_FOR_VERIFICATION" for status in statuses.values()):
                print(
                    "[poll] WAITING_FOR_VERIFICATION detected; human action may be required",
                    flush=True,
                )
            time.sleep(5)
        self.state["polls"] = polls
        self.save()
        return last

    # -- result checks --------------------------------------------------------------------
    def result_checks(self) -> None:
        ids = {key: value["id"] for key, value in self.state["tasks"].items()}
        expected = {
            "juxing": ("kuaishou_juxing", "JXM-JX-05"),
            "xingtu": ("douyin_xingtu", "JXM-XT-04"),
        }
        for key, (platform, case) in expected.items():
            data = self._task(ids[key], f"final-{key}")
            counts = data.get("counts") or {}
            ok = (
                data.get("status") == "COMPLETED"
                and data.get("platform") == platform
                and counts.get("target_count") == 1
                and counts.get("valid_count") == 1
                and counts.get("profile_complete_count") == 1
                and not data.get("failure_reason")
            )
            self.check(
                case,
                ok,
                f"{key} 终态={data.get('status')} platform={data.get('platform')} "
                f"counts={counts.get('valid_count')}/{counts.get('profile_complete_count')}/1 "
                f"failure={data.get('failure_reason')}",
                f"final-{key}",
                kind="真实任务",
            )

        polls = self.state.get("polls", [])
        executing = [
            {key for key, task in poll["tasks"].items() if task["status"] in EXECUTING}
            for poll in polls
        ]
        self.check(
            "JXM-EU-02",
            bool(polls) and all(len(running) <= 1 for running in executing),
            f"每轮最多一个平台处于执行态，轮询数={len(polls)}",
            "polls",
            kind="真实任务",
        )
        overlap = any(
            poll["tasks"]["juxing"]["status"] in EXECUTING
            and poll["tasks"]["xingtu"]["status"] == "QUEUED"
            for poll in polls
        )
        switch = any(
            poll["tasks"]["juxing"]["status"] == "COMPLETED"
            and poll["tasks"]["xingtu"]["status"] in EXECUTING
            for poll in polls
        )
        self.check(
            "JXM-EU-03",
            overlap and switch,
            f"聚星执行时星图排队={overlap}；聚星结束后星图执行={switch}",
            "polls",
            kind="真实任务",
        )
        currents = [
            poll["unit"].get("current_root_task_id")
            for poll in polls
            if poll["unit"].get("current_root_task_id")
        ]
        self.check(
            "JXM-EU-01",
            bool(currents) and set(currents) <= {ids["juxing"], ids["xingtu"]},
            "两个任务都由同一个 unit-local-mac-02 领取",
            "polls",
            kind="真实任务",
        )
        self.check(
            "JXM-EU-04",
            bool(currents) and currents[0] == ids["juxing"] and currents[-1] == ids["xingtu"],
            f"单元当前任务从聚星切换到星图：{currents[0][:8]} -> {currents[-1][:8]}",
            "polls",
            kind="真实任务",
        )
        final_unit = self._unit("final-unit")
        self.check(
            "JXM-EU-05",
            final_unit.get("state") == "READY"
            and not final_unit.get("current_root_task_id")
            and final_unit.get("browser_status") == "STOPPED",
            f"租约释放：state={final_unit.get('state')} "
            f"current={final_unit.get('current_root_task_id')} "
            f"browser={final_unit.get('browser_status')}",
            "final-unit",
            kind="真实任务",
        )

    # -- UI evidence ----------------------------------------------------------------------
    def ui_evidence(self) -> None:
        ids = {key: value["id"] for key, value in self.state["tasks"].items()}
        self.mcp.call_text("browser_navigate", {"url": f"{self.base}/tasks"}, timeout=120)
        self.page.wait_text("任务中心", tries=40)
        time.sleep(2)
        text = self.page.extract("07-task-center")["text"]
        short = {key: task_id[:8] for key, task_id in ids.items()}
        self.check(
            "JXM-TC-01",
            all(short_id in text for short_id in short.values()),
            "任务中心同时展示聚星与星图新任务",
            "07-task-center",
        )
        self.check(
            "JXM-TC-05",
            "磁力聚星" in text and "巨量星图" in text,
            "任务中心出现两个平台标签",
            "07-task-center",
        )
        self.shot("07-task-center")

        self.page.mcp.call(
            "browser_select_option",
            {"target": "select[aria-label='按平台筛选']", "values": ["kuaishou_juxing"]},
            timeout=60,
        )
        time.sleep(2)
        juxing_text = self.page.extract("08-task-filter-juxing")["text"]
        self.check(
            "JXM-TC-02",
            short["juxing"] in juxing_text and short["xingtu"] not in juxing_text,
            "聚星筛选只显示聚星任务",
            "08-task-filter-juxing",
        )
        self.shot("08-task-filter-juxing")
        self.page.mcp.call(
            "browser_select_option",
            {"target": "select[aria-label='按平台筛选']", "values": ["douyin_xingtu"]},
            timeout=60,
        )
        time.sleep(2)
        xingtu_text = self.page.extract("09-task-filter-xingtu")["text"]
        self.check(
            "JXM-TC-02D",
            short["xingtu"] in xingtu_text and short["juxing"] not in xingtu_text,
            "星图筛选只显示星图任务",
            "09-task-filter-xingtu",
        )
        self.shot("09-task-filter-xingtu")

        # Juxing task detail
        self.mcp.call_text(
            "browser_navigate", {"url": f"{self.base}/tasks/{ids['juxing']}"}, timeout=120
        )
        self.page.wait_text(ids["juxing"], tries=40)
        time.sleep(2)
        detail_text = self.page.extract("10-juxing-task-detail")["text"]
        self.check(
            "JXM-JX-07",
            "磁力聚星" in detail_text and "母婴亲子" in detail_text and "精选" not in detail_text,
            "聚星任务详情平台/条件正确且不显示精选",
            "10-juxing-task-detail",
        )
        self.shot("10-juxing-task-detail")

        # Creator library: juxing
        self.mcp.call_text(
            "browser_navigate",
            {"url": f"{self.base}/creators?platform=kuaishou_juxing"},
            timeout=120,
        )
        self.page.wait_text("磁力聚星达人", tries=40)
        time.sleep(2)
        library = self.page.extract("11-juxing-library")
        library_text = library.get("text", "")
        self.check(
            "JXM-LIB-01",
            "磁力聚星达人" in library_text and "位已加载" in library_text,
            "聚星达人库加载",
            "11-juxing-library",
        )
        self.shot("11-juxing-library")

        # Creator library: xingtu (existing baseline must remain readable)
        self.mcp.call_text(
            "browser_navigate", {"url": f"{self.base}/creators?platform=douyin_xingtu"}, timeout=120
        )
        self.page.wait_text("巨量星图达人", tries=40)
        time.sleep(2)
        xingtu_library = self.page.extract("12-xingtu-library")
        xingtu_text = xingtu_library.get("text", "")
        self.check(
            "JXM-LIB-02",
            "巨量星图达人" in xingtu_text and "位已加载" in xingtu_text,
            "星图达人库保留",
            "12-xingtu-library",
        )
        self.shot("12-xingtu-library")

        # Execution unit page
        self.mcp.call_text("browser_navigate", {"url": f"{self.base}/execution-units"}, timeout=120)
        self.page.wait_text("执行单元", tries=40)
        time.sleep(2)
        unit_text = self.page.extract("13-execution-units")["text"]
        self.check(
            "JXM-ACT-04",
            "unit-local-mac-02" in unit_text
            and "巨量星图" in unit_text
            and "磁力聚星" in unit_text,
            "执行单元页显示同一单元的双平台标签",
            "13-execution-units",
        )
        self.shot("13-execution-units")

        self.detail_checks()

    def detail_checks(self) -> None:
        self.mcp.call_text(
            "browser_navigate",
            {"url": f"{self.base}/creators?platform=kuaishou_juxing"},
            timeout=120,
        )
        self.page.wait_text("磁力聚星达人", tries=40)
        time.sleep(2)
        links_js = (
            "() => [...document.querySelectorAll('a.library-row')].map(a => a.getAttribute('href'))"
        )
        links = self.ev(links_js, "juxing-library-links")
        self.check(
            "JXM-LIB-03",
            bool(links),
            f"聚星达人库有 {len(links or [])} 个可达详情链接",
            "juxing-library-links",
        )
        if links:
            self.mcp.call_text("browser_navigate", {"url": self.base + links[0]}, timeout=120)
            self.page.wait_text("基础资料", tries=40)
            time.sleep(2)
            text = self.page.extract("14-juxing-creator-detail")["text"]
            self.check(
                "JXM-LIB-05",
                all(item in text for item in ("基础资料", "传播表现", "代表作品", "受众画像"))
                and "快手ID" in text,
                "聚星达人详情展示四个平台化章节与快手 ID",
                "14-juxing-creator-detail",
            )
            self.shot("14-juxing-creator-detail")

        self.mcp.call_text(
            "browser_navigate", {"url": f"{self.base}/creators?platform=douyin_xingtu"}, timeout=120
        )
        self.page.wait_text("巨量星图达人", tries=40)
        time.sleep(2)
        links_js = (
            "() => [...document.querySelectorAll('a.library-row')].map(a => a.getAttribute('href'))"
        )
        links = self.ev(links_js, "xingtu-library-links")
        if links:
            self.mcp.call_text("browser_navigate", {"url": self.base + links[0]}, timeout=120)
            self.page.wait_text("商业能力", tries=40)
            time.sleep(2)
            text = self.page.extract("15-xingtu-creator-detail")["text"]
            self.check(
                "JXM-LIB-07",
                all(item in text for item in ("商业能力", "创作能力", "履约能力", "连接用户")),
                "星图达人详情保留既有模块",
                "15-xingtu-creator-detail",
            )
            self.check(
                "JXM-LIB-08",
                "优秀传播视频" in text or "优秀种草视频" in text,
                "星图详情保留 F06 精选章节",
                "15-xingtu-creator-detail",
            )
            self.shot("15-xingtu-creator-detail")

    # -- run ------------------------------------------------------------------------------
    def run(self, phases: list[str]) -> None:
        ids = self.state.get("tasks", {})
        try:
            self.login()
            if "setup" in phases:
                self.setup_checks()
            if "submit" in phases:
                if "juxing" not in ids:
                    self.submit_juxing()
                else:
                    print(f"[submit] juxing already recorded: {ids['juxing']['id']}", flush=True)
                if "xingtu" not in ids:
                    self.submit_xingtu()
                else:
                    print(f"[submit] xingtu already recorded: {ids['xingtu']['id']}", flush=True)
            if "poll" in phases and self.state.get("tasks"):
                self.poll(int(self.state.get("poll_timeout", 900)))
                self.result_checks()
            if "ui" in phases and self.state.get("tasks"):
                if "poll" not in phases and self.state.get("polls"):
                    self.result_checks()
                self.ui_evidence()
        finally:
            self.save()
            report = {
                "schema_version": "juxing_main_mcp.v1",
                "base": self.base,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "tasks": self.state.get("tasks"),
                "cases": self.book.cases,
                "polls": self.state.get("polls", []),
            }
            (self.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            self.mcp.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--phases", nargs="+", default=["setup", "submit", "poll", "ui"])
    parser.add_argument("--poll-timeout", type=int, default=900)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--expect-juxing-tasks", type=int, default=0)
    args = parser.parse_args()
    driver = Driver(
        args.base,
        args.out,
        headless=not args.headed,
        expect_juxing_tasks=args.expect_juxing_tasks,
    )
    driver.state["poll_timeout"] = args.poll_timeout
    try:
        driver.run(args.phases)
    except Exception as exc:  # noqa: BLE001 - the report is the evidence
        print(f"DRIVER_ERROR: {type(exc).__name__}: {exc}", flush=True)
        return 1
    failed = [case for case in driver.book.cases if case["status"] == "FAIL"]
    print(f"cases={len(driver.book.cases)} failed={len(failed)}", flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
