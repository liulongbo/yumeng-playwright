# F04/F05/F06/M3 核心冒烟测试报告

## 2026-10-11 完整新任务闭环修复复核

本节是本报告的最新结论。下方的 2026-10-10 内容保留为首次冒烟时的历史记录，不覆盖其当时的阻塞事实。

### 原因与修复

首次冒烟中的“完整端到端闭环”没有成功，原因不是 F04/F05/F06 采集代码本身全部不可用，而是三个跨层问题叠加：

1. 首次 UI 新建任务时只启动了产品 API 和前端，没有启动 Intake Worker 与 Collection Worker；任务因此停在 `RECEIVED`，`intake_dispatches.sent=false`，没有进入 P1/P2。
2. 当时环境没有 `DEEPSEEK_API_KEY`，无法启动真实 DeepSeek Intake Worker，不能把停在 `RECEIVED` 的任务误判为业务执行失败。
3. 一个真实任务在执行完成后，任务计数已经更新，但任务详情页首次读取到的达人列表为空；任务进入终态后页面停止任务轮询，却没有刷新 `creators` 查询，造成“计数有达人、列表显示 0”的前端跨层展示不一致。

本次只做必要修复：

- 在 `contracts/douyin_xingtu.verified.json` 中为 `seeding.search_word_ctr` 和 `fulfillment.message_reply_rate` 登记成功响应缺源时的 `NO_DATA` 语义，修复 F05 缺源字段导致的错误失败。
- 在 `frontend/src/pages.tsx` 的 `TaskDetailPage` 中，当任务进入终态时失效并刷新 `['creators', taskId]` 查询，修复终态达人列表不刷新的问题。
- 为验证完整链路，启动临时 localhost-only DeepSeek-compatible Fixture `http://127.0.0.1:18080`，并同时启动 Intake Worker、Collection Worker、产品 API、前端和既有 Temporal/PostgreSQL/Redis/MinIO 依赖。Fixture 只用于受控验证，不是真实 DeepSeek，不计入真实模型现场验收。

### 修复后真实执行的完整链路

通过 Playwright MCP 真实浏览器操作创建新任务：

- root task：`acd929aa-874e-4de8-8fb1-6a9295cf07ff`
- 输入：关键词“宠物”、目标数量 `1`
- 页面状态：`RECEIVED → PARSING → QUEUED → COLLECTING → COMPLETED`
- 真实链路：UI → Product API → PostgreSQL 持久化 → Intake Worker → P1 Temporal Workflow → Collection Worker → F04 候选发现 → F05 资料采集 → F06 精选集合/封面 → PostgreSQL → API 查询 → UI 展示

最终结果：

- `discovered_count=20`
- `valid_count=1`
- `profile_complete_count=1`
- `featured_complete_count=1`
- `failed_count=0`
- `failure_reason=null`
- F05 最新快照：`profile_complete=true`、`featured_complete=true`、`pipeline_complete=true`，`COLLECTED=75`、`NO_DATA=6`、`FAILED=0`
- F06 两组精选集合均 `COMPLETE`，封面状态为 `STORED`

修复后的 Playwright MCP 页面显示“已完成”“已发现 20 候选达人”“有效入库 1，目标 1”“资料完整 1”“精选完整 1”“失败步骤 0”，并显示“1 位可查看”、达人 ID `6849131371793743886` 和“已发布快照”。任务完成后 `GET /api/tasks/<root>/creators?limit=20` 返回 200，页面不再停留在 0 位可查看。

### 最新测试结论

- 受控本地模型 Fixture 条件下，完整新任务 UI→API→Worker→F04/F05/F06→数据库持久化→API→UI 闭环：**PASS**。
- 既有真实 DeepSeek 任务 `f47eb1cf-f038-4f9f-ae3d-e02aa8a995d3` 经 F05 缺源契约修复和受控 retry 后：**PASS**，最终 `COMPLETED`，`profile_complete_count=2`、`featured_complete_count=2`、`pipeline_complete=true`。
- 本次新任务没有使用真实 DeepSeek，而是 localhost-only Fixture；因此“真实 DeepSeek 新任务现场调用”仍是**未执行**，不能据此宣称真实模型现场验收完成。
- F05 安全验证专项仍为**部分通过**：合成/离线回归通过，真实自然挑战、同一 BrowserHost/Context/Page 恢复、`session_version` 单次递增和重复请求下降 50% 的证据尚未取得。
- 生产 HTTPS、正式域名、Secure Cookie、生产 Origin、远程浏览器承载仍未验收。当前闭环结论只适用于本地开发环境。

