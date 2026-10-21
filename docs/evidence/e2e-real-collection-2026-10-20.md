# 巨量星图真实采集端到端验收报告（宠物 / 10 位）

- 测试日期：2026-10-20（UTC+08，核心窗口 21:46–22:17）
- 测试地址：<https://xingtu.yumeng.live>
- 测试性质：正式部署环境真实采集端到端验收（独立 QA）
- 核心任务：`11f9fc9c-ad06-4d41-9fde-c33bab168f47`（关键词 `宠物`，目标 `10`）
- 执行单元：`unit-local-mac-02` / `LOCAL_DEVELOPMENT` / Mac 当前 WiFi
- 浏览器：系统 Chrome 155.0.8059.85（Playwright MCP + 项目 Chrome）
- 最终结论：**NO-GO**

> 本轮 P1 DeepSeek 转换成功、真实 Chrome 启动并访问巨量星图、真实数据写入 PostgreSQL/MinIO；但 P2 采集在人工滑块验证后发生连续 heartbeat timeout，Workflow 失败而产品任务仍停在 `COLLECTING`，最终仅 2/10 位有效达人、1 份已发布快照，未形成 10 位完整结果。

---

## 1. 测试执行汇总

### 1.1 59 项历史用例本轮结果

| 模块 | 用例 | 本轮结果 | 说明 |
|---|---|---|---|
| S01 站点/HTTPS | SMK-01、02、03、04、06 | **PASS** | HTTPS、TLS、HTTP/2、静态资源、深链、直连均正常 |
| S01 | SMK-05 | **FAIL** | `http://` 3/3 被腾讯云 DNSPod 备案页拦截 |
| S02 登录/会话 | SMK-07—SMK-13 | **PASS**（7/7） | 未登录保护、错误密码、登录、刷新、Cookie、登出、重新登录 |
| S03 核心页面 | SMK-14—SMK-21 | **PASS**（8/8） | 任务中心、任务详情、创建任务、达人库、达人详情、执行单元、账号菜单、404 |
| S04 达人数据 | SMK-22 | **PASS** | 达人库显示本轮真实采集的“一只平安喵” |
| S04 | SMK-23 | **FAIL** | 详情字段可显示，但精选 `NOT_ATTEMPTED`、封面/作品未形成；第二位无快照 |
| S04 | SMK-24 | **PASS** | 空值/空态语义在达人库/详情可见 |
| S05 执行单元 | SMK-25、26、27、28 | **PASS** | 字段完整、API/DB 一致、Worker 在线≠可用、无伪造线路 |
| S05 | SMK-29 | **NOT TESTED** | 断线/恢复故障注入未执行 |
| S05 | SMK-30 | **PASS（本机）** | F10 本机原浏览器接管可用；远程 noVNC 另见 E2E-02 |
| S06 任务创建 | SMK-31、32、33、34 | **PASS** | 真实前端提交、P1 模型成功、任务进入 P2；校验有效 |
| S06 | SMK-35 | **FAIL** | Workflow 已 FAILED，产品任务仍显示采集中，失败态未收口 |
| S07 异步服务 | SMK-36—SMK-41 | **PASS**（6/6） | Intake/Mac poller、Temporal、DB、MinIO、容器状态、无重复派发 |
| S08 安全 | SMK-42—SMK-46 | **PASS**（5/5） | 401、CSRF/Origin、CORS、WS 拒绝、无敏感泄露 |
| S08 | SMK-47 | **FAIL** | 缺 HSTS/CSP/X-Frame-Options/X-Content-Type-Options/Referrer-Policy |
| S09 部署迁移 | SMK-48—SMK-53、SMK-55、SMK-56 | **PASS**（8/8） | 同源 API、Secure Cookie、SPA 刷新、WS 路由、Mac 状态、对象存储、容器、launchd |
| S09 | SMK-54 | **FAIL** | 部署产物未入库，后端运行版本仍靠源文件哈希追溯 |
| S10 故障恢复 | SMK-58 | **PASS** | 无活动租约；代次/租约状态可读 |
| S10 | SMK-57、SMK-59 | **NOT TESTED** | 破坏性断线/网络/Profile 锁注入未执行 |

