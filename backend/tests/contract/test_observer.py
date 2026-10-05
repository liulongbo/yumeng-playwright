"""Browser/network contracts on an entirely synthetic routed origin; no platform traffic."""

import asyncio
import json

import pytest
from playwright.async_api import async_playwright
from xingtu.contracts import RequestSpec
from xingtu.domain import CollectorError
from xingtu.observer import ResponseCollector


@pytest.fixture
async def page():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.route(
            "https://synthetic.invalid/",
            lambda route: route.fulfill(
                content_type="text/html", body="<html><body>synthetic contract test</body></html>"
            ),
        )
        await page.goto("https://synthetic.invalid/")
        yield page
        await browser.close()


def spec(key="search"):
    return RequestSpec(
        key=key,
        method="GET",
        host="synthetic.invalid",
        path="/search",
        request_match={"condition": "$condition"},
        response_match={"creator": "$creator"},
        success_path="code",
        success_value="0",
        error_codes={"login": "ACCOUNT_LOGIN_REQUIRED"},
    )


async def route_json(route):
    await route.fulfill(
        content_type="application/json", body=json.dumps({"code": 0, "creator": "A", "items": []})
    )


async def test_request_scoping_rejects_old_conditions_and_other_creator(page):
    await page.route("**/search?*", route_json)
    metrics = {}
    async with ResponseCollector(
        page, [spec()], {"condition": "new", "creator": "A"}, 1, 4096, metrics=metrics
    ) as capture:
        await page.evaluate(
            "async () => { await fetch('/search?condition=old');"
            " await fetch('/search?condition=new'); }"
        )
        results, failures = await capture.read()
        assert results["search"]["creator"] == "A" and not failures
        assert metrics == {"requests": 1, "responses": 1}
    assert capture.closed and not capture.requests
    async with ResponseCollector(
        page, [spec()], {"condition": "new", "creator": "B"}, 1, 4096
    ) as capture:
        await page.evaluate("fetch('/search?condition=new')")
        results, failures = await capture.read()
    assert not results and failures["search"] == "RESPONSE_UNCORRELATED"


@pytest.mark.parametrize("code", ["PLATFORM_PERMISSION_DENIED", "PLATFORM_QUOTA_EXHAUSTED"])
async def test_restrictions_are_not_login_or_schema_errors(page, code):
    request = spec().model_copy(update={"error_codes": {"restricted": code}})
    await page.route(
        "**/search?*",
        lambda route: route.fulfill(content_type="application/json", body='{"code":"restricted"}'),
    )
    with pytest.raises(CollectorError) as error:
        async with ResponseCollector(
            page, [request], {"condition": "new", "creator": "A"}, 1, 4096
        ) as capture:
            await page.evaluate("fetch('/search?condition=new')")
            await capture.read()
    assert error.value.code == code


async def test_duplicate_matching_requests_are_ambiguous(page):
    await page.route("**/search?*", route_json)
    async with ResponseCollector(
        page, [spec()], {"condition": "new", "creator": "A"}, 1, 4096
    ) as capture:
        await page.evaluate(
            "Promise.all([fetch('/search?condition=new'),fetch('/search?condition=new')])"
        )
        results, failures = await capture.read()
        assert not results and failures["search"] == "RESPONSE_UNCORRELATED"


@pytest.mark.parametrize(
    "body,content_type,code",
    [
        ("<html>login</html>", "text/html", "PLATFORM_PAGE_CHANGED"),
        ('{"code":"login"}', "application/json", "ACCOUNT_LOGIN_REQUIRED"),
        ('{"code":"unknown"}', "application/json", "PLATFORM_PAGE_CHANGED"),
    ],
)
async def test_html_business_errors_not_empty_results(page, body, content_type, code):
    await page.route(
        "**/search?*", lambda route: route.fulfill(body=body, content_type=content_type)
    )
    with pytest.raises(CollectorError) as error:
        async with ResponseCollector(
            page, [spec()], {"condition": "new", "creator": "A"}, 1, 4096
        ) as capture:
            await page.evaluate("fetch('/search?condition=new')")
            await capture.read()
    assert error.value.code == code


async def test_old_request_started_before_observer_not_accepted(page):
    release = asyncio.Event()

    async def delayed(route):
        await release.wait()
        await route_json(route)

    await page.route("**/search?*", delayed)
    request_seen = asyncio.Event()
    page.on("request", lambda _: request_seen.set())
    await page.evaluate("() => { void fetch('/search?condition=new'); }")
    await request_seen.wait()
    async with ResponseCollector(
        page, [spec()], {"condition": "new", "creator": "A"}, 0.05, 4096
    ) as capture:
        release.set()
        results, failures = await capture.read()
        assert not results and failures["search"] == "MODULE_TIMEOUT"


async def test_response_size_limit(page):
    await page.route("**/search?*", route_json)
    async with ResponseCollector(
        page, [spec()], {"condition": "new", "creator": "A"}, 1, 5
    ) as capture:
        await page.evaluate("fetch('/search?condition=new')")
        results, failures = await capture.read()
        assert not results and failures["search"] == "RESPONSE_TOO_LARGE"
