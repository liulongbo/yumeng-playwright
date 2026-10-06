# AUTO-01：自动化采集优化与分阶段实证

状态：进行中  
更新时间：2026-10-05T11:20:00+08:00（Asia/Shanghai）
是否验收：否

## 目标与范围

执行用户批准的《巨量星图自动化采集技术调研与实施建议》：每天最多 200 位、当前账号可访问的完整主页默认口径、会话复用与登录后续跑。排除官方 API、付费数据服务、全量签名逆向和自动人机挑战求解。用户本轮补充“自动化短信先不做”，改为 Chrome 短信／账号密码入口登录；不开发设备接入与收码。

## 关联与依赖

关联 BASE-01、UNIT-01、F04、F05、F06、F10；后台由 APP-01、INTAKE-01、CONSOLE-01、OPS-01 承接。验收覆盖 T05/T06/T13—T17/T31—T40。真实账号、生产环境及持续观察为独立实证条件；短信设备已移出本轮。

## 验收清单

- [x] 调研报告落盘，修订旧自动化边界并同步索引。
- [x] 首页能力限制不再报告平台耗尽，停止原因与检查点可追溯。
- [x] 需求覆盖独立于已注册模块，历史任务和快照语义兼容。
- [x] 区分挑战、登录、权限、额度、网络与契约异常；必要运行指标可查。
- [ ] 核对真实账号权益、完整字段清单和分页，完成 5 位及 20 位实测。
- [x] Chrome 正常登录后校验、错误分类与原任务恢复（原自动短信设备验收由用户明确移出本轮）。**真实 dispatch 中同一 root/checkpoint 经登录原子提升、挑战回切、再登录后 `valid_count 0→1→2`，Temporal workflow 正常完成。**
- [ ] 三类代表性网页接口完成等价性实验，逐项登记采用或保留浏览器。
- [ ] 后台维护与采集互斥，续跑幂等；完成容量与连续 7 天观察。**互斥、同上下文/同 Page 交接、真实原任务续跑与重复 wake 幂等已通过；容量与 7 天观察仍未验证。**
- [x] 单达人 `IDENTITY_UNREADABLE` 最多三次独立详情页尝试，失败记录后继续后续候选；合成 20/200 位连续采集通过。
- [x] Contract 改为能力 scope 健康状态：不同主体 + 新浏览器租约双门槛；单达人失败不再禁用整版本，无关 scope 不受阻断。

## 实现记录

2026-09-28：开始执行。现有源码及卡片已复核；先实施阶段一，不能将阶段一完成标为整项完成。当前无 Git，不编造提交号。代码图数据库及 MCP 不可用，使用定向源码检查。

2026-09-28：用户已明确批准原方案的实证修订，同意下一批按“每执行单元一个有界浏览器宿主、同一上下文完成登录维护到采集交接”实现，并允许在不是最佳方案时修改原技术实现。完整新窗口交接见[有界浏览器宿主实施交接](../handoffs/AUTO-01-bounded-browser-host-handoff-2026-09-28.md)。

2026-09-28：新窗口继续实施已启动。已依次复核开发规范、技术方案相关章节、本卡、有界宿主交接、DEC-011、调研与两份阶段证据；用户本轮再次明确授权直接实现同一 Chrome/BrowserContext 的维护到采集交接。当前仓库仍无 `.code-review-graph/graph.db` 且无可用 MCP，按规范回退到 `rg` 和定向源码检查。本轮将先完成不依赖人工登录的仓储、宿主、工作流、测试和文档；真实等待任务通过前保持“进行中／未验收”。

2026-09-28：**有界浏览器宿主批次代码已实现**（卡片此前的“本轮将先完成”已实际落地）：新增 `backend/src/xingtu/browser_host.py`（每单元一个有界宿主，持有租约、profile 锁与 BrowserContext；维护与采集共用同一上下文，绝不跨进程传递；关闭未确认保持 `browser_stopped=false` 并隔离）；迁移 `migrations/005_bounded_browser_host.sql`（新增 `expected_account_id`/`verified_account_id`/`current_root_task_id`/`maintenance_deadline`/`idle_deadline`）；`Repository` 新增带行锁与 fencing 的 `promote_maintenance_to_collect`（单事务校验 owner/generation/state/mode/租约/session_version/maintenance_deadline，成功后改 `mode=collect`、`session_version+1`、清 `failure_reason`、写审计）、反向 `transition_collect_to_maintenance`、`verify_maintenance`、幂等 `queue_login_resumes`、`request_login_maintenance`；`worker.py` 以宿主租约驱动“维护→采集”续跑；`cli.py` 的 `login` 不再自行开关 Chrome，改为登记幂等维护意图、由 Worker 打开有界 Chrome，移除“关闭后重启才算成功”的旧交接路径。

