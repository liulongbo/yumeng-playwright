from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from xingtu.contracts import PlatformRegistry
from xingtu.domain import Candidate, CollectorError, CreatorRef, TaskStatus
from xingtu.intake import LLMFailure, LLMResult, build_expected_plan
from xingtu.intake_worker import IntakeProcessor
from xingtu.product_api import ProductServices, ProductSettings, create_app
from xingtu.product_auth import AuthService, MemoryLoginLimiter, PasswordService
from xingtu.product_covers import ProductCoverConfig
from xingtu.product_models import RequirementForm
from xingtu.product_queries import ProductQueries
from xingtu.product_repository import ProductRepository
from xingtu.repository import TERMINAL_COMPLETED_AT_CLAUSE


def product_user(products):
    return products.create_user(
        "media",
        "媒介 A",
        PasswordService().hash("a-secure-password"),
        actor="test",
    )


def test_product_submit_idempotency_and_same_root_promotion(repo):
    products = ProductRepository(repo)
    user_id = product_user(products)
    registry = PlatformRegistry.model_validate_json(
        Path("contracts/douyin_xingtu.verified.json").read_text()
    )
    form = RequirementForm(keyword="宠物", target_count=20)

    def submit():
        return products.create_product_task(
            form,
            capability_version=registry.capabilities.version,
            user_id=user_id,
            idempotency_key="same-key",
            model_config_id="deepseek-flash",
            prompt_version="m3-filter-plan-v2",
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: submit(), range(4)))
    roots = {response.root_task_id for response in responses}
    assert len(roots) == 1
    root = roots.pop()
    with repo.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM requirements").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM intake_dispatches").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM task_dispatches").fetchone()["n"] == 0
    state = products.load_intake(root)
    plan = build_expected_plan(form, registry.capabilities)
    succeeded = state.model_copy(
        update={"outcome": "succeeded", "final_plan": plan, "attempt_count": 1}
    )
    products.save_intake(succeeded, TaskStatus.PARSING)
    products.promote_intake(
        succeeded,
        plan,
        unit_id="unit",
        registry=registry,
    )
    task = repo.get(root)
    assert task.root_task_id == root
    assert task.source == "model"
    assert task.plan == plan
    with repo.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM task_dispatches").fetchone()["n"] == 1
        assert (
            conn.execute("SELECT count(*) AS n FROM filter_plans WHERE source='model'").fetchone()[
                "n"
            ]
            == 1
        )


def test_product_submit_conflict_rolls_back_without_duplicate(repo):
    products = ProductRepository(repo)
    user_id = product_user(products)
    kwargs = {
        "capability_version": "cap-v1",
        "user_id": user_id,
        "idempotency_key": "one-key",
        "model_config_id": "deepseek-flash",
        "prompt_version": "v1",
    }
    products.create_product_task(RequirementForm(keyword="宠物"), **kwargs)
    with pytest.raises(CollectorError, match="IDEMPOTENCY_CONFLICT"):
        products.create_product_task(RequirementForm(keyword="母婴"), **kwargs)
    with repo.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM requirements").fetchone()["n"] == 1


def test_requirement_discriminator_persists_v2_and_keeps_v1_readable(repo):
    products = ProductRepository(repo)
    user_id = product_user(products)
    products.create_product_task(
        RequirementForm(schema_version="requirement_form.v1", keyword="历史关键词"),
        capability_version="xingtu-ad-creator-square-v1",
        user_id=user_id,
        idempotency_key="requirement-v1",
        model_config_id="synthetic-flash",
        prompt_version="m3-filter-plan-v1",
    )
    products.create_product_task(
        RequirementForm(keyword="新关键词", creator_gender="female"),
        capability_version="xingtu-ad-creator-square-v2",
        user_id=user_id,
        idempotency_key="requirement-v2",
        model_config_id="synthetic-flash",
        prompt_version="m3-filter-plan-v2",
    )

    with repo.connect() as conn:
        rows = conn.execute(
            "SELECT root_task_id,schema_version,payload FROM requirements ORDER BY schema_version"
        ).fetchall()

    assert [row["schema_version"] for row in rows] == [
        "requirement_form.v1",
        "requirement_form.v2",
    ]
    assert (
        RequirementForm.model_validate(rows[0]["payload"]).schema_version == "requirement_form.v1"
    )
    restored_v2 = RequirementForm.model_validate(rows[1]["payload"])
    assert restored_v2.schema_version == "requirement_form.v2"
    assert restored_v2.creator_gender == "female"


