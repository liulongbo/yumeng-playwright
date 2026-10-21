# 混合部署采集性能诊断与 Heartbeat / 终态修复报告

- 日期：2026-10-21（UTC+08）
- 关联真实任务：`b5a01709-8a4b-46bd-aa31-6494b0d9ce24`（第二次 `宠物/10`）、`11f9fc9c-ad06-4d41-9fde-c33bab168f47`（第一次 `宠物/10`）
- 关联卡片：[PERF-01](../tasks/PERF-01.md)、[PERF-02](../tasks/PERF-02.md)、[P1FIX-02](../tasks/P1FIX-02.md)、[E2E-01](../tasks/E2E-01.md)
- 后续专项验证（网络方向/0.5–2.5 MiB benchmark/heartbeat 缺陷修复）：[perf-verification-2026-10-21.md](perf-verification-2026-10-21.md)。该轮以方向不对称（DB 下载 41–61 KiB/s vs 上传 1.5–6.3 MiB/s）确认瓶颈在**云→Mac 出口**，并修正了 heartbeat watchdog 的一处缺陷；本轮结论以该报告为准。
- 结论：**性能根因已定位并完成最小修复；真实采集复验未执行**。
  - 采集变慢的主因不是 Temporal 或 asyncio 本身，而是 **每一步都通过 0.6 Mbps 级 Tailscale/云出口链路传输 510 KiB 级完整 checkpoint**，叠加 **covers 改走远程 MinIO 读回校验**。
  - Heartbeat timeout 是上述阻塞/链路饱和的结果；`not_found` 终态分类错误是独立的收口缺陷。
  - 本轮只改代码、隔离测试和只读测量；**未部署、未重启正式 Worker、未创建真实任务、未修改生产业务数据**。
  - 两个历史任务在本轮开始前已是 `CANCELLED`（15:34:29Z / 15:34:38Z，非本轮写入），不再保持 `COLLECTING`；本轮未重试/取消/修复它们。

---

## 1. 证据边界与测量条件

| 项目 | 事实 |
|---|---|
| 代码版本 | 工作区相对 `HEAD 5182c09` 含上一轮未提交的混合部署/修复改动；本轮改动见 §5。**未 commit/push/merge**。 |
| 正式 Worker | Mac `launchd` PID 20406，2026-10-20 23:05 启动，加载的是**部署时**代码；本轮修改**尚未部署**。 |
| 正式云服务 | 腾讯云 `yumeng-xingtu-cloud`（Tailscale `100.86.124.51`），PostgreSQL 18.3、Temporal、MinIO、API。未重启/改配置。 |
| 本轮对生产库的操作 | 仅 `SELECT`、`SET TRANSACTION READ ONLY`，以及会话内 `TEMP TABLE`（`hybrid_db_latency.py` 写入后 `ROLLBACK`）。未写业务表。 |
| 真实采集 | **未创建新任务**（按授权）。本轮没有真实 `宠物/10` 复验。 |
| 历史任务状态 | 本轮 00:06 首次只读查询时，`b5a01709` 已是 `CANCELLED v137`（updated 15:34:29Z），`11f9fc9c` 已是 `CANCELLED v184`（updated 15:34:38Z）；两者均 `completed_at` 有值、`creator_snapshots` 仍为 0（`b5a01709`）。该变化发生在 `e2e-real-collection-run2-2026-10-20.md` 成文（15:32）之后；`audit_logs` 显示两条 `action=cancel`，actor 均为 `product:a1598139-34e9-4e2c-baf4-711feedf8ea3`（15:34:27Z / 15:34:36Z），**不是本轮操作**。 |
| 测量脚本 | `scripts/diag/hybrid_db_latency.py`（新增，默认只读；写基准仅 TEMP TABLE）。 |

> 说明：本文严格区分“**真实历史证据**”“**本轮生产只读实测**”“**隔离数据库实测**”“**由代码路径与实测单价推导的估算**”。没有把推导值写成实测值。

---

## 2. 结论摘要（先看这里）

### 2.1 采集速度为什么明显下降

**已证实：**

1. **Hot path 每模块至少传输完整 checkpoint 7 次。** 在 `Engine._collect_once()` 的每个模块循环中，旧代码执行：
   - `charge()` → 全量 `edit`（读 + 写 checkpoint）
   - `guard()` → 再 `charge()` 全量 `edit` + `repo.get()` 全量读
   - `repo.get()` 全量读
   - 模块 `finally` 全量 `edit` 写 `module_seconds`
   - 观测落库全量 `edit`
   - `fresh = repo.get()` 全量读
   
   合计 **3 次全量读 + 4 次全量读改写 = 至少 7 次完整 checkpoint 传输/模块**（adapter 的 `guard()` 还会增加）。

2. **checkpoint 已达 510 KiB（文本），且随候选/观测增长。** `b5a01709` 的 `task_checkpoints.payload`：文本 **521,870 B（约 510 KiB）**，`pg_column_size` **131,091 B**。历史本地库中同类 checkpoint 最大到 **9.2 MB 文本**。

3. **Mac → 腾讯云 PostgreSQL 的有效吞吐只有约 46–89 KiB/s。** 同一时段普通公网下载可达 0.36–2.9 MB/s；Tailscale RTT 约 19 ms，TCP 建连约 19 ms。**并发 1/4/8 条连接的总吞吐没有提升**（89 / 53 / 77 KiB/s），说明是共享带宽上限，而不是单连接慢。

