# QA-01 connection_users 单边界修复与真实回归（2026-10-22）

> 授权：用户 2026-10-22 明确要求“按上述方案修复 connection_users 单边界并跑回归”。
> 范围：Adapter 单边界归一化 + 单元/契约测试 + 两个真实产品回归任务；未改 Schema、迁移、Workflow、前端或数据库。

## 1. 根因

- connection_users 单边界时平台会补 0：min=10w、max 空 -> 最终请求 ge=100000、le=0；max=20w、min 空 -> ge=0、le=200000。
- 修复前期望只生成已填一侧，实际多出 0 条目，ResponseCollector 精确多重集判为 RESPONSE_UNCORRELATED，最终 SEARCH_RESPONSE_FAILED。
- 修复前 min-only 的真实响应为 authors=0/has_more=false；不是单纯误判，而是用户条件未执行。
- followers 单边界实测不补 0，因此修复只针对 connection_users。

## 2. 代码改动

- backend/src/xingtu/adapter.py 新增 _connection_range_bounds：
  - 只用于 connection_users；
  - min 缺失补契约域下界 0，max 缺失补契约域上界 100w；
  - 契约缺域约束时 PLATFORM_PAGE_CHANGED，归一化越界时 INVALID_FORM。
- build_expected_attribute_filters 对每个非空 connection 区间生成归一化后的 __ge 与 __le；FilterPlan 保留用户原始单边界，不改变 plan/digest。
- _apply_xingtu_filters 的 connection_users 分支填归一化后的两个边界，不再留空。
- 未改 followers、Schema、迁移、Workflow、前端、数据库。

## 3. 自动回归

- make test-unit：305 passed。
- make test-contract：35 passed。
- ruff check、ruff format --check、mypy backend/src/xingtu/adapter.py：通过。
- 新增测试：
  - backend/tests/unit/test_filter_request_mapping.py：min-only 期望 ge=100000/le=1000000；max-only 期望 ge=0/le=200000；followers min-only 仍只有 ge。
  - backend/tests/contract/test_filter_controls.py：合成连接控件断言实际填 [10,100] 与 [0,20]。
- 未运行 PostgreSQL 集成套件：当前环境未配置 XINGTU_TEST_DATABASE_URL，集成 fixture 会显式失败；本次改动不涉及存储/Schema，已用单元、契约和两个真实产品任务覆盖。

## 4. 真实产品回归

| 用例 | task_id | 输入 | 终态 | 计数 | 证据 |
|---|---|---|---|---|---|
| A-08 两边界对照 | 09b51e99-5876-404a-b6fb-0acb957f2ca2 | 户外 + connected 10–20w；target 1 | PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE | discovered 20、valid 1、profile 0、featured 1、failed 0 | checkpoint 50 req/50 resp、0 duplicate；搜索 20 候选 |
| A-07 单边界修复 | e75d8f07-ab07-4254-97e6-9322ab46f2d5 | 户外 + connected min=10w、max 空；target 1 | PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE | discovered 20、valid 1、profile 0、featured 1、failed 0 | checkpoint 75 req/75 resp、0 duplicate；搜索 20 候选 |

- 两个任务均由 media-a 从真实前端提交，走 P1/P2/真实平台/持久化/前端展示；未出现 SEARCH_RESPONSE_FAILED、未触发 search 契约熔断。
- A-07 的 requirement/plan 仍保留 connected.min=10、max=null；修复只在 Adapter 执行与期望生成层做平台域归一化，未改写用户需求。
- 两个任务的 PARTIAL_COMPLETED 原因是 PROFILE_SCOPE_INCOMPLETE（资料完整 0/1），不是筛选/分页失败；精选完整 1/1、失败步骤 0。
- 任务内达人均为 1 人、快照 1 份；featured_collections 均 2 条（A-08 一条 COMPLETE/一条 EMPTY；A-07 两条 COMPLETE）。
- 修复后 search 契约健康仍为 ENABLED、consecutive_failures=0。
- 前端截图：
  - [A-08 两边界任务](assets/qa01/A-08-two-bounds.png)
  - [A-07 单边界任务](assets/qa01/A-07-min-only.png)
- 截图显示：部分完成、已发现 20、有效入库 1、资料完整 0、精选完整 1、失败步骤 0；页面计数与 DB/API 一致。

## 5. 结论

- connection_users 单边界根因已修复，并通过单元、契约、真机只读探针和两个真实产品任务回归。
- 两边界与单边界都能真实检索到 20 位候选并采集 1 位有效达人；不再出现修复前的 SEARCH_RESPONSE_FAILED。
- 修复未改变 FilterPlan/用户输入语义；min-only 页面 chip 在平台域内显示为 10w-100w，等价于 10w以上（平台上限 100w）。
- 未执行 A-12/B-01/C-01 与 PG-03；分页第 3 页仍未验证。

## 6. 运行态

- 两个回归任务期间 Collection Worker 正常运行；任务结束后单元租约释放，无残留 Chrome/Profile 进程。
- update-scheduler 未启动。
- 未提交 Git。
