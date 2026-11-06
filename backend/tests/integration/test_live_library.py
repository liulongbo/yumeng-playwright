from datetime import UTC, datetime
from pathlib import Path

from psycopg.types.json import Jsonb
from xingtu.contracts import PlatformRegistry
from xingtu.creator_library import CreatorLiveLibraryWriter
from xingtu.domain import CreatorScene, uid
from xingtu.live_update import LiveCreatorUpdateService
from xingtu.product_queries import ProductQueries


def _seed_live_creator(repo):
    creator_id = uid()
    snapshot_id = uid()
    root_id = uid()
    captured_at = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
    modules = {
        "basic": {
            "status": "COLLECTED",
            "fields": [
                {"field_key": "nickname", "status": "COLLECTED", "value": "直播达人"},
                {
                    "field_key": "followers",
                    "status": "COLLECTED",
                    "raw_value": "1,056",
                    "value": {"kind": "number", "bound": "exact", "amount": "1056", "quantum": "1"},
                },
                {"field_key": "city", "status": "COLLECTED", "value": "宿州市"},
            ],
        },
        "live": {
            "status": "COLLECTED",
            "fields": [
                {
                    "field_key": "live.room_cnt",
                    "status": "COLLECTED",
                    "raw_value": "12",
                    "value": {"kind": "number", "bound": "exact", "amount": "12", "quantum": "1"},
                    "unit": "count",
                    "period_label": "近30天",
                },
                {"field_key": "live.acu", "status": "NO_DATA"},
            ],
        },
    }
    snapshot = {
        "schema_version": "profile_snapshot.v1",
        "creator_scene": "live_square",
        "modules": modules,
        "profile_complete": True,
        "pipeline_complete": True,
    }
    with repo.connect() as conn:
        conn.execute(
            "INSERT INTO platform_creators(creator_id,platform,platform_creator_id) "
            "VALUES(%s,'douyin_xingtu','live-library-sample')",
            (creator_id,),
        )
        conn.execute(
            """INSERT INTO root_tasks(
            root_task_id,state,version,payload,task_kind,platform,creator_scene)
            VALUES(%s,'COMPLETED',1,%s,'collection','douyin_xingtu','live_square')""",
            (root_id, Jsonb({"state": "COMPLETED"})),
        )
        conn.execute(
            """INSERT INTO creator_snapshots(
            snapshot_id,root_task_id,creator_id,draft_revision,payload,creator_scene,created_at)
            VALUES(%s,%s,%s,1,%s,'live_square',%s)""",
            (snapshot_id, root_id, creator_id, Jsonb(snapshot), captured_at),
        )
        CreatorLiveLibraryWriter().sync(
            conn,
            creator_id=creator_id,
            platform="douyin_xingtu",
            platform_creator_id="live-library-sample",
            snapshot_id=snapshot_id,
            snapshot=snapshot,
            captured_at=captured_at,
            profile_complete=True,
            pipeline_complete=True,
        )
    return creator_id


def test_live_read_model_is_separate_from_video(repo):
    creator_id = _seed_live_creator(repo)
    queries = ProductQueries(repo)
    live = queries.list_creator_library(creator_scene=CreatorScene.LIVE_SQUARE)
    assert [item.creator_id for item in live.items] == [creator_id]
    assert live.items[0].creator_scene == CreatorScene.LIVE_SQUARE
    assert live.items[0].live_metrics["live.room_cnt"]["status"] == "COLLECTED"
    detail = queries.get_creator_library(creator_id, CreatorScene.LIVE_SQUARE)
    assert detail.display_name == "直播达人"
    assert detail.available_scenes == [CreatorScene.LIVE_SQUARE]
    assert "live.acu" not in detail.live_metrics
    assert detail.field_sources["live.acu"]["status"] == "NO_DATA"
    assert detail.profile_payload["creator_scene"] == "live_square"
    # A live-only creator must not appear in the established video library or its projection.
    video = queries.list_creator_library(creator_scene=CreatorScene.VIDEO_SQUARE)
    assert video.items == []
    with repo.connect() as conn:
        projection = conn.execute(
            "SELECT projection FROM platform_creators WHERE creator_id=%s", (creator_id,)
        ).fetchone()["projection"]
    assert projection == {}


