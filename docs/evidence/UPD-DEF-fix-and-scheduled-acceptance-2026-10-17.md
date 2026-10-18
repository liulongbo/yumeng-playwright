# UPD 缺陷修复与真实定时更新验收报告（2026-10-17）

- 范围：DEF-01、DEF-02 修复；受控真实定时更新；修复后核心链路回归
- 约束：只修改上述两项缺陷及必要测试；未做无关功能开发、未部署、未 commit/push
- 结论：**Go（受控 MVP 范围）**。两项缺陷已修复并复验；真实定时更新单达人批次完成；手动更新与正常采集回归通过。剩余风险见第 7 节。

## 1. DEF-01 修复：终态自动、幂等 reconcile

### 1.1 代码修改

- [`repository.py`](../../backend/src/xingtu/repository.py#L1440-L1452)：`Repository.edit()` 在任务事务提交后，对 `task_kind != collection` 且进入终态的 task 调用 `reconcile_update_task(self, root)`。这是 Activity、API command、CLI command 共用的终态写入边界，因此不依赖前端状态查询或下一次调度器 tick。
- [`creator_update.py`](../../backend/src/xingtu/creator_update.py#L590-L611)：新增模块级 `reconcile_update_task(repository, root)`，按 `creator_update_schedule.in_flight_root_task_id` 锁定并复用既有 `_reconcile_row`；已释放/无匹配行时返回 0，幂等。
- [`product_queries.py`](../../backend/src/xingtu/product_queries.py#L754-L800)：`ProductQueries.command()` 自己直接写 root task（不走 `Repository.edit`），因此在更新任务被 API 取消/终态化后同样调用 `reconcile_update_task`。失败只记录 warning，不把已提交的取消/终态重新变成错误。

### 1.2 自动化回归

新增：

- [`test_creator_update.py`](../../backend/tests/integration/test_creator_update.py#L186-L250)：
  - `test_terminal_edit_reconciles_schedule_without_status_read`：不调用状态查询/scheduler，仅通过 `Repository.edit()` 进入 `COMPLETED`，验证 in-flight 释放、`last_success_at`/`last_success_snapshot_id` 更新。
  - `test_cancel_command_reconciles_schedule_without_status_read`：通过 `ProductQueries.command("cancel")` 取消更新任务，验证不读状态也能释放在途标记。
- 两次调用 `reconcile_update_task` 的幂等断言：第二次返回 0。

结果：以上测试随全量集成通过（`94 passed, 1 skipped`）。

## 2. DEF-02 修复：更新任务能力版本文案

- [`pages.tsx`](../../frontend/src/pages.tsx#L363)：`item.capability_version || (taskKind === "collection" ? "历史任务" : "更新任务不适用")`。
- [`App.test.tsx`](../../frontend/src/App.test.tsx#L382)：更新任务详情断言显示“更新任务不适用”，且不显示“历史任务”。
- Chrome 复核：手动任务 `9a7d5d43…` 详情显示“更新任务不适用”，不再显示“历史任务”；截图 `docs/evidence/assets/upd/32-manual-detail.png`。

## 3. 受控真实定时更新验收

### 3.1 安全限定方式

现有调度器没有 `--creator-id` 参数，因此没有直接启动全量调度。采用**数据层受控范围**（未改业务代码）：

1. 备份 `creator_update_schedule` 原始行（测试前只有目标达人 1 行）。
2. 为其余全部已入库达人预置 `next_due_at = now() + 365 days`，仅目标达人 `6f13771f-b62a-4b6f-b5a4-c3aa85c86edd`（就叫Roxy）设为 `next_due_at = now()`。
3. 启动前断言“到期行恰好 1 条且等于目标达人”，并确认无运行中的正常采集任务。
4. `update-scheduler --batch-size 1 --tick-seconds 1`；**创建批次后立即停止调度器**，后续执行与终态收尾不依赖下一次调度器 tick。
5. 测试结束后删除为其他达人注入的未来调度行，保留目标达人的真实调度结果；原始其他行按备份恢复。

### 3.2 真实任务结果

| 项 | 值 |
|---|---|
| Task ID | `6871b08c-d446-4825-8d9e-f9da6dfb5408` |
| task_kind | `scheduled_update` |
| 状态流转 | `QUEUED → COLLECTING → COMPLETED` |
| 执行单元 | `unit-local-mac-02`（唯一单元，allowed_task_kinds=三类） |
| 创建/完成 | 2026-10-17T16:41:59Z / 2026-10-17T16:43:08Z |
| 目标达人 | `6f13771f-b62a-4b6f-b5a4-c3aa85c86edd`（6639192346380468227） |
| 新快照 | `0ac06761-ed37-4113-adb3-5b00fe9288e6` |
| 快照数 | 4 → 5（目标达人） |
| 当前投影 | `data_updated_at=16:43:08Z`、`profile_complete=true`、`pipeline_complete=true` |
| 任务数据 | `task_creators=1`、`filter_plans=0`、`requirements=0`、`model_runs=0` |
| 达人身份 | `platform_creators=1`（按平台 ID 无重复） |
| 调度收尾 | `in_flight_root_task_id=null`、`last_success_at=16:43:08Z`、`next_due_at=2026-10-20T16:43:08Z`、失败计数 0 |
| 调度器状态 | 创建批次后已停止；终态收尾仍完成 → **DEF-01 真实场景验证通过** |

证据：[UPD-scheduled-real-2026-10-17.json](UPD-scheduled-real-2026-10-17.json)、日志 `assets/upd/scheduled-real.log`。

### 3.3 说明：修复前的第一次定时尝试

第一次受控调度任务 `8640e74e-f096-4a35-bbfd-51bb7c16ae58` 执行时，Collection Worker 还是修复前的旧进程，因此任务虽 `COMPLETED`，调度行仍停留在 in-flight。该行随后用修复后的 `reconcile_update_task` 手工收敛；该任务保留为测试历史，但**不作为 DEF-01 修复验证**。修复后重启 Worker/API，再跑一次得到上述 `6871b08c…` 任务。

## 4. 修复后核心链路回归

| 场景 | Task ID | 结果 |
|---|---|---|
| 单达人手动更新（修复后） | `797a9207-3ddc-4e66-8cda-fc126eab5e43` | `QUEUED→COLLECTING→COMPLETED`；快照 5→6；`in_flight=null`，`last_success=16:44:53Z`，`next_due=10-20`；未依赖状态查询 |
| 定时更新（修复后） | `6871b08c-d446-4825-8d9e-f9da6dfb5408` | `QUEUED→COLLECTING→COMPLETED`；单元匹配、快照、入库、下一次周期均正确 |
| 正常采集主链路（修复后） | `193b7b97-9601-4bdc-9cc3-fec9ea58b2fc` | 关键词“露营”、目标 1；`RECEIVED→QUEUED→COLLECTING→COMPLETED`；有效 1、快照 1 |
| 任务中心 | 三类任务 | 采集/手动/定时均可见；`task_kind` 过滤可用；更新详情展示目标与状态 |
| 单执行单元共享 | 唯一 `unit-local-mac-02` | 三类任务均由该单元认领执行；WEB 互斥/租约未发现冲突 |
| 历史快照 | 目标达人 | 旧快照保留；新快照追加；达人主记录不重复 |

### 自动化回归

- 后端单元：**303 passed**
- 后端契约：**33 passed**
- 后端集成：**94 passed, 1 skipped**（含 2 个新增 DEF-01 回归）
- 前端：TypeScript 通过、**83 passed**、Vite build 通过（含 DEF-02 断言）
- `ruff check` / `ruff format --check`（变更文件）通过；`mypy backend/src`：34 files，无错误
- `make m3-check`：`PREFLIGHT_OK`，迁移 18、单元 READY、模型可用

## 5. Playwright MCP + Chrome 证据

- MCP：项目配置的 `@playwright/mcp` `1.62.0-alpha-2026-06-29`，23 个工具；真实 Chrome `155.0.8059.84`。
- 定时任务列表/详情：`docs/evidence/assets/upd/30-scheduled-list.png`、`31-scheduled-detail.png`。
- DEF-02 修复后的手动任务详情：`32-manual-detail.png`（“更新任务不适用”）。
- 修复后手动更新：`33-manual-after-fix.png`。
- 正常采集：`10-collection-form.png`、`12-collection-*.png`、`13-collection-terminal.png`、`14-task-list-collection.png`。
- 全量前端页控制台：任务/达人页 **Errors: 0**。

## 6. 数据库更新前后对比

| 项 | 验收前（上一轮结束） | 本轮结束 |
|---|---|---|
| 达人主记录 | 60 | 60（正常采集命中已有达人，未新增） |
| 不可变快照 | 126 | 130 |
| 根任务 | 52 | 56 |
| 目标达人快照 | 3 | 6 |
| 目标达人调度 | `last_success=16:27:02Z`、`next_due=10-20`、in-flight=null | `last_success=16:44:53Z`、`next_due=10-20`、in-flight=null、失败 0 |
| 定时任务 | 0 | 2（`8640…` 修复前历史；`6871…` 修复后验证） |

目标达人新增快照（按时间）：原 1 份 + 手动首次部分 1 份 + 手动重试完整 1 份 + 修复前定时 1 份 + 修复后定时 1 份 + 修复后手动 1 份 = 6 份。所有旧快照仍保留。

## 7. 尚未解决/未覆盖

1. **强制并发/故障注入未执行**：未做两个真实 Worker 强制抢同一任务、Worker 真崩溃、DB/Temporal 停机、会话失效/安全验证的真实故障注入；已有单元/集成租约与状态机测试，但不能替代真实故障演练。
2. **调度器需常驻**：测试结束后 update-scheduler 已停止；生产/长期运行必须由部署进程常驻，否则周期更新不会自动发生。
3. **平台瞬时异常**：首次手动更新的 fans `JSONDecodeError` 仍可能出现；本轮重试成功，未改解析器/不放宽断言。
4. **修复前定时任务**：`8640…` 是修复前旧 Worker 产生的历史任务，其调度行已手工收敛；保留为测试数据，不代表修复后行为。
5. **规模/积压/饥饿**：只验证单达人受控批次，未验证大量达人到期、长队列、饥饿与多批次连续调度。
6. **测试数据**：真实任务/快照按要求保留作为证据；合成定时/取消任务已清理；测试期间未修改真实达人身份字段、账号凭据、执行单元或 Schema。

## 8. 最终建议

**Go（受控 MVP 范围）**：

- DEF-01、DEF-02 已修复并有自动化回归；
- 单达人手动更新、单达人真实定时更新、正常采集主链路均真实通过；
- 统一任务中心、单执行单元共享、数据/快照/下次周期验证通过；
- 无阻塞性代码缺陷。

**生产上线前仍需**：让 update-scheduler 常驻并监控；在扩容/高积压场景前补做真实故障注入与多批次压力验证；不将本轮单达人受控结论扩展为全量规模结论。

## 9. 证据索引

- 定时验收：[UPD-scheduled-real-2026-10-17.json](UPD-scheduled-real-2026-10-17.json)、`assets/upd/scheduled-real.log`
- 手动验收：[UPD-manual-e2e-2026-10-17.json](UPD-manual-e2e-2026-10-17.json)
- 正常采集：[UPD-collection-regression-2026-10-17.json](UPD-collection-regression-2026-10-17.json)
- 修复前采集基线：[UPD-collection-regression-before-fix-2026-10-17.json](UPD-collection-regression-before-fix-2026-10-17.json)
- 执行单元矩阵：[UPD-pool-matrix-2026-10-17.txt](UPD-pool-matrix-2026-10-17.txt)
- 周期边界：[UPD-period-boundaries-2026-10-17.txt](UPD-period-boundaries-2026-10-17.txt)
- 截图：[assets/upd/](assets/upd/)
- 上一轮完整测试报告：[UPD-acceptance-report-2026-10-17.md](UPD-acceptance-report-2026-10-17.md)
