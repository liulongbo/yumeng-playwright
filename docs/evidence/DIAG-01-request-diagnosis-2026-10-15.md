# DIAG-01 巨量星图采集请求行为与验证触发专项诊断报告

- 日期：2026-10-15（Asia/Shanghai）
- 诊断任务卡：[DIAG-01](../tasks/DIAG-01.md)
- 诊断代码版本：分支 `llb_1013`，HEAD `ee1125412a181e4df13fbe32ea0242a18ab02622`，工作区含用户未提交改动；逐文件 sha256 见 `.runtime/diag01/revision-sha256.txt`
- 环境：macOS 本机真实 Chrome + 项目独立 profile `.runtime/profiles/unit-local-mac-02`；`local_development`；真实 PostgreSQL `55432/xingtu_development`；Temporal `57233`
- 本轮真实采集任务：`381d628b-e6e8-4d0e-865e-ed4aab98c11c`（关键词「汽车」、目标 2 位、产品前端提交、仅提交一次）
- 关联证据：`.runtime/diag01/`（普查 jsonl、census-analysis、census-windows、final-metrics、run-evidence.json、wf-history）

> **结论纪律**：本报告严格区分 ①已证实的系统问题 ②与验证事件有时间关联的异常 ③有证据支持的原因假设 ④无证据的推测。**不声称已证明平台内部风控规则。**

---

## 第一部分：执行摘要（面向产品负责人）

1. **当前采集系统整体是否正常？** 主链路可用：产品前端提交 → API → 模型转换 → Temporal → Playwright → 落库 → 回显全程走通，本轮 2 位达人均成功入库资料并生成快照。**但交付不完整**：两组精选集合与全部封面本次**一条都没有采到**，任务以"部分完成"收口。

2. **是否发现明显异常请求？** 是。本轮 2 位达人、零验证的**健康**运行仍产生 **2698 条网络请求**，其中：
   - 静态资源 1743 条（64.6%），**其中 1345 条是同一 URL 的完全重复下载**（占全部请求的 49.9%）；
   - 平台 API 542 条（20.1%）；埋点/监控/安全 SDK 183 条（6.8%）；
   - 而系统自己的"关联业务请求"计数器只记 **49 条**（1.8%）。

3. **两个达人产生多少请求？** 取决于口径，同一件事有三个数字：**49**（系统计数器"关联请求"）、**555**（平台主域 `xingtu.cn` 请求）、**2698**（全部网络请求）。

4. **请求数量是否合理？** **不合理**。合理的部分：49 条业务请求对 2 位达人（≈24.5 条/达人），与该系统历史健康基线（30–45 条/达人）同量级。不合理的部分：① 同一位达人的主页在自动流程中被**整页重复加载**（本轮每达人 2 次，正常完成会到 3 次），每次整页加载带来约 **270 条**网络请求；② 任务一旦落到 `WAITING_FOR_RESOURCE`，工作流**每 30 秒重跑整段采集**（重启 Chrome + 重新搜索 + 从第 1 页重扫）。

5. **与人工操作有哪些已验证差异？** 已取得完整人工基线（用户在同一单元/profile/账号手工完成**同样两位达人**的任务）。**核心差异：同样两位达人，自动化在更短的时间内发出 1.46 倍总请求**，且多出来的几乎全是**页面加载开销**而非业务请求 —— 静态资源 1.74×、完全重复请求 2.06×，而平台 API 仅 1.21×。机制已定位：**人工对每位达人主页只整页加载 1 次，自动化加载 2 次**（精选正常完成时为 3 次）。自动化失败率反而更低（2.8% vs 人工 4.6%），说明"自动化因重试多请求"在本样本中不成立。

6. **当前最需要解决的三个问题：**
   - **ISSUE-001（P0）**：精选集合整段未采集 —— 2 位达人的精选集合判定为 `IDENTITY_MISMATCH` 而全部 `NOT_ATTEMPTED`，数据库 `featured_collections` **0 行**、封面 0 个；而观测证据表明页面加载的确实是**同一位达人**。
   - **ISSUE-002（P0）**：`WAITING_FOR_RESOURCE` 触发每 30 秒整段重跑 —— 已在 Temporal 历史中实证；同一达人耗时从 77 秒膨胀到 263 秒，请求近乎翻倍。
   - **ISSUE-004（P1）**：请求量口径严重失真 —— 同一个 30 秒失败运行，计数器显示 **0 条请求**，实际发生 **542 条**；跨操作重复请求计数器恒为 0（本轮实测 1966 条）。团队据此做的任何"请求降幅"结论都不可靠。

7. **哪些问题可能与验证频繁出现有关？**
   - **ISSUE-002 / ISSUE-003（结构性放大，证据充分，因果为假设）**：重复整页加载与每 30 秒整段重跑，把平台可见流量放大 2–3 倍。这是我们**唯一有量级证据**的"自身原因"。
   - **ISSUE-005（证据充分）**：2026-10-15 一次真实自然挑战，检测到放行仅 **5.740 秒**，且等待期 `challenge_samples=0` —— 即**新增的 15 秒观测窗口没有生效**。历史 69–84ms 误恢复已修，但"检测后等待期未再看到挑战即按 5 秒放行"的路径仍在。
   - 静态资源重复是否被风控计入，**无证据**，不作因果断言。

8. **是否建议立即修改？** **建议立即修 ISSUE-001 与 ISSUE-002**（一个导致交付缺失，一个导致流量与耗时成倍放大），其余按第八部分优先级排期。本轮**未做任何修复**。

---

## 第二部分：测试环境与测试范围

| 项 | 值 |
|---|---|
| Git 分支 / HEAD | `llb_1013` / `ee1125412a181e4df13fbe32ea0242a18ab02622` |
| 工作区 | 109 项未提交改动（用户所有；本轮未整理、未提交、未推送） |
| 执行单元 | `unit-local-mac-02`；账号 `ID: 1807978499337419`（`media-a`） |
| 网络模式 | `local_development`（数据库不可变）；无代理、无线路证明 |
| 浏览器 | 真实 Google Chrome（`browser_executable_path` 固定）、非 headless、项目独立持久 profile |
| 契约 | `contracts/douyin_xingtu.verified.json`，`contract_version=xingtu-ad-creator-featured-v10`，8 模块 + 2 精选，`action_interval_seconds=2.0`、`operation_timeout_seconds=90`、`resume_supported=false`、`page_fetch_max_verified=2` |
| 服务 | Temporal 57233 / PostgreSQL 55432 / Redis 56379 / MinIO 59000 均在线；API 8000、前端 5173、intake worker、collection worker 在线 |
| 数据库迁移 | `applied=13`（含 `013_requirement_form_v2.sql`） |
| 测试样本 | 关键词「汽车」、`target_count=2`；产品前端**一次**提交；不重复提交 |
| 测试时间 | 2026-10-15 21:19–21:28（CST） |
| 本轮改动 | 仅新增 `request_census.py` + `runtime.py` 一处默认关闭挂载点 + `scripts/diag/manual_request_census.py` + 单元测试；**未改动采集主链路任何文件** |

