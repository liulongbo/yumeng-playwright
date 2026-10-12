# CONSOLE-01：任务中心与任务内达人结果

状态：已完成
更新时间：2026-10-12T01:00:00+08:00
是否验收：是；F07/F08 已在真实产品任务上完成轮询到终态、两媒介共享读取、退出/重登恢复、两份发布快照、双精选集合和受保护封面验收。

## 2026-10-12 FIX-01 P3-D：主动取消不再显示成「需要关注」

**根因（DEF-04）**：`taskMessage()` 未覆盖 `CANCELLING`/`CANCELLED`（落到兜底文案「任务状态已从服务端恢复，页面会按需自动更新。」），关注面板只看 `failure_reason` 是否非空，因此把用户主动取消的 `TASK_CANCELLED` 渲染成红色「任务需要关注」并暴露内部错误码。

**最小修复**：

- `frontend/src/pages.tsx`：`taskMessage()` 覆盖 `CANCELLING`（「取消已受理，正在等待执行中的步骤安全收尾。」）与 `CANCELLED`（「任务已按你的操作取消，已持久的结果保留。」）；新增 `isUserCancelled()` / `attentionPanelClass()` / `attentionTitle()` / `attentionDetail()`：`CANCELLED` 或 `failure_reason=TASK_CANCELLED` 使用中性面板、标题「任务已取消」、说明「任务已按你的操作取消，已持久的结果会保留。」，**不显示内部错误码**。
- `frontend/src/status.ts`：`CANCELLED` 徽标由 `danger` 改为 `neutral`（`FAILED` / `FAILED_VALIDATION` 仍为 `danger`），避免「已取消」被读成系统故障。
- 同一处还补了 `PROFILE_SCOPE_INCOMPLETE` 的可兑现说明（「重试失败步骤」只补采缺失模块、不会重复创建任务），替代裸内部错误码。

**验证（Playwright MCP + 真实 Chrome，任务 `0300f417-c0fe-428d-9878-5aec314acc48`）**：徽标 `status-badge neutral` 文案「已取消」；页头文案为中性取消说明；关注面板存在但 `className="attention-panel neutral"`、标题「任务已取消」；页面正文**不含** `TASK_CANCELLED` / `PROFILE_SCOPE_INCOMPLETE`，**不出现**「任务需要关注」。前端 `tsc` / vitest（3 passed）/ 生产构建全部通过。完整证据见 [FIX-01 真实采集闭环修复证据](../evidence/FIX-01-real-collection-close-2026-10-12.md)。

## 2026-10-11 Playwright MCP 原生工具端到端 UI 复跑

以**已注册到 profile 的原生 MCP 工具**（`mcp__playwright__*`）驱动真实 Chrome 复核任务中心与状态展示，报告见 [MCP UI 端到端测试报告](../testing/mcp-ui-e2e-2026-10-11.md)。

- PASS：任务中心可见性（20 行）、新任务与状态传播（`取消中 露营 #1489571e`、`已取消 美妆 #71c7252f`）、详情页状态与阶段文案（`QUEUED`「等待采集资源」）、无消费者阻塞面板（`INTAKE_WORKER_UNAVAILABLE`）、`RECEIVED` 阶段取消的终态展示、API 重启后会话无需重登、控制台无 JavaScript 异常。
- 新缺陷（P3，展示层，**已于 2026-10-12 修复**，见上节）：**DEF-04** —— 用户主动取消（`CANCELLED`）的详情页显示红色「任务需要关注 / TASK_CANCELLED」，且页头用兜底文案「任务状态已从服务端恢复，页面会按需自动更新。」（`taskMessage` 未覆盖 `CANCELLED`；`failure_reason` 非空即进关注面板，未区分主动取消与真实失败）。建议 `CANCELLED` 用中性文案且 `TASK_CANCELLED` 不进红色面板。
- 相关但不属本卡（P1，状态机）：**DEF-01** —— 已 `QUEUED` 的任务取消后停在 `CANCELLING`，终态化依赖 P2 Worker，详见报告与 [INTAKE-01](INTAKE-01.md)。

