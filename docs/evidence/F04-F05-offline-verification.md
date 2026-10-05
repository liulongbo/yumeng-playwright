# F04/F05 离线验证证据

- 日期：2026-09-26T21:42～21:49+08:00（含 21:46、21:49 两次收尾校验）
- 执行人：AI 编程助手（本轮交付）
- 环境：macOS 26.5.2（darwin 24.6.0）；Python 3.13.5（`.venv`）；PostgreSQL 18.3（Homebrew 独立实例，`127.0.0.1:55439`，测试库 `xingtu_test_f04f05`，角色 `xingtu_test`）；Chromium `chromium-1243`（`PLAYWRIGHT_BROWSERS_PATH=.runtime/browsers`）；Temporal Python SDK 本地测试服务器 `1.33.0`；Docker Compose v2.40.3（**守护进程未运行**）。
- 契约/适配器版本：合成样本 `contract_version=adapter_version=synthetic-v1`（测试夹具，明确人工构造）；随包模板 `contracts/douyin_xingtu.unverified.json` 为 `xingtu-unverified-v1` + `browser-v1`，状态 `UNVERIFIED`。
- 原始命令记录：[F04-F05-offline-verification.log](F04-F05-offline-verification.log)

## 1. 静态检查

| 命令 | 结果 |
|---|---|
| `ruff check backend conftest.py tests scripts` | All checks passed |
| `ruff format --check backend conftest.py tests scripts` | 23 files already formatted |
| `mypy backend/src`（strict） | Success: no issues found in 13 source files |

## 2. 测试分层

| 命令 | 结果 | 覆盖重点 |
|---|---|---|
| `pytest backend/tests/unit -q` | **41 passed** | 领域校验（数量 1—200、区间、单位、语义）、数值/报价/比例标准化与近似语义、注册表发布门槛（1 项通过 + 21 项拒绝原因）、证据/耗尽需要证据 |
| `pytest backend/tests/contract -q` | **10 passed**（10.28s） | 观察器：旧条件响应拒绝、重复请求歧义、HTTP 200 登录 HTML、业务错误码、超时、响应体上限；适配器：真实 Chromium + 合成路由来源下的搜索/回读/详情页/模块级无权限/入口页/加载提示消失/无身份行诊断 |
| `pytest backend/tests/integration -q` | **22 passed**（101.84s） | 启动幂等与并发投递、事务回滚、租约过期隔离与迟到写入拒绝、快照不可变、已有达人重采与新快照、字段失败不清空投影、有序去重与无效补位、20/200 目标停止、零结果终点、扫描预算暂停与继续、崩溃后检查点复用、登录等待与取消围栏、条件不一致不提交、游标循环、游标失效重扫与首次位置保留、**中途游标失效重扫且不禁用契约**、**重扫经过已见身份不算契约失败**、**诊断持久化**、**检查点版本不兼容停止**、**执行上下文预算生效**、**证据写入与保留登记** |
| `pytest tests/e2e -q` | **1 passed**（1.21s，本地 Temporal 测试服务器） | 预算暂停 → Signal 唤醒 → 继续 → `PARTIAL_COMPLETED`，并做工作流历史重放校验 |

合计 **74 项测试通过**；失败退出码正常传播，无跳过或弱化断言。

## 3. 命令与门槛实测

| 命令 | 观察结果 |
|---|---|
| `make check` | ruff、ruff format、mypy、unit 全部通过（见 §1、§2） |
| `make test-contract` / `make test-integration` / `make test-e2e` | 10 / 22 / 1 passed |
| `make migrate ENVIRONMENT=test` | `migration 1 applied or already present`，退出码 0 |
| `xingtu register-unit --config .runtime/evidence-run/unit.json` | `{"unit_id": "evidence-unit", "state": "NEEDS_LOGIN"}` |
| `xingtu start`（未核验注册表） | `{"error_code": "PLATFORM_PAGE_CHANGED", "reason": "UNVERIFIED_REGISTRY"}`，退出码 2 —— live 门槛不可绕过 |
| `xingtu enable-contract`（未核验注册表） | 同上拒绝，退出码 2 |
| `xingtu doctor` | 输出 `live_status=UNVERIFIED`、四条未核验缺口、附录 A 预算默认值与默认证据实现 |
| `xingtu status <root>` | 输出 `rescan_reasons=["CURSOR_INVALID"]`、`search_generation=1`、`unidentified_rows` 两条诊断、`profile_checkpoint_versions`、逐模块/逐字段状态与失败原因 |
| `xingtu results <root>` | 返回已发布快照（含字段来源、观测时间、单位），与草稿分离 |
| `make dev` | **失败**：`Cannot connect to the Docker daemon`（本机 Docker 守护进程未运行），Compose 路径本轮未验证 |
| `make setup` / `make stop` / `make smoke-live` | 未执行（安装入口未重跑；Compose 未启动；冒烟需真实账号） |

