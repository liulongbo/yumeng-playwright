# UNIT-01：执行单元与平台核验

状态：待验收  
更新时间：2026-10-23T21:07:56+08:00

## 2026-10-23 macOS/Windows 本地化补充

F10 本轮新增 POSIX/Windows Profile 锁适配、Windows Chromium `lockfile` 保守停止证明、系统
Chrome Stable 发现、Collection Worker 独立 generation/心跳/停止记录与重复实例拒绝。macOS 已
实测 Chrome 156.0.8078.47、可见模式 SessionHealth `VALID`、Worker generation 1→2 与重复启动
拒绝；自然 Challenge 后浏览器/租约按超时路径安全释放。Windows 只有静态/隔离测试，实机仍为
**NOT TESTED**，故本卡状态及 U06/U07/U08 未验收项不变。证据见
[F10 跨平台适配验收](../evidence/F10-local-cross-platform-2026-10-23.md)。

## 2026-10-06 单元账号绑定变更（改绑）

用户决策舍弃旧登录身份（其父账号下多个子账号导致重启后漂移），改为只含单一子账号的新巨量星图账号。`unit-local-mac-02` 的 `expected_account_id` 由 `ID: 1865332309937515` 改为 `ID: 1807978499337419`，旧 profile 备份后清空重建，改绑经新增的显式审计路径执行（迁移 007 + `xingtu rebind-account`），单元重置为 `SESSION_UNVERIFIED` 后由两次独立冷启动复核为 `STABLE`。**绑定字段本身的不可变性未放宽**：`register_unit` 与 `ACCOUNT_MISMATCH` 路径仍拒绝自动改绑。证据见[执行单元账号改绑与漂移规避证据](../evidence/SESSION-01-account-rebinding-2026-10-06.md)，判定过程见 [SESSION-01](SESSION-01.md)。

## 目标与范围

实现并核验执行单元：单元配置与绑定、独立持久 profile、独占租约与心跳、维护模式、线路/代理与 DNS 隔离、旧执行者隔离、会话版本，以及平台契约（会话/搜索/主页字段）的真实核验。  
包含：单元注册与状态、租约获取/续租/释放/隔离、profile 私有目录与文件锁、线路证明与探针、凭据环境引用、维护入口（CLI）、平台契约登记与核验交付物。  
不包含：前端与产品 API、F06/F09、采购决策、生产发布、远程浏览器承载方案选型实现（U06 待核验）。

## 本地阶段补充（2026-09-27）

用户确认设备齐全、有真实星图账号，原“硬件/账号未到位”阻塞解除。先用本机IP + Chrome +账号验证本地核心流程，再实施蜂窝线路；本卡状态调整为进行中，表示继续推进已有工作。

> **2026-09-27 本轮更新（一）**：本地开发网络模式、真实 Chrome 固定与版本实测、契约研究采集工具、登录等待改造、本地验证载体（`make smoke-local`）均已实现并通过离线/静态检查与真实浏览器启动验证。当时真实星图登录未完成（用户手机不在身边），会话/搜索/主页契约未登记。
>
> **2026-09-27 本轮更新（二）**：用户随后可接收验证码，本地阶段完成**真实登录 + 真实搜索 + 2 位达人主页采集与落库核对**；平台契约 `xingtu-ad-creator-square-v1` 已由真实交互登记并通过 live 门槛发布。阻塞解除，本卡由“阻塞”改为“待验收”。仍未满足：分页只核验首页、主页只登记 `basic` 模块、筛选枚举与访问节奏未核验、生产线路/远程维护（U06/U07/U08）未执行——因此整卡不得标为已完成。见[真实采集证据](../evidence/UNIT-01-real-collection-2026-09-27.md)。

新增本地阶段验收（不删除原生产验收）：

