# 巨量星图直播广场「时尚」70 位单任务真实验收报告

日期：2026-11-06（Asia/Shanghai）  
结论：**PASS**（含 1 项最小恢复修复，已复测）  
任务卡：[LIVE-03-70](../tasks/LIVE-03-70.md)

## 11.1 任务信息

| 项 | 值 |
|---|---|
| 真实任务 ID | `149be43e-320f-48bb-a9a9-739d90e631e9` |
| Git 分支 / HEAD | `1105-live02g` / `d9f263e`（工作区含 LIVE-02G/LIVE-03 未提交成果，未提交/未推送） |
| 测试环境 | 本机开发栈；API `127.0.0.1:8000`、Web `127.0.0.1:5173`、Postgres `55432`、Redis `56379`、Temporal `57233` |
| 平台 / 场景 | 巨量星图 / 直播广场（`live_square`） |
| 筛选条件 | 内容类型 = 时尚；`live_content_type=["fashion"]`；无关键词/达人 ID |
| 目标数量 | 70 |
| 实际执行单元 | `unit-local-mac-02`（巨量星图） |
| 创建方式 | Playwright MCP + 系统 Chrome，从产品前端创建；**非后端接口模拟** |
| 创建 / 首次终态 / 最终更新 | 00:13:17 / 03:16:27（PARTIAL）/ 03:22:19（COMPLETED） |
| 最终任务状态 | **COMPLETED**，failure_reason=null |
| 执行段 | segment 0（00:13）、segment 1（02:14 预算 continue）、segment 2（03:20 retry backfill） |

证据：[创建表单](assets/LIVE-03-70/fashion-70-form.png)、[排队任务页](assets/LIVE-03-70/fashion-70-queued.png)、[部分完成/补采按钮](assets/LIVE-03-70/fashion-70-partial.png)、[最终完成页](assets/LIVE-03-70/fashion-70-completed.png)。

## 11.2 实际采集统计

| 指标 | 实际结果 |
|---|---|
| 目标数量 | 70 |
| 筛选条件 | 时尚（跨 4 页条件 digest 一致） |
| 实际有效达人 | **70** |
| 资料完整达人 | **70**（profile_complete=70 / pipeline_complete=70） |
| 成功入库达人 | **70**（70 task_creators，70 个 latest_snapshot_id） |
| 发现候选 | **80**（4 页 × 20） |
| 采集达人页面 | **70**（每位有效达人一次详情；`navigation_count=75` 含 4 次检索页/导航） |
| 重复候选 | **0**（80 个 platform_creator_id 全部唯一） |
| 失败/无效达人 | **0**（failed_count=0；70 valid 全部 profile complete） |
| 未访问候选 | 10（第 4 页达到 70 后停止；`exhausted=false`，非候选耗尽） |
| 快照数量 | **71 行历史 / 70 位唯一达人 / 70 个 latest**；1 行为预算中断批次被后续 complete 快照取代 |
| 直播 current | **70**（profile_complete=70、pipeline_complete=70） |
| 任务恢复次数 | **2**：02:14 预算暂停 continue；03:20 PARTIAL 后 retry backfill（同一任务） |
| 最终任务状态 | **COMPLETED** |

分页证据：
- 第 1/2/3/4 页各 20 条，80 个候选 0 重复；
- checkpoint `cursor=5`、`visited_cursors=[None,"2","3","4"]`、`exhausted=false`；
- 四页 `conditions_digest=d6b1209035243be03c7b2eb4432cfefe4dfc83e73fa0ceb083a3a1494a595ac8` 完全一致；
- plan 仅 `live_content_type=["fashion"]`，未静默取消/放宽；平台请求由 Adapter 的 `expected_xingtu_live_request` 校验（LIVE-02F 已实测映射 `live_tag_content_v2_level_one=[10719]`）；
- 入库后 70/70 达人的 `basic.content_type` 实测均为「时尚」，不是「不限」或其他分类。

## 11.3 LIVE-03 字段结果（70 个 latest 快照）

