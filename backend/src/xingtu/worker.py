from __future__ import annotations

import asyncio
import logging
import os
import platform
from contextlib import suppress
from pathlib import Path

from playwright.async_api import Error as BrowserError
from pydantic import ValidationError
from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError
from temporalio.worker import Worker

from .adapter import BrowserAdapter
from .adapter_factory import build_platform_adapter
from .browser_host import BrowserHost
from .challenge import ChallengeHandler, ChallengePolicy
from .contracts import PlatformRegistry
from .covers import CoverPipeline, build_cover_store
from .domain import CollectorError, ExecutionContext, TaskKind, TaskRecord, TaskStatus, uid, utcnow
from .engine import Engine
from .evidence import build_evidence_sink
from .repository import Repository
from .runtime import UnitConfig, confirm_local_browser_stopped, ensure_line
from .workflow import CollectionWorkflow

logger = logging.getLogger(__name__)


async def registered_page_error_after_browser_failure(
    adapter: BrowserAdapter,
) -> CollectorError | None:
    """Recover a registered page state that interrupted a Playwright action.

    A challenge can render after the last normal readiness check and intercept an in-flight
    click.  Playwright then raises an action timeout, which is not evidence that Chrome closed.
    Re-read only the contract's registered error selectors; never interact with the challenge.
    """

    seen: set[int] = set()
    for page in (adapter.detail_page, adapter.search_page):
        if page is None or id(page) in seen:
            continue
        seen.add(id(page))
        try:
            await asyncio.wait_for(adapter.check_page_errors(page), timeout=3.0)
        except CollectorError as exc:
            return exc
        except (BrowserError, TimeoutError):
            continue
    return None


def browser_transport_was_closed(exc: BrowserError) -> bool:
    """Distinguish a closed transport from an ordinary locator/action failure."""

    if type(exc).__name__ == "TargetClosedError":
        return True
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "browser has been closed",
            "context has been closed",
            "page has been closed",
            "target page, context or browser has been closed",
            "connection closed",
        )
    )


def adopt_compatible_legacy_checkpoint(task: TaskRecord, registry: PlatformRegistry) -> bool:
    """Adopt the current runtime contract for a pristine compatible v1 task.

    This is deliberately narrower than a general checkpoint migration.  It only covers the
    deployment boundary promised by the v2 capability registry: a queued, Keyword-only v1 plan
    which has never started browser collection.  Once any collection progress exists, changing
    the runtime versions would make resume semantics ambiguous and must remain fail closed.
    """

    if task.plan is None:
        return False
    capabilities = registry.capabilities
    compatible = task.state == TaskStatus.QUEUED and (
        (
            task.plan.schema_version == "filter_plan.v1"
            and task.plan.capability_version in capabilities.compatible_plan_versions
            and {item.field for item in task.plan.filters} == {"keyword"}
        )
        or (
            task.plan.schema_version == "filter_plan.v3"
            and task.plan.capability_version == capabilities.version
        )
    )
    checkpoint = task.checkpoint
    pristine = (
        checkpoint.search_generation == 0
        and checkpoint.cursor is None
        and not checkpoint.visited_cursors
        and not checkpoint.processed_operations
        and not checkpoint.exhausted
        and not checkpoint.exhaustion_evidence_refs
        and checkpoint.search_stop_reason is None
        and not checkpoint.candidates
        and not checkpoint.scanned_ids
        and checkpoint.pending_page is None
        and not checkpoint.diagnostics
        and checkpoint.no_progress_pages == 0
        and checkpoint.active_seconds == 0
        and checkpoint.observed_requests == 0
        and checkpoint.observed_responses == 0
        and checkpoint.navigation_count == 0
        and checkpoint.duplicate_request_count == 0
        and checkpoint.featured_load_count == 0
        and checkpoint.cover_request_count == 0
        and not checkpoint.module_seconds
        and not checkpoint.failure_counts
        and not checkpoint.rescan_reasons
        and checkpoint.challenge_count == 0
        and checkpoint.challenge_recovery_count == 0
        and not checkpoint.challenge_recoveries_by_creator
        and checkpoint.challenge_first_detected_at is None
        and checkpoint.challenge_last_detected_at is None
        and checkpoint.challenge_wait_started_at is None
        and checkpoint.challenge_last_recovered_at is None
        and checkpoint.challenge_current_creator is None
        and checkpoint.challenge_type is None
        and checkpoint.challenge_state is None
    )
    if not compatible or not pristine:
        return False

    checkpoint.adapter_version = registry.adapter_version
    checkpoint.contract_version = registry.contract_version
    checkpoint.profile_module_keys = [item.key for item in registry.modules]
    checkpoint.profile_checkpoint_versions = {
        item.key: item.checkpoint_version for item in registry.modules
    }
    checkpoint.featured_collection_types = [item.key.value for item in registry.featured]
    checkpoint.featured_checkpoint_versions = {
        item.key.value: item.checkpoint_version for item in registry.featured
    }
    return True


