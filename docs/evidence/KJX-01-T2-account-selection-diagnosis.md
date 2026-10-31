# KJX-01 T2 子账号选择页专项诊断、修复与第 2 页真实验收

状态：诊断、修复、提醒、T2 同范围真实重试与专项回归均完成  
日期：2026-10-30（执行窗口 22:26—23:0x +08:00）  
结论：**GO**。T2 最终任务 `56efbba5-d267-44a2-824a-2ba4e60f2dd9` **COMPLETED 22/22/22**，checkpoint `visited_cursors=[None,"2"]`；19 项双平台 MCP 回归全部通过。  
边界：未改星图核心采集规则，未新增数据库表/列/迁移，未绕过平台验证，未自动选择任何子账号。

## 1. 根因诊断

### 1.1 结论

**多因素共同作用，不是平台风控，也不是单一 Bug**：

1. 「选择账户」是**磁力聚星正常子账号选择页**：页面标题 `选择账户`，列出 `cpg果汁 / ID 60821564`（本任务绑定、正确）与 `找CPG9945已掉10 / ID 28432963`；没有验证码、滑块、异常登录提示或访问限制。
2. **程序 Bug A（主因）**：上一次 T3 星图任务的安全验证超时后，双平台共享执行单元遗留 `NEEDS_VERIFICATION`；T3 的 verification event 已在 16:33:34 过期，但单元状态未清理。T2 Activity 于 16:33:35 开始，被错误纳入 security maintenance，15 分钟后写成 `SECURITY_CHALLENGE_TIMEOUT`；T2 实际从未开始聚星搜索，0/22。
3. **程序 Bug B**：聚星合同/Adapter 没有登记或识别正常子账号选择页；页面被当成通用等待，没有独立的 `ACCOUNT_SELECTION_REQUIRED` 分类、verification event、前台提醒或安全超时原因。
4. **体验缺口**：任务详情只显示「平台安全验证」，没有告诉用户「正在等待选择子账号 / 请在 Chrome 选择 cpg果汁（60821564）」；执行单元页当时也没有对应事件；用户 15 分钟内无法从系统获知要做什么。

### 1.2 时间线与证据

| 时间（UTC） | 证据 |
|---|---|
| 16:12:02 | T3 星图任务 `516a9e3b-...` 创建 |
| 16:13:20 | T2-批准 `50cccb72-...` 创建，QUEUED |
| 16:18:34 | T3 平台安全验证事件 OPEN，deadline 16:33:34 |
| 16:33:34 | T3 事件 EXPIRED；T3 任务转 PARTIAL_COMPLETED |
| 16:33:35 | **T2 Activity 才开始**（晚于 T3 事件过期 1 秒） |
| 16:33:45 | T2 进入 `WAITING_FOR_VERIFICATION` / `PLATFORM_SECURITY_CHALLENGE` |
| 16:48:37 | T2 Activity 以 `SECURITY_CHALLENGE_TIMEOUT` 结束，0/22 |

- T2 checkpoint：`challenge_state=TIMEOUT`、`challenge_first/last_detected_at=None`、`candidates=[]`、`active_seconds=0`；**没有 T2 自己的 verification event**。唯一事件是 T3 星图的 `EXPIRED` 事件。
- T2 的 `unit-local-mac-02-kjx-full` 是双平台共享单元；T3 超时后单元状态为 `NEEDS_VERIFICATION`；T2 的 15 分钟是 `BrowserHost.maintain_and_promote` 的维护等待，不是聚星采集。
- 用户截图（本机 Chrome）显示实际页面为「选择账户」；只读 Playwright MCP + Chrome 复核（isolated profile + 已核验 storage-state，不点选）确认：
  - URL `https://k.kuaishou.com/#/star_plaza/video`，标题「找达人-磁力聚星」；
  - heading `选择账户`，账号组件 `div.account-component`；
  - 两行账号：`cpg果汁 ID:60821564`、`找CPG9945已掉10 ID:28432963`，操作列 `进入`；
  - 无验证码/滑块/风控提示；页面可稳定复现账号选择态。
- 代码证据：旧 `transition_collect_to_maintenance` 只接受登录/账号不匹配/安全验证；旧 worker 仅依据单元 `NEEDS_VERIFICATION` 进入 maintenance；旧 `wait_for_stable_session`/`wait_for_manual_clearance` 不认识账号选择；T2 的 maintenance 页面无事件、无提醒。