def test_product_queries_show_intake_and_cancel_before_browser_allocation(repo):
    products = ProductRepository(repo)
    user_id = product_user(products)
    response = products.create_product_task(
        RequirementForm(keyword="宠物"),
        capability_version="cap-v1",
        user_id=user_id,
        idempotency_key="create",
        model_config_id="deepseek-flash",
        prompt_version="v1",
    )
    queries = ProductQueries(repo)
    detail = queries.get_task(response.root_task_id)
    assert detail.status == "RECEIVED"
    assert detail.allowed_actions == ["cancel"]
    cancelled = queries.command(
        response.root_task_id,
        "cancel",
        expected_version=detail.version,
        user_id=user_id,
        idempotency_key="cancel-key",
    )
    assert cancelled.status == "CANCELLED"
    assert cancelled.allowed_actions == []
    with repo.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM task_dispatches").fetchone()["n"] == 0


class NoopCoverReader:
    def read(self, object_id, *, checksum, byte_size):
        del object_id, checksum, byte_size
        raise AssertionError("cover read was not expected")


def queued_product_task(products, user_id, registry, key):
    """Promote a product task to QUEUED exactly as intake does (no P2 worker involved)."""

    created = create_intake(products, user_id, registry, key)
    plan = build_expected_plan(
        RequirementForm(keyword="宠物", target_count=20), registry.capabilities
    )
    products.promote_intake(
        products.load_intake(created.root_task_id), plan, unit_id="unit", registry=registry
    )
    return created, plan


def test_cancel_queued_task_without_a_started_collection_reaches_cancelled(repo):
    """FIX-01 P1-B: no collection process exists, so the API must terminalise immediately.

    Before the fix this only reached CANCELLING and needed the P2 dispatch loop to finish it, so
    with no P2 worker running the user's cancellation never became visible.
    """

    products = ProductRepository(repo)
    user_id = product_user(products)
    registry = PlatformRegistry.model_validate_json(
        Path("contracts/douyin_xingtu.verified.json").read_text()
    )
    created, _ = queued_product_task(products, user_id, registry, "cancel-queued-unstarted")
    queries = ProductQueries(repo)
    detail = queries.get_task(created.root_task_id)
    assert detail.status == "QUEUED"
    assert detail.allowed_actions == ["cancel"]
    with repo.connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM task_dispatches WHERE root_task_id=%s AND sent",
                (created.root_task_id,),
            ).fetchone()["n"]
            == 0
        )

    cancelled = queries.command(
        created.root_task_id,
        "cancel",
        expected_version=detail.version,
        user_id=user_id,
        idempotency_key="cancel-queued-unstarted-key",
    )
    assert cancelled.status == "CANCELLED"
    assert cancelled.failure_reason == "TASK_CANCELLED"
    assert cancelled.allowed_actions == []
    # One command only: no CANCELLING hop and no version churn beyond the single transition.
    assert cancelled.version == detail.version + 1
    assert repo.get(created.root_task_id).state == TaskStatus.CANCELLED


def test_cancel_queued_task_with_a_started_collection_still_waits_for_p2(repo):
    """The opposite path must not change: a started collection is finalised by the P2 worker."""

    products = ProductRepository(repo)
    user_id = product_user(products)
    registry = PlatformRegistry.model_validate_json(
        Path("contracts/douyin_xingtu.verified.json").read_text()
    )
    created, _ = queued_product_task(products, user_id, registry, "cancel-queued-started")
    with repo.connect() as conn:
        conn.execute(
            "UPDATE task_dispatches SET sent=true,workflow_started_at=now() WHERE root_task_id=%s",
            (created.root_task_id,),
        )
    queries = ProductQueries(repo)
    detail = queries.get_task(created.root_task_id)
    cancelled = queries.command(
        created.root_task_id,
        "cancel",
        expected_version=detail.version,
        user_id=user_id,
        idempotency_key="cancel-queued-started-key",
    )
    assert cancelled.status == "CANCELLING"
    assert cancelled.allowed_actions == []
    # P2 owns the terminal transition; the API must not race it.
    assert repo.get(created.root_task_id).state == TaskStatus.CANCELLING


