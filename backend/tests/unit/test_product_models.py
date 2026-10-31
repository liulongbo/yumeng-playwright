from pathlib import Path

import pytest
from pydantic import ValidationError
from xingtu.contracts import PlatformRegistry
from xingtu.domain import (
    Capabilities,
    CollectorError,
    CombinationPolicy,
    FilterCapability,
)
from xingtu.intake import build_expected_plan
from xingtu.product_models import CapabilityDTO, RequirementForm
from xingtu.product_queries import ProductQueries


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
    assert [field.field for field in dto.fields] == [
        "keyword",
        "gender",
        "region",
        "education",
        "yellow_v",
        "connection_users",
        "followers",
        "viewer_profile",
        "fan_profile",
    ]
    assert dto.fixed_sort_key == "score"
    assert dto.combinations == [["keyword"]]
    assert dto.combination_policy
    region = next(field for field in dto.fields if field.field == "region")
    assert len(region.region_tree) == 34
    assert sum(len(item["children"]) for item in region.region_tree) == 452


def test_expected_plan_is_exact_and_uses_fixed_platform_sort():
    plan = build_expected_plan(
        RequirementForm(keyword="  宠物  ", target_count=20), live_capabilities()
    )
    assert plan.target_count == 20
    assert plan.schema_version == "filter_plan.v2"
    assert plan.sort.key == "score"
    assert plan.filters[0].field == "keyword"
    assert plan.filters[0].value == "宠物"
    assert plan.filters[0].source_fields == ["keyword"]


def test_juxing_p0_form_maps_platform_specific_filters_without_touching_xingtu():
    capabilities = Capabilities(
        version="juxing-synthetic-v1",
        status="VERIFIED",
        sample_kind="live",
        evidence_refs=["synthetic:test-only"],
        fields=[
            FilterCapability(field="keyword", operators=["eq"], keyword_mode="content"),
            FilterCapability(field="content_type", operators=["in"], enum=["母婴亲子"]),
            FilterCapability(field="followers", operators=["range"], unit="count"),
            *[
                FilterCapability(
                    field=field,
                    operators=["range"],
                    unit="yuan",
                    currencies=["CNY"],
                    cooperation_forms=[form],
                )
                for field, form in (
                    ("video_quote_1_20", "short_video_1_20s"),
                    ("video_quote_21_60", "short_video_21_60s"),
                    ("video_quote_60_plus", "short_video_60s_plus"),
                )
            ],
        ],
        sorts=["platform_default"],
        combination_policy=CombinationPolicy(
            fields=[
                "keyword",
                "content_type",
                "followers",
                "video_quote_1_20",
                "video_quote_21_60",
                "video_quote_60_plus",
            ]
        ),
    )
    form = RequirementForm(
        schema_version="requirement_form.v3",
        platform="kuaishou_juxing",
        keyword=" 母婴 ",
        content_types=["母婴亲子"],
        followers={"min": 100000, "max": 1000000, "unit": "count"},
        juxing_video_quotes={
            "seconds_1_20": {"max": 5000, "unit": "yuan"},
            "seconds_21_60": {"min": 3000, "max": 8000, "unit": "yuan"},
        },
        target_count=10,
    )
    plan = build_expected_plan(form, capabilities)
    assert plan.platform == "kuaishou_juxing"
    assert plan.schema_version == "filter_plan.v3"
    assert plan.target_count == 10
    assert [item.field for item in plan.filters] == [
        "keyword",
        "content_type",
        "followers",
        "video_quote_1_20",
        "video_quote_21_60",
    ]
    quotes = {item.field: item for item in plan.filters if item.field.startswith("video_quote")}
    assert quotes["video_quote_1_20"].cooperation_form == "short_video_1_20s"
    assert quotes["video_quote_21_60"].currency == "CNY"


def test_platform_specific_forms_reject_cross_platform_fields():
    with pytest.raises(ValidationError, match="not valid"):
        RequirementForm(keyword="宠物", content_types=["母婴亲子"])
    with pytest.raises(ValidationError, match="requires requirement_form.v3"):
        RequirementForm(platform="kuaishou_juxing", keyword="母婴")
    with pytest.raises(ValidationError, match="unsupported kuaishou"):
        RequirementForm(
            schema_version="requirement_form.v3",
            platform="kuaishou_juxing",
            keyword="母婴",
            creator_gender="female",
        )


