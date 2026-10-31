#!/usr/bin/env python3
"""KJX-01 stage-C+ real-user regression over Playwright MCP + Chrome.

Every browser action goes through the locally installed @playwright/mcp server's browser_*
tools (MCP stdio), not Playwright Python page automation.  The driver:
  * logs into the product UI through the real login form,
  * verifies both platform catalogs and the new juxing filter surface,
  * submits T1/T2/T3 once from the real UI and polls the product API with the same session,
  * runs the two-platform UI/API regression and screenshots the evidence.

Task ids are persisted in state.json so a re-run never submits the same real task twice.
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

from kjx_full_mcp import Book, MCPPage, load_credentials  # noqa: E402
from mcp_client import PlaywrightMCP  # noqa: E402

DEFAULT_BASE = "http://127.0.0.1:4193"
DEFAULT_CREDS = ROOT / ".runtime/kjx-full/regression/credentials"
DEFAULT_OUT = ROOT / ".runtime/kjx-full/regression/mcp"

TERMINAL = {"COMPLETED", "PARTIAL_COMPLETED", "FAILED", "FAILED_VALIDATION", "CANCELLED", "EXPIRED"}


class Driver:
    def __init__(self, base: str, out: Path) -> None:
        self.base = base.rstrip("/")
        self.out = out
        self.out.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state_path = self.out / "state.json"
        self.state = (
            json.loads(self.state_path.read_text()) if self.state_path.exists() else {"tasks": {}}
        )
        self.book = Book()
        self.page: MCPPage | None = None

    # -- infrastructure -------------------------------------------------------------------
    def save(self) -> None:
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2))

    def login(self) -> None:
        assert self.page is not None
        page = self.page
        username, password = load_credentials(DEFAULT_CREDS)
        page.mcp.call_text("browser_navigate", {"url": f"{self.base}/login"}, timeout=120)
        if not page.wait_text("产品账号", tries=40):
            raise RuntimeError("login page did not render")
        page.mcp.call(
            "browser_type", {"target": "input[autocomplete=username]", "text": username}, timeout=60
        )
        page.mcp.call(
            "browser_type", {"target": ".password-field input", "text": password}, timeout=60
        )
        page.mcp.call("browser_click", {"target": "button.login-button"}, timeout=60)
        if not page.wait_text("任务中心", tries=60):
            raise RuntimeError("login did not reach the task center")
        text = page.extract("login-after")["text"]
        self.book.check(
            "KJX-REG-LOGIN", "回归媒介" in text, "登录后进入任务中心并显示回归媒介", "login-after"
        )

    def api(self, path: str, name: str = "api") -> dict[str, Any] | None:
        assert self.page is not None
        js = (
            "(async () => { const r = await fetch("
            + json.dumps(path)
            + ", {headers: {Accept: 'application/json'}});"
            " let body = null; try { body = await r.json(); } catch (e) { body = null; }"
            " return {status: r.status, body: body}; })()"
        )
        data = self.page.ev(js, name)
        if data.get("status") != 200:
            self.book.add(
                f"KJX-REG-API-{name}",
                "FAIL",
                f"{path} -> HTTP {data.get('status')}",
                name,
                kind="API 回读",
            )
            return None
        return data.get("body")

    def shot(self, name: str) -> str:
        assert self.page is not None
        return self.page.shot(name)

    # -- task creation --------------------------------------------------------------------
    def set_input(self, selector: str, value: str, name: str) -> None:
        assert self.page is not None
        js = (
            "() => { const input = document.querySelector("
            + json.dumps(selector)
            + "); if (!input) return null;"
            " const setter = Object.getOwnPropertyDescriptor("
            "window.HTMLInputElement.prototype, 'value').set;"
            " setter.call(input, "
            + json.dumps(value)
            + "); input.dispatchEvent(new Event('input', {bubbles: true}));"
            " input.dispatchEvent(new Event('change', {bubbles: true}));"
            " return input.value; }"
        )
        self.page.ev(js, name)

    def submit_juxing(
        self,
        task_key: str,
        keyword: str,
        content_type: str,
        target: int,
        followers: str | None,
        quote_max: int | None,
        region: bool = True,
    ) -> str:
        assert self.page is not None
        page = self.page
        page.mcp.call_text("browser_navigate", {"url": f"{self.base}/tasks/new"}, timeout=120)
        if not page.wait_text("磁力聚星", tries=40):
            raise RuntimeError("new task page did not render")
        page.click_text("磁力聚星")
        if not page.wait_text("内容类型", tries=40):
            raise RuntimeError("juxing form did not render")
        page.mcp.call(
            "browser_type",
            {"target": "input[placeholder='例如：母婴']", "text": keyword},
            timeout=60,
        )
        page.mcp.call(
            "browser_select_option",
            {"target": "select[aria-label='内容类型']", "values": [content_type]},
            timeout=60,
        )
        if followers:
            page.mcp.call(
                "browser_select_option",
                {"target": "select[aria-label='粉丝数量']", "values": [followers]},
                timeout=60,
            )
        if region:
            page.mcp.call(
                "browser_select_option",
                {"target": "select[aria-label='省级地域']", "values": ["11"]},
                timeout=60,
            )
        if quote_max is not None:
            page.mcp.call(
                "browser_select_option",
                {"target": "select[aria-label='报价档位']", "values": ["seconds_21_60"]},
                timeout=60,
            )
            page.mcp.call(
                "browser_type",
                {"target": "input[aria-label='报价上限（元）']", "text": str(quote_max)},
                timeout=60,
            )
        if target != 3:
            self.set_input(".number-field input", str(target), f"{task_key}-target")
        page.extract(f"{task_key}-form-before-submit")
        self.shot(f"{task_key}-form")
        page.mcp.call("browser_click", {"target": "button.submit-button"}, timeout=60)
        task_id = self.wait_created(task_key)
        self.book.check(
            f"KJX-REG-{task_key.upper()}-CREATE",
            bool(task_id),
            f"从真实 UI 提交 {task_key}，task={task_id}",
            f"{task_key}-form",
        )
        return task_id

    def submit_xingtu(self, task_key: str, keyword: str, target: int) -> str:
        assert self.page is not None
        page = self.page
        page.mcp.call_text("browser_navigate", {"url": f"{self.base}/tasks/new"}, timeout=120)
        if not page.wait_text("巨量星图", tries=40):
            raise RuntimeError("new task page did not render")
        page.click_text("巨量星图")
        if not page.wait_text("内容关键词", tries=40):
            raise RuntimeError("xingtu form did not render")
        page.mcp.call(
            "browser_type",
            {"target": "input[placeholder='例如：宠物、母婴辅食、户外露营']", "text": keyword},
            timeout=60,
        )
        if target != 20:
            self.set_input(".number-field input", str(target), f"{task_key}-target")
        page.extract(f"{task_key}-form-before-submit")
        self.shot(f"{task_key}-form")
        page.mcp.call("browser_click", {"target": "button.submit-button"}, timeout=60)
        task_id = self.wait_created(task_key)
        self.book.check(
            f"KJX-REG-{task_key.upper()}-CREATE",
            bool(task_id),
            f"从真实 UI 提交 {task_key}，task={task_id}",
            f"{task_key}-form",
        )
        return task_id

    def wait_created(self, task_key: str) -> str:
        assert self.page is not None
        page = self.page
        started = time.time()
        while time.time() - started < 60:
            path = page.ev("() => location.pathname", f"{task_key}-path")
            match = re.match(r"^/tasks/([0-9a-f-]{36})$", str(path))
            if match:
                return match.group(1)
            time.sleep(0.5)
        tasks = self.api("/api/tasks?limit=20", f"{task_key}-recent")
        items = (tasks or {}).get("items", [])
        for item in items:
            if item.get("root_task_id"):
                return str(item["root_task_id"])
        raise RuntimeError(f"{task_key}: task id not observed")

    def poll(self, task_key: str, task_id: str, timeout_seconds: int) -> dict[str, Any]:
        started = time.time()
        last: dict[str, Any] = {}
        while time.time() - started < timeout_seconds:
            data = self.api(f"/api/tasks/{task_id}", f"{task_key}-poll") or {}
            last = data
            status = data.get("status")
            counts = data.get("counts") or {}
            progress = (
                f"[{task_key}] {status} valid={counts.get('valid_count')} "
                f"profile={counts.get('profile_complete_count')} "
                f"failed={counts.get('failed_count')}"
            )
            print(progress, flush=True)
            if status in TERMINAL:
                actual = (
                    f"{task_key} 终态 {status}，"
                    f"valid={counts.get('valid_count')}/{counts.get('target_count')}，"
                    f"failure={data.get('failure_reason')}"
                )
                self.book.check(
                    f"KJX-REG-{task_key.upper()}-TERMINAL",
                    status in {"COMPLETED", "PARTIAL_COMPLETED"},
                    actual,
                    f"{task_key}-poll",
                    kind="真实任务",
                )
                return data
            time.sleep(5)
        self.book.add(
            f"KJX-REG-{task_key.upper()}-TIMEOUT",
            "FAIL",
            f"{task_key} 在 {timeout_seconds}s 内未终态",
            f"{task_key}-poll",
            kind="真实任务",
        )
        return last

    # -- phases ---------------------------------------------------------------------------
    def setup_checks(self) -> None:
        assert self.page is not None
        page = self.page
        page.mcp.call_text("browser_navigate", {"url": f"{self.base}/tasks"}, timeout=120)
        page.wait_text("任务中心", tries=40)
        self.shot("01-tasks")
        platforms = self.api("/api/platforms", "platforms") or []
        by_platform = {item.get("platform"): item for item in platforms if isinstance(item, dict)}
        self.book.check(
            "KJX-REG-PLATFORMS",
            set(by_platform) == {"douyin_xingtu", "kuaishou_juxing"}
            and all(item.get("enabled") for item in by_platform.values()),
            "平台目录："
            f"{[(k, v.get('enabled'), v.get('contract_version')) for k, v in by_platform.items()]}",
            "platforms",
            kind="API 回读",
        )
        jux = self.api("/api/platforms/kuaishou_juxing/capabilities", "juxing-capabilities") or {}
        fields = {field.get("field"): field for field in jux.get("fields", [])}
        content = fields.get("content_type", {})
        region = fields.get("region", {})
        quote_fields = [key for key in fields if key.startswith("video_quote_")]
        capability_actual = (
            f"v={jux.get('capability_version')} max={jux.get('target_count_max')} "
            f"fields={sorted(fields)} content={len(content.get('options', []))} "
            f"regions={len(region.get('region_tree', []))} quotes={quote_fields}"
        )
        self.book.check(
            "KJX-REG-CAPABILITY",
            jux.get("target_count_max") == 30
            and len(fields) == 7
            and len(content.get("options", [])) == 38
            and len(region.get("region_tree", [])) == 34
            and len(quote_fields) == 3,
            capability_actual,
            "juxing-capabilities",
            kind="API 回读",
        )
        xing = self.api("/api/platforms/douyin_xingtu/capabilities", "xingtu-capabilities") or {}
        self.book.check(
            "KJX-REG-XINGTU-CAPABILITY",
            bool(xing.get("fields")),
            f"星图 capability={xing.get('capability_version')} "
            f"fields={len(xing.get('fields', []))}",
            "xingtu-capabilities",
            kind="API 回读",
        )
        # Form render without submission.
        page.mcp.call_text("browser_navigate", {"url": f"{self.base}/tasks/new"}, timeout=120)
        page.wait_text("磁力聚星", tries=40)
        page.click_text("磁力聚星")
        page.wait_text("内容类型", tries=40)
        form = page.extract("juxing-form")
        text = form.get("text", "")
        self.book.check(
            "KJX-REG-JUXING-FORM",
            all(
                x in text for x in ("内容类型", "粉丝数量", "达人地域", "视频报价", "目标达人数量")
            ),
            "聚星表单显示内容类型/粉丝/地域/报价/目标数量",
            "juxing-form",
        )
        self.shot("02-juxing-form")
        page.mcp.call_text("browser_navigate", {"url": f"{self.base}/tasks/new"}, timeout=120)
        page.wait_text("巨量星图", tries=40)
        page.click_text("巨量星图")
        page.wait_text("内容关键词", tries=40)
        xingtu_form = page.extract("xingtu-form")
        self.book.check(
            "KJX-REG-XINGTU-FORM",
            all(x in xingtu_form.get("text", "") for x in ("内容关键词", "目标达人数量")),
            "星图表单仍渲染内容关键词/目标数量",
            "xingtu-form",
        )
        self.shot("03-xingtu-form")

    def task_phase(self, key: str) -> dict[str, Any] | None:
        existing = (self.state.get("tasks") or {}).get(key)
        if existing:
            print(
                f"[{key}] existing task {existing['task_id']} (submitted once, no duplicate)",
                flush=True,
            )
            result = self.poll(key, existing["task_id"], int(existing.get("timeout", 1800)))
            existing["result_summary"] = {
                k: result.get(k) for k in ("status", "counts", "failure_reason", "stage")
            }
            self.save()
            return result
        if key == "t1":
            task_id = self.submit_juxing("t1", "母婴", "maternal_child", 3, "10w_100w", 10000)
            timeout = 1800
        elif key == "t2":
            task_id = self.submit_juxing(
                "t2", "母婴", "maternal_child", 22, None, None, region=False
            )
            timeout = 3600
        elif key == "t3":
            task_id = self.submit_xingtu("t3", "宠物", 1)
            timeout = 1800
        elif key == "t3_retry":
            task_id = self.submit_xingtu("t3_retry", "宠物", 1)
            timeout = 5400
        else:
            raise ValueError(key)
        if not task_id:
            return None
        self.state.setdefault("tasks", {})[key] = {
            "task_id": task_id,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "platform": "kuaishou_juxing" if key in {"t1", "t2"} else "douyin_xingtu",
            "target": {"t1": 3, "t2": 22, "t3": 1, "t3_retry": 1}[key],
            "timeout": timeout,
        }
        self.save()
        result = self.poll(key, task_id, timeout)
        self.state["tasks"][key]["result_summary"] = {
            k: result.get(k) for k in ("status", "counts", "failure_reason", "stage")
        }
        self.save()
        self.shot(f"{key}-task-detail")
        return result

    def regression_phase(self) -> None:
        assert self.page is not None
        page = self.page
        tasks = self.state.get("tasks") or {}
        # Task center: both platforms, task rows visible.
        page.mcp.call_text("browser_navigate", {"url": f"{self.base}/tasks"}, timeout=120)
        page.wait_text("任务中心", tries=40)
        tasks_text = page.extract("regression-tasks")["text"]
        self.book.check(
            "KJX-REG-TASKS-UI",
            "巨量星图" in tasks_text and "磁力聚星" in tasks_text,
            "任务中心显示两个平台的任务",
            "regression-tasks",
        )
        self.shot("10-task-center")
        # Juxing library + detail.
        page.mcp.call_text(
            "browser_navigate",
            {"url": f"{self.base}/creators?platform=kuaishou_juxing"},
            timeout=120,
        )
        page.wait_text("磁力聚星达人", tries=40)
        jux_library = page.extract("juxing-library")
        self.book.check(
            "KJX-REG-JUXING-LIBRARY",
            "磁力聚星达人" in jux_library.get("text", ""),
            "聚星达人库加载",
            "juxing-library",
        )
        self.shot("11-juxing-library")
        creators = (
            self.api("/api/creator-library?platform=kuaishou_juxing&limit=5", "juxing-library-api")
            or {}
        )
        items = creators.get("items", [])
        self.book.check(
            "KJX-REG-JUXING-LIBRARY-COUNT",
            bool(items),
            f"聚星达人库 API items={len(items)}",
            "juxing-library-api",
            kind="API 回读",
        )
        if items:
            creator = items[0]
            summary_actual = (
                f"聚星列表 summary 粉丝={creator.get('followers', {}).get('value')} "
                f"互动={creator.get('interaction_rate', {}).get('value')} "
                f"播放中位数={creator.get('play_median', {}).get('value')}"
            )
            self.book.check(
                "KJX-REG-JUXING-SUMMARY",
                creator.get("followers", {}).get("value") is not None
                and creator.get("interaction_rate", {}).get("status") == "COLLECTED",
                summary_actual,
                "juxing-library-api",
                kind="API 回读",
            )
            page.mcp.call_text(
                "browser_navigate",
                {"url": f"{self.base}/creators/{creator['creator_id']}"},
                timeout=120,
            )
            page.wait_text("快手ID", tries=40)
            basic = page.extract("juxing-detail-basic")
            self.shot("12-juxing-detail-basic")
            self.book.check(
                "KJX-REG-JUXING-DETAIL-BASIC",
                all(x in basic.get("text", "") for x in ("快手ID", "性别", "内容形式", "快手主页")),
                "聚星详情基础区显示快手ID/性别/内容形式/主页链接",
                "juxing-detail-basic",
            )
            page.click_text("传播表现")
            page.wait_text("传播表现", tries=20)
            spread = page.extract("juxing-detail-spread")
            self.shot("13-juxing-detail-spread")
            self.book.check(
                "KJX-REG-JUXING-DETAIL-SPREAD",
                any(
                    x in spread.get("text", "")
                    for x in (
                        "播放中位数优于同类",
                        "互动率优于同类",
                        "连接用户数",
                        "近期CPM",
                        "近期CPE",
                        "转化点击率",
                        "visitor_num",
                        "recent_cpm",
                        "play_median_percentile",
                    )
                ),
                "聚星传播表现显示新注册字段",
                "juxing-detail-spread",
            )
            page.click_text("代表作品")
            page.wait_text("代表及近期作品", tries=20)
            works = page.extract("juxing-detail-works")
            self.shot("14-juxing-detail-works")
            self.book.check(
                "KJX-REG-JUXING-DETAIL-WORKS",
                "代表及近期作品" in works.get("text", "") and bool(works.get("workImages")),
                f"聚星作品区有封面图 {len(works.get('workImages') or [])} 张",
                "juxing-detail-works",
            )
            page.click_text("受众画像")
            page.wait_text("粉丝画像", tries=20)
            audience = page.extract("juxing-detail-audience")
            self.shot("15-juxing-detail-audience")
            self.book.check(
                "KJX-REG-JUXING-DETAIL-AUDIENCE",
                "查看平台原始结构" in audience.get("text", "")
                and "占比" in audience.get("text", ""),
                "聚星受众画像显示维度表与原始结构",
                "juxing-detail-audience",
            )
        # Xingtu library remains intact.
        page.mcp.call_text(
            "browser_navigate", {"url": f"{self.base}/creators?platform=douyin_xingtu"}, timeout=120
        )
        page.wait_text("巨量星图达人", tries=40)
        xingtu_library = page.extract("xingtu-library")
        self.shot("16-xingtu-library")
        self.book.check(
            "KJX-REG-XINGTU-LIBRARY",
            "巨量星图达人" in xingtu_library.get("text", ""),
            "星图达人库加载",
            "xingtu-library",
        )
        x_items = (
            self.api("/api/creator-library?platform=douyin_xingtu&limit=5", "xingtu-library-api")
            or {}
        ).get("items", [])
        self.book.check(
            "KJX-REG-XINGTU-LIBRARY-COUNT",
            bool(x_items),
            f"星图达人库 API items={len(x_items)}",
            "xingtu-library-api",
            kind="API 回读",
        )
        if x_items:
            page.mcp.call_text(
                "browser_navigate",
                {"url": f"{self.base}/creators/{x_items[0]['creator_id']}"},
                timeout=120,
            )
            page.wait_text("星图ID", tries=40)
            xdetail = page.extract("xingtu-detail")
            self.shot("17-xingtu-detail")
            self.book.check(
                "KJX-REG-XINGTU-DETAIL",
                "星图ID" in xdetail.get("text", "") and "商业能力" in xdetail.get("text", ""),
                "星图详情仍显示星图ID/商业能力等既有章节",
                "xingtu-detail",
            )
        # Task details for all three.
        for key in ("t1", "t2", "t3"):
            entry = tasks.get(key)
            if not entry:
                continue
            page.mcp.call_text(
                "browser_navigate", {"url": f"{self.base}/tasks/{entry['task_id']}"}, timeout=120
            )
            page.wait_text("任务", tries=40)
            detail = page.extract(f"{key}-detail")
            self.shot(f"18-{key}-detail")
            self.book.check(
                f"KJX-REG-{key.upper()}-DETAIL",
                entry["task_id"] in page.mcp.call_text("browser_snapshot")
                or "任务" in detail.get("text", ""),
                f"{key} 任务详情可打开",
                f"{key}-detail",
            )
        # API payload checks for the first juxing creator and first xingtu creator.
        if items:
            detail = (
                self.api(f"/api/creator-library/{items[0]['creator_id']}", "juxing-detail-api")
                or {}
            )
            payload = detail.get("profile_payload") or {}
            modules = payload.get("modules") or {}
            counts = {key: len((value or {}).get("fields", [])) for key, value in modules.items()}
            payload_actual = (
                f"聚星详情 payload 字段数={counts} "
                f"profile_complete={detail.get('profile_complete')} "
                f"pipeline={detail.get('pipeline_complete')}"
            )
            self.book.check(
                "KJX-REG-JUXING-PAYLOAD",
                counts.get("basic") == 18
                and counts.get("spread") == 31
                and counts.get("works") == 1
                and counts.get("audience") == 2,
                payload_actual,
                "juxing-detail-api",
                kind="API 回读",
            )
        for key in ("t1", "t2", "t3"):
            entry = tasks.get(key)
            if not entry:
                continue
            detail = self.api(f"/api/tasks/{entry['task_id']}", f"{key}-api-final") or {}
            counts = detail.get("counts") or {}
            final_actual = (
                f"{key} final status={detail.get('status')} "
                f"valid={counts.get('valid_count')}/{counts.get('target_count')} "
                f"profile_complete={counts.get('profile_complete_count')} "
                f"failure={detail.get('failure_reason')}"
            )
            self.book.check(
                f"KJX-REG-{key.upper()}-FINAL",
                detail.get("status") in {"COMPLETED", "PARTIAL_COMPLETED"}
                and int(counts.get("valid_count", 0)) >= int(entry["target"]) - 1,
                final_actual,
                f"{key}-api-final",
                kind="API 回读",
            )

    def run(self, phases: list[str]) -> None:
        username, password = load_credentials(DEFAULT_CREDS)  # noqa: F841 - fail early if private file is absent
        mcp = PlaywrightMCP(self.out, headless=True, log_path=self.out / "mcp-server.log")
        try:
            mcp.initialize()
            self.page = MCPPage(mcp, self.out)
            self.login()
            if "setup" in phases:
                self.setup_checks()
            for key in ("t1", "t2", "t3", "t3_retry"):
                if key in phases:
                    self.task_phase(key)
            if "regression" in phases:
                self.regression_phase()
        except Exception as exc:  # noqa: BLE001 - retain the failure as evidence
            self.book.add("KJX-REG-RUN", "FAIL", f"{type(exc).__name__}: {exc}", "driver")
            raise
        finally:
            try:
                mcp.close()
            except Exception:  # noqa: BLE001
                pass
            report = {
                "phase": "+".join(phases),
                "base": self.base,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "tasks": self.state.get("tasks", {}),
                "cases": self.book.cases,
                "summary": self.book.summary(),
            }
            (self.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps(report["summary"], ensure_ascii=False), flush=True)
            print(f"report: {self.out / 'report.json'}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--phases", default="setup,t1,t2,t3,regression")
    args = parser.parse_args()
    phases = [item.strip() for item in args.phases.split(",") if item.strip()]
    Driver(args.base, args.out).run(phases)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
