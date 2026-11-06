# UPD-06 真实验收报告：四场景定时自动更新与独立开关

- 日期：2026-11-06
- 环境：macOS 本机；隔离库 `xingtu_test_upd06`（克隆 `xingtu_development`，schema 22）；PostgreSQL 55432 / Redis 56379 / Temporal 57233；真实 Chrome + 现有已登录 Profile；执行单元 `unit-local-mac-02`（星图）与 `unit-local-mac-03-juxing`（聚星）；隔离 API 8000 / 前端 5173 / 一个 scheduler（`--batch-size 1 --tick-seconds 5`）。主站 Worker 验收期间停止以避免 Profile 冲突。
- 结论：**CONDITIONAL GO**。四组真实定时更新、独立开关、双场景隔离、重复/重启/取消、手动更新与普通采集回归均 PASS；条件见第 7 节。

## 1. 四组真实定时更新（A）

所有任务均由 scheduler 自动创建（`root_tasks.created_by IS NULL`、`audit_logs.actor='scheduler'`），进入统一任务中心，由平台专属单元执行；非直接调用单达人采集接口。

| 组 | 测试达人（creator_id / 平台 ID） | 任务 ID | 单元 | 结果 | 数据变化 | 下次计划 |
|---|---|---|---|---|---|---|
| 星图短视频 | `0b99f212-0fbe-491e-aff8-5065fb1842f1` / `7480355375695265829` | `c8a2f16a-33b2-441a-b8dd-ee7853c441fc` | unit-local-mac-02 | **COMPLETED 1/1，profile complete 1，pipeline complete** | 视频快照 1→2；新 `fb60fedc-1125-4bd3-a4ba-50b00edec4b7`；current/index `data_updated_at` 推进 | `2026-11-11 15:23:17+08:00`，failures 0 |
| 星图直播 | `52b29755-26c6-4574-ba77-909025bd9f9b` / `7623704992305643547` | `c278ba50-465f-408f-990b-0042805f1656` | unit-local-mac-02 | **COMPLETED 1/1** | 直播快照 2→3；新 `e4c5f14d-e512-4bae-929c-2456aa3c2a0c`；`creator_live_current.latest_snapshot_id` 同步 | `2026-11-13 15:24:17+08:00`，failures 0 |
| 聚星短视频 | `8ac289e4-14bf-40ba-9b7f-f56b1b5b5155` / `148837959` | `f39722b3-edb8-4482-afba-083e6f81c35d` | unit-local-mac-03-juxing | **COMPLETED 1/1**（同 root 重试） | 视频快照 1→2；新 `532a11dc-ae5f-464e-9b94-90751590d0b3`；followers 1899637→1899625；无 live current | `2026-11-07 15:27:00+08:00`，failures 0 |
| 聚星直播 | `0f237f96-e53d-4a53-822c-13b9cea79ddf` / `1768843196` | `ffcd2a5e-7352-4968-a8c2-ca0f679e83cb` | unit-local-mac-03-juxing | **COMPLETED 1/1** | 直播快照 2→3；新 `718cd055-b67b-4228-a69c-d0eaed8f53af`；无视频快照/投影 | `2026-11-07 15:27:54+08:00`，failures 0 |

A3 过程说明（真实暴露并最小修复的缺口）：第一次执行返回 `WAITING_FOR_RESOURCE`，`failure_reason=SESSION_INDETERMINATE:JUXING_SEARCH_PAGE_MISSING`——`KuaishouJuxingAdapter.profile()` 依赖 search page，而 `Engine.run_update` 不执行 `prepare`。按 5.3 授权增加 `_ensure_search_page()`（无 plan 时按合同建立受绑定 video-square 页并校验会话），重启聚星 Worker 后**同一 root 任务重试完成**，未新建重复任务。修复后单测 `test_plan_less_update_establishes_the_bound_video_square_page` 通过。

调度器日志（摘录，节选）：
```
15:21:57 created=1  douyin_xingtu:video_square   (其余 3 组 SERVICE_DISABLED)
15:23:57 created=1  douyin_xingtu:live_square    (其余 SERVICE_DISABLED)
15:24:27 created=1  kuaishou_juxing:video_square (其余 SERVICE_DISABLED)
15:27:23 created=1  kuaishou_juxing:live_square  (三组 enabled 但无到期)
```