4. **一次 `Repository.get()` 实测 7.7–8.3 s，同字节 `SELECT repeat(...)` 9.6–9.8 s。** 本地隔离库同一 617 KiB checkpoint 的 `Repository.get()` 仅 **14.5 ms**。远程/本地约 **530–570 倍**。

5. **模块耗时被 DB 传输支配。** `b5a01709` 的 `module_seconds` 与 2026-10-15 本地真实任务 `381d628b`（同为 20 候选、2 位有效）对比：

   | 模块 | 混合部署（实测） | 本地历史（实测） | 倍数 |
   |---|---:|---:|---:|
   | basic | 28.89 s | 0.12 s | 243× |
   | commercial | 21.21 s | 0.10 s | 213× |
   | fulfillment | 4.96 s | 0.11 s | 44× |
   | conversion | 3.94 s | 0.11 s | 36× |
   | spread | 3.25 s | 0.10 s | 34× |
   | seeding | 2.63 s | 0.11 s | 25× |
   | creation | 97.16 s | 4.56 s | 21× |
   | fans | 14.63 s | 4.54 s | 3.2× |
   | **合计** | **176.67 s** | **9.74 s** | **18×** |

   `basic`/`commercial` 的浏览器工作量很小，却从 0.1 s 变成 20–29 s，这部分不可能是页面操作，只能是同步 DB 往返。

**高置信度：**

6. 云服务器公网出口/Tailscale 路径存在约 **0.6 Mbps 级共享上限**（46–89 KiB/s）。Mac 当前 WiFi 也在波动（普通下载 0.36–2.9 MB/s），因此不能把全部责任归给云端；但“普通公网 23 Mbps 时 DB 仍只有 76 KiB/s”这一点表明瓶颈不只在 WiFi。未读取腾讯云带宽套餐（本轮无 SSH 权限），故不写成“已证实”。

7. **covers 从本地目录改为远程 MinIO 后增加了固定成本。** `b5a01709` 34 个封面、共 1,299,928 B；首个达人 30 个封面在 **68 s** 内完成（15:18:37–15:19:45）。每个封面的流程是 `put_object` → `head_object` → `get_object`（读回校验）→ 一次新连接写 `media_objects`。其中读回校验是业务完整性要求，不能删除；但每个封面多一次跨网下载，叠加 DB 建连，使 creation 模块从本地 4.56 s 变为 97.16 s。

### 2.2 Heartbeat timeout 为什么发生

**已证实：**

1. 旧路径中 Temporal heartbeat 的发送点位于同步 DB 工作之后/同一事件循环内；`engine.guard()` 每次全量 `repo.get()`（实测 7.7–8.3 s）是纯同步 psycopg 调用，直接阻塞 asyncio loop。
2. 每个模块至少 7 次全量传输中，多次连续发生在 loop 上；单次 8 s，连续几次即可逼近/超过 45 s 的 heartbeat timeout。与此同时，大 checkpoint 传输会占满 0.6 Mbps 链路，使独立的 lease 续租小查询也排队。
3. 证据：15:26:21.656 `activity heartbeat failed reason=RESOURCE_UNAVAILABLE: HEARTBEAT_TIMEOUT elapsed=11.4s`；15:29:51.009 Temporal `ACTIVITY_TASK_TIMED_OUT`，`MAXIMUM_ATTEMPTS_REACHED`。
4. `execution_units` 正常阶段约每 15 s 续租；但 attempt 2–4 不再出现 heartbeat 日志，说明 heartbeat 协程/事件循环已被长时间同步 DB 调用拖住或取消。

**因果链：** 完整 checkpoint 过大 + 链路吞吐低 → 每次 `get/edit` 数秒 → 同步调用阻塞 loop 并占满链路 → Temporal heartbeat 与 lease 续租被饿死 → 45 s 超时 → Activity 取消 → 重试 → 再次读取完整 checkpoint/重新导航 → 更快耗尽重试预算。

### 2.3 root_task 为什么无法收口

**已证实：**

1. 部署版本的 `should_finalize_cancelled()` 把 `not_found=True` 与 `paused/reset` 一起排除，返回 `False`。
2. run2 的 **最后一次 attempt（attempt 4）** cancellation details 正是
   `ActivityCancellationDetails(not_found=True, cancel_requested=False, paused=False, reset=False, timed_out=False, worker_shutdown=False)`。
3. 因返回 `False`，`_finalize_interrupted()` 未执行；Workflow 于 15:29:53.247Z `FAILED`，root_task 保持 `COLLECTING`。
4. 这不是“Activity 仍有重试机会”：Temporal history 已记录 `retry_state=MAXIMUM_ATTEMPTS_REACHED`，最后一次失败后没有下一次 attempt。

**`not_found` 的 Temporal 语义（核实）：** 表示服务端已不再接受该 Activity 的 task token（Activity 已完成、已超时或已被服务端清理）。它**不**表示“任务不存在”，也**不**表示“仍会自动重试”。在最后一个 attempt 上，它和 `timed_out=True` 一样属于“本次 Activity 已不可继续”的信号；是否安全收口应由持久化的 task/attempt/generation fence 决定，而不是直接跳过。

### 2.4 checkpoint 为什么没有发布

**已证实：**

