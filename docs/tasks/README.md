# 开发任务索引

# 2026-09-29 F04/F05 真实核心流程测试轮

独立测试角色复核 F04/F05 核心流程，证据见 [F04/F05 真实核心流程证据](../evidence/F04-F05-real-core-flow-2026-09-29.md)：离线 `ruff`/`format-check`/`mypy` 通过、**178 项测试全通过**（105/18/51/4）；真实 `target=2` 关键词搜索 + 2 位达人主页采集**通过**（`valid=2`、`discovered=20`、`search_exhausted=false`，`basic` 9 字段逐项带来源），真实 `target=25` 在单进程内连续采集 **7 位**后中断。

本轮登记三个未修复缺陷：**D1** 新 Chrome 进程账号元素不可读（任务内 5 次 + 独立诊断 1 次，`observed_account_id=null`）、**D2** 该 `SESSION_INDETERMINATE` 不打开登录窗口、**D3** 采集中途 `LEASE_LOST`（2 次，根因未定位）。三者叠加使真实 20/200 位与恢复验收不可达；F04/F05 因实机核验项（筛选枚举、访问节奏、分页、其余主页模块）仍未完成而保持**待验收**。

# 2026-09-29 会话寿命更正

[SESSION-01](SESSION-01.md)：**待验收／未验收**，不计入一期 12 项。原载“实测证明星图业务会话不能跨 Chrome 重启恢复”的结论因证据不足已撤回；当前代码与状态机以 [DEC-013](../decisions/DEC-013-structured-session-and-scoped-contract-health.md) 为准。

**2026-09-29 首次两段式真实验收（4 次运行）**，完整证据见[两段式验收证据](../evidence/SESSION-01-acceptance-2026-09-29.md)：

- ✅ **会话跨任务复用机制成立（历史四轮实测）**：单元为 `READY` 时以 `collect` 模式复用 Profile，`session_version` 不变、**未发生 promote、未要求人工登录**。该证据来自 DEC-012 时期；当前代码必须在新 Chrome 进程内重新得到 DEC-013 的 `VALID` SessionHealth，不能仅信任旧 `READY`。
- ❌ **发现账号在同一 profile 内漂移**：run 3 与 run 4 间隔约 3 分钟、无人工登录，实际账号却从 `1865332309937515`（绑定）变为 `1832740070238347`。这是 run 2／run 4 失败的直接原因。
- 已修复：账号不匹配独立为 `ACCOUNT_MISMATCH/WAITING_FOR_ACCOUNT`；旧 READY 不再提前证明当前 Session；过期租约可单步回收且不依赖 `/bin/ps`。账号漂移根因和长期寿命仍待单账号真实实验。

核验完成前不得以任一方向结论作为设计前提；"登录一次存活 1 个月"仍未达成。

结构性修复见 [DEC-013](../decisions/DEC-013-structured-session-and-scoped-contract-health.md) 与[实施证据](../evidence/SESSION-01-implementation-2026-09-29.md)：五态 SessionHealth、显式 ReleaseDisposition、HMAC 诊断、首次身份失败后的 Session 复核、达人级重试/跳过及 scoped breaker/回滚开关已实现；**178 项离线/合成测试通过**（105/18/51/4）。真实单账号清理、5/10/20 和 30 天长测未执行，故仍未验收。

# 2026-09-28 自动化优化补充

[AUTO-01](AUTO-01.md)：**进行中／未验收**，为跨现有功能卡的优化跟踪项，不计入原 12 个一期交付单元。2026-09-29 已实现单达人 `IDENTITY_UNREADABLE` 三次尝试后跳过续跑、按能力 scope 的 Contract breaker，并通过合成 20/200 位连续任务；旧“任务结束必回 NEEDS_LOGIN”已被 DEC-013 取代。未验收：真实全字段、第 3 页及终点、真实 5/10/20、50/100 与 7 天观察。


> 更新时间：2026-09-29T14:56:37+08:00。具体实现与验收事实只在各卡片及其证据维护；本表同步ID、标题、状态和链接。

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
