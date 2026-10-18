import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from xingtu.contracts import PlatformRegistry
from xingtu.creator_library import CreatorLibraryWriter
from xingtu.domain import uid
from xingtu.product_api import ProductServices, ProductSettings, create_app
from xingtu.product_auth import AuthService, MemoryLoginLimiter, PasswordService
from xingtu.product_covers import ProductCoverConfig
from xingtu.product_queries import ProductQueries
from xingtu.product_repository import ProductRepository


def _seed_creator_library(repo, plan):
    root = repo.create(
        plan,
        "unit",
        "creator-library-seed",
        "test",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        modules=["basic"],
    )
    creator_id = uid()
    snapshot_id = uid()
    captured_at = datetime(2026, 10, 12, 8, 9, tzinfo=UTC)
    sources = {
        "followers_count": {
            "status": "COLLECTED",
            "unit": "count",
            "observed_at": captured_at.isoformat(),
            "source_contract": "test-v1",
        },
        "monthly_deep_users_count": {
            "status": "COLLECTED",
            "unit": "count",
            "observed_at": captured_at.isoformat(),
        },
    }
    with repo.connect() as conn:
        conn.execute(
            "INSERT INTO platform_creators(creator_id,platform,platform_creator_id) "
            "VALUES(%s,%s,%s)",
            (creator_id, "douyin_xingtu", "creator-library-sample"),
        )
        conn.execute(
            """INSERT INTO creator_snapshots(
            snapshot_id,root_task_id,creator_id,draft_revision,payload,created_at)
            VALUES(%s,%s,%s,1,%s,%s)""",
            (
                snapshot_id,
                root,
                creator_id,
                Jsonb({"modules": {}, "profile_complete": True, "pipeline_complete": True}),
                captured_at,
            ),
        )
        conn.execute(
            """INSERT INTO douyin_xingtu_creator_current(
            creator_id,platform_creator_id,latest_snapshot_id,display_name,creator_type_label,province,city,
            industry_labels,followers_count,followers_raw,monthly_deep_users_count,monthly_deep_users_raw,
            monthly_deep_users_is_approximate,interaction_rate_value_raw,completion_rate_value_raw,
            expected_cpm_21_60_raw,expected_cpe_21_60_raw,profile_complete,pipeline_complete,
            collected_field_count,failed_field_count,field_sources,data_updated_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true,%s,%s,%s,%s,true,true,80,0,%s,%s)""",
            (
                creator_id,
                "creator-library-sample",
                snapshot_id,
                "达人 A",
                "生活",
                "北京市",
                "朝阳区",
                Jsonb(["食品饮料", "汽车"]),
                5704674,
                "5704674",
                48899000,
                "4,889.9w",
                428,
                6343,
                10029,
                934,
                Jsonb(sources),
                captured_at,
            ),
        )
        conn.execute(
            """INSERT INTO douyin_xingtu_creator_snapshot_index(
            snapshot_id,creator_id,captured_at,profile_complete,pipeline_complete,module_statuses,metric_statuses,
            followers_count,monthly_deep_users_count,interaction_rate_value_raw,completion_rate_value_raw)
            VALUES(%s,%s,%s,true,true,%s,%s,%s,%s,%s,%s)""",
            (
                snapshot_id,
                creator_id,
                captured_at,
                Jsonb({"basic": "COLLECTED"}),
                Jsonb({"followers": "COLLECTED"}),
                5704674,
                48899000,
                428,
                6343,
            ),
        )
        conn.execute(
            """INSERT INTO douyin_xingtu_creator_quote_observations(
            snapshot_id,creator_id,position,cooperation_form,settlement_description,price_raw,offer_raw,observed_at)
            VALUES(%s,%s,0,%s,%s,%s,%s,%s)""",
            (
                snapshot_id,
                creator_id,
                "植入视频",
                "固定价格",
                60000,
                Jsonb({"desc": "植入视频", "price": 60000}),
                captured_at,
            ),
        )
    return creator_id, snapshot_id


