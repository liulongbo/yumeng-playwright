# QA-01 Phase 1 真机只读探针：connection_users 单边界根因（2026-10-22）

> 范围：真实 Chrome + unit-local-mac-02 受控 Profile，只读执行筛选并抓取最终搜索请求/响应；未创建采集任务、未采集达人、未发布快照、未写业务库。

## 1. 方法与安全边界

- 先停止 Collection Worker（原 PID 82805），确认无在途任务和 Profile 占用；探针结束后已用 local-main 配置重启（PID 1799），两个队列消费者恢复正常。
- 使用项目 BrowserRuntime + 现有 unit profile，不修改账号/Cookie/Profile，不绕过验证。
- 探针脚本只放在 .runtime/qa/probe_connection.py，不是业务代码；仅保存请求中的 attribute_filter 字段名/值、搜索词、分页号和响应 authors 数量；不保存 Header、Cookie、完整响应体。
- 未创建 root_task，未写 requirements/filter_plans/task_checkpoints/snapshots。
- 探针期间 session 均为 VALID / PROTECTED_PAGE_AND_ACCOUNT_VERIFIED，账号精确匹配 ID: 1807978499337419。

## 2. 结果

### 2.1 connection_users 只填下限（min=10w，max 空）

- FilterPlan：keyword=户外 + connection_users.connected.min=10。
- 页面选中区：已选条件 搜索词：户外 连接用户数：10w以上 达人报价：植入视频 清空。
- 最终请求 attribute_filter：
  - link_link_cnt_by_industry__ge = 100000
  - link_link_cnt_by_industry__le = 0
  - price_by_video_type__ge = 0（rel_id=2，契约允许的静态条件）
- 平台响应：HTTP 200，authors=0，pagination.page=1，has_more=false。
- 系统期望：build_expected_attribute_filters 只生成 link_link_cnt_by_industry__ge=100000；没有 le=0。
- 结论：实际请求比计划多出 le=0；ResponseCollector 的精确多重集匹配判为 RESPONSE_UNCORRELATED，最终抛 SEARCH_RESPONSE_FAILED。平台把空上限当成 0，所以即使不判相关性，这次搜索也只会得到 0 位达人；用户“>=10w”的意图没有被正确执行。

### 2.2 connection_users 两边界（min=10w，max=20w）

- FilterPlan：connected.min=10、max=20。
- 页面选中区：连接用户数：10w-20w。
- 最终请求 attribute_filter：
  - link_link_cnt_by_industry__ge = 100000
  - link_link_cnt_by_industry__le = 200000
  - price_by_video_type__ge = 0（rel_id=2，允许静态）
- 平台响应：HTTP 200，authors=20，has_more=true。
- 系统期望：ge=100000、le=200000；与实测一致。
- 结论：两边界路径正常；这解释了 FILTER-01 LT-04/09 的两边界五区间 PASS 与产品任务单边界 FAIL 的差异。

### 2.3 connection_users 只填上限（max=20w，min 空）

- 页面选中区：连接用户数：20w以下。
- 最终请求：link_link_cnt_by_industry__ge=0、le=200000，另加允许静态。
- 系统期望：只有 le=200000。
- 结论：同样多出 ge=0；属同一类单边界问题。用户“<=20w”在语义上等价于 0–20w，但当前期望未包含 0，仍会判为不可相关。

### 2.4 followers 只填下限（min=1000w，max 空）

- 页面选中区：粉丝数量：1000w以上。
- 最终请求：follower__ge=10000000，另加允许静态；没有 follower__le=0。
- 系统期望：只有 follower__ge=10000000；与实测一致。
- 结论：单边界空对侧是 connection_users 专有行为，不是所有区间字段的通用行为；修复不能套用到 followers。

## 3. 根因结论

1. connection_users 控件在某一侧留空时，平台最终请求会用 0 补齐另一侧：只填 min 时补 le=0，只填 max 时补 ge=0。
2. 当前 Adapter 的 build_expected_attribute_filters 对单边界只生成已填一侧，因此实际请求必然多出 0 条目；ResponseCollector 精确多重集拒绝，抛 RESPONSE_UNCORRELATED，再由 _search_operation 转成 SEARCH_RESPONSE_FAILED。
3. 该失败发生在 charge/候选解析之前，所以历史检查点 observed_requests=0 并不表示没有发请求；它只是没有把这次未相关的请求计入关联请求。
4. 即使放宽相关性，min-only 的 le=0 也会让平台返回 0 位达人，说明问题不是“误判”，而是筛选条件没有被正确执行。
5. 5 个历史失败任务全部是 connected.min=2/10、max 空，与该根因完全一致；两边界任务/直接测试则通过。
6. 这是 Adapter 的单边界执行/期望归一化缺陷，不是平台不支持 connection_users，也不是前端没有选中；页面 chip 已正确显示。

