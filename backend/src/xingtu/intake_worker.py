from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from temporalio import activity
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.worker import Worker

from .contracts import PlatformRegistry
from .domain import CollectorError, ProfileRequirement, TaskStatus
from .intake import IntakeGraph, LLMAdapter
from .intake_workflow import IntakeWorkflow
from .product_models import FieldError, P1WorkflowState
from .product_repository import ProductRepository

logger = logging.getLogger(__name__)


class IntakeProcessor:
    def __init__(
        self,
        repository: ProductRepository,
        registry: PlatformRegistry,
        adapter: LLMAdapter,
        *,
        execution_unit_id: str,
        profile_requirement: ProfileRequirement | None = None,
        platform_registries: dict[str, PlatformRegistry] | None = None,
        platform_profile_requirements: dict[str, ProfileRequirement] | None = None,
    ) -> None:
        self.repository = repository
        self.registry = registry
        self.adapter = adapter
        self.execution_unit_id = execution_unit_id
        self.profile_requirement = profile_requirement
        self.platform_registries = {
            "douyin_xingtu": registry,
            **(platform_registries or {}),
        }
        # `profile_requirement` is the Xingtu full-homepage field inventory.  It must never be
        # attached to another platform: a juxing task would then be required to collect Xingtu-only
        # modules and could never become COMPLETED.  Juxing P0 completeness is defined by its own
        # verified registry modules; a platform entry can override this explicitly when a real
        # per-platform inventory exists.
        self.platform_profile_requirements = dict(platform_profile_requirements or {})

    def _profile_requirement_for(self, platform: str) -> ProfileRequirement | None:
        if platform in self.platform_profile_requirements:
            return self.platform_profile_requirements[platform]
        if platform == "douyin_xingtu":
            return self.profile_requirement
        return None

    async def process(self, root_task_id: str) -> str:
        state = self.repository.load_intake(root_task_id)
        registry = self.platform_registries.get(state.requirement_form.platform)
        if registry is None:
            error = FieldError(
                code="PLATFORM_CONTRACT_NOT_AVAILABLE",
                path="platform",
                message=state.requirement_form.platform,
            )
            failed = state.model_copy(update={"outcome": "failed_model", "final_error": [error]})
            self.repository.fail_intake(failed, TaskStatus.FAILED_VALIDATION, [error])
            return TaskStatus.FAILED_VALIDATION
        try:
            self.repository.save_intake(state, TaskStatus.PARSING)
        except CollectorError as exc:
            if exc.code == "TASK_CANCELLED":
                return TaskStatus.CANCELLED
            raise

        async def checkpoint(updated: P1WorkflowState) -> None:
            self.repository.save_intake(updated, TaskStatus.PARSING)

        graph = IntakeGraph(
            registry.capabilities,
            self.adapter,
            self.repository,
            checkpoint=checkpoint,
        )
        try:
            result = await graph.run(state)
        except CollectorError as exc:
            if exc.code == "TASK_CANCELLED":
                return TaskStatus.CANCELLED
            error = FieldError(
                code="AI_PARSE_FAILED",
                path="intake",
                message=exc.code,
            )
            failed = state.model_copy(update={"outcome": "failed_model", "final_error": [error]})
            self.repository.fail_intake(failed, TaskStatus.FAILED, [error])
            return TaskStatus.FAILED
        except Exception as exc:  # noqa: BLE001 - terminal state must survive unexpected defects
            error = FieldError(
                code="AI_PARSE_FAILED",
                path="intake",
                message=type(exc).__name__,
            )
            failed = state.model_copy(update={"outcome": "failed_model", "final_error": [error]})
            self.repository.fail_intake(failed, TaskStatus.FAILED, [error])
            return TaskStatus.FAILED
        if result.outcome == "succeeded" and result.final_plan:
            try:
                self.repository.promote_intake(
                    result,
                    result.final_plan,
                    unit_id=self.execution_unit_id,
                    registry=registry,
                    profile_requirement=self._profile_requirement_for(
                        state.requirement_form.platform
                    ),
                )
            except CollectorError as exc:
                if exc.code == "TASK_CANCELLED":
                    return TaskStatus.CANCELLED
                # A failed promotion must leave a terminal, traceable state. Re-raising would fail
                # the Temporal workflow (maximum_attempts=1) and strand the root task in PARSING
                # with no failure_reason at all.
                return self._fail_after_promotion(result, exc.code, exc.reason)
            except Exception as exc:  # noqa: BLE001 - terminal state must survive defects
                return self._fail_after_promotion(result, type(exc).__name__, type(exc).__name__)
            return TaskStatus.QUEUED
        status = (
            TaskStatus.FAILED if result.outcome == "failed_model" else TaskStatus.FAILED_VALIDATION
        )
        self.repository.fail_intake(result, status, result.final_error)
        return status

    def _fail_after_promotion(self, state: P1WorkflowState, code: str, reason: str) -> TaskStatus:
        error = FieldError(code=code or "INTAKE_PROMOTE_FAILED", path="promote", message=reason)
        failed = state.model_copy(update={"outcome": "failed_model", "final_error": [error]})
        self.repository.fail_intake(failed, TaskStatus.FAILED, [error])
        logger.warning(
            "intake promotion failed for %s (%s); task finalised as FAILED",
            state.root_task_id,
            code,
        )
        return TaskStatus.FAILED


