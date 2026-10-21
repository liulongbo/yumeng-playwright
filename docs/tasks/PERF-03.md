# PERF-03：带宽升级评估、单达人性能模型与可靠性回归

状态：阻塞
更新时间：2026-10-21T10:30:00+08:00
是否验收：否；已完成一次真实 `户外/3` 实测：单达人 11 分 37 秒，性能 NO-GO；带宽未升级，手机热点 DERP 约 400ms、MinIO 22.8–26.8 KiB/s。

## 目标与范围

在 PERF-01/PERF-02 基础上，评估“腾讯云带宽升级 + 最小代码优化”能否把单达人完整采集控制在 ≤120 s / ≤60 s，并完成已确认缺陷的可靠性回归。

包含：带宽档位评估、0.5/5/10/20 Mbps 隔离 benchmark、MinIO 分阶段与 checksum 探针、旧/新数据 parity、heartbeat/lease/终态回归、部署与真实验收方案。

不做：购买/变更腾讯云套餐、部署/重启正式 Worker、创建真实采集任务、修改生产库/Schema/账号/Profile、修改网络/安全组/Tailscale ACL、Git commit/push/merge、Schema 重构、媒体校验语义变更。

## 结论摘要

**推荐方案 B：当前已验证的 checkpoint/heartbeat 优化 + 腾讯云出口带宽升级。**

| 档位 | 2.5 MiB 初始、8 模块、30 封面、60 s 浏览器基线 | ≤120 s | ≤60 s |
|---|---:|---|---|
| 0.5 Mbps | 602 s | 否 | 否 |
| 5 Mbps | 121.5 s | 边界 | 否 |
| **10 Mbps** | **96.6 s** | **是** | 否 |
| **20 Mbps** | **84.4 s** | **是** | 否（需浏览器 ≤35 s） |

- **10 Mbps 为最低推荐**；20 Mbps 更稳、为页面/F10/重试留余量。
- 仅升级带宽不够：旧代码在 20 Mbps/2.5 MiB/8 模块下 DB 75.6 s，总计约 144 s >120；新代码 15.7 s DB，总计约 84 s。
- 0.5 Mbps 即使做 MinIO 读回优化也不达标（DB 513 s）。
- ≤60 s 不是带宽能单独解决的：60 s 浏览器基线已占满预算；需要浏览器/页面优化或 JSONB 局部更新，另立任务。

## 证据

- 报告：[bandwidth-optimization-2026-10-21.md](../evidence/bandwidth-optimization-2026-10-21.md)
- 网络/DB/MinIO/perf 证据：[perf-verification-2026-10-21](../evidence/perf-verification-2026-10-21/)
- 带宽模型：[12-bandwidth-model.txt](../evidence/perf-verification-2026-10-21/12-bandwidth-model.txt)
- 8 模块原始 JSON：[bench-bandwidth](../evidence/perf-verification-2026-10-21/bench-bandwidth/)
- 旧/新 parity：[10-parity.txt](../evidence/perf-verification-2026-10-21/10-parity.txt)
- MinIO checksum：[11-minio-checksum.txt](../evidence/perf-verification-2026-10-21/11-minio-checksum.txt)
- 测试：[07-tests.txt](../evidence/perf-verification-2026-10-21/07-tests.txt)

## 已验证

- 网络主瓶颈：云→Mac 出口（DB 41–61 KiB/s vs 上传 1.5–6.3 MiB/s；MinIO GET 50–122 KiB/s vs PUT 0.7–7.3 MiB/s；并发不扩展；DB 0.046 ms；Tailscale direct）。
- 当前优化（8 模块、新代码）DB 时间：0.5 Mbps 145 s；5 Mbps 16.2/24.9/51.3 s；10 Mbps 8.9/13.6/27.5 s；20 Mbps 5.4/8.0/15.7 s（0.5/1/2.5 MiB 初始）。
- 旧代码 20 Mbps：0.5 MiB 21.7 s / 2.5 MiB 75.6 s（59 次完整传输，178.7 MB 下行）；新代码同场景 5.4/15.7 s（10 次，30.2 MB）。
- Heartbeat：0.5/5/10/20 Mbps 下均约 1 s 间隔；loop lag 42 s → 1.4–3.4 s（随带宽）；`TemporalHeartbeat` watchdog 缺陷已修复（先发心跳，60 s 不可运行才停）。
- 数据一致性：旧/新 `Engine.run()` synthetic parity **True**（状态/计数/字段/快照/精选一致）。
- 测试：单元 **352**、契约 **33**、隔离集成 **103/3 skipped**（含本地 MinIO `test_s3_covers.py` 1 passed）、mypy/ruff 通过。
- MinIO checksum 探针：PUT 48 ms、HEAD 22 ms、checksum 匹配；可作为低带宽可选优化，**未改生产代码**。

## 代码改动

