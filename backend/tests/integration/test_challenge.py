from xingtu.challenge import ChallengeHandler
from xingtu.domain import Candidate, CreatorRef, ReleaseDisposition, TaskStatus
from xingtu.product_queries import ProductQueries


def test_challenge_limits_and_product_summary_survive_repository_reload(repo, plan):
    root = repo.create(
        plan,
        "unit",
        "challenge-checkpoint",
        "test",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        modules=["basic"],
    )
    with repo.edit(root) as (task, _):
        task.state = TaskStatus.COLLECTING
        task.checkpoint.candidates = [
            Candidate(
                ref=CreatorRef(
                    platform_creator_id="creator-1",
                    verified_homepage="https://synthetic.invalid/creator/creator-1",
                ),
                state="collecting",
            )
        ]
    attempt_id = repo.get(root).attempt_id
    handler = ChallengeHandler(repo)

    first = handler.register(root, attempt_id)
    assert first.allowed
    handler.recovered(root, attempt_id, first.creator_id)
    second = handler.register(root, attempt_id)

    assert not second.allowed
    stored = repo.get(root)
    assert stored.checkpoint.challenge_count == 2
    assert stored.checkpoint.challenge_recovery_count == 1
    assert stored.checkpoint.challenge_recoveries_by_creator == {"creator-1": 1}
    detail = ProductQueries(repo).get_task(root)
    assert detail.challenge is not None
    assert detail.challenge.state == "LIMIT_EXCEEDED"
    assert detail.challenge.detected_count == 2


def test_security_challenge_release_requires_verification(repo, plan):
    root = repo.create(
        plan,
        "unit",
        "challenge-release",
        "test",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        modules=["basic"],
    )
    task = repo.get(root)
    generation, _ = repo.acquire("unit", task.attempt_id, root_task_id=root)

    repo.release(
        "unit",
        task.attempt_id,
        generation,
        stopped=True,
        disposition=ReleaseDisposition.SECURITY_CHALLENGE,
        reason="REGISTERED_SECURITY_CHALLENGE",
    )

    unit = repo.unit("unit")
    assert unit["state"] == "NEEDS_VERIFICATION"
    assert unit["last_session_status"] == "SECURITY_CHALLENGE"