- [x] 显式开发模式支持本机IP，记录Chrome路径/版本与Playwright兼容性；保持项目独立profile、账号校验、独占和维护互斥。现有必填代理/证明逻辑须适配，不伪造生产线路证明。
  - 实测：`xingtu browser-check` 用 `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`（154.0.8037.57）真实启动成功，Playwright 1.63.0 报告版本与可执行文件一致；`proxy_configured=false`。模式与绑定校验见[DEC-006](../decisions/DEC-006-local-network-mode.md)。
- [x] 唤起独立浏览器由用户人工登录，登记真实会话入口、账号身份与受保护页证据；session=null时不能跳过登记直接运行CLI。
  - 实测：`xingtu login` 在真实账号上通过——会话入口 `sso.oceanengine.com/xingtu/login?role=1`、受保护就绪 `a.navigator-menu-item-link[href="/ad/creator/index"]`、账号 `div.navigator-user__userid`（文本 `ID: 1865332309937515`，与 `expected_account_id` 精确比对），单元进入 `READY`、`session_version` 递增到 4。
  - 未绕过登记：`session=null` 时 `login` 仍以 `REGISTER_SESSION_ENTRY_FIRST` 拒绝；先由真实观察登记会话，再运行 `login`。
- [x] 按真实交互登记U02/U04搜索与主页契约，不猜测选择器/端点，不关闭live门槛；F04/F05完成1—3位小样本采集与持久结果核对。
  - 注册表 `contracts/douyin_xingtu.verified.json` 已发布（`require_enabled(live=True)` 通过）：搜索请求/回读/关联、`authors[]`+`star_id`、主页 URL 模板、`basic` 模块字段全部来自真实观察；未知项保持 `null` 或登记为覆盖缺口。
  - 真实小样本：关键词「美妆」→ 20 候选 → 采集 2 位 → `valid_count=2`、`profile_complete_count=2`，已发布快照并与真实主页身份块对照（`姜乘澜 / 星图ID 7646720304210771978`）。
  - 范围说明（未覆盖部分仍计入下方未勾选项）：分页仅首页、主页仅 `basic`、筛选枚举与访问节奏未核验。
- [x] 本地阶段证据明确标识网络模式，生产入口拒绝把本地配置视为已通过蜂窝隔离验证；本地完成后仍保留U07/U08生产验收。
  - 实测：`xingtu production-preflight` 对本地单元返回 `RESOURCE_UNAVAILABLE: LOCAL_DEVELOPMENT_UNIT_IS_NOT_A_PRODUCTION_LINE`（exit 2）；网络模式入库（迁移 002）并进入 `EvidenceSummary`/`ExecutionContext`；`enable-contract` 对未核验注册表仍拒绝 `UNVERIFIED_REGISTRY`；真实 `Activities.collect` 经 `make smoke-local` 验证 live 门槛不可绕过。U07/U08 原验收全部保留。

依据：[技术方案§1.3](../AI达人智能发现与采集系统-完整技术方案.md)、[项目基线](../evidence/PROJECT-BASELINE-2026-09-27.md)。远程承载实现由[F10](F10.md)负责，产品资源调度/跨节点与部署由[OPS-01](OPS-01.md)负责；本卡保留原验收并共享证据。

## 关联与依赖

前置：BASE-01。功能：F04/F05 必要支撑。验收：T17—T19、T31—T40。待验证：U02/U04/U06/U07/U08。

## 验收清单

