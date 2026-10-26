# DIAG-03：24 位任务在第 20 位失败与「继续采集」失败修复报告（2026-10-26）

> 任务卡：[DIAG-03](../tasks/DIAG-03.md)。任务：`8013a009-c058-441e-a99f-9976c7d48df0`。
> 环境：`main@f52b7fb` 工作区最小修复；单机原生 `local-main`；`unit-local-mac-02`；Chrome 156；
> Playwright MCP `1.62.0-alpha-2026-06-29`（23 个工具）。真实 E2E 22:06—22:17（Asia/Shanghai）。
> 证据目录：[assets/diag03](assets/diag03/)；结构化结果：[continue-evidence.json](assets/diag03/continue-evidence.json)。

## 1. 问题结论

### 1.1 真正的根因

**直接根因不是分页，而是单个可选模块动作超时被当成任务级失败。**

- 第 20 位达人 `7057631599210266654` 的 `fans` 模块注册动作
  `.el-tabs__item:has-text('连接用户')` 在 90 秒内未变为可点击。
- worker 将其包装为 `PLATFORM_PAGE_CHANGED:BROWSER_ACTION_FAILED`；engine 未把该错误限定在
  `fans` 模块，直接以任务级 `FAILED` 收口，导致第 2 页搜索从未发起。
- 首次执行与续采各自独立打开一次该达人主页，均在同一个动作上 90 秒超时；Chrome History
  时间（21:28:29、21:32:14）与两份失败证据（21:30:50、21:33:56）一致。

### 1.2 为什么恰好是第 20 位

巨量星图当前搜索结果第 1 页返回 20 位。第 20 位恰好是第 1 页最后一位：

- 20 位候选全部已计入有效数并发布快照；
- 第 20 位的 `basic` 已成功（`valid_count` 先到 20），随后 `fans` 模块动作超时；
- 任务在进入第 2 页之前终止。

因此 **20 是单页容量造成的边界位置，不是游标/页码上限，也不是第 2 页被判重复**。
checkpoint 中 `processed_operations` 只有 1 个搜索操作、只有 20 个候选、`pending_page=null`，
第 2 页请求从未发生。

### 1.3 为什么「继续采集」也失败

- `retry:continue`（21:31:53）后，第 20 位候选仍是 `valid=true, state=collecting`；
  原 `requeue_for_retry` 只把已计数 `pending` 收敛为 `done`，保留 `collecting`，engine 又优先
  处理 `valid + pending/collecting` 候选。
- 续采重新打开同一位达人主页，`fans` 标签再次 90 秒超时，仍未走到第 2 页。
- 该缺口由 RETRY-01 的 `61f76d2` 引入；但预 RETRY-01 的旧代码同样会把「已有效但不完整」候选
  置回 pending，所以它是**续采缺口**，不是首次失败的新回归。

### 1.4 分页机制结论

- 契约 `next_page_mode=page_fetch`、`page_fetch_max_verified=3`、`resume_supported=false`；
  代码支持第 2 页。QA-01 的 PG-03 真实任务已有 `valid=21、40 候选、page2 position20 首位有效`
  证据。
- 本任务从未请求第 2 页；**本轮不修改** `adapter.search()`、engine 搜索循环、游标/页码或契约
  分页字段。收口后真实第 2 页请求成功（见 §3.3）。

### 1.5 历史变更判断

| 变更 | 影响 |
|---|---|
| `024f879`（2026-10-23，F10/QA-01） | `worker.py` 把未识别为浏览器关闭的 Playwright 动作超时从旧的 `RESOURCE_UNAVAILABLE:BROWSER_TRANSPORT`（Temporal 最多重试 4 次）改为立即 `PLATFORM_PAGE_CHANGED:BROWSER_ACTION_FAILED` 任务级失败。**这是本次失败表现（第 20 位立即整任务失败）的近期促成变更**；底层触发仍是第 20 位 `fans` 标签不可点击。 |
| `61f76d2`（2026-10-24，RETRY-01） | 已计数 `collecting` 候选仍由 engine 完成，导致续采重入同一失败达人。**是续采失败的直接原因**；旧代码也会重排已有效但不完整候选，因此不是首次失败的新回归。 |
| 分页/搜索代码 | 近期无改动；本任务第 2 页从未请求，**无分页回归证据**。 |

