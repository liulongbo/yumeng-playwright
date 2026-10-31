"""KJX-01：磁力聚星统一达人库读模型（隔离 PostgreSQL，合成形状，非真实平台验收）。

These fixtures mirror the persisted juxing shape measured in stage B: identity in
`platform_creators`, current observations in `projection` envelopes keyed `module.field`, and the
immutable snapshot in `creator_snapshots.payload`.  A juxing creator has no
`douyin_xingtu_creator_*` row, so every assertion here is also an isolation check.
"""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from xingtu.contracts import PlatformRegistry
from xingtu.creator_update import CreatorUpdateService
from xingtu.domain import CollectorError, Filter, FilterPlan, uid
from xingtu.product_api import ProductServices, ProductSettings, create_app
from xingtu.product_auth import AuthService, MemoryLoginLimiter, PasswordService
from xingtu.product_covers import ProductCoverConfig
from xingtu.product_queries import ProductQueries
from xingtu.product_repository import ProductRepository
from xingtu.repository import Repository

JUXING_CONTRACT = "juxing-video-creator-stage-c-v3"
OBSERVED_AT = "2026-10-27T20:00:00+08:00"


def _number(amount: str, *, bound: str = "exact") -> dict[str, object]:
    return {"kind": "number", "amount": amount, "bound": bound, "quantum": "1"}


def _structured(data: object) -> dict[str, object]:
    return {"kind": "structured", "data": data}


def _envelope(
    field_key: str,
    value: object,
    *,
    unit: str | None = None,
    period: str | None = None,
    raw: str | None = None,
    status: str = "COLLECTED",
    path: str = "data.synthetic",
    approximate: bool = False,
) -> dict[str, object]:
    return {
        "field_key": field_key,
        "value": value,
        "raw_value": raw,
        "unit": unit,
        "period_label": period,
        "observed_at": OBSERVED_AT,
        "status": status,
        "source_kind": "response" if status == "COLLECTED" else None,
        "source_contract": JUXING_CONTRACT if status == "COLLECTED" else None,
        "path_ref": path,
        "precision": None,
        "is_approximate": approximate,
        "truncated": False,
        "evidence_refs": [],
        "failure_reason": None,
        "operation_id": "synthetic-operation",
        "session_version": 1,
        "fallback_reason": None,
    }