def adopt_compatible_update_checkpoint(task: TaskRecord, registry: PlatformRegistry) -> bool:
    """Adopt the current registry versions for a pristine plan-less update task.

    An update task records the contract/adapter versions at creation.  If a deployment upgrades the
    registry while the task is still queued, it must fail closed once any creator work exists;
    a pristine task may adopt the new versions because it has collected nothing yet.
    """
    if task.task_kind == TaskKind.COLLECTION:
        return False
    if any(
        candidate.modules
        or candidate.observation_history
        or candidate.collections
        or candidate.collection_history
        for candidate in task.checkpoint.candidates
    ):
        return False
    task.checkpoint.adapter_version = registry.adapter_version
    task.checkpoint.contract_version = registry.contract_version
    task.checkpoint.profile_module_keys = [item.key for item in registry.modules]
    task.checkpoint.profile_checkpoint_versions = {
        item.key: item.checkpoint_version for item in registry.modules
    }
    task.checkpoint.featured_collection_types = [item.key.value for item in registry.featured]
    task.checkpoint.featured_checkpoint_versions = {
        item.key.value: item.checkpoint_version for item in registry.featured
    }
    return True


class Activities:
    def __init__(
        self,
        repo: Repository,
        config: UnitConfig,
        private_root: Path,
        challenge_policy: ChallengePolicy | None = None,
    ):
        self.repo, self.config, self.private_root = repo, config, private_root
        # Temporal is configured for one Activity at a time, and this process lock also makes the
        # per-unit BrowserHost ownership explicit for direct tests/callers.
        self.host_lock = asyncio.Lock()
        self.challenge_policy = challenge_policy or ChallengePolicy()

    async def _wait_for_human_challenge_handoff(
        self,
        *,
        host: BrowserHost,
        task: TaskRecord,
        page: object,
        handler: ChallengeHandler,
    ) -> str:
        """Keep the original browser idle until a human explicitly returns control.

        This loop intentionally makes no Playwright calls while a takeover is ACTIVE.  It only
        renews the host lease via the caller's heartbeat task and reads durable takeover state.
        A person may manually inspect a small number of creator pages in the visible browser;
        those observations are never persisted as collection output.
        """
        if not host.browser_instance_id:
            raise CollectorError("LEASE_LOST", "BROWSER_INSTANCE_NOT_REGISTERED")
        event = self.repo.create_verification_event(
            unit=task.execution_unit_id,
            root_task_id=task.root_task_id,
            generation=host.generation,
            browser_instance_id=host.browser_instance_id,
            timeout_seconds=max(0.0, handler.remaining_timeout(self.repo.get(task.root_task_id))),
        )
        event_id = str(event["event_id"])
        while True:
            latest_task = self.repo.get(task.root_task_id)
            if latest_task.state in {TaskStatus.CANCELLING, TaskStatus.CANCELLED}:
                self.repo.expire_verification_event(event_id, "TASK_CANCELLED")
                return "cancelled"
            remaining = handler.remaining_timeout(latest_task)
            if remaining <= 0:
                self.repo.expire_verification_event(event_id, "SECURITY_CHALLENGE_TIMEOUT")
                return "timeout"
            takeover = self.repo.activate_browser_takeover(
                unit=task.execution_unit_id,
                owner=host.owner,
                generation=host.generation,
                browser_instance_id=host.browser_instance_id,
            )
            if takeover is None:
                # No human is controlling the page, so keep the original browser idle.
                await asyncio.sleep(min(1.0, remaining))
                continue
            takeover_id = str(takeover["takeover_id"])
            while True:
                current = self.repo.takeover(takeover_id)
                state = str(current["state"])
                if self.repo.get(task.root_task_id).state in {
                    TaskStatus.CANCELLING,
                    TaskStatus.CANCELLED,
                }:
                    self.repo.expire_verification_event(event_id, "TASK_CANCELLED")
                    return "cancelled"
                if current["expires_at"] <= utcnow():
                    self.repo.finish_browser_takeover(
                        takeover_id, resumed=False, failure_reason="TAKEOVER_EXPIRED"
                    )
                    break
                if state == "VERIFYING":
                    # The API flips state before closing the noVNC WebSocket.  Its connection
                    # fence is cleared in the proxy's finally block; until then, any Playwright
                    # page access would race the operator's last mouse/keyboard input.
                    if current.get("viewer_connection_id"):
                        await asyncio.sleep(0.1)
                        continue
                    verification_remaining = handler.remaining_timeout(
                        self.repo.get(task.root_task_id)
                    )
                    if verification_remaining <= 0:
                        self.repo.finish_browser_takeover(
                            takeover_id, resumed=False, failure_reason="TAKEOVER_EXPIRED"
                        )
                        self.repo.expire_verification_event(event_id, "SECURITY_CHALLENGE_TIMEOUT")
                        return "timeout"
                    try:
                        await host.maintain_and_promote(
                            timeout=min(verification_remaining, 30.0),
                            actor="browser-host:" + task.attempt_id,
                            page=page,  # type: ignore[arg-type]
                            challenge_handler=handler,
                            return_on_challenge_visible=True,
                        )
                    except CollectorError as exc:
                        reason = (
                            "SECURITY_CHALLENGE_STILL_PRESENT"
                            if exc.code == "SECURITY_CHALLENGE_STILL_PRESENT"
                            else exc.code
                        )
                        self.repo.finish_browser_takeover(
                            takeover_id, resumed=False, failure_reason=reason
                        )
                        break
                    self.repo.finish_browser_takeover(takeover_id, resumed=True)
                    return "resumed"
                if state in {"RELEASED", "EXPIRED", "FAILED"}:
                    break
                if handler.remaining_timeout(self.repo.get(task.root_task_id)) <= 0:
                    self.repo.finish_browser_takeover(
                        takeover_id, resumed=False, failure_reason="TAKEOVER_EXPIRED"
                    )
                    self.repo.expire_verification_event(event_id, "SECURITY_CHALLENGE_TIMEOUT")
                    return "timeout"
                await asyncio.sleep(0.5)

    def cancel_disabled_scheduled_update(self, task: TaskRecord) -> str | None:
        """Refuse to start a scheduled batch whose service was switched off while queued.

        The check runs before any unit/browser work, so a stale plan created just before the
        operator flipped the switch never opens Chrome.  Running tasks are untouched: this method
        only sees the task before execution starts.
        """
        if task.task_kind != TaskKind.SCHEDULED_UPDATE:
            return None
        if self.repo.scheduled_update_enabled(task.platform.value, task.creator_scene.value):
            return None
        with self.repo.edit(task.root_task_id) as (current, _):
            current.state = TaskStatus.CANCELLED
            current.failure_reason = "UPDATE_SERVICE_DISABLED"
        return TaskStatus.CANCELLED

    @activity.defn(name="collect_segment_v1")
    async def collect(self, root: str) -> str:
        task = self.repo.get(root)
        if task.state == TaskStatus.CANCELLING:
            with self.repo.edit(root) as (current, _):
                current.state = TaskStatus.CANCELLED
            return TaskStatus.CANCELLED
        if task.state in {
            TaskStatus.PAUSED_BUDGET,
            TaskStatus.CANCELLED,
            TaskStatus.PARTIAL_COMPLETED,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
        }:
            return task.state
        disabled = self.cancel_disabled_scheduled_update(task)
        if disabled is not None:
            return disabled
        unit = self.repo.unit(task.execution_unit_id)
        # A challenge timeout closes the verification event but can leave the shared unit in
        # NEEDS_VERIFICATION.  The next task (possibly for the other platform) must not inherit
        # that stale state; a fresh browser check re-detects a real challenge.
        if self.repo.reconcile_stale_verification(
            task.execution_unit_id, "worker:" + task.attempt_id
        ):
            unit = self.repo.unit(task.execution_unit_id)
        if task.task_kind.value not in (unit.get("allowed_task_kinds") or []):
            with self.repo.edit(root) as (current, _):
                current.state = TaskStatus.FAILED
                current.failure_reason = "TASK_KIND_NOT_ALLOWED"
            return TaskStatus.FAILED
        if not self.repo.unit_supports_platform(task.execution_unit_id, task.platform.value):
            with self.repo.edit(root) as (current, _):
                current.state = TaskStatus.WAITING_FOR_RESOURCE
                current.failure_reason = "PLATFORM_BINDING_NOT_CONFIGURED"
            return TaskStatus.WAITING_FOR_RESOURCE
        try:
            active_config = self.config.for_scene(task.platform, task.creator_scene)
        except CollectorError as exc:
            with self.repo.edit(root) as (current, _):
                current.state = TaskStatus.WAITING_FOR_RESOURCE
                current.failure_reason = str(exc)
            return TaskStatus.WAITING_FOR_RESOURCE
        if task.task_kind != TaskKind.COLLECTION and self.repo.has_runnable_higher_priority_task(
            task.execution_unit_id, root, task.task_kind
        ):
            # Do not acquire or open the browser while normal collection (or a manual update for
            # a scheduled batch) is runnable.  The Workflow's 30-second loop retries this activity.
            with self.repo.edit(root) as (current, _):
                current.state = TaskStatus.QUEUED
                current.failure_reason = None
            return TaskStatus.QUEUED
        try:
            try:
                registry = PlatformRegistry.model_validate_json(
                    active_config.registry_path.read_text()
                )
            except (OSError, ValidationError) as exc:
                raise CollectorError(
                    "PLATFORM_PAGE_CHANGED", "PLATFORM_REGISTRY_NOT_EXECUTABLE"
                ) from exc
            registry.require_enabled(live=True)
            if task.plan is not None:
                registry.capabilities.validate_plan(task.plan, live=True)
            versions_changed = (
                task.checkpoint.adapter_version != registry.adapter_version
                or task.checkpoint.contract_version != registry.contract_version
            )
            if versions_changed:
                with self.repo.edit(root) as (current, _):
                    adopted = (
                        adopt_compatible_legacy_checkpoint(current, registry)
                        if current.plan is not None
                        else adopt_compatible_update_checkpoint(current, registry)
                    )
                    if not adopted:
                        raise CollectorError("PLATFORM_PAGE_CHANGED", "VERSION_MISMATCH")
                task = self.repo.get(root)
            required_scopes = {"session", "search", "profile_identity"}
            required_scopes.update(f"profile_module:{item.key}" for item in registry.modules)
            required_scopes.update(f"featured:{item.key.value}" for item in registry.featured)
            self.repo.require_contract(registry.contract_version, required_scopes)
            await ensure_line(active_config)
        except CollectorError as exc:
            with self.repo.edit(root) as (current, _):
                if current.attempt_id != task.attempt_id:
                    return current.state
                current.state = (
                    TaskStatus.WAITING_FOR_LOGIN
                    if exc.code == "ACCOUNT_LOGIN_REQUIRED"
                    else TaskStatus.WAITING_FOR_ACCOUNT
                    if exc.code == "ACCOUNT_MISMATCH"
                    else TaskStatus.WAITING_FOR_RESOURCE
                    if exc.code in {"RESOURCE_UNAVAILABLE", "SESSION_INDETERMINATE"}
                    else TaskStatus.FAILED
                )
                current.failure_reason = str(exc)
                return current.state
        evidence = build_evidence_sink(active_config.evidence, self.repo, self.private_root.parent)
        covers = CoverPipeline(
            self.repo, build_cover_store(active_config.covers, self.repo, self.private_root.parent)
        )
        main_task = asyncio.current_task()
        heartbeat_error: CollectorError | None = None
        host: BrowserHost | None = None
        engine: Engine | None = None

        async def guard() -> None:
            if not host:
                raise CollectorError("LEASE_LOST", "BROWSER_HOST_NOT_STARTED")
            await host.heartbeat()
            activity.heartbeat(root)
            if engine and host.mode == "collect":
                engine.guard()

        async def heartbeat() -> None:
            nonlocal heartbeat_error
            while True:
                await asyncio.sleep(15)
                try:
                    await guard()
                except CollectorError as exc:
                    heartbeat_error = exc
                    if main_task:
                        main_task.cancel()
                    return

        maintenance = unit["state"] in {
            "NEEDS_LOGIN",
            "ACCOUNT_MISMATCH",
            "NEEDS_VERIFICATION",
        }
        if maintenance:
            with self.repo.edit(root) as (current, _):
                if current.attempt_id != task.attempt_id:
                    return current.state
                current.state = (
                    TaskStatus.WAITING_FOR_ACCOUNT
                    if unit["state"] == "ACCOUNT_MISMATCH"
                    else TaskStatus.WAITING_FOR_VERIFICATION
                    if unit["state"] == "NEEDS_VERIFICATION"
                    else TaskStatus.WAITING_FOR_LOGIN
                )
                current.failure_reason = (
                    "ACCOUNT_MISMATCH"
                    if unit["state"] == "ACCOUNT_MISMATCH"
                    else "PLATFORM_SECURITY_CHALLENGE"
                    if unit["state"] == "NEEDS_VERIFICATION"
                    else "ACCOUNT_LOGIN_REQUIRED"
                )

        async with self.host_lock:
            try:
                async with BrowserHost.lease(
                    self.repo,
                    active_config,
                    registry,
                    self.private_root,
                    root,
                    task.attempt_id,
                    maintenance=maintenance,
                ) as active_host:
                    host = active_host
                    pulse = asyncio.create_task(heartbeat())
                    challenge_handler = ChallengeHandler(self.repo, self.challenge_policy)
                    try:
                        if host.mode == "maintenance":
                            recovering_challenge = unit["state"] == "NEEDS_VERIFICATION"
                            maintenance_timeout = self.challenge_policy.timeout_seconds
                            if recovering_challenge:
                                maintenance_timeout = challenge_handler.remaining_timeout(
                                    self.repo.get(root)
                                )
                                if maintenance_timeout <= 0:
                                    challenge_handler.failed(
                                        root,
                                        task.attempt_id,
                                        "SECURITY_CHALLENGE_TIMEOUT",
                                    )
                                    with self.repo.edit(root) as (current, conn):
                                        self.repo.persist_creators(conn, current, publish=True)
                                        current.pipeline_complete = False
                                        current.state = TaskStatus.PARTIAL_COMPLETED
                                        current.failure_reason = "SECURITY_CHALLENGE_TIMEOUT"
                                    return TaskStatus.PARTIAL_COMPLETED
                            try:
                                await host.maintain_and_promote(
                                    timeout=maintenance_timeout,
                                    actor="browser-host:" + task.attempt_id,
                                    challenge_handler=challenge_handler
                                    if recovering_challenge
                                    else None,
                                )
                            except CollectorError as exc:
                                if recovering_challenge and exc.code.startswith(
                                    "SECURITY_CHALLENGE_"
                                ):
                                    challenge_handler.failed(root, task.attempt_id, exc.code)
                                    with self.repo.edit(root) as (current, conn):
                                        self.repo.persist_creators(conn, current, publish=True)
                                        current.pipeline_complete = False
                                        current.state = TaskStatus.PARTIAL_COMPLETED
                                        current.failure_reason = exc.code
                                    return TaskStatus.PARTIAL_COMPLETED
                                raise
                            if recovering_challenge:
                                current = self.repo.get(root)
                                challenge_handler.recovered(
                                    root,
                                    task.attempt_id,
                                    current.checkpoint.challenge_current_creator,
                                )
                                await challenge_handler.cooldown()
                        while True:
                            with self.repo.edit(root) as (current, _):
                                if current.state in {
                                    TaskStatus.WAITING_FOR_LOGIN,
                                    TaskStatus.WAITING_FOR_ACCOUNT,
                                    TaskStatus.WAITING_FOR_VERIFICATION,
                                    TaskStatus.WAITING_FOR_RESOURCE,
                                    TaskStatus.RETRY_WAIT,
                                }:
                                    current.state = TaskStatus.QUEUED
                                    current.failure_reason = None
                            ctx = ExecutionContext(
                                root_task_id=root,
                                task_id=task.task_id,
                                attempt_id=task.attempt_id,
                                execution_unit_id=task.execution_unit_id,
                                lease_generation=host.generation,
                                session_version=host.session_version,
                                capability_version=(
                                    task.capability_version or registry.capabilities.version
                                ),
                                adapter_version=registry.adapter_version,
                                contract_version=registry.contract_version,
                                network_mode=active_config.network_mode,
                                budget=active_config.budget,
                            )
                            assert host.browser
                            adapter = build_platform_adapter(
                                task.platform,
                                host.browser,
                                registry,
                                active_config.expected_account_id,
                                guard,
                                scene=task.creator_scene,
                                on_session_health=host.observe_session,
                                manually_attested_account_id=active_config.manually_attested_account_id,
                            )
                            adapter.creator_interval_seconds = (
                                self.challenge_policy.creator_interval_seconds
                            )
                            adapter.search_page = host.take_collection_page()
                            engine = Engine(
                                self.repo, adapter, ctx, evidence=evidence, covers=covers
                            )
                            try:
                                try:
                                    if task.task_kind == TaskKind.COLLECTION:
                                        return await engine.run()
                                    return await engine.run_update()
                                except BrowserError as exc:
                                    page_error = await registered_page_error_after_browser_failure(
                                        adapter
                                    )
                                    if page_error is not None:
                                        raise page_error from exc
                                    raise
                            except CollectorError as exc:
                                if exc.code in {
                                    "ACCOUNT_LOGIN_REQUIRED",
                                    "ACCOUNT_MISMATCH",
                                    "PLATFORM_SECURITY_CHALLENGE",
                                    "ACCOUNT_SELECTION_REQUIRED",
                                }:
                                    maintenance_page = adapter.detail_page or adapter.search_page
                                    if maintenance_page:
                                        adapter.detach_page(maintenance_page)
                                    host.enter_maintenance(
                                        exc.code, "browser-host:" + task.attempt_id
                                    )
                                    engine.record_error(exc)
                                    if exc.code == "ACCOUNT_SELECTION_REQUIRED":
                                        with self.repo.edit(root) as (current, _):
                                            current.state = TaskStatus.WAITING_FOR_ACCOUNT
                                            current.failure_reason = "ACCOUNT_SELECTION_REQUIRED"
                                        if maintenance_page is None:
                                            with self.repo.edit(root) as (current, _):
                                                current.state = TaskStatus.PARTIAL_COMPLETED
                                                current.failure_reason = (
                                                    "ACCOUNT_SELECTION_REQUIRED"
                                                )
                                            return TaskStatus.PARTIAL_COMPLETED
                                        assert host.browser_instance_id
                                        event = self.repo.create_verification_event(
                                            unit=task.execution_unit_id,
                                            root_task_id=task.root_task_id,
                                            generation=host.generation,
                                            browser_instance_id=host.browser_instance_id,
                                            timeout_seconds=self.challenge_policy.timeout_seconds,
                                            reason="ACCOUNT_SELECTION_REQUIRED",
                                        )
                                        event_id = str(event["event_id"])
                                        try:
                                            await host.maintain_and_promote(
                                                timeout=self.challenge_policy.timeout_seconds,
                                                actor="browser-host:" + task.attempt_id,
                                                page=maintenance_page,
                                            )
                                        except CollectorError as handoff_error:
                                            reason = (
                                                "ACCOUNT_SELECTION_TIMEOUT"
                                                if handoff_error.code
                                                in {
                                                    "ACCOUNT_LOGIN_REQUIRED",
                                                    "MAINTENANCE_TIMEOUT",
                                                }
                                                or "TIMEOUT" in handoff_error.code
                                                else handoff_error.code
                                            )
                                            self.repo.expire_verification_event(
                                                event_id,
                                                "ACCOUNT_SELECTION_TIMEOUT"
                                                if reason == "ACCOUNT_SELECTION_TIMEOUT"
                                                else reason,
                                            )
                                            with self.repo.edit(root) as (current, _):
                                                current.state = TaskStatus.PARTIAL_COMPLETED
                                                current.failure_reason = reason
                                            return TaskStatus.PARTIAL_COMPLETED
                                        engine = None
                                        continue
                                    if exc.code == "PLATFORM_SECURITY_CHALLENGE":
                                        attempt = challenge_handler.register(root, task.attempt_id)
                                        if not attempt.allowed:
                                            return engine.partial_complete(
                                                attempt.terminal_reason
                                                or "SECURITY_CHALLENGE_LIMIT"
                                            )
                                        if maintenance_page is None:
                                            challenge_handler.failed(
                                                root,
                                                task.attempt_id,
                                                "SECURITY_CHALLENGE_UNKNOWN",
                                            )
                                            return engine.partial_complete(
                                                "SECURITY_CHALLENGE_UNKNOWN"
                                            )
                                        handoff = await self._wait_for_human_challenge_handoff(
                                            host=host,
                                            task=task,
                                            page=maintenance_page,
                                            handler=challenge_handler,
                                        )
                                        if handoff == "timeout":
                                            challenge_handler.failed(
                                                root, task.attempt_id, "SECURITY_CHALLENGE_TIMEOUT"
                                            )
                                            return engine.partial_complete(
                                                "SECURITY_CHALLENGE_TIMEOUT"
                                            )
                                        if handoff == "cancelled":
                                            with self.repo.edit(root) as (current, _):
                                                if current.state == TaskStatus.CANCELLING:
                                                    current.state = TaskStatus.CANCELLED
                                            return TaskStatus.CANCELLED
                                        challenge_handler.recovered(
                                            root, task.attempt_id, attempt.creator_id
                                        )
                                        await challenge_handler.cooldown()
                                    else:
                                        await host.maintain_and_promote(
                                            timeout=self.challenge_policy.timeout_seconds,
                                            actor="browser-host:" + task.attempt_id,
                                            page=maintenance_page,
                                        )
                                    engine = None
                                    continue
                                # Rate limits consume a bounded Temporal retry budget; no nested
                                # client retries and no transition into login maintenance.
                                if (
                                    exc.code == "PLATFORM_RATE_LIMITED"
                                    and activity.info().attempt < 4
                                ):
                                    engine.record_error(exc)
                                    raise
                                return engine.record_error(exc)
                            except BrowserError as exc:
                                # Preserve the decisive Playwright detail, but only classify an
                                # actual closed target/transport as a resource loss. Locator and
                                # action failures with no registered page state remain contract
                                # failures and must not falsely claim that the user closed Chrome.
                                logger.warning(
                                    "browser action failure attempt=%s %s: %s",
                                    activity.info().attempt,
                                    type(exc).__name__,
                                    exc,
                                )
                                browser_error = CollectorError(
                                    "RESOURCE_UNAVAILABLE"
                                    if browser_transport_was_closed(exc)
                                    else "PLATFORM_PAGE_CHANGED",
                                    "BROWSER_CLOSED_OR_TRANSPORT_LOST"
                                    if browser_transport_was_closed(exc)
                                    else "BROWSER_ACTION_FAILED",
                                )
                                if (
                                    browser_error.code == "RESOURCE_UNAVAILABLE"
                                    and activity.info().attempt < 4
                                ):
                                    raise browser_error from exc
                                return engine.record_error(browser_error)
                            finally:
                                if host.mode == "collect":
                                    await adapter.close()
                    finally:
                        pulse.cancel()
                        with suppress(asyncio.CancelledError):
                            await pulse
            except asyncio.CancelledError:
                if heartbeat_error and engine:
                    return engine.record_error(heartbeat_error)
                raise
            except CollectorError as exc:
                if engine:
                    return engine.record_error(exc)
                with self.repo.edit(root) as (current, _):
                    if current.attempt_id != task.attempt_id:
                        return current.state
                    current.state = (
                        TaskStatus.WAITING_FOR_LOGIN
                        if exc.code == "ACCOUNT_LOGIN_REQUIRED"
                        else TaskStatus.WAITING_FOR_VERIFICATION
                        if exc.code == "PLATFORM_SECURITY_CHALLENGE"
                        else TaskStatus.WAITING_FOR_ACCOUNT
                        if exc.code == "ACCOUNT_MISMATCH"
                        else TaskStatus.WAITING_FOR_RESOURCE
                        if exc.code
                        in {
                            "RESOURCE_UNAVAILABLE",
                            "LEASE_LOST",
                            "SESSION_INDETERMINATE",
                        }
                        else TaskStatus.FAILED
                    )
                    current.failure_reason = str(exc)
                    return current.state


