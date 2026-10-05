from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from .domain import ERROR_CODES, Capabilities, CollectionType, CollectorError, Model


class LocatorSpec(Model):
    selector: str
    frame: str | None = None
    attribute: str | None = None
    # Form controls expose their content as a DOM property; the attribute is often absent.
    property: Literal["value"] | None = None
    value_map: dict[str, str] = Field(default_factory=dict)


class Action(Model):
    kind: Literal["click", "fill", "select", "scroll"]
    locator: LocatorSpec
    value: str | None = None


class RequestSpec(Model):
    key: str
    method: str
    host: str
    path: str
    request_match: dict[str, str]  # dotted JSON body or query keys -> literal / $binding
    response_match: dict[str, str]
    success_path: str
    success_value: str
    required: bool = True
    # Registered module-internal incremental loading: the same request may fire several times and
    # every matched response contributes to this key. Default false keeps ambiguity rejection.
    repeats: bool = False
    cursor_invalid_codes: list[str] = Field(default_factory=list)
    error_codes: dict[str, str] = Field(default_factory=dict)


class SourceSpec(Model):
    kind: Literal["response", "dom"]
    request_key: str | None = None
    path: str | None = None
    locator: LocatorSpec | None = None


class FieldSpec(Model):
    key: str
    name: str
    kind: Literal["text", "number", "ratio", "quote", "tags", "distribution"]
    source: SourceSpec
    fallback: SourceSpec | None = None
    fallback_on: list[Literal["MISSING_SOURCE", "MODULE_TIMEOUT"]] = Field(default_factory=list)
    compare_rounding: Literal["nearest"] | None = None
    unit: str | None = None
    currency: str | None = None
    cooperation_form: str | None = None
    dimension: str | None = None
    period_source: SourceSpec | None = None
    # A registered platform truncation marker; a value ending with it is kept and flagged.
    truncate_marker: str | None = None
    # Exact registered values, not missing selectors, establish absence.
    empty_values: list[str] = Field(default_factory=list)
    permission_values: list[str] = Field(default_factory=list)
    not_provided_values: list[str] = Field(default_factory=list)


class ModuleAbsenceSpec(Model):
    """Registered module-level absence evidence; a missing element never proves absence."""

    probe: SourceSpec
    empty_values: list[str] = Field(default_factory=list)
    permission_values: list[str] = Field(default_factory=list)
    not_provided_values: list[str] = Field(default_factory=list)


class ProfileModuleSpec(Model):
    key: str
    basic: bool = False
    # Entry page, tab/expand actions, readiness and per-module versions stay null/1 until verified.
    entry: str | None = None
    default_bindings: dict[str, str] = Field(default_factory=dict)
    actions: list[Action] = Field(default_factory=list)
    ready: LocatorSpec
    ready_hidden: list[LocatorSpec] = Field(default_factory=list)
    timeout_seconds: float | None = Field(default=None, gt=0)
    requests: list[RequestSpec] = Field(default_factory=list)
    fields: list[FieldSpec] = Field(min_length=1)
    period_source: SourceSpec | None = None
    absence: ModuleAbsenceSpec | None = None
    checkpoint_version: int = Field(default=1, ge=1)
    coverage_gaps: list[str] = Field(default_factory=list)


class CoverSpec(Model):
    """Registered cover download scope; the CDN allowlist is an explicit verified range."""

    field_key: str = "cover"
    allowed_hosts: list[str] = Field(min_length=1)
    allowed_content_types: list[str] = Field(min_length=1)
    max_bytes: int = Field(gt=0)
    timeout_seconds: float = Field(gt=0)
    max_redirects: int = Field(default=0, ge=0, le=3)


