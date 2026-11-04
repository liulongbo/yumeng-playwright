from pathlib import Path

import pytest
from pydantic import ValidationError
from xingtu.contracts import AttributeFilterEntry, PlatformRegistry
from xingtu.domain import CollectorError, CreatorScene, Filter, FilterPlan, NumberRange, Sort
from xingtu.intake import build_expected_plan
from xingtu.live_filters import (
    expected_xingtu_live_request,
    juxing_live_filter_body,
    validate_xingtu_live_request,
)
from xingtu.product_models import RequirementForm


def registry(name: str) -> PlatformRegistry:
    return PlatformRegistry.model_validate_json(Path(f"contracts/{name}").read_text())


XINGTU = registry("douyin_xingtu.live.verified.json")
JUXING = registry("kuaishou_juxing.live.verified.json")


def xingtu_form(**kwargs) -> RequirementForm:
    values = {
        "schema_version": "requirement_form.v2",
        "platform": "douyin_xingtu",
        "creator_scene": CreatorScene.LIVE_SQUARE,
        "keyword": None,
        "target_count": 5,
    }
    values.update(kwargs)
    return RequirementForm(**values)


def juxing_form(**kwargs) -> RequirementForm:
    values = {
        "schema_version": "requirement_form.v3",
        "platform": "kuaishou_juxing",
        "creator_scene": CreatorScene.LIVE_SQUARE,
        "keyword": None,
        "target_count": 5,
    }
    values.update(kwargs)
    return RequirementForm(**values)


def test_live_filter_only_is_allowed_and_empty_is_rejected():
    form = xingtu_form(live_filters=[{"field": "live_content_type", "values": ["fashion"]}])
    assert form.live_filters[0].field == "live_content_type"
    with pytest.raises(ValidationError, match="keyword, creator id or filter"):
        xingtu_form()
    with pytest.raises(ValidationError, match="only valid for live_square"):
        RequirementForm(
            schema_version="requirement_form.v2",
            platform="douyin_xingtu",
            keyword="宠物",
            live_filters=[{"field": "live_content_type", "values": ["fashion"]}],
        )
    with pytest.raises(ValidationError, match="70"):
        xingtu_form(
            target_count=71,
            live_filters=[{"field": "live_content_type", "values": ["fashion"]}],
        )


def test_live_keyword_and_filter_can_be_combined():
    form = xingtu_form(
        keyword="美妆",
        live_filters=[
            {"field": "live_content_type", "values": ["fashion"]},
            {"field": "live_gender", "values": ["female"]},
        ],
    )
    plan = build_expected_plan(form, XINGTU.capabilities)
    assert [item.field for item in plan.filters] == ["keyword", "live_content_type", "live_gender"]


def test_xingtu_content_type_maps_to_verified_level_one_attribute():
    form = xingtu_form(live_filters=[{"field": "live_content_type", "values": ["fashion"]}])
    plan = build_expected_plan(form, XINGTU.capabilities)
    expectation = expected_xingtu_live_request(plan, XINGTU.capabilities)
    assert expectation.attribute_filters == (
        AttributeFilterEntry(
            field_name="live_tag_content_v2_level_one", field_value="[10719]", rel_id=None
        ),
    )
    assert expectation.keyword is None


def test_xingtu_gender_cert_region_and_followers_map_exactly():
    form = xingtu_form(
        live_filters=[
            {"field": "live_gender", "values": ["female"]},
            {"field": "live_certification", "values": ["business"]},
            {"field": "live_region", "regions": [{"province_code": "440000"}]},
            {
                "field": "live_followers",
                "range": {"min": 100, "max": 300, "unit": "ten_thousand_count"},
            },
        ]
    )
    plan = build_expected_plan(form, XINGTU.capabilities)
    entries = expected_xingtu_live_request(plan, XINGTU.capabilities).attribute_filters
    assert sorted((entry.field_name, entry.field_value) for entry in entries) == [
        ("cert_types", "3"),
        ("follower__ge", "1000000"),
        ("follower__le", "3000000"),
        ("gender", "2"),
        ("province", '["广东省"]'),
    ]


