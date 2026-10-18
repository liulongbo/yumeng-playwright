from datetime import UTC, datetime, timedelta
from pathlib import Path

from psycopg.types.json import Jsonb
from xingtu.contracts import PlatformRegistry
from xingtu.creator_update import CreatorUpdateService, reconcile_update_task
from xingtu.domain import (
    Candidate,
    Checkpoint,
    CreatorRef,
    ExecutionContext,
    ProfileRequirement,
    TaskKind,
    TaskRecord,
    TaskStatus,
    uid,
)
from xingtu.engine import Engine
from xingtu.product_queries import ProductQueries
from xingtu.repository import Repository

from backend.tests.synthetic import SyntheticAdapter

ROOT = Path(__file__).resolve().parents[3]


def registry() -> PlatformRegistry:
    return PlatformRegistry.model_validate_json(
        (ROOT / "contracts/douyin_xingtu.verified.json").read_text()
    )


def requirement() -> ProfileRequirement:
    return ProfileRequirement.model_validate_json(
        (ROOT / "contracts/profile_requirements.json").read_text()
    )


def seed_creator(
    repo: Repository, *, platform_creator_id: str = "999", followers: int = 120000
) -> str:
    creator_id = uid()
    with repo.connect() as conn:
        conn.execute(
            """INSERT INTO platform_creators(creator_id,platform,platform_creator_id)
            VALUES(%s,'douyin_xingtu',%s)""",
            (creator_id, platform_creator_id),
        )
        conn.execute(
            """INSERT INTO douyin_xingtu_creator_current(
            creator_id,platform_creator_id,followers_count,data_updated_at,
            profile_complete,pipeline_complete) VALUES(%s,%s,%s,now(),true,true)""",
            (creator_id, platform_creator_id, followers),
        )
    return creator_id


def seed_user(repo: Repository) -> str:
    user_id = uid()
    with repo.connect() as conn:
        conn.execute(
            """INSERT INTO users(user_id,username,display_name,password_hash)
            VALUES(%s,%s,'Tester','x')""",
            (user_id, "tester-" + user_id[:8]),
        )
    return user_id


def test_manual_update_creates_task_and_is_idempotent(repo):
    creator_id = seed_creator(repo)
    user_id = seed_user(repo)
    service = CreatorUpdateService(repo, registry(), requirement())

    first = service.create_manual_update(creator_id, user_id=user_id, idempotency_key="k1")
    assert first.status == TaskStatus.QUEUED and not first.reused
    task = repo.get(first.root_task_id)
    assert task.task_kind == TaskKind.MANUAL_UPDATE
    assert task.plan is None and task.target_count == 1
    with repo.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM filter_plans").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM requirements").fetchone()["n"] == 0

    replay = service.create_manual_update(creator_id, user_id=user_id, idempotency_key="k1")
    assert replay.root_task_id == first.root_task_id

    while_running = service.create_manual_update(creator_id, user_id=user_id, idempotency_key="k2")
    assert while_running.root_task_id == first.root_task_id
    assert while_running.reused is True

    claimed = repo.claim_unassigned_update("unit")
    assert claimed == first.root_task_id
    assert repo.get(first.root_task_id).execution_unit_id == "unit"
    status = service.status(creator_id)
    assert status.in_flight_root_task_id == first.root_task_id
    assert status.task_stage == "等待采集资源"

    queries = ProductQueries(repo)
    page = queries.list_tasks(task_kind=TaskKind.MANUAL_UPDATE)
    assert [item.root_task_id for item in page.items] == [first.root_task_id]
    detail = queries.get_task(first.root_task_id)
    assert detail.task_kind == TaskKind.MANUAL_UPDATE
    assert detail.update_targets[0].platform_creator_id == "999"
    assert detail.update_targets[0].state == "pending"
    assert queries.list_tasks(task_kind=TaskKind.COLLECTION).items == []

    # A key that reused the in-flight task must still replay that task after it finishes.
    with repo.connect() as conn:
        conn.execute(
            "UPDATE root_tasks SET state='COMPLETED' WHERE root_task_id=%s",
            (first.root_task_id,),
        )
    replay_after_completion = service.create_manual_update(
        creator_id, user_id=user_id, idempotency_key="k2"
    )
    assert replay_after_completion.root_task_id == first.root_task_id
    assert replay_after_completion.reused is True
    with repo.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM root_tasks").fetchone()["n"] == 1


