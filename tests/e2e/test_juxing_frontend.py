"""KJX-01 stage B: juxing product pages in a real Chromium with synthetic API responses.

No backend, database or platform access: every API response is a route-fulfilled synthetic fixture.
This proves the product UI renders juxing platform semantics (library list/detail, task counts, task
creator detail) and never mounts Xingtu-only sub-resources.  Screenshots are written under
``.runtime/test-artifacts/kjx-stage-b``.
"""

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.async_api import Route, async_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
ARTIFACTS = ROOT / ".runtime" / "test-artifacts" / "kjx-stage-b"
TASK_ID = "77777777-7777-4777-8777-777777777777"
CREATOR_ID = "88888888-8888-4888-8888-888888888888"
SNAPSHOT_ID = "99999999-9999-4999-8999-999999999999"

USER = {
    "user_id": "user-a",
    "username": "media-a",
    "display_name": "媒介 A",
    "csrf_token": "csrf-token",
}

COUNT = {
    "target_count": 1,
    "discovered_count": 1,
    "valid_count": 1,
    "profile_complete_count": 1,
    "featured_complete_count": 0,
    "failed_count": 0,
}

TASK = {
    "root_task_id": TASK_ID,
    "platform": "kuaishou_juxing",
    "task_kind": "collection",
    "status": "COMPLETED",
    "stage": "已完成",
    "version": 5,
    "created_at": "2026-10-27T20:00:00Z",
    "updated_at": "2026-10-27T20:10:00Z",
    "completed_at": "2026-10-27T20:10:00Z",
    "created_by": "user-a",
    "created_by_name": "媒介 A",
    "source": "product",
    "keyword": "母婴",
    "counts": COUNT,
    "allowed_actions": [],
    "failure_reason": None,
}

DETAIL = {
    **TASK,
    "requirement": {
        "schema_version": "requirement_form.v3",
        "platform": "kuaishou_juxing",
        "keyword": "母婴",
        "content_types": ["maternal_child"],
        "creator_types": [],
        "followers": None,
        "creator_gender": None,
        "creator_regions": [],
        "creator_education": None,
        "yellow_v_certification": None,
        "connection_users": None,
        "viewer_profile": None,
        "fan_profile": None,
        "quote": None,
        "juxing_video_quotes": None,
        "sort_key": None,
        "target_count": 1,
    },
    "capability_version": "juxing-video-square-stage-b-v1",
    "plan": None,
    "field_errors": [],
    "origin_root_task_id": None,
    "challenge": None,
    "intake": None,
    "update_targets": [],
    "retry_plan": None,
}

