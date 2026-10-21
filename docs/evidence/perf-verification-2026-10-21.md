# 混合部署网络瓶颈与 checkpoint 优化专项验证

- 日期：2026-10-21（UTC+08）
- 关联：[PERF-01](../tasks/PERF-01.md)、[PERF-02](../tasks/PERF-02.md)、[P1FIX-02](../tasks/P1FIX-02.md)、[E2E-01](../tasks/E2E-01.md)
- 结论：**主瓶颈实测证实为云端→Mac 方向出口带宽（约 0.4–0.7 Mbps），不是 Tailscale 中继、不是 Mac 网络、不是 PostgreSQL 慢查询/锁、不是数据库访问模式本身。**
- 当前 checkpoint 优化在隔离测试中把单模块完整传输 **10 → 3 次**（边际 **7 → 1**），下行字节约 **−70%**，单模块耗时约 **−66%–69%**；但剩余 1 次完整 edit 仍是 5.6–27.7 s/模块的主要残项。
- **未部署、未创建真实采集任务、未修改生产业务库/Schema/网络、未 commit/push/merge。** 验证后生产只读复核：最近 120 分钟新增 root task=0；两个历史任务仍 `CANCELLED`；Worker 仍 PID 20406 运行部署时代码。
- **建议 GO（受控验证部署 + 一次真实 `宠物/10`）**，前提是接受当前网速下约 30–60 分钟的 10 位任务；若要求接近本地速度，应先升级云出口带宽或另行批准无 Schema 的局部 JSONB 更新。

---

## 1. 网络瓶颈：实测与归因

### 1.1 连接类型与延迟

| 项目 | 实测 |
|---|---|
| Tailscale 路径 | `active; direct 119.91.210.100:41641`，`tailscale ping` 首个 pong 即 `via 119.91.210.100:41641`；**非 DERP/relay** |
| Tailscale JSON | `CurAddr=119.91.210.100:41641`，`Relay=tor` 只是 home DERP 标记，不是当前数据路径 |
| Tailscale RTT | 18–20 ms |
| ICMP | 20 包收到 18，10% 丢包；RTT 18.0/18.7/20.0 ms（min/avg/max） |
| TCP connect（50 次） | 5432/7233/9000 均 50/50 成功；中位数 19.3/19.4/19.3 ms；p95 约 60–61 ms；最大 805–820 ms（5432/7233 各一次） |

**判断：** 链路是 direct，RTT 稳定；存在偶发 ~0.8 s 建连尖峰和 ICMP 丢包，但 TCP 连接无失败，不是本轮 40–60 KiB/s 吞吐的主因。

### 1.2 双向吞吐（关键证据）

同一 Tailscale 路径、同一 PostgreSQL/MinIO、同一时段：

| 操作 | 方向 | 实测 |
|---|---|---|
| PostgreSQL 128 KiB 文本 | 云 → Mac | 2.22–2.54 s，**53.8 KiB/s** |
| PostgreSQL 512 KiB 文本 | 云 → Mac | 8.33–8.52 s，**60.8 KiB/s** |
| PostgreSQL 1 MiB 文本 | 云 → Mac | 20.7–21.8 s，**48.2 KiB/s** |
| PostgreSQL 2.5 MiB 文本 | 云 → Mac | 46.0–78.1 s，**41.3 KiB/s** |
| PostgreSQL 128 KiB 参数 | Mac → 云 | 0.08–0.09 s，**1,463 KiB/s** |
| PostgreSQL 512 KiB 参数 | Mac → 云 | 0.15–0.18 s，**3,136 KiB/s** |
| PostgreSQL 1 MiB 参数 | Mac → 云 | 0.18–0.97 s，**1,771 KiB/s** |
| PostgreSQL 2.5 MiB 参数 | Mac → 云 | 0.36–0.46 s，**6,256 KiB/s** |
| MinIO PUT 64 KiB–1 MiB | Mac → 云 | **730–7,299 KiB/s** |
| MinIO HEAD | 往返 | 21–48 ms |
| MinIO DELETE | 往返 | 23–25 ms |
| MinIO GET 64 KiB | 云 → Mac | 640 ms，**100.0 KiB/s** |
| MinIO GET 256 KiB | 云 → Mac | 3,503 ms，**73.1 KiB/s** |
| MinIO GET 512 KiB | 云 → Mac | 10,214 ms，**50.1 KiB/s** |
| MinIO GET 1 MiB | 云 → Mac | 18,097 ms，**56.6 KiB/s** |
| 真实封面 61,866 B（`b5a01709`） | 云 → Mac | HEAD 48 ms，GET 496 ms，**121.8 KiB/s** |