证据：

- Playwright 截图：`.playwright-mcp/e2e-repair-task-completed-with-creator.png`
- Playwright 页面/Network 证据：`.playwright-mcp/` 下对应 `acd929aa-874e-4de8-8fb1-6a9295cf07ff` 的任务详情快照及 `/api/tasks/<root>`、`/creators` 200 响应记录
- 自动化复测：`npm --prefix frontend run lint`、`npm --prefix frontend test -- --run`（3 passed）、`npm --prefix frontend run build`、`git diff --check` 均 PASS

## 2026-10-10 修复追记：既有真实产品闭环已补齐到 COMPLETED

用户追问“完整端到端闭环为什么没有成功”后，继续定位并修复。根因分两层：

- 新建 UI 受控任务 `b12b5785-f90a-42c2-8c4f-67c54ab690e4` 未成功，是因为当前本地只运行 API/前端，没有 Intake Worker/Collection Worker；此外当前会话和 `.runtime/m3-app.env` 均未提供 `DEEPSEEK_API_KEY`，不能重新创建一个真实 P1 新任务闭环。
- 既有真实产品任务 `f47eb1cf-f038-4f9f-ae3d-e02aa8a995d3` 未全量成功，是因为 F05 仍有可重试缺口：第一位达人 `fans` 曾因安全验证/Schema mismatch 未完成，第二位达人 `seeding.search_word_ctr` 与 `fulfillment.message_reply_rate` 在成功响应中缺源，当前 verified contract 未声明其缺源业务口径。

本轮修复只做必要改动：在 `contracts/douyin_xingtu.verified.json` 中为 `search_word_ctr` 和 `message_reply_rate` 增加显式 `missing_source_status=NO_DATA` 及 live 证据引用；未修改采集代码。随后启动真实 P2 Worker，对 root `f47eb1cf-f038-4f9f-ae3d-e02aa8a995d3` 执行两次受控 retry：第一次将 `profile_complete_count` 从 0 提升到 1；第二次在新 contract 下达到 `COMPLETED`。

修复后证据：

- DB：root `f47eb1cf-f038-4f9f-ae3d-e02aa8a995d3` 为 `COMPLETED`，version 452，`valid_count=2`、`profile_complete_count=2`、`featured_complete_count=2`、`pipeline_complete=true`、`failure_reason=null`。
- DB：两位达人最新快照均 `profile_complete=true`、`featured_complete=true`；最新快照中无 `FAILED` 字段或不完整模块。
- DB：F06 仍为 14 张精选卡、14 个 `STORED` 封面。
- API：`GET /api/tasks/f47eb1cf-f038-4f9f-ae3d-e02aa8a995d3` 返回 200，`status=COMPLETED`，`allowed_actions=[]`。
- Playwright MCP UI：任务详情页显示“已完成 / 目标链路已完成，可查看发布快照”；第二位达人详情无“失败/FAILED”文本，8 个 F05 模块均 `COLLECTED/complete=true`，两组 F06 集合均 `COMPLETE`。
- 证据快照：`.playwright-mcp/smoke-repair-task-completed-after-api-restart.yml`、`.playwright-mcp/smoke-repair-task-completed-full.yml`、`.playwright-mcp/page-2026-10-10T15-12-56-896Z.yml`。
- 验证：`PlatformRegistry.require_enabled(live=True)` 通过；`pytest backend/tests/unit/test_search_contract_registration.py backend/tests/contract/test_profile.py -q` 为 12 passed。

修复结论：既有真实产品任务的完整端到端闭环现已 PASS（M3 真实提交历史 → P1 → P2/F04/F05/F06 → DB → API → 前端结果展示）。新建任务从 UI 当场创建并执行到完成仍依赖重新提供 `DEEPSEEK_API_KEY` 并同时运行 Intake Worker 与 Collection Worker；本轮未伪造该前置。

