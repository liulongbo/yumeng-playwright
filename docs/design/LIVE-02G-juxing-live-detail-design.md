# LIVE-02G 磁力聚星直播达人详情技术设计

日期：2026-11-05
状态：已实现（代码与真实小样本验证见验收证据）
关联：[LIVE-02G 任务卡](../tasks/LIVE-02G.md)、[调查](../evidence/LIVE-02G-juxing-live-detail-investigation.md)、[字段字典](LIVE-02G-juxing-live-field-dictionary.md)

## 1. 目标与边界

在不改变 LIVE-02/02F 已验证的直播采集架构、执行单元、任务中心、70 位上限和短视频隔离的前提下，补齐磁力聚星直播达人详情的业务字段：

- 基础信息/标签/认证/三类报价；
- 数据概览（含信用分、预期最高在线、合作行业、观众摘要）；
- 达人指数（综合/维度/均值/排名/趋势）；
- 代表作品（个人/聚星/电商过滤/最近15场/频次）；
- 粉丝趋势（30/90 总量与增量）；
- 受众画像（观众/粉丝独立完整分布）；
- 带货数据（7/30/90 + goodsGraph + 热销品牌/类目）；
- 合作数据概览（30/90）；
- 客户评价（汇总/总数/明细分页）。

不做：数据库整体重构、新执行单元/队列/Profile、定时更新、星图直播/短视频变更、联系方式采集、70 位全量重跑。

## 2. 数据流

```text
磁力聚星直播详情页（已登录页面上下文）
  ├─ POST starProfile          ─┐
  ├─ POST starWorksInfo        │
  ├─ POST listPortrait         │  已登记响应，仅允许这几条路径
  ├─ POST starIndex/radar      │  （queryVideoPlayCnt 本次补充登记）
  ├─ POST starIndex/trend      │
  ├─ POST evaluation/score     │
  ├─ POST evaluation/list(分页)│
  ├─ POST commerce/live(7/30/90)│
  └─ POST queryVideoPlayCnt(type=4) ─┘
            │
            ▼
JuxingLiveDetailAdapter（按模块懒加载/缓存，失败局部化）
            │
            ▼
juxing_live_fields.py（纯解析/标准化/状态判定）
            │
            ▼
ModuleObservation/FieldObservation
  ├─ creator_snapshots.payload（不可变历史，全部状态）
  └─ creator_live_current.live_metrics（COLLECTED 当前读模型）
            │
            ├─ GET /api/creator-library/{id}?creator_scene=live_square
            │     → live_metrics（完整）+ profile_payload（完整快照）
            └─ GET /api/creator-library?...（列表）
                  → live_metrics 过滤详情大字段
            │
            ▼
/creators/:id/live（React，聚星专属区块）
```

## 3. 契约设计

契约版本 `juxing-live-square-v3` / `juxing-live-browser-v3`，模块：

| 模块 | 作用 |
|---|---|
| `basic` | 身份、内容分类/形式、行业、机构、认证 |
| `live` | 数据概览、报价明细、合作 30/90、观众摘要、旧 7 天 commerce 字段 |
| `fans_trend` | 30/90 涨粉数/率/总量/增量序列 |
| `index` | 综合分、雷达维度/同粉段均值、排名/比例、趋势 |
| `works` | 个人/聚星/最近15场作品、直播频次 |
| `audience` | 观众/粉丝画像 |
| `commerce` | 7/30/90 带货结构、热销品牌/类目 |
| `cooperation` | 评价汇总/总数/明细分页 |

旧 `basic`/`live` 字段全部保留；新增字段见字段字典。每个模块的 `requests` 记录真实 POST 路径与请求匹配；Adapter 仍使用显式 `DETAIL_PATHS` 白名单，未知路径 fail closed。

## 4. 存储设计

### 4.1 决策：继续 JSONB，不新增表/列/迁移