def _juxing_projection(
    *,
    platform_creator_id: str,
    nickname: str,
    followers: str,
    growth_rate: str,
) -> dict[str, object]:
    projection: dict[str, object] = {
        "basic.platform_creator_id": _envelope(
            "platform_creator_id", platform_creator_id, path="data.userId"
        ),
        "basic.nickname": _envelope("nickname", nickname, path="data.name"),
        "basic.avatar_uri": _envelope(
            "avatar_uri", "https://synthetic.invalid/avatar.png", path="data.headUrl"
        ),
        "basic.province": _envelope("province", "广东省", path="data.address"),
        "basic.city": _envelope("city", "深圳市", path="data.address"),
        "basic.content_type_labels": _envelope(
            "content_type_labels", ["母婴亲子"], path="data.contentTypeTag"
        ),
        "basic.mcn_name": _envelope("mcn_name", "合成 MCN", path="data.mcnName"),
        "basic.introduction": _envelope("introduction", "合成简介", path="data.introduction"),
        "basic.followers": _envelope(
            "followers",
            _number(followers),
            unit="count",
            raw=followers,
            path="data.fansNumber",
        ),
        "basic.monthly_follower_growth_count": _envelope(
            "monthly_follower_growth_count",
            _number("268703"),
            unit="count",
            period="近30天",
            raw="268703",
            path="data.fansIncreaseNum",
        ),
        "basic.monthly_follower_growth_rate": _envelope(
            "monthly_follower_growth_rate",
            _number(growth_rate),
            unit="ratio",
            period="近30天",
            raw=growth_rate,
            path="data.fansIncreaseRate",
        ),
        "basic.cooperation_offers": _envelope(
            "cooperation_offers",
            _structured(
                [
                    {
                        "price_type": 1,
                        "duration": "1-20秒",
                        "platform_price_raw": 20000,
                        "price_yuan": 20,
                        "currency": "CNY",
                    }
                ]
            ),
            path="data.priceShowInfo",
        ),
        "spread.play_median": _envelope(
            "play_median",
            _number("13092269"),
            unit="count",
            period="近30天/流量范围7天",
            raw="13092269",
            path="data.natureStatistics.pplayMedian",
        ),
        "spread.expected_cpm": _envelope(
            "expected_cpm",
            _number("20"),
            unit="CNY_per_thousand_impressions",
            period="近30天/流量范围7天",
            raw="20",
            path="data.businessStatistics.beCPM",
        ),
        "spread.interaction_rate": _envelope(
            "interaction_rate",
            _number("0.03911"),
            unit="ratio",
            period="近30天/流量范围7天",
            raw="0.03911",
            path="data.natureStatistics.pinteractionRate",
        ),
        "works.works": _envelope(
            "works",
            _structured(
                [
                    {
                        "platform_content_id": "synthetic-work-1",
                        "title": "合成作品",
                        "media_url": "https://synthetic.invalid/media.mp4",
                        "cover_url": "https://synthetic.invalid/cover.png",
                        "play_count": 100,
                        "like_count": 10,
                        "comment_count": 2,
                        "share_count": 1,
                        "published_at_ms": 1760000000000,
                    }
                ]
            ),
            period="页面最多近半年15个作品",
            path="data.detailList",
        ),
        "audience.fan_portrait": _envelope(
            "fan_portrait",
            _structured({"gender": {"male": 0.4, "female": 0.6}}),
            period="近30天",
            path="data.fansPortrait",
        ),
        "audience.viewer_portrait": _envelope(
            "viewer_portrait",
            _structured({"gender": {"male": 0.5, "female": 0.5}}),
            period="近30天",
            path="data.viewerPortrait",
        ),
    }
    # A deliberately absent Xingtu-only dimension: the read model must not invent it.
    return projection


def _snapshot_payload(projection: dict[str, object], *, complete: bool) -> dict[str, object]:
    modules: dict[str, object] = {}
    for module_key in ("basic", "spread", "works", "audience"):
        fields = [value for key, value in projection.items() if key.split(".", 1)[0] == module_key]
        modules[module_key] = {
            "module_key": module_key,
            "status": "COLLECTED",
            "complete": complete,
            "observed_at": OBSERVED_AT,
            "module_observation_id": uid(),
            "failure_reason": None,
            "fields": fields,
        }
    return {
        "schema_version": "profile_snapshot.v1",
        "modules": modules,
        "collections": {},
        "profile_complete": complete,
        "profile_coverage": {"complete": complete},
        "featured_complete": False,
        "pipeline_complete": complete,
        "featured_status": "NOT_ATTEMPTED",
        "failure_reason": None,
    }


def _juxing_root(repo: Repository, key: str) -> str:
    plan = FilterPlan(
        schema_version="filter_plan.v3",
        platform="kuaishou_juxing",
        capability_version=JUXING_CONTRACT,
        target_count=1,
        filters=[Filter(field="keyword", operator="eq", value="母婴", source_fields=["keyword"])],
    )
    return repo.create(
        plan,
        "unit",
        key,
        "test",
        adapter_version="juxing-browser-v1",
        contract_version=JUXING_CONTRACT,
        modules=["basic", "spread", "works", "audience"],
    )