- [x] 单元对象与状态机：平台、账号引用、线路 ID、代理端点、profile 引用、状态（`READY`/`LEASED`/`NEEDS_LOGIN`/`OFFLINE`/`QUARANTINED`/`DRAINING`）、会话版本、单调递增租约代次。
- [x] 独占租约与心跳：事务 + 唯一约束获取，心跳续租，写入前校验租约代次与尝试版本，拒绝旧代次迟到写入；租约到期不抢占而是先隔离。
- [x] profile 隔离：`launch_persistent_context` 使用项目私有目录、`0700` 目录与 `0600` 文件锁、禁止多进程同时打开、禁止使用日常浏览器目录。
- [x] 线路与凭据：线路证明文件校验（DNS 绑定、断线禁止直连、出口强制）、独立探针命令与新鲜度校验；代理凭据只经环境变量引用，不进入配置响应或日志。
- [x] 维护模式：独占维护租约、15 分钟限时、`session_version` 递增、成功后释放并唤醒等待任务。
- [x] 离线单元、契约、存储及恢复验证通过：租约过期隔离与陈旧写入拒绝、事务回滚、并发投递幂等、profile 配置校验路径。
- [ ] 实机核验：真实账号登录与身份识别、受保护页面与会话验证、J1900/蜂窝模块/SIM 与 OpenWrt 线路、DNS 与断线拒绝直连、出口变化、旧浏览器停止确认与节点失联隔离（U06/U07/U08）。
  - 已实测（本地部分）：浏览器可执行路径/版本与 Playwright 兼容性；真实账号登录与身份识别；受保护页面与会话验证（`xingtu login` → READY，session_version=4）。
  - 未执行：J1900/蜂窝/SIM/OpenWrt、DNS 与断线拒绝直连、出口变化、旧浏览器停止确认与节点失联隔离。
- [ ] 平台契约核验：会话、搜索分页与终点、主页逐模块字段与默认口径的正反样本（U02/U04）。
  - 已核验：会话入口/账号/受保护页/主页身份；关键词搜索首页（`authors[]`、`id_path=star_id`、`pagination.has_more`）；`basic` 模块 9 个字段的来源、状态与采集时间。
  - 未核验：多页推进（契约声明 `single_page_only` 并记录缺口）、商业与报价/传播与互动/粉丝画像等模块、筛选枚举与组合、访问节奏与限流阈值。
- [ ] 远程浏览器承载方式验证（U06）。

## 实现记录

