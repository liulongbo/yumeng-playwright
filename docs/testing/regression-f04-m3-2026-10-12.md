# F04 / M3 真实业务回归方案与执行记录

状态：进行中
创建时间：2026-10-12T15:10:00+08:00
授权依据：用户 2026-10-12 明确授权（档位 A 立即执行；真实采集「宠物」、目标达人 **5**；本文档载体；Q2 并发测试补齐）
证据工具：Playwright MCP（`mcp__playwright__*`，真实 Chrome `--isolated`）+ 后端 API + PostgreSQL + Temporal + Worker 日志

> 本文档是本次回归的**方案与证据载体**。方案先行，执行结果按小节回写。
> 卡片状态以 `docs/tasks/` 为准；本文档不单独升级任何验收状态。

---

## 一、环境检查结论（2026-10-12 实测）

| 检查项 | 结论 | 证据 |
|---|---|---|
| Playwright MCP 可用性 | ✅ 可用 | `~/.local/bin/playwrightmcp` symlink 正常；Node v24.14.0；成功 `navigate` 本机 API 并返回快照 |
| Chrome 连接 | ✅ 真实系统 Chrome 154.0.8037.98 | MCP `--browser chrome`；`/Applications/Google Chrome.app` 存在 |
| **MCP 与 ExecutionUnit 是否共用 Profile** | ✅ **完全隔离，无冲突** | MCP `--isolated` → 临时 profile（`/tmp/dsh-playwright-mcp`）；单元 `profile_directory=.runtime/profiles/unit-local-mac-02`（持久 + 系统 Keychain） |
| 采集单元状态 | ✅ `READY`，`owner=NULL`、`mode=NULL`、`session_version=6` | `execution_units` 表 |
| 单元绑定账号 | `ID: 1807978499337419` | 与 `.runtime/units/local-dev-mac-02.json` 一致 |
| 租约约束 | ⚠️ **同一时刻仅一个进程可持有单元** | `Repository.acquire` 并发 1；故 F04 真实采集**必须经采集 Worker 串行**，不得同时用 MCP 驱动星图页面 |
| 前端 | ⚠️ 需启动 Vite :5173 | `frontend/node_modules` 与 `dist` 均存在 |
| API | ✅ `/api/auth/me → 401` | 预期 |

### 已知环境缺陷（本次复现）

`.venv` 中 `_editable_impl_xingtu_collector.pth` 与 `_virtualenv.pth` 再次被置 `UF_HIDDEN`（`flags=32832`），
导致直接调用 `.venv/bin/xingtu*` 报 `ModuleNotFoundError`。**Makefile 目标不受影响**（已导出 `PYTHONPATH`）；
直接调用时需 `PYTHONPATH=backend/src`。这是 APFS/同步导致的可复发问题，见 AC 表。

---

## 二、F04 验收方案

### 2.1 唯一未闭合验收项

`docs/tasks/F04.md:59`：**[ ] 实机核验：真实账号下的筛选枚举、内容关键词模式、分页与终点、访问节奏（U02/U04）**

### 2.2 ⚠️ 关键前置发现：当前契约**在设计上拒绝 Page 3**

`contracts/douyin_xingtu.verified.json`：

```
search.next_page_mode          = "page_fetch"
search.page_fetch_max_verified = 2
search.pagination              = "page"
search.initial_cursor          = "1"
search.single_page_only        = false
search.coverage_gaps[0]        = "...当前 page_fetch_max_verified=2，page=3 及以后和真实终点尚未核验，
                                  达到边界会以 SEARCH_CAPABILITY_LIMIT 停止而不报告平台耗尽"
```

门禁实现 `backend/src/xingtu/adapter.py:718-731`：

```python
if spec.next_page_mode == "page_fetch":
    if (not cp.cursor or not cp.cursor.isdigit() or int(cp.cursor) < 2
        or (not spec.page_fetch_continuous_verified
            and (not spec.page_fetch_max_verified
                 or int(cp.cursor) > spec.page_fetch_max_verified))):
        raise CollectorError("SEARCH_CAPABILITY_LIMIT", "PAGE_FETCH_LIMIT_NOT_VERIFIED")
```

**推论**：请求第 3 页时 `cursor=3 > 2` → 直接抛 `SEARCH_CAPABILITY_LIMIT`，引擎记
`checkpoint.search_stop_reason = "SEARCH_CAPABILITY_LIMIT"`（`engine.py:274-276`），**不会发起第 3 页请求**。

