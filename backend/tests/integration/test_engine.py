from contextlib import asynccontextmanager
from threading import Event, Thread

import pytest
from xingtu.domain import (
    CandidateDiagnostic,
    CollectorError,
    ExecutionContext,
    ReleaseDisposition,
    SegmentBudget,
    TaskStatus,
    uid,
)
from xingtu.engine import Engine
from xingtu.evidence import FileEvidenceStore

from backend.tests.synthetic import SyntheticAdapter


class ExpiringCursor(SyntheticAdapter):
    """Reports the registered SEARCH_CURSOR_INVALID contract on one search batch."""

    def __init__(self, *args, fail_on_call=1, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = 0
        self.fail_on_call = fail_on_call

    async def search(self, plan, cp, ctx):
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "SEARCH_CURSOR_INVALID")
        return await super().search(plan, cp, ctx)


def start(repo, plan, target_count):
    task_plan = plan.model_copy(update={"target_count": target_count})
    root = repo.create(
        task_plan,
        "unit",
        uid(),
        "test",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        modules=["basic", "commercial", "fans"],
    )
    task = repo.get(root)
    gen, session = repo.acquire("unit", task.attempt_id)
    return ExecutionContext(
        root_task_id=root,
        task_id=task.task_id,
        attempt_id=task.attempt_id,
        execution_unit_id="unit",
        lease_generation=gen,
        session_version=session,
        capability_version="synthetic-v1",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
    )


async def test_order_dedup_invalid_topup_and_snapshots(repo, started):
    adapter = SyntheticAdapter(["bad", "1", "1", "2", "3"], invalid=["bad"], page_size=2)
    engine = Engine(repo, adapter, started)
    assert await engine.run() == "PARTIAL_COMPLETED"
    task = repo.get(started.root_task_id)
    assert task.valid_count == 2
    assert adapter.visits == ["bad", "1", "2"]
    assert task.profile_complete_count == 2
    assert task.pipeline_complete is False
    results = repo.results(task.root_task_id)
    assert [r["first_position"] for r in results] == [1, 2]
    assert all(r["payload"]["featured_status"] == "NOT_ATTEMPTED" for r in results)


async def test_zero_result_has_endpoint(repo, started):
    await Engine(repo, SyntheticAdapter([]), started).run()
    task = repo.get(started.root_task_id)
    assert task.valid_count == 0 and task.checkpoint.exhausted
    assert task.failure_reason == "SEARCH_EXHAUSTED"


async def test_capability_boundary_keeps_cursor_and_partial_results(repo, started):
    class Limited(SyntheticAdapter):
        async def search(self, plan, cp, ctx):
            if cp.cursor is not None:
                raise CollectorError("SEARCH_CAPABILITY_LIMIT", "PAGINATION_NOT_VERIFIED")
            return await super().search(plan, cp, ctx)

    adapter = Limited(["1", "2", "3"], page_size=1)
    assert await Engine(repo, adapter, started).run() == "PARTIAL_COMPLETED"
    task = repo.get(started.root_task_id)
    assert task.valid_count == 1
    assert not task.checkpoint.exhausted and task.checkpoint.cursor is not None
    assert not task.checkpoint.exhaustion_evidence_refs
    assert task.failure_reason == task.checkpoint.search_stop_reason == "SEARCH_CAPABILITY_LIMIT"
    assert len(repo.results(task.root_task_id)) == 1


async def test_business_scope_persists_and_prevents_false_completion(repo, started):
    from xingtu.domain import ProfileRequirement

    with repo.edit(started.root_task_id) as (task, _):
        task.profile_requirement = ProfileRequirement(
            version="unverified-v1", modules={"extra": []}
        )
    await Engine(repo, SyntheticAdapter(), started).run()
    task = repo.get(started.root_task_id)
    assert task.valid_count == 2 and task.profile_complete_count == 0
    assert task.failure_reason == "PROFILE_SCOPE_INCOMPLETE"
    coverage = repo.results(task.root_task_id)[0]["payload"]["profile_coverage"]
    assert not coverage["complete"] and coverage["requirement_version"] == "unverified-v1"


