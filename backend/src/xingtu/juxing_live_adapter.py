"""Kuaishou Juxing live-square adapter.

Shares the verified session/browser/identity primitives with the video adapter, but uses the
live list endpoint (`taskType=4`, `pathSource=no_filter_live|search_live`) and the live creator
detail endpoints (`live-promotion/star/{starId}`).  The video adapter is not modified.
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from playwright.async_api import Page

from .adapter import RowCoverSink
from .contracts import bind_account_to_url
from .domain import (
    CollectorError,
    CreatorRef,
    ExecutionContext,
    FieldObservation,
    FieldStatus,
    FilterPlan,
    ModuleObservation,
    SearchPage,
    uid,
)
from .juxing_adapter import KuaishouJuxingAdapter
from .live_filters import juxing_live_filter_body, live_filter_fields
from .normalize import number

logger = logging.getLogger(__name__)


class KuaishouJuxingLiveAdapter(KuaishouJuxingAdapter):
    """Live-square adapter for one bound Juxing child account."""

    SEARCH_PATH = "/rest/web/star/list"
    LIVE_DETAIL_PATHS = frozenset(
        {
            "/rest/web/star/starProfile",
            "/rest/web/star/starWorksInfo",
            "/rest/web/commerce/live",
            "/rest/web/star/listPortrait",
            "/rest/web/starIndex/info",
            "/rest/web/starIndex/starRadarGraph",
            "/rest/web/starIndex/starTrendGraph",
            "/rest/web/evaluation/star/score",
            "/rest/web/evaluation/star/list",
        }
    )
    DETAIL_PATHS = KuaishouJuxingAdapter.DETAIL_PATHS | LIVE_DETAIL_PATHS
    PAGE_SIZE = 20

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._star_profile: dict[str, Any] = {}
        self._star_works: dict[str, Any] = {}
        self._commerce_live: dict[str, Any] = {}

    @staticmethod
    def _live_homepage(star_id: str, account: str) -> str:
        return (
            f"https://k.kuaishou.com/?__accountId__={account}"
            f"#/live-promotion/star/{star_id}?openBy=user"
        )

    @staticmethod
    def _live_star_id(creator: CreatorRef) -> int:
        match = re.search(r"#/live-promotion/star/(\d+)", creator.verified_homepage)
        if not match:
            raise CollectorError("CREATOR_INVALID", "UNVERIFIED_LIVE_HOMEPAGE")
        return int(match.group(1))

    def _build_live_search_body(self, plan: FilterPlan, page_number: int) -> dict[str, Any]:
        keyword = None
        for item in plan.filters:
            if item.field == "keyword" and isinstance(item.value, str):
                keyword = item.value
                break
        filtered = bool(live_filter_fields(plan))
        body: dict[str, Any] = {
            "currentPage": page_number,
            "pageSize": self.PAGE_SIZE,
            "starOrderTag": 3,
            "starOrderType": 0,
            "taskType": 4,
            "viewerCityPercentage": [],
            "fansCityPercentage": [],
            "starTagIds": [],
            "pickList": [],
            "advertiserPickList": [],
            "pathSource": (
                "has_filter_live" if filtered else "search_live" if keyword else "no_filter_live"
            ),
        }
        if keyword:
            body["userName"] = keyword
        # Every planned filter must be represented exactly once.  The helper raises instead of
        # silently dropping an unmapped field.
        body.update(juxing_live_filter_body(plan, self.registry.capabilities))
        return body

    async def _live_search(self, plan: FilterPlan, cp: Any, *, page_number: int) -> SearchPage:
        assert self.search_page is not None
        body = self._build_live_search_body(plan, page_number)
        applied = {
            key: value
            for key, value in body.items()
            if key
            not in {
                "currentPage",
                "pageSize",
                "starOrderTag",
                "starOrderType",
                "taskType",
                "viewerCityPercentage",
                "fansCityPercentage",
                "starTagIds",
                "pickList",
                "advertiserPickList",
                "pathSource",
                "userName",
            }
        }
        logger.info(
            "juxing live search root=%s page=%s filters=%s path_source=%s digest=%s applied=%s",
            getattr(self, "_root_task_id", None),
            page_number,
            live_filter_fields(plan),
            body.get("pathSource"),
            plan.digest()[:16],
            applied,
        )
        payload = await self._post_json(self.search_page, self.SEARCH_PATH, body)
        rows = payload.get("starList")
        total = payload.get("total")
        current = payload.get("currentPage")
        if (
            not isinstance(rows, list)
            or isinstance(total, bool)
            or not isinstance(total, int)
            or isinstance(current, bool)
            or not isinstance(current, int)
        ):
            raise CollectorError("PLATFORM_PAGE_CHANGED", "JUXING_LIVE_SEARCH_SCHEMA")
        if current != page_number:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "JUXING_LIVE_SEARCH_PAGE_MISMATCH")
        operation = uid()
        candidates: list[CreatorRef] = []
        for position, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            user_id, star_id = row.get("userId"), row.get("starId")
            if (
                isinstance(user_id, bool)
                or not isinstance(user_id, (str, int))
                or isinstance(star_id, bool)
                or not isinstance(star_id, (str, int))
            ):
                continue
            candidates.append(
                CreatorRef(
                    platform="kuaishou_juxing",
                    platform_creator_id=str(user_id),
                    verified_homepage=self._live_homepage(str(star_id), self.account),
                    first_position=(page_number - 1) * self.PAGE_SIZE + position,
                    source_refs=[f"{operation}:starList.{position}"],
                )
            )
        exhausted = current * self.PAGE_SIZE >= total
        if not rows and not exhausted:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "JUXING_LIVE_SEARCH_EMPTY_PAGE")
        return SearchPage(
            candidates=candidates,
            current_checkpoint=cp.cursor,
            next_checkpoint=None if exhausted else str(current + 1),
            conditions_digest=plan.digest(),
            search_generation=cp.search_generation,
            operation_id=operation,
            exhausted=exhausted,
            exhaustion_evidence_refs=[f"{operation}:currentPage,total"] if exhausted else [],
        )

    async def prepare(self, plan: FilterPlan, cp: Any, ctx: ExecutionContext) -> bool:
        self._root_task_id = ctx.root_task_id
        self.registry.capabilities.validate_plan(plan, live=self.live)
        if self.search_page is None:
            self.search_page = await self.browser.new_page()
        page = self.search_page
        page.set_default_timeout(self.timeout_seconds() * 1000)
        search = self.registry.search
        session = self.registry.session
        assert search and session
        if not page.url.startswith("https://k.kuaishou.com/"):
            await self.navigate(
                page,
                bind_account_to_url(search.entry_url, session.account_url_parameter, self.account),
            )
        await self.check_session(page)
        if cp.cursor is not None:
            if not isinstance(cp.cursor, str) or not cp.cursor.isdigit() or int(cp.cursor) < 2:
                return False
            max_verified = search.page_fetch_max_verified
            if max_verified is not None and int(cp.cursor) > max_verified + 1:
                raise CollectorError("SEARCH_CAPABILITY_LIMIT", "JUXING_LIVE_PAGE_LIMIT")
            return True
        self.prepared_result = await self._live_search(plan, cp, page_number=1)
        return True

    async def search(self, plan: FilterPlan, cp: Any, ctx: ExecutionContext) -> SearchPage:
        del ctx
        if self.prepared_result is not None:
            result, self.prepared_result = self.prepared_result, None
            return result
        if self.search_page is None:
            raise CollectorError("SESSION_INDETERMINATE", "JUXING_LIVE_SEARCH_PAGE_MISSING")
        cursor = cp.cursor
        if not isinstance(cursor, str) or not cursor.isdigit() or int(cursor) < 2:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "JUXING_LIVE_SEARCH_CURSOR_INVALID")
        page_number = int(cursor)
        spec = self.registry.search
        assert spec
        if spec.page_fetch_max_verified is not None and page_number > spec.page_fetch_max_verified:
            raise CollectorError("SEARCH_CAPABILITY_LIMIT", "JUXING_LIVE_PAGE_LIMIT")
        await self.check_session(self.search_page)
        return await self._live_search(plan, cp, page_number=page_number)

    @asynccontextmanager
    async def profile(self, creator: CreatorRef, ctx: ExecutionContext) -> AsyncIterator[None]:
        del ctx
        if self.search_page is None:
            # Manual updates have no search plan/prepare step, so the live adapter must establish
            # its own authenticated live-square page before opening the target detail.
            search = self.registry.search
            session = self.registry.session
            assert search and session
            self.search_page = await self.browser.new_page()
            await self.navigate(
                self.search_page,
                bind_account_to_url(search.entry_url, session.account_url_parameter, self.account),
            )
        await self.check_session(self.search_page)
        page = await self.browser.new_page()
        self.detail_page = page
        self._star_profile = {}
        self._star_works = {}
        self._commerce_live = {}
        page.set_default_timeout(self.timeout_seconds() * 1000)
        try:
            self._live_star_id(creator)
            session = self.registry.session
            assert session
            await self.navigate(
                page,
                bind_account_to_url(
                    creator.verified_homepage, session.account_url_parameter, self.account
                ),
            )
            # The SPA hydrates the ID node after the route change; verify_identity is bounded but
            # reading too early can still exhaust that bound on a slow live-detail render.
            await page.wait_for_function(
                "() => { const el=document.querySelector('div.id-and-location > div:first-child');"
                " return !!el && /^ID\\s*[:：]?\\s*\\d+$/.test((el.innerText||'').trim()); }",
                timeout=20_000,
            )
            await self.verify_identity(page, creator)
            yield
        finally:
            self.detail_page = None
            await page.close()

    async def _load_detail(self, page: Page, creator: CreatorRef) -> None:
        if self._star_profile:
            return
        star_id = self._live_star_id(creator)
        self._star_profile = await self._post_json(
            page, "/rest/web/star/starProfile", {"starId": str(star_id), "starType": 4}
        )
        try:
            self._star_works = await self._post_json(
                page, "/rest/web/star/starWorksInfo", {"starId": str(star_id), "starType": 4}
            )
        except CollectorError:
            self._star_works = {}
        try:
            self._commerce_live = await self._post_json(
                page, "/rest/web/commerce/live", {"starId": star_id, "duration": 7}
            )
        except CollectorError:
            self._commerce_live = {}

    @staticmethod
    def _profile_data(payload: dict[str, Any]) -> dict[str, Any]:
        data = payload.get("starProfile")
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _works_data(payload: dict[str, Any]) -> dict[str, Any]:
        data = payload.get("starWorksInfo")
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _commerce_data(payload: dict[str, Any]) -> dict[str, Any]:
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    def _obs(
        self,
        key: str,
        raw: Any,
        *,
        ctx: ExecutionContext,
        operation: str,
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
                source_kind="response",
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
        if unit is None and not isinstance(value, (str, list, dict)):
            value = str(value)
        return FieldObservation(
            field_key=key,
            value=value,
            raw_value=str(raw),
            status=FieldStatus.COLLECTED,
            operation_id=operation,
            session_version=ctx.session_version,
            unit=unit,
            period_label=period,
            source_kind="response",
            source_contract=self.registry.contract_version,
            path_ref=path,
        )

    def _basic_fields(
        self, creator: CreatorRef, ctx: ExecutionContext, operation: str
    ) -> list[FieldObservation]:
        profile = self._profile_data(self._star_profile)
        address = str(profile.get("address") or "")
        province, _, city = address.partition("-")
        values = {
            "platform_creator_id": creator.platform_creator_id,
            "platform_star_id": str(profile.get("starId") or "") or None,
            "nickname": profile.get("name"),
            "avatar_uri": profile.get("headUrl"),
            "gender": profile.get("gender"),
            "province": province or None,
            "city": city or None,
            "followers": profile.get("fansNumber"),
            "creator_type_label": profile.get("starTagStr"),
            "industry_labels": profile.get("industryTagStr"),
            "mcn_name": profile.get("govName"),
        }
        units = {
            "followers": "count",
        }
        fields: list[FieldObservation] = []
        for key in self.module_fields.get("basic", list(values)):
            fields.append(
                self._obs(
                    key,
                    values.get(key),
                    ctx=ctx,
                    operation=operation,
                    path=f"starProfile.{key}",
                    unit=units.get(key),
                )
            )
        return fields

    def _live_fields(self, ctx: ExecutionContext, operation: str) -> list[FieldObservation]:
        profile = self._profile_data(self._star_profile)
        works = self._works_data(self._star_works)
        raw_report = works.get("starWorkReport")
        report: dict[str, Any] = raw_report if isinstance(raw_report, dict) else {}
        commerce = self._commerce_data(self._commerce_live)
        raw_prices = profile.get("priceShowInfo")
        price_info: list[Any] = raw_prices if isinstance(raw_prices, list) else []
        price_by_type: dict[int, int] = {}
        for item in price_info:
            if (
                isinstance(item, dict)
                and item.get("businessLine") == 2
                and isinstance(item.get("price"), int)
            ):
                price_by_type[int(item.get("priceType", 0))] = item["price"] // 1000

        def zero_is_missing(value: Any) -> Any:
            return None if value in (0, "0", None, "") else value

        values: dict[str, tuple[Any, str | None, str]] = {
            "platform_star_id": (profile.get("starId"), None, "starProfile.starId"),
            "live.expect_viewer": (
                profile.get("livePlayCntExpectancy"),
                "count",
                "starProfile.livePlayCntExpectancy",
            ),
            "live.max_online": (profile.get("livePcuCnt"), "count", "starProfile.livePcuCnt"),
            "live.expect_cpm": (
                profile.get("liveCpmExpectancy"),
                None,
                "starProfile.liveCpmExpectancy",
            ),
            "live.weekly_sessions": (
                profile.get("liveWeeklyTimesCnt"),
                "count",
                "starProfile.liveWeeklyTimesCnt",
            ),
            "live.avg_people": (
                profile.get("liveAvgPeopleNum"),
                "count",
                "starProfile.liveAvgPeopleNum",
            ),
            "live.avg_like": (profile.get("liveAvgLikeCnt"), "count", "starProfile.liveAvgLikeCnt"),
            "live.week_release": (
                report.get("liveWeekRelease"),
                "count",
                "starWorksInfo.starWorkReport.liveWeekRelease",
            ),
            "live.interaction_rate": (
                report.get("liveInteractionRate"),
                None,
                "starWorksInfo.starWorkReport.liveInteractionRate",
            ),
            "live.quote_hour": (price_by_type.get(1), "yuan", "starProfile.priceShowInfo[type=1]"),
            "live.quote_day": (price_by_type.get(2), "yuan", "starProfile.priceShowInfo[type=2]"),
            "live.quote_goods": (price_by_type.get(3), "yuan", "starProfile.priceShowInfo[type=3]"),
            "live.commerce_sessions": (
                zero_is_missing(commerce.get("liveCnt")),
                "count",
                "commerce/live.data.liveCnt",
            ),
            "live.commerce_watch_median": (
                zero_is_missing(commerce.get("liveWatchCntMedian")),
                "count",
                "commerce/live.data.liveWatchCntMedian",
            ),
            "live.commerce_max_online_median": (
                zero_is_missing(commerce.get("liveMaxOnlineCntMedian")),
                "count",
                "commerce/live.data.liveMaxOnlineCntMedian",
            ),
            "live.commerce_goods": (
                zero_is_missing(commerce.get("goodsCnt")),
                "count",
                "commerce/live.data.goodsCnt",
            ),
        }
        fields: list[FieldObservation] = []
        for key in self.module_fields.get("live", list(values)):
            raw, unit, path = values.get(key, (None, None, f"live.{key}"))
            fields.append(
                self._obs(
                    key,
                    raw,
                    ctx=ctx,
                    operation=operation,
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
        row_covers: RowCoverSink | None = None,
    ) -> ModuleObservation:
        del row_covers
        if self.detail_page is None:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "JUXING_LIVE_DETAIL_PAGE_MISSING")
        await self._load_detail(self.detail_page, creator)
        operation = uid()
        if key == "basic":
            fields = self._basic_fields(creator, ctx, operation)
        elif key == "live":
            fields = self._live_fields(ctx, operation)
        else:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "UNKNOWN_JUXING_LIVE_MODULE")
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