### 测试限制（如实登记）

- 人工基线**已取得**（同一单元、同一 profile、同一账号、同两位达人；对照窗口对齐到"首次打开达人主页→结束"）。人工未逐字段核对数据完整性，故数据完整率列不构成人工侧对照值。
- 逐请求观测是本轮为诊断新增的能力；**历史运行没有逐请求记录**，因此历史任务的分类无法补做。
- 因执行单元为 `local_development`，本轮结论**不代表**生产线路形态。
- ISSUE-001 的最终根因仍待一次只读 DOM 确认（置信度中）。

---

## 第三部分：真实采集执行报告

### 执行时间线（任务 `381d628b`，全部为 UTC）

| 时间 | 事件 | 证据 |
|---|---|---|
| 13:26:11.07 | 产品前端提交，API 202 返回 `root_task_id` | UI 驱动捕获的 POST 正文与响应 |
| 13:26:15.29 | collection worker 打开浏览器上下文（普查 session 2 开始） | census header |
| 13:26:15.71 | 导航至 `/ad/creator/market`（bootstrap） | census document |
| 13:26:21–25 | P1 模型解析完成、任务进入 QUEUED→COLLECTING | `root_tasks.version` 演进 |
| 13:26:26.67 | 打开达人 1 主页 `douyin-video/7503176021160493065` | census document |
| 13:26:34.18 | 达人 1 精选重载同一主页 → `IDENTITY_MISMATCH` | census document + 快照 `failure_reason` |
| 13:26:50.98 | 打开达人 2 主页 `douyin-video/7282701602991898661` | census document |
| 13:27:04–13:27:51 | 约 47 秒低流量窗口（仅 5 条业务请求） | census 密度直方图 |
| 13:27:58.80 | 达人 2 精选重载同一主页 → `IDENTITY_MISMATCH` | census document + 快照 |
| 13:28:15.23 | 终态 `PARTIAL_COMPLETED`，浏览器关闭（普查 session 2 结束） | `root_tasks.completed_at` + census footer |

- **墙钟耗时 124 秒**，`active_seconds=119.76`。
- **零安全验证**（`challenge_count=0`）、**零失败计数**（`failure_counts={}`）、**零重扫**（`rescan_reasons=[]`）、**单次 Activity 执行**（无 30 秒定时器）。
- 这是一份**干净样本**：没有挑战、没有租约丢失、没有 30 秒重跑。

### 请求统计（分层口径）

| 层 | 口径定义 | 本轮实测 | 占比 |
|---|---|---|---|
| **L0 全部网络请求** | Context 级每一请求（含静态资源、埋点、iframe） | **2698** | 100% |
| L0-a 静态资源 | `script/stylesheet/font/media` 或未匹配命名的页面资源 | 1743 | 64.6% |
| L0-b 埋点/监控/安全 SDK | `mcs.zijieapi.com`、`mon.zijieapi.com`、`security.zijieapi.com`、`ibytedapm.com`、`secsdk*` | 183 | 6.8% |
| L0-c 平台 API（`xingtu.cn` 的 xhr/fetch） | 含**平台自身**发起的调用 | 542 | 20.1% |
| L0-d 未识别第三方 | 其它 xhr/fetch | 129 | 4.8% |
| L0-e 图片 | `image` 资源类型 | 72 | 2.7% |
| L0-f 页面文档 | `document`（= 导航数，含重定向与 iframe 文档） | 10 | 0.4% |
| **L1 已登记业务请求（"关联请求"）** | **命中已登记 `RequestSpec`（method+host+path+参数绑定）** | **49** | **1.8%** |
| L2 重复（计数器口径） | 同一操作内同 `spec.key` 再现 | **0** | — |
| L2′ 重复（跨操作，普查口径） | 同方法+同路径+同参数（`url_key` 相同） | **1966 条多余重复 / 551 组** | 72.9% 的请求属重复组 |
| L3 失败请求 | 有 `error` 的请求 | 63（47 无终态、10 `ERR_ABORTED`、6 `ERR_CONNECTION_CLOSED`） | 2.3% |
| L4 整段重执行 | Activity 执行次数 | **1**（无重跑） | — |

**L2 与 L2′ 的差距是本轮最重要的口径发现**：系统计数器报"重复请求 0"，而实际上有 1966 条完全重复请求未被计入。原因是 `duplicate_request_count` 只在**单个 `ResponseCollector` 实例内**计数（`observer.py:205` 每次操作新建 `self.seen`），跨操作/跨 Activity 的重复完全不反映。

### 页面导航

平台主页文档请求 5 次：1 次 bootstrap（`/ad/creator/market`）+ 达人 1 的 profile 与 featured 各 1 次 + 达人 2 的 profile 与 featured 各 1 次。另有 5 次第三方 `iframe-cookie-detect.html`（安全组件，非我们发起）。

每次平台整页加载平均带来 **约 270 条网络请求**（2698 / 10 个文档），其中约 **135 条**是同一 URL 的完全重复静态资源。

### 异常事件

- 无安全验证、无租约丢失、无 30 秒重跑、无失败计数。
- 63 条请求无终态/失败：47 条 `NO_TERMINAL_EVENT`（请求已发出但既无响应也无 `requestfailed`）、10 条 `net::ERR_ABORTED`、6 条 `net::ERR_CONNECTION_CLOSED`。
- `observed_responses=48 < observed_requests=49`：有一条已登记业务请求没有拿到响应。

### 数据库结果

| 项 | 实测 |
|---|---|
| 终态 | `PARTIAL_COMPLETED`，`failure_reason=PROFILE_SCOPE_INCOMPLETE` |
| 计数 | `target_count=2`、`discovered_count=20`、`valid_count=2`、`profile_complete_count=1`、`featured_complete_count=0`、`failed_count=2` |
| `task_creators` | 2 行，`valid=true`，各 1 个快照 |
| `creator_snapshots` | 2 行；每位达人 8 个模块**已采集**（如 `fans.monthly_connected_users=23454413` / `27066231`，`source_kind=response`） |
| `featured_collections` | **0 行** |
| `featured_cards` | **0 行** |
| `media_objects`（封面） | **0** |
| `allowed_actions` | `["retry"]` |

---

## 第四部分：八大维度分析

### 维度 1：请求行为

