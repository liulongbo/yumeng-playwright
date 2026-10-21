# LIVE-01：前端发起「户外 / 10 位」真实采集验收

状态：待验收  
更新时间：2026-10-21T18:20:00+08:00（Asia/Shanghai）  
是否验收：部分

## 目标与范围

使用已注册的原生 Playwright MCP 工具 + 本机真实 Chrome，从「星采」前端一次性提交内容关键词「户外」、目标达人数 `10`，持续观测 P1 需求转换、P2 真实巨量星图搜索/采集、持久化与前端结果展示，直到根任务进入真实终态。

包含：环境就绪检查、前端登录与单次提交、任务状态跟踪、前端/API/数据库一致性核对，以及为达成本次链路所必需的小范围修复与复测。

不包含：第二条真实采集任务、扩大到 20/200 位、变更业务口径、绕过平台验证/风控、轮换账号或代理、生产发布。

## 关联与依赖

- 前置：[SESSION-01](SESSION-01.md)、[DEV-01](DEV-01.md)、[INTAKE-01](INTAKE-01.md)。
- 功能：[F04](F04.md)、[F05](F05.md)、[F06](F06.md)、[CONSOLE-01](CONSOLE-01.md)。
- 环境：`unit-local-mac-02`，绑定账号 `ID: 1807978499337419`，`network_mode=local_development`，**单机原生 local-main 进程**（非 Mac+Linux 混合部署）。
- 用户授权：2026-10-21 明确授权从前端发起一次「户外 / 10 位」真实采集，并允许对范围内小问题修复。

## 验收清单

- [x] Playwright MCP + 真实 Chrome 登录星采前端，提交内容关键词「户外」、目标数 `10`，且只提交一次需求。实际任务 `b94d146b-98f5-41ee-8041-77f2b042d9d2`；后续两次是页面的「重试失败步骤」，没有创建新需求。
- [x] 任务经 `RECEIVED / PARSING / QUEUED / COLLECTING`（中间帧存在快速跳过）并最终进入真实终态；记录任务 ID、版本、时间线。观测到 `QUEUED → COLLECTING → WAITING_FOR_RESOURCE(LEASE_LOST) → 自动重试 QUEUED → COLLECTING → FAILED(504) → 重试 → PARTIAL_COMPLETED`；`RECEIVED/PARSING` 由 `root_tasks`、`intake_dispatches`、`model_runs` 与页面进度轨证明。
- [x] 终态为 `PARTIAL_COMPLETED`（非 `COMPLETED`）：`valid_count=10`、目标 10、10 位达人各有已发布快照；已记录终态原因 `PROFILE_SCOPE_INCOMPLETE`、已保留结果与可执行重试；未伪报完整。F05 资料完整 5/10、F06 双精选完整 9/10。
- [x] 核对 F05 模块完整度与 F06 两组精选集合/卡片/封面，未将缺失或失败伪报为完整：10 位达人 8 个模块均 `COLLECTED`；缺口为字段级 `MISSING_SOURCE/NO_DATA`；`featured_collections` 17 COMPLETE + 4 INCOMPLETE + 1 EMPTY，`featured_cards=76`，`media_objects=259`。
- [x] 前端可查看任务列表、详情、达人列表与至少一位达人详情；控制台无未解释的 JavaScript 错误（封面目录修复后 0 错误，9/9 图片加载）。
- [x] 修复：保留首次失败证据，实施最小改动（504 分类 + 封面运行配置），运行契约/单元回归并复测真实任务恢复路径。
- [x] 脱敏证据、本卡、任务索引与项目总览已同步；未提交/推送/合并。

## 实现记录

- 2026-10-21T17:33:23+08:00：通过 Playwright MCP + 真实 Chrome 以 `media-a` 登录前端，提交「户外 / 10 位」需求，获得根任务 `b94d146b-98f5-41ee-8041-77f2b042d9d2`。
- 17:33:27：首次 `FAILED`，原因 `CONTRACT_SCOPE_DISABLED:search`。定位为 17:19 之前 4 个非验收脚本计划（`keyword=户外` + `connection_users.connected.min=10`、`target_count=20`）触发 search scope breaker；保存恢复前快照后，用 `xingtu enable-contract --scope search` 带审计原因恢复。
- 17:34:53–17:35:18：通过页面「重试失败步骤」重试同一任务；`QUEUED → COLLECTING`，真实检索发现 20 位候选。
- 17:44:08–17:51:24：采集中途 lease 丢失（`WAITING_FOR_RESOURCE/LEASE_LOST`，7 位有效已保存），工作流自动重试并恢复到 `COLLECTING`。
- 17:58:04：平台 `spread` 请求返回 HTTP 504/HTML，被误判为 `PLATFORM_PAGE_CHANGED:RESPONSE_CONTENT_TYPE`，任务在 9 位有效后 `FAILED`；失败证据已保存。
- 17:59:39–18:05:41：修复 504 分类并重启采集 Worker 加载新代码后，通过页面再次「重试失败步骤」；任务补齐到 10 位有效，终态 `PARTIAL_COMPLETED` / `PROFILE_SCOPE_INCOMPLETE`。
- 18:07–18:09：修复 API 封面目录与 Worker 封面目录不一致（运行配置），重启 API；前端复测 9/9 图片加载、控制台 0 错误。
- 代码改动仅 1 处业务逻辑 + 1 个契约测试；运行配置改动 3 项（封面目录、Redis 密码、API/Worker 重启）。未改数据库 Schema、未删除/覆盖业务数据、未提交 Git。

