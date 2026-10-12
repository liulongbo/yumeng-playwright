# M3 前端任务停留 RECEIVED：根因定位与最小修复证据（2026-10-11）

> 范围：诊断 → 受控复现 → 最小修复 → 分层回归。环境为本机 localhost 开发环境（真实开发库、真实 DeepSeek、真实 Temporal、真实 Chromium 前端）。
> 边界：本轮**未**运行 P2 采集 Worker，**未**访问巨量星图，**未**改动既有生产采集实现（`adapter.py`/`engine.py`/`browser_host.py`/`challenge.py`/`covers.py` 未改）；**未**新增迁移。
> 凭据：模型密钥只写入被 gitignore 的 `.runtime/deepseek.env`（`0600`），未进入仓库、卡片、日志或本文。

## 1. 故障现象与真实样本

| 项 | 值 |
|---|---|
| 根任务 | `3c96c78a-77f8-4e11-8081-953b12deae91` |
| 提交方 | `media-a`（真实 UI 提交） |
| 原始需求 | 关键词「户外」，目标 4，能力版本 `xingtu-ad-creator-square-v1` |
| 创建 | 2026-10-11 02:12:05Z（10:12:05+08） |
| 症状 | 持续 `RECEIVED`（version 0）**7 小时 8 分**，直到用户手动取消 |
| `intake_dispatches.sent` | **false**，且 `updated_at == created_at`（此后未被任何进程触碰） |
| `model_runs` / `filter_plans` | **0 / 0** |
| Temporal `intake/*` | 全库仅 1 条历史工作流（属于另一任务） |
| Temporal 队列 `xingtu-intake` | pollers = 0 |

**判定**：任务从未进入 P1 转换环节；前端提交与服务端受理（`product_task.create` 审计存在、单事务落库完整）均正常。属于「任务真正没有开始 + 投递意图无消费者」。

## 2. 根因（两个独立条件）

| # | 根因 | 性质 | 证据 |
|---|---|---|---|
| ① | 产品入口独有的 P1 **Intake Worker 没有运行**，`dispatch_intakes()` 从未执行 | 直接原因 | `sent=false` 持续 7h8m；正常派发循环 ≤2 s 即翻转（实测量级 0.13 s）；隔离 A/B 复现见 §4 |
| ② | **缺少模型凭据** `DEEPSEEK_API_KEY`，使该 Worker 无法启动 | 硬门槛（① 的启动前置） | 四处凭据位置（当前 shell、`.runtime/m3-app.env`、`.runtime/development.env`、shell rc）全部缺失；真实命令 `xingtu-product intake-worker` 以 `RESOURCE_UNAVAILABLE: DEEPSEEK_API_KEY_REQUIRED` 退出（exit 1），发生在建立 Temporal 连接之前 |

两个条件相互独立：② 可在任意任务状态下验证；① 在模型可用的隔离实验（合成 Adapter）中仍完整复现。即使提供凭据，也没有任何编排/文档步骤会启动该进程（`make dev` 只起 Compose，原 §5 启动步骤只含 API 与前端）。

**伴随缺陷**：缺消费者时系统没有任何失败面 —— 没有 worker 心跳、没有队列就绪检查、状态查询只返回「需求已接收 / 等待转换工作流接管」，用户无法区分“正在转换”与“无人接管”。
**潜在缺陷**：`IntakeProcessor.process` 对 `promote_intake` 的非取消异常直接 `raise`，Activity 失败后 Workflow 失败（`maximum_attempts=1`），根任务会永久停在 `PARSING` 且没有 `failure_reason`。
**环境缺陷**：本机 `no_proxy` 含 `[::1]`，httpx 0.28.1 直接抛 `InvalidURL: Invalid port: ':1]'`，真实模型调用在任何请求发出前即失败（且不是 `httpx.TransportError`，不会被 `verify_model` 转成稳定错误码）。

## 3. 受控对照实验（修复前）

Temporal 官方测试服务器 + 真实 PostgreSQL 临时 schema + 真实 `run_intake_worker` + 合成 Adapter：

| 阶段 | 3 个任务的状态 |
|---|---|
| A：提交后无消费者 | 3/3 `RECEIVED` v0、`sent=false`、`model_runs=0`、`filter_plans=0`；等待 6 s 后**完全不变**；`pending_intake_dispatches()` 返回 3（行可见，不是丢失） |
| B：启动真实消费者 | +0.27 s 出现新鲜 poller（`last_access_age=0.1 s`）；**+0.56 s 全部 `QUEUED` v3**、`sent=true`、每任务 1 `model_run` + 1 `filter_plan` + 1 `task_dispatches` |

