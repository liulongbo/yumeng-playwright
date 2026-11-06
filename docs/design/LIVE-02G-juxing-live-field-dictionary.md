# LIVE-02G 磁力聚星直播达人详情字段字典

契约：`contracts/kuaishou_juxing.live.verified.json`（`juxing-live-square-v3`）
调查：2026-11-05 真实页面/接口（9104 王者荣耀王小贱、451066 桐桐就酱）
关联：[设计](LIVE-02G-juxing-live-detail-design.md)、[调查证据](../evidence/LIVE-02G-juxing-live-detail-investigation.md)

## 1. 读法

- 每个字段由 `FieldObservation` 封装：`status/value/raw_value/unit/period_label/source_kind/source_contract/path_ref/observed_at`。
- `status`：`COLLECTED`（成功有值）、`NO_DATA`（平台明确无数据/空/页面 `-`）、`FAILED`（采集失败）、`NOT_ATTEMPTED`（本次未执行）；旧快照缺字段在 UI 显示“尚未采集”。
- 比率统一 0–1；金额人民币元；时长秒（原始毫秒保留）；日期 ISO + 原始 label。
- 未列出的联系人/介绍/商务电话不采集。

## 2. `basic`：基础信息

| field_key | 名称 | 来源 | kind/unit | 状态规则 |
|---|---|---|---|---|
| `platform_creator_id` | 快手ID（userId） | `starProfile.userId` | text | null → NO_DATA |
| `platform_star_id` | starId | `starProfile.starId` | text | null → NO_DATA |
| `nickname` | 昵称 | `starProfile.name` | text | 空 → NO_DATA |
| `avatar_uri` | 头像 | `starProfile.headUrl` | text | 空 → NO_DATA |
| `gender` | 性别 | `starProfile.gender` | text | 空 → NO_DATA |
| `province` | 省份 | `starProfile.address` 拆分 | text | 地址空 → NO_DATA |
| `city` | 城市 | `starProfile.address` 拆分 | text | 地址空 → NO_DATA |
| `followers` | 粉丝数 | `starProfile.fansNumber` | number/count | null → NO_DATA |
| `creator_type_label` | 达人类型 | `starProfile.starTagStr` | text | 样本为空 → NO_DATA；不拿内容分类冒充 |
| `industry_labels` | 所属行业 | `starProfile.industryTag` | tags | 空 → NO_DATA；回退 `industryTagStr` 拆分 |
| `mcn_name` | 所属机构 | `starProfile.govName` | text | 空 → NO_DATA |
| `content_type_labels` | 内容分类及标签 | `starProfile.contentTypeTag` | tags | first/second 组合；空 → NO_DATA |
| `content_form_labels` | 内容形式 | `starProfile.contentFormTag` | tags | 空 → NO_DATA |
| `verified_info` | 认证信息 | `starProfile.verifiedInfo` | text | 空 → NO_DATA |

## 3. `live`：数据概览/报价/合作概览/观众摘要