- 2026-09-26 原始实现（历史保留）：`backend/src/xingtu/runtime.py` 的 `UnitConfig`（含 `budget`/`evidence`）、`ensure_line` 线路证明与探针、`BrowserRuntime` 持久化上下文与 profile 锁、`confirm_local_browser_stopped` 保守隔离确认；`backend/src/xingtu/repository.py` 当时的 `register_unit`/`acquire`/`heartbeat`/`release`/`verify_maintenance`/`recover_stopped_unit`、租约代次与会话版本围栏；`backend/src/xingtu/worker.py` 的 Activity 心跳、租约校验、运行/维护互斥、释放时上报浏览器是否已停止；`backend/src/xingtu/cli.py` 当时的 `register-unit`、`login`（人工登录 + 三项证据校验 + `session_version` 递增）、`recover-unit`、`worker`；`contracts/README.md` 契约登记与核验交付清单。**AUTO-01 已于 2026-09-28 删除 `verify_maintenance` 旧入口，改为只能通过同一 BrowserContext 的 `promote_maintenance_to_collect` 原子交接递增会话版本；本条仅记录历史，不是当前可调用接口清单。**
- 2026-09-27 本轮改动：
- `backend/src/xingtu/runtime.py`：`UnitConfig`（本地/生产模式互斥校验、`browser_executable_path`/`browser_channel`、`research_allowed_hosts`、`budget`/`evidence`）、`ensure_line` 按模式分派、`local_network_attestation`、`BrowserRuntime` 持久化上下文与 profile 锁（本地模式不加代理、记录浏览器版本）、`browser_compatibility_report`、`browser_executable_version`、`confirm_local_browser_stopped`（进程列表不可用时 fail-closed 为 `PROCESS_LIST_UNAVAILABLE`）。
- `backend/src/xingtu/domain.py`：`NetworkMode`；`ExecutionContext.network_mode`。
- `backend/src/xingtu/research.py`（新增）：`xingtu research` 研究采集（仅 `local_development`、主机白名单、结构脱敏记录、`--steps` 显式驱动）。
- `backend/src/xingtu/repository.py`：`migrate` 改为按 `schema_migrations` 顺序应用全部待应用迁移；`register_unit` 记录 `network_mode` 并纳入不可变绑定。
- `migrations/002_unit_network_mode.sql`（新增）：`execution_units.network_mode`。
- `backend/src/xingtu/evidence.py`：`EvidenceSummary.network_mode`（本地证据自带模式标识，不伪装线路证明）。
- `backend/src/xingtu/cli.py`：`browser-check`、`production-preflight`、`research` 新命令；`login` 改为证据驱动的有界人工登录等待（`--wait-seconds`，TTY 可用回车提前结束）；本地输入不可读返回 `INPUT_FILE_UNREADABLE`；`register-unit` 输出网络模式。
- `scripts/local_smoke.py` + `make smoke-local`（新增）：本地验证载体，用 Temporal 本地测试服务器运行**真实** `Activities.collect` 与 `CollectionWorkflow`，一次性等待终态。
- `backend/src/xingtu/contracts.py`（真实登记后补充）：`SearchSpec` 新增 `homepage_path`/`homepage_template`（恰好登记其一，模板含 `{platform_creator_id}`）、`fixed_sort`、`single_page_only`（必须附覆盖缺口）、`binding_values`（计划取值→平台字面量）、检索级 `coverage_gaps`；`LocatorSpec` 新增 `property`（读取表单 DOM property）；注册表级 `session_boot_timeout_seconds`。
- `backend/src/xingtu/adapter.py`（真实登记后修复）：`prepare()` 先经 `session.entry_url` 完成会话握手再进搜索入口；`read_account()` 有界等待账号可见；`map_bindings` 在全部绑定生成后应用；`read_locator` 支持 property 读取并报出失败定位；`single_page_only` 在第 2 页请求前安全停止；`resolve_homepage` 用 `id_path` + 模板生成候选主页。
- `backend/src/xingtu/worker.py`：把 `config.network_mode` 带入 `ExecutionContext`（此前证据会误标 `production_line`）。
- 未改动 F04/F05 的 Engine、Adapter、契约与字段解析逻辑（本轮只补齐其真实验证的前置条件）。
- 决策记录：[DEC-005 注册表补齐与发布门槛](../decisions/DEC-005-registry-gate.md)、[DEC-006 显式本地开发网络模式与生产线路隔离](../decisions/DEC-006-local-network-mode.md)、[DEC-007 真实契约登记的研究采集工具与本地验证载体](../decisions/DEC-007-contract-research-tooling.md)。

## 验证证据

- 2026-09-26（离线/合成）：macOS 26.5.2 / Python 3.13.5 / PostgreSQL 18.3。详见[离线验证证据](../evidence/F04-F05-offline-verification.md)与[命令记录](../evidence/F04-F05-offline-verification.log)。`pytest backend/tests/integration` 22 passed；`xingtu register-unit` 登记成功；`xingtu migrate --environment test` 应用迁移 1。
- 2026-09-27（本轮，离线/静态 + 本地真实浏览器）：macOS 26.5.2 / Python 3.13.5 / Playwright 1.63.0 / 系统 Chrome 154.0.8037.57 / PostgreSQL 18.3（`xingtu_local_dev`）/ Temporal 测试服务器 v1.9.1 / Docker 不可用。详见[本地阶段证据](../evidence/UNIT-01-local-stage-2026-09-27.md)与[命令记录](../evidence/UNIT-01-local-stage-2026-09-27.log)。
  - `ruff check`、`ruff format --check`、`mypy backend/src` 全部通过（exit 0）。
  - `pytest backend/tests/unit` **52 passed**；`backend/tests/contract` **10 passed**；`backend/tests/integration` **23 passed**；`tests/e2e` **2 passed**（合计 87，含本轮新增 12 项本地模式/门槛/网络模式入库用例与 1 项"真实 Activity 拒绝未核验注册表"用例）。
  - `xingtu browser-check`：真实启动系统 Chrome，`launch_ok=true`、版本 154.0.8037.57、`proxy_configured=false`、`browser_stopped=true`。
  - `xingtu migrate --environment development`：`schema_migrations={1,2}`；`xingtu register-unit`：`network_mode=local_development` 已入库。
  - 门槛负向实测：`production-preflight` → `LOCAL_DEVELOPMENT_UNIT_IS_NOT_A_PRODUCTION_LINE`（exit 2）；`enable-contract` → `UNVERIFIED_REGISTRY`（exit 2）；`make smoke-local`（未核验契约）→ 终态 `FAILED` / `PLATFORM_PAGE_CHANGED: UNVERIFIED_REGISTRY`。
  - 未执行：真实会话/账号身份（U06）、真实搜索与主页契约（U02/U04）、F04/F05 真实小样本采集、蜂窝线路与生产隔离（U07/U08）、远程承载（U06）；原因：**人工登录未完成（用户手机不在身边，无法接收平台验证码）**与本地阶段范围边界。影响：平台契约保持 `UNVERIFIED`，F04/F05 不能标记完成。
  - 未执行：`make dev`/`make stop`（Docker 守护进程不可用）；`make setup`、S3/MinIO 证据路径（历史未执行项，本轮未重测）。
  - 历史未执行记录保留：2026-09-26 因资源缺失导致的实机核验项未执行，本轮原因已由"资源未到位"更新为"人工登录资源暂时不可用"。
