# LIVE-02G：磁力聚星直播达人详情字段补全

状态：**已完成（CONDITIONAL GO）**
建立时间：2026-11-05T21:30:00+08:00
最近更新：2026-11-05T22:25:00+08:00
是否验收：是（字段补全与真实小样本通过；E2E 环境阻塞、70 未重跑等条件见 §验证证据）
关联：[LIVE-02](LIVE-02.md)（已完成，CONDITIONAL GO）、[LIVE-02F](LIVE-02F.md)（CONDITIONAL GO）、[技术方案](../design/LIVE-02G-juxing-live-detail-design.md)、[字段字典](../design/LIVE-02G-juxing-live-field-dictionary.md)、[调查证据](../evidence/LIVE-02G-juxing-live-detail-investigation.md)、[验收证据](../evidence/LIVE-02G-acceptance.md)

## 目标与范围

在 LIVE-02 已完成的磁力聚星直播广场采集之上，补齐「直播达人详情」中平台真实提供的业务字段：

1. 基础信息：内容分类/标签/行业/认证、三类直播报价的业务类型、单位与金额。
2. 数据概览：信用分、预期最高在线人数、历史合作行业、观众摘要；区分最高在线与预期最高在线。
3. 达人指数：综合指数、雷达维度、同粉丝段均值、同行业/同粉段排名与比例、同类型趋势。
4. 代表作品：个人作品、聚星作品、只看电商带货、最近 15 个直播、逐作品字段、直播频次分布。
5. 粉丝趋势：近 30/90 天涨粉数/率、总量与增量日期序列。
6. 受众画像：观众与粉丝独立、完整分布（性别/年龄/设备品牌/设备价格/设备类型/活跃度/城市等级/省市/兴趣/九大人群/TGI）。
7. 带货数据：7/30/90 天场次、观看中位数、最高在线中位数、商品数、带货分析；0 与暂无数据区分。
8. 合作数据概览：30/90 天接单率、完单率、订单完成数。
9. 客户评价：汇总评分、评价总数、全部评价明细分页；隐藏评价身份，内容联系方式脱敏。

同时完成：JSONB/快照/current 存储、达人库详情 API 返回、`/creators/:id/live` 前端展示、手动更新同链路。

不包含：数据库表结构重构、定时更新、执行单元/队列/并发变更、短视频及星图直播行为变更、70 位全量重跑、联系方式/私密信息采集。

## 关键调查事实

- 附件为混合样本：基础/概览/报价/指数/合作/评价来自 userId 52022133（starId 9104），代表作品/粉丝趋势/受众画像明细来自 userId 1633604095（starId 451066）。验收同时使用两位达人。
- 真实详情接口均为登录页内 POST：`starProfile`、`starWorksInfo`、`listPortrait`、`starIndex/starRadarGraph`、`starIndex/starTrendGraph`、`evaluation/star/score`、`evaluation/star/list`、`commerce/live`（7/30/90）、`queryVideoPlayCnt`（type=4）。
- `cityPercentage` = 城市等级，`cityLevelPercentage` = 城市名；平台命名与语义相反。
- `livePcuCnt` = 最高在线人数，`liveMaxExpectOnlineViewer` = 预期最高在线人数，不能合并。
- `creditScore`（近30天信用分）与 `evaluation.credit`（评价信用评分）是不同字段。
- 9104：指数 81.6/30538/78.3%/64；作品 19/57/15，电商过滤 4；频次 33/48/9；带货 7 天无数据、30/90 有数据；合作 56.4%/72%/18 与 73.6%/84.5%/60；评价 18 条。
- 451066：作品 35/0/15；粉丝趋势 +23.1万/1.4% 量级；合作 30/90 与评价均为空；评价接口 score 返回 5.0 但页面显示空态，不能当有效评价。

## 验收清单

- [x] 契约 v3：8 模块、新增字段、来源/单位/周期/coverage_gaps 完整；旧字段保留。
- [x] 纯解析器覆盖所有新增字段与空值/0/失败/分页/去重/隐私规则。
- [x] Adapter 按模块采集，评价分页，失败局部化，不修改搜索/身份/并发。
- [x] 快照与 `creator_live_current.live_metrics` 保存结构化集合；旧成功值不被失败清空。
- [x] 列表 API 不返回详情大字段；详情 API 返回完整字段；旧快照显示尚未采集。
- [x] 前端聚星直播详情按模块展示；图表使用真实数值；周期/作品/评价切换可用。
- [x] 9104 真实任务 COMPLETED，源→DB→API→前端逐项核对。
- [x] 451066 真实任务 COMPLETED，空数据/0/未提供状态正确。
- [x] 9104 直播手动更新成功；新快照、字段一致、旧快照不变、schedule 0 行。
- [x] 星图直播/两平台短视频/任务中心/70 上限/执行单元/数据隔离回归通过（自动化 + 页面加载；未重跑 70 全量）。
- [~] 自动化测试、前端 build、mypy/ruff 通过：unit 442、contract 43、integration 133/1 skip、frontend 119、build、mypy 44 通过；E2E 6 passed/8 blocked（Temporal ephemeral server 下载被环境网络阻止）；全仓既有 ruff/format 问题不在本任务。
- [x] 证据与卡片回写。

