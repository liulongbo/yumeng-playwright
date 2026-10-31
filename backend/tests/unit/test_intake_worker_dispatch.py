"""Dispatch-loop robustness tests (no Temporal server, no database).

Regression guard for the failure mode found during the M3 diagnosis: a single ``start_workflow``
error used to propagate out of ``dispatch_intakes`` and out of the ``while True`` poll loop, which
silently killed the only intake consumer. The fingerprint was identical to "no worker running":
``intake_dispatches.sent`` stayed false with no error recorded anywhere.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from temporalio.exceptions import WorkflowAlreadyStartedError
from xingtu.domain import CollectorError, TaskStatus
from xingtu.intake_worker import IntakeProcessor, dispatch_intakes, run_intake_worker
from xingtu.product_models import FieldError, P1WorkflowState, RequirementForm


class FakeRepository:
    def __init__(self, roots: list[str], *, failure: Exception | None = None) -> None:
        self.roots = roots
        self.failure = failure
        self.marked: list[str] = []
        self.recorded: list[tuple[str, str]] = []
        self.pending_calls = 0

    def pending_intake_dispatches(self) -> list[dict[str, Any]]:
        self.pending_calls += 1
        return [
            {"root_task_id": root, "workflow_id": f"intake/{root}"}
            for root in self.roots
            if root not in self.marked
        ]

    def mark_intake_dispatched(self, root_task_id: str) -> None:
        self.marked.append(root_task_id)

    def record_intake_dispatch_failure(
        self, root_task_id: str, error_code: str, *, throttle_seconds: int = 60
    ) -> None:
        del throttle_seconds
        self.recorded.append((root_task_id, error_code))


class FakeClient:
    def __init__(self, *, fail_for: set[str] | None = None, error: Exception | None = None) -> None:
        self.fail_for = fail_for or set()
        self.error = error or RuntimeError("TEMPORAL_UNAVAILABLE")
        self.started: list[str] = []

    async def start_workflow(self, run, root_task_id: str, **kwargs: Any) -> None:
        del run, kwargs
        if root_task_id in self.fail_for:
            raise self.error
        self.started.append(root_task_id)


async def test_dispatch_marks_every_pending_task():
    repository = FakeRepository(["a", "b"])
    client = FakeClient()
    dispatched = await dispatch_intakes(repository, client, queue="xingtu-intake")  # type: ignore[arg-type]
    assert dispatched == 2
    assert client.started == ["a", "b"]
    assert repository.marked == ["a", "b"]
    assert repository.recorded == []


async def test_failing_dispatch_records_and_never_aborts_the_loop():
    """One failing task must not stop the others and must not raise."""
    repository = FakeRepository(["a", "b", "c"])
    client = FakeClient(fail_for={"a"})
    dispatched = await dispatch_intakes(repository, client, queue="xingtu-intake")  # type: ignore[arg-type]
    assert dispatched == 2
    assert client.started == ["b", "c"]
    assert repository.marked == ["b", "c"]
    assert repository.recorded == [("a", "RuntimeError")]
    # The failed task stays unsent, so the next poll tick retries it.
    assert "a" not in repository.marked


async def test_temporal_outage_does_not_raise_and_leaves_everything_unsent():
    repository = FakeRepository(["a", "b"])
    client = FakeClient(fail_for={"a", "b"}, error=CollectorError("STORAGE_UNAVAILABLE", "boom"))
    dispatched = await dispatch_intakes(repository, client, queue="xingtu-intake")  # type: ignore[arg-type]
    assert dispatched == 0
    assert repository.marked == []
    assert [code for _, code in repository.recorded] == ["CollectorError", "CollectorError"]


async def test_already_started_workflow_is_treated_as_dispatched():
    repository = FakeRepository(["a"])
    client = FakeClient(error=WorkflowAlreadyStartedError("intake/a", "intake"))
    dispatched = await dispatch_intakes(repository, client, queue="xingtu-intake")  # type: ignore[arg-type]
    assert dispatched == 1
    assert repository.marked == ["a"]
    assert repository.recorded == []


class FailingPromoteRepository:
    def __init__(self, error: CollectorError) -> None:
        self.error = error
        self.failure: tuple[str, list[FieldError]] | None = None

    def promote_intake(self, *args: Any, **kwargs: Any) -> str:
        del args, kwargs
        raise self.error

    def fail_intake(self, state: P1WorkflowState, status: TaskStatus, errors: list[FieldError]):
        self.failure = (status.value, errors)


class FakeGraph:
    """Stands in for IntakeGraph: the promotion attempt is what these tests exercise."""

    def __init__(self, state: P1WorkflowState) -> None:
        self.state = state

    async def run(self, state: P1WorkflowState) -> P1WorkflowState:
        del state
        return self.state.model_copy(
            update={"outcome": "succeeded", "final_plan": _synthetic_plan()}
        )


def _synthetic_plan():
    from xingtu.domain import Filter, FilterPlan

    return FilterPlan(
        capability_version="cap-v1",
        target_count=1,
        filters=[Filter(field="keyword", operator="eq", value="宠物", source_fields=["keyword"])],
    )


def make_processor(repository: Any) -> IntakeProcessor:
    """Node arguments are evaluated eagerly, so the registry stub needs a ``capabilities`` attr."""
    registry = SimpleNamespace(capabilities=SimpleNamespace(version="cap-v1"))
    return IntakeProcessor(repository, registry, SimpleNamespace(), execution_unit_id="unit")


async def test_promotion_failure_finalises_the_task_instead_of_parsing_forever(monkeypatch):
    """A failed promotion must produce FAILED + a reason, never a silent PARSING forever."""
    error = CollectorError("RESOURCE_UNAVAILABLE", "EXECUTION_UNIT_NOT_FOUND")
    repository = FailingPromoteRepository(error)
    state = P1WorkflowState(
        root_task_id="root",
        requirement_id="req",
        p1_task_id="p1",
        requirement_form=RequirementForm(keyword="宠物", target_count=1),
        capability_version="cap-v1",
        capability_snapshot_ref="registry:cap-v1",
        prompt_version="v1",
        model_config_id="deepseek-flash",
    )
    processor = make_processor(repository)
    monkeypatch.setattr(processor.repository, "load_intake", lambda root: state, raising=False)
    monkeypatch.setattr(processor.repository, "save_intake", lambda *a, **k: None, raising=False)
    monkeypatch.setattr("xingtu.intake_worker.IntakeGraph", lambda *a, **k: FakeGraph(state))

    status = await processor.process("root")
    assert status == TaskStatus.FAILED
    assert repository.failure is not None
    failure_status, errors = repository.failure
    assert failure_status == TaskStatus.FAILED.value
    assert errors[0].code == "RESOURCE_UNAVAILABLE"
    assert errors[0].path == "promote"


@pytest.mark.parametrize("expected", [TaskStatus.QUEUED])
async def test_promotion_success_still_reports_queued(monkeypatch, expected):
    class OkRepository(FailingPromoteRepository):
        def promote_intake(self, *args: Any, **kwargs: Any) -> str:
            del args, kwargs
            return "p2"

    repository = OkRepository(CollectorError("INVALID_FORM", "unused"))
    state = P1WorkflowState(
        root_task_id="root",
        requirement_id="req",
        p1_task_id="p1",
        requirement_form=RequirementForm(keyword="宠物", target_count=1),
        capability_version="cap-v1",
        capability_snapshot_ref="registry:cap-v1",
        prompt_version="v1",
        model_config_id="deepseek-flash",
    )
    processor = make_processor(repository)
    monkeypatch.setattr(processor.repository, "load_intake", lambda root: state, raising=False)
    monkeypatch.setattr(processor.repository, "save_intake", lambda *a, **k: None, raising=False)
    monkeypatch.setattr("xingtu.intake_worker.IntakeGraph", lambda *a, **k: FakeGraph(state))
    assert await processor.process("root") == expected


class CapturingPromoteRepository(FailingPromoteRepository):
    """Records which platform requirement a promotion was asked to enforce."""

    def __init__(self) -> None:
        super().__init__(CollectorError("INVALID_FORM", "unused"))
        self.promotions: list[tuple[str, object]] = []

    def promote_intake(self, *args: Any, **kwargs: Any) -> str:
        self.promotions.append((args[1].platform, kwargs.get("profile_requirement")))
        return "p2"


def _juxing_state() -> P1WorkflowState:
    return P1WorkflowState(
        root_task_id="root-juxing",
        requirement_id="req-juxing",
        p1_task_id="p1-juxing",
        requirement_form=RequirementForm.model_validate(
            {
                "schema_version": "requirement_form.v3",
                "platform": "kuaishou_juxing",
                "keyword": "母婴",
                "content_types": ["maternal_child"],
                "target_count": 1,
            }
        ),
        capability_version="cap-juxing",
        capability_snapshot_ref="registry:cap-juxing",
        prompt_version="v1",
        model_config_id="deepseek-flash",
    )


class JuxingGraph(FakeGraph):
    async def run(self, state: P1WorkflowState) -> P1WorkflowState:
        del state
        from xingtu.domain import Filter, FilterPlan

        plan = FilterPlan(
            schema_version="filter_plan.v3",
            platform="kuaishou_juxing",
            capability_version="cap-juxing",
            target_count=1,
            filters=[
                Filter(field="keyword", operator="eq", value="母婴", source_fields=["keyword"])
            ],
        )
        return self.state.model_copy(update={"outcome": "succeeded", "final_plan": plan})


async def test_xingtu_promotion_keeps_the_xingtu_profile_inventory(monkeypatch):
    """The Xingtu full-homepage inventory must stay attached to Xingtu, unchanged."""
    repository = CapturingPromoteRepository()
    state = P1WorkflowState(
        root_task_id="root",
        requirement_id="req",
        p1_task_id="p1",
        requirement_form=RequirementForm(keyword="宠物", target_count=1),
        capability_version="cap-v1",
        capability_snapshot_ref="registry:cap-v1",
        prompt_version="v1",
        model_config_id="deepseek-flash",
    )
    inventory = object()
    registry = SimpleNamespace(capabilities=SimpleNamespace(version="cap-v1"))
    processor = IntakeProcessor(
        repository,  # type: ignore[arg-type]
        registry,  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        execution_unit_id="unit",
        profile_requirement=inventory,  # type: ignore[arg-type]
    )
    monkeypatch.setattr(processor.repository, "load_intake", lambda root: state, raising=False)
    monkeypatch.setattr(processor.repository, "save_intake", lambda *a, **k: None, raising=False)
    monkeypatch.setattr("xingtu.intake_worker.IntakeGraph", lambda *a, **k: FakeGraph(state))

    assert await processor.process("root") == TaskStatus.QUEUED
    assert repository.promotions == [("douyin_xingtu", inventory)]


async def test_juxing_promotion_never_inherits_the_xingtu_profile_inventory(monkeypatch):
    """Regression: the Xingtu inventory made every juxing task permanently incomplete.

    Juxing P0 completeness is defined by its own verified registry modules.  Attaching the Xingtu
    requirement would demand `commercial/fans/creation...` fields the juxing contract never
    collects, leaving a successful run in ``PARTIAL_COMPLETED`` with ``PROFILE_SCOPE_INCOMPLETE``.
    """
    repository = CapturingPromoteRepository()
    state = _juxing_state()
    juxing_registry = SimpleNamespace(capabilities=SimpleNamespace(version="cap-juxing"))
    processor = IntakeProcessor(
        repository,  # type: ignore[arg-type]
        SimpleNamespace(capabilities=SimpleNamespace(version="cap-v1")),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        execution_unit_id="unit",
        profile_requirement=object(),  # type: ignore[arg-type]
        platform_registries={"kuaishou_juxing": juxing_registry},  # type: ignore[dict-item]
    )
    monkeypatch.setattr(processor.repository, "load_intake", lambda root: state, raising=False)
    monkeypatch.setattr(processor.repository, "save_intake", lambda *a, **k: None, raising=False)
    monkeypatch.setattr("xingtu.intake_worker.IntakeGraph", lambda *a, **k: JuxingGraph(state))

    assert await processor.process("root-juxing") == TaskStatus.QUEUED
    assert repository.promotions == [("kuaishou_juxing", None)]


async def test_intake_tick_survives_an_unexpected_listing_failure(monkeypatch):
    """FIX-01 P1-C parity guard.

    The collection consumer already has a "any tick error only logs" wrapper (see
    ``test_collection_worker_dispatch.py``); the intake consumer must stay behaviourally identical,
    otherwise an unexpected repository error once again kills the only intake consumer and looks
    exactly like "no worker running".
    """

    async def fake_connect(address: str) -> FakeClient:
        del address
        return FakeClient()

    class ExplodingRepository(FakeRepository):
        def pending_intake_dispatches(self):
            raise RuntimeError("TEMPORAL_UNAVAILABLE")

    monkeypatch.setattr("xingtu.intake_worker.Client.connect", fake_connect)
    monkeypatch.setattr("xingtu.intake_worker.Worker", FakeTemporalWorker)
    worker = asyncio.create_task(
        run_intake_worker(
            ExplodingRepository([]),  # type: ignore[arg-type]
            SimpleNamespace(),  # type: ignore[arg-type]
            "127.0.0.1:57233",
        )
    )
    await asyncio.sleep(0.05)
    assert not worker.done(), "the intake consumer exited after a dispatch tick error"
    worker.cancel()
    try:
        await worker
    except asyncio.CancelledError:  # pragma: no cover - cancellation is the test's own action
        pass


class FakeTemporalWorker:
    """Stands in for temporalio.worker.Worker so run_intake_worker needs no Temporal server."""

    def __init__(self, *_: Any, **__: Any) -> None:
        pass

    async def __aenter__(self) -> FakeTemporalWorker:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None