1. 发布只发生在 `engine.finish()` / `repository.finalize_interrupted(..., publish=True)` 路径。
2. Activity 被取消后没有进入任何终态写入，因此 `persist_creators(publish=True)` 从未执行。
3. `b5a01709` 第一位达人的 8 个模块和两组精选确实已在 checkpoint 中（`COMPLETE`），但 `creator_snapshots=0`、`featured_collections=0`、`featured_cards=0`；34 个封面已入 `media_objects`/MinIO，却没有快照引用。这是“已采集未发布”，不是“未采集”。

### 2.5 这些问题的因果关系

```text
完整 checkpoint（510 KiB，持续增长）
        +
Mac↔云 DB 共享吞吐 ~46–89 KiB/s
        ↓
每次 get/edit 7.7–8.3 s（本地 14.5 ms）
        ↓
每模块至少 7 次全量传输；同步 psycopg 阻塞 asyncio loop
        ↓
Temporal heartbeat / lease 续租被饿死（15:26:21，11.4 s）
        ↓
Activity 取消 → 4 次 attempt 耗尽
        ↓
attempt 4 not_found 分类错误（独立缺陷）
        ↓
不写终态、不发布 checkpoint
        ↓
Workflow FAILED，root_task 仍 COLLECTING，快照/精选为 0
```

`not_found` 分类错误不是变慢的原因；它是超时之后“无法收口”的直接原因。速度下降也不需要假设“混合部署本身有问题”：**同一套代码在本地库上 browser 占主导，在远程库上 DB 传输占主导**。

---

## 3. 架构对比与关键测量

### 3.1 混合部署前后

| 维度 | 混合部署前（2026-10-15 前后的本地开发） | 当前混合部署 |
|---|---|---|
| 应用/DB | 同一台 Mac，本地 Docker | Mac Worker；腾讯云 PostgreSQL |
| DB 地址 | `127.0.0.1:55432` | `100.86.124.51:5432`（Tailscale） |
| Temporal | `127.0.0.1:57233` | `100.86.124.51:7233`（Tailscale） |
| 封面存储 | 本地目录 `.runtime/covers` | 腾讯云 MinIO `:9000`（Tailscale） |
| 关键变化 | DB 往返约 0.1–15 ms | DB 往返 0.16–8.3 s（取决于传输字节） |
| 代码路径 | 同一 `Repository.get/edit` 全量 checkpoint | **未变**；环境变了，代价被放大 |

代码没有在混合部署时“改成逐条请求”；它**原本就是**逐次全量读写。本地库把这种设计的代价隐藏了，远程链路把它放大成主耗时。

### 3.2 本轮生产只读实测（`02-db-latency.json`）

| 操作 | 中位数 | 最小/最大 | 说明 |
|---|---:|---:|---|
| TCP connect（5432） | 19.5 ms | 18.7 / 24.0 ms | Tailscale RTT 约 19 ms |
| psycopg connect + `SELECT 1` | **160.2 ms** | 159.2 / 1,048.4 ms | SCRAM/认证多往返；每次新连接都付 |
| 复用连接 `SELECT 1` | 19.4 ms | 19.1 / 19.8 ms | 查询本身不慢 |
| `Repository.get()`（510 KiB checkpoint） | **8,285.7 ms** | 8,260.1 / 8,311.4 ms | 旧 hot path 每次调用 |
| 同字节 `SELECT repeat('x', 521870)` | **9,788.9 ms** | 9,612.2 / 9,965.7 ms | 纯传输，证明不是 JSON 解析 |
| `candidate_module_complete`（小查询） | 381.7 ms | 160.7 / 3,812.3 ms | 新路径；受建连/链路抖动影响 |
| `candidate_valid`（小查询） | 178.7 ms | 160.9 / 612.6 ms | 新路径 |
| 服务端 progress UPDATE（TEMP TABLE） | 34.2 ms | 30.5 / 39.7 ms | 同连接；新 `record_progress` 的 SQL 形态 |

> 生产只读探针还会输出 `slow database operation op=get ... elapsed_ms=...`，本次为 8,259 / 8,310 ms。该日志由本轮新增的 `XINGTU_DB_SLOW_MS` 控制（默认 1000 ms）。

### 3.3 本地隔离基线（`03-local-baseline.txt`）

| 操作 | 本地实测 |
|---|---:|
| 512 KiB 文本传输 | 中位数 **2.9 ms** |
| `Repository.get()`（617,126 B checkpoint） | 中位数 **14.5 ms** |

历史本地 dump（`.runtime/xingtu-pre-data02-20261016T153124.dump`）恢复到本机隔离容器 `127.0.0.1:55439/xingtu_hist`；不是生产库，也不是模拟数据。远程/本地 `Repository.get()` 比值约 **530–570×**。

### 3.4 链路吞吐（`04-link-bandwidth.txt`）

| 测量 | 结果 |
|---|---|
| Tailscale ping | 18–20 ms，直连 `119.91.210.100:41641` |
| 普通公网下载（Cloudflare 10 MB） | 00:11 为 **2,914,287 B/s（23.3 Mbps）**；00:35 前后波动到 364,693 / 504,232 / 1,706,027 / 431,357 B/s |
| PostgreSQL 128 KiB 单连接 | 1.43 s → **89.2 KiB/s** |
| PostgreSQL 4 并发 × 128 KiB | 9.70 s → **52.8 KiB/s（总吞吐未升）** |
| PostgreSQL 8 并发 × 64 KiB | 6.67 s → **76.8 KiB/s（总吞吐未升）** |
| PostgreSQL 128 KiB 复测 | 中位数 2,788 ms → **45.9 KiB/s** |

