from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

import psycopg
import pytest
from xingtu.domain import (
    CollectorError,
    ReleaseDisposition,
    SessionHealth,
    SessionHealthStatus,
    TaskStatus,
    uid,
)


def test_start_idempotency_conflict_and_concurrent_delivery(repo, plan):
    def create():
        return repo.create(
            plan,
            "unit",
            "key",
            "test",
            adapter_version="synthetic-v1",
            contract_version="synthetic-v1",
            modules=["basic"],
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        roots = list(pool.map(lambda _: create(), range(4)))
    assert len(set(roots)) == 1
    with repo.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM task_dispatches").fetchone()["n"] == 1
    with pytest.raises(CollectorError, match="IDEMPOTENCY_CONFLICT"):
        repo.create(
            plan.model_copy(update={"target_count": 3}),
            "unit",
            "key",
            "test",
            adapter_version="synthetic-v1",
            contract_version="synthetic-v1",
            modules=["basic"],
        )


def test_transaction_rolls_back_checkpoint_and_count(repo, started):
    with pytest.raises(RuntimeError):
        with repo.edit(started.root_task_id, started) as (task, _):
            task.valid_count = 1
            task.checkpoint.cursor = "would-skip-page"
            raise RuntimeError("storage failure")
    task = repo.get(started.root_task_id)
    assert task.valid_count == 0 and task.checkpoint.cursor is None


def test_browser_takeover_is_fenced_mutually_exclusive_and_reusable(repo, started):
    from xingtu.product_repository import ProductRepository

    products = ProductRepository(repo)
    operator_a = products.create_user("operator-a", "媒介 A", "unused", actor="test")
    operator_b = products.create_user("operator-b", "媒介 B", "unused", actor="test")
    browser_instance = uid()
    repo.register_browser_instance(
        "unit", started.attempt_id, started.lease_generation, browser_instance
    )
    repo.transition_collect_to_maintenance(
        "unit",
        started.attempt_id,
        started.lease_generation,
        started.session_version,
        "PLATFORM_SECURITY_CHALLENGE",
        "test",
    )
    with repo.edit(started.root_task_id) as (task, _):
        task.state = TaskStatus.WAITING_FOR_VERIFICATION
    event = repo.create_verification_event(
        unit="unit",
        root_task_id=started.root_task_id,
        generation=started.lease_generation,
        browser_instance_id=browser_instance,
        timeout_seconds=60,
    )

    requested = repo.request_browser_takeover("unit", operator_a)
    with pytest.raises(CollectorError, match="BROWSER_ALREADY_TAKEN_OVER"):
        repo.request_browser_takeover("unit", operator_b)
    active = repo.activate_browser_takeover(
        unit="unit",
        owner=started.attempt_id,
        generation=started.lease_generation,
        browser_instance_id=browser_instance,
    )
    assert active and active["takeover_id"] == requested["takeover_id"]
    assert repo.active_takeover_for_viewer(str(active["takeover_id"]), operator_a)
    repo.claim_takeover_viewer(str(active["takeover_id"]), operator_a, "viewer-a")
    with pytest.raises(CollectorError, match="TAKEOVER_VIEWER_ALREADY_CONNECTED"):
        repo.claim_takeover_viewer(str(active["takeover_id"]), operator_a, "viewer-b")

    repo.report_takeover_reappearance(
        str(active["takeover_id"]), operator_a, "PLATFORM_SECURITY_CHALLENGE"
    )
    assert repo.verification_event(str(event["event_id"]))["reappearance_count"] == 1
    verifying = repo.complete_browser_takeover(str(active["takeover_id"]), operator_a)
    assert verifying["state"] == "VERIFYING"
    assert repo.takeover(str(active["takeover_id"]))["viewer_connection_id"] == "viewer-a"
    repo.release_takeover_viewer(str(active["takeover_id"]), "viewer-a")
    assert repo.takeover(str(active["takeover_id"]))["viewer_connection_id"] is None
    with pytest.raises(CollectorError, match="TAKEOVER_NOT_ACTIVE"):
        repo.active_takeover_for_viewer(str(active["takeover_id"]), operator_a)

    repo.finish_browser_takeover(
        str(active["takeover_id"]),
        resumed=False,
        failure_reason="SECURITY_CHALLENGE_STILL_PRESENT",
    )
    assert repo.verification_event(str(event["event_id"]))["reappearance_count"] == 2
    replacement = repo.request_browser_takeover("unit", operator_b)
    assert replacement["state"] == "REQUESTED"
    repo.expire_verification_event(str(event["event_id"]), "SECURITY_CHALLENGE_TIMEOUT")
    assert repo.takeover(str(replacement["takeover_id"]))["state"] == "EXPIRED"


def test_collection_worker_registration_heartbeats_and_fences_stale_instances(repo, started):
    first_generation = repo.register_worker_instance("unit", "worker-one", 101, "synthetic")
    repo.heartbeat_worker_instance("unit", "worker-one", first_generation)
    with pytest.raises(CollectorError, match="DUPLICATE_WORKER_FOR_UNIT"):
        repo.register_worker_instance("unit", "worker-two", 102, "synthetic")

    with repo.connect() as conn:
        conn.execute(
            """UPDATE execution_unit_workers
            SET last_heartbeat_at=now()-interval '1 minute'
            WHERE worker_instance_id='worker-one'"""
        )
    second_generation = repo.register_worker_instance("unit", "worker-two", 102, "synthetic")
    assert second_generation > first_generation
    with pytest.raises(CollectorError, match="WORKER_INSTANCE_FENCED"):
        repo.heartbeat_worker_instance("unit", "worker-one", first_generation)
    repo.stop_worker_instance("unit", "worker-two", second_generation, "NORMAL_STOP")
    with repo.connect() as conn:
        rows = conn.execute(
            """SELECT worker_instance_id,stop_reason FROM execution_unit_workers
            ORDER BY worker_generation"""
        ).fetchall()
    assert [(row["worker_instance_id"], row["stop_reason"]) for row in rows] == [
        ("worker-one", "STALE_REPLACED"),
        ("worker-two", "NORMAL_STOP"),
    ]


def test_lease_expiry_quarantines_and_rejects_stale_write(repo, started):
    with repo.connect() as conn:
        conn.execute("UPDATE execution_units SET lease_until=now()-interval '1 second'")
    with pytest.raises(CollectorError, match="isolation"):
        repo.acquire("unit", "new-owner")
    assert repo.unit("unit")["state"] == "QUARANTINED"
    with pytest.raises(CollectorError, match="LEASE_LOST"):
        with repo.edit(started.root_task_id, started):
            pass


def test_recover_stopped_unit_handles_expired_lease_in_one_step(repo, started):
    with repo.connect() as conn:
        conn.execute("UPDATE execution_units SET lease_until=now()-interval '1 second'")
    repo.recover_stopped_unit("unit", "test")
    unit = repo.unit("unit")
    assert unit["state"] == "SESSION_UNVERIFIED"
    assert unit["owner"] is None
    assert unit["browser_stopped"] is True
    assert unit["last_session_status"] == "INDETERMINATE"
    generation, _ = repo.acquire("unit", "new-owner")
    assert generation > started.lease_generation


def test_has_active_unit_claim_observes_the_lease(repo, started):
    """Startup reconciliation must not clear a unit whose lease is still live."""

    assert repo.has_active_unit_claim("unit") is True
    with repo.connect() as conn:
        conn.execute("UPDATE execution_units SET owner=NULL,lease_until=NULL WHERE unit_id='unit'")
    assert repo.has_active_unit_claim("unit") is False


async def test_snapshot_database_immutability(repo, started):
    from xingtu.engine import Engine

    from backend.tests.synthetic import SyntheticAdapter

    await Engine(repo, SyntheticAdapter(), started).run()
    row = repo.results(started.root_task_id)[0]
    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        with repo.connect() as conn:
            conn.execute(
                "UPDATE creator_snapshots SET payload='{}' WHERE snapshot_id=%s",
                (row["snapshot_id"],),
            )


async def test_existing_creator_new_snapshot_and_failed_field_preserves_projection(repo, plan):
    from xingtu.domain import ExecutionContext, uid
    from xingtu.engine import Engine

    from backend.tests.synthetic import SyntheticAdapter

    roots = []
    for fail in [None, "fans"]:
        root = repo.create(
            plan,
            "unit",
            uid(),
            "test",
            adapter_version="synthetic-v1",
            contract_version="synthetic-v1",
            modules=["basic", "commercial", "fans"],
        )
        roots.append(root)
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
        await Engine(repo, SyntheticAdapter(failed_module=fail), ctx).run()
        assert repo.get(root).valid_count == 2
        repo.release(
            "unit",
            task.attempt_id,
            gen,
            stopped=True,
            disposition=ReleaseDisposition.VERIFIED_READY,
        )
    with repo.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM platform_creators").fetchone()["n"] == 2
        projections = conn.execute("SELECT projection FROM platform_creators").fetchall()
        assert all(row["projection"]["fans.value"]["status"] == "COLLECTED" for row in projections)
    assert repo.results(roots[0])[0]["snapshot_id"] != repo.results(roots[1])[0]["snapshot_id"]
    assert repo.results(roots[0])[0]["payload"]["modules"]["fans"]["complete"]
    assert not repo.results(roots[1])[0]["payload"]["modules"]["fans"]["complete"]


def test_network_mode_is_persisted_and_immutable(repo):
    from xingtu.domain import NetworkMode

    repo.register_unit(
        "local-unit", "acct", "local-dev", "/tmp/local-profile", NetworkMode.LOCAL_DEVELOPMENT.value
    )
    row = repo.unit("local-unit")
    assert row["network_mode"] == "local_development"
    # The historical fixture unit keeps the production-line binding.
    assert repo.unit("unit")["network_mode"] == "production_line"
    # A re-registration that changes the network binding is a hard error, not a silent switch.
    import pytest
    from xingtu.domain import CollectorError

    with pytest.raises(CollectorError, match="immutable"):
        repo.register_unit("local-unit", "acct", "local-dev", "/tmp/local-profile")
    with repo.connect() as conn:
        versions = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    # 010/011 add and normalise the creator-library read models (LIB-01), 012 adds the product
    # task completion moment, 013 the requirement form v2, 014 the F10 browser takeover, 015 the
    # creator video/metric fields, 016 their backfilled provenance and 017 the correction that
    # drops provenance entries describing a NULL column (DATA-02), 018 the creator update task
    # kinds and scheduling state (UPD), 019 the independent Collection Worker liveness
    # generation/heartbeat records, 020 the additive task-platform/unit-platform binding,
    # 021 the live-square creator scene, and 022 the per-scene update plans/service switches:
    # the set is asserted exhaustively so a migration that silently stops being applied is caught.
    assert [row["version"] for row in versions] == [
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        17,
        18,
        19,
        20,
        21,
        22,
    ]
    with repo.connect() as conn:
        binding = conn.execute(
            """SELECT platform,account_ref,profile_ref,enabled
            FROM execution_unit_platform_bindings WHERE unit_id='unit'"""
        ).fetchone()
    assert binding == {
        "platform": "douyin_xingtu",
        "account_ref": "synthetic-account",
        "profile_ref": "synthetic-profile",
        "enabled": True,
    }


def test_unit_selection_requires_both_task_kind_and_platform_binding(repo):
    from xingtu.domain import TaskKind

    assert repo.select_execution_unit(TaskKind.COLLECTION, "douyin_xingtu") == "unit"
    assert repo.select_execution_unit(TaskKind.COLLECTION, "kuaishou_juxing") is None
    repo.register_unit_platform_binding(
        "unit", "kuaishou_juxing", "ks-account", "ks-id", "ks-profile", "ks-registry"
    )
    assert repo.select_execution_unit(TaskKind.COLLECTION, "kuaishou_juxing") == "unit"
    repo.register_unit_platform_binding(
        "unit",
        "kuaishou_juxing",
        "ks-account",
        "ks-id",
        "ks-profile",
        "ks-registry",
        enabled=False,
    )
    assert repo.select_execution_unit(TaskKind.COLLECTION, "kuaishou_juxing") is None
    repo.register_unit_platform_binding(
        "unit", "kuaishou_juxing", "ks-account", "ks-id", "ks-profile", "ks-registry"
    )
    with pytest.raises(CollectorError, match="immutable"):
        repo.register_unit_platform_binding(
            "unit", "kuaishou_juxing", "changed", "ks-id", "ks-profile", "ks-registry"
        )
    repo.set_unit_task_kinds(
        "unit", [TaskKind.SCHEDULED_UPDATE], "test", "only scheduled for qualification test"
    )
    assert repo.select_execution_unit(TaskKind.COLLECTION, "kuaishou_juxing") is None
    assert repo.select_execution_unit(TaskKind.SCHEDULED_UPDATE, "kuaishou_juxing") == "unit"


def test_account_rebinding_is_explicit_audited_and_requires_released_browser(repo, started):
    import pytest
    from xingtu.domain import CollectorError

    # While a browser host owns the unit the binding must not move, even for an audited rebind.
    with pytest.raises(CollectorError, match="already has a browser host"):
        repo.rebind_unit_account("unit", "ID: 9000000000000001", "operator", "test rebind")
    with repo.connect() as conn:
        assert (
            conn.execute("SELECT expected_account_id FROM execution_units").fetchone()[
                "expected_account_id"
            ]
            is None
        )

    repo.release(
        "unit",
        started.attempt_id,
        started.lease_generation,
        stopped=True,
        disposition=ReleaseDisposition.SESSION_UNVERIFIED,
    )
    repo.rebind_unit_account(
        "unit",
        "ID: 9000000000000001",
        "operator",
        "bound account no longer usable",
        "docs/evidence/example.json",
        "ID: 9000000000000000",
    )
    row = repo.unit("unit")
    assert row["expected_account_id"] == "ID: 9000000000000001"
    assert row["verified_account_id"] is None
    assert row["state"] == "SESSION_UNVERIFIED"
    assert row["failure_reason"] == "ACCOUNT_BINDING_CHANGED"
    with repo.connect() as conn:
        binding = conn.execute(
            """SELECT expected_account_id,last_observed_status,last_observed_reason
            FROM execution_unit_platform_bindings
            WHERE unit_id='unit' AND platform='douyin_xingtu'"""
        ).fetchone()
    assert binding["expected_account_id"] == "ID: 9000000000000001"
    assert binding["last_observed_status"] == "INDETERMINATE"
    assert binding["last_observed_reason"] == "ACCOUNT_BINDING_CHANGED"
    with repo.connect() as conn:
        rebinding = conn.execute("SELECT * FROM unit_account_rebindings").fetchone()
        audit = conn.execute(
            "SELECT action FROM audit_logs WHERE action LIKE 'rebind_unit_account:%'"
        ).fetchone()
    assert rebinding["previous_account_id"] is None
    assert rebinding["previous_config_account_id"] == "ID: 9000000000000000"
    assert rebinding["account_id"] == "ID: 9000000000000001"
    assert rebinding["actor"] == "operator"
    assert rebinding["evidence_ref"] == "docs/evidence/example.json"
    assert audit is not None

    # Rebinding to the identity that is already bound is a no-op error, not a silent write.
    with pytest.raises(CollectorError, match="ACCOUNT_ALREADY_BOUND"):
        repo.rebind_unit_account("unit", "ID: 9000000000000001", "operator", "same account")
    with pytest.raises(CollectorError, match="ACCOUNT_ACTOR_AND_REASON_REQUIRED"):
        repo.rebind_unit_account("unit", "", "operator", "empty target")
    # Automated re-registration still refuses to change the identity.
    with pytest.raises(CollectorError, match="immutable"):
        repo.register_unit(
            "unit",
            "synthetic-account",
            "synthetic-line",
            "synthetic-profile",
            expected_account_id="ID: 9000000000000002",
        )


def test_login_resume_is_durable_idempotent_and_requires_released_browser(repo, started):
    from xingtu.domain import TaskStatus

    root = started.root_task_id
    with repo.edit(root) as (task, conn):
        task.state = TaskStatus.WAITING_FOR_LOGIN
        conn.execute("UPDATE task_dispatches SET sent=true WHERE root_task_id=%s", (root,))
    with pytest.raises(CollectorError, match="already has a browser host"):
        repo.request_login_maintenance("unit", "test")
    repo.release(
        "unit",
        started.attempt_id,
        started.lease_generation,
        stopped=True,
        disposition=ReleaseDisposition.LOGIN_REQUIRED,
    )
    assert repo.request_login_maintenance("unit", "test") == 1
    assert repo.request_login_maintenance("unit", "test") == 1
    assert repo.get(root).state == TaskStatus.WAITING_FOR_LOGIN


def test_invalidate_session_requires_stopped_unowned_unit(repo, started):
    with pytest.raises(CollectorError, match="active browser cannot be invalidated"):
        repo.invalidate_session("unit", "SESSION_RESTART_CHECK_FAILED", "test")

    repo.release(
        "unit",
        started.attempt_id,
        started.lease_generation,
        stopped=True,
        disposition=ReleaseDisposition.VERIFIED_READY,
    )
    repo.invalidate_session("unit", "SESSION_RESTART_CHECK_FAILED", "test")
    unit = repo.unit("unit")
    assert unit["state"] == "NEEDS_LOGIN"
    assert unit["failure_reason"] == "SESSION_RESTART_CHECK_FAILED"


def test_explicit_release_dispositions_do_not_confuse_account_or_unknown_session(repo, started):
    repo.release(
        "unit",
        started.attempt_id,
        started.lease_generation,
        stopped=True,
        disposition=ReleaseDisposition.ACCOUNT_MISMATCH,
        reason="PROTECTED_PAGE_WRONG_ACCOUNT",
    )
    unit = repo.unit("unit")
    assert unit["state"] == "ACCOUNT_MISMATCH"
    assert unit["last_session_status"] == "ACCOUNT_MISMATCH"
    assert unit["failure_reason"] == "PROTECTED_PAGE_WRONG_ACCOUNT"

    generation, _ = repo.acquire("unit", "maintenance", maintenance=True)
    repo.release(
        "unit",
        "maintenance",
        generation,
        stopped=True,
        disposition=ReleaseDisposition.SESSION_UNVERIFIED,
        reason="NO_REGISTERED_SESSION_SIGNAL",
    )
    unit = repo.unit("unit")
    assert unit["state"] == "SESSION_UNVERIFIED"
    assert unit["last_session_status"] == "INDETERMINATE"


def test_scoped_contract_breaker_requires_distinct_subjects_and_fresh_lease(repo):
    version = "synthetic-v1"
    scope = "profile_identity"
    assert (
        repo.record_capability_failure(version, scope, "a", 1, "IDENTITY_UNREADABLE") == "ENABLED"
    )
    assert (
        repo.record_capability_failure(version, scope, "a", 1, "IDENTITY_UNREADABLE") == "ENABLED"
    )
    assert (
        repo.record_capability_failure(version, scope, "b", 1, "IDENTITY_UNREADABLE") == "ENABLED"
    )
    assert (
        repo.record_capability_failure(version, scope, "c", 1, "IDENTITY_UNREADABLE") == "SUSPECTED"
    )
    repo.require_contract(version, {scope})
    repo.require_contract(version, {"search"})
    assert (
        repo.record_capability_failure(version, scope, "d", 2, "IDENTITY_UNREADABLE") == "DISABLED"
    )
    with pytest.raises(CollectorError, match="CONTRACT_SCOPE_DISABLED:profile_identity"):
        repo.require_contract(version, {scope})
    # A disabled profile scope does not disable an unrelated search capability.
    repo.require_contract(version, {"search"})
    repo.enable_contract_scope(version, scope, "test", "verified fixture update")
    repo.require_contract(version, {scope})
    with repo.connect() as conn:
        action = conn.execute(
            "SELECT action FROM audit_logs WHERE action LIKE 'enable_contract_scope:%'"
        ).fetchone()["action"]
    assert action.endswith(":verified fixture update")


def test_scoped_contract_breaker_can_be_disabled_for_rollback(repo, monkeypatch):
    monkeypatch.setenv("XINGTU_SCOPED_CONTRACT_HEALTH", "false")
    version, scope = "synthetic-v1", "profile_identity"
    for index in range(4):
        assert (
            repo.record_capability_failure(
                version, scope, f"rollback-{index}", index + 1, "IDENTITY_UNREADABLE"
            )
            == "ENABLED"
        )
    assert not repo.capability_has_failure_streak(version, scope)
    with repo.connect() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM contract_capability_health "
            "WHERE contract_version=%s AND scope=%s",
            (version, scope),
        ).fetchone()
    assert row and row["n"] == 0


