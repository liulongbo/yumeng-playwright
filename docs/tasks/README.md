# 开发任务索引

# 2026-10-06 达人完整资料与连续分页实施

[AUTO-01](AUTO-01.md) 已完成当前可离线实施部分：主页从 9 个基础字段扩展为 6 模块/61 个结构化字段，新增首页加载多模块响应捕获、连续分页能力门槛、连续两页无新 ID 保护，并通过 130 项单元/浏览器合约与 52 项范围内 PostgreSQL 集成测试。真实 Page 1/Page 2 仍返回各 20 位且 ID 摘要不同，主页业务端点仍存在。修复研究工具后重启 Chrome 出现 `ACCOUNT_MISMATCH`，按既定范围停止真实测试；需人工选择/登录 `ID: 1865332309937515`后继续 Page 3 与 61 字段数据库对照。AUTO-01 为**阻塞/未验收**，F04/F05 仍为**待验收**。详见[2026-10-06 实施证据](../evidence/AUTO-01-profile-pagination-implementation-2026-10-06.md)。

# 2026-10-05 子账号回退诊断链修复 + 真实 A/B 进行中

2026-10-06 发布前复核：本地与 `origin/main` 无分叉，明文凭据扫描通过，`make check`（107 单测）、21 项 Browser Contract 及探针 10+2 项自检通过。本轮仅发布已记录的安全修复和诊断证据；SESSION-01 状态仍为进行中／未验收。

[诊断链实施证据](../evidence/SESSION-01-subaccount-diagnostics-implementation-2026-10-05.md)：已修正页面跳转丢失最后点击与 `add_init_script` 未真正执行的缺陷，新增 Python binding、脱敏请求—响应—会话检查点、Playwright `locator.click()` 及受限 A/B 开关；最终 `make check`（107 单测）和 21 项 Browser Contract 通过。正式 Adapter 自动选号保持关闭，见 [A/B 手册](../handoffs/SESSION-01-browser-ab-runbook.md)。

登录页／业务页逻辑已闭合：维护和采集优先进入受保护业务页，有效会话展示登录后页面，真实失效才由平台跳登录；首次不可判定仅做一次有界 SSO 握手后回业务页复核。B1/B2 进一步证实 macOS Playwright 默认 mock keychain 会让自然 Chrome profile 的认证 Cookie 不可用并被清除；已用执行单元显式 `macos_system_keychain` 修复，只忽略 `--use-mock-keychain`，不改 UA、`navigator.webdriver`，不做 stealth。

A 组第三账号对照已通过：不经过 Playwright 的项目 profile 选择 `1831973402720484` 后，在选择后、刷新后、达人广场三个检查点均保持该账号。因此不是“所有非默认账号都会在项目 profile 中回退”。

A 组目标账号也已通过：从第三账号切到 `1865332309937515` 后，点击后立即、等待 10 秒、刷新和达人广场均稳定保持目标，且未曾短暂回退。由此排除目标账号当前不可用及项目 profile 自身异常。

B3/C 最终证明自动选号在当前 Playwright 环境中不可靠：目标条目收到可信点击，实际选号 POST 返回 HTTP 200并导航，但账号和 `star_sessionid` HMAC均不变；移除 `--disable-quic` 与 WebRTC UDP 参数后，4 次请求／54 个检查点仍相同。因此项目网络参数排除，不实施自动选号、Cookie 注入、自动化伪装或无限重试；优先在平台设置目标为默认账号，或为目标使用独立登录身份。

# 2026-10-05 账号漂移专项检测

新增只读探针 [account_drift_probe.py](../../scripts/account_drift_probe.py)（不点击／不登录／不切换账号，凭证只记 HMAC）。它把过去混为一谈的三种现象拆开判定：`DRIFT_WITHIN_PAGE`（同页反复读就变）、`DRIFT_WITHIN_PROCESS`（同进程跨页面/标签页变）、`DRIFT_ACROSS_RESTART`（重启 Chrome 后变，与 run 3→run 4 同型），并记录定位器匹配数、iframe 内匹配数、单页内不同 `ID:` 数量（H-A 直接判据）与凭证指纹做载体定位。人工登录期间不导航，人工窗口观测不计入漂移判定。离线自检 7 项判定 + 2 项载体/人工窗口用例通过，`ruff`/`format` 通过。

**本轮已确认**：

