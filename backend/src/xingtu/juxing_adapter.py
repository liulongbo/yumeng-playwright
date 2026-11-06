from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any

from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .adapter import BrowserAdapter, RowCoverSink
from .contracts import account_id_from_url, bind_account_to_url
from .domain import (
    CandidateDiagnostic,
    Checkpoint,
    CollectorError,
    CreatorRef,
    ExecutionContext,
    FieldObservation,
    FieldStatus,
    FilterPlan,
    ModuleObservation,
    NumberRange,
    NumericValue,
    SearchPage,
    StructuredValue,
    uid,
)
from .normalize import number

POST_JSON_JS = """
async (args) => {
  const response = await fetch(args.path, {
    method: "POST",
    credentials: "include",
    headers: {"content-type": "application/json"},
    body: JSON.stringify(args.body),
  });
  return {
    status: response.status,
    contentType: response.headers.get("content-type") || "",
    text: await response.text(),
  };
}
"""
_RAW_UNSET = object()


class KuaishouJuxingAdapter(BrowserAdapter):
    """Small, fail-closed Juxing video-creator adapter.

    The endpoints below are not treated as a public API.  They are registered page responses and
    are replayed only inside the authenticated Kuaishou page through its own Chrome session.  No
    cookie, header or token is read by Python.  Contract/version gates remain identical to Xingtu.
    """

    SEARCH_PATH = "/rest/web/star/list"
    DETAIL_PATHS = frozenset(
        {
            "/rest/web/star/match/starPage/baseInfo",
            "/rest/web/post/video/works/statistics/get",
            "/rest/web/post/video/representative/works/info/list",
            "/rest/web/star/listPortrait",
            "/rest/web/post/video/portrait/fans/fluctuation/get",
        }
    )
    PAGE_SIZE = 20

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.prepared_result = None

    async def _post_json(self, page: Page, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if path != self.SEARCH_PATH and path not in self.DETAIL_PATHS:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "UNREGISTERED_JUXING_REQUEST")
        if not page.url.startswith("https://k.kuaishou.com/"):
            raise CollectorError("PLATFORM_PAGE_CHANGED", "JUXING_PAGE_OUT_OF_SCOPE")
        await self.guard()
        result = await page.evaluate(POST_JSON_JS, {"path": path, "body": body})
        if not isinstance(result, dict):
            raise CollectorError("PLATFORM_PAGE_CHANGED", "JUXING_RESPONSE_UNREADABLE")
        if result.get("status") != 200 or "json" not in str(result.get("contentType", "")):
            raise CollectorError("MODULE_COLLECTION_FAILED", "JUXING_RESPONSE_FAILED")
        text = result.get("text")
        if not isinstance(text, str) or len(text.encode()) > (
            self.registry.response_body_max_bytes or 1
        ):
            raise CollectorError("PLATFORM_PAGE_CHANGED", "JUXING_RESPONSE_SIZE")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "JUXING_RESPONSE_SCHEMA") from exc
        if not isinstance(payload, dict) or str(payload.get("result")) != "1":
            raise CollectorError("MODULE_COLLECTION_FAILED", "JUXING_BUSINESS_RESPONSE_FAILED")
        return payload

    @staticmethod
    def _range_value(
        value: NumberRange, *, scale: Decimal = Decimal(1)
    ) -> tuple[int | None, int | None]:
        def convert(bound: Decimal | None) -> int | None:
            if bound is None:
                return None
            scaled = bound * scale
            if scaled != scaled.to_integral():
                raise CollectorError("INVALID_FORM", "JUXING_RANGE_PRECISION")
            return int(scaled)

        return convert(value.min), convert(value.max)

    def _capability(self, key: str) -> Any:
        for field in self.registry.capabilities.fields:
            if field.field == key:
                return field
        raise CollectorError("UNSUPPORTED_FILTER", key)

    def _content_tag(self, value: str) -> dict[str, Any]:
        field = self._capability("content_type")
        mapping = field.request_mapping.get(value)
        if not isinstance(mapping, dict):
            raise CollectorError("UNSUPPORTED_FILTER", "content_type")
        tag_id = mapping.get("id")
        sub_ids = mapping.get("sub_ids")
        if (
            isinstance(tag_id, bool)
            or not isinstance(tag_id, (str, int))
            or not isinstance(sub_ids, list)
            or any(isinstance(item, bool) or not isinstance(item, (str, int)) for item in sub_ids)
        ):
            raise CollectorError("PLATFORM_PAGE_CHANGED", "JUXING_CONTENT_MAPPING")
        return {
            "id": str(tag_id),
            "subIds": [str(item) for item in sub_ids],
            "selectFirstLevelId": bool(mapping.get("select_first_level_id", True)),
        }

    def _region_codes(self, value: Any) -> list[int]:
        field = self._capability("region")
        nodes = {node.value: node for node in field.region_tree}
        codes: list[int] = []
        for selection in value.selections:
            node = nodes.get(selection.province_code)
            if node is None:
                raise CollectorError("UNSUPPORTED_FILTER", "region")
            if selection.city is None:
                if not node.children:
                    raise CollectorError("UNSUPPORTED_FILTER", "region")
                for child in node.children:
                    try:
                        codes.append(int(child.value))
                    except (TypeError, ValueError) as exc:
                        raise CollectorError(
                            "PLATFORM_PAGE_CHANGED", "JUXING_REGION_MAPPING"
                        ) from exc
            else:
                child = next((item for item in node.children if item.label == selection.city), None)
                if child is None:
                    raise CollectorError("UNSUPPORTED_FILTER", "region")
                try:
                    codes.append(int(child.value))
                except (TypeError, ValueError) as exc:
                    raise CollectorError("PLATFORM_PAGE_CHANGED", "JUXING_REGION_MAPPING") from exc
        return list(dict.fromkeys(codes))

    def _quote_type(self, field_key: str) -> int:
        field = self._capability(field_key)
        price_type = field.request_mapping.get("price_type")
        if isinstance(price_type, bool) or not isinstance(price_type, (int, str)):
            raise CollectorError("PLATFORM_PAGE_CHANGED", "JUXING_QUOTE_MAPPING")
        try:
            return int(price_type)
        except (TypeError, ValueError) as exc:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "JUXING_QUOTE_MAPPING") from exc

    def _build_search_body(self, plan: FilterPlan, page_number: int) -> dict[str, Any]:
        body: dict[str, Any] = {
            "currentPage": page_number,
            "pageSize": self.PAGE_SIZE,
            "starOrderTag": 3,
            "starOrderType": 0,
            "taskType": 1,
            "marketingGoal": 1,
            "searchSourceType": 0,
            "viewerCityPercentage": [],
            "fansCityPercentage": [],
            "starTagIds": [],
            "pickList": [],
            "advertiserPickList": [],
            "pathSource": "no_filter_video",
        }
        keyword = False
        filtered = False
        quote_field: str | None = None
        for item in plan.filters:
            if item.field == "keyword" and isinstance(item.value, str):
                body["userName"] = item.value
                body["searchSourceType"] = 10
                keyword = True
            elif item.field == "content_type" and isinstance(item.value, list):
                body["contentTagIdList"] = [self._content_tag(value) for value in item.value]
                filtered = True
            elif item.field == "followers" and isinstance(item.value, NumberRange):
                minimum, maximum = self._range_value(item.value)
                if minimum is not None:
                    body["fansMinNum"] = minimum
                if maximum is not None:
                    body["fansMaxNum"] = maximum
                filtered = True
            elif item.field == "region" and hasattr(item.value, "selections"):
                body["cityCodeList"] = self._region_codes(item.value)
                filtered = True
            elif item.field in {
                "video_quote_1_20",
                "video_quote_21_60",
                "video_quote_60_plus",
            } and isinstance(item.value, NumberRange):
                if quote_field is not None:
                    raise CollectorError("INVALID_FORM", "JUXING_QUOTE_FILTERS_MUTUALLY_EXCLUSIVE")
                quote_field = item.field
                minimum, maximum = self._range_value(item.value, scale=Decimal(1000))
                body["priceType"] = self._quote_type(item.field)
                if minimum is not None:
                    body["starMinPrice"] = minimum
                if maximum is not None:
                    body["starMaxPrice"] = maximum
                filtered = True
            else:
                raise CollectorError("UNSUPPORTED_FILTER", item.field)
        body["pathSource"] = (
            "precise_content_search_video"
            if keyword and not filtered
            else "fuzzy_content_search_video"
            if filtered
            else "no_filter_video"
        )
        return body

    async def navigate(self, page: Page, url: str) -> None:
        """Navigate the juxing SPA without failing on a late DOMContentLoaded.

        The platform's hash-routed SPA occasionally finishes painting after the registered 30s
        operation budget while the protected search surface is already present.  Treat that as a
        late load, not a page-contract change: first check the registered ready surface, then retry
        with ``wait_until='commit'`` and the same ready contract.  Login/challenge/account checks
        remain in ``check_session`` and are never bypassed.
        """

        self.metric("navigations")
        search = self.registry.search
        assert search is not None
        timeout_ms = self.timeout_seconds() * 1000
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            return
        except PlaywrightTimeoutError:
            if page.url.startswith("https://k.kuaishou.com/"):
                try:
                    await self.wait_ready(page, search.ready, search.ready_hidden)
                    return
                except CollectorError as exc:
                    # Account selection is a legitimate ready maintenance page, not a
                    # navigation failure; preserve it for the worker's handoff.
                    if exc.code == "ACCOUNT_SELECTION_REQUIRED":
                        raise
            try:
                await page.goto(url, wait_until="commit", timeout=timeout_ms)
                await self.wait_ready(page, search.ready, search.ready_hidden)
                return
            except (PlaywrightTimeoutError, CollectorError) as exc:
                if isinstance(exc, CollectorError) and exc.code == "ACCOUNT_SELECTION_REQUIRED":
                    raise
                raise CollectorError("PLATFORM_PAGE_CHANGED", "JUXING_NAVIGATION_TIMEOUT") from exc

    async def prepare(self, plan: FilterPlan, cp: Checkpoint, ctx: ExecutionContext) -> bool:
        del ctx
        self.registry.capabilities.validate_plan(plan, live=self.live)
        if self.search_page is None:
            self.search_page = await self.browser.new_page()
        page = self.search_page
        page.set_default_timeout(self.timeout_seconds() * 1000)
        search = self.registry.search
        assert search is not None
        session = self.registry.session
        assert session is not None
        if (
            not page.url.startswith("https://k.kuaishou.com/")
            or account_id_from_url(page.url, session.account_url_parameter) != self.account
        ):
            await self.navigate(
                page,
                bind_account_to_url(
                    search.entry_url,
                    session.account_url_parameter,
                    self.account,
                ),
            )
        await self.check_session(page)
        if cp.cursor is not None:
            # A checkpoint that already advanced must keep its cursor: re-asserting the registered
            # search surface/session is enough, and the next search() request rebuilds the full
            # filter body for that page.  Returning True is what lets Engine resume instead of
            # rescanning page 1.
            if not isinstance(cp.cursor, str) or not cp.cursor.isdigit() or int(cp.cursor) < 2:
                return False
            max_verified = search.page_fetch_max_verified
            # After scanning the last verified page the engine stores `max_verified + 1` as the
            # next cursor while it still has that page's candidates to collect.  Resuming in that
            # state must work; the capability boundary itself belongs to search(), where the engine
            # converts SEARCH_CAPABILITY_LIMIT into a partial completion (engine.run's search
            # branch) instead of a hard task failure.  Only a cursor beyond that natural sentinel
            # is corrupt.
            if max_verified is not None and int(cp.cursor) > max_verified + 1:
                raise CollectorError("SEARCH_CAPABILITY_LIMIT", "JUXING_PAGE_LIMIT")
            return True
        self.prepared_result = await self._search(plan, cp, page_number=1)
        return True

    async def _search(self, plan: FilterPlan, cp: Checkpoint, *, page_number: int) -> SearchPage:
        assert self.search_page is not None
        operation = uid()
        body = self._build_search_body(plan, page_number)
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
            raise CollectorError("PLATFORM_PAGE_CHANGED", "JUXING_SEARCH_SCHEMA")
        if current != page_number:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "JUXING_SEARCH_PAGE_MISMATCH")
        exhausted = current * self.PAGE_SIZE >= total
        if not rows and not exhausted:
            # total says there is more while the page came back empty: this is a page-contract
            # anomaly, never evidence that the platform has no more creators.
            raise CollectorError("PLATFORM_PAGE_CHANGED", "JUXING_SEARCH_EMPTY_PAGE")
        candidates: list[CreatorRef] = []
        unidentified: list[CandidateDiagnostic] = []
        for position, row in enumerate(rows):
            source = f"{operation}:starList.{position}"
            if not isinstance(row, dict):
                unidentified.append(
                    CandidateDiagnostic(
                        reason="CANDIDATE_IDENTITY_UNREADABLE",
                        detail="starList row",
                        source_ref=source,
                        operation_id=operation,
                    )
                )
                continue
            user_id, star_id = row.get("userId"), row.get("starId")
            if (
                isinstance(user_id, bool)
                or not isinstance(user_id, (str, int))
                or isinstance(star_id, bool)
                or not isinstance(star_id, (str, int))
            ):
                unidentified.append(
                    CandidateDiagnostic(
                        reason="CANDIDATE_IDENTITY_UNREADABLE",
                        detail="userId/starId",
                        source_ref=source,
                        operation_id=operation,
                    )
                )
                continue
            homepage = f"https://k.kuaishou.com/#/promotion/star/{star_id}?openBy=user"
            candidates.append(
                CreatorRef(
                    platform="kuaishou_juxing",
                    platform_creator_id=str(user_id),
                    verified_homepage=homepage,
                    first_position=(current - 1) * self.PAGE_SIZE + position,
                    source_refs=[source],
                )
            )
        return SearchPage(
            candidates=candidates,
            current_checkpoint=cp.cursor,
            next_checkpoint=None if exhausted else str(current + 1),
            conditions_digest=plan.digest(),
            search_generation=cp.search_generation,
            operation_id=operation,
            exhausted=exhausted,
            exhaustion_evidence_refs=[f"{operation}:currentPage,total"] if exhausted else [],
            unidentified=unidentified,
        )

    async def search(self, plan: FilterPlan, cp: Checkpoint, ctx: ExecutionContext) -> SearchPage:
        del ctx
        if self.prepared_result is not None:
            result, self.prepared_result = self.prepared_result, None
            return result
        if self.search_page is None:
            raise CollectorError("SESSION_INDETERMINATE", "JUXING_SEARCH_PAGE_MISSING")
        spec = self.registry.search
        assert spec is not None
        cursor = cp.cursor
        if not isinstance(cursor, str) or not cursor.isdigit() or int(cursor) < 2:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "JUXING_SEARCH_CURSOR_INVALID")
        page_number = int(cursor)
        if spec.page_fetch_max_verified is not None and page_number > spec.page_fetch_max_verified:
            raise CollectorError("SEARCH_CAPABILITY_LIMIT", "JUXING_PAGE_LIMIT")
        await self.check_session(self.search_page)
        return await self._search(plan, cp, page_number=page_number)

    @staticmethod
    def _star_id(creator: CreatorRef) -> int:
        match = re.fullmatch(
            r"https://k\.kuaishou\.com/#/promotion/star/(\d+)\?openBy=user",
            creator.verified_homepage,
        )
        if not match:
            raise CollectorError("CREATOR_INVALID", "UNVERIFIED_JUXING_HOMEPAGE")
        return int(match.group(1))

    async def _ensure_search_page(self) -> Page:
        """Establish the bound video-square page for a plan-less targeted update.

        Normal collection always has a prepared search page.  A scheduled/manual update starts
        directly at the creator detail, but Juxing's detail requests are posted from a page inside
        the authenticated SPA, and the detail route itself omits the account markers.  Create and
        verify the registered video-square page exactly as a manual update would, without running
        search or P1.
        """
        if self.search_page is not None:
            return self.search_page
        search = self.registry.search
        session = self.registry.session
        assert search is not None and session is not None
        page = await self.browser.new_page()
        page.set_default_timeout(self.timeout_seconds() * 1000)
        try:
            await self.navigate(
                page,
                bind_account_to_url(
                    search.entry_url,
                    session.account_url_parameter,
                    self.account,
                ),
            )
        except Exception:
            await page.close()
            raise
        self.search_page = page
        return page

    @asynccontextmanager
    async def profile(self, creator: CreatorRef, ctx: ExecutionContext) -> AsyncIterator[None]:
        del ctx
        # Juxing's detail route omits the child-account/protected markers that exist on the
        # creator-square page. Prove the exact account on that still-live page before opening the
        # detail tab, then use the detail page only for creator identity and registered data.
        await self.check_session(await self._ensure_search_page())
        page = await self.browser.new_page()
        self.detail_page = page
        page.set_default_timeout(self.timeout_seconds() * 1000)
        try:
            self._star_id(creator)
            session = self.registry.session
            assert session is not None
            await self.navigate(
                page,
                bind_account_to_url(
                    creator.verified_homepage,
                    session.account_url_parameter,
                    self.account,
                ),
            )
            await self.verify_identity(page, creator)
            yield
        finally:
            self.detail_page = None
            await page.close()

    @staticmethod
    def _raw(value: Any) -> str:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return str(value)

    @staticmethod
    def _safe_introduction(value: Any) -> str | None:
        """Keep biography text while refusing to persist embedded contact details."""

        if not isinstance(value, str) or not value.strip():
            return None
        redacted = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[联系方式已脱敏]", value)
        redacted = re.sub(
            r"(?i)(微信|vx|v信|商务合作|合作联系)\s*[:：]?\s*[A-Za-z0-9_-]{4,}",
            r"\1：[联系方式已脱敏]",
            redacted,
        )
        return redacted.strip()

    def _field(
        self,
        *,
        key: str,
        value: Any,
        operation: str,
        ctx: ExecutionContext,
        path: str,
        raw: Any = _RAW_UNSET,
        unit: str | None = None,
        period: str | None = None,
    ) -> FieldObservation:
        if value is None or value == "" or value == []:
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
        return FieldObservation(
            field_key=key,
            value=value,
            raw_value=self._raw(value if raw is _RAW_UNSET else raw),
            status=FieldStatus.COLLECTED,
            operation_id=operation,
            session_version=ctx.session_version,
            unit=unit,
            period_label=period,
            source_kind="response",
            source_contract=self.registry.contract_version,
            path_ref=path,
        )

    @staticmethod
    def _numeric(value: Any, *, unit: str) -> NumericValue | None:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            return None
        try:
            return number(
                str(value), unit=unit, ratio_input="decimal" if unit == "ratio" else "percent"
            )
        except CollectorError:
            return None

    def _module(
        self,
        creator: CreatorRef,
        key: str,
        fields: list[FieldObservation],
        operation: str,
        *,
        period: str | None = None,
    ) -> ModuleObservation:
        return ModuleObservation(
            creator_ref=creator,
            module_key=key,
            source_period_label=period,
            fields=fields,
            expected_fields=self.module_fields[key],
            operation_id=operation,
            contract_version=self.registry.contract_version,
        )

    async def collect_module(
        self,
        key: str,
        creator: CreatorRef,
        ctx: ExecutionContext,
        row_covers: RowCoverSink | None = None,
    ) -> ModuleObservation:
        del row_covers
        if self.detail_page is None:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "JUXING_DETAIL_PAGE_MISSING")
        if self.search_page is None:
            raise CollectorError("SESSION_INDETERMINATE", "JUXING_SEARCH_PAGE_MISSING")
        page = self.detail_page
        await self.check_session(self.search_page)
        await self.verify_identity(page, creator)
        star_id = self._star_id(creator)
        operation = uid()
        if key == "basic":
            base = (
                await self._post_json(
                    page,
                    "/rest/web/star/match/starPage/baseInfo",
                    {"starId": star_id, "starType": 1},
                )
            ).get("data")
            growth = (
                await self._post_json(
                    page,
                    "/rest/web/post/video/portrait/fans/fluctuation/get",
                    {"starId": star_id, "timeDim": 30},
                )
            ).get("data")
            if not isinstance(base, dict) or not isinstance(growth, dict):
                raise CollectorError("MODULE_COLLECTION_FAILED", "JUXING_BASIC_SCHEMA")
            address = str(base.get("address") or "")
            province, _, city = address.partition("-")
            tags = base.get("contentTypeTag") or {}
            content_types = (
                [
                    value
                    for value in (tags.get("firstTagName"), tags.get("secondTagName"))
                    if isinstance(value, str) and value
                ]
                if isinstance(tags, dict)
                else []
            )
            content_forms: list[str] = []
            for form in base.get("contentFormTag") or []:
                if not isinstance(form, dict):
                    continue
                candidates: list[Any] = [form.get("firstTagName")]
                seconds = form.get("secondTagName")
                if isinstance(seconds, list):
                    candidates.extend(seconds)
                for value in candidates:
                    if isinstance(value, str) and value and value not in content_forms:
                        content_forms.append(value)
            identity = base.get("platformTargetIdentityInfo")
            identity_name = identity.get("name") if isinstance(identity, dict) else None
            settlement = base.get("publicSettlement")
            settlement_text = (
                "支持对公" if settlement is True else "不支持对公" if settlement is False else None
            )

            def yuan(raw: Any) -> int | None:
                if isinstance(raw, bool) or not isinstance(raw, int):
                    return None
                return raw // 1000 if raw % 1000 == 0 else None

            offers: list[Any] = []
            for item in base.get("priceShowInfo") or []:
                if not isinstance(item, dict) or item.get("businessLine") != 1:
                    continue
                raw_price = item.get("price")
                original_price = item.get("originalPrice")
                offers.append(
                    {
                        "price_type": item.get("priceType"),
                        "duration": item.get("priceTypeName"),
                        "platform_price_raw": raw_price,
                        "price_yuan": yuan(raw_price),
                        "original_price_raw": original_price,
                        "original_price_yuan": yuan(original_price),
                        "price_start_ms": item.get("priceStartTimeMs") or None,
                        "price_end_ms": item.get("priceEndTimeMs") or None,
                        "currency": "CNY",
                    }
                )
            introduction = self._safe_introduction(base.get("introduction"))
            values = {
                "platform_creator_id": str(base.get("userId"))
                if base.get("userId") is not None
                else None,
                "nickname": base.get("name"),
                "avatar_uri": base.get("headUrl"),
                "province": province or None,
                "city": city or None,
                "content_type_labels": content_types,
                "mcn_name": base.get("mcnName"),
                "introduction": introduction,
                "followers": self._numeric(base.get("fansNumber"), unit="count"),
                "monthly_follower_growth_count": self._numeric(
                    growth.get("fansIncreaseNum"), unit="count"
                ),
                "monthly_follower_growth_rate": self._numeric(
                    growth.get("fansIncreaseRate"), unit="ratio"
                ),
                "cooperation_offers": StructuredValue(data=offers) if offers else None,
                "gender": base.get("gender"),
                "profile_url": base.get("profileUrl"),
                "content_form_labels": content_forms,
                "platform_identity": identity_name,
                "style_detail": base.get("styleDetail"),
                "public_settlement": settlement_text,
            }
            paths = {
                "platform_creator_id": "data.userId",
                "nickname": "data.name",
                "avatar_uri": "data.headUrl",
                "province": "data.address",
                "city": "data.address",
                "content_type_labels": "data.contentTypeTag",
                "mcn_name": "data.mcnName",
                "introduction": "data.introduction",
                "followers": "data.fansNumber",
                "monthly_follower_growth_count": "data.fansIncreaseNum",
                "monthly_follower_growth_rate": "data.fansIncreaseRate",
                "cooperation_offers": "data.priceShowInfo",
                "gender": "data.gender",
                "profile_url": "data.profileUrl",
                "content_form_labels": "data.contentFormTag",
                "platform_identity": "data.platformTargetIdentityInfo",
                "style_detail": "data.styleDetail",
                "public_settlement": "data.publicSettlement",
            }
            basic_raw_values = {
                "platform_creator_id": base.get("userId"),
                "nickname": base.get("name"),
                "avatar_uri": base.get("headUrl"),
                "province": address,
                "city": address,
                "content_type_labels": tags,
                "mcn_name": base.get("mcnName"),
                # Contact details embedded in the biography are out of scope and never persisted,
                # including in raw_value.
                "introduction": introduction,
                "followers": base.get("fansNumber"),
                "monthly_follower_growth_count": growth.get("fansIncreaseNum"),
                "monthly_follower_growth_rate": growth.get("fansIncreaseRate"),
                "cooperation_offers": base.get("priceShowInfo"),
                "gender": base.get("gender"),
                "profile_url": base.get("profileUrl"),
                "content_form_labels": content_forms,
                "platform_identity": identity,
                "style_detail": base.get("styleDetail"),
                "public_settlement": settlement,
            }
            return self._module(
                creator,
                key,
                [
                    self._field(
                        key=name,
                        value=value,
                        operation=operation,
                        ctx=ctx,
                        path=paths[name],
                        raw=basic_raw_values[name],
                        unit="count"
                        if name in {"followers", "monthly_follower_growth_count"}
                        else "ratio"
                        if name.endswith("_rate")
                        else None,
                        period="近30天" if name.startswith("monthly_") else None,
                    )
                    for name, value in values.items()
                ],
                operation,
            )
        if key == "spread":
            data = (
                await self._post_json(
                    page,
                    "/rest/web/post/video/works/statistics/get",
                    {"nature": False, "starId": star_id, "timeDim": 30, "trafficDim": 7},
                )
            ).get("data")
            if not isinstance(data, dict):
                raise CollectorError("MODULE_COLLECTION_FAILED", "JUXING_SPREAD_SCHEMA")
            natural = data.get("natureStatistics") or {}
            business = data.get("businessStatistics") or {}
            if not isinstance(natural, dict) or not isinstance(business, dict):
                raise CollectorError("MODULE_COLLECTION_FAILED", "JUXING_SPREAD_SCHEMA")
            raw_values = {
                "play_median": (
                    natural.get("pplayMedian"),
                    "count",
                    "natureStatistics.pplayMedian",
                ),
                "expected_play": (
                    business.get("beplayCnt"),
                    "count",
                    "businessStatistics.beplayCnt",
                ),
                "expected_cpm": (
                    business.get("beCPM"),
                    "CNY_per_thousand_impressions",
                    "businessStatistics.beCPM",
                ),
                "interaction_rate": (
                    natural.get("pinteractionRate"),
                    "ratio",
                    "natureStatistics.pinteractionRate",
                ),
                "completion_rate": (
                    natural.get("pcompletePlayRate"),
                    "ratio",
                    "natureStatistics.pcompletePlayRate",
                ),
                "average_share": (
                    natural.get("pavgShareCntData"),
                    "count",
                    "natureStatistics.pavgShareCntData",
                ),
                "average_like": (
                    natural.get("pavgLikeCntData"),
                    "count",
                    "natureStatistics.pavgLikeCntData",
                ),
                "average_comment": (
                    natural.get("pavgCommentCntData"),
                    "count",
                    "natureStatistics.pavgCommentCntData",
                ),
                "video_count": (
                    natural.get("preleaseCnt"),
                    "count",
                    "natureStatistics.preleaseCnt",
                ),
                "average_duration_seconds": (
                    natural.get("pavgVideoDurationData"),
                    "seconds",
                    "natureStatistics.pavgVideoDurationData",
                ),
                "play_median_percentile": (
                    natural.get("pplayMedianPowerPercent"),
                    "ratio",
                    "natureStatistics.pplayMedianPowerPercent",
                ),
                "interaction_rate_percentile": (
                    natural.get("pinteractionRatePowerPercent"),
                    "ratio",
                    "natureStatistics.pinteractionRatePowerPercent",
                ),
                "completion_rate_percentile": (
                    natural.get("pcompletePlayRatePowerPercent"),
                    "ratio",
                    "natureStatistics.pcompletePlayRatePowerPercent",
                ),
                "expected_play_mom": (
                    business.get("beplayCntMOM"),
                    "ratio",
                    "businessStatistics.beplayCntMOM",
                ),
                "expected_cpm_mom": (
                    business.get("beCpmMOM"),
                    "ratio",
                    "businessStatistics.beCpmMOM",
                ),
                "recent_cpm": (
                    business.get("bcpm"),
                    "CNY_per_thousand_impressions",
                    "businessStatistics.bcpm",
                ),
                "recent_cpe": (
                    business.get("bcpe"),
                    "CNY_per_action",
                    "businessStatistics.bcpe",
                ),
                "conversion_click_rate": (
                    business.get("bavgConversionClickRate"),
                    "ratio",
                    "businessStatistics.bavgConversionClickRate",
                ),
                "visitor_num": (data.get("visitorNum"), "count", "visitorNum"),
                "deep_visitor_num": (data.get("deepVisitorNum"), "count", "deepVisitorNum"),
                "business_play_median": (
                    business.get("bplayMedian"),
                    "count",
                    "businessStatistics.bplayMedian",
                ),
                "business_play_median_percentile": (
                    business.get("bplayMedianPowerPercent"),
                    "ratio",
                    "businessStatistics.bplayMedianPowerPercent",
                ),
                "business_video_count": (
                    business.get("breleaseCnt"),
                    "count",
                    "businessStatistics.breleaseCnt",
                ),
                "business_completion_rate": (
                    business.get("bcompletePlayRate"),
                    "ratio",
                    "businessStatistics.bcompletePlayRate",
                ),
                "business_completion_rate_percentile": (
                    business.get("bcompletePlayRatePowerPercent"),
                    "ratio",
                    "businessStatistics.bcompletePlayRatePowerPercent",
                ),
                "business_interaction_rate": (
                    business.get("binteractionRate"),
                    "ratio",
                    "businessStatistics.binteractionRate",
                ),
                "business_interaction_rate_percentile": (
                    business.get("binteractionRatePowerPercent"),
                    "ratio",
                    "businessStatistics.binteractionRatePowerPercent",
                ),
                "business_average_duration_seconds": (
                    business.get("bavgVideoDurationData"),
                    "seconds",
                    "businessStatistics.bavgVideoDurationData",
                ),
                "business_average_like": (
                    business.get("bavgLikeCntData"),
                    "count",
                    "businessStatistics.bavgLikeCntData",
                ),
                "business_average_comment": (
                    business.get("bavgCommentCntData"),
                    "count",
                    "businessStatistics.bavgCommentCntData",
                ),
                "business_average_share": (
                    business.get("bavgShareCntData"),
                    "count",
                    "businessStatistics.bavgShareCntData",
                ),
            }
            fields = []
            for name, (raw, unit, path) in raw_values.items():
                numeric_unit = "ratio" if unit == "ratio" else "count"
                fields.append(
                    self._field(
                        key=name,
                        value=self._numeric(raw, unit=numeric_unit),
                        operation=operation,
                        ctx=ctx,
                        path=f"data.{path}",
                        raw=raw,
                        unit=unit,
                        period="近30天/流量范围7天",
                    )
                )
            return self._module(creator, key, fields, operation, period="近30天/流量范围7天")
        if key == "works":
            data = (
                await self._post_json(
                    page,
                    "/rest/web/post/video/representative/works/info/list",
                    {"starId": star_id, "nature": False},
                )
            ).get("data")
            rows = data.get("detailList") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise CollectorError("MODULE_COLLECTION_FAILED", "JUXING_WORKS_SCHEMA")
            works: list[Any] = [
                {
                    "platform_content_id": str(row.get("photoId")),
                    "title": row.get("caption"),
                    # The observed response exposes a media URL, not a verified public work page.
                    "media_url": row.get("webpUrl"),
                    "cover_url": row.get("coverUrl"),
                    "play_count": row.get("viewCnt"),
                    "like_count": row.get("likeCnt"),
                    "comment_count": row.get("commentCnt"),
                    "share_count": row.get("forwardCnt"),
                    "published_at_ms": row.get("releaseTimeMillis"),
                    "is_commercial": row.get("business"),
                    "rank_type": row.get("worksRankType"),
                    "product_name": row.get("productName"),
                    "contains_paid": row.get("containsPaid"),
                    "quality_hot": row.get("qualityHot"),
                    "quantity_hot": row.get("quantityHot"),
                    "quality_and_quantity_hot": row.get("qualityAndQuantityHot"),
                    "first_industry_name": row.get("firstIndustryName"),
                }
                for row in rows
                if isinstance(row, dict) and row.get("photoId") is not None
            ]
            field = self._field(
                key="works",
                value=StructuredValue(data=works) if works else None,
                operation=operation,
                ctx=ctx,
                path="data.detailList",
                raw=rows,
                period="页面最多近半年15个作品",
            )
            return self._module(creator, key, [field], operation, period="页面最多近半年15个作品")
        if key == "audience":
            data = (
                await self._post_json(
                    page,
                    "/rest/web/star/listPortrait",
                    {"starId": star_id, "starType": 1},
                )
            ).get("data")
            if not isinstance(data, dict):
                raise CollectorError("MODULE_COLLECTION_FAILED", "JUXING_AUDIENCE_SCHEMA")
            fields = [
                self._field(
                    key="fan_portrait",
                    value=StructuredValue(data=data["fansPortrait"])
                    if isinstance(data.get("fansPortrait"), dict)
                    else None,
                    operation=operation,
                    ctx=ctx,
                    path="data.fansPortrait",
                    raw=data.get("fansPortrait"),
                    period="近30天",
                ),
                self._field(
                    key="viewer_portrait",
                    value=StructuredValue(data=data["viewerPortrait"])
                    if isinstance(data.get("viewerPortrait"), dict)
                    else None,
                    operation=operation,
                    ctx=ctx,
                    path="data.viewerPortrait",
                    raw=data.get("viewerPortrait"),
                    period="近30天",
                ),
            ]
            return self._module(creator, key, fields, operation, period="近30天")
        raise CollectorError("PLATFORM_PAGE_CHANGED", "UNKNOWN_JUXING_MODULE")

    async def collect_featured_collections(
        self, creator: CreatorRef, cp: Checkpoint, ctx: ExecutionContext
    ) -> list[Any]:
        del creator, cp, ctx
        return []
