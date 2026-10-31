# KJX-01 阶段 C+ 功能完成证据（分页 / 筛选 / 详情字段）

状态：实现完成；真实平台回归完成（T1/T2/T3 全部通过；阶段 D-0 GO）  
更新时间：2026-10-30T00:20:00+08:00  
范围：磁力聚星（快手）在既有 Stage C 采集链路上补齐分页、已核验筛选和既有四模块详情字段；巨量星图既有采集链路不变。  
结论：**GO**。分页第 1→2 页真实验收、T1 五项筛选、字段扩展、账号选择提醒/人工接管与星图 T3 重试均通过；最终双平台 MCP **19 PASS / 0 FAIL**。阶段 C 的 macOS v1 GO 不受影响。

## 1. 本轮目标

用户本轮明确要求：不是再证明聚星能采 10 位达人，而是让聚星具备实际媒介业务所需的完整筛选、分页和资料获取能力；同时不能影响已满足需求的巨量星图正常流程。

完成边界：

1. **分页**：合同开放第 2 页（`page_fetch`），第 3 页起 fail closed；第 2 页必须重建完整筛选请求体，不能使用平台 UI 点击分页时丢筛选的通用体。
2. **筛选**：关键词、平台真实 38 个内容类目、粉丝量级、34 省/352 市地域、三档视频报价（单档互斥）；全部来自合同/页面回读，不硬编码猜测。
3. **详情字段**：只扩展既有 `basic / spread / works / audience` 四模块；不新增模块、不改变完成判定、不做数据库 Schema 变更。
4. **巨量星图回归**：星图合同、Adapter、完成判定、F04/F05/F06、已有字段与 UI 语义不变；真实星图任务回归另行执行。

## 2. 合同 v2

文件：`contracts/kuaishou_juxing.verified.json`（真实平台只读调查后生成，`require_enabled(live=True)` 通过）。

| 项 | 值 |
|---|---|
| capability_version | `juxing-video-square-stage-c-v2` |
| contract_version | `juxing-video-creator-stage-c-v2` |
| adapter_version | `juxing-browser-v2` |
| 搜索 | `page_fetch`；`page_fetch_max_verified=2`；`resume_supported=true`；`next_path=currentPage`；`exhausted_path=total` |
| 内容类型 | 38 个一级类目（页面 `starTagV2`）；每项含 id、sub_ids、select_first_level_id |
| 粉丝 | 6 个平台预设 + 自定义区间；count |
| 地域 | 34 个省级节点、352 个市级节点；平台 `address/list` 的 provinceCode/cityCode |
| 报价 | 1-20 秒 / 21-60 秒 / 60 秒以上三档；`priceType` 11/12/13；平台整数 = 元 × 1000；单档互斥 |
| 模块字段 | basic 18、spread 31、works 1 个结构化项、audience 2 个原始画像 |
| checkpoint 版本 | basic/spread/works = 2；audience = 1 |
| 显式边界 | 第 2 页已验证；第 3 页起 `SEARCH_CAPABILITY_LIMIT`；不新增履约/带货模块 |

旧 v1 聚星任务按现有版本边界只读、不可续跑；阶段 C GO 继续针对 v1 证据有效。

## 3. 实现

### 3.1 Adapter

`backend/src/xingtu/juxing_adapter.py`：

- 筛选请求体从合同 `request_mapping` / `region_tree` 读取；删除旧的硬编码母婴/北京/报价常量。
- 每页用同一 `FilterPlan` 重建完整请求体，仅改变 `currentPage`；关键词 + 任一筛选时 `pathSource=fuzzy_content_search_video`，纯关键词时 `precise_content_search_video`。
- 第 2 页在 `prepare` 中保留 cursor 并返回可续跑；`search()` 对 cursor 做数字/范围校验；超过 2 页 fail closed。
- 第 2 页沿用 `check_session`；`exhausted = currentPage × 20 >= total`；total 仍大于当前页却返回空页时抛 `JUXING_SEARCH_EMPTY_PAGE`，不伪装耗尽。
- 新增 basic 字段：gender、profile_url、content_form_labels、platform_identity、style_detail、public_settlement；报价项增加原价/有效期原始值。
- 新增 21 个 spread 字段：分位数、环比、近期 CPM/CPE、转化点击率、访客/深度访客、商业作品中位数/数量/完播/互动/时长/点赞/评论/分享。
- works item 增加 product_name / contains_paid / quality_hot / quantity_hot / quality_and_quantity_hot / first_industry_name；保留 cover_url。
- 合同期望的每个字段都发出 `FieldObservation`；缺失为 `NO_DATA`，不以 0 填充；`profile_complete` 仍由四模块完整性判定。

### 3.2 读模型

`backend/src/xingtu/product_queries.py`：

- 聚星达人库新增中性指标投影：`interaction_rate`、`completion_rate`、`play_median`、`average_duration`、`average_likes`、`average_comments`、`average_shares`。
- 星图专属 CPM/CPE 两档语义继续不映射到聚星；月连接/深度用户保持不适用，不把访客数冒充连接用户。
- 无数据库迁移、无新表/列。

### 3.3 前端

- 聚星表单：38 内容类目、粉丝预设/自定义（万→count）、完整省市、三档报价（一次一档）、目标数量；条件摘要与提交体。
- 聚星详情：性别/主页链接/内容形式/平台身份/风格/对公结算；报价原价/有效期；新增传播字段；作品封面与标签；受众画像维度表（性别/年龄/地域/城市/兴趣/活跃度/手机品牌/手机价格/九大人群/地域 TOP 占比/渗透）+ 原始 JSON 保留。
- 任务详情：`failure_reason` 在存在重试范围时仍显示；聚星条件摘要显示内容类型/粉丝/地域/报价。
- 巨量星图分支不变；星图表单/详情/F06 文案未改。
- 达人库/任务内达人聚星行显示互动/完播/播放中位数。

