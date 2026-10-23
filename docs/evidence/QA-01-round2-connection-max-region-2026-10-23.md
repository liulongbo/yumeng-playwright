# QA-01 第二轮：连接用户数 99999w 与地域筛选生效（2026-10-23）

> 授权：用户在本轮明确要求修复「连接用户数五个字段最大 99999w」与「填写湖南省但检索结果不符」，并要求用 Playwright MCP + Chrome 做真实验收。
> 环境：单机 local-main；API 127.0.0.1:8000；前端 127.0.0.1:5173；PostgreSQL 127.0.0.1:55432；Temporal 127.0.0.1:57233；执行单元 unit-local-mac-02；产品账号 media-a；系统 Chrome 156.0.8078.47。
> 契约：xingtu-ad-creator-featured-v13；能力 xingtu-ad-creator-square-v3；Adapter browser-v9。
> 浏览器自动化：项目 Playwright MCP server 1.62.0-alpha-2026-06-29 over stdio + 系统 Chrome。前端验收使用项目 acceptance profile；星图页面验收使用执行单元的 storage-state 快照，未使用 mock。

## 1. 结论

1. 「连接用户数 / 了解 / 兴趣 / 喜欢 / 追随」当前平台真实输入范围是 **0–99999w**，不是旧的 0–100w。旧契约、后端硬编码上限和由此生成的前端 max 属性共同造成 99999 无法提交。已统一改为 99999w，并验证 99999 在平台请求中换算为 **999,990,000**，没有截断或溢出。
2. 用户报告的湖南省任务 2df0fd1d-... 的真实原因是：**前端根本没有把湖南省放进提交表单**。该任务原始 requirement 的 creator_regions 是空数组，FilterPlan 也没有 region；P1/P2 没有收到该条件，因此不是 P2 丢弃、覆盖或静默降级。前端地域控件把选择暂存在组件本地状态，只有点击「添加」才写入表单，直接提交会静默漏掉该条件。
3. 已修复为地域选择后立即写入表单；另保留「添加」按钮用于移除 chip 后重新加入，重复点击不会产生重复项。修复后新建任务 a1c874f9-... 的 requirement、FilterPlan、平台最终请求、任务结果和达人详情一致。
4. 已逐项审计五类筛选链路。除上述前端「待添加」缺口与一个**既有的无关键词任务 MISSING_BINDING 问题**外，没有发现其他前端字段被静默丢弃，也没有发现 P1/P2 对已提交字段的覆盖或错误映射。

## 2. 问题一：连接用户数最大值 99999w

### 2.1 旧行为与真实根因

- 旧契约 contracts/douyin_xingtu.verified.json 的五个连接用户维度均为 min=0、max=100；前端 RangeInputs 使用能力接口返回的 range_constraints，因此五个上限输入框都是 max=100。
- 后端有两处独立硬编码：product_models.ConnectionUsersRequirement 拒绝大于 100 的值；domain 的 FilterPlan 校验也拒绝大于 100w。
- 这不是单位换算问题。99999w 在 Adapter 中按 scale=10000 换算为 999,990,000，仍在安全整数范围内。
- 当前平台真实控件已确认：五个维度共用同一 range 组件；上限 input 的 placeholder=99999、max=99999、min=0；输入 99999 后原生校验 checkValidity()=true。

### 2.2 最小修复

- contracts/douyin_xingtu.verified.json
  - contract_version：featured-v12 → featured-v13
  - capabilities.version：square-v2 → square-v3
  - compatible_plan_versions：新增 square-v2，保留 square-v1
  - 五个 connection_users dimensions 的 range_constraints.max：100 → 99999
  - verified_at 与 evidence_refs 同步更新
- backend/src/xingtu/domain.py
  - 新增共享常量 CONNECTION_USERS_MAX_W = Decimal("99999")
  - FilterPlan 的连接用户上限校验使用该常量，错误改为 exceeds 99999w
- backend/src/xingtu/product_models.py
  - RequirementForm 的连接用户上限校验使用同一常量
