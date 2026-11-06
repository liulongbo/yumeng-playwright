# LIVE-03 字段差异与补全清单

日期：2026-11-05  
对照：附件 Element、`contracts/douyin_xingtu.live.verified.json`（v3）、真实页面/网络调查（[调查证据](LIVE-03-live-detail-investigation.md)）。  
状态口径：已有 / 本次新增 / 平台暂无数据 / 当前账号不可获取 / 未完成。

## 1. 基本资料

| 字段 | 附件要求 | 现状（LIVE-02） | 本次实现 | 验证方式 | 状态 |
|---|---|---|---|---|---|
| 达人名称 | 昵称 | `basic.nickname` 已有 | 复用 | 真实页面/API | 已有 |
| 头像 | 头像 | `basic.avatar_uri` 已有 | 复用 | 真实页面/API | 已有 |
| 性别 | 男/女 | `basic.gender` 已有；无性别页面为 NO_DATA | 复用 | 真实页面/API | 已有 |
| 所在地域 | 省市 | `basic.province/city` 已有 | 复用 | 真实页面/API | 已有 |
| 粉丝数 | 粉丝 | `basic.followers` 已有 | 复用 | 真实页面/API | 已有 |
| 内容类型 | 主类型 | `basic.content_type` 已有 | 复用 | 真实页面/API | 已有 |
| 内容标签 | 类型下标签 | 无 | `basic.content_tags`，来自 `live_labels_v2` 值 | 真实 API | 本次新增 |
| 商单类型 | 商单类型 | 无 | `basic.business_order_types`，来自 `live_order_labels` 键 | 真实 API | 本次新增 |
| 抖音号 | 抖音号 | 无 | `basic.douyin_id`，`unique_id`/`short_id` | 真实 API | 本次新增 |
| 星图 ID | 星图 ID | `platform_creator_id` / `platform_star_id` 已有 | 复用 | 真实页面/API | 已有 |
| 达人介绍 | 介绍 | 直播详情无；视频有 | `basic.introduction`，`channel_info.self_intro`，联系方式脱敏 | 真实 API | 本次新增 |
| 联系方式 | 不采集 | 未采集 | 明确排除 `author_get_business_card_info` | 代码/证据检查 | 不采集 |

## 2. 直播服务报价

| 字段 | 附件要求 | 现状 | 本次实现 | 状态 |
|---|---|---|---|---|
| 品牌营销专场（按天） | 金额、按天 | 无 | `pricing.services[]`，`pricing_mode=per_day`，`unit=元/天`，CNY | 本次新增 |
| 品牌营销专场（按小时） | 金额、按小时 | 无 | `per_hour`，`元/小时` | 本次新增 |
| 电商带货专场（按小时） | 金额、按小时 | 无 | `per_hour`，`元/小时` | 本次新增 |
| 电商带货拼场（按商品） | 金额、按商品 | 无 | `per_goods`，`元/商品` | 本次新增 |
| 平台其他报价属性 | 结算/原价/有效期等 | 无 | `platform{settlement_type, settlement_desc, video_type, task_category, enable, is_open, need_price, has_discount, start_time, end_time, activity_info}` | 本次新增 |
| 币种 | ￥ | 无 | `currency=CNY`（页面 ￥；响应无币种字段） | 本次新增 |
| 不同服务不混算 | 必须 | 无 | 每个服务独立对象；按天/小时/商品不覆盖 | 本次新增 |

## 3. 数据概览

### 3.1 数据解读

| 字段 | 现状 | 本次实现 | 状态 |
|---|---|---|---|
| 近 90 天累计开播场次 | 仅默认周期 room_cnt | `overview.{type}.calibres[period_90...].interpretation.room_cnt` | 本次新增 |
| ACU | 仅默认 | `interpretation.acu` | 本次新增 |
| 同粉段排名百分位 | 仅默认 | `interpretation.acu_precede_percent` | 本次新增 |
| 不同直播类型 | 无 | `overview.general/game/ecom/other` 独立字段 | 本次新增 |
| 统计周期 | 无 | calibre 内 `period=30/90` + `period_label` | 本次新增 |
| 排除营销流量 | 无 | calibre 内 `flow_type` + `excluded_marketing`；默认 flow=1 已采，替代 flow=0 未采（`not_captured` 披露） | 部分 |
| 只看星图商单 | 无 | calibre 内 `only_star_order` | 本次新增 |

### 3.2 直播间数据

