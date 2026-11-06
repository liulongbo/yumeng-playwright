from xingtu.domain import FieldStatus
from xingtu.juxing_live_fields import (
    _iso_from_ms,
    failed_fields,
    parse_audience,
    parse_basic,
    parse_commerce_period,
    parse_cooperation,
    parse_fans_trend,
    parse_hot_brands,
    parse_index,
    parse_live,
    parse_works,
    redact_contact_text,
    review_key,
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
        "industryTag": [
            {"firstTagName": "通信", "secondTagName": ["号卡", "彩铃"]},
            {"firstTagName": "游戏", "secondTagName": ["角色扮演"]},
        ],
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
        "liveQuotedInfo": {"perHour": 29100000, "perDay": 75450000, "perGoods": 45400000},
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
        "trendData": {
            "30": [
                {"label": "20261006", "value": 37372930},
                {"label": "20261007", "value": 37380000},
            ],
            "90": [{"label": "20260807", "value": 36752095}],
        },
        "trendDiffData": {
            "30": [{"label": "20261007", "value": 7070}],
            "90": [{"label": "20260808", "value": 39304}],
        },
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
    commercial = {
        **item,
        "streamId": "15047054415",
        "caption": "聚星直播",
        "hasSkuInfo": False,
        "orderId": 1313921741704737653,
    }
    return {
        "personLiveWorks": [item],
        "adSocialLiveWorks": [commercial],
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
                "cityPercentage": [
                    {"label": "firstline", "value": 0.033, "tgi": 78},
                    {"label": "thirdline", "value": 0.296, "tgi": 125},
                ],
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


def review_row(
    timestamp: int, content: str, *, hidden: bool = True, name: str = "匿名评论"
) -> dict:
    return {
        "contentQualityScore": 5.0,
        "cooperation": 5.0,
        "credit": 5.0,
        "comprehensive": 5.0,
        "productName": name,
        "promotionType": 2,
        "content": content,
        "timestamp": timestamp,
        "hiddenName": hidden,
        "haveAgent": False,
    }


def test_basic_parses_tags_industry_and_verified_info() -> None:
    parsed = parse_basic("52022133", profile())
    assert parsed.fields["industry_labels"].value == [
        "通信-号卡",
        "通信-彩铃",
        "游戏-角色扮演",
    ]
    assert parsed.fields["content_type_labels"].value == ["游戏", "MOBA"]
    assert parsed.fields["verified_info"].value == "快手2025百大主播"
    assert parsed.fields["creator_type_label"].status == FieldStatus.NO_DATA
    assert parsed.fields["content_form_labels"].status == FieldStatus.NO_DATA


def test_live_distinguishes_max_online_from_expected_max_and_keeps_quotes_separate() -> None:
    parsed = parse_live(profile(), works(), {"data": {"liveCnt": 0, "liveCnt2": 0}})
    assert parsed.fields["live.max_online"].value == 129037
    assert parsed.fields["live.expect_max_online"].value == 52357
    assert parsed.fields["live.credit_score"].status == FieldStatus.NO_DATA
    assert parsed.fields["live.credit_score"].raw is None
    quotes = parsed.fields["live.quote_details"].value
    assert [(quote["price_type"], quote["price_yuan"]) for quote in quotes] == [
        (1, 29100),
        (2, 75450),
        (3, 45400),
    ]
    assert parsed.fields["live.accept_order_rate_30d"].value == 0.5641
    assert parsed.fields["live.completed_orders_90d"].value == 60
    # commerce 7d all zero is a platform no-data state, not a real 0.
    assert parsed.fields["live.commerce_sessions"].status == FieldStatus.NO_DATA
    assert (
        "PLATFORM_ZERO_DISPLAYED_AS_NO_DATA"
        == parsed.fields["live.commerce_sessions"].failure_reason
    )


def test_business_period_null_values_are_no_data_not_zero() -> None:
    value = profile()
    value["liveBusinessReport"] = {
        "advertiserFirstIndustries": [],
        "acceptOrderRateData": {"30": None, "90": None},
        "completeOrderRateData": {"30": None, "90": None},
        "completeOrderCntData": {"30": 0, "90": 0},
    }
    parsed = parse_live(value, works(), None)
    for key in (
        "live.accept_order_rate_30d",
        "live.complete_order_rate_30d",
        "live.completed_orders_30d",
        "live.accept_order_rate_90d",
        "live.complete_order_rate_90d",
        "live.completed_orders_90d",
    ):
        assert parsed.fields[key].status == FieldStatus.NO_DATA
        assert parsed.fields[key].value is None


def test_fans_trend_keeps_30_and_90_series_and_dates_separate() -> None:
    parsed = parse_fans_trend(profile())
    trend_30 = parsed.fields["live.follower_trend_30d"].value
    trend_90 = parsed.fields["live.follower_trend_90d"].value
    assert trend_30["period_days"] == 30
    assert trend_30["total_series"][0]["date"] == "2026-10-06"
    assert trend_30["increment_series"][0]["value"] == 7070
    assert trend_90["period_days"] == 90
    assert parsed.fields["live.follower_growth_rate_30d"].value == 0.0004


def test_index_keeps_current_and_same_fans_average_without_faking_composite() -> None:
    radar = {
        "starRadarGraphVO": {
            "starIndexCurrent": [
                {"label": "starIndexCurr", "value": 81.6},
                {"label": "addFansIndexCurr", "value": 92.09},
                {"label": "performancePriceIndexCurr", "value": 49.48},
                {"label": "createIndexCurr", "value": 89.92},
                {"label": "bizActiIndexCurr", "value": 89.72},
                {"label": "coopIndexCurr", "value": 94.0},
            ],
            "starIndexAvg": [
                {"label": "addFansIndexAvg", "value": 91.1},
                {"label": "performancePriceAvg", "value": 59.63},
            ],
        }
    }
    trend = {
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
                {
                    "label": "starIndexHist",
                    "value": [
                        {"label": "202606", "value": 0.0},
                        {"label": "202607", "value": 0.0},
                    ],
                }
            ],
        }
    }
    parsed = parse_index(radar, trend)
    dimensions = parsed.fields["live.index_dimensions"].value
    assert dimensions["current"][0]["label"] == "达人指数"
    assert dimensions["missing_avg_dimensions"] == [
        "bizActiIndex",
        "coopIndex",
        "createIndex",
        "starIndex",
    ]
    assert parsed.fields["live.index_industry_rank"].value == 30538
    assert parsed.fields["live.index_industry_percent"].value == 0.7832
    assert parsed.fields["live.index_fans_rank"].value == 64
    assert parsed.fields["live.index_trend"].value["all_zero"] is True


