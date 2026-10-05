from pathlib import Path

import pytest
from pydantic import ValidationError
from xingtu.contracts import PlatformRegistry, SessionSpec
from xingtu.domain import ProfileRequirement
from xingtu.repository import Repository


def test_inventory_cannot_be_certified_without_fields_and_evidence():
    with pytest.raises(ValidationError):
        ProfileRequirement(version="v1", inventory_verified=True, modules={"fans": []})
    with pytest.raises(ValidationError):
        ProfileRequirement(version="v1", modules={"basic": ["nickname", "nickname"]})


def test_unknown_session_error_is_rejected():
    with pytest.raises(ValidationError, match="unknown session error"):
        SessionSpec(
            entry_url="https://synthetic.invalid/login",
            account={"selector": "#account"},
            protected_ready={"selector": "#ready"},
            identity={"selector": "#identity"},
            error_selectors={"MADE_UP_ERROR": {"selector": "#error"}},
        )


def test_live_registry_classifies_observed_challenge_and_permission_error():
    root = Path(__file__).resolve().parents[3]
    registry = PlatformRegistry.model_validate_json(
        (root / "contracts/douyin_xingtu.verified.json").read_text()
    )
    assert "PLATFORM_SECURITY_CHALLENGE" in registry.session.error_selectors
    search = next(item for item in registry.search.requests if item.key == "search")
    assert search.error_codes["10003"] == "PLATFORM_PERMISSION_DENIED"


def test_new_requirement_does_not_reinterpret_legacy_task(plan):
    from xingtu.domain import (
        Candidate,
        Checkpoint,
        CreatorRef,
        FieldObservation,
        ModuleObservation,
        TaskRecord,
    )

    creator = CreatorRef(
        platform_creator_id="1",
        verified_homepage="https://synthetic.invalid/creator/1",
        first_position=0,
    )
    observation = FieldObservation(
        field_key="nickname",
        value="synthetic",
        raw_value="synthetic",
        status="COLLECTED",
        source_kind="dom",
        source_contract="synthetic-v1",
        path_ref="#nickname",
        operation_id="op",
        session_version=1,
    )
    task = TaskRecord(
        root_task_id="root",
        task_id="task",
        attempt_id="attempt",
        plan=plan,
        execution_unit_id="unit",
        checkpoint=Checkpoint(
            conditions_digest=plan.digest(),
            contract_version="synthetic-v1",
            adapter_version="synthetic-v1",
            profile_module_keys=["basic"],
            candidates=[
                Candidate(
                    ref=creator,
                    valid=True,
                    modules={
                        "basic": ModuleObservation(
                            creator_ref=creator,
                            module_key="basic",
                            fields=[observation],
                            expected_fields=["nickname"],
                            operation_id="op",
                            contract_version="synthetic-v1",
                        )
                    },
                )
            ],
        ),
    )
    original = task.model_dump_json()
    assert Repository.profile_complete(task, "1")
    task.profile_requirement = ProfileRequirement(
        version="business-v1",
        inventory_verified=True,
        modules={"basic": ["nickname", "followers"], "fans": ["age"]},
        evidence_refs=["synthetic-evidence"],
    )
    coverage = Repository.profile_coverage(task, "1")
    assert coverage["registered_complete"] and not coverage["complete"]
    assert coverage["gaps"] == ["FIELD_NOT_ATTEMPTED:basic.followers", "MODULE_NOT_ATTEMPTED:fans"]
    assert Repository.profile_complete(TaskRecord.model_validate_json(original), "1")
    task.profile_requirement = ProfileRequirement(version="draft", modules={"basic": ["nickname"]})
    assert "REQUIREMENT_INVENTORY_UNVERIFIED" in Repository.profile_coverage(task, "1")["gaps"]
