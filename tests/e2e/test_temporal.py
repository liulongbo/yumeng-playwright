"""Real Temporal test server + PostgreSQL + synthetic adapter, not live platform acceptance."""

import asyncio
import os
from pathlib import Path

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker
from xingtu.domain import CollectorError, TaskStatus
from xingtu.engine import Engine
from xingtu.intake import LLMResult, build_expected_plan
from xingtu.intake_worker import IntakeActivities, IntakeProcessor
from xingtu.intake_workflow import IntakeWorkflow
from xingtu.product_auth import PasswordService
from xingtu.product_models import RequirementForm
from xingtu.product_repository import ProductRepository
from xingtu.workflow import CollectionWorkflow

from backend.tests.synthetic import SyntheticAdapter


async def test_product_intake_workflow_promotes_same_root_and_replays(repo):
    from xingtu.contracts import PlatformRegistry

    products = ProductRepository(repo)
    user_id = products.create_user(
        "temporal-media",
        "Temporal 媒介",
        PasswordService().hash("a-secure-password"),
        actor="test",
    )
    registry = PlatformRegistry.model_validate_json(
        Path("contracts/douyin_xingtu.verified.json").read_text()
    )
    form = RequirementForm(keyword="宠物", target_count=20)
    created = products.create_product_task(
        form,
        capability_version=registry.capabilities.version,
        user_id=user_id,
        idempotency_key="temporal-intake",
        model_config_id="synthetic-flash",
        prompt_version="m3-filter-plan-v1",
    )
    expected = build_expected_plan(form, registry.capabilities)

    class SyntheticLLM:
        provider = "synthetic"
        model = "synthetic-flash"

        async def generate_filter_plan(self, **kwargs):
            del kwargs
            return LLMResult(payload=expected.model_dump(mode="json"), response_model=self.model)

    processor = IntakeProcessor(
        products,
        registry,
        SyntheticLLM(),
        execution_unit_id="unit",
    )
    activities = IntakeActivities(processor)
    executable = os.environ.get("XINGTU_TEMPORAL_TEST_BINARY")
    async with await WorkflowEnvironment.start_local(
        dev_server_existing_path=executable,
        dev_server_download_version="v1.9.1",
        download_dest_dir=str(Path(".runtime/temporal-test").resolve()),
        dev_server_log_level="error",
    ) as env:
        async with Worker(
            env.client,
            task_queue="product-intake-test",
            workflows=[IntakeWorkflow],
            activities=[activities.process],
        ):
            handle = await env.client.start_workflow(
                IntakeWorkflow.run,
                created.root_task_id,
                id="intake-" + created.root_task_id,
                task_queue="product-intake-test",
            )
            assert await handle.result() == TaskStatus.QUEUED
            history = await handle.fetch_history()
            await Replayer(workflows=[IntakeWorkflow]).replay_workflow(history)
    task = repo.get(created.root_task_id)
    assert task.root_task_id == created.root_task_id
    assert task.source == "model" and task.plan == expected
    with repo.connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM model_runs WHERE root_task_id=%s",
                (created.root_task_id,),
            ).fetchone()["n"]
            == 1
        )
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM task_dispatches WHERE root_task_id=%s",
                (created.root_task_id,),
            ).fetchone()["n"]
            == 1
        )


async def test_waiting_for_login_requires_an_explicit_wake(repo, started):
    calls = 0

    @activity.defn(name="collect_segment_v1")
    async def segment(root: str) -> str:
        nonlocal calls
        calls += 1
        activity.heartbeat(root)
        if calls == 1:
            with repo.edit(root) as (task, _):
                task.state = TaskStatus.WAITING_FOR_LOGIN
            return TaskStatus.WAITING_FOR_LOGIN
        with repo.edit(root) as (task, _):
            task.state = TaskStatus.FAILED
        return TaskStatus.FAILED

    executable = os.environ.get("XINGTU_TEMPORAL_TEST_BINARY")
    async with await WorkflowEnvironment.start_local(
        dev_server_existing_path=executable,
        dev_server_download_version="v1.9.1",
        download_dest_dir=str(Path(".runtime/temporal-test").resolve()),
        dev_server_log_level="error",
    ) as env:
        async with Worker(
            env.client,
            task_queue="login-wake-test",
            workflows=[CollectionWorkflow],
            activities=[segment],
        ):
            handle = await env.client.start_workflow(
                CollectionWorkflow.run,
                started.root_task_id,
                id="login-wake-" + started.root_task_id,
                task_queue="login-wake-test",
            )
            async with asyncio.timeout(30):
                while repo.get(started.root_task_id).state != TaskStatus.WAITING_FOR_LOGIN:
                    await asyncio.sleep(0.05)
            await asyncio.sleep(0.2)
            assert calls == 1
            await handle.signal(CollectionWorkflow.wake)
            assert await handle.result() == TaskStatus.FAILED
            assert calls == 2
            history = await handle.fetch_history()
            await Replayer(workflows=[CollectionWorkflow]).replay_workflow(history)


