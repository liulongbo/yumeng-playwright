from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from xingtu.contracts import PlatformRegistry
from xingtu.domain import (
    Checkpoint,
    CollectorError,
    CreatorRef,
    ExecutionContext,
    FieldStatus,
    Filter,
    FilterPlan,
    NumberRange,
    RegionCompound,
    RegionFilterSelection,
)
from xingtu.juxing_adapter import KuaishouJuxingAdapter

CONTRACT = Path("contracts/kuaishou_juxing.verified.json")


def registry() -> PlatformRegistry:
    parsed = PlatformRegistry.model_validate_json(CONTRACT.read_text())
    parsed.require_enabled(live=True)
    return parsed


async def guard() -> None:
    return None


def adapter() -> KuaishouJuxingAdapter:
    return KuaishouJuxingAdapter(
        Mock(),
        registry(),
        "60821564",
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
        adapter_version="juxing-browser-v3",
        contract_version="juxing-video-creator-stage-c-v3",
    )


def creator() -> CreatorRef:
    return CreatorRef(
        platform="kuaishou_juxing",
        platform_creator_id="1344496241",
        verified_homepage="https://k.kuaishou.com/#/promotion/star/765154?openBy=user",
    )


def cp(plan: FilterPlan, cursor: str | None = None) -> Checkpoint:
    return Checkpoint(
        conditions_digest=plan.digest(),
        cursor=cursor,
        contract_version="juxing-video-creator-stage-c-v3",
        adapter_version="juxing-browser-v3",
    )


def plan(filters: list[Filter], target: int = 1) -> FilterPlan:
    return FilterPlan(
        schema_version="filter_plan.v3",
        platform="kuaishou_juxing",
        capability_version="juxing-video-square-stage-c-v2",
        target_count=target,
        filters=filters,
    )


def keyword(value: str = "母婴") -> Filter:
    return Filter(field="keyword", operator="eq", value=value, source_fields=["keyword"])


def content(value: list[str]) -> Filter:
    return Filter(
        field="content_type", operator="in", value=value, source_fields=["content_types.0"]
    )


def followers(minimum: str, maximum: str | None) -> Filter:
    return Filter(
        field="followers",
        operator="range",
        value=NumberRange(
            min=Decimal(minimum) if minimum else None,
            max=Decimal(maximum) if maximum else None,
        ),
        source_fields=["followers.min", "followers.max"],
        unit="count",
    )


def quote(field: str = "video_quote_21_60", minimum: str = "1000", maximum: str = "3000") -> Filter:
    return Filter(
        field=field,
        operator="range",
        value=NumberRange(min=Decimal(minimum), max=Decimal(maximum)),
        source_fields=["juxing_video_quotes.seconds_21_60.min"],
        unit="yuan",
        currency="CNY",
        cooperation_form="short_video_21_60s",
    )


def region(*selections: RegionFilterSelection) -> Filter:
    return Filter(
        field="region",
        operator="compound",
        value=RegionCompound(selections=list(selections)),
        source_fields=["creator_regions"],
    )


def page(cursor: str | None = None) -> Mock:
    return Mock(
        url="https://k.kuaishou.com/?__accountId__=60821564#/star_plaza/video?__accountId__=60821564",
        cursor=cursor,
    )


def search_payload(page_number: int, total: int, count: int, start: int = 0) -> dict:
    return {
        "result": 1,
        "total": total,
        "currentPage": page_number,
        "starList": [
            {"userId": str(start + index), "starId": 700000 + start + index}
            for index in range(count)
        ],
    }


def test_contract_registers_pages_one_to_five_and_the_filter_surface():
    parsed = registry()
    assert parsed.search is not None
    assert parsed.search.page_fetch_max_verified == 5
    assert parsed.search.single_page_only is False
    assert parsed.search.resume_supported is True
    capabilities = {field.field: field for field in parsed.capabilities.fields}
    assert len(capabilities["content_type"].options) == 38
    assert len(capabilities["region"].region_tree) == 34
    assert {"video_quote_1_20", "video_quote_21_60", "video_quote_60_plus"} <= set(capabilities)
    assert [len(module.fields) for module in parsed.modules] == [18, 31, 1, 2]