async def test_operation_counters_are_delta_based_and_errors_are_classified(repo, started):
    adapter = SyntheticAdapter()
    adapter.operation_metrics = {"requests": 3, "responses": 2}
    engine = Engine(repo, adapter, started)
    engine.guard()
    engine.guard()
    cp = repo.get(started.root_task_id).checkpoint
    assert (cp.observed_requests, cp.observed_responses) == (3, 2)
    adapter.operation_metrics["responses"] = 3
    engine.guard()
    assert repo.get(started.root_task_id).checkpoint.observed_responses == 3
    assert engine.record_error(CollectorError("PLATFORM_PERMISSION_DENIED")) == "FAILED"
    task = repo.get(started.root_task_id)
    assert task.checkpoint.failure_counts == {"PLATFORM_PERMISSION_DENIED": 1}
    repo.require_contract("synthetic-v1")


async def test_optional_failure_keeps_basic_and_retry_new_observation(repo, started):
    adapter = SyntheticAdapter(failed_module="fans")
    await Engine(repo, adapter, started).run()
    old = repo.get(started.root_task_id)
    first_snapshots = repo.results(old.root_task_id)
    assert old.valid_count == 2 and old.profile_complete_count == 0
    basic_id = old.checkpoint.candidates[0].modules["basic"].module_observation_id
    repo.release(
        "unit",
        started.attempt_id,
        started.lease_generation,
        stopped=True,
        disposition=ReleaseDisposition.VERIFIED_READY,
    )
    repo.command(old.root_task_id, "retry", old.version, "test")
    task = repo.get(old.root_task_id)
    gen, session = repo.acquire("unit", task.attempt_id)
    ctx = started.model_copy(update={"attempt_id": task.attempt_id, "lease_generation": gen})
    repaired = SyntheticAdapter()
    await Engine(repo, repaired, ctx).run()
    current = repo.get(old.root_task_id)
    assert current.valid_count == 2 and current.profile_complete_count == 2
    assert current.checkpoint.candidates[0].modules["basic"].module_observation_id == basic_id
    assert all(key == "fans" for _, key in repaired.modules)
    with repo.connect() as conn:
        previous = conn.execute(
            "SELECT payload FROM creator_snapshots WHERE snapshot_id=%s",
            (first_snapshots[0]["snapshot_id"],),
        ).fetchone()["payload"]
    assert previous == first_snapshots[0]["payload"]


async def test_optional_schema_mismatch_is_scoped_to_the_module(repo, started):
    class OptionalSchemaMismatch(SyntheticAdapter):
        async def collect_module(self, key, creator, ctx, row_covers=None):
            if key == "fans":
                raise CollectorError("PLATFORM_PAGE_CHANGED", "RESPONSE_SCHEMA_MISMATCH")
            return await super().collect_module(key, creator, ctx)

    state = await Engine(repo, OptionalSchemaMismatch(), started).run()
    assert state == TaskStatus.PARTIAL_COMPLETED
    task = repo.get(started.root_task_id)
    assert task.valid_count == 2
    for candidate in (item for item in task.checkpoint.candidates if item.valid):
        failure = candidate.modules["fans"].fields[0]
        assert failure.field_key == "__module_failure__"
        assert failure.failure_reason == "PLATFORM_PAGE_CHANGED:RESPONSE_SCHEMA_MISMATCH"
        assert candidate.modules["basic"].complete


async def test_basic_schema_mismatch_remains_a_strict_task_error(repo, started):
    class BasicSchemaMismatch(SyntheticAdapter):
        async def collect_module(self, key, creator, ctx, row_covers=None):
            if key == "basic":
                raise CollectorError("PLATFORM_PAGE_CHANGED", "RESPONSE_SCHEMA_MISMATCH")
            return await super().collect_module(key, creator, ctx)

    with pytest.raises(CollectorError) as error:
        await Engine(repo, BasicSchemaMismatch(), started).run()
    assert error.value.code == "PLATFORM_PAGE_CHANGED"
    assert error.value.reason == "RESPONSE_SCHEMA_MISMATCH"


