# JUXING-MAIN-01：5173 主站双平台整合方案（已执行完成，GO）

状态：**已执行完成（GO）**。P1–P6 全部完成，验收证据见 [JUXING-MAIN-01 验收](../evidence/JUXING-MAIN-01-acceptance.md)。  
建立时间：2026-10-31（Asia/Shanghai）  
关联：[JUXING-MAIN-01 任务卡](../tasks/JUXING-MAIN-01.md)、[KJX-01](../tasks/KJX-01.md)、[OPS-04](../tasks/OPS-04.md)、[OPS-05](../tasks/OPS-05.md)。  
最终目标：`http://localhost:5173` 同时支持巨量星图与磁力聚星，共享任务中心、业务数据库、达人库与同一个 `unit-local-mac-02` 执行单元，同时保留两平台独立账号、Chrome Profile 和已验证采集能力。

## 1. 审计结论（2026-10-31 实测）

1. **5173 与 4193 是同一份代码**：两侧运行同一 checkout 的 `.venv/bin/xingtu-api`、`.venv/bin/xingtu-product intake-worker`、`.venv/bin/xingtu worker` 与同一 `frontend/` 源码；差异只在环境变量、数据库、Temporal/Redis 端口和执行单元配置。
2. **迁移 020 已在主库执行**（OPS-04，2026-10-31 00:44）：`xingtu_development.schema_migrations` 20 条，最大 20；`root_tasks.platform`、`execution_unit_platform_bindings`、`requirements` v1/v2/v3 约束存在。交接文档中“迁移 020 未进业务库”的表述已过期。
3. **主站缺少的是配置与绑定，不是功能**：主站 `.runtime/m3-app.env` 无聚星 Flag/registry/上限；主站单元配置只有星图绑定；主库 `unit-local-mac-02` 只有 `douyin_xingtu` 一行平台绑定；主站聚星 Profile/快照存在但需要切换后只读会话核对。
4. **唯一确认的产品代码缺口**是任务中心平台筛选：`/api/tasks` 无 `platform` 参数，前端任务中心无平台下拉。达人库平台切换、任务/达人平台徽标、聚星详情、任务详情平台化、聚星读模型均已在当前代码中实现。
5. **无需新迁移、无需导入 4193 数据、无需重开采集器、无需第二套任务中心/执行单元池**。
6. **30 不是已验证的产品上限**。长期产品上限 200（与星图一致），本轮主站配置 30；已验证到第 2 页与真实 22/22/22，30/200 均不得写成“已完整验收”。

### 1.1 运行状态基线

| 栈 | 组件 | 状态 |
|---|---|---|
| 5173 主站 | API 8000 / Vite 5173 / intake `xingtu-intake` / collection `xingtu-unit-local-mac-02` | 运行中；`update-scheduler` 未运行 |
| 主站依赖 | PostgreSQL 55432 `xingtu_development`、Temporal 57233、Redis 56379 DB0 | 运行中 |
| 4193 隔离站 | API 4192 / Vite 4193 / Temporal 57235 / 单元 `unit-local-mac-02-kjx-full` | 运行中；测试库 55439 |
| 浏览器 | 系统 Chrome 156.0.8078.76；Playwright MCP 0.0.77 | 可用 |

### 1.2 主库基线（只读）

| 项 | 实测 |
|---|---|
| `schema_migrations` | 20 |
| `root_tasks` | 117，全部 `douyin_xingtu`；CANCELLED 23 / COMPLETED 19 / FAILED 11 / FAILED_VALIDATION 1 / PARTIAL_COMPLETED 63；非终态 0 |
| 星图达人 | `platform_creators` 138；`douyin_xingtu_creator_current` 138 |
| 快照/关联 | `task_creators` 293、`creator_snapshots` 355、`task_dispatches` 129、`intake_dispatches` 80 |
| 更新资格 | `creator_update_schedule` 90（调度器未运行） |
| 执行单元 | `unit-local-mac-02` READY；owner/lease/current_task 空；browser_stopped=true；无 open verification/takeover |
| 平台绑定 | 仅 `(unit-local-mac-02, douyin_xingtu)`；无聚星行 |
| 聚星数据 | 0 条 |

### 1.3 4193 测试库基线（只读，数量修正）

| 项 | 实测 |
|---|---|
| `root_tasks` | **8 条**：聚星 5（COMPLETED 3 / PARTIAL_COMPLETED 2）、星图 3（COMPLETED 2 / PARTIAL_COMPLETED 1） |
| 聚星达人 | **39 位** |
| 星图达人 | 3 位 |
| 单元 | `unit-local-mac-02-kjx-full`，双平台绑定，最近聚星观测 VALID |