**统计**

| 结果 | 上轮 | 本轮 |
|---|---|---|
| PASS | 45 | **51** |
| FAIL | 4 | **5** |
| BLOCKED | 6 | **0** |
| NOT TESTED | 3 | **3** |
| NOT APPLICABLE | 1 | **0** |
| 合计 | 59 | 59 |

> 本轮数据类 BLOCKED 已解除（达人库/详情有真实数据），但 S04-23、S06-35 转为 FAIL；HTTP 80、安全头、部署可追溯性仍未解决。
> 说明：S01/S02/S03/S05/S06/S07/S08/S09 的关键路径本轮重新执行；SMK-24 等纯空态/边界用例未重复触发，沿用上一轮证据；破坏性故障注入未执行。

### 1.2 新增真实 E2E 用例

| ID | 场景 | 结果 | 说明 |
|---|---|---|---|
| E2E-01 | 前端提交 `宠物/10`，P1 DeepSeek 真实转换 | **PASS** | model_run 16073/88 tokens，1043ms，FilterPlan 正确 |
| E2E-02 | P2 任务派发、Mac Worker、Chrome 启动 | **PASS**（部分） | `task_dispatches.sent=true`，项目 Chrome 真实启动 |
| E2E-03 | 巨量星图滑块/F10 人工验证 | **CONDITIONAL PASS** | 本机人工滑块成功，challenge RESOLVED；远程 noVNC 不可用 |
| E2E-04 | 真实采集执行到目标 10 位 | **FAIL** | 仅 2 位有效、1 份快照；Workflow 失败 |
| E2E-05 | 结果持久化到 PostgreSQL/MinIO | **PARTIAL** | 34 个封面对象、1 份快照；0 精选集合、第二位无快照 |
| E2E-06 | 采集结果符合 `宠物` 筛选 | **UNCONFIRMED** | 第一位宠物相关；第二位标签为生活/食品饮料/汽车/3C，但其 ID 是搜索候选 first_position=1，不能仅凭标签判定筛选失败 |
| E2E-07 | 任务最终状态与 Temporal/DB 一致 | **FAIL** | Workflow FAILED，root_task 仍 COLLECTING，无 failure_reason |
| E2E-08 | 前端正确展示进度与结果 | **PARTIAL** | 显示 2/10、2 位草稿、1 位已发布快照；但任务永远“采集中” |
| E2E-09 | 不绕过验证、不伪造 NetworkProof | **PASS** | 人工完成滑块；单元仍 `LOCAL_DEVELOPMENT`，无 NetworkProof |
| E2E-10 | 不重复创建真实任务 | **PASS** | 本轮仅 1 个真实采集任务；未删除历史数据 |

---

## 2. 核心端到端证据

### 2.1 P1 转换与任务创建

| 项目 | 实测 |
|---|---|
| 入口 | 前端 `/tasks/new`，关键词 `宠物`，目标 `10` |
| 任务 ID | `11f9fc9c-ad06-4d41-9fde-c33bab168f47` |
| Intake Workflow | `ProcessProductIntakeV1` **COMPLETED**（13:46:09→13:46:10Z） |
| model_run | `1121cbde-ac7e-47db-9494-66d0ae3406fb`，`deepseek-flash`，**succeeded**，16073 input / 88 output，1043ms，`error_payload=NULL` |
| FilterPlan | `source=model`，keyword=`宠物`，target=10，`validation_errors=[]` |
| 前端截图 | [创建任务页](e2e-real-collection-2026-10-20/e2e-01-form.png) |

### 2.2 P2 派发与 Chrome

- `task_dispatches.sent=true`，`workflow_started_at=2026-10-20T13:46:10.863Z`。
- Mac Worker 项目 Chrome 真实启动，命令行含：
  `--user-data-dir=/Users/Longbo/Developer/YUMENG/.runtime/profiles/unit-local-mac-02`。
