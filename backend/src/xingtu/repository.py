from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .creator_library import CreatorLibraryWriter
from .domain import (
    Candidate,
    Checkpoint,
    CollectorError,
    ExecutionContext,
    FeaturedCard,
    FeaturedCollectionObservation,
    FieldStatus,
    FilterPlan,
    NetworkMode,
    PlatformId,
    ProfileRequirement,
    ReleaseDisposition,
    SessionHealthStatus,
    TaskKind,
    TaskRecord,
    TaskStatus,
    uid,
    utcnow,
)
from .retry_policy import (
    challenge_blocks_retry,
    decide_retry_scope,
    is_retryable,
    requeue_for_retry,
)

logger = logging.getLogger(__name__)

RUNNING = {
    TaskStatus.QUEUED,
    TaskStatus.SEARCHING,
    TaskStatus.COLLECTING,
    TaskStatus.PERSISTING,
    TaskStatus.RETRY_WAIT,
    TaskStatus.WAITING_FOR_VERIFICATION,
}

# Statuses in which a task has stopped progressing. The set matches the product query layer's
# `TERMINAL_STATES`; it is defined here as well so the task write path can stamp `completed_at`
# without importing the query layer.
TERMINAL_TASK_STATES = frozenset(
    {
        TaskStatus.CANCELLED,
        TaskStatus.COMPLETED,
        TaskStatus.PARTIAL_COMPLETED,
        TaskStatus.FAILED_VALIDATION,
        TaskStatus.FAILED,
    }
)

# Appended to a root-task UPDATE: record the completion moment only on the transition into a
# terminal state, and never overwrite a previously recorded one.
TERMINAL_COMPLETED_AT_CLAUSE = (
    ",completed_at=CASE WHEN %s AND completed_at IS NULL THEN now() ELSE completed_at END"
)


