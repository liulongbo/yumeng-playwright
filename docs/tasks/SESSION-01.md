# SESSION-01：平台会话真实存活时长核验

状态：待验收  
更新时间：2026-09-29T14:56:37+08:00（Asia/Shanghai）  
是否验收：否

## 目标与范围

确定**巨量星图业务会话在项目独立 profile 中的真实存活时长与失效条件**，并据此推翻或确立"登录一次可长期复用"这一前提。

包含：存活时长实测、跨重启复用判定、失效诱因区分（跨客户端互踢／自动化风控／启动参数）、复用失败时的正确状态与降级路径。

不包含：产品登录会话（F01/APP-01）、蜂窝线路与远程承载（U06/U07/U08）。2026-09-29 用户批准结构性修复后，本卡范围扩展为：结构化 SessionHealth、显式释放状态、账号冲突分流、诊断基础设施和长期观测；达人级恢复与 scoped Contract breaker 由 AUTO-01 联动实现。

## 关联与依赖

前置：[UNIT-01](UNIT-01.md)、[AUTO-01](AUTO-01.md)。功能：F01（平台侧会话，非产品登录）、F10、F11。验收：T17—T20、T40。待验证：**U06**（会话识别与持久化）。

本卡直接更正 [技术方案§1.4](../AI达人智能发现与采集系统-完整技术方案.md) 与 [DEC-011](../decisions/DEC-011-automation-optimization.md) 中已撤回的"不能跨重启恢复"结论。

## 背景：两套互相矛盾的观测

| 观测 | 对象 | 结果 |
|---|---|---|
| 用户日常 Chrome（私用 profile） | 生产使用 | 首次登录后 **7-8 天**仍可直接进入后台，无需再登录 |
| 项目独立 profile（`unit-local-mac-02`） | 自动化采集 | 登录后约 **45 分钟**即失效：再次冷启动落在 `/?redirect_uri=/ad/creator/market`，账号元素不可读 |

原结论"不能跨重启恢复"来自 2026-09-28 的一次观测，但：

- [有界宿主真实运行证据](../evidence/AUTO-01-bounded-host-real-run-2026-09-28.md) 第 3.1 节**自述无法区分**"用户新登录"与"既有会话被接受"；
- 该结论所依赖的会话探针**只检查受保护元素是否可见，从未比对账号 ID**，而 `check_session` 与 `wait_for_manual_clearance` 都要求账号**精确等于** `expected_account_id`。因此"会话失效"存在**测量假象**可能。

## 验收清单

- [x] 假设登记：明确列出待区分假设及其判别特征，并记录先验依据。
- [x] 跨浏览器重启复用判定（首次）：同一 profile 在 `READY` 状态下以 `collect` 模式复用会话，`session_version` 不变、**未要求人工登录**——机制成立。
- [x] 探针正确性自查：确认判定依据必须是"账号 ID 精确一致 + 受保护业务能力可用"，不是"元素可见"；据此定位了历史误判来源。
- [x] 失效降级路径（部分）：会话/账号异常时任务进入 `WAITING_FOR_LOGIN`、单元进入维护；**未**因会话问题禁用平台契约。
- [ ] H1 跨客户端互踢：需在"其他客户端并发登录同一账号"条件下做对照实验（本轮 H-C 未排除）。
- [ ] H2 自动化风控：登录后仅静默不访问 vs. 立即访问搜索/主页，会话存活时长对照。
- [ ] H3 启动参数：`--disable-quic`、`--force-webrtc-ip-handling-policy=disable_non_proxied_udp` 的对照实验（优先级低于 H-A/H-B，因其不解释账号漂移）。
- [ ] **H-A/H-B 账号漂移根因**：判定 profile 是否并存多个账号登录态；若是，明确"单元 profile 只允许单一绑定账号"的检测与约束方式。
- [ ] 存活时长实测：测出会话失效的**时间下界与上界**（本轮仅知"至少存活约 20 分钟且跨越多次浏览器重启"，未测上界）。
- [ ] 结论回写：把根因结论写入技术方案、[AUTO-01](AUTO-01.md)、[UNIT-01](UNIT-01.md) 与 [DEC-011](../decisions/DEC-011-automation-optimization.md)（本轮已回写 SESSION-01 与本卡，其余待根因确定后统一回填）。
- [x] 结构化会话状态：五类 SessionHealth、`WAITING_FOR_ACCOUNT`、`SESSION_UNVERIFIED` 和显式 ReleaseDisposition 已实现；旧 READY 不再提前证明当前进程 Session。
- [x] 回收缺陷修复：过期 LEASED 可单步回收；隔离判定使用项目 `flock` + Chromium Singleton PID，不依赖 `/bin/ps`。
- [x] 诊断基础设施：`xingtu session-diagnostics` 记录 Cookie/Storage HMAC、浏览器环境、Profile mtime、IndexedDB 摘要与页面健康，不保存 Token 明文。
- [x] 离线/合成回归：105 单元 + 18 契约 + 51 集成 + 4 E2E，共 178 项通过；真实 Profile 未执行。

