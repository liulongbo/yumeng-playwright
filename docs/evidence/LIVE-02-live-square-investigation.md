# LIVE-02 双平台「直播广场」真实页面调查证据

日期：2026-11-04（Asia/Shanghai）  
分支：`1104-llb`，起点 `origin/main@2ee5d1f`（上一轮交付提交 `d34a3b4`）  
环境：macOS 本机；前端 `5173`、API `8000`、PostgreSQL `55432`（schema 20）、Redis `56379`、Temporal `57233`；真实平台：巨量星图 + 磁力聚星  
工具：项目 `scripts/qa/mcp_client.py`（stdio JSON-RPC）驱动 `@playwright/mcp` + 系统 Chrome；只读 PostgreSQL  
关联：[LIVE-02 任务卡](../tasks/LIVE-02.md)、[PRD](../prd/LIVE-02-live-square-collection.md)、[技术方案](../design/LIVE-02-live-square-technical-design.md)

## 1. 目的、边界与工具

本调查只用于阶段一事实收集：

- 只读访问平台；每平台执行 1 次宽泛关键词检索、1 次按已知达人 ID 检索、1 次翻页、1 个达人详情。
- 不创建本系统采集任务，不点击下单/加入清单/联系/导出等写操作。
- 不绕过登录、验证码或风控；不记录 Cookie、令牌、请求头或完整响应正文。
- 原始响应正文只保存在 `.runtime/live02/`（`.gitignore`、0600）；本文只记录路径、键名、单位、统计口径和少量已公开的业务数值。
- 会话来源：`unit-local-mac-02` 星图快照（captured_at `2026-11-04T11:38:05Z`）与 `unit-local-mac-03-juxing` 聚星快照（captured_at `2026-11-03T12:39:59Z`），提取为隔离浏览器 `storage_state`；**未打开执行单元 Profile 目录**，避免与 Worker 争用。
- 浏览器实际工具名：`browser_navigate / browser_snapshot / browser_click / browser_type / browser_evaluate / browser_take_screenshot / browser_network_requests / browser_network_request`（MCP stdio）。

## 2. 预检基线

| 项 | 实测 |
|---|---|
| 数据库 | schema 20；根任务 149 条全部终态；无在途任务 |
| 执行单元 | `unit-local-mac-02`（星图）、`unit-local-mac-03-juxing`（聚星），均 `READY`、无 owner/lease、`browser_stopped=true` |
| 定时更新 | `update-scheduler` 未运行 |
| 达人库 | 星图 201、聚星 80 位既有达人 |
| 平台开关 | `XINGTU_ENABLE_KUAISHOU_JUXING=1`；两平台 verified 契约可执行 |
| 登录态 | 星图 47 cookies / 2 origins；聚星 24 cookies / 3 origins（只记录数量，不输出值） |

## 3. 巨量星图

### 3.1 入口与页面

| 项 | 实测 |
|---|---|
| 顶部菜单 | `找达人` → `DIV.navigator-menu-item.el-popover__reference`；hover 后出现子菜单 |
| 直播广场链接 | 真实 DOM `<a href="/ad/creator/market/live">直播广场</a>` |
| 短视频广场链接 | `/ad/creator/market`（保持并存） |
| 最终 URL | `https://www.xingtu.cn/ad/creator/market/live` |
| 页面标题 | `直播广场 - 巨量星图` |
| 账号 | 页面显示 `予梦 ID: 1807978499337419`，与执行单元期望账号一致 |
| 默认状态 | 已选条件「达人报价：品牌营销专场(按小时)」；找到 10000+ 个达人；每页 20 位 |

说明：用户提供的两张截图存在平台标签与实际布局交叉——真实星图直播广场与截图的「商业能力/匹配度/性价比」筛选和「代表直播/近期直播场次/ACU/PCU」列一致；真实聚星直播达人广场与另一张截图的「内容分类/所属行业/星标推荐」筛选和「粉丝数/预期观看人数/最高在线人数/预期CPM」列一致。本报告以真实页面为准，不对截图标签做推断。

### 3.2 筛选能力（标签与控件已确认，请求映射多数待验证）

