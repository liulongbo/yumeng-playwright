"""Parsing and normalisation for the Kuaishou Juxing live creator detail page.

The functions here are deliberately free of Playwright and persistence concerns.  The adapter
replays the already-registered page requests and hands the JSON payloads to these functions; the
functions decide what was collected, what the platform explicitly left empty, and what the platform
displayed as a dash/no-data state.  Keeping this layer pure makes the field rules testable without a
browser and keeps the adapter limited to request orchestration.

Source paths (verified 2026-11-05 against the real live detail page):

* ``starProfile.starProfile``        basic identity, overview, quotes, fan growth, cooperation
* ``starWorksInfo.starWorksInfo``           personal/commercial live works, recent 15, live report
* ``listPortrait.data``                     viewer and fan portrait distributions
* ``starRadarGraph.starRadarGraphVO``       index score, six dimensions, same-fans-segment averages
* ``starTrendGraph.starTrendGraphVO``       index history, industry/same-fans rank and percentage
* ``evaluation/star/score.data``            evaluation summary
* ``evaluation/star/list.data``             evaluation total and page rows
* ``commerce/live.data``                    live commerce metrics and goods graph per period
* ``queryVideoPlayCnt.data``                monthly/weekly/hourly live frequency

The platform has a few traps that are encoded here:

* ``livePcuCnt`` is the displayed "最高在线人数"; ``liveMaxExpectOnlineViewer`` is the separate
  "预期最高在线人数".
* ``creditScore`` (near-30-day credit) is not ``evaluation.credit`` (customer evaluation credit).
* ``cityPercentage`` is actually the city-tier distribution while ``cityLevelPercentage`` is the
  city-name distribution.  Semantic keys below are named for the UI meaning and retain the raw key.
* ``commerce/live`` returns all-zero rows for a period with no commerce activity; the page renders
  those as "-" and "暂无带货分析数据".  Zeros are preserved in the raw value and the field is
  ``NO_DATA`` rather than a real 0.
* Review rows have no platform id and ``pageNum``/``pageSize`` come back as 0; pagination is driven
  by ``total`` and the number of returned rows, and a stable key is derived from the row content.
* A review whose ``hiddenName`` is true must never persist the raw ``productName`` (it can contain
  order/client details); it is exposed as "匿名评论".
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from .domain import FieldStatus

SHANGHAI = ZoneInfo("Asia/Shanghai")
REVIEW_PAGE_SIZE = 10
REVIEW_PAGE_LIMIT = 50

# Platform fields that are not part of the requested business modules.  In particular
# ``introduction``/``businessPhone`` can contain contact details and are never persisted.
_CONTACT_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_CONTACT_SOCIAL = re.compile(r"(?i)(微信|vx|v信|商务合作|合作联系)\s*[:：]?\s*[A-Za-z0-9_-]{4,}")

_CITY_TIER_LABELS = {
    "firstline": "一线",
    "newfirstline": "新一线",
    "secondline": "二线",
    "thirdline": "三线",
    "fourthline": "四线",
    "fifthline": "五线",
}
_CITY_TIER_KEYS = set(_CITY_TIER_LABELS)

# Page selector exposes these six dimensions; the trend response also contains four additional
# video-era series which are stored but not offered by the live page selector.
_INDEX_DIMENSIONS = {
    "starIndex": "达人指数",
    "addFansIndex": "涨粉指数",
    "performancePriceIndex": "性价比",
    "createIndex": "影响力",
    "bizActiIndex": "商业活跃度",
    "coopIndex": "合作指数",
    "developIndex": "发展指数",
    "spreadingIndex": "传播指数",
    "appealIndex": "吸引力指数",
    "businessIndex": "商业指数",
}
_INDEX_SELECTABLE = [
    "starIndex",
    "addFansIndex",
    "performancePriceIndex",
    "createIndex",
    "bizActiIndex",
    "coopIndex",
]
_QUOTE_PAGE_LABELS = {
    1: "按小时/1小时",
    2: "按天/1天",
    3: "按商品/1个商品(拼场直播)",
}


@dataclass(frozen=True)
class ParsedField:
    """One field ready for the adapter's ``FieldObservation`` construction."""

    key: str
    status: FieldStatus
    value: Any = None
    raw: Any = None
    unit: str | None = None
    period: str | None = None
    path: str = ""
    failure_reason: str | None = None
    structured: bool = False


@dataclass
class ParsedModule:
    fields: dict[str, ParsedField] = field(default_factory=dict)
    coverage_gaps: list[str] = field(default_factory=list)


