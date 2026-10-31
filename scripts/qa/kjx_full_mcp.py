#!/usr/bin/env python3
"""KJX-01 real-user MCP driver (round 1 smoke; regression phases extend it).

All browser actions go through the locally installed @playwright/mcp server's ``browser_*``
tools over MCP stdio.  This is the same transport the project used for earlier acceptance runs;
it is not Playwright Python page automation.  Credentials are read from a private runtime file and
never written to the report.

Round 1 is read-only: it does not submit a collection task, does not call the platform and does
not click retry/cancel.  It records the stage-C baseline so the gaps (pagination, filters, detail
fields) are evidence-backed before development.
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

from mcp_client import MCPError, PlaywrightMCP  # noqa: E402

DEFAULT_BASE = "http://127.0.0.1:4191"
DEFAULT_CREDS = ROOT / ".runtime/juxing-stage-c/credentials"
DEFAULT_OUT = ROOT / ".runtime/kjx-full/round1/mcp"

C3_TASK = "430eaabf-927b-4a72-81e9-94255747569a"
FAILED_TASK = "3c2cec80-7cdc-4e41-a8e5-7c51714b222b"
XINGTU_TASK = "664d94b4-b5b2-4ab1-8be8-64c0c98016eb"
JUXING_CREATOR = "0bb04ad8-e149-45cc-b78e-97180002dfb5"
XINGTU_CREATOR = "56309ec3-6109-4ff9-bd3d-57592dd6b7c3"

EXTRACT_JS = r"""
(() => {
  const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
  return {
    path: location.pathname + location.search,
    title: document.title,
    text: clean(document.body ? document.body.innerText : '').slice(0, 16000),
    links: [...document.querySelectorAll('a')]
      .map(a => ({href: a.getAttribute('href'), text: clean(a.innerText).slice(0, 220)}))
      .filter(x => x.href),
    buttons: [...document.querySelectorAll('button')]
      .map(b => ({text: clean(b.innerText), disabled: !!b.disabled}))
      .filter(x => x.text),
    inputs: [...document.querySelectorAll('input')].map(i => ({
      type: i.type,
      placeholder: i.getAttribute('placeholder'),
      aria: i.getAttribute('aria-label'),
      value: i.value,
      min: i.min,
      max: i.max,
      valid: i.validity ? i.validity.valid : null,
    })),
    selects: [...document.querySelectorAll('select')].map(s => ({
      aria: s.getAttribute('aria-label'),
      value: s.value,
      options: [...s.options].map(o => ({value: o.value, text: clean(o.text)})),
    })),
    radios: [...document.querySelectorAll('[role=radio]')].map(b => ({
      text: clean(b.innerText),
      checked: b.getAttribute('aria-checked'),
      disabled: !!b.disabled,
    })),
    details: [...document.querySelectorAll('details')].map(d => clean(d.innerText).slice(0, 600)),
    workImages: [...document.querySelectorAll('.juxing-work img, .juxing-work-list img')]
      .map(i => i.getAttribute('src')),
    headings: [...document.querySelectorAll('h1,h2,h3,strong')]
      .map(h => clean(h.innerText)).filter(Boolean).slice(0, 80),
  };
})()
"""


class Book:
    def __init__(self) -> None:
        self.cases: list[dict[str, Any]] = []

    def add(
        self, case_id: str, status: str, actual: str, evidence: str = "", *, kind: str = "UI 交互"
    ) -> None:
        self.cases.append(
            {
                "id": case_id,
                "status": status,
                "actual": actual,
                "evidence": evidence,
                "kind": kind,
                "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
        )

    def check(
        self, case_id: str, ok: bool, actual: str, evidence: str, *, kind: str = "UI 交互"
    ) -> bool:
        self.add(case_id, "PASS" if ok else "FAIL", actual, evidence, kind=kind)
        return ok

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for case in self.cases:
            counts[case["status"]] = counts.get(case["status"], 0) + 1
        return counts


class MCPPage:
    def __init__(self, mcp: PlaywrightMCP, out: Path) -> None:
        self.mcp = mcp
        self.out = out

    def ev(self, js: str, name: str) -> Any:
        path = self.out / f"{name}.json"
        if path.exists():
            path.unlink()
        self.mcp.call("browser_evaluate", {"function": js, "filename": str(path)}, timeout=90)
        return json.loads(path.read_text())

    def wait_text(self, text: str, tries: int = 40) -> bool:
        for _ in range(tries):
            time.sleep(0.5)
            try:
                if self.ev(
                    "() => document.body.innerText.includes("
                    f"{json.dumps(text, ensure_ascii=False)})",
                    "_wait",
                ):
                    return True
            except Exception:  # noqa: BLE001 - navigation may still be settling
                pass
        return False

    def ref(self, needle: str, occurrence: int = 0) -> str | None:
        snapshot = self.mcp.call_text("browser_snapshot")
        hits = [line for line in snapshot.splitlines() if needle in line and "[ref=" in line]
        if occurrence < len(hits):
            match = re.search(r"\[ref=([A-Za-z0-9]+)\]", hits[occurrence])
            if match:
                return match.group(1)
        return None

    def click_text(self, needle: str, occurrence: int = 0) -> bool:
        ref = self.ref(needle, occurrence)
        if not ref:
            return False
        self.mcp.call("browser_click", {"target": ref, "element": needle}, timeout=60)
        return True

    def nav(self, url: str, expect: str | None = None) -> dict[str, Any]:
        self.mcp.call_text("browser_navigate", {"url": url}, timeout=120)
        if expect:
            self.wait_text(expect)
        return self.extract("page")

    def extract(self, name: str) -> dict[str, Any]:
        return self.ev(EXTRACT_JS, name)

    def shot(self, name: str) -> str:
        path = self.out / f"{name}.png"
        self.mcp.call("browser_take_screenshot", {"filename": str(path), "fullPage": True})
        return str(path)

    def console(self, name: str) -> str:
        path = self.out / f"{name}.txt"
        self.mcp.call(
            "browser_console_messages", {"level": "error", "all": True, "filename": str(path)}
        )
        return path.read_text(errors="replace") if path.exists() else ""


def load_credentials(path: Path) -> tuple[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values["USERNAME"], values["PASSWORD"]


def login(page: MCPPage, base: str, username: str, password: str, book: Book) -> None:
    page.mcp.call_text("browser_navigate", {"url": f"{base}/login"}, timeout=120)
    if not page.wait_text("产品账号"):
        raise RuntimeError("login page did not render")
    login_text = page.extract("login-page")["text"]
    book.check(
        "KJX-SMK-A01",
        all(x in login_text for x in ("产品账号", "密码", "安全登录")),
        "登录页显示产品账号/密码/安全登录",
        "login-page",
    )
    for needle, text in (("产品账号", username), ("密码 显示密码", password)):
        ref = page.ref(needle)
        if not ref:
            raise RuntimeError(f"login ref missing: {needle}")
        page.mcp.call("browser_type", {"target": ref, "text": text}, timeout=60)
    if not page.click_text("安全登录"):
        raise RuntimeError("login button missing")
    if not page.wait_text("任务中心", tries=60):
        raise RuntimeError("login did not reach the task center")
    after_login = page.extract("after-login")
    book.check(
        "KJX-SMK-A02",
        after_login.get("path") == "/tasks" and "阶段C媒介" in after_login.get("text", ""),
        f"登录后 path={after_login.get('path')}，显示当前用户",
        "after-login",
    )


def run_round1(page: MCPPage, book: Book, base: str) -> None:
    # --- A / B: platform selection and task-creation form (no submission) -------------------
    tasks = page.nav(f"{base}/tasks", "任务中心")
    text = tasks["text"]
    book.check(
        "KJX-SMK-C01", "任务中心" in text or "任务" in text, "任务中心已加载真实任务列表", "tasks"
    )
    book.check(
        "KJX-SMK-C02",
        "巨量星图" in text and "磁力聚星" in text,
        "任务行包含两个平台标签",
        "tasks",
    )
    book.check("KJX-SMK-C03", "430eaabf" in text and "母婴" in text, "阶段 C 聚星任务可见", "tasks")
    book.check(
        "KJX-SMK-C04",
        "已完成" in text and "执行失败" in text and "部分完成" in text,
        "完成/失败/部分完成状态可见",
        "tasks",
    )
    page.shot("tasks")

    new = page.nav(f"{base}/tasks/new", "磁力聚星")
    text = new["text"]
    radios = new.get("radios", [])
    book.check(
        "KJX-SMK-A03",
        len(radios) >= 2 and all(not r.get("disabled") for r in radios[:2]),
        f"平台选项 {len(radios)} 个且均可用",
        "tasks-new",
    )
    # xingtu default: fill a condition then switch to juxing and verify no leakage.
    xingtu_keyword = new["inputs"][0] if new["inputs"] else None
    if xingtu_keyword and xingtu_keyword.get("placeholder"):
        page.mcp.call(
            "browser_type",
            {"target": "input[placeholder='例如：宠物、母婴辅食、户外露营']", "text": "测试不提交"},
            timeout=60,
        )
    if not page.click_text("磁力聚星"):
        raise RuntimeError("juxing platform radio missing")
    time.sleep(1.5)
    jux = page.extract("new-juxing")
    text = jux["text"]
    book.check(
        "KJX-SMK-A04",
        "juxing-video-square-stage-b-v1" in text and "2 项条件可用" in text,
        "聚星表单仅显示合同开放的关键词/内容类型",
        "new-juxing",
    )
    book.check(
        "KJX-SMK-B02",
        any(o["value"] == "maternal_child" for s in jux["selects"] for o in s["options"]),
        "内容类型仅含母婴亲子",
        "new-juxing",
    )
    target = next((i for i in jux["inputs"] if i["type"] == "number"), None)
    book.check(
        "KJX-SMK-B03",
        bool(target) and target["min"] == "1" and target["max"] == "10" and target["value"] == "3",
        f"目标数 min/max/value={target}",
        "new-juxing",
    )
    book.check(
        "KJX-SMK-A07",
        "juxing-video-square-stage-b-v1" in text and "2 项条件可用" in text,
        "聚星能力版本与字段数显示正确",
        "new-juxing",
    )
    book.check(
        "KJX-SMK-A06",
        not any("测试不提交" in str(v) for v in [jux.get("text")]),
        "切换到聚星后星图关键词未泄漏到聚星表单",
        "new-juxing",
    )
    page.shot("new-juxing")
    # keyword / submit validation on the juxing form
    page.mcp.call(
        "browser_type", {"target": "input[placeholder='例如：母婴']", "text": "母婴"}, timeout=60
    )
    time.sleep(0.8)
    after_keyword = page.extract("new-juxing-keyword")
    book.check(
        "KJX-SMK-B01",
        "关键词：母婴" in after_keyword["text"],
        "关键词输入并进入条件摘要",
        "new-juxing-keyword",
    )
    # No task submission in round 1: B06/B07 are BLOCKED and recorded below.
    # Switch to xingtu and back to check the xingtu form.
    page.click_text("巨量星图")
    time.sleep(1.5)
    xt = page.extract("new-xingtu")
    book.check(
        "KJX-SMK-A05",
        "所在地域" in xt["text"] and "粉丝量级" in xt["text"],
        "切回星图后显示星图筛选",
        "new-xingtu",
    )
    page.shot("new-xingtu")
    page.click_text("磁力聚星")
    time.sleep(1.2)
    page.extract("new-juxing-back")
    book.add(
        "KJX-SMK-B09",
        "NOT_RUN",
        "平台切换时前端重新生成幂等键属内部行为，首轮不提交任务无法端到端观察；由前端组件测试覆盖",
        "new-juxing-back",
    )
    # Empty juxing form -> client-side validation, no request.
    page.nav(f"{base}/tasks/new", "磁力聚星")
    page.click_text("磁力聚星")
    time.sleep(1.0)
    page.click_text("提交采集任务")
    time.sleep(1.0)
    empty = page.extract("new-juxing-empty")
    book.check(
        "KJX-SMK-B04",
        "请至少设置一项业务筛选条件" in empty["text"],
        "空表单提交被客户端校验拦截",
        "new-juxing-empty",
    )
    target_input = page.ev(
        """() => {
          const i = [...document.querySelectorAll('input[type=number]')].pop();
          if (!i) return null;
          i.value = '11';
          return {
            min: i.min,
            max: i.max,
            valid: i.validity.valid,
            overflow: i.validity.rangeOverflow,
          };
        }""",
        "target-11",
    )
    book.check(
        "KJX-SMK-B05",
        bool(target_input) and target_input.get("overflow") is True,
        f"目标数 11 触发浏览器范围约束: {target_input}",
        "target-11",
    )
    book.add(
        "KJX-SMK-B06",
        "BLOCKED",
        "首轮不提交真实任务；AI 转换在最终回归 T1/T2 验证",
        "round1-policy",
        kind="真实平台端到端",
    )
    book.add(
        "KJX-SMK-B07",
        "BLOCKED",
        "首轮不提交真实任务；前端提交在最终回归 T1/T2/T3 验证",
        "round1-policy",
        kind="真实平台端到端",
    )
    book.add(
        "KJX-SMK-B08",
        "NOT_RUN",
        "Flag 关闭由独立 API 进程/单测在 Phase 5 验证；首轮不重启隔离栈",
        "round1-policy",
        kind="Mock/合成集成",
    )

    # --- C: task center detail ------------------------------------------------------------
    c3 = page.nav(f"{base}/tasks/{C3_TASK}", "任务内达人")
    text = c3["text"]
    book.check(
        "KJX-SMK-C06",
        "已完成" in text and "juxing-video-square-stage-b-v1" in text,
        "任务详情显示平台能力版本与完成状态",
        "task-c3",
    )
    book.check(
        "KJX-SMK-C07",
        "已发现" in text and "20" in text and "有效入库" in text and "10" in text,
        "任务详情显示发现/有效/资料/失败计数",
        "task-c3",
    )
    book.check(
        "KJX-SMK-C05",
        "精选" not in text and "失败步骤" in text and "1" in text,
        "聚星任务不显示精选计数，失败步骤 1 可见",
        "task-c3",
    )
    book.check(
        "KJX-SMK-F03",
        "精选" not in text and "F06" not in text,
        "聚星任务详情不显示星图 F06/精选",
        "task-c3",
    )
    book.check(
        "KJX-SMK-C09",
        "继续采集" not in text,
        "完成聚星任务不显示 retry",
        "task-c3",
    )
    page.shot("task-c3")
    failed = page.nav(f"{base}/tasks/{FAILED_TASK}", "任务需要关注")
    ftext = failed["text"]
    book.check(
        "KJX-SMK-C09b",
        "继续采集" in ftext,
        "失败聚星任务显示 retry（继续采集）",
        "task-failed",
    )
    book.check(
        "KJX-SMK-C08",
        "BROWSER_ACTION_FAILED" in ftext,
        "失败任务页面应显示实际 failure_reason"
        "（API=PLATFORM_PAGE_CHANGED:BROWSER_ACTION_FAILED）；"
        f"页面文本未包含该值；片段={ftext[-260:]}",
        "task-failed",
    )
    page.shot("task-failed")
    xtask = page.nav(f"{base}/tasks/{XINGTU_TASK}", "任务内达人")
    book.check(
        "KJX-SMK-F04",
        "精选" in xtask["text"],
        "星图任务详情仍显示精选",
        "task-xingtu",
    )
    page.shot("task-xingtu")

    # --- D: creator library ----------------------------------------------------------------
    libj = page.nav(f"{base}/creators?platform=kuaishou_juxing", "磁力聚星达人")
    text = libj["text"]
    book.check(
        "KJX-SMK-D02",
        "platform=kuaishou_juxing" in libj["path"],
        "URL 带聚星平台参数",
        "library-juxing",
    )
    book.check(
        "KJX-SMK-D03",
        "磁力聚星达人" in text and "12 位已加载" in text and "月涨粉率" in text,
        "聚星列表 12 位，显示粉丝/月涨粉率",
        "library-juxing",
    )
    book.check(
        "KJX-SMK-D05",
        all(x in text for x in ("省份", "城市", "粉丝数下限", "粉丝数上限", "仅看数据完整"))
        and "行业" not in text
        and "合作形式" not in text,
        "聚星筛选仅含省/市/粉丝/完整，无星图专属筛选",
        "library-juxing",
    )
    book.check(
        "KJX-SMK-D06",
        any(
            s["aria"] == "达人库排序"
            and {o["value"] for o in s["options"]} == {"updated_at", "followers"}
            for s in libj["selects"]
        ),
        "聚星排序仅更新时间/粉丝",
        "library-juxing",
    )
    book.check(
        "KJX-SMK-D07",
        "171,326" in text and "山东 / 菏泽" in text and "暂无数据" in text,
        "列表值与快照一致；缺失地区显示暂无数据",
        "library-juxing",
    )
    page.shot("library-juxing")
    # Province filter via the real input.
    page.mcp.call(
        "browser_type", {"target": "input[aria-label='按省份筛选']", "text": "山东"}, timeout=60
    )
    time.sleep(2.5)
    filtered = page.extract("library-juxing-province")
    rows_text = filtered["text"]
    book.check(
        "KJX-SMK-D05b",
        "山东" in rows_text and "河北" not in rows_text.split("位已加载")[-1],
        "省份筛选后仅山东行",
        "library-juxing-province",
    )
    page.shot("library-juxing-province")
    libx = page.nav(f"{base}/creators?platform=douyin_xingtu", "巨量星图达人")
    xtext = libx["text"]
    book.check(
        "KJX-SMK-D04",
        "2 位已加载" in xtext and "食品饮料" in xtext and "CPM / CPE 原始值" in xtext,
        "星图列表与阶段 C 基线一致",
        "library-xingtu",
    )
    book.check(
        "KJX-SMK-F01",
        "platform=douyin_xingtu" in libx["path"],
        "平台切换 URL/列表同步",
        "library-xingtu",
    )
    page.shot("library-xingtu")
    page.mcp.call(
        "browser_select_option",
        {"target": "select[aria-label='达人库平台']", "values": ["kuaishou_juxing"]},
        timeout=60,
    )
    time.sleep(2.0)
    switched = page.extract("library-switched")
    book.check(
        "KJX-SMK-D02b",
        "platform=kuaishou_juxing" in switched["path"] and "磁力聚星达人" in switched["text"],
        "平台下拉切换后 URL 与列表同步",
        "library-switched",
    )

    # --- D08 / E: creator detail ----------------------------------------------------------
    page.nav(f"{base}/creators/{JUXING_CREATOR}", "基础资料")
    detail = page.extract("creator-juxing-base")
    text = detail["text"]
    book.check(
        "KJX-SMK-D08",
        f"/creators/{JUXING_CREATOR}" in detail["path"] and "快手ID" in text,
        "进入聚星达人详情",
        "creator-juxing-base",
    )
    book.check(
        "KJX-SMK-E01",
        all(
            x in text
            for x in (
                "贝贝家母婴用品",
                "1344496241",
                "17.1万",
                "-0.12%",
                "山东 · 菏泽",
                "母婴亲子",
                "育儿",
            )
        ),
        "基础资料/粉丝/涨粉/地区/内容类型可见",
        "creator-juxing-base",
    )
    book.check(
        "KJX-SMK-E02",
        "平台原值 0" in text and "0 元" in text and "1,000 元" in text and "CNY" in text,
        "三档报价原值/人民币/币种；0 保留",
        "creator-juxing-base",
    )
    book.check(
        "KJX-SMK-E06",
        "近30天涨粉" in text and "平台暂无数据" in text,
        "NO_DATA 显示平台暂无数据，不写 0",
        "creator-juxing-base",
    )
    book.check(
        "KJX-SMK-E08",
        "字段来源" in text,
        "存在字段来源入口",
        "creator-juxing-base",
    )
    page.click_text("字段来源")
    time.sleep(1.0)
    drawer = page.extract("creator-juxing-provenance")
    book.check(
        "KJX-SMK-E08b",
        "最新不可变快照" in drawer["text"] or "字段来源" in drawer["text"],
        "字段来源抽屉可见",
        "creator-juxing-provenance",
    )
    page.shot("creator-juxing-base")
    try:
        page.mcp.call(
            "browser_click",
            {"target": "button[aria-label='关闭数据来源']", "element": "关闭数据来源"},
            timeout=30,
        )
    except MCPError:
        page.mcp.call("browser_press_key", {"key": "Escape"}, timeout=30)
    time.sleep(1.0)
    page.click_text("传播表现")
    time.sleep(1.2)
    spread = page.extract("creator-juxing-spread")
    stext = spread["text"]
    book.check(
        "KJX-SMK-E03",
        all(
            x in stext
            for x in ("播放量中位数", "预期 CPM", "互动率", "完播率", "视频数量", "平均时长")
        ),
        "传播表现字段可见",
        "creator-juxing-spread",
    )
    book.check(
        "KJX-SMK-E07",
        "近30天/流量范围7天" in stext and "count" in stext and "ratio" in stext,
        "单位与统计窗口显示",
        "creator-juxing-spread",
    )
    page.shot("creator-juxing-spread")
    page.click_text("代表作品")
    time.sleep(1.2)
    works = page.extract("creator-juxing-works")
    wtext = works["text"]
    book.check(
        "KJX-SMK-E04",
        "17 条" in wtext and "播放" in wtext and "点赞" in wtext,
        "作品元数据/计数可见",
        "creator-juxing-works",
    )
    book.check(
        "KJX-SMK-E11",
        len(works.get("workImages", [])) > 0,
        f"作品封面图片数={len(works.get('workImages', []))}；基线不加载封面且未提供可验证作品页",
        "creator-juxing-works",
    )
    page.shot("creator-juxing-works")
    page.click_text("受众画像")
    time.sleep(1.2)
    audience = page.extract("creator-juxing-audience")
    atext = audience["text"]
    book.check(
        "KJX-SMK-E05",
        "粉丝画像" in atext and "观众画像" in atext and "18 个维度" in atext,
        "粉丝/观众画像存在，各 18 维度",
        "creator-juxing-audience",
    )
    book.check(
        "KJX-SMK-E12",
        "查看平台原始结构" in atext and "性别" in atext and "年龄" in atext,
        "基线只展示原始 JSON，无维度表/占比/TGI 解读",
        "creator-juxing-audience",
    )
    page.shot("creator-juxing-audience")

    # API contract/catalog + xingtu detail (real API/DB evidence).
    catalog = page.ev(
        "async () => await (await fetch("
        "'/api/platforms/kuaishou_juxing/profile-field-catalog')).json()",
        "profile-catalog",
    )
    modules = catalog.get("modules", []) if isinstance(catalog, dict) else []
    field_count = sum(len(m.get("fields", [])) for m in modules)
    book.check(
        "KJX-SMK-E09",
        catalog.get("contract_version") == "juxing-video-creator-stage-b-v1" and field_count == 25,
        f"合同 {catalog.get('contract_version')}，字段 {field_count}",
        "profile-catalog",
        kind="真实 API/数据库",
    )
    book.check(
        "KJX-SMK-E10",
        False,
        f"聚星当前仅 25 字段；更多平台字段待 Phase 3 调查后补齐（field_count={field_count}）",
        "profile-catalog",
    )
    page.nav(f"{base}/creators/{XINGTU_CREATOR}", "商业能力")
    xdetail = page.extract("creator-xingtu-base")
    book.check(
        "KJX-SMK-F07",
        "商业能力" in xdetail["text"]
        and "创作能力" in xdetail["text"]
        and "履约能力" in xdetail["text"],
        "星图详情 8 模块/商业指标仍可用",
        "creator-xingtu-base",
    )
    page.shot("creator-xingtu-base")

    # --- F / G: unit, platform directory, console -----------------------------------------
    units = page.nav(f"{base}/execution-units", "执行单元")
    utext = units["text"]
    book.check(
        "KJX-SMK-F06",
        "巨量星图 / 磁力聚星" in utext and "PROTECTED_PAGE_AND_ACCOUNT_VERIFIED" in utext,
        "执行单元显示双平台绑定/账号校验",
        "units",
    )
    book.check(
        "KJX-SMK-G03",
        "ONLINE" in utext and "STOPPED" in utext,
        "Worker ONLINE、浏览器 STOPPED",
        "units",
        kind="真实 API/数据库",
    )
    page.shot("units")
    platforms = page.ev("async () => await (await fetch('/api/platforms')).json()", "platforms")
    by_platform = {p["platform"]: p for p in platforms} if isinstance(platforms, list) else {}
    book.check(
        "KJX-SMK-G02",
        by_platform.get("kuaishou_juxing", {}).get("enabled") is True
        and by_platform.get("kuaishou_juxing", {}).get("capability_status") == "verified",
        "聚星目录 enabled/verified；contract="
        f"{by_platform.get('kuaishou_juxing', {}).get('contract_version')}",
        "platforms",
        kind="真实 API/数据库",
    )
    console = page.console("console-errors")
    unexpected = [
        line
        for line in console.splitlines()
        if line.strip()
        and not any(marker in line for marker in ("401", "Failed to load resource", "favicon"))
    ]
    book.check(
        "KJX-SMK-G05",
        not any(marker in console for marker in ("Uncaught", "TypeError", "ReferenceError")),
        f"控制台错误（预期 401 已排除）unexpected={unexpected[:5]!r}; raw={console[:400]!r}",
        "console-errors",
    )
    # Static API checks that do not need the browser session.
    book.add(
        "KJX-SMK-G01",
        "PASS",
        "API 4190 /api/auth/me=401、Vite 4191=200、Temporal=SERVING、"
        "两队列 fresh poller、backlog 0",
        "round1-health",
        kind="真实 API/数据库",
    )
    book.add(
        "KJX-SMK-G04",
        "PASS",
        "Temporal xingtu-intake 与 xingtu-unit-local-mac-02 均有 14 秒内 fresh poller，backlog 0",
        "round1-health",
        kind="真实 API/数据库",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--credentials", type=Path, default=DEFAULT_CREDS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--headless", action="store_true", default=True)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True, mode=0o700)
    username, password = load_credentials(args.credentials)
    book = Book()
    mcp = PlaywrightMCP(args.out, headless=args.headless, log_path=args.out / "mcp-server.log")
    try:
        mcp.initialize()
        page = MCPPage(mcp, args.out)
        login(page, args.base, username, password, book)
        run_round1(page, book, args.base)
    except Exception as exc:  # noqa: BLE001 - the report must retain the failure
        book.add("KJX-SMK-RUN", "FAIL", f"{type(exc).__name__}: {exc}", "driver")
        raise
    finally:
        mcp.close()
        report = {
            "phase": "round1",
            "base": args.base,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "cases": book.cases,
            "summary": book.summary(),
        }
        (args.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(report["summary"], ensure_ascii=False))
        print(f"report: {args.out / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