结论：**共享吞吐约 46–89 KiB/s（0.4–0.7 Mbps）**；不是单连接 RTT 问题，也不是查询本身慢。普通公网在同一时段远高于此，故瓶颈至少包含云端出口/Tailscale 路径；Mac WiFi 波动是叠加因素。具体套餐未读取（无 SSH），标记为高置信度而非已证实。

### 3.5 单达人耗时分解（真实 run2）

`b5a01709` checkpoint 实测：

- `active_seconds = 672.73 s`（11.2 min）
- `module_seconds` 合计 **176.67 s**
- 候选 20；有效 2；`navigation_count=5`；`observed_requests/responses=107/107`
- 第一位达人：`basic` at **15:16:51.53**；`fans` 15:17:55.52；`creation` 15:19:43.83；两组精选 `excellent_reach` 15:21:33.81、`excellent_seeding` 15:23:04.82；最后一组精选封面 15:23:36.81
- 第二位达人：`basic` at **15:24:51.28**；之后到 15:26:21 heartbeat 失败
- heartbeat 失败 15:26:21.66；attempt 4 开始 15:29:06.01；Activity timed out 15:29:51.01；Workflow failed 15:29:53.25

**可测部分（实测）：**

| 阶段 | 实测 |
|---|---:|
| 第一位达人 basic → 最后精选封面 | **405 s**（15:16:51 → 15:23:36） |
| 其中 `module_seconds` 合计 | 176.67 s |
| 其中 cover 上传（34 个，1.30 MB） | 15:18:37–15:23:36；前 30 个 68 s |
| 第二位达人 basic | 15:24:51，距第一位创建 5 min 前段 |
| heartbeat 失败 elapsed | 11.4 s |
| Activity 总墙钟（scheduled→failed） | 13 min 46 s |

**不可从现有日志精确拆分（未测量）：** 页面加载、单个模块的浏览器操作、每个 `repo.get/edit` 的精确次数与耗时。为此本轮增加了最小埋点（`slow database operation`、`module collected ... elapsed`、`featured collected`、`featured covers`、`activity event loop stalled`），下一次授权运行即可直接测量，不再依赖推断。

**由实测单价 + 代码路径推导（估算，不是实测）：**

| 每模块 | 旧路径 | 新路径 |
|---|---:|---:|
| 全量读 | 3 × ~8.3 s | 0 |
| 全量读改写 | 4 × (~8.3 + 0.65) s | 1 × (~8.3 + 0.65) s |
| 小查询/小写入 | 0 | 5 × ~0.2–0.4 s |
| **合计** | **~56–61 s** | **~9–11 s** |

按 8 个模块计：旧 ~450–490 s，新 ~76–88 s；与第一位达人 405 s 的实测墙钟同量级，说明模型可信。**这是 DB 层的可比较指标，不是新的真实采集结果。**

---

## 4. Heartbeat / 终态 / 发布修复

### 4.1 Temporal heartbeats 不再依赖事件循环

新增 `TemporalHeartbeat`（`worker.py`）：

- 每个 Activity attempt 启动 **1 个** daemon 线程，使用 `contextvars.copy_context()` 传播 Temporal Activity context；线程只调用 `activity.heartbeat(root)`，不访问 DB、浏览器或文件。
- 间隔 10 s；启动即发送一次，覆盖 `BrowserHost.lease`/session 验证/重试窗口。
- **loop watchdog 60 s**：心跳线程每轮用 `loop.call_soon_threadsafe` 探测事件循环；若 60 s 内无法执行一个空回调，停止发送心跳，让 Temporal 自己的 45 s heartbeat timeout 接管。这样既不会被一次 8–40 s 的 checkpoint 传输误杀，也不会把永久卡死的 Activity 藏到 125 分钟的 `start_to_close`。
- `collect()` 在 `finally` 中 `stop()`/`join(timeout=5)`；每个 attempt 最多一个线程，不会无限增长。
- 单元测试覆盖：启动即发送、阻塞 0.2 s 的事件循环仍持续发送、`stop()` 后停止、事件循环永久卡死时停止。

独立于 Temporal heartbeat 的 **lease heartbeat** 仍保留在 asyncio 任务中：

- `renew_lease()` 继续用 `asyncio.to_thread` + 10 s 上限；
- `Repository.heartbeat(..., lock_timeout_seconds=8)` 使用 `SET LOCAL lock_timeout`，不会在业务写持有 unit 行时无限排队；失败转成稳定的 `CollectorError`，由 Activity 取消并走重试/收口；
- `activity event loop stalled` 日志在 sleep 超时 ≥2 s 时记录，下一次可直接量化 loop 阻塞。

### 4.2 终态收口（P1-A）

`should_finalize_cancelled()` 现在：

- `attempt < 4`：一律不收口（Temporal 仍有重试预算）；
- `attempt >= 4`：
  - `worker_shutdown` → 不收口（Temporal 重启后会重试）；
  - `cancel_requested` → 不收口（用户/产品取消路径负责）；
  - `paused/reset` → 不收口；
  - `timed_out=True` → 收口；
  - `not_found=True` → **收口**；
  - 本地 `heartbeat_error` 存在 → 收口。

收口调用链：

