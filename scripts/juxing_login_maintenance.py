"""Keep the dedicated Juxing Chrome context open for an operator login.

This stage-B helper owns the BrowserRuntime for its whole lifetime.  It does not expose CDP,
touch the business database, or drive any platform write operation.  A verified session is
saved only to the platform-specific private storage-state path already managed by
``BrowserRuntime``; the Chrome window remains open until the stop file appears or the bounded
maintenance window expires.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from xingtu.adapter import BrowserAdapter  # noqa: E402
from xingtu.contracts import PlatformRegistry, bind_account_to_url  # noqa: E402
from xingtu.domain import PlatformId, SessionHealthStatus  # noqa: E402
from xingtu.platform_runtime import apply_private_permissions  # noqa: E402
from xingtu.runtime import BrowserRuntime, load_unit  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="磁力聚星阶段 B 持久人工登录窗口")
    parser.add_argument("--config", type=Path, required=True, help="私有执行单元配置")
    parser.add_argument("--private-root", type=Path, default=ROOT / ".runtime")
    parser.add_argument(
        "--status-file",
        type=Path,
        default=ROOT / ".runtime" / "juxing-maintenance" / "status.json",
    )
    parser.add_argument(
        "--stop-file",
        type=Path,
        default=ROOT / ".runtime" / "juxing-maintenance" / "stop",
    )
    parser.add_argument("--seconds", type=int, default=8 * 60 * 60)
    return parser.parse_args()


def write_status(path: Path, **values: Any) -> None:
    """Atomically publish non-secret maintenance state for a later agent turn."""

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    apply_private_permissions(path.parent, 0o700)
    payload = {
        "schema_version": "juxing_login_maintenance.v1",
        "observed_at": datetime.now(UTC).isoformat(),
        **values,
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    apply_private_permissions(temporary, 0o600)
    temporary.replace(path)


async def run(options: argparse.Namespace) -> int:
    if options.seconds <= 0:
        raise ValueError("--seconds must be positive")
    config = load_unit(options.config).for_platform(PlatformId.KUAISHOU_JUXING)
    registry = PlatformRegistry.model_validate_json(config.registry_path.read_text())
    registry.require_enabled(live=True)
    runtime = BrowserRuntime(config.model_copy(update={"headless": False}), options.private_root)

    options.stop_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    apply_private_permissions(options.stop_file.parent, 0o700)
    if options.stop_file.exists():
        write_status(
            options.status_file,
            state="STOPPED",
            pid=os.getpid(),
            platform=config.active_platform.value,
            profile=str(config.profile_directory),
            stop_reason="PREEXISTING_STOP_FILE",
            snapshot_saved=False,
        )
        return 0

    write_status(
        options.status_file,
        state="STARTING",
        pid=os.getpid(),
        platform=config.active_platform.value,
        profile=str(config.profile_directory),
        snapshot_saved=False,
    )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + options.seconds
    verified = False
    snapshot_saved = False
    last_state: tuple[str, str] | None = None

    try:
        async with runtime.open() as browser:
            page = browser.pages[0] if browser.pages else await browser.new_page()
            session = registry.session
            search = registry.search
            assert session is not None and search is not None
            if page.url == "about:blank":
                await page.goto(
                    bind_account_to_url(
                        search.entry_url,
                        session.account_url_parameter,
                        config.expected_account_id,
                    ),
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )

            adapter = BrowserAdapter(
                browser,
                registry,
                config.expected_account_id,
                guard=lambda: asyncio.sleep(0),
                live=True,
                manually_attested_account_id=config.manually_attested_account_id,
            )
            write_status(
                options.status_file,
                state="WAITING_FOR_OPERATOR",
                pid=os.getpid(),
                platform=config.active_platform.value,
                profile=str(config.profile_directory),
                snapshot_saved=False,
                current_url=page.url,
            )

            while loop.time() < deadline and not options.stop_file.exists():
                open_pages = [candidate for candidate in browser.pages if not candidate.is_closed()]
                if open_pages:
                    page = open_pages[-1]
                else:
                    page = await browser.new_page()
                    await page.goto(
                        bind_account_to_url(
                            search.entry_url,
                            session.account_url_parameter,
                            config.expected_account_id,
                        ),
                        wait_until="domcontentloaded",
                        timeout=60_000,
                    )

                health = await adapter.inspect_session(page, timeout=2.0)
                current = (health.status.value, health.evidence_reason)
                if current != last_state:
                    verified = health.status == SessionHealthStatus.VALID
                    account_match = bool(
                        verified and health.observed_account_id == config.expected_account_id
                    )
                    if account_match:
                        snapshot_saved = await runtime.export_session_snapshot(browser)
                    write_status(
                        options.status_file,
                        state="VERIFIED_WINDOW_OPEN" if account_match else "WAITING_FOR_OPERATOR",
                        pid=os.getpid(),
                        platform=config.active_platform.value,
                        profile=str(config.profile_directory),
                        session_status=health.status.value,
                        evidence_reason=health.evidence_reason,
                        protected_page_verified=health.protected_page_verified,
                        account_match=account_match,
                        snapshot_saved=snapshot_saved,
                        current_url=page.url,
                    )
                    last_state = current
                await asyncio.sleep(2.0)

            stop_reason = "STOP_FILE" if options.stop_file.exists() else "MAINTENANCE_TIMEOUT"
            if verified:
                snapshot_saved = await runtime.export_session_snapshot(browser)
            write_status(
                options.status_file,
                state="CLOSING",
                pid=os.getpid(),
                platform=config.active_platform.value,
                profile=str(config.profile_directory),
                stop_reason=stop_reason,
                snapshot_saved=snapshot_saved,
            )
    except Exception as exc:  # noqa: BLE001 - persist a bounded operational failure for handoff
        write_status(
            options.status_file,
            state="FAILED",
            pid=os.getpid(),
            platform=config.active_platform.value,
            profile=str(config.profile_directory),
            error_type=type(exc).__name__,
            error=str(exc),
            snapshot_saved=snapshot_saved,
        )
        raise

    write_status(
        options.status_file,
        state="STOPPED",
        pid=os.getpid(),
        platform=config.active_platform.value,
        profile=str(config.profile_directory),
        snapshot_saved=snapshot_saved,
    )
    return 0


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