def _seed_juxing_creator(
    repo: Repository,
    *,
    key: str,
    platform_creator_id: str,
    nickname: str = "合成聚星达人",
    followers: str = "21686076",
    growth_rate: str = "0.0125",
    complete: bool = True,
    captured_at: datetime | None = None,
) -> tuple[str, str, str]:
    creator_id, snapshot_id = uid(), uid()
    root = _juxing_root(repo, key)
    captured_at = captured_at or datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
    projection = _juxing_projection(
        platform_creator_id=platform_creator_id,
        nickname=nickname,
        followers=followers,
        growth_rate=growth_rate,
    )
    payload = _snapshot_payload(projection, complete=complete)
    with repo.connect() as conn:
        conn.execute(
            """INSERT INTO platform_creators(creator_id,platform,platform_creator_id,projection)
            VALUES(%s,'kuaishou_juxing',%s,%s)""",
            (creator_id, platform_creator_id, Jsonb(projection)),
        )
        conn.execute(
            """INSERT INTO creator_snapshots(
            snapshot_id,root_task_id,creator_id,draft_revision,payload,created_at)
            VALUES(%s,%s,%s,1,%s,%s)""",
            (snapshot_id, root, creator_id, Jsonb(payload), captured_at),
        )
        conn.execute(
            """INSERT INTO task_creators(
            root_task_id,creator_id,first_position,valid,latest_snapshot_id)
            VALUES(%s,%s,0,true,%s)""",
            (root, creator_id, snapshot_id),
        )
    return root, creator_id, snapshot_id


def test_juxing_library_list_filters_sorting_and_zero_semantics(repo):
    _, creator_a, _ = _seed_juxing_creator(
        repo,
        key="kjx-library-a",
        platform_creator_id="578000000001",
        nickname="母婴达人 A",
        followers="21686076",
        growth_rate="0.0125",
        captured_at=datetime(2026, 10, 27, 12, 0, tzinfo=UTC),
    )
    _, creator_b, _ = _seed_juxing_creator(
        repo,
        key="kjx-library-b",
        platform_creator_id="578000000002",
        nickname="母婴达人 B",
        followers="0",
        growth_rate="0",
        complete=False,
        captured_at=datetime(2026, 10, 26, 12, 0, tzinfo=UTC),
    )
    queries = ProductQueries(repo)

    page = queries.list_creator_library(platform="kuaishou_juxing")
    assert [item.creator_id for item in page.items] == [creator_a, creator_b]
    assert all(item.platform == "kuaishou_juxing" for item in page.items)
    assert page.items[0].followers.value == 21686076
    assert page.items[0].followers.raw_value == "21686076"
    assert page.items[0].content_theme_labels == ["母婴亲子"]
    # Juxing has no Xingtu creator type/industry/deep-user projection.
    assert page.items[0].creator_type_label is None
    assert page.items[0].industry_labels == []
    assert page.items[0].monthly_deep_users.value is None
    assert page.items[0].monthly_deep_users.status != "COLLECTED"
    assert page.items[0].expected_cpm_21_60.value is None
    # A real platform zero is kept as 0; it is not conflated with "missing".
    assert page.items[1].followers.value == 0
    assert page.items[1].followers.raw_value == "0"
    assert page.items[1].profile_complete is False
    assert page.items[1].pipeline_complete is False

    assert [
        item.creator_id
        for item in queries.list_creator_library(
            platform="kuaishou_juxing", followers_min=1, sort="followers"
        ).items
    ] == [creator_a]
    assert [
        item.creator_id
        for item in queries.list_creator_library(
            platform="kuaishou_juxing", complete_only=True
        ).items
    ] == [creator_a]
    assert [
        item.creator_id
        for item in queries.list_creator_library(
            platform="kuaishou_juxing", province="广东省", city="深圳市"
        ).items
    ] == [creator_a, creator_b]
    assert [
        item.creator_id
        for item in queries.list_creator_library(
            platform="kuaishou_juxing", sort="followers", direction="asc"
        ).items
    ] == [creator_b, creator_a]

    first = queries.list_creator_library(platform="kuaishou_juxing", limit=1)
    assert first.next_cursor is not None
    second = queries.list_creator_library(
        platform="kuaishou_juxing", limit=1, cursor=first.next_cursor
    )
    assert [item.creator_id for item in second.items] == [creator_b]
    assert second.next_cursor is None

    # The Xingtu library read model never sees the juxing rows.
    assert queries.list_creator_library().items == []
    # A Xingtu-only filter is an explicit error for juxing, never silently ignored.
    for kwargs in (
        {"industry": "母婴"},
        {"creator_type": "生活"},
        {"interaction_min": 1},
        {"cooperation_form": "植入视频"},
    ):
        try:
            queries.list_creator_library(platform="kuaishou_juxing", **kwargs)
        except CollectorError as exc:
            assert exc.reason == "KUAISHOU_JUXING_LIBRARY_FILTER_UNSUPPORTED"
        else:  # pragma: no cover - the assertion above is the contract
            raise AssertionError(f"unsupported filter accepted: {kwargs}")
    try:
        queries.list_creator_library(platform="kuaishou_juxing", sort="interaction")
    except CollectorError as exc:
        assert exc.reason == "KUAISHOU_JUXING_LIBRARY_SORT_UNSUPPORTED"
    else:  # pragma: no cover
        raise AssertionError("unsupported juxing sort accepted")


