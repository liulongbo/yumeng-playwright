# BASE-01：必要工程基础

状态：待验收  
更新时间：2026-09-27T17:35:00+08:00

## 目标与范围

提供 F04/F05 所需的最小可运行工程基础：锁定依赖与工具链、统一命令入口、业务库迁移、幂等与检查点存储、租约与状态机、Temporal 编排、脱敏证据存储、注册表发布门槛、开发与运维说明。  
不包含：前端、产品 API（F01/F02/F07/F08）、P1 模型转换（F03）、F06、F09—F11 的真实硬件与远程维护、采购与生产发布。

## 关联与依赖

前置：无。功能：F04/F05 必要支撑。验收：T12—T16、T19、T21。待验证：U08/U09。

## 验收清单

- [x] 范围内代码与版本化契约实现（迁移、仓储、租约、状态机、Engine、Temporal Workflow/Activity、注册表、证据、CLI）。
- [x] 适用离线单元、契约、存储及恢复验证通过，证据可查。
- [x] 独立本地依赖服务验证：PostgreSQL 18.3（业务库与迁移）、Temporal Python SDK 本地测试服务器 1.33.0（工作流暂停/唤醒/重放）、Chromium 1243（浏览器契约）。
- 命令契约入口可用（已实测）：`make help`、`make check`（= lint + format-check + typecheck + test-unit）、`make test-contract`、`make test-integration`、`make test-e2e`、`make migrate ENVIRONMENT=test`；`xingtu doctor|migrate|register-unit|enable-contract|start|status|results`。
- [ ] 未实测命令：`make setup`、`make dev`、`make stop`、`make smoke-live`（Docker 守护进程未运行 / 需真实账号，见交接信息）。
- [x] 新增入口实测（2026-09-27）：`make smoke-local`（本地验证载体，负向门槛路径已跑通终态）、`xingtu browser-check`、`xingtu production-preflight`、`xingtu research`（真实启动，人工登录未完成）。
- [x] 文档、命令与交接信息更新：[开发与运维说明](../development.md)、[决策记录](../decisions/)、[验证证据](../evidence/F04-F05-offline-verification.md)。

## 实现记录

- 工程与命令：`pyproject.toml`、`uv.lock`、`Makefile`、`scripts/commands.py`、`deploy/compose.yaml`；命令说明见[开发与运维说明](../development.md)。
- 存储与状态：`migrations/001_initial.sql`（任务、尝试、检查点、幂等、快照不可变触发器、租约、审计、证据、契约健康）、`backend/src/xingtu/repository.py`（幂等启动、围栏写入、快照发布、命令状态机）。
- 编排：`backend/src/xingtu/workflow.py`（Signal 唤醒、历史只传 ID/状态、continue-as-new 兼容）、`backend/src/xingtu/worker.py`（Activity 心跳、租约释放、派发器）。
- 证据：`backend/src/xingtu/evidence.py`（`EvidenceSink`、`S3EvidenceStore`、`FileEvidenceStore`、`EvidenceConfig`）、`build_evidence_sink`（`evidence.py:124`）；预算与证据配置进入 `UnitConfig`（`runtime.py:33`、`34`），由 Worker 注入（`worker.py:72`、`114`）。
- 预算：`SegmentBudget`（`domain.py:349`）与 `ExecutionContext.budget`（`domain.py:370`）落实附录 A 默认值，Engine 不再硬编码。
- 决策记录：[DEC-001 工具链](../decisions/DEC-001-toolchain.md)、[DEC-004 证据写入与保留](../decisions/DEC-004-evidence-sink.md)。
- 2026-09-27 本轮改动：迁移机制由"只应用 001"改为按 `schema_migrations` 顺序应用全部待应用迁移（`repository.migrate`），并新增 `migrations/002_unit_network_mode.sql`；`evidence.py` 的 `EvidenceSummary` 增加 `network_mode`；`Makefile`/`scripts/commands.py` 增加 `make smoke-local` 与 `scripts/local_smoke.py`（本地验证载体，不替代生产编排）。
- 2026-09-27 真实采集阶段改动：新增 `migrations/004_local_line_sharing.sql`（同一开发机多个本地单元共享本地出口，生产线路唯一性由部分唯一索引保持）；`contracts.py` 搜索契约新增 `homepage_template`/`fixed_sort`/`single_page_only`/`binding_values`/检索级 `coverage_gaps` 与 `LocatorSpec.property`、注册表级 `session_boot_timeout_seconds`；`worker.py` 把 `network_mode` 带入 `ExecutionContext`；`adapter.py` 增加会话引导、账号有界等待与 property 读取。

