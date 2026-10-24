# 开发与运维说明（F04/F05 交付）

> 编写日期：2026-09-26。适用对象：本项目的开发、测试与运维。
> 业务契约以[完整技术方案](AI达人智能发现与采集系统-完整技术方案.md)为准；工程流程以[Agent 开发规范](agent.md)为准。本文只描述**当前实际可用**的环境、命令与门槛，不把计划能力写成已实现能力。

2026-10-10 M3 补充：产品后端、迁移、认证、可靠提交、LangGraph P1、任务/结果 API 已实现，详见 [M3 后端证据](evidence/M3-backend-implementation-2026-10-10.md) 和 [DEC-014](decisions/DEC-014-m3-product-application-and-intake.md)。同日后续恢复 Lazyweb 本地 MCP，完成 React + TypeScript + Vite 登录、动态表单、任务中心、达人快照与双精选集合页面，详见 [M3 产品前端证据](evidence/M3-product-frontend-2026-10-10.md)。随后在真实开发库、真实 DeepSeek、Temporal、现有执行单元和真实 Chromium 上完成关键词目标 2 的产品闭环：2 位发布快照、两组精选 14 张卡片与 14 个封面可查询，两媒介共享及退出/重登恢复通过；详见 [M3 真实产品闭环证据](evidence/M3-real-product-acceptance-2026-10-10.md)。INTAKE-01、CONSOLE-01 已完成；APP-01 仅剩本轮明确不执行的生产 HTTPS/域名/Secure Cookie 环境验收。

2026-09-27 真实采集补充：本地阶段已完成**真实登录 + 真实搜索 + 2 位达人主页采集并落库核对**（[证据](evidence/UNIT-01-real-collection-2026-09-27.md)）；平台契约 `contracts/douyin_xingtu.verified.json` 已发布。仍属部分核验：只登记 `basic` 模块、分页仅开放到已验证页 2（`next_page_mode=page_fetch`、`page_fetch_max_verified=2`）、未登记筛选枚举与访问节奏；生产线路未验证。2026-09-28 补充：该真实链路已在不关闭浏览器的有界宿主内再次跑通（[证据](evidence/AUTO-01-bounded-host-real-run-2026-09-28.md)）。

2026-09-27 补充：最新实施顺序与状态见[项目任务进度总览](项目任务进度总览.md)。用户已确认设备和账号具备，优先本机IP + Chrome本地检索/采集验证。**本地开发网络模式（`network_mode=local_development`）、真实 Chrome 路径/版本探测、契约研究采集（`xingtu research`）、本地验证载体（`make smoke-local`），以及 F06 两组默认精选集合与受控封面存储（迁移 003、`CoverPipeline`、`xingtu cover-gc`）已实现并实测**；真实星图登录尚未完成（用户手机不在身边，无法接收验证码），因此真实契约（含两组精选集合）仍未登记。以下 2026-09-26 版本与测试事实保留为历史交付记录；F06 细节见 [F06 离线验证证据](evidence/F06-offline-verification.md)。

## 1. 当前实现范围

| 范围 | 状态 |
|---|---|
| P2-1 平台筛选、搜索与候选发现（F04） | 已实现（离线可验证；真实平台路径见 §7） |
| 达人主页资料采集（F05） | 已实现（离线可验证；真实字段字典见 §7） |
| 执行单元、租约、线路/Profile 隔离（UNIT-01 的代码部分） | 已实现（真实线路实测见 §7） |
| 显式本地开发网络模式、真实 Chrome 固定与兼容性探测、契约研究采集、本地验证载体 | 已实现并实测（仅 `local_development` 单元可用；见 §3、§4、§7） |
| 工程基础：迁移、幂等、检查点、Temporal 编排、证据存储、命令入口（BASE-01） | 已实现 |
| F01/F02/F07/F08 的产品 API 与前端 | 产品 API、React 前端及本地真实产品任务已验收；仅 F01 生产 HTTPS 环境项待验收 |
| P1 需求转换（F03） | LangGraph + DeepSeek Adapter 已通过真实 DeepSeek、model_runs 追溯和 P1→P2 同根任务验收 |
| 主页精选作品采集与封面存储（F06） | 已实现（离线可验证；真实集合边界与封面来源见 §7）。未注册两组集合时任务仍为 `PARTIAL_COMPLETED`（未登记模块或集合时收尾原因为 `PROFILE_SCOPE_INCOMPLETE`，`featured_status=NOT_ATTEMPTED`），F05+F06 全部完成且达到目标时为 `COMPLETED` |
| F09/F10/F11 的远程浏览器维护与代理池运维 | 部分实现（单元状态、维护锁、租约），真实硬件与远程承载未验证 |

当前可运行的入口是内部验收 CLI `xingtu`，它**不绕过**产品 P1 提交契约：`start` 只接受已经通过能力校验的 `FilterPlan`。

## 2. 环境与版本