> 修正：OPS-05 当时的“6 条任务（4 聚星 / 2 星图）”是当时快照，之后新增任务；本次实测为 8 条。方案初稿把总数写成 6、明细合计 8，属于笔误，已以本表为准。4193 数据不导入主库。

### 1.4 测试基线

| 层 | 结果 |
|---|---|
| 后端单元 + 合同 | **409 passed**（本轮实测，含 5 条新增） |
| 隔离 PostgreSQL 集成 | 全新空库 `xingtu_test_juxing_main`：**121 passed / 1 skipped**；共享测试库发现 1 个测试隔离缺陷（见 1.5） |
| 前端 | **105 passed** + lint + build（本轮实测） |
| E2E | **14 passed**（30.73s） |
| Mypy | backend/src 38 files，无问题 |
| 全仓 `make check` | 仍受既有 `scripts/acceptance` 11 个 UP031 与 `scripts/qa` 既有 E501/F841 阻断（与本轮无关）；本轮改动文件定向检查通过 |

### 1.5 独立记录的测试缺陷（不是产品缺陷）

`backend/tests/integration/test_migrations_020.py` 的第 78–84 行用：

```sql
SELECT count(*) FROM information_schema.columns
WHERE table_name='root_tasks' AND column_name='platform'
```

查询列是否存在，但 **未限定 `table_schema`**。当测试数据库的 public schema 已有迁移后的表（例如 4193 使用的 `xingtu_test_kjx_regression`），即使测试自己建的随机 schema 还是 v19，`information_schema` 也会返回 public schema 的列，导致 `assert 1 == 0` 失败。它在全新空库（KJX 的 `xingtu_test_kjx_full`、本轮的 `xingtu_test_juxing_main`）通过，说明失败是测试隔离问题，不是迁移或产品缺陷。

本轮处理：**不修改该测试**，改用全新空测试库运行集成套件；在任务卡与验收证据中独立记录，后续应给它补 `table_schema = current_schema()` 限定。不得用“换了库就通过”掩盖该缺陷。

## 2. 最小改动清单

| # | 项 | 改动 | 状态 |
|---|---|---|---|
| 1 | `backend/src/xingtu/product_queries.py` | `list_tasks(platform=...)`；SQL `r.platform=%s`；cursor scope 纳入 platform | 已完成 |
| 2 | `backend/src/xingtu/product_api.py` | `GET /api/tasks` 增加 `platform` 查询参数（非法值 422） | 已完成 |
| 3 | `frontend/src/pages.tsx` | 任务中心「全部平台 / 巨量星图 / 磁力聚星」下拉；变更重置 cursor | 已完成 |
| 4 | 测试 | API 单测、集成筛选/游标测试、前端组件测试、切换工具单测/集成测试 | 已完成 |
| 5 | `scripts/juxing_main_switch.py` | 只读 baseline / preflight / compare / session-check | 已完成 |
| 6 | 主站 `.runtime/m3-app.env` | 3 个聚星键（候选文件已准备，**未应用**） | 待授权门 B |
| 7 | 主站单元配置 | 增加聚星 `platform_bindings`（候选文件已准备，**未应用**） | 待授权门 B |
| 8 | 主库 `execution_unit_platform_bindings` | worker 启动时幂等注册聚星行 | 待授权门 B |
| 9 | 重启主站 4 进程 | 读取新配置；`update-scheduler` 保持关闭 | 待授权门 B |
| 10 | 真实样本 | 1 位聚星 + 1 位星图（已授权，P5 执行） | 待授权门 B |
| 11 | 4193 | P4 停止整栈，保留数据/配置/证据 | 待授权门 B |
| 12 | 数据库迁移 | **不需要** | — |

明确不改：星图 Adapter/合同/F04/F05/F06/完成判定/更新语义；聚星 Adapter/合同/分页/筛选/字段采集；任务中心结构；执行单元池模型；`scripts/dev.sh` 既有逻辑。

## 3. 目标架构

```text
ExecutionUnit: unit-local-mac-02（唯一逻辑单元，并发=1）
├── 共享：本机出口 / Chrome 运行环境 / 队列 xingtu-unit-local-mac-02 / 租约
├── 巨量星图（顶层绑定，不变）
│   ├── 账号 ID: 1807978499337419
│   ├── Profile .runtime/profiles/unit-local-mac-02
│   └── contracts/douyin_xingtu.verified.json
└── 磁力聚星（新增 platform_bindings 一项）
    ├── 子账号 60821564
    ├── Profile .runtime/profiles/unit-local-mac-02-juxing
    ├── 快照 .runtime/storage-state/unit-local-mac-02.kuaishou_juxing.json
    └── contracts/kuaishou_juxing.verified.json
```