def test_xingtu_performance_metrics_use_distinct_fields():
    form = xingtu_form(
        live_filters=[
            {"field": "live_recent_sessions", "range": {"min": 7, "max": 25, "unit": "count"}},
            {"field": "live_avg_viewers", "range": {"min": 100, "max": 500, "unit": "count"}},
            {"field": "live_avg_view_visits", "range": {"min": 100, "max": 500, "unit": "count"}},
            {"field": "live_acu", "range": {"min": 5, "max": 10, "unit": "count"}},
            {"field": "live_pcu", "range": {"min": 21, "max": 50, "unit": "count"}},
        ]
    )
    plan = build_expected_plan(form, XINGTU.capabilities)
    entries = expected_xingtu_live_request(plan, XINGTU.capabilities).attribute_filters
    fields = {entry.field_name for entry in entries}
    assert fields == {
        "live_room_cnt_30d__ge",
        "live_room_cnt_30d__le",
        "live_sn_watch_ucnt_avg_30d__ge",
        "live_sn_watch_ucnt_avg_30d__le",
        "live_sn_watch_cnt_avg_30d__ge",
        "live_sn_watch_cnt_avg_30d__le",
        "acu__ge",
        "acu__le",
        "live_pcu_30d__ge",
        "live_pcu_30d__le",
    }


def test_xingtu_profile_request_validation_accepts_exact_profile_fields():
    form = xingtu_form(
        live_filters=[
            {
                "field": "live_viewer_profile",
                "profile": [
                    {"key": "age", "values": ["age_18_23"]},
                    {"key": "gender", "values": ["male_50"]},
                ],
            }
        ]
    )
    plan = build_expected_plan(form, XINGTU.capabilities)
    expectation = expected_xingtu_live_request(plan, XINGTU.capabilities)
    payload = {
        "attribute_filter": [
            {"field": {"field_name": "watcher_age_rate_most"}, "field_value": "[21]"},
            {"field": {"field_name": "live_watcher_gender_male_rate__ge"}, "field_value": "0.5"},
        ]
    }
    validate_xingtu_live_request(payload, expectation)
    with pytest.raises(CollectorError, match="LIVE_PROFILE_MISSING"):
        validate_xingtu_live_request({"attribute_filter": []}, expectation)
    with pytest.raises(CollectorError, match="LIVE_PROFILE_VALUE"):
        validate_xingtu_live_request(
            {
                "attribute_filter": [
                    {"field": {"field_name": "watcher_age_rate_most"}, "field_value": "[21]"},
                    {
                        "field": {"field_name": "live_watcher_gender_male_rate__ge"},
                        "field_value": "0.6",
                    },
                ]
            },
            expectation,
        )


def test_xingtu_request_validation_rejects_missing_or_extra_filters():
    form = xingtu_form(live_filters=[{"field": "live_content_type", "values": ["fashion"]}])
    plan = build_expected_plan(form, XINGTU.capabilities)
    expectation = expected_xingtu_live_request(plan, XINGTU.capabilities)
    with pytest.raises(CollectorError, match="LIVE_FILTER_REQUEST_MISMATCH"):
        validate_xingtu_live_request({"attribute_filter": None}, expectation)
    with pytest.raises(CollectorError, match="LIVE_FILTER_REQUEST_MISMATCH"):
        validate_xingtu_live_request(
            {
                "attribute_filter": [
                    {
                        "field": {"field_name": "live_tag_content_v2_level_one"},
                        "field_value": "[10719]",
                    },
                    {"field": {"field_name": "gender"}, "field_value": "2"},
                ]
            },
            expectation,
        )


def test_juxing_content_category_maps_to_verified_tag_and_path_source():
    form = juxing_form(
        live_filters=[
            {"field": "live_content_category", "values": ["beauty", "fashion"]},
            {
                "field": "live_expected_viewers",
                "range": {"min": 100, "max": 300, "unit": "ten_thousand_count"},
            },
            {
                "field": "live_max_online",
                "range": {"min": 100, "max": 300, "unit": "ten_thousand_count"},
            },
            {"field": "live_expected_cpm", "range": {"min": 30, "max": 50, "unit": "yuan"}},
        ]
    )
    plan = build_expected_plan(form, JUXING.capabilities)
    body = juxing_live_filter_body(plan, JUXING.capabilities)
    assert body == {
        "contentTagIdList": [
            {
                "id": "670",
                "subIds": ["707", "708", "709", "710", "711", "712"],
                "selectFirstLevelId": True,
            },
            {
                "id": "675",
                "subIds": ["735", "736", "737", "738", "739"],
                "selectFirstLevelId": True,
            },
        ],
        "liveExpectViewer": {"min": 1000000, "max": 3000000},
        "liveMaxViewerMinNum": 1000000,
        "liveMaxViewerMaxNum": 3000000,
        "expectCpmMinNum": 30,
        "expectCpmMaxNum": 50,
    }


