"""Small OS adapter for local browser/profile ownership.

Business code must not infer execution ownership from process names.  This module only provides
the two host primitives needed by ``BrowserRuntime``: a project-owned profile lock and a
conservative Chromium-process check after that project lock has been released.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import BinaryIO, Literal


class ProfileLockBusy(OSError):
    """Another project process currently owns the execution-unit profile."""


def apply_private_permissions(path: Path, mode: int) -> None:
    """Apply POSIX private modes; Windows keeps the directory's inherited user ACL.

    Windows ``chmod`` only toggles the read-only bit and cannot express an owner-only ACL.  The
    Windows local-runtime preflight therefore requires the runtime root to live below the current
    user's profile and rejects reparse-point config/profile paths instead of pretending POSIX mode
    bits provide protection there.
    """

    if sys.platform != "win32":
        os.chmod(path, mode)


def validate_windows_private_path(path: Path) -> None:
    if sys.platform != "win32":
        return
    resolved = path.resolve()
    user_profile = os.environ.get("USERPROFILE")
    if not user_profile:
        raise OSError("WINDOWS_USERPROFILE_UNAVAILABLE")
    user_root = Path(user_profile).resolve()
    try:
        resolved.relative_to(user_root)
    except ValueError as exc:
        raise OSError("WINDOWS_PRIVATE_PATH_OUTSIDE_USERPROFILE") from exc
    # ``Path.is_symlink()`` does not cover every Windows junction/reparse point.  Inspect the
    # target and each existing parent up to USERPROFILE without following the metadata lookup.
    candidate = path
    while True:
        if candidate.exists() or candidate.is_symlink():
            attributes = getattr(candidate.lstat(), "st_file_attributes", 0)
            if candidate.is_symlink() or attributes & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
                raise OSError("WINDOWS_PRIVATE_PATH_REPARSE_POINT")
        if candidate == user_root or candidate.parent == candidate:
            break
        candidate = candidate.parent


def acquire_profile_lock(handle: BinaryIO) -> None:
    """Acquire one non-blocking byte-range lock for the lifetime of ``handle``."""

    if sys.platform == "win32":
        import msvcrt

        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise ProfileLockBusy from exc
        return

    import fcntl

    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise ProfileLockBusy from exc


def release_profile_lock(handle: BinaryIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle, fcntl.LOCK_UN)


def windows_chromium_lock_state(profile: Path) -> Literal["STOPPED", "RUNNING", "UNVERIFIABLE"]:
    """Probe Chromium's Windows delete-on-close ``lockfile`` without modifying it."""

    if sys.platform != "win32":
        raise RuntimeError("windows_chromium_lock_state is Windows-only")

    import ctypes
    from ctypes import wintypes

    lockfile = profile / "lockfile"
    if not lockfile.exists():
        return "STOPPED"

    create_file = ctypes.WinDLL("kernel32", use_last_error=True).CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    generic_write = 0x40000000
    file_share_read = 0x00000001
    open_existing = 3
    file_attribute_normal = 0x00000080
    invalid_handle = wintypes.HANDLE(-1).value
    handle = create_file(
        str(lockfile),
        generic_write,
        file_share_read,
        None,
        open_existing,
        file_attribute_normal,
        None,
    )
    if handle == invalid_handle:
        return classify_windows_chromium_lock_error(ctypes.get_last_error())
    close_handle(handle)
    return "STOPPED"


def classify_windows_chromium_lock_error(
    error: int,
) -> Literal["STOPPED", "RUNNING", "UNVERIFIABLE"]:
    if error in {32, 33}:  # sharing/lock violation: Chromium still owns the handle
        return "RUNNING"
    if error in {2, 3}:  # raced normal browser shutdown and delete-on-close
        return "STOPPED"
    return "UNVERIFIABLE"


def chrome_candidates() -> list[Path]:
    """Ordered system Chrome Stable candidates; no daily/default profile is involved."""

    if sys.platform == "darwin":
        return [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ]
    if sys.platform == "win32":
        roots = [
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        ]
        return [Path(root) / "Google/Chrome/Application/chrome.exe" for root in roots if root]
    return [
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/google-chrome-stable"),
        Path("/opt/google/chrome/google-chrome"),
    ]


def discover_chrome_executable(explicit: Path | None = None) -> Path | None:
    candidates = [explicit] if explicit else chrome_candidates()
    return next((path.resolve() for path in candidates if path and path.is_file()), None)
