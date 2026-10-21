# 正式环境端到端验收：`户外 / 3` 真实采集（2026-10-21）

> 执行：DSH（独立 QA / 全栈），Playwright MCP（stdio）+ 系统 Chrome 155.0.8059.85
> 站点：https://xingtu.yumeng.live
> 结论先行：**核心链路可走通到“1 位达人完整 8 模块 + 封面 + 快照发布”，但 `户外/3` 只完成 1/3，
> 性能 11 分 37 秒/达人，远超 120 秒；F10 未触发。整体 E2E = NO-GO（性能与网络阻塞）。**
> 本轮另发现并修复一个真实 P1 心跳缺陷（见 §8）。

## 1. 执行前状态核验（实测，不引用历史）

| 项目 | 实测（2026-10-21 CST） | 判定 |
|---|---|---|
| 站点 HTTPS | `https://xingtu.yumeng.live/` 200，TLSv1.3，登录页正常 | PASS |
| 部署代码 | `browser_host/engine/repository` SHA256 与 `.runtime/backups/perf03-20261021/candidate` 完全一致；`worker.py` 本轮修复后为 `85ff1053…`（原 `639377a7…`） | PASS（见 §8） |
| Mac Worker | 09:21 时 launchd 状态 running、PID 54216；09:35 与 09:52 因排障两次重启；当前为手工拉起 PID 64182（见 §11.3） | 见 §11.3 |
| Temporal Poller | `xingtu-unit-local-mac-02` alive=true，fresh_pollers≥1（09:32、09:38、09:56 均复核） | PASS |
| 执行单元 | 09:27 为 `SESSION_UNVERIFIED / OFFLINE`；网络恢复后 `ONLINE`；任务结束回到 `READY / owner=NULL / browser_stopped=true / generation=23` | PASS |
| 历史任务 | 5 个历史任务均 `CANCELLED/FAILED`，无自动重试 | PASS |
| Chrome Profile | `unit-local-mac-02`，无并发浏览器；09:35 遗留的孤儿 Chrome 经 CDP `Browser.close` 确认终止后才恢复单元 | PASS（见 §9.2） |

## 2. 网络实测（两段，均非预测值）

### 2.1 公司 WiFi（09:21–09:31）：Tailscale 完全不可用

- en0 `192.168.10.165`，公网 `222.240.4.78`。
- `*.tailscale.com` 的 TLS 握手被 `ConnectionReset`（`derp1.tailscale.com`、`controlplane.tailscale.com` 3/3 复现）。
- `tailscale ping 100.86.124.51` 无回应；TCP 5432/7233/9000 全部不可达；`tailscale status` 仅残留缓存 `relay "sfo"`，`tx` 增长、`rx=0`。
- Worker 日志每 12 s `collection dispatch tick failed: ConnectionTimeout`；云端显示 unit OFFLINE、poller alive=false。
- 站点公网 443 正常（200）。结论：**公司 WiFi 拦截 Tailscale，Mac 无法访问云私网**；未创建任务。

### 2.2 手机热点（09:31 起）：连通但吞吐不足

| 指标 | 实测 |
|---|---|
| 地址 | en0 `10.209.115.57`，公网 `223.160.115.198` |
| Tailscale 路径 | **DERP(sfo) 377–449 ms**，无 direct；`MappingVariesByDestIP=true`（对称 NAT） |
| TCP 5432/7233/9000 | 429–448 ms，3/3 可达 |
| PostgreSQL | connect 2.4–4.1 s；`SELECT 1` 0.48–0.93 s（基线）→ 采集中 **4–11 s**（抖动） |
| MinIO 回读 | **22.8–26.8 KiB/s**（29–62 KiB 样本） |
| Event Loop Lag | 3.0 s / 4.1 s / 4.3 s / 4.9 s / 6.1 s / 6.8 s / 7.9 s / **15.7 s / 22.1 s** |

**云出口带宽未升级**：本轮实测有效回传仅约 0.2 Mbps 级，远低于 PERF-03 评估所需的 10–20 Mbps；10/20 Mbps 的 96.6 s/84.4 s 模型不适用于本轮。