**判断：** 同一路径的 **上传（Mac→云）是 0.7–7.3 MiB/s，下载（云→Mac）只有 40–122 KiB/s**。这不是 Mac 出口问题（Mac 普通公网下载 0.36–2.9 MiB/s），不是 RTT 问题（19 ms），也不是数据库查询问题（见 1.3）。最符合 **腾讯云公网出方向带宽上限/整形**；Tailscale 直连本身不解释该单向不对称。

### 1.3 并发是否提升总吞吐

| 场景 | 并发 1 | 并发 2 | 并发 4 | 并发 8 |
|---|---:|---:|---:|---:|
| DB 下载 128 KiB（总 KiB/s） | 42.0 | 81.8 | 74.5 | 70.4 |
| DB 下载 512 KiB（总 KiB/s） | 53.9 | 67.3 | 71.8 | 61.8 |
| DB 上传 512 KiB（总 KiB/s） | 1,621.7 | 1,898.3 | 2,464.1 | 5,193.0 |
| MinIO GET 60 KiB（总 KiB/s） | 79.5 | 80.9 | 108.4 | 98.1 |

**判断：** 下载方向总吞吐不随并发提升，稳定在约 40–108 KiB/s；上传方向随并发提升到 5 MiB/s。**共享出口上限在云→Mac 方向**，不是单连接慢。MinIO 与 PostgreSQL 同时受限，说明是链路/出口层，而不是某个服务的连接池。

### 1.4 PostgreSQL 内部：不是慢查询/锁/连接池

| 项目 | 实测 |
|---|---|
| `EXPLAIN (ANALYZE, BUFFERS)` 读取完整 checkpoint | **Execution Time 0.046 ms**，Planning 0.099 ms；Seq Scan 7 行；shared hit 5，read 0 |
| 服务器版本/配置 | PostgreSQL 18.3；`max_connections=100`；`shared_buffers=128MB`；`work_mem=4MB` |
| 连接 | 11 个连接，`max_connections=100`；当前无连接池（每次操作新建连接） |
| 锁 | 无未授予锁；无 `locktype=transactionid` 等待；`deadlocks=0` |
| 临时文件 | `temp_files=0`，`temp_bytes=0` |
| 表更新 | `task_checkpoints` 7 行、`root_tasks` 4 行；`task_checkpoints` seq_scan 2,135，`n_tup_upd=328`；小表扫描不是瓶颈 |
| 缓存 | `blks_hit=39,434,450`，`blks_read=1,492`，命中率约 99.996% |
| 客户端完整 `Repository.get()` | 7.7–8.3 s（生产只读），而服务器执行 0.046 ms |

**判断：** **99.99% 的 `Repository.get()` 时间在传输，不在 SQL。** 没有慢查询、锁等待、临时文件或连接池耗尽。每次新建连接约 160 ms 是次要成本（约 2–3%），不是主因。

### 1.5 云服务器运行时利用率

- **无法读取**：当前只有 Tailscale/DB/MinIO 访问，没有 SSH、`tccli`、腾讯云 API 凭据或控制台权限；无法读取 CVM/Lighthouse 的带宽套餐、CPU、内存、出方向流量曲线。
- **可排除的部分**：DB 服务器执行 0.046 ms、无锁/临时文件；MinIO PUT/HEAD 快速；同一云主机对上传方向可达 5–7 MiB/s。因此“云主机 CPU/内存被单个查询打满”与本轮证据不符。
- **仍需控制台补证**：出方向带宽套餐、是否被限速、是否有其他业务占用出流量、CPU steal/内存压力。**在未读取控制台前，不把“具体套餐值”写成已证实；只把“云→Mac 出口受限”写成高置信度。**