def test_works_keep_all_items_and_live_frequency_modes() -> None:
    frequency = {
        "data": {
            "starWorkPlayMonthInfo": {"9": 33, "10": 48, "11": 9},
            "starWorkPlayWeekInfo": {"0": 15, "1": 14},
            "starWorkPlayHourInfo": {"19": 41, "12": 35},
        }
    }
    parsed = parse_works(works(), frequency)
    personal = parsed.fields["live.personal_live_works"].value
    commercial = parsed.fields["live.commercial_live_works"].value
    assert len(personal) == 1 and len(commercial) == 1
    assert personal[0]["stream_id"] == "15046311215"
    assert personal[0]["has_sku_info"] is True
    assert personal[0]["duration_seconds"] == 5523
    assert commercial[0]["order_id"] == "1313921741704737653"
    frequency_value = parsed.fields["live.live_frequency"].value
    assert frequency_value["modes"]["month"]["items"][0] == {
        "key": "9",
        "label": "9月",
        "value": 33,
    }
    assert frequency_value["modes"]["week"]["items"][0]["label"] == "周日"
    assert frequency_value["modes"]["hour"]["items"][0]["label"] == "12时"


def test_audience_corrects_city_key_swap_and_marks_summary_only_device_type() -> None:
    parsed = parse_audience(portrait(), viewer_device_tags=["安卓设备为主，占比67.5%"])
    viewer = parsed.fields["live.viewer_portrait"].value
    fan = parsed.fields["live.fan_portrait"].value
    assert viewer["city_tier"][1] == {
        "raw_label": "thirdline",
        "label": "三线",
        "value": 0.296,
        "tgi": 125,
    }
    assert viewer["city"][0]["label"] == "重庆"
    assert viewer["province"][0]["label"] == "广东"
    assert viewer["availability"]["device_type"] == "SUMMARY_ONLY"
    assert fan["interest"][0]["label"] == "运动"
    assert viewer["interest"] == []


def test_commerce_7d_zero_is_no_data_but_30d_values_are_collected() -> None:
    zero = parse_commerce_period(
        7,
        {
            "data": {
                "liveCnt": 0,
                "liveWatchCntMedian": 0,
                "liveMaxOnlineCntMedian": 0,
                "goodsCnt": 0,
                "goodsGraph": [],
                "duration": 0,
            }
        },
    )
    assert zero.status == FieldStatus.NO_DATA
    assert zero.raw is not None
    positive = parse_commerce_period(
        30,
        {
            "data": {
                "liveCnt": 4,
                "liveWatchCntMedian": 2313723,
                "liveMaxOnlineCntMedian": 45708,
                "goodsCnt": 14,
                "goodsGraph": [{"range": "100+", "cnt": 77}],
                "duration": 30,
            }
        },
    )
    assert positive.status == FieldStatus.COLLECTED
    assert positive.value["period_days"] == 30
    assert positive.value["goods_graph"] == [{"range": "100+", "count": 77}]


def test_hot_brands_and_categories_are_structured() -> None:
    parsed = parse_hot_brands(profile())
    assert parsed.fields["live.hot_brands"].value[0]["title"] == "王者荣耀"
    assert parsed.fields["live.hot_categories"].value[0]["title"] == "其他"


