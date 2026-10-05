# AUTO-01 有界浏览器宿主真实运行验证（维护→采集交接）

日期：2026-09-28（Asia/Shanghai）；macOS，本项目 `.venv`，无 Git。
任务卡：[AUTO-01](../tasks/AUTO-01.md)；交接依据：[有界浏览器宿主实施交接](../handoffs/AUTO-01-bounded-browser-host-handoff-2026-09-28.md)。
命令与数据库记录：[运行日志](AUTO-01-bounded-host-real-run-2026-09-28.log)。
范围：**真实平台**（巨量星图，账号 `ID: 1865332309937515`，本机 IP + 项目独立 Chrome 154 + 持久 profile，`network_mode=local_development`），不是合成或离线验证。

## 1. 本轮验证目标

验证交接文档第五节修订后的流程是否成立：

```text
任务等待登录 → 浏览器宿主持有租约/profile/Chrome → 同上下文打开维护页
→ 用户正常登录 → 同上下文验证账号与受保护业务能力
→ Repository 原子 maintenance → collect → 增加 session_version
→ 同一上下文执行搜索与主页采集 → 关闭后回到 NEEDS_LOGIN
```

## 2. 实际执行

```bash
export XINGTU_DATABASE_URL=postgresql://xingtu_test@127.0.0.1:55439/xingtu_local_dev
export XINGTU_TEMPORAL_TEST_BINARY="$PWD/.runtime/temporal-test/temporal-v1.9.1"
make migrate ENVIRONMENT=development          # 应用迁移 005（此前本地库为 1—4）
xingtu start --plan .runtime/plans/local-smoke-beauty.json \
             --config .runtime/units/local-dev-mac-02.json --key <uuid> --actor local-verify
make smoke-local UNIT_CONFIG=.runtime/units/local-dev-mac-02.json \
     ROOT_TASK_ID=aa179d9b-68cf-4035-870e-a1b96332e098 TIMEOUT_SECONDS=1200
```

- 关键词 `美妆`，`target_count=2`，契约 `xingtu-ad-creator-square-v1`（live、VERIFIED）。
- 单元初始状态 `NEEDS_LOGIN`（`session_version=5`、`SESSION_NOT_PERSISTED_AFTER_RESTART`）。
- Temporal 使用官方 SDK 本地测试服务器（Server 1.32.0，in-memory），本机无 Docker 守护进程。
- **人工登录由用户本人在宿主打开的 Chrome 窗口内完成**；工具未接触、索取或记录密码、验证码、Cookie 或请求头值。
- 退出码 **0**。

## 3. 交接结果（本轮核心结论）

| 检查项 | 实际值 | 结论 |
|---|---|---|
| 宿主取得租约 | `state=LEASED`、`mode=maintenance`、`generation=13`、`maintenance_deadline` 已设 | 通过 |
| 同上下文人工登录后账号核验 | `verified_account_id=ID: 1865332309937515`（与配置期望账号一致） | 通过 |
| 受保护业务能力核验 | 同上下文进入 `/ad/creator/market`，`check_session` 通过后才允许提升 | 通过 |
| 原子 `maintenance → collect` | `mode=collect`、`session_version 5 → 6`、`failure_reason=NULL`、`maintenance_deadline=NULL` | 通过 |
| 审计 | `browser-host:887c0810-9bdd-469a-83d6-96e232efe438 \| promote_maintenance_to_collect:unit-local-mac-02` @15:23:44 | 通过 |
| 采集使用同一上下文 | 采集响应 `observed_at=2026-09-28T07:26:5xZ`、`session_version=6` | 通过 |
| 关闭后状态 | 单元回到 `NEEDS_LOGIN`、`browser_stopped=true`、`owner=NULL`；profile `SingletonLock` 已消失（Chrome 确认关闭） | 通过，未虚报可复用 |

这证明：**关闭 Chrome 后重新打开持久 profile 不是可用恢复路径，而同一宿主内的上下文交接是可用的**——与交接文档第三节继承的真实证据一致，不需要恢复已被否定的旧方案。

### 3.1 一处必须保留的证据张力（不得据此改写既有结论）