| field_key | 名称 | 来源 | kind/unit/period | 状态规则 |
|---|---|---|---|---|
| `platform_star_id` | starId | `starProfile.starId` | text | 保留兼容 |
| `live.expect_viewer` | 预期观看人数 | `starProfile.livePlayCntExpectancy` | number/count | null → NO_DATA |
| `live.max_online` | 最高在线人数 | `starProfile.livePcuCnt` | number/count | 与预期最高在线分开 |
| `live.expect_cpm` | 预期CPM | `starProfile.liveCpmExpectancy` | number/cpm | null → NO_DATA |
| `live.weekly_sessions` | 周均直播场次 | `starProfile.liveWeeklyTimesCnt` | number/count | null → NO_DATA |
| `live.avg_people` | 平均观看人数 | `starProfile.liveAvgPeopleNum` | number/count | 保留原值；0 不擅自当缺失 |
| `live.avg_like` | 场均点赞 | `starProfile.liveAvgLikeCnt` | number/count | 同上 |
| `live.week_release` | 直播周发布 | `starWorksInfo.starWorkReport.liveWeekRelease` | number/count | works 失败 → FAILED |
| `live.interaction_rate` | 直播互动率（平台原值） | `starWorksInfo.starWorkReport.liveInteractionRate` | ratio（平台原值，不缩放） | 平台值可能 >1；保持原值不缩放；works 失败 → FAILED |
| `live.quote_hour` | 按小时报价 | `starProfile.priceShowInfo[type=1]` | number/yuan | 原始 price/1000；缺失 → NO_DATA |
| `live.quote_day` | 按天报价 | `priceShowInfo[type=2]` | number/yuan | 同上 |
| `live.quote_goods` | 按商品报价 | `priceShowInfo[type=3]` | number/yuan | 同上 |
| `live.quote_details` | 报价明细 | `starProfile.priceShowInfo`（businessLine=2） | structured | 保留 business_line/price_type/price_type_name/page_label/price_raw/price_yuan/currency/original/start/end；空 → NO_DATA |
| `live.expect_max_online` | 预期最高在线人数 | `starProfile.liveMaxExpectOnlineViewer` | number/count | 与 `live.max_online` 不同字段 |
| `live.credit_score` | 近30天信用分 | `starProfile.creditScore` | number/score/近30天 | null → NO_DATA；不用评价 credit 补 |
| `live.cooperation_industries` | 历史合作行业 | `starProfile.liveBusinessReport.advertiserFirstIndustries` | tags | 空 → NO_DATA |
| `live.viewer_feature_tags` | 观众特征摘要 | `starProfile.viewerFeatureTag` | tags | 平台文字摘要 |
| `live.viewer_device_tags` | 观众设备摘要 | `starProfile.viewerDeviceTag` | tags | 设备类型完整分布缺失时用于 SUMMARY_ONLY |
| `live.viewer_area_tags` | 观众地域摘要 | `starProfile.viewerAreaTag` | tags | 平台文字摘要 |
| `live.accept_order_rate_30d` | 近30天接单率 | `...acceptOrderRateData.30` | ratio/近30天 | null/0 且三项均空 → NO_DATA |
| `live.complete_order_rate_30d` | 近30天完单率 | `...completeOrderRateData.30` | ratio/近30天 | 同上 |
| `live.completed_orders_30d` | 近30天订单完成数 | `...completeOrderCntData.30` | count/近30天 | 同上 |
| `live.accept_order_rate_90d` | 近90天接单率 | `...acceptOrderRateData.90` | ratio/近90天 | 同上 |
| `live.complete_order_rate_90d` | 近90天完单率 | `...completeOrderRateData.90` | ratio/近90天 | 同上 |
| `live.completed_orders_90d` | 近90天订单完成数 | `...completeOrderCntData.90` | count/近90天 | 同上 |
| `live.commerce_sessions` | 带货直播场次（7天） | `commerce/live.data.liveCnt` (duration=7) | count/近7天 | 全 0/空 → NO_DATA + raw 0 |
| `live.commerce_watch_median` | 观看人数中位数（7天） | `...liveWatchCntMedian` | count/近7天 | 同上 |
| `live.commerce_max_online_median` | 最高在线中位数（7天） | `...liveMaxOnlineCntMedian` | count/近7天 | 同上 |
| `live.commerce_goods` | 带货商品数量（7天） | `...goodsCnt` | count/近7天 | 同上 |

## 4. `fans_trend`：粉丝趋势

| field_key | 名称 | 来源 | kind/unit/period | 状态规则 |
|---|---|---|---|---|
| `live.follower_growth_30d` | 近30天涨粉数 | `starProfile.fansIncreaseNum.30` | number/count/近30天 | null → NO_DATA；0 可有效 |
| `live.follower_growth_rate_30d` | 近30天涨粉率 | `starProfile.fansIncreaseRateIn30` | ratio/近30天 | 0.0% 有效；null → NO_DATA |
| `live.follower_trend_30d` | 近30天粉丝趋势 | `trendData.30` + `trendDiffData.30` | structured/近30天 | `total_series`/`increment_series` 各自日期点；空 → NO_DATA |
| `live.follower_growth_90d` | 近90天涨粉数 | `fansIncreaseNum.90` | count/近90天 | 同上 |
| `live.follower_growth_rate_90d` | 近90天涨粉率 | `fansIncreaseRateIn90` | ratio/近90天 | 同上 |
| `live.follower_trend_90d` | 近90天粉丝趋势 | `trendData.90` + `trendDiffData.90` | structured/近90天 | 同上 |

## 5. `index`：达人指数

