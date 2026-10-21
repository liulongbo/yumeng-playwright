# Mac 采集节点网络兼容性检查（家庭 WiFi / 手机热点）

- 日期：2026-10-21
- 范围：只读网络/服务探针，未创建真实采集任务，未修改业务代码/Schema/账号/Profile/腾讯云网络。
- 结论：**手机热点可用但为 DERP relay、性能不足；家庭 WiFi 本次 NOT TESTED（Mac 未拿到 192.168.3.x）；双向切换 NOT TESTED。现有 launchd/Worker 重试机制观察到可跨网络恢复，无需代码修改。**

---

## 1. 当前网络与手机热点

当前 Mac 实际为 `10.209.115.57`（与此前手机热点一致），**不是**家庭 WiFi 的 `192.168.3.x`。

| 项目 | 手机热点实测 |
|---|---|
| 接口/网关 | en0 `10.209.115.57` / `10.209.115.126` |
| 公网 IP | `223.160.114.198`（netcheck） |
| Tailscale | **relay "sfo" / DERP**，`tailscale ping` 383–401 ms；**无 direct** |
| netcheck | UDP true；`MappingVariesByDestIP=true`；PortMapping 空；Nearest DERP Singapore |
| TCP 5432/7233/9000 | 约 **335–466 ms**，3/3 成功 |
| PostgreSQL | `SELECT 1` 约 **3.75–4.99 s**；unit `SESSION_UNVERIFIED / generation 9 / owner NULL / browser_stopped=true` |
| MinIO cover GET | 61,866 B 约 **1.47–2.80 s（21.6–41.1 KiB/s）** |
| Temporal Poller | `alive=True, fresh_pollers=1, poller_entries=1` |
| Worker | launchd PID **54216**，runs=3，state=active |
| 活动任务 | 0；root_tasks 总数 4；无新任务 |

手机热点是**对称 NAT**（`MappingVariesByDestIP=true`），Tailscale 无法 direct，只能走 DERP(sfo) 400 ms 左右。连接本身可用（DB/Temporal/MinIO 均可达，Worker poller 正常），但 **21–41 KiB/s 的 MinIO/DB 路径不足以支撑 10 位真实采集的性能目标**。

两次独立探针均得到相同结论（`02-phone-hotspot.json`、`03-phone-hotspot-2.json`）。

---

## 2. 家庭 WiFi

**NOT TESTED。**

原因：用户选择“已连家庭 WiFi”，但实际接口仍为 `10.209.115.57`（手机热点），未拿到 `192.168.3.x`。因此本轮**没有家庭 WiFi 的实测数据**，不能标记 PASS。

家庭 WiFi 验证步骤（待用户在家/可达时）：

```bash
ifconfig en0 | grep 'inet '
# 期望：192.168.3.x
tailscale status | grep yumeng-xingtu-cloud
# 期望：direct 119.91.210.100:41641
tailscale ping --c 3 100.86.124.51
# 期望：18-20 ms direct
```

注意：手机热点会与家庭 WiFi 竞争自动加入；测试家庭时建议先关闭手机热点或关闭该网络的自动加入，避免 macOS 又切回 `OnePlus Ace 3`。

---

## 3. 双向切换

| 场景 | 状态 | 证据 |
|---|---|---|
| 家庭 WiFi → 手机热点 | **NOT TESTED** | 本次没有家庭 WiFi 实测；当前已是手机热点 |
| 手机热点 → 家庭 WiFi | **NOT TESTED** | 未拿到 192.168.3.x |
| 公司 WiFi → 手机热点（额外观察） | **PARTIAL** | Worker PID 54216 在 07:20 启动；08:41–08:43 在 `192.168.10.165` 记录 `ConnectionTimeout`；09:02–09:04 已在 `10.209.115.57`，同一 PID 54216、poller alive=1；**未重启、无重复 Worker**。切换/恢复的精确时刻未捕获，不能给秒级指标。 |

现有机制观察：

- launchd `KeepAlive.NetworkState=true`、`ThrottleInterval=30`；网络变化时由 launchd 决定是否重启。
- Worker dispatch loop 捕获 DB/Temporal 异常，每 2 s 重试；psycopg 每次操作新建连接、`connect_timeout=10`；Temporal SDK 自身重连。
- 公司→手机这次切换中，**同一 PID 54216 存活并恢复 poller**，没有产生第二个 Worker、没有异常 lease owner、没有历史任务误重试。
- 因此**未发现需要修改业务代码或 launchd 配置的明确缺陷**；本轮不做代码修改。

