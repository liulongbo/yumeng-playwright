# LIVE-02 第三阶段真实验收结果

执行日期：2026-11-04 至 2026-11-05（Asia/Shanghai）  
环境：本机开发栈，API `http://127.0.0.1:8000`，Web `http://127.0.0.1:5173`；数据库 schema=21。  
执行单元：`unit-local-mac-02`（巨量星图）、`unit-local-mac-03-juxing`（磁力聚星）；未新增单元/队列。  
真实浏览器：Playwright MCP + 系统 Chrome（单元 profile）；用户指定验证关键词 `美妆`。

## 1. 两平台真实 70 位直播采集

| 平台 | 任务 ID | 关键词 | 目标 | 状态 | 有效 | 资料完整 | 快照 | 入库 current | 唯一平台 ID | 页数/候选 | 重复 |
|---|---|---|---:|---|---:|---:|---:|---:|---:|---|---:|
| 巨量星图 | `065d36d8-8988-4882-948b-54d1dd864cdf` | 美妆 | 70 | 见下 | 见下 | 见下 | 见下 | 见下 | 见下 | 见下 | 见下 |
| 磁力聚星 | `f6003e46-9463-48bd-b87e-91b96bd3736c` | 美妆 | 70 | COMPLETED | 70 | 70 | 70 | 70 | 70 | 74 位 / 第 5 页游标 | 0 |

### 磁力聚星 70 位（已完成）

- `root_tasks.state=COMPLETED`、`version=1273`、`payload.valid_count=70`、`profile_complete_count=70`、`pipeline_complete=true`。
- `task_creators`：70 行、70 valid；70 个唯一 `platform_creators.platform_creator_id`。
- `creator_snapshots(creator_scene='live_square')`：70 行、70 个唯一 creator；每 creator 1 份快照。
- `creator_live_current`：70 行、70 个 `pipeline_complete=true`。
- 直播字段：940 COLLECTED / 180 NO_DATA；指标来自 `starProfile`、`starWorksInfo`、`commerce/live`，空/零按平台页面提示转 NO_DATA。
- checkpoint：`visited_cursors` 4 个（第 1—4 页），候选 74；达到 70 后停止。
- 首次运行在 68/74 时因一次浏览器动作失败中止；`retry` 从 checkpoint 继续，两次共完成 70，未重新采集前 68 位，未伪造候选。

### 巨量星图 70 位（已完成）

- `root_tasks.state=COMPLETED`、`version=1149`、`payload.valid_count=70`、`profile_complete_count=70`、`pipeline_complete=true`、`failure_reason=null`。
- `task_creators`：70 行、70 valid；70 个唯一 `platform_creators.platform_creator_id`。
- `creator_snapshots(creator_scene='live_square')`：70 行、70 个唯一 creator；每 creator 1 份快照；0 个 creator 多快照。
- `creator_live_current`：70 行、70 个 `pipeline_complete=true`。
- 直播字段：342 COLLECTED / 848 NO_DATA；其中 17 位达人至少采集到 1 项非 `platform_star_id` 的真实直播表现指标（如 ACU、PCU、场次、场均观看、带货指标）；其余达人页面显示“近30天内没有开播”，按 NO_DATA 记录，不伪造 0。
- checkpoint：`visited_cursors` 4 个（第 1—4 页），候选 78；达到 70 后停止；跨页 0 重复。
- 此前 `5847b568-5a1e-446e-9929-3549e8efe2c3` 已完成 70 位，但当时统计响应监听器过早移除，直播指标全部 NO_DATA；该任务仅作为“70 位身份/计数”对照，不计入最终直播数据验收。
- 最终任务修复了统计响应监听生命周期，并对单达人详情未就绪做一次重载后按候选失败继续，不再中止整任务；最终任务未失败重试。

## 2. 小样本闭环

