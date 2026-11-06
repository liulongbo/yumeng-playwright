"""KJX-01 stage B: isolated full-stack UI check (real API + PostgreSQL + Chromium).

Starts the real FastAPI app on 127.0.0.1:4181 against a random schema in the isolated
``xingtu_test*`` database, starts the real Vite frontend on 127.0.0.1:4180, logs in through the real
auth flow and reads a seeded juxing task/creator.  No platform access, no business database, no
production Feature Flag.  The schema is dropped afterwards.

If the environment cannot start these loopback processes the test skips; the component + route-mock
coverage remains the evidence baseline.
"""

from __future__ import annotations

import os
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from playwright.async_api import async_playwright, expect
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb
from xingtu.domain import Filter, FilterPlan, TaskStatus, uid
from xingtu.product_auth import PasswordService
from xingtu.product_repository import ProductRepository
from xingtu.repository import Repository

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
ARTIFACTS = ROOT / ".runtime" / "test-artifacts" / "kjx-stage-b"
JUXING_CONTRACT = "juxing-video-creator-stage-b-v1"
JUXING_ADAPTER = "juxing-browser-v1"
USERNAME = "ui-media"
PASSWORD = "ui-media-password"


def _isolated_redis_url() -> str:
    """Use the configured Redis endpoint on a dedicated logical database.

    The local development Redis lives on a non-default port and requires the credentials from
    ``XINGTU_REDIS_URL``.  Hard-coding ``127.0.0.1:6379`` made this check fail with
    ``LOGIN_LIMITER_UNAVAILABLE`` on every machine that runs the documented local stack.  The
    database index is still pinned so the rate-limit keys of this check stay isolated.
    """

    configured = os.environ.get("XINGTU_REDIS_URL")
    if not configured:
        return "redis://127.0.0.1:6379/15"
    parts = urlsplit(configured)
    return urlunsplit((parts.scheme, parts.netloc, "/15", "", ""))


def _number(amount: str) -> dict[str, object]:
    return {"kind": "number", "amount": amount, "bound": "exact", "quantum": "1"}


def _envelope(field_key: str, value: object, **extra: object) -> dict[str, object]:
    return {
        "field_key": field_key,
        "value": value,
        "raw_value": extra.pop("raw_value", None),
        "unit": extra.pop("unit", None),
        "period_label": extra.pop("period_label", None),
        "observed_at": "2026-10-27T20:00:00+08:00",
        "status": "COLLECTED",
        "source_kind": "response",
        "source_contract": JUXING_CONTRACT,
        "path_ref": "data.synthetic",
        "precision": None,
        "is_approximate": False,
        "truncated": False,
        "evidence_refs": [],
        "failure_reason": None,
        "operation_id": "synthetic",
        "session_version": 1,
        "fallback_reason": None,
    }