## 2026-10-11 完整新任务闭环修复复核

首次冒烟中，新建任务因只启动 API/前端、未启动 Intake Worker/Collection Worker 而停在 `RECEIVED`；另外，任务进入终态后达人列表查询没有刷新，曾造成任务计数与任务内达人列表短暂不一致。本次保留该历史记录，并完成最小修复：

- 启动完整本地受控执行环境，使用 localhost-only DeepSeek-compatible Fixture 验证 P1，不将 Fixture 当作真实 DeepSeek。
- `frontend/src/pages.tsx` 在任务进入终态时刷新 `['creators', taskId]`，确保发布结果可见。
- 通过 Playwright MCP 创建 root `acd929aa-874e-4de8-8fb1-6a9295cf07ff`，真实观察 `RECEIVED → PARSING → QUEUED → COLLECTING → COMPLETED`。
- 最终 API/UI 结果一致：发现 20、有效 1、资料完整 1、精选完整 1、失败 0；页面显示“1 位可查看 / 已发布快照”。

结论：本地受控模型条件下，CONSOLE-01 的任务详情终态刷新和任务内结果展示已复核通过；真实 DeepSeek 新任务现场调用、真实自然安全验证和生产环境验收仍不属于本次通过范围。

## 2026-10-10 冒烟后修复复核：真实任务已显示已完成

F05 契约缺源口径修复并对 root `f47eb1cf-f038-4f9f-ae3d-e02aa8a995d3` retry 后，产品 API 与 Playwright MCP UI 已复核：任务详情返回 `COMPLETED`、`valid_count=2`、`profile_complete_count=2`、`featured_complete_count=2`、`allowed_actions=[]`、`failure_reason=null`；前端展示“已完成 / 目标链路已完成，可查看发布快照”。第二位达人详情页无“失败/FAILED”文本，8 个 F05 模块全部 `COLLECTED/complete=true`，两组 F06 集合均 `COMPLETE`。

## 2026-10-10 F04/F05/F06/M3 核心冒烟复核

本轮通过 Playwright MCP 真实 UI 复核任务中心、任务详情、任务操作和任务内达人结果，报告见 [F04/F05/F06/M3 核心冒烟测试报告](../testing/smoke-test-f04-f05-f06-m3.md)。任务列表显示真实开发数据 15 条；新建 root `b12b5785-f90a-42c2-8c4f-67c54ab690e4` 的详情页显示 `RECEIVED`、计数为 0、合法操作为 `cancel`，通过页面确认框取消后，前端/API/DB 一致为 `CANCELLED`。

同轮打开既有真实任务 `f47eb1cf-f038-4f9f-ae3d-e02aa8a995d3`，前端/API 均显示 `PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE`、目标 2、发现 20、有效 2、F05 完整 0、F06 完整 2；任务内达人列表显示 2 位达人。进入第一位达人详情后，F05 模块状态与 F06 双集合均可见；API 与 DB 交叉验证为 2 位达人、7 份快照、4 个集合、14 张精选卡、14 个 `STORED` 封面引用。结论：CONSOLE-01 的本地真实 UI/API/DB 冒烟 PASS，真实任务部分完成被正确呈现。

## 目标与范围

**目的**：让媒介能看到需求、进度、结果和异常，并安全操作持久任务。

**任务内容**：任务列表/详情及 API、状态与阶段/计数/allowed_actions、取消/继续/失败重试/修改重提、任务内达人分页/详情、运行草稿与发布快照区分、两组卡片与封面展示、来源谱系和错误呈现。

**不包含**：不做跨任务达人搜索、评分、导出、导入；刷新执行由 F09 负责，远程登录由 F10 负责。

## 关联与依赖

