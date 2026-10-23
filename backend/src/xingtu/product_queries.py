from __future__ import annotations

import base64
import copy
import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

from psycopg import sql
from psycopg.types.json import Jsonb

from .creator_update import reconcile_update_task
from .domain import (
    CollectorError,
    FilterPlan,
    TaskKind,
    TaskRecord,
    TaskStatus,
    uid,
    utcnow,
)
from .product_models import (
    BrowserTakeoverView,
    ChallengeSummary,
    CreatorLibraryDetail,
    CreatorLibraryHistory,
    CreatorLibraryHistoryPoint,
    CreatorLibraryPage,
    CreatorLibraryQuote,
    CreatorLibrarySummary,
    CreatorPage,
    CreatorSummary,
    CreatorVideoObservation,
    CreatorVideoPage,
    ExecutionUnitView,
    FieldError,
    IntakeProgress,
    LibraryMetric,
    ManualProbeCreator,
    P1WorkflowState,
    RequirementForm,
    TaskCounts,
    TaskDetail,
    TaskPage,
    TaskSummary,
    UpdateTargetView,
    VerificationEventView,
)
from .repository import TERMINAL_COMPLETED_AT_CLAUSE, TERMINAL_TASK_STATES, Repository
from .worker_health import INTAKE_QUEUE, WorkerHealthMonitor