**结论**：`024f879` 的分类变更与 `61f76d2` 的续采缺口共同造成「一失败就整任务失败、续采又
重入」；真正需要修的是**模块动作超时的局部化**与**续采不重访已计数候选人**，不是分页。

## 2. 修复内容

### 2.1 文件与逻辑

| 文件 | 修改 | 为什么 |
|---|---|---|
| `backend/src/xingtu/adapter.py` | 新增 `PlaywrightTimeoutError` 导入；在 `BrowserAdapter.collect_module()` 中，对**非 basic** profile 模块的 `actions`/`wait_ready` 做局部化：Playwright 动作超时 → `MODULE_COLLECTION_FAILED:MODULE_ACTION_TIMEOUT:<key>`；`PAGE_READY_TIMEOUT` → `MODULE_COLLECTION_FAILED:MODULE_READY_TIMEOUT:<key>`。转换前执行 `check_page_errors(page)`，命中挑战/登录仍按原错误抛出。basic、session、challenge、login、lease、identity、浏览器关闭保持 fatal。 | 一个可选模块的 tab 不可点击不应杀死整个任务；adapter 知道模块 key，能留下准确观测，engine 已有 `MODULE_COLLECTION_FAILED` 局部处理。 |
| `backend/src/xingtu/retry_policy.py` | `requeue_for_retry()` 的 `CONTINUE` 分支：已计数 `pending` **和 `collecting`** 统一收敛为 `done`；未计数 `pending/collecting/failed` 仍置 `pending`。同步更新 docstring。 | 继续采集只补数量，不重访已入库达人；缺失模块留给数量达标后的「补采缺失字段」。同一未终态尝试内的 `collecting` 断点仍由 engine 恢复，不冲突。 |

### 2.2 影响面

- **不改**数据库 Schema、迁移、`TaskRecord`/`Candidate` 持久化结构、`retry_plan` 字段、前端 DTO、
  Workflow、Temporal 拓扑、账号并发、执行单元与人工验证接管。
- **不改** `adapter.search()`、搜索循环、游标/页码、契约 `page_fetch_max_verified`。
- 行为变化仅两处：可选 profile 模块动作超时不再升为任务失败；用户显式「继续采集」不再重入
  已计数 `collecting` 达人。
- 回滚：纯代码/测试/文档变更，回退两个源文件即可；旧 checkpoint/payload 保持可读，已产生的
  24 位数据不受影响。

### 2.3 测试新增/调整

- `backend/tests/unit/test_retry_policy.py`：已计数 `collecting` → `done`；未计数 `collecting`
  仍为 `pending`。
- `backend/tests/contract/test_browser_flow.py`：合成页面缺少模块 tab，真实 Playwright 点击超时
  后必须抛 `MODULE_COLLECTION_FAILED:MODULE_ACTION_TIMEOUT:broken`。
- `backend/tests/integration/test_engine.py`：新增 5 例——target=20 单页不取第 2 页；target=24
  跨页；第 20 位模块超时仍到 24；续采跳过已计数第 3 位并搜索第 2 页；22/24 可用时
  `SEARCH_EXHAUSTED`。既有继续/补采/分页/游标/耗尽用例保留未削弱。

## 3. 测试结果

### 3.1 离线测试

| 检查 | 命令 | 结果 |
|---|---|---|
| 单元 | `.venv/bin/pytest backend/tests/unit -q` | **327 passed** |
| 契约 | `PLAYWRIGHT_BROWSERS_PATH=.runtime/browsers .venv/bin/pytest backend/tests/contract -q` | **40 passed**（原 39 + 新增 1） |
| 集成（隔离 PG） | `XINGTU_TEST_DATABASE_URL=… xingtu_test .venv/bin/pytest backend/tests/integration -q` | **108 passed, 1 skipped**（173.88s，exit 0） |
| 集成定向（engine） | `… pytest backend/tests/integration/test_engine.py -q` | **34 passed**（150.79s） |
| 新增集成 5 例 | 见 §2.3 | **5 passed**（14.23s） |
| E2E | `PYTHONPATH=… XINGTU_TEMPORAL_TEST_BINARY=… pytest tests/e2e -q` | **9 passed**（8.73s） |
| 前端 | `npm --prefix frontend run lint && test && run build` | lint 通过；**89 passed**；build 通过 |
| 静态 | `.venv/bin/mypy backend/src`；ruff check/format（改动文件） | **36 files, no issues**；ruff/format 通过 |

