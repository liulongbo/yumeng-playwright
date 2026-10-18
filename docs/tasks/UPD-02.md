# UPD-02：统一执行单元池匹配、优先级与更新执行分支

状态：待验收  
更新时间：2026-10-18T00:50:00+08:00  
是否验收：否；核心闭环通过，真实强制并发/故障注入未执行（非阻塞余项）。

## 目标与范围

**目的**：让更新任务通过统一执行单元池认领执行，并保证正常采集优先且不中断运行中的达人。

**包含**：正常采集能力守卫；Worker 未分配任务认领、优先级派发；Activity 能力复核；准入与达人边界让路；`Engine.run_update`；`recheck_session` 回退；update 失败原因映射。

**不包含**：多单元负载均衡、抢占式中断、定时调度器、产品 API/前端。

## 关联与依赖

F01/F02/F04/F05；DEC-017。前置：UPD-01。

## 验收清单

- [ ] 正常采集回归通过；单单元默认行为不变。
- [ ] update 任务不调用 `prepare/search`，只采集指定达人主页与两组精选。
- [ ] 两个 Worker 不重复认领同一未分配任务；无匹配单元时任务保持 QUEUED。
- [ ] 正常采集存在时，update 在拿浏览器前或达人边界让路；当前达人不被中断。
- [ ] update 成功产生新快照/投影/达人库更新且不新增达人；失败不清旧值。

## 实现记录

- [engine.py](../../backend/src/xingtu/engine.py)：`_bind_registry()` 提取、`run_update()`、达人边界让路、update 失败原因映射；`run()` 搜索路径保持。
- [worker.py](../../backend/src/xingtu/worker.py)：Activity 能力复核、拿浏览器前让路、按优先级派发、未分配任务认领、update/collection 路由。
- [adapter.py](../../backend/src/xingtu/adapter.py)：`recheck_session` 回退 `detail_page`。
- [repository.py](../../backend/src/xingtu/repository.py)：优先级/可运行任务判定、`SKIP LOCKED` 认领、配置变更回池。

## 验证证据

验收测试报告：[UPD-acceptance-report-2026-10-17.md](../evidence/UPD-acceptance-report-2026-10-17.md)；离线证据见 [UPD-01-05-offline-verification-2026-10-17.md](../evidence/UPD-01-05-offline-verification-2026-10-17.md)。

- 隔离库：`test_engine_run_update_does_not_search_or_duplicate_creator` 通过（`adapter.prepared == []`、仅访问目标达人、快照/达人库更新、不新增达人）。
- 隔离库：`test_pool_claim_and_priority_gate`、`test_creator_update` 其余 5 项通过。
- 既有采集集成回归通过（`94 passed, 1 skipped`）。
- 验收测试：执行单元能力矩阵（all/仅采集/仅手动/仅定时/采集+手动）与双线程认领竞争通过；正常采集+手动真实任务均由唯一单元顺序执行。
- **未执行**：两个真实 Worker 强制重叠时序、真实页面上的正常采集与更新让路、真实租约/会话故障注入。
- 结论：核心闭环通过；保留待验收仅因强制并发/故障注入未执行。

## 交接信息

UPD-03/04 依赖本卡的认领、执行分支与让路机制。

## 状态历史

- 2026-10-17T15:45:18+08:00：建立 → 进行中；按已批准方案开始实施。
- 2026-10-17T16:34:38+08:00：进行中 → 待验收；离线/隔离库检查通过，等待真实浏览器与双 Worker 时序验收。
- 2026-10-18T00:35:00+08:00：核心闭环通过；强制并发与故障注入未执行，保留待验收。
