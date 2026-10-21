# PERF-02：混合部署网络瓶颈与 checkpoint 优化专项验证

状态：待验收
更新时间：2026-10-21T01:45:00+08:00
是否验收：否；网络瓶颈与优化收益已实测，heartbeat 缺陷已修复并通过测试；**未部署、未创建真实采集任务**，真实 `宠物/10` 复验待授权。

## 目标与范围

在 PERF-01 基础上回答：

1. 40–90 KiB/s 的瓶颈到底来自云出口、Tailscale 中继、Mac 网络、数据库访问模式还是其他；
2. 当前 checkpoint 优化在 0.5 / 1 / 2.5 MiB checkpoint 下的真实收益；
3. 独立 Temporal heartbeat 线程在 Activity 完成、取消、过期、loop 阻塞、lease/generation 失效时的安全性；
4. 是否具备受控部署 + 一次真实 `宠物/10` 验证的条件；
5. 是否存在不修改 Schema 的进一步优化空间。

不做：部署/重启正式 Worker、创建真实采集任务、修改生产业务库/Schema/账号/Cookie/Profile、修改腾讯云安全组/Tailscale ACL/生产网络、Git commit/push/merge、数据库重构。

## 关联与依赖

- 前置：[PERF-01](PERF-01.md)、[P1FIX-02](P1FIX-02.md)、[E2E-01](E2E-01.md)。
- 证据：[perf-verification-2026-10-21.md](../evidence/perf-verification-2026-10-21.md)。

## 已证实结论

### 网络

- Tailscale 为 **direct**（`active; direct 119.91.210.100:41641`，首个 pong 即 direct），**不是 DERP/relay**；RTT 18–20 ms。
- **方向严重不对称**：PostgreSQL 云→Mac 下载 41–61 KiB/s；Mac→云上传 1.5–6.3 MiB/s。MinIO GET 50–122 KiB/s；PUT 0.7–7.3 MiB/s。同一路径、同一 RTT、同一时段。
- 并发下载总吞吐不提升（约 40–108 KiB/s）；并发上传提升到 5 MiB/s。MinIO 与 PostgreSQL 同时受限。
- PostgreSQL 服务器执行 `SELECT payload` **0.046 ms**；无锁等待/死锁/临时文件；11/100 连接；缓存命中约 99.996%。
- 结论：**云端→Mac 方向出口带宽/整形是主瓶颈**；具体腾讯云套餐值未能读取（无 SSH/tccli/控制台权限），属高置信度而非已读取配置。不是 Tailscale 中继、不是 Mac 网络、不是 DB 慢查询/锁/连接池。

### 当前优化收益（隔离 benchmark）

真实 Engine（部署基线 vs 当前代码），本地 PostgreSQL，独立限速代理（云→Mac 100 KiB/s，Mac→云 2 MiB/s，10 ms），1 个 basic 模块：

| checkpoint | 版本 | 完整传输 | 下行 MiB | 总耗时 s | 单次最大调用 s | 心跳最大间隔 s |
|---:|---|---:|---:|---:|---:|---:|
| 0.50 MiB | old | 10 | 5.03 | 54.69 | 5.65 | — |
| 0.50 MiB | new | **3** | **1.52** | **18.38** | 5.64 | **1.006** |
| 1.00 MiB | old | 10 | 10.03 | 108.45 | 11.13 | — |
| 1.00 MiB | new | **3** | **3.02** | **34.85** | 11.12 | **1.005** |
| 2.50 MiB | old | 10 | 25.03 | 270.36 | 27.68 | — |
| 2.50 MiB | new | **3** | **7.52** | **84.64** | 27.70 | **1.010** |

