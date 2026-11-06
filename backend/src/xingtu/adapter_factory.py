"""Platform Adapter selection without weakening the verified Xingtu path."""

from collections.abc import Awaitable, Callable

from playwright.async_api import BrowserContext

from .adapter import BrowserAdapter
from .contracts import PlatformRegistry
from .domain import CreatorScene, PlatformId, SessionHealth
from .juxing_adapter import KuaishouJuxingAdapter
from .juxing_live_adapter import KuaishouJuxingLiveAdapter
from .xingtu_live_adapter import XingtuLiveAdapter


def platform_adapter_available(platform: PlatformId | str) -> bool:
    """Whether this build contains an executable, verified adapter for the platform."""

    return PlatformId(platform) in {PlatformId.DOUYIN_XINGTU, PlatformId.KUAISHOU_JUXING}


def platform_scene_adapter_available(platform: PlatformId | str, scene: CreatorScene | str) -> bool:
    """Whether this build contains an executable adapter for the platform/scene pair."""

    if CreatorScene(scene) == CreatorScene.VIDEO_SQUARE:
        return platform_adapter_available(platform)
    try:
        PlatformId(platform)
    except ValueError:
        return False
    return True


def build_platform_adapter(
    platform: PlatformId,
    browser: BrowserContext,
    registry: PlatformRegistry,
    expected_account_id: str,
    guard: Callable[[], Awaitable[None]],
    *,
    scene: CreatorScene | str = CreatorScene.VIDEO_SQUARE,
    on_session_health: Callable[[SessionHealth], None],
    manually_attested_account_id: str | None = None,
) -> BrowserAdapter:
    value = CreatorScene(scene) if isinstance(scene, str) else scene
    adapter_type: type[BrowserAdapter]
    if value == CreatorScene.LIVE_SQUARE:
        adapter_type = (
            KuaishouJuxingLiveAdapter
            if platform == PlatformId.KUAISHOU_JUXING
            else XingtuLiveAdapter
        )
    else:
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