- 执行单元 `LEASED`，`browser_started_at=13:46:24Z`，任务进入 `COLLECTING`。
- 真实访问巨量星图并发现 20 位候选，`observed_requests` 随采集增长。

### 2.3 滑块/F10 人工验证

- 13:47:57Z 触发 `PLATFORM_SECURITY_CHALLENGE`，任务 `WAITING_FOR_VERIFICATION`。
- F10 takeover 自动创建并进入 `ACTIVE`；页面显示“远程浏览器正在就绪”，但**本机 noVNC/远程查看未配置**。
- 用户在本机项目 Chrome 中完成滑块；QA 随后在 F10 面板点击“我已完成验证”；系统记录：
  - challenge `RESOLVED`，`recovery_count=1`，`account_matches=true`；
  - takeover `RESUMED`，任务回到 `QUEUED`，重新 `LEASED`。
- 截图：[F10 接管页面](e2e-real-collection-2026-10-20/e2e-03-verification.png)

### 2.4 采集结果与失败

| 项目 | 实测 |
|---|---|
| 目标 | 10 |
| 有效入库（UI/API） | **2** |
| 已发布快照 | **1** |
| 资料完整 | 0 |
| 精选完整 | 0 |
| 封面对象 | **34**（MinIO `xingtu-covers` 34 个对象） |
| featured_collections / cards | 0 / 0 |
| 达人库已加载 | 1（第二位无 `latest_snapshot_id`） |
| 任务最终状态 | **COLLECTING（version 182，无 completed_at，无 failure_reason）** |
| Temporal Workflow | **FAILED**（14:12:31Z） |

**达人结果**

1. 一只平安喵（平台 ID 698…560）：萌宠 / 医药健康 / 母婴宠物 / 工具类软件；杭州；粉丝 1,001,127；有已发布快照；但精选为 `NOT_ATTEMPTED`，资料不完整。
2. C位小师妹（平台 ID 736…225）：生活 / 食品饮料 / 汽车 / 3C 及电器；粉丝 5,703,049；`latest_snapshot_id=NULL`；无互动/完播/CPM/CPE 数据；任务详情标记“执行中草稿”。

**结论：实际只完成 2/10，且仅 1 位有快照；第二位与关键词的语义相关性尚未证实（其为搜索候选），不能据此判定筛选失败；不存在 10 位完整结果。**

截图：

- [2/10 采集中](e2e-real-collection-2026-10-20/e2e-06-collecting-2.png)
- [达人库真实数据](e2e-real-collection-2026-10-20/e2e-07-creator-library.png)
- [达人详情](e2e-real-collection-2026-10-20/e2e-08-creator-detail.png)
- [任务卡在采集中](e2e-real-collection-2026-10-20/e2e-09-stuck-collecting.png)
- [执行单元 SESSION_UNVERIFIED](e2e-real-collection-2026-10-20/e2e-10-unit-unverified.png)

---

## 3. 缺陷清单

### D-01（P1）Workflow 失败但产品任务不收口

**实际表现**

- `CollectF04F05V1` 于 14:12:31Z **FAILED**；失败原因：
  `activity Heartbeat timeout`，`collect_segment_v1` 4 次尝试后 `RETRY_STATE_MAXIMUM_ATTEMPTS_REACHED`。
- `root_tasks.state` 仍为 `COLLECTING`，version 182，`completed_at=NULL`，`failure_reason=NULL`。
- 前端任务详情仍显示“采集中/采集达人资料”，用户无法知道任务已失败。

**复现路径**

1. 真实任务进入 `COLLECTING`；
2. 触发滑块，人工验证完成并恢复；
3. 采集一段时间后，Worker 出现 4 次 `collect_segment_v1` 失败；
4. Temporal Workflow FAILED，root_task 仍 COLLECTING。

**根因证据（已确认 + 待验证）**

