# DIAG-02：ExecutionUnit「old browser requires isolation」专项诊断与最小修复

状态：待验收（修复已实施；macOS 真实 Chrome E2E 通过；Windows/F10 未测）
是否验收：否（Windows 实机、F10 真实接管、封面/完整性残余、completed_at 既有问题）
更新时间：2026-10-24T20:44:00+08:00
关联功能：F10、QA-01、UNIT-01、AUTO-01、SESSION-01
关联任务：`383474a1-40b6-4343-ac22-9a4efcdc6af7`、`2ff8ad00-1436-4be6-850f-c2129881849b`、`60a67287-4bc0-46cf-a50a-f62bc38c658f`

## 目标与范围

诊断并修复 `RESOURCE_UNAVAILABLE: old browser requires isolation`：定位触发条件/根因/影响面，经用户批准后实施最小修复，并用 Playwright MCP + 真实 Chrome 做回归。

包含：

- 只读检查任务、P1/P2、Temporal、Collection Worker、ExecutionUnit、Chrome 进程/Profile、PostgreSQL。
- 回滚事务复现；隔离证明（项目 Profile 锁、SingletonLock PID、lsof、个人 Chrome 区分）。
- **最小修复**：Collection Worker 启动时对“已隔离 + 无活跃租约/验证/接管 + 本地停止证明通过”的单元执行一次审计回收。
- 真实重启回收、真实 Chrome 采集回归、负向分支测试。
- 诊断报告、修复报告、任务卡与进度索引同步。

明确不做：

- 不新增 Schema/迁移；不删除 Profile/Cookie/锁；不杀未知 Chrome。
- 不创建新采集任务；使用既有 `383474a1`。
- 不做 graceful shutdown 改造（8.3 建议另立卡片）、不做 API/UI 恢复按钮、不做 `profile_ref`/launchd 清理。
- 提交/推送/合并按 2026-10-24 用户单独授权执行（见状态历史）。

## 关联与依赖

- 诊断报告：[DIAG-02-browser-isolation-2026-10-24](../evidence/DIAG-02-browser-isolation-2026-10-24.md)。
- 修复与回归：[DIAG-02-fix-2026-10-24](../evidence/DIAG-02-fix-2026-10-24.md)。
- 证据 JSON：[fix-evidence.json](../evidence/assets/diag02/fix-evidence.json)。
- 前置/相关：[F10](F10.md)、[QA-01](QA-01.md)、[UNIT-01](UNIT-01.md)、[AUTO-01](AUTO-01.md)、[SESSION-01](SESSION-01.md)。
- 代码版本：分支 `快手_1024`，基线 HEAD `024f879`；本轮提交 `3a7be00`，与 RETRY-01 的 `61f76d2` 一起合并为 `fa28876`。
- 运行态：Worker generation 5（PID 34571）；单元 `unit-local-mac-02` 最终 `READY`；任务 `383474a1` 最终 `PARTIAL_COMPLETED`。

## 验收清单