- backend/src/xingtu/adapter.py
  - 仅更新单边界归一化注释中的 0/100w 为 0/99999w；执行逻辑不变
- 前端不写死 99999：继续由 capabilities 的 range_constraints 驱动，max 自动变为 99999。

### 2.3 实测结果

| 用例 | 前端/平台实际 | 结论 |
|---|---|---|
| 五个字段的 max 属性 | 10 个连接用户 input 全部 max=99999，step=any | PASS |
| 五个字段均填 99999（上限、下限留空） | 表单接受；摘要「连接用户：5 个区间」；无原生校验错误 | PASS |
| 单字段上限 99999 | 平台请求 link_link_cnt_by_industry__ge=0、__le=999990000，返回 200 | PASS |
| 单字段下限=上限=99999 | 平台页面显示 99999w-99999w；请求 ge=999990000、le=999990000；0 位达人 | PASS（边界） |
| 100000w 提交 API | HTTP 422；field_errors.body.connection_users = connection user range exceeds 99999w | PASS（拒绝越界） |
| 10–20w 既有区间 | 既有 A-08 任务和契约测试继续通过 | PASS（未回归） |

真实产品任务 f3aba74e-a9cc-4b05-822f-6ce3f76576d6：关键词「户外」+ 五个连接用户上限 99999w，目标 1。
- requirement：五个字段均为 max=99999、unit=ten_thousand_count；
- FilterPlan：capability_version=square-v3，五个字段原样保留；
- 终态：PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE，valid=1，搜索本身成功；资料部分完成属于既有 F05 范围，不是筛选失败；
- 入库达人：户外胡三浪，粉丝 749,848，月连接用户 1,959,434。

## 3. 问题二：湖南省任务的实际链路

### 3.1 用户报告的故障任务

任务：2df0fd1d-d7f7-4574-980a-344780f2e7e4，2026-10-23 10:00 创建，终态 COMPLETED，目标 2、valid 2。

原始 requirement（数据库）：
~~~json
{
  "keyword": "美妆教程",
  "creator_gender": "male",
  "creator_regions": [],
  "connection_users": {"connected": {"min": "10", "max": "100", "unit": "ten_thousand_count"}},
  "viewer_profile": {"age": ["age_18_23", "age_24_30", "age_31_40", "age_41_50"]}
}
~~~

FilterPlan：
- filters 只有 keyword、gender、connection_users、viewer_profile；
- 没有 region；
- capability_version=xingtu-ad-creator-square-v2（历史计划，现在仍可读）。

入库结果：
| 达人 | 省份 | 城市 | 粉丝 |
|---|---|---|---|
| 网紫垫下 | 浙江省 | 杭州市 | 145,862 |
| Sam老师 | 上海市 | 长宁区 | 108,031 |

结论：湖南省没有进入 requirement，因此不可能进入 P1、FilterPlan、P2 或 Chrome。任务完成并不代表用户以为的 region 条件被执行；这里的问题是**提交前就丢了条件**。

### 3.2 前端复现（修复前）

在真实前端 /tasks/new：
1. 输入关键词「美妆教程」；
2. 在「所在地域」选择湖南省；
3. 此时省级 select 的 value 已是 430000，但 selection-chips 为空，右侧摘要仍只有「关键词：美妆教程」；
4. 只有点击「添加」后，才出现「湖南省 ×」和「所在地域：1 项」。

证据：
- [修复前：选择后尚未添加](assets/qa01/round2/region-selection-before-add.png)
- [点击添加后](assets/qa01/round2/region-selected-after-add.png)

根因定位到 frontend/src/pages.tsx 的 RegionField：province/city 只是组件本地 state，add() 才调用 update("creator_regions", ...)。提交函数只序列化 form，因此未点击「添加」时该条件被静默省略。

### 3.3 平台「所在地域」的真实语义

平台最终请求使用 attribute_filter 的 province 字段，不是达人资料里的任意文本标签：