1. 用户现场确认目标子账号 `ID: 1865332309937515` 在平台子账号列表中**可见且可选** → 排除"父账号无权访问目标子账号"，问题指向**自动化缺少"选定目标子账号"步骤**（契约 `session` 段无任何选号动作）。`子账号` 概念在 `docs/` 与 `backend/` **全仓零命中**，技术方案 U06 要求账号识别却未定义选号流程，属**文档/PRD 缺口，需产品侧补需求**。
2. **漂移真实复现**（[证据](../evidence/account-drift-probe-2026-10-05.md)）：人工登录并选定目标子账号后，间隔约 3 分钟重启 Chrome，生效账号由 `1865332309937515` 变为 `1832740070238347`（与 run 4 一致），判定 `IDENTITY_CHANGED_WHILE_UNREADABLE`（退出码 1）。同一进程内跨页面/同页反复读/第二标签页均为目标账号，排除页面差异与多标签页解释。
3. **缺陷 D1 与漂移同源**：漂移后受保护壳不渲染 → 账号定位器匹配数 0、受保护页不可见 → 系统只得 `SESSION_INDETERMINATE`。D1 是"错误账号"被误分类为"会话不可判定"。
4. **载体收敛**到唯一变化的身份 Cookie `star_sessionid`；`possess_scene_star_id`、`session_tlb_tag` 逐字节未变，原推测被否定。

**未完成**：H-A 与 H-B 仍未区分（只证明"生效账号改变"）；漂移属"重启触发"还是"时间触发"未测；长期存活仍未取得。[SESSION-01](SESSION-01.md)、[AUTO-01](AUTO-01.md) 相应验收项保持未勾选。

**2026-10-05 最小验证**（[证据](../evidence/account-drift-probe-2026-10-05-minimal-verification.md)）：① 客户端**未持久保存子账号**（`localStorage` 的 STAR 键为空数组）；② 重启后**确实落到默认子账号** `1832740070238347`，且冷启动时 SSO 登录在而 `star_sessionid` 缺失、**停在 SSO 入口页永不签发业务会话**；③ **自动选号尚未成功**——已排除"账号信息弹层"，真正选号入口未定位，按规范不猜选择器；④ **选中不跨重启保持**。漂移第二次复现且本次导航栏正常渲染、系统自身给出 `ACCOUNT_MISMATCH` → **D1 与 `WRONG_ACCOUNT` 是同一次漂移的两种表现**。**结论**：自动选号由"可选"变为**必需且每个新 Chrome 进程都要执行**；"往 Cookie 里加子账号"不可行。**阻塞**：定位选号入口需操作者提供人工切换路径。

# 2026-09-29 F04/F05 真实核心流程测试轮

独立测试角色复核 F04/F05 核心流程，证据见 [F04/F05 真实核心流程证据](../evidence/F04-F05-real-core-flow-2026-09-29.md)：离线 `ruff`/`format-check`/`mypy` 通过、**178 项测试全通过**（105/18/51/4）；真实 `target=2` 关键词搜索 + 2 位达人主页采集**通过**（`valid=2`、`discovered=20`、`search_exhausted=false`，`basic` 9 字段逐项带来源），真实 `target=25` 在单进程内连续采集 **7 位**后中断。

本轮登记三个未修复缺陷：**D1** 新 Chrome 进程账号元素不可读（任务内 5 次 + 独立诊断 1 次，`observed_account_id=null`）、**D2** 该 `SESSION_INDETERMINATE` 不打开登录窗口、**D3** 采集中途 `LEASE_LOST`（2 次，根因未定位）。三者叠加使真实 20/200 位与恢复验收不可达；F04/F05 因实机核验项（筛选枚举、访问节奏、分页、其余主页模块）仍未完成而保持**待验收**。

# 2026-09-29 会话寿命更正

[SESSION-01](SESSION-01.md)：**进行中／未验收**，不计入一期 12 项。原载“实测证明星图业务会话不能跨 Chrome 重启恢复”的结论因证据不足已撤回；当前代码与状态机以 [DEC-013](../decisions/DEC-013-structured-session-and-scoped-contract-health.md) 为准。

**2026-09-29 首次两段式真实验收（4 次运行）**，完整证据见[两段式验收证据](../evidence/SESSION-01-acceptance-2026-09-29.md)：

- ✅ **会话跨任务复用机制成立（历史四轮实测）**：单元为 `READY` 时以 `collect` 模式复用 Profile，`session_version` 不变、**未发生 promote、未要求人工登录**。该证据来自 DEC-012 时期；当前代码必须在新 Chrome 进程内重新得到 DEC-013 的 `VALID` SessionHealth，不能仅信任旧 `READY`。
- ❌ **发现账号在同一 profile 内漂移**：run 3 与 run 4 间隔约 3 分钟、无人工登录，实际账号却从 `1865332309937515`（绑定）变为 `1832740070238347`。这是 run 2／run 4 失败的直接原因。
- 已修复：账号不匹配独立为 `ACCOUNT_MISMATCH/WAITING_FOR_ACCOUNT`；旧 READY 不再提前证明当前 Session；过期租约可单步回收且不依赖 `/bin/ps`。账号漂移根因和长期寿命仍待单账号真实实验。

核验完成前不得以任一方向结论作为设计前提；"登录一次存活 1 个月"仍未达成。

结构性修复见 [DEC-013](../decisions/DEC-013-structured-session-and-scoped-contract-health.md) 与[实施证据](../evidence/SESSION-01-implementation-2026-09-29.md)：五态 SessionHealth、显式 ReleaseDisposition、HMAC 诊断、首次身份失败后的 Session 复核、达人级重试/跳过及 scoped breaker/回滚开关已实现；**178 项离线/合成测试通过**（105/18/51/4）。真实单账号清理、5/10/20 和 30 天长测未执行，故仍未验收。

