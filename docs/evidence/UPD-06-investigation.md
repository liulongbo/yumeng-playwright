# UPD-06 现状调查与基线（2026-11-06）

## 1. 环境与检查方式

- 本机 macOS 原生 `local-main` 栈：PostgreSQL `127.0.0.1:55432`（`xingtu_development`，schema 21）、Redis `127.0.0.1:56379`、Temporal `127.0.0.1:57233`；应用服务在调查开始时全部未运行，依赖服务也未运行，随后按 `docs/evidence/OPS-02-local-restart-2026-10-22.md` 的底层入口启动依赖（未改业务数据）。
- 只读查询使用项目 `.venv` + `psycopg`，未打印 DSN、口令或平台正文。
- 方案比对依据：`backend/src/xingtu/creator_update.py`、`product_cli.py`、`worker.py`、`repository.py`、`migrations/018`、`021`、`live_update.py`、`juxing_adapter.py`、`juxing_live_adapter.py`、`xingtu_live_adapter.py`、`product_api.py`、`frontend/src/App.tsx`、`docs/tasks/UPD-04.md`、`docs/decisions/DEC-017/018`。

## 2. 现有定时更新链路（实施前）

- 调度：`CreatorUpdateService.scheduler_tick` + `xingtu-product update-scheduler`；`pg_advisory_xact_lock(904052)`、单活跃批次、到期 `FOR UPDATE SKIP LOCKED`、失败退避、终态 reconcile 已实现。
- 计划表：`creator_update_schedule` 主键仅 `creator_id`；所有查询只服务巨量星图短视频：
  - enrollment 只读 `douyin_xingtu_creator_current` + `douyin_xingtu_creator_snapshot_index`；
  - 到期/目标只读同一当前表；
  - `_require_xingtu_creator` 显式拒绝聚星；
  - `scheduler_tick` 只加载一个 registry，只建一种 task。
- 执行：`root_tasks.task_kind='scheduled_update'` → 统一任务中心 → `claim_unassigned_update` → `CollectionWorkflow`/`collect_segment_v1` → `Engine.run_update`，复用执行单元/租约/优先级；不搜索、不 P1。
- 持久化：短视频写 `platform_creators.projection`（聚星）/`douyin_xingtu_creator_current`（星图）；直播写 `creator_live_current`；快照有 `creator_scene`。
- 终态结算：`Repository.edit` 只在 `creator_scene='video_square'` 时 reconcile，直播更新终态不结算。
- 手动更新：`CreatorUpdateService`（星图短视频）与 `LiveCreatorUpdateService`（两平台直播，手动、不写计划表）。
- 前端：`/settings` 是「当前里程碑不包含设置页面」占位，没有自动更新管理页。

## 3. 当前运行状态（关键事实）

- **定时更新调度器代码存在但进程未运行**：`.runtime/dev/pids.tsv` 无 `update-scheduler`；OPS-02/03/04 均记录“按用户决定未启动”；`scripts/dev.sh` 有 `SKIP_UPDATE_SCHEDULER`。
- `creator_update_schedule` 有 **201 行、148 行到期**，全部属于巨量星图短视频；历史 `root_tasks` 中 `scheduled_update` 24 条（2 COMPLETED、20 PARTIAL、1 FAILED、1 CANCELLED）。
- 两执行单元均 `READY`：`unit-local-mac-02`（星图，binding 启用；聚星 binding 关闭）与 `unit-local-mac-03-juxing`（聚星，binding 启用）；`allowed_task_kinds` 均含三类任务。
- 数据库现状（调查时 schema=21）：
  - `platform_creators`：星图 390 / 聚星 232；
  - `creator_live_current`：星图 189 / 聚星 151；
  - 视频快照覆盖：星图 201 位 / 聚星 81 位；
  - 同 `creator_id` 双场景交集：**0**（不是代码限制；当时采集样本未覆盖同一达人两场景）。
- 聚星短视频 81 位均可从最新视频快照的 root task checkpoint 解析 `verified_homepage`（`userId→starId`），回填可行。

## 4. 三个真实缺口

1. **计划维度**：单主键 + 单场景查询，无法为同一达人建立短视频/直播两条计划，也无法按平台/场景独立到期、in-flight、失败与下次时间。
2. **调度范围**：单 registry、单当前表、单主键、无分组开关、无组内/组间隔离、无调度器心跳；一个组的失败或关闭会（至少全局单活跃批次下）影响其他组。
3. **聚星短视频定向更新**：更新服务入口拒绝聚星；身份 `userId` 与详情路由 `starId` 之间没有持久化定位；`KuaishouJuxingAdapter.profile()` 要求已有 search page，而 `Engine.run_update` 不执行 `prepare`，实际首次调度返回 `SESSION_INDETERMINATE:JUXING_SEARCH_PAGE_MISSING`（真实隔离验收中复现，已最小修复：`_ensure_search_page`）。Adapter/`collect_module`/持久化本身可复用，无需重写。

## 5. 实施后主库状态（2026-11-06，迁移 022 已应用）

- 备份：`.runtime/backups/upd06-20261106/xingtu_development.dump`（68MB，498 TOC entries）。
- schema=22；`creator_update_schedule` 主键 `(creator_id, creator_scene)`，201 legacy 行均为 `video_square`。
- `creator_update_service`：星图短视频 `enabled=true`，其余三组 `false`。
- `platform_creators.video_homepage`：回填 81/81（dry-run eligible=81/resolvable=81/unresolved=0；apply filled=81；再次 dry-run eligible=0）。
- `creator_update_scheduler_heartbeat` 0 行；主站 scheduler 未启动（保留调查时行为），`GET /api/update-services` 显示 `scheduler_alive=false`、星图短视频 `effective_enabled=false`、到期 148。
- 主站应用进程（API/Intake/两平台 Worker/前端）已按原进程集合恢复，未启动 scheduler；`dev.sh` 队列检查在线。

## 6. 结论

- 复用现有 `creator_update_schedule`、周期/退避、统一任务中心、执行单元与 `Engine.run_update` 是可行且最小的方案；不需要新调度架构。
- 需要的最小新增：场景维度、四组开关、调度器心跳、按组建批/隔离、worker 启动闸门、聚星短视频定位持久化/回填、聚星 Adapter 的定向更新 search page 支持、管理 API/页面。
- 真实双场景达人需要**真实采集准备**（本次通过星图直播按 star_id 关键词采集 A1 视频达人，得到同一 `creator_id` 的视频 2 份 + 直播快照，随后验证计划隔离）。