## 2. 同达人双场景（C）

准备：原库无双场景达人。通过**真实平台采集**为 A1 星图达人补采直播场景：`POST /api/tasks` 关键词 = star_id `7480355375695265829`，星图直播 target 1；任务 `33c25563-00c9-46cb-8420-4e12db8a6b53` **COMPLETED 1/1**，得到同一 `creator_id` 的：
- 视频快照 2 份（A1 后）；
- 直播快照 1 份（`f99d5644-663c-49bc-b5d7-77d1f625ea10`）；
- 两条独立计划（视频 / 直播）。

| 步骤 | 任务 ID | 结果 | 未更新场景的证据 |
|---|---|---|---|
| 只让直播到期 | `3502f932-ed58-4a37-aa74-a8c2a9922f4f` | COMPLETED | 视频计划 last_success 仍 `fb60fedc…`，next_due 12/06，视频快照仍 2 |
| 只让短视频到期 | `7845da9a-3ec7-4b61-afdb-35d5959a5877` | COMPLETED | 直播计划 last_success 仍 `e2679464…`，next_due 12/06，直播快照仍 2 |

两条计划的 `creator_scene`、`in_flight_root_task_id`、`last_success_snapshot_id`、`next_due_at`、`consecutive_failures` 全程独立；快照表按 scene 隔离，无跨写。

## 3. 独立开关（B）

| 用例 | 操作/任务 | 结果 |
|---|---|---|
| B1 | 关闭星图短视频；星图短视频达人到期；星图直播到期 | 视频组无 task（计划仍到期、in-flight NULL）；直播 task `5e541d93…` COMPLETED；日志 `SERVICE_DISABLED` |
| B2 | 关闭聚星直播；聚星直播达人到期；星图直播到期 | 聚星直播组无 task（计划仍到期）；星图直播 task `28a2d472…` COMPLETED；日志 skipped=2 |
| B3 | 星图短视频关闭时手动更新 | `8f18fa2b-39f1-4b37-9f45-c6bbf089476e` manual_update **COMPLETED**；视频快照 3→4；开关保持关闭 |
| B4 | 星图短视频关闭时普通采集 1 位 | `f08ebeef-c8f0-47be-920a-6e631898959d` collection **COMPLETED 1/1**；开关不变 |
| B5 | 重新开启星图短视频并让达人到期 | `1069c030-a952-473c-89bc-68901f4b316c` **COMPLETED**；恢复调度 |
| B6 | queued 批次 + 关闭 + 启动 Worker | `9d1abca2-0702-424c-893a-d90aaf5e3f72` **CANCELLED / UPDATE_SERVICE_DISABLED**；无新视频快照（仍 5）；计划 `consecutive_failures=0`、`next_due` 仍过去、in-flight NULL |
| B7 | 重启 API + scheduler | 开关持久化：星图视频 false、星图直播 true、聚星视频 true、聚星直播 false；scheduled task 34→34；scheduler 心跳恢复，`scheduler_alive=true` |

关闭只影响新自动批次；手动更新和普通采集不受影响（B3/B4）。

## 4. 重复调度、失败/取消与重启（D）

- 单组单活跃批次：同组第二次 tick 不重复建 task；四组各自独立，互不阻塞（A/B/C 日志）。
- 重启：`scheduled_update` 任务总数 34→34（B7），无重复。
- 受控取消（运行中）：task `7fbc4214-1de9-404e-8ba4-7b1c3af1e6dc`（聚星短视频）取消后 **CANCELLED**，`failure_reason=TASK_CANCELLED:STALE_ATTEMPT_OR_STATE`；计划 `consecutive_failures=1`、`next_due_at=16:45:47`（+1h，符合既有快速重试）、`last_failure_reason` 记录；视频快照仍 2、`platform_creators.projection` md5 不变 → 历史/当前数据保留。
- 执行单元/租约：星图 task 均 `unit-local-mac-02`，聚星 task 均 `unit-local-mac-03-juxing`；终态后 owner/lease 释放，单元 READY。
- `_reconcile_row` 对 `UPDATE_SERVICE_DISABLED` 只释放不记失败；对普通失败/取消沿用 1h/6h/档位退避（单测 `test_backoff_is_capped_by_the_normal_interval`、集成 `test_disabled_cancel_releases_without_a_failure_or_advancing_due`）。

