"""Platform Adapter selection without weakening the verified Xingtu path."""

from collections.abc import Awaitable, Callable

from playwright.async_api import BrowserContext

from .adapter import BrowserAdapter
from .contracts import PlatformRegistry
from .domain import PlatformId, SessionHealth
from .juxing_adapter import KuaishouJuxingAdapter


def platform_adapter_available(platform: PlatformId | str) -> bool:
    """Whether this build contains an executable, verified adapter for the platform."""

    return PlatformId(platform) in {PlatformId.DOUYIN_XINGTU, PlatformId.KUAISHOU_JUXING}


def build_platform_adapter(
    platform: PlatformId,
    browser: BrowserContext,
    registry: PlatformRegistry,
    expected_account_id: str,
    guard: Callable[[], Awaitable[None]],
    *,
    on_session_health: Callable[[SessionHealth], None],
    manually_attested_account_id: str | None = None,
) -> BrowserAdapter:
    adapter_type = (
        KuaishouJuxingAdapter if platform == PlatformId.KUAISHOU_JUXING else BrowserAdapter
    )
    return adapter_type(
        browser,
        registry,
        expected_account_id,
        guard,
        on_session_health=on_session_health,
        manually_attested_account_id=manually_attested_account_id,
    )
