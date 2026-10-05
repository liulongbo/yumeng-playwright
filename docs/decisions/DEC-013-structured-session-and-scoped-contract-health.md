# DEC-013：结构化会话健康与按能力范围的 Contract 熔断

> 日期：2026-09-29。状态：已实施，待真实平台长期验收。关联任务：[SESSION-01](../tasks/SESSION-01.md)、[AUTO-01](../tasks/AUTO-01.md)。取代 [DEC-012](DEC-012-session-persistence.md) 中布尔 `session_verified`／`needs_login` 的最终设计；DEC-012 保留为历史。

## 问题

旧实现混合了三组不同事实：数据库中的 `READY`、当前 Chrome 进程是否真实验证过 Session、失败后用户应采取什么动作。结果包括：旧 `READY` 在页面校验前把 `session_verified=True`；错误账号被包装为 `ACCOUNT_LOGIN_REQUIRED`；无登录页也无受保护页证据时无法表达“不可判定”；单达人 `IDENTITY_UNREADABLE` 又被放大成整版本 Contract disabled。

## 选择

1. 每个新 Chrome 进程都从“未验证”开始；持久状态 `READY` 只允许取得 collect 租约，不作为当前会话有效证据。
2. `SessionHealthStatus` 为 `VALID`、`LOGIN_REQUIRED`、`ACCOUNT_MISMATCH`、`SECURITY_CHALLENGE`、`INDETERMINATE`。只有受保护业务页可用、账号可读且与绑定一致、无登录页和挑战时才为 `VALID`。
3. BrowserHost 以 `ReleaseDisposition` 释放：`VERIFIED_READY`、`LOGIN_REQUIRED`、`ACCOUNT_MISMATCH`、`SESSION_UNVERIFIED`、`BROWSER_UNCONFIRMED`。浏览器正常关闭本身不改变认证事实；关闭未确认始终隔离。
4. ExecutionUnit 新增 `ACCOUNT_MISMATCH`、`SESSION_UNVERIFIED`；根任务新增 `WAITING_FOR_ACCOUNT`。错误账号要求切换到绑定账号或显式审计改绑，不允许自动改绑。
5. 单达人首次出现 `IDENTITY_UNREADABLE` 后先重新验证 Session；Session 仍为 `VALID` 时最多执行三次独立详情页尝试，每次重建 Page 和观察器。仍失败则记录候选失败并继续补位。
6. Contract 健康按 `session`、`search`、`profile_identity`、`profile_module:<key>`、`featured:<key>` 管理。三个不同主体在连续失败中达到 `SUSPECTED`；新浏览器租约内第四个不同主体再次复现才 `DISABLED`。全局 `contract_health` 暂留作兼容和人工覆盖。
7. 过期租约回收使用项目 profile `flock` 与 Chromium `SingletonLock` PID 作为独立证据，不依赖 `/bin/ps`；回收后为 `SESSION_UNVERIFIED`，不把 Worker 中断伪装成真实登出。
8. scoped breaker 默认启用；紧急回滚可用 `XINGTU_SCOPED_CONTRACT_HEALTH=false` 停止读取与推进 scope 状态，旧全局人工覆盖继续生效。开关不删除历史记录。

## 数据与兼容

迁移 006 只新增 `execution_units.last_session_*`、`contract_capability_health` 和用于不同主体去重的 `contract_capability_failures`。不删除旧字段、不改写历史快照；旧全局 disabled 仍优先阻断。Checkpoint 中 `Candidate.retry_count` 有默认值，旧 JSON 可直接读取。Temporal Workflow 仅增加 `WAITING_FOR_ACCOUNT` 的显式 wake 分支，不改变 Activity 名称。

## 安全与诊断

`xingtu session-diagnostics` 冷启动同一持久 Profile，记录浏览器环境摘要、Cookie 属性与值 HMAC、当前 origin 的 LocalStorage/SessionStorage key 与值 HMAC、IndexedDB 名称/store/数量、页面 SessionHealth 和正常关闭结果。HMAC 密钥只从 `XINGTU_DIAGNOSTIC_HMAC_KEY` 读取；报告存放于本机受控 `.runtime/session-diagnostics/`，不进入版本库，也不记录 Cookie/Token 明文。

## 尚未完成的真实验收

- 项目 Chrome 内退出全部账号后只登录绑定账号，完成两次冷启动复验；
- 0/15/30/45/60 分钟及 2/6/12/24 小时、3/7/14/30 天分阶段观测；
- 真实 5/10/20 位连续采集和单达人失败后补位；
- 第 3 页及分页终点确认后才允许 50/100 位真实任务。

因此当前状态为“代码与离线/合成验证完成，真实平台待验收”，不得宣称一个月 Session 目标已经达成。
