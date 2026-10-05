# SESSION-01 / AUTO-01 结构性修复实施证据（2026-09-29）

## 范围与边界

本轮实施用户批准的结构化 SessionHealth、显式 ReleaseDisposition、达人级身份重试/跳过、按能力范围的 Contract breaker、诊断工具及安全回收。未启动真实巨量星图任务，未打开、清理或改写真实账号 Profile，未把离线结果当成一个月 Session 或真实 5/10/20 位验收。

当前仓库无 Git，证据以 2026-09-29 本地文件与实际命令结果为准，不编造 commit。

## 实现事实

- 迁移 006 新增 `execution_units.last_session_status/checked_at/reason`、`contract_capability_health`、`contract_capability_failures`，旧 `contract_health` 保留。
- `SessionHealthStatus`：`VALID`、`LOGIN_REQUIRED`、`ACCOUNT_MISMATCH`、`SECURITY_CHALLENGE`、`INDETERMINATE`。
- `ReleaseDisposition`：`VERIFIED_READY`、`LOGIN_REQUIRED`、`ACCOUNT_MISMATCH`、`SESSION_UNVERIFIED`、`BROWSER_UNCONFIRMED`。
- Worker 删除“旧单元为 READY 就提前 `session_verified=True`”的循环信任；当前 Chrome 必须实测受保护页和绑定账号。
- `IDENTITY_UNREADABLE` 首次出现后先重新验证受保护 Session；Session 仍有效时最多三次独立详情页尝试，仍失败则 `retry_count=2`、候选 `failed` 并继续补位。
- 三个不同主体连续失败进入 scope `SUSPECTED`；新租约第四个不同主体复现才 `DISABLED`。单样本不会禁用整版本；无关 scope 不受阻断。
- `recover-unit` 在 profile 项目锁和 Chromium Singleton PID 证明浏览器已停止后，可直接回收过期 `LEASED` 或 `QUARANTINED`，回收为 `SESSION_UNVERIFIED`。
- 新增 `xingtu session-diagnostics`。Cookie/LocalStorage/SessionStorage 值只写本机 HMAC；IndexedDB 只写数据库名、store 名与数量；报告权限为 `0600`。本轮未对真实 Profile 执行该命令。

## 自动验证

环境：macOS，本项目 `.venv`，项目固定 Chromium，PostgreSQL 隔离数据库 `xingtu_test_f04f05` 的随机 schema，Temporal 本地测试服务。测试不访问真实平台。

| 检查 | 结果 |
|---|---|
| `ruff check backend/src backend/tests tests/e2e` | 通过 |
| `ruff format --check backend/src backend/tests tests/e2e` | 通过，33 files already formatted |
| `mypy backend/src` | 通过，17 个源码文件 |
| `pytest backend/tests/unit -q` | 105 passed |
| `pytest backend/tests/contract -q` | 18 passed，项目固定 Chromium，合成页面 |
| `pytest backend/tests/integration -q` | 51 passed，118.52s，随机 PostgreSQL schema |
| `PYTHONPATH=. pytest tests/e2e -q` | 4 passed，2.12s，本地 Temporal + 合成 Adapter |
| `xingtu migrate --environment development` | 成功；本地 `xingtu_local_dev` 的 `schema_migrations={1,2,3,4,5,6}`，两张 scoped health 表存在 |

合计：178 passed。

迁移 006 已应用到本地开发库；它只新增列和表，不重写任务、快照、ExecutionUnit 绑定或 Contract 历史。真实 Profile 未被打开或改写。

测试历史如实保留：早期 E2E 首次只运行 `tests/e2e` 且未设置项目根 `PYTHONPATH`，在收集阶段报 `ModuleNotFoundError: backend`；本轮追加 Session 复核用例后的第一次 E2E 又遗漏 `XINGTU_TEST_DATABASE_URL`，4 项均在 fixture setup 阶段拒绝运行。补齐 `PYTHONPATH=.` 与隔离测试库 DSN 后 4/4 通过。定向 Integration 最初两次使用了不存在的本地角色 `postgres`/`yaoyao`，在建 schema 前被 PostgreSQL 拒绝；使用项目测试角色 `xingtu_test` 后通过。以上均为命令环境错误，没有业务断言失败，也没有接触开发业务库。

## 关键断言

- `test_session_health_distinguishes_valid_mismatch_login_and_indeterminate`：五态中的 VALID、错误账号、登录页、不可判定分流。
- `test_ready_collect_lease_must_reverify_before_returning_ready`：旧 READY 取得的新 Chrome 若未实测会话，关闭后只能 `SESSION_UNVERIFIED`。
- `test_browser_host_promotes_and_collects_with_the_exact_same_context`：维护三证据通过后同上下文提升并释放 READY。
- `test_identity_unreadable_retries_then_skips_and_continues`：一个达人三次身份不可读后记录失败，后续两位继续并达成目标。
- `test_identity_unreadable_rechecks_session_before_retry`：首次身份不可读后若受保护 Session 已明确失效，立即进入登录等待，不把认证问题误作达人级重试。
- `test_scoped_contract_breaker_requires_distinct_subjects_and_fresh_lease`：重复同一主体不推进；三个不同主体 SUSPECTED；新租约第四主体 DISABLED；search scope 不受 profile_identity 禁用影响；人工恢复有 actor/reason 审计。
- `test_scoped_contract_breaker_can_be_disabled_for_rollback`：紧急回滚开关关闭时不读取或推进 scope 记录，旧全局人工覆盖仍独立保留。
- `test_target_20_and_200`：同一业务根任务的合成 20/200 位连续采集通过。
- `test_recover_stopped_unit_handles_expired_lease_in_one_step`：过期 LEASED 无需先触发 acquire 即可安全回收。

## 未验收项

1. 在项目 Chrome 内正常退出全部账号，仅登录绑定账号并执行两次冷启动验证。
2. 真实 Session 0/15/30/45/60 分钟，2/6/12/24 小时，3/7/14/30 天分阶段观测。
3. 真实平台 5/10/20 位连续采集和单达人失败补位。
4. 第 3 页及分页终点验证完成后再执行真实 50/100 位任务。
5. 浏览器启动参数、版本、Client Hints、其他客户端互踢的单变量对照。

因此 SESSION-01 为“待验收”，AUTO-01 仍为“进行中／未验收”；不得宣称 Goal 1 的一个月寿命或 Goal 2 的真实平台规模已经通过。
