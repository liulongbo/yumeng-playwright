# 修复记录：DF-01 采集断点 / DF-03 丢失底层异常 / DF-06 集成测试替身失效 / DF-07 挑战放行过早

- 日期：2026-10-13（Asia/Shanghai）
- 授权：用户 2026-10-13 明确授权修复核心流程采集，并要求排查 5 秒误判问题
- 分支/HEAD：`llb_1013` / `ee11254`（经核实 HEAD 已是 `10.9` 合并后的最新提交，无更早可用分支作为回退点）
- 边界：未重构、未改 Schema、未改环境配置语义、未绕过平台安全验证

---

## 1. DF-01（P0 阻断）采集断点 —— 根因与修复

### 1.1 根因：early-return 回归，不是平台限制

并行会话新增的"人工身份认证"回退在 `adapter.py` 的 `inspect_session()` 中
**受保护标记刚出现就立即返回 `VALID`**，未给账号定位符任何渲染时间：

```python
if protected_seen:
    ...                      # 账号可读则正常返回（含 wrong-account 检测）
    if self.manually_attested_account_id == self.account:
        return VALID         # ← 过早返回：app shell 仍在启动
```

失败链条：过早认证 → `prepare()` 立即驱动页面 → SPA 尚未就绪 → 平台自身导航把页面带到
`https://www.xingtu.cn/?redirect_uri=%2Fad%2Fcreator%2Fmarket` → `fill` 在新 URL 上等不到元素
→ **90 s（Playwright 默认）超时** → `BrowserError` → `RESOURCE_UNAVAILABLE:BROWSER_TRANSPORT`
→ `WAITING_FOR_RESOURCE`，`candidates=[]`。

**反证**：同一 profile 用项目自身 `BrowserRuntime` 只读探测 `/ad/creator/market`，等待 6 s 后
`protected=true`、`account="ID: 1807978499337419"`、`input[placeholder="按内容关键词找达人"]` 可见。
即登录态有效、账号正确、契约选择器未失效，**唯一差别是是否等待页面就绪**。

### 1.2 修复

认证回退移入 **deadline 之后**，且要求 `protected_seen` 在整个有界窗口内持续为真：

```python
if asyncio.get_running_loop().time() >= deadline:
    if protected_seen and self.manually_attested_account_id == self.account:
        return VALID / MANUALLY_ATTESTED_UNIQUE_ACCOUNT
    return INDETERMINATE / (PROTECTED_PAGE_ACCOUNT_UNREADABLE | NO_REGISTERED_SESSION_SIGNAL)
```

- 保留设计意图：DOM 确实读不到账号时，显式、限时、仅限 `local_development` 的操作者认证仍可用；
- 恢复原有语义：窗口内重新轮询等待账号渲染，页面就绪后才判定；
- 未放宽安全边界：可读账号**始终优先**于认证，`ACCOUNT_MISMATCH` 检测不受影响。

---

## 2. DF-07（P2）挑战"放行过早" —— 用户要求排查的 5 秒误判

### 2.1 现场数据

| 项 | 实测 |
|---|---|
| `stable_seconds`（策略） | 5.0 |
| 首次挑战可见 → 判定"已清除" | **5.360 s** |
| 该判定后挑战**再次出现** | **62.5 s** |
| 该任务 `checkpoint.challenge_count` | 2（达 `max_task_recoveries=2` 后收口） |

判定耗时几乎正好等于 `stable_seconds`，且账号与受保护面均匹配，因此 `wait_for_stable_session`
的稳定窗口分支被满足并返回 `CHALLENGE_CLEAR_STABLE_WINDOW`。

### 2.2 可确证的缺陷（已修）

`wait_for_stable_session` 在**整个等待过程中从未观测到挑战 iframe**的情况下，也会在
`stable_seconds` 后宣布"会话稳定"。而挑战 iframe 是**异步加载**的：它可能尚未渲染进 DOM。
因此"连续 5 s 看不到挑战"与"iframe 还没加载出来"在当时不可区分。

修复（`challenge.py`）：

- `ChallengePolicy.challenge_observation_seconds`：新增观测窗口，显式给定；未给定时按
  `max(stable_seconds × 3, stable_seconds + 3)` 推导（生产默认 `stable=5 → 观测窗口 15 s`），
  并要求 `>= stable_seconds`，否则构造报错；
- 该窗口**仅在本轮等待中确实观测到过挑战时生效**（`challenge_seen_this_wait`）。
  未观测到挑战时会话检查行为与修复前完全一致 —— 这一点是必需的：否则每次会话校验都要空等窗口，
  会把"恢复既有会话"变成一个无谓的 15 s 停顿（实测该写法导致 4 个集成用例失败，见 §4.2）；