本轮单元进入维护态时状态为 `NEEDS_LOGIN / SESSION_NOT_PERSISTED_AFTER_RESTART`（2026-09-28 14:38 由 `AUTO-01` 审计写入）。宿主打开 Chrome 后，`wait_for_manual_clearance` 在本轮可观测时间内即取到受保护业务页与可读账号并完成提升。

从现有证据**无法区分**以下两种情形：

1. 用户在窗口内完成了正常登录；
2. profile 中的既有会话本次被平台接受（即该会话在本次重启后仍然有效）。

两者都满足本批验收条件（必须**在同一上下文**核验账号与受保护业务能力后才允许提升，仅凭 URL 或 Cookie 不能调用 `promote_maintenance_to_collect`）。但如果是情形 2，则与 14:38 记录的 `SESSION_NOT_PERSISTED_AFTER_RESTART` 存在张力，说明"跨重启复用失败"可能是**时序或环境相关**，而非绝对不可恢复。

**处理方式**：不撤销、不改写 14:38 的失效审计与既有卡片结论；这属于新增观察，列入下一批待复核项（见第八节待办）。下一批应在**一次显式重启**后重复本流程并记录时间戳，以区分情形 1 与情形 2。

## 4. 真实采集结果

任务 `aa179d9b-68cf-4035-870e-a1b96332e098`：

| 指标 | 值 |
|---|---|
| 工作流 / 任务终态 | `PARTIAL_COMPLETED` |
| 收尾原因 | `PROFILE_SCOPE_INCOMPLETE` |
| 发现候选 / 本段扫描 | 20 / 20 |
| 有效达人 | **2** |
| 完整主页数 | **0** |
| 搜索是否谎报耗尽 | 否（`search_exhausted=false`，达到目标即停止） |
| 检查点 | `revision=52`、`discovered=20`、`scanned=20` |
| 精选作品 | `featured_status=NOT_ATTEMPTED`（注册表 `featured=[]`） |

已发布快照（`task_creators ⋈ creator_snapshots`，`session_version=6`、`source_contract=xingtu-ad-creator-square-v1`）：

| 位置 | `platform_creator_id` | 昵称 | 粉丝 | 地区 | MCN | 内容标签 |
|---|---|---|---|---|---|---|
| 0 | `7646720304210771978` | 姜乘澜 | 19,383,152 | `NO_DATA`（真实空值） | 弄新妆 | 3 项 |
| 1 | `6935067985597956133` | 阿里北杯 | 4,091,398 | 上海市长宁区 | `NO_DATA`（真实空值） | 10 项 |

字段级来源完整：每个字段均有 `status`、`raw_value`、`observed_at`、`operation_id`、`path_ref`、`source_kind=response`、`session_version`、`source_contract` 与 `evidence_refs`；空值记 `NO_DATA` 而非 0 或空文本，未补造任何字段。

**跨运行一致性**：2026-09-27 真实采集的首位候选同为 `7646720304210771978`／姜乘澜，且 `city`/`province` 同样为 `NO_DATA`。两次独立运行结果一致，支持搜索顺序与字段解析的可重现性。

## 5. 完整度语义（本轮的行为验证）

本轮 `valid_count=2` 但 `profile_complete_count=0`，收尾原因由历史证据中的 `FEATURED_NOT_ATTEMPTED` 变为 **`PROFILE_SCOPE_INCOMPLETE`**。这是预期行为，不是缺陷：

- `contracts/profile_requirements.json` 声明的完整主页范围包含 `commercial`/`spread`/`fans`/`creation_and_fulfillment`，这些模块在注册表中**尚未登记**且 `inventory_verified=false`；
- 完整度**不再由已注册模块反推**，因此只采到 `basic` 时不会被算成"完整主页"；
- 即 AUTO-01 要求的"不把 basic 当成完整主页"在真实运行中生效。

## 6. 本轮未覆盖（不得视为通过）

