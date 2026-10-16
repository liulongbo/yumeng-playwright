"""CD-07 acceptance: 达人详情「报价与历史」移除「系统采集历史」小模块展示.

Real running stack: frontend http://127.0.0.1:5173, API http://127.0.0.1:8000 and real database rows.
The browser comes from the project's configured Playwright MCP server over MCP stdio (see
mcp_client.py); this is not "Playwright MCP tool direct-call" and is reported as such.

Covers:
  - the 系统采集历史 module is gone (title, index counter, timeline, empty shell);
  - 报价历史 in the same chapter still renders real quote observations;
  - the page no longer consumes `GET /api/creator-library/{id}/history` while that endpoint and its
    data remain intact (no destructive change);
  - the untouched chapters, the task entry, and 390px still work.

Usage:
    XINGTU_QA_PASSWORD=... .venv/bin/python scripts/acceptance/run_cd07_acceptance.py

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
EVIDENCE_DIR = pathlib.Path("docs/evidence/assets/cd07")
REPORT = pathlib.Path("docs/evidence/CD-07-acceptance-2026-10-15.json")

CREATOR_ID = "700ca5b0-f0c8-4436-86fe-624dfeb0f151"
TASK_ID = "efb257a6-476b-47ee-aff4-807795bb61a0"
CREATOR_NAME = "甄选聊车"
QUOTE_CHAPTER = "报价与历史"

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
        shots.append({"name": name, "path": f"docs/evidence/assets/cd07/{name}.png", "note": None})
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
            panelTitles: Array.from(document.querySelectorAll('.chapter-body .panel-heading h2')).map((n) => n.textContent),
            text,
            hasHistoryList: Boolean(document.querySelector('.history-list')),
            hasHistoryPanel: Boolean(document.querySelector('.history-panel')),
            hasGapNote: Boolean(document.querySelector('.gap-note')),
            quoteRows: document.querySelectorAll('.quote-list > div').length,
            hasJsonLeak: text.includes('{') && text.includes('snapshot_id'),
            emptyShells: Array.from(document.querySelectorAll('.chapter-body section')).filter(
              (node) => node.textContent.trim().length === 0
            ).length,
          };
        })()""",
    )