```text
CancelledError
  → should_finalize_cancelled(...)
  → _finalize_interrupted(root, task, reason, engine, host)
      → engine.finish(force=True, failure_reason=reason)          # 优先，复用正常 finish 的发布逻辑
      → repo.finalize_interrupted(..., publish=True)              # engine 不可用/失败
      → repo.finalize_interrupted(..., publish=False)             # 发布失败时至少落终态
      → 最后记录 error 日志并返回当前 durable state
```

关键性质：

- `engine.finish(force=True)` 仍经过 `repo.edit(require_lease=False)`，**保留 task/attempt/generation fence**；旧 Worker 不能覆盖新 Worker。
- `finalize_interrupted` 只处理 `RUNNING` 且 `attempt_id` 匹配的任务；已终态任务直接返回，**幂等，不重复发布/覆盖**。
- 目标/完整度满足 → `COMPLETED`；有有效数据但未满足 → `PARTIAL_COMPLETED`；无有效数据 → `FAILED`。
- 普通 Worker shutdown / 用户 cancel / paused / reset **不会**被写成采集失败。

### 4.3 checkpoint 发布

- `engine.finish(force=True)` 复用 `persist_creators(conn, task, publish=True)`，为每个 `valid` 候选生成快照，未采集模块/集合以 `NOT_ATTEMPTED` 和 `UPSTREAM_INTERRUPTED` 保留，不伪造数据。
- 第一位达人已有 8 模块 + 2 精选，会在下一次授权部署后的真实失败/完成路径中正常发布；本轮未对历史任务执行发布。
- 发布失败时退化为 `publish=False` 终态写入，避免“发布失败 → 永久 COLLECTING”；最后失败会记录 `collection activity finalization failed ... error=CODE:REASON`。
- 幂等性由 `finalize_interrupted` 的 `state not in RUNNING` 检查和 integration test 覆盖；重复收口不会新增快照。
- **真实 checkpoint 重放（隔离库，不是生产）**：把 run2 的真实 `root_tasks`/`task_checkpoints`/`tasks`/34 个 `media_objects` 行复制到本机隔离 PostgreSQL，把 root 置回 `COLLECTING`、unit generation=9，然后调用 `finalize_interrupted(..., 'HEARTBEAT_TIMEOUT', lease_generation=9)`：
  - root → **PARTIAL_COMPLETED**，`failure_reason=HEARTBEAT_TIMEOUT`，`completed_at` 写入；
  - `task_creators=2`、`creator_snapshots=2`、`featured_collections=2`（两组均 `COMPLETE`）、`featured_cards=8`、`snapshot_collections=2`；
  - 第二位仅有 basic 的达人得到带 `NOT_ATTEMPTED` 缺口的快照，不伪造数据；
  - 再次调用收口，所有计数不变（幂等）。
  - 证据：[07-closeout-replay.txt](hybrid-performance-diagnosis-2026-10-21/07-closeout-replay.txt)。该重放不修改生产库；生产两个任务仍是 `CANCELLED`、`b5a01709` 快照仍为 0。

---

## 5. 修复内容（最小改动）

| 文件 | 关键改动 | 原因 | 对现有链路影响 |
|---|---|---|---|
| `backend/src/xingtu/worker.py` | `TemporalHeartbeat` 线程 + 60 s loop watchdog；`collect()` 启停；`not_found` 最后 attempt 收口；`_finalize_interrupted` 错误日志；heartbeat 异常/loop lag 日志；dispatch DB 调用移出事件循环（上一轮已做） | 防止同步 DB 阻塞饿死 Temporal heartbeat；保证重试耗尽后必落终态 | 正常采集仍走 `engine.run()`；lease/generation 语义不变；每 attempt 一个线程 |
| `backend/src/xingtu/repository.py` | 新增 `record_progress()`（服务端 JSONB 增量更新，含 lease/attempt/state/version fence）；`candidate_module_complete()`、`candidate_valid()` 小查询；`heartbeat(lock_timeout_seconds)`；`XINGTU_DB_SLOW_MS` 慢操作日志；`get/edit/finalize_interrupted` 计时 | 消除 hot path 上非必要的完整 checkpoint 传输；给下一次运行留下可核验耗时 | 无 Schema/迁移；`record_progress` 只允许计数器和 `module_seconds`，不触碰采集值；root/checkpoint 行锁顺序与 `edit` 一致 |
| `backend/src/xingtu/engine.py` | `guard()` 使用内存 `active_seconds` + `record_progress`，不再 `repo.get`；`charge()` 用小增量写；模块循环用 `candidate_module_complete`/`candidate_valid`；`module_seconds` 用小增量写；模块/精选/封面耗时日志 | 每模块全量传输 ≥7 次 → 1 次，降低 loop 阻塞与链路占用 | `active_seconds` 仍逐次持久化；预算判定口径不变；模块跳过/观测落库逻辑不变 |
| `backend/src/xingtu/browser_host.py` | `heartbeat_lease(lock_timeout_seconds=8)` | 避免 lease 续租在业务写后无限排队；失败可诊断 | 正常续租不变；失败会触发既有 `HEARTBEAT_*` 取消/重试路径 |
| `backend/tests/unit/test_worker_heartbeat.py` | 线程心跳、阻塞 loop、watchdog、stop 测试 | 证明 heartbeat 不再依赖 loop | 仅测试 |
| `backend/tests/unit/test_worker_cancellation.py` | `_finalize_interrupted` 引擎/回退/最终失败测试 | 证明收口链与 generation fence | 仅测试 |
| `backend/tests/unit/test_engine_progress.py` | `guard` 不读 checkpoint、预算、计数器去重 | 防止性能回退 | 仅测试 |
| `backend/tests/integration/test_progress.py` | `record_progress` 持久化/幂等 fence/小查询完整性 | 真实 PostgreSQL 行为 | 仅测试 |
| `deploy/macos/worker.env.example`、`deploy/application.env.example` | 增加 `XINGTU_DB_SLOW_MS=1000` | 部署时可观测 | 默认不影响行为 |
| `scripts/diag/hybrid_db_latency.py` | 只读 DB/链路探针 + TEMP TABLE 写基准 | 下一次可复现测量 | 不接触业务表 |