| 组件 | 本轮验证版本 | 说明 |
|---|---|---|
| Python | 3.13.5（`.venv`） | `pyproject.toml` 限定 `>=3.13,<3.14` |
| 依赖管理 | uv（`.bootstrap/bin/uv`），`uv.lock` | `make setup` 使用 `--frozen` |
| PostgreSQL | 18.3（本地独立实例） | 业务库；测试库名必须以 `xingtu_test` 开头 |
| Temporal | Python SDK 1.33.0 本地测试服务器 / 服务端 `1.28.1`（Compose） | 工作流与 Activity |
| Chromium | Playwright `chromium-1243`（`.runtime/browsers`） | 契约测试与采集 |
| 本机 Chrome | 154.0.8037.57（`/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`），Playwright 1.63.0 启动兼容性已实测 | 本地开发单元的真实浏览器；`xingtu browser-check` 复核 |
| Temporal 本地测试服务器 | v1.9.1（`.runtime/temporal-test`） | `make smoke-local` / E2E；因 Docker 不可用而替代 Compose Temporal |
| 对象存储 | MinIO（Compose）/ 本地文件实现 | 脱敏证据；本地实现用于离线验证 |
| Docker Compose | v2.40.3-desktop.1 | `deploy/compose.yaml` |

## 3. 命令

命令契约与边界见[规范第 3.1 节](agent.md)。以下为实际命令与前置条件：

| 命令 | 前置条件 | 副作用 |
|---|---|---|
| `make help` | 无 | 无 |
| `make setup` | 网络、uv、Node.js/npm | 安装锁定 Python/前端依赖、Chromium、生成 `.runtime/development.env`（随机密码，不打印） |
| `make dev` / `make stop` | Docker、`.runtime/development.env` | 启动/停止依赖服务；不启动真实采集 |
| `make m3-check` | 无（只读） | 前置自检：环境文件、DB/迁移、Temporal、注册表、执行单元、模型凭据与模型可用性；不启动进程 |
| `make m3-up [M3_UP_FLAGS="--with-collection --with-frontend"]` | 同上；模型凭据就绪 | 启动 API + Intake Worker（可选 P2 Worker 与前端），门禁通过后保持前台监督；Ctrl-C 一并停止 |
| `python scripts/m3_up.py --status --with-collection --unit-config <file>` | 同上 | macOS/Windows 通用只读状态入口；Windows 不依赖 bash/lsof/pgrep。配置、启动、停止与 F10 本机接管见[本机运行手册](F10-local-macos-windows.md) |
| `make api` | 已迁移业务库；`XINGTU_DATABASE_URL`、Redis、登录 HMAC、允许 Origin 等 M3 环境变量 | 启动 FastAPI 产品 API；自动加载 `.runtime/m3-app.env`；不会自动创建任务 |
| `make intake-worker UNIT_CONFIG=<file>` | 产品 API 环境、Temporal、live 注册表、有效执行单元和 `DEEPSEEK_API_KEY` | 校验模型后消费 `intake_dispatches`；成功才派发现有 P2 |
| `make collection-worker UNIT_CONFIG=<file>` | 同上 + 真实浏览器与采集授权 | 消费 `xingtu-<unit>` 队列并执行 F04/F05/F06 采集；也执行手动/定时更新任务 |
| `make update-scheduler [UNIT_CONFIG=<file>] [BATCH_SIZE=5]` | 已迁移业务库、live 注册表、执行单元；不需要模型密钥或浏览器 | 按粉丝档位生成 `scheduled_update` 批次任务；不运行则定时更新暂停，正常采集与手动更新不受影响 |
| `make frontend-dev` | 已执行 `make frontend-install`；本地 API 默认在 `127.0.0.1:8000` | 启动 Vite 界面并同源代理 `/api` |
| `make frontend-build` | Node.js/npm | TypeScript strict 检查并生成 `frontend/dist/` |
| `make test-product-e2e` | 前端依赖与 Chromium | 真实 Chromium + 合成 API 验证登录、提交、进度和结果；不访问平台 |
| `make lint` / `make format-check` / `make typecheck` | 无 | 只读检查（ruff、ruff format、mypy strict） |
| `make test-unit` | 无 | 纯逻辑与领域规则，无外部服务 |
| `make test-contract` | 已安装 Chromium | 合成路由来源上的适配器/观察器契约，无平台流量 |
| `make test-integration` | `XINGTU_TEST_DATABASE_URL` 指向 `xingtu_test*` 库 | 建临时 schema 并在结束时删除 |
| `make test-e2e` | `XINGTU_TEST_DATABASE_URL`、本地 Temporal 测试服务器 | 启动测试服务器与 Worker；不访问平台 |
| `make check` | 已安装 Python 与前端锁定依赖 | 后端 `lint/format/typecheck/unit` + 前端 TypeScript/组件测试/生产构建 |
| `make migrate ENVIRONMENT=development\|test` | `XINGTU_DATABASE_URL` | 修改业务库，环境不明拒绝执行 |
| `make smoke-live` | `UNIT_CONFIG`、`PLAN`、`ACTOR`、`IDEMPOTENCY_KEY`，且 `target_count` ≤ 3 | 真实账号采集，需人工显式运行 |
| `make smoke-local` | `UNIT_CONFIG`、`ROOT_TASK_ID`、`XINGTU_DATABASE_URL`；Temporal 本地测试服务器 | 本地阶段验证载体：真实 `Activities.collect` + `CollectionWorkflow`，一次性等待终态。**不是生产编排** |
| `xingtu browser-check --config <unit.json>` | 单元配置 | 真实启动一次配置的浏览器，记录路径/版本/UA/兼容性；不访问平台 |
| `xingtu production-preflight --config <unit.json>` | `network_mode=production_line` + 有效线路证明/探针 + live 注册表 | 生产入口显式检查；**本地开发单元一律拒绝** |
| `xingtu research --config <unit.json> ...` | 仅 `network_mode=local_development`，主机须在 `research_allowed_hosts` 内 | 开发期契约研究采集：打开真实页面、等待人工登录、记录结构（不记录头部/Cookie/令牌/响应正文）；原始件写入 `.runtime/research/` |
| `xingtu rebind-account --config <unit.json> --account-id <ID: ...> --actor <actor> --reason <原因>` | `XINGTU_DATABASE_URL`；单元 JSON 的 `expected_account_id` 必须已改为同一身份；单元当前无浏览器宿主（`owner` 为空且 `browser_stopped=true`） | **显式审计改绑**：写入 `unit_account_rebindings` 与 `audit_logs`，并把单元置为 `SESSION_UNVERIFIED` 要求重新验证。可选 `--previous-account-id`（旧绑定只存在于配置文件、未落库时）与 `--evidence-ref`。自动化路径（`register-unit`、`ACCOUNT_MISMATCH`）仍不得改绑 |
| `xingtu cover-gc --config <unit.json>` | `XINGTU_DATABASE_URL`；`covers` 配置（默认 `local`，目录在运行根内） | 删除没有任何卡片引用的封面对象并解除登记；已发布快照引用的封面保留 |

