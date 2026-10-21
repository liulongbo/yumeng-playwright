# F10 后采集中断 / Heartbeat / 任务终态修复报告

- 修复日期：2026-10-20（UTC+08）
- 关联真实任务：`11f9fc9c-ad06-4d41-9fde-c33bab168f47`
- 关联缺陷报告：[e2e-real-collection-2026-10-20.md](e2e-real-collection-2026-10-20.md)
- 修复卡：[P1FIX-02](../tasks/P1FIX-02.md)
- 范围：本地代码、单元/契约/前端/隔离 PostgreSQL 集成回归；**已部署 Mac Worker；未重试真实任务、未改数据库/Schema**
- 结论：**本地与集成测试通过，Mac Worker 已部署；待真实 F10/10 复验**；stuck 任务保持原状作为证据。

---

## 1. 根因分析

### 1.1 关键时间线（已证实）

| UTC | 事件 |
|---|---|
| 13:46:09 | 任务创建；P1 成功 |
| 13:46:24 | ExecutionUnit LEASED，项目 Chrome 启动 |
| 13:47:57 | 滑块触发，`WAITING_FOR_VERIFICATION` |
| 13:48:17 | F10 takeover ACTIVE |
| 13:57:02 | 人工完成滑块，QA 点击“我已完成验证” |
| 13:57:12 | challenge `RESOLVED`，takeover `RESUMED` |
| 13:57:18 | 第一个 `collect_segment_v1` 完成（等待验证前） |
| 13:57:48 | Workflow 定时器结束，调度下一次 activity |
| 13:57:51 | ExecutionUnit 再次 `LEASED`，采集恢复 |
| 14:08:33 | 已持久 2 位达人草稿（第 2 位 basic 完成） |
| 14:09:32～14:11:29 | Worker 日志 attempt 1–3 failed |
| 14:11:41 | Temporal 记录 activity attempt 4 started |
| 14:11:52 | `execution_units.last_heartbeat_at` 最后更新 |
| 14:12:26 | Temporal `ActivityTaskTimedOut`（heartbeat） |
| 14:12:31 | `CollectF04F05V1` **FAILED**（max attempts） |
| 之后 | root_task 仍 `COLLECTING` v182；unit `SESSION_UNVERIFIED` generation 5 |

Temporal History：event 16 调度 → event 17 attempt 4 start → event 18 timeout → event 22 Workflow failed。
Worker 日志 4 次 `Completing activity as failed`，traceback 尾部均为
`asyncio.CancelledError: Activity cancelled`，最后位于 `page.goto` / `check_session` / `locator.is_visible`。

### 1.2 已证实根因

**A. 任务终态缺口（直接导致 root_task 永久 COLLECTING）**

修复前 `worker.py`：

```python
except asyncio.CancelledError:
    if heartbeat_error and engine:
        return engine.record_error(heartbeat_error)
    raise
```

Temporal 在 heartbeat timeout 后取消 Activity；若 `heartbeat_error` 为空，代码直接 re-raise，
不会写 root_task 终态。Workflow 随后 FAILED，但产品任务仍是 `COLLECTING`。

**B. Heartbeat 发送顺序错误**

旧 heartbeat 任务每 15 秒执行：

```text
await host.heartbeat()      # 同步 psycopg + ensure_line
activity.heartbeat(root)    # 之后才发送 Temporal heartbeat
engine.guard()
```

`host.heartbeat()` 是同步 PostgreSQL/Tailscale 调用；一旦卡顿，Temporal 45 秒内收不到心跳。
`last_heartbeat_at=14:11:52` 到 timeout `14:12:26` 约 34 秒，之后无 DB 心跳，与该路径一致。

**C. Heartbeat 异常未捕获**

heartbeat 任务只捕获 `CollectorError`；`psycopg.OperationalError`、`TimeoutError` 等会静默杀死协程，
`heartbeat_error` 保持为空，最终走 A 的 re-raise 路径。

**D. 失败后未发布 checkpoint 数据**

checkpoint 中 candidate 0 已有 8 个 modules + 两组 collections，但
`creator_snapshots=1`、`featured_collections=0`、`featured_cards=0`。
这不是“未采集”，而是 Workflow 失败后没有执行 `finish`/`persist_creators(publish=True)`。

### 1.3 F10 恢复：假设被排除，不改其逻辑

证据表明 F10 恢复**本身成功**：