- **方法**：新增 Context 级普查（`request`/`response`/`requestfailed`），按"资源类型 × 主机归属 × 是否命中已登记规格"分类；与既有 checkpoint 计数器交叉校验。
- **实际结果**：见第三部分分层表。关键比值：**L1/L0 = 1.8%**；**重复静态资源占全部请求 49.9%**；平台 API 542 条中只有 49 条由我们的操作参数匹配命中，其余由**我们触发的页面加载**所引发。
- **发现的问题**：ISSUE-004（口径失真）、ISSUE-003（重复整页加载放大流量）。
- **证据**：`.runtime/diag01/census/auto-20261015T131920Z.jsonl`（session 2 = 2698 条）、`census-analysis.txt`、`final-metrics.txt`。
- **是否影响业务**：是（平台可见流量与风控暴露面成倍放大）。**是否需要优化**：是。

> **分类依据声明**：分类规则是机械的 —— 资源类型桶 + 主机后缀（`xingtu.cn` / 其它）+ 是否命中注册表路径。**未识别的第三方一律进 `unrecognised_third_party`，不做厂商级猜测**。注意：按"路径"匹配注册表会高估业务量（例如 `get_sign_image` 被平台自身调用 56 次），因此业务量以参数匹配的 L1（49）为准。

### 维度 2：访问路径

- **方法**：按普查时间轴重建"操作 → 页面状态"，并用 `url_key` HMAC 比对两次加载是否同一达人同一参数。
- **实际路径**：`/ad/creator/market`（bootstrap）→ 达人 1 主页 → 达人 1 主页**重载**（精选）→ 达人 2 主页 → 达人 2 主页**重载**（精选）→ 结束。
- **关键证据**：达人 1 的 profile 窗口有 41 个不同 `url_key`，其 featured 窗口 13 条请求的 `url_key` **全部**出现在 profile 窗口中（13/13）；达人 2 为 14/14；而达人 1 与达人 2 的 `url_key` **零重合**。
  → **精选重载加载的确实是同一位达人、同样的参数**，重载本身没有走错页面。
- **发现的问题**：同一达人主页被重复整页加载（ISSUE-003）；失败后**第二位精选集合从未被尝试**（`collect_featured_collections` 首个规格抛错即中断循环）。
- **是否影响业务**：是。**需要优化**：是。

### 维度 3：浏览器环境

- **方法**：`xingtu browser-check` 环境哈希、profile 文件与 Chrome 进程只读核对。
- **实际结果**：单一持久 Context；本轮 1 个 session；无意外重建；无 `PROFILE_IN_USE`；Chrome 正常启动与关闭（census header/footer 成对）。
- **发现的问题**：无浏览器环境类缺陷。**环境侧风险**：第二 checkout 与共享 DB 导致 `execution_units.profile_ref` 指向另一 checkout 的路径（ISSUE-010，审计隐患，不影响本轮运行）。
- **是否需要优化**：仅记录，不改绑定。

### 维度 4：交互过程与页面状态

- **方法**：把普查时间轴与 `module_seconds`、`failure_counts`、快照逐字段状态对齐。
- **实际结果**：8 个模块全部采集到真实值（`fans` 4.5s、`creation` 4.6s，其余 0.04–0.12s），说明**就绪判定与解析在 profile 阶段是有效的**；问题集中在**精选阶段重载后的身份判定**。
- **发现的问题**：ISSUE-001（重载后身份判定失败）、ISSUE-007（一次 abort/无终态即可让整段搜索失败）。
- **是否影响业务**：是。**需要优化**：是。

### 维度 5：Temporal 调度与异常恢复

- **方法**：只读拉取 `collect/<root>` 的全部 workflow run 与事件时间线（`wf-history-collect.json`），对照 `audit_logs`、`task_attempts`、`execution_units.generation`。
- **实际结果（本轮的干净运行）**：1 次 Activity 执行、无定时器、无重跑。
- **实际结果（同日用户运行 `50c8edf4`）**：**两个 segment 各有 2 次 `collect_segment_v1` 执行，中间各有一个 30 秒定时器**：
  - run `01a13e24…`：activity 0.15s → 92.5s 完成；`TimerStarted 30s`；122.5s 再次调度并启动；263.0s 完成并结束。
  - run `01a13f51…`：同型（0.04 → 92.5 → 30s 定时器 → 122.5 → 263.0）。
  - 该任务 `failure_counts={"LEASE_LOST":1,"SESSION_INDETERMINATE":1,"PLATFORM_SECURITY_CHALLENGE":1}`、`rescan_reasons=["CURSOR_INVALID"]`。
- **机制（已确认代码路径）**：`workflow.py:46–58` 的显式唤醒集合只含 `WAITING_FOR_LOGIN`/`WAITING_FOR_ACCOUNT`/`WAITING_FOR_VERIFICATION`/`PAUSED_BUDGET`；`engine.record_error` 把 `LEASE_LOST`/`SESSION_INDETERMINATE`/`RESOURCE_UNAVAILABLE` 映射为 `WAITING_FOR_RESOURCE`（`engine.py:756–759`），因此走 30 秒超时分支重跑整段。叠加 `resume_supported=false`（`adapter.py:793`）→ 每次重跑都清游标、重新 bootstrap、重新搜索、从第 1 页重扫。
- **发现的问题**：ISSUE-002。
- **复核历史 69–84ms**：`audit_logs` 中 5 组间隔 84/73/76/69/81 ms（2026-10-10 06:26:18–06:27:13 UTC）**完全可复现**，该旧机制已被 `ChallengeHandler` 取代；但见 ISSUE-005。
- **是否影响业务**：是（耗时 77s→263s，请求 31→62/达人）。**需要优化**：是，P0。

### 维度 6：网络与接口异常

- **方法**：`requestfailed` 事件 + 冻结计数器 + 失败证据工件。
- **实际结果**：本轮 63 条（2.3%）无终态或失败；`observed_responses(48) < observed_requests(49)`。
- **误配提交那次的完整因果链（同一普查文件中 session 1）**：一次逻辑搜索产生 **5 次 `POST /gw/api/gsearch/search_for_author_square`**，其中**第一次 `net::ERR_ABORTED`**；该次运行 30 秒内以 `PLATFORM_PAGE_CHANGED:SEARCH_RESPONSE_FAILED` 整段失败。
- **发现的问题**：ISSUE-007（一次中断放大为整段失败）、ISSUE-011（失败证据缺定位信息：`status_code=null`、`response_keys=[]`、`diagnostic={}`）。
- **诚实声明**：误配提交含一个**非预期筛选**（我的提交错误），该筛选可能加剧筛选交互与自动搜索次数，因此**不能单独归因**；置信度中。
- **是否影响业务**：是。**需要优化**：是。