## 3. Playwright MCP + Chrome 真实浏览器证据

- MCP 服务：`@playwright/mcp`（stdio），`--browser chrome`，独立测试 profile，`--no-proxy-server`（系统代理 127.0.0.1:7897 已失效，不走代理）。
- 真实 Chrome：`Google Chrome 155.0.8059.85`，页面标题“星采 · 媒介工作台”。
- 截图（本目录）：
  - `01-login-initial.png` 登录页；`02-tasks-admin.png` 登录后任务中心；
  - `03-execution-units.png` 执行单元（当时 OFFLINE）；
  - `04-new-task-filled.png` / `05-task-submitted.png` 第一次真实任务 `宠物/10`；
  - `06-task-collecting.png` 采集中；
  - `07-new-task-outdoor-3.png` / `08-outdoor-task-created.png` 本次 `户外/3` 创建；
  - `09-task-partial-completed.png` 终态“部分完成”；
  - `10-task-detail-data.png` 任务详情数据；
  - `11-creator-library.png` / `12-creator-detail.png` 达人库与 `TEX极境探险` 详情。

## 4. 两个真实任务与链路

### 4.1 任务 A：`83fbc4a9-bcbe-46d2-a552-e02d8eb49d56`（宠物 / 10）

- 创建 09:33:41；P1 `deepseek-flash` 1150 ms，16073/88 tokens，FilterPlan `keyword=宠物, target_count=10, validation_errors=[]`。
- P2 dispatch sent=true；Worker 领取；Chrome 启动。
- **暴露 P1 缺陷**：09:33:52 `temporal heartbeat failed … type=RuntimeError`，`coroutine '_ActivityWorker._heartbeat_async' was never awaited`；Activity 每次 45 s 心跳超时后重派（attempt 1→2→3）。
- 因用户改为验证 `户外/3`，该任务在 0 候选/0 采集状态下由产品 UI 取消（09:56，`CANCELLED`），未删除、未重试。

### 4.2 任务 B：`4ab65124-ce3c-4fd5-adcf-aa837228006b`（户外 / 3）— 本轮主验收

| 阶段 | 证据 |
|---|---|
| 前端提交 | 09:57:15，任务详情 `#4ab65124` |
| P1 | `model_runs`: succeeded，`deepseek-flash`，866 ms，16073/88 tokens；requirement `keyword=户外, target_count=3`；FilterPlan 校验通过 |
| P2 | `task_dispatches` 1 条，sent=true，workflow `collect/4ab65124…` 09:57:32 启动；无重复派发 |
| Worker | 09:57:43 领取；Temporal heartbeat 正常刷新（见 §8） |
| Chrome | 项目 Profile 真实启动（`*.runtime/profiles/unit-local-mac-02`，8 个 Chrome 进程） |
| 会话 | `last_session_status=VALID`，`PROTECTED_PAGE_AND_ACCOUNT_VERIFIED`（未触发登录/滑块） |
| 搜索 | 20 位候选；候选 ID 顺序落库；仅第 1 位进入采集 |
| 采集 | `7567692037719916582`（`TEX极境探险`）8 模块：basic / commercial / spread / seeding / fulfillment / conversion / fans / creation，81 个字段 |
| 持久化 | 10 个封面对象（904,132 B，全部 HEAD 校验通过，image/webp） |
| 发布 | 1 份快照 `c8b1ed55…`（85,868 B，created 10:17:11） |
| 终态 | `PARTIAL_COMPLETED`，`failure_reason=HEARTBEAT_TIMEOUT`，completed_at 10:17:11 |

## 5. 数据完整性（前端 / API / PostgreSQL / MinIO 交叉）

