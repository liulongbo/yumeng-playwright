"""CD-05 acceptance: 达人详情 Tab 调整 + 「创作能力 · 最新视频表现」图表/作品优化.

Real running stack: frontend http://127.0.0.1:5173, API http://127.0.0.1:8000 and real database rows.
The browser comes from the project's configured Playwright MCP server over MCP stdio (see
mcp_client.py); this is not "Playwright MCP tool direct-call" and is reported as such.

Covers the CRE-01..CRE-22 cases of the round: the five chapters and their default, the removed 概览,
the removed 视频表现口径对照, the bar chart's default play labels in 万, the publish-date x axis, the
hover layer, the real work links on both the bars and the cards, cover degradation, data consistency
between the chart and the list, refresh, long titles and the other-chapter regression.

Usage:
    XINGTU_QA_PASSWORD=... .venv/bin/python scripts/acceptance/run_cd05_acceptance.py

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
EVIDENCE_DIR = pathlib.Path("docs/evidence/assets/cd05")
REPORT = pathlib.Path("docs/evidence/CD-05-acceptance-2026-10-15.json")

# 甄选聊车: a real creator whose creation module holds 15 real video records.
TASK_ID = "efb257a6-476b-47ee-aff4-807795bb61a0"
CREATOR_ID = "700ca5b0-f0c8-4436-86fe-624dfeb0f151"
CREATOR_NAME = "甄选聊车"
CREATIVE_CHAPTER = "创作能力"
FIVE_TABS = ["商业能力", "创作能力", "履约能力", "连接用户", "报价与历史"]
FOUR_TABS = ["商业能力", "创作能力", "履约能力", "连接用户"]

results: list[dict[str, Any]] = []
shots: list[Any] = []
console_messages: list[dict[str, Any]] = []
failed_requests: list[dict[str, Any]] = []


def check(name: str, passed: bool, detail: str) -> None:
    results.append({"check": name, "passed": bool(passed), "detail": detail})
    print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}", flush=True)


def screenshot(client: PlaywrightMcp, name: str) -> None:
    """Capture the current page into the evidence directory and register the artefact."""
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
        shots.append({"name": name, "path": f"docs/evidence/assets/cd05/{name}.png", "note": None})
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
    navigate(client, url, 3000)
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


def tab_state(client: PlaywrightMcp) -> dict[str, Any]:
    return evaluate(
        client,
        """(() => ({
          tabs: Array.from(document.querySelectorAll('.chapter-tabs button')).map((n) => n.textContent.trim()),
          roles: Array.from(document.querySelectorAll('.chapter-tabs button')).map((n) => n.getAttribute('role')),
          active: document.querySelector('.chapter-tabs button.active')?.textContent?.trim() || null,
          activeAria: document.querySelector('.chapter-tabs button.active')?.getAttribute('aria-selected') || null,
          bodyLength: (document.querySelector('.chapter-body')?.textContent || '').length,
          tabpanel: Boolean(document.querySelector('.chapter-body[role="tabpanel"]')),
          hasOverviewTab: Array.from(document.querySelectorAll('.chapter-tabs button'))
            .some((n) => n.textContent.trim() === '达人概览'),
          hasOverviewPanel: Boolean(document.querySelector('#overview')),
        }))()""",
    )


def chart_state(client: PlaywrightMcp) -> dict[str, Any]:
    return evaluate(
        client,
        """(() => ({
          bars: document.querySelectorAll('.video-bar-slot').length,
          barLinks: Array.from(document.querySelectorAll('a.video-bar')).map((n) => ({
            href: n.getAttribute('href'), target: n.getAttribute('target'), rel: n.getAttribute('rel'),
            id: n.getAttribute('data-video-id'),
          })),
          plainBars: document.querySelectorAll('div.video-bar').length,
          labels: Array.from(document.querySelectorAll('.video-bar-value')).map((n) => n.textContent),
          dates: Array.from(document.querySelectorAll('.video-bar-date')).map((n) => n.textContent),
          heights: Array.from(document.querySelectorAll('.video-bar i')).map((n) => n.style.height),
          cards: document.querySelectorAll('.video-card').length,
          cardLinks: Array.from(document.querySelectorAll('a.video-card')).map((n) => ({
            href: n.getAttribute('href'), target: n.getAttribute('target'),
          })),
          noLinkCards: document.querySelectorAll('.video-card.no-link').length,
          cardCovers: document.querySelectorAll('.video-card-cover img').length,
          cardCoverEmpty: document.querySelectorAll('.video-card-cover-empty').length,
          cardTexts: Array.from(document.querySelectorAll('.video-card')).map((n) => n.textContent),
          hasCompare: Boolean(document.querySelector('.compare-table')),
          hasCompareTitle: document.body.innerText.includes('视频表现口径对照'),
          hasOverviewTab: Array.from(document.querySelectorAll('.chapter-tabs button'))
            .some((n) => n.textContent.trim() === '达人概览'),
        }))()""",
    )


def read_api_videos(client: PlaywrightMcp, path_name: str, url: str) -> dict[str, Any]:
    """Read the real records straight from the API the page itself consumes."""
    return evaluate(
        client,
        """(async () => {
          const response = await fetch(%s, { credentials: 'include' });
          if (!response.ok) return { ok: false, status: response.status };
          const body = await response.json();
          const payload = body.profile_payload || {};
          const creation = ((payload.modules || {}).creation || {}).fields || [];
          const field = creation.find((item) => item.field_key === 'recent_video_performance');
          const data = field && field.value ? field.value.data : null;
          const rows = Array.isArray(data) ? data : [];
          return {
            ok: true,
            status: response.status,
            name: %s,
            recorded: rows.map((item) => ({
              item_id: String(item.item_id ?? item.video_id ?? ''),
              title: String(item.title ?? item.item_title ?? ''),
              play: item.play,
              date: String(item.item_date ?? ''),
              cover: item.item_cover ?? '',
              url: String(item.url ?? ''),
            })),
          };
        })()"""
        % (json.dumps(url), json.dumps(path_name)),
    )


def hover_layer(client: PlaywrightMcp, index: int) -> dict[str, Any]:
    """Hover a real bar with a real mouse and read the layer it opens."""
    return evaluate(
        client,
        """(async () => {
          const bar = document.querySelectorAll('.video-bar')[%d];
          if (!bar) return { found: false };
          const box = bar.getBoundingClientRect();
          bar.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, clientX: box.x + box.width / 2, clientY: box.y + box.height / 2 }));
          bar.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true, clientX: box.x + box.width / 2, clientY: box.y + box.height / 2 }));
          await new Promise((resolve) => setTimeout(resolve, 400));
          const tip = document.querySelector('.video-tip');
          if (!tip) return { found: false };
          const rect = tip.getBoundingClientRect();
          const barRect = bar.getBoundingClientRect();
          return {
            found: true,
            role: tip.getAttribute('role'),
            text: tip.textContent,
            title: tip.querySelector('strong')?.textContent || '',
            hasCover: Boolean(tip.querySelector('.video-tip-cover img')),
            hasCoverEmpty: Boolean(tip.querySelector('.video-tip-cover-empty')),
            link: tip.querySelector('a.video-tip-link')?.getAttribute('href') || null,
            linkTarget: tip.querySelector('a.video-tip-link')?.getAttribute('target') || null,
            rect: { x: rect.x, y: rect.y, w: rect.width, h: rect.height },
            barRect: { x: barRect.x, y: barRect.y, w: barRect.width, h: barRect.height },
            withinViewport: rect.x >= 0 && rect.y >= 0 && rect.right <= window.innerWidth + 1,
            position: getComputedStyle(tip).position,
          };
        })()"""
        % index,
    )


def click_opens_new_tab(client: PlaywrightMcp, selector: str, index: int) -> dict[str, Any]:
    """Click through the real element and capture the tab it opens, without leaving the detail page."""
    return evaluate(
        client,
        """(async () => {
          const target = document.querySelectorAll(%s)[%d];
          if (!target) return { found: false };
          const opened = [];
          const original = window.open;
          window.open = (url, name, features) => {
            opened.push({ url: String(url), name: name === undefined ? null : String(name), features: features === undefined ? null : String(features) });
            return null;
          };
          const before = location.href;
          let defaultPrevented = false;
          target.addEventListener('click', (event) => { defaultPrevented = event.defaultPrevented; }, { once: true });
          target.click();
          await new Promise((resolve) => setTimeout(resolve, 500));
          window.open = original;
          return {
            found: true,
            opened,
            href: target.getAttribute('href'),
            targetAttr: target.getAttribute('target'),
            rel: target.getAttribute('rel'),
            stayed: location.href === before,
            pathname: location.pathname,
            defaultPrevented,
          };
        })()"""
        % (json.dumps(selector), index),
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
            "CD05-MCP",
            "browser_navigate" in tools and "browser_hover" in tools,
            f"Playwright MCP {info.get('serverInfo', {}).get('version')} over stdio, {len(tools)} tools "
            "(tool direct-call not exposed in this session; see the evidence file)",
        )

        navigate(client, f"{BASE}/creators", 2500)
        signed_out = evaluate(
            client,
            "(() => location.pathname === '/login' || Boolean(document.querySelector('.login-card')))()",
        )
        if signed_out:
            check("CD05-session", False, "seeded session expired; re-run scripts/acceptance/seed_auth.py")
            collect_observability(client)
            return 1
        client.call("browser_resize", {"width": 1440, "height": 1400}, timeout=60)

        # ---- CRE-01..CRE-05: chapters, default, legacy identifier -------------------------------
        navigate(client, library_url, 3200)
        library_tabs = tab_state(client)
        check(
            "CRE-01-library-five-tabs",
            library_tabs["tabs"] == FIVE_TABS,
            f"达人库入口 tabs={library_tabs['tabs']!r}",
        )
        check(
            "CRE-02-overview-removed",
            library_tabs["hasOverviewTab"] is False and "达人概览" not in library_tabs["tabs"],
            f"containsOverview={library_tabs['hasOverviewTab']!r}",
        )
        check(
            "CRE-03-default-commercial",
            library_tabs["active"] == "商业能力" and library_tabs["activeAria"] == "true",
            f"active={library_tabs['active']!r} aria-selected={library_tabs['activeAria']!r}",
        )
        screenshot(client, "CD05-library-default-tab")

        # Every one of the five chapters must render real content.
        chapter_bodies: dict[str, int] = {}
        for label in FIVE_TABS:
            evaluate(
                client,
                """(() => {
                  const b = Array.from(document.querySelectorAll('.chapter-tabs button')).find((n) => n.textContent.trim() === %s);
                  if (b) b.click();
                  return Boolean(b);
                })()"""
                % json.dumps(label),
            )
            time.sleep(1.4)
            body = evaluate(
                client,
                """(() => ({
                  active: document.querySelector('.chapter-tabs button.active')?.textContent?.trim() || null,
                  length: (document.querySelector('.chapter-body')?.textContent || '').trim().length,
                  headings: Array.from(document.querySelectorAll('.chapter-body .profile-heading h3')).map((n) => n.textContent),
                }))()""",
            )
            chapter_bodies[label] = body["length"]
            check(
                f"CRE-04-chapter-{label}",
                body["active"] == label and body["length"] > 40,
                f"active={body['active']!r} textLength={body['length']} headings={body['headings']!r}",
            )
        screenshot(client, "CD05-library-five-chapters")

        # A legacy 达人概览 identifier must not leave a blank page behind. Two real paths:
        # (a) a full page load straight onto `#overview`; (b) a same-document hash change (a bookmark
        # click inside an already-open page), which does not remount the component.
        navigate(client, f"{library_url}#overview", 3200)
        legacy_load = tab_state(client)
        check(
            "CRE-05-legacy-anchor-full-load",
            legacy_load["active"] == "商业能力"
            and legacy_load["bodyLength"] > 40
            and legacy_load["hasOverviewTab"] is False
            and legacy_load["hasOverviewPanel"] is False,
            f"整页加载 #overview: active={legacy_load['active']!r} bodyLength={legacy_load['bodyLength']} "
            f"overviewPanel={legacy_load['hasOverviewPanel']!r} tabs={legacy_load['tabs']!r}",
        )
        evaluate(
            client,
            """(() => {
              const b = Array.from(document.querySelectorAll('.chapter-tabs button')).find((n) => n.textContent.trim() === '报价与历史');
              if (b) b.click();
              return Boolean(b);
            })()""",
        )
        time.sleep(1.2)
        evaluate(client, "(() => { window.location.hash = '#overview'; return true; })()")
        time.sleep(1.5)
        legacy_same_doc = tab_state(client)
        check(
            "CRE-05-legacy-anchor-same-document",
            legacy_same_doc["active"] == "商业能力"
            and legacy_same_doc["bodyLength"] > 40
            and legacy_same_doc["hasOverviewTab"] is False,
            f"页内改 hash 到 #overview: active={legacy_same_doc['active']!r} "
            f"bodyLength={legacy_same_doc['bodyLength']} url={evaluate(client, 'location.href')!r}",
        )

        # ---- CRE-06..CRE-13: the video chart ------------------------------------------------------
        open_chapter(client, library_url, CREATIVE_CHAPTER)
        chart = chart_state(client)
        api = read_api_videos(client, "library", f"/api/creator-library/{CREATOR_ID}")
        recorded = api.get("recorded") or []
        check(
            "CRE-06-chart-loads",
            chart["bars"] > 0 and chart["bars"] == len(recorded),
            f"bars={chart['bars']} apiRecords={len(recorded)} (apiStatus={api.get('status')})",
        )
        screenshot(client, "CD05-library-latest-video-chart")

        # Every bar label must be the real play count of that same record, in 万/k.
        def expected_label(value: Any) -> str:
            try:
                amount = float(value)
            except (TypeError, ValueError):
                return "—"
            if abs(amount) >= 10_000:
                return f"{amount / 10_000:,.1f}万"
            if abs(amount) >= 1_000:
                return f"{amount / 1_000:,.1f}k"
            return f"{int(amount):,}"

        expected_labels = [expected_label(item["play"]) for item in recorded]
        check(
            "CRE-07-every-bar-shows-its-play-count",
            chart["labels"] == expected_labels and len(chart["labels"]) == len(recorded),
            f"rendered={chart['labels']!r} expectedFromApi={expected_labels!r}",
        )
        check(
            "CRE-08-play-unit-wan",
            all(
                label.endswith("万") or label.endswith("k") or label.replace(",", "").isdigit()
                for label in chart["labels"]
            )
            and any(label.endswith("万") for label in chart["labels"]),
            f"labels={chart['labels']!r} (≥1万→万, 1千–1万→k, <1千 原数；仅展示层换算)",
        )
        expected_dates = [item["date"] for item in recorded]
        check(
            "CRE-09-x-axis-publish-date",
            chart["dates"] == expected_dates and all(d != "—" for d in chart["dates"]),
            f"xAxis={chart['dates']!r}",
        )
        check(
            "CRE-10-date-matches-video-record",
            chart["dates"] == expected_dates and not any(d.isdigit() for d in chart["dates"]),
            f"xAxis matches platform item_date for all {len(recorded)} records: {expected_dates[:4]!r}…",
        )
        check(
            "CRE-19-chart-and-list-consistent",
            [link["href"] for link in chart["barLinks"]] == [link["href"] for link in chart["cardLinks"]],
            f"barLinks={len(chart['barLinks'])} cardLinks={len(chart['cardLinks'])} identical order+targets",
        )

        # Hover a bar with a real mouse event and read the layer.
        hover = hover_layer(client, 0)
        first = recorded[0] if recorded else {}
        check(
            "CRE-11-hover-shows-cover-title-play",
            hover.get("found") is True
            and first.get("title", "")[:12] in (hover.get("title") or "")
            and str(first.get("play")) in (hover.get("text") or "").replace(",", ""),
            f"title={hover.get('title')!r} play={first.get('play')!r} text={str(hover.get('text'))[:120]!r} "
            f"cover={'img' if hover.get('hasCover') else 'empty-state'}",
        )
        rect = hover.get("rect") or {}
        bar_rect = hover.get("barRect") or {}
        check(
            "CRE-12-hover-not-clipped",
            hover.get("found") is True
            and hover.get("position") == "fixed"
            and hover.get("withinViewport") is True
            and float(rect.get("w") or 0) > 180
            and float(rect.get("h") or 0) > 100,
            f"position={hover.get('position')!r} tip={rect!r} bar={bar_rect!r} withinViewport={hover.get('withinViewport')!r}",
        )
        screenshot(client, "CD05-library-hover-tooltip")

        # Moving the pointer from the bar onto the layer must not dismiss it.
        stayed = evaluate(
            client,
            """(async () => {
              const bar = document.querySelectorAll('.video-bar')[0];
              bar.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
              await new Promise((r) => setTimeout(r, 250));
              const tip = document.querySelector('.video-tip');
              if (!tip) return { hadTip: false };
              bar.dispatchEvent(new MouseEvent('mouseleave', { bubbles: true }));
              tip.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
              await new Promise((r) => setTimeout(r, 400));
              return { hadTip: true, stillOpen: Boolean(document.querySelector('.video-tip')) };
            })()""",
        )
        check(
            "CRE-12-hover-survives-move-to-layer",
            stayed.get("hadTip") is True and stayed.get("stillOpen") is True,
            f"{stayed!r}",
        )

        # Clicking the bar opens the real work URL in a new tab and keeps the detail page.
        bar_click = click_opens_new_tab(client, "a.video-bar", 0)
        expected_url = first.get("url")
        check(
            "CRE-13-bar-click-opens-real-work",
            bar_click.get("found") is True
            and bar_click.get("href") == expected_url
            and bar_click.get("targetAttr") == "_blank"
            and bar_click.get("stayed") is True,
            f"href={bar_click.get('href')} matches apiUrl={expected_url} target={bar_click.get('targetAttr')!r} "
            f"stayedOnDetail={bar_click.get('stayed')!r} opened={bar_click.get('opened')!r}",
        )
        tip_click = click_opens_new_tab(client, ".video-tip-link", 0)
        check(
            "CRE-13-tooltip-link-real-work",
            tip_click.get("found") is True and tip_click.get("href") == expected_url,
            f"tooltipLink={tip_click.get('href')} (same record as the hovered bar)",
        )

        # ---- CRE-14..CRE-15: the work cards -------------------------------------------------------
        check(
            "CRE-14-cards-render-cover-or-degrade",
            chart["cards"] == len(recorded)
            and chart["cardCovers"] + chart["cardCoverEmpty"] == len(recorded),
            f"cards={chart['cards']} withRealCoverImg={chart['cardCovers']} emptyCoverState={chart['cardCoverEmpty']}",
        )
        check(
            "CRE-14-cover-gap-is-real-not-faked",
            chart["cardCovers"] == 0 and chart["cardCoverEmpty"] == len(recorded),
            "JSONB item_cover 是不透明对象存储 key（非 http 地址），故按现有占位降级，未构造未经验证的 CDN 链接",
        )
        card_click = click_opens_new_tab(client, "a.video-card", 0)
        check(
            "CRE-15-card-click-opens-real-work",
            card_click.get("found") is True
            and card_click.get("href") == expected_url
            and card_click.get("targetAttr") == "_blank"
            and card_click.get("stayed") is True,
            f"cardHref={card_click.get('href')} matches apiUrl={expected_url} target={card_click.get('targetAttr')!r}",
        )
        check(
            "CRE-15-real-link-unique-per-record",
            len({link["href"] for link in chart["barLinks"]}) == len(chart["barLinks"])
            and all(
                link["href"] and str(recorded[index]["item_id"]) in link["href"]
                for index, link in enumerate(chart["barLinks"])
            ),
            f"each href carries its own item_id: {[link['href'][-24:] for link in chart['barLinks'][:3]]!r}…",
        )

        # ---- CRE-16: 视频表现口径对照 removed ------------------------------------------------------
        check(
            "CRE-16-compare-module-removed",
            chart["hasCompare"] is False and chart["hasCompareTitle"] is False,
            f"compareTable={chart['hasCompare']!r} titleVisible={chart['hasCompareTitle']!r}",
        )
        screenshot(client, "CD05-library-work-cards")

        # ---- CRE-17: empty/degraded data ----------------------------------------------------------
        empty = evaluate(
            client,
            """(async () => {
              const button = Array.from(document.querySelectorAll('.profile-controls button'))
                .find((n) => n.textContent.trim() === '最新星图视频');
              if (button) button.click();
              await new Promise((r) => setTimeout(r, 700));
              const state = {
                labels: Array.from(document.querySelectorAll('.video-bar-value')).map((n) => n.textContent),
                bars: document.querySelectorAll('.video-bar-slot').length,
                cardLinks: Array.from(document.querySelectorAll('a.video-card')).map((n) => n.getAttribute('href')),
                emptyState: document.querySelector('#content .profile-empty')?.textContent || null,
                stayed: location.pathname,
              };
              if (!state.emptyState) return state;
              return state;
            })()""",
        )
        check(
            "CRE-17-empty-or-degraded-state",
            bool(empty.get("emptyState")) or int(empty.get("bars") or 0) > 0,
            f"最新星图视频 切换后：bars={empty.get('bars')} emptyState={empty.get('emptyState')!r} "
            "（有数据则正常渲染，无数据则走既有空态，不出现空白页）",
        )
        # Back to 最新视频 for the remaining checks.
        evaluate(
            client,
            """(() => {
              const button = Array.from(document.querySelectorAll('.profile-controls button'))
                .find((n) => n.textContent.trim() === '最新视频');
              if (button) button.click();
              return Boolean(button);
            })()""",
        )
        time.sleep(1.2)

        # ---- CRE-18: long titles ------------------------------------------------------------------
        client.call("browser_resize", {"width": 390, "height": 900}, timeout=60)
        time.sleep(1.5)
        narrow = evaluate(
            client,
            """(() => {
              const bar = document.querySelector('.video-bar-slot');
              const card = document.querySelector('.video-card');
              return {
                horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
                docWidth: document.documentElement.scrollWidth,
                innerWidth: window.innerWidth,
                barWidth: bar ? bar.getBoundingClientRect().width : 0,
                cardWidth: card ? card.getBoundingClientRect().width : 0,
                labelsClipped: Array.from(document.querySelectorAll('.video-bar-value')).some((n) => n.scrollWidth > n.clientWidth + 2 && n.clientWidth > 0),
                titlesInCards: Array.from(document.querySelectorAll('.video-card-copy strong')).every((n) => n.scrollHeight <= n.clientHeight + 2 || n.clientHeight > 0),
              };
            })()""",
        )
        check(
            "CRE-18-narrow-no-overflow",
            narrow.get("horizontalOverflow") is False
            and float(narrow.get("barWidth") or 0) > 0
            and float(narrow.get("cardWidth") or 0) > 0,
            f"390px: overflow={narrow.get('horizontalOverflow')!r} doc={narrow.get('docWidth')}px "
            f"viewport={narrow.get('innerWidth')}px bar={narrow.get('barWidth')} card={narrow.get('cardWidth')}",
        )
        screenshot(client, "CD05-library-creative-390")
        client.call("browser_resize", {"width": 1440, "height": 1400}, timeout=60)
        time.sleep(1.2)

        # ---- CRE-20: refresh ----------------------------------------------------------------------
        open_chapter(client, library_url, CREATIVE_CHAPTER)
        before_refresh = chart_state(client)
        client.call("browser_navigate", {"url": library_url}, timeout=120)
        time.sleep(3.5)
        after_refresh = tab_state(client)
        refreshed = evaluate(
            client,
            """(() => {
              const b = Array.from(document.querySelectorAll('.chapter-tabs button')).find((n) => n.textContent.trim() === '创作能力');
              if (b) b.click();
              return true;
            })()""",
        )
        time.sleep(1.8)
        after_chart = chart_state(client)
        check(
            "CRE-20-refresh-restores-data",
            refreshed
            and after_refresh["active"] == "商业能力"
            and after_chart["bars"] == before_refresh["bars"]
            and after_chart["labels"] == before_refresh["labels"]
            and after_chart["dates"] == before_refresh["dates"],
            f"刷新后默认章节={after_refresh['active']!r}，创作能力 bars={after_chart['bars']} "
            f"labels identical={after_chart['labels'] == before_refresh['labels']}",
        )

        # ---- CRE-22: the other entry point + chapter regression ------------------------------------
        navigate(client, task_url, 3500)
        task_tabs = tab_state(client)
        # 任务入口的章节数：本轮未改动「报价与历史」的既有条件（CD-04 起仅当该快照确有报价观察时
        # 才渲染），因此这里断言"要么 4 个（无报价数据）、要么 5 个（有报价数据）"，
        # 而不是把既有数据条件当成缺陷或擅自改变它。
        check(
            "CRE-01-task-tabs",
            task_tabs["tabs"] in (FOUR_TABS, FIVE_TABS) and task_tabs["tabs"][:4] == FOUR_TABS,
            f"任务入口 tabs={task_tabs['tabs']!r}（前四个固定；报价与历史沿用既有数据条件，未修改）",
        )
        check(
            "CRE-03-task-default-commercial",
            task_tabs["active"] == "商业能力",
            f"task active={task_tabs['active']!r}",
        )
        check(
            "CRE-22-task-entry-no-overview",
            task_tabs["hasOverviewTab"] is False,
            f"containsOverview={task_tabs['hasOverviewTab']!r}",
        )
        open_chapter(client, task_url, CREATIVE_CHAPTER)
        task_chart = chart_state(client)
        check(
            "CRE-22-entry-parity",
            task_chart["bars"] == chart["bars"]
            and task_chart["labels"] == chart["labels"]
            and task_chart["dates"] == chart["dates"]
            and task_chart["barLinks"] == chart["barLinks"]
            and task_chart["hasCompare"] is False,
            f"任务入口与达人库入口一致：bars={task_chart['bars']} labelsIdentical={task_chart['labels'] == chart['labels']} "
            f"datesIdentical={task_chart['dates'] == chart['dates']} linksIdentical={task_chart['barLinks'] == chart['barLinks']}",
        )
        screenshot(client, "CD05-task-latest-video-chart")

        # Regression on the neighbouring chapters of the task entry.
        for label, marker in (("履约能力", "履约与合作表现"), ("连接用户", "连接用户")):
            open_chapter(client, task_url, label)
            body = evaluate(
                client,
                """(() => ({
                  active: document.querySelector('.chapter-tabs button.active')?.textContent?.trim() || null,
                  text: (document.querySelector('.chapter-body')?.textContent || '').slice(0, 4000),
                }))()""",
            )
            check(
                f"CRE-22-regression-{label}",
                body["active"] == label and marker in body["text"] and len(body["text"]) > 40,
                f"active={body['active']!r} containsMarker={marker in body['text']} length={len(body['text'])}",
            )

        collect_observability(client)

    # Console errors / failed API requests must be empty for this round.
    # The MCP answer always opens with a summary line ("Total messages: N (Errors: M, ...)"), which is
    # not itself a console error, so it is excluded rather than counted as one.
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
        if "/api/" in line and ("500" in line or "404" in line or "failed" in line.lower())
    ]
    check(
        "CRE-22-no-console-errors",
        not error_lines,
        f"console error lines={len(error_lines)}: {error_lines[:3]!r}",
    )
    check(
        "CRE-22-no-failed-api-calls",
        not failed_api,
        f"failed API lines={len(failed_api)}: {failed_api[:3]!r}",
    )

    failed = [item for item in results if not item["passed"]]
    report = {
        "round": "CD-05",
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "base": BASE,
        "entry_points": {"library": f"{BASE}/creators/{CREATOR_ID}", "task": f"{BASE}/tasks/{TASK_ID}/creators/{CREATOR_ID}"},
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
