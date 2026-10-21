"""Pin the cheap progress path so a full checkpoint read cannot silently return to guard()."""

from types import SimpleNamespace

import pytest
from xingtu.domain import CollectorError, TaskStatus
from xingtu.engine import Engine


class ProgressRepo:
    def __init__(self, active_seconds: float):
        self.active_seconds = active_seconds
        self.get_calls = 0
        self.progress_calls: list[dict[str, object]] = []

    def get(self, root: str):
        self.get_calls += 1
        return SimpleNamespace(
            root_task_id=root,
            task_id="task",
            attempt_id="attempt",
            state=TaskStatus.COLLECTING,
            target_count=10,
            valid_count=0,
            checkpoint=SimpleNamespace(
                active_seconds=self.active_seconds,
                candidates=[],
                search_stop_reason=None,
            ),
        )

    def capability_has_failure_streak(self, *args):
        return False

    def record_progress(self, root, ctx, *, active_seconds=0.0, counters=None, module_seconds=None):
        self.progress_calls.append(
            {
                "root": root,
                "active_seconds": active_seconds,
                "counters": counters or {},
                "module_seconds": module_seconds or {},
            }
        )
        self.active_seconds += float(active_seconds)
        return self.active_seconds


def _engine(repo: ProgressRepo, budget: float = 100.0) -> Engine:
    ctx = SimpleNamespace(
        root_task_id="root",
        contract_version="v1",
        budget=SimpleNamespace(active_seconds=budget, candidate_scan=lambda count: count),
    )
    adapter = SimpleNamespace(module_keys=[], featured_keys=[], operation_metrics={})
    return Engine(repo, adapter, ctx)


def test_guard_writes_progress_without_reading_the_checkpoint():
    repo = ProgressRepo(active_seconds=4.0)
    engine = _engine(repo)
    engine.guard()
    # Only Engine.__init__ read the task; guard itself must not load the checkpoint again.
    assert repo.get_calls == 1
    assert len(repo.progress_calls) == 1
    assert repo.progress_calls[0]["active_seconds"] > 0
    assert engine.active_seconds > 4.0


def test_guard_uses_the_active_seconds_returned_by_the_progress_write():
    repo = ProgressRepo(active_seconds=99.9)
    engine = _engine(repo, budget=99.9)
    with pytest.raises(CollectorError) as caught:
        engine.guard()
    assert caught.value.code == "BUDGET_EXHAUSTED"
    assert caught.value.reason == "ACTIVE_TIME"


def test_charge_forwards_only_the_allowed_counter_deltas():
    repo = ProgressRepo(active_seconds=0.0)
    engine = _engine(repo)
    engine.adapter.operation_metrics = {"requests": 5, "responses": 2, "navigations": 1}
    engine.charge(0.0)
    assert repo.progress_calls[0]["counters"] == {
        "observed_requests": 5,
        "observed_responses": 2,
        "navigation_count": 1,
    }
    # The same absolute metric values must not be charged twice.
    engine.charge(0.0)
    assert repo.progress_calls[1]["counters"] == {}