def test_evaluation_total_zero_hides_summary_even_when_score_endpoint_returns_five() -> None:
    score = {
        "data": {
            "contentQualityScore": 5.0,
            "cooperation": 5.0,
            "credit": 5.0,
            "comprehensive": 5.0,
        }
    }
    page = {"data": {"data": [], "total": 0, "pageNum": 0, "pageSize": 0}}
    parsed = parse_cooperation("451066", score, [page], review_complete=True)
    assert parsed.fields["live.evaluation_summary"].status == FieldStatus.NO_DATA
    assert parsed.fields["live.evaluation_total"].value == 0
    assert parsed.fields["live.evaluation_reviews"].status == FieldStatus.NO_DATA


def test_evaluation_pagination_dedupes_and_hides_product_name_for_hidden_reviews() -> None:
    rows = [
        review_row(1667193774469, "遵守脚本约定，联系顺畅", hidden=True, name="客户订单-A"),
        review_row(1656164841958, "未按脚本介绍", hidden=True),
    ]
    score = {
        "data": {
            "contentQualityScore": 4.8,
            "cooperation": 4.8,
            "credit": 4.8,
            "comprehensive": 4.8,
        }
    }
    page1 = {"data": {"data": rows, "total": 3}}
    page2 = {"data": {"data": [rows[0], review_row(1642583081203, "棒棒棒")], "total": 3}}
    parsed = parse_cooperation("9104", score, [page1, page2], review_complete=True)
    reviews = parsed.fields["live.evaluation_reviews"].value
    assert reviews["total"] == 3
    assert reviews["collected"] == 3
    assert reviews["items"][0]["reviewer_label"] == "匿名评论"
    assert "product_name" not in reviews["items"][0]
    assert len({item["review_key"] for item in reviews["items"]}) == 3
    assert not parsed.coverage_gaps


def test_evaluation_partial_pagination_is_reported_as_incomplete() -> None:
    score = {"data": {"comprehensive": 4.8}}
    page = {"data": {"data": [review_row(1667193774469, "")], "total": 18}}
    parsed = parse_cooperation("9104", score, [page], review_complete=False)
    assert "REVIEW_PAGINATION_INCOMPLETE" in parsed.coverage_gaps
    assert parsed.fields["live.evaluation_reviews"].value["complete"] is False


def test_review_key_is_stable_and_review_content_redacts_contacts() -> None:
    row = review_row(1667193774469, "联系 13800138000 或微信 abcdef", hidden=False, name="品牌")
    assert review_key("9104", row) == review_key("9104", dict(row))
    redacted, changed = redact_contact_text("联系 13800138000 或微信 abcdef")
    assert changed is True
    assert "13800138000" not in redacted
    parsed = parse_cooperation(
        "9104",
        {"data": {"comprehensive": 5.0}},
        [{"data": {"data": [{**row, "content": "联系 13800138000"}], "total": 1}}],
        review_complete=True,
    )
    item = parsed.fields["live.evaluation_reviews"].value["items"][0]
    assert item["content_redacted"] is True
    assert "13800138000" not in item["content"]


def test_failed_fields_are_explicit() -> None:
    parsed = failed_fields(["live.a", "live.b"], "HTTP_500")
    assert set(parsed.fields) == {"live.a", "live.b"}
    assert all(field.status == FieldStatus.FAILED for field in parsed.fields.values())


def test_out_of_range_timestamp_is_missing_not_an_exception() -> None:
    assert _iso_from_ms(10**19) is None
    assert _iso_from_ms(1793482386000) is not None


def test_scores_survive_a_failed_review_list() -> None:
    # The score panel and the review list are separate requests.  When the list fails the scores
    # are still real data; only the review total is unknown, so the summary must stay COLLECTED
    # with total_reviews=None instead of being downgraded to NO_DATA.
    parsed = parse_cooperation(
        "451066",
        {"data": {"comprehensive": 5.0, "contentQualityScore": 4.8}},
        [],
        review_complete=False,
        page_error="REVIEWS_UNAVAILABLE",
    )
    summary = parsed.fields["live.evaluation_summary"]
    assert summary.status == FieldStatus.COLLECTED
    assert summary.value["total_reviews"] is None
    assert summary.value["comprehensive"] == 5.0
    assert parsed.fields["live.evaluation_total"].status == FieldStatus.NO_DATA


def test_failed_review_list_does_not_invent_a_total() -> None:
    page = {
        "data": {
            "data": [review_row(1667193774469, "遵守脚本约定", hidden=False)],
            "pageNum": 1,
        }
    }
    parsed = parse_cooperation("451066", None, [page], review_complete=False)
    assert parsed.fields["live.evaluation_total"].status == FieldStatus.NO_DATA
    assert parsed.fields["live.evaluation_reviews"].value["total"] is None
