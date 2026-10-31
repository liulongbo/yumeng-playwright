# KJX-01：磁力聚星 P0 多平台接入

状态：进行中（阶段 C macOS GO 有效；阶段 D-0 **GO**：T1/T2/T3 全部通过，T2 22/22/22 且真实第 2 页；Windows 移交 DEPLOY-WIN-01）  
更新时间：2026-10-30T23:10:00+08:00  
是否验收：macOS P0 / 阶段 C 已通过（C1 环境、C2 聚星 1 位、C3 聚星 10 位、C4 星图回归与双平台隔离）；KJX-01 总体待 Windows 单独验收。生产业务库、生产 Feature Flag、Windows 仍未变更/未执行。

## 目标与范围

在保持巨量星图核心业务行为兼容的前提下，将磁力聚星作为第二个平台接入现有任务中心、ExecutionUnit、Temporal、达人身份/快照与前端。一个任务只对应一个平台；两个平台共用执行单元资源池，并在同一单元内严格串行。

本卡 P0 包含：平台选择与 Feature Flag、磁力聚星最小筛选模型和能力合同、任务平台持久化、执行单元平台绑定、Adapter 选择边界、平台隔离展示、迁移与离线/隔离测试。P0 不包含直播、电商/履约深层数据、联系方式、写入平台的下单/导出操作、跨平台自然人合并、跨平台指标比较，且不改变现有任务优先级及更新任务在达人边界让出单元的语义。

## 关联与依赖

- 产品依据：用户确认的《磁力聚星接入 PRD 与技术方案：精准修订版》。
- 技术依据：[完整技术方案](../AI达人智能发现与采集系统-完整技术方案.md)第 13—16、18 章；[DATA-01](DATA-01.md)、[RETRY-01](RETRY-01.md)、[UNIT-01](UNIT-01.md)。
- 复用：`allowed_task_kinds`、任务检查点/continue/backfill、`platform + platform_creator_id`、执行单元租约及 BrowserHost 实时会话检查。
- 平台能力前置：阶段 B 可执行合同仅将已实测的关键词、母婴亲子、搜索第一页及四个详情模块标记为 `verified`；阶段 D-0 在只读调查和真实回归授权下，将合同升级为 v2（第 2 页、粉丝/地域/38 内容类目/三档报价、既有四模块字段扩展），第 3 页起与高级模块仍不得进入可执行合同。

## 验收清单

- [x] 一个任务只对应 `douyin_xingtu` 或 `kuaishou_juxing`；旧任务和旧请求保持星图默认语义。
- [x] 磁力聚星默认关闭；关闭时前端入口、任务创建及调度均拒绝聚星任务，星图行为不变。
- [x] macOS 阶段 C 使用隔离 DB/API/Vite/Temporal/Worker；真实 DeepSeek、Chrome、双平台 Profile、合同、Flag 与任务/达人库 API 验收通过。
- [x] P0 表单与确定性模型仅包含关键词、内容类型、粉丝数、地域、三档视频报价和目标数；未验证能力不能进入 live 执行。
- [x] 任务中心显示平台，任务分配同时校验 `allowed_task_kinds` 与执行单元平台绑定。
- [x] 同一逻辑执行单元可配置独立的平台账号、Profile 和 registry；旧单平台配置无需修改即可运行。
- [x] BrowserHost/Adapter 的受保护页实时检查仍是登录权威，数据库只保存带时间的最近观察结果。
- [x] 磁力聚星 Adapter 遵守现有 SearchPage/Checkpoint/CreatorRef/快照契约；阶段 B 合同开放关键词、母婴亲子和搜索第一页，未验证分页 fail closed。
- [x] 达人身份继续使用 `(platform, platform_creator_id)`；1 位真实样本形状已在隔离 PostgreSQL 验证当前投影、原始值、不可变快照与星图表隔离。
- [x] 聚星专用 Profile 可在正常关闭后冷启动恢复；受保护找达人页与绑定子账号 `60821564` 精确匹配后才允许执行，另一个子账号不能被静默接受。
- [x] 真实只读目标数 1 闭环达到 `COMPLETED`：搜索、详情四模块、标准化、当前投影、不可变快照与任务完成判定均通过，验证后随机测试 Schema 已删除。
- [x] continue/backfill、取消、部分完成及现有优先级语义没有被重写。
- [x] 巨量星图单元、契约、集成及前端回归通过。
- [x] 磁力聚星已入库达人可通过统一达人库按平台筛选、查看列表与详情；平台专属字段保留原始单位/窗口，缺失不显示为 0，同名/同 ID 跨平台不合并。
- [x] 任务中心、任务详情与任务内达人按平台展示；聚星不显示 F06/精选计数或星图文案。
- [x] 隔离 Temporal E2E：API→Intake→Temporal→Worker→聚星配置/Adapter→Engine→DB→任务终态→API/达人库，平台、账号、Profile、合同与数据隔离均有断言。
- [x] 隔离全栈界面：真实 Uvicorn + 随机测试 Schema + 真实登录 + Chromium，聚星库/详情/任务/任务内达人读取真实数据库。
- [x] 真实聚星「母婴 / 母婴亲子 / 10 位」端到端验收完成：`COMPLETED`，有效/资料完整/快照均 10，仅使用第一页，未开发第二页。
- [x] 真实星图「宠物 / 目标 1」回归完成（含一次真实重试）：`COMPLETED`，资料完整 1、F06 双集合完整 1；同一单元双平台串行、账号/Profile/数据隔离成立。
- [ ] Windows 配置路径与 Profile 绑定不依赖 POSIX 专属语义（移交 [DEPLOY-WIN-01](DEPLOY-WIN-01.md)）。

