# F04/F05 真实核心流程验证证据（2026-09-29）

日期：2026-09-29（Asia/Shanghai）。环境：macOS、本项目 `.venv`（Python 3.13.5）、PostgreSQL 18.3（`127.0.0.1:55439`，角色 `xingtu_test`，开发库 `xingtu_local_dev`）、Playwright Chromium 1243、本机 Chrome 154.0.8037.58、Temporal 测试服务器 v1.9.1、无 Git。
范围：**离线分层回归 + 真实平台**（巨量星图，本机 IP + 项目独立 Chrome + 持久 profile，`network_mode=local_development`）。真实登录由用户本人在有界 Chrome 窗口内完成，工具未接触或记录任何凭据。
任务卡：[F04](../tasks/F04.md)、[F05](../tasks/F05.md)；关联：[SESSION-01](../tasks/SESSION-01.md)、[AUTO-01](../tasks/AUTO-01.md)、[UNIT-01](../tasks/UNIT-01.md)。
命令与数据库原始记录：[命令记录](F04-F05-real-core-flow-2026-09-29.log)；独立会话诊断报告：[session-diagnostics](F04-F05-session-diagnostics-2026-09-29.json)。

## 1. 本轮目标

由测试角色独立复核 F04（平台筛选、搜索与候选发现）与 F05（达人主页资料采集）的核心流程：先跑完整离线分层回归，再用真实账号跑真实搜索 + 主页采集，逐项对照技术方案 §5/§6 的契约，并如实记录缺陷与未覆盖项。

## 2. 离线分层回归（通过）

| 检查 | 命令（实际） | 结果 |
|---|---|---|
| 静态检查 | `ruff check`、`ruff format --check`、`mypy backend/src` | 全部通过，退出码 0（36 files already formatted；17 source files 无 mypy 问题） |
| 单元 | `pytest backend/tests/unit` | 105 项（全套通过） |
| 契约 | `pytest backend/tests/contract` | 18 项（全套通过） |
| 集成 | `pytest backend/tests/integration` | 51 项（全套通过） |
| E2E | `pytest tests/e2e` | 4 项（全套通过） |
| 全套 | `pytest backend/tests tests/e2e -q --tb=short --import-mode=importlib` | **178 passed in 169.10s，退出码 0** |

集成/E2E 使用隔离测试库 `xingtu_test_f04f05`（DSN 见命令记录），未接触开发库；E2E 使用固定本地 Temporal 测试服务器二进制。本轮未修改任何源码或测试，因此不存在"改代码后未复测"的缺口。

## 3. 真实平台运行结果

### 3.1 运行 A（target=2）：F04+F05 核心流程**通过**

根任务 `1807a588-f7dc-46e3-83f4-ef50c7cf92b5`（`xingtu-ad-creator-square-v1`、关键词「宠物」、`sort=score`、`target_count=2`）。

时间线（`audit_logs`）：14:18:09 `invalidate_session`（测试按有证据的会话不可读状态将其置为 `NEEDS_LOGIN`）→ 14:18:11 `internal_acceptance.start` → 14:18:35 `promote_maintenance_to_collect`（**用户人工登录后**，`session_version 10 → 11`）→ 14:21:47 任务终态。

`make smoke-local` 输出（真实 `Activities.collect` + `CollectionWorkflow`）：

| 指标 | 实际值 | 判定 |
|---|---|---|
| `workflow_state` / `task_state` | `PARTIAL_COMPLETED` / `PARTIAL_COMPLETED` | 与注册范围一致（见下） |
| `discovered_count` / `scanned_count_segment` | 20 / 20 | 首页 20 位候选全部扫描 |
| `valid_count` | **2** | 达到 `target_count` 即停止 |
| `search_exhausted` / `search_stop_reason` | `false` / `null` | **未谎报"平台已耗尽"** |
| `search_generation` / `rescan_reasons` / `diagnostics` | 0 / `[]` / `[]` | 无重扫、无无身份候选 |
| `failure_reason` | `PROFILE_SCOPE_INCOMPLETE` | 注册表只有 `basic`、`featured=[]`，如实标为不完整 |
| `active_seconds`（预算引用） | 192.42 | 远低于 `active_seconds=7200` |
| `observed_requests` / `observed_responses` | 3 / 3 | 1 次搜索 + 2 次主页 `basic` 请求，无越界响应 |
| `failure_counts` | `{}` | 无错误计数 |