| 分组 | 字段（真实页面） | 状态 |
|---|---|---|
| 直播内容 | 昵称/抖音号/星图ID（文本）；直播间内容=抖音 | 页面已确认；ID 检索已验证 |
| 商业能力 | 营销目标：不限/游戏下载/应用与线索/电商带货 | 页面已确认；映射待验证 |
| 匹配度 | 内容类型、商单类型、达人性别、所在地域、粉丝量级、个人认证、受众画像、直播间观众画像、粉丝画像 | 页面已确认；映射待验证 |
| 性价比·合作信息 | 达人报价·1（默认品牌营销专场按小时）、进行中的直播任务数、近期合作直播任务数 | 默认条件已验证；其余待验证 |
| 性价比·带货表现 | 带货商品数、平均销售额、带货商品价格、GPM、带货等级、近30天最多带货品类、带货品类 | 页面已确认；映射待验证 |
| 性价比·直播间表现 | 近期直播场次、平均观看人数、平均观看人次、ACU、PCU、粉丝观看占比、场均涨粉数、场均评论率、场均点赞率、平均看播时长 | 页面已确认；详情字段已验证 |
| 性价比·转化表现 | 场均CTR、小手柄场均CTR、小雪花场均CTR、小风车场均CTR、小手柄场均CVR | 页面已确认；样本为空 |
| 推荐清单 | 达人清单 | 页面已确认 |

### 3.3 列表请求契约（真实捕获）

- 方法/路径：`POST https://www.xingtu.cn/gw/api/gsearch/search_for_author_square`
- 请求体：

```json
{
  "scene_param": {"platform_source": 1, "search_scene": 2, "display_scene": 5, "marketing_target": 3, "task_category": 6},
  "search_param": {"keyword": "美食", "seach_type": 2},
  "sort_param": {"sort_type": 2, "sort_field": {"field_name": "score"}},
  "page_param": {"page": 1, "limit": 20},
  "attribute_filter": [{"field": {"field_name": "price_by_video_type__ge", "rel_id": "9"}, "field_value": "0"}]
}
```

- 响应顶层：`authors[]`、`base_resp`、`extra_data`、`pagination`
- 身份：`authors[].star_id`（字符串）
- 分页：`pagination.page / limit / total_count / has_more`
- 默认条件：`attribute_filter[0]` 对应「达人报价：品牌营销专场(按小时)」。
- 列表列：达人信息、代表直播、近期直播场次、平均观看人次、ACU、PCU、场均评论率、场均点赞率、报价、操作。

**列表字段（已验证路径）：**

| 页面字段 | 响应路径 | 样本值/单位 | 口径/备注 |
|---|---|---|---|
| 粉丝数 | `attribute_datas.follower` | 1605365（160.5w） | 平台展示为万 |
| 近期直播场次 | `attribute_datas.live_room_cnt_30d` | 21 | 近 30 天 |
| 平均观看人数 | `attribute_datas.live_watch_ucnt_avg_30d` | 50526（5w） | 与详情「不限」口径接近但不完全相等 |
| 平均观看人次 | `attribute_datas.live_watch_cnt_avg_30d` | 63459（6.3w） | 与详情口径分次观测 |
| ACU | `attribute_datas.acu` | 407 | 字符串数字 |
| PCU | `attribute_datas.live_pcu_30d` | 1153 | 字符串数字 |
| 粉丝观看占比 | `attribute_datas.live_sn_fans_watch_rate_30d` | 0.1398（13.98%） | **`live_sn_*` 为星图商单口径**，与详情「不限直播类型」34.9% 不同，不可混用 |
| 场均涨粉数 | `attribute_datas.live_sn_follow_ucnt_avg_30d` | 353 | 星图商单口径 |
| 场均评论率 | `attribute_datas.live_comment_rate_avg_30d` | 0.0086（0.86%） | 比率 0-1 |
| 场均点赞率 | `attribute_datas.live_like_rate_avg_30d` | 0.0021（0.21%） | 比率 0-1 |
| 平均看播时长 | `attribute_datas.live_avg_watch_duration_30d` | 40 | 秒 |
| 场均互动率 | `attribute_datas.live_interact_rate_avg_30d` | 0.1144（11.44%） | 页面列表未直接展示 |
| 带货商品数 | `attribute_datas.ecom_live_product_num_30d` | 23 | 近 30 天 |
| 平均销售额 | `attribute_datas.ecom_amt_avg_30d` | 4342937 | 平台原始值，不能直接当区间 |
| GPM 区间 | `attribute_datas.ecom_gpm_30days_range` | `150以上` | 平台原始字符串 |
| 带货客单价 | `attribute_datas.ecom_main_price_30days_range` | `50以下` | 平台原始字符串 |
| 带货等级/评分 | `attribute_datas.ecom_score` | 86 | 平台原始值 |
| 直播订单数 | `attribute_datas.star_live_order_cnt` | 1 | 星图直播订单 |
| 完成订单数 | `attribute_datas.order_complete_cnt` | 1 | 完成口径待核验 |
| 报价 | `task_infos[].price_infos[]` | `price=620/3100` 等 | 单位分/千分之一元；`task_category/video_type` 对应场次类型 |
| 代表直播 | `authors[].items[]` | 样本为空数组 | 需在阶段二验证非空样本 |

### 3.4 翻页（真实验证）

