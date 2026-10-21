# SESSION-01：平台会话真实存活时长核验

状态：进行中
更新时间：2026-10-21T17:03:26+08:00（Asia/Shanghai）
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
- [ ] **H-A/H-B 账号漂移根因**：判定 profile 是否并存多个账号登录态；若是，明确"单元 profile 只允许单一绑定账号"的检测与约束方式。（2026-10-05：漂移现象已复现、载体收敛到 `star_sessionid`，见[证据](../evidence/account-drift-probe-2026-10-05.md)；H-A 与 H-B **仍未区分**，故不勾选。2026-10-06：新增**可用规避**路径——清除旧身份后改绑到"只含单一子账号"的新登录身份，两次独立冷启动判定 `STABLE`，见[改绑证据](../evidence/SESSION-01-account-rebinding-2026-10-06.md)；根因本身仍未区分，该项保持不勾选。）
- [ ] 存活时长实测：测出会话失效的**时间下界与上界**（本轮仅知"至少存活约 20 分钟且跨越多次浏览器重启"，未测上界）。2026-10-12 新增下界数据点：上次进程内确证（01:12:41+08）后，**14.4 小时后**再次冷启动仍为 `VALID` 且账号一致（见[会话实时只读核验证据](../evidence/UNIT-01-session-live-check-2026-10-12.md)）；**上界与失效条件仍未测**，故不勾选。
- [ ] 结论回写：把根因结论写入技术方案、[AUTO-01](AUTO-01.md)、[UNIT-01](UNIT-01.md) 与 [DEC-011](../decisions/DEC-011-automation-optimization.md)（本轮已回写 SESSION-01 与本卡，其余待根因确定后统一回填）。
- [x] 显式账号改绑：迁移 007 + `Repository.rebind_unit_account` + `xingtu rebind-account` 已实现；改绑带操作者/原因/证据、宿主占用时拒绝、自动化路径仍不可变更身份；集成测试覆盖。
- [x] 混合持久化与冷启动引导：持久目录 + storage-state 显式注入（会话有效时导出、下次启动首次导航前注入、只在保护页可读时覆盖），冷启动引导改为有界重试 + 短探测；对照实验证明注入快照决定"能否进入后台"。单元 114 + 契约 22 通过。**存活上界与长期稳定性仍未测，故本项只勾"机制已实现并现场验证"，不代表验收通过。**
- [x] 结构化会话状态：五类 SessionHealth、`WAITING_FOR_ACCOUNT`、`SESSION_UNVERIFIED` 和显式 ReleaseDisposition 已实现；旧 READY 不再提前证明当前进程 Session。
- [x] 回收缺陷修复：过期 LEASED 可单步回收；隔离判定使用项目 `flock` + Chromium Singleton PID，不依赖 `/bin/ps`。
- [x] 诊断基础设施：`xingtu session-diagnostics` 记录 Cookie/Storage HMAC、浏览器环境、Profile mtime、IndexedDB 摘要与页面健康，不保存 Token 明文。
- [x] 离线/合成回归：105 单元 + 18 契约 + 51 集成 + 4 E2E，共 178 项通过；真实 Profile 未执行。

## 实现记录

2026-09-29：本卡建立，仅登记背景与待验证假设，尚未开始核验。

2026-10-13：用户报告执行单元的巨量星图账号态失效并请求人工重新登录。开始登录维护前只读核对发现专属 profile `unit-local-mac-02` 仍持有 Chrome `SingletonLock`（PID 10613，锁文件时间 08:43+08:00）；不会启动第二个实例或改动 profile，改为向该既有实例发送受保护业务页打开请求，交由用户完成验证码／登录操作。

2026-10-13 15:41+08:00：已向该 profile 的现有 Chrome 实例发送 `https://www.xingtu.cn/ad/creator/index` 并将 Chrome 置前台；`SingletonLock`、`SingletonSocket`、`SingletonCookie` 均刷新到 15:41:15+08:00，证明请求已由该 profile 的实例接收。未读取 Cookie、未执行搜索／采集，也不会把“窗口打开”误记为登录成功；待用户完成交互后再做受控会话核验。

2026-10-13 15:46+08:00：用户确认已在该窗口登录，并明确要求将会话长期复用。核对现有实现与运行态：`UnitConfig.capture_session_snapshot=true`，`BrowserRuntime` 会在受保护业务页与绑定账号验证后，将完整 `storage_state` 写入私有 `.runtime/profiles/storage-state/unit-local-mac-02.json`（目录 `0700`、文件 `0600`），下次启动首个导航前再注入；这是对会话型业务 Cookie 的正确持久化路径。当前 profile 的 `Default/Cookies` 与 `Local State` 已在 15:44+08:00 更新，但专用快照仍不存在。为不并发打开当前仍占用 profile 的 Chrome，不读取／复制 Cookie 数据库；需先正常关闭**该执行单元 Chrome 窗口**，然后以受控 `BrowserRuntime` 冷启动核验并导出快照。

2026-10-13 15:49—15:51+08:00：用户关闭窗口后尝试受控 `xingtu session-diagnostics`。首次沙箱内启动被 macOS Mach/Crashpad 权限拒绝，未访问 profile；经授权重试时 Chrome 明确输出“正在现有的浏览器会话中打开”，且 `SingletonLock` 仍指向 PID 18738，说明窗口关闭并未使执行单元的 Chrome 进程退出。受控 Runtime 因而无法取得独占 profile、快照仍不存在；未尝试复制锁定的 Cookie 数据库或删除 Singleton 文件。需要用户以“退出 Chrome”（而非只关窗口）的方式释放该执行单元实例，再重试冷启动核验与快照导出。

2026-10-13 15:57+08:00：受控核验产生脱敏报告，结果为 `INDETERMINATE / PROTECTED_PAGE_ACCOUNT_UNREADABLE`（受保护页可见、登录页与挑战均未见、绑定账号元素不可读），不满足快照导出的“受保护页 + 账号精确匹配”门槛，因此 `.runtime/storage-state/unit-local-mac-02.json` 仍不存在。按登记的准确登录入口 `https://sso.oceanengine.com/xingtu/login?role=1` 尝试重新打开专属 profile 时，Chrome 在创建 `SingletonLock` 阶段返回 `No space left on device` 并主动中止，以避免 profile 损坏；当时 Data 卷仅余 101 MiB。未写入、复制或泄露 Cookie／Storage 值。

2026-10-13 15:59+08:00：用户已恢复本机空间；只读核对 Data 卷可用空间约 17 GiB、profile 未见 `Singleton*` 锁文件，先前磁盘阻断解除。开始按已登记 SSO 登录入口重新建立受控登录维护，完成后仍须以账号精确匹配为门槛才导出快照。

2026-10-13 16:07—16:08+08:00：以专属 profile 成功打开并置前台已登记入口 `https://sso.oceanengine.com/xingtu/login?role=1`；新的 `SingletonLock` 指向 PID 20167，Cookies／Local State 均更新。当前仅等待用户在**该窗口**完成平台正常登录；不把窗口／文件更新时间视为登录成功，后续仍需安全交接、精确账号验证及私有 storage-state 导出。

