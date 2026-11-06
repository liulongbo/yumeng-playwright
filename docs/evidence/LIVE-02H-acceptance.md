# LIVE-02H 磁力聚星直播广场 70 位真实采集验收报告

日期：2026-11-06（Asia/Shanghai）
分支：`1105-live02g`，HEAD `d9f263e`
方式：Playwright MCP + Chrome 操作真实前端；真实平台磁力聚星；任务执行由 `unit-local-mac-03-juxing` 完成
结论：**PASS（70/70 有效、70/70 资料完整、COMPLETED；0 失败字段）**
关联：[LIVE-02H 任务卡](../tasks/LIVE-02H.md)、[LIVE-02H 测试用例](LIVE-02H-test-cases.md)、[LIVE-02G 验收](LIVE-02G-acceptance.md)

## 1. 任务信息

| 项 | 实测 |
|---|---|
| 真实任务 ID | `0b37dedf-3b98-409d-aab0-754dbb670c76` |
| 创建方式 | 前端 `/tasks/new`，Playwright MCP + Chrome 真实点击/填写/提交（非 API 替代） |
| 测试时间 | 2026-11-06 00:10–01:32（Asia/Shanghai） |
| 平台/场景 | 磁力聚星 / 直播广场（`live_square`） |
| 筛选条件 | 内容分类 **时尚**；未放宽/取消 |
| 目标数量 | **70** |
| 实际执行单元 | `unit-local-mac-03-juxing` |
| 最终任务状态 | **COMPLETED** |
| 最终有效/完整 | **70 / 70；70 / 70** |
| 任务尝试 | 3 次，同一 root：初次 `28513e35…`、继续 `8a04e306…`、补采 `b88e78ac…` |
| 前端最终页面 | [任务完成截图](../evidence/assets/LIVE-02H/live02h-final-task.png) |

> 前端最终显示：`已完成`、`有效入库 70 / 目标 70`、`资料完整 70 / 全部完整`、`失败步骤 0`，无“补采/继续”按钮。

## 2. 采集结果

| 指标 | 实测结果 |
|---|---|
| 目标数量 | 70 |
| 有效达人数量 | **70** |
| 成功入库数量 | **70** |
| 实际访问页数 | **4**（page 1–4；`visited_cursors=[None,"2","3","4"]`，cursor=5） |
| 候选达人数量 | **80**（4 页 × 20；80 个唯一 userId） |
| 重复候选数量 | **0**（跨页去重；80 unique/80） |
| 未使用候选 | 10（达到 70 后停止，未访问/未采集，不是失败） |
| 失败/不可用达人 | **0**（最终 checkpoint invalid=0、failed=0；0 FAILED 字段） |
| 快照数量 | **79**（70 位达人 + 9 份补采新快照；70 个不同 creator，最新快照 70 份） |
| task_creators | **70**，全部 valid，70 个不同 creator |
| creator_live_current | **70**，最新快照 70 个不同 |
| 最终任务状态 | **COMPLETED**，`failure_reason=null`，`pipeline_complete=true` |

### 分页与筛选

真实 worker 日志（同一 root）：

| 页 | 请求时间 | 筛选 | applied |
|---|---|---|---|
| 1 | 00:10:44 | `live_content_category` | `contentTagIdList=[{id:"675",subIds:["735".."739"],selectFirstLevelId:true}]` |
| 2 | 00:21:10 | 同上 | 同上，digest 不变 |
| 3 | 00:37:55 | 同上 | 同上，digest 不变 |
| 4 | 01:02:27 | 同上 | 同上，digest 不变 |

- 平台 `total=5000`；任务只读取实际需要的 4 页，未访问第 5–7 页。
- 只读探测（任务外，Chrome 登录上下文）：page 7/8 均 HTTP 200、20 行、0 重复；**未提升契约 page 上限**（`page_fetch_max_verified=6`）。
- 第 7 页不是本任务完成条件；任务 4 页即达到 70。

## 3. 执行与恢复

### 3.1 初次执行

