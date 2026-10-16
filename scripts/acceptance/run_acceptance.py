"""UI-01 acceptance: drives the project's configured Playwright MCP server over MCP stdio.

Real Chrome, real running stack (frontend http://127.0.0.1:5173, API http://127.0.0.1:8000) and
real database rows. It records DOM-derived evidence, console messages, failed network requests and
screenshots under docs/evidence/assets/ui01/.

Usage:
    XINGTU_QA_PASSWORD=... .venv/bin/python scripts/acceptance/run_acceptance.py

The password is read from the environment and never written to the evidence files.
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

BASE = "http://127.0.0.1:5173"
SHOT_DIR = pathlib.Path("/tmp/dsh-playwright-mcp")
EVIDENCE_DIR = pathlib.Path("docs/evidence/assets/ui01")
TASK_ID = "efb257a6-476b-47ee-aff4-807795bb61a0"
CREATOR_ID = "700ca5b0-f0c8-4436-86fe-624dfeb0f151"
CREATOR_NAME = "甄选聊车"

results: list[dict[str, Any]] = []
shots: list[Any] = []
console_messages: list[dict[str, Any]] = []
failed_requests: list[dict[str, Any]] = []


def check(name: str, passed: bool, detail: str) -> None:
    results.append({"check": name, "passed": bool(passed), "detail": detail})
    print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}", flush=True)


def evaluate(client: PlaywrightMcp, expression: str) -> Any:
    """Run a browser expression and return the decoded `### Result` block.

    The MCP server answers with a Markdown envelope that also carries the generated Playwright
    snippet, page URL/title and console notes, so only the result block is decoded here.
    """
    wrapped = f"() => ({expression})" if expression.lstrip().startswith(("(", "[")) else expression
    payload = client.text_of(client.call("browser_evaluate", {"function": wrapped}))
    block = payload.split("### Result", 1)[1] if "### Result" in payload else payload
    block = block.split("### Ran Playwright code", 1)[0].strip()
    try:
        return json.loads(block)
    except json.JSONDecodeError:
        return block


def navigate(client: PlaywrightMcp, url: str, wait_ms: int = 1200) -> None:
    client.call("browser_navigate", {"url": url}, timeout=120)
    time.sleep(wait_ms / 1000)


def screenshot(client: PlaywrightMcp, name: str) -> None:
    """Capture the current page into the evidence directory and register the artefact."""
    global shots  # noqa: PLW0603 - one module-level artefact list feeds the report
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
        shots.append({"name": name, "path": f"docs/evidence/assets/ui01/{name}.png", "note": None})
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
        sink.append({"raw": payload[:20000]})


def login_password_checks(client: PlaywrightMcp, password: str) -> None:
    """T01 on a signed-out browser: hidden by default, toggle keeps the typed value.

    An authenticated session redirects away from /login, so the driver calls this only after
    logging out at the end of the authenticated checks.
    """
    navigate(client, f"{BASE}/login", 2500)
    password_state = evaluate(
        client,
        """(() => {
      const input = document.querySelector('.password-field input');
      const toggle = document.querySelector('.password-toggle');
      return {
        onLogin: location.pathname === '/login',
        type: input && input.type,
        label: toggle && toggle.getAttribute('aria-label'),
        pressed: toggle && toggle.getAttribute('aria-pressed'),
      };
    })()""",
    )
    check(
        "T01-on-login-page",
        bool(password_state.get("onLogin")),
        f"landed on {password_state!r}",
    )
    check(
        "T01-default-hidden",
        password_state.get("type") == "password",
        f"password input type={password_state.get('type')!r}, toggle label={password_state.get('label')!r}",
    )

    # Fill the real controlled inputs. The password is staged on `window` for the browser call and
    # removed again, so it never appears in source or in the evaluated expression text.
    evaluate(
        client,
        f"(() => {{ window.__acceptanceSecret = {json.dumps(password)}; return true; }})()",
    )
    fill = evaluate(
        client,
        """(() => {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      const username = document.querySelector('input[autocomplete="username"]');
      const password = document.querySelector('.password-field input');
      setter.call(username, 'media-a');
      username.dispatchEvent(new Event('input', { bubbles: true }));
      setter.call(password, window.__acceptanceSecret);
      password.dispatchEvent(new Event('input', { bubbles: true }));
      delete window.__acceptanceSecret;
      return {username: username.value, passwordLength: password.value.length};
    })()""",
    )
    check(
        "T01-typed",
        fill.get("username") == "media-a" and fill.get("passwordLength") == len(password),
        f"typed username={fill.get('username')!r}, password length={fill.get('passwordLength')}",
    )

    shown = evaluate(
        client,
        """(async () => {
      const toggle = document.querySelector('.password-toggle');
      toggle.click();
      await new Promise((resolve) => setTimeout(resolve, 150));
      const revealed = document.querySelector('.password-field input');
      const after = { type: revealed.type, value: revealed.value.length, label: document.querySelector('.password-toggle').getAttribute('aria-label'), pressed: document.querySelector('.password-toggle').getAttribute('aria-pressed') };
      document.querySelector('.password-toggle').click();
      await new Promise((resolve) => setTimeout(resolve, 150));
      const hidden = document.querySelector('.password-field input');
      return { after, restored: { type: hidden.type, value: hidden.value.length, label: document.querySelector('.password-toggle').getAttribute('aria-label') } };
    })()""",
    )
    check(
        "T01-reveal",
        shown["after"]["type"] == "text" and shown["after"]["label"] == "隐藏密码",
        f"after first click type={shown['after']['type']!r}, aria-label={shown['after']['label']!r}",
    )
    check(
        "T01-restore",
        shown["restored"]["type"] == "password" and shown["restored"]["label"] == "显示密码",
        f"after second click type={shown['restored']['type']!r}, aria-label={shown['restored']['label']!r}",
    )
    check(
        "T01-value-kept",
        shown["after"]["value"] == len(password) and shown["restored"]["value"] == len(password),
        f"password length after reveal/hide: {shown['after']['value']} / {shown['restored']['value']}",
    )
    screenshot(client, "T01-login-password-toggle")

    # The original login path must still work after the toggle was used.
    submitted = evaluate(
        client,
        """(async () => {
      document.querySelector('.login-button').click();
      for (let i = 0; i < 60; i += 1) {
        await new Promise((resolve) => setTimeout(resolve, 250));
        if (location.pathname.startsWith('/tasks')) break;
      }
      return { path: location.pathname, heading: document.querySelector('h1') && document.querySelector('h1').textContent };
    })()""",
    )
    check(
        "T01-login-works",
        submitted.get("path", "").startswith("/tasks"),
        f"redirected to {submitted.get('path')!r}, heading={submitted.get('heading')!r}",
    )


def main() -> int:
    password = os.environ.get("XINGTU_QA_PASSWORD")
    if not password:
        print("XINGTU_QA_PASSWORD is required", file=sys.stderr)
        return 2

    with PlaywrightMcp() as client:
        info = client.initialize()
        tools = {tool["name"] for tool in client.list_tools()}
        check(
            "MCP-TRANSPORT",
            "browser_navigate" in tools,
            f"Playwright MCP {info.get('serverInfo', {}).get('version')} over stdio, {len(tools)} tools",
        )

        # ---------------------------------------------------------------- T02 navigation menu
        # Wait for the signed-in shell to mount: the login redirect can resolve before React has
        # rendered the sidebar, and an unrendered page must not be read as "the menu is gone".
        navigate(client, f"{BASE}/tasks", 1500)
        for _ in range(20):
            mounted = evaluate(
                client,
                "(() => ({ nav: document.querySelectorAll('nav[aria-label=\"主导航\"] a').length, rows: document.querySelectorAll('.task-row:not(.table-head)').length }))()",
            )
            if mounted.get("nav") and mounted.get("rows"):
                break
            time.sleep(0.5)
        nav = evaluate(
            client,
            """(() => {
          const links = Array.from(document.querySelectorAll('nav[aria-label="主导航"] a'));
          const rects = links.map((link) => { const box = link.getBoundingClientRect(); return { text: link.textContent.trim(), top: Math.round(box.top), height: Math.round(box.height) }; });
          const gap = rects.length > 1 ? rects[1].top - (rects[0].top + rects[0].height) : null;
          return { links: rects, gap, section: (document.querySelector('.nav-section') || {}).textContent || null };
        })()""",
        )
        labels = [item["text"] for item in nav.get("links", [])]
        check("T02-no-duplicate-entry", "创建任务" not in labels, f"nav links = {labels}")
        check("T02-kept-entries", labels == ["任务中心", "达人库"], f"nav links = {labels}")
        check(
            "T02-spacing",
            nav.get("gap") is not None and 0 <= nav["gap"] <= 12,
            f"vertical gap between entries = {nav.get('gap')}px, section label={nav.get('section')!r}",
        )
        screenshot(client, "T02-sidebar-navigation")

        in_page = evaluate(
            client,
            """(() => {
          const links = Array.from(document.querySelectorAll('a')).filter((link) => link.textContent.includes('创建任务'));
          return links.map((link) => link.getAttribute('href'));
        })()""",
        )
        check("T02-in-page-create", in_page == ["/tasks/new"], f"in-page create links = {in_page}")

        # ---------------------------------------------------------------- T03 task creator list
        navigate(client, f"{BASE}/tasks/{TASK_ID}", 2500)
        rows = evaluate(
            client,
            """(() => Array.from(document.querySelectorAll('.creator-row')).map((row) => ({
          href: row.getAttribute('href'),
          name: row.querySelector('.creator-copy strong') && row.querySelector('.creator-copy strong').textContent,
          tags: row.querySelector('.creator-copy span') && row.querySelector('.creator-copy span').textContent,
          avatar: Boolean(row.querySelector('.creator-avatar img')),
          stats: Array.from(row.querySelectorAll('.creator-stat')).map((stat) => ({ label: stat.querySelector('span').textContent, value: stat.querySelector('strong').textContent, note: stat.querySelector('small') ? stat.querySelector('small').textContent : null })),
          scrollWidth: row.scrollWidth,
          clientWidth: row.clientWidth,
          overflow: row.scrollWidth > row.clientWidth + 1,
        })))()""",
        )
        target = next((row for row in rows if CREATOR_NAME in (row.get("name") or "")), None)
        check(
            "T03-row-present",
            target is not None,
            f"{len(rows)} creator rows, target {CREATOR_NAME!r} found={target is not None}",
        )
        if target:
            labels_seen = [stat["label"] for stat in target["stats"]]
            check(
                "T03-metrics-labelled",
                labels_seen == ["粉丝", "月深度用户", "互动 / 完播原始值", "CPM / CPE 原始值"],
                f"metric labels = {labels_seen}",
            )
            values = {stat["label"]: stat["value"] for stat in target["stats"]}
            check(
                "T03-followers",
                values.get("粉丝") == "1,351,784",
                f"粉丝 = {values.get('粉丝')!r} (DB followers_count=1351784)",
            )
            check(
                "T03-deep-users",
                values.get("月深度用户") == "≈1,158w",
                f"月深度用户 = {values.get('月深度用户')!r} (DB raw='1,158w', approximate=true)",
            )
            check(
                "T03-interaction-completion",
                values.get("互动 / 完播原始值") == "112 / 551",
                f"互动/完播 = {values.get('互动 / 完播原始值')!r} (DB 112 / 551)",
            )
            check(
                "T03-cpm-cpe",
                values.get("CPM / CPE 原始值") == "2969 / 246",
                f"CPM/CPE = {values.get('CPM / CPE 原始值')!r} (DB 21-60: 2969 / 246)",
            )
            note_visible = evaluate(
                client,
                """(() => {
          const note = document.querySelector('.creator-row .creator-stat.commercial small');
          if (!note) return null;
          const box = note.getBoundingClientRect();
          const style = getComputedStyle(note);
          return {
            text: note.textContent,
            height: Math.round(box.height),
            lineHeight: Math.round(parseFloat(style.lineHeight) || 0),
            clipped: note.scrollWidth > note.clientWidth + 1,
            hidden: style.display === 'none' || style.visibility === 'hidden',
          };
        })()""",
            )
            check(
                "T03-second-cpm-band",
                bool(note_visible)
                and "60 秒以上 2969 / 246" in (note_visible.get("text") or "")
                and not note_visible.get("clipped")
                and not note_visible.get("hidden"),
                f"second band note = {note_visible}",
            )
            check(
                "T03-tags",
                bool(target["tags"]) and "汽车" in target["tags"],
                f"tags = {target['tags']!r} (snapshot creator_type_label=汽车, industry=金融业/美妆/游戏)",
            )
            check("T03-avatar", target["avatar"], "avatar rendered from snapshot basic.avatar_uri")
            viewport = evaluate(
                client,
                "(() => ({ width: window.innerWidth, scrollWidth: document.documentElement.scrollWidth }))()",
            )
            check(
                "T03-no-overflow",
                not target["overflow"],
                f"row scrollWidth={target['scrollWidth']} clientWidth={target['clientWidth']} "
                f"viewport={viewport}",
            )
        screenshot(client, "T03-task-creator-metrics")

        # Detail navigation from the task entry.
        detail_href = target["href"] if target else f"/tasks/{TASK_ID}/creators/{CREATOR_ID}"
        navigate(client, f"{BASE}{detail_href}", 2500)
        task_detail = evaluate(
            client,
            """(() => ({
          path: location.pathname,
          heading: document.querySelector('h1') && document.querySelector('h1').textContent,
          dt: Array.from(document.querySelectorAll('.library-fields dt')).map((node) => node.textContent),
          dd: Array.from(document.querySelectorAll('.library-fields dd')).map((node) => node.textContent),
          metrics: Array.from(document.querySelectorAll('.library-metrics .metric')).map((node) => ({ label: node.querySelector('span').textContent, value: node.querySelector('strong').textContent })),
          sections: Array.from(document.querySelectorAll('.library-detail-panel h2')).map((node) => node.textContent),
          error: Boolean(document.querySelector('.danger-state')),
        }))()""",
        )
        check(
            "T03-detail-nav",
            task_detail["path"] == detail_href and not task_detail["error"],
            f"task entry opened {task_detail['path']!r}, heading={task_detail['heading']!r}, error={task_detail['error']}",
        )
        screenshot(client, "T05-task-entry-creator-detail")

        # ---------------------------------------------------------------- T04 completion time
        # The previous step ended on the creator detail page, so return to the task detail first.
        navigate(client, f"{BASE}/tasks/{TASK_ID}", 2500)
        hero = evaluate(
            client,
            """(() => {
          const facts = Array.from(document.querySelectorAll('.hero-meta > div')).map((node) => ({ label: node.querySelector('span').textContent, value: node.querySelector('strong').textContent, title: node.querySelector('strong').getAttribute('title') }));
          return { status: document.querySelector('.status-badge') && document.querySelector('.status-badge').textContent, facts };
        })()""",
        )
        labels = [fact["label"] for fact in hero["facts"]]
        values = {fact["label"]: fact["value"] for fact in hero["facts"]}
        check("T04-completion-label", "完成时间" in labels, f"hero facts labels = {labels}")
        check(
            "T04-update-label",
            "最近更新" in labels,
            "the last-write field keeps its own distinct label",
        )
        expected_completed = "10/14 10:02"
        check(
            "T04-completion-value",
            values.get("完成时间") == expected_completed,
            f"完成时间 = {values.get('完成时间')!r} (DB completed_at = 2026-10-14T02:02:10Z == UTC+8 10:02)",
        )
        check(
            "T04-tooltip",
            any("最后一次改动" in (fact["title"] or "") for fact in hero["facts"]),
            "最近更新 explains it is the last write, not completion",
        )
        screenshot(client, "T04-task-completion-time")

        # ---------------------------------------------------------------- T05 unified detail
        navigate(client, f"{BASE}/creators/{CREATOR_ID}", 2500)
        library_detail = evaluate(
            client,
            """(() => ({
          path: location.pathname,
          heading: document.querySelector('h1') && document.querySelector('h1').textContent,
          dt: Array.from(document.querySelectorAll('.library-fields dt')).map((node) => node.textContent),
          dd: Array.from(document.querySelectorAll('.library-fields dd')).map((node) => node.textContent),
          metrics: Array.from(document.querySelectorAll('.library-metrics .metric')).map((node) => ({ label: node.querySelector('span').textContent, value: node.querySelector('strong').textContent })),
          sections: Array.from(document.querySelectorAll('.library-detail-panel h2')).map((node) => node.textContent),
          error: Boolean(document.querySelector('.danger-state')),
        }))()""",
        )
        check(
            "T05-library-entry",
            library_detail["path"] == f"/creators/{CREATOR_ID}" and not library_detail["error"],
            f"library entry opened {library_detail['path']!r}, heading={library_detail['heading']!r}, error={library_detail['error']}",
        )
        check(
            "T05-same-heading",
            library_detail["heading"] == task_detail["heading"],
            f"headings: library={library_detail['heading']!r} task={task_detail['heading']!r}",
        )
        check(
            "T05-same-field-labels",
            library_detail["dt"] == task_detail["dt"],
            f"library fields={library_detail['dt']} / task fields={task_detail['dt']}",
        )
        check(
            "T05-same-field-values",
            library_detail["dd"] == task_detail["dd"],
            f"library values={library_detail['dd']} / task values={task_detail['dd']}",
        )
        check(
            "T05-same-metrics",
            library_detail["metrics"] == task_detail["metrics"],
            f"library KPIs={library_detail['metrics']} / task KPIs={task_detail['metrics']}",
        )
        check(
            "T05-same-base-sections",
            [s for s in task_detail["sections"] if s in ("基础与传播表现", "数据质量与来源")]
            == [s for s in library_detail["sections"] if s in ("基础与传播表现", "数据质量与来源")],
            f"library sections={library_detail['sections']} / task sections={task_detail['sections']}",
        )
        check(
            "T05-id-not-mixed-up",
            CREATOR_NAME in (library_detail["heading"] or "")
            and library_detail["heading"] == task_detail["heading"],
            "both entries resolved the same creator id to the same creator name",
        )
        screenshot(client, "T05-library-entry-creator-detail")

        # Regression: task centre and library list still load.
        navigate(client, f"{BASE}/tasks", 2000)
        tasks_page = evaluate(
            client,
            """(() => ({ path: location.pathname, rows: document.querySelectorAll('.task-row:not(.table-head)').length, error: Boolean(document.querySelector('.danger-state')) }))()""",
        )
        check(
            "REG-task-centre",
            tasks_page["rows"] > 0 and not tasks_page["error"],
            f"/tasks rows={tasks_page['rows']}, error={tasks_page['error']}",
        )
        navigate(client, f"{BASE}/creators", 2500)
        library_page = evaluate(
            client,
            """(() => ({ rows: document.querySelectorAll('.library-row').length, error: Boolean(document.querySelector('.danger-state')) }))()""",
        )
        check(
            "REG-creator-library",
            library_page["rows"] > 0 and not library_page["error"],
            f"/creators rows={library_page['rows']}, error={library_page['error']}",
        )
        screenshot(client, "REG-creator-library-list")

        navigate(client, f"{BASE}/tasks/new", 2500)
        new_task = evaluate(
            client,
            """(() => ({ heading: document.querySelector('h1') && document.querySelector('h1').textContent, error: Boolean(document.querySelector('.danger-state')), path: location.pathname }))()""",
        )
        check(
            "REG-create-task-entry",
            new_task["path"] == "/tasks/new" and not new_task["error"],
            f"/tasks/new heading={new_task['heading']!r}, error={new_task['error']}",
        )
        screenshot(client, "REG-create-task-entry")

        # ------------------------------------------------------- T01 (signed out at the end)
        # The authenticated checks are done, so log out and exercise the password toggle on a
        # genuinely signed-out browser; the helper signs back in afterwards.
        logout = evaluate(
            client,
            """(async () => {
          const button = document.querySelector('.account-menu button[aria-label="退出登录"]');
          if (!button) return { clicked: false, path: location.pathname };
          button.click();
          for (let i = 0; i < 60; i += 1) {
            await new Promise((resolve) => setTimeout(resolve, 250));
            if (location.pathname === '/login') break;
          }
          return { clicked: true, path: location.pathname };
        })()""",
        )
        check(
            "T01-logout",
            logout.get("clicked") and logout.get("path") == "/login",
            f"logout reached {logout.get('path')!r}",
        )
        login_password_checks(client, password)

        collect_observability(client)
        try:
            client.call("browser_close", {}, timeout=30)
        except Exception:  # noqa: BLE001 - closing is best effort
            pass

    report = {
        "task_id": TASK_ID,
        "creator_id": CREATOR_ID,
        "checks": results,
        "screenshots": shots,
        "console_messages": console_messages,
        "network_requests": failed_requests,
    }
    out = pathlib.Path("docs/evidence/ui01-browser-acceptance.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    failed = [item for item in results if not item["passed"]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed -> {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
