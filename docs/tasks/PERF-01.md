# PERF-01：混合部署采集性能诊断与 Heartbeat / 终态最小修复

状态：待验收
更新时间：2026-10-21T00:45:00+08:00
是否验收：否；代码与隔离测试完成，**未部署、未做真实 `宠物/10` 复验**；结构性带宽/checkpoint 方案待用户确认。

## 目标与范围

回答并修复 2026-10-20 第二次真实 `宠物/10`（`b5a01709-8a4b-46bd-aa31-6494b0d9ce24`）暴露的问题：

1. 混合部署后采集速度明显下降的真实原因；
2. Temporal heartbeat timeout 与同步 PostgreSQL 阻塞；
3. 最后一次 attempt `not_found=True` 不落终态、root_task 永久 `COLLECTING`；
4. 失败时 checkpoint 已采集数据不发布。

包含：只读生产诊断、Git/历史基线对比、最小代码修复、单元/契约/隔离 PostgreSQL 集成测试、性能对比、部署与验收建议。

不做：部署/重启正式 Worker、创建真实任务、重试/取消历史任务、修改生产数据/Schema/账号/Cookie/Profile、改筛选或有效性口径、改 F10 恢复逻辑、改 Workflow 图或延长 timeout/retry、结构化 checkpoint/迁移、前端改动、Git commit/push/merge。

## 关联与依赖

- 前置：[P1FIX-02](P1FIX-02.md)（heartbeat/终态上一轮修复，真实 E2E FAIL）、[E2E-01](E2E-01.md)（真实采集验收，阻塞）、[DIAG-01](DIAG-01.md)（历史请求/性能基线）。
- 部署：[DEP-01](DEP-01.md)、[DEP-02](DEP-02.md)、[OPS-01](OPS-01.md)、[MAC-01](MAC-01.md)。
- 真实任务：`b5a01709-8a4b-46bd-aa31-6494b0d9ce24`、`11f9fc9c-ad06-4d41-9fde-c33bab168f47`（均为历史证据，本轮未修改；本轮开始时已是 `CANCELLED`）。

## 根因结论

### 已证实

- **采集热路径每模块至少 7 次完整 checkpoint 传输**：3 次 `Repository.get` + 4 次 `edit`（读改写）。checkpoint 文本 **521,870 B（510 KiB）**。
- **远程 `Repository.get()` 实测 7.7–8.3 s**；同字节传输 9.6–9.8 s；本地隔离库同 617 KiB checkpoint 仅 **14.5 ms**（约 530–570×）。
- **链路共享吞吐 46–89 KiB/s**（0.4–0.7 Mbps）；并发 1/4/8 不提升；Tailscale RTT 19 ms、TCP 建连 19.5 ms、psycopg 建连+SELECT 160 ms。普通公网同时间段 0.36–2.9 MB/s（波动）。
- **模块耗时被 DB 支配**：run2 `module_seconds` 合计 176.67 s（basic 28.89 s、creation 97.16 s、commercial 21.21 s），历史本地任务 `381d628b` 合计 9.74 s（basic 0.12 s、creation 4.56 s）。basic/commercial 的 200× 级差异不可能是浏览器操作。
- **Heartbeat timeout**：同步 psycopg 在 asyncio loop 上执行全量 `get/edit`，单次 8 s；同时占满链路使 lease 续租排队。15:26:21.656 `HEARTBEAT_TIMEOUT elapsed=11.4s`；15:29:51 Activity timed out；15:29:53 Workflow FAILED。
- **终态缺口**：部署版本 `should_finalize_cancelled()` 把 `not_found=True` 排除，attempt 4 未调用 `_finalize_interrupted`；Temporal 已 `MAXIMUM_ATTEMPTS_REACHED`，不是“仍有重试机会”。
- **未发布**：发布只在 `finish`/`finalize_interrupted`；取消后未进入，故第一位达人的 8 模块/2 精选未生成快照；34 个封面 1.30 MB 已入 MinIO 但无引用。
- **Covers 远程化成本**：每个封面 `put_object` + `head_object` + `get_object`（读回校验）+ 新连接写 `media_objects`；首个达人 30 个封面 68 s。

### 高置信度

- 云出口/Tailscale 路径存在约 0.6 Mbps 级共享上限；Mac WiFi 波动是叠加因素。未读取腾讯云带宽套餐（无 SSH），故不写成已证实。
- 若带宽不升级，单次完整 `edit` 仍会随 checkpoint 增长成为瓶颈；结构化 checkpoint 才能让 10 位目标在混合链路上接近本地耗时。

