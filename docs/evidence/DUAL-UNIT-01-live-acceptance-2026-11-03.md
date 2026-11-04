# DUAL-UNIT-01：双平台专属执行单元真实切换与验收证据

日期：2026-11-03（Asia/Shanghai）  
环境：macOS 本机；PostgreSQL 18.3 `127.0.0.1:55432/xingtu_development`（schema 20）；Temporal `127.0.0.1:57233`；Redis `56379`；前端 `5173`；API `8000`。真实平台：巨量星图 + 磁力聚星。  
工具：Playwright MCP（项目 `scripts/qa/mcp_client.py` stdio 客户端 + 本机 Chrome）、只读 PostgreSQL、Temporal history。  
未提交 Git、未修改历史任务/快照、未删除旧执行单元。

## 1. 切换结果

| 项 | 巨量星图 | 磁力聚星 |
|---|---|---|
| 执行单元 | `unit-local-mac-02`（保留） | `unit-local-mac-03-juxing`（新增） |
| 单元配置 | `.runtime/units/local-dev-mac-02.json` | `.runtime/units/local-dev-mac-03-juxing.json` |
| 队列 | `xingtu-unit-local-mac-02` | `xingtu-unit-local-mac-03-juxing` |
| 账号 | `ID: 1807978499337419` | `60821564` |
| Profile | `.runtime/profiles/unit-local-mac-02` | `.runtime/profiles/unit-local-mac-03-juxing`（从旧聚星 Profile 复制） |
| 快照 | `.runtime/profiles/storage-state/unit-local-mac-02.json` | `.runtime/profiles/storage-state/unit-local-mac-03-juxing.kuaishou_juxing.json` |
| binding | 星图 enabled=true；聚星 enabled=false | 仅聚星 enabled=true；无星图 binding |
| 最终状态 | `READY`、无 owner/lease、browser_stopped=true | `READY`、无 owner/lease、browser_stopped=true |

- 备份：`.runtime/backups/dual-unit-20261103T203827/`（业务库 `pg_dump` 35 MB、旧单元配置、两平台快照；目录 0700，文件 0600）。
- 新单元注册后 `NEEDS_LOGIN`；首个真实聚星任务经有界维护自动提升为 `READY`（`session_version=1`）。
- 旧聚星 binding 由星图 Worker 启动时按配置 `enabled=false` 幂等禁用；未手写业务 SQL 修改 binding。
- 两个 Worker 各 1 个新鲜实例；三条队列（intake + 两 collection）均有新鲜消费者。最终 `execution_unit_workers` 新鲜数：星图 1（generation 17）、聚星 1（generation 3）。

## 2. 会话核验

| 单元 | 结果 | 证据 |
|---|---|---|
| 星图 `unit-local-mac-02` | `VALID`，观测账号 = 期望账号 `ID: 1807978499337419`，受保护页 true，快照在首个导航前恢复 | `session-diagnostics` 报告 `unit-local-mac-02-20261103T123019Z.json` |
| 聚星旧 Profile | 首次直接入口落在“选择账户”页；父账号已登录，`cpg果汁 ID:60821564` 可选 | `.runtime/juxing-main/diag-20261103/juxing-entry.png` |
| 聚星旧 Profile（维护窗口） | 使用既有 `juxing_login_maintenance.py` 以 `__accountId__=60821564` 进入，`VALID`、账号匹配、快照保存 | 状态文件 `VERIFIED_WINDOW_OPEN` / `STOPPED`，快照 `unit-local-mac-02.kuaishou_juxing.json` |
| 新单元复制后 | `VALID`，观测账号 = `60821564`，受保护页 true，`restored_before_navigation=true`，快照导出到新单元路径 | `unit-local-mac-03-juxing-20261103T123828Z.json` |

## 3. 真实任务与结果

所有任务均由 5173 真实 UI 通过 Playwright MCP + Chrome 提交，真实平台采集、真实 PostgreSQL 入库。