## 1. 测试概览

- 测试日期：2026-10-10T22:24:55+08:00。
- Git 分支：`10.9`。
- 代码版本：`bc1f95a`；工作区测试前已有大量未提交修改，本轮未改业务源码、未 commit、未 push、未清理工作区。
- 测试环境：本机 macOS；前端 `http://127.0.0.1:5173`；产品 API `http://127.0.0.1:8000`；PostgreSQL `127.0.0.1:55432/xingtu_development/public`；隔离测试库 `127.0.0.1:55439/xingtu_test_f04f05`；Redis `127.0.0.1:56379`；Temporal `127.0.0.1:57233`；MinIO `127.0.0.1:59000/59001`。
- Docker Compose 状态：`app-postgres` healthy；`redis`、`temporal`、`objects` 均 Up 3 days。
- Playwright MCP 状态：可用。已通过 `data:` 页面真实导航、页面快照、表单填写、点击、dialog、fetch evaluation、network/console 读取验证。
- 测试范围：F04、F05、F06、M3（APP-01/INTAKE-01/CONSOLE-01）及 CHALLENGE-01 安全验证专项。
- 总体结论：自动化脚本层核心回归通过；Playwright MCP 真实 UI 的登录、创建、取消、列表、详情、结果读取、双集合切换、退出保护通过。新建受控任务 `b12b5785-f90a-42c2-8c4f-67c54ab690e4` 因本地未运行 Intake Worker/Collection Worker 未进入 P1/P2，已通过 UI 取消避免后续真实平台采集。完整“新任务从创建到采集完成”的当前环境闭环未执行完成，标记 BLOCKED；既有真实产品任务 `f47eb1cf-f038-4f9f-ae3d-e02aa8a995d3` 可验证 P1→P2 后的结果读取闭环，但终态为 `PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE`。

## 2. 测试用例汇总

| 测试编号 | 模块 | 测试场景 | 测试方式 | 执行结果 | 证据 |
| ---- | -- | ---- | ---- | ---- | -- |
| ST-001 | 环境 | Git、服务、MCP 基线 | CLI + Playwright MCP | PASS | `git branch/status/diff/log`；Docker ps；MCP snapshot `.playwright-mcp/page-2026-10-10T13-56-59-610Z.yml` |
| ST-002 | F04/F05/F06/M3 | 单元规则回归 | `make test-unit` | PASS | 164 passed |
| ST-003 | M3 前端 | 类型、组件、生产构建 | `make frontend-check && make frontend-build` | PASS | TS strict；Vitest 3 passed；Vite build passed |
| ST-004 | 全仓静态 | lint/format/typecheck | `make lint && make format-check && make typecheck` | PASS | ruff passed；62 files formatted；mypy 28 source files passed |
| ST-005 | F04/F05/F06/Challenge | 浏览器契约 | `make test-contract`（沙箱外复跑） | PASS | 28 passed；沙箱内首次失败为 macOS Mach port 权限 |
| ST-006 | F04/F05/F06/M3/Challenge | PostgreSQL 集成 | `XINGTU_TEST_DATABASE_URL=... make test-integration` | PASS | 67 passed, 1 skipped |
| ST-007 | F06 | MinIO/S3 封面专项 | `test_s3_covers.py` with local MinIO | PASS | 1 passed |
| ST-008 | M3/Workflow | Temporal + 前端合成 E2E | `tests/e2e -q` | PASS | 7 passed |
| ST-009 | M3 Auth | 未登录访问受保护页 | Playwright MCP | PASS | `/tasks` 回跳 `/login`；Network `/api/auth/me` 401 |
| ST-010 | M3 Auth | 临时 QA 用户登录与退出 | Playwright MCP | PASS | 用户 `smoke-qa-20261010` 登录；退出后直达任务 URL 回登录 |
| ST-011 | M3 Intake | 创建页能力驱动表单 | Playwright MCP | PASS | 仅展示 1 项已核验条件：内容关键词；默认目标 20，范围 1-200 |
| ST-012 | M3 Intake | 创建受控任务并取消 | Playwright MCP + API + DB | PASS | root `b12b5785-f90a-42c2-8c4f-67c54ab690e4`：RECEIVED 后 UI 取消为 CANCELLED，DB `intake_sent=false` |
| ST-013 | M3 Results/F04-F06 | 读取既有真实结果任务 | Playwright MCP + API + DB | PASS | root `f47eb1cf-f038-4f9f-ae3d-e02aa8a995d3`：2 位达人、14 张卡片、14 个 STORED 封面引用 |
| ST-014 | F05 Challenge | 安全验证托管专项 | 现有单元/契约/集成 | PARTIAL PASS | 合成专项通过；真实自然挑战未触发，仍 BLOCKED |