`make smoke-live` 只校验目标数量并调用 `xingtu start`；它不会绕过注册表的 `VERIFIED`/live 证据门槛（见 §5）。

## 4. 配置

环境变量：

| 变量 | 用途 |
|---|---|
| `XINGTU_DATABASE_URL` | 业务库 DSN；未设置时 `xingtu` 命令返回 `STORAGE_UNAVAILABLE` |
| `XINGTU_TEST_DATABASE_URL` | 集成/E2E 测试库 DSN；库名必须匹配 `xingtu_test*` |
| `XINGTU_TEMPORAL_ADDRESS` | Temporal 地址，默认 `127.0.0.1:57233` |
| `XINGTU_TEMPORAL_TEST_BINARY` | 固定本地测试服务器可执行文件，避免测试期下载 |
| `PLAYWRIGHT_BROWSERS_PATH` | Chromium 安装目录，由 Makefile 固定为 `.runtime/browsers` |
| `UNIT_CONFIG` / `PLAN` / `ACTOR` / `IDEMPOTENCY_KEY` | 仅 `make smoke-live` 使用 |
| `XINGTU_REDIS_URL` | 产品登录双维度限流；不可用时登录失败关闭 |
| `XINGTU_LOGIN_HMAC_KEY` | 登录账号限流键 HMAC，至少 32 字节；不得提交到仓库 |
| `XINGTU_ALLOWED_ORIGINS` | 允许执行登录及写操作的精确 Origin，逗号分隔 |
| `XINGTU_SECURE_COOKIE` | 生产默认为 `1`；仅 localhost HTTP 开发时可显式设为 `0` |
| `DEEPSEEK_API_KEY` / `XINGTU_DEEPSEEK_MODEL` / `XINGTU_DEEPSEEK_BASE_URL` | Intake Worker 的模型凭据与配置；真实启动时先查询模型列表。默认值即官方契约：`deepseek-flash` + `https://api.deepseek.com`（2026-10-11 实测 `GET /models` 返回 `deepseek-flash`、`deepseek-v4-pro`）。凭据建议放在被忽略的 `.runtime/deepseek.env`（0600），由 `make m3-up`/`make intake-worker` 自动加载，不写入仓库 |
| `no_proxy` / `NO_PROXY` | httpx 0.28 无法解析方括号 IPv6 项（`[::1]`），会直接抛 `InvalidURL`，使真实模型调用与 `make m3-check` 失败。`scripts/m3_up.py` 会自动移除该形式并保留 `::1`；手工启动 Worker 时需自行确认 |
| `XINGTU_PROMPT_VERSION` | 写入 P1 状态与 `model_runs` 的 Prompt 版本 |
| `XINGTU_COVER_KIND` / `XINGTU_COVER_DIRECTORY` | 产品封面读取后端；本地目录必须位于 `XINGTU_RUNTIME_ROOT` |

执行单元配置（`xingtu register-unit|login|worker|start|browser-check|research --config`）为 JSON，字段见 `UnitConfig`：

