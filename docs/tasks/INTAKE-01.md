# INTAKE-01：筛选表单、P1 转换与可靠任务提交

状态：已完成
更新时间：2026-10-12T01:00:00+08:00
是否验收：是；2026-10-11 的「UI 提交后永久停留 `RECEIVED`」端到端缺陷已修复，并通过**真实 Playwright MCP + 真实 Chrome + 真实 DeepSeek** 的完整 UI 复跑验收（登录 → 发起 → 需求转换 → 排队 → 阻塞可见 → UI 取消）。P2 采集段仍需单独采集授权，不属于本卡范围。

## 2026-10-12 FIX-01 P1-B：已 `QUEUED` 任务取消到达终态

**根因（DEF-01）**：`product_queries.command("cancel")` 只对 `RECEIVED`/`PARSING` 直接落 `CANCELLED`，其余状态一律置 `CANCELLING`，终态化依赖 P2 `worker.dispatch()` 的收尾分支。**从未被派发过**的任务（`task_dispatches.sent=false`）在 P2 未运行时永久停在 `CANCELLING`，`allowed_actions=[]`，用户无法判断取消结果。

**最小修复**：迁移 `009_collect_dispatch_start.sql` 为 `task_dispatches` 增加可空列 `workflow_started_at`（不改写既有行）；`worker.dispatch()` 启动/确认启动后写 `sent=true,workflow_started_at=now()`；`Activities.collect` 对已是 `CANCELLED` 的任务直接返回终态；`product_queries` 取消分支新增 `_collect_workflow_started()` —— **从未启动采集工作流**的分段直接 `CANCELLED` + `TASK_CANCELLED`，已启动的维持 `CANCELLING` 交 P2。原 `RECEIVED`/`PARSING` 取消语义与 P2 唤醒路径均未改变。

**验证（Playwright MCP + 真实 Chrome + 真实 API/DB）**：任务是 `91a112ed-5dfe-488c-856d-c70e3109eecf`（宠物 / 目标 1），在页面提交后轮询 API，于 `QUEUED` v3 调用取消 → **HTTP 200、一次调用直达 `CANCELLED` v4**（`failure_reason=TASK_CANCELLED`、`allowed_actions=[]`，`CANCELLING` 未出现、version 只 +1），页面显示「已取消」。P2 持有路径（任务 `0300f417-c0fe-428d-9878-5aec314acc48`，`COLLECTING` v21 取消）→ `CANCELLING` 后约 0.5 s 由 P2 收尾为 `CANCELLED`（v22 → v23）。两条路径各有集成测试：`test_cancel_queued_task_without_a_started_collection_reaches_cancelled`、`test_cancel_queued_task_with_a_started_collection_still_waits_for_p2`。完整证据见 [FIX-01 真实采集闭环修复证据](../evidence/FIX-01-real-collection-close-2026-10-12.md)。

**观察缺口（已修复）**：根任务 `state` 列与 `payload.state` 必须同写。修复过程中一次验证脚本只改了列、未改 payload，导致 API 读到 payload 里的终态而拒绝取消（409 `ACTION_NOT_ALLOWED`）；已按 `CANCELLED`/`TASK_CANCELLED` 校正为一致。该现象不属产品代码缺陷，但作为「状态改动必须列与 payload 同写」的教训记录在此。

## 2026-10-11 RECEIVED 永久停留缺陷：根因、修复与复核

**根因（已验证，两个独立条件）**：① 产品入口独有的常驻 P1 Intake Worker 没有运行，`dispatch_intakes()` 从未执行；② 缺少 `DEEPSEEK_API_KEY`，该 Worker 启动即 `DEEPSEEK_API_KEY_REQUIRED` 退出。真实样本 `3c96c78a-77f8-4e11-8081-953b12deae91`（media-a / 关键词「户外」/ 目标 4）在 `RECEIVED` 停留 **7 小时 8 分**，`intake_dispatches.sent=false` 且 `updated_at == created_at`，`model_runs`/`filter_plans` 均为 0，Temporal `intake/*` 无对应工作流。此外原文档 §5 启动步骤只含 API 与前端，`make dev` 也只起 Compose，因此按文档操作必然复现。

