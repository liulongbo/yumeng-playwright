# LIVE-02：巨量星图 / 磁力聚星「直播广场」达人采集扩展

状态：**已完成（CONDITIONAL GO，2026-11-05）**
建立时间：2026-11-04T20:44:00+08:00
最近更新：2026-11-05T00:50:00+08:00
是否验收：是（核心验收通过；6 条 BLOCKED、12 条 NOT_RUN 见测试用例与残余风险）

## 目标与范围

在现有双平台短视频采集能力之上，新增两平台「直播广场」达人采集，保持短视频能力零回退：

1. 双平台直播场景选择与直播采集任务（关键词/达人 ID + 目标数）。
2. 直播独立契约、Adapter、字段解析、持久化与不可变快照。
3. 直播达人库、直播详情、独立手动更新。
4. 统一任务中心场景标识/管理；复用现有执行单元与并发互斥。
5. 直播单任务默认 20、**最大 70**（两平台统一）；跨页、去重、checkpoint/继续采集。
6. 现有短视频采集/详情/更新/定时更新保持；仅实施已批准的两处共享逻辑修改并回归。
7. 第三阶段用 Playwright MCP + Chrome 完成两平台小样本闭环、两平台真实 70 位直播采集、短视频回归。

不包含：

- 直播筛选器逐项开发（D1：只调研）。
- 空条件/「不限」直播采集（D2：必须关键词/ID）。
- 直播定时更新；聚星短视频手动更新历史缺口（D7）。
- 新执行单元/队列/Profile；跨平台身份合并；无关重构。

## 正式裁决（2026-11-04）

| 编号 | 裁决 |
|---|---|
| D1 | 同意：首版只做关键词/达人 ID + 目标数；其他筛选只调研 |
| D2 | 同意：必须输入关键词或达人 ID；不开放空条件 |
| D3 | 同意：仅已有直播数据的达人显示独立直播更新入口 |
| D4 | 同意：直播详情独立路由 `/creators/:id/live`，支持双场景切换 |
| D5 | 同意：共享 `platform_creators` 身份；直播/短视频数据分别存储/读取/更新 |
| D6 | 调整：直播默认 20、**最大 70**（两平台统一）；取消直播 200 位上限；短视频上限/行为不变 |
| D7 | 同意：不补齐聚星短视频手动更新缺口 |

## 关联与依赖

- 规范：[AGENTS.md](../../AGENTS.md)、[docs/agent.md](../agent.md)。
- 业务契约：[技术方案](../AI达人智能发现与采集系统-完整技术方案.md) §13、§19。
- 研究规则：[DEC-006](../decisions/DEC-006-local-network-mode.md)、[DEC-007](../decisions/DEC-007-contract-research-tooling.md)。
- 既有相关卡片：[DUAL-70-01](DUAL-70-01.md)、[DUAL-UNIT-01](DUAL-UNIT-01.md)、[JUXING-MAIN-01](JUXING-MAIN-01.md)、[KJX-01](KJX-01.md)、[QA-01](QA-01.md)、[DIAG-03](DIAG-03.md)。
- 代码基线：分支 `1104-llb`，起点 `origin/main@2ee5d1f`；上一轮交付提交 `d34a3b4`。
- 执行单元：`unit-local-mac-02`（巨量星图）、`unit-local-mac-03-juxing`（磁力聚星）；不新增、不改账号绑定/并发。
- 工具：`scripts/qa/mcp_client.py`（stdio 驱动 `@playwright/mcp` + 系统 Chrome）。

## 阶段二实现记录（2026-11-04）

