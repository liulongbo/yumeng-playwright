# UPD-06：四场景定时自动更新与独立开关（设计）

- 日期：2026-11-06
- 状态：已实施（2026-11-06）；隔离库真实四组验收通过，见 `docs/evidence/UPD-06-acceptance.md`
- 关联：UPD-01、UPD-04、UPD-05；LIVE-02、LIVE-02G、LIVE-03；KJX-01；DEC-017、DEC-018、DEC-022

## 1. 目标

在保留现有「巨量星图短视频定时更新」语义的前提下，让四组**已入库**达人按现有周期自动刷新资料，并能独立开启/关闭：

| 平台 | 场景 | 更新计划来源 | 更新契约 |
|---|---|---|---|
| douyin_xingtu | video_square | `douyin_xingtu_creator_current` | `douyin_xingtu.verified.json` |
| douyin_xingtu | live_square | `creator_live_current` | `douyin_xingtu.live.verified.json` |
| kuaishou_juxing | video_square | `platform_creators` + 视频快照 + 详情定位 | `kuaishou_juxing.verified.json` |
| kuaishou_juxing | live_square | `creator_live_current` | `kuaishou_juxing.live.verified.json` |

不新增执行单元、Temporal 队列或工作流；一个 scheduler 进程服务四组。

## 2. 链路

```
管理页 /api/update-services
        │ 开关
        ▼
creator_update_service (4 行)
        │
update-scheduler（单进程，四 scope）
  reconcile in-flight（全部场景）
  逐组 SAVEPOINT：
    enroll 缺失计划（仅开启组）
    检查：开关 / 本组活跃批次 / 本平台普通采集 / 平台可用单元
    到期行 FOR UPDATE SKIP LOCKED
    建 1 个 scheduled_update 批次 + 原子置 in-flight
  写 creator_update_scheduler_heartbeat
        │
统一任务中心 → CollectionWorkflow/collect_segment_v1
        │
执行单元（平台绑定、并发 1、租约）
        │
Engine.run_update（不搜索、不 P1）
  scope.registry 决定 Adapter / 模块 / checkpoint
  scope.homepage 决定目标详情
        │
不可变快照 creator_snapshots(creator_scene)
  ├─ 直播 → creator_live_current
  ├─ 星图短视频 → douyin_xingtu_creator_current + index
  └─ 聚星短视频 → platform_creators.projection
        │
Repository.edit 终态 → reconcile_update_task（全部场景）
```

## 3. 数据库（迁移 022）

### 3.1 计划按场景独立

`creator_update_schedule` 增加 `creator_scene`，主键改为 `(creator_id, creator_scene)`；旧行默认 `video_square`。新增 `(creator_scene, next_due_at)` 部分索引。周期字段、退避、tier、失败计数语义不变。

### 3.2 四组开关

`creator_update_service(platform, creator_scene, enabled, updated_at, updated_by)`，迁移预置：

- 星图短视频：`true`（保留现有代码行为；主站调度器进程当前未运行，因此实际未生效）
- 其余三组：`false`

### 3.3 调度器心跳

`creator_update_scheduler_heartbeat(singleton, last_tick_at, tick_seconds, available_scopes, scope_errors, last_result, updated_at)`。迁移不插行，避免“未运行却在线”。管理页的 `effective_enabled` 同时要求开关、心跳新鲜、契约可用。

### 3.4 聚星短视频详情定位

`platform_creators.video_homepage`（可空）。聚星短视频身份是 `userId`，详情路由需要 `starId`；短视频发布时写入 `ref.verified_homepage`（`COALESCE`，不覆盖已有值），直播发布不写该列。历史行由 `scripts/backfill_video_homepage.py` 从最新视频快照的 root task checkpoint 回填；回填不到位的达人不纳入计划，管理页显示 `missing_target_count`。

### 3.5 回滚影响

迁移 022 与新应用配套。旧代码的 `INSERT ... ON CONFLICT(creator_id)` 在复合主键下不再匹配，回滚应用前必须回滚迁移（或先清理直播计划行）。迁移本身只新增列/表/索引，不重写历史快照、投影或任务。

## 4. 调度语义

### 4.1 开关

