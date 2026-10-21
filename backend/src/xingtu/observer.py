from __future__ import annotations

import asyncio
import copy
import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, Self
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import Page, Request, Response

from .contracts import AttributeFilterEntry, AttributeFilterMatchSpec, RequestSpec
from .domain import CollectorError


@dataclass
class RequestDiagnostic:
    """Bounded, de-identified facts about one rejected response.

    A schema rejection must be actionable: which registered request was rejected, with what HTTP
    status and content type, and the platform's own business code. Response bodies, URLs, query
    values, headers and page text are never kept.
    """

    request_key: str
    http_status: int | None = None
    content_type_kind: str | None = None
    business_code: str | None = None
    business_path: str | None = None
    root_keys: list[str] = None  # type: ignore[assignment]
    lookup_error: str | None = None

    def __post_init__(self) -> None:
        if self.root_keys is None:
            self.root_keys = []

    def as_evidence(self) -> dict[str, object]:
        return {
            "request_key": self.request_key,
            "http_status": self.http_status,
            "content_type_kind": self.content_type_kind,
            "business_code": self.business_code,
            "business_path": self.business_path,
            "root_keys": list(self.root_keys),
            "lookup_error": self.lookup_error,
        }


def content_type_kind(headers: dict[str, str]) -> str:
    """Classify a content type without keeping the raw header value."""

    value = (headers or {}).get("content-type", "").lower()
    for marker in ("json", "html", "text", "javascript", "image", "octet-stream"):
        if marker in value:
            return marker
    return "other" if value else "missing"


@dataclass
class ReplayRequest:
    """One matched same-origin JSON request kept in memory for verified page advancement."""

    url: str
    method: str
    body: dict[str, Any]
    headers: dict[str, str]


def replace_path(payload: dict[str, Any], path: str, value: str) -> None:
    parts = path.split(".")
    current: Any = payload
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "PAGINATION_REQUEST_PATH_MISSING")
        current = current[part]
    if not isinstance(current, dict) or parts[-1] not in current:
        raise CollectorError("PLATFORM_PAGE_CHANGED", "PAGINATION_REQUEST_PATH_MISSING")
    original = current[parts[-1]]
    current[parts[-1]] = int(value) if isinstance(original, int) and value.isdigit() else value


def replay_headers(headers: dict[str, str]) -> dict[str, str]:
    """Headers a same-origin Fetch may replay; values never leave process memory or logs."""
    forbidden = {
        "accept-encoding",
        "connection",
        "content-length",
        "cookie",
        "host",
        "origin",
        "referer",
        "user-agent",
    }
    return {
        key: value
        for key, value in headers.items()
        if key not in forbidden and not key.startswith(":") and not key.startswith("sec-")
    }


def lookup(data: Any, path: str) -> Any:
    for part in path.split("."):
        if isinstance(data, dict):
            data = data.get(part)
        elif isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        else:
            return None
    return data