async def test_real_dispatch_records_the_start_moment_in_the_database(repo):
    """FIX-01 P1-B end of the loop: the real ``worker.dispatch`` SQL writes the durable fact.

    The unit tests cover the dispatch loop with fakes; this one runs the real SQL against a real
    database so the migration column, the UPDATE and the cancel gate are verified together. A fake
    Temporal client keeps the test offline and the root task is left CANCELLED so its workflow stops
    at the activity's terminal-state check without touching the platform.
    """

    from xingtu.worker import dispatch

    products = ProductRepository(repo)
    user_id = product_user(products)
    registry = PlatformRegistry.model_validate_json(
        Path("contracts/douyin_xingtu.verified.json").read_text()
    )
    created, _ = queued_product_task(products, user_id, registry, "real-dispatch-start")

    class FakeHandle:
        async def describe(self):
            raise AssertionError("no cancellation wake expected")

        async def signal(self, *_: object) -> None:
            raise AssertionError("no cancellation wake expected")

    class FakeClient:
        def __init__(self) -> None:
            self.started: list[str] = []

        def get_workflow_handle(self, workflow_id: str) -> FakeHandle:
            del workflow_id
            return FakeHandle()

        async def start_workflow(self, run: object, root: str, **kwargs: object) -> None:
            del run, kwargs
            self.started.append(root)

    client = FakeClient()
    # ``dispatch`` addresses units by ``xingtu-<unit_id>``; ``queued_product_task`` promotes with
    # unit_id="unit", so this queue selects exactly that row.
    await dispatch(repo, client, "xingtu-unit")  # type: ignore[arg-type]
    assert client.started == [created.root_task_id]

    with repo.connect() as conn:
        row = conn.execute(
            "SELECT sent,workflow_started_at FROM task_dispatches WHERE root_task_id=%s",
            (created.root_task_id,),
        ).fetchone()
        assert row is not None
        assert row["workflow_started_at"] is not None, (
            "the real UPDATE must record the start moment"
        )
        # And the cancel gate now sees a possibly-held task, so it must NOT terminalise it itself.
        assert ProductQueries(repo)._collect_workflow_started(conn, created.root_task_id, 0)


