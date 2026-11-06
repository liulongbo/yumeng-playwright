# LIVE-02H：磁力聚星直播广场单任务 70 位真实采集验收

状态：**已完成（PASS）**
建立时间：2026-11-06T00:10:00+08:00
最近更新：2026-11-06T01:42:00+08:00
是否验收：是（真实 70/70、资料完整 70/70、COMPLETED、0 FAILED）
关联：[LIVE-02](LIVE-02.md)、[LIVE-02F](LIVE-02F.md)、[LIVE-02G](LIVE-02G.md)、[LIVE-02G 验收](../evidence/LIVE-02G-acceptance.md)、[测试用例](../evidence/LIVE-02H-test-cases.md)

## 目标与边界

从项目前端真实创建一次磁力聚星「直播广场」任务：

- 平台：磁力聚星
- 场景：直播广场（`live_square`）
- 筛选条件：内容分类 **时尚**（不得在执行中擅自放宽/取消）
- 目标：**70 位有效达人**
- 方式：Playwright MCP + Chrome 操作用户前端，不使用后端 API 代替完整业务测试。

验证完整链路：前端创建 → 任务中心 → 磁力聚星执行单元 → 真实直播广场筛选 → 跨页候选 → 逐达人 8 模块采集 → 标准化/入库 → 进度/终态 → 达人库/直播详情展示。

不修改：执行单元/队列/并发/Profile/线路、限额 70、短视频与星图主流程、任务中心状态机、无关数据库结构、其他平台 Adapter。发现缺陷只做最小必要修复并回归。

## 环境基线（创建任务前）

- 分支 `1105-live02g`，HEAD `d9f263e`；工作区含 LIVE-02G 与并发 LIVE-03 未提交改动。**不执行 reset/clean/checkout 覆盖/stash pop/rebase**。
- API `8000`、前端 `5173`、PostgreSQL `55432`、Redis `56379`、Temporal `57233` 均在监听。
- `unit-local-mac-02`、`unit-local-mac-03-juxing` 均 `READY`、`browser_stopped=true`；无在途任务。
- 磁力聚星执行单元 worker `0b96d5f3…`（PID 84855）心跳新鲜；Juxing 契约 `juxing-live-square-v3`，8 模块、70 字段。
- 当前 Juxing live 达人 88 位、直播快照 131 份；最近任务均终态。
- Chrome/聚星会话此前已真实访问 9104/451066；本轮创建任务前再次检查前端与任务中心可用。

## 验收清单

- [x] T01 Git/环境只读检查通过，无破坏性操作。
- [x] T02 契约 v3、8 模块、70 字段；内容分类「时尚」能力可用。
- [x] T03 前端目标 70 可提交；71 仍被拒绝。
- [x] T04 前端真实创建任务成功（非 API 替代），任务进入任务中心。
- [x] T05 计划包含 `live_content_category=fashion`、target=70；任务详情/任务中心展示正确。
- [x] T06 任务调度到 `unit-local-mac-03-juxing`，队列/心跳正常。
- [x] T07 真实浏览器应用「时尚」，请求 `contentTagIdList` 含 675/735-739，首页候选正确。
- [x] T08 跨页采集正常，每页筛选保持不变，跨页去重正确。
- [x] T09 有效/无效候选人判定符合既有标准，不把仅访问过算作有效。
- [x] T10 8 模块逐达人采集；局部 NO_DATA 不误判 FAILED，局部失败不拖垮整任务。
- [x] T11 达人身份、快照、current、任务关联正确；不覆盖其他达人/场景。
- [x] T12 任务进度、有效数、目标数、入库数一致。
- [x] T13 checkpoint/分页游标/继续采集机制可用。
- [x] T14 失败时保留已采数据；不重复采集已有效达人。
- [x] T15 最终 70 位有效入库，任务终态与结果一致。
- [x] T16 前端任务中心/达人库/直播详情展示正确。
- [x] T17 如需第 7 页及之后，如实记录平台表现；不以假设放宽分页边界。
- [x] T18 磁力聚星短视频、星图共享逻辑、任务中心/限额/隔离必要回归通过。

## 测试用例

完整 18 条（含 PASS/FAIL/BLOCKED 判定标准、证据记录栏）见 [LIVE-02H 测试用例](../evidence/LIVE-02H-test-cases.md)。

## 实现/执行记录

