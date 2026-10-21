# P1FIX-02：F10 后采集中断 / Workflow 失败不收口 / Heartbeat 诊断修复

状态：待验收
更新时间：2026-10-21T10:30:00+08:00
是否验收：否；已部署并用真实任务验证“失败收口 + checkpoint 发布 + generation fence”；但本轮又发现并修复 Temporal 心跳线程 P1 缺陷，慢网下租约心跳仍 fail-closed，需在直连网络复验完整采集。

## 目标与范围

修复真实任务 `11f9fc9c-ad06-4d41-9fde-c33bab168f47` 暴露的：

1. F10 人工验证后采集只完成 2/10；
2. `CollectF04F05V1` FAILED 但 root_task 永久 `COLLECTING`；
3. 失败时 checkpoint 中已采集的精选/达人数据未发布，计数不一致；
4. 45 秒 heartbeat timeout 缺乏诊断、同步 DB 调用可能阻塞 Temporal heartbeat。

不做：重构采集引擎、修改筛选/业务口径、变更 Schema、修改生产网络/NetworkProof、处理 noVNC/HTTP 80/证书、
部署或重试真实任务。

## 根因结论

### 已证实

- **任务终态缺口**：`worker.py` 的 `except asyncio.CancelledError` 仅在 `heartbeat_error` 存在时写任务终态；
  否则 re-raise。Temporal 在 heartbeat timeout/取消后判定 Workflow FAILED，root_task 仍 COLLECTING。
- **heartbeat 顺序缺陷**：旧 heartbeat 任务先执行同步 `host.heartbeat()`（psycopg + ensure_line），
  再调用 `activity.heartbeat(root)`；DB/网络一卡顿，Temporal 45 秒收不到心跳。
- **异常捕获缺口**：heartbeat 任务只捕获 `CollectorError`；`psycopg.OperationalError`、`TimeoutError`
  等会静默杀死 heartbeat 协程，`heartbeat_error` 保持空。
- **失败后未发布**：checkpoint 中 candidate 0 已有 8 个 modules + 两组 collections，
  但 `featured_collections/cards=0`、仅 1 份快照；原因是 Workflow 失败后没有执行 `finish`/publish，
  不是数据未采集。
- **F10 恢复本身是成功的**：challenge RESOLVED、takeover RESUMED、任务再次 LEASED，
  第二位达人 basic 已采集；失败发生在恢复约 11 分钟后，heartbeat/activity 取消，
  不是 takeover 无法重新获得浏览器。
- **候选身份未错位**：第二位 ID 736… 对应 checkpoint candidate first_position=1，
  与搜索响应候选列表一致；`SESSION_UNVERIFIED` 是取消后无当前进程 observation 的释放结果，
  不能证明 Profile/session 损坏。

### 高置信度/未证实

- 高置信度：Mac↔云端 PostgreSQL/Tailscale 或同步 DB 调用于 14:11:52 后阻塞，
  导致 heartbeat 停止；本轮其它 API/DB 查询也出现 60 秒级卡顿。
- 未证实：F10 人工选择导致候选污染、`CURSOR_INVALID` 是最终失败直接原因、Profile 损坏。
- 第二位“C位小师妹”行业标签为生活/食品饮料/汽车/3C，但其 ID 是搜索候选；
  仅凭标签不能判定筛选失败，本轮不修改筛选逻辑。
- `valid=true` 是既有 basic 阈值语义，不等于“完整采集”；`valid_count=2` 与
  `profile_complete_count=0` 的口径差异留待业务确认，不以代码强行改口径。

## 代码修复

| 文件 | 内容 |
|---|---|
| `backend/src/xingtu/worker.py` | 新增 `renew_lease()`：同步 lease 在 worker thread 中执行、10s 上限、异常转稳定 `CollectorError`；heartbeat 先发 Temporal heartbeat，再续租；heartbeat 捕获所有异常并记录 reason/latency；新增 `should_finalize_cancelled()`，仅在最后 attempt 收口且排除 worker_shutdown/cancel/paused/reset/not_found；未处理异常 attempt 4 也收口 |
| `backend/src/xingtu/browser_host.py` | 拆分 `heartbeat_lease()`（纯同步 DB）与 `heartbeat()`（lease + line），供线程安全续租 |
| `backend/src/xingtu/repository.py` | `edit(..., require_lease=False)`：保留 task/attempt fence，且仍校验 generation，旧 Worker 不得覆盖新 Worker；新增 `finalize_interrupted(..., lease_generation)`：幂等、按 valid 数落 PARTIAL/FAILED、发布 checkpoint 数据、拒绝覆盖终态 |
| `backend/src/xingtu/engine.py` | `finish(force=False, failure_reason=None)`：支持租约已失的强制收口、上传已采集快照、保留真实 failure_reason；正常 `finish()` 行为不变 |
| `backend/tests/unit/test_engine_finish.py` | 6 个测试：force/partial/completed/lease 要求/幂等 finalizer/generation fence |
| `backend/tests/unit/test_worker_heartbeat.py` | 4 个新测试：成功、timeout、RuntimeError 包装、CollectorError 保留 |
| `backend/tests/unit/test_worker_cancellation.py` | 7 个测试：attempt 预算、shutdown/cancel/paused 不收口 |
| `backend/tests/integration/test_interrupted_finalize.py` | 4 个真实 PostgreSQL 测试：终态/幂等/generation fence/checkpoint 发布/force finish |