def test_keyword_only_body_matches_the_verified_page_request():
    body = adapter()._build_search_body(plan([keyword()]), 1)
    assert body["userName"] == "母婴"
    assert body["searchSourceType"] == 10
    assert body["pathSource"] == "precise_content_search_video"
    assert "contentTagIdList" not in body
    assert body["currentPage"] == 1
    assert body["pageSize"] == 20


def test_content_type_uses_contract_mapping_for_maternal_and_beauty():
    subject = adapter()
    maternal = subject._build_search_body(plan([keyword(), content(["maternal_child"])]), 1)
    assert maternal["contentTagIdList"] == [
        {"id": "676", "subIds": ["740", "741", "742", "743"], "selectFirstLevelId": True}
    ]
    assert maternal["pathSource"] == "fuzzy_content_search_video"
    beauty = subject._build_search_body(plan([keyword(), content(["670"])]), 1)
    assert beauty["contentTagIdList"] == [
        {
            "id": "670",
            "subIds": ["707", "708", "709", "710", "711", "712"],
            "selectFirstLevelId": True,
        }
    ]


def test_followers_quote_and_path_source_match_verified_page_bodies():
    subject = adapter()
    body = subject._build_search_body(plan([keyword(), followers("100000", "1000000")]), 1)
    assert body["fansMinNum"] == 100000
    assert body["fansMaxNum"] == 1000000
    assert body["pathSource"] == "fuzzy_content_search_video"
    quoted = subject._build_search_body(plan([keyword(), quote()]), 1)
    assert quoted["priceType"] == 12
    assert quoted["starMinPrice"] == 1_000_000
    assert quoted["starMaxPrice"] == 3_000_000
    assert quoted["pathSource"] == "fuzzy_content_search_video"


def test_region_contract_expands_provinces_and_selects_cities():
    subject = adapter()
    beijing = subject._build_search_body(
        plan([keyword(), region(RegionFilterSelection(province_code="11"))]), 1
    )
    assert beijing["cityCodeList"] == [1101]
    hebei = subject._build_search_body(
        plan([keyword(), region(RegionFilterSelection(province_code="13"))]), 1
    )
    assert len(hebei["cityCodeList"]) == 12
    assert 1301 in hebei["cityCodeList"]
    city = subject._build_search_body(
        plan([keyword(), region(RegionFilterSelection(province_code="13", city="石家庄"))]), 1
    )
    assert city["cityCodeList"] == [1301]


def test_multiple_quote_tiers_are_rejected():
    subject = adapter()
    with pytest.raises(CollectorError, match="JUXING_QUOTE_FILTERS_MUTUALLY_EXCLUSIVE"):
        subject._build_search_body(
            plan([keyword(), quote("video_quote_1_20"), quote("video_quote_21_60")]), 1
        )


def test_unknown_filter_is_never_silently_ignored():
    subject = adapter()
    unsupported = Mock(field="gender", value="female")
    invalid_plan = Mock(filters=[unsupported])
    with pytest.raises(CollectorError, match="UNSUPPORTED_FILTER"):
        subject._build_search_body(invalid_plan, 1)


async def test_page_two_search_rebuilds_filters_and_advances_checkpoint():
    subject = adapter()
    subject.search_page = page()
    subject.check_session = AsyncMock()
    subject._post_json = AsyncMock(return_value=search_payload(2, total=21, count=1, start=20))
    current = cp(plan([keyword(), content(["maternal_child"])]))
    current.cursor = "2"
    result = await subject.search(
        plan([keyword(), content(["maternal_child"])]), current, context()
    )
    assert [candidate.platform_creator_id for candidate in result.candidates] == ["20"]
    assert result.current_checkpoint == "2"
    assert result.next_checkpoint is None
    assert result.exhausted is True
    body = subject._post_json.await_args.args[2]
    assert body["currentPage"] == 2
    assert body["contentTagIdList"][0]["id"] == "676"
    assert body["userName"] == "母婴"