## 验证证据

- 日期与环境：2026-09-26，macOS 26.5.2 / Python 3.13.5 / PostgreSQL 18.3 / Chromium 1243 / Temporal 测试服务器 1.33.0 / Docker Compose v2.40.3（守护进程未运行）。详见[离线验证证据](../evidence/F04-F05-offline-verification.md)与[命令记录](../evidence/F04-F05-offline-verification.log)。
- 命令与结果：`ruff check` 通过；`ruff format --check` 23 files already formatted；`mypy backend/src` 无问题；`pytest backend/tests/unit` 41 passed；`backend/tests/contract` 10 passed；`backend/tests/integration` 22 passed；`tests/e2e` 1 passed（含工作流历史重放）。
- 2026-09-27（本轮回归，本地环境）：`ruff check`/`ruff format --check`（26 files）/`mypy backend/src` 通过；`pytest backend/tests/unit` **52 passed**、`backend/tests/contract` **10 passed**、`backend/tests/integration` **23 passed**、`tests/e2e` **2 passed**；`xingtu migrate --environment development` 在库 `xingtu_local_dev` 应用迁移，`schema_migrations={1,2}`；`make smoke-local` 在真实 `Activities.collect` + `CollectionWorkflow` + Temporal 本地测试服务器上跑通（未核验契约 → 终态 `FAILED`/`UNVERIFIED_REGISTRY`）。详见[本地阶段证据](../evidence/UNIT-01-local-stage-2026-09-27.md)。
- 迁移与命令实测（2026-09-26）：`xingtu migrate --environment test` 应用迁移 1；`xingtu register-unit` 登记单元；`xingtu start` 与 `xingtu enable-contract` 对未核验注册表返回 `UNVERIFIED_REGISTRY`（退出码 2）；`xingtu status`/`results` 输出检查点、诊断与已发布快照。
- 未执行：`make setup`、`make dev` / `make stop`（Docker 守护进程未运行）、`make smoke-live`（需真实账号）；影响：Compose 编排与安装/冒烟入口未验证，故本卡保持"待验收"。
- 未执行：MinIO/S3 证据上传实测（U09）；仅验证本地文件实现。
- 2026-09-27（真实采集阶段）：新增迁移 `004` 已在本地开发库应用（`schema_migrations={1,2,3,4}`）；迁移机制被真实采集链路使用（`xingtu migrate` → `register-unit` → `start` → `make smoke-local`）。四层离线测试在最后一次代码改动后复测全绿：单测 94 / 契约 13 / 集成 26 / E2E 3。详见[真实采集证据](../evidence/UNIT-01-real-collection-2026-09-27.md)。

## 交接信息

- 阻塞：无（工程基础不依赖硬件）。
- 遗留：`make setup`、`make dev`/`make stop`、`make smoke-live` 未实测；S3/MinIO 路径未实测；Redis 缓存与限流本轮未启用（业务不依赖缓存，符合方案要求）。`make smoke-local` 的正向（真实采集）路径依赖已核验注册表与人工登录，尚未执行。
- 下一步：启动 Docker 守护进程后执行 `make dev` 并确认各服务健康，再执行 `make stop`；具备对象存储环境后补 S3 证据路径验证；真实账号可登录后跑 `make smoke-live`/`make smoke-local`。

## 状态历史

- 2026-09-26T20:17:35+08:00：待办 → 进行中；用户批准开发方案。
- 2026-09-26T21:50:00+08:00：进行中 → 待验收；离线实现与本地依赖服务验证完成，Compose 编排与 S3 路径未验证。
- 2026-09-27T09:51:41+08:00：待验收 → 待验收；静态盘点确认既有基础可复用；安装/Compose/S3等历史未验收项保留，本轮未重跑应用检查。见[项目基线](../evidence/PROJECT-BASELINE-2026-09-27.md)。
- 2026-09-27T11:20:00+08:00：待验收 → 待验收；本轮实际改动迁移机制（增量应用）与证据网络模式字段，新增 `make smoke-local` 并实测负向路径；四层离线测试重跑全绿（52/10/23/2）。Compose/S3/安装等历史未验收项保留。
- 2026-09-27T17:35:00+08:00：待验收 → 待验收；新增迁移 `004`（本地出口共享）并由真实采集链路实际使用；搜索契约与适配器新增字段/修复随 UNIT-01 真实登记一并落地；四层离线测试复测全绿（94/13/26/3）。Compose/S3/安装等历史未验收项保留。