2026-10-13 16:14—16:16+08:00：用户确认已登录后，正常关闭专属 Chrome 并以受控 Runtime 冷启动核验。新脱敏报告 `unit-local-mac-02-20261013T081546Z.json` 显示 46 个 Cookie（其中 5 个会话型），但 `SessionHealth=INDETERMINATE / PROTECTED_PAGE_ACCOUNT_UNREADABLE`：受保护业务页可见，未见登录页或挑战页，**绑定账号 ID 仍不可读**。因此不满足“受保护页 + 账号精确匹配”的持久化门槛，`storage-state` 快照保持不存在；未执行搜索／采集，也未把 Cookie 值写入卡片或证据。需先恢复账号身份可读性／确认当前业务页面身份，才能安全导出长期复用快照。

2026-10-13 16:17—16:20+08:00：用户确认该登录身份只有唯一子账号 `ID: 1807978499337419`，且手工 Chrome 显示已登录。为区分“登录无效”与“定位器失效”，在禁用快照导出的受控 Runtime 中执行三次只读 DOM 结构探针：① 业务页 `/ad/creator/index` 有 1 个受保护菜单标记，但旧账号选择器匹配 0，整页无绑定 ID 或 `ID:<数字>`；② 账户管理页 `/ad/user-center/user/account/auth` 亦无绑定 ID／登录表单；③ 页面仅一个同源 iframe，仍无 ID。结论：平台当前 UI 未提供可自动比对的账号 ID，旧定位器确已失效；不能以 CSS 更新修复。用户的“唯一子账号”人工确认可作为审计证据，但若改为自动放行／导出会话的替代身份门槛，将改变既有“精确账号验证”安全契约，等待用户明确授权该降级策略或提供平台可验证的身份入口。

2026-10-13 16:39—16:48+08:00：用户明确授权唯一子账号人工确认后，实施 [DEC-016](../decisions/DEC-016-manual-identity-attestation.md)：仅 `local_development`、账号必须精确匹配、必须记录操作者／原因／批准与截止时间、最长 31 天；账号可读但不一致、登录页和安全挑战仍优先拒绝。随后三次真实 Chrome 冷启动诊断均不执行搜索或采集。最终报告 `unit-local-mac-02-20261013T084837Z.json` 为 `VALID / MANUALLY_ATTESTED_UNIQUE_ACCOUNT`，受保护页为真、登录页／挑战为假，且 `session_snapshot.restored_before_navigation=true`；说明上一次私有快照在本次首个导航前已注入并复用。快照路径 `.runtime/profiles/storage-state/unit-local-mac-02.json` 存在，目录 `0700`、文件 `0600`，未向文档、日志或前端写入 Cookie／Token 明文。完整脱敏证据见[本轮快照核验](../evidence/SESSION-01-manual-attestation-snapshot-2026-10-13.md)。

### 2026-10-21 当前登录状态实时核验（未改代码）

用户要求查看当前执行单元的巨量星图登录状态。当前只有一份有效开发单元配置 `.runtime/units/local-dev-mac-02.json`，对应 `unit-local-mac-02`。执行只读 `xingtu session-diagnostics`：首次沙箱内启动在访问平台前被 macOS Crashpad/Mach 权限拒绝（exit 1，不属会话结论）；同一命令在允许 Chrome 正常启动的环境重试成功（exit 0）。报告 `unit-local-mac-02-20261021T085856Z.json` 显示 `VALID / PROTECTED_PAGE_AND_ACCOUNT_VERIFIED`，`observed == expected == ID: 1807978499337419`，受保护页 `true`，登录页／挑战 `false`，私有快照在首次导航前恢复，Chrome `156.0.8078.47` 正常关闭。本轮未搜索、未采集、未重新登录、未写业务库；报告与快照权限均为 `0600`。证据见[实时只读核验](../evidence/SESSION-01-session-live-check-2026-10-21.md)。

### 2026-10-14 登录状态核验与“快速失效”根因复盘（未改代码）

用户再次询问执行单元星图登录状态是否有效，并在失效时要求唤起 Chrome 人工登录，同时要求记录“为什么登录状态这么快失效”的原因备用。实际执行：

1. **只读核验（有效）**：`xingtu session-diagnostics --config .runtime/units/local-dev-mac-02.json`，`2026-10-14T15:49:46 → 15:49:53+08:00`，exit `0`；报告 `unit-local-mac-02-20261014T074953Z.json` 为 `VALID`，`observed == expected == ID: 1807978499337419`、受保护页 `true`、登录页／挑战 `false`、`restored_before_navigation=true`、Chrome `155.0.8059.40`、`normal_close_confirmed=true`。**这是快照路径首次在账号 DOM 可读条件下的 `VALID`**（此前三次 `VALID` 均依赖 `MANUALLY_ATTESTED_UNIQUE_ACCOUNT`）。未搜索、未采集、未写业务库。
2. **存活下界更新**：快照首写 `2026-10-13T16:48+08` → 本轮 `2026-10-14T15:49+08`，**约 29 小时、3 次冷启动**会话仍被平台接受且账号无漂移。上界仍未测。
3. **“很快失效”的根因**：业务会话载体 `.xingtu.cn/star_sessionid` 是**会话级 Cookie**（`expires=-1`），进程退出后不会自行留在磁盘；登录态能否跨重启完全取决于私有 `storage-state` 快照。而 **2026-10-13 16:48 之前从未产出过快照**（当时报告均为 `PROTECTED_PAGE_ACCOUNT_UNREADABLE`，身份门槛不满足），所以那时每次关闭 Chrome 都真的丢掉会话，用户感知即“刚登录很快就失效”。次要放大器：Playwright 默认 `--use-mock-keychain` 与系统 Keychain 不兼容（已由 `macos_system_keychain` 缓解，绕过项目启动器仍会复现）、多子账号漂移导致 `ACCOUNT_MISMATCH`（已由单一子账号身份规避，根因 H-A/H-B 未区分）。**目前没有证据支持“平台会话本身只有几十分钟寿命”。**
4. **记录的待优化缺口**（写在本轮证据第 3.4/4 节，不在本轮实施）：① 快照写入只在“导航事件 + 4 秒防抖 + 页面判定”兜底路径上，详情页结束或无导航的有效会话可能整轮不落盘；② 快照准入门槛与身份门槛耦合，`DEC-016` 人工确认 `2026-11-12T16:39:32+08:00` 到期后不可读仍会重现该循环；③ `_restore_session_snapshot` 失败静默、无“快照年龄/注入结果”可观测字段；④ 无阶段性巡检，只能在采集时才发现失效；⑤ H1 跨客户端互踢未排除。
5. **Chrome 唤起**：核验后按用户要求以执行单元专属 profile 打开 `https://www.xingtu.cn/ad/creator/index`（PID 36251）供人工查看/登录。无需重新登录。注意：窗口开着时单元 profile 被占用，采集会以 `PROFILE_IN_USE` 失败，用完必须 `Command-Q` 完全退出。