- [x] DIAG-02A 只读核对任务 `383474a1` 的 P1、P2、Temporal、task_checkpoints、task_creators、creator_snapshots。
- [x] DIAG-02B 只读核对 ExecutionUnit 行、Worker 实例、owner/lease/generation、browser_instance、mode、current_root_task_id。
- [x] DIAG-02C 定位 `old browser requires isolation` 的代码触发条件与调用链。
- [x] DIAG-02D 回滚事务复现：过期 owner + `browser_stopped=false` 与 QUARANTINED 行均触发同一异常；回滚后库内不变。
- [x] DIAG-02E 隔离证明：Profile 锁空闲、SingletonLock PID 23355 不存在、profile 无进程打开；个人 Chrome 未使用单元 Profile。
- [x] DIAG-02F Playwright + 系统 Chrome 查看任务页/执行单元页；截图与 API 响应已存档。
- [x] DIAG-02G 核对 F10 提交 diff，判断是否由 macOS/Windows 适配引入（结论：非直接引入）。
- [x] DIAG-02H 输出影响范围、最小修复方案、回归测试与 E2E 测试计划。
- [x] DIAG-02I 修复实施：`has_active_unit_claim` + `reconcile_quarantined_unit` + `run_worker` 启动调用；6 个新单测。
- [x] DIAG-02J 真实重启回收：新 Worker generation 5 在 12:17:39 日志回收，`audit_logs` 437；未手动执行 `recover-unit`。
- [x] DIAG-02K Playwright MCP + 真实 Chrome E2E：`383474a1` 从 `QUEUED` 到 `PARTIAL_COMPLETED`；`valid=2/2`、2 快照；无 isolation 错误。
- [x] DIAG-02L 负向验证：活跃租约阻断、Profile 锁占用失败关闭、重复 Worker 拒绝、OPEN 验证事件阻断（回滚）。
- [x] DIAG-02M 自动检查：unit **321 passed**、contract **39 passed**、mypy **35 files**、ruff/format 通过。
- [ ] DIAG-02N Windows 实机验收（NOT TESTED）。
- [ ] DIAG-02O F10 真实挑战/人工接管验收（本轮未触发，NOT TESTED）。

## 实现记录

- 2026-10-24T12:13—12:17：实现 `Repository.has_active_unit_claim()` 与 `worker.reconcile_quarantined_unit()`；`run_worker()` 注册 Worker 后调用；证明失败/活跃 claim/回收拒绝均保持隔离。新增 `backend/tests/unit/test_worker_startup_recovery.py` 6 例；补齐 dispatch fake；新增集成用例（未运行）。
- 2026-10-24T12:16：停止旧 Worker generation 4（PID 28208，无浏览器租约）；等待心跳超过 45 秒。
- 2026-10-24T12:17:39：启动 Worker generation 5（PID 34571）；启动回收日志 `recovered quarantined unit unit-local-mac-02 after local isolation proof (reason=EXPIRED_OWNER, worker=b612f21a-…)`；`audit_logs` 437；单元 `QUARANTINED → SESSION_UNVERIFIED`。
- 2026-10-24T12:17:58：`383474a1` 首次尝试因 `Page.goto: net::ERR_NETWORK_CHANGED` 失败为 `PLATFORM_PAGE_CHANGED:BROWSER_ACTION_FAILED`；单元正常释放（`SESSION_UNVERIFIED/owner=NULL/browser_stopped=true`），**不是隔离回归**。
- 2026-10-24T12:23:25：通过 Playwright MCP + 系统 Chrome 156 点击「重试失败步骤」；`audit_logs` 439；状态 `QUEUED 12:23:32 → SEARCHING 12:23:51 → COLLECTING 12:23:57 → PARTIAL_COMPLETED 12:28:05`。
- 最终数据：`task_creators=2`、`creator_snapshots=2`、`featured_collections=4`、`featured_cards=6`、`media_objects=0`（封面 6/6 FAILED）；`valid=2/2`；单元 `READY`、`browser_stopped=true`、`owner=NULL`、无 open verification/takeover。
- MCP 说明：`@playwright/mcp 0.0.77`（Playwright `1.62.0-alpha-2026-06-29`）通过 `--cdp-endpoint` 驱动系统 Chrome 156.0.8078.47；MCP 自身 launch 在受限沙箱下 Chrome `SIGTRAP`，因此使用 CDP 连接的**真实系统 Chrome**；MCP 实际执行 navigate/type/click/evaluate/screenshot。

## 验证证据