| 模块 | COLLECTED | NO_DATA | FAILED/UNPARSED | 说明 |
|---|---:|---:|---:|---|
| live | 821 | 369 | 0 | 17 个既有直播指标 |
| basic | 655 | 255 | 0 | 13 字段，含抖音号/内容标签/商单类型/介绍 |
| live_pricing | 70 | 0 | 0 | 70 位均 COLLECTED；服务 146 条：per_day 67、per_hour 75、per_goods 4 |
| live_analysis | 289 | 341 | 0 | 月历/近15场/场次明细；49 位有数据，21 位 NO_DATA |
| live_audience | 110 | 450 | 0 | 粉丝画像按类型 110 COLLECTED；观众画像 0（既有受限项） |
| live_overview | 190 | 160 | 0 | 分类型/周期/口径；0 FAILED |

分类型覆盖（概览）：
- 不限：49 COLLECTED / 21 NO_DATA；
- 电商带货：16 / 54；
- 游戏直播：6 / 64；
- 其它直播：49 / 21。

分类型覆盖（分析）：
- 不限 49、电商 16、游戏 6、其它 49 有 calendar/latest；`analysis.rooms` 49 位有数据；其余为真实 NO_DATA。

受众粉丝画像：不限 49、电商 13、游戏 6、其它 42 有 COLLECTED；`live_crowd_type=1` 观众画像仍 0（见残余项）。

关键正确性：
- 0 FAILED / 0 UNPARSED 字段；21 位无直播数据达人按 NO_DATA 处理，未导致整达人失败；
- 概览按 `overview.{general,game,ecom,other}` 独立字段，calibre key 含 period/flow/star（如 `period_30_flow_1_star_0`），未混合；
- 区间/0/缺失原因沿 LIVE-03 语义；未把空数据写成 0；
- 付费报价按服务独立，按天/小时/商品不覆盖。

样本：
- 富数据达人 `7620474284346966052`：基本/报价/概览/分析/画像完整，96 场/10 页；详情页见 [rich creator](assets/LIVE-03-70/fashion-70-rich-creator.png)。
- 被中断后补采达人 `7623704992305643547`：补采后 6 模块完整；详情页见 [backfill creator](assets/LIVE-03-70/fashion-70-backfill-creator.png)。

## 11.4 异常与最小修复

### 现象

1. 02:14 达到 2 小时执行预算，任务 **PAUSED_BUDGET**；当时 49 valid/48 done/49 快照。
2. 按既有 `continue` 恢复为 segment 1，任务继续并达到 70 valid；03:16 以 **PARTIAL_COMPLETED** 结束，`profile_complete_count=69`，`failure_reason=MODULE_COLLECTION_FAILED`。
3. 检查发现 `7623704992305643547` 在 02:13 中断：只完成 `basic`，其余 5 模块未尝试；它已计入 valid，但任务 detail 的 `allowed_actions=[]`、`retry_plan.retryable_creator_count=0`，无法用补采按钮/retry 恢复。
4. 快照/current 均保留；问题不是数据丢失，而是 **已有效但缺少预期模块的中断达人不可重试**。

### 根因

`backend/src/xingtu/retry_policy.py::is_retryable` 只检查 `candidate.modules` 中**已存在**模块的 `complete`，不检查 checkpoint `profile_module_keys` 中**预期但缺失**的模块。中断发生在 basic 之后时，缺失模块根本不在 dict 中，因此被判为“不可重试”；`allowed_actions`/`retry_plan`/`requeue_for_retry` 均受影响。

### 最小修复

- `retry_policy.is_retryable(candidate, expected_modules=None)`：当 `expected_modules - candidate.modules` 非空时视为可重试；
- `retryable_creator_count`、`requeue_for_retry` 传入 `task.checkpoint.profile_module_keys`；
- `Repository.retryable` 增加可选参数；`Repository.command`、`product_queries.allowed_actions`/retry 逻辑传入预期模块；
- 新增单测：缺失预期模块可重试，现有 failed/complete/pending/invalid 行为不变。