证据：[登录状态核验与快速失效根因记录](../evidence/SESSION-01-login-lifetime-root-cause-2026-10-14.md)。本卡状态与其余验收项不变。

### 2026-10-06 用户决策：舍弃旧登录身份，改用单子账号身份并显式改绑

本节之后（同日 18:01）追加：**混合持久化修复 + 冷启动引导修复**，使"同一 profile 有时在登录态、有时被踢回登录页"的问题不再阻塞采集。两处改动及对照实验见[宠物 22 位采集效果测试报告](../evidence/pet22-crawl-test-2026-10-06.md)第 3 节。

用户在 2026-10-05 复核结论（"切换目标子账号会被平台回退到 `1832740070238347`"）之后决定**不再与旧身份纠缠**：清除执行单元内已登录的巨量星图账号与缓存，改用**只含单一子账号的新巨量星图账号**做后续功能验收，以规避无法自动纠正的子账号漂移。

- **清空**：隔离验证（`flock` 空闲 + `SingletonLock` PID 不存在）后备份 `unit-local-mac-02` profile 到 `.runtime/profiles/unit-local-mac-02.bak-20261006T161500`（200 MiB），再删除重建为空 profile。
- **重登**：因 Temporal（57233）未运行，未使用 `xingtu login` 的 Worker 维护窗口，改用同一 `BrowserRuntime` 的探针登录窗口（`scripts/account_drift_probe.py --await-login-seconds`）唤起真实 Chrome；人工登录后冷启动读到新账号 `ID: 1807978499337419`（受保护业务页可见）。
- **改绑（新增能力，此前不存在）**：迁移 [007_unit_account_rebinding.sql](../../migrations/007_unit_account_rebinding.sql) 新增 `unit_account_rebindings` 审计表；`Repository.rebind_unit_account` 与 CLI `xingtu rebind-account` 提供**显式、带操作者/原因/证据引用**的改绑，宿主占用单元时拒绝执行，并强制把单元置为 `SESSION_UNVERIFIED` 以重新观测新身份。`register_unit` 与 `ACCOUNT_MISMATCH` 路径**仍不允许**自动改绑（原有约束不变）。CLI 要求单元配置文件先行携带同一身份，避免"库里已改、启动仍用旧配置"的分裂。
- **改绑结果**：`expected_account_id` = `ID: 1807978499337419`、`verified_account_id` = `NULL`、`state` = `SESSION_UNVERIFIED`、`failure_reason` = `ACCOUNT_BINDING_CHANGED`；审计行记录 `previous_config_account_id = ID: 1865332309937515`（旧绑定只存在于单元 JSON，从未落库，故 `previous_account_id` 为 `NULL`，由新增列如实记录）。
- **规避有效性验证**：改绑后两次独立冷启动（间隔 10 秒）判定 **`STABLE`**，实测账号恒为 `ID: 1807978499337419`、身份 Cookie 跨轮**零变化**，与改绑前"重启即回退到 `1832740070238347`"形成对照。证据见[改绑与漂移规避证据](../evidence/SESSION-01-account-rebinding-2026-10-06.md)。
- **未改变的部分**：漂移**根因**（H-A/H-B）仍未区分，本轮只是把身份换成"平台无法在多个子账号间选择"的形态；冷启动首跳仍会先重定向到 `/?redirect_uri=...`，需第二次进入业务页才可读账号。

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

2026-10-21（真实平台，只读会话核验）：`xingtu session-diagnostics --config .runtime/units/local-dev-mac-02.json` 在允许 Chrome 正常启动的本机环境 exit `0`；结果 `VALID`，账号精确一致，受保护页可用，无登录页、无安全挑战，快照在首次导航前恢复，浏览器正常关闭。首次受限沙箱尝试因 macOS Crashpad/Mach 权限在访问平台前失败，不计为会话失效。完整边界与脱敏证据见[实时只读核验](../evidence/SESSION-01-session-live-check-2026-10-21.md)。本轮不改变长期存活上界、漂移根因等未完成验收项，卡片仍为进行中／未验收。

2026-10-13：本轮实现与真实冷启动结果见[唯一子账号人工确认与会话快照核验](../evidence/SESSION-01-manual-attestation-snapshot-2026-10-13.md)。离线验证：定向 `ruff check`、`mypy backend/src/xingtu` 通过，`backend/tests/unit/test_session_snapshot.py` **7 passed**；全量 `make check` exit 0（ruff／format／mypy、后端单元 **189 passed**、前端 typecheck／Vitest **3 passed**／build）。新增浏览器契约覆盖人工确认仅在身份不可读时生效、错误账号／登录页／挑战页必定优先拒绝。本机 Playwright bundled Chromium 未安装，故 `backend/tests/contract/test_session_recovery.py` 的 3 项（含该新增用例）均在启动阶段因可执行文件缺失失败，非断言失败；真实绑定 Chrome 的三次冷启动已经覆盖当前配置的正向复用路径，负向分支保留待具备测试浏览器后复跑。

2026-09-29 结构性修复实现与自动验证见 [实施证据](../evidence/SESSION-01-implementation-2026-09-29.md)。代码和离线/合成检查已完成；单账号清理、真实 5/10/20 和 30 天长测仍未执行，故状态为待验收而非已完成。

2026-10-05 诊断链修复与浏览器 A/B 载体见[子账号诊断链实施证据](../evidence/SESSION-01-subaccount-diagnostics-implementation-2026-10-05.md)：页面跳转后点击不丢、脱敏请求—响应—会话关联、Playwright locator 点击及 A/B 参数已实现；探针自检和 2 项真实 Chrome+合成路由契约用例通过。真实 A 组窗口已打开，等待操作者完成两个非默认子账号的对照；正式 Adapter 选号仍保持关闭。

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

### 2026-10-05 漂移专项检测工具与首个已确认结论

新增只读探针 [account_drift_probe.py](../../scripts/account_drift_probe.py)（不点击、不登录、不切换账号；Cookie/Storage 只记 HMAC）。它把过去混在一起的三种现象拆开判定：`DRIFT_WITHIN_PAGE`（同页反复读就变）、`DRIFT_WITHIN_PROCESS`（同进程跨页面/标签页变）、`DRIFT_ACROSS_RESTART`（重启 Chrome 后变，与 run 3→run 4 同型），并把账号定位器匹配数、iframe 内匹配数、**单页内出现的不同 `ID:` 数量**（H-A 的直接判据）与凭证指纹同步记录，用于载体定位。人工登录期间探针不导航，人工窗口内的观测单独统计且不计入漂移判定（避免把操作者主动换号误报为平台漂移）。

**离线自检（不代表平台验证）**：`ruff`/`format` 通过；`--self-test` 7 项判定用例 + 2 项载体/人工窗口用例全部通过。

**本卡首个经用户现场确认的结论**：登录后平台的子账号选择列表**可见且可选** `ID: 1865332309937515`。据此可排除「当前登录的父账号无权访问目标子账号」这一分支，问题指向**自动化流程缺少"选定目标子账号"步骤**：契约 `session` 段只有入口地址、账号定位器与受保护页标志，**没有任何"选择账号"动作**（[契约](../../contracts/douyin_xingtu.verified.json)），代码也只"读"不"选"（[adapter.py:275-292](../../backend/src/xingtu/adapter.py)）。即平台解析成谁、系统就是谁，系统只能检测 `ACCOUNT_MISMATCH` 而无法纠正。

