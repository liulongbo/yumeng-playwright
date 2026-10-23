# QA-01 Phase 1 字段/参数映射离线检查（2026-10-22）

> 范围：离线生成 FilterPlan/attribute_filter，核对契约映射、边界与互斥；未创建任务、未访问平台。

## 1. 环境与命令

- 代码：HEAD ae600ec；契约 xingtu-ad-creator-featured-v11 / xingtu-ad-creator-square-v2。
- 命令：
  - PLAYWRIGHT_BROWSERS_PATH=.runtime/browsers .venv/bin/pytest backend/tests/unit/test_filter_request_mapping.py backend/tests/unit/test_product_models.py backend/tests/unit/test_intake.py backend/tests/unit/test_observer_filters.py backend/tests/contract/test_filter_controls.py -q
- 结果：34 passed in 1.81s。

## 2. 关键映射结果

| 用例 | FilterPlan | 期望 attribute_filter | 结论 |
|---|---|---|---|
| connection connected min=10，max 空 | connection_users，connected.min=10 | link_link_cnt_by_industry__ge=100000 | 合法；只产生下界条目 |
| connection connected 10–20 | connected.min=10/max=20 | __ge=100000、__le=200000 | 合法；两条目 |
| connection 五维（10–20、0.5–3、0–5、0–2、0–1） | 五维 compound | link_link/l/i/n/k 的 __ge/__le 共 10 条 | 合法；顺序与契约一致 |
| followers 10–100w | followers range | follower__ge=100000、follower__le=1000000 | 合法 |
| followers 12.5–25.5w | followers range | follower__ge=125000、follower__le=255000 | 合法；Decimal 精度保留 |
| followers min=1000，max 空 | followers range | follower__ge=10000000 | 合法；只产生下界 |
| 背景四项（女、北京/朝阳、硕士、科技） | gender/region/education/yellow_v | gender=2、city=["朝阳区"]、两个 persona_tag_level_one=["110211"]/["110210"] | 合法；同名多重集；city 不产生 province |
| 观众画像五维 | viewer_profile compound | watcher_age_most_new=[22,23]、watcher_device_brand_most_new=[10]、watcher_city_level_most_new=[13]、link_crowd_profile=[58]、watcher_gender_female_rate_v2__ge=0.6 | 合法 |
| 粉丝画像五维 | fan_profile compound | fans_age_rate_most=[21]、fans_system_rate_most=[10]、fans_city_level_most=[13]、fans_crowd_profile=[58]、fans_gender_female_rate_v2__ge=0.5 | 合法 |

## 3. 边界与非法输入

| 用例 | 结果 |
|---|---|
| connection 100/100 | 合法；__ge=1000000、__le=1000000 |
| connection 100.1 | 拒绝（RequirementForm 校验） |
| connection min>max | 拒绝 |
| connection 空对象 | 拒绝 |
| connection 只填 max | 合法；只产生 __le |
| followers 0–5000 | 合法；follower__ge=0、follower__le=50000000 |
| followers 5000.1 | 拒绝 |
| followers min>max | 拒绝 |
| followers 只填 max | 合法；只产生 __le |
| viewer + fan 同时 | 拒绝 |
| 北京整省 + 北京/朝阳 | 拒绝 |
| 无业务筛选 | 拒绝 |
| target 0 / 201 | 拒绝 |
| v2 creator_types / quote | 拒绝 |

## 4. 新发现/待真机确认

1. **min=0 会产生 __ge=0 条目**：followers 0–5000、connection 五维中 aware/interested/liked/followed 的 0 下界都会生成 __ge=0。若平台在 UI 层省略零下界，attribute_filter 精确多重集会把它当成残留并拒绝。Phase 1 真机探针必须覆盖 0 下界。
2. **单边界在当前计划层是合法的**：connection/followers 只填一侧都能通过 P1 和契约校验；实际平台请求是否只发单侧、是否出现空对侧，必须真机抓取。离线检查不能证实 H1。
3. **观众/粉丝画像的 attribute_filter 顺序与控件顺序不同**：性别条目最后生成，但 ResponseCollector 使用多重集，顺序不影响匹配；不能据此判错。
4. **前端到请求的精确值**：离线仅证明 Adapter 期望值；平台 UI 是否按这些值填写、是否残留，仍需 Phase 1 真机探针。

## 5. 未执行

- 未创建任务、未访问平台、未写业务库。
- 未修改代码/契约/数据库。
- 真机探针（connection 单边界 vs 两边界、0 下界、五维顺序）尚未执行。