### 维度 7：账号与会话生命周期- **方法**：`execution_units` 只读、`SessionHealth` 证据原因、Temporal 与 audit 时间线。
- **实际结果**：本轮 `session_version=9` 全程未变（无恢复、无会话失效）；`generation` 从 49 增至 51；终态 `browser_stopped=true`、无残留租约。
- **验证事件（同日用户运行，自然触发）**：14:00:04.967 检测 `PLATFORM_SECURITY_CHALLENGE` → 14:00:10.707 恢复，**间隔 5.740 秒**；worker 日志原文：
  `challenge declared clear: stable_window=5.162s observed_for=5.162s since_last_challenge_visible=None challenge_samples=0 clean_samples=20`
  → 等待期内**从未观测到挑战**（`challenge_samples=0`），因此按设计"未见挑战时不施加观测窗"，仅凭 5 秒稳定窗放行。恢复后采集继续并成功。
- **发现的问题**：ISSUE-005。**无法区分**两种解释：①挑战确实只是闪烁；②iframe 尚未重新渲染而系统已放行。**不作因果断言。**
- **是否影响业务**：可能（若为②，则是在挑战未解除时继续采集）。**需要优化**：是，建议加固判定。

#### 维度 7 补充：冷启动重定向已实机复现（排除了"登录态失效/执行单元选错"）

用户报告"打开的 Chrome 里星图不是登录状态"，要求排查是否选错执行单元。排查结论（全部有实测证据）：

| 检查 | 结果 |
|---|---|
| 当前执行单元 | `unit-local-mac-02`（数据库内**唯一**注册单元）；`expected_account_id=ID: 1807978499337419`；`network_mode=local_development` |
| 是否为之前可用单元 | **是**。`xingtu session-diagnostics` 在 2026-10-14 14:52 判定 `VALID`；本日自动化任务 `381d628b` 结束时单元记录 `last_session_status=VALID`（13:28:15 UTC）且成功采集 2 位达人资料 |
| 登录态是否失效 | **未失效**。本轮在同一 profile 上重新执行 `xingtu session-diagnostics`（2026-10-15T13:59:10Z）→ `status=VALID`、`observed_account_id=ID: 1807978499337419`（与 expected 相同）、`protected_page_verified=true`、`login_page_verified=false`、`challenge_verified=false`、快照在首个导航前恢复 |
| 那为什么窗口里"未登录" | **已登记的冷启动重定向**，不是登录态问题。实机复现（同一窗口、同一次观测）：尝试 1 导航 `/ad/creator/index` → 被 302 到 `https://www.xingtu.cn/?redirect_uri=/ad/creator/index`（与 `adapter.py` 注释记录的 `?redirect_uri=` 现象逐字一致）；尝试 2 先经登记的 SSO 入口交接、再导航 `/ad/creator/market` → **受保护业务页就绪** |
| 是否需要换单元 | **不需要**（数据库只有一个注册单元；且现有单元登录态有效）。修复方式是用采集适配器同款**有界冷启动**，而不是换单元 |

**旁证成本（并入 ISSUE-002/ISSUE-003）**：一次冷启动落地跨了 **3 次文档导航**（业务页→被重定向的公开首页→SSO 登录页→业务页成功）才就绪，即"首次导航必然浪费一整轮页面加载"。这为"每次 Activity 重跑都要重新 bootstrap"的放大量级再添一层证据。

**队列元数据不一致（ISSUE-010 的补充）**：数据库 `execution_units` 行的 `account_ref=xingtu-account-02`、`line_ref=local-dev-macos`、`profile_ref=…/予梦/01-定向爬取+定时更新/.runtime/profiles/unit-local-mac-02`，与本机配置文件的 `media-a` / `local-mac-02` / `…/YUMENG/.runtime/profiles/…` **全部不同** —— 该行由另一 checkout 写入，运行时不使用它（运行时用配置文件的 profile 路径），但因为绑定不可变，`register-unit` 无法纠正。不影响本次登录态判定。


### 维度 8：数据完整性与采集效率

| 指标 | 本轮实测 | 历史健康基线（`7620fb83`, target=1） |
|---|---|---|
| 终态 | `PARTIAL_COMPLETED` | `COMPLETED` |
| 有效达人 | 2 / 目标 2 | 1 / 目标 1 |
| 达人资料模块 | 8/8 已采集（2 位） | 8/8 `COLLECTED` |
| 资料完整 | 1 / 2 | 1 / 1 |
| **精选集合** | **0 / 4（全 NOT_ATTEMPTED）** | **2 / 2 COMPLETE** |
| 精选卡片 | 0 | 5 张全 `STORED` |
| 封面对象 | **0** | 5 |
| 业务请求（L1） | 49 | 45 |
| 全部网络请求（L0） | 2698 | 未记录（当时无此能力） |
| 重复业务请求（计数器） | 0 | 0 |
| 重复请求（跨操作，普查） | **1966** | 未记录 |
| 安全验证 | 0 | 0 |

- **有效采集效率** = 2 位有效达人 ÷ 124 秒 = **0.0161 位/秒（≈62 秒/位）**。
- **业务请求效率** = 2 位 ÷ 49 条业务请求 = **0.0408 位/条**。
- **全量请求效率** = 2 位 ÷ 2698 条 = **0.00074 位/条（≈1349 条/位）**。
- **发现的问题**：ISSUE-001（精选与封面全缺）、ISSUE-006（计数自相矛盾且 retry 整段重采）。
- **是否影响业务**：是（媒介人员拿不到精选作品与封面，必须人工介入）。**需要优化**：是，P0。

---

## 第五部分：人工与自动化对照

**人工基线已取得**：2026-10-15 22:02–22:07（CST），用户在同一执行单元 `unit-local-mac-02`、同一 profile、同一账号、同一浏览器上手工完成同一业务任务；普查与自动化使用**同一模块、同一口径、同一 HMAC 密钥**。

**可比性已验证**：人工访问的两位达人与自动化**完全一致** —— `douyin-video/7503176021160493065` 与 `douyin-video/7282701602991898661`（由 census `path` 逐字比对确认）。

**对照窗口已对齐**：双方都从"**第一次打开达人主页**"起算到各自会话结束，从而排除冷启动与搜索阶段的差异（人工 14:04:51→14:07:02，跨度 131s；自动化 13:26:26→13:28:15，跨度 109s）。

