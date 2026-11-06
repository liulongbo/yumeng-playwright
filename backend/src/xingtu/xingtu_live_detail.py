"""Parsing and normalisation for the Xingtu live creator-detail modules.

The live adapter owns the browser interaction and hands raw platform responses to these pure
builders.  Every numeric envelope keeps the platform's raw text, the normalised value, the unit and
an explicit status so the UI can distinguish a real zero from a missing / non-applicable metric.

Nothing here calls the network, reads cookies or decides that a missing element means "no data".
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .domain import CollectorError

SHANGHAI = timezone(timedelta(hours=8))

# The platform's live_type values, verified against real requests on 2026-11-05.
LIVE_TYPE_META: dict[str, tuple[str, int]] = {
    "general": ("不限", 1),
    "game": ("游戏直播", 2),
    "ecom": ("电商带货", 3),
    "other": ("其它直播", 4),
}
LIVE_TYPE_BY_REQUEST = {value: key for key, (_, value) in LIVE_TYPE_META.items()}

CROWD_LABEL = {"fans": "粉丝画像", "user": "观众画像"}
PERIOD_LABEL = {30: "近30天", 90: "近90天"}

MISSING_NON_STAR = "非星图商单，不做统计"
MISSING_NON_ECOM = "非带货直播，不做统计"
MISSING_PLATFORM = "平台未提供该指标"
MISSING_ROOM_TYPE = "直播间列表接口未提供该场直播类型"

_STATUSES = {"COLLECTED", "NOT_PROVIDED", "NO_DATA", "NO_PERMISSION", "FAILED", "UNPARSED"}

_COUNT = re.compile(r"^(\d+(?:\.\d+)?)(亿|万|[wW])?(\+)?$")
_DECIMAL = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
_RANGE = re.compile(r"^\s*([^~～\-]+?)\s*[~～\-]\s*([^~～\-]+?)\s*$")


def _raw_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    text = str(value).strip()
    return text or None


def _decimal(text: str) -> tuple[Decimal, str]:
    """Return (amount, bound) for a platform count/percentage text.

    ``1.7w``/``1.7万`` are display abbreviations and keep the ``approximate`` bound; a trailing
    ``+`` keeps the ``lower`` bound.  Commas are display separators only.
    """

    cleaned = text.strip().replace(",", "")
    if cleaned.endswith("%"):
        digits = cleaned[:-1].strip()
        if not _DECIMAL.fullmatch(digits):
            raise ValueError("invalid percent")
        return Decimal(digits) / Decimal(100), "exact"
    match = _COUNT.fullmatch(cleaned)
    if not match:
        raise ValueError("invalid number")
    digits, suffix, lower = match.groups()
    scale = Decimal(1)
    bound = "lower" if lower else "exact"
    if suffix in {"亿"}:
        scale = Decimal(100_000_000)
        bound = "approximate"
    elif suffix in {"万", "w", "W"}:
        scale = Decimal(10_000)
        bound = "approximate"
    return Decimal(digits) * scale, bound


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        # Strip only the representation's trailing zeros; the raw platform text is kept apart.
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def metric(
    raw: Any,
    unit: str | None,
    *,
    status: str = "COLLECTED",
    reason: str | None = None,
    value: Any = None,
    bound: str | None = None,
    range_value: dict[str, Any] | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """One metric envelope.  ``value`` is always normalised to the declared unit."""

    if status not in _STATUSES:
        raise ValueError(f"unknown metric status {status}")
    envelope: dict[str, Any] = {
        "raw": _raw_text(raw),
        "value": _jsonable(value),
        "unit": unit,
        "status": status,
    }
    if reason:
        envelope["reason"] = reason
    if bound:
        envelope["bound"] = bound
    if range_value is not None:
        envelope["range"] = range_value
    if note:
        envelope["note"] = note
    return envelope


def missing_metric(
    raw: Any = None,
    *,
    unit: str | None = None,
    status: str = "NOT_PROVIDED",
    reason: str | None = None,
) -> dict[str, Any]:
    return metric(raw, unit, status=status, reason=reason)


def number_metric(raw: Any, unit: str) -> dict[str, Any]:
    """Normalise a count/ratio/second metric, preserving ``-`` and display abbreviations."""

    text = _raw_text(raw)
    if text is None or text in {"-", "--", "—", "暂无", "暂无数据"}:
        return missing_metric(raw, unit=unit, reason=None if text is None else MISSING_PLATFORM)
    if isinstance(raw, bool):
        return metric(raw, unit, value=None, status="UNPARSED", reason="平台返回布尔值")
    try:
        amount, bound = _decimal(text)
    except (ValueError, InvalidOperation):
        return metric(raw, unit, status="UNPARSED", reason="无法解析为数值")
    if unit == "ratio" and amount > 1:
        return metric(raw, unit, status="UNPARSED", reason="比例超出 0-1 范围")
    return metric(raw, unit, value=amount, bound=bound)


def range_metric(raw: Any, unit: str = "yuan") -> dict[str, Any]:
    """A platform range such as ``2w~20w``/``500~1,000``; never averaged or collapsed."""

    text = _raw_text(raw)
    if text is None or text in {"-", "--", "—", "暂无", "暂无数据"}:
        return missing_metric(raw, unit=unit, reason=MISSING_PLATFORM)
    match = _RANGE.match(text)
    if not match:
        # A single value is still a range with equal bounds; zero stays a real collected zero.
        try:
            amount, bound = _decimal(text)
        except (ValueError, InvalidOperation):
            return metric(raw, unit, status="UNPARSED", reason="无法解析为区间")
        return metric(
            raw,
            unit,
            value=amount,
            bound=bound,
            range_value={"min": str(amount), "max": str(amount), "unit": unit},
        )
    left, right = match.groups()
    try:
        low, low_bound = _decimal(left)
        high, high_bound = _decimal(right)
    except (ValueError, InvalidOperation):
        return metric(raw, unit, status="UNPARSED", reason="无法解析为区间")
    if high < low:
        low, high = high, low
    bound = "exact"
    if "approximate" in {low_bound, high_bound}:
        bound = "approximate"
    if "lower" in {low_bound, high_bound}:
        bound = "lower"
    return metric(
        raw,
        unit,
        value=None,
        bound=bound,
        range_value={"min": str(low), "max": str(high), "unit": unit},
    )


def duration_metric(raw: Any) -> dict[str, Any]:
    """Average watch duration.  Seconds are verified by matching the page text.

    A value above one day cannot be a per-view second average; it is kept raw and marked
    ``unit_ambiguous`` rather than silently converted.
    """

    envelope = number_metric(raw, "second")
    if envelope["status"] == "COLLECTED" and envelope.get("value") is not None:
        try:
            if Decimal(str(envelope["value"])) > Decimal(86400):
                envelope["note"] = (
                    "unit_ambiguous: value is outside a plausible per-view second range"
                )
                envelope["unit_confidence"] = "ambiguous"
        except InvalidOperation:
            pass
    return envelope


def _require_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise CollectorError(
            "PLATFORM_PAGE_CHANGED", "RESPONSE_SCHEMA_MISMATCH:LIVE_DETAIL_RESPONSE_NOT_OBJECT"
        )
    base = payload.get("base_resp")
    if isinstance(base, dict) and base.get("status_code") not in {None, 0}:
        raise CollectorError(
            "MODULE_COLLECTION_FAILED",
            f"LIVE_DETAIL_BUSINESS_ERROR:{base.get('status_code')}",
        )
    return payload


def _iso_from_unix(value: Any) -> tuple[str | None, int | None]:
    raw = _raw_text(value)
    if raw is None:
        return None, None
    try:
        seconds = int(raw)
        observed_at = datetime.fromtimestamp(seconds, tz=SHANGHAI).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        # A millisecond value or an out-of-range timestamp is a platform-parse problem, not a
        # page-shape change; returning None lets the field be classified instead of aborting.
        return None, None
    return observed_at, seconds


def _duration(start: Any, end: Any) -> int | None:
    _, start_s = _iso_from_unix(start)
    _, end_s = _iso_from_unix(end)
    if start_s is None or end_s is None:
        return None
    return max(0, end_s - start_s)


def _type_from_request(value: Any) -> str | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return LIVE_TYPE_BY_REQUEST.get(number)


def _type_meta(live_type: str) -> tuple[str, int]:
    return LIVE_TYPE_META.get(live_type, (live_type, 0))


ROOM_METRICS: dict[str, tuple[str, str]] = {
    "watch_ucnt": ("count", "count"),
    "watch_cnt": ("count", "count"),
    "acu": ("count", "count"),
    "pcu": ("count", "count"),
    "comment_rate": ("ratio", "ratio"),
    "like_rate": ("ratio", "ratio"),
    "fans_watch_rate": ("ratio", "ratio"),
    "follow_ucnt": ("count", "count"),
    "watch_duration_avg": ("second", "second"),
    "acu_rank_rate": ("ratio", "ratio"),
}

ROOM_ECOMMERCE_METRICS: dict[str, tuple[str, str]] = {
    "ecom_live_product_num": ("count", "count"),
    "avg_ecom_product_price_range": ("yuan", "yuan"),
    "gmv_range": ("yuan", "yuan"),
    "avg_gpm_range": ("gpm", "gpm"),
}

ROOM_FLAGS = ("is_star_order", "is_star_ad_order")


def room_envelope(
    item: Any,
    *,
    live_type: str | None = None,
    request_live_type: int | None = None,
    type_reason: str | None = None,
) -> dict[str, Any]:
    """Normalise one live-room row from latest/periodic/multi_get responses."""

    if not isinstance(item, dict):
        raise CollectorError(
            "PLATFORM_PAGE_CHANGED", "RESPONSE_SCHEMA_MISMATCH:LIVE_ROOM_NOT_OBJECT"
        )
    row: dict[str, Any] = {
        "room_id": _raw_text(item.get("room_id")),
        "title": _raw_text(item.get("title")),
        "start_time": _iso_from_unix(item.get("start_time"))[0],
        "end_time": _iso_from_unix(item.get("end_time"))[0],
        "duration_seconds": _duration(item.get("start_time"), item.get("end_time")),
        "metrics": {},
        "flags": {flag: item.get(flag) for flag in ROOM_FLAGS if flag in item},
    }
    if live_type:
        row["live_type"] = live_type
        row["live_type_label"] = _type_meta(live_type)[0]
        row["request_live_type"] = request_live_type
    else:
        row["live_type"] = None
        row["live_type_status"] = "NOT_PROVIDED"
        row["live_type_reason"] = type_reason or MISSING_ROOM_TYPE

    star_order = item.get("is_star_order")
    is_ecom = live_type == "ecom"
    if live_type is None:
        # The list endpoint does not return live_type.  E-commerce capability is still explicit:
        # an ecom room always has ecom_live_product_num / price range; a non-ecom room has neither.
        is_ecom = item.get("ecom_live_product_num") is not None or (
            item.get("avg_ecom_product_price_range") not in {None, "", "0"}
        )

    for key, (_, unit) in ROOM_METRICS.items():
        if key not in item:
            row["metrics"][key] = missing_metric(None, unit=unit, status="NO_DATA")
        elif key == "watch_duration_avg":
            row["metrics"][key] = duration_metric(item.get(key))
        else:
            row["metrics"][key] = number_metric(item.get(key), unit)
    ctr_raw = item.get("ctr")
    if star_order is False:
        row["metrics"]["ctr"] = missing_metric(ctr_raw, unit="ratio", reason=MISSING_NON_STAR)
    elif ctr_raw is None:
        row["metrics"]["ctr"] = missing_metric(
            None, unit="ratio", reason=MISSING_NON_STAR if star_order is False else MISSING_PLATFORM
        )
    else:
        row["metrics"]["ctr"] = number_metric(ctr_raw, "ratio")

    for key, (_, unit) in ROOM_ECOMMERCE_METRICS.items():
        if not is_ecom:
            row["metrics"][key] = missing_metric(item.get(key), unit=unit, reason=MISSING_NON_ECOM)
        elif key == "gmv_range" or key == "avg_ecom_product_price_range":
            row["metrics"][key] = range_metric(item.get(key), unit="yuan")
        else:
            row["metrics"][key] = number_metric(item.get(key), unit)

    row["brands"] = [str(value) for value in (item.get("brand_info") or []) if value]
    if item.get("cover_url"):
        # Only the presence is recorded; signed URLs are short-lived and are not business data.
        row["has_cover"] = True
    return row


def build_pricing(payload: Any) -> dict[str, Any] | None:
    """Live service quotes from ``get_author_marketing_info.price_info``."""

    payload = _require_payload(payload)
    items = payload.get("price_info")
    if not isinstance(items, list):
        return None
    services: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        desc = _raw_text(item.get("desc")) or ""
        task_category = item.get("task_category")
        is_live = task_category == 6 or any(token in desc for token in ("直播", "专场", "拼场"))
        if not is_live:
            continue
        if "按天" in desc:
            mode, unit = "per_day", "元/天"
        elif "电商带货拼场" in desc:
            mode, unit = "per_goods", "元/商品"
        elif "电商带货专场" in desc:
            mode, unit = "per_hour", "元/小时"
        elif "按小时" in desc or "小时" in desc:
            mode, unit = "per_hour", "元/小时"
        elif "按商品" in desc or "商品" in desc:
            mode, unit = "per_goods", "元/商品"
        else:
            mode, unit = "unknown", None
        price = item.get("price")
        origin = item.get("origin_price")
        services.append(
            {
                "service_key": f"live:{item.get('video_type')}:{desc}",
                "service_label": desc,
                "pricing_mode": mode,
                "unit": unit,
                "currency": "CNY",
                "price": _jsonable(number_metric(price, unit or "count")),
                "origin_price": _jsonable(number_metric(origin, unit or "count")),
                "platform": {
                    key: item.get(key)
                    for key in (
                        "video_type",
                        "task_category",
                        "task_category_status",
                        "settlement_type",
                        "settlement_desc",
                        "enable",
                        "is_open",
                        "need_price",
                        "has_discount",
                        "online_status",
                        "start_time",
                        "end_time",
                        "activity_info",
                    )
                    if key in item
                },
            }
        )
    if not services:
        return None
    return {
        "services": services,
        "currency": "CNY",
        "source": {"path": "data.price_info", "request": "get_author_marketing_info"},
    }


def _calibre_key(period: int | None, flow_type: int | None, only_star_order: bool) -> str:
    period_part = period if period is not None else "na"
    flow_part = flow_type if flow_type is not None else "na"
    return f"period_{period_part}_flow_{flow_part}_star_{int(bool(only_star_order))}"


def _overview_groups(payload: dict[str, Any]) -> dict[str, Any]:
    room = payload.get("live_room_statistics")
    ecom = payload.get("live_ecom_statistics")
    convert = payload.get("live_convert_statistics")
    groups: dict[str, Any] = {"room": {}, "ecom": {}, "convert": {}}
    if isinstance(room, dict):
        groups["room"] = {
            key: (
                duration_metric(room.get(key))
                if key == "watch_duration_avg"
                else number_metric(room.get(key), unit)
            )
            for key, unit in (
                ("room_cnt", "count"),
                ("watch_ucnt_avg", "count"),
                ("watch_cnt_avg", "count"),
                ("acu", "count"),
                ("pcu", "count"),
                ("fans_watch_rate", "ratio"),
                ("follow_ucnt_avg", "count"),
                ("comment_rate_avg", "ratio"),
                ("like_rate_avg", "ratio"),
                ("watch_duration_avg", "second"),
                ("acu_precede_percent", "ratio"),
                ("interact_rate_avg", "ratio"),
                ("finish_order_cnt", "count"),
                ("in_process_order_cnt", "count"),
            )
            if key in room
        }
    if isinstance(ecom, dict):
        groups["ecom"] = {
            "ecom_live_product_num": number_metric(ecom.get("ecom_live_product_num"), "count"),
            "avg_gmv_range": range_metric(ecom.get("avg_gmv_range"), "yuan"),
            "avg_ecom_product_price_range": range_metric(
                ecom.get("avg_ecom_product_price_range"), "yuan"
            ),
            "avg_gpm_range": range_metric(ecom.get("avg_gpm_range"), "gpm"),
        }
    if isinstance(convert, dict) and convert:
        groups["convert"] = {
            key: number_metric(convert.get(key), "ratio")
            for key in (
                "ctr_avg",
                "handle_ctr_avg",
                "snowflake_ctr_avg",
                "windmill_ctr_avg",
                "handle_cvr_avg",
            )
        }
    else:
        groups["convert"] = {}
        groups["convert_note"] = "转化表现仅对星图商单生效"
    return groups


def build_overview_field(
    captures: Iterable[dict[str, Any]],
    *,
    live_type: str,
) -> dict[str, Any] | None:
    """One live type's captured overview calibres.  Each calibre is stored separately."""

    label, request_value = _type_meta(live_type)
    calibres: dict[str, Any] = {}
    captured_periods: list[int] = []
    for capture in captures:
        payload = _require_payload(capture.get("payload"))
        period = capture.get("period")
        flow_type = capture.get("flow_type")
        star = bool(capture.get("only_star_order"))
        key = _calibre_key(period, flow_type, star)
        if key in calibres:
            continue
        excluded = capture.get("excluded_marketing")
        if excluded is None and flow_type is not None:
            # Verified on 2026-11-05: switch ON => flow_type=1 (marketing traffic excluded),
            # switch OFF => flow_type=0.  Keep the raw value alongside the semantic label.
            excluded = int(flow_type) == 1
        groups = _overview_groups(payload)
        interpretation = {}
        room_group = groups.get("room", {})
        for metric_key in ("room_cnt", "acu", "acu_precede_percent"):
            if metric_key in room_group:
                interpretation[metric_key] = room_group[metric_key]
        calibres[key] = {
            "period": period,
            "period_label": PERIOD_LABEL.get(period) if isinstance(period, int) else None,
            "flow_type": flow_type,
            "excluded_marketing": excluded,
            "only_star_order": star,
            "groups": groups,
            "interpretation": interpretation,
            "source": {
                "request": "get_author_live_statistics",
                "path": capture.get("path"),
                "observed_at": capture.get("observed_at"),
            },
        }
        if isinstance(period, int) and period not in captured_periods:
            captured_periods.append(period)
    if not calibres:
        return None
    return {
        "live_type": live_type,
        "live_type_label": label,
        "request_live_type": request_value,
        "calibres": calibres,
        "captured_periods": sorted(captured_periods),
    }