2026-09-28：**真实平台交接与采集已实测通过**（详见[有界宿主真实运行证据](../evidence/AUTO-01-bounded-host-real-run-2026-09-28.md)、[运行日志](../evidence/AUTO-01-bounded-host-real-run-2026-09-28.log)）。迁移 005 已应用到本地开发库（此前为 1—4）。单元 `unit-local-mac-02` 由 `NEEDS_LOGIN/session_version=5` 经同一 Chrome 上下文人工登录后原子提升为 `mode=collect/session_version=6`，真实账号 `ID: 1865332309937515` 与受保护业务页均在同一上下文核验，审计为 `browser-host:<attempt>|promote_maintenance_to_collect:unit-local-mac-02`；随后同一上下文完成关键词 `美妆` 搜索与 2 位达人 `basic` 采集落库（`valid=2`、发现/扫描 20/20、检查点 `revision=52`），终态 `PARTIAL_COMPLETED`、原因 `PROFILE_SCOPE_INCOMPLETE`；运行结束 Chrome 确认关闭，单元回到 `NEEDS_LOGIN/browser_stopped=true`，未虚报可复用。

2026-09-28：交付前安全收紧：上述初始实现记录中的 `verify_maintenance` 后续已删除，因为它可以绕开同上下文的完整 fencing 校验单独递增 `session_version`。当前仅 `promote_maintenance_to_collect` 能递增会话版本。同时将重复维护确认改为幂等成功：已有 maintenance 宿主时复用原 owner/generation/session，不创建第二个浏览器。

2026-09-28T18:43+08:00：真实 dispatch 续跑暴露两个组合缺陷。首次登录原子提升成功（同 owner/generation，`session_version 0→1`）并采到 1 位候选；随后触发 `PLATFORM_SECURITY_CHALLENGE`。实现在提升时为**已正在运行的 Activity**又登记了 wake，而 Workflow 对 `WAITING_FOR_LOGIN` 仍会 30 秒轮询；维护超时后因此可再开一个 Chrome。另外，交接后 Adapter 新建 Page，对用户表现为“又打开一个未登录页面”。已修复为：采集一次性接管刚通过账号/受保护页校验的**原 Page**；挑战回切时先从旧 Adapter 脱离该 Page，不再被 `finally` 关闭；同 Activity 内的 promote 不再自我登记 wake；`WAITING_FOR_LOGIN` 改为只等待新的显式 `xingtu login` wake，不再定时重启 Chrome。中断时关闭确认失败被保守置为 `QUARANTINED`；确认项目 Chrome 进程与 profile 锁均已消失后，通过内置 `recover-unit` 审计恢复，未直接改库绕过隔离。原 root `8120b16c-9289-4822-913a-542be3db6bc3` 与 `valid_count=1` 当时得以保留；后续已续跑完成，见下方验证记录。

2026-09-29：用户批准 SESSION-01/AUTO-01 结构性修复。迁移 006 新增 capability scope 健康状态；Engine 将单达人 `IDENTITY_UNREADABLE` 改为最多三次新 Page 尝试，仍失败后保留证据并继续补位。三个不同主体连续失败只进入 `SUSPECTED`，新浏览器租约的第四个不同主体再次复现才禁用 `profile_identity`；旧全局开关保留兼容。目标 5 的历史失败 RCA 已确认首发是第六个候选身份 DOM 不可读，不是固定达人数量上限，Contract disabled 是后续放大结果。实现证据见 [SESSION-01 / AUTO-01 结构性修复实施证据](../evidence/SESSION-01-implementation-2026-09-29.md)。

2026-10-05：账号漂移专项测量移交 SESSION-01，并由新增只读探针 [account_drift_probe.py](../../scripts/account_drift_probe.py) 承接。用户现场确认目标子账号 `ID: 1865332309937515` 在平台子账号列表中**可见且可选**，据此排除"父账号无权访问目标子账号"分支，问题指向**自动化缺少"选定目标子账号"步骤**；该缺口同时是文档缺口（`子账号` 在 `docs/`、`backend/` 全仓零命中）。

