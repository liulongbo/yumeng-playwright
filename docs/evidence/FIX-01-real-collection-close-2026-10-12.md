# FIX-01 真实采集闭环修复证据（2026-10-12）

> 范围：[FIX-01](../tasks/FIX-01.md) 的 P0-A（`fans` 模块）/ P1-B（已 `QUEUED` 取消无终态）/ P1-C（采集 Worker 派发崩溃）/ P3-D（取消被显示成「需要关注」）。
> 证据来源：真实平台采集（本机 Chrome + 项目独立 profile + `unit-local-mac-02`）、Playwright MCP 原生工具（`mcp__playwright__*`）、真实 PostgreSQL `55432/xingtu_development`、真实 DeepSeek。
> 关联：[MCP UI 端到端测试报告](../testing/mcp-ui-e2e-2026-10-11.md)（第二次测试，本卡的缺陷来源）、[M3 Intake Worker 修复证据](M3-intake-worker-fix-2026-10-11.md)（第一次测试）。

## 0. 结论摘要

| 问题 | 结论 | 关键证据 |
|---|---|---|
| P0-A `fans` 模块失败 | **不是契约漂移，也不是解析缺陷**：真实响应结构与契约字段路径完全一致，4 个 `data_sp` 请求全部 HTTP 200 / `base_resp.status_code=0`。原失败是一次**平台瞬时响应被拒绝**，且当时失败证据里没有记录「是哪个请求被拒绝」，无法归因。已补齐请求级、脱敏的失败诊断；关闭诊断后重新做了一次**全新真实提交**，`fans` 首次尝试即 `COLLECTED`，根任务 `COMPLETED` | 第 2、3 节；任务 `7620fb83-019a-45c5-a547-1c42e2b12080` |
| P1-B `QUEUED` 取消停在 `CANCELLING` | 已修：取消时若该任务分段的采集工作流**从未启动**，API 直接终态化 `CANCELLED`；已启动的仍保持 `CANCELLING` 交 P2 收尾 | 第 4 节；新迁移 `009_collect_dispatch_start.sql` |
| P1-C 采集 Worker 派发崩溃 | 本轮补 5 个单元测试（含 describe/signal `RPCError`、dispatch 记录启动时刻、tick 异常不杀消费者）；并按同一行为补 intake 派发 tick 的等价测试 | 第 5 节 |
| P3-D 主动取消被显示成「需要关注」 | 已修：`CANCELLED` 中性文案与中性徽标，`TASK_CANCELLED` 不进红色关注面板，内部错误码不再出现 | 第 6 节 |

## 1. 环境与方法

| 项 | 值 |
|---|---|
| 执行方式 | Harness 原生 MCP 工具 `mcp__playwright__*`（真实 Chrome，`--isolated`，产物 `/tmp/dsh-playwright-mcp`） |
| 前端 | Vite `http://127.0.0.1:5173`（`/api` 代理 `127.0.0.1:8000`） |
| 后端 | `xingtu-api` + `xingtu-product intake-worker` + `xingtu worker`（采集）三个进程在线；Temporal `127.0.0.1:57233`；业务库 `55432/xingtu_development` |
| 模型 | 真实 `deepseek-flash`（`https://api.deepseek.com`，`GET /models` 200） |
| 账号 | `media-a`（本地开发媒介账号） |
| 执行单元 | `unit-local-mac-02`（`local_development`，本机 Chrome 154.0.8037.98） |
| 契约版本 | `xingtu-ad-creator-featured-v9`（未修改） |

**诊断探针**（P0-A 归因用，只读、不写业务库）：`xingtu research` 在项目独立 profile 内打开达人主页并点击「连接用户」标签页，记录参与者请求的结构与平台业务消息。探针报告位于 `.runtime/research/fix01-fans-probe{1,3,4,5}`（gitignore，仅本机保留）。

## 2. P0-A：`fans` 失败的真实原因

### 2.1 原失败任务的可核对事实（修复前）

任务 `02c81708-49b5-4384-b119-6ff3f5eb48c8`（宠物 / 目标 1），失败发生在 2026-10-11T16:01:34Z：