- 页面底部为 Element Plus 分页（`el-pager` + 跳转）。
- 真实 UI 点击第 2 页后：
  - `pagination.page=2`、`has_more=true`、`total_count=977`
  - 第 1 页 20 个 `star_id`、第 2 页 20 个 `star_id`，**跨页 0 重复**
- 证据：`.runtime/live02/xingtu-page2-ui/results.json`（私有原始件）。

### 3.5 达人详情

| 项 | 实测 |
|---|---|
| 点击方式 | 列表达人名（generic，cursor=pointer）→ 新标签页 |
| URL | `https://www.xingtu.cn/ad/creator/author/douyin/{star_id}/{video_type}`（新标签页，`current_tab=2` 等查询参数） |
| 标题 | `颜美食 - 抖音达人主页 - 巨量星图`；页面标题「抖音直播主页」 |
| 身份 | 页面显示「星图ID 6769089207643144205」，与列表 `star_id` 一致 |
| 标签页 | 数据概览、直播分析、受众画像 |
| 默认口径 | 直播类型=不限；只看星图商单=未勾选；时间=近30天；排除营销流量=关 |

**详情已验证字段：**

| 模块 | 页面字段 | 样本值 | 来源/备注 |
|---|---|---|---|
| 基础 | 昵称/性别/地域/粉丝数/内容类型/商单类型/抖音号/星图ID | 颜美食 / 女 / 暂无地域信息 / 160.5w / 其他 / 暂无标签 | 详情页 DOM；介绍含联系方式，**不采集** |
| 报价 | 品牌营销专场(按小时) | ¥1,000 | `priceShowInfo`/`task_infos`；单位换算待契约化 |
| 报价 | 电商带货专场(按小时) | ¥3,100 | 同上 |
| 报价 | 电商带货拼场(按商品) | ¥620 | 同上 |
| 数据概览 | 近30天累计开播 | 21 场 | `live_room_statistics.room_cnt` |
| 数据概览 | ACU / 同粉段排名 | 407 / 前 13.5% | `acu` / `acu_precede_percent=0.1352` |
| 直播间数据 | 近期直播场次 | 21 | `room_cnt` |
| 直播间数据 | 平均观看人数 | 5w | `watch_ucnt_avg=49778` |
| 直播间数据 | 平均观看人次 | 6.3w | `watch_cnt_avg=62579` |
| 直播间数据 | ACU / PCU | 407 / 1,153 | `acu` / `pcu` |
| 直播间数据 | 粉丝观看占比 | 34.9% | `fans_watch_rate=0.3486`（不限直播类型） |
| 直播间数据 | 场均涨粉数 | 335 | `follow_ucnt_avg` |
| 直播间数据 | 场均评论率 / 点赞率 | 0.9% / 0.2% | `comment_rate_avg=0.0086` / `like_rate_avg=0.0021` |
| 直播间数据 | 平均看播时长 | 0分40秒 | `watch_duration_avg=40`（秒） |
| 直播间数据 | 场均互动率 | 页面未列 | `interact_rate_avg=0.1144` |
| 带货表现 | 带货商品数 / 场均GMV / 客单价 / GPM | 23 / 2w~20w / 10~30 / 400~1,000 | `live_ecom_statistics` 原始区间字符串 |
| 转化表现 | 场均CTR / 小手柄 / 小雪花 / 小风车 / CVR | 均为 `-` | `live_convert_statistics={}` → **NO_DATA，不是 0** |
| 受众画像 | 直播间/观众画像 | 未展开核验 | 标签页存在；字段待验证 |

**详情接口（真实捕获）：**

| 接口 | 方法/路径 | 观察到的响应键 |
|---|---|---|
| 直播统计 | `GET /gw/api/aggregator/get_author_live_statistics` | `live_room_statistics.{room_cnt,watch_ucnt_avg,watch_cnt_avg,acu,pcu,fans_watch_rate,follow_ucnt_avg,comment_rate_avg,like_rate_avg,watch_duration_avg,interact_rate_avg,acu_precede_percent}`、`live_ecom_statistics.*`、`live_convert_statistics`、`live_aa_statistics` |
| 直播统计候选 | `GET /gw/api/aggregator/get_author_live_statistics_candidates` | `candidates_30d/90d.{ecom,game,general,other,...}` |
| 身份/主页 | `GET /gw/api/author/get_author_platform_channel_info_v2` | `club_follower`、`self_intro` |
| 名片 | `GET /gw/api/gauthor/author_get_business_card_info` | 含 `email/phone/wechat` → **明确不采集** |
| 库存 | `GET /gw/api/gdemander/get_author_stock_info` | `in_aa_stock` |
| 榜单 | `GET /gw/api/gsearch/get_authors_ranking_in` | 排名类字段 |

