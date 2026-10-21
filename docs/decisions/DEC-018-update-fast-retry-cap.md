# DEC-018：达人更新「数据不完整」的快速重试上限为 2 次

- 日期：2026-10-21
- 状态：已实施（2026-10-21）
- 关联：UPD-04；技术方案 §10A.1「异常与失败」

## 待解决问题

定时更新任务以 `PARTIAL_COMPLETED` 结束（达人快照 `pipeline_complete=false`）时，调度层按
`1h → 6h → 24h → 粉丝档位周期` 退避并无限重试。2026-10-21 本地实测：18 个任务全部部分完成，
59 位达人目标被执行 78 次（19 次重复采集），22 位达人进入快速重试；平台请求与带宽被反复消耗，
而结构性缺失（固定模块抓不到）时重试并不能补全。产品要求把快速重试限制为 **2 次**。

## 选择

- 快速重试上限 `MAX_FAST_RETRIES = 2`：第 1 次失败后 +1 小时、第 2 次失败后 +6 小时各重试一次；
  第 3 次仍不完整则**不再快速重试**，直接按该达人粉丝档位周期（1/3/5/7/15 天）安排下一次正常更新。
- 规则实现在 `creator_update._backoff`，`_reconcile_row` 的调用方式不变；不新增状态、不改任务状态机、
  不改数据库结构；`consecutive_failures` 继续保留原有语义（跨成功清零）。
- 采集任务本身的重试（Temporal Activity 最多 4 次、UI「重试失败步骤」）不受影响。

## 主要替代方案

- 保留 24 小时第 3 次快速重试：仍会在一天内多爬 1 次，且不解决结构性问题。
- 达到上限后彻底停止该达人的自动更新：会长期停留在「数据不完整」，且需要新状态/迁移/UI，改动大。
- 只补缺失模块而不是整批重采：更彻底，但属于采集层改造，另立任务（UPD 后续卡）。

## 影响

- 不完整达人的重试次数从「无限（1h/6h/24h/周期）」降为「最多 2 次快速重试 + 正常周期」。
- 已存在 `consecutive_failures ≥ 3` 的行会在下次 reconcile 时直接按周期安排（存量数据无需迁移）。
- 产品语义变化，需要同步技术方案 §10A.1 与 UPD-04 验收项。

## 验证

- `backend/tests/unit/test_creator_update.py::test_backoff_is_capped_by_the_normal_interval`：
  `_backoff(1)=1h`、`_backoff(2)=6h`、`_backoff(3)=档位间隔`、`_backoff(4)=档位间隔`。
- 全量单测与 lint/typecheck 通过后记录在 UPD-04 验证证据。
- 2026-10-21：`pytest backend/tests/unit -q` 303 passed；`pytest backend/tests/integration/test_creator_update.py` 8 passed（隔离库）；`ruff`/`mypy` 通过。