## 实现记录

2026-09-29：本卡建立，仅登记背景与待验证假设，尚未开始核验。

### 2026-09-29 实测暴露的缺陷：账号不匹配被误报为"需要登录"

两段式验收期间，项目 profile 实际登录的是 `ID: 1832740070238347`，而单元 `unit-local-mac-02` 绑定 `expected_account_id = ID: 1865332309937515`。此时：

- 受保护业务页**可用**（`div.search-content--header` 可见）；
- 会话**有效**（`flock` 空闲、`ID: 1832740070238347` 可读、无安全挑战）；
- 但 `check_session` 抛 `ACCOUNT_LOGIN_REQUIRED`，理由为 `WRONG_ACCOUNT`（[adapter.py:286-292](../../backend/src/xingtu/adapter.py)）。

结果是任务反复进入维护等待，用户反复被引导去"重新登录"，而真正要做的是**换用绑定账号**或**修改绑定**。`ACCOUNT_LOGIN_REQUIRED` 因此至少混装了三种互不相同的状况：

| 真实情况 | 现行错误码 | 是否恰当 |
|---|---|---|
| 会话真的失效 | `ACCOUNT_LOGIN_REQUIRED` | 恰当 |
| **会话有效但登录账号 ≠ 绑定账号** | `ACCOUNT_LOGIN_REQUIRED`（`WRONG_ACCOUNT`） | **不恰当，误导排障** |
| 受保护标记未渲染/冷启动竞态 | `ACCOUNT_LOGIN_REQUIRED` | 不恰当（分不清是登录问题还是页面问题） |

**2026-09-29 已实现**：账号不匹配已分离为 `ACCOUNT_MISMATCH`，根任务进入 `WAITING_FOR_ACCOUNT`，ExecutionUnit 不再被误标为 `NEEDS_LOGIN`；诊断结果保留 expected/observed account，但不自动改绑。

已具备但不充分的工具与环境：

- `xingtu session-diagnostics`：正式冷启动观测命令；记录结构化 SessionHealth、浏览器环境摘要及 Cookie/Storage HMAC 元数据，敏感值不明文落盘。
- `.runtime/exp-probe-session.py`：多 URL 探针，用于区分"会话失效"与"探针走错路径"。
- `xingtu research`（受控本地研究采集，[DEC-007](../decisions/DEC-007-contract-research-tooling.md)）：可在主机白名单与结构脱敏前提下观察真实页面状态。

已知工具局限（影响核验，需在结论中标注）：

- 历史探针**只验证元素可见**，未比对账号 ID，是历史误判的直接来源；正式诊断命令已经改为同时核对受保护页、账号、登录页和挑战。
- `recover-unit` 的历史 `/bin/ps` 依赖和两步协议已经修复；真实开发单元尚未用新路径执行回收，当前只有自动测试证据。

## 验证证据

2026-09-29 结构性修复实现与自动验证见 [实施证据](../evidence/SESSION-01-implementation-2026-09-29.md)。代码和离线/合成检查已完成；单账号清理、真实 5/10/20 和 30 天长测仍未执行，故状态为待验收而非已完成。

**完整证据见 [SESSION-01 两段式验收证据](../evidence/SESSION-01-acceptance-2026-09-29.md)**（含四次真实运行结果、审计时间线、问题清单、四个未验证推测及证据局限）。

### 已确认的两条结论

