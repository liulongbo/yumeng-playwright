from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from xingtu.platform_runtime import (
    ProfileLockBusy,
    acquire_profile_lock,
    classify_windows_chromium_lock_error,
    discover_chrome_executable,
    release_profile_lock,
    validate_windows_private_path,
)


def test_posix_profile_lock_is_exclusive_and_reusable(tmp_path):
    path = tmp_path / "unit.lock"
    with path.open("a+b") as first, path.open("a+b") as second:
        acquire_profile_lock(first)
        with pytest.raises(ProfileLockBusy):
            acquire_profile_lock(second)
        release_profile_lock(first)
        acquire_profile_lock(second)
        release_profile_lock(second)


def test_windows_chromium_lock_errors_fail_closed():
    assert classify_windows_chromium_lock_error(32) == "RUNNING"
    assert classify_windows_chromium_lock_error(33) == "RUNNING"
    assert classify_windows_chromium_lock_error(2) == "STOPPED"
    assert classify_windows_chromium_lock_error(5) == "UNVERIFIABLE"


def test_windows_profile_lock_uses_one_exclusive_byte(tmp_path, monkeypatch):
    locked = False

    def locking(_fd, mode, size):
        nonlocal locked
        assert size == 1
        if mode == 1:
            if locked:
                raise OSError("busy")
            locked = True
        else:
            locked = False

    fake_msvcrt = SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=locking)
    monkeypatch.setattr("xingtu.platform_runtime.sys.platform", "win32")
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    path = tmp_path / "unit.lock"
    with path.open("a+b") as first, path.open("a+b") as second:
        acquire_profile_lock(first)
        with pytest.raises(ProfileLockBusy):
            acquire_profile_lock(second)
        release_profile_lock(first)
        acquire_profile_lock(second)
        release_profile_lock(second)


def test_windows_private_paths_must_stay_under_userprofile(tmp_path, monkeypatch):
    user = tmp_path / "user"
    private = user / "runtime" / "unit.json"
    private.parent.mkdir(parents=True)
    private.touch()
    monkeypatch.setattr("xingtu.platform_runtime.sys.platform", "win32")
    monkeypatch.setenv("USERPROFILE", str(user))
    validate_windows_private_path(private)
    with pytest.raises(OSError, match="OUTSIDE_USERPROFILE"):
        validate_windows_private_path(tmp_path / "elsewhere.json")


def test_chrome_discovery_prefers_an_existing_explicit_path(tmp_path):
    chrome = tmp_path / "chrome"
    chrome.touch()
    assert discover_chrome_executable(chrome) == chrome.resolve()
    assert discover_chrome_executable(tmp_path / "missing") is None
