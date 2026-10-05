# DEC-012：会话验证后的执行单元状态

> **历史决策，最终状态机已被 [DEC-013](DEC-013-structured-session-and-scoped-contract-health.md) 取代。** 本文保留 DSH 阶段的原始选择与证据，不能再作为当前 `Repository.release`、ExecutionUnit 状态或错误分类的实现说明。

> 日期：2026-09-29。关联任务：[SESSION-01](../tasks/SESSION-01.md)、[AUTO-01](../tasks/AUTO-01.md)、[UNIT-01](../tasks/UNIT-01.md)。相关决策：[DEC-011](DEC-011-automation-optimization.md)。

## 待解决的问题

执行单元在每次任务结束时被**无条件**打回 `NEEDS_LOGIN`，导致下一个任务必然进入人工维护流程并等待用户登录。用户需求是"首次登录后持久存活，跑任务后关掉浏览器再跑任务不用登录"。

同时需要判定：**关闭浏览器这个动作，本身是否构成平台会话的认证边界。**

## 背景：原假设及其证据问题

原实现（[AUTO-01](../tasks/AUTO-01.md) 有界浏览器宿主批次）在 `BrowserHost.lease` 的 `finally` 中写死：

```python
# Closing a Chrome process is an authentication boundary for the verified platform.
repo.release(..., needs_login=True)
```

其依据是"实测证明星图业务会话不能跨 Chrome 重启恢复"（写入[技术方案§1.4](../AI达人智能发现与采集系统-完整技术方案.md)）。但该结论存在两个问题：

1. 证据本身自述**无法区分**"用户新登录"与"既有会话被接受"（[有界宿主真实运行](../evidence/AUTO-01-bounded-host-real-run-2026-09-28.md) 第 3.1 节）；
2. 当时的会话探针**只验证受保护元素可见，从未比对账号 ID**，而 `check_session` 与 `wait_for_manual_clearance` 都要求账号精确一致 —— 因此"会话失效"可能是测量假象。

2026-09-29 的实际观测进一步显示两种方向同时存在：用户日常 Chrome 可 7-8 天免登录；项目独立 profile 约 45 分钟即失效。**会话真实寿命未定，已独立建卡核验（[SESSION-01](../tasks/SESSION-01.md)）。**

## 选择

**不改变任何会话寿命假设**，只修正状态机的一处过度断言：

- 新增 `BrowserHost.session_verified`，默认 `False`；
- 只有**本次运行确实验证过活跃受保护会话**时才置 `True`：维护路径在 `promote_maintenance_to_collect`（三项证据：账号一致、受保护业务页可用、线路正常）成功后置位；采集路径在本 Activity 已在 `READY` 单元上开始采集时置位（该租约本身即要求单元为 `READY`，且 Adapter 仍会在业务调用前重新校验会话）；
- `release(needs_login=not session_verified)`。

于是：**验证过会话的运行**在确认关闭后回到 `READY`，下一个任务直接以采集模式复用持久 profile，不再打开人工登录窗口；**从未验证过会话的运行**仍回 `NEEDS_LOGIN`；**关闭未确认**仍进 `QUARANTINED`。

`session_verified` **不表达**"会话还能用多久"。会话在下一次运行时由 Adapter 重新校验，失效则照常进入维护流程。

## 主要替代方案

| 方案 | 未采用原因 |
|---|---|
| 常驻 BrowserHost，任务间不关闭浏览器 | 彻底绕开"能否跨重启"，但引入常驻内存、备份、节点迁移与 profile 独占问题；在会话寿命未明前属于过度投入 |
| 每次任务结束导出 Playwright `storageState` 并在启动时恢复 | 持久 profile 已承载 Cookie 与 localStorage，重复导出无收益；且不解决"服务端是否接受"这一真正变量 |
| 保持 `needs_login=True` 不变，只做会话核验 | 会继续让"会话有效"的运行也强制人工登录，直接违背用户需求 |

## 与既有架构的兼容性

- 不改数据库结构，无迁移。
- 不改 `Repository.release` 语义（它本就支持 `READY`），也不改 `acquire` 的 `state != READY` 门。
- 不改 Temporal 工作流逻辑；`WAITING_FOR_LOGIN` 与显式 wake 语义保持。
- 会话失效路径保持 fail-closed：单元进 `NEEDS_LOGIN`、任务进 `WAITING_FOR_LOGIN`，**不使用** `PLATFORM_PAGE_CHANGED` 表达"登录过期"，以免触发 `contract_health` 的整版本禁用。

## 最小验证结果

2026-09-29，本地离线/合成验证：

- `ruff check`、`ruff format --check`、`mypy backend/src` 通过。
- `pytest backend/tests tests/e2e`：**167 passed**（102 单测 / 17 契约 / 44 集成 / 4 E2E），退出码 0。
- 新增/更新的定向断言：
  - `test_browser_host_promotes_and_collects_with_the_exact_same_context`：提升后再确认关闭，断言单元为 `READY`、`browser_stopped=true`、`owner=NULL`。
  - `test_browser_host_owns_one_context_and_confirmed_close_needs_login`（既有）：未验证会话的宿主确认关闭后仍断言 `NEEDS_LOGIN`，覆盖负向路径。

**未验证（如实记录）**：真实端到端两段式验收（同一 profile 连跑两次、第二次不出现人工登录窗口）**尚未执行**。原因：验收运行在受限沙箱中无法完成单元回收（`recover-unit` 依赖 `/bin/ps`，返回 `PROCESS_LIST_UNAVAILABLE`），且项目 profile 的会话在本次会话期间已失效，需要一次人工登录才能完成验证。该验收保留为待办，证书状态不得据此写成"已验收"。

## 限制与风险

- 若会话寿命问题最终无法解决，"免登录"在真实场景下仍受平台会话存续限制；本决策**不承诺**具体免登录时长。
- 采集路径的置位依赖"租约要求单元为 `READY`"这一前提；若未来允许在非 `READY` 状态下授予采集租约，该置位逻辑需要同步复核。
- 会话真实失效后，用户会经历一次未预期的维护等待；这是 fail-closed 的预期行为，不是缺陷。