def test_live_manual_update_does_not_enroll_the_video_schedule(repo):
    creator_id = _seed_live_creator(repo)
    user_id = str(uid())
    with repo.connect() as conn:
        conn.execute(
            """INSERT INTO users(user_id,username,display_name,password_hash)
            VALUES(%s,'live-test','Live Test','x')""",
            (user_id,),
        )
    registry = PlatformRegistry.model_validate_json(
        Path("contracts/douyin_xingtu.live.verified.json").read_text()
    )
    service = LiveCreatorUpdateService(repo, {"douyin_xingtu:live_square": registry})
    response = service.create_manual_update(
        creator_id, user_id=user_id, idempotency_key="live-update-1"
    )
    assert response.reused is False
    with repo.connect() as conn:
        task = conn.execute(
            "SELECT task_kind,platform,creator_scene FROM root_tasks WHERE root_task_id=%s",
            (response.root_task_id,),
        ).fetchone()
        assert tuple(task.values()) == ("manual_update", "douyin_xingtu", "live_square")
        schedule = conn.execute(
            "SELECT 1 FROM creator_update_schedule WHERE creator_id=%s", (creator_id,)
        ).fetchone()
        assert schedule is None
    repeated = service.create_manual_update(
        creator_id, user_id=user_id, idempotency_key="live-update-2"
    )
    assert repeated.reused is True
    assert repeated.root_task_id == response.root_task_id
    status = service.status(creator_id)
    assert status.in_flight_root_task_id == response.root_task_id
    assert status.next_due_at is None


def test_live_list_omits_detail_collections_but_detail_returns_them(repo):
    creator_id = uid()
    snapshot_id = uid()
    root_id = uid()
    captured_at = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
    work = {
        "stream_id": "15046311215",
        "collection_kind": "personal",
        "title": "福利主播来了",
        "view_count": 1099630,
        "has_sku_info": True,
    }
    modules = {
        "basic": {
            "status": "COLLECTED",
            "fields": [
                {"field_key": "nickname", "status": "COLLECTED", "value": "聚星直播达人"},
                {
                    "field_key": "followers",
                    "status": "COLLECTED",
                    "raw_value": "37388604",
                    "value": {"kind": "number", "amount": "37388604", "bound": "exact"},
                },
                {
                    "field_key": "content_type_labels",
                    "status": "COLLECTED",
                    "value": ["游戏", "MOBA"],
                },
            ],
        },
        "live": {
            "status": "COLLECTED",
            "fields": [
                {
                    "field_key": "live.expect_viewer",
                    "status": "COLLECTED",
                    "raw_value": "1734393",
                    "value": {"kind": "number", "amount": "1734393", "bound": "exact"},
                    "unit": "count",
                },
                {"field_key": "live.credit_score", "status": "NO_DATA"},
            ],
        },
        "works": {
            "status": "COLLECTED",
            "fields": [
                {
                    "field_key": "live.personal_live_works",
                    "status": "COLLECTED",
                    "value": {"kind": "structured", "data": [work]},
                }
            ],
        },
        "cooperation": {
            "status": "COLLECTED",
            "fields": [
                {
                    "field_key": "live.evaluation_reviews",
                    "status": "COLLECTED",
                    "value": {
                        "kind": "structured",
                        "data": {
                            "total": 1,
                            "collected": 1,
                            "pages": 1,
                            "complete": True,
                            "items": [],
                        },
                    },
                }
            ],
        },
    }
    snapshot = {
        "schema_version": "profile_snapshot.v1",
        "creator_scene": "live_square",
        "modules": modules,
        "profile_complete": True,
        "pipeline_complete": True,
    }
    with repo.connect() as conn:
        conn.execute(
            "INSERT INTO platform_creators(creator_id,platform,platform_creator_id) "
            "VALUES(%s,'kuaishou_juxing','72022133')",
            (creator_id,),
        )
        conn.execute(
            """INSERT INTO root_tasks(
            root_task_id,state,version,payload,task_kind,platform,creator_scene)
            VALUES(%s,'COMPLETED',1,%s,'collection','kuaishou_juxing','live_square')""",
            (root_id, Jsonb({"state": "COMPLETED"})),
        )
        conn.execute(
            """INSERT INTO creator_snapshots(
            snapshot_id,root_task_id,creator_id,draft_revision,payload,creator_scene,created_at)
            VALUES(%s,%s,%s,1,%s,'live_square',%s)""",
            (snapshot_id, root_id, creator_id, Jsonb(snapshot), captured_at),
        )
        CreatorLiveLibraryWriter().sync(
            conn,
            creator_id=creator_id,
            platform="kuaishou_juxing",
            platform_creator_id="72022133",
            snapshot_id=snapshot_id,
            snapshot=snapshot,
            captured_at=captured_at,
            profile_complete=True,
            pipeline_complete=True,
        )
        row = conn.execute(
            "SELECT content_theme_labels,live_metrics FROM creator_live_current "
            "WHERE creator_id=%s",
            (creator_id,),
        ).fetchone()
    assert row["content_theme_labels"] == ["游戏", "MOBA"]
    assert "live.personal_live_works" in row["live_metrics"]
    assert "live.evaluation_reviews" in row["live_metrics"]

    queries = ProductQueries(repo)
    listing = queries.list_creator_library(
        platform="kuaishou_juxing", creator_scene=CreatorScene.LIVE_SQUARE
    )
    assert len(listing.items) == 1
    assert "live.personal_live_works" not in listing.items[0].live_metrics
    assert "live.evaluation_reviews" not in listing.items[0].live_metrics
    assert listing.items[0].live_metrics["live.expect_viewer"]["status"] == "COLLECTED"

    detail = queries.get_creator_library(creator_id, CreatorScene.LIVE_SQUARE)
    assert "live.personal_live_works" in detail.live_metrics
    assert "live.evaluation_reviews" in detail.live_metrics
    assert detail.display_name == "聚星直播达人"


