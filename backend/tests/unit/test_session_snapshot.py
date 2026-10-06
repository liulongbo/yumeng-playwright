"""Hybrid persistence: persistent profile directory plus an explicit storage-state snapshot.

All data here is synthetic; no browser is launched and no platform host is contacted.  The fake
context mirrors only the three Playwright methods the runtime actually uses.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
from pathlib import Path

from xingtu.runtime import BrowserRuntime, UnitConfig

REGISTRY = {
    "session": {"protected_ready": {"selector": "#ready"}},
}


def unit_config(tmp_path: Path, registry: Path | None = None) -> UnitConfig:
    registry_path = registry or (tmp_path / "registry.json")
    if registry is None:
        registry_path.write_text(json.dumps(REGISTRY))
    return UnitConfig.model_validate(
        {
            "unit_id": "unit-snapshot",
            "account_ref": "acct",
            "expected_account_id": "synthetic-account",
            "line_id": "local",
            "profile_directory": tmp_path / "profile",
            "registry_path": registry_path,
            "network_mode": "local_development",
            "browser_channel": "chromium",
        }
    )


class FakeLocator:
    def __init__(self, count: int, text: str | None = None):
        self._count = count
        self._text = text

    async def count(self) -> int:
        return self._count

    @property
    def first(self) -> FakeLocator:
        return self

    async def text_content(self, timeout: int | None = None) -> str | None:
        return self._text


class FakePage:
    """Selector-aware page: only the registered markers report as present/readable."""

    def __init__(
        self,
        protected_present: bool = False,
        account_text: str | None = None,
        account_count: int | None = None,
    ):
        self.protected_present = protected_present
        self.account_text = account_text
        self.account_count = (
            account_count if account_count is not None else (1 if account_text else 0)
        )

    def locator(self, selector: str) -> FakeLocator:
        if selector == "#ready":
            return FakeLocator(1 if self.protected_present else 0)
        if selector == "#account":
            return FakeLocator(self.account_count, self.account_text)
        return FakeLocator(0)


class FakeFrame:
    def __init__(self, page: FakePage, parent_frame: FakeFrame | None = None):
        self.page = page
        self.parent_frame = parent_frame


class FakeContext:
    def __init__(self, state: dict | None = None):
        self.state = state or {"cookies": [], "origins": []}
        self.added_cookies: list[list[dict]] = []
        self.init_scripts: list[str] = []

    async def storage_state(self) -> dict:
        return self.state

    async def add_cookies(self, cookies: list[dict]) -> None:
        self.added_cookies.append(cookies)

    async def add_init_script(self, script: str) -> None:
        self.init_scripts.append(script)


def test_snapshot_round_trip_covers_cookies_and_local_storage(tmp_path):
    config = unit_config(tmp_path)
    runtime = BrowserRuntime(config, tmp_path)
    source = FakeContext(
        state={
            "cookies": [
                {
                    "name": "star_sessionid",
                    "value": "synthetic",
                    "domain": ".xingtu.cn",
                    "path": "/",
                }
            ],
            "origins": [
                {
                    "origin": "https://www.xingtu.cn",
                    "localStorage": [{"name": "STAR_KEY", "value": "1"}],
                }
            ],
        }
    )

    assert asyncio.run(runtime.export_session_snapshot(source)) is True
    path = runtime.session_snapshot_path
    assert path.is_file()
    # Live credentials: private file inside the private runtime root.
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    payload = json.loads(path.read_text())
    assert payload["schema_version"] == "session_snapshot.v1"
    assert payload["storage_state"]["cookies"][0]["name"] == "star_sessionid"
    assert runtime.session_snapshot_available() is True

    restored = FakeContext()
    assert asyncio.run(runtime._restore_session_snapshot(restored)) is True
    assert runtime.session_snapshot_restored is True
    assert restored.added_cookies[0][0]["name"] == "star_sessionid"
    assert restored.init_scripts and "STAR_KEY" in restored.init_scripts[0]


def test_snapshot_is_opt_out_and_tolerates_broken_files(tmp_path):
    config = unit_config(tmp_path).model_copy(update={"capture_session_snapshot": False})
    runtime = BrowserRuntime(config, tmp_path)
    assert asyncio.run(runtime.export_session_snapshot(FakeContext())) is False
    assert runtime.session_snapshot_available() is False

    enabled = BrowserRuntime(unit_config(tmp_path), tmp_path)
    enabled.session_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    enabled.session_snapshot_path.write_text("{not json")
    assert asyncio.run(enabled._restore_session_snapshot(FakeContext())) is False
    assert enabled.session_snapshot_restored is False


def test_capture_skips_pages_without_the_registered_protected_marker(tmp_path):
    config = unit_config(tmp_path)
    runtime = BrowserRuntime(config, tmp_path)
    runtime.protected_ready_selector = "#ready"
    runtime.account_selector = "#account"
    runtime.snapshot_debounce_seconds = 0.0
    runtime._context = FakeContext(
        state={"cookies": [{"name": "star_sessionid", "value": "synthetic"}], "origins": []}
    )

    # Redirected/blocked surface: must not overwrite a good snapshot with a broken state.
    asyncio.run(runtime._capture_after_navigation(FakeFrame(FakePage(protected_present=False))))
    assert runtime.session_snapshot_available() is False

    asyncio.run(runtime._capture_after_navigation(FakeFrame(FakePage(protected_present=True))))
    assert runtime.session_snapshot_available() is True


def test_creator_detail_page_capture_requires_the_bound_identity(tmp_path):
    """A detail page has no navigation menu; the account locator must still match the binding."""
    config = unit_config(tmp_path)
    runtime = BrowserRuntime(config, tmp_path)
    runtime.protected_ready_selector = "#ready"
    runtime.account_selector = "#account"
    runtime.snapshot_debounce_seconds = 0.0
    runtime._context = FakeContext(
        state={"cookies": [{"name": "star_sessionid", "value": "synthetic"}], "origins": []}
    )

    # Readable but different account: never persisted as this unit's session.
    asyncio.run(
        runtime._capture_after_navigation(
            FakeFrame(FakePage(protected_present=False, account_text="ID: 9999999999999999"))
        )
    )
    assert runtime.session_snapshot_available() is False

    # Ambiguous locator (0 or ≥2 matches) is not proof either.
    asyncio.run(
        runtime._capture_after_navigation(
            FakeFrame(
                FakePage(protected_present=False, account_text="synthetic-account", account_count=2)
            )
        )
    )
    assert runtime.session_snapshot_available() is False

    asyncio.run(
        runtime._capture_after_navigation(
            FakeFrame(FakePage(protected_present=False, account_text="synthetic-account"))
        )
    )
    assert runtime.session_snapshot_available() is True


def test_iframe_navigation_never_triggers_a_snapshot(tmp_path):
    config = unit_config(tmp_path)
    runtime = BrowserRuntime(config, tmp_path)
    runtime.protected_ready_selector = "#ready"
    runtime._context = FakeContext(state={"cookies": [], "origins": []})
    parent = FakeFrame(FakePage(protected_present=True))
    runtime._on_frame_navigated(FakeFrame(FakePage(protected_present=True), parent_frame=parent))
    assert runtime._snapshot_task is None


def test_missing_registry_selector_disables_the_filter_not_the_browser(tmp_path):
    config = unit_config(tmp_path, registry=tmp_path / "absent.json")
    runtime = BrowserRuntime(config, tmp_path)
    assert runtime.protected_ready_selector is None
    assert os.path.isdir(tmp_path) and not (tmp_path / "absent.json").exists()
