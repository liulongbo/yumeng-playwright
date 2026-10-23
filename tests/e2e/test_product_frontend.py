"""M3 product-browser E2E with a real Chromium and synthetic API responses only."""

import asyncio
import json
import os
import subprocess
import urllib.request
from pathlib import Path

import pytest
from playwright.async_api import Route, async_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
ARTIFACTS = ROOT / ".runtime" / "test-artifacts" / "m3-frontend"
TASK_ID = "11111111-1111-4111-8111-111111111111"
CREATOR_ID = "22222222-2222-4222-8222-222222222222"


@pytest.fixture(scope="module")
def frontend_url():
    if not (FRONTEND / "node_modules" / ".bin" / "vite").exists():
        pytest.skip("frontend dependencies are not installed")
    environment = dict(os.environ)
    for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        environment.pop(key, None)
    environment.update({"NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"})
    process = subprocess.Popen(
        ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "4174"],
        cwd=FRONTEND,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        env=environment,
    )
    url = "http://127.0.0.1:4174"
    for _ in range(80):
        try:
            urllib.request.urlopen(url, timeout=0.25).read(1)
            break
        except Exception:
            if process.poll() is not None:
                pytest.fail("Vite development server exited before becoming ready")
            import time

            time.sleep(0.1)
    else:
        process.terminate()
        pytest.fail("Vite development server did not become ready")
    yield url
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


USER = {
    "user_id": "user-a",
    "username": "media-a",
    "display_name": "媒介 A",
    "csrf_token": "csrf-token",
}
COUNTS = {
    "target_count": 20,
    "discovered_count": 31,
    "valid_count": 8,
    "profile_complete_count": 6,
    "featured_complete_count": 4,
    "failed_count": 1,
}
TASK = {
    "root_task_id": TASK_ID,
    "status": "COLLECTING",
    "stage": "采集达人资料",
    "version": 3,
    "created_at": "2026-10-10T02:00:00Z",
    "updated_at": "2026-10-10T02:05:00Z",
    "created_by": "user-a",
    "created_by_name": "媒介 A",
    "source": "product",
    "keyword": "宠物",
    "counts": COUNTS,
    "allowed_actions": ["cancel"],
    "failure_reason": None,
}
DETAIL = {
    **TASK,
    "requirement": {
        "schema_version": "requirement_form.v1",
        "platform": "douyin_xingtu",
        "keyword": "宠物",
        "creator_types": [],
        "followers": None,
        "creator_gender": None,
        "creator_regions": [],
        "quote": None,
        "sort_key": None,
        "target_count": 20,
    },
    "capability_version": "xingtu-live-v1",
    "plan": None,
    "field_errors": [],
    "origin_root_task_id": None,
}
CREATOR = {
    "creator_id": CREATOR_ID,
    "platform_creator_id": "xingtu-creator-001",
    "first_position": 0,
    "view_kind": "published",
    "snapshot_id": "33333333-3333-4333-8333-333333333333",
    "observed_at": "2026-10-10T02:05:00Z",
    "payload": {
        "nickname": "小满和两只猫",
        "follower_count": 126800,
        "modules": {
            "basic": {
                "status": "COMPLETE",
                "fields": [
                    {"field_key": "nickname", "value": "小满和两只猫", "status": "COLLECTED"},
                    {"field_key": "follower_count", "value": 126800, "status": "COLLECTED"},
                ],
            },
            "commercial": {
                "status": "PARTIAL",
                "fields": [{"field_key": "expected_cpm", "value": 38.4, "status": "COLLECTED"}],
            },
        },
    },
}


async def fulfill_json(route: Route, body, status=200):
    await route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(body, ensure_ascii=False),
    )


