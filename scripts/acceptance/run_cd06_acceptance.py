"""CD-06 acceptance: 达人详情「履约能力」精简 + 「连接用户」双轴趋势合并.

Real running stack: frontend http://127.0.0.1:5173, API http://127.0.0.1:8000 and real database rows.
The browser comes from the project's configured Playwright MCP server over MCP stdio (see
mcp_client.py); this is not "Playwright MCP tool direct-call" and is reported as such.

Covers the two requirements of this round:
 一. 履约能力 — 行业订单分布 / 行业播放分布 / 合作行业分布 三个模块不再展示（数据未删）;
 二. 连接用户 — 去掉「连接用户规模与粉丝增长」与「近 30 日粉丝日增量」；把「近 30 日粉丝总数」与
    「近 30 日连接用户（平台窗口口径）」合并为一张双轴图（左轴连接用户数、右轴粉丝数、X 轴时间），
    鼠标移到任一时间点可同时查看两者。

Usage:
    XINGTU_QA_PASSWORD=... .venv/bin/python scripts/acceptance/run_cd06_acceptance.py

The password is read from the environment and never written into the evidence files.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import time
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from scripts.acceptance.mcp_client import PlaywrightMcp  # noqa: E402
from scripts.acceptance.run_acceptance import BASE, evaluate, navigate  # noqa: E402

SHOT_DIR = pathlib.Path("/tmp/dsh-playwright-mcp")
EVIDENCE_DIR = pathlib.Path("docs/evidence/assets/cd06")
REPORT = pathlib.Path("docs/evidence/CD-06-acceptance-2026-10-15.json")

CREATOR_ID = "700ca5b0-f0c8-4436-86fe-624dfeb0f151"
TASK_ID = "efb257a6-476b-47ee-aff4-807795bb61a0"
CREATOR_NAME = "甄选聊车"
FULFILLMENT = "履约能力"
AUDIENCE = "连接用户"

REMOVED_FULFILLMENT = ["行业订单分布", "行业播放分布", "合作行业分布"]
REMOVED_AUDIENCE = [
    "连接用户规模与粉丝增长",
    "近 30 日粉丝日增量",
    "近 30 日粉丝总数",
    "近 30 日连接用户（平台窗口口径）",
]

results: list[dict[str, Any]] = []
shots: list[Any] = []
console_messages: list[dict[str, Any]] = []
failed_requests: list[dict[str, Any]] = []


def check(name: str, passed: bool, detail: str) -> None:
    results.append({"check": name, "passed": bool(passed), "detail": detail})
    print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}", flush=True)


def screenshot(client: PlaywrightMcp, name: str) -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    target = SHOT_DIR / f"{name}.png"
    try:
        client.call(
            "browser_take_screenshot",
            {"filename": str(target), "fullPage": True, "type": "png"},
            timeout=120,
        )
    except Exception as error:  # noqa: BLE001 - a failed capture is reported, not hidden
        shots.append({"name": name, "path": None, "note": f"screenshot failed: {error}"})
        return
    for _ in range(40):
        if target.exists():
            break
        time.sleep(0.25)
    if target.exists():
        shutil.copyfile(target, EVIDENCE_DIR / f"{name}.png")
        shots.append({"name": name, "path": f"docs/evidence/assets/cd06/{name}.png", "note": None})
    else:
        shots.append({"name": name, "path": None, "note": "screenshot file was not produced"})


def collect_observability(client: PlaywrightMcp) -> None:
    for tool, sink in (
        ("browser_console_messages", console_messages),
        ("browser_network_requests", failed_requests),
    ):
        try:
            payload = client.text_of(client.call(tool, {}, timeout=60))
        except Exception as error:  # noqa: BLE001 - observability must not abort the run
            sink.append({"error": str(error)})
            continue
        sink.append({"raw": payload[:30000]})


def open_chapter(client: PlaywrightMcp, url: str, label: str) -> None:
    navigate(client, url, 3200)
    clicked = evaluate(
        client,
        """(() => {
          const button = Array.from(document.querySelectorAll('.chapter-tabs button'))
            .find((node) => node.textContent.trim() === %s);
          if (!button) return false;
          button.click();
          return true;
        })()"""
        % json.dumps(label),
    )
    if not clicked:
        raise RuntimeError(f"chapter {label!r} not found")
    time.sleep(1.8)


def chapter_state(client: PlaywrightMcp) -> dict[str, Any]:
    return evaluate(
        client,
        """(() => {
          const body = document.querySelector('.chapter-body');
          const text = body ? body.textContent : '';
          return {
            active: document.querySelector('.chapter-tabs button.active')?.textContent?.trim() || null,
            headings: Array.from(document.querySelectorAll('.chapter-body .profile-heading h3')).map((n) => n.textContent),
            text,
            hasDeltaBars: Boolean(document.querySelector('.delta-bar')),
            hasJsonLeak: text.includes('"rate"') || text.includes('{"'),
          };
        })()""",
    )


def chart_state(client: PlaywrightMcp) -> dict[str, Any]:
    return evaluate(
        client,
        """(() => {
          const figure = document.querySelector('.chart-figure');
          const svg = figure ? figure.querySelector('svg') : null;
          const lines = Array.from(document.querySelectorAll('.chart-figure polyline.trend-line'));
          return {
            hasFigure: Boolean(figure),
            ariaLabel: svg ? svg.getAttribute('aria-label') : null,
            seriesCount: lines.length,
            seriesClasses: lines.map((n) => n.getAttribute('class')),
            legend: Array.from(document.querySelectorAll('.trend-legend span')).map((n) => n.textContent.trim()),
            axisTitles: Array.from(document.querySelectorAll('.trend-axis-title')).map((n) => n.textContent),
            ticks: Array.from(document.querySelectorAll('.trend-tick')).map((n) => n.textContent),
            dots: document.querySelectorAll('.chart-figure .trend-dot').length,
            hasCapture: Boolean(document.querySelector('.trend-capture')),
            figcaption: figure ? (figure.querySelector('figcaption')?.textContent || null) : null,
            polylinePoints: lines.map((n) => (n.getAttribute('points') || '').split(' ').length),
          };
        })()""",
    )


def read_api_series(client: PlaywrightMcp) -> dict[str, Any]:
    """Read the two real series straight from the API the page itself consumes."""
    return evaluate(
        client,
        """(async () => {
          const response = await fetch(%s, { credentials: 'include' });
          if (!response.ok) return { ok: false, status: response.status };
          const body = await response.json();
          const payload = body.profile_payload || {};
          const fans = ((payload.modules || {}).fans || {}).fields || [];
          const pick = (key) => {
            const field = fans.find((item) => item.field_key === key);
            const data = field && field.value ? field.value.data : null;
            return Array.isArray(data) ? data : [];
          };
          const follower = pick('fans_daily_trend');
          const connection = pick('connection_daily_trend');
          return {
            ok: true,
            follower: follower.map((item) => ({ date: String(item.date), value: Number(item.fans_cnt) })),
            connection: connection.map((item) => ({ date: String(item.date), value: Number(item.value) })),
          };
        })()"""
        % json.dumps(f"/api/creator-library/{CREATOR_ID}"),
    )


def hover_chart(client: PlaywrightMcp, fraction: float) -> dict[str, Any]:
    """Move a real mouse over the chart band and read the layer it opens."""
    geometry = evaluate(
        client,
        """(() => {
          const band = document.querySelector('.trend-capture');
          if (!band) return null;
          const box = band.getBoundingClientRect();
          return { x: box.x, y: box.y, w: box.width, h: box.height };
        })()""",
    )
    if not geometry:
        return {"found": False, "reason": "no-capture-band"}
    x = geometry["x"] + geometry["w"] * fraction
    y = geometry["y"] + geometry["h"] / 2
    try:
        client.call("browser_evaluate", {"function": f"() => {{ window.__cd06 = {{x: {x}, y: {y}}}; return true; }}"}, timeout=60)
        client.call(
            "browser_run_code_unsafe",
            {
                "code": (
                    "async (page) => {\n"
                    "  const point = await page.evaluate(() => window.__cd06);\n"
                    "  // Move away first: a move to the same coordinates emits no event and would\n"
                    "  // leave the layer from a previous step open (or never open it).\n"
                    "  await page.mouse.move(5, 5);\n"
                    "  await page.waitForTimeout(120);\n"
                    "  await page.mouse.move(point.x, point.y);\n"
                    "  await page.waitForTimeout(400);\n"
                    "  return 'moved';\n"
                    "}"
                )
            },
            timeout=90,
        )
    except Exception as error:  # noqa: BLE001 - fall back to a synthetic event, reported below
        evaluate(
            client,
            """(() => {
              const band = document.querySelector('.trend-capture');
              if (!band) return false;
              band.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, clientX: %s, clientY: %s }));
              return true;
            })()"""
            % (x, y),
        )
        time.sleep(0.4)
        return {
            "found": True,
            "synthetic": True,
            "note": f"real mouse move unavailable: {error}",
            **evaluate(client, """(() => {
              const tip = document.querySelector('.trend-tip');
              if (!tip) return { tip: null };
              return { tip: tip.textContent, role: tip.getAttribute('role') };
            })()"""),
        }
    state = evaluate(
        client,
        """(() => {
          const tip = document.querySelector('.trend-tip');
          if (!tip) return { tip: null };
          const rect = tip.getBoundingClientRect();
          const guide = document.querySelector('.trend-guide line');
          return {
            tip: tip.textContent,
            role: tip.getAttribute('role'),
            rect: { x: rect.x, y: rect.y, w: rect.width, h: rect.height },
            withinViewport: rect.x >= -1 && rect.y >= -1 && rect.right <= window.innerWidth + 1,
            hasGuide: Boolean(guide),
            activeDots: document.querySelectorAll('.trend-dot.active').length,
          };
        })()""",
    )
    state["found"] = True
    return state


def main() -> int:
    password = os.environ.get("XINGTU_QA_PASSWORD")
    if not password:
        print("XINGTU_QA_PASSWORD is required (used only to re-seed a session if it expired)", file=sys.stderr)
        return 2
    library_url = f"{BASE}/creators/{CREATOR_ID}"
    task_url = f"{BASE}/tasks/{TASK_ID}/creators/{CREATOR_ID}"

    with PlaywrightMcp() as client:
        info = client.initialize()
        tools = {tool["name"] for tool in client.list_tools()}
        check(
            "CD06-MCP",
            "browser_navigate" in tools and "browser_run_code_unsafe" in tools,
            f"Playwright MCP {info.get('serverInfo', {}).get('version')} over stdio, {len(tools)} tools "
            "(tool direct-call not exposed in this session)",
        )

        navigate(client, f"{BASE}/creators", 2500)
        if evaluate(client, "(() => location.pathname === '/login' || Boolean(document.querySelector('.login-card')))()"):
            check("CD06-session", False, "seeded session expired; re-run scripts/acceptance/seed_auth.py")
            collect_observability(client)
            return 1
        client.call("browser_resize", {"width": 1440, "height": 1500}, timeout=60)

        # ---- 需求一：履约能力 ----------------------------------------------------------------
        open_chapter(client, library_url, FULFILLMENT)
        fulfillment = chapter_state(client)
        check(
            "CD06-FUL-01-three-modules-removed",
            all(name not in fulfillment["text"] for name in REMOVED_FULFILLMENT)
            and "履约与合作表现" in fulfillment["headings"],
            f"履约能力 headings={fulfillment['headings']!r}（应只剩「履约与合作表现」）",
        )
        check(
            "CD06-FUL-02-removed-titles-absent",
            fulfillment["headings"] == ["履约与合作表现"],
            f"章节标题={fulfillment['headings']!r}",
        )
        check(
            "CD06-FUL-03-no-raw-json",
            not fulfillment["hasJsonLeak"],
            f"正文是否泄漏原始 JSON：{fulfillment['hasJsonLeak']!r}",
        )
        screenshot(client, "CD06-library-fulfillment")

        # The removed fields' data must still exist (page-level removal only, not a data change).
        data_state = evaluate(
            client,
            """(async () => {
              const response = await fetch(%s, { credentials: 'include' });
              if (!response.ok) return { ok: false, status: response.status };
              const body = await response.json();
              const payload = body.profile_payload || {};
              const fulfilled = ((payload.modules || {}).fulfillment || {}).fields || [];
              const keys = fulfilled.map((item) => item.field_key);
              const byKey = (key) => {
                const field = fulfilled.find((item) => item.field_key === key);
                return field ? String(field.status) : null;
              };
              return {
                ok: true,
                keys,
                industry_order: byKey('industry_order_distribution'),
                industry_play: byKey('industry_play_distribution'),
                cooperation: byKey('cooperation_industry_distribution'),
              };
            })()"""
            % json.dumps(f"/api/creator-library/{CREATOR_ID}"),
        )
        check(
            "CD06-FUL-04-data-retained-in-api",
            data_state.get("ok") is True
            and all(
                key in (data_state.get("keys") or [])
                for key in (
                    "industry_order_distribution",
                    "industry_play_distribution",
                    "cooperation_industry_distribution",
                )
            ),
            f"三个字段仍由 API 返回（仅移除页面展示）：{data_state!r}",
        )

        # ---- 需求二：连接用户 ----------------------------------------------------------------
        open_chapter(client, library_url, AUDIENCE)
        audience = chapter_state(client)
        chart = chart_state(client)
        api = read_api_series(client)
        check(
            "CD06-AUD-01-scale-panel-removed",
            "连接用户规模与粉丝增长" not in audience["text"],
            f"「连接用户规模与粉丝增长」仍在页面：{'连接用户规模与粉丝增长' in audience['text']!r}",
        )
        check(
            "CD06-AUD-02-delta-panel-removed",
            "近 30 日粉丝日增量" not in audience["text"] and not audience["hasDeltaBars"],
            f"「近 30 日粉丝日增量」标题在页面：{'近 30 日粉丝日增量' in audience['text']!r}；"
            f"柱状图元素：{audience['hasDeltaBars']!r}",
        )
        check(
            "CD06-AUD-03-two-panels-merged",
            "近 30 日粉丝总数" not in audience["text"]
            and "近 30 日连接用户（平台窗口口径）" not in audience["text"]
            and "近 30 日连接用户与粉丝趋势" in audience["text"],
            f"两个旧标题都不再单独出现，改为合并标题；headings={audience['headings']!r}",
        )
        check(
            "CD06-AUD-04-dual-line-chart",
            chart["hasFigure"] is True
            and chart["seriesCount"] == 2
            and any("tone-blue" in (item or "") for item in chart["seriesClasses"])
            and any("tone-crimson" in (item or "") for item in chart["seriesClasses"]),
            f"两条折线：{chart['seriesClasses']!r}；图例={chart['legend']!r}",
        )
        check(
            "CD06-AUD-05-axes-left-right",
            chart["axisTitles"] == ["连接用户数", "粉丝数"],
            f"轴标题={chart['axisTitles']!r}（左=连接用户数，右=粉丝数）",
        )
        check(
            "CD06-AUD-06-time-axis-dates",
            any(t and t.startswith("2026-") for t in chart["ticks"]),
            f"X 轴日期刻度={[t for t in chart['ticks'] if t and t.startswith('2026-')]!r}",
        )
        check(
            "CD06-AUD-07-axis-unit-wan",
            any((t or "").endswith("万") for t in chart["ticks"]),
            f"轴刻度按「万」展示：{chart['ticks'][:4]!r}",
        )
        # Each series must be drawn from its own real platform values, not a shared scale.
        connection = api.get("connection") or []
        follower = api.get("follower") or []
        check(
            "CD06-AUD-08-both-series-from-real-data",
            api.get("ok") is True
            and len(connection) >= 2
            and len(follower) >= 2
            and chart["dots"] >= len(connection) + len(follower) - 2,
            f"API 连接用户 {len(connection)} 点 / 粉丝 {len(follower)} 点；图上点 {chart['dots']} 个",
        )
        check(
            "CD06-AUD-09-last-values-match-api",
            all(value and value in (chart["figcaption"] or "") for value in [
                f"{connection[-1]['value']:,}" if connection else None,
                f"{follower[-1]['value']:,}" if follower else None,
            ]),
            f"末值与 API 一致：{chart['figcaption']!r}",
        )
        check(
            "CD06-AUD-10-legends",
            chart["legend"] == ["连接用户数", "粉丝数"],
            f"图例={chart['legend']!r}",
        )
        screenshot(client, "CD06-library-audience")

        # Hover: both quantities must be readable at one time point.
        hover = hover_chart(client, 0.96)
        tip_text = hover.get("tip") or ""
        check(
            "CD06-AUD-11-hover-shows-both",
            hover.get("tip") is not None
            and "连接用户数" in tip_text
            and "粉丝数" in tip_text
            and any(str(item["value"]) in tip_text.replace(",", "") for item in connection[-1:]),
            f"Hover 浮层={tip_text!r}（role={hover.get('role')!r}）",
        )
        check(
            "CD06-AUD-12-hover-visible-and-guide",
            hover.get("withinViewport") is not False
            and hover.get("hasGuide") is True
            and (hover.get("activeDots") or 0) >= 1,
            f"withinViewport={hover.get('withinViewport')!r} 参考线={hover.get('hasGuide')!r} "
            f"高亮点={hover.get('activeDots')!r} rect={hover.get('rect')!r}",
        )
        screenshot(client, "CD06-library-audience-hover")
        # Clear with a real mouse move away from the chart (a synthetic mouseleave does not drive
        # React's pointer handling, so it would not prove anything).
        try:
            client.call(
                "browser_run_code_unsafe",
                {
                    "code": (
                        "async (page) => {\n"
                        "  await page.mouse.move(10, 10);\n"
                        "  await page.waitForTimeout(400);\n"
                        "  return 'moved-away';\n"
                        "}"
                    )
                },
                timeout=90,
            )
        except Exception as error:  # noqa: BLE001 - reported, not hidden
            check("CD06-AUD-13-hover-clears", False, f"real mouse move unavailable: {error}")
        cleared = evaluate(client, "(() => !document.querySelector('.trend-tip'))()")
        if "CD06-AUD-13-hover-clears" not in {item["check"] for item in results}:
            check("CD06-AUD-13-hover-clears", cleared is True, f"移出图表后浮层关闭={cleared!r}")

        # ---- 回归 ---------------------------------------------------------------------------
        open_chapter(client, task_url, AUDIENCE)
        task_chart = chart_state(client)
        check(
            "CD06-REG-01-task-entry-parity",
            task_chart["seriesCount"] == 2 and task_chart["axisTitles"] == chart["axisTitles"],
            f"任务入口同一双轴图：seriesCount={task_chart['seriesCount']} axes={task_chart['axisTitles']!r}",
        )
        tap = chapter_state(client)
        check(
            "CD06-REG-02-task-entry-removals",
            all(name not in tap["text"] for name in REMOVED_AUDIENCE[:2]) and not tap["hasDeltaBars"],
            f"任务入口同样移除两个模块：{'连接用户规模与粉丝增长' in tap['text']!r}",
        )
        open_chapter(client, task_url, FULFILLMENT)
        tf = chapter_state(client)
        check(
            "CD06-REG-03-task-fulfillment",
            tf["headings"] == ["履约与合作表现"],
            f"任务入口履约能力 headings={tf['headings']!r}",
        )
        # The neighbouring chapters this round did not touch must still render.
        for label, marker in (("商业能力", "内容数据"), ("创作能力", "最新视频表现"), ("报价与历史", "报价")):
            open_chapter(client, library_url, label)
            state = chapter_state(client)
            check(
                f"CD06-REG-04-{label}",
                marker in state["text"] and state["active"] == label,
                f"active={state['active']!r} contains={marker in state['text']!r}",
            )

        # 390px: the dual-axis chart must not overflow.
        client.call("browser_resize", {"width": 390, "height": 900}, timeout=60)
        time.sleep(1.2)
        open_chapter(client, library_url, AUDIENCE)
        narrow = evaluate(
            client,
            """(() => {
              const figure = document.querySelector('.chart-figure');
              return {
                horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
                docWidth: document.documentElement.scrollWidth,
                innerWidth: window.innerWidth,
                figureWidth: figure ? figure.getBoundingClientRect().width : 0,
                svgWidth: figure && figure.querySelector('svg') ? figure.querySelector('svg').getBoundingClientRect().width : 0,
              };
            })()""",
        )
        check(
            "CD06-REG-05-mobile-no-overflow",
            narrow.get("horizontalOverflow") is False
            and float(narrow.get("figureWidth") or 0) > 0
            and float(narrow.get("svgWidth") or 0) > 0,
            f"390px: overflow={narrow.get('horizontalOverflow')!r} doc={narrow.get('docWidth')} "
            f"viewport={narrow.get('innerWidth')} figure={narrow.get('figureWidth')}",
        )
        screenshot(client, "CD06-library-audience-390")
        client.call("browser_resize", {"width": 1440, "height": 1500}, timeout=60)

        collect_observability(client)

    console_raw = "\n".join(str(entry.get("raw", "")) for entry in console_messages)
    error_lines = [
        line
        for line in console_raw.splitlines()
        if ("error" in line.lower() or "Error" in line)
        and not line.strip().startswith("Total messages:")
        and "favicon" not in line.lower()
        and "Failed to load resource" not in line
    ]
    failed_api = [
        line
        for line in console_raw.splitlines()
        if "/api/" in line and any(code in line for code in ("500", "502", "503"))
    ]
    check("CD06-NO-console-errors", not error_lines, f"console error lines={len(error_lines)}: {error_lines[:3]!r}")
    check("CD06-NO-failed-api", not failed_api, f"failed API lines={len(failed_api)}: {failed_api[:3]!r}")

    failed = [item for item in results if not item["passed"]]
    report = {
        "round": "CD-06",
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "base": BASE,
        "creator": CREATOR_NAME,
        "mcp": "project Playwright MCP server over MCP stdio (mcp_client.py); tool direct-call not exposed",
        "checks": results,
        "screenshots": shots,
        "console": console_messages,
        "network": failed_requests,
        "passed": len(results) - len(failed),
        "failed": len(failed),
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed; report={REPORT}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
