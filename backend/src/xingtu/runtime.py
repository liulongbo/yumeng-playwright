from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import subprocess
from contextlib import asynccontextmanager
from datetime import datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any, Literal

from playwright.async_api import BrowserContext, ProxySettings, async_playwright
from playwright.async_api import Error as BrowserError
from pydantic import Field, model_validator

from .covers import CoverConfig
from .domain import CollectorError, Model, NetworkMode, SegmentBudget, utcnow
from .evidence import EvidenceConfig


class UnitConfig(Model):
    """Execution unit binding.

    `network_mode` is explicit and fail-closed:

    - `production_line` (default): a bound proxy endpoint plus a valid `NetworkProof` and a fresh
      probe are mandatory, exactly as before this change.
    - `local_development`: the unit uses this machine's own egress for local verification with a
      project-private persistent profile. Proxy settings and a production `NetworkProof` are
      rejected, so a local unit can never be presented as a verified cellular line.
    """

    unit_id: str
    account_ref: str
    expected_account_id: str
    line_id: str
    profile_directory: Path
    registry_path: Path
    network_mode: NetworkMode = NetworkMode.PRODUCTION_LINE
    # Production-line binding.
    proxy_server: str | None = None
    proxy_username_env: str | None = None
    proxy_password_env: str | None = None
    network_evidence_path: Path | None = None
    network_probe_command: list[str] = Field(default_factory=list)
    # Local development binding: a real Chrome/Chromium executable is pinned by path and/or channel.
    browser_executable_path: Path | None = None
    browser_channel: Literal["chromium", "chrome", "chrome-beta", "msedge"] | None = None
    # Research captures may only open hosts explicitly listed here (see `xingtu research`).
    research_allowed_hosts: list[str] = Field(default_factory=list)
    # §13.4 main path is "the browser runs the platform's own scripts". The platform session
    # layer uses service workers for token refresh, so blocking them breaks the app: observed
    # on 2026-09-27 that a session created with `service_workers=block` stopped validating on
    # the next launch while an in-session login worked. Keep the platform behaviour by default.
    block_service_workers: bool = False
    headless: bool = False
    # Appendix A defaults; this configured budget is the ExecutionContext budget reference.
    budget: SegmentBudget = Field(default_factory=SegmentBudget)
    evidence: EvidenceConfig = Field(default_factory=EvidenceConfig)
    # F06 cover storage; `local` keeps covers under the project runtime root (Appendix A keeps
    # business snapshot covers for the long term, unlike 30/90-day evidence).
    covers: CoverConfig = Field(default_factory=CoverConfig)

    @model_validator(mode="after")
    def mode_binding(self) -> UnitConfig:
        if self.network_mode == NetworkMode.PRODUCTION_LINE:
            if not self.proxy_server:
                raise ValueError("production_line unit requires proxy_server")
            if not self.network_evidence_path:
                raise ValueError("production_line unit requires network_evidence_path")
            if not self.network_probe_command:
                raise ValueError("production_line unit requires network_probe_command")
        else:
            if self.proxy_server:
                # A local unit must not silently route through (or be confused with) a bound line.
                raise ValueError("local_development unit must not configure proxy_server")
            if self.network_evidence_path or self.network_probe_command:
                raise ValueError(
                    "local_development unit must not carry a production NetworkProof or probe"
                )
        if self.browser_channel and self.browser_executable_path:
            raise ValueError("configure either browser_channel or browser_executable_path")
        return self

    @property
    def is_local_development(self) -> bool:
        return self.network_mode == NetworkMode.LOCAL_DEVELOPMENT


class NetworkProof(Model):
    line_id: str
    unit_id: str
    proxy_server: str
    dns_bound: bool
    disconnect_blocks_direct: bool
    worker_egress_enforced: bool
    verified_at: datetime
    valid_until: datetime
    evidence_refs: list[str] = Field(min_length=1)


class NetworkProbe(Model):
    line_id: str
    healthy: bool
    egress_enforced: bool
    observed_at: datetime


def local_network_attestation(config: UnitConfig) -> dict[str, Any]:
    """Explicit local-mode marker. Deliberately not a `NetworkProof` and never line evidence."""
    return {
        "network_mode": NetworkMode.LOCAL_DEVELOPMENT.value,
        "line_id": config.line_id,
        "proxy_configured": bool(config.proxy_server),
        "egress": "local_machine",
        "attested_at": utcnow().isoformat(),
    }