**文档缺口（需产品侧补齐）**：`子账号 / 主账号 / 切换账号` 在 `docs/` 与 `backend/` **全仓零命中**；技术方案 U06 要求"账号识别及会话验证"（[技术方案:977](../AI达人智能发现与采集系统-完整技术方案.md)），但从未定义"子账号"概念与选号流程。

**profile 重置（绑定未改动）**：已备份 `.runtime/profiles/unit-local-mac-02.bak-20261005T105927`（116M）后删除重建。`expected_account_id` 属不可变绑定，本次未触碰，故无需审计改绑。

**真实观测结果（退出码 1，判定 `IDENTITY_CHANGED_WHILE_UNREADABLE`）**：完整证据见 [账号漂移专项检测证据](../evidence/account-drift-probe-2026-10-05.md)，原始报告 [account-drift-probe-2026-10-05.json](../evidence/account-drift-probe-2026-10-05.json)。

| 轮次 | 导航栏读到 | 页面正文出现的 ID | 受保护页 | 定位器匹配数 |
|---|---|---|---|---|
| 0 人工登录并**选定目标子账号**后 | `ID: 1865332309937515` | `1865332309937515` | 可见 | 1 |
| 1 同一 profile **重启 Chrome 后**、无人工介入 | **读不到** | **`1832740070238347`** | **不可见** | **0** |

- **漂移已复现**：间隔约 3 分钟的一次 Chrome 重启后，生效账号由绑定账号变为 `1832740070238347`（与 run 4 漂移账号一致）。轮 0 在同一进程内跨页面、同页反复读 4 次、返回导航、第二标签页**始终**是目标账号，据此排除"页面场景差异"与"多标签页读到不同账号"两种解释。
- **D1 成因得到解释**：漂移后当前子账号无法渲染星图受保护应用壳 → 定位器匹配数为 0、受保护页不可见 → 系统只能得到 `SESSION_INDETERMINATE`。即 **D1 与账号漂移是同一事件的两个视角**，D1 是"错误账号"被**误分类**为"会话不可判定"。
- **载体收敛**：跨重启唯一变化的身份 Cookie 是 `cookie:.xingtu.cn/star_sessionid`；SSO 登录层与 `sessionid`/`uid_tt`/`has_biz_token`/`is_staff_user` 均逐字节未变，**`possess_scene_star_id` 与 `session_tlb_tag` 也未变**——此前"`possess_scene_star_id` 是漂移载体"的推测被本轮数据**否定**。
- **自我纠错（必须保留）**：首次自动判定误输出 `STABLE`（整轮不可读被跨轮比较静默忽略）。已修正判定逻辑并新增 `IDENTITY_CHANGED_WHILE_UNREADABLE` / `SESSION_NOT_OBSERVABLE` 两态与回归自检，再用 `--reanalyse` 对**同一份已保存报告**离线复算得到上述结论，未重跑浏览器、未改动观测数据。

**仍未完成**：H-A 与 H-B 仍未区分（本次只证明"生效账号发生改变"，不足以区分平台侧重新绑定与 profile 内多账号声明）；漂移属"重启触发"还是"时间触发"未测。

### 2026-10-05 最小验证：存储结构 / 默认子账号 / 自动选号 / 保持性

完整证据见[最小验证证据](../evidence/account-drift-probe-2026-10-05-minimal-verification.md)，原始报告 [验证 A](../evidence/account-drift-probe-verifyA-2026-10-05.json)、[验证 B](../evidence/account-drift-probe-verifyB-2026-10-05.json)。

| 问题 | 结论 |
|---|---|
| 子账号是否被客户端持久保存 | **未发现任何持久化记录**：`localStorage` 的 `STAR_*_LOCAL_STORAGE_KEY` 均为**空数组**；有内容的是 `sessionStorage` 的 `STAR_*_SESSION_STORAGE_KEY`（字段 `slogan`/`is_step_guide`/`queue_type`，更像引导/队列数据，非子账号描述）。承载者更可能在**服务端** |
| 重启后是否落到默认子账号 | **是**，两次独立验证均落到 `1832740070238347`。且冷启动时 SSO 登录在、`star_sessionid` **缺失**——**停在 SSO 入口页永远不会签发业务会话**，必须访问业务页引导 |
| 自动选号能否做到 | **尚未做到**。已定位并排除"账号信息弹层"（`el-popover__reference-wrapper` → `navigator-account-info` → `header.star-navigator`），该弹层只显示当前账号；真正的选号入口未定位，按规范**不猜选择器** |
| 选中能否跨重启保持 | **不能**。轮 0 选定绑定账号后同进程内全程稳定（13 条可读、跨页面/标签页/反复读），间隔 3 分钟重启后即回到 `1832740070238347` |

**关键推论**：① 自动选号由"可选"升级为**必需**，且必须**每个新 Chrome 进程执行一次**；② "在保存的 Cookie 中增加子账号信息"**不可行**（服务端签发并校验，且客户端无对应槽位）；③ 冷启动必须包含"访问业务页引导会话"步骤。

**漂移的两种表现已统一**：验证 A 中导航栏正常渲染并读出另一账号，系统自身给出 `ACCOUNT_MISMATCH`；首次复现中业务壳未渲染，系统只能给 `SESSION_INDETERMINATE`。即 **D1 与 `WRONG_ACCOUNT` 是同一次漂移的不同表现**，取决于重启后业务壳是否渲染成功。

**阻塞**：定位真正的子账号选择入口需要操作者提供人工切换路径（在哪个元素点击、弹层还是独立页面、列表形态），以便按实际 DOM 登记契约。**自动化选号的可行性与保持性仍未验证**。

**自我纠错（第 3 次）**：验证 B 首次自动判定误输出 `STABLE`（账号全程为另一账号、从不等绑定账号，属"稳定地错"）。已新增 `PERSISTENT_ACCOUNT_MISMATCH` 判定与回归自检（现 10 项判定 + 2 项载体/人工窗口），并用 `--reanalyse` 离线复算两份报告得 `DRIFT_ACROSS_RESTART` 与 `PERSISTENT_ACCOUNT_MISMATCH`，未重跑浏览器、未改动观测数据。

### 2026-10-05 选号入口定位 + 操作者关键观察（会话内回退）

**选号入口已用"记录操作者真实点击"方式定位（不再猜测）**，证据见 [点击记录](../evidence/account-drift-probe-clicks-2026-10-05.json)：

- 账号弹层由 **hover** 打开（JS `click()` 无效——这正是此前逐级点击祖先链全部失败的原因）；祖先链为 `span.el-popover__reference-wrapper` → `div.navigator-account-info` → `header.star-navigator`。
- 弹层内 `button.change-account-button`（文本"切换"）位于 `div.navigator-user-popover__header` → `div.navigator-user-popover` → `div.el-popover.el-popper.navigator-user__popover`。
- 点击"切换"后还会导航到**独立选号页** `https://www.xingtu.cn/ad/user-center/user/account/auth`。
- 点击后枚举到的候选账号 **4 条、3 个不同 ID**：`1832740070238347`（当前）、`1831973402720484`、**`1865332309937515`（绑定目标，在列表中存在）**。