### 1.6 MinIO 各环节

| 环节 | 实测 | 结论 |
|---|---|---|
| PUT | 64 KiB 88 ms；256 KiB 95 ms；512 KiB 97 ms；1 MiB 140 ms | 上传快，不是瓶颈 |
| HEAD | 21–48 ms | 元数据校验快 |
| GET（读回校验） | 64 KiB 640 ms；256 KiB 3.5 s；512 KiB 10.2 s；1 MiB 18.1 s | **读回校验是主要成本** |
| DELETE | 23–25 ms | 快 |
| 真实封面 61.9 KiB | GET 496 ms | 与 30 个封面 68 s 的量级一致 |

**判断：** 当前 `CoverPipeline` 的“写入后读回校验”是数据完整性要求，不能删除；它把云→Mac 的 40–120 KiB/s 上限直接带入 creation 模块。30 个封面约 1.3 MB，仅读回就约 20–30 s，加上每封面 HEAD/DB/请求开销，首个达人 68 s 可解释。

---

## 2. 当前代码优化的真实收益（隔离测试）

### 2.1 方法

- **真实 Engine**：`old` 使用部署基线 `.runtime/backups/p1fix-02-20261020/current/` 的 `engine.py`/`repository.py`；`new` 使用当前工作区代码。
- **真实 PostgreSQL 18.3**：本机 Docker，随机 schema；不接触生产库。
- **限速代理**：独立进程，云→Mac **100 KiB/s**、Mac→云 **2 MiB/s**、单程 10 ms；模拟生产的不对称链路。100 KiB/s 高于生产实测 40–61 KiB/s，因此**绝对耗时偏乐观**；传输次数、字节数和相对比例不受影响。
- **无浏览器 Adapter**：只执行 1 个 `basic` 模块，排除 Playwright 变量；测的是 DB/传输。
- **规模**：checkpoint 文本 **0.5 / 1.0 / 2.5 MiB**；每个版本、每个规模 1 次。
- **隔离**：旧路径在 2.5 MiB 超过真实 120 s lease TTL，首次运行 `LEASE_LOST`；为测 DB 路径，把隔离库 lease 延长到 2 h（输出 `lease_ttl_extended=true`）。这本身是旧路径的真实缺陷证据。

### 2.2 结果

| checkpoint | 版本 | 完整传输 | 下行 MiB | 上行 MiB | 总耗时 s | DB 等待 s | 单次最大调用 s | 心跳数 | 心跳最大间隔 s |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.50 MiB | old | 10 | 5.03 | 3.53 | 54.69 | 54.52 | 5.65 | 0 | — |
| 0.50 MiB | new | **3** | **1.52** | **1.52** | **18.38** | **17.87** | 5.64 | 19 | **1.006** |
| 1.00 MiB | old | 10 | 10.03 | 7.03 | 108.45 | 108.28 | 11.13 | 0 | — |
| 1.00 MiB | new | **3** | **3.02** | **3.02** | **34.85** | **34.33** | 11.12 | 35 | **1.005** |
| 2.50 MiB | old | 10 | 25.03 | 17.53 | 270.36 | 270.18 | 27.68 | 0 | — |
| 2.50 MiB | new | **3** | **7.52** | **7.52** | **84.64** | **84.09** | 27.70 | 85 | **1.010** |

**改善比例：**

- 单模块总耗时：**−66.4% / −67.9% / −68.7%**（0.5 / 1 / 2.5 MiB）。
- 完整传输：**10 → 3**（−70%）；边际每模块 **7 → 1**（−85.7%）。
- 下行字节：**−69.8% / −69.9% / −69.9%**；上行字节：**−56.9% / −57.1% / −57.2%**。
- 8 模块模型：**59 → 10 次完整传输**（−83%），DB 传输时间约 **5.9×** 更少；实际总耗时还受 covers/页面影响，不能直接乘。
- **单次完整 edit 的成本没有下降**：old/new 的 `max_single_db_call` 都是 5.65/11.13/27.68 s。这是剩余的主要瓶颈。
- `module_seconds` 从 5.31/10.43/25.81 s 降到 0.17/0.17/0.19 s，但**口径不完全可比**：旧值包含模块 `finally` 的全量 `module_seconds` edit；新值改为小增量，观测落库的全量 edit 本来就在模块计时之外。不要把它当作端到端提升比例。

