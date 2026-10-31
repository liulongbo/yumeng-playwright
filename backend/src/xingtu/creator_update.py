from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from .contracts import PlatformRegistry
from .domain import (
    Candidate,
    Checkpoint,
    CollectorError,
    CreatorRef,
    ProfileRequirement,
    TaskKind,
    TaskRecord,
    TaskStatus,
    uid,
    utcnow,
)
from .product_models import CreatorUpdateResponse, CreatorUpdateStatus
from .repository import Repository

TERMINAL_STATES = (
    "COMPLETED",
    "PARTIAL_COMPLETED",
    "CANCELLED",
    "FAILED",
    "FAILED_VALIDATION",
)
RUNNABLE_STATES = ("QUEUED", "SEARCHING", "COLLECTING", "PERSISTING", "RETRY_WAIT")
IN_FLIGHT_TTL = timedelta(hours=6)


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def update_policy(followers: Decimal | None) -> tuple[str, int]:
    """Return (tier, interval_days) using the approved follower bands."""
    if followers is None:
        return "unknown", 15
    if followers >= 1_000_000:
        return "ge_100w", 1
    if followers >= 500_000:
        return "50w_100w", 3
    if followers >= 100_000:
        return "10w_50w", 5
    if followers >= 10_000:
        return "1w_10w", 7
    return "lt_1w", 15


def _next_due(base: datetime, followers: Decimal | None) -> tuple[datetime, str, int]:
    tier, days = update_policy(followers)
    return base + timedelta(days=days), tier, days


# Fast retries allowed after an incomplete or failed update: 1 h, then 6 h.  Once they are
# exhausted the creator waits for its normal follower-band interval instead of entering another
# 24 h retry, so a structurally incomplete profile cannot be re-crawled on a short cycle forever.
MAX_FAST_RETRIES = 2


def _backoff(failures: int, interval_days: int) -> timedelta:
    if failures > MAX_FAST_RETRIES:
        return timedelta(days=interval_days)
    value = timedelta(hours=1) if failures <= 1 else timedelta(hours=6)
    return min(value, timedelta(days=interval_days))


