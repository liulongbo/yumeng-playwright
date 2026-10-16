from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from playwright.async_api import Error as BrowserError
from xingtu.adapter import BrowserAdapter, build_expected_attribute_filters
from xingtu.contracts import PlatformRegistry
from xingtu.domain import CollectorError
from xingtu.intake import build_expected_plan
from xingtu.product_models import RequirementForm


def capabilities():
    return PlatformRegistry.model_validate_json(
        Path("contracts/douyin_xingtu.verified.json").read_text()
    ).capabilities


def registry():
    return PlatformRegistry.model_validate_json(
        Path("contracts/douyin_xingtu.verified.json").read_text()
    )


def test_full_combination_maps_to_exact_attribute_filter_multiset():
    form = RequirementForm(
        keyword="汽车",
        creator_gender="female",
        creator_regions=[{"province_code": "110000"}],
        creator_education="master",
        yellow_v_certification="technology",
        connection_users={
            "connected": {"min": 1, "max": 2},
            "aware": {"min": 0.5},
            "interested": {"max": 3},
            "liked": {"min": 4},
            "followed": {"max": 5},
        },
        followers={"min": 100, "max": 300},
        fan_profile={
            "age": ["age_18_23"],
            "gender": "female_60",
            "device_brand": ["apple"],
            "city_level": ["tier_1"],
            "crowd": ["gen_z"],
        },
    )
    actual = build_expected_attribute_filters(
        build_expected_plan(form, capabilities()), capabilities()
    )
    assert [(item.field_name, item.field_value) for item in actual] == [
        ("follower__ge", "1000000"),
        ("follower__le", "3000000"),
        ("gender", "2"),
        ("province", '["北京市"]'),
        ("persona_tag_level_one", '["110211"]'),
        ("persona_tag_level_one", '["110210"]'),
        ("link_link_cnt_by_industry__ge", "10000"),
        ("link_link_cnt_by_industry__le", "20000"),
        ("link_l_cnt_by_industry__ge", "5000"),
        ("link_i_cnt_by_industry__le", "30000"),
        ("link_n_cnt_by_industry__ge", "40000"),
        ("link_k_cnt_by_industry__le", "50000"),
        ("fans_age_rate_most", "[21]"),
        ("fans_system_rate_most", "[10]"),
        ("fans_city_level_most", "[13]"),
        ("fans_crowd_profile", "[58]"),
        ("fans_gender_female_rate_v2__ge", "0.6"),
    ]


def test_city_path_maps_to_city_without_inventing_province_filter():
    form = RequirementForm(creator_regions=[{"province_code": "110000", "city": "朝阳区"}])
    actual = build_expected_attribute_filters(
        build_expected_plan(form, capabilities()), capabilities()
    )
    assert [(item.field_name, item.field_value) for item in actual] == [("city", '["朝阳区"]')]


def test_dynamic_profile_automation_uses_stable_select_containers():
    fields = {item.field: item for item in capabilities().fields}
    assert fields["viewer_profile"].automation["dimension_selector"] == ".el-select"
    assert fields["fan_profile"].automation["dimension_selector"] == ".el-select"
    assert fields["followers"].automation["custom_input_selector"] == ".custom input"


async def test_dynamic_filter_locator_drift_is_classified_fail_closed():
    async def guard():
        return None

    adapter = BrowserAdapter(None, registry(), "account", guard, live=True)
    adapter._apply_xingtu_filters = AsyncMock(side_effect=BrowserError("missing control"))
    plan = build_expected_plan(RequirementForm(keyword="汽车"), capabilities())

    with pytest.raises(CollectorError) as error:
        await adapter.apply_xingtu_filters(None, plan)
    assert error.value.code == "PLATFORM_PAGE_CHANGED"
    assert error.value.reason == "REGISTERED_FILTER_CONTROL_UNAVAILABLE"