### 阶段 D-0（2026-10-29）：分页 / 筛选 / 详情字段补齐与双平台回归（进行中）

- [x] 首轮 Playwright MCP + Chrome 真实用户冒烟：57 例，49 PASS / 4 FAIL / 2 BLOCKED / 2 NOT_RUN；证据 [KJX-01-full-test-cases](../evidence/KJX-01-full-test-cases.md)。
- [x] 真实平台只读调查：第 2/3 页、筛选面板/请求映射、详情各 tab 字段清单；证据 `.runtime/kjx-full/probe/`。
- [x] 聚星合同 v2：分页 page_fetch 边界、已核验筛选、既有四模块字段扩展；不新增必填模块；`require_enabled(live=True)` 通过。
- [x] Adapter：第 2 页请求、断点续跑、空页/失败/上限语义；筛选请求映射来自合同；新增 adapter v2 专项 15 条。
- [x] 前端：粉丝/地域/报价表单、画像维度表、作品封面/标签、任务详情失败原因与条件摘要。
- [x] 自动化回归：后端单元+合同 403、隔离集成 118/1 skipped、E2E 14、前端 103 + lint/build。
- [x] 新隔离栈全量 MCP 回归 + 授权真实任务 T1/T2/T3：T1 `COMPLETED 3/3/3`；T2 最终 `56efbba5...` **COMPLETED 22/22/22**（`visited_cursors=[None,"2"]`，40 候选，22 snapshots，无第 3 页）；T3 首次验证超时、同范围重试 `COMPLETED 1/1/1`；T2-偏差 16/22 仅作历史记录；最终 MCP **19 PASS/0 FAIL**。
- [x] 4 份交付文档 + 卡片更新；最终 **GO**（阶段 D-0 macOS 范围）。
- [x] 子账号选择专项：正常页面识别、`ACCOUNT_SELECTION_REQUIRED` 提醒/接管、正确/错误账号、超时原因、过期跨平台验证清理；见 [专项诊断](../evidence/KJX-01-T2-account-selection-diagnosis.md)。

## 实现记录

