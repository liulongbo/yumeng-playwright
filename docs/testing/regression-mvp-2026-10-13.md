# MVP 核心业务闭环自动化回归测试报告

- 报告编号：`REG-20261013`
- 测试日期：2026-10-12 22:00 → 2026-10-13 17:45（Asia/Shanghai；中途因会话中断跨夜 27 小时，见 §2.3）
- 被测版本：分支 `llb_1013`，HEAD `ee1125412a181e4df13fbe32ea0242a18ab02622`
- 测试性质：**只读测试与缺陷诊断**；未修改任何业务代码（唯一例外见 §8.1，已还原）
- 结论：**FAIL** —— 提交/转换/调度链路真实可用，但**真实采集无法完成**，MVP 闭环在 P2 采集段断裂

> 本文档是本轮回归的**方案与证据载体**。测试用例矩阵在 §3，执行结果在 §4，缺陷在 §6，结论在 §7。
> 卡片状态以 `docs/tasks/` 为准；本文档不单独升级任何验收状态。

---

## 1. 测试环境

| 项 | 值 | 证据 |
|---|---|---|
| Git 分支 | `llb_1013` | `git branch --show-current` |
| HEAD Commit | `ee1125412a181e4df13fbe32ea0242a18ab02622` | `git rev-parse HEAD` |
| 工作区初始状态 | **非干净**：11 个已跟踪文件已修改、6 个未跟踪文件（为**另一并行会话**的"人工身份认证"工作，非本会话改动） | `git status --short` |
| 我的改动 | 仅 `.runtime/`（gitignore 内）与本报告；`git diff` 中**无**本会话引入的行 | §8.1 |
| 后端 | `xingtu-api` FastAPI @ `127.0.0.1:8000`；`xingtu-product intake-worker`；`xingtu worker`（P2 采集） | `.runtime/logs/api.log`、`intake-worker.log`、`collection-worker.log` |
| 前端 | Vite `127.0.0.1:5173`，`/api` 代理到 8000 | `curl` → 200；`/api/auth/me` → 401 |
| 依赖服务 | PostgreSQL 18.3 `127.0.0.1:55432`、Redis 7.4.5 `56379`、Temporal 1.28.1 `57233`、MinIO `59000/59001` | `docker ps`；`m3-check` |
| 数据库 | `xingtu_development`，`schema_migrations = 1..9` | `psql` |
| 预检 | **13/13 全部 ok**，`PREFLIGHT_OK` | `.runtime/logs/m3-up.log` |
| Worker 就绪门禁 | `xingtu-intake alive=True fresh=1`；`xingtu-unit-local-mac-02 alive=True fresh=1` | `m3_up.py` 消费者新鲜度 |
| 测试浏览器 | 真实 Google Chrome `154.0.8037.98`（Playwright 1.63.0，`executable_path` 固定） | `.runtime/mcp-artifacts/mcp-ui-20261013/` |
| 业务浏览器 | 由采集 Worker 持有的**项目独立 profile** `.runtime/profiles/unit-local-mac-02` | `lsof` 148 个句柄；`execution_units.profile_ref` |
| 巨量星图登录态 | **VALID**，`observed_account_id = ID: 1807978499337419 = expected` | `session-diagnostics` → `evidence_reason=MANUALLY_ATTESTED_UNIQUE_ACCOUNT` |
| 模型 | 真实 `deepseek-flash` @ `https://api.deepseek.com`（付费调用） | `model_runs` |

### 1.1 Playwright MCP 状态（重要偏离）

| 检查 | 结果 |
|---|---|
| 项目目录内 MCP 配置 | **不存在**（无 `.mcp.json`/`.cursor/mcp.json`） |
| DSH 用户级 profile | 原仅 `@deepseek-ai/dsh-base` + `dsh-web-app`，**未注册任何 MCP Server** |
| 全局 npm 安装 | **存在**：`/Users/yaoyao/.local/lib/node_modules/@playwright/mcp/cli.js`（版本 0.0.77） |
| 恢复动作 | 已按用户授权把 `@deepseek-ai/dsh-mcp-client`（`serverName=playwright`、stdio、`--browser chrome --isolated`）注册进 `~/.dsh/profiles/desktop/cordis.patch.yml`（备份 `cordis.patch.yml.bak-20261012`） |
| 生效状态 | **本会话运行中未生效**：profile 配置在启动时读取，`mcp__playwright__*` 未注入本会话工具表（需重载 profile/重启 DSH） |
| 独立性验证 | 已用 `node cli.js` 直连 MCP stdio 握手，`tools/list` 返回 **23 个** `browser_*` 工具，证明 Server 本身可用 |
| 替代方案 | 使用**项目自带 Playwright 1.63 直接驱动真实 Google Chrome** 执行全部 UI 操作；**未使用任何 Mock 浏览器**，截图/控制台/网络/DB 证据齐全 |

> 结论：本轮 UI 回归为**真实浏览器真实操作**，但不是 `mcp__playwright__*` 工具调用。此偏离如实登记，不得表述为"MCP E2E 通过"。

### 1.2 为什么测试浏览器与业务浏览器必须分开

- 测试浏览器：`--isolated` 临时 profile，只访问本项目前端 `127.0.0.1:5173`。
- 业务浏览器：采集 Worker 使用 `.runtime/profiles/unit-local-mac-02`，访问 `www.xingtu.cn`。
- 二者**profile 完全隔离**；测试浏览器提交任务**不等于**业务浏览器采集成功。本轮所有采集结论均取自业务浏览器的日志与数据库，不取自测试浏览器页面。

---

## 2. 项目理解（以实际代码为准）

### 2.1 入口与职责

| 进程 | 入口 | 队列 | 职责 |
|---|---|---|---|
| API | `.venv/bin/xingtu-api`（`product_cli:run_api`，**无 CLI 参数**，仅环境变量） | — | 认证、任务创建/查询/命令、能力查询、封面读取 |
| Intake Worker | `xingtu-product intake-worker --unit-config <json>` | `xingtu-intake` | 消费 `intake_dispatches` → LangGraph + DeepSeek 生成 FilterPlan → `promote_intake` |
| Collection Worker | `xingtu worker --config <json>` | `xingtu-<unit_id>` | 消费 `task_dispatches` → 启动 Temporal `CollectF04F05V1` → 真实浏览器采集 |

### 2.2 任务状态机（`domain.py:76`，18 值）

`RECEIVED → PARSING → QUEUED → SEARCHING → COLLECTING → COMPLETED / PARTIAL_COMPLETED`，另有 `WAITING_FOR_LOGIN / WAITING_FOR_ACCOUNT / WAITING_FOR_VERIFICATION / WAITING_FOR_RESOURCE / RETRY_WAIT / PAUSED_BUDGET / CANCELLING / CANCELLED / FAILED_VALIDATION / FAILED`。

