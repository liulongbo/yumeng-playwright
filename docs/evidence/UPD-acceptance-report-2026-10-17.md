# 达人数据周期性更新功能验收测试报告

> **2026-10-18 更新**：DEF-01/DEF-02 已修复并复验；真实单达人定时批次已完成。最新结论见 [UPD 缺陷修复与真实定时验收报告](UPD-DEF-fix-and-scheduled-acceptance-2026-10-17.md)。本报告保留为修复前基线。

- 测试日期：2026-10-17—2026-10-18（Asia/Shanghai）
- 测试对象：达人手动更新、周期性更新、统一任务中心、统一执行单元池、优先级/冲突、数据与历史、正常采集回归
- 测试性质：只读 + 受控真实业务闭环；未修改业务代码、Schema、凭据或执行单元，未 commit/push/merge/deploy
- 测试计划：[UPD-acceptance-test-plan-2026-10-17.md](UPD-acceptance-test-plan-2026-10-17.md)
- 结论：**条件不通过（Conditional No-Go）**。手动更新与正常采集主链路真实跑通；周期调度逻辑与批次创建通过隔离验证，但当前环境未运行调度器，真实定时批次未执行，并发现 1 个 P2 调度状态收敛缺口、1 个 P3 展示缺陷。

## 1. 测试环境与基线

| 项 | 值 |
|---|---|
| Git | 分支 `llb_1016`，HEAD `a347b062fd10eae2e59a82e6f930cda557e95f48`，工作区存在本轮开发前已有未提交变更 |
| 前端 | Vite `http://127.0.0.1:5173`，HTTP 200 |
| API | FastAPI `http://127.0.0.1:8000`，`/api/auth/me` 401（期望） |
| PostgreSQL | `127.0.0.1:55432/xingtu_development`，`schema_migrations=18` |
| Redis | `127.0.0.1:56379` 可用 |
| Temporal | `127.0.0.1:57233` 可用 |
| Intake Worker | 在线（重启后使用当前代码），`xingtu-intake` 新鲜消费者=1 |
| Collection Worker | 在线（重启后使用当前代码），`xingtu-unit-local-mac-02` 新鲜消费者=1 |
| update-scheduler | **未运行**（当前环境；未在 dev 库启动，避免产生真实批量更新） |
| ExecutionUnit | 唯一 `unit-local-mac-02`，`READY`，`allowed_task_kinds=[collection,manual_update,scheduled_update]` |
| 测试前达人/快照/根任务 | 达人 59、快照 123、根任务 49、`creator_update_schedule` 0 行 |
| 测试后达人/快照/根任务 | 达人 60、快照 126、根任务 52、调度行 1（就叫Roxy） |
| Chrome | Google Chrome `155.0.8059.84` |
| Playwright MCP | 项目配置的 `@playwright/mcp` `1.62.0-alpha-2026-06-29`，23 个工具；harness 未直接暴露 `mcp__playwright__*`，通过项目已有 `scripts/acceptance/mcp_client.py` 以 MCP stdio 调用同一 server |
| 产品账号/会话 | `media-a`；会话诊断 `VALID`（期望账号=观测账号、受保护页已验证） |

**环境处理**：开始时 API/Worker 为 11:59 启动的旧进程，不包含本轮代码。已通过 `./dev.sh stop` 后手工启动 API、Intake Worker、Collection Worker、前端（**未启动 update-scheduler**），并用 `GET /api/creator-library/{id}/update` 返回 401 验证新路由已注册。同步中断时间与日志已记录。

## 2. 测试层级与方法

| 层级 | 方法 | 说明 |
|---|---|---|
| L1 单元 | `pytest backend/tests/unit` | 周期边界、TaskRecord、优先级/退避、状态机 |
| L2 集成 | `pytest backend/tests/integration`（隔离库 `xingtu_test_upd`） | 迁移、API/仓储、调度器、认领、快照、幂等 |
| L3 契约 | `pytest backend/tests/contract`（项目 Chromium） | 既有浏览器契约回归 |
| L4 前端 | TypeScript、Vitest、Vite build | 任务中心/达人页/更新任务详情 |
| L5 真实 UI | Playwright MCP + Chrome | 达人主页手动更新、任务中心、正常采集 |
| L6 进程级 | 隔离库启动 `update-scheduler` | 调度器建批、重启不重复；无真实采集 |
| L7 真实业务 | dev 库 + 真实 Chrome/账号 | 1 次正常采集、2 次手动更新（首次部分、重试完整） |

