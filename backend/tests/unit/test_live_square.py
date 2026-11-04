from pathlib import Path

import pytest
from pydantic import ValidationError
from xingtu.adapter_factory import platform_scene_adapter_available
from xingtu.contracts import PlatformRegistry
from xingtu.domain import CreatorScene, Filter, FilterPlan, Sort
from xingtu.product_models import CapabilityDTO, RequirementForm


def registry(name: str) -> PlatformRegistry:
    return PlatformRegistry.model_validate_json(Path(f"contracts/{name}").read_text())


def plan(platform: str, scene: CreatorScene, target: int = 70) -> FilterPlan:
    schema = "filter_plan.v2" if platform == "douyin_xingtu" else "filter_plan.v3"
    return FilterPlan(
        schema_version=schema,
        platform=platform,
        creator_scene=scene,
        capability_version="placeholder",
        target_count=target,
        filters=[Filter(field="keyword", operator="eq", value="美食", source_fields=["keyword"])],
        sort=Sort(key="platform_default"),
    )


@pytest.mark.parametrize(
    ("name", "platform"),
    [
        ("douyin_xingtu.live.verified.json", "douyin_xingtu"),
        ("kuaishou_juxing.live.verified.json", "kuaishou_juxing"),
    ],
)
def test_live_contracts_are_enabled_and_keyword_only(name, platform):
    live = registry(name)
    live.require_enabled(live=True)
    assert live.sample_kind == "live"
    assert [item.key for item in live.modules] == ["basic", "live"]
    assert [field.field for field in live.capabilities.fields] == ["keyword"]
    candidate = plan(platform, CreatorScene.LIVE_SQUARE)
    candidate.capability_version = live.capabilities.version
    live.capabilities.validate_plan(candidate, live=True)


@pytest.mark.parametrize("platform", ["douyin_xingtu", "kuaishou_juxing"])
def test_live_requirement_defaults_and_70_limit(platform):
    schema = "requirement_form.v2" if platform == "douyin_xingtu" else "requirement_form.v3"
    requirement = RequirementForm(
        schema_version=schema,
        platform=platform,
        creator_scene=CreatorScene.LIVE_SQUARE,
        keyword="美食",
        target_count=70,
    )
    assert requirement.creator_scene == CreatorScene.LIVE_SQUARE
    assert requirement.target_count == 70
    with pytest.raises(ValidationError, match="70"):
        RequirementForm(
            schema_version=schema,
            platform=platform,
            creator_scene=CreatorScene.LIVE_SQUARE,
            keyword="美食",
            target_count=71,
        )
    with pytest.raises(ValidationError, match="keyword"):
        RequirementForm(
            schema_version=schema,
            platform=platform,
            creator_scene=CreatorScene.LIVE_SQUARE,
            keyword=None,
            target_count=20,
        )


def test_video_target_limit_is_not_changed_by_live_70_limit():
    # The established Xingtu video contract still accepts its full range (up to 200).
    assert RequirementForm(keyword="宠物", target_count=200).target_count == 200
    assert (
        RequirementForm(keyword="宠物", target_count=1).creator_scene == CreatorScene.VIDEO_SQUARE
    )


def test_live_capability_dto_defaults_to_20_and_caps_at_70():
    live = registry("douyin_xingtu.live.verified.json")
    dto = CapabilityDTO.from_capabilities(
        live.capabilities, creator_scene=CreatorScene.LIVE_SQUARE, target_count_max=70
    )
    assert dto.creator_scene == CreatorScene.LIVE_SQUARE
    assert dto.target_count_default == 20
    assert dto.target_count_max == 70
    assert [field.field for field in dto.fields] == ["keyword"]


def test_scene_is_not_part_of_the_filter_plan_digest():
    first = plan("douyin_xingtu", CreatorScene.VIDEO_SQUARE)
    second = plan("douyin_xingtu", CreatorScene.LIVE_SQUARE)
    assert first.digest() == second.digest()


@pytest.mark.parametrize("platform", ["douyin_xingtu", "kuaishou_juxing"])
def test_both_scenes_have_browser_adapters(platform):
    assert platform_scene_adapter_available(platform, CreatorScene.VIDEO_SQUARE)
    assert platform_scene_adapter_available(platform, CreatorScene.LIVE_SQUARE)
