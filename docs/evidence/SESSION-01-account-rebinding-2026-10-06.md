# SESSION-01 执行单元账号改绑与漂移规避证据（2026-10-06）

## 目的

用户决定**舍弃旧登录身份**（其父账号下并存多个子账号，重启后平台解析回退到 `ID: 1832740070238347`），改用**只含单一子账号的新巨量星图账号**，以绕开无法自动纠正的子账号漂移，使 F04/F05 后续功能验收不被 `ACCOUNT_MISMATCH` 拦住。

本证据回答两件事：

1. 该执行单元的旧平台账号与缓存是否已按契约清除、新登录身份是否真实生效；
2. 改绑后的绑定在**独立冷启动**下是否仍然漂移（区别于此前"人工登录后同一进程内稳定"）。

## 环境与版本

| 项 | 值 |
|---|---|
| 日期时间 | 2026-10-06 16:14–16:30（+08:00） |
| 执行单元 | `unit-local-mac-02`，配置文件 `.runtime/units/local-dev-mac-02.json` |
| 绑定变更 | `expected_account_id`：`ID: 1865332309937515` → `ID: 1807978499337419` |
| 网络模式 | `local_development`（本地出口，**非生产线路，本次不代表生产验收**） |
| 浏览器 | 真实 Google Chrome，`headless=false`，`macos_system_keychain=true`（忽略 Playwright 默认 `--use-mock-keychain`） |
| 代码版本 | 分支 `翻页+全字段`，HEAD `bc74e27`（工作区含未提交的"翻页+全字段"进行中改动） |
| 数据库 | 本地 PostgreSQL 18.3，`127.0.0.1:55439`，开发库 `xingtu_local_dev` |
| Temporal | **未运行**（57233 关闭），故未走 `xingtu login` 的 Worker 维护窗口，改用项目同一 `BrowserRuntime` 的探针登录窗口 |
| profile | 备份后删除重建：`.runtime/profiles/unit-local-mac-02.bak-20261006T161500`（200 MiB） |

## 清除与重建（先备份，再删除）

```bash
# 1) 隔离验证（flock 空闲 + SingletonLock 指向的 PID 不存在），备份并清空
.venv/bin/python /tmp/reset_unit_profile.py
#    [ok] 无浏览器占用 profile
#    [ok] 备份：.runtime/profiles/unit-local-mac-02.bak-20261006T161500 (200 MiB)
#    [ok] 已清空并重建：entries=0

# 2) 用项目真实 Chrome 打开登录窗口（探针走同一 BrowserRuntime / 同一 profile）
XINGTU_DIAGNOSTIC_HMAC_KEY=... PYTHONUNBUFFERED=1 \
.venv/bin/python scripts/account_drift_probe.py \
    --config .runtime/units/local-dev-mac-02.json \
    --rounds 1 --await-login-seconds 900 \
    --out .runtime/drift-probe/relogin-20261006
```

清空前的静态检查（只读）：`execution_units.unit-local-mac-02` 为 `state=SESSION_UNVERIFIED`、`owner` 为空、`browser_stopped=true`，无租约；profile 内存在旧身份 Cookie。

## 结果 1：新登录身份生效，旧绑定下判定 `PERSISTENT_ACCOUNT_MISMATCH`

人工在窗口内完成登录后，探针冷启动读到：

| 观测点 | 读到账号 | 受保护页 | 会话判定 |
|---|---|---|---|
| `business-page-entered` | `ID: 1807978499337419` | 可见 | `ACCOUNT_MISMATCH / PROTECTED_PAGE_WRONG_ACCOUNT` |
| `index` | `ID: 1807978499337419` | 可见 | 同上 |
| `market` + 同页反复读取 4 次 | `ID: 1807978499337419` | 可见 | 同上 |
| `index-again`、`tab2-market` | `ID: 1807978499337419` | 可见 | 同上 |

判定 `PERSISTENT_ACCOUNT_MISMATCH`（退出码 1）**是改绑前绑定的预期结果**，不是新故障：绑定当时仍是 `ID: 1865332309937515`。同进程 10 次读取恒为同一新 ID，说明新身份在进程内稳定。