async def test_temporal_pause_signal_resume_and_replay(repo, started):
    calls = 0

    @activity.defn(name="collect_segment_v1")
    async def segment(root: str) -> str:
        nonlocal calls
        calls += 1
        activity.heartbeat(root)
        if calls == 1:
            engine = Engine(
                repo, SyntheticAdapter(["bad", "1", "2"], invalid=["bad"]), started, scan_budget=1
            )
            try:
                return await engine.run()
            except CollectorError as exc:
                return engine.record_error(exc)
        return await Engine(
            repo, SyntheticAdapter(["bad", "1", "2"], invalid=["bad"]), started
        ).run()

    # Pinned official local test server, independently versioned from the Compose runtime.
    executable = os.environ.get("XINGTU_TEMPORAL_TEST_BINARY")
    async with await WorkflowEnvironment.start_local(
        dev_server_existing_path=executable,
        dev_server_download_version="v1.9.1",
        download_dest_dir=str(Path(".runtime/temporal-test").resolve()),
        dev_server_log_level="error",
    ) as env:
        async with Worker(
            env.client,
            task_queue="synthetic-test",
            workflows=[CollectionWorkflow],
            activities=[segment],
        ):
            handle = await env.client.start_workflow(
                CollectionWorkflow.run,
                started.root_task_id,
                id="synthetic-" + started.root_task_id,
                task_queue="synthetic-test",
            )
            async with asyncio.timeout(30):
                while repo.get(started.root_task_id).state != TaskStatus.PAUSED_BUDGET:
                    await asyncio.sleep(0.05)
            with repo.edit(started.root_task_id) as (task, _):
                task.state = TaskStatus.QUEUED
                task.checkpoint.scanned_ids = []
                task.checkpoint.active_seconds = 0
            # Duplicate wakes are intentional: they must resume the same workflow/root exactly
            # once, without creating a second task or duplicating persisted creator counts.
            await handle.signal(CollectionWorkflow.wake)
            await handle.signal(CollectionWorkflow.wake)
            assert await handle.result() == "PARTIAL_COMPLETED"
            assert repo.get(started.root_task_id).valid_count == 2
            assert calls == 2
            with repo.connect() as conn:
                assert conn.execute("SELECT count(*) AS n FROM root_tasks").fetchone()["n"] == 1
            history = await handle.fetch_history()
            await Replayer(workflows=[CollectionWorkflow]).replay_workflow(history)


async def test_activities_refuse_unverified_registry_and_stop_terminal(repo, plan, tmp_path):
    """Real Activity + workflow negative test: the live registry gate is not bypassable.

    This also exercises the local-stage harness plumbing (real `Activities.collect` on the local
    Temporal test server) without any platform traffic.
    """
    from xingtu.domain import uid
    from xingtu.runtime import UnitConfig
    from xingtu.worker import Activities

    root = repo.create(
        plan,
        "unit",
        uid(),
        "test",
        adapter_version="browser-v1",
        contract_version="xingtu-unverified-v1",
        modules=[],
    )
    profiles = tmp_path / "profiles"
    config = UnitConfig.model_validate(
        {
            "unit_id": "unit",
            "account_ref": "synthetic-account",
            "expected_account_id": "synthetic",
            "line_id": "local-dev",
            "profile_directory": str(profiles / "unit"),
            "registry_path": str(Path("contracts/douyin_xingtu.unverified.json").resolve()),
            "network_mode": "local_development",
            "browser_channel": "chromium",
        }
    )
    activities = Activities(repo, config, profiles)
    executable = os.environ.get("XINGTU_TEMPORAL_TEST_BINARY")
    async with await WorkflowEnvironment.start_local(
        dev_server_existing_path=executable,
        dev_server_download_version="v1.9.1",
        download_dest_dir=str(Path(".runtime/temporal-test").resolve()),
        dev_server_log_level="error",
    ) as env:
        async with Worker(
            env.client,
            task_queue="xingtu-unit",
            workflows=[CollectionWorkflow],
            activities=[activities.collect],
        ):
            handle = await env.client.start_workflow(
                CollectionWorkflow.run,
                root,
                id="gate-" + root,
                task_queue="xingtu-unit",
            )
            async with asyncio.timeout(30):
                assert await handle.result() == TaskStatus.FAILED
    final = repo.get(root)
    assert final.state == TaskStatus.FAILED
    assert "UNVERIFIED_REGISTRY" in (final.failure_reason or "")