def test_scheduler_creates_one_batch_and_marks_in_flight(repo):
    creator_id = seed_creator(repo)
    with repo.connect() as conn:
        conn.execute(
            "UPDATE douyin_xingtu_creator_current SET data_updated_at=%s WHERE creator_id=%s",
            (datetime.now(UTC) - timedelta(days=10), creator_id),
        )
    service = CreatorUpdateService(repo, registry(), requirement(), batch_size=5)
    assert service.scheduler_tick()["created"] == 1
    with repo.connect() as conn:
        roots = conn.execute("SELECT task_kind,state,unit_id FROM root_tasks").fetchall()
        rows = conn.execute(
            "SELECT in_flight_root_task_id FROM creator_update_schedule WHERE creator_id=%s",
            (creator_id,),
        ).fetchall()
    assert len(roots) == 1
    assert roots[0]["task_kind"] == "scheduled_update"
    assert roots[0]["state"] == "QUEUED"
    assert roots[0]["unit_id"] is None
    assert rows[0]["in_flight_root_task_id"] is not None
    assert service.scheduler_tick()["created"] == 0


def test_reconcile_resets_cycle_only_for_a_complete_snapshot(repo):
    creator_id = seed_creator(repo)
    user_id = seed_user(repo)
    service = CreatorUpdateService(repo, registry(), requirement())
    created = service.create_manual_update(creator_id, user_id=user_id, idempotency_key="k1")
    repo.claim_unassigned_update("unit")
    with repo.connect() as conn:
        conn.execute(
            "UPDATE root_tasks SET state='COMPLETED' WHERE root_task_id=%s",
            (created.root_task_id,),
        )
        snapshot_id = uid()
        captured = datetime.now(UTC)
        conn.execute(
            """INSERT INTO creator_snapshots(
            snapshot_id,root_task_id,creator_id,draft_revision,payload)
            VALUES(%s,%s,%s,0,%s)""",
            (snapshot_id, created.root_task_id, creator_id, Jsonb({})),
        )
        conn.execute(
            """INSERT INTO douyin_xingtu_creator_snapshot_index(
            snapshot_id,creator_id,captured_at,profile_complete,pipeline_complete)
            VALUES(%s,%s,%s,true,true)""",
            (snapshot_id, creator_id, captured),
        )
    service.reconcile_creator(creator_id)
    status = service.status(creator_id)
    assert status.in_flight_root_task_id is None
    assert status.last_success_at is not None
    assert status.last_success_snapshot_id == snapshot_id
    assert status.next_due_at is not None
    assert status.next_due_at > status.last_success_at


def test_scheduler_does_not_create_a_batch_while_normal_collection_is_runnable(repo, plan):
    seed_creator(repo)
    with repo.connect() as conn:
        conn.execute(
            "UPDATE douyin_xingtu_creator_current SET data_updated_at=%s",
            (datetime.now(UTC) - timedelta(days=10),),
        )
    repo.create(
        plan,
        "unit",
        uid(),
        "test",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        modules=["basic", "commercial", "fans"],
    )
    service = CreatorUpdateService(repo, registry(), requirement())
    result = service.scheduler_tick()
    assert result["created"] == 0
    assert result["skipped"] == 1


def test_terminal_edit_reconciles_schedule_without_status_read(repo):
    creator_id = seed_creator(repo)
    user_id = seed_user(repo)
    service = CreatorUpdateService(repo, registry(), requirement())
    created = service.create_manual_update(creator_id, user_id=user_id, idempotency_key="k1")
    repo.claim_unassigned_update("unit")
    captured = datetime.now(UTC)
    snapshot_id = uid()
    with repo.connect() as conn:
        conn.execute(
            """INSERT INTO creator_snapshots(
            snapshot_id,root_task_id,creator_id,draft_revision,payload)
            VALUES(%s,%s,%s,0,%s)""",
            (snapshot_id, created.root_task_id, creator_id, Jsonb({})),
        )
        conn.execute(
            """INSERT INTO douyin_xingtu_creator_snapshot_index(
            snapshot_id,creator_id,captured_at,profile_complete,pipeline_complete)
            VALUES(%s,%s,%s,true,true)""",
            (snapshot_id, creator_id, captured),
        )
    # Repository.edit is the single terminal write boundary; no status read or scheduler tick.
    with repo.edit(created.root_task_id) as (task, _):
        task.state = TaskStatus.COMPLETED
    schedule = (
        repo.connect()
        .execute(
            """SELECT in_flight_root_task_id,last_success_snapshot_id,last_success_at
        FROM creator_update_schedule WHERE creator_id=%s""",
            (creator_id,),
        )
        .fetchone()
    )
    assert schedule["in_flight_root_task_id"] is None
    assert str(schedule["last_success_snapshot_id"]) == snapshot_id
    assert schedule["last_success_at"] is not None
    assert reconcile_update_task(repo, created.root_task_id) == 0


