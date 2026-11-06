"""RETRY-01 pure retry policy: scope, requeue rules and the retry summary counts."""

from typing import Literal

from xingtu.domain import (
    Candidate,
    Checkpoint,
    CreatorRef,
    FieldObservation,
    FieldStatus,
    ModuleObservation,
    TaskRecord,
    TaskStatus,
)
from xingtu.retry_policy import (
    RetryScope,
    challenge_blocks_retry,
    decide_retry_scope,
    incomplete_valid_count,
    is_retryable,
    remaining_to_target,
    requeue_for_retry,
    retryable_creator_count,
)

CandidateState = Literal["pending", "collecting", "done", "invalid", "failed"]


def reference(identity: str) -> CreatorRef:
    return CreatorRef(
        platform_creator_id=identity,
        verified_homepage=f"https://synthetic.invalid/creator/{identity}",
    )


def module(identity: str, *, complete: bool) -> ModuleObservation:
    field = (
        FieldObservation(
            field_key="value",
            value="synthetic",
            source_kind="response",
            source_contract="synthetic-v1",
            status=FieldStatus.COLLECTED,
            operation_id="op",
            session_version=1,
        )
        if complete
        else FieldObservation(
            field_key="value",
            status=FieldStatus.FAILED,
            failure_reason="SYNTHETIC_TIMEOUT",
            operation_id="op",
            session_version=1,
        )
    )
    return ModuleObservation(
        creator_ref=reference(identity),
        module_key="basic",
        fields=[field],
        expected_fields=["value"],
        operation_id="op",
        contract_version="synthetic-v1",
    )


def candidate(
    identity: str,
    *,
    state: CandidateState = "pending",
    valid: bool = False,
    complete: bool = True,
) -> Candidate:
    return Candidate(
        ref=reference(identity),
        state=state,
        valid=valid,
        modules={"basic": module(identity, complete=complete)},
    )


def task(
    plan,
    *,
    valid_count: int,
    profile_complete_count: int = 0,
    candidates: list[Candidate],
    target: int = 2,
) -> TaskRecord:
    scoped = plan.model_copy(update={"target_count": target})
    return TaskRecord(
        root_task_id="root",
        task_id="task",
        attempt_id="attempt",
        plan=scoped,
        execution_unit_id="unit",
        state=TaskStatus.PARTIAL_COMPLETED,
        checkpoint=Checkpoint(
            conditions_digest=scoped.digest(),
            contract_version="synthetic-v1",
            adapter_version="synthetic-v1",
            candidates=candidates,
        ),
        valid_count=valid_count,
        profile_complete_count=profile_complete_count,
    )


def test_scope_follows_the_creator_count(plan):
    assert (
        decide_retry_scope(task(plan, valid_count=1, candidates=[], target=2))
        is RetryScope.CONTINUE
    )
    assert (
        decide_retry_scope(task(plan, valid_count=2, candidates=[], target=2))
        is RetryScope.BACKFILL
    )
    assert (
        decide_retry_scope(task(plan, valid_count=3, candidates=[], target=2))
        is RetryScope.BACKFILL
    )


def test_retryable_covers_failed_and_incomplete_but_not_resolved_absences():
    assert is_retryable(candidate("1", state="failed", valid=False, complete=False))
    assert is_retryable(candidate("2", state="done", valid=True, complete=False))
    assert not is_retryable(candidate("3", state="done", valid=True, complete=True))
    assert not is_retryable(candidate("4", state="pending", valid=False, complete=True))
    assert not is_retryable(candidate("5", state="invalid", valid=False, complete=False))
    # A budget interruption can leave only the basic module in the checkpoint.  The missing
    # expected module is retryable even though every present module is complete.
    interrupted = candidate("6", state="done", valid=True, complete=True)
    assert not is_retryable(interrupted, ["basic"])
    assert is_retryable(interrupted, ["basic", "live"])


def test_continue_leaves_every_counted_creator_alone(plan):
    done_complete = candidate("1", state="done", valid=True, complete=True)
    done_incomplete = candidate("2", state="done", valid=True, complete=False)
    pending_incomplete = candidate("3", state="pending", valid=True, complete=False)
    collecting_incomplete = candidate("4", state="collecting", valid=True, complete=False)
    uncollected = candidate("5", state="pending", valid=False, complete=False)
    failed = candidate("6", state="failed", valid=False, complete=False)
    invalid = candidate("7", state="invalid", valid=False, complete=False)
    collecting_uncounted = candidate("8", state="collecting", valid=False, complete=False)
    record = task(
        plan,
        valid_count=4,
        candidates=[
            done_complete,
            done_incomplete,
            pending_incomplete,
            collecting_incomplete,
            uncollected,
            failed,
            invalid,
            collecting_uncounted,
        ],
        target=10,
    )

    requeue_for_retry(record, RetryScope.CONTINUE)

    assert done_complete.state == "done"
    assert done_incomplete.state == "done"
    # A counted creator is never re-opened by a quantity-only retry, even when its last attempt
    # was interrupted while collecting; the missing modules wait for a later backfill.
    assert pending_incomplete.state == "done"
    assert collecting_incomplete.state == "done"
    assert uncollected.state == "pending"
    assert failed.state == "pending"
    assert invalid.state == "invalid"
    # An uncounted creator that was mid-collection is still the candidate to finish.
    assert collecting_uncounted.state == "pending"


def test_backfill_only_requeues_counted_incomplete_creators(plan):
    complete = candidate("1", state="done", valid=True, complete=True)
    incomplete = candidate("2", state="done", valid=True, complete=False)
    uncollected = candidate("3", state="pending", valid=False, complete=False)
    failed_uncounted = candidate("4", state="failed", valid=False, complete=False)
    record = task(
        plan,
        valid_count=2,
        candidates=[complete, incomplete, uncollected, failed_uncounted],
        target=2,
    )

    requeue_for_retry(record, RetryScope.BACKFILL)

    assert complete.state == "done"
    assert incomplete.state == "pending"
    assert uncollected.state == "pending"
    # The target is met: an uncounted failure must not be re-queued, otherwise the failed-step
    # count would silently drop without anything being collected.
    assert failed_uncounted.state == "failed"


def test_security_challenge_terminal_state_never_offers_retry(plan):
    record = task(plan, valid_count=1, candidates=[candidate("1", valid=True, complete=False)])
    record.failure_reason = "SECURITY_CHALLENGE_TIMEOUT"
    assert challenge_blocks_retry(record)
    record.failure_reason = "PROFILE_SCOPE_INCOMPLETE"
    assert not challenge_blocks_retry(record)
    record.state = TaskStatus.FAILED
    record.failure_reason = "SECURITY_CHALLENGE_TIMEOUT"
    assert not challenge_blocks_retry(record)


def test_summary_counts_match_the_two_goals(plan):
    record = task(
        plan,
        valid_count=2,
        profile_complete_count=1,
        candidates=[
            candidate("1", state="done", valid=True, complete=True),
            candidate("2", state="done", valid=True, complete=False),
            candidate("3", state="pending", valid=False, complete=False),
        ],
        target=5,
    )
    assert remaining_to_target(record) == 3
    assert incomplete_valid_count(record) == 1
    assert retryable_creator_count(record) == 1
