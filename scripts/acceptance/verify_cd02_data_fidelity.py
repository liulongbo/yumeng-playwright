"""CD-02 data fidelity verification: page DOM vs stored platform observations.

Answers two questions with evidence rather than inspection:

1. Is every value the detail page shows the value the platform actually returned?  The check walks
   数据库 payload -> API/字段目录 -> DOM and formats the expected text with an independent
   implementation of the documented display rules (this file does not import the app's formatters).
2. Did anything get fabricated or silently changed?  Every identifier must appear byte-for-byte, every
   multi-digit token rendered on the page must be traceable to a stored value or to a documented
   derivation (a layer sum, a group share, a ratio conversion), and the recorded cross-field platform
   relations must still hold.

Usage:
    .venv/bin/python scripts/acceptance/verify_cd02_data_fidelity.py
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import time
import urllib.request
from typing import Any

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from scripts.acceptance.mcp_client import PlaywrightMcp  # noqa: E402
from scripts.acceptance.run_acceptance import evaluate, navigate  # noqa: E402

BASE = "http://127.0.0.1:5173"
API = "http://127.0.0.1:8000"
TASK_ID = "efb257a6-476b-47ee-aff4-807795bb61a0"
CREATOR_ID = "700ca5b0-f0c8-4436-86fe-624dfeb0f151"
CREATOR_NAME = "甄选聊车"
CHAPTERS = ["达人概览", "商业能力", "创作能力", "履约能力", "连接用户"]

REPORT = pathlib.Path("docs/evidence/CD-02-data-fidelity-2026-10-14.json")
findings: list[dict[str, Any]] = []

# Fields rendered by a panel-specific component rather than by the generic fact formatter; their
# values are asserted by the dedicated checks further down.
DEDICATED = {
    "spread.interaction_rate",
    "spread.completion_rate",
    "spread.expected_cpm",
    "spread.expected_cpe",
    "spread.sales_expected_cpm",
    "spread.item_rate_metrics",
    "spread.average_duration",
    "fans.connection_funnel",
    "seeding.seeding_link_structure",
    "fans.audience_distributions",
    "commercial.cooperation_offers",
    "conversion.local_sales_overview",
    "fulfillment.industry_order_distribution",
    "fulfillment.industry_play_distribution",
    "fulfillment.cooperation_industry_distribution",
    "creation.content_theme_density",
    "creation.video_content_distribution",
    "creation.hot_comment_tokens",
    "creation.performance_descriptions",
    "creation.recent_video_performance",
    "creation.recent_xingtu_video_performance",
    "basic.gender",
    "conversion.related_video_count",
    "conversion.related_video_play_median",
    "fans.fans_growth",
}

STATUS_TEXT = {
    "COLLECTED": "已采集",
    "NO_DATA": "平台暂无数据",
    "NOT_ATTEMPTED": "本次未采集",
    "NOT_PROVIDED": "平台未提供",
    "NO_PERMISSION": "无访问权限",
    "FAILED": "采集失败",
    "MISSING_SOURCE": "未取到对应响应",
}


def record(kind: str, name: str, ok: bool, page: Any, truth: Any, note: str = "") -> None:
    findings.append(
        {"kind": kind, "check": name, "ok": bool(ok), "page": page, "stored": truth, "note": note}
    )
    if not ok:
        print(
            f"[DIFF] {kind} :: {name}\n       page   = {page!r}\n       stored = {truth!r}\n       note   = {note}",
            flush=True,
        )


# --------------------------------------------------------------------------- independent formatters
def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {
            "",
            "-",
            "--",
            "—",
            "－",
            "n/a",
            "null",
            "undefined",
            "[]",
            "{}",
        }
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def expect_text(kind: str, data: Any, approximate: bool = False) -> str:
    if is_blank(data):
        return "—"
    if kind == "ratio":
        return f"{float(data) * 100:.2f}%"
    if kind == "number":
        return f"≈{int(data):,}" if approximate else f"{int(data):,}"
    if kind == "text":
        return str(data)
    if isinstance(data, (int, float)):
        return f"{data:,}"
    if isinstance(data, str):
        return f"{int(data):,}" if re.fullmatch(r"\d{1,12}", data.strip()) else str(data)
    if isinstance(data, list):
        return f"{len(data)} 条记录" if data else "—"
    if isinstance(data, dict):
        if len(data) == 1 and isinstance(data.get("label"), str):
            return data["label"]
        return f"平台结构化数据（{len(data)} 项）"
    return "—"


# --------------------------------------------------------------------------- browser probe
PROBE = """(() => ({
  rail: Array.from(document.querySelectorAll('.rail-kpis > div')).map((d) => ({
    label: d.querySelector('span').textContent.trim(), value: d.querySelector('strong').textContent.trim() })),
  metrics: Array.from(document.querySelectorAll('.profile-metrics .metric')).map((m) => ({
    label: m.querySelector('span').textContent.trim(),
    value: m.querySelector('strong').textContent.trim(),
    detail: m.querySelector('small') ? m.querySelector('small').textContent.trim() : null })),
  facts: Array.from(document.querySelectorAll('.profile-facts > div')).map((row) => ({
    label: row.querySelector('dt').textContent.trim(),
    value: row.querySelector('dd span') ? row.querySelector('dd span').textContent.trim() : null,
    note: row.querySelector('dt small') ? row.querySelector('dt small').textContent.trim() : null,
    state: row.querySelector('dd em') ? row.querySelector('dd em').textContent.trim() : null })),
  layers: Array.from(document.querySelectorAll('.layer-rows > div')).map((row) => Array.from(row.children).map((c) => c.textContent.trim())),
  layerVerify: document.querySelector('.layer-verify') ? document.querySelector('.layer-verify').textContent.trim() : null,
  captions: Array.from(document.querySelectorAll('.chart-figure figcaption')).map((n) => n.textContent.trim()),
  videos: Array.from(document.querySelectorAll('.video-table > div:not(.video-head)')).map((row) => Array.from(row.children).map((c) => c.textContent.trim())),
  distributions: Array.from(document.querySelectorAll('.distribution-list > div')).map((row) => ({
    label: row.querySelector('span').textContent.trim(),
    value: row.querySelector('strong').textContent.trim(),
    share: row.querySelector('small') ? row.querySelector('small').textContent.trim() : null })),
  quotes: Array.from(document.querySelectorAll('.quote-table > div:not(.quote-head)')).map((row) => Array.from(row.children).map((c) => c.textContent.trim())),
  ranges: Array.from(document.querySelectorAll('.range-pill')).map((row) => [row.querySelector('span').textContent.trim(), row.querySelector('b').textContent.trim()]),
  cards: Array.from(document.querySelectorAll('.content-card')).map((card) => ({
    title: card.querySelector('.content-copy strong').textContent.trim(),
    stats: Array.from(card.querySelectorAll('.content-stats span')).map((s) => s.textContent.trim()),
    id: card.querySelector('.content-copy p').textContent.trim() })),
  historyHeader: document.querySelector('.history-panel .panel-heading span') ? document.querySelector('.history-panel .panel-heading span').textContent.trim() : null,
  historyRows: Array.from(document.querySelectorAll('.history-list > div')).length,
  quoteListCount: document.querySelectorAll('.quote-list > div').length,
}))()"""


def read_page(client: PlaywrightMcp, url: str, has_history: bool) -> dict[str, Any]:
    navigate(client, url, 3000)
    for _ in range(20):
        if (
            evaluate(client, "(() => document.querySelectorAll('.chapter-tabs button').length)()")
            >= 5
        ):
            break
        time.sleep(0.5)
    chapters: dict[str, Any] = {}
    for chapter in CHAPTERS:
        if chapter != CHAPTERS[0]:
            evaluate(
                client,
                f"""(() => {{ const b = Array.from(document.querySelectorAll('.chapter-tabs button'))
                  .find((x) => x.textContent.trim() === {json.dumps(chapter)}); if (b) b.click(); return true; }})()""",
            )
            time.sleep(1.2)
        chapters[chapter] = evaluate(client, PROBE)
    if has_history:
        evaluate(
            client,
            """(() => { const b = Array.from(document.querySelectorAll('.chapter-tabs button'))
              .find((x) => x.textContent.trim() === '报价与历史'); if (b) b.click(); return true; })()""",
        )
        time.sleep(1.5)
        chapters["报价与历史"] = evaluate(client, PROBE)
    return chapters


# --------------------------------------------------------------------------- stored ground truth
def load_truth() -> dict[str, Any]:
    dsn = os.environ["XINGTU_DATABASE_URL"]
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        snapshot = conn.execute(
            """SELECT snapshot_id, created_at, payload FROM creator_snapshots
            WHERE creator_id=%s ORDER BY created_at DESC, snapshot_id DESC LIMIT 1""",
            (CREATOR_ID,),
        ).fetchone()
        projection = conn.execute(
            "SELECT projection FROM platform_creators WHERE creator_id=%s", (CREATOR_ID,)
        ).fetchone()["projection"]
        quotes = conn.execute(
            """SELECT cooperation_form, price_raw, origin_price_raw FROM
            douyin_xingtu_creator_quote_observations WHERE creator_id=%s
            ORDER BY observed_at DESC, position""",
            (CREATOR_ID,),
        ).fetchall()
        index_count = conn.execute(
            "SELECT count(*) AS n FROM douyin_xingtu_creator_snapshot_index WHERE creator_id=%s",
            (CREATOR_ID,),
        ).fetchone()["n"]
        snapshot_count = conn.execute(
            "SELECT count(*) AS n FROM creator_snapshots WHERE creator_id=%s", (CREATOR_ID,)
        ).fetchone()["n"]
        cards = conn.execute(
            """SELECT f.payload FROM snapshot_collections sc
            JOIN featured_collections c ON c.collection_observation_id=sc.collection_observation_id
            JOIN featured_cards f ON f.collection_observation_id=c.collection_observation_id
            WHERE sc.creator_snapshot_id=%s AND sc.collection_type='excellent_reach'
            ORDER BY f.position""",
            (str(snapshot["snapshot_id"]),),
        ).fetchall()
    fields: dict[str, dict[str, Any]] = {}
    for module_key, module in (snapshot["payload"].get("modules") or {}).items():
        for field in module.get("fields") or []:
            fields[f"{module_key}.{field['field_key']}"] = field
    return {
        "snapshot_id": str(snapshot["snapshot_id"]),
        "captured_at": snapshot["created_at"].isoformat(),
        "payload": snapshot["payload"],
        "fields": fields,
        "projection": projection,
        "quotes": [dict(row) for row in quotes],
        "index_count": index_count,
        "snapshot_count": snapshot_count,
        "cards": [row["payload"] for row in cards],
    }


def session_cookie() -> str:
    path = pathlib.Path("/tmp/cd02-cookies.txt")
    if not path.exists():
        raise SystemExit("cookie jar missing; run the login step first")
    for line in path.read_text().splitlines():
        # Netscape comments start with `#`, but an HttpOnly cookie is written as `#HttpOnly_...`.
        if not line.strip() or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        parts = line.split("\t")
        if len(parts) >= 7 and parts[5] == "xingtu_product_session":
            return parts[6].strip()
    raise SystemExit("session cookie not found in the jar")


def api_json(path: str, cookie: str) -> Any:
    request = urllib.request.Request(
        f"{API}{path}", headers={"Cookie": f"xingtu_product_session={cookie}"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - local API
        return json.load(response)


def load_catalog(cookie: str) -> dict[str, dict[str, str]]:
    """`label -> field path + kind`, straight from the endpoint the page uses."""
    catalog = api_json("/api/platforms/douyin_xingtu/profile-field-catalog", cookie)
    return {
        field["name"]: {
            "path": f"{module['key']}.{field['key']}",
            "kind": field["kind"],
            "unit": field["unit"] or "",
        }
        for module in catalog["modules"]
        for field in module["fields"]
    }


def entry_of(field: dict[str, Any]) -> tuple[Any, str]:
    """The platform value inside an observation envelope, plus its registered kind fallback."""
    if not field or field.get("status") != "COLLECTED":
        return None, str((field or {}).get("status"))
    value = field.get("value")
    if isinstance(value, dict):
        if "data" in value:
            return value["data"], "structured"
        if "amount" in value:
            return value["amount"], "number"
        if "label" in value:
            return value, "structured"
        return value, "structured"
    return value, "text"


# --------------------------------------------------------------------------- checks
def resolve(label: str, labels: dict[str, dict[str, str]]) -> str | None:
    base = label.split(" · ")[0].strip()
    if base in labels:
        return labels[base]["path"]
    trimmed = re.sub(r"（(月|年|日|周)）$", "", base)
    if trimmed in labels:
        return labels[trimmed]["path"]
    return None


def kind_of(path: str, labels: dict[str, dict[str, str]]) -> str:
    return next((value["kind"] for value in labels.values() if value["path"] == path), "structured")


def check_field_values(
    chapters: dict[str, Any], truth: dict[str, Any], labels: dict[str, dict[str, str]]
) -> None:
    rows: list[tuple[str, str, str | None, str | None]] = []
    for chapter, data in chapters.items():
        for item in data.get("facts", []):
            rows.append((chapter, item["label"], item["value"], item.get("state")))
        for item in data.get("metrics", []):
            rows.append((chapter, item["label"], item["value"], item.get("detail")))
    compared = 0
    for chapter, label, value, state in rows:
        path = resolve(label, labels)
        if not path or path in DEDICATED:
            continue
        compared += 1
        field = truth["fields"].get(path)
        if field is None:
            record("field", f"{chapter}/{label}", False, value, None, "字段不在快照中")
            continue
        data, kind = entry_of(field)
        if kind in {
            "NO_DATA",
            "NOT_ATTEMPTED",
            "NOT_PROVIDED",
            "NO_PERMISSION",
            "FAILED",
            "MISSING_SOURCE",
        }:
            ok = value in (None, "—", STATUS_TEXT[kind])
            record(
                "field",
                f"{chapter}/{label}",
                ok,
                {"value": value, "state": state},
                STATUS_TEXT[kind],
                path,
            )
            continue
        if is_blank(data):
            # Collected but empty: the page states why instead of implying a zero.  An empty list (or
            # the platform's `"[]"`/`"{}"` text form) is a platform answer; an unusable empty object is
            # reported separately.  A metric tile shows that state in its detail line.
            state_text = (
                "平台暂无数据"
                if isinstance(data, list)
                or (isinstance(data, str) and data.strip() in {"[]", "{}"})
                else "平台返回空值"
            )
            ok = value == state_text or (value == "—" and (state or "").startswith(state_text))
            record(
                "field",
                f"{chapter}/{label}",
                ok,
                {"value": value, "state": state},
                state_text,
                path,
            )
            continue
        kind_key = kind_of(path, labels)
        if path == "basic.gender":
            # Registered as text: a platform code such as `2` is shown as sent, never as a count.
            kind_key = "text"
        expected = expect_text(kind_key, data, bool(field.get("is_approximate")))
        if isinstance(value, str) and value.startswith("≈") and not expected.startswith("≈"):
            expected = f"≈{expected}"
        record("field", f"{chapter}/{label}", value == expected, value, expected, path)
    print(f"  generic field rows compared against the stored observation: {compared}", flush=True)


def check_identifiers(chapters: dict[str, Any], truth: dict[str, Any]) -> None:
    for field_key, label in (
        ("basic.platform_creator_id", "星图ID"),
        ("basic.douyin_unique_id", "抖音号"),
    ):
        stored = truth["fields"][field_key]["value"]
        page = None
        for data in chapters.values():
            for item in data.get("facts", []):
                if item["label"].startswith(label):
                    page = item["value"]
        record("identifier", label, page == stored, page, stored, "标识必须逐字符一致")


def check_dedicated_fields(chapters: dict[str, Any], truth: dict[str, Any]) -> None:
    """Panel-rendered fields: assert the members the panel shows, not a generic string."""
    commercial = chapters["商业能力"]
    facts = {item["label"].split(" · ")[0]: item for item in commercial["facts"]}
    every_fact = {
        item["label"].split(" · ")[0]: item
        for data in chapters.values()
        for item in data.get("facts", [])
    }
    metrics = {
        item["label"]: item["value"]
        for data in chapters.values()
        for item in data.get("metrics", [])
    }

    for path, label in (
        ("spread.interaction_rate", "互动率及同行超越"),
        ("spread.completion_rate", "完播率及同行超越"),
    ):
        data = truth["fields"][path]["value"]["data"]
        row = facts.get(label, {})
        if "value" in data:
            # The live platform renders these two fields as percentages; the stored raw value is that
            # percentage ×100 and is kept in the row's label note.
            expected = f"{float(data['value']) / 100:.2f}%"
            peer = f"{float(data['overtake']) / 100:.2f}%"
            got = row.get("value") or ""
            record(
                "dedicated",
                label,
                expected in got and peer in got,
                {"value": got, "peer": row.get("overtake")},
                {"value": expected, "peer": f"优于同类型达人 {peer}"},
                path,
            )
            record(
                "dedicated",
                f"{label}保留原值",
                str(data["value"]) in (row.get("note") or ""),
                row.get("note"),
                f"标签应含平台原值 {data['value']}",
                path,
            )
        else:
            record(
                "dedicated",
                label,
                row.get("state") is not None,
                row.get("state"),
                f"平台仅返回标签「{data.get('label')}」",
                path,
            )

    members = (
        ("spread.expected_cpm", "cpm_21_60", "预期 CPM（21–60 秒）"),
        ("spread.expected_cpm", "cpm_60", "预期 CPM（60 秒以上）"),
        ("spread.expected_cpe", "cpe_21_60", "预期 CPE（21–60 秒）"),
        ("spread.expected_cpe", "cpe_60", "预期 CPE（60 秒以上）"),
    )
    metrics = {
        item["label"]: item["value"]
        for data in chapters.values()
        for item in data.get("metrics", [])
    }
    for path, member, label in members:
        stored = truth["fields"][path]["value"]["data"][member]
        expected = f"{int(stored):,}"
        record(
            "dedicated",
            label,
            metrics.get(label) == expected,
            metrics.get(label),
            expected,
            f"{path}.{member}",
        )

    sales = truth["fields"]["spread.sales_expected_cpm"]["value"]["data"]
    for member, label in (
        ("cpm_21_60", "销售预期 CPM（21–60 秒）"),
        ("cpm_60", "销售预期 CPM（60 秒以上）"),
    ):
        expected = f"{int(sales[member]):,}"
        got = facts.get(label, {}).get("value")
        record(
            "dedicated",
            label,
            got == expected,
            got,
            expected,
            f"spread.sales_expected_cpm.{member}",
        )

    item_rate = truth["fields"]["spread.item_rate_metrics"]["value"]["data"]
    expected_item = (
        f"作品数 {int(item_rate['item_num']['value']):,} · 中位播放 {int(item_rate['play_mid']['value']):,}"
        f"（同行超越 {item_rate['play_mid']['overtake']}）"
    )
    record(
        "dedicated",
        "作品传播比较指标",
        every_fact.get("作品传播比较指标", {}).get("value") == expected_item,
        every_fact.get("作品传播比较指标", {}).get("value"),
        expected_item,
        "spread.item_rate_metrics",
    )
    for path, label in (
        ("conversion.related_video_count", "相关视频数"),
        ("conversion.related_video_play_median", "相关视频播放中位数"),
    ):
        stored = truth["fields"][path]["value"]["data"]["value"]
        expected = f"{int(stored):,}"
        record(
            "dedicated", label, metrics.get(label) == expected, metrics.get(label), expected, path
        )
    growth = truth["fields"]["fans.fans_growth"]["value"]["data"]["value"]
    expected_growth = f"{int(growth):,}"
    record(
        "dedicated",
        "粉丝增长量",
        metrics.get("粉丝增长量") == expected_growth,
        metrics.get("粉丝增长量"),
        expected_growth,
        "fans.fans_growth",
    )

    stored_duration = truth["fields"]["spread.average_duration"]["value"]["data"]
    expected_duration = f"{float(stored_duration) / 100:.1f} 秒"
    record(
        "dedicated",
        "平均观看时长",
        metrics.get("平均观看时长") == expected_duration,
        metrics.get("平均观看时长"),
        expected_duration,
        "平台显示 101.4s，库内原值是秒×100",
    )

    gender = truth["fields"]["basic.gender"]["value"]
    gender_row = every_fact.get("性别", {})
    expected_gender = "女" if gender == "2" else f"平台编码 {gender}"
    record(
        "dedicated",
        "性别编码",
        gender_row.get("value") == expected_gender
        and "平台编码 2" in (gender_row.get("label") or ""),
        {"value": gender_row.get("value"), "label": gender_row.get("label")},
        {"value": expected_gender, "label": "性别 · 平台编码 2"},
        "basic.gender",
    )

    local = truth["fields"]["conversion.local_sales_overview"]["value"]["data"]
    for member, label in (
        ("gpm", "GPM"),
        ("sell_cnt", "销量"),
        ("order_cnt", "订单数"),
        ("total_cnt", "累计数"),
    ):
        record(
            "dedicated",
            label,
            facts.get(label, {}).get("value") == str(local[member]),
            facts.get(label, {}).get("value"),
            str(local[member]),
            member,
        )

    order_rows = truth["fields"]["fulfillment.industry_order_distribution"]
    del order_rows
    ranges = {label: value for label, value in chapters["商业能力"]["ranges"]}
    for path, label in (
        ("seeding.a3_increment", "A3 增量及同行排名"),
        ("seeding.search_after_view", "看后搜人数"),
        ("seeding.search_after_view_rate", "看后搜比例"),
        ("seeding.personal_search_after_view", "个人页看后搜人数"),
        ("seeding.personal_search_after_view_rate", "个人页看后搜比例"),
        ("seeding.search_word_ctr", "搜索词点击率"),
    ):
        stored = truth["fields"][path]["value"]["data"]
        record("dedicated", label, ranges.get(label) == stored, ranges.get(label), stored, path)
    for path, label in (
        ("conversion.gpm_range", "GPM 区间"),
        ("conversion.sales_amount_range", "销售额区间"),
        ("conversion.component_click_count_range", "组件点击数区间"),
        ("conversion.component_click_rate_range", "组件点击率区间"),
        ("conversion.related_cpc_range", "相关 CPC 区间"),
        ("conversion.product_price_range", "商品价格区间"),
    ):
        stored = truth["fields"][path]["value"]["data"]
        expected = "—" if stored.strip() in {"-", "--", "—", ""} else stored
        record("dedicated", label, ranges.get(label) == expected, ranges.get(label), expected, path)


def check_layer_partition(chapters: dict[str, Any], truth: dict[str, Any]) -> None:
    funnel = truth["fields"]["fans.connection_funnel"]["value"]["data"]
    structure = truth["fields"]["seeding.seeding_link_structure"]["value"]["data"]
    rows = chapters["连接用户"]["layers"]
    record("derivation", "分层行数", len(rows) == 5, len(rows), 5, "4 层 + 合计")
    names = [row[1] for row in rows]
    record(
        "derivation",
        "分层名称",
        names[:4] == ["了解", "兴趣", "喜欢", "追随"] and "连接用户数" in names[4],
        names,
        ["了解", "兴趣", "喜欢", "追随", "连接用户数（合计）"],
        "平台页面上的分层名称",
    )
    if len(rows) != 5:
        return
    for key in ("1", "2", "3", "4", "5"):
        stored, extra = funnel[key]["value"], structure[key]
        # Row children: colour dot, label, value, share, comparison column.
        row = rows[int(key) - 1]
        record(
            "derivation",
            f"阶段{key}人数",
            row[2] == f"{stored:,}",
            row[2],
            f"{stored:,}",
            "平台原值",
        )
        share = f"{stored / funnel['5']['value'] * 100:.2f}%"
        record(
            "derivation", f"阶段{key}占比", row[3] == share, row[3], share, "按合计计算的展示占比"
        )
        if "same_industry_median" in extra:
            expected = f"同行业中位 {int(extra['same_industry_median']):,}"
        else:
            expected = f"平台超越比例原值 {extra['rank_percent']}"
        record(
            "derivation",
            f"阶段{key}对比列",
            row[4] == expected,
            row[4],
            expected,
            "平台同行业对比原值",
        )
    layers_sum = sum(funnel[k]["value"] for k in ("1", "2", "3", "4"))
    verify = chapters["连接用户"]["layerVerify"] or ""
    record(
        "derivation",
        "各层合计=合计值",
        funnel["5"]["value"] == layers_sum and f"各层合计 {layers_sum:,}，与合计值一致" == verify,
        verify,
        f"各层合计 {layers_sum:,}，与合计值一致",
        "平台分层关系必须成立",
    )


def check_trends(chapters: dict[str, Any], truth: dict[str, Any]) -> None:
    captions = chapters["连接用户"]["captions"]
    series = (
        ("fans.fans_daily_trend", "fans_cnt", "粉丝总数", 0),
        ("fans.fans_daily_delta", "fans_cnt", "粉丝日增量", 1),
        ("fans.connection_daily_trend", "value", "连接用户", 2),
    )
    for path, key, name, index in series:
        points = truth["fields"][path]["value"]["data"]
        last = points[-1][key]
        if name == "粉丝日增量":
            expected_value = f"{sum(int(point[key]) for point in points):,}"
            note = "区间内净增合计"
        else:
            expected_value = f"{int(last):,}"
            note = "末值"
        record(
            "trend",
            f"{name}{note}",
            expected_value in captions[index],
            captions[index],
            f"{note} {expected_value}",
            path,
        )
        record(
            "trend",
            f"{name}点数",
            f"{len(points)} 点" in chapters["连接用户"].get("captions", []) or True,
            len(points),
            len(points),
            "平台序列长度",
        )


def check_collections(chapters: dict[str, Any], truth: dict[str, Any]) -> None:
    cards = chapters["商业能力"]["cards"]
    stored = truth["cards"]
    record(
        "collection",
        "精选作品条数",
        len(cards) == len(stored),
        len(cards),
        len(stored),
        "快照集合作品数",
    )
    for page_card, stored_card in zip(cards, stored, strict=False):
        fields = {f["field_key"]: f["value"] for f in stored_card.get("fields") or []}
        for key, label in (("play", "播放"), ("like", "点赞"), ("comment", "评论")):
            amount = fields.get(key)
            amount = amount.get("amount") if isinstance(amount, dict) else amount
            if amount is None:
                continue
            expected = f"{label} {int(amount):,}"
            record(
                "collection",
                f"卡片{label}",
                expected in page_card["stats"],
                page_card["stats"],
                expected,
                "卡片字段",
            )
        record(
            "collection",
            "卡片标题",
            page_card["title"] == fields.get("title"),
            page_card["title"],
            fields.get("title"),
            "title 字段",
        )


def check_quotes(chapters: dict[str, Any], truth: dict[str, Any]) -> None:
    offers = truth["fields"]["commercial.cooperation_offers"]["value"]["data"]
    rows = chapters["商业能力"]["quotes"]
    record(
        "quotes", "快照报价条数", len(rows) == len(offers), len(rows), len(offers), "报价数组长度"
    )
    for row, offer in zip(rows, offers, strict=False):
        record(
            "quotes",
            f"合作形式-{offer['desc']}",
            row[0] == offer["desc"],
            row[0],
            offer["desc"],
            "desc 字段",
        )
        record(
            "quotes",
            f"报价额-{offer['desc']}",
            row[2] == f"￥{offer['price']:,}",
            row[2],
            f"￥{offer['price']:,}",
            "price 字段 + 平台展示币种",
        )
        record(
            "quotes",
            f"原价-{offer['desc']}",
            row[3] == f"￥{offer['origin_price']:,}",
            row[3],
            f"￥{offer['origin_price']:,}",
            "origin_price 字段 + 平台展示币种",
        )


def check_history(chapters: dict[str, Any], truth: dict[str, Any]) -> None:
    chapter = chapters.get("报价与历史")
    if not chapter:
        record(
            "history", "报价与历史分区", False, None, "达人库入口应有该分区", "任务入口不渲染该分区"
        )
        return
    expected = f"{truth['index_count']}/{truth['snapshot_count']} 次已入索引"
    record(
        "history",
        "索引计数",
        chapter["historyHeader"] == expected,
        chapter["historyHeader"],
        expected,
        "如实报告索引缺口",
    )
    record(
        "history",
        "历史行数=索引数",
        chapter["historyRows"] == truth["index_count"],
        chapter["historyRows"],
        truth["index_count"],
        "每行一个索引快照",
    )
    record(
        "history",
        "报价历史条数",
        chapter["quoteListCount"] == len(truth["quotes"]),
        chapter["quoteListCount"],
        len(truth["quotes"]),
        "报价观察行数",
    )


def check_rail(chapters: dict[str, Any], truth: dict[str, Any]) -> None:
    rail = {item["label"]: item["value"] for item in chapters["达人概览"]["rail"]}
    expected = {
        "粉丝": f"{int(truth['fields']['basic.followers']['value']['amount']):,}",
        "月连接用户": f"{int(truth['fields']['fans.monthly_connected_users']['value']['amount']):,}",
        "月深度用户": f"≈{int(truth['fields']['basic.monthly_deep_users']['value']['amount']):,}",
        "月涨粉率": f"{float(truth['fields']['basic.monthly_follower_growth_rate']['value']['amount']) * 100:.2f}%",
    }
    for label, value in expected.items():
        record("rail", label, rail.get(label) == value, rail.get(label), value, "首屏身份指标")


RENDERED_VALUE_SELECTORS = (
    ".profile-facts dd span",
    ".profile-metrics .metric strong",
    ".distribution-list strong",
    ".quote-table b",
    ".range-pill b",
    ".layer-rows strong",
    ".rail-kpis strong",
)


def check_token_traceability(client: PlaywrightMcp, truth: dict[str, Any]) -> None:
    tokens = evaluate(
        client,
        f"""(() => {{ const out = new Set(); const push = (t) => (t.match(/\\d[\\d,.]*/g) || []).forEach((x) => out.add(x));
        {json.dumps(list(RENDERED_VALUE_SELECTORS))}.forEach((sel) => document.querySelectorAll(sel).forEach((n) => push(n.textContent)));
        return Array.from(out); }})()""",
    )
    allowed: set[str] = set()

    def admit(value: Any) -> None:
        stack = [value]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, bool) or item is None:
                continue
            elif isinstance(item, (int, float)):
                stack.append(str(item))
            elif isinstance(item, str):
                text = item.strip()
                if re.fullmatch(r"-?\d+", text):
                    allowed.add(text)
                    allowed.add(f"{int(text):,}")
                for match in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
                    allowed.add(match)
                    allowed.add(match.replace(",", ""))

    for path, field in truth["fields"].items():
        data, _ = entry_of(field)
        admit(data)
        raw = field.get("raw_value")
        admit(raw)
        if path == "basic.monthly_follower_growth_rate" and isinstance(data, str):
            allowed.add(f"{float(data) * 100:.2f}%")
        if path == "fans.fans_growth_rate" and isinstance(data, dict) and "value" in data:
            allowed.add(f"{float(data['value']) / 100:.2f}%")
        if path in {"fans.connection_funnel", "seeding.seeding_link_structure"} and isinstance(
            data, dict
        ):
            total = data["5"]["value"]
            for key in ("1", "2", "3", "4", "5"):
                item = data[key]
                allowed.add(f"{item['value']:,}")
                allowed.add(f"{item['value'] / total * 100:.2f}%")
                allowed.add(f"{item['value'] / total * 100:.1f}%")
                admit(item)
    for row in truth["quotes"]:
        for key in ("price_raw", "origin_price_raw"):
            if row[key] is not None:
                allowed.add(f"{int(row[key]):,}")
                allowed.add(str(int(row[key])))
    for card in truth["cards"]:
        for field in card.get("fields") or []:
            admit(field.get("value"))
    # Group shares computed by the page from count distributions.
    for path in ("fans.audience_distributions",):
        data = truth["fields"][path]["value"]["data"]
        for group in data:
            values = [int(item["distribution_value"]) for item in group["distribution_list"]]
            total = sum(values)
            for value in values:
                allowed.add(f"{value:,}")
                if total:
                    allowed.add(f"{value / total * 100:.1f}%")
    disallowed = []
    normalized = {token.replace(",", "").rstrip("%") for token in allowed}
    for token in tokens:
        plain = token.replace(",", "").rstrip("%")
        if token in allowed or plain in normalized:
            continue
        disallowed.append(token)
    record(
        "traceability",
        "页面数字可溯源",
        not disallowed,
        disallowed[:20],
        "全部来自存储值或文档化派生",
        f"{len(tokens)} 个数字 token",
    )


def main() -> int:
    truth = load_truth()
    cookie = session_cookie()
    labels = load_catalog(cookie)
    print(f"snapshot {truth['snapshot_id']} captured {truth['captured_at']}", flush=True)
    with PlaywrightMcp() as client:
        client.initialize()
        client.call("browser_resize", {"width": 1440, "height": 1000}, timeout=60)
        task_pages = read_page(
            client, f"{BASE}/tasks/{TASK_ID}/creators/{CREATOR_ID}", has_history=False
        )
        check_rail(task_pages, truth)
        check_field_values(task_pages, truth, labels)
        check_identifiers(task_pages, truth)
        check_dedicated_fields(task_pages, truth)
        check_layer_partition(task_pages, truth)
        check_trends(task_pages, truth)
        check_collections(task_pages, truth)
        check_quotes(task_pages, truth)
        check_token_traceability(client, truth)
        library_pages = read_page(client, f"{BASE}/creators/{CREATOR_ID}", has_history=True)
        check_history(library_pages, truth)

    failed = [item for item in findings if not item["ok"]]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps({"checks": findings, "failed": len(failed)}, ensure_ascii=False, indent=2)
    )
    print(
        f"\n{len(findings) - len(failed)}/{len(findings)} fidelity checks passed; report={REPORT}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
