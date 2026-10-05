from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from playwright.async_api import BrowserContext, Page

from .adapter import BrowserAdapter
from .contracts import PlatformRegistry
from .domain import (
    CollectorError,
    ReleaseDisposition,
    SessionHealth,
    SessionHealthStatus,
)
from .repository import Repository
from .runtime import BrowserRuntime, UnitConfig, ensure_line


async def wait_for_manual_clearance(page: Page, spec: Any, timeout: float) -> str:
    """Wait for normal human login/challenge handling without reading any secret values."""

    def locator(loc: Any) -> Any:
        return (
            page.frame_locator(loc.frame).locator(loc.selector)
            if loc.frame
            else page.locator(loc.selector)
        )

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        blocked = False
        for code, loc in spec.error_selectors.items():
            if await locator(loc).is_visible():
                if code in {"PLATFORM_SECURITY_CHALLENGE", "ACCOUNT_LOGIN_REQUIRED"}:
                    blocked = True
                else:
                    raise CollectorError(code, "REGISTERED_PAGE_STATE")
        protected = not blocked and await locator(spec.protected_ready).is_visible()
        account = ""
        if protected:
            try:
                account = (
                    await locator(spec.account).get_attribute(spec.account.attribute)
                    if spec.account.attribute
                    else await locator(spec.account).inner_text()
                ) or ""
            except Exception:
                account = ""
        if protected and account.strip():
            return account.strip()
        if loop.time() >= deadline:
            raise CollectorError("ACCOUNT_LOGIN_REQUIRED", "MAINTENANCE_TIMEOUT")
        await asyncio.sleep(min(1.0, max(0.1, deadline - loop.time())))


