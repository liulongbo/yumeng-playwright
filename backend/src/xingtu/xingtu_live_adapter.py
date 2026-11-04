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
    CandidateDiagnostic,
    CollectorError,
    CreatorRef,
    ExecutionContext,
    FieldObservation,
    FieldStatus,
    FilterPlan,
    SearchPage,
    uid,
    utcnow,
)
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

    async def _expect_search(self, page: Page, action: Any) -> dict[str, Any]:
        try:
            async with page.expect_response(
                lambda r: SEARCH_PATH in r.url and r.request.method == "POST",
                timeout=self.timeout_seconds() * 1000,
            ) as info:
                await action()
            response = await info.value
        except PlaywrightTimeoutError as exc:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "LIVE_SEARCH_RESPONSE_TIMEOUT") from exc
        if response.status != 200:
            raise CollectorError("MODULE_COLLECTION_FAILED", "LIVE_SEARCH_HTTP")
        try:
            payload = await response.json()
        except Exception as exc:  # noqa: BLE001 - response schema is the contract
            raise CollectorError("PLATFORM_PAGE_CHANGED", "LIVE_SEARCH_SCHEMA") from exc
        return payload if isinstance(payload, dict) else {}

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

    async def prepare(self, plan: FilterPlan, cp: Any, ctx: ExecutionContext) -> bool:
        del ctx
        self.registry.capabilities.validate_plan(plan, live=self.live)
        keyword = next((str(item.value) for item in plan.filters if item.field == "keyword"), None)
        if not keyword:
            raise CollectorError("INVALID_FORM", "LIVE_KEYWORD_REQUIRED")
        self._search_keyword = keyword
        spec = self.registry.search
        session = self.registry.session
        assert spec and session
        if self.search_page is None:
            self.search_page = await self.browser.new_page()
        page = self.search_page
        page.set_default_timeout(self.timeout_seconds() * 1000)
        if cp.cursor is not None:
            # A retry after page 1 must not re-scan page 1: doing so would report next_checkpoint
            # "2" while the checkpoint is already "2" and the engine would reject a cursor loop.
            self.prepared_result = None
            if not page.url.startswith(spec.entry_url):
                await self._bootstrap_session(page, spec.entry_url, session.entry_url)
            await self.check_session(page)
            return True
        await self._bootstrap_session(page, spec.entry_url, session.entry_url)
        await self.check_session(page)
        # The live square pre-applies a platform quote condition.  Clear it so a keyword task is
        # not silently restricted by a condition the user never chose.
        clear = page.locator("button").filter(has_text="清空")
        if await clear.count() and await clear.first.is_visible():
            await clear.first.click()
            await asyncio.sleep(1.0)
        search_input = page.locator(SEARCH_INPUT).first
        await search_input.wait_for(state="visible", timeout=self.timeout_seconds() * 1000)
        await search_input.fill(keyword)
        payload = await self._expect_search(page, lambda: search_input.press("Enter"))
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
        await pager.scroll_into_view_if_needed()
        payload = await self._expect_search(page, lambda: pager.click())
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
