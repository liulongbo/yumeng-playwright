# NET-01：Mac 家庭 WiFi / 手机热点网络兼容性与自动恢复

状态：阻塞
更新时间：2026-10-21T10:30:00+08:00
是否验收：否；公司 WiFi 实测**阻断 Tailscale**（TLS reset，私网不可达）；手机热点连接性 OK 但仅 22.8–26.8 KiB/s；家庭 WiFi/双向切换仍未测；未改网络策略。

## 目标

验证 Mac 在家庭 WiFi 与手机热点两种网络下都能连接腾讯云 PostgreSQL/Temporal/MinIO，并在切换后自动恢复 Worker/Poller/ExecutionUnit；只有明确故障才做最小修复。

不做：创建真实采集任务、修改业务代码/Schema/账号/Profile/腾讯云网络、购买带宽、重试/取消历史任务、Git commit/push/merge。

## 关联

- [PERF-03](PERF-03.md)、[E2E-01](E2E-01.md)、[MAC-01](MAC-01.md)、[OPS-01](OPS-01.md)。
- 报告：[network-compat-2026-10-21.md](../evidence/network-compat-2026-10-21.md)。

## 已实测

### 手机热点

- en0 `10.209.115.57` / 网关 `10.209.115.126`；公网 `223.160.114.198`。
- Tailscale **relay "sfo" / DERP**；`tailscale ping` 383–401 ms；无 direct。
- netcheck：UDP true；**MappingVariesByDestIP=true**；PortMapping 空；Nearest DERP Singapore。
- TCP 5432/7233/9000：335–466 ms，3/3 成功。
- PostgreSQL `SELECT 1`：3.75–4.99 s；Temporal poller `alive=True, fresh_pollers=1`；MinIO cover GET 21.6–41.1 KiB/s。
- Worker：launchd PID **54216**，runs=3，active；ExecutionUnit `SESSION_UNVERIFIED / generation 9 / owner NULL / browser_stopped=true`；无活动 task，无重复 Worker，无 lease owner。
- **连接性 PASS；性能 FAIL（不足以支撑 10 位真实采集）。**

### 家庭 WiFi

**NOT TESTED**：Mac 实际仍为 `10.209.115.57`（手机热点），未拿到 `192.168.3.x`；不能标记 PASS。

### 双向切换

- 家庭→手机、手机→家庭：**NOT TESTED**。
- 额外观察：Worker PID 54216 在 `192.168.10.165` 网络下 08:41–08:43 记录 `ConnectionTimeout`；到 `10.209.115.57` 手机热点后同一 PID 仍存活，poller alive=1，未重启、无重复 Worker。说明现有机制在至少一次网络变化中恢复了云端通信；但切换/恢复精确时刻未捕获，不能作为家庭↔手机验收。

## 现有机制（未修改）

- launchd `KeepAlive.NetworkState=true`、`ThrottleInterval=30`；`RunAtLoad=true`。
- Worker dispatch loop 捕获 DB/Temporal 异常，每 2 s 重试；psycopg 每次新建连接、`connect_timeout=10`；Temporal SDK 自带重连。
- 未发现需要修改业务代码或 launchd 配置的明确缺陷；本轮**零代码改动**（仅新增只读诊断脚本 `scripts/diag/network_compat_check.py` 与证据）。

## 待完成

1. 用户连接家庭 WiFi（期望 `192.168.3.x`），关闭手机热点自动加入，确认 `tailscale status` direct、RTT ~19 ms。
2. 在家庭 WiFi 下复跑探针，记录 DB/Temporal/MinIO/Worker/Poller/ExecutionUnit。
3. 家庭→手机：记录切换时刻、Worker PID/runs、poller、服务可达性、离线/恢复时间。
4. 手机→家庭：同上。
5. 若发现 Worker 不恢复/重复 Worker/lease 冲突，再做最小修复并补测试。

## 结论

**CONDITIONAL GO**：手机热点连接性可用但性能不足；家庭 WiFi 与双向切换未实测；现有机制无需修改。待家庭 WiFi 可达后继续。

## 状态历史

- 2026-10-21：待办 → 进行中；检查现有 Tailscale/launchd/Worker 机制。
- 2026-10-21：进行中 → **阻塞**；手机热点实测可用但 relay 400 ms/21–41 KiB/s；家庭 WiFi 与双向切换未实测；等待用户在家连接。


## 2026-10-21 公司 WiFi 补充验证

- 公司 WiFi `192.168.10.165`：Tailscale relay "sfo" 348–451 ms，UDP false，无 direct；TCP 5432/7233/9000 294–415 ms 可达；PostgreSQL `SELECT 1` 3.4–4.0 s；Temporal poller alive=1；MinIO 45.7–46.0 KiB/s；Worker PID 54216、runs=3；无活动 task/lease。
- **连接性 PASS，性能有限**：可作为控制面/轻量任务网络，不适合 10 位真实采集性能验收。
- **手机热点 → 公司 WiFi** 切换：同一 PID 54216、runs=3、poller alive=1，未重启/无重复 Worker/无 lease owner；自动恢复观察到。
- 家庭 WiFi 仍 **NOT TESTED**；家庭↔手机/公司双向切换未测。
- 结论保持 **CONDITIONAL GO**；无代码/配置修改。
- 证据：[network-compat-2026-10-21.md](../evidence/network-compat-2026-10-21.md)、[04-company-wifi.json](../evidence/network-compat-2026-10-21/04-company-wifi.json)、[05-company-wifi-2.json](../evidence/network-compat-2026-10-21/05-company-wifi-2.json)。

## 2026-10-21 09:21–09:31 公司 WiFi：Tailscale 被拦截

- `192.168.10.165` / 公网 `222.240.4.78` 下，`derp1.tailscale.com`、`controlplane.tailscale.com` 的 TLS 握手
  3/3 `ConnectionReset`；`tailscale ping` 无回应；TCP 5432/7233/9000 全不可达；Worker 每 12s `ConnectionTimeout`，
  云端 unit OFFLINE、poller alive=false；站点公网 443 正常。
- 判定：**连接性 FAIL（该网络阻断 Tailscale）**，不是 Worker 或云服务故障；未改网络策略。
- 09:31 切回手机热点后自动恢复（DERP sfo 约 390ms，poller 恢复，无需重启 Worker 即重新领取任务）。
- 证据：[e2e-real-collection-2026-10-21.md](../evidence/e2e-real-collection-2026-10-21.md)。