def test_creator_library_query_reads_raw_metrics_history_quotes_and_filters(repo, plan):
    creator_id, snapshot_id = _seed_creator_library(repo, plan)
    queries = ProductQueries(repo)

    page = queries.list_creator_library(
        industry="食品饮料",
        creator_type="生活",
        followers_min=5_000_000,
        cooperation_form="植入视频",
    )
    assert [item.creator_id for item in page.items] == [creator_id]
    assert page.items[0].monthly_deep_users.raw_value == "4,889.9w"
    assert page.items[0].monthly_deep_users.is_approximate
    assert page.items[0].interaction_rate.raw_value == "428"

    detail = queries.get_creator_library(creator_id)
    assert detail.collected_field_count == 80
    assert detail.expected_cpm_21_60.raw_value == "10029"
    assert detail.field_sources["followers_count"]["source_contract"] == "test-v1"

    history = queries.creator_library_history(creator_id)
    assert history.items[0].snapshot_id == snapshot_id
    assert history.items[0].metrics["followers_count"] == 5704674
    quotes = queries.creator_library_quotes(creator_id)
    assert quotes[0].cooperation_form == "植入视频"
    assert quotes[0].price_raw == 60000


def test_creator_library_api_requires_login_and_returns_library_views(repo, plan):
    creator_id, _ = _seed_creator_library(repo, plan)
    products = ProductRepository(repo)
    passwords = PasswordService()
    products.create_user(
        "library-user", "达人库用户", passwords.hash("a-secure-password"), actor="test"
    )
    registry_path = Path("contracts/douyin_xingtu.verified.json")
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
            secure_cookie=True,
            allowed_origins=("https://app.test",),
            cover_config=ProductCoverConfig(
                kind="local", directory=Path(".runtime/covers"), allowed_root=Path(".runtime")
            ),
        ),
    )
    client = TestClient(create_app(services), base_url="https://app.test")
    assert client.get("/api/creator-library").status_code == 401
    login = client.post(
        "/api/auth/login",
        headers={"Origin": "https://app.test"},
        json={"username": "library-user", "password": "a-secure-password"},
    )
    assert login.status_code == 200
    page = client.get("/api/creator-library?industry=%E9%A3%9F%E5%93%81%E9%A5%AE%E6%96%99")
    assert page.status_code == 200
    assert page.json()["items"][0]["creator_id"] == creator_id
    assert client.get(f"/api/creator-library/{creator_id}/history").status_code == 200
    quotes = client.get(f"/api/creator-library/{creator_id}/quotes")
    assert quotes.json()[0]["cooperation_form"] == "植入视频"


def test_creator_library_writer_keeps_last_success_when_a_field_later_fails(repo, plan):
    creator_id, snapshot_id = _seed_creator_library(repo, plan)
    observed_at = datetime(2026, 10, 13, 8, 9, tzinfo=UTC)
    collected_followers = {
        "field_key": "followers",
        "status": "COLLECTED",
        "value": {"kind": "number", "amount": "5800000"},
        "raw_value": "5800000",
        "unit": "count",
        "observed_at": observed_at.isoformat(),
        "source_kind": "response",
        "source_contract": "test-v2",
    }
    snapshot = {
        "profile_complete": True,
        "pipeline_complete": True,
        "modules": {
            "basic": {"status": "COLLECTED", "fields": [collected_followers]},
            "commercial": {
                "status": "COLLECTED",
                "fields": [
                    {
                        "field_key": "cooperation_offers",
                        "status": "COLLECTED",
                        "value": {
                            "kind": "structured",
                            "data": [{"desc": "定制视频", "price": "75000"}],
                        },
                    }
                ],
            },
        },
    }
    writer = CreatorLibraryWriter()
    with repo.connect() as conn:
        writer.sync(
            conn,
            creator_id=creator_id,
            platform_creator_id="creator-library-sample",
            projection={"basic.followers": collected_followers},
            snapshot_id=snapshot_id,
            snapshot=snapshot,
            captured_at=observed_at,
        )
        writer.sync(
            conn,
            creator_id=creator_id,
            platform_creator_id="creator-library-sample",
            projection={"basic.followers": {"field_key": "followers", "status": "FAILED"}},
            snapshot_id=snapshot_id,
            snapshot=snapshot,
            captured_at=observed_at,
        )
        row = conn.execute(
            "SELECT followers_count,field_sources FROM douyin_xingtu_creator_current "
            "WHERE creator_id=%s",
            (creator_id,),
        ).fetchone()
        quote = conn.execute(
            "SELECT price_raw FROM douyin_xingtu_creator_quote_observations "
            "WHERE snapshot_id=%s AND position=0",
            (snapshot_id,),
        ).fetchone()
    assert row["followers_count"] == 5800000
    assert row["field_sources"]["followers_count"]["source_contract"] == "test-v2"
    assert quote["price_raw"] == 60000


