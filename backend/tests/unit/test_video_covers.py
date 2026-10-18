"""CD-08: the creation works list exchanges an opaque cover key for its observed signed URL.

The contract test asserts the *registered* shape; this module asserts the parsing behaviour,
which is where a wrong join would silently hand the UI another work's image.
"""

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from xingtu.adapter import BrowserAdapter, RowCoverSource
from xingtu.contracts import PlatformRegistry

REGISTRY = PlatformRegistry.model_validate_json(
    Path("contracts/douyin_xingtu.verified.json").read_text()
)
CREATION = next(module for module in REGISTRY.modules if module.key == "creation")


class _Sink:
    def __init__(self) -> None:
        self.received: list[RowCoverSource] = []

    async def __call__(self, row: RowCoverSource) -> None:
        self.received.append(row)


class _Page:
    """A page stub that records replay URLs and answers with a signed envelope for that URI.

    The real endpoint echoes the requested `uri` back in `img.uri`; `echo_override` simulates the
    (dangerous) case where it answers with a different object instead.
    """

    def __init__(self, *, echo_override: str | None = None, status: int = 200) -> None:
        self.urls: list[str] = []
        self.echo_override = echo_override
        self.status = status

    async def evaluate(self, _script: str, args: dict[str, Any]) -> dict[str, Any]:
        url = args["url"]
        self.urls.append(url)
        query = dict(parse_qsl(urlsplit(url).query))
        uri = self.echo_override or query.get("uri", "")
        return {
            "status": self.status,
            "contentType": "application/json",
            "text": json.dumps(_signed(uri)),
        }


class _Engine:
    """The row-cover pass only reads `registry`, but it calls the real replay helper.

    Binding `BrowserAdapter.replay_row_cover_sign` onto this stub keeps the tested code path exactly
    the production one instead of re-implementing it in the test.
    """

    registry = REGISTRY
    replay_row_cover_sign = BrowserAdapter.replay_row_cover_sign


def _engine() -> Any:
    return _Engine()


def _signed(uri: str) -> dict[str, Any]:
    return {
        "base_resp": {"status_code": 0},
        "img": {"uri": uri},
        "mainURL": f"https://p3-star-fe-sign.byteimg.com/{uri}~tplv-x-image.webp?sig=1",
    }


def _data(rows: list[dict[str, Any]], *, signs: list[Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "show_items": {"latest_item_info": rows},
    }
    if signs is not None:
        payload["cover_signs"] = signs
    return payload


ROWS = [
    {"item_id": "1", "item_cover": "tos-cn-i-0813c001/aaa"},
    {"item_id": "2", "item_cover": "tos-cn-i-0813c001/bbb"},
    {"item_id": "3", "item_cover": ""},
    {"item_id": "4"},
]


def test_only_observed_signed_urls_are_emitted_and_rows_are_positionally_anchored():
    """Row 1's key was already signed by the page; row 0 is replayed for its own key only."""
    sink = _Sink()
    page = _Page()
    data = _data(ROWS, signs=[_signed("tos-cn-i-0813c001/bbb")])
    gaps = asyncio.run(
        BrowserAdapter.emit_row_covers(_engine(), page, CREATION, data, {}, {}, sink)
    )
    assert [(row.field_key, row.position, row.source_key) for row in sink.received] == [
        ("recent_video_performance", 0, "tos-cn-i-0813c001/aaa"),
        ("recent_video_performance", 1, "tos-cn-i-0813c001/bbb"),
    ]
    assert gaps == []
    # Exactly one replay, and it asked for the row that had no observed signature.
    assert len(page.urls) == 1
    assert "uri=tos-cn-i-0813c001%2Faaa" in page.urls[0]


def test_missing_sign_response_is_replayed_from_the_registered_query_defaults():
    sink = _Sink()
    page = _Page()
    gaps = asyncio.run(
        BrowserAdapter.emit_row_covers(_engine(), page, CREATION, _data(ROWS), {}, {}, sink)
    )
    assert [row.source_key for row in sink.received] == [
        "tos-cn-i-0813c001/aaa",
        "tos-cn-i-0813c001/bbb",
    ]
    assert gaps == []
    # `format=webp` is load-bearing: without it the platform returns a .jpeg outside the
    # registered image/webp scope. The row URI (not the whole response) is the only substitution.
    assert len(page.urls) == 2
    assert all("format=webp" in url for url in page.urls)
    assert all("durationTS=86400" in url for url in page.urls)
    assert any("uri=tos-cn-i-0813c001%2Faaa" in url for url in page.urls)
    assert any("uri=tos-cn-i-0813c001%2Fbbb" in url for url in page.urls)


def test_a_row_without_a_cover_key_is_silence_not_a_substitute():
    sink = _Sink()
    page = _Page()
    asyncio.run(
        BrowserAdapter.emit_row_covers(_engine(), page, CREATION, _data(ROWS), {}, {}, sink)
    )
    # Rows 2 (empty key) and 3 (no key) are never signed and never borrow another row's image.
    assert [row.position for row in sink.received] == [0, 1]
    assert len(page.urls) == 2


def test_a_sign_response_that_echoes_a_different_uri_is_rejected():
    """A mismatched echo would attach another work's image; it must be dropped, never shown."""
    sink = _Sink()
    page = _Page(echo_override="tos-cn-i-0813c001/zzz")
    gaps = asyncio.run(
        BrowserAdapter.emit_row_covers(_engine(), page, CREATION, _data(ROWS), {}, {}, sink)
    )
    assert sink.received == []
    assert "cover_sign_missing" in gaps


def test_a_failed_sign_lookup_is_a_coverage_gap_not_a_cover():
    sink = _Sink()
    page = _Page(status=403)
    gaps = asyncio.run(
        BrowserAdapter.emit_row_covers(_engine(), page, CREATION, _data(ROWS), {}, {}, sink)
    )
    assert sink.received == []
    assert "cover_sign_missing" in gaps


def test_no_sink_means_no_work_and_no_coverage_gap():
    assert (
        asyncio.run(
            BrowserAdapter.emit_row_covers(_engine(), _Page(), CREATION, _data(ROWS), {}, {}, None)
        )
        == []
    )
