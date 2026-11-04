"""Xingtu live-square adapter.

The live surface shares the platform session/account/identity model with the verified video
adapter, but its search scene, request body and detail modules are different.  This adapter keeps
the shared browser/session primitives and implements the live interactions directly; the video
adapter is untouched.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .adapter import BrowserAdapter
from .domain import (
    LIVE_OPTION_FIELDS,
    LIVE_PROFILE_FIELDS,
    LIVE_RANGE_FIELDS,
    CandidateDiagnostic,
    CollectorError,
    CreatorRef,
    ExecutionContext,
    FieldObservation,
    FieldStatus,
    Filter,
    FilterPlan,
    LiveProfileCompound,
    NumberRange,
    RegionCompound,
    SearchPage,
    uid,
    utcnow,
)
from .live_filters import expected_xingtu_live_request, validate_xingtu_live_request
from .normalize import number

logger = logging.getLogger(__name__)

SEARCH_INPUT = "input[placeholder='输入达人昵称、抖音号或星图ID']"
SEARCH_PATH = "/gw/api/gsearch/search_for_author_square"
LIVE_STATS_PATH = "get_author_live_statistics"
BASIC_JS = r"""
(() => ({
  title: document.title,
  text: (document.body ? document.body.innerText : '')
    .replace(/\s+/g, ' ')
    .trim().slice(0, 24000),
  images: [...document.querySelectorAll('img')]
    .map(i => i.getAttribute('src')).filter(Boolean).slice(0, 20)
}))()
"""


CLEAR_JS = r"""
() => {
  const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
  const button = [...document.querySelectorAll('button')].find(
    (el) => clean(el.innerText) === '清空' && el.getBoundingClientRect().width > 0
  );
  if (!button) return false;
  button.click();
  return true;
}
"""

OPEN_CONTROL_JS = r"""
(label) => {
  const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const items = [
    ...document.querySelectorAll('.market-filters .filter-item, .market-filters .xt-dropdown')
  ]
    .filter(visible)
    .filter((el) => clean(el.innerText).startsWith(label))
    .sort((a, b) => clean(a.innerText).length - clean(b.innerText).length);
  if (!items.length) return false;
  const item = items[0];
  const button = item.querySelector('[role=button], .el-dropdown-selfdefine') || item;
  button.click();
  return true;
}
"""

CLICK_MENU_OPTION_JS = r"""
(label) => {
  const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).display !== 'none';
  };
  const menus = [...document.querySelectorAll('ul.el-dropdown-menu')].filter(visible);
  for (const menu of menus) {
    const items = [...menu.querySelectorAll('li,button,span,label')].filter(
      (el) => clean(el.innerText) === label && visible(el)
    );
    if (!items.length) continue;
    const target = items[0].closest('li,button,label') || items[0];
    target.click();
    return true;
  }
  return false;
}
"""

CLICK_REGION_JS = r"""
(args) => {
  const [province, city] = args;
  const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const panels = [...document.querySelectorAll('.xt-cascader-panel')].filter(visible);
  for (const panel of panels) {
    const rows = [...panel.querySelectorAll('li.xt-cascader-option')];
    const row = rows.find((el) => clean(el.innerText) === province);
    if (!row) continue;
    if (city) {
      const suffix = row.querySelector('.xt-cascader-option__suffix');
      if (suffix) suffix.click();
      return true;
    }
    const box =
      row.querySelector('input[type=checkbox]') ||
      row.querySelector('.el-checkbox') ||
      row;
    box.click();
    return true;
  }
  return false;
}
"""

CLICK_REGION_CITY_JS = r"""
(args) => {
  const [province, city] = args;
  const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const panels = [...document.querySelectorAll('.xt-cascader-panel')].filter(visible);
  for (const panel of panels) {
    const rows = [...panel.querySelectorAll('li.xt-cascader-option')];
    const row = rows.find((el) => clean(el.innerText) === city);
    if (!row) continue;
    const box =
      row.querySelector('input[type=checkbox]') ||
      row.querySelector('.el-checkbox') ||
      row;
    box.click();
    return true;
  }
  return false;
}
"""

SELECTED_CONDITIONS_JS = r"""
() => {
  const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const candidates = [...document.querySelectorAll('div')].filter(
    (el) => visible(el) && clean(el.innerText).startsWith('已选条件')
  );
  if (!candidates.length) return '';
  candidates.sort((a, b) => clean(a.innerText).length - clean(b.innerText).length);
  return clean(candidates[0].innerText);
}
"""

CLICK_PROFILE_DIMENSION_JS = r"""
(key) => {
  const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).display !== 'none';
  };
  const menus = [...document.querySelectorAll('ul.el-dropdown-menu')].filter(visible);
  const popup = menus.find(
    (menu) => clean(menu.innerText).includes('确定') && menu.querySelector('.panel-content')
  );
  if (!popup) return false;
  const labels = {age: '年龄', gender: '性别', device_brand: '设备', city_level: '地域'};
  const suffix = labels[key];
  if (!suffix) return false;
  const panels = [...popup.querySelectorAll('.panel-content')];
  const panel = panels.find((item) =>
    clean(item.querySelector('.label')?.innerText || '').includes(suffix)
  );
  if (!panel) return false;
  const input = panel.querySelector('.el-select input');
  if (!input) return false;
  input.click();
  return true;
}
"""

CLICK_PROFILE_OPTION_JS = r"""
(label) => {
  const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).display !== 'none';
  };
  const dropdowns = [...document.querySelectorAll('.el-select-dropdown')].filter(visible);
  for (const dropdown of dropdowns) {
    const options = [...dropdown.querySelectorAll('.el-select-dropdown__item')].filter(
      (el) => clean(el.innerText) === label && visible(el)
    );
    if (!options.length) continue;
    options[0].click();
    return true;
  }
  return false;
}
"""

CONFIRM_PROFILE_JS = r"""
() => {
  const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).display !== 'none';
  };
  const menus = [...document.querySelectorAll('ul.el-dropdown-menu')].filter(visible);
  const popup = menus.find(
    (menu) => clean(menu.innerText).includes('确定') && menu.querySelector('.panel-content')
  );
  if (!popup) return false;
  const buttons = [...popup.querySelectorAll('button,span,div')].filter(
    (el) => clean(el.innerText) === '确定' && visible(el)
  );
  if (!buttons.length) return false;
  (buttons[0].closest('button') || buttons[0]).click();
  return true;
}
"""


def _clean_line(text: str, label: str) -> str | None:
    pos = text.find(label)
    if pos < 0:
        return None
    tail = text[pos + len(label) :].strip()
    return tail.split("  ")[0].strip() or None


class XingtuLiveAdapter(BrowserAdapter):
    """Live-square browser adapter for one authenticated Xingtu unit."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._stats: dict[str, Any] = {}
        self._basic: dict[str, Any] = {}
        self._search_keyword: str | None = None
        self._no_live = False
        self._stats_event = asyncio.Event()

    # -- search -------------------------------------------------------------------------

    def _detail_url(self, star_id: str) -> str:
        return f"https://www.xingtu.cn/ad/creator/author/douyin/{star_id}/10"

    def _expectation(self, plan: FilterPlan) -> Any:
        return expected_xingtu_live_request(plan, self.registry.capabilities)

    def _page_from_payload(
        self, plan: FilterPlan, checkpoint: Any, payload: dict[str, Any], page_number: int
    ) -> SearchPage:
        authors = payload.get("authors")
        pagination = payload.get("pagination")
        if not isinstance(authors, list) or not isinstance(pagination, dict):
            raise CollectorError("PLATFORM_PAGE_CHANGED", "LIVE_SEARCH_SCHEMA")
        operation = uid()
        candidates: list[CreatorRef] = []
        unidentified: list[CandidateDiagnostic] = []
        for index, row in enumerate(authors):
            if not isinstance(row, dict):
                continue
            star_id = row.get("star_id")
            if isinstance(star_id, bool) or not isinstance(star_id, (str, int)):
                continue
            star_id = str(star_id)
            if not star_id:
                continue
            candidates.append(
                CreatorRef(
                    platform="douyin_xingtu",
                    platform_creator_id=star_id,
                    verified_homepage=self._detail_url(star_id),
                    first_position=(page_number - 1) * 20 + index,
                    source_refs=[f"{operation}:authors.{index}"],
                )
            )
        has_more = bool(pagination.get("has_more"))
        total = pagination.get("total_count")
        if total is not None and not isinstance(total, (int, str)):
            raise CollectorError("PLATFORM_PAGE_CHANGED", "LIVE_SEARCH_SCHEMA")
        return SearchPage(
            candidates=candidates,
            current_checkpoint=checkpoint.cursor,
            next_checkpoint=None if not has_more else str(page_number + 1),
            conditions_digest=plan.digest(),
            search_generation=checkpoint.search_generation,
            operation_id=operation,
            exhausted=not has_more,
            exhaustion_evidence_refs=([f"{operation}:pagination.has_more"] if not has_more else []),
            unidentified=unidentified,
        )

    async def _clear_conditions(self, page: Page) -> None:
        clicked = await page.evaluate(CLEAR_JS)
        if clicked:
            await asyncio.sleep(1.0)

    async def _open_control(self, page: Page, label: str) -> None:
        opened = await page.evaluate(OPEN_CONTROL_JS, label)
        if not opened:
            raise CollectorError("PLATFORM_PAGE_CHANGED", f"LIVE_FILTER_OPENER:{label}")
        await asyncio.sleep(self.registry.action_interval_seconds or 0)

    async def _click_menu_option(self, page: Page, label: str) -> None:
        clicked = await page.evaluate(CLICK_MENU_OPTION_JS, label)
        if not clicked:
            raise CollectorError("PLATFORM_PAGE_CHANGED", f"LIVE_FILTER_OPTION:{label}")
        await asyncio.sleep(self.registry.action_interval_seconds or 0)

    async def _apply_option_filter(self, page: Page, field: str, values: list[str]) -> None:
        spec = next(item for item in self.registry.capabilities.fields if item.field == field)
        labels = {option.value: option.label for option in spec.options}
        if field == "live_content_type":
            for value in values:
                label = labels.get(value)
                if not label:
                    raise CollectorError("UNSUPPORTED_FILTER", f"{field}.{value}")
                await self._open_control(page, label)
                await self._click_menu_option(page, "全选")
            return
        if len(values) != 1:
            raise CollectorError("INVALID_FORM", f"{field} requires one value")
        label = labels.get(values[0])
        if not label:
            raise CollectorError("UNSUPPORTED_FILTER", f"{field}.{values[0]}")
        await self._open_control(page, spec.label or field)
        await self._click_menu_option(page, label)

    async def _apply_region_filter(self, page: Page, item: Filter) -> None:
        value = item.value
        assert isinstance(value, RegionCompound)
        spec = next(
            field for field in self.registry.capabilities.fields if field.field == "live_region"
        )
        provinces = {node.value: node for node in spec.region_tree}
        await self._open_control(page, spec.label or "所在地域")
        for selection in value.selections:
            province = provinces.get(selection.province_code)
            if province is None:
                raise CollectorError("INVALID_FORM", "unknown province")
            clicked = await page.evaluate(CLICK_REGION_JS, [province.label, selection.city])
            if not clicked:
                raise CollectorError(
                    "PLATFORM_PAGE_CHANGED",
                    f"LIVE_FILTER_REGION:{province.label}/{selection.city or ''}",
                )
            if selection.city is not None:
                await asyncio.sleep(self.registry.action_interval_seconds or 0)
                clicked = await page.evaluate(
                    CLICK_REGION_CITY_JS, [province.label, selection.city]
                )
                if not clicked:
                    raise CollectorError(
                        "PLATFORM_PAGE_CHANGED",
                        f"LIVE_FILTER_REGION_CITY:{province.label}/{selection.city}",
                    )
            await asyncio.sleep(self.registry.action_interval_seconds or 0)
        try:
            await page.keyboard.press("Escape")
        except Exception:  # noqa: BLE001 - closing an already closed popover is not data loss
            pass

    async def _apply_range_filter(self, page: Page, item: Filter) -> None:
        assert isinstance(item.value, NumberRange)
        spec = next(
            field for field in self.registry.capabilities.fields if field.field == item.field
        )
        preset = next(
            (
                option
                for option in spec.options
                if option.range
                and option.range.min == item.value.min
                and option.range.max == item.value.max
            ),
            None,
        )
        await self._open_control(page, spec.label or item.field)
        if preset is not None:
            await self._click_menu_option(page, preset.label)
            return
        # The live range menu renders its custom inputs only after opening.  The unit shown by the
        # control is the capability unit; the plan already stores that unit.
        menus = page.locator("ul.el-dropdown-menu:visible")
        if await menus.count() == 0:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "LIVE_RANGE_MENU_MISSING")
        menu = menus.last
        inputs = menu.locator("input")
        if await inputs.count() < 2:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "LIVE_RANGE_INPUTS_MISSING")
        await inputs.nth(0).fill(str(item.value.min) if item.value.min is not None else "")
        await inputs.nth(1).fill(str(item.value.max) if item.value.max is not None else "")
        confirm = menu.locator("button").filter(has_text="确定")
        if await confirm.count() == 0:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "LIVE_RANGE_CONFIRM_MISSING")
        await confirm.first.click()
        await asyncio.sleep(self.registry.action_interval_seconds or 0)

    async def _apply_profile_filter(self, page: Page, item: Filter) -> None:
        assert isinstance(item.value, LiveProfileCompound)
        spec = next(
            field for field in self.registry.capabilities.fields if field.field == item.field
        )
        dimensions = {dimension.key: dimension for dimension in spec.dimensions}
        labels = {
            key: {option.value: option.label for option in dimension.options}
            for key, dimension in dimensions.items()
        }
        await self._open_control(page, spec.label or item.field)
        for selection in item.value.dimensions:
            dimension = dimensions.get(selection.key)
            if dimension is None:
                raise CollectorError("UNSUPPORTED_FILTER", f"{item.field}.{selection.key}")
            panel_labels = labels[selection.key]
            selected_labels = []
            for value in selection.values:
                label = panel_labels.get(value)
                if label is None:
                    raise CollectorError("UNSUPPORTED_FILTER", f"{item.field}.{selection.key}")
                selected_labels.append(label)
            clicked = await page.evaluate(CLICK_PROFILE_DIMENSION_JS, selection.key)
            if not clicked:
                raise CollectorError(
                    "PLATFORM_PAGE_CHANGED", f"LIVE_PROFILE_DIMENSION:{selection.key}"
                )
            await asyncio.sleep(0.5)
            for label in selected_labels:
                option_clicked = False
                for _ in range(10):
                    option_clicked = await page.evaluate(CLICK_PROFILE_OPTION_JS, label)
                    if option_clicked:
                        break
                    await asyncio.sleep(0.2)
                if not option_clicked:
                    raise CollectorError("PLATFORM_PAGE_CHANGED", f"LIVE_PROFILE_OPTION:{label}")
            await asyncio.sleep(self.registry.action_interval_seconds or 0)
        confirmed = await page.evaluate(CONFIRM_PROFILE_JS)
        if not confirmed:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "LIVE_PROFILE_CONFIRM_MISSING")
        await asyncio.sleep(self.registry.action_interval_seconds or 0)

    async def _apply_live_filters(self, page: Page, plan: FilterPlan) -> None:
        for item in plan.filters:
            if item.field == "keyword":
                continue
            if item.field in LIVE_OPTION_FIELDS:
                values = item.value if isinstance(item.value, list) else [str(item.value)]
                await self._apply_option_filter(page, item.field, [str(value) for value in values])
            elif item.field == "live_region":
                await self._apply_region_filter(page, item)
            elif item.field in LIVE_RANGE_FIELDS:
                await self._apply_range_filter(page, item)
            elif item.field in LIVE_PROFILE_FIELDS:
                await self._apply_profile_filter(page, item)
            else:
                raise CollectorError("UNSUPPORTED_FILTER", item.field)

    async def _readback_live_conditions(self, page: Page, plan: FilterPlan) -> None:
        text = await page.evaluate(SELECTED_CONDITIONS_JS)
        if not isinstance(text, str):
            raise CollectorError("PLATFORM_CONDITION_MISMATCH", "LIVE_SELECTED_CONDITIONS_MISSING")
        specs = {field.field: field for field in self.registry.capabilities.fields}
        for item in plan.filters:
            if item.field == "keyword":
                continue
            spec = specs[item.field]
            if item.field in LIVE_OPTION_FIELDS:
                values = item.value if isinstance(item.value, list) else [str(item.value)]
                for value in values:
                    option = next(
                        (option for option in spec.options if option.value == value), None
                    )
                    if option is None or option.label not in text:
                        raise CollectorError(
                            "PLATFORM_CONDITION_MISMATCH", f"LIVE_SELECTED_MISSING:{value}"
                        )
            elif item.field == "live_region":
                if "所在地域" not in text:
                    raise CollectorError(
                        "PLATFORM_CONDITION_MISMATCH", "LIVE_SELECTED_MISSING:live_region"
                    )
            elif item.field in LIVE_PROFILE_FIELDS:
                assert isinstance(item.value, LiveProfileCompound)
                for selection in item.value.dimensions:
                    dimension = next(
                        dimension for dimension in spec.dimensions if dimension.key == selection.key
                    )
                    for value in selection.values:
                        option = next(
                            (option for option in dimension.options if option.value == value), None
                        )
                        if option is None or option.label not in text:
                            raise CollectorError(
                                "PLATFORM_CONDITION_MISMATCH",
                                f"LIVE_SELECTED_MISSING:{item.field}.{value}",
                            )
            elif item.field in LIVE_RANGE_FIELDS:
                label = spec.label or item.field
                if label not in text and not (
                    item.field == "live_followers" and "粉丝数量" in text
                ):
                    raise CollectorError(
                        "PLATFORM_CONDITION_MISMATCH", f"LIVE_SELECTED_MISSING:{item.field}"
                    )

    async def _collect_search(
        self,
        page: Page,
        action: Any,
        plan: FilterPlan,
        page_number: int,
        expectation: Any,
    ) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[dict[str, Any]] = loop.create_future()
        last_error: list[str] = []

        async def on_response(response: Any) -> None:
            if waiter.done():
                return
            if SEARCH_PATH not in response.url or response.request.method != "POST":
                return
            try:
                request_payload = response.request.post_data_json
            except Exception:  # noqa: BLE001 - a malformed request body is not an applied plan
                last_error.append("LIVE_SEARCH_REQUEST_SCHEMA")
                return
            try:
                page_param = (
                    request_payload.get("page_param") if isinstance(request_payload, dict) else None
                )
                if not isinstance(page_param, dict) or page_param.get("page") != page_number:
                    return
                if expectation.keyword is not None:
                    search_param = request_payload.get("search_param") or {}
                    if search_param.get("keyword") != expectation.keyword:
                        return
                elif (request_payload.get("search_param") or {}).get("keyword"):
                    return
                validate_xingtu_live_request(request_payload, expectation)
                if response.status != 200:
                    last_error.append(f"LIVE_SEARCH_HTTP:{response.status}")
                    return
                payload = await response.json()
                if not isinstance(payload, dict):
                    last_error.append("LIVE_SEARCH_SCHEMA")
                    return
                waiter.set_result(payload)
            except CollectorError as exc:
                last_error.append(f"{exc.code}:{exc.reason}")
            except Exception as exc:  # noqa: BLE001 - response parsing is a contract boundary
                last_error.append(type(exc).__name__)

        page.on("response", on_response)
        try:
            await action()
            try:
                return await asyncio.wait_for(waiter, self.timeout_seconds())
            except TimeoutError as exc:
                reason = last_error[-1] if last_error else "LIVE_FILTER_RESPONSE_TIMEOUT"
                raise CollectorError("PLATFORM_CONDITION_MISMATCH", reason) from exc
        finally:
            page.remove_listener("response", on_response)

    async def _apply_filters_and_trigger(
        self, page: Page, plan: FilterPlan, keyword: str | None
    ) -> None:
        await self._apply_live_filters(page, plan)
        if keyword is not None:
            search_input = page.locator(SEARCH_INPUT).first
            await search_input.wait_for(state="visible", timeout=self.timeout_seconds() * 1000)
            await search_input.fill(keyword)
            await search_input.press("Enter")

    async def prepare(self, plan: FilterPlan, cp: Any, ctx: ExecutionContext) -> bool:
        self.registry.capabilities.validate_plan(plan, live=self.live)
        keyword = next((str(item.value) for item in plan.filters if item.field == "keyword"), None)
        self._search_keyword = keyword
        spec = self.registry.search
        session = self.registry.session
        assert spec and session
        if self.search_page is None:
            self.search_page = await self.browser.new_page()
        page = self.search_page
        page.set_default_timeout(self.timeout_seconds() * 1000)
        await self._bootstrap_session(page, spec.entry_url, session.entry_url)
        await self.check_session(page)
        await self._clear_conditions(page)
        expectation = self._expectation(plan)
        if cp.cursor is not None:
            # Rebuild the original conditions on every retry.  The previous browser page may have
            # been lost or replaced, and silently starting on page N without the user's filters
            # would return a different population than the first page.
            self.prepared_result = None
            await self._collect_search(
                page,
                lambda: self._apply_filters_and_trigger(page, plan, keyword),
                plan,
                1,
                expectation,
            )
            await self._readback_live_conditions(page, plan)
            return True
        payload = await self._collect_search(
            page,
            lambda: self._apply_filters_and_trigger(page, plan, keyword),
            plan,
            1,
            expectation,
        )
        await self._readback_live_conditions(page, plan)
        self.prepared_result = self._page_from_payload(plan, cp, payload, 1)
        return True

    async def search(self, plan: FilterPlan, cp: Any, ctx: ExecutionContext) -> SearchPage:
        del ctx
        if self.prepared_result is not None:
            result, self.prepared_result = self.prepared_result, None
            return result
        if self.search_page is None:
            raise CollectorError("SESSION_INDETERMINATE", "LIVE_SEARCH_PAGE_MISSING")
        page = self.search_page
        cursor = cp.cursor
        if not isinstance(cursor, str) or not cursor.isdigit() or int(cursor) < 2:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "LIVE_SEARCH_CURSOR_INVALID")
        page_number = int(cursor)
        max_verified = (
            self.registry.search.page_fetch_max_verified if self.registry.search else None
        )
        if max_verified is not None and page_number > max_verified:
            raise CollectorError("SEARCH_CAPABILITY_LIMIT", "LIVE_PAGE_LIMIT")
        await self.check_session(page)
        pager = page.locator(".el-pager li").filter(has_text=re.compile(rf"^{page_number}$")).first
        if await pager.count() == 0:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "LIVE_PAGE_NOT_AVAILABLE")
        await pager.scroll_into_view_if_needed()
        expectation = self._expectation(plan)
        payload = await self._collect_search(
            page, lambda: pager.click(), plan, page_number, expectation
        )
        return self._page_from_payload(plan, cp, payload, page_number)

    # -- profile ------------------------------------------------------------------------

    @asynccontextmanager
    async def profile(self, creator: CreatorRef, ctx: ExecutionContext) -> AsyncIterator[None]:
        self.registry.validate_homepage(creator.verified_homepage)
        page = await self.browser.new_page()
        self.detail_page = page
        self._stats = {}
        self._basic = {}
        self._no_live = False
        self._stats_event = asyncio.Event()
        page.set_default_timeout(min(self.timeout_seconds() * 1000, 20_000))
        try:
            await self.guard()
            stats_task: asyncio.Task[None] | None = None

            def capture_stats(response: Any) -> None:
                nonlocal stats_task
                if (
                    stats_task is None
                    and LIVE_STATS_PATH in response.url
                    and "candidates" not in response.url
                ):
                    stats_task = asyncio.create_task(self._capture_stats(response))

            page.on("response", capture_stats)
            await self.navigate(page, creator.verified_homepage)
            # The SPA title/innerText is the page-ready signal.  Reading immediately after a
            # navigation can capture the generic site title and a truncated "粉丝 1" value.
            try:
                await page.wait_for_function(
                    "document.title.includes('抖音达人主页')"
                    " && document.body.innerText.includes('星图ID')"
                    " && document.body.innerText.includes('粉丝')",
                    timeout=15_000,
                )
            except PlaywrightTimeoutError:
                # One reload is enough to distinguish a transient hydration stall from a creator
                # page that genuinely cannot be read.  A page-specific failure is a candidate
                # failure, not a platform-contract change that must abort the whole task.
                try:
                    await self.navigate(page, creator.verified_homepage)
                    await page.wait_for_function(
                        "document.title.includes('抖音达人主页')"
                        " && document.body.innerText.includes('星图ID')"
                        " && document.body.innerText.includes('粉丝')",
                        timeout=10_000,
                    )
                except PlaywrightTimeoutError as exc:
                    raise CollectorError("CREATOR_INVALID", "LIVE_DETAIL_NOT_READY") from exc
            if stats_task is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(stats_task), 5)
                except TimeoutError:
                    # A slow stats response must not block the profile; missing fields are NO_DATA.
                    pass
            await self.check_session(page)
            if creator.platform_creator_id not in page.url:
                raise CollectorError("CREATOR_INVALID", "LIVE_IDENTITY_MISMATCH")
            self._basic = await page.evaluate(BASIC_JS)
            basic_text = str(self._basic.get("text") or "")
            if "星图ID" not in basic_text:
                raise CollectorError("CREATOR_INVALID", "LIVE_DETAIL_IDENTITY_MISSING")
            # A creator with no live tab is still a live-square candidate; its live module is
            # NO_DATA.  Both the explicit "no live in 30 days" text and the absent live tab count.
            self._no_live = "没有开播" in basic_text or "抖音直播主页" not in basic_text
            yield
        finally:
            self.detail_page = None
            self._stats = {}
            self._basic = {}
            self._stats_event.set()
            page.remove_listener("response", capture_stats)
            await page.close()

    async def _capture_stats(self, response: Any) -> None:
        try:
            if response.status != 200:
                return
            payload = await response.json()
        except Exception:  # noqa: BLE001 - a non-JSON stats response is simply no live evidence
            return
        if isinstance(payload, dict):
            self._stats = payload

    @staticmethod
    def _profile_header(text: str) -> re.Match[str] | None:
        # Both live-tab and no-live pages render the header as
        # "<nickname> <gender> <city> 粉丝 <count>"; the live tab inserts a label before it.
        return re.search(r"([^\s]+)\s+([男女])\s+([^\s]+)\s+粉丝", text)

    def _basic_value(self, key: str) -> Any:
        text = str(self._basic.get("text") or "")
        title = str(self._basic.get("title") or "")
        if key == "platform_creator_id":
            match = re.search(r"(?:星图ID|ID)\s*[:：]?\s*(\d+)", text)
            return match.group(1) if match else None
        if key == "nickname":
            if "抖音达人主页" in title:
                return title.split(" - ")[0].strip() or None
            match = re.search(r"抖音直播主页\s+(\S+)", text)
            if match:
                return match.group(1)
            header = self._profile_header(text)
            return header.group(1) if header else None
        if key == "avatar_uri":
            images = self._basic.get("images") or []
            for image in images:
                if (
                    isinstance(image, str)
                    and "lf-star-static" not in image
                    and "logo" not in image.lower()
                ):
                    return image
            return None
        if key == "gender":
            match = re.search(r"抖音直播主页\s+\S+\s+([男女])", text)
            if match:
                return match.group(1)
            header = self._profile_header(text)
            return header.group(2) if header else None
        if key == "province":
            return None
        if key == "city":
            match = re.search(r"抖音直播主页\s+\S+\s+[男女]\s+(\S+)", text)
            if match:
                return match.group(1) if match.group(1) not in {"暂无地域信息"} else None
            header = self._profile_header(text)
            return header.group(3) if header and header.group(3) not in {"暂无地域信息"} else None
        if key == "followers":
            match = re.search(r"粉丝(?:数)?\s*[:：]?\s*([\d,.]+[万亿wW]?)", text)
            if not match:
                pos = text.find("粉丝")
                logger.warning(
                    "live followers unreadable snippet=%r", text[max(0, pos - 20) : pos + 80]
                )
            return match.group(1) if match else None
        if key == "content_type":
            match = re.search(r"内容类型\s+([^\s]+)", text)
            return match.group(1) if match else None
        if key == "mcn_name":
            match = re.search(r"所属机构\s+([^\s]+)", text)
            return match.group(1) if match else None
        return None

    @staticmethod
    def _stats_value(key: str) -> Any:
        return None

    def _observation(
        self,
        key: str,
        raw: Any,
        *,
        ctx: ExecutionContext,
        operation: str,
        source_kind: Literal["response", "dom", "api"],
        path: str,
        unit: str | None = None,
        period: str | None = None,
    ) -> FieldObservation:
        if raw is None or raw == "" or raw == []:
            return FieldObservation(
                field_key=key,
                status=FieldStatus.NO_DATA,
                operation_id=operation,
                session_version=ctx.session_version,
                unit=unit,
                period_label=period,
                source_kind=source_kind,
                source_contract=self.registry.contract_version,
                path_ref=path,
                evidence_refs=[f"{operation}:{path}:empty"],
            )
        value: Any = raw
        try:
            if unit in {"count", "ratio", "second", "yuan"}:
                value = number(
                    str(raw),
                    unit=unit,
                    ratio_input="decimal" if unit == "ratio" else "percent",
                )
        except CollectorError:
            value = str(raw)
        return FieldObservation(
            field_key=key,
            value=value,
            raw_value=str(raw),
            status=FieldStatus.COLLECTED,
            operation_id=operation,
            session_version=ctx.session_version,
            unit=unit,
            period_label=period,
            source_kind=source_kind,
            source_contract=self.registry.contract_version,
            path_ref=path,
            observed_at=utcnow(),
        )

    def _basic_fields(
        self, creator: CreatorRef, ctx: ExecutionContext, operation: str
    ) -> list[FieldObservation]:
        mappings = {
            "platform_creator_id": None,
            "nickname": None,
            "avatar_uri": None,
            "gender": None,
            "province": None,
            "city": None,
            "followers": "count",
            "content_type": None,
            "mcn_name": None,
        }
        fields: list[FieldObservation] = []
        for key in self.module_fields.get("basic", list(mappings)):
            unit = mappings.get(key)
            raw = (
                creator.platform_creator_id
                if key == "platform_creator_id"
                else self._basic_value(key)
            )
            fields.append(
                self._observation(
                    key,
                    raw,
                    ctx=ctx,
                    operation=operation,
                    source_kind="dom",
                    path=f"live-basic.{key}",
                    unit=unit,
                )
            )
        return fields

    def _live_fields(
        self, creator: CreatorRef, ctx: ExecutionContext, operation: str
    ) -> list[FieldObservation]:
        if self._no_live:
            self._stats = {}
        room = self._stats.get("live_room_statistics")
        ecom = self._stats.get("live_ecom_statistics")
        if not isinstance(room, dict):
            room = {}
        if not isinstance(ecom, dict):
            ecom = {}
        mapping: dict[str, tuple[str, str | None]] = {
            "live.room_cnt": ("room_cnt", "count"),
            "live.watch_ucnt_avg": ("watch_ucnt_avg", "count"),
            "live.watch_cnt_avg": ("watch_cnt_avg", "count"),
            "live.acu": ("acu", "count"),
            "live.pcu": ("pcu", "count"),
            "live.fans_watch_rate": ("fans_watch_rate", "ratio"),
            "live.follow_ucnt_avg": ("follow_ucnt_avg", "count"),
            "live.comment_rate_avg": ("comment_rate_avg", "ratio"),
            "live.like_rate_avg": ("like_rate_avg", "ratio"),
            "live.watch_duration_avg": ("watch_duration_avg", "second"),
            "live.interact_rate_avg": ("interact_rate_avg", "ratio"),
            "live.acu_precede_percent": ("acu_precede_percent", "ratio"),
            "live.ecom_product_num": ("ecom_live_product_num", "count"),
            "live.ecom_avg_gmv_range": ("avg_gmv_range", None),
            "live.ecom_avg_price_range": ("avg_ecom_product_price_range", None),
            "live.ecom_avg_gpm_range": ("avg_gpm_range", None),
        }
        fields: list[FieldObservation] = []
        for key in self.module_fields.get("live", list(mapping)):
            unit: str | None
            raw: Any
            if key == "platform_star_id":
                raw = creator.platform_creator_id
                unit = None
                path = "creator.star_id"
            elif key in mapping:
                source, unit = mapping[key]
                raw = (room if source in room else ecom).get(source)
                path = (
                    f"live_room_statistics.{source}"
                    if source in room
                    else f"live_ecom_statistics.{source}"
                )
            else:
                raw = None
                unit = None
                path = f"live.{key}"
            fields.append(
                self._observation(
                    key,
                    raw,
                    ctx=ctx,
                    operation=operation,
                    source_kind="response",
                    path=path,
                    unit=unit,
                    period="近30天",
                )
            )
        return fields

    async def collect_module(
        self,
        key: str,
        creator: CreatorRef,
        ctx: ExecutionContext,
        row_covers: Any = None,
    ) -> Any:
        del row_covers
        from .domain import ModuleObservation

        operation = uid()
        if key == "basic":
            fields = self._basic_fields(creator, ctx, operation)
        elif key == "live":
            if not self._stats:
                try:
                    await asyncio.wait_for(self._stats_event.wait(), 5)
                except TimeoutError:
                    pass
            fields = self._live_fields(creator, ctx, operation)
        else:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "UNKNOWN_LIVE_MODULE")
        return ModuleObservation(
            creator_ref=creator,
            module_key=key,
            source_period_label="近30天" if key == "live" else None,
            fields=fields,
            expected_fields=self.module_fields[key],
            operation_id=operation,
            contract_version=self.registry.contract_version,
        )

    async def collect_featured_collections(self, *args: Any, **kwargs: Any) -> list[Any]:
        del args, kwargs
        return []