- **本节当时 Temporal 幂等唤醒与原任务续跑未验证**：本轮由 `make smoke-local` 直接启动工作流。后续已由第 10 节的真实 dispatch 实验补齐；本句保留为时序记录，不再是当前缺口。
- **第 3.1 节的会话来源歧义未消除**：需一次显式重启后的重复实验来区分"人工新登录"与"既有会话被接受"。
- 第 3 页及以后与真实分页终点；契约硬边界仍为 `page_fetch_max_verified=2`。
- 除 `basic` 外的全部主页模块（含画像、创作能力、两组精选作品与封面来源）。
- 筛选枚举与访问节奏、挑战清除后的完整续跑。
- 5 位完整主页、20 位连续任务、单日 200 位与连续 7 天容量观察。
- 生产线路与远程维护（U06/U07/U08）、S3/MinIO 封面写入与认证访问（U09）。

## 7. 脱敏与清理

- 未记录密码、验证码、Cookie、令牌、请求头值或 CDP 控制地址；证据只保留字段级业务结果与状态。
- Chrome 已确认关闭，profile 锁已释放，单元回到 `NEEDS_LOGIN`，未遗留可复用会话的错误状态。
- 原始 JSON 结果只含业务字段与来源指针，写入 `.runtime/evidence-local/` 与业务库快照。

## 8. 对卡片验收项的影响

- AUTO-01「后台维护与采集互斥，续跑幂等；容量与 7 天观察」→ **部分满足**：互斥、同 Page 交接与幂等续跑已真实通过；容量与 7 天观察未验证，**不勾选整项**。
- AUTO-01「核对真实账号权益、完整字段清单和分页，完成 5 位及 20 位实测」→ **仍未满足**。
- 本轮不改变 UNIT-01/F04/F05/F06 的既有验收状态。

## 9. 交付前自动回归与安全收紧

2026-09-28T17:52+08:00 在不再访问真实平台的前提下完成最终本地／合成回归：

- `.venv/bin/ruff check backend conftest.py tests scripts`：通过。
- `.venv/bin/ruff format --check backend conftest.py tests scripts`：34 个文件格式合规。
- `.venv/bin/mypy backend/src`：16 个源文件通过。
- `PYTHONPATH="$PWD" PLAYWRIGHT_BROWSERS_PATH="$PWD/.runtime/browsers" XINGTU_TEST_DATABASE_URL=postgresql://xingtu_test@127.0.0.1:55439/xingtu_test_f04f05 XINGTU_TEMPORAL_TEST_BINARY="$PWD/.runtime/temporal-test/temporal-v1.9.1" .venv/bin/pytest backend/tests tests/e2e -q --tb=short --import-mode=importlib`：**166 passed in 149.31s，退出码 0**（102 单测 / 17 契约 / 44 集成 / 3 E2E）。
- Temporal 定向用例对同一 workflow 连续发送两次 `wake`，断言 Activity 总调用次数仍为 2、`root_tasks` 仍只有 1 条、有效达人仍为 2，并通过 Workflow history replay。这是合成编排证据，不替代第 6 节尚缺的真实等待任务 dispatch 续跑。
- 仓储／宿主集成用例覆盖：错误 owner、旧 generation、过期租约、session_version 冲突、重复 promote、两个并发 promote、事务失败无部分更新、审计、活跃 collect 拒绝并发维护、同一 BrowserContext 提升、关闭确认回 `NEEDS_LOGIN`、关闭未确认进 `QUARANTINED`、重复维护确认复用原 owner/generation/session。
- 删除旧 `Repository.verify_maintenance`：它可以在缺少同上下文账号／业务页／线路证据时单独递增 `session_version`，与本批原子交接契约冲突。当前仅 `promote_maintenance_to_collect` 能递增已验证会话版本。

保留的失败与修复历史：

1. 首次仓储定向测试在 macOS 沙箱内无法访问本机 PostgreSQL，16 个 setup error 均为 `Operation not permitted`；在获授权的本机测试环境重跑后进入业务断言。
2. 首次仓储断言为 15 passed / 1 failed；失败是 PostgreSQL UUID 对象与字符串比较的测试类型问题，统一为字符串比较后 16 passed，未改变生产逻辑或放宽断言。
3. 挑战等待契约首次在沙箱内因 Chromium MachPort 权限失败；沙箱外使用同一项目缓存 Chromium 复测 1 passed。
4. 单独收集 E2E 文件的定向命令两次因未包含项目根目录导入路径而报 `ModuleNotFoundError: backend`；显式使用 `PYTHONPATH="$PWD"` 后定向 Temporal 用例通过，完整回归也使用同一可重现命令。
5. 安全收紧前首轮全套为 165 passed in 149.32s；删除旧入口并新增重复 maintenance 确认用例后，最终为 166 passed in 149.31s。

