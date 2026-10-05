# UNIT-01 本地开发验证阶段：验证证据（2026-09-27）

> **2026-09-27 后续更新：本文记录阶段的阻塞已解除。** 用户随后可接收验证码；真实登录、真实搜索与 2 位达人主页采集已跑通并落库，见[真实采集验证](UNIT-01-real-collection-2026-09-27.md)。本文中「登录未完成/未执行」的结论只代表该阶段当时的事实，保留不改写。
> 另需更正本文 3.3 的初步归因：后续证据表明「登录失效」不是 Chrome/profile 质量问题，而是 SSO 会话域与深链不启动应用的组合表象。

> 结论先行：**本地开发模式已实现并通过离线/静态检查与真实浏览器启动验证；真实星图登录与真实采集未完成**（用户手机不在身边，无法接收平台验证码）。因此 U02/U04/U06 未核验、平台契约未登记、F04/F05 真实功能验收未通过。本文只记录实际发生的事，未执行项列在末节。
> 命令原始记录见 [UNIT-01-local-stage-2026-09-27.log](UNIT-01-local-stage-2026-09-27.log)。

## 1. 执行环境（本轮实测）

| 项目 | 实际值 | 核实方式 |
|---|---|---|
| 操作系统 | macOS 26.5.2 | `sw_vers -productVersion` |
| Python | 3.13.5（`.venv`） | `.venv/bin/python -V` |
| Playwright | 1.63.0 | `importlib.metadata.version("playwright")` |
| 浏览器（本机 Chrome） | `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`，`--version` = 154.0.8037.57 | `xingtu browser-check` |
| Playwright 启动后报告版本 | 154.0.8037.57（与可执行文件一致） | `xingtu browser-check` |
| 随包 Chromium | `chromium-1243`（`.runtime/browsers`） | 目录检查；契约测试使用 |
| PostgreSQL | 18.3，`127.0.0.1:55439`，角色 `xingtu_test`；本轮新建库 `xingtu_local_dev` | `pg_ctl status`、`psql \l` |
| Temporal | Python SDK 1.33.0 本地测试服务器（`.runtime/temporal-test/temporal-v1.9.1`） | `pytest tests/e2e` 与 `make smoke-local` 实际运行 |
| Docker | 守护进程**不可用** | `docker info` 失败；`make dev`/`make stop` 仍未验证 |
| 网络 | `https://www.xingtu.cn/` 返回 HTTP 200 | `curl` |
| 会话 MCP | 本会话无已接入的 Playwright MCP | Harness 工具列表中无 MCP 客户端（决策见 [DEC-007](../decisions/DEC-007-contract-research-tooling.md)） |

## 2. 本轮实现（含关键文件）

| 内容 | 落点 |
|---|---|
| 显式网络模式 `production_line` / `local_development`，按模式互斥校验代理与线路证明 | `backend/src/xingtu/domain.py`（`NetworkMode`）、`backend/src/xingtu/runtime.py`（`UnitConfig.mode_binding`） |
| 本地模式 `ensure_line` 只断言"无绑定代理"，产出 `local_network_attestation()`（不含线路证明字段） | `runtime.py` |
| 真实 Chrome 固定与版本记录：`browser_executable_path` / `browser_channel`（互斥），启动后记录版本与 UA | `runtime.py`、`xingtu browser-check` |
| profile 隔离保持：项目私有根、`0700` 目录、`0600` 锁、禁多进程；`ps` 不可用时改为 fail-closed 的 `PROCESS_LIST_UNAVAILABLE` | `runtime.py` |
| 网络模式入库并纳入不可变绑定 | `migrations/002_unit_network_mode.sql`、`repository.py`（`migrate` 改为按 `schema_migrations` 顺序应用全部待应用迁移、`register_unit`） |
| 证据与执行上下文标识网络模式 | `evidence.py`（`EvidenceSummary.network_mode`）、`domain.py`（`ExecutionContext.network_mode`） |
| 生产入口显式拒绝本地单元 | `xingtu production-preflight`（`cli.py`） |
| 真实契约登记用研究采集（仅本地模式、主机白名单、脱敏结构记录） | `backend/src/xingtu/research.py`、`xingtu research` |
| 登录等待改为证据驱动（受保护页可见 + 账号可读，`expected_account_id` 必须一致） | `cli.py`（`wait_for_manual_login`） |
| 本地验证载体（真实 Activity + Workflow，Temporal 本地测试服务器，一次性终态） | `scripts/local_smoke.py`、`make smoke-local` |
| 未捕获本地输入的稳定错误码（不再抛栈） | `cli.py`（`INPUT_FILE_UNREADABLE`）、`scripts/local_smoke.py`（`ROOT_TASK_ID_MUST_BE_UUID`） |

## 3. 实际执行的验证与结果

### 3.1 离线/静态（合成数据，不含平台流量）