def _validated_uuid(value: str, reason: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise CollectorError("INVALID_FORM", reason) from exc


def _reconcile_row(conn: Any, row: dict[str, Any]) -> None:
    if not row.get("in_flight_root_task_id"):
        return
    task_state = row.get("task_state")
    if task_state is not None and task_state not in TERMINAL_STATES:
        if row.get("in_flight_expires_at") and row["in_flight_expires_at"] <= utcnow():
            conn.execute(
                """UPDATE creator_update_schedule
                SET in_flight_expires_at=%s,updated_at=now() WHERE creator_id=%s""",
                (utcnow() + IN_FLIGHT_TTL, row["creator_id"]),
            )
        return
    snapshot = conn.execute(
        """SELECT s.snapshot_id,s.created_at,
        COALESCE(i.pipeline_complete,(s.payload->>'pipeline_complete')::boolean,false)
          AS pipeline_complete
        FROM creator_snapshots s
        LEFT JOIN douyin_xingtu_creator_snapshot_index i USING(snapshot_id)
        WHERE s.root_task_id=%s AND s.creator_id=%s
        ORDER BY s.created_at DESC,s.snapshot_id DESC LIMIT 1""",
        (row["in_flight_root_task_id"], row["creator_id"]),
    ).fetchone()
    creator = conn.execute(
        "SELECT followers_count FROM douyin_xingtu_creator_current WHERE creator_id=%s",
        (row["creator_id"],),
    ).fetchone()
    followers = _decimal(creator["followers_count"]) if creator else None
    failures = int(row["consecutive_failures"])
    if snapshot and bool(snapshot["pipeline_complete"]):
        next_due, tier, days = _next_due(snapshot["created_at"], followers)
        conn.execute(
            """UPDATE creator_update_schedule SET
            next_due_at=%s,tier=%s,interval_days=%s,last_success_at=%s,
            last_success_snapshot_id=%s,consecutive_failures=0,last_failure_reason=NULL,
            in_flight_root_task_id=NULL,in_flight_claimed_at=NULL,in_flight_expires_at=NULL,
            updated_at=now() WHERE creator_id=%s""",
            (
                next_due,
                tier,
                days,
                snapshot["created_at"],
                snapshot["snapshot_id"],
                row["creator_id"],
            ),
        )
        return
    failures += 1
    reason = (
        "PARTIAL_UPDATE"
        if snapshot is not None
        else (row.get("task_failure_reason") or "UPDATE_NO_SNAPSHOT")
    )
    interval_days = int(row["interval_days"])
    next_due = utcnow() + _backoff(failures, interval_days)
    conn.execute(
        """UPDATE creator_update_schedule SET
        next_due_at=%s,consecutive_failures=%s,last_failure_reason=%s,
        in_flight_root_task_id=NULL,in_flight_claimed_at=NULL,in_flight_expires_at=NULL,
        updated_at=now() WHERE creator_id=%s""",
        (next_due, failures, reason, row["creator_id"]),
    )


class CreatorUpdateService:
    """Manual/scheduled creator updates: scheduling state, task creation and reconciliation."""

    def __init__(
        self,
        repository: Repository,
        registry: PlatformRegistry,
        profile_requirement: ProfileRequirement | None = None,
        *,
        batch_size: int = 5,
    ):
        if not 1 <= batch_size <= 20:
            raise ValueError("update batch size must be between 1 and 20")
        self.repository = repository
        self.registry = registry
        self.profile_requirement = profile_requirement
        self.batch_size = batch_size

    # -- creation helpers ----------------------------------------------------------------

    def homepage(self, platform_creator_id: str) -> str:
        spec = self.registry.search
        if spec is None or not spec.homepage_template:
            raise CollectorError("PLATFORM_PAGE_CHANGED", "HOMEPAGE_TEMPLATE_MISSING")
        url = spec.homepage_template.format(platform_creator_id=platform_creator_id)
        self.registry.validate_homepage(url)
        return url

    def _checkpoint(self, targets: list[CreatorRef]) -> Checkpoint:
        digest = hashlib.sha256(
            "|".join(sorted(target.platform_creator_id for target in targets)).encode()
        ).hexdigest()
        return Checkpoint(
            conditions_digest="update:" + digest,
            adapter_version=self.registry.adapter_version,
            contract_version=self.registry.contract_version,
            profile_module_keys=[item.key for item in self.registry.modules],
            profile_checkpoint_versions={
                item.key: item.checkpoint_version for item in self.registry.modules
            },
            featured_collection_types=[item.key.value for item in self.registry.featured],
            featured_checkpoint_versions={
                item.key.value: item.checkpoint_version for item in self.registry.featured
            },
        )

    def _targets(self, rows: list[dict[str, Any]]) -> list[CreatorRef]:
        return [
            CreatorRef(
                platform_creator_id=str(row["platform_creator_id"]),
                verified_homepage=self.homepage(str(row["platform_creator_id"])),
                first_position=index,
                creator_id=str(row["creator_id"]),
            )
            for index, row in enumerate(rows)
        ]

    def _record(
        self,
        targets: list[CreatorRef],
        task_kind: TaskKind,
        *,
        root_task_id: str | None = None,
    ) -> TaskRecord:
        checkpoint = self._checkpoint(targets)
        checkpoint.candidates = [Candidate(ref=target) for target in targets]
        return TaskRecord(
            root_task_id=root_task_id or uid(),
            task_id=uid(),
            attempt_id=uid(),
            plan=None,
            task_kind=task_kind,
            update_targets=targets,
            state=TaskStatus.QUEUED,
            execution_unit_id="",
            checkpoint=checkpoint,
            profile_requirement=self.profile_requirement,
            source="internal_acceptance",
        )

    def _insert_task(
        self,
        conn: Any,
        task: TaskRecord,
        *,
        created_by: str | None,
        origin_root_task_id: str | None = None,
        actor: str = "scheduler",
    ) -> None:
        conn.execute(
            """INSERT INTO root_tasks(
            root_task_id,state,version,unit_id,payload,created_by,origin_root_task_id,task_kind,platform)
            VALUES(%s,%s,%s,NULL,%s,%s,%s,%s,%s)""",
            (
                task.root_task_id,
                task.state.value,
                task.version,
                Jsonb(task.model_dump(mode="json", exclude={"checkpoint"})),
                created_by,
                origin_root_task_id,
                task.task_kind.value,
                task.platform.value,
            ),
        )
        conn.execute(
            "INSERT INTO tasks VALUES(%s,%s,NULL,%s)",
            (task.task_id, task.root_task_id, "P2-1"),
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
            "INSERT INTO audit_logs(root_task_id,actor,action) VALUES(%s,%s,%s)",
            (
                task.root_task_id,
                actor,
                f"creator_update.create:{task.task_kind.value}:{task.target_count}",
            ),
        )

    def _ensure_schedule_row(self, conn: Any, creator_id: str) -> dict[str, Any]:
        row = conn.execute(
            """SELECT c.creator_id,c.platform_creator_id,c.followers_count,c.data_updated_at,
            (SELECT si.captured_at FROM douyin_xingtu_creator_snapshot_index si
             WHERE si.creator_id=c.creator_id AND si.pipeline_complete=true
             ORDER BY si.captured_at DESC LIMIT 1) AS last_complete_at,
            (SELECT si.snapshot_id FROM douyin_xingtu_creator_snapshot_index si
             WHERE si.creator_id=c.creator_id AND si.pipeline_complete=true
             ORDER BY si.captured_at DESC LIMIT 1) AS last_complete_snapshot_id
            FROM douyin_xingtu_creator_current c WHERE c.creator_id=%s""",
            (creator_id,),
        ).fetchone()
        if not row:
            raise CollectorError("INVALID_FORM", "CREATOR_NOT_FOUND")
        base = row["last_complete_at"] or row["data_updated_at"] or utcnow()
        next_due, tier, days = _next_due(base, _decimal(row["followers_count"]))
        conn.execute(
            """INSERT INTO creator_update_schedule(
            creator_id,next_due_at,tier,interval_days,last_success_at,last_success_snapshot_id)
            VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(creator_id) DO NOTHING""",
            (
                creator_id,
                next_due,
                tier,
                days,
                row["last_complete_at"],
                row["last_complete_snapshot_id"],
            ),
        )
        current = conn.execute(
            "SELECT * FROM creator_update_schedule WHERE creator_id=%s FOR UPDATE",
            (creator_id,),
        ).fetchone()
        assert current
        return dict(current)

    def _insert_missing_schedule_rows(self, conn: Any) -> int:
        rows = conn.execute(
            """SELECT c.creator_id,c.followers_count,c.data_updated_at,
            (SELECT si.captured_at FROM douyin_xingtu_creator_snapshot_index si
             WHERE si.creator_id=c.creator_id AND si.pipeline_complete=true
             ORDER BY si.captured_at DESC LIMIT 1) AS last_complete_at,
            (SELECT si.snapshot_id FROM douyin_xingtu_creator_snapshot_index si
             WHERE si.creator_id=c.creator_id AND si.pipeline_complete=true
             ORDER BY si.captured_at DESC LIMIT 1) AS last_complete_snapshot_id
            FROM douyin_xingtu_creator_current c
            LEFT JOIN creator_update_schedule u USING(creator_id)
            WHERE u.creator_id IS NULL"""
        ).fetchall()
        inserted = 0
        for row in rows:
            base = row["last_complete_at"] or row["data_updated_at"] or utcnow()
            next_due, tier, days = _next_due(base, _decimal(row["followers_count"]))
            result = conn.execute(
                """INSERT INTO creator_update_schedule(
                creator_id,next_due_at,tier,interval_days,last_success_at,
                last_success_snapshot_id) VALUES(%s,%s,%s,%s,%s,%s)
                ON CONFLICT(creator_id) DO NOTHING""",
                (
                    row["creator_id"],
                    next_due,
                    tier,
                    days,
                    row["last_complete_at"],
                    row["last_complete_snapshot_id"],
                ),
            )
            inserted += int(result.rowcount)
        return inserted

    # -- reconciliation ------------------------------------------------------------------

    def _reconcile_in_flight(self, conn: Any) -> int:
        rows = conn.execute(
            """SELECT s.*,r.state AS task_state,r.payload->>'failure_reason'
              AS task_failure_reason
            FROM creator_update_schedule s
            LEFT JOIN root_tasks r ON r.root_task_id=s.in_flight_root_task_id
            WHERE s.in_flight_root_task_id IS NOT NULL
            FOR UPDATE OF s SKIP LOCKED"""
        ).fetchall()
        for row in rows:
            _reconcile_row(conn, dict(row))
        return len(rows)

    def reconcile_creator(self, creator_id: str) -> None:
        with self.repository.connect() as conn:
            row = conn.execute(
                """SELECT s.*,r.state AS task_state,r.payload->>'failure_reason'
                  AS task_failure_reason
                FROM creator_update_schedule s
                LEFT JOIN root_tasks r ON r.root_task_id=s.in_flight_root_task_id
                WHERE s.creator_id=%s FOR UPDATE OF s""",
                (creator_id,),
            ).fetchone()
            if not row:
                return
            _reconcile_row(conn, dict(row))

    # -- manual update -------------------------------------------------------------------

    def _require_xingtu_creator(self, creator_id: str) -> None:
        """Creator updates are still the Xingtu-only update service (KJX-01 stage D scope).

        A juxing creator must get an explicit "not supported" answer, never a misleading
        CREATOR_NOT_FOUND from the Xingtu current-projection table.
        """

        with self.repository.connect() as conn:
            row = conn.execute(
                "SELECT platform FROM platform_creators WHERE creator_id=%s", (creator_id,)
            ).fetchone()
        if not row:
            raise CollectorError("INVALID_FORM", "CREATOR_NOT_FOUND")
        if row["platform"] != "douyin_xingtu":
            raise CollectorError("UNSUPPORTED_FILTER", "KUAISHOU_JUXING_UPDATE_NOT_SUPPORTED")

    def create_manual_update(
        self, creator_id: str, *, user_id: str, idempotency_key: str
    ) -> CreatorUpdateResponse:
        creator_id = _validated_uuid(creator_id, "CREATOR_NOT_FOUND")
        if not idempotency_key.strip() or len(idempotency_key) > 200:
            raise CollectorError("INVALID_FORM", "INVALID_IDEMPOTENCY_KEY")
        self._require_xingtu_creator(creator_id)
        actor = "product:" + user_id
        operation = "creator.update"
        digest = hashlib.sha256(f"{creator_id}:{operation}".encode()).hexdigest()
        self.reconcile_creator(creator_id)
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
                return CreatorUpdateResponse.model_validate(
                    old["response_payload"]
                    or {"root_task_id": str(old["root_task_id"]), "status": "QUEUED"}
                )
            creator = conn.execute(
                """SELECT c.creator_id,c.platform_creator_id,c.followers_count
                FROM douyin_xingtu_creator_current c WHERE c.creator_id=%s""",
                (creator_id,),
            ).fetchone()
            if not creator:
                raise CollectorError("INVALID_FORM", "CREATOR_NOT_FOUND")
            self._ensure_schedule_row(conn, creator_id)
            # _ensure_schedule_row locks the schedule row.  Reconcile a terminal in-flight task
            # before deciding whether this click must reuse it.
            existing = conn.execute(
                """SELECT s.*,r.state AS task_state,r.payload->>'failure_reason'
                  AS task_failure_reason
                FROM creator_update_schedule s
                LEFT JOIN root_tasks r ON r.root_task_id=s.in_flight_root_task_id
                WHERE s.creator_id=%s""",
                (creator_id,),
            ).fetchone()
            if existing and existing["in_flight_root_task_id"]:
                _reconcile_row(conn, dict(existing))
                existing = conn.execute(
                    """SELECT s.*,r.state AS task_state,r.payload->>'failure_reason'
                      AS task_failure_reason
                    FROM creator_update_schedule s
                    LEFT JOIN root_tasks r ON r.root_task_id=s.in_flight_root_task_id
                    WHERE s.creator_id=%s""",
                    (creator_id,),
                ).fetchone()
            if existing and existing["in_flight_root_task_id"]:
                state = existing.get("task_state")
                response = CreatorUpdateResponse(
                    root_task_id=str(existing["in_flight_root_task_id"]),
                    status=TaskStatus(state) if state is not None else TaskStatus.QUEUED,
                    reused=True,
                )
                conn.execute(
                    """INSERT INTO idempotency_records(
                    actor,operation,key,digest,root_task_id,response_payload)
                    VALUES(%s,%s,%s,%s,%s,%s)""",
                    (
                        actor,
                        operation,
                        idempotency_key,
                        digest,
                        response.root_task_id,
                        Jsonb(response.model_dump(mode="json")),
                    ),
                )
                return response
            root = uid()
            targets = self._targets([dict(creator)])
            task = self._record(targets, TaskKind.MANUAL_UPDATE, root_task_id=root)
            self._insert_task(conn, task, created_by=user_id, actor=actor)
            conn.execute(
                """UPDATE creator_update_schedule SET
                in_flight_root_task_id=%s,in_flight_claimed_at=now(),
                in_flight_expires_at=%s,last_attempt_at=now(),updated_at=now()
                WHERE creator_id=%s""",
                (root, utcnow() + IN_FLIGHT_TTL, creator_id),
            )
            response = CreatorUpdateResponse(root_task_id=root, reused=False)
            conn.execute(
                """INSERT INTO idempotency_records(
                actor,operation,key,digest,root_task_id,response_payload)
                VALUES(%s,%s,%s,%s,%s,%s)""",
                (
                    actor,
                    operation,
                    idempotency_key,
                    digest,
                    root,
                    Jsonb(response.model_dump(mode="json")),
                ),
            )
            return response

    # -- scheduler -----------------------------------------------------------------------

    def scheduler_tick(self) -> dict[str, int]:
        with self.repository.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(904052)")
            reconciled = self._reconcile_in_flight(conn)
            inserted = self._insert_missing_schedule_rows(conn)
            active = conn.execute(
                """SELECT 1 FROM root_tasks WHERE task_kind='scheduled_update'
                AND state NOT IN ('COMPLETED','PARTIAL_COMPLETED','CANCELLED',
                                  'FAILED','FAILED_VALIDATION') LIMIT 1"""
            ).fetchone()
            if active:
                return {
                    "reconciled": reconciled,
                    "enrolled": inserted,
                    "created": 0,
                    "skipped": 1,
                }
            normal = conn.execute(
                """SELECT 1 FROM root_tasks WHERE task_kind='collection'
                AND state = ANY(%s) LIMIT 1""",
                (list(RUNNABLE_STATES),),
            ).fetchone()
            if normal:
                return {
                    "reconciled": reconciled,
                    "enrolled": inserted,
                    "created": 0,
                    "skipped": 1,
                }
            capable = conn.execute(
                """SELECT 1 FROM execution_units
                WHERE 'scheduled_update' = ANY(allowed_task_kinds)
                  AND state <> 'QUARANTINED' LIMIT 1"""
            ).fetchone()
            if not capable:
                return {
                    "reconciled": reconciled,
                    "enrolled": inserted,
                    "created": 0,
                    "skipped": 1,
                }
            due = conn.execute(
                """SELECT u.creator_id,c.platform_creator_id
                FROM creator_update_schedule u
                JOIN douyin_xingtu_creator_current c USING(creator_id)
                WHERE u.next_due_at <= now() AND u.in_flight_root_task_id IS NULL
                ORDER BY u.next_due_at,c.creator_id
                LIMIT %s
                FOR UPDATE OF u SKIP LOCKED""",
                (self.batch_size,),
            ).fetchall()
            if not due:
                return {
                    "reconciled": reconciled,
                    "enrolled": inserted,
                    "created": 0,
                    "skipped": 0,
                }
            targets = self._targets([dict(row) for row in due])
            task = self._record(targets, TaskKind.SCHEDULED_UPDATE)
            self._insert_task(conn, task, created_by=None)
            conn.execute(
                """UPDATE creator_update_schedule SET
                in_flight_root_task_id=%s,in_flight_claimed_at=now(),
                in_flight_expires_at=%s,last_attempt_at=now(),updated_at=now()
                WHERE creator_id = ANY(%s)""",
                (
                    task.root_task_id,
                    utcnow() + IN_FLIGHT_TTL,
                    [str(row["creator_id"]) for row in due],
                ),
            )
            return {
                "reconciled": reconciled,
                "enrolled": inserted,
                "created": len(due),
                "skipped": 0,
            }

    # -- status --------------------------------------------------------------------------

    def status(self, creator_id: str) -> CreatorUpdateStatus:
        creator_id = _validated_uuid(creator_id, "CREATOR_NOT_FOUND")
        self._require_xingtu_creator(creator_id)
        with self.repository.connect() as conn:
            self._ensure_schedule_row(conn, creator_id)
        self.reconcile_creator(creator_id)
        with self.repository.connect() as conn:
            row = conn.execute(
                """SELECT u.*,c.data_updated_at,r.state AS task_state
                FROM creator_update_schedule u
                JOIN douyin_xingtu_creator_current c USING(creator_id)
                LEFT JOIN root_tasks r ON r.root_task_id=u.in_flight_root_task_id
                WHERE u.creator_id=%s""",
                (creator_id,),
            ).fetchone()
        if not row:
            raise CollectorError("INVALID_FORM", "CREATOR_NOT_FOUND")
        state = row.get("task_state")
        from .product_queries import task_stage

        return CreatorUpdateStatus(
            creator_id=creator_id,
            in_flight_root_task_id=str(row["in_flight_root_task_id"])
            if row["in_flight_root_task_id"]
            else None,
            task_status=TaskStatus(state) if state is not None else None,
            task_stage=task_stage(TaskStatus(state)) if state is not None else None,
            last_write_at=row.get("data_updated_at"),
            last_success_at=row.get("last_success_at"),
            last_success_snapshot_id=str(row["last_success_snapshot_id"])
            if row.get("last_success_snapshot_id")
            else None,
            next_due_at=row.get("next_due_at"),
            tier=row.get("tier"),
            interval_days=row.get("interval_days"),
            consecutive_failures=int(row.get("consecutive_failures") or 0),
            last_failure_reason=row.get("last_failure_reason"),
        )


def reconcile_update_task(repository: Repository, root_task_id: str) -> int:
    """Release one update task's in-flight schedule rows and advance/back off.

    Called when a task reaches a terminal state, independent of UI reads or the next
    scheduler tick.  It is idempotent: rows already released are simply absent.
    """
    with repository.connect() as conn:
        rows = conn.execute(
            """SELECT s.*,r.state AS task_state,r.payload->>'failure_reason'
              AS task_failure_reason
            FROM creator_update_schedule s
            LEFT JOIN root_tasks r ON r.root_task_id=s.in_flight_root_task_id
            WHERE s.in_flight_root_task_id=%s
            FOR UPDATE OF s""",
            (root_task_id,),
        ).fetchall()
        for row in rows:
            _reconcile_row(conn, dict(row))
        return len(rows)
