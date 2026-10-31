from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any, Literal

from playwright.async_api import BrowserContext, ProxySettings, async_playwright
from playwright.async_api import Error as BrowserError
from pydantic import Field, model_validator

from .contracts import account_id_from_url
from .covers import CoverConfig
from .domain import CollectorError, Model, NetworkMode, PlatformId, SegmentBudget, utcnow
from .evidence import EvidenceConfig
from .platform_runtime import (
    ProfileLockBusy,
    acquire_profile_lock,
    apply_private_permissions,
    discover_chrome_executable,
    release_profile_lock,
    validate_windows_private_path,
    windows_chromium_lock_state,
)
from .request_census import RequestCensus, census_path_from_env


class ManualIdentityAttestation(Model):
    """Audited human confirmation for a unique account when the platform omits its ID from DOM."""

    account_id: str
    actor: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    approved_at: datetime
    valid_until: datetime

    @model_validator(mode="after")
    def time_window_is_valid(self) -> ManualIdentityAttestation:
        if self.approved_at.tzinfo is None or self.valid_until.tzinfo is None:
            raise ValueError("manual identity attestation timestamps must include a timezone")
        if self.valid_until <= self.approved_at:
            raise ValueError("manual identity attestation valid_until must be after approved_at")
        if self.valid_until - self.approved_at > timedelta(days=31):
            raise ValueError("manual identity attestation may not exceed 31 days")
        return self


