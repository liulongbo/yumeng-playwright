"""Xingtu live-square adapter.

The live surface shares the platform session/account/identity model with the verified video
adapter, but its search scene, request body and detail modules are different.  This adapter keeps
the shared browser/session primitives and implements the live interactions directly; the video
adapter is untouched.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit

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
    ModuleObservation,
    NumberRange,
    RegionCompound,
    SearchPage,
    StructuredValue,
    uid,
    utcnow,
)
from .live_filters import expected_xingtu_live_request, validate_xingtu_live_request
from .normalize import number
from .xingtu_live_detail import (
    LIVE_TYPE_BY_REQUEST,
    LIVE_TYPE_META,
    build_audience,
    build_basic_extra,
    build_calendar,
    build_latest,
    build_overview_field,
    build_overview_meta,
    build_pricing,
    build_rooms,
    clean_wechat,
)

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


# Registered live-detail endpoints.  Longest path first so
# ``..._candidates`` is never mistaken for ``..._statistics``.
LIVE_DETAIL_PATHS: tuple[tuple[str, str], ...] = (
    ("/gw/api/aggregator/get_author_live_statistics_candidates", "candidates"),
    ("/gw/api/aggregator/get_author_live_statistics", "statistics"),
    ("/gw/api/aggregator/get_author_peroidic_live_analysis", "periodic"),
    ("/gw/api/aggregator/get_author_latest_live_analysis", "latest"),
    ("/gw/api/aggregator/get_author_live_room_detail", "room_detail"),
    ("/gw/api/aggregator/multi_get_room_data", "room_data"),
    ("/gw/api/aggregator/get_author_live_watch_distribution", "audience"),
    ("/gw/api/gsearch/search_for_live_room_list", "room_list"),
    ("/gw/api/author/get_author_base_info", "base_info"),
    ("/gw/api/author/get_author_marketing_info", "marketing_info"),
    ("/gw/api/author/get_author_platform_channel_info_v2", "channel_info"),
)


def _record_kind(url: str) -> str | None:
    path = urlsplit(url).path
    for suffix, kind in LIVE_DETAIL_PATHS:
        if path.endswith(suffix):
            return kind
    return None


def _query_int(record: dict[str, Any], key: str) -> int | None:
    value = (record.get("query") or {}).get(key)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _query_bool(record: dict[str, Any], key: str) -> bool | None:
    value = (record.get("query") or {}).get(key)
    if value is None:
        return None
    return str(value).lower() == "true"


class LiveDetailRecorder:
    """Correlate registered live-detail responses with their request parameters.

    The listener is attached before navigation and never parses an arbitrary response.  Only the
    registered endpoint suffixes are kept; bodies over the registry limit are dropped.  The
    business-card response (phone/email/wechat) is deliberately not registered.
    """

    def __init__(self, page: Page, max_bytes: int) -> None:
        self.page = page
        self.max_bytes = max(1, max_bytes)
        self.records: list[dict[str, Any]] = []
        self._tasks: set[asyncio.Task[None]] = set()
        self._lock = asyncio.Lock()
        self._changed = asyncio.Event()
        self._closed = False

    def attach(self) -> None:
        self.page.on("response", self._on_response)

    async def close(self) -> None:
        self._closed = True
        try:
            self.page.remove_listener("response", self._on_response)
        except Exception:  # noqa: BLE001 - the page may already be closed
            pass
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()

    def _on_response(self, response: Any) -> None:
        if self._closed:
            return
        kind = _record_kind(response.url)
        if kind is None:
            return
        task = asyncio.create_task(self._read(response, kind))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _read(self, response: Any, kind: str) -> None:
        try:
            if response.status != 200:
                return
            body = await response.body()
            if len(body) > self.max_bytes:
                return
            payload = json.loads(body)
        except Exception:  # noqa: BLE001 - a non-JSON/oversized body is not business data
            return
        if not isinstance(payload, dict):
            return
        query: dict[str, str] = {}
        try:
            parsed = parse_qs(urlsplit(response.url).query, keep_blank_values=True)
            query = {
                key: values[0]
                for key, values in parsed.items()
                if key not in {"msToken", "a_bogus"} and values
            }
        except Exception:  # noqa: BLE001 - malformed query is still a usable envelope
            query = {}
        request_body: Any = None
        if response.request.method == "POST":
            try:
                request_body = response.request.post_data_json
            except Exception:  # noqa: BLE001
                request_body = response.request.post_data
        async with self._lock:
            record = {
                "seq": len(self.records),
                "kind": kind,
                "path": urlsplit(response.url).path,
                "query": query,
                "request_body": request_body,
                "payload": payload,
                "observed_at": utcnow(),
            }
            self.records.append(record)
        self._changed.set()

    async def wait_for(
        self,
        kind: str,
        *,
        predicate: Callable[[dict[str, Any]], bool] | None = None,
        after: int = 0,
        timeout: float = 12.0,
    ) -> dict[str, Any] | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.1, timeout)
        while True:
            for record in list(self.records):
                if record["seq"] < after:
                    continue
                if record["kind"] != kind:
                    continue
                if predicate is None or predicate(record):
                    return record
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            self._changed.clear()
            try:
                await asyncio.wait_for(self._changed.wait(), min(remaining, 0.5))
            except TimeoutError:
                pass

    def latest(self, kind: str) -> dict[str, Any] | None:
        for record in reversed(self.records):
            if record["kind"] == kind:
                return record
        return None

    def all(self, kind: str) -> list[dict[str, Any]]:
        return [record for record in self.records if record["kind"] == kind]

    @property
    def mark(self) -> int:
        return len(self.records)


CLICK_TEXT_JS = r"""
(args) => {
  const [text, selector, contains, scopeSel] = args;
  const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
  };
  const root = scopeSel ? document.querySelector(scopeSel) : document;
  if (!root) return {clicked: false, reason: 'scope-missing'};
  const els = [...root.querySelectorAll(selector || '*')].filter((el) => {
    if (!visible(el)) return false;
    if (el.className && el.className.toString().includes('is-disabled')) return false;
    const t = clean(el.innerText);
    return contains ? t.includes(text) : t === text;
  });
  if (!els.length) return {clicked: false, reason: 'not-found'};
  els.sort((a, b) => clean(a.innerText).length - clean(b.innerText).length);
  const el = els[0];
  const target = el.closest(
    'label,button,a,[role=radio],[role=tab],.el-tabs__item,.el-checkbox'
  ) || el;
  target.click();
  return {clicked: true, text: clean(target.innerText).slice(0, 80),
          cls: (target.className || '').toString().slice(0, 160)};
}
"""

CLICK_SWITCH_JS = r"""
(scopeSel) => {
  const root = scopeSel ? document.querySelector(scopeSel) : document;
  if (!root) return {clicked: false, reason: 'scope-missing'};
  const sw = root.querySelector('.xt-switch');
  if (!sw) return {clicked: false, reason: 'switch-missing'};
  const target = sw.querySelector('.xt-switch__box')
    || sw.querySelector('.xt-switch__handle') || sw;
  target.click();
  return {clicked: true, cls: (sw.className || '').toString().slice(0, 180)};
}
"""

READ_SWITCH_JS = r"""
(scopeSel) => {
  const root = scopeSel ? document.querySelector(scopeSel) : document;
  const sw = root && root.querySelector('.xt-switch');
  return sw ? (sw.className || '').toString() : null;
}
"""

SELECT_OPTION_JS = r"""
(args) => {
  const [label, option] = args;
  const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.display !== 'none';
  };
  const selects = [...document.querySelectorAll('.el-select')].filter(visible);
  const box = selects.find((el) => {
    const text = clean(el.innerText);
    return text.includes(label) || [...el.querySelectorAll('.el-select-dropdown__item')]
      .some((item) => clean(item.innerText) === label);
  });
  if (!box) return {clicked: false, reason: 'select-missing'};
  const input = box.querySelector('input');
  if (!input || input.disabled) return {clicked: false, reason: 'select-disabled'};
  input.click();
  return {clicked: true, opened: true};
}
"""

PICK_OPTION_JS = r"""
(option) => {
  const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.display !== 'none';
  };
  const items = [...document.querySelectorAll('.el-select-dropdown__item')]
    .filter((el) => visible(el) && clean(el.innerText) === option);
  if (!items.length) {
    return {clicked: false, options: [...document.querySelectorAll('.el-select-dropdown__item')]
      .filter(visible).map((el) => clean(el.innerText)).slice(0, 20)};
  }
  items[0].click();
  return {clicked: true};
}
"""

PICK_OPTION_FORCE_JS = r"""
(option) => {
  const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
  const items = [...document.querySelectorAll('.el-select-dropdown__item')]
    .filter((el) => clean(el.innerText) === option);
  if (!items.length) return {clicked: false};
  items[0].click();
  return {clicked: true, cls: (items[0].className || '').toString()};
}
"""

SELECT_OPTIONS_JS = r"""
(label) => {
  const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const selects = [...document.querySelectorAll('.el-select')].filter(visible);
  const box = selects.find((el) => {
    const text = clean(el.innerText);
    return text.includes(label) || [...el.querySelectorAll('.el-select-dropdown__item')]
      .some((item) => clean(item.innerText) === label);
  }) || selects[0];
  if (!box) return {found: false, options: []};
  return {
    found: true,
    placeholder: box.querySelector('input') ? box.querySelector('input').placeholder : null,
    disabled: box.querySelector('input') ? box.querySelector('input').disabled : null,
    text: clean(box.innerText).slice(0, 80),
    options: [...box.querySelectorAll('.el-select-dropdown__item')]
      .map((el) => clean(el.innerText)),
  };
}
"""

CLICK_PAGER_JS = r"""
(pageNo) => {
  const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
  const items = [...document.querySelectorAll('.el-pager li')].filter(
    (el) => clean(el.innerText) === String(pageNo) && el.getBoundingClientRect().width > 0
  );
  if (!items.length) return {clicked: false, reason: 'pager-missing'};
  items[0].click();
  return {clicked: true};
}
"""

ACTIVE_TYPE_JS = r"""
() => {
  const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
  const radios = [...document.querySelectorAll('.el-radio-button')].filter(
    (el) => el.getBoundingClientRect().width > 0
  );
  return {
    active: (() => {
      const hit = radios.find((el) => el.className.toString().includes('is-active'));
      return hit ? clean(hit.innerText) : null;
    })(),
    all: radios.map((el) => ({
      text: clean(el.innerText),
      disabled: el.className.toString().includes('is-disabled'),
    })),
  };
}
"""

ACTIVE_TAB_JS = r"""
() => {
  const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
  const tabs = [...document.querySelectorAll('.el-tabs__item.is-top')].filter(
    (el) => el.getBoundingClientRect().width > 0
  );
  const active = tabs.find((el) => el.className.toString().includes('is-active'));
  return active ? clean(active.innerText) : null;
}
"""

CHECKBOX_STATE_JS = r"""
(text) => {
  const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
  const boxes = [...document.querySelectorAll('.el-checkbox')].filter(
    (el) => el.getBoundingClientRect().width > 0 && clean(el.innerText).includes(text)
  );
  if (!boxes.length) return null;
  return {
    cls: (boxes[0].className || '').toString(),
    checked: boxes[0].className.toString().includes('is-checked'),
  };
}
"""


class XingtuLiveAdapter(BrowserAdapter):
    """Live-square browser adapter for one authenticated Xingtu unit."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._stats: dict[str, Any] = {}
        self._basic: dict[str, Any] = {}
        self._search_keyword: str | None = None
        self._no_live = False
        self._recorder: LiveDetailRecorder | None = None
        self._default_stats: dict[str, Any] = {}
        self._default_stats_params: dict[str, str] = {}
        self._wechat: str | None = None

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
        self._default_stats = {}
        self._default_stats_params = {}
        self._no_live = False
        self._wechat = None
        recorder = LiveDetailRecorder(page, self.registry.response_body_max_bytes or 8_000_000)
        self._recorder = recorder
        recorder.attach()
        page.set_default_timeout(min(self.timeout_seconds() * 1000, 20_000))
        try:
            await self.guard()
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
            # The live-detail requests are emitted by the homepage load.  They are recorded from
            # before navigation, so a slow or absent module is NO_DATA rather than a lost response.
            await asyncio.gather(
                recorder.wait_for("candidates", timeout=8),
                recorder.wait_for("base_info", timeout=8),
                recorder.wait_for("marketing_info", timeout=8),
                recorder.wait_for("channel_info", timeout=8),
            )
            default_record = await recorder.wait_for(
                "statistics",
                predicate=lambda record: (
                    _query_int(record, "live_type") in {None, 1}
                    and _query_int(record, "period") in {None, 30}
                ),
                timeout=10,
            )
            if default_record is None:
                default_record = recorder.latest("statistics")
            if default_record is not None:
                self._default_stats = default_record["payload"]
                self._default_stats_params = dict(default_record["query"])
            self._stats = self._default_stats
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
            # Minimal live-only page interaction: open the contact popover and the WeChat dialog,
            # read .wechat, then close it before module collectors run.  A missing/unauthorized
            # control is NO_DATA, never a reason to fail the whole creator.
            self._wechat = await self._read_wechat(page)
            yield
        finally:
            self.detail_page = None
            self._stats = {}
            self._basic = {}
            self._default_stats = {}
            self._default_stats_params = {}
            self._wechat = None
            self._recorder = None
            await recorder.close()
            await page.close()

    async def _read_wechat(self, page: Page) -> str | None:
        """Open 联系 -> 查看微信 and read only the explicit dialog value.

        The contact popover is the platform's own authorized entry point.  No consent/paywall is
        bypassed: if the item or dialog is absent, the field is NO_DATA.  The copy icon is never
        clicked; the dialog is closed before the module collectors continue.
        """

        try:
            contact = (
                page.locator(".operate-title").filter(has_text=re.compile(r"^\s*联系\s*$")).first
            )
            if await contact.count() == 0:
                return None
            await contact.hover(timeout=4_000)
            await asyncio.sleep(0.6)
            view = (
                page.locator(".op-more-text").filter(has_text=re.compile(r"^\s*查看微信\s*$")).first
            )
            if await view.count() == 0 or not await view.is_visible():
                await page.keyboard.press("Escape")
                return None
            await view.click(timeout=4_000)
            await asyncio.sleep(0.8)
            value_node = page.locator('.el-dialog[aria-label="达人微信"] .wechat').first
            try:
                await value_node.wait_for(state="visible", timeout=3_000)
            except PlaywrightTimeoutError:
                await page.keyboard.press("Escape")
                return None
            text = await value_node.inner_text(timeout=2_000)
            close = page.locator('.el-dialog[aria-label="达人微信"] .el-dialog__headerbtn').first
            if await close.count():
                await close.click(timeout=2_000)
            else:
                await page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
            return clean_wechat(text)
        except Exception:  # noqa: BLE001 - contact UI absence is a field-level NO_DATA
            try:
                await page.keyboard.press("Escape")
            except Exception:  # noqa: BLE001 - page may already be closing
                pass
            return None

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
        if isinstance(raw, list):
            values = [str(item) for item in raw if str(item).strip()]
            if not values:
                return FieldObservation(
                    field_key=key,
                    status=FieldStatus.NO_DATA,
                    operation_id=operation,
                    session_version=ctx.session_version,
                    source_kind=source_kind,
                    source_contract=self.registry.contract_version,
                    path_ref=path,
                    evidence_refs=[f"{operation}:{path}:empty-list"],
                )
            return FieldObservation(
                field_key=key,
                value=values,
                status=FieldStatus.COLLECTED,
                operation_id=operation,
                session_version=ctx.session_version,
                source_kind=source_kind,
                source_contract=self.registry.contract_version,
                path_ref=path,
                observed_at=utcnow(),
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
        if isinstance(raw, str) and unit == "second":
            try:
                if float(raw.replace(",", "")) > 86400:
                    return FieldObservation(
                        field_key=key,
                        status=FieldStatus.NOT_PROVIDED,
                        operation_id=operation,
                        session_version=ctx.session_version,
                        unit=unit,
                        failure_reason=(
                            "UNIT_AMBIGUOUS: watch duration is outside a per-view second range"
                        ),
                        source_kind=source_kind,
                        source_contract=self.registry.contract_version,
                        path_ref=path,
                        evidence_refs=[f"{operation}:{path}:unit-ambiguous"],
                    )
            except ValueError:
                pass
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

    def _basic_extra(self) -> dict[str, Any]:
        recorder = self._recorder
        if recorder is None:
            return {}
        base = recorder.latest("base_info")
        channel = recorder.latest("channel_info")
        try:
            return build_basic_extra(
                base["payload"] if base else None,
                channel["payload"] if channel else None,
            )
        except CollectorError:
            return {}

    def _basic_fields(
        self, creator: CreatorRef, ctx: ExecutionContext, operation: str
    ) -> list[FieldObservation]:
        extra = self._basic_extra()
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
            "douyin_id": None,
            "content_tags": None,
            "business_order_types": None,
            "introduction": None,
            "wechat": None,
        }
        fields: list[FieldObservation] = []
        for key in self.module_fields.get("basic", list(mappings)):
            unit = mappings.get(key)
            if key == "platform_creator_id":
                raw: Any = creator.platform_creator_id
                source_kind: Literal["response", "dom", "api"] = "dom"
                path = f"live-basic.{key}"
            elif key == "douyin_id":
                raw = extra.get("douyin_id")
                source_kind = "response"
                path = "get_author_base_info.unique_id|short_id"
            elif key == "content_tags":
                raw = extra.get("content_tags")
                source_kind = "response"
                path = "get_author_base_info.live_labels_v2"
            elif key == "business_order_types":
                raw = extra.get("business_order_types")
                source_kind = "response"
                path = "get_author_base_info.live_order_labels"
            elif key == "introduction":
                raw = extra.get("introduction")
                source_kind = "response"
                path = "get_author_platform_channel_info_v2.self_intro"
            elif key == "wechat":
                raw = self._wechat
                source_kind = "dom"
                path = 'dialog[aria-label="达人微信"].wechat'
            elif key == "content_type":
                raw = self._basic_value(key) or ((extra.get("content_types") or [None])[0])
                source_kind = "dom"
                path = "live-basic.content_type|live_labels_v2"
            else:
                raw = self._basic_value(key)
                source_kind = "dom"
                path = f"live-basic.{key}"
            fields.append(
                self._observation(
                    key,
                    raw,
                    ctx=ctx,
                    operation=operation,
                    source_kind=source_kind,
                    path=path,
                    unit=unit,
                )
            )
        return fields

    def _live_fields(
        self, creator: CreatorRef, ctx: ExecutionContext, operation: str
    ) -> list[FieldObservation]:
        stats = {} if self._no_live else (self._stats or self._default_stats)
        room = stats.get("live_room_statistics")
        ecom = stats.get("live_ecom_statistics")
        if not isinstance(room, dict):
            room = {}
        if not isinstance(ecom, dict):
            ecom = {}
        period_days = self._default_stats_params.get("period")
        period = f"近{period_days}天" if period_days in {"30", "90"} else "近30天"
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
                    period=period,
                )
            )
        return fields

    def _structured_field(
        self,
        key: str,
        data: dict[str, Any] | None,
        ctx: ExecutionContext,
        operation: str,
        *,
        path: str,
        period: str | None = None,
        reason: str | None = None,
    ) -> FieldObservation:
        if data is None:
            return FieldObservation(
                field_key=key,
                status=FieldStatus.NO_DATA,
                operation_id=operation,
                session_version=ctx.session_version,
                period_label=period,
                source_kind="response",
                source_contract=self.registry.contract_version,
                path_ref=path,
                evidence_refs=[f"{operation}:{path}:{reason or 'no-data'}"],
            )
        return FieldObservation(
            field_key=key,
            value=StructuredValue(data=data),
            status=FieldStatus.COLLECTED,
            operation_id=operation,
            session_version=ctx.session_version,
            period_label=period,
            source_kind="response",
            source_contract=self.registry.contract_version,
            path_ref=path,
            observed_at=utcnow(),
        )

    def _pricing_fields(self, ctx: ExecutionContext, operation: str) -> list[FieldObservation]:
        record = self._recorder.latest("marketing_info") if self._recorder else None
        data = build_pricing(record["payload"]) if record else None
        return [
            self._structured_field(
                "pricing.services",
                data,
                ctx,
                operation,
                path="get_author_marketing_info.price_info",
                reason="no-live-service-quote",
            )
        ]

    # -- live-detail interactions -------------------------------------------------------

    @staticmethod
    def _type_label(live_type: str) -> str:
        return LIVE_TYPE_META.get(live_type, (live_type, 0))[0]

    @staticmethod
    def _type_request(live_type: str) -> int | None:
        return LIVE_TYPE_META.get(live_type, (live_type, 0))[1] or None

    @staticmethod
    def _canonical_type(value: Any) -> str | None:
        try:
            return LIVE_TYPE_BY_REQUEST.get(int(value))
        except (TypeError, ValueError):
            return None

    async def _ensure_top_tab(self, page: Page, label: str) -> bool:
        result = await page.evaluate(CLICK_TEXT_JS, [label, ".el-tabs__item", False, None])
        if not isinstance(result, dict) or not result.get("clicked"):
            return False
        await asyncio.sleep(min(self.registry.action_interval_seconds or 1.0, 2.0))
        return True

    async def _ensure_section(self, page: Page, label: str) -> bool:
        active = await page.evaluate(ACTIVE_TAB_JS)
        if isinstance(active, str) and active.strip() == label:
            return True
        return await self._ensure_top_tab(page, label)

    async def _available_types(self, page: Page, recorder: LiveDetailRecorder) -> list[str]:
        candidates = recorder.latest("candidates")
        payload = candidates["payload"] if candidates else {}
        for key in ("candidates_90d", "candidates_30d"):
            block = payload.get(key) if isinstance(payload, dict) else None
            if isinstance(block, dict) and any(block.get(item) for item in LIVE_TYPE_META):
                return [item for item in LIVE_TYPE_META if block.get(item)]
        state = await page.evaluate(ACTIVE_TYPE_JS)
        radios = (state or {}).get("all") if isinstance(state, dict) else None
        labels = {
            "不限": "general",
            "游戏直播": "game",
            "电商带货": "ecom",
            "其它直播": "other",
            "其他直播": "other",
        }
        found: list[str] = []
        for radio in radios or []:
            if not isinstance(radio, dict) or radio.get("disabled"):
                continue
            value = labels.get(str(radio.get("text") or "").strip())
            if value and value not in found:
                found.append(value)
        return found

    async def _click_type(self, page: Page, live_type: str) -> bool:
        result = await page.evaluate(
            CLICK_TEXT_JS, [self._type_label(live_type), ".el-radio-button", False, None]
        )
        if not isinstance(result, dict) or not result.get("clicked"):
            return False
        await asyncio.sleep(0.4)
        return True

    async def _read_options(self, page: Page, label: str) -> list[str]:
        result = await page.evaluate(SELECT_OPTIONS_JS, label)
        if not isinstance(result, dict):
            return []
        options = result.get("options")
        return [str(item) for item in options] if isinstance(options, list) else []

    async def _select_option(self, page: Page, label: str, option: str) -> bool:
        # The audience/period controls are temporarily removed while their section reloads.  Wait
        # for the select to reappear and retry the open+pick when the popup re-renders under us.
        for _ in range(24):
            value = await page.evaluate(SELECT_OPTIONS_JS, label)
            state = value if isinstance(value, dict) else None
            if not state or not state.get("found"):
                await asyncio.sleep(0.5)
                continue
            if state.get("value") == option:
                return True
            opened = await page.evaluate(SELECT_OPTION_JS, [label, option])
            if not isinstance(opened, dict) or not opened.get("clicked"):
                await asyncio.sleep(0.5)
                continue
            await asyncio.sleep(0.8)
            picked = await page.evaluate(PICK_OPTION_JS, option)
            if not isinstance(picked, dict) or not picked.get("clicked"):
                # Element UI keeps the options in the DOM; clicking the hidden item still invokes
                # its handler and is more reliable than relying on the popup's animation state.
                picked = await page.evaluate(PICK_OPTION_FORCE_JS, option)
            if isinstance(picked, dict) and picked.get("clicked"):
                await asyncio.sleep(0.6)
                return True
            await asyncio.sleep(0.5)
        # Last resort: a real Playwright click sequence.  This handles Element UI instances that
        # ignore synthetic JS clicks in the unit's persistent browser profile.
        try:
            select = (
                page.locator(".el-select")
                .filter(has=page.locator(".el-select-dropdown__item", has_text=label))
                .first
            )
            if await select.count():
                await select.locator("input").click(timeout=5000)
                option_locator = page.locator(".el-select-dropdown__item").filter(
                    has_text=re.compile(rf"^{re.escape(option)}$")
                )
                await option_locator.first.click(timeout=5000)
                await asyncio.sleep(0.8)
                return True
        except Exception as exc:  # noqa: BLE001 - fallback diagnostics only
            logger.info(
                "live select locator fallback failed label=%s option=%s err=%s",
                label,
                option,
                type(exc).__name__,
            )
        logger.info("live select failed label=%s option=%s", label, option)
        return False

    async def _toggle_flow(self, page: Page) -> str | None:
        result = await page.evaluate(CLICK_SWITCH_JS, ".module-card.data-overview")
        if not isinstance(result, dict) or not result.get("clicked"):
            return None
        await asyncio.sleep(0.4)
        return str(result.get("cls") or "")

    async def _read_flow(self, page: Page) -> str | None:
        value = await page.evaluate(READ_SWITCH_JS, ".module-card.data-overview")
        return str(value) if value else None

    async def _checkbox_state(self, page: Page) -> dict[str, Any] | None:
        value = await page.evaluate(CHECKBOX_STATE_JS, "只看星图商单")
        return value if isinstance(value, dict) else None

    async def _click_star(self, page: Page) -> bool:
        result = await page.evaluate(CLICK_TEXT_JS, ["只看星图商单", ".el-checkbox", True, None])
        if not isinstance(result, dict) or not result.get("clicked"):
            return False
        await asyncio.sleep(0.5)
        return True

    @staticmethod
    def _matches(
        record: dict[str, Any],
        *,
        live_type: int | None = None,
        period: int | None = None,
        flow_type: int | None = None,
        only_star_order: bool | None = None,
        crowd_type: int | None = None,
    ) -> bool:
        if live_type is not None and _query_int(record, "live_type") != live_type:
            return False
        if period is not None and _query_int(record, "period") != period:
            return False
        if flow_type is not None and _query_int(record, "flow_type") != flow_type:
            return False
        if (
            only_star_order is not None
            and _query_bool(record, "only_star_order") != only_star_order
        ):
            return False
        if crowd_type is not None and _query_int(record, "live_crowd_type") != crowd_type:
            return False
        return True

    async def _wait_stats(
        self,
        recorder: LiveDetailRecorder,
        *,
        live_type: int | None = None,
        period: int | None = None,
        flow_type: int | None = None,
        only_star_order: bool | None = None,
        after: int = 0,
        timeout: float = 15.0,
    ) -> dict[str, Any] | None:
        record = await recorder.wait_for(
            "statistics",
            predicate=lambda item: self._matches(
                item,
                live_type=live_type,
                period=period,
                flow_type=flow_type,
                only_star_order=only_star_order,
            ),
            after=after,
            timeout=timeout,
        )
        if record is not None:
            return record
        # Clicking an already-active tab may reuse the cached response instead of issuing a new
        # request.  Fall back to the newest recorded response for the same dimensions; a response
        # for another type/period/calibre is never substituted.
        for item in reversed(recorder.all("statistics")):
            if self._matches(
                item,
                live_type=live_type,
                period=period,
                flow_type=flow_type,
                only_star_order=only_star_order,
            ):
                return item
        return None

    @staticmethod
    def _capture_payload(record: dict[str, Any]) -> dict[str, Any]:
        observed_at = record.get("observed_at")
        formatter = getattr(observed_at, "isoformat", None)
        return {
            "payload": record.get("payload"),
            "path": record.get("path"),
            # StructuredValue.data must be plain JSON; a datetime is not a JSON value.
            "observed_at": formatter() if callable(formatter) else observed_at,
        }

    def _overview_capture(self, record: dict[str, Any]) -> dict[str, Any] | None:
        live_type = self._canonical_type(_query_int(record, "live_type"))
        if live_type is None:
            return None
        period = _query_int(record, "period")
        flow_type = _query_int(record, "flow_type")
        star = _query_bool(record, "only_star_order")
        capture = self._capture_payload(record)
        capture.update(
            {
                "live_type": live_type,
                "period": period,
                "flow_type": flow_type,
                "only_star_order": bool(star) if star is not None else False,
                "excluded_marketing": (flow_type == 1 if flow_type is not None else None),
            }
        )
        return capture

    async def _collect_room_pages(
        self, page: Page, recorder: LiveDetailRecorder, *, max_pages: int = 12
    ) -> dict[str, Any] | None:
        first = recorder.latest("room_list")
        if first is None:
            first = await recorder.wait_for("room_list", timeout=10)
        if first is None:
            return None
        list_pages: list[dict[str, Any]] = []
        room_items: dict[str, dict[str, Any]] = {}
        current = first
        for _ in range(max_pages):
            payload = current.get("payload")
            if not isinstance(payload, dict):
                break
            pagination_obj = payload.get("pagination")
            pagination = pagination_obj if isinstance(pagination_obj, dict) else {}
            request_body = current.get("request_body")
            page_no = request_body.get("page") if isinstance(request_body, dict) else None
            try:
                page_no = int(page_no) if page_no is not None else int(pagination.get("page") or 1)
            except (TypeError, ValueError):
                page_no = len(list_pages) + 1
            list_pages.append({"page": page_no, "payload": payload})
            ids = payload.get("item_ids")
            first_id = str(ids[0]) if isinstance(ids, list) and ids else None
            if first_id:

                def matches_room_data(
                    item: dict[str, Any], first_id: str | None = first_id
                ) -> bool:
                    if first_id is None:
                        return False
                    query = item.get("query") or {}
                    return first_id in str(query.get("room_ids") or "")

                data_record = await recorder.wait_for(
                    "room_data",
                    predicate=matches_room_data,
                    after=current["seq"],
                    timeout=12,
                )
                if data_record is not None:
                    self._merge_room_items(room_items, data_record.get("payload"))
            if not pagination.get("has_more"):
                break
            next_page = page_no + 1
            clicked = await page.evaluate(CLICK_PAGER_JS, next_page)
            if not isinstance(clicked, dict) or not clicked.get("clicked"):
                break

            def matches_page(item: dict[str, Any], next_page: int = next_page) -> bool:
                return self._page_number(item) == next_page

            following = await recorder.wait_for(
                "room_list",
                predicate=matches_page,
                after=current["seq"],
                timeout=12,
            )
            if following is None:
                break
            current = following
        return {"pages": list_pages, "room_items": room_items, "max_pages": max_pages}

    @staticmethod
    def _page_number(record: dict[str, Any]) -> int | None:
        body = record.get("request_body")
        if isinstance(body, dict):
            raw = body.get("page")
            if raw is None:
                return None
            try:
                return int(raw)
            except (TypeError, ValueError):
                return None
        return None

    @staticmethod
    def _merge_room_items(target: dict[str, dict[str, Any]], payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        items = payload.get("items")
        if not isinstance(items, list):
            return
        for item in items:
            if isinstance(item, dict) and item.get("room_id"):
                target[str(item["room_id"])] = item

    @staticmethod
    def _latest_types(records: Iterable[dict[str, Any]]) -> dict[str, str]:
        result: dict[str, str] = {}
        for record in records:
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue
            rooms = payload.get("latest_live_rooms")
            if not isinstance(rooms, list):
                continue
            for room in rooms:
                if not isinstance(room, dict) or room.get("room_id") is None:
                    continue
                value = room.get("live_type")
                if value is None:
                    continue
                try:
                    live_type = LIVE_TYPE_BY_REQUEST.get(int(value))
                except (TypeError, ValueError):
                    live_type = None
                if live_type:
                    result[str(room["room_id"])] = live_type
        return result

    @staticmethod
    def _latest_kind(
        recorder: LiveDetailRecorder, kind: str, request_type: int | None
    ) -> dict[str, Any] | None:
        for record in reversed(recorder.all(kind)):
            if request_type is None or _query_int(record, "live_type") == request_type:
                return record
        return None

    async def _analysis_fields(
        self, ctx: ExecutionContext, operation: str
    ) -> list[FieldObservation]:
        page, recorder = self.detail_page, self._recorder
        if page is None or recorder is None:
            raise CollectorError("MODULE_COLLECTION_FAILED", "LIVE_DETAIL_PAGE_MISSING")
        if self._no_live:
            return self._no_live_fields("live_analysis", ctx, operation, "live-tab-absent")
        if not await self._ensure_top_tab(page, "直播分析"):
            raise CollectorError("MODULE_COLLECTION_FAILED", "LIVE_ANALYSIS_TAB_MISSING")
        await asyncio.sleep(1.0)
        types = await self._available_types(page, recorder)
        # Capture the 90-day room list before switching live types.  The list is tied to the page's
        # current type/date state; capturing it first preserves the default (不限/近90天) window and
        # avoids inheriting the last type tab's filtered population.
        room_data = await self._collect_room_pages(page, recorder)
        captures: dict[str, dict[str, Any]] = {}
        latest_records: list[dict[str, Any]] = []
        for live_type in types:
            request_type = self._type_request(live_type)
            mark = recorder.mark
            if not await self._click_type(page, live_type):
                continue

            def matches_type(item: dict[str, Any], request_type: int | None = request_type) -> bool:
                return _query_int(item, "live_type") == request_type

            periodic = await recorder.wait_for(
                "periodic",
                predicate=matches_type,
                after=mark,
                timeout=15,
            )
            latest = await recorder.wait_for(
                "latest",
                predicate=matches_type,
                after=mark,
                timeout=15,
            )
            if periodic is None:
                periodic = self._latest_kind(recorder, "periodic", request_type)
            if latest is None:
                latest = self._latest_kind(recorder, "latest", request_type)
            months: list[dict[str, Any]] = []
            if periodic is not None:
                months.append(
                    {
                        "year": _query_int(periodic, "year"),
                        "month": _query_int(periodic, "month"),
                        "flow_type": _query_int(periodic, "flow_type"),
                        "only_star_order": bool(_query_bool(periodic, "only_star_order")),
                        "excluded_marketing": _query_int(periodic, "flow_type") == 1,
                        "payload": periodic.get("payload"),
                        "path": periodic.get("path"),
                    }
                )
                payload = periodic.get("payload")
                rooms = payload.get("live_rooms") if isinstance(payload, dict) else None
                if isinstance(rooms, list) and not rooms:
                    previous_mark = recorder.mark
                    clicked = await page.evaluate(CLICK_TEXT_JS, ["上个月", "button", False, None])
                    if isinstance(clicked, dict) and clicked.get("clicked"):

                        def matches_previous(
                            item: dict[str, Any], request_type: int | None = request_type
                        ) -> bool:
                            return _query_int(item, "live_type") == request_type

                        previous = await recorder.wait_for(
                            "periodic",
                            predicate=matches_previous,
                            after=previous_mark,
                            timeout=12,
                        )
                        if previous is not None:
                            months.append(
                                {
                                    "year": _query_int(previous, "year"),
                                    "month": _query_int(previous, "month"),
                                    "flow_type": _query_int(previous, "flow_type"),
                                    "only_star_order": bool(
                                        _query_bool(previous, "only_star_order")
                                    ),
                                    "excluded_marketing": _query_int(previous, "flow_type") == 1,
                                    "payload": previous.get("payload"),
                                    "path": previous.get("path"),
                                }
                            )
            if latest is not None:
                latest_records.append(latest)
            captures[live_type] = {
                "months": months,
                "latest": latest.get("payload") if latest else None,
            }
        latest_types = self._latest_types(latest_records)
        results: dict[str, dict[str, Any] | None] = {}
        for live_type in LIVE_TYPE_META:
            entry = captures.get(live_type)
            if entry is None or not entry.get("months"):
                results[f"analysis.{live_type}.calendar"] = None
            else:
                results[f"analysis.{live_type}.calendar"] = build_calendar(
                    entry["months"], live_type=live_type
                )
            results[f"analysis.{live_type}.latest"] = (
                build_latest(entry["latest"], live_type=live_type)
                if entry and entry.get("latest") is not None
                else None
            )
        results["analysis.rooms"] = (
            build_rooms(
                list_pages=room_data["pages"],
                room_items=room_data["room_items"],
                latest_types=latest_types,
                max_pages=room_data["max_pages"],
            )
            if room_data
            else None
        )
        fields: list[FieldObservation] = []
        for key in self.module_fields.get("live_analysis", []):
            data = results.get(key)
            if data is None:
                fields.append(self._no_data_field(key, ctx, operation, "live-analysis-no-data"))
            else:
                fields.append(
                    self._structured_field(
                        key, data, ctx, operation, path="live-analysis", period="近90天"
                    )
                )
        return fields

    async def _audience_fields(
        self, ctx: ExecutionContext, operation: str
    ) -> list[FieldObservation]:
        page, recorder = self.detail_page, self._recorder
        if page is None or recorder is None:
            raise CollectorError("MODULE_COLLECTION_FAILED", "LIVE_DETAIL_PAGE_MISSING")
        if self._no_live:
            return self._no_live_fields("live_audience", ctx, operation, "live-tab-absent")
        if not await self._ensure_top_tab(page, "受众画像"):
            raise CollectorError("MODULE_COLLECTION_FAILED", "LIVE_AUDIENCE_TAB_MISSING")
        crowd_options: list[str] = []
        for _ in range(20):
            await asyncio.sleep(0.5)
            crowd_options = await self._read_options(page, "粉丝画像")
            if crowd_options:
                break
        types = await self._available_types(page, recorder)
        logger.info("live audience options=%s types=%s", crowd_options, types)
        crowd_map = [("fans", "粉丝画像", 2), ("user", "观众画像", 1)]
        available_crowds = [
            item for item in crowd_map if any(option == item[1] for option in crowd_options)
        ]
        if not available_crowds:
            available_crowds = [("fans", "粉丝画像", 2)]
        results: dict[str, dict[str, Any] | None] = {}
        # Select the crowd once, then switch live type.  Selecting a crowd after every type made
        # the Element UI select unavailable during the section's loading state.
        for crowd_key, crowd_label, crowd_value in available_crowds:
            selected = await self._select_option(page, "粉丝画像", crowd_label)
            logger.info("live audience crowd=%s selected=%s", crowd_key, selected)
            for live_type in types:
                request_type = self._type_request(live_type)
                mark = recorder.mark
                if not await self._click_type(page, live_type):
                    continue
                await self._ensure_section(page, "受众画像")

                def matches_crowd(
                    item: dict[str, Any],
                    request_type: int | None = request_type,
                    crowd_value: int = crowd_value,
                ) -> bool:
                    return (
                        _query_int(item, "live_type") == request_type
                        and _query_int(item, "live_crowd_type") == crowd_value
                    )

                record = await recorder.wait_for(
                    "audience",
                    predicate=matches_crowd,
                    after=mark,
                    timeout=15,
                )
                if record is None:
                    record = next(
                        (
                            item
                            for item in reversed(recorder.all("audience"))
                            if _query_int(item, "live_type") == request_type
                            and _query_int(item, "live_crowd_type") == crowd_value
                        ),
                        None,
                    )
                logger.info(
                    "live audience type=%s crowd=%s record=%s",
                    live_type,
                    crowd_key,
                    "yes" if record else "no",
                )
                results[f"audience.{live_type}.{crowd_key}"] = (
                    build_audience(
                        record.get("payload"),
                        live_type=live_type,
                        crowd_type=crowd_key,
                        request_crowd_type=crowd_value,
                    )
                    if record
                    else None
                )
        fields: list[FieldObservation] = []
        for key in self.module_fields.get("live_audience", []):
            data = results.get(key)
            if data is None:
                fields.append(self._no_data_field(key, ctx, operation, "live-audience-no-data"))
            else:
                fields.append(
                    self._structured_field(
                        key, data, ctx, operation, path="live-audience", period="近90天"
                    )
                )
        return fields

    async def _overview_fields(
        self, ctx: ExecutionContext, operation: str
    ) -> list[FieldObservation]:
        page, recorder = self.detail_page, self._recorder
        if page is None or recorder is None:
            raise CollectorError("MODULE_COLLECTION_FAILED", "LIVE_DETAIL_PAGE_MISSING")
        candidates_record = recorder.latest("candidates")
        candidates = candidates_record.get("payload") if candidates_record else None
        if self._no_live:
            fields = self._no_live_fields("live_overview", ctx, operation, "live-tab-absent")
            meta = build_overview_meta(
                candidates=candidates if isinstance(candidates, dict) else None,
                captures=[],
                default_type=None,
                default_period=None,
                default_flow_type=None,
                default_only_star_order=None,
                not_captured=["live-tab-absent"],
                policy="live-detail-tab-absent",
            )
            fields[0] = self._structured_field(
                "overview.meta", meta, ctx, operation, path="live-overview.meta"
            )
            return fields
        if not await self._ensure_top_tab(page, "数据概览"):
            raise CollectorError("MODULE_COLLECTION_FAILED", "LIVE_OVERVIEW_TAB_MISSING")
        await asyncio.sleep(1.0)
        default_record = recorder.latest("statistics")
        default_type = (
            self._canonical_type(_query_int(default_record, "live_type"))
            if default_record
            else None
        ) or "general"
        default_period = _query_int(default_record, "period") if default_record else 30
        default_flow = _query_int(default_record, "flow_type") if default_record else 1
        default_star = _query_bool(default_record, "only_star_order") if default_record else False
        types = await self._available_types(page, recorder)
        captures: list[dict[str, Any]] = []
        not_captured: list[str] = []

        # The page may persist a non-default period.  Capture the default period first, then the
        # other option offered by the time select, so both 近30天 and 近90天 are stored.
        async def capture_types(period: int | None, suffix: str) -> None:
            for live_type in types:
                request_type = self._type_request(live_type)
                mark = recorder.mark
                if not await self._click_type(page, live_type):
                    not_captured.append(f"{live_type}:tab-unavailable")
                    continue
                await self._ensure_section(page, "数据概览")
                record = await self._wait_stats(
                    recorder,
                    live_type=request_type,
                    period=period,
                    after=mark,
                    timeout=15,
                )
                if record is not None:
                    capture = self._overview_capture(record)
                    if capture:
                        captures.append(capture)

        await capture_types(default_period, "default")
        options = await self._read_options(page, "近30天")
        current_option = next((option for option in options if str(default_period) in option), None)
        other_option = next((option for option in options if option != current_option), None)
        other_period = None
        if other_option is not None:
            digits = re.search(r"(\d+)", other_option)
            other_period = int(digits.group(1)) if digits else None
        if other_option and other_period is not None and other_period != default_period:
            if await self._select_option(page, "近30天", other_option):
                await asyncio.sleep(1.0)
                await capture_types(other_period, "alternate")
                if current_option:
                    await self._select_option(page, "近30天", current_option)
            else:
                not_captured.append(f"period:{other_period}:select-failed")
        else:
            not_captured.append("period:only-one-option")
        # Marketing-flow and star-order calibre sweep, bounded to the default type.
        default_request = self._type_request(default_type)
        flow_mark = recorder.mark
        if await self._click_type(page, default_type):
            await self._ensure_section(page, "数据概览")
            toggled = await self._toggle_flow(page)
            if toggled is not None:
                record = await self._wait_stats(
                    recorder, live_type=default_request, after=flow_mark, timeout=12
                )
                if record is None:
                    # Some page states change the switch visually but only refetch after the type
                    # tab is touched again.  Force one correlated request and keep the actual query.
                    force_mark = recorder.mark
                    await self._click_type(page, default_type)
                    record = await self._wait_stats(
                        recorder, live_type=default_request, after=force_mark, timeout=12
                    )
                if record is not None:
                    capture = self._overview_capture(record)
                    if capture:
                        captures.append(capture)
                await self._toggle_flow(page)
        star_state = await self._checkbox_state(page)
        if star_state is not None and not star_state.get("checked"):
            star_mark = recorder.mark
            if await self._click_star(page):
                record = await self._wait_stats(
                    recorder,
                    live_type=default_request,
                    only_star_order=True,
                    after=star_mark,
                    timeout=12,
                )
                if record is not None:
                    capture = self._overview_capture(record)
                    if capture:
                        captures.append(capture)
                await self._click_star(page)
        else:
            not_captured.append(f"{default_type}:star-order-control-unavailable")
        if not any(item.get("flow_type") == 0 for item in captures):
            not_captured.append("flow:0:alternate-not-captured")
        if len(types) > 1:
            for live_type in types:
                if live_type != default_type:
                    not_captured.append(f"{live_type}:alternate-flow-star-not-captured")
        results: dict[str, dict[str, Any] | None] = {}
        for live_type in LIVE_TYPE_META:
            relevant = [item for item in captures if item.get("live_type") == live_type]
            results[f"overview.{live_type}"] = (
                build_overview_field(relevant, live_type=live_type) if relevant else None
            )
        meta = build_overview_meta(
            candidates=candidates if isinstance(candidates, dict) else None,
            captures=captures,
            default_type=default_type,
            default_period=default_period,
            default_flow_type=default_flow,
            default_only_star_order=default_star,
            not_captured=not_captured,
            policy="types x each period offered by the UI; flow/star sweep on default type only",
        )
        results["overview.meta"] = meta
        fields = []
        for key in self.module_fields.get("live_overview", []):
            if key == "overview.meta":
                fields.append(
                    self._structured_field(key, meta, ctx, operation, path="live-overview.meta")
                )
                continue
            data = results.get(key)
            if data is None:
                fields.append(self._no_data_field(key, ctx, operation, "live-overview-no-data"))
            else:
                fields.append(
                    self._structured_field(key, data, ctx, operation, path="live-overview")
                )
        return fields

    def _no_data_field(
        self, key: str, ctx: ExecutionContext, operation: str, reason: str
    ) -> FieldObservation:
        return FieldObservation(
            field_key=key,
            status=FieldStatus.NO_DATA,
            operation_id=operation,
            session_version=ctx.session_version,
            source_kind="response",
            source_contract=self.registry.contract_version,
            path_ref=reason,
            evidence_refs=[f"{operation}:{reason}"],
        )

    def _no_live_fields(
        self, module_key: str, ctx: ExecutionContext, operation: str, reason: str
    ) -> list[FieldObservation]:
        return [
            self._no_data_field(key, ctx, operation, reason)
            for key in self.module_fields.get(module_key, [])
        ]

    async def collect_module(
        self,
        key: str,
        creator: CreatorRef,
        ctx: ExecutionContext,
        row_covers: Any = None,
    ) -> Any:
        del row_covers
        operation = uid()
        if key == "basic":
            fields = self._basic_fields(creator, ctx, operation)
        elif key == "live":
            fields = self._live_fields(creator, ctx, operation)
        elif key == "live_pricing":
            fields = self._pricing_fields(ctx, operation)
        elif key == "live_analysis":
            fields = await self._analysis_fields(ctx, operation)
        elif key == "live_audience":
            fields = await self._audience_fields(ctx, operation)
        elif key == "live_overview":
            fields = await self._overview_fields(ctx, operation)
        else:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "UNKNOWN_LIVE_MODULE")
        return ModuleObservation(
            creator_ref=creator,
            module_key=key,
            source_period_label=(
                f"近{self._default_stats_params.get('period', 30)}天" if key == "live" else None
            ),
            fields=fields,
            expected_fields=self.module_fields[key],
            operation_id=operation,
            contract_version=self.registry.contract_version,
        )

    async def collect_featured_collections(self, *args: Any, **kwargs: Any) -> list[Any]:
        del args, kwargs
        return []