派发失败对照组（注入 `start_workflow` 异常）：异常从 `dispatch_intakes` 抛出并终止整个轮询循环，任务保持 `RECEIVED`/`sent=false`、**无任何错误记录** —— 与“没有消费者”指纹完全一致。这证明仅凭 `sent=false` 的时长无法区分二者，必须叠加派发失败记录。

## 4. 修复后的真实模型闭环（2026-10-11 实测）

真实 `DeepSeekAdapter` + 真实 `run_intake_worker` + 真实 Temporal Docker（`127.0.0.1:57233`）+ 真实队列 `xingtu-intake` + 隔离临时 schema（用后即 DROP）：

| 观测点 | 结果 |
|---|---|
| `verify_model()` | PASS；`GET /models` 返回 `deepseek-flash`、`deepseek-v4-pro` |
| A：提交后 4 s 无消费者 | `RECEIVED` v0、`sent=false`、`model_runs=0`、`filter_plans=0` |
| B：消费者出现 | +0.13 s 新鲜 poller（`freshest_age=0.0026 s`） |
| C：终态 | **+1.71 s → `QUEUED` v3**，`unit_id=unit-local-mac-02` |
| `model_runs` | 1 条：`provider=deepseek`、`requested/response_model=deepseek-flash`、`status=succeeded`、**1126 input / 88 output tokens、1262 ms** |
| `filter_plans` | 1 条：`source=model`，关键词「户外」未改写、目标 4、能力版本一致；**与 `build_expected_plan` 确定性期望完全相等** |
| `task_dispatches` | 1 条（`sent=false`，因未启用 P2 采集 Worker，符合预期） |
| `p1` 检查点 | `outcome=succeeded`、`attempt_count=1`、`final_error=[]` |

## 5. 关键机制修正：poller 新鲜度是粗粒度信号

连续采样一个**健康** Worker 的 poller 条目：

```
t+0s  age=18.3 → t+40s age=58.4 → t+45s age=3.4  (刷新)
     → t+100s age=58.4 → t+105s age=4.4 (刷新)
     → t+155s age=121.0 → t+160s age=0.5 (刷新)
```

结论：长轮询持有请求，`last_access_time` 的刷新间隔实测为 **58 s / 58 s / 121 s**；Worker 停止后条目仍会保留数分钟（实测 >2 分钟）。因此：

- `xingtu.worker_health.DEFAULT_FRESHNESS_SECONDS` 由初版 10 s 修正为 **180 s**（10 s 会把健康 Worker 判成离线）；
- 任务是否“无人接管”**不以 poller 为准**，而由精确的任务级信号判定：正常派发循环约 2 s 内即置 `sent=true`，故 `sent=false` 超过 **120 s** 且无派发失败记录即为结论（`INTAKE_BLOCK_AFTER_SECONDS`）；
- `consumer_alive` 仅作为诊断元数据（三态：`true`/`false`/`null`=无法观测）与 `GET /api/health/workers` 一并返回。

## 6. 最小修复清单

| 项 | 文件 | 内容 |
|---|---|---|
| P0-1 启动编排与就绪门禁 | `scripts/m3_up.py`（新增）、`Makefile`、`scripts/commands.py` | 只读前置自检（13 项，稳定代号）+ 进程启动 + **新鲜消费者**门禁 + 前台监督 + 日志落 `.runtime/logs/`；新增 `m3-check`/`m3-up`/`collection-worker` 目标；`api`/`intake-worker` 自动加载 `.runtime/m3-app.env` 与 `.runtime/deepseek.env`；SIGTERM 也会回收子进程 |
| P0-1b 代理环境缺陷 | `scripts/m3_up.py`、`docs/development.md` | 移除 `no_proxy` 中的方括号 IPv6 项（保留 `::1`），使真实模型调用可发出 |
| P0-2 派发循环异常隔离 | `intake_worker.py`、`product_repository.py` | `dispatch_intakes` 逐任务 try/except，失败时**保持 `sent=false` 以便下次重试**并记 `audit_logs`（`product_intake.dispatch_failed:<code>`，60 s 节流）；轮询循环整体兜底；失败不再杀死消费者 |
| P0-3 三态可见性 | `worker_health.py`（新增）、`product_models.py`、`product_queries.py`、`product_api.py`、`frontend/src/{types.ts,pages.tsx,styles.css}` | `TaskDetail.intake`（`sent`/`pending_seconds`/`consumer_alive`/`dispatch_error`/`blocked_reason`）；`INTAKE_WORKER_UNAVAILABLE` 与 `INTAKE_DISPATCH_FAILING` 两态；前端阻塞面板与文案修正；后台线程健康缓存，请求路径不直连 Temporal；新增 `GET /api/health/workers` |
| P0-4 回归门禁 | `tests/e2e/test_intake_worker_loop.py`（新增）、`backend/tests/unit/test_worker_health.py`（新增）、`backend/tests/unit/test_intake_worker_dispatch.py`（新增）、`backend/tests/integration/test_product_m3.py`（新增 2 例） | 无消费者→卡住、消费者出现→排空的端到端回归；派发失败隔离；新鲜度分档；`intake` 字段与 API 序列化 |
| P1-1 失败终态 | `intake_worker.py` | `promote_intake` 非取消异常 → `fail_intake(FAILED, field_errors)`，不再永久 `PARSING` |
| P2 文档 | `docs/development.md` | 新启动契约、检查项表、`intake` 字段语义、poller 粗粒度说明、凭据与 `no_proxy` 说明；历史启动步骤标注为已致因记录 |

