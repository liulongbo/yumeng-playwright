from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path

from playwright.async_api import Error as BrowserError
from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.worker import Worker

from .adapter import BrowserAdapter
from .browser_host import BrowserHost
from .contracts import PlatformRegistry
from .covers import CoverPipeline, build_cover_store
from .domain import CollectorError, ExecutionContext, TaskStatus
from .engine import Engine
from .evidence import build_evidence_sink
from .repository import Repository
from .runtime import UnitConfig, ensure_line
from .workflow import CollectionWorkflow


class Activities:
    def __init__(self, repo: Repository, config: UnitConfig, private_root: Path):
        self.repo, self.config, self.private_root = repo, config, private_root
        # Temporal is configured for one Activity at a time, and this process lock also makes the
        # per-unit BrowserHost ownership explicit for direct tests/callers.
        self.host_lock = asyncio.Lock()

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
            if engine:
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
        maintenance = unit["state"] in {"NEEDS_LOGIN", "ACCOUNT_MISMATCH"}
        if maintenance:
            with self.repo.edit(root) as (current, _):
                if current.attempt_id != task.attempt_id:
                    return current.state
                current.state = (
                    TaskStatus.WAITING_FOR_ACCOUNT
                    if unit["state"] == "ACCOUNT_MISMATCH"
                    else TaskStatus.WAITING_FOR_LOGIN
                )
                current.failure_reason = (
                    "ACCOUNT_MISMATCH"
                    if unit["state"] == "ACCOUNT_MISMATCH"
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
                    try:
                        if host.mode == "maintenance":
                            await host.maintain_and_promote(
                                timeout=900, actor="browser-host:" + task.attempt_id
                            )
                        while True:
                            with self.repo.edit(root) as (current, _):
                                if current.state in {
                                    TaskStatus.WAITING_FOR_LOGIN,
                                    TaskStatus.WAITING_FOR_ACCOUNT,
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
                                    await host.maintain_and_promote(
                                        timeout=900,
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
                        if exc.code in {"ACCOUNT_LOGIN_REQUIRED", "PLATFORM_SECURITY_CHALLENGE"}
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
            await handle.signal(CollectionWorkflow.wake)
        with repo.connect() as conn:
            conn.execute(
                "UPDATE task_dispatches SET sent=true WHERE root_task_id=%s AND segment=%s",
                (root, row["segment"]),
            )
    # Cancellation must also wake workflows paused on a signal.
    with repo.connect() as conn:
        cancelling = conn.execute(
            "SELECT root_task_id FROM root_tasks WHERE state='CANCELLING' AND unit_id=%s",
            (queue.removeprefix("xingtu-"),),
        ).fetchall()
    for row in cancelling:
        handle = client.get_workflow_handle(f"collect/{row['root_task_id']}")
        description = await handle.describe()
        if description.status == WorkflowExecutionStatus.RUNNING:
            await handle.signal(CollectionWorkflow.wake)
        else:
            with repo.edit(str(row["root_task_id"])) as (task, _):
                task.state = TaskStatus.CANCELLED


async def run_worker(
    repo: Repository, config: UnitConfig, address: str, private_root: Path
) -> None:
    client = await Client.connect(address)
    queue = f"xingtu-{config.unit_id}"
    activities = Activities(repo, config, private_root)
    async with Worker(
        client,
        task_queue=queue,
        workflows=[CollectionWorkflow],
        activities=[activities.collect],
        max_concurrent_activities=1,
    ):
        while True:
            await dispatch(repo, client, queue)
            await asyncio.sleep(2)