- 2026-10-26：建立实施卡并进入进行中。确认现有 `allowed_task_kinds` 已能表达仅手动、仅定时、手动+定时三种资格组合；本卡不新增执行单元模式字段，不按平台拆分资源池，不修改现有 `collection > manual_update > scheduled_update` 优先级。
- 2026-10-27：完成迁移 020、任务平台模型、P0 Requirement/FilterPlan v3、执行单元平台绑定、按平台 Profile/registry 选择、Adapter 工厂、Feature Flag 三重门禁、任务/执行单元平台展示和兼容性测试。旧 UnitConfig 自动映射为星图单绑定；平台绑定的账号/Profile/registry 不可静默变更，`enabled` 可运维启停。
- 2026-10-27：通过已登录 Playwright MCP 对关键词、粉丝、地域及三档报价完成低风险应用与回读；内容类型只有选中状态、缺独立摘要/结果差异。页面出现多次 Network Error，平台总合同继续为 `observed`，未启用聚星入口。
- 2026-10-27：用户明确授权阶段 B 真实小样本验证；限定专用聚星 Profile、独立测试库、1–3 位达人和只读平台操作。开始核对 Profile 隔离、搜索/详情契约、Adapter 与持久化路径。
- 2026-10-28：完成 1 位真实详情小样本的五个只读模块回读；确认 `userId` 为身份、`starId` 仅作详情导航、报价平台整数按 1/1000 元标准化。完成聚星 Adapter、平台能力 API/任务门禁、AI Intake 按平台合同选择及隔离库持久化专项测试。阶段 B 服务端硬限制最多 3 位，生产 Feature Flag 保持关闭。
- 2026-10-28：建立 Worker 专用持久化聚星 Profile 并验证 Profile 锁可独占。正常关闭人工 Chrome 后，聚星会话级登录状态未随 Profile 自动恢复；无快照 Worker 检查返回 `INDETERMINATE / NO_REGISTERED_SESSION_SIGNAL`，人工维护窗口等待登录后超时。因会话快照包含 Cookie，未获单独明确同意前拒绝导出或保存。
- 2026-10-28：用户明确同意将聚星专用会话快照保存在本机 `.runtime` 私有目录。先修复共享执行单元的快照隔离：星图继续沿用 `unit_id.json`，聚星改用 `unit_id.kuaishou_juxing.json`，避免覆盖星图。聚星快照已按 `0600` 保存，但首次重启回读仍为 `INDETERMINATE`、账号未匹配，因此只证明“独立快照已落盘”，尚未证明“登录可恢复”。
- 2026-10-28：新增阶段 B 本地维护入口 `scripts/juxing_login_maintenance.py`。该进程独占聚星 Profile 与 Playwright Context，不暴露 CDP、不连接业务库；最长保持窗口 8 小时，检测到注册账号与受保护页面同时匹配后保存聚星独立快照，但直到显式停止文件或超时才关闭窗口。已通过 Ruff、Mypy strict 与 Python 编译检查，并由 macOS 用户级 `launchd` 启动；首次启动状态为 `WAITING_FOR_OPERATOR`，入口为聚星短视频找达人，后续冷启动验证已通过并正常停止。
- 2026-10-28：用户确认当前账号下有两个均可访问找达人/详情的子账号，本次绑定子账号 ID 为 `60821564`。聚星合同新增 `__accountId__` URL 账号证据；冷启动和详情导航同时绑定外层与 SPA 路由参数，正式 `BrowserHost` 人工维护等待入口也复用该证据。DOM 账号证据仍优先，URL 参数冲突或其他子账号返回 `ACCOUNT_MISMATCH`。搜索页承担子账号实时校验，详情页承担达人身份校验，避免把详情页没有账号控件误判为会话失效。
- 2026-10-28：专用会话快照正常关闭后冷启动成功，无需再次人工登录，得到 `VALID / PROTECTED_PAGE_AND_URL_ACCOUNT_VERIFIED / account_match=true`。新增 `scripts/juxing_stage_b_smoke.py`，强制仅连接 `xingtu_test*` 数据库、随机 Schema、真实只读目标数 1，并复用 `BrowserHost → KuaishouJuxingAdapter → Engine → Repository`。首次真实执行暴露“无聚星精选集合仍要求星图 F06”的完成判定耦合；仅对聚星且合同未登记精选集合时改为资料模块完整即流水线完整，星图两组精选规则不变。最终真实复跑为 `COMPLETED`，Schema 核对后删除。
- 2026-10-28：完成后端聚星统一达人库读模型（无新增表）：`ProductQueries` 按 `platform` 分流，聚星列表/详情读 `platform_creators.projection` + 最近一条 `creator_snapshots`；只开放省/市/粉丝区间/完整性/`updated_at|followers`，星图专属筛选显式拒绝；聚星不适用子资源（报价/历史/作品观测/精选）与手动更新返回显式 not-applicable，避免“达人存在却报未找到”。`CreatorSummary.platform` 随任务结果返回；字段目录改为按平台读取。
- 2026-10-28：完成前端平台化：达人库平台切换与聚星行；聚星详情复用现有详情骨架，章节为 `基础资料 / 传播表现 / 代表作品 / 受众画像`，展示平台原值/单位/统计窗口、报价原值与“整数÷1000=元”、作品文本与计数、画像平台原始结构；任务中心与任务内达人隐藏 F06/精选并切换指标组，聚星不再请求星图专属子资源。
- 2026-10-28：定位并修复两个阻塞缺陷：① 迁移 013 的 `requirements.schema_version` 约束未允许 `requirement_form.v3`，经用户授权后在未应用的迁移 020 中重建为 v1/v2/v3（不新增表/列、不触正式库）；② `IntakeProcessor` 原对所有平台套用星图 `profile_requirements.json`，聚星任务会永久 `PARTIAL_COMPLETED`，现按平台选择，聚星 P0 由自身 registry 四模块决定完整性，星图保持不变。
- 2026-10-28：完成隔离 Temporal 全链路测试（真实 FastAPI + PostgreSQL + Temporal 测试服务器 + `Activities.collect`，合成 LLM/Adapter 与假 BrowserHost）与真实 Chromium 产品页测试；另以真实 Uvicorn + 随机测试 Schema + 真实登录验证聚星库/详情/任务读取真实数据库。断言包含平台/合同/账号/Profile/Adapter 选择、四模块完成、`COMPLETED`、计数、快照、星图投影 0 与跨平台隔离。
- 2026-10-29（阶段 D-0）：首轮 MCP + Chrome 真实用户冒烟完成（57 例，49 PASS / 4 FAIL / 2 BLOCKED / 2 NOT_RUN）；失败为已知基线缺口（更多详情字段、画像可读性、作品封面）与任务详情未展示 failure_reason；未提交真实任务、未访问平台、未改代码。
- 2026-10-30（阶段 D-0）：合同 v2（`juxing-video-square-stage-c-v2` / `juxing-browser-v2`）完成并通过 live 校验；Adapter 从合同读取 38 内容类目、粉丝/地域/三档报价映射，补齐第 2 页请求重建、区间校验、空页异常、超界 fail closed、断点续跑，新增 basic 6 字段、spread 21 字段、works 6 个 item 键；前端补齐聚星表单/详情/画像维度表/作品封面/失败原因/条件摘要；读模型新增互动/完播/播放中位数等中性指标；无 Schema 变更、无星图逻辑改动。自动化：后端单元+合同 403、隔离集成 118/1 skipped、E2E 14、前端 103 + lint/build、adapter v2 专项 15。
- 2026-10-30（阶段 D-0 真实栈）：新隔离栈（DB `xingtu_test_kjx_regression`、API 4192、Vite 4193、Temporal 57235、Redis DB15、单元 `unit-local-mac-02-kjx-full`、max target 30）。MCP 设置 6 PASS；T1（母婴/母婴亲子/10万–100万/北京/21-60秒上限10000元/target=3）`COMPLETED`，发现 10、有效 3、资料完整 3、失败 0，三位四模块均 18/31/1/2。复制 Profile 在本机 Keychain/持久上下文下被平台判为无会话（`NO_REGISTERED_SESSION_SIGNAL`），改用空 Profile + 单元私有核验快照后 T1 自动重试成功；失败计数保留，不伪报。
- 2026-10-30（阶段 D-0 终态）：T2-偏差（误加北京地域）`PARTIAL_COMPLETED 16/22`、`SEARCH_EXHAUSTED`，只到第 1 页，不用于分页验收。T3 首次 1 valid 后平台安全验证超时；授权的一次同范围重试 `ef1ed66e-...` **COMPLETED 1/1/1**。
- 2026-10-30（T2 专项）：专项定位确认首次 T2 的 page 是**正常磁力聚星子账号选择页 + 过期星图 verification 状态未清理 + 账号选择未识别/未通知**。最小修复：过期状态清理、`ACCOUNT_SELECTION_REQUIRED` 合同/Adapter/worker/前端提醒/接管/超时、v3 pristine plan adopt。T2 最终 `56efbba5-d267-44a2-824a-2ba4e60f2dd9` **COMPLETED 22/22/22**，`visited_cursors=[None,"2"]`，40 候选、22 snapshots、无第 3 页；最终 MCP **19 PASS/0 FAIL**。阶段 D-0 **GO**。
- 2026-10-28（阶段 C）：搭建 macOS 隔离栈（DB `xingtu_test_stage_c`、Temporal 57234、API 4190、Vite 4191、Redis DB14、独立聚星/星图 Profile），验证真实 DeepSeek、Chrome 156、双平台会话、Flag 与合同；迁移 020 专项测试覆盖旧星图库回填、v3 约束与幂等。
- 2026-10-28（C2）：从前端真实提交聚星「母婴 / 母婴亲子 / 目标 1」，经 DeepSeek→FastAPI→Temporal→Worker→Chrome/Profile→Adapter→PostgreSQL 达到 `COMPLETED`；有效/资料完整均为 1，四模块完整，星图投影 0；对同一详情做只读源对照全部通过。前两次真实任务因聚星入口 `Page.goto` 偶发 30 秒超时失败，第三次成功。
- 2026-10-28（C3）：从前端真实提交「母婴 / 母婴亲子 / 目标 10」，`COMPLETED`；有效 10、资料完整 10、快照 10、平台身份唯一 10，1 个 `IDENTITY_UNREADABLE` 候选未计入；仅使用第一页 20 位，未实现/未调用第二页。两位抽样源对照：一位 12/12，另一位 11/12（可选的近 30 天涨粉数采集时 `NO_DATA`，其率值一致）。
- 2026-10-28（C4）：真实星图「宠物 / 目标 1」第一次任务因候选 `fans` 响应 JSON 解析失败及 `MISSING_SOURCE` 返回 `PARTIAL_COMPLETED`（资料完整 0、F06 1）；同一授权样本重试任务 `COMPLETED`，8 个资料模块完整，F06 `excellent_reach`/`excellent_seeding` 各 4 卡片，资料覆盖 80 收集/0 失败/1 无数据。C4 第一次任务在 C3 运行期间提交并保持 `QUEUED`，C3 完成后才执行，证明同单元跨平台串行。
- 2026-10-28：新增聚星导航回退（首次 `domcontentloaded` 超时后按已注册就绪面继续，或 `commit` + 就绪面重试；登录/挑战/账号仍由 `check_session` 校验），并新增 2 条单元回归。聚星详情同时区分「统计接口平均值」与「页面作品波动前 15 个作品均值」，避免口径混用；任务内达人/达人库的月涨粉率统一按百分比显示（与详情一致）。

