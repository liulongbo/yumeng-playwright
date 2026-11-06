#!/usr/bin/env python3
"""Real-browser UI acceptance for the UPD-06 automatic-update management page.

Logs into the running product UI with the existing QA account, opens the new /settings page,
checks the four services and the scheduler state, toggles one real switch through the browser,
confirms the persisted state through the page's own authenticated API context, toggles it back,
and captures the task-centre detail of a real scheduled batch.

The script never prints credentials and does not start/stop any service.  It requires the isolated
UPD-06 API + frontend to be running (or any equivalent product URL via --base).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CREDS = ROOT / ".runtime" / "qa-credentials.env"
SHOTS = ROOT / "docs" / "evidence" / "assets" / "UPD-06"


def load_password() -> str:
    for line in CREDS.read_text().splitlines():
        if line.startswith("QA_MEDIA_A_PASSWORD="):
            return line.partition("=")[2].strip()
    raise SystemExit("QA_MEDIA_A_PASSWORD missing")


def services(page) -> dict:
    response = page.request.get("http://127.0.0.1:8000/api/update-services")
    if not response.ok:
        raise RuntimeError(f"update-services API returned {response.status}")
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser(description="UPD-06 management-page browser acceptance")
    parser.add_argument("--base", default="http://127.0.0.1:5173")
    parser.add_argument(
        "--task-id",
        default="c8a2f16a-33b2-441a-b8dd-ee7853c441fc",
        help="a real scheduled batch to open in the task centre",
    )
    args = parser.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)
    password = load_password()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 980})
        page.goto(args.base + "/settings", wait_until="networkidle")
        if "/login" in page.url:
            page.get_by_placeholder("请输入账号").fill("media-a")
            page.get_by_placeholder("请输入密码").fill(password)
            page.get_by_role("button", name="安全登录").click()
            page.wait_for_url("**/settings", timeout=20_000)
        page.get_by_role("heading", name="自动更新服务").wait_for(timeout=20_000)
        page.get_by_text("调度器在线", exact=True).wait_for(timeout=20_000)
        switch_count = page.get_by_role("switch").count()
        page.screenshot(path=str(SHOTS / "ui-services.png"), full_page=True)
        before = services(page)

        toggle = page.get_by_role("switch", name="开启 磁力聚星直播广场自动更新")
        toggle.click()
        page.get_by_role("switch", name="关闭 磁力聚星直播广场自动更新").wait_for(timeout=20_000)
        page.screenshot(path=str(SHOTS / "ui-juxing-live-enabled.png"), full_page=True)
        enabled = services(page)
        page.get_by_role("switch", name="关闭 磁力聚星直播广场自动更新").click()
        page.get_by_role("switch", name="开启 磁力聚星直播广场自动更新").wait_for(timeout=20_000)
        page.screenshot(path=str(SHOTS / "ui-juxing-live-restored.png"), full_page=True)
        restored = services(page)

        page.goto(args.base + f"/tasks/{args.task_id}", wait_until="networkidle")
        page.locator("h1").first.wait_for(timeout=20_000)
        page.screenshot(path=str(SHOTS / "ui-scheduled-task-detail.png"), full_page=True)
        browser.close()

    def group(page_state: dict, platform: str, scene: str) -> dict:
        return next(
            item
            for item in page_state["items"]
            if item["platform"] == platform and item["creator_scene"] == scene
        )

    result = {
        "switch_count": switch_count,
        "scheduler_alive": before["scheduler_alive"],
        "groups_before": [
            (item["platform"], item["creator_scene"], item["enabled"], item["effective_enabled"])
            for item in before["items"]
        ],
        "toggled_group_enabled": group(enabled, "kuaishou_juxing", "live_square")["enabled"],
        "restored_group_enabled": group(restored, "kuaishou_juxing", "live_square")["enabled"],
        "screenshots": sorted(path.name for path in SHOTS.glob("ui-*.png")),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if switch_count == 4 and result["toggled_group_enabled"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