**自动选号仍未成功**：按上述 DOM 实现 hover→JS 点击后，`span.el-popover__reference-wrapper` / `div.navigator-account-info` / `div[class*="navigator-user"]` / `header.star-navigator [class*="account"]` 四种触发器 hover 后最多只枚举到 1—2 条候选，**目标条目始终不可见**（`TARGET_NOT_VISIBLE_AFTER_HOVER`）；而人工真实点击时同一步骤可见 4 条。→ 说明**该列表需要真实鼠标交互/延迟才会完整渲染**，纯脚本 hover 不足以触发。

**操作者关键观察（2026-10-05，未由脚本独立复核）**：登录后人工切换账号时，**无论怎么点击目标 `1865332309937515`，弹窗关闭后平台都会自动回到 `1832740070238347`**。若成立，则问题不止"重启后漂移"，而是**平台在同一会话内即拒绝/回退目标账号**；这也与"三次尝试选 515 全部回到 347"的脚本结果方向一致（目标条目未能被脚本点击到，无法排除脚本因素）。

**待判定（决定方案走向）**：切换到第三个账号 `1831973402720484` 是否**能保持**？
- 若能保持 → 只有 `1865332309937515` 被拒绝 → 该绑定账号当前对本次登录不可用，应走**审计改绑**或更换登录身份，属产品决策。
- 若任何账号都保不住 → 会话被服务端锁定在 `1832740070238347`，属平台侧会话绑定问题，自动选号无法解决。

## 交接信息

- 阻塞项：本轮身份不可读阻塞已解除：用户明确授权的、最长 31 天人工确认已受限启用，并完成私有快照的跨冷启动复用验证。不会自动延长或静默替代可读账号校验。
- **当前会话（2026-10-21T16:58:54+08:00 实测）**：`unit-local-mac-02` 为 `VALID`，账号精确匹配 `ID: 1807978499337419`，受保护页可用，无登录页和挑战，快照恢复成功；无需重新登录。该结论仅代表当前时点，不代表已测出存活上界。
- 遗留问题：① 账号漂移根因未定（H-A/H-B 优先，本轮仅规避未区分）；② 会话存活上界未测，平台仍可随时使会话失效；③ 人工确认于 `2026-11-12T16:39:32+08:00` 到期；④ 浏览器契约 3 项因本机 Playwright bundled Chromium 缺失未执行到断言；⑤ 真实平台 5/10/20 与新恢复路径尚未验收；⑥ 改绑后尚无一次**真实业务采集**在新身份下跑通。
- 下一步（按优先级）：
  1. **在新绑定下跑一次真实小规模采集**（如 `target_count ≤ 3`）并观察是否仍出现账号相关维护窗口；这是 F04/F05 后续验收的前置。
  2. **区分 H-A 与 H-B**：本次已证明"生效账号改变"并收敛载体到 `star_sessionid`，下一步需对照实验区分"平台侧重新绑定"与"profile 内多账号声明导致解析不稳定"。
  3. **测漂移触发条件与时间窗**：多轮重复，区分"重启触发"与"时间触发"；新身份下重新测量。
  4. **产品侧补需求**：`子账号` 概念在 `docs/`、`backend/` 零命中，需在 PRD/技术方案中定义"子账号选择与固定"流程，并要求自动化**显式选定**目标子账号（当前只校验、不选择）；同时把"账号不可用时经审计改绑"从临时能力补成产品流程（[技术方案 ACCOUNT_MISMATCH 行](../AI达人智能发现与采集系统-完整技术方案.md)）。
  5. 使用 `xingtu session-diagnostics` 建立 0/15/30/45/60 分钟到 30 天的分阶段基线。
  6. 在真实环境复验账号冲突状态和过期租约单步回收。
  7. 完成真实 5/10/20 位连续采集；满足前置契约后再决定是否执行 50/100。

## 状态历史


- 2026-10-21T16:57:51+08:00：进行中 → 进行中（实时核验开始）。用户要求查看当前执行单元的巨量星图登录状态；本轮绑定唯一开发单元 `unit-local-mac-02`，计划使用 `xingtu session-diagnostics` 冷启动真实 Chrome 执行只读进程内观测。不执行搜索、采集、登录或业务库写入；结果及脱敏证据待命令结束后回写。
- 2026-10-21T17:03:00+08:00：进行中 → 进行中（实时核验完成）。受限沙箱的首次尝试在访问平台前因 macOS Chrome 运行权限失败；同一只读命令重试 exit `0`，真实 Chrome 观测为 `VALID / PROTECTED_PAGE_AND_ACCOUNT_VERIFIED`，实测账号与绑定账号一致，受保护页可用，未见登录页或安全挑战，快照在首导航前恢复，浏览器正常关闭。未搜索、未采集、未重登、未写业务库。本卡长期验收项未闭合，状态保持进行中／未验收。证据：[实时只读核验](../evidence/SESSION-01-session-live-check-2026-10-21.md)。
- 2026-10-21T17:03:05+08:00：进行中 → 进行中（人工查看窗口启动）。用户追问有效单元并要求打开其 Chrome；已再次确认对象为 `unit-local-mac-02`，绑定 `ID: 1807978499337419`，专属 profile 启动前无 `Singleton*` 锁。以同一 `BrowserRuntime` 恢复私有快照后打开已登记受保护页，Chrome PID `61698` 持有专属 profile 锁，进入 1800 秒人工查看等待。未启动采集、未自动点击或搜索；窗口期间不可同时启动该单元采集，查看完成后需 `Command-Q` 完全退出。证据：[实时只读核验](../evidence/SESSION-01-session-live-check-2026-10-21.md)。