PAYLOAD = {
    "modules": {
        "basic": {
            "status": "COLLECTED",
            "fields": [
                {"field_key": "nickname", "value": "聚星同名达人", "status": "COLLECTED"},
                {"field_key": "province", "value": "广东省", "status": "COLLECTED"},
                {"field_key": "city", "value": "深圳市", "status": "COLLECTED"},
                {
                    "field_key": "content_type_labels",
                    "value": ["母婴亲子"],
                    "status": "COLLECTED",
                },
                {
                    "field_key": "followers",
                    "value": {"kind": "number", "amount": "21686076", "bound": "exact"},
                    "status": "COLLECTED",
                    "unit": "count",
                },
                {
                    "field_key": "monthly_follower_growth_count",
                    "value": {"kind": "number", "amount": "268703", "bound": "exact"},
                    "status": "COLLECTED",
                    "unit": "count",
                    "period_label": "近30天",
                },
                {
                    "field_key": "monthly_follower_growth_rate",
                    "value": {"kind": "number", "amount": "0.0125", "bound": "exact"},
                    "status": "COLLECTED",
                    "unit": "ratio",
                    "period_label": "近30天",
                },
                {
                    "field_key": "cooperation_offers",
                    "status": "COLLECTED",
                    "value": {
                        "kind": "structured",
                        "data": [
                            {
                                "duration": "1-20秒",
                                "platform_price_raw": 20000,
                                "price_yuan": 20,
                                "currency": "CNY",
                            }
                        ],
                    },
                },
            ],
        },
        "spread": {
            "status": "COLLECTED",
            "fields": [
                {
                    "field_key": "play_median",
                    "value": {"kind": "number", "amount": "13092269", "bound": "exact"},
                    "status": "COLLECTED",
                    "unit": "count",
                    "period_label": "近30天/流量范围7天",
                },
                {
                    "field_key": "expected_cpm",
                    "value": {"kind": "number", "amount": "20", "bound": "exact"},
                    "status": "COLLECTED",
                    "unit": "CNY_per_thousand_impressions",
                },
                {
                    "field_key": "video_count",
                    "value": {"kind": "number", "amount": "15", "bound": "exact"},
                    "status": "COLLECTED",
                    "unit": "count",
                },
            ],
        },
        "works": {
            "status": "COLLECTED",
            "fields": [
                {
                    "field_key": "works",
                    "status": "COLLECTED",
                    "value": {
                        "kind": "structured",
                        "data": [
                            {
                                "platform_content_id": "w1",
                                "title": "合成作品",
                                "play_count": 100,
                                "like_count": 10,
                                "comment_count": 2,
                                "share_count": 1,
                                "published_at_ms": 1760000000000,
                            }
                        ],
                    },
                }
            ],
        },
        "audience": {
            "status": "COLLECTED",
            "fields": [
                {
                    "field_key": "fan_portrait",
                    "status": "COLLECTED",
                    "period_label": "近30天",
                    "value": {"kind": "structured", "data": {"gender": {"male": 0.4}}},
                }
            ],
        },
    },
    "profile_complete": True,
    "pipeline_complete": True,
}

LIBRARY_SUMMARY = {
    "creator_id": CREATOR_ID,
    "platform": "kuaishou_juxing",
    "platform_creator_id": "578000000001",
    "display_name": "聚星同名达人",
    "avatar_uri": None,
    "creator_type_label": None,
    "province": "广东省",
    "city": "深圳市",
    "industry_labels": [],
    "content_theme_labels": ["母婴亲子"],
    "followers": {
        "value": "21686076",
        "raw_value": "21686076",
        "unit": "count",
        "is_approximate": False,
        "status": "COLLECTED",
        "observed_at": None,
    },
    "monthly_deep_users": {
        "value": None,
        "raw_value": None,
        "unit": None,
        "is_approximate": False,
        "status": "NOT_AVAILABLE",
        "observed_at": None,
    },
    "monthly_connected_users": {
        "value": None,
        "raw_value": None,
        "unit": None,
        "is_approximate": False,
        "status": "NOT_AVAILABLE",
        "observed_at": None,
    },
    "monthly_follower_growth_rate": {
        "value": "0.0125",
        "raw_value": "0.0125",
        "unit": "ratio",
        "is_approximate": False,
        "status": "COLLECTED",
        "observed_at": None,
    },
    "interaction_rate": {
        "value": None,
        "raw_value": None,
        "unit": None,
        "is_approximate": False,
        "status": "NOT_AVAILABLE",
        "observed_at": None,
    },
    "completion_rate": {
        "value": None,
        "raw_value": None,
        "unit": None,
        "is_approximate": False,
        "status": "NOT_AVAILABLE",
        "observed_at": None,
    },
    "play_median": {
        "value": "13092269",
        "raw_value": "13092269",
        "unit": "count",
        "is_approximate": False,
        "status": "COLLECTED",
        "observed_at": None,
    },
    "average_duration": {
        "value": "10.476",
        "raw_value": "10.476",
        "unit": "seconds",
        "is_approximate": False,
        "status": "COLLECTED",
        "observed_at": None,
    },
    "average_likes": {
        "value": "2",
        "raw_value": "2",
        "unit": "count",
        "is_approximate": False,
        "status": "COLLECTED",
        "observed_at": None,
    },
    "average_comments": {
        "value": None,
        "raw_value": None,
        "unit": None,
        "is_approximate": False,
        "status": "NOT_AVAILABLE",
        "observed_at": None,
    },
    "average_shares": {
        "value": None,
        "raw_value": None,
        "unit": None,
        "is_approximate": False,
        "status": "NOT_AVAILABLE",
        "observed_at": None,
    },
    "expected_cpm_21_60": {
        "value": None,
        "raw_value": None,
        "unit": None,
        "is_approximate": False,
        "status": "NOT_AVAILABLE",
        "observed_at": None,
    },
    "expected_cpm_60_plus": {
        "value": None,
        "raw_value": None,
        "unit": None,
        "is_approximate": False,
        "status": "NOT_AVAILABLE",
        "observed_at": None,
    },
    "expected_cpe_21_60": {
        "value": None,
        "raw_value": None,
        "unit": None,
        "is_approximate": False,
        "status": "NOT_AVAILABLE",
        "observed_at": None,
    },
    "expected_cpe_60_plus": {
        "value": None,
        "raw_value": None,
        "unit": None,
        "is_approximate": False,
        "status": "NOT_AVAILABLE",
        "observed_at": None,
    },
    "profile_complete": True,
    "pipeline_complete": True,
    "data_updated_at": "2026-10-27T20:00:00+08:00",
}