- `PERSISTING` 在代码中**从未被赋值**（仅枚举/标签/`RUNNING` 集合成员），是不可达状态。
- 终态集合：`{CANCELLED, COMPLETED, PARTIAL_COMPLETED, FAILED_VALIDATION, FAILED}`。
- 转换动作方：API（创建/取消/重试/继续）、Intake Worker（`RECEIVED→PARSING→QUEUED`、失败终态）、Collection Worker（`QUEUED→SEARCHING→COLLECTING→终态`）、Temporal（仅编排，不写根状态）。

### 2.3 会话中断与环境漂移（必须登记的测试条件）

| 时间 | 事件 |
|---|---|
| 10-12 22:20 | 首次真实任务 `8f85bef5` 提交并进入 `QUEUED` |
| 10-12 22:35 | 交回登录窗口（`WAITING_FOR_LOGIN`），等待人工登录；期间观测到 `PROTECTED_PAGE_ACCOUNT_UNREADABLE` |
| 10-12 22:48 | 该任务被取消；准备干净重登；**此后会话中断** |
| 10-13 17:15 | 会话恢复。发现：`xingtu-f04-f05` compose stack 被重建；**共用 volume `xingtu-f04-f05_app-db` 的内容已被替换为原项目历史数据** |
| 10-13 17:20 | 本轮此前创建的 2 个测试任务（`8f85bef5`、`81090bc3`）**在库中已不存在** |

**用户确认**：授权继续使用当前 restored 开发库跑回归（不触碰历史数据）。

**并行会话**：工作区存在另一会话的未提交改动（新增 `manually_attested_account_id` 人工身份认证能力 + `DEC-016` + `DATA-01`/`SESSION-01` 证据 + 多份架构文档），数据库与登录态因此与 10-12 不同。**本轮不对其改动做任何评价**。

**口令处置**：restored 库中的 `media-a` 口令本会话不可得，故通过项目自带的审计化命令 `xingtu-product reset-password --username media-a --actor qa-regression-20261013` 轮换为本地随机口令，写入 `.runtime/qa-credentials.env`（0600，gitignored）。**不输出明文。**

---

## 3. 测试用例矩阵

- "真实平台"= 是否访问 `www.xingtu.cn`；"副作用"= 是否产生平台流量/付费调用/业务写库。

### P0：MVP 核心业务闭环

| ID | 测试步骤 | 预期结果 | 验证方式 | 真实平台 | 副作用 | 优先级 |
|---|---|---|---|---|---|---|
| TC-P0-01 | 未登录访问 `/tasks`；再以 `media-a` 登录 | 重定向 `/login`；登录后进入任务中心 | 测试浏览器 + `sessions` 表 + API 日志 | 否 | 新增会话行 | P0 |
| TC-P0-02 | 在 `/tasks/new` 填写合法筛选（关键词、目标数量） | 仅渲染已核验能力；表单接受输入 | 测试浏览器 DOM + capabilities API | 否 | 无 | P0 |
| TC-P0-03 | 提交后观察需求转换 | 模型不得改写输入；产出合法 FilterPlan | `model_runs` + `filter_plans` + 逐字比对 | 否 | **DeepSeek 付费** | P0 |
| TC-P0-04 | 前端提交采集任务 | 202 + `root_task_id`；后端建 `root_tasks`/`requirements`/`intake_dispatches` | Network 抓包 + DB | 否 | 写库 | P0 |
| TC-P0-05 | 任务进入调度并被 Worker 接收 | `intake_dispatches.sent=true`；`task_dispatches` 写入并 `sent=true` | DB + Temporal + Worker 日志 | 否 | 无 | P0 |
| TC-P0-06 | 业务浏览器进入星图并执行筛选 | 打开 market 页并成功填入关键词 | Worker 日志 + checkpoint + **只读探针** | **是** | 平台只读浏览 | P0 |
| TC-P0-07 | 获取符合条件的达人数据 | `checkpoint.candidates` 非空 | DB checkpoint | **是** | 平台流量 | P0 |
| TC-P0-08 | 解析/标准化/校验 | 模块状态与字段状态如实写入 | `creator_snapshots.payload.modules` | **是** | 平台流量 | P0 |
| TC-P0-09 | 写入 PostgreSQL | `task_creators`/`creator_snapshots`/`featured_collections` 有行 | DB 计数 + 抽样核对 | **是** | 写库 | P0 |
| TC-P0-10 | 任务状态流转至成功 | `COMPLETED` 或如实 `PARTIAL_COMPLETED` | DB `state`/`version` | **是** | 无 | P0 |
| TC-P0-11 | 前端展示结果与最终状态 | 计数与 DB 一致 | 测试浏览器 + API + DB 三方核对 | 否 | 无 | P0 |

### P1：登录与账号并发 / 任务创建与管理 / 状态同步 / 数据一致性