class IntakeActivities:
    def __init__(self, processor: IntakeProcessor):
        self.processor = processor

    @activity.defn(name="process_intake_v1")
    async def process(self, root_task_id: str) -> str:
        return await self.processor.process(root_task_id)


async def dispatch_intakes(repository: ProductRepository, client: Client, *, queue: str) -> int:
    """Start one Temporal workflow per unsent intake dispatch. Returns how many were dispatched.

    A per-task start failure is recorded and left ``sent=false`` so the next poll tick retries it;
    it must never abort the whole loop, because that would silently kill the only consumer and
    look exactly like "no worker is running".
    """
    dispatched = 0
    for row in repository.pending_intake_dispatches():
        root_task_id = str(row["root_task_id"])
        try:
            await client.start_workflow(
                IntakeWorkflow.run,
                root_task_id,
                id=str(row["workflow_id"]),
                task_queue=queue,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
        except WorkflowAlreadyStartedError:
            # The workflow id already exists: another dispatcher owns it, so it is dispatched.
            pass
        except Exception as exc:  # noqa: BLE001 - one bad task must not stop the consumer
            logger.warning("intake dispatch failed for %s: %s", root_task_id, type(exc).__name__)
            repository.record_intake_dispatch_failure(root_task_id, type(exc).__name__)
            continue
        repository.mark_intake_dispatched(root_task_id)
        dispatched += 1
    return dispatched


async def run_intake_worker(
    repository: ProductRepository,
    processor: IntakeProcessor,
    temporal_address: str,
    *,
    queue: str = "xingtu-intake",
) -> None:
    client = await Client.connect(temporal_address)
    activities = IntakeActivities(processor)
    logger.info("intake worker polling %s on %s", queue, temporal_address)
    async with Worker(
        client,
        task_queue=queue,
        workflows=[IntakeWorkflow],
        activities=[activities.process],
        max_concurrent_activities=4,
    ):
        while True:
            try:
                dispatched = await dispatch_intakes(repository, client, queue=queue)
                if dispatched:
                    logger.info("dispatched %s intake task(s)", dispatched)
            except Exception as exc:  # noqa: BLE001 - the consumer must survive any tick error
                logger.warning("intake dispatch tick failed: %s", type(exc).__name__)
            await asyncio.sleep(2)


def load_profile_requirement(path: Path | None) -> ProfileRequirement | None:
    if path is None:
        return None
    return ProfileRequirement.model_validate_json(path.read_text())
