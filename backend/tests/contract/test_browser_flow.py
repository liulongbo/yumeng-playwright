"""Production browser adapter exercised against artificial HTML/network on a routed origin."""

import json
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright
from xingtu.adapter import BrowserAdapter
from xingtu.contracts import PlatformRegistry
from xingtu.domain import Checkpoint, ExecutionContext


def registry(capabilities):
    def dom(selector):
        return {"kind": "dom", "locator": {"selector": selector}}

    return PlatformRegistry.model_validate(
        {
            "contract_version": "synthetic-v1",
            "adapter_version": "synthetic-v1",
            "status": "VERIFIED",
            "sample_kind": "synthetic",
            "capabilities": capabilities.model_dump(),
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
            "search": {
                "entry_url": "https://synthetic.invalid/search",
                "reset_actions": [],
                "apply_actions": [{"kind": "click", "locator": {"selector": "#go"}}],
                "next_actions": [{"kind": "click", "locator": {"selector": "#next"}}],
                "ready": {"selector": "#ready"},
                "readback": {
                    "sort": {"selector": "#sort"},
                    "followers.min": {"selector": "#min"},
                    "followers.max": {"selector": "#max"},
                },
                "requests": [
                    {
                        "key": "list",
                        "method": "GET",
                        "host": "synthetic.invalid",
                        "path": "/api/search",
                        "request_match": {
                            "sort": "$sort",
                            "min": "$followers.min",
                            "max": "$followers.max",
                        },
                        "response_match": {"sort": "$sort"},
                        "success_path": "code",
                        "success_value": "0",
                    }
                ],
                "result_request_key": "list",
                "candidates_path": "items",
                "id_path": "id",
                "homepage_path": "url",
                "next_path": "next",
                "exhausted_path": "done",
                "exhausted_value": "true",
                "pagination": "page",
            },
            "modules": [
                {
                    "key": "basic",
                    "basic": True,
                    "ready": {"selector": "#identity"},
                    "requests": [
                        {
                            "key": "basic",
                            "method": "GET",
                            "host": "synthetic.invalid",
                            "path": "/api/basic",
                            "request_match": {"id": "$creator_id"},
                            "response_match": {"id": "$creator_id"},
                            "success_path": "code",
                            "success_value": "0",
                        }
                    ],
                    "fields": [
                        {
                            "key": "platform_creator_id",
                            "name": "id",
                            "kind": "text",
                            "source": dom("#identity"),
                        },
                        {
                            "key": "nickname",
                            "name": "nickname",
                            "kind": "text",
                            "source": {
                                "kind": "response",
                                "request_key": "basic",
                                "path": "nickname",
                            },
                        },
                    ],
                },
                {
                    # This endpoint auto-fires during homepage navigation and must be observed
                    # before the page load begins, alongside the basic response.
                    "key": "commercial",
                    "capture_on_profile_load": True,
                    "default_bindings": {"scope": "default"},
                    "ready": {"selector": "#commercial"},
                    "timeout_seconds": 0.5,
                    "checkpoint_version": 2,
                    "requests": [
                        {
                            "key": "commercial",
                            "method": "GET",
                            "host": "synthetic.invalid",
                            "path": "/api/commercial",
                            "request_match": {"id": "$creator_id", "scope": "$scope"},
                            "response_match": {"id": "$creator_id", "scope": "$scope"},
                            "success_path": "code",
                            "success_value": "0",
                        }
                    ],
                    "fields": [
                        {
                            "key": "value",
                            "name": "value",
                            "kind": "number",
                            "unit": "count",
                            "source": {
                                "kind": "response",
                                "request_key": "commercial",
                                "path": "value",
                            },
                        }
                    ],
                },
                {
                    # Module-level permission evidence, not a missing element.
                    "key": "fans",
                    "ready": {"selector": "#fans"},
                    "absence": {
                        "probe": dom("#absent"),
                        "permission_values": ["no-permission"],
                    },
                    "fields": [
                        {
                            "key": "total",
                            "name": "fans",
                            "kind": "number",
                            "unit": "count",
                            "source": dom("#fans"),
                        }
                    ],
                },
            ],
        }
    )