- 通用必填：`unit_id`、`account_ref`、`expected_account_id`、`line_id`、`profile_directory`、`registry_path`、`network_mode`。
- `network_mode` 默认 `production_line`（缺省即最严格），二选一：
  - `production_line`：另需 `proxy_server`、`network_evidence_path`、`network_probe_command`；`ensure_line` 校验线路证明与探针新鲜度。
  - `local_development`：**禁止**出现 `proxy_server`、`network_evidence_path`、`network_probe_command`；用本机出口与项目独立 profile，供本地验证。系统不产生任何 `NetworkProof`，也不因本地通过而改变生产门槛。
- 浏览器固定（本地模式建议显式配置）：`browser_executable_path`（本机 Chrome 可执行文件）或 `browser_channel`，二者互斥。
- `research_allowed_hosts`：`xingtu research` 允许打开的主机白名单（非空才能使用该命令）。
- `proxy_username_env` / `proxy_password_env`：凭据只经环境变量引用，不写入配置或日志。
- `budget`：`SegmentBudget`，默认取附录 A——`active_seconds=7200`、`candidate_scan_floor=200`、`candidate_scan_multiplier=5`（`candidate_scan = max(200, 5 × target_count)`）。该值即 `ExecutionContext.budget` 引用，是保护阀而非完成时限。
- `evidence`：`EvidenceConfig`，`kind` 为 `local`（默认，写入 `.runtime/evidence`）或 `s3`（需 `endpoint`、`bucket`）。`local` 目录必须位于运行根目录内。
- `covers`：`CoverConfig`，F06 封面对象存储，`kind` 为 `local`（默认，写入 `.runtime/covers`）或 `s3`（需 `endpoint`、`bucket`）。对象写入后读回校验，未引用对象由 `xingtu cover-gc` 清理；封面默认随业务快照长期保留。
- `headless`：默认 `false`（人工维护与可视核验）。
- `block_service_workers`：默认 `false`，即允许平台的 Service Worker（§13.4「浏览器正常运行平台脚本」）；仅在确认需要限制后台流量时改为 `true`（实测与登出无关）。
- `browser_executable_path` / `browser_channel`：本地模式固定真实浏览器；`research_allowed_hosts` 为 `xingtu research` 的主机白名单。
- 注册表 `session_boot_timeout_seconds`（默认 120）：会话入口 SSO→应用壳握手的有界等待；`search.single_page_only` / `homepage_template` / `binding_values` / `fixed_sort` 见[契约登记说明](../contracts/README.md)。

配置文件必须为 `0600`、profile 目录必须位于项目私有根目录内，否则拒绝启动（`PRIVATE_FILE_PERMISSIONS_REQUIRED` / `PROFILE_OUTSIDE_PROJECT_PRIVATE_ROOT`）。网络模式在数据库中不可变（`execution_units.network_mode`，迁移 002）：更改模式必须使用新的执行单元。

## 5. 启用门槛

平台配置（`contracts/*.json`，`PlatformRegistry`）只有同时满足以下条件才可发布：

1. `status=VERIFIED`，且 `session`、`search` 均存在。
2. `allowed_hosts`、`homepage_path_prefixes`、`action_interval_seconds`、`operation_timeout_seconds`、`response_body_max_bytes` 全部已填。
3. **live 运行**额外要求 `sample_kind=live`、`verified_at`、`account_permission_type` 和非空 `evidence_refs`；合成样本永远不能通过 live 门槛。
4. 引用完整性校验（`_validate_references`）：请求键唯一且主机在范围内、字段来源引用的请求必须已声明、`fallback` 必须声明 `fallback_on`、报价/分布/数值字段的单位与语义必须完整、模块缺失证据取值不得歧义、`entry` 与入口 URL 必须在平台主机范围内、业务错误码必须属于附录 B。
5. 能力字典 `status=VERIFIED` 且版本与 `FilterPlan.capability_version` 一致；`combinations` 必须显式列出允许的组合。

旧 `contract_health.disabled` 仍作为全局人工覆盖；它不会再因单次 `PLATFORM_PAGE_CHANGED` 自动置位。运行时按 `session`、`search`、`profile_identity`、`profile_module:<key>`、`featured:<key>` 维护 capability scope：单主体失败不熔断，三个不同主体连续失败进入 `SUSPECTED`，新浏览器租约中第四个不同主体复现后仅禁用对应 scope。修复并验证后使用 `xingtu enable-contract --registry <file> --scope <scope> --reason <reason> --actor <actor>` 审计恢复。可恢复游标失效不会进入该计数。

`contracts/douyin_xingtu.unverified.json` 是**未核验模板**：`session`/`search` 为 `null`、`modules` 为空，`require_enabled` 必然失败。这是预期行为，不得为通过门槛而填入推测的选择器或接口。

## 6. 存储与证据保留

- 业务数据、检查点、幂等事实与租约在 PostgreSQL；Redis 仅用于可重建缓存与限流（本轮未启用缓存）。
- 脱敏证据（搜索耗尽摘要、任务级失败、模块级失败）写入对象存储或本地实现，并在 `raw_evidence` 登记校验和与到期时间：失败证据 30 天、必要摘要 90 天。
- 证据内容为允许列表结构（根任务/子任务/尝试、操作 ID、契约版本、结构键、失败原因），**不含**请求正文、URL、Cookie、令牌或页面文本。
- 业务快照（`creator_snapshots`）不可修改（数据库触发器保证），默认持续保留。