- 已确认：`worker.py:574` 的 `except asyncio.CancelledError` 只在 `heartbeat_error` 存在时写任务终态；否则重新抛出，导致 Temporal 已失败而产品任务无人收口。
- 已确认：Temporal 最后事件为 `Activity task timed out / activity Heartbeat timeout`。
- 高置信度：Mac↔云端 DB/Tailscale 延迟或 Playwright 导航阻塞使 45 秒 heartbeat 超时；本轮多次 API/DB 查询也出现 60 秒级卡顿，Worker 日志显示 activity 在 `page.goto` / `check_session` 时被取消。
- 具体是网络延迟还是页面阻塞，需要在 Worker 增加 heartbeat 错误/耗时日志后再确认。

**业务影响**：任务永久显示“采集中”，无法重试/取消收口，结果不发布，运营无法判断失败；属于 P1 核心状态机缺陷。

**建议方向**：在 activity 取消/心跳超时路径中写入明确的 `FAILED/PARTIAL_COMPLETED` 与 failure_reason；对 heartbeat 错误做日志与指标；将 heartbeat_timeout 与页面导航超时解耦。

---

### D-02（P1）F10 恢复后 heartbeat 失败、仅完成 2/10（F10 本身未失败）

**实际表现**

- 滑块人工完成、challenge RESOLVED 后，任务重新 QUEUED/LEASED，第二位达人 basic 成功采集；**F10 恢复本身成功**；
- 恢复约 11 分钟后 heartbeat 停止，4 次 `collect_segment_v1` 被取消，ExecutionUnit generation 从 1 增至 **5**，最终 `SESSION_UNVERIFIED / UNAVAILABLE`、`browser_stopped=true`、`last_session_status=INDETERMINATE`；
- Workflow FAILED，任务不收口。

**根因/证据**

- Worker 日志：4 次 `Completing activity as failed`，traceback 位于 `page.goto` / `check_session` / `locator.is_visible`，最后 `asyncio.CancelledError: Activity cancelled`。
- Temporal：`activity Heartbeat timeout`，max attempts。
- 执行单元：`SESSION_UNVERIFIED`、generation 5、owner NULL、browser stopped。
- 已证实：heartbeat 先做同步 DB 续租再发 Temporal heartbeat，且只捕获 CollectorError；14:11:52 后无心跳，45 秒后 Temporal timeout。
- F10 恢复已成功；`CURSOR_INVALID` rescan 被正常处理，未证明是最终失败的直接原因；`SESSION_UNVERIFIED` 是取消后的释放 disposition，不是 Profile 损坏证据。
- 影响：恢复后长任务在 heartbeat/网络抖动时中断；对本轮目标（10 位）直接阻断。

**建议方向**：修复 heartbeat 顺序/异常捕获和 Activity 取消终态（见 P1FIX-02）；F10 逻辑暂不改，真实复验若仍出现恢复后上下文问题再处理。

---

### D-03（P1）结果数据不完整；第二位相关性未证实且被计为有效

**实际表现**

- 目标 10，实际有效 2；仅 1 份快照；`profile_complete_count=0`、`featured_complete_count=0`。
- 第一位“一只平安喵”为宠物相关，但精选 `NOT_ATTEMPTED`，无精选集合/卡片。
- 第二位“C位小师妹”标签为生活/食品饮料/汽车/3C，**与关键词的语义相关性未证实**；其 ID 是搜索响应候选 first_position=1，不能仅凭行业标签判定筛选失败。该达人无快照、无指标，却被计为 `valid=true`，任务详情显示“2 位可查看”，达人库只显示 1 位。
- 34 个封面对象已写入 MinIO，但没有对应的精选/快照完整结果。

**根因/证据**

- 已确认：`task_creators` 2 行，第二位 `latest_snapshot_id=NULL`；`creator_snapshots` 1 行；`featured_collections/cards` 0；`media_objects` 34。
- 未证实：第二位由人工选择导致候选污染；其 ID 与搜索候选一致，人工切换是否改变候选需平台语义/后续证据确认。
- 已确认：`valid=true` 的草稿无快照仍计入前端“有效入库 2”，与“资料完整 0/达人库 1”语义冲突。
- 已确认：`valid=true` 的草稿无快照仍被计入前端“有效入库 2”，与“资料完整 0/达人库 1”语义冲突。