async def ensure_line(config: UnitConfig) -> None:
    if config.is_local_development:
        # Local development: the only real precondition is that no bound line/proxy is involved.
        if config.proxy_server:
            raise CollectorError("RESOURCE_UNAVAILABLE", "LOCAL_MODE_MUST_NOT_USE_PROXY")
        return
    assert config.proxy_server and config.network_evidence_path
    try:
        proof = NetworkProof.model_validate_json(config.network_evidence_path.read_text())
        if (
            proof.line_id != config.line_id
            or proof.unit_id != config.unit_id
            or proof.proxy_server != config.proxy_server
            or not proof.dns_bound
            or not proof.disconnect_blocks_direct
            or not proof.worker_egress_enforced
            or proof.valid_until <= utcnow()
            or proof.verified_at > utcnow()
        ):
            raise CollectorError("RESOURCE_UNAVAILABLE", "NETWORK_PROOF_INVALID")
        process = await asyncio.create_subprocess_exec(
            *config.network_probe_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(), 10)
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        if process.returncode != 0 or len(output) > 8192:
            raise CollectorError("RESOURCE_UNAVAILABLE", "LINE_PROBE_FAILED")
        probe = NetworkProbe.model_validate_json(output)
        age = (utcnow() - probe.observed_at).total_seconds()
        if (
            probe.line_id != config.line_id
            or not probe.healthy
            or not probe.egress_enforced
            or not 0 <= age <= 30
        ):
            raise CollectorError("RESOURCE_UNAVAILABLE", "LINE_UNHEALTHY")
    except (OSError, ValueError, TimeoutError) as exc:
        raise CollectorError("RESOURCE_UNAVAILABLE", "LINE_VERIFICATION_UNAVAILABLE") from exc


def check_private(path: Path) -> None:
    if path.stat().st_mode & 0o077:
        raise CollectorError("RESOURCE_UNAVAILABLE", "PRIVATE_FILE_PERMISSIONS_REQUIRED")