## 3. 测试用例执行结果

> 结果标记：PASS=实际验证通过；FAIL=实际失败/不符合预期；BLOCKED=缺少安全条件或未执行。L5 为真实 UI；L2/L6 为隔离/进程级；不得把 Mock 结果当作真实平台 E2E。

| ID | 测试场景 | 结果 | 测试方式 | 证据 |
|---|---|---|---|---|
| B-01 | Git 分支/HEAD/工作区 | PASS | 命令 | 本报告 §1 |
| B-02 | API/前端/DB/Redis/Temporal | PASS | 端口/健康检查 | `dev.sh status` |
| B-03 | Intake/Collection Worker | PASS | `dev.sh status` | 在线，消费者新鲜 |
| B-04 | update-scheduler | **BLOCKED** | `dev.sh status` | 未运行；见 ENV-01 |
| B-05 | 单元数量/任务类型权限 | PASS | DB | 1 个单元，三类全允许 |
| B-06 | 达人/快照/任务基线 | PASS | DB | 59/123/49；调度 0 |
| B-07 | Chrome/MCP/会话 | PASS | MCP probe + session diagnostics | MCP 1.62.0、23 工具；会话 VALID |
| T01-01 | 登录/进入达人库/达人主页 | PASS | Chrome E2E | 截图 `01-creator-before.png` |
| T01-02 | 手动更新按钮展示 | PASS | Chrome E2E | 按钮“手动更新”可见、可点击 |
| T01-03 | 点击创建更新任务 | PASS | Chrome+DB | root `9a7d5d43…`；任务中心可见 |
| T01-04 | 重复点击/在途幂等 | PASS | Chrome+集成 | 在途按钮 disabled“更新进行中”；L2 幂等测试通过 |
| T01-05 | 任务进入现有任务中心 | PASS | Chrome+API | `task_kind=manual_update` |
| T01-06 | 排队/执行/终态展示 | PASS | Chrome+DB | `COLLECTING→COMPLETED`；截图 |
| T01-07 | 更新后新快照 | PASS | DB | 快照 2→3；新 `7945ec86…` |
| T01-08 | 不重复创建达人 | PASS | DB | `platform_creators=1` |
| T01-09 | 历史快照不被覆盖 | PASS | DB | 旧快照 payload hash 全部不变 |
| T01-10 | 页面/API/DB 一致 | PASS | Chrome+API+DB | 最近成功时间/状态一致 |
| T01-11 | 取消更新任务 | PASS | Chrome+DB | 合成任务点击取消 → `CANCELLED`，`TASK_CANCELLED` |
| T01-12 | 无可用执行单元 | PASS | 隔离库 | 仅 `collection` 能力时认领返回 None，任务仍 `QUEUED` |
| T01-13 | 任务失败/部分更新 | PASS（部分） | 真实 E2E | 首次 `560a3fb6…` `PARTIAL_COMPLETED`；`fans` 失败 |
| T01-14 | 页面刷新/重新进入 | PASS | Chrome E2E | 重新进入达人页仍显示最近成功/写入 |
| T02-01 | 五档周期边界 | PASS | L1 | 9999/10000/99999/100000/499999/500000/999999/1000000 全部正确 |
| T02-02 | 首次登记基线 | PASS | L2 | 最近完整快照/写入时间为基线 |
| T02-03 | 到期生成批次 | PASS | L6 隔离库 | 调度器创建 1 个 `scheduled_update`，`QUEUED`、`unit_id=NULL` |
| T02-04 | 未到期不提前 | PASS | L2 隔离库 | 未来到期 tick `created=0` |
| T02-05 | 跨档重算 | PASS | L1/L2 | 档位/周期函数；手动成功 947256→`50w_100w`/3 天 |
| T02-06 | 手动有效成功重置周期 | PASS | 真实 E2E | 第二次手动 `COMPLETED`；`last_success_at=16:27:02`，`next_due=+3 天`，失败计数 0 |
| T02-07 | 部分更新不重置/退避 | PASS | 真实 E2E | 第一次部分更新后读取状态：`PARTIAL_UPDATE`，失败=1，`next_due=+1h`，`last_success` 未推进 |
| T02-08 | 同达人/同批次去重 | PASS | L2/L6 | 在途复用；调度器重启后仍只有 1 个批次 |
| T02-09 | 调度器重复 tick | PASS | L6 隔离库 | 第二次启动无新批次；重启日志为空但 DB 仍只有 1 个 root |
| T02-10 | 无 scheduled 能力 | PASS | L2 隔离库 | `created=0, skipped=1` |
| T02-11 | 当前环境自动周期更新 | **BLOCKED** | 环境 | dev 库 update-scheduler 未运行（ENV-01） |
| T02-12 | 真实定时批次执行终态 | **BLOCKED** | 真实 E2E | 未启动 dev 调度器，未做真实批量更新 |
| T03-01 | 三类任务进入任务中心 | PASS | Chrome+DB | 采集、手动真实；定时用合成任务 UI 验证 |
| T03-02 | 任务类型筛选 | PASS | Chrome+API | manual/collection/scheduled `task_kind` 过滤 |
| T03-03 | 更新任务目标/状态 | PASS | Chrome+API | 更新目标、每位状态/失败原因可见 |
| T03-04 | 取消操作 | PASS | Chrome+DB | 合成更新任务 `CANCELLED` |
| T03-05 | 重试操作 | **BLOCKED** | 未执行 | 未对真实/合成任务执行 retry |
| T03-06 | 刷新后状态不丢失 | PASS | Chrome+API | 任务详情/列表重新加载一致 |
| T03-07 | 无独立更新系统 | PASS | DB/路由审查 | 仅 `root_tasks/task_*` + `creator_update_schedule` |
| T04-01 | 当前单元支持三类 | PASS | DB+真实 | `allowed_task_kinds` 三类；手动/采集均被该单元认领 |
| T04-02 | 手动任务被单元认领 | PASS | DB | `unit_id=unit-local-mac-02` |
| T04-03 | 仅采集配置 | PASS | L6 隔离库 | 只认领 collection |
| T04-04 | 仅手动配置 | PASS | L6 隔离库 | 只认领 manual_update |
| T04-05 | 仅定时配置 | PASS | L6 隔离库 | 只认领 scheduled_update |
| T04-06 | 采集+手动配置 | PASS | L6 隔离库 | 不认领 scheduled_update |
| T04-07 | 无匹配单元等待 | PASS | L2 隔离库 | 任务保持 `QUEUED`，不丢失 |
| T04-08 | 忙碌等待/浏览器互斥 | PASS（间接） | DB/日志/代码 | 两次真实任务顺序执行；`max_concurrent_activities=1`+租约；未强制重叠 |
| T04-09 | 配置变更回池/运行中不打断 | PASS | L2 隔离库 | 未启动任务回池；已启动任务保持 `unit_id` |
| T04-10 | 多 Worker 竞争 | PASS | L6 隔离库 | 两线程 `SKIP LOCKED` 认领到不同 root，无重复 |
| T05-01 | 三类同排优先级 | PASS | L6 隔离库 | 认领顺序 collection→manual→scheduled |
| T05-02 | 正常采集存在时跳过建批 | PASS | L2 隔离库 | 调度器 `created=0, skipped=1` |
| T05-03 | 手动优先于定时 | PASS | L6 隔离库 | 认领顺序 manual 先于 scheduled |
| T05-04 | 正常任务在更新拿浏览器前优先 | PASS | L2 隔离库 | 正常任务可运行时 `Engine.run_update` 返回 `QUEUED`，零访问 |
| T05-05 | 达人边界让路 | PASS（合成） | L2 隔离库 | 同上；未做真实“边采集边到达”时序 |
| T05-06 | 已运行正常采集不被中断 | PASS（间接） | 真实/代码 | 正常任务完整 `COMPLETED`；未强制并发 |
| T05-07 | 定时批次不重复 | PASS | L6 隔离库 | 单活跃批次；重启后仍 1 个 |
| T05-08 | Temporal 严格优先级 | **BLOCKED** | 限制 | Temporal 无严格业务优先级；仅验证 DB 认领/Activity 让路 |
| T06-01 | 更新不搜索/P1 | PASS | DB | 手动任务 `filter_plans=0/requirements=0/model_runs=0` |
| T06-02 | 平台身份不变 | PASS | DB | `platform_creators=1`，无重复 |
| T06-03 | 新快照 | PASS | DB | 2→3；`7945ec86…` |
| T06-04 | 旧快照不变 | PASS | DB | 旧 snapshot payload hash 全部不变 |
| T06-05 | 当前投影更新 | PASS | DB | `data_updated_at` 推进；`profile/pipeline=true`（第二次） |
| T06-06 | 达人库/页面/API 一致 | PASS | Chrome+API+DB | 页面显示最近成功/下次到期；API 一致 |
| T06-07 | 失败不清旧值 | PASS（L2） | L2 集成 | 旧字段/旧快照保留；首次部分更新未清空 |
| T06-08 | 部分更新不重置 | PASS | 真实 E2E | `PARTIAL_UPDATE`，失败 1，`next_due=+1h` |
| T06-09 | 有效成功才重置 | PASS | 真实 E2E | 第二次 `COMPLETED`，失败清零，周期 +3 天 |
| T07-01 | 登录/表单/能力 | PASS | Chrome E2E | 新任务页显示 9 项已核验能力；截图 |
| T07-02 | 提交正常采集 | PASS | Chrome+API | 关键词“露营”、目标 1；root `3130eb97…` |
| T07-03 | P1 转换/排队 | PASS | DB | `PARSING→QUEUED`；`model_runs=1`、`filter_plans=1` |
| T07-04 | Worker 执行 | PASS | DB/日志 | `QUEUED→COLLECTING→COMPLETED` |
| T07-05 | 数据入库/达人库 | PASS | DB/UI | 有效 1、快照 1、`task_creators=1` |
| T07-06 | 新增功能无回归 | PASS | DB | 采集任务仍为 `task_kind=collection`；主链路正常 |
| T07-07 | 既有测试 | PASS | L1/L2/L3/L4 | 303/92+1skip/33/83 |
| T07-08 | 控制台/网络 | PASS | Chrome | 任务/达人页 Errors: 0；网络无失败 API |
| T08-01 | 手动重复提交 | PASS | Chrome+L2 | 在途禁用；同键返回同任务 |
| T08-02 | 调度器停止/重启 | PASS | L6 隔离库 | 重启后不重复建批 |
| T08-03 | Worker 崩溃恢复 | **BLOCKED** | 未执行 | 未做真实进程 kill/恢复；仅既有租约/检查点测试 |
| T08-04 | DB/Temporal 暂不可用 | **BLOCKED** | 未执行 | 未在受控环境停依赖 |
| T08-05 | 任务取消/资源释放 | PASS | Chrome+DB | 合成更新任务取消终态 `CANCELLED` |
| T08-06 | 会话失效/安全验证 | **BLOCKED** | 未触发 | 会话 VALID；未制造/绕过验证 |
| T08-07 | Schema 漂移 | PASS | DB | 迁移 018；未新增 Schema |
| T08-08 | 未授权变更 | PASS | Git | 测试期间未修改业务代码；仅新增测试证据/运行时脚本 |

