# 遗留质量测试与工程优化待办（合并前登记）

状态：待办（不在本次合并范围内）
创建时间：2026-10-12T16:05:00+08:00
背景：`10.9` → `main` 合并收尾阶段，用户决定不再扩大测试与修复范围，将以下事项登记为后续待办。

> **登记原则**：未验证项一律**不标记 PASS**；Q2 **不得**标记为已修复。
> 每项均给出「已知风险」与「后续验收条件」，便于下一阶段直接接手。

---

## L1. F04 Page 3 与真实终点核验

**状态**：未验证（F04 保持**待验收**）

**已知事实**
- 契约 `search.page_fetch_max_verified = 2`，`next_page_mode = "page_fetch"`，`resume_supported = false`，`initial_cursor = "1"`。
- `backend/src/xingtu/adapter.py:718-731` 对 `cursor > 2` 抛 `SEARCH_CAPABILITY_LIMIT: PAGE_FETCH_LIMIT_NOT_VERIFIED`；
  `engine.py:274-276` 记 `checkpoint.search_stop_reason = "SEARCH_CAPABILITY_LIMIT"`，**不发起第 3 页请求**。
- 一轮只读尝试（MCP 隔离 profile）打开 `https://www.xingtu.cn/ad/creator/market` 被重定向到
  `https://www.xingtu.cn/?redirect_uri=%2Fad%2Fcreator%2Fmarket`（登录墙），**未获得平台证据**。
- 已核验通过的部分（可保留）：筛选枚举与契约一致（仅 `keyword:eq`）、关键词模式、游标去重、
  边界拒绝的**诚实性**（报能力上限而非谎报平台耗尽）、访问节奏 ≥ `action_interval_seconds=2.0`。

**已知风险**
- 分页终点未经实证，**"达到边界"不等于"平台耗尽"**；正式合约上限仍是第 2 页。
- 若不核验，任何"多页采集完整性"的业务承诺都缺乏依据。

**后续验收条件（全部满足方可关闭）**
1. 在**真实登录会话**（采集单元可见 Chrome，人工完成验证，**不注入 Cookie、不绕过验证**）下，
   观察 Page 3 的实际可访问性、响应结构与翻页行为，留脱敏证据。
2. 依据观察结果给出**契约变更建议**（例如 `page_fetch_max_verified` 由 2 调整为 3 或登记连续翻页证据）；
   **变更需单独授权**，本阶段已明确不允许修改。
3. 单独验证**真实终点**（不把 Page 3 可访问等同于终点），需有界或连续的终点证据。
4. 回写 `docs/tasks/F04.md` 对应验收项并更新进度总览。

---

## L2. M2–M6 真实端到端测试

**状态**：未执行（计划已就绪）

**已知事实**
- 档位 A 已完成并通过：**M0**（服务就绪、双队列新鲜消费者）、**M1**（`media-a` 真实登录成功，
  DB 新增 session `a8e5f1b7-c161-4424-a493-478f7d87f420` @ 2026-10-12 07:05:36）、**F1**（筛选枚举只读核验）。
- 计划文档：`docs/testing/m2-m6-minimal-e2e-plan-2026-10-12.md`（含费用上限、停止条件、人工配合点）。
- **M2/M3/M4/M5/M6 均未执行**：未从前端提交真实任务，未产生 DeepSeek 付费调用，未做真实星图采集。

**已知风险**
- RECEIVED 缺陷的机制修复已被自动化与历史真实链路验证，但**缺少本轮从 UI 现场提交的端到端证据**；
  因此不能宣称 M3 端到端验收通过。
- 首次采集可能要求人工在可见 Chrome 完成账号/会话验证（设计约束，不绕过）。

**后续验收条件**
1. 用户确认计划 §7 的 4 项（目标数量、费用上限、人工介入许可、`PARTIAL_COMPLETED` 是否保持不重试）。
2. 按计划执行 M2→M6，逐阶段留存 UI/API/DB/Temporal/日志证据。
3. 终态达到 `COMPLETED`、8 模块全 `COLLECTED`、`profile_complete_count=1`、`failure_reason=null`，
   且 UI/API/DB 三方计数一致 → 回写 `INTAKE-01`、`CONSOLE-01`、`F05`、`F06` 与进度总览。
4. 若收口 `PARTIAL_COMPLETED`，**如实记录**，不得标记 PASS。

---

## L3. Q2 并发登录安全加固

**状态**：**已发现，未修复**（候选方案 D 已设计，未实施）

**已知事实（实测，真实 `AuthService.login` + 真实 Redis）**
- `AuthService.login` 顺序为 `limiter.check()` → Argon2 → `limiter.failure()`，两次 Redis 往返之间存在
  昂贵的密码校验，形成 read-then-act 竞争窗口。
- 实测：**24 并发全部错误口令 → 24/24 到达 Argon2，0 次限流**；24 并发正确口令 → 失败计数未被写入；
  串行第 6 次仍 `PLATFORM_RATE_LIMITED`（既有串行契约未回归）。
- 生产 Argon2id 参数 `time_cost=3, memory_cost=64 MiB, parallelism=4` → **每请求 64 MiB**；
  并发上限实际由 anyio 线程池（默认 40）决定（≈2.5 GiB），**不受 `max_failures` 约束**。
