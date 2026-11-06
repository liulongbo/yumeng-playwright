"""Adapter-level checks for the Juxing live detail modules.

The browser is not involved: the registered responses are replaced by real-shaped payloads and the
adapter's module orchestration/FieldObservation construction is exercised directly.  These tests
catch integration mistakes between the pure parsers, the contract field kinds/units and the
per-module cycle (especially the difference between NO_DATA and FAILED).
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from xingtu.contracts import PlatformRegistry
from xingtu.domain import CollectorError, CreatorRef, FieldStatus
from xingtu.juxing_live_adapter import KuaishouJuxingLiveAdapter


def registry() -> PlatformRegistry:
    return PlatformRegistry.model_validate_json(
        Path("contracts/kuaishou_juxing.live.verified.json").read_text()
    )


def profile() -> dict:
    return {
        "userId": 52022133,
        "starId": 9104,
        "name": "测试达人",
        "headUrl": "https://example.test/avatar.jpg",
        "gender": "男",
        "address": "广东-广州",
        "fansNumber": 37388604,
        "starTagStr": "",
        "industryTagStr": "",
        "industryTag": [{"firstTagName": "游戏", "secondTagName": ["角色扮演"]}],
        "contentTypeTag": {"firstTagName": "游戏", "secondTagName": "MOBA"},
        "contentFormTag": [],
        "govName": "测试机构",
        "verifiedInfo": "快手2025百大主播",
        "livePlayCntExpectancy": 1734393,
        "livePcuCnt": 129037,
        "liveCpmExpectancy": 17.0,
        "liveWeeklyTimesCnt": 10,
        "liveAvgPeopleNum": 847557,
        "liveAvgLikeCnt": 0,
        "liveMaxExpectOnlineViewer": 52357,
        "creditScore": None,
        "priceShowInfo": [
            {"businessLine": 2, "priceType": 1, "price": 29100000, "priceTypeName": "直播按小时"},
            {"businessLine": 2, "priceType": 2, "price": 75450000, "priceTypeName": "直播按天"},
            {"businessLine": 2, "priceType": 3, "price": 45400000, "priceTypeName": "直播按商品数"},
        ],
        "liveBusinessReport": {
            "advertiserFirstIndustries": ["游戏", "电商平台"],
            "acceptOrderRateData": {"30": 0.5641, "90": 0.7363},
            "completeOrderRateData": {"30": 0.72, "90": 0.8451},
            "completeOrderCntData": {"30": 18, "90": 60},
        },
        "viewerFeatureTag": ["男性观众为主，占比76.6%"],
        "viewerDeviceTag": ["安卓设备为主，占比67.5%"],
        "viewerAreaTag": ["广东、河南、山东的观众居多"],
        "fansIncreaseNum": {"30": 15674, "90": 636509},
        "fansIncreaseRateIn30": 0.0004,
        "fansIncreaseRateIn90": 0.0173,
        "trendData": {"30": [{"label": "20261006", "value": 37372930}], "90": []},
        "trendDiffData": {"30": [{"label": "20261007", "value": 7070}], "90": []},
        "hotBrandInfo": [
            {"hotSaleBrandId": 42119, "hotSaleBrandTitle": "王者荣耀", "hotSaleBrandRank": 1}
        ],
        "hotChannelInfo": [
            {
                "hotSaleChannelId": 0,
                "hotSaleChannelTitle": "其他",
                "hotSaleChannelRate": 100.0,
                "hotSaleChannelRank": 1,
            }
        ],
    }


def works() -> dict:
    item = {
        "streamId": "15046311215",
        "caption": "福利主播来了",
        "coverUrl": "https://example.test/cover.jpg",
        "url": "https://example.test/replay.m3u8?auth_key=1",
        "releaseTimeMillis": 1793851222704,
        "durationTimeMillis": 5523872,
        "viewCnt": 1099630,
        "peakCnt": 63543,
        "likeCnt": 4087340,
        "commentCnt": 50668,
        "forwardCnt": 2878,
        "hasSkuInfo": True,
        "orderId": 0,
    }
    return {
        "personLiveWorks": [item],
        "adSocialLiveWorks": [{**item, "streamId": "15047054415", "orderId": 1313921741704737653}],
        "recentLiveWorks": [item],
        "starWorkReport": {"liveWeekRelease": 8, "liveInteractionRate": 2.4677},
    }


def portrait() -> dict:
    return {
        "data": {
            "viewerPortrait": {
                "sexPercentage": [{"label": "男性", "value": 0.766, "tgi": 146}],
                "agePercentage": [{"label": "18-23", "value": 0.383, "tgi": 336}],
                "mobilePercentage": [],
                "mobileBrandPercentage": [{"label": "华为", "value": 0.211, "tgi": 73}],
                "mobilePricePercentage": [{"label": "1000-2000", "value": 0.393, "tgi": 89}],
                "activityPercentage": [{"label": "超高活", "value": 0.512, "tgi": 132}],
                "cityPercentage": [{"label": "thirdline", "value": 0.296, "tgi": 125}],
                "cityLevelPercentage": [{"label": "重庆", "value": 0.015, "tgi": 96}],
                "areaPercentage": [{"label": "广东", "value": 0.114, "tgi": 156}],
                "areaTopWithRadio": [{"label": "广东", "value": 0.114, "tgi": 156}],
                "areaTopWithPermeation": [{"label": "江西", "value": 0.036, "tgi": None}],
                "interestPercentage": [],
                "nineMajorGroupsPercentage": [],
            },
            "fansPortrait": {
                "sexPercentage": [{"label": "女性", "value": 0.607, "tgi": 144}],
                "agePercentage": [{"label": "18-23", "value": 0.235, "tgi": 144}],
                "mobilePercentage": [],
                "mobileBrandPercentage": [{"label": "苹果", "value": 0.268, "tgi": 99}],
                "mobilePricePercentage": [{"label": "1000-2000", "value": 0.421, "tgi": 105}],
                "activityPercentage": [{"label": "超高活", "value": 0.476, "tgi": 179}],
                "cityPercentage": [{"label": "thirdline", "value": 0.29, "tgi": 116}],
                "cityLevelPercentage": [{"label": "重庆", "value": 0.023, "tgi": 134}],
                "areaPercentage": [{"label": "广东", "value": 0.088, "tgi": 106}],
                "areaTopWithRadio": [{"label": "广东", "value": 0.088, "tgi": 106}],
                "areaTopWithPermeation": [{"label": "台湾", "value": 0.063, "tgi": None}],
                "interestPercentage": [{"label": "运动", "value": 0.825, "tgi": 98}],
                "nineMajorGroupsPercentage": [],
            },
        }
    }


def radar() -> dict:
    return {
        "starRadarGraphVO": {
            "starIndexCurrent": [
                {"label": "starIndexCurr", "value": 81.6},
                {"label": "addFansIndexCurr", "value": 92.09},
                {"label": "performancePriceIndexCurr", "value": 49.48},
                {"label": "createIndexCurr", "value": 89.92},
                {"label": "bizActiIndexCurr", "value": 89.72},
                {"label": "coopIndexCurr", "value": 94.0},
            ],
            "starIndexAvg": [{"label": "addFansIndexAvg", "value": 91.1}],
        }
    }


def trend() -> dict:
    return {
        "starTrendGraphVO": {
            "starIndexRank": [
                {"label": "bizStarRank", "value": 30538},
                {"label": "fansStarRank", "value": 64},
            ],
            "starIndexPercent": [
                {"label": "bizStarPercent", "value": 0.7832},
                {"label": "fansStarPercent", "value": 0.3905},
            ],
            "starIndexHistory": [
                {"label": "starIndexHist", "value": [{"label": "202606", "value": 0.0}]}
            ],
        }
    }


def review_rows(page: int) -> dict:
    rows = []
    for index in range(10 if page == 1 else 8):
        rows.append(
            {
                "contentQualityScore": 5.0,
                "cooperation": 5.0,
                "credit": 5.0,
                "comprehensive": 5.0,
                "productName": "客户订单-A",
                "promotionType": 2,
                "content": "遵守脚本约定",
                "timestamp": 1667193774469 + page * 1000 + index,
                "hiddenName": True,
                "haveAgent": False,
            }
        )
    return {"data": {"data": rows, "total": 18, "pageNum": 0, "pageSize": 0}}


class FakeAdapter(KuaishouJuxingLiveAdapter):
    def __init__(self, responses, *, fail_path: str | None = None):
        self.registry = registry()
        self.module_fields = {
            module.key: [field.key for field in module.fields] for module in self.registry.modules
        }
        self.module_specs = {module.key: module for module in self.registry.modules}
        self.detail_page = object()
        self.responses = responses
        self.fail_path = fail_path
        self.calls: list[tuple[str, dict]] = []
        self._reset_detail_state()

    async def _post_json(self, page, path, body):  # type: ignore[override]
        del page
        self.calls.append((path, body))
        if self.fail_path is not None and path == self.fail_path:
            raise CollectorError("MODULE_COLLECTION_FAILED", "FAKE_FAILURE")
        if path == "/rest/web/evaluation/star/list":
            page_number = int(body.get("page", 1))
            return review_rows(page_number)
        return self.responses[path]


def creator() -> CreatorRef:
    return CreatorRef(
        platform="kuaishou_juxing",
        platform_creator_id="52022133",
        verified_homepage="https://k.kuaishou.com/#/live-promotion/star/9104?openBy=user",
    )


def ctx() -> SimpleNamespace:
    return SimpleNamespace(session_version=1)


def responses() -> dict:
    return {
        "/rest/web/star/starProfile": {"result": 1, "starProfile": profile()},
        "/rest/web/star/starWorksInfo": {"result": 1, "starWorksInfo": works()},
        "/rest/web/star/listPortrait": {"result": 1, **portrait()},
        "/rest/web/starIndex/starRadarGraph": {"result": 1, **radar()},
        "/rest/web/starIndex/starTrendGraph": {"result": 1, **trend()},
        "/rest/web/star/queryVideoPlayCnt": {
            "result": 1,
            "data": {
                "starWorkPlayMonthInfo": {"9": 33, "10": 48, "11": 9},
                "starWorkPlayWeekInfo": {"0": 15},
                "starWorkPlayHourInfo": {"19": 41},
            },
        },
        "/rest/web/evaluation/star/score": {
            "result": 1,
            "data": {
                "contentQualityScore": 4.8,
                "cooperation": 4.8,
                "credit": 4.8,
                "comprehensive": 4.8,
            },
        },
        "/rest/web/commerce/live": {
            "result": 1,
            "data": {
                "liveCnt": 0,
                "liveWatchCntMedian": 0,
                "liveMaxOnlineCntMedian": 0,
                "goodsCnt": 0,
                "goodsGraph": [],
                "duration": 0,
            },
        },
    }


@pytest.mark.asyncio
async def test_all_modules_return_exactly_their_expected_fields() -> None:
    adapter = FakeAdapter(responses())
    for module in adapter.registry.modules:
        observation = await adapter.collect_module(module.key, creator(), ctx())
        assert [field.field_key for field in observation.fields] == list(
            adapter.module_fields[module.key]
        )
        assert observation.expected_fields == adapter.module_fields[module.key]
        assert observation.coverage_gaps == []


@pytest.mark.asyncio
async def test_live_module_keeps_no_data_and_collected_apart() -> None:
    adapter = FakeAdapter(responses())
    observation = await adapter.collect_module("live", creator(), ctx())
    by_key = {field.field_key: field for field in observation.fields}
    assert by_key["live.max_online"].status == FieldStatus.COLLECTED
    assert by_key["live.max_online"].value is not None
    assert by_key["live.credit_score"].status == FieldStatus.NO_DATA
    assert by_key["live.credit_score"].value is None
    assert by_key["live.commerce_sessions"].status == FieldStatus.NO_DATA
    assert by_key["live.commerce_sessions"].raw_value is not None


@pytest.mark.asyncio
async def test_works_and_frequency_keep_all_items() -> None:
    adapter = FakeAdapter(responses())
    observation = await adapter.collect_module("works", creator(), ctx())
    by_key = {field.field_key: field for field in observation.fields}
    personal = by_key["live.personal_live_works"]
    assert personal.status == FieldStatus.COLLECTED
    assert personal.value is not None
    assert len(personal.value.data) == 1  # type: ignore[union-attr]
    frequency = by_key["live.live_frequency"]
    assert frequency.value is not None
    assert frequency.value.data["modes"]["month"]["items"][0]["value"] == 33  # type: ignore[index]


@pytest.mark.asyncio
async def test_index_query_empty_is_no_data_not_schema_failure() -> None:
    empty = {"result": 1, "errMsg": "查询为空", "starRadarGraphVO": None}
    empty_trend = {"result": 1, "errMsg": "查询为空", "starTrendGraphVO": None}
    data = responses()
    data["/rest/web/starIndex/starRadarGraph"] = empty
    data["/rest/web/starIndex/starTrendGraph"] = empty_trend
    adapter = FakeAdapter(data)
    observation = await adapter.collect_module("index", creator(), ctx())
    assert observation.complete
    assert observation.coverage_gaps == []
    assert [field.status for field in observation.fields] == [FieldStatus.NO_DATA] * 7


@pytest.mark.asyncio
async def test_index_malformed_payload_still_fails() -> None:
    data = responses()
    data["/rest/web/starIndex/starRadarGraph"] = {
        "result": 1,
        "errMsg": "",
        "starRadarGraphVO": None,
    }
    data["/rest/web/starIndex/starTrendGraph"] = {
        "result": 1,
        "errMsg": "",
        "starTrendGraphVO": None,
    }
    adapter = FakeAdapter(data)
    observation = await adapter.collect_module("index", creator(), ctx())
    assert not observation.complete
    assert [field.status for field in observation.fields] == [FieldStatus.FAILED] * 7


@pytest.mark.asyncio
async def test_works_failure_is_failed_not_silent_no_data() -> None:
    adapter = FakeAdapter(responses(), fail_path="/rest/web/star/starWorksInfo")
    observation = await adapter.collect_module("works", creator(), ctx())
    by_key = {field.field_key: field for field in observation.fields}
    assert by_key["live.personal_live_works"].status == FieldStatus.FAILED
    assert by_key["live.commercial_live_works"].status == FieldStatus.FAILED
    assert by_key["live.recent_live_works"].status == FieldStatus.FAILED
    assert by_key["live.live_frequency"].status == FieldStatus.COLLECTED
    assert not observation.complete


@pytest.mark.asyncio
async def test_review_pagination_collects_two_pages_and_dedupes() -> None:
    adapter = FakeAdapter(responses())
    observation = await adapter.collect_module("cooperation", creator(), ctx())
    by_key = {field.field_key: field for field in observation.fields}
    reviews = by_key["live.evaluation_reviews"]
    assert reviews.status == FieldStatus.COLLECTED
    data = reviews.value.data  # type: ignore[union-attr]
    assert data["total"] == 18
    assert data["collected"] == 18
    assert data["complete"] is True
    review_calls = [
        body["page"] for path, body in adapter.calls if path == "/rest/web/evaluation/star/list"
    ]
    assert review_calls == [1, 2]
    assert all(item["reviewer_label"] == "匿名评论" for item in data["items"])


@pytest.mark.asyncio
async def test_commerce_period_requests_are_separate_and_7d_stays_no_data() -> None:
    adapter = FakeAdapter(responses())
    observation = await adapter.collect_module("commerce", creator(), ctx())
    by_key = {field.field_key: field for field in observation.fields}
    assert by_key["live.commerce_7d"].status == FieldStatus.NO_DATA
    assert by_key["live.hot_brands"].status == FieldStatus.COLLECTED
    calls = [body["duration"] for path, body in adapter.calls if path == "/rest/web/commerce/live"]
    assert calls == [7, 30, 90]


@pytest.mark.asyncio
async def test_profile_failure_is_raised_for_basic_module() -> None:
    adapter = FakeAdapter(responses(), fail_path="/rest/web/star/starProfile")
    with pytest.raises(CollectorError):
        await adapter.collect_module("basic", creator(), ctx())