- challenge `RESOLVED`、takeover `RESUMED`；
- 任务重新 `QUEUED/LEASED`；
- 第二位达人 basic 实际采集并持久化；
- 第二位 ID `736…225` 对应 checkpoint candidate `first_position=1`，与搜索响应候选一致；
- `CURSOR_INVALID` 触发既有 rescan 分支，被正常处理，没有抛错；
- `SESSION_UNVERIFIED` 是 Activity 取消后没有当前进程 observation 的释放 disposition，
  不能证明 Profile/session 损坏。

因此**没有修改 F10 接管/恢复逻辑**。本轮修复的是恢复后 heartbeat/终态问题，避免把“恢复成功但随后超时”
误判为 F10 失败。若真实复验仍出现恢复后无法继续，再根据新证据单独处理。

### 1.4 数据完整性/筛选/计数

- `valid=true` 是既有 **basic 模块阈值**语义，不是“完整采集”；`valid_count=2` 与
  `profile_complete_count=0` 的口径差异是既有设计，不以代码强行改变业务定义。
- 第二位“C位小师妹”标签为生活/食品饮料/汽车/3C，但其 ID 是搜索候选 `first_position=1`；
  仅凭行业标签不能证明筛选失败，**本轮未修改筛选逻辑**；需在真实复验时结合平台搜索语义核对。
- 第一位“一只平安喵”的精选数据已在 checkpoint，但未发布；修复后的强制收口会发布已有数据，
  不补采、不伪造。
- 未发现 candidate ID 与实际达人 ID 错位；未发现跨达人数据串写。

### 1.5 未证实/未解决

- heartbeat 停止的底层触发（PostgreSQL/Tailscale 延迟 vs 其他同步阻塞）未完全证实；
  本轮通过顺序调整、线程化 lease、超时/异常日志和终态收口，避免“静默卡死”和“永久 COLLECTING”。
- 若网络持续不稳定，任务仍可能以 `PARTIAL_COMPLETED` 正确收口，而不是完成 10 位；
  这属于真实环境限制，不应通过延长 timeout 掩盖。
- 远程 noVNC、HTTP 80、证书、安全头不在本轮范围。

---

## 2. 代码修复

| 文件 | 修改 | 理由 |
|---|---|---|
| `backend/src/xingtu/worker.py` | 新增 `renew_lease()`；heartbeat 先发 Temporal heartbeat，再线程化续租；捕获所有异常并记录 reason/elapsed；新增 `should_finalize_cancelled()`：worker_shutdown/cancel/paused/reset/not_found 不收口，heartbeat timeout 仅在最后重试预算（attempt 4）收口；`CancelledError` 走终态收口；未处理异常在 attempt 4 也收口 | 防止同步 DB 卡顿饿死 Temporal heartbeat；保留 Temporal 重试机会；取消/重试耗尽后不永久 COLLECTING |
| `backend/src/xingtu/browser_host.py` | 拆分 `heartbeat_lease()`（纯同步 DB）和 `heartbeat()`（lease + line） | 让 lease 续租可在 worker thread 中执行，不阻塞事件循环 |
| `backend/src/xingtu/repository.py` | `edit(..., require_lease=False)` 仍校验 generation；新增 `finalize_interrupted(..., lease_generation)` | 取消时 lease 可能已释放；保留 task/attempt/generation fence，旧 Worker 不得覆盖新 Worker；幂等落 PARTIAL/FAILED 并发布已持久数据 |
| `backend/src/xingtu/engine.py` | `finish(force=False, failure_reason=None)` | 强制收口复用正常 finish 的计数/publish 逻辑；保留真实失败原因；正常路径不变 |
| `backend/tests/unit/test_engine_finish.py` | 6 个测试 | force/partial/completed/lease 要求/幂等 finalizer/generation fence |
| `backend/tests/unit/test_worker_heartbeat.py` | 4 个测试 | 成功、timeout、RuntimeError 包装、CollectorError 保留 |
| `backend/tests/unit/test_worker_cancellation.py` | 7 个测试 | timeout 仅在最后 attempt 收口；shutdown/cancel/paused/reset 不收口 |
| `backend/tests/integration/test_interrupted_finalize.py` | 4 个真实 PostgreSQL 测试 | 终态/幂等/generation fence/checkpoint 发布/force finish |

关键行为：

- Temporal heartbeat 现在**先**发送，lease/line 续租在 `asyncio.to_thread` 中执行，10 秒上限；
- DB/网络异常 → `CollectorError("RESOURCE_UNAVAILABLE", "HEARTBEAT_*")`，heartbeat 记录 warning；
- Activity 取消 → `engine.finish(force=True, failure_reason=...)`：
  - 目标/完整度满足 → `COMPLETED`；
  - 未满足 → `PARTIAL_COMPLETED`（有 valid 数据）或 `FAILED`（无数据）；
  - 发布 checkpoint 中已采集的 snapshot/featured 数据；
