# SESSION-01 会话复用与账号绑定验收证据（两段式实测）

日期：2026-09-29（Asia/Shanghai）。环境：macOS、本项目 `.venv`、无 Git。
任务卡：[SESSION-01](../tasks/SESSION-01.md)；相关：[AUTO-01](../tasks/AUTO-01.md)、[UNIT-01](../tasks/UNIT-01.md)、[DEC-012](../decisions/DEC-012-session-persistence.md)。
范围：**真实平台**（巨量星图，本机 IP + 项目独立 Chrome + 持久 profile，`network_mode=local_development`），非合成、非离线。

## 1. 本轮验证目标

验证用户需求："首次登录后，跑任务→关闭浏览器→再跑任务不需要登录"，并顺带观测持久会话的真实存活情况。

## 2. 前置改动

按 [DEC-012](../decisions/DEC-012-session-persistence.md) 落地两处最小改动（改动 1「冷启动握手重试」经评估后**未纳入**，理由见该决策记录）：

- `BrowserHost.session_verified`：仅当本次运行确实验证过活跃受保护会话时置位。
- `release(needs_login=not session_verified)`：会话验证通过的运行在确认关闭后回到 `READY`，不再无条件打回 `NEEDS_LOGIN`。
- `worker.py`：单元已是 `READY` 的采集路径同样置位（该租约本身要求单元为 `READY`）。

离线验证：`ruff`／`format-check`／`mypy` 通过；`pytest backend/tests tests/e2e` **167 passed**（102 单测 / 17 契约 / 44 集成 / 4 E2E），退出码 0。

## 3. 四次真实运行的结果

全部为 `target_count=2`、关键词「宠物」、`make smoke-local`。

| 运行 | 起始单元状态 | 实际生效账号 | 结果 | 失败原因 |
|---|---|---|---|---|
| run 1 | `NEEDS_LOGIN` | `ID: 1865332309937515`（绑定） | `PARTIAL_COMPLETED`，有效 **2** 位 | — |
| run 2 | `READY` | 未成功核验 | 失败，0 候选 0 扫描 | `ACCOUNT_LOGIN_REQUIRED` ×2、`LEASE_LOST` ×2 |
| run 3 | `NEEDS_LOGIN` | `ID: 1865332309937515`（绑定） | `PARTIAL_COMPLETED`，有效 **2** 位 | — |
| run 4 | `READY` | `ID: 1832740070238347`（**非绑定**） | 失败，0 候选 0 扫描 | `ACCOUNT_LOGIN_REQUIRED:WRONG_ACCOUNT` ×3、`LEASE_LOST` ×1 |

单元绑定：`expected_account_id = ID: 1865332309937515`（`.runtime/units/local-dev-mac-02.json`，`docs/` 中出现 7 次均为该值）。

run 1 期间的完整审计（用于排除归因错误）：

```text
02:31:06Z  internal_acceptance.start          [user-acceptance-run1]
02:31:39Z  promote_maintenance_to_collect     [browser-host:c7150c86…]   ← 用户人工登录
02:34:56Z  transition_collect_to_maintenance  :PLATFORM_SECURITY_CHALLENGE
02:35:00Z  promote_maintenance_to_collect     [browser-host:c7150c86…]   ← 挑战清除后自动恢复
02:38:23Z  internal_acceptance.start          [user-acceptance-run2]
```

## 4. 结论一：会话跨任务复用**成立**（机制层面）

- run 4 在单元为 `READY` 时以 `collect` 模式取得租约，**`session_version` 全程保持 10、未发生任何 promote**，即**未要求人工登录**。
- 独立探测（直接导航受保护业务页）显示 `div.search-content--header` 可见、会话有效、无安全挑战。
- 会话在同一 profile 上跨越多次运行与浏览器关闭仍然有效，本轮结束时（距 run 3 约 20 分钟）仍可读到该账号。

**因此 [DEC-012](../decisions/DEC-012-session-persistence.md) 的状态机改动按设计生效**，"会话有效即不重复登录"这一半目标已达成。

## 5. 结论二：账号在同一 profile 内**漂移**

run 3（正确账号）与 run 4（错误账号）间隔约 3 分钟，期间**无人工登录**，实际生效账号却不同。这是本轮最重要的未解释现象，也是 run 2／run 4 失败的直接原因。

### 直接观测

```text
配置期望账号 : ID: 1865332309937515
profile 实际账号: ID: 1832740070238347
受保护业务页 : 可用（div.search-content--header 可见）
匹配元素数量 : 1
错误页特征   : PLATFORM_SECURITY_CHALLENGE visible=False
```

会话有效、页面可用、账号可读，**唯独账号不是绑定的那个**。

## 6. 问题清单

### P1 账号不匹配被错误归因为"需要登录"（已确认，未修）

`check_session`（[adapter.py:286-292](../../backend/src/xingtu/adapter.py)）对账号不符抛 `ACCOUNT_LOGIN_REQUIRED`（reason `WRONG_ACCOUNT`）。于是 `ACCOUNT_LOGIN_REQUIRED` 至少混装三种不同状况：