**已完成的最小修复**：启动编排与就绪门禁（`scripts/m3_up.py`、`make m3-check`/`m3-up`/`collection-worker`）；派发循环异常隔离与派发失败留痕（`intake_worker.py`、`product_repository.py`）；任务级三态可见性（`worker_health.py`、`product_models.IntakeProgress`、`product_queries` 判定、`GET /api/health/workers`、前端阻塞面板与文案）；`promote_intake` 失败终态化；`no_proxy` 中 `[::1]` 导致 httpx `InvalidURL` 的环境缺陷修复。

**复核结果（真实模型 + 隔离 schema）**：`verify_model()` PASS（`GET /models` 返回 `deepseek-flash`、`deepseek-v4-pro`）；无消费者时任务停在 `RECEIVED`（`sent=false`、0 model run、0 plan），消费者出现后 **+0.13 s 见新鲜 poller、+1.71 s 任务转为 `QUEUED` v3**；真实 `model_runs` 1 条 `succeeded`（1126 input / 88 output、1262 ms），`filter_plans` 1 条 `source=model` 且与确定性期望完全相等，`task_dispatches` 1 条。分层回归：`make check` exit 0（单元 178 passed）、集成 69 passed/1 skipped、契约 28 passed、e2e 9 passed。完整证据见 [M3 Intake Worker 修复证据](../evidence/M3-intake-worker-fix-2026-10-11.md)。

**重要机制修正**：Temporal poller 的 `last_access_time` 是粗粒度信号 —— 实测健康 Worker 的刷新间隔为 58 s / 58 s / **121 s**，停止后条目仍保留数分钟。因此“无人接管”判定改为任务级（`sent=false` 超过 120 s 且无派发失败记录），poller 新鲜度阈值取 180 s 仅作诊断元数据；**不得**再用 poller 计数或 10 s 级新鲜度判活。

**本轮未完成**：① 真实用户在页面点击提交的现场确认（运行环境已就绪：`make m3-up` 前置自检 13/13 通过、`xingtu-intake` 消费者在线）；② `QUEUED → 采集完成` 段需显式采集授权后运行 `make collection-worker`；③ 精确秒级 Worker 心跳（需迁移 009）列为后续可靠性增强。

## 2026-10-11 完整新任务闭环修复复核（历史）

首次冒烟的新任务停在 `RECEIVED` 的原因已确认是运行环境缺少 Intake Worker/Collection Worker，且当时没有 `DEEPSEEK_API_KEY`，不是 UI 提交或数据库受理失败。本次在不修改 Intake 业务逻辑的前提下，启动 Intake Worker、Collection Worker 和 localhost-only DeepSeek-compatible Fixture，使用 Playwright MCP 重新创建任务 `acd929aa-874e-4de8-8fb1-6a9295cf07ff`。

任务真实经过 `RECEIVED → PARSING → QUEUED → COLLECTING → COMPLETED`，关键词“宠物”和目标 1 保持不变；最终发现 20、有效 1、资料完整 1、精选完整 1、失败 0。该结果证明本地受控条件下表单 → Product API → Intake Worker → P1 Workflow → P2 Collection Worker 的提交和晋级链路可运行。

边界：本次 P1 使用本地 Fixture，不是真实 DeepSeek；既有真实 DeepSeek 任务证据仍由 `f47eb1cf-f038-4f9f-ae3d-e02aa8a995d3` 单独支撑。生产模型调用、生产 HTTPS/Secure Cookie 和真实自然安全验证不因本次本地闭环通过而自动完成。

## 2026-10-10 F04/F05/F06/M3 核心冒烟复核

