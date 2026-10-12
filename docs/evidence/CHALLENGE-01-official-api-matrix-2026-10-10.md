# CHALLENGE-01：巨量引擎／星图官方开放能力字段矩阵

> 复核日期：2026-10-10。结论基于公开官方资料；企业账号实际可申请权限尚未在认证控制台中核验。本文件不登记或推测私有接口。

## 官方公开能力结论

- 巨量引擎商业开放平台公开提供 OAuth2、Access Token、SDK、可视化调试及接口频控；官方能力地图中的星图公开能力主要指向账号信息、资金和任务后报等方向：<https://open.oceanengine.com/mui/doc/v2/1776463843653639>。
- 官方接口同时受客户、开发者和单接口频率控制：<https://open.oceanengine.com/labels/35/docs/1696710758159360>。
- 巨量星图平台协议入口：<https://www.xingtu.cn/help-center/facilitator/140780>。
- 未发现官方公开的自动完成滑块、人机验证码或 `verifycenter` 安全挑战接口。
- 未发现能够公开证明覆盖当前 F05 8 模块／81 字段及 F06 两组默认精选集合的等价接口。

因此本期官方路线的状态为 **待企业权限核验，不接入运行时**；安全验证采用平台原生人工动作 + 系统自动托管恢复。

## F05 字段对照

下表列出当前正式注册表的全部 81 个字段。当前来源以已验证网页响应/DOM 为准；公开官方接口栏统一为“未发现等价公开接口”，并不表示平台内部不存在能力，只表示不能在没有正式权限和文档的情况下接入。

| 模块 | 当前字段 | 当前已验证来源 | 公开官方接口 | 接入结论 |
|---|---|---|---|---|
| basic（20） | `platform_creator_id`, `nickname`, `avatar_uri`, `followers`, `gender`, `city`, `province`, `mcn_name`, `content_theme_labels`, `creator_type_raw`, `author_type_raw`, `industry_labels_raw`, `content_style_labels_raw`, `douyin_sec_uid`, `douyin_unique_id`, `introduction`, `monthly_deep_users`, `monthly_follower_growth_rate`, `creator_type_label`, `industry_labels` | 星图达人主页响应与登记 DOM | 未发现覆盖全部字段的等价公开接口 | 保留网页路径；企业权限核验后逐字段比对 |
| commercial（2） | `cooperation_offers`, `marketing_industry_tags` | 星图商业报价响应 | 未发现等价公开接口 | 不替换 |
| spread（18） | `play_median`, `interaction_rate`, `completion_rate`, `average_duration`, `average_likes`, `average_comments`, `average_shares`, `expected_cpm`, `expected_cpe`, `sales_expected_cpm`, `play_stability`, `item_rate_metrics`, `commercial_play_count`, `commercial_natural_play_count`, `commercial_cpm_20_60`, `commercial_cpm_60`, `commercial_cpe_20_60`, `commercial_cpe_60` | 星图传播表现响应 | 未发现等价公开接口 | 不替换 |
| seeding（7） | `a3_increment`, `search_after_view`, `search_after_view_rate`, `personal_search_after_view`, `personal_search_after_view_rate`, `search_word_ctr`, `seeding_link_structure` | 星图种草表现响应 | 未发现等价公开接口 | 不替换 |
| fulfillment（9） | `credit_score`, `new_credit_score`, `historical_order_count`, `processing_order_count`, `max_processing_order_count`, `message_reply_rate`, `industry_order_distribution`, `industry_play_distribution`, `cooperation_industry_distribution` | 星图履约响应 | 未发现等价公开接口 | 不替换 |
| conversion（10） | `gpm_range`, `sales_amount_range`, `component_click_count_range`, `component_click_rate_range`, `related_cpc_range`, `recommended_product_count`, `product_price_range`, `related_video_count`, `related_video_play_median`, `local_sales_overview` | 星图转化响应 | 未发现等价公开接口 | 不替换 |
| fans（9） | `monthly_connected_users`, `fans_daily_trend`, `fans_daily_delta`, `fans_growth`, `fans_growth_rate`, `connection_funnel`, `connection_daily_trend`, `audience_distributions`, `audience_last_updated_at` | 星图粉丝画像响应 | 未发现等价公开接口 | 不替换 |
| creation（6） | `video_content_distribution`, `hot_comment_tokens`, `content_theme_density`, `recent_video_performance`, `recent_xingtu_video_performance`, `performance_descriptions` | 星图创作能力响应 | 未发现等价公开接口 | 不替换 |

## F06 两组精选集合对照

`excellent_reach` 与 `excellent_seeding` 均采集 `platform_content_id`, `local_key`, `link`, `title`, `subtitle`, `play`, `like`, `comment`, `cover`，并要求默认集合边界、组内顺序、完整加载证据及受控封面存储。公开资料未发现同时满足这些语义的等价官方接口，因此当前不替换。

## 企业权限核验清单

后续只有同时取得以下证据，某个字段或模块才可进入 API/UI 并行试点：正式接口名称与版本、应用/账号权限、OAuth scope、请求和响应字段定义、统计周期、数据时效、历史范围、分页语义、客户/开发者/接口频控、错误码、费用或认证要求、字段单位与缺失语义、至少正常/空态/无权限三类真实样本、与同一账号同一时点网页结果的等价性报告。

未满足任一项时状态保持 `UNVERIFIED`，不得以 API 名称相似或响应中出现近似字段为由替代现有数据。
