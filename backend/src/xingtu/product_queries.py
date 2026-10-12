from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

from psycopg import sql
from psycopg.types.json import Jsonb

from .domain import CollectorError, FilterPlan, TaskRecord, TaskStatus, uid, utcnow
from .product_models import (
    ChallengeSummary,
    CreatorPage,
    CreatorSummary,
    FieldError,
    IntakeProgress,
    P1WorkflowState,
    RequirementForm,
    TaskCounts,
    TaskDetail,
    TaskPage,
    TaskSummary,
)
from .repository import Repository
from .worker_health import INTAKE_QUEUE, WorkerHealthMonitor

TERMINAL_STATES = {
    TaskStatus.CANCELLED,
    TaskStatus.COMPLETED,
    TaskStatus.PARTIAL_COMPLETED,
    TaskStatus.FAILED_VALIDATION,
    TaskStatus.FAILED,
}

INTAKE_STAGE_STATES = {TaskStatus.RECEIVED, TaskStatus.PARSING}
# A healthy dispatch loop flips `sent` within ~2 s and retries every 2 s, so an unsent row that has
# waited this long means nothing is consuming it. Two minutes leaves room for a slow database tick
# without delaying the user-visible diagnosis.
INTAKE_BLOCK_AFTER_SECONDS = 120.0
DISPATCH_FAILURE_PREFIX = "product_intake.dispatch_failed"