本轮通过 Playwright MCP 真实 UI 操作复核 INTAKE-01 的能力驱动表单与可靠提交入口，报告见 [F04/F05/F06/M3 核心冒烟测试报告](../testing/smoke-test-f04-f05-f06-m3.md)。创建页只展示 1 项已核验条件“内容关键词”，默认目标 20、允许范围 1—200；空表单提交被页面校验拦截。填写关键词“冒烟测试”、目标 1 后提交成功，生成 root `b12b5785-f90a-42c2-8c4f-67c54ab690e4`。

同一任务跨层核对：API 初始状态为 `RECEIVED`；DB 中 `root_tasks.task_type=product_intake`，需求关键词“冒烟测试”、目标 1、`submitted_by=smoke-qa-20261010`，P1 task kind 为 `P1`，`intake_sent=false`。由于本轮环境未运行 Intake Worker/Collection Worker，该新任务未进入 P1/P2 执行；为避免后续真实平台采集，已通过 UI 取消，前端/API/DB 一致为 `CANCELLED`、version 1、`TASK_CANCELLED`。结论：受理、持久化、取消一致性 PASS；新任务执行到采集完成 BLOCKED 于 worker 环境，不改变本卡已完成状态。

## 目标与范围

**目的**：打通媒介原始需求到合法采集任务的入口，确保 AI 不改变用户筛选意图。

**任务内容**：表单与能力查询、RequirementForm、原始需求持久化、异步 P1 Activity、模型供应商适配、版本化 Prompt 和结构化输出、逐字段覆盖/语义校验、model_runs、可靠提交与启动派发；补齐 RECEIVED/PARSING/FAILED_VALIDATION 等实际链路，合法计划交给现有采集器。

**不包含**：不允许空条件搜索、模型自由点击、额外确认页或未核验选项；不实现采集器内部字段读取。

## 关联与依赖

F02/F03；技术方案第 3—4、13—16 章。T01—T04/T14/T21，U01/U02/U03。

前置：[APP-01](APP-01.md)、[BASE-01](BASE-01.md)；能力字典由 [UNIT-01](UNIT-01.md) 和 [F04](F04.md) 核验。离线开发可使用明确标识的合成能力及模型替身。

## 当前开发状态与实现记录

2026-10-10 已实现 `RequirementForm v1`、能力 DTO、事务化提交、产品幂等、`intake_dispatches`、`model_runs`、LangGraph `StateGraph`、DeepSeek Responses API Adapter、有限修复、P1 Temporal Workflow/Worker 及原 `root_task_id` 上的 P2 原子晋级。F04 仍接收原 `FilterPlan v1`；未修改平台 Adapter、Parser 或 Engine。

实现依据：[类型契约](../../backend/src/xingtu/product_models.py)、[Intake Graph](../../backend/src/xingtu/intake.py)、[Intake Worker](../../backend/src/xingtu/intake_worker.py)、[产品仓储](../../backend/src/xingtu/product_repository.py)、[迁移 008](../../migrations/008_m3_product_app.sql)、[DEC-014](../decisions/DEC-014-m3-product-application-and-intake.md)。

同日后续已实现 [能力驱动表单](../../frontend/src/pages.tsx)、只渲染 capability API 返回的字段、默认 20/限制 1—200、稳定创建幂等键、修改重提和 202 后根任务跳转，见 [前端证据](../evidence/M3-product-frontend-2026-10-10.md)。

## 验收清单

