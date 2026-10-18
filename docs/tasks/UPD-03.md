# UPD-03：单达人手动更新闭环

状态：已完成  
更新时间：2026-10-18T10:01:22+08:00  
是否验收：是；真实手动更新（重试后 COMPLETED）、状态/数据/快照/任务中心/终态自动 reconcile 均通过。

## 目标与范围

**目的**：达人库 → 达人主页可提交单达人更新任务，并在任务中心追踪状态、结果与最近成功更新时间。

**包含**：`POST /api/creator-library/{id}/updates`、`GET .../update`；幂等与在途认领；inline reconcile；前端按钮/状态/最近写入与最近成功；API/UI 测试。

**不包含**：任务入口的来源任务刷新别名、定时批次、真实采集验收。

## 关联与依赖

F02/F03/F05；DEC-017。前置：UPD-01/02。

## 验收清单

- [x] 点击生成一个 update 任务并进入任务中心；同键/重复点击返回同一任务。
- [x] 已有定时在途任务时复用现有任务，不重复创建。
- [x] 有效成功才重置周期；部分更新不清空旧值且不重置。
- [x] 页面展示任务状态、最近成功更新、最近写入、下次定时更新；在途按钮禁用。
- [x] 未知达人 404；CSRF/Origin/Idempotency-Key 校验生效。

## 实现记录

- 新增 [creator_update.py](../../backend/src/xingtu/creator_update.py)：手动更新幂等/在途认领、周期计算、ensure/reconcile/claim/batch、有效成功判定。
- [product_api.py](../../backend/src/xingtu/product_api.py)：`POST /api/creator-library/{id}/updates`、`GET /api/creator-library/{id}/update`；[product_models.py](../../backend/src/xingtu/product_models.py) 新增状态/响应 DTO。
- 前端：[pages.tsx](../../frontend/src/pages.tsx) 达人主页“手动更新”、在途禁用、最近成功/最近写入/下次到期；[CreatorProfile.tsx](../../frontend/src/profile/CreatorProfile.tsx) 入口动作。
- 任务中心：`TaskDetail.update_targets` 每位目标状态/失败原因。

## 验证证据

验收测试报告：[UPD-acceptance-report-2026-10-17.md](../evidence/UPD-acceptance-report-2026-10-17.md)；UI/DB 证据：[UPD-manual-e2e-2026-10-17.json](../evidence/UPD-manual-e2e-2026-10-17.json)；离线证据见 [UPD-01-05-offline-verification-2026-10-17.md](../evidence/UPD-01-05-offline-verification-2026-10-17.md)。

- 隔离库：手动更新创建 `manual_update` 任务、无 `requirements/filter_plans`、同键/重复点击返回同任务、在途复用、任务类型筛选、update targets 状态、有效成功重置周期均通过。
- 前端：TypeScript、`83 passed`、Vite build 通过；新增更新批次详情用例。
- API 路由：CSRF/登录/Idempotency-Key 测试通过。
- **真实 E2E**：手动更新两次；第一次 `PARTIAL_COMPLETED`（fans 瞬时 JSONDecodeError），重试 `COMPLETED`；新快照 2→3、旧快照 hash 不变、达人身份不重复、无搜索/P1；状态/最近成功时间页面与 API 一致。
- **DEF-01/DEF-02 已修复并复验**：终态自动 reconcile；能力版本显示“更新任务不适用”；详见 [修复与定时验收报告](../evidence/UPD-DEF-fix-and-scheduled-acceptance-2026-10-17.md)。
- **2026-10-18 合并前幂等回归**：在途复用返回前持久化当前请求键；任务终态后以该键重放仍返回原任务，与任务快照隔离用例合计 `2 passed`。
- 真实修复后手动任务 `797a9207…` `COMPLETED`；旧快照保留；调度自动收尾。
- 未执行：真实账号失效/安全验证故障注入。

## 交接信息

UPD-05 依赖本卡的 API/DTO 与页面状态。

## 状态历史

- 2026-10-17T15:45:18+08:00：建立 → 进行中；按已批准方案开始实施。
- 2026-10-17T16:34:38+08:00：进行中 → 待验收；离线/隔离库/前端通过，等待真实平台更新验收。
- 2026-10-18T00:35:00+08:00：真实手动更新 E2E 完成（重试后 COMPLETED）。
- 2026-10-18T00:50:00+08:00：DEF-01/DEF-02 修复并复验；待验收 → 已完成。
- 2026-10-18T10:01:22+08:00：修复在途任务复用路径的幂等记录缺失并完成终态重放回归；状态保持已完成。