**因此**：
1. **"推进至 Page 3" 在当前契约下不可通过系统流程达成**，这属**设计上的 fail-closed 行为**，不是缺陷。
2. 要取得 Page 3 实证，必须先**核验** Page 3 契约（U02 的一部分）并提升
   `page_fetch_max_verified` 至 3；核验动作本身需在真实平台观察并如实登记。
3. 本次运行**能确证**的是 Page 1/2 的真实性与**边界拒绝的诚实性**（拒绝时报告
   `SEARCH_CAPABILITY_LIMIT` 而非谎报平台耗尽）。

> **F04 结论预告**：除非另行授权"核验并登记 Page 3 契约"，**F04 本次仍无法转为完成**，
> 但可获得"边界 fail-closed 正确"的正面证据。

### 2.3 步骤（含可执行性标注）

| # | 步骤 | 可达性 | 预期结果 | 验证点 | 失败判据 | 副作用 |
|---|---|---|---|---|---|---|
| F1 | MCP **只读**浏览星图搜索页，采集可见筛选项清单 | ✅ **档位 A 可执行** | 可见筛选项 ⊆/＝ 契约 `capabilities.fields`（现仅 `keyword:eq`）；未登记项不得被系统接受 | **UI** 截图 + 与 `capabilities.fields` 比对 | 出现契约未登记项却被系统接受 | 真实平台**只读浏览** |
| F2 | `xingtu start --plan .runtime/plans/pet-5.json`（关键词宠物、目标 5） | ⚠️ 档位 B（已授权） | `discovered=20`、`valid≥1`、如实收口 | **DB** `root_tasks.payload`（discovered/scanned/valid）、`creator_snapshots` 行数、`checkpoint.candidates` | `discovered=0`；或谎报 `search_exhausted=true` | **真实采集** |
| F3 | 推进至 Page 3 | ❌ **当前契约拒绝**（见 2.2） | 第 3 页**不发起请求**，任务以 `SEARCH_CAPABILITY_LIMIT` 停止 | **DB** `checkpoint.search_stop_reason='SEARCH_CAPABILITY_LIMIT'`；**日志** 无 page=3 请求 | 未达边界却停止；或谎报耗尽 | 仅 Page 1/2 请求 |
| F4 | 游标**去重** | ✅ 自动（DB 分析） | `candidates` 内 `platform_creator_id` 无重复 | **DB** `GROUP BY platform_creator_id HAVING count(*)>1` 为空 | 出现重复候选 | 无 |
| F5 | **终点条件**诚实性 | ✅ 自动 | 终止原因为「达目标」或「能力边界」，不得声称平台耗尽 | **DB** `search_exhausted` + `search_stop_reason` | 无进展却 `search_exhausted=true` | 无 |
| F6 | **访问节奏**（U04） | ✅ 自动（证据分析） | 实测动作间隔 ≥ 契约 `action_interval_seconds=2.0` | **证据** 请求时间戳间隔 | 间隔显著低于 2.0s | 无 |

### 2.4 不以浏览器搜索结果判定通过

F04 通过判据**仅**取系统产物：候选队列落库顺序、`visited_cursors`、`search_stop_reason`、
`discovered/valid` 计数、以及安全验证计数。手工在星图页面看到的 20 条结果**不作为**通过依据。

---

## 三、M3 验收方案

判据以**实际事件与数据库证据**为准，不要求每个瞬时状态在前端可见。