# 2026-09-28 自动化优化补充

[AUTO-01](AUTO-01.md)：**进行中／未验收**，为跨现有功能卡的优化跟踪项，不计入原 12 个一期交付单元。2026-09-29 已实现单达人 `IDENTITY_UNREADABLE` 三次尝试后跳过续跑、按能力 scope 的 Contract breaker，并通过合成 20/200 位连续任务；旧“任务结束必回 NEEDS_LOGIN”已被 DEC-013 取代。未验收：真实全字段、第 3 页及终点、真实 5/10/20、50/100 与 7 天观察。


> 更新时间：2026-10-06T16:03:29+08:00。具体实现与验收事实只在各卡片及其证据维护；本表同步ID、标题、状态和链接。

**先看[项目任务进度总览](../项目任务进度总览.md)**：当前进度、推荐顺序、F/T/U覆盖、依赖及AI执行方式。

## 一期交付（12项）

| ID | 标题 | 状态 | 卡片 |
|---|---|---|---|
| BASE-01 | 必要工程基础 | 待验收 | [BASE-01.md](BASE-01.md) |
| UNIT-01 | 执行单元与平台核验（先本地后蜂窝） | 待验收 | [UNIT-01.md](UNIT-01.md) |
| F04 | 平台筛选、搜索与候选发现 | 待验收 | [F04.md](F04.md) |
| F05 | 达人主页资料采集 | 待验收 | [F05.md](F05.md) |
| APP-01 | 产品应用基础与登录会话 | 待办 | [APP-01.md](APP-01.md) |
| INTAKE-01 | 筛选表单、P1转换与可靠提交 | 待办 | [INTAKE-01.md](INTAKE-01.md) |
| F06 | 主页精选作品采集与封面存储 | 待验收 | [F06.md](F06.md) |
| CONSOLE-01 | 任务中心与任务内达人结果 | 待办 | [CONSOLE-01.md](CONSOLE-01.md) |
| F09 | 手动刷新达人 | 待办 | [F09.md](F09.md) |
| F10 | 执行单元状态与远程登录维护 | 待办 | [F10.md](F10.md) |
| OPS-01 | 生产运行、资源调度与运维恢复 | 待办 | [OPS-01.md](OPS-01.md) |
| RELEASE-01 | 一期全链路联调与上线验收 | 待办 | [RELEASE-01.md](RELEASE-01.md) |

## 管理文档任务（不计入产品进度）

| ID | 标题 | 状态 | 卡片 |
|---|---|---|---|
| PLAN-01 | 项目进度基线与完整任务规划 | 已完成 | [PLAN-01.md](PLAN-01.md) |
| PLAN-02 | 开发与自动测试后强制回写任务进度 | 已完成 | [PLAN-02.md](PLAN-02.md) |

开发或MCP／工具测试结束后，由负责的AI按[开发规范第4.5节](../agent.md)自动回写原卡片，并同步本索引及项目总览，无需用户提醒。

## 依据

- [完整技术方案](../AI达人智能发现与采集系统-完整技术方案.md)
- [开发与运维说明](../development.md)
- [本轮静态基线证据](../evidence/PROJECT-BASELINE-2026-09-27.md)
- [本轮 UNIT-01 本地阶段证据](../evidence/UNIT-01-local-stage-2026-09-27.md)
- [本轮 UNIT-01 真实采集证据](../evidence/UNIT-01-real-collection-2026-09-27.md)
- [F06 离线验证证据](../evidence/F06-offline-verification.md)
- [历史离线验证证据](../evidence/F04-F05-offline-verification.md)
- [平台契约登记说明](../../contracts/README.md)

2026-09-27 本轮（F06）：两组默认精选集合与封面存储已完成离线实现并通过四层测试，迁移 003 已在既有本地开发库应用；F06 由"待办"改为**待验收**（真实 U05/U09 核验未执行）。

2026-09-27 本轮（最新，UNIT-01 本地阶段真实采集）：用户可接收验证码后，完成**真实登录 + 真实搜索 + 2 位达人主页采集与落库核对**；平台契约 `xingtu-ad-creator-square-v1` 已由真实交互登记并通过 live 门槛发布（[真实采集证据](../evidence/UNIT-01-real-collection-2026-09-27.md)）。迁移 004（本地出口共享）随之落地。状态统计更新为：**待验收 5**（BASE-01、UNIT-01、F04、F05、F06）、阻塞 0、待办 7、已完成 0。UNIT-01 由"阻塞"改为**待验收**：分页仅核验首页、主页只登记 `basic` 模块、筛选枚举与访问节奏未核验、生产线路与远程维护（U06/U07/U08）未执行，整卡不得标为已完成。两组精选集合契约（F06）仍未登记。