- 2026-09-27（本轮二，本地真实采集）：环境同上。详见[真实采集证据](../evidence/UNIT-01-real-collection-2026-09-27.md)与[命令/数据库记录](../evidence/UNIT-01-real-collection-2026-09-27.log)。
  - `xingtu login`（账号二）→ `READY`、`session_version=4`；`xingtu start` → root `a48d60c6-5e44-4b56-915d-474304fb4f17`。
  - `make smoke-local`（真实 `Activities.collect` + `CollectionWorkflow`，关键词「美妆」，目标 2）→ `PARTIAL_COMPLETED`；`discovered=20`、`scanned=20`、`valid=2`、`profile_complete=2`、诊断 0、`search_exhausted=false`（未谎报耗尽）。
  - 持久化核对：2 条已发布快照（`profile_complete=true`、`featured_status=NOT_ATTEMPTED`、`created_at=2026-09-27 17:11:28+08`）；`basic` 9 字段均带 `source_kind=response`、真实 `path_ref`、`observed_at`、`session_version`、`source_contract`；`city/province` 为 `NO_DATA`（平台空串，未伪造）。
  - 真实页面 ↔ 持久结果：主页 `.../douyin-video/7646720304210771978` 身份块 `姜乘澜  精选达人 星图ID: 7646720304210771978` 与持久 `nickname`/`platform_creator_id` 一致。
  - 失败→修复链（保留）：`MISSING_SOURCE`（改 property 读取与唯一 ready）→ `ACCOUNT_LOCATOR_UNREADABLE`（改有界等待）→ `PLATFORM_CONDITION_MISMATCH:keyword_mode`（映射顺序）→ 成功。
  - 未执行（本轮二）：分页第 2 页及以后、其余主页模块、筛选枚举、访问节奏、生产线路/远程维护（U06/U07/U08）、Docker Compose、`make setup`、S3。
  - 最终离线复测：`ruff check`/`ruff format --check`/`mypy` 通过；`pytest` 单测 94 / 契约 13 / 集成 26 / E2E 3 全绿。