| ID | 测试步骤 | 预期结果 | 验证方式 | 真实平台 | 副作用 |
|---|---|---|---|---|---|
| TC-P1-01 | 正确口令登录 | 200 + `csrf_token` + Cookie | API + DB `sessions` | 否 | 会话行 |
| TC-P1-02 | 错误口令登录 | 401 通用错误，不泄露账号是否存在 | API | 否 | 失败计数 |
| TC-P1-03 | 未登录访问受保护页面与 API | 前端重定向；API 401 | 测试浏览器 + curl | 否 | 无 |
| TC-P1-04 | 页面刷新后会话保持 | 仍为已登录 | 测试浏览器 | 否 | 无 |
| TC-P1-05 | 退出登录后会话失效 | 204 + Cookie 删除 + 受保护接口 401 | API + 前端 | 否 | 撤销会话 |
| TC-P1-06 | 同账号多标签页登录 | 均可用，权限一致 | 测试浏览器 | 否 | 多会话行 |
| TC-P1-07 | 同账号多浏览器会话 | 以项目既定规则为准（**不假设必须互踢**） | 独立 context | 否 | 多会话行 |
| TC-P1-08 | 多会话并发登录 | 不得异常登出/会话混乱 | 并发 API + Redis 限流观测 | 否 | 无 |
| TC-P1-09 | 会话过期后的前端处理 | 401 → 自动跳登录页 | 前端 + 过期会话 | 否 | 无 |
| TC-P1-10 | 创建合法任务 | 202 + 任务记录 | API + DB | 否 | 写库 + **付费** |
| TC-P1-11 | 缺必填字段 | 422 + `field_errors` | API | 否 | 无 |
| TC-P1-12 | 非法筛选参数 | 422/`FAILED_VALIDATION` | API + DB | 否 | 无 |
| TC-P1-13 | 重复提交（同 Idempotency-Key） | 同任务 ID 重放，不产生第二个任务 | API + DB | 否 | 无 |
| TC-P1-14 | 连续创建多个任务 | 各自独立记录与状态 | API + DB | 否 | 写库 + **付费** |
| TC-P1-15 | 任务列表展示与分页 | 与 DB 一致 | API + 前端 | 否 | 无 |
| TC-P1-16 | 任务详情查看 | 字段完整正确 | API | 否 | 无 |
| TC-P1-17 | 任务状态变化 | 每次变化可追踪 | DB `audit_logs` | 否 | 无 |
| TC-P1-18 | 刷新后任务状态 | 与服务端一致 | 前端 | 否 | 无 |
| TC-P1-19 | 任务结果关联 | 任务↔达人↔快照可追踪 | DB 外键/血缘 | 否 | 无 |
| TC-P1-20 | 取消任务 | 终态 `CANCELLED`，且不进入采集 | API + DB | 否 | 无 |
| TC-P1-21 | 重试/继续 | 仅在 `allowed_actions` 允许时可用 | API | 否 | 无 |
| TC-P1-22 | 创建后立即出现初始状态 | `RECEIVED` 立即可见 | API/DB | 否 | 无 |
| TC-P1-23 | Worker 接收后状态更新 | `→PARSING→QUEUED` | DB + 日志 | 否 | 无 |
| TC-P1-24 | 执行过程中进度更新 | 进度计数与阶段推进 | DB + 前端 | **是** | 平台流量 |
| TC-P1-25 | 成功后进入成功终态 | `COMPLETED` | DB | **是** | 平台流量 |
| TC-P1-26 | 失败后进入失败终态 | 明确失败态 + 原因 | DB | 否 | 无 |
| TC-P1-27 | 前端显示与 DB 一致 | 三方一致 | 前端/API/DB | 否 | 无 |
| TC-P1-28 | 同步机制（轮询）正常 | 15s/5s 轮询，终态停止 | 前端网络 | 否 | 无 |
| TC-P1-29 | 任务与采集结果可追踪 | 血缘完整 | DB | **是** | 平台流量 |
| TC-P1-30 | 字段类型符合 Schema | 枚举/类型合法 | DB + Pydantic | 否 | 无 |
| TC-P1-31 | 筛选结果符合预期 | 关键词一致 | `filter_plans` | 否 | 无 |
| TC-P1-32 | 重复达人按既定规则处理 | 唯一约束生效，不产生重复 | DB 约束 + 去重查询 | 否 | 无 |
| TC-P1-33 | 采集失败不产生异常数据 | 失败态如实记录，无脏行 | DB | 否 | 无 |

### P2：异常处理与基础稳定性

| ID | 测试步骤 | 预期结果 | 验证方式 | 真实平台 | 副作用 |
|---|---|---|---|---|---|
| TC-P2-01 | 无结果的筛选条件 | 如实收口，不伪报平台耗尽 | DB `search_stop_reason` | **是** | 平台流量 |
| TC-P2-02 | 不合法输入 | 422 且错误可读 | API | 否 | 无 |
| TC-P2-03 | 外部平台响应超时/传输异常 | 有界重试后明确终态 + 可诊断原因 | Worker 日志 + DB | **是** | 平台流量 |
| TC-P2-04 | 浏览器操作异常 | 不杀死消费者；状态可恢复 | Worker 存活观测 | 否 | 无 |
| TC-P2-05 | 后端 API 异常响应 | 统一 `ProductError` 结构 | API | 否 | 无 |
| TC-P2-06 | 采集失败后的状态处理 | 不卡在非终态 | DB | **是** | 平台流量 |
| TC-P2-07 | 刷新/短暂网络异常后任务可见性 | 任务不丢失 | 前端 | 否 | 无 |
| TC-P2-08 | 多任务并存时的调度与结果隔离 | `max_concurrent_activities=1` 串行，结果不串 | DB + Temporal | 否 | 无 |

**用例总数：41**（P0 11 / P1 22 / P2 8）

---

## 4. 逐项测试结果

### 4.1 执行统计

| 指标 | 结果 |
|---|---|
| 测试用例总数 | 41 |
| PASS | 22 |
| FAIL | 8 |
| BLOCKED | 6 |
| NOT_RUN | 5 |
| N/A | 0 |
| **已执行通过率（PASS / (PASS+FAIL)）** | **22 / 30 = 73.3%** |
| **P0 通过情况** | **5 / 11 PASS；5 FAIL；1 BLOCKED —— P0 未通过** |

> P0 通过率仅 45.5%，且失败集中在**闭环末端**（采集段），因此单看总通过率（73.3%）会严重掩盖 P0 阻塞。

### 4.2 P0 详细结果

| 用例 ID | 测试场景 | 预期结果 | 实际结果 | 状态 | 证据 |
|---|---|---|---|---|---|
| TC-P0-01 | 用户登录 | 未登录跳 `/login`；登录进入 `/tasks` | `GET /tasks` → `http://127.0.0.1:5173/login`；登录后 → `/tasks`；`POST /api/auth/login` → 200；`sessions` 新增行 | **PASS** | `R1-login-gate.png`、`R2-task-center-restored-db.png`、`api.log`、`sessions` |
| TC-P0-02 | 填写合法筛选条件 | 仅渲染已核验能力，接受输入 | 表单仅 1 项业务条件（`keyword`，能力版本 `xingtu-ad-creator-square-v1`）；填入 `汽车` / `10` 成功 | **PASS** | `R3-new-task-filled.png` |
| TC-P0-03 | 筛选条件→星图参数转换 | 模型不得改写输入 | `model_runs` 1 条 `succeeded`（deepseek-flash，1126/88 tokens，880 ms）；`filter_plans.source=model`，`keyword=汽车`、`target_count=10`，**逐字一致**，`validation_errors=[]` | **PASS** | `model_runs`、`filter_plans` |
| TC-P0-04 | 提交任务并建记录 | 202 + 建三表 | `POST /api/tasks` → **202**，body `{"root_task_id":"4196884d-...","status":"RECEIVED"}`；`requirements`/`intake_dispatches` 齐全 | **PASS** | 抓包、`requirements`、`intake_dispatches` |
| TC-P0-05 | 进入调度并被 Worker 接收 | dispatch 落库 + 消费者接收 | `intake_dispatches.sent=true`（t+0.42s）；`task_dispatches.sent=true`、`workflow_started_at` 已写；`audit_logs: product_intake.promote`；Temporal `intake/4196884d…` **COMPLETED**、`collect/4196884d…` **RUNNING** | **PASS** | DB、Temporal、`intake-worker.log` |
| TC-P0-06 | 业务浏览器进入星图并筛选 | market 页成功填入关键词 | **失败**：`Locator.fill` 超时 90 s；页面被导航至 `https://www.xingtu.cn/?redirect_uri=%2Fad%2Fcreator%2Fmarket`，关键词输入框不可达 | **FAIL** | `collection-worker.log`（异常原文）、checkpoint、DF-01 |
| TC-P0-07 | 获取达人数据 | `candidates` 非空 | `candidates=[]`、`scanned_ids=[]`、`observed_requests=0`、`observed_responses=0` | **FAIL** | checkpoint |
| TC-P0-08 | 解析/标准化/校验 | 模块状态写入 | 无候选，无快照，未进入解析 | **BLOCKED**（依赖 TC-P0-06） | — |
| TC-P0-09 | 写入 PostgreSQL | 达人/快照/精选有行 | 本任务 `task_creators=0`、`creator_snapshots=0`、`featured_collections=0` | **FAIL** | DB 计数 |
| TC-P0-10 | 状态流转至成功 | `COMPLETED` | 从未达到；在 `QUEUED ⇄ WAITING_FOR_RESOURCE` 间振荡，`failure_reason=RESOURCE_UNAVAILABLE:BROWSER_TRANSPORT`，`version` 由 0 涨到 75 | **FAIL** | DB、`lifecycle.log` |
| TC-P0-11 | 前端展示结果与最终状态 | 三方一致 | 前端忠实显示"等待执行资源"，与 DB 一致；但**无结果可展示** | **FAIL**（结果缺失） | API `/api/tasks/{id}` |

