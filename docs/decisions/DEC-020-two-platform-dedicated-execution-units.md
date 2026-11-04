# DEC-020：巨量星图与磁力聚星使用专属执行单元实现跨平台并行

日期：2026-11-03  
状态：**已实施，核心目标 GO，待用户验收**

## 要解决的问题

当前 `unit-local-mac-02` 一个执行单元同时绑定巨量星图与磁力聚星两个平台，只有一个 Collection Worker（`max_concurrent_activities=1`）和一条 Temporal 队列。两个平台的任务在 P1 晋级时都落到同一 `unit_id`，因此即使账号、Profile、登录态彼此独立，真实采集仍严格串行：一个平台的长任务会阻塞另一个平台。

## 决策

保留 `unit-local-mac-02` 作为巨量星图专属执行单元，新增 `unit-local-mac-03-juxing` 作为磁力聚星专属执行单元：

- 两单元各自一个 Collection Worker、一个 Temporal 队列（`xingtu-<unit_id>`）、并发 1。
- 两单元各自账号、Profile、Chrome 进程、快照、租约、心跳与故障恢复边界。
- 两单元共用当前本机 `local_development` 网络出口，不新增代理/IP。
- P1 晋级按 `plan.platform` 选择专属单元；历史任务 retry/continue 重新解析；更新任务继续按平台 binding 认领。
- 旧单元保留历史任务、Profile、登录态和队列；只把聚星 binding 置为 `enabled=false`。
- 新单元使用新的 `account_ref` 与 `profile_ref`，复制旧聚星 Profile 并核验会话，避免违反 `UNIQUE(profile_ref)` / `UNIQUE(platform, account_ref)`。

## 主要替代方案与不采用原因

1. **单单元提高 `max_concurrent_activities=2`**：`execution_units` 的 owner/lease/current task、`host_lock`、单 BrowserHost 均为单元级；要并发必须重构租约与浏览器宿主，破坏“一单元一浏览器”不变量，风险远大于收益。
2. **单进程内起两个 Temporal Worker**：进程级故障仍同时影响两平台，不满足故障隔离；配置与进程识别更复杂。
3. **新增代理/IP 分流**：超出本轮目标，成本和运维复杂度不必要。

## 兼容性影响

- 无数据库 schema 迁移；只新增/更新数据行（1 个 `execution_units`、1 个 binding，旧 binding `enabled=false`）。
- 旧 `unit-local-mac-02` 标识、历史任务 `unit_id`、旧队列名不变；历史数据不重写。
- 历史聚星任务重试/继续时会重新解析到新单元，并同步 `root_tasks.unit_id` 与 payload `execution_unit_id`。
- 平台专属单元不隐式创建星图 binding；单平台聚星释放状态使用真实 disposition。
- Intake Worker 加载“已声明但执行禁用”的平台 registry，避免星图单元禁用聚星 binding 后聚星 P1 失败。

## 实施与验证结果（2026-11-03）

- 已真实切换：新单元注册、聚星 Profile 复制并 VALID、旧聚星 binding 禁用、双 Worker/三队列就绪。
- 13 条真实 UI 任务全部 `COMPLETED`、各 1/1；新星图任务全部旧 unit，新聚星任务全部新 unit。
- 干净并行对真实 activity 重叠 65.99 秒；双平台各两任务平台内衔接 0.002/0.003 秒；每 unit 最大活动采集 1。
- 两方向 Worker 离线/重启隔离、真实星图滑块/接管/恢复、全栈重启通过。
- 已知：挑战恢复后一次既有 `LEASE_LOST`+30 秒重试；`dev.sh restart` 首次撞既有 45 秒 Worker 去重窗口。详见 [DUAL-UNIT-01 真实验收证据](../evidence/DUAL-UNIT-01-live-acceptance-2026-11-03.md)。

## 验证要求

- 两单元/两 Worker/两队列/两 Chrome/两 Profile 独立。
- 跨平台任务真实采集 activity 区间重叠；同平台任意时刻最多一个活动采集。
- 无错误路由；历史任务可读且 retry/continue 正确；故障隔离；回滚可恢复旧串行行为。
- 证据见 `docs/tasks/DUAL-UNIT-01.md` 与 `docs/evidence/DUAL-UNIT-01-*`。

## 限制

- 共用本机网络出口、Temporal、PostgreSQL、Redis：这些共同依赖故障会同时影响两平台，不属于单元隔离范围。
- 本轮不提升单平台并发，不新增 IP/代理，不改采集逻辑与前端业务。
