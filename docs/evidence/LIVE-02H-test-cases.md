# LIVE-02H 磁力聚星直播 70 位真实采集测试用例

日期：2026-11-06
目标：磁力聚星 / 直播广场 / 内容分类「时尚」/ 70 位有效达人
方式：Playwright MCP + Chrome 从前端创建任务并观察；数据库/日志只读核对
判定：PASS / FAIL / BLOCKED

## 判定通用规则

- **PASS**：用例预期行为被真实数据/日志/页面证据证实，且无越界修改。
- **FAIL**：产品行为与预期不符，且属于可定位/可修复的代码或数据缺陷。
- **BLOCKED**：外部条件（平台候选不足、登录/验证、网络、环境）导致无法完成，且不能在不放宽标准的情况下继续。
- 不以“请求成功”“候选 70 个”“页面显示 70”“数据库有 70 位历史达人”替代“本次 70 位有效入库”。

| ID | 用例 | 预期 | PASS 标准 | FAIL/BLOCKED 条件 |
|---|---|---|---|---|
| T01 | Git/工作区安全 | 分支/HEAD 明确；不 reset/clean/checkout 覆盖/stash pop/rebase；保留 LIVE-02G/03 | 只读检查完成；未执行破坏性 Git | 任何覆盖/清理他人改动 → FAIL |
| T02 | 契约与筛选能力 | `juxing-live-square-v3`；8 模块/70 字段；时尚选项可用 | API catalog 返回 8 模块；真实页面可选时尚 | 契约缺模块/时尚不可用 → FAIL/BLOCKED |
| T03 | 70 上限与 71 拒绝 | 前端可填 70；71 被拒绝 | 70 提交进入队列；71 返回 422 | 70 被拒/71 被接受 → FAIL |
| T04 | 前端真实创建 | 从前端选聚星/直播/时尚/70 并提交 | 页面提交成功，任务中心出现任务 | 只能 API 创建或页面失败 → FAIL |
| T05 | 计划参数 | 计划含 `live_content_category=fashion`、target=70 | DB/API plan 与 UI 摘要一致 | 条件丢失/被改写 → FAIL |
| T06 | 调度到执行单元 | 任务由 `unit-local-mac-03-juxing` 执行 | 队列消费者/心跳/任务 unit 一致 | 调度到错误 unit/长时间无消费者 → FAIL/BLOCKED |
| T07 | 首页筛选请求 | 真实请求包含 `contentTagIdList` 675/735-739，pathSource=has_filter_live | 网络/日志/响应可证；首页候选读取 | 请求未带筛选 → FAIL |
| T08 | 跨页与去重 | 第 2 页起筛选不变；跨页 0 重复；必要时继续 | checkpoint 页码前进；候选 userId 去重；筛选一致 | 筛选丢失/重复计数/游标错误 → FAIL |
| T09 | 有效候选人判定 | 有效=既有标准（详情可采集/有效身份），非“访问过” | 有效数=入库有效达人；无效候选人单独记录 | 访问数冒充有效数 → FAIL |
| T10 | 8 模块采集 | 每位达人 8 模块；NO_DATA 不误判 FAILED；局部失败可记录 | 快照模块存在/状态合理；字段状态区分 | 模块无故跳过/NO_DATA 导致全任务失败 → FAIL |
| T11 | 数据关联与隔离 | 身份/快照/current/task 关联；不覆盖其他场景 | 快照数=有效达人；current 最新；projection/星图表不变 | 关联错误/跨场景污染 → FAIL |
| T12 | 进度与计数 | 进度/有效/目标/入库一致 | DB/API/UI 计数一致 | 计数漂移 → FAIL |
| T13 | checkpoint/继续 | checkpoint 记录页/候选/进度；可继续 | checkpoint 完整；继续入口可用 | checkpoint 丢失/无法继续 → FAIL |
| T14 | 失败保留与续采 | 失败不清已有有效数据；不重复已采 | 失败后有效快照保留；续采只补剩余 | 清空/重采全部 → FAIL |
| T15 | 70 位终态 | 70 位有效达人入库；终态 COMPLETED | 有效=70、唯一=70、快照=70、COMPLETED | 不足 70/终态不符 → FAIL/BLOCKED（平台候选不足） |
| T16 | 前端展示 | 任务中心/达人库/直播详情正确 | 数量、状态、详情关键字段可见 | 页面错误/空白 → FAIL |
| T17 | 第 7 页边界（如需） | 如实记录；不以假设放宽 | 若访问到第 7 页，记录请求/响应/候选/失败 | 未经验证擅自提升 page 上限 → FAIL |
| T18 | 必要回归 | 聚星短视频、星图共享、任务中心、71、隔离 | 自动化/小样本/页面检查通过 | 回退 → FAIL |