~~~json
{"field":{"field_name":"province"},"field_value":"[\"湖南省\"]"}
~~~

真实只读探针（关键词「美妆教程」+ 湖南省）：
- 页面已选条件显示「搜索词：美妆教程 / 所在地域：共14项」；「共14项」是平台省级节点下 13 个地级市加省节点自身的内部计数，不是 14 个独立筛选项；
- 最终请求为 province=["湖南省"]，search_param.keyword="美妆教程"；
- 返回 19 位达人；19/19 的 attribute_datas.province 都是「湖南省」，城市为长沙/怀化/邵阳/湘潭等；
- 页面首屏与任务首位达人都是「饭仔牙🦷 / 长沙市」。

因此不能仅凭达人资料中的某个地域标签判定平台未过滤；本项目的正确判据是：最终请求的 province 数组 + 平台返回的 attribute_datas.province/city + 入库快照/当前投影。

### 3.4 修复

frontend/src/pages.tsx 的 RegionField：
- 省级 select 变更后立即 commit(province, "")；
- 二级地域 select 变更后立即 commit(province, city)；
- commit 复用原有去重/整省替换逻辑；「添加」按钮保留，点击为幂等操作，便于移除 chip 后重新加入；
- 不改变后端 RegionCompound 结构、province/city 请求映射或任务 API。

### 3.5 修复后的真实任务

任务：a1c874f9-2465-4789-9fc1-b6aa0fccaa1e，关键词「美妆教程」+ 湖南省，目标 1。

- 前端摘要：关键词 1 项 + 所在地域 1 项；
- requirement：creator_regions=[{"province_code":"430000","city":null}]；
- FilterPlan：keyword + region，region.selections=[{province_code:"430000",city:null}]，capability_version=square-v3；
- 终态：PARTIAL_COMPLETED / FEATURED_COLLECTION_INCOMPLETE，valid=1，profile=1，failed=0；
- 任务 checkpoint：71 requests / 71 responses，failure_counts={}，无 attribute_filter mismatch；
- 入库达人：饭仔牙🦷，平台 ID 6870168454683426823，省份「湖南省」、城市「长沙市」，粉丝 397,195；
- 前端达人详情显示：地区「湖南省 · 长沙市」。

说明：FEATURED_COLLECTION_INCOMPLETE 是既有 F06 精选集合完整度问题，不是地区筛选失败；任务内达人已存在且地区正确。

## 4. 五类筛选条件排查

### 4.1 代码路径覆盖

以下五类字段均经过同一条链路：
- 前端 CapabilityInput -> RequirementForm
- backend intake.build_expected_plan -> FilterPlan
- BrowserAdapter.apply_xingtu_filters -> 页面控件
- readback_conditions -> 已选条件
- build_expected_attribute_filters -> 最终请求精确多重集
- ResponseCollector -> 响应相关性
- 任务快照/当前投影 -> 页面

| 类别 | 字段 | 前端提交 | P1/Plan | P2 应用 | 读回/请求关联 | 本轮结论 |
|---|---|---|---|---|---|---|
| 背景信息 | gender / education / yellow_v | 直接写 form | 保留 | 已实现 | 字段+选项+最终请求 | 无新增问题；既有任务通过 |
| 背景信息 | region | 修复前需点击添加，已改为选择即写入 | 保留 | province/city | 字段标签+最终 province/city 数组 | 已修复并真实通过 |
| 受众画像 | connection_users 五维 | 直接写 form；max 已改 99999 | 保留 | 五维区间 | 字段标签+数值 token+最终请求 | 最大值问题已修复；五维真实任务通过 |
| 受众画像 | followers | 直接写 form（预设/自定义） | 保留 | 预设/自定义 | 字段+数值+最终请求 | 未改；既有 12.5w 通过 |
| 观众画像 | viewer_profile 五维 | 直接写 form | 保留 | 五维控件 | 选项标签+最终请求 | 未改；既有 A-12 通过 |
| 粉丝画像 | fan_profile 五维 | 直接写 form | 保留 | 五维控件 | 选项标签+最终请求 | 未改；互斥逻辑既有通过 |