**同日真实复现**（[证据](../evidence/account-drift-probe-2026-10-05.md)）：人工登录并选定目标子账号后，间隔约 3 分钟重启 Chrome，生效账号由 `1865332309937515` 变为 `1832740070238347`（与 run 4 一致），判定 `IDENTITY_CHANGED_WHILE_UNREADABLE`；同一进程内各页面/标签页均为目标账号。漂移后受保护壳不渲染 → 账号定位器匹配数 0 → 系统只得 `SESSION_INDETERMINATE`，**缺陷 D1 与账号漂移同源**（D1 是"错误账号"的误分类）。载体收敛到唯一变化的身份 Cookie `star_sessionid`。本卡依赖账号稳定的验收项（真实 5/20 位、完整字段、7 天观察）保持未勾选。

## 验证证据

2026-09-28：ruff、format、mypy 通过。**最终全套 167 项测试通过**（`pytest backend/tests tests/e2e -q`，退出码 0）；此前 166/153/147 项为分阶段历史基线。新增宿主所有权、同上下文/同 Page 提升、关闭隔离、租约、重复维护确认、无显式 wake 时不重试以及重复 Temporal wake/history replay 测试。失败与修复历史已追加到[有界宿主真实运行证据](../evidence/AUTO-01-bounded-host-real-run-2026-09-28.md)。历史 2 位基础验证不能替代完整主页新验收。

2026-09-28：**真实平台运行证据**（[有界宿主真实运行](../evidence/AUTO-01-bounded-host-real-run-2026-09-28.md)／[日志](../evidence/AUTO-01-bounded-host-real-run-2026-09-28.log)）：同一上下文 `maintenance → collect` 原子交接、账号与受保护页核验、`session_version 5→6`、审计记录、2 位达人 `basic` 真实落库（字段级来源完整、空值记 `NO_DATA`）、关闭后 `NEEDS_LOGIN/browser_stopped=true` 均通过。该早期 `make smoke-local` 运行当时尚未覆盖 dispatch 原任务续跑；后续已在本卡 18:43 记录和证据第 10 节补齐。当前未通过项为第 3 页及终点、其余主页模块、5/20/200 位与 7 天观察。

2026-09-28T17:56+08:00：只读收尾核对本地开发库：`schema_migrations=1,2,3,4,5`；`unit-local-mac-02|NEEDS_LOGIN|browser_stopped=true|session_version=6|owner=NULL|mode=NULL`。证明复测后没有遗留宿主、租约所有者或错误 READY 状态。

2026-09-29（本轮结构性修复）：静态检查通过；105 单元、18 浏览器契约、51 PostgreSQL 集成、4 Temporal E2E，共 178 项通过。包含合成 20/200 位连续任务、首次身份不可读后的 Session 复核、单达人失败后补位和 scoped breaker 回滚开关；未启动真实平台任务，真实 5/10/20、50/100 与 7 天观察仍未验收。

2026-09-28T18:06+08:00：最终真实 dispatch 验证当时进入人工登录等待。为避免触碰本地开发库的历史未发送 dispatch，在同一隔离测试 PostgreSQL 实例中建立专用 schema `auto01_dispatch_20260928`，应用迁移 1—5 并注册同一真实单元绑定。新 root `8120b16c-9289-4822-913a-542be3db6bc3`（target_count=2）由原 workflow 进入 `WAITING_FOR_LOGIN`，检查点 revision=1/valid_count=0；连续两次 `xingtu login` 均幂等返回 1 个原等待任务，owner/generation/session 未变，没有第二个宿主。该等待后续已完成；本段保留为时序证据。

2026-09-28T18:43+08:00：上述真实 root 已实证“首次登录提升 → 原任务续跑 → `valid_count 0→1` → 挑战回切”，并暴露重复 Chrome/Page 缺陷。修复后原 workflow 继续到 `valid_count=2`，终态 `PARTIAL_COMPLETED/PROFILE_SCOPE_INCOMPLETE`，宿主确认关闭并回 `NEEDS_LOGIN/browser_stopped=true/session_version=2`。直接修改 Workflow 等待命令首次暴露 `TMPRL1100` nondeterminism；改为 `workflow.patched("waiting-for-login-explicit-wake-v1")` 后兼容旧 Timer history，原 workflow 已以 `WORKFLOW_EXECUTION_STATUS_COMPLETED`、结果 `PARTIAL_COMPLETED`、history length 48 正常结束。本卡仍“进行中／未验收”，因完整主页、容量与 7 天观察未完成。

同一上下文真实能力与主页数据面见[当前账号能力与字段盘点](../evidence/AUTO-01-current-account-inventory-2026-09-28.md)。已确认搜索前两页和多个主页数据面，挑战定位与历史权益错误码已登记；第 3 页及以后、终点与完整字段仍未通过。

