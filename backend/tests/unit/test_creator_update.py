from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from xingtu.creator_update import _backoff, update_policy
from xingtu.domain import (
    Candidate,
    Checkpoint,
    CreatorRef,
    Filter,
    FilterPlan,
    NumberRange,
    TaskKind,
    TaskRecord,
    TaskStatus,
    uid,
)


def checkpoint(*ids: str, modules: list[str] | None = None) -> Checkpoint:
    return Checkpoint(
        conditions_digest="update:test",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        profile_module_keys=modules or ["basic"],
        profile_checkpoint_versions={key: 1 for key in (modules or ["basic"])},
        featured_collection_types=[],
        featured_checkpoint_versions={},
        candidates=[
            Candidate(
                ref=CreatorRef(
                    platform_creator_id=creator_id,
                    verified_homepage=f"https://synthetic.invalid/{creator_id}",
                    first_position=index,
                )
            )
            for index, creator_id in enumerate(ids)
        ],
    )


def update_record(*ids: str) -> TaskRecord:
    targets = [
        CreatorRef(
            platform_creator_id=creator_id,
            verified_homepage=f"https://synthetic.invalid/{creator_id}",
            first_position=index,
        )
        for index, creator_id in enumerate(ids)
    ]
    return TaskRecord(
        root_task_id=uid(),
        task_id=uid(),
        attempt_id=uid(),
        plan=None,
        task_kind=TaskKind.MANUAL_UPDATE,
        update_targets=targets,
        state=TaskStatus.QUEUED,
        execution_unit_id="",
        checkpoint=checkpoint(*ids),
    )


def plan() -> FilterPlan:
    return FilterPlan(
        capability_version="synthetic-v1",
        target_count=2,
        filters=[
            Filter(
                field="followers",
                operator="range",
                value=NumberRange(min=0, max=1000),
                source_fields=["followers"],
                unit="count",
            )
        ],
    )


@pytest.mark.parametrize(
    ("followers", "tier", "days"),
    [
        (None, "unknown", 15),
        (Decimal("0"), "lt_1w", 15),
        (Decimal("9999"), "lt_1w", 15),
        (Decimal("10000"), "1w_10w", 7),
        (Decimal("99999"), "1w_10w", 7),
        (Decimal("100000"), "10w_50w", 5),
        (Decimal("499999"), "10w_50w", 5),
        (Decimal("500000"), "50w_100w", 3),
        (Decimal("999999"), "50w_100w", 3),
        (Decimal("1000000"), "ge_100w", 1),
    ],
)
def test_update_policy_boundaries(followers, tier, days):
    assert update_policy(followers) == (tier, days)


def test_backoff_is_capped_by_the_normal_interval():
    assert _backoff(1, 15) == timedelta(hours=1)
    assert _backoff(2, 15) == timedelta(hours=6)
    assert _backoff(3, 15) == timedelta(hours=24)
    assert _backoff(4, 15) == timedelta(days=15)
    assert _backoff(4, 1) == timedelta(days=1)


def test_update_record_requires_targets_and_matching_candidates():
    record = update_record("1", "2")
    assert record.task_kind == TaskKind.MANUAL_UPDATE
    assert record.plan is None
    assert record.target_count == 2

    targets = record.update_targets
    with pytest.raises(ValueError, match="must match"):
        TaskRecord(
            **record.model_dump(exclude={"checkpoint", "update_targets"}),
            update_targets=targets,
            checkpoint=checkpoint("2", "1"),
        )


def test_update_record_rejects_duplicate_targets():
    record = update_record("1", "2")
    with pytest.raises(ValueError, match="unique"):
        TaskRecord(
            **record.model_dump(exclude={"checkpoint", "update_targets"}),
            update_targets=[
                CreatorRef(
                    platform_creator_id="1",
                    verified_homepage="https://synthetic.invalid/1",
                    first_position=0,
                ),
                CreatorRef(
                    platform_creator_id="1",
                    verified_homepage="https://synthetic.invalid/1",
                    first_position=1,
                ),
            ],
            checkpoint=checkpoint("1", "1"),
        )


def test_collection_record_still_requires_a_plan():
    with pytest.raises(ValueError, match="requires a filter plan"):
        TaskRecord(
            root_task_id=uid(),
            task_id=uid(),
            attempt_id=uid(),
            plan=None,
            checkpoint=Checkpoint(
                conditions_digest="x",
                adapter_version="synthetic-v1",
                contract_version="synthetic-v1",
            ),
            execution_unit_id="unit",
        )


def test_collection_target_count_comes_from_plan():
    record = TaskRecord(
        root_task_id=uid(),
        task_id=uid(),
        attempt_id=uid(),
        plan=plan(),
        checkpoint=Checkpoint(
            conditions_digest="x",
            adapter_version="synthetic-v1",
            contract_version="synthetic-v1",
        ),
        execution_unit_id="unit",
    )
    assert record.task_kind == TaskKind.COLLECTION
    assert record.target_count == 2
    assert record.capability_version == "synthetic-v1"
    assert record.model_dump(mode="json")["task_kind"] == "collection"


def test_update_record_backward_compatible_when_loading_old_payload():
    payload = {
        "root_task_id": uid(),
        "task_id": uid(),
        "attempt_id": uid(),
        "plan": plan().model_dump(mode="json"),
        "state": "QUEUED",
        "version": 0,
        "execution_unit_id": "unit",
        "checkpoint": Checkpoint(
            conditions_digest="x",
            adapter_version="synthetic-v1",
            contract_version="synthetic-v1",
        ).model_dump(mode="json"),
    }
    record = TaskRecord.model_validate(payload)
    assert record.task_kind == TaskKind.COLLECTION
    assert record.update_targets == []


def test_next_due_uses_fixed_elapsed_days():
    from xingtu.creator_update import _next_due

    base = datetime(2026, 10, 1, tzinfo=UTC)
    due, tier, days = _next_due(base, Decimal("500000"))
    assert (tier, days) == ("50w_100w", 3)
    assert due == base + timedelta(days=3)