### 2.3 Event Loop 与 Heartbeat

| checkpoint | 版本 | loop lag 最大 s | 心跳数 | 心跳最大间隔 s |
|---:|---|---:|---:|---:|
| 0.50 MiB | old | 54.70 | 0（旧代码无独立线程） | — |
| 0.50 MiB | new | 12.62 | 19 | 1.006 |
| 1.00 MiB | old | 108.45 | 0 | — |
| 1.00 MiB | new | 23.60 | 35 | 1.005 |
| 2.50 MiB | old | 270.37 | 0 | — |
| 2.50 MiB | new | 56.84 | 85 | 1.010 |

- **Temporal heartbeat 线程在 loop 被阻塞时仍按约 1 s 发送**（benchmark 用 1 s 间隔；生产 10 s）；这验证了独立线程有效。
- **loop 仍会被单次完整 edit 阻塞 5.6–27.7 s**；新代码把 loop 阻塞总时长降低约 3–5×，但没有消除。异步 lease 心跳/取消在单次 edit 期间仍可能被延迟；当前 lease TTL 120 s，单次 edit 27.7 s 尚可，但更大 checkpoint 会接近/超过 TTL。
- 已在模块之间加入 `asyncio.sleep(0.001)`，让 lease 心跳/取消在模块之间获得执行机会；这不会改变采集/数据语义，但**不能**拆分单次同步 `edit`。
- 旧路径在 2.5 MiB 单模块就超过 120 s lease TTL；**这是旧代码在真实链路上的硬失败**，不只是“慢”。

### 2.4 剩余 1 次 edit 的无 Schema 优化评估

在隔离 PostgreSQL 上对真实 JSONB 结构做**服务端局部更新**原型（不修改表结构）：

| checkpoint | 候选索引扫描 | 局部更新（32 KiB observation） |
|---:|---:|---:|
| ~0.5 MiB | 0.5 ms | 5.5 ms |
| ~1.0 MiB | 0.4 ms | 6.3 ms |
| ~2.5 MiB | 0.7 ms | 7.8 ms |

- 网络只需上传约 32 KiB observation + 小响应，而不是 0.5–2.5 MiB 的完整 checkpoint 下行+上行。
- 按实测单价估算：2.5 MiB 下每模块从 **27.7 s → 约 0.2–0.3 s**；8 模块从 222 s → 约 2 s。**但 start/end 的 2 次完整 edit 和 covers 仍在**（约 55 s + 60 s/达人）。
- **可行性：** 不需要 Schema 迁移，保留现有 JSONB 结构；但要把 `_collect_once` 的观测提交、basic 阈值、`valid_count`、`persist_creators`、幂等去重都改成服务端局部更新路径，属于核心数据路径改动，**不是一行改动**。
- **本轮未实现**，避免扩大范围；如要追求接近本地速度，建议单独立项并配完整回归。若只需一次真实 `宠物/10` 验收，当前 7→1 的优化已足够先验证正确性。

---

## 3. Heartbeat 实现验证

### 3.1 发现并修复的缺陷

上一版 `TemporalHeartbeat._loop_responsive()` **先等待 loop 执行一个回调，再发送心跳**。在 loop 被完整 edit 阻塞 5.6–27.7 s 时，心跳线程会一起等待，等于把心跳重新绑回 loop，违背独立线程的目的。

修复（`worker.py`）：

- **先发送 `activity.heartbeat()`**；
- 再用 `loop.call_soon_threadsafe(self._mark_loop_alive)` 记录 loop 最近一次可运行时间；
- 仅当 loop 连续不可运行超过 **60 s** 时停止心跳（让 Temporal 自己的 45 s timeout 接管）；
- `stop()` 设置 Event 并 join 5 s；每个 attempt 最多一个 daemon 线程。

### 3.2 已验证