| 对照维度 | 人工操作 | 当前自动化 | 差异 | 是否异常 |
|---|---|---|---|---|
| 观测跨度 | 131 s | 109 s | 自动化反而更短（0.83×） | 否 |
| **总请求数（L0）** | **1519** | **2215** | **1.46×（自动化更多）** | **是（ISSUE-003）** |
| 每位达人均摊 | 760 | 1108 | 1.46× | 是 |
| 静态资源 | 822（54.1%） | 1430（64.6%） | **1.74×** | **是（ISSUE-003）** |
| 平台域请求（`xingtu.cn`） | 412 | 459 | 1.11× | 否（接近） |
| 平台 API 请求 | 370 | 447 | 1.21× | 否（接近） |
| 图片请求 | 68 | 63 | 0.93× | 否 |
| **完全重复请求（多余条数）** | **751** | **1548** | **2.06×** | **是（ISSUE-003）** |
| 其中静态资源重复 | 397 | 1063 | **2.68×** | **是（ISSUE-003）** |
| 页面导航（文档请求） | 4 | 8 | 2.00× | 是 |
| **达人主页整页加载次数** | **2（每位 1.0 次）** | **4（每位 2.0 次）** | **2.00×** | **是（ISSUE-003）** |
| 失败/无终态请求 | 70 | 62 | 0.89× | 否（自动化并未更多失败） |
| 请求失败率 | 4.6% | 2.8% | 自动化更低 | 否 |
| 单达人耗时 | ≈66 s | ≈55 s | 自动化更快 | 否 |
| 数据完整率（模块） | 未逐字段核对（人工只浏览） | 8/8 模块已采集、精选 0/4（ISSUE-001） | — | 是（ISSUE-001） |

### 对照结论（直接回答核心问题）

1. **自动化确实存在人工操作中没有的多余请求**：同一任务、同两位达人、**更短的时间内**多发 **1.46 倍**总请求；多出来的部分集中在**静态资源（1.74×）与完全重复请求（2.06×）**。
2. **差异的机制已被定位且可解释**：**人工对每位达人主页只整页加载 1 次；自动化整页加载 2 次**（本次因精选提前失败只加载 2 次；若精选正常完成将达到 **3 次**：1 次资料 + 2 次精选重载）。每一次整页加载都会重新拉取同一批 SPA 资源，因此重复数成倍增长。
3. **业务 API 调用量与人工接近**（1.21×），说明自动化多出来的**不是业务请求**，而是**页面加载开销**。
4. **失败与重试不是本次差异的来源**：人工的失败/无终态请求（70）反而**多于**自动化（62），即"自动化因重试而多请求"在此样本中不成立。
5. **属于正常自动化实现、不应视为缺陷的差异**：脚本化操作更快（跨度更短、单达人更快）、失败率更低（自动化有明确的会话校验与错误分类）、图像请求量相当。
6. **属于需要修复的工程缺陷的差异**：① 同一达人主页重复整页加载（ISSUE-003）；② 精选集合整段未采集（ISSUE-001）；③ 请求量口径不可见（ISSUE-004，对照本身必须先靠新普查才能做出来）。

> **诚实说明**：本次人工基线由脚本先做了一次**有界冷启动**（为把浏览器可靠落到已登录业务页），该段流量已通过时间窗**排除**在对照之外；人工段内的搜索、打开主页、逐模块阅读均为用户真实操作。人工并未逐字段核对数据完整性，故数据完整率列不构成人工侧的对照值。


---

## 第六部分：问题清单

| 编号 | 问题 | 业务影响 | 严重程度 | 证据 | 置信度 |
|---|---|---|---|---|---|
| **ISSUE-001** | 精选集合重载后身份判定 `IDENTITY_MISMATCH`（`CREATOR_INVALID`），两位达人 4 组精选全部 `NOT_ATTEMPTED`，`featured_collections` 0 行、封面 0 个 | 媒介人员拿不到精选作品与封面；任务显示"部分完成"却无法从状态看出精选整段未采 | **P0** | **根因已确认**：重载后 `div.author-info span.copy-text` 有约 45–60 ms 只渲染空文本、且 `read_locator` 接受空串 → `'' != creator_id`；只读探针 2/2 复现（`+375ms`/`+315ms` 读到 `''`）；`adapter.py` `read_locator`+`verify_identity`；`url_key` 13/13、14/14 证明加载的是同一达人 | **高** |
| **ISSUE-002** | `WAITING_FOR_RESOURCE`/`RETRY_WAIT` 不在 workflow 显式唤醒集合 → 每 30 秒重跑整段 Activity（重启 Chrome、重新 bootstrap、重新搜索、清游标重扫第 1 页） | 单达人耗时 77s→263s、请求 ~31→62；同一任务反复启动真实 Chrome 与整页访问，是"自动化比人工更频繁访问"的主要结构性放大源 | **P0** | Temporal history：两个 run 各 2 次 Activity + 各 1 个 30s `TimerStarted`；`workflow.py:46–58`、`engine.py:756–759`、`adapter.py:793`；`failure_counts` 含 `LEASE_LOST`/`SESSION_INDETERMINATE` | **高** |
| **ISSUE-003** | 同一达人主页被重复整页加载（正常完成路径每达人 3 次：1 次 profile + 2 次 featured；本轮因精选早退为 2 次） | 每次整页加载约 270 条网络请求，耗时与风控暴露面成倍放大 | **P1** | `reload_homepage=true`（注册表两个精选规格）；census 5 次主页文档；`Navigation` 计数 5；每条主页加载约 270 条请求、其中约 135 条重复静态资源 | **高** |
| **ISSUE-004** | "关联请求"口径仅覆盖命中登记规格的请求；`duplicate_request_count` 只统计单操作内重复；跨操作重复完全不反映 | 团队据"重复请求 0 / 降幅 50%"做的结论不可靠；任何优化收益无法度量 | **P1** | 同一 30 秒失败运行：计数器 0 vs census 542；本轮计数器 0 vs census 1966 条跨操作重复；`domain.py:956`、`observer.py:205/268` | **高** |
| **ISSUE-005** | 挑战"稳定窗口"在等待期内从未观测到挑战时即生效，15 秒观测窗被绕过 | 可能在挑战仍未解除时继续采集，导致后续请求被风控放大 | **P1** | worker 日志 `challenge_samples=0 ... observed_for=5.162s`；audit 检测→放行 5.740s；`challenge.py:246–250` | **高**（现象）/ **中**（后果） |
| **ISSUE-006** | 同一任务同时显示"有效入库 2"与"失败步骤 2"（同一批达人），且 `allowed_actions=["retry"]`；retry 会对已成功达人整段重采 | 媒介人员看到自相矛盾计数；一次 retry 使该达人请求从 ~31 增至 62（实测 `50c8edf4`） | **P1** | API `valid_count=2` 与 `failed_count=2` 并存；`engine.py` `_collect_once` 在 `CREATOR_INVALID` 时置 `state=failed` 且保留 `valid=True`；`50c8edf4` 的 62 请求 vs 健康基线 ≈31 | **高** |
| **ISSUE-007** | 一次被中断/交错的请求即可让整段搜索失败（5 次搜索 POST 中第 1 次 `ERR_ABORTED` → `SEARCH_RESPONSE_FAILED`）；本轮另有 63 条请求无终态、`responses < requests` | 网络抖动即导致整段任务失败或重跑，成功率与耗时不可预测 | **P1** | census session 1 搜索 POST 时间线与首次 abort；`PLATFORM_PAGE_CHANGED:SEARCH_RESPONSE_FAILED`；`observer.py` required+failed 判定 | **中高** |
| **ISSUE-008** | 所有 failure/summary 证据固定标记 `network_mode: production_line`，即使执行单元为 `local_development` | 审计/证据溯源失真，可能被误认为走过生产线路 | **P2** | 两份证据 `network_mode=production_line` + DB 单元 `local_development`；`evidence.py:28` 默认值从未被 `engine.py:107` 覆盖 | **高** |
| **ISSUE-009** | 诊断指标不可独立使用：`navigation_count` 少计（仅 `BrowserAdapter.navigate`）、`cover_request_count=0` 而 census 中封面 CDN 72 条、`featured_load_count` 与真实加载次数不符 | 运维/产品据此判断"有没有访问平台"会误判 | **P2** | census 文档数 10 vs `navigation_count=5`；`cover_request_count=0` vs census image 72 | **中高** |
| **ISSUE-010** | 第二 checkout 与共享数据库导致 `execution_units.profile_ref` 指向另一 checkout 的 profile 路径；`register-unit` 因绑定不可变会拒绝纠正 | 隔离与审计判断隐患；换环境时可能启动错误的 profile | **P2** | DB `profile_ref=/Users/yaoyao/…/01-定向爬取+定时更新/.runtime/profiles/…` vs 本机配置路径；`repository.py:276–295` | **高** |
| **ISSUE-011** | 失败证据缺少可定位信息（`status_code=null`、`response_keys=[]`、`diagnostic={}`） | 失败后无法从证据判断是哪个请求、什么状态，只能靠人工复现 | **P2** | `.runtime/evidence/failure/fc5fb419…/*.json`、`50c8edf4…/*.json` | **高** |