def test_creator_library_writer_projects_video_metrics_and_work_observations(repo, plan):
    """DATA-02: the writer projects the five new metrics and appends one row per work record.

    Uses a second snapshot so the snapshot-index insert is exercised too (the seeded snapshot
    already has an index row, and that insert is intentionally `DO NOTHING`).
    """
    creator_id, seeded_snapshot_id = _seed_creator_library(repo, plan)
    observed_at = datetime(2026, 10, 16, 1, 43, 32, tzinfo=UTC)
    snapshot_id = uid()

    def structured(key: str, data: object) -> dict[str, object]:
        return {
            "field_key": key,
            "status": "COLLECTED",
            "value": {"kind": "structured", "data": data},
            "raw_value": json.dumps(data, ensure_ascii=False),
            "observed_at": observed_at.isoformat(),
            "source_kind": "response",
            "source_contract": "test-v1",
        }

    item_rate = structured(
        "item_rate_metrics",
        {
            "item_num": {"label": "", "value": 5},
            "play_mid": {"label": "", "value": 766187, "overtake": 9923},
        },
    )
    spread_fields = [
        item_rate,
        structured("play_median", "1399516"),
        structured("average_duration", "19112"),
        structured("average_likes", "32600"),
        structured("average_comments", "1619"),
        structured("average_shares", "549"),
    ]
    creation_fields = [
        structured(
            "recent_video_performance",
            [
                {
                    "item_id": "7692029874500553679",
                    "video_id": "v0d00fg10000davp8evog65p5dl8ti0g",
                    "core_user_id": "103411567572",
                    "title": "作品一",
                    "item_cover": "tos-cn-i-0813c001/osvAyCE5GFDA9ggqRvAqFnfAf7NAFqQAlUIpK3",
                    "play": 515348,
                    "like": 24642,
                    "comment": 1050,
                    "share": 326,
                    "item_date": "2026-10-02",
                    "url": "https://www.iesdouyin.com/share/video/7692029874500553679/",
                },
                {
                    "item_id": "7647143907176419043",
                    "core_user_id": "103411567572",
                    "title": "作品二",
                    "item_cover": "",
                    "play": 0,
                    "like": 0,
                    "comment": 0,
                    "share": 0,
                    "create_time": 1790940267,
                    "url": "https://www.iesdouyin.com/share/video/7647143907176419043/",
                },
            ],
        )
    ]
    projection = {key: field for field in spread_fields for key in [f"spread.{field['field_key']}"]}
    snapshot = {
        "profile_complete": True,
        "pipeline_complete": True,
        "modules": {
            "spread": {"status": "COLLECTED", "fields": spread_fields},
            "creation": {"status": "COLLECTED", "fields": creation_fields},
        },
    }
    with repo.connect() as conn:
        root_task_id = conn.execute(
            "SELECT root_task_id FROM creator_snapshots WHERE snapshot_id=%s", (seeded_snapshot_id,)
        ).fetchone()["root_task_id"]
        conn.execute(
            """INSERT INTO creator_snapshots(
            snapshot_id,root_task_id,creator_id,draft_revision,payload,created_at)
            VALUES(%s,%s,%s,2,%s,%s)""",
            (snapshot_id, root_task_id, creator_id, Jsonb(snapshot), observed_at),
        )
        CreatorLibraryWriter().sync(
            conn,
            creator_id=creator_id,
            platform_creator_id="creator-library-sample",
            projection=projection,
            snapshot_id=snapshot_id,
            snapshot=snapshot,
            captured_at=observed_at,
        )
        current = conn.execute(
            "SELECT play_median_value_raw,average_duration_value_raw,average_likes_value_raw,"
            "average_comments_value_raw,average_shares_value_raw,field_sources "
            "FROM douyin_xingtu_creator_current WHERE creator_id=%s",
            (creator_id,),
        ).fetchone()
        index = conn.execute(
            "SELECT play_median_value_raw,average_duration_value_raw,average_shares_value_raw "
            "FROM douyin_xingtu_creator_snapshot_index WHERE snapshot_id=%s",
            (snapshot_id,),
        ).fetchone()
        videos = conn.execute(
            "SELECT position,content_id,platform_item_id,platform_video_id,platform_author_id,"
            "title,subtitle,published_at,published_raw,play_count,like_count,comment_count,"
            "favorite_count,share_count,cover_source_uri,work_url,field_statuses "
            "FROM douyin_xingtu_creator_video_observations WHERE snapshot_id=%s "
            "ORDER BY module_key,position",
            (snapshot_id,),
        ).fetchall()
        content = conn.execute(
            "SELECT platform,platform_content_id,canonical_link FROM contents WHERE content_id=%s",
            (videos[0]["content_id"],),
        ).fetchone()

    # The nested `item_rate.play_mid` leaf wins; the top-level decoy must not be projected.
    assert current["play_median_value_raw"] == 766187
    assert current["average_duration_value_raw"] == 19112
    assert current["average_likes_value_raw"] == 32600
    assert current["average_comments_value_raw"] == 1619
    assert current["average_shares_value_raw"] == 549
    assert current["field_sources"]["play_median_value_raw"]["source_contract"] == "test-v1"
    assert index["play_median_value_raw"] == 766187
    assert index["average_duration_value_raw"] == 19112
    assert index["average_shares_value_raw"] == 549

    assert len(videos) == 2
    first, second = videos
    assert first["platform_item_id"] == "7692029874500553679"
    assert first["platform_video_id"] == "v0d00fg10000davp8evog65p5dl8ti0g"
    assert first["platform_author_id"] == "103411567572"
    assert first["title"] == "作品一"
    assert first["published_at"] == datetime(2026, 10, 2, tzinfo=UTC)
    assert first["play_count"] == 515348
    assert first["cover_source_uri"] == "tos-cn-i-0813c001/osvAyCE5GFDA9ggqRvAqFnfAf7NAFqQAlUIpK3"
    assert first["field_statuses"]["cover"] == "COLLECTED"
    assert content["platform"] == "douyin_xingtu"
    assert content["platform_content_id"] == "7692029874500553679"

    # A real platform zero is stored as 0; the never-returned fields stay NULL with a reason.
    assert second["play_count"] == 0
    assert second["like_count"] == 0
    assert second["cover_source_uri"] is None
    assert second["field_statuses"]["cover"] == "NOT_PROVIDED"
    assert second["subtitle"] is None
    assert second["favorite_count"] is None
    assert second["field_statuses"]["subtitle"] == "NOT_PROVIDED"
    assert second["field_statuses"]["favorite_count"] == "NOT_PROVIDED"