候选单元配置（已生成、未应用）：`.runtime/juxing-main/local-dev-mac-02.candidate.json`（0600）。  
预检已确认：候选只增加 `platform_bindings`，星图字段逐项一致；聚星 Profile 独立、目录存在且 0700、两把 Profile 锁均 FREE；快照存在、0600、`unit_id=unit-local-mac-02`；registry live verified（`juxing-video-creator-stage-c-v3`）；主库无 (unit, juxing) / (juxing, account_ref) / profile_ref 冲突。

## 4. 数据库与历史数据保护

- 不执行新迁移；主库已是 20。
- 不导入 4193 数据；主库聚星数据只来自 P5 的 1 位真实样本。
- 切换前新备份：
  - `.runtime/backups/juxing-main-20261031T021309/xingtu_development-pre-juxing-main.dump`（35,539,606 bytes，Custom/gzip，TOC 231，sha256 `055a98ba…6d521`）；
  - `m3-app.env.pre-switch`、`local-dev-mac-02.json.pre-switch`（0600）；
  - `juxing-profile-and-snapshot.tar.gz`（0600，172,661,570 bytes）。
- 恢复演练：在测试集群 55439 建临时库 `xingtu_test_restorecheck_20261031T021321`，`pg_restore --no-owner --no-privileges` 成功；用 baseline 的同口径 count+md5 对比**全部一致**；随后删除临时库。
  - 演练中发现并修正了工具自身的问题：`row::text` 会按会话时区渲染 timestamptz，主库默认 Asia/Shanghai、测试库默认 UTC，导致同数据 md5 不同。工具已在 `_connect` 固定 `SET TIME ZONE 'UTC'`，baseline 已重采并复验通过。
- 内容一致性口径：`scripts/juxing_main_switch.py baseline/compare` 对 117 个星图根任务、138 位星图达人及其关联表做 count + `md5(string_agg(md5(row::text)))`，覆盖 `root_tasks`、`platform_creators`、`task_creators`、`creator_snapshots`、`douyin_xingtu_creator_*`、`requirements`、`filter_plans`、`task_checkpoints`、`task_dispatches`、`featured_collections/cards`、`raw_evidence`、`media_objects`、`creator_update_schedule`，并核对单元与星图绑定的不可变字段。compare 使用 baseline 时的 ID 列表，新增任务不会污染历史哈希。
- 说明：主库 `execution_units` 与星图 binding 的 `profile_ref` 仍是旧仓库绝对路径（`/Users/yaoyao/Documents/...`），而运行配置使用当前 checkout 路径；这是历史遗留的展示字段，运行时以单元配置为准。本轮不修改该不可变字段，已记录为剩余风险。

## 5. Feature Flag 与上限

| 项 | 决定 |
|---|---|
| 长期产品上限 | 200 位/任务（与星图一致）；本轮不宣称已具备 200 位真实能力 |
| 本轮主站配置 | `XINGTU_KUAISHOU_JUXING_MAX_TARGET_COUNT=30` |
| 已验证能力 | 第 1–2 页；真实 22/22/22；阶段 C 10 位；30/200 未验收 |
| 分页边界 | 第 3 页起 fail closed；候选不足如实 `SEARCH_EXHAUSTED` / `SEARCH_CAPABILITY_LIMIT` |
| 启用方式 | 环境变量 + verified 合同 + 可执行 Adapter；不改代码安全限制 |
| 回退 | Flag=0 关闭新入口；星图不受影响；Flag 不是 worker kill switch，不会停止已入队/执行中的聚星任务 |

候选环境增量（已生成、未应用）：`.runtime/juxing-main/juxing-main.env.additions`（0600），仅 3 个键。预检确认生效值：Flag=1、registry 绝对路径存在、max=30。

## 6. 已执行的 P1–P3