最终只读数据库收尾：`schema_migrations=1,2,3,4,5`；`unit-local-mac-02` 为 `NEEDS_LOGIN`、`browser_stopped=true`、`session_version=6`、`owner=NULL`、`mode=NULL`。本轮没有遗留 Chrome 宿主或可被误认为已验证的 `READY` 状态。

## 10. 真实 dispatch 续跑与重复 Chrome 缺陷（2026-09-28 18:06—18:43+08:00）

使用独立 schema `auto01_dispatch_20260928` 和持久化本地 Temporal 实例跑真实 `xingtu start → worker/dispatch → WAITING_FOR_LOGIN → xingtu login`。原 root 为 `8120b16c-9289-4822-913a-542be3db6bc3`；重复两次 `login` 请求均复用同 owner/generation/session，未创建第二宿主。用户登录后，原 Activity 在同上下文完成 `maintenance → collect`、`session_version 0→1`，并使同一 root 的 `valid_count 0→1`；证明原任务/原检查点续跑成功。

随后真实页面触发 `PLATFORM_SECURITY_CHALLENGE`，用户观察到又出现一个未登录 Chrome。数据库与进程取证表明：同时没有两个宿主抢占单元，owner 不变；但存在两条叠加的实现缺陷：

1. 校验 Page 没有交给采集 Adapter，后者会新建 Page，造成可见的额外页面；
2. promote 为已在运行的 Activity 重新登记 dispatch wake，且 Workflow 对 `WAITING_FOR_LOGIN` 有 30 秒定时轮询。挑战维护超时后，预先残留的 wake/轮询可在没有新的用户请求时启动另一个 Chrome 运行周期。

修复不改写成功证据，也不恢复被证否的跨进程会话方案：`BrowserHost` 一次性交出原校验 Page；Adapter 在挑战回切时 detach 该 Page；同 Activity promote 不再写 `sent=false`；Workflow 在 `WAITING_FOR_LOGIN` 上只等显式 signal。中断 Worker 时 Playwright 关闭返回未确认，单元按安全边界进入 `QUARANTINED/browser_stopped=false`；只读确认项目 Chrome 进程消失后，运行内置 `recover-unit` 再回 `NEEDS_LOGIN`，该恢复有审计记录。

用户在修复版宿主中正常完成登录/挑战处理后，原 root 继续从 `valid_count=1` 到 `2`，检查点 `revision=88`，两个结果位置为 0/1，字段分别带 `session_version=1/2`，证明未重新计数且确实跨挑战续跑。业务终态 `PARTIAL_COMPLETED/PROFILE_SCOPE_INCOMPLETE`；宿主关闭后单元为 `NEEDS_LOGIN|browser_stopped=true|session_version=2|owner=NULL|mode=NULL`，dispatch 为 `sent=true`。审计顺序为 start → promote → challenge 回切 → promote。

首次将 `WAITING_FOR_LOGIN` 改为无 Timer 时，已有 Temporal history 因包含旧 `TimerStarted` 暴露 `TMPRL1100` nondeterminism。未删除/重建工作流；改用 `workflow.patched("waiting-for-login-explicit-wake-v1")` 兼容重放旧 Timer，新历史才使用显式 wake。原 workflow ID `collect/8120b16c-9289-4822-913a-542be3db6bc3` 最终为 `WORKFLOW_EXECUTION_STATUS_COMPLETED`，结果 `PARTIAL_COMPLETED`，history length 48。

最终验证：定向 4 passed；Temporal patch 定向 2 passed 并 history replay 通过；`ruff check`、`ruff format --check`、`mypy backend/src` 通过；补丁加载后全套 **167 passed**。首次未设 `PYTHONPATH` 的 Temporal 定向收集报 `ModuleNotFoundError: backend`，按项目已记录命令补 `PYTHONPATH="$PWD"` 后通过；该失败不是业务断言失败。收尾时 Worker、Temporal 测试服务器和项目 Chrome 均已关闭。