| root_task_id（短） | 平台 | 单元 | 状态 | 有效/发现 | 快照 | 说明 |
|---|---|---|---|---|---|---|
| `3eed5a7e` | 聚星 | 新 | `COMPLETED` | 1/1 | 1 | 新单元首个任务，自动提升 READY |
| `25182f11` | 星图 | 旧 | `COMPLETED` | 1/1 | 2 | 真实滑块、接管、人工完成、恢复后完成（见 §6） |
| `d91527d0` | 聚星 | 新 | `COMPLETED` | 1/1 | 1 | 与星图首个任务并行窗口内完成 |
| `c847f162` | 星图 | 旧 | `COMPLETED` | 1/1 | 1 | 干净并行对 A |
| `c68f54ff` | 聚星 | 新 | `COMPLETED` | 1/1 | 1 | 干净并行对 C |
| `817e0fcc` | 星图 | 旧 | `COMPLETED` | 1/1 | 1 | 双平台各两任务 A |
| `2165d3ff` | 星图 | 旧 | `COMPLETED` | 1/1 | 1 | 双平台各两任务 B（A 完成后立即开始） |
| `8d326bd4` | 聚星 | 新 | `COMPLETED` | 1/1 | 1 | 双平台各两任务 C |
| `aec4f5c1` | 聚星 | 新 | `COMPLETED` | 1/1 | 1 | 双平台各两任务 D（C 完成后立即开始） |
| `a74abc55` | 星图 | 旧 | `COMPLETED` | 1/1 | 1 | 聚星 Worker 离线/重启期间持续执行 |
| `4bd0916a` | 聚星 | 新 | `COMPLETED` | 1/1 | 1 | Worker 离线时 QUEUED，重启后执行 |
| `ae08c1b4` | 星图 | 旧 | `COMPLETED` | 1/1 | 1 | 星图 Worker 离线时 QUEUED，重启后执行 |
| `aaabfe2d` | 聚星 | 新 | `COMPLETED` | 1/1 | 1 | 星图 Worker 离线期间完成 |

- 每条新任务的 `creator_platforms` 只有本平台；无跨平台 creator 混写。
- `25182f11` 的 2 份快照是挑战中断/恢复后的追加观测（append-only），`task_creators` 仍为 1 条，非重复入库。
- 旧聚星历史任务 3 条（`b9517e8b`、`210b37c4`、`e5a8ca5b`）仍为 `unit-local-mac-02`，`updated_at` 保持在 2026-10-31，未被重写。

## 4. 跨平台并行证据（C-03）

干净并行对：

| 任务 | 平台 | 单元 | 活动区间（Asia/Shanghai） |
|---|---|---|---|
| `c847f162` | 星图 | `unit-local-mac-02` | 21:00:24.456 → 21:01:43.759 |
| `c68f54ff` | 聚星 | `unit-local-mac-03-juxing` | 21:00:30.500 → 21:01:36.489 |

- Temporal 真实 `collect_segment_v1` activity 区间**重叠 65.99 秒**。
- 1 秒采样器：**66 个采样点**两 unit 同时 `state=LEASED`、`mode=collect`、`current_root_task_id` 分别为上述两个不同 root；每个 unit 的 distinct current root 仅为自己任务 + null。
- 并行期间两 Profile `.lock` 同时 BUSY；`SingletonLock` PID 分别为 **38271 / 38358**（不同且存活）；`execution_units.browser_instance_id` 分别为 `0c7f3cdd…` / `bbb8e3fb…`。
- 证据：`.runtime/dual-unit-acceptance/pair-clean-20261103/report.json`、`samples.jsonl`；原始 `profile` 检查见会话记录。

## 5. 双平台各两任务：并行 + 平台内串行（C-04/C-05/C-06/C-08）

| 任务 | 平台 | 单元 | 活动区间（Asia/Shanghai） |
|---|---|---|---|
| A `817e0fcc` | 星图 | 旧 | 21:02:35.639 → 21:04:00.397 |
| B `2165d3ff` | 星图 | 旧 | 21:04:00.399 → 21:05:36.862 |
| C `8d326bd4` | 聚星 | 新 | 21:02:47.750 → 21:03:16.968 |
| D `aec4f5c1` | 聚星 | 新 | 21:03:16.972 → 21:04:29.299 |

- A 与 C 真实重叠 **29.22 秒**；另 A/D、B/D 亦有真实重叠窗口。
- 同平台严格串行：B 在 A 完成后 **0.002 秒**开始；D 在 C 完成后 **0.003 秒**开始；区间无重叠。
- 1 秒采样器按 unit 统计最大同时活动采集任务：星图 **1**、聚星 **1**。
- 4 条任务全部 `COMPLETED`，各 1/1，单快照，平台字段正确。
- 证据：`.runtime/dual-unit-acceptance/two-each-20261103/report.json`、`data-validation.json`、`samples.jsonl`。

## 6. 真实挑战、接管与恢复（F-07 / 异常隔离）

星图任务 `25182f11` 在首次采集中触发真实滑块（`SLIDER_OR_INTERACTIVE`）：

