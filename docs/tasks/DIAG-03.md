# DIAG-03：24 位任务在第 20 位失败与「继续采集」失败修复

状态：已完成（数量目标与执行失败修复；原任务真实续采 24/24）
是否验收：是（本轮范围：失败定位、跨页/续采修复、24 位真实入库与前端一致性；资料/精选完整度与全新首跑重放不作为本轮阻塞）
更新时间：2026-10-26T22:40:00+08:00
关联功能：F04（搜索与候选发现）、F05（主页资料）、F06（精选集合）、F07（任务操作）、QA-01（20+ 分页）、RETRY-01（继续/补采拆分）、DIAG-02（执行单元）
关联任务：`8013a009-c058-441e-a99f-9976c7d48df0`（target=24，valid=20，FAILED）

## 目标与范围

定位并修复真实任务 `8013a009-c058-441e-a99f-9976c7d48df0` 在采集到第 20 位时以
`PLATFORM_PAGE_CHANGED:BROWSER_ACTION_FAILED` 失败、点击「继续采集（还差 4 位）」后再次失败的缺陷。
重点区分「分页/游标问题」与「单个达人可选模块动作超时导致任务级失败」，并保证：

- 有效数未达标时能继续补足数量，不被已计数达人的缺失字段阻塞；
- 单个可选模块动作失败不再中止整个任务，已成功数据保留；
- 达到 24 位后正确收口，DB/API/前端一致；
- 不破坏现有分页、去重、状态机、账号并发、人工验证接管与执行单元隔离。

包含：

- 基于任务日志、checkpoint、快照、Temporal 记录、Chrome History 与 Git 历史的只读诊断。
- 最小修复：profile 可选模块动作超时局部化；继续采集不重入已计数 `collecting` 候选人。
- 单元 / 契约 / 集成 / E2E / 前端回归；原任务真实 Playwright MCP + Chrome 续采验收。
- 诊断与修复报告、任务卡、索引、总览、架构与 RETRY-01 交叉引用同步。

明确不做：

- 不改数据库 Schema、迁移、`TaskRecord`/`Candidate` 持久化结构。
- 不改 `adapter.search()`、engine 搜索循环、游标/页码、契约分页字段。
- 不改前端、Workflow、Temporal 拓扑、账号并发、人工验证接管、执行单元隔离。
- 不重跑一次全新的 20+ 真实采集来验证首次跨页；首次跨页由集成用例 + 既有 QA-01 PG-03 真实证据覆盖。
- 初始范围不含 commit/push；2026-10-26 用户明确授权代码审查与合入后，由审查会话提交
  `609c8db`、经 merge `bb29801` 合入 `main` 并推送。

## 关联与依赖

- 任务证据：`.runtime/evidence/failure/8013a009-c058-441e-a99f-9976c7d48df0/` 两份失败 JSON。
- Worker 日志：`.runtime/logs/collection-worker.log`（21:30:50、21:33:56 两次 `Locator.click` 90s 超时）。
- 业务库：`root_tasks` / `task_attempts` / `task_checkpoints` / `creator_snapshots` / `audit_logs`。
- 关联卡片：[RETRY-01](RETRY-01.md)、[QA-01](QA-01.md)、[DIAG-02](DIAG-02.md)、[F05](F05.md)、[F06](F06.md)。
- 决策：[DEC-019 重试目标拆分](../decisions/DEC-019-retry-scope-split.md)。
- 报告：[DIAG-03 修复报告](../evidence/DIAG-03-24-creator-page-boundary-fix-2026-10-26.md)。

## 验收清单

- [x] DIAG-03A 只读定位失败位置：第 20 位候选 `fans` 模块动作 90s 超时；两次独立页面加载均复现。
- [x] DIAG-03B 分页核验：第 2 页请求从未发起；确认不是游标/页码/去重导致，不修改分页代码。
- [x] DIAG-03C 历史变更核验：`024f879` 的浏览器错误分类变更与 `61f76d2` 的续采策略缺口的实际影响。
- [x] DIAG-03D 修复：非 basic profile 模块的 Playwright 动作/就绪超时降级为 `MODULE_COLLECTION_FAILED`，挑战/登录/session/lease/identity 仍 fatal。
- [x] DIAG-03E 修复：`CONTINUE` 下已计数 `pending`/`collecting` 候选统一收敛为 `done`，本次不重访。
- [x] DIAG-03F 单元测试：retry policy 新语义；计数/重试统计不回归（327 passed）。
- [x] DIAG-03G 契约测试：模块动作超时确实转为模块局部失败（40 passed）。
- [x] DIAG-03H 集成测试：target=20 单页；target=24 跨页；第 20 位模块超时仍到 24；续采跳过已计数并搜索第 2 页；22/24 可用时正确耗尽（5 passed）。
- [x] DIAG-03I 离线回归：unit 327、contract 40、integration 108+1 skip、e2e 9、frontend 89+build、mypy 36 files、ruff 改动文件通过（既有 `scripts/acceptance` UP031 除外并如实记录）。
- [x] DIAG-03J 真实 E2E：原任务经 Playwright MCP + Chrome 续采至 `valid=24/24`，请求第 2 页，未重访 20 位已入库达人，任务不是 `FAILED`。
- [x] DIAG-03K 数据核验：`task_creators=24`、新增 4 份快照、无重复入库、Chrome History 仅 4 位新主页。
- [x] DIAG-03L 前端核验：任务页显示 24 位（「查看更多达人」后）、不再显示执行失败；任务页无登录后运行期错误（登录前 `/api/auth/me` 一次预期 401）。
- [x] DIAG-03M 文档：修复报告、卡片、索引、总览、架构 §6.8、DEC-019、RETRY-01 交叉引用同步。
- [x] DIAG-03N 残余如实登记：第 20 位 `fans` 标签缺失/受阻的 DOM 级原因；既有 6/24 资料完整度与 0/24 精选完整度；首次 24 首跑未重复执行。