- 单模块耗时 **−66%–69%**；完整传输 **10 → 3**（边际 7 → 1）；下行字节 **−70%**；8 模块模型 **59 → 10**（约 5.9× 更少）。
- **剩余 1 次完整 edit 仍是主要成本**：5.64 / 11.12 / 27.70 s（0.5/1/2.5 MiB）。
- 旧路径在 2.5 MiB 单模块超过 120 s lease TTL，首次运行 `LEASE_LOST`；benchmark 延长隔离 lease 才能测完。这证明旧路径在真实链路下不只是慢，而是会失败。
- `module_seconds` 新旧口径不完全可比（旧的 finally 含全量 edit；新的观测全量 edit 本来在计时外），不用于计算提升比例。

### Heartbeat

- 发现并修复上一版 `TemporalHeartbeat` 的缺陷：`_loop_responsive()` 先等待 loop 再发心跳，会在 loop 阻塞时延迟心跳。现改为**先发心跳**，仅当 loop 连续 60 s 不可运行时停止；测试覆盖。
- Activity context 传递、正常完成、异常、取消、token 失效、loop 短阻塞仍心跳、loop 永久卡死停止、20 次 start/stop 无线程堆积、lease 失效，均通过测试。
- 未用独立 Temporal 服务器做端到端 heartbeat timeout/cancel；使用 `ActivityEnvironment` + 生产历史 `not_found` 证据。

### 无 Schema 进一步优化

- 服务端 JSONB 局部更新原型：0.5/1/2.5 MiB checkpoint 上，32 KiB observation 的索引扫描 0.4–0.7 ms、更新 **5.5–7.8 ms**；网络只需约 32 KiB 上行。
- 估算 2.5 MiB 每模块 **27.7 s → 0.2–0.3 s**；8 模块约 222 s → 2 s；但 start/end 2 次完整 edit 和 covers 仍在（约 55 s + 60 s/达人）。
- 不需要 Schema 迁移，但要改观测提交/basic 阈值/`persist_creators`/幂等路径，属核心数据路径改动；本轮未实现，建议单独立项。

## 实现修复（本轮）

| 文件 | 内容 |
|---|---|
| `backend/src/xingtu/worker.py` | `TemporalHeartbeat` 改为“先发心跳、后探测 loop”；仅 60 s 不可运行才停止；每 attempt 一个 daemon 线程，stop/join |
| `backend/src/xingtu/engine.py` | 模块之间/精选观测之间加入 `asyncio.sleep(0.001)`，让 lease 心跳/取消在模块之间运行；不改变数据/筛选/完整度语义 |
| `backend/tests/unit/test_worker_heartbeat.py` | 新增 token 失效、线程不堆积、Activity 取消、collect start/stop、异常 stop、短阻塞仍心跳、永久卡死停止 |
| `backend/tests/integration/test_progress.py` | 新增已释放 lease 的 heartbeat → `LEASE_LOST` |
| `scripts/diag/checkpoint_benchmark.py` | 新增：旧/新 Engine + 限速代理 + 0.5/1/2.5 MiB + 心跳/loop lag/字节/调用计数 |
| `scripts/diag/hybrid_db_latency.py` | 上一轮只读探针；本轮格式化并复用 |

**未做**：未部署、未创建真实任务、未改 Schema/生产数据/网络/账号/Profile、未 commit/push/merge。

## 验证证据

- 网络/DB/MinIO/benchmark 报告：[perf-verification-2026-10-21.md](../evidence/perf-verification-2026-10-21.md)
- [网络路径](../evidence/perf-verification-2026-10-21/01-network-path.txt)
- [DB 内部](../evidence/perf-verification-2026-10-21/02-db-internals.txt)
- [DB 双向吞吐](../evidence/perf-verification-2026-10-21/03-db-throughput.txt)
- [MinIO phases](../evidence/perf-verification-2026-10-21/04-minio-phases.txt)
- [局部更新原型](../evidence/perf-verification-2026-10-21/05-partial-update-prototype.txt)
- [并发扩展](../evidence/perf-verification-2026-10-21/06-concurrency.txt)
- [测试](../evidence/perf-verification-2026-10-21/07-tests.txt)
- [Benchmark 汇总](../evidence/perf-verification-2026-10-21/08-benchmark-summary.txt)
- [Benchmark JSON](../evidence/perf-verification-2026-10-21/bench/)
- [验证后生产只读状态](../evidence/perf-verification-2026-10-21/09-production-state.txt)