def test_juxing_library_detail_payload_provenance_and_latest_snapshot(repo):
    root, creator_id, first_snapshot = _seed_juxing_creator(
        repo,
        key="kjx-library-detail",
        platform_creator_id="578000000003",
        complete=True,
        captured_at=datetime(2026, 10, 27, 12, 0, tzinfo=UTC),
    )
    # A newer snapshot of the same creator must win, and an unpublished latest state is explicit.
    newer_snapshot = uid()
    projection = _juxing_projection(
        platform_creator_id="578000000003",
        nickname="合成聚星达人",
        followers="21686076",
        growth_rate="0.0125",
    )
    with repo.connect() as conn:
        conn.execute(
            """INSERT INTO creator_snapshots(
            snapshot_id,root_task_id,creator_id,draft_revision,payload,created_at)
            VALUES(%s,%s,%s,2,%s,%s)""",
            (
                newer_snapshot,
                root,
                creator_id,
                Jsonb(_snapshot_payload(projection, complete=True)),
                datetime(2026, 10, 28, 12, 0, tzinfo=UTC),
            ),
        )
        conn.execute(
            "UPDATE task_creators SET latest_snapshot_id=%s "
            "WHERE root_task_id=%s AND creator_id=%s",
            (newer_snapshot, root, creator_id),
        )
    queries = ProductQueries(repo)
    detail = queries.get_creator_library(creator_id)
    assert detail.platform == "kuaishou_juxing"
    assert detail.latest_snapshot_id == newer_snapshot
    assert detail.display_name == "合成聚星达人"
    assert detail.mcn_name == "合成 MCN"
    assert detail.introduction == "合成简介"
    assert detail.gender is None
    assert detail.content_theme_labels == ["母婴亲子"]
    assert set(detail.module_statuses) == {"basic", "spread", "works", "audience"}
    assert detail.module_statuses["basic"] == "COLLECTED"
    assert detail.profile_complete is True
    assert detail.pipeline_complete is True
    assert detail.profile_payload["modules"]["works"]["fields"][0]["field_key"] == "works"
    stored_fields = [
        field for module in detail.profile_payload["modules"].values() for field in module["fields"]
    ]
    assert detail.collected_field_count == len(stored_fields)
    assert detail.failed_field_count == 0
    assert detail.field_sources["spread.interaction_rate"]["unit"] == "ratio"
    assert "period_label" not in detail.field_sources["basic.followers"]
    # Neutral, platform-native spread metrics are projected; Xingtu-only slots stay absent.
    assert detail.interaction_rate.value == Decimal("0.03911")
    assert detail.play_median.value == Decimal("13092269")
    assert detail.monthly_connected_users.value is None

    # The task-scoped shared creator query carries the actual platform.
    scoped = queries.get_creator(root, creator_id)
    assert scoped.platform == "kuaishou_juxing"
    assert scoped.snapshot_id == newer_snapshot

    # Xingtu-only library sub-resources answer "not applicable", not "creator not found".
    for method, kwargs, scope in (
        (queries.creator_library_history, {}, "HISTORY"),
        (queries.creator_library_quotes, {}, "QUOTES"),
        (queries.creator_library_videos, {}, "VIDEOS"),
    ):
        try:
            method(creator_id, **kwargs)
        except CollectorError as exc:
            assert exc.reason == f"KUAISHOU_JUXING_LIBRARY_{scope}_NOT_APPLICABLE"
        else:  # pragma: no cover
            raise AssertionError(f"juxing {scope} unexpectedly served Xingtu data")
    try:
        queries.creator_library_contents(creator_id, "excellent_reach")
    except CollectorError as exc:
        assert exc.reason == "KUAISHOU_JUXING_LIBRARY_CONTENTS_NOT_APPLICABLE"
    else:  # pragma: no cover
        raise AssertionError("juxing featured collections unexpectedly served")

    # A published snapshot is required to have a library entry; an identity alone is not enough.
    unpublished_id = uid()
    with repo.connect() as conn:
        conn.execute(
            """INSERT INTO platform_creators(creator_id,platform,platform_creator_id,projection)
            VALUES(%s,'kuaishou_juxing',%s,'{}'::jsonb)""",
            (unpublished_id, "578000000099"),
        )
    try:
        queries.get_creator_library(unpublished_id)
    except CollectorError as exc:
        assert exc.reason == "CREATOR_NOT_FOUND"
    else:  # pragma: no cover
        raise AssertionError("unpublished juxing identity served a library detail")
    assert first_snapshot != newer_snapshot

    # Creator updates are Xingtu-only in KJX-01 scope and must say so explicitly.
    registry = PlatformRegistry.model_validate_json(
        Path("contracts/douyin_xingtu.verified.json").read_text()
    )
    updates = CreatorUpdateService(repo, registry, None)
    for call in (
        lambda: updates.status(creator_id),
        lambda: updates.create_manual_update(creator_id, user_id="u", idempotency_key="k"),
    ):
        try:
            call()
        except CollectorError as exc:
            assert exc.reason == "KUAISHOU_JUXING_UPDATE_NOT_SUPPORTED"
        else:  # pragma: no cover
            raise AssertionError("juxing manual update unexpectedly accepted")