class BrowserHost:
    """Bounded, process-local owner of one unit lease, profile lock and BrowserContext.

    The host deliberately exposes no CDP/control address.  A context is never serialized or
    transferred to another process; maintenance and collection both borrow this same object.
    """

    def __init__(
        self,
        repo: Repository,
        config: UnitConfig,
        registry: PlatformRegistry,
        private_root: Path,
        root_task_id: str,
        owner: str,
        generation: int,
        session_version: int,
        mode: str,
        runtime: BrowserRuntime | None = None,
    ):
        self.repo = repo
        self.config = config
        self.registry = registry
        self.private_root = private_root
        self.root_task_id = root_task_id
        self.owner = owner
        self.generation = generation
        self.session_version = session_version
        self.mode = mode
        self.runtime = runtime or BrowserRuntime(
            config.model_copy(update={"headless": False}), private_root
        )
        self.browser: BrowserContext | None = None
        self._collection_page: Page | None = None
        # Persisted READY is not proof for a new Chrome process.  Until the current context emits
        # a structured observation, release remains SESSION_UNVERIFIED.
        self.release_disposition = (
            ReleaseDisposition.LOGIN_REQUIRED
            if mode == "maintenance"
            else ReleaseDisposition.SESSION_UNVERIFIED
        )
        self.session_health: SessionHealth | None = None

    @classmethod
    @asynccontextmanager
    async def lease(
        cls,
        repo: Repository,
        config: UnitConfig,
        registry: PlatformRegistry,
        private_root: Path,
        root_task_id: str,
        owner: str,
        *,
        maintenance: bool,
        runtime: BrowserRuntime | None = None,
    ) -> AsyncIterator[BrowserHost]:
        generation, session = repo.acquire(
            config.unit_id,
            owner,
            maintenance=maintenance,
            root_task_id=root_task_id,
        )
        host = cls(
            repo,
            config,
            registry,
            private_root,
            root_task_id,
            owner,
            generation,
            session,
            "maintenance" if maintenance else "collect",
            runtime,
        )
        try:
            async with host.runtime.open() as browser:
                host.browser = browser
                yield host
        finally:
            host.browser = None
            repo.release(
                config.unit_id,
                owner,
                generation,
                stopped=host.runtime.stopped,
                disposition=host.release_disposition,
                reason=(
                    host.session_health.evidence_reason
                    if host.session_health
                    else "NO_CURRENT_PROCESS_SESSION_OBSERVATION"
                ),
            )

    def observe_session(self, health: SessionHealth) -> None:
        """Set the eventual release result from a current-process session observation."""
        self.session_health = health.model_copy(
            update={
                "browser_version": health.browser_version
                or getattr(self.runtime, "browser_version", None),
                "browser_environment_hash": health.browser_environment_hash
                or getattr(self.runtime, "environment_hash", None),
            }
        )
        self.release_disposition = {
            SessionHealthStatus.VALID: ReleaseDisposition.VERIFIED_READY,
            SessionHealthStatus.LOGIN_REQUIRED: ReleaseDisposition.LOGIN_REQUIRED,
            SessionHealthStatus.ACCOUNT_MISMATCH: ReleaseDisposition.ACCOUNT_MISMATCH,
            SessionHealthStatus.SECURITY_CHALLENGE: ReleaseDisposition.LOGIN_REQUIRED,
            SessionHealthStatus.INDETERMINATE: ReleaseDisposition.SESSION_UNVERIFIED,
        }[health.status]

    async def heartbeat(self) -> None:
        self.repo.heartbeat(self.config.unit_id, self.owner, self.generation)
        await ensure_line(self.config)

    async def maintain_and_promote(
        self,
        *,
        timeout: float,
        actor: str,
        page: Page | None = None,
    ) -> int:
        if self.mode != "maintenance" or not self.browser:
            raise CollectorError("LEASE_LOST", "HOST_NOT_IN_MAINTENANCE")
        session = self.registry.session
        search = self.registry.search
        assert session and search
        await self.heartbeat()
        maintenance_page = page or (
            self.browser.pages[0] if self.browser.pages else await self.browser.new_page()
        )
        if page is None:
            await maintenance_page.goto(session.entry_url, wait_until="domcontentloaded")
        account = await wait_for_manual_clearance(maintenance_page, session, timeout)
        if account != self.config.expected_account_id:
            self.observe_session(
                SessionHealth(
                    status=SessionHealthStatus.ACCOUNT_MISMATCH,
                    expected_account_id=self.config.expected_account_id,
                    observed_account_id=account,
                    protected_page_verified=True,
                    evidence_reason="PROTECTED_PAGE_WRONG_ACCOUNT",
                )
            )
            raise CollectorError("ACCOUNT_MISMATCH", "WRONG_ACCOUNT")

        # Verify the protected business capability, not merely an app shell or a Cookie.
        await maintenance_page.goto(search.entry_url, wait_until="domcontentloaded")
        verifier = BrowserAdapter(
            self.browser,
            self.registry,
            self.config.expected_account_id,
            self.heartbeat,
            live=True,
            on_session_health=self.observe_session,
        )
        try:
            await verifier.check_session(maintenance_page, timeout=30)
        finally:
            await verifier.close()
        self.observe_session(
            SessionHealth(
                status=SessionHealthStatus.VALID,
                expected_account_id=self.config.expected_account_id,
                observed_account_id=account,
                protected_page_verified=True,
                evidence_reason="PROTECTED_PAGE_AND_ACCOUNT_VERIFIED",
            )
        )
        await self.heartbeat()
        self.session_version = self.repo.promote_maintenance_to_collect(
            self.config.unit_id,
            self.owner,
            self.generation,
            self.session_version,
            account,
            actor,
            account_verified=True,
            protected_page_verified=True,
            line_verified=True,
        )
        self.mode = "collect"
        # Hand the exact page that proved the account and protected capability to the
        # collector.  Creating a fresh page here is both unnecessary and confusing to a
        # person clearing a login/challenge: it looks like a second, logged-out browser even
        # though Playwright still owns a single BrowserContext.
        self._collection_page = maintenance_page
        return self.session_version

    def take_collection_page(self) -> Page | None:
        """Transfer the verified page once, without transferring BrowserContext ownership."""

        page, self._collection_page = self._collection_page, None
        return page

    def enter_maintenance(self, reason: str, actor: str) -> None:
        if self.mode != "collect":
            raise CollectorError("LEASE_LOST", "HOST_NOT_IN_COLLECT")
        self.repo.transition_collect_to_maintenance(
            self.config.unit_id,
            self.owner,
            self.generation,
            self.session_version,
            reason,
            actor,
        )
        self.mode = "maintenance"
        self.release_disposition = (
            ReleaseDisposition.ACCOUNT_MISMATCH
            if reason == "ACCOUNT_MISMATCH"
            else ReleaseDisposition.LOGIN_REQUIRED
        )