- 快照 `creator_snapshots.payload` 是完整不可变事实：字段值、状态、raw、单位、周期、来源路径、观测时间。
- `creator_live_current.live_metrics` 只保存 `live.*` 且 `COLLECTED` 的 envelope；结构化集合用 `StructuredValue.data` 保存。
- 作品、评价、画像、趋势、带货分析都属于“单达人详情集合”，无需全局检索；建专表会扩大迁移/写入/API 面积，不选。
- 评价去重键在单次采集内稳定；跨快照由快照不可变性和“最新快照”读取自然隔离，不建立累计评价表。

### 4.2 列表保护

`live_metrics` 中的详情大字段（作品、画像、趋势、评价、带货结构、报价明细等）在列表响应中过滤，详情响应完整返回。这样 70 位任务列表不会因为每个达人携带 50KB+ 集合而膨胀；数据本身不丢。

### 4.3 状态规则

见[字段字典 §4](LIVE-02G-juxing-live-field-dictionary.md)。核心：

- `COLLECTED`：响应成功且有值；
- `NO_DATA`：平台明确 null/空数组/页面 `-`/commerce 全 0；保留 raw；
- `FAILED`：请求 HTTP/业务失败或 schema 不符；不吞成 NO_DATA；
- 旧快照缺字段：前端显示“尚未采集”，不伪造；
- 结构化画像子维度：`availability` 区分 `COLLECTED` / `NO_DATA` / `SUMMARY_ONLY`。

## 5. Adapter 设计

- `LIVE_DETAIL_PATHS` 增加 `/rest/web/star/queryVideoPlayCnt`；其余沿用已登记路径。
- 按模块懒加载并缓存 `starProfile`、`starWorksInfo`、`listPortrait`、`starIndex`、`evaluation`、`commerce(7/30/90)`、`queryVideoPlayCnt`；同一次详情只请求一次。
- `collect_module` 支持 8 个模块；每个模块返回全部 `expected_fields`。
- 非 `basic` 模块的请求失败只产生该模块 FAILED 字段，不阻断已经成功的模块；`basic` profile 失败保持现有失败路径。
- 评价分页：
  - `size=10`，page=1..；
  - 以 `data.total` 与累计行数判断结束，忽略返回 0 的 `pageNum/pageSize`；
  - 达到 total、空页或短页停止；最多 50 页保护；
  - 页 2 失败保留页 1 数据，module coverage gap `REVIEW_PAGINATION_INCOMPLETE`（任务诚实 PARTIAL，不丢已采数据）。
- 评价无平台 ID：`review_key = sha256(starId|promotionType|timestamp|comprehensive|content|hiddenName|productName(非隐藏))`；同一快照内去重。
- 隐私：`hiddenName=true` 不保存原始 `productName`；评价文本中的手机号/微信模式脱敏；`introduction/businessPhone` 不采集。
- 现有 `live` 旧字段全部保留；commerce 旧字段的 `period_label` 从“近30天”修正为“近7天”（值本来就是 `duration=7`），这是元数据纠正，不是数值覆盖；旧快照保留原 label。

## 6. API/读模型

- 无需新增 API/迁移。
- 详情 `GET /api/creator-library/{id}?creator_scene=live_square`：
  - `live_metrics` 完整（含结构化集合）；
  - `profile_payload` 完整快照；
  - `field_sources` / `module_statuses` 指示状态与来源。
- 列表 `GET /api/creator-library`：
  - `live_metrics` 过滤 `LIVE_DETAIL_ONLY_METRICS`（作品/画像/趋势/评价/带货结构/报价明细等）；
  - 保留原有标量指标（含星图 live 字段），不影响列表卡片。
- 任务结果列表的 live payload 由共享查询层裁剪到 basic/live 模块；单达人详情仍完整（与并发 LIVE-03 的列表保护一致）。
- 手动更新沿用 `LiveCreatorUpdateService`，新契约模块自动进入 update 任务；不写 `creator_update_schedule`。