- 报告：[诊断](../evidence/DIAG-02-browser-isolation-2026-10-24.md)、[修复与回归](../evidence/DIAG-02-fix-2026-10-24.md)。
- 截图：[修复前失败](../evidence/assets/diag02/fix-task-before-retry.png)、[采集中](../evidence/assets/diag02/fix-task-collecting.png)、[最终任务](../evidence/assets/diag02/fix-task-final.png)、[单元 READY](../evidence/assets/diag02/fix-units-ready.png)、[达人详情](../evidence/assets/diag02/fix-creator-detail.png)、[诊断时任务页](../evidence/assets/diag02/task-383474a1.png)、[诊断时单元页](../evidence/assets/diag02/execution-units.png)。
- 结构化证据：[fix-evidence.json](../evidence/assets/diag02/fix-evidence.json)、[timeline.json](../evidence/assets/diag02/timeline.json)。
- 测试命令与结果：
  - `pytest -q backend/tests/unit` → **321 passed**。
  - `PLAYWRIGHT_BROWSERS_PATH=.runtime/browsers pytest -q backend/tests/contract` → **39 passed**。
  - `mypy backend/src` → **35 source files, no issues**。
  - `ruff check`（改动文件）→ pass。
  - 活跃租约回滚：`reconcile_quarantined_unit()=False`，单元保持隔离，回滚后库内不变。
  - 持有项目 flock：`confirm_local_browser_stopped()` → `RESOURCE_UNAVAILABLE: PROFILE_STILL_IN_USE`。
  - 第二个 Worker → `RESOURCE_UNAVAILABLE: DUPLICATE_WORKER_FOR_UNIT`，未新增 worker 行。
  - 回滚插入 OPEN 验证事件：`has_active_unit_claim()=True`，回滚后 False。
- 未执行：`XINGTU_TEST_DATABASE_URL` 集成测试（未配置）；Windows 实机；F10 真实挑战/接管。

## 交接信息

- **当前状态**：`383474a1` 终态 `PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE`，`valid=2/2`，2 份快照；`unit-local-mac-02` `READY`，`owner=NULL`，`browser_stopped=true`，无 open verification/takeover；Worker generation 5 ONLINE。
- **隔离问题**：已修复并经真实重启/真实 Chrome 验证；`old browser requires isolation` 不再出现。
- **残余（不阻塞本修复结论，但不能标“全部验收”）**：
  1. `completed_at` 仍为首次失败时间 12:17:58，而状态在 12:28:05 变 `PARTIAL_COMPLETED`；页面「完成时间/最近更新」不一致（既有 `TERMINAL_COMPLETED_AT_CLAUSE` 行为）。
  2. 封面 6/6 `FAILED`、`media_objects=0`；`profile_complete_count=0`、`featured_complete_count=0`；属采集完整度/封面存储环境，不是隔离错误。
  3. Windows 实机、F10 真实挑战/接管 **NOT TESTED**。
  4. `execution_units.profile_ref` 旧 checkout、launchd 遗留 agent 未处理。
- **下一步**：用户审阅；如需继续，建议另立卡片：(a) graceful stop / supervisor 信号；(b) 封面入库与完整性；(c) `completed_at` 重试语义；(d) profile_ref/launchd 清理；(e) Windows/F10 实机验收。
- **提交状态**：`3a7be00`（含本卡与证据），经 merge `fa28876` 合入 `main` 并推送；合入前重跑单元/契约/集成/E2E/前端/静态检查通过（集成用临时 PostgreSQL `xingtu_test_retry01`，验证后已删除，未触碰开发库）。

## 状态历史

- 2026-10-24T12:10:00+08:00：新建 → 进行中。诊断与复现完成；未修改代码/DB/任务/Profile；等待用户审批修复方案。
- 2026-10-24T12:13:00+08:00：进行中；用户批准执行，开始实施 Worker 启动隔离回收。
- 2026-10-24T12:17:39+08:00：修复代码启动；新 Worker generation 5 自动回收隔离单元（audit 437）。
- 2026-10-24T12:28:05+08:00：真实 Chrome E2E 到 `PARTIAL_COMPLETED`，valid 2/2；单元 READY。
- 2026-10-24T12:35:00+08:00：进行中 → 待验收。修复/真实回归完成；Windows/F10 与残余项未完成，故不标已完成。
- 2026-10-24T20:44:00+08:00：状态保持待验收。用户授权提交/合并：本卡代码与文档提交 `3a7be00`，经 merge `fa28876` 合入 `main` 并推送（合入前单元/契约/集成/E2E/前端/静态检查通过）；Windows 实机、F10 真实接管与残余项仍未完成。