## 验证证据

- [KJX-01 阶段 A 实施与验证证据](../evidence/KJX-01-stage-a-implementation-2026-10-27.md)。
- [KJX-01 阶段 B 真实小样本证据](../evidence/KJX-01-stage-b-live-sample-2026-10-27.md)。
- 自动回归：后端单元 334；隔离 PostgreSQL 集成 109 passed / 1 skipped；合同 40；前端 89 + build；本地前端 E2E 2；Ruff、format、Mypy strict 通过。
- 阶段 B 最终回归：后端单元 339；隔离 PostgreSQL 集成 110 passed / 1 skipped；浏览器合同 43；前端沿用本卡既有 90 + build；Ruff、Mypy、`git diff --check` 通过。聚星专项持久化 1 passed。
- 持久登录维护入口：`.venv/bin/ruff check scripts/juxing_login_maintenance.py`、`.venv/bin/mypy --strict scripts/juxing_login_maintenance.py`、`.venv/bin/python -m py_compile scripts/juxing_login_maintenance.py` 均通过；运行状态文件仅记录非秘密会话结论，不记录 Cookie、Token 或请求正文。
- 真实阶段 B 冒烟报告保存在本机私有 `.runtime/juxing-stage-b/smoke-report.json`（`0600`）：`COMPLETED`、目标/有效/完整均为 1、快照 1、星图投影 0、会话账号匹配；只保留达人 ID 哈希，不保存昵称或字段正文。
- 阶段 D-0 自动化：后端单元+合同 **403 passed**；隔离 PostgreSQL 集成 **118 passed / 1 skipped**；E2E **14 passed**；前端 **103 passed** + `tsc` + `vite build`；adapter v2 专项 **15 passed**。
- 阶段 D-0 真实 MCP：设置 **6 PASS**；T1 `COMPLETED`（3/3/3，18/31/1/2，五条件）；T2 最终 `COMPLETED 22/22/22`（`visited_cursors=[None,"2"]`，40 候选，22 snapshots）；T3 同范围重试 `COMPLETED 1/1/1`；最终 **19 PASS/0 FAIL**。证据 `.runtime/kjx-full/regression/`（私有 0700；截图/报告不入 Git）。
- T2 专项诊断/修复：[KJX-01-T2-account-selection-diagnosis](../evidence/KJX-01-T2-account-selection-diagnosis.md)；后端单元+合同 **404**、前端 **104**、最终 MCP **19/0**。
- 阶段 D-0 交付文档：[功能完成证据](../evidence/KJX-01-feature-completion.md)、[全量回归报告](../evidence/KJX-01-full-regression.md)、[全量测试用例](../evidence/KJX-01-full-test-cases.md)、[平台差距分析](../design/KJX-01-platform-gap-analysis.md)。
- 冒烟结束后只读查询 `information_schema.schemata`，`kjx_stage_b_%` 残留 Schema 数为 0；真实样本未留在测试数据库。
- 阶段 B 产品闭环证据：[KJX-01 阶段 B 产品业务闭环证据](../evidence/KJX-01-stage-b-product-integration-2026-10-28.md)。
- 阶段 B 产品闭环回归：后端单元 + 合同 384 passed；隔离 PostgreSQL 集成 113 passed / 1 skipped（MinIO 未配置）；全量 E2E 14 passed（含聚星 Temporal 2、聚星产品页 2、隔离全栈 UI 1）；前端 98 passed + lint + build；Ruff（本卡范围）、Ruff format（本卡范围）、Mypy strict、`git diff --check` 通过。
- 阶段 D-0 首轮冒烟：[KJX-01-full-test-cases](../evidence/KJX-01-full-test-cases.md)；MCP 报告 `.runtime/kjx-full/round1/mcp/report.json`（私有）、DB 基线 `.runtime/kjx-full/round1/db-baseline.json`、健康 `.runtime/kjx-full/round1/health.txt`。
- 阶段 C 最终回归：后端单元 + 合同 **388 passed**；隔离 PostgreSQL 集成 **118 passed / 1 skipped**；迁移 020 专项 **2 passed**；聚星导航回退专项 **6 passed**；E2E **14 passed**；前端 **99 passed** + lint + build；Ruff/format（本卡改动文件）、Mypy strict（5 个核心后端文件）、`git diff --check` 通过。全仓 `make check` 仍受既有 11 个 `scripts/acceptance` `UP031` 阻断，与本卡无关。
- UI 证据截图保存在本机私有 `.runtime/test-artifacts/kjx-stage-b/`（含聚星库列表/详情/任务/任务内达人，以及真实 API+DB 全栈页面），不提交 Git。
- `make check` 仍受 11 个既有 acceptance `UP031` 阻断；本卡改动范围静态检查通过。
- 已运行 1 位真实只读采集、隔离产品闭环与阶段 C 真实 C1—C4；未运行真实业务库迁移、生产 Feature Flag、Windows 或平台写操作；未提交 Git。

