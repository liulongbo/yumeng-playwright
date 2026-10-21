# CFG-01：中心 Worker 与 UnitConfig 解耦

状态：已完成
更新时间：2026-10-19
是否验收：是；自动化与镜像 CLI 验证通过。

## 目标与范围

中心 Intake Worker 和更新调度器只接收 Registry、ProfileRequirement 与默认单元 ID 等职责内配置，不依赖 Mac 的 Profile、Chrome 或线路路径；保留旧命令兼容。

## 验收清单

- [x] 云端中心进程不需读取完整 UnitConfig。
- [x] 首期默认单元明确为 `unit-mac-cell-01`，缺失配置快速失败并给出可解释原因。
- [x] 原本地 UnitConfig 启动方式仍可使用。

## 验证证据

- 2026-10-18：基线确认 `product_cli.py` 的两个中心进程均通过 `load_unit()` 读取 Registry/单元 ID。
- 2026-10-19：Intake 改用 `execution_unit_id + registry`，Scheduler 改用 Registry；旧 `--unit-config` 保留。缺少默认单元报 `DEFAULT_EXECUTION_UNIT_ID_REQUIRED`；新增 2 项直接回归通过，镜像 CLI 帮助核对通过。

## 状态历史

- 2026-10-18：待办 → 进行中。
- 2026-10-19：进行中 → 已完成；未修改采集 Engine、Adapter 或 Workflow。