def _detail_snapshot(*, audience_status: str = "COLLECTED") -> dict:
    audience_value = {
        "kind": "structured",
        "data": {
            "live_type": "general",
            "crowd_type": "fans",
            "distributions": {"gender": {"total": "10", "items": [{"key": "女", "count": "10"}]}},
        },
    }
    modules = {
        "basic": {
            "status": "COLLECTED",
            "fields": [
                {"field_key": "nickname", "status": "COLLECTED", "value": "直播达人"},
                {"field_key": "introduction", "status": "COLLECTED", "value": "公开介绍"},
                {"field_key": "douyin_id", "status": "COLLECTED", "value": "34976739532"},
                {"field_key": "wechat", "status": "COLLECTED", "value": "wx_example_001"},
            ],
        },
        "live": {
            "status": "COLLECTED",
            "fields": [
                {
                    "field_key": "live.room_cnt",
                    "status": "COLLECTED",
                    "value": {"kind": "number", "bound": "exact", "amount": "12", "quantum": "1"},
                    "unit": "count",
                }
            ],
        },
        "live_pricing": {
            "status": "COLLECTED",
            "fields": [
                {
                    "field_key": "pricing.services",
                    "status": "COLLECTED",
                    "value": {
                        "kind": "structured",
                        "data": {"services": [{"service_label": "按天"}]},
                    },
                }
            ],
        },
        "live_analysis": {
            "status": "COLLECTED",
            "fields": [
                {
                    "field_key": "analysis.rooms",
                    "status": "COLLECTED",
                    "value": {"kind": "structured", "data": {"rows": [{"room_id": "1"}]}},
                }
            ],
        },
        "live_audience": (
            {
                "status": "COLLECTED",
                "fields": [
                    {
                        "field_key": "audience.general.fans",
                        "status": "COLLECTED",
                        "value": audience_value,
                    }
                ],
            }
            if audience_status == "COLLECTED"
            else {
                "status": "FAILED",
                "fields": [
                    {
                        "field_key": "__module_failure__",
                        "status": "FAILED",
                        "failure_reason": "LIVE_AUDIENCE_TAB_MISSING",
                    }
                ],
            }
        ),
        "live_overview": {
            "status": "COLLECTED",
            "fields": [
                {
                    "field_key": "overview.meta",
                    "status": "COLLECTED",
                    "value": {"kind": "structured", "data": {"defaults": {"period": 30}}},
                }
            ],
        },
    }
    return {
        "schema_version": "profile_snapshot.v1",
        "creator_scene": "live_square",
        "modules": modules,
        "profile_complete": True,
        "pipeline_complete": True,
    }


