from __future__ import annotations

import asyncio
import time
from typing import Any

from .adapter import Adapter
from .covers import CoverPipeline
from .domain import (
    Candidate,
    CandidateDiagnostic,
    CollectionStatus,
    CollectorError,
    CoverRef,
    CoverStatus,
    ExecutionContext,
    FieldObservation,
    FieldStatus,
    ModuleObservation,
    TaskRecord,
    TaskStatus,
    uid,
)
from .evidence import EvidenceSink, EvidenceSummary, schema_keys
from .repository import Repository

# Diagnostics worth an isolated, allowlisted artifact; pauses and cancellation are not failures.
EVIDENCE_ERROR_CODES = frozenset(
    {
        "PLATFORM_PAGE_CHANGED",
        "PLATFORM_CONDITION_MISMATCH",
        "ACCOUNT_LOGIN_REQUIRED",
        "PLATFORM_SECURITY_CHALLENGE",
        "PLATFORM_RATE_LIMITED",
        "MODULE_COLLECTION_FAILED",
    }
)


def rejected_response_diagnostic(error: CollectorError | None) -> dict[str, Any]:
    """Allowlisted facts about the response that was rejected, or an empty mapping.

    The collector attaches at most one diagnostic per registered request. Only the request key,
    HTTP status, content-type kind, the platform's own business code path/value and the response's
    top-level key names are kept; bodies, URLs, query values and headers never are.
    """

    for item in getattr(error, "diagnostics", []) or []:
        as_evidence = getattr(item, "as_evidence", None)
        if callable(as_evidence):
            return dict(as_evidence())
    return {}


def response_key_paths(diagnostic: dict[str, Any]) -> list[str]:
    keys = diagnostic.get("root_keys")
    return [str(key) for key in keys] if isinstance(keys, list) else []


