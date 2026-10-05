"""F06 adapter contract on artificial routes in a real Chromium (no platform traffic)."""

import json
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright
from xingtu.adapter import BrowserAdapter
from xingtu.contracts import PlatformRegistry
from xingtu.covers import CoverPipeline
from xingtu.domain import Checkpoint, CollectionStatus, CreatorRef, ExecutionContext, FieldStatus

CARD_FIELDS = ["platform_content_id", "link", "title", "play", "cover"]


def registry(capabilities):
    def dom(selector):
        return {"kind": "dom", "locator": {"selector": selector}}

    def response(path, *, key="cards", **extra):
        return {"kind": "response", "request_key": key, "path": path, **extra}

    card_fields = [
        {"key": "platform_content_id", "name": "id", "kind": "text", "source": response("id")},
        {
            "key": "link",
            "name": "link",
            "kind": "text",
            "source": response("link"),
            "not_provided_values": ["none"],
        },
        {
            "key": "title",
            "name": "title",
            "kind": "text",
            "source": response("title"),
            "truncate_marker": "…",
        },
        {
            "key": "play",
            "name": "play",
            "kind": "number",
            "unit": "count",
            "source": response("play"),
        },
        {"key": "cover", "name": "cover", "kind": "text", "source": response("cover")},
    ]

    def featured(key, more_selector=None):
        return {
            "key": key,
            "module_label": f"synthetic {key}",
            # The registered module tab re-enters the homepage so the module load is observed.
            "entry": f"/creator/A?tab={key}",
            "ready": {"selector": "#featured"},
            "ready_hidden": [{"selector": "#loading"}],
            "actions": [{"kind": "click", "locator": {"selector": more_selector}}]
            if more_selector
            else [],
            "timeout_seconds": 2,
            "checkpoint_version": 1,
            "requests": [
                {
                    "key": "cards",
                    "method": "GET",
                    "host": "synthetic.invalid",
                    "path": f"/api/{key}",
                    "request_match": {"id": "$creator_id", "collection": "$collection"},
                    "response_match": {"id": "$creator_id", "collection": "$collection"},
                    "success_path": "code",
                    "success_value": "0",
                    "repeats": True,
                }
            ],
            "result_request_key": "cards",
            "cards_path": "cards",
            "link_hosts": ["synthetic.invalid"],
            "default_period_path": "period",
            "set_key_path": "set_key",
            "load_complete_path": "done",
            "load_complete_value": "true",
            "card_fields": card_fields,
            "cover": {
                "field_key": "cover",
                "allowed_hosts": ["cdn.synthetic.invalid"],
                "allowed_content_types": ["image/png"],
                "max_bytes": 4096,
                "timeout_seconds": 5,
                "max_redirects": 0,
            },
        }

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
            "response_body_max_bytes": 8192,
            "session": {
                "entry_url": "https://synthetic.invalid/search",
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
                "readback": {"sort": {"selector": "#sort"}},
                "requests": [
                    {
                        "key": "list",
                        "method": "GET",
                        "host": "synthetic.invalid",
                        "path": "/api/search",
                        "request_match": {"sort": "$sort"},
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
                            "name": "n",
                            "kind": "text",
                            "source": dom("#nickname"),
                        },
                    ],
                }
            ],
            "featured": [featured("excellent_reach", "#more-reach"), featured("excellent_seeding")],
        }
    )


class Store:
    def __init__(self):
        self.objects = {}

    def put(self, *, root_task_id, body, content_type, checksum, source_url):
        object_id = f"cover/{root_task_id}/{checksum}"
        self.objects[object_id] = (body, content_type)
        return object_id

    def verify(self, object_id):
        assert object_id in self.objects

    def delete(self, object_id):
        self.objects.pop(object_id, None)


def payload(cards, *, done, period="synthetic default 30 days", set_key="set-a", extra=None):
    body = {
        "code": 0,
        "id": "A",
        "collection": "x",
        "cards": cards,
        "set_key": set_key,
        "done": done,
    }
    if period is not None:
        body["period"] = period
    if extra:
        body.update(extra)
    return body


HAPPY_REACH_PAGE_1 = payload(
    [
        {
            "id": "v1",
            "link": "https://synthetic.invalid/work/v1",
            "title": "first work",
            "play": "1.2万",
            "cover": "https://cdn.synthetic.invalid/v1.png",
        },
        {
            "id": "v2",
            "link": "https://synthetic.invalid/work/v2",
            "title": "second work",
            "play": "300",
            "cover": "https://cdn.synthetic.invalid/v2.png",
        },
    ],
    done=False,
    # Works outside the registered cards_path must never be collected.
    extra={"other_works": [{"id": "OUTSIDE", "title": "not in scope"}]},
)
HAPPY_REACH_PAGE_2 = payload(
    [
        {
            "id": "v2",
            "link": "https://synthetic.invalid/work/v2",
            "title": "second work",
            "play": "300",
            "cover": "https://cdn.synthetic.invalid/v2.png",
        },
        {
            "id": "v3",
            "link": "https://synthetic.invalid/work/v3",
            "title": "a very long title that the platform shortened…",
            "play": "42",
            "cover": "https://cdn.synthetic.invalid/v3.png",
        },
    ],
    done=True,
)
HAPPY_SEEDING = payload(
    [
        {
            "id": "v2",
            "link": "https://synthetic.invalid/work/v2",
            "title": "second work (seeding view)",
            "play": "777",
            "cover": "https://cdn.synthetic.invalid/v2.png",
        },
        {
            "id": "v9",
            "link": "none",
            "title": "no link provided",
            "play": "5",
            "cover": "https://cdn.synthetic.invalid/v9.png",
        },
    ],
    done=True,
    set_key="set-b",
)