async def dispatch(repo: Repository, client: Client, queue: str) -> None:
    with repo.connect() as conn:
        rows = conn.execute(
            "SELECT d.* FROM task_dispatches d JOIN root_tasks r USING(root_task_id) "
            "WHERE d.sent=false AND r.unit_id=%s "
            "ORDER BY CASE r.task_kind "
            "WHEN 'collection' THEN 0 WHEN 'manual_update' THEN 1 "
            "WHEN 'scheduled_update' THEN 2 ELSE 3 END, r.updated_at,d.segment",
            (queue.removeprefix("xingtu-"),),
        ).fetchall()
    for row in rows:
        root, workflow_id = str(row["root_task_id"]), row["workflow_id"]
        handle = client.get_workflow_handle(workflow_id)
        try:
            await client.start_workflow(
                CollectionWorkflow.run,
                root,
                id=workflow_id,
                task_queue=queue,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            )
        except WorkflowAlreadyStartedError:
            # The workflow may already have finished; a wake signal is then meaningless and must
            # not take the worker down.
            with suppress(RPCError):
                await handle.signal(CollectionWorkflow.wake)
        with repo.connect() as conn:
            # ``workflow_started_at`` is the durable fact the cancel path uses to decide whether a
            # collection process can still be holding this task (FIX-01 P1-B).
            conn.execute(
                """UPDATE task_dispatches SET sent=true,workflow_started_at=now()
                WHERE root_task_id=%s AND segment=%s""",
                (root, row["segment"]),
            )
    # Cancellation must also wake workflows paused on a signal.
    with repo.connect() as conn:
        cancelling = conn.execute(
            "SELECT root_task_id FROM root_tasks WHERE state='CANCELLING' AND unit_id=%s",
            (queue.removeprefix("xingtu-"),),
        ).fetchall()
    for row in cancelling:
        root = str(row["root_task_id"])
        handle = client.get_workflow_handle(f"collect/{root}")
        try:
            description = await handle.describe()
        except RPCError:
            description = None
        if description is not None and description.status == WorkflowExecutionStatus.RUNNING:
            try:
                await handle.signal(CollectionWorkflow.wake)
            except RPCError:
                # The workflow finished between describe and signal. Nothing is running for this
                # root, so the cancellation is finalised here instead of killing the worker.
                logger.info("collect workflow for %s ended before the wake signal", root)
                _finalise_cancelled(repo, root)
            continue
        _finalise_cancelled(repo, root)


