from __future__ import annotations

import asyncio
import contextvars
import logging
import threading
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from playwright.async_api import Error as BrowserError
from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError
from temporalio.worker import Worker

from .adapter import BrowserAdapter
from .browser_host import BrowserHost
from .challenge import ChallengeHandler, ChallengePolicy
from .contracts import PlatformRegistry
from .covers import CoverPipeline, build_cover_store
from .domain import CollectorError, ExecutionContext, TaskKind, TaskRecord, TaskStatus, utcnow
from .engine import Engine
from .evidence import build_evidence_sink
from .repository import Repository
from .runtime import UnitConfig, ensure_line
from .workflow import CollectionWorkflow

logger = logging.getLogger(__name__)


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
    compatible = (
        task.state == TaskStatus.QUEUED
        and task.plan.schema_version == "filter_plan.v1"
        and task.plan.capability_version in capabilities.compatible_plan_versions
        and {item.field for item in task.plan.filters} == {"keyword"}
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


def should_finalize_cancelled(
    details: object | None,
    heartbeat_error: object | None,
    *,
    attempt: int,
    max_attempts: int = 4,
) -> bool:
    """Whether a cancellation is terminal *and* the Temporal retry budget is exhausted.

    Temporal exposes why the Activity was cancelled:
    - worker_shutdown: the Worker is going away; Temporal will retry after restart.  Do not
      prematurely mark the task terminal.
    - timed_out: heartbeat timeout; re-raise while Temporal still has retry budget, and
      finalize only on the last allowed attempt.
    - cancel_requested: a user/product cancel owns the state; let the cancel path finish it.
    - paused/reset: Temporal lifecycle operations; do not finalize.
    - not_found: the server no longer accepts the Activity token.  On the final configured
      attempt this is also how a heartbeat timeout can surface locally, so let the durable
      attempt/generation fences decide whether finalization is still safe.
    A locally detected heartbeat error is also deferred until the last attempt, unless the
    server explicitly reports a user cancel/shutdown/lifecycle operation.
    """
    if attempt < max_attempts:
        return False
    if details is not None:
        if getattr(details, "worker_shutdown", False):
            return False
        if getattr(details, "timed_out", False):
            return True
        if getattr(details, "cancel_requested", False):
            return False
        if any(getattr(details, name, False) for name in ("paused", "reset")):
            return False
        if getattr(details, "not_found", False):
            return True
    return heartbeat_error is not None


async def renew_lease(host: BrowserHost, *, timeout: float = 10.0) -> None:
    """Renew the database lease without blocking the Activity heartbeat loop.

    The synchronous psycopg call runs in a worker thread and is bounded.  A network/database
    stall becomes a stable CollectorError instead of silently killing the heartbeat coroutine.
    """
    try:
        await asyncio.wait_for(asyncio.to_thread(host.heartbeat_lease), timeout=timeout)
        await asyncio.wait_for(ensure_line(host.config), timeout=timeout)
    except TimeoutError as exc:
        raise CollectorError("RESOURCE_UNAVAILABLE", "HEARTBEAT_TIMEOUT") from exc
    except CollectorError:
        raise
    except Exception as exc:  # noqa: BLE001 - psycopg/network errors are lease failures too
        raise CollectorError("RESOURCE_UNAVAILABLE", f"HEARTBEAT_{type(exc).__name__}") from exc


class TemporalHeartbeat:
    """Schedule Temporal heartbeats for one Activity attempt.

    ``temporalio.activity.heartbeat`` is not thread-safe for asynchronous Activities: it hands the
    payload to ``asyncio.create_task``, so it must run on the thread that owns the event loop.
    Calling it directly from a daemon thread raised ``RuntimeError: no running event loop`` on the
    first tick, left ``_heartbeat_async`` un-awaited, and silently stopped every heartbeat -- the
    45-second heartbeat timeout then re-dispatched the Activity on every attempt.

    The daemon thread therefore only *schedules* the SDK call on the owning loop with the Activity
    context captured at start.  Heartbeats travel as fast as the loop drains callbacks, so a
    multi-second PostgreSQL checkpoint stall still delays them; the async lease heartbeat task
    remains responsible for fail-closed lease renewal, and the loop watchdog reports a wedged loop
    instead of hiding it.
    """

    def __init__(
        self,
        root: str,
        *,
        interval: float = 10.0,
        loop_watchdog_seconds: float = 60.0,
    ):
        self.root, self.interval = root, interval
        self.loop_watchdog_seconds = loop_watchdog_seconds
        self._stop = threading.Event()
        self._loop_alive_at = time.monotonic()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._context: contextvars.Context | None = None
        self._thread: threading.Thread | None = None
        self._failed = False

    def start(self) -> None:
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            # Unit tests or a non-async caller: there is no event loop to schedule onto.
            self._loop = None
        self._loop_alive_at = time.monotonic()
        self._context = contextvars.copy_context()
        self._thread = threading.Thread(
            target=self._run,
            name="temporal-activity-heartbeat",
            daemon=True,
        )
        self._thread.start()

    def _mark_loop_alive(self) -> None:
        self._loop_alive_at = time.monotonic()

    def _send(self) -> None:
        """Run on the loop thread: the SDK schedules its own coroutine from there."""
        try:
            activity.heartbeat(self.root)
        except Exception as exc:  # noqa: BLE001 - stop quietly once the Activity is gone
            self._failed = True
            if not self._stop.is_set():
                logger.warning(
                    "temporal heartbeat failed root=%s type=%s",
                    self.root,
                    type(exc).__name__,
                )

    def _run(self) -> None:
        while not self._stop.is_set():
            # Heartbeat first, then the loop-liveness probe.  The SDK call is scheduled on the
            # loop thread because it is not safe to call from this daemon thread.
            started = time.monotonic()
            if self._loop is not None and self._context is not None:
                try:
                    self._loop.call_soon_threadsafe(self._context.run, self._send)
                except RuntimeError:  # loop already closed
                    return
            else:
                self._send()
            if self._failed:
                return
            if time.monotonic() - started > 2.0:
                logger.warning(
                    "temporal heartbeat scheduling delayed root=%s elapsed=%.1fs",
                    self.root,
                    time.monotonic() - started,
                )
            if self._loop is not None:
                try:
                    self._loop.call_soon_threadsafe(self._mark_loop_alive)
                except RuntimeError:
                    return
                unresponsive_for = time.monotonic() - self._loop_alive_at
                if unresponsive_for > self.loop_watchdog_seconds:
                    logger.error(
                        "activity event loop unresponsive root=%s for=%.1fs watchdog=%.0fs; "
                        "stopping Temporal heartbeats",
                        self.root,
                        unresponsive_for,
                        self.loop_watchdog_seconds,
                    )
                    return
            self._stop.wait(self.interval)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None


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

    def _finalize_interrupted(
        self,
        root: str,
        task: TaskRecord,
        reason: str,
        engine: Engine | None,
        host: BrowserHost | None,
    ) -> str:
        """Lease-free, generation-fenced terminal write used after retry/cancel exhaustion."""
        lease_generation = (
            engine.ctx.lease_generation
            if engine is not None
            else host.generation
            if host is not None
            else None
        )
        logger.warning(
            "collection activity interrupted root=%s reason=%s engine=%s generation=%s",
            root,
            reason,
            engine is not None,
            lease_generation,
        )
        try:
            if engine is not None:
                return engine.finish(force=True, failure_reason=reason)
            return self.repo.finalize_interrupted(
                root,
                task.attempt_id,
                reason,
                lease_generation=lease_generation,
            )
        except CollectorError:
            try:
                return self.repo.finalize_interrupted(
                    root,
                    task.attempt_id,
                    reason,
                    lease_generation=lease_generation,
                )
            except CollectorError:
                try:
                    return self.repo.finalize_interrupted(
                        root,
                        task.attempt_id,
                        reason,
                        publish=False,
                        lease_generation=lease_generation,
                    )
                except CollectorError as final_error:
                    logger.error(
                        "collection activity finalization failed root=%s reason=%s error=%s:%s",
                        root,
                        reason,
                        final_error.code,
                        final_error.reason,
                    )
                    return self.repo.get(root).state

    @activity.defn(name="collect_segment_v1")
    async def collect(self, root: str) -> str:
        # The heartbeat thread is independent of the asyncio loop.  The Activity's synchronous
        # checkpoint reads/writes can stall the loop for seconds, which previously also stalled
        # the only Temporal heartbeat sender and produced a false heartbeat timeout.
        heartbeat = TemporalHeartbeat(root)
        heartbeat.start()
        try:
            return await self._collect(root)
        finally:
            heartbeat.stop()

    async def _collect(self, root: str) -> str:
        task = await asyncio.to_thread(self.repo.get, root)
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
        unit = await asyncio.to_thread(self.repo.unit, task.execution_unit_id)
        if task.task_kind.value not in (unit.get("allowed_task_kinds") or []):
            with self.repo.edit(root) as (current, _):
                current.state = TaskStatus.FAILED
                current.failure_reason = "TASK_KIND_NOT_ALLOWED"
            return TaskStatus.FAILED
        higher_priority = task.task_kind != TaskKind.COLLECTION and await asyncio.to_thread(
            self.repo.has_runnable_higher_priority_task,
            task.execution_unit_id,
            root,
            task.task_kind,
        )
        if higher_priority:
            # Do not acquire or open the browser while normal collection (or a manual update for
            # a scheduled batch) is runnable.  The Workflow's 30-second loop retries this activity.
            with self.repo.edit(root) as (current, _):
                current.state = TaskStatus.QUEUED
                current.failure_reason = None
            return TaskStatus.QUEUED
        registry = PlatformRegistry.model_validate_json(self.config.registry_path.read_text())
        try:
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
                task = await asyncio.to_thread(self.repo.get, root)
            required_scopes = {"session", "search", "profile_identity"}
            required_scopes.update(f"profile_module:{item.key}" for item in registry.modules)
            required_scopes.update(f"featured:{item.key.value}" for item in registry.featured)
            await asyncio.to_thread(
                self.repo.require_contract, registry.contract_version, required_scopes
            )
            await ensure_line(self.config)
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
        evidence = build_evidence_sink(self.config.evidence, self.repo, self.private_root.parent)
        covers = CoverPipeline(
            self.repo, build_cover_store(self.config.covers, self.repo, self.private_root.parent)
        )
        main_task = asyncio.current_task()
        heartbeat_error: CollectorError | None = None
        host: BrowserHost | None = None
        engine: Engine | None = None

        async def guard() -> None:
            if not host:
                raise CollectorError("LEASE_LOST", "BROWSER_HOST_NOT_STARTED")
            await renew_lease(host)
            if engine and host.mode == "collect":
                await asyncio.to_thread(engine.guard)

        async def heartbeat() -> None:
            nonlocal heartbeat_error
            while True:
                scheduled = time.monotonic()
                await asyncio.sleep(15)
                # If the loop was blocked (typically by a synchronous checkpoint transfer), the
                # sleep overshoots by exactly that stall.  Log it so the next incident has a
                # measured event-loop lag instead of an unexplained heartbeat timeout.
                lag = time.monotonic() - scheduled - 15
                if lag >= 2.0:
                    logger.warning("activity event loop stalled root=%s lag=%.1fs", root, lag)
                started = time.monotonic()
                try:
                    # Restored loop-side Temporal heartbeat.  The dedicated thread above can only
                    # schedule on this loop; this direct call is the path that actually reaches the
                    # server whenever the loop is running.  A send failure must not be treated as a
                    # lease failure: Temporal owns the heartbeat timeout and retry budget.
                    try:
                        activity.heartbeat(root)
                    except Exception as exc:  # noqa: BLE001 - activity may already be gone
                        logger.warning(
                            "temporal heartbeat send failed root=%s type=%s",
                            root,
                            type(exc).__name__,
                        )
                    await guard()
                except CollectorError as exc:
                    heartbeat_error = exc
                    logger.warning(
                        "activity heartbeat failed root=%s reason=%s elapsed=%.1fs",
                        root,
                        exc,
                        time.monotonic() - started,
                    )
                    if main_task:
                        main_task.cancel()
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - diagnostics must never kill the loop silently
                    heartbeat_error = CollectorError(
                        "RESOURCE_UNAVAILABLE", f"HEARTBEAT_{type(exc).__name__}"
                    )
                    logger.warning(
                        "activity heartbeat unexpected root=%s type=%s elapsed=%.1fs",
                        root,
                        type(exc).__name__,
                        time.monotonic() - started,
                    )
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
                    self.config,
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
                                network_mode=self.config.network_mode,
                                budget=self.config.budget,
                            )
                            assert host.browser
                            adapter = BrowserAdapter(
                                host.browser,
                                registry,
                                self.config.expected_account_id,
                                guard,
                                on_session_health=host.observe_session,
                                manually_attested_account_id=self.config.manually_attested_account_id,
                            )
                            adapter.creator_interval_seconds = (
                                self.challenge_policy.creator_interval_seconds
                            )
                            adapter.search_page = host.take_collection_page()
                            engine = Engine(
                                self.repo, adapter, ctx, evidence=evidence, covers=covers
                            )
                            try:
                                if task.task_kind == TaskKind.COLLECTION:
                                    return await engine.run()
                                return await engine.run_update()
                            except CollectorError as exc:
                                if exc.code in {
                                    "ACCOUNT_LOGIN_REQUIRED",
                                    "ACCOUNT_MISMATCH",
                                    "PLATFORM_SECURITY_CHALLENGE",
                                }:
                                    maintenance_page = adapter.detail_page or adapter.search_page
                                    if maintenance_page:
                                        adapter.detach_page(maintenance_page)
                                    await host.enter_maintenance(
                                        exc.code, "browser-host:" + task.attempt_id
                                    )
                                    engine.record_error(exc)
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
                                # A transport failure used to collapse into a bare
                                # RESOURCE_UNAVAILABLE:BROWSER_TRANSPORT, leaving nothing in the
                                # log.  Diagnosing the 2026-10-13 zero-candidate incident required
                                # temporarily patching this line, because the decisive detail (the
                                # page had been navigated to `https://www.xingtu.cn/?redirect_uri=...`)
                                # existed only inside this exception.  Keep it.
                                logger.warning(
                                    "browser transport failure attempt=%s %s: %s",
                                    activity.info().attempt,
                                    type(exc).__name__,
                                    exc,
                                )
                                if activity.info().attempt < 4:
                                    raise CollectorError(
                                        "RESOURCE_UNAVAILABLE", "BROWSER_TRANSPORT"
                                    ) from exc
                                return engine.record_error(
                                    CollectorError("PLATFORM_PAGE_CHANGED", "BROWSER_FAILURE")
                                )
                            finally:
                                if host.mode == "collect":
                                    await adapter.close()
                    finally:
                        pulse.cancel()
                        with suppress(asyncio.CancelledError):
                            await pulse
            except asyncio.CancelledError:
                # Distinguish a terminal heartbeat/attempt failure from a transient worker
                # shutdown or a user cancel.  Temporal retries worker-shutdown cancellations;
                # finalizing here would be an incorrect terminal state and could lose a retry.
                try:
                    details = activity.cancellation_details()
                except Exception:  # noqa: BLE001 - keep the Activity fail-closed if details are unavailable
                    details = None
                if not should_finalize_cancelled(
                    details, heartbeat_error, attempt=activity.info().attempt
                ):
                    logger.warning(
                        "collection activity cancellation deferred root=%s details=%s heartbeat=%s",
                        root,
                        details,
                        heartbeat_error,
                    )
                    raise
                # Temporal can cancel an Activity after its heartbeat timeout, and the lease may
                # already have been released by the interrupted attempt.  Never leave the root
                # task in COLLECTING: finalize from the persisted checkpoint, publishing any
                # complete creator data that was already collected.
                reason = (
                    (heartbeat_error.reason or heartbeat_error.code)
                    if heartbeat_error
                    else "ACTIVITY_CANCELLED_OR_HEARTBEAT_TIMEOUT"
                )
                return self._finalize_interrupted(root, task, reason, engine, host)
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
            except Exception as exc:  # noqa: BLE001 - retry budget is owned by the Workflow
                logger.warning(
                    "unhandled collection activity failure root=%s attempt=%s type=%s",
                    root,
                    activity.info().attempt,
                    type(exc).__name__,
                )
                if activity.info().attempt < 4:
                    raise
                return self._finalize_interrupted(
                    root, task, f"ACTIVITY_{type(exc).__name__}", engine, host
                )


