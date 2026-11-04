#!/usr/bin/env python3
"""Real-user UI regression for the two dedicated execution units.

Every browser action goes through the project's Playwright MCP stdio client (real Chrome).
The script only reads the UI and submits no task; dynamic routing/concurrency is covered by
``dual_unit_acceptance.py``.  DB is used only to pick one recent completed task per platform.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "qa"))

from juxing_main_mcp import Driver  # noqa: E402

BASE = "http://127.0.0.1:5173"
API = "http://127.0.0.1:8000"


def recent_completed(platform: str) -> str | None:
    dsn = os.environ.get("XINGTU_DATABASE_URL")
    if not dsn:
        return None
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        row = conn.execute(
            """SELECT root_task_id FROM root_tasks
            WHERE platform=%s AND state IN ('COMPLETED','PARTIAL_COMPLETED')
            ORDER BY created_at DESC LIMIT 1""",
            (platform,),
        ).fetchone()
    return str(row["root_task_id"]) if row else None


def rows(page: Any) -> list[str]:
    return page.ev(
        "() => [...document.querySelectorAll('a.task-row')].map(r => r.innerText)",
        "task-rows",
    )


def main() -> int:
    out = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else Path(".runtime/dual-unit-acceptance/regression-ui")
    )
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    checks: list[dict[str, Any]] = []
    shots: list[str] = []

    def check(case: str, ok: bool, detail: str) -> None:
        checks.append({"case": case, "ok": bool(ok), "detail": detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {case}: {detail}", flush=True)

    d = Driver(BASE, out / "mcp", headless=True)
    try:
        # R9-01: unauthenticated API rejects, real login works.
        d.mcp.call_text("browser_navigate", {"url": f"{API}/api/auth/me"}, timeout=120)
        body = d.page.ev("() => document.body.innerText", "unauth-body")
        check(
            "R9-01a",
            "ACCOUNT_LOGIN_REQUIRED" in body,
            f"unauthenticated /api/auth/me body={body[:160]!r}",
        )
        d.login()
        check("R9-01b", True, "real media-a login reached task center")

        # R1: execution units.
        d.mcp.call_text("browser_navigate", {"url": f"{BASE}/execution-units"}, timeout=120)
        time.sleep(2)
        body = d.page.ev("() => document.body.innerText", "units-body")
        units_body = body
        rows_text = d.page.ev(
            "() => [...document.querySelectorAll('.unit-table tbody tr')].map(r => r.innerText)",
            "unit-rows",
        )
        check("R1-01", len(rows_text) == 2, f"unit rows={len(rows_text)}")
        check(
            "R1-01b",
            "unit-local-mac-02" in body
            and "unit-local-mac-03-juxing" in body
            and "巨量星图" in body
            and "磁力聚星" in body,
            "two unit ids and platform labels visible",
        )
        check("R1-01c", body.count("ONLINE") >= 2, f"worker ONLINE count={body.count('ONLINE')}")
        check(
            "R1-03",
            "•••" in body and "—" in body,
            "masked account/line and empty current task visible",
        )
        summary = d.page.ev(
            "() => [...document.querySelectorAll('.unit-summary-grid .panel')].map(p => p.innerText)",
            "unit-summary",
        )
        joined = " | ".join(summary)
        check(
            "R1-02",
            "可用单元" in joined
            and "\n2" in joined
            and "采集中" in joined
            and "待人工验证" in joined,
            f"summary={summary}",
        )
        shots.append(d.shot("01-execution-units"))

        # R2: task center platform filter + details.
        d.mcp.call_text("browser_navigate", {"url": f"{BASE}/tasks"}, timeout=120)
        time.sleep(2)
        options = d.page.ev(
            "() => [...document.querySelectorAll(\"select[aria-label='按平台筛选'] option\")].map(o => o.value)",
            "platform-options",
        )
        check("R2-01", options == ["", "douyin_xingtu", "kuaishou_juxing"], f"options={options}")
        d.mcp.call(
            "browser_select_option",
            {"target": "select[aria-label='按平台筛选']", "values": ["douyin_xingtu"]},
            timeout=60,
        )
        time.sleep(2)
        xrows = rows(d.page)
        check(
            "R2-02a",
            bool(xrows)
            and all("巨量星图" in r for r in xrows)
            and not any("磁力聚星" in r for r in xrows),
            f"xingtu rows={len(xrows)}",
        )
        d.mcp.call(
            "browser_select_option",
            {"target": "select[aria-label='按平台筛选']", "values": ["kuaishou_juxing"]},
            timeout=60,
        )
        time.sleep(2)
        jrows = rows(d.page)
        check(
            "R2-02b",
            bool(jrows)
            and all("磁力聚星" in r for r in jrows)
            and not any("巨量星图" in r for r in jrows),
            f"juxing rows={len(jrows)}",
        )
        shots.append(d.shot("02-task-filter-juxing"))
        d.mcp.call(
            "browser_select_option",
            {"target": "select[aria-label='按平台筛选']", "values": [""]},
            timeout=60,
        )

        xingtu_root = recent_completed("douyin_xingtu")
        juxing_root = recent_completed("kuaishou_juxing")
        check("R2-03a", bool(xingtu_root), f"recent xingtu root={xingtu_root}")
        check("R2-03b", bool(juxing_root), f"recent juxing root={juxing_root}")
        for case, root, platform in (
            ("R2-03", xingtu_root, "巨量星图"),
            ("R2-04", juxing_root, "磁力聚星"),
        ):
            if not root:
                continue
            d.mcp.call_text("browser_navigate", {"url": f"{BASE}/tasks/{root}"}, timeout=120)
            time.sleep(2)
            body = d.page.ev("() => document.body.innerText", f"{case}-body")
            ok = (
                platform in body
                and "已完成" in body
                and "任务内达人" in body
                and "需求与执行约束" in body
            )
            check(case, ok, f"root={root} platform={platform} detail rendered")
            shots.append(d.shot(f"03-{platform}-task-detail"))

        # R3: new task form / platform selector.
        d.mcp.call_text("browser_navigate", {"url": f"{BASE}/tasks/new"}, timeout=120)
        time.sleep(2)
        radios = d.page.ev(
            "() => [...document.querySelectorAll('[role=radio]')].map(b => ({text:b.innerText,disabled:b.disabled,checked:b.getAttribute('aria-checked')}))",
            "platform-radios",
        )
        check(
            "R3-01",
            len(radios) == 2
            and all(not r["disabled"] for r in radios)
            and "巨量星图" in radios[0]["text"]
            and "磁力聚星" in radios[1]["text"],
            f"radios={radios}",
        )
        body = d.page.ev("() => document.body.innerText", "xingtu-form")
        check(
            "R3-02",
            all(x in body for x in ("内容关键词", "背景信息", "受众画像", "目标达人数量"))
            and "内容类型" not in body,
            "xingtu form fields",
        )
        target = d.page.ev(
            "() => { const i=document.querySelector('.number-field input'); return i ? {min:i.min,max:i.max,value:i.value,type:i.type} : null; }",
            "xingtu-target",
        )
        check(
            "R3-04a",
            bool(target)
            and target["type"] == "number"
            and int(target["max"] or 0) >= int(target["value"] or 0) >= int(target["min"] or 0),
            f"xingtu target={target}",
        )
        d.page.click_text("磁力聚星")
        d.page.wait_text("内容类型")
        body = d.page.ev("() => document.body.innerText", "juxing-form")
        check(
            "R3-03",
            "内容类型" in body
            and "目标达人数量" in body
            and not any(x in body for x in ("连接用户数", "学历", "黄v认证", "观众画像")),
            "juxing form shows only juxing fields",
        )
        target_j = d.page.ev(
            "() => { const i=document.querySelector('.number-field input'); return i ? {min:i.min,max:i.max,value:i.value,type:i.type} : null; }",
            "juxing-target",
        )
        check(
            "R3-04b",
            bool(target_j)
            and target_j["type"] == "number"
            and int(target_j["max"] or 0)
            >= int(target_j["value"] or 0)
            >= int(target_j["min"] or 0),
            f"juxing target={target_j}",
        )
        shots.append(d.shot("04-new-task-juxing-form"))

        # R7: creator library and detail for both platforms.
        for case, platform, heading in (
            ("R7-01", "douyin_xingtu", "巨量星图达人"),
            ("R7-02", "kuaishou_juxing", "磁力聚星达人"),
        ):
            d.mcp.call_text(
                "browser_navigate", {"url": f"{BASE}/creators?platform={platform}"}, timeout=120
            )
            time.sleep(2)
            body = d.page.ev("() => document.body.innerText", f"{case}-library")
            check(
                case,
                heading in body and "位已加载" in body and "暂无匹配达人" not in body,
                f"{heading} loaded",
            )
            shots.append(d.shot(f"05-{platform}-library"))
            clicked = d.page.ev(
                "() => { const a=document.querySelector('a.library-row'); if(!a) return false; a.click(); return true; }",
                f"{case}-click",
            )
            if clicked:
                d.page.wait_text("粉丝")
                time.sleep(1)
                detail = d.page.ev("() => document.body.innerText", f"{case}-detail")
                # The detail page uses the platform's own identifier label, not the library
                # heading: Xingtu renders "星图ID", Juxing renders "快手ID"/"快手主页".
                marker = "星图ID" if platform == "douyin_xingtu" else "快手ID"
                check(
                    f"{case}-detail",
                    marker in detail and "粉丝" in detail and "当前达人资料" in detail,
                    f"creator detail rendered ({marker})",
                )
            else:
                check(f"{case}-detail", False, "no library row to click")

        # R9-02: the execution-units page already proves both registered units/platforms.
        check(
            "R9-02",
            "unit-local-mac-02" in units_body and "unit-local-mac-03-juxing" in units_body,
            "execution-units page proves both registered units",
        )
    finally:
        d.mcp.close()

    report = {"checks": checks, "screenshots": shots, "ok": all(c["ok"] for c in checks)}
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