def _finalise_cancelled(repo: Repository, root: str) -> None:
    with repo.edit(root) as (task, _):
        task.state = TaskStatus.CANCELLED


# Quarantined is produced only by an expired owner or an unconfirmed browser exit.  Both are
# recoverable after the local profile lock and Chromium singleton/lockfile checks prove no
# browser is still running; there is no manual quarantine reason to filter here.
def reconcile_quarantined_unit(
    repo: Repository,
    config: UnitConfig,
    private_root: Path,
    worker_instance_id: str,
) -> bool:
    """Recover one locally proven stopped unit, or leave it quarantined.

    This runs only at Collection Worker startup, after this process registered its own worker
    generation.  It deliberately does not touch a unit with an active lease, verification event
    or takeover, and it never kills a process, deletes a lock or clears a profile.  If the local
    isolation proof fails for any reason the unit stays quarantined and the Worker continues;
    recovery must never be a prerequisite for serving the queue.
    """
    unit = repo.unit(config.unit_id)
    if unit["state"] != "QUARANTINED":
        return False
    reason = str(unit.get("failure_reason") or "UNKNOWN")
    if repo.has_active_unit_claim(config.unit_id):
        logger.warning(
            "quarantined unit %s still has an active lease/verification/takeover; left isolated",
            config.unit_id,
        )
        return False
    try:
        confirm_local_browser_stopped(config, private_root)
    except (CollectorError, OSError) as exc:
        logger.warning(
            "quarantined unit %s remains isolated: %s",
            config.unit_id,
            str(exc) or type(exc).__name__,
        )
        return False
    try:
        repo.recover_stopped_unit(config.unit_id, "collection-worker:" + worker_instance_id)
    except CollectorError as exc:
        logger.warning(
            "quarantined unit %s recovery refused: %s", config.unit_id, str(exc) or exc.code
        )
        return False
    logger.info(
        "recovered quarantined unit %s after local isolation proof (reason=%s, worker=%s)",
        config.unit_id,
        reason,
        worker_instance_id,
    )
    return True


