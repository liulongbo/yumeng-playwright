from __future__ import annotations

from xingtu.xingtu_live_detail import (
    MISSING_NON_ECOM,
    MISSING_NON_STAR,
    _iso_from_unix,
    build_audience,
    build_basic_extra,
    build_calendar,
    build_latest,
    build_overview_field,
    build_pricing,
    build_rooms,
    clean_wechat,
    duration_metric,
    number_metric,
    range_metric,
    redact_contact,
)

BASE = {"status_code": 0, "status_message": ""}


def payload(**values):
    return {"base_resp": BASE, **values}


def test_number_metric_keeps_raw_and_approximate_bound():
    metric = number_metric("1.7w", "count")
    assert metric["status"] == "COLLECTED"
    assert metric["value"] == "17000"
    assert metric["bound"] == "approximate"
    assert metric["raw"] == "1.7w"


def test_ratio_metric_handles_percent_and_decimal():
    assert number_metric("13.9%", "ratio")["value"] == "0.139"
    assert number_metric(0.1392, "ratio")["value"] == "0.1392"
    assert number_metric("-", "ratio")["status"] == "NOT_PROVIDED"


def test_range_metric_preserves_interval():
    metric = range_metric("2w~20w")
    assert metric["status"] == "COLLECTED"
    assert metric["range"] == {"min": "20000", "max": "200000", "unit": "yuan"}
    assert metric["bound"] == "approximate"
    assert metric["value"] is None


def test_zero_is_collected_not_missing():
    metric = number_metric("0", "count")
    assert metric["status"] == "COLLECTED"
    assert metric["value"] == "0"


def test_duration_above_one_day_is_flagged_not_converted():
    metric = duration_metric(653006)
    assert metric["status"] == "COLLECTED"
    assert metric["value"] == "653006"
    assert metric["unit_confidence"] == "ambiguous"


def test_build_pricing_only_keeps_live_services_and_modes():
    data = build_pricing(
        payload(
            price_info=[
                {
                    "desc": "品牌营销专场（按天）",
                    "task_category": 6,
                    "video_type": 56,
                    "price": 6000,
                    "origin_price": 6000,
                    "settlement_type": 2,
                },
                {
                    "desc": "电商带货拼场",
                    "task_category": 6,
                    "video_type": 58,
                    "price": 600,
                },
                {
                    "desc": "电商带货专场",
                    "task_category": 6,
                    "video_type": 57,
                    "price": 3100,
                },
                {
                    "desc": "短视频报价",
                    "task_category": 2,
                    "video_type": 1,
                    "price": 100,
                },
            ]
        )
    )
    assert data is not None
    assert [item["pricing_mode"] for item in data["services"]] == [
        "per_day",
        "per_goods",
        "per_hour",
    ]
    assert data["services"][0]["price"]["value"] == "6000"
    assert data["currency"] == "CNY"


def test_build_overview_keeps_calibres_separate():
    captures = [
        {
            "live_type": "general",
            "period": 30,
            "flow_type": 1,
            "only_star_order": False,
            "payload": payload(
                live_room_statistics={"room_cnt": "30", "acu": "270", "watch_duration_avg": 95},
                live_ecom_statistics={"ecom_live_product_num": "3"},
                live_convert_statistics={"ctr_avg": 0.139},
            ),
            "path": "/gw/api/aggregator/get_author_live_statistics",
        },
        {
            "live_type": "general",
            "period": 90,
            "flow_type": 0,
            "only_star_order": True,
            "payload": payload(
                live_room_statistics={"room_cnt": "86", "acu": "543"},
                live_convert_statistics={},
            ),
            "path": "/gw/api/aggregator/get_author_live_statistics",
        },
    ]
    data = build_overview_field(captures, live_type="general")
    assert data is not None
    assert data["request_live_type"] == 1
    assert set(data["calibres"]) == {
        "period_30_flow_1_star_0",
        "period_90_flow_0_star_1",
    }
    first = data["calibres"]["period_30_flow_1_star_0"]
    second = data["calibres"]["period_90_flow_0_star_1"]
    assert first["excluded_marketing"] is True
    assert first["interpretation"]["room_cnt"]["value"] == "30"
    assert second["excluded_marketing"] is False
    assert second["interpretation"]["room_cnt"]["value"] == "86"
    assert second["groups"]["convert"] == {}
    assert "convert_note" in second["groups"]


def test_build_calendar_groups_days_in_shanghai():
    data = build_calendar(
        [
            {
                "year": 2026,
                "month": 11,
                "flow_type": 1,
                "only_star_order": False,
                "payload": payload(
                    live_rooms=[
                        {
                            "room_id": "1",
                            "title": "A",
                            "start_time": "1793482386",
                            "end_time": "1793485415",
                            "acu": "108",
                        }
                    ],
                    highest_live_room={"room_id": "1", "start_time": "1793482386"},
                    latest_live_room={"room_id": "1", "start_time": "1793482386"},
                ),
                "path": "/gw/api/aggregator/get_author_peroidic_live_analysis",
            }
        ],
        live_type="general",
    )
    assert data is not None
    assert data["months"][0]["month_label"] == "2026-11"
    assert data["months"][0]["days"][0]["date"] == "2026-11-01"
    assert data["months"][0]["room_count"] == 1


