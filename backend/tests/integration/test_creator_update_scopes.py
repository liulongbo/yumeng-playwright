"""UPD-06: per-(platform, scene) scheduled update plans.

These are real PostgreSQL integration tests (the shared ``repo`` fixture creates an isolated
schema and applies every migration).  They exercise the scheduler's plan creation, the per-scene
contract/target selection, switch gating, dual-scene isolation and terminal reconciliation without
starting a browser or Temporal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb
from xingtu.contracts import PlatformRegistry
from xingtu.creator_update import CreatorUpdateService, UpdateScope, scope_key
from xingtu.creator_update_services import CreatorUpdateServiceAdmin
from xingtu.domain import CreatorScene, PlatformId, ProfileRequirement, TaskKind, TaskStatus, uid

ROOT = Path(__file__).resolve().parents[3]
REGISTRY_FILES = {
    "douyin_xingtu.video_square": "douyin_xingtu.verified.json",
    "douyin_xingtu.live_square": "douyin_xingtu.live.verified.json",
    "kuaishou_juxing.video_square": "kuaishou_juxing.verified.json",
    "kuaishou_juxing.live_square": "kuaishou_juxing.live.verified.json",
}
XINGTU_VIDEO = (PlatformId.DOUYIN_XINGTU, CreatorScene.VIDEO_SQUARE)
XINGTU_LIVE = (PlatformId.DOUYIN_XINGTU, CreatorScene.LIVE_SQUARE)
JUXING_VIDEO = (PlatformId.KUAISHOU_JUXING, CreatorScene.VIDEO_SQUARE)
JUXING_LIVE = (PlatformId.KUAISHOU_JUXING, CreatorScene.LIVE_SQUARE)
ALL_SCOPES = (XINGTU_VIDEO, XINGTU_LIVE, JUXING_VIDEO, JUXING_LIVE)


def registry(filename: str) -> PlatformRegistry:
    return PlatformRegistry.model_validate_json((ROOT / "contracts" / filename).read_text())


def requirement() -> ProfileRequirement:
    return ProfileRequirement.model_validate_json(
        (ROOT / "contracts" / "profile_requirements.json").read_text()
    )


def all_scopes() -> dict[str, UpdateScope]:
    scopes = {}
    for (platform, scene), name in zip(
        ALL_SCOPES,
        (
            "douyin_xingtu.video_square",
            "douyin_xingtu.live_square",
            "kuaishou_juxing.video_square",
            "kuaishou_juxing.live_square",
        ),
        strict=True,
    ):
        scopes[scope_key(platform, scene)] = UpdateScope(
            platform,
            scene,
            registry(REGISTRY_FILES[name]),
            requirement() if (platform, scene) == XINGTU_VIDEO else None,
        )
    return scopes


def add_juxing_binding(repo) -> None:
    with repo.connect() as conn:
        conn.execute(
            """INSERT INTO execution_unit_platform_bindings(
            unit_id,platform,account_ref,expected_account_id,profile_ref,registry_ref,enabled)
            VALUES('unit','kuaishou_juxing','juxing-account','60821564',
                   'synthetic-juxing-profile','contracts/kuaishou_juxing.verified.json',true)
            ON CONFLICT(unit_id,platform) DO UPDATE SET enabled=true"""
        )


def set_flag(repo, platform: PlatformId, scene: CreatorScene, enabled: bool) -> None:
    with repo.connect() as conn:
        conn.execute(
            """INSERT INTO creator_update_service(platform,creator_scene,enabled,updated_at)
            VALUES(%s,%s,%s,now())
            ON CONFLICT(platform,creator_scene)
            DO UPDATE SET enabled=EXCLUDED.enabled,updated_at=now()""",
            (platform.value, scene.value, enabled),
        )


def _new_root(
    conn: Any, platform: PlatformId, scene: CreatorScene, payload: dict | None = None
) -> str:
    root = uid()
    conn.execute(
        """INSERT INTO root_tasks(
        root_task_id,state,version,unit_id,payload,platform,creator_scene)
        VALUES(%s,'COMPLETED',0,NULL,%s,%s,%s)""",
        (root, Jsonb(payload or {}), platform.value, scene.value),
    )
    return root


def _snapshot(
    conn: Any,
    creator_id: str,
    platform: PlatformId,
    scene: CreatorScene,
    *,
    pipeline_complete: bool = True,
    root_task_id: str | None = None,
) -> tuple[str, str]:
    root = root_task_id or _new_root(conn, platform, scene)
    snapshot_id = uid()
    conn.execute(
        """INSERT INTO creator_snapshots(
        snapshot_id,root_task_id,creator_id,draft_revision,payload,creator_scene)
        VALUES(%s,%s,%s,0,%s,%s)""",
        (
            snapshot_id,
            root,
            creator_id,
            Jsonb({"pipeline_complete": pipeline_complete, "modules": {}}),
            scene.value,
        ),
    )
    return snapshot_id, root


def seed_scene(
    repo,
    platform: PlatformId,
    platform_creator_id: str,
    scene: CreatorScene,
    *,
    followers: int = 120000,
    homepage: str | None = None,
    star_id: str | None = None,
    creator_id: str | None = None,
) -> str:
    """Seed one already-collected scene for one platform identity."""
    with repo.connect() as conn:
        if creator_id is None:
            row = conn.execute(
                """INSERT INTO platform_creators(
                creator_id,platform,platform_creator_id,video_homepage)
                VALUES(%s,%s,%s,%s) RETURNING creator_id""",
                (uid(), platform.value, platform_creator_id, homepage),
            ).fetchone()
            creator_id = str(row["creator_id"])
        elif homepage is not None:
            conn.execute(
                "UPDATE platform_creators SET video_homepage=%s WHERE creator_id=%s",
                (homepage, creator_id),
            )
        if scene == CreatorScene.VIDEO_SQUARE:
            if platform == PlatformId.DOUYIN_XINGTU:
                conn.execute(
                    """INSERT INTO douyin_xingtu_creator_current(
                    creator_id,platform_creator_id,followers_count,data_updated_at,
                    profile_complete,pipeline_complete)
                    VALUES(%s,%s,%s,now()-interval '10 days',true,true)""",
                    (creator_id, platform_creator_id, followers),
                )
            snapshot_id, _ = _snapshot(conn, creator_id, platform, scene)
            if platform == PlatformId.DOUYIN_XINGTU:
                conn.execute(
                    """INSERT INTO douyin_xingtu_creator_snapshot_index(
                    snapshot_id,creator_id,captured_at,profile_complete,pipeline_complete)
                    VALUES(%s,%s,now()-interval '10 days',true,true)""",
                    (snapshot_id, creator_id),
                )
        else:
            conn.execute(
                """INSERT INTO creator_live_current(
                creator_id,platform,platform_creator_id,platform_star_id,followers_count,
                data_updated_at,profile_complete,pipeline_complete)
                VALUES(%s,%s,%s,%s,%s,now()-interval '10 days',true,true)""",
                (creator_id, platform.value, platform_creator_id, star_id, followers),
            )
            _snapshot(conn, creator_id, platform, scene)
        return str(creator_id)


def schedule_rows(repo, creator_id: str) -> dict[str, dict[str, Any]]:
    with repo.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM creator_update_schedule WHERE creator_id=%s", (creator_id,)
        ).fetchall()
    return {row["creator_scene"]: dict(row) for row in rows}


def set_due(repo, creator_id: str, scene: CreatorScene, *, due: bool = True) -> None:
    expression = "now() - interval '1 minute'" if due else "now() + interval '30 days'"
    with repo.connect() as conn:
        conn.execute(
            f"""UPDATE creator_update_schedule SET next_due_at={expression}
            WHERE creator_id=%s AND creator_scene=%s""",
            (creator_id, scene.value),
        )


def scheduled_tasks(repo) -> list[dict[str, Any]]:
    with repo.connect() as conn:
        return [
            dict(row)
            for row in conn.execute(
                """SELECT root_task_id,state,platform,creator_scene,unit_id,payload
                FROM root_tasks WHERE task_kind='scheduled_update'
                ORDER BY created_at,root_task_id"""
            ).fetchall()
        ]


def task_checkpoint(repo, root_task_id: str) -> dict[str, Any]:
    with repo.connect() as conn:
        row = conn.execute(
            """SELECT c.payload FROM task_checkpoints c
            JOIN tasks t USING(task_id) WHERE t.root_task_id=%s""",
            (root_task_id,),
        ).fetchone()
    assert row is not None
    return dict(row["payload"])


def test_scheduler_creates_scene_batches_with_scene_targets_and_contracts(repo) -> None:
    add_juxing_binding(repo)
    xingtu_live = seed_scene(
        repo, PlatformId.DOUYIN_XINGTU, "xingtu-live-1", CreatorScene.LIVE_SQUARE
    )
    juxing_live = seed_scene(
        repo, PlatformId.KUAISHOU_JUXING, "juxing-live-1", CreatorScene.LIVE_SQUARE, star_id="9001"
    )
    juxing_video = seed_scene(
        repo,
        PlatformId.KUAISHOU_JUXING,
        "juxing-video-1",
        CreatorScene.VIDEO_SQUARE,
        homepage="https://k.kuaishou.com/#/promotion/star/9002?openBy=user",
    )
    service = CreatorUpdateService(repo, scopes=all_scopes(), batch_size=5)
    for key in all_scopes():
        service.enroll_group(key)
    for platform, scene in (XINGTU_LIVE, JUXING_LIVE, JUXING_VIDEO):
        set_flag(repo, platform, scene, True)
    set_due(repo, xingtu_live, CreatorScene.LIVE_SQUARE)
    set_due(repo, juxing_live, CreatorScene.LIVE_SQUARE)
    set_due(repo, juxing_video, CreatorScene.VIDEO_SQUARE)

    result = service.scheduler_tick()
    assert result["created"] == 3
    tasks = scheduled_tasks(repo)
    by_key = {(task["platform"], task["creator_scene"]): task for task in tasks}
    assert set(by_key) == {
        (PlatformId.DOUYIN_XINGTU.value, CreatorScene.LIVE_SQUARE.value),
        (PlatformId.KUAISHOU_JUXING.value, CreatorScene.LIVE_SQUARE.value),
        (PlatformId.KUAISHOU_JUXING.value, CreatorScene.VIDEO_SQUARE.value),
    }

    xingtu_live_task = by_key[(PlatformId.DOUYIN_XINGTU.value, "live_square")]
    xingtu_target = xingtu_live_task["payload"]["update_targets"][0]
    assert xingtu_target["verified_homepage"] == (
        "https://www.xingtu.cn/ad/creator/author/douyin/xingtu-live-1/10"
    )
    xingtu_checkpoint = task_checkpoint(repo, xingtu_live_task["root_task_id"])
    assert xingtu_checkpoint["contract_version"] == (
        registry(REGISTRY_FILES["douyin_xingtu.live_square"]).contract_version
    )
    assert xingtu_checkpoint["profile_module_keys"] == [
        module.key for module in registry(REGISTRY_FILES["douyin_xingtu.live_square"]).modules
    ]

    juxing_live_task = by_key[(PlatformId.KUAISHOU_JUXING.value, "live_square")]
    assert (
        juxing_live_task["payload"]["update_targets"][0]["verified_homepage"]
        == "https://k.kuaishou.com/#/live-promotion/star/9001?openBy=user"
    )
    juxing_live_checkpoint = task_checkpoint(repo, juxing_live_task["root_task_id"])
    assert juxing_live_checkpoint["profile_module_keys"] == [
        module.key for module in registry(REGISTRY_FILES["kuaishou_juxing.live_square"]).modules
    ]

    juxing_video_task = by_key[(PlatformId.KUAISHOU_JUXING.value, "video_square")]
    assert (
        juxing_video_task["payload"]["update_targets"][0]["verified_homepage"]
        == "https://k.kuaishou.com/#/promotion/star/9002?openBy=user"
    )
    assert task_checkpoint(repo, juxing_video_task["root_task_id"])["profile_module_keys"] == [
        module.key for module in registry(REGISTRY_FILES["kuaishou_juxing.video_square"]).modules
    ]

    for creator_id, scene, task in (
        (xingtu_live, CreatorScene.LIVE_SQUARE, xingtu_live_task),
        (juxing_live, CreatorScene.LIVE_SQUARE, juxing_live_task),
        (juxing_video, CreatorScene.VIDEO_SQUARE, juxing_video_task),
    ):
        row = schedule_rows(repo, creator_id)[scene.value]
        assert str(row["in_flight_root_task_id"]) == str(task["root_task_id"])
        assert row["last_attempt_at"] is not None

    # One active batch per group: a second tick cannot duplicate any of them.
    assert service.scheduler_tick()["created"] == 0


def test_disabled_group_creates_no_task_and_other_group_continues(repo) -> None:
    xingtu_video = seed_scene(
        repo, PlatformId.DOUYIN_XINGTU, "xingtu-video-off", CreatorScene.VIDEO_SQUARE
    )
    xingtu_live = seed_scene(
        repo, PlatformId.DOUYIN_XINGTU, "xingtu-live-on", CreatorScene.LIVE_SQUARE
    )
    service = CreatorUpdateService(repo, scopes=all_scopes(), batch_size=5)
    service.enroll_group(scope_key(*XINGTU_VIDEO))
    service.enroll_group(scope_key(*XINGTU_LIVE))
    set_flag(repo, *XINGTU_VIDEO, False)
    set_flag(repo, *XINGTU_LIVE, True)
    set_due(repo, xingtu_video, CreatorScene.VIDEO_SQUARE)
    set_due(repo, xingtu_live, CreatorScene.LIVE_SQUARE)

    result = service.scheduler_tick()
    assert result["created"] == 1
    tasks = scheduled_tasks(repo)
    assert len(tasks) == 1
    assert tasks[0]["creator_scene"] == "live_square"
    assert schedule_rows(repo, xingtu_video)["video_square"]["in_flight_root_task_id"] is None
    reasons = result["groups"][scope_key(*XINGTU_VIDEO)]["reasons"]
    assert "SERVICE_DISABLED" in reasons


def test_same_creator_two_scenes_have_independent_plans_and_batches(repo) -> None:
    add_juxing_binding(repo)
    homepage = "https://k.kuaishou.com/#/promotion/star/9010?openBy=user"
    creator_id = seed_scene(
        repo,
        PlatformId.KUAISHOU_JUXING,
        "dual-scene-1",
        CreatorScene.VIDEO_SQUARE,
        homepage=homepage,
    )
    seed_scene(
        repo,
        PlatformId.KUAISHOU_JUXING,
        "dual-scene-1",
        CreatorScene.LIVE_SQUARE,
        star_id="9010",
        creator_id=creator_id,
    )
    service = CreatorUpdateService(repo, scopes=all_scopes(), batch_size=5)
    service.enroll_group(scope_key(*JUXING_VIDEO))
    service.enroll_group(scope_key(*JUXING_LIVE))
    set_flag(repo, *JUXING_VIDEO, True)
    set_flag(repo, *JUXING_LIVE, True)
    set_due(repo, creator_id, CreatorScene.VIDEO_SQUARE)
    set_due(repo, creator_id, CreatorScene.LIVE_SQUARE, due=False)

    assert service.scheduler_tick()["created"] == 1
    rows = schedule_rows(repo, creator_id)
    assert set(rows) == {"video_square", "live_square"}
    assert rows["video_square"]["in_flight_root_task_id"] is not None
    assert rows["live_square"]["in_flight_root_task_id"] is None
    video_task = scheduled_tasks(repo)[0]

    set_due(repo, creator_id, CreatorScene.LIVE_SQUARE)
    assert service.scheduler_tick()["created"] == 1
    tasks = scheduled_tasks(repo)
    assert len(tasks) == 2
    live_task = next(task for task in tasks if task["creator_scene"] == "live_square")
    assert live_task["root_task_id"] != video_task["root_task_id"]
    rows = schedule_rows(repo, creator_id)
    assert str(rows["video_square"]["in_flight_root_task_id"]) == str(video_task["root_task_id"])
    assert str(rows["live_square"]["in_flight_root_task_id"]) == str(live_task["root_task_id"])


def test_live_reconcile_advances_only_the_live_plan(repo) -> None:
    add_juxing_binding(repo)
    homepage = "https://k.kuaishou.com/#/promotion/star/9020?openBy=user"
    creator_id = seed_scene(
        repo,
        PlatformId.KUAISHOU_JUXING,
        "reconcile-dual-1",
        CreatorScene.VIDEO_SQUARE,
        homepage=homepage,
    )
    seed_scene(
        repo,
        PlatformId.KUAISHOU_JUXING,
        "reconcile-dual-1",
        CreatorScene.LIVE_SQUARE,
        star_id="9020",
        creator_id=creator_id,
    )
    service = CreatorUpdateService(repo, scopes=all_scopes(), batch_size=5)
    service.enroll_group(scope_key(*JUXING_VIDEO))
    service.enroll_group(scope_key(*JUXING_LIVE))
    set_flag(repo, *JUXING_VIDEO, True)
    set_flag(repo, *JUXING_LIVE, True)
    set_due(repo, creator_id, CreatorScene.VIDEO_SQUARE, due=False)
    set_due(repo, creator_id, CreatorScene.LIVE_SQUARE)
    assert service.scheduler_tick()["created"] == 1
    task = scheduled_tasks(repo)[0]
    assert task["creator_scene"] == "live_square"
    assert repo.claim_unassigned_update("unit") == str(task["root_task_id"])

    with repo.connect() as conn:
        new_snapshot_id, _ = _snapshot(
            conn,
            creator_id,
            PlatformId.KUAISHOU_JUXING,
            CreatorScene.LIVE_SQUARE,
            pipeline_complete=True,
            root_task_id=task["root_task_id"],
        )
    before = schedule_rows(repo, creator_id)
    video_next_due = before["video_square"]["next_due_at"]
    video_snapshot = before["video_square"]["last_success_snapshot_id"]
    with repo.edit(task["root_task_id"]) as (current, _):
        current.state = TaskStatus.COMPLETED
        current.pipeline_complete = True

    after = schedule_rows(repo, creator_id)
    assert after["live_square"]["in_flight_root_task_id"] is None
    assert str(after["live_square"]["last_success_snapshot_id"]) == new_snapshot_id
    assert after["live_square"]["last_success_at"] is not None
    assert after["live_square"]["next_due_at"] > after["live_square"]["last_success_at"]
    assert after["live_square"]["consecutive_failures"] == 0
    assert after["video_square"]["in_flight_root_task_id"] is None
    assert after["video_square"]["last_success_snapshot_id"] == video_snapshot
    assert after["video_square"]["next_due_at"] == video_next_due


def test_disabled_cancel_releases_without_a_failure_or_advancing_due(repo) -> None:
    creator_id = seed_scene(
        repo, PlatformId.DOUYIN_XINGTU, "disabled-cancel-1", CreatorScene.VIDEO_SQUARE
    )
    service = CreatorUpdateService(repo, scopes=all_scopes(), batch_size=5)
    service.enroll_group(scope_key(*XINGTU_VIDEO))
    set_flag(repo, *XINGTU_VIDEO, True)
    set_due(repo, creator_id, CreatorScene.VIDEO_SQUARE)
    assert service.scheduler_tick()["created"] == 1
    task = scheduled_tasks(repo)[0]
    assert repo.claim_unassigned_update("unit") == str(task["root_task_id"])
    with repo.edit(task["root_task_id"]) as (current, _):
        current.state = TaskStatus.CANCELLED
        current.failure_reason = "UPDATE_SERVICE_DISABLED"
    row = schedule_rows(repo, creator_id)["video_square"]
    assert row["in_flight_root_task_id"] is None
    assert row["consecutive_failures"] == 0
    assert row["last_failure_reason"] is None
    # Still due, so re-enabling resumes from the existing cycle instead of a fake backoff.
    assert row["next_due_at"] <= row["last_attempt_at"]


def test_juxing_video_without_locator_is_not_enrolled_until_known(repo) -> None:
    add_juxing_binding(repo)
    creator_id = seed_scene(
        repo, PlatformId.KUAISHOU_JUXING, "no-locator-1", CreatorScene.VIDEO_SQUARE
    )
    service = CreatorUpdateService(repo, scopes=all_scopes(), batch_size=5)
    assert service.enroll_group(scope_key(*JUXING_VIDEO)) == 0
    assert schedule_rows(repo, creator_id) == {}
    homepage = "https://k.kuaishou.com/#/promotion/star/9030?openBy=user"
    with repo.connect() as conn:
        conn.execute(
            "UPDATE platform_creators SET video_homepage=%s WHERE creator_id=%s",
            (homepage, creator_id),
        )
    assert service.enroll_group(scope_key(*JUXING_VIDEO)) == 1
    assert "video_square" in schedule_rows(repo, creator_id)


def test_one_scope_failure_does_not_stop_the_other_scope(repo) -> None:
    add_juxing_binding(repo)
    juxing_video = seed_scene(
        repo,
        PlatformId.KUAISHOU_JUXING,
        "bad-locator-1",
        CreatorScene.VIDEO_SQUARE,
        homepage="https://invalid.example/not-juxing",
    )
    xingtu_live = seed_scene(
        repo, PlatformId.DOUYIN_XINGTU, "healthy-live-1", CreatorScene.LIVE_SQUARE
    )
    service = CreatorUpdateService(repo, scopes=all_scopes(), batch_size=5)
    service.enroll_group(scope_key(*JUXING_VIDEO))
    service.enroll_group(scope_key(*XINGTU_LIVE))
    set_flag(repo, *JUXING_VIDEO, True)
    set_flag(repo, *XINGTU_LIVE, True)
    set_due(repo, juxing_video, CreatorScene.VIDEO_SQUARE)
    set_due(repo, xingtu_live, CreatorScene.LIVE_SQUARE)
    result = service.scheduler_tick()
    assert result["created"] == 1
    assert scope_key(*JUXING_VIDEO) in result["errors"]
    tasks = scheduled_tasks(repo)
    assert len(tasks) == 1 and tasks[0]["creator_scene"] == "live_square"
    assert schedule_rows(repo, juxing_video)["video_square"]["in_flight_root_task_id"] is None


def test_manual_status_reads_only_the_video_plan(repo) -> None:
    creator_id = seed_scene(
        repo, PlatformId.DOUYIN_XINGTU, "manual-status-1", CreatorScene.VIDEO_SQUARE
    )
    seed_scene(
        repo,
        PlatformId.DOUYIN_XINGTU,
        "manual-status-1",
        CreatorScene.LIVE_SQUARE,
        creator_id=creator_id,
    )
    service = CreatorUpdateService(repo, scopes=all_scopes(), batch_size=5)
    service.enroll_group(scope_key(*XINGTU_VIDEO))
    service.enroll_group(scope_key(*XINGTU_LIVE))
    set_due(repo, creator_id, CreatorScene.VIDEO_SQUARE, due=False)
    with repo.connect() as conn:
        video_due = conn.execute(
            """SELECT next_due_at FROM creator_update_schedule
            WHERE creator_id=%s AND creator_scene='video_square'""",
            (creator_id,),
        ).fetchone()["next_due_at"]
    status = service.status(creator_id)
    assert status.next_due_at == video_due
    assert status.next_due_at is not None


def test_manual_status_ignores_a_live_only_plan(repo) -> None:
    creator_id = seed_scene(
        repo, PlatformId.DOUYIN_XINGTU, "manual-live-only", CreatorScene.LIVE_SQUARE
    )
    service = CreatorUpdateService(repo, scopes=all_scopes(), batch_size=5)
    service.enroll_group(scope_key(*XINGTU_LIVE))
    # The creator has no video projection, so the manual video status must keep failing closed.
    from xingtu.domain import CollectorError

    try:
        service.status(creator_id)
    except CollectorError as exc:
        assert exc.reason == "CREATOR_NOT_FOUND"
    else:  # pragma: no cover - explicit contract guard
        raise AssertionError("live-only creator must not get a Xingtu video update status")


def test_heartbeat_records_available_scopes_and_scope_errors(repo) -> None:
    service = CreatorUpdateService(
        repo,
        scopes=all_scopes(),
        scope_errors={scope_key(*JUXING_LIVE): "UPDATE_LIVE_REGISTRY_UNAVAILABLE"},
        batch_size=5,
    )
    service.scheduler_tick()
    with repo.connect() as conn:
        heartbeat = dict(
            conn.execute(
                "SELECT * FROM creator_update_scheduler_heartbeat WHERE singleton=true"
            ).fetchone()
        )
    assert set(heartbeat["available_scopes"]) == set(all_scopes())
    assert heartbeat["scope_errors"][scope_key(*JUXING_LIVE)] == (
        "UPDATE_LIVE_REGISTRY_UNAVAILABLE"
    )
    assert heartbeat["last_result"]["created"] == 0
    assert heartbeat["tick_seconds"] == 60.0


def test_admin_view_reports_switch_liveness_and_missing_locators(repo) -> None:
    add_juxing_binding(repo)
    with repo.connect() as conn:
        user_id = uid()
        conn.execute(
            """INSERT INTO users(user_id,username,display_name,password_hash)
            VALUES(%s,%s,'Tester','x')""",
            (user_id, "tester-" + user_id[:8]),
        )
    seed_scene(repo, PlatformId.DOUYIN_XINGTU, "admin-video-1", CreatorScene.VIDEO_SQUARE)
    seed_scene(repo, PlatformId.KUAISHOU_JUXING, "admin-missing-locator", CreatorScene.VIDEO_SQUARE)
    admin = CreatorUpdateServiceAdmin(repo)
    page = admin.list_services()
    assert len(page.items) == 4
    by_key = {(item.platform, item.creator_scene): item for item in page.items}
    assert by_key[("douyin_xingtu", CreatorScene.VIDEO_SQUARE)].enabled is True
    assert by_key[("douyin_xingtu", CreatorScene.VIDEO_SQUARE)].effective_enabled is False
    assert by_key[("douyin_xingtu", CreatorScene.VIDEO_SQUARE)].unavailable_reason == (
        "SCHEDULER_NOT_RUNNING"
    )
    assert by_key[("kuaishou_juxing", CreatorScene.VIDEO_SQUARE)].missing_target_count == 1

    with repo.connect() as conn:
        conn.execute(
            """INSERT INTO creator_update_scheduler_heartbeat(
            singleton,last_tick_at,tick_seconds,available_scopes,scope_errors)
            VALUES(true,now(),5,%s,'{}')
            ON CONFLICT(singleton) DO UPDATE SET
            last_tick_at=now(),tick_seconds=5,available_scopes=EXCLUDED.available_scopes""",
            (Jsonb(sorted(all_scopes())),),
        )
    page = admin.list_services()
    by_key = {(item.platform, item.creator_scene): item for item in page.items}
    video = by_key[("douyin_xingtu", CreatorScene.VIDEO_SQUARE)]
    assert page.scheduler_alive is True and video.effective_enabled is True
    assert video.unavailable_reason is None

    view = admin.set_enabled("kuaishou_juxing", CreatorScene.LIVE_SQUARE, True, user_id=user_id)
    assert view.enabled is True and view.effective_enabled is True
    with repo.connect() as conn:
        enabled = conn.execute(
            """SELECT enabled FROM creator_update_service
            WHERE platform='kuaishou_juxing' AND creator_scene='live_square'"""
        ).fetchone()["enabled"]
        audit = conn.execute(
            """SELECT count(*) AS n FROM audit_logs
            WHERE action='creator_update_service.set:kuaishou_juxing:live_square:1'"""
        ).fetchone()["n"]
    assert enabled is True and audit == 1

    # A stale heartbeat must not keep claiming the service is effective.
    with repo.connect() as conn:
        conn.execute(
            """UPDATE creator_update_scheduler_heartbeat
            SET last_tick_at=now()-interval '1 hour' WHERE singleton=true"""
        )
    page = admin.list_services()
    by_key = {(item.platform, item.creator_scene): item for item in page.items}
    assert page.scheduler_alive is False
    assert by_key[("douyin_xingtu", CreatorScene.VIDEO_SQUARE)].effective_enabled is False


def test_admin_view_reports_latest_scheduled_task(repo) -> None:
    with repo.connect() as conn:
        root = uid()
        conn.execute(
            """INSERT INTO root_tasks(
            root_task_id,state,version,unit_id,payload,task_kind,platform,creator_scene)
            VALUES(%s,'PARTIAL_COMPLETED',0,NULL,%s,'scheduled_update','douyin_xingtu',
                   'video_square')""",
            (
                root,
                Jsonb(
                    {
                        "failure_reason": "MODULE_COLLECTION_FAILED",
                        "target_count": 3,
                        "valid_count": 2,
                        "profile_complete_count": 1,
                        "task_kind": TaskKind.SCHEDULED_UPDATE.value,
                    }
                ),
            ),
        )
    item = next(
        item
        for item in CreatorUpdateServiceAdmin(repo).list_services().items
        if item.platform == "douyin_xingtu" and item.creator_scene == CreatorScene.VIDEO_SQUARE
    )
    assert item.last_task is not None
    assert item.last_task.root_task_id == root
    assert item.last_task.state == TaskStatus.PARTIAL_COMPLETED
    assert item.last_task.failure_reason == "MODULE_COLLECTION_FAILED"
    assert item.last_task.target_count == 3
    assert item.last_task.valid_count == 2
    assert item.last_task.profile_complete_count == 1