async def test_budget_preserves_entire_batch_and_resume(repo, started):
    engine = Engine(
        repo, SyntheticAdapter(["bad", "1", "2", "3"], invalid=["bad"]), started, scan_budget=1
    )
    with pytest.raises(CollectorError) as error:
        await engine.run()
    assert error.value.code == "BUDGET_EXHAUSTED"
    engine.record_error(error.value)
    task = repo.get(started.root_task_id)
    assert task.state == TaskStatus.PAUSED_BUDGET
    assert task.checkpoint.pending_page is not None
    repo.release(
        "unit",
        started.attempt_id,
        started.lease_generation,
        stopped=True,
        disposition=ReleaseDisposition.VERIFIED_READY,
    )
    repo.command(task.root_task_id, "continue", task.version, "test")
    task = repo.get(task.root_task_id)
    gen, _ = repo.acquire("unit", task.attempt_id)
    ctx = started.model_copy(update={"attempt_id": task.attempt_id, "lease_generation": gen})
    adapter = SyntheticAdapter(["bad", "1", "2", "3"], invalid=["bad"])
    await Engine(repo, adapter, ctx).run()
    assert adapter.visits == ["1", "2"]
    assert repo.get(task.root_task_id).valid_count == 2


async def test_crash_after_basic_reuses_checkpoint(repo, started):
    adapter = SyntheticAdapter()

    def crash(key):
        if key == "commercial":
            raise RuntimeError("simulated crash")

    adapter.before_module = crash
    with pytest.raises(RuntimeError, match="simulated crash"):
        await Engine(repo, adapter, started).run()
    task = repo.get(started.root_task_id)
    assert task.valid_count == 1
    resumed = SyntheticAdapter()
    await Engine(repo, resumed, started).run()
    assert ("1", "basic") not in resumed.modules
    assert repo.get(task.root_task_id).valid_count == 2


async def test_login_not_invalid_and_cancellation_fences(repo, started):
    adapter = SyntheticAdapter()
    adapter.profile_error = CollectorError("ACCOUNT_LOGIN_REQUIRED")
    engine = Engine(repo, adapter, started)
    with pytest.raises(CollectorError) as exc:
        await engine.run()
    engine.record_error(exc.value)
    task = repo.get(started.root_task_id)
    assert task.state == TaskStatus.WAITING_FOR_LOGIN and task.valid_count == 0
    assert task.checkpoint.candidates[0].state == "collecting"
    repo.command(task.root_task_id, "cancel", task.version, "test")
    with pytest.raises(CollectorError, match="TASK_CANCELLED"):
        with repo.edit(task.root_task_id, started):
            pass


async def test_identity_unreadable_retries_then_skips_and_continues(repo, started):
    class IdentityUnreadable(SyntheticAdapter):
        def __init__(self):
            super().__init__(["unreadable", "1", "2"], page_size=3)
            self.unreadable_attempts = 0

        @asynccontextmanager
        async def profile(self, creator, ctx):
            self.visits.append(creator.platform_creator_id)
            if creator.platform_creator_id == "unreadable":
                self.unreadable_attempts += 1
                raise CollectorError("PLATFORM_PAGE_CHANGED", "IDENTITY_UNREADABLE")
            yield

    adapter = IdentityUnreadable()
    assert await Engine(repo, adapter, started).run() == TaskStatus.PARTIAL_COMPLETED
    task = repo.get(started.root_task_id)
    failed = task.checkpoint.candidates[0]
    assert failed.state == "failed"
    assert failed.failure_reason == "IDENTITY_UNREADABLE"
    assert failed.retry_count == 2
    assert adapter.session_rechecks == 1
    assert adapter.visits == ["unreadable", "unreadable", "unreadable", "1", "2"]
    assert task.valid_count == 2
    repo.require_contract("synthetic-v1", {"profile_identity"})


async def test_creator_failure_on_page_two_continues_through_page_three(repo, plan):
    class PageTwoFailure(SyntheticAdapter):
        @asynccontextmanager
        async def profile(self, creator, ctx):
            self.visits.append(creator.platform_creator_id)
            if creator.platform_creator_id == "failed-on-page-2":
                raise CollectorError("CREATOR_INVALID", "synthetic unavailable creator")
            yield

    ctx = start(repo, plan, 4)
    adapter = PageTwoFailure(
        ["page-1-a", "page-1-b", "failed-on-page-2", "page-2-b", "page-3-a"],
        page_size=2,
    )
    assert await Engine(repo, adapter, ctx).run() == TaskStatus.PARTIAL_COMPLETED
    task = repo.get(ctx.root_task_id)
    assert task.valid_count == 4
    assert adapter.visits == [
        "page-1-a",
        "page-1-b",
        "failed-on-page-2",
        "page-2-b",
        "page-3-a",
    ]
    assert task.checkpoint.visited_cursors == [None, "2", "4"]
    rows = repo.results(ctx.root_task_id)
    assert len(rows) == 4
    assert [row["first_position"] for row in rows] == [0, 1, 3, 4]
    assert all(row["snapshot_id"] for row in rows)