def _xingtu_seed(repo: Repository, platform_creator_id: str) -> str:
    """Minimal Xingtu current row so cross-platform isolation is observable in one query."""
    creator_id, snapshot_id = uid(), uid()
    root = repo.create(
        FilterPlan(
            schema_version="filter_plan.v1",
            platform="douyin_xingtu",
            capability_version="xingtu-live-v1",
            target_count=1,
            filters=[
                Filter(field="keyword", operator="eq", value="宠物", source_fields=["keyword"])
            ],
        ),
        "unit",
        "xingtu-library-" + creator_id,
        "test",
        adapter_version="browser-v1",
        contract_version="xingtu-live-v1",
        modules=["basic"],
    )
    with repo.connect() as conn:
        conn.execute(
            "INSERT INTO platform_creators(creator_id,platform,platform_creator_id) "
            "VALUES(%s,'douyin_xingtu',%s)",
            (creator_id, platform_creator_id),
        )
        conn.execute(
            """INSERT INTO creator_snapshots(
            snapshot_id,root_task_id,creator_id,draft_revision,payload)
            VALUES(%s,%s,%s,1,%s)""",
            (
                snapshot_id,
                root,
                creator_id,
                Jsonb({"modules": {}, "profile_complete": True, "pipeline_complete": True}),
            ),
        )
        conn.execute(
            """INSERT INTO douyin_xingtu_creator_current(
            creator_id,platform_creator_id,latest_snapshot_id,display_name,followers_count,
            profile_complete,pipeline_complete,field_sources)
            VALUES(%s,%s,%s,'星图同名达人',100,true,true,'{}'::jsonb)""",
            (creator_id, platform_creator_id, snapshot_id),
        )
    return creator_id


