from xingtu.domain import (
    ChallengeState,
    ChallengeType,
    Checkpoint,
    TaskRecord,
    TaskStatus,
    utcnow,
)
from xingtu.product_queries import ProductQueries, allowed_actions


def challenged_task(plan):
    checkpoint = Checkpoint(
        conditions_digest=plan.digest(),
        contract_version="v1",
        adapter_version="v1",
        challenge_count=2,
        challenge_recovery_count=1,
        challenge_first_detected_at=utcnow(),
        challenge_last_detected_at=utcnow(),
        challenge_wait_started_at=utcnow(),
        challenge_current_creator="creator-1",
        challenge_type=ChallengeType.SLIDER_OR_INTERACTIVE,
        challenge_state=ChallengeState.HANDLING,
    )
    return TaskRecord(
        root_task_id="root",
        task_id="task",
        attempt_id="attempt",
        plan=plan,
        state=TaskStatus.WAITING_FOR_VERIFICATION,
        execution_unit_id="unit",
        checkpoint=checkpoint,
        valid_count=1,
    )


def test_product_challenge_summary_exposes_actionable_waiting_state(plan):
    task = challenged_task(plan)
    summary = ProductQueries._challenge_summary(task)
    assert summary is not None
    assert summary.state == "HANDLING"
    assert summary.detected_count == 2
    assert summary.recovery_count == 1
    assert summary.current_creator_id == "creator-1"
    assert summary.requires_user_action and summary.monitoring
    assert summary.delivered_result == "已保留 1 位达人及其已持久数据"


def test_security_partial_completion_does_not_offer_same_task_retry(plan):
    task = challenged_task(plan)
    task.state = TaskStatus.PARTIAL_COMPLETED
    task.failure_reason = "SECURITY_CHALLENGE_LIMIT"
    assert allowed_actions(task.state, task) == []
