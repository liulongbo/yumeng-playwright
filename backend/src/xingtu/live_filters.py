"""Scene-isolated live-square filter mapping.

This module is deliberately separate from the verified video-square filter executor.  Both live
adapters import it; neither the video adapter nor its contract reads anything from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .contracts import AttributeFilterEntry
from .domain import (
    LIVE_OPTION_FIELDS,
    LIVE_PROFILE_FIELDS,
    LIVE_RANGE_FIELDS,
    Capabilities,
    CollectorError,
    Filter,
    FilterPlan,
    LiveProfileCompound,
    NumberRange,
    RegionCompound,
)


@dataclass(frozen=True)
class ProfileExpectation:
    """One selected profile dimension and the request field family it must produce."""

    field: str
    dimension: str
    allowed_fields: frozenset[str]
    exact_value: str | None = None


@dataclass(frozen=True)
class LiveRequestExpectation:
    attribute_filters: tuple[AttributeFilterEntry, ...]
    profile_expectations: tuple[ProfileExpectation, ...]
    keyword: str | None


def _spec(capabilities: Capabilities, field: str) -> Any:
    for item in capabilities.fields:
        if item.field == field:
            return item
    raise CollectorError("UNSUPPORTED_FILTER", field)


def _option_request_value(spec: Any, value: str) -> str:
    option = next((item for item in spec.options if item.value == value), None)
    if option is None or option.request_value is None:
        raise CollectorError("PLATFORM_PAGE_CHANGED", f"MISSING_REQUEST_MAPPING:{spec.field}")
    return str(option.request_value)


def _scaled(value: Decimal, scale: int) -> str:
    scaled = value * scale
    if scaled == scaled.to_integral():
        return str(int(scaled))
    return format(scaled, "f").rstrip("0").rstrip(".")


def expected_xingtu_live_request(
    plan: FilterPlan, capabilities: Capabilities
) -> LiveRequestExpectation:
    """Build the exact non-profile attribute entries plus profile field obligations.

    Profile option ids are emitted by the live Xingtu component and are not stable plan values;
    their authoritative checks are the request field family and the visible selected-chip
    readback.  All other conditions are matched as an exact multiset.
    """

    entries: list[AttributeFilterEntry] = []
    profiles: list[ProfileExpectation] = []
    keyword: str | None = None
    for item in plan.filters:
        if item.field == "keyword":
            keyword = str(item.value)
            continue
        spec = _spec(capabilities, item.field)
        mapping = spec.request_mapping
        if item.field in LIVE_OPTION_FIELDS:
            if isinstance(item.value, list):
                values = [str(value) for value in item.value]
            else:
                values = [str(item.value)]
            field_name = str(mapping.get("field_name") or "")
            if not field_name:
                raise CollectorError(
                    "PLATFORM_PAGE_CHANGED", f"MISSING_REQUEST_MAPPING:{item.field}"
                )
            if mapping.get("encoding") == "json_array":
                payload = (
                    "[" + ",".join(_option_request_value(spec, value) for value in values) + "]"
                )
            else:
                if len(values) != 1:
                    raise CollectorError("INVALID_FORM", f"{item.field} requires one value")
                payload = _option_request_value(spec, values[0])
            entries.append(AttributeFilterEntry(field_name=field_name, field_value=payload))
        elif item.field == "live_region" and isinstance(item.value, RegionCompound):
            provinces = {node.value: node for node in spec.region_tree}
            province_values: list[str] = []
            city_values: list[str] = []
            for selection in item.value.selections:
                province = provinces.get(selection.province_code)
                if province is None:
                    raise CollectorError("INVALID_FORM", "unknown province")
                if selection.city is None:
                    province_values.append(province.label)
                else:
                    city_values.append(selection.city)
            if province_values:
                entries.append(
                    AttributeFilterEntry(
                        field_name=str(mapping["province_field"]),
                        field_value=_json_array(province_values),
                    )
                )
            if city_values:
                entries.append(
                    AttributeFilterEntry(
                        field_name=str(mapping["city_field"]),
                        field_value=_json_array(city_values),
                    )
                )
        elif item.field in LIVE_RANGE_FIELDS and isinstance(item.value, NumberRange):
            scale_value = mapping.get("scale")
            if isinstance(scale_value, bool) or not isinstance(scale_value, (int, str)):
                raise CollectorError("PLATFORM_PAGE_CHANGED", "INVALID_REQUEST_SCALE")
            scale = int(scale_value)
            if item.value.min is not None:
                entries.append(
                    AttributeFilterEntry(
                        field_name=str(mapping["min_field"]),
                        field_value=_scaled(item.value.min, scale),
                    )
                )
            if item.value.max is not None:
                entries.append(
                    AttributeFilterEntry(
                        field_name=str(mapping["max_field"]),
                        field_value=_scaled(item.value.max, scale),
                    )
                )
        elif item.field in LIVE_PROFILE_FIELDS and isinstance(item.value, LiveProfileCompound):
            for profile_selection in item.value.dimensions:
                exact: str | None = None
                if profile_selection.key == "age":
                    allowed = frozenset({str(mapping["age_field"])})
                elif profile_selection.key == "gender":
                    if len(profile_selection.values) != 1:
                        raise CollectorError("INVALID_FORM", "single gender value required")
                    value = profile_selection.values[0]
                    if value.startswith("male_"):
                        allowed = frozenset({str(mapping["gender_male_field"])})
                        exact = _ratio(value.removeprefix("male_"))
                    elif value.startswith("female_"):
                        allowed = frozenset({str(mapping["gender_female_field"])})
                        exact = _ratio(value.removeprefix("female_"))
                    else:
                        raise CollectorError("UNSUPPORTED_FILTER", f"{item.field}.gender")
                elif profile_selection.key in {"device_brand", "city_level"}:
                    key = (
                        "device_field" if profile_selection.key == "device_brand" else "city_field"
                    )
                    allowed = frozenset({str(mapping[key])})
                else:
                    raise CollectorError(
                        "UNSUPPORTED_FILTER", f"{item.field}.{profile_selection.key}"
                    )
                profiles.append(
                    ProfileExpectation(
                        field=item.field,
                        dimension=profile_selection.key,
                        allowed_fields=allowed,
                        exact_value=exact,
                    )
                )
        else:
            raise CollectorError("UNSUPPORTED_FILTER", item.field)
    return LiveRequestExpectation(
        attribute_filters=tuple(entries),
        profile_expectations=tuple(profiles),
        keyword=keyword,
    )


def _ratio(value: str) -> str:
    if not value.isdigit():
        raise CollectorError("UNSUPPORTED_FILTER", "profile gender ratio")
    return format(Decimal(int(value)) / Decimal(100), "f")


def _json_array(values: list[str]) -> str:
    import json

    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def observed_attribute_entries(payload: Any) -> list[AttributeFilterEntry] | None:
    if not isinstance(payload, dict):
        return None
    entries = payload.get("attribute_filter")
    if entries is None:
        return []
    if not isinstance(entries, list):
        return None
    result: list[AttributeFilterEntry] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("field"), dict):
            return None
        name = entry["field"].get("field_name")
        value = entry.get("field_value")
        if not isinstance(name, str) or value is None:
            return None
        rel_id = entry["field"].get("rel_id", entry.get("rel_id"))
        result.append(
            AttributeFilterEntry(
                field_name=name,
                field_value=str(value),
                rel_id=str(rel_id) if rel_id is not None else None,
            )
        )
    return result


def validate_xingtu_live_request(payload: Any, expectation: LiveRequestExpectation) -> None:
    """Reject a request that does not carry the exact planned non-profile conditions."""

    if not isinstance(payload, dict):
        raise CollectorError("PLATFORM_PAGE_CHANGED", "LIVE_SEARCH_REQUEST_SCHEMA")
    actual = observed_attribute_entries(payload)
    if actual is None:
        raise CollectorError("PLATFORM_PAGE_CHANGED", "LIVE_SEARCH_REQUEST_SCHEMA")
    profile_fields = {
        field for item in expectation.profile_expectations for field in item.allowed_fields
    }
    non_profile = [entry for entry in actual if entry.field_name not in profile_fields]
    expected = list(expectation.attribute_filters)
    if sorted((entry.field_name, entry.field_value) for entry in non_profile) != sorted(
        (entry.field_name, entry.field_value) for entry in expected
    ):
        raise CollectorError("PLATFORM_CONDITION_MISMATCH", "LIVE_FILTER_REQUEST_MISMATCH")
    if expectation.profile_expectations:
        relevant = [entry for entry in actual if entry.field_name in profile_fields]
        for profile in expectation.profile_expectations:
            matches = [entry for entry in relevant if entry.field_name in profile.allowed_fields]
            if not matches:
                raise CollectorError(
                    "PLATFORM_CONDITION_MISMATCH", f"LIVE_PROFILE_MISSING:{profile.dimension}"
                )
            if profile.exact_value is not None and not any(
                entry.field_value == profile.exact_value for entry in matches
            ):
                raise CollectorError(
                    "PLATFORM_CONDITION_MISMATCH", f"LIVE_PROFILE_VALUE:{profile.dimension}"
                )
    elif any(entry.field_name in profile_fields for entry in actual):
        raise CollectorError("PLATFORM_CONDITION_MISMATCH", "LIVE_UNEXPECTED_PROFILE")


def juxing_live_filter_body(plan: FilterPlan, capabilities: Capabilities) -> dict[str, Any]:
    """Translate one live plan into the verified Juxing ``star/list`` filter fields.

    Unknown or unmapped fields are rejected instead of being silently dropped.
    """

    body: dict[str, Any] = {}
    handled: set[str] = set()
    for item in plan.filters:
        if item.field == "keyword":
            continue
        spec = _spec(capabilities, item.field)
        mapping = spec.request_mapping
        if item.field == "live_content_category":
            values = item.value if isinstance(item.value, list) else [item.value]
            tags = mapping.get("tags")
            if not isinstance(tags, dict):
                raise CollectorError("PLATFORM_PAGE_CHANGED", "JUXING_LIVE_CONTENT_MAPPING")
            payload: list[dict[str, Any]] = []
            for value in values:
                tag = tags.get(str(value))
                if not isinstance(tag, dict):
                    raise CollectorError("UNSUPPORTED_FILTER", "live_content_category")
                payload.append(dict(tag))
            key = str(mapping.get("field") or "contentTagIdList")
            body[key] = payload
            handled.add(item.field)
        elif item.field in LIVE_RANGE_FIELDS and isinstance(item.value, NumberRange):
            scale_value = mapping.get("scale", 1)
            if isinstance(scale_value, bool) or not isinstance(scale_value, (int, str)):
                raise CollectorError("PLATFORM_PAGE_CHANGED", "JUXING_LIVE_RANGE_SCALE")
            scale = int(scale_value)
            if mapping.get("nested"):
                field = str(mapping.get("field") or "")
                if not field:
                    raise CollectorError("PLATFORM_PAGE_CHANGED", "JUXING_LIVE_RANGE_MAPPING")
                nested: dict[str, int] = {}
                if item.value.min is not None:
                    nested["min"] = int(item.value.min * scale)
                if item.value.max is not None:
                    nested["max"] = int(item.value.max * scale)
                body[field] = nested
            else:
                if item.value.min is not None:
                    body[str(mapping["min_field"])] = int(item.value.min * scale)
                if item.value.max is not None:
                    body[str(mapping["max_field"])] = int(item.value.max * scale)
            handled.add(item.field)
        elif item.field in LIVE_PROFILE_FIELDS and isinstance(item.value, LiveProfileCompound):
            for selection in item.value.dimensions:
                if selection.key == "age":
                    field = str(mapping["age_field"])
                    body[field] = [
                        {
                            "queryName": value,
                            "from": str(mapping.get("seed_from", "0.50")),
                            "to": str(mapping.get("seed_to", "1.00")),
                        }
                        for value in selection.values
                    ]
                elif selection.key == "gender":
                    if len(selection.values) != 1:
                        raise CollectorError("INVALID_FORM", "single gender value required")
                    body[str(mapping["gender_field"])] = {
                        "queryName": selection.values[0],
                        "from": "0.00",
                        "to": "1.00",
                    }
                elif selection.key == "mobile":
                    if len(selection.values) != 1:
                        raise CollectorError("INVALID_FORM", "single device value required")
                    body[str(mapping["mobile_field"])] = {
                        "queryName": selection.values[0],
                        "from": "0.00",
                        "to": "1.00",
                    }
                elif selection.key in {"area", "crowd"}:
                    field = str(
                        mapping["area_field"] if selection.key == "area" else mapping["crowd_field"]
                    )
                    body[field] = [
                        {"queryName": value, "from": "0.00", "to": "1.00"}
                        for value in selection.values
                    ]
                else:
                    raise CollectorError("UNSUPPORTED_FILTER", f"{item.field}.{selection.key}")
            handled.add(item.field)
        else:
            raise CollectorError("UNSUPPORTED_FILTER", item.field)
    expected = {item.field for item in plan.filters if item.field != "keyword"}
    if handled != expected:
        raise CollectorError("UNSUPPORTED_FILTER", "JUXING_LIVE_UNMAPPED_FILTER")
    return body


def is_live_filter(field: str) -> bool:
    return field in LIVE_OPTION_FIELDS | LIVE_RANGE_FIELDS | LIVE_PROFILE_FIELDS | {"live_region"}


def live_filter_fields(plan: FilterPlan) -> list[str]:
    return [item.field for item in plan.filters if item.field != "keyword"]


def filter_value_summary(item: Filter) -> str:
    if isinstance(item.value, LiveProfileCompound):
        return ",".join(
            f"{dimension.key}={'/'.join(dimension.values)}" for dimension in item.value.dimensions
        )
    if isinstance(item.value, RegionCompound):
        return ",".join(
            selection.province_code + (f"/{selection.city}" if selection.city else "")
            for selection in item.value.selections
        )
    if isinstance(item.value, NumberRange):
        return f"{item.value.min}-{item.value.max}"
    if isinstance(item.value, list):
        return ",".join(item.value)
    return str(item.value)
