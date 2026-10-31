"""Presentation catalog for the registered creator-profile fields.

The verified platform registry is the authoritative source for a field's display name, kind, unit,
period label and registered empty/absence semantics.  It holds no business values, so this catalog
is safe to serve to an authenticated product page and lets the detail view label all 81 fields
without hardcoding Chinese names in the frontend.

Evidence corrections
--------------------
Four `fans.*` fields are registered with a "连接用户" (connected users) display name:

- `fans_daily_trend`, `fans_daily_delta`, `fans_growth`, `fans_growth_rate`.

Every observed snapshot derives them from the platform's `get_author_daily_fans` response
(`request_key: daily_fans`, paths `daily` / `delta` / `fans_growth_v2` / `fans_growth_rate_v2`, leaf
key `fans_cnt`); their values track `basic.followers` (largest observed trend end 1,353,611 against
followers 1,351,784, day-over-day difference equals the matching `delta` value), while the separate
`connection_daily_trend` series ends exactly at `fans.monthly_connected_users`.  They are therefore
served here as follower data.  The verified contract artifact and the collection path are left
untouched; `docs/达人数据字段字典.md` records the discrepancy and the evidence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from .product_models import (
    ProfileFieldCatalog,
    ProfileFieldCatalogEntry,
    ProfileModuleCatalog,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .contracts import PlatformRegistry

# `(module_key, field_key) -> display name`, applied only when the registered name contradicts the
# observed data source and value shape.  Each entry must stay paired with the evidence above.
DISPLAY_NAME_CORRECTIONS: dict[tuple[str, str], str] = {
    ("fans", "fans_daily_trend"): "近30日粉丝总数趋势",
    ("fans", "fans_daily_delta"): "近30日粉丝日增量趋势",
    ("fans", "fans_growth"): "粉丝增长量",
    ("fans", "fans_growth_rate"): "粉丝增长率（万分比）",
}


def build_profile_field_catalog(
    registry: PlatformRegistry,
    platform: Literal["douyin_xingtu", "kuaishou_juxing"] = "douyin_xingtu",
) -> ProfileFieldCatalog:
    modules: list[ProfileModuleCatalog] = []
    for module in registry.modules:
        entries: list[ProfileFieldCatalogEntry] = []
        for field in module.fields:
            corrected = DISPLAY_NAME_CORRECTIONS.get((module.key, field.key))
            entries.append(
                ProfileFieldCatalogEntry(
                    key=field.key,
                    name=corrected or field.name,
                    contract_name=field.name,
                    name_source="evidence_correction" if corrected else "contract",
                    kind=field.kind,
                    unit=field.unit,
                    period_label=field.period_label,
                    empty_values=list(field.empty_values),
                    missing_source_status=field.missing_source_status,
                )
            )
        modules.append(ProfileModuleCatalog(key=module.key, fields=entries))
    return ProfileFieldCatalog(
        platform=platform,
        contract_version=registry.contract_version,
        modules=modules,
    )