## 4. 建议修复（本轮未实施）

- 在 Adapter 执行 connection_users 时，对每个单边界区间做平台域内的无损归一化：缺 max 时填 100（契约已核验上限 100w），缺 min 时填 0。
- 同步在 build_expected_attribute_filters 中为归一化后的 connection_users 生成对应的 le/ge 条目；FilterPlan 保留用户原始单边界值，不改变 plan/digest。
- 只对 connection_users 做该归一化；followers 单边界已实测不补 0，不能一并修改。
- 增加单测/契约测试：connection min-only、max-only、五维混合单/双边界；真实回归 A-07/A-08/A-09。
- 建议同批补结构化筛选值回读（P1，独立问题）：当前 _assert_selected 只查标签，无法在提交前发现值错误；但本次根因不是回读，而是期望/执行不一致。
- 预计范围：backend/src/xingtu/adapter.py + backend/tests；不改 Schema、迁移、Workflow、前端或数据库。

## 5. 本轮未执行

- 未运行 A-07 产品任务：根因已由真机请求/响应证实，再创建一个必然失败的任务只会增加 search 熔断风险；修复后再跑 A-07/A-08。
- 未执行 target=21 分页任务、未执行其它真实采集任务。
- 未修改业务代码/契约/数据库；未提交 Git。

## 6. 修复实施与自动回归（2026-10-22）

### 6.1 代码改动

- backend/src/xingtu/adapter.py 新增 _connection_range_bounds：
  - 只用于 connection_users；
  - 缺失 min 时补契约域下界 0，缺失 max 时补契约域上界 100w；
  - 若契约缺少域约束则 PLATFORM_PAGE_CHANGED，若归一化后越界则 INVALID_FORM。
- build_expected_attribute_filters 对每个非空 connection 区间同时生成 __ge 与 __le（使用归一化后的有效边界）；FilterPlan 仍保留用户原始单边界值，不改变 plan/digest。
- _apply_xingtu_filters 的 connection_users 分支填归一化后的两个边界，而不是留空。
- 未改 followers：实测它不会补 0；未改 Schema、迁移、Workflow、前端、数据库。
- 新增测试：
  - backend/tests/unit/test_filter_request_mapping.py：min-only 期望 ge=100000/le=1000000；max-only 期望 ge=0/le=200000；followers min-only 仍只有 ge。
  - backend/tests/contract/test_filter_controls.py：合成连接控件断言实际填入 [10,100] 与 [0,20]。

### 6.2 自动回归结果

- make test-unit：305 passed。
- make test-contract：35 passed。
- ruff check、ruff format --check、mypy backend/src/xingtu/adapter.py：通过。
- 新增的 6 项映射测试与连接合成控件测试均通过。

### 6.3 修复后真机只读探针

| 场景 | 修复前实际请求 | 修复后实际请求 | 修复后响应 |
|---|---|---|---|
| connected.min=10w，max 空 | ge=100000、le=0 | ge=100000、le=1000000 | 200，authors=20，has_more=true |
| connected.max=20w，min 空 | ge=0、le=200000 | ge=0、le=200000（期望也含 ge=0） | 200，authors=20，has_more=true |
| connected 10–20w | ge=100000、le=200000 | 不变 | 200，authors=20，has_more=true |

- 修复后 min-only 的页面 chip 为“连接用户数：10w-100w”（平台域上限 100w），语义等价于“10w以上”；不再出现 le=0。
- 期望 attribute_filter 与实际请求一致，理论上不会再抛 RESPONSE_UNCORRELATED/SEARCH_RESPONSE_FAILED；真实产品任务回归见下一节。

## 7. 运行态恢复

- 修复探针前再次停止 Collection Worker，探针结束后已用 local-main 配置重启（PID 5557）；队列 xingtu-unit-local-mac-02 有新鲜消费者；./dev.sh status 全绿。
- 探针 Chrome 已正常关闭，未留下 unit profile 进程；API/前端/Intake Worker 未重启。