- 2026-09-26 历史记录（保留）：未执行全部实机核验项（真实账号、线路、profile 隔离实测、远程浏览器维护），原因为 J1900/蜂窝模块/SIM/真实星图账号未到位且 U06 承载方案未选定；执行单元 Activity 强制 `require_enabled(live=True)`，无法用合成注册表绕过；`make dev` Compose 依赖编排因 Docker 守护进程未运行未执行。
- 2026-10-12（真实平台，**只读会话核验**）：用户显式授权只读核验后执行 `xingtu session-diagnostics --config .runtime/units/local-dev-mac-02.json`（`XINGTU_DIAGNOSTIC_HMAC_KEY` 取自 `.runtime/drift-probe.hmac-key`，`PYTHONPATH=backend/src`），`2026-10-12T15:36:53+08:00 → 15:37:01+08:00`、exit `0`。结果 `SessionHealthStatus.VALID`：`observed_account_id == expected_account_id == ID: 1807978499337419`、`protected_page_verified=true`、`login_page_verified=false`、`challenge_verified=false`、Chrome `154.0.8037.98`、`normal_close_confirmed=true`。**未**执行搜索、采集或任何业务写入；`session-diagnostics` 不取租约，故库中 `execution_units.last_session_checked_at` 仍为旧观测 `2026-10-12T01:12:41+08:00`，本次结论以报告文件为准。详见[会话实时只读核验证据](../evidence/UNIT-01-session-live-check-2026-10-12.md)。
  - 核验前的既有记录（**不作为实时结论**）：库中 `state=READY`、`last_session_status=VALID`、`last_session_reason=PROTECTED_PAGE_AND_ACCOUNT_VERIFIED`，时间 `2026-10-12T01:12:41+08:00`，对应根任务 `7a5111cc-49cd-431d-90ca-3120201e809e` `COMPLETED`。按 `domain.py` 的 `SessionHealthStatus` 契约，持久化状态**从不**构成活动会话证明，只有当前进程观测可产生 `VALID`，故必须补做本次进程内观测。
  - 本次核验不改变本卡验收结论：分页/其余主页模块/筛选枚举与访问节奏、生产线路与隔离（U07/U08）、远程承载（U06）仍未验收。
- 2026-10-14（真实平台，**只读会话核验**）：用户要求核验执行单元星图登录状态并在失效时唤起 Chrome 人工登录，同时记录“登录态快速失效”的原因。执行 `xingtu session-diagnostics --config .runtime/units/local-dev-mac-02.json`（HMAC 密钥为本轮新生成的本机 `.runtime/diag.hmac-key`，因历史 `.runtime/drift-probe.hmac-key` 已不在工作区，故本次报告 HMAC 与旧报告不可比对），`2026-10-14T15:49:46 → 15:49:53+08:00`、exit `0`。结果 `VALID`、`observed == expected == ID: 1807978499337419`、`protected_page_verified=true`、`login_page_verified=false`、`challenge_verified=false`、`evidence_reason=PROTECTED_PAGE_AND_ACCOUNT_VERIFIED`（**未**走人工确认降级）、`session_snapshot.restored_before_navigation=true`、Chrome `155.0.8059.40`、`normal_close_confirmed=true`。**未**执行搜索、采集或任何业务写入；结论以报告文件为准。据此存活下界更新为**约 29 小时 / 3 次冷启动**（首份快照 2026-10-13T16:48+08 → 本轮），上界仍未测。根因与 5 项待优化缺口见[登录状态核验与快速失效根因记录](../evidence/SESSION-01-login-lifetime-root-cause-2026-10-14.md)。本卡验收结论不变。

## 交接信息

- **当前运行态（2026-10-23T21:07+08:00）**：自然 Challenge 的人工接管窗口超时后，任务已
  `PARTIAL_COMPLETED` 并安全释放浏览器/租约；Collection Worker generation 2 在线，执行单元保留
  `NEEDS_VERIFICATION / browser STOPPED`。再次真实采集前必须由用户完成合法验证并重新形成
  SessionHealth；不得依据 10 月 14 日的历史 `VALID` 直接放行。