### 4.2 特别核对

- RegionField 是唯一带「暂存后添加」的字段；connection/followers/profile 在 onChange 中直接更新 form。
- 前端 selectedConditionSummary 与提交的 form 同源；修复后地域摘要立即出现，用户不必猜测是否已加入。
- P1 的 build_expected_plan 从 normalized RequirementForm 构造，不依赖模型自由输出；已提交字段不会因模型省略而从计划中消失。
- P2 的 readback_conditions 对每个计划字段检查标签/选项/数值；region 只检查字段标签，最终 province/city 值由精确请求多重集校验。
- 多条件组合：T1 使用 keyword + 五个 connection 条件成功搜索；Hunan 使用 keyword + region 成功搜索并入库；既有 C-01 跨类别条件仍保留在 plan/请求中。
- 未发现条件被覆盖或部分条件未生效却继续采集的情况。任务若未通过读回或请求多重集，会以 PLATFORM_CONDITION_MISMATCH / RESPONSE_UNCORRELATED / SEARCH_RESPONSE_FAILED 失败，而不是静默放宽。

## 5. 自动化回归

| 检查 | 结果 |
|---|---|
| backend unit（10:51，修复完成时） | 307 passed |
| backend unit（11:13，当前工作区） | 311 passed、1 failed；失败为 backend/tests/unit/test_collection_worker_dispatch.py::test_a_failing_tick_never_kills_the_consumer，原因是工作区另一组 Worker liveness 改动的新调用 register_worker_instance 未同步到该测试的 FakeRepository；与本轮筛选/地域改动无关，未擅自修改 |
| backend 本轮定向测试 | 34 passed（product_models / filter_request_mapping / search_contract_registration） |
| backend contract | 37 passed |
| frontend tests（当前工作区） | 84 passed |
| frontend TypeScript lint | passed |
| frontend production build | passed |
| mypy backend/src | Success: no issues found in 35 source files |
| ruff check（本次改动文件） | All checks passed |
| ruff format --check（本次改动文件） | passed |
| make check | 失败于既有 scripts/acceptance 的 11 个 UP031，不是本次改动文件；本次改动文件单独 lint/format 通过 |

新增/更新测试：
- backend/tests/unit/test_product_models.py：99999 接受、100000 拒绝、小数仍拒绝；
- backend/tests/unit/test_filter_request_mapping.py：五维 99999 映射为 999,990,000；单边界填域上限；
- backend/tests/contract/test_filter_controls.py：合成控件填 0/99999；读回 10w-99999w；
- frontend/src/App.test.tsx：五个 input max=99999、step=any；99999 写入 form；地域选择即提交；province→city 替换；
- 契约登记测试继续覆盖 page=3 / max_verified=3。

## 6. 真实任务与探针清单

| 对象 | 类型 | 结果 |
|---|---|---|
| 2df0fd1d-... | 用户报告的湖南任务 | COMPLETED，2 valid；requirement/plan 无 region；浙江/上海结果 |
| a1c874f9-... | 修复后湖南任务 | PARTIAL_COMPLETED / FEATURED_COLLECTION_INCOMPLETE，1 valid；湖南长沙 |
| f3aba74e-... | 五个连接 99999 任务 | PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE，1 valid；搜索成功 |
| 47a49ae9-... | 无关键词、仅连接 99999 | FAILED / PLATFORM_PAGE_CHANGED:MISSING_BINDING；既有独立问题，见 §7 |
| d1813612-... | 重启时 update-scheduler 误创建 | FAILED / PLATFORM_PAGE_CHANGED:RESPONSE_SCHEMA_MISMATCH；1 份快照；scheduler 已停 |
| MCP 平台探针 99999 | 只读 | ge=0 / le=999990000，200 |
| MCP 平台边界 99999/99999 | 只读 | ge=le=999990000，0 位 |
| MCP 湖南探针 | 只读 | province=["湖南省"]，19/19 作者湖南 |
| PG-03 829d4568 | 既有分页任务 | task_creators=21、valid=21、快照=21；前端 20→21；visited_cursors=[null,"2"]、cursor=3 |

