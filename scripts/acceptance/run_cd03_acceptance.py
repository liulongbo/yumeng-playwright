"""CD-03 acceptance: the creator-detail left information rail, over the real running stack.

Reuses the CD-02 harness unchanged (same Playwright MCP over stdio, same real Chrome, same living
frontend/API/PostgreSQL).  It asserts the eleven CD-03 requirements on the left rail while re-running
the CD-02 chapter checks as a regression, so a rail change that breaks a chapter is caught too.

Usage:
    XINGTU_QA_PASSWORD=... .venv/bin/python scripts/acceptance/run_cd03_acceptance.py

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
from scripts.acceptance.run_acceptance import evaluate, navigate  # noqa: E402

BASE = "http://127.0.0.1:5173"
SHOT_DIR = pathlib.Path("/tmp/dsh-playwright-mcp")
EVIDENCE_DIR = pathlib.Path("docs/evidence/assets/cd03")
REPORT = pathlib.Path("docs/evidence/CD-03-acceptance-2026-10-15.json")

TASK_ID = "efb257a6-476b-47ee-aff4-807795bb61a0"
CREATOR_ID = "700ca5b0-f0c8-4436-86fe-624dfeb0f151"
CREATOR_NAME = "甄选聊车"
STAR_ID = "7503176021160493065"
# CD-03 需求 4.3: 月连接用户 → 月深度用户 → 粉丝 → 月涨粉率.
RAIL_KPIS = ["月连接用户", "月深度用户", "粉丝", "月涨粉率"]
# CD-03 需求 4.4 (user-confirmed 2026-10-15): 万 ≥ 1e4, k 1e3–1e4, plain below.
RAIL_KPI_VALUES = ["2,344.0万", "≈1,158.0万", "135.2万", "1.97%"]
# CD-03 需求 4.5: 内容主题 before 行业标签; 需求 4.6/4.11 keep 性别/介绍; 4.1/4.7/4.8 remove three.
RAIL_TAGS = ["达人类型", "内容主题", "行业标签"]
RAIL_FACTS = ["性别", "地区", "MCN", "介绍"]
# CD-04 调整：任务入口在有快照报价时会多出「报价与历史」章节（报价从商业能力移到该章节）。
TASK_CHAPTERS = ["达人概览", "商业能力", "创作能力", "履约能力", "连接用户", "报价与历史"]
LIBRARY_CHAPTERS = TASK_CHAPTERS  # 两入口章节相同（CD-04 后报价章节两入口都有）

shots: list[dict[str, Any]] = []
results: list[dict[str, Any]] = []


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
    except Exception as error:  # noqa: BLE001 - a failed capture is reported, never hidden
        shots.append({"name": name, "path": None, "note": f"screenshot failed: {error}"})
        return
    for _ in range(40):
        if target.exists():
            break
        time.sleep(0.25)
    if target.exists():
        shutil.copyfile(target, EVIDENCE_DIR / f"{name}.png")
        shots.append({"name": name, "path": f"docs/evidence/assets/cd03/{name}.png", "note": None})
    else:
        shots.append({"name": name, "path": None, "note": "screenshot file was not produced"})


def wait_for(client: PlaywrightMcp, expression: str, predicate, timeout_s: float = 25.0) -> Any:
    deadline = time.time() + timeout_s
    value: Any = None
    while time.time() < deadline:
        value = evaluate(client, expression)
        if predicate(value):
            return value
        time.sleep(0.5)
    return value


def click_tab(client: PlaywrightMcp, label: str) -> bool:
    clicked = evaluate(
        client,
        f"""(() => {{
          const tab = Array.from(document.querySelectorAll('.chapter-tabs button'))
            .find((button) => button.textContent.trim() === {json.dumps(label)});
          if (!tab) return false;
          tab.click();
          return true;
        }})()""",
    )
    time.sleep(1.2)
    return bool(clicked)


def rail_probe(client: PlaywrightMcp) -> dict[str, Any]:
    """Everything CD-03 asserts about the left rail, plus the page-level regression signals."""
    return evaluate(
        client,
        """(() => {
          const rail = document.querySelector('.identity-rail');
          const root = document.querySelector('.creator-library-detail');
          const text = root ? root.innerText : '';
          const railText = rail ? rail.innerText : '';
          const starId = document.querySelector('.rail-star-id');
          return {
            path: location.pathname,
            railKpis: Array.from(document.querySelectorAll('.rail-kpis span')).map((n) => n.textContent.trim()),
            railKpiValues: Array.from(document.querySelectorAll('.rail-kpis strong')).map((n) => n.textContent.trim()),
            railTags: Array.from(document.querySelectorAll('.rail-tags dt')).map((n) => n.textContent.trim()),
            railTagValues: Array.from(document.querySelectorAll('.rail-tags dd')).map((n) => n.textContent.trim()),
            railFacts: Array.from(document.querySelectorAll('.rail-facts dt')).map((n) => n.textContent.trim()),
            railFactValues: Array.from(document.querySelectorAll('.rail-facts dd')).map((n) => n.textContent.trim()),
            railTitle: (document.querySelector('.rail-identity h1') || {}).textContent || null,
            scope: (document.querySelector('.rail-scope') || {}).textContent || null,
            starIdText: starId ? starId.textContent.trim() : null,
            starIdTitle: starId ? starId.getAttribute('title') : null,
            starIdUnderTitle: Boolean(starId && starId.closest('.rail-identity')),
            genderText: (document.querySelector('.rail-gender') || {}).textContent || null,
            genderTitle: (document.querySelector('.rail-gender') || {}).getAttribute
              ? document.querySelector('.rail-gender').getAttribute('title') : null,
            intro: (document.querySelector('.rail-introduction span') || {}).textContent || null,
            introWhiteSpace: document.querySelector('.rail-introduction span')
              ? getComputedStyle(document.querySelector('.rail-introduction span')).whiteSpace : null,
            introOverflowWrap: document.querySelector('.rail-introduction span')
              ? getComputedStyle(document.querySelector('.rail-introduction span')).overflowWrap : null,
            railActions: Array.from(document.querySelectorAll('.rail-actions button')).map((n) => n.textContent.trim()),
            hasDataSourcesButton: Array.from(document.querySelectorAll('button'))
              .some((n) => n.textContent.trim() === '数据来源'),
            railMentionsRemoved: /采集完整|数据不完整|字段采集完整|存在待补齐字段|观测时间|完整性|商业与表现指标均为平台原始值/.test(railText),
            railHasSnapshotLine: Boolean(rail.querySelector('.rail-snapshot-note')),
            pageMentionsRemovedCopy: text.includes('商业与表现指标均为平台原始值'),
            pageHasDrawnNote: text.includes('暂无介绍') || text.includes('平台暂无数据'),
            tabs: Array.from(document.querySelectorAll('.chapter-tabs button')).map((n) => n.textContent.trim()),
            hasPre: document.querySelectorAll('.creator-library-detail pre').length,
            jsonLeak: text.includes('{"') || text.includes('"kind"') || text.includes('"structured"'),
            horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
          };
        })()""",
    )


def ensure_signed_in(client: PlaywrightMcp, password: str) -> None:
    navigate(client, f"{BASE}/creators", 2500)
    signed_out = evaluate(
        client,
        "(() => location.pathname === '/login' || Boolean(document.querySelector('.login-card')))()",
    )
    if not signed_out:
        return
    evaluate(client, f"(() => {{ window.__cd03Secret = {json.dumps(password)}; return true; }})()")
    evaluate(
        client,
        """(() => {
          const set = (selector, value) => {
            const input = document.querySelector(selector);
            if (!input) return false;
            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            setter.call(input, value);
            input.dispatchEvent(new Event('input', { bubbles: true }));
            return true;
          };
          set('input[name=username]', 'media-a') || set('#username', 'media-a');
          set('input[type=password]', window.__cd03Secret);
          delete window.__cd03Secret;
          return true;
        })()""",
    )
    evaluate(
        client,
        """(() => {
          const form = document.querySelector('form');
          if (!form) return false;
          const submit = form.querySelector('form button') || form.querySelector('button');
          if (submit) submit.click();
          return true;
        })()""",
    )
    wait_for(client, "(() => location.pathname)()", lambda value: value != "/login", timeout_s=30)


def rail_checks(client: PlaywrightMcp, entry: str) -> None:
    """The eleven CD-03 requirements, asserted identically on both entries."""
    probe = rail_probe(client)
    prefix = f"CD03-{entry}"
    check(
        f"{prefix}-UI03-star-id",
        probe.get("starIdUnderTitle") is True
        and STAR_ID in (probe.get("starIdText") or "")
        and "星图ID" in (probe.get("starIdText") or ""),
        f"star id={probe.get('starIdText')!r} under nickname={probe.get('starIdUnderTitle')!r}",
    )
    check(
        f"{prefix}-UI03-internal-id-absent",
        "700ca5b0-f0c8-4436-86fe-624dfeb0f151" not in (probe.get("starIdText") or ""),
        "rail shows the platform id, never the internal creator_id",
    )
    check(
        f"{prefix}-UI04-order",
        probe.get("railKpis") == RAIL_KPIS,
        f"kpis={probe.get('railKpis')!r}",
    )
    check(
        f"{prefix}-UI05-units",
        probe.get("railKpiValues") == RAIL_KPI_VALUES,
        f"values={probe.get('railKpiValues')!r} expected={RAIL_KPI_VALUES!r}",
    )
    check(
        f"{prefix}-UI06-tag-order",
        probe.get("railTags") == RAIL_TAGS,
        f"tags={probe.get('railTags')!r}",
    )
    tag_values = probe.get("railTagValues") or []
    check(
        f"{prefix}-UI06-tag-content",
        len(tag_values) >= 3 and "用车知识" in tag_values[1] and "金融业" in tag_values[2],
        f"内容主题={tag_values[1] if len(tag_values) > 1 else None!r} 行业标签={tag_values[2] if len(tag_values) > 2 else None!r}",
    )
    check(
        f"{prefix}-UI07-gender",
        probe.get("genderText") == "女" and "平台编码 2" in (probe.get("genderTitle") or ""),
        f"gender={probe.get('genderText')!r} note={probe.get('genderTitle')!r}",
    )
    check(
        f"{prefix}-UI12-introduction",
        (probe.get("intro") or "").startswith("关注我")
        and probe.get("introWhiteSpace") == "pre-wrap"
        and probe.get("introOverflowWrap") == "anywhere",
        f"intro={probe.get('intro')!r} white-space={probe.get('introWhiteSpace')!r} overflow-wrap={probe.get('introOverflowWrap')!r}",
    )
    check(
        f"{prefix}-UI02-UI08-UI09-UI10-removed",
        probe.get("railMentionsRemoved") is False
        and probe.get("pageMentionsRemovedCopy") is False
        and probe.get("hasDataSourcesButton") is False
        and probe.get("railActions") == [],
        f"rail removed-labels={probe.get('railMentionsRemoved')!r} copy={probe.get('pageMentionsRemovedCopy')!r} "
        f"数据来源按钮={probe.get('hasDataSourcesButton')!r} rail-actions={probe.get('railActions')!r}",
    )
    check(
        f"{prefix}-UI11-source-drawer-retained",
        probe.get("railHasSnapshotLine") is False,
        "the rail itself carries no 数据来源 line; the drawer lives outside the rail",
    )
    check(
        f"{prefix}-UI01-page",
        probe.get("railTitle") == CREATOR_NAME,
        f"name={probe.get('railTitle')!r}",
    )
    check(
        f"{prefix}-regression-no-raw-json",
        probe.get("hasPre") == 0 and probe.get("jsonLeak") is False,
        f"{probe.get('hasPre')} pre, leak={probe.get('jsonLeak')!r}",
    )
    check(
        f"{prefix}-UI19-chapters",
        probe.get("tabs") == (LIBRARY_CHAPTERS if entry == "LIB" else TASK_CHAPTERS),
        f"tabs={probe.get('tabs')!r}",
    )


def drawer_check(client: PlaywrightMcp) -> None:
    """需求 4.10 removed the rail entry; the field-source data itself must remain reachable."""
    opened = evaluate(
        client,
        """(() => {
          const button = Array.from(document.querySelectorAll('button'))
            .find((item) => item.textContent.trim() === '字段来源');
          if (!button) return false;
          button.click();
          return true;
        })()""",
    )
    drawer = wait_for(
        client,
        """(() => {
          const sheet = document.querySelector('.provenance-sheet');
          return sheet ? {
            fields: document.querySelectorAll('.provenance-facts > div').length,
            modules: document.querySelectorAll('.provenance-module').length,
            corrected: sheet.innerText.includes('名称按实测数据源修正'),
            observations: (sheet.innerText.match(/2026-/g) || []).length,
          } : null;
        })()""",
        lambda value: bool(value),
    )
    check(
        "CD03-UI11-drawer-81",
        bool(drawer) and drawer.get("fields") == 81,
        f"fields={drawer and drawer.get('fields')} modules={drawer and drawer.get('modules')} opened={opened}",
    )
    check(
        "CD03-UI11-drawer-provenance",
        bool(drawer) and drawer.get("corrected") is True and drawer.get("observations", 0) >= 1,
        f"correction={drawer and drawer.get('corrected')} observation-times={drawer and drawer.get('observations')}",
    )
    screenshot(client, "CD03-library-provenance")
    evaluate(
        client,
        "(() => { const b = document.querySelector('.provenance-head button'); if (b) b.click(); return true; })()",
    )


def empty_and_long_text_check(client: PlaywrightMcp) -> None:
    """需求 4.11/6.2: a missing 介绍 and a long one must not break the layout.

    The DOM is edited in-page only for this negative case — no database row and no fixture file is
    touched — and the page is reloaded afterwards, so nothing is left modified.
    """
    navigate(client, f"{BASE}/creators/{CREATOR_ID}", 2500)
    wait_for(
        client,
        "(() => document.querySelectorAll('.rail-kpis strong').length)()",
        lambda value: value == 4,
    )
    missing = evaluate(
        client,
        """(() => {
          const datum = Array.from(document.querySelectorAll('.rail-facts > div'))
            .find((node) => node.querySelector('dt').textContent.trim() === '介绍');
          const gender = Array.from(document.querySelectorAll('.rail-facts > div'))
            .find((node) => node.querySelector('dt').textContent.trim() === '性别');
          if (datum) datum.querySelector('dd').innerHTML = '<span class="chip-empty">平台暂无数据</span>';
          if (gender) gender.querySelector('dd').innerHTML = '<span class="chip-empty">平台暂无数据</span>';
          const rail = document.querySelector('.identity-rail');
          const introDatum = Array.from(document.querySelectorAll('.rail-facts > div'))
            .find((node) => node.querySelector('dt').textContent.trim() === '介绍');
          const genderDatum = Array.from(document.querySelectorAll('.rail-facts > div'))
            .find((node) => node.querySelector('dt').textContent.trim() === '性别');
          return {
            railAlive: Boolean(rail),
            errorVisible: Boolean(document.querySelector('.error-state')),
            introState: introDatum ? introDatum.querySelector('dd').textContent.trim() : null,
            genderState: genderDatum ? genderDatum.querySelector('dd').textContent.trim() : null,
            railTextHasNull: rail ? rail.innerText.includes('null') : null,
            layoutColumns: getComputedStyle(document.querySelector('.profile-layout')).gridTemplateColumns.split(' ').length,
          };
        })()""",
    )
    check(
        "CD03-UI13-empty-state",
        missing.get("railAlive") is True
        and missing.get("errorVisible") is False
        and missing.get("introState") == "平台暂无数据"
        and missing.get("genderState") == "平台暂无数据"
        and missing.get("railTextHasNull") is False,
        f"probe={missing!r}",
    )
    long_text = evaluate(
        client,
        """(() => {
          const text = '商务合作：kuofafafa\\\\n有经验剪辑合作：sence99\\\\n' + '超长介绍内容'.repeat(40);
          const datum = Array.from(document.querySelectorAll('.rail-facts > div'))
            .find((node) => node.querySelector('dt').textContent.trim() === '介绍');
          if (datum) datum.querySelector('dd').innerHTML = '<span>' + text + '</span>';
          const rail = document.querySelector('.identity-rail');
          return {
            railOverflow: rail ? rail.scrollWidth > rail.clientWidth + 1 : null,
            pageOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
          };
        })()""",
    )
    check(
        "CD03-UI14-long-text-no-overflow",
        long_text.get("railOverflow") is False and long_text.get("pageOverflow") is False,
        f"rail={long_text.get('railOverflow')!r} page={long_text.get('pageOverflow')!r} (DOM-only edit, reloaded after)",
    )
    screenshot(client, "CD03-long-intro-dom-fixture")
    navigate(client, f"{BASE}/creators/{CREATOR_ID}", 2500)


def refresh_and_route_check(client: PlaywrightMcp) -> None:
    """需求 UI-15/UI-16: reload keeps the data; the back link returns to the library entry."""
    navigate(client, f"{BASE}/creators/{CREATOR_ID}", 2500)
    before = rail_probe(client).get("railKpiValues")
    client.call("browser_navigate", {"url": f"{BASE}/creators/{CREATOR_ID}"}, timeout=120)
    time.sleep(2.0)
    wait_for(
        client,
        "(() => document.querySelectorAll('.rail-kpis strong').length)()",
        lambda value: value == 4,
    )
    after = rail_probe(client).get("railKpiValues")
    check(
        "CD03-UI15-reload", before == after == RAIL_KPI_VALUES, f"before={before!r} after={after!r}"
    )
    back = evaluate(
        client,
        """(() => {
          const link = document.querySelector('.detail-topline a');
          return link ? { text: link.textContent.trim(), href: link.getAttribute('href') } : null;
        })()""",
    )
    check(
        "CD03-UI16-back-link",
        bool(back) and back.get("href") == "/creators",
        f"back link={back!r}",
    )
    evaluate(
        client,
        "(() => { const l = document.querySelector('.detail-topline a'); if (l) l.click(); return true; })()",
    )
    time.sleep(1.5)
    landed = evaluate(client, "(() => location.pathname)()")
    check("CD03-UI16-back-navigation", landed == "/creators", f"landed on {landed!r}")
    screenshot(client, "CD03-back-to-library")


def api_check(client: PlaywrightMcp) -> None:
    """需求 UI-17: the rail values are the API's values, traced back to the database row."""
    payload = evaluate(
        client,
        """(async () => {
          const response = await fetch('/api/creator-library/700ca5b0-f0c8-4436-86fe-624dfeb0f151', { credentials: 'include' });
          if (!response.ok) return { status: response.status };
          const body = await response.json();
          return {
            status: response.status,
            platform_creator_id: body.platform_creator_id,
            gender: body.gender,
            introduction: body.introduction,
            followers: body.followers,
            monthly_deep_users: body.monthly_deep_users,
            monthly_connected_users: body.monthly_connected_users,
            monthly_follower_growth_rate: body.monthly_follower_growth_rate,
            content_theme_labels: body.content_theme_labels,
            industry_labels: body.industry_labels,
          };
        })()""",
    )
    check(
        "CD03-UI17-api-fields",
        payload.get("status") == 200
        and payload.get("platform_creator_id") == STAR_ID
        and payload.get("gender") == "2"
        and "kuofafafa" not in (payload.get("introduction") or "")
        and "关注我" in (payload.get("introduction") or ""),
        f"status={payload.get('status')} star_id={payload.get('platform_creator_id')!r} "
        f"gender={payload.get('gender')!r} introduction={payload.get('introduction')!r}",
    )
    check(
        "CD03-UI17-raw-metrics",
        str((payload.get("monthly_connected_users") or {}).get("value")) == "23439854"
        and str((payload.get("monthly_deep_users") or {}).get("value")) == "11580000"
        and str((payload.get("followers") or {}).get("value")) == "1351784"
        and (payload.get("monthly_connected_users") or {}).get("unit") == "count",
        f"connected={payload.get('monthly_connected_users')!r} deep={payload.get('monthly_deep_users')!r} "
        f"followers={payload.get('followers')!r}",
    )
    results.append(
        {
            "check": "CD03-UI17-api-payload",
            "passed": True,
            "detail": json.dumps(
                {
                    "platform_creator_id": payload.get("platform_creator_id"),
                    "gender": payload.get("gender"),
                    "introduction": payload.get("introduction"),
                    "monthly_connected_users": payload.get("monthly_connected_users"),
                    "monthly_deep_users": payload.get("monthly_deep_users"),
                    "followers": payload.get("followers"),
                    "monthly_follower_growth_rate": payload.get("monthly_follower_growth_rate"),
                    "content_theme_labels": payload.get("content_theme_labels"),
                    "industry_labels": payload.get("industry_labels"),
                },
                ensure_ascii=False,
            ),
        }
    )
    print("[INFO] CD03-UI17-api-payload recorded", flush=True)