class FeaturedCollectionSpec(Model):
    """One of the two default featured modules (technical plan §7.2).

    Card fields read response paths relative to a card row or the index-th DOM node of the
    registered locator. ``cards_path`` is the only accepted work range: everything else in the
    same response is out of scope and is never collected.
    """

    key: CollectionType
    module_label: str
    entry: str | None = None
    default_bindings: dict[str, str] = Field(default_factory=dict)
    actions: list[Action] = Field(default_factory=list)
    ready: LocatorSpec
    ready_hidden: list[LocatorSpec] = Field(default_factory=list)
    timeout_seconds: float | None = Field(default=None, gt=0)
    requests: list[RequestSpec] = Field(default_factory=list)
    result_request_key: str
    cards_path: str
    # Card fields keyed "platform_content_id", "link" and "local_key" carry identity when
    # registered; identity is never inferred from titles or cover similarity.
    link_hosts: list[str] = Field(default_factory=list)
    default_period_path: str | None = None
    set_key_path: str | None = None
    load_complete_path: str
    load_complete_value: str
    card_fields: list[FieldSpec] = Field(min_length=1)
    cover: CoverSpec | None = None
    absence: ModuleAbsenceSpec | None = None
    checkpoint_version: int = Field(default=1, ge=1)
    coverage_gaps: list[str] = Field(default_factory=list)


class SearchSpec(Model):
    entry_url: str
    default_bindings: dict[str, str] = Field(default_factory=dict)
    reset_actions: list[Action]
    apply_actions: list[Action]
    next_actions: list[Action] = Field(default_factory=list)
    ready: LocatorSpec
    ready_hidden: list[LocatorSpec] = Field(default_factory=list)
    readback: dict[str, LocatorSpec]
    requests: list[RequestSpec]
    result_request_key: str
    candidates_path: str
    id_path: str
    # Exactly one of the two must be registered: a response path, or a verified URL template that
    # carries the platform creator id (some platforms return only the id in the search response).
    homepage_path: str | None = None
    homepage_template: str | None = None
    next_path: str
    exhausted_path: str
    exhausted_value: str
    pagination: Literal["cursor", "page", "load_more", "scroll"]
    next_page_mode: Literal["actions", "page_fetch"] = "actions"
    # A page-fetch contract is enabled only through the largest page proven with real evidence.
    page_fetch_max_verified: int | None = Field(default=None, ge=2)
    resume_supported: bool = False
    initial_cursor: str = ""
    # The platform sort is fixed by the contract; the plan may only use that one value.
    fixed_sort: bool = False
    # The verified contract covers the first result page only; advancing needs re-verification.
    single_page_only: bool = False
    # Plan value -> platform literal for bindings (e.g. keyword mode "content" -> "3").
    binding_values: dict[str, dict[str, str]] = Field(default_factory=dict)
    # Gaps inside this search contract that the coverage evidence must keep visible.
    coverage_gaps: list[str] = Field(default_factory=list)


class SessionSpec(Model):
    entry_url: str
    account: LocatorSpec
    protected_ready: LocatorSpec
    error_selectors: dict[str, LocatorSpec]
    identity: LocatorSpec

    @model_validator(mode="after")
    def known_errors(self) -> SessionSpec:
        if not set(self.error_selectors) <= ERROR_CODES:
            raise ValueError("unknown session error classification")
        return self


