"""P2 collection dispatch-loop robustness tests (no Temporal server, no database).

Regression guards for the failure found in the 2026-10-11 real run: one cancellation wake signal
raised ``RPCError: workflow execution already completed`` inside ``dispatch()``, which propagated
out of ``run_worker``'s ``while True`` loop and killed the only collection consumer. No collection
worker means every submitted task waits forever, and the fingerprint is identical to "no worker
running".
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode
from xingtu.domain import TaskStatus
from xingtu.worker import dispatch, run_worker

ROOT = "02c81708-49b5-4384-b119-6ff3f5eb48c8"
QUEUE = "xingtu-unit-local-mac-02"
UNIT = "unit-local-mac-02"


def rpc_error(message: str = "workflow execution already completed") -> RPCError:
    return RPCError(message, RPCStatusCode.NOT_FOUND, b"")


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeConnection:
    def __init__(self, repository: FakeRepository) -> None:
        self.repository = repository

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> FakeCursor:
        self.repository.statements.append((sql, params))
        if sql.strip().startswith("SELECT d.*"):
            return FakeCursor(
                [
                    row
                    for row in self.repository.dispatches
                    if not row["sent"] and row["unit_id"] == params[0]
                ]
            )
        if "state='CANCELLING'" in sql:
            return FakeCursor(
                [
                    {"root_task_id": row["root_task_id"]}
                    for row in self.repository.cancelling
                    if row["unit_id"] == params[0]
                ]
            )
        return FakeCursor([])

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class FakeRepository:
    def __init__(
        self,
        *,
        dispatches: list[dict[str, Any]] | None = None,
        cancelling: list[dict[str, Any]] | None = None,
        connect_error: Exception | None = None,
    ) -> None:
        self.dispatches = dispatches or []
        self.cancelling = cancelling or []
        self.connect_error = connect_error
        self.statements: list[tuple[str, tuple[Any, ...]]] = []
        self.states: dict[str, str] = {}
        self.worker_stops: list[tuple[str, str, int, str]] = []

    def register_worker_instance(
        self, unit_id: str, instance_id: str, pid: int, platform_name: str
    ) -> int:
        del unit_id, instance_id, pid, platform_name
        return 1

    def unit(self, unit_id: str) -> dict[str, Any]:
        del unit_id
        return {"state": "READY", "failure_reason": None}

    def has_active_unit_claim(self, unit_id: str) -> bool:
        del unit_id
        return False

    def heartbeat_worker_instance(self, unit_id: str, instance_id: str, generation: int) -> None:
        del unit_id, instance_id, generation

    def stop_worker_instance(
        self, unit_id: str, instance_id: str, generation: int, reason: str
    ) -> None:
        self.worker_stops.append((unit_id, instance_id, generation, reason))

    def connect(self) -> FakeConnection:
        if self.connect_error:
            raise self.connect_error
        return FakeConnection(self)

    def edit(self, root: str):
        repository = self

        class Edit:
            def __enter__(self) -> tuple[Any, None]:
                return (FakeTask(root, repository), None)

            def __exit__(self, *_: object) -> None:
                return None

        return Edit()


class FakeTask:
    def __init__(self, root: str, repository: FakeRepository) -> None:
        object.__setattr__(self, "_repository", repository)
        object.__setattr__(self, "root_task_id", root)
        object.__setattr__(self, "state", TaskStatus.QUEUED)

    def __setattr__(self, name: str, value: Any) -> None:
        object.__setattr__(self, name, value)
        if name == "state":
            self._repository.states[self.root_task_id] = str(value)


class FakeHandle:
    def __init__(
        self,
        *,
        status: WorkflowExecutionStatus | None = WorkflowExecutionStatus.RUNNING,
        describe_error: Exception | None = None,
        signal_error: Exception | None = None,
    ) -> None:
        self.status = status
        self.describe_error = describe_error
        self.signal_error = signal_error
        self.signals = 0

    async def describe(self) -> Any:
        if self.describe_error:
            raise self.describe_error
        return SimpleNamespace(status=self.status)

    async def signal(self, *_: Any, **__: Any) -> None:
        self.signals += 1
        if self.signal_error:
            raise self.signal_error


class FakeClient:
    def __init__(self, handle: FakeHandle | None = None) -> None:
        self.handle = handle or FakeHandle()
        self.started: list[str] = []

    def get_workflow_handle(self, workflow_id: str) -> FakeHandle:
        self.last_workflow_id = workflow_id
        return self.handle

    async def start_workflow(self, run: Any, root: str, **kwargs: Any) -> None:
        del run, kwargs
        self.started.append(root)


class FakeConfig:
    unit_id = UNIT


class FakeTemporalWorker:
    """Stands in for temporalio.worker.Worker so run_worker needs no Temporal server."""

    def __init__(self, *_: Any, **__: Any) -> None:
        pass

    async def __aenter__(self) -> FakeTemporalWorker:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


async def test_cancel_wake_signal_that_already_completed_finalises_instead_of_raising():
    """describe() says RUNNING but the workflow ended before signal() -> finalise, never raise."""

    repository = FakeRepository(cancelling=[{"root_task_id": ROOT, "unit_id": UNIT}])
    client = FakeClient(FakeHandle(signal_error=rpc_error()))

    await dispatch(repository, client, QUEUE)  # type: ignore[arg-type]

    assert client.handle.signals == 1
    assert repository.states[ROOT] == "CANCELLED"


async def test_cancel_describe_failure_still_finalises():
    """A workflow that no longer exists cannot hold the task, so CANCELLING must end."""

    repository = FakeRepository(cancelling=[{"root_task_id": ROOT, "unit_id": UNIT}])
    client = FakeClient(FakeHandle(describe_error=rpc_error("workflow not found")))

    await dispatch(repository, client, QUEUE)  # type: ignore[arg-type]

    assert client.handle.signals == 0
    assert repository.states[ROOT] == "CANCELLED"


async def test_cancel_wake_signal_for_a_running_workflow_is_kept_as_cancelling():
    """The wake path itself must stay intact: a running workflow is signalled, not finalised."""

    repository = FakeRepository(cancelling=[{"root_task_id": ROOT, "unit_id": UNIT}])
    client = FakeClient(FakeHandle())

    await dispatch(repository, client, QUEUE)  # type: ignore[arg-type]

    assert client.handle.signals == 1
    assert repository.states == {}


async def test_dispatch_records_the_start_moment_for_started_collections():
    """FIX-01 P1-B reads this durable fact: a started dispatch is never finalised by the API."""

    repository = FakeRepository(
        dispatches=[
            {
                "root_task_id": ROOT,
                "segment": 0,
                "workflow_id": f"collect/{ROOT}",
                "sent": False,
                "unit_id": UNIT,
            }
        ]
    )
    client = FakeClient()

    await dispatch(repository, client, QUEUE)  # type: ignore[arg-type]

    assert client.started == [ROOT]
    updates = [sql for sql, _ in repository.statements if "workflow_started_at=now()" in sql]
    assert updates, repository.statements


async def test_a_failing_tick_never_kills_the_consumer(monkeypatch):
    """The poll loop must survive any tick error; otherwise "no worker" looks like a dead system.

    This exercises the real ``run_worker`` wiring: a fake Temporal client plus a repository whose
    dispatch query always raises. Before the fix the first tick raised out of the loop and the
    consumer died; the assertion is that the loop is still alive after several tick intervals.
    """

    async def fake_connect(address: str) -> FakeClient:
        del address
        return FakeClient()

    monkeypatch.setattr("xingtu.worker.Client.connect", fake_connect)
    monkeypatch.setattr("xingtu.worker.Worker", FakeTemporalWorker)
    repository = FakeRepository(connect_error=RuntimeError("TEMPORAL_UNAVAILABLE"))
    worker = asyncio.create_task(
        run_worker(repository, FakeConfig(), "127.0.0.1:57233", Path(".runtime"))  # type: ignore[arg-type]
    )
    await asyncio.sleep(0.05)
    assert not worker.done(), "the collection consumer exited after a dispatch tick error"
    worker.cancel()
    try:
        await worker
    except asyncio.CancelledError:  # pragma: no cover - cancellation is the test's own action
        pass
