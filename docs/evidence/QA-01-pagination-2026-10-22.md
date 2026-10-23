# QA-01 target=21 分页真实验收（2026-10-22）

> 范围：当前产品前端 + 当前 v11 契约 + 当前 Collection Worker，keyword-only、target=21；真实平台分页、跨页去重、持久化、前端“查看更多达人”。未改 Schema/迁移/Workflow/数据库。

## 1. 任务与终态

| 项 | 值 |
|---|---|
| task_id | 829d4568-078d-486c-8702-12b2c9e397e6 |
| 创建时间 | 2026-10-22T12:49:44+08:00 |
| 完成时间 | 2026-10-22T14:12:55+08:00 |
| 状态 | PARTIAL_COMPLETED |
| failure_reason | PROFILE_SCOPE_INCOMPLETE |
| counts | target 21、discovered 40、valid 21、profile 12、featured 20、failed 0 |
| task_creators | 21 |
| creator_snapshots | 21 |
| featured_collections | 42（COMPLETE/INCOMPLETE 混合） |

## 2. 分页证据

| 项 | 值 |
|---|---|
| cursor | 3 |
| visited_cursors | [null, "2"] |
| processed_operations | 3 个（首轮 page1、LEASE_LOST 后重扫、page2） |
| candidates | 40，unique 40，first_position 唯一 |
| valid_candidates | 21 |
| page2 候选位置 | first_position 20–39 |
| page2 首位有效候选 | position 20，platform_creator_id 7503858807357833243，valid=true |
| failure_counts | LEASE_LOST: 1 |
| observed_requests/responses | 1715 / 1715 |
| duplicate_request_count | 0 |
| exhausted | false（目标达成即停止，未到平台终点） |
| search_stop_reason | null |
| search 契约健康 | v11 search ENABLED，consecutive_failures=0 |

结论：

- page=2 真实发出并取得 20 位新候选（position 20–39）；两页 40 位 ID 全唯一。
- 第 21 位有效达人来自 page2（position 20）；valid_count=21 达到目标后停止，未继续请求 page3。
- 40 位候选均有唯一 first_position；21 位有效达人均有 task_creators 行与已发布快照。
- 未出现 SEARCH_RESPONSE_FAILED、未出现跨页重复计数。

## 3. 中断与恢复

- 采集中途发生一次 LEASE_LOST；Workflow 自动重试，单元重新获取租约。
- 由于 resume_supported=false，重试从 page1 重扫；检查点保留已见身份和 21 位有效数据，随后 page2 仍成功取得。
- failure_counts=LEASE_LOST:1 如实保留；没有把重扫误报为平台耗尽，也没有重复 valid_count。
- 该场景可作为 PG-08 的真实中断/恢复证据；根因未诊断（非本轮范围）。

## 4. 前端展示

- 任务页初始显示 20 位可查看；点击“查看更多达人”后显示 21 位。
- 页面计数：已发现 40、有效入库 21/21、资料完整 12、精选完整 20、失败步骤 0。
- 第 21 位达人可打开并显示“已发布快照”。
- 截图：[PG-03 21 位任务](assets/qa01/PG-03-task-21.png)。
- 页面计数与 DB/API 一致（DB task_creators=21、snapshots=21；API final counts 同上）。
- 浏览器 Console：0 Errors、0 Warnings；Network 未发现失败 API 行（51 条静态请求被 MCP 默认省略）。

## 5. 结论与边界

- 当前产品端到端已证明：target=21 能跨越单页 20 位，page2 真实候选、跨页去重、持久化、前端加载更多均正确。
- PARTIAL_COMPLETED 来自 PROFILE_SCOPE_INCOMPLETE（profile 12/21），不是分页失败；分页验收以 valid_count=21、40 候选、21 快照、21 前端为准。
- target=41/第 3 页仍未验证；page_fetch_max_verified=2，不能据此宣称 41 可完成。
- 采集耗时约 83 分钟（含一次 LEASE_LOST/重扫），成本较高；后续分页复测应优先复用现有数据/证据。
- MCP 轮询在 12:55 遇到一次空响应 JSON 解析错误退出，任务本身未受影响；改用只读 DB 轮询至终态。属测试工具健壮性问题，不是业务故障。
- 未提交 Git。