F07/F08；技术方案第 8—9、14—16 章。T05—T07/T12—T16/T21/T24/T29/T30，U01/U04/U05。

前置：[APP-01](APP-01.md) 与 [BASE-01](BASE-01.md)；完整验收依赖 [INTAKE-01](INTAKE-01.md)、[F04](F04.md)、[F05](F05.md)、[F06](F06.md)。可先接现有任务及主页快照。

## 当前开发状态与实现记录

2026-10-10 已实现认证任务 API、稳定游标与筛选、详情阶段/计数/错误/`allowed_actions`、带版本和幂等的取消/继续/重试、P1 失败新重试周期、任务内达人草稿/发布投影、F05 字段、F06 两组独立分页及受保护封面。实现仅从既有持久化事实构建产品投影，不修改 F04/F05/F06 采集业务逻辑。

实现依据：[产品查询](../../backend/src/xingtu/product_queries.py)、[产品 API](../../backend/src/xingtu/product_api.py)、[封面读取](../../backend/src/xingtu/product_covers.py)、[产品集成测试](../../backend/tests/integration/test_product_m3.py)、[React 任务/结果页](../../frontend/src/pages.tsx)、[产品浏览器 E2E](../../tests/e2e/test_product_frontend.py)。Lazyweb 参考与视觉验证详见 [前端证据](../evidence/M3-product-frontend-2026-10-10.md)。

## 验收清单

- [x] API 列表按创建时间倒序并支持状态/时间筛选；详情可追溯原表单、执行条件、来源、阶段和错误，发现/有效/完整/失败数不混同。
- [x] API 运行中读取已持久部分并标草稿；发布结果严格读取任务关联快照；替换任务/达人 ID 无法读取无关联结果。
- [x] API 保持两组作品组内顺序、独立观测、缺失/截断/封面状态；游标不能跨任务、达人或集合复用。
- [x] 操作按状态版本与幂等校验；冲突返回当前版本和合法操作；无失败步骤不提供无意义重试。
- [x] React 实现默认 5 秒轮询、长等待 15 秒、终态停止；无会话直达任务 URL 在登录后恢复原路由。
- [x] 任务列表/详情、状态/时间筛选、服务端游标、合法操作、达人草稿/快照、F05 字段和 F06 双集合 React 页面与合成 API Chromium E2E 完成。
- [x] 使用真实产品 API/PostgreSQL/Temporal 验证页面刷新、退出/清缓存后恢复、两媒介共享任务及真实快照/封面展示。

## 验证证据

- 2026-09-27：静态盘点依据见 [项目基线证据](../evidence/PROJECT-BASELINE-2026-09-27.md)。
- 2026-10-10：[M3 本地产品控制台启动与真实数据联调证据](../evidence/M3-local-console-startup-2026-10-10.md)。在真实开发库（`127.0.0.1:55432 / xingtu_development`，迁移 008 后）与真实 Chromium 上完成只读联调：11 条真实任务列表、任务详情四类计数、达人 F05 字段与 F06 双集合、4 张 `STORED` 封面经认证 HTTP 返回 200（无会话 401、跨任务 404）；两媒介账号可共享读取同一任务；页面刷新保持会话、退出后直达任务 URL 回登录。此轮未推进任何任务状态、未提交新任务。
- 2026-10-10：[M3 后端实现与回归证据](../evidence/M3-backend-implementation-2026-10-10.md)。任务、操作、草稿/快照、双集合/封面范围均有 PostgreSQL 集成测试；Browser Contract 28/28、MinIO 专项 1/1。
- 2026-10-10：[M3 产品前端证据](../evidence/M3-product-frontend-2026-10-10.md)。真实 Chromium + 合成 API 2 passed，已通过登录恢复、任务列表→详情→达人快照/精选作品和创建任务提交链路。
- 2026-10-10：[M3 真实 DeepSeek 与产品闭环证据](../evidence/M3-real-product-acceptance-2026-10-10.md)。真实任务 `f47eb1cf-f038-4f9f-ae3d-e02aa8a995d3` 完成 P1→P2、轮询到 `PARTIAL_COMPLETED`、2 位发布快照、14 张双集合卡片/14 个封面、两媒介共享读取和 Chromium 重登恢复。

