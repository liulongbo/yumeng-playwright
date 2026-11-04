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
