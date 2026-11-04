"""Featured-collection tab localization (2026-11-04 wake/featured failure).

A featured collection shares the same optional tab as profile modules (for example
``商业能力``).  Its action/readiness timeout must become a failed observation for that collection,
never a task-level ``BROWSER_ACTION_FAILED``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from xingtu.adapter import BrowserAdapter
from xingtu.contracts import Action, LocatorSpec
from xingtu.domain import CollectionType, CollectorError


def spec(key: CollectionType = CollectionType.EXCELLENT_REACH) -> SimpleNamespace:
    return SimpleNamespace(
        key=key,
        actions=[Action(kind="click", locator=LocatorSpec(selector="#tab"))],
        ready=LocatorSpec(selector="#ready"),
        ready_hidden=[],
    )


async def test_featured_action_timeout_is_localized_to_the_collection() -> None:
    adapter = BrowserAdapter.__new__(BrowserAdapter)
    adapter.actions = AsyncMock(
        side_effect=PlaywrightTimeoutError("Locator.click: Timeout 90000ms exceeded.")
    )
    adapter.wait_ready = AsyncMock()
    with pytest.raises(CollectorError) as caught:
        await adapter._run_featured_interaction(object(), spec())
    assert caught.value.code == "MODULE_COLLECTION_FAILED"
    assert caught.value.reason == "FEATURED_ACTION_TIMEOUT:excellent_reach"
    assert BrowserAdapter.featured_spec_local_reason(caught.value) == caught.value.reason
    adapter.wait_ready.assert_not_awaited()


async def test_featured_ready_timeout_is_localized_to_the_collection() -> None:
    adapter = BrowserAdapter.__new__(BrowserAdapter)
    adapter.actions = AsyncMock()
    adapter.wait_ready = AsyncMock(
        side_effect=CollectorError("PLATFORM_PAGE_CHANGED", "PAGE_READY_TIMEOUT")
    )
    with pytest.raises(CollectorError) as caught:
        await adapter._run_featured_interaction(object(), spec(CollectionType.EXCELLENT_SEEDING))
    assert caught.value.reason == "FEATURED_READY_TIMEOUT:excellent_seeding"
    assert BrowserAdapter.featured_spec_local_reason(caught.value) is not None


async def test_featured_session_error_still_aborts() -> None:
    adapter = BrowserAdapter.__new__(BrowserAdapter)
    adapter.actions = AsyncMock(
        side_effect=CollectorError("ACCOUNT_LOGIN_REQUIRED", "REGISTERED_LOGIN_PAGE")
    )
    adapter.wait_ready = AsyncMock()
    with pytest.raises(CollectorError, match="ACCOUNT_LOGIN_REQUIRED"):
        await adapter._run_featured_interaction(object(), spec())
    assert (
        BrowserAdapter.featured_spec_local_reason(
            CollectorError("ACCOUNT_LOGIN_REQUIRED", "REGISTERED_LOGIN_PAGE")
        )
        is None
    )
