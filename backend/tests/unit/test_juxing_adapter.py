from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from xingtu.contracts import LocatorSpec, PlatformRegistry
from xingtu.domain import (
    CollectorError,
    CreatorRef,
    ExecutionContext,
    Filter,
    FilterPlan,
    NumberRange,
)
from xingtu.juxing_adapter import KuaishouJuxingAdapter


def registry() -> PlatformRegistry:
    return PlatformRegistry.model_validate_json(
        Path("contracts/kuaishou_juxing.verified.json").read_text()
    )


async def guard() -> None:
    return None


def adapter() -> KuaishouJuxingAdapter:
    return KuaishouJuxingAdapter(
        Mock(),
        registry(),
        "stage-b-test-account",
        guard,
        on_session_health=Mock(),
    )


def context() -> ExecutionContext:
    return ExecutionContext(
        root_task_id="root",
        task_id="task",
        attempt_id="attempt",
        execution_unit_id="unit",
        lease_generation=1,
        session_version=1,
        capability_version="juxing-video-square-stage-c-v2",
        adapter_version="juxing-browser-v1",
        contract_version="juxing-video-creator-stage-c-v3",
    )


def creator() -> CreatorRef:
    return CreatorRef(
        platform="kuaishou_juxing",
        platform_creator_id="576757970",
        verified_homepage="https://k.kuaishou.com/#/promotion/star/196223?openBy=user",
    )


def test_locator_capture_regex_is_explicit_and_single_group():
    locator = LocatorSpec(
        selector="iframe[src*='aid=']",
        attribute="src",
        capture_regex=r"[?&]aid=(\d+)",
    )
    assert locator.capture_regex == r"[?&]aid=(\d+)"


def test_stage_b_search_mapping_uses_verified_juxing_literals():
    plan = FilterPlan(
        schema_version="filter_plan.v3",
        platform="kuaishou_juxing",
        capability_version="juxing-video-square-stage-c-v2",
        target_count=1,
        filters=[
            Filter(
                field="keyword",
                operator="eq",
                value="母婴",
                source_fields=["keyword"],
            ),
            Filter(
                field="content_type",
                operator="in",
                value=["maternal_child"],
                source_fields=["content_types.0"],
            ),
        ],
    )
    body = adapter()._build_search_body(plan, 1)
    assert body["userName"] == "母婴"
    assert body["contentTagIdList"] == [
        {
            "id": "676",
            "subIds": ["740", "741", "742", "743"],
            "selectFirstLevelId": True,
        }
    ]
    assert body["pathSource"] == "fuzzy_content_search_video"


def test_quote_mapping_preserves_yuan_to_platform_scale():
    plan = FilterPlan(
        schema_version="filter_plan.v3",
        platform="kuaishou_juxing",
        capability_version="test",
        target_count=1,
        filters=[
            Filter(
                field="video_quote_21_60",
                operator="range",
                value=NumberRange(min=Decimal("100"), max=Decimal("10000")),
                source_fields=["min", "max"],
                unit="yuan",
                currency="CNY",
                cooperation_form="short_video_21_60s",
            )
        ],
    )
    body = adapter()._build_search_body(plan, 1)
    assert body["priceType"] == 12
    assert body["starMinPrice"] == 100_000
    assert body["starMaxPrice"] == 10_000_000


async def test_live_shaped_basic_response_maps_identity_growth_and_quotes():
    subject = adapter()
    subject.search_page = Mock(url="https://k.kuaishou.com/#/star_plaza/video")
    subject.detail_page = Mock(url="https://k.kuaishou.com/#/promotion/star/196223?openBy=user")
    subject.check_session = AsyncMock()
    subject.verify_identity = AsyncMock()
    subject._post_json = AsyncMock(
        side_effect=[
            {
                "result": 1,
                "data": {
                    "userId": 576757970,
                    "starId": 196223,
                    "name": "真实样本昵称已脱敏",
                    "headUrl": "https://p3-ad.adukwai.com/example.jpg",
                    "address": "黑龙江-哈尔滨",
                    "fansNumber": 21686076,
                    "introduction": "母婴内容创作者，商务合作微信 sample_vx_1234，电话 13800138000",
                    "mcnName": "样本机构",
                    "contentTypeTag": {"firstTagName": "短剧", "secondTagName": "搞笑短剧"},
                    "priceShowInfo": [
                        {
                            "businessLine": 1,
                            "priceType": 12,
                            "price": 210750000,
                            "priceTypeName": "21-60秒视频",
                        }
                    ],
                },
            },
            {
                "result": 1,
                "data": {"fansIncreaseNum": 268703, "fansIncreaseRate": 0.0125},
            },
        ]
    )
    observation = await subject.collect_module("basic", creator(), context())
    fields = {field.field_key: field for field in observation.fields}
    assert fields["platform_creator_id"].value == "576757970"
    assert fields["followers"].value.amount == Decimal("21686076")
    assert fields["followers"].raw_value == "21686076"
    assert fields["monthly_follower_growth_rate"].value.amount == Decimal("0.0125")
    assert fields["monthly_follower_growth_rate"].raw_value == "0.0125"
    assert "sample_vx_1234" not in fields["introduction"].value
    assert "13800138000" not in fields["introduction"].raw_value
    offers = fields["cooperation_offers"].value.data
    assert offers[0]["platform_price_raw"] == 210750000
    assert offers[0]["price_yuan"] == 210750
    assert observation.complete is True


class _VisibleLocator:
    async def is_visible(self) -> bool:
        return True


class _HiddenLocator:
    async def is_visible(self) -> bool:
        return False


class _SlowPage:
    """First goto times out; the registered ready surface is already present."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.calls: list[tuple[str, str | None]] = []

    async def goto(self, url: str, *, wait_until: str | None = None, timeout: float | None = None):
        del timeout
        self.calls.append((url, wait_until))
        if wait_until == "commit":
            return None
        raise PlaywrightTimeoutError("Timeout 30000ms exceeded")

    def locator(self, selector: str):
        # The fake page has no account-selection modal; only the registered search surface.
        if selector == "div.account-component":
            return _HiddenLocator()
        return _VisibleLocator()


async def test_late_domcontentloaded_is_accepted_when_the_ready_surface_is_present():
    page = _SlowPage("https://k.kuaishou.com/#/star_plaza/video")
    adapter_instance = adapter()
    await adapter_instance.navigate(page, "https://k.kuaishou.com/#/star_plaza/video")
    assert page.calls == [("https://k.kuaishou.com/#/star_plaza/video", "domcontentloaded")]


async def test_navigation_retries_with_commit_then_waits_for_the_same_ready_contract():
    page = _SlowPage("about:blank")
    adapter_instance = adapter()
    await adapter_instance.navigate(page, "https://k.kuaishou.com/#/star_plaza/video")
    assert page.calls == [
        ("https://k.kuaishou.com/#/star_plaza/video", "domcontentloaded"),
        ("https://k.kuaishou.com/#/star_plaza/video", "commit"),
    ]


class _AccountSelectionPage:
    url = "https://k.kuaishou.com/#/star_plaza/video"

    def locator(self, selector: str):
        del selector
        return _VisibleLocator()


async def test_account_selection_page_is_classified_separately_from_security_challenge():
    subject = adapter()
    with pytest.raises(CollectorError) as raised:
        await subject.inspect_session(_AccountSelectionPage())
    assert raised.value.code == "ACCOUNT_SELECTION_REQUIRED"
