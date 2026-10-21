# 带宽升级评估与单达人性能模型

- 日期：2026-10-21（UTC+08）
- 关联：[PERF-02](../tasks/PERF-02.md)、[PERF-03](../tasks/PERF-03.md)、[PERF-01](../tasks/PERF-01.md)、[E2E-01](../tasks/E2E-01.md)
- 结论：**推荐方案 B：保留当前已验证的 checkpoint/heartbeat 优化 + 腾讯云出口带宽升级。**
  - **10 Mbps 是最低推荐档位**：2.5 MiB checkpoint 场景、8 模块、30 封面、60 s 浏览器基线下，单达人约 **96.6 s**，满足 ≤120 s。
  - **20 Mbps 是更稳妥档位**：同一场景约 **84.4 s**，为页面/F10/重试留出余量；但仅靠带宽仍难以稳定 ≤60 s。
  - **5 Mbps 处于边界**：2.5 MiB 场景约 **121.5 s**，略超 120 s；0.5/1 MiB 场景可满足 ≤120 s。
  - **0.5 Mbps 不满足**：2.5 MiB 场景约 **602 s**；即使 MinIO 读回优化也无法把 DB 145–513 s 压到 120 s 内。
  - **仅升级带宽、不保留代码优化也不够**：旧代码在 20 Mbps、2.5 MiB、8 模块下 DB 就需 **75.6 s**，加浏览器/封面约 144 s，超过 120 s；新代码同场景 DB 15.7 s。
- **未部署、未创建真实采集任务、未修改生产库/Schema/网络、未购买带宽、未 commit/push/merge。**

---

## 1. 腾讯云带宽现状核实

**本轮无法读取腾讯云控制台/API**：没有 SSH、`tccli`、腾讯云 API 凭据或控制台登录权限。因此：

- **不能声称当前套餐是 1 Mbps、5 Mbps 或某个具体计费模式**。
- 只能给出实测“等效云→Mac 出口吞吐约 0.4–0.7 Mbps”以及方向不对称证据。
- 具体套餐、计费方式、升级档位、费用、是否重启、是否可降档，必须在控制台确认。

### 1.1 控制台核对步骤

**如果是 CVM（云服务器）：**