## 7. 分层回归结果（2026-10-11）

| 套件 | 结果 |
|---|---|
| `make check`（ruff / format-check / mypy strict / 单元 / 前端 tsc+vitest / 前端构建） | **exit 0**；单元 **178 passed**；`Success: no issues found in 29 source files`；前端 3 passed + 构建成功 |
| `make test-integration` | **69 passed, 1 skipped** |
| `make test-contract` | **28 passed** |
| `make test-e2e` | **9 passed**（含本轮新增 2 例） |
| `make m3-check` | **13/13 ok**（含 `MODEL_AVAILABLE deepseek-flash`） |
| 真实运行环境 | `make m3-up` 前置自检全通过 → 启动 API + Intake Worker → 就绪门禁 `xingtu-intake alive=True freshest_age=29.5s` → READY |

## 8. 隔离与工作区保护

- 开发库前后一致：`root_tasks=18`、`model_runs=2`、`filter_plans=13`（验证均在 `xingtu_test_m3` 的临时 schema 内进行，结束即 `DROP SCHEMA ... CASCADE`；无 `verify_*`/`test_*` 残留 schema）。
- 共享开发 Temporal 中新增 5 条 `intake/*` 工作流执行（验证用，全部 `COMPLETED`，随 ~24 h 保留期自动清除）。
- 验证脚本位于被 gitignore 的 `.runtime/`，不属于项目代码；分支 `10.9` 未提交、未推送、未清理。
- 密钥仅存于 `.runtime/deepseek.env`（`0600`、gitignore）。**建议**：该密钥已在会话中明文出现，验收后应轮换。

## 9. 未完成项

1. **真实用户在 UI 点击提交的现场确认**：API 与 Intake Worker 已在本地运行（`make m3-up`），但本轮未取得 UI 登录口令，也未在本会话绑定 Playwright MCP，因此“真实用户在浏览器提交后离开 RECEIVED”这一步由操作者在页面完成并核对。
2. **P2 采集段（`QUEUED → 采集完成`）**：需显式采集授权后运行 `make collection-worker`，本轮未执行，也未访问巨量星图。
3. **Worker 心跳（精确存活性）**：当前用「任务级 120 s + poller 180 s」判定；若要秒级存活信号（例如「Worker 已死」在 10 s 内可见），需新增心跳表（迁移 009），列为后续可靠性增强。

## 10. Playwright MCP + 真实 Chrome 完整 UI 复跑（2026-10-11 23:08–23:12）

**方式**：真实 Playwright MCP 服务（`/Users/yaoyao/.local/bin/playwrightmcp`，Playwright `1.62.0-alpha-2026-06-29`，23 个工具）+ 真实 Chrome（`--browser chrome --isolated`）。每一次浏览器动作都是 MCP 的 `tools/call`。

**两点必须如实说明**：

1. 本会话的工具集中**没有**绑定 Playwright MCP 工具（`cordis_inspect_query(host/Tool, listTools)` 的完整列表已确认）。因此我用真实 MCP stdio 协议（JSON-RPC 2.0，`initialize` → `tools/list` → `tools/call`）驱动该 MCP 服务；这不是“普通 Playwright 脚本冒充 MCP”，但也**不是**由 harness 直接调用的 MCP 工具。若要让 harness 原生暴露这些工具，需在 profile 中注册该 MCP。
2. MCP 启动 Chrome 时需要在 `~/Library/Caches/ms-playwright/b/` 写一个约 1 KB 的浏览器注册标记（工作区之外），当前沙箱以 `EPERM` 拒绝；本轮为该命令申请了一次 `danger-full-access`。
3. 取消按钮使用 `window.confirm`，而 MCP 会自动关闭原生对话框，因此取消步骤先以一段记录型 `window.confirm` 覆盖（并读回应用真实询问的文案）再点击；点击、API 调用与状态流转都是真实应用路径。