def scoped_contract_health_enabled() -> bool:
    return os.environ.get("XINGTU_SCOPED_CONTRACT_HEALTH", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


class Repository:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def connect(self) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def migrate(self, directory: Path) -> None:
        """Apply every pending versioned migration in order, inside one transaction."""
        files = sorted(directory.glob("*.sql"))
        if not files:
            raise CollectorError("STORAGE_UNAVAILABLE", "NO_MIGRATIONS_FOUND")
        with self.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(904051)")
            found = conn.execute("SELECT to_regclass('schema_migrations') AS name").fetchone()
            applied: set[int] = set()
            if found and found["name"]:
                applied = {
                    row["version"]
                    for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
                }
            for path in files:
                prefix = path.name.split("_", 1)[0]
                if not prefix.isdigit():
                    raise CollectorError(
                        "STORAGE_UNAVAILABLE", f"INVALID_MIGRATION_NAME:{path.name}"
                    )
                if int(prefix) in applied:
                    continue
                conn.execute(path.read_text())

    def require_contract(self, version: str, scopes: set[str] | None = None) -> None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT disabled FROM contract_health WHERE contract_version=%s", (version,)
            ).fetchone()
            if row and row["disabled"]:
                raise CollectorError("PLATFORM_PAGE_CHANGED", "CONTRACT_DISABLED")
            if scopes and scoped_contract_health_enabled():
                disabled = conn.execute(
                    "SELECT scope FROM contract_capability_health "
                    "WHERE contract_version=%s AND scope=ANY(%s) AND state='DISABLED' "
                    "ORDER BY scope LIMIT 1",
                    (version, list(scopes)),
                ).fetchone()
                if disabled:
                    raise CollectorError(
                        "PLATFORM_PAGE_CHANGED", f"CONTRACT_SCOPE_DISABLED:{disabled['scope']}"
                    )

    def enable_contract(self, version: str, actor: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO contract_health(contract_version,disabled) VALUES(%s,false) "
                "ON CONFLICT(contract_version) DO UPDATE SET disabled=false, "
                "failure_reason=NULL,updated_at=now()",
                (version,),
            )
            conn.execute(
                "INSERT INTO audit_logs(actor,action) VALUES(%s,%s)",
                (actor, "enable_contract:" + version),
            )

    def enable_contract_scope(self, version: str, scope: str, actor: str, reason: str) -> None:
        if not scope or not reason.strip():
            raise CollectorError("INVALID_FORM", "SCOPE_AND_REASON_REQUIRED")
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM contract_capability_failures WHERE contract_version=%s AND scope=%s",
                (version, scope),
            )
            conn.execute(
                """INSERT INTO contract_capability_health(contract_version,scope,state)
                VALUES(%s,%s,'ENABLED') ON CONFLICT(contract_version,scope) DO UPDATE SET
                state='ENABLED',consecutive_failures=0,distinct_subject_count=0,
                first_failed_at=NULL,last_failed_at=NULL,failure_reason=NULL,
                suspected_generation=NULL,updated_at=now()""",
                (version, scope),
            )
            conn.execute(
                "INSERT INTO audit_logs(actor,action) VALUES(%s,%s)",
                (actor, f"enable_contract_scope:{version}:{scope}:{reason.strip()}"),
            )

    def record_capability_failure(
        self,
        version: str,
        scope: str,
        subject_id: str,
        generation: int,
        reason: str,
    ) -> str:
        """Advance a scoped breaker only with distinct failing subjects.

        Three distinct subjects in one uninterrupted failure streak produce ``SUSPECTED``.
        A fourth distinct subject in a newer browser lease confirms ``DISABLED``.  Re-observing
        one subject is idempotent and can never advance the breaker by itself.
        """
        if not scoped_contract_health_enabled():
            return "ENABLED"
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO contract_capability_health(contract_version,scope) VALUES(%s,%s) "
                "ON CONFLICT DO NOTHING",
                (version, scope),
            )
            health = conn.execute(
                "SELECT * FROM contract_capability_health "
                "WHERE contract_version=%s AND scope=%s FOR UPDATE",
                (version, scope),
            ).fetchone()
            assert health
            inserted = conn.execute(
                "INSERT INTO contract_capability_failures"
                "(contract_version,scope,subject_id,lease_generation,failure_reason) "
                "VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING subject_id",
                (version, scope, subject_id, generation, reason),
            ).fetchone()
            if not inserted:
                return str(health["state"])
            count_row = conn.execute(
                "SELECT count(*) AS n FROM contract_capability_failures "
                "WHERE contract_version=%s AND scope=%s",
                (version, scope),
            ).fetchone()
            assert count_row
            count = int(count_row["n"])
            state = str(health["state"])
            suspected_generation = health["suspected_generation"]
            if (
                state == "SUSPECTED"
                and suspected_generation is not None
                and (generation > suspected_generation and count >= 4)
            ):
                state = "DISABLED"
            elif state == "ENABLED" and count >= 3:
                state = "SUSPECTED"
                suspected_generation = generation
            conn.execute(
                """UPDATE contract_capability_health SET state=%s,
                consecutive_failures=%s,distinct_subject_count=%s,
                first_failed_at=coalesce(first_failed_at,now()),last_failed_at=now(),
                failure_reason=%s,suspected_generation=%s,updated_at=now()
                WHERE contract_version=%s AND scope=%s""",
                (
                    state,
                    count,
                    count,
                    reason,
                    suspected_generation,
                    version,
                    scope,
                ),
            )
            return state

    def record_capability_success(self, version: str, scope: str) -> None:
        """A successful invariant check resets only a non-disabled failure streak."""
        if not scoped_contract_health_enabled():
            return
        with self.connect() as conn:
            row = conn.execute(
                "SELECT state FROM contract_capability_health "
                "WHERE contract_version=%s AND scope=%s FOR UPDATE",
                (version, scope),
            ).fetchone()
            if not row or row["state"] == "DISABLED":
                return
            conn.execute(
                "DELETE FROM contract_capability_failures WHERE contract_version=%s AND scope=%s",
                (version, scope),
            )
            conn.execute(
                """UPDATE contract_capability_health SET state='ENABLED',
                consecutive_failures=0,distinct_subject_count=0,first_failed_at=NULL,
                last_failed_at=NULL,failure_reason=NULL,suspected_generation=NULL,updated_at=now()
                WHERE contract_version=%s AND scope=%s""",
                (version, scope),
            )

    def capability_has_failure_streak(self, version: str, scope: str) -> bool:
        if not scoped_contract_health_enabled():
            return False
        with self.connect() as conn:
            row = conn.execute(
                "SELECT consecutive_failures FROM contract_capability_health "
                "WHERE contract_version=%s AND scope=%s",
                (version, scope),
            ).fetchone()
            return bool(row and row["consecutive_failures"])

    def register_unit(
        self,
        unit: str,
        account: str,
        line: str,
        profile: str,
        network_mode: str = NetworkMode.PRODUCTION_LINE.value,
        expected_account_id: str | None = None,
        *,
        register_xingtu_binding: bool = True,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO execution_units(
                unit_id,account_ref,line_ref,profile_ref,network_mode,expected_account_id)
                VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(unit_id) DO NOTHING""",
                (unit, account, line, profile, network_mode, expected_account_id),
            )
            if expected_account_id:
                conn.execute(
                    "UPDATE execution_units SET expected_account_id=%s "
                    "WHERE unit_id=%s AND expected_account_id IS NULL",
                    (expected_account_id, unit),
                )
            row = conn.execute("SELECT * FROM execution_units WHERE unit_id=%s", (unit,)).fetchone()
            if not row or (
                row["account_ref"],
                row["line_ref"],
                row["profile_ref"],
                row["network_mode"],
            ) != (account, line, profile, network_mode):
                raise CollectorError("RESOURCE_UNAVAILABLE", "unit binding is immutable")
            if expected_account_id and row["expected_account_id"] != expected_account_id:
                raise CollectorError("RESOURCE_UNAVAILABLE", "unit account identity is immutable")
            if register_xingtu_binding:
                # Legacy Xingtu units keep the implicit Xingtu binding. A platform-dedicated
                # unit (for example Juxing) must not acquire a Xingtu binding here, otherwise
                # Xingtu promotion/dispatch could route to a browser that only owns the other
                # platform's account and profile.
                conn.execute(
                    """INSERT INTO execution_unit_platform_bindings(
                    unit_id,platform,account_ref,expected_account_id,profile_ref,registry_ref)
                    VALUES(%s,'douyin_xingtu',%s,%s,%s,'contracts/douyin_xingtu.verified.json')
                    ON CONFLICT(unit_id,platform) DO NOTHING""",
                    (unit, account, expected_account_id or account, profile),
                )

    def rebind_unit_account(
        self,
        unit: str,
        account_id: str,
        actor: str,
        reason: str,
        evidence_ref: str | None = None,
        previous_config_account_id: str | None = None,
    ) -> str | None:
        """Change the bound platform account through an explicit, audited rebinding.

        The binding stays immutable on every automated path (``register_unit`` still rejects a
        changed identity).  A legitimate change of login identity — for example the bound account
        is no longer usable and the operator logs in a different one — must go through this
        method, which refuses to run while a browser host owns the unit and resets the session to
        unverified so the new identity is observed from scratch.  No account is ever rebound
        automatically on ``ACCOUNT_MISMATCH``.

        ``previous_config_account_id`` records the superseded binding when it only ever existed in
        the unit config file, so the audit row documents the real before/after in that case too.
        """
        if not account_id or not actor.strip() or not reason.strip():
            raise CollectorError("INVALID_FORM", "ACCOUNT_ACTOR_AND_REASON_REQUIRED")
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM execution_units WHERE unit_id=%s FOR UPDATE", (unit,)
            ).fetchone()
            if not row:
                raise CollectorError("RESOURCE_UNAVAILABLE", "unit not registered")
            if row["owner"] or not row["browser_stopped"]:
                raise CollectorError("RESOURCE_UNAVAILABLE", "unit already has a browser host")
            previous = row["expected_account_id"] or previous_config_account_id
            if previous == account_id:
                raise CollectorError("INVALID_FORM", "ACCOUNT_ALREADY_BOUND")
            conn.execute(
                """UPDATE execution_units SET expected_account_id=%s,verified_account_id=NULL,
                state='SESSION_UNVERIFIED',owner=NULL,mode=NULL,lease_until=NULL,
                current_root_task_id=NULL,maintenance_deadline=NULL,idle_deadline=NULL,
                last_session_status='INDETERMINATE',last_session_checked_at=now(),
                last_session_reason='ACCOUNT_BINDING_CHANGED',
                failure_reason='ACCOUNT_BINDING_CHANGED'
                WHERE unit_id=%s""",
                (account_id, unit),
            )
            conn.execute(
                """UPDATE execution_unit_platform_bindings
                SET expected_account_id=%s,last_observed_status='INDETERMINATE',
                    last_observed_at=now(),last_observed_reason='ACCOUNT_BINDING_CHANGED'
                WHERE unit_id=%s AND platform='douyin_xingtu'""",
                (account_id, unit),
            )
            conn.execute(
                """INSERT INTO unit_account_rebindings(
                unit_id,previous_account_id,account_id,actor,reason,evidence_ref,
                previous_config_account_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                (
                    unit,
                    row["expected_account_id"],
                    account_id,
                    actor.strip(),
                    reason.strip(),
                    evidence_ref,
                    previous_config_account_id,
                ),
            )
            conn.execute(
                "INSERT INTO audit_logs(actor,action) VALUES(%s,%s)",
                (
                    actor.strip(),
                    "rebind_unit_account:"
                    + unit
                    + ":"
                    + str(previous)
                    + "->"
                    + account_id
                    + ":"
                    + reason.strip(),
                ),
            )
            return previous

    def register_unit_platform_binding(
        self,
        unit: str,
        platform: str,
        account_ref: str,
        expected_account_id: str,
        profile_ref: str,
        registry_ref: str,
        *,
        enabled: bool = True,
    ) -> None:
        """Register immutable platform identity from UnitConfig; observations remain mutable."""

        with self.connect() as conn:
            if not conn.execute(
                "SELECT 1 FROM execution_units WHERE unit_id=%s", (unit,)
            ).fetchone():
                raise CollectorError("RESOURCE_UNAVAILABLE", "unit not registered")
            conn.execute(
                """INSERT INTO execution_unit_platform_bindings(
                unit_id,platform,account_ref,expected_account_id,profile_ref,registry_ref,enabled)
                VALUES(%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(unit_id,platform) DO UPDATE SET enabled=EXCLUDED.enabled""",
                (
                    unit,
                    platform,
                    account_ref,
                    expected_account_id,
                    profile_ref,
                    registry_ref,
                    enabled,
                ),
            )
            row = conn.execute(
                """SELECT account_ref,expected_account_id,profile_ref,registry_ref,enabled
                FROM execution_unit_platform_bindings WHERE unit_id=%s AND platform=%s""",
                (unit, platform),
            ).fetchone()
            actual = (
                (
                    row["account_ref"],
                    row["expected_account_id"],
                    row["profile_ref"],
                    row["registry_ref"],
                    row["enabled"],
                )
                if row
                else None
            )
            expected = (
                account_ref,
                expected_account_id,
                profile_ref,
                registry_ref,
                enabled,
            )
            if actual != expected:
                raise CollectorError("RESOURCE_UNAVAILABLE", "platform binding is immutable")

    def recover_stopped_unit(self, unit: str, actor: str) -> None:
        # Caller must perform local profile lock + process isolation verification first.
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM execution_units WHERE unit_id=%s FOR UPDATE", (unit,)
            ).fetchone()
            if not row:
                raise CollectorError("RESOURCE_UNAVAILABLE", "unit not registered")
            expired_lease = (
                row["state"] == "LEASED"
                and row["owner"]
                and row["lease_until"]
                and row["lease_until"] <= utcnow()
            )
            if row["state"] != "QUARANTINED" and not expired_lease:
                raise CollectorError("RESOURCE_UNAVAILABLE", "UNIT_NOT_RECOVERABLE")
            conn.execute(
                "UPDATE execution_units SET state='SESSION_UNVERIFIED',owner=NULL,mode=NULL, "
                "generation=generation+1,lease_until=NULL,browser_stopped=true, "
                "current_root_task_id=NULL,maintenance_deadline=NULL,idle_deadline=NULL, "
                "last_session_status='INDETERMINATE',last_session_checked_at=now(), "
                "last_session_reason='RECOVERED_AFTER_UNCONFIRMED_EXIT', "
                "failure_reason='RECOVERED_AFTER_UNCONFIRMED_EXIT' "
                "WHERE unit_id=%s",
                (unit,),
            )
            conn.execute(
                "INSERT INTO audit_logs(actor,action) VALUES(%s,%s)",
                (actor, "recover_stopped_unit:" + unit),
            )

    def invalidate_session(self, unit: str, reason: str, actor: str) -> None:
        """Fail a stopped, unowned unit closed after protected-session verification fails."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM execution_units WHERE unit_id=%s FOR UPDATE", (unit,)
            ).fetchone()
            if not row:
                raise CollectorError("RESOURCE_UNAVAILABLE", "unit not registered")
            if row["owner"] or not row["browser_stopped"]:
                raise CollectorError("RESOURCE_UNAVAILABLE", "active browser cannot be invalidated")
            conn.execute(
                "UPDATE execution_units SET state='NEEDS_LOGIN',failure_reason=%s WHERE unit_id=%s",
                (reason, unit),
            )
            conn.execute(
                "INSERT INTO audit_logs(actor,action) VALUES(%s,%s)",
                (actor, "invalidate_session:" + unit + ":" + reason),
            )

    def unit(self, unit: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM execution_units WHERE unit_id=%s", (unit,)).fetchone()
            if not row:
                raise CollectorError("RESOURCE_UNAVAILABLE", "unit not registered")
            return row

    def has_active_unit_claim(self, unit: str) -> bool:
        """Whether a live lease, verification event or takeover still owns the unit.

        Startup reconciliation must never clear a quarantined unit while a person or another
        process is still acting on it.  This is a read-only pre-check; ``recover_stopped_unit``
        still takes the unit row lock and performs its own state transition.
        """
        with self.connect() as conn:
            row = conn.execute(
                """SELECT (
                EXISTS(SELECT 1 FROM execution_units
                       WHERE unit_id=%s AND owner IS NOT NULL AND lease_until > now())
                OR EXISTS(SELECT 1 FROM verification_events
                          WHERE unit_id=%s AND state IN ('OPEN','ACKNOWLEDGED'))
                OR EXISTS(SELECT 1 FROM browser_takeover_sessions
                          WHERE unit_id=%s AND state IN ('REQUESTED','ACTIVE','VERIFYING'))
                ) AS active""",
                (unit, unit, unit),
            ).fetchone()
            return bool(row and row["active"])

    def register_worker_instance(
        self,
        unit: str,
        worker_instance_id: str,
        process_id: int,
        platform: str,
        *,
        stale_after_seconds: int = 45,
    ) -> int:
        """Register exactly one fresh Collection Worker without borrowing a browser lease."""

        if process_id <= 0 or stale_after_seconds <= 0:
            raise CollectorError("INVALID_FORM", "INVALID_WORKER_REGISTRATION")
        with self.connect() as conn:
            execution_unit = conn.execute(
                "SELECT worker_generation FROM execution_units WHERE unit_id=%s FOR UPDATE",
                (unit,),
            ).fetchone()
            if not execution_unit:
                raise CollectorError("RESOURCE_UNAVAILABLE", "unit not registered")
            fresh = conn.execute(
                """SELECT worker_instance_id FROM execution_unit_workers
                WHERE unit_id=%s AND stopped_at IS NULL
                AND last_heartbeat_at > now()-(%s * interval '1 second')
                FOR UPDATE""",
                (unit, stale_after_seconds),
            ).fetchall()
            if fresh:
                raise CollectorError("RESOURCE_UNAVAILABLE", "DUPLICATE_WORKER_FOR_UNIT")
            conn.execute(
                """UPDATE execution_unit_workers SET stopped_at=now(),stop_reason='STALE_REPLACED'
                WHERE unit_id=%s AND stopped_at IS NULL""",
                (unit,),
            )
            generation = int(execution_unit["worker_generation"]) + 1
            conn.execute(
                "UPDATE execution_units SET worker_generation=%s WHERE unit_id=%s",
                (generation, unit),
            )
            conn.execute(
                """INSERT INTO execution_unit_workers(
                worker_instance_id,unit_id,worker_generation,process_id,platform)
                VALUES(%s,%s,%s,%s,%s)""",
                (worker_instance_id, unit, generation, process_id, platform),
            )
            return generation

    def heartbeat_worker_instance(
        self, unit: str, worker_instance_id: str, worker_generation: int
    ) -> None:
        with self.connect() as conn:
            updated = conn.execute(
                """UPDATE execution_unit_workers w SET last_heartbeat_at=now()
                FROM execution_units u
                WHERE w.worker_instance_id=%s AND w.unit_id=%s
                AND w.worker_generation=%s AND w.stopped_at IS NULL
                AND u.unit_id=w.unit_id AND u.worker_generation=w.worker_generation
                RETURNING w.worker_instance_id""",
                (worker_instance_id, unit, worker_generation),
            ).fetchone()
            if not updated:
                raise CollectorError("RESOURCE_UNAVAILABLE", "WORKER_INSTANCE_FENCED")

    def stop_worker_instance(
        self,
        unit: str,
        worker_instance_id: str,
        worker_generation: int,
        reason: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """UPDATE execution_unit_workers SET stopped_at=now(),stop_reason=%s
                WHERE worker_instance_id=%s AND unit_id=%s AND worker_generation=%s
                AND stopped_at IS NULL""",
                (reason, worker_instance_id, unit, worker_generation),
            )

    def select_execution_unit(
        self, task_kind: TaskKind, platform: str = "douyin_xingtu"
    ) -> str | None:
        """First unit eligible for both the task kind and platform; no load balancing in MVP."""
        with self.connect() as conn:
            row = conn.execute(
                """SELECT u.unit_id FROM execution_units u
                JOIN execution_unit_platform_bindings b ON b.unit_id=u.unit_id
                WHERE %s = ANY(u.allowed_task_kinds) AND u.state <> 'QUARANTINED'
                  AND b.platform=%s AND b.enabled=true
                ORDER BY u.unit_id LIMIT 1""",
                (task_kind.value, platform),
            ).fetchone()
            return str(row["unit_id"]) if row else None

    def select_collection_unit(self, platform: str) -> str | None:
        """First unit eligible to execute a collection task for this platform.

        A quarantined unit is still returned when it is the only binding: promotion must stay
        durable and let the existing unit recovery path handle it, exactly like the single-unit
        assignment did before dedicated units existed. When several units are eligible, a healthy
        unit is preferred; there is no load balancing in the MVP.
        """
        with self.connect() as conn:
            row = conn.execute(
                """SELECT u.unit_id FROM execution_units u
                JOIN execution_unit_platform_bindings b ON b.unit_id=u.unit_id
                WHERE 'collection' = ANY(u.allowed_task_kinds)
                  AND b.platform=%s AND b.enabled=true
                ORDER BY (u.state='QUARANTINED'), u.unit_id LIMIT 1""",
                (platform,),
            ).fetchone()
            return str(row["unit_id"]) if row else None

    def unit_supports_platform(self, unit: str, platform: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """SELECT 1 FROM execution_unit_platform_bindings
                WHERE unit_id=%s AND platform=%s AND enabled=true""",
                (unit, platform),
            ).fetchone()
            return row is not None

    def observe_unit_platform_session(
        self, unit: str, platform: str, status: SessionHealthStatus, reason: str
    ) -> None:
        """Persist an observation only; a future task still performs a live browser check."""

        with self.connect() as conn:
            updated = conn.execute(
                """UPDATE execution_unit_platform_bindings
                SET last_observed_status=%s,last_observed_at=now(),last_observed_reason=%s
                WHERE unit_id=%s AND platform=%s RETURNING unit_id""",
                (status.value, reason, unit, platform),
            ).fetchone()
            if not updated:
                raise CollectorError("RESOURCE_UNAVAILABLE", "PLATFORM_BINDING_NOT_CONFIGURED")

    def set_unit_task_kinds(self, unit: str, kinds: list[TaskKind], actor: str, reason: str) -> int:
        """Replace one unit's allowed task kinds and requeue unstarted incompatible tasks.

        Running tasks keep running: their Activity already re-validated the kind at start.  A queued
        task that never started is unassigned so the pool can match it to another capable unit.
        """
        values = [kind.value for kind in kinds]
        if not values or len(values) != len(set(values)):
            raise CollectorError("INVALID_FORM", "TASK_KINDS_REQUIRED_AND_UNIQUE")
        supported = {kind.value for kind in TaskKind}
        if not set(values) <= supported:
            raise CollectorError("INVALID_FORM", "UNKNOWN_TASK_KIND")
        if not actor.strip() or not reason.strip():
            raise CollectorError("INVALID_FORM", "ACTOR_AND_REASON_REQUIRED")
        with self.connect() as conn:
            row = conn.execute(
                "SELECT unit_id FROM execution_units WHERE unit_id=%s FOR UPDATE", (unit,)
            ).fetchone()
            if not row:
                raise CollectorError("RESOURCE_UNAVAILABLE", "unit not registered")
            conn.execute(
                "UPDATE execution_units SET allowed_task_kinds=%s WHERE unit_id=%s",
                (values, unit),
            )
            requeued = conn.execute(
                """UPDATE root_tasks r
                SET unit_id=NULL,
                    payload=jsonb_set(
                      r.payload,'{execution_unit_id}',to_jsonb(%s::text),true
                    ),
                    updated_at=now()
                WHERE r.unit_id=%s AND r.state='QUEUED'
                  AND NOT (r.task_kind = ANY(%s))
                  AND NOT EXISTS (
                    SELECT 1 FROM task_dispatches d
                    WHERE d.root_task_id=r.root_task_id
                      AND d.workflow_started_at IS NOT NULL
                  )
                RETURNING r.root_task_id""",
                ("", unit, values),
            ).fetchall()
            for item in requeued:
                conn.execute(
                    """UPDATE task_dispatches SET sent=false
                    WHERE root_task_id=%s AND workflow_started_at IS NULL""",
                    (item["root_task_id"],),
                )
            conn.execute(
                "INSERT INTO audit_logs(actor,action) VALUES(%s,%s)",
                (
                    actor.strip(),
                    "set_unit_task_kinds:" + unit + ":" + ",".join(values) + ":" + reason.strip(),
                ),
            )
            return len(requeued)

    def claim_unassigned_update(self, unit: str) -> str | None:
        """Claim one unassigned pool task for this unit; returns the root id or None.

        Manual/scheduled updates are created unassigned.  Normal collection keeps its existing
        promotion-time assignment, so it only appears here when an operator removed its capability
        and it was released back to the pool; matching it again is the intended recovery.
        """
        with self.connect() as conn:
            row = conn.execute(
                """WITH candidate AS (
                  SELECT r.root_task_id
                  FROM root_tasks r
                  JOIN execution_units u ON u.unit_id=%s
                  JOIN execution_unit_platform_bindings b
                    ON b.unit_id=u.unit_id AND b.platform=r.platform AND b.enabled=true
                  WHERE r.unit_id IS NULL
                    AND r.state='QUEUED'
                    AND r.task_kind = ANY(u.allowed_task_kinds)
                    AND u.state <> 'QUARANTINED'
                    AND EXISTS (
                      SELECT 1 FROM task_dispatches d
                      WHERE d.root_task_id=r.root_task_id
                        AND d.segment=(r.payload->>'segment')::int
                        AND d.sent=false
                    )
                  ORDER BY CASE r.task_kind
                    WHEN 'collection' THEN 0
                    WHEN 'manual_update' THEN 1
                    WHEN 'scheduled_update' THEN 2
                    ELSE 3 END,
                    r.created_at, r.root_task_id
                  FOR UPDATE OF r SKIP LOCKED
                  LIMIT 1
                )
                UPDATE root_tasks r
                SET unit_id=%s,
                    payload=jsonb_set(
                      r.payload,'{execution_unit_id}',to_jsonb(%s::text),true
                    ),
                    updated_at=now()
                FROM candidate c
                WHERE r.root_task_id=c.root_task_id
                RETURNING r.root_task_id""",
                (unit, unit, unit),
            ).fetchone()
            return str(row["root_task_id"]) if row else None

    def has_runnable_higher_priority_task(
        self,
        unit: str,
        current_root: str,
        current_kind: TaskKind,
    ) -> bool:
        """Whether a collection/manual task should get the browser before this update task."""
        priority = {
            TaskKind.COLLECTION: 0,
            TaskKind.MANUAL_UPDATE: 1,
            TaskKind.SCHEDULED_UPDATE: 2,
        }
        higher = [kind.value for kind, value in priority.items() if value < priority[current_kind]]
        if not higher:
            return False
        runnable = ["QUEUED", "SEARCHING", "COLLECTING", "PERSISTING", "RETRY_WAIT"]
        with self.connect() as conn:
            row = conn.execute(
                """SELECT 1 FROM root_tasks r
                JOIN execution_unit_platform_bindings b
                  ON b.unit_id=%s AND b.platform=r.platform AND b.enabled=true
                WHERE r.root_task_id<>%s
                  AND r.task_kind = ANY(%s)
                  AND (r.unit_id=%s OR r.unit_id IS NULL)
                  AND r.state = ANY(%s)
                LIMIT 1""",
                (unit, current_root, higher, unit, runnable),
            ).fetchone()
            return row is not None

    def acquire(
        self,
        unit: str,
        owner: str,
        *,
        maintenance: bool = False,
        root_task_id: str | None = None,
        maintenance_ttl: timedelta = timedelta(minutes=15),
        idle_ttl: timedelta = timedelta(minutes=5),
    ) -> tuple[int, int]:
        error = False
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM execution_units WHERE unit_id=%s FOR UPDATE", (unit,)
            ).fetchone()
            if not row:
                raise CollectorError("RESOURCE_UNAVAILABLE", "unit not registered")
            if row["owner"]:
                if row["lease_until"] > utcnow():
                    raise CollectorError("RESOURCE_UNAVAILABLE", "unit occupied")
                # Expiry is never permission to steal a browser/profile.
                conn.execute(
                    "UPDATE execution_units SET state='QUARANTINED', "
                    "failure_reason='EXPIRED_OWNER' WHERE unit_id=%s",
                    (unit,),
                )
                conn.execute(
                    """UPDATE browser_takeover_sessions SET state='EXPIRED',
                    failure_reason='UNIT_QUARANTINED'
                    WHERE unit_id=%s AND state IN ('REQUESTED','ACTIVE','VERIFYING')""",
                    (unit,),
                )
                conn.execute(
                    """UPDATE verification_events SET state='EXPIRED',reason='UNIT_QUARANTINED'
                    WHERE unit_id=%s AND state IN ('OPEN','ACKNOWLEDGED')""",
                    (unit,),
                )
                error = True
            elif row["state"] == "QUARANTINED" or not row["browser_stopped"]:
                error = True
            elif row["state"] not in {"READY", "SESSION_UNVERIFIED"} and not maintenance:
                code = (
                    "ACCOUNT_MISMATCH"
                    if row["state"] == "ACCOUNT_MISMATCH"
                    else "ACCOUNT_LOGIN_REQUIRED"
                )
                raise CollectorError(code, "unit needs verification")
            else:
                result = conn.execute(
                    """UPDATE execution_units SET generation=generation+1,
                    owner=%s, lease_until=%s, browser_stopped=false, state='LEASED', mode=%s,
                    current_root_task_id=%s, maintenance_deadline=%s, idle_deadline=%s,
                    verified_account_id=NULL
                    WHERE unit_id=%s RETURNING generation,session_version""",
                    (
                        owner,
                        utcnow() + timedelta(seconds=120),
                        "maintenance" if maintenance else "collect",
                        root_task_id,
                        utcnow() + maintenance_ttl if maintenance else None,
                        utcnow() + idle_ttl,
                        unit,
                    ),
                ).fetchone()
                assert result
                return result["generation"], result["session_version"]
        if error:
            raise CollectorError("RESOURCE_UNAVAILABLE", "old browser requires isolation")
        raise AssertionError("unreachable")

    def heartbeat(self, unit: str, owner: str, generation: int) -> None:
        with self.connect() as conn:
            row = conn.execute(
                """UPDATE execution_units SET lease_until=%s,last_heartbeat_at=now()
              WHERE unit_id=%s AND owner=%s AND generation=%s AND lease_until>now()
              AND state='LEASED' RETURNING unit_id""",
                (utcnow() + timedelta(seconds=120), unit, owner, generation),
            ).fetchone()
            if not row:
                raise CollectorError("LEASE_LOST")

    def register_browser_instance(
        self, unit: str, owner: str, generation: int, browser_instance_id: str
    ) -> None:
        """Publish only a random instance fence, never a browser control endpoint.

        Product APIs use this value to reject stale takeover requests after a host restart.  The
        actual BrowserContext continues to be owned by BrowserHost in the Worker process.
        """
        with self.connect() as conn:
            row = conn.execute(
                """UPDATE execution_units SET browser_instance_id=%s,browser_started_at=now(),
                last_heartbeat_at=now() WHERE unit_id=%s AND owner=%s AND generation=%s
                AND state='LEASED' AND browser_stopped=false RETURNING unit_id""",
                (browser_instance_id, unit, owner, generation),
            ).fetchone()
            if not row:
                raise CollectorError("LEASE_LOST", "BROWSER_INSTANCE_FENCE_REJECTED")

    def create_verification_event(
        self,
        *,
        unit: str,
        root_task_id: str,
        generation: int,
        browser_instance_id: str,
        timeout_seconds: float,
        reason: str = "PLATFORM_SECURITY_CHALLENGE",
    ) -> dict[str, Any]:
        """Create one open notification per original browser instance.

        Repeated detections before a successful handoff update the existing event instead of
        generating alert noise or consuming the normal recovery budget.
        """
        deadline = utcnow() + timedelta(seconds=timeout_seconds)
        with self.connect() as conn:
            existing = conn.execute(
                """SELECT * FROM verification_events WHERE unit_id=%s AND root_task_id=%s
                AND browser_instance_id=%s AND state IN ('OPEN','ACKNOWLEDGED') FOR UPDATE""",
                (unit, root_task_id, browser_instance_id),
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE verification_events SET last_detected_at=now(),reason=%s
                    WHERE event_id=%s""",
                    (reason, existing["event_id"]),
                )
                existing["reason"] = reason
                return existing
            row = conn.execute(
                """INSERT INTO verification_events(event_id,unit_id,root_task_id,
                lease_generation,browser_instance_id,state,reason,deadline_at)
                VALUES(%s,%s,%s,%s,%s,'OPEN',%s,%s) RETURNING *""",
                (uid(), unit, root_task_id, generation, browser_instance_id, reason, deadline),
            ).fetchone()
            assert row
            conn.execute(
                "INSERT INTO audit_logs(root_task_id,actor,action) VALUES(%s,%s,%s)",
                (root_task_id, "browser-host", "verification_event.open:" + unit),
            )
            return row

    def list_verification_events(self, *, open_only: bool = True) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT e.*,u.state AS unit_state,u.mode,u.browser_stopped,u.last_heartbeat_at,
                r.state AS task_state FROM verification_events e
                JOIN execution_units u USING(unit_id) JOIN root_tasks r USING(root_task_id) """
                + ("WHERE e.state IN ('OPEN','ACKNOWLEDGED') " if open_only else "")
                + "ORDER BY e.detected_at DESC"
            ).fetchall()
            return [dict(row) for row in rows]

    def verification_event(self, event_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM verification_events WHERE event_id=%s", (event_id,)
            ).fetchone()
            if not row:
                raise CollectorError("INVALID_FORM", "VERIFICATION_EVENT_NOT_FOUND")
            return dict(row)

    def request_browser_takeover(self, unit: str, actor_user_id: str) -> dict[str, Any]:
        """Create a fenced request; the owning Worker alone can activate it."""
        with self.connect() as conn:
            unit_row = conn.execute(
                "SELECT * FROM execution_units WHERE unit_id=%s FOR UPDATE", (unit,)
            ).fetchone()
            if not unit_row:
                raise CollectorError("RESOURCE_UNAVAILABLE", "EXECUTION_UNIT_NOT_FOUND")
            if (
                unit_row["state"] != "LEASED"
                or unit_row["mode"] != "maintenance"
                or unit_row["browser_stopped"]
                or not unit_row["browser_instance_id"]
            ):
                raise CollectorError("RESOURCE_UNAVAILABLE", "ORIGINAL_BROWSER_UNAVAILABLE")
            event = conn.execute(
                """SELECT * FROM verification_events WHERE unit_id=%s
                AND browser_instance_id=%s AND state IN ('OPEN','ACKNOWLEDGED')
                AND deadline_at>now() ORDER BY detected_at DESC LIMIT 1 FOR UPDATE""",
                (unit, unit_row["browser_instance_id"]),
            ).fetchone()
            if not event:
                raise CollectorError("INVALID_FORM", "NO_ACTIVE_VERIFICATION_EVENT")
            # A disconnected operator must not prevent a new operator from taking over for
            # the remainder of the verification window.  This is deliberately done under
            # the unit row lock before checking the partial unique index below.
            conn.execute(
                """UPDATE browser_takeover_sessions SET state='EXPIRED',
                failure_reason=COALESCE(failure_reason, 'TAKEOVER_EXPIRED')
                WHERE unit_id=%s AND state IN ('REQUESTED','ACTIVE','VERIFYING')
                AND expires_at<=now()""",
                (unit,),
            )
            current = conn.execute(
                """SELECT * FROM browser_takeover_sessions WHERE unit_id=%s
                AND state IN ('REQUESTED','ACTIVE','VERIFYING') FOR UPDATE""",
                (unit,),
            ).fetchone()
            if current:
                if str(current["actor_user_id"]) == actor_user_id:
                    return dict(current)
                raise CollectorError("RESOURCE_UNAVAILABLE", "BROWSER_ALREADY_TAKEN_OVER")
            row = conn.execute(
                """INSERT INTO browser_takeover_sessions(takeover_id,event_id,unit_id,root_task_id,
                lease_generation,browser_instance_id,actor_user_id,state,expires_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,'REQUESTED',%s) RETURNING *""",
                (
                    uid(),
                    event["event_id"],
                    unit,
                    event["root_task_id"],
                    event["lease_generation"],
                    event["browser_instance_id"],
                    actor_user_id,
                    event["deadline_at"],
                ),
            ).fetchone()
            assert row
            conn.execute(
                "UPDATE verification_events SET state='ACKNOWLEDGED' WHERE event_id=%s",
                (event["event_id"],),
            )
            conn.execute(
                """INSERT INTO audit_logs(root_task_id,actor,actor_user_id,action)
                VALUES(%s,%s,%s,%s)""",
                (
                    event["root_task_id"],
                    "product:" + actor_user_id,
                    actor_user_id,
                    "browser_takeover.request:" + unit,
                ),
            )
            return dict(row)

    def activate_browser_takeover(
        self, *, unit: str, owner: str, generation: int, browser_instance_id: str
    ) -> dict[str, Any] | None:
        """Worker-side compare-and-set. This is the only path to ACTIVE."""
        with self.connect() as conn:
            row = conn.execute(
                """SELECT * FROM browser_takeover_sessions WHERE unit_id=%s
                AND lease_generation=%s AND browser_instance_id=%s AND state='REQUESTED'
                AND expires_at>now() ORDER BY created_at LIMIT 1 FOR UPDATE""",
                (unit, generation, browser_instance_id),
            ).fetchone()
            if not row:
                return None
            owned = conn.execute(
                """SELECT unit_id FROM execution_units WHERE unit_id=%s AND owner=%s
                AND generation=%s AND browser_instance_id=%s AND state='LEASED'
                AND mode='maintenance' AND browser_stopped=false""",
                (unit, owner, generation, browser_instance_id),
            ).fetchone()
            if not owned:
                return None
            conn.execute(
                """UPDATE browser_takeover_sessions SET state='ACTIVE',activated_at=now(),
                last_human_action_at=now() WHERE takeover_id=%s""",
                (row["takeover_id"],),
            )
            row["state"] = "ACTIVE"
            return dict(row)

    def takeover(self, takeover_id: str, actor_user_id: str | None = None) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM browser_takeover_sessions WHERE takeover_id=%s", (takeover_id,)
            ).fetchone()
            if not row:
                raise CollectorError("INVALID_FORM", "TAKEOVER_NOT_FOUND")
            if actor_user_id and str(row["actor_user_id"]) != actor_user_id:
                raise CollectorError("INVALID_FORM", "TAKEOVER_ACCESS_DENIED")
            return dict(row)

    def active_takeover_for_viewer(self, takeover_id: str, actor_user_id: str) -> dict[str, Any]:
        """Return an operator's live takeover only while it still fences the original browser."""
        with self.connect() as conn:
            row = conn.execute(
                """SELECT t.* FROM browser_takeover_sessions t
                JOIN execution_units u ON u.unit_id=t.unit_id
                WHERE t.takeover_id=%s AND t.actor_user_id=%s AND t.state='ACTIVE'
                AND t.expires_at>now() AND u.state='LEASED' AND u.mode='maintenance'
                AND u.browser_stopped=false AND u.browser_instance_id=t.browser_instance_id""",
                (takeover_id, actor_user_id),
            ).fetchone()
            if not row:
                raise CollectorError("INVALID_FORM", "TAKEOVER_NOT_ACTIVE")
            return dict(row)

    def claim_takeover_viewer(
        self, takeover_id: str, actor_user_id: str, connection_id: str
    ) -> None:
        """Fence one VNC WebSocket so Playwright can wait for its confirmed disconnect."""
        with self.connect() as conn:
            row = conn.execute(
                """SELECT t.takeover_id FROM browser_takeover_sessions t
                JOIN execution_units u ON u.unit_id=t.unit_id
                WHERE t.takeover_id=%s AND t.actor_user_id=%s AND t.state='ACTIVE'
                AND t.expires_at>now() AND t.viewer_connection_id IS NULL
                AND u.state='LEASED' AND u.mode='maintenance' AND u.browser_stopped=false
                AND u.browser_instance_id=t.browser_instance_id FOR UPDATE OF t""",
                (takeover_id, actor_user_id),
            ).fetchone()
            if not row:
                raise CollectorError("INVALID_FORM", "TAKEOVER_VIEWER_ALREADY_CONNECTED")
            conn.execute(
                """UPDATE browser_takeover_sessions SET viewer_connection_id=%s,
                viewer_connected_at=now(),viewer_disconnected_at=NULL WHERE takeover_id=%s""",
                (connection_id, takeover_id),
            )

    def release_takeover_viewer(self, takeover_id: str, connection_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """UPDATE browser_takeover_sessions SET viewer_connection_id=NULL,
                viewer_disconnected_at=now() WHERE takeover_id=%s AND viewer_connection_id=%s""",
                (takeover_id, connection_id),
            )

    def report_takeover_reappearance(
        self, takeover_id: str, actor_user_id: str, reason: str
    ) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM browser_takeover_sessions WHERE takeover_id=%s FOR UPDATE",
                (takeover_id,),
            ).fetchone()
            if not row or str(row["actor_user_id"]) != actor_user_id:
                raise CollectorError("INVALID_FORM", "TAKEOVER_ACCESS_DENIED")
            if row["state"] != "ACTIVE":
                raise CollectorError("INVALID_FORM", "TAKEOVER_NOT_ACTIVE")
            conn.execute(
                """UPDATE verification_events SET state='OPEN',last_detected_at=now(),
                reappearance_count=reappearance_count+1,reason=%s WHERE event_id=%s""",
                (reason, row["event_id"]),
            )
            conn.execute(
                """UPDATE browser_takeover_sessions SET last_human_action_at=now()
                WHERE takeover_id=%s""",
                (takeover_id,),
            )
            row["last_human_action_at"] = utcnow()
            return dict(row)

    def complete_browser_takeover(self, takeover_id: str, actor_user_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM browser_takeover_sessions WHERE takeover_id=%s FOR UPDATE",
                (takeover_id,),
            ).fetchone()
            if not row or str(row["actor_user_id"]) != actor_user_id:
                raise CollectorError("INVALID_FORM", "TAKEOVER_ACCESS_DENIED")
            if row["state"] != "ACTIVE" or row["expires_at"] <= utcnow():
                raise CollectorError("INVALID_FORM", "TAKEOVER_NOT_ACTIVE")
            conn.execute(
                """UPDATE browser_takeover_sessions SET state='VERIFYING',
                last_human_action_at=now(),completed_at=now() WHERE takeover_id=%s""",
                (takeover_id,),
            )
            now = utcnow()
            row["state"] = "VERIFYING"
            row["last_human_action_at"] = now
            row["completed_at"] = now
            return dict(row)

    def finish_browser_takeover(
        self, takeover_id: str, *, resumed: bool, failure_reason: str | None = None
    ) -> None:
        state = "RESUMED" if resumed else "FAILED"
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM browser_takeover_sessions WHERE takeover_id=%s FOR UPDATE",
                (takeover_id,),
            ).fetchone()
            if not row:
                return
            conn.execute(
                """UPDATE browser_takeover_sessions SET state=%s,failure_reason=%s
                WHERE takeover_id=%s""",
                (state, failure_reason, takeover_id),
            )
            if resumed:
                conn.execute(
                    """UPDATE verification_events SET state='RESOLVED',resolved_at=now()
                    WHERE event_id=%s""",
                    (row["event_id"],),
                )
            else:
                conn.execute(
                    """UPDATE verification_events SET state='OPEN',last_detected_at=now(),
                    reason=%s,reappearance_count=reappearance_count+
                    CASE WHEN %s='SECURITY_CHALLENGE_STILL_PRESENT' THEN 1 ELSE 0 END
                    WHERE event_id=%s""",
                    (
                        failure_reason or "VERIFICATION_NOT_CONFIRMED",
                        failure_reason,
                        row["event_id"],
                    ),
                )

    def expire_verification_event(self, event_id: str, reason: str) -> None:
        """Close a notification when its bounded wait is no longer actionable.

        Expiry never attempts browser cleanup.  The Worker remains the sole owner that closes the
        original BrowserContext; this update merely prevents an expired event from appearing as
        a live operator notification.
        """
        with self.connect() as conn:
            conn.execute(
                """UPDATE browser_takeover_sessions SET state='EXPIRED',failure_reason=%s
                WHERE event_id=%s AND state IN ('REQUESTED','ACTIVE','VERIFYING')""",
                (reason, event_id),
            )
            conn.execute(
                """UPDATE verification_events SET state='EXPIRED',reason=%s
                WHERE event_id=%s AND state IN ('OPEN','ACKNOWLEDGED')""",
                (reason, event_id),
            )

    def release_browser_takeover(self, takeover_id: str, actor_user_id: str) -> None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM browser_takeover_sessions WHERE takeover_id=%s FOR UPDATE",
                (takeover_id,),
            ).fetchone()
            if not row or str(row["actor_user_id"]) != actor_user_id:
                raise CollectorError("INVALID_FORM", "TAKEOVER_ACCESS_DENIED")
            if row["state"] not in {"REQUESTED", "ACTIVE"}:
                raise CollectorError("INVALID_FORM", "TAKEOVER_NOT_RELEASABLE")
            conn.execute(
                """UPDATE browser_takeover_sessions SET state='RELEASED',completed_at=now()
                WHERE takeover_id=%s""",
                (takeover_id,),
            )
            conn.execute(
                "UPDATE verification_events SET state='OPEN' WHERE event_id=%s", (row["event_id"],)
            )

    def release(
        self,
        unit: str,
        owner: str,
        generation: int,
        *,
        stopped: bool,
        disposition: ReleaseDisposition,
        reason: str | None = None,
    ) -> None:
        if not stopped:
            disposition = ReleaseDisposition.BROWSER_UNCONFIRMED
        state = {
            ReleaseDisposition.VERIFIED_READY: "READY",
            ReleaseDisposition.LOGIN_REQUIRED: "NEEDS_LOGIN",
            ReleaseDisposition.ACCOUNT_MISMATCH: "ACCOUNT_MISMATCH",
            ReleaseDisposition.SECURITY_CHALLENGE: "NEEDS_VERIFICATION",
            ReleaseDisposition.SESSION_UNVERIFIED: "SESSION_UNVERIFIED",
            ReleaseDisposition.BROWSER_UNCONFIRMED: "QUARANTINED",
        }[disposition]
        session_status = {
            ReleaseDisposition.VERIFIED_READY: "VALID",
            ReleaseDisposition.LOGIN_REQUIRED: "LOGIN_REQUIRED",
            ReleaseDisposition.ACCOUNT_MISMATCH: "ACCOUNT_MISMATCH",
            ReleaseDisposition.SECURITY_CHALLENGE: "SECURITY_CHALLENGE",
            ReleaseDisposition.SESSION_UNVERIFIED: "INDETERMINATE",
            ReleaseDisposition.BROWSER_UNCONFIRMED: "INDETERMINATE",
        }[disposition]
        with self.connect() as conn:
            conn.execute(
                """UPDATE execution_units SET owner=NULL, lease_until=NULL,
              browser_stopped=%s, mode=NULL, state=%s, current_root_task_id=NULL,
              maintenance_deadline=NULL, idle_deadline=NULL,last_session_status=%s,
              last_session_checked_at=now(),last_session_reason=%s,failure_reason=%s,
              browser_instance_id=NULL,browser_started_at=NULL
              WHERE unit_id=%s AND owner=%s
              AND generation=%s""",
                (
                    stopped,
                    state,
                    session_status,
                    reason,
                    reason,
                    unit,
                    owner,
                    generation,
                ),
            )
            if state == "QUARANTINED":
                conn.execute(
                    """UPDATE browser_takeover_sessions SET state='EXPIRED',
                    failure_reason='UNIT_QUARANTINED'
                    WHERE unit_id=%s AND state IN ('REQUESTED','ACTIVE','VERIFYING')""",
                    (unit,),
                )
                conn.execute(
                    """UPDATE verification_events SET state='EXPIRED',reason='UNIT_QUARANTINED'
                    WHERE unit_id=%s AND state IN ('OPEN','ACKNOWLEDGED')""",
                    (unit,),
                )

    def unit_has_open_verification_event(self, unit: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """SELECT 1 FROM verification_events
                WHERE unit_id=%s AND state IN ('OPEN','ACKNOWLEDGED') LIMIT 1""",
                (unit,),
            ).fetchone()
            return row is not None

    def reconcile_stale_verification(self, unit: str, actor: str = "worker") -> bool:
        """Clear an expired unit verification state that no open event still justifies.

        The verification event is the operator-facing authority.  A unit left in
        NEEDS_VERIFICATION after its event expired must not route the next task (especially a
        task for the other platform) into security maintenance; the fresh browser check will
        re-detect any real challenge.  ACCOUNT_MISMATCH and NEEDS_LOGIN are deliberately not
        cleared here because those require an actual account/login observation.
        """
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM execution_units WHERE unit_id=%s FOR UPDATE", (unit,)
            ).fetchone()
            if (
                not row
                or row["state"] != "NEEDS_VERIFICATION"
                or row["owner"]
                or not row["browser_stopped"]
            ):
                return False
            open_event = conn.execute(
                """SELECT 1 FROM verification_events
                WHERE unit_id=%s AND state IN ('OPEN','ACKNOWLEDGED') LIMIT 1""",
                (unit,),
            ).fetchone()
            if open_event:
                return False
            conn.execute(
                """UPDATE execution_units SET state='READY',mode=NULL,failure_reason=NULL,
                maintenance_deadline=NULL,last_session_status='INDETERMINATE',
                last_session_checked_at=now(),
                last_session_reason='STALE_VERIFICATION_EXPIRED'
                WHERE unit_id=%s AND state='NEEDS_VERIFICATION' AND owner IS NULL""",
                (unit,),
            )
            conn.execute(
                "INSERT INTO audit_logs(root_task_id,actor,action) VALUES(NULL,%s,%s)",
                (actor, "verification_event.stale_cleared:" + unit),
            )
            return True

    def promote_maintenance_to_collect(
        self,
        unit: str,
        owner: str,
        generation: int,
        expected_session_version: int,
        verified_account_id: str,
        actor: str,
        *,
        account_verified: bool,
        protected_page_verified: bool,
        line_verified: bool,
    ) -> int:
        """Atomically fence a verified, live maintenance context into collect mode.

        The caller is the BrowserHost that owns the process-local BrowserContext.  The three
        evidence flags are deliberately explicit so no URL/Cookie-only check can call this path.
        """
        if not verified_account_id or not all(
            (account_verified, protected_page_verified, line_verified)
        ):
            raise CollectorError("ACCOUNT_LOGIN_REQUIRED", "SESSION_VERIFICATION_INCOMPLETE")
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM execution_units WHERE unit_id=%s FOR UPDATE", (unit,)
            ).fetchone()
            if not row:
                raise CollectorError("RESOURCE_UNAVAILABLE", "unit not registered")
            if row["owner"] != owner or row["generation"] != generation:
                raise CollectorError("LEASE_LOST", "OWNER_OR_GENERATION_MISMATCH")
            if (
                row["state"] != "LEASED"
                or row["mode"] != "maintenance"
                or row["lease_until"] <= utcnow()
                or row["browser_stopped"]
            ):
                raise CollectorError("LEASE_LOST", "MAINTENANCE_LEASE_NOT_ACTIVE")
            if row["session_version"] != expected_session_version:
                raise CollectorError("LEASE_LOST", "SESSION_VERSION_CONFLICT")
            if row["maintenance_deadline"] and row["maintenance_deadline"] <= utcnow():
                raise CollectorError("ACCOUNT_LOGIN_REQUIRED", "MAINTENANCE_TIMEOUT")
            if row["expected_account_id"] and row["expected_account_id"] != verified_account_id:
                raise CollectorError("ACCOUNT_MISMATCH", "WRONG_ACCOUNT")
            promoted = conn.execute(
                """UPDATE execution_units SET mode='collect',session_version=session_version+1,
                verified_account_id=%s,failure_reason=NULL,maintenance_deadline=NULL,
                last_session_status='VALID',last_session_checked_at=now(),
                last_session_reason='PROTECTED_PAGE_AND_ACCOUNT_VERIFIED'
                WHERE unit_id=%s RETURNING session_version,current_root_task_id""",
                (verified_account_id, unit),
            ).fetchone()
            assert promoted
            root = promoted["current_root_task_id"]
            # The BrowserHost that performs this transaction already owns the running Activity
            # and continues collection in-process.  Re-queueing its workflow here would leave a
            # stale wake signal behind; if a later challenge timed out, that signal could launch
            # another Chrome without a new user maintenance request.
            conn.execute(
                "INSERT INTO audit_logs(root_task_id,actor,action) VALUES(%s,%s,%s)",
                (root, actor, "promote_maintenance_to_collect:" + unit),
            )
            # The current operator-facing verification notification is complete once the
            # account/protected page is verified; leaving it OPEN would show a stale warning.
            conn.execute(
                """UPDATE verification_events SET state='RESOLVED',resolved_at=now()
                WHERE unit_id=%s AND root_task_id=%s AND state IN ('OPEN','ACKNOWLEDGED')""",
                (unit, root),
            )
            return int(promoted["session_version"])

    def transition_collect_to_maintenance(
        self,
        unit: str,
        owner: str,
        generation: int,
        expected_session_version: int,
        reason: str,
        actor: str,
        *,
        maintenance_ttl: timedelta = timedelta(minutes=15),
    ) -> None:
        if reason not in {
            "ACCOUNT_LOGIN_REQUIRED",
            "ACCOUNT_MISMATCH",
            "PLATFORM_SECURITY_CHALLENGE",
            "ACCOUNT_SELECTION_REQUIRED",
        }:
            raise CollectorError("INVALID_FORM", "NON_AUTH_FAILURE_CANNOT_ENTER_MAINTENANCE")
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM execution_units WHERE unit_id=%s FOR UPDATE", (unit,)
            ).fetchone()
            if (
                not row
                or row["owner"] != owner
                or row["generation"] != generation
                or row["state"] != "LEASED"
                or row["mode"] != "collect"
                or row["lease_until"] <= utcnow()
                or row["browser_stopped"]
                or row["session_version"] != expected_session_version
            ):
                raise CollectorError("LEASE_LOST")
            conn.execute(
                """UPDATE execution_units SET mode='maintenance',failure_reason=%s,
                maintenance_deadline=%s WHERE unit_id=%s""",
                (reason, utcnow() + maintenance_ttl, unit),
            )
            conn.execute(
                "INSERT INTO audit_logs(root_task_id,actor,action) VALUES(%s,%s,%s)",
                (
                    row["current_root_task_id"],
                    actor,
                    "transition_collect_to_maintenance:" + unit + ":" + reason,
                ),
            )

    def queue_login_resumes(self, unit: str) -> int:
        """Durable wake intentions, only after verified maintenance released the browser.

        Dispatch reuses the existing workflow ID and its idempotent wake signal.
        A new owner/session state must not be overwritten by this notification.
        """
        with self.connect() as conn:
            row = conn.execute(
                "SELECT state,browser_stopped FROM execution_units WHERE unit_id=%s FOR UPDATE",
                (unit,),
            ).fetchone()
            if not row or row["state"] != "READY" or not row["browser_stopped"]:
                return 0
            result = conn.execute(
                "UPDATE task_dispatches d SET sent=false FROM root_tasks r "
                "WHERE d.root_task_id=r.root_task_id AND d.segment=(r.payload->>'segment')::int "
                "AND r.unit_id=%s AND r.state IN "
                "('WAITING_FOR_LOGIN','WAITING_FOR_ACCOUNT','WAITING_FOR_VERIFICATION') "
                "AND d.sent=true",
                (unit,),
            )
            return int(result.rowcount)

    def request_login_maintenance(self, unit: str, actor: str) -> int:
        """Wake existing waiting workflows; the Worker-owned BrowserHost opens Chrome."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM execution_units WHERE unit_id=%s FOR UPDATE", (unit,)
            ).fetchone()
            if not row:
                raise CollectorError("RESOURCE_UNAVAILABLE", "unit not registered")
            waiting = conn.execute(
                "SELECT count(*) AS n FROM root_tasks WHERE unit_id=%s "
                "AND state IN "
                "('WAITING_FOR_LOGIN','WAITING_FOR_ACCOUNT','WAITING_FOR_VERIFICATION')",
                (unit,),
            ).fetchone()
            assert waiting
            count = int(waiting["n"])
            if row["owner"] and row["mode"] == "maintenance" and not row["browser_stopped"]:
                # The bounded host is already showing the maintenance context.  Repeated user
                # confirmation is a successful no-op and must never create another owner/browser.
                conn.execute(
                    "INSERT INTO audit_logs(actor,action) VALUES(%s,%s)",
                    (actor, "request_login_maintenance_existing:" + unit + ":" + str(count)),
                )
                return count
            if row["owner"] or not row["browser_stopped"]:
                raise CollectorError("RESOURCE_UNAVAILABLE", "unit already has a browser host")
            if row["state"] == "QUARANTINED":
                raise CollectorError("RESOURCE_UNAVAILABLE", "old browser requires isolation")
            conn.execute(
                """UPDATE task_dispatches d SET sent=false FROM root_tasks r
                WHERE d.root_task_id=r.root_task_id
                AND d.segment=(r.payload->>'segment')::int AND r.unit_id=%s
                AND r.state IN
                ('WAITING_FOR_LOGIN','WAITING_FOR_ACCOUNT','WAITING_FOR_VERIFICATION')""",
                (unit,),
            )
            conn.execute(
                "INSERT INTO audit_logs(actor,action) VALUES(%s,%s)",
                (actor, "request_login_maintenance:" + unit + ":" + str(count)),
            )
            return count

    def create(
        self,
        plan: FilterPlan,
        unit: str,
        key: str,
        actor: str,
        *,
        adapter_version: str,
        contract_version: str,
        modules: list[str],
        module_checkpoint_versions: dict[str, int] | None = None,
        featured_types: list[str] | None = None,
        featured_checkpoint_versions: dict[str, int] | None = None,
        profile_requirement: ProfileRequirement | None = None,
    ) -> str:
        checkpoint_versions = dict(module_checkpoint_versions or {})
        featured_types = list(featured_types or [])
        featured_versions = dict(featured_checkpoint_versions or {})
        digest = hashlib.sha256(
            (
                plan.model_dump_json()
                + unit
                + adapter_version
                + contract_version
                + json.dumps(checkpoint_versions, sort_keys=True)
                + json.dumps(featured_versions, sort_keys=True)
                + json.dumps(featured_types)
                + (
                    json.dumps(profile_requirement.model_dump(mode="json"), sort_keys=True)
                    if profile_requirement is not None
                    else ""
                )
            ).encode()
        ).hexdigest()
        with self.connect() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (actor + ":start:" + key,)
            )
            old = conn.execute(
                """SELECT * FROM idempotency_records
                WHERE actor=%s AND operation='start' AND key=%s""",
                (actor, key),
            ).fetchone()
            if old:
                if old["digest"] != digest:
                    raise CollectorError("INVALID_FORM", "IDEMPOTENCY_CONFLICT")
                return str(old["root_task_id"])
            task = TaskRecord(
                root_task_id=uid(),
                task_id=uid(),
                attempt_id=uid(),
                plan=plan,
                execution_unit_id=unit,
                profile_requirement=profile_requirement,
                checkpoint=Checkpoint(
                    conditions_digest=plan.digest(),
                    adapter_version=adapter_version,
                    contract_version=contract_version,
                    profile_module_keys=modules,
                    profile_checkpoint_versions=checkpoint_versions,
                    featured_collection_types=featured_types,
                    featured_checkpoint_versions=featured_versions,
                ),
            )
            conn.execute(
                """INSERT INTO root_tasks(root_task_id,state,version,unit_id,payload,platform)
                VALUES(%s,%s,0,%s,%s,%s)""",
                (
                    task.root_task_id,
                    task.state,
                    unit,
                    Jsonb(task.model_dump(mode="json", exclude={"checkpoint"})),
                    task.platform.value,
                ),
            )
            conn.execute(
                "INSERT INTO filter_plans VALUES(%s,%s,%s)",
                (task.root_task_id, Jsonb(plan.model_dump(mode="json")), task.source),
            )
            conn.execute(
                "INSERT INTO tasks VALUES(%s,%s,NULL,%s)", (task.task_id, task.root_task_id, "P2-1")
            )
            for kind in ("search", "profile"):
                conn.execute(
                    "INSERT INTO tasks VALUES(%s,%s,%s,%s)",
                    (uid(), task.root_task_id, task.task_id, kind),
                )
            conn.execute(
                "INSERT INTO task_attempts(attempt_id,root_task_id,segment) VALUES(%s,%s,0)",
                (task.attempt_id, task.root_task_id),
            )
            conn.execute(
                "INSERT INTO task_checkpoints VALUES(%s,0,%s)",
                (task.task_id, Jsonb(task.checkpoint.model_dump(mode="json"))),
            )
            conn.execute(
                "INSERT INTO task_dispatches VALUES(%s,0,%s,false)",
                (task.root_task_id, f"collect/{task.root_task_id}"),
            )
            conn.execute(
                "INSERT INTO idempotency_records VALUES(%s,'start',%s,%s,%s)",
                (actor, key, digest, task.root_task_id),
            )
            conn.execute(
                "INSERT INTO audit_logs(root_task_id,actor,action) VALUES(%s,%s,%s)",
                (task.root_task_id, actor, "internal_acceptance.start"),
            )
            return task.root_task_id

    def _load(
        self, conn: psycopg.Connection[dict[str, Any]], root: str, *, lock: bool = False
    ) -> TaskRecord:
        row = conn.execute(
            "SELECT payload FROM root_tasks WHERE root_task_id=%s"
            + (" FOR UPDATE" if lock else ""),
            (root,),
        ).fetchone()
        if not row:
            raise CollectorError("INVALID_FORM", "TASK_NOT_FOUND")
        data = row["payload"]
        cp = conn.execute(
            "SELECT payload FROM task_checkpoints WHERE task_id=%s", (data["task_id"],)
        ).fetchone()
        assert cp
        return TaskRecord.model_validate({**data, "checkpoint": cp["payload"]})

    def get(self, root: str) -> TaskRecord:
        with self.connect() as conn:
            return self._load(conn, root)

    def _save(self, conn: psycopg.Connection[dict[str, Any]], task: TaskRecord) -> None:
        task.version += 1
        task.checkpoint.revision += 1
        # `updated_at` stays the last-write audit value. `completed_at` is written once, on the
        # transition into a terminal state, and never overwritten afterwards (a retried task that
        # reaches a terminal state again keeps its first completion moment).
        conn.execute(
            "UPDATE root_tasks SET state=%s,version=%s,payload=%s,unit_id=%s,updated_at=now()"
            + TERMINAL_COMPLETED_AT_CLAUSE
            + " WHERE root_task_id=%s",
            (
                task.state,
                task.version,
                Jsonb(task.model_dump(mode="json", exclude={"checkpoint"})),
                task.execution_unit_id,
                task.state in TERMINAL_TASK_STATES,
                task.root_task_id,
            ),
        )
        conn.execute(
            "UPDATE task_checkpoints SET revision=%s,payload=%s WHERE task_id=%s",
            (
                task.checkpoint.revision,
                Jsonb(task.checkpoint.model_dump(mode="json")),
                task.task_id,
            ),
        )

    @contextmanager
    def edit(
        self, root: str, ctx: ExecutionContext | None = None
    ) -> Iterator[tuple[TaskRecord, psycopg.Connection[dict[str, Any]]]]:
        with self.connect() as conn:
            task = self._load(conn, root, lock=True)
            if ctx:
                lease = conn.execute(
                    "SELECT * FROM execution_units WHERE unit_id=%s FOR UPDATE",
                    (ctx.execution_unit_id,),
                ).fetchone()
                if (
                    not lease
                    or lease["generation"] != ctx.lease_generation
                    or lease["owner"] != ctx.attempt_id
                    or lease["state"] != "LEASED"
                    or lease["lease_until"] <= utcnow()
                    or lease["mode"] != "collect"
                    or lease["session_version"] != ctx.session_version
                ):
                    raise CollectorError("LEASE_LOST")
                if (
                    task.attempt_id != ctx.attempt_id
                    or task.state not in RUNNING
                    or task.execution_unit_id != ctx.execution_unit_id
                    or task.root_task_id != ctx.root_task_id
                    or task.task_id != ctx.task_id
                ):
                    raise CollectorError("TASK_CANCELLED", "STALE_ATTEMPT_OR_STATE")
                if (
                    task.plan is not None and task.plan.capability_version != ctx.capability_version
                ) or (
                    task.checkpoint.adapter_version != ctx.adapter_version
                    or task.checkpoint.contract_version != ctx.contract_version
                ):
                    raise CollectorError("PLATFORM_PAGE_CHANGED", "VERSION_MISMATCH")
            yield task, conn
            self._save(conn, task)
        # The task write path is the single terminal boundary for every caller (Activity,
        # API command, CLI).  Reconcile the update schedule after the task transaction commits,
        # so manual updates do not depend on a later UI read or scheduler tick.  The call is
        # idempotent and only touches rows whose in-flight root is this task.
        if task.task_kind != TaskKind.COLLECTION and task.state in TERMINAL_TASK_STATES:
            try:
                from .creator_update import reconcile_update_task

                reconcile_update_task(self, root)
            except Exception as exc:  # noqa: BLE001 - a committed task must not be re-failed
                logger.warning(
                    "update schedule reconcile failed root=%s: %s", root, type(exc).__name__
                )

    def command(self, root: str, action: str, version: int, actor: str) -> None:
        with self.edit(root) as (task, conn):
            if task.version != version:
                raise CollectorError("INVALID_FORM", "STATE_VERSION_CONFLICT")
            if action == "cancel":
                if task.state in {
                    TaskStatus.CANCELLED,
                    TaskStatus.COMPLETED,
                    TaskStatus.PARTIAL_COMPLETED,
                    TaskStatus.FAILED_VALIDATION,
                }:
                    raise CollectorError("INVALID_FORM", "ACTION_NOT_ALLOWED")
                task.state = TaskStatus.CANCELLING
            elif action in {"continue", "retry"}:
                allowed = (
                    {TaskStatus.PAUSED_BUDGET}
                    if action == "continue"
                    else {TaskStatus.FAILED, TaskStatus.PARTIAL_COMPLETED}
                )
                if task.state not in allowed:
                    raise CollectorError("INVALID_FORM", "ACTION_NOT_ALLOWED")
                if action == "retry" and task.state == TaskStatus.PARTIAL_COMPLETED:
                    if challenge_blocks_retry(task):
                        raise CollectorError("INVALID_FORM", "ACTION_NOT_ALLOWED")
                    if not any(self.retryable(c) for c in task.checkpoint.candidates):
                        raise CollectorError("INVALID_FORM", "NO_RETRYABLE_FAILURE")
                scope = decide_retry_scope(task)
                task.segment += 1
                task.attempt_id = uid()
                task.state = TaskStatus.QUEUED
                task.failure_reason = None
                task.checkpoint.active_seconds = 0
                task.checkpoint.scanned_ids = []
                # A task created before dedicated execution units may still point at a unit that
                # no longer carries its platform binding. Re-resolve on every retry/continue so
                # the new segment is dispatched to the unit that can actually execute it.
                task.execution_unit_id = (
                    self.select_collection_unit(task.platform.value) or task.execution_unit_id
                )
                requeue_for_retry(task, scope)
                conn.execute(
                    "INSERT INTO task_attempts(attempt_id,root_task_id,segment) VALUES(%s,%s,%s)",
                    (task.attempt_id, root, task.segment),
                )
                conn.execute(
                    "INSERT INTO task_dispatches VALUES(%s,%s,%s,false)",
                    (root, task.segment, f"collect/{root}"),
                )
            else:
                raise CollectorError("INVALID_FORM", "UNKNOWN_ACTION")
            audit_action = action
            if action in {"continue", "retry"}:
                audit_action = f"{action}:{scope.value}"
            conn.execute(
                "INSERT INTO audit_logs(root_task_id,actor,action) VALUES(%s,%s,%s)",
                (root, actor, audit_action),
            )

    def persist_creators(
        self,
        conn: psycopg.Connection[dict[str, Any]],
        task: TaskRecord,
        *,
        publish: bool,
        only_creator: str | None = None,
    ) -> None:
        # Called inside the same locked transaction as module/checkpoint/count changes.
        # A terminal closeout publishes every valid creator, but one retry segment usually changes
        # only a few. Compare with each creator's latest snapshot payload so an unchanged creator
        # keeps its published version: append-only history stays intact and no duplicate snapshot
        # row, `latest_snapshot_id` move or library sync happens.
        published: dict[str, Any] = {}
        if publish:
            latest_ids = [
                candidate.snapshot_ids[-1]
                for candidate in task.checkpoint.candidates
                if candidate.valid
                and candidate.snapshot_ids
                and (only_creator is None or candidate.ref.platform_creator_id == only_creator)
            ]
            if latest_ids:
                rows = conn.execute(
                    "SELECT snapshot_id,payload FROM creator_snapshots "
                    "WHERE snapshot_id=ANY(%s::uuid[])",
                    (latest_ids,),
                ).fetchall()
                published = {str(row["snapshot_id"]): row["payload"] for row in rows}
        for candidate in task.checkpoint.candidates:
            if not candidate.valid or (
                only_creator and candidate.ref.platform_creator_id != only_creator
            ):
                continue
            ref = candidate.ref
            # Defence in depth for the platform invariant: an identity from another platform must
            # never be written into platform_creators/projection/snapshot for this task.
            if ref.platform != task.platform:
                raise CollectorError("PLATFORM_PAGE_CHANGED", "CREATOR_PLATFORM_MISMATCH")
            conn.execute(
                """INSERT INTO platform_creators(creator_id,platform,platform_creator_id)
                VALUES(%s,%s,%s) ON CONFLICT(platform,platform_creator_id) DO NOTHING""",
                (ref.creator_id or uid(), ref.platform, ref.platform_creator_id),
            )
            row = conn.execute(
                """SELECT * FROM platform_creators
                WHERE platform=%s AND platform_creator_id=%s FOR UPDATE""",
                (ref.platform, ref.platform_creator_id),
            ).fetchone()
            assert row
            ref.creator_id = str(row["creator_id"])
            conn.execute(
                """INSERT INTO task_creators(root_task_id,creator_id,first_position,valid)
                VALUES(%s,%s,%s,true) ON CONFLICT(root_task_id,creator_id)
                DO UPDATE SET valid=true""",
                (task.root_task_id, ref.creator_id, ref.first_position),
            )
            if not publish:
                continue
            fields = row["projection"]
            for module in candidate.modules.values():
                for field in module.fields:
                    key = f"{module.module_key}.{field.field_key}"
                    old = fields.get(key)
                    if field.status == FieldStatus.COLLECTED and (
                        not old or field.observed_at > datetime.fromisoformat(old["observed_at"])
                    ):
                        fields[key] = field.model_dump(mode="json")
            snapshot: dict[str, Any] = {
                "schema_version": "profile_snapshot.v1",
                "modules": {
                    k: {**m.model_dump(mode="json"), "status": m.status, "complete": m.complete}
                    for k, m in candidate.modules.items()
                },
                "collections": {
                    k: {**o.model_dump(mode="json"), "complete": o.complete}
                    for k, o in candidate.collections.items()
                },
                "profile_complete": self.profile_complete(task, candidate.ref.platform_creator_id),
                "profile_coverage": self.profile_coverage(task, candidate.ref.platform_creator_id),
                "featured_complete": self.featured_complete(
                    task, candidate.ref.platform_creator_id
                ),
                "pipeline_complete": self.pipeline_complete(
                    task, candidate.ref.platform_creator_id
                ),
                "featured_status": task.featured_status,
                "failure_reason": candidate.failure_reason,
            }
            for key in task.checkpoint.profile_module_keys:
                if key not in candidate.modules:
                    snapshot["modules"][key] = {
                        "module_key": key,
                        "status": "NOT_ATTEMPTED",
                        "complete": False,
                        "observed_at": None,
                        "module_observation_id": None,
                        "failure_reason": candidate.failure_reason
                        or task.failure_reason
                        or "UPSTREAM_INTERRUPTED",
                        "fields": [
                            {
                                "field_key": f,
                                "status": "NOT_ATTEMPTED",
                                "value": None,
                                "failure_reason": "UPSTREAM_INTERRUPTED",
                            }
                            for f in task.checkpoint.profile_field_keys.get(key, [])
                        ],
                    }
            for key in task.checkpoint.featured_collection_types:
                if key not in candidate.collections:
                    snapshot["collections"][key] = {
                        "collection_observation_id": None,
                        "collection_type": key,
                        "status": "NOT_ATTEMPTED",
                        "complete": False,
                        "observed_at": None,
                        "module_label": None,
                        "cards": [],
                        "coverage_gaps": ["not_attempted"],
                        "failure_reason": candidate.failure_reason
                        or task.failure_reason
                        or "UPSTREAM_INTERRUPTED",
                    }
            previous = published.get(candidate.snapshot_ids[-1]) if candidate.snapshot_ids else None
            if previous == snapshot:
                continue
            snapshot_id = uid()
            for observation in candidate.collections.values():
                self._persist_collection(conn, task, ref.creator_id, observation)
            snapshot_row = conn.execute(
                "INSERT INTO creator_snapshots(snapshot_id,root_task_id,creator_id,"
                "draft_revision,payload) VALUES(%s,%s,%s,%s,%s) RETURNING created_at",
                (
                    snapshot_id,
                    task.root_task_id,
                    ref.creator_id,
                    task.checkpoint.revision,
                    Jsonb(snapshot),
                ),
            ).fetchone()
            assert snapshot_row is not None
            for observation in candidate.collections.values():
                conn.execute(
                    """INSERT INTO snapshot_collections(creator_snapshot_id,collection_type,
                    collection_observation_id,observed_at,status) VALUES(%s,%s,%s,%s,%s)
                    ON CONFLICT(creator_snapshot_id,collection_type) DO NOTHING""",
                    (
                        snapshot_id,
                        observation.collection_type.value,
                        observation.collection_observation_id,
                        observation.observed_at,
                        observation.status.value,
                    ),
                )
            candidate.snapshot_ids.append(snapshot_id)
            conn.execute(
                "UPDATE task_creators SET latest_snapshot_id=%s "
                "WHERE root_task_id=%s AND creator_id=%s",
                (snapshot_id, task.root_task_id, ref.creator_id),
            )
            conn.execute(
                "UPDATE platform_creators SET projection=%s WHERE creator_id=%s",
                (Jsonb(fields), ref.creator_id),
            )
            if ref.platform == "douyin_xingtu":
                CreatorLibraryWriter().sync(
                    conn,
                    creator_id=ref.creator_id,
                    platform_creator_id=ref.platform_creator_id,
                    projection=fields,
                    snapshot_id=snapshot_id,
                    snapshot=snapshot,
                    captured_at=snapshot_row["created_at"],
                )

    def _persist_collection(
        self,
        conn: psycopg.Connection[dict[str, Any]],
        task: TaskRecord,
        creator_id: str,
        observation: FeaturedCollectionObservation,
    ) -> None:
        """Append-only write of one collection observation and its ordered cards."""
        conn.execute(
            """INSERT INTO featured_collections(collection_observation_id,root_task_id,creator_id,
            collection_type,status,observed_at,set_key,coverage_gaps,payload)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(collection_observation_id) DO NOTHING""",
            (
                observation.collection_observation_id,
                task.root_task_id,
                creator_id,
                observation.collection_type.value,
                observation.status.value,
                observation.observed_at,
                observation.set_key,
                Jsonb(observation.coverage_gaps),
                Jsonb(observation.model_dump(mode="json")),
            ),
        )
        for card in observation.cards:
            if card.identity_ref and card.content_id is None:
                # Verified identity is reused across modules; the two modules keep their own cards.
                card.content_id = self._content_id(conn, card)
            conn.execute(
                """INSERT INTO featured_cards(collection_observation_id,card_id,position,content_id,
                identity_kind,platform_content_id,canonical_link,local_key,cover_object_id,
                cover_status,truncated_fields,payload)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(collection_observation_id,card_id) DO NOTHING""",
                (
                    observation.collection_observation_id,
                    card.card_id,
                    card.position,
                    card.content_id,
                    card.identity_kind,
                    card.platform_content_id,
                    card.canonical_link,
                    card.local_key,
                    card.cover.object_id if card.cover else None,
                    card.cover.status.value if card.cover else "NOT_ATTEMPTED",
                    Jsonb(card.truncated_fields),
                    Jsonb(card.model_dump(mode="json")),
                ),
            )

    @staticmethod
    def _content_id(conn: psycopg.Connection[dict[str, Any]], card: FeaturedCard) -> str | None:
        conn.execute(
            """INSERT INTO contents(content_id,platform,platform_content_id,canonical_link)
            VALUES(%s,'douyin_xingtu',%s,%s) ON CONFLICT DO NOTHING""",
            (uid(), card.platform_content_id, card.canonical_link),
        )
        if card.platform_content_id:
            row = conn.execute(
                "SELECT content_id FROM contents WHERE platform='douyin_xingtu' "
                "AND platform_content_id=%s",
                (card.platform_content_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT content_id FROM contents WHERE platform='douyin_xingtu' "
                "AND canonical_link=%s",
                (card.canonical_link,),
            ).fetchone()
        return str(row["content_id"]) if row else None

    @staticmethod
    def retryable(candidate: Candidate) -> bool:
        """A candidate is retryable when a step is failed or an attempted step is incomplete."""
        return is_retryable(candidate)

    def cover_reference(self, root_task_id: str, object_id: str) -> dict[str, Any] | None:
        """Authenticated-access check: an object is only reachable through its own task's rows.

        Two ownership paths exist and both are checked:

        * `media_objects` → `featured_cards` → `featured_collections.root_task_id`
          (精选集合 covers);
        * `media_objects.source_key` → `douyin_xingtu_creator_video_observations.cover_source_uri`
          → `creator_snapshots.root_task_id` (the DATA-02 work covers, whose platform object key
          is the stable link and whose signed URL expires).

        The second path is why the 创作能力 works list can serve a cover through the task-scoped
        endpoint at all; without it the page correctly degrades to 「封面未生成」.
        """
        with self.connect() as conn:
            return conn.execute(
                """SELECT m.object_id,m.checksum,m.kind,m.content_type,m.byte_size,
                c.collection_observation_id,c.card_id
                FROM media_objects m
                JOIN featured_cards c ON c.cover_object_id=m.object_id
                JOIN featured_collections f
                ON f.collection_observation_id=c.collection_observation_id
                WHERE m.object_id=%s AND m.kind='cover' AND f.root_task_id=%s
                UNION ALL
                SELECT m.object_id,m.checksum,m.kind,m.content_type,m.byte_size,NULL,NULL
                FROM media_objects m
                JOIN douyin_xingtu_creator_video_observations v
                  ON v.cover_source_uri=m.source_key
                JOIN creator_snapshots s ON s.snapshot_id=v.snapshot_id
                WHERE m.object_id=%s AND m.kind='cover' AND m.source_key IS NOT NULL
                  AND s.root_task_id=%s
                LIMIT 1""",
                (object_id, root_task_id, object_id, root_task_id),
            ).fetchone()

    @staticmethod
    def featured_complete(task: TaskRecord, creator: str) -> bool:
        c = next(c for c in task.checkpoint.candidates if c.ref.platform_creator_id == creator)
        return (
            bool(task.checkpoint.featured_collection_types)
            and set(c.collections) == set(task.checkpoint.featured_collection_types)
            and all(o.complete for o in c.collections.values())
        )

    @classmethod
    def pipeline_complete(cls, task: TaskRecord, creator: str) -> bool:
        """Require only the collection scopes registered for the task's platform contract."""

        profile_complete = cls.profile_complete(task, creator)
        if (
            task.platform == PlatformId.KUAISHOU_JUXING
            and not task.checkpoint.featured_collection_types
        ):
            return profile_complete
        # Preserve the established Xingtu behaviour: both F06 default collections are required.
        return profile_complete and cls.featured_complete(task, creator)

    @classmethod
    def profile_complete(cls, task: TaskRecord, creator: str) -> bool:
        coverage = cls.profile_coverage(task, creator)
        return bool(coverage["complete"])

    @staticmethod
    def profile_coverage(task: TaskRecord, creator: str) -> dict[str, Any]:
        c = next(c for c in task.checkpoint.candidates if c.ref.platform_creator_id == creator)
        registered_complete = (
            bool(task.checkpoint.profile_module_keys)
            and set(c.modules) == set(task.checkpoint.profile_module_keys)
            and all(m.complete for m in c.modules.values())
        )
        requirement = task.profile_requirement
        gaps: list[str] = []
        if requirement:
            if not requirement.inventory_verified:
                gaps.append("REQUIREMENT_INVENTORY_UNVERIFIED")
            for key, fields in requirement.modules.items():
                module = c.modules.get(key)
                if module is None:
                    gaps.append(f"MODULE_NOT_ATTEMPTED:{key}")
                    continue
                values = {field.field_key: field for field in module.fields}
                for field in fields:
                    if field not in values:
                        gaps.append(f"FIELD_NOT_ATTEMPTED:{key}.{field}")
                    elif values[field].status in {FieldStatus.FAILED, FieldStatus.NOT_ATTEMPTED}:
                        gaps.append(f"FIELD_INCOMPLETE:{key}.{field}")
        counts = {status.value: 0 for status in FieldStatus}
        for module in c.modules.values():
            for observation in module.fields:
                counts[observation.status.value] += 1
        return {
            "scope": "business_requirement" if requirement else "legacy_registered_modules",
            "requirement_version": requirement.version if requirement else None,
            "registered_complete": registered_complete,
            "complete": registered_complete and not gaps,
            "gaps": gaps,
            # Permission/empty states are resolved observations, never collected values.
            "observed_field_status_counts": counts,
        }

    def results(self, root: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            self._load(conn, root)
            return conn.execute(
                """SELECT tc.creator_id,tc.first_position,s.snapshot_id,s.payload
                FROM task_creators tc JOIN creator_snapshots s
                ON s.snapshot_id=tc.latest_snapshot_id
                AND s.root_task_id=tc.root_task_id AND s.creator_id=tc.creator_id
                WHERE tc.root_task_id=%s ORDER BY tc.first_position""",
                (root,),
            ).fetchall()