def _seed_video_rows(conn, creator_id: str, snapshot_id: str) -> None:
    """Two work observations plus one stored cover object, as DATA-02 writes them."""
    conn.execute(
        """INSERT INTO contents(content_id,platform,platform_content_id,canonical_link)
        VALUES('11111111-1111-4111-8111-111111111111','douyin_xingtu','7692029874500553679',
        'https://www.iesdouyin.com/share/video/7692029874500553679/') ON CONFLICT DO NOTHING"""
    )
    conn.execute(
        """INSERT INTO media_objects(object_id,checksum,kind,content_type,byte_size,
        source_url,source_key)
        VALUES('cover/task/abc','abc','cover','image/webp',1234,'https://signed.example/x.webp',
        'tos-cn-i-0813c001/aaa')"""
    )
    rows = [
        (
            snapshot_id,
            creator_id,
            "recent_video_performance",
            0,
            "11111111-1111-4111-8111-111111111111",
            "7692029874500553679",
            "tos-cn-i-0813c001/aaa",
            "STORED",
        ),
        (
            snapshot_id,
            creator_id,
            "recent_xingtu_video_performance",
            0,
            None,
            "7650000000000000000",
            None,
            "NOT_PROVIDED",
        ),
    ]
    for snapshot, creator, module_key, position, content_id, item_id, cover_key, _status in rows:
        conn.execute(
            """INSERT INTO douyin_xingtu_creator_video_observations(
            snapshot_id,creator_id,module_key,position,content_id,platform_item_id,platform_video_id,
            title,published_at,play_count,like_count,comment_count,share_count,cover_source_uri,
            work_url,field_statuses,observed_at)
            VALUES(%s,%s,%s,%s,%s,%s,'v0d',%s,%s,100,0,0,0,%s,%s,%s,%s)""",
            (
                snapshot,
                creator,
                module_key,
                position,
                content_id,
                item_id,
                f"作品 {module_key}",
                datetime(2026, 10, 2, tzinfo=UTC),
                cover_key,
                f"https://www.iesdouyin.com/share/video/{item_id}/",
                Jsonb({"cover": "COLLECTED"}),
                datetime(2026, 10, 16, tzinfo=UTC),
            ),
        )