class Engine:
    """Activity-side serial coordinator. All durable writes are fenced PostgreSQL transactions."""

    def __init__(
        self,
        repository: Repository,
        adapter: Adapter,
        ctx: ExecutionContext,
        *,
        active_budget: float | None = None,
        scan_budget: int | None = None,
        evidence: EvidenceSink | None = None,
        covers: CoverPipeline | None = None,
    ):
        self.repo, self.adapter, self.ctx = repository, adapter, ctx
        self.evidence = evidence
        self.covers = covers
        self.root = ctx.root_task_id
        task = repository.get(self.root)
        self.last_tick = time.monotonic()
        self.last_metrics: dict[str, int] = {}
        # Appendix A defaults live in the execution context budget, not in this class.
        self.active_budget = (
            active_budget if active_budget is not None else ctx.budget.active_seconds
        )
        self.scan_budget = (
            scan_budget
            if scan_budget is not None
            else ctx.budget.candidate_scan(task.plan.target_count)
        )
        self.identity_failure_streak = repository.capability_has_failure_streak(
            ctx.contract_version, "profile_identity"
        )

    def record_evidence(
        self,
        kind: str,
        *,
        operation_id: str,
        failure_reason: str | None = None,
        payload: object | None = None,
        error: CollectorError | None = None,
    ) -> str | None:
        if not self.evidence:
            return None
        diagnostic = rejected_response_diagnostic(error) if error else {}
        # Storage failures surface as STORAGE_UNAVAILABLE; evidence is never silently dropped.
        return self.evidence.save(
            EvidenceSummary(
                root_task_id=self.ctx.root_task_id,
                task_id=self.ctx.task_id,
                attempt_id=self.ctx.attempt_id,
                execution_unit_id=self.ctx.execution_unit_id,
                operation_id=operation_id,
                contract_version=self.ctx.contract_version,
                source_contract=self.ctx.contract_version,
                kind="failure" if kind == "failure" else "summary",
                schema_keys=schema_keys(payload),
                failure_reason=failure_reason,
                response_keys=response_key_paths(diagnostic),
                status_code=diagnostic.get("http_status") if diagnostic else None,
                diagnostic=diagnostic,
            )
        )

    def guard(self) -> None:
        self.charge(time.monotonic())
        if self.repo.get(self.root).checkpoint.active_seconds >= self.active_budget:
            raise CollectorError("BUDGET_EXHAUSTED", "ACTIVE_TIME")

    def charge(self, start: float) -> None:
        # Charge only while this activity is active; waiting between activities is excluded.
        now = time.monotonic()
        with self.repo.edit(self.root, self.ctx) as (task, _):
            task.checkpoint.active_seconds += max(0, now - self.last_tick)
            metrics = getattr(self.adapter, "operation_metrics", {})
            for source, target in (
                ("requests", "observed_requests"),
                ("responses", "observed_responses"),
                ("navigations", "navigation_count"),
                ("duplicate_requests", "duplicate_request_count"),
                ("featured_loads", "featured_load_count"),
                ("cover_requests", "cover_request_count"),
            ):
                value = int(metrics.get(source, 0))
                delta = max(0, value - self.last_metrics.get(source, 0))
                setattr(task.checkpoint, target, getattr(task.checkpoint, target) + delta)
        self.last_metrics = dict(metrics)
        self.last_tick = now

    def rescan(self, reason: str = "CURSOR_INVALID") -> None:
        with self.repo.edit(self.root, self.ctx) as (task, _):
            cp = task.checkpoint
            cp.search_generation += 1
            cp.cursor = None
            cp.visited_cursors = []
            cp.exhausted = False
            cp.exhaustion_evidence_refs = []
            cp.search_stop_reason = None
            cp.no_progress_pages = 0
            cp.rescan_reasons.append(reason)

    def ingest_pending_page(self) -> None:
        with self.repo.edit(self.root, self.ctx) as (task, _):
            cp = task.checkpoint
            page = cp.pending_page
            if not page:
                return
            existing = {c.ref.platform_creator_id for c in cp.candidates}
            scanned = set(cp.scanned_ids)
            remaining = []
            for index, ref in enumerate(page.candidates):
                identity = ref.platform_creator_id
                if identity not in scanned:
                    if len(scanned) >= self.scan_budget:
                        remaining = page.candidates[index:]
                        break
                    cp.scanned_ids.append(identity)
                    scanned.add(identity)
                if identity not in existing:
                    ref = ref.model_copy(update={"first_position": len(cp.candidates)})
                    cp.candidates.append(Candidate(ref=ref))
                    existing.add(identity)
            if remaining:
                page.candidates = remaining
            else:
                cp.pending_page = None

    async def rebuild_conditions(self) -> None:
        """§5.2.3: rebuild and read back the original conditions before scanning."""
        task = self.repo.get(self.root)
        start = time.monotonic()
        compatible = await self.adapter.prepare(task.plan, task.checkpoint, self.ctx)
        self.charge(start)
        if compatible:
            return
        # A verified invalid cursor restarts the scan; seen identities keep their first position.
        self.rescan("CURSOR_INVALID")
        task = self.repo.get(self.root)
        start = time.monotonic()
        if not await self.adapter.prepare(task.plan, task.checkpoint, self.ctx):
            raise CollectorError("PLATFORM_PAGE_CHANGED", "CANNOT_REBUILD_CONDITIONS")
        self.charge(start)

    async def run(self) -> str:
        required_scopes = {"session", "search", "profile_identity"}
        required_scopes.update(f"profile_module:{key}" for key in self.adapter.module_keys)
        required_scopes.update(f"featured:{key}" for key in self.adapter.featured_keys)
        self.repo.require_contract(self.ctx.contract_version, required_scopes)
        with self.repo.edit(self.root, self.ctx) as (current, _):
            if current.checkpoint.profile_module_keys != self.adapter.module_keys:
                raise CollectorError("PLATFORM_PAGE_CHANGED", "MODULE_REGISTRY_CHANGED")
            recorded = current.checkpoint.profile_checkpoint_versions
            if recorded and recorded != self.adapter.module_checkpoint_versions:
                raise CollectorError("PLATFORM_PAGE_CHANGED", "MODULE_CHECKPOINT_CHANGED")
            current.checkpoint.profile_field_keys = self.adapter.module_fields
            current.checkpoint.profile_checkpoint_versions = self.adapter.module_checkpoint_versions
            if current.checkpoint.featured_collection_types != self.adapter.featured_keys:
                raise CollectorError("PLATFORM_PAGE_CHANGED", "FEATURED_REGISTRY_CHANGED")
            featured_recorded = current.checkpoint.featured_checkpoint_versions
            if featured_recorded and featured_recorded != self.adapter.featured_checkpoint_versions:
                raise CollectorError("PLATFORM_PAGE_CHANGED", "FEATURED_CHECKPOINT_CHANGED")
            current.checkpoint.featured_card_fields = self.adapter.featured_card_fields
            current.checkpoint.featured_checkpoint_versions = (
                self.adapter.featured_checkpoint_versions
            )
        self.guard()
        await self.rebuild_conditions()
        while True:
            self.guard()
            task = self.repo.get(self.root)
            # Finish already valid but incomplete creators before enforcing new-start target.
            candidate = next(
                (
                    c
                    for c in task.checkpoint.candidates
                    if c.valid and c.state in {"pending", "collecting"}
                ),
                None,
            )
            if candidate is None and task.valid_count < task.plan.target_count:
                candidate = next(
                    (c for c in task.checkpoint.candidates if c.state in {"pending", "collecting"}),
                    None,
                )
            if candidate:
                await self.collect(candidate.ref.platform_creator_id)
                interval = float(getattr(self.adapter, "creator_interval_seconds", 0.0))
                if interval:
                    await asyncio.sleep(interval)
                continue
            if task.valid_count >= task.plan.target_count:
                return self.finish()
            if task.checkpoint.pending_page:
                before = len(task.checkpoint.scanned_ids)
                self.ingest_pending_page()
                if (
                    self.repo.get(self.root).checkpoint.pending_page is not None
                    and len(self.repo.get(self.root).checkpoint.scanned_ids) == before
                ):
                    raise CollectorError("BUDGET_EXHAUSTED", "CANDIDATE_SCAN")
                continue
            if task.checkpoint.exhausted:
                return self.finish()
            if len(task.checkpoint.scanned_ids) >= self.scan_budget:
                raise CollectorError("BUDGET_EXHAUSTED", "CANDIDATE_SCAN")
            no_progress_limit_reached = False
            with self.repo.edit(self.root, self.ctx) as (current, _):
                current.state = TaskStatus.SEARCHING
            start = time.monotonic()
            try:
                page = await self.adapter.search(task.plan, task.checkpoint, self.ctx)
            except CollectorError as exc:
                self.charge(start)
                if exc.code == "SEARCH_CAPABILITY_LIMIT":
                    with self.repo.edit(self.root, self.ctx) as (current, _):
                        current.checkpoint.search_stop_reason = "SEARCH_CAPABILITY_LIMIT"
                    return self.finish()
                if exc.code == "PLATFORM_PAGE_CHANGED" and exc.reason == "SEARCH_CURSOR_INVALID":
                    # §5.2.3: an expired cursor re-scans from the start under the same conditions.
                    self.rescan("CURSOR_INVALID")
                    await self.rebuild_conditions()
                    continue
                raise
            self.charge(start)
            if page.exhausted:
                # Upload and verify evidence before the checkpoint transaction references it.
                key = self.record_evidence("summary", operation_id=page.operation_id)
                if key:
                    page.exhaustion_evidence_refs = [*page.exhaustion_evidence_refs, key]
            with self.repo.edit(self.root, self.ctx) as (current, _):
                cp = current.checkpoint
                if page.conditions_digest != cp.conditions_digest:
                    raise CollectorError("PLATFORM_CONDITION_MISMATCH")
                if page.search_generation != cp.search_generation:
                    raise CollectorError("PLATFORM_PAGE_CHANGED", "STALE_SEARCH_GENERATION")
                if page.operation_id in cp.processed_operations:
                    raise CollectorError("PLATFORM_PAGE_CHANGED", "DUPLICATE_OPERATION")
                if page.current_checkpoint != cp.cursor:
                    raise CollectorError("PLATFORM_PAGE_CHANGED", "CHECKPOINT_MISMATCH")
                if not page.exhausted and page.next_checkpoint in [cp.cursor, *cp.visited_cursors]:
                    raise CollectorError("PLATFORM_PAGE_CHANGED", "CURSOR_LOOP")
                seen = {c.ref.platform_creator_id for c in cp.candidates}
                has_new = any(c.platform_creator_id not in seen for c in page.candidates)
                # §5.2.2: a batch without a new identity is neither exhaustion nor by itself a
                # contract failure - a §5.2.3 rescan re-visits known identities by design.
                # Repeated cursors are rejected as CURSOR_LOOP above; otherwise the scan and
                # active budgets bound progress and non-exhaustion is never claimed from it.
                cp.no_progress_pages = 0 if has_new else cp.no_progress_pages + 1
                # A cursor-expiry rescan is expected to replay the already-known prefix. Give it
                # enough room to reach the old frontier; normal forward paging still stops after
                # two consecutive pages without a new creator identity.
                no_progress_limit = max(2, len(cp.candidates) + 1) if cp.search_generation else 2
                no_progress_limit_reached = cp.no_progress_pages >= no_progress_limit
                cp.visited_cursors.append(cp.cursor)
                cp.cursor = page.next_checkpoint
                cp.exhausted = page.exhausted
                cp.exhaustion_evidence_refs = page.exhaustion_evidence_refs
                cp.diagnostics.extend(page.unidentified)
                cp.processed_operations.append(page.operation_id)
                cp.pending_page = page
            self.ingest_pending_page()
            if no_progress_limit_reached:
                # Preserve the observed pages/checkpoint, but do not misreport a changing or
                # repeated result set as platform exhaustion.
                raise CollectorError("PLATFORM_PAGE_CHANGED", "SEARCH_NO_PROGRESS")

    async def collect(self, identity: str) -> None:
        """Collect one creator with bounded identity retries and candidate-scoped failure."""
        for attempt in range(1, 4):
            try:
                await self._collect_once(identity)
                if self.identity_failure_streak:
                    self.repo.record_capability_success(
                        self.ctx.contract_version, "profile_identity"
                    )
                    self.identity_failure_streak = False
                return
            except CollectorError as exc:
                if not (
                    exc.code == "PLATFORM_PAGE_CHANGED" and exc.reason == "IDENTITY_UNREADABLE"
                ):
                    raise
                evidence_ref = self.record_evidence(
                    "failure",
                    operation_id=uid(),
                    failure_reason=f"IDENTITY_UNREADABLE:attempt={attempt}",
                )
                with self.repo.edit(self.root, self.ctx) as (task, _):
                    candidate = next(
                        c
                        for c in task.checkpoint.candidates
                        if c.ref.platform_creator_id == identity
                    )
                    candidate.retry_count = min(attempt, 2)
                    candidate.failure_reason = "IDENTITY_UNREADABLE"
                    if evidence_ref:
                        task.checkpoint.diagnostics.append(
                            CandidateDiagnostic(
                                reason="CANDIDATE_IDENTITY_UNREADABLE",
                                detail=f"profile identity attempt {attempt} failed",
                                source_ref=evidence_ref,
                                operation_id=uid(),
                            )
                        )
                if attempt == 1:
                    # Identity DOM absence can be caused by logout, an account switch or a
                    # challenge. Prove the protected session again before treating it as a
                    # creator-scoped transient and opening a fresh detail page.
                    await self.adapter.recheck_session()
                if attempt < 3:
                    self.identity_failure_streak = True
                    continue
                with self.repo.edit(self.root, self.ctx) as (task, _):
                    candidate = next(
                        c
                        for c in task.checkpoint.candidates
                        if c.ref.platform_creator_id == identity
                    )
                    candidate.state = "failed"
                    candidate.failure_reason = "IDENTITY_UNREADABLE"
                breaker = self.repo.record_capability_failure(
                    self.ctx.contract_version,
                    "profile_identity",
                    identity,
                    self.ctx.lease_generation,
                    "IDENTITY_UNREADABLE",
                )
                if breaker == "SUSPECTED":
                    raise CollectorError(
                        "RESOURCE_UNAVAILABLE", "CONTRACT_SCOPE_SUSPECTED:profile_identity"
                    ) from exc
                if breaker == "DISABLED":
                    raise CollectorError(
                        "PLATFORM_PAGE_CHANGED", "CONTRACT_SCOPE_DISABLED:profile_identity"
                    ) from exc
                return

    async def _collect_once(self, identity: str) -> None:
        with self.repo.edit(self.root, self.ctx) as (task, _):
            candidate = next(
                c for c in task.checkpoint.candidates if c.ref.platform_creator_id == identity
            )
            candidate.state = "collecting"
            task.state = TaskStatus.COLLECTING
            ref = candidate.ref.model_copy(deep=True)
            already_complete = candidate.valid and self.repo.pipeline_complete(task, identity)
            if already_complete:
                candidate.state = "done"
                candidate.failure_reason = None
                return
        start = time.monotonic()
        try:
            async with self.adapter.profile(ref, self.ctx):
                for key in self.adapter.module_keys:
                    self.charge(start)
                    start = time.monotonic()
                    self.guard()
                    task = self.repo.get(self.root)
                    candidate = next(
                        c
                        for c in task.checkpoint.candidates
                        if c.ref.platform_creator_id == identity
                    )
                    old = candidate.modules.get(key)
                    if old and old.complete:
                        continue
                    module_started = time.monotonic()
                    try:
                        observation = await self.adapter.collect_module(key, ref, self.ctx)
                        self.repo.record_capability_success(
                            self.ctx.contract_version, f"profile_module:{key}"
                        )
                    except CollectorError as exc:
                        optional_schema_failure = (
                            key != self.adapter.module_keys[0]
                            and exc.code == "PLATFORM_PAGE_CHANGED"
                            and exc.reason == "RESPONSE_SCHEMA_MISMATCH"
                        )
                        if exc.code != "MODULE_COLLECTION_FAILED" and not optional_schema_failure:
                            raise
                        operation = uid()
                        evidence_ref = self.record_evidence(
                            "failure",
                            operation_id=operation,
                            failure_reason=(
                                f"{exc.code}:{exc.reason}"
                                if optional_schema_failure
                                else exc.reason
                            ),
                            error=exc,
                        )
                        if optional_schema_failure:
                            # The creator identity and basic threshold remain strict. A malformed
                            # optional module is isolated to its registered capability scope so
                            # successful modules and the creator draft survive this observation.
                            self.repo.record_capability_failure(
                                self.ctx.contract_version,
                                f"profile_module:{key}",
                                identity,
                                self.ctx.lease_generation,
                                exc.reason,
                            )
                        observation = ModuleObservation(
                            creator_ref=ref,
                            module_key=key,
                            fields=[
                                FieldObservation(
                                    field_key="__module_failure__",
                                    status=FieldStatus.FAILED,
                                    failure_reason=(
                                        f"{exc.code}:{exc.reason}"
                                        if optional_schema_failure
                                        else exc.reason
                                    ),
                                    operation_id=operation,
                                    session_version=self.ctx.session_version,
                                    evidence_refs=[evidence_ref] if evidence_ref else [],
                                )
                            ],
                            expected_fields=["__module_failure__"],
                            coverage_gaps=["module unreadable"],
                            operation_id=operation,
                            contract_version=self.ctx.contract_version,
                        )
                    finally:
                        with self.repo.edit(self.root, self.ctx) as (current, _):
                            times = current.checkpoint.module_seconds
                            times[key] = times.get(key, 0.0) + time.monotonic() - module_started
                    if (
                        observation.creator_ref.platform_creator_id != identity
                        or observation.module_key != key
                        or observation.contract_version != self.ctx.contract_version
                    ):
                        raise CollectorError("PLATFORM_PAGE_CHANGED", "MODULE_IDENTITY_OR_VERSION")
                    with self.repo.edit(self.root, self.ctx) as (current, conn):
                        c = next(
                            c
                            for c in current.checkpoint.candidates
                            if c.ref.platform_creator_id == identity
                        )
                        if any(
                            m.module_observation_id == observation.module_observation_id
                            for m in c.observation_history
                        ):
                            continue
                        c.observation_history.append(observation)
                        c.modules[key] = observation
                        if key == self.adapter.module_keys[0]:
                            fields = {f.field_key: f for f in observation.fields}
                            name, platform_id = (
                                fields.get("nickname"),
                                fields.get("platform_creator_id"),
                            )
                            if (
                                not name
                                or name.status != FieldStatus.COLLECTED
                                or not name.value
                                or not platform_id
                                or platform_id.status != FieldStatus.COLLECTED
                            ):
                                c.state = "failed"
                                c.failure_reason = "BASIC_THRESHOLD_FAILED"
                            elif platform_id.value != identity:
                                c.state = "invalid"
                                c.failure_reason = "CREATOR_INVALID"
                            else:
                                if not c.valid:
                                    if current.valid_count >= current.plan.target_count:
                                        raise CollectorError(
                                            "PLATFORM_PAGE_CHANGED", "TARGET_OVERRUN"
                                        )
                                    c.valid = True
                                    current.valid_count += 1
                                self.repo.persist_creators(
                                    conn, current, publish=False, only_creator=identity
                                )
                    fresh = self.repo.get(self.root)
                    c = next(
                        c
                        for c in fresh.checkpoint.candidates
                        if c.ref.platform_creator_id == identity
                    )
                    if not c.valid:
                        return
                if self.adapter.featured_keys:
                    await self.collect_featured(identity)
                with self.repo.edit(self.root, self.ctx) as (current, _):
                    c = next(
                        c
                        for c in current.checkpoint.candidates
                        if c.ref.platform_creator_id == identity
                    )
                    c.state = "done"
                    if self.repo.pipeline_complete(current, identity):
                        c.failure_reason = None
                    elif self.repo.profile_complete(current, identity):
                        c.failure_reason = "FEATURED_COLLECTION_INCOMPLETE"
                    else:
                        c.failure_reason = (
                            "PROFILE_SCOPE_INCOMPLETE"
                            if current.profile_requirement is not None
                            else "MODULE_COLLECTION_FAILED"
                        )
        except CollectorError as exc:
            if exc.code != "CREATOR_INVALID":
                raise
            with self.repo.edit(self.root, self.ctx) as (task, _):
                c = next(
                    c for c in task.checkpoint.candidates if c.ref.platform_creator_id == identity
                )
                # Previously committed valid results are retained; a changed homepage is a failure.
                c.state = "failed" if c.valid else "invalid"
                c.failure_reason = exc.reason or "CREATOR_INVALID"
        finally:
            self.charge(start)

    async def collect_featured(self, identity: str) -> None:
        """Collect both default modules for one creator and commit each module independently."""
        task = self.repo.get(self.root)
        candidate = next(
            c for c in task.checkpoint.candidates if c.ref.platform_creator_id == identity
        )
        ref = candidate.ref.model_copy(deep=True)
        start = time.monotonic()
        try:
            observations = await self.adapter.collect_featured_collections(
                ref, task.checkpoint, self.ctx
            )
        finally:
            self.charge(start)
        for observation in observations:
            key = observation.collection_type.value
            if (
                observation.creator_ref.platform_creator_id != identity
                or observation.contract_version != self.ctx.contract_version
                or key not in self.adapter.featured_keys
            ):
                raise CollectorError("PLATFORM_PAGE_CHANGED", "FEATURED_IDENTITY_OR_VERSION")
            spec = self.adapter.featured_specs.get(key)
            if spec and spec.cover:
                if self.covers is None:
                    observation = observation.with_gap("cover_pipeline_unavailable")
                else:
                    await self.store_covers(observation, spec)
                    observation = observation.apply_cover_outcomes(cover_registered=True)
            with self.repo.edit(self.root, self.ctx) as (current, _):
                c = next(
                    c
                    for c in current.checkpoint.candidates
                    if c.ref.platform_creator_id == identity
                )
                if any(
                    o.collection_observation_id == observation.collection_observation_id
                    for o in c.collection_history
                ):
                    continue
                previous = c.collections.get(key)
                if (
                    observation.status in {CollectionStatus.FAILED, CollectionStatus.NOT_ATTEMPTED}
                    and previous is not None
                ):
                    # A failed re-read is recorded but never clears a committed observation.
                    c.collection_history.append(observation)
                    continue
                if previous is not None and self.reusable(previous, observation, spec):
                    # Same verified default set: keep the original observation id and time.
                    continue
                c.collection_history.append(observation)
                c.collections[key] = observation

    @staticmethod
    def reusable(previous: Any, observation: Any, spec: Any) -> bool:
        """Reuse requires a registered stable set key and an unchanged ordered set."""
        if not previous.complete or spec is None or spec.set_key_path is None:
            return False
        return (
            previous.set_key is not None
            and previous.set_key == observation.set_key
            and previous.fingerprint() == observation.fingerprint()
        )

    async def store_covers(self, observation: Any, spec: Any) -> None:
        assert spec.cover and self.covers
        for card in observation.cards:
            if card.cover is None:
                card.cover = CoverRef(
                    status=CoverStatus.NOT_ATTEMPTED, failure_reason="COVER_SOURCE_MISSING"
                )
            if card.cover.status == CoverStatus.STORED:
                continue
            # Upload and verify the object before any observation references it.
            card.cover = await self.covers.store(
                root_task_id=self.root,
                source_url=card.cover.source_url,
                spec=spec.cover,
                fetch=self.adapter.fetch_cover,
            )

    def refresh_counts(self, task: TaskRecord) -> None:
        task.profile_complete_count = sum(
            c.valid and self.repo.profile_complete(task, c.ref.platform_creator_id)
            for c in task.checkpoint.candidates
        )
        task.featured_complete_count = sum(
            c.valid and self.repo.featured_complete(task, c.ref.platform_creator_id)
            for c in task.checkpoint.candidates
        )
        attempted = any(c.collections for c in task.checkpoint.candidates if c.valid)
        if not attempted:
            task.featured_status = "NOT_ATTEMPTED"
        elif task.valid_count and task.featured_complete_count == task.valid_count:
            task.featured_status = "COMPLETED"
        else:
            task.featured_status = "PARTIAL_COMPLETED"

    def finish(self) -> str:
        with self.repo.edit(self.root, self.ctx) as (task, conn):
            self.refresh_counts(task)
            profile_incomplete = any(
                c.valid and not self.repo.profile_complete(task, c.ref.platform_creator_id)
                for c in task.checkpoint.candidates
            )
            # §14.3: COMPLETED needs the target reached *and* every attempted step complete.
            task.pipeline_complete = (
                task.valid_count >= task.plan.target_count
                and not profile_incomplete
                and not any(
                    c.valid and not self.repo.pipeline_complete(task, c.ref.platform_creator_id)
                    for c in task.checkpoint.candidates
                )
            )
            self.repo.persist_creators(conn, task, publish=True)
            if task.pipeline_complete:
                task.state = TaskStatus.COMPLETED
                task.failure_reason = None
            else:
                task.state = TaskStatus.PARTIAL_COMPLETED
                task.failure_reason = (
                    "SEARCH_CAPABILITY_LIMIT"
                    if task.checkpoint.search_stop_reason
                    and task.valid_count < task.plan.target_count
                    else "PROFILE_SCOPE_INCOMPLETE"
                    if profile_incomplete and task.profile_requirement is not None
                    else "MODULE_COLLECTION_FAILED"
                    if profile_incomplete
                    or any(c.state == "failed" for c in task.checkpoint.candidates)
                    else "FEATURED_COLLECTION_INCOMPLETE"
                    if task.featured_status == "PARTIAL_COMPLETED"
                    else "FEATURED_NOT_ATTEMPTED"
                    if task.valid_count >= task.plan.target_count
                    else "SEARCH_EXHAUSTED"
                )
        return task.state

    @staticmethod
    def contract_scope(error: CollectorError) -> str | None:
        if error.code != "PLATFORM_PAGE_CHANGED" or error.reason.startswith("CONTRACT_SCOPE_"):
            return None
        reason = error.reason.upper()
        if "IDENTITY" in reason:
            return "profile_identity"
        if "FEATURED" in reason or "COVER" in reason:
            return "featured:registry"
        if "MODULE" in reason or "PROFILE" in reason:
            return "profile_module:registry"
        if any(
            marker in reason
            for marker in ("SEARCH", "CURSOR", "PAGINATION", "CONDITION", "PAGE_READY")
        ):
            return "search"
        return None

    def record_error(self, error: CollectorError) -> str:
        if error.code in EVIDENCE_ERROR_CODES:
            # Allowlisted failure evidence only; never platform bodies or credentials.
            self.record_evidence(
                "failure",
                operation_id=uid(),
                failure_reason=f"{error.code}:{error.reason}" if error.reason else error.code,
                error=error,
            )
        breaker: str | None = None
        scope = self.contract_scope(error)
        if scope:
            breaker = self.repo.record_capability_failure(
                self.ctx.contract_version,
                scope,
                self.root,
                self.ctx.lease_generation,
                error.reason,
            )
        state = {
            "BUDGET_EXHAUSTED": TaskStatus.PAUSED_BUDGET,
            "ACCOUNT_LOGIN_REQUIRED": TaskStatus.WAITING_FOR_LOGIN,
            "ACCOUNT_MISMATCH": TaskStatus.WAITING_FOR_ACCOUNT,
            "SESSION_INDETERMINATE": TaskStatus.WAITING_FOR_RESOURCE,
            "PLATFORM_SECURITY_CHALLENGE": TaskStatus.WAITING_FOR_VERIFICATION,
            "RESOURCE_UNAVAILABLE": TaskStatus.WAITING_FOR_RESOURCE,
            "LEASE_LOST": TaskStatus.WAITING_FOR_RESOURCE,
            "PLATFORM_RATE_LIMITED": TaskStatus.RETRY_WAIT,
            "TASK_CANCELLED": TaskStatus.CANCELLED,
        }.get(error.code, TaskStatus.FAILED)
        if breaker == "SUSPECTED":
            state = TaskStatus.WAITING_FOR_RESOURCE
        # This control transaction never accepts module values or updates projections.
        with self.repo.edit(self.root) as (task, conn):
            if task.attempt_id != self.ctx.attempt_id:
                return task.state
            if task.state == TaskStatus.CANCELLING:
                state = TaskStatus.CANCELLED
            if task.state in {
                TaskStatus.CANCELLED,
                TaskStatus.PARTIAL_COMPLETED,
                TaskStatus.COMPLETED,
            }:
                return task.state
            self.refresh_counts(task)
            if state not in {TaskStatus.WAITING_FOR_RESOURCE, TaskStatus.RETRY_WAIT}:
                self.repo.persist_creators(conn, task, publish=True)
            counts = task.checkpoint.failure_counts
            counts[error.code] = counts.get(error.code, 0) + 1
            task.state = state
            task.failure_reason = error.code + (":" + error.reason if error.reason else "")
        return state

    def partial_complete(self, reason: str) -> str:
        """Publish all durable progress and stop a challenge loop with an explicit reason."""

        with self.repo.edit(self.root) as (task, conn):
            if task.attempt_id != self.ctx.attempt_id:
                return task.state
            if task.state in {
                TaskStatus.CANCELLED,
                TaskStatus.COMPLETED,
                TaskStatus.PARTIAL_COMPLETED,
            }:
                return task.state
            self.refresh_counts(task)
            self.repo.persist_creators(conn, task, publish=True)
            task.pipeline_complete = False
            task.state = TaskStatus.PARTIAL_COMPLETED
            task.failure_reason = reason
        return TaskStatus.PARTIAL_COMPLETED