1. 控制台 → 云服务器 CVM → 实例 → 目标实例 ID。
2. 查看“网络与安全”/“公网带宽”：确认是**按带宽计费**还是**按流量计费**，当前公网**出带宽上限**。
3. 操作 → 调整网络/调整带宽：先看价格预览；按带宽计费通常可调整带宽，按流量计费需确认峰值上限和流量单价。
4. 同时看“监控”→“公网出带宽/出流量”：确认当前是否长期打满，是否有其他业务占用。
5. 官方文档：[调整公网计费](https://cloud.tencent.com.cn/document/product/213/10580)。

**如果是轻量应用服务器 Lighthouse：**

1. 控制台 → 轻量应用服务器 → 实例 → 套餐/带宽。
2. 查看当前套餐带宽、月流量包、超出流量计费。
3. 操作 → 升级套餐：确认目标套餐带宽、价格、是否需要重启、是否支持降档/续费周期。
4. 官方文档：[升级实例套餐](https://cloud.tencent.com.cn/document/product/1207/51730)。

**关键成本提示：**

- 当前 Tailscale 是 **direct 119.91.210.100:41641**，走公网 UDP；因此 Tailscale 的 PostgreSQL/MinIO 流量会计入该实例的**公网出方向**。升级带宽也会影响这部分计费/限速。
- 若控制台显示“按流量计费”，升级“峰值带宽”可能不增加固定带宽费，但会增加可突发上限；需看流量单价。
- 若显示“按带宽计费”，10/20 Mbps 的价格通常显著高于 5 Mbps；以控制台价格预览为准。
- **本轮不提供具体金额**，避免用估算冒充实际套餐/计费。费用获取方式：
  - CVM **按带宽计费**：在“调整带宽”页面看目标档位的月价预览；通常按 Mbps 阶梯计价，5/10/20 Mbps 不是线性价格。
  - CVM **按流量计费**：升级峰值带宽可能不改固定带宽费，但按实际公网出流量计费；Tailscale direct 的 DB/MinIO 流量都计入，需看流量单价和当月用量。
  - Lighthouse：升级套餐通常按月差价 + 月流量包；超出流量另计；降档/退订规则以控制台为准。
  - 是否重启：CVM 调整带宽通常不需要重启；Lighthouse 升级套餐/变更网络可能需要重启，按控制台提示。
  - 是否可回退：CVM 一般可在下个计费周期调整；Lighthouse 降档可能仅续费时支持。**以控制台账单/规则为准。**

### 1.2 为什么判断是云出口而非其他

| 证据 | 说明 |
|---|---|
| DB 云→Mac 41–61 KiB/s vs Mac→云 1.5–6.3 MiB/s | 同一路径、同一 RTT，方向严重不对称 |
| MinIO GET 50–122 KiB/s vs PUT 0.7–7.3 MiB/s | 两个不同服务同时出现同样方向差异 |
| 并发下载不扩展、上传扩展 | 共享出口上限，不是单连接慢 |
| PostgreSQL 服务器执行 0.046 ms、无锁/临时文件 | 不是 DB 查询/锁 |
| Tailscale direct，非 relay；RTT 19 ms | 不是 DERP 中继或高延迟 |
| Mac 普通公网下载 0.36–2.9 MiB/s | 不是 Mac 出口总带宽 |

**仍需控制台确认**：实例公网出带宽套餐/限速、CPU/内存/网络监控、是否有其他业务占用。当前结论是**方向已实测证实，具体套餐值待确认**。

---

## 2. 不同带宽下的代码性能（隔离 benchmark）

### 2.1 方法

- 真实 Engine + 真实 PostgreSQL 18.3（本机 Docker，随机 schema）。
- 独立限速代理：云→Mac 按 0.5/5/10/20 Mbps，Mac→云 2–8 MiB/s，单程 1 ms（避免人为限制高带宽）。
- 8 个模块，每模块 100 个字段；target 初始 checkpoint 0.5/1/2.5 MiB；实际 final checkpoint 因模块观测增长到约 **1.32/1.82/3.32 MiB**。
- 无浏览器 Adapter；测的是 DB/传输。
- 0.5 Mbps 只实测了 0.5 MiB 初始场景（1/2.5 MiB 用 5 Mbps 实测字节按带宽线性外推，标注“模型”）。

### 2.2 8 模块 DB 耗时

| 初始 checkpoint | final checkpoint | 0.5 Mbps | 5 Mbps | 10 Mbps | 20 Mbps |
|---:|---:|---:|---:|---:|---:|
| 0.50 MiB | 1.32 MiB | **144.9 s**（实测） | **16.2 s** | **8.9 s** | **5.4 s** |
| 1.00 MiB | 1.82 MiB | **248.6 s**（模型） | **24.9 s** | **13.6 s** | **8.0 s** |
| 2.50 MiB | 3.32 MiB | **513.0 s**（模型） | **51.3 s** | **27.5 s** | **15.7 s** |

对应下行字节（8 模块，含 10 次完整 edit + 小增量）：

| 初始 checkpoint | 下行数据量 |
|---:|---:|
| 0.50 MiB | 9.24 MB |
| 1.00 MiB | 14.48 MB |
| 2.50 MiB | 30.21 MB |

- 10 次完整传输（start + 8 次观测 + end）；每模块边际 1 次完整 edit + 小增量。
- 单次最大 DB 调用：0.5 Mbps **21.7 s**；5 Mbps **2.2–5.7 s**；10 Mbps **1.1–2.9 s**；20 Mbps **0.56–1.55 s**。
- Heartbeat 在 0.5/5/10/20 Mbps 下均保持约 1 s 间隔（benchmark 用 1 s；生产 10 s）；loop lag 从 42 s（0.5）降到 1.4–3.4 s（20）。

### 2.3 旧代码在 20 Mbps 仍不够

| 初始 checkpoint | 旧代码 20 Mbps DB | 新代码 20 Mbps DB |
|---|---:|---:|
| 0.50 MiB | 21.7 s（59 次完整传输） | **5.4 s**（10 次） |
| 2.50 MiB | 75.6 s（178.7 MB 下行） | **15.7 s**（30.2 MB 下行） |

**结论：带宽升级必须与当前 checkpoint 优化组合。** 旧代码在 20 Mbps、2.5 MiB 场景下 DB 已 75.6 s，加浏览器/封面约 144 s，超过 120 s；新代码约 84 s。

---

## 3. 单达人耗时模型（DB + MinIO + 浏览器）

### 3.1 组成

| 组成 | 取值 | 来源 |
|---|---|---|
| DB（8 模块） | 见 2.2 | 隔离 benchmark 实测/模型 |
| MinIO 封面 | 30 个、约 1.3 MiB；固定 PUT/HEAD/DB 8.1 s + 1.3 MiB/带宽 | 生产 MinIO 分阶段实测 + 模型 |
| 浏览器/页面/解析 | **60 s/达人** | 历史本地任务 `381d628b`：2 位达人 active 119.76 s，本地 DB/封面；**当前环境未单独实测** |
| F10 人工等待 | 不计入正常采集 | 单独统计，变量大 |
| 重试 | 不计入正常采集 | 异常单独统计 |

**注意：** 60 s 是历史本地基线，不是当前混合部署的浏览器实测；真实值可能 40–80 s。下面的总耗时是**模型**，不是真实验收。

### 3.2 总耗时（模型）

| 初始 checkpoint | 0.5 Mbps | 5 Mbps | 10 Mbps | 20 Mbps |
|---:|---:|---:|---:|---:|
| 0.50 MiB | 234.3 s | 86.5 s | 78.1 s | 74.0 s |
| 1.00 MiB | 338.0 s | 95.1 s | 82.7 s | 76.7 s |
| 2.50 MiB | 602.4 s | **121.5 s** | **96.6 s** | **84.4 s** |

**结论：**

- **10 Mbps**：2.5 MiB 场景约 **96.6 s/达人**，满足 **≤120 s**；0.5/1 MiB 更快（78–83 s）。
- **20 Mbps**：约 **84.4 s/达人**，满足 ≤120 s，并为页面/F10/重试留余量；但**不足以稳定 ≤60 s**，因为 60 s 浏览器基线本身已占满预算。
- **5 Mbps**：2.5 MiB 约 **121.5 s**，处于 120 s 边界；0.5/1 MiB 可满足（86–95 s）。不建议作为 10 位目标的唯一档位。
- **0.5 Mbps**：2.5 MiB 约 602 s，不满足；即使优化 MinIO 读回也无法解决 DB 的 145–513 s。

### 3.3 ≤60 s 的条件

以 20 Mbps 为例：DB 15.7 s + 封面 8.6 s = 24.3 s；要达到 60 s，浏览器/页面/解析必须 **≤35.7 s**。当前历史基线约 60 s，因此：

- **≤120 s：10 Mbps 可达（模型）；20 Mbps 更稳。**
- **≤60 s：仅靠带宽不够**；需要浏览器/页面时间降到 ~35 s 以下，或进一步把剩余 1 次完整 edit 改为 JSONB 局部更新（可再省约 15 s DB），或减少重复主页加载（DIAG-01 ISSUE-003）。这些属于后续优化，不应在本轮未验证的情况下强行实施。

---

## 4. MinIO 校验优化评估（未实施）

### 4.1 实测阶段

| 环节 | 0.5 Mbps 等效 | 5 Mbps 模型 | 10 Mbps 模型 | 20 Mbps 模型 |
|---|---:|---:|---:|---:|
| 30 封面 PUT/HEAD/DB 固定 | ~8.1 s | ~8.1 s | ~8.1 s | ~8.1 s |
| 30 封面 GET 读回（1.3 MiB） | ~20.8 s | ~2.1 s | ~1.0 s | ~0.5 s |
| 合计（仅 MinIO 部分） | ~28.9 s | ~10.2 s | ~9.1 s | ~8.6 s |

生产实测：PUT 52–140 ms、HEAD 21–48 ms、GET 50–122 KiB/s；真实封面 61,866 B GET 496 ms。  
因此带宽升级后，MinIO 读回不再是主要成本；**10/20 Mbps 下不需要为了性能改媒体校验语义**。

### 4.2 服务端 SHA256 校验可行性（仅探针）

MinIO 实测支持：

- `PUT` 带 `ChecksumSHA256` + `ChecksumAlgorithm=SHA256`：64 KiB 中位数 **48 ms**（普通 PUT 52 ms）。
- `HEAD` 带 `ChecksumMode=ENABLED`：中位数 **22 ms**，返回 `ChecksumSHA256`，与客户端一致；`ContentLength`/`ContentType` 也可校验。
- 临时对象已清理，残留 0。

**影响评估（若采用）：**

- 可把“PUT + HEAD + GET 全量读回”改为“PUT + HEAD 服务端校验和”，省掉云→Mac 的 GET 读回；0.5 Mbps 下 30 封面约省 **18–20 s**。
- 但这是**媒体完整性校验语义变更**：从“读回字节哈希”变为“服务端计算的 SHA256 + 大小/类型/metadata”。MinIO 支持时等价或更强；但需要确认对象存储版本、代理/网关是否透传 checksum、以及历史对象兼容性。
- **本轮未实施**。在 10/20 Mbps 下 GET 仅约 1 s/30 封面，收益很小；不建议为此扩大风险。若坚持 0.5 Mbps，才值得单独评估。

---

## 5. 代码改动与本轮可靠性修复

### 5.1 本轮实际新增/修复

| 文件 | 改动 | 影响 |
|---|---|---|
| `backend/src/xingtu/worker.py` | **修复 TemporalHeartbeat watchdog 缺陷**：先发心跳，再记录 loop 存活；仅 60 s 不可运行才停止。每 attempt 一个 daemon 线程，stop/join。 | 防止 loop 阻塞时心跳被 watchdog 自己延迟；不改变 Temporal 重试/取消/终态语义 |
| `backend/src/xingtu/engine.py` | 模块/精选观测之间加入 `asyncio.sleep(0.001)` | 让 lease 心跳/取消在模块之间运行；不改变采集/字段/完整性 |
| `backend/tests/unit/test_worker_heartbeat.py` | 新增 token 失效、Activity 取消、线程不堆积、collect start/stop、异常 stop、短阻塞仍心跳、永久卡死停止 | 覆盖 heartbeat 生命周期 |
| `backend/tests/integration/test_progress.py` | 新增已释放 lease → `LEASE_LOST` | 覆盖 lease 失效 |
| `scripts/diag/checkpoint_benchmark.py` | 8 模块、0.5/5/10/20 Mbps、0.5/1/2.5 MiB、心跳/loop lag/字节/调用计数 | 可复现性能验证 |
| `scripts/diag/parity_check.py` | 旧/新 Engine 全流程 DB 产物对照 | 证明数据一致 |

**没有改动**：Schema、迁移、筛选规则、字段/模块、快照发布算法、MinIO 校验语义、F10、账号/Profile、生产数据、网络配置。

### 5.2 数据一致性对照

用 `SyntheticAdapter`（1 候选、3 模块、无精选）分别运行旧/新 `Engine.run()`，包含搜索、采集、`finish` 和快照发布，比较：

- task 状态/计数/失败原因；
- candidate 状态/模块/字段 status/value/collections；
- task_creators、creator_snapshots、featured counts；
- snapshot payload 的模块/字段/完整性字段（排除 UUID/时间/版本）。

**结果：`PARITY True`**（旧/新完全一致）。证据：[10-parity.txt](perf-verification-2026-10-21/10-parity.txt)。

### 5.3 回归测试

- 单元 **352 passed**
- 契约 **33 passed**
- 隔离 PostgreSQL 集成 **103 passed, 3 skipped**（含本地 MinIO `test_s3_covers.py` 1 passed）
- mypy **Success 34 files**
- ruff check/format **通过 92 files**
- 旧/新数据 parity：**True**
- MinIO checksum 探针：**支持/通过**（未改生产代码）

未执行：真实 Temporal 服务器端到端 cancel/timeout、真实 `宠物/10`、F10 真实触发、真实 30 封面在 5/10/20 Mbps 下的端到端（当前为模型）。

---

## 6. 推荐方案与决策

### 6.1 A/B/C 方案对比

| 方案 | 实测/模型结果 | 结论 |
|---|---|---|
| **A. 只升级带宽** | 旧代码 20 Mbps、2.5 MiB、8 模块 DB 75.6 s，加浏览器/封面约 **144 s** >120；10 Mbps 更差 | **不采用**；带宽 alone 不足以覆盖 10 位任务的 checkpoint 增长 |
| **B. 现有代码优化 + 带宽** | 新代码 10 Mbps/2.5 MiB 约 **96.6 s**；20 Mbps 约 **84.4 s** | **推荐**；满足 ≤120，稳定性/维护成本最低 |
| **C. 追加局部代码优化** | JSONB 局部更新原型 5.5–7.8 ms/模块，估算 2.5 MiB 每模块 27.7 s→0.2–0.3 s；MinIO checksum 可省 0.5 Mbps 下约 18–20 s | 仅在 ≤60 为硬目标/无法升级带宽时考虑；本轮不实施高风险改造 |

**方案 B：当前 checkpoint/heartbeat 优化 + 腾讯云出口带宽升级。**

- **最低档：10 Mbps**。2.5 MiB 场景模型 ~96.6 s/达人，满足 ≤120 s；0.5/1 MiB 78–83 s。
- **推荐档：20 Mbps**。2.5 MiB 场景 ~84.4 s，给页面/F10/重试留余量；但 ≤60 s 仍不保证。
- **不建议 5 Mbps 作为唯一档**：2.5 MiB 约 121.5 s，边界；0.5 Mbps 明确不达标。
- **不建议只升级带宽、不保留代码优化**：旧代码 20 Mbps/2.5 MiB 已 75.6 s DB，总计约 144 s >120。
- **不建议本轮继续做高风险持久化改造**：10 Mbps 已可达 ≤120；JSONB 局部更新/媒体校验语义变更留作 ≤60 或带宽不可升级时的备选。

### 6.2 需要你决策

1. **确认控制台套餐/计费**：当前实例是 CVM 还是 Lighthouse？公网出带宽/流量计费？当前是否被限速/其他业务占用？这决定升级路径和费用。
2. **批准带宽档位**：建议 **10 Mbps 起，20 Mbps 优先**。具体价格需控制台预览；本轮不购买、不变更网络。
3. **是否把 ≤60 s 作为硬目标**：
   - 若 ≤120 s 即可：10 Mbps + 当前代码，GO。
   - 若必须 ≤60 s：20 Mbps 仍可能 74–85 s；需要额外优化浏览器/页面或 JSONB 局部更新，建议另立任务，不本轮扩大范围。
4. **是否批准 MinIO checksum 语义变更**：仅在坚持低带宽或想进一步省 0.5 Mbps 下的封面上传时间时考虑；10/20 Mbps 下收益很小，不建议现在改。
5. **是否批准部署 + 一次真实 `宠物/10`**：见 §7。

### 6.3 预计单达人耗时

| 档位 | 0.5 MiB 初始 | 1 MiB 初始 | 2.5 MiB 初始 | ≤120 | ≤60 |
|---|---:|---:|---:|---|---|
| 0.5 Mbps | 234 s | 338 s | 602 s | 否 | 否 |
| 5 Mbps | 86.5 s | 95.1 s | 121.5 s | 2.5 MiB 边界 | 否 |
| 10 Mbps | 78.1 s | 82.7 s | 96.6 s | **是** | 否 |
| 20 Mbps | 74.0 s | 76.7 s | 84.4 s | **是** | 否（需浏览器 ≤35 s） |

> 以上为模型（隔离 benchmark + 历史浏览器基线 + MinIO 阶段实测），不是真实采集验收。最终以授权后的真实 `宠物/10` 为准。

---

## 7. 部署与真实验收计划（待授权）

### 7.1 带宽升级

1. 你确认控制台当前套餐/计费/费用后，选择 10 或 20 Mbps 出方向。
2. 若控制台支持“调整带宽”且不需重启：直接调整，观察公网出带宽监控。
3. 若 Lighthouse 需升级套餐/重启：安排在无任务窗口，重启后验证 Tailscale/PostgreSQL/Temporal/MinIO 连通。
4. 升级后复跑只读探针：`scripts/diag/hybrid_db_latency.py`，确认 DB/MinIO 云→Mac 吞吐达到预期（10 Mbps ≈1.25 MiB/s；20 Mbps ≈2.5 MiB/s）。
5. 不修改安全组/Tailscale ACL/账号/Profile。

### 7.2 代码部署

- 备份当前 4 个 Python 文件（worker/engine/repository/browser_host）→ 替换 → 可选 `XINGTU_DB_SLOW_MS=1000`。
- 仅 `launchctl kickstart -k` Mac Worker；无 Schema 迁移、无云端服务重启。
- 回滚：恢复 4 个文件并重启 Worker；不删任务/快照。

### 7.3 真实 `宠物/10`

- 只创建 **1 个**新任务；不重试/取消历史任务（二者已 `CANCELLED`）。
- 监控：`slow database`、`activity event loop stalled`、heartbeat failed、`LEASE_LOST`、root 终态、快照/精选、重复发布、generation fence。
- 验收：单达人 ≤120 s（10 Mbps 预期 ~96 s；20 Mbps ~84 s）；10 位总时长约 16–25 min（模型，含搜索/封面/队列）；≤60 s 不作为本次硬指标。
- 中止：lease 失效、heartbeat timeout、10 分钟无进度、root 非预期状态、发布异常。
- F10 若触发：单独记录人工等待，不计入正常采集耗时。

---

## 8. 残余风险

| 风险 | 说明 | 缓解 |
|---|---|---|
| 浏览器基线不确定 | 60 s 来自历史本地任务，不是当前环境实测 | 真实任务记录 `module collected`/页面耗时；若 >80 s，10 Mbps 也可能超 120 |
| 单次完整 edit 仍阻塞 loop | 0.5–3.3 MiB 下 0.56–21.7 s | 心跳线程独立；lease TTL 120 s；模块间 1 ms yield；若更大 checkpoint 需局部更新 |
| 5 Mbps 边界 | 2.5 MiB 模型 121.5 s | 选 10 Mbps 起 |
| MinIO 读回 | 0.5 Mbps 下 30 封面 ~29 s | 带宽升级后 ~9–10 s；不建议为性能改校验语义 |
| 云套餐/费用未知 | 无控制台权限 | 先确认套餐/计费/价格，再购买 |
| F10 未真实触发 | 本轮未测 | 保持现有 F10 逻辑；真实任务单独记录 |
| Temporal 真实 cancel/timeout | 仅 ActivityEnvironment + 历史证据 | 部署后监控；不重试历史任务 |
| 数据一致性 | 旧/新 synthetic parity True | 真实任务仍以快照/精选/去重核对 |

---

## 9. 证据索引

- [网络路径与延迟](perf-verification-2026-10-21/01-network-path.txt)
- [PostgreSQL 内部/锁/配置](perf-verification-2026-10-21/02-db-internals.txt)
- [DB 双向吞吐](perf-verification-2026-10-21/03-db-throughput.txt)
- [MinIO 分阶段](perf-verification-2026-10-21/04-minio-phases.txt)
- [JSONB 局部更新原型](perf-verification-2026-10-21/05-partial-update-prototype.txt)
- [并发扩展](perf-verification-2026-10-21/06-concurrency.txt)
- [测试结果](perf-verification-2026-10-21/07-tests.txt)
- [带宽模型](perf-verification-2026-10-21/12-bandwidth-model.txt)
- [8 模块/带宽原始 JSON](perf-verification-2026-10-21/bench-bandwidth/)
- [旧/新数据 parity](perf-verification-2026-10-21/10-parity.txt)
- [MinIO checksum 探针](perf-verification-2026-10-21/11-minio-checksum.txt)
- [生产只读状态](perf-verification-2026-10-21/09-production-state.txt)