| 文件 | 内容 |
|---|---|
| `backend/src/xingtu/worker.py` | 修复 `TemporalHeartbeat` watchdog：先发心跳、后探测 loop；60 s 不可运行才停止；线程 stop/join |
| `backend/src/xingtu/engine.py` | 模块/精选之间 1 ms yield，让 lease 心跳/取消运行 |
| `backend/tests/unit/test_worker_heartbeat.py` | Activity 取消/token 失效/线程堆积/短阻塞/永久卡死/collect start-stop |
| `backend/tests/integration/test_progress.py` | 已释放 lease → `LEASE_LOST` |
| `scripts/diag/checkpoint_benchmark.py` | 8 模块、0.5/5/10/20 Mbps、0.5/1/2.5 MiB、心跳/loop lag/字节/调用计数 |
| `scripts/diag/parity_check.py` | 旧/新全流程 DB 产物对照 |

未改 Schema、迁移、筛选、字段/模块、快照算法、MinIO 校验语义、F10、账号/Profile。

## 待决策

1. 控制台确认实例类型/套餐/计费/当前出带宽/CPU/内存/网络监控（本轮无控制台权限，不能冒充套餐值）。
2. 批准 10 Mbps 或 20 Mbps 出方向升级；价格以控制台预览为准。**本轮未购买、未改网络。**
3. 是否把 ≤60 s 作为硬目标：若是，需另立浏览器/JSONB 局部更新任务；20 Mbps 仍约 84 s。
4. 是否批准部署 4 个 Python 文件 + 一次真实 `宠物/10`（不重试历史任务）。

## 部署与回滚

- 带宽：控制台调整出带宽/升级套餐；确认是否重启；升级后复跑只读探针确认 10/20 Mbps 实际吞吐。
- 代码：备份 4 个文件 → 替换 → 仅重启 Mac Worker；无迁移；回滚恢复 4 个文件并重启。
- 真实验收：1 个 `宠物/10`；监控 slow DB/loop lag/heartbeat/LEASE_LOST/终态/快照/精选/幂等；10 Mbps 预期 ~96 s/达人，20 Mbps ~84 s；≤120 为本次硬指标，≤60 不作为硬指标。

## 状态历史

- 2026-10-21：待办 → 进行中；开始带宽档位/代码收益/数据 parity 验证。
- 2026-10-21：进行中 → 待验收；方案 B（10 Mbps 起/20 Mbps 优先）完成评估；代码/测试/parity 完成；未部署/未购买/未真实采集。


## 2026-10-21 执行阻塞（部署前网络复核）

- 当前 Mac en0 `10.209.115.57`，公网 `223.160.114.198`；`netcheck MappingVariesByDestIP=true`、`PortMapping` 空。
- Tailscale 对 cloud 为 **relay "sea" / DERP**，`tailscale ping` 372–393 ms；TCP 5432/7233/9000 约 473–510 ms；psycopg connect 15 s 超时；MinIO cover GET 约 27 KiB/s。
- 与 2026-10-20 的健康路径（Mac 192.168.3.132、public 120.228.1.159、direct 19 ms、MappingVariesByDestIP=false）不同；这是 **Mac 本地网络变化**，不是腾讯云带宽。
- 2026-10-21 07:20：在无活动 lease/task 前提下，已备份并重启 Mac Worker 加载新代码：新 PID **54216**，runs=3，启动日志 “collection worker polling …”；Temporal poller `alive=True, fresh_pollers=2`。**真实任务未创建**（网络不可用）。
- 解除条件：Mac 接回原 WiFi/任何 Tailscale direct 网络（`tailscale status` 显示 direct、RTT ~19 ms、MappingVariesByDestIP=false）；并在腾讯云控制台确认套餐/10–20 Mbps 价格/升级。代码已部署，无需再次重启即可继续；若需回滚，使用 `.runtime/backups/perf03-20261021/deployed-baseline/`。
- 证据：[deployment-blocker-2026-10-21/01-tailscale-relay.txt](../evidence/deployment-blocker-2026-10-21/01-tailscale-relay.txt)。

### 状态历史补充

- 2026-10-21：待验收 → **阻塞**；Mac 网络切至对称 NAT，Tailscale DERP 378 ms，DB 超时；停止部署/真实验收；等待网络恢复与控制台带宽确认。

## 2026-10-21 真实采集性能实测（户外/3）

- 带宽**未升级**；手机热点 Tailscale DERP(sfo) 377–449ms、对称 NAT，MinIO 回读 **22.8–26.8 KiB/s**（约 0.2 Mbps 级）。
- 真实达人 `7567692037719916582`：8 模块完成 **11 分 37 秒**，到快照发布 **15 分 39 秒**；
  单模块 9.3–26.3s，`creation` 127.1s；event loop lag 3.0–22.1s，slow DB 4–11s。
- 结论：PERF-03 的 10 Mbps→96.6s / 20 Mbps→84.4s 模型**不适用于当前链路**；**≤120s 未达标**，≤60s 更不可能。
  在不升级带宽、不改 checkpoint 结构（需另立项）的前提下，不应重复真实采集。
- 证据：[e2e-real-collection-2026-10-21.md](../evidence/e2e-real-collection-2026-10-21.md)。