- 前端提交后 P1 计划：`live_content_category=["fashion"]`、`target_count=70`、`juxing-live-square-capability-v2`；调度至 `unit-local-mac-03-juxing`。
- 00:10–01:02：page 1–3 完成 60 位有效；page 4 首位候选 `2340057801` 详情页动作等待 20s 超时，任务在 **60/70** 时 `FAILED / PLATFORM_PAGE_CHANGED:BROWSER_ACTION_FAILED`。已采 60 位、60 份快照保留。
- 同时发现 **9 位达人、63 个 index 字段**因平台 `查询为空` 被误判 FAILED（见 §4）。

### 3.2 继续原任务（不重建）

- 前端任务页显示“继续采集（还差 10 位）”；确认只补数量、不重采已入库。
- 新 attempt `8a04e306…` 从原 checkpoint 继续；60 位 done 未重采；page 4 剩余候选继续。
- 01:05–01:21：有效 60 → **70**；终态 `PARTIAL_COMPLETED`，资料完整 61/70，9 位 index 待补采。
- 原有 60 位快照/数据保留；未创建第二个 70 任务。

### 3.3 补采缺失字段（同一 root）

- 前端“补采缺失字段（9 位）”；新 attempt `b88e78ac…`。
- 仅重置 9 位不完整有效达人 + 10 位从未使用的 page 4 候选；61 位完整达人保持 done，未重采。
- 01:22–01:32：9 位 index 被重新采集；修复后平台查询为空 → **NO_DATA**；0 FAILED。
- 终态 **COMPLETED**：valid 70、profile complete 70、pipeline complete true、failure_reason null。

### 3.4 模块与字段

- 70 位达人全部具备 8 模块：
  `basic / live / fans_trend / index / works / audience / commerce / cooperation`。
- 70 × 70 = **4900** 个字段观测：
  - **COLLECTED 3664**
  - **NO_DATA 1236**（平台明确空/查询为空/全 0 等）
  - **FAILED 0**
  - **NOT_ATTEMPTED 0**
- 8 模块观测数各 70；module sets 全部 8 个；无模块缺失。
- 典型平台 NO_DATA：index 70（10 位达人查询为空）、live 613、works 80、commerce 44、cooperation 138、basic 258、fans_trend 28、audience 5。
- 详细模块字段分布：`live` 1417/613、`basic` 722/258、`index` 420/70、`works` 200/80、`audience` 135/5、`commerce` 306/44、`fans_trend` 392/28、`cooperation` 72/138（COLLECTED/NO_DATA）。

## 4. 缺陷与最小修复

### 4.1 问题

- 现象：9 位时尚达人的 index 模块 7 个字段全部 FAILED（合计 63 字段），任务最终 `PARTIAL_COMPLETED`。
- 平台真实响应（HTTP 200）：
  ```json
  {"result":1,"errMsg":"查询为空","starRadarGraphVO":null}
  {"result":1,"errMsg":"查询为空","starTrendGraphVO":null}
  ```
- 页面/接口明确表示该达人没有指数数据，不是采集失败。
- 证据：
  - `.runtime/live02h/index-failure/raw-responses.json`
  - `.runtime/live02h/index-failure/checkpoint-failures.json`
  - 受影响 userId：`126294140`、`2180773250`、`1768843196`、`1626732271`、`678375121`、`4351711073`、`4450493551`、`2278223859`、`3995434228`（及补采/继续阶段另一 query-empty 达人）。

### 4.2 根因

`KuaishouJuxingLiveAdapter._radar/_trend` 只接受非空 dict；当平台明确 `errMsg="查询为空"` 且 VO 为 null 时，抛 `JUXING_LIVE_RADAR_SCHEMA/TREND_SCHEMA`，把 NO_DATA 误判为 FAILED。

### 4.3 修复（Juxing 直播专属最小改动）

