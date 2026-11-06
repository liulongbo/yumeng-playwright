# LIVE-03-70 测试用例：巨量星图直播「时尚」70 位单任务

执行方式：Playwright MCP + Chrome 从产品前端创建任务。  
状态：待执行 / PASS / FAIL / BLOCKED / 部分。

| ID | 用例 | 预期/通过标准 | 证据 | 状态 |
|---|---|---|---|---|
| T01 | 前端时尚创建 | 巨量星图/直播广场/内容类型时尚/无关键词/目标 70；提交成功得到任务 ID | 截图/URL | PASS |
| T02 | 目标 70 传递 | 需求与 plan 的 target_count=70；前端不截断；后端接受 | 任务详情/DB | PASS |
| T03 | 平台隔离 | plan 仅含 star 平台与 fashion；不含聚星/其他分类字段 | DB plan | PASS |
| T04 | 执行单元分配 | 任务归属 `unit-local-mac-02`；无跨单元抢占 | DB/任务页 | PASS |
| T05 | Chrome 时尚生效 | 真实列表请求携带时尚映射 `live_tag_content_v2_level_one=[10719]`；候选来自时尚结果 | 请求/候选 | PASS（plan+4页digest+逐请求校验+70/70 content_type=时尚） |
| T06 | 第一页候选 | 第 1 页 20 条（平台默认）且有有效/无效区分 | checkpoint/DB | PASS（第1页20条） |
| T07 | 后续分页 | 访问第 2 页及以后；每页 20 条；按需继续直至 70 或耗尽 | checkpoint | PASS（4页/80候选，目标70后停） |
| T08 | 筛选跨页 | 每次翻页/恢复请求仍携带时尚，不回落不限 | 请求/契约校验 | PASS（4页digest一致） |
| T09 | 跨页去重 | 跨页 `platform_creator_id` 0 重复；重复不重复计数 | checkpoint/DB | PASS（0重复） |
| T10 | 详情字段 | LIVE-03 六模块随采集执行；字段/状态/单位/周期结构化入库 | 快照 | PASS（6模块，0 FAILED） |
| T11 | 类型/口径隔离 | 不限/游戏/电商/其他；30/90；flow/star 不互相覆盖 | 快照 | PASS（类型/30/90/calibre分键） |
| T12 | 缺失/局部失败 | 无数据/不适用/0/失败可区分；单模块失败不误判整达人 | 快照/日志 | PASS（0 FAILED；NO_DATA按契约） |
| T13 | checkpoint | 页游标、候选、模块、计数持久化；恢复不丢 | DB | PASS（cursor5/visited 2-4） |
| T14 | 失败继续 | 若中断，保留已有效达人，继续原任务而非新任务/重头 | 任务/DB | PASS（预算continue+retry，同一任务） |
| T15 | 有效计数 | valid=70 为本次任务实际有效并关联的达人；非候选/访问数 | DB/任务页 | PASS（70 valid/70 complete） |
| T16 | 入库/快照 | 70 位 task_creators 有效；70 份 live 快照；current 70；快照/达人关联正确 | SQL | PASS（70 latest/70 current；71历史含1中断） |
| T17 | 任务状态 | QUEUED→COLLECTING→COMPLETED；进度/计数/终态一致 | 任务中心/API | PASS（COMPLETED；failed 0） |
| T18 | 前端展示 | 任务结果 70 位；直播达人库/详情可打开；LIVE-03 五模块展示 | 截图 | PASS（任务页/达人详情截图） |
| T19 | 短视频回归 | 短视频契约/Adapter/任务行为未变；自动化通过；必要时小样本真实任务 | 测试/证据 | PASS（自动化+既有真实证据；未改短视频） |
| T20 | 聚星隔离 | 聚星契约/Adapter/任务未变；聚星数据不被写入/混用 | 测试/SQL | PASS（聚星集成通过；未改聚星） |