# The same terminal set the task write path uses to stamp `completed_at`; kept as the query layer's
# public name because the API and result-action rules already refer to it.
TERMINAL_STATES = set(TERMINAL_TASK_STATES)
logger = logging.getLogger(__name__)

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
    def _mask_reference(value: str | None) -> str:
        if not value:
            return "未配置"
        tail = value[-4:] if len(value) > 4 else value
        return "•••" + tail

    @staticmethod
    def _browser_status(
        row: dict[str, Any],
    ) -> Literal["ONLINE", "MAINTENANCE", "STOPPED", "SUSPECTED_OFFLINE", "QUARANTINED"]:
        if row["state"] == "QUARANTINED":
            return "QUARANTINED"
        if row["browser_stopped"]:
            return "STOPPED"
        if row["lease_until"] and row["lease_until"] <= utcnow():
            return "SUSPECTED_OFFLINE"
        if row["mode"] == "maintenance":
            return "MAINTENANCE"
        return "ONLINE"

    def _execution_unit_view(self, row: dict[str, Any]) -> ExecutionUnitView:
        deadline = row.get("event_deadline_at")
        fresh_workers = int(row.get("fresh_worker_count") or 0)
        worker_history = int(row.get("worker_history_count") or 0)
        worker_status: Literal["ONLINE", "OFFLINE", "DUPLICATE", "UNKNOWN"] = (
            "DUPLICATE"
            if fresh_workers > 1
            else "ONLINE"
            if fresh_workers == 1
            else "OFFLINE"
            if worker_history
            else "UNKNOWN"
        )
        actionable_reason = row.get("event_reason") or row.get("failure_reason")
        if not actionable_reason and worker_status in {"OFFLINE", "DUPLICATE"}:
            actionable_reason = (
                "COLLECTION_WORKER_OFFLINE"
                if worker_status == "OFFLINE"
                else "DUPLICATE_COLLECTION_WORKERS"
            )
        return ExecutionUnitView(
            unit_id=row["unit_id"],
            account_label=self._mask_reference(row.get("account_ref")),
            line_label=self._mask_reference(row.get("line_ref")),
            state=row["state"],
            mode=row.get("mode"),
            allowed_task_kinds=list(row.get("allowed_task_kinds") or []),
            current_root_task_id=str(row["current_root_task_id"])
            if row.get("current_root_task_id")
            else None,
            worker_status=worker_status,
            worker_instances=fresh_workers,
            worker_last_heartbeat_at=row.get("worker_last_heartbeat_at"),
            browser_status=self._browser_status(row),
            verification_state=row.get("event_state"),
            takeover_state=row.get("takeover_state"),
            verification_deadline_at=deadline,
            last_heartbeat_at=row.get("last_heartbeat_at"),
            actionable_reason=actionable_reason,
        )

    def list_execution_units(self) -> list[ExecutionUnitView]:
        with self.repository.connect() as conn:
            rows = conn.execute(
                """SELECT u.*,e.state AS event_state,e.reason AS event_reason,
                e.deadline_at AS event_deadline_at,t.state AS takeover_state,
                wh.fresh_worker_count,wh.worker_history_count,wh.worker_last_heartbeat_at
                FROM execution_units u
                LEFT JOIN LATERAL (
                  SELECT * FROM verification_events WHERE unit_id=u.unit_id
                  AND state IN ('OPEN','ACKNOWLEDGED') ORDER BY detected_at DESC LIMIT 1
                ) e ON true
                LEFT JOIN LATERAL (
                  SELECT * FROM browser_takeover_sessions WHERE unit_id=u.unit_id
                  AND state IN ('REQUESTED','ACTIVE','VERIFYING') ORDER BY created_at DESC LIMIT 1
                ) t ON true
                LEFT JOIN LATERAL (
                  SELECT
                    count(*) FILTER (WHERE stopped_at IS NULL
                      AND last_heartbeat_at > now()-interval '45 seconds') AS fresh_worker_count,
                    count(*) AS worker_history_count,
                    max(last_heartbeat_at) AS worker_last_heartbeat_at
                  FROM execution_unit_workers WHERE unit_id=u.unit_id
                ) wh ON true ORDER BY u.unit_id"""
            ).fetchall()
            return [self._execution_unit_view(dict(row)) for row in rows]

    def execution_unit(self, unit_id: str) -> ExecutionUnitView:
        rows = [row for row in self.list_execution_units() if row.unit_id == unit_id]
        if not rows:
            raise CollectorError("INVALID_FORM", "EXECUTION_UNIT_NOT_FOUND")
        return rows[0]

    def verification_events(self, *, open_only: bool = True) -> list[VerificationEventView]:
        events = self.repository.list_verification_events(open_only=open_only)
        now = utcnow()
        return [
            VerificationEventView(
                event_id=str(row["event_id"]),
                unit_id=row["unit_id"],
                root_task_id=str(row["root_task_id"]),
                state=row["state"],
                reason=row["reason"],
                detected_at=row["detected_at"],
                last_detected_at=row["last_detected_at"],
                deadline_at=row["deadline_at"],
                reappearance_count=row["reappearance_count"],
                remaining_seconds=max(0, int((row["deadline_at"] - now).total_seconds())),
            )
            for row in events
        ]

    def takeover_view(
        self,
        row: dict[str, Any],
        *,
        viewer_url: str | None = None,
        access_mode: Literal["LOCAL_WINDOW", "REMOTE_VIEWER"] = "LOCAL_WINDOW",
        operator_message: str | None = None,
    ) -> BrowserTakeoverView:
        probes: list[ManualProbeCreator] = []
        try:
            task = self.repository.get(str(row["root_task_id"]))
        except CollectorError:
            task = None
        if task:
            for candidate in task.checkpoint.candidates:
                if candidate.state not in {"done", "collecting"}:
                    probes.append(
                        ManualProbeCreator(
                            platform_creator_id=candidate.ref.platform_creator_id,
                            display_name=None,
                            state=candidate.state,
                        )
                    )
                if len(probes) == 3:
                    break
        return BrowserTakeoverView(
            takeover_id=str(row["takeover_id"]),
            unit_id=row["unit_id"],
            root_task_id=str(row["root_task_id"]),
            state=row["state"],
            expires_at=row["expires_at"],
            failure_reason=row.get("failure_reason"),
            viewer_url=viewer_url,
            access_mode=access_mode,
            operator_message=operator_message,
            manual_probe_creators=probes,
        )

    @staticmethod
    def _scope(
        status: TaskStatus | None,
        created_from: datetime | None,
        created_to: datetime | None,
        task_kind: TaskKind | None = None,
    ) -> str:
        value = "|".join(
            [
                status.value if status else "",
                task_kind.value if task_kind else "",
                created_from.isoformat() if created_from else "",
                created_to.isoformat() if created_to else "",
            ]
        )
        return hashlib.sha256(value.encode()).hexdigest()[:16]

    def list_tasks(
        self,
        *,
        status: TaskStatus | None = None,
        task_kind: TaskKind | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> TaskPage:
        if not 1 <= limit <= 100:
            raise CollectorError("INVALID_FORM", "INVALID_PAGE_SIZE")
        scope = self._scope(status, created_from, created_to, task_kind)
        clauses = [sql.SQL("true")]
        params: list[Any] = []
        if status:
            clauses.append(sql.SQL("r.state=%s"))
            params.append(status.value)
        if task_kind:
            clauses.append(sql.SQL("r.task_kind=%s"))
            params.append(task_kind.value)
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
        task = self._task_record(row)
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
            challenge=self._challenge_summary(task),
            intake=self._intake_progress(row),
            update_targets=self._update_targets(task),
        )

    @staticmethod
    def _update_targets(task: TaskRecord | None) -> list[UpdateTargetView]:
        if task is None or task.plan is not None:
            return []
        candidates = {
            candidate.ref.platform_creator_id: candidate for candidate in task.checkpoint.candidates
        }
        targets: list[UpdateTargetView] = []
        for target in task.update_targets:
            candidate = candidates.get(target.platform_creator_id)
            targets.append(
                UpdateTargetView(
                    creator_id=target.creator_id,
                    platform_creator_id=target.platform_creator_id,
                    first_position=target.first_position,
                    state=candidate.state if candidate else "pending",
                    failure_reason=candidate.failure_reason if candidate else None,
                )
            )
        return targets

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
            remaining_creator_count=max(0, task.target_count - task.valid_count),
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
                target_count=task.target_count,
                discovered_count=len(task.checkpoint.candidates),
                valid_count=task.valid_count,
                profile_complete_count=task.profile_complete_count,
                featured_complete_count=task.featured_complete_count,
                failed_count=sum(
                    candidate.state == "failed" for candidate in task.checkpoint.candidates
                ),
            )
            keyword = (
                next(
                    (
                        str(item.value)
                        for item in task.plan.filters
                        if item.field == "keyword" and isinstance(item.value, str)
                    ),
                    None,
                )
                if task.plan is not None
                else None
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
            task_kind=TaskKind(row.get("task_kind") or "collection"),
            status=status,
            stage=task_stage(status),
            version=int(row["version"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row.get("completed_at"),
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
        terminal_update = False
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
                        updated_at=now()"""
                        + TERMINAL_COMPLETED_AT_CLAUSE
                        + """ WHERE root_task_id=%s""",
                        (Jsonb(payload), True, root_task_id),
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
                terminal_update = (
                    task.task_kind != TaskKind.COLLECTION and task.state in TERMINAL_STATES
                )
                task.version += 1
                task.checkpoint.revision += 1
                conn.execute(
                    """UPDATE root_tasks SET state=%s,version=%s,payload=%s,updated_at=now()"""
                    + TERMINAL_COMPLETED_AT_CLAUSE
                    + """ WHERE root_task_id=%s""",
                    (
                        task.state,
                        task.version,
                        Jsonb(task.model_dump(mode="json", exclude={"checkpoint"})),
                        task.state in TERMINAL_STATES,
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
        if terminal_update:
            try:
                reconcile_update_task(self.repository, root_task_id)
            except Exception as exc:  # noqa: BLE001 - the command already committed
                logger.warning(
                    "update schedule reconcile failed root=%s: %s", root_task_id, type(exc).__name__
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

    @staticmethod
    def _creator_library_scope(filters: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(filters, sort_keys=True, default=str, separators=(",", ":")).encode()
        ).hexdigest()[:16]

    @staticmethod
    def _library_cursor(cursor: str, scope: str) -> int:
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            data = json.loads(raw)
            if data["scope"] != scope or not isinstance(data["offset"], int):
                raise ValueError("library cursor scope mismatch")
            return data["offset"]
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise CollectorError("INVALID_FORM", "INVALID_CURSOR") from exc

    @staticmethod
    def _metric(
        row: dict[str, Any],
        *,
        column: str,
        source_key: str,
        raw_column: str | None = None,
        approximate_column: str | None = None,
    ) -> LibraryMetric:
        sources = row.get("field_sources") or {}
        source = (
            sources.get(source_key)
            or sources.get(
                {
                    "followers_count": "basic.followers",
                    "monthly_deep_users_count": "basic.monthly_deep_users",
                    "monthly_connected_users_count": "fans.monthly_connected_users",
                    "monthly_follower_growth_rate_raw": "basic.monthly_follower_growth_rate",
                    "interaction_rate_value_raw": "spread.interaction_rate",
                    "completion_rate_value_raw": "spread.completion_rate",
                    "play_median_value_raw": "spread.item_rate_metrics",
                    "average_duration_value_raw": "spread.average_duration",
                    "average_likes_value_raw": "spread.average_likes",
                    "average_comments_value_raw": "spread.average_comments",
                    "average_shares_value_raw": "spread.average_shares",
                    "expected_cpm_21_60_raw": "spread.expected_cpm",
                    "expected_cpm_60_plus_raw": "spread.expected_cpm",
                    "expected_cpe_21_60_raw": "spread.expected_cpe",
                    "expected_cpe_60_plus_raw": "spread.expected_cpe",
                }.get(source_key, "")
            )
            or {}
        )
        value = row.get(column)
        raw = row.get(raw_column) if raw_column else None
        if raw is None and value is not None:
            raw = str(value)
        return LibraryMetric(
            value=value,
            raw_value=raw,
            unit=source.get("unit"),
            is_approximate=bool(row.get(approximate_column)) if approximate_column else False,
            status=source.get("status") or ("COLLECTED" if value is not None else "NOT_AVAILABLE"),
            observed_at=source.get("observed_at"),
        )

    @classmethod
    def _creator_library_summary(cls, row: dict[str, Any]) -> CreatorLibrarySummary:
        metric = cls._metric
        return CreatorLibrarySummary(
            creator_id=str(row["creator_id"]),
            platform_creator_id=row["platform_creator_id"],
            display_name=row.get("display_name"),
            avatar_uri=row.get("avatar_uri"),
            creator_type_label=row.get("creator_type_label"),
            province=row.get("province"),
            city=row.get("city"),
            industry_labels=row.get("industry_labels") or [],
            followers=metric(
                row,
                column="followers_count",
                source_key="followers_count",
                raw_column="followers_raw",
                approximate_column="followers_is_approximate",
            ),
            monthly_deep_users=metric(
                row,
                column="monthly_deep_users_count",
                source_key="monthly_deep_users_count",
                raw_column="monthly_deep_users_raw",
                approximate_column="monthly_deep_users_is_approximate",
            ),
            monthly_connected_users=metric(
                row,
                column="monthly_connected_users_count",
                source_key="monthly_connected_users_count",
            ),
            monthly_follower_growth_rate=metric(
                row,
                column="monthly_follower_growth_rate_raw",
                source_key="monthly_follower_growth_rate_raw",
            ),
            interaction_rate=metric(
                row, column="interaction_rate_value_raw", source_key="interaction_rate_value_raw"
            ),
            completion_rate=metric(
                row, column="completion_rate_value_raw", source_key="completion_rate_value_raw"
            ),
            play_median=metric(
                row, column="play_median_value_raw", source_key="play_median_value_raw"
            ),
            average_duration=metric(
                row, column="average_duration_value_raw", source_key="average_duration_value_raw"
            ),
            average_likes=metric(
                row, column="average_likes_value_raw", source_key="average_likes_value_raw"
            ),
            average_comments=metric(
                row, column="average_comments_value_raw", source_key="average_comments_value_raw"
            ),
            average_shares=metric(
                row, column="average_shares_value_raw", source_key="average_shares_value_raw"
            ),
            expected_cpm_21_60=metric(
                row, column="expected_cpm_21_60_raw", source_key="expected_cpm_21_60_raw"
            ),
            expected_cpm_60_plus=metric(
                row, column="expected_cpm_60_plus_raw", source_key="expected_cpm_60_plus_raw"
            ),
            expected_cpe_21_60=metric(
                row, column="expected_cpe_21_60_raw", source_key="expected_cpe_21_60_raw"
            ),
            expected_cpe_60_plus=metric(
                row, column="expected_cpe_60_plus_raw", source_key="expected_cpe_60_plus_raw"
            ),
            profile_complete=bool(row["profile_complete"]),
            pipeline_complete=bool(row["pipeline_complete"]),
            data_updated_at=row.get("data_updated_at"),
        )

    def list_creator_library(
        self,
        *,
        industry: str | None = None,
        creator_type: str | None = None,
        province: str | None = None,
        city: str | None = None,
        followers_min: float | None = None,
        followers_max: float | None = None,
        monthly_growth_min: float | None = None,
        monthly_growth_max: float | None = None,
        interaction_min: float | None = None,
        interaction_max: float | None = None,
        completion_min: float | None = None,
        completion_max: float | None = None,
        expected_cpm_min: float | None = None,
        expected_cpm_max: float | None = None,
        expected_cpe_min: float | None = None,
        expected_cpe_max: float | None = None,
        cooperation_form: str | None = None,
        complete_only: bool = False,
        sort: str = "updated_at",
        direction: Literal["asc", "desc"] = "desc",
        cursor: str | None = None,
        limit: int = 20,
    ) -> CreatorLibraryPage:
        if not 1 <= limit <= 100:
            raise CollectorError("INVALID_FORM", "INVALID_PAGE_SIZE")
        sort_columns = {
            "updated_at": "data_updated_at",
            "followers": "followers_count",
            "monthly_growth": "monthly_follower_growth_rate_raw",
            "interaction": "interaction_rate_value_raw",
            "completion": "completion_rate_value_raw",
            "expected_cpm": "expected_cpm_21_60_raw",
            "expected_cpe": "expected_cpe_21_60_raw",
        }
        if sort not in sort_columns:
            raise CollectorError("INVALID_FORM", "INVALID_CREATOR_LIBRARY_SORT")
        filters = {
            "industry": industry,
            "creator_type": creator_type,
            "province": province,
            "city": city,
            "followers_min": followers_min,
            "followers_max": followers_max,
            "monthly_growth_min": monthly_growth_min,
            "monthly_growth_max": monthly_growth_max,
            "interaction_min": interaction_min,
            "interaction_max": interaction_max,
            "completion_min": completion_min,
            "completion_max": completion_max,
            "expected_cpm_min": expected_cpm_min,
            "expected_cpm_max": expected_cpm_max,
            "expected_cpe_min": expected_cpe_min,
            "expected_cpe_max": expected_cpe_max,
            "cooperation_form": cooperation_form,
            "complete_only": complete_only,
            "sort": sort,
            "direction": direction,
        }
        scope = self._creator_library_scope(filters)
        offset = self._library_cursor(cursor, scope) if cursor else 0
        clauses = [sql.SQL("true")]
        params: list[Any] = []
        simple = {
            "creator_type": "c.creator_type_label",
            "province": "c.province",
            "city": "c.city",
        }
        for key, column in simple.items():
            if filters[key]:
                clauses.append(sql.SQL(column + "=%s"))
                params.append(filters[key])
        if industry:
            clauses.append(sql.SQL("c.industry_labels ? %s"))
            params.append(industry)
        if complete_only:
            clauses.append(sql.SQL("c.profile_complete AND c.pipeline_complete"))
        numeric_ranges = (
            ("followers_count", followers_min, followers_max),
            ("monthly_follower_growth_rate_raw", monthly_growth_min, monthly_growth_max),
            ("interaction_rate_value_raw", interaction_min, interaction_max),
            ("completion_rate_value_raw", completion_min, completion_max),
            ("expected_cpm_21_60_raw", expected_cpm_min, expected_cpm_max),
            ("expected_cpe_21_60_raw", expected_cpe_min, expected_cpe_max),
        )
        for column, minimum, maximum in numeric_ranges:
            if minimum is not None:
                clauses.append(sql.SQL("c." + column + ">=%s"))
                params.append(minimum)
            if maximum is not None:
                clauses.append(sql.SQL("c." + column + "<=%s"))
                params.append(maximum)
        if cooperation_form:
            clauses.append(
                sql.SQL("""EXISTS(SELECT 1 FROM douyin_xingtu_creator_quote_observations q
                WHERE q.creator_id=c.creator_id AND q.cooperation_form=%s)""")
            )
            params.append(cooperation_form)
        order_column = sql.Identifier(sort_columns[sort])
        order_direction = sql.SQL("ASC") if direction == "asc" else sql.SQL("DESC")
        query = (
            sql.SQL("SELECT c.* FROM douyin_xingtu_creator_current c WHERE ")
            + sql.SQL(" AND ").join(clauses)
            + sql.SQL(" ORDER BY ")
            + order_column
            + sql.SQL(" ")
            + order_direction
            + sql.SQL(" NULLS LAST,c.creator_id ASC LIMIT %s OFFSET %s")
        )
        params.extend([limit + 1, offset])
        with self.repository.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        visible = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            raw = json.dumps(
                {"scope": scope, "offset": offset + limit}, separators=(",", ":")
            ).encode()
            next_cursor = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        return CreatorLibraryPage(
            items=[self._creator_library_summary(row) for row in visible], next_cursor=next_cursor
        )

    def get_creator_library(self, creator_id: str) -> CreatorLibraryDetail:
        creator_id = _validated_uuid(creator_id, "CREATOR_NOT_FOUND")
        with self.repository.connect() as conn:
            row = conn.execute(
                """SELECT c.*,si.module_statuses,pc.projection,s.payload AS latest_payload
                FROM douyin_xingtu_creator_current c
                JOIN platform_creators pc ON pc.creator_id=c.creator_id
                LEFT JOIN douyin_xingtu_creator_snapshot_index si
                  ON si.snapshot_id=c.latest_snapshot_id
                LEFT JOIN creator_snapshots s ON s.snapshot_id=c.latest_snapshot_id
                WHERE c.creator_id=%s""",
                (creator_id,),
            ).fetchone()
        if not row:
            raise CollectorError("INVALID_FORM", "CREATOR_NOT_FOUND")
        return CreatorLibraryDetail(
            **self._creator_library_summary(row).model_dump(),
            latest_snapshot_id=str(row["latest_snapshot_id"])
            if row["latest_snapshot_id"]
            else None,
            mcn_name=row.get("mcn_name"),
            introduction=row.get("introduction"),
            gender=self._gender_value(row.get("projection") or {}),
            content_theme_labels=row.get("content_theme_labels") or [],
            collected_field_count=int(row["collected_field_count"]),
            failed_field_count=int(row["failed_field_count"]),
            field_sources=row.get("field_sources") or {},
            module_statuses=row.get("module_statuses") or {},
            profile_payload=self._current_profile_payload(
                row.get("latest_payload") or {}, row.get("projection") or {}
            ),
        )

    @staticmethod
    def _gender_value(projection: dict[str, Any]) -> str | None:
        """`basic.gender` (the platform's own code) from the current projection.

        Returns the code unchanged: the backend never assigns a meaning to it.  An empty platform
        answer stays `None` (an explicit "no data"), never an empty string or a guessed label.
        """
        field = projection.get("basic.gender")
        if not isinstance(field, dict) or field.get("status") != "COLLECTED":
            return None
        value = field.get("value")
        if not isinstance(value, str) or not value.strip():
            return None
        return value.strip()

    @staticmethod
    def _current_profile_payload(
        latest_payload: dict[str, Any], projection: dict[str, Any]
    ) -> dict[str, Any]:
        """Overlay each current successful FieldObservation without changing snapshot history.

        A current profile may legitimately consist of fields observed at different times.  The
        envelopes carry those per-field observation times; the latest snapshot supplies module
        state and non-success statuses for fields without a current projection value.
        """
        profile = copy.deepcopy(latest_payload)
        modules = profile.get("modules")
        if not isinstance(modules, dict):
            return profile
        for module_key, module in modules.items():
            if not isinstance(module, dict):
                continue
            fields = module.get("fields")
            if not isinstance(fields, list):
                continue
            for index, field in enumerate(fields):
                if not isinstance(field, dict) or not isinstance(field.get("field_key"), str):
                    continue
                current = projection.get(f"{module_key}.{field['field_key']}")
                if isinstance(current, dict) and current.get("status") == "COLLECTED":
                    fields[index] = copy.deepcopy(current)
        return profile

    def creator_library_contents(
        self,
        creator_id: str,
        collection_type: Literal["excellent_reach", "excellent_seeding"],
        *,
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """The 精选集合 of a creator's **latest** snapshot, for the library entry (CD-04).

        The task entry already reads its own snapshot through `contents`.  The library entry owns no
        task id, so this read-only query resolves the creator's latest snapshot and returns the same
        card shape — including the stored cover object id and the platform share link — from the
        same `featured_collections`/`featured_cards` rows.  Nothing is written and no task scope
        leaks: the snapshot is selected by `douyin_xingtu_creator_current.latest_snapshot_id`.

        Cards are streamed from the card payload persisted at collection time, so a stale or expired
        platform CDN URL is never used as the cover source.
        """
        if not 1 <= limit <= 100:
            raise CollectorError("INVALID_FORM", "INVALID_PAGE_SIZE")
        creator_id = _validated_uuid(creator_id, "CREATOR_NOT_FOUND")
        after = -1
        if cursor:
            try:
                data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
                expected_scope = {"creator_id": creator_id, "collection_type": collection_type}
                if any(data.get(key) != value for key, value in expected_scope.items()):
                    raise ValueError("content cursor scope mismatch")
                after = int(data["position"])
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                raise CollectorError("INVALID_FORM", "INVALID_CURSOR") from exc
        with self.repository.connect() as conn:
            creator = conn.execute(
                "SELECT latest_snapshot_id FROM douyin_xingtu_creator_current WHERE creator_id=%s",
                (creator_id,),
            ).fetchone()
            if not creator:
                raise CollectorError("INVALID_FORM", "CREATOR_NOT_FOUND")
            snapshot_id = creator["latest_snapshot_id"]
            observation = conn.execute(
                """SELECT f.collection_observation_id,f.status,f.observed_at,f.coverage_gaps
                FROM snapshot_collections sc JOIN featured_collections f
                ON f.collection_observation_id=sc.collection_observation_id
                WHERE sc.creator_snapshot_id=%s AND sc.collection_type=%s""",
                (snapshot_id, collection_type),
            ).fetchone()
            if not observation:
                return {
                    "view_kind": "published",
                    "snapshot_id": str(snapshot_id),
                    "collection_type": collection_type,
                    "status": "NOT_ATTEMPTED",
                    "cards": [],
                    "next_cursor": None,
                }
            cards = conn.execute(
                """SELECT card_id,position,cover_status,truncated_fields,payload
                FROM featured_cards WHERE collection_observation_id=%s AND position>%s
                ORDER BY position LIMIT %s""",
                (observation["collection_observation_id"], after, limit + 1),
            ).fetchall()
        visible = cards[:limit]
        return {
            "view_kind": "published",
            "snapshot_id": str(snapshot_id),
            "collection_type": collection_type,
            "status": observation["status"],
            "observed_at": observation["observed_at"].isoformat(),
            "coverage_gaps": observation["coverage_gaps"],
            "cards": [dict(card) for card in visible],
            "next_cursor": self._library_content_cursor(
                creator_id, collection_type, int(visible[-1]["position"])
            )
            if len(cards) > limit and visible
            else None,
        }

    @staticmethod
    def _library_content_cursor(creator_id: str, collection_type: str, position: int) -> str:
        raw = json.dumps(
            {"creator_id": creator_id, "collection_type": collection_type, "position": position},
            separators=(",", ":"),
        ).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    def creator_library_cover_reference(
        self, creator_id: str, object_id: str
    ) -> dict[str, Any] | None:
        """Authenticated cover access for the library entry: the object must belong to this creator.

        Same shape as `Repository.cover_reference`, but scoped to a creator instead of a root task.
        Two ownership paths exist and both are checked:

        * `media_objects` → `featured_cards` → `featured_collections.creator_id` (精选集合 covers);
        * `media_objects.source_key` → `douyin_xingtu_creator_video_observations.cover_source_uri`
          → `creator_id` (the DATA-02 work covers, whose platform object key is the stable link and
          whose signed URL is short-lived).

        Returns `None` for any mismatch, so a caller cannot reach another creator's cover by
        guessing an object id.
        """
        creator_id = _validated_uuid(creator_id, "CREATOR_NOT_FOUND")
        with self.repository.connect() as conn:
            return conn.execute(
                """SELECT m.object_id,m.checksum,m.kind,m.content_type,m.byte_size,
                c.collection_observation_id,c.card_id
                FROM media_objects m
                JOIN featured_cards c ON c.cover_object_id=m.object_id
                JOIN featured_collections f
                ON f.collection_observation_id=c.collection_observation_id
                WHERE m.object_id=%s AND m.kind='cover' AND f.creator_id=%s
                UNION ALL
                SELECT m.object_id,m.checksum,m.kind,m.content_type,m.byte_size,NULL,NULL
                FROM media_objects m
                JOIN douyin_xingtu_creator_video_observations v
                  ON v.cover_source_uri=m.source_key AND v.creator_id=%s
                WHERE m.object_id=%s AND m.kind='cover' AND m.source_key IS NOT NULL
                LIMIT 1""",
                (object_id, creator_id, creator_id, object_id),
            ).fetchone()

    @staticmethod
    def _video_observation(row: dict[str, Any]) -> CreatorVideoObservation:
        return CreatorVideoObservation(
            module_key=row["module_key"],
            position=int(row["position"]),
            content_id=str(row["content_id"]) if row.get("content_id") else None,
            platform_item_id=row.get("platform_item_id"),
            platform_video_id=row.get("platform_video_id"),
            platform_author_id=row.get("platform_author_id"),
            title=row.get("title"),
            subtitle=row.get("subtitle"),
            published_at=row.get("published_at"),
            published_raw=row.get("published_raw"),
            play_count=row.get("play_count"),
            like_count=row.get("like_count"),
            comment_count=row.get("comment_count"),
            favorite_count=row.get("favorite_count"),
            share_count=row.get("share_count"),
            cover_source_uri=row.get("cover_source_uri"),
            cover_object_id=row.get("cover_object_id"),
            cover_status=row["cover_status"],
            work_url=row.get("work_url"),
            field_statuses=row.get("field_statuses") or {},
            observed_at=row["observed_at"],
        )

    def _video_page(
        self,
        conn: Any,
        creator_id: str,
        snapshot_id: str | None,
        module_key: str | None,
    ) -> CreatorVideoPage:
        """One snapshot's ordered work observations, with each cover resolved read-side.

        `cover_status` distinguishes the three states the page must not blur: the platform returned
        no cover key at all (`NOT_PROVIDED`), the key exists but no verified object is stored yet
        (`UNRESOLVED`), or the stored object is available (`STORED`).
        """
        if not snapshot_id:
            return CreatorVideoPage(
                creator_id=creator_id, snapshot_id=None, view_kind="unavailable"
            )
        clause = "" if module_key is None else " AND v.module_key=%(module_key)s"
        rows = conn.execute(
            f"""SELECT v.module_key,v.position,v.content_id,v.platform_item_id,v.platform_video_id,
            v.platform_author_id,v.title,v.subtitle,v.published_at,v.published_raw,
            v.play_count,v.like_count,v.comment_count,v.favorite_count,v.share_count,
            v.cover_source_uri,v.work_url,v.field_statuses,v.observed_at,
            m.object_id AS cover_object_id,
            CASE WHEN v.cover_source_uri IS NULL THEN 'NOT_PROVIDED'
                 WHEN m.object_id IS NOT NULL THEN 'STORED'
                 ELSE 'UNRESOLVED' END AS cover_status
            FROM douyin_xingtu_creator_video_observations v
            LEFT JOIN LATERAL (
              SELECT object_id FROM media_objects
              WHERE kind='cover' AND source_key=v.cover_source_uri
              ORDER BY created_at DESC, object_id LIMIT 1
            ) m ON true
            WHERE v.creator_id=%(creator_id)s AND v.snapshot_id=%(snapshot_id)s{clause}
            ORDER BY v.module_key,v.position""",
            {
                "creator_id": creator_id,
                "snapshot_id": snapshot_id,
                "module_key": module_key,
            },
        ).fetchall()
        return CreatorVideoPage(
            creator_id=creator_id,
            snapshot_id=snapshot_id,
            view_kind="published",
            items=[self._video_observation(row) for row in rows],
        )

    def creator_library_videos(
        self,
        creator_id: str,
        *,
        module_key: str | None = None,
        snapshot_id: str | None = None,
    ) -> CreatorVideoPage:
        """The work observations of the creator's current snapshot, or of an explicit one."""
        creator_id = _validated_uuid(creator_id, "CREATOR_NOT_FOUND")
        with self.repository.connect() as conn:
            if snapshot_id:
                snapshot_id = _validated_uuid(snapshot_id, "SNAPSHOT_NOT_FOUND")
                owned = conn.execute(
                    "SELECT 1 FROM creator_snapshots WHERE snapshot_id=%s AND creator_id=%s",
                    (snapshot_id, creator_id),
                ).fetchone()
                if not owned:
                    raise CollectorError("INVALID_FORM", "CREATOR_NOT_FOUND")
            else:
                row = conn.execute(
                    "SELECT latest_snapshot_id FROM douyin_xingtu_creator_current "
                    "WHERE creator_id=%s",
                    (creator_id,),
                ).fetchone()
                if not row:
                    raise CollectorError("INVALID_FORM", "CREATOR_NOT_FOUND")
                snapshot_id = str(row["latest_snapshot_id"]) if row["latest_snapshot_id"] else None
            return self._video_page(conn, creator_id, snapshot_id, module_key)

    def task_creator_videos(
        self,
        root_task_id: str,
        creator_id: str,
        *,
        module_key: str | None = None,
        snapshot_id: str | None = None,
    ) -> CreatorVideoPage:
        """The work observations of the snapshot this task collected for this creator."""
        root_task_id = _validated_uuid(root_task_id, "TASK_NOT_FOUND")
        creator_id = _validated_uuid(creator_id, "CREATOR_NOT_FOUND")
        with self.repository.connect() as conn:
            row = conn.execute(
                "SELECT latest_snapshot_id FROM task_creators "
                "WHERE root_task_id=%s AND creator_id=%s",
                (root_task_id, creator_id),
            ).fetchone()
            if not row:
                raise CollectorError("INVALID_FORM", "CREATOR_NOT_FOUND")
            if snapshot_id:
                snapshot_id = _validated_uuid(snapshot_id, "SNAPSHOT_NOT_FOUND")
                task_snapshot_id = (
                    str(row["latest_snapshot_id"]) if row["latest_snapshot_id"] else None
                )
                if snapshot_id != task_snapshot_id:
                    raise CollectorError("INVALID_FORM", "SNAPSHOT_NOT_FOUND")
            else:
                snapshot_id = str(row["latest_snapshot_id"]) if row["latest_snapshot_id"] else None
            return self._video_page(conn, creator_id, snapshot_id, module_key)

    def creator_library_history(self, creator_id: str) -> CreatorLibraryHistory:
        creator_id = _validated_uuid(creator_id, "CREATOR_NOT_FOUND")
        with self.repository.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM douyin_xingtu_creator_snapshot_index WHERE creator_id=%s
                ORDER BY captured_at DESC,snapshot_id DESC""",
                (creator_id,),
            ).fetchall()
            # HISTORICAL_BACKFILL_PENDING: snapshots written before the library read model existed
            # have no index row yet (measured: 58 indexed of 78 stored).  The page reports the gap
            # rather than showing an incomplete timeline as complete.
            stored = conn.execute(
                "SELECT count(*) AS total FROM creator_snapshots WHERE creator_id=%s",
                (creator_id,),
            ).fetchone()
            total_snapshots = int(stored["total"]) if stored else 0
        if not rows:
            raise CollectorError("INVALID_FORM", "CREATOR_NOT_FOUND")
        metric_columns = (
            "followers_count",
            "monthly_deep_users_count",
            "monthly_connected_users_count",
            "monthly_follower_growth_rate_raw",
            "interaction_rate_value_raw",
            "completion_rate_value_raw",
            "expected_cpm_21_60_raw",
            "expected_cpm_60_plus_raw",
            "expected_cpe_21_60_raw",
            "expected_cpe_60_plus_raw",
        )
        return CreatorLibraryHistory(
            items=[
                CreatorLibraryHistoryPoint(
                    snapshot_id=str(row["snapshot_id"]),
                    captured_at=row["captured_at"],
                    profile_complete=bool(row["profile_complete"]),
                    pipeline_complete=bool(row["pipeline_complete"]),
                    module_statuses=row["module_statuses"],
                    metrics={key: row[key] for key in metric_columns},
                )
                for row in rows
            ],
            indexed_snapshots=len(rows),
            total_snapshots=total_snapshots,
        )

    def creator_library_quotes(
        self, creator_id: str, cooperation_form: str | None = None
    ) -> list[CreatorLibraryQuote]:
        creator_id = _validated_uuid(creator_id, "CREATOR_NOT_FOUND")
        query = "SELECT * FROM douyin_xingtu_creator_quote_observations WHERE creator_id=%s"
        params: list[Any] = [creator_id]
        if cooperation_form:
            query += " AND cooperation_form=%s"
            params.append(cooperation_form)
        query += " ORDER BY observed_at DESC,position ASC"
        with self.repository.connect() as conn:
            rows = conn.execute(query, params).fetchall()
            exists = conn.execute(
                "SELECT 1 FROM douyin_xingtu_creator_current WHERE creator_id=%s", (creator_id,)
            ).fetchone()
        if not exists:
            raise CollectorError("INVALID_FORM", "CREATOR_NOT_FOUND")
        return [
            CreatorLibraryQuote(
                snapshot_id=str(row["snapshot_id"]),
                position=int(row["position"]),
                cooperation_form=row["cooperation_form"],
                settlement_description=row["settlement_description"],
                price_raw=row["price_raw"],
                origin_price_raw=row["origin_price_raw"],
                observed_at=row["observed_at"],
                offer_raw=row["offer_raw"],
            )
            for row in rows
        ]

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