1. **会话跨任务复用成立（机制层面）**：单元为 `READY` 时以 `collect` 模式取得租约，`session_version` 不变、**未发生 promote、未要求人工登录**。会话跨越多次运行与浏览器关闭仍然有效。→ [DEC-012](../decisions/DEC-012-session-persistence.md) 的状态机改动按设计生效。
2. **账号在同一 profile 内漂移**：run 3 与 run 4 间隔约 3 分钟、无人工登录，实际账号却不同（`1865332309937515` → `1832740070238347`）。这是 run 2／run 4 失败的直接原因。

### 四次运行对照

| 运行 | 起始状态 | 实际账号 | 结果 |
|---|---|---|---|
| run 1 | `NEEDS_LOGIN` | 绑定账号 | ✅ `PARTIAL_COMPLETED`，有效 2 位 |
| run 2 | `READY` | 未确证 | ❌ `ACCOUNT_LOGIN_REQUIRED` ×2、`LEASE_LOST` ×2 |
| run 3 | `NEEDS_LOGIN` | 绑定账号 | ✅ `PARTIAL_COMPLETED`，有效 2 位 |
| run 4 | `READY` | **非绑定账号** | ❌ `ACCOUNT_LOGIN_REQUIRED:WRONG_ACCOUNT` ×3 |

### 未验证的推测（不得当作结论）

- **H-A（倾向）**：profile 内并存多个账号登录态，平台解析不稳定。理由：两轮间隔极短、无人工登录却账号不同；而会话与受保护页始终正常，说明不是平台不支持持久会话。
- **H-B（倾向）**：账号切换导致服务端会话被重新绑定，而非会话失效。
- **H-C**：未识别的外部因素改变了账号解析（本轮曾出现不持有 profile 锁的遗留 Chrome 窗口）。
- **H-D（优先级低）**：与 `BrowserRuntime` 注入的启动参数有关；只能解释"会话易失效"，**不能解释账号漂移**。

### 证据局限（必须保留）

各假设均为单次观测；本轮工作过程中**有两次过早结论被后续审计推翻**（曾判定 run 2／run 4"免登录成功"），故所有结论以审计与数据库为准；`run 2` 的实际账号未确证；未测出会话存活**上界**；未做"其他客户端并发登录"的对照，H-C 未排除。

### 历史相关证据（均不足以支撑任一方向结论）

- [有界宿主真实运行](../evidence/AUTO-01-bounded-host-real-run-2026-09-28.md)：同一上下文交接通过；第 3.1 节自述会话来源存在歧义。
- [当前账号能力与字段盘点](../evidence/AUTO-01-current-account-inventory-2026-09-28.md)：记录"关闭后重启的受保护会话复核失败"，但同样未比对账号 ID。

其余历史相关证据（均**不足以**支撑任一方向结论）：

- [有界宿主真实运行](../evidence/AUTO-01-bounded-host-real-run-2026-09-28.md)：同一上下文交接通过；第 3.1 节自述会话来源存在歧义。
- [当前账号能力与字段盘点](../evidence/AUTO-01-current-account-inventory-2026-09-28.md)：记录"关闭后重启的受保护会话复核失败"，但同样未比对账号 ID。
- 2026-09-29 本次会话观测（**未形成证据文档，结论待复核**）：同一 profile 直接导航受保护页，3/3 冷启动在**第 2 次导航**后 `search_ui_ready=true`；但同一 profile 在一次维护流程后停在登录页，且约 45 分钟后完全失效。二者矛盾，正是本卡要解决的对象。

### 2026-09-29 独立测试轮新增证据（账号不可读的第 5 次复现）

在 F04/F05 真实核心流程测试中（[证据](../evidence/F04-F05-real-core-flow-2026-09-29.md)）：