### 未证实/未改变

- 第二位达人筛选相关性；`valid=true` 与 `profile_complete=0` 的既有口径差异；F10 真实恢复（run2 未触发）；Profile/账号问题。
- 未修改筛选、有效性、完整度、F10、账号/Profile、历史数据。

## 代码修复

| 文件 | 内容 |
|---|---|
| `backend/src/xingtu/worker.py` | `TemporalHeartbeat` 独立 daemon 线程（10 s，`contextvars.copy_context`，60 s loop watchdog，启停有界）；`not_found` 最后 attempt 收口；`_finalize_interrupted` 三级回退 + error 日志；heartbeat reason/elapsed、event-loop lag 日志 |
| `backend/src/xingtu/repository.py` | `record_progress()` 服务端 JSONB 增量更新（lease/attempt/state/version fence，不传 checkpoint）；`candidate_module_complete()` / `candidate_valid()` 小查询；`heartbeat(lock_timeout_seconds=8)`；`XINGTU_DB_SLOW_MS` 慢操作日志；`get/edit/finalize_interrupted` 计时 |
| `backend/src/xingtu/engine.py` | `guard()` 用内存 active_seconds + `record_progress`；`charge()` 小增量；模块循环用小查询；`module_seconds` 小增量；模块/精选/封面耗时日志 |
| `backend/src/xingtu/browser_host.py` | `heartbeat_lease(lock_timeout_seconds=8)` |
| `backend/tests/unit/test_worker_heartbeat.py` | 线程心跳、阻塞 loop 仍心跳、watchdog、stop |
| `backend/tests/unit/test_worker_cancellation.py` | `not_found`/timeout/shutdown/cancel 分类；`_finalize_interrupted` 回退链 |
| `backend/tests/unit/test_engine_progress.py` | guard 不读 checkpoint、预算、计数器去重 |
| `backend/tests/integration/test_progress.py` | `record_progress` 持久化/幂等/三类 fence；小查询完整性 |
| `deploy/macos/worker.env.example`、`deploy/application.env.example` | `XINGTU_DB_SLOW_MS=1000` |
| `scripts/diag/hybrid_db_latency.py` | 只读 DB/链路探针 + TEMP TABLE 写基准 |

关键行为：

- 每模块完整传输 **≥7 → 1**；每模块 DB 时间推算 **~56–61 s → ~9–11 s**（实测单价 × 代码路径）。
- Temporal heartbeat 不再依赖 asyncio loop；事件循环永久卡死 60 s 后 watchdog 停止心跳，交回 Temporal 45 s 超时。
- 最后 attempt 的 `timed_out`/`not_found` 收口；`worker_shutdown`/`cancel_requested`/`paused`/`reset` 不收口；`attempt<4` 不提前收口。
- 收口优先 `engine.finish(force=True)`，发布已采集数据；发布失败退化为无发布终态；重复收口幂等；保留 generation/attempt fence。
- 用 run2 的真实 checkpoint 在隔离库重放 `finalize_interrupted`：root → PARTIAL_COMPLETED，`creator_snapshots=2`、`featured_collections=2`（COMPLETE）、`featured_cards=8`、`snapshot_collections=2`；重复调用计数不变。

## 验证证据

- 报告：[hybrid-performance-diagnosis-2026-10-21.md](../evidence/hybrid-performance-diagnosis-2026-10-21.md)
- 时序/历史对比：[01-timing-comparison.txt](../evidence/hybrid-performance-diagnosis-2026-10-21/01-timing-comparison.txt)
- 生产只读 DB 探针：[02-db-latency.json](../evidence/hybrid-performance-diagnosis-2026-10-21/02-db-latency.json)
- 本地隔离基线：[03-local-baseline.txt](../evidence/hybrid-performance-diagnosis-2026-10-21/03-local-baseline.txt)
- 链路带宽：[04-link-bandwidth.txt](../evidence/hybrid-performance-diagnosis-2026-10-21/04-link-bandwidth.txt)
- 测试：[05-tests.txt](../evidence/hybrid-performance-diagnosis-2026-10-21/05-tests.txt)
- 生产只读状态：[06-state-readonly.txt](../evidence/hybrid-performance-diagnosis-2026-10-21/06-state-readonly.txt)
- 真实 checkpoint 收口重放（隔离库）：[07-closeout-replay.txt](../evidence/hybrid-performance-diagnosis-2026-10-21/07-closeout-replay.txt)