## 4. 缺陷与观察

### DEF-01（P2）手动更新任务终态后，调度状态不自动收敛

- **复现步骤**：
  1. 达人库 → 达人主页 → 手动更新，创建任务 `560a3fb6-0cae-463c-b818-3ddf49fe4711`。
  2. 等待任务到 `PARTIAL_COMPLETED`（2026-10-17T16:20:14Z）。
  3. 在未调用 `GET /api/creator-library/{id}/update`、且 update-scheduler 未运行时，直接查询 `creator_update_schedule`。
- **预期**：任务终态后应在途标记释放，并按有效/部分更新更新 `next_due_at`/失败计数。
- **实际**：`in_flight_root_task_id` 仍为 `560a3fb6…`，`next_due_at` 仍为旧的 2026-10-19，失败计数仍为 0。随后调用 `GET /api/creator-library/{id}/update`，同一行才变为：`in_flight=null`、`last_failure_reason=PARTIAL_UPDATE`、`consecutive_failures=1`、`next_due=+1h`。
- **证据**：E2E 首次运行 `T02-06` FAIL（[manual-first-attempt.log](assets/upd/manual-first-attempt.log)）；DB 行前后对比；`creator_update.py` 的 reconcile 仅在 `status()`/`scheduler_tick()` 中调用，任务 `finish()` 不写调度表。
- **根因与置信度**：高置信度。手动更新终态收敛依赖读接口或调度器 tick；当前 dev 环境调度器未运行，因此可稳定观察。
- **影响**：无数据丢失；但手动更新后的下次周期/退避不会立即持久化，用户不打开达人页时调度状态陈旧；若调度器正常运行，通常一个 tick 内自愈。
- **建议最小修复**：在任务终态写入路径（Activity/Engine.finish 或任务命令终态化）调用一次幂等 reconcile；或由调度器保证常驻并缩短 tick。**本轮未修复。**