async def synthetic_api(route: Route):
    request = route.request
    path = request.url.split("4174", 1)[-1]
    if path == "/api/auth/me":
        return await fulfill_json(route, USER)
    if path.startswith("/api/platforms/douyin_xingtu/capabilities"):
        return await fulfill_json(
            route,
            {
                "platform": "douyin_xingtu",
                "capability_version": "xingtu-live-v1",
                "fields": [
                    {
                        "field": "keyword",
                        "label": "内容关键词",
                        "operators": ["eq"],
                        "options": [],
                        "currencies": [],
                        "cooperation_forms": [],
                        "keyword_mode": "content",
                    }
                ],
                "combinations": [["keyword"]],
                "target_count_default": 20,
                "target_count_min": 1,
                "target_count_max": 200,
                "fixed_sort_key": "score",
                "fixed_sort_label": "平台默认排序",
            },
        )
    if path == "/api/tasks" and request.method == "POST":
        return await fulfill_json(route, {"root_task_id": TASK_ID, "status": "RECEIVED"}, 202)
    if path.startswith("/api/tasks?"):
        return await fulfill_json(route, {"items": [TASK], "next_cursor": None})
    if path == f"/api/tasks/{TASK_ID}":
        return await fulfill_json(route, DETAIL)
    if path.startswith(f"/api/tasks/{TASK_ID}/creators/{CREATOR_ID}/contents"):
        return await fulfill_json(
            route,
            {
                "view_kind": "published",
                "snapshot_id": CREATOR["snapshot_id"],
                "collection_type": "excellent_reach",
                "status": "COMPLETE",
                "cards": [
                    {
                        "card_id": "card-1",
                        "position": 0,
                        "cover_status": "NOT_ATTEMPTED",
                        "truncated_fields": [],
                        "payload": {
                            "title": "猫咪换粮的三件小事",
                            "platform_content_id": "video-001",
                            "canonical_link": "https://synthetic.invalid/video-001",
                            "fields": [
                                {
                                    "field_key": "title",
                                    "value": "猫咪换粮的三件小事",
                                    "status": "COLLECTED",
                                }
                            ],
                        },
                    }
                ],
                "next_cursor": None,
            },
        )
    if path == f"/api/tasks/{TASK_ID}/creators/{CREATOR_ID}":
        return await fulfill_json(route, CREATOR)
    if path.startswith(f"/api/tasks/{TASK_ID}/creators"):
        return await fulfill_json(route, {"items": [CREATOR], "next_cursor": None})
    return await fulfill_json(route, {"code": "NOT_FOUND", "message": "not found"}, 404)


async def test_product_login_establishes_session_and_restores_destination(frontend_url):
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    logged_in = False

    async def login_api(route: Route):
        nonlocal logged_in
        path = route.request.url.split("4174", 1)[-1]
        if path == "/api/auth/me":
            if logged_in:
                return await fulfill_json(route, USER)
            return await fulfill_json(
                route,
                {
                    "code": "ACCOUNT_LOGIN_REQUIRED",
                    "message": "LOGIN_REQUIRED",
                    "request_id": "login-test",
                },
                401,
            )
        if path == "/api/auth/login" and route.request.method == "POST":
            logged_in = True
            return await fulfill_json(route, USER)
        if path.startswith("/api/tasks?"):
            return await fulfill_json(route, {"items": [TASK], "next_cursor": None})
        return await fulfill_json(route, {"code": "NOT_FOUND", "message": "not found"}, 404)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        await page.route("**/api/**", login_api)
        await page.goto(f"{frontend_url}/tasks")
        await expect(page.get_by_role("heading", name="欢迎回来")).to_be_visible()
        await page.screenshot(path=ARTIFACTS / "login.png", full_page=True)
        await page.get_by_label("产品账号").fill("media-a")
        await page.locator('input[type="password"]').fill("a-secure-password")
        await page.get_by_role("button", name="安全登录").click()
        await expect(page).to_have_url(f"{frontend_url}/tasks")
        await expect(page.get_by_role("heading", name="任务中心")).to_be_visible()
        await browser.close()


async def test_media_user_can_submit_track_and_open_results(frontend_url):
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        await page.route("**/api/**", synthetic_api)

        await page.goto(f"{frontend_url}/tasks")
        await expect(page.get_by_role("heading", name="任务中心")).to_be_visible()
        await expect(page.get_by_text("宠物", exact=True)).to_be_visible()
        await page.screenshot(path=ARTIFACTS / "tasks.png", full_page=True)

        await page.get_by_text("宠物", exact=True).click()
        await expect(page.get_by_role("heading", name="宠物")).to_be_visible()
        await expect(page.get_by_text("采集达人资料").first).to_be_visible()
        await expect(page.get_by_text("小满和两只猫")).to_be_visible()

        await page.get_by_text("小满和两只猫").click()
        await expect(page.get_by_role("heading", name="小满和两只猫")).to_be_visible()
        await expect(page.get_by_role("heading", name="优秀传播视频", exact=True)).to_be_visible()
        await expect(page.get_by_text("猫咪换粮的三件小事").first).to_be_visible()
        await page.screenshot(path=ARTIFACTS / "creator-detail.png", full_page=True)

        await page.goto(f"{frontend_url}/tasks/new")
        await expect(page.get_by_role("heading", name="创建采集任务")).to_be_visible()
        await page.get_by_placeholder("例如：宠物、母婴辅食、户外露营").fill("宠物")
        async with page.expect_request(
            lambda req: req.url.endswith("/api/tasks") and req.method == "POST"
        ) as submitted:
            await page.get_by_role("button", name="提交采集任务").click()
        request = await submitted.value
        assert request.headers["idempotency-key"]
        assert request.post_data_json["target_count"] == 20
        await expect(page).to_have_url(f"{frontend_url}/tasks/{TASK_ID}")

        await browser.close()
        await asyncio.sleep(0)