修改文件：
- `backend/src/xingtu/retry_policy.py`
- `backend/src/xingtu/repository.py`
- `backend/src/xingtu/product_queries.py`
- `backend/tests/unit/test_retry_policy.py`

共享组件说明：retry policy 为两平台共享；本次只增加“缺失预期模块”判定，不改变现有 failed/incomplete 语义；新增保护性单测，unit/contract 487、product M3 integration 21、integration 135/1 均通过。

### 复测

- 重启 API 加载修复（任务已 PARTIAL 终态，无采集进程在跑；未丢数据）。
- `allowed_actions=['retry']`、`retry_plan={scope:backfill, incomplete_valid_count:1, retryable_creator_count:1}`。
- 对**同一任务**执行 retry（未新建任务）：03:20 进入 segment 2，仅补采 1 位；03:22 任务 **COMPLETED**，70 valid/70 profile complete，失败 0。
- 新快照 `057a7339…` 完整；旧中断快照 `3819894b…` 保留为历史；`task_creators.latest_snapshot_id` 指向新快照；current 70/70。
- 任务页显示「上次重试 03:20 · 更新了 1 位达人的资料；当前有效 70/70，资料完整 70」。

## 11.5 回归与隔离

| 项 | 结果 |
|---|---|
| 后端 unit + contract | **487 passed**（修复前 485，+2 retry 保护测试） |
| 后端 integration | **135 passed / 1 skipped** |
| product M3 integration | **21 passed** |
| 前端 | **123 passed** + `tsc -b` + `vite build` 通过 |
| 71 位上限 | API 422 `live target_count exceeds 70` |
| 短视频 | 未改短视频 Adapter/契约；自动化回归通过；复用既有真实 70 证据，未重跑全量 |
| 磁力聚星 | 未改聚星 Adapter/契约；integration（含聚星）通过；共享 retry 修复有保护测试 |
| 任务中心/执行单元 | 任务终态/重试正确；结束后 `unit-local-mac-02=READY`、无 active task |
| 数据库/快照 | 无迁移；历史快照保留；current 70 完整；未删除/重写数据 |

## 11.6 残余项

1. **10 个第 4 页候选未访问**：达到目标 70 后按现有停止逻辑结束；`exhausted=false`，不是候选耗尽，也不是失败。若需证明第 4 页耗尽，应另跑更高目标（但本次目标 70 已完成）。
2. **21 位达人分析/画像 NO_DATA**：平台对无直播数据达人返回空；按 LIVE-03 契约为完整 NO_DATA，不伪造 0。
3. **观众画像** `live_crowd_type=1` 仍为 0（LIVE-03 已记录的持久 profile UI 限制）；flow=0 替代口径未保存；逐场类型仅 latest 命中时登记。均为既有受限项，非本次引入。
4. **快照 71 行/70 位**：保留 1 份中断批次的 `NOT_ATTEMPTED` 历史快照（append-only，不删除历史）；70 个 latest/current 均 complete。
5. 本次为应用共享 retry 修复重启了 API（任务已终态，无采集中断）；未改数据库结构、执行单元、并发模型、Temporal/任务中心状态机。

## 11.7 结论

**PASS**。

单任务 `149be43e-320f-48bb-a9a9-739d90e631e9` 通过真实产品前端创建，使用「时尚」筛选，真实分页 4 页/80 候选/0 重复，最终 **70/70 有效且资料完整**、70 个 latest 快照与 current、任务 COMPLETED、前端任务中心/达人详情正常。过程中发现并修复了“中断达人缺失预期模块不可重试”的恢复缺陷，修复后在同一任务上补采完成，未新建任务、未重置 checkpoint、未删除历史数据；其他业务自动化回归通过。

证据文件：
- [任务卡](../tasks/LIVE-03-70.md)、[测试用例](LIVE-03-70-test-cases.md)
- 截图：`assets/LIVE-03-70/`（表单、排队、部分完成、最终完成、富达人详情、补采达人详情）
- 原始日志/监控：`.runtime/live03/task70-monitor.log`、`ui-fashion-70/`（gitignored）