async def run_worker(
    repo: Repository, config: UnitConfig, address: str, private_root: Path
) -> None:
    for binding in getattr(config, "platform_bindings", []):
        repo.register_unit_platform_binding(
            config.unit_id,
            binding.platform.value,
            binding.account_ref,
            binding.expected_account_id,
            str(binding.profile_directory),
            str(binding.registry_path),
            enabled=binding.enabled,
        )
    client = await Client.connect(address)
    queue = f"xingtu-{config.unit_id}"
    activities = Activities(repo, config, private_root)
    worker_instance_id = uid()
    worker_generation = repo.register_worker_instance(
        config.unit_id,
        worker_instance_id,
        os.getpid(),
        platform.system().lower() or "unknown",
    )
    try:
        reconcile_quarantined_unit(repo, config, private_root, worker_instance_id)
    except Exception as exc:  # noqa: BLE001 - startup must not be blocked by recovery bookkeeping
        logger.warning(
            "quarantined unit reconciliation failed: %s: %s", type(exc).__name__, str(exc)
        )

    async def worker_heartbeat() -> None:
        while True:
            await asyncio.sleep(10)
            repo.heartbeat_worker_instance(config.unit_id, worker_instance_id, worker_generation)

    heartbeat_task = asyncio.create_task(worker_heartbeat())
    stop_reason = "NORMAL_STOP"
    try:
        logger.info(
            "collection worker polling %s on %s instance=%s generation=%s",
            queue,
            address,
            worker_instance_id,
            worker_generation,
        )
        async with Worker(
            client,
            task_queue=queue,
            workflows=[CollectionWorkflow],
            activities=[activities.collect],
            max_concurrent_activities=1,
        ):
            while True:
                if heartbeat_task.done():
                    heartbeat_task.result()
                try:
                    # Local (normal collection/manual) dispatches start first.  Only then does
                    # this worker claim one unassigned update task from the shared pool.
                    await dispatch(repo, client, queue)
                    if repo.claim_unassigned_update(config.unit_id):
                        await dispatch(repo, client, queue)
                except Exception as exc:  # noqa: BLE001 - dispatch survives a tick error
                    logger.warning("collection dispatch tick failed: %s", type(exc).__name__)
                await asyncio.sleep(2)
    except BaseException as exc:
        stop_reason = type(exc).__name__
        raise
    finally:
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)
        try:
            repo.stop_worker_instance(
                config.unit_id,
                worker_instance_id,
                worker_generation,
                stop_reason,
            )
        except Exception as exc:  # noqa: BLE001 - shutdown must preserve the original failure
            logger.warning("collection worker stop record failed: %s", type(exc).__name__)
