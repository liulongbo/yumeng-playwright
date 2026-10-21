# HYB-01：Collection Worker 在线状态

状态：待验收
更新时间：2026-10-19
是否验收：否；待自动化回归与跨机实测。

## 目标与范围

基于指定 Temporal Task Queue 的 poller 识别 Worker 在线状态，并与执行单元状态、线路验证和浏览器租约分开展示；不改变租约代次及恢复语义。

## 验收清单

- [x] 动态监控 `xingtu-{unit_id}`，不以数据库 READY 推断 Worker 在线。
- [x] API/页面分别展示 Worker、执行单元、线路与浏览器租约状态。
- [ ] 停机与恢复可在 Temporal poller 信号允许的时间窗口内重新识别。

## 验证证据

- 2026-10-18：基线已有 TTL poller 判定，但 API monitor 只配置 `xingtu-intake`。
- 2026-10-19：Monitor 支持运行中登记 collection queue；执行单元 API/页面新增 `worker_status`、`unit_availability`、`line_health`、`browser_lease_status`。中心没有新鲜 NetworkProbe 时线路明确为 `UNKNOWN`，不以 READY/会话伪造健康。5 项相关 liveness/视图回归包含在 308 项单测中通过。
- 未验收：Mac 真正断线/恢复的跨机收敛（设计上为 poller freshness 180 秒 + 5 秒监控周期）留待第四/七阶段。

## 状态历史

- 2026-10-18：待办 → 进行中。
- 2026-10-19：进行中 → 待验收；代码完成，跨机行为尚未实测。