## 实现记录

- 2026-10-26T21:54：建立卡片。只读诊断已完成：任务 20 位候选全部有效，第 20 位 `7057631599210266654` 停在 `collecting`，`fans`/`creation` 缺失；Worker 日志两次均为 `.el-tabs__item:has-text('连接用户')` 点击 90s 超时；第 2 页搜索从未发起；续采 `retry:continue` 后重入同一候选人并再次失败。
- 2026-10-26T22:03：实施 `adapter.py` 模块动作超时局部化与 `retry_policy.py` 续采收敛；新增单元/契约/集成测试。
- 2026-10-26T22:05：重启 local-main（API/intake/collection/frontend；update-scheduler 未启动）；collection 首次撞 45s 旧心跳窗口退出，等待后 `up` 成功，generation=9、pid 84779。
- 2026-10-26T22:06—22:17：原任务通过 Playwright MCP + Chrome 续采：20/24 → 24/24，`PARTIAL_COMPLETED`，第 2 页真实入库 4 位；无重复、无已计数达人重访；前端 24 行。
- 2026-10-26T22:18：离线回归完成（unit 327、contract 40、integration 108+1 skip、e2e 9、frontend 89+build、mypy 36 files、ruff 改动文件）。
- 2026-10-26T22:20：报告、任务卡、索引、总览、架构 §6.8、DEC-019、RETRY-01 交叉引用回写。

## 验证证据

- 修复报告：[DIAG-03-24-creator-page-boundary-fix-2026-10-26](../evidence/DIAG-03-24-creator-page-boundary-fix-2026-10-26.md)。
- 真实 E2E：[continue-evidence.json](../evidence/assets/diag03/continue-evidence.json)；截图
  [before](../evidence/assets/diag03/continue-before.png)、
  [after](../evidence/assets/diag03/continue-after.png)、
  [after-more](../evidence/assets/diag03/continue-after-more.png)。
- 任务终态：`PARTIAL_COMPLETED`、`valid=24/24`、`discovered=40`、`profile_complete=6`、
  `featured_complete=0`、`failed=0`、segment=2；`task_creators=24`（distinct 24、重复 0）、
  `creator_snapshots=44`（20 旧×2 + 4 新×1）；第 2 页 `processed_operations=3`、
  `visited_cursors=[null,"2"]`、`cursor="3"`。
- 不重访：续采后 unit profile Chrome History 仅 4 个新达人主页（7458517895514062898 /
  7069339222624174111 / 7441957186432925722 / 6771315413448916999），20 位旧达人 0 次。
- 离线：unit 327 passed；contract 40 passed；integration 108 passed / 1 skipped（173.88s）；
  engine targeted 34 passed；new integration 5 passed；e2e 9 passed；frontend 89 passed、lint/build；
  mypy 36 files；ruff/format 改动文件通过。
- 未执行/未重放：第 20 位 `fans` DOM 级原因、模块超时真实首跑、全新 24 首跑、资料/精选完整度；
  见报告 §4.3。
- 2026-10-26T22:31—22:39 提交前复跑（工作区基于 `main@f52b7fb`）：unit 327、contract 40、
  integration 108 passed / 1 skipped、e2e 9、frontend 89 + `tsc -b` + build、mypy 36 files、
  ruff/format 改动文件通过。契约与 `tests/e2e/test_product_frontend.py` 需
  `PLAYWRIGHT_BROWSERS_PATH=.runtime/browsers`（首次未设置时 33 个契约用例与 2 个 E2E 用例因
  浏览器缺失失败，属环境未就绪，重跑通过）；`make lint` 的 11 个 `scripts/acceptance` UP031 与
  3 个 `scripts/acceptance` format 问题为既有、本轮未改。

## 交接信息

- 阻塞：无。
- 残余：第 20 位 `fans` 模块不完整仍会使其资料不完整；后续「补采缺失字段」可能再次得到模块
  不完整结果，但不再导致任务执行失败。4 位新达人 basic/fans/creation 均完整，精选集合仍
  INCOMPLETE/FAILED/EMPTY（本任务 46 行：35 INCOMPLETE / 9 EMPTY / 2 FAILED），精选完整度
  0/24 属既有 F3/F06 缺口，不在本轮范围。
- 风险：若后续真实采集遇到挑战/登录失效，按现有接管机制停止，不绕过验证；若平台第 2 页无
  更多可用达人，按 `SEARCH_EXHAUSTED` 收口并如实报告实际数量。
- 提交状态：已提交 `609c8db`，经 merge `bb29801` 合入 `main` 并推送；工作区仅剩与本卡无关的
  未跟踪截图 `qa01-retry-trigger.png`（未提交）。

## 状态历史

- 2026-10-26T21:54:03+08:00：新建 → 进行中；诊断完成，等待实施最小修复。
- 2026-10-26T22:20:00+08:00：进行中 → 已完成；修复、离线回归、原任务真实续采 24/24、前端/DB 核验与文档回写完成；资料/精选完整度、模块超时真实首跑、全新 24 首跑作为如实登记的残余，不阻塞本轮数量与执行失败修复。
- 2026-10-26T22:40:00+08:00：保持已完成（补充提交/合并记录）：用户授权本轮审查后提交前复跑离线检查通过，提交 `609c8db`、merge `bb29801`、推送 `main`；未改代码逻辑与验收结论。