### 3.6 身份交叉核对

- 既有短视频达人 `6769198961371643915`（星图 ID）在直播广场按该 ID 检索，返回 **1 条**，`star_id` 仍为 `6769198961371643915`，`pagination.total_count=1`。
- 结论：同一平台内，短视频与直播使用同一 `star_id` 身份，可共享 `platform_creators` 身份而不重复建人。
- 证据：`.runtime/live02/xingtu-overlap/ids.json`。

### 3.7 状态

| 调查项 | 状态 | 说明 |
|---|---|---|
| 入口/菜单/URL | PASS | 真实 DOM anchor + 页面加载 |
| 会话/账号 | PASS | 页面显示期望账号；无登录墙 |
| 筛选标签/控件 | PASS（标签） | 请求映射多数 NOT_VERIFIED |
| 列表字段/请求契约 | PASS | 请求体与响应路径真实捕获 |
| 翻页 | PASS（第 2 页） | 20 条、0 重复；page 3+ 未验证 |
| 详情/字段 | PASS（数据概览） | 直播分析/受众画像标签页待验证 |
| 身份交叉 | PASS | 同 star_id |
| 直播筛选完整开发 | NOT_VERIFIED | 阶段一只调查，不实现 |

## 4. 磁力聚星

### 4.1 入口与页面

| 项 | 实测 |
|---|---|
| 进入前置 | 会话快照首次落在「选择账户」；必须点击 `cpg果汁 ID:60821564` 行的 `进入` 链接（`javascript:;`），未修改账号或凭据 |
| 顶部菜单 | `找达人`（menuitem，动态 class）→ `直播广场`（menuitem） |
| 最终 hash | `#/star_plaza/live`；父级 query `__accountId__=60821564` |
| 页面标题 | `找达人-磁力聚星`；内容标题「直播达人广场」 |
| 默认状态 | 无已选条件条；为您推荐 1000+ 位达人；每页 20 位 |

### 4.2 筛选能力（标签已确认，映射待验证）

| 分组 | 字段（真实页面） | 状态 |
|---|---|---|
| 内容分类 | 不限 + 美妆/游戏/颜值达人/美食/短剧/时尚/母婴亲子/…/自拍 + 更多 | 页面已确认 |
| 所属行业 | 不限 + 传媒资讯/工具类软件/…/旅游 + 更多 | 页面已确认 |
| 星标推荐 | 不限/近30日粉丝数上升/涨粉黑马/支持对公/机构达人/小麦优质达人/支持CPS带货/星选达人/榜上有名/领域先锋/经验丰富/有商单经验/历史合作过/新芽优质达人/30天内有视频商单经验/90天内有视频商单经验/视频限时价/直播限时价/更多 | 页面已确认 |
| 达人信息 | 粉丝数量、达人报价、达人性别、达人地域、达人指数 | 页面已确认 |
| 受众人群 | 粉丝画像、观众画像 | 页面已确认 |
| 内容表现 | 预期观看人数、最高在线人数、预期CPM、限时折扣 | 页面已确认；列表值已验证 |
| 推荐清单 | 达人清单 + 4 个推荐集合 | 页面已确认 |

### 4.3 列表请求契约（真实捕获）

- 方法/路径：`POST https://k.kuaishou.com/rest/web/star/list`
- 默认请求体：

```json
{"currentPage":1,"pageSize":20,"starOrderTag":3,"starOrderType":0,"taskType":4,
 "viewerCityPercentage":[],"fansCityPercentage":[],"starTagIds":[],
 "pickList":[],"advertiserPickList":[],"pathSource":"no_filter_live"}
```

- 按快手 ID 检索时：`userName="841292065"`，`pathSource="search_live"`。
- 响应：`result`、`total`、`currentPage`、`starList[]`；身份 `starList[].userId`；详情键 `starList[].starId`。
- 列表列：达人信息、粉丝数、预期观看人数、最高在线人数、预期CPM、粉丝增长量、粉丝增长率、报价、操作。

**列表字段（已验证路径）：**

| 页面字段 | 响应路径 | 样本值/单位 |
|---|---|---|
| 粉丝数 | `starList[].fansNumber` | 17104132（1710万） |
| 预期观看人数 | `starList[].liveExpectViewer` | 3352173（335万） |
| 最高在线人数 | `starList[].liveMaxViewer` | 410697（41万） |
| 预期CPM | `starList[].liveExpectCpm` | 18 |
| 直播互动率 | `starList[].liveInteractionRate` | 2.4677（2.47%） |
| 直播报价 | `liveQuotedPrice` / `priceShowInfo[]` | 60000000（÷1000=¥60,000） |
| 报价类型 | `priceShowInfo[].priceTypeName` | 直播按小时/直播按天/直播按商品数 |
| 带货/视频字段 | `photoExpectPlay`、`photoExpectCpm`、`photoInteractionRate` 等 | **视频口径，不得当直播指标** |
| 粉丝增长量/增长率 | `fansIncreaseNum` / `fansIncreaseRate` | 页面列展示 |
| 账号/直播状态 | `liveStatus` / `liveActive` | 1/1 |
| 身份 | `userId` | 1633604095 |
| 详情键 | `starId` | 451066 |

