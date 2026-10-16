from pathlib import Path

from xingtu.contracts import PlatformRegistry
from xingtu.domain import Checkpoint, FilterPlan, TaskRecord, TaskStatus
from xingtu.worker import adopt_compatible_legacy_checkpoint


def current_registry() -> PlatformRegistry:
    return PlatformRegistry.model_validate_json(
        Path("contracts/douyin_xingtu.verified.json").read_text()
    )


def legacy_task(*, state: TaskStatus = TaskStatus.QUEUED) -> TaskRecord:
    plan = FilterPlan.model_validate(
        {
            "schema_version": "filter_plan.v1",
            "capability_version": "xingtu-ad-creator-square-v1",
            "target_count": 2,
            "filters": [
                {
                    "field": "keyword",
                    "operator": "eq",
                    "value": "汽车",
                    "source_fields": ["keyword"],
                }
            ],
        }
    )
    return TaskRecord(
        root_task_id="root",
        task_id="task",
        attempt_id="attempt",
        plan=plan,
        state=state,
        execution_unit_id="unit-local-mac-02",
        checkpoint=Checkpoint(
            conditions_digest=plan.digest(),
            adapter_version="xingtu-playwright-v8",
            contract_version="xingtu-verified-2026-10-08-v9",
        ),
    )


def test_pristine_queued_keyword_v1_checkpoint_adopts_current_runtime_versions():
    registry = current_registry()
    task = legacy_task()

    assert adopt_compatible_legacy_checkpoint(task, registry)
    assert task.plan.capability_version == "xingtu-ad-creator-square-v1"
    assert task.checkpoint.adapter_version == registry.adapter_version
    assert task.checkpoint.contract_version == registry.contract_version
    assert task.checkpoint.profile_module_keys == [item.key for item in registry.modules]
    assert task.checkpoint.featured_collection_types == [
        item.key.value for item in registry.featured
    ]


def test_legacy_checkpoint_with_browser_progress_remains_fail_closed():
    task = legacy_task()
    task.checkpoint.observed_requests = 1

    assert not adopt_compatible_legacy_checkpoint(task, current_registry())
    assert task.checkpoint.adapter_version == "xingtu-playwright-v8"


def test_nonqueued_legacy_checkpoint_is_not_adopted():
    task = legacy_task(state=TaskStatus.RETRY_WAIT)

    assert not adopt_compatible_legacy_checkpoint(task, current_registry())


def test_v2_plan_is_not_treated_as_checkpoint_migration():
    task = legacy_task()
    task.plan = task.plan.model_copy(
        update={
            "schema_version": "filter_plan.v2",
            "capability_version": current_registry().capabilities.version,
        }
    )

    assert not adopt_compatible_legacy_checkpoint(task, current_registry())