### DEF-02（P3）更新任务详情把“能力版本”显示为“历史任务”

- **复现**：打开手动更新任务 `9a7d5d43…` 详情，查看 hero meta「能力版本」。
- **预期**：更新任务不适用筛选能力版本，应显示“不适用/更新任务”。
- **实际**：显示“历史任务”。
- **证据**：Chrome 页面文本确认；`TaskDetail.capability_version` 对更新任务为 null，前端 `pages.tsx` 使用 `item.capability_version || "历史任务"`。
- **根因与置信度**：高置信度，纯展示回退文案问题。
- **影响**：误导用户以为这是历史任务；不影响数据/调度。
- **建议**：按 `task_kind` 分支显示“更新任务不适用”或隐藏该字段。**本轮未修复。**

### OBS-01（P3，平台瞬时异常）首次手动更新的 fans 模块 `RESPONSE_SCHEMA_MISMATCH`

- **现象**：任务 `560a3fb6…` 的 `fans` 模块失败，failure=`PLATFORM_PAGE_CHANGED:RESPONSE_SCHEMA_MISMATCH`；证据显示 `request_key=daily_link`、HTTP 200、`content_type_kind=json`、`lookup_error=JSONDecodeError`、`root_keys=[]`。
- **对照**：7 分钟后重试同一达人，任务 `9a7d5d43…` `COMPLETED`，8 模块/两组精选完整；同日另一正常采集任务 `3130eb97…` 的 fans 9/9 完整。
- **判断**：更像平台瞬时返回非法/截断 JSON，而不是更新分支独有缺陷；现有部分更新/退避/重试行为正确。未见可复现的代码缺陷，置信度中等。
- **建议**：保留失败证据并观察平台响应；不在本轮修改解析器或放宽断言。

