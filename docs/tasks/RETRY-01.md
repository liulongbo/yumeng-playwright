# RETRY-01：任务「继续采集」与「补采缺失字段」双语义拆分

状态：进行中（代码已按用户授权提交并合并至 main；F1 快照去重、F2 搜索耗尽死循环、F3 封面存储、F5 运行期隔离仍待修复后复测）
更新时间：2026-10-24T20:44:00+08:00（Asia/Shanghai）
是否验收：否（真实 E2E 与 Playwright MCP 验收均发现 F1/F2 待修；F3 封面存储、F5 执行单元运行期隔离阻塞；Windows 不适用）
关联功能：F07（任务列表/进度/操作）、CONSOLE-01、QA-01、DIAG-01、FIX-01、UPD
关联需求：[RETRY-01 产品需求文档](../prd/RETRY-01-retry-and-backfill.md)（2026-10-24 批准）
关联决策：[DEC-019 重试目标拆分](../decisions/DEC-019-retry-scope-split.md)

## 目标与范围

把「任务失败后继续采集」与「任务已完成后补采缺失字段」拆成两个清晰、互不混淆的业务行为：数量未达标时优先补足数量、本次不重访已入库达人；数量已达标时只补缺失资料、不搜索不新增达人。最小改动，不改状态机、不加迁移、不改工作流。

包含：

- 服务端单一事实源的重试策略（继续采集 / 补采缺失字段），产品 API 与内部 CLI 共用。
- 重试入队规则：继续采集只恢复未计入有效数的候选；补采只恢复已入库但不完整的达人。
- 任务详情读模型新增 `retry_plan`（本次目标、还差数量、待补采数量、上次重试时间、上次重试后更新人数）。
- 补采时跳过已完整的精选；终态收口时不再为内容未变化的达人重复生成资料版本。
- 安全验证终态：接口与页面规则对齐（不再允许通过接口重试）。
- 前端按钮文案、二次确认、关注区提示、计数卡副标题、上次重试与「首次完成时间」。
- 单元 / 集成 / 前端测试与任务卡、索引、总览、技术方案、架构文档同步。

明确不做（对应 PRD §1.5、§11 推荐项）：

- 不新增任务类型、任务状态、数据库表或迁移；不改 `TaskRecord`/`Candidate` 持久化结构。
- 不做双入口（D1=A）；不设补采无进展上限（D2=A）；不开放搜索耗尽再搜（D3=A）；不开放安全验证后继续（D5=A）。
- 不改 `workflow.py`、`adapter.py`、`contracts/`、F10、租约/generation/执行单元隔离。
- 不发起真实采集；提交/推送/合并按 2026-10-24 用户单独授权执行（见实现记录与状态历史）。

## 关联与依赖

- 产品依据：[RETRY-01 PRD](../prd/RETRY-01-retry-and-backfill.md)；决策 [DEC-019](../decisions/DEC-019-retry-scope-split.md)。
- 前置证据：[QA-01 重试语义核验](../evidence/QA-01-retry-semantics-2026-10-24.md)、[QA-01](QA-01.md) 的 QA01-11、[DIAG-01](DIAG-01.md) ISSUE-006、[FIX-01](FIX-01.md)。
- 业务契约：技术方案 §8.1（任务操作）、§14.5（重试语义）、§18 T27（精选集合变化）已同步。
- 架构文档：[任务中心架构](../任务中心架构.md) §6.8 已同步。
- 代码基线：分支 `快手_1024`，基线 HEAD `024f879`；本卡提交 `61f76d2`，与 DIAG-02 的 `3a7be00` 一起合并为 `fa28876`。
- 隔离测试库：临时创建 `xingtu_test_retry01`（PostgreSQL 18.3，本机 55432），集成测试使用独立 schema 并在结束时删除；本轮验证完成后已整库删除，未触碰开发库。

## 验收清单