def test_juxing_library_api_platform_parameter_and_cross_platform_isolation(repo):
    _, juxing_creator, _ = _seed_juxing_creator(
        repo,
        key="kjx-library-api",
        platform_creator_id="578000000004",
        nickname="同名达人",
    )
    # Same platform_creator_id and display name on another platform: distinct identities.
    xingtu_creator = _xingtu_seed(repo, "578000000004")
    products = ProductRepository(repo)
    passwords = PasswordService()
    products.create_user("kjx-user", "聚星用户", passwords.hash("a-secure-password"), actor="test")
    registry_path = Path("contracts/douyin_xingtu.verified.json")
    juxing_registry_path = Path("contracts/kuaishou_juxing.verified.json")
    services = ProductServices(
        auth=AuthService(products, MemoryLoginLimiter(), passwords=passwords),
        products=products,
        queries=ProductQueries(repo),
        registry=PlatformRegistry.model_validate_json(registry_path.read_text()),
        covers=object(),
        settings=ProductSettings(
            database_url=repo.dsn,
            redis_url="unused",
            login_hmac_key=b"x" * 32,
            registry_path=registry_path,
            juxing_registry_path=juxing_registry_path,
            secure_cookie=True,
            allowed_origins=("https://app.test",),
            cover_config=ProductCoverConfig(
                kind="local",
                directory=Path(".runtime/covers"),
                allowed_root=Path(".runtime"),
            ),
        ),
        platform_registries={
            "kuaishou_juxing": PlatformRegistry.model_validate_json(
                juxing_registry_path.read_text()
            )
        },
    )
    client = TestClient(create_app(services), base_url="https://app.test")
    login = client.post(
        "/api/auth/login",
        headers={"Origin": "https://app.test"},
        json={"username": "kjx-user", "password": "a-secure-password"},
    )
    assert login.status_code == 200

    juxing_page = client.get("/api/creator-library?platform=kuaishou_juxing")
    assert juxing_page.status_code == 200
    assert [item["creator_id"] for item in juxing_page.json()["items"]] == [juxing_creator]
    assert juxing_page.json()["items"][0]["platform"] == "kuaishou_juxing"
    assert juxing_page.json()["items"][0]["content_theme_labels"] == ["母婴亲子"]

    xingtu_page = client.get("/api/creator-library?platform=douyin_xingtu")
    assert [item["creator_id"] for item in xingtu_page.json()["items"]] == [xingtu_creator]

    unsupported = client.get("/api/creator-library?platform=kuaishou_juxing&interaction_min=1")
    assert unsupported.status_code == 422
    assert unsupported.json()["code"] == "INVALID_FORM"
    assert unsupported.json()["message"] == "KUAISHOU_JUXING_LIBRARY_FILTER_UNSUPPORTED"

    detail = client.get(f"/api/creator-library/{juxing_creator}")
    assert detail.status_code == 200
    assert detail.json()["platform"] == "kuaishou_juxing"
    assert detail.json()["profile_payload"]["modules"]["basic"]["status"] == "COLLECTED"

    quotes = client.get(f"/api/creator-library/{juxing_creator}/quotes")
    assert quotes.status_code == 422
    assert quotes.json()["message"] == "KUAISHOU_JUXING_LIBRARY_QUOTES_NOT_APPLICABLE"

    catalog = client.get("/api/platforms/kuaishou_juxing/profile-field-catalog")
    assert catalog.status_code == 200
    assert catalog.json()["platform"] == "kuaishou_juxing"
    assert [module["key"] for module in catalog.json()["modules"]] == [
        "basic",
        "spread",
        "works",
        "audience",
    ]
    assert client.get("/api/platforms/douyin_xingtu/profile-field-catalog").json()["platform"] == (
        "douyin_xingtu"
    )