## 3. F04 测试结果

F04 职责经卡片确认是平台筛选、搜索与候选发现，不按编号猜测。脚本层覆盖搜索条件重建、回读不一致拒绝、响应关联、有序去重、分页、游标恢复、预算暂停、无身份候选诊断和持久化。`make test-unit`、`make test-contract`、`make test-integration`、`tests/e2e` 均通过相关用例。

UI/真实数据侧，既有真实产品任务 `f47eb1cf-f038-4f9f-ae3d-e02aa8a995d3` 前端与 API 均显示 `discovered_count=20`、`valid_count=2`、目标 2，DB 中 `task_creators=2`。本轮未执行新的真实平台搜索，因为当前未运行 Intake Worker/Collection Worker，且用户要求不主动制造高频平台请求或安全验证。

结论：F04 核心冒烟 PASS；新建任务的即时 P2 执行链路 BLOCKED 于 worker 未启动。

## 4. F05 测试结果

F05 职责经卡片确认是达人主页资料采集、字段标准化、持久化、恢复和安全验证相关流程。自动化层通过 164 单元、28 浏览器契约、67 集成和 7 E2E。真实结果任务的达人详情页显示 8 个主页资料模块，其中 `basic/spread/seeding/creation/commercial/conversion/fulfillment` 为 `COLLECTED`，`fans` 为 `FAILED`。该任务因此整体为 `PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE`，前端没有伪报完成。

结论：F05 自动化核心冒烟 PASS；所选真实产品任务暴露的 `fans` 模块失败被正确保留并展示，因此真实任务结果为 PARTIAL PASS，不作为全量完成证明。

## 5. F06 测试结果

F06 职责经卡片确认是两组精选作品采集与受控封面存储。脚本层：F06 单元/浏览器契约/集成/Temporal E2E 均随套件通过；MinIO 专项在本轮显式配置 `XINGTU_TEST_S3_ENDPOINT=http://127.0.0.1:59000` 后 1 passed。

真实结果任务验证：第一个达人详情页可在“优秀传播视频”和“优秀种草视频”之间切换；API 返回 `excellent_reach` 与 `excellent_seeding` 均 `COMPLETE=true`，每组 4 张卡。DB 对同一 root 统计：`collections=4`、`featured_cards=14`；封面状态拆分显示 `STORED=14`、`object_refs=14`、`distinct_objects=13`，说明 14 张卡都有封面对象引用，其中一个对象被复用。

结论：F06 核心冒烟 PASS。

## 6. M3 测试结果

M3 覆盖 APP-01、INTAKE-01、CONSOLE-01：登录会话、能力驱动表单、FilterPlan/P1 受理入口、任务列表/详情、任务操作和结果页。

- 登录：未登录 `/tasks` 回跳 `/login`；临时本地用户 `smoke-qa-20261010` 登录成功；退出后直达任务 URL 再次回跳登录。
- 创建任务：页面只渲染已核验关键词能力；空表单不离开页面；填写“冒烟测试”、目标 1 后提交成功，进入 root `b12b5785-f90a-42c2-8c4f-67c54ab690e4`。
- API/DB 一致性：新建任务 API 为 `RECEIVED`，DB 为 `product_intake`、关键词“冒烟测试”、目标 1、P1 task kind `P1`、`intake_sent=false`；取消后前端/API/DB 均为 `CANCELLED`、version 1、`TASK_CANCELLED`。
- 结果读取：既有真实产品任务 `f47eb1cf...` 前端/API 显示 `PARTIAL_COMPLETED`、发现 20、有效 2、F06 完整 2；DB 显示 2 位达人、7 份快照、14 张精选卡。

