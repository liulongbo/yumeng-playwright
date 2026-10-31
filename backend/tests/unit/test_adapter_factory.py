from pathlib import Path
from unittest.mock import Mock

from xingtu.adapter import BrowserAdapter
from xingtu.adapter_factory import build_platform_adapter, platform_adapter_available
from xingtu.contracts import PlatformRegistry
from xingtu.domain import PlatformId
from xingtu.juxing_adapter import KuaishouJuxingAdapter


def test_factory_preserves_xingtu_and_selects_verified_juxing_adapter():
    assert platform_adapter_available("douyin_xingtu") is True
    assert platform_adapter_available("kuaishou_juxing") is True
    xingtu_registry = PlatformRegistry.model_validate_json(
        Path("contracts/douyin_xingtu.verified.json").read_text()
    )
    juxing_registry = PlatformRegistry.model_validate_json(
        Path("contracts/kuaishou_juxing.verified.json").read_text()
    )

    async def guard():
        return None

    xingtu = build_platform_adapter(
        PlatformId.DOUYIN_XINGTU,
        Mock(),
        xingtu_registry,
        "expected",
        guard,
        on_session_health=Mock(),
    )
    assert isinstance(xingtu, BrowserAdapter)
    juxing = build_platform_adapter(
        PlatformId.KUAISHOU_JUXING,
        Mock(),
        juxing_registry,
        "expected",
        guard,
        on_session_health=Mock(),
    )
    assert isinstance(juxing, KuaishouJuxingAdapter)