已知既有问题：`make lint` / `make format-check` 在 `scripts/acceptance/run_cd05/06/07_acceptance.py`
报 11 个 UP031，本轮未改这些文件，未作为本轮失败。

### 3.2 真实 E2E 设置

- 代码加载：`./.runtime/dev-no-upd.sh restart`，collection 首次因旧 Worker 45 秒心跳窗口退出，
  等待窗口后 `up` 成功（generation=9，pid 84779）；`update-scheduler` 始终未运行。
- 原任务 `8013a009`：FAILED / 20/24；状态 `READY`、无 owner/lease、`browser_stopped=true`。
- 通过 Playwright MCP + Chrome 从前端点击「继续采集（还差 4 位）」，确认文案
  「本次只补足剩余 4 位有效达人，不会补采已入库达人的缺失资料。是否继续？」，接受后
  `POST /api/tasks/8013a009…/retry` → 200。
- 任务 22:06:48 `QUEUED`，22:17:25 `PARTIAL_COMPLETED`（约 10 分 37 秒）。

### 3.3 真实结果

| 项 | 结果 |
|---|---|
| 任务终态 | **`PARTIAL_COMPLETED`**（不是 `FAILED`；`failure_reason=PROFILE_SCOPE_INCOMPLETE`，segment=2） |
| 计数 | 目标 24，**有效 24/24**，已发现 40，失败步骤 0 |
| 第 2 页 | `processed_operations` 3 个；`visited_cursors=[null,"2"]`；`cursor="3"`；`scanned_ids=40`；`candidates=40`；第 2 页真实请求并入库 |
| 新增 4 位 | first_position 20—23：`7458517895514062898`、`7069339222624174111`、`7441957186432925722`、`6771315413448916999`，各 1 份快照 |
| 入库/去重 | `task_creators=24`、distinct=24；重复行 **0**；`creator_snapshots=44`（20 位旧达人各 2 份 + 4 位新达人各 1 份） |
| 不重访 | 续采后 unit profile Chrome History 仅出现上述 **4 个新达人主页**；20 位已入库达人主页 0 次 |
| 前端 | 任务页「部分完成」；有效入库 **24**、已发现 **40**、资料完整 **6**、精选完整 **0**、失败步骤 **0**；任务内达人初始 20 行 →「查看更多达人」后 **24 行**；不再显示「执行失败」 |
| 按钮 | 补采前「继续采集（还差 4 位）」；补采后「补采缺失字段（18 位）」 |
| Console | 任务页仅 React DevTools 信息；登录前 `/api/auth/me` 一次预期 401，无登录后运行期错误 |
| 执行单元 | 结束时 `READY`、owner/lease 为空、`browser_stopped=true`、`current_root_task_id=null` |

**关键截图**：[补采前（20/24，继续采集）](assets/diag03/continue-before.png)、
[补采后（24/24，部分完成）](assets/diag03/continue-after.png)、
[查看更多达人后 24 行](assets/diag03/continue-after-more.png)。

**结构化证据**：[continue-evidence.json](assets/diag03/continue-evidence.json)（完整驱动结果）、
[task-detail-before.json](assets/diag03/task-detail-before.json)（FAILED/20/24/continue）、
[status-final.json](assets/diag03/status-final.json)（PARTIAL/24/24/backfill 18）、
[units-after.json](assets/diag03/units-after.json)（单元 READY/STOPPED）。

### 3.4 场景矩阵