def _maintenance(repo, started, owner="browser-host"):
    repo.release(
        "unit",
        started.attempt_id,
        started.lease_generation,
        stopped=True,
        disposition=ReleaseDisposition.LOGIN_REQUIRED,
    )
    generation, session = repo.acquire(
        "unit", owner, maintenance=True, root_task_id=started.root_task_id
    )
    return owner, generation, session


def _promote(repo, started, owner, generation, session):
    return repo.promote_maintenance_to_collect(
        "unit",
        owner,
        generation,
        session,
        "synthetic-account",
        "test",
        account_verified=True,
        protected_page_verified=True,
        line_verified=True,
    )


def test_promote_maintenance_to_collect_is_atomic_audited_and_fenced(repo, started):
    with repo.connect() as conn:
        conn.execute(
            "UPDATE task_dispatches SET sent=true WHERE root_task_id=%s",
            (started.root_task_id,),
        )
    owner, generation, session = _maintenance(repo, started)
    new_session = _promote(repo, started, owner, generation, session)
    unit = repo.unit("unit")
    assert new_session == session + 1
    assert unit["mode"] == "collect"
    assert unit["session_version"] == new_session
    assert unit["verified_account_id"] == "synthetic-account"
    assert unit["failure_reason"] is None
    assert str(unit["current_root_task_id"]) == started.root_task_id
    with repo.connect() as conn:
        dispatch = conn.execute(
            "SELECT sent FROM task_dispatches WHERE root_task_id=%s",
            (started.root_task_id,),
        ).fetchone()
        audit = conn.execute(
            "SELECT action FROM audit_logs WHERE root_task_id=%s ORDER BY id DESC LIMIT 1",
            (started.root_task_id,),
        ).fetchone()
    assert dispatch["sent"] is True
    assert audit["action"] == "promote_maintenance_to_collect:unit"

    before = repo.unit("unit")
    with pytest.raises(CollectorError, match="MAINTENANCE_LEASE_NOT_ACTIVE"):
        _promote(repo, started, owner, generation, session)
    after = repo.unit("unit")
    assert after["session_version"] == before["session_version"]
    assert after["mode"] == before["mode"]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("owner", "OWNER_OR_GENERATION_MISMATCH"),
        ("generation", "OWNER_OR_GENERATION_MISMATCH"),
        ("lease", "MAINTENANCE_LEASE_NOT_ACTIVE"),
        ("session", "SESSION_VERSION_CONFLICT"),
    ],
)
def test_promote_rejects_stale_fences_without_partial_update(repo, started, mutation, message):
    owner, generation, session = _maintenance(repo, started)
    call_owner, call_generation, call_session = owner, generation, session
    if mutation == "owner":
        call_owner = "stale-owner"
    elif mutation == "generation":
        call_generation -= 1
    elif mutation == "lease":
        with repo.connect() as conn:
            conn.execute("UPDATE execution_units SET lease_until=now()-interval '1 second'")
    else:
        call_session -= 1
    with repo.connect() as conn:
        before_audits = conn.execute("SELECT count(*) AS n FROM audit_logs").fetchone()["n"]
    with pytest.raises(CollectorError, match=message):
        _promote(repo, started, call_owner, call_generation, call_session)
    unit = repo.unit("unit")
    assert unit["mode"] == "maintenance"
    assert unit["session_version"] == session
    assert unit["verified_account_id"] is None
    with repo.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM audit_logs").fetchone()["n"] == before_audits


