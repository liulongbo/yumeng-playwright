# LIVE-02：巨量星图 / 磁力聚星「直播广场」达人采集扩展

状态：**进行中（第二阶段开发）**  
建立时间：2026-11-04T20:44:00+08:00  
最近更新：2026-11-04T21:20:00+08:00  
是否验收：否（第二阶段开发中；第三阶段真实验收完成后判定）

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

## 验收清单

### 阶段一（已完成）

- [x] 代码/契约/迁移/任务中心/执行单元/前端/测试基线调查。
- [x] 两平台直播入口/URL/筛选/列表/第 2 页/详情/身份真实浏览器证据。
- [x] 两平台字段清单与身份交叉核对。
- [x] PRD、技术方案、测试用例（85 条）、影响分析。
- [x] observed 契约 + 脱敏证据 + 任务卡/索引/总览回写。

### 阶段二（开发）

- [ ] 迁移 021（`creator_scene`、`creator_snapshots.creator_scene`、`creator_live_current`、索引）在隔离库验证后应用到目标库；执行前备份。
- [ ] 领域 scene 维度贯穿 `RequirementForm/FilterPlan/TaskRecord/root_tasks`；旧数据默认 `video_square`。
- [ ] 直播上限 70：前端、后端、P1/计划、任务记录一致；71 拒绝；短视频不变。
- [ ] 两平台 live verified 契约与 `(platform, scene)` registry 选择；缺契约 fail closed，禁止回落短视频。
- [ ] 星图/聚星直播 Adapter：关键词/ID、跨页、详情字段；不修改短视频 Adapter 行为。
- [ ] 持久化：直播快照 + `creator_live_current`；不写 projection/星图短视频 current；历史快照保留。
- [ ] 读模型/API：直播库/详情、任务中心 scene、直播更新接口；聚星短视频最近快照加 video_square 过滤。
- [ ] `pipeline_complete` 精选条件一般化，短视频回归。
- [ ] 前端：场景选择、任务中心、达人库切换、`/creators/:id/live`、双更新入口。
- [ ] 自动化：单元/契约/集成/E2E/前端；短视频全回归通过。
- [ ] 独立 commit 到 `1104-llb`；不合并/不推送 main。

### 阶段三（真实验收）

- [ ] 两平台直播小样本闭环（创建→任务→单元→采集→入库→状态→达人库→详情）。
- [ ] 两平台真实 70 位直播任务（目标 70、有效/入库/快照一致；跨页 >1；0 重复）。
- [ ] 71 位被前端/后端拒绝；70 位被接受。
- [ ] 直播间数据未污染短视频数据；同达人两场景可分别查看/更新。
- [ ] 两平台短视频小样本回归；手动更新/定时更新边界检查。
- [ ] 执行单元/并发/互斥检查：同平台串行、跨平台并行、无新增单元。
- [ ] 85 条测试用例状态回填（PASS/FAIL/BLOCKED/NOT_RUN）；证据/任务卡/索引/报告。
- [ ] 最终 GO / CONDITIONAL GO / NO-GO 与遗留问题。

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

- 当前阶段：第二阶段开发（D1—D7 已裁决；直播上限 70）。
- 进行中：文档同步完成，准备提交阶段一成果；随后迁移 021、领域/契约/Adapter/持久化/读模型/API/前端/测试。
- 约束：不改短视频行为；不新增执行单元/队列；不写直播数据到短视频 projection；不合并/推送 main；重大架构变更先报告。
- 下一步：阶段二完成后直接进入阶段三真实验收（小样本 → 两平台 70 位 → 短视频回归）。

## 状态历史

- 2026-11-04T20:44:00+08:00：待办 → 进行中；开始阶段一。
- 2026-11-04T21:10:00+08:00：阶段一完成；等待审批。
- 2026-11-04T21:20:00+08:00：用户批准第二阶段并裁决 D1—D7（D6 调整为直播最大 70）；开始阶段二开发。