## 5. 证据来源（E）

- scheduler 日志：`.runtime/upd06/logs/update-scheduler.log`、`update-scheduler-restart.log`（隔离环境，未入库）；摘录见第 1 节。
- 任务：`root_tasks.created_by IS NULL`，`audit_logs.actor='scheduler'`；任务在任务中心可按 `scheduled_update` 筛选，详情显示平台/场景/来源“定时调度”。
- 计划行：创建时原子写 `in_flight_root_task_id`、`last_attempt_at`；终态由 `Repository.edit` 的 reconcile 释放并推进 `next_due`。
- 未使用“直接调用单达人采集接口”代替调度。

## 6. 回归（F）与兼容性

- 普通采集小样本全部 COMPLETED：星图短视频 `f08ebeef…` 1/1；聚星短视频 `67ac447f…`、`e789785c…` 1/1；星图直播 `33c25563…` 1/1；聚星直播 `e43ce95d…` 1/1。
- 手动更新：星图短视频 `8f18fa2b…` COMPLETED（开关关闭状态下）。
- 既有 70 位能力未重跑，引用 [LIVE-02H](LIVE-02H-acceptance.md) 与 [LIVE-03-70](LIVE-03-70-acceptance.md)；本轮未修改采集搜索、筛选、70 上限、执行单元/Temporal 状态机。
- 接口/数据兼容：`creator_update_schedule` 旧行保留为 `video_square`；新增列/表/索引；`creator_update_service` 四行默认值；`platform_creators.video_homepage` 为导航数据，不参与业务字段投影。
- 共享代码最小改动：`Repository.edit` 终态 reconcile 范围改为所有更新场景（幂等空操作）；`persist_creators` 写 `video_homepage`；`Activities.collect` 只对 scheduled_update 增加开关闸门；`KuaishouJuxingAdapter` 增加无 plan 更新的 search page 建立。均有对应回归测试。
- 主站迁移：备份 `.runtime/backups/upd06-20261106/xingtu_development.dump`（68MB/498 TOC）；迁移 022 应用；回填 81/81；主站 scheduler 保持未运行；API/前端/两个 Worker 已恢复，队列各 1 个消费者。

## 7. 结论与条件

**CONDITIONAL GO**：
- 功能与隔离验收通过（四组真实、开关、双场景、重复/重启/取消、回归）。
- 条件 1：主站 scheduler 按用户现状保持关闭；若需持续自动更新，需运营确认后启动（`nohup .venv/bin/xingtu-product update-scheduler --unit-config .runtime/units/local-dev-mac-02.json --batch-size 5 >>.runtime/logs/update-scheduler.log 2>&1 &`），并按分组开关逐组放量。
- 条件 2：未主动制造真实平台故障；失败/退避由受控取消 + 集成失败用例覆盖。若需平台级故障注入，另立受控验收。
- 条件 3：Windows 实机登录/部署未在本轮验证（DEPLOY-WIN-01）。
- 条件 4：聚星短视频历史定位回填覆盖 81/81；新采集会自动写入，仍缺定位的达人不会纳入计划并在管理页显示。主站管理页当前显示聚星短视频 0 已纳入（开关关闭，未启用）。
- 残余：仓库级 `ruff check scripts` 仍有 3 个未改动的既有验收脚本的 UP031/格式问题；本次改动文件与 `backend/src` 检查通过。

## 8. 截图

- 隔离环境管理页（scheduler 在线、四组、开关/统计）：[ui-services.png](assets/UPD-06/ui-services.png)
- 浏览器开关聚星直播后：[ui-juxing-live-enabled.png](assets/UPD-06/ui-juxing-live-enabled.png)
- 恢复关闭：[ui-juxing-live-restored.png](assets/UPD-06/ui-juxing-live-restored.png)
- 真实定时批次详情（星图短视频 A1）：[ui-scheduled-task-detail.png](assets/UPD-06/ui-scheduled-task-detail.png)
- 主站交付态（scheduler 关闭、1/4 开启、148 到期、无虚构生效）：[main-ui-services-scheduler-off.png](assets/UPD-06/main-ui-services-scheduler-off.png)