结论：M3 UI/API/DB 核心冒烟 PASS；本轮未启动 worker，不能把新建任务推进到采集完成，完整新任务闭环 BLOCKED。

## 7. Playwright MCP UI 测试结果

Playwright MCP 不是普通 HTTP 替代：本轮实际执行了浏览器导航、输入、点击、确认框、页面快照、console/network 读取和页面内 fetch。关键证据路径：

- 登录页：`.playwright-mcp/page-2026-10-10T14-08-28-266Z.yml`。
- 登录后任务中心：`.playwright-mcp/page-2026-10-10T14-09-03-152Z.yml`。
- 创建任务页：`.playwright-mcp/page-2026-10-10T14-09-29-311Z.yml`。
- 新建任务详情：`.playwright-mcp/page-2026-10-10T14-10-50-785Z.yml`。
- 取消确认与取消后详情：`.playwright-mcp/page-2026-10-10T14-15-21-029Z.yml`、`.playwright-mcp/page-2026-10-10T14-15-49-568Z.yml`。
- 真实任务详情与达人详情：`.playwright-mcp/page-2026-10-10T14-18-03-014Z.yml`、`.playwright-mcp/page-2026-10-10T14-18-27-144Z.yml`、`.playwright-mcp/page-2026-10-10T14-18-51-390Z.yml`。
- 退出与会话失效：`.playwright-mcp/page-2026-10-10T14-22-50-827Z.yml`、`.playwright-mcp/page-2026-10-10T14-23-07-169Z.yml`。

Console 记录只有预期的未登录 `/api/auth/me` 401 和 `favicon.ico` 404，未发现业务 JavaScript 异常。Network 最终显示 `/api/auth/me => 401`，符合退出后会话失效预期。

## 8. 端到端业务闭环验证结果

本轮按同一任务做了两个层级的闭环：

- 新建任务 `b12b5785-f90a-42c2-8c4f-67c54ab690e4`：M3 前端提交 → API → DB 持久化 → 前端详情 → API 查询 → DB 查询 → UI 取消 → API/DB 取消一致。该链路 PASS，但只覆盖 P1 接管前的受理闭环。
- 既有真实任务 `f47eb1cf-f038-4f9f-ae3d-e02aa8a995d3`：产品结果页 → API → DB → F04 发现计数 → F05 模块状态 → F06 双集合/封面。该链路 PASS，但终态为 `PARTIAL_COMPLETED`，说明系统正确展示部分完成，不证明“全量完成”闭环。

完整的新任务从 M3 创建到 F04/F05/F06 采集完成在当前环境 BLOCKED：只运行了 `xingtu-api`，未运行 `xingtu-product intake-worker` 或 collection worker。

## 9. F05 安全验证专项回归

本轮通过现有自动化覆盖 CHALLENGE-01 的合成/离线路径：挑战期间零业务请求、5 秒稳定恢复门槛、达人/任务次数上限、超时部分完成、检查点兼容、产品状态展示等相关单元/契约/集成均随套件通过。

真实平台自然安全验证未触发，本轮也未主动制造风控。因此以下项仍 BLOCKED：同一 BrowserHost/Context/Page/租约的真实恢复、真实恢复只增加一次 `session_version`、重复业务请求下降至少 50% 的真实对比证据、Worker 重启后的真实挑战恢复验证。

## 10. 缺陷清单

### D-SMOKE-001：新建 UI 任务未进入 P1/P2 执行链路

- 严重等级：P1 / 环境阻塞。
- 复现步骤：登录本地 UI；创建关键词“冒烟测试”、目标 1；进入任务详情。
- 预期结果：若完整执行环境启动，任务应由 Intake Worker 接管，进入 PARSING/QUEUED/COLLECTING。
- 实际结果：任务停留 `RECEIVED`；DB `intake_sent=false`；只读进程检查仅发现 `xingtu-api`，没有 Intake Worker/Collection Worker。
- 证据：root `b12b5785-f90a-42c2-8c4f-67c54ab690e4`；DB 查询 `root_state=CANCELLED`、`intake_sent=false`（取消前为 RECEIVED）。
- 可能涉及模块：M3 运行环境、Intake Worker、Collection Worker。
- 推荐修复方向：冒烟环境启动脚本应明确同时启动 API、frontend、Intake Worker、Collection Worker，并在 UI 冒烟前做 worker health/readiness 检查。

