# KJX-01 全量回归报告（两平台 / 真实栈 / Playwright MCP + Chrome）

状态：已完成（T1/T2/T3 全部通过；T2 最终任务 22/22/22 且真实进入第 2 页；阶段 D-0 GO）  
生成时间：2026-10-30T00:22:00+08:00  
执行环境：macOS 隔离回归栈，非生产环境  
结论：**GO**。聚星分页第 1→2 页真实验收、T1 五项筛选、字段扩展、账号选择处理与星图 T3 重试均通过；最终双平台 MCP 回归 **19 PASS / 0 FAIL**。阶段 C 的 macOS v1 GO 结论继续有效。

## 1. 方法与授权

- 浏览器操作全部通过 `@playwright/mcp@0.0.77` 的 MCP stdio 工具驱动本机 Google Chrome；产品登录、平台选择、表单填写、筛选、提交、任务详情/达人库/详情导航均为真实 UI 操作，不是 Playwright Python 页面自动化。
- 平台侧仅使用授权子账号 `60821564`，只读调查 + 小样本真实采集；无平台写操作、无绕过验证、无扩大采集。
- 真实任务均从产品 UI 提交：T1（聚星 target=3，五项筛选）、T2-批准（聚星 keyword+content type，target=22，分页）、T3（星图 宠物 target=1）。
- 另有一个 **T2-偏差**：驱动误选北京地域，平台只返回 16 个候选并 exhausted；任务真实存在并保留，透明记录，不作为分页验收依据。批准 T2 的额外规模仍在授权 worst-case 49 位内（3+16+22+1=42）。
- 会话：回归单元使用**全新空 Profile + 经核验的加密会话快照**；复制现有 Profile 在本机 Keychain/持久上下文下被平台判为无会话，已按单元私有快照方式重建，未扩大平台权限。

## 2. 隔离环境

| 项 | 值 |
|---|---|
| 数据库 | `xingtu_test_kjx_regression`（迁移 20；无生产库写入） |
| API / Vite | `127.0.0.1:4192` / `127.0.0.1:4193` |
| Temporal | `127.0.0.1:57235`（本地 SQLite） |
| Redis | `127.0.0.1:6379/15` |
| 执行单元 | `unit-local-mac-02-kjx-full`；双平台绑定；单 Worker；同单元串行 |
| 聚星能力 | `juxing-video-square-stage-c-v2`；target 上限 30（仅本隔离进程） |
| 星图能力 | 既有 Stage C 合同/Adapter；未修改 |
| 产品账号 | `kjx-regression-media`（密码仅在本机 0600 私有文件） |
| 平台会话 | 私有 `.runtime/profiles/storage-state/`，0600；不写文档、不入 Git |

## 3. 自动化回归

| 层 | 命令/范围 | 结果 |
|---|---|---|
| 后端单元 + 合同 | `pytest backend/tests/unit backend/tests/contract` | **403 passed** |
| 隔离 PostgreSQL 集成 | 全新 `xingtu_test_kjx_full` | **118 passed / 1 skipped** |
| 全量 E2E | `pytest tests/e2e`（含聚星 Temporal/产品页/全栈） | **14 passed** |
| 前端 | `npm --prefix frontend run lint/test/build` | **103 passed**；tsc/build 通过 |
| 合同 v2 | `require_enabled(live=True)` | 通过 |
| Adapter v2 专项 | 15 条（分页/筛选/空页/续跑/字段/合同） | **15 passed** |

## 4. Playwright MCP 设置与 UI 基线

`--phases setup` 结果：**6 PASS**。

- 双平台目录启用、合同版本正确；聚星 capability 7 字段、38 内容类目、34 省、3 报价、target max=30。
- 聚星表单显示内容类型/粉丝/地域/报价/目标数量；星图表单仍显示内容关键词/目标数量。
- 截图：`01-tasks.png`、`02-juxing-form.png`、`03-xingtu-form.png`；报告见私有 `.runtime/kjx-full/regression/mcp/report.json`。

## 5. 真实任务 T1