---

## 4. 服务与状态

| 项目 | 手机热点 |
|---|---|
| PostgreSQL | 可达；单次 `SELECT 1` 3.75–4.99 s（慢，但连接成功） |
| Temporal | 可达；poller fresh=1 |
| MinIO | 可达；21.6–41.1 KiB/s |
| Worker | PID 54216，runs=3，active |
| ExecutionUnit | `SESSION_UNVERIFIED / generation 9 / owner NULL / browser_stopped=true` |
| 活动 task | 0；无 lease owner |
| 重复 Worker | 未发现；poller_entries=1 |
| 历史任务 | 未修改/未重试/未取消 |

---

## 5. 结论

- **手机热点：连接性 PASS，性能 FAIL（DERP relay 400 ms，MinIO 21–41 KiB/s）。**
- **家庭 WiFi：NOT TESTED**（本次未真正连接 192.168.3.x）。
- **双向切换：NOT TESTED**（仅观察到公司→手机的同一 Worker 恢复，作为部分证据）。
- **代码/配置修改：无**；现有 launchd/Worker 重试机制在观察到的网络变化中恢复，没有明确缺陷。
- **是否影响原有采集/F10：未修改任何业务模块、F10、租约或数据逻辑。**
- 需要你操作：在家庭 WiFi 可达时手动连接，并关闭手机热点自动加入；确认 `192.168.3.x + direct 19ms` 后我再测家庭与双向切换。

**最终判定：CONDITIONAL GO（手机热点连接性可用；家庭 WiFi 与双向切换未实测；手机热点性能不足以做 10 位性能验收）。**

---

## 6. 证据

- [当前网络基线（公司/未知）](network-compat-2026-10-21/01-current.json)
- [手机热点探针 1](network-compat-2026-10-21/02-phone-hotspot.json)
- [手机热点探针 2](network-compat-2026-10-21/03-phone-hotspot-2.json)
- [launchd/Worker 配置](network-compat-2026-10-21/02-launchd-worker.txt)
- [部署记录](deployment-2026-10-21.md)

---

## 7. 公司 WiFi 补充验证（2026-10-21 09:09–09:10）

用户在切换到公司 WiFi 后要求验证。两次独立探针结果一致：

| 项目 | 公司 WiFi 实测 |
|---|---|
| 接口/网关 | en0 `192.168.10.165` / `192.168.10.1` |
| Tailscale | **relay "sfo" / DERP**，348–451 ms；`UDP: false`，无 direct |
| TCP 5432/7233/9000 | 294–415 ms，3/3 成功 |
| PostgreSQL | `SELECT 1` 3.4–4.0 s |
| Temporal | poller `alive=True, fresh_pollers=1` |
| MinIO cover GET | 45.7–46.0 KiB/s |
| Worker | PID **54216**，runs=3，active |
| ExecutionUnit | `SESSION_UNVERIFIED / generation 9 / owner NULL / browser_stopped=true` |
| 活动任务 | 0；root_tasks 4；无新任务 |

**结论：公司 WiFi 连接性可行（服务均可达，Worker/Poller 正常），但为 DERP relay、350–450 ms、MinIO ~46 KiB/s；不适合作为 10 位真实采集的性能验收网络，但可作为控制面/轻量任务网络。**

**切换恢复证据：** 手机热点探针（09:04–09:05）与公司 WiFi 探针（09:09–09:10）之间，Worker 仍为同一 **PID 54216**、runs=3、poller alive=1；未重启、无重复 Worker、无 lease owner、无历史任务重试。说明现有 launchd/Worker 机制在**手机热点 → 公司 WiFi** 切换中自动恢复。

仍未完成：家庭 WiFi（未拿到 192.168.3.x）、家庭↔手机/公司双向切换。家庭 WiFi 仍为 **NOT TESTED**。

**更新判定：CONDITIONAL GO** —— 公司/手机热点连接性均可用且可自动恢复；家庭 WiFi 未实测；手机/公司 relay 性能不足以做 10 位性能验收。

证据：[04-company-wifi.json](network-compat-2026-10-21/04-company-wifi.json)、[05-company-wifi-2.json](network-compat-2026-10-21/05-company-wifi-2.json)。
