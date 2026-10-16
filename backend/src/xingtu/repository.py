from __future__ import annotations

import hashlib
import json
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
    ProfileRequirement,
    ReleaseDisposition,
    TaskRecord,
    TaskStatus,
    uid,
    utcnow,
)

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
                """UPDATE execution_units SET lease_until=%s
              WHERE unit_id=%s AND owner=%s AND generation=%s AND lease_until>now()
              AND state='LEASED' RETURNING unit_id""",
                (utcnow() + timedelta(seconds=120), unit, owner, generation),
            ).fetchone()
            if not row:
                raise CollectorError("LEASE_LOST")

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
              last_session_checked_at=now(),last_session_reason=%s,failure_reason=%s
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
                """INSERT INTO root_tasks(root_task_id,state,version,unit_id,payload)
                VALUES(%s,%s,0,%s,%s)""",
                (
                    task.root_task_id,
                    task.state,
                    unit,
                    Jsonb(task.model_dump(mode="json", exclude={"checkpoint"})),
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
            "UPDATE root_tasks SET state=%s,version=%s,payload=%s,updated_at=now()"
            + TERMINAL_COMPLETED_AT_CLAUSE
            + " WHERE root_task_id=%s",
            (
                task.state,
                task.version,
                Jsonb(task.model_dump(mode="json", exclude={"checkpoint"})),
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
                    task.plan.capability_version != ctx.capability_version
                    or task.checkpoint.adapter_version != ctx.adapter_version
                    or task.checkpoint.contract_version != ctx.contract_version
                ):
                    raise CollectorError("PLATFORM_PAGE_CHANGED", "VERSION_MISMATCH")
            yield task, conn
            self._save(conn, task)

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
                    if not any(self.retryable(c) for c in task.checkpoint.candidates):
                        raise CollectorError("INVALID_FORM", "NO_RETRYABLE_FAILURE")
                task.segment += 1
                task.attempt_id = uid()
                task.state = TaskStatus.QUEUED
                task.failure_reason = None
                task.checkpoint.active_seconds = 0
                task.checkpoint.scanned_ids = []
                for c in task.checkpoint.candidates:
                    if self.retryable(c):
                        c.state = "pending"
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
            conn.execute(
                "INSERT INTO audit_logs(root_task_id,actor,action) VALUES(%s,%s,%s)",
                (root, actor, action),
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
        for candidate in task.checkpoint.candidates:
            if not candidate.valid or (
                only_creator and candidate.ref.platform_creator_id != only_creator
            ):
                continue
            ref = candidate.ref
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
            snapshot_id = uid()
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
        if candidate.state == "failed":
            return True
        if not candidate.valid:
            return False
        return any(not m.complete for m in candidate.modules.values()) or any(
            not o.complete for o in candidate.collections.values()
        )

    def cover_reference(self, root_task_id: str, object_id: str) -> dict[str, Any] | None:
        """Authenticated-access check: an object is only reachable through its own task's card."""
        with self.connect() as conn:
            return conn.execute(
                """SELECT m.object_id,m.checksum,m.kind,m.content_type,m.byte_size,
                c.collection_observation_id,c.card_id
                FROM media_objects m
                JOIN featured_cards c ON c.cover_object_id=m.object_id
                JOIN featured_collections f
                ON f.collection_observation_id=c.collection_observation_id
                WHERE m.object_id=%s AND m.kind='cover' AND f.root_task_id=%s LIMIT 1""",
                (object_id, root_task_id),
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
        """F05 profile steps and both F06 default collections must all be complete."""
        return cls.profile_complete(task, creator) and cls.featured_complete(task, creator)

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