## 本轮记录栏

| ID | 状态 | 证据 |
|---|---|---|
| T01 | PASS｜分支/HEAD 只读；无 reset/clean/rebase；服务正常 | 见 [LIVE-02H 验收](LIVE-02H-acceptance.md) |
| T02 | PASS｜8 模块/70 字段；前端时尚可选；真实请求 675/735-739 | 见 [LIVE-02H 验收](LIVE-02H-acceptance.md) |
| T03 | PASS｜前端 70 提交成功；71 返回 422 | 见 [LIVE-02H 验收](LIVE-02H-acceptance.md) |
| T04 | PASS｜前端创建 root `0b37dedf…`；见提交前截图 | 见 [LIVE-02H 验收](LIVE-02H-acceptance.md) |
| T05 | PASS｜plan fashion、target 70、capability v2 | 见 [LIVE-02H 验收](LIVE-02H-acceptance.md) |
| T06 | PASS｜`unit-local-mac-03-juxing`；LEASED→READY；worker gen 25 | 见 [LIVE-02H 验收](LIVE-02H-acceptance.md) |
| T07 | PASS｜page 1 请求带 675/735-739；40 候选起可核 | 见 [LIVE-02H 验收](LIVE-02H-acceptance.md) |
| T08 | PASS｜page 1–4 digest 不变；80 唯一、0 重复；4 页 | 见 [LIVE-02H 验收](LIVE-02H-acceptance.md) |
| T09 | PASS｜70 valid、0 invalid/failed；10 个候选未使用未计数 | 见 [LIVE-02H 验收](LIVE-02H-acceptance.md) |
| T10 | PASS｜70×8 模块；4900 字段 0 FAILED；10 位 index NO_DATA（9 位补采 + 1 位继续阶段） | 见 [LIVE-02H 验收](LIVE-02H-acceptance.md) |
| T11 | PASS｜70 task_creators；79 快照/70 creator；projection 0/70；Xingtu current 0；schedule 0/70 | 见 [LIVE-02H 验收](LIVE-02H-acceptance.md) |
| T12 | PASS｜UI 70/70、资料完整 70；DB 70/70 | 见 [LIVE-02H 验收](LIVE-02H-acceptance.md) |
| T13 | PASS｜3 attempts 同 root；checkpoint rev 3909；cursor/visited/候选完整 | 见 [LIVE-02H 验收](LIVE-02H-acceptance.md) |
| T14 | PASS｜60/70 失败保留；继续只补 10；补采只补 9；未重采 61 | 见 [LIVE-02H 验收](LIVE-02H-acceptance.md) |
| T15 | PASS｜70/70、profile 70/70、pipeline true、COMPLETED、0 失败 | 见 [LIVE-02H 验收](LIVE-02H-acceptance.md) |
| T16 | PASS｜任务页 70/70；正常详情 84.22；修复达人 NO_DATA；达人库/详情 | 见 [LIVE-02H 验收](LIVE-02H-acceptance.md) |
| T17 | PASS（未需要）｜任务 4 页完成；只读 page 7/8 200/20/0 dup；未改 page 上限 | 见 [LIVE-02H 验收](LIVE-02H-acceptance.md) |
| T18 | PASS｜unit 444、contract 43、targeted integration 44、frontend 123、build、mypy 44；71 422；聚星短视频/星图直播页面 | 见 [LIVE-02H 验收](LIVE-02H-acceptance.md) |

## 执行结论

**PASS**：真实 70/70 有效、70/70 资料完整、COMPLETED、0 FAILED 字段；初始 60/70 失败后同一 root 继续并补采 9 位 index；仅修复磁力聚星直播 index 查询为空误判，未改共享逻辑。