class PlatformBindingConfig(Model):
    """One account/Profile/contract binding inside a shared logical execution unit."""

    platform: PlatformId
    account_ref: str = Field(min_length=1)
    expected_account_id: str = Field(min_length=1)
    profile_directory: Path
    registry_path: Path
    enabled: bool = True
    manual_identity_attestation: ManualIdentityAttestation | None = None

    @model_validator(mode="after")
    def attestation_matches(self) -> PlatformBindingConfig:
        if (
            self.manual_identity_attestation
            and self.manual_identity_attestation.account_id != self.expected_account_id
        ):
            raise ValueError("platform binding attestation must match expected_account_id")
        return self


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
    active_platform: PlatformId = PlatformId.DOUYIN_XINGTU
    # Empty keeps every existing unit file valid as a single Douyin Xingtu binding.
    platform_bindings: list[PlatformBindingConfig] = Field(default_factory=list)
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
    # Natural Chrome profiles on macOS encrypt cookies with the system Keychain. Playwright's
    # default --use-mock-keychain cannot decrypt those rows and Chromium removes the unusable
    # authentication cookies. This opt-in ignores only that one Playwright default argument.
    macos_system_keychain: bool = False
    # Hybrid persistence, part two: on top of the persistent profile directory, keep an explicit
    # storage-state snapshot of the last verified session inside the private runtime root and
    # re-inject it before the next launch's first navigation. This makes session-scoped business
    # cookies (e.g. `.xingtu.cn/star_sessionid`) survive a close whose disk flush is uncertain.
    capture_session_snapshot: bool = True
    # A deliberately narrow, time-bounded fallback for a platform UI that no longer renders an
    # account identifier. It is never inferred from a protected page: an operator must attest
    # the single-account binding explicitly, and normal readable-account mismatch detection
    # always wins over this fallback.
    manual_identity_attestation: ManualIdentityAttestation | None = None
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
        platforms = [binding.platform for binding in self.platform_bindings]
        if len(platforms) != len(set(platforms)):
            raise ValueError("platform bindings must be unique by platform")
        profiles = [binding.profile_directory for binding in self.platform_bindings]
        if len(profiles) != len(set(profiles)):
            raise ValueError("platform bindings must use distinct profile directories")
        if self.manual_identity_attestation:
            if not self.is_local_development:
                raise ValueError("manual identity attestation is limited to local_development")
            if self.manual_identity_attestation.account_id != self.expected_account_id:
                raise ValueError("manual identity attestation must match expected_account_id")
        return self

    def binding_for(self, platform: PlatformId | str) -> PlatformBindingConfig:
        requested = PlatformId(platform)
        for binding in self.platform_bindings:
            if binding.platform == requested:
                if not binding.enabled:
                    raise CollectorError("RESOURCE_UNAVAILABLE", "PLATFORM_BINDING_DISABLED")
                return binding
        if requested == PlatformId.DOUYIN_XINGTU:
            return PlatformBindingConfig(
                platform=requested,
                account_ref=self.account_ref,
                expected_account_id=self.expected_account_id,
                profile_directory=self.profile_directory,
                registry_path=self.registry_path,
                manual_identity_attestation=self.manual_identity_attestation,
            )
        raise CollectorError("RESOURCE_UNAVAILABLE", "PLATFORM_BINDING_NOT_CONFIGURED")

    def for_platform(self, platform: PlatformId | str) -> UnitConfig:
        """Return a validated active binding while reusing line and browser-host settings."""

        binding = self.binding_for(platform)
        data = self.model_dump()
        data.update(
            active_platform=binding.platform,
            account_ref=binding.account_ref,
            expected_account_id=binding.expected_account_id,
            profile_directory=binding.profile_directory,
            registry_path=binding.registry_path,
            manual_identity_attestation=binding.manual_identity_attestation,
        )
        return UnitConfig.model_validate(data)

    @property
    def is_local_development(self) -> bool:
        return self.network_mode == NetworkMode.LOCAL_DEVELOPMENT

    @property
    def manually_attested_account_id(self) -> str | None:
        """Return only a currently valid, exact, local-development attestation."""
        attestation = self.manual_identity_attestation
        if not attestation or attestation.valid_until <= utcnow():
            return None
        return attestation.account_id


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
    if sys.platform == "win32":
        try:
            validate_windows_private_path(path)
        except OSError as exc:
            raise CollectorError("RESOURCE_UNAVAILABLE", str(exc)) from exc
        return
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
        self.browser_executable_path = (
            discover_chrome_executable(config.browser_executable_path)
            if config.browser_executable_path or not config.browser_channel
            else None
        )
        # Hybrid persistence bookkeeping (see the snapshot section below).
        self._context: BrowserContext | None = None
        self._snapshot_task: asyncio.Task[None] | None = None
        self.session_snapshot_restored = False
        self.session_snapshot_captured_at: str | None = None
        self.snapshot_debounce_seconds = 4.0
        self.protected_ready_selector: str | None = None
        self.account_selector: str | None = None
        self.account_url_parameter: str | None = None

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
            "executable": str(self.browser_executable_path)
            if self.browser_executable_path
            else None,
            "channel": self.config.browser_channel,
            "service_workers": "block" if self.config.block_service_workers else "allow",
            "keychain": "system" if self.config.macos_system_keychain else "playwright-default",
            "args": self.launch_args,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def _launch_options(self) -> dict[str, Any]:
        config = self.config
        if config.browser_executable_path and not self.browser_executable_path:
            raise CollectorError("RESOURCE_UNAVAILABLE", "BROWSER_EXECUTABLE_NOT_FOUND")
        if self.browser_executable_path:
            path = self.browser_executable_path
            if not path.is_file() or not os.access(path, os.X_OK):
                raise CollectorError("RESOURCE_UNAVAILABLE", "BROWSER_EXECUTABLE_NOT_RUNNABLE")
        options: dict[str, Any] = {"headless": config.headless, "accept_downloads": False}
        if not config.headless:
            # Manual maintenance/log-in is easier in a real window sized by the OS, not a
            # fixed 1280x720 viewport.
            options["no_viewport"] = True
        if self.browser_executable_path:
            options["executable_path"] = str(self.browser_executable_path)
        elif config.browser_channel:
            options["channel"] = config.browser_channel
        if config.macos_system_keychain:
            if sys.platform != "darwin" or not self.browser_executable_path:
                raise CollectorError(
                    "RESOURCE_UNAVAILABLE", "SYSTEM_KEYCHAIN_REQUIRES_MACOS_EXECUTABLE"
                )
            options["ignore_default_args"] = ["--use-mock-keychain"]
        return options

    # --- Hybrid persistence: persistent profile directory + explicit storage-state snapshot -----
    #
    # Why both halves are needed:
    # * The persistent directory keeps non-session cookies, localStorage and IndexedDB across
    #   launches, and macOS Keychain decrypts those rows (``macos_system_keychain``).
    # * The platform's *business* session lives in session-scoped cookies such as
    #   `.xingtu.cn/star_sessionid` (observed 2026-10-06: ``is_persistent=0``,
    #   ``has_expires=0``).  Whether Chromium's crash-restore writes those rows back to disk is
    #   timing dependent, which matches the observed "sometimes still logged in, sometimes
    #   redirected to the login page" behaviour in the same profile.  A storage-state snapshot
    #   taken while the session is verified makes that state explicit and re-injectable.
    #
    # Both the snapshot and its directory hold live credentials, so they stay inside the private
    # runtime root with ``0600``/``0700`` permissions and never leave the execution unit.

    @property
    def session_snapshot_path(self) -> Path:
        # Preserve the established Douyin filename exactly. Additional platform bindings share
        # the logical unit id but must never overwrite Douyin's cookies/local storage.
        platform_suffix = (
            ""
            if self.config.active_platform == PlatformId.DOUYIN_XINGTU
            else f".{self.config.active_platform.value}"
        )
        return self.private_root / "storage-state" / f"{self.config.unit_id}{platform_suffix}.json"

    def session_snapshot_available(self) -> bool:
        path = self.session_snapshot_path
        return path.is_file() and path.stat().st_size > 0

    async def export_session_snapshot(self, context: BrowserContext) -> bool:
        """Persist the full cookie jar + local storage of a verified session. Never raises."""
        if not self.config.capture_session_snapshot:
            return False
        try:
            state = await context.storage_state()
        except Exception:  # noqa: BLE001 - persistence must not break a verified session
            return False
        path = self.session_snapshot_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            apply_private_permissions(path.parent, 0o700)
            temporary = path.with_suffix(".tmp")
            captured_at = datetime.now(UTC).isoformat()
            payload: dict[str, Any] = {
                "schema_version": "session_snapshot.v1",
                "unit_id": self.config.unit_id,
                "captured_at": captured_at,
                "storage_state": state,
            }
            temporary.write_text(json.dumps(payload, ensure_ascii=False))
            apply_private_permissions(temporary, 0o600)
            temporary.replace(path)
        except OSError:
            return False
        self.session_snapshot_captured_at = captured_at
        return True

    async def _restore_session_snapshot(self, context: BrowserContext) -> bool:
        if not self.config.capture_session_snapshot or not self.session_snapshot_available():
            return False
        try:
            payload = json.loads(self.session_snapshot_path.read_text())
            state = payload["storage_state"]
            await context.add_cookies(state.get("cookies") or [])
            for origin in state.get("origins") or []:
                entries = origin.get("localStorage") or []
                if not entries:
                    continue
                restored = json.dumps({item["name"]: item["value"] for item in entries})
                await context.add_init_script(
                    "(() => { const data = "
                    + restored
                    + "; for (const [k, v] of Object.entries(data)) "
                    "window.localStorage.setItem(k, v); })()"
                )
        except (OSError, ValueError, KeyError, TypeError):
            return False
        self.session_snapshot_restored = True
        return True

    def _on_frame_navigated(self, frame: Any) -> None:
        """Schedule a snapshot capture after a successful navigation on a top-level frame."""
        if not self.config.capture_session_snapshot or frame.parent_frame is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._snapshot_task and not self._snapshot_task.done():
            return
        self._snapshot_task = loop.create_task(self._capture_after_navigation(frame))

    async def _capture_after_navigation(self, frame: Any) -> None:
        await asyncio.sleep(self.snapshot_debounce_seconds)
        context = self._context
        if context is None:
            return
        page = getattr(frame, "page", None)
        if page is not None and not await self._session_looks_verified(page):
            # Redirected to a public/login surface: this is not a verified session and capturing it
            # would persist a broken state over a good snapshot.  A creator detail page carries no
            # navigation menu, so the account locator is accepted as the second registered signal;
            # matched to the bound identity it cannot be a public page.
            return
        await self.export_session_snapshot(context)

    async def _session_looks_verified(self, page: Any) -> bool:
        """True only when a registry-registered signal proves the bound session is live."""
        if self.protected_ready_selector:
            try:
                if await page.locator(self.protected_ready_selector).count():
                    if self.account_url_parameter:
                        return (
                            account_id_from_url(page.url, self.account_url_parameter)
                            == self.config.expected_account_id
                        )
                    return True
            except Exception:  # noqa: BLE001
                return False
        if not self.account_selector or not self.config.expected_account_id:
            return False
        try:
            locator = page.locator(self.account_selector)
            if await locator.count() != 1:
                return False
            raw = (await locator.first.text_content(timeout=2000) or "").strip()
        except Exception:  # noqa: BLE001
            return False
        return bool(raw) and raw == self.config.expected_account_id

    @asynccontextmanager
    async def open(self) -> Any:
        config = self.config
        profile = config.profile_directory.resolve()
        if not profile.is_relative_to(self.private_root) or profile == self.private_root:
            raise CollectorError("RESOURCE_UNAVAILABLE", "PROFILE_OUTSIDE_PROJECT_PRIVATE_ROOT")
        try:
            validate_windows_private_path(profile)
        except OSError as exc:
            raise CollectorError("RESOURCE_UNAVAILABLE", str(exc)) from exc
        await ensure_line(config)
        profile.mkdir(parents=True, exist_ok=True, mode=0o700)
        apply_private_permissions(profile, 0o700)
        lock_path = profile.parent / (profile.name + ".lock")
        with lock_path.open("a+b") as lock:
            apply_private_permissions(lock_path, 0o600)
            try:
                acquire_profile_lock(lock)
            except ProfileLockBusy as exc:
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
            # DIAG-01: opt-in request census. Inert unless XINGTU_REQUEST_CENSUS is set, so the
            # default execution path attaches no listeners and behaves exactly as before.
            census: RequestCensus | None = None
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
                        self._context = browser
                        self.protected_ready_selector = _protected_ready_selector(config)
                        self.account_selector = _account_selector(config)
                        self.account_url_parameter = _account_url_parameter(config)
                        # Hybrid persistence: the persistent directory keeps non-session cookies,
                        # localStorage and IndexedDB, while an explicit storage-state snapshot
                        # re-injects the whole cookie jar (including session-scoped cookies the
                        # platform issues, e.g. `.xingtu.cn/star_sessionid`) on the next launch.
                        # The snapshot is applied before the first navigation, so the very first
                        # request the platform sees already carries the verified session.
                        await self._restore_session_snapshot(browser)
                        try:
                            probe_page = (
                                browser.pages[0] if browser.pages else await browser.new_page()
                            )
                            self.browser_ua = await probe_page.evaluate("navigator.userAgent")
                        except BrowserError:
                            self.browser_ua = None
                        browser.on("framenavigated", self._on_frame_navigated)
                        census_path = census_path_from_env()
                        if census_path is not None:
                            census = RequestCensus(census_path)
                            census.attach(browser)
                        yield browser
                    finally:
                        if browser:
                            # Let a pending snapshot write finish: the session is still verified
                            # at this point, and it is the state the next launch must restore.
                            pending = self._snapshot_task
                            if pending and not pending.done():
                                with suppress(asyncio.TimeoutError, Exception):
                                    await asyncio.wait_for(pending, timeout=10.0)
                            await close_browser_context(browser)
                            self.stopped = True
                            self._context = None
                        if census is not None:
                            census.close()
                            census = None
            finally:
                release_profile_lock(lock)


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