| field_key | 名称 | 来源 | kind/unit | 状态规则 |
|---|---|---|---|---|
| `live.index_score` | 达人综合指数 | `starRadarGraphVO.starIndexCurrent[starIndexCurr]` | number/score | 缺失 → NO_DATA |
| `live.index_dimensions` | 维度与同粉段均值 | `starIndexCurrent` + `starIndexAvg` | structured | 当前 6 维；均值 5 维（无综合）；缺失维度放 `missing_avg_dimensions` |
| `live.index_industry_rank` | 同行业达人排名 | `starIndexRank[bizStarRank]` | count | 缺失/0 → NO_DATA |
| `live.index_industry_percent` | 超越同行业比例 | `starIndexPercent[bizStarPercent]` | ratio | 0 可有效；缺失 → NO_DATA |
| `live.index_fans_rank` | 同粉丝段排名 | `starIndexRank[fansStarRank]` | count | 缺失/0 → NO_DATA |
| `live.index_fans_percent` | 同粉段比例 | `starIndexPercent[fansStarPercent]` | ratio | <0.5 页面显示“低于50%以上达人” |
| `live.index_trend` | 同类型达人指数趋势 | `starIndexHistory` | structured | 10 条序列全存；页面暴露 6；全 0 标记 `all_zero` |

## 6. `works`：代表作品与直播表现

| field_key | 名称 | 来源 | kind/period | 状态规则 |
|---|---|---|---|---|
| `live.personal_live_works` | 个人作品 | `starWorksInfo.personLiveWorks` | structured/近30天 | 全量数组；空 → NO_DATA |
| `live.commercial_live_works` | 聚星作品 | `starWorksInfo.adSocialLiveWorks` | structured | 全量；空 → NO_DATA |
| `live.recent_live_works` | 最近15个直播 | `starWorksInfo.recentLiveWorks` | structured/最近15个直播 | chart 源 |
| `live.live_frequency` | 直播频次分布 | `queryVideoPlayCnt.data.starWorkPlayMonthInfo/WeekInfo/HourInfo` | structured/近三个月 | 月/周/时；全空 → NO_DATA |

作品对象：

| 键 | 说明 | 规则 |
|---|---|---|
| `stream_id` | 平台作品唯一标识 | 缺失/重复跳过并记 coverage gap |
| `title` | caption | 空保留 null |
| `cover_url` | 平台封面 URL | 不进入对象存储；前端失败占位 |
| `media_url`/`media_url_kind` | 平台播放地址 | `playback_signed`；带 auth_key、有时效；不伪造公开作品页 |
| `published_at`/`published_at_ms` | 发布时间 | ISO +08:00 + 原始 ms |
| `duration_seconds`/`duration_ms` | 直播时长 | 秒 + 原始 ms |
| `view_count` | 观看量 | 0 保留 |
| `peak_online_count` | 最高在线人数 | 0 保留 |
| `like_count`/`comment_count`/`share_count` | 点赞/评论/分享 | 0 保留 |
| `has_sku_info` | 是否电商带货 | 前端“只看电商带货”过滤依据 |
| `order_id` | 聚星订单 ID | 字符串，避免大整数精度损失 |
| `collection_kind` | personal/commercial/recent | 列表归属 |

## 7. `audience`：受众画像

| field_key | 名称 | 来源 | kind | 状态规则 |
|---|---|---|---|---|
| `live.viewer_portrait` | 观众画像 | `listPortrait.data.viewerPortrait` | structured | 全部维度 + TGI + availability；整体空 → NO_DATA |
| `live.fan_portrait` | 粉丝画像 | `listPortrait.data.fansPortrait` | structured | 独立保存，不拿观众替代 |

画像维度（两侧同名 key）：

| 语义 key | 平台原键 | 说明 |
|---|---|---|
| `gender` | `sexPercentage` | 比例 0–1 + TGI |
| `age` | `agePercentage` | 年龄段 |
| `device_brand` | `mobileBrandPercentage` | 设备品牌（“设备分布”页面的真实来源） |
| `device_price` | `mobilePricePercentage` | 设备价格区间 |
| `device_type` | `mobilePercentage` | 两样本为空 → `SUMMARY_ONLY`（用 viewerDeviceTag 文本） |
| `activity` | `activityPercentage` | 观众/粉丝活跃度 |
| `city_tier` | `cityPercentage` | **平台命名相反**：城市等级；raw_label firstline→一线等 |
| `city` | `cityLevelPercentage` | 城市名 |
| `province` | `areaPercentage` | 省份占比 |
| `province_share` | `areaTopWithRadio` | 省份占比面板 |
| `province_penetration` | `areaTopWithPermeation` | 省份渗透 |
| `interest` | `interestPercentage` | 仅粉丝有；观众空 |
| `nine_major_groups` | `nineMajorGroupsPercentage` | 两样本空 → NO_DATA |

每个点：`{raw_label,label,value,tgi}`；`availability` 标 `COLLECTED/NO_DATA/SUMMARY_ONLY`。

## 8. `commerce`：带货数据