- 迁移 021 已应用到开发库（执行前备份 `.runtime/backups/live02-20261104/before-migration-021.dump`；schema=21）；旧数据默认 `video_square`。
- 新增两份直播 verified 契约：`contracts/douyin_xingtu.live.verified.json`、`contracts/kuaishou_juxing.live.verified.json`；仅注册 `keyword` 能力、`basic` + `live` 模块，无 featured。
- 直播分页上限：真实核验第 2/5/6 页（各 20 条、0 重复）后设为 `page_fetch_max_verified=6`；真实数据存在无效/无直播候选人，4 页不足以稳定凑满 70 位有效达人，6 页（120 位候选）是当前真实可验证边界；page 7+ 在 coverage_gaps 披露。
- 新增 `xingtu_live_adapter.py` / `juxing_live_adapter.py`；复用现有 `BrowserAdapter` 会话/身份/证据框架，live 只按 `(platform, scene)` 选择契约与 adapter。
- 持久化：`creator_snapshots.creator_scene=live_square`；`creator_live_current` 独立读模型；live 不写 `platform_creators.projection`，不写星图短视频 current；juxing 短视频读模型对最近快照加 `creator_scene='video_square'` 过滤。
- 读模型/API：`/api/creator-library?creator_scene=`、`GET /api/creator-library/{id}?creator_scene=`、任务中心 scene、`POST/GET /api/creator-library/{id}/live-updates|live-update`；直播手动更新不写 `creator_update_schedule`。
- 前端：创建任务场景选择 + 直播表单（默认 20、max 70）；任务中心场景筛选/标识；达人库场景切换；`/creators/:id/live`；直播详情与双更新入口。
- 运行配置：`XINGTU_ENABLE_LIVE_SQUARE=1`，两平台 live registry 路径写入单元配置/环境；未新增执行单元/队列/Profile。
- 71 位拒绝：两平台 `POST /api/tasks` 均返回 422（`live target_count exceeds 70`）；70 位接受。
- 验证关键词：按用户 2026-11-04 指示改用 `美妆`；此前 `美食` 70 任务因有效达人不足在 30/70 时取消，保留为对照，不计入最终 70 结果。

### 阶段二自动化与真实验证进度

- 单元/契约/集成/前端测试持续执行；真实 70 任务与短视频回归结果在阶段三记录。
- 已知限制：直播详情页无直播 tab 的达人按 NO_DATA 记录直播模块，不伪造 0；聚星部分详情页首帧身份节点未就绪时等待 20s 后仍失败，按失败候选记录，不降低有效性标准。

## 验收清单

### 阶段一（已完成）

- [x] 代码/契约/迁移/任务中心/执行单元/前端/测试基线调查。
- [x] 两平台直播入口/URL/筛选/列表/第 2 页/详情/身份真实浏览器证据。
- [x] 两平台字段清单与身份交叉核对。
- [x] PRD、技术方案、测试用例（85 条）、影响分析。
- [x] observed 契约 + 脱敏证据 + 任务卡/索引/总览回写。

### 阶段二（开发）

- [x] 迁移 021（`creator_scene`、`creator_snapshots.creator_scene`、`creator_live_current`、索引）在隔离库验证后应用到目标库；执行前备份。
- [x] 领域 scene 维度贯穿 `RequirementForm/FilterPlan/TaskRecord/root_tasks`；旧数据默认 `video_square`。
- [x] 直播上限 70：前端、后端、P1/计划、任务记录一致；71 拒绝；短视频不变。
- [x] 两平台 live verified 契约与 `(platform, scene)` registry 选择；缺契约 fail closed，禁止回落短视频。
- [x] 星图/聚星直播 Adapter：关键词/ID、跨页、详情字段；不修改短视频 Adapter 行为。
- [x] 持久化：直播快照 + `creator_live_current`；不写 projection/星图短视频 current；历史快照保留。
- [x] 读模型/API：直播库/详情、任务中心 scene、直播更新接口；聚星短视频最近快照加 video_square 过滤。
- [x] `pipeline_complete` 精选条件一般化，短视频回归。
- [x] 前端：场景选择、任务中心、达人库切换、`/creators/:id/live`、双更新入口。
- [x] 自动化：单元/契约/集成/E2E/前端；短视频全回归通过。
- [x] 独立 commit 到 `1104-llb`：`3502c92`；不合并/不推送 main。

### 阶段三（真实验收）