## 7. 未完成的实机核验（不得视为已通过）

| 空缺 | 未核验内容 | 影响 |
|---|---|---|
| U02 | 内容关键词模式已核验（内容找人、`search_param.keyword`、回读一致）；筛选枚举、报价形式/单位与组合仍未核验 | F04 可执行关键词小样本；筛选项相关验收未勾选 |
| U04 | 首页搜索（`authors[]`/`star_id`/`pagination.has_more`）与 `basic` 模块字段来源已核验；**分页推进、其余主页模块、默认统计口径与访问节奏未核验** | F05 仅 `basic` 部分核验；分页与其余模块验收未勾选 |
| U05 | 两个精选集合的边界、稳定键、加载终点、标题/副标题/链接/封面来源（契约与 Adapter 已实现，注册表 `featured=[]` 待登记） | F06 无法真实执行；注册表保持 `[]` |
| U06 | 账号识别与受保护页面已真实核验（`xingtu login` → `READY`/session_version++）；**远程浏览器承载仍未实现** | F10 远程维护入口未验证 |
| U07/U08 | J1900/蜂窝模块/SIM、OpenWrt、代理端点、DNS 与断线隔离、旧进程停止机制 | UNIT-01 实机核验阻塞 |
| U09 | 对象存储服务、图片上限/CDN 白名单、备份介质与告警通道 | 封面本地实现与孤儿清理已实测；S3/MinIO 与认证图片访问未验证 |

另外，执行单元 Activity（`Activities.collect`）的 live 门槛**故意不可绕过**，因此其端到端验证必须使用已核验注册表与真实账号/线路，不能用合成样本替代。2026-09-27 已用 `make smoke-local` 在 Temporal 本地测试服务器上运行真实 `Activities.collect`，对未核验注册表取得终态 `FAILED`（`PLATFORM_PAGE_CHANGED: UNVERIFIED_REGISTRY`），证明门槛未被本地模式削弱。**正向真实采集已执行**：2026-09-27（`xingtu login` + `xingtu start` + `make smoke-local`）与 2026-09-28（有界宿主同一上下文交接）各完成一次关键词搜索 + 2 位达人 `basic` 落库；仍未验证的是经 Temporal 幂等唤醒的原任务续跑、其余主页模块与实际生产线路。

## 8. 相关文档

- [Agent 开发规范](agent.md)
- [技术方案](AI达人智能发现与采集系统-完整技术方案.md)
- [平台契约登记说明](../contracts/README.md)
- [本轮验证证据](evidence/F04-F05-offline-verification.md)
- [决策记录](decisions/)
- [任务卡片](tasks/README.md)

## 2026-09-28 AUTO-01 行为变更

- `xingtu start` 默认读取 `contracts/profile_requirements.json`；可通过 `--requirements` 指定经过审查的业务范围版本。当前默认清单尚需实机盘点（`inventory_verified=false`），完整度明确为未完成：只采到 `basic` 时任务以 `PARTIAL_COMPLETED`／`PROFILE_SCOPE_INCOMPLETE` 收尾，不会把 basic 当成完整主页。
- `xingtu status` 增加停止原因、字段覆盖、操作匹配请求/响应计数、模块耗时及失败分类。计数不包含页面全部请求，不能据此推算平台权益用量。
- `xingtu login` 不再自行开关浏览器：它登记幂等维护意图（`request_login_maintenance`）并由 Worker 打开有界 Chrome；人在该 Chrome 内用短信／账号密码入口登录。**有界浏览器宿主（迁移 005）**：每执行单元一个宿主，持有租约、profile 锁与 `BrowserContext`，维护与采集使用**同一上下文和同一个已校验 Page**，浏览器对象不跨进程传递；登录核验通过后由 `Repository.promote_maintenance_to_collect` 单事务、带 fencing、可审计地从 `maintenance` 切到 `collect` 并递增 `session_version`；当 Activity 本身已在运行时，promote 后直接续跑，不额外给自己发 wake；挑战时反向切回维护；`WAITING_FOR_LOGIN`/`WAITING_FOR_ACCOUNT` 只因新的显式 `xingtu login` 请求被唤醒，不定时重启 Chrome。2026-09-28 已在真实账号上通过同上下文交接与真实采集；任务结束后的最终释放语义已由下方 2026-09-29 状态机取代。
- 迁移 005（`migrations/005_bounded_browser_host.sql`）新增宿主所有权与生命周期列：`expected_account_id`、`verified_account_id`、`current_root_task_id`、`maintenance_deadline`、`idle_deadline`。
- 历史任务兼容：JSON 载荷新增字段均有兼容默认值。未带需求清单的历史任务保留原注册范围语义，历史快照不改写；Workflow 定义未改动，现有重放用例通过。
- pytest 默认 `--import-mode=importlib`，使不同目录同名测试可同时收集。2026-09-28 的 **166 项**是历史基线；2026-09-29 结构性修复后的当前结果见下节和实施证据。已删除能够绕开原子交接单独递增 `session_version` 的旧入口；重复维护确认在已有 maintenance 宿主时幂等复用原所有权。
- 2026-09-28 的“关闭后必须回到 `NEEDS_LOGIN`”是历史观测，不再是当前规则；参见 [DEC-013](decisions/DEC-013-structured-session-and-scoped-contract-health.md)。