def test_only_one_concurrent_maintenance_promotion_commits(repo, started):
    owner, generation, session = _maintenance(repo, started)

    def promote():
        try:
            return _promote(repo, started, owner, generation, session)
        except CollectorError as exc:
            return exc.reason

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: promote(), range(2)))
    assert results.count(session + 1) == 1
    assert results.count("MAINTENANCE_LEASE_NOT_ACTIVE") == 1
    assert repo.unit("unit")["session_version"] == session + 1


def test_reverse_transition_only_accepts_auth_or_challenge(repo, started):
    owner, generation, session = _maintenance(repo, started)
    new_session = _promote(repo, started, owner, generation, session)
    with pytest.raises(CollectorError, match="NON_AUTH_FAILURE"):
        repo.transition_collect_to_maintenance(
            "unit", owner, generation, new_session, "PLATFORM_PERMISSION_DENIED", "test"
        )
    assert repo.unit("unit")["mode"] == "collect"

    repo.transition_collect_to_maintenance(
        "unit", owner, generation, new_session, "PLATFORM_SECURITY_CHALLENGE", "test"
    )
    unit = repo.unit("unit")
    assert unit["mode"] == "maintenance"
    assert unit["failure_reason"] == "PLATFORM_SECURITY_CHALLENGE"
    assert unit["maintenance_deadline"] is not None


