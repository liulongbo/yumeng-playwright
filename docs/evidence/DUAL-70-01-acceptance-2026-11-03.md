# DUAL-70-01：巨量星图与磁力聚星单任务 70 位真实采集能力验收报告

状态：**两平台 70/70 有效达人、唯一入库与前端展示均通过；聚星 `COMPLETED`，星图 `PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE`（资料完整 22/70）**  
开始时间：2026-11-03T20:38:11+08:00  
目标环境：`http://127.0.0.1:5173` 主站 + `xingtu_development` 主业务库 + 双平台专属执行单元  
关联任务卡：[DUAL-70-01](../tasks/DUAL-70-01.md)  
性能诊断：[DUAL-70-01 性能诊断报告](DUAL-70-01-performance-diagnosis-2026-11-03.md)

## 1. 结论（按平台分别判定）

| 平台 | 分页 3/4/5 真实验证 | 5 位核心闭环 | 70 位完整验收 | 结论 |
|---|---|---|---|---|
| 巨量星图 | **通过**：page 1—5 各 20 位、100 身份 0 重复；page 6 fail closed | **通过（数量）**：多次 5/5；终态 `PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE`；修复后 5 位 featured 5/5 | **数量通过**：`51dfca56…` `valid=70/70`、`task_creators` distinct=70、snapshots distinct=70、discovered=81、`visited_cursors=[null,"2","3","4"]`；终态 `PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE`（资料完整 22/70），失败步骤 0 | **PASS（数量/入库/前端）**；终态部分完成原因如实保留；严格“必须 COMPLETED”口径下不是完全通过 |
| 磁力聚星 | **通过**：page 1—5 各 20 位、100 身份 0 重复；page 6 fail closed | **通过**：`7587a87b…` target=5、有效 5、资料完整 5、快照 5、`COMPLETED`；突破旧 3 位限制 | **通过**：`f7a8f087…` `valid=70/70`、`task_creators` distinct=70、snapshots=70、profile=70、discovered=80、`visited_cursors=[null,"2","3","4"]`；终态 **`COMPLETED`**，失败 0 | **PASS（完整）** |

> 数量验收只认“本任务已持久化且唯一的有效达人”。候选数、页面行数、采集尝试次数不作为达标依据。两平台均达到 70 位唯一有效；星图终态为既有资料完整性规则导致的 `PARTIAL_COMPLETED`，不是数量/分页失败。

## 2. 当前真实上限与“3 位”的来源（调查结论）

### 2.1 当前真实生效上限