### 4.4 翻页（真实验证）

- 页面底部为 ant-pagination：`1 2 3 4 5 … 250`。
- 真实 UI 点击第 2 页：
  - `currentPage=1`（第 1 页）→ `currentPage=2`（第 2 页）
  - 每页 20 条；跨页 0 重复；`total=5000`
- 请求体对比：`currentPage` 1→2，`taskType=4`、`pathSource="no_filter_live"` 不变。
- 证据：`.runtime/live02/juxing-page2-ui/results.json`。

### 4.5 达人详情

| 项 | 实测 |
|---|---|
| 点击方式 | 列表达人名 → 新标签页 |
| URL | `#/live-promotion/star/{starId}?openBy=user`（父级 query 带 `pathSource=no_filter_live&__accountId__=60821564`） |
| 标题 | `达人主页-磁力聚星`；内容标题「达人直播主页」 |
| 身份 | 页面显示 `ID: 1633604095`（userId）；路径 `starId=451066` |
| 标签页 | 数据概览、达人指数、代表作品、受众分析、带货数据、合作情况 |
| 默认口径 | 数据概览时间范围：2026-10-05 ~ 2026-11-03（近30天） |

**详情已验证字段：**

| 模块 | 页面字段 | 样本值 | 来源/备注 |
|---|---|---|---|
| 基础 | 昵称/地域/达人类型/内容形式/粉丝数/所属行业/所属机构 | 桐桐就酱 / 湖南-常德 / 颜值达人 / vlog / 1710万 / 房产家居… / 嘉火娱乐 | 详情页 DOM |
| 报价 | 按小时/1小时、按天/1天、按商品/1个商品(拼场直播) | ¥60,000 / ¥60,000 / ¥60,000 | `starProfile.priceShowInfo`（businessLine=2）；price 除以 1000 |
| 重点数据 | 粉丝数 | 1710万 | `starProfile.fansNumber` |
| 重点数据 | 预期观看人数 | 335万 | `starProfile.livePlayCntExpectancy` |
| 重点数据 | 最高在线人数 | 41万 | `starProfile.livePcuCnt` / `starWorkReport.liveMaxViewer` |
| 重点数据 | 预期CPM | 18 | `starProfile.liveCpmExpectancy` |
| 重点数据 | 周均直播场次 | 8 | `starProfile.liveWeeklyTimesCnt` |
| 重点数据 | 近30天信用分 | `-` | `evaluation/star/score` 有 5.0 分，但页面未显示；**不强行映射** |
| 商业数据 | 预期最高在线人数 | 161720 | 页面标签与数值语义待核验 |
| 观众画像 | 性别/年龄/设备/设备价格/城市等级/地域 | 女性86%、18-23岁45.1%、安卓61.8%、1000-2000元37.2%、三线28.7%、广东/河南/河北 | `listPortrait.viewerPortrait.*`，比例 0-1 |
| 达人指数 | 综合指数/同行业排名/同粉丝段排名 | 85.25 / 13776 / 6387 | `starIndex/*`；部分子模型为 null |
| 带货数据 | 带货直播场次/观看人数中位数/最高在线中位数/商品数 | 全部 `-` | `commerce/live` 样本 `liveCnt=0,goodsCnt=0` → **无数据，不是真实 0** |
| 合作情况 | 接单率/完单率/订单完成数/客户评价 | 全部 `-` | `evaluation/star/*`；不得用空值补造 |
| 代表作品 | 个人作品/聚星作品/直播频次分布/粉丝趋势 | 可见 | `starWorksInfo.recentWorks/personLiveWorks/recentLiveWorks` |

**详情接口（真实捕获）：**