## 2026-09-29 SESSION-01 / AUTO-01 行为变更

- 迁移 006 新增结构化会话观测与按能力范围的 Contract 健康表。迁移只新增，不删除旧列或历史数据；旧 `contract_health.disabled` 仍是全局人工覆盖。
- 新 Chrome 进程不能继承旧 `READY` 的“已验证”结论。Adapter 必须在当前上下文得到受保护页、账号一致、无登录/挑战的正证据，BrowserHost 才以 `VERIFIED_READY` 释放回 `READY`。
- 会话结果分为 `VALID`、`LOGIN_REQUIRED`、`ACCOUNT_MISMATCH`、`SECURITY_CHALLENGE`、`INDETERMINATE`；ExecutionUnit 对应支持 `ACCOUNT_MISMATCH`、`SESSION_UNVERIFIED`，根任务支持 `WAITING_FOR_ACCOUNT`。正常关浏览器、Worker/服务重启不是登录失效证据。
- `IDENTITY_UNREADABLE` 在达人级重建详情页并最多尝试 3 次；仍失败记录该候选并继续补位。只有不同主体连续复现且跨新浏览器租约确认后才禁用相应 Contract scope，不再单次禁用整版本。
- scoped Contract 健康默认启用；紧急回滚可设置 `XINGTU_SCOPED_CONTRACT_HEALTH=false`，此时不读取或推进 scope 状态，旧 `contract_health.disabled` 全局人工覆盖仍生效。该开关只用于回滚，不会自动清除已有 scope 记录。
- `xingtu recover-unit` 可直接回收已过期的 `LEASED` 或 `QUARANTINED` 单元；隔离判断使用项目 `flock` + Chromium `SingletonLock` PID，不再依赖 `/bin/ps`。回收后为 `SESSION_UNVERIFIED`，下次运行必须实测 Session。
- Collection Worker 启动时也会对 `QUARANTINED` 单元执行一次同样的本地隔离证明与回收：仅当无活跃租约/验证事件/接管且证明通过时调用 `recover_stopped_unit()`，actor 为 `collection-worker:<instance>` 并写 `audit_logs`；证明失败保持隔离。手工 `recover-unit` 仍保留。
- `xingtu session-diagnostics --config ...` 要求本机环境变量 `XINGTU_DIAGNOSTIC_HMAC_KEY`（至少 32 字节），在 `.runtime/session-diagnostics/` 写 `0600` 报告。Cookie/Storage 值只保存 HMAC，不打印明文；该命令会真实冷启动并访问注册表中的受保护入口，不属于离线检查。
- 真实单账号清理、5/10/20 位平台任务与 30 天分阶段长测尚未执行；代码通过不等于这些验收已通过。

## 2026-10-11 M3 完整运行链路启动（当前推荐方式）

2026-10-11 诊断确认：产品任务只在**常驻 Intake Worker** 消费 `intake_dispatches` 时才会离开 `RECEIVED`。此前该进程不在任何编排目标与启动步骤中，也没有任何失败面，因此“按文档启动 API+前端”提交任务后会永久停在 `RECEIVED`。现在由单一入口负责启动、前置自检与就绪门禁：

```bash
# 依赖服务（PostgreSQL 55432、Redis 56379、MinIO 59000/59001、Temporal 57233）
make dev

# 只读前置自检：环境文件、DB、迁移、Temporal、注册表、执行单元、模型凭据与模型可用性
make m3-check

# 启动 API + Intake Worker，并在出现“新鲜消费者”后才宣告 READY（前台运行，Ctrl-C 一并停止）
make m3-up
# 需要真实采集时追加（会打开真实 Chrome，须先取得采集授权）：
#   make m3-up M3_UP_FLAGS="--with-collection --with-frontend"
```

前置自检覆盖的检查项（任一失败即拒绝启动并给出稳定代号）：

| 检查 | 说明 |
|---|---|
| `M3_ENV_FILE` / `MODEL_ENV_FILE` | `.runtime/m3-app.env` 必需；`.runtime/deepseek.env`（模型凭据，0600、被 gitignore）可选 |
| `NO_PROXY_SANITISED` | 本机 `no_proxy` 含 `[::1]`，httpx 0.28 会以 `InvalidURL: Invalid port: ':1]'` 直接失败；启动器移除方括号 IPv6 项（`::1` 仍在），否则真实模型调用无法发出 |
| `DATABASE_REACHABLE` / `MIGRATIONS_APPLIED` | 连接业务库并比对 `schema_migrations` 与 `migrations/*.sql` |
| `TEMPORAL_REACHABLE` | 连接 `XINGTU_TEMPORAL_ADDRESS` |
| `REGISTRY_VERIFIED_LIVE` | 注册表 `require_enabled(live=True)` |
| `UNIT_CONFIG` / `EXECUTION_UNIT_REGISTERED` / `EXECUTION_UNIT_READY` | 单元 JSON 可解析，且 `execution_units` 行存在并 `READY`（否则 `promote_intake` 会失败） |
| `DEEPSEEK_API_KEY` / `MODEL_AVAILABLE` | 凭据存在，且 `GET {base_url}/models` 返回该模型（当前官方名称即 `deepseek-flash`） |