- 固化测试：`backend/tests/integration/test_login_concurrency.py`（3 passed），
  其中第 1 个用例**刻意断言当前暴露**，方案落地后应改为 `verify_calls <= max_attempts` 而**不是删除**。

**已知风险**
- 高频密码猜测在并发突发下不受 `max_failures` 限制；突发可耗尽 API 的 CPU/内存，影响**所有**接口。

**后续验收条件（方案 D）**
1. `product_auth.py` 新增 `max_attempts`（建议 20 > `max_failures`=5）与原子 `admit()`（Lua 单次往返
   `INCR → 首次 EXPIRE → 超限 DECR 并拒绝`，计数有界、保留滑动窗口、键与失败计数隔离）。
2. `AuthService.login()` 在 `check()` **之前**调用 `admit()`；`MemoryLoginLimiter` 同步实现 `admit()`。
3. 验收：并发错误口令 `verify_calls <= max_attempts`；并发正确口令失败计数仍为 0；
   串行第 `max_failures+1` 次仍 `PLATFORM_RATE_LIMITED`；持续超限后计数**不增长**；
   Redis 不可用仍 `RESOURCE_UNAVAILABLE/LOGIN_LIMITER_UNAVAILABLE`。
4. **残余风险须同时登记**：阈值处仍可能有至多 `max_attempts` 次并发校验（先到先服务固有），
   彻底上限需运维层 `uvicorn limit_concurrency` 或前置反代限速。

---

## L4. UF_HIDDEN 虚拟环境问题

**状态**：**已定位，未修复**（用户本轮暂缓授权修复）

**已知事实**
- 仓库 `.venv` 内 **9746 个文件**带 macOS `UF_HIDDEN`（`flags=32832`）；`backend/src` 为 **0 个**。
- `.venv/lib/python3.13/site-packages/_editable_impl_xingtu_collector.pth`（79 字节，无结尾换行）
  与 `_virtualenv.pth` 因 `UF_HIDDEN` 被 CPython ≥3.13.5 的 `site.py:174-179` 跳过
  → `import xingtu` 失败 → `.venv/bin/xingtu*` 直调报 `ModuleNotFoundError`。
- `/tmp` 干净检出的同名 `.pth` `flags=0`，导入正常 → 证明**与宿主目录/文件标志相关，非代码缺陷**。
- 扩展属性仅 `com.apple.provenance`（macOS 15 来源标记），**无** FileProvider/iCloud 同步 xattr；
  `~/Library/Mobile Documents` 基本为空。分布呈**局限于 `.venv` 子树的批量特征**，
  符合"文件树曾被整体复制/还原并保留源端 flags"，**尚未证实是否存在活跃置位者**。
- 上游同源问题：`astral-sh/uv#16977`。
- **当前缓解已在位**：`Makefile` 导出 `PYTHONPATH := $(CURDIR)/backend/src`，`make check` 等目标
  不受影响（已验证 exit 0）。

**已知风险**
- 直接调用 `.venv/bin/xingtu` / `xingtu-api` / `xingtu-product` 会失败，除非显式设 `PYTHONPATH`。
- 问题**已复现两次**（合并前再次复现），会随宿主还原/同步行为复发。

**后续验收条件**
1. 先做**只读置位测试**：在 `.runtime/` 放入 `_` 前缀文件，观察 30 分钟内是否被自动置位，
   以判定"是否有活跃置位者"。
2. 若无活跃置位者 → 执行 `chflags -R nohidden .venv`（仅改元数据，可回滚），随后验证
   `import xingtu` 与控制台脚本正常。
3. 若有活跃置位者或再次复发 → 在**非同步/非被还原路径**重建 venv（`uv sync --frozen`，
   `uv.lock` 已验证可复现），并调整 Makefile 的 `.venv` 路径引用。
4. 验收：`.venv/bin/xingtu --help`、`make check`、`make test-unit` 在**不设** `PYTHONPATH` 时全部通过。

---

## 其它已在文档中登记的低优先级项（不阻塞）

| 项 | 位置 | 说明 |
|---|---|---|
| 挑战超时/失败无证据摘要 | `engine.py` `EVIDENCE_ERROR_CODES` | 5 个 `SECURITY_CHALLENGE_*` 码未入白名单，挑战最终失败仅有 `task.failure_reason` |
| `maintenance_reason` 只写不读 | `browser_host.py:104/261/287` | 死字段，`release_disposition` 才是实际载体 |
| 迁移 008 不可重跑 | `migrations/008_m3_product_app.sql` | `ADD COLUMN`/`ADD CONSTRAINT` 未用 `IF NOT EXISTS`（009 已用） |
| 会话表只增不减 | `product_repository.expire_sessions` | 无调用方，会话过期目前为懒判定 |
| 外键并发的极端分支 | `product_repository.create_product_task` | 存在性检查与 INSERT 同事务；并发删除仍由 FK 兜底，表现为 500（未转为 422） |
| `covers.py` 与 `product_covers.py` 双实现 | - | 本次仅统一修复 S3 body 泄漏，未做合并重构 |