**建议方向**：先确认平台搜索语义与第二位相关性；`valid`/完整度口径需业务确认后再改；前端明确“草稿/已发布快照”区别。不要仅为标签不含“宠物”就修改筛选逻辑。

---

### D-04（P2）远程 F10 查看不可用，人工验证必须在 Mac 本机

- 执行单元页显示“远程浏览器正在就绪…Linux noVNC 网关配置完成后…”，实际无 noVNC；
- macOS Screen Sharing 未启用，5900/6080 无监听；
- 本轮用户只能在本机项目 Chrome 完成滑块，无法远程操作；
- 影响：无人值守/远程运维场景无法完成安全验证。

**建议**：部署并验收 noVNC 网关；或在产品上明确“需本机人工介入”，不要显示“正在就绪”的误导文案。

### D-05（P2）Heartbeat 机制脆弱且缺少可诊断信息

- 45 秒 heartbeat timeout；Mac↔云端 DB/Tailscale 出现 60 秒级卡顿；
- Worker 在 `page.goto/check_session` 时被取消；`heartbeat_error` 未记录，导致任务状态无法收口；
- 影响：长任务在页面慢/网络抖动时失败，且无根因日志。

**建议**：记录 heartbeat 延迟/异常、页面导航耗时；评估 heartbeat timeout 与网络基线；活动取消时写终态。

### D-06（P2）任务/达人计数语义不一致

- 任务详情“有效入库 2 / 目标 10”“2 位可查看”，但 `profile_complete_count=0`、达人库 1 位、仅 1 份快照；
- 第二位无指标/无快照仍计入有效；
- 影响：运营误判进度。

### D-07（P3）F10 面板状态文案不准确

- 任务详情“安全验证托管/当前达人 698…”仍显示第一位，而实际当前为第二位 736…；
- 剩余 8 位与实际进度不一致；
- 执行单元页 `SESSION_UNVERIFIED` 时“验证”列仍显示“正常”；
- 影响：误导排障。

### D-08（P2/P3，既有部署问题）

- `http://xingtu.yumeng.live` 3/3 被腾讯云 DNSPod 备案页拦截；
- Let's Encrypt 自动续期未验证；
- 安全响应头缺失；
- 部署产物未入库，后端版本仍靠源文件哈希追溯；
- 已登记 [FOLLOW-01](../tasks/FOLLOW-01.md)。

---

## 4. 已验证 / 未验证

### 已验证

- 前端登录、会话保持、登出、重新登录；Cookie/CSRF/Origin/CORS/WS 保护。
- 前端真实创建 `宠物/10` 任务；P1 DeepSeek 真实转换成功，FilterPlan 正确。
- P2 派发、Mac Worker、项目 Chrome 启动、真实访问巨量星图、发现 20 位候选。
- F10 本机原浏览器接管 + 人工滑块完成，challenge RESOLVED、任务恢复 QUEUED。
- 真实数据写入：2 位达人草稿、1 份快照、34 个 MinIO 封面对象；前端达人库/详情可显示。
- 执行单元/Worker/Temporal/DB 状态可读；无伪造 NetworkProof，仍为 `LOCAL_DEVELOPMENT`。

### 未验证 / 失败

- 目标 10 位完整采集：**失败**，仅 2/10。
- 第二位达人筛选相关性：**未证实**（生活/食品/汽车/3C；其 ID 为搜索候选，需平台语义核对）。
- 第一位精选集合：`NOT_ATTEMPTED`；0 精选集合/卡片。
- 任务最终状态、失败收口、发布快照：**失败**（Workflow FAILED，root COLLECTING）。
- 远程 F10/noVNC：**BLOCKED**（仅本机可用）。
- 生产移动线路/NetworkProof：**NOT TESTED**（本轮 LOCAL_DEVELOPMENT）。
- Worker 断线/恢复、Profile 锁、网络故障注入：**NOT TESTED**。
- HTTP 80/证书自动续期/安全头：既有 FAIL，未在本轮修复。

---

## 5. 最终 QA 结论