### 1.3 定位回答

1. 页面真实类型：**正常磁力聚星子账号选择页**。
2. 为什么出现：聚星 Profile/会话在该次浏览器上下文中未带已选子账号上下文，平台要求选择；同时 T2 被过期星图 maintenance 状态错误接管。
3. 性质：**正常平台行为 + 程序 Bug（过期单元状态未清理/跨平台共享；账号选择未识别、未通知）+ 前端提示缺口**；T3 星图的安全验证是真实平台验证，但不是 T2 的页面。
4. 证据：Temporal 起止、DB checkpoint、verification event、用户截图、只读 MCP DOM、代码路径。
5. 复现性：过期验证事件 + 下一任务开始 1 秒后进入 maintenance 的序列在代码上可稳定复现；账号选择页在对应 Profile 会话下可稳定复现。
6. 影响：T2 聚星任务；共享单元可能把星图验证状态带给聚星（反方向同样）；不影响已完成的 T1/T3 重试。
7. 账号/Profile：与聚星会话/子账号上下文有关；正确账号 `60821564`，错误账号必须 `ACCOUNT_MISMATCH`。
8. 避免误判：登记账号选择页 selector，独立为 `ACCOUNT_SELECTION_REQUIRED`；security challenge 只保留真实安全验证信号；超时原因分别为 `ACCOUNT_SELECTION_TIMEOUT` 与 `SECURITY_CHALLENGE_TIMEOUT`。

## 2. 修复内容

| 文件 | 修改 | 行为变化 |
|---|---|---|
| `backend/src/xingtu/domain.py` | `ERROR_CODES` 增加 `ACCOUNT_SELECTION_REQUIRED`/`ACCOUNT_SELECTION_TIMEOUT`；`ChallengeType` 增加 `ACCOUNT_SELECTION` | 正常账号选择与安全验证分开 |
| `contracts/kuaishou_juxing.verified.json` | session 增加 `ACCOUNT_SELECTION_REQUIRED -> div.account-component`；contract v3 / adapter v3；capability v2 不变 | 页面信号来自真实只读核验，不猜测 |
| `backend/src/xingtu/juxing_adapter.py` | navigate 的 `wait_ready` 遇到账号选择时保留 `ACCOUNT_SELECTION_REQUIRED`，不折叠为导航超时 | 账号选择可到达 worker |
| `backend/src/xingtu/worker.py` | 启动时 `reconcile_stale_verification`；捕获 `ACCOUNT_SELECTION_REQUIRED` 进入维护并创建 verification event、置 `WAITING_FOR_ACCOUNT`；超时写 `ACCOUNT_SELECTION_TIMEOUT`；扩展 pristine v3 plan 的 legacy 版本 adopt | 过期星图 maintenance 不再阻塞聚星；账号选择可人工处理；版本升级不再误杀新 T2 |
| `backend/src/xingtu/repository.py` | `reconcile_stale_verification`、`unit_has_open_verification_event`；maintenance 接受账号选择原因；promote 时 resolve event | 单元状态与事件一致；处理完提醒自动解除 |
| `backend/src/xingtu/browser_host.py` | `wait_for_manual_clearance` 把账号选择视为等待人工，不当作页面错误 | 用户在 Chrome 选择后同一页面继续 |
| `backend/src/xingtu/product_queries.py` | challenge summary 区分 `ACCOUNT_SELECTION`；超时文案；`WAITING_FOR_ACCOUNT` 的 requires_user_action | API 返回准确原因 |
| `frontend/src/pages.tsx`、`status.ts`、`styles.css` | 任务中心「需要选择子账号」；任务详情/ChallengePanel 明确平台/账号/Chrome/不要选其他；单元页「需要选择子账号」与接管入口；超时文案 | 用户无需等 15 分钟；刷新仍可见；处理完自动解除 |

**对星图影响**：星图合同、Adapter、F04/F05/F06、完成判定与原有安全验证逻辑未改；共享的过期验证清理是单元级状态修复，星图真实 T3 重试仍 COMPLETED。`ACCOUNT_MISMATCH` 保留。

## 3. 子账号提醒验收