| 接口 | 方法/路径 | 观察到的响应键 |
|---|---|---|
| 达人资料 | `GET /rest/web/star/starProfile` | `starProfile.{userId,starId,name,gender,fansNumber,address,introduction,liveAvgPeopleNum,liveAvgLikeCnt,liveAvgLikeRate,dailyLiveTime,liveQuotedPrice,liveCpmExpectancy,livePlayCntExpectancy,livePcuCnt,liveWeeklyTimesCnt,priceShowInfo[],liveQuotedInfo}` |
| 直播带货 | `GET /rest/web/commerce/live` | `data.{liveCnt,liveWatchCntMedian,liveMaxOnlineCntMedian,goodsCnt,goodsGraph,duration}` |
| 作品/直播记录 | `GET /rest/web/star/starWorksInfo` | `starWorkReport.*`、`personLiveWorks[]`、`recentLiveWorks[]`（viewCnt/likeCnt/peakCnt/commentCnt/forwardCnt/duration/caption） |
| 受众画像 | `GET /rest/web/star/listPortrait` | `data.fansPortrait.*`、`data.viewerPortrait.*`（sex/age/activity/area/cityLevel/city/mobileBrand/mobilePrice/interest/nineMajorGroups + tgi） |
| 达人指数 | `GET /rest/web/starIndex/info`、`starRadarGraph`、`starTrendGraph` | 各 power model、雷达、趋势、排名/分位 |
| 评价 | `GET /rest/web/evaluation/star/score`、`/list` | contentQualityScore/cooperation/credit/comprehensive；评价列表 |
| 视频带货 | `GET /rest/web/star/queryCommerceInfo` | `video*` 字段；**视频口径，不是直播** |

### 4.6 身份交叉核对

- 既有短视频达人 `userId=841292065`（莉莉）在直播广场按快手 ID 检索，返回 **1 条**，`userId` 仍为 `841292065`，`starId=2576496`，`total=1`。
- 结论：聚星短视频与直播使用同一 `userId` 作为业务身份；`starId` 是详情/主页键，必须单独保留。
- 证据：`.runtime/live02/juxing-overlap/star_list_request-body.txt`、`star_list_response-body.txt`。

### 4.7 状态

| 调查项 | 状态 | 说明 |
|---|---|---|
| 子账号进入 | PASS | 需点「进入」，未改凭据 |
| 菜单/路由 | PASS | `#/star_plaza/live` |
| 筛选标签/控件 | PASS（标签） | 请求映射未逐项验证 |
| 列表/请求契约 | PASS | taskType=4、pathSource 真实捕获 |
| 翻页 | PASS（第 2 页） | 20 条、0 重复、total=5000 |
| 详情/字段 | PASS（数据概览） | 其他标签页部分字段待验证 |
| 身份交叉 | PASS | 同 userId、starId 单列 |
| 直播筛选完整开发 | NOT_VERIFIED | 阶段一只调查 |

## 5. 字段清单汇总（是否可获取）

状态定义：`已验证` = 本轮真实页面/响应确认；`待验证` = 页面可见但未逐项确认来源/映射；`不支持` = 未发现或明确不采集。

### 5.1 巨量星图直播

| 字段 | 含义 | 类型 | 来源 | 是否可获取 | 存储建议 | 展示位置 |
|---|---|---|---|---|---|---|
| star_id | 星图达人身份 | 文本 | 列表/详情 | 已验证 | `platform_creators.platform_creator_id` | 身份/详情 |
| 昵称/头像/性别/地域/粉丝 | 基础资料 | 文本/数值 | 列表/详情 | 已验证 | live current 通用列 | 基础信息 |
| 内容类型/内容标签 | 直播内容分类 | 文本/数组 | 列表/详情 | 已验证 | `live_metrics`/JSONB 或标签列 | 基础信息 |
| 近期直播场次 | 近30天开播场次 | 数值 | 列表/详情 | 已验证 | `live_metrics`（含 period=30d） | 直播表现 |
| 平均观看人数/人次 | 场均人数/人次 | 数值 | 详情 | 已验证 | `live_metrics`，单位=人 | 直播表现 |
| ACU/PCU | 平均/最高在线 | 数值 | 列表/详情 | 已验证 | `live_metrics` | 直播表现 |
| 粉丝观看占比 | 观众中粉丝占比 | 比率 | 详情（不限） | 已验证 | `live_metrics`，保存 0-1 比率 + 百分比原文 | 直播表现 |
| 场均涨粉数 | 场均新增粉丝 | 数值 | 详情 | 已验证 | `live_metrics` | 直播表现 |
| 场均评论率/点赞率 | 互动率 | 比率 | 列表/详情 | 已验证 | `live_metrics` | 直播表现 |
| 平均看播时长 | 秒 | 时长 | 详情 | 已验证 | `live_metrics`，单位=秒 | 直播表现 |
| 场均互动率 | 互动综合 | 比率 | 详情响应 | 已验证（响应） | `live_metrics`；页面暂未展示 | 扩展指标 |
| 带货商品数/GMV/客单价/GPM | 直播带货 | 数值/区间 | 详情 | 已验证 | `live_metrics`，区间保存原文 | 带货表现 |
| 场均CTR/CVR（4类） | 转化 | 比率 | 详情 | 样本为空 | `live_metrics`，NO_DATA 而非 0 | 转化表现 |
| 直播报价（品牌/电商专场/拼场） | 报价 | 金额/合作形式 | 详情 | 已验证 | 报价观察（可选新表/JSONB） | 报价 |
| 直播分析页 | 逐场分析 | 未知 | 直播分析标签 | 待验证 | 阶段二决定 | 直播分析 |
| 受众画像 | 观众/粉丝画像 | 分布 | 受众画像标签 | 待验证 | 阶段二决定 | 受众画像 |
| 联系方式（微信/电话/邮箱） | 联系 | 文本 | 详情介绍/名片接口 | 不支持（明确不采集） | 不存储 | 不展示 |