def browser_executable_version(path: Path) -> str | None:
    """Best-effort real version of a pinned Chrome/Chromium executable; never guessed."""
    try:
        result = subprocess.run(
            [str(path), "--version"], capture_output=True, text=True, timeout=20, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (result.stdout or result.stderr or "").strip()
    if not text:
        return None
    parts = text.split()
    return parts[-1] if parts else None


class BrowserRuntime:
    def __init__(self, config: UnitConfig, private_root: Path):
        self.config, self.private_root = config, private_root.resolve()
        self.stopped = True
        self.browser_version: str | None = None
        self.browser_ua: str | None = None
        self.proxied = False
        self.network_mode = config.network_mode

    @property
    def launch_args(self) -> list[str]:
        return [
            "--disable-quic",
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-position=60,60",
            "--window-size=1440,960",
        ]

    @property
    def environment_hash(self) -> str:
        """Non-secret fingerprint of the client environment used for session comparisons."""
        payload = {
            "browser_version": self.browser_version,
            "user_agent": self.browser_ua,
            "headless": self.config.headless,
            "executable": str(self.config.browser_executable_path)
            if self.config.browser_executable_path
            else None,
            "channel": self.config.browser_channel,
            "service_workers": "block" if self.config.block_service_workers else "allow",
            "args": self.launch_args,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def _launch_options(self) -> dict[str, Any]:
        config = self.config
        if config.browser_executable_path:
            path = config.browser_executable_path
            if not path.is_file() or not os.access(path, os.X_OK):
                raise CollectorError("RESOURCE_UNAVAILABLE", "BROWSER_EXECUTABLE_NOT_RUNNABLE")
        options: dict[str, Any] = {"headless": config.headless, "accept_downloads": False}
        if not config.headless:
            # Manual maintenance/log-in is easier in a real window sized by the OS, not a
            # fixed 1280x720 viewport.
            options["no_viewport"] = True
        if config.browser_executable_path:
            options["executable_path"] = str(config.browser_executable_path)
        elif config.browser_channel:
            options["channel"] = config.browser_channel
        return options

    @asynccontextmanager
    async def open(self) -> Any:
        config = self.config
        profile = config.profile_directory.resolve()
        if not profile.is_relative_to(self.private_root) or profile == self.private_root:
            raise CollectorError("RESOURCE_UNAVAILABLE", "PROFILE_OUTSIDE_PROJECT_PRIVATE_ROOT")
        await ensure_line(config)
        profile.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(profile, 0o700)
        lock_path = profile.parent / (profile.name + ".lock")
        with lock_path.open("a") as lock:
            os.chmod(lock_path, 0o600)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise CollectorError("RESOURCE_UNAVAILABLE", "PROFILE_IN_USE") from exc
            proxy: ProxySettings | None = None
            if not config.is_local_development:
                assert config.proxy_server
                proxy = {"server": config.proxy_server}
                for key, env_name in [
                    ("username", config.proxy_username_env),
                    ("password", config.proxy_password_env),
                ]:
                    if env_name:
                        if not os.environ.get(env_name):
                            raise CollectorError(
                                "RESOURCE_UNAVAILABLE", "PROXY_CREDENTIAL_REF_MISSING"
                            )
                        if key == "username":
                            proxy["username"] = os.environ[env_name]
                        else:
                            proxy["password"] = os.environ[env_name]
            self.proxied = proxy is not None
            browser: BrowserContext | None = None
            self.stopped = False
            try:
                async with async_playwright() as playwright:
                    sw_policy: Literal["allow", "block"] = (
                        "block" if config.block_service_workers else "allow"
                    )
                    try:
                        options = self._launch_options()
                        browser = await playwright.chromium.launch_persistent_context(
                            str(profile),
                            proxy=proxy,
                            service_workers=sw_policy,
                            args=self.launch_args,
                            **options,
                        )
                        if browser.browser:
                            self.browser_version = browser.browser.version
                        try:
                            probe_page = (
                                browser.pages[0] if browser.pages else await browser.new_page()
                            )
                            self.browser_ua = await probe_page.evaluate("navigator.userAgent")
                        except BrowserError:
                            self.browser_ua = None
                        yield browser
                    finally:
                        if browser:
                            await close_browser_context(browser)
                            self.stopped = True
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


async def close_browser_context(browser: BrowserContext, timeout_seconds: float = 20.0) -> None:
    """Close a persistent context within a fixed bound.

    A close acknowledgement is part of execution-unit isolation.  If Chromium or the
    Playwright transport hangs, callers must keep ``browser_stopped=false`` and quarantine the
    unit instead of releasing the profile as reusable.
    """
    try:
        await asyncio.wait_for(browser.close(), timeout=timeout_seconds)
    except TimeoutError as exc:
        raise CollectorError("RESOURCE_UNAVAILABLE", "BROWSER_CLOSE_TIMEOUT") from exc


def load_unit(path: Path) -> UnitConfig:
    check_private(path)
    return UnitConfig.model_validate(json.loads(path.read_text()))


def confirm_local_browser_stopped(config: UnitConfig, private_root: Path) -> None:
    """Conservative local-only isolation check. Never kills an unverified process.

    The project lock proves no BrowserHost owns the profile.  Chromium's SingletonLock supplies
    a second, independent PID signal without relying on process-list permission.  A stale
    SingletonLock whose PID no longer exists is evidence of an unclean exit, not a live browser.
    """
    profile = config.profile_directory.resolve()
    if not profile.is_relative_to(private_root.resolve()):
        raise CollectorError("RESOURCE_UNAVAILABLE", "PROFILE_OUTSIDE_PROJECT_PRIVATE_ROOT")
    if not profile.parent.exists():
        raise CollectorError("RESOURCE_UNAVAILABLE", "PROFILE_NOT_CREATED")
    with (profile.parent / (profile.name + ".lock")).open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CollectorError("RESOURCE_UNAVAILABLE", "PROFILE_STILL_IN_USE") from exc
        try:
            singleton = profile / "SingletonLock"
            if singleton.exists() or singleton.is_symlink():
                try:
                    target = (
                        os.readlink(singleton) if singleton.is_symlink() else singleton.read_text()
                    )
                    pid_text = target.rsplit("-", 1)[-1].strip()
                    pid = int(pid_text)
                except (OSError, ValueError) as exc:
                    raise CollectorError(
                        "RESOURCE_UNAVAILABLE", "SINGLETON_LOCK_UNREADABLE"
                    ) from exc
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    pass
                except PermissionError as exc:
                    raise CollectorError(
                        "RESOURCE_UNAVAILABLE", "SINGLETON_PROCESS_UNVERIFIABLE"
                    ) from exc
                else:
                    raise CollectorError("RESOURCE_UNAVAILABLE", "OLD_PROCESS_STILL_VISIBLE")
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


async def browser_compatibility_report(config: UnitConfig, private_root: Path) -> dict[str, Any]:
    """Launch the configured real browser once and record the executable actually used."""
    try:
        playwright_version: str | None = package_version("playwright")
    except PackageNotFoundError:
        playwright_version = None
    runtime = BrowserRuntime(config.model_copy(update={"headless": True}), private_root)
    result: dict[str, Any] = {
        "network_mode": config.network_mode.value,
        "proxy_configured": bool(config.proxy_server),
        "browser_channel": config.browser_channel,
        "browser_executable_path": str(config.browser_executable_path)
        if config.browser_executable_path
        else None,
        "executable_reported_version": browser_executable_version(config.browser_executable_path)
        if config.browser_executable_path
        else None,
        "playwright_version": playwright_version,
    }
    async with runtime.open() as browser:
        result["launch_ok"] = True
        result["playwright_reported_version"] = runtime.browser_version
        result["user_agent"] = runtime.browser_ua
        result["profile_directory"] = str(config.profile_directory.resolve())
        page = await browser.new_page()
        result["page_opened"] = page is not None
        await page.close()
    result["browser_stopped"] = runtime.stopped
    return result