def context_of():
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


def checkpoint():
    from xingtu.domain import FilterPlan

    plan = FilterPlan(
        capability_version="synthetic-v1",
        filters=[
            {
                "field": "followers",
                "operator": "range",
                "value": {"min": 0, "max": 100},
                "source_fields": ["followers_max"],
                "unit": "count",
            }
        ],
    )
    return Checkpoint(
        conditions_digest=plan.digest(),
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
    )


async def guard():
    pass


def homepage_html():
    return (
        '<meta charset="utf-8"><div id="account">account</div><div id="ready">ready</div>'
        '<div id="identity">A</div><div id="nickname">nick</div>'
        '<div id="featured">featured</div><div id="loading" style="display:none">loading</div>'
        '<button id="more-reach" '
        "onclick=\"fetch('/api/excellent_reach?id=A&collection=excellent_reach&page=2')\">more</button>"
        '<script>fetch("/api/basic?id=A")</script>'
        '<script>fetch("/api/excellent_reach?id=A&collection=excellent_reach&page=1")</script>'
        '<script>fetch("/api/excellent_seeding?id=A&collection=excellent_seeding&page=1")</script>'
    )


async def test_two_modules_incremental_load_identity_and_bounds(capabilities):
    page_calls = {"reach": 0}

    async def route(route):
        parsed = urlsplit(route.request.url)
        path = parsed.path
        query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        if path == "/api/basic":
            await route.fulfill(
                content_type="application/json",
                body=json.dumps({"code": 0, "id": query["id"], "nickname": "nick"}),
            )
        elif path == "/api/excellent_reach":
            page_calls["reach"] += 1
            body = HAPPY_REACH_PAGE_1 if query.get("page") == "1" else HAPPY_REACH_PAGE_2
            echo = {**body, "collection": query["collection"]}
            await route.fulfill(content_type="application/json", body=json.dumps(echo))
        elif path == "/api/excellent_seeding":
            echo = {**HAPPY_SEEDING, "collection": query["collection"]}
            await route.fulfill(content_type="application/json", body=json.dumps(echo))
        elif path.endswith(".png"):
            await route.fulfill(content_type="image/png", body=b"\x89PNG" + path.encode())
        else:
            await route.fulfill(content_type="text/html", body=homepage_html())

    config = registry(capabilities)
    store = Store()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context()
        await context.route("**/*", route)
        adapter = BrowserAdapter(context, config, "account", guard, live=False)
        creator = CreatorRef(
            platform_creator_id="A", verified_homepage="https://synthetic.invalid/creator/A"
        )
        ctx = context_of()
        async with adapter.profile(creator, ctx):
            observations = await adapter.collect_featured_collections(creator, checkpoint(), ctx)
            for observation in observations:
                spec = adapter.featured_specs[observation.collection_type.value]
                pipeline = CoverPipeline(None, store)
                for card in observation.cards:
                    card.cover = await pipeline.store(
                        root_task_id="root",
                        source_url=card.cover.source_url,
                        spec=spec.cover,
                        fetch=adapter.fetch_cover,
                    )
                observation.apply_cover_outcomes(cover_registered=True)
        await adapter.close()
        await browser.close()

    reach, seeding = observations
    assert reach.collection_type.value == "excellent_reach"
    assert reach.status == CollectionStatus.COMPLETE and reach.load_complete
    assert reach.default_period_label == "synthetic default 30 days"
    assert reach.set_key == "set-a"
    # In-module incremental load: three cards, the re-sent v2 counted once.
    assert [card.platform_content_id for card in reach.cards] == ["v1", "v2", "v3"]
    assert [card.position for card in reach.cards] == [0, 1, 2]
    assert reach.cards[1].reload_count == 2
    assert all(card.identity_kind == "platform_content_id" for card in reach.cards)
    assert reach.cards[2].truncated_fields == ["title"]
    assert reach.cards[2].fields[2].truncated
    assert reach.cards[0].fields[3].value.amount == 12000
    assert reach.cards[0].fields[3].value.bound == "approximate"
    assert all(card.cover.status.value == "STORED" for card in reach.cards)
    assert len(store.objects) == 4  # v1/v2/v3 covers plus the shared seeding v2 cover

    assert seeding.status == CollectionStatus.COMPLETE
    assert [card.platform_content_id for card in seeding.cards] == ["v2", "v9"]
    # Same work in both modules: independent positions and metric observations.
    assert seeding.cards[0].fields[3].value.amount == 777
    assert reach.cards[1].fields[3].value.amount == 300
    assert seeding.cards[1].fields[1].status == FieldStatus.NOT_PROVIDED
    assert seeding.cards[1].canonical_link is None
    assert f"link_missing:{seeding.cards[1].card_id}" in seeding.coverage_notes
    # The module issued at least the initial and the in-module loaded page.
    assert page_calls["reach"] >= 2


