"""Fenced, small progress writes used by the hybrid Collection Worker.

These tests pin two properties that matter on a remote PostgreSQL link:

* a progress charge must not rewrite or lose any collected observation;
* the small candidate queries must reproduce ``ModuleObservation.complete`` exactly.
"""

from __future__ import annotations

import pytest
from xingtu.domain import (
    Candidate,
    CollectorError,
    CreatorRef,
    FieldObservation,
    FieldStatus,
    ModuleObservation,
    ReleaseDisposition,
    uid,
)


def _ref(identity: str) -> CreatorRef:
    return CreatorRef(
        platform_creator_id=identity,
        verified_homepage=f"https://synthetic.invalid/creator/{identity}",
    )


def _module(
    ref: CreatorRef,
    key: str,
    *,
    expected: list[str],
    collected: list[str],
    gaps: list[str] | None = None,
) -> ModuleObservation:
    operation = uid()
    return ModuleObservation(
        creator_ref=ref,
        module_key=key,
        fields=[
            FieldObservation(
                field_key=field_key,
                value=f"value-{field_key}",
                raw_value=f"value-{field_key}",
                status=FieldStatus.COLLECTED,
                source_kind="dom",
                source_contract="synthetic-v1",
                operation_id=operation,
                session_version=1,
            )
            for field_key in collected
        ],
        expected_fields=expected,
        coverage_gaps=gaps or [],
        operation_id=operation,
        contract_version="synthetic-v1",
    )


def _seed_candidates(repo, root: str) -> None:
    ref = _ref("creator-1")
    with repo.edit(root) as (task, _):
        task.checkpoint.candidates.append(
            Candidate(
                ref=ref,
                valid=True,
                modules={
                    "basic": _module(
                        ref,
                        "basic",
                        expected=["platform_creator_id", "nickname"],
                        collected=["platform_creator_id", "nickname"],
                    ),
                    "commercial": _module(
                        ref,
                        "commercial",
                        expected=["value"],
                        collected=[],
                        gaps=["value unreadable"],
                    ),
                },
            )
        )
        task.checkpoint.candidates.append(Candidate(ref=_ref("creator-2")))


async def test_record_progress_preserves_observations_and_returns_active_seconds(repo, started):
    _seed_candidates(repo, started.root_task_id)
    before = repo.get(started.root_task_id)
    active = repo.record_progress(
        started.root_task_id,
        started,
        active_seconds=1.25,
        counters={"observed_requests": 3, "cover_request_count": 2},
        module_seconds={"basic": 0.5},
    )
    after = repo.get(started.root_task_id)
    assert active == pytest.approx(before.checkpoint.active_seconds + 1.25)
    assert after.checkpoint.active_seconds == pytest.approx(active)
    assert after.checkpoint.observed_requests == before.checkpoint.observed_requests + 3
    assert after.checkpoint.cover_request_count == before.checkpoint.cover_request_count + 2
    assert after.checkpoint.module_seconds["basic"] == pytest.approx(
        before.checkpoint.module_seconds.get("basic", 0.0) + 0.5
    )
    # The collected data is byte-for-byte the same object model, not a partial rewrite.
    assert after.checkpoint.candidates == before.checkpoint.candidates
    assert after.version == before.version + 1
    assert after.checkpoint.revision == before.checkpoint.revision + 1


async def test_record_progress_without_delta_is_a_noop(repo, started):
    before = repo.get(started.root_task_id)
    assert repo.record_progress(started.root_task_id, started) is None
    after = repo.get(started.root_task_id)
    assert after.version == before.version
    assert after.checkpoint.revision == before.checkpoint.revision


async def test_record_progress_rejects_a_stale_generation(repo, started):
    stale = started.model_copy(update={"lease_generation": started.lease_generation + 1})
    with pytest.raises(CollectorError) as caught:
        repo.record_progress(started.root_task_id, stale, active_seconds=1)
    assert caught.value.code == "LEASE_LOST"


async def test_record_progress_rejects_a_stale_attempt(repo, started):
    # Keep the lease owner intact and move only the task attempt, otherwise the earlier lease
    # fence would (correctly) reject it as LEASE_LOST before the task fence is evaluated.
    with repo.edit(started.root_task_id) as (task, _):
        task.attempt_id = uid()
    with pytest.raises(CollectorError) as caught:
        repo.record_progress(started.root_task_id, started, active_seconds=1)
    assert caught.value.code == "TASK_CANCELLED"
    assert caught.value.reason == "STALE_ATTEMPT_OR_STATE"


async def test_record_progress_rejects_a_version_mismatch(repo, started):
    stale = started.model_copy(update={"contract_version": "synthetic-v2"})
    with pytest.raises(CollectorError) as caught:
        repo.record_progress(started.root_task_id, stale, active_seconds=1)
    assert caught.value.code == "PLATFORM_PAGE_CHANGED"
    assert caught.value.reason == "VERSION_MISMATCH"


async def test_candidate_queries_match_the_domain_completeness_rule(repo, started):
    _seed_candidates(repo, started.root_task_id)
    assert repo.candidate_module_complete(started.root_task_id, "creator-1") == {
        "basic": True,
        "commercial": False,
    }
    assert repo.candidate_module_complete(started.root_task_id, "creator-2") == {}
    assert repo.candidate_valid(started.root_task_id, "creator-1") is True
    assert repo.candidate_valid(started.root_task_id, "creator-2") is False
    with pytest.raises(CollectorError) as caught:
        repo.candidate_valid(started.root_task_id, "missing")
    assert caught.value.code == "INVALID_FORM"
    assert caught.value.reason == "CANDIDATE_NOT_FOUND"


async def test_heartbeat_rejects_a_released_lease(repo, started):
    repo.release(
        "unit",
        started.attempt_id,
        started.lease_generation,
        stopped=True,
        disposition=ReleaseDisposition.VERIFIED_READY,
    )
    with pytest.raises(CollectorError) as caught:
        repo.heartbeat(
            "unit",
            started.attempt_id,
            started.lease_generation,
            lock_timeout_seconds=1.0,
        )
    assert caught.value.code == "LEASE_LOST"