def test_creator_library_videos_resolve_covers_and_are_creator_scoped(repo, plan):
    creator_id, snapshot_id = _seed_creator_library(repo, plan)
    # A second, unrelated creator only needs an identity row for the ownership checks.
    other_id = uid()
    with repo.connect() as conn:
        conn.execute(
            "INSERT INTO platform_creators(creator_id,platform,platform_creator_id) "
            "VALUES(%s,'douyin_xingtu','creator-library-other')",
            (other_id,),
        )
        # A registered creator with no snapshot yet: a valid, empty library entry (not a 404).
        conn.execute(
            "INSERT INTO douyin_xingtu_creator_current(creator_id,platform_creator_id) "
            "VALUES(%s,'creator-library-other')",
            (other_id,),
        )
        _seed_video_rows(conn, creator_id, snapshot_id)
    queries = ProductQueries(repo)

    page = queries.creator_library_videos(creator_id)
    assert page.snapshot_id == snapshot_id
    assert page.view_kind == "published"
    assert [item.module_key for item in page.items] == [
        "recent_video_performance",
        "recent_xingtu_video_performance",
    ]
    stored, missing = page.items
    # The cover is resolved read-side from the platform key, never from a stored signed URL.
    assert stored.cover_status == "STORED"
    assert stored.cover_object_id == "cover/task/abc"
    assert stored.cover_source_uri == "tos-cn-i-0813c001/aaa"
    assert stored.play_count == 100
    assert stored.like_count == 0  # a real platform zero stays zero
    assert missing.cover_status == "NOT_PROVIDED"
    assert missing.cover_object_id is None

    only = queries.creator_library_videos(creator_id, module_key="recent_xingtu_video_performance")
    assert [item.module_key for item in only.items] == ["recent_xingtu_video_performance"]

    # A stored work cover is reachable only through its own creator.
    reference = queries.creator_library_cover_reference(creator_id, "cover/task/abc")
    assert reference is not None and reference["content_type"] == "image/webp"
    assert queries.creator_library_cover_reference(other_id, "cover/task/abc") is None

    # A foreign creator cannot read this snapshot's work rows by naming its snapshot id.
    import pytest
    from xingtu.domain import CollectorError

    with pytest.raises(CollectorError, match="CREATOR_NOT_FOUND"):
        queries.creator_library_videos(other_id, snapshot_id=snapshot_id)
    other_page = queries.creator_library_videos(other_id)
    assert other_page.view_kind == "unavailable" and not other_page.items


def test_task_creator_videos_read_the_task_snapshot(repo, plan):
    creator_id, snapshot_id = _seed_creator_library(repo, plan)
    with repo.connect() as conn:
        _seed_video_rows(conn, creator_id, snapshot_id)
        root_task_id = conn.execute(
            "SELECT root_task_id FROM creator_snapshots WHERE snapshot_id=%s", (snapshot_id,)
        ).fetchone()["root_task_id"]
        conn.execute(
            "INSERT INTO task_creators("
            "root_task_id,creator_id,first_position,valid,latest_snapshot_id)"
            " VALUES(%s,%s,0,true,%s) ON CONFLICT(root_task_id,creator_id) "
            "DO UPDATE SET latest_snapshot_id=EXCLUDED.latest_snapshot_id",
            (root_task_id, creator_id, snapshot_id),
        )
    queries = ProductQueries(repo)
    page = queries.task_creator_videos(str(root_task_id), creator_id)
    assert page.snapshot_id == snapshot_id
    assert len(page.items) == 2

    # The task-scoped cover endpoint must serve a work cover referenced by this task's snapshot,
    # and must refuse it for an unrelated task (CD-08: the works list is task-entry visible too).
    assert repo.cover_reference(str(root_task_id), "cover/task/abc") is not None
    other_root = repo.create(
        plan,
        "unit",
        "creator-library-other-task",
        "test",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        modules=["basic"],
    )
    assert repo.cover_reference(str(other_root), "cover/task/abc") is None

    # Even another snapshot of the same creator cannot be selected through this task.
    other_snapshot_id = uid()
    with repo.connect() as conn:
        conn.execute(
            """INSERT INTO creator_snapshots(
            snapshot_id,root_task_id,creator_id,draft_revision,payload,created_at)
            VALUES(%s,%s,%s,1,%s,%s)""",
            (
                other_snapshot_id,
                other_root,
                creator_id,
                Jsonb({"modules": {}, "profile_complete": True, "pipeline_complete": True}),
                datetime(2026, 10, 17, tzinfo=UTC),
            ),
        )

    import pytest
    from xingtu.domain import CollectorError

    with pytest.raises(CollectorError, match="SNAPSHOT_NOT_FOUND"):
        queries.task_creator_videos(str(root_task_id), creator_id, snapshot_id=other_snapshot_id)
