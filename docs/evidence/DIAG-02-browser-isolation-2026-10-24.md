# DIAG-02：ExecutionUnit「old browser requires isolation」专项诊断（2026-10-24）

> 结论时点：2026-10-24T12:07+08:00。本轮只读诊断，**未修改业务代码、数据库、Schema、Chrome Profile、租约或任务**，未创建新采集任务，未 commit/push/merge。
> 关联任务：`383474a1-40b6-4343-ac22-9a4efcdc6af7`（失败任务）、`2ff8ad00-1436-4be6-850f-c2129881849b`（触发隔离的上一任务）、`60a67287-4bc0-46cf-a50a-f62bc38c658f`（同因被取消任务）。
> 关联卡片：[DIAG-02](../tasks/DIAG-02.md)、[F10](../tasks/F10.md)、[QA-01](../tasks/QA-01.md)、[AUTO-01](../tasks/AUTO-01.md)、[UNIT-01](../tasks/UNIT-01.md)。
>
> **2026-10-24 12:32 更新**：用户批准后已实施最小修复并完成 macOS 真实 Chrome E2E。本报告第 0—11 节与附录保留 **12:07 诊断时点**的事实（当时确实只读、未修复）；修复实施、测试与真实回归结果见 [DIAG-02 修复与真实 Chrome 回归](DIAG-02-fix-2026-10-24.md)。

## 0. 结论摘要

| 问题 | 结论 |
|---|---|
| 是否复现 | **是**。真实任务 `383474a1` 仍在稳定失败；另用真实 PostgreSQL 行 + 真实 `Repository.acquire()` 在**回滚事务**中复现了同一异常，事务回滚后库内状态逐字段不变。未创建新任务。 |
| 错误位置 | `backend/src/xingtu/repository.py:648-716` 的 `Repository.acquire()`，在**打开 Chrome 之前**；不是 Chrome 启动失败，也不是复用旧浏览器失败。 |
| 直接触发条件 | 执行单元存在 `owner` 且 `lease_until` 已过期，或 `state='QUARANTINED'`，或 `browser_stopped=false`；任一成立即 `RESOURCE_UNAVAILABLE: old browser requires isolation`。 |
| 系统检测到的“old browser” | 不是一个仍在运行的 Chrome，而是 **11:20:48 启动、11:23 前后随 Worker 异常退出而消失的旧 BrowserHost 的数据库残留**：`owner=d358fe6b…`、`browser_instance_id=a937d566…`、`browser_stopped=false`。 |
| 旧浏览器是否真实残留 | **否**。项目 Profile 锁空闲；Chrome SingletonLock 指向 PID `23355`，该 PID 已不存在；profile 无任何进程打开；用户个人 Chrome（PID 983）使用默认 Profile。`confirm_local_browser_stopped()` 实测 **PASS**。 |
| 是否最近 macOS/Windows 适配引入 | **不是直接引入**。`old browser requires isolation` 与 `recover-unit` 自初始导入即存在，F10 提交未改 `acquire`/`release`/`BrowserHost` 释放语义。F10 新增的 Worker 心跳/重启入口**没有把单元回收纳入启动流程**，使既有的 fail-closed 缺口在频繁本机重启下更容易暴露。 |
| 任务是否进入终态 | **否**。`383474a1` 为 `WAITING_FOR_RESOURCE`，`completed_at=NULL`，Workflow 每约 30 秒重试一次；截至 12:06:59 已写至 version 38。资源等待按设计不是终态，但在隔离状态下**永远不会自行恢复**。 |
| 是否影响新任务 | **是**。新任务仍会被 `promote_intake` 分配给同一单元（它只检查 `allowed_task_kinds`，不检查 `state='QUARANTINED'`），随后在 `collect` 阶段得到同一错误。`select_execution_unit` 虽排除 QUARANTINED，但正常产品任务并不走该函数。 |
| 已产生数据 | `383474a1`：`task_creators=0`、`creator_snapshots=0`、P2 checkpoints 无导航/无候选；**未进入 Chrome 采集阶段，无新数据**。上一任务 `2ff8ad00` 的 1 位达人 / 1 份快照（2026-10-23T12:02:43）**完整保留**，无覆盖、无重复。 |
| 最小修复建议 | **立即**：在隔离证明通过后运行既有 `xingtu recover-unit`（会改 generation/lease，需批准）。**代码**：在 Collection Worker 启动时，对满足严格条件的已隔离单元执行一次“本地隔离证明 + 审计回收”，复用 `confirm_local_browser_stopped()` 与 `recover_stopped_unit()`；不新增 Schema，不删除锁，不杀 Chrome。 |
| 是否可进入修复阶段 | **可以**，但需先批准第 11 节的授权事项；当前任务可在回收后沿用，无需新建任务。 |

## 1. 范围、授权与工具

- 本轮只做诊断与方案评审。**未**修改任何业务代码、数据库/Schema、租约/generation、Chrome Profile、Cookie 或会话；**未**取消、删除、重试历史任务；**未**创建新的真实采集任务。
- 使用 **Playwright 1.63.0 + 系统 Chrome 156.0.8078.47** 完成前端只读检查（登录 `media-a`，查看任务页/执行单元页，截图 2 张）。本会话没有可用的 Playwright MCP 工具，因此以同版本 Playwright 库 + 系统 Chrome 替代；这属于**真实浏览器**证据，但不是 MCP 通道，特此标注。
- 登录 `media-a` 会创建正常产品会话记录（`sessions` 表）；未触发任务、未点击取消/重试/接管。隔离复现全部在 `BEGIN … ROLLBACK` 事务内执行，回滚后逐字段核对未变。
- 读取：PostgreSQL 业务库（只读查询）、Temporal 历史（`temporal workflow show`）、`.runtime/logs/`、Chrome Profile 锁/进程状态、Git 历史。
- 未执行：新真实任务、`recover-unit`（会写 DB）、修复代码、部署、重启 Worker、清理锁/进程/Profile。

## 2. 复现

### 2.1 真实前端只读复现（Playwright + 系统 Chrome）

| 页面 | 观察到的事实 | 截图 |
|---|---|---|
| `/tasks/383474a1-…` | 阶段停在「排队 / 等待执行资源」；`RESOURCE_UNAVAILABLE: old browser requires isolation`；已发现 0、有效入库 0、资料完整 0、精选完整 0、失败步骤 0；最近更新 12:01。 | [task-383474a1.png](assets/diag02/task-383474a1.png) |
| `/execution-units` | `unit-local-mac-02`：运行状态「已隔离 / EXPIRED_OWNER」；当前任务仍指向旧任务 `2ff8ad00`；Worker `ONLINE`（1 实例，心跳 12:01）；浏览器 `QUARANTINED`；验证「正常」；最近心跳 11:23；操作只有不可用的「查看」。 | [execution-units.png](assets/diag02/execution-units.png) |