LIBRARY_DETAIL = {
    **LIBRARY_SUMMARY,
    "latest_snapshot_id": SNAPSHOT_ID,
    "mcn_name": "合成 MCN",
    "introduction": "合成简介",
    "gender": None,
    "collected_field_count": 19,
    "failed_field_count": 0,
    "field_sources": {},
    "module_statuses": {
        "basic": "COLLECTED",
        "spread": "COLLECTED",
        "works": "COLLECTED",
        "audience": "COLLECTED",
    },
    "profile_payload": PAYLOAD,
}

CREATOR = {
    "creator_id": CREATOR_ID,
    "platform": "kuaishou_juxing",
    "platform_creator_id": "578000000001",
    "first_position": 0,
    "view_kind": "published",
    "snapshot_id": SNAPSHOT_ID,
    "observed_at": "2026-10-27T20:00:00+08:00",
    "payload": PAYLOAD,
}

CATALOG = {
    "platform": "kuaishou_juxing",
    "contract_version": "juxing-test",
    "modules": [
        {
            "key": "basic",
            "fields": [
                {
                    "key": "nickname",
                    "name": "昵称",
                    "contract_name": "昵称",
                    "name_source": "contract",
                    "kind": "text",
                    "unit": None,
                    "period_label": None,
                    "empty_values": [],
                    "missing_source_status": None,
                },
                {
                    "key": "province",
                    "name": "省份",
                    "contract_name": "省份",
                    "name_source": "contract",
                    "kind": "text",
                    "unit": None,
                    "period_label": None,
                    "empty_values": [],
                    "missing_source_status": None,
                },
                {
                    "key": "city",
                    "name": "城市",
                    "contract_name": "城市",
                    "name_source": "contract",
                    "kind": "text",
                    "unit": None,
                    "period_label": None,
                    "empty_values": [],
                    "missing_source_status": None,
                },
                {
                    "key": "content_type_labels",
                    "name": "内容类型",
                    "contract_name": "内容类型",
                    "name_source": "contract",
                    "kind": "tags",
                    "unit": None,
                    "period_label": None,
                    "empty_values": [],
                    "missing_source_status": None,
                },
                {
                    "key": "followers",
                    "name": "粉丝数",
                    "contract_name": "粉丝数",
                    "name_source": "contract",
                    "kind": "number",
                    "unit": "count",
                    "period_label": None,
                    "empty_values": [],
                    "missing_source_status": None,
                },
                {
                    "key": "monthly_follower_growth_count",
                    "name": "近30天涨粉",
                    "contract_name": "近30天涨粉",
                    "name_source": "contract",
                    "kind": "number",
                    "unit": "count",
                    "period_label": None,
                    "empty_values": [],
                    "missing_source_status": None,
                },
                {
                    "key": "monthly_follower_growth_rate",
                    "name": "月涨粉率",
                    "contract_name": "月涨粉率",
                    "name_source": "contract",
                    "kind": "ratio",
                    "unit": "ratio",
                    "period_label": None,
                    "empty_values": [],
                    "missing_source_status": None,
                },
                {
                    "key": "cooperation_offers",
                    "name": "视频报价",
                    "contract_name": "视频报价",
                    "name_source": "contract",
                    "kind": "structured",
                    "unit": None,
                    "period_label": None,
                    "empty_values": [],
                    "missing_source_status": None,
                },
            ],
        },
        {
            "key": "spread",
            "fields": [
                {
                    "key": "play_median",
                    "name": "播放量中位数",
                    "contract_name": "播放量中位数",
                    "name_source": "contract",
                    "kind": "number",
                    "unit": "count",
                    "period_label": None,
                    "empty_values": [],
                    "missing_source_status": None,
                },
                {
                    "key": "expected_cpm",
                    "name": "预期 CPM",
                    "contract_name": "预期 CPM",
                    "name_source": "contract",
                    "kind": "number",
                    "unit": "CNY_per_thousand_impressions",
                    "period_label": None,
                    "empty_values": [],
                    "missing_source_status": None,
                },
                {
                    "key": "video_count",
                    "name": "视频数",
                    "contract_name": "视频数",
                    "name_source": "contract",
                    "kind": "number",
                    "unit": "count",
                    "period_label": None,
                    "empty_values": [],
                    "missing_source_status": None,
                },
            ],
        },
        {
            "key": "works",
            "fields": [
                {
                    "key": "works",
                    "name": "代表及近期作品",
                    "contract_name": "代表及近期作品",
                    "name_source": "contract",
                    "kind": "structured",
                    "unit": None,
                    "period_label": None,
                    "empty_values": [],
                    "missing_source_status": None,
                }
            ],
        },
        {
            "key": "audience",
            "fields": [
                {
                    "key": "fan_portrait",
                    "name": "粉丝画像",
                    "contract_name": "粉丝画像",
                    "name_source": "contract",
                    "kind": "structured",
                    "unit": None,
                    "period_label": None,
                    "empty_values": [],
                    "missing_source_status": None,
                },
                {
                    "key": "viewer_portrait",
                    "name": "观众画像",
                    "contract_name": "观众画像",
                    "name_source": "contract",
                    "kind": "structured",
                    "unit": None,
                    "period_label": None,
                    "empty_values": [],
                    "missing_source_status": None,
                },
            ],
        },
    ],
}