| 命令 | 结果 |
|---|---|
| `ruff check backend conftest.py tests scripts` | 通过，exit 0 |
| `ruff format --check backend conftest.py tests scripts` | 26 files already formatted，exit 0 |
| `mypy backend/src` | Success: no issues found in 14 source files |
| `pytest backend/tests/unit -q` | **52 passed**（原 41 + 新增 11） |
| `pytest backend/tests/contract -q` | **10 passed**（真实 Chromium + 合成路由） |
| `pytest backend/tests/integration -q` | **23 passed**（原 22 + 新增 1；真实 PostgreSQL） |
| `pytest tests/e2e -q` | **2 passed**（原 1 + 新增 1；真实 Temporal 测试服务器） |

合计 **87 项通过**。新增用例覆盖：本地模式必填/互斥校验、本地模式不产生线路证明字段、`ensure_line` 本地通过且带代理即拒、生产无证明即 `LINE_VERIFICATION_UNAVAILABLE`、profile 必须位于项目私有根、配置文件权限、证据网络模式标识、research 模式与主机白名单拒绝、迁移 1+2 与网络模式入库/不可变、以及"真实 Activity 拒绝未核验注册表并进入终态 FAILED"。

### 3.2 本地真实执行（本机 IP + 本机 Chrome）

| 检查 | 实际结果 |
|---|---|
| `xingtu migrate --environment development`（库 `xingtu_local_dev`） | 成功；`schema_migrations` = {1,2} |
| `xingtu register-unit` | `{"unit_id":"unit-local-mac-01","state":"NEEDS_LOGIN","network_mode":"local_development"}`；库内 `line_ref=local-dev-macos`、`network_mode=local_development` |
| `xingtu browser-check` | 真实启动系统 Chrome 成功：`launch_ok=true`、`playwright_reported_version=154.0.8037.57`、`page_opened=true`、`browser_stopped=true`、`proxy_configured=false` |
| `xingtu production-preflight`（本地配置） | 按预期拒绝：`RESOURCE_UNAVAILABLE: LOCAL_DEVELOPMENT_UNIT_IS_NOT_A_PRODUCTION_LINE`，exit 2 |
| `xingtu enable-contract --registry contracts/douyin_xingtu.unverified.json` | 按预期拒绝：`PLATFORM_PAGE_CHANGED: UNVERIFIED_REGISTRY`，exit 2 |
| `make smoke-local`（真实 `Activities.collect` + `CollectionWorkflow` + Temporal 测试服务器，未核验契约） | 终态 `FAILED`，`failure_reason=PLATFORM_PAGE_CHANGED: UNVERIFIED_REGISTRY`，`valid_count=0`；exit 0（夹具按终态断言） |
| `xingtu research`（打开 `https://www.xingtu.cn/`） | 进程按 `local_development` 启动成功，创建独立 profile 与研究输出目录；**人工登录未完成**（见 3.3） |

上述第 5—7 项同时证明：live 平台门槛未被本地模式削弱，本地配置无法被当成生产线路，未核验契约不能启用。

### 3.3 真实账号登录：未完成（人工资源限制）

- 已按 §1.3 唤起项目独立 profile 的本机 Chrome，打开 `https://www.xingtu.cn/` 并等待人工登录。
- 用户反馈：**手机号码不在身边，当前无法接收平台验证码**，因此无法完成登录；并明确这不是代码问题。
- 处理：主动取消研究进程，未产生任何登录后证据（`.runtime/research/r01-login/` 为空）。
- 影响：会话入口/账号标识/受保护页面、搜索分页与终点、主页逐模块字段**全部未登记**；未创建 `contracts/douyin_xingtu.verified.json`；不做任何推测填写。

## 4. 未执行项与影响（不计为通过）

| 未执行 | 原因 | 影响 |
|---|---|---|
| 真实会话与账号身份证据（U06） | 人工登录未完成 | `registry.session=null`；`xingtu login` 仍会以 `REGISTER_SESSION_ENTRY_FIRST` 拒绝 |
| 真实搜索筛选/回读/分页/终点（U02、U04） | 依赖会话 | F04 不能标记完成；`search=null` |
| 真实主页逐模块字段对照（U04） | 依赖会话 | F05 不能标记完成；`modules=[]` |
| F04/F05 真实 1—3 位小样本采集与落库核对 | 依赖已核验注册表 | 无真实采集/快照证据 |
| 生产线路、蜂窝、DNS、断线隔离、旧执行者撤销（U07/U08） | 本轮范围外 | 本地证据不能替代生产验收 |
| `make dev` / `make stop`（Compose） | Docker 守护进程不可用 | 编排入口仍未验证 |
| `make setup`、S3/MinIO 证据、封面存储（U09） | 未执行 | 安装与对象存储路径未验证 |

## 5. 脱敏与隐私处理

- 原始研究采集仅写入 `.runtime/research/`（`0700`、`.gitignore` 覆盖）；不采集请求/响应头、Cookie、令牌与响应正文整体，查询值按形状脱敏。
- 本轮未产生登录后页面数据，因此 `docs/` 内没有任何平台正文或个人数据。
- 单元配置、profile 与数据库 DSN 均位于 `.runtime/`（`0600`/`0700`），未写入版本库；`contracts/` 未粘贴任何凭据。