async def test_identity_unreadable_rechecks_session_before_retry(repo, started):
    class LoggedOutAfterIdentityFailure(SyntheticAdapter):
        @asynccontextmanager
        async def profile(self, creator, ctx):
            raise CollectorError("PLATFORM_PAGE_CHANGED", "IDENTITY_UNREADABLE")
            yield  # pragma: no cover - makes this an async context-manager generator

        async def recheck_session(self):
            self.session_rechecks += 1
            raise CollectorError("ACCOUNT_LOGIN_REQUIRED", "REGISTERED_LOGIN_PAGE")

    adapter = LoggedOutAfterIdentityFailure()
    engine = Engine(repo, adapter, started)
    with pytest.raises(CollectorError, match="ACCOUNT_LOGIN_REQUIRED") as exc:
        await engine.run()
    assert adapter.session_rechecks == 1
    assert engine.record_error(exc.value) == TaskStatus.WAITING_FOR_LOGIN


async def test_target_20_and_200(repo, plan):
    from xingtu.domain import ExecutionContext, uid

    for count in [20, 200]:
        p = plan.model_copy(update={"target_count": count})
        root = repo.create(
            p,
            "unit",
            uid(),
            "test",
            adapter_version="synthetic-v1",
            contract_version="synthetic-v1",
            modules=["basic", "commercial", "fans"],
        )
        task = repo.get(root)
        gen, session = repo.acquire("unit", task.attempt_id)
        # The 200-creator finish transaction can hold the unit row for longer than the default
        # 120-second lease on a slow local PostgreSQL.  This case exercises the target/count path,
        # not lease expiry; keep the fencing window generous so a heartbeat blocked behind that
        # transaction cannot turn the test into a timing failure.
        with repo.connect() as conn:
            conn.execute(
                "UPDATE execution_units SET lease_until=now()+interval '1 hour' "
                "WHERE unit_id='unit'"
            )
        ctx = ExecutionContext(
            root_task_id=root,
            task_id=task.task_id,
            attempt_id=task.attempt_id,
            execution_unit_id="unit",
            lease_generation=gen,
            session_version=session,
            capability_version="synthetic-v1",
            adapter_version="synthetic-v1",
            contract_version="synthetic-v1",
        )
        adapter = SyntheticAdapter([str(i) for i in range(count + 5)], page_size=50)

        # This large integration case exercises the same transaction-heavy path as a real
        # Worker segment. Keep its unit lease alive just as Activities.collect does; otherwise
        # a slow CI host can turn the intended 120-second fencing check into a timing flake.
        stopped = Event()

        def heartbeat(
            owner: str = ctx.attempt_id,
            lease_generation: int = gen,
            stop_signal: Event = stopped,
        ) -> None:
            while not stop_signal.wait(15):
                with repo.connect() as conn:
                    conn.execute(
                        """UPDATE execution_units
                        SET lease_until=now()+interval '1 hour',last_heartbeat_at=now()
                        WHERE unit_id='unit' AND owner=%s AND generation=%s""",
                        (owner, lease_generation),
                    )

        pulse = Thread(target=heartbeat, daemon=True)
        pulse.start()
        try:
            await Engine(repo, adapter, ctx).run()
        finally:
            stopped.set()
            pulse.join(timeout=5)
        assert repo.get(root).valid_count == count
        assert len(adapter.visits) == count
        repo.release(
            "unit",
            ctx.attempt_id,
            gen,
            stopped=True,
            disposition=ReleaseDisposition.VERIFIED_READY,
        )


async def test_condition_mismatch_never_commits_candidates(repo, started):
    class WrongConditions(SyntheticAdapter):
        async def search(self, plan, cp, ctx):
            page = await super().search(plan, cp, ctx)
            page.conditions_digest = "wrong"
            return page

    with pytest.raises(CollectorError, match="PLATFORM_CONDITION_MISMATCH"):
        await Engine(repo, WrongConditions(), started).run()
    assert not repo.get(started.root_task_id).checkpoint.candidates