1. 20:52:52 产生 `PLATFORM_SECURITY_CHALLENGE` 事件（OPEN，15 分钟窗口），星图单元 `LEASED/maintenance`；聚星任务 `d91527d0` 继续真实采集，不受影响。
2. 通过 5173 执行单元页发起接管；`browser_takeover_sessions` 为 `ACTIVE`，用户在星图专属 Chrome 完成滑块并确认。
3. 20:55:08 `challenge declared clear`；接管 `RESUMED`、事件 `RESOLVED`；20:55:20 任务出现一次 `WAITING_FOR_RESOURCE: LEASE_LOST`，Temporal Workflow 在 20:55:57 自动重试，任务恢复 `COLLECTING`，20:57:15 `COMPLETED` 1/1。
4. **发现（既有问题，非本轮引入）**：`BrowserHost.maintain_and_promote` 提升新 `session_version` 后、活动循环重建 Engine 前，15 秒心跳协程可能用旧 Engine 的 `ctx.session_version` 调用 `repo.edit`，触发一次 `LEASE_LOST`；Workflow 的 30 秒重试可恢复，但会产生一次非必要 `WAITING_FOR_RESOURCE`。建议后续独立任务修复（心跳仅在 Engine 的 `ctx.session_version == host.session_version` 时调用 `guard`），本轮未擅自修改，避免扩大范围。

## 7. Worker 离线、重启与对称隔离（B-04/B-05/E-01/E-02/E-07）

| 场景 | 证据 | 结论 |
|---|---|---|
| 聚星 Worker 离线 | 聚星任务 `4bd0916a` 创建于 21:06:34，聚星 Worker gen1 于 21:07:19 被替换；该任务 `workflow_started_at=21:07:19`，activity 21:07:19—21:07:52 | 离线期间 QUEUED，未误派星图；重启后执行完成 |
| 同期星图任务 | `a74abc55` activity 21:06:31—21:09:54 | 聚星 Worker 离线/重启期间星图任务持续执行并完成 |
| 星图 Worker 离线 | 星图任务 `ae08c1b4` 创建于 21:12:05，星图 Worker gen17 于 21:13:31 启动；该任务 `workflow_started_at=21:13:31`，activity 21:13:31—21:15:11 | 离线期间 QUEUED，未误派聚星；重启后执行完成 |
| 同期聚星任务 | `aaabfe2d` activity 21:12:14—21:12:49 | 星图 Worker 离线期间聚星任务完成，未受影响 |

- 两次重启后两个 unit 均恢复 `READY`、无 owner/lease、`browser_stopped=true`；两 Worker 各 1 个新鲜实例。
- 未执行 Chrome 窗口强制关闭、会话失效、单任务取消、单 unit QUARANTINED 的破坏性演练；这些列为未执行项（见 §9），不以推断替代。

## 8. 全栈重启与持久性（F-10）

- 21:10:00 执行 `SKIP_UPDATE_SCHEDULER=1 ./dev.sh restart`，首次两个 Collection Worker 因上一代 Worker 心跳仍在 **45 秒去重窗口**内，以 `DUPLICATE_WORKER_FOR_UNIT` 退出；这是既有重启时序问题（OPS-03 已记录）。
- 21:10:49 再次 `./dev.sh up`，两 Worker 正常注册（星图 generation 16、聚星 generation 3），两 unit 均 `READY`，三条队列恢复新鲜消费者。
- 持久化结果：两 unit、两 binding（旧聚星 disabled、新聚星 enabled）、两 Profile/快照、两队列均保留；历史数据未重写。
- 当前最终运行态：星图 Worker generation 17（B-05 测试后重启）、聚星 Worker generation 3；两 unit `READY`、browser STOPPED。
- 部分重启限制：`dev.sh up` 会先做完整前置自检，主单元处于 `LEASED`（另一平台任务在跑）时 `EXECUTION_UNIT_READY` 会拒绝启动；本轮在 B-04/B-05 中用 CLI 单独启动缺失 Worker。后续可增加“只启停单个 Worker/允许 LEASED 的部分重启”入口，避免为了重启一个单元而等待另一个任务。

## 9. UI 证据（Playwright MCP + Chrome）

