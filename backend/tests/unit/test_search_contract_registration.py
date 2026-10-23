"""Registration rules added for the real Xingtu search contract (2026-09-27).

Pure unit tests: no browser, no platform traffic, no database.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError
from xingtu.adapter import map_bindings, resolve_homepage
from xingtu.contracts import PlatformRegistry, SearchSpec
from xingtu.domain import CollectorError

CONTRACT = "synthetic-v1"


def search(**overrides):
    payload = {
        "entry_url": "https://synthetic.invalid/market",
        "reset_actions": [],
        "apply_actions": [],
        "next_actions": [{"kind": "click", "locator": {"selector": "#next"}}],
        "ready": {"selector": "#ready"},
        "readback": {"keyword": {"selector": "#kw", "attribute": "value"}},
        "requests": [
            {
                "key": "list",
                "method": "POST",
                "host": "synthetic.invalid",
                "path": "/api/search",
                "request_match": {"keyword": "$keyword"},
                "response_match": {},
                "success_path": "code",
                "success_value": "0",
            }
        ],
        "result_request_key": "list",
        "candidates_path": "authors",
        "id_path": "star_id",
        "homepage_path": "homepage",
        "next_path": "pagination.page",
        "exhausted_path": "pagination.has_more",
        "exhausted_value": "false",
        "pagination": "page",
    }
    return {**payload, **overrides}


def registry(search_spec):
    return PlatformRegistry.model_validate(
        {
            "contract_version": CONTRACT,
            "adapter_version": CONTRACT,
            "status": "VERIFIED",
            "sample_kind": "synthetic",
            "capabilities": {
                "version": CONTRACT,
                "status": "VERIFIED",
                "sample_kind": "synthetic",
                "fields": [{"field": "keyword", "operators": ["eq"], "keyword_mode": "content"}],
                "sorts": ["score"],
                "combinations": [["keyword"]],
            },
            "allowed_hosts": ["synthetic.invalid"],
            "homepage_path_prefixes": ["/creator/"],
            "action_interval_seconds": 0.001,
            "operation_timeout_seconds": 1,
            "response_body_max_bytes": 4096,
            "session": {
                "entry_url": "https://synthetic.invalid/login",
                "account": {"selector": "#account"},
                "protected_ready": {"selector": "#ready"},
                "error_selectors": {},
                "identity": {"selector": "#identity"},
            },
            "search": search_spec,
            "modules": [
                {
                    "key": "basic",
                    "basic": True,
                    "ready": {"selector": "#identity"},
                    "fields": [
                        {
                            "key": "platform_creator_id",
                            "name": "id",
                            "kind": "text",
                            "source": {"kind": "dom", "locator": {"selector": "#identity"}},
                        },
                        {
                            "key": "nickname",
                            "name": "nickname",
                            "kind": "text",
                            "source": {"kind": "dom", "locator": {"selector": "#nick"}},
                        },
                    ],
                }
            ],
        }
    )


def test_homepage_must_come_from_exactly_one_source():
    with pytest.raises(CollectorError, match="HOMEPAGE_CONTRACT_AMBIGUOUS"):
        registry(search(homepage_path=None)).require_enabled(live=False)
    with pytest.raises(CollectorError, match="HOMEPAGE_CONTRACT_AMBIGUOUS"):
        registry(
            search(
                homepage_path="homepage",
                homepage_template="https://synthetic.invalid/creator/{platform_creator_id}",
            )
        ).require_enabled(live=False)


def test_homepage_template_needs_the_id_placeholder_and_in_scope_host():
    with pytest.raises(CollectorError, match="HOMEPAGE_TEMPLATE_PLACEHOLDER"):
        registry(
            search(homepage_path=None, homepage_template="https://synthetic.invalid/creator")
        ).require_enabled(live=False)
    with pytest.raises(CollectorError, match="INVALID_HOMEPAGE_TEMPLATE"):
        registry(
            search(
                homepage_path=None,
                homepage_template="https://elsewhere.invalid/creator/{platform_creator_id}",
            )
        ).require_enabled(live=False)
    with pytest.raises(CollectorError, match="INVALID_HOMEPAGE_TEMPLATE"):
        registry(
            search(
                homepage_path=None,
                homepage_template="https://synthetic.invalid/other/{platform_creator_id}",
            )
        ).require_enabled(live=False)
    registry(
        search(
            homepage_path=None,
            homepage_template="https://synthetic.invalid/creator/{platform_creator_id}",
        )
    ).require_enabled(live=False)


def test_homepage_path_alone_still_publishes():
    registry(search()).require_enabled(live=False)


def test_single_page_contract_requires_a_coverage_gap():
    with pytest.raises(CollectorError, match="MISSING_PAGINATION_ACTION"):
        registry(search(next_actions=[])).require_enabled(live=False)
    with pytest.raises(CollectorError, match="SINGLE_PAGE_COVERAGE_GAP_REQUIRED"):
        registry(search(next_actions=[], single_page_only=True)).require_enabled(live=False)
    registry(
        search(next_actions=[], single_page_only=True, coverage_gaps=["page 2+ not verified"])
    ).require_enabled(live=False)


def test_published_contract_verifies_page_three_but_stays_bounded():
    current = PlatformRegistry.model_validate_json(
        Path("contracts/douyin_xingtu.verified.json").read_text()
    )
    assert current.search is not None
    assert current.search.page_fetch_max_verified == 3
    assert current.search.page_fetch_continuous_verified is False
    assert any("page=3" in gap for gap in current.search.coverage_gaps)


def test_page_fetch_contract_requires_live_bounded_or_continuous_evidence():
    valid = search(
        next_actions=[],
        next_page_mode="page_fetch",
        page_fetch_max_verified=2,
        requests=[
            {
                "key": "list",
                "method": "POST",
                "host": "synthetic.invalid",
                "path": "/api/search",
                "request_match": {"page": "$cursor", "keyword": "$keyword"},
                "response_match": {},
                "success_path": "code",
                "success_value": "0",
            }
        ],
    )
    registry(valid).require_enabled(live=False)
    with pytest.raises(CollectorError, match="INVALID_PAGE_FETCH_CONTRACT"):
        registry({**valid, "page_fetch_max_verified": None}).require_enabled(live=False)
    continuous = {
        **valid,
        "page_fetch_max_verified": None,
        "page_fetch_continuous_verified": True,
    }
    registry(continuous).require_enabled(live=False)
    with pytest.raises(CollectorError, match="INVALID_PAGE_FETCH_CONTRACT"):
        registry({**valid, "page_fetch_continuous_verified": True}).require_enabled(live=False)
    with pytest.raises(CollectorError, match="UNUSED_PAGE_FETCH_LIMIT"):
        registry(search(page_fetch_max_verified=2)).require_enabled(live=False)
    with pytest.raises(CollectorError, match="UNUSED_PAGE_FETCH_LIMIT"):
        registry(search(page_fetch_continuous_verified=True)).require_enabled(live=False)


async def test_single_page_boundary_never_returns_exhaustion(plan):
    from xingtu.adapter import BrowserAdapter
    from xingtu.domain import Checkpoint

    spec = registry(
        search(next_actions=[], single_page_only=True, coverage_gaps=["page 2 unknown"])
    )

    async def guard():
        pass

    adapter = BrowserAdapter(None, spec, "synthetic-account", guard, live=False)
    adapter.search_page = object()
    cp = Checkpoint(
        conditions_digest=plan.digest(),
        cursor="2",
        contract_version=CONTRACT,
        adapter_version=CONTRACT,
    )
    with pytest.raises(CollectorError, match="SEARCH_CAPABILITY_LIMIT"):
        await adapter.search(plan, cp, None)
    assert cp.cursor == "2" and not cp.exhausted and not cp.exhaustion_evidence_refs


def test_resolve_homepage_prefers_the_response_path_then_the_template():
    spec = SearchSpec.model_validate(
        search(
            homepage_path=None,
            homepage_template="https://synthetic.invalid/creator/{platform_creator_id}",
        )
    )
    assert resolve_homepage(spec, {"star_id": 123}) == "https://synthetic.invalid/creator/123"
    # An unreadable identity must not silently build a URL from nothing.
    assert resolve_homepage(spec, {"star_id": None}) is None
    assert resolve_homepage(spec, {"star_id": True}) is None
    with_path = SearchSpec.model_validate(
        search(
            homepage_path="link",
            homepage_template="https://synthetic.invalid/creator/{platform_creator_id}",
        )
    )
    assert resolve_homepage(with_path, {"star_id": 123, "link": "https://synthetic.invalid/x"}) == (
        "https://synthetic.invalid/x"
    )


def test_map_bindings_translates_only_registered_values():
    bindings = {"keyword_mode": "content", "keyword": "美妆", "cursor": "1"}
    mapping = {"keyword_mode": {"content": "3"}, "unknown": {"a": "b"}}
    assert map_bindings(bindings, mapping) == {
        "keyword_mode": "3",
        "keyword": "美妆",
        "cursor": "1",
    }
    # An unmapped plan value is never silently replaced.
    assert map_bindings({"keyword_mode": "nickname"}, mapping)["keyword_mode"] == "nickname"


def test_search_spec_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        SearchSpec.model_validate(search(not_a_field=True))