- publish 失败时退化为 `finalize_interrupted(..., publish=False)`，至少落终态，绝不永久 COLLECTING；
- 正常 `finish()` 仍要求 lease，行为不变；
- `should_finalize_cancelled()` 保证 Temporal 仍有重试预算时不提前收口；Worker shutdown/user cancel 不写成 FAILED；
- `require_lease=False` 仍要求 generation 匹配，旧 Worker 不能覆盖新 Worker。

---

## 3. 自动化测试结果

| 检查 | 命令 | 结果 |
|---|---|---|
| 后端单元 | `.venv/bin/pytest backend/tests/unit -q` | **332 passed** |
| 后端契约 | `PLAYWRIGHT_BROWSERS_PATH=... .venv/bin/pytest backend/tests/contract -q` | **33 passed** |
| 真实 PostgreSQL 集成 | `XINGTU_TEST_DATABASE_URL=...pytest backend/tests/integration -q` | **95 passed, 4 skipped** |
| 类型 | `.venv/bin/mypy backend/src` | Success，34 files |
| 后端 lint/format | `ruff check backend` / `format --check` | 通过，87 files |
| 前端测试 | `npm --prefix frontend test` | 6 files / **83 tests passed** |
| 前端构建 | `npm --prefix frontend run build` | exit 0 |
| 新增 F10/heartbeat 单元 | test_engine_finish.py + test_worker_heartbeat.py + test_worker_cancellation.py | **17 passed** |
| 新增 PostgreSQL 集成 | test_interrupted_finalize.py | **4 passed** |

新增测试覆盖：

- force finish 跳过 lease 但保留 task/attempt fence；
- force 时目标未达成 → PARTIAL，目标/完整度满足 → COMPLETED；
- 无 valid 数据 → FAILED；
- 重复取消幂等，不重复发布/覆盖终态；
- heartbeat 成功、timeout → `HEARTBEAT_TIMEOUT`、RuntimeError → `HEARTBEAT_RuntimeError`、
  CollectorError 原样保留。

**未执行**：

- 真实 Playwright + Chrome F10 复验：已部署新代码，但需下一轮授权；
- 真实 `宠物/10` 复验：未授权，不创建任务。

真实 PostgreSQL 集成使用本机 Docker `postgres:18.3` 隔离库 `xingtu_test_p1fix`，fixture 随机 schema + 迁移后 drop；未接触正式业务库。

> 上述 mock/单元测试不能替代部署后的真实 F10 复验。

证据：[测试结果](p1-f10-heartbeat-fix-2026-10-20/05-tests.txt)、
[时间线](p1-f10-heartbeat-fix-2026-10-20/01-timeline.txt)、
[heartbeat 根因](p1-f10-heartbeat-fix-2026-10-20/02-heartbeat-root-cause.txt)、
[F10 结论](p1-f10-heartbeat-fix-2026-10-20/03-f10-findings.txt)、
[数据语义](p1-f10-heartbeat-fix-2026-10-20/04-data-semantics.txt)。

---

## 4. 回归风险

| 路径 | 影响 | 评估 |
|---|---|---|
| P1 → P2 派发 | intake/product_repository 未改 | 低 |
| 无滑块正常采集 | heartbeat 顺序/lease 线程化；正常 `finish()` 不变 | 中，需真实复验 |
| ExecutionUnit 租约/session | 仅 cancellation 的 force 路径跳过 lease；正常路径仍 fence | 中，需验证 |
| 达人数据保存/快照/去重 | 强制收口复用 `persist_creators`，不新增发布算法 | 中，需验证不重复快照/发布 |
| 历史快照/任务 | 不修改已存在数据；stuck 任务保持原状 | 低 |
| 任务状态并发 | `finalize_interrupted` 加 task 行锁、attempt fence、幂等 | 低-中，需并发取消测试 |
| 现有 F10 恢复 | 未修改 takeover/challenge 逻辑 | 低 |

---

## 5. 专项风险复核与部署结果

### 5.1 三项关键风险

| 风险 | 结论 | 证据 |
|---|---|---|
| Activity 取消/Workflow 失败/重试耗尽 | **PASS（本地+真实 DB）** | timeout 仅在 attempt 4 收口；worker_shutdown/cancel/paused/reset/not_found 不收口；未处理异常 attempt<4 继续重试；attempt 4 收口 |
| 租约/并发安全 | **PASS（真实 DB）** | `require_lease=False` 仍校验 generation；新 owner acquire 后旧 generation 编辑抛 `LEASE_LOST:GENERATION_FENCED`；finalizer task/attempt fence + 幂等 |
| Heartbeat 协同 | **PASS（代码/单元）** | 先发 Temporal heartbeat；lease 线程化 10s 上限；DB/异常触发 abort；worker_shutdown 不误收口；每 attempt 最多一个后台续租线程 |

