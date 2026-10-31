#!/usr/bin/env python3
"""Independent QA regression over Playwright MCP + Chrome for the 5173 dual-platform station.

Reads existing tasks/creators only; it never submits a real collection task. Clicking submit on an
empty form is safe because the client rejects it before any request. Every browser action goes
through @playwright/mcp tools over MCP stdio.
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

BASE = "http://127.0.0.1:5173"
OUT = ROOT / ".runtime/qa-round/mcp"
CREDS = ROOT / ".runtime/qa-credentials.env"
JUXING_TASK = "b9517e8b-a342-484f-980d-39137f95ff25"
XINGTU_TASK = "c30b7622-a054-4a0d-9969-e150512e4479"
HISTORICAL_TASK = "6dff3c73-6818-4ef2-8183-d94706240d9b"


def password() -> str:
    for line in CREDS.read_text().splitlines():
        if line.startswith("QA_MEDIA_A_PASSWORD="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("QA_MEDIA_A_PASSWORD missing")


class Driver:
    def __init__(self, out: Path, headless: bool = True) -> None:
        self.out = out
        self.out.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.book = Book()
        self.mcp = PlaywrightMCP(out / "mcp-output", headless=headless, log_path=out / "mcp.log")
        self.mcp.initialize()
        self.page = MCPPage(self.mcp, out)

    def check(
        self, case: str, ok: bool, actual: str, evidence: str, *, kind: str = "真实 UI"
    ) -> bool:
        return self.book.check(case, ok, actual, evidence, kind=kind)

    def add(
        self, case: str, status: str, actual: str, evidence: str, *, kind: str = "真实 UI"
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
            return None
        return data.get("body")

    def shot(self, name: str) -> str:
        return self.page.shot(name)

    def rows(self, name: str) -> list[str]:
        return self.ev(
            "() => [...document.querySelectorAll('.task-row:not(.table-head)')]"
            ".map(r => r.innerText.replace(/\\s+/g,' ').trim())",
            name,
        )

    def login(self) -> None:
        self.mcp.call_text("browser_navigate", {"url": f"{BASE}/login"}, timeout=120)
        if not self.page.wait_text("产品账号", tries=40):
            raise RuntimeError("login page did not render")
        login_text = self.page.extract("qa-login")["text"]
        self.check(
            "QAR-UI-01",
            all(x in login_text for x in ("产品账号", "密码", "安全登录")),
            "登录页渲染产品账号、密码、安全登录",
            "qa-login",
        )
        self.mcp.call(
            "browser_type",
            {"target": "input[autocomplete=username]", "text": "media-a"},
            timeout=60,
        )
        self.mcp.call(
            "browser_type", {"target": ".password-field input", "text": password()}, timeout=60
        )
        self.mcp.call("browser_click", {"target": "button.login-button"}, timeout=60)
        if not self.page.wait_text("任务中心", tries=60):
            raise RuntimeError("login did not reach the task center")
        text = self.page.extract("qa-after-login")["text"]
        self.check(
            "QAR-UI-02",
            "媒介 A" in text and "任务中心" in text,
            "media-a 登录进入任务中心",
            "qa-after-login",
        )

    # -- P0 smoke + navigation ------------------------------------------------------------
    def navigation(self) -> None:
        targets = [
            ("/tasks", "MEDIA OPERATIONS", "qa-nav-tasks"),
            ("/tasks/new", "NEW COLLECTION TASK", "qa-nav-new"),
            ("/creators", "CREATOR LIBRARY", "qa-nav-library"),
            ("/execution-units", "RESOURCE CONTROL", "qa-nav-units"),
        ]
        expected = {
            "/tasks": "MEDIA OPERATIONS",
            "/tasks/new": "NEW COLLECTION TASK",
            "/creators": "CREATOR LIBRARY",
            "/execution-units": "RESOURCE CONTROL",
        }
        ok = True
        for path, _needle, name in targets:
            self.mcp.call_text("browser_navigate", {"url": BASE + path}, timeout=120)
            ok = self.page.wait_text(expected[path], tries=40) and ok
            self.shot(name)
        self.check("QAR-UI-03", ok, "任务中心/创建任务/达人库/执行单元四页可达", "qa-nav-*")

        self.mcp.call_text("browser_navigate", {"url": f"{BASE}/tasks"}, timeout=120)
        self.page.wait_text("任务中心", tries=40)
        self.mcp.call_text("browser_navigate", {"url": f"{BASE}/tasks"}, timeout=120)
        reloaded = self.page.wait_text("任务中心", tries=40)
        self.check(
            "QAR-UI-04",
            reloaded and bool(self.rows("qa-refresh-rows")),
            "刷新任务中心后页面恢复并加载任务",
            "qa-refresh-rows",
        )

    # -- platform selection and forms -----------------------------------------------------
    def forms(self) -> None:
        self.mcp.call_text("browser_navigate", {"url": f"{BASE}/tasks/new"}, timeout=120)
        self.page.wait_text("采集平台", tries=40)
        radios = self.ev(
            "() => [...document.querySelectorAll('[role=radio]')].map(b => "
            "({text:b.innerText, disabled:b.disabled, checked:b.getAttribute('aria-checked')}))",
            "qa-platforms",
        )
        self.check(
            "QAR-PLT-01",
            len(radios) == 2 and all(not r["disabled"] for r in radios),
            f"平台选项={radios}",
            "qa-platforms",
        )
        xingtu_text = self.page.extract("qa-form-xingtu")["text"]
        self.check(
            "QAR-PLT-02",
            "xingtu-ad-creator-square-v3" in xingtu_text
            and "内容关键词" in xingtu_text
            and "达人性别" in xingtu_text,
            "星图表单字段与能力版本正确",
            "qa-form-xingtu",
        )
        self.shot("qa-form-xingtu")

        self.page.click_text("磁力聚星")
        self.page.wait_text("内容类型", tries=40)
        juxing_text = self.page.extract("qa-form-juxing")["text"]
        self.check(
            "QAR-PLT-03",
            "juxing-video-square-stage-c-v2" in juxing_text
            and "内容类型" in juxing_text
            and "当前环境允许 1—30 位" in juxing_text
            and "母婴亲子" in juxing_text,
            "聚星表单合同字段/38 类目/上限 30 正确",
            "qa-form-juxing",
        )
        self.shot("qa-form-juxing")

        # Fill a juxing keyword, switch to xingtu, verify no cross-platform leakage.
        self.mcp.call(
            "browser_type",
            {"target": "input[placeholder='例如：母婴']", "text": "母婴"},
            timeout=60,
        )
        self.page.click_text("巨量星图")
        self.page.wait_text("达人性别", tries=40)
        xingtu_values = self.ev(
            "() => [...document.querySelectorAll('input,select')].map(e => e.value)",
            "qa-xingtu-values",
        )
        self.check(
            "QAR-PLT-04",
            all(v != "母婴" for v in xingtu_values)
            and "内容类型" not in self.page.extract("qa-xingtu-form")["text"],
            "切换平台后不携带聚星筛选值/字段",
            "qa-xingtu-values",
        )
        self.page.click_text("磁力聚星")
        self.page.wait_text("内容类型", tries=40)
        juxing_values = self.ev(
            "() => [...document.querySelectorAll('input,select')].map(e => e.value)",
            "qa-juxing-values",
        )
        self.check(
            "QAR-PLT-04B",
            all(value != "母婴" for value in juxing_values),
            f"切回聚星表单已重置，未保留跨平台筛选值：{juxing_values}",
            "qa-juxing-values",
        )

        overflow = self.ev(
            "() => { const i=document.querySelector('.number-field input');"
            " const setter=Object.getOwnPropertyDescriptor("
            "window.HTMLInputElement.prototype,'value').set;"
            " setter.call(i,'31'); i.dispatchEvent(new Event('input',{bubbles:true}));"
            " i.dispatchEvent(new Event('change',{bubbles:true}));"
            " return {value:i.value, valid:i.validity.valid,"
            " overflow:i.validity.rangeOverflow, max:i.max}; }",
            "qa-target-31",
        )
        self.check(
            "QAR-PLT-05",
            overflow.get("max") == "30"
            and overflow.get("valid") is False
            and overflow.get("overflow") is True,
            f"聚星目标 31 触发浏览器范围校验：{overflow}",
            "qa-target-31",
        )
        self._set_input(".number-field input", "1", "qa-target-reset")

        # Clear the juxing keyword before clicking submit: an empty form is rejected client-side,
        # while a form with a business filter would create a real task.
        self._set_input("input[placeholder='例如：母婴']", "", "qa-clear-juxing-keyword")
        time.sleep(0.3)
        self.mcp.call("browser_click", {"target": "button.submit-button"}, timeout=60)
        time.sleep(1)
        empty_text = self.ev("() => document.body.innerText", "qa-empty-submit")
        path = self.ev("() => location.pathname", "qa-empty-path")
        self.check(
            "QAR-PLT-06A",
            "请至少设置一项业务筛选条件" in empty_text and str(path) == "/tasks/new",
            "聚星空表单提交被客户端拦截",
            "qa-empty-submit",
        )
        self.page.click_text("巨量星图")
        self.page.wait_text("达人性别", tries=40)
        self.mcp.call("browser_click", {"target": "button.submit-button"}, timeout=60)
        time.sleep(1)
        empty_text = self.ev("() => document.body.innerText", "qa-empty-submit-xingtu")
        path = self.ev("() => location.pathname", "qa-empty-path-xingtu")
        self.check(
            "QAR-PLT-06B",
            "请至少设置一项业务筛选条件" in empty_text and str(path) == "/tasks/new",
            "星图空表单提交被客户端拦截",
            "qa-empty-submit-xingtu",
        )

    def _set_input(self, selector: str, value: str, name: str) -> None:
        js = (
            "() => { const input = document.querySelector("
            + json.dumps(selector)
            + "); if (!input) return null;"
            " const setter = Object.getOwnPropertyDescriptor("
            "window.HTMLInputElement.prototype,'value').set;"
            " setter.call(input, " + json.dumps(value) + ");"
            " input.dispatchEvent(new Event('input',{bubbles:true}));"
            " input.dispatchEvent(new Event('change',{bubbles:true}));"
            " return input.value; }"
        )
        self.ev(js, name)

    # -- task center ----------------------------------------------------------------------
    def task_center(self) -> None:
        self.mcp.call_text("browser_navigate", {"url": f"{BASE}/tasks"}, timeout=120)
        self.page.wait_text("任务中心", tries=40)
        time.sleep(2)
        text = self.page.extract("qa-task-center")["text"]
        self.check(
            "QAR-TC-01",
            "任务中心" in text
            and "宠物" in text
            and "母婴" in text
            and "巨量星图" in text
            and "磁力聚星" in text,
            "任务中心首屏混排两平台任务与计数",
            "qa-task-center",
        )
        rows = self.rows("qa-tc-rows")
        self.check(
            "QAR-TC-04",
            any("#c30b7622" in row and "巨量星图" in row for row in rows)
            and any("#b9517e8b" in row and "磁力聚星" in row for row in rows),
            "两平台真实任务行标识正确",
            "qa-tc-rows",
        )
        self.shot("qa-task-center")

        self.page.mcp.call(
            "browser_select_option",
            {"target": "select[aria-label='按平台筛选']", "values": ["douyin_xingtu"]},
            timeout=60,
        )
        time.sleep(2)
        xingtu_rows = self.rows("qa-tc-xingtu-rows")
        xingtu_api = self.api("/api/tasks?limit=20&platform=douyin_xingtu", "qa-api-xingtu")
        self.check(
            "QAR-TC-02",
            bool(xingtu_api)
            and all(item.get("platform") == "douyin_xingtu" for item in xingtu_api.get("items", []))
            and all("巨量星图" in row for row in xingtu_rows)
            and not any("磁力聚星" in row for row in xingtu_rows),
            f"星图筛选返回 {len(xingtu_api.get('items', []) if xingtu_api else [])} 条且无聚星",
            "qa-tc-xingtu-rows",
        )
        self.shot("qa-task-filter-xingtu")

        self.page.mcp.call(
            "browser_select_option",
            {"target": "select[aria-label='按平台筛选']", "values": ["kuaishou_juxing"]},
            timeout=60,
        )
        time.sleep(2)
        juxing_rows = self.rows("qa-tc-juxing-rows")
        juxing_api = self.api("/api/tasks?limit=20&platform=kuaishou_juxing", "qa-api-juxing")
        self.check(
            "QAR-TC-03",
            bool(juxing_api)
            and len(juxing_api.get("items", [])) == 1
            and any("#b9517e8b" in row for row in juxing_rows)
            and all("磁力聚星" in row for row in juxing_rows),
            f"聚星筛选返回 {len(juxing_api.get('items', []) if juxing_api else [])} 条",
            "qa-tc-juxing-rows",
        )
        self.shot("qa-task-filter-juxing")

        # Pagination: compute the second page through the API, then click the UI button.
        self.page.mcp.call(
            "browser_select_option",
            {"target": "select[aria-label='按平台筛选']", "values": ["douyin_xingtu"]},
            timeout=60,
        )
        time.sleep(2)
        first = self.api("/api/tasks?limit=20&platform=douyin_xingtu", "qa-page-1")
        cursor = (first or {}).get("next_cursor")
        second = (
            self.api(
                f"/api/tasks?limit=20&platform=douyin_xingtu&cursor={cursor}",
                "qa-page-2",
            )
            if cursor
            else None
        )
        second_ids = [item.get("root_task_id", "")[:8] for item in (second or {}).get("items", [])]
        clicked = self.page.click_text("查看更早任务")
        time.sleep(2)
        older_rows = self.rows("qa-tc-older-rows")
        self.check(
            "QAR-TC-05",
            clicked
            and bool(second_ids)
            and any(any(sid in row for row in older_rows) for sid in second_ids),
            f"点击更早任务后命中第二页任务 {second_ids[:3]}",
            "qa-tc-older-rows",
        )
        self.shot("qa-task-pagination")

        self.page.mcp.call(
            "browser_select_option",
            {"target": "select[aria-label='按平台筛选']", "values": ["kuaishou_juxing"]},
            timeout=60,
        )
        time.sleep(2)
        reset_rows = self.rows("qa-tc-reset-rows")
        self.check(
            "QAR-TC-06",
            len(reset_rows) == 1 and "#b9517e8b" in reset_rows[0],
            "切换平台后 cursor 重置为聚星 1 条",
            "qa-tc-reset-rows",
        )

        self.page.mcp.call(
            "browser_select_option",
            {"target": "select[aria-label='按状态筛选']", "values": ["COMPLETED"]},
            timeout=60,
        )
        time.sleep(2)
        completed_rows = self.rows("qa-tc-completed-rows")
        self.check(
            "QAR-TC-07",
            bool(completed_rows) and all("已完成" in row for row in completed_rows),
            f"平台+状态组合筛选（聚星+已完成）行数={len(completed_rows)}",
            "qa-tc-completed-rows",
        )

        self.mcp.call_text("browser_navigate", {"url": f"{BASE}/tasks"}, timeout=120)
        self.page.wait_text("任务中心", tries=40)
        self._set_input("input[aria-label='创建开始日期']", "2026-12-31", "qa-date-from")
        time.sleep(2)
        future_text = self.page.extract("qa-tc-future")["text"]
        self.check(
            "QAR-TC-08",
            "没有匹配的任务" in future_text,
            "平台/日期组合筛选生效（未来日期空态）",
            "qa-tc-future",
        )

        self.mcp.call_text("browser_navigate", {"url": f"{BASE}/tasks"}, timeout=120)
        self.page.wait_text("任务中心", tries=40)
        self.page.mcp.call(
            "browser_select_option",
            {"target": "select[aria-label='按平台筛选']", "values": ["kuaishou_juxing"]},
            timeout=60,
        )
        time.sleep(1)
        self.mcp.call_text("browser_navigate", {"url": f"{BASE}/tasks"}, timeout=120)
        reloaded = self.page.wait_text("任务中心", tries=40)
        refresh_text = self.page.extract("qa-tc-refresh")["text"]
        self.check(
            "QAR-TC-09",
            reloaded and "母婴" in refresh_text and "宠物" in refresh_text,
            "刷新后页面恢复、筛选重置为全部平台、数据完整",
            "qa-tc-refresh",
        )

    # -- task detail ----------------------------------------------------------------------
    def task_details(self) -> None:
        cases = [
            (
                "QAR-TD-01",
                JUXING_TASK,
                ["磁力聚星", "母婴亲子", "有效入库 1", "资料完整 1", "已完成"],
                ["精选"],
            ),
            ("QAR-TD-02", XINGTU_TASK, ["巨量星图", "宠物", "有效入库 1", "精选"], []),
            ("QAR-TD-03", HISTORICAL_TASK, ["部分完成", "4"], []),
        ]
        for case, task_id, needles, forbidden in cases:
            self.mcp.call_text("browser_navigate", {"url": f"{BASE}/tasks/{task_id}"}, timeout=120)
            self.page.wait_text(task_id[:8], tries=40)
            time.sleep(2)
            text = self.page.extract(f"qa-detail-{task_id[:8]}")["text"]
            ok = all(needle in text for needle in needles) and not any(
                item in text for item in forbidden
            )
            self.check(case, ok, f"{task_id[:8]} 详情校验", f"qa-detail-{task_id[:8]}")
            self.shot(f"qa-detail-{task_id[:8]}")

        failed = self.api("/api/tasks?limit=100&status=FAILED", "qa-failed-list") or {}
        failed_id = next(
            (
                item.get("root_task_id")
                for item in failed.get("items", [])
                if item.get("root_task_id")
            ),
            None,
        )
        if failed_id:
            self.mcp.call_text(
                "browser_navigate", {"url": f"{BASE}/tasks/{failed_id}"}, timeout=120
            )
            self.page.wait_text(failed_id[:8], tries=40)
            time.sleep(2)
            text = self.page.extract("qa-detail-failed")["text"]
            self.check(
                "QAR-TD-04",
                "执行失败" in text,
                f"失败任务 {failed_id[:8]} 详情显示失败状态/原因",
                "qa-detail-failed",
            )
            self.shot("qa-detail-failed")

    # -- creator library ------------------------------------------------------------------
    def libraries(self) -> None:
        self.mcp.call_text(
            "browser_navigate", {"url": f"{BASE}/creators?platform=douyin_xingtu"}, timeout=120
        )
        self.page.wait_text("巨量星图达人", tries=40)
        time.sleep(2)
        xingtu_text = self.page.extract("qa-lib-xingtu")["text"]
        xingtu_api = self.api(
            "/api/creator-library?platform=douyin_xingtu&limit=1", "qa-lib-xingtu-api"
        )
        self.check(
            "QAR-LIB-01",
            "巨量星图达人" in xingtu_text
            and "位已加载" in xingtu_text
            and bool(xingtu_api)
            and len(xingtu_api.get("items", [])) >= 1,
            "星图达人库可读",
            "qa-lib-xingtu",
        )
        self.shot("qa-lib-xingtu")

        self.page.mcp.call(
            "browser_select_option",
            {"target": "select[aria-label='达人库平台']", "values": ["kuaishou_juxing"]},
            timeout=60,
        )
        self.page.wait_text("磁力聚星达人", tries=40)
        time.sleep(2)
        juxing_text = self.page.extract("qa-lib-juxing")["text"]
        self.check(
            "QAR-LIB-02",
            "磁力聚星达人" in juxing_text and "1 位已加载" in juxing_text,
            "聚星达人库可读（1 位）",
            "qa-lib-juxing",
        )
        self.check(
            "QAR-LIB-03",
            "巨量星图达人" not in juxing_text and "磁力聚星达人" in juxing_text,
            "平台切换后列表/文案切换",
            "qa-lib-juxing",
        )
        self.shot("qa-lib-juxing")

        self.mcp.call(
            "browser_type",
            {"target": "input[aria-label='按省份筛选']", "text": "北京市"},
            timeout=60,
        )
        time.sleep(2)
        empty_text = self.page.extract("qa-lib-empty")["text"]
        self.check(
            "QAR-LIB-07",
            "暂无匹配达人" in empty_text,
            "聚星库无结果时显示空态",
            "qa-lib-empty",
        )
        self.shot("qa-lib-empty")
        self._set_input("input[aria-label='按省份筛选']", "山东", "qa-lib-province")
        time.sleep(2)
        shandong_text = self.page.extract("qa-lib-shandong")["text"]
        self.check(
            "QAR-LIB-06",
            "贝贝家母婴用品" in shandong_text and "1 位已加载" in shandong_text,
            "聚星省份筛选（山东）命中 1 位",
            "qa-lib-shandong",
        )
        self._set_input("input[aria-label='按省份筛选']", "", "qa-lib-province-clear")
        time.sleep(2)

        links_js = (
            "() => [...document.querySelectorAll('a.library-row')].map(a => a.getAttribute('href'))"
        )
        links = self.ev(links_js, "qa-lib-links")
        if links:
            self.mcp.call_text("browser_navigate", {"url": BASE + links[0]}, timeout=120)
            self.page.wait_text("基础资料", tries=40)
            time.sleep(2)
            detail_text = self.page.extract("qa-lib-juxing-detail")["text"]
            self.check(
                "QAR-LIB-04",
                all(x in detail_text for x in ("基础资料", "传播表现", "代表作品", "受众画像"))
                and "快手ID" in detail_text
                and "手动更新" not in detail_text
                and "报价与历史" not in detail_text,
                "聚星达人详情四章节/无星图专属操作",
                "qa-lib-juxing-detail",
            )
            self.shot("qa-lib-juxing-detail")

        self.mcp.call_text(
            "browser_navigate", {"url": f"{BASE}/creators?platform=douyin_xingtu"}, timeout=120
        )
        self.page.wait_text("巨量星图达人", tries=40)
        time.sleep(2)
        links = self.ev(links_js, "qa-lib-xingtu-links")
        if links:
            self.mcp.call_text("browser_navigate", {"url": BASE + links[0]}, timeout=120)
            self.page.wait_text("商业能力", tries=40)
            time.sleep(2)
            detail_text = self.page.extract("qa-lib-xingtu-detail")["text"]
            self.check(
                "QAR-LIB-05",
                all(x in detail_text for x in ("商业能力", "创作能力", "履约能力", "连接用户"))
                and ("优秀传播视频" in detail_text or "优秀种草视频" in detail_text),
                "星图达人详情/F06 保留",
                "qa-lib-xingtu-detail",
            )
            self.shot("qa-lib-xingtu-detail")

        # Consistency: task-internal creator names vs library names.
        self.mcp.call_text("browser_navigate", {"url": f"{BASE}/tasks/{JUXING_TASK}"}, timeout=120)
        self.page.wait_text("贝贝家母婴用品", tries=40)
        task_text = self.page.extract("qa-juxing-task-consistency")["text"]
        self.mcp.call_text(
            "browser_navigate", {"url": f"{BASE}/creators?platform=kuaishou_juxing"}, timeout=120
        )
        self.page.wait_text("贝贝家母婴用品", tries=40)
        library_text = self.page.extract("qa-juxing-library-consistency")["text"]
        self.check(
            "QAR-LIB-08",
            "贝贝家母婴用品" in task_text and "贝贝家母婴用品" in library_text,
            "聚星任务内达人与达人库一致",
            "qa-juxing-task-consistency",
        )

    def units(self) -> None:
        self.mcp.call_text("browser_navigate", {"url": f"{BASE}/execution-units"}, timeout=120)
        self.page.wait_text("执行单元管理", tries=40)
        time.sleep(2)
        text = self.page.extract("qa-units")["text"]
        self.check(
            "QAR-EU-01",
            "unit-local-mac-02" in text and "巨量星图" in text and "磁力聚星" in text,
            "执行单元页显示同一单元双平台",
            "qa-units",
        )
        self.check(
            "QAR-EU-02",
            "ONLINE" in text and "空闲可用" in text,
            "执行单元 ONLINE/空闲、无当前任务",
            "qa-units",
        )
        self.shot("qa-units")

    # -- console / network ----------------------------------------------------------------
    def observability(self) -> None:
        try:
            console = self.mcp.call_text(
                "browser_console_messages", {"level": "error", "all": True}, timeout=60
            )
        except Exception as exc:  # noqa: BLE001
            console = f"CONSOLE_UNAVAILABLE: {type(exc).__name__}"
        (self.out / "console-errors.txt").write_text(console)
        error_lines = [
            line
            for line in console.splitlines()
            if line.startswith("[ERROR]") or line.startswith("[WARNING]")
        ]
        relevant = [
            line
            for line in error_lines
            if "401" not in line and "Failed to load resource" not in line and "favicon" not in line
        ]
        self.check(
            "QAR-UI-05",
            not relevant,
            f"登录后 console 相关错误数={len(relevant)}",
            "console-errors",
        )
        try:
            network = self.mcp.call_text(
                "browser_network_requests", {"filter": "/api/"}, timeout=60
            )
        except Exception as exc:  # noqa: BLE001
            network = f"NETWORK_UNAVAILABLE: {type(exc).__name__}"
        (self.out / "network-api.txt").write_text(network)
        bad = [line for line in network.splitlines() if re.search(r"\s5\d\d\b", line)]
        self.check(
            "QAR-UI-06",
            not bad,
            f"API 请求无 5xx（检测到 {len(bad)}）",
            "network-api",
        )

    def run(self) -> None:
        try:
            self.login()
            self.navigation()
            self.forms()
            self.task_center()
            self.task_details()
            self.libraries()
            self.units()
            self.observability()
        finally:
            report = {
                "schema_version": "juxing_main_qa.v1",
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "cases": self.book.cases,
            }
            (self.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            self.mcp.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    driver = Driver(args.out, headless=not args.headed)
    try:
        driver.run()
    except Exception as exc:  # noqa: BLE001
        print(f"DRIVER_ERROR: {type(exc).__name__}: {exc}", flush=True)
        return 1
    failed = [c for c in driver.book.cases if c["status"] == "FAIL"]
    print(f"cases={len(driver.book.cases)} failed={len(failed)}", flush=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
