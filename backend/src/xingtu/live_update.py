"""Manual update service for live-square creator profiles.

The video update service and its schedule table are intentionally untouched: live updates use the
existing unified task centre / execution-unit pool, but never enroll in the scheduled-update table.
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from .contracts import PlatformRegistry
from .domain import (
    Checkpoint,
    CollectorError,
    CreatorRef,
    CreatorScene,
    TaskKind,
    TaskRecord,
    TaskStatus,
    uid,
)
from .product_models import CreatorUpdateResponse, CreatorUpdateStatus
from .product_queries import task_stage
from .repository import Repository

TERMINAL = {
    TaskStatus.CANCELLED,
    TaskStatus.COMPLETED,
    TaskStatus.PARTIAL_COMPLETED,
    TaskStatus.FAILED,
    TaskStatus.FAILED_VALIDATION,
}


def _validated_uuid(value: str, reason: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise CollectorError("INVALID_FORM", reason) from exc


class LiveCreatorUpdateService:
    """Create and report one-creator live update tasks without the schedule table."""

    def __init__(
        self,
        repository: Repository,
        registries: dict[str, PlatformRegistry],
    ) -> None:
        self.repository = repository
        self.registries = registries

    def _registry(self, platform: str) -> PlatformRegistry:
        registry = self.registries.get(f"{platform}:{CreatorScene.LIVE_SQUARE.value}")
        if registry is None:
            raise CollectorError("UNSUPPORTED_FILTER", "LIVE_UPDATE_NOT_CONFIGURED")
        return registry

    @staticmethod
    def _homepage(platform: str, platform_creator_id: str, star_id: str | None) -> str:
        if platform == "douyin_xingtu":
            return f"https://www.xingtu.cn/ad/creator/author/douyin/{platform_creator_id}/10"
        if not star_id:
            raise CollectorError("UNSUPPORTED_FILTER", "LIVE_STAR_ID_MISSING")
        return f"https://k.kuaishou.com/#/live-promotion/star/{star_id}?openBy=user"

    def _target(self, row: dict[str, Any], registry: PlatformRegistry) -> CreatorRef:
        platform = row["platform"]
        return CreatorRef(
            platform=platform,
            platform_creator_id=str(row["platform_creator_id"]),
            verified_homepage=self._homepage(
                platform,
                str(row["platform_creator_id"]),
                row.get("platform_star_id"),
            ),
            first_position=0,
            creator_id=str(row["creator_id"]),
        )

    def create_manual_update(
        self, creator_id: str, *, user_id: str, idempotency_key: str
    ) -> CreatorUpdateResponse:
        creator_id = _validated_uuid(creator_id, "CREATOR_NOT_FOUND")
        if not idempotency_key.strip() or len(idempotency_key) > 200:
            raise CollectorError("INVALID_FORM", "INVALID_IDEMPOTENCY_KEY")
        actor = "product:" + user_id
        operation = "creator.live_update"
        digest = hashlib.sha256(f"{creator_id}:{operation}".encode()).hexdigest()
        with self.repository.connect() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"{user_id}:{operation}:{idempotency_key}",),
            )
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"{operation}:{creator_id}",),
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
            row = conn.execute(
                """SELECT creator_id,platform,platform_creator_id,platform_star_id
                FROM creator_live_current WHERE creator_id=%s FOR UPDATE""",
                (creator_id,),
            ).fetchone()
            if not row:
                raise CollectorError("INVALID_FORM", "CREATOR_NOT_FOUND")
            platform = str(row["platform"])
            registry = self._registry(platform)
            existing = conn.execute(
                """SELECT root_task_id,state FROM root_tasks
                WHERE platform=%s AND creator_scene='live_square' AND task_kind='manual_update'
                  AND state NOT IN ('CANCELLED','COMPLETED','PARTIAL_COMPLETED','FAILED',
                                    'FAILED_VALIDATION')
                  AND payload->'update_targets' @> %s
                ORDER BY created_at DESC LIMIT 1""",
                (platform, Jsonb([{"creator_id": creator_id}])),
            ).fetchone()
            if existing:
                response = CreatorUpdateResponse(
                    root_task_id=str(existing["root_task_id"]),
                    status=TaskStatus(existing["state"]),
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
            target = self._target(dict(row), registry)
            checkpoint = Checkpoint(
                conditions_digest="live-update:" + digest,
                adapter_version=registry.adapter_version,
                contract_version=registry.contract_version,
                profile_module_keys=[item.key for item in registry.modules],
                profile_checkpoint_versions={
                    item.key: item.checkpoint_version for item in registry.modules
                },
                featured_collection_types=[],
                featured_checkpoint_versions={},
            )
            from .domain import Candidate

            checkpoint.candidates = [Candidate(ref=target)]
            root_task_id = uid()
            task = TaskRecord(
                root_task_id=root_task_id,
                task_id=uid(),
                attempt_id=uid(),
                plan=None,
                task_kind=TaskKind.MANUAL_UPDATE,
                creator_scene=CreatorScene.LIVE_SQUARE,
                update_targets=[target],
                state=TaskStatus.QUEUED,
                execution_unit_id="",
                checkpoint=checkpoint,
                source="internal_acceptance",
            )
            conn.execute(
                """INSERT INTO root_tasks(
                root_task_id,state,version,unit_id,payload,created_by,origin_root_task_id,
                task_kind,platform,creator_scene)
                VALUES(%s,%s,%s,NULL,%s,%s,NULL,%s,%s,%s)""",
                (
                    task.root_task_id,
                    task.state.value,
                    task.version,
                    Jsonb(task.model_dump(mode="json", exclude={"checkpoint"})),
                    user_id,
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
                "INSERT INTO audit_logs(root_task_id,actor,actor_user_id,action)"
                " VALUES(%s,%s,%s,'creator.live_update.create')",
                (task.root_task_id, actor, user_id),
            )
            response = CreatorUpdateResponse(root_task_id=root_task_id, reused=False)
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
            return response

    def status(self, creator_id: str) -> CreatorUpdateStatus:
        creator_id = _validated_uuid(creator_id, "CREATOR_NOT_FOUND")
        with self.repository.connect() as conn:
            exists = conn.execute(
                "SELECT platform FROM creator_live_current WHERE creator_id=%s", (creator_id,)
            ).fetchone()
            if not exists:
                raise CollectorError("INVALID_FORM", "CREATOR_NOT_FOUND")
            in_flight = conn.execute(
                """SELECT root_task_id,state FROM root_tasks
                WHERE creator_scene='live_square' AND task_kind='manual_update'
                  AND state NOT IN ('CANCELLED','COMPLETED','PARTIAL_COMPLETED','FAILED',
                                    'FAILED_VALIDATION')
                  AND payload->'update_targets' @> %s
                ORDER BY created_at DESC LIMIT 1""",
                (Jsonb([{"creator_id": creator_id}]),),
            ).fetchone()
            last = conn.execute(
                """SELECT snapshot_id,created_at FROM creator_snapshots
                WHERE creator_id=%s AND creator_scene='live_square'
                ORDER BY created_at DESC,snapshot_id DESC LIMIT 1""",
                (creator_id,),
            ).fetchone()
            success = conn.execute(
                """SELECT snapshot_id,created_at FROM creator_snapshots
                WHERE creator_id=%s AND creator_scene='live_square'
                  AND COALESCE((payload->>'pipeline_complete')::boolean,false)=true
                ORDER BY created_at DESC,snapshot_id DESC LIMIT 1""",
                (creator_id,),
            ).fetchone()
            failure = conn.execute(
                """SELECT payload->>'failure_reason' AS reason FROM root_tasks
                WHERE creator_scene='live_square' AND task_kind='manual_update'
                  AND payload->'update_targets' @> %s
                ORDER BY created_at DESC LIMIT 1""",
                (Jsonb([{"creator_id": creator_id}]),),
            ).fetchone()
        state = TaskStatus(in_flight["state"]) if in_flight else None
        return CreatorUpdateStatus(
            creator_id=creator_id,
            in_flight_root_task_id=str(in_flight["root_task_id"]) if in_flight else None,
            task_status=state,
            task_stage=task_stage(state) if state else None,
            last_write_at=last["created_at"] if last else None,
            last_success_at=success["created_at"] if success else None,
            last_success_snapshot_id=str(success["snapshot_id"]) if success else None,
            next_due_at=None,
            tier=None,
            interval_days=None,
            consecutive_failures=0,
            last_failure_reason=(failure or {}).get("reason") if failure else None,
        )