- 当前资源：用户已确认设备及账号具备；本轮实测到系统 Chrome 154.0.8037.57 + Playwright 1.63.0 可真实启动并访问 `https://www.xingtu.cn/`（HTTP 200）。
- **会话现状（2026-10-14T15:49+08:00 实测）**：`unit-local-mac-02` 的星图登录状态为**有效**（`VALID`，受保护页可见，账号 = `ID: 1807978499337419`，快照在首个导航前恢复），可继续免人工登录发起采集；用户已按需打开专属 profile 的 Chrome 窗口（用完须 `Command-Q`，否则采集会 `PROFILE_IN_USE`）。注意 `star_sessionid` 为会话级 Cookie，登录态跨重启依赖私有快照，该结论只对“当前这一时段”成立。根因记录见[登录状态核验与快速失效根因记录](../evidence/SESSION-01-login-lifetime-root-cause-2026-10-14.md)。
- 阻塞已解除（2026-09-27 本轮二）：真实登录、真实搜索与 2 位达人主页采集均已完成并落库（[真实采集证据](../evidence/UNIT-01-real-collection-2026-09-27.md)）。以下历史解除条件保留备查：
  1. `xingtu research --config .runtime/units/local-dev-mac.json --url https://www.xingtu.cn/ --out .runtime/research/r01-login --login-wait-seconds 1500 --login-done-file .runtime/research/login.done --steps .runtime/research/steps-login.json`（登录完成后由人工信号或超时结束）；
  2. 依据真实观察登记会话/搜索/主页契约到 `contracts/douyin_xingtu.verified.json`，通过 `require_enabled(live=True)` 与 13.5 交付清单；
  3. `xingtu login`（校验 `expected_account_id`）→ `xingtu start`（`target_count ≤ 3`）→ `make smoke-local`；
  4. 用 `xingtu status`/`results` 与数据库快照核对字段、来源、状态与采集时间。
- 当前遗留（未满足的验收）：
  1. 分页仍未完整核验：AUTO-01 已实证并限界开放第 2 页；第 3 页及以后与分页终点未通过。
  2. 主页只登记 `basic` 模块；商业与报价、传播与互动汇总、粉丝画像等未登记（该账号观察中 `price_info` 为空）。
  3. 筛选枚举（合作诉求/匹配度/性价比/主题推荐）与访问节奏/限流阈值未核验。
  4. 生产线路与隔离（U07/U08）、远程承载（U06）未验证；**本地证据不能替代**，`production-preflight` 仍拒绝本地单元。
- 下一步：①按[契约登记说明](../../contracts/README.md) 补齐分页与其余主页模块；②执行蜂窝线路、DNS/断线/失联/租约过期验证；③U06 远程维护承载。
- 历史资源说明仅代表 2026-09-26/2026-09-27 核验时情况；上节历史验证记录保留。

## 状态历史

- 2026-10-23T21:07:56+08:00：保持待验收；macOS 本地锁/Chrome/Worker 心跳及自然 Challenge
  接管已验证，Windows 实机未验证。自然 Challenge 未由人工完成，单元安全停在
  `NEEDS_VERIFICATION / browser STOPPED`，再次采集前需人工恢复会话。

- 2026-09-26T20:17:35+08:00：待办 → 进行中；用户批准开发方案。
- 2026-09-26T21:50:00+08:00：进行中 → 阻塞；离线实现与合成验证完成，真实账号/线路/硬件核验因资源缺失无法推进。
- 2026-09-27T09:51:41+08:00：阻塞 → 进行中；用户确认资源齐全，明确优先本机IP+Chrome+账号开发验证；新增本地阶段清单，保留全部生产验收。
- 2026-09-27T17:35:00+08:00：阻塞 → 待验收；用户可接收验证码后完成真实登录（`READY`/session_version=4）、按真实交互登记并发布平台契约 `xingtu-ad-creator-square-v1`、完成 2 位达人真实采集与落库核对（`valid=2`/`profile_complete=2`）。仍剩分页、其余主页模块、筛选枚举、访问节奏与全部生产线路/远程维护验收，故为“待验收”。见[真实采集证据](../evidence/UNIT-01-real-collection-2026-09-27.md)。
- 2026-09-27T11:20:00+08:00：进行中 → 阻塞；本地开发网络模式、真实 Chrome 兼容性、研究采集工具与本地验证载体已实现并实测（87 项离线/本地测试通过，门槛负向实测通过）；真实星图登录因用户手机不在身边、无法接收验证码而未完成，会话/搜索/主页契约未登记，F04/F05 真实采集未执行。解除条件见交接信息。见[本地阶段证据](../evidence/UNIT-01-local-stage-2026-09-27.md)。
- 2026-10-12T15:37:00+08:00：待验收 → 待验收（不变）。用户授权后对当前唯一执行单元 `unit-local-mac-02` 执行只读实时会话核验：`xingtu session-diagnostics` 冷启动真实 Chrome 访问已登记受保护入口，得 `SessionHealthStatus.VALID`，账号精确等于绑定账号 `ID: 1807978499337419`，无登录页、无安全挑战、浏览器正常关闭。该核验只补"当前进程会话有效"这一项证据，未改变本卡"待验收"状态与其余未验收项。见[会话实时只读核验证据](../evidence/UNIT-01-session-live-check-2026-10-12.md)。

