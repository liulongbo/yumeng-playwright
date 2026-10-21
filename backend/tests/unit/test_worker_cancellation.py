from pathlib import Path
from types import SimpleNamespace

from xingtu.domain import CollectorError, TaskStatus
from xingtu.worker import Activities, should_finalize_cancelled

ERROR = CollectorError("RESOURCE_UNAVAILABLE", "HEARTBEAT_TIMEOUT")


def test_heartbeat_timeout_finalizes_on_last_attempt():
    details = SimpleNamespace(timed_out=True)
    assert should_finalize_cancelled(details, None, attempt=4) is True


def test_heartbeat_timeout_defers_while_retry_budget_remains():
    details = SimpleNamespace(timed_out=True)
    assert should_finalize_cancelled(details, None, attempt=1) is False
    assert should_finalize_cancelled(details, None, attempt=3) is False


def test_worker_shutdown_is_not_terminal_even_on_last_attempt():
    details = SimpleNamespace(worker_shutdown=True, timed_out=False)
    assert should_finalize_cancelled(details, ERROR, attempt=4) is False


def test_user_cancel_is_left_to_cancel_path():
    details = SimpleNamespace(cancel_requested=True)
    assert should_finalize_cancelled(details, ERROR, attempt=4) is False


def test_paused_and_reset_are_not_terminal():
    for name in ("paused", "reset"):
        details = SimpleNamespace(**{name: True})
        assert should_finalize_cancelled(details, None, attempt=4) is False


def test_not_found_on_final_attempt_uses_durable_fences_to_finalize():
    details = SimpleNamespace(
        not_found=True,
        timed_out=False,
        worker_shutdown=False,
        cancel_requested=False,
        paused=False,
        reset=False,
    )
    assert should_finalize_cancelled(details, None, attempt=4) is True


def test_not_found_defers_while_retry_budget_remains():
    details = SimpleNamespace(not_found=True)
    assert should_finalize_cancelled(details, None, attempt=3) is False


def test_local_heartbeat_error_is_deferred_until_last_attempt():
    assert should_finalize_cancelled(None, ERROR, attempt=1) is False
    assert should_finalize_cancelled(None, ERROR, attempt=4) is True


def test_unknown_cancellation_without_heartbeat_error_is_deferred():
    assert should_finalize_cancelled(None, None, attempt=4) is False


def _activities(repo):
    return Activities(repo, SimpleNamespace(), Path("."))


def test_finalize_interrupted_prefers_the_engine_and_keeps_the_generation():
    calls = []

    class Engine:
        ctx = SimpleNamespace(lease_generation=7)

        def finish(self, *, force=False, failure_reason=None):
            calls.append((force, failure_reason))
            return TaskStatus.PARTIAL_COMPLETED

    class Repo:
        def finalize_interrupted(self, *args, **kwargs):  # pragma: no cover - must not be used
            raise AssertionError("repository fallback must not run when the engine can finalize")

    activities = _activities(Repo())
    task = SimpleNamespace(attempt_id="attempt")
    result = activities._finalize_interrupted(
        "root", task, "HEARTBEAT_TIMEOUT", Engine(), host=None
    )
    assert result == TaskStatus.PARTIAL_COMPLETED
    assert calls == [(True, "HEARTBEAT_TIMEOUT")]


def test_finalize_interrupted_retries_without_publishing_when_publish_fails():
    calls = []

    class Engine:
        ctx = SimpleNamespace(lease_generation=7)

        def finish(self, *, force=False, failure_reason=None):
            raise CollectorError("STORAGE_UNAVAILABLE", "PUBLISH_FAILED")

    class Repo:
        def finalize_interrupted(
            self, root, attempt, reason, *, publish=True, lease_generation=None
        ):
            calls.append((publish, lease_generation))
            if publish:
                raise CollectorError("INVALID_FORM", "state=COLLECTING")
            return TaskStatus.FAILED

    activities = _activities(Repo())
    task = SimpleNamespace(attempt_id="attempt")
    result = activities._finalize_interrupted("root", task, "HEARTBEAT_TIMEOUT", Engine(), None)
    assert result == TaskStatus.FAILED
    assert calls == [(True, 7), (False, 7)]


def test_finalize_interrupted_returns_the_durable_state_when_every_write_fails():
    class Engine:
        ctx = SimpleNamespace(lease_generation=7)

        def finish(self, *, force=False, failure_reason=None):
            raise CollectorError("STORAGE_UNAVAILABLE", "PUBLISH_FAILED")

    class Repo:
        def finalize_interrupted(self, *args, **kwargs):
            raise CollectorError("STORAGE_UNAVAILABLE", "DATABASE_DOWN")

        def get(self, root):
            return SimpleNamespace(state=TaskStatus.COLLECTING)

    activities = _activities(Repo())
    task = SimpleNamespace(attempt_id="attempt")
    assert (
        activities._finalize_interrupted("root", task, "HEARTBEAT_TIMEOUT", Engine(), None)
        == TaskStatus.COLLECTING
    )