def test_active_collect_rejects_concurrent_maintenance(repo, started):
    with pytest.raises(CollectorError, match="unit occupied"):
        repo.acquire(
            "unit", "maintenance-owner", maintenance=True, root_task_id=started.root_task_id
        )


def test_request_login_maintenance_only_requeues_existing_waiting_root(repo, started):
    from xingtu.domain import TaskStatus

    with repo.edit(started.root_task_id) as (task, conn):
        task.state = TaskStatus.WAITING_FOR_LOGIN
        conn.execute(
            "UPDATE task_dispatches SET sent=true WHERE root_task_id=%s",
            (started.root_task_id,),
        )
    repo.release(
        "unit",
        started.attempt_id,
        started.lease_generation,
        stopped=True,
        disposition=ReleaseDisposition.LOGIN_REQUIRED,
    )
    assert repo.request_login_maintenance("unit", "test") == 1
    assert repo.request_login_maintenance("unit", "test") == 1
    with repo.connect() as conn:
        row = conn.execute(
            "SELECT workflow_id,sent FROM task_dispatches WHERE root_task_id=%s",
            (started.root_task_id,),
        ).fetchone()
        root_count = conn.execute("SELECT count(*) AS n FROM root_tasks").fetchone()["n"]
    assert row == {"workflow_id": f"collect/{started.root_task_id}", "sent": False}
    assert root_count == 1