async def test_featured_completion_propagates_and_replays(repo, plan, tmp_path):
    """F05 + F06 completion reaches COMPLETED through the real workflow, and history replays."""
    from xingtu.covers import CoverPipeline, LocalCoverStore
    from xingtu.domain import ExecutionContext, uid
    from xingtu.engine import Engine

    from backend.tests.synthetic import SyntheticAdapter

    collections = ["excellent_reach", "excellent_seeding"]
    root = repo.create(
        plan.model_copy(update={"target_count": 2}),
        "unit",
        uid(),
        "test",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        modules=["basic", "commercial", "fans"],
        featured_types=collections,
        featured_checkpoint_versions={key: 1 for key in collections},
    )
    task = repo.get(root)
    generation, session = repo.acquire("unit", task.attempt_id)
    ctx = ExecutionContext(
        root_task_id=root,
        task_id=task.task_id,
        attempt_id=task.attempt_id,
        execution_unit_id="unit",
        lease_generation=generation,
        session_version=session,
        capability_version="synthetic-v1",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
    )
    covers = CoverPipeline(repo, LocalCoverStore(repo, tmp_path / "covers", tmp_path))
    adapter = SyntheticAdapter(
        ["1", "2"],
        featured={
            "excellent_reach": {
                "cards": [
                    {
                        "platform_content_id": "v1",
                        "link": "https://synthetic.invalid/work/v1",
                        "title": "title v1",
                        "play": 1,
                        "cover": "https://cdn.synthetic.invalid/v1.png",
                    }
                ],
                "set_key": "set-a",
            },
            "excellent_seeding": {
                "cards": [
                    {
                        "platform_content_id": "v1",
                        "link": "https://synthetic.invalid/work/v1",
                        "title": "seeding v1",
                        "play": 9,
                        "cover": "https://cdn.synthetic.invalid/v1.png",
                    }
                ],
                "set_key": "set-b",
            },
        },
    )

    @activity.defn(name="collect_segment_v1")
    async def segment(root_task_id: str) -> str:
        activity.heartbeat(root_task_id)
        return await Engine(repo, adapter, ctx, covers=covers).run()

    executable = os.environ.get("XINGTU_TEMPORAL_TEST_BINARY")
    async with await WorkflowEnvironment.start_local(
        dev_server_existing_path=executable,
        dev_server_download_version="v1.9.1",
        download_dest_dir=str(Path(".runtime/temporal-test").resolve()),
        dev_server_log_level="error",
    ) as env:
        async with Worker(
            env.client,
            task_queue="featured-test",
            workflows=[CollectionWorkflow],
            activities=[segment],
        ):
            handle = await env.client.start_workflow(
                CollectionWorkflow.run,
                root,
                id="featured-" + root,
                task_queue="featured-test",
            )
            async with asyncio.timeout(60):
                assert await handle.result() == TaskStatus.COMPLETED
            history = await handle.fetch_history()
            await Replayer(workflows=[CollectionWorkflow]).replay_workflow(history)

    final = repo.get(root)
    assert final.state == TaskStatus.COMPLETED
    assert final.pipeline_complete and final.featured_status == "COMPLETED"
    assert final.featured_complete_count == final.valid_count == 2
    # One work appears in both modules: one stored object, two independent card observations.
    with repo.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM contents").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM featured_cards").fetchone()["n"] == 4
        assert (
            conn.execute(
                "SELECT count(DISTINCT cover_object_id) AS n FROM featured_cards"
            ).fetchone()["n"]
            == 1
        )
