"""Retry intent, derived from one task's own counts.

The product has two different user goals behind one entry point:

* **continue** — the task has not reached its creator target yet, so the retry only finishes
  the count and must not revisit creators that already count as valid;
* **backfill** — the target is reached, so the retry only completes the already-counted
  creators and must not search or add creators.

Deriving the scope from ``valid_count``/``target_count`` keeps both command paths (product API
and internal CLI), the engine and the read model in agreement without storing a new field.  The
module is deliberately dependency-free apart from the domain types, so it is unit-testable
without PostgreSQL.
"""

from __future__ import annotations

from enum import StrEnum

from .domain import Candidate, TaskRecord, TaskStatus


class RetryScope(StrEnum):
    CONTINUE = "continue"
    BACKFILL = "backfill"


def is_retryable(candidate: Candidate) -> bool:
    """A candidate is retryable when a step is failed or an attempted step is incomplete."""
    if candidate.state == "failed":
        return True
    if not candidate.valid:
        return False
    return any(not module.complete for module in candidate.modules.values()) or any(
        not collection.complete for collection in candidate.collections.values()
    )


def challenge_blocks_retry(task: TaskRecord) -> bool:
    """A security-challenge terminal reason is never retried automatically or by one click."""
    return task.state == TaskStatus.PARTIAL_COMPLETED and (task.failure_reason or "").startswith(
        "SECURITY_CHALLENGE_"
    )


def decide_retry_scope(task: TaskRecord) -> RetryScope:
    """Continue the count first; only complete existing creators once the target is reached."""
    return RetryScope.CONTINUE if task.valid_count < task.target_count else RetryScope.BACKFILL


def remaining_to_target(task: TaskRecord) -> int:
    return max(0, task.target_count - task.valid_count)


def incomplete_valid_count(task: TaskRecord) -> int:
    """Already-counted creators whose profile is not complete (the backfill population)."""
    return max(0, task.valid_count - task.profile_complete_count)


def retryable_creator_count(task: TaskRecord) -> int:
    return sum(1 for candidate in task.checkpoint.candidates if is_retryable(candidate))


def requeue_for_retry(task: TaskRecord, scope: RetryScope) -> None:
    """Repair the retry queue for one segment without touching what the user asked to keep.

    ``continue`` only revives candidates that are not counted yet.  A counted creator that is
    still ``pending`` is the leftover of an earlier retry (the defect this policy replaces), so it
    is settled to ``done`` and left for a later backfill instead of opening its homepage again.
    A counted creator that is ``collecting`` was interrupted mid-flight; the engine finishes it,
    which is the existing resume behaviour.

    ``backfill`` only revives counted creators with an incomplete step.  Uncounted candidates are
    left exactly as they are: the target is already met, so re-queuing them would neither collect
    anything nor keep the failed-step count truthful.
    """

    for candidate in task.checkpoint.candidates:
        if scope is RetryScope.CONTINUE:
            if candidate.valid:
                if candidate.state == "pending":
                    candidate.state = "done"
                continue
            if candidate.state in {"pending", "collecting", "failed"}:
                candidate.state = "pending"
            continue
        if candidate.valid and is_retryable(candidate):
            candidate.state = "pending"