第 3 行的任务由 `xingtu status` 读取；该任务是**明确人工构造**的内部验收任务（合成适配器、`adapter_version=contract_version=synthetic-v1`），不是真实采集结果，不得作为平台可用性证据。

## 4. 本轮修复的缺陷（含最小复现）

| 缺陷 | 影响 | 复现与修复验证 |
|---|---|---|
| 搜索中途游标失效未重扫 | 可恢复状态被判为 `FAILED`，并把整个 `contract_version` 置为 `disabled`，屏蔽后续新任务 | 修复前：合成适配器第 2 批抛 `SEARCH_CURSOR_INVALID` 时异常冒泡；修复后 `test_mid_scan_cursor_expiry_rescans_and_keeps_contract_enabled` 通过且 `contract_health` 无记录（见 [DEC-002](../decisions/DEC-002-cursor-recovery.md)） |
| 连续 3 批无新身份即 `NO_PROGRESS` | 会杀掉技术方案 5.2.3 要求的合法重扫（重扫必然连续经过已见身份） | `test_rescan_over_known_identities_is_not_a_contract_failure`：目标 5、连续 4 个已见身份页面后补足完成；`CURSOR_LOOP` 与扫描/主动预算继续兜底 |
| 无身份搜索行直接判契约失效 | 未满足"留诊断记录、不增加有效数"，并把局部脏行升级为全局失败 | `test_unreadable_rows_become_diagnostics_not_candidates`、`test_unreadable_rows_are_persisted_as_diagnostics`（见 [DEC-003](../decisions/DEC-003-unidentified-candidates.md)） |
| 模块级无权限无法与读取失败区分 | T07/T09 无法满足；整体无权限会表现为每个字段 `FAILED` | 契约测试中 `fans` 模块以登记探针判定 `NO_PERMISSION` 且 `complete=true`（见 [DEC-005](../decisions/DEC-005-registry-gate.md)） |
| 注册表无引用完整性校验 | 字段引用未声明的请求键等配置错误要到运行时才逐个失败 | 单测 21 项拒绝原因 |
| `EvidenceStore` 为死代码 | 搜索耗尽与模块失败没有可追溯证据 | `test_evidence_records_exhaustion_and_module_failure`（见 [DEC-004](../decisions/DEC-004-evidence-sink.md)） |

## 5. 未验证事项（不得视为通过）

1. **真实平台（U02/U04）**：筛选枚举、内容关键词模式、报价形式/单位、重置与回读、分页与终点、主页各模块字段来源与默认口径、真实定位器与访问节奏。注册表保持 `session/search=null`、`modules=[]`。
2. **执行单元与线路（U06/U07/U08）**：远程浏览器维护、账号识别、J1900/蜂窝模块/SIM、代理端点、DNS 绑定、断线禁止直连、旧浏览器停止与隔离实测。执行单元配置与租约隔离仅有代码与合成验证。
3. **执行单元 Activity 端到端**：`Activities.collect` 强制 `require_enabled(live=True)`，无法用合成注册表绕过；因此其端到端验证必须等待真实账号与线路（UNIT-01），本轮只覆盖 Engine/Repository/Workflow/适配器契约层。
4. **对象存储 S3 路径（U09）**：仅验证本地文件实现；`S3EvidenceStore` 与 MinIO 未实测。
5. **Docker Compose**：`make dev` / `make stop` 因守护进程未运行未验证。
6. **精选作品与封面（U05、F06）**：本轮范围外，任务终态保持 `PARTIAL_COMPLETED`、`featured_status=NOT_ATTEMPTED`。

## 6. 结论

F04（平台筛选、搜索与候选发现）与 F05（达人主页资料采集）的**离线可验证部分**已实现并通过上述检查；两卡状态为**待验收**，真实平台与线路核验受 UNIT-01 资源缺失阻塞。不得据此宣称真实采集可用或生产就绪。