F05 字段级核对（两位达人的已发布快照，同一 `basic` 模块）：

| 达人（`platform_creator_id` / 昵称） | 首位位置 | `basic.status` | `complete` | `coverage_gaps` | 字段数 |
|---|---|---|---|---|---|
| 6849131371793743886 / 娱乐课代表孙小寒 | 0 | `COLLECTED` | `true` | `[]` | 9 |
| 7360610271510921225 / C位小师妹 | 1 | `COLLECTED` | `true` | `[]` | 9 |

9 个字段（`platform_creator_id`、`nickname`、`avatar_uri`、`followers`、`gender`、`city`、`province`、`mcn_name`、`content_theme_labels`）逐项带来源与观测：`source_kind=response`、真实 `path_ref`（如 `id`、`nick_name`）、`operation_id`、`observed_at`（`2026-09-29T06:21:4xZ`）、`session_version=11`、`source_contract=xingtu-ad-creator-square-v1`、`evidence_refs`；`followers` 为 `{kind:number, amount:4271428/5713574, bound:exact, quantum:1}` + `unit=count`，未把缺失写成 0。

`first_position` 为 0、1 且唯一，与平台顺序一致；`task_creators.valid=true`、`latest_snapshot_id` 非空。

### 3.2 运行 C（target=25）：部分成功，被会话与租约缺陷中断

根任务 `1cdd495b-8ce6-4177-a007-79283db540f8`（同契约与关键词，`target_count=25`，意在触发 `page=2` 并验证 20 位以上连续采集）。14:32:46 置 `NEEDS_LOGIN` → 用户再次人工登录 A 账号 → 14:33:57 `promote`（`session_version 11 → 12`）。

| 时间 | 事件 | 判定 |
|---|---|---|
| 14:33:57 | `promote_maintenance_to_collect`（人工登录核验通过） | 正确 |
| 14:37:09 → 14:37:10 | `PLATFORM_SECURITY_CHALLENGE` → 维护 → 挑战清除后 `promote`（→13） | **自动恢复正确** |
| 14:40:32 → 14:40:33 | 同上第 2 次（→14） | **自动恢复正确** |
| 14:40:39 | 有效达人 7 位、首页 20 位候选、`search_generation=1` | 连续采集推进 |
| 14:45:13 | `LEASE_LOST` → 任务 `WAITING_FOR_RESOURCE` | **缺陷 D3** |
| 14:45:53 | Temporal 重试，新 Chrome 进程重新取租约 | — |
| 14:50:14 | `SESSION_INDETERMINATE:PROTECTED_PAGE_ACCOUNT_UNREADABLE` | **缺陷 D1 复现** |
| ~14:53 | 停止运行（人工终止，避免无意义空转） | — |

检查点事实：`failure_counts = {PLATFORM_SECURITY_CHALLENGE: 2, SESSION_INDETERMINATE: 2, LEASE_LOST: 1}`、`active_seconds=937.9`、候选 20、`search_generation=1`。

**已落库成果（真实）**：7 位有效达人、8 个 `basic` 模块快照，每个快照 `status=COLLECTED`、`complete=true`、9 字段（达人 `6849131371793743886` 在新任务中被再次采集，产生第 2 个快照——对应"已有达人计入目标并重新采集"，且旧快照未被覆盖）。
**未达成**：未到 `page=2`（首页候选处理完之前即中断），`target_count=25` 未满足，任务最终为 `WAITING_FOR_RESOURCE` 后被取消。

### 3.3 运行 B/D（未给登录窗口）：会话核验失败

| 运行 | 计划 | 根任务 | 现象 |
|---|---|---|---|
| D（14:00 启动） | `target_count=2` | `6ea0296e-a086-4cd3-87d6-9190cffc8fa3` | 14:05:10 `SESSION_INDETERMINATE:PROTECTED_PAGE_ACCOUNT_UNREADABLE` → 重试 → 14:12:39 `LEASE_LOST` → 重试 → 无法自愈，人工取消 |
| B（14:23 启动） | `target_count=25` | `82506ea5-b11c-4d02-9ae4-a3396426294e` | 14:28:23 同一会话错误 → 重试 → 人工取消 |

两次均以单元 `READY` 起步（`maintenance=False`，直接进入 `collect`），因此会话核验失败被归入"资源等待"而不是登录维护。