**没有做的事：** 未改 Schema/迁移、未改筛选/有效性/完整度口径、未改 F10 takeover/challenge、未改账号/Cookie/Profile、未改 P1/DeepSeek、未改 Workflow 图与重试次数、未延长 heartbeat timeout、未部署、未创建真实任务。

---

## 6. 性能对比

### 6.1 可核验指标

| 指标 | 修复前（部署代码/当前链路） | 修复后（工作区代码，隔离验证） | 证据类型 |
|---|---:|---:|---|
| 每模块完整 checkpoint 传输次数 | **≥7**（3 读 + 4 读改写，adapter guard 还会增加） | **1**（观测落库） | 代码路径 |
| 每模块传输量（510 KiB checkpoint） | 约 **5.6 MiB** | 约 **1.0 MiB + 5 个小请求** | 代码路径 + 实测字节 |
| 每模块 DB 时间（推算） | **~56–61 s** | **~9–11 s** | 实测单价 × 路径 |
| `Repository.get()` 510 KiB | **8.3 s** | 不再出现在模块 hot path | 生产只读实测 |
| `record_progress` | 不存在 | 同连接 SQL **34 ms**；含建连约 0.2 s | TEMP TABLE + 生产只读 |
| `candidate_module_complete` | 不存在 | 中位数 **0.38 s** | 生产只读 |
| `candidate_valid` | 不存在 | 中位数 **0.18 s** | 生产只读 |
| 单达人 8 模块 DB 时间（推算） | ~450–490 s | ~76–88 s | 同上 |
| `module_seconds` 实测（run2） | 176.67 s / 8 模块 | 待部署后真实复验 | 真实历史 |
| 本地同 checkpoint `Repository.get()` | 14.5 ms | 14.5 ms | 隔离实测 |
| Temporal heartbeat | 15:26:21 `HEARTBEAT_TIMEOUT` 11.4 s | 独立线程 + watchdog，单测通过 | 真实历史 + 单测 |
| root_task 终态 | `COLLECTING` 永久 | 最后 attempt 收口 + 发布，集成测试通过 | 真实历史 + 集成测试 |
| 快照/精选 | 0 / 0 | 收口时按 checkpoint 发布；幂等测试通过 | 真实历史 + 集成测试 |

### 6.2 必须说清楚的限制

- **没有修复前后同条件的真实采集对比。** 本轮未获授权创建真实任务；表中“修复后”是隔离测试/只读测量/代码推导，不是真实 E2E 结果。
- **历史本地基线不是严格 A/B。** `381d628b` 是 2026-10-15 的本地任务（汽车/2），与 run2（宠物/10）关键词、代码版本和目标数不同；用它对比的是“同一类模块计时在本地库/远程库下的量级差”，不是同条件对照实验。
- 即使修复后，**每模块仍有 1 次完整 edit**（读 + 写 510 KiB）。在 0.6 Mbps 链路上约 8.9 s/模块；checkpoint 增长到 2.5 MB 时约 40 s/模块。**上表 ~9–11 s/模块只覆盖 DB 传输，不含 `creation` 的封面下载/上传/读回校验**；run2 首个达人 30 个封面约 68 s，这部分仍是约 60–70 s 的固定成本，除非 MinIO/链路改善。因此：
  - 在 510 KiB 时，10 位目标仍可能需 ~20–30 分钟（推算，未实测）；
  - 在历史 9.2 MB 级 checkpoint 时，单次 edit 就会超过 2 分钟，**热路径优化不足以让混合部署恢复到本地速度**。
- 要把采集恢复到接近本地水平，必须处理 **链路带宽** 或 **完整 checkpoint 的结构**；这超出本轮“最小代码修复”的授权，需另行确认（见 §9）。

---

## 7. 自动化测试

环境：macOS，Python 3.13，隔离 PostgreSQL 18.3 容器 `127.0.0.1:55439`（测试 schema 随机创建/销毁，不使用生产库）。

| 检查 | 命令 | 结果 |
|---|---|---|
| 后端单元 | `.venv/bin/pytest backend/tests/unit -q` | **346 passed** |
| 后端契约 | `PLAYWRIGHT_BROWSERS_PATH=... pytest backend/tests/contract -q` | **33 passed** |
| 隔离 PostgreSQL 集成 | `XINGTU_TEST_DATABASE_URL=postgresql://.../xingtu_test_perf pytest backend/tests/integration -q` | **101 passed, 4 skipped** |
| mypy | `.venv/bin/mypy backend/src` | **Success, 34 files** |
| ruff check | `.venv/bin/ruff check backend` | **All checks passed** |
| ruff format | `.venv/bin/ruff format --check backend` | **89 files already formatted** |
| 前端 | 未改前端；未复跑 | 不适用（本轮无前端变更） |