### D-SMOKE-002：真实产品样本任务仍为 F05 范围不完整

- 严重等级：P2 / 已知业务缺口。
- 复现步骤：打开 root `f47eb1cf-f038-4f9f-ae3d-e02aa8a995d3`；查看任务详情和第一个达人详情。
- 预期结果：完整闭环样本应为 `COMPLETED` 且 F05/F06 均完整。
- 实际结果：任务为 `PARTIAL_COMPLETED`，失败原因 `PROFILE_SCOPE_INCOMPLETE`；第一个达人 `fans` 模块 `FAILED`，页面和 API 如实展示。
- 证据：任务详情 snapshot `.playwright-mcp/page-2026-10-10T14-18-03-014Z.yml`；达人详情 snapshot `.playwright-mcp/page-2026-10-10T14-18-27-144Z.yml`；API counts `profile_complete_count=0`、`featured_complete_count=2`。
- 可能涉及模块：F05 平台契约、M3 结果展示。
- 推荐修复方向：继续按 F05 scoped contract health 调研 `fans` 模块 Schema 变化；保持 M3 当前部分完成展示，不应改为成功。

### D-SMOKE-003：缺少真实安全验证自然触发/恢复证据

- 严重等级：P2 / 验收缺口。
- 复现步骤：本轮不主动触发平台安全验证；仅运行合成自动化。
- 预期结果：CHALLENGE-01 最终验收需要真实挑战等待、同页恢复、session_version 增量和重复请求下降证据。
- 实际结果：自动化通过，但真实自然挑战未发生。
- 证据：CHALLENGE-01 卡片仍有真实恢复与重复请求降幅未勾选项；本报告 ST-014。
- 可能涉及模块：F05 ChallengeHandler、BrowserHost、Worker。
- 推荐修复方向：等待自然触发或用户授权小样本验收，禁止高频制造风控。

## 11. 未执行与阻塞项

- 未执行真实新任务 P1/P2/采集完成：当前只运行 API，无 Intake Worker/Collection Worker；为避免后续真实采集，测试任务已取消。
- 未执行真实平台安全验证专项：不主动触发风控，等待自然出现或受控授权。
- 未执行生产 HTTPS/域名/Secure Cookie：APP-01 本身仍标记待验收，当前是 localhost HTTP 开发环境。
- 未执行 F04 Page 3+、筛选枚举组合、访问节奏实机扩展：F04 卡片原本仍待验收，本轮未扩大平台请求。
- 未执行真实 DeepSeek 重新调用：本轮未启动 Intake Worker，避免额外模型成本；M3 真实模型闭环引用既有任务和自动化证据。

## 12. 最终验收结论

1. F04 是否通过核心冒烟测试？PASS。脚本与既有真实任务发现计数通过；分页/筛选扩展仍是原有待验收项。
2. F05 是否通过核心冒烟测试？PARTIAL PASS。自动化通过；真实样本保留 `fans` 模块失败并形成 `PARTIAL_COMPLETED`，未伪报完成。
3. F06 是否通过核心冒烟测试？PASS。双集合、卡片、封面对象存储和结果展示均通过。
4. M3 是否通过核心冒烟测试？PASS for UI/API/DB 受理、操作、结果读取；BLOCKED for 新任务完整执行，因为 worker 未启动。
5. Playwright MCP 真实界面操作是否成功？PASS。实际执行登录、创建、取消、结果查看、退出和会话保护。
6. 完整端到端业务闭环是否通过？PARTIAL。既有真实任务可读到 P1→P2→F04/F05/F06 的部分完成结果；本轮新建任务未推进到采集完成。
7. F05 安全验证优化是否通过回归？PARTIAL PASS。合成/自动化回归通过，真实自然挑战恢复仍 BLOCKED。
8. 当前是否存在阻塞上线的问题？有。若上线标准要求“新任务从 UI 创建到采集完成”的现场证明，则当前冒烟不满足；必须启动并验证 Intake Worker/Collection Worker，同时补真实安全验证恢复证据和生产 HTTPS/Secure Cookie 验收。