**NO-GO。**

- P1 DeepSeek 转换与真实任务创建已通过，但真实 P2 采集未完成 10 位目标，且发生 **Workflow FAILED / 产品任务 COLLECTING** 的核心状态不一致。
- 人工滑块后仅完成 2/10；第二位相关性未证实且没有快照/指标；无法把当前结果用于业务验收。
- F10 远程查看不可用，人工验证依赖 Mac 本机；本轮已由用户手动完成，但不具备可重复的远程验收条件。
- 现有 HTTP 80、证书续期、安全头、部署可追溯性仍为部署待办；不是本轮 NO-GO 的主因。

**建议不要在当前状态进入下一阶段真实采集验收。** 先修复 D-01/D-02/D-03，再进行一次受控的 10 位复测。

---

## 6. 下一步建议（最小必要）

1. **修复任务终态收口**：activity 被 Temporal 取消/心跳超时时，必须写 `FAILED`/`PARTIAL_COMPLETED` 与 failure_reason；不得让 root_task 永久 COLLECTING。
2. **修复 F10 恢复**：takeover 完成后重新建立 search/candidate 上下文；人工浏览不得改变任务候选；恢复后校验当前达人、筛选条件与游标。
3. **修正 valid/计数语义**：无快照/无必要数据的草稿不得作为“有效入库”；前端区分草稿与已发布快照。
4. **heartbeat 诊断**：记录 heartbeat 延迟、页面导航耗时、取消原因；评估 45 秒阈值与 Mac↔云端网络基线。
5. 修复后**只复测一次** `宠物/10`；复测前不要重试当前 stuck 任务，不要创建第二个真实任务。
6. 远程运维需另行授权部署/验收 noVNC；HTTP 80/证书/安全头按 FOLLOW-01 处理。

---

## 7. 证据索引

| 文件 | 内容 |
|---|---|
| [01-p1-plan.txt](e2e-real-collection-2026-10-20/01-p1-plan.txt) | P1 model_run/FilterPlan |
| [02-e2e-timeline.txt](e2e-real-collection-2026-10-20/02-e2e-timeline.txt) | 创建→滑块→恢复→失败→卡住时间线 |
| [03-temporal-failure.txt](e2e-real-collection-2026-10-20/03-temporal-failure.txt) | Workflow FAILED / heartbeat timeout |
| [04-worker-state.txt](e2e-real-collection-2026-10-20/04-worker-state.txt) | Unit SESSION_UNVERIFIED / root COLLECTING |
| [05-data-results.txt](e2e-real-collection-2026-10-20/05-data-results.txt) | 2/10、快照、封面、达人标签 |
| [06-security-recheck.txt](e2e-real-collection-2026-10-20/06-security-recheck.txt) | 登录/Cookie/CSRF/CORS/WS/HTTP80/安全头 |
| [e2e-01-form.png](e2e-real-collection-2026-10-20/e2e-01-form.png) | 前端真实任务表单 |
| [e2e-03-verification.png](e2e-real-collection-2026-10-20/e2e-03-verification.png) | F10 接管与 noVNC 缺失 |
| [e2e-06-collecting-2.png](e2e-real-collection-2026-10-20/e2e-06-collecting-2.png) | 2/10 采集中 |
| [e2e-07-creator-library.png](e2e-real-collection-2026-10-20/e2e-07-creator-library.png) | 真实达人库 |
| [e2e-08-creator-detail.png](e2e-real-collection-2026-10-20/e2e-08-creator-detail.png) | 达人详情 |
| [e2e-09-stuck-collecting.png](e2e-real-collection-2026-10-20/e2e-09-stuck-collecting.png) | 任务卡在采集中 |
| [e2e-10-unit-unverified.png](e2e-real-collection-2026-10-20/e2e-10-unit-unverified.png) | 执行单元 SESSION_UNVERIFIED |

### 数据安全声明

本报告与证据不含账号密码、Cookie/Token、API Key、数据库/MinIO 凭据；达人平台 ID 未完整展示；未保存 HAR；未删除或伪造业务数据。