def test_repeated_login_confirmation_during_maintenance_reuses_owner(repo, started):
    from xingtu.domain import TaskStatus

    with repo.edit(started.root_task_id) as (task, _):
        task.state = TaskStatus.WAITING_FOR_LOGIN
    repo.release(
        "unit",
        started.attempt_id,
        started.lease_generation,
        stopped=True,
        disposition=ReleaseDisposition.LOGIN_REQUIRED,
    )
    generation, session = repo.acquire(
        "unit", "browser-host", maintenance=True, root_task_id=started.root_task_id
    )
    assert repo.request_login_maintenance("unit", "test") == 1
    unit = repo.unit("unit")
    assert unit["owner"] == "browser-host"
    assert unit["generation"] == generation
    assert unit["session_version"] == session
    assert unit["mode"] == "maintenance"


class _FakeRuntime:
    def __init__(self, *, close_ok=True, context=None):
        self.stopped = True
        self.close_ok = close_ok
        self.context = context or object()
        # A verified promotion now re-exports the session snapshot.  This fake has no real
        # BrowserContext, so the call is recorded instead of executed; the export itself is
        # covered by backend/tests/unit/test_session_snapshot.py.
        self.snapshot_exports: list[object] = []

    async def export_session_snapshot(self, context):
        self.snapshot_exports.append(context)
        return True

    @asynccontextmanager
    async def open(self):
        self.stopped = False
        try:
            yield self.context
        finally:
            if self.close_ok:
                self.stopped = True
            else:
                raise RuntimeError("close not acknowledged")