## 交接信息

macOS 阶段 C 已完成：隔离栈上真实 DeepSeek、Temporal、Worker、Chrome/双平台 Profile、Adapter、PostgreSQL 与前端 UI 闭环通过；C2 聚星 1 位、C3 聚星 10 位、C4 星图 1 位重试均达到 `COMPLETED`，同单元跨平台串行与账号/Profile/数据隔离有证据。阶段 D-0 在当前隔离栈补齐聚星第 2 页、粉丝/地域/38 内容类目/三档报价筛选和既有四模块字段；T1 真实五项筛选、T2 最终 22/22/22 第 2 页、T3 重试星图回归均已完成，**阶段 D-0 GO**。KJX-01 总体仍保持“进行中”，仅因 Windows 实机/配置验收已按用户要求拆到 [DEPLOY-WIN-01](DEPLOY-WIN-01.md)。生产 Feature Flag 继续关闭，正式业务库未迁移/未写入；第 3 页+、更新/补采/定时和看履约/看带货模块仍不进入当前可执行合同。

## 状态历史

- 2026-10-26T23:07:30+08:00：建立 → 进行中；用户明确授权按精准修订版实施，保留真实平台验收单独授权边界。
- 2026-10-27T19:52:53+08:00：进行中 → 阻塞；阶段 A 代码、迁移文件、隔离回归及低风险页面验证完成。因合同不完整且页面存在网络错误，拒绝伪造 live Adapter 或启用平台入口。
- 2026-10-27T20:08:00+08:00：阻塞 → 进行中；用户明确授权使用独立测试库与专用聚星 Profile 采集 1–3 位真实达人，以完成 Adapter、字段映射和持久化闭环；生产开关和实际业务库仍禁止。
- 2026-10-28T01:08:00+08:00：进行中；1 位详情的真实只读响应、Adapter 映射及隔离 PostgreSQL 持久化已通过。等待建立 Worker 管理的持久化聚星 Profile 并由用户人工登录后，再验证 Profile 重启与真实任务端到端。
- 2026-10-28T01:32:00+08:00：进行中；专用 Profile 与锁隔离成立，但无会话快照时重启无法恢复聚星登录。等待用户决定是否允许仅在 `.runtime` 私有目录保存含 Cookie 的 `0600` 会话快照；未授权前不执行。
- 2026-10-28T02:05:00+08:00：进行中；用户已授权私有会话快照，聚星独立快照已保存且未覆盖星图，但首次重启验证仍为 `INDETERMINATE`。后续先修会话恢复/定位器证据，再执行 1 位真实 Adapter 端到端；不得把长会话或额度中断造成的窗口超时当成用户未操作。
- 2026-10-28T11:57:00+08:00：进行中；用独立、最长 8 小时的维护进程替换短时登录窗口，聚星专用 Chrome 已稳定停留在找达人入口并等待人工登录。登录后仍须完成快照落盘、正常停止和 Worker 冷启动账号匹配验证。
- 2026-10-28T16:16:00+08:00：进行中；阶段 B 小样本闭环已通过。双子账号场景下精确绑定 `60821564`，快照冷启动恢复和 1 位真实 `COMPLETED` 隔离持久化成立；总体任务因 Windows 与阶段 C 未完成而不标记已完成。
- 2026-10-28T22:35:00+08:00：进行中；阶段 B 产品业务闭环完成。统一达人库聚星读模型、任务中心/详情/任务内达人平台化、隔离 Temporal 全链路与真实 API+DB+Chromium 全栈界面均通过；修复 requirements v3 约束与 Intake 星图字段清单误套两个阻塞缺陷。阶段 C/Windows/真实平台 Temporal/10 位仍未完成，生产 Flag 与业务库未变更。
- 2026-10-28T23:55:00+08:00：进行中；macOS 阶段 C 通过。C1 隔离栈/真实 DeepSeek/双平台会话/迁移 020；C2 聚星 1 位、C3 聚星 10 位均 `COMPLETED`；C4 星图 1 位首次 `PARTIAL_COMPLETED`、同授权样本重试 `COMPLETED` 且 F06 双集合完整；同单元串行与账号/Profile/数据隔离成立。新增聚星导航回退与作品波动/统计接口口径区分。Windows 移交 DEPLOY-WIN-01；生产 Flag/业务库未变更。
- 2026-10-29T23:05:00+08:00：进行中；阶段 D-0 首轮 MCP + Chrome 冒烟完成（57 例：49 PASS/4 FAIL/2 BLOCKED/2 NOT_RUN）。失败项为已知基线缺口（详情字段、画像可读性、作品封面、任务详情 failure_reason 未展示）；未提交真实任务、未访问平台、未改代码。进入只读平台调查。
- 2026-10-30T00:22:00+08:00：进行中；阶段 D-0 合同 v2/Adapter/前端/读模型/自动化完成；T1 真实五项筛选任务 `COMPLETED 3/3/3`，四模块 18/31/1/2；T2-批准与 T3 执行中，T2-偏差透明记录。阶段 C macOS GO 继续有效；最终 GO/CONDITIONAL/NO-GO 待 T2/T3 终态与双平台回归。
- 2026-10-30T01:00:00+08:00：进行中；阶段 D-0 **CONDITIONAL GO**（历史）。T2-批准 0/22 为过期星图 maintenance + 正常子账号选择页误判。
- 2026-10-30T23:10:00+08:00：进行中（仅 Windows）；阶段 D-0 **GO**。T2 最终 56ef **COMPLETED 22/22/22**、`visited_cursors=[None,"2"]`、40 候选、22 snapshots、无第 3 页；T1 3/3/3；T3 重试 1/1/1；最终 MCP **19/0**；账号选择专项修复/提醒/接管/超时。阶段 C macOS v1 GO 继续有效；Windows/DEPLOY-WIN-01、生产 Flag/正式库、看履约/看带货/第 3 页+仍不在本轮范围。
