"""Kuaishou Juxing live-square adapter.

Shares the verified session/browser/identity primitives with the video adapter, but uses the
live list endpoint (`taskType=4`, `pathSource=no_filter_live|search_live`) and the live creator
detail endpoints (`live-promotion/star/{starId}`).  The video adapter is not modified.

The detail page loads all of its business tabs from registered XHR responses; we replay those
requests inside the authenticated page and build one module observation per business area.  A
failure in one optional area is reported as FAILED fields for that area and does not discard the
other areas.  No request is invented: every path below was observed on the live detail page.
"""

from __future__ import annotations

import json
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
    StructuredValue,
    uid,
)
from .juxing_adapter import KuaishouJuxingAdapter
from .juxing_live_fields import (
    REVIEW_PAGE_LIMIT,
    REVIEW_PAGE_SIZE,
    ParsedField,
    ParsedModule,
    failed_field,
    failed_fields,
    parse_audience,
    parse_basic,
    parse_commerce_period,
    parse_cooperation,
    parse_fans_trend,
    parse_hot_brands,
    parse_index,
    parse_live,
    parse_works,
)
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
            "/rest/web/star/queryVideoPlayCnt",
        }
    )
    DETAIL_PATHS = KuaishouJuxingAdapter.DETAIL_PATHS | LIVE_DETAIL_PATHS
    PAGE_SIZE = 20

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.prepared_result = None
        self._reset_detail_state()

    def _reset_detail_state(self) -> None:
        self._star_profile: dict[str, Any] = {}
        self._star_works: dict[str, Any] | None = None
        self._portrait_payload: dict[str, Any] | None = None
        self._radar_payload: dict[str, Any] | None = None
        self._trend_payload: dict[str, Any] | None = None
        self._score_payload: dict[str, Any] | None = None
        self._frequency_payload: dict[str, Any] | None = None
        self._commerce_payloads: dict[int, dict[str, Any]] = {}
        self._review_pages: list[dict[str, Any]] = []
        self._review_loaded = False
        self._review_complete = False
        self._profile_error: str | None = None
        self._works_error: str | None = None
        self._portrait_error: str | None = None
        self._radar_error: str | None = None
        self._trend_error: str | None = None
        self._score_error: str | None = None
        self._frequency_error: str | None = None
        self._commerce_errors: dict[int, str] = {}
        self._review_error: str | None = None

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
        self._reset_detail_state()
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

    # --------------------------------------------------------------------------------------
    # Registered detail requests (lazy, cached, per-module error retained)
    # --------------------------------------------------------------------------------------

    @staticmethod
    def _error_text(exc: CollectorError) -> str:
        return f"{exc.code}:{exc.reason}"

    async def _profile(self, page: Page, star_id: int) -> dict[str, Any]:
        if self._star_profile:
            return self._star_profile
        if self._profile_error:
            raise CollectorError("MODULE_COLLECTION_FAILED", self._profile_error)
        try:
            payload = await self._post_json(
                page, "/rest/web/star/starProfile", {"starId": str(star_id), "starType": 4}
            )
        except CollectorError as exc:
            self._profile_error = self._error_text(exc)
            raise
        data = payload.get("starProfile")
        if not isinstance(data, dict):
            self._profile_error = "JUXING_LIVE_PROFILE_SCHEMA"
            raise CollectorError("PLATFORM_PAGE_CHANGED", self._profile_error)
        self._star_profile = data
        return data

    async def _works(self, page: Page, star_id: int) -> dict[str, Any] | None:
        if self._star_works is not None:
            return self._star_works
        if self._works_error:
            return None
        try:
            payload = await self._post_json(
                page, "/rest/web/star/starWorksInfo", {"starId": str(star_id), "starType": 4}
            )
        except CollectorError as exc:
            self._works_error = self._error_text(exc)
            return None
        data = payload.get("starWorksInfo")
        if not isinstance(data, dict):
            self._works_error = "JUXING_LIVE_WORKS_SCHEMA"
            return None
        self._star_works = data
        return data

    async def _portrait(self, page: Page, star_id: int) -> dict[str, Any] | None:
        if self._portrait_payload is not None:
            return self._portrait_payload
        if self._portrait_error:
            return None
        try:
            payload = await self._post_json(
                page, "/rest/web/star/listPortrait", {"starId": str(star_id), "starType": 4}
            )
        except CollectorError as exc:
            self._portrait_error = self._error_text(exc)
            return None
        data = payload.get("data")
        if not isinstance(data, dict):
            self._portrait_error = "JUXING_LIVE_PORTRAIT_SCHEMA"
            return None
        self._portrait_payload = payload
        return payload

    async def _radar(self, page: Page, user_id: int) -> dict[str, Any] | None:
        if self._radar_payload is not None:
            return self._radar_payload
        if self._radar_error:
            return None
        try:
            payload = await self._post_json(
                page, "/rest/web/starIndex/starRadarGraph", {"userId": user_id, "starType": 4}
            )
        except CollectorError as exc:
            self._radar_error = self._error_text(exc)
            return None
        if (
            payload.get("starRadarGraphVO") is None
            and str(payload.get("errMsg") or "").strip() == "查询为空"
        ):
            # The platform returns HTTP 200 + errMsg=查询为空 + a null VO when it has no index
            # calculation for this creator.  That is an explicit empty observation, not a schema
            # failure; keeping the raw payload lets the parser emit NO_DATA for the index fields.
            self._radar_payload = payload
            return payload
        if not isinstance(payload.get("starRadarGraphVO"), dict):
            self._radar_error = "JUXING_LIVE_RADAR_SCHEMA"
            return None
        self._radar_payload = payload
        return payload

    async def _trend(self, page: Page, user_id: int) -> dict[str, Any] | None:
        if self._trend_payload is not None:
            return self._trend_payload
        if self._trend_error:
            return None
        try:
            payload = await self._post_json(
                page, "/rest/web/starIndex/starTrendGraph", {"userId": user_id, "starType": 4}
            )
        except CollectorError as exc:
            self._trend_error = self._error_text(exc)
            return None
        if (
            payload.get("starTrendGraphVO") is None
            and str(payload.get("errMsg") or "").strip() == "查询为空"
        ):
            self._trend_payload = payload
            return payload
        if not isinstance(payload.get("starTrendGraphVO"), dict):
            self._trend_error = "JUXING_LIVE_TREND_SCHEMA"
            return None
        self._trend_payload = payload
        return payload

    async def _score(self, page: Page, star_id: int) -> dict[str, Any] | None:
        if self._score_payload is not None:
            return self._score_payload
        if self._score_error:
            return None
        try:
            payload = await self._post_json(
                page,
                "/rest/web/evaluation/star/score",
                {"starId": star_id, "promotionType": 2},
            )
        except CollectorError as exc:
            self._score_error = self._error_text(exc)
            return None
        if not isinstance(payload.get("data"), dict):
            self._score_error = "JUXING_LIVE_EVALUATION_SCORE_SCHEMA"
            return None
        self._score_payload = payload
        return payload

    async def _frequency(self, page: Page, star_id: int) -> dict[str, Any] | None:
        if self._frequency_payload is not None:
            return self._frequency_payload
        if self._frequency_error:
            return None
        try:
            payload = await self._post_json(
                page, "/rest/web/star/queryVideoPlayCnt", {"starId": star_id, "type": 4}
            )
        except CollectorError as exc:
            self._frequency_error = self._error_text(exc)
            return None
        if not isinstance(payload.get("data"), dict):
            self._frequency_error = "JUXING_LIVE_FREQUENCY_SCHEMA"
            return None
        self._frequency_payload = payload
        return payload

    async def _commerce(self, page: Page, star_id: int, duration: int) -> dict[str, Any] | None:
        if duration in self._commerce_payloads:
            return self._commerce_payloads[duration]
        if duration in self._commerce_errors:
            return None
        try:
            payload = await self._post_json(
                page, "/rest/web/commerce/live", {"starId": star_id, "duration": duration}
            )
        except CollectorError as exc:
            self._commerce_errors[duration] = self._error_text(exc)
            return None
        data = payload.get("data")
        if not isinstance(data, dict):
            self._commerce_errors[duration] = "JUXING_LIVE_COMMERCE_SCHEMA"
            return None
        self._commerce_payloads[duration] = payload
        return payload

    async def _reviews(self, page: Page, star_id: int) -> None:
        if self._review_loaded:
            return
        self._review_loaded = True
        collected = 0
        for page_number in range(1, REVIEW_PAGE_LIMIT + 1):
            try:
                payload = await self._post_json(
                    page,
                    "/rest/web/evaluation/star/list",
                    {
                        "starId": star_id,
                        "promotionType": 2,
                        "page": page_number,
                        "size": REVIEW_PAGE_SIZE,
                    },
                )
            except CollectorError as exc:
                self._review_error = self._error_text(exc)
                return
            data = payload.get("data")
            rows = data.get("data") if isinstance(data, dict) else None
            if not isinstance(data, dict) or not isinstance(rows, list):
                self._review_error = "JUXING_LIVE_EVALUATION_LIST_SCHEMA"
                return
            self._review_pages.append(payload)
            total = data.get("total")
            total_value = total if isinstance(total, int) and not isinstance(total, bool) else None
            collected += len(rows)
            if total_value is not None and collected >= total_value:
                self._review_complete = True
                return
            if not rows:
                self._review_complete = total_value == 0
                return
            if len(rows) < REVIEW_PAGE_SIZE:
                self._review_complete = total_value is None or collected >= total_value
                return
        self._review_error = "REVIEW_PAGE_LIMIT"

    # --------------------------------------------------------------------------------------
    # Observation construction
    # --------------------------------------------------------------------------------------

    @staticmethod
    def _raw_text(raw: Any) -> str | None:
        if raw is None:
            return None
        if isinstance(raw, (dict, list)):
            return json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
        return str(raw)

    @staticmethod
    def _value_for(parsed: ParsedField, kind: str) -> Any:
        value = parsed.value
        if kind == "structured" or parsed.structured:
            return StructuredValue(data=value)
        if kind in {"number", "ratio"}:
            if parsed.unit in {"count", "ratio", "yuan"}:
                try:
                    return number(
                        str(value),
                        unit=parsed.unit,
                        ratio_input="decimal" if parsed.unit == "ratio" else "percent",
                    )
                except CollectorError:
                    return str(value)
            return str(value)
        if kind == "tags":
            return value if isinstance(value, list) else [str(value)]
        if kind == "text":
            return value if isinstance(value, str) else str(value)
        return value

    def _observation(
        self,
        parsed: ParsedField,
        ctx: ExecutionContext,
        operation: str,
        kind: str,
    ) -> FieldObservation:
        path = parsed.path or parsed.key
        if parsed.status == FieldStatus.COLLECTED and parsed.value is not None:
            return FieldObservation(
                field_key=parsed.key,
                value=self._value_for(parsed, kind),
                raw_value=self._raw_text(parsed.raw),
                status=FieldStatus.COLLECTED,
                operation_id=operation,
                session_version=ctx.session_version,
                unit=parsed.unit,
                period_label=parsed.period,
                source_kind="response",
                source_contract=self.registry.contract_version,
                path_ref=path,
                evidence_refs=[f"{operation}:{path}"],
            )
        if parsed.status == FieldStatus.FAILED:
            return FieldObservation(
                field_key=parsed.key,
                status=FieldStatus.FAILED,
                operation_id=operation,
                session_version=ctx.session_version,
                unit=parsed.unit,
                period_label=parsed.period,
                source_kind="response",
                source_contract=self.registry.contract_version,
                path_ref=path,
                evidence_refs=[f"{operation}:{path}:failed"],
                failure_reason=parsed.failure_reason or "JUXING_LIVE_FIELD_FAILED",
            )
        return FieldObservation(
            field_key=parsed.key,
            status=FieldStatus.NO_DATA,
            raw_value=self._raw_text(parsed.raw),
            operation_id=operation,
            session_version=ctx.session_version,
            unit=parsed.unit,
            period_label=parsed.period,
            source_kind="response",
            source_contract=self.registry.contract_version,
            path_ref=path,
            evidence_refs=[f"{operation}:{path}:empty"],
            fallback_reason=parsed.failure_reason,
        )

    def _module_observation(
        self,
        creator: CreatorRef,
        key: str,
        parsed: ParsedModule,
        ctx: ExecutionContext,
        operation: str,
    ) -> ModuleObservation:
        specs = {field.key: field for field in self.module_specs[key].fields}
        fields = [
            self._observation(
                parsed.fields.get(field_key)
                or failed_field(field_key, "JUXING_LIVE_FIELD_NOT_PARSED"),
                ctx,
                operation,
                specs[field_key].kind,
            )
            for field_key in self.module_fields[key]
        ]
        return ModuleObservation(
            creator_ref=creator,
            module_key=key,
            source_period_label=None,
            fields=fields,
            expected_fields=self.module_fields[key],
            coverage_gaps=parsed.coverage_gaps,
            operation_id=operation,
            contract_version=self.registry.contract_version,
        )

    def _all_failed(self, key: str, reason: str) -> ParsedModule:
        return failed_fields(self.module_fields[key], reason)

    # --------------------------------------------------------------------------------------
    # Module collection
    # --------------------------------------------------------------------------------------

    async def collect_module(
        self,
        key: str,
        creator: CreatorRef,
        ctx: ExecutionContext,
        row_covers: RowCoverSink | None = None,
    ) -> ModuleObservation:
        del row_covers
        page = self.detail_page
        if page is None:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "JUXING_LIVE_DETAIL_PAGE_MISSING")
        if key not in self.module_fields:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "UNKNOWN_JUXING_LIVE_MODULE")
        star_id = self._live_star_id(creator)
        operation = uid()

        if key == "basic":
            profile = await self._profile(page, star_id)
            parsed = parse_basic(creator.platform_creator_id, profile)
            return self._module_observation(creator, key, parsed, ctx, operation)

        if key == "live":
            try:
                profile = await self._profile(page, star_id)
            except CollectorError as exc:
                parsed = self._all_failed(key, self._error_text(exc))
                return self._module_observation(creator, key, parsed, ctx, operation)
            works = await self._works(page, star_id)
            commerce = await self._commerce(page, star_id, 7)
            parsed = parse_live(
                profile,
                works if self._works_error is None else None,
                commerce if 7 not in self._commerce_errors else None,
            )
            if self._works_error:
                for field_key in ("live.week_release", "live.interaction_rate"):
                    parsed.fields[field_key] = failed_field(field_key, self._works_error)
            if 7 in self._commerce_errors:
                for field_key in (
                    "live.commerce_sessions",
                    "live.commerce_watch_median",
                    "live.commerce_max_online_median",
                    "live.commerce_goods",
                ):
                    parsed.fields[field_key] = failed_field(field_key, self._commerce_errors[7])
            return self._module_observation(creator, key, parsed, ctx, operation)

        if key == "fans_trend":
            try:
                profile = await self._profile(page, star_id)
            except CollectorError as exc:
                parsed = self._all_failed(key, self._error_text(exc))
                return self._module_observation(creator, key, parsed, ctx, operation)
            return self._module_observation(creator, key, parse_fans_trend(profile), ctx, operation)

        if key == "index":
            try:
                profile = await self._profile(page, star_id)
            except CollectorError as exc:
                parsed = self._all_failed(key, self._error_text(exc))
                return self._module_observation(creator, key, parsed, ctx, operation)
            user_id = profile.get("userId")
            if isinstance(user_id, bool) or not isinstance(user_id, (int, str)):
                parsed = self._all_failed(key, "JUXING_LIVE_USER_ID_MISSING")
                return self._module_observation(creator, key, parsed, ctx, operation)
            radar = await self._radar(page, int(user_id))
            trend = await self._trend(page, int(user_id))
            parsed = parse_index(radar or {}, trend or {})
            if self._radar_error:
                for field_key in ("live.index_score", "live.index_dimensions"):
                    parsed.fields[field_key] = failed_field(field_key, self._radar_error)
            if self._trend_error:
                for field_key in (
                    "live.index_industry_rank",
                    "live.index_industry_percent",
                    "live.index_fans_rank",
                    "live.index_fans_percent",
                    "live.index_trend",
                ):
                    parsed.fields[field_key] = failed_field(field_key, self._trend_error)
            return self._module_observation(creator, key, parsed, ctx, operation)

        if key == "works":
            works = await self._works(page, star_id)
            frequency = await self._frequency(page, star_id)
            parsed = parse_works(
                works or {},
                frequency if self._frequency_error is None else None,
            )
            if self._works_error:
                for field_key in (
                    "live.personal_live_works",
                    "live.commercial_live_works",
                    "live.recent_live_works",
                ):
                    parsed.fields[field_key] = failed_field(field_key, self._works_error)
            if self._frequency_error:
                parsed.fields["live.live_frequency"] = failed_field(
                    "live.live_frequency", self._frequency_error
                )
            return self._module_observation(creator, key, parsed, ctx, operation)

        if key == "audience":
            portrait = await self._portrait(page, star_id)
            if portrait is None:
                parsed = self._all_failed(
                    key, self._portrait_error or "JUXING_LIVE_PORTRAIT_FAILED"
                )
                return self._module_observation(creator, key, parsed, ctx, operation)
            tags: list[str] = []
            try:
                profile = await self._profile(page, star_id)
                raw_tags = profile.get("viewerDeviceTag")
                if isinstance(raw_tags, list):
                    tags = [str(tag) for tag in raw_tags if isinstance(tag, str) and tag.strip()]
            except CollectorError:
                tags = []
            parsed = parse_audience(portrait, viewer_device_tags=tags)
            return self._module_observation(creator, key, parsed, ctx, operation)

        if key == "commerce":
            parsed = ParsedModule()
            for period in (7, 30, 90):
                payload = await self._commerce(page, star_id, period)
                field = parse_commerce_period(period, payload)
                if period in self._commerce_errors:
                    field = failed_field(field.key, self._commerce_errors[period])
                parsed.fields[field.key] = field
            try:
                profile = await self._profile(page, star_id)
                hot = parse_hot_brands(profile)
                parsed.fields.update(hot.fields)
            except CollectorError as exc:
                for field_key in ("live.hot_brands", "live.hot_categories"):
                    parsed.fields[field_key] = failed_field(field_key, self._error_text(exc))
            return self._module_observation(creator, key, parsed, ctx, operation)

        if key == "cooperation":
            score = await self._score(page, star_id)
            await self._reviews(page, star_id)
            parsed = parse_cooperation(
                str(star_id),
                score,
                self._review_pages,
                review_complete=self._review_complete,
                page_error=self._review_error,
            )
            if self._score_error:
                parsed.fields["live.evaluation_summary"] = failed_field(
                    "live.evaluation_summary", self._score_error
                )
            if self._review_error and not self._review_pages:
                for field_key in ("live.evaluation_total", "live.evaluation_reviews"):
                    parsed.fields[field_key] = failed_field(field_key, self._review_error)
            if self._review_error and "REVIEW_PAGINATION_INCOMPLETE" not in parsed.coverage_gaps:
                parsed.coverage_gaps.append("REVIEW_PAGINATION_INCOMPLETE")
            return self._module_observation(creator, key, parsed, ctx, operation)

        raise CollectorError("PLATFORM_PAGE_CHANGED", "UNKNOWN_JUXING_LIVE_MODULE")

    async def collect_featured_collections(self, *args: Any, **kwargs: Any) -> list[Any]:
        del args, kwargs
        return []