def test_juxing_profile_body_uses_real_field_names_and_shapes():
    form = juxing_form(
        live_filters=[
            {
                "field": "live_fan_profile",
                "profile": [
                    {"key": "age", "values": ["18-23"]},
                    {"key": "gender", "values": ["FEMALE"]},
                    {"key": "mobile", "values": ["IOS"]},
                    {"key": "crowd", "values": ["精致妈妈"]},
                ],
            }
        ]
    )
    plan = build_expected_plan(form, JUXING.capabilities)
    body = juxing_live_filter_body(plan, JUXING.capabilities)
    assert body == {
        "fansAgeList": [{"queryName": "18-23", "from": "0.50", "to": "1.00"}],
        "fansGender": {"queryName": "FEMALE", "from": "0.00", "to": "1.00"},
        "fansMobile": {"queryName": "IOS", "from": "0.00", "to": "1.00"},
        "fansNineMajorGroupsList": [{"queryName": "精致妈妈", "from": "0.00", "to": "1.00"}],
    }


def test_cross_platform_filter_fields_are_rejected():
    xingtu_plan = FilterPlan(
        schema_version="filter_plan.v2",
        platform="douyin_xingtu",
        creator_scene=CreatorScene.LIVE_SQUARE,
        capability_version=XINGTU.capabilities.version,
        target_count=5,
        filters=[
            Filter(
                field="live_content_category",
                operator="in",
                value=["fashion"],
                source_fields=["live_filters.0"],
            )
        ],
        sort=Sort(key="platform_default"),
    )
    with pytest.raises(CollectorError, match="UNSUPPORTED_FILTER"):
        XINGTU.capabilities.validate_plan(xingtu_plan, live=True)
    juxing_plan = xingtu_plan.model_copy(
        update={"platform": "kuaishou_juxing", "schema_version": "filter_plan.v3"}
    )
    juxing_plan.filters = [
        Filter(
            field="live_content_type",
            operator="in",
            value=["fashion"],
            source_fields=["live_filters.0"],
        )
    ]
    with pytest.raises(CollectorError, match="UNSUPPORTED_FILTER"):
        JUXING.capabilities.validate_plan(juxing_plan, live=True)


def test_disabled_filter_is_rejected():
    capabilities = XINGTU.capabilities.model_copy(deep=True)
    field = next(item for item in capabilities.fields if item.field == "live_region")
    field.disabled_reason = "当前账号不可用"
    form = xingtu_form(
        live_filters=[{"field": "live_region", "regions": [{"province_code": "440000"}]}]
    )
    with pytest.raises(CollectorError, match="当前账号不可用"):
        build_expected_plan(form, capabilities)


def test_live_invalid_range_is_rejected():
    with pytest.raises(CollectorError, match="range outside capability"):
        build_expected_plan(
            xingtu_form(
                live_filters=[
                    {
                        "field": "live_followers",
                        "range": {"min": 5001, "max": 6000, "unit": "ten_thousand_count"},
                    }
                ]
            ),
            XINGTU.capabilities,
        )


def test_video_square_behavior_is_unchanged():
    video = registry("douyin_xingtu.verified.json")
    form = RequirementForm(keyword="宠物", target_count=200)
    plan = build_expected_plan(form, video.capabilities)
    assert [item.field for item in plan.filters] == ["keyword"]
    assert plan.target_count == 200
    assert plan.creator_scene == CreatorScene.VIDEO_SQUARE


def test_live_plan_digest_contains_filter_values():
    first = build_expected_plan(
        xingtu_form(live_filters=[{"field": "live_content_type", "values": ["fashion"]}]),
        XINGTU.capabilities,
    )
    second = build_expected_plan(
        xingtu_form(live_filters=[{"field": "live_gender", "values": ["female"]}]),
        XINGTU.capabilities,
    )
    assert first.digest() != second.digest()


def test_live_profiles_are_compound_and_require_dimensions():
    with pytest.raises(ValidationError, match="profile dimensions"):
        xingtu_form(live_filters=[{"field": "live_fan_profile", "values": ["anything"]}])
    with pytest.raises(ValidationError, match="exactly one value shape"):
        xingtu_form(
            live_filters=[
                {
                    "field": "live_fan_profile",
                    "values": ["x"],
                    "profile": [{"key": "age", "values": ["age_18_23"]}],
                }
            ]
        )
    with pytest.raises(CollectorError, match="enum"):
        build_expected_plan(
            xingtu_form(
                live_filters=[
                    {
                        "field": "live_gender",
                        "values": ["unknown"],
                    }
                ]
            ),
            XINGTU.capabilities,
        )
    assert NumberRange(min=1, max=2)