| 层 | 星图 | 聚星 | 证据 |
|---|---|---|---|
| 表单硬上限 | 200 | 200 | `RequirementForm.target_count` `ge=1, le=200`（[product_models.py:179](../../backend/src/xingtu/product_models.py#L179)） |
| 产品/运行时上限 | 200 | 修复前 30，修复后 200 | 修复前 `.runtime/m3-app.env` `=30`；代码无 env 时默认 3（[product_api.py:59-71](../../backend/src/xingtu/product_api.py#L59-L71)、`:92-94`） |
| 契约分页候选上限 | 修复前 page 3×20=60；修复后 page 5×20=100 | 修复前 page 2×20=40；修复后 page 5×20=100 | [douyin_xingtu.verified.json:3394](../../contracts/douyin_xingtu.verified.json#L3394)、[kuaishou_juxing.verified.json:2940](../../contracts/kuaishou_juxing.verified.json#L2940) |
| 历史真实完成 | 主库最大 24 位 | 主库 3 位（target=3）；隔离环境曾 22/22/22 | 主库 `root_tasks`；[KJX-01 全量回归](KJX-01-full-regression.md) |

**“实际最多 3 位”的真实原因**：主库最近两条聚星任务 `e5a8ca5b…`、`210b37c4…` 的 `target_count=3`（表单默认值），达到目标后正常 `COMPLETED`；引擎/Worker/Workflow 没有 3 位硬限制。`scripts/commands.py` 的 1..3 仅是内部 live smoke 保护，不是产品入口。

### 2.2 七个问题的事实回答

1. **当前真实生效的最大采集数量**：修复前，星图产品上限 200 但受契约 60 候选限制；聚星产品上限 30 且受契约 40 候选限制，主库实际完成 3。修复后，两平台产品上限均 200，契约候选上限 100（page 5）；70 位可达。
2. **限制来自哪里**：聚星表单默认 3（`CapabilityDTO` 旧公式）、聚星运行时 30/代码默认 3、两份契约分页边界；不是引擎/Worker 的 3 位限制。
3. **已验分页能力**：修复前星图 page 2 有真实任务证据、page 3 有真实只读请求证据但无产品任务跑过；聚星 page 2 有真实 22/22/22 证据；星图 page 4/5、聚星 page 3/4/5 未进入可执行合同。本轮已补齐两平台 page 3/4/5 真实 Adapter 证据。
4. **70 位是否存在技术阻断**：修复前存在明确阻断（60/40 候选 <70、聚星上限 30 <70）。修复后阻断解除；剩余风险是单段 7200s 预算、平台安全验证/登录态、可选模块完整性导致的 `PARTIAL_COMPLETED`。
5. **哪些地方需要修改代码**：两份 verified 契约分页边界/coverage gap；聚星产品上限默认值与表单默认目标；对应测试；验收工具与文档。**未改** Engine/Workflow/Adapter 解析/DB schema/前端业务页面。
6. **哪些只需调整配置**：聚星 `XINGTU_KUAISHOU_JUXING_MAX_TARGET_COUNT` 30→200（运行时私有配置）；表单默认 3→20（代码默认值，属产品契约对齐）。
7. **是否影响已验收功能**：只放宽上限和分页边界；历史任务/快照/达人/Profile/登录态未删除、未重写；`contract_version` 未提升，历史 retry/continue 不会因版本不匹配失败；既有 1/20 位任务行为不变。

## 3. 代码与配置变更

| 文件 | 变更 | 原因 |
|---|---|---|
| `contracts/douyin_xingtu.verified.json` | `page_fetch_max_verified` 3→5；coverage gap 记录 2026-11-03 page 1—5 真实验证；evidence_refs 增加本报告 | 真实候选上限从 60 提升到 100 |
| `contracts/kuaishou_juxing.verified.json` | `page_fetch_max_verified` 2→5；search/top-level coverage gap 更新；evidence_refs 增加本报告 | 真实候选上限从 40 提升到 100 |
| `backend/src/xingtu/product_api.py` | `_juxing_max_target_count()` 默认 3→200；`ProductSettings.kuaishou_juxing_max_target_count` 默认 3→200 | 移除阶段 B 的隐藏 3 位默认上限，与长期产品契约 200 对齐 |
| `backend/src/xingtu/product_models.py` | 聚星 `target_count_default` 3→20；`target_count_max` 默认 200 | 与星图及技术方案“默认 20、允许 1—200”一致，消除“默认只有 3 位”的误导 |
| `.runtime/m3-app.env`（私有，未提交） | `XINGTU_KUAISHOU_JUXING_MAX_TARGET_COUNT` 30→200 | 运行时配置与产品上限一致 |
| `backend/tests/unit/test_product_api.py` | 默认 20/200、target=70 可创建、配置化上限、env 默认 200 | 覆盖新契约 |
| `backend/tests/unit/test_juxing_adapter_v2.py` | 契约 page 5、page 5 解析、page 6 fail closed、sentinel 6/7 | 覆盖新分页边界 |
| `backend/tests/unit/test_search_contract_registration.py` | published 契约 page 5 + coverage gap | 覆盖契约发布 |
| `backend/tests/unit/test_intake.py` | target=70 经 `build_expected_plan` 保持 70 | 覆盖 P1 参数转换 |
| `backend/tests/integration/test_engine.py` | target=70 跨 4 页、稀疏页继续、第 5 页失败保留已采 60 位 | 覆盖持续采集、去重、失败不丢数据 |
| `scripts/acceptance/dual_70_*.py` | 新增真实分页探针、UI 任务驱动、只读 DB 核验 | 本轮验收工具，不进入生产运行路径 |
| `docs/development.md` | 聚星上限默认/主站 200、表单默认 20、双单元配置说明 | 运行文档与代码一致 |

**契约版本决策**：`contract_version` 保持不变。分页边界是向后兼容的能力放宽；提升版本会让历史任务 retry/continue 触发 `VERSION_MISMATCH`，违反“不破坏原有重试/继续采集”。本报告与契约 coverage gap 记录新的已验证边界。

## 4. 真实验证证据

### 4.1 会话门禁（只读）

| 平台 | 单元 | 状态 | 账号 | 证据 |
|---|---|---|---|---|
| 巨量星图 | `unit-local-mac-02` | `VALID` | `ID: 1807978499337419` | `.runtime/acceptance/dual-70-20261103/xingtu-session/` |
| 磁力聚星 | `unit-local-mac-03-juxing` | `VALID` | `60821564` | binding 20:40:35；探针每页会话校验 VALID |

### 4.2 分页探针（真实 Adapter，page 1—5）

| 平台 | 轮次 | page 1 | page 2 | page 3 | page 4 | page 5 | 跨页身份 | 重复 | page 6 |
|---|---|---|---|---|---|---|---|---|---|
| 星图 | 研究模式 | 20 | 20 | 20 | 20 | 20 | 100 | 0 | 未请求 |
| 星图 | 真实契约 | 20 | 20 | 20 | 20 | 20 | 100 | 0 | `SEARCH_CAPABILITY_LIMIT / PAGE_FETCH_LIMIT_NOT_VERIFIED` |
| 聚星 | 研究模式 | 20 | 20 | 20 | 20 | 20 | 100 | 0 | 未请求 |
| 聚星 | 真实契约 | 20 | 20 | 20 | 20 | 20 | 100 | 0 | `SEARCH_CAPABILITY_LIMIT / JUXING_PAGE_LIMIT` |

- 星图每页 `pagination.page` 与请求页码一致、`has_more=true`；聚星每页 `currentPage` 与请求页码一致、`total` 合理。
- 两平台每页 0 个 `unidentified` 候选；跨页身份集合 100 个全部唯一。
- 详细 JSON（含平台身份，私有 0600）：`.runtime/acceptance/dual-70-20261103/pagination-{xingtu,juxing}-{research,contract}.json`。

### 4.3 5 位小样本

| 平台 | 任务 ID | 目标 | 有效 | 资料完整 | 精选完整 | 发现 | 失败步骤 | 终态 | active_seconds |
|---|---|---|---|---|---|---|---|---|---|
| 星图 | `07efcced-5423-4f47-a079-65716bd88032` | 5 | **5** | 2 | 4 | 20 | 0 | `PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE` | 859.7 |
| 聚星 | `7587a87b-a22b-4f00-83de-74b963b31e3b` | 5 | **5** | 5 | 0 | 20 | 1 | **`COMPLETED`** | 169.3 |

- 星图 5 位：`task_creators` distinct=5、`creator_snapshots` distinct=5、重复 first_position=0、平台污染=0、单元释放正常。
- 聚星 5 位：`task_creators` distinct=5、`creator_snapshots` distinct=5、重复=0、平台污染=0、单元释放正常；**5>3，已突破旧的默认 3 位限制**。
- 星图 `PARTIAL_COMPLETED` 来自既有 `PROFILE_SCOPE_INCOMPLETE`（可选模块完整性），不是数量/分页失败；报告不把它写成“完整完成”。
- 前端：两任务详情均显示“有效入库 5 / 目标 5”，各 5 位可查看；聚星显示“已完成”，星图显示“部分完成”。

### 4.4 70 位完整任务

| 平台 | 任务 ID | 创建方式 | 目标 | 有效 | 唯一入库 | 快照 | 终态 | 结论 |
|---|---|---|---|---|---|---|---|---|
| 星图 | `51dfca56-54c9-4d02-a5e4-da29f0f7d719` | 5173 前端 | 70 | **70** | **70** | **102（70 distinct）** | **PARTIAL_COMPLETED** | **PASS（数量/入库/前端）**；资料完整 22/70 |
| 聚星 | `f7a8f087-2aa7-442b-bbcf-424c523509e9` | 5173 前端 | 70 | **70** | **70** | **70** | **COMPLETED** | **PASS（完整）** |

- 星图 70：`requirements.target_count=70`、`filter_plans.target_count=70`、keyword=宠物，真实 `unit-local-mac-02`。
- 星图 70 最终：`valid=70`、`task_creators` distinct=70、`creator_snapshots` distinct=70（共 102 份，含重试/补采的多份快照）、`discovered=81`、`visited_cursors=[null,"2","3","4"]`、`processed_operations=6`、`search_stop_reason=null`、`failure_counts={"PLATFORM_PAGE_CHANGED":2}`（前两次失败保留）、`active_seconds=7002.4`，失败步骤 0。
- 星图终态 `PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE`（资料完整 22/70、精选完整 61/70）：这是既有完成规则，**不是数量/分页失败**；前端显示“有效入库 70 / 目标 70”“已发现 81”“部分完成”，达人列表 API 返回 70 位。
- 星图曾两次因“商业能力”动作 90s 超时失败（32/70、33/70）；已按授权做 P0 修复（唤醒路径 + featured 路径局部化、同 tab 去重），5 位回归通过后，对同一 root task 两次使用前端“继续采集”，未新建重复任务、未重采已入库达人。
- 聚星 70：`requirements.target_count=70`、`filter_plans.target_count=70`、母婴 / 母婴亲子，真实 `unit-local-mac-03-juxing`；最终 `valid=70`、`task_creators` distinct=70、`creator_snapshots`=70、`profile_complete=70`、`discovered=80`、`visited_cursors=[null,"2","3","4"]`、`processed_operations=4`、`active_seconds=2177.3`、`failure_counts={}`、终态 **`COMPLETED`**，失败步骤 0。
- 聚星前端：任务详情显示“有效入库 70 / 目标 70”“已发现 80”“资料完整 70 全部完整”“已完成”，达人列表 API 返回 70 位；任务在星图终态后创建，两个 70 位任务未同时运行。
- 结构化证据：星图 `.runtime/acceptance/dual-70-20261103/db-xingtu-70-final.json`、`xingtu-70-resume2/02-task-detail.png`；聚星 `.runtime/acceptance/dual-70-20261103/db-juxing-70-final.json`、`juxing-70/02-task-detail.png`。

## 5. 数据库核验（小样本）

| 项 | 星图 5 | 聚星 5 |
|---|---|---|
| `task_creators` 行 / distinct | 5 / 5 | 5 / 5 |
| `creator_snapshots` / distinct | 5 / 5 | 5 / 5 |
| 重复 first_position | 0 | 0 |
| 跨平台行 | 0 | 0 |
| 星图投影行 | 5 | 0 |
| 精选集合 | 10 | 0 |
| 单元终态 | READY / browser_stopped / 无租约 | 同左 |

- 结构化核验：`.runtime/acceptance/dual-70-20261103/db-{xingtu,juxing}-5.json`。
- 5 个快照的模块覆盖：星图 `basic/commercial/fans/spread` 各 5，`seeding` 3、`creation` 4、`conversion` 2、`fulfillment` 3；聚星 `basic/spread/works/audience` 各 5。

### 5.1 星图 70 位 DB 核验

| 项 | 值 |
|---|---|
| `requirements` / `filter_plans` / payload plan target | 70 / 70 / 70 |
| `root_tasks.state` | `PARTIAL_COMPLETED` |
| `valid_count` | **70** |
| `task_creators` 行 / distinct | 70 / **70** |
| `creator_snapshots` / distinct creators | 102 / **70** |
| 重复 first_position | 0 |
| 跨平台污染行 | 0（仅 `douyin_xingtu`） |
| 星图投影行 | 70 |
| 精选集合 / snapshot_collections | 138 / 202 |
| checkpoint 候选 / `scanned_ids` / `visited_cursors` | 81 / 80 / `[null,"2","3","4"]` |
| `processed_operations` / `search_stop_reason` | 6 / null |
| `active_seconds` | 7002.4 |
| `failure_counts` | `{"PLATFORM_PAGE_CHANGED": 2}`（历史失败保留，不计入有效数） |
| 单元终态 | READY / browser_stopped / 无租约 |
| 结构化核验 | `.runtime/acceptance/dual-70-20261103/db-xingtu-70-final.json` |

> 70 位有效、70 位唯一、102 份快照（含重试/补采多份）与 `valid_count` 交叉一致；数量验收通过。资料完整 22/70 导致终态 `PARTIAL_COMPLETED`，这是既有完成规则，不是数量/分页失败。

## 6. 回归

| 检查 | 结果 |
|---|---|
| 后端 unit | **383 passed** |
| 后端 contract | **43 passed** |
| 隔离 PostgreSQL integration | **128 passed / 1 skipped** |
| Temporal E2E | **14 passed**（临时 6379 Redis 仅用于既有 E2E，验证后停止） |
| 前端 lint / test / build | tsc 通过；**106 passed**；build 通过 |
| Mypy | 38 source files，Success |
| Ruff / format | 改动文件通过 |

## 7. 未解决问题与后续

- 星图 70 位**数量验收已通过**（70/70、70 distinct、前端 70）；终态 `PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE`（资料完整 22/70、精选完整 61/70）。该终态是既有完成规则，不是数量/分页失败；若要求严格 `COMPLETED`，需要对同一任务“补采缺失字段（48 位）”，这会再访问 48 位已入库达人（不新增达人、不超过 70），需另行授权。
- 聚星 70 位已 **`COMPLETED` 70/70**，资料完整 70/70，失败 0；无需补采。
- page 6+ 与平台真实终点仍未验证；本轮只开放到 page 5（100 候选），实际两个 70 位任务使用到 page 4（星图 81 候选、聚星 80 候选），均未触发 page 5 上限。
- 星图两次因“商业能力”动作 90s 超时失败（32/70、33/70）；P0 修复（`_wake_unresolved_modules` + `_run_featured_interaction` 局部化、同 tab 去重）后 5 位回归通过，原任务两次前端“继续采集”补足 70；修复未改变字段契约/顺序/去重/有效性规则。
- 平台安全验证/登录态如阻断，将记录真实原因与已成功位数，不绕过、不虚报。
- 本轮未执行 Git commit/push/merge；未删除/覆盖历史任务、快照或达人；未修改账号、Profile 或登录态。

## 8. 最终判定（按用户口径）

| 平台 | 70 位有效 | 唯一入库 | 任务终态 | 前端展示 | 判定 |
|---|---|---|---|---|---|
| 巨量星图 | **70/70** | **70 distinct** | `PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE`（资料完整 22/70） | 70/70，部分完成 | **数量/入库/前端 PASS**；严格 `COMPLETED` 未满足 |
| 磁力聚星 | **70/70** | **70 distinct** | **`COMPLETED`**（资料完整 70/70） | 70/70，已完成 | **完整 PASS** |

- **按“单任务 70 位有效达人采集 + 唯一入库 + 前端展示”口径：两平台均通过。**
- **按“任务必须 `COMPLETED`”的严格口径：整体不判定为完全 PASS**，因为星图终态为 `PARTIAL_COMPLETED`，原因是既有资料完整性规则（22/70），不是数量/分页失败。
- 70 是本轮验收目标，不是产品上限；产品上限仍为 200，200 位未验收；page 6+ 未验证。
- 两个平台分别报告，不用一个平台的结果代表另一个平台。

## 9. 合规声明

- 两个 70 位任务严格顺序执行，从未同时运行；未创建 >70 位任务。
- 数量判定使用本任务 `task_creators` distinct + `creator_snapshots` distinct + `valid_count` 交叉核验，不使用候选数/页面行数替代。
- 证据目录 `.runtime/acceptance/dual-70-20261103/` 为私有（0700/0600），公开报告不含达人昵称、平台 ID、Cookie、Token 或响应正文。