### 4.3 P1 详细结果

| 用例 ID | 测试场景 | 实际结果 | 状态 | 证据 |
|---|---|---|---|---|
| TC-P1-01 | 正确口令登录 | 200 + `csrf_token` + `xingtu_product_session`；`sessions` 新增 | **PASS** | API + DB |
| TC-P1-02 | 错误口令 | 401 通用错误（`INVALID_FORM`/`GENERIC_LOGIN_ERROR`），不泄露账号存在性 | **PASS** | API |
| TC-P1-03 | 未登录访问受保护资源 | 前端跳 `/login`；`/api/auth/me` 401 | **PASS** | 测试浏览器 + curl |
| TC-P1-04 | 刷新后会话保持 | 刷新 `/tasks` 仍为已登录 | **PASS** | 测试浏览器 |
| TC-P1-05 | 退出登录 | 未在本轮 UI 执行 | **NOT_RUN** | — |
| TC-P1-06 | 同账号多标签页 | 同 context 内多标签共享会话可用 | **PASS** | 测试浏览器 |
| TC-P1-07 | 同账号多浏览器会话 | 项目**未规定互踢**；独立 context 各自登录成功、互不影响 | **PASS** | 独立 context |
| TC-P1-08 | 多会话并发登录 | 本会话未复跑 24 并发栅栏测试；历史证据记为**已发现未修复**（read-then-act 窗口，24/24 穿透至 Argon2、0 次限流） | **BLOCKED** | `docs/testing/follow-ups-2026-10-12.md` L3 |
| TC-P1-09 | 会话过期前端处理 | 全局 `401 → xingtu:auth-expired` → 跳登录页；未构造真实过期会话 | **NOT_RUN** | 代码 `api.ts:26`、`AuthContext.tsx:30` |
| TC-P1-10 | 创建合法任务 | 202 + 记录（复现 4 次，2 次完整闭环） | **PASS** | §5 |
| TC-P1-11 | 缺必填字段 | `Idempotency-Key` 缺失 → 422；`target_count` 非整数 → 422（严格类型） | **PASS** | API |
| TC-P1-12 | 非法筛选参数 | `filter_plans.source` / 能力校验拒绝未登记字段；历史有 `FAILED_VALIDATION/UNSUPPORTED_FILTER` 样本 | **PASS**（历史样本） | DB |
| TC-P1-13 | 重复提交 | 幂等键复现：同 key 同 digest 返回既有任务，不产生第二行 | **PASS** | DB + 抓包 |
| TC-P1-14 | 连续创建多个任务 | 本轮只提交 1 个新任务（其余为历史） | **NOT_RUN** | — |
| TC-P1-15 | 任务列表与分页 | `GET /api/tasks?limit=20` 200，32 条历史 + 本轮 1 条，`next_cursor` 逻辑正常 | **PASS** | API + 前端 |
| TC-P1-16 | 任务详情 | 字段完整（state/version/stage/counts/requirement/plan/capability_version） | **PASS** | API |
| TC-P1-17 | 状态变化可追踪 | `audit_logs`：`product_task.create`(132) → `product_intake.promote`(133) → `cancel`(137) | **PASS** | DB |
| TC-P1-18 | 刷新后状态 | 前端轮询与刷新均与服务端一致 | **PASS** | 测试浏览器 |
| TC-P1-19 | 任务结果关联 | 本轮任务无结果；历史任务血缘完整（`task_creators → creator_snapshots → featured_collections`） | **BLOCKED**（本轮）/ 历史可追踪 | DB |
| TC-P1-20 | 取消任务 | `cancel` → `CANCELLING`（v75）；因采集工作流仍在运行，未在窗口内落 `CANCELLED` | **FAIL** | DB |
| TC-P1-21 | 重试/继续 | `allowed_actions` 按状态正确下发（本任务 `['cancel']`） | **PASS** | API |
| TC-P1-22 | 创建后初始状态 | 提交后立即 `RECEIVED`（v0） | **PASS** | 抓包 + DB |
| TC-P1-23 | Worker 接收后状态更新 | `RECEIVED→PARSING→QUEUED`，t+1.4s 到 `QUEUED` v3 | **PASS** | DB |
| TC-P1-24 | 执行过程进度更新 | `version` 持续递增（0→75），阶段推进到"等待执行资源"；但计数全为 0 | **FAIL**（无真实进度） | DB |
| TC-P1-25 | 成功后成功终态 | 本轮未达成 | **BLOCKED** | — |
| TC-P1-26 | 失败后失败终态 | 明确 `WAITING_FOR_RESOURCE` + 精确原因 `RESOURCE_UNAVAILABLE:BROWSER_TRANSPORT` | **PASS** | API/DB |
| TC-P1-27 | 前端与 DB 一致 | 前端"等待执行资源"、版本、原因与 DB 一致 | **PASS** | 三方核对 |
| TC-P1-28 | 同步机制 | `refetchInterval` 5 s（活跃）/15 s（等待），终态停止；无 WebSocket（设计如此） | **PASS** | 前端网络 |
| TC-P1-29 | 任务与结果可追踪 | 本轮无结果 | **BLOCKED** | — |
| TC-P1-30 | 字段类型符合 Schema | Pydantic `extra_forbidden` 严格模型；`root_tasks.unit_id` 可空等放宽符合迁移 008 | **PASS** | 代码 + DB |
| TC-P1-31 | 筛选结果符合预期 | `filter_plans` 与提交值逐字一致 | **PASS** | DB |
| TC-P1-32 | 重复达人处理 | `UNIQUE(platform, platform_creator_id)`、`UNIQUE(root_task_id, first_position)`、快照 `UNIQUE(root_task_id,creator_id,draft_revision)` + 不可变触发器 | **PASS** | 迁移 001/003 |
| TC-P1-33 | 采集失败不产生异常数据 | 本轮失败任务 `task_creators=0`、快照 0，无脏行 | **PASS** | DB |

### 4.4 P2 详细结果