- 2026-11-06T00:10：建立卡片；完成只读环境基线；尚未创建 70 任务。
- 2026-11-06T00:10：通过 Playwright MCP + Chrome 在真实前端 `创建采集任务` 页选择磁力聚星 / 直播广场 / 内容分类「时尚」/ 目标 70，提交成功；真实任务 `0b37dedf-3b98-409d-aab0-754dbb670c76`。
- 2026-11-06T00:10–00:11：P1 计划确认 `live_content_category=fashion`、`target_count=70`、`juxing-live-square-capability-v2`；调度至 `unit-local-mac-03-juxing`；真实搜索日志为 `path_source=has_filter_live`，`contentTagIdList=[675/735-739]`。
- 2026-11-06T00:14：任务 COLLECTING；已发现 20 候选（第 1 页），8 位有效，所有已完成候选均含 8 模块；初检无异常。
- 2026-11-06T00:22：发现真实缺陷——部分时尚达人的 `starRadarGraph/starTrendGraph` 返回 HTTP 200 + `errMsg="查询为空"` + `starRadarGraphVO/starTrendGraphVO=null`，Adapter 却抛出 `JUXING_LIVE_RADAR_SCHEMA/TREND_SCHEMA`，把平台 NO_DATA 误判为 FAILED（当时 2/21 位、14 字段）。原始响应与 checkpoint 证据保存在 `.runtime/live02h/index-failure/`。
- 2026-11-06T00:23：完成最小修复：仅修改 `backend/src/xingtu/juxing_live_adapter.py` 的 `_radar/_trend`，当平台明确 `errMsg=查询为空` 且 VO 为 null 时按 NO_DATA 处理并保留原始 payload；真正的 schema 异常仍 FAILED。新增/更新 `test_juxing_live_adapter_detail.py` 两条测试（查询为空→7 个 NO_DATA 且 module complete；空 VO 无查询为空→仍 7 个 FAILED），22+9 条相关测试通过；未改共享代码/其他平台。
- 2026-11-06T00:32：原任务仍由旧 worker 执行（未热重启，避免中断），已 35 位有效；失败字段累计 28（4 位达人，均为同一 index 查询为空根因）。计划：原任务终态后只重启磁力聚星 worker 加载修复，再在原任务上通过前端“补采缺失字段”恢复，不重建 70 任务、不重采其余达人。
- 2026-11-06T01:03–01:32：初次任务在 60/70 因 page 4 首位候选 `BROWSER_ACTION_FAILED` 失败；前端继续同一 root 补 10 位至 70/70；只重启磁力聚星 worker 加载修复；前端补采 9 位 index 查询为空达人；最终 COMPLETED、70/70、资料完整 70/70、0 FAILED。

## 验证证据

- 验收报告：[LIVE-02H 验收](../evidence/LIVE-02H-acceptance.md)
- 测试用例结果：[LIVE-02H 测试用例](../evidence/LIVE-02H-test-cases.md)
- 真实任务：`0b37dedf-3b98-409d-aab0-754dbb670c76`；3 次 attempt（初次 `28513e35…`、继续 `8a04e306…`、补采 `b88e78ac…`），同一 root。
- 最终结果：valid 70/70、profile complete 70/70、pipeline true、COMPLETED、0 FAILED 字段；4 页、80 唯一候选、0 重复；79 快照/70 distinct creator；task_creators 70；current 70。
- 隔离：选中 70 位 projection 0/70、Xingtu current 0、schedule 0/70；无迁移/新单元/队列/Profile。
- 截图：[提交前 70/时尚](../evidence/assets/LIVE-02H/live02h-before-submit.png)、[失败态 60/70](../evidence/assets/LIVE-02H/live02h-failed-task.png)、[最终任务](../evidence/assets/LIVE-02H/live02h-final-task.png)、[修复达人详情](../evidence/assets/LIVE-02H/live02h-repaired-index-section.png)、[正常达人详情](../evidence/assets/LIVE-02H/live02h-normal-index-section.png)。
- 原始证据：`.runtime/live02h/index-failure/`（查询为空原始响应/checkpoint 失败字段）、`.runtime/live02h/monitor.log`、`.runtime/live02h/screens/`。
- 自动化：unit **444**、contract **43**、targeted integration **44**、frontend **123**、build 通过、mypy **44**；71 返回 422；聚星短视频/星图直播页面加载。
- 修复：`backend/src/xingtu/juxing_live_adapter.py` + `backend/tests/unit/test_juxing_live_adapter_detail.py`；仅 Juxing live index 查询为空分类，无共享代码。

## 交接信息

- 当前阶段：已完成（PASS）；未提交 Git。
- 结论：真实 70/70 有效、70/70 资料完整、COMPLETED、0 FAILED；初始 60/70 失败后同一 root 继续，随后补采 9 位 index；未重建 70 任务、未重采已完成达人。
- 残余：10 位达人 index 为平台明确 NO_DATA；任务只使用 4 页（只读 page 7/8 正常但未改 6 页契约）；初次 page 4 有一次 BROWSER_ACTION_FAILED，继续后恢复；79 快照为 70 位 + 9 份补采；工作区含并发 LIVE-03 改动，未 commit/push。
- 约束：不改共享核心/其他平台；不提交/合并/推送；不清理历史数据。

## 状态历史

- 2026-11-06T00:10：待办 → 进行中。
- 2026-11-06T01:03：初次任务 60/70 `FAILED / BROWSER_ACTION_FAILED`；保留 60 位。
- 2026-11-06T01:05：前端继续同一 root；01:21 达 70/70，`PARTIAL_COMPLETED`（9 位 index 未完整）。
- 2026-11-06T01:22：前端补采 9 位；01:32 **COMPLETED** 70/70、资料完整 70/70。
- 2026-11-06T01:42：缺陷最小修复、回归、证据与卡片回写完成；判定 PASS。