### ENV-01（验收阻塞）当前环境未运行 update-scheduler

- `dev.sh status`：update-scheduler **未运行**；`creator_update_schedule` 在测试开始为 0 行。
- 因此**真实周期性更新没有在 dev 环境自动发生**；F01 的真实批次执行未验收。
- 已用隔离库进程级验证调度器建批/重启不重复；不能替代真实 dev 批次。
- **建议**：在授权窗口启动 `make update-scheduler`，先将 `next_due` 控制为 1 位达人，执行 1 个小批次；确认后再恢复常规调度。

### LIM-01（限制）Temporal 不提供严格业务优先级

- 已验证 DB 认领顺序和 Activity 让路；未验证已派发 Workflow 的严格排序/抢占。按设计不强制中断运行中达人。
- 影响：正常采集优先是“尽力 + 安全边界”，不是 Temporal 级硬优先级。

### LIM-02（未验证）故障注入

- 未执行 Worker 真崩溃、DB/Temporal 停机、会话失效、平台安全验证等真实故障；只运行了既有单元/集成回归。未触发平台验证，也未绕过平台安全机制。

## 5. 核心业务闭环结论

1. **手动更新是否真实跑通？** **是（条件通过）**。第二次 `COMPLETED`；新快照、当前投影、达人库更新，旧快照 hash 不变，达人不重复，任务中心状态正确。首次为平台瞬时 fans 响应失败，重试成功。
2. **定时更新是否按周期创建并完成任务？** **部分**。五档规则、到期建批、单活跃批次、重启不重复通过隔离/进程级验证；真实 dev 调度器未运行，真实批次执行未完成 → **未完全通过**。
3. **所有任务是否统一进入任务中心？** **是**。采集、手动真实；定时任务用合成数据验证列表/详情/筛选；无独立更新中心。
4. **唯一执行单元能否处理三类任务？** **配置与认领层通过**；采集+手动真实执行；定时批次未真实执行。隔离矩阵三类全部可认领。
5. **执行单元任务类型配置是否生效？** **是**。5 种组合矩阵通过；未启动任务回池、已启动任务不打断通过隔离验证。
6. **是否存在执行资源冲突？** **未观察到冲突**。真实任务顺序执行，租约/单 Activity 并发 1；未做强制重叠测试。
7. **正常采集是否仍能端到端运行？** **是**。任务 `3130eb97…`：P1 模型 1 次、`filter_plans=1`、`QUEUED→COLLECTING→COMPLETED`、有效 1、快照 1，UI 正常。
8. **最新数据与历史快照是否正确？** **是**。手动更新新快照/当前投影/达人库更新；旧快照保留；不重复达人；部分更新不清旧值。
9. **当前是否具备交付验收条件？** **否（Conditional No-Go）**。手动更新主链路和正常采集回归通过，但存在 P2 调度状态收敛缺口，且真实周期批次未执行、调度器未运行、故障注入未覆盖。建议先修复/确认 DEF-01，并在授权窗口完成 1 个真实定时批次后再验收。