async def test_looping_cursor_fails_not_exhausted(repo, started):
    class Loop(SyntheticAdapter):
        async def search(self, plan, cp, ctx):
            page = await super().search(plan, cp, ctx)
            page.next_checkpoint = cp.cursor or "1"
            page.exhausted = False
            return page

    with pytest.raises(CollectorError, match="CURSOR_LOOP"):
        await Engine(repo, Loop(page_size=1, invalid=["1", "2", "3"]), started).run()
    assert not repo.get(started.root_task_id).checkpoint.exhausted


async def test_two_pages_without_new_creator_ids_stop_as_pagination_error(repo, started):
    class RepeatedResults(SyntheticAdapter):
        async def search(self, plan, cp, ctx):
            page = await super().search(plan, cp, ctx)
            page.candidates = [
                page.candidates[0].model_copy(update={"platform_creator_id": "same"})
            ]
            offset = int(cp.cursor or "0")
            page.exhausted = False
            page.next_checkpoint = str(offset + 1)
            return page

    adapter = RepeatedResults(["same", "same", "same", "same"], page_size=1)
    with pytest.raises(CollectorError, match="SEARCH_NO_PROGRESS"):
        await Engine(repo, adapter, started).run()
    task = repo.get(started.root_task_id)
    assert task.valid_count == 1
    assert task.checkpoint.no_progress_pages == 2
    assert task.checkpoint.cursor == "3"
    assert not task.checkpoint.exhausted


async def test_invalid_cursor_rescans_and_preserves_first_positions(repo, started):
    adapter = SyntheticAdapter(["bad", "1", "2", "3"], page_size=1, invalid=["bad"])
    engine = Engine(repo, adapter, started, scan_budget=1)
    with pytest.raises(CollectorError) as error:
        await engine.run()
    assert error.value.code == "BUDGET_EXHAUSTED"
    # Emulate a new budget segment after verified recovery, keeping persisted seen identities.
    with repo.edit(started.root_task_id, started) as (task, _):
        task.checkpoint.scanned_ids = []
    adapter.cursor_invalid = True
    await Engine(repo, adapter, started).run()
    task = repo.get(started.root_task_id)
    assert task.checkpoint.search_generation == 1
    assert [c.ref.platform_creator_id for c in task.checkpoint.candidates][:3] == ["bad", "1", "2"]
    assert [c.ref.first_position for c in task.checkpoint.candidates][:3] == [0, 1, 2]
    assert task.checkpoint.rescan_reasons == ["CURSOR_INVALID"]


async def test_budget_partial_snapshot_explicit_unattempted_modules(repo, started):
    adapter = SyntheticAdapter()

    def pause(key):
        if key == "commercial":
            raise CollectorError("BUDGET_EXHAUSTED", "synthetic interruption")

    adapter.before_module = pause
    engine = Engine(repo, adapter, started)
    with pytest.raises(CollectorError) as error:
        await engine.run()
    engine.record_error(error.value)
    rows = repo.results(started.root_task_id)
    assert len(rows) == 1
    assert rows[0]["payload"]["modules"]["commercial"]["status"] == "NOT_ATTEMPTED"
    assert rows[0]["payload"]["modules"]["basic"]["complete"]


async def test_mid_scan_cursor_expiry_rescans_and_keeps_contract_enabled(repo, started):
    adapter = ExpiringCursor(["1", "2", "3", "4"], page_size=1, fail_on_call=2)
    assert await Engine(repo, adapter, started).run() == "PARTIAL_COMPLETED"
    task = repo.get(started.root_task_id)
    assert task.valid_count == 2
    assert task.checkpoint.search_generation == 1
    assert task.checkpoint.rescan_reasons == ["CURSOR_INVALID"]
    assert not task.checkpoint.exhausted
    with repo.connect() as conn:
        # A recoverable expired cursor never disables the adapter for new tasks.
        assert conn.execute("SELECT count(*) AS n FROM contract_health").fetchone()["n"] == 0