async def test_page_five_search_rebuilds_filters_and_keeps_advancing():
    subject = adapter()
    subject.search_page = page()
    subject.check_session = AsyncMock()
    subject._post_json = AsyncMock(return_value=search_payload(5, total=101, count=20, start=80))
    current = cp(plan([keyword(), content(["maternal_child"])]))
    current.cursor = "5"
    result = await subject.search(
        plan([keyword(), content(["maternal_child"])]), current, context()
    )
    assert [candidate.platform_creator_id for candidate in result.candidates] == [
        str(80 + index) for index in range(20)
    ]
    assert result.current_checkpoint == "5"
    assert result.next_checkpoint == "6"
    assert result.exhausted is False
    body = subject._post_json.await_args.args[2]
    assert body["currentPage"] == 5
    assert body["contentTagIdList"][0]["id"] == "676"
    assert body["userName"] == "母婴"


async def test_cursor_above_the_verified_bound_fails_closed():
    subject = adapter()
    subject.search_page = page()
    subject.check_session = AsyncMock()
    subject._post_json = AsyncMock()
    current = cp(plan([keyword()]))
    current.cursor = "6"
    with pytest.raises(CollectorError, match="JUXING_PAGE_LIMIT"):
        await subject.search(plan([keyword()]), current, context())
    subject._post_json.assert_not_awaited()


async def test_empty_page_before_total_is_a_contract_error_not_exhaustion():
    subject = adapter()
    subject.search_page = page()
    subject.check_session = AsyncMock()
    subject._post_json = AsyncMock(
        return_value={"result": 1, "total": 60, "currentPage": 2, "starList": []}
    )
    current = cp(plan([keyword()]))
    current.cursor = "2"
    with pytest.raises(CollectorError, match="JUXING_SEARCH_EMPTY_PAGE"):
        await subject._search(plan([keyword()]), current, page_number=2)


async def test_prepare_resumes_page_two_without_refetching_page_one():
    subject = adapter()
    browser = Mock()
    browser_page = Mock(
        url="https://k.kuaishou.com/?__accountId__=60821564#/star_plaza/video?__accountId__=60821564"
    )
    browser.new_page = AsyncMock(return_value=browser_page)
    subject.browser = browser
    subject.check_session = AsyncMock()
    subject._post_json = AsyncMock()
    current = cp(plan([keyword()]))
    current.cursor = "2"
    assert await subject.prepare(plan([keyword()]), current, context()) is True
    subject._post_json.assert_not_awaited()
    assert subject.search_page is browser_page


async def test_prepare_resumes_the_sentinel_cursor_after_the_last_verified_page():
    """After page 5 the engine stores "6" while page-5 candidates are still being collected.

    A retry in that state must resume, not fail: the capability boundary is enforced by
    ``search()`` (which the engine turns into a partial completion), not by ``prepare``.
    """

    subject = adapter()
    browser = Mock()
    browser_page = Mock(
        url="https://k.kuaishou.com/?__accountId__=60821564#/star_plaza/video?__accountId__=60821564"
    )
    browser.new_page = AsyncMock(return_value=browser_page)
    subject.browser = browser
    subject.check_session = AsyncMock()
    subject._post_json = AsyncMock()
    assert subject.registry.search is not None
    assert subject.registry.search.page_fetch_max_verified == 5
    current = cp(plan([keyword()]))
    current.cursor = "6"
    assert await subject.prepare(plan([keyword()]), current, context()) is True
    subject._post_json.assert_not_awaited()