- [x] 后端表单契约要求至少一项业务筛选，默认 20、允许 1—200；0/201/非整数、反向区间、错单位和语义冲突被拒绝。
- [x] Mock/本地集成中每份处理表单有模型运行记录；丢字段、加条件、范围改变、错误枚举或不支持组合被确定性校验阻止，失败不获取浏览器。
- [x] 模型超时与修复预算按附录 A；失败可见且不降级为空搜索，供应商/Prompt/用量/耗时/错误可追溯，U03 配额与数据处理安排有记录。
- [x] 原需求、根任务与启动意图同事务提交；202 返回 ID；同键同内容返回原任务、异内容冲突，响应丢失及重复派发不重复采集。
- [x] 修改重提通过来源根任务创建新需求；旧需求不变。旧 `internal_acceptance`、检查点与工作流兼容测试保持通过。
- [x] 使用真实 U02 能力和已选模型完成首批字段及组合验证；与 F04 页面回读衔接，通过 T01—T04 适用全链路。本轮“首批”严格指 live 注册表唯一已核验的 `keyword:eq` 组合。
- [x] 完成能力驱动 React 表单、组件测试与真实 Chromium + 合成 API 提交 E2E。
- [x] 在真实 PostgreSQL/Temporal/DeepSeek 和已核验星图关键词环境中完成前后端全链路联调。
- [x] （2026-10-11 新增）运行编排保证 P1 Intake Worker 与 P2 Collection Worker 不可遗漏：`make m3-check` 只读前置自检 13/13 通过，`make m3-up` 在出现新鲜消费者后才宣告 READY。
- [x] （2026-10-11 新增）无消费者可见且可区分：`TaskDetail.intake` 返回 `sent`/`pending_seconds`/`consumer_alive`/`blocked_reason`，`INTAKE_WORKER_UNAVAILABLE` 与 `INTAKE_DISPATCH_FAILING` 两态经集成测试与 API 序列化测试验证。
- [x] （2026-10-11 新增）派发失败不再杀死消费者：单元测试证明单任务 `start_workflow` 异常被留痕并保持 `sent=false` 重试，其余任务照常派发。
- [x] （2026-10-11 新增）真实模型闭环：真实 `DeepSeekAdapter` + 真实派发循环在隔离 schema 内把任务从 `RECEIVED` 推进到 `QUEUED`（+1.71 s），生成 1 条真实 `model_runs`（1126/88 tokens、1262 ms）、1 条 `source=model` 的 `filter_plans` 与 1 条 `task_dispatches`。
- [x] （2026-10-11 新增）`promote_intake` 非取消异常改为 `FAILED` + `field_errors` 终态，不再永久停留 `PARSING`。
- [x] （2026-10-11 新增）**真实用户在页面提交后确认任务离开 `RECEIVED`**：通过真实 Playwright MCP + 真实 Chrome 登录 `media-a`、填写「户外/4」并提交，页面 `t+1.61 s` 进入 `QUEUED` v3，最终执行计划关键词与目标未被改写。
- [x] （2026-10-11 新增）UI 阻塞可见与 UI 取消：无 Worker 时页面在 `t+120.5 s` 显示「需求转换工作流未运行…已等待 2 分 01 秒」阻塞面板；点击「取消任务」后在 `RECEIVED` 阶段直接终态化为 `CANCELLED`（0 次模型调用）。

## 验证证据