def _json_raw(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _field(
    key: str,
    value: Any,
    *,
    path: str,
    unit: str | None = None,
    period: str | None = None,
    structured: bool = False,
) -> ParsedField:
    return ParsedField(
        key=key,
        status=FieldStatus.COLLECTED,
        value=value,
        raw=value,
        unit=unit,
        period=period,
        path=path,
        structured=structured,
    )


def _no_data(
    key: str,
    *,
    path: str,
    raw: Any = None,
    reason: str | None = None,
    unit: str | None = None,
    period: str | None = None,
) -> ParsedField:
    return ParsedField(
        key=key,
        status=FieldStatus.NO_DATA,
        raw=raw,
        unit=unit,
        period=period,
        path=path,
        failure_reason=reason,
    )


def failed_field(key: str, reason: str, *, path: str = "response") -> ParsedField:
    return ParsedField(
        key=key,
        status=FieldStatus.FAILED,
        path=path,
        failure_reason=reason,
    )


def failed_fields(keys: list[str], reason: str) -> ParsedModule:
    return ParsedModule(fields={key: failed_field(key, reason) for key in keys})


def _record(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _number(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            parsed = Decimal(value.strip().replace(",", ""))
        except (InvalidOperation, ValueError):
            return None
        if not parsed.is_finite():
            return None
        return int(parsed) if parsed == parsed.to_integral() else float(parsed)
    return None


def _ratio(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    amount = float(number)
    if amount < 0 or amount > 1:
        # The live page's ratio leaves are decimal 0-1.  A value outside that range is not
        # silently scaled; the caller treats it as no usable value.
        return None
    return amount


def _tag_list(value: Any) -> list[str]:
    if isinstance(value, list):
        tags: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip() and item.strip() not in tags:
                tags.append(item.strip())
        return tags
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        return [part.strip() for part in re.split(r"[、,，/]", text) if part.strip()]
    return []


def _timestamp_ms(value: Any) -> int | None:
    number = _number(value)
    if number is None or number <= 0:
        return None
    return int(number)


def _iso_from_ms(value: Any) -> str | None:
    milliseconds = _timestamp_ms(value)
    if milliseconds is None:
        return None
    try:
        return datetime.fromtimestamp(milliseconds / 1000, tz=SHANGHAI).isoformat()
    except (ValueError, OSError, OverflowError):
        # Out-of-range platform timestamps must degrade to a missing value, never abort the module.
        return None


def _iso_date_from_label(value: Any) -> str | None:
    text = _text(value)
    if text is None or not re.fullmatch(r"\d{8}", text):
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").replace(tzinfo=SHANGHAI).date().isoformat()
    except ValueError:
        return None


def redact_contact_text(value: str) -> tuple[str, bool]:
    """Redact phone/social-contact patterns embedded in platform review text.

    Reviews are user-generated and may contain contact details.  The original text is not kept
    anywhere once a redaction happens; the returned flag lets the UI explain the redaction.
    """

    redacted = _CONTACT_PHONE.sub("[联系方式已脱敏]", value)
    redacted = _CONTACT_SOCIAL.sub(r"\1：[联系方式已脱敏]", redacted)
    return redacted, redacted != value


# --------------------------------------------------------------------------------------------
# basic
# --------------------------------------------------------------------------------------------


def parse_basic(creator_platform_id: str, profile: dict[str, Any]) -> ParsedModule:
    address = _text(profile.get("address")) or ""
    province, _, city = address.partition("-")
    content_type = _record(profile.get("contentTypeTag")) or {}
    content_type_labels: list[str] = []
    for value in (content_type.get("firstTagName"), content_type.get("secondTagName")):
        text = _text(value)
        if text and text not in content_type_labels:
            content_type_labels.append(text)
    content_form_labels: list[str] = []
    for form in _list(profile.get("contentFormTag")):
        item = _record(form)
        if not item:
            continue
        values: list[Any] = [item.get("firstTagName")]
        seconds = item.get("secondTagName")
        if isinstance(seconds, list):
            values.extend(seconds)
        elif seconds is not None:
            values.append(seconds)
        for value in values:
            text = _text(value)
            if text and text not in content_form_labels:
                content_form_labels.append(text)

    industry_labels: list[str] = []
    for tag in _list(profile.get("industryTag")):
        item = _record(tag)
        if not item:
            continue
        first = _text(item.get("firstTagName"))
        seconds = _list(item.get("secondTagName"))
        if first and seconds:
            for second in seconds:
                text = _text(second)
                label = f"{first}-{text}" if text else first
                if label not in industry_labels:
                    industry_labels.append(label)
        elif first and first not in industry_labels:
            industry_labels.append(first)
    if not industry_labels:
        industry_labels = _tag_list(profile.get("industryTagStr"))

    fields: dict[str, ParsedField] = {
        "platform_creator_id": _field(
            "platform_creator_id",
            _text(profile.get("userId")) or creator_platform_id,
            path="starProfile.userId",
        ),
        "platform_star_id": _field(
            "platform_star_id", _text(profile.get("starId")), path="starProfile.starId"
        ),
        "nickname": _field("nickname", _text(profile.get("name")), path="starProfile.name"),
        "avatar_uri": _field(
            "avatar_uri", _text(profile.get("headUrl")), path="starProfile.headUrl"
        ),
        "gender": _field("gender", _text(profile.get("gender")), path="starProfile.gender"),
        "followers": _field(
            "followers",
            _number(profile.get("fansNumber")),
            path="starProfile.fansNumber",
            unit="count",
        ),
        "creator_type_label": _field(
            "creator_type_label", _text(profile.get("starTagStr")), path="starProfile.starTagStr"
        ),
        "industry_labels": _field(
            "industry_labels", industry_labels, path="starProfile.industryTag"
        )
        if industry_labels
        else _no_data("industry_labels", path="starProfile.industryTag", raw=[]),
        "content_type_labels": _field(
            "content_type_labels", content_type_labels, path="starProfile.contentTypeTag"
        )
        if content_type_labels
        else _no_data("content_type_labels", path="starProfile.contentTypeTag", raw={}),
        "content_form_labels": _field(
            "content_form_labels", content_form_labels, path="starProfile.contentFormTag"
        )
        if content_form_labels
        else _no_data("content_form_labels", path="starProfile.contentFormTag", raw=[]),
        "mcn_name": _field("mcn_name", _text(profile.get("govName")), path="starProfile.govName"),
        "verified_info": _field(
            "verified_info", _text(profile.get("verifiedInfo")), path="starProfile.verifiedInfo"
        )
        if _text(profile.get("verifiedInfo"))
        else _no_data("verified_info", path="starProfile.verifiedInfo", raw=""),
        "province": _field("province", _text(province), path="starProfile.address")
        if _text(province)
        else _no_data("province", path="starProfile.address", raw=address),
        "city": _field("city", _text(city), path="starProfile.address")
        if _text(city)
        else _no_data("city", path="starProfile.address", raw=address),
    }
    # A field that is literally null must be NO_DATA, not a collected None.
    for key, parsed in list(fields.items()):
        if parsed.status == FieldStatus.COLLECTED and parsed.value is None:
            fields[key] = _no_data(key, path=parsed.path, raw=None)
    return ParsedModule(fields=fields)


# --------------------------------------------------------------------------------------------
# live overview / quotes / cooperation overview
# --------------------------------------------------------------------------------------------


def _quote_offers(profile: dict[str, Any]) -> list[dict[str, Any]]:
    fallback = _record(profile.get("liveQuotedInfo")) or {}
    offers: list[dict[str, Any]] = []
    raw_offers = _list(profile.get("priceShowInfo"))
    for item in raw_offers:
        offer = _record(item)
        if not offer or offer.get("businessLine") != 2:
            continue
        price_type = _number(offer.get("priceType"))
        raw_price = _number(offer.get("price"))
        if price_type is None or raw_price is None:
            continue
        price_yuan = int(Decimal(str(raw_price)) / Decimal(1000))
        original = _number(offer.get("originalPrice"))
        original_yuan = (
            int(Decimal(str(original)) / Decimal(1000)) if original is not None else None
        )
        offers.append(
            {
                "business_line": 2,
                "price_type": int(price_type),
                "price_type_name": _text(offer.get("priceTypeName")),
                "page_label": _QUOTE_PAGE_LABELS.get(int(price_type)),
                "price_raw": int(raw_price) if isinstance(raw_price, (int, float)) else raw_price,
                "price_yuan": price_yuan,
                "original_price_raw": original,
                "original_price_yuan": original_yuan,
                "price_start_ms": _number(offer.get("priceStartTimeMs")) or None,
                "price_end_ms": _number(offer.get("priceEndTimeMs")) or None,
                "currency": "CNY",
            }
        )
    if offers:
        return offers
    # The two live samples expose the same amounts through liveQuotedInfo.  Use it only when the
    # primary offer array is absent; the business type is still kept explicit.
    for price_type, key in (
        (1, "perHour"),
        (2, "perDay"),
        (3, "perGoods"),
    ):
        raw_price = _number(fallback.get(key))
        if raw_price is None:
            continue
        offers.append(
            {
                "business_line": 2,
                "price_type": price_type,
                "price_type_name": {
                    1: "直播按小时",
                    2: "直播按天",
                    3: "直播按商品数",
                }[price_type],
                "page_label": _QUOTE_PAGE_LABELS[price_type],
                "price_raw": raw_price,
                "price_yuan": int(Decimal(str(raw_price)) / Decimal(1000)),
                "original_price_raw": None,
                "original_price_yuan": None,
                "price_start_ms": None,
                "price_end_ms": None,
                "currency": "CNY",
            }
        )
    return offers


def _quote_map(offers: list[dict[str, Any]]) -> dict[int, int]:
    return {
        int(offer["price_type"]): int(offer["price_yuan"])
        for offer in offers
        if isinstance(offer.get("price_type"), int) and isinstance(offer.get("price_yuan"), int)
    }


def _business_period(
    report: dict[str, Any],
    period: int,
) -> tuple[ParsedField, ParsedField, ParsedField]:
    key = str(period)
    accept_data = report.get("acceptOrderRateData")
    complete_data = report.get("completeOrderRateData")
    count_data = report.get("completeOrderCntData")
    accept_raw = accept_data.get(key) if isinstance(accept_data, dict) else None
    complete_raw = complete_data.get(key) if isinstance(complete_data, dict) else None
    count_raw = count_data.get(key) if isinstance(count_data, dict) else None
    accept = _ratio(accept_raw)
    complete = _ratio(complete_raw)
    count = _number(count_raw)
    values = [accept, complete, count]
    all_empty = all(value in (None, 0) for value in values)
    suffix = f"{period}d"
    period_label = f"近{period}天"
    if all_empty:
        return (
            _no_data(
                f"live.accept_order_rate_{suffix}",
                path=f"starProfile.liveBusinessReport.acceptOrderRateData.{key}",
                raw=accept_raw,
                unit="ratio",
                period=period_label,
            ),
            _no_data(
                f"live.complete_order_rate_{suffix}",
                path=f"starProfile.liveBusinessReport.completeOrderRateData.{key}",
                raw=complete_raw,
                unit="ratio",
                period=period_label,
            ),
            _no_data(
                f"live.completed_orders_{suffix}",
                path=f"starProfile.liveBusinessReport.completeOrderCntData.{key}",
                raw=count_raw,
                unit="count",
                period=period_label,
            ),
        )
    return (
        _field(
            f"live.accept_order_rate_{suffix}",
            accept,
            path=f"starProfile.liveBusinessReport.acceptOrderRateData.{key}",
            unit="ratio",
            period=period_label,
        )
        if accept is not None
        else _no_data(
            f"live.accept_order_rate_{suffix}",
            path=f"starProfile.liveBusinessReport.acceptOrderRateData.{key}",
            raw=accept_raw,
            unit="ratio",
            period=period_label,
        ),
        _field(
            f"live.complete_order_rate_{suffix}",
            complete,
            path=f"starProfile.liveBusinessReport.completeOrderRateData.{key}",
            unit="ratio",
            period=period_label,
        )
        if complete is not None
        else _no_data(
            f"live.complete_order_rate_{suffix}",
            path=f"starProfile.liveBusinessReport.completeOrderRateData.{key}",
            raw=complete_raw,
            unit="ratio",
            period=period_label,
        ),
        _field(
            f"live.completed_orders_{suffix}",
            count,
            path=f"starProfile.liveBusinessReport.completeOrderCntData.{key}",
            unit="count",
            period=period_label,
        )
        if count is not None
        else _no_data(
            f"live.completed_orders_{suffix}",
            path=f"starProfile.liveBusinessReport.completeOrderCntData.{key}",
            raw=count_raw,
            unit="count",
            period=period_label,
        ),
    )


def _commerce_values(data: dict[str, Any] | None) -> dict[str, Any]:
    raw = data or {}
    return {
        "live_cnt": _number(raw.get("liveCnt")),
        "live_watch_cnt_median": _number(raw.get("liveWatchCntMedian")),
        "live_max_online_cnt_median": _number(raw.get("liveMaxOnlineCntMedian")),
        "goods_cnt": _number(raw.get("goodsCnt")),
        "goods_graph": [
            {
                "range": _text(item.get("range")),
                "count": _number(item.get("cnt")),
            }
            for item in _list(raw.get("goodsGraph"))
            if isinstance(item, dict)
        ],
        "duration": _number(raw.get("duration")),
    }


def _commerce_all_zero(values: dict[str, Any]) -> bool:
    return (
        values.get("live_cnt") in (None, 0)
        and values.get("live_watch_cnt_median") in (None, 0)
        and values.get("live_max_online_cnt_median") in (None, 0)
        and values.get("goods_cnt") in (None, 0)
        and not values.get("goods_graph")
    )


def _commerce_metric(
    key: str,
    member: str,
    data: dict[str, Any] | None,
    *,
    period: str,
) -> ParsedField:
    values = _commerce_values(data)
    raw_value = values.get(member)
    path = f"commerce/live.{member}"
    if _commerce_all_zero(values):
        return _no_data(
            key,
            path=path,
            raw=_record(data) or {},
            reason="PLATFORM_ZERO_DISPLAYED_AS_NO_DATA",
            unit="count",
            period=period,
        )
    if raw_value is None:
        return _no_data(key, path=path, raw=_record(data) or {}, unit="count", period=period)
    return _field(key, raw_value, path=path, unit="count", period=period)


def parse_live(
    profile: dict[str, Any],
    works: dict[str, Any] | None,
    commerce_seven: dict[str, Any] | None,
) -> ParsedModule:
    report = _record((works or {}).get("starWorkReport")) or {}
    offers = _quote_offers(profile)
    quote_map = _quote_map(offers)
    business = _record(profile.get("liveBusinessReport")) or {}
    commerce_data = _record((commerce_seven or {}).get("data")) or {}

    def scalar(
        key: str,
        value: Any,
        *,
        path: str,
        unit: str | None = None,
        period: str | None = None,
        zero_is_no_data: bool = False,
    ) -> ParsedField:
        number = _number(value)
        if number is None:
            return _no_data(key, path=path, raw=value, unit=unit, period=period)
        if zero_is_no_data and number == 0:
            return _no_data(
                key,
                path=path,
                raw=value,
                reason="PLATFORM_ZERO_DISPLAYED_AS_NO_DATA",
                unit=unit,
                period=period,
            )
        return _field(key, number, path=path, unit=unit, period=period)

    fields: dict[str, ParsedField] = {
        "platform_star_id": _field(
            "platform_star_id", _text(profile.get("starId")), path="starProfile.starId"
        ),
        "live.expect_viewer": scalar(
            "live.expect_viewer",
            profile.get("livePlayCntExpectancy"),
            path="starProfile.livePlayCntExpectancy",
            unit="count",
        ),
        "live.max_online": scalar(
            "live.max_online",
            profile.get("livePcuCnt"),
            path="starProfile.livePcuCnt",
            unit="count",
        ),
        "live.expect_cpm": scalar(
            "live.expect_cpm",
            profile.get("liveCpmExpectancy"),
            path="starProfile.liveCpmExpectancy",
            unit="cpm",
        ),
        "live.weekly_sessions": scalar(
            "live.weekly_sessions",
            profile.get("liveWeeklyTimesCnt"),
            path="starProfile.liveWeeklyTimesCnt",
            unit="count",
        ),
        "live.avg_people": scalar(
            "live.avg_people",
            profile.get("liveAvgPeopleNum"),
            path="starProfile.liveAvgPeopleNum",
            unit="count",
        ),
        "live.avg_like": scalar(
            "live.avg_like",
            profile.get("liveAvgLikeCnt"),
            path="starProfile.liveAvgLikeCnt",
            unit="count",
        ),
        "live.week_release": scalar(
            "live.week_release",
            report.get("liveWeekRelease"),
            path="starWorksInfo.starWorkReport.liveWeekRelease",
            unit="count",
        ),
        "live.interaction_rate": _field(
            "live.interaction_rate",
            _number(report.get("liveInteractionRate")),
            path="starWorksInfo.starWorkReport.liveInteractionRate",
        )
        if _number(report.get("liveInteractionRate")) is not None
        else _no_data(
            "live.interaction_rate",
            path="starWorksInfo.starWorkReport.liveInteractionRate",
            raw=report.get("liveInteractionRate"),
        ),
        "live.quote_hour": _field(
            "live.quote_hour",
            quote_map.get(1),
            path="starProfile.priceShowInfo[type=1]",
            unit="yuan",
        )
        if quote_map.get(1) is not None
        else _no_data(
            "live.quote_hour", path="starProfile.priceShowInfo[type=1]", raw=None, unit="yuan"
        ),
        "live.quote_day": _field(
            "live.quote_day",
            quote_map.get(2),
            path="starProfile.priceShowInfo[type=2]",
            unit="yuan",
        )
        if quote_map.get(2) is not None
        else _no_data(
            "live.quote_day", path="starProfile.priceShowInfo[type=2]", raw=None, unit="yuan"
        ),
        "live.quote_goods": _field(
            "live.quote_goods",
            quote_map.get(3),
            path="starProfile.priceShowInfo[type=3]",
            unit="yuan",
        )
        if quote_map.get(3) is not None
        else _no_data(
            "live.quote_goods",
            path="starProfile.priceShowInfo[type=3]",
            raw=None,
            unit="yuan",
        ),
        "live.quote_details": _field(
            "live.quote_details",
            offers,
            path="starProfile.priceShowInfo",
            structured=True,
        )
        if offers
        else _no_data("live.quote_details", path="starProfile.priceShowInfo", raw=[]),
        "live.expect_max_online": scalar(
            "live.expect_max_online",
            profile.get("liveMaxExpectOnlineViewer"),
            path="starProfile.liveMaxExpectOnlineViewer",
            unit="count",
        ),
        "live.credit_score": scalar(
            "live.credit_score",
            profile.get("creditScore"),
            path="starProfile.creditScore",
            unit="score",
            period="近30天",
        ),
        "live.cooperation_industries": _field(
            "live.cooperation_industries",
            _tag_list(business.get("advertiserFirstIndustries")),
            path="starProfile.liveBusinessReport.advertiserFirstIndustries",
        )
        if _tag_list(business.get("advertiserFirstIndustries"))
        else _no_data(
            "live.cooperation_industries",
            path="starProfile.liveBusinessReport.advertiserFirstIndustries",
            raw=[],
        ),
        "live.viewer_feature_tags": _field(
            "live.viewer_feature_tags",
            _tag_list(profile.get("viewerFeatureTag")),
            path="starProfile.viewerFeatureTag",
        )
        if _tag_list(profile.get("viewerFeatureTag"))
        else _no_data("live.viewer_feature_tags", path="starProfile.viewerFeatureTag", raw=[]),
        "live.viewer_device_tags": _field(
            "live.viewer_device_tags",
            _tag_list(profile.get("viewerDeviceTag")),
            path="starProfile.viewerDeviceTag",
        )
        if _tag_list(profile.get("viewerDeviceTag"))
        else _no_data("live.viewer_device_tags", path="starProfile.viewerDeviceTag", raw=[]),
        "live.viewer_area_tags": _field(
            "live.viewer_area_tags",
            _tag_list(profile.get("viewerAreaTag")),
            path="starProfile.viewerAreaTag",
        )
        if _tag_list(profile.get("viewerAreaTag"))
        else _no_data("live.viewer_area_tags", path="starProfile.viewerAreaTag", raw=[]),
        "live.commerce_sessions": _commerce_metric(
            "live.commerce_sessions", "live_cnt", commerce_data, period="近7天"
        ),
        "live.commerce_watch_median": _commerce_metric(
            "live.commerce_watch_median",
            "live_watch_cnt_median",
            commerce_data,
            period="近7天",
        ),
        "live.commerce_max_online_median": _commerce_metric(
            "live.commerce_max_online_median",
            "live_max_online_cnt_median",
            commerce_data,
            period="近7天",
        ),
        "live.commerce_goods": _commerce_metric(
            "live.commerce_goods", "goods_cnt", commerce_data, period="近7天"
        ),
    }
    for period in (30, 90):
        accept, complete, count = _business_period(business, period)
        fields[accept.key] = accept
        fields[complete.key] = complete
        fields[count.key] = count
    return ParsedModule(fields=fields)


# --------------------------------------------------------------------------------------------
# fans trend
# --------------------------------------------------------------------------------------------


def _fan_series(
    trend_data: dict[str, Any],
    diff_data: dict[str, Any],
    period: int,
) -> dict[str, Any] | None:
    key = str(period)
    total = _list(trend_data.get(key))
    diff = _list(diff_data.get(key))
    if not total and not diff:
        return None

    def points(rows: list[Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for row in rows:
            item = _record(row)
            if not item:
                continue
            label = _text(item.get("label"))
            value = _number(item.get("value"))
            if label is None or value is None:
                continue
            result.append(
                {
                    "raw_label": label,
                    "date": _iso_date_from_label(label),
                    "value": value,
                }
            )
        return result

    return {
        "period_days": period,
        "unit": "count",
        "total_series": points(total),
        "increment_series": points(diff),
        "source_note": "平台按日返回；总量与增量分别来自 trendData / trendDiffData",
    }


def parse_fans_trend(profile: dict[str, Any]) -> ParsedModule:
    trend_data = _record(profile.get("trendData")) or {}
    diff_data = _record(profile.get("trendDiffData")) or {}
    growth = _record(profile.get("fansIncreaseNum")) or {}
    fields: dict[str, ParsedField] = {}
    for period, rate_key in ((30, "fansIncreaseRateIn30"), (90, "fansIncreaseRateIn90")):
        suffix = f"{period}d"
        label = f"近{period}天"
        growth_raw = growth.get(str(period))
        growth_value = _number(growth_raw)
        fields[f"live.follower_growth_{suffix}"] = (
            _field(
                f"live.follower_growth_{suffix}",
                growth_value,
                path=f"starProfile.fansIncreaseNum.{period}",
                unit="count",
                period=label,
            )
            if growth_value is not None
            else _no_data(
                f"live.follower_growth_{suffix}",
                path=f"starProfile.fansIncreaseNum.{period}",
                raw=growth_raw,
                unit="count",
                period=label,
            )
        )
        rate_raw = profile.get(rate_key)
        rate_value = _ratio(rate_raw)
        fields[f"live.follower_growth_rate_{suffix}"] = (
            _field(
                f"live.follower_growth_rate_{suffix}",
                rate_value,
                path=f"starProfile.{rate_key}",
                unit="ratio",
                period=label,
            )
            if rate_value is not None
            else _no_data(
                f"live.follower_growth_rate_{suffix}",
                path=f"starProfile.{rate_key}",
                raw=rate_raw,
                unit="ratio",
                period=label,
            )
        )
        series = _fan_series(trend_data, diff_data, period)
        fields[f"live.follower_trend_{suffix}"] = (
            _field(
                f"live.follower_trend_{suffix}",
                series,
                path=f"starProfile.trendData.{period}+trendDiffData.{period}",
                unit="count",
                period=label,
                structured=True,
            )
            if series is not None
            else _no_data(
                f"live.follower_trend_{suffix}",
                path=f"starProfile.trendData.{period}+trendDiffData.{period}",
                raw={},
                unit="count",
                period=label,
            )
        )
    return ParsedModule(fields=fields)


# --------------------------------------------------------------------------------------------
# index
# --------------------------------------------------------------------------------------------


def _dimension_key(label: str, *, suffix: str) -> str | None:
    if not label.endswith(suffix):
        return None
    key = label[: -len(suffix)]
    # The radar's same-fans-segment average uses the shorter label
    # ``performancePriceAvg``; the current value uses ``performancePriceIndexCurr``.
    if key == "performancePrice":
        key = "performancePriceIndex"
    return key if key in _INDEX_DIMENSIONS else None


def _dimension_label(key: str) -> str:
    return _INDEX_DIMENSIONS.get(key, key)


def _index_points(rows: Any, *, suffix: str) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for row in _list(rows):
        item = _record(row)
        if not item:
            continue
        raw_label = _text(item.get("label"))
        value = _number(item.get("value"))
        if raw_label is None or value is None:
            continue
        key = _dimension_key(raw_label, suffix=suffix)
        if key is None:
            continue
        points.append(
            {
                "key": key,
                "raw_label": raw_label,
                "label": _dimension_label(key),
                "value": value,
            }
        )
    return points


def _rank_value(rows: Any, label: str) -> Any:
    for row in _list(rows):
        item = _record(row)
        if item and item.get("label") == label:
            return item.get("value")
    return None


def _trend_series(rows: Any) -> tuple[list[dict[str, Any]], bool]:
    series: list[dict[str, Any]] = []
    all_zero = True
    for row in _list(rows):
        item = _record(row)
        if not item:
            continue
        raw_label = _text(item.get("label"))
        points = _list(item.get("value"))
        if raw_label is None or not points:
            continue
        key = _dimension_key(raw_label, suffix="Hist")
        if key is None:
            continue
        values: list[dict[str, Any]] = []
        for point in points:
            entry = _record(point)
            if not entry:
                continue
            period = _text(entry.get("label"))
            value = _number(entry.get("value"))
            if period is None or value is None:
                continue
            if value != 0:
                all_zero = False
            values.append({"period": period, "value": value})
        if values:
            series.append(
                {
                    "key": key,
                    "raw_label": raw_label,
                    "label": _dimension_label(key),
                    "points": values,
                }
            )
    return series, all_zero


def parse_index(radar: dict[str, Any], trend: dict[str, Any]) -> ParsedModule:
    radar = _record(radar.get("starRadarGraphVO")) or {}
    trend = _record(trend.get("starTrendGraphVO")) or {}
    current = _index_points(radar.get("starIndexCurrent"), suffix="Curr")
    averages = _index_points(radar.get("starIndexAvg"), suffix="Avg")
    current_keys = {point["key"] for point in current}
    average_keys = {point["key"] for point in averages}
    score = next((point["value"] for point in current if point["key"] == "starIndex"), None)
    rank_industry = _number(_rank_value(trend.get("starIndexRank"), "bizStarRank"))
    rank_fans = _number(_rank_value(trend.get("starIndexRank"), "fansStarRank"))
    percent_industry_raw = _rank_value(trend.get("starIndexPercent"), "bizStarPercent")
    percent_fans_raw = _rank_value(trend.get("starIndexPercent"), "fansStarPercent")
    percent_industry = _ratio(percent_industry_raw)
    percent_fans = _ratio(percent_fans_raw)
    series, all_zero = _trend_series(trend.get("starIndexHistory"))
    fields: dict[str, ParsedField] = {
        "live.index_score": _field(
            "live.index_score",
            score,
            path="starRadarGraphVO.starIndexCurrent.starIndexCurr",
            unit="score",
        )
        if score is not None
        else _no_data(
            "live.index_score",
            path="starRadarGraphVO.starIndexCurrent.starIndexCurr",
            raw=None,
        ),
        "live.index_dimensions": _field(
            "live.index_dimensions",
            {
                "current": current,
                "same_fans_segment_avg": averages,
                "missing_avg_dimensions": sorted(current_keys - average_keys),
                "selectable": [key for key in _INDEX_SELECTABLE if key in current_keys],
                "same_fans_avg_scope": "同粉丝段均值",
                "note": "平台雷达没有综合指数的同粉段均值，未用 0 补造",
            },
            path="starRadarGraphVO.starIndexCurrent+starIndexAvg",
            structured=True,
        )
        if current or averages
        else _no_data(
            "live.index_dimensions",
            path="starRadarGraphVO.starIndexCurrent+starIndexAvg",
            raw={},
        ),
        "live.index_industry_rank": _field(
            "live.index_industry_rank",
            rank_industry,
            path="starTrendGraphVO.starIndexRank.bizStarRank",
            unit="count",
        )
        if rank_industry not in (None, 0)
        else _no_data(
            "live.index_industry_rank",
            path="starTrendGraphVO.starIndexRank.bizStarRank",
            raw=_rank_value(trend.get("starIndexRank"), "bizStarRank"),
            unit="count",
        ),
        "live.index_industry_percent": _field(
            "live.index_industry_percent",
            percent_industry,
            path="starTrendGraphVO.starIndexPercent.bizStarPercent",
            unit="ratio",
        )
        if percent_industry is not None
        else _no_data(
            "live.index_industry_percent",
            path="starTrendGraphVO.starIndexPercent.bizStarPercent",
            raw=percent_industry_raw,
            unit="ratio",
        ),
        "live.index_fans_rank": _field(
            "live.index_fans_rank",
            rank_fans,
            path="starTrendGraphVO.starIndexRank.fansStarRank",
            unit="count",
        )
        if rank_fans not in (None, 0)
        else _no_data(
            "live.index_fans_rank",
            path="starTrendGraphVO.starIndexRank.fansStarRank",
            raw=_rank_value(trend.get("starIndexRank"), "fansStarRank"),
            unit="count",
        ),
        "live.index_fans_percent": _field(
            "live.index_fans_percent",
            percent_fans,
            path="starTrendGraphVO.starIndexPercent.fansStarPercent",
            unit="ratio",
        )
        if percent_fans is not None
        else _no_data(
            "live.index_fans_percent",
            path="starTrendGraphVO.starIndexPercent.fansStarPercent",
            raw=percent_fans_raw,
            unit="ratio",
        ),
        "live.index_trend": _field(
            "live.index_trend",
            {
                "granularity": "month",
                "period_label": "近6个月",
                "series": series,
                "selectable": [
                    key for key in _INDEX_SELECTABLE if any(s["key"] == key for s in series)
                ],
                "all_zero": all_zero,
                "note": "平台返回的月度指数全部为 0 时保留原值并标记 all_zero，不伪造趋势",
            },
            path="starTrendGraphVO.starIndexHistory",
            structured=True,
        )
        if series
        else _no_data(
            "live.index_trend",
            path="starTrendGraphVO.starIndexHistory",
            raw=[],
        ),
    }
    return ParsedModule(fields=fields)


# --------------------------------------------------------------------------------------------
# works and live frequency
# --------------------------------------------------------------------------------------------


def _work_item(item: dict[str, Any], collection_kind: str) -> dict[str, Any] | None:
    stream_id = _text(item.get("streamId"))
    if stream_id is None:
        return None
    return {
        "stream_id": stream_id,
        "collection_kind": collection_kind,
        "title": _text(item.get("caption")),
        "cover_url": _text(item.get("coverUrl")),
        "media_url": _text(item.get("url")),
        "media_url_kind": "playback_signed",
        "published_at": _iso_from_ms(item.get("releaseTimeMillis")),
        "published_at_ms": _timestamp_ms(item.get("releaseTimeMillis")),
        "duration_seconds": (
            int(Decimal(str(_number(item.get("durationTimeMillis")))) / Decimal(1000))
            if _number(item.get("durationTimeMillis")) is not None
            else None
        ),
        "duration_ms": _timestamp_ms(item.get("durationTimeMillis")),
        "view_count": _number(item.get("viewCnt")),
        "peak_online_count": _number(item.get("peakCnt")),
        "like_count": _number(item.get("likeCnt")),
        "comment_count": _number(item.get("commentCnt")),
        "share_count": _number(item.get("forwardCnt")),
        "has_sku_info": bool(item.get("hasSkuInfo")),
        "order_id": str(item.get("orderId")) if item.get("orderId") is not None else None,
    }


def _work_rows(rows: Any, collection_kind: str) -> tuple[list[dict[str, Any]], bool]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicate = False
    missing_identity = False
    for row in _list(rows):
        item = _record(row)
        if not item:
            continue
        parsed = _work_item(item, collection_kind)
        if parsed is None:
            missing_identity = True
            continue
        if parsed["stream_id"] in seen:
            duplicate = True
            continue
        seen.add(parsed["stream_id"])
        result.append(parsed)
    return result, missing_identity or duplicate


def _frequency_items(raw: Any, *, labels: dict[str, str] | None = None) -> list[dict[str, Any]]:
    data = _record(raw) or {}
    items: list[dict[str, Any]] = []
    for key, value in data.items():
        number = _number(value)
        if number is None:
            continue
        label = labels.get(str(key), str(key)) if labels else str(key)
        items.append({"key": str(key), "label": label, "value": number})
    return items


def parse_works(
    works: dict[str, Any],
    frequency_payload: dict[str, Any] | None,
) -> ParsedModule:
    personal, personal_gap = _work_rows(works.get("personLiveWorks"), "personal")
    commercial, commercial_gap = _work_rows(works.get("adSocialLiveWorks"), "commercial")
    recent, recent_gap = _work_rows(works.get("recentLiveWorks"), "recent")
    coverage: list[str] = []
    if personal_gap:
        coverage.append("PERSONAL_WORK_IDENTITY_OR_DUPLICATE")
    if commercial_gap:
        coverage.append("COMMERCIAL_WORK_IDENTITY_OR_DUPLICATE")
    if recent_gap:
        coverage.append("RECENT_WORK_IDENTITY_OR_DUPLICATE")
    fields: dict[str, ParsedField] = {
        "live.personal_live_works": _field(
            "live.personal_live_works",
            personal,
            path="starWorksInfo.personLiveWorks",
            period="近30天",
            structured=True,
        )
        if personal
        else _no_data(
            "live.personal_live_works",
            path="starWorksInfo.personLiveWorks",
            raw=[],
            period="近30天",
        ),
        "live.commercial_live_works": _field(
            "live.commercial_live_works",
            commercial,
            path="starWorksInfo.adSocialLiveWorks",
            structured=True,
        )
        if commercial
        else _no_data("live.commercial_live_works", path="starWorksInfo.adSocialLiveWorks", raw=[]),
        "live.recent_live_works": _field(
            "live.recent_live_works",
            recent,
            path="starWorksInfo.recentLiveWorks",
            period="最近15个直播",
            structured=True,
        )
        if recent
        else _no_data(
            "live.recent_live_works",
            path="starWorksInfo.recentLiveWorks",
            raw=[],
            period="最近15个直播",
        ),
    }
    frequency_data = _record((frequency_payload or {}).get("data")) or {}
    months = _frequency_items(
        frequency_data.get("starWorkPlayMonthInfo"),
        labels={str(month): f"{month}月" for month in range(1, 13)},
    )
    weeks = _frequency_items(
        frequency_data.get("starWorkPlayWeekInfo"),
        labels={
            "0": "周日",
            "1": "周一",
            "2": "周二",
            "3": "周三",
            "4": "周四",
            "5": "周五",
            "6": "周六",
        },
    )
    hours = _frequency_items(
        frequency_data.get("starWorkPlayHourInfo"),
        labels={str(hour): f"{hour}时" for hour in range(24)},
    )
    frequency = {
        "period_label": "近三个月",
        "unit": "session_count",
        "modes": {
            "month": {"label": "按月", "items": sorted(months, key=lambda item: int(item["key"]))},
            "week": {"label": "按周", "items": sorted(weeks, key=lambda item: int(item["key"]))},
            "hour": {"label": "按时", "items": sorted(hours, key=lambda item: int(item["key"]))},
        },
    }
    fields["live.live_frequency"] = (
        _field(
            "live.live_frequency",
            frequency,
            path="queryVideoPlayCnt.data.starWorkPlayMonthInfo|WeekInfo|HourInfo",
            period="近三个月",
            structured=True,
        )
        if months or weeks or hours
        else _no_data(
            "live.live_frequency",
            path="queryVideoPlayCnt.data.starWorkPlayMonthInfo|WeekInfo|HourInfo",
            raw=frequency_data,
            period="近三个月",
        )
    )
    return ParsedModule(fields=fields, coverage_gaps=coverage)


# --------------------------------------------------------------------------------------------
# audience
# --------------------------------------------------------------------------------------------


def _portrait_points(
    raw: Any,
    *,
    label_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in _list(raw):
        item = _record(row)
        if not item:
            continue
        raw_label = _text(item.get("label"))
        value = _ratio(item.get("value"))
        if raw_label is None or value is None:
            continue
        label = label_map.get(raw_label, raw_label) if label_map else raw_label
        result.append(
            {
                "raw_label": raw_label,
                "label": label,
                "value": value,
                "tgi": _number(item.get("tgi")),
            }
        )
    return result


def _portrait_side(
    raw: dict[str, Any],
    *,
    side: str,
    summary_tags_present: bool,
) -> dict[str, Any]:
    dimensions: dict[str, list[dict[str, Any]]] = {
        "gender": _portrait_points(raw.get("sexPercentage")),
        "age": _portrait_points(raw.get("agePercentage")),
        "device_brand": _portrait_points(raw.get("mobileBrandPercentage")),
        "device_price": _portrait_points(raw.get("mobilePricePercentage")),
        "device_type": _portrait_points(raw.get("mobilePercentage")),
        "activity": _portrait_points(raw.get("activityPercentage")),
        # The platform names these the other way round: cityPercentage is the city tier and
        # cityLevelPercentage is the city-name distribution.
        "city_tier": _portrait_points(raw.get("cityPercentage"), label_map=_CITY_TIER_LABELS),
        "city": _portrait_points(raw.get("cityLevelPercentage")),
        "province": _portrait_points(raw.get("areaPercentage")),
        "province_share": _portrait_points(raw.get("areaTopWithRadio")),
        "province_penetration": _portrait_points(raw.get("areaTopWithPermeation")),
        "interest": _portrait_points(raw.get("interestPercentage")),
        "nine_major_groups": _portrait_points(raw.get("nineMajorGroupsPercentage")),
    }
    availability: dict[str, str] = {}
    for key, points in dimensions.items():
        if points:
            availability[key] = "COLLECTED"
        elif key == "device_type" and side == "viewer" and summary_tags_present:
            availability[key] = "SUMMARY_ONLY"
        else:
            availability[key] = "NO_DATA"
    return {
        "side": side,
        "gender": dimensions["gender"],
        "age": dimensions["age"],
        "device_brand": dimensions["device_brand"],
        "device_price": dimensions["device_price"],
        "device_type": dimensions["device_type"],
        "activity": dimensions["activity"],
        "city_tier": dimensions["city_tier"],
        "city": dimensions["city"],
        "province": dimensions["province"],
        "province_share": dimensions["province_share"],
        "province_penetration": dimensions["province_penetration"],
        "interest": dimensions["interest"],
        "nine_major_groups": dimensions["nine_major_groups"],
        "availability": availability,
        "source_note": (
            "平台 cityPercentage=城市等级、cityLevelPercentage=城市名；"
            "本系统按业务语义纠正 key，并保留 raw_label。"
        ),
    }


def parse_audience(
    portrait_payload: dict[str, Any],
    *,
    viewer_device_tags: list[str] | None = None,
) -> ParsedModule:
    data = _record(portrait_payload.get("data")) or portrait_payload
    viewer_raw = _record(data.get("viewerPortrait")) or {}
    fans_raw = _record(data.get("fansPortrait")) or {}
    viewer = _portrait_side(
        viewer_raw, side="viewer", summary_tags_present=bool(viewer_device_tags)
    )
    fans = _portrait_side(fans_raw, side="fan", summary_tags_present=False)
    viewer_has_data = any(
        viewer[key]
        for key in (
            "gender",
            "age",
            "device_brand",
            "device_price",
            "device_type",
            "activity",
            "city_tier",
            "city",
            "province",
            "province_share",
            "province_penetration",
            "interest",
            "nine_major_groups",
        )
    )
    fans_has_data = any(
        fans[key]
        for key in (
            "gender",
            "age",
            "device_brand",
            "device_price",
            "device_type",
            "activity",
            "city_tier",
            "city",
            "province",
            "province_share",
            "province_penetration",
            "interest",
            "nine_major_groups",
        )
    )
    fields = {
        "live.viewer_portrait": _field(
            "live.viewer_portrait",
            viewer,
            path="listPortrait.data.viewerPortrait",
            structured=True,
        )
        if viewer_has_data
        else _no_data(
            "live.viewer_portrait", path="listPortrait.data.viewerPortrait", raw=viewer_raw
        ),
        "live.fan_portrait": _field(
            "live.fan_portrait",
            fans,
            path="listPortrait.data.fansPortrait",
            structured=True,
        )
        if fans_has_data
        else _no_data("live.fan_portrait", path="listPortrait.data.fansPortrait", raw=fans_raw),
    }
    return ParsedModule(fields=fields)


# --------------------------------------------------------------------------------------------
# commerce
# --------------------------------------------------------------------------------------------


def parse_commerce_period(
    period: int,
    payload: dict[str, Any] | None,
) -> ParsedField:
    data = _record((payload or {}).get("data")) or {}
    values = _commerce_values(data)
    key = f"live.commerce_{period}d"
    if not data:
        return _no_data(
            key,
            path=f"commerce/live[data].{period}",
            raw={},
            period=f"近{period}日",
        )
    structure = {
        "period_days": period,
        "requested_duration": period,
        "response_duration": values.get("duration"),
        "live_cnt": values.get("live_cnt"),
        "live_watch_cnt_median": values.get("live_watch_cnt_median"),
        "live_max_online_cnt_median": values.get("live_max_online_cnt_median"),
        "goods_cnt": values.get("goods_cnt"),
        "goods_graph": values.get("goods_graph"),
        "unit": "count",
        "zero_means_no_data": _commerce_all_zero(values),
    }
    if _commerce_all_zero(values):
        return _no_data(
            key,
            path=f"commerce/live[data].{period}",
            raw=data,
            reason="PLATFORM_ZERO_DISPLAYED_AS_NO_DATA",
            period=f"近{period}日",
        )
    return _field(
        key,
        structure,
        path=f"commerce/live[data].{period}",
        period=f"近{period}日",
        structured=True,
    )


def parse_hot_brands(profile: dict[str, Any]) -> ParsedModule:
    brands = [
        {
            "brand_id": _number(item.get("hotSaleBrandId")),
            "title": _text(item.get("hotSaleBrandTitle")),
            "rank": _number(item.get("hotSaleBrandRank")),
        }
        for item in _list(profile.get("hotBrandInfo"))
        if isinstance(item, dict)
    ]
    categories = [
        {
            "category_id": _number(item.get("hotSaleChannelId")),
            "title": _text(item.get("hotSaleChannelTitle")),
            "rate": _number(item.get("hotSaleChannelRate")),
            "rank": _number(item.get("hotSaleChannelRank")),
        }
        for item in _list(profile.get("hotChannelInfo"))
        if isinstance(item, dict)
    ]
    return ParsedModule(
        fields={
            "live.hot_brands": _field(
                "live.hot_brands", brands, path="starProfile.hotBrandInfo", structured=True
            )
            if brands
            else _no_data("live.hot_brands", path="starProfile.hotBrandInfo", raw=[]),
            "live.hot_categories": _field(
                "live.hot_categories",
                categories,
                path="starProfile.hotChannelInfo",
                structured=True,
            )
            if categories
            else _no_data("live.hot_categories", path="starProfile.hotChannelInfo", raw=[]),
        }
    )


# --------------------------------------------------------------------------------------------
# cooperation / evaluation
# --------------------------------------------------------------------------------------------


def review_key(star_id: str, item: dict[str, Any]) -> str:
    hidden = bool(item.get("hiddenName"))
    parts = [
        str(star_id),
        str(item.get("promotionType")),
        str(item.get("timestamp")),
        str(item.get("comprehensive")),
        str(item.get("content") or ""),
        "hidden" if hidden else "named",
        "" if hidden else str(item.get("productName") or ""),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _review_item(star_id: str, item: dict[str, Any]) -> dict[str, Any] | None:
    timestamp = _timestamp_ms(item.get("timestamp"))
    if timestamp is None:
        return None
    hidden = bool(item.get("hiddenName"))
    product_name = _text(item.get("productName"))
    reviewer_label = "匿名评论" if hidden else (product_name or "匿名评论")
    content_raw = item.get("content")
    content = content_raw if isinstance(content_raw, str) else ""
    redacted, was_redacted = redact_contact_text(content)
    return {
        "review_key": review_key(star_id, item),
        "comprehensive": _number(item.get("comprehensive")),
        "content_quality": _number(item.get("contentQualityScore")),
        "cooperation": _number(item.get("cooperation")),
        "credit": _number(item.get("credit")),
        "content": redacted,
        "content_redacted": was_redacted,
        "timestamp": timestamp,
        "occurred_at": _iso_from_ms(timestamp),
        "promotion_type": _number(item.get("promotionType")),
        "hidden_name": hidden,
        "reviewer_label": reviewer_label,
        "have_agent": bool(item.get("haveAgent")),
    }


def parse_cooperation(
    star_id: str,
    score_payload: dict[str, Any] | None,
    review_pages: list[dict[str, Any]],
    *,
    review_complete: bool,
    page_error: str | None = None,
) -> ParsedModule:
    score_data = _record((score_payload or {}).get("data")) or {}
    total: int | None = None
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    pages = 0
    for page in review_pages:
        data = _record((page or {}).get("data"))
        if data is None:
            continue
        pages += 1
        raw_total = _number(data.get("total"))
        if isinstance(raw_total, int):
            total = raw_total
        for row in _list(data.get("data")):
            if not isinstance(row, dict):
                continue
            parsed = _review_item(star_id, row)
            if parsed is None:
                continue
            if parsed["review_key"] in seen:
                continue
            seen.add(parsed["review_key"])
            items.append(parsed)
    # Never synthesise a platform total from the page we happened to collect; a missing total is
    # reported as missing rather than promoted to a fact.
    coverage: list[str] = []
    if page_error:
        coverage.append("REVIEW_PAGINATION_INCOMPLETE")
    if not review_complete:
        coverage.append("REVIEW_PAGINATION_INCOMPLETE")
    if total is not None and total > 0 and not items:
        coverage.append("REVIEW_ROWS_MISSING")
    elif total is not None and review_complete and len(items) < total:
        coverage.append("REVIEW_ROWS_INCOMPLETE")

    summary: dict[str, Any] | None = None
    if score_data:
        comprehensive = _number(score_data.get("comprehensive"))
        content_quality = _number(score_data.get("contentQualityScore"))
        cooperation = _number(score_data.get("cooperation"))
        credit = _number(score_data.get("credit"))
        # The score panel is collected by a different request than the review list.  A failed
        # review list (unknown total) must not discard successfully collected scores.  A *known*
        # zero-review creator still hides the summary: the platform returns a placeholder panel
        # there and the existing rule is that 0 reviews means no star summary.
        known_zero = total is not None and total <= 0
        if not known_zero and any(
            value is not None for value in (comprehensive, content_quality, cooperation, credit)
        ):
            summary = {
                "comprehensive": comprehensive,
                "content_quality": content_quality,
                "cooperation": cooperation,
                "credit": credit,
                "total_reviews": total,
                "unit": "star",
            }
    fields: dict[str, ParsedField] = {
        "live.evaluation_summary": _field(
            "live.evaluation_summary",
            summary,
            path="evaluation/star/score.data",
            structured=True,
        )
        if summary
        else _no_data(
            "live.evaluation_summary",
            path="evaluation/star/score.data",
            raw=score_data if score_data else None,
        ),
        "live.evaluation_total": _field(
            "live.evaluation_total",
            total,
            path="evaluation/star/list.data.total",
            unit="count",
        )
        if total is not None
        else _no_data(
            "live.evaluation_total",
            path="evaluation/star/list.data.total",
            raw=None,
            unit="count",
        ),
        "live.evaluation_reviews": _field(
            "live.evaluation_reviews",
            {
                "total": total,
                "collected": len(items),
                "pages": pages,
                "complete": review_complete and page_error is None,
                "items": items,
            },
            path="evaluation/star/list.data.data",
            structured=True,
        )
        if items
        else _no_data(
            "live.evaluation_reviews",
            path="evaluation/star/list.data.data",
            raw={
                "total": total,
                "collected": 0,
                "pages": pages,
                "complete": review_complete and page_error is None,
            },
        ),
    }
    if total == 0:
        fields["live.evaluation_summary"] = _no_data(
            "live.evaluation_summary",
            path="evaluation/star/score.data",
            raw=score_data if score_data else None,
            reason="PLATFORM_NO_REVIEWS",
        )
    return ParsedModule(fields=fields, coverage_gaps=coverage)