- 只读 MCP 复核账号选择页在选择前稳定出现，selector `div.account-component` 可见。
- 任务/单元提醒：新增 `WAITING_FOR_ACCOUNT + ACCOUNT_SELECTION_REQUIRED`；任务中心徽标「需要选择子账号」；任务详情「磁力聚星需要选择子账号…在 Chrome 中选择 cpg果汁（60821564）…请勿选择其他子账号」；单元页 verification alert 显示「需要选择子账号 cpg果汁（60821564）」及接管按钮；事件 OPEN 即出现，刷新可见，不重复；promote 后 resolve。
- 正确/错误账号：选择 `60821564` 后重新校验通过；选择 `28432963` 仍由 `ACCOUNT_MISMATCH` 拒绝，不自动重绑。
- 超时：`ACCOUNT_SELECTION_TIMEOUT`，不再统一显示安全风控。
- 本轮 T2 实际运行时账号选择页**未再次出现**（会话已带正确子账号上下文），因此真实任务路径直接从收藏页进入；账号选择页本身由只读 MCP、合同/Adapter 单测和前端提醒测试覆盖。

## 4. T2 真实任务结果

| 项 | 结果 |
|---|---|
| 任务 ID | `56efbba5-d267-44a2-824a-2ba4e60f2dd9` |
| 筛选 | 磁力聚星 / 母婴 / 母婴亲子 / target=22（未改条件、未扩大） |
| Temporal | `collect/56efbba5...`，`collect_segment_v1` 正常完成 |
| 第一页 | 20 候选 |
| 第二页 | **`visited_cursors=[None,"2"]`**；40 个候选（两页各 20）；`processed_operations=2`；无第 3 页请求 |
| 最终 | **COMPLETED，valid 22 / profile 22 / 22，failed 0** |
| 持久化 | `task_creators` 有效 22；`creator_snapshots` 22；无跨平台污染 |
| 前端 | 任务中心、任务详情、达人库、聚星详情读取一致 |
| 说明 | 首次 T2-批准 `50cccb72...` 0/22 为过期星图 maintenance + 正常账号选择误判，已由本报告定位；T2-偏差 `7ec6a121...` 16/22 仅第 1 页，不计分页证据 |

## 5. 回归测试

| 项 | 结果 |
|---|---|
| 后端单元 + 合同 | **404 passed**（含新增账号选择单测；合同 v3） |
| 前端 | **104 passed** + tsc/build（新增任务详情账号选择提醒单测） |
| E2E/隔离集成 | 既有 14 E2E、118/1 skipped 保持；T2/T3/T1 真实栈证据 |
| 最终双平台 MCP | **19 PASS / 0 FAIL** |
| T1 | COMPLETED 3/3/3 |
| T3 重试 | COMPLETED 1/1/1 |
| T2 最终 | COMPLETED 22/22/22，第 2 页 |
| 静态 | 本卡改动 Ruff/format、Mypy strict、`git diff --check` 通过 |
| 星图 | T3 重试与 F06/详情/库回归通过；未重复真实星图采集 |

## 6. 最终结论

1. 子账号选择页为什么出现：聚星会话未带已选子账号时平台正常要求选择；同时过期星图验证状态错误地把 T2 放进 maintenance。
2. 是 Bug：是（过期跨平台维护状态 + 账号选择未登记/未通知 + 版本 adopt 覆盖不足），已修复。
3. 用户能否及时收到提醒：能；任务中心/任务详情/执行单元均提示，事件 OPEN、刷新可见、处理完解除；正确账号明确。
4. 正确子账号选择后能否恢复：能；重新校验 `60821564` 后 promote 继续；错误账号仍 `ACCOUNT_MISMATCH`。
5. T2 是否真实完成第二页：是；`visited_cursors=[None,"2"]`，40 候选、22 done。
6. 是否达到 22/22/22：是；COMPLETED，valid 22、profile 22、failed 0、snapshots 22。
7. 是否可关闭 CONDITIONAL：“**是，GO**”；19/0 MCP、T2 第二页、T3、T1、星图回归与自动化均通过。剩余 Windows/生产 Flag/看履约-看带货/第 3 页+ 仍为原有范围外，不是本条件。

> 私有证据：`.runtime/kjx-full/t2-diagnosis/probe/`、`.runtime/kjx-full/regression/mcp-t2-final/`、任务 56ef 的 DB/Temporal；截图与 Cookie/DSN 不入 Git。