## 本地自动化回归

- unit：**332 passed**
- contract：**33 passed**
- mypy：34 source files，Success
- ruff check/format：通过（87 files）
- frontend：6 files / 83 tests passed；build exit 0
- integration（真实 PostgreSQL，隔离库 `xingtu_test_p1fix`）：**95 passed, 4 skipped**
- 真实 F10/Playwright E2E：**未执行**；Mac Worker 已部署新代码，需下一轮授权。
- 新增 4 个真实 PostgreSQL 集成测试：finalize 终态/幂等、generation fence、checkpoint 发布快照、
  force finish 发布；全部通过。

证据：[修复报告](../evidence/p1-f10-heartbeat-fix-2026-10-20.md)、
[测试结果](../evidence/p1-f10-heartbeat-fix-2026-10-20/05-tests.txt)。

## 部署结果（2026-10-20 23:05）

- 部署前：无活动浏览器/lease；stuck 任务 `11f9fc9c...` 保持 `COLLECTING` v182，未修改。
- 备份：`.runtime/backups/p1fix-02-20261020/{current,pre-fix}` + SHA256SUMS。
- `launchctl kickstart -k`，`runs=2`，新 PID **20406**；启动日志
  `23:05:01 INFO xingtu.worker collection worker polling xingtu-unit-local-mac-02`。
- Temporal poller fresh=1（约 33 秒）；ExecutionUnit `ONLINE / SESSION_UNVERIFIED /
  UNAVAILABLE / STOPPED / IDLE`，owner NULL。
- 未自动重试 stuck 任务：`updated_at`/`task_dispatches` 未变化。
- 未重启/修改腾讯云 API/DB/Temporal/Redis/MinIO；未改 Schema；未删除历史数据。
- 部署后数据计数不变：task_creators=2、creator_snapshots=1、featured_collections=0、featured_cards=0、media_objects=34。
- 当前四个源文件 SHA256 已记录；运行进程启动晚于修改时间。
- 工作区范围：旧 Worker 21:31 启动；其它既有 modified 源文件 mtime ≤21:15，本轮仅四个目标文件在 22:37–22:49 修改，未额外引入未验证模块。

## 真实 E2E 复验结果（2026-10-20）

新任务 `b5a01709-8a4b-46bd-aa31-6494b0d9ce24`（宠物/10）结果：**FAIL / NO-GO**。

- P1 成功、P2 派发、Worker/Chrome 正常启动；20 候选；2 位 valid；
- 第一位 8 模块 + 2 精选已采集，第二位 basic；
- Workflow 15:29:53Z FAILED（heartbeat timeout，max attempts）；
- root_task 仍 `COLLECTING v135`，unit `SESSION_UNVERIFIED/generation 9/owner NULL/browser_stopped`；
- `creator_snapshots=0`、`featured_collections=0`、`featured_cards=0`，第一位已采集数据未发布；
- F10 本轮 `challenge_count=0`，**NOT TESTED**；
- 未发现候选 ID 错位；第二位筛选相关性未证实。

**新 P1-A（确定）**：attempt 4 cancellation details `not_found=True`，`should_finalize_cancelled()` 返回 False，
未调用 `_finalize_interrupted`，导致最终 attempt 后仍不收口；数据未发布。

**P1-B（残留）**：首次 heartbeat 11.4s 超时；attempt 2–4 无 heartbeat 日志、仅 `not_found`，
说明 `engine.guard()`/主流程同步 DB 调用仍可能阻塞 heartbeat 事件循环，P2-01 未完成。

按本轮授权：**未修改生产代码、未重试/取消/修复该任务、未创建第二个任务**。