---

## 第七部分：原因分析

### ISSUE-001

- **已确认原因（2026-10-15 只读 DOM 探针，2/2 达人复现）**：精选路径在重载同一达人主页后调用 `verify_identity`，此时平台 SPA 正在 hydration，`div.author-info span.copy-text` 会有**数十毫秒的窗口只渲染出一个空文本节点**。因为该元素**存在且唯一**（`count()==1`），`read_locator` 的位置检查通过；而它只拒绝 `value is None`，**空字符串被当作一次成功的读取**返回；`verify_identity` 随即把 `''` 与 `creator.platform_creator_id` 比较，必然不等 → 抛 `CREATOR_INVALID: IDENTITY_MISMATCH`。
  - 探针原始时间线（达人 1）：重载后 `+0ms` → `div.author-info` 计数 0（此时若被读到会是 `IDENTITY_UNREADABLE`）；`+375ms` → `div.author-info` 计数 1、`span.copy-text` 计数 **1**、文本 **`''`** → 判定 **MISMATCH**；`+435ms` → 文本恢复为 `7503176021160493065`。达人 2：`+315ms` 为空、`+360ms` 恢复为 `7282701602991898661`。
  - 该空窗约 45–60 ms 宽；`check_session` 依赖**账号定位符**返回，而账号定位符与这个空的身份节点在 hydration 中几乎同时出现，因此 `check_session` 返回后紧接着的身份读取正好落进空窗 —— 这解释了为什么两位达人**稳定复现**而不是偶发。
  - 代码依据：[adapter.py](backend/src/xingtu/adapter.py) `read_locator` 仅以 `count()!=1` 与 `value is None` 作为失败条件（空串通过），`verify_identity` 直接做不等比较抛出 `CREATOR_INVALID: IDENTITY_MISMATCH`。
- **次生后果（同一条因果链）**：`collect_featured_collections` 对非 `MODULE_COLLECTION_FAILED` 的异常直接上抛，因此**第二个精选集合也不会被尝试**；且**没有任何 `FeaturedCollectionObservation` 落库** → `featured_collections` 0 行、`featured_cards` 0 行、封面 0 个、`cover_request_count=0`、`featured_status=NOT_ATTEMPTED`；`_collect_once` 捕获 `CREATOR_INVALID` 后保留 `valid=True` 并把 `state` 置 `failed`，于是任务同时显示"有效入库 2"与"失败步骤 2"（ISSUE-006）。
- **为什么资料阶段（profile）不失败**：同一份代码在资料阶段也在 `check_session` 后立刻读身份，但资料阶段是从业务页进入、应用外壳已预热，身份文本早于 `check_session` 返回即已填充，因此这条竞态在资料阶段被赢下、在精选重载阶段被输掉。
- **证据不足之处**：探针通过 CDP 逐次读取，采样间隔受往返延迟影响，故空窗宽度只能给"数十毫秒"量级，不是精确值；空窗的**存在性**与**空串被接受**这一机制已被直接观测与代码双重确认。
- **与验证事件的关联**：**无关联**（本轮零验证；该缺陷与风控无关）。


### ISSUE-002

- **已确认原因**：`WAITING_FOR_RESOURCE`（由 `LEASE_LOST`/`SESSION_INDETERMINATE`/`RESOURCE_UNAVAILABLE` 映射）与 `RETRY_WAIT` 不在 workflow 的显式唤醒集合中，落到 30 秒 `wait_condition` 超时分支后重新 `execute_activity`，从而重启整段。
- **上游原因**：`resume_supported=false` 使"重跑"无法复用游标——`prepare()` 在 `cursor` 非空时直接返回 False，触发 `rescan()` 清游标，并重新执行 `_bootstrap_session`（最多 4 次业务页 + 2 次 SSO 导航）与整段搜索。
- **是否与异常请求相关**：是，且是**最大量级的自我放大**：每次重跑新增约 1 次 bootstrap + 1 次搜索 + 1 次整页加载（≈270 条网络请求）。
- **与验证事件关联**：时间上相关（`50c8edf4` 的 `SESSION_INDETERMINATE` 与挑战同任务），但**不构成因果**。

### ISSUE-004

- **已确认原因**：计数器的设计口径就是"命中已登记操作关联的请求"，而非全量流量；且重复计数的作用域是单个 `ResponseCollector` 实例。
- **上游原因**：该口径在早期用于回答"我们发了多少次业务请求"，当时没有全量观测能力；后来被当作"请求量/重复量"的通用指标引用（包括 `CHALLENGE-01` 的"重复请求下降 ≥50%"验收项与历史"重复请求 0"结论）。
- **与验证事件关联**：**间接**——无法用现有指标判断"验证前的请求是否异常"，这正是历史上"159"数字无法复核的根因。

### ISSUE-005