- **同一 profile 内人工登录成功并采集成功后，任何新 Chrome 进程都取不到账号**：任务内计数 5 次（运行 D 2 次、运行 B 1 次、运行 C 2 次）＋ 1 次独立诊断冷启动，全部为 `SESSION_INDETERMINATE` / `PROTECTED_PAGE_ACCOUNT_UNREADABLE` / `observed_account_id=null`。
- **独立诊断命令复现**（非采集路径）：[session-diagnostics 报告](../evidence/F04-F05-session-diagnostics-2026-09-29.json) 显示 `protected_page_verified=true`（受保护页可见）、49 个 oceanengine SSO Cookie（含 `d_ticket`/`odin_tt`/`sid_ucp_sso_v1`，仅 HMAC）、`login_page_verified=false`、`challenge_verified=false`，但账号元素读不出值。即"**会话看起来是活的、账号却读不到**"，与 H-A/H-B（profile 内并存多账号／会话被重新绑定）方向一致，但**仍不能据此判定根因**。
- **用户现场观察（未由本轮独立验证）**：人工登录的是 A 账号（绑定 `ID: 1865332309937515`），最近唤起的 Chrome 实际显示 **B 账号**。这与本卡"账号漂移"结论一致，并把漂移与"账号元素不可读"关联起来。
- **新增缺陷（降级路径缺失）**：`SESSION_INDETERMINATE` 不触发人工登录维护窗口（`worker.py` 维护分支只接受 `NEEDS_LOGIN`/`ACCOUNT_MISMATCH`），任务只在 `WAITING_FOR_RESOURCE` 上有限重试。测试期间必须由人工执行 `Repository.invalidate_session(...)`（审计动作 `invalidate_session:unit-local-mac-02:PROTECTED_PAGE_ACCOUNT_UNREADABLE`）才能打开登录窗口继续。
- **仍未取得**：漂移根因（H-A/H-B 未区分）、会话存活上界、跨重启复用成功案例（本轮所有成功均发生在人工登录后的同一进程内）。

## 交接信息

- 阻塞项：无。核验需要用户配合（人工登录一次），且核验期间**不得用其他客户端登录同一星图账号**，否则 H-C 无法排除。
- 遗留问题：① 账号漂移根因未定（H-A/H-B 优先）；② 会话存活上界未测；③ 真实平台 5/10/20 与新恢复路径尚未验收。
- 下一步（按优先级）：
  1. **判定 profile 是否并存多账号登录态**；同时让用户在项目 Chrome 内彻底退出全部账号后只登绑定账号，再跑两段式验收，观察账号是否仍漂移。
  2. 使用 `xingtu session-diagnostics` 建立 0/15/30/45/60 分钟到 30 天的分阶段基线。
  3. 在真实环境复验账号冲突状态和过期租约单步回收。
  4. 完成真实 5/10/20 位连续采集；满足前置契约后再决定是否执行 50/100。

## 状态历史

- 2026-09-29T11:05:00+08:00：建立 → 待办。原"会话不能跨重启恢复"结论被判定证据不足并撤回；用户需求"登录一次可存活 1 个月"与现有实现存在差距，独立建卡核验。
- 2026-09-29T11:55:00+08:00：待办 → 进行中。完成首次两段式真实验收（4 次运行）：确认**会话跨任务复用机制成立**（`READY` 单元以 `collect` 复用、无 promote、无登录要求），但发现**账号在同一 profile 内漂移**（run 3 `1865332309937515` → run 4 `1832740070238347`），成为任务失败直接原因；同时登记 P1 错误归因、P3 回收协议与 `/bin/ps` 缺陷。完整证据见[两段式验收证据](../evidence/SESSION-01-acceptance-2026-09-29.md)。因根因未定，状态为进行中，不勾选整卡。
- 2026-09-29T13:25:37+08:00：进行中 → 待验收。用户批准结构性方案后完成迁移 006、五态 SessionHealth、显式 ReleaseDisposition、账号冲突分流、冷启动强制复验、单步安全回收和 HMAC 诊断工具；AUTO-01 联动完成首次身份不可读后的 Session 复核、达人级重试/跳过与 scoped breaker。178 项离线/合成测试通过；真实单账号与长期/规模验收未执行。
- 2026-09-29T13:46:05+08:00：待验收 → 待验收。迁移 006 已应用并只读确认本地开发库版本 1—6 与新表；真实 Profile、Session 和平台任务未触碰，剩余真实验收不变。
- 2026-09-29T13:50:33+08:00：待验收 → 待验收。补齐 scoped breaker 紧急回滚开关并完成 178 项最终回归；真实验收缺口不变。
- 2026-09-29T14:56:37+08:00：待验收 → 待验收。独立测试轮（F04/F05 真实核心流程）新增第 5 次账号不可读复现与独立诊断证据（受保护页可见 + SSO Cookie 齐全 + `observed_account_id=null`），并登记新缺陷：`SESSION_INDETERMINATE` 不会打开人工登录窗口，只能人工 `invalidate_session` 才能继续。用户现场观察到 A/B 账号漂移。漂移根因、存活上界与跨重启复用成功案例仍未取得。