def test_build_latest_keeps_series_values():
    data = build_latest(
        payload(
            latest_live_rooms=[
                {
                    "room_id": "1",
                    "start_time": "1793482386",
                    "watch_cnt": "5522",
                    "acu": "108",
                    "pcu": "186",
                },
                {
                    "room_id": "2",
                    "start_time": "1793396127",
                    "watch_cnt": "4956",
                    "acu": "144",
                    "pcu": "233",
                },
            ]
        ),
        live_type="general",
    )
    assert data is not None
    assert data["window"] == 2
    assert data["series"]["watch_cnt"][0]["value"] == "5522"
    assert data["series"]["acu"][1]["value"] == "144"


def test_build_rooms_distinguishes_non_star_and_non_ecom():
    data = build_rooms(
        list_pages=[
            {
                "page": 1,
                "payload": payload(
                    item_ids=["1", "2"],
                    pagination={"has_more": False, "limit": 10, "page": 1, "total_count": 2},
                ),
            }
        ],
        room_items={
            "1": {
                "room_id": "1",
                "title": "ecom",
                "start_time": "1793482386",
                "end_time": "1793485415",
                "acu": "108",
                "ctr": 0,
                "gmv_range": "0",
                "is_star_order": True,
                "ecom_live_product_num": "1",
                "avg_ecom_product_price_range": "100 ~ 250",
            },
            "2": {
                "room_id": "2",
                "title": "other",
                "start_time": "1793396127",
                "end_time": "1793399000",
                "acu": "144",
                "ctr": None,
                "gmv_range": "0",
                "is_star_order": False,
                "ecom_live_product_num": None,
            },
        },
        latest_types={"1": "ecom"},
    )
    assert data is not None
    rows = {row["room_id"]: row for row in data["rows"]}
    assert rows["1"]["live_type"] == "ecom"
    assert rows["1"]["metrics"]["ctr"]["status"] == "COLLECTED"
    assert rows["1"]["metrics"]["gmv_range"]["status"] == "COLLECTED"
    assert rows["2"]["live_type"] is None
    assert rows["2"]["metrics"]["ctr"]["reason"] == MISSING_NON_STAR
    assert rows["2"]["metrics"]["gmv_range"]["reason"] == MISSING_NON_ECOM


def test_build_audience_computes_percent_and_keeps_counts():
    data = build_audience(
        payload(
            distributions=[
                {
                    "type": 1,
                    "type_display": "性别分布",
                    "distribution_list": [
                        {"distribution_key": "男", "distribution_value": "9588"},
                        {"distribution_key": "女", "distribution_value": "39372"},
                    ],
                },
                {
                    "type": 4,
                    "type_display": "省份分布",
                    "distribution_list": [
                        {"distribution_key": "广东", "distribution_value": "3092"},
                        {"distribution_key": "江苏", "distribution_value": "3506"},
                    ],
                },
            ]
        ),
        live_type="general",
        crowd_type="fans",
        request_crowd_type=2,
    )
    assert data is not None
    gender = data["distributions"]["gender"]
    assert gender["total"] == "48960"
    assert gender["items"][0]["count"] == "9588"
    assert round(gender["items"][0]["percent"], 2) == 19.58
    province = data["distributions"]["province"]
    assert province["top10"][0]["key"] == "江苏"


def test_build_basic_extra_tags_and_redaction():
    data = build_basic_extra(
        payload(
            unique_id="34976739532",
            live_labels_v2={"游戏": ["语言互动"]},
            live_order_labels={"教育": []},
        ),
        payload(self_intro="合作请联系 13800138000 微信 abc12345"),
    )
    assert data["douyin_id"] == "34976739532"
    assert data["content_tags"] == ["语言互动"]
    assert data["business_order_types"] == ["教育"]
    assert "13800138000" not in (data["introduction"] or "")
    assert "abc12345" not in (data["introduction"] or "")
    assert redact_contact("正常介绍") == "正常介绍"


def test_clean_wechat_accepts_id_and_rejects_icon_text() -> None:
    # Finite synthetic values only: the real sample value is contact information and must never be
    # written back into tests, reports or logs (see LIVE-03-wechat evidence).
    assert clean_wechat("wx_example_001") == "wx_example_001"
    assert clean_wechat(" 13800138000 \n") == "13800138000"
    assert clean_wechat("复制") is None
    assert clean_wechat("暂无数据") is None
    assert clean_wechat("") is None
    assert clean_wechat(None) is None


def test_millisecond_or_out_of_range_timestamp_degrades_instead_of_raising() -> None:
    # A millisecond value or an out-of-range epoch must not escape as ValueError/OverflowError:
    # that aborted the whole creator/task instead of classifying one field.
    assert _iso_from_unix(1793482386000) == (None, None)
    assert _iso_from_unix(10**19) == (None, None)
    assert _iso_from_unix("not-a-number") == (None, None)
