"""Management read model and switch mutation for the four scheduled-update services.

The scheduler table stays the single source of truth for creator cadence.  This module only adds
an operator-facing view over ``creator_update_service``, ``creator_update_schedule``, the latest
scheduled root task and the scheduler heartbeat.  It never creates update tasks.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from .domain import CollectorError, CreatorScene, PlatformId, TaskStatus, utcnow
from .product_models import (
    CreatorUpdateServicePage,
    CreatorUpdateServiceView,
    CreatorUpdateTaskSummary,
)
from .product_queries import task_stage
from .repository import Repository

EXPECTED_SCOPES: tuple[tuple[PlatformId, CreatorScene], ...] = (
    (PlatformId.DOUYIN_XINGTU, CreatorScene.VIDEO_SQUARE),
    (PlatformId.DOUYIN_XINGTU, CreatorScene.LIVE_SQUARE),
    (PlatformId.KUAISHOU_JUXING, CreatorScene.VIDEO_SQUARE),
    (PlatformId.KUAISHOU_JUXING, CreatorScene.LIVE_SQUARE),
)
MIN_STALE_SECONDS = 60.0
STALE_TICK_MULTIPLIER = 3.0
TERMINAL_STATES = (
    "COMPLETED",
    "PARTIAL_COMPLETED",
    "CANCELLED",
    "FAILED",
    "FAILED_VALIDATION",
)


class CreatorUpdateServiceAdmin:
    def __init__(self, repository: Repository):
        self.repository = repository

    # -- reads ---------------------------------------------------------------------------

    @staticmethod
    def _heartbeat(conn: Any) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT * FROM creator_update_scheduler_heartbeat WHERE singleton=true"
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _alive(heartbeat: dict[str, Any] | None) -> tuple[bool, float | None]:
        if not heartbeat:
            return False, None
        tick = float(heartbeat.get("tick_seconds") or 60.0)
        threshold = max(MIN_STALE_SECONDS, tick * STALE_TICK_MULTIPLIER)
        return utcnow() - heartbeat["last_tick_at"] <= timedelta(seconds=threshold), tick

    @staticmethod
    def _flags(conn: Any) -> dict[str, bool]:
        rows = conn.execute(
            "SELECT platform,creator_scene,enabled FROM creator_update_service"
        ).fetchall()
        return {f"{row['platform']}:{row['creator_scene']}": bool(row["enabled"]) for row in rows}

    @staticmethod
    def _stats(conn: Any, platform: PlatformId, scene: CreatorScene) -> dict[str, Any]:
        return dict(
            conn.execute(
                """SELECT
                  count(*) AS enrolled,
                  count(*) FILTER (
                    WHERE s.next_due_at <= now() AND s.in_flight_root_task_id IS NULL
                  ) AS due,
                  count(*) FILTER (WHERE s.in_flight_root_task_id IS NOT NULL) AS in_flight,
                  min(s.next_due_at) FILTER (
                    WHERE s.in_flight_root_task_id IS NULL
                  ) AS next_due_at,
                  max(s.last_attempt_at) AS last_attempt_at,
                  max(s.last_success_at) AS last_success_at
                FROM creator_update_schedule s
                JOIN platform_creators pc USING(creator_id)
                WHERE s.creator_scene=%s AND pc.platform=%s""",
                (scene.value, platform.value),
            ).fetchone()
        )

    @staticmethod
    def _latest_task(
        conn: Any, platform: PlatformId, scene: CreatorScene
    ) -> CreatorUpdateTaskSummary | None:
        row = conn.execute(
            """SELECT root_task_id,state,created_at,completed_at,payload
            FROM root_tasks
            WHERE task_kind='scheduled_update' AND platform=%s AND creator_scene=%s
            ORDER BY created_at DESC,root_task_id DESC LIMIT 1""",
            (platform.value, scene.value),
        ).fetchone()
        if not row:
            return None
        payload = row.get("payload") or {}
        state = TaskStatus(row["state"])
        # ``target_count`` is a TaskRecord property, not a stored payload field; scheduled batches
        # carry their seeded targets in update_targets.  Prefer an explicit legacy value when a
        # plan-based payload happens to contain one, otherwise derive it from the target list.
        update_targets = payload.get("update_targets") or []
        target_count = int(payload.get("target_count") or len(update_targets))
        return CreatorUpdateTaskSummary(
            root_task_id=str(row["root_task_id"]),
            state=state,
            stage=task_stage(state),
            created_at=row["created_at"],
            completed_at=row.get("completed_at"),
            failure_reason=payload.get("failure_reason"),
            target_count=target_count,
            valid_count=int(payload.get("valid_count") or 0),
            profile_complete_count=int(payload.get("profile_complete_count") or 0),
        )

    @staticmethod
    def _missing_targets(conn: Any, platform: PlatformId, scene: CreatorScene) -> int:
        """Eligible creators that cannot be scheduled because their detail locator is unknown.

        Only the two juxing paths can have this gap: juxing identities are userIds while the
        verified detail routes use starId.  Xingtu identities already carry their route id.
        """
        if platform != PlatformId.KUAISHOU_JUXING:
            return 0
        if scene == CreatorScene.VIDEO_SQUARE:
            row = conn.execute(
                """SELECT count(*) AS n FROM platform_creators pc
                WHERE pc.platform='kuaishou_juxing' AND pc.video_homepage IS NULL
                  AND EXISTS (
                    SELECT 1 FROM creator_snapshots cs
                    WHERE cs.creator_id=pc.creator_id AND cs.creator_scene='video_square'
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM creator_update_schedule u
                    WHERE u.creator_id=pc.creator_id AND u.creator_scene='video_square'
                  )"""
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT count(*) AS n FROM creator_live_current l
                WHERE l.platform='kuaishou_juxing' AND l.platform_star_id IS NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM creator_update_schedule u
                    WHERE u.creator_id=l.creator_id AND u.creator_scene='live_square'
                  )"""
            ).fetchone()
        return int(row["n"]) if row else 0

    def _view(
        self,
        conn: Any,
        platform: PlatformId,
        scene: CreatorScene,
        *,
        flags: dict[str, bool],
        heartbeat: dict[str, Any] | None,
        alive: bool,
    ) -> CreatorUpdateServiceView:
        key = f"{platform.value}:{scene.value}"
        enabled = flags.get(key, False)
        config_missing = key not in flags
        available: set[str] | None = None
        errors: dict[str, str] = {}
        if heartbeat:
            available = {str(item) for item in (heartbeat.get("available_scopes") or [])}
            errors = {
                str(name): str(reason)
                for name, reason in (heartbeat.get("scope_errors") or {}).items()
            }
        registry_available = (key in available) if available is not None else None
        unavailable_reason: str | None = None
        if config_missing:
            unavailable_reason = "SERVICE_CONFIG_MISSING"
        elif not enabled:
            unavailable_reason = None
        elif not alive:
            unavailable_reason = "SCHEDULER_NOT_RUNNING"
        elif registry_available is False:
            unavailable_reason = errors.get(key, "SCOPE_NOT_REPORTED")
        effective = enabled and alive and registry_available is not False
        stats = self._stats(conn, platform, scene)
        return CreatorUpdateServiceView(
            platform=platform.value,
            creator_scene=scene,
            enabled=enabled,
            effective_enabled=effective,
            scheduler_alive=alive,
            scheduler_last_tick_at=heartbeat["last_tick_at"] if heartbeat else None,
            registry_available=registry_available,
            unavailable_reason=unavailable_reason,
            enrolled_count=int(stats.get("enrolled") or 0),
            due_count=int(stats.get("due") or 0),
            in_flight_count=int(stats.get("in_flight") or 0),
            missing_target_count=self._missing_targets(conn, platform, scene),
            next_due_at=stats.get("next_due_at"),
            last_attempt_at=stats.get("last_attempt_at"),
            last_success_at=stats.get("last_success_at"),
            last_task=self._latest_task(conn, platform, scene),
        )

    def list_services(self) -> CreatorUpdateServicePage:
        with self.repository.connect() as conn:
            heartbeat = self._heartbeat(conn)
            alive, tick = self._alive(heartbeat)
            flags = self._flags(conn)
            items = [
                self._view(
                    conn,
                    platform,
                    scene,
                    flags=flags,
                    heartbeat=heartbeat,
                    alive=alive,
                )
                for platform, scene in EXPECTED_SCOPES
            ]
        return CreatorUpdateServicePage(
            items=items,
            scheduler_alive=alive,
            scheduler_last_tick_at=heartbeat["last_tick_at"] if heartbeat else None,
            scheduler_tick_seconds=tick,
        )

    # -- writes --------------------------------------------------------------------------

    def set_enabled(
        self,
        platform: str,
        scene: CreatorScene,
        enabled: bool,
        *,
        user_id: str,
    ) -> CreatorUpdateServiceView:
        value = PlatformId(platform)
        if (value, scene) not in EXPECTED_SCOPES:
            raise CollectorError("UNSUPPORTED_FILTER", "UPDATE_SERVICE_NOT_CONFIGURED")
        actor = "product:" + user_id
        with self.repository.connect() as conn:
            conn.execute(
                """INSERT INTO creator_update_service(
                platform,creator_scene,enabled,updated_at,updated_by)
                VALUES(%s,%s,%s,now(),%s)
                ON CONFLICT(platform,creator_scene) DO UPDATE SET
                  enabled=EXCLUDED.enabled,updated_at=now(),updated_by=EXCLUDED.updated_by""",
                (value.value, scene.value, bool(enabled), user_id),
            )
            conn.execute(
                """INSERT INTO audit_logs(actor,actor_user_id,action)
                VALUES(%s,%s,%s)""",
                (
                    actor,
                    user_id,
                    f"creator_update_service.set:{value.value}:{scene.value}:{int(bool(enabled))}",
                ),
            )
        page = self.list_services()
        return next(
            item
            for item in page.items
            if item.platform == value.value and item.creator_scene == scene
        )