API 实测（`GET /api/tasks/383474a1…`、`GET /api/execution-units`）：

```text
task.status = WAITING_FOR_RESOURCE
task.failure_reason = RESOURCE_UNAVAILABLE: old browser requires isolation
task.counts = {target:3, discovered:0, valid:0, profile_complete:0, featured_complete:0, failed:0}
unit.state = QUARANTINED
unit.mode = maintenance
unit.current_root_task_id = 2ff8ad00-1436-4be6-850f-c2129881849b
unit.worker_status = ONLINE (1 instance, last heartbeat 12:01:54)
unit.browser_status = QUARANTINED
unit.actionable_reason = EXPIRED_OWNER
unit.last_heartbeat_at = 11:23:03
```

### 2.2 隔离环境状态机复现（真实 DB 行 + 真实代码，事务回滚）

目的：不依赖新建任务，验证“到底是哪个条件触发”。使用真实 `Repository.acquire()`，只把连接替换为**不提交**的连接，最后 `ROLLBACK`。

| 场景 | 操作（事务内） | 结果 | 回滚后 |
|---|---|---|---|
| 1. 过期 owner + 浏览器未确认停止 | 将当前单元临时置为 `LEASED / owner=diag-expired-owner / lease_until=now()-1min / browser_stopped=false`，调用 `acquire()` | `RESOURCE_UNAVAILABLE: old browser requires isolation`；单元被置为 `QUARANTINED`，`failure_reason=EXPIRED_OWNER` | 逐字段恢复原值，`UNCHANGED=True` |
| 2. 当前真实 QUARANTINED 行 | 直接调用 `acquire()` | 同一异常 | 逐字段恢复原值，`UNCHANGED=True` |
| 3. 回收后能否重新取得执行权 | 事务内调用 `recover_stopped_unit()`，再调用 `acquire()` | `SESSION_UNVERIFIED` → `LEASED`，`generation 137 → 138`，返回成功 | 回滚，库内仍为原 `QUARANTINED` |

完整证据（含三次 Temporal 历史、单元/任务/Worker 行）：[timeline.json](assets/diag02/timeline.json)。

> 这不是 Mock：使用的是真实 PostgreSQL 表、真实代码路径和真实当前行；只是**不落盘**。它证明的是状态机条件，不替代真实 Chrome 采集结论；真实 Chrome 结论见 2.3。

### 2.3 “旧浏览器”是否仍活着（真实进程/锁检查）

| 检查 | 命令/方法 | 结果 |
|---|---|---|
| 项目 Profile 锁 | `confirm_local_browser_stopped(config, ROOT/.runtime/profiles)` | **PASS**（`flock` 可获取，无 BrowserHost 持有） |
| Chrome SingletonLock | `readlink .runtime/profiles/unit-local-mac-02/SingletonLock` | 指向 `longboliuMacBook-Air.local-23355` |
| SingletonLock PID | `os.kill(23355, 0)` | `ProcessLookupError` → **PID 已不存在** |
| Profile 被占用文件 | `lsof +D .runtime/profiles/unit-local-mac-02` | **0 行** |
| 个人 Chrome 是否误用单元 Profile | `lsof -p 983` | 只打开 `~/Library/Application Support/Google/Chrome/…`，**未使用** `.runtime/profiles/unit-local-mac-02` |
| 单元 Profile 最近活动 | `stat` | 11:22（Chrome 退出前后），之后无活动 |

结论：**没有活着的旧浏览器**。`old browser` 是数据库里未被回收的“上次浏览器所有权”记录；隔离保护本身在正确地 fail-closed，但它把“已停止的旧浏览器”也一并拦住了。

### 2.4 复现频率与未执行项

- 频率：**确定性 100%**。只要单元处于当前 `QUARANTINED/EXPIRED_OWNER/browser_stopped=false`，每一次 Activity 尝试都在 `acquire()` 立即失败；`383474a1` 从 11:48:48 到 12:06:59 已重复 38 个版本。
- 复现边界：**原始 Worker 在 11:23 的异常终止本身不可重放**（没有该进程的 stderr，信号来源未确认）；本轮复现的是它留下的隔离判定与任务症状。真实新任务复现未执行；`recover-unit` 会写 DB，未执行；真实 Chrome 启动单元 Profile 会写 Cookie/会话，未执行。因此“修复后真实采集成功”只能作为待验证计划，不能宣称已通过。

## 3. 完整失败时间线（+08:00）

### 3.1 前因：10-23 的挑战与 10-24 的重试

| 时间 | 事件 | 证据 |
|---|---|---|
| 10-23 16:04:10 | 任务 `5542896c` 创建（target=1） | `root_tasks` |
| 10-23 16:06:59 | 检测到 `PLATFORM_SECURITY_CHALLENGE`，转 maintenance，创建验证事件 | `audit_logs` 415/416、`verification_events` |
| 10-23 16:08:25 | 用户请求并激活 takeover | `audit_logs` 419、`browser_takeover_sessions` |
| 10-23 16:21:59 | 15 分钟验证窗口到期，takeover `FAILED / TAKEOVER_EXPIRED` | `browser_takeover_sessions` |
| 10-23 16:32:23 | 任务最终 `PARTIAL_COMPLETED / SECURITY_CHALLENGE_TIMEOUT`；保留 1 位达人 | `root_tasks`、F10 证据 |
| 10-24 11:20:35 | `media-a` 登录 | `audit_logs` 423 |
| 10-24 11:20:44.173 | 对 `2ff8ad00`（10-23 12:02 已取消）点击重试；新 attempt `d358fe6b…`、segment 1 | `audit_logs` 424、`task_attempts` |
| 10-24 11:20:44.831 | Temporal 新 run 启动，Worker 身份 `80876@…`（generation 2） | Temporal `collect/2ff8ad00…` event 1 |
| 10-24 11:20:48.430 | 单元分配浏览器实例 `a937d566…`，Chrome 启动 | `execution_units.browser_started_at` |
| 10-24 11:21:43.483 | 用户取消 `2ff8ad00`；任务转 `CANCELLING`，开始每 ~2 秒的 `wake` 信号 | `audit_logs` 426、Temporal events 6–169 |

### 3.2 关键断点：Worker 在持有浏览器租约时异常消失