| 截图 | 说明 |
|---|---|
| [execution-units-two-dedicated.png](assets/dual-unit/execution-units-two-dedicated.png) | 执行单元页：两行、平台分别为巨量星图/磁力聚星、Worker ONLINE、浏览器 STOPPED、可用单元 2 |
| [task-center-after-dual-unit.png](assets/dual-unit/task-center-after-dual-unit.png) | 任务中心：双平台新任务与历史任务混排、平台/状态/计数正确 |
| [tasks-two-each-running.png](assets/dual-unit/tasks-two-each-running.png) | 双平台各两任务运行期间的列表截图（UI 15 秒轮询可能短暂显示上一任务状态，活动并发以 Temporal/采样器为准） |
| [xingtu-task-detail.png](assets/dual-unit/xingtu-task-detail.png) | 星图完成任务的详情/结果 |
| [juxing-task-detail.png](assets/dual-unit/juxing-task-detail.png) | 聚星完成任务的详情/结果 |
| [xingtu-library.png](assets/dual-unit/xingtu-library.png) | 星图达人库 |
| [juxing-library.png](assets/dual-unit/juxing-library.png) | 聚星达人库（8 位已加载，包含新采集） |

## 10. 判定汇总

**PASS（有真实证据）**

- A-01—A-12：两配置/两单元/两 binding/两 Worker/两队列/两会话/管理页/权限；旧单元身份保留。
- B-01—B-05、B-07：新任务按平台精确路由；无跨平台误派；两方向 Worker 离线均保持路由正确并恢复；错误 unit 的 takeover 不可用。
- C-01—C-09：单任务、跨平台真实重叠 65.99s、同平台串行（0.002/0.003s 衔接）、各两任务场景、每 unit 最大并发 1、两 Chrome/Profile 独立。
- D-01—D-06、D-09、D-10：续跑/谱系/状态/数据/页面/无重复 creator/无死锁/租约收尾。
- E-01/E-02/E-07：两方向 Worker 离线/重启隔离；真实挑战期间聚星任务不受影响。
- F-01/F-02/F-04/F-06/F-07/F-08/F-09/F-10：历史星图/聚星可读不重写；达人库/详情；定时更新保持关闭；真实挑战/接管；认证；自动回归；全栈重启（含既有 45 秒窗口说明）。

**未执行 / 部分（不作为 PASS）**

- B-06 手动/定时更新真实认领：未执行（自动测试覆盖 binding 认领）。
- B-08 真实幂等双击：未执行（既有自动测试覆盖）。
- C-10 精确资源 RSS/swap：未测量；两 Chrome 并行完成且无 OOM。
- D-07 普通失败/重试：未构造；真实挑战导致的 `LEASE_LOST` 与 Workflow 重试已记录。
- D-08 取消一个平台任务：未执行。
- E-03/E-04 Chrome 强制关闭：未执行（以真实滑块/接管作为平台级异常证据，但不替代 Chrome 关闭演练）。
- E-05/E-06 会话失效：未执行（真实挑战不等同于会话失效）。
- E-09 单 unit QUARANTINED：未执行。
- F-03 历史聚星任务真实 retry/continue：仅隔离集成测试通过；未对真实历史任务执行（避免无必要地追加历史数据）。
- F-05 手动更新真实回归：未执行。
- F-11 完整回滚演练：未执行；旧配置/DB/Profile 备份完整，可回滚。
- 星图历史 baseline 的逐项 count+md5 对比未重做；旧聚星 `unit_id`/`updated_at` 未变化已核对。

## 11. 结论与建议

**GO（核心目标达成）**：巨量星图与磁力聚星已运行在各自专属执行单元上；跨平台真实采集重叠 65.99 秒，同平台严格串行（衔接 0.002/0.003 秒）；平台内最大并发 1；无错误路由；两平台真实数据 13 条任务全部 `COMPLETED`、各 1/1、平台字段正确；历史数据未重写；两方向 Worker 离线/重启隔离与恢复通过；全栈重启后两单元/两队列/两 Worker 恢复。

**已知问题 / 后续**

1. 真实挑战恢复后的一次 `LEASE_LOST` 与 30 秒 Workflow 重试（既有问题，建议独立任务修复心跳的 `session_version` 栅栏）。
2. `dev.sh restart` 后 45 秒内会撞上上一代 Worker 心跳去重窗口，首次 `up` 可能启动失败；再等待后 `up` 成功。既有问题，建议后续给 `dev.sh`/`m3_up` 加“等待旧心跳过期/重试”逻辑。
3. 执行单元页对 `NEEDS_LOGIN/SESSION_UNVERIFIED` 仍显示原始枚举；本轮未改前端。
4. 未执行项见 §10；在完成 Chrome 关闭、取消、会话失效与回滚演练前，不应把对应测试项标为通过。

**证据位置**：`.runtime/dual-unit-acceptance/`（原始 sampler/report/screenshots，gitignored）；公开脱敏截图在 `docs/evidence/assets/dual-unit/`。
