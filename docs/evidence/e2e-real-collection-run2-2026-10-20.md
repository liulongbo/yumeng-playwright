# 真实「宠物 / 10」E2E 复验（P1FIX-02 部署后）

- 日期：2026-10-20
- 新任务 ID：`b5a01709-8a4b-46bd-aa31-6494b0d9ce24`
- 环境：https://xingtu.yumeng.live；unit-local-mac-02；LOCAL_DEVELOPMENT；Mac WiFi
- 真实任务数量：**1 个**（未创建第二个）
- 结论：**NO-GO**
- P1FIX-02 真实环境验收：**FAIL**
- E2E-01：**保持阻塞，不可解除**

本轮严格遵守授权：未重试/取消历史任务，未创建第二个真实任务，未修改生产代码/Schema/账号/Cookie/Profile，未修复性收口新任务。

---

## 1. 新任务与执行链路

| 阶段 | 证据 |
|---|---|
| 前端提交 | 2026-10-20T15:16:03Z，keyword=宠物，target_count=10，只提交一次 |
| P1 | deepseek-flash 成功，input_tokens=16073，output_tokens=88，latency_ms=1235 |
| FilterPlan | keyword=宠物，target_count=10，capability=xingtu-ad-creator-square-v2，validation_errors=[] |
| P2 | P2-1/search/profile 任务创建；task_dispatches `collect/b5a01709...` sent=true，workflow_started_at=15:16:07Z |
| Temporal | `CollectF04F05V1`，run `01a159e2-52a2-74fa-9aef-60fbff57baf2` |
| Worker | Mac Worker PID 20406（P1FIX-02 代码）；15:16:10Z 启动项目 Chrome，profile `.runtime/profiles/unit-local-mac-02` |
| Chrome | 真实访问巨量星图；20 个候选；未发生 F10 |

**结果：** Workflow 于 **2026-10-20T15:29:53Z FAILED**（Activity task timed out / heartbeat），
但 root_task 仍为 **COLLECTING v135**，前端仍显示“采集中”。

---

## 2. 采集与数据完整性

### 实际结果

- 发现候选：**20**
- 有效达人 `task_creators`：**2**（均 `valid=true`）
- 资料完整：**0**
- 已发布快照：**0**
- 精选集合：**0**
- 精选卡片：**0**
- PostgreSQL `media_objects`：**68**
- MinIO `xingtu-covers` 对象：**68**

### 达人

| platform_creator_id | position | 状态 | modules | collections | snapshot |
|---|---|---|---|---|---|
| 6983857505726103560（一只平安喵） | 0 | done，valid=true | 8 | excellent_reach、excellent_seeding | **NULL** |
| 7360610271510921225（C位小师妹） | 1 | collecting，valid=true | basic | 无 | **NULL** |

第一位达人的 8 个模块与两组精选已在 checkpoint 中采集完成；第二位是搜索候选 basic。
但由于 Activity 未执行终态发布，`creator_snapshots=0`、`featured_collections=0`、`featured_cards=0`。
68 个封面已进入 media_objects/MinIO，但没有快照引用，属于**未发布数据**。

前端显示“2 位有效 / 0 资料完整 / 0 精选 / 0 位可查看”，任务仍“采集中”；与数据库
`task_creators=2、snapshots=0` 的“未发布”状态一致，但与 `valid=true` 的展示语义冲突。

### 候选关联与筛选

- 两位 `platform_creator_id` 均与 checkpoint 候选及 `task_creators` 关联一致；
  **未发现候选 ID 错位、跨达人模块/精选串写**。
- 第二位仍是搜索响应 `first_position=1` 的候选；其标签为生活/食品/汽车等，
  **不能仅凭标签判定筛选失败**；本轮没有证据证明候选污染或人工干预（F10 未触发）。
- 第一位与第二位数据在现有 checkpoint/任务归属上分离。

---

## 3. Heartbeat / lease / Temporal

### 正常阶段

15:17–15:26 UTC 期间 `execution_units` 约每 15 秒续租，`lease_until` 持续前移；
样例：

- 15:18:47 / last 15:17:04
- 15:19:19 / last 15:17:21
- 15:20:30 / last 15:18:32
- 15:22:46 / last 15:20:48
- 15:25:44 / last 15:23:46
- 15:28:10 / last 15:26:12

### 异常阶段

Worker 日志（本地 UTC+08，对应 UTC）：

| 本地时间 | 现象 |
|---|---|
| 23:26:21 | `activity heartbeat failed reason=RESOURCE_UNAVAILABLE: HEARTBEAT_TIMEOUT elapsed=11.4s` |
| 23:26:36 | attempt 1 `cancellation deferred`（details=None，heartbeat_error 存在；attempt<4）→ activity failed |
| 23:27:58 | attempt 2 `not_found=True, timed_out=True`，heartbeat=None → deferred（attempt<4） |
| 23:28:50 | attempt 3 `not_found=True, timed_out=False`，heartbeat=None → deferred（attempt<4） |
| 23:29:55 | attempt 4 `not_found=True, timed_out=False`，heartbeat=None → **deferred（未收口）** |

Temporal history 在 final attempt（attempt 4）记录：

- Activity scheduled 15:16:07，heartbeat_timeout=45s，retry maximum_attempts=4；
- attempt 4 started 15:29:06，last_failure=activity Heartbeat timeout；
- 15:29:51 `ACTIVITY_TASK_TIMED_OUT`，retry_state=MAXIMUM_ATTEMPTS_REACHED；
- 15:29:53 workflow FAILED。