def search_payload(items):
    return {
        "code": 0,
        "sort": "platform_default",
        "items": items,
        "next": None,
        "done": True,
    }


async def route(route):
    url = urlsplit(route.request.url)
    query = parse_qs(url.query)
    if url.path == "/api/search":
        await route.fulfill(
            content_type="application/json",
            body=json.dumps(
                search_payload([{"id": "A", "url": "https://synthetic.invalid/creator/A"}])
            ),
        )
    elif url.path == "/api/basic":
        await route.fulfill(
            content_type="application/json",
            body=json.dumps(
                {
                    "code": 0,
                    "id": query["id"][0],
                    "nickname": "same synthetic nickname",
                }
            ),
        )
    elif url.path == "/api/commercial":
        # Echo both the creator and the module default condition for response correlation.
        await route.fulfill(
            content_type="application/json",
            body=json.dumps(
                {"code": 0, "id": query["id"][0], "scope": query["scope"][0], "value": "42"}
            ),
        )
    else:
        extra = (
            (
                '<div id="identity">A</div><div id="fans">1.2万</div>'
                '<div id="absent">no-permission</div>'
                '<div id="commercial">ok</div>'
                '<script>fetch("/api/basic?id=A")</script>'
                '<script>fetch("/api/commercial?id=A&scope=default")</script>'
            )
            if url.path.startswith("/creator")
            else (
                '<div id="min">0</div><div id="max">100000</div>'
                '<div id="sort">platform_default</div><button id="go" '
                "onclick=\"fetch('/api/search?sort=platform_default&min=0&max=100000')\">search</button>"
            )
        )
        await route.fulfill(
            content_type="text/html",
            body='<meta charset="utf-8"><div id="account">account</div>'
            '<div id="ready">ready</div>' + extra,
        )


def context_of(plan):
    return ExecutionContext(
        root_task_id="root",
        task_id="task",
        attempt_id="attempt",
        execution_unit_id="unit",
        lease_generation=1,
        session_version=1,
        capability_version="synthetic-v1",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
    )


async def guard():
    pass


def checkpoint(plan):
    return Checkpoint(
        conditions_digest=plan.digest(),
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
    )


async def test_search_profile_initial_response_and_default_module(capabilities, plan):
    config = registry(capabilities)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context()
        await context.route("**/*", route)
        document_urls = []
        context.on(
            "request",
            lambda request: (
                document_urls.append(request.url) if request.resource_type == "document" else None
            ),
        )
        adapter = BrowserAdapter(context, config, "account", guard, live=False)
        ctx = context_of(plan)
        await adapter.prepare(plan, checkpoint(plan), ctx)
        assert document_urls[0] == config.search.entry_url
        assert config.session.entry_url not in document_urls
        page = await adapter.search(plan, checkpoint(plan), ctx)
        assert page.exhausted and len(page.candidates) == 1
        assert not page.unidentified
        async with adapter.profile(page.candidates[0], ctx):
            basic = await adapter.collect_module("basic", page.candidates[0], ctx)
            assert basic.complete and basic.fields[1].value == "same synthetic nickname"
            commercial = await adapter.collect_module("commercial", page.candidates[0], ctx)
            assert commercial.complete
            assert commercial.fields[0].value.amount == 42
            assert adapter.detail_page is not None
            fans = await adapter.collect_module("fans", page.candidates[0], ctx)
            # Registered module absence evidence completes the check without reading fields.
            assert fans.status == "NO_PERMISSION"
            assert fans.complete and fans.fields[0].value is None
        assert adapter.detail_page is None
        await adapter.close()
        await browser.close()


