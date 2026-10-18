# DEC-017：达人手动/定时更新使用统一任务中心与统一执行单元池

- 日期：2026-10-17
- 状态：已批准（实施中）
- 关联：F01/F02/F03/F04/F05；UPD-01—UPD-05

## 待解决问题

现有系统只支持“表单 → P1 → 搜索 → 采集”的采集任务，没有已入库达人的手动更新与周期性更新；执行单元也没有“允许处理的任务类型”配置，派发无优先级。

## 选择

1. 任务类型使用 `root_tasks.task_kind ∈ {collection, manual_update, scheduled_update}`；不扩展已被 intake 来源占用的 `task_type`。
2. 手动/定时更新创建**未分配**的根任务，由具备对应能力的 Collection Worker 通过 `SKIP LOCKED` 认领；正常采集保留原有晋级分配路径，仅增加能力守卫/fallback。
3. 复用 `CollectionWorkflow` / `collect_segment_v1`，Activity 内路由 `Engine.run` 或 `Engine.run_update`；不新建 Workflow/Task Queue。
4. 更新任务不搜索、不调用 P1；只采集指定达人主页与两组默认精选。
5. 定时更新采用批次任务（默认 5 位，1–20 可配置），单活跃批次；达人级状态在 `creator_update_schedule`，不按达人建任务。
6. 优先级为 collection > manual_update > scheduled_update；在 DB 派发/认领排序、调度器建批前检查、Activity 拿浏览器前与达人边界让路三层生效；不抢占运行中的达人。
7. 周期基准为“最近一次有效更新成功时间”；有效更新 = 新快照 + 身份有效 + `pipeline_complete`；部分更新不重置周期，走 1h/6h/24h 退避。`data_updated_at` 保留“最近写入”语义，不改变正常采集写入行为。

## 主要替代方案

- 新建更新专用任务中心/爬虫：重复维护、违背统一约束。
- 所有任务共用一个 Temporal 队列或按任务类型拆队列：破坏每单元隔离或造成多套池。
- 按达人逐条建根任务：任务中心记录量过大，难以管理。
- 只靠 Temporal 队列顺序实现优先级：无法保证正常采集优先，且不可抢占已派发任务。

## 兼容性与影响

- 旧 `root_tasks` 无 `task_kind` 时默认 `collection`；旧 `TaskRecord` 仍有 plan。
- 正常采集的搜索、主页、精选、封面、持久化逻辑不变；只新增 update 分支与最小派发/查询扩展。
- 迁移仅新增列/表/索引；不重写既有快照或投影。
- 真实平台验收仍需单独授权；未验证项不得标记完成。

## 验证

实施后由 UPD-01—UPD-05 卡片记录命令、环境、结果与证据；详见各卡。
