from __future__ import annotations

import asyncio
import json
import runpy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[3]
PROBE: dict[str, Any] = runpy.run_path(str(ROOT / "scripts" / "account_drift_probe.py"))


def test_system_keychain_ab_ignores_only_mock_keychain_default() -> None:
    runtime = PROBE["ProbeBrowserRuntime"](
        SimpleNamespace(
            browser_executable_path=None,
            browser_channel=None,
            headless=False,
            network_mode="local_development",
            macos_system_keychain=False,
        ),
        ROOT / ".runtime",
        use_system_keychain=True,
    )

    assert runtime._launch_options()["ignore_default_args"] == ["--use-mock-keychain"]
    assert runtime.launch_args == [
        "--disable-quic",
        "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-position=60,60",
        "--window-size=1440,960",
    ]


def test_diagnostic_helpers_remove_query_values_and_response_values() -> None:
    sanitized_url = PROBE["sanitized_url"]
    response_shape = PROBE["response_shape"]
    in_scope = PROBE["request_in_diagnostic_scope"]

    assert sanitized_url("https://www.xingtu.cn/switch?token=secret#fragment") == {
        "host": "www.xingtu.cn",
        "path": "/switch",
    }
    shape = response_shape(
        {"code": 0, "status": "ok", "token": "supersecret", "payload": {"uid": "123"}}
    )
    assert shape == {
        "kind": "object",
        "keys": ["code", "payload", "status", "token"],
        "business_status": {"code": 0, "status": "ok"},
    }
    assert "supersecret" not in json.dumps(shape)
    assert in_scope("https://www.xingtu.cn/api/switch")
    assert in_scope("https://sso.oceanengine.com/login")
    assert not in_scope("https://xingtu.cn.attacker.invalid/api")


async def test_navigation_does_not_lose_click_and_evidence_stays_redacted() -> None:
    interaction_capture = PROBE["InteractionCapture"]
    target_id = "1865332309937515"

    async with async_playwright() as playwright:
        system_chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        launch_options = {"executable_path": str(system_chrome)} if system_chrome.is_file() else {}
        browser = await playwright.chromium.launch(**launch_options)
        context = await browser.new_context()
        await context.add_cookies(
            [
                {
                    "name": "star_sessionid",
                    "value": "session-secret",
                    "domain": ".xingtu.cn",
                    "path": "/",
                }
            ]
        )

        async def route_handler(route: Any) -> None:
            path = PROBE["sanitized_url"](route.request.url)["path"]
            if path == "/switch":
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"code": 0, "token": "supersecret"}),
                )
                return
            if path == "/next":
                await route.fulfill(
                    content_type="text/html",
                    body=(
                        f'<div id="account">ID: {target_id}</div>'
                        '<a id="protected" href="/protected">ready</a>'
                    ),
                )
                return
            await route.fulfill(
                content_type="text/html",
                body=(
                    '<button id="target">ID: '
                    f"{target_id}"
                    "</button>"
                    "<script>target.onclick=async()=>{"
                    "await (await fetch('/switch',{method:'POST'})).json();"
                    "location.href='/next';}</script>"
                ),
            )

        await context.route("https://www.xingtu.cn/**", route_handler)
        page = await context.new_page()
        capture = interaction_capture(
            context,
            "#account",
            "#protected",
            b"a" * 32,
            checkpoint_delays=(0.05, 0.1),
        )
        await capture.install()
        await page.goto("https://www.xingtu.cn/start")
        selection = await PROBE["select_subaccount"](page, target_id)
        assert selection["clicked"] is True
        assert selection["click_method"] == "playwright_locator"
        await page.wait_for_url("**/next")
        await asyncio.sleep(0.2)
        result = await capture.finish()

        account_events = [
            item for item in result["interactions"] if item.get("account_id") == target_id
        ]
        assert {item["kind"] for item in account_events} == {"pointerdown", "click"}
        assert all(item["bounding_box"] for item in account_events)
        assert any(
            item["kind"] == "request" and item["url"]["path"] == "/switch"
            for item in result["network"]
        )
        response = next(
            item
            for item in result["network"]
            if item["kind"] == "browser-fetch-response" and item["url"]["path"] == "/switch"
        )
        assert response["json_shape"]["business_status"] == {"code": 0}
        assert any(item.get("account") == f"ID: {target_id}" for item in result["checkpoints"])
        serialized = json.dumps(result)
        assert "supersecret" not in serialized
        assert "session-secret" not in serialized

        await page.set_content("<button>ID: 111111</button>")
        missing = await PROBE["select_subaccount"](page, target_id)
        assert missing == {"clicked": False, "reason": "TARGET_ID_NOT_PRESENT"}
        await page.set_content(f"<button>ID: {target_id}</button><button>ID: {target_id}</button>")
        ambiguous = await PROBE["select_subaccount"](page, target_id)
        assert ambiguous == {
            "clicked": False,
            "reason": "TARGET_ID_AMBIGUOUS",
            "candidate_count": 2,
        }
        await context.close()
        await browser.close()