- 新增诊断日志：`stable_window` / `observed_for` / `since_last_challenge_visible` /
  `challenge_samples` / `clean_samples`，使"是否真的见过挑战"从日志即可判定。

### 2.3 诚实的未确证部分

**无法确证** 62.5 s 后再次出现的那次挑战是否由该过早放行**直接导致**。两种解释都与现场数据相容：

1. 放行时 iframe 尚未加载 → 系统在挑战仍待处理时开始采集；
2. 放行是正确的，平台随后基于**自动化浏览行为**新发了一次挑战。

已实测的正面证据：修复后的一次完整真实采集（`f74f43bf`，10 位达人）**全程 `challenge_count = 0`**，
未出现挑战。因此该问题需要下一次真实挑战才能闭合验证，本轮不宣称已完全证实。

---

## 3. DF-03（P2）底层传输异常被吞掉

`worker.py` 的 `except BrowserError` 分支原先只抛 `RESOURCE_UNAVAILABLE:BROWSER_TRANSPORT`，
底层异常类型与 message 全部丢失。本轮为定位 DF-01 不得不**临时插桩**该行才拿到决定性线索
（"页面被导航到 `?redirect_uri=...`"）。现补常驻告警日志，记录 `attempt`、异常类型与 message。

---

## 4. DF-06（P2）集成测试替身失效

`test_browser_host_promotes_and_collects_with_the_exact_same_context` 抛
`TypeError: clearance() takes 3 positional arguments but 4 were given`。**产品代码自洽**
（`browser_host.py:215` 传 4 个、定义收 4 个），是测试替身未跟随契约变更。已补齐：

| 项 | 修复 |
|---|---|
| `clearance` 替身 | 补第 4 个参数 |
| `Verifier.check_session` 替身 | 返回真实 `SessionHealth`（promotion 现在 observe 校验器自身健康，不再把人工放行重新标注为自动校验） |
| `_FakeRuntime` | 支持 `export_session_snapshot` 记录，并**新增**断言证明快照确实导出 |

原有断言一条未削弱（`verified` 三方比对、`browser.pages[0].urls == [search.entry_url]`、
`take_collection_page()` 一次性移交、`session_version + 1`、终态 `READY`/`browser_stopped` 全保留）。

### 4.1 关于 `test_challenge.py` 的契约更新

`test_stable_window_resets_after_challenge_flicker_without_page_actions` 的
`timeout_seconds=5` 无法容纳任何有效观测窗口。已显式声明新契约：
`challenge_observation_seconds=4`、`timeout_seconds=8`，并把断言从 `clock.value >= 3.0`
更新为 `>= 6.0`（挑战最后可见于 2.0，其后需 4 s 观测 + 1 s 稳定）。这是**变更契约的显式登记**，
不是放宽断言。

### 4.2 我自己的回归与修正

DF-07 首次实现把观测窗口无条件施加于所有路径，导致集成测试 **79 passed → 4 failed**。
经 A/B 验证（临时 stash 掉该文件后 79 passed）确认由我引入，随即改为**仅在确实观测到挑战时生效**，
恢复 79 passed。记录此事以说明该判定是实测结论，而非推断。

---

## 5. 验证证据

### 5.1 静态与全量套件（最终代码）

| 检查 | 结果 |
|---|---|
| `ruff check backend conftest.py tests scripts` | All checks passed |
| `ruff format --check` | 72 files already formatted |
| `mypy backend/src`（strict） | Success: no issues found in 30 source files |
| `pytest backend/tests/unit` | **189 passed** |
| `pytest backend/tests/contract` | **29 passed** |
| `pytest backend/tests/integration` | **79 passed, 1 skipped** |
| `npm --prefix frontend run lint` + `vitest` | 通过，3 passed |
| `tests/e2e` | BLOCKED（缺 Temporal 测试服务器二进制，环境问题，非代码） |

### 5.2 DF-01 修复前后的真实采集对照（同环境、同 profile、关键词 `汽车`、目标 10）