## 交接信息

本卡已完成。真实任务暴露的一位达人 `fans` 模块 `RESPONSE_SCHEMA_MISMATCH` 属 F05 平台契约变化调研；CONSOLE 已正确保留、呈现部分完成和字段失败，未因该下游缺口降低本卡验收标准。

## 状态历史

- 2026-10-10T23:15:00+08:00：已完成 → 已完成；冒烟后修复复核通过，真实产品任务 `f47eb1cf-f038-4f9f-ae3d-e02aa8a995d3` 已从部分完成升级为 `COMPLETED`，前端/API/DB 显示一致。
- 2026-10-11：已完成 → 已完成；通过完整本地受控 Worker 链路复核新任务 `acd929aa-874e-4de8-8fb1-6a9295cf07ff`，并复测终态达人列表自动刷新修复；真实 DeepSeek 新任务、真实自然挑战和生产环境仍保留为未完成验收项。

- 2026-10-10T22:45:00+08:00：已完成 → 已完成；Playwright MCP 独立冒烟复核通过任务列表、详情、取消操作、真实部分完成任务结果页、达人详情、双集合与封面引用的前端/API/DB 一致性。报告见[核心冒烟测试报告](../testing/smoke-test-f04-f05-f06-m3.md)。

- 2026-10-10T14:43:53+08:00：进行中 → 已完成；真实 DeepSeek/P1/Temporal/星图产品任务轮询至终态，2 位发布快照、双集合、受保护封面、两用户共享和退出/重登恢复全部通过；部分完成原因如实可见。
- 2026-10-10T14:21:22+08:00：进行中 → 进行中；用户授权继续使用开发数据库、两个媒介用户和现有 READY 执行单元，启动真实 DeepSeek/API/Temporal/星图小样本的轮询、共享读取与结果验收。
- 2026-10-10T14:08:00+08:00：进行中 → 进行中；应用迁移 008 后启动产品 API 与前端，在真实开发库 + 真实 Chromium 上完成只读联调（任务/详情/达人/F06 双集合/认证封面、两媒介共享、刷新与退出恢复）。剩余验收仍为真实产品任务全链路与真实星图任务，未以本轮只读联调勾选完成。
- 2026-10-10T13:52:36+08:00：进行中 → 进行中；最终全仓 `make check` 与 Chromium 任务列表 → 详情 → 达人快照/双集合闭环 2/2 再次通过。真实产品库/工作流验收尚未执行。
- 2026-10-10T10:54:01+08:00：进行中 → 进行中；任务列表/详情、5/15 秒轮询、操作幂等/409 刷新、达人分页、草稿/快照、F05 字段和 F06 双集合 React 页面及 Chromium 合成 API E2E 完成。真实产品环境验收仍未执行。
- 2026-10-10T10:25:46+08:00：阻塞 → 进行中；Lazyweb 本地 MCP 已恢复，启动 React 任务中心、状态轮询、达人详情和双集合结果页实施。
- 2026-10-10T09:04:02+08:00：进行中 → 阻塞；F07/F08 后端查询、操作、结果/封面 API 与集成证据完成，但 Lazyweb MCP 未暴露，无法按仓库强制流程实现 React 页面和产品浏览器闭环。
- 2026-10-09T19:50:53+08:00：待办 → 进行中；用户确认完整 M3 开发计划，启动 F07/F08 API、查询投影和测试实施；Lazyweb 工具缺失仅阻塞页面视觉落地。
- 2026-09-27T09:51:41+08:00：建立 → 待办；依据完整技术方案及代码盘点补齐一期任务规划，未改变业务范围。