### 5.2 磁力聚星直播

| 字段 | 含义 | 类型 | 来源 | 是否可获取 | 存储建议 | 展示位置 |
|---|---|---|---|---|---|---|
| userId | 聚星快手账号身份 | 文本 | 列表/详情 | 已验证 | `platform_creators.platform_creator_id` | 身份/详情 |
| starId | 详情/主页键 | 文本 | 列表/详情 | 已验证 | live current 的 `platform_star_id` 或 `live_metrics` | 详情链接 |
| 昵称/头像/性别/地域/粉丝 | 基础资料 | 文本/数值 | 列表/详情 | 已验证 | live current 通用列 | 基础信息 |
| 达人类型/所属行业/所属机构 | 标签 | 文本/数组 | 列表/详情 | 已验证 | `live_metrics` | 基础信息 |
| 预期观看人数 | 直播预期观看 | 数值 | 列表/详情 | 已验证 | `live_metrics` | 直播表现 |
| 最高在线人数 | 直播峰值 | 数值 | 列表/详情 | 已验证 | `live_metrics` | 直播表现 |
| 预期CPM | 直播 CPM | 数值 | 列表/详情 | 已验证 | `live_metrics` | 直播表现 |
| 周均直播场次 | 开播频次 | 数值 | 详情 | 已验证 | `live_metrics` | 直播表现 |
| 直播互动率 | 互动率 | 比率 | 列表/详情 | 已验证 | `live_metrics` | 直播表现 |
| 平均观看人数（liveAvgPeopleNum） | 直播均值 | 数值 | 详情 | 已验证（列表样本为 0） | `live_metrics`，注明来源 | 扩展指标 |
| 场均点赞（liveAvgLikeCnt/Rate） | 点赞 | 数值/比率 | 详情 | 部分（Rate 可空） | `live_metrics`，空值 NO_DATA | 扩展指标 |
| 每日直播时长（dailyLiveTime） | 时长 | 文本/数值 | 详情 | 待验证（样本为空） | 阶段二 | 直播表现 |
| 带货直播场次/观看中位数/最高在线中位数/商品数 | 直播带货 | 数值 | 详情 commerce/live | 已验证（样本为 0 → 页面 -） | `live_metrics`，零值按无数据处理 | 带货数据 |
| 代表直播/直播频次/粉丝趋势 | 直播作品 | 列表/数组 | 详情 starWorksInfo | 已验证结构 | 可选作品/观测表或 JSONB | 代表作品 |
| 受众画像（观众/粉丝） | 分布 | 数组 | 详情 listPortrait | 已验证 | `live_metrics`/JSONB | 受众分析 |
| 达人指数/排名 | 指数 | 数值/文本 | 详情 starIndex | 部分（子项 null） | `live_metrics`，不补造 | 达人指数 |
| 评价/信用分 | 合作评价 | 数值/文本 | 详情 evaluation | 部分（页面显示 -） | `live_metrics`，NO_DATA | 合作情况 |
| 直播报价（按小时/天/商品） | 报价 | 金额/合作形式 | 详情 starProfile | 已验证 | 报价观察（可选） | 报价 |
| 联系方式 | 联系 | 文本 | 名片/介绍 | 不采集 | 不存储 | 不展示 |

## 6. 与短视频的差异（关键结论）

1. **入口不同**：星图 `/ad/creator/market/live`、聚星 `#/star_plaza/live`；短视频入口分别为 `/ad/creator/market`、`#/star_plaza/video`。
2. **请求不同**：星图同一 `search_for_author_square`，但 `scene_param.search_scene=2/display_scene=5` 等；聚星同一 `/rest/web/star/list`，但 `taskType=4`、`pathSource=no_filter_live|search_live`。
3. **详情不同**：星图直播主页路由 `author/douyin/{star_id}`；聚星 `live-promotion/star/{starId}`；接口和字段完全不同。
4. **身份一致**：星图共享 `star_id`；聚星共享 `userId`，`starId` 另存；可直接复用 `platform_creators` 身份。
5. **字段不可等同**：星图 `live_sn_*`（星图商单口径）≠ 详情『不限直播类型』；聚星列表 `liveAvgPeopleNum` 与详情 `starProfile.liveAvgPeopleNum` 样本不一致；聚星 `queryCommerceInfo` 是视频带货，不是直播。
6. **空值语义**：星图转化空对象、聚星 `commerce/live` 全 0、信用分 `-`；必须 `NO_DATA`，不能显示为真实 0 或补造。