真实列表主滚动容器已到达底部且没有第 2 页请求／下一页控件，故不猜测 UI 翻页动作。最终实验证明同一页面内存复用原生请求体和必要请求头可取得真实第 2 页；注册表仅开放至已验证页 2，超过边界明确停止。

## 真实会话复核进展

同一研究窗口内由用户完成正常登录后，页面进入 `/ad/creator/index`，随后正常打开 `/ad/creator/market`；达人广场搜索接口及业务依赖请求均返回 HTTP 200，搜索输入框就绪。这证明账号当前可进入业务后台，但不证明跨浏览器重启可复用。

关闭再启动后，直达达人广场、公开首页“客户”入口及 SSO 引导均不能恢复后台会话；重启复用未通过。CLI 已增加关闭后重启复核，不能再以维护窗口内成功误置 READY。失败研究的浏览器关闭也曾挂起，已新增 20 秒关闭上限：未收到关闭确认时保持 `browser_stopped=false`，由租约释放逻辑将单元隔离，不能虚报可复用。现有进程模型无法完成“人工登录后关闭窗口再由 Worker 续跑”，下一阶段需改为同一浏览器进程内从维护交接到采集。

本地 `unit-local-mac-02` 原先遗留为 `READY`；已通过只允许“无人持有且浏览器已停止”时执行的仓储操作纠正为 `NEEDS_LOGIN`，原因为 `SESSION_NOT_PERSISTED_AFTER_RESTART`。审计记录 actor 为 `AUTO-01`，session_version 保留为 5，未伪造新的登录成功版本。

**2026-09-28 交接已解决**：有界宿主实现后，用户在宿主打开的 Chrome 内完成正常登录，同一上下文核验账号与受保护业务页后原子提升为 `collect`（`session_version 5→6`），并使用**同一上下文**完成真实搜索与 `basic` 采集。运行结束时 Chrome 确认关闭（profile `SingletonLock` 消失），单元回到 `NEEDS_LOGIN`。跨进程“关闭再重开”路径不再是交付路径，且没有被绕过。

## 交接信息

用户已明确取消本轮短信设备接入。分页仅验证前两页；全字段、其余接口等价性及持续观察尚未完成。

**下一批待做（按优先级）**：

1. **会话来源复核**：在一次显式重启后带时间戳重复流程，区分“用户新登录”与“profile 既有会话本次被接受”，不改写旧审计。
2. 第 3 页及真实终点研究（页面外请求复用已证明可行，契约仍限页 2）。
3. 其余主页模块逐项登记（报价／传播／种草／履约／转化／画像／创作能力），再完成 5 位完整主页与 20 位连续任务。
4. 之后才是单日 200 位与连续 7 天容量观察。

## 当前实施方案（用户已确认方案变更；**已实现并实测**）

> 2026-09-28 状态：下述 1—5 项的单任务端到端路径已在真实 dispatch 中通过；AUTO-01 整体仍因完整字段、分页终点、5/20/200 位和 7 天观察未完成而未验收。

原批准方案写明“暂不重构跨任务常驻浏览器服务”，但真实证据已证明关闭 Chrome 会丢失受保护业务会话。推荐用**每执行单元一个有界浏览器宿主**替代当前“登录 CLI 关闭 → Worker 重启 Chrome”的交接方式：

1. 浏览器宿主持有 Chrome 进程、profile 锁和单元租约；本机私有控制端点只监听回环地址，不记录 CDP 地址、Cookie、令牌或请求头值。
2. 单元失效时宿主打开登录维护页并保持当前上下文；用户通过 Chrome 完成短信／账号密码登录，宿主在同一上下文验证账号、受保护页面和线路。
3. Repository 带 fencing 地原子切换 `maintenance → collect`；已在运行的 Activity 提升后就地续跑，不为自身留额外 wake。只有宿主已释放且用户新发起 `xingtu login` 时，才登记耐久 wake 意图唤醒原 workflow；浏览器对象不跨进程传递。
4. 采集 Adapter 复用该上下文；挑战发生时切回维护模式并暂停业务访问。空闲或维护超时后确认关闭，状态回到 `NEEDS_LOGIN`；关闭未确认则 `QUARANTINED`。
5. 先用一个等待任务完成“失效 → 人工登录 → 原任务续跑”的端到端验收，再继续 5 位完整主页、第 3 页及终点、20 位连续任务。