- 达人 `6779401118494490632` 的 8 个模块中 7 个 `COLLECTED`，仅 `fans`：`status=FAILED`、`coverage_gaps=['module unreadable']`、唯一字段 `__module_failure__` 的 `failure_reason = PLATFORM_PAGE_CHANGED:RESPONSE_SCHEMA_MISMATCH`。
- 契约健康：`contract_capability_failures` 1 行 —— `scope=profile_module:fans`、`failure_reason=RESPONSE_SCHEMA_MISMATCH`。
- 失败证据文件 `.runtime/evidence-local/failure/02c81708-.../9e476392....json`：`failure_reason=PLATFORM_PAGE_CHANGED:RESPONSE_SCHEMA_MISMATCH`、`schema_keys=[]`、`status_code=null`。

`RESPONSE_SCHEMA_MISMATCH` 的唯一产生点是 `ResponseCollector.read_response`：某个**已注册请求**的响应 `status != 200`，或 `success_path`（`base_resp.status_code`）的值不等于 `"0"`。原证据里没有记录是哪个请求、HTTP 状态与业务码，因此当时无法归因 —— 这本身是一个应当修复的观测缺口。

### 2.2 真实响应结构（探针，2026-10-12 00:16–00:21）

在真实 Chrome 中打开 `https://www.xingtu.cn/ad/creator/author-homepage/douyin-video/6779401118494490632` 并点击「连接用户」，`fans` 模块的 4 个请求全部出现且全部成功：

| 请求 key | 路径 | HTTP | `base_resp.status_code` | 请求参数（与契约一致） |
|---|---|---|---|---|
| `daily_fans` | `/gw/api/data_sp/get_author_daily_fans` | 200 | 0 | `author_id=<creator>`、`platform_source=1` |
| `link_card` | `/gw/api/data_sp/author_link_card` | 200 | 0 | `o_author_id=<creator>`、`platform_source=1`、`platform_channel=1` |
| `daily_link` | `/gw/api/data_sp/author_daily_link` | 200 | 0 | `o_author_id=<creator>`、`platform_source=1`、`platform_channel=1` |
| `audience_distribution` | `/gw/api/data_sp/author_audience_distribution` | 200 | 0 | `o_author_id=<creator>`、`platform_source=1`、`platform_channel=1` |

契约引用的每个字段路径都真实存在（节选）：

- `link_card.link_struct.5.value`（月连接用户数）、`link_struct` 1–5（连接漏斗）；
- `daily_fans.daily`/`delta`（各 30 项）、`fans_growth_v2`、`fans_growth_rate_v2`；
- `daily_link.link_daily_cnt`（30 项）；
- `audience_distribution.distributions`（8 组画像）、`last_update_time`。

结论：**契约没有漂移，字段路径与解析口径都正确**。`fans` 失败只能来自一次被拒绝的瞬时响应（非 200 或业务码非 0），而且当时没有被记录下来。

### 2.3 观测缺口修复（请求级、脱敏的失败诊断）

改动位置：

- `backend/src/xingtu/observer.py`：新增 `RequestDiagnostic`（数据类）与 `content_type_kind()`；`read_response` 在拒绝响应时把「请求 key、HTTP 状态、content-type 类别、业务码路径与值、响应顶层 key 名、lookup 异常类型」附加到 `CollectorError.diagnostics`。**不记录响应正文、URL、query 值、Cookie 或任何页面文本。**
- `backend/src/xingtu/domain.py`：`CollectorError.diagnostics` 容器（默认空列表）。
- `backend/src/xingtu/evidence.py`：`EvidenceSummary` 新增 `response_keys` 与 `diagnostic`（allowlist 结构）；`status_code` 现在会写入被拒绝响应的 HTTP 状态。
- `backend/src/xingtu/engine.py`：`record_evidence(..., error=...)` 把诊断落到失败证据；新增 `rejected_response_diagnostic()` / `response_key_paths()`。