def test_authenticated_api_shared_tasks_idempotency_and_audit(repo):
    products = ProductRepository(repo)
    passwords = PasswordService()
    first = products.create_user(
        "media-a", "媒介 A", passwords.hash("a-secure-password"), actor="test"
    )
    second = products.create_user(
        "media-b", "媒介 B", passwords.hash("b-secure-password"), actor="test"
    )
    registry_path = Path("contracts/douyin_xingtu.verified.json")
    settings = ProductSettings(
        database_url=repo.dsn,
        redis_url="unused",
        login_hmac_key=b"x" * 32,
        registry_path=registry_path,
        secure_cookie=True,
        allowed_origins=("https://app.test",),
        cover_config=ProductCoverConfig(
            kind="local", directory=Path(".runtime/covers"), allowed_root=Path(".runtime")
        ),
    )
    app = create_app(
        ProductServices(
            auth=AuthService(products, MemoryLoginLimiter(), passwords=passwords),
            products=products,
            queries=ProductQueries(repo),
            registry=PlatformRegistry.model_validate_json(registry_path.read_text()),
            covers=NoopCoverReader(),
            settings=settings,
        )
    )
    client = TestClient(app, base_url="https://app.test")
    login = client.post(
        "/api/auth/login",
        headers={"Origin": "https://app.test"},
        json={"username": "media-a", "password": "a-secure-password"},
    )
    assert login.status_code == 200
    csrf = login.json()["csrf_token"]
    headers = {
        "Origin": "https://app.test",
        "X-CSRF-Token": csrf,
        "Idempotency-Key": "submit-once",
    }
    created = client.post(
        "/api/tasks", headers=headers, json={"keyword": "宠物", "target_count": 20}
    )
    repeated = client.post(
        "/api/tasks", headers=headers, json={"keyword": "宠物", "target_count": 20}
    )
    assert created.status_code == repeated.status_code == 202
    assert created.json()["root_task_id"] == repeated.json()["root_task_id"]
    root = created.json()["root_task_id"]
    client.post(
        "/api/auth/logout",
        headers={"Origin": "https://app.test", "X-CSRF-Token": csrf},
    )
    assert client.get(f"/api/tasks/{root}").status_code == 401
    login_b = client.post(
        "/api/auth/login",
        headers={"Origin": "https://app.test"},
        json={"username": "media-b", "password": "b-secure-password"},
    )
    assert login_b.status_code == 200
    assert client.get(f"/api/tasks/{root}").status_code == 200
    csrf_b = login_b.json()["csrf_token"]
    cancelled = client.post(
        f"/api/tasks/{root}/cancel",
        headers={
            "Origin": "https://app.test",
            "X-CSRF-Token": csrf_b,
            "Idempotency-Key": "cancel-once",
        },
        json={"expected_version": 0},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    conflict = client.post(
        f"/api/tasks/{root}/cancel",
        headers={
            "Origin": "https://app.test",
            "X-CSRF-Token": csrf_b,
            "Idempotency-Key": "stale-cancel",
        },
        json={"expected_version": 0},
    )
    assert conflict.status_code == 409
    assert conflict.json()["current_version"] == 1
    assert conflict.json()["allowed_actions"] == []
    with repo.connect() as conn:
        task_audit = conn.execute(
            """SELECT actor_user_id,action FROM audit_logs WHERE root_task_id=%s
            ORDER BY created_at""",
            (root,),
        ).fetchall()
    assert [(str(row["actor_user_id"]), row["action"]) for row in task_audit] == [
        (first, "product_task.create"),
        (second, "cancel"),
    ]


class StaticLLM:
    provider = "synthetic"
    model = "synthetic-flash"

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    async def generate_filter_plan(self, **kwargs):
        del kwargs
        self.calls += 1
        return LLMResult(payload=self.payload, response_model=self.model)


def create_intake(products, user_id, registry, key):
    return products.create_product_task(
        RequirementForm(keyword="宠物", target_count=20),
        capability_version=registry.capabilities.version,
        user_id=user_id,
        idempotency_key=key,
        model_config_id="synthetic-flash",
        prompt_version="m3-filter-plan-v2",
    )


async def test_intake_processor_records_model_run_and_promotes_once(repo):
    products = ProductRepository(repo)
    user_id = product_user(products)
    registry = PlatformRegistry.model_validate_json(
        Path("contracts/douyin_xingtu.verified.json").read_text()
    )
    created = create_intake(products, user_id, registry, "processor-success")
    plan = build_expected_plan(RequirementForm(keyword="宠物"), registry.capabilities)
    llm = StaticLLM(plan.model_dump(mode="json"))
    processor = IntakeProcessor(products, registry, llm, execution_unit_id="unit")
    assert await processor.process(created.root_task_id) == TaskStatus.QUEUED
    assert llm.calls == 1
    assert repo.get(created.root_task_id).source == "model"
    with repo.connect() as conn:
        runs = conn.execute(
            "SELECT status,response_model FROM model_runs WHERE root_task_id=%s",
            (created.root_task_id,),
        ).fetchall()
        dispatches = conn.execute(
            "SELECT count(*) AS n FROM task_dispatches WHERE root_task_id=%s",
            (created.root_task_id,),
        ).fetchone()["n"]
    assert [(row["status"], row["response_model"]) for row in runs] == [
        ("succeeded", "synthetic-flash")
    ]
    assert dispatches == 1


async def test_intake_processor_rejects_changed_value_after_three_without_p2(repo):
    products = ProductRepository(repo)
    user_id = product_user(products)
    registry = PlatformRegistry.model_validate_json(
        Path("contracts/douyin_xingtu.verified.json").read_text()
    )
    created = create_intake(products, user_id, registry, "processor-failure")
    changed = build_expected_plan(
        RequirementForm(keyword="宠物", target_count=21), registry.capabilities
    )
    llm = StaticLLM(changed.model_dump(mode="json"))
    processor = IntakeProcessor(products, registry, llm, execution_unit_id="unit")
    assert await processor.process(created.root_task_id) == TaskStatus.FAILED_VALIDATION
    assert llm.calls == 3
    detail = ProductQueries(repo).get_task(created.root_task_id)
    assert detail.status == TaskStatus.FAILED_VALIDATION
    assert detail.field_errors[0].code == "VALUE_CHANGED"
    with repo.connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM model_runs WHERE root_task_id=%s",
                (created.root_task_id,),
            ).fetchone()["n"]
            == 3
        )
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM task_dispatches WHERE root_task_id=%s",
                (created.root_task_id,),
            ).fetchone()["n"]
            == 0
        )


class FailingLLM:
    provider = "synthetic"
    model = "synthetic-flash"

    def __init__(self):
        self.calls = 0

    async def generate_filter_plan(self, **kwargs):
        del kwargs
        self.calls += 1
        raise LLMFailure("AI_PROVIDER_RETRYABLE", "temporary", retryable=True)