- **已确认原因**：`wait_for_stable_session` 只在**本轮等待中确实观测到挑战**（`challenge_seen_this_wait`）时才施加 15 秒观测窗；检测与等待之间隔着 `enter_maintenance`、`detach_page`、`register` 与一次新的 `check_session`，等到真正轮询时挑战 iframe 常常已不可见，于是只按 5 秒稳定窗放行（实测 `observed_for=5.162s`、`challenge_samples=0`）。
- **可能原因（未确认）**：① 检测到的是短暂闪烁；② iframe 卸载/尚未重新渲染。两者与现场数据都相容。
- **证据不足之处**：缺少等待期内挑战 iframe 的出现/消失时间序列（`challenge_samples=0` 只说明轮询时不可见）。
- **与验证事件的关联**：**直接相关**（这就是验证事件本身），但**不能据此断言平台风控规则**。

### ISSUE-006

- **已确认原因**：`_collect_once` 的 `CREATOR_INVALID` 分支保留 `c.valid` 只把 `state` 改为 `failed`，因此同一达人同时满足"有效"与"失败"两个统计；`retry` 只按"未完成"重采，不区分"资料已成功、仅精选缺失"。
- **与验证事件的关联**：无。

### ISSUE-007

- **已确认原因**：搜索操作把"必需请求出现失败/未关联"直接判为 `SEARCH_RESPONSE_FAILED`；而一次页面交互会触发多次自动搜索（筛选交互、点击搜索按钮、平台自身重发），其中任何一次被 abort 即污染判定。
- **可能原因**：误配提交中的非预期筛选放大了筛选交互与搜索次数（5 次 POST），因此该次失败**不能单独归因于代码**。
- **与验证事件的关联**：无直接关联。

### ISSUE-008 / 009 / 010 / 011

均为**已确认的工程与可观测性缺陷**，无业务逻辑风险，但与验证事件无关。

---

## 第八部分：产品优化方案

| 优先级 | 当前问题 | 产品影响 | 优化方案 | 预期收益 | 风险 |
|---|---|---|---|---|---|
| **P0** | ISSUE-001 精选整段未采集（**根因已确认**：重载后身份元素有约 45–60 ms 空文本窗口，而空串被 `read_locator` 当作成功读取） | 媒介人员拿不到精选作品与封面，需人工介入重采 | 产品层：任务详情把"精选集合未采集"与"资料字段缺失"分开提示；异常需明确显示"精选本次未采集"并给出可重试入口。技术层：① `read_locator` 把**空白值**与 `None` 同等视为不可读；② `verify_identity` 的身份读取做**有界等待**（等到非空且稳定，超时按 `IDENTITY_UNREADABLE` 收口）；③ 单个精选失败不得阻止第二个精选尝试，失败也需落 `featured_collections` 记录 | 精选完整率从 0/4 恢复到历史基线 2/2；消除"无法从状态看出精选缺失"的问题 | 只动身份读取的失败判定与精选错误处理；不改契约、不改 profile 路径、不放宽任何既有断言；需新增离线用例覆盖"空文本瞬态" |
| **P0** | ISSUE-002 每 30 秒整段重跑 | 耗时 77s→263s、请求近翻倍、反复启动真实 Chrome | 技术层：为 `WAITING_FOR_RESOURCE`/`RETRY_WAIT` 引入**有界退避**（如指数退避 + 上限）与**显式唤醒**语义，避免无上限 30 秒重跑；产品层：等待态需向用户展示"等待资源/退避中（第 N 次）"与剩余次数 | 单达人耗时回到 ~77s 量级；单达人业务请求减少约 50% | 改 workflow 需验证历史重放（`patched` 保护）；不改重试上限语义需与既有 `maximum_attempts=4` 协调 |
| **P1** | ISSUE-003 主页重复整页加载 | 每次整页加载约 270 条请求，流量与耗时成倍放大 | 技术层：让**同一达人的第二次精选复用已加载页面**（注册表 `reload_homepage` 与"是否需要重载"解耦），或在两次精选间**只做一次重载**；保持契约不变，仅调整复用判定 | 每达人减少 1–2 次整页加载，网络请求显著下降（量级：每次约 270 条） | 需证明复用不改变精选结果（同一 `set_key`/指纹判定）；不得放宽数据完整性 |
| **P1** | ISSUE-004 请求口径失真 | 团队据错误数字判断成本与降幅 | 技术层：把"跨操作/跨 Activity 重复"作为**新增指标**记录（不改既有 `duplicate_request_count` 语义，避免追溯改写历史结论）；产品层：任务详情/运维视图区分"业务请求"与"总流量" | 使"重复请求下降 ≥50%"首次可度量 | 新增计数需落 checkpoint（带默认值，兼容旧数据） |
| **P1** | ISSUE-005 挑战过早放行 | 可能在挑战未解除时继续采集 | 技术层：把"检测到挑战"这一事实传入等待期，使 15 秒观测窗**在检测后的等待中始终生效**（而不依赖等待期是否再次看到 iframe）；产品层：恢复时展示"稳定确认耗时"与观测样本数 | 挑战恢复证据可闭合 DF-07/CHALLENGE-01 待验收项 | 会让每次真实恢复至少多等约 10 秒；需实测确认不引入假阴性 |
| **P1** | ISSUE-006 计数矛盾与 retry 整段重采 | 计数自相矛盾；retry 重复整段访问 | 产品层：区分"资料完成"与"精选完成"两个状态与两个重试入口；技术层：retry 支持**只补缺失步骤**（复用已成功模块与已存封面） | 消除矛盾计数；retry 请求量下降（实测 retry 使单人请求 31→62） | 状态机与前端联动改动，需回归 |
| **P1** | ISSUE-007 单次中断放大为整段失败 | 成功率与耗时不可预测 | 技术层：区分"必需请求被 abort"与"平台返回不可关联"，前者按**有界重试**而非整段失败；必要时对同一逻辑搜索的重复请求做窗口内归并 | 降低偶发网络抖动导致的任务失败 | 不得放宽"响应必须能关联"的严格性，避免误收 |
| **P2** | ISSUE-008 证据网络模式标注错误 | 审计溯源失真 | 技术层：`Engine.record_evidence` 传入 `ctx.network_mode` | 证据可信 | 极小 |
| **P2** | ISSUE-009 诊断指标不准 | 运维误判 | 技术层：导航计数覆盖 host 层 goto；`cover_request_count` 与实际封面请求对齐；或在文档明确其口径 | 指标可独立使用 | 极小 |
| **P2** | ISSUE-010 环境绑定不一致 | 隔离审计隐患 | 环境层：单独评估改绑/重建单元方案（本轮只记录） | 消除隐患 | 改绑是显式审计操作，需单独授权 |
| **P2** | ISSUE-011 失败证据缺定位信息 | 排障靠人工复现 | 技术层：为 `SEARCH_RESPONSE_FAILED` 附上被拒请求的 `request_key`/状态/内容类型 | 排障效率提升 | 极小 |

---

## 第九部分：推荐实施顺序（MVP）