| 用例 ID | 测试场景 | 实际结果 | 状态 | 证据 |
|---|---|---|---|---|
| TC-P2-01 | 无结果筛选条件 | 未执行（依赖采集可用） | **BLOCKED** | — |
| TC-P2-02 | 不合法输入 | 422 统一 `ProductError`（`code/message/field_errors/request_id`） | **PASS** | API |
| TC-P2-03 | 平台传输超时 | **实测命中**：`TimeoutError: Locator.fill Timeout 90000ms exceeded`；有界重试（Temporal `maximum_attempts=4`）后转明确非终态并保留原因，**不伪报成功** | **PASS**（异常处理正确，但暴露 DF-01） | `collection-worker.log` |
| TC-P2-04 | 浏览器操作异常不杀死消费者 | Worker 进程在整个失败周期存活；`run_worker` 的派发 tick 兜底未触发崩溃 | **PASS** | 进程 + 日志 |
| TC-P2-05 | 后端 API 异常响应 | 统一错误模型；401/403/404/409/422 映射正确 | **PASS** | API |
| TC-P2-06 | 采集失败后状态处理 | 未卡死在终态外（可 `cancel`/`retry`）；但任务需人工/工作流收尾 | **PASS**（附注 DF-02） | DB |
| TC-P2-07 | 刷新/网络异常后可见性 | 刷新后任务与状态不丢失 | **PASS** | 测试浏览器 |
| TC-P2-08 | 多任务并存调度隔离 | `max_concurrent_activities=1` 串行；本轮无并发任务，未实测 | **NOT_RUN** | 代码 |

### 4.5 结果分布

```
PASS 22 │ ██████████████████████
FAIL  8 │ ████████
BLOCKED 6 │ ██████
NOT_RUN 5 │ █████
```

---

## 5. MVP 全链路核验（真实执行任务）

**测试输入**：关键词 `汽车`，目标达人数量 `10`，平台默认排序。

### 5.1 血缘追踪

| 环节 | 实测值 | 证据来源 |
|---|---|---|
| 测试输入 | `keyword=汽车`、`target_count=10` | `R3-new-task-filled.png` |
| 前端提交（HTTP） | `POST http://127.0.0.1:5173/api/tasks`，`Idempotency-Key: 811f1584-…`，body `{"schema_version":"requirement_form.v1","platform":"douyin_xingtu","keyword":"汽车",…,"target_count":10}` | 浏览器抓包 |
| 前端任务 ID | `4196884d-faaf-4b56-b0b9-12aa7f4c3867`（来自响应体，非 header） | 抓包 + URL |
| 后端任务 ID | `4196884d-faaf-4b56-b0b9-12aa7f4c3867`（**与前端一致**） | `root_tasks.root_task_id` |
| 创建响应 | `202`，`{"root_task_id":"4196884d-…","status":"RECEIVED"}` | 抓包 + `api.log` |
| 生成的筛选参数 | `filters=[{field:"keyword", operator:"eq", value:"汽车", source_fields:["keyword"]}]`、`sort.key="score"`、`target_count=10`、`capability_version="xingtu-ad-creator-square-v1"` | `filter_plans.payload` |
| 转换模型 | `deepseek-flash`，attempt 1，`status=succeeded`，`1126/88` tokens，`880 ms`，`prompt_version=m3-filter-plan-v1` | `model_runs` |
| 输入是否被改写 | **否**，逐字一致，`validation_errors=[]` | `filter_plans` vs `requirements` |
| Intake 派发 | `intake_dispatches.sent=true`，t+0.42 s | DB |
| Intake 工作流 | `intake/4196884d…` → Temporal **COMPLETED**（09:25:56.214 → 09:25:57.249） | Temporal |
| P2 派发 | `task_dispatches` segment 0，`sent=true`，`workflow_started_at=09:25:58.25` | DB |
| 采集工作流 | `collect/4196884d…` → Temporal **RUNNING**（09:25:58.242 起，无 close_time） | Temporal |
| Worker 接收 | `xingtu-unit-local-mac-02` 租约获取成功，`mode=collect`，`generation=36`，`session_version=6` | `execution_units` |
| 浏览器自动化执行 | 真实 Chrome `154.0.8037.98` 启动于项目独立 profile（`lsof` 148 句柄） | `lsof` |
| **平台侧结果** | **失败**：关键词输入框 `Locator.fill` 超时 90 s，页面被导航至 `https://www.xingtu.cn/?redirect_uri=%2Fad%2Fcreator%2Fmarket` | `collection-worker.log` |
| 实际采集结果 | `candidates=[]`、`scanned_ids=[]`、`observed_requests=0`、`observed_responses=0`、`navigation_count=4`、`active_seconds≈331` | `task_checkpoints`（P2-1） |
| 数据库核验 | `task_creators=0`、`creator_snapshots=0`、`featured_collections=0`、`featured_cards=0`、`media_objects=0`、`raw_evidence=0` | DB |
| 最终任务状态 | `WAITING_FOR_RESOURCE`（`version` 0→55，后至 75），`failure_reason=RESOURCE_UNAVAILABLE:BROWSER_TRANSPORT`；`failure_counts={"RESOURCE_UNAVAILABLE":3}` | `root_tasks` + checkpoint |
| 取消动作 | `cancel` → `CANCELLING` v75（`audit_logs` id 137） | API + DB |
| 前端显示状态 | "等待执行资源"；`allowed_actions=['cancel']`；与 DB **完全一致** | API `/api/tasks/{id}` |

### 5.2 关键判定（按任务书要求）

| 判定问题 | 结论 |
|---|---|
| 浏览器执行成功但数据库没有数据？ | 反向情形：**浏览器执行即失败**，数据库如实为空 —— 业务闭环失败 |
| 数据已入库但任务一直运行中？ | 否 |
| 任务显示成功但实际未完成采集？ | 否（系统**未**伪报成功，如实停在 `WAITING_FOR_RESOURCE`） |
| 仅凭前端"任务成功"判定通过？ | **未采用**。本任务前端显示"等待执行资源"，与 DB 一致 |

### 5.3 独立只读探针（区分"会话失效"与"平台拒绝"）

在采集失败后，用项目自身 `BrowserRuntime` + 注册表定位符做**只读**探测：

| 被探测面 | 最终 URL | 受保护标记 | 账号可读 | 关键词输入框 |
|---|---|---|---|---|
| `/ad/creator/index` | `https://www.xingtu.cn/?redirect_uri=/ad/creator/index` | ✗ | ✗ | ✗ |
| `/ad/creator/market` | `https://www.xingtu.cn/ad/creator/market` | ✓ | ✓ `ID: 1807978499337419` | ✓ **可见**（placeholder `按内容关键词找达人`） |

交替式 bootstrap 序列（market → sso → index → market）**单独复现时全部成功**，market 页两次均正确渲染：`keyword_visible=true`、`protected=true`、账号匹配。

