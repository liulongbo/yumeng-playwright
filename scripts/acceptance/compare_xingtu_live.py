"""Read-only comparison against the live 巨量星图 creator homepage.

Opens the platform homepage for one already-collected creator with the project's logged-in execution
unit profile and records what the platform currently displays, so the stored snapshot can be checked
against its source.  It performs no search, no collection and writes nothing to the database.

Usage:
    .venv/bin/python scripts/acceptance/compare_xingtu_live.py --platform-id 7503176021160493065
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import psycopg
from psycopg.rows import dict_row

from scripts.acceptance.mcp_client import PlaywrightMcp  # noqa: E402
from scripts.acceptance.run_acceptance import evaluate  # noqa: E402

BASE = "https://www.xingtu.cn/ad/creator/author-homepage/douyin-video/{platform_id}"
PROFILE = "/Users/Longbo/Developer/YUMENG/.runtime/profiles/unit-local-mac-02"
SHOTS = pathlib.Path("/tmp/dsh-playwright-mcp")
EVIDENCE = pathlib.Path("docs/evidence/assets/cd02")
OUT = pathlib.Path("/tmp/xingtu-live.json")

# The application restores this snapshot into its own browser host before the first navigation; the
# bare MCP Chrome is seeded with the same session so the platform page can be read without touching
# the execution-unit profile directory at all (`--isolated` keeps the profile in memory).
# The private file is a *wrapper* (`{schema_version, unit_id, captured_at, storage_state}`) while
# Playwright needs the bare `{cookies, origins}` document, so the inner state is materialised to a
# temporary file.  Nothing is ever written back to the snapshot.
STORAGE_STATE = (
    "/Users/Longbo/Developer/YUMENG/.runtime/profiles/storage-state/unit-local-mac-02.json"
)
RAW_STATE = "/tmp/cd02-xingtu-state.json"


def materialise_state() -> str:
    wrapper = json.loads(pathlib.Path(STORAGE_STATE).read_text())
    pathlib.Path(RAW_STATE).write_text(json.dumps(wrapper["storage_state"]))
    return RAW_STATE


COMMAND = [
    "/usr/local/bin/node",
    "/Users/yaoyao/.local/lib/node_modules/@playwright/mcp/cli.js",
    "--browser",
    "chrome",
    "--no-sandbox",
    "--isolated",
    "--storage-state",
    RAW_STATE,
    "--output-dir",
    "/tmp/dsh-playwright-mcp",
]


def parse_platform_number(text: str | None) -> float | None:
    """`2,376.6w` / `135.2w` / `1.97%` / `40,000` → the absolute platform number."""
    if not text:
        return None
    match = re.search(r"([\d,]+(?:\.\d+)?)\s*(w|万|%)?", text)
    if not match:
        return None
    value = float(match.group(1).replace(",", ""))
    unit = match.group(2)
    if unit in {"w", "万"}:
        return value * 10000
    return value


def compare_with_snapshot(platform: dict, platform_id: str) -> dict:
    """Compare the live platform values with the stored snapshot for the same creator."""
    dsn = os.environ.get("XINGTU_DATABASE_URL")
    if not dsn:
        return {"skipped": "XINGTU_DATABASE_URL not set"}
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        snapshot = conn.execute(
            """SELECT s.snapshot_id, s.created_at, s.payload FROM creator_snapshots s
            JOIN platform_creators p ON p.creator_id = s.creator_id
            WHERE p.platform_creator_id = %s
            ORDER BY s.created_at DESC, s.snapshot_id DESC LIMIT 1""",
            (platform_id,),
        ).fetchone()
    if not snapshot:
        return {"skipped": "creator not stored"}
    fields: dict[str, Any] = {}
    for module_key, module in (snapshot["payload"].get("modules") or {}).items():
        for field in module.get("fields") or []:
            fields[f"{module_key}.{field['field_key']}"] = field

    def stored_amount(path: str) -> float | None:
        field = fields.get(path) or {}
        value = field.get("value")
        if isinstance(value, dict):
            value = value.get("amount", value.get("data"))
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    samples = []
    for label, path in (
        ("月连接用户数", "fans.monthly_connected_users"),
        ("月深度用户数", "basic.monthly_deep_users"),
        ("粉丝", "basic.followers"),
    ):
        live = parse_platform_number(platform["metrics"].get(label))
        stored = stored_amount(path)
        if live is None or stored is None:
            continue
        samples.append(
            {
                "metric": label,
                "platform_live": live,
                "stored_snapshot": stored,
                "difference": live - stored,
                "relative_percent": round((live - stored) / stored * 100, 4) if stored else None,
                "same": live == stored,
                "path": path,
            }
        )
    growth_live = platform["metrics"].get("月涨粉率")
    growth_stored = stored_amount("basic.monthly_follower_growth_rate")
    if growth_live and growth_stored is not None:
        live_pct = round(parse_platform_number(growth_live) or 0, 2)
        stored_pct = round(growth_stored * 100, 2)
        samples.append(
            {
                "metric": "月涨粉率",
                "platform_live": f"{live_pct}%",
                "stored_snapshot": f"{stored_pct}%",
                "difference": round(live_pct - stored_pct, 2),
                "relative_percent": None,
                "same": abs(live_pct - stored_pct) < 0.005,
                "path": "basic.monthly_follower_growth_rate",
            }
        )
    offers = (fields.get("commercial.cooperation_offers") or {}).get("value") or {}
    offers = offers.get("data") or []
    stored_prices = sorted({f"{int(offer['price']):,}" for offer in offers})
    live_prices = sorted(
        {
            f"{int(value):,}"
            for value in (parse_platform_number(x) or 0 for x in platform.get("quotes", []))
            if value
        }
    )
    return {
        "snapshot_id": str(snapshot["snapshot_id"]),
        "snapshot_captured_at": snapshot["created_at"].isoformat(),
        "metrics": samples,
        "labels": {
            "达人类型": platform["facts"].get("达人类型"),
            "行业标签": platform.get("tags"),
            "性别": platform["facts"].get("性别"),
            "地区": platform["facts"].get("地区"),
            "介绍": platform["facts"].get("介绍"),
            "平台报价": live_prices,
            "库内报价": stored_prices,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform-id", required=True)
    parser.add_argument("--name", default="creator")
    parser.add_argument(
        "--profile-dir",
        action="store_true",
        help="use the execution-unit profile instead of the snapshot",
    )
    args = parser.parse_args()

    url = BASE.format(platform_id=args.platform_id)
    materialise_state()
    command = COMMAND
    if args.profile_dir:
        command = [
            "/usr/local/bin/node",
            "/Users/yaoyao/.local/lib/node_modules/@playwright/mcp/cli.js",
            "--browser",
            "chrome",
            "--no-sandbox",
            "--user-data-dir",
            PROFILE,
            "--output-dir",
            "/tmp/dsh-playwright-mcp",
        ]
    with PlaywrightMcp(command=command) as client:
        info = client.initialize()
        print("mcp:", info.get("serverInfo"), flush=True)
        client.call("browser_navigate", {"url": url}, timeout=180)
        time.sleep(6)
        state = evaluate(
            client,
            """(() => ({
              url: location.href,
              title: document.title,
              hasAuthorCard: Boolean(document.querySelector('div.author-info')),
              loginForm: Boolean(document.querySelector('input[type=password]')),
              challenge: document.body.innerText.includes('验证') && document.body.innerText.length < 4000,
              bodyHead: document.body.innerText.slice(0, 400),
            }))()""",
        )
        print(json.dumps(state, ensure_ascii=False, indent=1), flush=True)
        if not state.get("hasAuthorCard"):
            client.call("browser_navigate", {"url": url}, timeout=180)
            time.sleep(8)
            state = evaluate(
                client,
                """(() => ({ url: location.href, hasAuthorCard: Boolean(document.querySelector('div.author-info')),
                  bodyHead: document.body.innerText.slice(0, 400) }))()""",
            )
            print("retry:", json.dumps(state, ensure_ascii=False), flush=True)

        platform = evaluate(
            client,
            """(() => {
              const lines = document.body.innerText.split('\\n').map((line) => line.trim()).filter(Boolean);
              const after = (label) => {
                const index = lines.indexOf(label);
                return index >= 0 && index + 1 < lines.length ? lines[index + 1] : null;
              };
              return {
                tabs: Array.from(document.querySelectorAll('.el-tabs__item')).map((n) => n.textContent.trim()),
                name: after('通用短视频主页') || after('星图ID') || null,
                metrics: {
                  月连接用户数: after('月连接用户数'),
                  月深度用户数: after('月深度用户数'),
                  粉丝: after('粉丝'),
                  月涨粉率: after('月涨粉率'),
                },
                facts: {
                  星图ID: after('星图ID'),
                  达人类型: after('达人类型'),
                  性别: after('性别'),
                  地区: after('地区'),
                  介绍: after('介绍'),
                },
                tags: lines.slice(lines.indexOf('行业标签') + 1, lines.indexOf('性别')).filter((x) => x !== '8+'),
                themeIndex: lines.indexOf('内容主题'),
                themes: lines.slice(lines.indexOf('内容主题') + 1, lines.indexOf('查看主题词相关视频和达人')),
                quotes: lines.slice(lines.indexOf('达人服务报价') + 1, lines.indexOf('达人服务报价') + 5),
              };
            })()""",
        )
        print(json.dumps(platform, ensure_ascii=False, indent=1), flush=True)

        comparison = compare_with_snapshot(platform, args.platform_id)
        print(json.dumps(comparison, ensure_ascii=False, indent=1), flush=True)

        SHOTS.mkdir(parents=True, exist_ok=True)
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        target = SHOTS / f"xingtu-live-{args.name}.png"
        try:
            client.call(
                "browser_take_screenshot",
                {"filename": str(target), "fullPage": True, "type": "png"},
                timeout=120,
            )
            time.sleep(1.5)
            if target.exists():
                (EVIDENCE / target.name).write_bytes(target.read_bytes())
                print("screenshot:", EVIDENCE / target.name, flush=True)
        except Exception as error:  # noqa: BLE001 - a failed capture is reported
            print("screenshot failed:", error, flush=True)

        OUT.write_text(
            json.dumps(
                {"state": state, "platform": platform, "comparison": comparison},
                ensure_ascii=False,
                indent=2,
            )
        )
        # Close the page so the profile is left clean for the application's own browser host.
        evaluate(client, "(() => { window.close(); return true; })()")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