| 指标 | 值 | 说明 |
|---|---|---|
| 搜索候选 | 20 | checkpoint `candidates` |
| 实际访问达人 | 1 | 其余 19 为 `pending` |
| valid 达人 | 1 | `task_creators.valid=true` |
| profile_complete | **false** | 8 模块已采，但精选 `NOT_ATTEMPTED`，`pipeline_complete=false` |
| 已发布快照 | 1 | 85,868 B；历史快照 `e187942b…`（10-20）时间/内容未变 |
| 精选集合/卡片 | **0 / 0** | 本轮未执行到精选模块，不能记为通过 |
| 媒体对象 | 10 | MinIO HEAD 10/10 存在，大小与 DB 一致 |
| 达人主记录关联 | 1 | `task_creators` → `creator_snapshots` → `platform_creators` 一致 |
| 重复快照 | 无 | 每任务 1 份 |
| 前端一致性 | 一致 | 任务详情“部分完成”，达人库可见 `TEX极境探险` |

## 6. 性能：逐达人完整时间线（真实样本）

达人 `7567692037719916582`（开始处理 ≈ basic 结束 − elapsed）：

| 环节 | 结束时间 | 本环节耗时 |
|---|---|---|
| basic | 10:01:51 | 19.02 s |
| commercial | 10:07:54 | 9.94 s（之前经历 10:02:15 心跳超时→重试/重验会话，间隔约 4 分 45 秒） |
| spread | 10:08:23 | 9.31 s |
| seeding | 10:08:53 | 9.72 s |
| fulfillment | 10:09:23 | 9.83 s |
| conversion | 10:09:53 | 9.86 s |
| fans | 10:10:40 | 26.26 s |
| creation | 10:13:09 | **127.12 s** |
| 快照发布 | 10:17:11 | 距最后模块 242 s |

- **达人模块完成耗时：约 11 分 37 秒（697 s）**；
- **到快照发布：约 15 分 39 秒（939 s）**；
- 剔除 10:02:15–10:07:00 的网络重试空档后仍约 6.5 分钟；
- **判定：> 120 s，性能不合格**；≤60 s 理想目标无从谈起。
- 单模块采集本身约 9–26 s，**真正开销在云端往返的同步 DB/checkpoint 与事件循环阻塞**（event loop lag 最高 22.1 s，slow DB 4–11 s）。

## 7. 精选 / 封面

- 精选：`featured_collections=0`，快照 `featured_status=NOT_ATTEMPTED`。**本轮精选模块未验证**。
- 封面：10 个对象已上传并被快照引用；未发现未引用对象。

## 8. Heartbeat / Lease / Generation / 终态

### 8.1 发现（P1，真实回归）

`TemporalHeartbeat` 在守护线程直接调用 `activity.heartbeat()`；该 API 在异步 Activity 内部执行
`asyncio.create_task(...)`，非事件循环线程调用立即抛 `RuntimeError: no running event loop`，
协程 `_ActivityWorker._heartbeat_async` 从未 await。结果：**没有任何 Temporal 心跳**，
45 s 后 Activity 心跳超时并被重派（任务 A 的 attempt 1→3）。

### 8.2 修复（最小、保留语义）

- `TemporalHeartbeat` 只负责把 `activity.heartbeat` 以捕获的 Activity Context **调度到事件循环线程**；
- 异步租约心跳任务恢复 `activity.heartbeat(root)` 的循环侧发送（发送失败只告警，不冒充租约失败）；
- 更新/新增单测断言“SDK 调用只发生在事件循环线程”，保留 watchdog 与取消/停止行为。
- 文件：`backend/src/xingtu/worker.py`；测试：`backend/tests/unit/test_worker_heartbeat.py`。
- 备份：`.runtime/backups/qa-hb-20261021/`（修复前文件 + SHA256）。

### 8.3 验证

- 单测：heartbeat 15 passed；全量 unit **352 passed**；contract **33 passed**（需 `PLAYWRIGHT_BROWSERS_PATH=.runtime/browsers`）；ruff/mypy 通过。
- 真实环境：修复后 Temporal `pending_activities[].last_heartbeat` 持续刷新（09:44:13、10:07:06、10:14:13），Activity 存活远超 45 s。
- 本轮后续失败是**租约心跳** `HEARTBEAT_TIMEOUT elapsed=10.0–11.1 s`（DB 单次操作超过 10 s 的既有 fail-closed 预算），不是 Temporal 心跳缺陷；未放宽该安全约束。

