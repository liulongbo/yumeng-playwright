import asyncio

import pytest
from playwright.async_api import async_playwright
from xingtu.adapter import BrowserAdapter
from xingtu.browser_host import wait_for_manual_clearance
from xingtu.cli import wait_for_manual_login
from xingtu.contracts import LocatorSpec, account_id_from_url, bind_account_to_url
from xingtu.domain import CollectorError, SessionHealthStatus

from backend.tests.unit.test_search_contract_registration import registry, search


async def test_challenge_interrupts_readiness_and_maintenance_waits_for_clearance():
    spec = registry(search())
    spec.session.error_selectors = {
        "PLATFORM_SECURITY_CHALLENGE": LocatorSpec(selector="#challenge")
    }

    async def guard():
        pass

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context()
        page = await context.new_page()
        await page.set_content('<div id="account">account</div><div id="challenge">verify</div>')
        adapter = BrowserAdapter(context, spec, "account", guard, live=False)
        with pytest.raises(CollectorError, match="PLATFORM_SECURITY_CHALLENGE"):
            await adapter.wait_ready(page, LocatorSpec(selector="#ready"), [])
        await page.evaluate(
            "document.body.insertAdjacentHTML('beforeend', '<div id=ready>ok</div>')"
        )
        pending = asyncio.create_task(wait_for_manual_login(page, spec.session, 5))
        await asyncio.sleep(0.1)
        assert not pending.done(), "app behind a challenge must not certify the session"
        await page.locator("#challenge").evaluate("el => el.remove()")
        assert await pending == "account"
        await browser.close()


async def test_session_health_distinguishes_valid_mismatch_login_and_indeterminate():
    spec = registry(search())
    spec.operation_timeout_seconds = 0.1
    spec.session.error_selectors = {
        "ACCOUNT_LOGIN_REQUIRED": LocatorSpec(selector="#login"),
        "PLATFORM_SECURITY_CHALLENGE": LocatorSpec(selector="#challenge"),
    }

    async def guard():
        pass

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context()
        page = await context.new_page()
        adapter = BrowserAdapter(context, spec, "expected", guard, live=False)

        await page.set_content('<div id="ready">ready</div><div id="account">expected</div>')
        assert (await adapter.inspect_session(page)).status == SessionHealthStatus.VALID

        await page.set_content('<div id="ready">ready</div><div id="account">other</div>')
        mismatch = await adapter.inspect_session(page)
        assert mismatch.status == SessionHealthStatus.ACCOUNT_MISMATCH
        assert mismatch.observed_account_id == "other"
        with pytest.raises(CollectorError) as error:
            await adapter.check_session(page)
        assert error.value.code == "ACCOUNT_MISMATCH"

        await page.set_content('<div id="login">login</div>')
        assert (await adapter.inspect_session(page)).status == SessionHealthStatus.LOGIN_REQUIRED

        await page.set_content("<div>app shell only</div>")
        unknown = await adapter.inspect_session(page)
        assert unknown.status == SessionHealthStatus.INDETERMINATE
        with pytest.raises(CollectorError) as error:
            await adapter.check_session(page)
        assert error.value.code == "SESSION_INDETERMINATE"
        await browser.close()


async def test_manual_identity_attestation_is_a_narrow_fallback_for_an_unreadable_locator():
    spec = registry(search())
    spec.operation_timeout_seconds = 0.1
    spec.session.error_selectors = {
        "ACCOUNT_LOGIN_REQUIRED": LocatorSpec(selector="#login"),
        "PLATFORM_SECURITY_CHALLENGE": LocatorSpec(selector="#challenge"),
    }

    async def guard():
        pass

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context()
        page = await context.new_page()
        adapter = BrowserAdapter(
            context,
            spec,
            "expected",
            guard,
            live=False,
            manually_attested_account_id="expected",
        )

        # A proven protected business surface may use the attestation only when its account
        # locator is absent/unreadable.
        await page.set_content('<div id="ready">ready</div>')
        health = await adapter.inspect_session(page)
        assert health.status == SessionHealthStatus.VALID
        assert health.evidence_reason == "MANUALLY_ATTESTED_UNIQUE_ACCOUNT"

        # A readable wrong account, login page, or challenge always defeats the fallback.
        await page.set_content('<div id="ready">ready</div><div id="account">other</div>')
        assert (await adapter.inspect_session(page)).status == SessionHealthStatus.ACCOUNT_MISMATCH
        await page.set_content('<div id="login">login</div><div id="ready">ready</div>')
        assert (await adapter.inspect_session(page)).status == SessionHealthStatus.LOGIN_REQUIRED
        await page.set_content('<div id="challenge">challenge</div><div id="ready">ready</div>')
        assert (
            await adapter.inspect_session(page)
        ).status == SessionHealthStatus.SECURITY_CHALLENGE
        await browser.close()


async def test_declared_url_account_distinguishes_juxing_child_accounts():
    spec = registry(search())
    spec.operation_timeout_seconds = 0.1
    spec.session.account_url_parameter = "__accountId__"

    async def guard():
        pass

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context()
        page = await context.new_page()
        await page.route(
            "**/*",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body='<div id="ready">ready</div>',
            ),
        )
        adapter = BrowserAdapter(context, spec, "60821564", guard, live=False)

        await page.goto(
            "https://platform.invalid/?__accountId__=60821564#/star_plaza/video"
            "?__accountId__=60821564"
        )
        valid = await adapter.inspect_session(page)
        assert valid.status == SessionHealthStatus.VALID
        assert valid.evidence_reason == "PROTECTED_PAGE_AND_URL_ACCOUNT_VERIFIED"

        await page.goto(
            "https://platform.invalid/?__accountId__=other#/star_plaza/video?__accountId__=other"
        )
        mismatch = await adapter.inspect_session(page)
        assert mismatch.status == SessionHealthStatus.ACCOUNT_MISMATCH
        assert mismatch.observed_account_id == "other"
        await browser.close()


def test_account_binding_updates_outer_and_spa_query_without_losing_route():
    bound = bind_account_to_url(
        "https://k.kuaishou.com/#/promotion/star/42?openBy=user",
        "__accountId__",
        "60821564",
    )
    assert "openBy=user" in bound
    assert account_id_from_url(bound, "__accountId__") == "60821564"
    assert bound.count("__accountId__=60821564") == 2


async def test_manual_maintenance_accepts_declared_protected_url_account():
    spec = registry(search())
    spec.session.account_url_parameter = "__accountId__"

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context()
        page = await context.new_page()
        await page.route(
            "**/*",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body='<div id="ready">ready</div>',
            ),
        )
        await page.goto(
            "https://platform.invalid/?__accountId__=60821564#/star_plaza/video"
            "?__accountId__=60821564"
        )
        assert await wait_for_manual_clearance(page, spec.session, 0.5) == "60821564"
        await browser.close()
