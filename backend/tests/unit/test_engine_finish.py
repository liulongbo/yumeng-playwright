from contextlib import contextmanager
from types import SimpleNamespace

from xingtu.domain import TaskStatus
from xingtu.engine import Engine


class FakeRepo:
    def __init__(self, task):
        self.task = task
        self.require_lease = None
        self.published = 0

    def get(self, root):
        return self.task

    def capability_has_failure_streak(self, *args):
        return False

    @contextmanager
    def edit(self, root, ctx=None, *, require_lease=True):
        self.require_lease = require_lease
        yield self.task, None

    def profile_complete(self, task, creator):
        return True

    def pipeline_complete(self, task, creator):
        return True

    def persist_creators(self, conn, task, *, publish=False, only_creator=None):
        self.published += 1


def make_engine(valid_count, target_count):
    task = SimpleNamespace(
        root_task_id="root",
        task_id="task",
        attempt_id="attempt",
        plan=object(),
        state=TaskStatus.COLLECTING,
        valid_count=valid_count,
        target_count=target_count,
        profile_complete_count=0,
        featured_complete_count=0,
        featured_status="NOT_ATTEMPTED",
        pipeline_complete=False,
        failure_reason=None,
        profile_requirement=None,
        checkpoint=SimpleNamespace(candidates=[], search_stop_reason=None, active_seconds=0.0),
    )
    repo = FakeRepo(task)
    ctx = SimpleNamespace(
        root_task_id="root",
        contract_version="v1",
        budget=SimpleNamespace(active_seconds=100, candidate_scan=lambda count: count),
    )
    adapter = SimpleNamespace(module_keys=[], featured_keys=[])
    return Engine(repo, adapter, ctx), repo, task


def test_forced_finish_skips_lease_and_finalizes_partial_result():
    engine, repo, task = make_engine(valid_count=2, target_count=10)
    state = engine.finish(force=True, failure_reason="HEARTBEAT_TIMEOUT")
    assert state == TaskStatus.PARTIAL_COMPLETED
    assert task.state == TaskStatus.PARTIAL_COMPLETED
    assert task.failure_reason == "HEARTBEAT_TIMEOUT"
    assert repo.require_lease is False
    assert repo.published == 1


def test_forced_finish_still_allows_completed_when_target_and_pipeline_are_complete():
    engine, repo, task = make_engine(valid_count=10, target_count=10)
    state = engine.finish(force=True, failure_reason="HEARTBEAT_TIMEOUT")
    assert state == TaskStatus.COMPLETED
    assert task.state == TaskStatus.COMPLETED
    assert task.failure_reason is None
    assert repo.require_lease is False
    assert repo.published == 1


def test_normal_finish_keeps_lease_required():
    engine, repo, _ = make_engine(valid_count=0, target_count=10)
    engine.finish()
    assert repo.require_lease is True


def test_repository_interrupted_finalizer_partial_and_idempotent():
    from contextlib import contextmanager

    from xingtu.repository import Repository

    class FakeRepo(Repository):
        def __init__(self, task):
            self.task = task
            self.persisted = 0
            self.saved = 0

        @contextmanager
        def connect(self):
            yield None

        def _load(self, conn, root, lock=True):
            return self.task

        def persist_creators(self, conn, task, *, publish=False):
            self.persisted += 1

        def _save(self, conn, task):
            self.saved += 1

    task = SimpleNamespace(
        attempt_id="attempt",
        state=TaskStatus.COLLECTING,
        valid_count=2,
        failure_reason=None,
    )
    repo = FakeRepo(task)
    assert repo.finalize_interrupted("root", "attempt", "HEARTBEAT_TIMEOUT") == "PARTIAL_COMPLETED"
    assert task.state == TaskStatus.PARTIAL_COMPLETED
    assert task.failure_reason == "HEARTBEAT_TIMEOUT"
    assert repo.persisted == 1 and repo.saved == 1

    # A late/duplicate cancellation must not republish or overwrite a terminal task.
    assert repo.finalize_interrupted("root", "attempt", "HEARTBEAT_TIMEOUT") == "PARTIAL_COMPLETED"
    assert repo.persisted == 1 and repo.saved == 1


def test_repository_interrupted_finalizer_marks_failed_without_valid_data():
    from contextlib import contextmanager

    from xingtu.repository import Repository

    class FakeRepo(Repository):
        def __init__(self, task):
            self.task = task
            self.persisted = 0
            self.saved = 0

        @contextmanager
        def connect(self):
            yield None

        def _load(self, conn, root, lock=True):
            return self.task

        def persist_creators(self, conn, task, *, publish=False):
            self.persisted += 1

        def _save(self, conn, task):
            self.saved += 1

    task = SimpleNamespace(
        attempt_id="attempt",
        state=TaskStatus.COLLECTING,
        valid_count=0,
        failure_reason=None,
    )
    repo = FakeRepo(task)
    assert repo.finalize_interrupted("root", "attempt", "HEARTBEAT_TIMEOUT") == "FAILED"
    assert task.state == TaskStatus.FAILED
    assert repo.persisted == 1 and repo.saved == 1


def test_repository_interrupted_finalizer_rejects_stale_generation():
    from contextlib import contextmanager

    from xingtu.repository import Repository

    class Cursor:
        def __init__(self, row):
            self.row = row

        def fetchone(self):
            return self.row

    class Conn:
        def __init__(self, generation):
            self.generation = generation

        def execute(self, sql, params=None):
            return Cursor({"generation": self.generation})

    class FakeRepo(Repository):
        def __init__(self, task, generation):
            self.task = task
            self.generation = generation
            self.persisted = 0
            self.saved = 0

        @contextmanager
        def connect(self):
            yield Conn(self.generation)

        def _load(self, conn, root, lock=True):
            return self.task

        def persist_creators(self, conn, task, *, publish=False):
            self.persisted += 1

        def _save(self, conn, task):
            self.saved += 1

    task = SimpleNamespace(
        attempt_id="attempt",
        state=TaskStatus.COLLECTING,
        valid_count=2,
        failure_reason=None,
        execution_unit_id="unit",
    )
    stale = FakeRepo(task, generation=6)
    assert (
        stale.finalize_interrupted("root", "attempt", "HEARTBEAT_TIMEOUT", lease_generation=5)
        == "COLLECTING"
    )
    assert stale.persisted == 0 and stale.saved == 0

    current = FakeRepo(task, generation=5)
    assert (
        current.finalize_interrupted("root", "attempt", "HEARTBEAT_TIMEOUT", lease_generation=5)
        == "PARTIAL_COMPLETED"
    )
    assert current.persisted == 1 and current.saved == 1