## 7. 覆盖缺口与未验证项

- 星图直播筛选器的逐项请求映射（内容类型、商单类型、地域、粉丝、报价、各类直播表现）未验证。
- 星图「直播分析」「受众画像」标签页字段未完整核验。
- 聚星直播筛选器逐项请求映射未验证；推荐清单集合未展开。
- 聚星「达人指数」「代表作品」「受众分析」「带货数据」「合作情况」标签页仅部分字段核验。
- 两平台第 3 页及以后、真实终点未验证。
- 直播达人 `liveOnly`、`live+video` 在本地库的真实交集样本：通过定向检索证明可关联，但当前库内没有同时含两类快照的达人样本。
- 直播报价的 `task_category/video_type` 枚举与页面文案的完整映射未验证。
- 两平台直播页的默认排序、排序切换、默认条件的清空行为（星图「清空」）未验证。

## 8. 证据文件索引

### 8.1 可提交证据

- [巨量星图直播广场列表](assets/LIVE-02/xingtu-live-square-2026-11-04.png)
- [巨量星图直播详情数据概览（已裁掉左侧联系方式区域）](assets/LIVE-02/xingtu-live-detail-data-2026-11-04.png)
- [磁力聚星直播达人广场列表](assets/LIVE-02/juxing-live-square-2026-11-04.png)
- [磁力聚星直播详情数据概览](assets/LIVE-02/juxing-live-detail-2026-11-04.png)
- [星图直播 observed 契约](../../contracts/douyin_xingtu.live.observed.json)
- [聚星直播 observed 契约](../../contracts/kuaishou_juxing.live.observed.json)

### 8.2 私有原始证据（不提交）

| 路径 | 内容 |
|---|---|
| `.runtime/live02/xingtu-live/live-page.json` | 星图直播广场 DOM/文本/控件 |
| `.runtime/live02/xingtu-menu/menu-probe.json` | 星图菜单 anchor（含 `/ad/creator/market/live`） |
| `.runtime/live02/xingtu-search/01-net.json` | 星图直播搜索请求体/响应键路径 |
| `.runtime/live02/xingtu-page2-ui/results.json` | 星图第 1/2 页身份与分页 |
| `.runtime/live02/xingtu-click/03-detail.json` | 星图直播详情 URL/文本 |
| `.runtime/live02/xingtu-detail-data/raw/` | 星图详情接口原始响应（含业务数据，0600） |
| `.runtime/live02/xingtu-overlap/ids.json` | 星图同 star_id 定向检索 |
| `.runtime/live02/juxing-live/04-live-page.json` | 聚星直播广场 DOM/文本/控件 |
| `.runtime/live02/juxing-live-net/star_list_128_*.txt` | 聚星直播列表请求体/响应原文 |
| `.runtime/live02/juxing-page2-ui/results.json` | 聚星第 1/2 页身份与分页 |
| `.runtime/live02/juxing-detail/02-detail.json` | 聚星直播详情 URL/文本 |
| `.runtime/live02/juxing-detail-data/raw/` | 聚星详情接口原始响应（含业务数据，0600） |
| `.runtime/live02/juxing-overlap/star_list_*.txt` | 聚星同 userId 定向检索 |

## 9. 隐私与合规

- 本文不包含 Cookie、令牌、请求头、密码或完整响应正文。
- 原始响应仅保存在 `.runtime/live02/`，不提交；其中可能含达人昵称、头像 URL、地区等公开业务数据。
- 星图详情介绍与名片接口可能含微信/电话/邮箱，**本项目不采集、不存储、不展示**；证据截图已裁掉星图左侧介绍区域。
- 未绕过验证码、风控或登录；未修改平台任何业务数据。

## 10. 结论

- 两平台直播广场均可真实进入、检索、翻页并打开直播专属详情；入口、身份、分页、列表与详情字段已取得真实证据。
- 两平台短视频与直播共享平台身份（星图 `star_id`、聚星 `userId`），直播数据必须独立存储并与短视频数据隔离。
- 直播字段与短视频字段口径不同，不能混用；空值/无数据必须显式建模。
- 阶段一可以支撑 PRD、技术方案、测试用例与影响分析；筛选器逐项映射、page 3+、部分标签页字段留待阶段二验证。