就绪门禁使用**消费者新鲜度**而不是 poller 计数：

- `DescribeTaskQueue` 的 poller 列表是 TTL 的：worker 停止后条目仍会保留数分钟（实测 > 2 分钟）。
- 更关键的是，**健康** worker 的 `last_access_time` 也会滞后：长轮询持有请求，实测刷新间隔为 58 s、58 s、**121 s**。因此 `worker_health.DEFAULT_FRESHNESS_SECONDS = 180`，用 10 s 之类的阈值会把正常 worker 判成“不在线”。

### 任务为何仍在 RECEIVED：`GET /api/tasks/{id}` 的 `intake` 字段

`TaskDetail.intake` 只在任务处于 `RECEIVED`/`PARSING` 时返回，用于区分三种情况（前两种会在页面上显示阻塞说明）：

| 情形 | 判据 | `blocked_reason` |
|---|---|---|
| 正常派发窗口 | `sent=false` 且等待 < 120 s | 无 |
| 没有消费者 | `sent=false` 且等待 ≥ 120 s，且无派发失败记录 | `INTAKE_WORKER_UNAVAILABLE` |
| 派发持续失败 | `audit_logs` 存在 `product_intake.dispatch_failed:*` | `INTAKE_DISPATCH_FAILING` |

判定**不依赖**粗粒度的 poller 信号：正常派发循环会在约 2 s 内置 `sent=true`，因此“等待数分钟仍未派发且没有失败记录”本身即结论。`consumer_alive`（poller 新鲜度，三态，`null` 表示无法观测）仅作为诊断信息与 `GET /api/health/workers` 一并返回。

要点：

- `XINGTU_ALLOWED_ORIGINS` 必须包含实际访问来源（如 `http://127.0.0.1:5173`、`http://localhost:5173`），否则登录与写操作因 Origin 校验返回 403。
- `XINGTU_SECURE_COOKIE=0` 只在本地 HTTP 开发可显式设置；生产保持默认 `1`。
- **两个 Worker 都必须运行**：`make intake-worker`（P1 需求转换，队列 `xingtu-intake`）与 `make collection-worker`（P2 采集，队列 `xingtu-<unit>`）。缺 P1 会停在 `RECEIVED`，缺 P2 会停在 `QUEUED`。`make m3-up` 默认只启动 P1，采集需显式 `--with-collection`。
- 未提供模型凭据时 `make m3-up` 会在前置自检阶段失败（`DEEPSEEK_API_KEY`），不会留下一个“看起来已启动但无人消费”的运行环境。
- 未登录访问业务 API 与封面返回 401，跨任务读取封面返回 404，均为预期保护行为。
- **后端代码变更后必须重启 `xingtu-api`**（该入口无 `--reload`）。长期运行的旧进程持有旧 Pydantic 模型：新代码写入带新字段的检查点后（例如安全验证的 `challenge_*` 字段），旧进程读取该任务会因 `TaskRecord`/`checkpoint` 的 `extra_forbidden` 返回 500，而更早的任务仍正常。2026-10-10 本地联调中实际出现，重启为当前代码后同一任务恢复 200。
- 同一端口只保留一个 API 进程：重复启动会以 `[Errno 48] address already in use` 退出（退出码 3）。先确认占用者（`lsof -nP -iTCP:8000 -sTCP:LISTEN`），不要并跑两个后端。`make m3-up` 会复用已在 8000 上通过 healthcheck 的 API 进程。
- Worker 进程日志写入 `.runtime/logs/`（`api.log`、`intake-worker.log`、`collection-worker.log`、`update-scheduler.log`、`frontend.log`）；Intake Worker 启动与派发失败都会记录，消费者不再可能“静默消失”。`update-scheduler` 只读写数据库，不运行只影响定时更新。

## 2026-10-10 M3 本地产品页面启动（历史记录）

2026-10-10 的启动顺序（真实开发库 + 真实 Chromium，证据见 [M3 本地控制台启动联调](evidence/M3-local-console-startup-2026-10-10.md)）。该顺序**缺少两个 Worker**，与上文 2026-10-11 事故直接相关，保留为历史记录：