## 实现记录

- 2026-11-05T21:30：建立卡片；分支 `1105-live02g`（起点 `1104-llb`）。
- 契约：`juxing-live-square-v3` / `juxing-live-browser-v3`，8 模块（basic/live/fans_trend/index/works/audience/commerce/cooperation），新增作品/画像/趋势/评价/带货集合。
- 后端：新增 `juxing_live_fields.py` 纯解析器；重写 Adapter 详情模块加载/缓存/失败局部化/评价分页；`creator_library.py` 增加 `content_type_labels` 回退；`product_queries.py` 列表裁剪详情大字段、详情完整。
- 前端：新增 `liveJuxingModel.ts`、`liveJuxingCharts.tsx`、`liveJuxingDetail.tsx`；`liveCreator.tsx` 聚星分支接入；`pages.tsx` 类型标签回退；`styles.css` 新增 `live-*` 局部样式。
- 存储：无迁移；快照 `payload` + `creator_live_current.live_metrics` JSONB。
- 并发说明：同一工作区同时存在另一会话的 `docs/tasks/LIVE-03.md`、`xingtu_live_detail.py`、`liveXingtuDetail.tsx` 等星图直播改动；本卡不把星图新增功能计为 LIVE-02G 成果，只在兼容性上确认聚星改动未改星图 Adapter/契约。
- 未提交 Git（工作区含并发 LIVE-03 改动，避免误提交他人未完成工作）；本轮交付以工作区 + 文档证据为准。

## 验证证据

- 调查：[LIVE-02G 调查](../evidence/LIVE-02G-juxing-live-detail-investigation.md)
- 验收：[LIVE-02G 验收](../evidence/LIVE-02G-acceptance.md)
- 字段字典：[LIVE-02G 字段字典](../design/LIVE-02G-juxing-live-field-dictionary.md)
- 技术设计：[LIVE-02G 设计](../design/LIVE-02G-juxing-live-detail-design.md)
- 真实任务：
  - 9104 `397b46dc-0cb4-4f8f-ae90-5d5bffd017d4` COMPLETED，快照 `4dfa3792-3136-4265-a22b-6127eb2bbec7`
  - 451066 `0e1e01c3-3293-4469-8934-2fdf5f0cb56a` COMPLETED
  - 9104 手动更新 `56592cc0-f56f-4b99-aa39-befd07e14e3e` COMPLETED，新快照 `81863e94-2fdb-43eb-90ee-3bd985c44610`
- 截图：[9104 顶部](../evidence/assets/LIVE-02G/live02g-9104-top.png)、[9104 作品区](../evidence/assets/LIVE-02G/live02g-9104-works.png)、[451066 顶部](../evidence/assets/LIVE-02G/live02g-451066-top.png)
- 原始响应/日志：`.runtime/live03-investigation/`（gitignored）
- 自动化：unit 442、contract 43、integration 133/1 skip、frontend 119、frontend build 通过；mypy 44 files；E2E 6/8 blocked（Temporal 下载）。

## 残余与条件

1. 未重跑 70 位全量（用户要求）；沿用 LIVE-02 70 证据 + 71 拒绝/自动化/小样本。
   - 2026-11-06 后续 LIVE-02H 已完成磁力聚星直播「时尚」70/70 COMPLETED、资料完整 70/70、0 FAILED；同任务继续+补采，未重建。见[LIVE-02H](LIVE-02H.md)。
2. E2E 8 条因 Temporal ephemeral server 下载被网络阻止，BLOCKED；非代码断言失败。
3. 指数趋势两样本全 0；设备类型仅文字摘要；九大人群/观众兴趣样本空。
4. 作品播放地址为有时效签名；评价无平台 ID；page 7+ 未验证。
5. 工作区含并发 LIVE-03 星图改动，未提交 Git；若需独立提交需先与另一会话协调。

## 交接信息

- 当前阶段：已完成（CONDITIONAL GO）；未提交 Git。
- 约束：不改短视频/星图直播；不新增迁移/执行单元/队列；不启动定时更新；不合并/推送 main。
- 下一步（若有条件）：独立提交 LIVE-02G；在不与 LIVE-03 冲突时复跑 E2E；按需验证 page 7+ 与 70 全量；若需历史评价聚合再评估专表。

## 状态历史

- 2026-11-05T21:30:00+08:00：待办 → 进行中；开始实现。
- 2026-11-05T22:25:00+08:00：开发、真实采集/手动更新/前端验收与文档完成；判定 CONDITIONAL GO。
