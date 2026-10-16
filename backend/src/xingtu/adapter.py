from __future__ import annotations

import asyncio
import base64
import copy
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, Protocol
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

from playwright.async_api import BrowserContext, Locator, Page
from playwright.async_api import Error as BrowserError

from .contracts import (
    Action,
    AttributeFilterEntry,
    CoverSpec,
    FeaturedCollectionSpec,
    LocatorSpec,
    PlatformRegistry,
    ProfileModuleSpec,
    SearchSpec,
    SourceSpec,
)
from .covers import FetchedCover
from .domain import (
    AudienceProfileCompound,
    CandidateDiagnostic,
    Capabilities,
    Checkpoint,
    CollectionStatus,
    CollectorError,
    ConnectionUsersCompound,
    CoverRef,
    CoverStatus,
    CreatorRef,
    DistributionValue,
    ExecutionContext,
    FeaturedCard,
    FeaturedCollectionObservation,
    FieldObservation,
    FieldStatus,
    FilterPlan,
    ModuleObservation,
    NumberRange,
    NumericValue,
    RegionCompound,
    SearchPage,
    SessionHealth,
    SessionHealthStatus,
    StructuredValue,
    uid,
)
from .normalize import consistent, number, quote
from .observer import ReplayRequest, ResponseCollector, lookup, replace_path, resolve, text_value

# Cover download runs inside the page: authenticated cookies, the unit's own line, explicit
# redirect counting and a fail-closed host re-check on every hop.
COVER_FETCH_JS = """
async (args) => {
  const allowed = new Set(args.allowedHosts);
  const timeoutMs = args.timeoutMs;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const toBase64 = (buffer) => {
    const bytes = new Uint8Array(buffer);
    let text = "";
    for (let i = 0; i < bytes.length; i += 0x8000) {
      text += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return btoa(text);
  };
  try {
    let current = args.url;
    let redirects = 0;
    for (;;) {
      if (!allowed.has(new URL(current).hostname)) return { error: "COVER_HOST_NOT_ALLOWED" };
      const response = await fetch(current, {
        redirect: "manual",
        credentials: "include",
        signal: controller.signal,
      });
      if (response.type === "opaqueredirect") return { error: "COVER_REDIRECT_OUT_OF_SCOPE" };
      if ([301, 302, 303, 307, 308].includes(response.status)) {
        if (redirects >= args.maxRedirects) return { error: "COVER_REDIRECT_LIMIT" };
        const location = response.headers.get("location");
        if (!location) return { error: "COVER_REDIRECT_LIMIT" };
        current = new URL(location, current).toString();
        redirects += 1;
        continue;
      }
      const buffer = await response.arrayBuffer();
      return {
        status: response.status,
        url: response.url || current,
        contentType: response.headers.get("content-type") || "",
        body: toBase64(buffer),
      };
    }
  } catch (error) {
    if (error && error.name === "AbortError") return { error: "COVER_TIMEOUT" };
    return { error: "COVER_FETCH_FAILED" };
  } finally {
    clearTimeout(timer);
  }
}
"""

SEARCH_PAGE_FETCH_JS = """
async (args) => {
  const response = await fetch(args.path, {
    method: args.method,
    credentials: "include",
    headers: {...args.headers, "content-type": "application/json"},
    body: JSON.stringify(args.body),
  });
  await response.arrayBuffer();
}
"""

JOIN_LOOKUP_FETCH_JS = """
async (args) => {
  const response = await fetch(args.url, {
    method: "GET",
    credentials: "include",
    headers: args.headers,
  });
  const contentType = response.headers.get("content-type") || "";
  const text = await response.text();
  return {status: response.status, contentType, text};
}
"""


class Adapter(Protocol):
    module_keys: list[str]
    module_fields: dict[str, list[str]]
    module_checkpoint_versions: dict[str, int]
    featured_keys: list[str]
    featured_card_fields: dict[str, list[str]]
    featured_checkpoint_versions: dict[str, int]
    featured_specs: dict[str, FeaturedCollectionSpec]

    async def prepare(self, plan: FilterPlan, cp: Checkpoint, ctx: ExecutionContext) -> bool:
        """Rebuild/read back original conditions. Return False only for verified invalid cursor."""
        ...

    async def search(
        self, plan: FilterPlan, cp: Checkpoint, ctx: ExecutionContext
    ) -> SearchPage: ...
    async def recheck_session(self) -> None:
        """Re-verify the protected session after an ambiguous creator-page failure."""
        ...

    def profile(self, creator: CreatorRef, ctx: ExecutionContext) -> Any: ...
    async def collect_module(
        self, key: str, creator: CreatorRef, ctx: ExecutionContext
    ) -> ModuleObservation: ...
    async def collect_featured_collections(
        self, creator: CreatorRef, cp: Checkpoint, ctx: ExecutionContext
    ) -> list[FeaturedCollectionObservation]:
        """Both default modules, each judged independently; one failure never drops the other."""
        ...

    async def fetch_cover(self, url: str, spec: CoverSpec) -> FetchedCover:
        """Fetch one cover inside the registered scope through the unit's own session."""
        ...

    async def close(self) -> None: ...


def map_bindings(bindings: dict[str, str], mapping: dict[str, dict[str, str]]) -> dict[str, str]:
    """Translate plan values into the platform's own literals (e.g. mode "content" -> "3")."""
    result = dict(bindings)
    for name, values in mapping.items():
        if name in result:
            result[name] = values.get(result[name], result[name])
    return result


def resolve_homepage(spec: SearchSpec, row: Any) -> str | None:
    """Candidate homepage from a verified response path or a verified URL template.

    The template id always comes from `id_path`; a page URL is never used as the source.
    """
    homepage = lookup(row, spec.homepage_path) if spec.homepage_path else None
    if not homepage and spec.homepage_template:
        identity = lookup(row, spec.id_path)
        if identity is not None and not isinstance(identity, bool):
            homepage = spec.homepage_template.format(platform_creator_id=str(identity))
    return homepage


def _scaled_count(value: Any, scale: int) -> str:
    scaled = value * scale
    if scaled == scaled.to_integral():
        return str(int(scaled))
    return format(scaled, "f").rstrip("0").rstrip(".")


def _json_array(values: list[Any]) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def build_expected_attribute_filters(
    plan: FilterPlan, capabilities: Capabilities
) -> list[AttributeFilterEntry]:
    """Build the exact final Xingtu request multiset from registered mappings only."""

    specs = {item.field: item for item in capabilities.fields}
    result: list[AttributeFilterEntry] = []
    for item in plan.filters:
        if item.field == "keyword":
            continue
        spec = specs.get(item.field)
        if spec is None:
            raise CollectorError("UNSUPPORTED_FILTER", item.field)
        mapping = spec.request_mapping
        options = {option.value: option.request_value for option in spec.options}
        if item.field in {"gender", "education", "yellow_v"}:
            if not isinstance(item.value, str) or item.value not in options:
                raise CollectorError("UNSUPPORTED_FILTER", item.field)
            request_value = options[item.value]
            if request_value is None:
                raise CollectorError("PLATFORM_PAGE_CHANGED", "MISSING_REQUEST_MAPPING")
            value = str(request_value)
            if item.field in {"education", "yellow_v"}:
                value = _json_array([value])
            result.append(
                AttributeFilterEntry(field_name=str(mapping["field_name"]), field_value=value)
            )
        elif item.field == "region" and isinstance(item.value, RegionCompound):
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
                result.append(
                    AttributeFilterEntry(
                        field_name=str(mapping["province_field"]),
                        field_value=_json_array(province_values),
                    )
                )
            if city_values:
                result.append(
                    AttributeFilterEntry(
                        field_name=str(mapping["city_field"]),
                        field_value=_json_array(city_values),
                    )
                )
        elif item.field == "connection_users" and isinstance(item.value, ConnectionUsersCompound):
            scale_value = mapping.get("scale")
            if isinstance(scale_value, bool) or not isinstance(scale_value, (int, str)):
                raise CollectorError("PLATFORM_PAGE_CHANGED", "INVALID_REQUEST_SCALE")
            scale = int(scale_value)
            for key in ("connected", "aware", "interested", "liked", "followed"):
                value = getattr(item.value, key)
                if value is None:
                    continue
                prefix = str(mapping[key])
                if value.min is not None:
                    result.append(
                        AttributeFilterEntry(
                            field_name=prefix + "__ge",
                            field_value=_scaled_count(value.min, scale),
                        )
                    )
                if value.max is not None:
                    result.append(
                        AttributeFilterEntry(
                            field_name=prefix + "__le",
                            field_value=_scaled_count(value.max, scale),
                        )
                    )
        elif item.field == "followers" and isinstance(item.value, NumberRange):
            scale_value = mapping.get("scale")
            if isinstance(scale_value, bool) or not isinstance(scale_value, (int, str)):
                raise CollectorError("PLATFORM_PAGE_CHANGED", "INVALID_REQUEST_SCALE")
            scale = int(scale_value)
            if item.value.min is not None:
                result.append(
                    AttributeFilterEntry(
                        field_name=str(mapping["min_field"]),
                        field_value=_scaled_count(item.value.min, scale),
                    )
                )
            if item.value.max is not None:
                result.append(
                    AttributeFilterEntry(
                        field_name=str(mapping["max_field"]),
                        field_value=_scaled_count(item.value.max, scale),
                    )
                )
        elif item.field in {"viewer_profile", "fan_profile"} and isinstance(
            item.value, AudienceProfileCompound
        ):
            dimensions = {dimension.key: dimension for dimension in spec.dimensions}
            for key in ("age", "device_brand", "city_level", "crowd"):
                values = getattr(item.value, key)
                if not values:
                    continue
                option_values = {
                    option.value: option.request_value for option in dimensions[key].options
                }
                result.append(
                    AttributeFilterEntry(
                        field_name=str(mapping[key]),
                        field_value=_json_array([option_values[value] for value in values]),
                    )
                )
            if item.value.gender:
                gender_option = next(
                    option
                    for option in dimensions["gender"].options
                    if option.value == item.value.gender
                )
                sex, threshold = str(gender_option.request_value).split(":", 1)
                result.append(
                    AttributeFilterEntry(
                        field_name=str(mapping[f"gender_{sex}"]),
                        field_value=threshold,
                    )
                )
        else:
            raise CollectorError("UNSUPPORTED_FILTER", item.field)
    return result


