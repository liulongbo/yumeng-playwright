from pathlib import Path

import pytest
from pydantic import ValidationError
from xingtu.contracts import PlatformRegistry
from xingtu.domain import CollectorError
from xingtu.intake import build_expected_plan
from xingtu.product_models import CapabilityDTO, RequirementForm


def live_capabilities():
    return PlatformRegistry.model_validate_json(
        Path("contracts/douyin_xingtu.verified.json").read_text()
    ).capabilities


@pytest.mark.parametrize("target", [1, 20, 200])
def test_requirement_target_boundaries(target):
    assert RequirementForm(keyword="宠物", target_count=target).target_count == target


@pytest.mark.parametrize("target", [0, 201, 1.5, True, "20"])
def test_requirement_rejects_invalid_targets(target):
    with pytest.raises(ValidationError):
        RequirementForm.model_validate({"keyword": "宠物", "target_count": target})


def test_requirement_needs_business_filter_and_rejects_reversed_ranges():
    with pytest.raises(ValidationError, match="business filter"):
        RequirementForm()
    with pytest.raises(ValidationError, match="reversed"):
        RequirementForm(
            keyword=None,
            followers={"min": 200, "max": 100, "unit": "count"},
        )


def test_capability_dto_only_exposes_live_verified_keyword():
    dto = CapabilityDTO.from_capabilities(live_capabilities())
    assert [field.field for field in dto.fields] == ["keyword"]
    assert dto.fixed_sort_key == "score"
    assert dto.combinations == [["keyword"]]


def test_expected_plan_is_exact_and_uses_fixed_platform_sort():
    plan = build_expected_plan(
        RequirementForm(keyword="  宠物  ", target_count=20), live_capabilities()
    )
    assert plan.target_count == 20
    assert plan.sort.key == "score"
    assert plan.filters[0].field == "keyword"
    assert plan.filters[0].value == "宠物"
    assert plan.filters[0].source_fields == ["keyword"]


def test_unverified_form_field_never_becomes_an_executable_plan():
    with pytest.raises(CollectorError, match="UNSUPPORTED_FILTER"):
        build_expected_plan(
            RequirementForm(keyword=None, creator_types=["剧情"]), live_capabilities()
        )