| 文件 | 修改 |
|---|---|
| `backend/src/xingtu/juxing_live_adapter.py` | `_radar/_trend`：当 `errMsg` 明确为“查询为空”且 VO 为 null 时保存原始 payload、返回空观测，不设置 schema error；真正 malformed/空 VO 仍 FAILED |
| `backend/tests/unit/test_juxing_live_adapter_detail.py` | 新增：查询为空 → 7 个 NO_DATA 且 module complete；空 VO 但无“查询为空” → 仍 7 个 FAILED |

- **未修改共享代码、其他平台 Adapter、契约、数据库结构、任务状态机或 70 上限。**
- 影响范围：仅磁力聚星直播 index 模块的“平台明确无数据”分类。
- 验证：unit **444 passed**、contract **43 passed**、targeted integration **44 passed**、真实 70 任务 **0 FAILED**；补采后 9 位 index 显示 NO_DATA（如 userId `126294140` 的 `index` 模块状态 NO_DATA、profile complete true）。
- 未提交 Git（工作区含其他会话改动；本轮未 commit/push/merge）。

### 4.4 原始失败（非代码缺陷）

- page 4 首位候选详情页动作等待 20s 超时导致 60/70 FAILED；重试/继续后正常，最终该候选及后续完成 70。
- 已保留原 60 位数据；继续/补采均在同一 root，未重建任务。

## 5. 测试用例结果

| ID | 结果 | 证据/说明 |
|---|---|---|
| T01 Git/环境 | PASS | 分支/HEAD 只读检查；未 reset/clean/rebase；API/前端/DB/Redis/Temporal 均正常 |
| T02 契约/时尚 | PASS | 8 模块/70 字段；前端时尚可选；真实日志 contentTagIdList 675/735-739 |
| T03 70/71 | PASS | 前端 70 提交成功；71 返回 422 |
| T04 前端真实创建 | PASS | 前端提交 → root `0b37dedf…`；见 before-submit 截图 |
| T05 计划参数 | PASS | DB plan：fashion、target 70、capability v2 |
| T06 调度 | PASS | root unit `unit-local-mac-03-juxing`；unit LEASED→READY；worker generation 25 |
| T07 首页筛选 | PASS | page 1 请求带 675/735-739；40 候选起可核 |
| T08 跨页/去重 | PASS | page 1–4 digest 不变；80 唯一、0 重复；visited cursors 4 页 |
| T09 有效判定 | PASS | 70 valid、0 invalid/failed；10 个未使用候选未计入 |
| T10 8 模块/NO_DATA | PASS | 70×8 模块；4900 字段 0 FAILED；修复后 10 位 index NO_DATA（9 位补采 + 1 位继续阶段） |
| T11 关联/隔离 | PASS | 70 task_creators；79 快照/70 creator；projection 0/70；Xingtu current 0；schedule 0/70 |
| T12 进度/计数 | PASS | UI 70/70、资料完整 70；DB 70/70 |
| T13 checkpoint/继续 | PASS | 3 attempts；checkpoint rev 3909；cursor/visited/候选完整；继续/补采可恢复 |
| T14 失败保留/续采 | PASS | 60/70 失败后原 60 保留；继续只补 10；补采只补 9；未重采 61 |
| T15 70 终态 | PASS | 70/70、profile 70/70、pipeline true、COMPLETED、0 失败 |
| T16 前端 | PASS | 任务页/达人库/详情（正常 84.22、修复达人 NO_DATA） |
| T17 第 7 页 | PASS（未需要） | 任务 4 页完成；只读 page 7/8 HTTP 200/20 行/0 重复；未提升 page 上限 |
| T18 回归 | PASS | unit 444、contract 43、targeted integration 44、frontend 123、build、mypy 44；聚星短视频/星图直播页面加载；71 拒绝 |

## 6. 数据库/API/前端证据

- 任务：
  - root `0b37dedf…`，`valid_count=70`、`profile_complete_count=70`、`pipeline_complete=true`、`failure_reason=null`。
  - 3 attempts 同一 root：`28513e35…`（初次）、`8a04e306…`（继续）、`b88e78ac…`（补采）。
  - checkpoint rev 3909，candidate 80，done 70，pending 10，valid 70，invalid/failed 0。
