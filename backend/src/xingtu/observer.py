from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import dataclass
from typing import Any, Self
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import Page, Request, Response

from .contracts import RequestSpec
from .domain import CollectorError


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
    ):
        self.page, self.specs, self.bindings = page, specs, bindings
        self.timeout, self.max_bytes = timeout, max_bytes
        self.requests: dict[Request, RequestSpec] = {}
        self.seen: set[str] = set()
        self.results: dict[str, Any] = {}
        self.failures: dict[str, str] = {}
        self.replays: dict[str, ReplayRequest] = {}
        self.global_error: CollectorError | None = None
        self.pending: set[asyncio.Task[None]] = set()
        self.changed = asyncio.Event()
        self.closed = False
        self.metrics = metrics if metrics is not None else {}
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
                if spec.key in self.seen and not spec.repeats:
                    self.failures[spec.key] = "RESPONSE_UNCORRELATED"
                self.seen.add(spec.key)
                if request not in self.requests:
                    self.metrics["requests"] = self.metrics.get("requests", 0) + 1
                self.requests[request] = spec
                if request.post_data and isinstance(params, dict):
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
        task.add_done_callback(self.pending.discard)

    async def read_response(self, response: Response, spec: RequestSpec) -> None:
        try:
            headers = response.headers
            if "json" not in headers.get("content-type", "").lower():
                raise CollectorError("PLATFORM_PAGE_CHANGED", "RESPONSE_CONTENT_TYPE")
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
            if business_code is not None and business_code in spec.cursor_invalid_codes:
                raise CollectorError("PLATFORM_PAGE_CHANGED", "SEARCH_CURSOR_INVALID")
            if business_code is not None and business_code in spec.error_codes:
                raise CollectorError(spec.error_codes[business_code], "REGISTERED_BUSINESS_ERROR")
            if response.status != 200 or (
                spec.success_path and business_code != spec.success_value
            ):
                raise CollectorError("PLATFORM_PAGE_CHANGED", "RESPONSE_SCHEMA_MISMATCH")
            if not all(
                text_value(lookup(data, k)) == resolve(v, self.bindings)
                for k, v in spec.response_match.items()
            ):
                self.failures[spec.key] = "RESPONSE_UNCORRELATED"
            elif spec.repeats:
                # Module-internal incremental loading: keep every correlated response body.
                self.results.setdefault(spec.key, []).append(data)
            else:
                self.results[spec.key] = data
        except CollectorError as exc:
            if exc.code == "MODULE_COLLECTION_FAILED":
                self.failures[spec.key] = exc.reason
            else:
                self.global_error = exc
        except (ValueError, TypeError):
            self.global_error = CollectorError("PLATFORM_PAGE_CHANGED", "RESPONSE_SCHEMA_MISMATCH")
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
            if all(s.key in settled for s in self.specs) and not self.pending:
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