def build_overview_meta(
    *,
    candidates: dict[str, Any] | None,
    captures: Iterable[dict[str, Any]],
    default_type: str | None,
    default_period: int | None,
    default_flow_type: int | None,
    default_only_star_order: bool | None,
    not_captured: list[str] | None = None,
    policy: str | None = None,
) -> dict[str, Any]:
    captured = []
    for capture in captures:
        captured.append(
            {
                "live_type": capture.get("live_type"),
                "period": capture.get("period"),
                "flow_type": capture.get("flow_type"),
                "only_star_order": bool(capture.get("only_star_order")),
                "excluded_marketing": capture.get("excluded_marketing"),
            }
        )
    return {
        "candidates": candidates or {},
        "type_map": {key: value for key, (_, value) in LIVE_TYPE_META.items()},
        "type_labels": {key: value for key, (value, _) in LIVE_TYPE_META.items()},
        "defaults": {
            "live_type": default_type,
            "period": default_period,
            "flow_type": default_flow_type,
            "only_star_order": default_only_star_order,
        },
        "flow_semantics": {"0": "all_traffic", "1": "exclude_marketing"},
        "captured": captured,
        "not_captured": not_captured or [],
        "capture_policy": policy,
    }


def build_calendar(
    captures: Iterable[dict[str, Any]],
    *,
    live_type: str,
    interpretation: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    label, request_value = _type_meta(live_type)
    months: list[dict[str, Any]] = []
    for capture in captures:
        payload = _require_payload(capture.get("payload"))
        rooms = payload.get("live_rooms")
        if not isinstance(rooms, list):
            raise CollectorError(
                "PLATFORM_PAGE_CHANGED", "RESPONSE_SCHEMA_MISMATCH:LIVE_CALENDAR_SCHEMA"
            )
        days: dict[str, list[dict[str, Any]]] = {}
        for item in rooms:
            row = room_envelope(item)
            date = (row.get("start_time") or "")[:10] or None
            if date:
                days.setdefault(date, []).append(row)
        month = capture.get("month")
        year = capture.get("year")
        entry: dict[str, Any] = {
            "year": year,
            "month": month,
            "month_label": f"{year}-{int(month):02d}" if year and month else None,
            "flow_type": capture.get("flow_type"),
            "excluded_marketing": capture.get("excluded_marketing"),
            "only_star_order": bool(capture.get("only_star_order")),
            "days": [{"date": date, "rooms": days[date]} for date in sorted(days)],
            "room_count": len(rooms),
            "highest_room": (
                room_envelope(payload.get("highest_live_room"))
                if isinstance(payload.get("highest_live_room"), dict)
                else None
            ),
            "latest_room": (
                room_envelope(payload.get("latest_live_room"))
                if isinstance(payload.get("latest_live_room"), dict)
                else None
            ),
            "source": {"request": "get_author_peroidic_live_analysis", "path": capture.get("path")},
        }
        if interpretation:
            entry["interpretation"] = interpretation
        months.append(entry)
    if not months:
        return None
    return {
        "live_type": live_type,
        "live_type_label": label,
        "request_live_type": request_value,
        "months": months,
        "months_captured": [entry["month_label"] for entry in months if entry.get("month_label")],
    }


def build_latest(payload: Any, *, live_type: str) -> dict[str, Any] | None:
    payload = _require_payload(payload)
    rooms = payload.get("latest_live_rooms")
    if not isinstance(rooms, list):
        return None
    points: list[dict[str, Any]] = []
    series: dict[str, list[dict[str, Any]]] = {"watch_cnt": [], "acu": [], "pcu": []}
    for index, item in enumerate(rooms):
        row = room_envelope(item)
        points.append(
            {
                "index": index,
                "room_id": row["room_id"],
                "start_time": row["start_time"],
                "metrics": row["metrics"],
            }
        )
        for key in series:
            metric_value = row["metrics"].get(key, {})
            series[key].append(
                {
                    "index": index,
                    "date": row["start_time"],
                    "raw": metric_value.get("raw"),
                    "value": metric_value.get("value"),
                    "status": metric_value.get("status"),
                }
            )
    label, request_value = _type_meta(live_type)
    return {
        "live_type": live_type,
        "live_type_label": label,
        "request_live_type": request_value,
        "window": len(rooms),
        "points": points,
        "series": series,
        "highest_room": (
            room_envelope(payload.get("highest_live_room"))
            if isinstance(payload.get("highest_live_room"), dict)
            else None
        ),
        "latest_room": (
            room_envelope(payload.get("latest_live_room"))
            if isinstance(payload.get("latest_live_room"), dict)
            else None
        ),
        "source": {"request": "get_author_latest_live_analysis"},
    }


def build_rooms(
    *,
    list_pages: Iterable[dict[str, Any]],
    room_items: dict[str, dict[str, Any]],
    latest_types: dict[str, str] | None = None,
    details: dict[str, dict[str, Any]] | None = None,
    max_pages: int | None = None,
) -> dict[str, Any] | None:
    """Live-room list across all pages.

    ``search_for_live_room_list`` returns only ids and pagination; ``multi_get_room_data`` returns
    the metrics for the ids of one page.  The list endpoint does not carry live_type, so a row's
    type is filled from the latest-15 payload or a room-detail payload when available, otherwise
    kept as NOT_PROVIDED with the reason text.
    """

    ordered_ids: list[str] = []
    seen: set[str] = set()
    pages: list[dict[str, Any]] = []
    for page in list_pages:
        payload = _require_payload(page.get("payload"))
        ids = payload.get("item_ids")
        if not isinstance(ids, list):
            raise CollectorError(
                "PLATFORM_PAGE_CHANGED", "RESPONSE_SCHEMA_MISMATCH:LIVE_ROOM_LIST_SCHEMA"
            )
        pagination_obj = payload.get("pagination")
        pagination: dict[str, Any] = pagination_obj if isinstance(pagination_obj, dict) else {}
        pages.append({"page": page.get("page") or pagination.get("page"), "pagination": pagination})
        for item_id in ids:
            value = _raw_text(item_id)
            if value and value not in seen:
                seen.add(value)
                ordered_ids.append(value)
    if not ordered_ids:
        return None
    latest_types = latest_types or {}
    details = details or {}
    rows: list[dict[str, Any]] = []
    for item_id in ordered_ids:
        item = room_items.get(item_id)
        detail = details.get(item_id)
        live_type = latest_types.get(item_id)
        request_type = None
        if isinstance(detail, dict):
            request_type = detail.get("live_type")
            if live_type is None and request_type is not None:
                live_type = _type_from_request(request_type)
        if item is None:
            row = {
                "room_id": item_id,
                "title": None,
                "start_time": None,
                "end_time": None,
                "duration_seconds": None,
                "live_type": live_type,
                "live_type_status": "COLLECTED" if live_type else "NO_DATA",
                "metrics": {
                    key: missing_metric(None, unit=unit, status="NO_DATA")
                    for key, (_, unit) in {**ROOM_METRICS, **ROOM_ECOMMERCE_METRICS}.items()
                },
                "flags": {},
            }
            rows.append(row)
            continue
        row = room_envelope(
            item,
            live_type=live_type,
            request_live_type=request_type,
        )
        if live_type:
            row["live_type_status"] = "COLLECTED"
        rows.append(row)
    total = None
    limit = None
    for page in pages:
        pagination = page.get("pagination") or {}
        if pagination.get("total_count") is not None:
            total = pagination.get("total_count")
        if pagination.get("limit") is not None:
            limit = pagination.get("limit")
    return {
        "rows": rows,
        "item_count": len(rows),
        "pagination": {
            "total_count": total,
            "limit": limit,
            "pages_captured": [page.get("page") for page in pages if page.get("page") is not None],
            "max_pages": max_pages,
        },
        "source": {
            "list_request": "search_for_live_room_list",
            "metrics_request": "multi_get_room_data",
        },
    }


AUDIENCE_KEYS = {
    "性别分布": "gender",
    "年龄分布": "age",
    "省份分布": "province",
    "城市分布": "city",
    "城市等级分布": "city_level",
    "兴趣分布": "interest",
    "八大人群分布": "eight_crowds",
    "设备品牌分布": "device",
}


def _distribution_entry(distribution: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    display = _raw_text(distribution.get("type_display")) or f"type_{distribution.get('type')}"
    key = AUDIENCE_KEYS.get(display, f"type_{distribution.get('type')}")
    items = distribution.get("distribution_list")
    if not isinstance(items, list):
        items = []
    parsed: list[dict[str, Any]] = []
    total = Decimal(0)
    for item in items:
        if not isinstance(item, dict):
            continue
        raw = _raw_text(item.get("distribution_value"))
        try:
            amount = Decimal(raw.replace(",", "")) if raw else None
        except (InvalidOperation, AttributeError):
            amount = None
        if amount is not None:
            total += amount
        parsed.append(
            {
                "key": _raw_text(item.get("distribution_key")),
                "raw": raw,
                "count": _jsonable(amount),
            }
        )
    for item in parsed:
        if total > 0 and item.get("count") is not None:
            ratio = Decimal(str(item["count"])) / total
            item["ratio"] = str(ratio)
            item["percent"] = float(ratio * 100)
        else:
            item["ratio"] = None
            item["percent"] = None
    return key, {
        "type": distribution.get("type"),
        "type_display": display,
        "description": distribution.get("description"),
        "image": distribution.get("image"),
        "items": parsed,
        "total": _jsonable(total) if total else None,
        "top10": sorted(
            [item for item in parsed if item.get("count") is not None],
            key=lambda item: Decimal(str(item["count"])),
            reverse=True,
        )[:10],
        "ratio_note": "占比按该分布计数合计计算；保留原始计数",
    }


def build_audience(
    payload: Any,
    *,
    live_type: str,
    crowd_type: str,
    request_crowd_type: int | None,
) -> dict[str, Any] | None:
    payload = _require_payload(payload)
    distributions = payload.get("distributions")
    if not isinstance(distributions, list):
        return None
    label, request_type = _type_meta(live_type)
    grouped: dict[str, Any] = {}
    for distribution in distributions:
        if not isinstance(distribution, dict):
            continue
        key, entry = _distribution_entry(distribution)
        grouped[key] = entry
    if not grouped:
        return None
    return {
        "live_type": live_type,
        "live_type_label": label,
        "request_live_type": request_type,
        "crowd_type": crowd_type,
        "crowd_type_label": CROWD_LABEL.get(crowd_type, crowd_type),
        "request_crowd_type": request_crowd_type,
        "distributions": grouped,
        "source": {"request": "get_author_live_watch_distribution"},
    }


_CONTACT_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_CONTACT_WECHAT = re.compile(r"(?i)(微信|vx|v信|商务合作|合作联系)\s*[:：]?\s*[A-Za-z0-9_-]{4,}")
# The dialog's .wechat node contains only the ID text plus an icon (no text). Keep IDs that look
# like a WeChat account (letter/digit start, letters/digits/_/-, 4-32 chars) and reject labels such
# as "复制"/"暂无数据" so the icon/empty state is never persisted as a contact.
_WECHAT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{3,31}$")


def clean_wechat(value: Any) -> str | None:
    """Return the exact WeChat ID from one dialog text node, or None when absent/invalid."""

    if not isinstance(value, str):
        return None
    first = value.strip().splitlines()[0].strip() if value.strip() else ""
    if not first or not _WECHAT_ID.fullmatch(first):
        return None
    return first


def redact_contact(value: Any) -> str | None:
    """Keep the biography but never persist embedded contact details."""

    if not isinstance(value, str) or not value.strip():
        return None
    text = _CONTACT_PHONE.sub("[联系方式已脱敏]", value)
    text = _CONTACT_WECHAT.sub(r"\1：[联系方式已脱敏]", text)
    return text.strip() or None


def build_basic_extra(base_info: Any, channel_info: Any) -> dict[str, Any]:
    base = _require_payload(base_info) if isinstance(base_info, dict) else {}
    channel = _require_payload(channel_info) if isinstance(channel_info, dict) else {}
    labels_obj = base.get("live_labels_v2")
    labels: dict[str, Any] = labels_obj if isinstance(labels_obj, dict) else {}
    order_obj = base.get("live_order_labels")
    order_labels: dict[str, Any] = order_obj if isinstance(order_obj, dict) else {}
    content_types = [str(key) for key in labels]
    content_tags: list[str] = []
    for values in labels.values():
        if isinstance(values, list):
            content_tags.extend(str(value) for value in values if value)
    business_types = [str(key) for key in order_labels]
    douyin_id = base.get("unique_id") or base.get("short_id")
    introduction = redact_contact(channel.get("self_intro"))
    return {
        "douyin_id": _raw_text(douyin_id),
        "content_types": content_types,
        "content_tags": content_tags,
        "business_order_types": business_types,
        "introduction": introduction,
    }


# Field keys produced by the builders; kept next to the contract for adapter validation.
NEW_FIELD_KEYS = {
    "live_pricing": ("pricing.services",),
    "live_analysis": (
        "analysis.general.calendar",
        "analysis.general.latest",
        "analysis.game.calendar",
        "analysis.game.latest",
        "analysis.ecom.calendar",
        "analysis.ecom.latest",
        "analysis.other.calendar",
        "analysis.other.latest",
        "analysis.rooms",
    ),
    "live_audience": (
        "audience.general.fans",
        "audience.general.user",
        "audience.game.fans",
        "audience.game.user",
        "audience.ecom.fans",
        "audience.ecom.user",
        "audience.other.fans",
        "audience.other.user",
    ),
    "live_overview": (
        "overview.meta",
        "overview.general",
        "overview.game",
        "overview.ecom",
        "overview.other",
    ),
}