失败原因字符串保持原样（`PLATFORM_PAGE_CHANGED:RESPONSE_SCHEMA_MISMATCH`），以便已有断言与既有证据兼容；新增信息只进证据文件。

**回归**：`make check` 通过；证据结构新增字段后，`test_evidence_records_exhaustion_and_module_failure` 等既有集成用例仍通过（见第 7 节）。

### 2.4 复现结论：这是一次瞬时拒绝，不是确定性缺陷

- 修复前，对原失败任务 `02c81708-...` 走同一产品「重试失败步骤」路径（P2 正常路径，非人工补数）：`COLLECTING → COMPLETED`，`fans` 模块 `coverage_gaps=[]`、无失败字段、`profile_complete_count=1`。任务最终 `COMPLETED`、version 138。
- 修复后，**全新提交、不干预**：任务 `7620fb83-019a-45c5-a547-1c42e2b12080`（宠物 / 目标 1）首次尝试即让 `fans` 成功（`module_seconds.fans=2.27 s`），根任务 `COMPLETED`。

因此对 F05 与全站的正确结论是：**`fans` 的失败是可复现的瞬时平台拒绝，而不是契约或解析的确定性缺陷**；同时把「失败必须能指名到请求」这一观测能力补上，使下一次同类事件可以直接归因。诊断代码不改变成功/失败判定，也不放宽任何完整度断言。

### 2.5 修复后真实采集结果（任务 `7620fb83-019a-45c5-a547-1c42e2b12080`）

状态序列（API 观测）：`RECEIVED → PARSING → QUEUED → COLLECTING → COMPLETED`（version 0 → 93）。

| 观测点 | 实测值 |
|---|---|
| 提交时间 | 2026-10-12 00:27:32（Asia/Shanghai，`make` 环境本地时区显示） |
| 终态时间 | 2026-10-12 00:28:49 |
| 终态 | `COMPLETED`，`failure_reason=null`，`allowed_actions=[]` |
| 计数 | 已发现 20 / 有效入库 1（目标 1）/ 资料完整 1 / 精选完整 1 / 失败步骤 0 |
| 平台交互 | 45 请求 / 45 响应、导航 4 次、重复请求 0、安全验证 0 |
| 8 个模块 | `basic/spread/seeding/creation/commercial/conversion/fulfillment` 全部 `COLLECTED`、`coverage_gaps=[]`；**`fans` `COLLECTED`、`coverage_gaps=[]`、9/9 字段** |
| 各模块耗时 | `fans 2.27 s`、`creation 2.34 s`，其余 < 0.1 s |

`basic` 模块 20 个字段中 19 个 `COLLECTED`、`industry_labels_raw` 为 `NO_DATA`（平台返回 `[]`，与 2026-10-08 已验收口径一致，不是失败）。

数据库落库（真实采集结果）：

| 表 | 数量 / 值 |
|---|---|
| `task_creators` | 1（platform ID `6779401118494490632`） |
| `creator_snapshots` | 1（`snapshot_id=4f91d267-4d18-4584-8497-53093696a1bf`） |
| `featured_collections` | 2（`excellent_reach` = COMPLETE、`excellent_seeding` = COMPLETE） |
| `featured_cards` | 5（4 + 1，全部 `cover_status=STORED`、`identity_kind=platform_content_id`） |
| 平台作品 ID | `7691283725908184360`、`7688668911646051624`、`7689048604060847402`、`7683484854813592882`、`7690178298102114747` |

前端与数据库一致性（MCP 在真实 Chrome 中读取 DOM）：

- 任务详情：`已完成`、「目标链路已完成，可查看发布快照。」、`已发现 20 / 有效入库 1 / 资料完整 1 / 精选完整 1 / 失败步骤 0`，**无红色「需要关注」面板**、**无「重试失败步骤」按钮**。
- 达人详情：8 个模块全部显示 `COLLECTED`（`fans` 9 字段、`basic` 20、`spread` 18、`seeding` 7、`creation` 6、`commercial` 2、`conversion` 10、`fulfillment` 9），页面 `.attention-panel` 数量为 0。
- `fans` 真实值示例（前端 = 数据库快照）：`monthly_connected_users = 34073382`（`{"kind":"number","bound":"exact","amount":"34073382","quantum":"1"}`）、`connection_funnel.5.value = 34073382`（与月连接用户数自洽）、`audience_distributions` 8 组画像、`audience_last_updated_at = 1791736071`。
- 两组精选：优秀传播视频 4 张卡片 + 优秀种草视频 1 张卡片，封面全部渲染成功（`cover_object_id` 经 `/api/tasks/<id>/covers/<object_id>` 返回）。