- [x] RETRY-01A 重试策略单一事实源：`retry_policy.py` 的 `RetryScope/decide_retry_scope/requeue_for_retry/is_retryable/challenge_blocks_retry`，覆盖 PRD §6.2 全部分支。
- [x] RETRY-01B 两个命令入口（产品 API 与 CLI）共用同一策略，行为一致；审计动作记录 `retry:continue` / `retry:backfill`。
- [x] RETRY-01C 继续采集：已入库达人主页访问次数为 0，只采剩余数量；已计数候选不被重新入队。
- [x] RETRY-01D 补采缺失字段：不搜索、不新增达人；只采缺失模块，已完整模块观测不变。
- [x] RETRY-01E 补采跳过已完整的精选集合，不重复加载。
- [x] RETRY-01F 终态收口不再为内容未变化的达人生成新资料版本（按 payload 比对，只写变化项）。
- [x] RETRY-01G `retry_plan` 读模型：scope、还差数量、待补采数量、上次重试时间、上次重试后更新人数；无迁移、无 payload 字段。
- [x] RETRY-01H 安全验证终态：页面不出现重试，产品 API 与 CLI 均拒绝。
- [x] RETRY-01I 前端：按钮文案、二次确认、关注区提示、计数卡副标题随目标变化；旧响应回退旧文案；更新任务保留中性文案。
- [x] RETRY-01J 正常首次采集零回归（单元/契约/集成/E2E/前端）。
- [x] RETRY-01K 自动检查：mypy strict、ruff、format（本轮改动文件）、单元、契约、集成、前端 lint/test/build 通过。
- [x] RETRY-01L 任务卡、任务索引、项目总览、PRD、技术方案、架构文档、DEC-019 已同步。
- [x] RETRY-01M 真实 Chrome E2E：直接 Playwright 一轮（3 真实任务 + 3 只读对照，**13 通过 / 2 失败**，[报告](../evidence/RETRY-01-real-e2e-2026-10-24.md)）+ **Playwright MCP + Chrome** 一轮（MCP-01—MCP-10，[报告](../evidence/RETRY-01-mcp-acceptance-2026-10-24.md)）。
- [ ] RETRY-01O 修复 F1：带精选卡片的无变化重试不再重发快照（卡片 `content_id` 在序列化前解析）。
- [ ] RETRY-01P 修复 F2：搜索耗尽且无可补候选时，重试目标转为「补采缺失字段」并说明剩余无法补足（需产品确认）。
- [ ] RETRY-01Q 处理 F3：恢复封面对象存储或实现存储类失败兜底，停止无限推荐补采。
- [ ] RETRY-01S 处理 F5：执行单元运行期隔离（`browser_stopped=false`）后任务停摆，需 Worker 重启才能恢复；建议运行期周期回收 + 页面恢复提示。
- [ ] RETRY-01R 修复后复测 TC-01—TC-15 并更新报告。
- [x] RETRY-01N 隔离 PostgreSQL 集成测试已执行（103 passed, 1 skipped）。

## 实现记录

- 2026-10-24T14:37：建立卡片，状态「进行中」；PRD 落盘到 `docs/prd/RETRY-01-retry-and-backfill.md`。
- 2026-10-24T14:40—14:46：新增 `backend/src/xingtu/retry_policy.py`；`ProductQueries.command()` 与 `Repository.command()` 接入派生策略；`allowed_actions` 与两个命令统一使用安全验证拦截；审计动作记录本次目标。
- 2026-10-24T14:46：新增 `RetryPlan` 与 `TaskDetail.retry_plan`；从 `audit_logs` 读上次重试时间、从 `creator_snapshots` 统计本次重试后更新的达人数；P1 阶段重试不写 scope（避免无候选队列时误用派生目标）。
- 2026-10-24T14:47：引擎在补采时跳过已完整的精选集合；`persist_creators()` 批量比对最新快照 payload，只写入内容变化或首次发布的达人。
- 2026-10-24T14:47—14:50：前端 `TaskActions` 按 `retry_plan.scope` 输出「继续采集（还差 N 位）」/「补采缺失字段（M 位）」并二次确认；关注区按目标改写；计数卡增加「还差 N 位 / 待补采 M 位」；终态显示「上次重试」；「完成时间」改称「首次完成时间」（PRD D4）；更新任务保留「重试失败步骤」。
- 2026-10-24T14:50：新增/调整测试：`test_retry_policy.py` 6 例；`test_engine.py` 3 例；`test_product_m3.py` 3 例；`test_featured.py` 调整已完整精选不重载的断言，并新增「未完成模块才重采并记录集合变化」的 T27 用例；`App.test.tsx` 5 例。
- 2026-10-24T14:52：同步技术方案 §8.1/§14.5/§18 T27 与任务中心架构 §6.8；新增 DEC-019。
- 2026-10-24T15:18：为加载新代码仅重启 API（pid 12680）与 Collection Worker（generation 6，pid 12917）；未启动 update-scheduler；前端由 Vite HMR 加载。
- 2026-10-24T15:18—15:31：执行真实 UI 回归（Playwright + 系统 Chrome 156）。用例见报告 §3；证据 `docs/evidence/assets/retry01/`（6 JSON + 12 截图）。
- 2026-10-24T15:21：383474a1 继续采集：2 位已入库达人的模块/精选观测 ID 与历史全部不变，仅 1 次搜索条件重建；但快照 2→4（F1）、按钮仍为「继续采集」（F2）。
- 2026-10-24T15:22：2cf27cbe 补采：无搜索批次、只有 1 个失败模块重读；因封面存储不可达仍部分完成（F3）。
- 2026-10-24T15:29：383474a1 第二次继续采集：快照 4→4、`changed=0`，证明去重在 payload 一致后有效；按钮仍为「继续采集」，确认死循环（F2）。
- 2026-10-24T15:29：新建真实 target=1 任务 7a9b1991，正常完成首次采集（有效 1/1、1 快照），创建与首次采集无回归。
- 2026-10-24T20:38—20:44：用户授权提交/推送/合并。按任务拆分提交：`3a7be00`（DIAG-02）与
  `61f76d2`（本卡），合并 commit `fa28876`；已推送 `origin/快手_1024` 与 `origin/main`。合并前在
  工作区重跑全套检查（见验证证据），未新增业务改动，F1/F2/F3/F5 保持未修。