| 场景 | 结果 |
|---|---|
| Activity context 传递 | `ActivityEnvironment` + `contextvars.copy_context()`；on_heartbeat 收到 `("root",)` |
| 启动即发送 | 首个心跳在 interval 前发送 |
| 正常完成 | `collect()` finally `stop()`；测试断言 start/stop 顺序 |
| 失败/异常 | `collect()` 抛异常时仍 stop；测试覆盖 |
| 取消 | `ActivityEnvironment.cancel()` 后 body finally stop，任务结束；无线程残留 |
| 过期 Activity/token 失效 | `activity.heartbeat` 抛错线程退出；测试覆盖 |
| Event loop 阻塞 < watchdog | 0.2 s 阻塞期间仍发送 ≥5 次心跳；测试覆盖 |
| Event loop 永久卡死 > watchdog | 0.25 s 阻塞 + 0.03 s watchdog：心跳停止（≤10 次），让 Temporal 超时 |
| 线程堆积/竞态 | 20 次 start/stop 后无存活 `temporal-activity-heartbeat` 线程 |
| generation/lease 失效 | 已释放 lease 的 `heartbeat` 返回 `LEASE_LOST`；stale generation/attempt/version 的 `record_progress` 全部拒绝 |
| 任务终态 | `not_found`/`timed_out` 最后 attempt 收口；`worker_shutdown`/`cancel_requested`/`paused`/`reset` 不收口；真实 run2 checkpoint 收口重放（上一轮）生成 2 快照/2 精选/8 卡片且幂等 |

**未验证：** 真实 Temporal 服务器的 Activity heartbeat timeout/cancel 端到端（本轮用 `ActivityEnvironment` + 生产历史 `not_found` 证据；未启动独立 Temporal 测试服务器）。

---

## 4. 决策回答

### 4.1 采集变慢的主要瓶颈是否得到实测证实？

**是，已证实到“方向”层级：**

- 云→Mac 下载 40–122 KiB/s；Mac→云上传 0.7–7.3 MiB/s；同路径、同 RTT、同服务。
- 并发下载不提升总吞吐；并发上传显著提升。
- PostgreSQL 服务器执行 0.046 ms；无锁/临时文件/慢查询。
- Tailscale 是 direct，不是 relay；Mac 普通公网下载正常。
- **结论：云端→Mac 方向的出口带宽/整形是主瓶颈。** 具体腾讯云套餐值未能读取（无 SSH/API/控制台权限），属高置信度而非“已读取配置”。

### 4.2 已实现的 checkpoint 优化预计解决多大比例？

- **已实测（隔离、限速、真实 Engine）**：单模块完整传输 **10 → 3**，下行字节 **−70%**，单模块耗时 **−66%–69%**；边际每模块 **7 → 1**。
- **已实测（模型）**：8 模块完整传输 **59 → 10**（−83%），DB 传输时间约 **5.9×** 更少。
- **未被实际验证**：真实 `宠物/10` 的端到端耗时（本轮未创建任务）；covers/页面/F10 未纳入隔离 benchmark。
- **未解决**：剩余 1 次完整 edit 仍是 5.6–27.7 s/模块；`start`/`end` 和 covers 仍在。

### 4.3 是否需要升级腾讯云带宽？

- **如果目标是“接近本地速度”或让 10 位任务在几分钟级完成：需要，方向是云服务器公网出方向（上行/egress）带宽。**
  - 当前云→Mac 约 0.4–0.7 Mbps；要把 2.5 MiB checkpoint 单次传输压到 ~1 s，需要约 **20 Mbps** 出方向；至少 **10 Mbps** 才有明显改善。
  - 证据：方向不对称、并发不扩展、服务器执行 0.046 ms、MinIO 与 PG 同时受限。
  - 腾讯云控制台需确认：实例/带宽包的公网**出带宽**、是否被限速、是否有其他业务占用、CPU/内存/网络监控。
- **如果目标只是“完成一次真实 `宠物/10` 正确性验收”：不必先升级。** 当前优化预计 30–60 分钟可完成（需实测），可作为受控验证；但不要把它当作性能达标。

**不要在没有控制台证据前直接采购**；先确认套餐/限速/监控，再按 10–20 Mbps 出方向评估。