- 2026-09-29T11:05:00+08:00：建立 → 待办。原"会话不能跨重启恢复"结论被判定证据不足并撤回；用户需求"登录一次可存活 1 个月"与现有实现存在差距，独立建卡核验。
- 2026-09-29T11:55:00+08:00：待办 → 进行中。完成首次两段式真实验收（4 次运行）：确认**会话跨任务复用机制成立**（`READY` 单元以 `collect` 复用、无 promote、无登录要求），但发现**账号在同一 profile 内漂移**（run 3 `1865332309937515` → run 4 `1832740070238347`），成为任务失败直接原因；同时登记 P1 错误归因、P3 回收协议与 `/bin/ps` 缺陷。完整证据见[两段式验收证据](../evidence/SESSION-01-acceptance-2026-09-29.md)。因根因未定，状态为进行中，不勾选整卡。
- 2026-09-29T13:25:37+08:00：进行中 → 待验收。用户批准结构性方案后完成迁移 006、五态 SessionHealth、显式 ReleaseDisposition、账号冲突分流、冷启动强制复验、单步安全回收和 HMAC 诊断工具；AUTO-01 联动完成首次身份不可读后的 Session 复核、达人级重试/跳过与 scoped breaker。178 项离线/合成测试通过；真实单账号与长期/规模验收未执行。
- 2026-09-29T13:46:05+08:00：待验收 → 待验收。迁移 006 已应用并只读确认本地开发库版本 1—6 与新表；真实 Profile、Session 和平台任务未触碰，剩余真实验收不变。
- 2026-09-29T13:50:33+08:00：待验收 → 待验收。补齐 scoped breaker 紧急回滚开关并完成 178 项最终回归；真实验收缺口不变。
- 2026-09-29T14:56:37+08:00：待验收 → 待验收。独立测试轮（F04/F05 真实核心流程）新增第 5 次账号不可读复现与独立诊断证据（受保护页可见 + SSO Cookie 齐全 + `observed_account_id=null`），并登记新缺陷：`SESSION_INDETERMINATE` 不会打开人工登录窗口，只能人工 `invalidate_session` 才能继续。用户现场观察到 A/B 账号漂移。漂移根因、存活上界与跨重启复用成功案例仍未取得。
- 2026-10-05T11:05:00+08:00：待验收 → 待验收。新增账号漂移专项只读探针（7 项判定 + 2 项载体/人工窗口离线自检通过）；用户现场确认目标子账号 `ID: 1865332309937515` 在平台子账号列表中**可见且可选**，据此排除"父账号无权访问"分支，问题指向自动化缺少"选定目标子账号"步骤，并登记该概念在文档与代码中的零命中缺口；已备份并重建 `unit-local-mac-02` profile（不可变绑定未改动）。真实漂移判定与载体定位仍在执行，根因未定，验收项「H-A/H-B 账号漂移根因」保持未勾选。
- 2026-10-05T11:20:00+08:00：待验收 → 待验收。**账号漂移真实复现**：同一 profile 在人工登录并选定目标子账号后，间隔约 3 分钟重启 Chrome，生效账号由 `1865332309937515` 变为 `1832740070238347`（与 run 4 一致），判定 `IDENTITY_CHANGED_WHILE_UNREADABLE`（退出码 1）；同一进程内跨页面/同页反复读/第二标签页均为目标账号，排除页面差异与多标签页解释。**D1 成因得到解释**：漂移后受保护壳不渲染 → 定位器匹配数 0、受保护页不可见 → 只得 `SESSION_INDETERMINATE`，即 D1 是"错误账号"的误分类，与漂移同源。**载体收敛**到唯一变化的身份 Cookie `star_sessionid`；`possess_scene_star_id`/`session_tlb_tag` 逐字节未变，原推测被否定。**自我纠错**：首次自动判定误输出 `STABLE`（整轮不可读被静默忽略），已修正判定逻辑并新增两态，用 `--reanalyse` 离线复算同一报告得到上述结论。证据见[账号漂移专项检测证据](../evidence/account-drift-probe-2026-10-05.md)。H-A/H-B 仍未区分，验收项保持未勾选。
- 2026-10-05T12:05:00+08:00：待验收 → 待验收。完成**最小验证**（两轮现场，各 2 次冷启动 + 180 秒间隔），证据见[最小验证证据](../evidence/account-drift-probe-2026-10-05-minimal-verification.md)：① 客户端**未持久保存任何子账号信息**（`localStorage` 的 STAR 键为空数组，有内容的在 sessionStorage 且更像引导/队列数据）；② 重启后**确实落到默认子账号** `1832740070238347`，且冷启动时 SSO 登录在而 `star_sessionid` 缺失、**停在 SSO 入口页永不签发业务会话**；③ **自动选号尚未成功**——已定位并排除"账号信息弹层"，真正选号入口未找到，按规范不猜选择器；④ **选中不跨重启保持**（轮 0 选定后重启即回到另一账号）。漂移第二次复现且本次导航栏正常渲染、系统自身给出 `ACCOUNT_MISMATCH`，据此把 **D1 与 `WRONG_ACCOUNT` 统一为同一次漂移的两种表现**。**自我纠错（第 3 次）**：验证 B 首次自动判定误输出 `STABLE`（"稳定地错"），已新增 `PERSISTENT_ACCOUNT_MISMATCH` 判定与回归自检并离线复算两份报告。**阻塞**：定位选号入口需操作者提供人工切换路径，自动选号的可行性与保持性仍未验证，验收项保持未勾选。
- 2026-10-05T13:30:00+08:00：待验收 → 待验收。用"记录操作者真实点击"定位**选号入口**（证据[点击记录](../evidence/account-drift-probe-clicks-2026-10-05.json)）：弹层由 **hover** 打开、内含 `button.change-account-button`（"切换"）、点击后到独立选号页 `/ad/user-center/user/account/auth`，候选 **4 条 / 3 个不同 ID**，绑定目标 `1865332309937515` **在列表中**。自动选号按该 DOM 实现后仍未成功（脚本 hover 只枚举到 1—2 条、目标不可见；人工真实点击可见 4 条）→ 列表需真实交互才完整渲染。**操作者关键观察（未由脚本独立复核）**：人工点击目标 `1865332309937515` 后弹窗一关**平台就自动回到 `1832740070238347`**，若成立则问题不止"重启后漂移"，而是**同一会话内即回退**。新增待判定项：切到第三个账号 `1831973402720484` 能否保持——据此决定走"审计改绑/更换登录身份"还是"平台侧会话绑定无法自动解决"。验收项保持未勾选。
- 2026-10-05T14:09:04+08:00：待验收 → 进行中。用户批准“先修复诊断链路、再做真实 A/B、只在证明 Playwright 环境可稳定选号后才启用正式自动选号”的实施方案。本轮开始修复页面跳转丢点击的探针缺陷，增加脱敏的选号请求—响应—会话关联证据及自动回归；正式 Adapter 选号保持关闭，等待真实 A/B 门槛。
- 2026-10-05T14:39:09+08:00：进行中 → 进行中。诊断链实现完成：修正 `add_init_script` 未执行及跳转丢点击，增加 Python binding、脱敏网络/会话检查点、locator 点击、安全 A/B profile/参数开关与手册；探针 12 项自检及 2 项合成 Chrome 契约用例通过。真实 A 组（同项目 profile、系统 Chrome 直启、无 Playwright）已打开等待人工选号结果；根因和正式自动选号门槛仍未闭合。
- 2026-10-05T15:04:01+08:00：进行中 → 进行中。确认 A 组当前不是“仅界面显示未登录”：项目 profile 的 Cookie 数据库中没有父账号 SSO 认证 Cookie，也没有星图业务 `star_sessionid`，故属于真实未登录。修复维护与采集入口顺序：均先进入受保护业务页，有效会话展示登录后页面，只有真实失效才由平台跳转登录；首次不可判定时 Adapter 仅做一次有界 SSO 握手后回业务页复核，账号/受保护页成功门槛不变。`make check`（105 单测）及完整 Browser Contract（20 项）通过；新增 BrowserHost 集成断言因本机专用 PostgreSQL 未运行而未执行到业务断言。当前需操作者先完成一次人工登录，再继续子账号 A/B，整卡保持进行中／未验收。
- 2026-10-05T15:09:25+08:00：进行中 → 进行中。操作者已在 A 组项目 profile（系统 Chrome 直启、无 Playwright）完成人工登录并确认显示星图首页；登录后的只读 Cookie 名称检查确认 OceanEngine SSO 认证 Cookie 与星图 `star_sessionid` 均已签发，与登录前二者均缺失形成对照，故登录页／业务页显示问题已闭合。下一步在同一 A 组窗口先测第三账号 `1831973402720484`，再测目标账号 `1865332309937515`；子账号回退根因与正式自动选号门槛仍未闭合，整卡保持进行中／未验收。
- 2026-10-05T15:13:17+08:00：进行中 → 进行中。A 组第三账号对照通过：系统 Chrome 直启项目 profile（无 Playwright）选择 `1831973402720484` 后，选择后、刷新后和达人广场均稳定保持该账号。由此排除“项目独立 profile 会使所有非默认账号回退到 `1832740070238347`”，并证明该 profile 的自然 Chrome 切换链路至少对第三账号正常。下一步在同一窗口测试目标 `1865332309937515`，以判断目标账号特异性；Playwright B 组及冷启动保持性仍未验收。
- 2026-10-05T15:17:47+08:00：进行中 → 进行中。A 组目标账号对照同样通过：不经过 Playwright 的同一项目 profile 从第三账号切到 `1865332309937515` 后，点击后立即即为目标且从未短暂回退，等待 10 秒、刷新、达人广场均保持目标。由此排除“目标账号本身不可用／权限异常”和“项目 profile 自身导致回退”；根因收敛到 Playwright 控制环境或旧探针交互/观测缺陷。下一步完全退出自然 Chrome并释放 profile 锁后，以同一 profile 进入 Playwright B 组；正式自动选号仍未启用。
- 2026-10-05T15:31:33+08:00：进行中 → 进行中。B1（当前 Playwright 环境）首次只读冷启动已完成：探针先修正为业务页第一跳后运行，7/7 检查点均被重定向到 `/?redirect_uri=...`、账号不可读、无受保护页，且 Context 中没有 SSO Cookie/`star_sessionid`；运行后磁盘 Cookie 数据库中的认证行也全部消失。B1 启动前这些认证 Cookie 明确存在，项目代码没有清 Cookie，因此故障定位到 Playwright 启动读取 profile 阶段，早于选号。最强机制假设为 Playwright macOS 默认 `--use-mock-keychain` 与自然 Chrome 系统 Keychain 不兼容，但尚待 B2 实证。已增加仅限 macOS 本地诊断的 `--use-system-keychain` 开关，只忽略该单一默认参数、保留其他参数且不做 stealth；单元断言通过。因 B1 已清除认证 Cookie，已重新打开自然 Chrome等待人工登录／选定目标后再跑 B2。
- 2026-10-05T16:05:03+08:00：进行中 → 进行中。完成 B2/B3/C 并形成分层根因：① B2 只忽略 Playwright 默认 `--use-mock-keychain` 后父账号 SSO Cookie 可跨启动保留，证实 mock keychain 与自然 Chrome 系统 Keychain 不兼容是“启动后显示未登录”的直接根因；已正式增加显式 `macos_system_keychain` 配置，当前本地单元启用，只忽略该单一参数且环境哈希纳入策略。② 新 Playwright 进程仍丢失 session 型 `star_sessionid` 并按默认账号 `1832740070238347` 重建；B3 真实目标点击已记录可信事件、选号 POST HTTP 200和导航，但所有选后检查点及 `star_sessionid` HMAC均不变。③ C 组移除两个项目网络参数后，4 次目标点击／4 次选号 POST／54 个检查点仍完全相同，故项目参数排除。正式自动选号没有满足稳定门槛，保持关闭；不做 stealth/Cookie 注入/无限重试。最终 `make check`（107 单测）和 21 项 Browser Contract 通过；依赖停机 PostgreSQL 的 BrowserHost 定向集成仍未执行到业务断言。整卡因平台侧可行方案和长期验收未闭合，保持进行中／未验收。
- 2026-10-06T15:19:21+08:00：进行中 → 进行中。用户明确授权将本轮改动发布到 `main`。发布前确认本地与 `origin/main` 无分叉，敏感信息复核未发现明文 Cookie/Token/请求正文，`.runtime/` 持续被忽略；`make check` 通过（Ruff/format/mypy/107 单测），完整 Browser Contract 在允许 Chromium Mach port 的环境中 21 passed，探针 10+2 项自检通过。受限沙箱中的首次 Contract 运行因 macOS `bootstrap_check_in ... Permission denied (1100)` 未启动 Chromium，属运行环境拒绝而非断言失败。本次发布不改变真实平台验收结论，整卡仍为进行中／未验收。
- 2026-10-06T16:35:00+08:00：进行中 → 进行中。用户决策**舍弃旧登录身份**并改用只含单一子账号的新巨量星图账号：备份 `.runtime/profiles/unit-local-mac-02.bak-20261006T161500`（200 MiB）后清空重建 profile，用项目真实 Chrome 完成人工登录，冷启动读到新账号 `ID: 1807978499337419`（受保护页可见）。新增**显式审计改绑**能力（迁移 007 `unit_account_rebindings`、`Repository.rebind_unit_account`、CLI `xingtu rebind-account`；宿主占用时拒绝、`register_unit` 与 `ACCOUNT_MISMATCH` 仍禁止自动改绑），改绑后单元为 `SESSION_UNVERIFIED`/`ACCOUNT_BINDING_CHANGED`。**规避有效性验证通过**：改绑后两次独立冷启动（间隔 10 秒）判定 `STABLE`，实测账号恒为新身份、跨轮身份 Cookie 零变化，与改绑前"重启即回退 `1832740070238347`"对照成立。`ruff`/`format`/`mypy` 通过、单元 108 passed、集成 53 passed / 1 failed（该失败在 HEAD `bc74e27` 上同样失败，属本分支"翻页+全字段"进行中改动的既有失败，与本轮无关，已登记遗留）。证据见[改绑与漂移规避证据](../evidence/SESSION-01-account-rebinding-2026-10-06.md)。漂移根因与存活上界仍未闭合，整卡保持进行中／未验收。
- 2026-10-06T18:01:11+08:00：进行中 → 进行中。用户要求"先修复账号不稳定问题"，并按**混合持久化（持久目录 + 显式 storage-state 注入）**方案实施。① 定位业务会话载体 `.xingtu.cn/star_sessionid` 为**会话级 Cookie**（`is_persistent=0`、`has_expires=0`），落盘不确定正是"有时登录、有时未登录"的直接机制；② 实现会话有效时导出 `context.storage_state()`（`.runtime/storage-state/<unit>.json`，`0600`）并在下次启动**首次导航前**注入全部 Cookie 与 localStorage，仅在页面出现契约保护页标志时才覆盖快照；③ **对照实验决定性**：同一 profile，注入快照 → 账号可读、后台可进；移走快照 → 被打回 `/?redirect_uri=...`。④ 同时修复冷启动引导缺陷：worker 路径下 `inspect_session` 会在已被重定向的页面上耗尽 `session_boot_timeout_seconds=180s`，改为有界重试（≤4 次，轮流使用新登记的 `session.business_urls`）+ 每次 15s 短探测。⑤ 效果：宠物 22 位采集**首次端到端跑通**（40 候选 / 22 有效 / 67 快照 / 两页翻页），全程未再因"被踢回登录页"空转。`ruff`/`format`/`mypy` 通过、单元 114 项通过、契约 22 项通过。存活上界仍未测，快照注入属凭证复用、平台若收紧需重评，整卡保持进行中／未验收。
- 2026-10-12T15:37:00+08:00：进行中 → 进行中（不变）。用户要求检查当前执行单元的星图登录状态是否失效，显式授权后执行**只读实时核验** `xingtu session-diagnostics`（`2026-10-12T15:36:53 → 15:37:01+08:00`，exit 0）：结果 `SessionHealthStatus.VALID`，`protected_page_verified=true`、`login_page_verified=false`、`challenge_verified=false`，`observed_account_id == expected_account_id == ID: 1807978499337419`（**漂移规避继续成立**），Chrome 154.0.8037.98、`normal_close_confirmed=true`。据此新增**存活时长下界**数据点：上次进程内确证（01:12:41+08）之后，**14.4 小时**且跨越新的冷启动仍被平台接受。**存活上界与失效诱因（H1/H2/H3、H-A/H-B）仍未闭合**，本卡保持进行中／未验收。证据见[会话实时只读核验证据](../evidence/UNIT-01-session-live-check-2026-10-12.md)。
- 2026-10-13T15:39:54+08:00：进行中 → 进行中（登录维护开始）。用户报告账号态失效并要求打开当前执行单元 Chrome 以人工重新登录。只读核对专属 profile 的 `SingletonLock` 显示既有 Chrome 实例（PID 10613，锁文件 08:43+08:00）仍在持有 profile；为保持「人工维护与采集互斥、同一 profile 不并发打开」约束，不启动第二个浏览器，改向既有实例发送巨量星图受保护业务页打开请求。登录结果及后续会话核验待用户完成交互后记录。
- 2026-10-13T15:42:09+08:00：进行中 → 进行中（登录窗口已就绪）。已向专属 profile 的现有 Chrome 实例发送受保护业务页并置前台；三个 Chromium Singleton 文件均更新为 `15:41:15+08:00`，表明该实例已接收本次打开请求。未触碰凭据、未执行采集；人工登录／验证码及随后账号精确匹配、受保护页和挑战状态核验仍待完成。
- 2026-10-13T15:46:39+08:00：进行中 → 进行中（等待安全交接）。用户已完成手工登录并要求长期复用会话。运行态证据：profile 的 Cookies／Local State 已更新，但显式私有 storage-state 快照尚不存在；现有 Chrome 仍持有 profile。既有实现会在受控 Runtime 的“受保护页 + 精确账号”核验通过后导出快照，并在后续采集启动前注入。为遵守同一 profile 不并发打开的约束，等待用户关闭刚才的执行单元 Chrome 窗口后再执行冷启动验证和快照导出；不读取或复制明文 Cookie。
- 2026-10-13T15:51:06+08:00：进行中 → 进行中（等待进程完全退出）。用户关闭了窗口，但两次冷启动均不能接管 profile：沙箱尝试被 macOS 运行权限拒绝；授权重试中 Chrome 返回“正在现有的浏览器会话中打开”，`SingletonLock` 仍指向 PID 18738，快照保持不存在。未并发访问、复制或导出 Cookie；待用户**完全退出执行单元 Chrome 进程**后，继续执行既有受控核验及 `storage-state` 导出。
- 2026-10-13T16:08:35+08:00：进行中 → 进行中（准确登录入口已打开）。用户恢复磁盘空间后，Data 卷可用约 17 GiB，profile 无旧锁；已重新打开并置前台登记 SSO 入口，PID 20167 正持有专属 profile。等待用户在该窗口完成登录，之后执行受控交接、绑定账号精确核验与 storage-state 导出。
- 2026-10-13T16:16:36+08:00：进行中 → 进行中（登录后身份不可读）。用户确认登录后完成受控冷启动核验；报告 `unit-local-mac-02-20261013T081546Z.json` 为 `INDETERMINATE / PROTECTED_PAGE_ACCOUNT_UNREADABLE`，虽有 46 个 Cookie／5 个会话 Cookie，仍无法验证绑定账号。快照未导出，避免把错误账号或不完整会话持久化；下一步是定位当前业务页的账号身份可读性，再重新核验与保存。
- 2026-10-13T16:20:44+08:00：进行中 → 阻塞。用户确认唯一子账号为绑定 ID 且手工页面已登录；三次禁用快照的受控 DOM 探针分别覆盖业务页、账户管理页和所有 iframe，均未见绑定 ID 或任何 `ID:<数字>` 节点，旧选择器零匹配。无法在不降低“精确账号验证”契约的前提下保存长期会话；等待用户授权带审计的人工确认兜底，或提供可验证身份的官方页面入口／证据。
- 2026-10-13T16:49:05+08:00：阻塞 → 进行中。用户明确授权受审计的唯一子账号人工确认；配置限制为本机开发单元、精确绑定 ID、最长 31 天且可撤销。真实 Chrome 三次冷启动后，最终脱敏报告确认 `VALID / MANUALLY_ATTESTED_UNIQUE_ACCOUNT`、私有 snapshot 在首个导航前已恢复、正常关闭确认；会话长期存活上界及其他历史验收项仍未完成。
- 2026-10-13T16:53:20+08:00：进行中 → 进行中。`make check` exit 0（后端单元 189 passed、前端 3 passed、构建通过）；浏览器契约仍因 Playwright bundled Chromium 未安装而未运行到断言，长期会话与历史实机验收项仍待完成。
- 2026-10-14T15:56:00+08:00：进行中 → 进行中。用户再次要求核验登录状态并在失效时唤起 Chrome 登录，同时要求记录“登录态快速失效”的原因。只读核验**有效**：`VALID`、账号精确匹配、受保护页 `true`、快照在首个导航前恢复、Chrome 155.0.8059.40 正常关闭（本轮为快照路径首次在账号可读条件下的 `VALID`）；存活下界更新为**约 29 小时 / 3 次冷启动**。根因复盘结论：`star_sessionid` 为会话级 Cookie，登录态跨重启完全依赖私有快照，而 **2026-10-13 16:48 之前从未产出过快照**（身份门槛不满足），故那时“登录很快失效”是会话无法落盘所致；`--use-mock-keychain` 与子账号漂移为次级放大器。登记 5 项待优化缺口（快照写入触发过窄、门槛耦合、恢复失败不可观测、无巡检、H1 未排除）。已按用户要求以专属 profile 打开受保护业务页供人工查看/登录，无采集、无业务写入。证据：[登录状态核验与快速失效根因记录](../evidence/SESSION-01-login-lifetime-root-cause-2026-10-14.md)。存活上界、漂移根因与长期验收项保持未勾选。