### 10.1 阶段一：Worker 运行时（登录 → 发起 → 需求转换 → 排队）

| 步骤 | 结果 |
|---|---|
| 未登录直达 `/tasks` | 重定向 `/login`（截图 `up-00-login-gate.png`） |
| 登录 `media-a` | 200 → `/tasks`，任务列表 22 行（截图 `up-01-login-filled.png`、`up-02-task-center.png`） |
| 新建任务表单（提交前） | 关键词「户外」、目标 4（截图 `up-task-01-form-before-submit.png`） |
| 提交 | 落 `/tasks/121d9014-0e77-4c06-89ee-8508e300966e`（`POST /api/tasks` → 202） |
| **状态流转** | **t+1.61 s → `QUEUED` v3**；转换校验完成，进度轨道停在「排队」 |
| 页面提示 | 转换期间显示新增的 intake 面板「需求转换工作流正在派发」（`consumer_alive=true`） |
| 结果核对 | API：`status=QUEUED`、`keyword=户外`、`plan.target_count=4`、`allowed_actions=[cancel]`（截图 `up-task-03-settled.png`） |
| `GET /api/health/workers` | `xingtu-intake alive=true`、`fresh_pollers=1` |
| 任务中心 | 新任务出现在列表（截图 `up-09-task-center-final.png`） |
| 服务端日志 | `POST https://api.deepseek.com/responses "HTTP/1.1 200 OK"`（该 UI 提交触发了真实模型调用） |

### 10.2 阶段二：仅 API、无 Worker（复现原缺陷 → 新阻塞提示 → UI 取消）

| 步骤 | 结果 |
|---|---|
| 环境 | 停掉 `make m3-up`，只启动 API；进程检查确认 Intake Worker 不在运行 |
| 新建任务 | 关键词「母婴辅食」、目标 2 → `bfc5d299-1cb3-432a-9808-76c6a161f144` |
| **原缺陷复现** | **t+1.63 s 起保持 `RECEIVED` v0**，`intake.sent=false` |
| t+34.5 s | 仍 `RECEIVED`，`pending_seconds=34.5`；此时 `consumer_alive=true`（**残留 poller**，worker 实际已死）→ 说明**不能**用 poller 判活 |
| **t+120.5 s** | `intake.blocked_reason=INTAKE_WORKER_UNAVAILABLE`；页面出现红色阻塞面板：「需求转换工作流未运行 —— 任务不会被自动推进：没有检测到需求转换（Intake）Worker 的在线消费者，已等待 2 分 01 秒。请在运行环境启动需求转换工作流。」（截图 `down-task-04-blocked.png`） |
| **UI 取消** | 点击「取消任务」→ 应用真实询问「确认取消这个任务？已持久的结果会保留。」（文案已读回）→ **t+1.64 s → `CANCELLED` v1**，`failure_reason=TASK_CANCELLED`、`allowed_actions=[]` |
| 取消的正确性 | 该任务 `model_runs=0`、`filter_plans=0`：在 `RECEIVED` 阶段取消**从未调用模型**，fail-closed 成立 |
| t≈130 s | `consumer_alive` 仍为 `true`（`freshest_age=166.7 s`）：再次印证 poller 阈值 180 s 的粗粒度特性，任务级 120 s 规则才是可靠判据 |
| 任务中心 | 该任务显示「已取消」（截图 `down-09-task-center-final.png`） |
| 浏览器控制台 | 仅 2 条预期噪声：`favicon.ico` 404 与登录前的 `/api/auth/me` 401；**无 JavaScript 异常** |

### 10.3 本轮 MCP 复跑新发现：已 `QUEUED` 的任务取消后停在 `CANCELLING`

- 观察：你自己的任务 `488eb716-25ba-442b-8003-dbc82e3d73a2`（宠物/2，22:27 创建）与代码路径核对显示 —— 任务一旦晋级为 `QUEUED`，`product_queries.command("cancel")` 只把它置为 `CANCELLING`；真正落到 `CANCELLED` 依赖 P2 `worker.dispatch()` 的收尾分支（对没有 RUNNING workflow 的任务直接终态化）。**没有 P2 Worker 时该任务会永久停在 `CANCELLING`**（当前该任务即为此状态）。
- 影响：与本次 `RECEIVED` 缺陷同属“缺消费者即无终态”的类别，但方向相反（这次是缺 P2）。
- 建议最小修复（P1，未实施）：若 `cancel` 时任务尚无任何已投递的采集（`task_dispatches.sent=false` 且无 `collect/*` workflow），说明不可能有采集进程持有它，API 可直接终态化为 `CANCELLED`；否则保持 `CANCELLING` 交由 P2 收尾。