async def test_browser_host_owns_one_context_and_unverified_maintenance_stays_login_required(
    repo, started, tmp_path, capabilities
):
    from xingtu.browser_host import BrowserHost
    from xingtu.runtime import UnitConfig

    from backend.tests.contract.test_browser_flow import registry

    repo.release(
        "unit",
        started.attempt_id,
        started.lease_generation,
        stopped=True,
        disposition=ReleaseDisposition.VERIFIED_READY,
    )
    config = UnitConfig.model_validate(
        {
            "unit_id": "unit",
            "account_ref": "synthetic-account",
            "expected_account_id": "synthetic-account",
            "line_id": "local",
            "profile_directory": tmp_path / "profile",
            "registry_path": tmp_path / "registry.json",
            "network_mode": "local_development",
            "browser_channel": "chromium",
        }
    )
    runtime = _FakeRuntime()
    async with BrowserHost.lease(
        repo,
        config,
        registry(capabilities),
        tmp_path,
        started.root_task_id,
        "host-owner",
        maintenance=True,
        runtime=runtime,
    ) as host:
        assert host.browser is runtime.context
        assert repo.unit("unit")["mode"] == "maintenance"
        with pytest.raises(CollectorError, match="unit occupied"):
            repo.acquire("unit", "second-host", maintenance=True)
    unit = repo.unit("unit")
    assert unit["state"] == "NEEDS_LOGIN"
    assert unit["last_session_status"] == "LOGIN_REQUIRED"
    assert unit["browser_stopped"] is True
    assert unit["owner"] is None


async def test_ready_collect_lease_must_reverify_before_returning_ready(
    repo, started, tmp_path, capabilities
):
    from xingtu.browser_host import BrowserHost
    from xingtu.runtime import UnitConfig

    from backend.tests.contract.test_browser_flow import registry

    repo.release(
        "unit",
        started.attempt_id,
        started.lease_generation,
        stopped=True,
        disposition=ReleaseDisposition.VERIFIED_READY,
    )
    config = UnitConfig.model_validate(
        {
            "unit_id": "unit",
            "account_ref": "synthetic-account",
            "expected_account_id": "synthetic-account",
            "line_id": "local",
            "profile_directory": tmp_path / "profile",
            "registry_path": tmp_path / "registry.json",
            "network_mode": "local_development",
            "browser_channel": "chromium",
        }
    )
    async with BrowserHost.lease(
        repo,
        config,
        registry(capabilities),
        tmp_path,
        started.root_task_id,
        "host-owner",
        maintenance=False,
        runtime=_FakeRuntime(),
    ):
        pass
    unit = repo.unit("unit")
    assert unit["state"] == "SESSION_UNVERIFIED"
    assert unit["last_session_status"] == "INDETERMINATE"