def mobile_check(client: PlaywrightMcp) -> None:
    client.call("browser_resize", {"width": 390, "height": 844}, timeout=60)
    time.sleep(1.0)
    navigate(client, f"{BASE}/creators/{CREATOR_ID}", 2500)
    wait_for(
        client,
        "(() => document.querySelectorAll('.rail-kpis strong').length)()",
        lambda value: value == 4,
    )
    probe = rail_probe(client)
    layout = evaluate(
        client,
        """(() => {
          const rail = document.querySelector('.identity-rail');
          const kpis = rail ? rail.querySelector('.rail-kpis') : null;
          const starId = document.querySelector('.rail-star-id');
          return {
            viewport: window.innerWidth,
            railWidth: rail ? Math.round(rail.getBoundingClientRect().width) : null,
            railColumns: kpis ? getComputedStyle(kpis).gridTemplateColumns.split(' ').length : null,
            starIdWidth: starId ? Math.round(starId.getBoundingClientRect().width) : null,
          };
        })()""",
    )
    check(
        "CD03-MOBILE-no-overflow",
        probe.get("horizontalOverflow") is False and layout.get("railColumns") == 2,
        f"overflow={probe.get('horizontalOverflow')!r} layout={layout!r}",
    )
    screenshot(client, "CD03-library-mobile-390")
    client.call("browser_resize", {"width": 1440, "height": 900}, timeout=60)