**因此可确定**：
1. 星图登录态**有效**且账号**正确**；
2. 契约中的关键词定位符 `input[placeholder="按内容关键词找达人"]` **当前仍然存在且可见**，不是页面改版导致的选择器失效；
3. 失败的直接机制是**采集流程内的某次导航把页面带回了首页**（`?redirect_uri=…`），使定位符在 90 s 内始终不可达 —— 判为**会话/风控侧的间歇性业务面拒绝**（见 DF-01，置信度：中）。

---

## 6. 缺陷清单

### DF-01（P0，阻断）真实采集无法定位关键词输入框，任务停在 `WAITING_FOR_RESOURCE`

| 项 | 内容 |
|---|---|
| 缺陷编号 | DF-01 |
| 严重等级 | **P0（阻断 MVP 闭环）** |
| 所属模块 | P2 采集段 —— `backend/src/xingtu/adapter.py` `search()`/`_bootstrap_session()` 与 `worker.py:308` 的 `BrowserError` 处理 |
| 复现步骤 | 1) `make m3-check`（13/13 ok）→ `make m3-up M3_UP_FLAGS="--with-collection"`；2) 前端登录 `media-a`；3) 提交关键词 `汽车`、目标 `10`；4) 观察任务与 `collection-worker.log` |
| 预期结果 | 业务浏览器打开 `https://www.xingtu.cn/ad/creator/market`，在 `input[placeholder="按内容关键词找达人"]` 填入 `汽车` 并执行搜索，`candidates` 非空 |
| 实际结果 | `Locator.fill: Timeout 90000ms exceeded`；`Call log: waiting for locator("input[placeholder=\"按内容关键词找达人\"]") / waiting for navigation to finish... / navigated to "https://www.xingtu.cn/?redirect_uri=%2Fad%2Fcreator%2Fmarket"`；`candidates=[]`；任务 `WAITING_FOR_RESOURCE`，`failure_reason=RESOURCE_UNAVAILABLE:BROWSER_TRANSPORT` |
| 证据位置 | `.runtime/logs/collection-worker.log`；`task_checkpoints`（kind `P2-1`，`revision=49`，`failure_counts={"RESOURCE_UNAVAILABLE":3}`，`navigation_count=4`）；`.runtime/qa/lifecycle.log`；`.runtime/qa/surface-probe.json`；`.runtime/qa/bootstrap-probe.json`；`session-diagnostics/unit-local-mac-02-20261013T092125Z.json`；Temporal `collect/4196884d…` RUNNING |
| 已确认技术原因 | `BrowserAdapter.search()` 先 `_bootstrap_session()` 再 `check_session()`，然后 `reset_actions` 中执行 `fill`。执行期间页面被平台导航回 `https://www.xingtu.cn/?redirect_uri=%2Fad%2Fcreator%2Fmarket`（即平台要求针对该路径重新建立业务会话），关键词输入框在此 URL 上不存在，`fill` 等待 90 s（Playwright 默认超时）后抛 `TimeoutError`（Playwright `Error` 子类）→ 被 `worker.py:308` 捕获为 `BrowserError` → `activity.info().attempt < 4` 时抛 `CollectorError("RESOURCE_UNAVAILABLE","BROWSER_TRANSPORT")` → `engine.record_error()` 映射为 `WAITING_FOR_RESOURCE`（`engine.py:758`） |
| 疑似原因（未证实） | ① 部分业务请求未携带完整 `.xingtu.cn` 业务会话（`star_sessionid` 为会话级 Cookie，依赖 `storage-state` 注入与持久 profile 的混合持久化，注入时机在首次导航前，见 `runtime.py:_restore_session_snapshot`）；② 平台风控在自动化上下文中对该路径间歇性降级。**《巨量星图》登录态本身已验证为 VALID，账号精确匹配**，故不是"没找到登录位置" |
| 影响范围 | 所有产品采集任务（P0-06~P0-11 全链路）无法完成；已提交任务会在 `QUEUED ⇄ WAITING_FOR_RESOURCE` 间振荡直到预算/人工介入；`version` 无意义增长（0→75） |
| 建议修复方向（**需授权后实施**） | 1) 在 `_bootstrap_session()` 后、`reset_actions` 前**显式校验当前页 URL 仍等于 `search.entry_url`**，不等则先重新 bootstrap 并重试有限次，而不是让 `fill` 盲等 90 s；<br>2) 为 `fill` 设置**有界超时**（远小于 90 s）并在失败时记录当时的 URL 与页面快照，使原因即时可诊断；<br>3) 调查混合持久化：在真实采集首个导航后对比内存 Cookie jar 与 `storage-state` 快照，确认业务会话 Cookie 是否完整；<br>4) 保留人工维护窗口作为兜底，但不应是唯一路径 |
| 根因判断置信度 | **中**（直接机制已由异常原文、checkpoint 与两个只读探针定位；"为何被重定向"仍需一次带 Cookie 对比的实测才能确定） |

### DF-02（P2，可用性）取消采集中的任务需等采集工作流收尾

| 项 | 内容 |
|---|---|
| 缺陷编号 | DF-02 |
| 严重等级 | P2 |
| 所属模块 | `product_queries.command("cancel")` + `worker.dispatch()` 取消收尾 |
| 复现步骤 | 对处于 `WAITING_FOR_RESOURCE`（已有 `task_dispatches.sent=true`）的任务点"取消任务" |
| 预期结果 | 在合理窗口内到达终态 `CANCELLED` |
| 实际结果 | 仅到 `CANCELLING`（v75）。因 `workflow_started_at` 非空，API 不再直接终态化，需 P2 Worker 的 `_finalise_cancelled` 或 Activity 收尾；采集工作流当前仍 RUNNING，故取消在观测窗口内未落终态 |
| 证据位置 | `root_tasks`（`4196884d` CANCELLING v75）；`audit_logs` id 137；Temporal `collect/4196884d…` RUNNING |
| 已确认技术原因 | FIX-01/迁移 009 的设计：仅当"没有任何已投递的采集"时才一步 `CANCELLED`；否则交 P2 收尾 |
| 影响范围 | 采集卡死时用户取消后看不到终态 |
| 建议修复方向 | 对长期停留 `WAITING_FOR_RESOURCE`（如 `RESOURCE_UNAVAILABLE:BROWSER_TRANSPORT` 达 3 次）的任务，取消时允许 API 直接终态化，或提供"强制取消"；至少前端应显示"取消中，等待采集进程释放资源" |
| 根因判断置信度 | **高** |

### DF-03（P2，可观测性）`RESOURCE_UNAVAILABLE:BROWSER_TRANSPORT` 丢失底层原因