def text_value(value: Any) -> str:
    if isinstance(value, (dict, list, bool)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def resolve(value: str, bindings: dict[str, str]) -> str:
    if not value.startswith("$"):
        return value
    if value[1:] not in bindings:
        raise CollectorError("PLATFORM_PAGE_CHANGED", "MISSING_BINDING")
    return bindings[value[1:]]


def attribute_filter_signature(value: Any) -> tuple[str, str | None, str] | None:
    if not isinstance(value, dict) or not isinstance(value.get("field"), dict):
        return None
    field = value["field"]
    name = field.get("field_name")
    raw = value.get("field_value")
    if not isinstance(name, str) or raw is None:
        return None
    rel_id = field.get("rel_id", value.get("rel_id"))
    if rel_id is not None:
        rel_id = str(rel_id)
    return name, rel_id, text_value(raw)


def attribute_filters_match(
    payload: Any,
    spec: AttributeFilterMatchSpec,
    expected: list[AttributeFilterEntry] | None,
) -> bool:
    if expected is None:
        return False
    values = lookup(payload, spec.path)
    # Xingtu omits the field (JSON null) when no business filter is active.  That is the same
    # multiset as an empty array, but only when the plan also expects no entries.
    if values is None:
        values = []
    if not isinstance(values, list):
        return False
    actual_signatures = [attribute_filter_signature(value) for value in values]
    if any(value is None for value in actual_signatures):
        return False
    actual = Counter(value for value in actual_signatures if value is not None)

    def consume(item: AttributeFilterEntry) -> bool:
        candidates: list[tuple[str, str | None, str]]
        if item.rel_id is not None:
            candidates = [(item.field_name, item.rel_id, item.field_value)]
        else:
            # rel_id is an optional discriminator.  When the registry does not publish it, match
            # by field/value while retaining multiset cardinality and rejecting every residue.
            candidates = sorted(
                signature
                for signature, count in actual.items()
                if count and signature[0] == item.field_name and signature[2] == item.field_value
            )
        if not candidates or actual[candidates[0]] <= 0:
            return False
        actual[candidates[0]] -= 1
        if actual[candidates[0]] == 0:
            del actual[candidates[0]]
        return True

    # Static fields are allowed, not required.  Consume one occurrence when present; an extra
    # occurrence remains residue and is rejected below.
    for item in spec.allowed_static:
        consume(item)
    if any(not consume(item) for item in expected):
        return False
    return not actual


class ResponseCollector:
    """One operation/page/session; reject ambiguity instead of choosing latest response."""

    def __init__(
        self,
        page: Page,
        specs: list[RequestSpec],
        bindings: dict[str, str],
        timeout: float,
        max_bytes: int,
        *,
        metrics: dict[str, int] | None = None,
        attribute_filters: list[AttributeFilterEntry] | None = None,
    ):
        self.page, self.specs, self.bindings = page, specs, bindings
        self.timeout, self.max_bytes = timeout, max_bytes
        self.requests: dict[Request, RequestSpec] = {}
        self.seen: set[str] = set()
        self.results: dict[str, Any] = {}
        self.failures: dict[str, str] = {}
        self.replays: dict[str, ReplayRequest] = {}
        self.global_error: CollectorError | None = None
        # Diagnostics for the response that produced ``global_error``; cleared for a clean run.
        self.failure_diagnostics: dict[str, RequestDiagnostic] = {}
        self.pending: set[asyncio.Task[None]] = set()
        self.changed = asyncio.Event()
        self.closed = False
        self.metrics = metrics if metrics is not None else {}
        self.attribute_filters = attribute_filters
        # Retain exact callbacks for remove_listener.
        self.request_callback = self.on_request
        self.response_callback = self.on_response

    async def __aenter__(self) -> Self:
        self.page.on("request", self.request_callback)
        self.page.on("response", self.response_callback)
        return self

    async def __aexit__(self, *_: object) -> None:
        self.closed = True
        self.page.remove_listener("request", self.request_callback)
        self.page.remove_listener("response", self.response_callback)
        for task in self.pending:
            task.cancel()
        await asyncio.gather(*self.pending, return_exceptions=True)
        self.requests.clear()

    def on_request(self, request: Request) -> None:
        if self.closed:
            return
        try:
            if request.frame.page is not self.page:
                return
            parsed = urlsplit(request.url)
            for spec in self.specs:
                if (
                    request.method != spec.method
                    or parsed.hostname != spec.host
                    or parsed.path != spec.path
                ):
                    continue
                params: Any = {
                    k: v[0] if len(v) == 1 else v
                    for k, v in parse_qs(parsed.query, keep_blank_values=True).items()
                }
                if request.post_data:
                    params = request.post_data_json
                if not all(
                    text_value(lookup(params, k)) == resolve(v, self.bindings)
                    for k, v in spec.request_match.items()
                ):
                    continue
                if spec.attribute_filter_match and not attribute_filters_match(
                    params, spec.attribute_filter_match, self.attribute_filters
                ):
                    self.failures[spec.key] = "RESPONSE_UNCORRELATED"
                    self.metrics["attribute_filter_mismatches"] = (
                        self.metrics.get("attribute_filter_mismatches", 0) + 1
                    )
                    continue
                if spec.key in self.seen and not spec.repeats:
                    self.failures[spec.key] = "RESPONSE_UNCORRELATED"
                    self.metrics["duplicate_requests"] = (
                        self.metrics.get("duplicate_requests", 0) + 1
                    )
                self.seen.add(spec.key)
                if request not in self.requests:
                    self.metrics["requests"] = self.metrics.get("requests", 0) + 1
                self.requests[request] = spec
                if isinstance(params, dict):
                    self.replays[spec.key] = ReplayRequest(
                        url=request.url,
                        method=request.method,
                        body=copy.deepcopy(params),
                        headers=replay_headers(request.headers),
                    )
        except (ValueError, json.JSONDecodeError):
            self.global_error = CollectorError("PLATFORM_PAGE_CHANGED", "REQUEST_SCHEMA_MISMATCH")
        self.changed.set()

    def on_response(self, response: Response) -> None:
        if self.closed or response.request not in self.requests:
            return
        self.metrics["responses"] = self.metrics.get("responses", 0) + 1
        task = asyncio.create_task(self.read_response(response, self.requests[response.request]))
        self.pending.add(task)
        task.add_done_callback(self._response_task_done)

    def _response_task_done(self, task: asyncio.Task[None]) -> None:
        """Wake readers after the pending set transitions, avoiding a lost-notify race."""
        self.pending.discard(task)
        self.changed.set()

    def _record_diagnostic(
        self, exc: CollectorError, diagnostic: RequestDiagnostic
    ) -> CollectorError:
        """Attach the request diagnostic to the error and keep it for evidence."""

        self.failure_diagnostics[diagnostic.request_key] = diagnostic
        diagnostics = getattr(exc, "diagnostics", None)
        if diagnostics is None:
            try:
                exc.diagnostics = [diagnostic]
            except (AttributeError, ValueError):  # pragma: no cover - plain exceptions
                pass
        else:
            diagnostics.append(diagnostic)
        return exc

    async def read_response(self, response: Response, spec: RequestSpec) -> None:
        data: Any = None
        try:
            headers = response.headers
            # A gateway/edge/server error is transient transport noise, not an unregistered
            # platform contract change. Classify it as a module-level failure so the engine keeps
            # the successful modules and the task can continue/retry instead of terminating the
            # whole collection on an HTML 502/503/504 body.
            if response.status in {408, 500, 502, 503, 504}:
                raise self._record_diagnostic(
                    CollectorError("MODULE_COLLECTION_FAILED", "PLATFORM_HTTP_5XX"),
                    RequestDiagnostic(
                        request_key=spec.key,
                        http_status=response.status,
                        content_type_kind=content_type_kind(headers),
                    ),
                )
            if "json" not in headers.get("content-type", "").lower():
                raise self._record_diagnostic(
                    CollectorError("PLATFORM_PAGE_CHANGED", "RESPONSE_CONTENT_TYPE"),
                    RequestDiagnostic(
                        request_key=spec.key,
                        http_status=response.status,
                        content_type_kind=content_type_kind(headers),
                    ),
                )
            length = headers.get("content-length")
            if length and int(length) > self.max_bytes:
                raise CollectorError("MODULE_COLLECTION_FAILED", "RESPONSE_TOO_LARGE")
            body = await response.body()
            if len(body) > self.max_bytes:
                raise CollectorError("MODULE_COLLECTION_FAILED", "RESPONSE_TOO_LARGE")
            data = json.loads(body)
            business_code = (
                text_value(lookup(data, spec.success_path)) if spec.success_path else None
            )
            diagnostic = RequestDiagnostic(
                request_key=spec.key,
                http_status=response.status,
                content_type_kind=content_type_kind(headers),
                business_code=business_code,
                business_path=spec.success_path,
                root_keys=sorted(str(key) for key in data)[:32] if isinstance(data, dict) else [],
            )
            if business_code is not None and business_code in spec.cursor_invalid_codes:
                raise self._record_diagnostic(
                    CollectorError("PLATFORM_PAGE_CHANGED", "SEARCH_CURSOR_INVALID"), diagnostic
                )
            if business_code is not None and business_code in spec.error_codes:
                raise self._record_diagnostic(
                    CollectorError(spec.error_codes[business_code], "REGISTERED_BUSINESS_ERROR"),
                    diagnostic,
                )
            if response.status != 200 or (
                spec.success_path and business_code != spec.success_value
            ):
                raise self._record_diagnostic(
                    CollectorError("PLATFORM_PAGE_CHANGED", "RESPONSE_SCHEMA_MISMATCH"), diagnostic
                )
            if not all(
                text_value(lookup(data, k)) == resolve(v, self.bindings)
                for k, v in spec.response_match.items()
            ):
                self.failures[spec.key] = "RESPONSE_UNCORRELATED"
            elif spec.repeats and spec.repeat_result_mode == "all":
                # Module-internal incremental loading: keep every correlated response body.
                self.results.setdefault(spec.key, []).append(data)
            elif spec.repeats and spec.repeat_result_mode == "latest":
                # The registry may opt into latest only after proving that each occurrence is a
                # complete snapshot for the same bound creator/module operation.
                self.results[spec.key] = data
            else:
                self.results[spec.key] = data
        except CollectorError as exc:
            if exc.code == "MODULE_COLLECTION_FAILED":
                self.failures[spec.key] = exc.reason
            else:
                self.global_error = exc
        except (ValueError, TypeError) as exc:
            # A malformed body is a rejected response, not an unhandled defect; name the request.
            diagnostic = RequestDiagnostic(
                request_key=spec.key,
                http_status=response.status,
                content_type_kind=content_type_kind(response.headers),
                root_keys=sorted(str(key) for key in data)[:32] if isinstance(data, dict) else [],
                lookup_error=type(exc).__name__,
            )
            self.global_error = self._record_diagnostic(
                CollectorError("PLATFORM_PAGE_CHANGED", "RESPONSE_SCHEMA_MISMATCH"), diagnostic
            )
        except Exception:
            # Browser transport failures are failed reads, never an empty result.
            self.failures[spec.key] = "RESPONSE_READ_FAILED"
        finally:
            self.changed.set()

    async def read(self) -> tuple[dict[str, Any], dict[str, str]]:
        deadline = asyncio.get_running_loop().time() + self.timeout
        while True:
            if self.global_error:
                raise self.global_error
            settled = set(self.results) | set(self.failures)
            # Optional responses enrich a result but do not hold an operation open after the
            # caller's bounded settle window. Any response already in flight is still drained.
            if all(s.key in settled for s in self.specs if s.required) and not self.pending:
                break
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            self.changed.clear()
            try:
                await asyncio.wait_for(self.changed.wait(), remaining)
            except TimeoutError:
                break
        if self.global_error:
            raise self.global_error
        for spec in self.specs:
            if spec.key not in self.results and spec.key not in self.failures:
                self.failures[spec.key] = "MODULE_TIMEOUT"
        for key in self.failures:
            self.results.pop(key, None)
        return self.results, self.failures