async def test_failed_model_step_can_retry_with_new_bounded_cycle(repo):
    products = ProductRepository(repo)
    user_id = product_user(products)
    registry = PlatformRegistry.model_validate_json(
        Path("contracts/douyin_xingtu.verified.json").read_text()
    )
    created = create_intake(products, user_id, registry, "processor-model-failure")
    failing = FailingLLM()
    processor = IntakeProcessor(products, registry, failing, execution_unit_id="unit")
    assert await processor.process(created.root_task_id) == TaskStatus.FAILED
    assert failing.calls == 3
    detail = ProductQueries(repo).get_task(created.root_task_id)
    assert detail.allowed_actions == ["retry"]
    retried = ProductQueries(repo).command(
        created.root_task_id,
        "retry",
        expected_version=detail.version,
        user_id=user_id,
        idempotency_key="retry-intake-cycle",
    )
    assert retried.status == TaskStatus.RECEIVED
    correct = build_expected_plan(RequirementForm(keyword="宠物"), registry.capabilities)
    retry_llm = StaticLLM(correct.model_dump(mode="json"))
    retry_processor = IntakeProcessor(products, registry, retry_llm, execution_unit_id="unit")
    assert await retry_processor.process(created.root_task_id) == TaskStatus.QUEUED
    with repo.connect() as conn:
        cycles = conn.execute(
            """SELECT retry_cycle,count(*) AS n FROM model_runs WHERE root_task_id=%s
            GROUP BY retry_cycle ORDER BY retry_cycle""",
            (created.root_task_id,),
        ).fetchall()
    assert [(row["retry_cycle"], row["n"]) for row in cycles] == [(0, 3), (1, 1)]


def test_running_creator_projection_is_explicitly_a_draft(repo, plan):
    root = repo.create(
        plan,
        "unit",
        "draft-key",
        "test",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        modules=["basic"],
    )
    with repo.edit(root) as (task, conn):
        candidate = Candidate(
            ref=CreatorRef(
                platform_creator_id="draft-creator",
                verified_homepage="https://synthetic.invalid/creator/draft-creator",
                first_position=0,
            ),
            valid=True,
            state="collecting",
        )
        task.checkpoint.candidates = [candidate]
        task.valid_count = 1
        repo.persist_creators(conn, task, publish=False)
    page = ProductQueries(repo).list_creators(root)
    assert len(page.items) == 1
    assert page.items[0].view_kind == "draft"
    assert page.items[0].snapshot_id is None
    assert page.items[0].payload["state"] == "collecting"


async def test_cancelled_intake_never_calls_model_or_allocates_browser(repo):
    products = ProductRepository(repo)
    user_id = product_user(products)
    registry = PlatformRegistry.model_validate_json(
        Path("contracts/douyin_xingtu.verified.json").read_text()
    )
    created = create_intake(products, user_id, registry, "cancel-before-intake")
    ProductQueries(repo).command(
        created.root_task_id,
        "cancel",
        expected_version=0,
        user_id=user_id,
        idempotency_key="cancel-intake",
    )
    plan = build_expected_plan(RequirementForm(keyword="宠物"), registry.capabilities)
    llm = StaticLLM(plan.model_dump(mode="json"))
    processor = IntakeProcessor(products, registry, llm, execution_unit_id="unit")
    assert await processor.process(created.root_task_id) == TaskStatus.CANCELLED
    assert llm.calls == 0
    with repo.connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM model_runs WHERE root_task_id=%s",
                (created.root_task_id,),
            ).fetchone()["n"]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM task_dispatches WHERE root_task_id=%s",
                (created.root_task_id,),
            ).fetchone()["n"]
            == 0
        )


class StaticMonitor:
    """Fake WorkerHealthMonitor: tests the intake progress contract without Temporal."""

    def __init__(self, alive: bool | None) -> None:
        self.alive = alive

    def intake_health(self, queue: str):
        from xingtu.worker_health import QueueHealth

        del queue
        return QueueHealth(
            queue="xingtu-intake",
            alive=self.alive,
            fresh_pollers=1 if self.alive else 0,
            poller_entries=1 if self.alive is not None else 0,
            error=None if self.alive is not None else "TemporalUnreachable",
        )


def intake_detail(repo, monitor: StaticMonitor, root_task_id: str):
    """Uses the production default threshold so the test exercises the real decision rule."""
    return ProductQueries(repo, monitor).get_task(root_task_id)


def backdate_intake_dispatch(repo, root_task_id: str, minutes: int) -> None:
    """Simulate a task that has been waiting: a live dispatch loop would have flipped `sent`."""
    with repo.connect() as conn:
        conn.execute(
            "UPDATE intake_dispatches SET created_at = now() - make_interval(mins => %s) "
            "WHERE root_task_id=%s",
            (minutes, root_task_id),
        )