async def test_absence_incomplete_and_endpoint_evidence(capabilities):
    async def route(route):
        parsed = urlsplit(route.request.url)
        path, query = (
            parsed.path,
            {key: values[0] for key, values in parse_qs(parsed.query).items()},
        )
        if path == "/api/basic":
            await route.fulfill(
                content_type="application/json",
                body=json.dumps({"code": 0, "id": "A", "nickname": "nick"}),
            )
        elif path == "/api/excellent_reach":
            body = payload(
                [
                    {
                        "id": "v1",
                        "link": "https://synthetic.invalid/work/v1",
                        "title": "only card",
                        "play": "10",
                        "cover": "https://cdn.synthetic.invalid/v1.png",
                    }
                ],
                done=False,
                period=None,
            )
            await route.fulfill(
                content_type="application/json",
                body=json.dumps({**body, "collection": query["collection"]}),
            )
        elif path == "/api/excellent_seeding":
            body = payload([], done=True, extra={"state": "no-permission"})
            await route.fulfill(
                content_type="application/json",
                body=json.dumps({**body, "collection": query["collection"]}),
            )
        else:
            await route.fulfill(
                content_type="text/html",
                body=homepage_html().replace(
                    '<div id="featured">featured</div>',
                    '<div id="featured">featured</div><div id="absent">no-permission</div>',
                ),
            )

    data = registry(capabilities).model_dump(mode="json")
    for spec in data["featured"]:
        spec["absence"] = {
            "probe": {"kind": "response", "request_key": "cards", "path": "state"},
            "permission_values": ["no-permission"],
        }
    config = PlatformRegistry.model_validate(data)
    config.require_enabled(live=False)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context()
        await context.route("**/*", route)
        adapter = BrowserAdapter(context, config, "account", guard, live=False)
        creator = CreatorRef(
            platform_creator_id="A", verified_homepage="https://synthetic.invalid/creator/A"
        )
        ctx = context_of()
        async with adapter.profile(creator, ctx):
            observations = await adapter.collect_featured_collections(creator, checkpoint(), ctx)
        await adapter.close()
        await browser.close()

    reach, seeding = observations
    # An unproven module end is explicitly incomplete, never "empty".
    assert reach.status == CollectionStatus.INCOMPLETE and not reach.load_complete
    assert "module_load_end_unverified" in reach.coverage_gaps
    # The module period label is only what the page actually reported; nothing is invented.
    assert reach.default_period_label is None
    assert len(reach.cards) == 1
    # Registered module-level absence evidence completes the check with a reason.
    assert seeding.status == CollectionStatus.NO_PERMISSION and not seeding.cards
    assert seeding.evidence_refs


async def test_module_failure_does_not_drop_the_other_module(capabilities):
    async def route(route):
        parsed = urlsplit(route.request.url)
        path, query = (
            parsed.path,
            {key: values[0] for key, values in parse_qs(parsed.query).items()},
        )
        if path == "/api/basic":
            await route.fulfill(
                content_type="application/json",
                body=json.dumps({"code": 0, "id": "A", "nickname": "nick"}),
            )
        elif path == "/api/excellent_reach":
            # Correlated response without the declared card list: a module read failure.
            await route.fulfill(
                content_type="application/json",
                body=json.dumps({"code": 0, "id": "A", "collection": query["collection"]}),
            )
        elif path == "/api/excellent_seeding":
            echo = {**HAPPY_SEEDING, "collection": query["collection"]}
            await route.fulfill(content_type="application/json", body=json.dumps(echo))
        else:
            await route.fulfill(content_type="text/html", body=homepage_html())

    config = registry(capabilities)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context()
        await context.route("**/*", route)
        adapter = BrowserAdapter(context, config, "account", guard, live=False)
        creator = CreatorRef(
            platform_creator_id="A", verified_homepage="https://synthetic.invalid/creator/A"
        )
        ctx = context_of()
        async with adapter.profile(creator, ctx):
            observations = await adapter.collect_featured_collections(creator, checkpoint(), ctx)
        await adapter.close()
        await browser.close()

    reach, seeding = observations
    assert reach.status == CollectionStatus.FAILED and reach.failure_reason
    assert reach.collection_type.value == "excellent_reach"
    assert seeding.status == CollectionStatus.COMPLETE and len(seeding.cards) == 2