| 阶段 | 内容 | 结果 |
|---|---|---|
| P1 | 平台筛选代码 + 测试 | 完成；后端单元+合同 409 passed；前端 105 passed + lint + build；Mypy 通过 |
| P2 | 全新空测试库 `xingtu_test_juxing_main`；集成/E2E | 集成 **121 passed / 1 skipped**；E2E **14 passed**；共享库测试缺陷独立记录（1.5） |
| P3 | 主站只读预检、基线、备份、恢复演练 | 预检 48 项 0 失败；baseline/compare 通过；备份与恢复演练通过 |
| P3 | 候选取证文件 | 候选配置、env 增量、baseline、preflight、compare 报告均在 `.runtime/juxing-main/`（0600/0700） |
| 未执行 | 主库绑定写入、主站 Flag、主站重启、4193 停止、真实采集、会话探测 | 等待授权门 B |

## 7. P4–P6 执行结果（已完成）

1. **P4 主站切换（已完成）**：停 4193 整栈 → 停主站 4 进程（确认无在途）→ 应用候选 env/单元配置 → 等待 >45s 心跳窗口 → 启动 → 验证聚星 binding 已注册、`/api/platforms` 双平台、队列消费者；generation 13。
2. **P5 真实验收（已完成）**：
   - 聚星会话只读探测（`scripts/juxing_main_switch.py session-check`）；失效时先备份再复制 4193 已验证快照，仍失败则请用户人工登录；不自动选子账号。
   - 从 5173 UI 发起 1 位真实聚星（母婴/母婴亲子/target=1）与 1 位真实星图（宠物/target=1），验证同单元串行、任务中心/达人库/详情、DB 与历史哈希。
3. **P6 收口（已完成）**：全量自动回归（409/121+1/14/105）、MCP 20/20、历史完整性 compare（仅授权星图任务正常更新 1 位既有达人）、Flag=0 运行时验证、正常重启后双平台复现、验收证据与任务卡；**GO**。

## 8. 授权门 B 检查清单（已于 2026-10-31 02:21 批准并执行）

实际执行结果见 [切换前检查清单](../evidence/JUXING-MAIN-01-pre-switch-checklist.md) 与 [验收证据](../evidence/JUXING-MAIN-01-acceptance.md)。授权门 B 批准前保持的边界：

- 不修改主业务库绑定；
- 不开启主站聚星 Flag；
- 不重启主站；
- 不停止 4193；
- 不执行真实主站采集；
- 不执行真实平台会话探测。

## 9. 回退

| 场景 | 回退 |
|---|---|
| 关闭聚星入口 | Flag=0（或移除）→ 重启 API；星图不变；已入队/执行中的聚星任务不会被 Flag 停止 |
| 撤销单元聚星绑定 | 单元配置 `enabled=false`（或移除）→ 重启 collection；只允许改 enabled |
| 配置写错 | 用 `.pre-switch` 备份覆盖 → 重启 |
| 真实任务异常 | 保留任务/快照，按 `PARTIAL_COMPLETED` + `failure_reason` 如实记录；重试需单独授权 |
| 数据损坏 | 停写 → 用切换前 dump 恢复（需单独授权）；本轮聚星行可按 ID 精确删除（需授权） |
| 恢复 4193 | `./.runtime/kjx-full/stack.sh up`（数据/脚本保留） |

## 10. 风险

- 主站聚星快照为 2026-10-28 16:03 采集，P5 前需只读探测；失效则按第 7 节处理。
- 星图真实任务可能触发平台安全验证；按既有 15 分钟流程，不绕过；超时如实部分完成，重试需再次授权。
- 共享执行单元的真实排队重叠可能因任务耗时差未出现；若未出现，用隔离并发测试补充，不虚报。
- 4193 任务数口径已修正为 8；文档不得再引用 OPS-05 的 6 条快照作为当前值。
- `test_migrations_020.py` 的 schema 限定缺陷仍存在；本轮不修，独立记录。
- 主库星图 binding 的旧 `profile_ref` 为历史遗留展示字段，不影响运行，但审计时需说明。

## 11. 证据索引

- 任务卡：[JUXING-MAIN-01](../tasks/JUXING-MAIN-01.md)
- 切换前检查清单：[JUXING-MAIN-01 pre-switch checklist](../evidence/JUXING-MAIN-01-pre-switch-checklist.md)
- 测试用例：[JUXING-MAIN-01 测试用例](../evidence/JUXING-MAIN-01-test-cases.md)
- 预检报告：`.runtime/juxing-main/preflight-pre-switch.json`
- 基线：`.runtime/juxing-main/baseline.json`
- 空闲复核：`.runtime/juxing-main/compare-idle.json`
- 恢复演练对比：`.runtime/juxing-main/restore-compare.json`
- 备份目录：`.runtime/backups/juxing-main-20261031T021309/`