def _validated_uuid(value: str, reason: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise CollectorError("INVALID_FORM", reason) from exc


def task_stage(status: TaskStatus) -> str:
    return {
        TaskStatus.RECEIVED: "需求已接收",
        TaskStatus.PARSING: "需求转换与校验",
        TaskStatus.QUEUED: "等待采集资源",
        TaskStatus.SEARCHING: "发现达人",
        TaskStatus.COLLECTING: "采集达人资料",
        TaskStatus.PERSISTING: "发布任务快照",
        TaskStatus.RETRY_WAIT: "等待重试",
        TaskStatus.WAITING_FOR_LOGIN: "等待平台登录",
        TaskStatus.WAITING_FOR_ACCOUNT: "等待正确平台账号",
        TaskStatus.WAITING_FOR_VERIFICATION: "等待安全验证",
        TaskStatus.WAITING_FOR_RESOURCE: "等待执行资源",
        TaskStatus.PAUSED_BUDGET: "预算暂停",
        TaskStatus.CANCELLING: "正在取消",
        TaskStatus.CANCELLED: "已取消",
        TaskStatus.COMPLETED: "已完成",
        TaskStatus.PARTIAL_COMPLETED: "部分完成",
        TaskStatus.FAILED_VALIDATION: "需求校验失败",
        TaskStatus.FAILED: "执行失败",
    }[status]


def allowed_actions(status: TaskStatus, task: TaskRecord | None) -> list[str]:
    actions: list[str] = []
    if status not in TERMINAL_STATES and status != TaskStatus.CANCELLING:
        actions.append("cancel")
    if status == TaskStatus.PAUSED_BUDGET:
        actions.append("continue")
    if status == TaskStatus.FAILED:
        actions.append("retry")
    if (
        status == TaskStatus.PARTIAL_COMPLETED
        and task
        and not (task.failure_reason or "").startswith("SECURITY_CHALLENGE_")
        and any(Repository.retryable(candidate) for candidate in task.checkpoint.candidates)
    ):
        actions.append("retry")
    if status == TaskStatus.FAILED_VALIDATION:
        actions.append("modify_resubmit")
    return actions


def _encode_cursor(created_at: datetime, root_task_id: str, scope: str) -> str:
    raw = json.dumps(
        {"created_at": created_at.isoformat(), "root_task_id": root_task_id, "scope": scope},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str, scope: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        data = json.loads(raw)
        if data["scope"] != scope:
            raise ValueError("cursor scope mismatch")
        return datetime.fromisoformat(data["created_at"]), str(data["root_task_id"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise CollectorError("INVALID_FORM", "INVALID_CURSOR") from exc


class ProductQueries:
    def __init__(
        self,
        repository: Repository,
        worker_health: WorkerHealthMonitor | None = None,
        *,
        intake_block_after_seconds: float = INTAKE_BLOCK_AFTER_SECONDS,
    ):
        self.repository = repository
        self.worker_health = worker_health
        self.intake_block_after_seconds = intake_block_after_seconds

    @staticmethod
    def _scope(
        status: TaskStatus | None, created_from: datetime | None, created_to: datetime | None
    ) -> str:
        value = "|".join(
            [
                status.value if status else "",
                created_from.isoformat() if created_from else "",
                created_to.isoformat() if created_to else "",
            ]
        )
        return hashlib.sha256(value.encode()).hexdigest()[:16]

    def list_tasks(
        self,
        *,
        status: TaskStatus | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> TaskPage:
        if not 1 <= limit <= 100:
            raise CollectorError("INVALID_FORM", "INVALID_PAGE_SIZE")
        scope = self._scope(status, created_from, created_to)
        clauses = [sql.SQL("true")]
        params: list[Any] = []
        if status:
            clauses.append(sql.SQL("r.state=%s"))
            params.append(status.value)
        if created_from:
            clauses.append(sql.SQL("r.created_at>=%s"))
            params.append(created_from)
        if created_to:
            clauses.append(sql.SQL("r.created_at<%s"))
            params.append(created_to)
        if cursor:
            cursor_time, cursor_id = _decode_cursor(cursor, scope)
            clauses.append(sql.SQL("(r.created_at,r.root_task_id)<(%s,%s)"))
            params.extend([cursor_time, cursor_id])
        query = (
            sql.SQL(
                """SELECT r.*,req.payload AS requirement_payload,
            req.capability_version,req.origin_root_task_id,
            u.display_name AS created_by_name,fp.payload AS plan_payload,
            cp.payload AS collection_checkpoint
            FROM root_tasks r
            LEFT JOIN requirements req ON req.root_task_id=r.root_task_id
            LEFT JOIN users u ON u.user_id=r.created_by
            LEFT JOIN filter_plans fp ON fp.root_task_id=r.root_task_id
            LEFT JOIN LATERAL (
              SELECT c.payload FROM tasks t JOIN task_checkpoints c USING(task_id)
              WHERE t.root_task_id=r.root_task_id AND t.kind='P2-1' LIMIT 1
            ) cp ON true
            WHERE """
            )
            + sql.SQL(" AND ").join(clauses)
            + sql.SQL(" ORDER BY r.created_at DESC,r.root_task_id DESC LIMIT %s")
        )
        params.append(limit + 1)
        with self.repository.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        has_more = len(rows) > limit
        visible = rows[:limit]
        items = [self._summary(row) for row in visible]
        next_cursor = None
        if has_more and visible:
            last = visible[-1]
            next_cursor = _encode_cursor(last["created_at"], str(last["root_task_id"]), scope)
        return TaskPage(items=items, next_cursor=next_cursor)

    def get_task(self, root_task_id: str) -> TaskDetail:
        root_task_id = _validated_uuid(root_task_id, "TASK_NOT_FOUND")
        with self.repository.connect() as conn:
            row = conn.execute(
                """SELECT r.*,req.payload AS requirement_payload,
                req.capability_version,req.origin_root_task_id,
                u.display_name AS created_by_name,fp.payload AS plan_payload,
                cp.payload AS collection_checkpoint,p1.payload AS intake_checkpoint,
                idp.sent AS intake_sent,idp.created_at AS intake_created_at,
                df.action AS dispatch_failure_action
                FROM root_tasks r
                LEFT JOIN requirements req ON req.root_task_id=r.root_task_id
                LEFT JOIN users u ON u.user_id=r.created_by
                LEFT JOIN filter_plans fp ON fp.root_task_id=r.root_task_id
                LEFT JOIN intake_dispatches idp ON idp.root_task_id=r.root_task_id
                LEFT JOIN LATERAL (
                  SELECT c.payload FROM tasks t JOIN task_checkpoints c USING(task_id)
                  WHERE t.root_task_id=r.root_task_id AND t.kind='P2-1' LIMIT 1
                ) cp ON true
                LEFT JOIN LATERAL (
                  SELECT c.payload FROM tasks t JOIN task_checkpoints c USING(task_id)
                  WHERE t.root_task_id=r.root_task_id AND t.kind='P1' LIMIT 1
                ) p1 ON true
                LEFT JOIN LATERAL (
                  SELECT a.action FROM audit_logs a
                  WHERE a.root_task_id=r.root_task_id AND a.action LIKE %s
                  ORDER BY a.created_at DESC LIMIT 1
                ) df ON true
                WHERE r.root_task_id=%s""",
                (DISPATCH_FAILURE_PREFIX + "%", root_task_id),
            ).fetchone()
        if not row:
            raise CollectorError("INVALID_FORM", "TASK_NOT_FOUND")
        summary = self._summary(row)
        root_payload = row["payload"]
        intake_checkpoint = row.get("intake_checkpoint") or {}
        errors = intake_checkpoint.get("final_error") or root_payload.get("field_errors") or []
        return TaskDetail(
            **summary.model_dump(),
            requirement=RequirementForm.model_validate(row["requirement_payload"])
            if row["requirement_payload"]
            else None,
            capability_version=row["capability_version"]
            or (row["plan_payload"] or {}).get("capability_version"),
            plan=FilterPlan.model_validate(row["plan_payload"]) if row["plan_payload"] else None,
            field_errors=[FieldError.model_validate(error) for error in errors],
            origin_root_task_id=str(row["origin_root_task_id"])
            if row["origin_root_task_id"]
            else None,
            challenge=self._challenge_summary(self._task_record(row)),
            intake=self._intake_progress(row),
        )

    def _intake_progress(self, row: dict[str, Any]) -> IntakeProgress | None:
        """Explain an intake-stage task that has not been picked up yet.

        Only the intake stage is described; once the task is QUEUED or terminal the dispatch row
        is history and the detail payload stays unchanged.
        """
        status = TaskStatus(row["state"])
        sent = row.get("intake_sent")
        if status not in INTAKE_STAGE_STATES or sent is None:
            return None
        created_at = row.get("intake_created_at")
        pending = (
            max(0.0, (utcnow() - created_at).total_seconds()) if created_at is not None else None
        )
        health = self.worker_health.intake_health(INTAKE_QUEUE) if self.worker_health else None
        consumer_alive = health.alive if health else None
        failure_action = row.get("dispatch_failure_action")
        dispatch_error = (
            failure_action.split(":", 1)[1]
            if isinstance(failure_action, str) and ":" in failure_action
            else (failure_action or None)
        )
        blocked_reason: str | None = None
        blocked_seconds: float | None = None
        stale = pending is not None and pending >= self.intake_block_after_seconds
        if not sent:
            if failure_action:
                blocked_reason = "INTAKE_DISPATCH_FAILING"
                blocked_seconds = pending
            elif stale:
                # Deliberately independent of the coarse poller signal: a live loop dispatches in
                # ~2 s, so waiting this long without a recorded dispatch failure is conclusive.
                blocked_reason = "INTAKE_WORKER_UNAVAILABLE"
                blocked_seconds = pending
        return IntakeProgress(
            sent=bool(sent),
            pending_seconds=pending,
            consumer_alive=consumer_alive,
            consumer_checked_at=health.checked_at if health else None,
            observed_fresh_pollers=health.fresh_pollers if health else None,
            dispatch_error=dispatch_error,
            blocked_reason=blocked_reason,
            blocked_seconds=blocked_seconds,
        )

    @staticmethod
    def _challenge_summary(task: TaskRecord | None) -> ChallengeSummary | None:
        if not task or not task.checkpoint.challenge_count:
            return None
        cp = task.checkpoint
        waiting_seconds = (
            max(0, int((utcnow() - cp.challenge_wait_started_at).total_seconds()))
            if cp.challenge_wait_started_at
            else 0
        )
        terminal_reason = (
            task.failure_reason
            if (task.failure_reason or "").startswith("SECURITY_CHALLENGE_")
            else None
        )
        terminal_messages = {
            "SECURITY_CHALLENGE_LIMIT": "安全验证次数已达到保护上限，系统已停止继续请求。",
            "SECURITY_CHALLENGE_TIMEOUT": (
                "等待安全验证超过 15 分钟，系统已保护现有结果并停止任务。"
            ),
            "SECURITY_CHALLENGE_SESSION_INVALID": "验证后登录状态已失效，系统未继续采集。",
            "SECURITY_CHALLENGE_ACCOUNT_MISMATCH": (
                "验证后的星图账号与任务绑定账号不一致，系统未继续采集。"
            ),
            "SECURITY_CHALLENGE_UNKNOWN": "页面安全状态无法确认，系统已停止继续请求。",
        }
        completed = sum(candidate.state == "done" for candidate in cp.candidates)
        return ChallengeSummary(
            state=cp.challenge_state.value if cp.challenge_state else "DETECTED",
            challenge_type=cp.challenge_type.value if cp.challenge_type else None,
            first_detected_at=cp.challenge_first_detected_at,
            last_detected_at=cp.challenge_last_detected_at,
            wait_started_at=cp.challenge_wait_started_at,
            last_recovered_at=cp.challenge_last_recovered_at,
            detected_count=cp.challenge_count,
            recovery_count=cp.challenge_recovery_count,
            current_creator_id=cp.challenge_current_creator,
            completed_creator_count=completed,
            remaining_creator_count=max(0, task.plan.target_count - task.valid_count),
            waiting_seconds=waiting_seconds,
            account_matches=(
                False
                if terminal_reason == "SECURITY_CHALLENGE_ACCOUNT_MISMATCH"
                else True
                if cp.challenge_state == "VERIFIED"
                else None
            ),
            requires_user_action=task.state == TaskStatus.WAITING_FOR_VERIFICATION,
            monitoring=task.state == TaskStatus.WAITING_FOR_VERIFICATION,
            terminal_reason=terminal_reason,
            terminal_message=terminal_messages.get(terminal_reason or ""),
            delivered_result=f"已保留 {task.valid_count} 位达人及其已持久数据",
        )

    @staticmethod
    def _task_record(row: dict[str, Any]) -> TaskRecord | None:
        checkpoint = row.get("collection_checkpoint")
        payload = row["payload"]
        if not checkpoint or "task_id" not in payload:
            return None
        return TaskRecord.model_validate({**payload, "checkpoint": checkpoint})

    def _summary(self, row: dict[str, Any]) -> TaskSummary:
        status = TaskStatus(row["state"])
        task = self._task_record(row)
        requirement = row.get("requirement_payload")
        if task:
            counts = TaskCounts(
                target_count=task.plan.target_count,
                discovered_count=len(task.checkpoint.candidates),
                valid_count=task.valid_count,
                profile_complete_count=task.profile_complete_count,
                featured_complete_count=task.featured_complete_count,
                failed_count=sum(
                    candidate.state == "failed" for candidate in task.checkpoint.candidates
                ),
            )
            keyword = next(
                (
                    str(item.value)
                    for item in task.plan.filters
                    if item.field == "keyword" and isinstance(item.value, str)
                ),
                None,
            )
            failure = task.failure_reason
        else:
            counts = TaskCounts(
                target_count=int(
                    (requirement or {}).get("target_count", row["payload"].get("target_count", 20))
                )
            )
            keyword = (requirement or {}).get("keyword")
            failure = row["payload"].get("failure_reason")
        return TaskSummary(
            root_task_id=str(row["root_task_id"]),
            status=status,
            stage=task_stage(status),
            version=int(row["version"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            created_by=str(row["created_by"]) if row.get("created_by") else None,
            created_by_name=row.get("created_by_name"),
            source="product" if row.get("requirement_payload") else "internal_acceptance",
            keyword=keyword,
            counts=counts,
            allowed_actions=allowed_actions(status, task),
            failure_reason=failure,
        )

    @staticmethod
    def _collect_workflow_started(conn: Any, root_task_id: str, segment: int) -> bool:
        """Whether a P2 collection workflow was actually started for this task segment.

        Only a recorded start moment proves a collection process can be holding the task. A
        dispatch row created but not yet started (no start moment) must stay cancellable by the
        API, otherwise a task parked in QUEUED can never be withdrawn while the P2 worker is down.
        """

        row = conn.execute(
            """SELECT workflow_started_at FROM task_dispatches
            WHERE root_task_id=%s AND segment=%s""",
            (root_task_id, segment),
        ).fetchone()
        return bool(row and row["workflow_started_at"])

    def command(
        self,
        root_task_id: str,
        action: Literal["cancel", "continue", "retry"],
        *,
        expected_version: int,
        user_id: str,
        idempotency_key: str,
    ) -> TaskDetail:
        root_task_id = _validated_uuid(root_task_id, "TASK_NOT_FOUND")
        if not idempotency_key.strip() or len(idempotency_key) > 200:
            raise CollectorError("INVALID_FORM", "INVALID_IDEMPOTENCY_KEY")
        actor = "product:" + user_id
        operation = "product.task." + action
        digest = hashlib.sha256(f"{root_task_id}:{action}:{expected_version}".encode()).hexdigest()
        with self.repository.connect() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"{user_id}:{operation}:{idempotency_key}",),
            )
            old = conn.execute(
                """SELECT digest FROM idempotency_records
                WHERE actor=%s AND operation=%s AND key=%s""",
                (actor, operation, idempotency_key),
            ).fetchone()
            if old:
                if old["digest"] != digest:
                    raise CollectorError("INVALID_FORM", "IDEMPOTENCY_CONFLICT")
                return self.get_task(root_task_id)
            row = conn.execute(
                "SELECT * FROM root_tasks WHERE root_task_id=%s FOR UPDATE", (root_task_id,)
            ).fetchone()
            if not row:
                raise CollectorError("INVALID_FORM", "TASK_NOT_FOUND")
            if int(row["version"]) != expected_version:
                raise CollectorError("INVALID_FORM", "STATE_VERSION_CONFLICT")
            status = TaskStatus(row["state"])
            payload = row["payload"]
            if "task_id" not in payload:
                if action == "cancel" and status in {TaskStatus.RECEIVED, TaskStatus.PARSING}:
                    payload = {**payload, "failure_reason": "TASK_CANCELLED"}
                    conn.execute(
                        """UPDATE root_tasks SET state='CANCELLED',version=version+1,payload=%s,
                        updated_at=now() WHERE root_task_id=%s""",
                        (Jsonb(payload), root_task_id),
                    )
                elif action == "retry" and status == TaskStatus.FAILED:
                    checkpoint = conn.execute(
                        """SELECT c.task_id,c.payload,c.revision FROM tasks t
                        JOIN task_checkpoints c USING(task_id)
                        WHERE t.root_task_id=%s AND t.kind='P1' FOR UPDATE OF c""",
                        (root_task_id,),
                    ).fetchone()
                    if not checkpoint:
                        raise CollectorError("STORAGE_UNAVAILABLE", "CHECKPOINT_NOT_FOUND")
                    intake = P1WorkflowState.model_validate(checkpoint["payload"])
                    intake = intake.model_copy(
                        update={
                            "retry_cycle": intake.retry_cycle + 1,
                            "attempt_count": 0,
                            "candidate_plan_json": None,
                            "candidate_plan": None,
                            "schema_errors": [],
                            "business_errors": [],
                            "model_run_ids": [],
                            "final_plan": None,
                            "final_error": [],
                            "outcome": "pending",
                        }
                    )
                    payload = {
                        **payload,
                        "stage": "intake",
                        "field_errors": [],
                        "failure_reason": None,
                    }
                    conn.execute(
                        """UPDATE task_checkpoints SET revision=%s,payload=%s
                        WHERE task_id=%s""",
                        (
                            int(checkpoint["revision"]) + 1,
                            Jsonb(intake.model_dump(mode="json")),
                            checkpoint["task_id"],
                        ),
                    )
                    conn.execute(
                        """UPDATE root_tasks SET state='RECEIVED',version=version+1,payload=%s,
                        updated_at=now() WHERE root_task_id=%s""",
                        (Jsonb(payload), root_task_id),
                    )
                    conn.execute(
                        """UPDATE intake_dispatches SET sent=false,workflow_id=%s,
                        updated_at=now() WHERE root_task_id=%s""",
                        (f"intake/{root_task_id}/{intake.retry_cycle}", root_task_id),
                    )
                else:
                    raise CollectorError("INVALID_FORM", "ACTION_NOT_ALLOWED")
            else:
                checkpoint = conn.execute(
                    "SELECT payload FROM task_checkpoints WHERE task_id=%s FOR UPDATE",
                    (payload["task_id"],),
                ).fetchone()
                if not checkpoint:
                    raise CollectorError("STORAGE_UNAVAILABLE", "CHECKPOINT_NOT_FOUND")
                task = TaskRecord.model_validate({**payload, "checkpoint": checkpoint["payload"]})
                if action == "cancel":
                    if task.state in TERMINAL_STATES or task.state == TaskStatus.CANCELLING:
                        raise CollectorError("INVALID_FORM", "ACTION_NOT_ALLOWED")
                    # A collection process can only be holding this task if its workflow was
                    # started. When no dispatch for it was ever started (sent=false and no
                    # recorded start), nothing can observe the cancellation, so parking the task in
                    # CANCELLING would strand it forever whenever the P2 worker is not running.
                    # Terminalise those here; anything already dispatched stays CANCELLING and is
                    # finalised by the P2 dispatch loop, which is the only layer that can prove
                    # whether a collection workflow is still running.
                    if self._collect_workflow_started(conn, root_task_id, task.segment):
                        task.state = TaskStatus.CANCELLING
                    else:
                        task.state = TaskStatus.CANCELLED
                        task.failure_reason = "TASK_CANCELLED"
                else:
                    expected_state = (
                        {TaskStatus.PAUSED_BUDGET}
                        if action == "continue"
                        else {TaskStatus.FAILED, TaskStatus.PARTIAL_COMPLETED}
                    )
                    if task.state not in expected_state:
                        raise CollectorError("INVALID_FORM", "ACTION_NOT_ALLOWED")
                    if (
                        action == "retry"
                        and task.state == TaskStatus.PARTIAL_COMPLETED
                        and not any(
                            Repository.retryable(candidate)
                            for candidate in task.checkpoint.candidates
                        )
                    ):
                        raise CollectorError("INVALID_FORM", "NO_RETRYABLE_FAILURE")
                    task.segment += 1
                    task.attempt_id = uid()
                    task.state = TaskStatus.QUEUED
                    task.failure_reason = None
                    task.checkpoint.active_seconds = 0
                    task.checkpoint.scanned_ids = []
                    for candidate in task.checkpoint.candidates:
                        if Repository.retryable(candidate):
                            candidate.state = "pending"
                    conn.execute(
                        """INSERT INTO task_attempts(attempt_id,root_task_id,segment)
                        VALUES(%s,%s,%s)""",
                        (task.attempt_id, root_task_id, task.segment),
                    )
                    conn.execute(
                        """INSERT INTO task_dispatches(root_task_id,segment,workflow_id,sent)
                        VALUES(%s,%s,%s,false)""",
                        (root_task_id, task.segment, f"collect/{root_task_id}"),
                    )
                task.version += 1
                task.checkpoint.revision += 1
                conn.execute(
                    """UPDATE root_tasks SET state=%s,version=%s,payload=%s,updated_at=now()
                    WHERE root_task_id=%s""",
                    (
                        task.state,
                        task.version,
                        Jsonb(task.model_dump(mode="json", exclude={"checkpoint"})),
                        root_task_id,
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
            conn.execute(
                """INSERT INTO idempotency_records(actor,operation,key,digest,root_task_id,
                response_payload) VALUES(%s,%s,%s,%s,%s,%s)""",
                (
                    actor,
                    operation,
                    idempotency_key,
                    digest,
                    root_task_id,
                    Jsonb({"root_task_id": root_task_id, "accepted": True}),
                ),
            )
            conn.execute(
                """INSERT INTO audit_logs(root_task_id,actor,actor_user_id,action)
                VALUES(%s,%s,%s,%s)""",
                (root_task_id, actor, user_id, action),
            )
        return self.get_task(root_task_id)

    def list_creators(
        self, root_task_id: str, *, cursor: str | None = None, limit: int = 20
    ) -> CreatorPage:
        root_task_id = _validated_uuid(root_task_id, "TASK_NOT_FOUND")
        if not 1 <= limit <= 100:
            raise CollectorError("INVALID_FORM", "INVALID_PAGE_SIZE")
        after = -1
        if cursor:
            try:
                data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
                if data["root_task_id"] != root_task_id:
                    raise ValueError("task mismatch")
                after = int(data["first_position"])
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                raise CollectorError("INVALID_FORM", "INVALID_CURSOR") from exc
        with self.repository.connect() as conn:
            root = conn.execute(
                "SELECT payload FROM root_tasks WHERE root_task_id=%s", (root_task_id,)
            ).fetchone()
            if not root:
                raise CollectorError("INVALID_FORM", "TASK_NOT_FOUND")
            rows = conn.execute(
                """SELECT tc.creator_id,tc.first_position,pc.platform_creator_id,
                s.snapshot_id,s.payload,s.created_at
                FROM task_creators tc JOIN platform_creators pc USING(creator_id)
                LEFT JOIN creator_snapshots s ON s.snapshot_id=tc.latest_snapshot_id
                AND s.root_task_id=tc.root_task_id AND s.creator_id=tc.creator_id
                WHERE tc.root_task_id=%s AND tc.valid=true AND tc.first_position>%s
                ORDER BY tc.first_position LIMIT %s""",
                (root_task_id, after, limit + 1),
            ).fetchall()
            checkpoint = None
            if "task_id" in root["payload"]:
                checkpoint = conn.execute(
                    "SELECT payload FROM task_checkpoints WHERE task_id=%s",
                    (root["payload"]["task_id"],),
                ).fetchone()
        has_more = len(rows) > limit
        visible = rows[:limit]
        items: list[CreatorSummary] = []
        for row in visible:
            if row["snapshot_id"]:
                payload = row["payload"]
                view_kind: Literal["draft", "published"] = "published"
                observed_at = row["created_at"]
            else:
                candidate = self._draft_candidate(
                    (checkpoint or {}).get("payload", {}), str(row["platform_creator_id"])
                )
                payload = candidate or {}
                view_kind = "draft"
                observed_at = None
            items.append(
                CreatorSummary(
                    creator_id=str(row["creator_id"]),
                    platform_creator_id=str(row["platform_creator_id"]),
                    first_position=int(row["first_position"]),
                    view_kind=view_kind,
                    snapshot_id=str(row["snapshot_id"]) if row["snapshot_id"] else None,
                    observed_at=observed_at,
                    payload=payload,
                )
            )
        next_cursor = None
        if has_more and visible:
            raw = json.dumps(
                {
                    "root_task_id": root_task_id,
                    "first_position": visible[-1]["first_position"],
                },
                separators=(",", ":"),
            ).encode()
            next_cursor = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        return CreatorPage(items=items, next_cursor=next_cursor)

    @staticmethod
    def _draft_candidate(
        checkpoint: dict[str, Any], platform_creator_id: str
    ) -> dict[str, Any] | None:
        for candidate in checkpoint.get("candidates", []):
            if (
                isinstance(candidate, dict)
                and candidate.get("ref", {}).get("platform_creator_id") == platform_creator_id
            ):
                return cast(dict[str, Any], candidate)
        return None

    def get_creator(self, root_task_id: str, creator_id: str) -> CreatorSummary:
        root_task_id = _validated_uuid(root_task_id, "TASK_NOT_FOUND")
        creator_id = _validated_uuid(creator_id, "CREATOR_NOT_FOUND")
        with self.repository.connect() as conn:
            row = conn.execute(
                """SELECT tc.creator_id,tc.first_position,pc.platform_creator_id,
                s.snapshot_id,s.payload,s.created_at,
                cp.payload AS collection_checkpoint
                FROM root_tasks r
                JOIN task_creators tc ON tc.root_task_id=r.root_task_id AND tc.valid=true
                JOIN platform_creators pc USING(creator_id)
                LEFT JOIN creator_snapshots s ON s.snapshot_id=tc.latest_snapshot_id
                AND s.root_task_id=tc.root_task_id AND s.creator_id=tc.creator_id
                LEFT JOIN LATERAL (
                  SELECT c.payload FROM tasks t JOIN task_checkpoints c USING(task_id)
                  WHERE t.root_task_id=r.root_task_id AND t.kind='P2-1' LIMIT 1
                ) cp ON true
                WHERE r.root_task_id=%s AND tc.creator_id=%s""",
                (root_task_id, creator_id),
            ).fetchone()
        if not row:
            # Do not distinguish a foreign creator from a missing creator.
            raise CollectorError("INVALID_FORM", "CREATOR_NOT_FOUND")
        if row["snapshot_id"]:
            payload = row["payload"]
            view_kind: Literal["draft", "published"] = "published"
            observed_at = row["created_at"]
        else:
            payload = (
                self._draft_candidate(
                    row["collection_checkpoint"] or {}, str(row["platform_creator_id"])
                )
                or {}
            )
            view_kind = "draft"
            observed_at = None
        return CreatorSummary(
            creator_id=str(row["creator_id"]),
            platform_creator_id=str(row["platform_creator_id"]),
            first_position=int(row["first_position"]),
            view_kind=view_kind,
            snapshot_id=str(row["snapshot_id"]) if row["snapshot_id"] else None,
            observed_at=observed_at,
            payload=payload,
        )

    def contents(
        self,
        root_task_id: str,
        creator_id: str,
        collection_type: Literal["excellent_reach", "excellent_seeding"],
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 100:
            raise CollectorError("INVALID_FORM", "INVALID_PAGE_SIZE")
        creator = self.get_creator(root_task_id, creator_id)
        after = -1
        if cursor:
            try:
                data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
                expected_scope = {
                    "root_task_id": root_task_id,
                    "creator_id": creator_id,
                    "collection_type": collection_type,
                    "snapshot_id": creator.snapshot_id,
                }
                if any(data.get(key) != value for key, value in expected_scope.items()):
                    raise ValueError("content cursor scope mismatch")
                after = int(data["position"])
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                raise CollectorError("INVALID_FORM", "INVALID_CURSOR") from exc
        if creator.view_kind == "draft":
            payload = cast(dict[str, Any], creator.payload)
            collections = cast(dict[str, Any], payload.get("collections") or {})
            collection = cast(dict[str, Any], collections.get(collection_type) or {})
            cards = [
                card
                for card in cast(list[dict[str, Any]], collection.get("cards", []))
                if int(card.get("position", -1)) > after
            ][: limit + 1]
            visible = cards[:limit]
            return {
                "view_kind": "draft",
                "collection_type": collection_type,
                "status": collection.get("status", "NOT_ATTEMPTED"),
                "cards": visible,
                "next_cursor": self._content_cursor(
                    root_task_id,
                    creator_id,
                    collection_type,
                    creator.snapshot_id,
                    int(visible[-1]["position"]),
                )
                if len(cards) > limit and visible
                else None,
            }
        assert creator.snapshot_id
        with self.repository.connect() as conn:
            observation = conn.execute(
                """SELECT f.collection_observation_id,f.status,f.observed_at,f.coverage_gaps
                FROM snapshot_collections sc JOIN featured_collections f
                ON f.collection_observation_id=sc.collection_observation_id
                WHERE sc.creator_snapshot_id=%s AND f.root_task_id=%s AND f.creator_id=%s
                AND sc.collection_type=%s""",
                (creator.snapshot_id, root_task_id, creator_id, collection_type),
            ).fetchone()
            if not observation:
                return {
                    "view_kind": "published",
                    "snapshot_id": creator.snapshot_id,
                    "collection_type": collection_type,
                    "status": "NOT_ATTEMPTED",
                    "cards": [],
                }
            cards = conn.execute(
                """SELECT card_id,position,cover_status,truncated_fields,payload
                FROM featured_cards WHERE collection_observation_id=%s AND position>%s
                ORDER BY position LIMIT %s""",
                (observation["collection_observation_id"], after, limit + 1),
            ).fetchall()
        visible_cards = cards[:limit]
        return {
            "view_kind": "published",
            "snapshot_id": creator.snapshot_id,
            "collection_type": collection_type,
            "status": observation["status"],
            "observed_at": observation["observed_at"].isoformat(),
            "coverage_gaps": observation["coverage_gaps"],
            "cards": [dict(card) for card in visible_cards],
            "next_cursor": self._content_cursor(
                root_task_id,
                creator_id,
                collection_type,
                creator.snapshot_id,
                int(visible_cards[-1]["position"]),
            )
            if len(cards) > limit and visible_cards
            else None,
        }

    @staticmethod
    def _content_cursor(
        root_task_id: str,
        creator_id: str,
        collection_type: str,
        snapshot_id: str | None,
        position: int,
    ) -> str:
        raw = json.dumps(
            {
                "root_task_id": root_task_id,
                "creator_id": creator_id,
                "collection_type": collection_type,
                "snapshot_id": snapshot_id,
                "position": position,
            },
            separators=(",", ":"),
        ).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")