- 达人/快照：
  - `task_creators` 70，全部 valid，70 distinct creator；latest_snapshot_id 70 distinct。
  - `creator_snapshots` 79 行、70 distinct creator（70 初始 + 9 补采）。
  - `creator_live_current` 70，profile/pipeline complete，最新时间 01:02–01:32。
- 隔离：
  - 选中 70 位 `platform_creators.projection` 全空（0/70）。
  - 选中 70 位 `douyin_xingtu_creator_current` 0 行。
  - 选中 70 位 `creator_update_schedule` 0 行。
  - 未修改执行单元/队列/Profile/并发/账号绑定。
- API/UI：
  - 任务页 `已完成`、`有效入库 70 / 目标 70`、`资料完整 70 / 全部完整`、`失败步骤 0`。
  - 正常达人 `648737405`（爱你不后悔）详情 index 84.22，8 模块完整。
  - 查询为空达人 `126294140`（燕青妹妹~小琳琳）补采后 index NO_DATA、无“采集失败”，8 模块存在，profile/pipeline complete。
  - 截图：[失败态](../evidence/assets/LIVE-02H/live02h-failed-task.png)、[最终任务](../evidence/assets/LIVE-02H/live02h-final-task.png)、[修复达人详情](../evidence/assets/LIVE-02H/live02h-repaired-index-section.png)、[正常达人详情](../evidence/assets/LIVE-02H/live02h-normal-index-section.png)、[提交前 70/时尚](../evidence/assets/LIVE-02H/live02h-before-submit.png)。

## 7. 回归与残余

### 回归

- 后端 unit **444 passed**；contract **43 passed**；targeted integration（live library + engine）**44 passed**；mypy **44 files no issues**；changed files Ruff/format 通过。
- 前端 **123 passed / 11 files**；build 通过（bundle 大小警告非失败）。
- 71 直播目标仍 **422**。
- 聚星短视频详情页、星图直播详情页、任务中心正常加载；未改其他平台 Adapter/短视频主流程。
- 未新增数据库迁移、执行单元、队列、Profile 或定时更新。

### 残余

1. **平台明确无数据**：10 位达人 index NO_DATA（其中 9 位补采后确认）；1236 个字段总体 NO_DATA；均按平台真实状态展示，不补 0。
2. 任务只使用 4 页；第 7 页及之后未在任务中触发。只读探测 page 7/8 正常，但未改已验证的 6 页契约边界。
3. 初次任务在 page 4 首位候选遇到一次 **BROWSER_ACTION_FAILED**（20s 页面动作超时），继续后恢复；非本次 index 修复引入。
4. `creator_snapshots` 为 79 行（70 位 + 9 份补采），不是 70；这是不可变历史保留，latest/达人 70。
5. 工作区含 LIVE-02G/LIVE-03 未提交改动；**本轮未 commit/push/merge**。修复只涉及 Juxing 直播 Adapter/测试。
6. 未重新执行巨量星图 70 全量；本次未修改星图共享业务逻辑。
7. 任务页“首次完成时间”保留第一次 `PARTIAL_COMPLETED` 的 01:02；最终 `COMPLETED` 以状态与“最近更新 01:32”为准，UI 同时展示“上次重试 01:22 更新 9 位”。

## 8. 最终结论

**PASS**。

- 从真实前端创建、真实磁力聚星「时尚」筛选、4 页候选、80 唯一候选、70/70 有效达人、70/70 资料完整、COMPLETED、0 FAILED 字段。
- 初始 60/70 失败后，保留原数据并通过“继续采集”补数量；再通过“补采缺失字段”修复 9 位 index 平台无数据；同一 root，无重建 70 任务、无重采已完成达人。
- 发现并最小修复了“平台查询为空被误判 FAILED”的真实缺陷；未扩大范围，其他业务回归通过。
- 残余均为平台明确无数据、未使用的第 7 页边界、不可变补采快照与未提交工作区，不影响 70 位采集结论。