| 场景 | 验证 | 结果 |
|---|---|---|
| 数量小于单页 | 既有 `test_target_20_and_200`（page_size=50）；target=1 历史真实任务 | 通过（历史 + 回归） |
| 数量等于单页 | 新增 target=20/page_size=20 集成 | 通过：20 位，只搜索 1 次，不取第 2 页 |
| 24 位超过单页 | 新增 target=24/page_size=20 集成；原任务真实续采 | 通过：24 位，搜索 2 次，第 2 页入库 4 位 |
| 跨多分页 | 既有 target=200 用例；新增 24 用例 | 通过 |
| 第一页后下一页 | 新增 24 用例；本任务真实 `visited_cursors=[null,"2"]` | 通过 |
| 20/24 失败后继续 | 原任务真实 MCP 续采 | 通过：20→24，不是 FAILED |
| 续采遇已入库达人 | DB + Chrome History | 通过：0 次重访，4 位新达人 |
| 平台可用不足 | 新增 22/24 集成 | 通过：`valid=22`、`exhausted=true`、`SEARCH_EXHAUSTED`，不死循环 |
| 单模块动作超时 | Contract + Integration | 通过：模块局部失败，任务仍到 24；**未在真实首跑中重新触发**（见 §4.3） |

## 4. 最终结论

### 4.1 判定

**PASS（数量目标与执行失败修复）/ 任务终态仍为「部分完成」。**

- 用户要求 24 位：**真实达到 24/24**，第 2 页真实采集并入库，前端展示 24 位；不再出现
  「执行失败」，也不再重入第 20 位已计数达人。
- 跨页采集、去重、续采、DB/API/前端一致性均已真实验证。
- 该结论不等于「资料 100% 完整」：`profile_complete_count=6/24`、`featured_complete_count=0/24`
  是既有 F05/F06 完整度口径；原任务在修复前就是 5/20、0/20。任务因此保持 `PARTIAL_COMPLETED`，
  并提供「补采缺失字段（18 位）」，这是正确的业务状态，不是本次执行失败。

### 4.2 交付状态

- 代码修复、测试、真实续采、任务卡与索引/总览/架构/DEC-019/RETRY-01 交叉引用已完成。
- 初版交付未提交/推送（当时未获提交授权）；2026-10-26 用户授权后提交 `609c8db`、
  经 merge `bb29801` 合入 `main` 并推送。改动文件：
  `backend/src/xingtu/adapter.py`、`backend/src/xingtu/retry_policy.py`、
  `backend/tests/unit/test_retry_policy.py`、`backend/tests/contract/test_browser_flow.py`、
  `backend/tests/integration/test_engine.py`、`scripts/qa/diag03_e2e.py`，以及本报告与文档。
- 无 Schema、迁移、契约、前端、Workflow、执行单元配置改动。

### 4.3 未完成 / 残余（不阻塞本次交付）

1. **第 20 位 `fans` 标签的 DOM 级原因未再单独取证**：真实页面两次均在该动作 90s 超时；本轮
   修复将其限定为模块不完整，不再阻塞数量和后续分页。该达人仍会缺 `fans`（以及未尝试的
   `creation`）模块，后续「补采缺失字段」可能再次得到模块不完整结果，但不会让任务执行失败。
2. **模块动作超时的真实首跑未重放**：原任务续采按规则跳过已计数第 20 位，因此没有再次触发
   同一超时；该路径由 Contract 测试 + Integration 测试覆盖，未作虚假声称。
3. **全新首跑 24 位未重复执行**：为避免重复高成本真实采集，首次跨页由新增集成用例与既有
   QA-01 PG-03 真实证据覆盖；原任务续采已真实请求第 2 页。
4. **完整度 / 封面**：`profile_complete_count=6`、`featured_complete_count=0`、`failed_count=0`；
   4 位新达人的 `basic`/`fans`/`creation` 模块均完整，但精选集合仍为
   `INCOMPLETE/FAILED/EMPTY`（本任务 46 行：35 INCOMPLETE / 9 EMPTY / 2 FAILED），故精选完整
   仍为 0；属既有 F3/F06/封面缺口，非本轮范围。
5. `completed_at` 仍为首次失败时间 `21:30:50`，而状态在 22:17:25 变为 `PARTIAL_COMPLETED`；
   页面「首次完成时间」按既有语义显示首次终态时间，未在本轮修改。
6. 初版未提交/推送；2026-10-26 已获授权并提交/合并（`609c8db` → merge `bb29801` → `main`）。
   提交前复跑：unit 327、contract 40、integration 108+1 skip、e2e 9、frontend 89+build、
   mypy 36 files、ruff 改动文件通过（契约/E2E 需 `PLAYWRIGHT_BROWSERS_PATH=.runtime/browsers`）。
