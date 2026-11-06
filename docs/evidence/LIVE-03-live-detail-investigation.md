# LIVE-03 巨量星图直播达人详情字段调查

调查日期：2026-11-05（Asia/Shanghai）  
环境：本机开发栈；执行单元 `unit-local-mac-02`；Playwright MCP + 系统 Chrome（隔离会话快照）。  
样本达人：`7620474284346966052`（倩倩美丽课堂，时尚，21w 粉，31/96 场）、`7632889314933735475`（附件达人，游戏/教育，3.3w 粉）。  
原始响应仅保存在 `.runtime/live03/`（gitignored、私有）；本文只记录脱敏后的端点、参数、字段路径与结论。

## 1. 页面与入口

| 项 | 实测 |
|---|---|
| 详情 URL | `https://www.xingtu.cn/ad/creator/author/douyin/{star_id}/10` |
| 页面标题 | `{昵称} - 抖音达人主页 - 巨量星图`；页面内标题「抖音直播主页」 |
| 顶部页签 | 数据概览 / 直播分析 / 受众画像（`.el-tabs__item.is-top`） |
| 直播类型 | 不限 / 游戏直播 / 电商带货 / 其它直播（`.el-radio-button`；不可用类型带 `is-disabled`） |
| 时间 | 下拉「近30天 / 近90天」（placeholder「请选择时间周期」） |
| 排除营销流量 | `.module-card.data-overview .xt-switch`；checked 时请求 `flow_type=1`，未选时 `flow_type=0` |
| 只看星图商单 | `.el-checkbox`；勾选后 `only_star_order=true` |
| 画像类型 | 下拉「粉丝画像 / 观众画像」；请求 `live_crowd_type=2 / 1` |
| 默认状态（本次单元 profile 实测） | 不限、近90天、排除营销流量=开（`flow_type=1`）、只看星图商单=未选；30 天由时间下拉补采 |

> 默认时间可能被浏览器 profile 记住；采集实现不能假定 30 天，必须读取实际请求并在 UI 可切换时同时采集 30/90。

## 2. 真实端点与参数

| 用途 | 方法与路径 | 已核实参数 |
|---|---|---|
| 直播类型可用性 | `GET /gw/api/aggregator/get_author_live_statistics_candidates` | `o_author_id, is_aa` |
| 数据概览 | `GET /gw/api/aggregator/get_author_live_statistics` | `o_author_id, live_type, period, only_star_order, is_aa, flow_type` |
| 直播月历 | `GET /gw/api/aggregator/get_author_peroidic_live_analysis`（平台拼写） | `o_author_id, year, month, live_type, only_star_order, is_aa, flow_type` |
| 近15场 | `GET /gw/api/aggregator/get_author_latest_live_analysis` | `o_author_id, live_room_num=15, live_type, only_star_order, is_aa, flow_type` |
| 直播间列表 | `POST /gw/api/gsearch/search_for_live_room_list` | body: `order_by=live_room_start_time, sort_type=2, page, limit=10, attribute_filter{author_id,...}` |
| 多场指标 | `GET /gw/api/aggregator/multi_get_room_data` | `room_ids`（逗号分隔）、`only_star_order, flow_type` |
| 受众画像 | `GET /gw/api/aggregator/get_author_live_watch_distribution` | `o_author_id, live_type, live_crowd_type` |
| 基础资料 | `GET /gw/api/author/get_author_base_info` | `o_author_id, platform_source, platform_channel, ...` |
| 直播报价 | `GET /gw/api/author/get_author_marketing_info` | `o_author_id, platform_source, platform_channel` |
| 介绍 | `GET /gw/api/author/get_author_platform_channel_info_v2` | `o_author_id, platform_source, platform_channel` |

未登记/不采集：`author_get_business_card_info`（包含 phone/email/wechat，明确排除）。

## 3. 枚举与口径映射

| 维度 | 平台值 | 语义 |
|---|---|---|
| `live_type` | 1 / 2 / 3 / 4 | 不限 / 游戏直播 / 电商带货 / 其它直播 |
| `period` | 30 / 90 | 近30天 / 近90天 |
| `flow_type` | 1 / 0 | 排除营销流量=开 / 关 |
| `only_star_order` | true / false | 只看星图商单 / 全部商单 |
| `live_crowd_type` | 2 / 1 | 粉丝画像 / 观众画像 |

- 游戏直播在当前时尚样本中 `candidates_30d/90d.game=false` 且页签 disabled；不请求、不伪造。
- 候选键同时包含 `ecom_star/general_star/other_star`，用于判断是否产生星图商单口径；不代表页面一定发起单独请求。
- 同一达人不同口径的数值确实不同（样本：不限 30 天 room_cnt=30、ACU=270；90 天 room_cnt=96、ACU=539；只看星图商单 90 天 room_cnt=86、ACU=543），必须分字段存储。

## 4. 响应结构（脱敏）