class PlatformRegistry(Model):
    schema_version: Literal["platform_registry.v1"] = "platform_registry.v1"
    contract_version: str
    adapter_version: str
    status: Literal["UNVERIFIED", "VERIFIED", "DISABLED"]
    sample_kind: Literal["synthetic", "live"]
    verified_at: str | None = None
    account_permission_type: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    capabilities: Capabilities
    allowed_hosts: list[str] = Field(default_factory=list)
    homepage_path_prefixes: list[str] = Field(default_factory=list)
    action_interval_seconds: float | None = Field(default=None, gt=0)
    operation_timeout_seconds: float | None = Field(default=None, gt=0)
    response_body_max_bytes: int | None = Field(default=None, gt=0)
    # Manual/browser log-in needs a longer bounded wait than a single page operation.
    session_boot_timeout_seconds: float = Field(default=120, gt=0)
    session: SessionSpec | None = None
    search: SearchSpec | None = None
    modules: list[ProfileModuleSpec] = Field(default_factory=list)
    # Empty means F06 was not registered for this run; a non-empty list must be exactly the two
    # default modules. An unverified registry keeps it empty.
    featured: list[FeaturedCollectionSpec] = Field(default_factory=list)
    direct_api_enabled: Literal[False] = False
    raw_har_trace_enabled: Literal[False] = False
    coverage_gaps: list[str] = Field(default_factory=list)

    def require_enabled(self, *, live: bool) -> None:
        if self.status != "VERIFIED" or not self.session or not self.search:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "UNVERIFIED_REGISTRY")
        if not all(
            (
                self.allowed_hosts,
                self.homepage_path_prefixes,
                self.action_interval_seconds,
                self.operation_timeout_seconds,
                self.response_body_max_bytes,
            )
        ):
            raise CollectorError("PLATFORM_PAGE_CHANGED", "INCOMPLETE_REGISTRY")
        if live and (
            self.sample_kind != "live"
            or not self.evidence_refs
            or not self.verified_at
            or not self.account_permission_type
        ):
            raise CollectorError("PLATFORM_PAGE_CHANGED", "LIVE_EVIDENCE_REQUIRED")
        keys = [m.key for m in self.modules]
        if (
            not self.modules
            or not self.modules[0].basic
            or any(m.basic for m in self.modules[1:])
            or len(set(keys)) != len(keys)
        ):
            raise CollectorError("PLATFORM_PAGE_CHANGED", "INVALID_MODULE_REGISTRY")
        if not {"platform_creator_id", "nickname"} <= {f.key for f in self.modules[0].fields}:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "MISSING_BASIC_IDENTITY_FIELDS")
        self._validate_references()

    def _validate_references(self) -> None:
        """A VERIFIED registry must be internally executable; unknown paths stay null."""
        search = self.search
        assert search
        session = self.session
        assert session
        if any(not host for host in self.allowed_hosts) or any(
            not prefix.startswith("/") for prefix in self.homepage_path_prefixes
        ):
            raise CollectorError("PLATFORM_PAGE_CHANGED", "INVALID_HOST_SCOPE")
        for url in (session.entry_url, search.entry_url):
            if not self._url_in_scope(url, homepage_required=False):
                raise CollectorError("PLATFORM_PAGE_CHANGED", "INVALID_ENTRY_URL")
        self._check_request_list(search.requests)
        if search.result_request_key not in {r.key for r in search.requests}:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "MISSING_RESULT_REQUEST")
        if (
            not all(
                (
                    search.candidates_path,
                    search.id_path,
                    search.next_path,
                    search.exhausted_path,
                )
            )
            or not search.readback
        ):
            raise CollectorError("PLATFORM_PAGE_CHANGED", "INCOMPLETE_SEARCH_CONTRACT")
        if bool(search.homepage_path) == bool(search.homepage_template):
            # A candidate homepage must come from exactly one verified source.
            raise CollectorError("PLATFORM_PAGE_CHANGED", "HOMEPAGE_CONTRACT_AMBIGUOUS")
        if search.homepage_template:
            if "{platform_creator_id}" not in search.homepage_template:
                raise CollectorError("PLATFORM_PAGE_CHANGED", "HOMEPAGE_TEMPLATE_PLACEHOLDER")
            sample = search.homepage_template.replace("{platform_creator_id}", "0")
            if not self._url_in_scope(sample, homepage_required=True):
                raise CollectorError("PLATFORM_PAGE_CHANGED", "INVALID_HOMEPAGE_TEMPLATE")
        if (
            search.next_page_mode == "actions"
            and not search.next_actions
            and not search.single_page_only
        ):
            # pagination names the verified advance mechanism; it needs a registered trigger.
            raise CollectorError("PLATFORM_PAGE_CHANGED", "MISSING_PAGINATION_ACTION")
        if search.next_page_mode == "page_fetch":
            result_request = next(
                request for request in search.requests if request.key == search.result_request_key
            )
            if (
                search.pagination != "page"
                or search.single_page_only
                or search.next_actions
                or not search.page_fetch_max_verified
                or result_request.method != "POST"
                or "$cursor" not in result_request.request_match.values()
                or result_request.host != urlsplit(search.entry_url).hostname
            ):
                raise CollectorError("PLATFORM_PAGE_CHANGED", "INVALID_PAGE_FETCH_CONTRACT")
        elif search.page_fetch_max_verified is not None:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "UNUSED_PAGE_FETCH_LIMIT")
        if search.single_page_only and not search.coverage_gaps:
            # A page-1-only contract must keep its pagination gap visible.
            raise CollectorError("PLATFORM_PAGE_CHANGED", "SINGLE_PAGE_COVERAGE_GAP_REQUIRED")
        for locator in (*search.readback.values(), search.ready, *search.ready_hidden):
            self._check_locator(locator)
        for module in self.modules:
            self._check_module(module)
        if self.featured:
            self._check_featured()

    def _check_featured(self) -> None:
        keys = [spec.key for spec in self.featured]
        if len(set(keys)) != len(keys):
            raise CollectorError("PLATFORM_PAGE_CHANGED", "DUPLICATE_FEATURED_COLLECTION")
        if set(keys) != set(CollectionType):
            # Only the two default modules may be collected; never an inferred Top X range.
            raise CollectorError("PLATFORM_PAGE_CHANGED", "MISSING_DEFAULT_FEATURED_COLLECTION")
        for spec in self.featured:
            self._check_locator(spec.ready)
            for locator in spec.ready_hidden:
                self._check_locator(locator)
            self._check_request_list(spec.requests)
            request_keys = {r.key for r in spec.requests}
            if spec.result_request_key not in request_keys:
                raise CollectorError("PLATFORM_PAGE_CHANGED", "MISSING_FEATURED_RESULT_REQUEST")
            if not spec.cards_path or not spec.load_complete_path or not spec.load_complete_value:
                raise CollectorError("PLATFORM_PAGE_CHANGED", "INCOMPLETE_FEATURED_CONTRACT")
            field_keys = [f.key for f in spec.card_fields]
            if len(set(field_keys)) != len(field_keys):
                raise CollectorError("PLATFORM_PAGE_CHANGED", "DUPLICATE_CARD_FIELD")
            for field in spec.card_fields:
                self._check_source(field.source, request_keys)
                if field.fallback:
                    if not field.fallback_on:
                        raise CollectorError("PLATFORM_PAGE_CHANGED", "FALLBACK_WITHOUT_TRIGGER")
                    self._check_source(field.fallback, request_keys)
                if field.kind == "number" and not field.unit:
                    raise CollectorError("PLATFORM_PAGE_CHANGED", "MISSING_FIELD_UNIT")
                if field.kind == "quote" and not (field.currency and field.cooperation_form):
                    raise CollectorError("PLATFORM_PAGE_CHANGED", "INCOMPLETE_QUOTE_CONTRACT")
                if field.kind == "distribution" and not field.dimension:
                    raise CollectorError("PLATFORM_PAGE_CHANGED", "MISSING_DIMENSION")
                status_values = [
                    field.empty_values,
                    field.permission_values,
                    field.not_provided_values,
                ]
                if sum(len(values) for values in status_values) != len(
                    {value for values in status_values for value in values}
                ):
                    raise CollectorError("PLATFORM_PAGE_CHANGED", "AMBIGUOUS_FIELD_ABSENCE")
                if field.period_source:
                    self._check_source(field.period_source, request_keys)
            if spec.link_hosts:
                # A displayed work link is a registered card field, validated against these hosts.
                links = [f for f in spec.card_fields if f.key == "link"]
                if len(links) != 1 or links[0].kind != "text":
                    raise CollectorError("PLATFORM_PAGE_CHANGED", "MISSING_LINK_FIELD")
            elif any(f.key == "link" for f in spec.card_fields):
                raise CollectorError("PLATFORM_PAGE_CHANGED", "MISSING_LINK_SCOPE")
            for host in spec.link_hosts:
                if not host or any(marker in host for marker in ("/", "*", ":")):
                    raise CollectorError("PLATFORM_PAGE_CHANGED", "MISSING_LINK_SCOPE")
            if spec.cover:
                if spec.cover.field_key not in set(field_keys):
                    raise CollectorError("PLATFORM_PAGE_CHANGED", "COVER_FIELD_NOT_DECLARED")
                for host in spec.cover.allowed_hosts:
                    if not host or any(marker in host for marker in ("/", "*", ":")):
                        raise CollectorError("PLATFORM_PAGE_CHANGED", "INVALID_COVER_SCOPE")
                if any(not item for item in spec.cover.allowed_content_types):
                    raise CollectorError("PLATFORM_PAGE_CHANGED", "INVALID_COVER_CONTENT_TYPE")
            if spec.absence:
                values = [
                    spec.absence.empty_values,
                    spec.absence.permission_values,
                    spec.absence.not_provided_values,
                ]
                if not any(values) or sum(len(v) for v in values) != len(
                    {x for v in values for x in v}
                ):
                    raise CollectorError("PLATFORM_PAGE_CHANGED", "AMBIGUOUS_MODULE_ABSENCE")
                self._check_source(spec.absence.probe, request_keys)
            if spec.entry:
                parsed_entry = urlsplit(spec.entry)
                if parsed_entry.scheme or parsed_entry.netloc:
                    if not self._url_in_scope(spec.entry, homepage_required=False):
                        raise CollectorError("PLATFORM_PAGE_CHANGED", "INVALID_MODULE_ENTRY")
                elif not spec.entry.startswith("/") or spec.entry.startswith("//"):
                    raise CollectorError("PLATFORM_PAGE_CHANGED", "INVALID_MODULE_ENTRY")
                # §7.1: a default featured module is a tab of the verified creator homepage;
                # an entry that leaves the homepage path range could be a full work list.
                entry_path = parsed_entry.path
                if not any(entry_path.startswith(prefix) for prefix in self.homepage_path_prefixes):
                    raise CollectorError("PLATFORM_PAGE_CHANGED", "FEATURED_ENTRY_OUTSIDE_HOMEPAGE")

    def _check_module(self, module: ProfileModuleSpec) -> None:
        if module.basic and module.entry:
            # The basic module is entered through the verified homepage, never a separate path.
            raise CollectorError("PLATFORM_PAGE_CHANGED", "BASIC_MODULE_ENTRY_UNSUPPORTED")
        self._check_locator(module.ready)
        for locator in module.ready_hidden:
            self._check_locator(locator)
        self._check_request_list(module.requests)
        request_keys = {r.key for r in module.requests}
        field_keys = [f.key for f in module.fields]
        if len(set(field_keys)) != len(field_keys):
            raise CollectorError("PLATFORM_PAGE_CHANGED", "DUPLICATE_MODULE_FIELD")
        for field in module.fields:
            self._check_source(field.source, request_keys)
            if field.fallback:
                # An unusable fallback must fail at publish time, not silently at runtime.
                if not field.fallback_on:
                    raise CollectorError("PLATFORM_PAGE_CHANGED", "FALLBACK_WITHOUT_TRIGGER")
                self._check_source(field.fallback, request_keys)
            if field.kind == "number" and not field.unit:
                raise CollectorError("PLATFORM_PAGE_CHANGED", "MISSING_FIELD_UNIT")
            if field.kind == "quote" and not (field.currency and field.cooperation_form):
                raise CollectorError("PLATFORM_PAGE_CHANGED", "INCOMPLETE_QUOTE_CONTRACT")
            if field.kind == "distribution" and not field.dimension:
                raise CollectorError("PLATFORM_PAGE_CHANGED", "MISSING_DIMENSION")
            status_values = [
                field.empty_values,
                field.permission_values,
                field.not_provided_values,
            ]
            if sum(len(values) for values in status_values) != len(
                {value for values in status_values for value in values}
            ):
                raise CollectorError("PLATFORM_PAGE_CHANGED", "AMBIGUOUS_FIELD_ABSENCE")
            if field.period_source:
                self._check_source(field.period_source, request_keys)
        if module.period_source:
            self._check_source(module.period_source, request_keys)
        if module.absence:
            values = [
                module.absence.empty_values,
                module.absence.permission_values,
                module.absence.not_provided_values,
            ]
            if not any(values) or sum(len(v) for v in values) != len(
                {x for v in values for x in v}
            ):
                raise CollectorError("PLATFORM_PAGE_CHANGED", "AMBIGUOUS_MODULE_ABSENCE")
            self._check_source(module.absence.probe, request_keys)
        if module.entry:
            parsed_entry = urlsplit(module.entry)
            if parsed_entry.scheme or parsed_entry.netloc:
                if not self._url_in_scope(module.entry, homepage_required=False):
                    raise CollectorError("PLATFORM_PAGE_CHANGED", "INVALID_MODULE_ENTRY")
            elif not module.entry.startswith("/") or module.entry.startswith("//"):
                # Relative entries resolve against the creator homepage and are re-checked there.
                raise CollectorError("PLATFORM_PAGE_CHANGED", "INVALID_MODULE_ENTRY")

    def _check_request_list(self, requests: list[RequestSpec]) -> None:
        keys = [r.key for r in requests]
        if len(set(keys)) != len(keys):
            raise CollectorError("PLATFORM_PAGE_CHANGED", "DUPLICATE_REQUEST_KEY")
        for request in requests:
            if (
                not request.method
                or not request.host
                or not request.path
                or not request.success_path
                or request.host not in self.allowed_hosts
            ):
                raise CollectorError("PLATFORM_PAGE_CHANGED", "INVALID_REQUEST_CONTRACT")
            if not set(request.error_codes.values()) <= ERROR_CODES:
                raise CollectorError("PLATFORM_PAGE_CHANGED", "UNKNOWN_ERROR_CODE")

    def _check_source(self, source: SourceSpec, request_keys: set[str]) -> None:
        if source.kind == "dom":
            if not source.locator:
                raise CollectorError("PLATFORM_PAGE_CHANGED", "MISSING_DOM_CONTRACT")
            self._check_locator(source.locator)
            return
        if not source.request_key or not source.path:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "MISSING_RESPONSE_CONTRACT")
        if source.request_key not in request_keys:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "UNDECLARED_SOURCE_REQUEST")

    @staticmethod
    def _check_locator(locator: LocatorSpec) -> None:
        if not locator.selector:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "EMPTY_LOCATOR")

    def _url_in_scope(self, url: str, *, homepage_required: bool) -> bool:
        parsed = urlsplit(url)
        return bool(
            parsed.scheme == "https"
            and parsed.hostname in self.allowed_hosts
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
            and (
                not homepage_required
                or any(parsed.path.startswith(prefix) for prefix in self.homepage_path_prefixes)
            )
        )

    def validate_platform_url(self, url: str) -> None:
        """Entry and module-tab URLs must stay inside the verified platform host scope."""
        if not self._url_in_scope(url, homepage_required=False):
            raise CollectorError("PLATFORM_PAGE_CHANGED", "UNVERIFIED_ENTRY_URL")

    def validate_homepage(self, url: str) -> None:
        if not self._url_in_scope(url, homepage_required=True):
            raise CollectorError("CREATOR_INVALID", "UNVERIFIED_HOMEPAGE")
