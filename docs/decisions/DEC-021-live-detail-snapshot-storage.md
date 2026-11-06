# DEC-021：直播详情模块使用快照存储与读时回退

- 日期：2026-11-05
- 状态：已采纳
- 关联：[LIVE-03](../tasks/LIVE-03.md)、[LIVE-03 技术方案](../design/LIVE-03-live-detail-fields.md)

## 问题

巨量星图直播详情新增报价、分类型/周期/口径的数据概览、月历/近15场/近90天场次列表、受众画像。数据量大、维度多，需要回答：

1. 是否新增 `creator_live_current` 列或新表；
2. 如何保证不同直播类型/周期/口径不互相覆盖；
3. 最新快照某模块失败时，如何不清空已有有效数据；
4. 如何避免 70 人任务列表因 payload 膨胀。

## 选择

1. **不新增迁移**：新模块写入不可变 `creator_snapshots.payload.modules`（`creator_scene=live_square`），`creator_live_current.latest_snapshot_id` 指向最新快照。
2. 新字段 key 不使用 `live.` 前缀；`creator_live_current.live_metrics` 继续只存既有 `live.*` 标量，新模块不进入列表读模型。
3. 详情 API 读时按模块回退：最新快照模块为 `FAILED/NOT_ATTEMPTED` 时，从最近 3 份快照读取该模块最近一次 COLLECTED 版本，返回 `module_fallbacks`；历史快照不变。
4. 任务达人列表 `list_creators` 对 `live_square` 只返回 `basic/live`；单达人详情保持完整。
5. 口径扫描有界：类型 × UI 提供的周期全采；排除营销流量/只看星图商单只对默认类型扫描；未采组合写入 `overview.meta.not_captured`。
6. 保持 `direct_api_enabled=false`，不通过修改请求参数或直连 API 获取页面未提供的数据。

## 主要替代方案

| 方案 | 不采用原因 |
|---|---|
| 为每个指标加物理列 | 维度多、类型/周期/口径组合爆炸；契约变更频繁；迁移风险高 |
| 新建直播详情表 | 与现有快照/历史/回退机制重复；增加写路径与迁移 |
| 直接调用平台 API | 项目禁用直接 API；需签名/会话等价性验证；违反已定边界 |
| 把全部数据放进 `live_metrics` | 达人库列表按 creator 返回 metrics，70 人列表会膨胀；语义混淆 |
| 最新快照失败就显示失败 | 会清空用户已看到的有效数据，违反 LIVE-02 更新不清空原则 |

## 影响与验证

- 兼容：旧快照/任务/读模型不变；无数据库迁移；短视频/聚星路径不改。
- 性能：单达人详情 payload 增大（样本约 375KB）；任务列表已裁剪；如后续超过可接受阈值，再评估独立详情接口或字段瘦身。
- 验证：集成测试覆盖新模块返回、失败模块回退、列表裁剪、introduction 投影；真实手动更新验证快照追加与旧数据保留。