def _pending_dispatches(repo: Repository, unit_id: str) -> list[dict[str, Any]]:
    with repo.connect() as conn:
        return conn.execute(
            "SELECT d.* FROM task_dispatches d JOIN root_tasks r USING(root_task_id) "
            "WHERE d.sent=false AND r.unit_id=%s "
            "ORDER BY CASE r.task_kind "
            "WHEN 'collection' THEN 0 WHEN 'manual_update' THEN 1 "
            "WHEN 'scheduled_update' THEN 2 ELSE 3 END, r.updated_at,d.segment",
            (unit_id,),
        ).fetchall()


def _mark_dispatch_started(repo: Repository, root: str, segment: object) -> None:
    with repo.connect() as conn:
        # ``workflow_started_at`` is the durable fact the cancel path uses to decide whether a
        # collection process can still be holding this task (FIX-01 P1-B).
        conn.execute(
            """UPDATE task_dispatches SET sent=true,workflow_started_at=now()
            WHERE root_task_id=%s AND segment=%s""",
            (root, segment),
        )


def _cancelling_roots(repo: Repository, unit_id: str) -> list[dict[str, Any]]:
    with repo.connect() as conn:
        return conn.execute(
            "SELECT root_task_id FROM root_tasks WHERE state='CANCELLING' AND unit_id=%s",
            (unit_id,),
        ).fetchall()


