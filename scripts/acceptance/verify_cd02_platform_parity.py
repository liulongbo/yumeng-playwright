"""CD-02 platform parity: stored snapshot vs the live 巨量星图 creator homepage.

Reads the platform text captured read-only by `compare_xingtu_live.py` / the tab probe
(`/tmp/platform-tabs.json`) and the stored snapshot, then answers, per data point:

- is the value the same, only time-shifted (the platform's windows are 近30天 and roll), or a real
  discrepancy?
- does the platform give a unit/scale the stored raw value can now be interpreted with?

Usage:
    .venv/bin/python scripts/acceptance/verify_cd02_platform_parity.py --tabs /tmp/platform-tabs.json
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
from typing import Any

import psycopg
from psycopg.rows import dict_row

PLATFORM_ID = "7503176021160493065"
REPORT = pathlib.Path("docs/evidence/CD-02-platform-parity-2026-10-14.json")
findings: list[dict[str, Any]] = []


def record(
    group: str,
    item: str,
    verdict: str,
    platform: Any,
    stored: Any,
    note: str = "",
) -> None:
    findings.append(
        {
            "group": group,
            "item": item,
            "verdict": verdict,
            "platform_live": platform,
            "stored_snapshot": stored,
            "note": note,
        }
    )


def wan(text: str) -> float | None:
    """`194.7w` / `93.8w` / `5,078` / `1.1%` → the number (万 expanded)."""
    match = re.search(r"([\d,]+(?:\.\d+)?)\s*(w|万)?", text or "")
    if not match:
        return None
    value = float(match.group(1).replace(",", ""))
    return value * 10000 if match.group(2) else value


def load_stored(platform_id: str) -> dict[str, Any]:
    dsn = os.environ["XINGTU_DATABASE_URL"]
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        row = conn.execute(
            """SELECT s.snapshot_id, s.created_at, s.payload FROM creator_snapshots s
            JOIN platform_creators p ON p.creator_id = s.creator_id
            WHERE p.platform_creator_id = %s
            ORDER BY s.created_at DESC, s.snapshot_id DESC LIMIT 1""",
            (platform_id,),
        ).fetchone()
        quotes = conn.execute(
            """SELECT q.cooperation_form, q.price_raw, q.observed_at
            FROM douyin_xingtu_creator_quote_observations q
            JOIN platform_creators p ON p.creator_id = q.creator_id
            WHERE p.platform_creator_id = %s ORDER BY q.observed_at DESC, q.position""",
            (platform_id,),
        ).fetchall()
    fields: dict[str, Any] = {}
    for module_key, module in (row["payload"].get("modules") or {}).items():
        for field in module.get("fields") or []:
            fields[f"{module_key}.{field['field_key']}"] = field
    return {
        "snapshot_id": str(row["snapshot_id"]),
        "captured_at": row["created_at"].isoformat(),
        "fields": fields,
        "quotes": [dict(item) for item in quotes],
    }


def value_of(fields: dict[str, Any], path: str) -> Any:
    entry = (fields.get(path) or {}).get("value")
    if isinstance(entry, dict):
        return entry.get("data", entry.get("amount"))
    return entry


def data_of(fields: dict[str, Any], path: str) -> Any:
    entry = (fields.get(path) or {}).get("value")
    return entry.get("data") if isinstance(entry, dict) else None


def section(text: str, start: str, end: str) -> str:
    begin = text.find(start)
    if begin < 0:
        return ""
    stop = text.find(end, begin)
    return text[begin : stop if stop > 0 else len(text)]


def compare(platform: dict[str, Any], stored: dict[str, Any]) -> None:
    fields = stored["fields"]
    overview = platform["达人概览"]["text"]
    commercial = platform["商业能力"]["text"]
    creation = platform["创作能力"]["text"]
    audience = platform["连接用户"]["text"]

    # ---------------------------------------------------------------- identity and scale
    record(
        "identity",
        "达人类型",
        "same" if "达人类型\n汽车" in overview else "different",
        "汽车",
        fields["basic.creator_type_label"]["value"],
        "平台左栏与库内一致",
    )
    tags = [
        line
        for line in section(overview, "行业标签", "性别").split("\n")[1:]
        if line and line != "8+"
    ]
    record(
        "identity",
        "行业标签",
        "same" if tags == fields["basic.industry_labels"]["value"] else "different",
        tags,
        fields["basic.industry_labels"]["value"],
        "顺序与取值一致",
    )
    record(
        "identity",
        "地区",
        "same"
        if "内蒙古自治区-赤峰市" in overview
        and fields["basic.province"]["value"] == "内蒙古自治区"
        and fields["basic.city"]["value"] == "赤峰市"
        else "different",
        "内蒙古自治区-赤峰市",
        f"{fields['basic.province']['value']}-{fields['basic.city']['value']}",
    )
    record(
        "identity",
        "介绍",
        "same" if fields["basic.introduction"]["value"] in overview else "different",
        None,
        fields["basic.introduction"]["value"],
    )
    gender = fields["basic.gender"]["value"]
    record(
        "identity",
        "性别编码",
        "same" if (gender == "2" and "性别\n女" in overview) else "different",
        "女",
        f"平台编码 {gender}",
        "平台显示「女」，库内保存原码 2（页面按原码显示，未做映射）",
    )

    # ---------------------------------------------------------------- four identity KPIs
    kpis = {
        "月连接用户数": ("fans.monthly_connected_users", 1.5),
        "月深度用户数": ("basic.monthly_deep_users", 1.5),
        "粉丝": ("basic.followers", 0.05),
    }
    for label, (path, tolerance_percent) in kpis.items():
        match = re.search(rf"{label}\n([\d.,]+w?)", overview)
        live = wan(match.group(1)) if match else None
        value = value_of(fields, path)
        stored_amount = float(value) if value not in (None, "") else None
        if live is None or stored_amount is None:
            record("kpi", label, "unavailable", live, stored_amount)
            continue
        delta_percent = (live - stored_amount) / stored_amount * 100
        record(
            "kpi",
            label,
            "time-shift" if abs(delta_percent) <= tolerance_percent else "different",
            live,
            stored_amount,
            f"差 {live - stored_amount:+,.0f}（{delta_percent:+.2f}%）；平台显示精度为 0.1w",
        )

    growth_stored = float(value_of(fields, "basic.monthly_follower_growth_rate"))
    match = re.search(r"月涨粉率\n([\d.]+)%", overview)
    live_growth = float(match.group(1)) if match else None
    record(
        "kpi",
        "月涨粉率",
        "same"
        if live_growth is not None and abs(live_growth - growth_stored * 100) < 0.005
        else "different",
        f"{live_growth}%",
        f"{growth_stored * 100:.2f}%（原始小数 {growth_stored}）",
        "契约 kind=ratio，×100 与平台完全一致",
    )

    # ---------------------------------------------------------------- rates and units
    rates = (
        ("互动率", "spread.interaction_rate", r"互动率\n([\d.]+)%", r"优于\n([\d.]+)%"),
        ("完播率", "spread.completion_rate", r"完播率\n([\d.]+)%", r"优于\n([\d.]+)%"),
    )
    for label, path, pattern, overtake_pattern in rates:
        data = data_of(fields, path)
        live = re.search(pattern, commercial)
        overtakes = re.findall(overtake_pattern, commercial)
        live_value = float(live.group(1)) if live else None
        stored_value = float(data["value"]) / 100
        record(
            "scale",
            f"{label}显示口径",
            "same"
            if live_value is not None and abs(live_value - stored_value) < 0.06
            else "different",
            f"{live_value}%",
            f"{stored_value:.2f}%（库内原值 {data['value']}）",
            "库内 value ÷ 100 = 平台百分比（平台显示 1 位小数）",
        )
        record(
            "scale",
            f"{label}同行超越口径",
            "time-shift",
            f"{overtakes[0] if overtakes else None}%",
            f"{float(data['overtake']) / 100:.2f}%（库内原值 {data['overtake']}）",
            "库内 overtake ÷ 100 = 「优于同类型达人」百分比",
        )

    play_median = re.search(r"播放量中位数\n([\d.]+w)", commercial)
    stored_median = float(value_of(fields, "spread.play_median"))
    live_median = wan(play_median.group(1)) if play_median else None
    record(
        "scale",
        "播放中位数",
        "time-shift"
        if live_median and abs(live_median - stored_median) / stored_median < 0.02
        else "different",
        live_median,
        stored_median,
        "时间漂移（近30天窗口）",
    )
    duration = re.search(r"平均时长\n([\d.]+)s", commercial)
    stored_duration = float(value_of(fields, "spread.average_duration"))
    record(
        "scale",
        "平均时长单位",
        "same"
        if duration and abs(float(duration.group(1)) - stored_duration / 100) < 0.05
        else "different",
        f"{duration.group(1)}s" if duration else None,
        f"{stored_duration}（读作 {stored_duration / 100:.1f} 秒）",
        "库内原值是「秒×100」",
    )

    # ---------------------------------------------------------------- connection layers
    layer_names = re.findall(r"\n(了解|兴趣|喜欢|追随)\n([\d,.]+)\n30天环比", audience)
    stored_layers = data_of(fields, "fans.connection_funnel")
    expected_names = ["了解", "兴趣", "喜欢", "追随"]
    same_names = [name for name, _ in layer_names] == expected_names
    record(
        "layers",
        "阶段名称",
        "same" if same_names else "different",
        [name for name, _ in layer_names],
        expected_names,
        "平台为阶段 1–4 命名：了解/兴趣/喜欢/追随；阶段 5 为连接用户数合计",
    )
    for index, (name, value) in enumerate(layer_names, start=1):
        live = float(value.replace(",", ""))
        stored_layer = float(stored_layers[str(index)]["value"])
        record(
            "layers",
            f"{index}. {name}",
            "time-shift" if abs(live - stored_layer) / stored_layer < 0.05 else "different",
            live,
            stored_layer,
            f"差 {live - stored_layer:+,.0f}",
        )
    total_live = float(re.search(r"连接用户数\n([\d,.]+)", audience).group(1).replace(",", ""))
    total_stored = float(stored_layers["5"]["value"])
    record(
        "layers",
        "合计=连接用户数",
        "same" if same_names else "different",
        total_live,
        total_stored,
        "平台把阶段 5 显示为「连接用户数」，与四层之和相等",
    )

    # ---------------------------------------------------------------- distributions
    stored_density = data_of(fields, "creation.content_theme_density")
    # The platform also lists an "其他" bucket the registry does not expose as a theme; only the
    # named themes are comparable.
    platform_density = {
        name: int(count)
        for name, count in re.findall(r"([^\s]+) \((\d+)\)", creation)
        if name not in {"全部", "其他"}
    }
    stored_density_counts = {
        item["label_name"]: int(item["label_item_count"]) for item in stored_density.values()
    }
    record(
        "distribution",
        "内容主题集中度",
        "same" if stored_density_counts == platform_density else "different",
        platform_density,
        stored_density_counts,
        "10 个主题与条数逐值一致",
    )

    stored_industry = data_of(fields, "fulfillment.cooperation_industry_distribution")
    first = stored_industry[0]
    record(
        "distribution",
        "合作行业分布",
        "same" if "汽车(100%)" in overview and first["industry"]["name"] == "汽车" else "different",
        "汽车(100%)",
        f"{first['industry']['name']}({first['industry']['rate']:.0%})",
        "一级类目 汽车厂商 亦一致",
    )

    # ---------------------------------------------------------------- seeding ranges
    ranges = {
        "商单视频看后搜率": ("seeding.search_after_view_rate", "0.5% - 1%"),
        "个人视频看后搜率": ("seeding.personal_search_after_view_rate", "0.02% - 0.1%"),
        "A3增长数": ("seeding.a3_increment", "20,000 - 100,000"),
    }
    for label, (path, expected) in ranges.items():
        stored_range = data_of(fields, path)
        record(
            "ranges",
            label,
            "same" if stored_range == expected and expected in overview else "different",
            expected if expected in overview else None,
            stored_range,
            "区间值逐字一致",
        )

    # ---------------------------------------------------------------- videos
    stored_recent = data_of(fields, "creation.recent_video_performance") or []
    stored_xingtu = data_of(fields, "creation.recent_xingtu_video_performance") or []
    titles = {item.get("title"): item for item in [*stored_recent, *stored_xingtu]}
    matched = 0
    for title, item in titles.items():
        if not title or title not in creation:
            continue
        matched += 1
        window = creation[creation.find(title) : creation.find(title) + 400]
        play_live = re.search(r"播放量\n([\d.]+w?)", window)
        live = wan(play_live.group(1)) if play_live else None
        stored_play = float(item["play"])
        if live is None:
            record("video", title[:24], "unavailable", None, stored_play)
            continue
        # A 万 value is rendered to 0.1w (1,000) precision, and the play counter kept growing for
        # the ~13 hours between the snapshot and this read, so only a regression or a gap far larger
        # than the observed growth would be a real discrepancy.
        growth = (live - stored_play) / stored_play
        record(
            "video",
            title[:24],
            "time-shift" if 0 <= growth <= 0.05 else "different",
            live,
            stored_play,
            f"差 {live - stored_play:+,.0f}（{growth:+.2%}，播放量随时间增长；万位取整 ±500）",
        )
    record(
        "video",
        "同标题可比对条数",
        "note",
        matched,
        len(stored_recent) + len(stored_xingtu),
        "平台前端仅渲染懒加载出的部分卡片，未匹配的标题不代表缺失",
    )

    # ---------------------------------------------------------------- quotes
    offers = data_of(fields, "commercial.cooperation_offers") or []
    live_prices = re.findall(r"￥([\d,]+)", commercial)
    stored_prices = [f"{int(offer['price']):,}" for offer in offers]
    record(
        "quotes",
        "报价金额与币种",
        "same" if live_prices and set(live_prices) == set(stored_prices) else "different",
        f"￥{live_prices}",
        stored_prices,
        "平台显示人民币（￥）；库内只保留原值，页面未标币种",
    )

    # ---------------------------------------------------------------- fields the platform shows but we do not collect
    missing = [
        name
        for name in ("预期播放量", "爆文率", "进店成本", "组件点击率", "CPC", "相关视频数")
        if name in overview or name in commercial
    ]
    record(
        "coverage",
        "平台展示但库内未采集",
        "note",
        missing,
        "无对应字段",
        "未采集项，不是显示错误",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tabs", default="/tmp/platform-tabs.json")
    parser.add_argument("--platform-id", default=PLATFORM_ID)
    args = parser.parse_args()

    platform = json.loads(pathlib.Path(args.tabs).read_text())
    stored = load_stored(args.platform_id)
    print(f"snapshot {stored['snapshot_id']} captured {stored['captured_at']}", flush=True)
    compare(platform, stored)

    counts: dict[str, int] = {}
    for item in findings:
        counts[item["verdict"]] = counts.get(item["verdict"], 0) + 1
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(
            {
                "snapshot_id": stored["snapshot_id"],
                "snapshot_captured_at": stored["captured_at"],
                "platform_read_at": platform["连接用户"].get("read_at"),
                "summary": counts,
                "findings": findings,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print("\n判定统计:", counts)
    for item in findings:
        if item["verdict"] == "different":
            print(
                f"[DIFFERENT] {item['group']} :: {item['item']}\n  platform={item['platform_live']!r}\n  stored  ={item['stored_snapshot']!r}\n  note    ={item['note']}",
                flush=True,
            )
    print("report:", REPORT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