def test_intake_progress_distinguishes_waiting_consumer_loss_and_dispatch_failure(repo):
    """The UI must be able to tell "waiting normally" from "no consumer" from "dispatch failing"."""
    products = ProductRepository(repo)
    user_id = product_user(products)
    registry = PlatformRegistry.model_validate_json(
        Path("contracts/douyin_xingtu.verified.json").read_text()
    )
    form = RequirementForm(keyword="宠物")
    created = products.create_product_task(
        form,
        capability_version=registry.capabilities.version,
        user_id=user_id,
        idempotency_key="blocked-intake",
        model_config_id="deepseek-flash",
        prompt_version="v1",
    )
    root = created.root_task_id

    # A: just submitted, inside the normal dispatch window -> never claim a fault.
    fresh = intake_detail(repo, StaticMonitor(False), root).intake
    assert fresh is not None
    assert fresh.sent is False
    assert fresh.pending_seconds is not None and fresh.pending_seconds < 120
    assert fresh.blocked_reason is None

    # B: the coarse poller signal is exposed as diagnostic metadata, tri-state included.
    assert fresh.consumer_alive is False
    assert intake_detail(repo, StaticMonitor(True), root).intake.consumer_alive is True
    assert intake_detail(repo, StaticMonitor(None), root).intake.consumer_alive is None

    # C: waiting far beyond the dispatch cadence with no failure recorded -> no consumer.
    backdate_intake_dispatch(repo, root, 10)
    blocked = intake_detail(repo, StaticMonitor(False), root).intake
    assert blocked is not None
    assert blocked.blocked_reason == "INTAKE_WORKER_UNAVAILABLE"
    assert blocked.blocked_seconds is not None and blocked.blocked_seconds >= 600
    # The verdict intentionally does not depend on the coarse poller signal.
    assert intake_detail(repo, StaticMonitor(True), root).intake.blocked_reason == (
        "INTAKE_WORKER_UNAVAILABLE"
    )

    # D: a recorded dispatch failure is reported as such, not as a missing worker.
    products.record_intake_dispatch_failure(root, "TemporalUnreachable", throttle_seconds=0)
    failing = intake_detail(repo, StaticMonitor(True), root).intake
    assert failing is not None
    assert failing.blocked_reason == "INTAKE_DISPATCH_FAILING"
    assert failing.dispatch_error == "TemporalUnreachable"

    # E: once dispatched the block disappears, whatever the poller says.
    products.mark_intake_dispatched(root)
    sent = intake_detail(repo, StaticMonitor(False), root).intake
    assert sent is not None
    assert sent.sent is True
    assert sent.blocked_reason is None

    # F: outside the intake stage the field is history and is not returned.
    plan = build_expected_plan(form, registry.capabilities)
    products.promote_intake(products.load_intake(root), plan, unit_id="unit", registry=registry)
    promoted = intake_detail(repo, StaticMonitor(False), root)
    assert promoted.status == "QUEUED"
    assert promoted.intake is None


def test_api_serialises_intake_block_reason(repo):
    """Guards the response model: a missing consumer must reach the UI as a field."""
    products = ProductRepository(repo)
    passwords = PasswordService()
    products.create_user("media-a", "媒介 A", passwords.hash("pw-a-secure-2026"), actor="test")
    registry_path = Path("contracts/douyin_xingtu.verified.json")
    settings = ProductSettings(
        database_url=repo.dsn,
        redis_url="unused",
        login_hmac_key=b"x" * 32,
        registry_path=registry_path,
        secure_cookie=True,
        allowed_origins=("https://app.test",),
        cover_config=ProductCoverConfig(
            kind="local", directory=Path(".runtime/covers"), allowed_root=Path(".runtime")
        ),
    )
    app = create_app(
        ProductServices(
            auth=AuthService(products, MemoryLoginLimiter(), passwords=passwords),
            products=products,
            queries=ProductQueries(repo, StaticMonitor(False)),
            registry=PlatformRegistry.model_validate_json(registry_path.read_text()),
            covers=NoopCoverReader(),
            settings=settings,
        )
    )
    client = TestClient(app, base_url="https://app.test")
    login = client.post(
        "/api/auth/login",
        headers={"Origin": "https://app.test"},
        json={"username": "media-a", "password": "pw-a-secure-2026"},
    )
    csrf = login.json()["csrf_token"]
    created = client.post(
        "/api/tasks",
        headers={
            "Origin": "https://app.test",
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "blocked-submit",
        },
        json={"keyword": "宠物", "target_count": 20},
    )
    assert created.status_code == 202
    root = created.json()["root_task_id"]
    root_id = root

    # Inside the dispatch window nothing is reported as blocked.
    early = client.get(f"/api/tasks/{root_id}").json()["intake"]
    assert early["blocked_reason"] is None
    assert early["sent"] is False

    backdate_intake_dispatch(repo, root_id, 10)
    detail = client.get(f"/api/tasks/{root_id}")
    assert detail.status_code == 200
    assert detail.json()["intake"]["blocked_reason"] == "INTAKE_WORKER_UNAVAILABLE"
    assert detail.json()["intake"]["consumer_alive"] is False