async def test_browser_host_unconfirmed_close_quarantines(repo, started, tmp_path, capabilities):
    from xingtu.browser_host import BrowserHost
    from xingtu.runtime import UnitConfig

    from backend.tests.contract.test_browser_flow import registry

    repo.release(
        "unit",
        started.attempt_id,
        started.lease_generation,
        stopped=True,
        disposition=ReleaseDisposition.VERIFIED_READY,
    )
    config = UnitConfig.model_validate(
        {
            "unit_id": "unit",
            "account_ref": "synthetic-account",
            "expected_account_id": "synthetic-account",
            "line_id": "local",
            "profile_directory": tmp_path / "profile",
            "registry_path": tmp_path / "registry.json",
            "network_mode": "local_development",
            "browser_channel": "chromium",
        }
    )
    with pytest.raises(RuntimeError, match="close not acknowledged"):
        async with BrowserHost.lease(
            repo,
            config,
            registry(capabilities),
            tmp_path,
            started.root_task_id,
            "host-owner",
            maintenance=True,
            runtime=_FakeRuntime(close_ok=False),
        ):
            pass
    unit = repo.unit("unit")
    assert unit["state"] == "QUARANTINED"
    assert unit["browser_stopped"] is False


async def test_browser_host_promotes_and_collects_with_the_exact_same_context(
    repo, started, tmp_path, capabilities, monkeypatch
):
    import xingtu.browser_host as host_module
    from xingtu.browser_host import BrowserHost
    from xingtu.runtime import UnitConfig

    from backend.tests.contract.test_browser_flow import registry

    class Page:
        def __init__(self):
            self.urls = []

        async def goto(self, url, **_):
            self.urls.append(url)

    class Browser:
        def __init__(self):
            self.pages = [Page()]

        async def new_page(self):
            page = Page()
            self.pages.append(page)
            return page

    verified = {}

    async def clearance(page, _spec, _timeout, _attested=None):
        verified["maintenance_page"] = page
        return "synthetic-account"

    class Verifier:
        def __init__(self, browser, *_args, **_kwargs):
            verified["browser"] = browser

        async def check_session(self, page, **_):
            verified["protected_page"] = page
            # Promotion now observes the verifier's own health instead of relabelling a manual
            # clearance as an automatic DOM verification, so the stub must return the real type.
            return SessionHealth(
                status=SessionHealthStatus.VALID,
                expected_account_id="synthetic-account",
                observed_account_id="synthetic-account",
                protected_page_verified=True,
                evidence_reason="PROTECTED_PAGE_AND_ACCOUNT_VERIFIED",
            )

        async def close(self):
            pass

    monkeypatch.setattr(host_module, "wait_for_manual_clearance", clearance)
    monkeypatch.setattr(host_module, "BrowserAdapter", Verifier)
    repo.release(
        "unit",
        started.attempt_id,
        started.lease_generation,
        stopped=True,
        disposition=ReleaseDisposition.VERIFIED_READY,
    )
    config = UnitConfig.model_validate(
        {
            "unit_id": "unit",
            "account_ref": "synthetic-account",
            "expected_account_id": "synthetic-account",
            "line_id": "local",
            "profile_directory": tmp_path / "profile",
            "registry_path": tmp_path / "registry.json",
            "network_mode": "local_development",
            "browser_channel": "chromium",
        }
    )
    browser = Browser()
    runtime = _FakeRuntime(context=browser)
    async with BrowserHost.lease(
        repo,
        config,
        registry(capabilities),
        tmp_path,
        started.root_task_id,
        "host-owner",
        maintenance=True,
        runtime=runtime,
    ) as host:
        original_context = host.browser
        new_session = await host.maintain_and_promote(timeout=10, actor="test")
        assert host.mode == "collect"
        assert host.browser is original_context is browser
        assert verified == {
            "maintenance_page": browser.pages[0],
            "browser": browser,
            "protected_page": browser.pages[0],
        }
        # Maintenance opens the protected business surface first.  A reusable session stays on
        # the signed-in application; only a genuinely logged-out profile is redirected by the
        # platform to SSO.  Opening the SSO entry first would show a login form unconditionally.
        assert browser.pages[0].urls == [registry(capabilities).search.entry_url]
        assert host.take_collection_page() is browser.pages[0]
        assert host.take_collection_page() is None
        assert len(browser.pages) == 1
        assert new_session == started.session_version + 1
        assert repo.unit("unit")["mode"] == "collect"
        # A promotion that verified the protected surface re-exports the session snapshot for the
        # next launch.  Losing it silently would drop session-scoped business cookies.
        assert runtime.snapshot_exports == [browser]
    # The promotion above verified a live account and protected business capability, so a
    # confirmed close returns the unit to READY: the persisted profile may be reused by the
    # next task without another manual login.
    unit = repo.unit("unit")
    assert unit["state"] == "READY"
    assert unit["browser_stopped"] is True
    assert unit["owner"] is None


