# LIVE-03 巨量星图直播达人详情字段技术方案

状态：实现中（2026-11-05）

> 2026-11-06 增补：`xingtu-live-square-v4` / `xingtu-live-browser-v4` 新增 `basic.wechat`（真实页面 `联系` → `查看微信` dialog `.wechat`），仅快照/详情返回，任务列表剔除；不写 current。见 [LIVE-03-WECHAT 验收](../evidence/LIVE-03-wechat-acceptance.md)。
  
关联：[LIVE-03 卡片](../tasks/LIVE-03.md)、[真实契约调查](../evidence/LIVE-03-live-detail-investigation.md)、[字段差异](../evidence/LIVE-03-field-diff.md)、[DEC-021](../decisions/DEC-021-live-detail-snapshot-storage.md)。

## 1. 范围

在 LIVE-02/02F 已有巨量星图直播广场采集之上，新增直播详情业务模块：

- `basic` 扩展：`douyin_id`、`content_tags`、`business_order_types`、`introduction`。
- `live_pricing`：直播服务报价（按天/按小时/按商品）。
- `live_overview`：按直播类型 × 周期 × 统计口径的数据概览（含转化表现）。
- `live_analysis`：直播月历、近15场、近90天直播间列表。
- `live_audience`：按直播类型 × 粉丝/观众画像的完整分布。

不修改短视频 Adapter/契约；不修改聚星 Adapter/契约；不新增执行单元/队列/迁移；不启用直接 API。

## 2. 数据流

```
真实星图直播主页
  → LiveDetailRecorder（页面加载/交互期间注册的响应监听）
  → xingtu_live_detail.build_*（纯解析/标准化）
  → ModuleObservation(FieldObservation + StructuredValue)
  → creator_snapshots(payload.modules, creator_scene=live_square) 不可变快照
  → creator_live_current（仅基础列 + 既有 live.* 标量；新模块不进 live_metrics）
  → GET /api/creator-library/{id}?creator_scene=live_square 的 profile_payload
  → 前端 liveXingtuDetail.tsx（五模块/类型/周期/口径切换/图表/明细/空态）
```

## 3. 契约与字段

契约：`contracts/douyin_xingtu.live.verified.json`

- `contract_version=xingtu-live-square-v3`、`adapter_version=xingtu-live-browser-v3`。
- 筛选 capabilities 不变（13 个筛选项、capacity v2），避免旧计划失效。
- 模块顺序：`basic, live, live_pricing, live_analysis, live_audience, live_overview`（overview 最后，避免开关状态影响其他模块）。
- 新字段 key 不使用 `live.` 前缀，防止进入 `creator_live_current.live_metrics` 和达人库列表。

字段列表见 [字段差异](../evidence/LIVE-03-field-diff.md) 与契约。结构化值统一 metric envelope：

```
{raw, value, unit, status, reason?, bound?, range?, note?, unit_confidence?}
```

状态：`COLLECTED / NOT_PROVIDED / NO_DATA / NO_PERMISSION / FAILED / UNPARSED`。

## 4. 采集策略

### 4.1 页面加载响应
`profile()` 在导航前注册 `LiveDetailRecorder`，只登记以下路径（不含 business card）：

- candidates、statistics、periodic、latest、room_list、room_data、room_detail、audience、base_info、marketing_info、channel_info。

响应按 URL path + query 关联；限制 body 大小；非 JSON/非 200 不解析成空数据。

### 4.2 数据概览
- 读取 candidates，只处理 UI 可用的直播类型（游戏 disabled 则不请求）。
- 读取页面实际默认周期（可能被 profile 记住），采集该周期；再切换时间下拉的另一周期（30/90）并采集；恢复默认。
- 对默认类型做一次 `排除营销流量`、`只看星图商单` 扫描；其他类型的替代口径不采集，写入 `overview.meta.not_captured`。
- 每个 calibre 独立 key：`period_{p}_flow_{f}_star_{0/1}`。
- `flow_type=1` = 排除营销流量开（已实测）；`0` = 关。

