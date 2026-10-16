from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playwright.async_api import Error as BrowserError

from .adapter import BrowserAdapter
from .contracts import PlatformRegistry
from .domain import CollectorError
from .runtime import BrowserRuntime, UnitConfig, browser_executable_version


def value_hmac(secret: bytes, value: str) -> str:
    return hmac.new(secret, value.encode(), hashlib.sha256).hexdigest()


def executable_sha256(path: Path | None) -> str | None:
    if not path or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def profile_file_metadata(profile: Path) -> list[dict[str, Any]]:
    paths = [
        profile / "Default" / "Cookies",
        profile / "Default" / "Local Storage",
        profile / "Default" / "Session Storage",
        profile / "Default" / "IndexedDB",
        profile / "Local State",
        profile / "Default" / "Preferences",
    ]
    result = []
    for path in paths:
        if not path.exists():
            result.append({"path": str(path.relative_to(profile)), "exists": False})
            continue
        stat = path.stat()
        result.append(
            {
                "path": str(path.relative_to(profile)),
                "exists": True,
                "kind": "directory" if path.is_dir() else "file",
                "size": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
            }
        )
    return result


async def browser_storage_summary(page: Any, secret: bytes) -> dict[str, Any]:
    raw = await page.evaluate(
        """async () => {
          const pairs = (storage) => Object.keys(storage).sort()
            .map((key) => [key, storage.getItem(key)]);
          let databases = [];
          try {
            const infos = await indexedDB.databases();
            for (const info of infos) {
              if (!info.name) continue;
              const db = await new Promise((resolve, reject) => {
                const request = indexedDB.open(info.name);
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
              });
              const stores = [];
              for (const name of Array.from(db.objectStoreNames)) {
                const count = await new Promise((resolve) => {
                  try {
                    const tx = db.transaction(name, 'readonly');
                    const request = tx.objectStore(name).count();
                    request.onsuccess = () => resolve(request.result);
                    request.onerror = () => resolve(null);
                  } catch (_) { resolve(null); }
                });
                stores.push({name, count});
              }
              databases.push({name: info.name, version: info.version, stores});
              db.close();
            }
          } catch (_) { databases = []; }
          return {
            origin: location.origin,
            localStorage: pairs(localStorage),
            sessionStorage: pairs(sessionStorage),
            indexedDB: databases,
            userAgent: navigator.userAgent,
            clientHints: navigator.userAgentData ? {
              brands: navigator.userAgentData.brands,
              mobile: navigator.userAgentData.mobile,
              platform: navigator.userAgentData.platform,
            } : null,
            locale: navigator.language,
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
          };
        }"""
    )

    def hashed(items: list[list[str | None]]) -> list[dict[str, str]]:
        return [
            {"key": key, "value_hmac": value_hmac(secret, value or "")}
            for key, value in items
            if key is not None
        ]

    return {
        "origin": raw["origin"],
        "local_storage": hashed(raw["localStorage"]),
        "session_storage": hashed(raw["sessionStorage"]),
        "indexed_db": raw["indexedDB"],
        "user_agent": raw["userAgent"],
        "client_hints": raw["clientHints"],
        "locale": raw["locale"],
        "timezone": raw["timezone"],
    }


async def run_session_diagnostics(
    config: UnitConfig,
    private_root: Path,
    output_root: Path,
) -> Path:
    """Cold-start one persistent profile and write a local, non-plaintext observation."""
    secret_text = os.environ.get("XINGTU_DIAGNOSTIC_HMAC_KEY")
    if not secret_text:
        raise CollectorError("INVALID_FORM", "XINGTU_DIAGNOSTIC_HMAC_KEY_REQUIRED")
    secret = secret_text.encode()
    if len(secret) < 32:
        raise CollectorError("INVALID_FORM", "DIAGNOSTIC_HMAC_KEY_TOO_SHORT")
    registry = PlatformRegistry.model_validate_json(config.registry_path.read_text())
    registry.require_enabled(live=True)
    if not registry.search:
        raise CollectorError("PLATFORM_PAGE_CHANGED", "MISSING_SEARCH_CONTRACT")
    runtime = BrowserRuntime(config.model_copy(update={"headless": False}), private_root)
    health = None
    cookies: list[dict[str, Any]] = []
    storage: dict[str, Any] = {}
    async with runtime.open() as browser:
        page = browser.pages[0] if browser.pages else await browser.new_page()
        await page.goto(registry.search.entry_url, wait_until="domcontentloaded")
        adapter = BrowserAdapter(
            browser,
            registry,
            config.expected_account_id,
            lambda: _noop_guard(),
            live=True,
            manually_attested_account_id=config.manually_attested_account_id,
        )
        try:
            health = await adapter.inspect_session(page)
            if health.status.value == "VALID":
                await runtime.export_session_snapshot(browser)
            for cookie in await browser.cookies():
                cookies.append(
                    {
                        "name": cookie["name"],
                        "domain": cookie["domain"],
                        "path": cookie["path"],
                        "secure": cookie["secure"],
                        "http_only": cookie["httpOnly"],
                        "same_site": cookie["sameSite"],
                        "session": cookie["expires"] == -1,
                        "expires": cookie["expires"],
                        "last_update": None,
                        "value_hmac": value_hmac(secret, cookie["value"]),
                    }
                )
            try:
                storage = await browser_storage_summary(page, secret)
            except BrowserError:
                # Session health and the cookie inventory have already been observed.  A
                # platform-driven navigation can replace the execution context while the
                # optional storage summary is iterating IndexedDB; it must not discard the
                # whole diagnostic (or the snapshot already safely exported above).
                storage = {"unavailable_reason": "PAGE_CONTEXT_CHANGED"}
        finally:
            await adapter.close()
    assert health
    observed_at = datetime.now(UTC)
    output_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output_root, 0o700)
    path = output_root / f"{config.unit_id}-{observed_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    report = {
        "schema_version": "session-diagnostics.v1",
        "observed_at": observed_at.isoformat(),
        "unit_id": config.unit_id,
        "session_health": health.model_dump(mode="json"),
        "browser": {
            "playwright_reported_version": runtime.browser_version,
            "executable_reported_version": browser_executable_version(
                config.browser_executable_path
            )
            if config.browser_executable_path
            else None,
            "executable_sha256": executable_sha256(config.browser_executable_path),
            "environment_hash": runtime.environment_hash,
            "headless": config.headless,
            "launch_args": runtime.launch_args,
            "service_workers": "block" if config.block_service_workers else "allow",
            "normal_close_confirmed": runtime.stopped,
        },
        "profile": {
            "path": str(config.profile_directory.resolve()),
            "files": profile_file_metadata(config.profile_directory.resolve()),
        },
        "session_snapshot": {
            "restored_before_navigation": runtime.session_snapshot_restored,
            "captured_at": runtime.session_snapshot_captured_at,
        },
        "cookies": sorted(cookies, key=lambda item: (item["domain"], item["name"])),
        "storage": storage,
        "limitations": [
            "cookie last_update is unavailable through Playwright and is recorded as null",
            "only storage visible to the verified entry origin is summarized",
            "values are local HMACs and cannot be compared if the HMAC key changes",
        ],
    }
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return path


async def _noop_guard() -> None:
    return None