### 4.4 是否存在不修改 Schema 的进一步优化空间？

**有，且已测量：** 服务端 JSONB 局部更新。0.5–2.5 MiB checkpoint 上，32 KiB observation 的局部更新约 **5.5–7.8 ms**；网络从 2.5 MiB 下行+上行降到约 32 KiB 上行。估算 2.5 MiB 每模块 **27.7 s → 0.2–0.3 s**。不需要 Schema 迁移，但需要改 `_collect_once` 的观测提交/basic 阈值/`persist_creators`/幂等路径，属于核心数据路径改动，建议单独立项；本轮未实现。

次要项：复用 PostgreSQL 连接（每次新建约 160 ms，占 2–3%）、避免 start/end 全量 edit（同一局部更新思路）。这些都不解决“云出口”本身，但能进一步减少字节。

### 4.5 本轮 heartbeat 与终态修复是否安全？

- **代码/隔离测试层面：安全。** 352 单元、33 契约、103 集成（3 skipped）、mypy/ruff 通过；线程生命周期、取消、token 失效、loop 阻塞、watchdog、线程堆积、lease/generation 失效均有测试。
- **发现并修复了一个真实缺陷**：上一版 watchdog 会在阻塞时延迟心跳；已改为先发心跳、仅 60 s 不可运行才停。
- **残余风险**：单次同步 `edit` 仍可阻塞 loop 5.6–27.7 s；异步 lease 心跳/取消可能被延迟，但 lease TTL 120 s 目前有余量；更大 checkpoint 会逼近 TTL。未做真实 Temporal 服务器端到端 cancel 测试；真实部署后需监控 `activity event loop stalled`、`slow database`、`HEARTBEAT_TIMEOUT`、`LEASE_LOST`。

### 4.6 当前是否具备部署并做一次真实「宠物/10」验证？

**GO（受控验证部署）**，不是无条件生产上线。

满足条件：

1. 只替换 4 个 Python 文件（`worker.py`、`engine.py`、`repository.py`、`browser_host.py`），无 Schema 迁移、无云端改动；部署前备份，回滚只回滚代码。
2. 仅 `launchctl kickstart -k` Mac Worker；确认无活动 lease/浏览器；不重试/取消历史任务（二者已是 `CANCELLED`）。
3. 只创建 **1 个**新 `宠物/10`；不创建第二个、不访问历史任务。
4. 监控：`slow database operation`、`activity event loop stalled`、`activity heartbeat failed`、`LEASE_LOST`、`root_task` 终态、`creator_snapshots`/`featured_collections`、重复快照、generation fence。
5. 预期：正确性可验收；速度仍受云出口限制，10 位可能 30–60 分钟；不要以“恢复到本地速度”为本次 GO 条件。
6. 中止条件：lease 失效、heartbeat timeout、10 分钟无新达人/无进度、root_task 非预期状态、发布异常；保留证据，不自动重试。

**如果验收目标是“速度必须接近本地”，则 NO-GO**，先做云出口带宽升级或批准 JSONB 局部更新。

---

## 5. 证据索引

- [网络路径与延迟](perf-verification-2026-10-21/01-network-path.txt)
- [PostgreSQL 内部/慢查询/锁/配置](perf-verification-2026-10-21/02-db-internals.txt)
- [DB 双向吞吐矩阵](perf-verification-2026-10-21/03-db-throughput.txt)
- [MinIO 上传/HEAD/读回/删除](perf-verification-2026-10-21/04-minio-phases.txt)
- [JSONB 局部更新原型](perf-verification-2026-10-21/05-partial-update-prototype.txt)
- [DB/MinIO 并发扩展](perf-verification-2026-10-21/06-concurrency.txt)
- [测试结果](perf-verification-2026-10-21/07-tests.txt)
- [Benchmark 汇总](perf-verification-2026-10-21/08-benchmark-summary.txt)
- [Benchmark 原始 JSON](perf-verification-2026-10-21/bench/)
- [验证后生产只读状态](perf-verification-2026-10-21/09-production-state.txt)
- [上一轮诊断与修复报告](hybrid-performance-diagnosis-2026-10-21.md)