class BrowserAdapter:
    def __init__(
        self,
        browser: BrowserContext,
        registry: PlatformRegistry,
        account: str,
        guard: Callable[[], Awaitable[None]],
        *,
        live: bool = True,
        on_session_health: Callable[[SessionHealth], None] | None = None,
        manually_attested_account_id: str | None = None,
    ):
        registry.require_enabled(live=live)
        self.browser, self.registry = browser, registry
        self.account, self.guard, self.live = account, guard, live
        self.on_session_health = on_session_health
        self.manually_attested_account_id = manually_attested_account_id
        self.module_keys = [m.key for m in registry.modules]
        self.module_fields = {m.key: [f.key for f in m.fields] for m in registry.modules}
        self.module_checkpoint_versions = {m.key: m.checkpoint_version for m in registry.modules}
        self.featured_specs = {spec.key.value: spec for spec in registry.featured}
        self.featured_keys = [spec.key.value for spec in registry.featured]
        self.featured_card_fields = {
            spec.key.value: [f.key for f in spec.card_fields] for spec in registry.featured
        }
        self.featured_checkpoint_versions = {
            spec.key.value: spec.checkpoint_version for spec in registry.featured
        }
        self.search_page: Page | None = None
        self.detail_page: Page | None = None
        # Short poll window per cold-start bootstrap attempt. The registry's full
        # `session_boot_timeout_seconds` stays the timeout for a session already on the protected
        # surface; using it per attempt lets a single redirected hop consume the whole window.
        self.bootstrap_probe_seconds = 15.0
        # Bounded confirmation window for the bound identity.  After a same-URL reload the platform
        # renders the identity node with EMPTY text for a few tens of milliseconds while the SPA
        # hydrates, so a single read can legitimately see "present but blank".  The cap bounds the
        # whole read-and-confirm process, never a single read in isolation.
        self.identity_read_cap_seconds = 5.0
        self.identity_poll_seconds = 0.1
        self.bindings: dict[str, str] = {}
        self.prepared_result: SearchPage | None = None
        self.search_replay: ReplayRequest | None = None
        self.initial_observations: dict[str, ModuleObservation] = {}
        self.operation_metrics: dict[str, int] = {}
        self.creator_interval_seconds = 0.0
        self.required_readbacks: set[str] = set()
        self.attribute_filters: list[AttributeFilterEntry] = []

    def metric(self, key: str, amount: int = 1) -> None:
        self.operation_metrics[key] = self.operation_metrics.get(key, 0) + amount

    async def navigate(self, page: Page, url: str) -> None:
        self.metric("navigations")
        await page.goto(url, wait_until="domcontentloaded")

    def locator(self, page: Page, spec: LocatorSpec) -> Locator:
        return (
            page.frame_locator(spec.frame).locator(spec.selector)
            if spec.frame
            else page.locator(spec.selector)
        )

    def timeout_seconds(self, override: float | None = None) -> float:
        return override or self.registry.operation_timeout_seconds or 30

    async def wait_ready(
        self,
        page: Page,
        ready: LocatorSpec,
        ready_hidden: list[LocatorSpec],
        *,
        timeout: float | None = None,
    ) -> None:
        deadline = asyncio.get_running_loop().time() + self.timeout_seconds(timeout)
        while True:
            await self.check_page_errors(page)
            hidden = [await self.locator(page, item).is_visible() for item in ready_hidden]
            if not any(hidden) and await self.locator(page, ready).is_visible():
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise CollectorError("PLATFORM_PAGE_CHANGED", "PAGE_READY_TIMEOUT")
            await asyncio.sleep(0.25)

    async def check_page_errors(self, page: Page) -> None:
        spec = self.registry.session
        assert spec
        for code, locator in spec.error_selectors.items():
            if await self.locator(page, locator).is_visible():
                raise CollectorError(code, "REGISTERED_PAGE_STATE")

    async def read_locator(
        self, page: Page, spec: LocatorSpec, *, require_non_empty: bool = False
    ) -> str | list[str]:
        locator = self.locator(page, spec)
        if spec.multiple:
            values = [value.strip() for value in await locator.all_inner_texts() if value.strip()]
            values = list(dict.fromkeys(values))
            if not values:
                if spec.empty_container_selector:
                    container = self.locator(
                        page,
                        LocatorSpec(selector=spec.empty_container_selector, frame=spec.frame),
                    )
                    if await container.count() == 1:
                        return []
                raise CollectorError("MODULE_COLLECTION_FAILED", f"MISSING_SOURCE:{spec.selector}")
            return [spec.value_map.get(value, value) for value in values]
        if await locator.count() != 1:
            # The failing locator is contract metadata, not page content, so it is safe to name.
            raise CollectorError("MODULE_COLLECTION_FAILED", f"MISSING_SOURCE:{spec.selector}")
        value: str | None
        if spec.property == "value":
            value = await locator.input_value()
        elif spec.attribute:
            value = await locator.get_attribute(spec.attribute)
        else:
            value = await locator.inner_text()
        if value is None:
            raise CollectorError("MODULE_COLLECTION_FAILED", f"UNREADABLE_VALUE:{spec.selector}")
        if require_non_empty and not value.strip():
            # The node exists but carries no content yet.  The platform renders the identity node
            # blank for a few tens of milliseconds while the SPA hydrates after a same-URL reload,
            # so a caller that needs a real value - the bound identity - must not accept it.
            # Default stays False: optional fields keep their existing "empty is a value" contract
            # and the multi-value branch already drops blanks above.
            raise CollectorError("MODULE_COLLECTION_FAILED", f"UNREADABLE_VALUE:{spec.selector}")
        return spec.value_map.get(value.strip(), value.strip())

    async def actions(self, page: Page, actions: list[Action]) -> None:
        for action in actions:
            await self.guard()
            target = self.locator(page, action.locator)
            if action.kind == "click":
                await target.click()
            elif action.kind == "fill":
                await target.fill(resolve(action.value or "", self.bindings))
            elif action.kind == "select":
                await target.select_option(resolve(action.value or "", self.bindings))
            else:
                await target.evaluate("(el) => { el.scrollTop += el.clientHeight; }")
            # Pacing is separate from explicit readiness and registered response evidence.
            await asyncio.sleep(self.registry.action_interval_seconds or 0)

    async def _paced_click(self, locator: Locator, *, force: bool = False) -> None:
        await self.guard()
        await locator.click(force=force)
        await asyncio.sleep(self.registry.action_interval_seconds or 0)

    async def _selected_text(self, page: Page) -> str:
        spec = self.registry.search
        assert spec and spec.selected_condition_chips
        locator = self.locator(page, spec.selected_condition_chips)
        if await locator.count() != 1:
            raise CollectorError("PLATFORM_CONDITION_MISMATCH", "SELECTED_FILTERS_MISSING")
        return " ".join((await locator.inner_text()).split())

    async def _assert_selected(self, page: Page, expected: str) -> None:
        if expected not in await self._selected_text(page):
            raise CollectorError("PLATFORM_CONDITION_MISMATCH", expected)

    async def apply_xingtu_filters(self, page: Page, plan: FilterPlan) -> None:
        try:
            await self._apply_xingtu_filters(page, plan)
        except BrowserError as exc:
            # A registered filter locator becoming unavailable is a platform-contract drift, not
            # an unclassified Playwright failure and never a reason to submit a partial plan.
            raise CollectorError(
                "PLATFORM_PAGE_CHANGED", "REGISTERED_FILTER_CONTROL_UNAVAILABLE"
            ) from exc

    async def _apply_xingtu_filters(self, page: Page, plan: FilterPlan) -> None:
        specs = {item.field: item for item in self.registry.capabilities.fields}
        filters = {item.field: item for item in plan.filters}
        for field_name in (
            "gender",
            "region",
            "education",
            "yellow_v",
            "connection_users",
            "followers",
            "viewer_profile",
            "fan_profile",
        ):
            item = filters.get(field_name)
            if item is None:
                continue
            capability = specs[field_name]
            automation = capability.automation
            opener_selector = automation.get("opener_selector")
            if not isinstance(opener_selector, str):
                raise CollectorError("PLATFORM_PAGE_CHANGED", f"MISSING_AUTOMATION:{field_name}")
            if field_name in {"gender", "education", "yellow_v"}:
                assert isinstance(item.value, str)
                option = next(
                    (option for option in capability.options if option.value == item.value), None
                )
                if option is None:
                    raise CollectorError("UNSUPPORTED_FILTER", field_name)
                await self._paced_click(page.locator(opener_selector).first)
                await self._paced_click(
                    page.locator("ul.el-dropdown-menu:visible")
                    .last.get_by_text(option.label, exact=True)
                    .first
                )
                await self._assert_selected(page, option.label)
            elif field_name == "region" and isinstance(item.value, RegionCompound):
                provinces = {node.value: node for node in capability.region_tree}
                await self._paced_click(page.locator(opener_selector).first)
                for selection in item.value.selections:
                    province = provinces[selection.province_code]
                    province_menu = page.locator("ul.el-dropdown-menu:visible").first
                    province_row = (
                        province_menu.locator("li.xt-cascader-option")
                        .filter(has_text=province.label)
                        .first
                    )
                    if selection.city is None:
                        checkbox = province_row.locator(".xt-checkbox").first
                    else:
                        await self._paced_click(
                            province_row.locator(".xt-cascader-option__suffix").first
                        )
                        city_menu = page.locator("ul.el-dropdown-menu:visible").last
                        city_row = (
                            city_menu.locator("li.xt-cascader-option")
                            .filter(has_text=selection.city)
                            .first
                        )
                        checkbox = city_row.locator(".xt-checkbox").first
                    await self._paced_click(checkbox)
                    if "is-checked" not in (await checkbox.get_attribute("class") or ""):
                        raise CollectorError("PLATFORM_CONDITION_MISMATCH", "region")
                await page.keyboard.press("Escape")
                await self._assert_selected(page, "所在地域")
            elif field_name == "connection_users" and isinstance(
                item.value, ConnectionUsersCompound
            ):
                await self._paced_click(page.locator(opener_selector).first)
                outer_selector = str(automation["outer_selector"])
                outer = page.locator(outer_selector)
                for index, dimension in enumerate(capability.dimensions):
                    value = getattr(item.value, dimension.key)
                    if value is None:
                        continue
                    await self._paced_click(outer.locator('[role="button"]').nth(index))
                    child = page.locator(".el-popper:visible").last
                    inputs = child.locator("input")
                    await inputs.nth(0).fill(str(value.min) if value.min is not None else "")
                    await inputs.nth(1).fill(str(value.max) if value.max is not None else "")
                    await self._paced_click(
                        child.locator(str(automation["inner_confirm_selector"])).first
                    )
                await self._paced_click(
                    outer.locator(str(automation["outer_confirm_selector"])).first
                )
                await self._assert_selected(page, capability.label or "连接用户数")
            elif field_name == "followers" and isinstance(item.value, NumberRange):
                preset = next(
                    (
                        option
                        for option in capability.options
                        if option.range
                        and option.range.min == item.value.min
                        and option.range.max == item.value.max
                    ),
                    None,
                )
                await self._paced_click(page.locator(opener_selector).first)
                menu = page.locator("ul.el-dropdown-menu:visible").last
                if preset:
                    await self._paced_click(menu.get_by_text(preset.label, exact=True).first)
                    await self._assert_selected(page, preset.label)
                else:
                    input_selector = automation.get("custom_input_selector")
                    confirm_selector = automation.get("custom_confirm_selector")
                    if not isinstance(input_selector, str) or not isinstance(confirm_selector, str):
                        raise CollectorError(
                            "PLATFORM_PAGE_CHANGED", "FOLLOWERS_CUSTOM_AUTOMATION_MISSING"
                        )
                    inputs = menu.locator(input_selector)
                    await inputs.nth(0).fill(
                        str(item.value.min) if item.value.min is not None else ""
                    )
                    await inputs.nth(1).fill(
                        str(item.value.max) if item.value.max is not None else ""
                    )
                    await self._paced_click(menu.locator(confirm_selector).first)
                    await self._assert_selected(page, "粉丝数量")
            elif field_name in {"viewer_profile", "fan_profile"} and isinstance(
                item.value, AudienceProfileCompound
            ):
                await self._paced_click(page.locator(opener_selector).first)
                label_prefix = "观众" if field_name == "viewer_profile" else "粉丝"
                outer = (
                    page.locator(".el-popper:visible").filter(has_text=label_prefix + "年龄").first
                )
                values_by_key = {
                    "age": item.value.age,
                    "gender": [item.value.gender] if item.value.gender else [],
                    "device_brand": item.value.device_brand,
                    "city_level": item.value.city_level,
                    "crowd": item.value.crowd,
                }
                selected_labels: list[str] = []
                dimension_selector = automation.get("dimension_selector")
                if not isinstance(dimension_selector, str):
                    raise CollectorError(
                        "PLATFORM_PAGE_CHANGED", "PROFILE_DIMENSION_AUTOMATION_MISSING"
                    )
                dimension_controls = outer.locator(dimension_selector)
                if await dimension_controls.count() != len(capability.dimensions):
                    raise CollectorError("PLATFORM_PAGE_CHANGED", "PROFILE_DIMENSION_COUNT_CHANGED")
                for index, dimension in enumerate(capability.dimensions):
                    dimension_values = values_by_key[dimension.key]
                    if dimension_values:
                        # Selected multi-value inputs lose their placeholder and would shift an
                        # input-based index.  The five registered .el-select containers remain
                        # stable across those re-renders.
                        await self._paced_click(dimension_controls.nth(index), force=True)
                    for value in dimension_values:
                        option = next(
                            option for option in dimension.options if option.value == value
                        )
                        await self._paced_click(
                            page.locator(".el-select-dropdown:visible")
                            .last.get_by_text(option.label, exact=True)
                            .first
                        )
                        selected_labels.append(option.label)
                    if await page.locator(".el-select-dropdown:visible").count():
                        # Multi-select menus intentionally remain open after a choice.  Clicking
                        # the registered dimension label is the component's normal outside-click
                        # close path while keeping the surrounding profile popup open.
                        await self._paced_click(
                            outer.get_by_text(label_prefix + dimension.label, exact=True).first,
                            force=True,
                        )
                        if await page.locator(".el-select-dropdown:visible").count():
                            raise CollectorError(
                                "PLATFORM_PAGE_CHANGED", "PROFILE_DIMENSION_DID_NOT_CLOSE"
                            )
                    await asyncio.sleep(0)
                await self._paced_click(
                    outer.get_by_role(
                        "button", name=str(automation["outer_confirm_text"]), exact=True
                    ),
                    force=True,
                )
                for label in selected_labels:
                    await self._assert_selected(page, label)
            else:
                raise CollectorError("UNSUPPORTED_FILTER", field_name)

    async def read_account(self, page: Page) -> str:
        """Bounded wait for the account identity; the nav renders after the app shell boots."""
        spec = self.registry.session
        assert spec
        deadline = asyncio.get_running_loop().time() + self.timeout_seconds()
        while True:
            await self.check_page_errors(page)
            locator = self.locator(page, spec.account)
            try:
                if await locator.count() == 1 and await locator.is_visible():
                    value = (await locator.inner_text()).strip()
                    if value:
                        return value
            except BrowserError:
                pass
            if asyncio.get_running_loop().time() >= deadline:
                raise CollectorError("ACCOUNT_LOGIN_REQUIRED", "ACCOUNT_LOCATOR_UNREADABLE")
            await asyncio.sleep(1.0)

    def publish_session_health(self, health: SessionHealth) -> SessionHealth:
        if self.on_session_health:
            self.on_session_health(health)
        return health

    async def inspect_session(self, page: Page, *, timeout: float | None = None) -> SessionHealth:
        """Observe session state without collapsing absence of proof into logout.

        The loop accepts only registered page signals.  A protected page with a different
        account is a valid session for the wrong account; a timeout with neither positive login
        evidence nor a protected account is explicitly indeterminate.
        """
        await self.guard()
        spec = self.registry.session
        assert spec
        deadline = asyncio.get_running_loop().time() + self.timeout_seconds(timeout)
        protected_seen = False
        while True:
            for code, locator_spec in spec.error_selectors.items():
                if not await self.locator(page, locator_spec).is_visible():
                    continue
                if code == "ACCOUNT_LOGIN_REQUIRED":
                    return self.publish_session_health(
                        SessionHealth(
                            status=SessionHealthStatus.LOGIN_REQUIRED,
                            expected_account_id=self.account,
                            login_page_verified=True,
                            evidence_reason="REGISTERED_LOGIN_PAGE",
                        )
                    )
                if code == "PLATFORM_SECURITY_CHALLENGE":
                    return self.publish_session_health(
                        SessionHealth(
                            status=SessionHealthStatus.SECURITY_CHALLENGE,
                            expected_account_id=self.account,
                            challenge_verified=True,
                            evidence_reason="REGISTERED_SECURITY_CHALLENGE",
                        )
                    )
                raise CollectorError(code, "REGISTERED_PAGE_STATE")
            protected_seen = (
                protected_seen or await self.locator(page, spec.protected_ready).is_visible()
            )
            if protected_seen:
                locator = self.locator(page, spec.account)
                try:
                    if await locator.count() == 1 and await locator.is_visible():
                        raw = (
                            await locator.get_attribute(spec.account.attribute)
                            if spec.account.attribute
                            else await locator.inner_text()
                        )
                        observed = (raw or "").strip()
                        if observed:
                            status = (
                                SessionHealthStatus.VALID
                                if observed == self.account
                                else SessionHealthStatus.ACCOUNT_MISMATCH
                            )
                            return self.publish_session_health(
                                SessionHealth(
                                    status=status,
                                    expected_account_id=self.account,
                                    observed_account_id=observed,
                                    protected_page_verified=True,
                                    evidence_reason=(
                                        "PROTECTED_PAGE_AND_ACCOUNT_VERIFIED"
                                        if status == SessionHealthStatus.VALID
                                        else "PROTECTED_PAGE_WRONG_ACCOUNT"
                                    ),
                                )
                            )
                except BrowserError:
                    pass
            if asyncio.get_running_loop().time() >= deadline:
                # The attestation is a last resort, never a fast path.  It is granted only after
                # the bounded window has actually elapsed with the protected surface continuously
                # visible and the identity locator still unreadable -- a UI that no longer renders
                # the account at all.  Returning it as soon as the protected marker appeared used
                # to certify the session while the app shell was still booting, so the caller
                # started driving the page before it was ready: the platform then navigated the
                # business surface away mid-action (observed: `Locator.fill` timing out while the
                # page sat on `https://www.xingtu.cn/?redirect_uri=/ad/creator/market`), and the
                # task parked in WAITING_FOR_RESOURCE with zero candidates.
                # A readable identity always wins over the attestation, so genuine wrong-account
                # detection is unaffected.
                if protected_seen and self.manually_attested_account_id == self.account:
                    return self.publish_session_health(
                        SessionHealth(
                            status=SessionHealthStatus.VALID,
                            expected_account_id=self.account,
                            observed_account_id=self.account,
                            protected_page_verified=True,
                            evidence_reason="MANUALLY_ATTESTED_UNIQUE_ACCOUNT",
                        )
                    )
                return self.publish_session_health(
                    SessionHealth(
                        status=SessionHealthStatus.INDETERMINATE,
                        expected_account_id=self.account,
                        protected_page_verified=protected_seen,
                        evidence_reason=(
                            "PROTECTED_PAGE_ACCOUNT_UNREADABLE"
                            if protected_seen
                            else "NO_REGISTERED_SESSION_SIGNAL"
                        ),
                    )
                )
            await asyncio.sleep(0.25)

    async def check_session(self, page: Page, *, timeout: float | None = None) -> SessionHealth:
        health = await self.inspect_session(page, timeout=timeout)
        if health.status == SessionHealthStatus.VALID:
            return health
        code = {
            SessionHealthStatus.LOGIN_REQUIRED: "ACCOUNT_LOGIN_REQUIRED",
            SessionHealthStatus.ACCOUNT_MISMATCH: "ACCOUNT_MISMATCH",
            SessionHealthStatus.SECURITY_CHALLENGE: "PLATFORM_SECURITY_CHALLENGE",
            SessionHealthStatus.INDETERMINATE: "SESSION_INDETERMINATE",
        }[health.status]
        raise CollectorError(code, health.evidence_reason)

    async def recheck_session(self) -> None:
        if not self.search_page:
            raise CollectorError("SESSION_INDETERMINATE", "SEARCH_PAGE_NOT_AVAILABLE")
        await self.check_session(self.search_page)

    async def prepare(self, plan: FilterPlan, cp: Checkpoint, ctx: ExecutionContext) -> bool:
        self.registry.capabilities.validate_plan(plan, live=self.live)
        spec = self.registry.search
        assert spec
        if cp.cursor is not None and not spec.resume_supported:
            return False
        self.bindings = {
            **spec.default_bindings,
            "conditions_digest": plan.digest(),
            "cursor": cp.cursor if cp.cursor is not None else spec.initial_cursor,
            "session_version": str(ctx.session_version),
            "sort": plan.sort.key,
        }
        for f in plan.filters:
            self.bindings[f.field] = text_value(f.model_dump(mode="json")["value"])
            self.bindings[f"{f.field}.unit"] = f.unit or ""
            self.bindings[f"{f.field}.currency"] = f.currency or ""
            self.bindings[f"{f.field}.cooperation_form"] = f.cooperation_form or ""
            if isinstance(f.value, NumberRange):
                self.bindings[f"{f.field}.min"] = (
                    str(f.value.min) if f.value.min is not None else ""
                )
                self.bindings[f"{f.field}.max"] = (
                    str(f.value.max) if f.value.max is not None else ""
                )
        self.attribute_filters = (
            build_expected_attribute_filters(plan, self.registry.capabilities)
            if any(request.attribute_filter_match for request in spec.requests)
            else []
        )
        required = set() if spec.fixed_sort else {"sort"}
        for f in plan.filters:
            if spec.dynamic_filter_executor and f.field != "keyword":
                continue
            required.update(
                {f"{f.field}.min", f"{f.field}.max"}
                if isinstance(f.value, NumberRange)
                else {f.field}
            )
            if f.field == "quote":
                required.update({"quote.unit", "quote.currency", "quote.cooperation_form"})
            if f.field == "keyword":
                self.bindings["keyword_mode"] = "content"
                required.add("keyword_mode")
        self.required_readbacks = required
        # Plan values become the platform's own literals only after every binding exists.
        self.bindings = map_bindings(self.bindings, spec.binding_values)
        if not required <= set(spec.readback):
            raise CollectorError("PLATFORM_PAGE_CHANGED", "INCOMPLETE_CONDITION_READBACK")
        request_bindings = {
            value[1:]
            for request in spec.requests
            for value in request.request_match.values()
            if value.startswith("$")
        }
        # Every accepted condition must participate in final request correlation.
        if not required <= request_bindings:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "INCOMPLETE_REQUEST_CONDITIONS")
        if not self.search_page:
            self.search_page = await self.browser.new_page()
            self.search_page.set_default_timeout(self.timeout_seconds() * 1000)
        page = self.search_page
        # Start from the protected business page.  The SSO entry always renders a login form even
        # when the parent SSO session can still bootstrap Xingtu, so showing it first misrepresents
        # a reusable session as logged out.
        #
        # Cold start is not a single navigation.  Observed 2026-10-06: the first hop to a
        # registered business page is regularly redirected to `/?redirect_uri=...`, and the
        # account/protected markers only become readable after the platform's own bootstrap runs
        # on a later attempt.  A single attempt therefore reported a reusable session as
        # indeterminate and the segment spun in WAITING_FOR_RESOURCE with zero candidates, while a
        # probe that alternated business pages recovered within seconds.  Keep the same bounded,
        # registered-URL recovery here: the first attempt gets the full boot timeout, later
        # attempts get short ones, and the decisive verdict stays with `check_session`.
        session = self.registry.session
        assert session
        await self._bootstrap_session(page, spec.entry_url, session.entry_url)
        await self.check_session(page)
        # Reset and v2 component actions intentionally stay outside the response collector: each
        # selection auto-searches and is legitimate intermediate traffic.
        if spec.dynamic_filter_executor and spec.clear_selected:
            clear = self.locator(page, spec.clear_selected)
            if await clear.count() == 1 and await clear.is_visible():
                await self._paced_click(clear)
        await self.actions(page, spec.reset_actions)
        if spec.dynamic_filter_executor == "xingtu-market-v2":
            await self.actions(page, spec.apply_actions)
            await self.apply_xingtu_filters(page, plan)
            if not spec.final_actions:
                raise CollectorError("PLATFORM_PAGE_CHANGED", "FINAL_SEARCH_ACTION_MISSING")
            self.prepared_result = await self._search_operation(
                page, spec.final_actions, plan, cp, ctx
            )
        else:
            self.prepared_result = await self._search_operation(
                page, spec.apply_actions, plan, cp, ctx
            )
        return True

    async def _bootstrap_session(
        self,
        page: Page,
        business_url: str,
        sso_url: str,
        attempts: int = 4,
    ) -> SessionHealth:
        """Bounded cold-start bootstrap over the two registered session URLs only.

        No selector is invented here: the probe is the registry's own account/protected locators,
        and the recovery alternates the registered business entry with the registered SSO entry so
        the platform can re-issue its business session.  A genuine logout still ends in
        ``check_session`` raising ``ACCOUNT_LOGIN_REQUIRED``.
        """
        health: SessionHealth | None = None
        session_spec = self.registry.session
        registered = list(session_spec.business_urls) if session_spec else []
        targets = [business_url] + [url for url in registered if url != business_url]
        for attempt in range(1, attempts + 1):
            if attempt > 1 and attempt % 2 == 0:
                # Bounce through the registered SSO entry so the parent session can hand off a
                # fresh business session, mirroring the verified manual recovery flow.
                await self.navigate(page, sso_url)
            target = targets[(attempt - 1) % len(targets)]
            await self.navigate(page, target)
            # Every bootstrap probe uses the short poll window.  The full session boot timeout is
            # for a session already sitting on the protected surface; a first hop that the platform
            # redirects away never becomes readable, and waiting the full timeout only burns the
            # window in which a retry could still succeed (observed: 180s spent on an already
            # redirected page, then WAITING_FOR_RESOURCE with zero candidates).
            health = await self.inspect_session(page, timeout=self.bootstrap_probe_seconds)
            if health.status != SessionHealthStatus.INDETERMINATE:
                return health
            await asyncio.sleep(2.0)
        assert health
        return health

    async def readback(self, page: Page) -> None:
        spec = self.registry.search
        assert spec
        for key in self.required_readbacks:
            locator = spec.readback.get(key)
            if locator is None or key not in self.bindings:
                raise CollectorError("PLATFORM_PAGE_CHANGED", "MISSING_READBACK_BINDING")
            if await self.read_locator(page, locator) != self.bindings[key]:
                raise CollectorError("PLATFORM_CONDITION_MISMATCH", key)

    async def _search_operation(
        self,
        page: Page,
        actions: list[Action],
        plan: FilterPlan,
        cp: Checkpoint,
        ctx: ExecutionContext,
        *,
        replay: ReplayRequest | None = None,
    ) -> SearchPage:
        spec = self.registry.search
        assert spec
        operation = uid()
        async with ResponseCollector(
            page,
            spec.requests,
            self.bindings,
            self.timeout_seconds(),
            self.registry.response_body_max_bytes or 1,
            metrics=self.operation_metrics,
            attribute_filters=self.attribute_filters,
        ) as capture:
            if replay:
                await self.replay_search_page(page, replay, spec)
            else:
                await self.actions(page, actions)
            await self.wait_ready(page, spec.ready, spec.ready_hidden)
            await self.check_session(page)
            await self.readback(page)
            data, failures = await capture.read()
            observed_replay = capture.replays.get(spec.result_request_key)
            if observed_replay:
                self.search_replay = observed_replay
            if any(s.required and s.key in failures for s in spec.requests):
                raise CollectorError("PLATFORM_PAGE_CHANGED", "SEARCH_RESPONSE_FAILED")
            result = data.get(spec.result_request_key)
            rows = lookup(result, spec.candidates_path)
            if not isinstance(rows, list):
                raise CollectorError("PLATFORM_PAGE_CHANGED", "SEARCH_SCHEMA_MISMATCH")
            candidates: list[CreatorRef] = []
            unidentified: list[CandidateDiagnostic] = []
            for index, row in enumerate(rows):
                source_ref = f"{operation}:{spec.candidates_path}.{index}"
                identity = lookup(row, spec.id_path)
                homepage = resolve_homepage(spec, row)
                if (
                    isinstance(identity, bool)
                    or not isinstance(identity, (str, int))
                    or not str(identity).strip()
                ):
                    # An unreadable identity is diagnosed and skipped; it never becomes a candidate.
                    unidentified.append(
                        CandidateDiagnostic(
                            reason="CANDIDATE_IDENTITY_UNREADABLE",
                            detail=spec.id_path,
                            source_ref=source_ref,
                            operation_id=operation,
                        )
                    )
                    continue
                if not isinstance(homepage, str) or not homepage.strip():
                    unidentified.append(
                        CandidateDiagnostic(
                            reason="UNVERIFIED_HOMEPAGE",
                            detail=spec.homepage_path or spec.homepage_template or "homepage",
                            source_ref=source_ref,
                            operation_id=operation,
                        )
                    )
                    continue
                try:
                    self.registry.validate_homepage(homepage)
                except CollectorError:
                    unidentified.append(
                        CandidateDiagnostic(
                            reason="UNVERIFIED_HOMEPAGE",
                            detail="host or path outside verified scope",
                            source_ref=source_ref,
                            operation_id=operation,
                        )
                    )
                    continue
                candidates.append(
                    CreatorRef(
                        platform_creator_id=str(identity),
                        verified_homepage=homepage,
                        source_refs=[source_ref],
                    )
                )
            end = lookup(result, spec.exhausted_path)
            if end is None:
                raise CollectorError("PLATFORM_PAGE_CHANGED", "MISSING_ENDPOINT_STATE")
            exhausted = text_value(end) == spec.exhausted_value
            next_value = lookup(result, spec.next_path)
            next_checkpoint: str | None = None
            if not exhausted:
                if spec.pagination == "page":
                    if isinstance(next_value, bool) or not isinstance(next_value, int | str):
                        raise CollectorError("PLATFORM_PAGE_CHANGED", "INVALID_PAGE_NUMBER")
                    try:
                        next_checkpoint = str(int(next_value) + 1)
                    except ValueError as exc:
                        raise CollectorError(
                            "PLATFORM_PAGE_CHANGED", "INVALID_PAGE_NUMBER"
                        ) from exc
                elif next_value is not None:
                    next_checkpoint = str(next_value)
            return SearchPage(
                candidates=candidates,
                current_checkpoint=cp.cursor,
                next_checkpoint=next_checkpoint,
                conditions_digest=plan.digest(),
                search_generation=cp.search_generation,
                operation_id=operation,
                exhausted=exhausted,
                exhaustion_evidence_refs=[f"{operation}:{spec.exhausted_path}"]
                if exhausted
                else [],
                unidentified=unidentified,
            )

    async def replay_search_page(self, page: Page, replay: ReplayRequest, spec: SearchSpec) -> None:
        result_request = next(item for item in spec.requests if item.key == spec.result_request_key)
        parsed = urlsplit(replay.url)
        if (
            replay.method != "POST"
            or parsed.scheme != "https"
            or parsed.hostname != result_request.host
            or parsed.path != result_request.path
            or urlsplit(page.url).hostname != result_request.host
        ):
            raise CollectorError("PLATFORM_PAGE_CHANGED", "PAGINATION_REPLAY_OUT_OF_SCOPE")
        body = copy.deepcopy(replay.body)
        for path, expected in result_request.request_match.items():
            if expected == "$cursor":
                replace_path(body, path, self.bindings["cursor"])
        await page.evaluate(
            SEARCH_PAGE_FETCH_JS,
            {
                "path": result_request.path,
                "method": result_request.method,
                "body": body,
                "headers": replay.headers,
            },
        )

    async def search(self, plan: FilterPlan, cp: Checkpoint, ctx: ExecutionContext) -> SearchPage:
        assert self.search_page and self.registry.search
        spec = self.registry.search
        if cp.cursor is not None and spec.single_page_only:
            # A capability boundary is not evidence that the platform has no more results.
            raise CollectorError("SEARCH_CAPABILITY_LIMIT", "PAGINATION_NOT_VERIFIED")
        await self.check_session(self.search_page)
        await self.readback(self.search_page)
        if self.prepared_result:
            result, self.prepared_result = self.prepared_result, None
            return result
        self.bindings["cursor"] = cp.cursor or ""
        if spec.next_page_mode == "page_fetch":
            if (
                not cp.cursor
                or not cp.cursor.isdigit()
                or int(cp.cursor) < 2
                or (
                    not spec.page_fetch_continuous_verified
                    and (
                        not spec.page_fetch_max_verified
                        or int(cp.cursor) > spec.page_fetch_max_verified
                    )
                )
            ):
                raise CollectorError("SEARCH_CAPABILITY_LIMIT", "PAGE_FETCH_LIMIT_NOT_VERIFIED")
            if not self.search_replay:
                raise CollectorError("PLATFORM_PAGE_CHANGED", "PAGINATION_REQUEST_NOT_OBSERVED")
            return await self._search_operation(
                self.search_page, [], plan, cp, ctx, replay=self.search_replay
            )
        return await self._search_operation(self.search_page, spec.next_actions, plan, cp, ctx)

    @asynccontextmanager
    async def profile(self, creator: CreatorRef, ctx: ExecutionContext) -> AsyncIterator[None]:
        self.registry.validate_homepage(creator.verified_homepage)
        page = await self.browser.new_page()
        self.detail_page = page
        page.set_default_timeout(self.timeout_seconds() * 1000)
        try:
            await self.guard()
            spec = self.registry.modules[0]
            initial_specs = [
                module
                for module in self.registry.modules
                if module.basic or module.capture_on_profile_load
            ]
            initial_requests = [request for module in initial_specs for request in module.requests]
            operation = uid()
            initial_defaults = {
                key: value
                for module in initial_specs
                for key, value in module.default_bindings.items()
            }
            bindings = {
                **self.bindings,
                **initial_defaults,
                "creator_id": creator.platform_creator_id,
                "module": spec.key,
            }
            async with ResponseCollector(
                page,
                initial_requests,
                bindings,
                self.timeout_seconds(spec.timeout_seconds),
                self.registry.response_body_max_bytes or 1,
                metrics=self.operation_metrics,
            ) as capture:
                # Register before navigation, including the homepage's initial business responses.
                await self.navigate(page, creator.verified_homepage)
                self.registry.validate_homepage(page.url)
                await self.check_session(page)
                await self.verify_identity(page, creator)
                await self.actions(page, spec.actions)
                await self.wait_ready(page, spec.ready, spec.ready_hidden)
                await self._wake_unresolved_modules(page, capture, initial_specs, spec)
                data, failures = await capture.read()
                self.initial_observations = {
                    module.key: await self.parse_module(
                        page, module, creator, ctx, operation, data, failures
                    )
                    for module in initial_specs
                }
            yield
        finally:
            self.detail_page = None
            self.initial_observations = {}
            await page.close()

    async def _wake_unresolved_modules(
        self,
        page: Page,
        capture: ResponseCollector,
        modules: list[ProfileModuleSpec],
        shared: ProfileModuleSpec,
    ) -> None:
        """Trigger a module's own registered actions when the page load did not emit its responses.

        ``profile`` collects every homepage module from one registered window. A module that
        declares ``capture_on_profile_load`` is expected to be emitted by the bare page load; the
        SPA only emits some of them after the registered tab interaction, so those modules declare
        that interaction as their own ``actions`` and it runs here, still inside the same window and
        after the observers were registered.

        The gate is what keeps this additive: a module whose required responses already arrived is
        left untouched, so a creator whose homepage prefetches the endpoint gets no extra click and
        no duplicated request. Readiness stays evidence-based - ``wait_ready`` re-asserts the
        module's registered ready selector and ``read`` still performs the bounded settle wait.
        """

        for module in modules:
            if module is shared or not module.actions:
                continue
            if not any(
                spec.required and spec.key not in capture.results for spec in module.requests
            ):
                continue
            await self.actions(page, module.actions)
            await self.wait_ready(page, module.ready, module.ready_hidden)

    async def verify_identity(self, page: Page, creator: CreatorRef) -> None:
        """Require the page's identity to be a non-empty, confirmed value. Bounded, fail closed.

        The whole read-and-confirm process is bounded by ``identity_read_cap_seconds``: a page that
        never exposes a usable identity still ends in ``IDENTITY_UNREADABLE`` rather than looping.
        A stable value that differs from the expected creator stays ``IDENTITY_MISMATCH``.
        """

        try:
            await asyncio.wait_for(
                self._confirm_identity(page, creator),
                timeout=self.identity_read_cap_seconds,
            )
        except TimeoutError as exc:
            # Bounded expiry, not a swallowed error: the identity never became usable in time.
            raise CollectorError("PLATFORM_PAGE_CHANGED", "IDENTITY_UNREADABLE") from exc

    async def _confirm_identity(self, page: Page, creator: CreatorRef) -> None:
        """Read the bound identity until it is non-empty and confirmed; the caller bounds time.

        The expected id is a known constant, so a read that equals it cannot be a hydration
        transient and is accepted immediately - the common path costs exactly one read.  Only a
        non-empty *unexpected* value pays for a second, confirming read, which prevents a transient
        wrong value from being reported as a wrong creator.  Blank reads are never a value and are
        retried until the caller's deadline expires.
        """

        session = self.registry.session
        assert session
        expected = creator.platform_creator_id
        unexpected: str | None = None
        while True:
            try:
                identity = await self.read_locator(page, session.identity, require_non_empty=True)
            except CollectorError:
                identity = None
            if isinstance(identity, str):
                if identity == expected:
                    return
                if identity == unexpected:
                    raise CollectorError("CREATOR_INVALID", "IDENTITY_MISMATCH")
                unexpected = identity
            await asyncio.sleep(self.identity_poll_seconds)

    async def source(
        self, page: Page, source: SourceSpec, responses: dict[str, Any], failures: dict[str, str]
    ) -> Any:
        if source.kind == "dom":
            if not source.locator:
                raise CollectorError("PLATFORM_PAGE_CHANGED", "MISSING_DOM_CONTRACT")
            return await self.read_locator(page, source.locator)
        if not source.request_key or not source.path:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "MISSING_RESPONSE_CONTRACT")
        if source.request_key in failures:
            raise CollectorError("MODULE_COLLECTION_FAILED", failures[source.request_key])
        value = lookup(responses.get(source.request_key), source.path)
        if value is None:
            raise CollectorError("MODULE_COLLECTION_FAILED", "MISSING_SOURCE")
        return value

    async def collect_module(
        self, key: str, creator: CreatorRef, ctx: ExecutionContext
    ) -> ModuleObservation:
        assert self.detail_page
        page = self.detail_page
        await self.check_session(page)
        await self.verify_identity(page, creator)
        if key in self.initial_observations:
            return self.initial_observations.pop(key)
        spec = next(m for m in self.registry.modules if m.key == key)
        operation = uid()
        bindings = {
            **self.bindings,
            **spec.default_bindings,
            "creator_id": creator.platform_creator_id,
            "module": key,
        }
        async with ResponseCollector(
            page,
            spec.requests,
            bindings,
            self.timeout_seconds(spec.timeout_seconds),
            self.registry.response_body_max_bytes or 1,
            metrics=self.operation_metrics,
        ) as capture:
            if spec.entry:
                # Registered module entry page; identity was verified before leaving the homepage.
                entry = urljoin(creator.verified_homepage, spec.entry)
                self.registry.validate_platform_url(entry)
                await self.navigate(page, entry)
                self.registry.validate_platform_url(page.url)
                await self.check_session(page)
            await self.actions(page, spec.actions)
            await self.wait_ready(page, spec.ready, spec.ready_hidden)
            await self.check_session(page)
            data, failures = await capture.read()
            return await self.parse_module(page, spec, creator, ctx, operation, data, failures)

    async def collection_absence(
        self,
        page: Page,
        spec: FeaturedCollectionSpec,
        operation: str,
        data: dict[str, Any],
        failures: dict[str, str],
    ) -> tuple[FieldStatus, str] | None:
        """Registered module-level absence evidence; a missing element never proves absence."""
        absence = spec.absence
        if not absence:
            return None
        # Incremental loads keep a list of bodies; module state is read from the latest body.
        latest = {
            key: (value[-1] if isinstance(value, list) and value else value)
            for key, value in data.items()
        }
        try:
            raw = await self.source(page, absence.probe, latest, failures)
        except CollectorError as exc:
            if exc.code != "MODULE_COLLECTION_FAILED":
                raise
            return None
        text = text_value(raw)
        for values, status in (
            (absence.permission_values, FieldStatus.NO_PERMISSION),
            (absence.empty_values, FieldStatus.NO_DATA),
            (absence.not_provided_values, FieldStatus.NOT_PROVIDED),
        ):
            if text in values:
                probe_ref = absence.probe.path or (
                    absence.probe.locator.selector if absence.probe.locator else "probe"
                )
                return status, f"{operation}:{spec.key.value}:{probe_ref}"
        return None

    _ABSENCE_STATUS = {
        FieldStatus.NO_PERMISSION: CollectionStatus.NO_PERMISSION,
        FieldStatus.NO_DATA: CollectionStatus.EMPTY,
        FieldStatus.NOT_PROVIDED: CollectionStatus.NOT_PROVIDED,
    }

    @staticmethod
    def featured_spec_local_reason(error: CollectorError) -> str | None:
        """Return a reason when a featured-collection failure is provably THIS collection's.

        Only two cases qualify, and nothing else is ever downgraded:

        * ``MODULE_COLLECTION_FAILED`` - the registered module's own response/schema/read failed,
          which is scoped to the collection that declared those requests.
        * ``PLATFORM_PAGE_CHANGED: PAGE_READY_TIMEOUT`` - ``PAGE_READY_TIMEOUT`` has exactly one
          producer (``wait_ready``) and it fires only when the caller's own ``ready`` selector did
          not appear, so inside a featured iteration it cannot describe any surface other than this
          collection's.

        Session loss, verification challenges, lease loss and creator-identity failures are
        deliberately absent: they are global and must keep aborting the whole creator.
        """

        if error.code == "MODULE_COLLECTION_FAILED":
            return error.reason or "MODULE_COLLECTION_FAILED"
        if error.code == "PLATFORM_PAGE_CHANGED" and error.reason == "PAGE_READY_TIMEOUT":
            return "PAGE_READY_TIMEOUT"
        return None

    async def collect_featured_collections(
        self, creator: CreatorRef, cp: Checkpoint, ctx: ExecutionContext
    ) -> list[FeaturedCollectionObservation]:
        assert self.detail_page
        page = self.detail_page
        await self.check_session(page)
        await self.verify_identity(page, creator)
        observations: list[FeaturedCollectionObservation] = []
        for spec in self.registry.featured:
            candidate = next(
                (
                    item
                    for item in cp.candidates
                    if item.ref.platform_creator_id == creator.platform_creator_id
                ),
                None,
            )
            previous = candidate.collections.get(spec.key.value) if candidate else None
            if previous is not None and previous.complete:
                continue
            try:
                self.metric("featured_loads")
                observations.append(await self._collect_featured(page, spec, creator, ctx))
            except CollectorError as exc:
                # One module failing must never drop the other module's committed result. Only a
                # failure provably scoped to this collection becomes a recorded failure here; every
                # other code (session, challenge, lease, identity) stays fatal and is re-raised.
                reason = self.featured_spec_local_reason(exc)
                if reason is None:
                    raise
                observations.append(self._featured_failure(spec, creator, ctx, reason))
        return observations

    def _featured_failure(
        self,
        spec: FeaturedCollectionSpec,
        creator: CreatorRef,
        ctx: ExecutionContext,
        reason: str,
    ) -> FeaturedCollectionObservation:
        operation = uid()
        return FeaturedCollectionObservation(
            creator_ref=creator,
            collection_type=spec.key,
            module_label=spec.module_label,
            page_url=self.detail_page.url if self.detail_page else creator.verified_homepage,
            status=CollectionStatus.FAILED,
            operation_id=operation,
            contract_version=self.registry.contract_version,
            failure_reason=reason,
        )

    async def _collect_featured(
        self,
        page: Page,
        spec: FeaturedCollectionSpec,
        creator: CreatorRef,
        ctx: ExecutionContext,
    ) -> FeaturedCollectionObservation:
        operation = uid()
        bindings = {
            **self.bindings,
            **spec.default_bindings,
            "creator_id": creator.platform_creator_id,
            "collection": spec.key.value,
        }
        async with ResponseCollector(
            page,
            spec.requests,
            bindings,
            self.timeout_seconds(spec.timeout_seconds),
            self.registry.response_body_max_bytes or 1,
            metrics=self.operation_metrics,
        ) as capture:
            if spec.reload_homepage:
                await self.navigate(page, creator.verified_homepage)
                self.registry.validate_homepage(page.url)
                await self.check_session(page)
                await self.verify_identity(page, creator)
            elif spec.entry:
                # Registered module entry; identity was verified on the homepage before leaving it.
                entry = urljoin(creator.verified_homepage, spec.entry)
                self.registry.validate_platform_url(entry)
                await self.navigate(page, entry)
                self.registry.validate_platform_url(page.url)
                await self.check_session(page)
            await self.actions(page, spec.actions)
            await self.wait_ready(page, spec.ready, spec.ready_hidden)
            await self.check_session(page)
            if spec.response_settle_seconds:
                await asyncio.sleep(spec.response_settle_seconds)
            data, failures = await capture.read()
            replays = dict(capture.replays)
        page_url = page.url
        absence = await self.collection_absence(page, spec, operation, data, failures)
        if absence is not None:
            status, evidence_ref = self._ABSENCE_STATUS[absence[0]], absence[1]
            return FeaturedCollectionObservation(
                creator_ref=creator,
                collection_type=spec.key,
                module_label=spec.module_label,
                page_url=page_url,
                status=status,
                operation_id=operation,
                contract_version=self.registry.contract_version,
                evidence_refs=[evidence_ref],
            )
        failed_required = [
            f"{request.key}={failures[request.key]}"
            for request in spec.requests
            if request.required and request.key in failures
        ]
        if failed_required:
            raise CollectorError(
                "MODULE_COLLECTION_FAILED",
                "FEATURED_RESPONSE_FAILED:" + ",".join(sorted(failed_required)),
            )
        raw_result = data.get(spec.result_request_key)
        # A registered incremental load contributes several correlated bodies for the same key.
        bodies = raw_result if isinstance(raw_result, list) else [raw_result]
        rows: list[Any] = []
        for body in bodies:
            part = lookup(body, spec.cards_path)
            if not isinstance(part, list):
                raise CollectorError("MODULE_COLLECTION_FAILED", "FEATURED_SCHEMA_MISMATCH")
            rows.extend(part)
        await self.complete_joined_card_sources(page, spec, rows, data, replays)
        # The latest in-module load reports the end state; an earlier page may still say "more".
        load_complete = bool(bodies) and (
            text_value(lookup(bodies[-1], spec.load_complete_path)) == spec.load_complete_value
        )
        period = spec.default_period_label
        if spec.default_period_path:
            period = next(
                (
                    text_value(value)
                    for body in bodies
                    if (value := lookup(body, spec.default_period_path)) is not None
                ),
                None,
            )
        set_key = None
        if spec.set_key_path:
            set_key = next(
                (
                    text_value(value)
                    for body in bodies
                    if (value := lookup(body, spec.set_key_path)) is not None
                ),
                None,
            )
        cards: list[FeaturedCard] = []
        seen: set[str] = set()
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                # A row outside the declared card shape is a failed read, never an empty card.
                raise CollectorError("MODULE_COLLECTION_FAILED", "FEATURED_CARD_SCHEMA")
            card = await self.parse_card(page, spec, row, index, operation, ctx, data, failures)
            dedupe = card.identity_ref or card.local_key
            if dedupe:
                if dedupe in seen:
                    # A repeated in-module load of the same card is counted, never appended twice.
                    existing = next(c for c in cards if (c.identity_ref or c.local_key) == dedupe)
                    existing.reload_count += 1
                    continue
                seen.add(dedupe)
            card.position = len(cards)
            cards.append(card)
        gaps = list(spec.coverage_gaps) + self.registry.coverage_gaps
        if not load_complete:
            gaps.append("module_load_end_unverified")
        if not cards and load_complete:
            # Registered endpoint state proves the module finished loading with no card.
            return FeaturedCollectionObservation(
                creator_ref=creator,
                collection_type=spec.key,
                module_label=spec.module_label,
                page_url=page_url,
                default_period_label=period,
                status=CollectionStatus.EMPTY,
                load_complete=True,
                coverage_gaps=gaps,
                set_key=set_key,
                operation_id=operation,
                contract_version=self.registry.contract_version,
                evidence_refs=[f"{operation}:{spec.load_complete_path}"],
            )
        observation = FeaturedCollectionObservation(
            creator_ref=creator,
            collection_type=spec.key,
            module_label=spec.module_label,
            page_url=page_url,
            default_period_label=period,
            status=CollectionStatus.INCOMPLETE,
            load_complete=load_complete,
            cards=cards,
            coverage_gaps=gaps,
            coverage_notes=self._coverage_notes(spec, cards),
            set_key=set_key,
            operation_id=operation,
            contract_version=self.registry.contract_version,
        )
        observation._settle_status()
        return observation

    async def complete_joined_card_sources(
        self,
        page: Page,
        spec: FeaturedCollectionSpec,
        rows: list[Any],
        data: dict[str, Any],
        replays: dict[str, ReplayRequest],
    ) -> None:
        """Replay an observed same-origin lookup only for card joins the lazy UI omitted."""
        for field in spec.card_fields:
            source = field.source
            if not (
                source.request_key
                and source.join_row_path
                and source.join_response_path
                and source.join_request_path
            ):
                continue
            replay = replays.get(source.request_key)
            if not replay or replay.method != "GET":
                continue
            request_spec = next(
                (request for request in spec.requests if request.key == source.request_key), None
            )
            if request_spec is None:
                continue
            raw_bodies = data.get(source.request_key)
            joined = raw_bodies if isinstance(raw_bodies, list) else [raw_bodies]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                join_value = lookup(row, source.join_row_path)
                if join_value is None or any(
                    body is not None and lookup(body, source.join_response_path) == join_value
                    for body in joined
                ):
                    continue
                params = copy.deepcopy(replay.body)
                try:
                    replace_path(params, source.join_request_path, text_value(join_value))
                    parsed = urlsplit(replay.url)
                    replay_url = urlunsplit(
                        (
                            parsed.scheme,
                            parsed.netloc,
                            parsed.path,
                            urlencode(params, doseq=True),
                            "",
                        )
                    )
                    response = await page.evaluate(
                        JOIN_LOOKUP_FETCH_JS,
                        {"url": replay_url, "headers": replay.headers},
                    )
                    encoded = str(response.get("text", "")).encode()
                    if (
                        int(response.get("status", 0)) != 200
                        or "json" not in str(response.get("contentType", "")).lower()
                        or len(encoded) > (self.registry.response_body_max_bytes or 1)
                    ):
                        continue
                    body = json.loads(encoded)
                    if request_spec.success_path and (
                        text_value(lookup(body, request_spec.success_path))
                        != request_spec.success_value
                    ):
                        continue
                    if lookup(body, source.join_response_path) != join_value:
                        continue
                except (BrowserError, ValueError, TypeError, json.JSONDecodeError):
                    continue
                joined.append(body)
            data[source.request_key] = joined

    @staticmethod
    def _coverage_notes(spec: FeaturedCollectionSpec, cards: list[FeaturedCard]) -> list[str]:
        notes: list[str] = []
        keys = {f.key for f in spec.card_fields}
        if not ({"platform_content_id", "local_key"} & keys):
            # Without a registered identity key the module cannot prove cross-load duplicates.
            notes.append("identity_unavailable")
        for card in cards:
            if card.identity_kind == "missing":
                notes.append(f"identity_missing:{card.card_id}")
            if spec.link_hosts and card.canonical_link is None:
                notes.append(f"link_missing:{card.card_id}")
        return sorted(set(notes))

    async def card_source(
        self,
        page: Page,
        row: dict[str, Any],
        index: int,
        source: SourceSpec,
        data: dict[str, Any],
        failures: dict[str, str],
    ) -> Any:
        """Card-scoped source read: response paths are relative to the card, DOM by index."""
        if source.kind == "dom":
            if not source.locator:
                raise CollectorError("PLATFORM_PAGE_CHANGED", "MISSING_DOM_CONTRACT")
            locator = self.locator(page, source.locator)
            if await locator.count() <= index:
                raise CollectorError("MODULE_COLLECTION_FAILED", "MISSING_SOURCE")
            element = locator.nth(index)
            value = (
                await element.get_attribute(source.locator.attribute)
                if source.locator.attribute
                else await element.inner_text()
            )
            if value is None:
                raise CollectorError("MODULE_COLLECTION_FAILED", "MISSING_SOURCE")
            return source.locator.value_map.get(value.strip(), value.strip())
        if not source.request_key or not source.path:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "MISSING_RESPONSE_CONTRACT")
        if source.request_key in failures:
            raise CollectorError("MODULE_COLLECTION_FAILED", failures[source.request_key])
        if source.join_row_path and source.join_response_path:
            join_value = lookup(row, source.join_row_path)
            if join_value is None:
                raise CollectorError("MODULE_COLLECTION_FAILED", "MISSING_SOURCE_JOIN_KEY")
            raw_bodies = data.get(source.request_key)
            bodies = raw_bodies if isinstance(raw_bodies, list) else [raw_bodies]
            matches = [
                body
                for body in bodies
                if body is not None and lookup(body, source.join_response_path) == join_value
            ]
            if not matches:
                raise CollectorError("MODULE_COLLECTION_FAILED", "MISSING_SOURCE_JOIN")
            # Signing may be repeated for the same URI. The latest correlated response is the
            # current signed URL; unrelated image responses are ignored by the equality join.
            value = lookup(matches[-1], source.path)
        else:
            value = lookup(row, source.path)
        if value is None:
            raise CollectorError("MODULE_COLLECTION_FAILED", "MISSING_SOURCE")
        return value

    async def parse_card(
        self,
        page: Page,
        spec: FeaturedCollectionSpec,
        row: dict[str, Any],
        index: int,
        operation: str,
        ctx: ExecutionContext,
        data: dict[str, Any],
        failures: dict[str, str],
    ) -> FeaturedCard:
        fields: list[FieldObservation] = []
        for field_spec in spec.card_fields:
            observation = FieldObservation(
                field_key=field_spec.key,
                status=FieldStatus.FAILED,
                failure_reason="NOT_READ",
                operation_id=operation,
                session_version=ctx.session_version,
                unit=field_spec.unit,
            )
            try:
                try:
                    raw = await self.card_source(
                        page, row, index, field_spec.source, data, failures
                    )
                except CollectorError as exc:
                    if exc.code != "MODULE_COLLECTION_FAILED":
                        raise
                    if not field_spec.fallback or exc.reason not in field_spec.fallback_on:
                        raise
                    raw = await self.card_source(
                        page, row, index, field_spec.fallback, data, failures
                    )
                    observation.fallback_reason = exc.reason
                text = text_value(raw)
                status = (
                    FieldStatus.NO_PERMISSION
                    if text in field_spec.permission_values
                    else FieldStatus.NOT_PROVIDED
                    if text in field_spec.not_provided_values
                    else FieldStatus.NO_DATA
                    if text in field_spec.empty_values
                    else FieldStatus.COLLECTED
                )
                values: dict[str, Any] = {
                    "raw_value": text,
                    "status": status,
                    "failure_reason": None,
                    "source_kind": field_spec.source.kind,
                    "source_contract": self.registry.contract_version,
                    "path_ref": field_spec.source.path
                    or (field_spec.source.locator.selector if field_spec.source.locator else None),
                    "evidence_refs": [f"{operation}:{spec.key.value}:{field_spec.key}"],
                }
                if status == FieldStatus.COLLECTED:
                    values["value"] = self._card_value(field_spec, raw)
                    if field_spec.truncate_marker and isinstance(values["value"], str):
                        values["truncated"] = values["value"].endswith(field_spec.truncate_marker)
                    if isinstance(values["value"], NumericValue):
                        values["is_approximate"] = values["value"].bound != "exact"
                observation = FieldObservation.model_validate(
                    {**observation.model_dump(), **values}
                )
            except CollectorError as exc:
                if exc.code != "MODULE_COLLECTION_FAILED":
                    raise
                if exc.reason == "MISSING_SOURCE" and field_spec.missing_source_status:
                    observation = FieldObservation.model_validate(
                        {
                            **observation.model_dump(),
                            "status": FieldStatus(field_spec.missing_source_status),
                            "failure_reason": None,
                            "source_kind": field_spec.source.kind,
                            "source_contract": self.registry.contract_version,
                            "path_ref": field_spec.source.path,
                            "evidence_refs": [
                                f"{operation}:{spec.key.value}:{field_spec.key}",
                                field_spec.missing_source_evidence,
                            ],
                        }
                    )
                else:
                    observation.failure_reason = exc.reason
            except (ValueError, TypeError):
                observation.failure_reason = "FIELD_SCHEMA_MISMATCH"
            fields.append(observation)
        by_key = {f.field_key: f for f in fields}
        content_id = None
        content = by_key.get("platform_content_id")
        if content and content.status == FieldStatus.COLLECTED and content.value:
            content_id = str(content.value).strip() or None
        canonical_link = None
        if spec.link_hosts:
            link = by_key.get("link")
            if link and link.status == FieldStatus.COLLECTED and isinstance(link.value, str):
                parsed_link = urlsplit(link.value)
                if (
                    parsed_link.scheme == "https"
                    and parsed_link.hostname in spec.link_hosts
                    and not parsed_link.username
                    and not parsed_link.password
                ):
                    canonical_link = link.value
        local_key = None
        local = by_key.get("local_key")
        if local and local.status == FieldStatus.COLLECTED and local.value:
            local_key = str(local.value)
        cover = None
        if spec.cover:
            cover_field = by_key.get(spec.cover.field_key)
            source_url = (
                cover_field.value
                if cover_field
                and cover_field.status == FieldStatus.COLLECTED
                and isinstance(cover_field.value, str)
                else None
            )
            cover = CoverRef(source_url=source_url, status=CoverStatus.NOT_ATTEMPTED)
        return FeaturedCard(
            position=0,
            platform_content_id=content_id,
            canonical_link=canonical_link,
            local_key=local_key,
            fields=fields,
            expected_fields=[f.key for f in spec.card_fields],
            truncated_fields=sorted(f.field_key for f in fields if f.truncated),
            cover=cover,
            operation_id=operation,
            contract_version=self.registry.contract_version,
        )

    @staticmethod
    def _card_value(field_spec: Any, raw: Any) -> Any:
        if field_spec.kind in {"number", "ratio"}:
            return number(
                text_value(raw),
                unit="ratio" if field_spec.kind == "ratio" else field_spec.unit or "count",
                ratio_input=field_spec.ratio_input,
            )
        if field_spec.kind == "quote":
            if not field_spec.currency or not field_spec.cooperation_form:
                raise CollectorError("PLATFORM_PAGE_CHANGED", "QUOTE_CONTRACT_INCOMPLETE")
            return quote(
                text_value(raw),
                currency=field_spec.currency,
                cooperation_form=field_spec.cooperation_form,
            )
        if field_spec.kind == "distribution":
            if not field_spec.dimension or not isinstance(raw, list):
                raise CollectorError("MODULE_COLLECTION_FAILED", "DISTRIBUTION_SCHEMA")
            return DistributionValue(dimension=field_spec.dimension, groups=raw)
        if field_spec.kind == "tags":
            if not isinstance(raw, list) or not all(isinstance(v, str) for v in raw):
                raise CollectorError("MODULE_COLLECTION_FAILED", "TAGS_SCHEMA")
            values = list(dict.fromkeys(value.strip() for value in raw if value.strip()))
            if not values:
                raise CollectorError("MODULE_COLLECTION_FAILED", "TAGS_SCHEMA")
            return values
        if not isinstance(raw, (str, int)) or not str(raw).strip():
            raise CollectorError("MODULE_COLLECTION_FAILED", "TEXT_SCHEMA")
        return str(raw)

    async def fetch_cover(self, url: str, spec: CoverSpec) -> FetchedCover:
        """Fetch one cover inside the registered scope, in the unit's own browser session.

        The request is issued by the module/detail page itself, so it reuses the authenticated
        cookies and the unit's bound line, and there is no direct-connection fallback. Redirects
        are followed explicitly, counted against ``max_redirects`` and re-checked against the
        registered cover hosts; an unverifiable redirect fails closed.
        """
        page = self.detail_page or self.search_page
        if page is None:
            raise CollectorError("COVER_STORE_FAILED", "COVER_SESSION_UNAVAILABLE")
        self.metric("cover_requests")
        result = await page.evaluate(
            COVER_FETCH_JS,
            {
                "url": url,
                "allowedHosts": spec.allowed_hosts,
                "maxRedirects": spec.max_redirects,
                "timeoutMs": spec.timeout_seconds * 1000,
            },
        )
        if result.get("error") == "COVER_FETCH_FAILED":
            # Signed CDN images may deliberately omit CORS response headers. A page-level fetch
            # then fails before JavaScript can read the response even though the same browser can
            # render the image. Keep the transfer inside the current page/context/line: initiate
            # a real image resource request and read the response Playwright already observed.
            def related_image(response: Any) -> bool:
                request = response.request
                first = request
                while first.redirected_from:
                    first = first.redirected_from
                return (
                    first.url == url
                    and request.resource_type == "image"
                    and response.status not in {301, 302, 303, 307, 308}
                )

            try:
                async with page.expect_response(
                    related_image, timeout=spec.timeout_seconds * 1000
                ) as response_info:
                    loaded = await page.evaluate(
                        """
                        (source) => new Promise((resolve) => {
                          const image = new Image();
                          image.onload = () => { image.remove(); resolve(true); };
                          image.onerror = () => { image.remove(); resolve(false); };
                          image.src = source;
                          document.body.appendChild(image);
                        })
                        """,
                        url,
                    )
                response = await response_info.value
                if not loaded:
                    raise CollectorError("COVER_STORE_FAILED", "COVER_FETCH_FAILED")
                chain: list[str] = []
                request_cursor: Any = response.request
                while request_cursor:
                    chain.append(request_cursor.url)
                    request_cursor = request_cursor.redirected_from
                chain.reverse()
                if len(chain) - 1 > spec.max_redirects:
                    raise CollectorError("COVER_STORE_FAILED", "COVER_REDIRECT_LIMIT")
                for hop in chain:
                    parsed = urlsplit(hop)
                    if (
                        parsed.scheme != "https"
                        or parsed.hostname not in spec.allowed_hosts
                        or parsed.port not in {None, 443}
                    ):
                        raise CollectorError("COVER_STORE_FAILED", "COVER_HOST_NOT_ALLOWED")
                return FetchedCover(
                    body=await response.body(),
                    content_type=response.headers.get("content-type", ""),
                    final_url=response.url,
                    status_code=response.status,
                )
            except CollectorError:
                raise
            except (BrowserError, TimeoutError) as exc:
                raise CollectorError("COVER_STORE_FAILED", "COVER_FETCH_FAILED") from exc
        if result.get("error"):
            raise CollectorError("COVER_STORE_FAILED", str(result["error"]))
        return FetchedCover(
            body=base64.b64decode(result["body"]),
            content_type=str(result["contentType"]),
            final_url=str(result["url"]),
            status_code=int(result["status"]),
        )

    async def module_absence(
        self,
        page: Page,
        spec: ProfileModuleSpec,
        operation: str,
        data: dict[str, Any],
        failures: dict[str, str],
    ) -> tuple[FieldStatus, str] | None:
        """Registered module-level absence evidence; a missing element never proves absence."""
        absence = spec.absence
        if not absence:
            return None
        # Incremental loads keep a list of bodies; module state is read from the latest body.
        latest = {
            key: (value[-1] if isinstance(value, list) and value else value)
            for key, value in data.items()
        }
        try:
            raw = await self.source(page, absence.probe, latest, failures)
        except CollectorError as exc:
            if exc.code != "MODULE_COLLECTION_FAILED":
                raise
            return None
        text = text_value(raw)
        for values, status in (
            (absence.permission_values, FieldStatus.NO_PERMISSION),
            (absence.empty_values, FieldStatus.NO_DATA),
            (absence.not_provided_values, FieldStatus.NOT_PROVIDED),
        ):
            if text in values:
                probe_ref = absence.probe.path or (
                    absence.probe.locator.selector if absence.probe.locator else "probe"
                )
                # Registered absence label only; never the raw page text.
                return status, f"{operation}:{spec.key}:{probe_ref}"
        return None

    async def parse_module(
        self,
        page: Page,
        spec: ProfileModuleSpec,
        creator: CreatorRef,
        ctx: ExecutionContext,
        operation: str,
        data: dict[str, Any],
        failures: dict[str, str],
    ) -> ModuleObservation:
        gaps = list(spec.coverage_gaps) + self.registry.coverage_gaps
        absence = await self.module_absence(page, spec, operation, data, failures)
        if absence is not None:
            status, evidence_ref = absence
            assert spec.absence
            return ModuleObservation(
                creator_ref=creator,
                module_key=spec.key,
                fields=[
                    FieldObservation(
                        field_key=field.key,
                        status=status,
                        unit=field.unit,
                        source_kind=spec.absence.probe.kind,
                        source_contract=self.registry.contract_version,
                        path_ref=spec.absence.probe.path
                        or (
                            spec.absence.probe.locator.selector
                            if spec.absence.probe.locator
                            else None
                        ),
                        evidence_refs=[evidence_ref],
                        operation_id=operation,
                        session_version=ctx.session_version,
                    )
                    for field in spec.fields
                ],
                expected_fields=[f.key for f in spec.fields],
                coverage_gaps=gaps,
                operation_id=operation,
                contract_version=self.registry.contract_version,
            )
        period: str | None = None
        if spec.period_source:
            try:
                period = text_value(await self.source(page, spec.period_source, data, failures))
            except CollectorError as exc:
                if exc.code != "MODULE_COLLECTION_FAILED":
                    raise
                gaps.append("period_unreadable")
        fields = []
        for field in spec.fields:
            observation = FieldObservation(
                field_key=field.key,
                status=FieldStatus.FAILED,
                failure_reason="NOT_READ",
                operation_id=operation,
                session_version=ctx.session_version,
                unit=field.unit,
                period_label=field.period_label or period,
            )
            source = field.source
            try:
                try:
                    raw = await self.source(page, source, data, failures)
                except CollectorError as exc:
                    if exc.code != "MODULE_COLLECTION_FAILED":
                        raise
                    if not field.fallback or exc.reason not in field.fallback_on:
                        raise
                    source = field.fallback
                    raw = await self.source(page, source, data, failures)
                    observation.fallback_reason = exc.reason
                text = text_value(raw)
                evidence = [f"{operation}:{field.key}"]
                status = (
                    FieldStatus.NO_PERMISSION
                    if text in field.permission_values
                    else FieldStatus.NOT_PROVIDED
                    if text in field.not_provided_values
                    else FieldStatus.NO_DATA
                    if text in field.empty_values
                    else FieldStatus.COLLECTED
                )
                values: dict[str, Any] = {
                    "raw_value": text,
                    "status": status,
                    "failure_reason": None,
                    "source_kind": source.kind,
                    "source_contract": self.registry.contract_version,
                    "path_ref": source.path
                    or (source.locator.selector if source.locator else None),
                    "evidence_refs": evidence,
                }
                if status == FieldStatus.COLLECTED:
                    if field.kind in {"number", "ratio"}:
                        value: Any = number(
                            text,
                            unit="ratio" if field.kind == "ratio" else field.unit or "count",
                            ratio_input=field.ratio_input,
                        )
                        if field.compare_rounding and field.fallback and source == field.source:
                            try:
                                other = await self.source(page, field.fallback, data, failures)
                            except CollectorError as exc:
                                if exc.code != "MODULE_COLLECTION_FAILED":
                                    raise
                            else:
                                if not consistent(
                                    value,
                                    number(
                                        text_value(other),
                                        unit="ratio"
                                        if field.kind == "ratio"
                                        else field.unit or "count",
                                        ratio_input=field.ratio_input,
                                    ),
                                ):
                                    raise CollectorError(
                                        "MODULE_COLLECTION_FAILED", "SOURCE_CONFLICT"
                                    )
                    elif field.kind == "quote":
                        if not field.currency or not field.cooperation_form:
                            raise CollectorError(
                                "PLATFORM_PAGE_CHANGED", "QUOTE_CONTRACT_INCOMPLETE"
                            )
                        value = quote(
                            text, currency=field.currency, cooperation_form=field.cooperation_form
                        )
                    elif field.kind == "distribution":
                        if not field.dimension or not isinstance(raw, list):
                            raise CollectorError("MODULE_COLLECTION_FAILED", "DISTRIBUTION_SCHEMA")
                        value = DistributionValue(dimension=field.dimension, groups=raw)
                    elif field.kind == "tags":
                        if not isinstance(raw, list) or not all(isinstance(v, str) for v in raw):
                            raise CollectorError("MODULE_COLLECTION_FAILED", "TAGS_SCHEMA")
                        value = list(dict.fromkeys(item.strip() for item in raw if item.strip()))
                        if not value:
                            raise CollectorError("MODULE_COLLECTION_FAILED", "TAGS_SCHEMA")
                    elif field.kind == "structured":
                        # Keep platform-native arrays/objects intact. Unit and enum semantics are
                        # supplied by the verified field contract and are never inferred here.
                        value = StructuredValue(data=raw)
                    else:
                        if not isinstance(raw, (str, int)) or not str(raw).strip():
                            raise CollectorError("MODULE_COLLECTION_FAILED", "TEXT_SCHEMA")
                        value = str(raw)
                    values["value"] = value
                    if isinstance(value, NumericValue):
                        values["is_approximate"] = value.bound != "exact"
                if field.period_source:
                    values["period_label"] = text_value(
                        await self.source(page, field.period_source, data, failures)
                    )
                observation = FieldObservation.model_validate(
                    {**observation.model_dump(), **values}
                )
            except CollectorError as exc:
                if exc.code != "MODULE_COLLECTION_FAILED":
                    raise
                if exc.reason == "MISSING_SOURCE" and field.missing_source_status:
                    observation = FieldObservation.model_validate(
                        {
                            **observation.model_dump(),
                            "status": FieldStatus(field.missing_source_status),
                            "failure_reason": None,
                            "source_kind": source.kind,
                            "source_contract": self.registry.contract_version,
                            "path_ref": source.path
                            or (source.locator.selector if source.locator else None),
                            "evidence_refs": [
                                f"{operation}:{field.key}",
                                field.missing_source_evidence,
                            ],
                        }
                    )
                else:
                    observation.failure_reason = exc.reason
            except (ValueError, TypeError):
                observation.failure_reason = "FIELD_SCHEMA_MISMATCH"
            fields.append(observation)
        return ModuleObservation(
            creator_ref=creator,
            module_key=spec.key,
            fields=fields,
            expected_fields=[f.key for f in spec.fields],
            coverage_gaps=gaps,
            source_period_label=period,
            operation_id=operation,
            contract_version=self.registry.contract_version,
        )

    async def close(self) -> None:
        if self.detail_page:
            await self.detail_page.close()
        if self.search_page:
            await self.search_page.close()

    def detach_page(self, page: Page) -> None:
        """Relinquish a page that the bounded host is moving into maintenance/collection."""

        if self.detail_page is page:
            self.detail_page = None
        if self.search_page is page:
            self.search_page = None