新增/更新的针对性测试：

- `test_worker_heartbeat.py`：`renew_lease` 成功/超时/异常/CollectorError；线程心跳启动即发送；**事件循环阻塞 0.2 s 仍持续心跳**；`stop()` 后停止；**事件循环永久卡死时 watchdog 停止心跳**。
- `test_worker_cancellation.py`：`timed_out` 仅最后 attempt 收口；`not_found` 最后 attempt 收口、attempt<4 延迟；`worker_shutdown`/`cancel_requested`/`paused`/`reset` 不收口；`_finalize_interrupted` 引擎优先/发布失败退化/全部失败返回 durable state。
- `test_engine_progress.py`：`guard` 不读 checkpoint；预算用 `record_progress` 返回值；计数器增量不重复。
- `test_engine_finish.py`：force finish 跳过 lease 但保留 fence；PARTIAL/COMPLETED/FAILED；幂等；generation fence。
- `test_interrupted_finalize.py`（既有）：真实 PostgreSQL 终态/幂等/generation fence/checkpoint 发布。
- `test_progress.py`（新增）：`record_progress` 保留观测、返回 active、版本/revision 递增、无变化 no-op、stale generation/attempt/version 全部拒绝；`candidate_module_complete` 与 domain `ModuleObservation.complete` 在真实 checkpoint 上逐模块一致；`candidate_valid` 与缺失候选。
- **真实 run2 checkpoint 收口重放（隔离 PostgreSQL）**：`finalize_interrupted` → PARTIAL_COMPLETED；`creator_snapshots=2`、`featured_collections=2`（COMPLETE）、`featured_cards=8`、`snapshot_collections=2`；重复收口计数不变。证据见 07。

**未覆盖/未执行：**

- 真实 `宠物/10` 采集（未授权）。
- 真实 Playwright + Chrome 的 F10/挑战路径（本轮 F10 未触发）。
- 部署后 Mac Worker + 云 DB 的真实 `record_progress` 写入（代码路径已用 TEMP TABLE 验证 SQL 形态，但未在生产任务中运行）。
- 长时间（>60 s）事件循环卡死 + 125 分钟 `start_to_close` 的真实行为（仅单测 watchdog）。
- 前端/UI 回归（本轮未改前端）。

---

## 8. 回归风险

| 路径 | 影响 | 评估/缓解 |
|---|---|---|
| 正常采集 | `charge/guard` 改小写入；`active_seconds` 在内存中累加 | 中；预算口径逐次持久化，测试覆盖；需真实复验 |
| `active_seconds` 预算 | 由 `record_progress` 返回值更新；并发写入仍由 root 行锁串行 | 低-中；`record_progress` 有完整 lease/attempt/version fence；测试覆盖 |
| 模块跳过 | `candidate_module_complete` 用 SQL 复现 `ModuleObservation.complete` | 中；已在真实 `b5a01709` checkpoint 上逐模块与 Python 结果一致；集成测试覆盖；SQL 规则需随 domain 规则同步 |
| `record_progress` 幂等/版本 | 服务端更新 `revision` 列 + payload `revision`，`version` 列 + payload `version` | 中；集成测试断言两者递增；正常 `edit` 仍用 `_save`，会覆盖为一致值 |
| Temporal 重试 | 线程心跳只在 attempt 内；`not_found` 仅在 attempt>=4 收口 | 中；分类测试覆盖；不会提前结束 attempt<4 |
| Worker shutdown | `worker_shutdown` 明确不收口；线程 stop | 低；单测覆盖 |
| 用户取消 | `cancel_requested` 交给既有 cancel 路径；`CANCELLING→CANCELLED` 不变 | 低；未改 cancel 路径 |
| 租约/generation | `record_progress` 只读 lease，不持锁；`edit` 仍 `FOR UPDATE`；finalizer 保留 generation fence | 中；真实 PostgreSQL 测试覆盖 stale generation；需真实并发复验 |
| Heartbeat 线程 | 若 watchdog 失效，可能延长卡死 Activity | 中；60 s watchdog + `start_to_close=125 min` 双重边界；单测覆盖 watchdog |
| `lock_timeout=8 s` | 极端长发布可能让 lease 续租失败 | 低-中；失败会走重试/收口，不会静默；部署后观察 `HEARTBEAT_LockNotAvailable` |
| checkpoint 发布 | force finish 复用正常 publish；可能发布不完整快照 | 中；与正常 `finish` 同口径，标记 `NOT_ATTEMPTED`；需真实复验确认业务可接受 |
| F10 | 未改 takeover/challenge/browser host 录制逻辑 | 低；需真实 F10 复验（本轮未触发） |
| 历史数据/迁移 | 无 Schema/迁移；未写历史任务 | 低 |
| P1/P2 派发 | 未改 intake/product_repository/workflow 图 | 低 |

---

## 9. 部署与验收建议（待授权）

### 9.1 最小部署