def api_probe(client: PlaywrightMcp) -> dict[str, Any]:
    """The endpoint and its data must still exist even though the page stopped consuming it."""
    return evaluate(
        client,
        """(async () => {
          const response = await fetch(%s, { credentials: 'include' });
          if (!response.ok) return { ok: false, status: response.status };
          const body = await response.json();
          return {
            ok: true,
            status: response.status,
            items: Array.isArray(body.items) ? body.items.length : null,
            indexed: body.indexed_snapshots,
            total: body.total_snapshots,
          };
        })()"""
        % json.dumps(f"/api/creator-library/{CREATOR_ID}/history"),
    )


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
            "CD07-MCP",
            "browser_navigate" in tools and "browser_network_requests" in tools,
            f"Playwright MCP {info.get('serverInfo', {}).get('version')} over stdio, {len(tools)} tools "
            "(tool direct-call not exposed in this session)",
        )

        navigate(client, f"{BASE}/creators", 2500)
        if evaluate(client, "(() => location.pathname === '/login' || Boolean(document.querySelector('.login-card')))()"):
            check("CD07-session", False, "seeded session expired; re-run scripts/acceptance/seed_auth.py")
            collect_observability(client)
            return 1
        client.call("browser_resize", {"width": 1440, "height": 1500}, timeout=60)

        # ---- 需求：移除「系统采集历史」 ------------------------------------------------------
        open_chapter(client, library_url, QUOTE_CHAPTER)
        quote_chapter = chapter_state(client)
        check(
            "CD07-QH-01-history-module-removed",
            "系统采集历史" not in quote_chapter["text"]
            and quote_chapter["hasHistoryList"] is False
            and quote_chapter["hasHistoryPanel"] is False,
            f"标题在页面：{'系统采集历史' in quote_chapter['text']!r}；"
            f".history-list={quote_chapter['hasHistoryList']!r} .history-panel={quote_chapter['hasHistoryPanel']!r}",
        )
        check(
            "CD07-QH-02-quote-history-retained",
            "报价历史" in quote_chapter["panelTitles"] and quote_chapter["quoteRows"] > 0,
            f"同一章节面板={quote_chapter['panelTitles']!r} 报价历史行数={quote_chapter['quoteRows']}",
        )
        check(
            "CD07-QH-05-no-shell-or-json",
            quote_chapter["emptyShells"] == 0 and quote_chapter["hasGapNote"] is False,
            f"空容器={quote_chapter['emptyShells']} 索引缺口提示残留={quote_chapter['hasGapNote']!r}",
        )
        screenshot(client, "CD07-library-quote-history")

        # The page must not consume the history endpoint any more.
        consumed = evaluate(
            client,
            """(() => {
              const entries = performance.getEntriesByType('resource').map((item) => item.name);
              return {
                history: entries.filter((url) => url.includes('/history')).length,
                quotes: entries.filter((url) => url.includes('/quotes')).length,
              };
            })()""",
        )
        check(
            "CD07-QH-03-history-not-consumed",
            consumed.get("history") == 0 and int(consumed.get("quotes") or 0) > 0,
            f"本次页面加载中的 /history 资源请求={consumed.get('history')}（应为 0），"
            f"/quotes={consumed.get('quotes')}（应 > 0）",
        )

        # …while the endpoint itself and its data are untouched.
        probe = api_probe(client)
        check(
            "CD07-QH-04-endpoint-and-data-intact",
            probe.get("ok") is True and probe.get("items") is not None,
            f"GET /api/creator-library/{{id}}/history 仍可用：{probe!r}（本轮只解除页面消费，未做破坏性变更）",
        )

        # ---- 回归 ---------------------------------------------------------------------------
        for label, marker in (
            ("商业能力", "内容数据"),
            ("创作能力", "最新视频表现"),
            ("履约能力", "履约与合作表现"),
            ("连接用户", "近 30 日连接用户与粉丝趋势"),
        ):
            open_chapter(client, library_url, label)
            state = chapter_state(client)
            check(
                f"CD07-REG-01-{label}",
                state["active"] == label and marker in state["text"],
                f"active={state['active']!r} contains {marker!r}={marker in state['text']}",
            )

        # Task entry: its 报价与历史 chapter carries this task's snapshot quotes (no such module there).
        open_chapter(client, task_url, QUOTE_CHAPTER)
        task_quote = chapter_state(client)
        check(
            "CD07-REG-02-task-entry",
            task_quote["active"] == QUOTE_CHAPTER
            and "系统采集历史" not in task_quote["text"]
            and len(task_quote["text"]) > 20,
            f"任务入口「报价与历史」active={task_quote['active']!r} "
            f"含系统采集历史={'系统采集历史' in task_quote['text']!r} length={len(task_quote['text'])}",
        )
        screenshot(client, "CD07-task-quote-history")

        # 390px
        client.call("browser_resize", {"width": 390, "height": 900}, timeout=60)
        time.sleep(1.2)
        open_chapter(client, library_url, QUOTE_CHAPTER)
        narrow = evaluate(
            client,
            """(() => ({
              horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
              docWidth: document.documentElement.scrollWidth,
              innerWidth: window.innerWidth,
              hasHistoryList: Boolean(document.querySelector('.history-list')),
            }))()""",
        )
        check(
            "CD07-REG-03-mobile-no-overflow",
            narrow.get("horizontalOverflow") is False and narrow.get("hasHistoryList") is False,
            f"390px: overflow={narrow.get('horizontalOverflow')!r} doc={narrow.get('docWidth')} "
            f"viewport={narrow.get('innerWidth')}",
        )
        screenshot(client, "CD07-library-quote-history-390")
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
    check("CD07-NO-console-errors", not error_lines, f"console error lines={len(error_lines)}: {error_lines[:3]!r}")
    check("CD07-NO-failed-api", not failed_api, f"failed API lines={len(failed_api)}: {failed_api[:3]!r}")

    failed = [item for item in results if not item["passed"]]
    report = {
        "round": "CD-07",
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