- 2026-10-26T22:20：DIAG-03 补齐本卡未覆盖的已计数 `collecting` 分支：`requeue_for_retry()`
  现把 `CONTINUE` 下已计数 `pending`/`collecting` 统一收敛为 `done`，不再重入同一失败达人；
  真实任务 `8013a009` 从 20/24 续采到 24/24，20 位旧达人主页 0 次重访。另修复 profile 非 basic
  模块动作超时被误升为任务级失败的问题。详见 [DIAG-03](DIAG-03.md)。
- 2026-10-26T22:40：DIAG-03 修复提交 `609c8db`，经 merge `bb29801` 合入 `main` 并推送；F1/F2/F5
  仍未修，本卡保持进行中。

## 验证证据

- 单元：`.venv/bin/pytest backend/tests/unit -q` → **327 passed**（含新增 `test_retry_policy.py` 6 例）。
- 契约：`make test-contract`（`PLAYWRIGHT_BROWSERS_PATH=.runtime/browsers`）→ **39 passed**。
- 集成（隔离 PostgreSQL）：
  - 全量 `backend/tests/integration` → **103 passed, 1 skipped**（152.00s，exit 0）。
  - 定向：`test_engine.py` 29 passed（含继续采集只采剩余达人、补采不搜索且不重载已完成精选、未变化达人不重发快照、安全验证终态拒绝直接重试）。
  - 定向：`test_product_m3.py` 20 passed（含 `retry_plan` 派生、命令保留已计数达人并记录目标、挑战拒绝）。
  - 定向：`test_featured.py` 4 passed（含已完整精选在补采中不重载、未完成模块重采并记录集合变化）。
- E2E：`tests/e2e`（本地 Temporal 测试服务器 + 项目 Chromium）→ **9 passed**（9.30s，exit 0）。首次直接运行因环境缺失失败：无法下载 ephemeral Temporal server（`No such file or directory`），且未设置 `PLAYWRIGHT_BROWSERS_PATH` 导致浏览器用例找不到可执行文件；设置 `XINGTU_TEMPORAL_TEST_BINARY=.runtime/local-main/bin/temporal` 与项目浏览器路径后通过，两份日志均已保留，属环境缺口而非代码回归。
- 前端：`make frontend-check` → lint（tsc）通过、**89 passed**（6 files）；`make frontend-build` 通过。
- 静态检查：`mypy backend/src` → 36 files，无问题；本轮改动文件 `ruff check` / `ruff format --check` 通过。
- 既有问题（非本轮引入）：`make lint` 在 `scripts/acceptance/run_cd05/06/07_acceptance.py` 报 11 个 UP031；`make format-check` 对同 3 个文件报需重排。已核对 `git diff`，本轮未改动这些文件，按范围纪律不顺手修改。
- **MCP 验收（2026-10-24 15:43—15:58）**：Playwright MCP 0.0.77 + Chrome 156，stdio 启动 MCP 服务（23 个工具）；MCP-01—MCP-10 全部执行：5/5 文案、2/2 接口负向（409 ACTION_NOT_ALLOWED）、继续采集 0 重访且快照 4→4、补采 0 搜索且只重读 basic；补采运行中触发 F5 执行单元隔离，重启 Worker 后自动续跑完成。报告 [RETRY-01-mcp-acceptance-2026-10-24](../evidence/RETRY-01-mcp-acceptance-2026-10-24.md)；证据 `docs/evidence/assets/retry01-mcp/`（11 截图 + 20 JSON）；MCP-10 通过表单新建 `8b0f0393`，首次采集正常（有效 1/1、1 快照）。
- 真实 E2E（2026-10-24）：Playwright + Chrome 156，3 个真实任务 + 3 个只读对照 + API 负向；**13 通过 / 2 失败**（另发现 F3 环境阻塞）；报告 [RETRY-01-real-e2e-2026-10-24](../evidence/RETRY-01-real-e2e-2026-10-24.md)；证据 `docs/evidence/assets/retry01/`（preflight/continue-run1/continue-run2/backfill/api/create 6 JSON + 12 截图）。
- 关键实证：继续采集 0 次重访（8 模块 + 2 精选观测 ID 不变）；补采 0 次搜索批次（`processed_operations`/游标不变）且只重读 1 个失败模块；已完成/安全验证终态接口返回 422；新建任务首次采集正常。
- 未通过：F1 无变化重试重发 2 份快照且页面显示「更新了 2 位」；F2 搜索耗尽后按钮永久停在「继续采集」；F3 封面 S3 不可达导致精选永久不完整、补采循环。
- 数据与环境：临时测试库 `xingtu_test_retry01` 仅用于集成测试，测试夹具使用独立 schema 并在结束时删除；本轮未访问巨量星图、未创建真实任务、未修改业务库。
- 合入前回归（2026-10-24T20:35—20:44，工作区 = `61f76d2` 合并树）：单元 327 passed；契约 39 passed；
  集成（临时库 `xingtu_test_retry01`，PostgreSQL 18.3@127.0.0.1:55432）103 passed / 1 skipped
  （144.95s，exit 0）；E2E（本地 Temporal + 项目 Chromium）9 passed（8.63s）；前端 `tsc` + 89 passed、
  `npm run build` 通过；`mypy backend/src` 36 files 无问题；改动文件 `ruff check`/`format --check`
  通过。`make lint`/`format-check` 仍只在既有 3 个 `scripts/acceptance` 文件失败（11 处 UP031），本轮
  未改动这些文件。集成用的临时库在验证后已整库删除，开发库未触碰。