### 3.4 测试

| 层 | 结果 |
|---|---|
| 后端单元 + 合同 | **403 passed**（新增 adapter v2 15 条） |
| 隔离 PostgreSQL 集成 | **118 passed / 1 skipped**（全新 `xingtu_test_kjx_full` 数据库） |
| 全量 E2E | **14 passed** |
| 前端 | **103 passed** + `tsc` + `vite build` |
| 合同校验 | `require_enabled(live=True)` 通过 |
| 真实 MCP 设置阶段 | 6 PASS（双平台目录、聚星 7 项能力/38 内容/34 省/3 报价、双平台表单） |

## 4. 真实平台

### 4.1 T1（已完成）

- 任务：`f1f62c78-c0e9-495c-8863-08a8d56a6e0f`，聚星「母婴 / 母婴亲子 / 粉丝 10 万–100 万 / 北京 / 21-60 秒视频报价上限 10000 元 / target=3」。
- 从真实产品 UI 提交一次；`COMPLETED`。
- 发现 10、有效 3、资料完整 3、失败 0；3 位快照四模块均为 18/31/1/2 字段；pipeline complete。
- 任务详情条件摘要正确显示全部 5 项条件；3 位达人粉丝均在 10 万–100 万、报价满足、地域北京。
- 新增字段实际值示例：gender 女/女/男；profileUrl 有值；content form 科普/教学/教学；platform identity 原创扶持达人/潜力达人；public settlement 不支持对公；visitor_num 143531/90798/762818；deep_visitor_num 2731/339/11470；分位数/环比有值；recent CPM/CPE 与商业作品字段为 `NO_DATA`（保留缺失语义）。
- 作品 `cover_url` 有真实平台封面；受众画像原始维度齐全（sex/age/area/city/interest/activity/mobile brand/mobile price/nine groups/areaTop/areaTopPermeation），`cityLevelPercentage` 原始标签实为城市名，前端未把它标成城市等级。
- 证据：`.runtime/kjx-full/regression/mcp/t1-form.png`、`t1-task-detail.png`、`t1-report.json`；数据库快照与投影见隔离库 `xingtu_test_kjx_regression`；截图私有，不入 Git。

### 4.2 T2（已通过）

- 首次 T2-批准 `50cccb72...` 0/22：过期星图 maintenance + 正常子账号选择页误判；已专项定位并修复。
- **T2 最终任务 `56efbba5-d267-44a2-824a-2ba4e60f2dd9`**：聚星「母婴 / 母婴亲子 / target=22」，修复后同任务重试；**COMPLETED 22/22/22**，`visited_cursors=[None,"2"]`，40 候选（两页各 20），22 creators/snapshots，无第 3 页。
- 另有一个**测试驱动偏差任务**（T2-偏差，`7ec6a121-47a7-44a4-865a-de480e1fc263`）：目标同为 22，但驱动误选了北京地域；平台只返回 16 个候选并 exhausted，任务终态 **PARTIAL_COMPLETED 16/22（SEARCH_EXHAUSTED）**，无法覆盖第 2 页；该任务作为真实小样本保留、在报告中透明记录，不作为分页验收依据。批准 T2 的额外规模仍在用户批准的 worst-case 49 位内（3 + 16 + 22 + 1 = 42）。
- 分页验收：T2 最终任务 **22/22/22**，checkpoint `visited_cursors=[None,"2"]`，真实第 2 页候选与落库成立；无第 3 页请求。CONDITIONAL 条件已关闭。

### 4.3 T3（已完成重试）

- 星图「宠物 / target=1」首次：1 位有效后触发 `PLATFORM_SECURITY_CHALLENGE`，15 分钟超时，`PARTIAL_COMPLETED`（valid 1、profile 0，failure=`SECURITY_CHALLENGE_TIMEOUT`）；不绕过验证。
- 同范围重试（授权一次）：`ef1ed66e-724d-43c4-a49f-a084c4884491`，真实 UI 一次提交，**COMPLETED 1/1/1**，profile/pipeline complete；星图 F06/详情/库回归通过；既有星图代码未改。

## 5. 未完成 / 延后

- T2 最终第 2 页验收已通过；T2-偏差 16/22 仅第 1 页，仅作透明历史记录，不替代最终 T2。
- 看履约/看带货模块：平台可用，但新增模块会改变完成判定；本轮按批准范围不新增，仅记录。
- 第 3 页及以后：只读观察，不进入执行合同；第 2 页已开放。
- 聚星更新/补采/定时任务：不在本轮范围；页级 retry 的继续补数量能力受合同边界保护。
- 达人库库级历史/报价/作品观测 UI：未新增；现有聚星快照/投影读模型可用。
- Windows 验收：仍由 `DEPLOY-WIN-01` 承担。
- 生产 Feature Flag、正式业务库、Git 提交/推送：均未变更/未执行。

## 6. 约束遵守

- 未做无必要架构重构；未改星图 Adapter/合同/完成判定/F04/F05/F06。
- 未新增数据库表/列/迁移；未写生产库；未开启生产 Flag。
- 真实平台仅使用授权子账号 `60821564` 与小样本；无平台写操作；无扩大采集规模。
- 真实任务 T1/T2/T3 各从 UI 提交一次；T2-偏差 与 T3 同范围重试的额外规模透明记录（累计 43 位，仍在批准 worst-case 49 位内）。
- 所有缺失字段以 NO_DATA 表达，未伪造 0；未把平台原始 URL 当公开作品页。
