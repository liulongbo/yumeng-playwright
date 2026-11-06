from __future__ import annotations

import hashlib
from dataclasses import dataclass
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
    CreatorScene,
    PlatformId,
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
UPDATE_SERVICE_DISABLED_REASON = "UPDATE_SERVICE_DISABLED"

XINGTU_VIDEO_HOMEPAGE = (
    "https://www.xingtu.cn/ad/creator/author-homepage/douyin-video/{platform_creator_id}"
)
XINGTU_LIVE_HOMEPAGE = "https://www.xingtu.cn/ad/creator/author/douyin/{platform_creator_id}/10"
JUXING_LIVE_HOMEPAGE = "https://k.kuaishou.com/#/live-promotion/star/{star_id}?openBy=user"


def scope_key(platform: PlatformId | str, scene: CreatorScene | str) -> str:
    platform_value = platform.value if isinstance(platform, PlatformId) else str(platform)
    scene_value = scene.value if isinstance(scene, CreatorScene) else str(scene)
    return f"{platform_value}:{scene_value}"


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


def _one(conn: Any, statement: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    row = conn.execute(statement, params).fetchone()
    return dict(row) if row is not None else None


def _many(conn: Any, statement: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(statement, params).fetchall()]


@dataclass
class UpdateScope:
    """One executable (platform, creator_scene) update lane.

    The scope owns the contract used to build update checkpoints and the deterministic target
    locator.  It deliberately does not own scheduling state: every creator's cadence still lives
    in ``creator_update_schedule`` keyed by (creator, scene).
    """

    platform: PlatformId
    scene: CreatorScene
    registry: PlatformRegistry
    profile_requirement: ProfileRequirement | None = None

    @property
    def key(self) -> str:
        return scope_key(self.platform, self.scene)

    def homepage(self, row: dict[str, Any]) -> str:
        platform_creator_id = str(row["platform_creator_id"])
        if self.platform == PlatformId.DOUYIN_XINGTU:
            spec = self.registry.search
            template = spec.homepage_template if spec is not None else None
            fallback = (
                XINGTU_VIDEO_HOMEPAGE
                if self.scene == CreatorScene.VIDEO_SQUARE
                else XINGTU_LIVE_HOMEPAGE
            )
            url = (template or fallback).format(platform_creator_id=platform_creator_id)
        elif self.scene == CreatorScene.VIDEO_SQUARE:
            # Juxing video identities are userIds; the verified detail route needs the starId,
            # captured with the identity and persisted as platform_creators.video_homepage.
            value = row.get("video_homepage")
            if not isinstance(value, str) or not value:
                raise CollectorError("CREATOR_INVALID", "UNRESOLVED_VIDEO_HOMEPAGE")
            url = value
        else:
            star_id = row.get("platform_star_id")
            if star_id is None or (isinstance(star_id, str) and not star_id.strip()):
                raise CollectorError("CREATOR_INVALID", "UNRESOLVED_LIVE_STAR_ID")
            url = JUXING_LIVE_HOMEPAGE.format(star_id=star_id)
        self.registry.validate_homepage(url)
        return url


def _reconcile_row(conn: Any, row: dict[str, Any]) -> None:
    creator_id = row["creator_id"]
    scene = row["creator_scene"]
    platform = row["platform"]
    if not row.get("in_flight_root_task_id"):
        return
    task_state = row.get("task_state")
    if task_state is not None and task_state not in TERMINAL_STATES:
        if row.get("in_flight_expires_at") and row["in_flight_expires_at"] <= utcnow():
            conn.execute(
                """UPDATE creator_update_schedule
                SET in_flight_expires_at=%s,updated_at=now()
                WHERE creator_id=%s AND creator_scene=%s""",
                (utcnow() + IN_FLIGHT_TTL, creator_id, scene),
            )
        return
    if row.get("task_failure_reason") == UPDATE_SERVICE_DISABLED_REASON:
        # Switching a service off is not a collection failure.  Release the claim but keep the
        # creator due, so re-enabling resumes from the existing cycle instead of a fake backoff.
        conn.execute(
            """UPDATE creator_update_schedule SET
            in_flight_root_task_id=NULL,in_flight_claimed_at=NULL,in_flight_expires_at=NULL,
            updated_at=now() WHERE creator_id=%s AND creator_scene=%s""",
            (creator_id, scene),
        )
        return
    snapshot = _latest_snapshot(conn, row)
    followers = _current_followers(conn, platform, scene, creator_id)
    failures = int(row["consecutive_failures"])
    if snapshot and bool(snapshot["pipeline_complete"]):
        next_due, tier, days = _next_due(snapshot["created_at"], followers)
        conn.execute(
            """UPDATE creator_update_schedule SET
            next_due_at=%s,tier=%s,interval_days=%s,last_success_at=%s,
            last_success_snapshot_id=%s,consecutive_failures=0,last_failure_reason=NULL,
            in_flight_root_task_id=NULL,in_flight_claimed_at=NULL,in_flight_expires_at=NULL,
            updated_at=now() WHERE creator_id=%s AND creator_scene=%s""",
            (
                next_due,
                tier,
                days,
                snapshot["created_at"],
                snapshot["snapshot_id"],
                creator_id,
                scene,
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
        updated_at=now() WHERE creator_id=%s AND creator_scene=%s""",
        (next_due, failures, reason, creator_id, scene),
    )


def _latest_snapshot(conn: Any, row: dict[str, Any]) -> dict[str, Any] | None:
    """Latest snapshot produced by this in-flight task, with the scene's complete flag."""
    creator_id = row["creator_id"]
    scene = row["creator_scene"]
    platform = row["platform"]
    if platform == PlatformId.DOUYIN_XINGTU.value and scene == CreatorScene.VIDEO_SQUARE.value:
        return _one(
            conn,
            """SELECT s.snapshot_id,s.created_at,
            COALESCE(i.pipeline_complete,(s.payload->>'pipeline_complete')::boolean,false)
              AS pipeline_complete
            FROM creator_snapshots s
            LEFT JOIN douyin_xingtu_creator_snapshot_index i USING(snapshot_id)
            WHERE s.root_task_id=%s AND s.creator_id=%s AND s.creator_scene=%s
            ORDER BY s.created_at DESC,s.snapshot_id DESC LIMIT 1""",
            (row["in_flight_root_task_id"], creator_id, scene),
        )
    return _one(
        conn,
        """SELECT snapshot_id,created_at,
        COALESCE((payload->>'pipeline_complete')::boolean,false) AS pipeline_complete
        FROM creator_snapshots
        WHERE root_task_id=%s AND creator_id=%s AND creator_scene=%s
        ORDER BY created_at DESC,snapshot_id DESC LIMIT 1""",
        (row["in_flight_root_task_id"], creator_id, scene),
    )


def _current_followers(conn: Any, platform: str, scene: str, creator_id: Any) -> Decimal | None:
    """Current follower count from the scene's authoritative projection."""
    if scene == CreatorScene.VIDEO_SQUARE.value and platform == PlatformId.DOUYIN_XINGTU.value:
        row = conn.execute(
            "SELECT followers_count FROM douyin_xingtu_creator_current WHERE creator_id=%s",
            (creator_id,),
        ).fetchone()
    elif scene == CreatorScene.LIVE_SQUARE.value:
        row = conn.execute(
            """SELECT followers_count FROM creator_live_current
            WHERE creator_id=%s AND platform=%s""",
            (creator_id, platform),
        ).fetchone()
    elif platform == PlatformId.KUAISHOU_JUXING.value:
        row = conn.execute(
            """SELECT (projection->'basic.followers'->'value'->>'amount')::numeric
            AS followers_count FROM platform_creators WHERE creator_id=%s""",
            (creator_id,),
        ).fetchone()
    else:
        return None
    return _decimal(row["followers_count"]) if row else None


class CreatorUpdateService:
    """Manual/scheduled creator updates: scheduling state, task creation and reconciliation.

    Manual updates remain the Xingtu video capability.  Scheduled updates now iterate every
    injected ``UpdateScope``; each scope has its own plan rows and its own guard rails.
    """

    def __init__(
        self,
        repository: Repository,
        registry: PlatformRegistry | None = None,
        profile_requirement: ProfileRequirement | None = None,
        *,
        batch_size: int = 5,
        scopes: dict[str, UpdateScope] | None = None,
        scope_errors: dict[str, str] | None = None,
        tick_seconds: float = 60.0,
    ):
        if not 1 <= batch_size <= 20:
            raise ValueError("update batch size must be between 1 and 20")
        self.repository = repository
        if scopes is None:
            if registry is None:
                raise ValueError("either registry or scopes is required")
            default = UpdateScope(
                PlatformId.DOUYIN_XINGTU,
                CreatorScene.VIDEO_SQUARE,
                registry,
                profile_requirement,
            )
            scopes = {default.key: default}
        self.scopes = dict(scopes)
        self.scope_errors = dict(scope_errors or {})
        self.batch_size = batch_size
        self.tick_seconds = tick_seconds

    # -- creation helpers ----------------------------------------------------------------

    @property
    def manual_scope(self) -> UpdateScope:
        scope = self.scopes.get(scope_key(PlatformId.DOUYIN_XINGTU, CreatorScene.VIDEO_SQUARE))
        if scope is None:
            raise CollectorError("UNSUPPORTED_FILTER", "UPDATE_SCOPE_NOT_CONFIGURED")
        return scope

    def _checkpoint(self, scope: UpdateScope, targets: list[CreatorRef]) -> Checkpoint:
        digest = hashlib.sha256(
            "|".join(sorted(target.platform_creator_id for target in targets)).encode()
        ).hexdigest()
        return Checkpoint(
            conditions_digest="update:" + digest,
            adapter_version=scope.registry.adapter_version,
            contract_version=scope.registry.contract_version,
            profile_module_keys=[item.key for item in scope.registry.modules],
            profile_checkpoint_versions={
                item.key: item.checkpoint_version for item in scope.registry.modules
            },
            featured_collection_types=[item.key.value for item in scope.registry.featured],
            featured_checkpoint_versions={
                item.key.value: item.checkpoint_version for item in scope.registry.featured
            },
        )

    def _targets(self, scope: UpdateScope, rows: list[dict[str, Any]]) -> list[CreatorRef]:
        return [
            CreatorRef(
                platform=scope.platform.value,
                platform_creator_id=str(row["platform_creator_id"]),
                verified_homepage=scope.homepage(dict(row)),
                first_position=index,
                creator_id=str(row["creator_id"]) if row.get("creator_id") else None,
            )
            for index, row in enumerate(rows)
        ]

    def _record(
        self,
        scope: UpdateScope,
        targets: list[CreatorRef],
        task_kind: TaskKind,
        *,
        root_task_id: str | None = None,
    ) -> TaskRecord:
        checkpoint = self._checkpoint(scope, targets)
        checkpoint.candidates = [Candidate(ref=target) for target in targets]
        return TaskRecord(
            root_task_id=root_task_id or uid(),
            task_id=uid(),
            attempt_id=uid(),
            plan=None,
            task_kind=task_kind,
            creator_scene=scope.scene,
            update_targets=targets,
            state=TaskStatus.QUEUED,
            execution_unit_id="",
            checkpoint=checkpoint,
            profile_requirement=scope.profile_requirement,
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
            root_task_id,state,version,unit_id,payload,created_by,origin_root_task_id,task_kind,
            platform,creator_scene) VALUES(%s,%s,%s,NULL,%s,%s,%s,%s,%s,%s)""",
            (
                task.root_task_id,
                task.state.value,
                task.version,
                Jsonb(task.model_dump(mode="json", exclude={"checkpoint"})),
                created_by,
                origin_root_task_id,
                task.task_kind.value,
                task.platform.value,
                task.creator_scene.value,
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

    def _ensure_schedule_row(
        self, conn: Any, creator_id: str, scope: UpdateScope | None = None
    ) -> dict[str, Any]:
        scope = scope or self.manual_scope
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
            creator_id,creator_scene,next_due_at,tier,interval_days,last_success_at,
            last_success_snapshot_id)
            VALUES(%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(creator_id,creator_scene) DO NOTHING""",
            (
                creator_id,
                scope.scene.value,
                next_due,
                tier,
                days,
                row["last_complete_at"],
                row["last_complete_snapshot_id"],
            ),
        )
        current = conn.execute(
            """SELECT * FROM creator_update_schedule
            WHERE creator_id=%s AND creator_scene=%s FOR UPDATE""",
            (creator_id, scope.scene.value),
        ).fetchone()
        assert current
        return dict(current)

    # -- reconciliation ------------------------------------------------------------------

    def _reconcile_in_flight(self, conn: Any) -> int:
        rows = conn.execute(
            """SELECT s.*,r.state AS task_state,r.payload->>'failure_reason'
              AS task_failure_reason,pc.platform
            FROM creator_update_schedule s
            JOIN platform_creators pc ON pc.creator_id=s.creator_id
            LEFT JOIN root_tasks r ON r.root_task_id=s.in_flight_root_task_id
            WHERE s.in_flight_root_task_id IS NOT NULL
            FOR UPDATE OF s SKIP LOCKED"""
        ).fetchall()
        for row in rows:
            _reconcile_row(conn, dict(row))
        return len(rows)

    def reconcile_creator(
        self, creator_id: str, scene: CreatorScene = CreatorScene.VIDEO_SQUARE
    ) -> None:
        with self.repository.connect() as conn:
            row = conn.execute(
                """SELECT s.*,r.state AS task_state,r.payload->>'failure_reason'
                  AS task_failure_reason,pc.platform
                FROM creator_update_schedule s
                JOIN platform_creators pc ON pc.creator_id=s.creator_id
                LEFT JOIN root_tasks r ON r.root_task_id=s.in_flight_root_task_id
                WHERE s.creator_id=%s AND s.creator_scene=%s FOR UPDATE OF s""",
                (creator_id, scene.value),
            ).fetchone()
            if not row:
                return
            _reconcile_row(conn, dict(row))

    # -- manual update -------------------------------------------------------------------

    def _require_xingtu_creator(self, creator_id: str) -> None:
        """Creator manual updates are still the Xingtu-only update service (KJX-01 stage D scope).

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
        scope = self.manual_scope
        actor = "product:" + user_id
        operation = "creator.update"
        digest = hashlib.sha256(f"{creator_id}:{operation}".encode()).hexdigest()
        self.reconcile_creator(creator_id, scope.scene)
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
            self._ensure_schedule_row(conn, creator_id, scope)
            # _ensure_schedule_row locks the schedule row.  Reconcile a terminal in-flight task
            # before deciding whether this click must reuse it.
            existing = conn.execute(
                """SELECT s.*,r.state AS task_state,r.payload->>'failure_reason'
                  AS task_failure_reason,pc.platform
                FROM creator_update_schedule s
                JOIN platform_creators pc ON pc.creator_id=s.creator_id
                LEFT JOIN root_tasks r ON r.root_task_id=s.in_flight_root_task_id
                WHERE s.creator_id=%s AND s.creator_scene=%s""",
                (creator_id, scope.scene.value),
            ).fetchone()
            if existing and existing["in_flight_root_task_id"]:
                _reconcile_row(conn, dict(existing))
                existing = conn.execute(
                    """SELECT s.*,r.state AS task_state,r.payload->>'failure_reason'
                      AS task_failure_reason,pc.platform
                    FROM creator_update_schedule s
                    JOIN platform_creators pc ON pc.creator_id=s.creator_id
                    LEFT JOIN root_tasks r ON r.root_task_id=s.in_flight_root_task_id
                    WHERE s.creator_id=%s AND s.creator_scene=%s""",
                    (creator_id, scope.scene.value),
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
            targets = self._targets(scope, [dict(creator)])
            task = self._record(scope, targets, TaskKind.MANUAL_UPDATE, root_task_id=root)
            self._insert_task(conn, task, created_by=user_id, actor=actor)
            conn.execute(
                """UPDATE creator_update_schedule SET
                in_flight_root_task_id=%s,in_flight_claimed_at=now(),
                in_flight_expires_at=%s,last_attempt_at=now(),updated_at=now()
                WHERE creator_id=%s AND creator_scene=%s""",
                (root, utcnow() + IN_FLIGHT_TTL, creator_id, scope.scene.value),
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

    def _service_flags(self, conn: Any) -> dict[str, bool]:
        rows = conn.execute(
            "SELECT platform,creator_scene,enabled FROM creator_update_service"
        ).fetchall()
        return {
            scope_key(row["platform"], row["creator_scene"]): bool(row["enabled"]) for row in rows
        }

    def _has_active_batch(self, conn: Any, scope: UpdateScope) -> bool:
        row = conn.execute(
            """SELECT 1 FROM root_tasks WHERE task_kind='scheduled_update'
            AND platform=%s AND creator_scene=%s AND state <> ALL(%s) LIMIT 1""",
            (scope.platform.value, scope.scene.value, list(TERMINAL_STATES)),
        ).fetchone()
        return row is not None

    def _has_runnable_collection(self, conn: Any, platform: PlatformId) -> bool:
        row = conn.execute(
            """SELECT 1 FROM root_tasks WHERE task_kind='collection' AND platform=%s
            AND state = ANY(%s) LIMIT 1""",
            (platform.value, list(RUNNABLE_STATES)),
        ).fetchone()
        return row is not None

    def _has_eligible_unit(self, conn: Any, platform: PlatformId) -> bool:
        row = conn.execute(
            """SELECT 1 FROM execution_units u
            JOIN execution_unit_platform_bindings b ON b.unit_id=u.unit_id
            WHERE 'scheduled_update' = ANY(u.allowed_task_kinds)
              AND b.platform=%s AND b.enabled=true
              AND u.state <> 'QUARANTINED' LIMIT 1""",
            (platform.value,),
        ).fetchone()
        return row is not None

    def _enroll_scope(self, conn: Any, scope: UpdateScope) -> int:
        rows = self._enrollment_rows(conn, scope)
        inserted = 0
        for row in rows:
            base = row["last_complete_at"] or row["data_updated_at"] or utcnow()
            next_due, tier, days = _next_due(base, _decimal(row["followers_count"]))
            result = conn.execute(
                """INSERT INTO creator_update_schedule(
                creator_id,creator_scene,next_due_at,tier,interval_days,last_success_at,
                last_success_snapshot_id)
                VALUES(%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(creator_id,creator_scene) DO NOTHING""",
                (
                    row["creator_id"],
                    scope.scene.value,
                    next_due,
                    tier,
                    days,
                    row["last_complete_at"],
                    row["last_complete_snapshot_id"],
                ),
            )
            inserted += int(result.rowcount)
        return inserted

    def _enrollment_rows(self, conn: Any, scope: UpdateScope) -> list[dict[str, Any]]:
        if scope.platform == PlatformId.DOUYIN_XINGTU and scope.scene == CreatorScene.VIDEO_SQUARE:
            return _many(
                conn,
                """SELECT c.creator_id,c.followers_count,c.data_updated_at,
                (SELECT si.captured_at FROM douyin_xingtu_creator_snapshot_index si
                 WHERE si.creator_id=c.creator_id AND si.pipeline_complete=true
                 ORDER BY si.captured_at DESC LIMIT 1) AS last_complete_at,
                (SELECT si.snapshot_id FROM douyin_xingtu_creator_snapshot_index si
                 WHERE si.creator_id=c.creator_id AND si.pipeline_complete=true
                 ORDER BY si.captured_at DESC LIMIT 1) AS last_complete_snapshot_id
                FROM douyin_xingtu_creator_current c
                LEFT JOIN creator_update_schedule u
                  ON u.creator_id=c.creator_id AND u.creator_scene='video_square'
                WHERE u.creator_id IS NULL""",
            )
        if scope.scene == CreatorScene.LIVE_SQUARE:
            star_filter = (
                "AND l.platform_star_id IS NOT NULL"
                if scope.platform == PlatformId.KUAISHOU_JUXING
                else ""
            )
            return _many(
                conn,
                f"""SELECT l.creator_id,l.followers_count,l.data_updated_at,
                (SELECT cs.created_at FROM creator_snapshots cs
                 WHERE cs.creator_id=l.creator_id AND cs.creator_scene='live_square'
                   AND COALESCE((cs.payload->>'pipeline_complete')::boolean,false)
                 ORDER BY cs.created_at DESC,cs.snapshot_id DESC LIMIT 1) AS last_complete_at,
                (SELECT cs.snapshot_id FROM creator_snapshots cs
                 WHERE cs.creator_id=l.creator_id AND cs.creator_scene='live_square'
                   AND COALESCE((cs.payload->>'pipeline_complete')::boolean,false)
                 ORDER BY cs.created_at DESC,cs.snapshot_id DESC LIMIT 1)
                   AS last_complete_snapshot_id
                FROM creator_live_current l
                LEFT JOIN creator_update_schedule u
                  ON u.creator_id=l.creator_id AND u.creator_scene='live_square'
                WHERE l.platform=%s AND u.creator_id IS NULL {star_filter}""",
                (scope.platform.value,),
            )
        # Juxing video: only identities whose verified detail locator is known can be scheduled.
        return _many(
            conn,
            """SELECT pc.creator_id,
            (pc.projection->'basic.followers'->'value'->>'amount')::numeric AS followers_count,
            latest.created_at AS data_updated_at,
            complete.created_at AS last_complete_at,
            complete.snapshot_id AS last_complete_snapshot_id
            FROM platform_creators pc
            JOIN LATERAL (
              SELECT cs.created_at FROM creator_snapshots cs
              WHERE cs.creator_id=pc.creator_id AND cs.creator_scene='video_square'
              ORDER BY cs.created_at DESC,cs.snapshot_id DESC LIMIT 1
            ) latest ON true
            LEFT JOIN LATERAL (
              SELECT cs.created_at,cs.snapshot_id FROM creator_snapshots cs
              WHERE cs.creator_id=pc.creator_id AND cs.creator_scene='video_square'
                AND COALESCE((cs.payload->>'pipeline_complete')::boolean,false)
              ORDER BY cs.created_at DESC,cs.snapshot_id DESC LIMIT 1
            ) complete ON true
            LEFT JOIN creator_update_schedule u
              ON u.creator_id=pc.creator_id AND u.creator_scene='video_square'
            WHERE pc.platform='kuaishou_juxing' AND pc.video_homepage IS NOT NULL
              AND u.creator_id IS NULL""",
        )

    def _due_rows(self, conn: Any, scope: UpdateScope) -> list[dict[str, Any]]:
        limit = self.batch_size
        if scope.platform == PlatformId.DOUYIN_XINGTU and scope.scene == CreatorScene.VIDEO_SQUARE:
            return _many(
                conn,
                """SELECT u.creator_id,c.platform_creator_id
                FROM creator_update_schedule u
                JOIN douyin_xingtu_creator_current c USING(creator_id)
                WHERE u.creator_scene='video_square'
                  AND u.next_due_at <= now() AND u.in_flight_root_task_id IS NULL
                ORDER BY u.next_due_at,u.creator_id
                LIMIT %s
                FOR UPDATE OF u SKIP LOCKED""",
                (limit,),
            )
        if scope.scene == CreatorScene.LIVE_SQUARE:
            return _many(
                conn,
                """SELECT u.creator_id,l.platform_creator_id,l.platform_star_id
                FROM creator_update_schedule u
                JOIN creator_live_current l USING(creator_id)
                WHERE u.creator_scene='live_square' AND l.platform=%s
                  AND u.next_due_at <= now() AND u.in_flight_root_task_id IS NULL
                ORDER BY u.next_due_at,u.creator_id
                LIMIT %s
                FOR UPDATE OF u SKIP LOCKED""",
                (scope.platform.value, limit),
            )
        return _many(
            conn,
            """SELECT u.creator_id,pc.platform_creator_id,pc.video_homepage
            FROM creator_update_schedule u
            JOIN platform_creators pc USING(creator_id)
            WHERE u.creator_scene='video_square' AND pc.platform='kuaishou_juxing'
              AND pc.video_homepage IS NOT NULL
              AND u.next_due_at <= now() AND u.in_flight_root_task_id IS NULL
            ORDER BY u.next_due_at,u.creator_id
            LIMIT %s
            FOR UPDATE OF u SKIP LOCKED""",
            (limit,),
        )

    def _create_due_batch(self, conn: Any, scope: UpdateScope) -> int:
        due = self._due_rows(conn, scope)
        if not due:
            return 0
        targets = self._targets(scope, [dict(row) for row in due])
        task = self._record(scope, targets, TaskKind.SCHEDULED_UPDATE)
        self._insert_task(conn, task, created_by=None)
        conn.execute(
            """UPDATE creator_update_schedule SET
            in_flight_root_task_id=%s,in_flight_claimed_at=now(),
            in_flight_expires_at=%s,last_attempt_at=now(),updated_at=now()
            WHERE creator_id = ANY(%s) AND creator_scene=%s""",
            (
                task.root_task_id,
                utcnow() + IN_FLIGHT_TTL,
                [str(row["creator_id"]) for row in due],
                scope.scene.value,
            ),
        )
        return len(due)

    def _write_heartbeat(self, conn: Any, result: dict[str, Any]) -> None:
        errors = {**self.scope_errors}
        errors.update(result.get("errors") or {})
        conn.execute(
            """INSERT INTO creator_update_scheduler_heartbeat(
            singleton,last_tick_at,tick_seconds,available_scopes,scope_errors,last_result,updated_at)
            VALUES(true,now(),%s,%s,%s,%s,now())
            ON CONFLICT(singleton) DO UPDATE SET
              last_tick_at=now(),tick_seconds=EXCLUDED.tick_seconds,
              available_scopes=EXCLUDED.available_scopes,
              scope_errors=EXCLUDED.scope_errors,last_result=EXCLUDED.last_result,
              updated_at=now()""",
            (
                self.tick_seconds,
                Jsonb(sorted(self.scopes)),
                Jsonb(errors),
                Jsonb(result),
            ),
        )

    def scheduler_tick(self) -> dict[str, Any]:
        with self.repository.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(904052)")
            reconciled = self._reconcile_in_flight(conn)
            flags = self._service_flags(conn)
            result: dict[str, Any] = {
                "reconciled": reconciled,
                "enrolled": 0,
                "created": 0,
                "skipped": 0,
                "groups": {},
                "errors": {},
                "available": sorted(self.scopes),
            }
            for key, scope in self.scopes.items():
                group: dict[str, Any] = {
                    "enrolled": 0,
                    "created": 0,
                    "skipped": 0,
                    "reasons": [],
                }
                if not flags.get(key, False):
                    group["skipped"] = 1
                    group["reasons"].append(
                        "SERVICE_DISABLED" if key in flags else "SERVICE_CONFIG_MISSING"
                    )
                    if key not in flags:
                        result["errors"][key] = "SERVICE_CONFIG_MISSING"
                    result["skipped"] += 1
                    result["groups"][key] = group
                    continue
                conn.execute("SAVEPOINT update_scope")
                try:
                    enrolled = self._enroll_scope(conn, scope)
                    group["enrolled"] = enrolled
                    result["enrolled"] += enrolled
                    if self._has_active_batch(conn, scope):
                        group["skipped"] = 1
                        group["reasons"].append("ACTIVE_BATCH")
                    elif self._has_runnable_collection(conn, scope.platform):
                        group["skipped"] = 1
                        group["reasons"].append("COLLECTION_RUNNABLE")
                    elif not self._has_eligible_unit(conn, scope.platform):
                        group["skipped"] = 1
                        group["reasons"].append("NO_ELIGIBLE_UNIT")
                    else:
                        created = self._create_due_batch(conn, scope)
                        group["created"] = created
                        result["created"] += created
                    if group["skipped"]:
                        result["skipped"] += 1
                    conn.execute("RELEASE SAVEPOINT update_scope")
                except Exception as exc:  # noqa: BLE001 - one scope must not stop the others
                    conn.execute("ROLLBACK TO SAVEPOINT update_scope")
                    conn.execute("RELEASE SAVEPOINT update_scope")
                    reason = type(exc).__name__
                    if isinstance(exc, CollectorError):
                        reason = f"{exc.code}:{exc.reason}"
                    result["errors"][key] = reason
                    group["error"] = reason
                    group["skipped"] = 1
                    group["reasons"].append("SCOPE_FAILED")
                    result["skipped"] += 1
                result["groups"][key] = group
            self._write_heartbeat(conn, result)
            return result

    # -- status --------------------------------------------------------------------------

    def status(self, creator_id: str) -> CreatorUpdateStatus:
        creator_id = _validated_uuid(creator_id, "CREATOR_NOT_FOUND")
        self._require_xingtu_creator(creator_id)
        with self.repository.connect() as conn:
            self._ensure_schedule_row(conn, creator_id, self.manual_scope)
        self.reconcile_creator(creator_id, CreatorScene.VIDEO_SQUARE)
        with self.repository.connect() as conn:
            row = conn.execute(
                """SELECT u.*,c.data_updated_at,r.state AS task_state
                FROM creator_update_schedule u
                JOIN douyin_xingtu_creator_current c USING(creator_id)
                LEFT JOIN root_tasks r ON r.root_task_id=u.in_flight_root_task_id
                WHERE u.creator_id=%s AND u.creator_scene='video_square'""",
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

    # -- operational helpers -------------------------------------------------------------

    def enroll_group(self, key: str) -> int:
        """Enroll missing plan rows for one scope (used by the scheduler and acceptance tools)."""
        scope = self.scopes.get(key)
        if scope is None:
            raise CollectorError("UNSUPPORTED_FILTER", "UPDATE_SCOPE_NOT_CONFIGURED")
        with self.repository.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(904052)")
            return self._enroll_scope(conn, scope)


def reconcile_update_task(repository: Repository, root_task_id: str) -> int:
    """Release one update task's in-flight schedule rows and advance/back off.

    Called when a task reaches a terminal state, independent of UI reads or the next
    scheduler tick.  It is idempotent: rows already released are simply absent.
    """
    with repository.connect() as conn:
        rows = conn.execute(
            """SELECT s.*,r.state AS task_state,r.payload->>'failure_reason'
              AS task_failure_reason,pc.platform
            FROM creator_update_schedule s
            JOIN platform_creators pc ON pc.creator_id=s.creator_id
            LEFT JOIN root_tasks r ON r.root_task_id=s.in_flight_root_task_id
            WHERE s.in_flight_root_task_id=%s
            FOR UPDATE OF s""",
            (root_task_id,),
        ).fetchall()
        for row in rows:
            _reconcile_row(conn, dict(row))
        return len(rows)
