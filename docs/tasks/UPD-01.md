# UPD-01：达人更新任务模型、迁移与执行单元能力配置

状态：已完成  
更新时间：2026-10-17T16:34:38+08:00  
是否验收：是；离线与隔离库验收通过；真实平台采集不属于本卡范围。

## 目标与范围

**目的**：为正常采集、手动更新、定时更新提供统一的任务类型与执行单元能力配置，保持旧任务兼容。

**包含**：迁移 018（`root_tasks.task_kind`、`execution_units.allowed_task_kinds`、`creator_update_schedule`）；`TaskKind` 与 `TaskRecord` 扩展；`ExecutionUnitView` 只读能力；`set-unit-task-kinds` CLI（审计与未启动任务回池）。

**不包含**：更新执行逻辑、调度器、产品 API/前端、真实采集。

## 关联与依赖

F01/F02/F03/F04/F05；技术方案 §14；DEC-017。前置：无。

## 验收清单

- [x] 迁移 018 在隔离测试库可应用；旧 `root_tasks` 记录默认加载为 `collection`。
- [x] `TaskRecord` 对 collection/update 组合做构造即拒绝；旧 payload 不受影响。
- [x] 单执行单元默认允许三类任务；CLI 变更写审计，未启动且类型被移除的任务回到池中。
- [x] `ExecutionUnitView.allowed_task_kinds` 可读；既有测试通过。

## 实现记录

- 迁移 [018_creator_update.sql](../../migrations/018_creator_update.sql)：`root_tasks.task_kind`、`execution_units.allowed_task_kinds`、`creator_update_schedule` 与索引。
- [domain.py](../../backend/src/xingtu/domain.py)：`TaskKind`、`TaskRecord.plan` 可空、`update_targets`、构造即校验、`target_count/capability_version`。
- [repository.py](../../backend/src/xingtu/repository.py)：能力查询、`set_unit_task_kinds`、池认领、优先级判定；[product_queries.py](../../backend/src/xingtu/product_queries.py) 暴露单元能力；[cli.py](../../backend/src/xingtu/cli.py) 新增 `set-unit-task-kinds`。
- 开发库已应用迁移 018；迁移仅新增，不重写既有数据。

## 验证证据

详见 [UPD 离线验证证据](../evidence/UPD-01-05-offline-verification-2026-10-17.md)：

- 开发库：`xingtu migrate --environment development` → 已应用；`schema_migrations=18`、单元默认三类任务。
- 隔离库集成：`92 passed, 1 skipped`（含迁移、配置回池、池认领）。
- 单元：`303 passed`；契约 `33 passed`；`ruff`/`mypy` 通过。
- CLI 实测：`set-unit-task-kinds --kinds collection` 输出 `requeued=1`，恢复三类任务输出 `requeued=0`。

## 交接信息

UPD-02 依赖本卡的任务类型、执行单元能力列与 `TaskRecord.target_count`。

## 状态历史

- 2026-10-17T15:45:18+08:00：建立 → 进行中；按已批准方案开始实施。
- 2026-10-17T16:34:38+08:00：进行中 → 已完成；迁移、领域模型、能力配置与隔离库/静态检查通过。
