# UPD-06 测试用例与结果

- 日期：2026-11-06
- 范围：四组定时更新、独立开关、同达人双场景、重复调度/失败、重启、管理页、现有采集/手动更新回归。
- 环境：macOS 本机原生 PostgreSQL/Redis/Temporal；开发库 `xingtu_development`（schema 22，主站 scheduler 关闭）；真实浏览器验收使用克隆库 `xingtu_test_upd06` + 现有已登录 Chrome Profile + 两平台专属执行单元。未在 Windows 实机执行。

## 1. 自动化测试

| 层级 | 命令 | 结果 |
|---|---|---|
| 单元 | `pytest backend/tests/unit -q` | **449 passed** |
| 集成 | `XINGTU_TEST_DATABASE_URL=…/xingtu_test pytest backend/tests/integration -q` | **149 passed, 1 skipped**（221.59s） |
| 契约 | `pytest backend/tests/contract -q` | **43 passed** |
| 前端 | `npm --prefix frontend test -- --run` | **127 passed**（12 files） |
| 构建 | `npm --prefix frontend run build` | 通过（Vite build；仅既有 >500kB chunk 警告） |
| 类型 | `mypy backend/src` | 通过（46 files） |
| 格式/静态（本次改动文件） | `ruff check backend/src backend/tests scripts/backfill_video_homepage.py scripts/acceptance/upd06_*.py`；`ruff format --check` 同上 | 通过（119 files already formatted） |
| 仓库级 `ruff check … scripts` | 全量 | 仍有 **11 个既有 UP031** + 3 个既有未格式化文件，均位于未改动的 `scripts/acceptance/run_cd05/06/07_acceptance.py`；本次未修改这些文件，记录为既有问题 |

新增/扩展的关键测试：
- `backend/tests/integration/test_creator_update_scopes.py`（12）：四组 target/契约、开关、组间隔离、双场景、reconcile、`UPDATE_SERVICE_DISABLED`、无定位、heartbeat、管理读模型。
- `backend/tests/integration/test_migrations_022.py`：旧计划行保留、复合主键、四组默认值、幂等。
- `backend/tests/integration/test_creator_update_backfill.py`：checkpoint 解析、幂等、不覆盖。
- `backend/tests/unit/test_worker_update_gate.py`：关闭组 scheduled 任务在浏览器前取消，手动/采集不受影响。
- `backend/tests/unit/test_juxing_adapter_v2.py`：无 plan 更新建立受绑定 video-square 页。
- `backend/tests/unit/test_update_scopes.py`：专用聚星 unit 的 binding live 契约解析。
- `backend/tests/unit/test_product_api.py`：GET/PUT 认证、CSRF、四组、非法场景。
- `frontend/src/updateServices.test.tsx`（4）：四行、开关 PUT、离线/生效、最近任务、错误态。

## 2. 真实隔离验收用例

环境准备：克隆 `xingtu_development` → `xingtu_test_upd06`；应用迁移 022；回填聚星短视频定位 81/81；`enroll_group` 纳入四组计划；除每组选定达人外，其余计划统一停到 30 天后；只让四个选定达人到期；隔离 API/前端/两平台 Worker/一个 scheduler（`--batch-size 1 --tick-seconds 5`）启动；主站 Worker 停止避免同一 Chrome Profile 冲突。