| 平台 | 任务 ID | 关键词 | 目标 | 状态 | 有效/完整 | 说明 |
|---|---|---|---:|---|---|---|
| 巨量星图 | `b1b6fdb9-6b5a-4dbf-8975-63f890d1270f` | `7619352201953017919`（达人 ID） | 1 | COMPLETED | 1/1 | 采集到 16 项真实直播指标（ACU=3、PCU=9、场次=6、场均观看 266 等） |
| 巨量星图（UI 创建） | `b8a0fb54-d35d-4cb8-b32a-990ec848578b` | 美妆 | 1 | COMPLETED | 1/1 | 通过真实产品 UI 创建；任务详情显示“巨量星图 · 直播广场” |
| 磁力聚星 | `af37d30b-5daa-473c-bbdb-908d78b941a7` | 美妆 | 1 | COMPLETED | 1/1 | 小样本闭环，单元/会话恢复后成功 |

## 3. 71 位拒绝

| 平台 | 请求 | 结果 |
|---|---|---|
| 巨量星图 | `target_count=71` | HTTP 422，`INVALID_FORM`，`live target_count exceeds 70` |
| 磁力聚星 | `target_count=71` | HTTP 422，`INVALID_FORM`，`live target_count exceeds 70` |

## 4. 直播手动更新

- 聚星达人 `f830b850-1160-4425-af68-dcdfd15070f2`：`POST /api/creator-library/{id}/live-updates` → `202`，任务 `b3410a77-1000-4983-83f4-0eb71cce1731`；完成 `COMPLETED`、有效 1、完整 1。
- 该达人直播快照从 1 份增加到 2 份；`creator_update_schedule` 行数仍为 0（直播更新不进入短视频定时更新表）。
- 修复点：直播手动更新没有搜索计划，聚星 adapter 在 `search_page is None` 时自行建立已登录直播页，不再 `SESSION_INDETERMINATE`。

## 5. 短视频回归

| 平台 | 任务 ID | 场景 | 状态 | 有效/完整 | 说明 |
|---|---|---|---|---|---|
| 磁力聚星 | `468089a0-1d4b-439f-8b4f-c539ff60374b` | `video_square` | COMPLETED | 1/1 | 首次导航超时；retry 后完成。短视频读模型/契约未改 |
| 巨量星图 | `183b72f4-2ec5-44d8-a2e8-1cd83b170bfa` | `video_square` | COMPLETED | 1/1 | 精选集合也 COMPLETED；短视频能力未回退 |

## 6. 自动化测试

- 后端单元/契约：`pytest backend/tests/unit backend/tests/contract`。
- 后端集成：`XINGTU_TEST_DATABASE_URL=<xingtu_test>`；覆盖迁移 21、直播读模型隔离、直播手动更新不建 schedule。
- 前端：`npm --prefix frontend test -- --run`（109 tests）。
- 新增用例：`backend/tests/unit/test_live_square.py`、`backend/tests/integration/test_live_library.py`、`frontend/src/liveCreator.test.ts`。

## 7. 测试与检查计数

| 检查 | 结果 |
|---|---|
| 后端 unit + contract + integration | 565 passed / 1 skipped |
| 前端 tsc / vitest / build | 109 passed；build 成功 |
| mypy | 41 files，0 error |
| ruff（backend/src + 本轮测试） | All checks passed |
| 85 条测试用例 | 67 PASS / 0 FAIL / 6 BLOCKED / 12 NOT_RUN |

## 8. 结论：CONDITIONAL GO

通过：双平台真实 70 位有效任务、71 拒绝、跨页、0 重复、有效/DB/快照/current 一致、短视频回归、直播更新不写视频 schedule、无新增单元。

条件：
1. 星图 70 位中 17 位有真实直播表现指标，其余为“近30天内没有开播”的 NO_DATA；不伪造。
2. 同一达人双场景（短视频+直播）分别查看/更新的端到端用例未闭环（BLOCKED）；已有共享身份证据但未在测试任务中构造同身份双场景。
3. 视频定时更新、登录失效、安全验证、页面结构破坏、异常注入等 6 条 BLOCKED / 12 条 NOT_RUN。
4. 两平台第 7 页以后未验证；契约 disclosure 保留。
5. 聚星 70 首次失败后 retry 补齐；星图 70 最终任务无失败重试；开发期失败/取消任务不作为最终证据。