### 3.4 独立会话诊断（非采集路径）

`xingtu session-diagnostics --config .runtime/units/local-dev-mac-02.json`（冷启动同一 profile，输出见诊断报告）：

| 项 | 实际值 |
|---|---|
| `session_health.status` | `INDETERMINATE` |
| `expected_account_id` / `observed_account_id` | `ID: 1865332309937515` / **`null`** |
| `protected_page_verified` / `login_page_verified` / `challenge_verified` | `true` / `false` / `false` |
| `evidence_reason` | `PROTECTED_PAGE_ACCOUNT_UNREADABLE` |
| Cookie 记录 | 49 个，含 `d_ticket`、`odin_tt`、`sid_ucp_sso_v1`、`passport_*` 等 oceanengine SSO Cookie（仅 HMAC，无明文） |
| 浏览器 | Chrome 154.0.8037.58，`normal_close_confirmed=true` |

即：**会话本身看起来是活的（受保护页可见、SSO Cookie 齐全），但登记的账号定位器取不到账号值**，且无法据此区分"未登录""账号不同""页面变体"。

## 4. 对照技术方案 §5/§6 的核对结论

| 契约条款 | 核对方式 | 结论 |
|---|---|---|
| §5.2.2 按平台顺序、首次位置唯一、跨页去重 | 运行 A/C 的 `task_creators.first_position` + 集成用例 | 通过（真实首屏）/ 部分（跨页未在真实环境复核） |
| §5.2.2 达到目标即停止、不谎报耗尽 | 运行 A：`valid=2`、`search_exhausted=false` | 通过 |
| §5.2.2 无效/无身份候选记录诊断、不计有效数 | `diagnostics=[]`（本轮真实未出现） | 离线/合成覆盖，真实未复现 |
| §5.2.3 游标失效重扫、保留首次位置、不禁用契约 | 运行 A/C 无重扫（`search_generation` 未因失效增加） | 离线/合成覆盖，真实未复现 |
| §5.3 20/200 位停止 | 运行 C 未达 25 | **未通过（被缺陷 D1/D3 阻断）** |
| §6.2.1 主页身份与最低有效资料、重定向复验 | 两位达人主页身份核对通过并落库 | 通过（小样本） |
| §6.2.2 模块注册表与逐模块执行 | 仅 `basic` 已登记并采集 | 通过（就注册范围而言） |
| §6.2.3 字段字典、单位、原文保留 | 9 字段均带 `raw_value`/`unit`/来源/观测时间 | 通过 |
| §6.2.4 字段状态与模块覆盖 | `COLLECTED` + `complete` + `coverage_gaps` 三者一致 | 通过 |
| §6.2.4 恢复产生新观测、不覆盖旧观测 | 运行 C 中同一达人出现 2 个快照、快照不可变 | 通过 |
| §6.2.1 单达人失败不放大为整任务失败 | 运行 C 中 7 位连续成功；身份不可读未在本轮真实出现 | 离线/合成覆盖 |
| §5/§6 其余主页模块、统计周期默认口径 | 注册表只有 `basic` | **未核验（U04）** |
| §5 筛选枚举/组合、访问节奏与限流 | 未执行 | **未核验（U02）** |
| §5 第 3 页及分页终点 | 契约 `page_fetch_max_verified=2` 且本轮未到 page 2 | **未核验（U04）** |

## 5. 本轮发现的缺陷

### D1 新 Chrome 进程内账号元素不可读（会话核验 INDETERMINATE）— 阻断恢复

- **现象**：用户刚在同一 profile 内完成登录并采集成功后，任何新的 Chrome 进程都会得到 `SESSION_INDETERMINATE:PROTECTED_PAGE_ACCOUNT_UNREADABLE`（`observed_account_id=null`），而受保护页可见。
- **复现次数**：2026-09-29 当天**任务内计数 5 次**（运行 D `failure_counts.SESSION_INDETERMINATE=2`、运行 B `=1`、运行 C `=2`；运行 A `={}`），**另有 1 次独立 `session-diagnostics` 冷启动**复现，合计 6 次。运行 D/C 各另有 1 次 `LEASE_LOST`。
- **用户观察（未由本轮独立验证）**：人工登录的是 A 账号，但最近唤起的 Chrome 实际是 **B 账号**；与 [SESSION-01 两段式验收](SESSION-01-acceptance-2026-09-29.md) 记载的"同 profile 账号漂移"一致。
- **影响**：真实任务一旦中断（崩溃、租约丢失、进程重启）就无法自动续跑；每次续跑都必须人工重新登录；F04/F05 的"20/200 位连续采集""恢复"在真实环境不可验收。
- **归属**：[SESSION-01](../tasks/SESSION-01.md)（账号漂移根因 H-A/H-B 仍未定）。