### 8.4 Lease / Generation / 终态

- generation 9 → 23，全部写入均带当前 generation；未发现旧代次写入成功。
- 中断后单元两次进入 `QUARANTINED`（`EXPIRED_OWNER`），按既有流程确认本机无浏览器进程后执行
  `xingtu recover-unit`（SESSION_UNVERIFIED，owner=NULL，browser_stopped=true，generation+1）。
- 任务结束：Workflow FAILED（max attempts），产品 root_task **PARTIAL_COMPLETED + HEARTBEAT_TIMEOUT**，
  已发布 checkpoint 快照；**未出现永久 COLLECTING，未重复发布**。P1FIX-02 的失败收口与 checkpoint 发布生效。

## 9. 过程中发现的其他问题

### 9.1 P2：取消/中断后 Profile 文件锁残留

10:17 中断后 `.runtime/profiles/unit-local-mac-02.lock` 仍被 Worker 持有，`recover-unit` 报
`PROFILE_STILL_IN_USE`，只能重启 Worker 释放。属中断清理路径缺陷，本轮未改（避免扩大改动）。

### 9.2 P2：孤儿 Chrome 需人工确认终止

Worker 被停止后 Chrome 仍监听 9223，需用 CDP `Browser.close` 终止后才可安全恢复单元；符合“租约到期≠浏览器停止”的既有约束，但缺少自动回收。

### 9.3 环境：本会话无法 `launchctl bootstrap`

`launchctl bootstrap/load gui/501` 对任意 plist 均返回 `Input/output error (5)`（最小 `sleep` 任务同样失败），
`submit` 亦不可用。因此本轮 Worker 以同参数手工拉起（`run-collection-worker.sh`，PID 64182）。**需在正常终端恢复 launchd。**

## 10. F10 人工验证

**NOT TESTED**。本轮未出现滑块/登录跳转；会话 `VALID`。不得将“未触发”记为 F10 通过。

## 11. 验收判定

| 卡片/项 | 判定 | 依据 |
|---|---|---|
| P1FIX-02 | **部分通过** | 失败收口 + checkpoint 发布 + generation fence 生效；但其 Temporal 心跳线程本身有 P1 缺陷，本轮已修复并验证；租约心跳在慢网下仍会 fail-closed |
| PERF-01 | 结论仍成立 | 慢因是 checkpoint 往返 + 出口链路，不是 Temporal/asyncio 本身 |
| PERF-02 | 优化生效但不足 | 完整传输 10→3、字节 −70% 仍无法抵消 0.2 Mbps 级链路 |
| PERF-03 | **未达标** | 带宽未升级；实测 22.8–26.8 KiB/s；单达人 11 分 37 秒 ≫ 120 s |
| E2E-01 | **未通过（NO-GO）** | `宠物/10` 已取消；`户外/3` 仅 1/3，精选 0，终态 PARTIAL_COMPLETED |

- **核心功能验收：CONDITIONAL** — 登录、P1、P2、Worker、Chrome、搜索、8 模块、封面、快照、前端展示、终态收口全部真实跑通；但目标人数与精选未完成。
- **采集性能验收：NO-GO** — 单达人 697 s（模块完成）/939 s（含发布）。
- **整体 E2E：NO-GO** — 受链路吞吐与租约心跳预算限制。

## 12. 下一步建议

1. 恢复 launchd Worker（正常终端执行 `launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.yumeng.xingtu.collection-worker.plist`）。
2. 提供可直连 Tailscale 的网络（家庭 WiFi direct ~19 ms）或经批准提升云出口/放开直连；否则不要重复真实采集。
3. 链路达标后再跑一次 `户外/3`，必须补做：精选两组、`profile_complete`、F10 真实恢复。
4. 单独立项修复：中断后 profile 锁清理、孤儿 Chrome 自动回收（涉及执行单元安全语义，需评审）。