| 字段 | 现状 | 本次实现 | 状态 |
|---|---|---|---|
| 近期直播场次 | `live.room_cnt`（默认口径） | `overview.*.groups.room.room_cnt`（分类型/周期/口径） | 本次新增（指标已有，维度新增） |
| 平均观看人数 | `live.watch_ucnt_avg` | `watch_ucnt_avg`，单位 count | 本次新增（维度） |
| 平均观看人次 | `live.watch_cnt_avg` | `watch_cnt_avg`，单位 count；与人数分开 | 本次新增（维度） |
| ACU | `live.acu` | `acu` | 本次新增（维度） |
| PCU | `live.pcu` | `pcu` | 本次新增（维度） |
| 粉丝观看占比 | `live.fans_watch_rate` | `fans_watch_rate`，ratio | 本次新增（维度） |
| 场均涨粉数 | `live.follow_ucnt_avg` | `follow_ucnt_avg` | 本次新增（维度） |
| 场均评论率 | `live.comment_rate_avg` | `comment_rate_avg`，ratio | 本次新增（维度） |
| 场均点赞率 | `live.like_rate_avg` | `like_rate_avg`，ratio | 本次新增（维度） |
| 平均看播时长 | `live.watch_duration_avg` | `watch_duration_avg`，second；异常单位标记 | 本次新增（维度） |
| 其他平台指标 | `interact_rate_avg` 已采未展示 | `interact_rate_avg`、`finish_order_cnt`、`in_process_order_cnt` | 本次新增（展示） |

### 3.3 带货表现

| 字段 | 现状 | 本次实现 | 状态 |
|---|---|---|---|
| 带货商品数 | `live.ecom_product_num` | `groups.ecom.ecom_live_product_num` | 本次新增（维度） |
| 场均 GMV | `live.ecom_avg_gmv_range`（仅文本） | `avg_gmv_range`：raw + min/max + bound + unit | 本次新增（结构化区间） |
| 带货商品客单价 | `live.ecom_avg_price_range` | `avg_ecom_product_price_range` 同上 | 本次新增（结构化区间） |
| GPM | `live.ecom_avg_gpm_range` | `avg_gpm_range`，raw + range，unit=gpm | 本次新增（结构化区间） |
| 区间不取平均 | 原值 | 区间对象保留上下界与原文本 | 本次新增 |

### 3.4 转化表现

| 字段 | 现状 | 本次实现 | 状态 |
|---|---|---|---|
| 场均 CTR | 未解析（`live_convert_statistics` 原始响应存在） | `groups.convert.ctr_avg` | 本次新增 |
| 小手柄场均 CTR | 未解析 | `handle_ctr_avg` | 本次新增 |
| 小雪花场均 CTR | 未解析 | `snowflake_ctr_avg` | 本次新增 |
| 小风车场均 CTR | 未解析 | `windmill_ctr_avg` | 本次新增 |
| 小手柄场均 CVR | 未解析 | `handle_cvr_avg` | 本次新增 |
| 非星图商单 | 页面文本 | `NOT_PROVIDED` + `non_star_order` 原因，不记 0 | 本次新增 |
| 非带货直播 | 页面文本 | GMV/ecom 字段 `NOT_PROVIDED` + 原因 | 本次新增 |

## 4. 直播分析

| 字段 | 现状 | 本次实现 | 状态 |
|---|---|---|---|
| 直播日期/开播时间 | 无 | `analysis.{type}.calendar.months[].days[].rooms[]`，ISO+08:00 | 本次新增 |
| 直播场次 | 无 | 月历日/rooms、`room_count` | 本次新增 |
| 对应直播类型 | 无 | `analysis.{type}.*` 字段 + 逐场 `live_type`（latest/detail 命中时） | 本次新增 |
| 平台分析指标 | 无 | 月历 room 对象与 latest/rooms 的指标 envelope | 本次新增 |
| 月度统计 | 无 | `room_count`、`highest_room`、`latest_room`、月份范围 | 本次新增 |
| 月份切换 | 无 | 当前月 + 当前月空时上月；`months_captured` | 本次新增 |
| 近15场观看人次/ACU/PCU | 无 | `analysis.{type}.latest.series.{watch_cnt,acu,pcu}` 原始点 | 本次新增 |
| 近15场场次/日期 | 无 | `points[]` + `window` | 本次新增 |
| 直播标题 | 无 | `rooms[].title` | 本次新增 |
| 开播时间/时长 | 无 | `start_time/end_time/duration_seconds` | 本次新增 |
| 观看人数/人次 | 无 | `rooms[].metrics.watch_ucnt/watch_cnt` | 本次新增 |
| ACU/PCU | 无 | `metrics.acu/pcu` | 本次新增 |
| 评论率/点赞率 | 无 | `metrics.comment_rate/like_rate` | 本次新增 |
| CTR/GMV | 无 | `metrics.ctr/gmv_range` + 原因 | 本次新增 |
| 其他场次信息 | 无 | `brand_info`、`acu_rank_rate`、排名、star/ad 标志、pagination | 本次新增 |
| 多场存储 | 无 | 近90天全量分页（最终时尚样本 96 场/10 页），不只首场 | 本次新增 |
| 非星图商单/非带货直播 | 无 | `status=NOT_PROVIDED` + `reason` 原文 | 本次新增 |
| 真实 0 / 无数据 / 失败 | 无 | `COLLECTED 0` / `NO_DATA` / `FAILED` 分离 | 本次新增 |