测试结果（2026-10-21）：单元 **352 passed**；契约 **33 passed**；隔离 PostgreSQL 集成 **103 passed, 3 skipped**；mypy **Success 34 files**；ruff check/format **通过 92 files**。

## 决策

1. **主瓶颈证实：云端→Mac 出口带宽/整形**（高置信度；套餐值待控制台确认）。
2. **当前优化收益**：隔离实测单模块 −66%–69%，完整传输 10→3，字节 −70%；8 模块模型 59→10（约 5.9×）。真实 `宠物/10` 未跑。
3. **带宽升级**：若要求接近本地速度，需要 **云出方向 ≥10–20 Mbps**；先读控制台确认套餐/限速/利用率，不先采购。
4. **无 Schema 优化**：服务端 JSONB 局部更新可行且已测；需单独立项，不在本轮扩大范围。
5. **Heartbeat/终态安全性**：代码与隔离测试通过；发现并修复 watchdog 缺陷；未真实部署。
6. **GO（受控验证部署 + 一次真实 `宠物/10`）**：正确性验收可做；速度仍受云出口限制，10 位可能 30–60 分钟。若要求速度达标，NO-GO，先升级带宽或做局部更新。

## 部署与回滚（待授权）

- 备份当前 4 个 Python 文件 → 替换 → 仅 `launchctl kickstart -k` Mac Worker；无迁移、无云端改动。
- 回滚：恢复 4 个文件并重启 Worker；不删任务/快照。
- 真实复验：只创建 1 个 `宠物/10`；检查终态、heartbeat、快照/精选、幂等、generation fence、DB/loop 日志；不重试历史任务。
- 中止条件：`LEASE_LOST`、heartbeat timeout、10 分钟无进度、root_task 非预期状态、发布异常。

## 状态历史

- 2026-10-21：待办 → 进行中；开始网络瓶颈与优化收益验证。
- 2026-10-21：进行中 → 待验收；网络/benchmark/heartbeat 验证完成；发现并修复 watchdog 缺陷；未部署/未真实复验；GO（受控验证）。

## 2026-10-21 带宽评估后续（PERF-03）

[PERF-03](PERF-03.md) 完成 0.5/5/10/20 Mbps 的 8 模块 benchmark 与单达人模型：10 Mbps 在 2.5 MiB checkpoint、30 封面、60 s 浏览器基线下约 **96.6 s/达人（≤120）**；20 Mbps 约 **84.4 s**；5 Mbps 约 121.5 s（边界）；0.5 Mbps 约 602 s（不达标）。旧代码 20 Mbps/2.5 MiB/8 模块 DB 仍 75.6 s，总计约 144 s >120，故必须保留当前代码优化。**推荐方案 B：10 Mbps 起、20 Mbps 优先**；具体套餐/费用需控制台确认。报告：[bandwidth-optimization-2026-10-21.md](../evidence/bandwidth-optimization-2026-10-21.md)。

## 2026-10-21 代码部署（真实任务待网络恢复）

- 已备份 `.runtime/backups/perf03-20261021/{deployed-baseline,candidate}` + SHA256。
- 无活动 lease/root task 前提下，`launchctl kickstart -k` 加载新代码：新 PID **54216**，runs=3；启动日志 `collection worker polling xingtu-unit-local-mac-02`；Temporal poller `alive=True, fresh_pollers=2`。
- **真实 `宠物/10` 未创建**：Mac 当前手机 WiFi 为对称 NAT，Tailscale DERP(sea) 378 ms，PostgreSQL 连接超时；待 direct 网络恢复后执行。
- 证据：[deployment-2026-10-21.md](../evidence/deployment-2026-10-21.md)。