## 验证证据

完整证据见 [LIVE-01 真实端到端验收证据](../evidence/LIVE-01-live-e2e-2026-10-21.md)。

- 任务：`b94d146b-98f5-41ee-8041-77f2b042d9d2`；终态 `PARTIAL_COMPLETED`，`valid_count=10/10`，`profile_complete_count=5`，`featured_complete_count=9`，`failure_reason=PROFILE_SCOPE_INCOMPLETE`，`version=1007`。
- P1：`model_runs=a6efe270-cbec-4801-9012-5731bf2717d0`，DeepSeek `deepseek-flash`，`succeeded`，`latency_ms=1038`；`filter_plans` 仅 `keyword=户外`、`target_count=10`，无额外筛选。
- 数据库：`task_creators=10`、已发布快照 `10`、`featured_collections` 17 COMPLETE/4 INCOMPLETE/1 EMPTY、`featured_cards=76`、`media_objects=259`、`raw_evidence` 1 条 504 失败证据；`contract_capability_health(v11,search)` 恢复为 `ENABLED`。
- 前端：任务详情 10 位达人、页面「资料完整 5 / 精选完整 9 / 失败步骤 0」；达人详情显示真实星图 ID、粉丝、月深度用户、内容数据、CPM/CPE、两组精选视频；`IMAGES_LOADED=9/9`、`CONSOLE_ERRORS=0`。
- 截图：[表单](../evidence/assets/LIVE-01-form-2026-10-21.png)、[采集中](../evidence/assets/LIVE-01-collecting-2026-10-21.png)、[首次失败](../evidence/assets/LIVE-01-first-failure-2026-10-21.png)、[504 失败](../evidence/assets/LIVE-01-failure-504-2026-10-21.png)、[最终任务](../evidence/assets/LIVE-01-task-final-2026-10-21.png)、[达人详情](../evidence/assets/LIVE-01-creator-final-2026-10-21.png)。
- 回归：`make test-unit` 303 passed；`make test-contract` 34 passed；`pytest backend/tests/contract/test_observer.py -q` 17 passed；`ruff`/`ruff format --check`/`mypy` 通过。
- 修复：
  1. `backend/src/xingtu/observer.py`：408/500/502/503/504 先于 content-type 检查，归类为 `MODULE_COLLECTION_FAILED:PLATFORM_HTTP_5XX`，避免整任务因网关错误终止；新增 `backend/tests/contract/test_observer.py::test_gateway_timeout_is_a_module_failure_not_a_contract_change`。
  2. `.runtime/local-main/env`（运行态，不入 Git）：`XINGTU_COVER_DIRECTORY` 对齐到 `.runtime/covers`；API 重启后封面 200、前端 0 错误。
- 运行环境：分支 `main` HEAD `ffd6b0b`；单机原生 local-main（API 8000 / 前端 5173 / PG 55432 / Redis 56379 / Temporal 57233）；Chrome `156.0.8078.47`；Playwright MCP `1.62.0-alpha-2026-06-29`。未使用混合部署或云端 Worker。

## 交接信息

- 当前状态：待验收（部分通过）。
- 未完成/遗留：
  1. 带 `connection_users` 等筛选条件的真实检索失败根因未确认、未修复（建议单独立项 + 一次受控小样本；在此之前不要声明该路径已验证）。
  2. 采集中途 lease 丢失根因未证实（已有自动恢复；建议心跳/长 I/O 可靠性优化）。
  3. F05 资料完整 5/10、F06 完整 9/10 为真实平台字段缺口；若要求 100% 完整，需按字段字典逐项校准。
  4. 重试后 `completed_at` 仍显示首次终态时间，属既有设计/UX 语义，待产品决定。
  5. `./dev.sh status` 与当前 local-main 运行栈不一致（旧 pid/日志路径），属运维工具缺口。
- 阻塞：无（本轮不依赖云端 Linux 主机）。

## 状态历史

- 2026-10-21T17:05:00+08:00：建立 → 进行中。用户明确要求 Playwright MCP + Chrome 从前端发起「户外 / 10 位」真实采集，并允许必要的小范围修复。
- 2026-10-21T18:20:00+08:00：进行中 → 待验收；是否验收：部分。真实闭环跑通并取得 10 位有效达人、10 个发布快照、前端展示与详情；终态为 `PARTIAL_COMPLETED`（`PROFILE_SCOPE_INCOMPLETE`，F05 5/10、F06 9/10），另修复 504 误判与封面目录不一致；筛选路径、lease 丢失等列为遗留，待用户决定是否接受条件通过。