Cookie 只读复核（`/tmp/cookie_check.py`）：`star_sessionid`、`sessionid`、`sid_guard`、`d_ticket`、`odin_tt` 等认证 Cookie **在冷启动前后均存在于磁盘且被 Context 读取**。即此前"冷启动未经登录"不是缺少凭证，而是**旧会话在服务端已失效**；首次冷启动第一跳仍会出现 `/?redirect_uri=...`，随后进入业务页并读到账号。

## 结果 2：改绑（显式、可审计）

新增迁移 `migrations/007_unit_account_rebinding.sql`：`unit_account_rebindings` 记录每次改绑的旧/新账号、操作者、原因、证据引用与时间；`previous_config_account_id` 记录"旧绑定只存在于单元配置文件、从未落库"的那种情形（本单元即如此，故 `previous_account_id` 为 `NULL`）。

```bash
export XINGTU_DATABASE_URL=postgresql://xingtu_test@127.0.0.1:55439/xingtu_local_dev
.venv/bin/xingtu migrate --environment development       # schema_migrations 1..7
.venv/bin/xingtu rebind-account \
  --config .runtime/units/local-dev-mac-02.json \
  --account-id "ID: 1807978499337419" \
  --previous-account-id "ID: 1865332309937515" \
  --actor "user-yaoyao" \
  --reason "旧登录身份存在子账号漂移…改用只含单一子账号的新巨量星图账号…" \
  --evidence-ref "docs/evidence/SESSION-01-account-rebinding-2026-10-06.md"
```

结果：

| 位置 | 值 |
|---|---|
| `execution_units.expected_account_id` | `ID: 1807978499337419` |
| `execution_units.verified_account_id` | `NULL`（新身份必须重新观测） |
| `execution_units.state` | `SESSION_UNVERIFIED` |
| `execution_units.failure_reason` / `last_session_reason` | `ACCOUNT_BINDING_CHANGED` |
| `unit_account_rebindings` | `previous_config_account_id=ID: 1865332309937515` → `ID: 1807978499337419`，actor `user-yaoyao` |
| `audit_logs` | `rebind_unit_account:unit-local-mac-02:ID: 1865332309937515->ID: 1807978499337419:<原因>` |

约束（已由集成测试固定）：改绑在**浏览器宿主占用单元时拒绝执行**；改绑到已绑定身份返回 `ACCOUNT_ALREADY_BOUND`；`register_unit`（自动化路径）**仍然拒绝**变更身份，`ACCOUNT_MISMATCH` 依旧不会触发自动改绑。

## 结果 3：改绑后两次独立冷启动判定 `STABLE`（零漂移）

```bash
XINGTU_DIAGNOSTIC_HMAC_KEY=... PYTHONUNBUFFERED=1 \
.venv/bin/python scripts/account_drift_probe.py \
    --config .runtime/units/local-dev-mac-02.json \
    --rounds 2 --gap-seconds 10 --await-login-seconds 300 \
    --out .runtime/drift-probe/rebind-verify-20261006
```

实际输出：

```text
判定：STABLE
绑定账号：ID: 1807978499337419
实测账号：['ID: 1807978499337419']
可读/不可读：15/5
不可读相位：['cold-entry', 'public-root', 'cold-entry', 'index', 'public-root']
浏览器 A/B=playwright-current 版本=154.0.8037.98
报告：.runtime/drift-probe/rebind-verify-20261006/drift-unit-local-mac-02-20261006T082826Z.json
退出码 0
```

| 轮 | 冷启动首跳 | 后续观测（`business-page-entered` / `index` / `market` / 同页 ×4 / `index-again` / `tab2`） |
|---|---|---|
| 0 | `/?redirect_uri=...`（不可读） | 全部 `ID: 1807978499337419`，受保护页可见，会话 `VALID` |
| 1 | `/?redirect_uri=...` 与 `index` 两跳不可读 | 从 `market` 起全部 `ID: 1807978499337419`，受保护页可见，会话 `VALID` |

跨轮比对：**身份 Cookie 变化 = 空**（`identity_cookies_changed: []`），变化的只有埋点/tanstack 缓存类 localStorage 与 sessionStorage 键。

**结论（本轮范围内）**：把单元绑定到"单一子账号"的新登录身份后，**同一 profile 在两次独立 Chrome 冷启动之间未再出现账号漂移**，与改绑前"重启即回退到 `1832740070238347`"形成对照。用户所述"新账号内只有一个子账号即可避免漂移"在本轮观测中成立。

## 结果 4：改绑后复跑仍 `STABLE`，但 `xingtu research` 路径单独失败（新登记缺陷）