此变更不引入自动收码、自动挑战、代理轮换或无边界多账号常驻；它只解决本轮实测暴露的浏览器生命周期所有权问题。

## 2026-09-29 会话结论更正与单元状态修正

**本卡此前采纳的前提已被判定证据不足。** 原记录（含[调研报告](../research/巨量星图自动化采集技术调研与实施建议.md)与[技术方案§1.4](../AI达人智能发现与采集系统-完整技术方案.md)）写"实测证明星图业务会话不能跨 Chrome 重启恢复"，并据此把"浏览器关闭即回待登录"固化进设计。该结论现予**撤回**，理由：

1. 其证据来源本文档所引的[有界宿主真实运行](../evidence/AUTO-01-bounded-host-real-run-2026-09-28.md) 第 3.1 节**自述无法区分**"用户新登录"与"既有会话被接受"；
2. 当时的会话探针**只验证受保护元素可见、从未比对账号 ID**，而 `check_session` 与 `wait_for_manual_clearance` 都要求账号精确等于 `expected_account_id`，故"会话失效"可能是测量假象；
3. 用户反馈其日常 Chrome 首次登录后可 **7-8 天**免登录进入后台，说明平台侧持久会话可行；
4. 但项目独立 profile 实测约 **45 分钟**即失效，方向相反。**两种观测并存，真实存活时长未定。**

**处理方式**：不删除、不改写 09-28 的审计与既有记录；新增独立核验卡 [SESSION-01](SESSION-01.md) 承接"会话真实存活时长与失效条件"，并把结论改为"**未经证实，不得据以设计**"。本卡不因此调整验收项。

**历史最小纠正**见 [DEC-012](../decisions/DEC-012-session-persistence.md)。其布尔 `session_verified` 设计已经被 [DEC-013](../decisions/DEC-013-structured-session-and-scoped-contract-health.md) 取代：当前必须在本 Chrome 进程内得到结构化 SessionHealth，才能选择明确 ReleaseDisposition。

**2026-09-29 当前验证**：`ruff`／`format-check`／`mypy` 通过；共 **178 passed**（105 单测 / 18 Browser Contract / 51 集成 / 4 E2E）。同日晚些的真实核心流程测试**已打开真实 Profile**：单进程内连续采集 7 位达人成功（8 个 `basic` 快照）、两次安全挑战自动恢复正确，但随后被 `LEASE_LOST` 与账号不可读中断，真实 5/10/20 位、50/100 与长周期 Session 观测仍未完成，故不据此宣称真实平台已验收。

**历史实测缺陷（2026-09-29 已修复）**：

1. `recover-unit` 依赖 `/bin/ps`，在受限沙箱返回 `PROCESS_LIST_UNAVAILABLE`；建议改用不依赖进程枚举的等价隔离判定（profile `flock` + `Singleton*` 文件），证据强度不低于 `/bin/ps`。
2. **回收协议缺少单一入口**：`recover-unit` 只接受 `QUARANTINED`，而 `LEASED`（租约到期）→ `QUARANTINED` 的迁移只发生于 `Repository.acquire()` 内部，没有对外命令。worker 被中断后的恢复因此是两步，单独执行 `recover-unit` 会报 `UNIT_NOT_QUARANTINED`。建议把两步合并为幂等单命令。

当前 `recover-unit` 可直接回收过期 `LEASED` 或 `QUARANTINED`，以 Profile `flock` 和 Chromium `SingletonLock` PID 判定占用，不再依赖 `/bin/ps`；回收后进入 `SESSION_UNVERIFIED`。旧两步真实回收记录仍作为历史审计保留，本轮没有操作真实开发单元。

### 2026-09-29 独立测试轮：真实连续采集的中途中断缺陷

F04/F05 真实核心流程测试（[证据](../evidence/F04-F05-real-core-flow-2026-09-29.md)）在同一有界宿主内连续采集时观测到两个未修复缺陷：

1. **`LEASE_LOST` 出现在采集中途**（运行 C 14:45:13，有效 7 位、采集第 8 位；运行 D 14:12:39 同样出现）。`Repository.heartbeat` 以 `lease_until=now+120s` 续期、worker 每 15s 心跳，正常情况下不应丢失；本轮**未取得该时刻的心跳间隔与页面耗时证据，根因未定位**。
2. **中断后的续跑必然失败**：`LEASE_LOST` 触发 Temporal 重试 → 新 Chrome 进程 → `SESSION_INDETERMINATE:PROTECTED_PAGE_ACCOUNT_UNREADABLE`（任务内 5 次 + 独立诊断 1 次）→ 任务停在 `WAITING_FOR_RESOURCE`。`SESSION_INDETERMINATE` 不走人工登录维护分支，用户得不到提示。