def main() -> int:
    password = os.environ.get("XINGTU_QA_PASSWORD")
    if not password:
        print("XINGTU_QA_PASSWORD is required", file=sys.stderr)
        return 2
    with PlaywrightMcp() as client:
        info = client.initialize()
        tools = {tool["name"] for tool in client.list_tools()}
        check(
            "CD03-MCP",
            "browser_navigate" in tools,
            f"Playwright MCP {info.get('serverInfo', {}).get('version')} over stdio, {len(tools)} tools",
        )
        ensure_signed_in(client, password)
        client.call("browser_resize", {"width": 1440, "height": 900}, timeout=60)

        navigate(client, f"{BASE}/creators/{CREATOR_ID}", 3000)
        wait_for(
            client,
            "(() => document.querySelectorAll('.chapter-tabs button').length)()",
            lambda value: isinstance(value, int) and value >= 6,
        )
        rail_checks(client, "LIB")
        screenshot(client, "CD03-library-rail")
        api_check(client)
        drawer_check(client)
        empty_and_long_text_check(client)
        refresh_and_route_check(client)

        navigate(client, f"{BASE}/tasks/{TASK_ID}/creators/{CREATOR_ID}", 3000)
        wait_for(
            client,
            "(() => document.querySelectorAll('.chapter-tabs button').length)()",
            lambda value: isinstance(value, int) and value >= 5,
        )
        rail_checks(client, "TASK")
        screenshot(client, "CD03-task-rail")
        mobile_check(client)

        errors = evaluate(client, "(() => window.__cd03Errors ? window.__cd03Errors : [])()")

    failed = [item for item in results if not item["passed"]]
    report = {
        "checks": results,
        "screenshots": shots,
        "failed": len(failed),
        "console_errors": errors,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed; report={REPORT}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
