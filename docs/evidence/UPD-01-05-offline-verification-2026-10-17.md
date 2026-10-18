# UPD-01—UPD-05 实施与离线验证证据

- 日期：2026-10-17
- 范围：达人手动更新、按粉丝档位的周期性更新、统一任务中心与统一执行单元池
- 环境：本机 macOS，开发库 `xingtu_development`（PostgreSQL，迁移 018），隔离测试库 `xingtu_test_upd`；未执行真实平台采集
- 结论：离线、隔离库、契约与前端检查通过；真实平台单达人更新与定时批次尚未执行，相关验收项保持未勾选

## 1. 实现范围

- 迁移 018：`root_tasks.task_kind`、`execution_units.allowed_task_kinds`、`creator_update_schedule`。
- 领域：`TaskKind`、`TaskRecord.plan` 可空、`update_targets`、目标数/能力版本属性。
- 执行：`Engine.run_update()`（不 prepare/search）、更新 Activity 让路、失败原因映射；`recheck_session` 回退 detail page。
- 执行单元池：正常采集能力守卫、`SKIP LOCKED` 未分配任务认领、优先级派发、配置变更回池、CLI `set-unit-task-kinds`。
- 手动更新：`POST/GET /api/creator-library/{id}/update(s)`、幂等与在途去重、最近成功/最近写入/下次到期。
- 周期更新：`CreatorUpdateService`（ensure/reconcile/claim/batch）、`update-scheduler` 进程、`make update-scheduler`、`dev.sh` 进程。
- 任务中心：`task_kind` 筛选、更新任务详情与每位达人状态、进度轨、前端按钮/标签。
- 文档：DEC-017、UPD-01—UPD-05、F09/F12、PRD、`docs/agent.md`、`docs/任务中心架构.md`、进度总览。

## 2. 数据库迁移

命令（开发库）：

```bash
set -a; . ./.runtime/m3-app.env; set +a
PYTHONPATH=backend/src .venv/bin/xingtu migrate --environment development
```

结果：`all pending migrations applied or already present`；只读核验：

- `schema_migrations.max(version)=18`
- `execution_units.unit-local-mac-02.allowed_task_kinds = [collection, manual_update, scheduled_update]`
- `root_tasks.task_kind` 列存在
- `creator_update_schedule` 初始 0 行（由调度器首次运行登记）

迁移仅新增列/表/索引；未重写既有快照、投影或历史任务。

`make m3-check`：`PREFLIGHT_OK`，其中 `MIGRATIONS_APPLIED applied=18 expected>=18`、`EXECUTION_UNIT_READY`、`REGISTRY_VERIFIED_LIVE` 均通过。

## 3. 自动化检查

### 后端单元

```bash
.venv/bin/pytest backend/tests/unit -q
```

结果：`303 passed`。

### 后端契约（需要项目 Chromium）

```bash
PLAYWRIGHT_BROWSERS_PATH="$PWD/.runtime/browsers" .venv/bin/pytest backend/tests/contract -q
```

结果：`33 passed`。

说明：首次全量运行时 `test_account_drift_probe::test_navigation_does_not_lose_click_and_evidence_stays_redacted` 一次失败；单独复跑通过，随后全量复跑 33 passed。保留该首跑失败记录，未通过修改断言掩盖。

### 后端集成（隔离测试库）

```bash
set -a; . ./.runtime/m3-app.env; set +a
export XINGTU_TEST_DATABASE_URL="$(python3 - <<'EOF'
import os
from psycopg.conninfo import make_conninfo
print(make_conninfo(os.environ['XINGTU_DATABASE_URL'], dbname='xingtu_test_upd'))
EOF
)"
.venv/bin/pytest backend/tests/integration -q
```

结果：`92 passed, 1 skipped in 254.50s`（最终代码复跑；此前一次 276.96s 同样 92 passed/1 skipped，用于确认重复性）。

覆盖：迁移 018、手动更新幂等/在途、任务类型筛选与 update targets、调度器建批/单活跃、正常采集可运行时跳过建批、池认领与配置回池、有效成功后重置周期、`Engine.run_update` 不搜索且不重复达人、既有任务/仓储/产品回归。

说明：`test_target_20_and_200` 在本地慢库上曾因 120 秒租约在长 `finish` 事务中被心跳阻塞而失败；该测试改为 1 小时测试租约并在心跳中同步延长，随后通过。此调整只影响测试夹具，不改变生产租约策略。

### 前端

```bash
npm --prefix frontend run lint
npm --prefix frontend test
npm --prefix frontend run build
```

结果：TypeScript 通过；`83 passed`；Vite build 通过。

### 静态检查

```bash
.venv/bin/ruff check <changed files>
.venv/bin/ruff format --check <changed files>
.venv/bin/mypy backend/src
```

结果：`All checks passed`；`Success: no issues found in 34 source files`。

## 4. 未执行/未验证

- 未执行真实平台单达人手动更新；未验证真实主页导航、身份校验、两组精选与封面在新任务类型下的端到端行为。
- 未执行真实定时批次；调度器仅在隔离库验证了建批/去重/退避/重置逻辑。
- 未执行真实执行单元认领/让路的浏览器级验收；未验证正常采集与更新并发时的真实页面级时序。
- 未启动/重启本地 API/Worker/调度器进程做 UI 验收；前端验证为组件/类型/构建层。
- `test_target_20_and_200` 的测试租约调整只解决本地慢库时序，不代表生产 200 位长任务已完成租约优化。

## 5. 下一步

- 经用户授权后执行：真实手动更新一位已入库达人 → 核对任务中心、新快照、投影、达人库 current/index、无重复达人、旧快照不变。
- 受控验证定时批次小样本（建议 1–2 位达人）与失败/部分更新路径。
- 按结果回写 UPD-03/UPD-04/UPD-05 验收项；未执行项保持未勾选。