@pytest.fixture(scope="module")
def frontend_url():
    if not (FRONTEND / "node_modules" / ".bin" / "vite").exists():
        pytest.skip("frontend dependencies are not installed")
    environment = dict(os.environ)
    for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        environment.pop(key, None)
    environment.update({"NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"})
    process = subprocess.Popen(
        ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "4175"],
        cwd=FRONTEND,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        env=environment,
    )
    url = "http://127.0.0.1:4175"
    for _ in range(80):
        try:
            urllib.request.urlopen(url, timeout=0.25).read(1)
            break
        except Exception:
            if process.poll() is not None:
                pytest.fail("Vite development server exited before becoming ready")
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


async def fulfill_json(route: Route, body, status=200):
    await route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(body, ensure_ascii=False),
    )


REQUESTED: list[str] = []


async def juxing_api(route: Route):
    request = route.request
    path = request.url.split("4175", 1)[-1]
    REQUESTED.append(path)
    if path == "/api/auth/me":
        return await fulfill_json(route, USER)
    if path == "/api/platforms/kuaishou_juxing/profile-field-catalog":
        return await fulfill_json(route, CATALOG)
    if path.startswith("/api/creator-library?"):
        return await fulfill_json(route, {"items": [LIBRARY_SUMMARY], "next_cursor": None})
    if path == f"/api/creator-library/{CREATOR_ID}":
        return await fulfill_json(route, LIBRARY_DETAIL)
    if path == f"/api/tasks/{TASK_ID}":
        return await fulfill_json(route, DETAIL)
    if path.startswith(f"/api/tasks/{TASK_ID}/creators?"):
        return await fulfill_json(route, {"items": [CREATOR], "next_cursor": None})
    if path == f"/api/tasks/{TASK_ID}/creators/{CREATOR_ID}":
        return await fulfill_json(route, CREATOR)
    return await fulfill_json(route, {"code": "NOT_FOUND", "message": "not found"}, 404)