## 2026-09-28 AUTO-01 联动回归

状态继续待验收。停止原因、独立业务覆盖、错误分类、页 2 请求复用及会话关闭复核由 [AUTO-01](AUTO-01.md) 承接；当前全套 153 项测试通过。真实分页只扩大到页 2，完整主页与跨重启会话续跑仍未验收。详见[阶段一证据](../evidence/AUTO-01-stage1-2026-09-28.md)。

## 2026-09-29 会话寿命结论更正

**U06 仍未关闭，且其判据需要修正。** 本卡此前沿用"星图业务会话不能跨 Chrome 重启恢复"作为会话结论，该结论现被判定**证据不足并撤回**（详见 [AUTO-01](AUTO-01.md) 与 [技术方案§1.4](../AI达人智能发现与采集系统-完整技术方案.md) 的更正说明）：

- 原证据自述**无法区分**"用户新登录"与"既有会话被接受"，且探针**只验证元素可见、从未比对账号 ID**；
- 用户日常 Chrome 实测可 **7-8 天**免登录，反证平台侧持久会话可行；
- 项目独立 profile 实测约 **45 分钟**失效，方向相反。**真实存活时长未定。**

**因此**：本卡的"平台会话识别与持久化"验收不得再以任一方向的未证实结论为依据；"会话能否跨重启、能存活多久"改由独立核验卡 [SESSION-01](SESSION-01.md) 承接，核验完成后再回填本卡 U06 结论。

**历史登记的两项实测缺陷（2026-09-29 已修复）**：

1. `recover-unit` 依赖 `/bin/ps`，在受限沙箱返回 `PROCESS_LIST_UNAVAILABLE`，导致 owner 中断后单元无法用内置路径回收（实测停在 `LEASED/maintenance/browser_stopped=false`）。安全边界本身正确（fail-closed），但缺少可在无 `ps` 环境使用的等价隔离判定。
2. **回收协议缺少单一入口**：旧 `recover-unit` 只接受 `QUARANTINED`，租约到期的 `LEASED` 只能先经 `acquire()` 隔离。当前实现已合并为幂等入口，自动测试覆盖直接回收过期 `LEASED`。

**历史实际回收记录**：旧实现曾以 Profile `flock` 和 `Singleton*` 独立证据完成两步回收并留下审计；本轮未使用新实现操作真实开发单元。

> 2026-09-29 修复：上述 `/bin/ps` 与两步回收缺陷已由 SESSION-01 实施解决。`confirm_local_browser_stopped` 现使用项目 profile `flock` + Chromium `SingletonLock` PID；陈旧 PID 不再误判为活进程。`recover-unit` 可直接处理租约已过期的 `LEASED` 或已隔离的 `QUARANTINED`，并回到 `SESSION_UNVERIFIED`，不把 Worker 中断伪装成平台登出。合成集成/单元测试已通过，真实单元本轮未执行回收。

**本轮已验收状态不变**：UNIT-01 仍为"待验收"；未执行真实两段式免登录端到端验收。