证据：[真实 E2E 报告](../evidence/e2e-real-collection-run2-2026-10-20.md)

## 回归风险

- P1→P2 派发：未修改 intake/product_repository 派发逻辑；风险低。
- 无滑块正常采集：heartbeat 改为先 Temporal 后 DB、lease 线程化；需真实复测确认。
- ExecutionUnit 租约/session：正常 `finish()` 仍要求 lease；只有 cancellation 的 `force` 跳过 lease，
  且保留 task/attempt fence；需真实复测。
- 达人数据保存/快照/去重：`persist_creators` 仅在强制收口/正常 finish 发布，未改发布算法；
  需验证不重复快照。
- 任务状态：新增 cancellation 终态路径；正常路径不变；需验证并发取消幂等。

## 真实复验方案（部署已完成，待授权）

1. 代码已在 Mac Worker 工作区通过 `launchctl kickstart -k` 加载；云端镜像/API/DB Schema 未变。
2. 部署前已确认无活动浏览器/lease；备份见 `.runtime/backups/p1fix-02-20261020/`。
3. 下一轮由 DSH 用新的 `宠物/10` 任务做一次真实复验（不得重试当前 stuck 任务）。
4. 验收：F10 后能继续；失败时 root_task 正确 PARTIAL/FAILED 且有 reason；checkpoint 数据发布；
   `valid_count/profile_complete/featured_complete` 与快照一致；无重复快照/候选错位。
5. 回滚：恢复修改前 worker.py/engine.py/repository.py/browser_host.py，重启 Worker；不删数据。
6. 当前 stuck 任务 `11f9fc9c...` 保持原状；如需修复性收口，另行提交方案和影响范围审批。

## 状态历史

- 2026-10-20：待办 → 进行中；开始证据审查和最小修复。
- 2026-10-20：进行中 → 待验收；本地/隔离 PostgreSQL 测试通过，Mac Worker 已部署（PID 20406）。
- 2026-10-20：待验收 → **阻塞**；真实 E2E 复验 2/10、Workflow FAILED 而任务仍 COLLECTING、0 快照；发现 P1-A/P1-B，按授权未修复。
- 2026-10-21：阻塞 → **待验收**；P1-A 代码修复与单元/集成测试完成；等待授权部署 + 真实 `宠物/10` 复验；性能残余项转 PERF-01。


## 2026-10-21 后续修复（P1-A 代码缺口已关闭，待部署/真实复验）

第二次真实 E2E 后，按授权在新一轮只读诊断中完成最小修复（详见 [PERF-01](PERF-01.md) 与[性能报告](../evidence/hybrid-performance-diagnosis-2026-10-21.md)）：

- **P1-A 已修复**：`should_finalize_cancelled()` 在 `attempt >= max_attempts` 时对 `not_found=True` 返回 True；`timed_out` 同样收口；`worker_shutdown`/`cancel_requested`/`paused`/`reset` 仍不收口，`attempt < 4` 仍不提前收口。
- **收口链**：`_finalize_interrupted` 优先 `engine.finish(force=True)`（发布 checkpoint 已采集数据），失败退化 `finalize_interrupted(publish=True)`，再失败 `publish=False` 至少落 PARTIAL/FAILED；最后失败写 error 日志。
- **Heartbeat**：新增 `TemporalHeartbeat` 独立 daemon 线程（10 s、`contextvars.copy_context`、60 s loop watchdog）；`Temporal heartbeat` 不再依赖 asyncio loop；lease 续租仍 `to_thread` + 10 s，并加 `lock_timeout=8 s`，不会无限排队。
- **性能根因**：旧 hot path 每模块至少 7 次完整 checkpoint 传输；远程 `Repository.get()` 实测 7.7–8.3 s，本地 14.5 ms；已改为 `record_progress` 服务端小增量 + `candidate_module_complete`/`candidate_valid` 小查询，每模块完整传输 ≥7 → 1。
- **测试**：单元 **346 passed**、契约 **33 passed**、隔离 PostgreSQL 集成 **101 passed / 4 skipped**、mypy/ruff 通过。
- **未做**：未部署、未重启正式 Worker、未创建真实任务、未对历史任务执行收口/发布。两个历史任务在本轮开始时已是 `CANCELLED`（15:34Z），非本轮写入。
- **剩余风险**：单次完整 `edit` 仍随 checkpoint 增长；0.6 Mbps 级链路下 10 位目标仍可能较慢；结构性方案（带宽/checkpoint）待用户确认。真实 `宠物/10` 复验需单独授权。


