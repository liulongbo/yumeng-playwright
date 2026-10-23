# QA-01 剩余筛选用例真实验收（2026-10-22）

> 范围：A-09 连接五维、A-12 观众画像五维、B-01 背景四项、C-01 跨类别组合；真实前端提交，media-a，target 1/2。未改 Schema/迁移/Workflow/数据库。

## 1. 结果总览

| 用例 | task_id | 输入 | 终态 | counts | 结论 |
|---|---|---|---|---|---|
| A-09 连接五维 | c9c4a1f1-94b8-4273-a917-b1eef1fa12a4 | 户外 + 连接五维（整数边界） | PARTIAL_COMPLETED / SEARCH_EXHAUSTED | discovered 0、valid 0、failed 0 | 最终请求精确相关；平台真实空结果；不是故障 |
| A-12 观众画像五维 | 666114c3-7b84-4943-8849-dc1ce3caf33d | 户外 + 观众年龄/性别/设备/地域/八大人群 | COMPLETED | discovered 20、valid 1、profile 1、featured 1、failed 0 | 五维映射、采集、快照、前端全通过 |
| B-01 背景四项 | 989822ba-7072-40bb-9aa3-f908aee5f9f8 | 户外 + 女 + 北京/朝阳 + 硕士 + 科技 | PARTIAL_COMPLETED / SEARCH_EXHAUSTED | discovered 0、valid 0、failed 0 | 最终请求精确相关；平台真实空结果；不是故障 |
| C-01 跨类别组合 | 43c74167-5954-4dc1-b668-52ddc448b209 | 户外 + 背景四项 + connected 10–20 + 粉丝 10–100 + 粉丝画像五维；target 2 | PARTIAL_COMPLETED / SEARCH_EXHAUSTED | discovered 0、valid 0、failed 0 | 8 类条件精确进入 plan/请求；平台真实空结果；不是故障 |

## 2. A-12 证据（正向完整）

- 终态 COMPLETED、valid 1/1、profile_complete 1、featured_complete 1、failed 0。
- task_creators 1、creator_snapshots 1。
- checkpoint：78 observed requests / 78 responses、0 duplicate、failure_counts {}、20 candidates、cursor=2、visited_cursors=[null]。
- 说明观众画像五维的 plan/请求/候选/采集/快照/收口/前端全链路通过。

## 3. A-09 / B-01 / C-01 证据（真实空结果）

- 三者均为平台真实空结果：
  - A-09：observed_requests=1、observed_responses=1、exhausted=true、candidates=0、failure_counts {}。
  - B-01：observed_requests=1、observed_responses=1、exhausted=true、candidates=0、failure_counts {}。
  - C-01：observed_requests=1、observed_responses=1、exhausted=true、candidates=0、failure_counts {}。
- 请求被 ResponseCollector 接受（若 attribute_filter 不一致会 SEARCH_RESPONSE_FAILED），说明五维/背景四项/8 类组合的映射与最终请求一致；平台返回 has_more=false，Engine 记录耗尽证据并以 PARTIAL_COMPLETED / SEARCH_EXHAUSTED 收口，符合“没有符合条件的达人不是程序故障”的产品规则。
- 但 A-09/B-01/C-01 没有有效达人和快照，因此不能作为这些组合“数据持久化正向”证据；正向持久化由 A-07/A-08/A-12 覆盖。

## 4. 新发现：小数范围值被前端原生 step 校验阻断

- A-09 首次尝试使用“了解 0.5–3w”。页面已正确生成 plan，但提交后没有 POST、没有 form-error，页面停留 /tasks/new；根因是 RangeInputs 的 input type=number 没有 step=any，浏览器默认 step=1，0.5 不满足原生约束，表单被浏览器拦截。
- 后端 RequirementRange/ConnectionUsersRequirement 允许 Decimal（0.5 合法），单元测试与历史 custom 12.5 也允许；因此这是前端可提交性缺口，不是后端/契约问题。
- 本次回归改用整数 1–3 完成 A-09；小数路径未修复、未验收。
- 建议另立前端小修：为连接/粉丝区间输入增加 step=any（或按产品规则明确只允许整数并在前端提示），并补测试；本轮未改，因为用户只授权 connection_users 单边界修复。

## 5. 运行态与未完成

- 未出现 SEARCH_RESPONSE_FAILED，search 契约健康应保持 ENABLED（PG-03 前复核）。
- A-09/B-01/C-01 的空结果不是故障；未重试、未扩大采集。
- PG-03 target=21 正在独立执行；第 3 页仍未验证。
- 未提交 Git。