改绑验证之后又连续做了 4 次以上的冷启动（`session-diagnostics`、两次只读复核、`xingtu research`），随后：

- `xingtu session-diagnostics`：`status=INDETERMINATE`、`protected_page_verified=true`、`observed_account_id=null`、`reason=PROTECTED_PAGE_ACCOUNT_UNREADABLE`（首次运行即落在 `/?redirect_uri=...`）。
- `xingtu research --login-wait-seconds 90` 与 `--login-wait-seconds 0`：均在 `verify_account` 步骤报 `ACCOUNT_LOGIN_REQUIRED: ACCOUNT_LOCATOR_UNREADABLE`（退出码 2）。
- 同时刻磁盘 Cookie 仍**完整存在**（`star_sessionid`、`sessionid`、`sid_guard`、`d_ticket`、`odin_tt`、`toutiao_sso_user` 等全部 PRESENT），故不是"被登出/凭证丢失"。
- 紧接着用探针复跑（`--rounds 2 --gap-seconds 15`，不带 `--await-login-seconds`、无需人工介入）**再次判定 `STABLE`**：16 次可读全部为 `ID: 1807978499337419`，4 次不可读仍只落在 `cold-entry` / `public-root`。

结论：**账号绑定与漂移规避在改绑后持续成立**（两种独立工具、共 4 次冷启动复核均为同一账号）；差异出在**工具自身的冷启动引导**——探针先进入业务页、读不到时最多重试 4 次业务页引导（`enter_business_page`），因此能在第一跳被重定向后恢复；`xingtu research` 只导航一次就直接执行步骤，第一跳被重定向到 `/?redirect_uri=...` 时没有第二次业务页引导，于是 `verify_account` 必然读不到账号。**该缺陷与账号漂移无关**，登记为遗留项（本轮未修，避免与工作区中未提交的 `research.py` 改动叠加）。

## 局限（必须与结论一起引用）

1. 本次只测**重启触发**，间隔 10–15 秒；未测时间触发的上界，也未做第三方客户端并发登录的对照（H-C 仍未排除）。
2. 冷启动**第一跳仍会重定向到 `/?redirect_uri=...`**，账号与受保护页要等**第二次导航**（业务页引导）才可读；上述 4—5 次"不可读"全部落在 `cold-entry` / `public-root` 相位，不是登出。这与 `SESSION-01` 已记录的"冷启动必须包含访问业务页引导会话"一致。
3. 连续多次冷启动（本次累计 8 次以上）后曾出现"连续多次落在跳转页"的窗口，但同一 profile 的 Cookie 未丢、随后立即恢复正常；未做对照实验，**不据此断言**是平台限流还是引导顺序问题。
4. 改绑是**人为决策**（用户确认新身份 `ID: 1807978499337419`），系统仍不自动改绑；真正的根因（H-A/H-B）本轮未被区分，只是被"单子账号身份"绕过。
5. 本次为 `local_development`，不代表生产线路验收。

## 同时发现的既有失败（与本轮改动无关）

`backend/tests/integration/test_repository.py::test_browser_host_promotes_and_collects_with_the_exact_same_context` 失败（`browser.pages[0].urls` 多出一次 `session.entry_url`）。经 **stash 本工作区改动后在本分支 HEAD `bc74e27` 上复跑，同样失败**，且断言与用例自本分支引入以来未被改动，失败面在工作区未提交的"翻页+全字段"改动所影响的宿主导航顺序，与本次账号改绑无关。本轮未修复，登记为遗留。

## 相关文件

- 迁移：[007_unit_account_rebinding.sql](../../migrations/007_unit_account_rebinding.sql)
- 仓储方法：`Repository.rebind_unit_account`（[repository.py:276](../../backend/src/xingtu/repository.py)）
- CLI：`xingtu rebind-account`（[cli.py:201](../../backend/src/xingtu/cli.py)）
- 集成测试：`test_account_rebinding_is_explicit_audited_and_requires_released_browser`（[test_repository.py](../../backend/tests/integration/test_repository.py)）
- 原始报告：`.runtime/drift-probe/rebind-verify-20261006/drift-unit-local-mac-02-20261006T082826Z.json`、`.runtime/drift-probe/relogin-20261006/`
- profile 备份：`.runtime/profiles/unit-local-mac-02.bak-20261006T161500`