async def test_prepare_still_rejects_a_cursor_beyond_the_verified_sentinel():
    subject = adapter()
    browser = Mock()
    browser_page = Mock(
        url="https://k.kuaishou.com/?__accountId__=60821564#/star_plaza/video?__accountId__=60821564"
    )
    browser.new_page = AsyncMock(return_value=browser_page)
    subject.browser = browser
    subject.check_session = AsyncMock()
    current = cp(plan([keyword()]))
    current.cursor = "7"
    with pytest.raises(CollectorError) as excinfo:
        await subject.prepare(plan([keyword()]), current, context())
    assert excinfo.value.code == "SEARCH_CAPABILITY_LIMIT"


async def test_prepare_fetches_page_one_and_search_returns_prepared_result():
    subject = adapter()
    browser = Mock()
    browser_page = Mock(
        url="https://k.kuaishou.com/?__accountId__=60821564#/star_plaza/video?__accountId__=60821564"
    )
    browser_page.set_default_timeout = Mock()
    browser.new_page = AsyncMock(return_value=browser_page)
    subject.browser = browser
    subject.check_session = AsyncMock()
    subject._post_json = AsyncMock(return_value=search_payload(1, total=40, count=20))
    task_plan = plan([keyword()])
    current = cp(task_plan)
    assert await subject.prepare(task_plan, current, context()) is True
    result = await subject.search(task_plan, current, context())
    assert len(result.candidates) == 20
    assert result.next_checkpoint == "2"
    assert result.exhausted is False
    subject._post_json.assert_awaited_once()


async def test_spread_module_emits_every_registered_field_and_new_metrics():
    subject = adapter()
    subject.search_page = page()
    subject.detail_page = page()
    subject.check_session = AsyncMock()
    subject.verify_identity = AsyncMock()
    subject._post_json = AsyncMock(
        return_value={
            "result": 1,
            "data": {
                "natureStatistics": {
                    "pplayMedian": 171,
                    "pinteractionRate": 0.01429,
                    "pcompletePlayRate": 0.07902,
                    "pavgShareCntData": None,
                    "pavgLikeCntData": 2,
                    "pavgCommentCntData": None,
                    "preleaseCnt": 25,
                    "pavgVideoDurationData": 10.4858,
                    "pplayMedianPowerPercent": 0.652,
                    "pinteractionRatePowerPercent": 0.76945,
                    "pcompletePlayRatePowerPercent": 0.65852,
                },
                "businessStatistics": {
                    "beplayCnt": 188,
                    "beplayCntMOM": 0.7904,
                    "beCPM": 5319.0,
                    "beCpmMOM": -1.0,
                    "bcpm": None,
                    "bcpe": None,
                    "bavgConversionClickRate": None,
                    "bplayMedian": None,
                    "bplayMedianPowerPercent": None,
                    "breleaseCnt": None,
                    "bcompletePlayRate": None,
                    "bcompletePlayRatePowerPercent": None,
                    "binteractionRate": None,
                    "binteractionRatePowerPercent": None,
                    "bavgVideoDurationData": None,
                    "bavgLikeCntData": None,
                    "bavgCommentCntData": None,
                    "bavgShareCntData": None,
                },
                "visitorNum": 2166,
                "deepVisitorNum": 20,
            },
        }
    )
    observation = await subject.collect_module("spread", creator(), context())
    fields = {field.field_key: field for field in observation.fields}
    assert observation.complete is True
    assert len(fields) == 31
    assert fields["play_median"].value.amount == Decimal("171")
    assert fields["play_median_percentile"].value.amount == Decimal("0.652")
    assert fields["interaction_rate_percentile"].value.amount == Decimal("0.76945")
    assert fields["expected_cpm_mom"].value.amount == Decimal("-1.0")
    assert fields["visitor_num"].value.amount == Decimal("2166")
    assert fields["deep_visitor_num"].value.amount == Decimal("20")
    assert fields["recent_cpm"].status == FieldStatus.NO_DATA
    assert fields["business_play_median"].status == FieldStatus.NO_DATA