| ID | 用例 | 结果 |
|---|---|---|
| A1 | 星图短视频：真实届期 → scheduler 建 task → 星图单元 → 新快照/current/index → next_due | **PASS** |
| A2 | 星图直播：同上，使用直播契约 6 模块 | **PASS** |
| A3 | 聚星短视频：同上，使用聚星短视频契约 4 模块；首次暴露 `JUXING_SEARCH_PAGE_MISSING`，最小修复后同 root 重试完成 | **PASS（含最小修复）** |
| A4 | 聚星直播：同上，使用 LIVE-02G 8 模块契约 | **PASS** |
| B1 | 关闭星图短视频；星图短视频到期但不建任务；星图直播仍建 task 并完成 | **PASS** |
| B2 | 关闭聚星直播；聚星直播到期但不建任务；星图直播仍建 task 并完成 | **PASS** |
| B3 | 星图短视频关闭时手动更新仍可创建并完成（manual_update） | **PASS** |
| B4 | 星图短视频关闭时普通采集仍可创建并完成 1/1（collection） | **PASS** |
| B5 | 重新开启星图短视频后，到期达人恢复建 task 并完成 | **PASS** |
| B6 | 关闭时尚未开始的 queued 批次：停 Worker → 建 task → 关闭组 → 启 Worker → task `CANCELLED/UPDATE_SERVICE_DISABLED`，无新快照、计划只释放、不记失败 | **PASS** |
| B7 | 重启 API + scheduler：开关持久化（1 开 3 关 / 具体状态）；scheduled task 数 34→34，无重复 | **PASS** |
| C1 | 同达人双场景：真实准备 1 位（星图 star_id `7480355375695265829`，视频 2 快照 + 直播 1 快照），两条计划独立 | **PASS** |
| C2 | 只让直播到期：仅建直播 task；视频计划 last_success/next_due/快照数不变 | **PASS** |
| C3 | 只让短视频到期：仅建视频 task；直播计划 last_success/next_due/快照数不变 | **PASS** |
| C4 | 关闭一个场景不影响另一个场景 | **PASS**（B1/B2 + C2/C3 组合） |
| D1 | 重复 tick/单活跃批次：同组不重复建 task | **PASS** |
| D2 | scheduler 重启不重复建 task | **PASS**（34→34） |
| D3 | 运行中 task 取消：`CANCELLED`，计划 `consecutive_failures=1`、`next_due` +1h；快照数/投影哈希不变 | **PASS** |
| D4 | 执行单元分配/租约：星图 task → `unit-local-mac-02`，聚星 task → `unit-local-mac-03-juxing`；终态后 owner 释放 | **PASS** |
| E | 证据来自真实 scheduler：scheduler 日志、task `created_by=NULL`、`audit_logs.actor='scheduler'`、DB 计划 in-flight；非单达人接口直调 | **PASS** |
| F1 | 星图短视频普通采集小样本 1/1 | **PASS** |
| F2 | 聚星短视频普通采集小样本 1/1（2 次） | **PASS** |
| F3 | 星图直播普通采集小样本 1/1 | **PASS** |
| F4 | 聚星直播普通采集小样本 1/1 | **PASS** |
| F5 | 手动更新小样本（星图短视频） | **PASS** |
| F6 | 既有 70 位能力 | **NOT_RUN（引用 LIVE-02H / LIVE-03-70）**，本轮不重跑 |

## 3. 管理页 UI 用例

| ID | 用例 | 结果 |
|---|---|---|
| UI1 | 真实登录 → `/settings` 显示 4 行、调度器在线/离线、四组开关与统计 | **PASS** |
| UI2 | 通过浏览器开关聚星直播（PUT），页面状态与认证 API 读回均为 enabled=true；再次点击恢复 | **PASS** |
| UI3 | 任务中心打开真实定时批次 `c8a2f16a…`，显示「定时更新 · 1 位达人」、平台/场景、已完成、来源「定时调度」 | **PASS** |
| UI4 | 主站恢复后 `/settings` 只读检查：调度器未运行、1/4 开启、0 生效、148 到期；无虚构状态 | **PASS** |

截图见 `assets/UPD-06/`（`ui-services.png`、`ui-juxing-live-enabled.png`、`ui-juxing-live-restored.png`、`ui-scheduled-task-detail.png`、`main-ui-services-scheduler-off.png`）。

## 4. 未执行/受限

- 真实平台故障注入（登出、契约失效、平台错误页）：未主动制造；使用受控取消 + 集成失败/退避测试覆盖。
- Windows 实机登录/部署：不在本轮范围（DEPLOY-WIN-01）。
- 四组 70 位全量重跑：不重跑，引用 LIVE-02H / LIVE-03-70。
- 主站 scheduler 持续运行：按初始状态保留关闭，待运营决定。