**关键异常：** attempt 4 已经是最后重试，但 cancellation details 同时带 `not_found=True`；
`should_finalize_cancelled()` 因 `not_found` 返回 False，未调用 `_finalize_interrupted`，
因此没有 PARTIAL/FAILED 终态、没有发布 checkpoint、root_task 永久 COLLECTING。

### 对 P1FIX-02 的判断

- attempt 门控（attempt<4 延迟收口）**生效**：attempt 1–3 未被提前写成终态；
- 但 **attempt 4 的 `not_found` 分类错误**，导致最终不收口；
- 第一次 heartbeat 超时是 lease/DB 续租 11.4s；attempt 2–4 没有 heartbeat 日志，
  说明 heartbeat 协程/事件循环仍可能被同步 DB 调用阻塞；`engine.guard()` 以及主流程的
  `persist_creators`/`repo` 调用仍在事件循环中执行，这是 P2-01 未完成的部分。
- 因此 P1FIX-02 **未通过真实环境验收**，且不是单纯外部网络问题；存在确定的终态分类缺陷。

---

## 4. Workflow 与产品任务最终状态

| 对象 | 状态 |
|---|---|
| Temporal Workflow | **FAILED**，close 15:29:53Z |
| root_task | **COLLECTING v135**，updated_at 15:29:33Z |
| ExecutionUnit | **SESSION_UNVERIFIED**，generation=9，owner=NULL，browser_stopped=true，last_heartbeat_at=15:29:53Z |
| 项目 Chrome | 已无进程 |
| 前端任务页 | 仍“采集中”；2 有效、0 完整、0 精选、0 可查看 |
| 自动重试 | 未发生；task_dispatches 未变化 |
| 第二个真实任务 | 未创建；30 分钟内新 root_task 仅 1 个 |

---

## 5. F10 真实恢复

**NOT TESTED**。

- 本任务 `challenge_count=0`；
- `verification_events` / `browser_takeover_sessions` 没有本任务记录；
- 唯一历史记录属于旧任务 `11f9fc9c...`，不能计为本轮 F10 结果；
- 本轮未人为制造滑块或绕过平台验证。

---

## 6. 历史任务与数据

- 旧 stuck 任务 `11f9fc9c...`：仍 **COLLECTING v182**，updated_at/14:12:16Z；
  task_creators=2、snapshots=1、featured_collections=0，未被本轮修改/重试/取消。
- 新任务数据独立：task_creators=2、snapshots=0、featured_collections=0、featured_cards=0。
- `media_objects` 全局从 34 增至 68；新增 34 个封面属于本轮采集，但无快照引用。
- 未删除任何历史任务、达人、快照、媒体对象。

---

## 7. 新缺陷结论

### P1-A（确定，新）：final attempt `not_found` 未收口

- `should_finalize_cancelled()` 在 attempt 4 遇到 `not_found=True` 返回 False；
- 没调用 `_finalize_interrupted`，root_task 永久 COLLECTING；
- checkpoint 中第一位达人的完整模块/两组精选未发布，snapshots/featured=0；
- 这是 P1FIX-02 的**确定缺陷**，需要在后续单独授权修复，并补 `not_found` 最后 attempt 的回归测试。

### P1-B（确定，残留）：heartbeat 仍可能被同步 DB 阻塞

- 首次 heartbeat 失败 elapsed=11.4s；后续 attempts 2–4 无 heartbeat 记录，只出现 `not_found`；
- 仅把 `host.heartbeat_lease` 移到线程，未覆盖 `engine.guard()` 和主流程的同步 DB 调用；
- 需要将 heartbeat 关键路径与同步 DB 调用隔离，或证明具体阻塞点后再修；本轮未改代码。

### 非缺陷/未证实

- F10 未触发，不能判断 F10 恢复；
- 第二位达人标签与关键词差异未证实是筛选失败；需平台搜索语义核对，不能仅凭标签修改筛选；
- 未发现候选 ID 错位或跨达人数据串写。

---

## 8. 最终结论

**NO-GO。**

依据：

1. 真实任务只完成 **2/10**，Workflow FAILED，root_task 仍 COLLECTING；
2. **0 份已发布快照**，第一位达人的 8 模块/2 精选未发布，数据完整性不满足；
3. F10 本轮 **NOT TESTED**，不能报告通过；
4. P1FIX-02 attempt 门控部分有效，但 final attempt `not_found` 未收口，真实环境验收 **FAIL**；
5. heartbeat 仍有同步 DB 阻塞迹象，P2-01 未完全解决。

**E2E-01 不能解除阻塞。**  
本轮不创建第二个任务、不重试/取消/修复任务、不改生产代码；等待审核后再决定修复方案。

---

## 证据

- [任务与数据](e2e-real-collection-run2-2026-10-20/01-task.md)
- [Temporal history](e2e-real-collection-run2-2026-10-20/02-temporal-history.txt)
- [Worker 日志](e2e-real-collection-run2-2026-10-20/03-worker-log.txt)
- [PostgreSQL 数据](e2e-real-collection-run2-2026-10-20/04-db.txt)
- [Heartbeat/lease](e2e-real-collection-run2-2026-10-20/05-heartbeat.txt)
- [采集截图](e2e-real-collection-run2-2026-10-20/01-collecting.png)
- [任务卡住截图](e2e-real-collection-run2-2026-10-20/02-stuck-ui.png)