def test_origin_root_task_id_is_validated_before_the_foreign_key(repo):
    """X-Origin-Root-Task-Id is client input; an unknown task must be 422, never an unhandled 500.

    The header used to reach the INSERT unchecked, so a syntactically valid UUID naming no task
    raised a ForeignKeyViolation outside the CollectorError handler. The three cases below pin the
    rejected, accepted and absent forms. The database foreign key is deliberately kept as the
    backstop for a source task deleted concurrently with this request.
    """
    products = ProductRepository(repo)
    passwords = PasswordService()
    products.create_user(
        "media-origin", "媒介 Origin", passwords.hash("origin-password"), actor="test"
    )
    registry_path = Path("contracts/douyin_xingtu.verified.json")
    settings = ProductSettings(
        database_url=repo.dsn,
        redis_url="unused",
        login_hmac_key=b"x" * 32,
        registry_path=registry_path,
        secure_cookie=True,
        allowed_origins=("https://app.test",),
        cover_config=ProductCoverConfig(
            kind="local", directory=Path(".runtime/covers"), allowed_root=Path(".runtime")
        ),
    )
    app = create_app(
        ProductServices(
            auth=AuthService(products, MemoryLoginLimiter(), passwords=passwords),
            products=products,
            queries=ProductQueries(repo),
            registry=PlatformRegistry.model_validate_json(registry_path.read_text()),
            covers=NoopCoverReader(),
            settings=settings,
        )
    )
    client = TestClient(app, base_url="https://app.test")
    login = client.post(
        "/api/auth/login",
        headers={"Origin": "https://app.test"},
        json={"username": "media-origin", "password": "origin-password"},
    )
    assert login.status_code == 200
    csrf = login.json()["csrf_token"]

    def submit(key: str, origin: str | None):
        headers = {
            "Origin": "https://app.test",
            "X-CSRF-Token": csrf,
            "Idempotency-Key": key,
        }
        if origin is not None:
            headers["X-Origin-Root-Task-Id"] = origin
        return client.post(
            "/api/tasks", headers=headers, json={"keyword": "宠物", "target_count": 1}
        )

    unknown = "11111111-1111-1111-1111-111111111111"
    missing = submit("origin-missing", unknown)
    assert missing.status_code == 422
    body = missing.json()
    assert body["code"] == "INVALID_FORM"
    assert body["message"] == "ORIGIN_TASK_NOT_FOUND"
    assert body["request_id"]
    assert body["field_errors"] == []
    with repo.connect() as conn:
        left = conn.execute(
            "SELECT count(*) AS n FROM root_tasks WHERE origin_root_task_id=%s", (unknown,)
        ).fetchone()
    assert left and left["n"] == 0

    source = submit("origin-source", None)
    assert source.status_code == 202
    source_root = source.json()["root_task_id"]

    linked = submit("origin-linked", source_root)
    assert linked.status_code == 202
    linked_root = linked.json()["root_task_id"]
    with repo.connect() as conn:
        row = conn.execute(
            "SELECT origin_root_task_id FROM root_tasks WHERE root_task_id=%s", (linked_root,)
        ).fetchone()
    assert row and str(row["origin_root_task_id"]) == source_root


def test_completed_at_is_recorded_once_a_task_reaches_a_terminal_state(repo):
    """UI-01 R4: `updated_at` is a last-write audit value, so completion needs its own column.

    A progressing task must report no completion moment; a terminal one must report exactly the
    transition into its terminal state, and a later rewrite of the same row must not move it.
    """

    products = ProductRepository(repo)
    user_id = product_user(products)
    created = products.create_product_task(
        RequirementForm(keyword="宠物"),
        capability_version="cap-v1",
        user_id=user_id,
        idempotency_key="completed-at-create",
        model_config_id="deepseek-flash",
        prompt_version="v1",
    )
    queries = ProductQueries(repo)
    waiting = queries.get_task(created.root_task_id)
    assert waiting.status == "RECEIVED"
    assert waiting.completed_at is None
    with repo.connect() as conn:
        assert (
            conn.execute(
                "SELECT completed_at FROM root_tasks WHERE root_task_id=%s",
                (created.root_task_id,),
            ).fetchone()["completed_at"]
            is None
        )

    cancelled = queries.command(
        created.root_task_id,
        "cancel",
        expected_version=waiting.version,
        user_id=user_id,
        idempotency_key="completed-at-cancel",
    )
    assert cancelled.status == "CANCELLED"
    assert cancelled.completed_at is not None
    with repo.connect() as conn:
        stored = conn.execute(
            "SELECT completed_at FROM root_tasks WHERE root_task_id=%s",
            (created.root_task_id,),
        ).fetchone()["completed_at"]
    assert stored == cancelled.completed_at

    # A later write to the same task refreshes `updated_at` but must never overwrite the recorded
    # completion moment. This mirrors the runtime write path's CASE expression.
    with repo.connect() as conn:
        conn.execute(
            "UPDATE root_tasks SET version=version+1,updated_at=now()"
            + TERMINAL_COMPLETED_AT_CLAUSE
            + " WHERE root_task_id=%s",
            (True, created.root_task_id),
        )
    after = queries.get_task(created.root_task_id)
    assert after.completed_at == cancelled.completed_at
    assert after.updated_at > cancelled.updated_at