## 7. 前端设计

- `LiveCreatorDetailView` 保持两平台分发：
  - 聚星 → `JuxingLiveSections`；
  - 星图 → `XingtuLiveSections`（并发 LIVE-03，不在本任务范围）。
- `JuxingLiveSections` 按业务区块组织，使用 `profile_payload` 的字段状态做展示，`live_metrics` 仅在最新快照字段缺失/未采集时作为“上次成功值”回退并标注。
- 图表不引入新依赖：SVG 雷达/折线/柱状 + 现有 `distribution-list` 分布条。
- 交互：
  - 作品：个人/聚星、电商过滤、4 条/页、指标 tab、频次 月/周/时；
  - 粉丝：30/90、总量/增量；
  - 画像：观众/粉丝、省份/城市、占比/渗透；
  - 带货：7/30/90；合作：30/90；评价：10 条/页；
  - 指数：6 维趋势选择。
- 状态：NO_DATA=暂无数据、FAILED=采集失败、旧快照=尚未采集；commerce 平台 0/空结构显示暂无数据；不为完整性补 0。
- 样式只新增 `live-*` 局部 class，复用现有色板/面板/分布样式；不影响星图/短视频页面。

## 8. 兼容性与失败恢复

- 磁力聚星短视频：Adapter/契约/读模型不改；`content_theme_labels` 只增加 `content_type_labels` 优先回退，旧 `content_type` 仍可用。
- 巨量星图直播：本任务不改星图契约/Adapter；共享 `LiveCreatorDetailView` 分发到星图组件。
- 巨量星图/星图短视频：无修改。
- 任务中心/执行单元/并发/70 上限：无修改；71 仍 422。
- 数据隔离：直播不写 `platform_creators.projection`、不写星图 current、不写 schedule（已验证）。
- 旧快照/旧达人：读取时字段缺失显示尚未采集；不重写历史。
- 失败恢复：最新快照某模块 FAILED 时，共享读模型可回退到最近最多 3 份旧快照的同模块并标注 `module_fallbacks`（并发 LIVE-03 共享实现）；本任务字段仍以最新成功字段为准。
- 回滚：无数据库迁移；回退代码/契约即可；已发布快照和旧 current 不受破坏。

## 9. 已知限制

- 指数趋势两样本全 0（平台返回），保留并标记。
- 设备类型 `mobilePercentage` 两样本空，仅文字摘要。
- 九大人群/观众兴趣在样本中为空。
- 作品播放地址有时效签名；封面不进入对象存储。
- 评价无平台 ID；隐藏评价不保存订单名。
- 未重跑 70 位全量；沿用 LIVE-02 70 位证据 + 自动化/小样本。
- page 7+ 真实终点沿用 LIVE-02 未验证结论。

## 10. 变更文件

- 契约：`contracts/kuaishou_juxing.live.verified.json`、`contracts/kuaishou_juxing.live.observed.json`。
- 后端：`backend/src/xingtu/juxing_live_adapter.py`、`backend/src/xingtu/juxing_live_fields.py`、`backend/src/xingtu/creator_library.py`、`backend/src/xingtu/product_queries.py`。
- 前端：`frontend/src/liveJuxingModel.ts`、`frontend/src/liveJuxingDetail.tsx`、`frontend/src/liveJuxingCharts.tsx`、`frontend/src/liveCreator.tsx`、`frontend/src/pages.tsx`、`frontend/src/styles.css`。
- 测试：`backend/tests/unit/test_juxing_live_fields.py`、`backend/tests/unit/test_juxing_live_adapter_detail.py`、`backend/tests/integration/test_live_library.py`、`backend/tests/unit/test_live_square.py`、`frontend/src/liveJuxingDetail.test.tsx`。
- 文档/证据：本任务卡、调查、字段字典、验收、索引/总览。