def test_cancel_command_reconciles_schedule_without_status_read(repo):
    creator_id = seed_creator(repo)
    user_id = seed_user(repo)
    service = CreatorUpdateService(repo, registry(), requirement())
    created = service.create_manual_update(creator_id, user_id=user_id, idempotency_key="k1")
    repo.claim_unassigned_update("unit")
    detail = ProductQueries(repo).command(
        created.root_task_id,
        "cancel",
        expected_version=repo.get(created.root_task_id).version,
        user_id=user_id,
        idempotency_key="cancel-1",
    )
    assert detail.status == TaskStatus.CANCELLED
    schedule = (
        repo.connect()
        .execute(
            "SELECT in_flight_root_task_id FROM creator_update_schedule WHERE creator_id=%s",
            (creator_id,),
        )
        .fetchone()
    )
    assert schedule["in_flight_root_task_id"] is None


def test_pool_claim_and_priority_gate(repo, plan):
    creator_id = seed_creator(repo)
    user_id = seed_user(repo)
    service = CreatorUpdateService(repo, registry(), requirement())
    update = service.create_manual_update(creator_id, user_id=user_id, idempotency_key="k1")
    normal = repo.create(
        plan,
        "unit",
        uid(),
        "test",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        modules=["basic", "commercial", "fans"],
    )
    assert repo.has_runnable_higher_priority_task(
        "unit", update.root_task_id, TaskKind.MANUAL_UPDATE
    )
    assert not repo.has_runnable_higher_priority_task("unit", normal, TaskKind.COLLECTION)
    repo.claim_unassigned_update("unit")
    repo.set_unit_task_kinds("unit", [TaskKind.COLLECTION], "tester", "dedicated collection")
    task = repo.get(update.root_task_id)
    assert task.execution_unit_id == ""
    assert repo.unit("unit")["allowed_task_kinds"] == ["collection"]


async def test_engine_run_update_does_not_search_or_duplicate_creator(repo):
    ref = CreatorRef(
        platform_creator_id="1",
        verified_homepage="https://synthetic.invalid/creator/1",
        first_position=0,
    )
    task = TaskRecord(
        root_task_id=uid(),
        task_id=uid(),
        attempt_id=uid(),
        plan=None,
        task_kind=TaskKind.MANUAL_UPDATE,
        update_targets=[ref],
        state=TaskStatus.QUEUED,
        execution_unit_id="unit",
        checkpoint=Checkpoint(
            conditions_digest="update:test",
            adapter_version="synthetic-v1",
            contract_version="synthetic-v1",
            profile_module_keys=["basic", "commercial", "fans"],
            profile_checkpoint_versions={"basic": 1, "commercial": 1, "fans": 1},
            featured_collection_types=["excellent_reach"],
            featured_checkpoint_versions={"excellent_reach": 1},
            candidates=[Candidate(ref=ref)],
        ),
    )
    with repo.connect() as conn:
        conn.execute(
            """INSERT INTO root_tasks(root_task_id,state,version,unit_id,payload,task_kind)
            VALUES(%s,'QUEUED',0,'unit',%s,'manual_update')""",
            (
                task.root_task_id,
                Jsonb(task.model_dump(mode="json", exclude={"checkpoint"})),
            ),
        )
        conn.execute(
            "INSERT INTO tasks VALUES(%s,%s,NULL,'P2-1')",
            (task.task_id, task.root_task_id),
        )
        conn.execute(
            "INSERT INTO task_attempts(attempt_id,root_task_id,segment) VALUES(%s,%s,0)",
            (task.attempt_id, task.root_task_id),
        )
        conn.execute(
            "INSERT INTO task_checkpoints VALUES(%s,0,%s)",
            (task.task_id, Jsonb(task.checkpoint.model_dump(mode="json"))),
        )
        conn.execute(
            "INSERT INTO task_dispatches VALUES(%s,0,%s,false)",
            (task.root_task_id, f"collect/{task.root_task_id}"),
        )
    generation, session = repo.acquire("unit", task.attempt_id)
    ctx = ExecutionContext(
        root_task_id=task.root_task_id,
        task_id=task.task_id,
        attempt_id=task.attempt_id,
        execution_unit_id="unit",
        lease_generation=generation,
        session_version=session,
        capability_version="synthetic-v1",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
    )
    adapter = SyntheticAdapter(["1"], featured={"excellent_reach": {}})
    result = await Engine(repo, adapter, ctx).run_update()
    assert result in {TaskStatus.COMPLETED, TaskStatus.PARTIAL_COMPLETED}
    assert adapter.prepared == []
    assert adapter.visits == ["1"]
    with repo.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM platform_creators").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM creator_snapshots").fetchone()["n"] == 1
    fresh = repo.get(task.root_task_id)
    assert fresh.task_kind == TaskKind.MANUAL_UPDATE
    assert fresh.valid_count == 1