- 2026-09-27：静态盘点依据见 [项目基线证据](../evidence/PROJECT-BASELINE-2026-09-27.md)。
- 2026-10-10：[M3 本地产品控制台启动与真实数据联调证据](../evidence/M3-local-console-startup-2026-10-10.md)。确认能力接口在真实运行环境下只返回 1 项已核验条件（`keyword`）、默认 20、范围 1—200，且 `/tasks/new` 只渲染该字段；本轮**未提交新任务**，因为环境无 `DEEPSEEK_API_KEY`，Intake Worker 无法启动（`DEEPSEEK_API_KEY_REQUIRED`），提交只会停留在 `RECEIVED`。真实模型与真实星图关键词验收项保持未勾选。
- 2026-10-10：[M3 后端实现与回归证据](../evidence/M3-backend-implementation-2026-10-10.md)。P1 节点/路由/三次上限单测、PostgreSQL 原子链路和 Temporal E2E 均通过。
- 2026-10-10：[M3 产品前端证据](../evidence/M3-product-frontend-2026-10-10.md)。当 capability 仅返回关键词时页面不显示其他条件；浏览器提交带稳定幂等键、默认目标 20 并进入同一根任务。
- 2026-10-10：[M3 真实 DeepSeek 与产品闭环证据](../evidence/M3-real-product-acceptance-2026-10-10.md)。真实 `deepseek-flash` 模型检查、JSON Schema 生成、`model_runs` 用量/耗时追溯与“游戏剧情”目标 2 的 P1→P2 同根任务闭环通过；最终取得 2 位真实达人并如实收口为 `PARTIAL_COMPLETED`。
- 2026-10-11：[MCP UI 端到端测试报告](../testing/mcp-ui-e2e-2026-10-11.md)。以**已注册到 profile 的原生 MCP 工具**（`mcp__playwright__*`）+ 真实 Chrome 复跑完整流程：登录门禁、发起「露营/3」→ `QUEUED` v3（提交后 2.67 s，真实 `model_runs` 1126/88 tokens、862 ms）、无 Worker 时 `t+140 s` 出现 `INTAKE_WORKER_UNAVAILABLE`（同时 `consumer_alive=true`，验证任务级判定不被残留 poller 误导）、`RECEIVED` 阶段取消 → `CANCELLED` v1 且 0 次模型调用。13 条用例 PASS，1 条 FAIL（DEF-01：已 `QUEUED` 任务取消停在 `CANCELLING`，需 P2 收尾）。
- 2026-10-11：[M3 Intake Worker 修复证据](../evidence/M3-intake-worker-fix-2026-10-11.md)。记录 `RECEIVED` 停留 7h8m 的真实样本、两个独立根因、隔离 A/B 复现、真实模型 `RECEIVED → QUEUED` 复核（1126/88 tokens、1262 ms）、poller 粗粒度实测（58/58/121 s）与分层回归结果（`make check` exit 0、集成 69/1 skipped、契约 28、e2e 9）。

## 交接信息

M3 P0 的代码与自动检查已完成。剩余事项：① 真实用户在页面提交后离开 `RECEIVED` 的现场确认；② `QUEUED → 采集完成` 段需显式采集授权后运行 `make collection-worker`（本轮未访问巨量星图）；③ 精确秒级 Worker 心跳（需迁移 009）为后续可靠性增强。U02 未登记的达人类型、粉丝量和互动率继续不对产品开放；该扩展属 F04/能力注册表的后续真实契约核验，不影响当前 keyword P0 验收结论。模型密钥已写入被 gitignore 的 `.runtime/deepseek.env`（0600），因已在会话中明文出现，验收后建议轮换。

## 状态历史