async def test_rescan_over_known_identities_is_not_a_contract_failure(repo, plan):
    ctx = start(repo, plan, 5)
    adapter = ExpiringCursor(["1", "2", "3", "4", "5", "6"], page_size=1, fail_on_call=5)
    assert await Engine(repo, adapter, ctx).run() == "PARTIAL_COMPLETED"
    task = repo.get(ctx.root_task_id)
    assert task.valid_count == 5
    assert task.checkpoint.rescan_reasons == ["CURSOR_INVALID"]
    # Re-walked identities keep one scan slot each ("本段同一身份不重复增加扫描数").
    assert task.checkpoint.scanned_ids == ["1", "2", "3", "4", "5"]
    assert [c.ref.platform_creator_id for c in task.checkpoint.candidates] == [
        "1",
        "2",
        "3",
        "4",
        "5",
    ]


async def test_unreadable_rows_are_persisted_as_diagnostics(repo, started):
    class Diagnosing(SyntheticAdapter):
        async def search(self, plan, cp, ctx):
            page = await super().search(plan, cp, ctx)
            dropped, page.candidates = page.candidates[0], page.candidates[1:]
            page.unidentified = [
                CandidateDiagnostic(
                    reason="CANDIDATE_IDENTITY_UNREADABLE",
                    detail="synthetic",
                    source_ref="synthetic:items.0",
                    operation_id=page.operation_id,
                )
            ]
            assert dropped.platform_creator_id == "drop"
            return page

    assert await Engine(repo, Diagnosing(["drop", "1", "2"]), started).run() == "PARTIAL_COMPLETED"
    task = repo.get(started.root_task_id)
    assert [c.ref.platform_creator_id for c in task.checkpoint.candidates] == ["1", "2"]
    assert [d.reason for d in task.checkpoint.diagnostics] == ["CANDIDATE_IDENTITY_UNREADABLE"]
    assert task.valid_count == 2


async def test_module_checkpoint_version_change_stops_the_attempt(repo, plan):
    root = repo.create(
        plan,
        "unit",
        uid(),
        "test",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        modules=["basic", "commercial", "fans"],
        module_checkpoint_versions={"basic": 9, "commercial": 9, "fans": 9},
    )
    task = repo.get(root)
    gen, session = repo.acquire("unit", task.attempt_id)
    ctx = ExecutionContext(
        root_task_id=root,
        task_id=task.task_id,
        attempt_id=task.attempt_id,
        execution_unit_id="unit",
        lease_generation=gen,
        session_version=session,
        capability_version="synthetic-v1",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
    )
    with pytest.raises(CollectorError, match="MODULE_CHECKPOINT_CHANGED"):
        await Engine(repo, SyntheticAdapter(), ctx).run()


async def test_budget_reference_comes_from_execution_context(repo, started):
    configured = started.model_copy(
        update={"budget": SegmentBudget(active_seconds=600, candidate_scan_floor=7)}
    )
    engine = Engine(repo, SyntheticAdapter(), configured)
    assert engine.active_budget == 600
    assert engine.scan_budget == max(7, 5 * 2)
    paused = started.model_copy(update={"budget": SegmentBudget(active_seconds=1e-9)})
    with pytest.raises(CollectorError) as error:
        await Engine(repo, SyntheticAdapter(), paused).run()
    assert error.value.code == "BUDGET_EXHAUSTED"


async def test_evidence_records_exhaustion_and_module_failure(repo, started, tmp_path):
    sink = FileEvidenceStore(repo, tmp_path / "evidence", tmp_path)
    adapter = SyntheticAdapter(["1"])

    def fail(key):
        if key == "fans":
            raise CollectorError("MODULE_COLLECTION_FAILED", "SYNTHETIC_MODULE_FAILURE")

    adapter.before_module = fail
    engine = Engine(repo, adapter, started, evidence=sink)
    assert await engine.run() == "PARTIAL_COMPLETED"
    task = repo.get(started.root_task_id)
    stored = [ref for ref in task.checkpoint.exhaustion_evidence_refs if ref.endswith(".json")]
    assert stored
    module = task.checkpoint.candidates[0].modules["fans"]
    assert module.fields[0].evidence_refs
    engine.record_error(CollectorError("PLATFORM_PAGE_CHANGED", "synthetic contract change"))
    files = sorted((tmp_path / "evidence").rglob("*.json"))
    assert len(files) == 3
    assert all((path.stat().st_mode & 0o077) == 0 for path in files)
    with repo.connect() as conn:
        kinds = conn.execute("SELECT kind,count(*) AS n FROM raw_evidence GROUP BY kind").fetchall()
    assert {row["kind"]: row["n"] for row in kinds} == {"failure": 2, "summary": 1}
