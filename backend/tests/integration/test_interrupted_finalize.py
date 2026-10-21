from uuid import uuid4

import pytest
from xingtu.domain import (
    Candidate,
    CollectorError,
    CreatorRef,
    ExecutionContext,
    ReleaseDisposition,
    TaskStatus,
)
from xingtu.engine import Engine

from backend.tests.synthetic import SyntheticAdapter


def _ctx(root, task, generation, session):
    return ExecutionContext(
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


def test_finalize_interrupted_is_terminal_and_idempotent(repo, plan):
    root = repo.create(
        plan,
        "unit",
        uuid4().hex,
        "test",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        modules=[],
    )
    task = repo.get(root)
    assert task.state == TaskStatus.QUEUED
    assert repo.finalize_interrupted(root, task.attempt_id, "HEARTBEAT_TIMEOUT") == "FAILED"
    current = repo.get(root)
    assert current.state == TaskStatus.FAILED
    assert current.failure_reason == "HEARTBEAT_TIMEOUT"
    assert repo.finalize_interrupted(root, task.attempt_id, "HEARTBEAT_TIMEOUT") == "FAILED"
    assert repo.get(root).state == TaskStatus.FAILED


def test_forced_edit_requires_matching_generation(repo, plan):
    root = repo.create(
        plan,
        "unit",
        uuid4().hex,
        "test",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        modules=[],
    )
    task = repo.get(root)
    generation, session = repo.acquire("unit", task.attempt_id)
    ctx = _ctx(root, task, generation, session)

    # A cancellation may finalize after the lease row was released, but only for this generation.
    with repo.edit(root, ctx, require_lease=False) as (current, _):
        assert current.attempt_id == task.attempt_id
    repo.release(
        "unit",
        task.attempt_id,
        generation,
        stopped=True,
        disposition=ReleaseDisposition.SESSION_UNVERIFIED,
        reason="TEST_RELEASE",
    )

    new_generation, _ = repo.acquire("unit", "new-owner")
    assert new_generation == generation + 1
    with pytest.raises(CollectorError) as caught:
        with repo.edit(root, ctx, require_lease=False):
            pass
    assert caught.value.code == "LEASE_LOST"
    assert caught.value.reason == "GENERATION_FENCED"

    # The old generation remains fenced; do not write anything further.


def test_finalize_interrupted_publishes_checkpoint_snapshot_once(repo, plan):
    root = repo.create(
        plan,
        "unit",
        uuid4().hex,
        "test",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        modules=[],
        featured_types=["excellent_reach"],
    )
    task = repo.get(root)
    with repo.edit(root) as (current, _):
        current.valid_count = 1
        current.checkpoint.candidates = [
            Candidate(
                ref=CreatorRef(
                    platform_creator_id="synthetic-1",
                    verified_homepage="https://synthetic.invalid/creator/1",
                ),
                state="collecting",
                valid=True,
            )
        ]
    assert task.attempt_id == repo.get(root).attempt_id

    assert (
        repo.finalize_interrupted(root, task.attempt_id, "HEARTBEAT_TIMEOUT") == "PARTIAL_COMPLETED"
    )
    current = repo.get(root)
    assert current.state == TaskStatus.PARTIAL_COMPLETED
    assert current.failure_reason == "HEARTBEAT_TIMEOUT"
    assert current.valid_count == 1
    with repo.connect() as conn:
        snapshots = conn.execute(
            "SELECT count(*) AS n FROM creator_snapshots WHERE root_task_id=%s", (root,)
        ).fetchone()["n"]
        task_creators = conn.execute(
            "SELECT count(*) AS n FROM task_creators WHERE root_task_id=%s", (root,)
        ).fetchone()["n"]
    assert snapshots == 1
    assert task_creators == 1
    assert len(repo.results(root)) == 1

    # Idempotent: a duplicate cancellation must not publish another snapshot.
    assert (
        repo.finalize_interrupted(root, task.attempt_id, "HEARTBEAT_TIMEOUT") == "PARTIAL_COMPLETED"
    )
    with repo.connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM creator_snapshots WHERE root_task_id=%s", (root,)
            ).fetchone()["n"]
            == 1
        )


def test_engine_force_finish_publishes_without_active_lease(repo, plan):
    root = repo.create(
        plan,
        "unit",
        uuid4().hex,
        "test",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        modules=[],
    )
    task = repo.get(root)
    generation, session = repo.acquire("unit", task.attempt_id)
    ctx = _ctx(root, task, generation, session)
    with repo.edit(root) as (current, _):
        current.valid_count = 1
        current.checkpoint.candidates = [
            Candidate(
                ref=CreatorRef(
                    platform_creator_id="synthetic-force-1",
                    verified_homepage="https://synthetic.invalid/creator/force-1",
                ),
                state="collecting",
                valid=True,
            )
        ]
    repo.release(
        "unit",
        task.attempt_id,
        generation,
        stopped=True,
        disposition=ReleaseDisposition.SESSION_UNVERIFIED,
        reason="TEST_FORCE_FINISH",
    )
    engine = Engine(repo, SyntheticAdapter([]), ctx)
    assert engine.finish(force=True, failure_reason="HEARTBEAT_TIMEOUT") == "PARTIAL_COMPLETED"
    current = repo.get(root)
    assert current.state == TaskStatus.PARTIAL_COMPLETED
    assert current.failure_reason == "HEARTBEAT_TIMEOUT"
    with repo.connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM creator_snapshots WHERE root_task_id=%s", (root,)
            ).fetchone()["n"]
            == 1
        )