| 项 | 结果 |
|---|---|
| 任务 | `f1f62c78-c0e9-495c-8863-08a8d56a6e0f` |
| 条件 | 母婴 / 母婴亲子 / 粉丝 10 万–100 万 / 北京 / 21-60 秒报价上限 10000 元 / target=3 |
| 状态 | **COMPLETED** |
| 计数 | 发现 10、有效 3、资料完整 3、失败 0 |
| 快照 | 3 位均 basic 18 / spread 31 / works 1 / audience 2；pipeline complete |
| 筛选核对 | 3 位粉丝均在区间；任务详情的 5 项条件全部显示 |
| 字段核对 | 新增 basic/spread 字段真实有值；recent CPM/CPE、商业作品字段为 NO_DATA；无伪 0 |
| 证据 | `t1-form.png`、`t1-task-detail.png`、`t1-report.json`（T1 3 PASS）；DB 快照/投影查询 |

T1 的 `failure_counts` 记录 4 次 `SESSION_INDETERMINATE`（复制 Profile 的会话恢复问题），在切换到空 Profile + 核验快照后同一任务自动重试成功；不是平台采集失败，已在报告中保留原始失败计数。

## 6. 真实任务 T2 / T3（已完成）

### 6.1 T2 最终任务（通过）

- 历史：首次 T2-批准 `50cccb72-3890-493f-ad9d-79f94278a24d` 因过期星图 maintenance + 正常子账号选择页被误判，`PARTIAL_COMPLETED 0/22`（详见专项诊断）。
- 最终任务：`56efbba5-d267-44a2-824a-2ba4e60f2dd9`；聚星「母婴 / 母婴亲子 / target=22」；真实 UI 提交，修复后同任务重试。
- 结果：**COMPLETED，valid 22 / profile_complete 22 / 22，failed 0**；`visited_cursors=[None,"2"]`，40 个候选（两页各 20），`processed_operations=2`，无第 3 页请求；`task_creators` 有效 22，`creator_snapshots` 22。
- 验收：真实第 2 页、22/22/22、无跨平台污染、任务中心/达人库/DB 一致，全部满足。
- 证据：`.runtime/kjx-full/regression/mcp-t2-final/`；隔离库任务 56ef 的 checkpoint/creators/snapshots；专项报告 [KJX-01-T2-account-selection-diagnosis](KJX-01-T2-account-selection-diagnosis.md)。

### 6.2 T2-偏差（透明记录，已终态）

- 任务：`7ec6a121-47a7-44a4-865a-de480e1fc263`；目标 22，但驱动误加北京地域；平台只返回 16 个候选并 `exhausted`；终态 **PARTIAL_COMPLETED 16/22（SEARCH_EXHAUSTED）**，无法覆盖第 2 页。该任务**不作分页验收依据**。
- 证据：`t2-form.png`（可见 3 项已选条件，含北京）、`t2-accidental-task-detail.png`；DB checkpoint `exhausted=true`、候选 16；报告 `t2-accidental-report.json`。

### 6.3 T3

- 任务：`516a9e3b-346c-4bf9-b5c4-a28d756e3272`；星图「宠物 / target=1」；真实 UI 一次提交。
- 首次任务：收集 1 位有效后触发 `PLATFORM_SECURITY_CHALLENGE`，`WAITING_FOR_VERIFICATION`；15 分钟窗口超时，**PARTIAL_COMPLETED**（valid 1、profile 0，failure=`SECURITY_CHALLENGE_TIMEOUT`）；未绕过验证。
- 同范围重试（授权一次）：`ef1ed66e-724d-43c4-a49f-a084c4884491`，星图「宠物 / target=1」，真实 UI 一次提交，**COMPLETED 1/1/1**，profile/pipeline complete；星图 F06/详情/库回归通过；既有星图代码未改。
- 证据：`t3-form.png`、`t3_retry-form.png`、任务详情/验证事件（私有）。

## 7. 双平台 UI/API 回归（已完成）

最终 MCP 回归：**19 PASS / 0 FAIL**；T2 最终任务 56ef 22/22/22、第 2 页证据通过。