def test_unverified_form_field_never_becomes_an_executable_plan():
    with pytest.raises(CollectorError, match="UNSUPPORTED_FILTER"):
        build_expected_plan(
            RequirementForm(
                schema_version="requirement_form.v1",
                keyword=None,
                creator_types=["剧情"],
            ),
            live_capabilities(),
        )


def test_v2_rejects_invalid_ranges_regions_and_mutually_exclusive_profiles():
    RequirementForm(connection_users={"connected": {"min": 99999}})
    with pytest.raises(ValidationError, match="99999w"):
        RequirementForm(connection_users={"connected": {"min": 100000}})
    with pytest.raises(ValidationError, match="whole ten-thousand"):
        RequirementForm(connection_users={"connected": {"min": 0.5}})
    RequirementForm(followers={"min": 12.5, "max": 25.5})
    with pytest.raises(ValidationError, match="5000w"):
        RequirementForm(followers={"min": 5001})
    with pytest.raises(ValidationError, match="province and its child"):
        RequirementForm(
            creator_regions=[
                {"province_code": "110000"},
                {"province_code": "110000", "city": "朝阳区"},
            ]
        )
    profile = {"age": ["age_18_23"]}
    with pytest.raises(ValidationError, match="mutually exclusive"):
        RequirementForm(viewer_profile=profile, fan_profile=profile)


def test_v2_full_form_maps_every_leaf_without_guessing():
    form = RequirementForm(
        keyword=" 汽车 ",
        creator_gender="female",
        creator_regions=[{"province_code": "110000", "city": "朝阳区"}],
        creator_education="master",
        yellow_v_certification="technology",
        connection_users={
            "connected": {"min": 1, "max": 2},
            "aware": {"min": 3},
        },
        followers={"min": 100, "max": 300},
        viewer_profile={
            "age": ["age_18_23"],
            "gender": "female_60",
            "device_brand": ["apple"],
            "city_level": ["tier_1"],
            "crowd": ["gen_z"],
        },
        target_count=2,
    )
    plan = build_expected_plan(form, live_capabilities())
    assert plan.schema_version == "filter_plan.v2"
    assert [item.field for item in plan.filters] == [
        "keyword",
        "followers",
        "gender",
        "region",
        "education",
        "yellow_v",
        "connection_users",
        "viewer_profile",
    ]
    values = {item.field: item for item in plan.filters}
    assert values["followers"].unit == "ten_thousand_count"
    assert values["region"].source_fields == [
        "creator_regions.0.province_code",
        "creator_regions.0.city",
    ]
    assert values["connection_users"].source_fields == [
        "connection_users.connected.min",
        "connection_users.connected.max",
        "connection_users.aware.min",
    ]
    assert values["viewer_profile"].source_fields == [
        "viewer_profile.age.0",
        "viewer_profile.gender",
        "viewer_profile.device_brand.0",
        "viewer_profile.city_level.0",
        "viewer_profile.crowd.0",
    ]


def test_historical_v1_keyword_plan_remains_executable_under_v2_registry():
    plan = build_expected_plan(
        RequirementForm(schema_version="requirement_form.v1", keyword="宠物"),
        live_capabilities(),
        capability_version="xingtu-ad-creator-square-v1",
    )
    assert plan.schema_version == "filter_plan.v1"
    assert plan.capability_version == "xingtu-ad-creator-square-v1"
    live_capabilities().validate_plan(plan, live=True)


def test_capability_rejects_unknown_region_child():
    form = RequirementForm(creator_regions=[{"province_code": "110000", "city": "不存在区"}])
    with pytest.raises(CollectorError, match="INVALID_FORM"):
        build_expected_plan(form, live_capabilities())


def test_creator_library_gender_reads_the_platform_code_from_the_projection():
    """CD-03 需求 4.6: the API hands over `basic.gender` unchanged, never a mapped label.

    The code → 女/男/未知 mapping is presentation-only (frontend/src/profile/views.ts), so the
    backend contract stays a platform code and an absent answer stays `None`, never a guess.
    """
    observed = {"status": "COLLECTED", "value": "2"}
    assert ProductQueries._gender_value({"basic.gender": observed}) == "2"
    assert ProductQueries._gender_value({"basic.gender": {**observed, "value": " 1 "}}) == "1"
    assert ProductQueries._gender_value({"basic.gender": {**observed, "status": "NO_DATA"}}) is None
    assert ProductQueries._gender_value({"basic.gender": {**observed, "value": ""}}) is None
    assert ProductQueries._gender_value({"basic.gender": {**observed, "value": 2}}) is None
    assert ProductQueries._gender_value({}) is None