- [x] 两平台直播小样本闭环（创建→任务→单元→采集→入库→状态→达人库→详情）。
- [x] 两平台真实 70 位直播任务（目标 70、有效/入库/快照一致；跨页 >1；0 重复）。
- [x] 71 位被前端/后端拒绝；70 位被接受。
- [x] 直播间数据未污染短视频数据（projection 全空、短视频 current 未写）；同达人两场景分别查看/更新本轮 **BLOCKED**（未找到同一测试身份同时有两场景完整数据，未伪造）。
- [x] 两平台短视频小样本回归；直播手动更新边界通过；视频定时更新边界 **BLOCKED/NOT_RUN**（调度器本轮未启动，未做真实定时触发）。
- [x] 执行单元/并发/互斥检查：同平台串行、跨平台并行、无新增单元。
- [x] 85 条测试用例状态回填（67 PASS / 0 FAIL / 6 BLOCKED / 12 NOT_RUN）；证据/任务卡/索引/报告。
- [x] 最终 **CONDITIONAL GO** 与遗留问题（见下方）。

## 第三阶段结果（2026-11-05）

| 项 | 结果 |
|---|---|
| 星图 70 | `065d36d8-8988-4882-948b-54d1dd864cdf`，COMPLETED，70/70 有效/完整，70 快照/70 current，78 候选/第 5 页游标，0 重复；342 项直播字段 COLLECTED、848 项 NO_DATA；17 位达人有非星图 ID 的真实直播表现指标 |
| 聚星 70 | `f6003e46-9463-48bd-b87e-91b96bd3736c`，COMPLETED，70/70 有效/完整，70 快照/70 current，74 候选/第 5 页游标，0 重复；940 项 COLLECTED、180 项 NO_DATA；首次 68/74 因浏览器动作失败，retry 从 checkpoint 补齐到 70 |
| 71 拒绝 | 两平台 `POST /api/tasks` 均 422：`live target_count exceeds 70`；前端输入 `max=70` |
| 小样本 | 星图 `b1b6fdb9-6b5a-4dbf-8975-63f890d1270f`（达人 ID，16 项真实直播指标）；聚星 `af37d30b-5daa-473c-bbdb-908d78b941a7`；UI 创建 `b8a0fb54-d35d-4cb8-b32a-990ec848578b` COMPLETED 1/1 |
| 直播手动更新 | 聚星 `b3410a77-1000-4983-83f4-0eb71cce1731` COMPLETED 1/1；直播快照 1→2；`creator_update_schedule` 0 行 |
| 短视频回归 | 星图 `183b72f4-2ec5-44d8-a2e8-1cd83b170bfa` COMPLETED 1/1（精选 COMPLETED）；聚星 `468089a0-1d4b-439f-8b4f-c539ff60374b` COMPLETED 1/1（首次导航超时，retry 通过） |
| 自动化 | 后端 565 passed / 1 skipped（unit+contract+integration）；前端 109 passed；mypy 41 files 0 error；ruff 全通过；前端 build 通过 |
| 页面证据 | `docs/evidence/assets/LIVE-02/phase3-live-{create,library,detail,detail-active,task,form}.png` |
| 详细报告 | [LIVE-02-phase3-results.md](../evidence/LIVE-02-phase3-results.md) |

### 最终判定：CONDITIONAL GO

**通过的核心条件**：两平台 70 位真实任务均 COMPLETED、有效/入库/快照/current 一致、0 重复、跨页；71 位两平台后端拒绝；直播更新不写短视频 schedule；短视频小样本回归通过；直播不写 projection/星图视频 current；无新增单元/队列。

**条件/限制**：
1. 星图 70 位中仅 17 位有真实直播表现指标；其余页面显示“近30天内没有开播”，按 NO_DATA 记录，未伪造 0。这是真实直播广场候选结构，不是采集遗漏。
2. 同一达人“短视频 + 直播”双场景分别查看/更新的端到端用例 **BLOCKED**：本轮 70 位任务的达人未同时具备两场景完整快照；已有身份重叠证据但未在测试任务中闭环。
3. 视频定时更新、登录失效、安全验证、页面结构破坏、异常注入等 6 条 BLOCKED / 12 条 NOT_RUN；未启动定时更新调度器。
4. 聚星/星图第 7 页以后仍未验证；契约披露 `page 7+` coverage gap。
5. 聚星 70 首次失败后 retry 补齐；星图 70 有多次开发期失败/取消任务，最终任务未失败重试。最终证据只采用最终 COMPLETED 任务。

## 实现记录