## 5. 受众画像

| 字段 | 现状 | 本次实现 | 状态 |
|---|---|---|---|
| 男性/女性占比 | 无 | `audience.*.*.distributions.gender`（count + computed ratio/percent） | 本次新增 |
| 年龄分布 | 无 | `distributions.age`（全年龄段） | 本次新增 |
| 全国省份分布 | 无 | `distributions.province`（34 省份） | 本次新增 |
| 地域 TOP10 省份/城市 | 无 | `province.top10` / `city.top10` | 本次新增 |
| 城市等级分布 | 无 | `distributions.city_level` | 本次新增 |
| 兴趣分布 | 无 | `distributions.interest`（40 类） | 本次新增 |
| 八大人群占比 | 无 | `distributions.eight_crowds`（8 类） | 本次新增 |
| 设备分布 | 无 | `distributions.device`（品牌分布） | 本次新增 |
| 不限/游戏/电商/其他 | 无 | `audience.{general,game,ecom,other}.*` 独立字段 | 本次新增 |
| 粉丝/观众画像 | 无 | `.fans` / `.user` 独立字段；`live_crowd_type=2/1`；粉丝画像按类型已验证；观众画像切换受持久 profile UI 限制，NO_DATA | 部分 |
| 完整分布 | 无 | 保存响应全部计数，不采集 hover 单点/Canvas | 本次新增 |

## 6. API / 前端 / 存储

| 项 | 现状 | 本次实现 | 状态 |
|---|---|---|---|
| 独立直播入库 | LIVE-02 快照 + `creator_live_current` | 新模块写入 live 快照；current 仅既有标量，不混合 | 复用/扩展 |
| 不同类型不覆盖 | 仅一个 `live` 模块 | 每个类型/周期/口径独立 calibre/字段 | 本次新增 |
| API 返回 | 详情 `profile_payload` 全量 | 新模块自动返回；`introduction` 投影；失败模块读时回退 | 本次新增 |
| 任务列表大小 | 全量 payload | live 列表只返回 basic/live；单达人详情完整 | 本次新增 |
| 前端展示 | 17 指标条 | 基本资料/报价/概览/分析/画像五模块，类型/周期/口径切换、图表、明细、空态 | 本次新增 |
| 手动更新 | 已有直播更新 | 新模块随更新采集；失败不清空旧数据 | 复用/验证 |
| 数据库迁移 | schema 21 | 无迁移 | 本次选择 |

## 7. 平台限制与未完成

| 项 | 说明 | 状态 |
|---|---|---|
| 逐场直播类型 | 列表接口不带 `live_type`；仅 latest/detail 同 room_id 命中时登记，其余 NOT_PROVIDED | 平台限制，已披露 |
| 游戏直播 | 时尚样本 candidates=false 且页签 disabled；不请求、不伪造 | 平台无数据 |
| 电商带货报价 | 时尚样本仅返回品牌营销两项；未返回的不补造 | 平台暂无数据 |
| 转化表现 | 仅星图商单口径返回；空组记原因 | 平台口径 |
| 投放表现 | `live_aa_statistics` 附件未要求，未采集 | 范围外 |
| 月历历史 | 仅当前月（空则上月），不无限回溯 | 本次范围 |
| 同达人四类型全量 | 仅 UI 可用类型；未开放类型记 NO_DATA | 按平台能力 |

## 8. 2026-11-06 增补：达人微信

单独增补 `basic.wechat`（`xingtu-live-square-v4`）：真实页面「联系」hover →「查看微信」→ `el-dialog[aria-label="达人微信"] .wechat`；仅读取文本、不点复制/不点联系授权确认。快照存储，任务列表不返回，登录后的单达人详情 API/前端基本资料展示；不写 `creator_live_current.live_metrics`，无迁移。详见 [LIVE-03-WECHAT 验收](LIVE-03-wechat-acceptance.md)。达人介绍仍执行联系方式脱敏，本字段为唯一显式例外。