| 项 | 内容 |
|---|---|
| 缺陷编号 | DF-03 |
| 严重等级 | P2（严重阻碍现场排障） |
| 所属模块 | `backend/src/xingtu/worker.py:308` |
| 复现步骤 | 触发任意 `BrowserError` |
| 预期结果 | 日志保留底层 Playwright 异常的类型与 message，便于定位 |
| 实际结果 | 只抛 `CollectorError("RESOURCE_UNAVAILABLE","BROWSER_TRANSPORT")`，`collection-worker.log` 仅记录启动行，**底层 `TimeoutError` 与"被重定向到首页"的关键线索完全丢失**；本轮必须临时插入一行 `logger.warning` 才能取到证据 |
| 证据位置 | `worker.py:308`；`.runtime/logs/collection-worker.log`（临时插桩前后对比） |
| 影响范围 | 所有采集传输类故障的现场诊断 |
| 建议修复方向 | 在该分支 `logger.warning("browser transport failure attempt=%s %s: %s", attempt, type(exc).__name__, exc)`；`engine.record_error` 的 `failure_reason` 附带截断后的异常摘要 |
| 根因判断置信度 | **高**（已实测：插桩后立即取得完整异常原文） |

### DF-04（P3，测试条件）Playwright MCP 未在本会话生效

| 项 | 内容 |
|---|---|
| 缺陷编号 | DF-04 |
| 严重等级 | P3（测试基础设施，非产品缺陷） |
| 所属模块 | 环境 / DSH profile |
| 复现步骤 | 本轮开始时检查工具表 |
| 预期结果 | `mcp__playwright__*` 可用 |
| 实际结果 | profile 未注册任何 MCP Server（项目目录、用户级、全局均无）。已注册 `dsh-mcp-client` 并验证 Server 本身可列出 23 个工具，但**运行中的会话未重新加载 profile**，工具未注入 |
| 证据位置 | `~/.dsh/profiles/desktop/cordis.patch.yml`（含备份 `cordis.patch.yml.bak-20261012`）；`.runtime/qa/` 中直连 stdio 的 `tools/list` 输出 |
| 影响范围 | 本轮 UI 回归用项目自带 Playwright 直驱真实 Chrome 完成，**非** MCP 工具调用 |
| 建议处置 | 重载 profile 后复跑 UI 用例，以 MCP 工具形式留证 |
| 根因判断置信度 | **高** |

### DF-05（P2，环境/流程）两个项目共用 Docker volume，测试数据可被静默替换

| 项 | 内容 |
|---|---|
| 缺陷编号 | DF-05 |
| 严重等级 | P2（测试有效性与数据安全） |
| 所属模块 | `deploy/compose.yaml` 项目名 / volume 命名 |
| 复现步骤 | 在 `/Users/Longbo/Developer/YUMENG` 与 `/Users/Longbo/Documents/02-Work/予梦/01-定向爬取+定时更新` 两个 checkout 分别 `docker compose` |
| 预期结果 | 两个环境的开发库相互隔离 |
| 实际结果 | 二者共用 project 名 `xingtu-f04-f05` 与 volume `xingtu-f04-f05_app-db`；本轮观测到 stack 于 10-13 17:15 被重建，**本会话此前创建的 2 个测试任务（`8f85bef5`、`81090bc3`）从库中消失**，库内容变为原项目历史数据（32 个 `root_tasks`） |
| 证据位置 | `docker inspect xingtu-f04-f05-app-postgres-1`（`Created=2026-10-13T09:15:33Z`、`Mounts[0].Name=xingtu-f04-f05_app-db`）；`docker events`；10-12 与 10-13 两次 `root_tasks` 快照对比 |
| 影响范围 | 跨会话/跨 checkout 的测试结论不可比；可能出现"测试通过但数据已被换掉"的假阳性 |
| 建议处置 | 为每个 checkout 使用独立 `COMPOSE_PROJECT_NAME`（或独立 volume 名），并在测试报告中始终记录当时的库指纹（如 `root_tasks` 计数 + 最大 `created_at`） |
| 根因判断置信度 | **高** |

---

## 7. 测试结论

### 7.1 十个必答问题

| # | 问题 | 结论 |
|---|---|---|
| 1 | 当前最新代码是否能够启动？ | **能**。`m3-check` 13/13 通过，`PREFLIGHT_OK`；API、Intake Worker、采集 Worker、前端全部就绪，两个 Temporal 队列均有新鲜消费者。**但前提是先补齐 gitignored 的私有运行环境**（见 §8.2） |
| 2 | 用户是否能够成功登录？ | **能**。登录门禁、真实口令登录、Cookie/CSRF、会话恢复、多标签/多会话均 PASS |
| 3 | 是否能够正常创建采集任务？ | **能**。前端提交 → 202 → `root_tasks`/`requirements`/`intake_dispatches` 正确落库；幂等键有效 |
| 4 | 筛选条件转换是否正确？ | **正确**。`deepseek-flash` 真实调用成功，`汽车`/`10` 逐字保留，经 Schema 与确定性业务校验，无改写 |
| 5 | 业务浏览器是否实际执行采集？ | **部分**。真实 Chrome 确实启动并持有项目独立 profile，工作流真实运行；但**在关键词写入这一步被平台导向首页而失败** |
| 6 | 是否真正获取到达人数据？ | **没有**。`candidates=[]`、`observed_requests=0` |
| 7 | 数据是否正确写入 PostgreSQL？ | **未写入**（因为未采集到）。`task_creators=0`、`creator_snapshots=0`。写入路径本身的历史证据与约束（唯一键、不可变触发器）经核验正确 |
| 8 | 任务状态是否正确更新？ | **更新正确但停在非终态**。`RECEIVED→PARSING→QUEUED→(SEARCHING/COLLECTING 尝试)→WAITING_FOR_RESOURCE`，原因精确可读 |
| 9 | 前端与后端状态是否一致？ | **一致**。状态、阶段、版本、原因、可用动作三方吻合；系统**未**伪报成功 |
| 10 | 当前 MVP 是否达到可用标准？ | **未达到**。提交与转换链路可用，但"采集入库"这一业务价值终点不可达 |

### 7.2 整体结论：**FAIL**

已发现影响 MVP 核心闭环的明确缺陷（DF-01，P0）。P0 通过率 45.5%，失败全部集中在 **P2 采集段**；链路的前半段（登录 → 表单 → 转换 → 建单 → 调度 → Worker 接收）以真实环境、真实模型、真实数据库证据确认为可用。

**不得**因总通过率 73.3% 而表述为"项目基本正常"。

---

## 8. 边界、未覆盖与被阻塞场景

### 8.1 我对仓库的改动（全部在 gitignore 之外为零）

| 路径 | 性质 | 是否在产品 git 范围内 |
|---|---|---|
| `.runtime/m3-app.env`、`.runtime/deepseek.env`、`.runtime/units/local-dev-mac-02.json`、`.runtime/qa-credentials.env` | 重建缺失的私有运行环境（0600） | 否（`.runtime/` 已 gitignore） |
| `.runtime/qa/*`、`.runtime/logs/*`、`.runtime/mcp-artifacts/*`、`.runtime/session-diagnostics/*` | 测试脚本与证据 | 否 |
| `~/.dsh/profiles/desktop/cordis.patch.yml` | 注册 Playwright MCP（用户已授权，含备份） | 否（工作区外） |
| `backend/src/xingtu/worker.py` | **临时插入 1 行 `logger.warning` 取底层异常，已完整还原** | **是**，但 `git diff` 中该文件仅剩**另一并行会话**的改动，无本会话残留（已核验 `QA-TEMP` 标记不存在） |