def _seed_detail_creator(repo, *, audience_status: str = "COLLECTED"):
    creator_id = uid()
    root_id = uid()
    snapshot_id = uid()
    captured_at = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
    snapshot = _detail_snapshot(audience_status=audience_status)
    with repo.connect() as conn:
        conn.execute(
            "INSERT INTO platform_creators(creator_id,platform,platform_creator_id) "
            "VALUES(%s,'douyin_xingtu','live-detail-sample')",
            (creator_id,),
        )
        conn.execute(
            """INSERT INTO root_tasks(
            root_task_id,state,version,payload,task_kind,platform,creator_scene)
            VALUES(%s,'COMPLETED',1,%s,'manual_update','douyin_xingtu','live_square')""",
            (root_id, Jsonb({"state": "COMPLETED"})),
        )
        conn.execute(
            """INSERT INTO creator_snapshots(
            snapshot_id,root_task_id,creator_id,draft_revision,payload,creator_scene,created_at)
            VALUES(%s,%s,%s,1,%s,'live_square',%s)""",
            (snapshot_id, root_id, creator_id, Jsonb(snapshot), captured_at),
        )
        conn.execute(
            """INSERT INTO task_creators(
            root_task_id,creator_id,first_position,valid,latest_snapshot_id)
            VALUES(%s,%s,1,true,%s)""",
            (root_id, creator_id, snapshot_id),
        )
        CreatorLiveLibraryWriter().sync(
            conn,
            creator_id=creator_id,
            platform="douyin_xingtu",
            platform_creator_id="live-detail-sample",
            snapshot_id=snapshot_id,
            snapshot=snapshot,
            captured_at=captured_at,
            profile_complete=True,
            pipeline_complete=True,
        )
    return creator_id, root_id, snapshot_id


def test_live_detail_modules_and_introduction_are_returned(repo):
    creator_id, root_id, _ = _seed_detail_creator(repo)
    queries = ProductQueries(repo)
    detail = queries.get_creator_library(creator_id, CreatorScene.LIVE_SQUARE)
    assert detail.introduction == "公开介绍"
    assert detail.module_fallbacks == {}
    basic_fields = {
        field["field_key"]: field for field in detail.profile_payload["modules"]["basic"]["fields"]
    }
    assert basic_fields["wechat"]["value"] == "wx_example_001"
    modules = detail.profile_payload["modules"]
    assert set(modules) == {
        "basic",
        "live",
        "live_pricing",
        "live_analysis",
        "live_audience",
        "live_overview",
    }
    page = queries.list_creators(root_id)
    assert len(page.items) == 1
    # The task-result list only carries the modules it renders; the detail keeps everything.
    assert set(page.items[0].payload["modules"]) == {"basic", "live"}
    listed_basic_fields = {
        field["field_key"] for field in page.items[0].payload["modules"]["basic"]["fields"]
    }
    assert "wechat" not in listed_basic_fields


def test_live_detail_reads_back_older_module_when_latest_failed(repo):
    creator_id, root_id, first_snapshot = _seed_detail_creator(repo)
    second_snapshot = uid()
    failed = _detail_snapshot(audience_status="FAILED")
    captured_at = datetime(2026, 11, 5, 13, 0, tzinfo=UTC)
    with repo.connect() as conn:
        conn.execute(
            """INSERT INTO creator_snapshots(
            snapshot_id,root_task_id,creator_id,draft_revision,payload,creator_scene,created_at)
            VALUES(%s,%s,%s,2,%s,'live_square',%s)""",
            (second_snapshot, root_id, creator_id, Jsonb(failed), captured_at),
        )
        conn.execute(
            "UPDATE task_creators SET latest_snapshot_id=%s "
            "WHERE root_task_id=%s AND creator_id=%s",
            (second_snapshot, root_id, creator_id),
        )
        CreatorLiveLibraryWriter().sync(
            conn,
            creator_id=creator_id,
            platform="douyin_xingtu",
            platform_creator_id="live-detail-sample",
            snapshot_id=second_snapshot,
            snapshot=failed,
            captured_at=captured_at,
            profile_complete=False,
            pipeline_complete=False,
        )
    queries = ProductQueries(repo)
    detail = queries.get_creator_library(creator_id, CreatorScene.LIVE_SQUARE)
    assert detail.profile_payload["modules"]["live_audience"]["status"] == "COLLECTED"
    assert (
        detail.profile_payload["modules"]["live_audience"]["fields"][0]["field_key"]
        == "audience.general.fans"
    )
    assert detail.module_fallbacks["live_audience"]["snapshot_id"] == str(first_snapshot)
    assert detail.module_statuses["live_audience"] == "COLLECTED"