1. **修 ISSUE-001**（P0，交付正确性）：让精选集合真正采到，且单个精选失败不阻断另一个。
2. **修 ISSUE-002**（P0，流量/耗时结构性放大）：有界退避 + 显式唤醒，消除无上限 30 秒整段重跑。
3. **降低重复整页加载**（ISSUE-003）：同一达人的精选复用已加载页面。
4. **补口径指标**（ISSUE-004）：新增跨操作重复计数与"业务请求/总流量"两个视图，使降幅可度量。
5. **加固挑战放行判定**（ISSUE-005）：检测事实贯穿等待期。
6. **修状态与重试语义**（ISSUE-006）+ **网络中断分类**（ISSUE-007）。
7. **可观测性与环境**（ISSUE-008/009/010/011）。

**不做**：在缺少证据时大规模重构；不为降低请求数而放宽数据完整性断言；不绕过任何平台安全机制。

---

## 第十部分：待我确认的问题

### 已确认（本轮据此执行）

1. ✅ 真实采集 target=2 / 关键词「汽车」/ 仅提交一次 — 2026-10-15
2. ✅ 产品前端真实提交 — 2026-10-15
3. ✅ 授权新增默认关闭的请求普查钩子 — 2026-10-15
4. ✅ 做人工基线 — 2026-10-15
5. ✅ 应用迁移 013 + 重启 API 与两个 worker — 2026-10-15

### D01 — ISSUE-001 根因已确认，请确认修复方向（**建议优先，且仍未改代码**）

1. **当前已知事实**：精选重载后 `div.author-info span.copy-text` 有约 45–60 ms 只渲染空文本的窗口，且 `read_locator` 把空串当作成功读取 → `verify_identity` 比较 `'' != creator_id` → `CREATOR_INVALID: IDENTITY_MISMATCH` → 整个精选步骤（两组）中止且零落库。只读探针 2/2 达人复现。
2. **不确定的地方**：空窗精确宽度；以及平台在该窗口后是否会再次出现同类瞬态（例如文本短暂为账号 ID）。
3. **可选方案**：
   - **A（推荐，最小且对症）**：`read_locator` 增加"空白值视为不可读"的判定（把 `value.strip()` 为空与 `value is None` 同等处理），并在 `verify_identity` 处对身份读取做**有界等待**（等到非空且稳定，超时仍按 `IDENTITY_UNREADABLE` 收口，不放宽任何断言）。
   - B：仅给 `verify_identity` 加重试（不改 `read_locator` 语义）。改动更小，但把"空串是可读值"的错误语义留在 `read_locator`，其他调用方仍可能受影响。
   - C：让 `collect_featured_collections` 在首个精选失败时仍继续尝试第二个精选并落库失败记录（修"次生后果"，不修根因）。可作为 A 的补充，不能单独使用。
4. **推荐方案**：**A + C 组合**（先修"空串被当读成功"这一根因，再修"一个精选失败阻断另一个且零落库"这一放大）。两者都属最小改动，不触碰契约、注册表、调度与会话逻辑。
5. **推荐理由**：A 使失败模式从"误判为身份不符并整段中止"回到正确的"读不到就按不可读收口"，且不会放宽既有严格性；C 保证任一精选失败不再连带丢弃另一个，并让数据可审计。
6. **需确认**：是否按 A + C 实施；是否同意"不影响既有断言、只把空/空白值归入不可读"。


### D02 — ISSUE-002 的修复取向

1. **当前已知事实**：`WAITING_FOR_RESOURCE`/`RETRY_WAIT` 触发 30 秒整段重跑；`resume_supported=false` 使重跑必然重扫。
2. **不确定的地方**：是"缩短/退避重跑"还是"把等待态也纳入显式唤醒（等用户/等资源就绪信号）"。
3. **可选方案**：A 有界指数退避 + 上限 + 显式唤醒（改动集中在 `workflow.py`，`patched` 保护历史重放）；B 仅把 `WAITING_FOR_RESOURCE` 加入显式唤醒集合（改动最小，但等待可能长时间不推进）；C 打开契约的 `resume_supported`（收益最大，但需契约重新核验，风险最高）。
4. **推荐方案**：**A**（本轮之后单独排期），并把 C 作为独立课题。
5. **推荐理由**：A 用最小改动消除无上限放大，且不需要重新核验平台契约。
6. **需确认**：取向与是否接受"等待态不再自动 30 秒重试"。

### D03 — ISSUE-004 的指标口径是否新增而非改写

1. **当前已知事实**：`duplicate_request_count` 语义窄；历史验收结论（"重复请求 0"、CHALLENGE-01 的"下降 ≥50%"）引用了它。
2. **不确定的地方**：是否允许修正既有字段语义。
3. **可选方案**：A 只**新增**跨操作重复指标，保留旧字段语义并在文档标注其口径（不追溯改写历史结论）；B 同时修正旧字段并回填说明。
4. **推荐方案**：**A**。
5. **推荐理由**：不改写历史证据，避免影响 CHALLENGE-01 的待验收结论。
6. **需确认**：是否同意 A。

### D04 — ISSUE-006 的 retry 语义

1. **当前已知事实**：retry 会对已成功达人整段重采（实测请求 31→62），且同一达人同时计入"有效"与"失败"。
2. **不确定的地方**：是"只补缺失步骤"还是"保持整段重采但在 UI 明确说明代价"。
3. **可选方案**：A 只补缺失步骤（复用已成功模块与已存封面）；B 维持现状 + UI 明示。
4. **推荐方案**：**A**（与既有"重试只补采缺失模块"的产品文案一致）。
5. **推荐理由**：避免为补 2 组精选而重采 8 个模块。
6. **需确认**：是否同意 A。

### D05 — 人工基线

1. **当前已知事实**：观测窗口已启动但尚无记录；脚本与清单已就绪。
2. **不确定的地方**：你是否能在此窗口内完成，或需要我重新开启一次更长的窗口。
3. **可选方案**：A 你完成当前窗口（同关键词「汽车」、结果前 2 位达人、8 模块 + 2 组精选）；B 我重新开启一个更长窗口；C 本轮不做，对照表保持"未验证"。
4. **推荐方案**：**A**（若窗口已过则 B）。
5. **推荐理由**：这是唯一能回答"人工 vs 自动化差异"的证据来源。
6. **需确认**：你何时方便；完成后请告知，我会自动收集并补全第五部分。

### D06 — 第二轮真实采集的规模

1. **当前已知事实**：本轮 target=2 已产生 2698 条网络请求；修复后需要一次可比复测来量化降幅。
2. **不确定的地方**：复测是否仍用 target=2、同关键词。
3. **可选方案**：A 同参数复测（唯一可比的方案）；B 用 target=1 降低暴露。
4. **推荐方案**：**A**（修复后、另行授权）。
5. **推荐理由**：只有同参数才可比；target=1 与 target=2 的请求构成不同。
6. **需确认**：是否同意修复后按同参数复测一次。