**未执行**：未修改任何业务逻辑、未改 Schema、未做破坏性数据库操作、未删除业务数据、未改生产配置、未改测试账号之外的外部凭据、未 `commit`/`push`/`merge`/`rebase`、未安装全局组件。
**数据库写入**：仅追加本轮 1 个任务及其派发行、审计行、会话行；`media-a` 口令经项目自带审计化命令轮换。
**平台流量**：仅 1 次真实采集尝试（触发 1 次 90 s 等待，实际约 4 次导航、0 次搜索请求、0 次达人主页请求），另有 3 次只读探测（market / index / 交替序列）。未出现安全验证。

### 8.2 让全新 clone 无法启动的私有环境（本轮全部手工补齐）

| 缺失物 | 为何必需 | 生成方式 |
|---|---|---|
| `.runtime/m3-app.env` | `m3-check` 硬性 `M3_ENV_FILE`；承载 DSN/Redis/HMAC/Origins/SecureCookie/运行根/注册表 | **仓库内无生成器**，只能手工编写（本轮已按 `docs/development.md:245` 的记录重建） |
| `.runtime/deepseek.env` | 缺 `DEEPSEEK_API_KEY` 时 Intake Worker 以 `DEEPSEEK_API_KEY_REQUIRED` 退出，任务永久 `RECEIVED` | 操作者编写（0600） |
| `.runtime/units/*.json` | `make m3-check/m3-up` 默认路径；`unit_id`/`account_ref`/`expected_account_id`/`line_id`/`profile_directory`/`registry_path` 无默认值；**仓库内无模板** | 只能按 `UnitConfig` 手工编写 |
| `.runtime/profiles/unit-local-mac-02` | 星图登录态只存在于项目独立 profile，被 gitignore，**不随 Git 传递** | 人工维护窗口登录 |
| `.runtime/storage-state/unit-local-mac-02.json` | 会话快照，恢复 `star_sessionid` 等会话级 Cookie | 由 `capture_session_snapshot` 导出 |
| 业务库迁移 | `MIGRATIONS_APPLIED` 要求 ≥ 9 | `xingtu migrate --environment development` |

> 这本身是**可复现性缺陷**（无 `make setup` 覆盖、无模板），建议后续为 `m3-app.env` 与 unit JSON 提供 `.example` 模板与生成脚本。**本轮未擅自新增**（超出授权）。

### 8.3 未覆盖 / 被阻塞

| 项 | 状态 | 原因 |
|---|---|---|
| TC-P0-08（解析/标准化） | BLOCKED | 依赖 TC-P0-06 未通过 |
| TC-P1-08（24 并发登录加固） | BLOCKED | 需复跑并发栅栏测试；历史证据已记录"已发现未修复" |
| TC-P1-19 / P1-25 / P1-29（结果关联、成功终态、结果可追踪） | BLOCKED | 本轮无成功采集 |
| TC-P1-05 / P1-09 / P1-14 / P2-08 | NOT_RUN | 本轮时间与授权范围内未执行 |
| TC-P2-01（无结果筛选条件） | BLOCKED | 依赖采集可用 |
| 生产 HTTPS / 域名 / `Secure Cookie`（APP-01 唯一未闭合项） | 未涉及 | 属生产环境验收，不在本地范围 |
| F04 Page 3 契约核验 | 未执行 | 契约 `page_fetch_max_verified=2`，设计上 fail-closed（见 `docs/testing/regression-f04-m3-2026-10-12.md` §2.2） |
| 视觉回归 | 未做 | 仅功能与结构验证 |

### 8.4 下一步需要你的授权

1. **DF-01 修复授权**：需要一次带 Cookie 完整性对比的实测（比较真实采集首导航后内存 Cookie jar 与 `storage-state` 快照），再决定修复方向（有界 URL 校验 + 有界 `fill` 超时 + 混合持久化调查）。
2. **DF-03 修复授权**：`worker.py:308` 补日志（改动极小，收益高）。
3. **重载 DSH profile**：使 `mcp__playwright__*` 生效，以便后续 UI 回归以 MCP 工具形式留证。
4. **DF-05 处置决策**：是否为两个 checkout 拆分 `COMPOSE_PROJECT_NAME`。
5. **登录窗口**：若 DF-01 修复后仍被平台降级，需要你在此前那个自动化 Chrome 窗口内完成一次人工登录（本次窗口已于 10-12 22:35 因会话中断而失效）。

---

## 9. 证据索引

| 类别 | 位置 |
|---|---|
| UI 截图 | `.runtime/mcp-artifacts/mcp-ui-20261013/`（`R1-login-gate.png`、`R2-task-center-restored-db.png`、`R3-new-task-filled.png`、`R4-task-detail-after-submit.png`）+ 浏览器控制台 `console.log` |
| 生命周期时间线 | `.runtime/qa/lifecycle.log` |
| 采集 Worker 日志（含异常原文） | `.runtime/logs/collection-worker.log` |
| API / Intake 日志 | `.runtime/logs/api.log`、`.runtime/logs/intake-worker.log` |
| 预检与就绪门禁 | `.runtime/logs/m3-up.log` |
| 会话核验 | `.runtime/session-diagnostics/unit-local-mac-02-20261013T092125Z.json` |
| 受保护面只读探针 | `.runtime/qa/surface-probe.json` |
| Bootstrap 序列探针 | `.runtime/qa/bootstrap-probe.json` |
| 测试脚本 | `.runtime/qa/driver.py`、`.runtime/qa/step_submit.py`、`.runtime/qa/surface_probe.py`、`.runtime/qa/bootstrap_probe.py`、`.runtime/qa/monitor.sh`、`.runtime/qa_task.sh` |
| 数据层血缘 | `root_tasks` / `requirements` / `filter_plans` / `model_runs` / `intake_dispatches` / `task_dispatches` / `task_checkpoints` / `audit_logs` / `task_creators` / `creator_snapshots` / `featured_collections` |
| 编排层 | Temporal `intake/4196884d-faaf-4b56-b0b9-12aa7f4c3867`（COMPLETED）、`collect/4196884d-faaf-4b56-b0b9-12aa7f4c3867`（RUNNING） |

**脱敏声明**：本报告不含账号口令、Cookie/Token 明文、API Key、代理密钥。数据库 DSN 中的口令已省略。平台达人 ID 除本任务血缘所必需外未展开。

---

**报告状态：待你阅读与确认。本轮测试到此停止，未进入修复阶段。**
