"""UPD-06: the single scheduler resolves every available platform/scene contract."""

from __future__ import annotations

from pathlib import Path

from xingtu.domain import CreatorScene, NetworkMode, PlatformId
from xingtu.product_cli import update_scopes
from xingtu.runtime import PlatformBindingConfig, UnitConfig

ROOT = Path(__file__).resolve().parents[3]
JUXING_VIDEO = ROOT / "contracts" / "kuaishou_juxing.verified.json"
JUXING_LIVE = ROOT / "contracts" / "kuaishou_juxing.live.verified.json"


def juxing_unit() -> UnitConfig:
    """A dedicated juxing unit: no top-level live path, the binding has one."""

    return UnitConfig(
        unit_id="unit-juxing-only",
        account_ref="juxing",
        expected_account_id="60821564",
        line_id="local",
        profile_directory=Path("/tmp/upd06-juxing-profile"),
        registry_path=JUXING_VIDEO,
        live_registry_path=None,
        active_platform=PlatformId.KUAISHOU_JUXING,
        platform_bindings=[
            PlatformBindingConfig(
                platform=PlatformId.KUAISHOU_JUXING,
                account_ref="juxing",
                expected_account_id="60821564",
                profile_directory=Path("/tmp/upd06-juxing-binding"),
                registry_path=JUXING_VIDEO,
                live_registry_path=JUXING_LIVE,
            )
        ],
        network_mode=NetworkMode.LOCAL_DEVELOPMENT,
        browser_channel="chrome",
    )


def test_scheduler_uses_binding_live_contract_for_a_dedicated_juxing_unit() -> None:
    scopes, errors = update_scopes(juxing_unit(), None)
    assert errors == {
        "douyin_xingtu:video_square": "UPDATE_VIDEO_REGISTRY_UNAVAILABLE",
        "douyin_xingtu:live_square": "UPDATE_LIVE_REGISTRY_UNAVAILABLE",
    }
    assert set(scopes) == {
        "kuaishou_juxing:video_square",
        "kuaishou_juxing:live_square",
    }
    assert (
        scopes["kuaishou_juxing:live_square"].registry.contract_version == "juxing-live-square-v3"
    )
    assert scopes["kuaishou_juxing:live_square"].scene == CreatorScene.LIVE_SQUARE
