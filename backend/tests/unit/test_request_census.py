"""DIAG-01: the opt-in request census must be inert by default and honest when enabled."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from xingtu.request_census import (
    ENV_OUTPUT,
    RequestCensus,
    census_path_from_env,
    sanitized_target,
)


class FakeRequest:
    def __init__(self, url: str, *, method: str = "GET", resource_type: str = "xhr") -> None:
        self.url, self.method, self.resource_type = url, method, resource_type
        self.failure: str | None = None


class FakeResponse:
    def __init__(self, request: FakeRequest, status: int = 200) -> None:
        self.request, self.status = request, status


class FakeContext:
    """Records handler registration so default-off behaviour is provable."""

    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}

    def on(self, event: str, handler: object) -> None:
        self.handlers[event] = handler

    def remove_listener(self, event: str, handler: object) -> None:
        self.handlers.pop(event, None)


def read_lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_disabled_unless_env_names_a_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_OUTPUT, raising=False)
    assert census_path_from_env() is None
    monkeypatch.setenv(ENV_OUTPUT, "  ")
    assert census_path_from_env() is None
    monkeypatch.setenv(ENV_OUTPUT, "/tmp/diag-census.jsonl")
    assert census_path_from_env() == Path("/tmp/diag-census.jsonl")


def test_classification_is_structural_and_never_guessed() -> None:
    assert RequestCensus.classify("document", "www.xingtu.cn", "/ad/creator/market") == (
        "platform_document"
    )
    assert RequestCensus.classify("xhr", "www.xingtu.cn", "/gw/api/x") == "platform_api"
    assert RequestCensus.classify("image", "www.xingtu.cn", "/a.png") == "platform_asset"
    assert RequestCensus.classify("xhr", "tracker.example.com", "/t") == "third_party_api"
    assert RequestCensus.classify("document", "sso.oceanengine.com", "/login") == (
        "third_party_document"
    )
    assert RequestCensus.classify("image", "p3-star-fe-sign.byteimg.com", "/c.webp") == (
        "image_asset"
    )
    assert RequestCensus.classify("script", "static.example.com", "/a.js") == "static_asset"
    # Anything unnamed stays explicitly unrecognised rather than being guessed into a vendor.
    assert RequestCensus.classify("websocket", "unknown.example", "/ws") == (
        "unrecognised_third_party"
    )


def test_query_strings_are_never_recorded(tmp_path: Path) -> None:
    assert sanitized_target("https://www.xingtu.cn/gw/api/x?cursor=2&token=SECRET#frag") == (
        "www.xingtu.cn",
        "/gw/api/x",
    )
    path = tmp_path / "census.jsonl"
    census = RequestCensus(path, label="unit")
    context = FakeContext()
    census.attach(context)  # type: ignore[arg-type]
    request = FakeRequest("https://www.xingtu.cn/gw/api/x?cursor=2&token=SECRET")
    census._on_request(request)  # type: ignore[arg-type]
    census._on_response(FakeResponse(request, status=200))  # type: ignore[arg-type]
    census.close()

    raw = path.read_text()
    assert "SECRET" not in raw
    assert "cursor" not in raw
    records = read_lines(path)
    assert [r["kind"] for r in records if "kind" in r] == ["census_header", "census_footer"]
    body = [r for r in records if "kind" not in r]
    assert len(body) == 1
    assert body[0]["host"] == "www.xingtu.cn"
    assert body[0]["path"] == "/gw/api/x"
    assert body[0]["bucket"] == "platform_api"
    assert body[0]["status"] == 200
    assert body[0]["error"] is None


def test_same_url_shares_url_key_and_different_parameters_do_not(tmp_path: Path) -> None:
    path = tmp_path / "census.jsonl"
    census = RequestCensus(path, label="dup")
    context = FakeContext()
    census.attach(context)  # type: ignore[arg-type]
    first = FakeRequest("https://www.xingtu.cn/gw/api/x?cursor=2")
    second = FakeRequest("https://www.xingtu.cn/gw/api/x?cursor=2")
    other = FakeRequest("https://www.xingtu.cn/gw/api/x?cursor=3")
    for request in (first, second, other):
        census._on_request(request)  # type: ignore[arg-type]
        census._on_response(FakeResponse(request))  # type: ignore[arg-type]
    census.close()

    body = [r for r in read_lines(path) if "kind" not in r]
    keys = [r["url_key"] for r in body]
    assert keys[0] == keys[1], "identical URL must share a key so duplicates are detectable"
    assert keys[0] != keys[2], "a different parameter value must not look like a duplicate"


def test_failed_requests_are_recorded_with_their_reason(tmp_path: Path) -> None:
    path = tmp_path / "census.jsonl"
    census = RequestCensus(path, label="fail")
    context = FakeContext()
    census.attach(context)  # type: ignore[arg-type]
    request = FakeRequest("https://www.xingtu.cn/gw/api/x", resource_type="fetch")
    request.failure = "net::ERR_ABORTED"
    census._on_request(request)  # type: ignore[arg-type]
    census._on_request_failed(request)  # type: ignore[arg-type]
    census.close()

    body = [r for r in read_lines(path) if "kind" not in r]
    assert body[0]["error"] == "net::ERR_ABORTED"
    assert body[0]["status"] is None


def test_overflow_is_reported_rather_than_hidden(tmp_path: Path) -> None:
    path = tmp_path / "census.jsonl"
    census = RequestCensus(path, label="cap", max_records=3)
    context = FakeContext()
    census.attach(context)  # type: ignore[arg-type]
    for index in range(10):
        request = FakeRequest(f"https://www.xingtu.cn/gw/api/x?i={index}")
        census._on_request(request)  # type: ignore[arg-type]
        census._on_response(FakeResponse(request))  # type: ignore[arg-type]
    census.close()

    records = read_lines(path)
    footer = next(r for r in records if r.get("kind") == "census_footer")
    assert footer["records"] == 3
    assert footer["dropped"] == 7
    assert footer["truncated"] is True


def test_close_is_idempotent_and_flushes_pending(tmp_path: Path) -> None:
    path = tmp_path / "census.jsonl"
    census = RequestCensus(path, label="pending")
    context = FakeContext()
    census.attach(context)  # type: ignore[arg-type]
    census._on_request(FakeRequest("https://www.xingtu.cn/gw/api/never"))  # type: ignore[arg-type]
    census.close()
    census.close()

    body = [r for r in read_lines(path) if "kind" not in r]
    assert len(body) == 1, "an in-flight request must still appear in the census"
    assert body[0]["error"] == "NO_TERMINAL_EVENT"
    assert list(context.handlers) == [], "listeners must be released on close"
