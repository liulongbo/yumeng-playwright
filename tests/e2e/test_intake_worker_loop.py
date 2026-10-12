"""End-to-end regression for the M3 intake consumer loop.

Reproduces the production failure and proves the fix, using the *real* dispatch loop
(`run_intake_worker`), the *real* Temporal workflow and activity, a real PostgreSQL temporary
schema and a synthetic model adapter:

* **A** while no consumer runs, submissions stay ``RECEIVED`` with ``intake_dispatches.sent=false``
  and no ``model_runs`` / ``filter_plans`` -- exactly the reported symptom;
* **B** once the consumer starts, the same backlog advances to ``QUEUED`` and every downstream
  record is created.

Temporal is provided by the in-process test server, so no shared cluster is touched and no platform
traffic occurs.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from xingtu.contracts import PlatformRegistry
from xingtu.domain import TaskStatus
from xingtu.intake import LLMResult, build_expected_plan
from xingtu.intake_worker import IntakeActivities, IntakeProcessor, run_intake_worker
from xingtu.intake_workflow import IntakeWorkflow
from xingtu.product_auth import PasswordService
from xingtu.product_models import RequirementForm
from xingtu.product_repository import ProductRepository
from xingtu.worker_health import check_queues

QUEUE = "xingtu-intake"
UNIT = "unit"
TASKS = 2


class SyntheticLLM:
    provider = "synthetic"
    model = "synthetic-flash"

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    async def generate_filter_plan(self, **kwargs) -> LLMResult:
        del kwargs
        self.calls += 1
        return LLMResult(payload=self.payload, response_model=self.model)


def snapshot(repo, roots: list[str]) -> dict[str, dict]:
    with repo.connect() as conn:
        states = {
            str(row["root_task_id"]): row["state"]
            for row in conn.execute(
                "SELECT root_task_id,state FROM root_tasks WHERE root_task_id = ANY(%s)", (roots,)
            ).fetchall()
        }
        sent = {
            str(row["root_task_id"]): row["sent"]
            for row in conn.execute(
                "SELECT root_task_id,sent FROM intake_dispatches WHERE root_task_id = ANY(%s)",
                (roots,),
            ).fetchall()
        }
        runs = {
            str(row["root_task_id"]): row["n"]
            for row in conn.execute(
                "SELECT root_task_id,count(*) AS n FROM model_runs WHERE root_task_id = ANY(%s) "
                "GROUP BY 1",
                (roots,),
            ).fetchall()
        }
        plans = {
            str(row["root_task_id"]): row["n"]
            for row in conn.execute(
                "SELECT root_task_id,count(*) AS n FROM filter_plans WHERE root_task_id = ANY(%s) "
                "GROUP BY 1",
                (roots,),
            ).fetchall()
        }
        dispatches = {
            str(row["root_task_id"]): row["n"]
            for row in conn.execute(
                "SELECT root_task_id,count(*) AS n FROM task_dispatches "
                "WHERE root_task_id = ANY(%s) GROUP BY 1",
                (roots,),
            ).fetchall()
        }
    return {
        root: {
            "state": states.get(root),
            "sent": sent.get(root),
            "model_runs": runs.get(root, 0),
            "filter_plans": plans.get(root, 0),
            "task_dispatches": dispatches.get(root, 0),
        }
        for root in roots
    }


async def test_intake_backlog_is_stuck_without_a_consumer_and_drains_with_one(repo):
    products = ProductRepository(repo)
    registry = PlatformRegistry.model_validate_json(
        Path("contracts/douyin_xingtu.verified.json").read_text()
    )
    user_id = products.create_user(
        "loop-media", "Loop 媒介", PasswordService().hash("loop-secret-2026"), actor="test"
    )
    form = RequirementForm(keyword="宠物", target_count=4)
    expected = build_expected_plan(form, registry.capabilities)
    roots = [
        products.create_product_task(
            form,
            capability_version=registry.capabilities.version,
            user_id=user_id,
            idempotency_key=f"loop-{index}",
            model_config_id="synthetic-flash",
            prompt_version="m3-filter-plan-v1",
        ).root_task_id
        for index in range(TASKS)
    ]

    # ---- A: no consumer -> the reported symptom, with rows visible to the dispatcher query ----
    before = snapshot(repo, roots)
    for root in roots:
        assert before[root]["state"] == TaskStatus.RECEIVED.value
        assert before[root]["sent"] is False
        assert before[root]["model_runs"] == 0
        assert before[root]["filter_plans"] == 0
        assert before[root]["task_dispatches"] == 0
    assert len(products.pending_intake_dispatches()) == TASKS
    await asyncio.sleep(3.0)
    after_wait = snapshot(repo, roots)
    assert after_wait == before, "nothing may advance while no consumer exists"

    executable = os.environ.get("XINGTU_TEMPORAL_TEST_BINARY")
    async with await WorkflowEnvironment.start_local(
        dev_server_existing_path=executable,
        dev_server_download_version="v1.9.1",
        download_dest_dir=str(Path(".runtime/temporal-test").resolve()),
        dev_server_log_level="error",
    ) as env:
        processor = IntakeProcessor(
            products,
            registry,
            SyntheticLLM(expected.model_dump(mode="json")),
            execution_unit_id=UNIT,
        )
        worker = asyncio.create_task(
            run_intake_worker(
                products, processor, env.client.service_client.config.target_host, queue=QUEUE
            )
        )
        try:
            # The consumer registers on the real queue name.
            alive = False
            for _ in range(60):
                health = (
                    await check_queues(env.client.service_client.config.target_host, [QUEUE])
                )[QUEUE]
                if health.alive:
                    alive = True
                    break
                await asyncio.sleep(0.25)
            assert alive, "the intake worker never appeared as a live consumer on xingtu-intake"

            for _ in range(120):
                drained = snapshot(repo, roots)
                if all(item["state"] == TaskStatus.QUEUED.value for item in drained.values()):
                    break
                await asyncio.sleep(0.25)

            # ---- B: the same backlog advanced, with every downstream record written ----
            for root in roots:
                assert drained[root]["state"] == TaskStatus.QUEUED.value
                assert drained[root]["sent"] is True
                assert drained[root]["model_runs"] == 1
                assert drained[root]["filter_plans"] == 1
                assert drained[root]["task_dispatches"] == 1
            task = repo.get(roots[0])
            assert task.plan is not None
            assert task.plan.filters[0].value == "宠物"
            assert task.plan.target_count == 4
            with repo.connect() as conn:
                audit = [
                    row["action"]
                    for row in conn.execute(
                        "SELECT action FROM audit_logs WHERE root_task_id=%s ORDER BY created_at",
                        (roots[0],),
                    ).fetchall()
                ]
            assert "product_task.create" in audit
            assert "product_intake.promote" in audit
        finally:
            worker.cancel()
            try:
                await worker
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass


async def test_intake_activities_are_registered_on_the_intake_queue(repo):
    """The worker must register both the workflow and the activity the dispatch loop starts."""
    products = ProductRepository(repo)
    registry = PlatformRegistry.model_validate_json(
        Path("contracts/douyin_xingtu.verified.json").read_text()
    )
    processor = IntakeProcessor(
        products, registry, SyntheticLLM({"unused": True}), execution_unit_id=UNIT
    )
    activities = IntakeActivities(processor)
    async with await WorkflowEnvironment.start_local(
        dev_server_existing_path=os.environ.get("XINGTU_TEMPORAL_TEST_BINARY"),
        dev_server_download_version="v1.9.1",
        download_dest_dir=str(Path(".runtime/temporal-test").resolve()),
        dev_server_log_level="error",
    ) as env:
        async with Worker(
            env.client,
            task_queue=QUEUE,
            workflows=[IntakeWorkflow],
            activities=[activities.process],
        ):
            address = env.client.service_client.config.target_host
            for _ in range(60):
                health = (await check_queues(address, [QUEUE]))[QUEUE]
                if health.alive:
                    break
                await asyncio.sleep(0.25)
            assert health.alive is True, "activity-only worker must still register a consumer"