- 任务中心：两平台任务、平台标签、计数、失败原因/条件摘要。
- 聚星达人库：平台筛选、列表指标、详情基础资料/传播表现/作品封面/受众维度表。
- 星图达人库/详情：星图 ID、8 模块、商业能力、F06；Xingtu-only 筛选与子资源正常。
- API：`/api/platforms`、双平台 capabilities、任务详情、`/api/creator-library`、聚星详情 payload（18/31/1/2）；T3 重试 1/1/1。
- 跨平台隔离：同一单元串行；聚星 projection 不写星图表；星图字段不映射到聚星。
- 截图：`10-task-center.png` 至 `18-t3-detail.png`（私有 0700）。

## 8. 未完成 / 风险

- 原 CONDITIONAL 条件已关闭：T2 最终任务 56ef **COMPLETED 22/22/22**，`visited_cursors=[None,"2"]`，第 2 页真实候选与落库成立。
- 专项诊断/修复：过期跨平台 verification 状态清理；聚星账号选择页独立分类 `ACCOUNT_SELECTION_REQUIRED`、人工接管、前端提醒、超时 `ACCOUNT_SELECTION_TIMEOUT`；v3 pristine plan 的版本 adopt。详见专项报告。
- T2-偏差 16/22、`SEARCH_EXHAUSTED`，仅第 1 页；透明保留，不作分页证据。累计真实样本仍在 worst-case 49 位内。
- T3 首次因平台安全验证超时 1/1（profile 0）；同范围重试 1/1/1 `COMPLETED`，星图回归通过；不绕过验证。
- 看履约/看带货模块、第 3 页+、聚星更新/定时、库级历史/报价/作品 UI 仍按范围延后。
- Windows 由 DEPLOY-WIN-01 承担；生产 Flag、正式业务库未变更；KJX-01 总体仍“进行中”仅因 Windows。
- `make check` 仍受既有 11 个 `scripts/acceptance` `UP031` 阻断；本卡范围 Ruff/format、Mypy strict、`git diff --check` 通过。

## 9. 最终判定

**GO**（阶段 C+ macOS 范围；阶段 D-0 CONDITIONAL 已关闭）：

- T2 最终任务 56ef：COMPLETED 22/22/22，真实第 2 页（`visited_cursors=[None,"2"]`），无第 3 页，22 creators/snapshots。
- T1：COMPLETED 3/3/3，四模块 18/31/1/2，五项筛选。
- T3：首次验证超时，授权同范围重试 COMPLETED 1/1/1；星图 F06/详情/库回归通过。
- 账号选择：正常子账号选择页识别、`ACCOUNT_SELECTION_REQUIRED` 提醒、人工接管、正确/错误账号、超时原因修复；无自动选择、无绕过。
- 最终 MCP 19 PASS/0 FAIL；后端单元+合同 404（新增账号选择单测）；前端 104（新增提醒单测）；E2E 14；隔离集成 118/1 skipped；无 Schema/星图逻辑改动。
- 范围外/延后：看履约/看带货、第 3 页+、更新/定时、库级历史/报价/作品 UI、Windows、生产 Flag/正式库；这些不是本轮 GO 的条件。
- 阶段 C macOS v1 GO 继续有效。

## 10. 证据索引

| 内容 | 位置 |
|---|---|
| MCP 设置/T1 报告 | `.runtime/kjx-full/regression/mcp/report.json`、`t1-report.json` |
| T2-批准 报告 | `.runtime/kjx-full/regression/mcp-t2-approved/report.json` |
| T2-偏差 报告 | `.runtime/kjx-full/regression/mcp/report.json`（T2 运行时） |
| 截图 | `.runtime/kjx-full/regression/mcp/*.png` |
| 服务日志 | `.runtime/kjx-full/regression/logs/` |
| 数据库 | 隔离库 `xingtu_test_kjx_regression`；无生产库 |
| 合同/单测/集成 | `contracts/kuaishou_juxing.verified.json`；`backend/tests`；`tests/e2e` |
| 功能完成证据 | [KJX-01-feature-completion](KJX-01-feature-completion.md) |

> 私有证据目录 0700；Cookie、Token、DSN、密码、达人昵称/ID 正文不写入文档。