- 只控制**新自动更新批次**的创建；普通采集、手动更新不受影响。
- 关闭后已在执行的批次不中断，按既有租约/终态结算。
- 关闭时尚未开始执行的批次：worker 在拿浏览器前检查开关，置 `CANCELLED/UPDATE_SERVICE_DISABLED`；计划行只释放、不计失败、不推进 `next_due_at`，重新开启后仍到期。
- 重新开启：下一次 tick 按现有周期 enrollment/到期判断，不会重复创建同一达人同一场景的 in-flight 任务。

### 4.2 组内单活跃批次、组间独立

每个 `(platform, scene)` 同时最多一个非终态 `scheduled_update` 根任务。不同组互不阻塞；一个组关闭、无可用单元或目标构造失败只影响本组（每组 SAVEPOINT + `scope_errors`）。

### 4.3 资源与优先级

- 到期任务仍未分配单元，由 `claim_unassigned_update` 按 `allowed_task_kinds + platform binding` 认领。
- 同平台仍串行、并发 1；跨平台可并行。
- 保留 `collection > manual_update > scheduled_update` 三层优先级；本组/本平台有 runnable 普通采集时暂不建更新批次。
- `--batch-size` 为**每组每 tick**上限（1–20），默认 5，避免一次提交大量任务。

### 4.4 同达人双场景

同一 `creator_id` 可有两行计划；到期、in-flight、失败、`last_success`、快照全部按 scene 隔离。更新任务只带一个 scene；worker 通过 `UnitConfig.for_scene` 选对应 registry，Adapter 工厂选对应 Adapter。直播只写 `creator_live_current`，短视频只写对应 projection/current，互不覆盖。

## 5. 管理页与 API

```
GET /api/update-services
PUT /api/update-services/{platform}/{creator_scene}  {"enabled": bool}
```

- 复用现有登录、Origin/CSRF、审计；任一已登录媒介可操作（当前系统单角色）。
- 返回四项：开关、当前生效、调度器在线/心跳、契约可用、已纳入/到期/执行中/缺少定位、下次计划、最近尝试/成功、最近批次状态与失败原因。
- 没有可靠来源的字段留空；不用“最近执行时间”冒充成功时间。

前端在既有 `/settings` 占位路由实现 `UpdateServicesPage`，侧栏增加「自动更新」入口；复用 `.panel` / `.unit-table` / `.unit-summary-grid` / `formatDate` / `statusLabel`，不重做后台。

## 6. 初始状态与运行前提

- 迁移后星图短视频开关为开，其余关闭；主站调度器进程保持调查时的现状（未运行）。实际生效需要操作者启动：
  `nohup .venv/bin/xingtu-product update-scheduler --unit-config <unit.json> >>.runtime/logs/update-scheduler.log 2>&1 &`
- 全局控制是调度器进程；分组开关是数据库状态。两者同时满足才产生自动更新。
- 调度器可用 registry：主 unit config + 其他平台 binding + 对应环境变量；可选契约缺失只禁用该组。

## 7. 兼容性

- 星图短视频：周期、退避、批大小、优先级、手动更新和计划行行为不变；新增场景过滤在单场景数据上等价。
- 手动更新：仍只支持星图短视频；聚星手动更新继续保持显式拒绝（本任务不扩展产品功能）。手动直播更新仍不写计划表。
- 采集：搜索/筛选/P1/目标 70 上限/执行单元/Temporal 状态机/历史快照不变。
- 共享代码改动：`Repository.edit` 终态结算范围扩到所有更新场景（直播手动任务无计划行时为空操作）；`persist_creators` 写一个导航列；`Activities.collect` 仅对 scheduled_update 增加开关闸门。

## 8. 验证

- 单元：scope 目标构造、worker 闸门、现有策略回归。
- 集成：迁移 022、四组计划、双场景隔离、开关、组失败隔离、reconcile、回填、管理读模型。
- API/前端：认证/CSRF/四行/开关/离线/最近结果。
- 真实隔离栈：克隆开发库 + 现有已登录 Chrome Profile，四组各 1 位真实达人，验证「计划到期 → scheduler 建任务 → 对应单元执行 → 快照/当前数据 → 计划推进」；另验证开关、双场景、重复/失败/重启、手动更新与普通采集回归。
- 证据：`docs/evidence/UPD-06-*.md`。

## 9. 明确不做

- 不新建调度架构、执行单元、Temporal 队列/工作流。
- 不开发聚星短视频手动更新产品功能。
- 不重做管理后台视觉。
- 不重跑四组 70 位全量采集。
- 不做生产部署、Windows 实机登录验收或 Git 合并。