def create_retryable_task(repo, plan, *, target, valid):
    scoped = plan.model_copy(update={"target_count": target})
    root = repo.create(
        scoped,
        "unit",
        f"retry-plan-{target}-{valid}",
        "test",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        modules=["basic"],
    )
    with repo.edit(root) as (task, _):
        for index in range(valid):
            task.checkpoint.candidates.append(
                Candidate(
                    ref=CreatorRef(
                        platform_creator_id=f"creator-{index}",
                        verified_homepage=f"https://synthetic.invalid/creator/creator-{index}",
                        first_position=index,
                    ),
                    state="failed",
                    valid=True,
                )
            )
        task.valid_count = valid
        task.profile_complete_count = 0
        task.state = TaskStatus.PARTIAL_COMPLETED
        task.failure_reason = "MODULE_COLLECTION_FAILED"
    return root


def test_retry_plan_derives_scope_from_the_creator_count(repo, plan):
    queries = ProductQueries(repo)
    continue_root = create_retryable_task(repo, plan, target=2, valid=1)
    continue_detail = queries.get_task(continue_root)
    assert "retry" in continue_detail.allowed_actions
    assert continue_detail.retry_plan is not None
    assert continue_detail.retry_plan.scope == "continue"
    assert continue_detail.retry_plan.remaining_to_target == 1
    assert continue_detail.retry_plan.incomplete_valid_count == 1
    assert continue_detail.retry_plan.retryable_creator_count == 1

    backfill_root = create_retryable_task(repo, plan, target=1, valid=1)
    backfill_detail = queries.get_task(backfill_root)
    assert backfill_detail.retry_plan is not None
    assert backfill_detail.retry_plan.scope == "backfill"
    assert backfill_detail.retry_plan.remaining_to_target == 0


def test_retry_command_keeps_counted_creators_and_records_the_goal(repo, plan):
    products = ProductRepository(repo)
    user_id = product_user(products)
    root = create_retryable_task(repo, plan, target=2, valid=1)
    queries = ProductQueries(repo)
    detail = queries.get_task(root)
    accepted = queries.command(
        root,
        "retry",
        expected_version=detail.version,
        user_id=user_id,
        idempotency_key="retry-continue-goal",
    )
    assert accepted.status == TaskStatus.QUEUED
    assert accepted.retry_plan is not None
    assert accepted.retry_plan.last_retry_at is not None
    assert accepted.retry_plan.changed_since_last_retry == 0
    # A creator that already counts is not re-queued for collection.
    task = repo.get(root)
    assert task.checkpoint.candidates[0].state == "failed"
    with repo.connect() as conn:
        action = conn.execute(
            "SELECT action FROM audit_logs WHERE root_task_id=%s ORDER BY id DESC LIMIT 1",
            (root,),
        ).fetchone()["action"]
    assert action == "retry:continue"


def test_product_retry_rejects_security_challenge_terminal(repo, plan):
    products = ProductRepository(repo)
    user_id = product_user(products)
    root = create_retryable_task(repo, plan, target=2, valid=1)
    with repo.edit(root) as (task, _):
        task.failure_reason = "SECURITY_CHALLENGE_TIMEOUT"
    queries = ProductQueries(repo)
    detail = queries.get_task(root)
    assert "retry" not in detail.allowed_actions
    with pytest.raises(CollectorError) as error:
        queries.command(
            root,
            "retry",
            expected_version=detail.version,
            user_id=user_id,
            idempotency_key="retry-challenge",
        )
    assert error.value.code == "INVALID_FORM"
    assert error.value.reason == "ACTION_NOT_ALLOWED"
