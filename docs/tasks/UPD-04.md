# UPD-04：达人周期性更新调度器

状态：待验收  
更新时间：2026-10-18T00:50:00+08:00  
是否验收：否；真实单达人定时批次已通过，失败/积压规模验证未执行（非阻塞余项）。

## 目标与范围

**目的**：按粉丝量档位生成定时更新批次任务，去重、失败退避、有效成功后重置周期。

**包含**：五档周期规则；`ensure/reconcile/claim/batch`；单活跃批次与 advisory lock；batch size CLI/env（默认 5，范围 1–20）；调度器进程、Makefile/dev.sh；失败退避与有效成功判定。

**不包含**：Temporal Schedule、多单元负载均衡、真实平台采集。

## 关联与依赖

F01/F03/F04/F05；DEC-017。前置：UPD-01/02。

## 验收清单

- [ ] 五档边界与 NULL 规则通过单测；跨档后 next_due 调整。
- [ ] 到期生成一个批次任务；单活跃批次；正常采集可运行时跳过建批。
- [ ] 批次内每位达人独立 checkpoint；部分达人失败不阻断其他达人。
- [ ] `pipeline_complete` 才重置周期；部分更新退避 1h/6h/24h 后回正常周期。
- [ ] 调度器停机不影响正常采集与手动更新；到期行不丢失。

## 实现记录

- [creator_update.py](../../backend/src/xingtu/creator_update.py)：五档周期、ensure rows、reconcile、due claim、单活跃批次、advisory lock、退避。
- [product_cli.py](../../backend/src/xingtu/product_cli.py)：`update-scheduler`（`--batch-size` 默认 5、`--tick-seconds`）；Makefile `update-scheduler`；`scripts/dev.sh` 启停/状态/日志。
- 迁移 018：`creator_update_schedule`、到期索引、`last_success_at/last_success_snapshot_id`。

## 验证证据

验收测试报告：[UPD-acceptance-report-2026-10-17.md](../evidence/UPD-acceptance-report-2026-10-17.md)；离线证据见 [UPD-01-05-offline-verification-2026-10-17.md](../evidence/UPD-01-05-offline-verification-2026-10-17.md)。

- 单元：五档边界/NULL、退避、next_due 通过（`test_creator_update.py`）。
- 隔离库：到期建批、单活跃批次、正常采集可运行时跳过建批、有效成功后重置周期通过。
- 验收测试：五档边界、未来到期不建批、到期建批、单活跃批次、调度器重启不重复、无 scheduled 能力跳过、手动有效成功重置/部分更新退避均通过（隔离库/进程级）。
- **真实批次**：`6871b08c…` 在只让目标达人到期、scheduler batch-size=1 的受控条件下 `QUEUED→COLLECTING→COMPLETED`；终态自动 reconcile 通过。
- **未执行**：真实失败/部分更新注入、长期积压/饥饿、多批次连续调度；保留待验收。

## 交接信息

UPD-05 依赖本卡的批次任务与 reconcile 语义。

## 状态历史

- 2026-10-17T15:45:18+08:00：建立 → 进行中；按已批准方案开始实施。
- 2026-10-17T16:34:38+08:00：进行中 → 待验收；隔离库调度逻辑通过，等待真实批次执行。
- 2026-10-18T00:35:00+08:00：隔离库调度器进程/去重通过。
- 2026-10-18T00:50:00+08:00：受控真实单达人定时批次完成；失败/积压规模验证未执行。