| 时间 | 事件 | 证据 |
|---|---|---|
| 11:23:02.612 | Worker generation 2 最后一次心跳 | `execution_unit_workers` |
| 11:23:03.526 | 单元最后一次租约心跳；`lease_until=11:25:03.526` | `execution_units` |
| 11:23:04.785 | 该 Worker 处理的最后一个 Workflow Task | Temporal `2ff8ad00` event 169 |
| ~11:23:05 | Worker 进程 80876 消失；**没有** `CancelledError`/`NORMAL_STOP` 记录，**没有** `repo.release()`（否则 `owner` 会被清空） | `execution_unit_workers`、`execution_units.owner` |
| 11:25:03.526 | 租约到期 | `execution_units.lease_until` |
| 11:28:40.596 | 新 Worker generation 3（PID 25208）启动；把 generation 2 标为 `STALE_REPLACED` | `execution_unit_workers`、collection-worker.log |
| 11:28:40.653 | 旧 Activity 以 attempt 2 重试，`lastFailure=activity Heartbeat timeout`；立即返回 `CANCELLED` | Temporal `2ff8ad00` events 174–179 |

**关键证据**：`BrowserHost.lease` 的 `finally` 一定会调用 `repo.release()`，而 `release()` 会把 `owner`、`lease_until`、`mode`、`current_root_task_id` 清空并设置 `browser_stopped=stopped`（[browser_host.py:157-166](../../backend/src/xingtu/browser_host.py#L157-L166)、[repository.py:1088-1145](../../backend/src/xingtu/repository.py#L1088-L1145)）。当前 `owner` 仍为 `d358fe6b…`、`mode` 仍为 `maintenance`、`browser_stopped=false`，因此 **release 路径根本没有执行**，不是“关闭超时后按设计置 QUARANTINED”。这是“进程被硬终止/终端关闭”这一类异常的强证据；但**具体信号来源没有日志，未能确认**（见 5.3）。

### 3.3 新任务被隔离状态拦截

| 时间 | 事件 | 证据 |
|---|---|---|
| 11:36:40.993 | 任务 `60a67287` 创建（关键词“宠物”） | `audit_logs` 428 |
| 11:36:44.217 | P2 promote，分配同一单元；attempt `2258ce70…` | `task_attempts` |
| 11:36:45.918 | Workflow 启动 | Temporal `60a67287` event 1 |
| **11:36:48.089** | 第一次 `collect` 返回 `WAITING_FOR_RESOURCE`；`acquire()` 在此时把单元置为 `QUARANTINED/EXPIRED_OWNER` | Temporal `60a67287` event 7；`execution_units.failure_reason` |
| 11:40:59.493 | 当前 Worker generation 4（PID 28208）启动 | `execution_unit_workers` |
| 11:47:31.377 | 用户取消 `60a67287` | `audit_logs` 430 |
| 11:48:42.326 | 任务 `383474a1` 创建（关键词“游戏集锦”，female，湖南，target=3） | `audit_logs` 431 |
| 11:48:43.009 | Intake Worker 派发 P1 | `intake-worker.log` |
| 11:48:45.009 | P1 成功，P2 promote，attempt `201a3697…` | `audit_logs` 432、P1 checkpoint `outcome=succeeded` |
| 11:48:46.728 | Workflow `collect/383474a1…` 启动 | Temporal event 1 |
| **11:48:48.798** | 第一次 `collect` 返回 `WAITING_FOR_RESOURCE`；此后每约 30 秒重复 | Temporal events 7、18、29… |
| 12:04:51 / 12:06:59 | `root_tasks.version` 34 / 38，`updated_at` 持续更新；仍无 Chrome、无数据 | DB、Temporal |
| 12:07:03 | 诊断时点：单元仍 `QUARANTINED`；Worker ONLINE；无打开的验证/接管 | `timeline.json` |

## 4. `old browser requires isolation` 的具体代码触发条件

调用链：

```text
Activities.collect (worker.py:293)
  → BrowserHost.lease (browser_host.py:116)
    → Repository.acquire (repository.py:648)
      → raise CollectorError("RESOURCE_UNAVAILABLE", "old browser requires isolation") (repository.py:715)
```

`Repository.acquire()` 的判定（简化）：

```python
row = SELECT * FROM execution_units WHERE unit_id=%s FOR UPDATE
if row["owner"]:
    if row["lease_until"] > now():
        raise RESOURCE_UNAVAILABLE "unit occupied"
    # 过期不是抢占浏览器/Profile 的许可
    UPDATE execution_units SET state='QUARANTINED', failure_reason='EXPIRED_OWNER'
    UPDATE browser_takeover_sessions ... state='EXPIRED'
    UPDATE verification_events ... state='EXPIRED'
    error = True
elif row["state"] == "QUARANTINED" or not row["browser_stopped"]:
    error = True
elif row["state"] not in {"READY","SESSION_UNVERIFIED"} and not maintenance:
    raise ACCOUNT_LOGIN_REQUIRED / ACCOUNT_MISMATCH
else:
    UPDATE ... generation+1, owner, lease_until, browser_stopped=false, state='LEASED'
    return generation, session_version
if error:
    raise RESOURCE_UNAVAILABLE "old browser requires isolation"
```

对应当前单元的三个条件**同时成立**：

1. `owner='d358fe6b…'`（非空），`lease_until=11:25:03`（已过期）；
2. `state='QUARANTINED'`（第一次失败时由本函数写入）；
3. `browser_stopped=false`（release 没跑）。

`failure_reason='EXPIRED_OWNER'` 证明**第一次触发是“owner 过期”分支**，不是后来才出现的 `QUARANTINED`。`lease_until=11:25:03` 与最后心跳 11:23:03 + 120 秒完全吻合。

错误之后的分类：

- `worker.collect` 捕获 `CollectorError`，把 `RESOURCE_UNAVAILABLE` 映射为 `TaskStatus.WAITING_FOR_RESOURCE`（[worker.py:635-658](../../backend/src/xingtu/worker.py#L635-L658)）。
- `workflow.py` 对非终态每 30 秒重试；`WAITING_FOR_RESOURCE` 不在显式唤醒集合，因此每 30 秒执行一次 `collect`，每次都再次失败。
- 任务因此**不是 FAILED，而是永远等待资源**；`allowed_actions` 只有 `cancel`。

单元选择：

- 正常产品任务在 `promote_intake` 中直接使用 Intake Worker 配置的 `unit_id`；只有在 `allowed_task_kinds` 不含 collection 时才回退查询 `state <> 'QUARANTINED'`（[product_repository.py:492-520](../../backend/src/xingtu/product_repository.py#L492-L520)）。因此**隔离单元仍会被分配给新任务**，随后在 `collect` 失败。
- `select_execution_unit()` 的 `state <> 'QUARANTINED'` 过滤（[repository.py:511-520](../../backend/src/xingtu/repository.py#L511-L520)）不覆盖正常采集路径。

## 5. 根因、已排除假设与未确认事项

### 5.1 已证实根因（因果链）

1. **11:20 的重试在 maintenance 模式下合法取得了单元**：单元在前一天挑战后为 `NEEDS_VERIFICATION`，`acquire(maintenance=True)` 允许它进入维护会话；Chrome 实例 `a937d566` 启动。
2. **11:23 Worker 异常消失，未执行 `BrowserHost.lease` 的 `finally → repo.release()`**：旧 owner、旧 lease、`browser_stopped=false`、`current_root_task_id`、`mode=maintenance` 全部留在库里。
3. **11:25 租约过期**；11:36:48 新任务第一次 `acquire()` 看到“owner 已过期 + 浏览器停止未确认”，按设计置 `QUARANTINED/EXPIRED_OWNER` 并拒绝分配。
4. **没有自动恢复**：隔离后只有 `xingtu recover-unit` 这一条人工 CLI 路径；Worker 启动、Intake promote、新任务创建都不会调用它。于是所有任务停在 `WAITING_FOR_RESOURCE`，每 30 秒重试，永不恢复。
5. **新任务继续被分配给同一隔离单元**：`promote_intake` 不检查 `state`，放大了影响面。

**一句话**：这不是“旧 Chrome 还在跑”，而是“上一次 Worker 没来得及交还浏览器所有权”；隔离保护正确地拒绝了抢占，但系统缺少把“已确认停止”的旧所有权自动/可见地回收的机制。

### 5.2 已排除的假设

| 假设 | 排除证据 |
|---|---|
| macOS Profile `flock`/SingletonLock 误判导致“旧浏览器” | `confirm_local_browser_stopped()` PASS；SingletonLock PID 23355 已不存在；profile 无进程打开；`acquire` 在打开 Chrome 之前就失败，根本没走到锁检查。 |
| Chrome 可执行文件发现/启动参数回归 | 错误发生在 `BrowserHost.lease → repo.acquire`；`BrowserRuntime.open()` 尚未调用；本轮没有 383 的 Chrome 启动记录。 |
| 真实旧 Chrome 仍占用 Profile | `lsof +D profile` 0 行；个人 Chrome PID 983 使用默认 Profile；无 `--user-data-dir` 指向单元 Profile。 |
| F10 接管/验证事件历史残留 | `verification_events` 中 OPEN/ACKNOWLEDGED = 0；`browser_takeover_sessions` 中 REQUESTED/ACTIVE/VERIFYING = 0；两个任务均无 takeover 行。 |
| Worker 重复/ fencing 误判 | 当前只有 generation 4 一个 Worker，`worker_status=ONLINE`；错误来自单元租约，不是 `DUPLICATE_WORKER_FOR_UNIT`。 |
| P1/P2 失败或计划非法 | P1 checkpoint `outcome=succeeded`；`FilterPlan` 与 requirement 一致，`validation_errors=[]`；P2 任务与 checkpoint 已创建。 |
| 数据库 generation/lease 被人工重置 | 无 `recover_stopped_unit`/`rebind` 审计；`generation=136`、`failure_reason=EXPIRED_OWNER` 与代码路径一致；本轮复现事务已回滚。 |
| 任务已进入终态但前端未刷新 | `completed_at=NULL`；Temporal Workflow 仍在 RUNNING，且 11:48–12:06 持续有 Activity 完成记录。 |

### 5.3 未确认事项

1. **11:23:04 具体是哪个信号/动作终止了 Worker generation 2**。没有该进程的 stderr/stdout（它的启动不在受管日志里；`collection-worker.log` 没有 21:04:40 的启动行），`execution_unit_workers.stop_reason` 后来被新 Worker 写成 `STALE_REPLACED`，不是真实退出原因。候选：终端关闭/SIGHUP、`kill`/SIGTERM、二次 Ctrl-C、SIGKILL。**这是唯一需要你补充信息的地方**：11:23 左右你是否关闭/重启过运行 Collection Worker 的终端？
2. **离开的 Activity 在 11:21:43 取消后、11:23 被杀前卡在哪一步**。P2 checkpoint 显示 `challenge_count=0`、`challenge_state=null`、`navigation_count=4`、`creation` 模块约 10 秒；可能是 Profile 采集中的 Playwright 等待，也可能是挑战页等待。没有该进程日志，不能把“取消未生效”归因为某一个函数。
3. **平台会话在回收后是否仍有效**。`last_session_status` 仍是 10-23 16:32 的 `SECURITY_CHALLENGE`；11:20 的 maintenance 采集到 1 位候选，说明会话至少部分可用。回收后可能需要一次 F10 人工验证；这是外部平台条件，不是隔离 Bug 本身。
4. **Windows 路径**未实测；本轮所有真实证据均为 macOS。
5. `execution_units.profile_ref` 仍指向旧 checkout `/Users/yaoyao/Documents/…`；运行时使用 `UnitConfig.profile_directory`（正确的新路径），所以不是本次根因，但属于需要清理的数据漂移。
6. launchd `com.yumeng.xingtu.collection-worker` 仍处于加载状态，按 KeepAlive 反复尝试执行不存在的 `deploy/macos/run-collection-worker.sh`（`ThrottleInterval=30s`），持续写 `cloud-collection-worker.error.log`。它不是本次根因，但属于本机运行时的遗留噪声/风险，建议单独清理。

## 6. 与最近 macOS/Windows 适配的关系（Git diff 结论）

最近提交：`024f879 feat(f10,qa-01): localize execution-unit runtime and stabilize filter execution`（2026-10-23 23:32）。涉及：

- `platform_runtime.py`（新）：POSIX `flock` / Windows `msvcrt`、Chrome 发现、Windows `lockfile`。
- `runtime.py`：锁调用改为适配层；Chrome 路径发现；POSIX 隔离逻辑保留。
- `worker.py`：Worker 实例注册/心跳/停止、BrowserError 分类、挑战页只读复核。
- `repository.py`：新增 `register_worker_instance` / `heartbeat_worker_instance` / `stop_worker_instance`（migration 019）。
- `product_queries.py` / `product_api.py` / 前端：Worker/浏览器/验证分列，LOCAL_WINDOW。

逐项核对：

| 关键点 | 是否被 F10 改动 | 证据 |
|---|---|---|
| `Repository.acquire()` 的隔离判断/错误文案 | **否** | `git log -S"old browser requires isolation"` 仅命中初始导入 `2fded60`；`024f879` 对 `repository.py` 只新增 Worker 方法（diff 已核对）。 |
| `BrowserHost.lease` 的 `finally → repo.release()` | **否** | `browser_host.py` 不在 `024f879` 变更文件列表；释放语义与 F10 前一致。 |
| POSIX Profile 锁 | **行为等价** | 旧 `fcntl.flock` 移入 `platform_runtime.acquire_profile_lock()`；macOS 仍为 `LOCK_EX|LOCK_NB`。 |
| `confirm_local_browser_stopped()` | **POSIX 逻辑保留** | 仍用项目 `flock` + `SingletonLock` PID；仅增加 Windows 分支和适配层调用。实测 PASS。 |
| 新增 Worker 心跳/重启 | **是** | 新增 `execution_unit_workers`；但只记录 Worker 生命周期，**不回收单元 owner/lease/browser 状态**。这正是缺口所在，不是错误判断本身。 |
| F10 运行手册 | **是** | 写了 Worker OFFLINE/休眠恢复、禁止改库，但**没有写 `recover-unit`**；见 [F10-local-macos-windows.md](../F10-local-macos-windows.md) 的“状态、日志与故障恢复”。 |

结论：

- **不是 F10 的 macOS/Windows 隔离判断把合法浏览器误判为旧浏览器**。如果是，错误应出现在 `confirm_local_browser_stopped`/`Profile` 锁，或者 `acquire` 之前；实际是 DB 里的旧 owner/lease 未释放，且 OS 层检查 PASS。
- **F10 的相关性在于“重启变多 + 恢复未接入启动流程”**：本机 supervisor/Worker 实例心跳让频繁重启更可见，但启动时只注册 Worker，不检查“上一个 Worker 是否留下未确认的浏览器”。既有的 fail-closed 缺口因此更容易被触发。
- `profile_ref` 漂移是项目目录迁移留下的数据问题，不是 F10 代码逻辑；运行时不使用该字段。
- 代码库已有集成测试把该语义固定为预期：`test_lease_expiry_quarantines_and_rejects_stale_write`（过期租约 → `QUARANTINED` → 拒绝旧代次写入）与 `test_recover_stopped_unit_handles_expired_lease_in_one_step`（回收 → `SESSION_UNVERIFIED` → 可再次 `acquire`），见 [test_repository.py:150-173](../../backend/tests/integration/test_repository.py#L150-L173)。本轮未运行这两个测试（需要 `XINGTU_TEST_DATABASE_URL`），因此不作为“测试通过”证据，只作为“该行为是既定设计而非新回归”的代码证据。

## 7. 业务链路影响

| 阶段 | 状态 | 说明 |
|---|---|---|
| 前端创建任务 | **PASS** | `audit_logs 431`（`product_task.create`）；任务页可读。 |
| P1 FilterPlan | **PASS** | `outcome=succeeded`；plan 与 requirement 一致；模型运行 1 次。 |
| P2 调度/派发 | **PASS** | P2 任务、attempt、`task_dispatches.sent=true`、Temporal Workflow 已启动。 |
| ExecutionUnit 取得执行权 | **FAIL** | `acquire()` 在打开 Chrome 前拒绝；无浏览器实例、无租约。 |
| Chrome 启动/采集 | **NOT REACHED** | 没有 383 的 Chrome 启动；`navigation_count=0`、无候选、无 profile 采集。 |
| PostgreSQL/MinIO 入库 | **NO NEW DATA** | 383 的 creators/snapshots 均为 0；上一任务的 1 位达人/1 快照保留。 |
| 任务终态 | **NO** | `WAITING_FOR_RESOURCE`，Workflow 持续每 30 秒重试；不是 FAILED，也不是 COMPLETED。 |
| 资源锁/租约/Chrome 释放 | **DB 残留，OS 已释放** | DB：owner/lease/browser_stopped 残留；OS：Profile 锁空闲、Chrome PID 不存在。没有物理锁泄漏。 |
| 后续新任务 | **受影响** | 同一单元仍被分配，随后同样卡在 `WAITING_FOR_RESOURCE`；`60a67287` 即为例证。 |
| F10 人工接管/恢复 | **当前未受影响机制，但不可用** | 无 open takeover/verification；隔离状态下 `request_browser_takeover` 要求 `LEASED/maintenance`，不会成功。回收后可恢复 F10 路径。 |
| macOS/Windows 兼容 | **macOS 现场；Windows 未测** | 代码路径平台无关；Windows 的 lockfile 逻辑未在本次事件中执行。 |
| 数据重复/丢失/快照覆盖 | **未发现** | `383` 无数据；`2ff8ad00` 的 `task_creators=1`、`creator_snapshots=1`（12:02:43）保持不变；无重复行。 |

## 8. 推荐修复方案

### 8.1 立即处置（人工，需批准；不改代码）

在**确认旧浏览器已停止**后运行既有 CLI：

```bash
cd /Users/Longbo/Developer/YUMENG
source .venv/bin/activate
set -a; . .runtime/local-main/env; set +a   # 提供 XINGTU_DATABASE_URL；不要回显文件内容
# 先只读确认（本轮已执行，PASS）：
#   confirm_local_browser_stopped → PASS
#   SingletonLock PID 23355 → gone
#   lsof profile → 0
xingtu recover-unit \
  --config .runtime/units/local-dev-mac-02.json \
  --actor "operator:$(whoami)"
```

效果：`QUARANTINED → SESSION_UNVERIFIED`，`owner=NULL`、`lease_until=NULL`、`browser_stopped=true`、`generation+1`、写 `audit_logs`。下一次 `383474a1` 的 30 秒重试将能取得执行权并尝试启动 Chrome。

**注意**：

- 这会改变租约/generation，属于你禁止的“重置 lease/generation”类别；**本轮未执行**，需你明确批准。
- 该命令只证明“浏览器已停止”，不证明平台会话仍有效；回收后仍可能需要 F10 人工验证。
- 不要删除 `SingletonLock`/`.lock`、不要杀 Chrome、不要改库绕过隔离。

### 8.2 推荐的最小代码修复（需批准；复用现有机制）

**在 Collection Worker 启动时做一次“隔离单元的本地证明 + 审计回收”。**

位置：`run_worker()` 在 `repo.register_worker_instance(...)` 之后、启动 Temporal `Worker` 之前（[worker.py:725-760](../../backend/src/xingtu/worker.py#L725-L760)）。

伪代码：

```python
unit = repo.unit(config.unit_id)
if unit["state"] == "QUARANTINED":
    # 1) 不碰仍有效的租约/接管
    if repo.has_active_lease_or_takeover(config.unit_id):
        log("quarantined unit still has an active lease/takeover; leave it")
    else:
        # 2) 只在本机 Worker 上做停止证明（项目锁 + SingletonLock/lockfile）
        try:
            confirm_local_browser_stopped(config, private_root)
        except CollectorError as exc:
            log("unit stays quarantined: isolation not proven: %s", exc)
        else:
            repo.recover_stopped_unit(
                config.unit_id,
                "collection-worker:" + worker_instance_id,
            )
            log("recovered quarantined unit after local isolation proof")
```

严格条件（缺一不可）：

1. `state='QUARANTINED'`；
2. `owner` 为空或 `lease_until` 已过期（无活跃租约）；
3. 无 `OPEN/ACKNOWLEDGED` 验证事件、无 `REQUESTED/ACTIVE/VERIFYING` 接管；
4. `confirm_local_browser_stopped()` 通过（项目 `flock` + SingletonLock/lockfile，不杀进程、不删锁）；
5. 当前 Worker 已注册且没有新鲜的其他 Worker（`register_worker_instance` 已保证；否则会先 `DUPLICATE_WORKER_FOR_UNIT`）；
6. **不按 `failure_reason` 字符串白名单过滤**：当前 `QUARANTINED` 只由 `acquire` 的 expired-owner 或 `release` 的 browser-unconfirmed 产生，两者在本地停止证明通过后都可回收；`failure_reason` 可能是 `EXPIRED_OWNER`，也可能是 session 的 evidence reason（如 `PROTECTED_PAGE_AND_ACCOUNT_VERIFIED`），用白名单会漏掉合法的 close-failure。若未来引入人工调查性隔离，必须新增独立标记并让本函数跳过，不能靠字符串猜测。

为什么这是最小必要修复：

- 复用现有 `confirm_local_browser_stopped()` + `recover_stopped_unit()`，不新增表、不新增迁移、不改 `acquire` 的 fail-closed 语义；
- 只在 Worker 启动时执行一次，不引入后台轮询，不自动打断人工接管；
- 恰好覆盖本次事故：gen3 在 11:28:40 启动时就会回收，11:36 的新任务不会失败；
- 不删除 Profile/锁、不杀 Chrome；证明失败时保持隔离。

需要新增/修改：

| 文件 | 变更 | 规模 |
|---|---|---|
| `backend/src/xingtu/worker.py` | 启动时调用回收；结构化日志 | ~20 行 |
| `backend/src/xingtu/repository.py` | `has_active_lease_or_takeover(unit)`（只读查询）或复用现有查询 | ~10 行 |
| `backend/tests/unit/test_worker_health.py` 或新测试 | 5 个分支：可回收/活跃租约/活跃接管/锁占用/PID 存活 | ~80 行 |
| `docs/F10-local-macos-windows.md` | 写明启动自动回收 + 手工 `recover-unit` | 文档 |
| `docs/development.md` | 已有 `recover-unit` 说明，补“Worker 启动会尝试一次” | 文档 |

**可选增强（不作为最小修复）**：

- `product_queries` 把 `RESOURCE_UNAVAILABLE: old browser requires isolation` 映射为可读的“执行单元上次浏览器退出未确认，需人工确认后恢复”，并在任务页显示恢复命令/按钮。
- 新增 `POST /api/execution-units/{unit}/recover`（仅 `local_development` 且 API 与 Worker 同机时可用；必须复用同一隔离证明 + CSRF + 审计）。这能让操作员不用 shell，但代码量更大（API + 前端 + 测试）。
- 修复 `promote_intake`：当配置单元 `state='QUARANTINED'` 时，不再静默分配；返回明确 `RESOURCE_UNAVAILABLE: NO_COLLECTION_UNIT` 或让任务等待可恢复单元。这是“更早暴露”，不是本 Bug 的必要修复。

### 8.3 预防再次发生（建议另立任务，需批准）

**Worker/Supervisor 的优雅停止**：

- `run_worker` 目前没有 SIGTERM 处理器；`scripts/m3_up.py` 的 `supervisor.stop()` 先 `proc.terminate()`（SIGTERM），`dev.sh stop` 也是 SIGTERM→等待 6 秒→SIGKILL。Python 默认 SIGTERM 直接终止，不会执行 `finally`；浏览器关闭可能需 20 秒（[runtime.py:548-558](../../backend/src/xingtu/runtime.py#L548-L558)），超过 supervisor 等待时间。
- 建议：POSIX 安装 SIGTERM 处理器，转为受控取消；Windows 使用 `CTRL_BREAK_EVENT` + 新进程组；supervisor 的等待时间覆盖浏览器关闭 + Temporal graceful shutdown；并保留启动回收作为 SIGKILL/断电兜底。
- 该改动涉及 Worker 生命周期和跨平台信号，风险高于 8.2，建议单独卡片、单独验收。

### 8.4 明确不建议

- 不要删除 `SingletonLock`/`SingletonCookie`/`SingletonSocket`/`.lock` 来“解决”问题；它们不是当前阻塞点，删除会掩盖真实占用。
- 不要 `kill` 所有 Chrome 或 `kill -9` Worker；个人 Chrome 与单元 Chrome 必须区分。
- 不要直接 SQL 改 `state/owner/lease/generation`；应走 `recover-unit`（有审计）。
- 不要自动重试/取消历史任务来“绕过”隔离；会丢失证据且不解决根因。
- `execution_units.profile_ref` 的旧路径不要用 raw SQL 直接改；若决定清理，应新增受控命令/迁移并审计，或让投影从 `UnitConfig` 派生。它不影响本次最小修复，但会误导后续排障。

## 9. 影响范围（按功能）

| 功能 | 影响 | 回归关注 |
|---|---|---|
| 正常采集 | 健康单元无变化；隔离单元被修复后恢复 | 正常 acquire 不得被回收逻辑影响；无隔离时不得写审计/改 generation。 |
| ExecutionUnit 状态监测 | 回收后 `QUARANTINED→SESSION_UNVERIFIED`；Worker 仍 ONLINE | API 投影、`actionable_reason`、UI 状态列。 |
| Chrome 生命周期 | 不启动/不杀/不删；只读证明 | `confirm_local_browser_stopped` 在 macOS/Windows 的 PASS/FAIL 分支。 |
| Browser Profile 隔离 | 复用现有 project flock + SingletonLock/lockfile | 锁被占用时必须保持隔离；不得删除锁。 |
| 单账号并发 | 恢复只在无新鲜 Worker/无活跃租约时执行 | 两个 Worker 同时启动仍应 `DUPLICATE_WORKER_FOR_UNIT`；不得出现双 Chrome。 |
| Lease/generation/owner | 回收 `generation+1`、清 owner/lease；下一次 acquire 再 `+1` | 旧 Activity 的迟到写入必须 `LEASE_LOST`；不得复用旧 generation。 |
| F10 人工接管/恢复 | 有 open takeover/verification 时**不回收**；回收后 F10 路径恢复 | 接管中重启 Worker 不得清掉接管；LOCAL_WINDOW 文案/接口不变。 |
| macOS | 本轮现场；POSIX 锁行为不变 | `recover-unit` 与启动回收实测。 |
| Windows | 未实测；使用 `msvcrt`/lockfile 分支 | 真实 Windows 主机验收，不得用静态测试代替。 |
| Temporal 任务终态 | 无 Workflow 改动；现有 30 秒循环恢复 | 不得引入历史重放不兼容；回收后任务应继续而非重跑数据。 |
| 达人数据/checkpoint/快照 | 回收不写业务数据；现有快照保留 | 383 无数据；2ff8ad00 的 1 位/1 快照不得变化。 |

## 10. 修复后的 Playwright + Chrome 端到端验收方案

> 原则：优先复用已存在的 `383474a1`（target=3，关键词“游戏集锦”，female，湖南），**不新建任务**；只有该任务被取消/不可恢复时才申请新建。验收前确认没有其他真实任务、没有活跃浏览器租约、没有 open takeover。

| # | 步骤 | 期望 | 证据 |
|---|---|---|---|
| 1 | 只读确认：`execution_units` 当前隔离；`confirm_local_browser_stopped` PASS；SingletonLock PID gone；profile lsof 0 | 无活旧浏览器 | 命令输出、DB 行 |
| 2 | 部署修复并**通过受管 supervisor**重启 Collection Worker（不要裸 kill） | 启动日志出现 `recovered quarantined unit after local isolation proof`；`audit_logs` 出现 `recover_stopped_unit:unit-local-mac-02` | worker 日志、audit |
| 3 | 确认单元 `SESSION_UNVERIFIED`、`owner=NULL`、`browser_stopped=true`、`generation` +1；Worker ONLINE | 状态机正确 | `GET /api/execution-units` |
| 4 | 等待 `383474a1` 下一次 30 秒重试（或触发一次 wake）；观察 `WAITING_FOR_RESOURCE → QUEUED/SEARCHING` | 任务取得执行权，开始 Chrome | Temporal history、任务页 |
| 5 | Playwright + 系统 Chrome：登录 `media-a`，打开 `/tasks/383474a1…`，等待阶段推进；截图 | 阶段 3→4/5/6；无 raw isolation 错误 | 截图、console/network |
| 6 | 若平台出现安全挑战：确认 `LOCAL_WINDOW` 提示、原 Chrome 保持、无第二个 Chrome；人工完成验证；点击完成 | `WAITING_FOR_VERIFICATION`；`session_version` 只 +1；同一 Context 恢复 | F10 UI、DB `session_version` |
| 7 | 采集完成/部分完成：检查 `task_creators`、`creator_snapshots`、`featured_*`、`media_objects`；检查 `valid_count`/失败步骤 | 有真实数据入库；页面展示一致；无重复 | DB 查询、任务页/达人页 |
| 8 | 检查终态：`COMPLETED` 或 `PARTIAL_COMPLETED`（含合理 `failure_reason`）；`completed_at` 有值 | 任务收口 | `GET /api/tasks/383…` |
| 9 | 资源收口：`owner=NULL`、`browser_stopped=true`、无 open verification/takeover；Worker ONLINE；单元 READY/NEEDS_VERIFICATION | 无残留 | DB、`GET /api/execution-units` |
| 10 | 负向回归：制造活跃租约/活跃接管/锁占用，分别启动 Worker | **不得**自动回收；保持隔离/接管 | 单测 + 集成测试 |
| 11 | 重启回归：在采集中重启 Worker（受管停止）；观察正常 release 或启动回收 | 不出现 `old browser requires isolation` 永久卡死 | 日志、DB |
| 12 | Windows（另一台实机）：同 1–9，使用测试单元 | 通过；否则如实 NOT TESTED | Windows 证据 |

建议的自动化命令（修复后）：

```bash
# 只读前置
python scripts/m3_up.py --status --with-collection --unit-config .runtime/units/local-dev-mac-02.json
# 采集后（在已登录的 Playwright context 内调用；不要复用明文 cookie 文件）
page.evaluate("fetch('/api/tasks/383474a1-40b6-4343-ac22-9a4efcdc6af7').then(r => r.json())")
```

Playwright 验收脚本可复用现有 `scripts/acceptance/run_f10_ui_acceptance.py` 的登录/导航模式，新增断言：任务页不出现 `old browser requires isolation`、阶段推进、`valid_count>0`、单元 `QUARANTINED` 消失。

## 11. 是否具备修复条件与审批事项

**具备进入修复阶段的条件**：

- 根因链、触发代码、当前状态、数据影响已用真实 DB/Temporal/进程/锁/前端证据闭合；
- 隔离证明已通过，当前无活旧浏览器、无活跃租约/接管；
- 修复可复用现有 `recover-unit`/`confirm_local_browser_stopped`，不需要 Schema 迁移或破坏性操作；
- 现有任务 `383474a1` 可在回收后继续，不需要新建任务。

**需要你批准的事项**（以下为 2026-10-24T12:07 诊断时点的审批请求；用户随后已批准并执行，实际结果见[修复报告](DIAG-02-fix-2026-10-24.md)）：

1. **立即回收**：批准对 `unit-local-mac-02` 执行 `xingtu recover-unit --config .runtime/units/local-dev-mac-02.json --actor …`。这会清 owner/lease、`generation+1`、`browser_stopped=true`，并写审计。若你希望先看修复代码再执行，也可以只批准代码修复，回收留到修复后由 Worker 启动自动完成。
2. **代码修复方案**：批准 8.2 的“Worker 启动隔离回收”（推荐），或选择 8.2 的可选 API/UI 按钮方案，或选择“只修文档/只人工回收”。8.2 会触碰执行单元隔离机制，必须单独授权。
3. **预防项**：是否同时批准 8.3 的优雅停止（SIGTERM/Windows CTRL_BREAK）作为独立卡片；若不批准，则先以启动回收兜底。
4. **验收任务**：批准继续使用 `383474a1` 做修复后真实验收（不新建任务）；如果该任务需要先取消，请明确，我会在取消前另取授权。
5. **清理项**（可与本次解耦）：是否批准修复 `execution_units.profile_ref` 旧路径、停用/修正 launchd `com.yumeng.xingtu.collection-worker`。两项均不影响本次根因，但会减少后续误判。
6. **补充信息**：11:23 左右你是否关闭/重启过 Collection Worker 的终端？这能关闭 5.3 的唯一未确认项，但**不是**继续修复的前置条件。

## 12. 修复实施与验收结果（2026-10-24 12:32 更新）

> 本节是诊断报告后追加的实施结果；详细证据见 [DIAG-02 修复与真实 Chrome 回归](DIAG-02-fix-2026-10-24.md)。

- **修复已实施**：`Repository.has_active_unit_claim()`（[repository.py:433-454](../../backend/src/xingtu/repository.py#L433-L454)）、`reconcile_quarantined_unit()`（[worker.py:728-788](../../backend/src/xingtu/worker.py#L728-L788)）、`run_worker()` 启动调用（[worker.py:791-796](../../backend/src/xingtu/worker.py#L791-L796)）；新增 6 个启动回收单测；未新增 Schema/迁移。
- **真实恢复**：新 Worker generation 5 于 12:17:39.662 启动，12:17:39.673 日志 `recovered quarantined unit unit-local-mac-02 after local isolation proof (reason=EXPIRED_OWNER, worker=b612f21a-…)`；`audit_logs` 437 记录回收；单元 `QUARANTINED → SESSION_UNVERIFIED`。**没有手动执行 `recover-unit`**。
- **首次尝试**：12:17:58 因 `Page.goto: net::ERR_NETWORK_CHANGED` 失败为 `PLATFORM_PAGE_CHANGED:BROWSER_ACTION_FAILED`，不是隔离错误；单元正常释放。
- **MCP + 真实 Chrome 回归**：12:23:25 通过 MCP 点击「重试失败步骤」；`QUEUED 12:23:32 → SEARCHING 12:23:51 → COLLECTING 12:23:57 → PARTIAL_COMPLETED 12:28:05`；`valid=2/2`、2 份快照、4 个精选集合、6 张卡片；单元最终 `READY`、`browser_stopped=true`、无 open verification/takeover。截图：[最终任务页](assets/diag02/fix-task-final.png)、[单元 READY](assets/diag02/fix-units-ready.png)、[达人详情](assets/diag02/fix-creator-detail.png)。
- **回归**：unit 321 passed；contract 39 passed；mypy 35 files；活跃租约/Profile 锁/重复 Worker/OPEN 验证事件负向分支均通过（详见修复报告）。
- **残余**：`completed_at` 仍为首次失败时间 12:17:58（既有行为）；封面 6/6 FAILED、`media_objects=0`（封面/存储环境）；`profile_complete_count=0`；Windows 实机与 F10 真实接管未测。卡片状态因此为 **待验收**，不是“全部完成”。

## 附录 A：关键代码位置

| 文件 | 行 | 作用 |
|---|---|---|
| [repository.py](../../backend/src/xingtu/repository.py#L648-L716) | 648–716 | `acquire()`：owner 过期/quarantine/browser_stopped 判定与错误抛出 |
| [repository.py](../../backend/src/xingtu/repository.py#L376-L405) | 376–405 | `recover_stopped_unit()`：隔离回收，清 owner/lease，`generation+1` |
| [repository.py](../../backend/src/xingtu/repository.py#L1088-L1145) | 1088–1145 | `release()`：正常释放会清 owner/lease/mode/current task |
| [browser_host.py](../../backend/src/xingtu/browser_host.py#L116-L166) | 116–166 | `BrowserHost.lease()`：acquire → open → finally release |
| [worker.py](../../backend/src/xingtu/worker.py#L293-L425) | 293–425 | `Activities.collect()`：acquire 与任务状态 |
| [worker.py](../../backend/src/xingtu/worker.py#L635-L658) | 635–658 | `RESOURCE_UNAVAILABLE → WAITING_FOR_RESOURCE` |
| [worker.py](../../backend/src/xingtu/worker.py#L725-L787) | 725–787 | `run_worker()`：注册 Worker 后直接启动，无单元回收 |
| [runtime.py](../../backend/src/xingtu/runtime.py#L590-L642) | 590–642 | `confirm_local_browser_stopped()`：项目锁 + SingletonLock/lockfile |
| [runtime.py](../../backend/src/xingtu/runtime.py#L548-L558) | 548–558 | `close_browser_context()`：20 秒关闭超时 |
| [product_repository.py](../../backend/src/xingtu/product_repository.py#L492-L520) | 492–520 | `promote_intake()`：只检查 task kinds，不检查 QUARANTINED |
| [workflow.py](../../backend/src/xingtu/workflow.py#L20-L60) | 20–60 | 非终态 30 秒重试；资源等待不终态 |
| [F10-local-macos-windows.md](../F10-local-macos-windows.md) | 状态/恢复节 | 写了 Worker OFFLINE/休眠，但未写 `recover-unit` |
| [development.md](../development.md#L178) | 178 | 已有 `recover-unit` 命令说明 |
| [AUTO-01.md](../tasks/AUTO-01.md) | 历史记录 | 同类“中断未确认→QUARANTINED→recover-unit”历史先例 |

## 附录 B：证据清单

- 截图：[task-383474a1.png](assets/diag02/task-383474a1.png)、[execution-units.png](assets/diag02/execution-units.png)。
- 结构化证据：[timeline.json](assets/diag02/timeline.json)（单元/任务/Worker 行、三份 Temporal 历史、隔离检查、回滚复现、Git HEAD）。
- 诊断阶段只读查询：PostgreSQL `execution_units`、`execution_unit_workers`、`root_tasks`、`task_attempts`、`task_checkpoints`、`task_creators`、`creator_snapshots`、`audit_logs`、`verification_events`、`browser_takeover_sessions`。
- Temporal：`collect/383474a1…`（231 events）、`collect/2ff8ad00…`（179）、`collect/60a67287…`（124）。
- 运行日志：`.runtime/logs/collection-worker.log`（诊断阶段 generation 3/4 启动；修复阶段 generation 5 启动/回收见修复报告）、`.runtime/logs/intake-worker.log`（11:36/11:48 派发）、`.runtime/logs/api.log`。
- 进程/锁：`os.kill(23355,0)` → gone；`lsof +D profile` → 0；`confirm_local_browser_stopped` → PASS；个人 Chrome PID 983 未使用单元 Profile。
- Git：HEAD `024f879`，分支 `快手_1024`；`024f879` 的 diff 已核对；工作区仅有本轮前已存在的 QA-01 文档/截图未提交改动（`docs/evidence/QA-01-positive-filters-2026-10-23.md`、`docs/tasks/QA-01.md`、未跟踪的 QA-01 重试证据与 `qa01-retry-trigger.png`），本轮未改动它们。

## 附录 C：诊断阶段未执行 / NOT TESTED（12:07 时点；修复后结果见第 12 节）

> 下表是诊断阶段的事实，保留以说明“当时为什么没有直接下结论”。用户批准后，修复、回收和真实 Chrome E2E 已执行，结果见 [修复报告](DIAG-02-fix-2026-10-24.md)。

| 项 | 诊断阶段原因 | 修复后状态 |
|---|---|---|
| 新建真实任务复现 | 用户明确要求先确认，不得擅自创建 | 未新建；使用既有 `383474a1`，通过 MCP 重试完成 |
| `recover-unit` 真实执行 | 会改 generation/lease，用户禁止未经确认 | 未手动执行；由新 Worker 启动回收完成（审计 437） |
| 修复后真实 Chrome 采集 | 尚未修复/授权 | 已执行；`PARTIAL_COMPLETED`，2 位有效/2 快照；详见修复报告 |
| 真实 F10 人工验证 | 需要平台挑战窗口与人工操作 | 本轮未出现挑战；F10 真实接管仍 **NOT TESTED** |
| Windows 实机 | 无 Windows 主机 | 仍 **NOT TESTED** |
| 单元/契约测试全量 | 诊断阶段未改代码；集成测试需 `XINGTU_TEST_DATABASE_URL` | unit 321 passed、contract 39 passed、mypy 35 files；集成测试用例已加但未运行 |