## 2026-10-21 性能专项验证后续（Heartbeat 缺陷修复）

[PERF-02](PERF-02.md) 专项验证发现并修复一个真实缺陷：上一版 `TemporalHeartbeat._loop_responsive()` 先等待事件循环执行回调、再发送心跳；当 loop 被完整 checkpoint edit 阻塞 5.6–27.7 s 时，心跳线程会一起等待，重新把 Temporal heartbeat 绑回 loop。

修复：**先发送 `activity.heartbeat()`**，再用 `loop.call_soon_threadsafe(_mark_loop_alive)` 记录 loop 最近可运行时间；仅当 loop 连续 **60 s** 不可运行时停止心跳，让 Temporal 自己的 45 s timeout 接管。每个 attempt 仍只有一个 daemon 线程，`stop()` 设置 Event 并 join 5 s。

新增测试：Activity context 传递、正常完成、异常、取消、token 失效、短阻塞仍心跳、永久卡死停止、20 次 start/stop 无线程堆积、已释放 lease → LEASE_LOST。另在模块/精选观测之间加入 `asyncio.sleep(0.001)`，让 lease 心跳/取消可在模块之间运行。

测试：单元 **352 passed**、契约 **33 passed**、隔离 PostgreSQL 集成 **103 passed / 3 skipped**、mypy/ruff 通过。

报告：[perf-verification-2026-10-21.md](../evidence/perf-verification-2026-10-21.md)。仍未部署、未真实复验；两个历史任务保持 `CANCELLED`。

## 2026-10-21 代码部署（真实任务待网络恢复）

- 已备份 `.runtime/backups/perf03-20261021/{deployed-baseline,candidate}` + SHA256。
- 无活动 lease/root task 前提下，`launchctl kickstart -k` 加载新代码：新 PID **54216**，runs=3；启动日志 `collection worker polling xingtu-unit-local-mac-02`；Temporal poller `alive=True, fresh_pollers=2`。
- **真实 `宠物/10` 未创建**：Mac 当前手机 WiFi 为对称 NAT，Tailscale DERP(sea) 378 ms，PostgreSQL 连接超时；待 direct 网络恢复后执行。
- 证据：[deployment-2026-10-21.md](../evidence/deployment-2026-10-21.md)。

## 2026-10-21 真实复验：心跳修复本身存在 P1 缺陷，已修复并验证

- 真实 `宠物/10` 首个 Activity 即报
  `temporal heartbeat failed … type=RuntimeError` + `coroutine '_ActivityWorker._heartbeat_async' was never awaited`。
  根因：`TemporalHeartbeat` 守护线程直接调用 `activity.heartbeat()`；Temporal Python SDK 在异步 Activity 中
  通过 `asyncio.create_task` 发送心跳，非事件循环线程调用必然 `RuntimeError`，于是**没有心跳**，45s 超时后每次尝试都被重派。
  既有单测用 `ActivityEnvironment` 掩盖了该问题（其 heartbeat 可跨线程）。
- 修复（最小、保留 fail-closed）：线程只把 `activity.heartbeat` 以捕获的 Activity Context 调度到事件循环线程；
  异步租约心跳恢复循环侧 `activity.heartbeat(root)`（失败只告警，不冒充租约失败）；测试改为断言“SDK 调用只发生在事件循环线程”。
- 文件：`backend/src/xingtu/worker.py`、`backend/tests/unit/test_worker_heartbeat.py`；备份/哈希见
  `.runtime/backups/qa-hb-20261021/`。修复后 `worker.py` SHA256 `85ff1053…`（原 `639377a7…`）。
- 验证：heartbeat 15 passed、unit 352 passed、contract 33 passed（`PLAYWRIGHT_BROWSERS_PATH=.runtime/browsers`）、mypy/ruff 通过；
  真实环境 `pending_activities[].last_heartbeat` 持续刷新（09:44:13 / 10:07:06 / 10:14:13），Activity 存活远超 45s。
- 复验仍然失败的原因不同：慢网下**租约心跳** `HEARTBEAT_TIMEOUT`（DB 单次操作 10.0–11.1s > 10s 预算），
  属既有安全语义，未放宽。终态正确收口 `PARTIAL_COMPLETED + HEARTBEAT_TIMEOUT`、checkpoint 快照已发布，
  证明本卡“失败收口/发布/generation fence”修复有效。
- 证据：[e2e-real-collection-2026-10-21.md](../evidence/e2e-real-collection-2026-10-21.md)。