async def test_unreadable_rows_become_diagnostics_not_candidates(capabilities, plan):
    config = registry(capabilities)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context()

        async def mixed(route):
            url = urlsplit(route.request.url)
            if url.path == "/api/search":
                await route.fulfill(
                    content_type="application/json",
                    body=json.dumps(
                        search_payload(
                            [
                                {"url": "https://synthetic.invalid/creator/A"},
                                {"id": "B", "url": "https://evil.invalid/creator/B"},
                                {"id": "C", "url": "https://synthetic.invalid/creator/C"},
                            ]
                        )
                    ),
                )
            else:
                await route.fulfill(
                    content_type="text/html",
                    body='<meta charset="utf-8"><div id="account">account</div>'
                    '<div id="ready">ready</div><div id="min">0</div><div id="max">100000</div>'
                    '<div id="sort">platform_default</div><button id="go" '
                    "onclick=\"fetch('/api/search?sort=platform_default&min=0&max=100000')\">"
                    "search</button>",
                )

        await context.route("**/*", mixed)
        adapter = BrowserAdapter(context, config, "account", guard, live=False)
        ctx = context_of(plan)
        await adapter.prepare(plan, checkpoint(plan), ctx)
        page = await adapter.search(plan, checkpoint(plan), ctx)
        assert [c.platform_creator_id for c in page.candidates] == ["C"]
        assert [d.reason for d in page.unidentified] == [
            "CANDIDATE_IDENTITY_UNREADABLE",
            "UNVERIFIED_HOMEPAGE",
        ]
        await adapter.close()
        await browser.close()


async def test_verified_page_fetch_reuses_in_memory_headers_and_advances_checkpoint(
    capabilities, plan
):
    config = registry(capabilities)
    assert config.search
    search_data = config.search.model_dump(mode="json")
    search_data.update(
        {
            "initial_cursor": "1",
            "next_actions": [],
            "next_page_mode": "page_fetch",
            "page_fetch_max_verified": None,
            "page_fetch_continuous_verified": True,
            "requests": [
                {
                    "key": "list",
                    "method": "POST",
                    "host": "synthetic.invalid",
                    "path": "/api/search",
                    "request_match": {
                        "page": "$cursor",
                        "sort": "$sort",
                        "min": "$followers.min",
                        "max": "$followers.max",
                    },
                    "response_match": {"sort": "$sort"},
                    "success_path": "code",
                    "success_value": "0",
                }
            ],
        }
    )
    config.search = type(config.search).model_validate(search_data)
    config.require_enabled(live=False)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context()

        async def paged(route):
            request = route.request
            url = urlsplit(request.url)
            if url.path == "/api/search":
                body = request.post_data_json
                page_number = int(body["page"])
                if request.headers.get("x-replay-token") != "synthetic-token":
                    await route.fulfill(status=400, body="missing replay header")
                    return
                await route.fulfill(
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "code": 0,
                            "sort": "platform_default",
                            "items": [
                                {
                                    "id": f"P{page_number}",
                                    "url": f"https://synthetic.invalid/creator/P{page_number}",
                                }
                            ],
                            "next": page_number,
                            "done": page_number == 3,
                        }
                    ),
                )
                return
            await route.fulfill(
                content_type="text/html",
                body='<meta charset="utf-8"><div id="account">account</div>'
                '<div id="ready">ready</div><div id="min">0</div><div id="max">100000</div>'
                '<div id="sort">platform_default</div><button id="go" '
                "onclick=\"fetch('/api/search',{method:'POST',headers:{'content-type':'application/json',"
                "'x-replay-token':'synthetic-token'},body:JSON.stringify({page:1,sort:'platform_default',"
                "min:'0',max:'100000'})})\">search</button>",
            )

        await context.route("**/*", paged)
        adapter = BrowserAdapter(context, config, "account", guard, live=False)
        ctx = context_of(plan)
        first_cp = checkpoint(plan)
        await adapter.prepare(plan, first_cp, ctx)
        first = await adapter.search(plan, first_cp, ctx)
        assert [row.platform_creator_id for row in first.candidates] == ["P1"]
        assert first.next_checkpoint == "2" and not first.exhausted
        second_cp = checkpoint(plan)
        second_cp.cursor = first.next_checkpoint
        second = await adapter.search(plan, second_cp, ctx)
        assert [row.platform_creator_id for row in second.candidates] == ["P2"]
        assert not second.exhausted and second.next_checkpoint == "3"
        third_cp = checkpoint(plan)
        third_cp.cursor = second.next_checkpoint
        third = await adapter.search(plan, third_cp, ctx)
        assert [row.platform_creator_id for row in third.candidates] == ["P3"]
        assert third.exhausted and third.next_checkpoint is None
        await adapter.close()
        await browser.close()