### 4.3 直播分析
- 逐可用类型：点击类型 → 等待 periodic/latest；当前月为空时点击「上个月」补采一次。
- 直播间列表为近90天全量分页（样本 96 场/10 页）：`search_for_live_room_list` 取 item_ids，`multi_get_room_data` 取指标；最多 `max_pages=12`，分页信息保留。
- 列表接口不带 live_type；逐场类型从 latest 记录同 room_id 映射，未命中记 NOT_PROVIDED + 原因。
- 缺失原因：CTR 非星图商单、GMV 非带货直播；保留平台原文，不记 0。

### 4.4 受众画像
- 逐可用类型 × 粉丝/观众（下拉实际选项）：`get_author_live_watch_distribution`。
- 选择画像类型一次后切换类型，避免每次类型切换后下拉处于加载态。
- 控件短暂消失时轮询等待；选择失败重试。
- 分布保存计数 + 按合计计算的占比；不读取 hover/Canvas 单点。

### 4.5 基础资料/报价
- 基础：`get_author_base_info` 的 `live_labels_v2`/`live_order_labels`/`unique_id`；介绍取 `channel_info.self_intro` 并脱敏。
- 报价：`get_author_marketing_info.price_info`，`task_category=6` 为直播；按 desc 识别按天/小时/商品；每个服务独立对象。

## 5. 缺失与失败语义

| 平台/场景 | 状态 | 说明 |
|---|---|---|
| `0` | COLLECTED 0 | 真实零值 |
| `-` | NOT_PROVIDED | 平台未提供；raw 保留 |
| 非星图商单，不做统计 | NOT_PROVIDED + reason | CTR/CVR |
| 非带货直播，不做统计 | NOT_PROVIDED + reason | GMV/ecom |
| 无该直播类型/candidates=false | NO_DATA | 记录证据 |
| 页面无直播/没有开播 | NO_DATA | 模块仍可 complete |
| 请求/结构/动作失败 | FAILED 或 MODULE_COLLECTION_FAILED | 模块隔离，不伪造 |
| 单位异常（看播时长>86400） | COLLECTED + unit_confidence=ambiguous | 保留 raw，不换算 |

## 6. 存储与读模型

- 不新增迁移：新模块进快照 `payload.modules`；`creator_live_current.latest_snapshot_id` 指向最新快照。
- `creator_live_current` 仅保留 `live.*` 标量；新 key 不会进入 `live_metrics`。
- 详情 API 读时回退：最新快照模块为 FAILED/NOT_ATTEMPTED 时，从最近 3 份快照回读该模块，返回 `module_fallbacks`，不清空旧数据。
- `CreatorLibraryDetail.introduction` 从 `basic.introduction` 投影。
- 任务达人列表对 live 场景只返回 `basic/live` 模块；单达人详情返回完整 payload，避免 70 人列表膨胀。

## 7. 前端

- `frontend/src/liveXingtuDetail.tsx`：五模块；类型/周期/口径 tab/select；日历、趋势、明细表、分布图；空态/失败/回退提示。
- `frontend/src/liveDetail.ts`：纯解析/格式化（metricText、calibre 选择、distribution 计算、module fallback）。
- 复用 `profile/ui.tsx` 的 `TrendLine`/`DistributionBars`；不新增图表依赖。
- 聚星直播详情使用独立 `liveJuxingDetail.tsx`，共享 `liveCreator.tsx` 仅按平台分支，互不覆盖。

## 8. 验证

- 单元：解析/区间/缺失/类型口径/画像占比。
- 契约：新模块/字段、视频/聚星契约不变。
- 集成：快照→详情、失败模块回退、列表裁剪、introduction 投影。
- 前端：模块渲染/切换/空态/格式化。
- 真实：时尚筛选任务、手动更新、短视频/聚星回归；证据见 LIVE-03 验收文档。