1. **前置**：确认无活动租约/浏览器（`execution_units.owner IS NULL`、`browser_stopped=true`、无项目 Chrome），确认两个历史任务保持 `CANCELLED`，不再重试/修改。
2. **备份**：把当前工作区的 `worker.py`、`engine.py`、`repository.py`、`browser_host.py` 备份到 `.runtime/backups/<timestamp>/`，记录 SHA256；当前部署基线仍在 `.runtime/backups/p1fix-02-20261020/current/`。
3. **安装**：只替换上述 4 个 Python 文件；在 `.runtime/cloud-worker.env` 增加 `XINGTU_DB_SLOW_MS=1000`（可选，默认 1000）。无需迁移、无需改云端服务。
4. **重启**：仅重启 Mac collection worker（`launchctl kickstart -k gui/$(id -u)/com.yumeng.xingtu.collection-worker`）；不要重启腾讯云 API/DB/Temporal/MinIO。
5. **回滚**：恢复备份的 4 个文件并重启 Worker；无数据库迁移，无需数据回滚；已产生的任务/快照不删除。

### 9.2 真实 `宠物/10` 复验（需单独授权）

只创建 **1 个**新任务，不重试历史任务。验收重点：

| 验收项 | 通过标准 |
|---|---|
| 终态一致性 | 无论 COMPLETED/PARTIAL/FAILED，root_task 在 Workflow 结束后不再 `COLLECTING`；`failure_reason` 可读 |
| Heartbeat | 无 `HEARTBEAT_TIMEOUT`；如有，日志必须有 `elapsed`、reason、event-loop lag 和最终收口证据 |
| 数据发布 | 已采集 valid 达人有快照；精选/封面正确关联；不完整项标记 `NOT_ATTEMPTED`，不伪造 |
| 幂等 | 重复收口/重试不产生重复快照；`creator_snapshots` 与 `task_creators.latest_snapshot_id` 一致 |
| 性能 | 记录 `slow database operation`、`module collected`、`featured collected`、`featured covers`；对比单达人耗时与 DB 等待 |
| 租约/generation | 取消/重试后旧 Worker 不覆盖新 Worker；`LEASE_LOST`/`GENERATION_FENCED` 可诊断 |
| F10 | 若自然触发，确认 takeover/challenge 恢复不被本轮修改影响 |
| 筛选/有效性 | 不因性能修复改变筛选条件、valid 阈值或完整度口径 |

### 9.3 性能验收的硬约束

**如果目标是在 10 位达人的任务上恢复“接近本地”的耗时，仅部署本轮代码不够。** 需要二选一（或组合），并先确认：

| 方案 | 内容 | 影响 | 建议 |
|---|---|---|---|
| A. 提升云出口带宽 | 确认腾讯云公网带宽/计费，升级到 ≥10–20 Mbps；或让 Tailscale 走非受限路径 | 运维/费用；不改代码 | **优先验证**；这是最小、最直接恢复原设计效率的方式 |
| B. 结构化 checkpoint 写入 | 把模块观测/历史拆成独立行或服务端 JSONB 增量提交，避免每次 edit 传输完整 checkpoint | Schema/Repository/Engine 改动，需迁移与兼容/回滚方案 | 带宽无法升级时再做；本轮未实施，需单独授权 |
| C. 局部缓存/压缩 | Worker 本地缓存 checkpoint + 压缩传输 | 与“DB 为唯一事实源”的现有约束冲突，恢复/多 Worker 语义复杂 | 不推荐作为首选 |

在方案确认前，**不应**通过延长 heartbeat timeout、增加 retry、减少采集字段或放宽有效性来“通过”验收。

---

## 10. 未完成 / 待确认

1. **未部署**：正式 Worker 仍是 23:05 的旧代码；本轮修复待在授权后部署。
2. **未做真实 `宠物/10` 复验**：需要单独授权；本轮未创建任务。
3. **未读取腾讯云带宽套餐**：无 SSH 权限；链路瓶颈为高置信度，非“已证实套餐值”。
4. **未改结构化 checkpoint**：单次完整 edit 仍是残留瓶颈；是否实施需用户确认。
5. **未验证真实 F10**：run2 `challenge_count=0`；本轮未制造滑块。
6. **第二位达人相关性/筛选**：没有新证据，未修改筛选逻辑；保持原判断“不能仅凭标签判定”。
7. **`valid=true` 与 `profile_complete=0` 的口径差异**：既有业务语义，未修改。
8. **前端**：本轮未改，未复跑前端测试。

---

## 11. 证据索引

- [时序与历史对比](hybrid-performance-diagnosis-2026-10-21/01-timing-comparison.txt)
- [生产 DB 只读延迟探针（JSON）](hybrid-performance-diagnosis-2026-10-21/02-db-latency.json)
- [探针 stderr / slow database 日志](hybrid-performance-diagnosis-2026-10-21/02-db-latency.stderr.txt)
- [本地隔离基线](hybrid-performance-diagnosis-2026-10-21/03-local-baseline.txt)
- [链路/带宽测量](hybrid-performance-diagnosis-2026-10-21/04-link-bandwidth.txt)
- [run2 原始证据](e2e-real-collection-run2-2026-10-20.md)
- [run2 Temporal history](e2e-real-collection-run2-2026-10-20/02-temporal-history.txt)
- [run2 Worker 日志](e2e-real-collection-run2-2026-10-20/03-worker-log.txt)
- [上一轮 heartbeat 修复报告](p1-f10-heartbeat-fix-2026-10-20.md)
- [测试结果](hybrid-performance-diagnosis-2026-10-21/05-tests.txt)
- [生产只读状态](hybrid-performance-diagnosis-2026-10-21/06-state-readonly.txt)
- [后续网络/benchmark 专项验证](perf-verification-2026-10-21.md)
- [真实 checkpoint 收口重放（隔离库）](hybrid-performance-diagnosis-2026-10-21/07-closeout-replay.txt)
