from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from pathlib import Path

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
from .domain import CollectorError, ExecutionContext, TaskRecord, TaskStatus
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
        registry = PlatformRegistry.model_validate_json(self.config.registry_path.read_text())
        try:
            registry.require_enabled(live=True)
            registry.capabilities.validate_plan(task.plan, live=True)
            versions_changed = (
                task.checkpoint.adapter_version != registry.adapter_version
                or task.checkpoint.contract_version != registry.contract_version
            )
            if versions_changed:
                with self.repo.edit(root) as (current, _):
                    if not adopt_compatible_legacy_checkpoint(current, registry):
                        raise CollectorError("PLATFORM_PAGE_CHANGED", "VERSION_MISMATCH")
                task = self.repo.get(root)
            required_scopes = {"session", "search", "profile_identity"}
            required_scopes.update(f"profile_module:{item.key}" for item in registry.modules)
            required_scopes.update(f"featured:{item.key.value}" for item in registry.featured)
            self.repo.require_contract(registry.contract_version, required_scopes)
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

        unit = self.repo.unit(task.execution_unit_id)
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
                                capability_version=task.plan.capability_version,
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
                                return await engine.run()
                            except CollectorError as exc:
                                if exc.code in {
                                    "ACCOUNT_LOGIN_REQUIRED",
                                    "ACCOUNT_MISMATCH",
                                    "PLATFORM_SECURITY_CHALLENGE",
                                }:
                                    maintenance_page = adapter.detail_page or adapter.search_page
                                    if maintenance_page:
                                        adapter.detach_page(maintenance_page)
                                    host.enter_maintenance(
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
                                        try:
                                            await host.maintain_and_promote(
                                                timeout=self.challenge_policy.timeout_seconds,
                                                actor="browser-host:" + task.attempt_id,
                                                page=maintenance_page,
                                                challenge_handler=challenge_handler,
                                            )
                                        except CollectorError as recovery_error:
                                            reason = (
                                                recovery_error.code
                                                if recovery_error.code.startswith(
                                                    "SECURITY_CHALLENGE_"
                                                )
                                                else "SECURITY_CHALLENGE_UNKNOWN"
                                            )
                                            challenge_handler.failed(root, task.attempt_id, reason)
                                            return engine.partial_complete(reason)
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
            "WHERE d.sent=false AND r.unit_id=%s ORDER BY r.updated_at,d.segment",
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
                await dispatch(repo, client, queue)
            except Exception as exc:  # noqa: BLE001 - the consumer must survive any tick error
                logger.warning("collection dispatch tick failed: %s", type(exc).__name__)
            await asyncio.sleep(2)
