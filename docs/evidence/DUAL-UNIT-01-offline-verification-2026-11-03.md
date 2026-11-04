# DUAL-UNIT-01 离线实施与回归证据

日期：2026-11-03（Asia/Shanghai）  
分支：`快手_1026`，基线 HEAD `c7d12cd`（本轮未提交）  
环境：macOS 本机；PostgreSQL 18.3 `127.0.0.1:55432/xingtu_development`（schema 20）；测试库 `xingtu_test`；Temporal dev server `127.0.0.1:57233`；Redis `56379`；E2E 专用 Redis `6379`。未启动 API / Intake / Collection / 前端，未执行真实采集。

## 1. 本轮实现范围

- `runtime.py`：`UnitConfig.enabled_platforms` / `is_multi_platform`；平台专属配置不再借用旧星图顶层身份。
- `browser_host.py`：`release_disposition_for` 按“另一平台 binding 是否启用”判断共享/专属单元；单平台聚星使用真实释放状态。
- `repository.py`：
  - `select_collection_unit(platform)`：collection 能力 + enabled binding，优先非隔离；
  - `register_unit(..., register_xingtu_binding=False)`：平台专属单元不隐式创建星图 binding；
  - `_save` 同步写 `root_tasks.unit_id`；
  - `Repository.command` retry/continue 重解析平台专属单元。
- `intake_worker.py`：P1 晋级按 `plan.platform` 解析专属单元。
- `product_cli.py`：Intake 加载已声明但 `enabled=false` 的平台 registry；损坏时仅告警跳过。
- `product_queries.py`：API 侧 retry/continue 重解析并写回 `root_tasks.unit_id`。
- `cli.py`：`register-unit` 按 `active_platform` 跳过隐式星图 binding。
- `scripts/dev.sh`：双单元配置、双 Collection Worker、双队列 status/stop/logs/就绪检查、`SKIP_UPDATE_SCHEDULER`。
- `scripts/m3_up.py`：默认主站星图配置；`--extra-unit-config`；额外单元预检/启动/就绪；Collection Worker 退出不终止另一单元。

## 2. 测试结果

| 层级 | 命令 | 结果 |
|---|---|---|
| 后端单元 | `.venv/bin/pytest backend/tests/unit -q` | **375 passed** |
| 后端合同 | `.venv/bin/pytest backend/tests/contract -q` | **43 passed** |
| 隔离 PostgreSQL 集成 | `XINGTU_TEST_DATABASE_URL=...xingtu_test .venv/bin/pytest backend/tests/integration -q` | **122 passed / 4 skipped** |
| E2E | `XINGTU_TEMPORAL_TEST_BINARY=.runtime/local-main/bin/temporal .venv/bin/pytest tests/e2e -q` | **14 passed** |
| 前端 lint（tsc） | `npm --prefix frontend run lint` | 通过 |
| 前端单测 | `npm --prefix frontend test -- --run` | **106 passed** |
| 前端构建 | `npm --prefix frontend run build` | 通过 |
| 类型检查 | `.venv/bin/mypy backend/src` | **Success: no issues found in 38 source files** |
| 改动文件 Ruff | 对 13 个改动 Python 文件执行 `ruff check` / `ruff format --check` | 全部通过 |
| 空白检查 | `git diff --check` | 通过 |

已知既有问题（非本轮引入、未改动）：`scripts/acceptance/` 仍有 11 个 UP031 与 4 个未格式化文件；`make lint` / `make format-check` 会在这些历史文件上失败。

## 3. 只读预检（开发库，切换前）

- `execution_units` 仅 `unit-local-mac-02`：`READY`、`owner=NULL`、`lease_until=NULL`、`browser_stopped=true`、`generation=164`、`allowed_task_kinds=[collection,manual_update,scheduled_update]`。
- `execution_unit_platform_bindings`：
  - 星图：`account_ref=xingtu-account-02`、`expected_account_id=ID: 1807978499337419`、enabled=true、`last_observed_status=VALID`；
  - 聚星：`account_ref=juxing-account-02`、`expected_account_id=60821564`、enabled=true、`last_observed_status=VALID`；字段与 `.runtime/units/local-dev-mac-02.json` 的聚星 binding 一致。
- `root_tasks`：无非终态任务；无 owner/lease；无 takeover/verification event；聚星历史任务 3 条，均终态。
- 迁移版本 20；未注册 `unit-local-mac-03-juxing`；未复制 Profile；未修改旧单元配置。

> 注意：旧星图 binding 的 `profile_ref` 仍是历史仓库绝对路径（`/Users/yaoyao/Documents/...`），与 `.runtime/units/local-dev-mac-02.json` 的当前路径不同。这是 JUXING-MAIN-01 已记录的既有展示值；运行时以 Worker `--config` 为准，本轮不改不可变字段。

## 4. 限制与下一步

- 尚未执行真实切换：未复制聚星 Profile、未注册新单元、未修改旧单元 binding、未启动应用 Worker、未提交真实采集任务。
- 尚未验证两平台真实并行/串行、故障隔离、历史任务 retry/continue 的真实现象；这些在 Gate B 执行。
- Playwright MCP 当前会话工具目录未暴露；Gate B 前需确认可用，或取得替代方案授权。
- 需要用户确认停机窗口、两平台会话/人工登录可用性；若复制后会话失效，需本机人工登录/选择子账号。