已确认的正常行为：两次 `PLATFORM_SECURITY_CHALLENGE` 均按设计转入维护、人工清除后 `promote` 并继续采集（`session_version` 每次递增），采集结束单元回到 `READY`。

## 状态历史

- 2026-09-28：建立 → 进行中；用户明确批准实施报告中的分阶段方案。
- 2026-09-28：范围调整；用户明确“自动化短信先不做”，继续 Chrome 短信／账号密码登录。
- 2026-09-28：真实复核发现跨重启业务会话未恢复、浏览器关闭可挂起；保持进行中并新增关闭隔离修复。
- 2026-09-28：真实第 2 页接口复用通过并限界到页 2；本地错误 READY 状态已审计纠正；最终回归 153 项通过。
- 2026-09-28：用户批准有界浏览器宿主架构变更；建立独立交接文档，下一窗口继续实现。
- 2026-09-28：新窗口开始继续实现；复核必读文档并确认用户授权已生效，任务保持进行中。
- 2026-09-28：有界浏览器宿主批次实现完成（宿主、迁移 005、仓储原子切换、Worker/CLI 协作、新增测试）；全套由 153 项更新为 **165 项通过**，静态检查通过。状态保持进行中／未验收（真实交接未跑）。
- 2026-09-28：迁移 005 应用到本地开发库；**真实账号同一上下文 `maintenance → collect` 交接与 2 位达人 `basic` 采集实测通过**，Chrome 确认关闭后单元回 `NEEDS_LOGIN`。状态仍为进行中／未验收：原任务幂等续跑、第 3 页及终点、其余主页模块与容量观察未完成。
- 2026-09-28：交付前收紧幂等边界；删除旧 `verify_maintenance` 会话递增入口，重复 `login` 确认在已有 maintenance 宿主时复用原 owner/generation/session，重复 wake 继续同一 workflow/root/checkpoint。最终 **166 项通过**，任务保持进行中／未验收。
- 2026-09-28：本轮结束回写；迁移 005 与单元安全终态只读核对通过。因真实 dispatch 原等待任务续跑、完整主页与容量观察尚未完成，状态继续为进行中／未验收，不宣称 AUTO-01 完成。
- 2026-09-28：真实 dispatch 原 root 经登录、挑战回切、再登录后 `valid_count 0→1→2`；修复额外 Page、残留 wake 和登录轮询重启，用 Temporal patch 兼容旧 history，原 workflow 正常完成。状态仍为进行中／未验收：完整主页与容量观察未完成。
- 2026-09-29T13:25:37+08:00：进行中 → 进行中。完成首次身份不可读后的 Session 复核、达人级三次尝试后跳过续跑、scoped Contract breaker、结构化会话/回收联动和迁移 006；178 项离线/合成测试通过。真实 5/10/20、50/100、完整主页与连续 7 天观察未执行，故不进入待验收或完成。
- 2026-09-29T13:46:05+08:00：进行中 → 进行中。迁移 006 已应用并只读确认本地开发库版本 1—6；无真实 Profile 或平台流量。剩余真实容量、完整主页与长期观察项不变。
- 2026-09-29T13:50:33+08:00：进行中 → 进行中。补齐 `XINGTU_SCOPED_CONTRACT_HEALTH=false` 紧急回滚开关并完成最终回归；真实验收项不变。
- 2026-09-29T14:56:37+08:00：进行中 → 进行中。独立测试轮真实观测：同一进程内连续采集 7 位成功（8 个 basic 快照），两次安全挑战维护→promote 处理正确；但采集中途 `LEASE_LOST`（2 次）叠加新进程账号不可读（5 次）使中断后续跑完全失败，真实 20/200 位与恢复验收仍不可达。缺陷归属见本卡新增小节与 [SESSION-01](SESSION-01.md)。
- 2026-10-05T16:05:03+08:00：进行中 → 进行中。SESSION-01 A/B 证实 macOS Playwright 默认 mock keychain 会清除自然 Chrome profile 的父账号认证，已用显式系统 Keychain 配置修复；但 Playwright 新进程仍按默认子账号重建业务会话，真实目标点击及选号 POST不生效，移除项目网络参数亦无改善。正式自动选号保持关闭，错误账号继续 fail-closed，真实恢复与容量验收仍不可达。