| # | 步骤 | 工具 | 预期 | 验证点 | 失败判据 | 副作用 |
|---|---|---|---|---|---|---|
| M0 | 启动 Vite:5173 + 三进程，双队列新鲜消费者 | make | `xingtu-intake` 与 `xingtu-unit-local-mac-02` 均 `alive=True` | Temporal `check_queues` | 任一队列无新鲜消费者 | 无 |
| M1 | MCP 打开前端，以 `media-a` 登录 | MCP | 登录成功进入任务列表 | UI 截图；API `POST /api/auth/login → 200`；DB `sessions` 行 | 401/403/Origin 失败 | 无 |
| M7 | 提交后立即取消，验证 `QUEUED → CANCELLED` 一步终态 | MCP + API | `version` 仅 +1，不出现 `CANCELLING` | DB `root_tasks.state/version` | 停在 `CANCELLING` | 无（不进入采集） |
| M2 | 前端提交关键词「宠物」、目标 1 | MCP | `202` + 任务详情 | API `202`；DB `root_tasks(RECEIVED)`+`requirements`+`intake_dispatches` | 提交报错；无 DB 行 | **DeepSeek 付费调用** |
| M3 | 观察 `RECEIVED→PARSING→QUEUED→COLLECTING→COMPLETED` | API/DB | 依次推进至终态 | DB `state`+`version`；API `GET /api/tasks/{id}` | 停留非终态超合理窗口 | **真实星图采集** |
| M4 | Temporal 派发与消费核验 | Temporal/日志 | `intake_dispatches.sent=true`；`model_runs` 有 provider/model/tokens/latency | DB `intake_dispatches.sent`、`model_runs`；Temporal；日志 `dispatched N` | `sent=false` 长期不变；派发失败累积 | 无额外 |
| M5 | 终态与完整度 | DB | `COMPLETED`；8 模块全 `COLLECTED`；`profile_complete_count=1`；`failure_reason=null` | DB 快照、`checkpoint` 模块状态、`featured_collections` | `PARTIAL_COMPLETED`/`PROFILE_SCOPE_INCOMPLETE` | 无额外 |
| M6 | 结果持久化与 UI 展示三方一致 | MCP+API+DB | 达人列表/详情/两组精选/封面可见且计数一致 | UI 截图；API `/creators`、`/contents`、`/covers/...`；DB 行 | 三方不一致；封面 404/403 | 无额外 |

### 复用合法会话，不绕过验证

采集单元 `READY` 但 `verified_account_id=NULL` → 首次采集会要求会话/账号验证。
按设计走 `xingtu login` 的**人工可见维护窗口**；**不注入 Cookie、不绕过安全验证**。
若会话过期或触发挑战，如实记录为 `WAITING_FOR_LOGIN` / `WAITING_FOR_VERIFICATION` 或 `PARTIAL_COMPLETED`。

---

## 四、安全约束

| 项 | 约束 |
|---|---|
| 数据修改 | 仅本地开发库 `xingtu_development`（`127.0.0.1:55432`）；**不触碰生产** |
| 外部平台 | F1/F2、M3–M6 真实访问巨量星图 → 已获授权，规模受控 |
| 付费调用 | M2 触发 DeepSeek `/responses` → 已获授权；目标数 1 |
| 风控 | 目标数：F04=**5**（用户授权，见 §5 冲突说明）、M3=1；**不重复提交**；出现验证不主动制造、不绕过 |
| 凭据 | 日志/截图/本文件中不出现 Cookie、Token、API Key |
| 回退 | 不删数据、不 `reset --hard`、不清库；任务可用 `retry` |

### §5 授权范围冲突（须知悉）

`docs/tasks/FIX-01.md` §五.3 规定真实采集「目标数量 **≤2**」，而本次用户授权 **目标 5**。
**处理**：以用户显式授权为准（F04 需 >2 方能使分页/终点验收有意义），并在此如实登记该偏离。

---

## 五、执行记录

### 5.1 档位 A（已执行 2026-10-12）

| 项 | 结果 | 证据 |
|---|---|---|
| **M0** 服务就绪 | ✅ **PASS** | API :8000（401 已核）；Vite :5173 → **HTTP 200**；intake worker 在线；`xingtu-intake alive=True fresh=1`、`xingtu-unit-local-mac-02 alive=True fresh=1` |
| **M1** 真实用户登录 | ✅ **PASS** | MCP 在真实 Chrome 打开 `http://127.0.0.1:5173/` → 未登录自动跳 `/login`（门禁生效）；以 **media-a** 登录 → 跳转 `/tasks`；**UI**：任务中心渲染 20 条真实任务、侧栏显示「媒介 A @media-a」；**DB**：`sessions` 新增一行 `a8e5f1b7-c161-4424-a493-478f7d87f420`（`media-a`，`2026-10-12 07:05:36`，未撤销）；活跃会话 23 |
| M1 交叉核对 | ✅ 一致 | UI 列表中的 `#7a5111cc`(母婴/已完成/2-2)、`#7620fb83`(宠物/已完成/1-1)、已取消任务等与 DB 中 `root_tasks` 状态一致 |
| **F1** 筛选枚举（只读） | ✅ **PASS** | 契约 `capabilities.fields = [{"field":"keyword","operators":["eq"],"keyword_mode":"content"}]`、`sorts=["score"]`、`combinations=[["keyword"]]`；前端创建页由能力驱动（未登记字段不开放）。**未发现**契约未登记却被系统接受的筛选项 |
| **Q2 并发测试** | ✅ 已补齐（3 passed） | `backend/tests/integration/test_login_concurrency.py`（真实 Redis + 真实 `AuthService.login`），见 §6 |