def _projection(platform_creator_id: str) -> dict[str, object]:
    return {
        "basic.platform_creator_id": _envelope("platform_creator_id", platform_creator_id),
        "basic.nickname": _envelope("nickname", "聚星同名达人"),
        "basic.province": _envelope("province", "广东省"),
        "basic.city": _envelope("city", "深圳市"),
        "basic.content_type_labels": _envelope("content_type_labels", ["母婴亲子"]),
        "basic.mcn_name": _envelope("mcn_name", "合成 MCN"),
        "basic.introduction": _envelope("introduction", "合成简介"),
        "basic.followers": _envelope(
            "followers", _number("21686076"), unit="count", raw_value="21686076"
        ),
        "basic.monthly_follower_growth_count": _envelope(
            "monthly_follower_growth_count",
            _number("268703"),
            unit="count",
            period_label="近30天",
            raw_value="268703",
        ),
        "basic.monthly_follower_growth_rate": _envelope(
            "monthly_follower_growth_rate",
            _number("0.0125"),
            unit="ratio",
            period_label="近30天",
            raw_value="0.0125",
        ),
        "basic.cooperation_offers": _envelope(
            "cooperation_offers",
            {
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
        ),
        "spread.play_median": _envelope(
            "play_median",
            _number("13092269"),
            unit="count",
            period_label="近30天/流量范围7天",
            raw_value="13092269",
        ),
        "spread.expected_cpm": _envelope(
            "expected_cpm",
            _number("20"),
            unit="CNY_per_thousand_impressions",
            period_label="近30天/流量范围7天",
            raw_value="20",
        ),
        "spread.video_count": _envelope(
            "video_count", _number("15"), unit="count", period_label="近30天"
        ),
        "works.works": _envelope(
            "works",
            {
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
            period_label="页面最多近半年15个作品",
        ),
        "audience.fan_portrait": _envelope(
            "fan_portrait",
            {"kind": "structured", "data": {"gender": {"male": 0.4}}},
            period_label="近30天",
        ),
    }


def _snapshot(projection: dict[str, object]) -> dict[str, object]:
    modules = {}
    for key in ("basic", "spread", "works", "audience"):
        fields = [value for name, value in projection.items() if name.split(".", 1)[0] == key]
        modules[key] = {
            "module_key": key,
            "status": "COLLECTED",
            "complete": True,
            "observed_at": "2026-10-27T20:00:00+08:00",
            "module_observation_id": uid(),
            "failure_reason": None,
            "fields": fields,
        }
    return {
        "schema_version": "profile_snapshot.v1",
        "modules": modules,
        "collections": {},
        "profile_complete": True,
        "pipeline_complete": True,
        "featured_status": "NOT_ATTEMPTED",
        "failure_reason": None,
    }


def _seed(repository: Repository) -> str:
    """One completed juxing task plus one published creator, in the random test schema."""
    repository.register_unit("unit", "synthetic-account", "synthetic-line", "synthetic-profile")
    with repository.connect() as conn:
        conn.execute("UPDATE execution_units SET state='READY',session_version=1")
    plan = FilterPlan(
        schema_version="filter_plan.v3",
        platform="kuaishou_juxing",
        capability_version="juxing-video-square-stage-b-v1",
        target_count=1,
        filters=[Filter(field="keyword", operator="eq", value="母婴", source_fields=["keyword"])],
    )
    root = repository.create(
        plan,
        "unit",
        "kjx-ui-" + uuid4().hex,
        "test",
        adapter_version=JUXING_ADAPTER,
        contract_version=JUXING_CONTRACT,
        modules=["basic", "spread", "works", "audience"],
    )
    with repository.edit(root) as (task, _):
        task.state = TaskStatus.COMPLETED
        task.valid_count = 1
        task.profile_complete_count = 1
        task.pipeline_complete = True
        task.featured_complete_count = 0
    creator_id, snapshot_id = uid(), uid()
    platform_creator_id = "578000000001"
    projection = _projection(platform_creator_id)
    with repository.connect() as conn:
        conn.execute(
            """INSERT INTO platform_creators(creator_id,platform,platform_creator_id,projection)
            VALUES(%s,'kuaishou_juxing',%s,%s)""",
            (creator_id, platform_creator_id, Jsonb(projection)),
        )
        conn.execute(
            """INSERT INTO creator_snapshots(
            snapshot_id,root_task_id,creator_id,draft_revision,payload,created_at)
            VALUES(%s,%s,%s,1,%s,%s)""",
            (
                snapshot_id,
                root,
                creator_id,
                Jsonb(_snapshot(projection)),
                datetime(2026, 10, 27, 20, 0, tzinfo=UTC),
            ),
        )
        conn.execute(
            """INSERT INTO task_creators(
            root_task_id,creator_id,first_position,valid,latest_snapshot_id)
            VALUES(%s,%s,0,true,%s)""",
            (root, creator_id, snapshot_id),
        )
    ProductRepository(repository).create_user(
        USERNAME, "UI 媒介", PasswordService().hash(PASSWORD), actor="test"
    )
    return root


def _wait_http(url: str, *, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=0.5).read(1)
            return
        except urllib.error.HTTPError:
            return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError(f"service did not become ready: {url}")


@pytest.fixture(scope="module")
def full_stack() -> Iterator[dict[str, object]]:
    base_dsn = os.environ.get("XINGTU_TEST_DATABASE_URL")
    if not base_dsn:
        pytest.skip("XINGTU_TEST_DATABASE_URL required for the isolated full-stack UI check")
    if not (FRONTEND / "node_modules" / ".bin" / "vite").exists():
        pytest.skip("frontend dependencies are not installed")
    schema = "kjx_ui_" + uuid4().hex[:10]
    with psycopg.connect(base_dsn) as conn:
        database = conn.execute("SELECT current_database()").fetchone()[0]
        if not str(database).startswith("xingtu_test"):
            pytest.skip("refusing a non-test database")
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(base_dsn, options=f"-csearch_path={schema}")
    repository = Repository(dsn)
    repository.migrate(ROOT / "migrations")
    root = _seed(repository)

    api_env = dict(
        os.environ,
        XINGTU_DATABASE_URL=dsn,
        XINGTU_REDIS_URL=_isolated_redis_url(),
        XINGTU_LOGIN_HMAC_KEY="kjx-ui-fullstack-hmac-key-0123456789",
        XINGTU_ENABLE_KUAISHOU_JUXING="1",
        XINGTU_SECURE_COOKIE="0",
        XINGTU_ALLOWED_ORIGINS="http://127.0.0.1:4180",
        XINGTU_RUNTIME_ROOT=str(ROOT / ".runtime"),
        XINGTU_API_HOST="127.0.0.1",
        XINGTU_API_PORT="4181",
        PYTHONPATH=f"{ROOT}:{ROOT / 'backend' / 'src'}",
    )
    api = subprocess.Popen(
        [str(ROOT / ".venv/bin/xingtu-api")],
        cwd=ROOT,
        env=api_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    vite_env = dict(
        os.environ,
        XINGTU_FRONTEND_API_TARGET="http://127.0.0.1:4181",
        NO_PROXY="127.0.0.1,localhost",
        no_proxy="127.0.0.1,localhost",
    )
    for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        vite_env.pop(key, None)
    vite = subprocess.Popen(
        ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "4180"],
        cwd=FRONTEND,
        env=vite_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_http("http://127.0.0.1:4181/api/auth/me")
        _wait_http("http://127.0.0.1:4180")
        assert api.poll() is None, "API process exited"
        assert vite.poll() is None, "Vite process exited"
        yield {"url": "http://127.0.0.1:4180", "root": root}
    finally:
        for process in (vite, api):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        with psycopg.connect(base_dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


async def test_real_api_ui_serves_juxing_library_and_task(full_stack):
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    url = str(full_stack["url"])
    root = str(full_stack["root"])
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        await page.goto(f"{url}/login")
        await page.get_by_label("产品账号").fill(USERNAME)
        await page.locator('input[type="password"]').fill(PASSWORD)
        await page.get_by_role("button", name="安全登录").click()
        await expect(page).to_have_url(f"{url}/tasks")

        await page.goto(f"{url}/creators?platform=kuaishou_juxing")
        await expect(page.get_by_role("heading", name="磁力聚星达人")).to_be_visible()
        await expect(page.get_by_text("聚星同名达人")).to_be_visible()
        await expect(page.get_by_text("母婴亲子").first).to_be_visible()
        await page.screenshot(path=ARTIFACTS / "fullstack-juxing-library.png", full_page=True)

        await page.get_by_text("聚星同名达人").click()
        await expect(page.get_by_text("快手ID")).to_be_visible()
        await expect(page.get_by_role("tab", name="基础资料")).to_be_visible()
        await expect(page.get_by_text("1-20秒")).to_be_visible()
        await page.screenshot(
            path=ARTIFACTS / "fullstack-juxing-library-detail.png", full_page=True
        )

        await page.goto(f"{url}/tasks/{root}")
        await expect(page.get_by_text("磁力聚星 · 短视频广场", exact=True)).to_be_visible()
        await expect(page.get_by_text("精选完整")).to_have_count(0)
        await expect(page.get_by_text("聚星同名达人")).to_be_visible()
        await page.get_by_text("聚星同名达人").click()
        await expect(page.get_by_text("快手ID")).to_be_visible()
        await page.get_by_role("tab", name="代表作品").click()
        await expect(page.get_by_text("合成作品")).to_be_visible()
        await page.screenshot(path=ARTIFACTS / "fullstack-juxing-task-creator.png", full_page=True)
        await browser.close()