| 真实情况 | 现行表现 | 是否恰当 |
|---|---|---|
| 会话真的失效 | `ACCOUNT_LOGIN_REQUIRED` | 恰当 |
| 会话有效但登录账号 ≠ 绑定账号 | `ACCOUNT_LOGIN_REQUIRED:WRONG_ACCOUNT` | **不恰当**：用户被反复引导去"重新登录"，而正确动作是"换账号"或"改绑定" |
| 受保护标记未渲染／冷启动竞态 | `ACCOUNT_LOGIN_REQUIRED` | 不恰当：分不清是登录问题还是页面问题 |

影响：用户无法自助排障；同一现象在四轮运行中被反复误读为登录问题（本轮工作记录中亦有两次据此作出的错误结论）。

### P2 账号在 profile 内漂移（现象确认，根因未定）

同一 profile、无人工干预，账号在不同运行间不同。根因待定，见第 7 节。

### P3 回收协议缺少单一入口且依赖 `/bin/ps`（已确认，未修）

- `recover-unit` 只接受 `QUARANTINED`；而"租约到期的 `LEASED` → `QUARANTINED`"迁移只发生在 `Repository.acquire()` 内部，没有对外命令。worker 被中断后恢复实为**两步**，单独执行 `recover-unit` 会报 `UNIT_NOT_QUARANTINED`。
- `confirm_local_browser_stopped` 依赖 `/bin/ps`，在受限环境返回 `PROCESS_LIST_UNAVAILABLE`。

本轮实测同时证明 `/bin/ps` 判据**弱于** `flock`：收尾时 `SingletonLock` 指向的 PID `14184` 已不存在（陈旧残留），`ps` 无法分辨真假，而 `flock` 给出了正确结论（profile 空闲）。建议改用 `flock` + `Singleton*` 文件作为等价隔离判定。

### P4 无人值守时任务会长期占用 profile（行为确认，设计待评估）

run 2 失败后进入维护等待，最长 900 秒持有 Chrome；worker 被外部中断后无法完成收尾，单元停在 `LEASED/maintenance/browser_stopped=false`，Chrome 持续占用 profile。安全边界 fail-closed 正确，但需要有人观察才能解除。

## 7. 可能原因与理由（**均为推测，未验证**）

| # | 推测 | 支持理由 | 反对理由 / 待查 |
|---|---|---|---|
| H-A | **profile 内并存多个账号的登录态**，平台解析当前账号时不稳定 | run 3 与 run 4 间隔约 3 分钟、无人工登录却账号不同；`div.navigator-user__userid` 只匹配到 1 个元素但内容在两轮间变化；用户日常 Chrome 使用同一平台且稳定，说明不是平台不支持持久会话 | 未检查 profile 内是否存在多账号声明；无法在不停用 profile 的前提下直接枚举 |
| H-B | **账号切换导致服务端会话被重新绑定**，而非会话失效 | 受保护页始终可用、无挑战、`session_version` 未变，说明会话本身没死，只是账号归属变了 | 需要带时间戳的切换实验才能证伪 |
| H-C | 存在**未识别的外部因素**（其他客户端／浏览器窗口／平台侧多设备策略）在本轮窗口内改变了账号解析 | 本轮曾观察到不持有 profile 锁的遗留 Chrome 窗口 | 用户报告期间未在其他客户端登录；但未做到全程隔离验证 |
| H-D | 与 `BrowserRuntime` 注入的启动参数有关（`--disable-quic`、`--force-webrtc-ip-handling-policy` 在本地模式也注入） | 与用户日常 Chrome 的关键差异之一 | 该假设只解释"会话易失效"，**不解释账号漂移**，优先级低于 H-A/H-B |

**综合判断**：H-A/H-B（多账号并存／会话被重新绑定）最能同时解释"会话有效但账号不对"这一特征；H-D 仅能解释会话寿命，不足以解释本次现象。

## 8. 本轮证据局限（必须保留）

1. 各假设**均为单次观测**，未做重复实验，不能据此定论。
2. 本轮工作过程中有**两次过早结论被后续审计推翻**（曾判定 run 2、run 4"免登录成功"，实际两者最终均失败）。本节所有结论均以审计记录与数据库状态为准，不采信过程判断。
3. `run 2` 的实际生效账号未能从审计中确证（其失败信息为 `ACCOUNT_LOGIN_REQUIRED`，未记录账号值）。
4. 未测量会话的**真实存活上界**；本轮结束时会话仍有效，只能说"至少存活约 20 分钟且跨越多次浏览器重启"。
5. 未在有其他客户端并发登录同一账号的条件下做对照实验，H-C 未被排除。

## 9. 未执行项

- 完整 5/20/200 位容量观测、连续 7 天观察。
- 分页第 3 页及真实终点（与本轮无关，见 [F04](../tasks/F04.md)）。
- 生产线路与远程维护（U06/U07/U08）。
- 修复 P1／P2／P3／P4 中任何一项（本轮仅登记，未改动）。

## 10. 脱敏与清理

- 未记录密码、验证码、Cookie 值、令牌或请求头值；仅保留账号 ID、状态枚举与计数。
- 本轮结束后环境状态：`unit-local-mac-02` = `READY`／`owner=NULL`／`browser_stopped=true`／`session_version=10`；`contract_health` = `disabled=false`；profile `flock` 空闲、无 `Singleton*` 残留。
- 两次中断均由内置路径带审计恢复：`recover_stopped_unit:unit-local-mac-02`（actor `session-persistence-recovery` / `session-persistence-recovery-2`）。