测试结果（2026-10-21）：

- 后端单元 **346 passed**
- 后端契约 **33 passed**
- 隔离 PostgreSQL 集成 **101 passed, 4 skipped**
- mypy **Success 34 files**
- ruff check/format **通过（89 files）**
- 前端：未改，未复跑

未执行：真实 `宠物/10`（未授权）、真实 F10、部署后真实 `record_progress`、>60 s loop 卡死的真实验证、前端回归。

## 部署与回滚（待授权）

- 最小部署：备份当前 4 个 Python 文件 → 替换 → 可选加 `XINGTU_DB_SLOW_MS=1000` → 仅 `launchctl kickstart -k` Mac Worker；不重启云端、无迁移。
- 回滚：恢复 4 个文件并重启 Worker；无数据回滚；不删除任务/快照。
- 真实复验：只创建 1 个 `宠物/10`，检查终态一致、heartbeat 无 timeout、快照/精选发布、幂等、generation fence、模块/DB 耗时。
- 性能硬约束：若要在 10 位目标上接近本地耗时，需先确认云出口带宽升级（优先）或结构化 checkpoint（需单独授权）；不得靠延长 timeout/retry 或降低数据标准。


## 2026-10-21 性能专项验证后续（PERF-02）

- [PERF-02](PERF-02.md) 完成网络瓶颈与优化收益专项验证，报告：[perf-verification-2026-10-21.md](../evidence/perf-verification-2026-10-21.md)。
- **主瓶颈实测证实为云端→Mac 出口带宽/整形**：DB 下载 41–61 KiB/s vs 上传 1.5–6.3 MiB/s；MinIO GET 50–122 KiB/s vs PUT 0.7–7.3 MiB/s；并发下载不扩展、上传扩展；PostgreSQL 服务器执行 0.046 ms、无锁/临时文件；Tailscale 为 direct 非 relay。
- **优化收益（隔离 benchmark，0.5/1/2.5 MiB）**：完整传输 10→3、下行字节 −70%、单模块耗时 −66%–69%；8 模块模型 59→10（约 5.9×）；剩余 1 次完整 edit 仍为 5.6–27.7 s/模块。
- **Heartbeat 缺陷修复**：上一版 watchdog 会先等 loop 再发心跳；已改为先发心跳、仅 60 s 不可运行才停；新增 Activity 取消/token 失效/线程堆积/短阻塞/永久卡死测试。模块间加入 1 ms yield 让 lease 心跳/取消可运行。
- **测试**：单元 352、契约 33、隔离集成 103/3 skipped、mypy/ruff 通过。
- **决策**：若要求接近本地速度，需云出方向 ≥10–20 Mbps（先读控制台确认套餐/限速/利用率）；无 Schema 的服务端 JSONB 局部更新已测可行（2.5 MiB 每模块 27.7 s→约 0.2–0.3 s），但需单独立项。当前代码 **GO（受控验证部署 + 一次真实 `宠物/10`）**；速度仍受云出口限制，10 位可能 30–60 分钟。若速度必须达标则 NO-GO。
- 未部署、未创建真实任务、未改 Schema/生产数据/网络、未 commit/push/merge。

## 状态历史

- 2026-10-21：待办 → 进行中；开始只读性能诊断。
- 2026-10-21：进行中 → 待验收；代码/隔离测试/报告完成；未部署、未真实复验；结构性带宽/checkpoint 方案待确认。

## 2026-10-21 代码部署（真实任务待网络恢复）

- 已备份 `.runtime/backups/perf03-20261021/{deployed-baseline,candidate}` + SHA256。
- 无活动 lease/root task 前提下，`launchctl kickstart -k` 加载新代码：新 PID **54216**，runs=3；启动日志 `collection worker polling xingtu-unit-local-mac-02`；Temporal poller `alive=True, fresh_pollers=2`。
- **真实 `宠物/10` 未创建**：Mac 当前手机 WiFi 为对称 NAT，Tailscale DERP(sea) 378 ms，PostgreSQL 连接超时；待 direct 网络恢复后执行。
- 证据：[deployment-2026-10-21.md](../evidence/deployment-2026-10-21.md)。