```bash
# 依赖服务（PostgreSQL 55432、Redis 56379、MinIO 59000/59001、Temporal 57233）
make dev

# 私有运行环境（0600，位于被忽略的 .runtime/；含 DSN、Redis、随机登录 HMAC、允许 Origin、
# XINGTU_SECURE_COOKIE=0 仅用于 localhost HTTP、运行根/封面目录、注册表与 API 监听地址）
set -a; . ./.runtime/m3-app.env; set +a

# 业务库迁移（先备份开发库再执行；迁移为追加）
.venv/bin/xingtu migrate --environment development

# 本地开发用户（仅首次；口令交互输入，不写入仓库）
.venv/bin/xingtu-product create-user --username media-a --display-name "媒介 A" --actor bootstrap

# 后端产品 API（前台运行；healthcheck 可用 GET /api/auth/me 期待 401）
.venv/bin/xingtu-api                 # http://127.0.0.1:8000

# 前端页面（另一个终端；Vite 将 /api 代理到 127.0.0.1:8000）
npm --prefix frontend run dev        # http://127.0.0.1:5173
```

要点：

- `XINGTU_ALLOWED_ORIGINS` 必须包含实际访问来源（如 `http://127.0.0.1:5173`、`http://localhost:5173`），否则登录与写操作因 Origin 校验返回 403。
- `XINGTU_SECURE_COOKIE=0` 只在本地 HTTP 开发可显式设置；生产保持默认 `1`。
- 未提供 `DEEPSEEK_API_KEY` 时 `.venv/bin/xingtu-product intake-worker` 会在校验阶段以 `DEEPSEEK_API_KEY_REQUIRED` 退出，页面提交的新任务不会离开 `RECEIVED`；真实采集 Worker（`xingtu worker --config <unit>`）需另行显式授权后运行。
- 未登录访问业务 API 与封面返回 401，跨任务读取封面返回 404，均为预期保护行为。
- **后端代码变更后必须重启 `xingtu-api`**（该入口无 `--reload`）。长期运行的旧进程持有旧 Pydantic 模型：新代码写入带新字段的检查点后（例如安全验证的 `challenge_*` 字段），旧进程读取该任务会因 `TaskRecord`/`checkpoint` 的 `extra_forbidden` 返回 500，而更早的任务仍正常。2026-10-10 本地联调中实际出现，重启为当前代码后同一任务恢复 200。
- 同一端口只保留一个 API 进程：重复启动会以 `[Errno 48] address already in use` 退出（退出码 3）。先确认占用者（`lsof -nP -iTCP:8000 -sTCP:LISTEN`），不要并跑两个后端。

## 2026-10-14 DEV-01：本机一键启停入口 `./dev.sh`

上面 `make m3-up` 的默认清单**不含前端**（需 `M3_UP_FLAGS="--with-collection --with-frontend"`），且它不记录 PID，停止后 API 与前端会成为游离进程。需要「在终端一条命令唤起前后端并打开页面体验」时改用根目录入口：

```bash
./dev.sh            # = ./dev.sh up：依赖 → 前置自检 → API + P1 + P2 + 更新调度器 + 前端 → 就绪校验
./dev.sh status     # 进程 / 端口 / HTTP / 队列消费者新鲜度 / 日志末行
./dev.sh logs [名称] # 名称：api | intake-worker | collection-worker | update-scheduler | frontend
./dev.sh stop       # 只停本脚本记录过的进程（连同 npm run dev 的子进程），保留数据库/对象/profile
./dev.sh restart    # stop + up
./dev.sh check      # 只做前置自检
```

行为边界：

- 实现为 [scripts/dev.sh](../scripts/dev.sh)，根目录 [dev.sh](../dev.sh) 只是转发；进程仍由既有入口启动，前置自检仍调用 `scripts/m3_up.py --check`，没有第二套真相，`Makefile` 未改动。
- 默认启动四个进程：API（`xingtu-api`）、P1 Intake Worker、P2 采集 Worker（`xingtu worker --config`）、前端（`npm run dev`）。缺 P1 任务停在 `RECEIVED`，缺 P2 停在 `QUEUED`，缺前端没有页面。
- **接管而非叠加**：已在监听的 API/前端与已在运行的 Worker 会被记录 PID 后复用；同一单元出现多个 Worker 时只保留一个并结束其余（重复 Intake 会重复派发，重复采集会在同一 profile 上互斥）。因此 `up` 可重复执行。
- Worker 通过 `pgrep -f` 与 `lsof -c Python -F p` 取交集识别；只看命令行字符串会把本脚本自身的 shell 误判成 worker。
- `stop` 递归结束子进程（`npm run dev` 的 Vite 是子进程，只 kill npm 会留下占用 5173 的孤儿），只处理本脚本记录过的 PID；端口被外部进程占用时打印占用者 PID 而不擅自 kill。
- 不启停 Docker 依赖服务；依赖未起时由前置自检的 `DATABASE_REACHABLE` / `TEMPORAL_REACHABLE` 报错。依赖停止仍用 `make stop`（或 `./.runtime/dev-up.sh stop`）。
- 采集 Worker 会打开真实 Chrome 并调用真实星图；`up` 默认包含它。页面地址 `http://127.0.0.1:5173/`，登录账号见 `.runtime/qa-credentials.env`（不写入仓库）。
- 验证记录（前置自检、完整停启、幂等接管、真实 Chrome 页面渲染）见 [DEV-01 证据](evidence/DEV-01-launcher-2026-10-14.md)与 [DEV-01 卡片](tasks/DEV-01.md)。
