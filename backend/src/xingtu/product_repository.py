from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from .contracts import PlatformRegistry
from .domain import (
    Checkpoint,
    CollectorError,
    FilterPlan,
    ProfileRequirement,
    TaskKind,
    TaskRecord,
    TaskStatus,
    uid,
    utcnow,
)
from .product_models import (
    CreateTaskResponse,
    FieldError,
    P1WorkflowState,
    RequirementForm,
)
from .repository import TERMINAL_COMPLETED_AT_CLAUSE, Repository


class ProductRepository:
    """M3 persistence isolated from the existing collection repository.

    Only ``promote_intake`` writes the existing P2 tables, and it writes the same ``TaskRecord``
    payload and checkpoint shape as ``Repository.create``.
    """

    def __init__(self, repository: Repository):
        self.repository = repository

    # --- Product identities and sessions -------------------------------------------------

    def create_user(
        self, username: str, display_name: str, password_hash: str, *, actor: str
    ) -> str:
        user_id = uid()
        with self.repository.connect() as conn:
            row = conn.execute(
                """INSERT INTO users(user_id,username,display_name,password_hash)
                VALUES(%s,%s,%s,%s) ON CONFLICT(username) DO NOTHING RETURNING user_id""",
                (user_id, username, display_name, password_hash),
            ).fetchone()
            if not row:
                raise CollectorError("INVALID_FORM", "USERNAME_EXISTS")
            conn.execute(
                "INSERT INTO audit_logs(actor,actor_user_id,action) VALUES(%s,%s,%s)",
                (actor, user_id, "product_user.create"),
            )
        return user_id

    def set_user_active(self, username: str, active: bool, *, actor: str) -> str:
        with self.repository.connect() as conn:
            row = conn.execute(
                "UPDATE users SET active=%s,updated_at=now() WHERE username=%s RETURNING user_id",
                (active, username),
            ).fetchone()
            if not row:
                raise CollectorError("INVALID_FORM", "USER_NOT_FOUND")
            user_id = str(row["user_id"])
            if not active:
                conn.execute(
                    "UPDATE sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL",
                    (user_id,),
                )
            conn.execute(
                "INSERT INTO audit_logs(actor,actor_user_id,action) VALUES(%s,%s,%s)",
                (actor, user_id, "product_user.enable" if active else "product_user.disable"),
            )
            return user_id

    def reset_password(self, username: str, password_hash: str, *, actor: str) -> str:
        with self.repository.connect() as conn:
            row = conn.execute(
                """UPDATE users SET password_hash=%s,password_changed_at=now(),updated_at=now()
                WHERE username=%s RETURNING user_id""",
                (password_hash, username),
            ).fetchone()
            if not row:
                raise CollectorError("INVALID_FORM", "USER_NOT_FOUND")
            user_id = str(row["user_id"])
            conn.execute(
                "UPDATE sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL",
                (user_id,),
            )
            conn.execute(
                "INSERT INTO audit_logs(actor,actor_user_id,action) VALUES(%s,%s,%s)",
                (actor, user_id, "product_user.reset_password"),
            )
            return user_id

    def find_user_for_login(self, username: str) -> dict[str, object] | None:
        with self.repository.connect() as conn:
            row = conn.execute(
                """SELECT user_id,username,display_name,password_hash,active
                FROM users WHERE username=%s""",
                (username,),
            ).fetchone()
            return dict(row) if row else None

    def create_session(
        self,
        user_id: str,
        token_hash: str,
        csrf_token: str,
        idle_expires_at: object,
        absolute_expires_at: object,
    ) -> str:
        session_id = uid()
        with self.repository.connect() as conn:
            conn.execute(
                """INSERT INTO sessions(session_id,user_id,token_hash,csrf_token,
                idle_expires_at,absolute_expires_at) VALUES(%s,%s,%s,%s,%s,%s)""",
                (
                    session_id,
                    user_id,
                    token_hash,
                    csrf_token,
                    idle_expires_at,
                    absolute_expires_at,
                ),
            )
            conn.execute(
                "INSERT INTO audit_logs(actor,actor_user_id,action) VALUES(%s,%s,%s)",
                ("product:" + user_id, user_id, "product_auth.login"),
            )
        return session_id

    def resolve_session(
        self, token_hash: str, idle_extension: timedelta
    ) -> dict[str, object] | None:
        with self.repository.connect() as conn:
            row = conn.execute(
                """SELECT s.session_id,s.user_id,s.csrf_token,u.username,u.display_name
                FROM sessions s JOIN users u USING(user_id)
                WHERE s.token_hash=%s AND s.revoked_at IS NULL AND u.active=true
                AND s.idle_expires_at>now() AND s.absolute_expires_at>now() FOR UPDATE OF s""",
                (token_hash,),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                """UPDATE sessions SET last_seen_at=now(),
                idle_expires_at=least(absolute_expires_at,now()+%s) WHERE session_id=%s""",
                (idle_extension, row["session_id"]),
            )
            return dict(row)

    def revoke_session(self, token_hash: str, actor_user_id: str | None) -> None:
        with self.repository.connect() as conn:
            row = conn.execute(
                """UPDATE sessions SET revoked_at=coalesce(revoked_at,now()) WHERE token_hash=%s
                RETURNING user_id""",
                (token_hash,),
            ).fetchone()
            if row:
                user_id = actor_user_id or str(row["user_id"])
                conn.execute(
                    "INSERT INTO audit_logs(actor,actor_user_id,action) VALUES(%s,%s,%s)",
                    ("product:" + user_id, user_id, "product_auth.logout"),
                )

    # --- Durable intake ------------------------------------------------------------------

    def create_product_task(
        self,
        form: RequirementForm,
        *,
        capability_version: str,
        user_id: str,
        idempotency_key: str,
        model_config_id: str,
        prompt_version: str,
        origin_root_task_id: str | None = None,
    ) -> CreateTaskResponse:
        if not idempotency_key.strip() or len(idempotency_key) > 200:
            raise CollectorError("INVALID_FORM", "INVALID_IDEMPOTENCY_KEY")
        payload = {
            "form": form.model_dump(mode="json"),
            "capability_version": capability_version,
            "origin_root_task_id": origin_root_task_id,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        actor = "product:" + user_id
        operation = "product.create_task"
        with self.repository.connect() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"{user_id}:{operation}:{idempotency_key}",),
            )
            old = conn.execute(
                """SELECT digest,response_payload,root_task_id FROM idempotency_records
                WHERE actor=%s AND operation=%s AND key=%s""",
                (actor, operation, idempotency_key),
            ).fetchone()
            if old:
                if old["digest"] != digest:
                    raise CollectorError("INVALID_FORM", "IDEMPOTENCY_CONFLICT")
                return CreateTaskResponse.model_validate(
                    old["response_payload"]
                    or {"root_task_id": str(old["root_task_id"]), "status": "RECEIVED"}
                )
            root_task_id, requirement_id, p1_task_id = uid(), uid(), uid()
            if origin_root_task_id is not None:
                # A syntactically valid UUID that names no task used to surface as an unhandled
                # ForeignKeyViolation (HTTP 500). The header is client input, so reject it as a
                # validation error inside the same transaction as the insert.
                known = conn.execute(
                    "SELECT 1 FROM root_tasks WHERE root_task_id=%s", (origin_root_task_id,)
                ).fetchone()
                if not known:
                    raise CollectorError("INVALID_FORM", "ORIGIN_TASK_NOT_FOUND")
            state = P1WorkflowState(
                root_task_id=root_task_id,
                requirement_id=requirement_id,
                p1_task_id=p1_task_id,
                requirement_form=form,
                capability_version=capability_version,
                capability_snapshot_ref="registry:" + capability_version,
                prompt_version=prompt_version,
                model_config_id=model_config_id,
            )
            root_payload = {
                "schema_version": "product_root_task.v1",
                "root_task_id": root_task_id,
                "requirement_id": requirement_id,
                "p1_task_id": p1_task_id,
                "target_count": form.target_count,
                "stage": "intake",
                "field_errors": [],
            }
            conn.execute(
                """INSERT INTO root_tasks(root_task_id,state,version,unit_id,payload,
                requirement_id,created_by,origin_root_task_id,task_type,platform)
                VALUES(%s,'RECEIVED',0,NULL,%s,%s,%s,%s,'product_intake',%s)""",
                (
                    root_task_id,
                    Jsonb(root_payload),
                    requirement_id,
                    user_id,
                    origin_root_task_id,
                    form.platform,
                ),
            )
            conn.execute(
                """INSERT INTO requirements(requirement_id,root_task_id,submitted_by,
                origin_root_task_id,schema_version,capability_version,payload)
                VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                (
                    requirement_id,
                    root_task_id,
                    user_id,
                    origin_root_task_id,
                    form.schema_version,
                    capability_version,
                    Jsonb(form.model_dump(mode="json")),
                ),
            )
            conn.execute(
                """INSERT INTO tasks(task_id,root_task_id,parent_task_id,kind)
                VALUES(%s,%s,NULL,'P1')""",
                (p1_task_id, root_task_id),
            )
            conn.execute(
                "INSERT INTO task_checkpoints(task_id,revision,payload) VALUES(%s,0,%s)",
                (p1_task_id, Jsonb(state.model_dump(mode="json"))),
            )
            conn.execute(
                """INSERT INTO intake_dispatches(root_task_id,p1_task_id,workflow_id)
                VALUES(%s,%s,%s)""",
                (root_task_id, p1_task_id, f"intake/{root_task_id}"),
            )
            response = CreateTaskResponse(root_task_id=root_task_id)
            conn.execute(
                """INSERT INTO idempotency_records(
                actor,operation,key,digest,root_task_id,response_payload)
                VALUES(%s,%s,%s,%s,%s,%s)""",
                (
                    actor,
                    operation,
                    idempotency_key,
                    digest,
                    root_task_id,
                    Jsonb(response.model_dump(mode="json")),
                ),
            )
            conn.execute(
                """INSERT INTO audit_logs(root_task_id,actor,actor_user_id,action)
                VALUES(%s,%s,%s,'product_task.create')""",
                (root_task_id, actor, user_id),
            )
            return response

    def load_intake(self, root_task_id: str, *, lock: bool = False) -> P1WorkflowState:
        with self.repository.connect() as conn:
            row = conn.execute(
                """SELECT c.payload FROM root_tasks r
                JOIN tasks t ON t.root_task_id=r.root_task_id AND t.kind='P1'
                JOIN task_checkpoints c ON c.task_id=t.task_id
                WHERE r.root_task_id=%s"""
                + (" FOR UPDATE OF r,c" if lock else ""),
                (root_task_id,),
            ).fetchone()
            if not row:
                raise CollectorError("INVALID_FORM", "TASK_NOT_FOUND")
            return P1WorkflowState.model_validate(row["payload"])

    def save_intake(self, state: P1WorkflowState, status: TaskStatus) -> None:
        with self.repository.connect() as conn:
            row = conn.execute(
                """SELECT r.version,r.state,c.revision FROM root_tasks r
                JOIN task_checkpoints c ON c.task_id=%s
                WHERE r.root_task_id=%s FOR UPDATE OF r,c""",
                (state.p1_task_id, state.root_task_id),
            ).fetchone()
            if not row:
                raise CollectorError("INVALID_FORM", "TASK_NOT_FOUND")
            if row["state"] == TaskStatus.CANCELLED:
                raise CollectorError("TASK_CANCELLED", "INTAKE_CANCELLED")
            if row["state"] not in {TaskStatus.RECEIVED, TaskStatus.PARSING}:
                raise CollectorError("INVALID_FORM", "INTAKE_STATE_CONFLICT")
            conn.execute(
                "UPDATE task_checkpoints SET revision=%s,payload=%s WHERE task_id=%s",
                (
                    int(row["revision"]) + 1,
                    Jsonb(state.model_dump(mode="json")),
                    state.p1_task_id,
                ),
            )
            conn.execute(
                """UPDATE root_tasks SET state=%s,version=%s,updated_at=now(),
                payload=jsonb_set(payload,'{stage}',to_jsonb(%s::text)) WHERE root_task_id=%s""",
                (status, int(row["version"]) + 1, status.value.lower(), state.root_task_id),
            )

    def existing_model_run(
        self, root_task_id: str, retry_cycle: int, attempt: int
    ) -> dict[str, Any] | None:
        with self.repository.connect() as conn:
            row = conn.execute(
                """SELECT * FROM model_runs WHERE root_task_id=%s
                AND retry_cycle=%s AND attempt_number=%s""",
                (root_task_id, retry_cycle, attempt),
            ).fetchone()
            return dict(row) if row else None

    def begin_model_run(
        self,
        state: P1WorkflowState,
        *,
        provider: str,
        requested_model: str,
        input_digest: str,
    ) -> str:
        model_run_id = uid()
        with self.repository.connect() as conn:
            row = conn.execute(
                """INSERT INTO model_runs(model_run_id,root_task_id,p1_task_id,retry_cycle,
                attempt_number,
                provider,requested_model,prompt_version,input_digest,status)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'started')
                ON CONFLICT(root_task_id,retry_cycle,attempt_number) DO NOTHING
                RETURNING model_run_id""",
                (
                    model_run_id,
                    state.root_task_id,
                    state.p1_task_id,
                    state.retry_cycle,
                    state.attempt_count,
                    provider,
                    requested_model,
                    state.prompt_version,
                    input_digest,
                ),
            ).fetchone()
            if row:
                return str(row["model_run_id"])
            old = conn.execute(
                """SELECT model_run_id,input_digest FROM model_runs
                WHERE root_task_id=%s AND retry_cycle=%s AND attempt_number=%s""",
                (state.root_task_id, state.retry_cycle, state.attempt_count),
            ).fetchone()
            if not old or old["input_digest"] != input_digest:
                raise CollectorError("STORAGE_UNAVAILABLE", "MODEL_RUN_CONFLICT")
            return str(old["model_run_id"])

    def finish_model_run(
        self,
        model_run_id: str,
        *,
        status: str,
        response_model: str | None = None,
        output_payload: dict[str, Any] | None = None,
        error_payload: dict[str, Any] | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        latency_ms: int | None = None,
        delivery_status: str = "received",
    ) -> None:
        with self.repository.connect() as conn:
            updated = conn.execute(
                """UPDATE model_runs SET status=%s,response_model=%s,output_payload=%s,
                error_payload=%s,input_tokens=%s,output_tokens=%s,latency_ms=%s,
                delivery_status=%s,completed_at=now()
                WHERE model_run_id=%s AND status='started' RETURNING model_run_id""",
                (
                    status,
                    response_model,
                    Jsonb(output_payload) if output_payload is not None else None,
                    Jsonb(error_payload) if error_payload is not None else None,
                    input_tokens,
                    output_tokens,
                    latency_ms,
                    delivery_status,
                    model_run_id,
                ),
            ).fetchone()
            if not updated:
                existing = conn.execute(
                    "SELECT status FROM model_runs WHERE model_run_id=%s", (model_run_id,)
                ).fetchone()
                if not existing:
                    raise CollectorError("STORAGE_UNAVAILABLE", "MODEL_RUN_NOT_FOUND")

    def fail_intake(
        self, state: P1WorkflowState, status: TaskStatus, errors: list[FieldError]
    ) -> None:
        if status not in {TaskStatus.FAILED, TaskStatus.FAILED_VALIDATION}:
            raise ValueError("invalid intake terminal status")
        state.final_error = errors
        with self.repository.connect() as conn:
            row = conn.execute(
                "SELECT state,version,payload FROM root_tasks WHERE root_task_id=%s FOR UPDATE",
                (state.root_task_id,),
            ).fetchone()
            if not row:
                raise CollectorError("INVALID_FORM", "TASK_NOT_FOUND")
            if row["state"] == TaskStatus.CANCELLED:
                return
            payload = dict(row["payload"])
            payload["stage"] = (
                "validation_failed" if status == TaskStatus.FAILED_VALIDATION else "model_failed"
            )
            payload["field_errors"] = [error.model_dump(mode="json") for error in errors]
            payload["failure_reason"] = errors[0].code if errors else "AI_PARSE_FAILED"
            conn.execute(
                "UPDATE task_checkpoints SET revision=revision+1,payload=%s WHERE task_id=%s",
                (Jsonb(state.model_dump(mode="json")), state.p1_task_id),
            )
            conn.execute(
                """UPDATE root_tasks SET state=%s,version=%s,payload=%s,updated_at=now()"""
                + TERMINAL_COMPLETED_AT_CLAUSE
                + """ WHERE root_task_id=%s""",
                (
                    status,
                    int(row["version"]) + 1,
                    Jsonb(payload),
                    True,
                    state.root_task_id,
                ),
            )

    def promote_intake(
        self,
        state: P1WorkflowState,
        plan: FilterPlan,
        *,
        unit_id: str,
        registry: PlatformRegistry,
        profile_requirement: ProfileRequirement | None = None,
    ) -> str:
        with self.repository.connect() as conn:
            root = conn.execute(
                "SELECT state,version FROM root_tasks WHERE root_task_id=%s FOR UPDATE",
                (state.root_task_id,),
            ).fetchone()
            if not root:
                raise CollectorError("INVALID_FORM", "TASK_NOT_FOUND")
            existing = conn.execute(
                "SELECT task_id FROM tasks WHERE root_task_id=%s AND kind='P2-1'",
                (state.root_task_id,),
            ).fetchone()
            if existing:
                return str(existing["task_id"])
            if root["state"] == TaskStatus.CANCELLED:
                raise CollectorError("TASK_CANCELLED", "INTAKE_CANCELLED")
            if root["state"] not in {TaskStatus.PARSING, TaskStatus.RECEIVED}:
                raise CollectorError("INVALID_FORM", "INTAKE_STATE_CONFLICT")
            unit = conn.execute(
                """SELECT u.unit_id,u.allowed_task_kinds,b.enabled AS platform_enabled
                FROM execution_units u LEFT JOIN execution_unit_platform_bindings b
                  ON b.unit_id=u.unit_id AND b.platform=%s
                WHERE u.unit_id=%s""",
                (plan.platform, unit_id),
            ).fetchone()
            if not unit:
                raise CollectorError("RESOURCE_UNAVAILABLE", "EXECUTION_UNIT_NOT_FOUND")
            # Keep the existing promotion-time assignment, but never assign a collection task to a
            # unit whose capability configuration no longer allows it.  With the current single
            # unit this is behavior-identical; the fallback only matters for future multi-unit
            # configurations.
            assigned_unit_id = unit_id
            if (
                TaskKind.COLLECTION.value not in (unit["allowed_task_kinds"] or [])
                or not unit["platform_enabled"]
            ):
                capable = conn.execute(
                    """SELECT u.unit_id FROM execution_units u
                    JOIN execution_unit_platform_bindings b ON b.unit_id=u.unit_id
                    WHERE %s = ANY(u.allowed_task_kinds) AND u.state <> 'QUARANTINED'
                      AND b.platform=%s AND b.enabled=true
                    ORDER BY u.unit_id LIMIT 1""",
                    (TaskKind.COLLECTION.value, plan.platform),
                ).fetchone()
                if not capable:
                    raise CollectorError("RESOURCE_UNAVAILABLE", "NO_COLLECTION_UNIT")
                assigned_unit_id = str(capable["unit_id"])
            p2_task_id, attempt_id = uid(), uid()
            module_versions = {item.key: item.checkpoint_version for item in registry.modules}
            featured_types = [item.key.value for item in registry.featured]
            featured_versions = {
                item.key.value: item.checkpoint_version for item in registry.featured
            }
            task = TaskRecord(
                root_task_id=state.root_task_id,
                task_id=p2_task_id,
                attempt_id=attempt_id,
                plan=plan,
                state=TaskStatus.QUEUED,
                version=int(root["version"]) + 1,
                execution_unit_id=assigned_unit_id,
                source="model",
                profile_requirement=profile_requirement,
                checkpoint=Checkpoint(
                    conditions_digest=plan.digest(),
                    adapter_version=registry.adapter_version,
                    contract_version=registry.contract_version,
                    profile_module_keys=[item.key for item in registry.modules],
                    profile_checkpoint_versions=module_versions,
                    featured_collection_types=featured_types,
                    featured_checkpoint_versions=featured_versions,
                ),
            )
            conn.execute(
                "UPDATE root_tasks SET platform=%s WHERE root_task_id=%s",
                (plan.platform, state.root_task_id),
            )
            conn.execute(
                "INSERT INTO filter_plans(root_task_id,payload,source) VALUES(%s,%s,'model')",
                (state.root_task_id, Jsonb(plan.model_dump(mode="json"))),
            )
            conn.execute(
                """INSERT INTO tasks(task_id,root_task_id,parent_task_id,kind)
                VALUES(%s,%s,%s,'P2-1')""",
                (p2_task_id, state.root_task_id, state.p1_task_id),
            )
            for kind in ("search", "profile"):
                conn.execute(
                    """INSERT INTO tasks(task_id,root_task_id,parent_task_id,kind)
                    VALUES(%s,%s,%s,%s)""",
                    (uid(), state.root_task_id, p2_task_id, kind),
                )
            conn.execute(
                "INSERT INTO task_attempts(attempt_id,root_task_id,segment) VALUES(%s,%s,0)",
                (attempt_id, state.root_task_id),
            )
            conn.execute(
                "INSERT INTO task_checkpoints(task_id,revision,payload) VALUES(%s,0,%s)",
                (p2_task_id, Jsonb(task.checkpoint.model_dump(mode="json"))),
            )
            conn.execute(
                """INSERT INTO task_dispatches(root_task_id,segment,workflow_id,sent)
                VALUES(%s,0,%s,false)""",
                (state.root_task_id, f"collect/{state.root_task_id}"),
            )
            conn.execute(
                """UPDATE root_tasks SET state='QUEUED',version=%s,unit_id=%s,payload=%s,
                updated_at=now() WHERE root_task_id=%s""",
                (
                    task.version,
                    assigned_unit_id,
                    Jsonb(task.model_dump(mode="json", exclude={"checkpoint"})),
                    state.root_task_id,
                ),
            )
            conn.execute(
                "UPDATE task_checkpoints SET revision=revision+1,payload=%s WHERE task_id=%s",
                (Jsonb(state.model_dump(mode="json")), state.p1_task_id),
            )
            conn.execute(
                """INSERT INTO audit_logs(root_task_id,actor,action)
                VALUES(%s,'intake-worker','product_intake.promote')""",
                (state.root_task_id,),
            )
            return p2_task_id

    def mark_intake_dispatched(self, root_task_id: str) -> None:
        with self.repository.connect() as conn:
            conn.execute(
                "UPDATE intake_dispatches SET sent=true,updated_at=now() WHERE root_task_id=%s",
                (root_task_id,),
            )

    def record_intake_dispatch_failure(
        self, root_task_id: str, error_code: str, *, throttle_seconds: int = 60
    ) -> None:
        """Record a failed intake dispatch without a schema change.

        The dispatch row deliberately keeps ``sent=false`` so the next poll tick retries it; this
        audit entry is the only persistent trace of the failure. It is throttled so a persistent
        failure cannot flood ``audit_logs`` every 2 seconds.
        """
        action = f"product_intake.dispatch_failed:{error_code}"[:200]
        with self.repository.connect() as conn:
            recent = conn.execute(
                """SELECT 1 FROM audit_logs WHERE root_task_id=%s
                AND action LIKE 'product_intake.dispatch_failed%%'
                AND created_at > now() - make_interval(secs => %s)""",
                (root_task_id, float(throttle_seconds)),
            ).fetchone()
            if recent:
                return
            conn.execute(
                """INSERT INTO audit_logs(root_task_id,actor,action)
                VALUES(%s,'intake-worker',%s)""",
                (root_task_id, action),
            )

    def intake_dispatch_state(self, root_task_id: str) -> dict[str, Any] | None:
        with self.repository.connect() as conn:
            row = conn.execute(
                """SELECT sent,created_at,updated_at,workflow_id FROM intake_dispatches
                WHERE root_task_id=%s""",
                (root_task_id,),
            ).fetchone()
            return dict(row) if row else None

    def pending_intake_dispatches(self) -> list[dict[str, Any]]:
        with self.repository.connect() as conn:
            return conn.execute(
                """SELECT d.* FROM intake_dispatches d JOIN root_tasks r USING(root_task_id)
                WHERE d.sent=false AND r.state IN ('RECEIVED','PARSING') ORDER BY d.created_at"""
            ).fetchall()

    def model_run_started_at(self, model_run_id: str) -> datetime | None:
        with self.repository.connect() as conn:
            row = conn.execute(
                "SELECT created_at FROM model_runs WHERE model_run_id=%s", (model_run_id,)
            ).fetchone()
            return row["created_at"] if row else None

    def expire_sessions(self) -> int:
        now = utcnow()
        with self.repository.connect() as conn:
            row = conn.execute(
                """UPDATE sessions SET revoked_at=%s WHERE revoked_at IS NULL
                AND (idle_expires_at<=%s OR absolute_expires_at<=%s) RETURNING session_id""",
                (now, now, now),
            ).fetchall()
            return len(row)