- 2026-11-04T20:44:00+08:00：建立卡片。开始前完成 Git 整理：
  - 未提交改动提交为 `d34a3b4`（DUAL-70-01、DUAL-UNIT-01、DEPLOY-WIN-01，61 files）。
  - `快手_1026` 以 `--no-ff` 合入 `main`，合并提交 `2ee5d1f` 并推送 GitHub。
  - 从最新 `origin/main` 创建并推送分支 `1104-llb`。
  - 提交前检查：unit 383 passed、contract 43 passed、mypy 38 files；Ruff 11 个既有 UP031 与 3 个既有 format 失败不在本次提交范围。
- 2026-11-04T20:45—21:00：阶段一真实浏览器调查（Playwright MCP + Chrome，隔离 storage_state）：
  - 星图：`/ad/creator/market/live`；`search_for_author_square`（`search_scene=2`）；`authors[].star_id`；第 2 页 20/0 重复/total=977；详情 `author/douyin/{star_id}`。
  - 聚星：`#/star_plaza/live`；`star/list`（`taskType=4`、`pathSource=no_filter_live|search_live`）；`starList[].userId`；第 2 页 20/0 重复/total=5000；详情 `#/live-promotion/star/{starId}`。
  - 同身份样本：星图 `6769198961371643915`（同 star_id）、聚星 `841292065`（同 userId，starId=2576496）。
- 2026-11-04T21:02—21:06：阶段一产出 PRD/技术方案/影响分析/测试用例（77 条）/observed 契约/4 张脱敏截图/调查证据。
- 2026-11-04T21:20：用户正式批准进入第二阶段并裁决 D1—D7；D6 调整为直播最大 70。已同步 PRD/技术方案/测试用例（新增 8 条 70 专项，共 85 条）/影响分析/任务卡。开始阶段二开发；阶段一文档将单独 commit 到 `1104-llb`。

## 验证证据

### 阶段一

- [调查证据](../evidence/LIVE-02-live-square-investigation.md)
- [PRD](../prd/LIVE-02-live-square-collection.md)
- [技术方案](../design/LIVE-02-live-square-technical-design.md)
- [测试用例](../evidence/LIVE-02-test-cases.md)（85 条）
- [影响分析](../design/LIVE-02-compatibility-impact.md)
- [星图 observed 契约](../../contracts/douyin_xingtu.live.observed.json)、[聚星 observed 契约](../../contracts/kuaishou_juxing.live.observed.json)
- 截图：[星图直播广场](../evidence/assets/LIVE-02/xingtu-live-square-2026-11-04.png)、[星图直播详情](../evidence/assets/LIVE-02/xingtu-live-detail-data-2026-11-04.png)、[聚星直播广场](../evidence/assets/LIVE-02/juxing-live-square-2026-11-04.png)、[聚星直播详情](../evidence/assets/LIVE-02/juxing-live-detail-2026-11-04.png)
- 私有原始证据：`.runtime/live02/`（0600、gitignored）。

### 阶段二/三

开发与验收完成后回填（命令、测试计数、任务 ID、DB 核对、截图、日志）。

## 交接信息

- 当前阶段：已完成（CONDITIONAL GO）；实现提交 `3502c92`，阶段一文档提交 `c4617fe`。
- 进行中：无。
- 约束：不改短视频行为；不新增执行单元/队列；不写直播数据到短视频 projection；不合并/推送 main；重大架构变更先报告。
- 下一步（若有条件）：补同达人双场景闭环、视频定时更新、登录失效/安全验证/页面结构破坏异常注入；验证直播第 7 页以后。

## 状态历史

- 2026-11-04T20:44:00+08:00：待办 → 进行中；开始阶段一。
- 2026-11-04T21:10:00+08:00：阶段一完成；等待审批。
- 2026-11-04T21:20:00+08:00：用户批准第二阶段并裁决 D1—D7（D6 调整为直播最大 70）；开始阶段二开发。
- 2026-11-04T23:00—2026-11-05T00:50：第二阶段实现 + 第三阶段真实验收；两平台 70/70 COMPLETED、71 拒绝、短视频回归通过；85 条用例回填 67 PASS / 6 BLOCKED / 12 NOT_RUN；判定 CONDITIONAL GO。
- 2026-11-05T00:55：实现/证据提交 `3502c92` 到 `1104-llb`；未合并/推送 main。