## 交接信息

- 阻塞：F3 的封面对象存储 `http://100.86.124.51:9000` 不可达（非代码阻塞；恢复前精选无法完整）。
- 待修：
  1. **F1（P1）**：`repository.persist_creators` 在序列化快照前解析卡片 `content_id`；补集成用例；复测 383474a1 第三次重试应 `4→4`、`changed=0`。
  2. **F2（P1，需产品确认）**：`retry_policy.decide_retry_scope` 在搜索耗尽且无可补候选时转 BACKFILL，并更新文案；补单元/集成/前端用例。
  3. **F3（P1，环境+兜底）**：恢复/改指封面存储；产品侧增加存储类失败兜底，停止无限推荐补采（对应 PRD D2）。
  4. **F4（P3）**：`changed=0` 时文案改为「本次重试未产生新的达人资料」。
- 其他遗留：
  1. `make lint` / `make format-check` 的既有 `scripts/acceptance` 11 处 UP031 与 3 个文件格式问题仍在，属既有技术债。
  2. PRD 决策 D2、D5、D7-B 按推荐留待后续。
- 风险：
  - 「补采不重载已完成精选」改变了既有 T27 测试的触发路径：已完整集合在补采中不再刷新；技术方案 T27 已按新契约澄清，并新增「未完成模块重采」用例保留集合变化覆盖。若产品希望补采同时刷新精选，需要恢复逐次重读或引入显式刷新入口（后续决策）。
  - 集成测试依赖隔离 PostgreSQL；本轮临时库已建，后续执行需重新配置 `XINGTU_TEST_DATABASE_URL`。
- 下一步：用户审阅；先按产品确认处理 F2（D3 是否调整），再修 F1/F3/F5 并复测 TC-01—TC-15 与 MCP-01—MCP-08。代码已合并，不重复提交。

## 状态历史

- 2026-10-24T14:37:00+08:00：建立 → 进行中；PRD 已获批准，按推荐决策 D1–D7 实施最小方案。
- 2026-10-24T15:00:00+08:00：进行中 → 待验收；实现、自动检查（含本地 Temporal E2E 9 passed）与文档回写完成；真实 Chrome 小样本 E2E 未执行。
- 2026-10-24T15:35:00+08:00：待验收 → 进行中；真实 Chrome E2E 完成，核心语义通过，发现 F1/F2/F3/F4，修复后复测。
- 2026-10-24T15:56:00+08:00：Playwright MCP + Chrome 验收完成（MCP 0.0.77，stdio 23 工具）：MCP-01—MCP-10 执行；接口负向更正为 409 ACTION_NOT_ALLOWED；补采中新增 F5 执行单元运行期隔离，重启 Worker 后自动续跑；仍待修 F1/F2/F3/F5。
- 2026-10-24T20:44:00+08:00：状态保持进行中（不进入待验收）。用户授权提交/推送/合并：`61f76d2`（本卡）与 `3a7be00`（DIAG-02）经 merge `fa28876` 合入 `main` 并推送；合入前单元/契约/集成/E2E/前端/静态检查全部通过；F1（一次性重发快照）、F2（搜索耗尽后继续采集空转，需 D3 产品确认）、F3（封面存储不可达）、F5（运行期隔离需重启 Worker）作为已知缺口保留。