| 指标 | 修复前 `4196884d` | 修复后 `2111c8f5` | 完整跑 `f74f43bf` |
|---|---|---|---|
| 终态 | `WAITING_FOR_RESOURCE` | `PARTIAL_COMPLETED` | `PARTIAL_COMPLETED` |
| `failure_reason` | `RESOURCE_UNAVAILABLE:BROWSER_TRANSPORT` | `SECURITY_CHALLENGE_LIMIT` | `PROFILE_SCOPE_INCOMPLETE` |
| `candidates` | **0** | **20** | **20** |
| `observed_requests/responses` | 0 / 0 | **30 / 30** | 有 |
| `task_creators` | 0 | 1 | **10** |
| `creator_snapshots` | 0 | 3 | **10**（重试后 20） |
| `featured_collections` | 0 | 0 | **20** |
| `featured_cards` | 0 | 0 | **66** |
| `media_objects`（封面） | 0 | 0 | **56** |
| `challenge_count` | — | 2（收口） | **0** |
| 提交→终态 | 未达终态 | 79 s | 约 16 min |

### 5.3 MVP 全链路（`f74f43bf-ffbc-4577-b8af-9a7a5db44662`）
`RECEIVED → PARSING → QUEUED → SEARCHING → COLLECTING → PARTIAL_COMPLETED`，`version` 0→1003。

前端三方一致（测试浏览器 + API + DB）：

- 任务详情：`部分完成`、进度轨道、"任务需要关注"面板文案、"重试失败步骤"按钮；
- 计数：已发现 **20** / 有效入库 **10**（目标 10）/ 资料完整 **6** / 精选完整 **9** / 失败步骤 0；
- 任务内达人列表：**10 位**，全部标注"已发布快照"；
- 达人详情页渲染不可变快照与逐字段状态（`fans.COLLECTED`、`monthly_connected_users` 等真实值）。

### 5.4 为什么是 `PARTIAL_COMPLETED` 而不是 `COMPLETED`（结论：设计正确，非缺陷）

用项目自身 `Repository.profile_coverage()` 逐位核对，模块级 8/8 `COLLECTED`，但**字段级**存在缺口：

| 达人 | 缺口（示例） |
|---|---|
| 4 位 | `FIELD_INCOMPLETE:seeding.a3_increment`、`seeding.search_after_view_rate`、`conversion.gpm_range`、`conversion.sales_amount_range` 等 |
| 1 位 | `FIELD_INCOMPLETE:conversion.recommended_product_count`、`fulfillment.processing_order_count`、`fulfillment.max_processing_order_count` |

即：这些是**平台对部分达人未公开的可选字段**，系统按字段状态如实标注，并把任务收口为
`PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE`，前端也如实提示"有位达人的主页资料本次未能全部读到"。
**未伪报完成**，符合 §14.3 口径。

另：首次采集中 1 位达人的 `fans` 模块 `FAILED`（`module unreadable`，已知偶发）；
经 `retry` 后**最新快照 8/8 模块全部 `COLLECTED`**（历史快照按不可变契约保留，故总快照数为 20）。
这同时正面验证了 `retry` 链路与快照不可变性。

### 5.5 最终代码的独立复现（`1e7a02ff-56c5-4f5b-b92f-3a8c6d71e9be`）

在**全部修复落地后的最终代码**上重新提交同一需求（关键词 `汽车`、目标 10），前端真实提交、
全程零人工干预：

| 指标 | 实测 |
|---|---|
| 状态序列 | `RECEIVED → PARSING → QUEUED → SEARCHING → COLLECTING → PARTIAL_COMPLETED` |
| `version` | 0 → **756** |
| 提交 → 终态 | 21:29:48 → **21:46:57（约 17 分钟）** |
| `task_creators` | **10** |
| `creator_snapshots` | **10** |
| `featured_collections` | **20** |
| `featured_cards` | **64** |
| `media_objects`（封面） | **54** |
| `model_runs`（succeeded） | 1（真实 DeepSeek 调用） |
| **`challenge_count`** | **0（全程未触发安全验证）** |
| `failure_reason` | `PROFILE_SCOPE_INCOMPLETE`（同上，字段级可选字段缺口，如实收口） |
| 执行单元终态 | `READY`、`browser_stopped=true`、`last_session_status=VALID`（租约正常释放） |

**结论：DF-01 修复稳定可复现，MVP 核心闭环（登录 → 提交 → 转换 → 调度 → 真实采集 → 落库 → 状态回流 → 前端展示）已完整跑通。**

---

## 6. 未完成事项

1. **DF-07 的最终闭合**：需要一次真实挑战来确认观测窗口生效（修复后两次真实采集均未触发挑战）。
2. **`tests/e2e` 7 项**：缺 `XINGTU_TEMPORAL_TEST_BINARY`。
3. **回归报告中的其余未完成用例**：会话保持/登出失效/重复采集去重规则/卡死与排队区分/并发登录加固等。

未执行任何绕过安全验证、注入 Cookie 或风控规避动作。