### D2 会话 `INDETERMINATE` 没有登录降级路径

- `SESSION_INDETERMINATE` 被归入"资源等待"（任务 `WAITING_FOR_RESOURCE`，单元 `SESSION_UNVERIFIED`），只做有限次数重试，**不会创建人工登录维护窗口**（`worker.py` 的维护分支只接受 `NEEDS_LOGIN`/`ACCOUNT_MISMATCH`）。
- 后果：用户从未被提示需要登录；同一失败在 14:05→14:50 之间重复 5 次而没有可用出口。测试过程中只能由人工用 `Repository.invalidate_session(...)`（审计动作 `invalidate_session:unit-local-mac-02:PROTECTED_PAGE_ACCOUNT_UNREADABLE`）显式打开维护窗口才能继续。
- **归属**：[SESSION-01](../tasks/SESSION-01.md)／[AUTO-01](../tasks/AUTO-01.md)。

### D3 采集中途 `LEASE_LOST`（租约 120s、心跳 15s）

- 运行 C 在有效 7 位、采集第 8 位时于 14:45:13 报 `LEASE_LOST`（`Repository.heartbeat` 的 `UPDATE ... WHERE lease_until>now()` 未命中）；运行 D 在 14:12:39 同样报错。
- 该错误使任务转入 `WAITING_FOR_RESOURCE` 并触发**新进程**重试，与 D1 叠加后必然失败，已采数据只能靠检查点保留。
- **本轮未能定位根因**（未取得该时刻的心跳间隔与页面调用耗时证据），仅记录现象与两次复现（运行 D `LEASE_LOST:1`、运行 C `LEASE_LOST:1`）；`lease_until` 续期 120s、心跳周期 15s，正常情况下不应丢失。
- **归属**：[AUTO-01](../tasks/AUTO-01.md)／[UNIT-01](../tasks/UNIT-01.md)（有界宿主与租约语义）。

### 已确认的正常行为（非缺陷）

- 两次 `PLATFORM_SECURITY_CHALLENGE` 均被正确处理：转入维护 → 等待人工清除 → `promote` 后继续采集，且每次都递增 `session_version`。
- 采集结束后单元回到 `READY`（运行 A），会话核验通过的结果没有被伪报；`PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE` 如实反映"只登记了 basic、精选集合为空"。

## 6. 未执行与未核验项

- 真实 `page=2` 请求与第 3 页及分页终点（本轮未推进到任何翻页；`page_fetch_max_verified=2` 未受影响，仍为未核验边界）。
- 真实 20/200 位连续采集、50/100 位容量、连续 7 天观察。
- 真实筛选枚举与组合（合作诉求／匹配度／性价比／主题推荐）、访问节奏与限流阈值。
- 其余主页模块（商业与报价、传播与互动汇总、粉丝画像）字段字典与默认统计口径（注册表 `modules` 仍只有 `basic`）。
- 跨任务会话复用（本轮所有"成功"都发生在**人工登录后的同一 Chrome 进程**内，不构成本卡意义上的跨重启复用证据）。

## 7. 证据文件

- 命令记录：[F04-F05-real-core-flow-2026-09-29.log](F04-F05-real-core-flow-2026-09-29.log)（静态检查、178 项回归尾部、运行 A 完整输出、数据库只读查询、审计时间线、诊断摘要）
- 诊断报告：[F04-F05-session-diagnostics-2026-09-29.json](F04-F05-session-diagnostics-2026-09-29.json)
- 运行现场（工作区，未纳入 `docs/`）：`.runtime/verify-2026/` 下的 `static.log`、`full-suite.log`、`real-run-{1,2,3,4}.log`、`start*.json`
- 相关历史证据：[UNIT-01 真实采集](UNIT-01-real-collection-2026-09-27.md)、[有界宿主真实运行](AUTO-01-bounded-host-real-run-2026-09-28.md)、[SESSION-01 两段式验收](SESSION-01-acceptance-2026-09-29.md)