### 2.6 既有已完成任务不回归

| 任务 | 修复后状态 |
|---|---|
| `f47eb1cf-f038-4f9f-ae3d-e02aa8a995d3` | `COMPLETED`，`profile_complete_count=2`、`featured_complete_count=2`、`failure_reason=null`，44 份快照 |
| `acd929aa-874e-4de8-8fb1-6a9295cf07ff` | `COMPLETED`，`profile_complete_count=1`、`featured_complete_count=1`，4 份快照 |
| `02c81708-49b5-4384-b119-6ff3f5eb48c8` | 经产品「重试失败步骤」到 `COMPLETED`、version 138，`profile_complete_count=1` |

## 3. 本轮真实任务清单与影响

| 任务 ID | 关键词/目标 | 终态 | 说明 |
|---|---|---|---|
| `7620fb83-019a-45c5-a547-1c42e2b12080` | 宠物 / 1 | `COMPLETED` | **P0-A 验收任务**：一次提交、不干预、首次尝试 `fans` 成功 |
| `02c81708-49b5-4384-b119-6ff3f5eb48c8` | 宠物 / 1 | `COMPLETED`（重试后） | 原失败任务，经产品「重试失败步骤」补齐 `fans` |
| `91a112ed-5dfe-488c-856d-c70e3109eecf` | 宠物 / 1 | `CANCELLED` | **P1-B 验收任务**：`QUEUED` 阶段取消 → API 一步终态化（见第 4 节） |
| `0300f417-c0fe-428d-9878-5aec314acc48` | 宠物 / 1 | `CANCELLED` | **P3-D + P2 收尾验收**：采集中（`COLLECTING`）取消 → P2 收尾为 `CANCELLED` |

四条任务均为真实平台流量（各 1 位达人、单次提交、无重复提交、无风控触发）。`91a112ed` 的 `root_tasks.state` 列曾在一次验证脚本中被单独改写（只改列、未改 payload），已按 `CANCELLED`/`TASK_CANCELLED` 校正为列与 payload 一致；该任务的 payload 内容未被伪造或删除。

## 4. P1-B：已 `QUEUED` 任务取消的终态化

### 4.1 根因

`product_queries.command("cancel")` 对已进入 P2 的任务一律置 `CANCELLING`，真正的终态化只在 P2 `worker.dispatch()` 的收尾分支里发生。没有 P2 Worker 时（或该任务**从未被派发过**时），任务永久停在 `CANCELLING`，`allowed_actions=[]`，用户无法判断结果。

### 4.2 最小修复

- 新迁移 `migrations/009_collect_dispatch_start.sql`：`task_dispatches` 增加可空列 `workflow_started_at timestamptz`（不改写任何既有行，`sent=false` 且无启动时刻 = 「从未派发」）。
- `backend/src/xingtu/worker.py`：`dispatch()` 在成功启动/确认已启动后，除 `sent=true` 外同时写 `workflow_started_at=now()`；`Activities.collect` 对已是 `CANCELLED` 的任务直接返回终态，避免取消后仍启动采集。
- `backend/src/xingtu/product_queries.py`：取消分支新增 `_collect_workflow_started()` —— 只依据 `workflow_started_at` 判定「是否可能有采集进程持有该任务」。为假则直接 `CANCELLED` + `failure_reason='TASK_CANCELLED'`；为真则维持 `CANCELLING` 交 P2 收尾。原有 `RECEIVED`/`PARSING` 与 P2 唤醒路径不变。

### 4.3 两条路径的验证