### 4.1 数据概览 `get_author_live_statistics`
```
base_resp.status_code
live_room_statistics: room_cnt, watch_ucnt_avg, watch_cnt_avg, acu, pcu,
  fans_watch_rate, follow_ucnt_avg, comment_rate_avg, like_rate_avg,
  watch_duration_avg, acu_precede_percent, interact_rate_avg,
  finish_order_cnt, in_process_order_cnt
live_ecom_statistics: ecom_live_product_num, avg_gmv_range,
  avg_ecom_product_price_range, avg_gpm_range
live_convert_statistics: ctr_avg, handle_ctr_avg, snowflake_ctr_avg,
  windmill_ctr_avg, handle_cvr_avg（实际返回的键子集）
live_aa_statistics: 样本为空；本轮不采集
```
- `watch_duration_avg` 常规为秒（与页面「1分35秒」一致）；大于 86400 的异常组合保留 raw 并标记 `unit_confidence=ambiguous`，不强行换算。
- 区间字符串如 `2w~20w`、`500~1,000` 原样保留，同时解析 min/max，不取平均。
- `live_convert_statistics` 为空时，页面显示 `-` 或「仅对星图商单生效」；本系统记 `NOT_PROVIDED`，不是 0。

### 4.2 月历 `get_author_peroidic_live_analysis`
```
base_resp.status_code
live_rooms[]: room_id, title, start_time, end_time, acu, pcu, watch_ucnt,
  watch_cnt, comment_rate, like_rate, fans_watch_rate, follow_ucnt,
  watch_duration_avg, acu_rank_rate, is_star_order, is_star_ad_order,
  ecom_live_product_num, avg_ecom_product_price_range, gmv_range, ...
highest_live_room, latest_live_room（同结构）
```
- 当前月无场次时 `live_rooms=[]`；点击「上个月」可取得上月数据。采集只回溯一个月。

### 4.3 近15场 `get_author_latest_live_analysis`
```
latest_live_rooms[]（最多 15；含 watch_cnt/acu/pcu 等原始点）
highest_live_room, latest_live_room
```
- 图表使用该数组的原始值；不读取 Canvas 像素。

### 4.4 直播间列表
- `search_for_live_room_list` 返回 `item_ids[]` + `pagination{page, limit=10, total_count, has_more}`；`item_ids` 不含指标。
- `multi_get_room_data` 返回 `items[]`，字段与 4.2 的 room 相同；列表接口不带 `live_type`，因此逐场类型只有在 latest/detail 里同 `room_id` 命中时才能登记。
- 样本 `total_count=96`，10 页（第 10 页 6 条），0 重复；页面分页器可翻到第 10 页。
- 列表 DOM 对缺失值直接显示「非星图商单，不做统计」「非带货直播，不做统计」；响应侧可据 `is_star_order` / 是否返回 ecom 字段判定，保留平台原文。

### 4.5 受众画像 `get_author_live_watch_distribution`
```
distributions[]: {
  type, type_display, description, image,
  distribution_list[]: {distribution_key, distribution_value}
}
```
- 实测 `type_display`：性别分布、年龄分布、省份分布、城市分布、城市等级分布、兴趣分布、八大人群分布、设备品牌分布。
- `distribution_value` 是计数（如性别 9588/39372，合计 48960），页面显示占比；本系统同时保存计数并按分布合计计算占比，标注计算规则。
- 省份 34 类、城市 50 类、兴趣 40 类；前端按 TOP10/完整分布展示。
- 观众画像 `live_crowd_type=1` 与粉丝画像 `2` 的计数不同，必须分开存储。

### 4.6 基础资料与报价
- `get_author_base_info`：`nick_name, avatar_uri, follower, gender, city, province, mcn_name, short_id, unique_id, live_labels_v2{内容类型: [标签]}, live_order_labels{商单类型: []}`。
- `get_author_platform_channel_info_v2.self_intro`：介绍；联系方式需脱敏，空值记 NO_DATA。
- `get_author_marketing_info.price_info[]`：`desc, price, origin_price, video_type, task_category, settlement_type, settlement_desc, has_discount, enable, is_open, need_price, start_time, end_time, activity_info`。
  - 样本 `task_category=6` 为直播服务；`desc` 含「按天/按小时/按商品」。
  - 时尚样本仅返回 2 项（品牌营销专场按天/按小时）；附件样本返回 4 项。没有返回的服务不补造。

## 5. 结论与限制

1. 附件五个业务模块均可从真实页面/网络获得；无需直连 API、无需 Canvas OCR。
2. 类型/周期/口径/画像类型均有真实请求参数；同一指标不同维度数值不同，必须隔离存储。
3. 直播间列表为平台近 90 天全量分页，接口不带直播类型；逐场类型仅在 latest/detail 命中时登记，其余标记 NOT_PROVIDED 并保留原因。
4. 月历只采集当前月（空则上月），不做无限历史回溯。
5. 报价按平台实际返回服务采集，不要求每个达人都有四项。
6. 无效/无直播达人：页面无直播页签或显示「没有开播」，相关模块记 NO_DATA；不得伪造 0。
7. `watch_duration_avg` 存在个别口径异常值（>86400），保留 raw 并标记单位待确认，不强行归一。

## 6. 证据

- 初始页面/网络：`.runtime/live03/inspect-7620474284346966052/`、`inspect2-*`、`inspect3-*`、`inspect4-*`
- 受众下拉验证：`.runtime/live03/probe5/`
- 真实手动更新（适配器联调）：任务 `47143c60-c54e-4a56-b260-c8436b24b2af`（首轮完整模块）、`a57c401c-28e5-4912-b6c8-d7132a54d800`（30/90 双周期修复后）
- 原始响应含平台业务数据，仅保存在 `.runtime`，不复制个人信息或凭据到本文。