async def test_works_items_include_verified_business_fields():
    subject = adapter()
    subject.search_page = page()
    subject.detail_page = page()
    subject.check_session = AsyncMock()
    subject.verify_identity = AsyncMock()
    subject._post_json = AsyncMock(
        return_value={
            "result": 1,
            "data": {
                "detailList": [
                    {
                        "photoId": "213722177875",
                        "caption": "作品",
                        "webpUrl": "https://video.kuaishou.com/short-video/example",
                        "coverUrl": "https://p3-ad.adukwai.com/example.jpg",
                        "viewCnt": 876,
                        "likeCnt": 4,
                        "commentCnt": 2,
                        "forwardCnt": 3,
                        "releaseTimeMillis": 1793157880101,
                        "business": False,
                        "worksRankType": 1,
                        "productName": "商品",
                        "containsPaid": False,
                        "qualityHot": True,
                        "quantityHot": False,
                        "qualityAndQuantityHot": False,
                        "firstIndustryName": "母婴",
                    }
                ]
            },
        }
    )
    observation = await subject.collect_module("works", creator(), context())
    works = {field.field_key: field for field in observation.fields}["works"]
    assert works.status == FieldStatus.COLLECTED
    item = works.value.data[0]
    assert item["cover_url"] == "https://p3-ad.adukwai.com/example.jpg"
    assert item["product_name"] == "商品"
    assert item["quality_hot"] is True
    assert item["first_industry_name"] == "母婴"


async def test_basic_module_adds_gender_profile_forms_and_settlement():
    subject = adapter()
    subject.search_page = page()
    subject.detail_page = page()
    subject.check_session = AsyncMock()
    subject.verify_identity = AsyncMock()
    subject._post_json = AsyncMock(
        side_effect=[
            {
                "result": 1,
                "data": {
                    "userId": 1344496241,
                    "name": "样本",
                    "headUrl": "https://p3-ad.adukwai.com/head.jpg",
                    "gender": "女",
                    "address": "山东-菏泽",
                    "profileUrl": "www.kuaishou.com/profile/example",
                    "fansNumber": 171304,
                    "contentTypeTag": {"firstTagName": "母婴亲子", "secondTagName": "育儿"},
                    "contentFormTag": [{"firstTagName": "推荐", "secondTagName": ["探店"]}],
                    "platformTargetIdentityInfo": {"id": 0, "name": "潜力达人"},
                    "styleDetail": "普通中立",
                    "publicSettlement": False,
                    "mcnName": "",
                    "introduction": "简介",
                    "priceShowInfo": [
                        {
                            "businessLine": 1,
                            "priceType": 12,
                            "price": 1000000,
                            "priceTypeName": "21-60秒视频",
                            "originalPrice": 2000000,
                            "priceStartTimeMs": 0,
                            "priceEndTimeMs": 0,
                        }
                    ],
                },
            },
            {"result": 1, "data": {"fansIncreaseNum": 226, "fansIncreaseRate": 0.002}},
        ]
    )
    observation = await subject.collect_module("basic", creator(), context())
    fields = {field.field_key: field for field in observation.fields}
    assert observation.complete is True
    assert fields["gender"].value == "女"
    assert fields["profile_url"].value == "www.kuaishou.com/profile/example"
    assert fields["content_form_labels"].value == ["推荐", "探店"]
    assert fields["platform_identity"].value == "潜力达人"
    assert fields["style_detail"].value == "普通中立"
    assert fields["public_settlement"].value == "不支持对公"
    offer = fields["cooperation_offers"].value.data[0]
    assert offer["price_yuan"] == 1000
    assert offer["original_price_yuan"] == 2000
    assert offer["price_start_ms"] is None