| field_key | 名称 | 来源 | kind/period | 状态规则 |
|---|---|---|---|---|
| `live.commerce_7d` | 近7日带货数据 | `commerce/live duration=7` | structured/近7日 | 全 0/空 → NO_DATA + raw 0；`zero_means_no_data=true` |
| `live.commerce_30d` | 近30日带货数据 | `commerce/live duration=30` | structured/近30日 | 有值 → COLLECTED；含 goodsGraph |
| `live.commerce_90d` | 近90日带货数据 | `commerce/live duration=90` | structured/近90日 | 同上 |
| `live.hot_brands` | 热销Top品牌 | `starProfile.hotBrandInfo` | structured | 空 → NO_DATA |
| `live.hot_categories` | 优势类目 | `starProfile.hotChannelInfo` | structured | 空 → NO_DATA |

结构：`period_days/requested_duration/response_duration/live_cnt/live_watch_cnt_median/live_max_online_cnt_median/goods_cnt/goods_graph[{range,count}]/unit/zero_means_no_data`。

## 9. `cooperation`：合作数据概览 + 客户评价

合作 30/90 字段在 `live` 模块（见 §3）。评价：

| field_key | 名称 | 来源 | kind | 状态规则 |
|---|---|---|---|---|
| `live.evaluation_summary` | 评价汇总 | `evaluation/star/score.data` | structured | total=0 → NO_DATA（不展示 5.0 默认分）；否则 comprehensive/content_quality/cooperation/credit/total_reviews |
| `live.evaluation_total` | 评价总数 | `evaluation/star/list.data.total` | number/count | 0 也 COLLECTED |
| `live.evaluation_reviews` | 评价明细 | `evaluation/star/list` 全部页 | structured | `{total,collected,pages,complete,items[]}`；total=0 → NO_DATA + raw total 0 |

评价对象：`review_key`（稳定哈希）、`comprehensive/content_quality/cooperation/credit`、`content`（联系方式脱敏）、`content_redacted`、`timestamp/occurred_at`、`hidden_name`、`reviewer_label`、`promotion_type`、`have_agent`。隐藏评价不保存原始 `productName`。

## 10. 附件字段 → 本次实现

| 附件模块/字段 | 状态 | 实现 |
|---|---|---|
| 基础信息：昵称/头像/ID/地域/粉丝/MCN | 已有 | 保留 |
| 内容分类及标签 | 部分（原仅 starTagStr） | `content_type_labels` |
| 所属行业及行业标签 | 部分（原用空 industryTagStr） | `industry_labels` 从 industryTag |
| 认证信息 | 缺失 | `verified_info` |
| 按小时/天/商品报价 | 部分（金额有、类型/单位无） | `quote_details` + 旧 quote_* |
| 重点数据 6 项 | 5 项已有 | 新增 credit_score |
| 预期最高在线人数 | 缺失 | `expect_max_online` |
| 历史合作行业 | 缺失 | `cooperation_industries` |
| 观众性别/年龄/设备/价格/城市等级/地域摘要 | 缺失 | 3 个 viewer tag 字段 |
| 达人指数全部 | 缺失 | index 7 字段 |
| 代表作品/电商过滤/最近15场/频次 | 部分（report only） | works 4 字段 |
| 粉丝趋势 | 缺失 | fans_trend 6 字段 |
| 受众画像（观众/粉丝） | 缺失（端点未调用） | audience 2 结构化字段 |
| 带货 7/30/90 + 分析 | 部分（仅7天） | commerce 5 字段 |
| 合作 30/90 | 缺失（profile 未解析） | 6 字段 |
| 客户评价汇总/明细/分页 | 缺失（端点未调用） | cooperation 3 字段 |

## 11. 当前样本不可获取/不适用

| 字段/能力 | 样本结果 | 处理 |
|---|---|---|
| `starIndex/info` 视频指数 | 全 null | 不进入直播字段 |
| 设备类型 `mobilePercentage` | 两样本空 | 仅摘要 `SUMMARY_ONLY` |
| 九大人群 | 两样本空 | NO_DATA |
| 观众兴趣 | 空 | 仅粉丝兴趣 |
| 指数趋势 | 全 0 | COLLECTED + all_zero |
| 同粉段综合均值 | 平台无 | 5 维均值 + 说明 |
| 评价平台 ID | 无 | 组合哈希 |
| 作品稳定公开页 | 无 | 保存播放 URL，标注时效 |
| 合作 30/90（451066） | null/0 | NO_DATA |
| 带货（451066） | 空 | NO_DATA |
| 认证（451066） | 空 | NO_DATA |
| page 7+ | 未验证 | 沿用 LIVE-02 结论 |