## 7. 未解决问题与风险

1. **无关键词任务 MISSING_BINDING（既有缺陷，未修）**：任务 47a49ae9-... 只有 connection_users，没有 keyword。search.request_match 固定包含 search_param.keyword 与 search_param.seach_type；prepare() 在无 keyword 时不写入 keyword/keyword_mode 绑定，ResponseCollector.resolve() 抛出 PLATFORM_PAGE_CHANGED:MISSING_BINDING。该问题与 99999 无关，但意味着「仅连接用户」任务目前不能执行。修复需要调整 P2 请求相关性语义（关键词缺失时跳过关键词匹配），属于高风险模块，未在本轮擅自修改，需用户确认后另立最小修复/回归。
2. **重启副作用**：执行 ./dev.sh restart 时脚本自动启动 update-scheduler；它在 10:51:51 创建了 scheduled_update d1813612-...，更新 1 位达人后因既有响应 Schema 不匹配失败。已立即停止 scheduler；未删除任务或快照，保留审计。
3. **FEATURED_COLLECTION_INCOMPLETE / PROFILE_SCOPE_INCOMPLETE**：既有 F05/F06 完整度问题，不是筛选失败；本轮未修。
4. **地域多省组合**：本轮只验证了单省整省；跨省整省+城市组合的 AND/OR 平台语义未完成真机确认。产品当前允许该组合，建议单独验收，避免在地域组合上引入未验证假设。
5. make check 的 lint 仍被 scripts/acceptance 既有 UP031 阻断；不是本轮代码引入，但完整 make check 不能宣称通过。当前工作区另有 Worker liveness 并发改动，使全量 backend unit 出现 1 个与本轮无关的测试失败（见 §5）。
6. 重启后曾出现登录 503 LOGIN_LIMITER_UNAVAILABLE：.runtime/m3-app.env 的 XINGTU_REDIS_URL 无密码，而本机 Redis 需要认证。已将运行态 URL 对齐 .runtime/local-main/env（不进入版本库），重启 API 后登录 200；未改业务代码或数据库。
7. 2026-10-23T12:05 已补做剩余字段的正向真机（followers、fan_profile、gender、education、yellow_v），四个任务均 valid=1；详见 [QA-01-positive-filters-2026-10-23.md](QA-01-positive-filters-2026-10-23.md)。

## 8. 证据文件

- 五维 99999 输入：[five-99999-inputs.png](assets/qa01/round2/five-99999-inputs.png)
- 五维 99999 FilterPlan：[five-99999-plan.png](assets/qa01/round2/five-99999-plan.png)
- 五维任务详情：[five-99999-task.png](assets/qa01/round2/five-99999-task.png)
- 平台 99999 结果页：[platform-99999-chip.png](assets/qa01/round2/platform-99999-chip.png)
- 湖南选择即加入：[hunan-selected.png](assets/qa01/round2/hunan-selected.png)
- 湖南 FilterPlan：[hunan-plan.png](assets/qa01/round2/hunan-plan.png)
- 湖南任务详情：[hunan-task.png](assets/qa01/round2/hunan-task.png)
- 湖南达人详情（湖南省·长沙市）：[hunan-creator.png](assets/qa01/round2/hunan-creator.png)
- 平台湖南搜索（19 位、全部湖南）：[hunan-platform-search.png](assets/qa01/round2/hunan-platform-search.png)
- 修复前地域未加入：[region-selection-before-add.png](assets/qa01/round2/region-selection-before-add.png)
- 点击添加后：[region-selected-after-add.png](assets/qa01/round2/region-selected-after-add.png)
- PG-03 分页 20→21：[pg03-21.png](assets/qa01/round2/pg03-21.png)