- 2026-10-11T23:55:00+08:00：已完成 → 已完成；用已注册到 profile 的原生 Playwright MCP 工具（`mcp__playwright__*`）+ 真实 Chrome 复跑完整 UI 流程，13 条用例中 12 PASS / 1 FAIL；FAIL 为已 `QUEUED` 任务取消停在 `CANCELLING`（DEF-01，P1 设计缺口，需 P2 Worker 收尾，未修复），其余（发起、需求转换、状态流转、阻塞可见、intake 阶段取消、会话跨 API 重启）全部通过。报告见 [MCP UI 端到端测试报告](../testing/mcp-ui-e2e-2026-10-11.md)。
- 2026-10-11T23:20:00+08:00：待验收 → 已完成；真实 Playwright MCP + 真实 Chrome 完成完整 UI 复跑：登录门禁、发起（户外/4 → `QUEUED` v3 @ t+1.61 s）、无 Worker 时阻塞面板（`INTAKE_WORKER_UNAVAILABLE` @ t+120.5 s）、UI 取消（`CANCELLED` @ t+1.64 s、0 model run）、任务中心一致性，浏览器控制台无 JS 异常。新发现：已 `QUEUED` 的任务取消后停在 `CANCELLING`（需 P2 Worker 收尾），已记入证据并列为 P1 建议。
- 2026-10-11T18:40:00+08:00：已完成 → 待验收；发现并修复「UI 提交后任务永久停留 `RECEIVED`」端到端缺陷（根因：Intake Worker 未运行 + 缺模型凭据；伴随：无消费者不可见、派发失败会杀死消费者、promote 失败无终态、`no_proxy` 触发 httpx `InvalidURL`）。代码、编排、可见性与测试门禁完成，真实模型 `RECEIVED → QUEUED` 复核通过；仅剩真实用户 UI 现场确认与 P2 采集授权段。
- 2026-10-10T22:45:00+08:00：已完成 → 已完成；Playwright MCP 独立冒烟复核通过能力驱动表单、表单校验、UI 提交、API/DB 持久化和 UI 取消一致性。新建任务因本地 worker 未启动未进入 P1/P2，已取消并作为环境阻塞记录。报告见[核心冒烟测试报告](../testing/smoke-test-f04-f05-f06-m3.md)。
- 2026-10-11：已完成 → 已完成；启动本地受控 Intake/Collection Worker 与模型 Fixture 后，Playwright MCP 新建任务 `acd929aa-874e-4de8-8fb1-6a9295cf07ff` 完成 P1→P2→F04/F05/F06→API/UI 展示闭环；真实 DeepSeek 新任务现场调用仍未执行。

- 2026-10-10T14:43:53+08:00：进行中 → 已完成；真实 DeepSeek Flash、PostgreSQL/Temporal、已核验关键词和星图 2 位产品闭环通过。未登记互动率同步 422，未核验达人类型/粉丝组合 `FAILED_VALIDATION`，且为 0 model run/0 collection dispatch，fail-closed 成立。
- 2026-10-10T14:21:22+08:00：进行中 → 进行中；用户提供 DeepSeek 验收资源，启动真实 P1/产品闭环验收。预检确认 live capabilities 仍只允许内容关键词；本轮以“游戏剧情”、目标 2 执行，不伪造“达人类型/粉丝 10—100w/互动率≥2%”已受支持。
- 2026-10-10T14:08:00+08:00：进行中 → 进行中；产品 API 与前端在真实开发库启动后核对能力接口与动态表单；因缺 `DEEPSEEK_API_KEY` 未启动 Intake Worker、未提交真实产品任务，真实模型与小样本验收项保持未勾选。
- 2026-10-10T13:52:36+08:00：进行中 → 进行中；最终全仓 `make check` 与 Chromium 合成 API 提交闭环再次通过。仍未提供 DeepSeek 真实资源，也未创建真实星图新任务，因此不改为已验收。
- 2026-10-10T10:54:01+08:00：进行中 → 进行中；能力驱动表单、稳定幂等键、修改重提与 Chromium 合成 API 提交 E2E 完成。真实 DeepSeek/星图小样本仍未验收。
- 2026-10-10T10:25:46+08:00：阻塞 → 进行中；Lazyweb 本地 MCP 已恢复，启动 capability-driven React 表单与产品联调；真实 DeepSeek 验收仍等待 API key/配额与数据处理确认，但不再阻塞当前前端开发。
- 2026-10-10T09:04:02+08:00：进行中 → 阻塞；F02/F03 后端、迁移、StateGraph、DeepSeek Adapter、Intake Workflow 和本地自动化证据完成。继续完成必要验收需要恢复 Lazyweb MCP 并提供 DeepSeek API key/配额与数据处理确认。
- 2026-10-09T19:50:53+08:00：待办 → 进行中；用户确认完整 M3 开发计划，启动 F02/F03 契约、迁移、可靠提交和 P1 工作流实施。
- 2026-09-27T09:51:41+08:00：建立 → 待办；依据完整技术方案及代码盘点补齐一期任务规划，未改变业务范围。