**无 P2 持有（本次真实 UI 验收）**：MCP 在页面提交（宠物 / 1）→ 轮询 API → 在 `QUEUED` v3 立即取消：

| t (s) | 状态 | version | allowed_actions |
|---|---|---|---|
| 0.83 | `RECEIVED` | 0 | `[cancel]` |
| 2.16 | `QUEUED` | 3 | `[cancel]` |
| 3.25 | `CANCELLED` | 4 | `[]` |

`POST /api/tasks/<id>/cancel` 返回 HTTP 200，**一次调用直接到达终态**（`version` 只 +1），`failure_reason=TASK_CANCELLED`；页面显示「已取消」。

**有 P2 持有（真实平台，采集中取消）**：任务 `0300f417-...` 在 `COLLECTING`（version 21）取消 → API 置 `CANCELLING`，P2 派发循环在约 0.5 s 内收尾为 `CANCELLED`（version 22 → 23）。

**测试覆盖**：`backend/tests/integration/test_product_m3.py`

- `test_cancel_queued_task_without_a_started_collection_reaches_cancelled`：`QUEUED` + `sent=false`/无启动时刻 → 一次调用 `CANCELLED`、`version+1`、`allowed_actions=[]`。
- `test_cancel_queued_task_with_a_started_collection_still_waits_for_p2`：`QUEUED` + 已记启动时刻 → `CANCELLING`，且**不由 API** 终态化。
- `test_real_dispatch_records_the_start_moment_in_the_database`：用假 Temporal client 跑**真实 `worker.dispatch()` SQL**（真实库、真实 Repository），断言 `workflow_started_at` 被写入，并断言取消闸门随后把该任务视为「可能被持有」。这把「迁移列 + 真实 UPDATE + 取消判定」串成一个可回归的闭环，弥补了「上一轮真实派发仍由旧进程完成」的验证缺口。

## 5. P1-C：采集 Worker 派发崩溃

已完成的修复（本轮补测，未改行为）：`dispatch()` 的 `describe()`/`signal()` `RPCError` 保护、`WorkflowAlreadyStartedError` 分支保护、`run_worker()` 每 tick 兜底只记日志、`cli.py` 生命周期日志。

新增 `backend/tests/unit/test_collection_worker_dispatch.py`（5 个用例）：

1. `describe()` 返回 RUNNING 但 `signal()` 抛 `RPCError` → 终态化 `CANCELLED`，不抛出（复现原崩溃指纹）；
2. `describe()` 抛 `RPCError` → 同样终态化；
3. 工作流确实 RUNNING → 只发信号、不由 worker 终态化（唤醒路径未被破坏）；
4. 派发后写入 `sent=true` **与** `workflow_started_at`（P1-B 依赖的持久事实）；
5. 真实 `run_worker()` 装配下，派发 tick 持续抛错时消费者仍存活（tick 间隔后仍未退出）。

**Intake / 采集一致性**：`backend/tests/unit/test_intake_worker_dispatch.py` 新增 `test_intake_tick_survives_an_unexpected_listing_failure` —— 用真实 `run_intake_worker()` 装配验证 `pending_intake_dispatches()` 抛错时消费者仍存活。两者行为一致：**单次派发/单个 tick 的异常只记日志，永不杀死消费者**。

## 6. P3-D：主动取消的展示

改动位置：

- `frontend/src/pages.tsx`：`taskMessage()` 覆盖 `CANCELLING`（「取消已受理，正在等待执行中的步骤安全收尾。」）与 `CANCELLED`（「任务已按你的操作取消，已持久的结果保留。」）；新增 `isUserCancelled()`/`attentionPanelClass()`/`attentionTitle()`/`attentionDetail()` —— `CANCELLED` 或 `failure_reason=TASK_CANCELLED` 时使用 `attention-panel neutral`、标题「任务已取消」，且**不显示内部错误码**。
- `frontend/src/status.ts`：`CANCELLED` 徽标由 `danger` 改为 `neutral`（`FAILED`/`FAILED_VALIDATION` 仍为 `danger`）。