## 6. 测试数据与清理

- 真实测试任务（保留作为历史/证据）：
  - 手动更新 `560a3fb6-0cae-463c-b818-3ddf49fe4711`：`PARTIAL_COMPLETED`，新快照 `d2cd6e8c…`。
  - 手动更新 `9a7d5d43-daec-42be-ae61-ab377c17754b`：`COMPLETED`，新快照 `7945ec86…`。
  - 正常采集 `3130eb97-93e5-4987-b0b0-dd65f64e348c`：`COMPLETED`，关键词“露营”，目标 1。
- 测试达人 `6f13771f-b62a-4b6f-b5a4-c3aa85c86edd`（就叫Roxy）：快照 1→3，`data_updated_at` 更新；当前 `last_success_at=2026-10-17T16:27:02Z`，`next_due_at=2026-10-20T16:27:02Z`，失败计数 0。
- 正常采集新增达人 1 位、快照 1 份；总达人 59→60，快照 123→126。
- 合成定时任务 `b245d82f…`、合成取消任务 `6c452705…` 已删除；隔离测试 schema/数据库已删除。
- 未删除真实不可变快照/任务（历史证据保留）；未修改真实达人身份字段；未修改账号凭据。
- 测试期间未修改业务代码；新增文件仅为测试计划、报告、截图、证据 JSON 与 `.runtime/recon` 测试脚本。

## 7. 证据索引

- 测试计划：[UPD-acceptance-test-plan-2026-10-17.md](UPD-acceptance-test-plan-2026-10-17.md)
- 手动更新 UI/DB：[UPD-manual-e2e-2026-10-17.json](UPD-manual-e2e-2026-10-17.json)
- 正常采集回归：[UPD-collection-regression-2026-10-17.json](UPD-collection-regression-2026-10-17.json)
- 周期边界：[UPD-period-boundaries-2026-10-17.txt](UPD-period-boundaries-2026-10-17.txt)
- 执行单元矩阵：[UPD-pool-matrix-2026-10-17.txt](UPD-pool-matrix-2026-10-17.txt)
- 浏览器控制台/网络：[UPD-browser-observability-2026-10-17.json](UPD-browser-observability-2026-10-17.json)
- 截图：[assets/upd/](assets/upd/)
- 调度器进程日志：[assets/upd/scheduler-create.log](assets/upd/scheduler-create.log)；重启无新批次时日志为空，DB 计数证据见报告。
- 手动首次部分更新日志：[assets/upd/manual-first-attempt.log](assets/upd/manual-first-attempt.log)
- 正常采集日志：[assets/upd/collection-regression.log](assets/upd/collection-regression.log)