### 5.2 档位 B / C

**状态：已授权但本轮未执行**（见 §7 待办）。

### 5.3 环境缺陷复现记录（需长期处置）

本轮再次复现：`.venv/.../_editable_impl_xingtu_collector.pth` 与 `_virtualenv.pth` 的 `UF_HIDDEN`
**被重新置位**（`flags=32832`），导致 `.venv/bin/xingtu*` 直接调用报 `ModuleNotFoundError`。
**Makefile 目标不受影响**（已导出 `PYTHONPATH`）；以 `PYTHONPATH=backend/src` 直调亦可。
**处置建议**（待授权）：`chflags -R nohidden .venv`，或把 `.venv` 移出同步目录。
**根因**：宿主 APFS/同步对 `_` 前缀文件置 hidden + CPython ≥3.13.5 跳过 hidden `.pth`（uv#16977）。

---

## 六、Q2 并发登录：实测结论与推荐方案

### 6.1 实测（真实 `AuthService.login` + 真实 Redis，非模拟）

| 场景 | Argon2 实际执行 | 结果分布 |
|---|---|---|
| 24 并发 **全部错误**口令（加栅栏制造最坏交错） | **24 / 24** | `INVALID_FORM=24`、**`PLATFORM_RATE_LIMITED=0`** |
| 24 并发 **全部正确**口令 | **24 / 24** | 校验通过；**失败计数未被写入** |
| 串行 5 次失败后 | 第 6 次 | `PLATFORM_RATE_LIMITED`（既有契约**未回归**） |

**结论**：`check()` → Argon2 → `failure()` 的 read-then-act 窗口使**整个突发全部穿透到校验器**。
生产参数为 Argon2id `time_cost=3, memory_cost=64 MiB, parallelism=4` → **每请求 64 MiB**，
突发上限只受请求线程池（默认 40）约束，**不受 `max_failures` 约束**。

### 6.2 计划 B 的精确调用顺序（为何其不成立）

计划 B 仅在 `failure()` 内做原子 `INCR+判定`，调用顺序仍为 `check → Argon2 → failure`，
**判定点仍在 Argon2 之后**，故**无法**提前拦截并发（已由 6.1 证实）。

### 6.3 推荐：方案 D（双计数器，唯一语义自洽）

```python
# login() 精确顺序
self.limiter.admit(ip, normalized)   # ① 新增：原子「尝试闸门」，Argon2 之前
self.limiter.check(ip, normalized)   # ② 既有失败计数检查（契约不变）
row = self.store.find_user_for_login(normalized)
password_matches = self.passwords.verify(stored, password)   # ③ Argon2
if row is None or not active or not password_matches:
    self.limiter.failure(ip, normalized)   # ④ 仅失败才计失败数
    raise CollectorError("INVALID_FORM", GENERIC_LOGIN_ERROR)
self.limiter.success(ip, normalized)       # ⑤ 成功清失败计数
```

- **为什么必须两个计数器**：校验前无法知道本次是对是错，故任何「失败计数」都无法充当准入闸门；
  反过来，任何"每次请求都计数"的单一计数器都会把**正确登录也算作失败**。
- **`max_attempts` 建议高于 `max_failures`**（如 20 vs 5），使失败计数**先**触发，
  既保留既有凭证填充语义与单测，又给 CPU 暴露设上限。
- **闸门实现**：Lua 脚本单次往返 `INCR → EXPIRE(首次) → 超限则 DECR 并拒绝`，
  计数**有界**且保留滑动窗口；键与失败计数键隔离，**不影响**现有 4 个旧断言。
- **诚实局限**：阈值处仍可能有至多 `max_attempts` 次并发校验同时发生（先到先服务固有）；
  真正的上限防护还需 `uvicorn limit_concurrency` 或前置反代限速（运维层，另行决定）。

### 6.4 已交付的测试（本方案不实施改动，仅测试）

`backend/tests/integration/test_login_concurrency.py`（**3 passed**）：
1. `test_concurrent_wrong_passwords_all_reach_the_password_verifier` —— **固化当前暴露**
   （栅栏制造最坏交错，断言 24/24 到达校验器、0 次限流）。**方案 D 落地后应改为
   `verify_calls <= max_attempts`，而不是删除。**
2. `test_concurrent_correct_passwords_are_not_counted_as_failures` —— 正确口令**不得**消耗失败预算
   （这正是"校验前自增"的朴素实现会破坏的不变量）。
3. `test_serial_failures_still_block_at_the_documented_threshold` —— 既有串行契约不回归。