def _account_selector(config: UnitConfig) -> str | None:
    """Registry-provided account locator; ``None`` when the registry is unreadable."""
    return _registry_selector(config, "account")


def _account_url_parameter(config: UnitConfig) -> str | None:
    """Registry-declared URL identity fallback; absent contracts keep legacy behaviour."""

    try:
        registry = json.loads(config.registry_path.read_text())
        parameter = (registry.get("session") or {}).get("account_url_parameter")
    except (OSError, ValueError, AttributeError):
        return None
    return parameter if isinstance(parameter, str) and parameter else None


def _protected_ready_selector(config: UnitConfig) -> str | None:
    """Registry-provided marker of a signed-in business surface; ``None`` if unavailable.

    Only used to decide whether the current page is worth snapshotting.  A missing or unreadable
    registry never blocks the browser: snapshot capture is then skipped rather than guessed.
    """
    return _registry_selector(config, "protected_ready")


def _registry_selector(config: UnitConfig, key: str) -> str | None:
    try:
        registry = json.loads(config.registry_path.read_text())
        session = registry.get("session") or {}
        selector = (session.get(key) or {}).get("selector")
    except (OSError, ValueError, AttributeError):
        return None
    return selector if isinstance(selector, str) and selector else None


def confirm_local_browser_stopped(config: UnitConfig, private_root: Path) -> None:
    """Conservative local-only isolation check. Never kills an unverified process.

    The project lock proves no BrowserHost owns the profile.  Chromium's SingletonLock supplies
    a second, independent PID signal without relying on process-list permission.  A stale
    SingletonLock whose PID no longer exists is evidence of an unclean exit, not a live browser.
    """
    profile = config.profile_directory.resolve()
    if not profile.is_relative_to(private_root.resolve()):
        raise CollectorError("RESOURCE_UNAVAILABLE", "PROFILE_OUTSIDE_PROJECT_PRIVATE_ROOT")
    try:
        validate_windows_private_path(profile)
    except OSError as exc:
        raise CollectorError("RESOURCE_UNAVAILABLE", str(exc)) from exc
    if not profile.parent.exists():
        raise CollectorError("RESOURCE_UNAVAILABLE", "PROFILE_NOT_CREATED")
    with (profile.parent / (profile.name + ".lock")).open("a+b") as lock:
        try:
            acquire_profile_lock(lock)
        except ProfileLockBusy as exc:
            raise CollectorError("RESOURCE_UNAVAILABLE", "PROFILE_STILL_IN_USE") from exc
        try:
            if sys.platform == "win32":
                state = windows_chromium_lock_state(profile)
                if state == "RUNNING":
                    raise CollectorError("RESOURCE_UNAVAILABLE", "OLD_PROCESS_STILL_VISIBLE")
                if state == "UNVERIFIABLE":
                    raise CollectorError("RESOURCE_UNAVAILABLE", "SINGLETON_PROCESS_UNVERIFIABLE")
                return
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
            release_profile_lock(lock)


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
        "browser_executable_path": str(runtime.browser_executable_path)
        if runtime.browser_executable_path
        else None,
        "executable_reported_version": browser_executable_version(runtime.browser_executable_path)
        if runtime.browser_executable_path
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