### 5.2 复核中发现并修复的新问题

1. **会提前收口 Temporal 仍可重试的 Activity**：初版在任何 CancelledError 都终态收口。
   已增加 attempt 预算判断：attempt<4 时 re-raise，让 Temporal 重试；仅 attempt 4 收口。
2. **worker shutdown 可能被误写 FAILED/PARTIAL**：已使用 `activity.cancellation_details()` 区分
   `worker_shutdown`、`cancel_requested`、`paused/reset/not_found`。
3. **`require_lease=False` 缺少 generation fence**：旧 Worker 可能在 lease 释放后覆盖新 Worker；
   已增加 generation 匹配，旧 generation 直接拒绝。
4. **未处理异常（如 psycopg）可能绕过终态**：attempt 4 时走统一 `_finalize_interrupted`；
   attempt<4 继续重试。

### 5.3 部署结果（已完成）

- 部署前：unit `SESSION_UNVERIFIED / owner NULL / browser_stopped=true`；无活动浏览器；
  stuck 任务 `11f9fc9c...` 仍 `COLLECTING` v182，未修改。
- 备份：`.runtime/backups/p1fix-02-20261020/{current,pre-fix}`，含四个源文件与 SHA256SUMS。
- 部署：`launchctl kickstart -k`，launchd `runs=2`，新 **PID 20406**；
  进程命令指向 `/Users/Longbo/Developer/YUMENG/.venv/bin/xingtu worker --config ...`。
- 启动后日志：`2026-10-20 23:05:01,345 INFO xingtu.worker collection worker polling xingtu-unit-local-mac-02`；
  无 import/启动错误（旧 traceback 为历史日志）。
- Temporal poller：`xingtu-unit-local-mac-02` fresh=1，约 33 秒；旧 poller 已随 180 秒 TTL 消失。
- ExecutionUnit：`ONLINE / SESSION_UNVERIFIED / UNAVAILABLE / browser_stopped=true / IDLE`，owner NULL。
- 未自动重试 stuck 任务：任务 `updated_at` 仍为 14:12:16Z，`task_dispatches.sent=true`、
  `workflow_started_at=13:46:10Z` 未变化。
- 未重启/修改腾讯云 API/DB/Temporal/Redis/MinIO；未改 Schema；未删除历史任务/达人/快照。
- 部署后数据计数仍为 task_creators=2、creator_snapshots=1、featured_collections=0、featured_cards=0、media_objects=34。
- 当前源文件 SHA256 已记录；运行进程启动时间 23:05:01 晚于四个源文件修改时间。
- 工作区范围：旧 Worker 21:31:30 启动；其它既有 modified 源文件 mtime ≤21:15（已加载），本轮仅四个目标文件 mtime 22:37–22:49；未额外引入未验证模块。
- 部署证据：[06-deployment.txt](p1-f10-heartbeat-fix-2026-10-20/06-deployment.txt)

### 5.4 真实复验计划（待授权）

经你授权后，重新创建 **1 个** `宠物/10` 任务；重点验证：
F10 后是否继续；失败时是否 PARTIAL/FAILED 且有 reason；checkpoint 数据是否发布、快照/计数一致；
不重复/不串写；前端/Temporal/DB 一致。不得重试 stuck 任务。

### 5.5 回滚

恢复 `.runtime/backups/p1fix-02-20261020/pre-fix/` 四个文件，`launchctl kickstart -k` 重启 Worker；
不删数据/快照；stuck 任务保持。

---

## 6. 结论

- P1-01：**F10 恢复本身成功**，未发现需要修改 F10 的确定证据；未做无依据重构。
- P1-02：**已修复**任务终态缺口（取消/心跳超时 → PARTIAL/FAILED，发布已持久数据）。
- P2-01：**已修复可复现的 heartbeat 代码缺陷**（顺序、线程化、异常捕获、日志）；底层网络触发待真实复验。
- P1-03：**已修复失败后未发布 checkpoint 数据的问题**；`valid`/完整度口径与第二位筛选相关性
  未擅自改变，保留业务确认。
- 本地单元/契约/前端与真实 PostgreSQL 集成测试通过，Mac Worker 已部署新代码；
  **真实 F10/10 复验尚未执行**；当前结论为“修复已部署、待真实验收”，不是“真实采集通过”。