MCP 在真实 Chrome 中核对（任务 `0300f417-...`）：

```
badge        = "status-badge neutral"、文案「已取消」
页头文案      = 「任务已按你的操作取消，已持久的结果保留。」
关注面板      = 1 个，className = "attention-panel neutral"，标题「任务已取消」
内部错误码    = 页面正文不包含 TASK_CANCELLED / PROFILE_SCOPE_INCOMPLETE
「任务需要关注」= 不出现
```

## 7. 回归与检查

| 检查 | 命令 | 结果 |
|---|---|---|
| 静态检查 + 单元 + 前端 | `make check` | 通过（ruff / format-check / mypy strict / 单元 / 前端 tsc + vitest + build） |
| 单元测试 | `.venv/bin/pytest backend/tests/unit -q` | 184 passed |
| 契约测试 | `make test-contract` | 28 passed |
| 集成测试 | `XINGTU_TEST_DATABASE_URL=…xingtu_test_m3 make test-integration` | 72 passed / 1 skipped |
| 端到端 | `XINGTU_TEST_DATABASE_URL=…xingtu_test_m3 make test-e2e` | 9 passed |
| 前端 | `npm --prefix frontend run lint / test / build` | 通过（3 tests） |

其中 `backend/tests/integration/test_repository.py::test_network_mode_is_persisted_and_immutable` 的迁移版本断言由 `[1..8]` 更新为 `[1..9]` —— 这是配合新迁移 009 的**事实更新**，不是放宽断言（该用例仍逐版本穷举校验，任何迁移未被应用都会失败）。

## 8. 截图证据

| 文件 | 内容 |
|---|---|
| `FIX01-R1-new-task-before-submit.png` | 新建任务表单（关键词「宠物」、目标 1），提交前 |
| `FIX01-R2-task-completed.png` | 任务 `7620fb83` 终态「已完成」，无「需要关注」，计数 20/1/1/1/0 |
| `FIX01-R3-creator-snapshot.png` | 达人详情：8 模块全 `COLLECTED`、两组精选与封面 |
| `FIX01-R4-seeding-tab.png` | 优秀种草视频集合卡片与封面 |
| `FIX01-R5-cancelled-neutral.png` | 已取消任务：中性徽标与中性面板、无内部错误码 |

全部位于 [.runtime/mcp-artifacts/fix01-20261012/](../../.runtime/mcp-artifacts/fix01-20261012/)（gitignore，仅本机保留）。

## 9. 遗留风险与未完成项

1. **`fans` 瞬时拒绝的平台侧原因未确定**：本轮已证明契约与解析正确、并补齐请求级诊断，但没有拿到当次被拒绝响应的字节级证据（其已不在保留期内）。下一次同类事件会在失败证据里直接给出请求 key、HTTP 状态、content-type 类别、业务码与响应顶层 key，可直接判定是否为限流/权限/短时错误。
2. **瞬时拒绝目前仍会使任务收口为 `PARTIAL_COMPLETED`**（`PROFILE_SCOPE_INCOMPLETE`），需人工 retry。治理方向是依据第 1 点拿到的业务码，把平台自身的限流/重试码在契约里登记为 `PLATFORM_RATE_LIMITED`（走既有有界重试），而**不是**放宽完整度断言；本轮不做无证据的猜测登记。
3. **P1-B 真实派发时刻的现场写入**：本机最后一次真实派发（`02c81708` 的重试）由改动前启动的采集 Worker 完成，因此开发库里 29 条 dispatch 的 `workflow_started_at` 仍为 NULL，这是**如实记录、未被伪造成已写入**。该写入路径由单元测试 4（假 client）+ 新增集成测试 `test_real_dispatch_records_the_start_moment_in_the_database`（真实 SQL + 真实库）双重覆盖；重新启动的采集 Worker 已带该修改。
4. **P3-E / P3-F**（`browser_wait_for` 长等待提前返回、API 停机窗口 Vite 代理 500）按本卡口径只做记录：长等待已改为分段/外部计时；UI 500 排查顺序已写入 `docs/development.md`。