async def test_juxing_library_list_and_detail_render_in_chromium(frontend_url):
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    REQUESTED.clear()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        await page.route("**/api/**", juxing_api)

        await page.goto(f"{frontend_url}/creators?platform=kuaishou_juxing")
        await expect(page.get_by_role("heading", name="磁力聚星达人")).to_be_visible()
        await expect(page.get_by_text("聚星同名达人")).to_be_visible()
        await expect(page.get_by_text("月涨粉率")).to_be_visible()
        # The Xingtu-only filters must not be offered for the juxing platform.
        await expect(page.get_by_label("按行业筛选")).to_have_count(0)
        await expect(page.get_by_label("按合作形式筛选")).to_have_count(0)
        await page.screenshot(path=ARTIFACTS / "juxing-library-list.png", full_page=True)

        await page.get_by_text("聚星同名达人").click()
        await expect(page.get_by_text("快手ID")).to_be_visible()
        await expect(page.get_by_role("tab", name="基础资料")).to_have_attribute(
            "aria-selected", "true"
        )
        await expect(page.get_by_text("1-20秒")).to_be_visible()
        await expect(page.get_by_text("20 元")).to_be_visible()
        await page.screenshot(path=ARTIFACTS / "juxing-library-detail-basic.png", full_page=True)

        await page.get_by_role("tab", name="传播表现").click()
        await expect(page.get_by_text("播放量中位数")).to_be_visible()
        await expect(page.get_by_text("预期 CPM")).to_be_visible()
        await page.get_by_role("tab", name="代表作品").click()
        await expect(page.get_by_text("合成作品")).to_be_visible()
        await page.get_by_role("tab", name="受众画像").click()
        await expect(page.get_by_text("粉丝画像")).to_be_visible()
        await page.screenshot(path=ARTIFACTS / "juxing-library-detail-chapters.png", full_page=True)

        # The juxing library must never touch Xingtu-only sub-resources.
        assert not [path for path in REQUESTED if path.endswith(("/quotes", "/update", "/videos"))]
        assert not [path for path in REQUESTED if "/contents" in path]
        await browser.close()


async def test_juxing_task_and_task_creator_detail_render_in_chromium(frontend_url):
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    REQUESTED.clear()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        await page.route("**/api/**", juxing_api)

        await page.goto(f"{frontend_url}/tasks/{TASK_ID}")
        await expect(page.get_by_text("磁力聚星 · 短视频广场", exact=True)).to_be_visible()
        await expect(page.get_by_text("精选完整")).to_have_count(0)
        await expect(page.get_by_text("F06 双集合")).to_have_count(0)
        await expect(page.get_by_text("聚星同名达人")).to_be_visible()
        await page.screenshot(path=ARTIFACTS / "juxing-task-detail.png", full_page=True)

        await page.get_by_text("聚星同名达人").click()
        await expect(page.get_by_text("快手ID")).to_be_visible()
        await expect(page.get_by_role("tab", name="代表作品")).to_be_visible()
        await page.get_by_role("tab", name="代表作品").click()
        await expect(page.get_by_text("合成作品")).to_be_visible()
        await page.screenshot(path=ARTIFACTS / "juxing-task-creator-detail.png", full_page=True)

        assert not [path for path in REQUESTED if "/contents" in path]
        assert not [path for path in REQUESTED if "/videos" in path]
        await browser.close()