def test_completed_at_only_moves_on_the_transition_into_a_terminal_state(repo, plan):
    """UI-01 R4 at the worker write path: progress keeps it null, a terminal state stamps it once.

    The same helper covers every collector terminal transition because all of them persist through
    `Repository._save` / `edit`.
    """

    root = repo.create(
        plan,
        "unit",
        uid(),
        "test",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        modules=["basic"],
    )

    def read():
        with repo.connect() as conn:
            return conn.execute(
                "SELECT state,version,updated_at,completed_at FROM root_tasks"
                " WHERE root_task_id=%s",
                (root,),
            ).fetchone()

    assert read()["completed_at"] is None

    with repo.edit(root) as (task, _):
        task.state = TaskStatus.SEARCHING
    progressing = read()
    assert progressing["completed_at"] is None

    with repo.edit(root) as (task, _):
        task.state = TaskStatus.COMPLETED
    completed = read()
    assert completed["completed_at"] is not None
    assert completed["updated_at"] == completed["completed_at"]

    # A later non-terminal write (a retry cycle re-entering the queue) refreshes `updated_at` and
    # must leave the recorded completion moment untouched.
    with repo.edit(root) as (task, _):
        task.state = TaskStatus.QUEUED
    reopened = read()
    assert reopened["state"] == TaskStatus.QUEUED
    assert reopened["completed_at"] == completed["completed_at"]
    assert reopened["updated_at"] > completed["completed_at"]


def test_platform_dedicated_unit_has_no_implicit_xingtu_binding(repo):
    repo.register_unit(
        "unit-juxing",
        "juxing-account",
        "local-line",
        "juxing-profile",
        "local_development",
        "60821564",
        register_xingtu_binding=False,
    )
    repo.register_unit_platform_binding(
        "unit-juxing",
        "kuaishou_juxing",
        "juxing-account",
        "60821564",
        "juxing-profile",
        "contracts/kuaishou_juxing.verified.json",
    )
    with repo.connect() as conn:
        rows = conn.execute(
            "SELECT platform,enabled FROM execution_unit_platform_bindings "
            "WHERE unit_id='unit-juxing' ORDER BY platform"
        ).fetchall()
    assert [(row["platform"], row["enabled"]) for row in rows] == [("kuaishou_juxing", True)]
    from xingtu.domain import TaskKind

    assert repo.select_collection_unit("kuaishou_juxing") == "unit-juxing"
    # The dedicated Juxing unit must never be a Xingtu candidate.
    assert repo.select_execution_unit(TaskKind.COLLECTION, "douyin_xingtu") != "unit-juxing"


def test_select_collection_unit_prefers_a_healthy_unit_but_keeps_a_single_one(repo):
    for unit in ("unit-juxing-a", "unit-juxing-b"):
        repo.register_unit(
            unit,
            unit + "-account",
            "local-line",
            unit + "-profile",
            "local_development",
            "60821564",
            register_xingtu_binding=False,
        )
        repo.register_unit_platform_binding(
            unit,
            "kuaishou_juxing",
            unit + "-account",
            "60821564",
            unit + "-profile",
            "contracts/kuaishou_juxing.verified.json",
        )
    assert repo.select_collection_unit("kuaishou_juxing") == "unit-juxing-a"
    with repo.connect() as conn:
        conn.execute("UPDATE execution_units SET state='QUARANTINED' WHERE unit_id='unit-juxing-a'")
    assert repo.select_collection_unit("kuaishou_juxing") == "unit-juxing-b"


def test_retry_re_resolves_a_historical_juxing_task_to_the_dedicated_unit(repo):
    from xingtu.domain import Filter, FilterPlan

    repo.register_unit(
        "unit-juxing",
        "juxing-account",
        "local-line",
        "juxing-profile",
        "local_development",
        "60821564",
        register_xingtu_binding=False,
    )
    repo.register_unit_platform_binding(
        "unit-juxing",
        "kuaishou_juxing",
        "juxing-account",
        "60821564",
        "juxing-profile",
        "contracts/kuaishou_juxing.verified.json",
    )
    plan = FilterPlan(
        schema_version="filter_plan.v3",
        platform="kuaishou_juxing",
        capability_version="synthetic-v1",
        target_count=1,
        filters=[Filter(field="keyword", operator="eq", value="母婴", source_fields=["keyword"])],
    )
    root = repo.create(
        plan,
        "unit",
        uid(),
        "test",
        adapter_version="synthetic-v1",
        contract_version="synthetic-v1",
        modules=["basic"],
    )
    with repo.edit(root) as (task, _):
        task.state = TaskStatus.FAILED
        task.failure_reason = "SYNTHETIC"
    failed = repo.get(root)
    repo.command(root, "retry", failed.version, "test")
    retried = repo.get(root)
    assert retried.execution_unit_id == "unit-juxing"
    with repo.connect() as conn:
        column = conn.execute(
            "SELECT unit_id FROM root_tasks WHERE root_task_id=%s", (root,)
        ).fetchone()
        dispatch = conn.execute(
            "SELECT sent FROM task_dispatches WHERE root_task_id=%s "
            "AND segment=(SELECT max(segment) FROM task_dispatches WHERE root_task_id=%s)",
            (root, root),
        ).fetchone()
    assert column["unit_id"] == "unit-juxing"
    assert dispatch["sent"] is False