async def dispatch(repo: Repository, client: Client, queue: str) -> None:
    unit_id = queue.removeprefix("xingtu-")
    # This poll loop shares the Temporal SDK event loop with async Activities.  All psycopg work
    # must therefore stay off that loop; a slow Tailnet connection previously starved Activity
    # heartbeats even though the browser itself was still making progress.
    rows = await asyncio.to_thread(_pending_dispatches, repo, unit_id)
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
        await asyncio.to_thread(_mark_dispatch_started, repo, root, row["segment"])
    # Cancellation must also wake workflows paused on a signal.
    cancelling = await asyncio.to_thread(_cancelling_roots, repo, unit_id)
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
                await asyncio.to_thread(_finalise_cancelled, repo, root)
            continue
        await asyncio.to_thread(_finalise_cancelled, repo, root)


def _finalise_cancelled(repo: Repository, root: str) -> None:
    with repo.edit(root) as (task, _):
        task.state = TaskStatus.CANCELLED


async def run_worker(
    repo: Repository, config: UnitConfig, address: str, private_root: Path
) -> None:
    client = await Client.connect(address)
    queue = f"xingtu-{config.unit_id}"
    activities = Activities(repo, config, private_root)
    logger.info("collection worker polling %s on %s", queue, address)
    async with Worker(
        client,
        task_queue=queue,
        workflows=[CollectionWorkflow],
        activities=[activities.collect],
        max_concurrent_activities=1,
    ):
        while True:
            try:
                # Local (normal collection/manual) dispatches start first.  Only then does this
                # worker claim one unassigned update task from the shared pool.
                await dispatch(repo, client, queue)
                if await asyncio.to_thread(repo.claim_unassigned_update, config.unit_id):
                    await dispatch(repo, client, queue)
            except Exception as exc:  # noqa: BLE001 - the consumer must survive any tick error
                logger.warning("collection dispatch tick failed: %s", type(exc).__name__)
            await asyncio.sleep(2)
