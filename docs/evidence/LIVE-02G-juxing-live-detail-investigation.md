# LIVE-02G 磁力聚星直播达人详情字段调查证据

日期：2026-11-05（Asia/Shanghai）
分支：`1105-live02g`（起点 `1104-llb`）
环境：macOS 本机；API `8000`、前端 `5173`、PostgreSQL `55432`（schema 21）、Redis `56379`、Temporal `57233`；真实平台：磁力聚星
工具：项目 `scripts/qa/mcp_client.py`（stdio JSON-RPC）驱动 `@playwright/mcp` + 系统 Chrome；只读页面/接口；数据库只读查询
关联：[LIVE-02G 任务卡](../tasks/LIVE-02G.md)、[设计](../design/LIVE-02G-juxing-live-detail-design.md)、[字段字典](../design/LIVE-02G-juxing-live-field-dictionary.md)

## 1. 目的与边界

本次只调查磁力聚星「找达人 → 直播达人广场 → 达人直播主页」的详情字段，目标是确认：

1. 附件中的业务模块真实归属哪个达人、哪个页面；
2. 每个字段的真实请求、响应路径、类型、单位、周期；
3. 当前代码已经采集/未采集/采集后未展示的差异；
4. 空值、`0`、`-`、空数组和采集失败的区分；
5. 需要新增的请求/页面操作，以及哪些字段当前账号或样本不可获取。

调查只读：不点击下单/联系/加入清单，不采集 Cookie/令牌/请求头，不写业务数据。原始响应保存在 `.runtime/live03-investigation/`（gitignored、0600），本文只记录路径、键名、单位、口径与公开业务数值。

## 2. 附件身份：不是单一达人页面

附件是**两个真实达人**的模块混合，已通过真实页面文本、ID、粉丝数、报价、作品和排名逐一核对：

| 附件模块 | 真实归属 | 关键证据 |
|---|---|---|
| 基础信息、数据概览、报价、达人指数、合作数据概览、客户评价 | 王者荣耀王小贱（福利主播），userId `52022133`，starId `9104` | ID `52022133`；粉丝 3739万；报价 29,100/75,450/45,400；指数 81.6；排名 30538/64；合作 56.4%/72%/18；评价 4.8、18条 |
| 代表作品、粉丝趋势、受众画像明细 | 桐桐就酱🐑.，userId `1633604095`，starId `451066` | 作品「桐门」；个人作品 35 条/1/9；粉丝趋势约 +23.1万/1.4%（本次实测 +23.1万/1.4% 附近）；受众画像 女性85.9%、苹果32.1%、Top5 广东河南河北山东广西 |

因此验收同时使用 `9104` 与 `451066`；附件中的模块归属和当前真实值会随时间漂移，**以本次观测值为准**。

## 3. 当前实现基线

- `backend/src/xingtu/juxing_live_adapter.py` 原只请求 `starProfile`、`starWorksInfo`（仅 report）、`commerce/live`（仅 7 天）。
- `contracts/kuaishou_juxing.live.verified.json` 原只有 `basic` + `live`（27 字段）。
- `creator_live_current.live_metrics` 保存 `live.*` 的 COLLECTED envelope；快照 payload 保存全部字段状态。
- 前端 `frontend/src/liveCreator.tsx` 原只显示一个 15 项指标条；没有模块、图表、作品、画像、评价。
- `listPortrait`、`starIndex/*`、`evaluation/*` 已在 `DETAIL_PATHS` 登记但未调用；`queryVideoPlayCnt` 未登记。

## 4. 真实端点

所有详情请求都在已登录的 `https://k.kuaishou.com/` 页面内以 `fetch(credentials: include)` 重放；真实方法均为 POST：

| 端点 | 请求体 | 支撑模块 |
|---|---|---|
| `/rest/web/star/starProfile` | `{"starId":"9104","starType":4}` | 基础、概览、报价、粉丝趋势、合作、热销品牌/类目、观众摘要 |
| `/rest/web/star/starWorksInfo` | `{"starId":"9104","starType":4}` | 个人作品、聚星作品、最近15个直播、直播报告 |
| `/rest/web/star/listPortrait` | `{"starId":"9104","starType":4}` | 观众画像、粉丝画像完整分布 |
| `/rest/web/starIndex/starRadarGraph` | `{"userId":52022133,"starType":4}` | 达人指数、六维雷达、同粉段均值 |
| `/rest/web/starIndex/starTrendGraph` | `{"userId":52022133,"starType":4}` | 指数趋势、同行业/同粉段排名与比例 |
| `/rest/web/evaluation/star/score` | `{"starId":9104,"promotionType":2}` | 评价汇总 |
| `/rest/web/evaluation/star/list` | `{"starId":9104,"promotionType":2,"page":1,"size":10}` | 评价明细分页 |
| `/rest/web/commerce/live` | `{"starId":9104,"duration":7}`（另 30/90） | 带货数据 |
| `/rest/web/star/queryVideoPlayCnt` | `{"starId":9104,"type":4}` | 直播频次分布（月/周/时） |

不采集：`commerce/video`、`queryCommerceInfo`（视频带货口径）、`starIndex/info`（两样本全 null，直播页不依赖）、联系/接单/短剧等非本任务模块。

## 5. 字段来源与关键语义

| 页面字段 | 真实来源 | 类型/单位 | 关键规则 |
|---|---|---|---|
| 昵称/头像/userId/starId/地域/粉丝/MCN | `starProfile.name/headUrl/userId/starId/address/fansNumber/govName` | text/count | 身份沿用 `platform_creators` |
| 内容分类/标签 | `starProfile.contentTypeTag.firstTagName/secondTagName` | tags | 9104=`["游戏","多人在线战术竞技游戏"]`；451066=`["颜值达人","颜值综合"]` |
| 内容形式 | `starProfile.contentFormTag` | tags | 451066=`["vlog"]`；9104 空 |
| 所属行业 | `starProfile.industryTag[].firstTagName/secondTagName[]` | tags | 拼接为「通信-号卡」等；不再使用空的 `industryTagStr` |
| 认证信息 | `starProfile.verifiedInfo` | text | 9104=`快手2025百大主播`；451066 空 → NO_DATA |
| 按小时/天/商品报价 | `starProfile.priceShowInfo[]`（businessLine=2） | yuan | 原始 price 为 1/1000 元；`price_type` 1/2/3 分开，不合并 |
| 粉丝/预期观看/最高在线/CPM/周均 | `starProfile.fansNumber/livePlayCntExpectancy/livePcuCnt/liveCpmExpectancy/liveWeeklyTimesCnt` | count/cpm | 最高在线与预期最高在线分开 |
| 预期最高在线 | `starProfile.liveMaxExpectOnlineViewer` | count | 9104=52,357；最高在线=129,037 |
| 近30天信用分 | `starProfile.creditScore` | number | 两样本 null → NO_DATA；不能用 `evaluation.credit` 补 |
| 历史合作行业 | `starProfile.liveBusinessReport.advertiserFirstIndustries` | tags | 10 个行业 |
| 观众摘要 | `starProfile.viewerFeatureTag/viewerDeviceTag/viewerAreaTag` | tags | 平台文字摘要；不是完整分布 |
| 合作 30/90 | `liveBusinessReport.acceptOrderRateData/completeOrderRateData/completeOrderCntData` | ratio/count | 9104 30=56.41%/72%/18，90=73.63%/84.51%/60；451066 30/90 null/0 → NO_DATA |
| 粉丝趋势 30/90 | `fansIncreaseNum.30/90`、`fansIncreaseRateIn30/90`、`trendData`、`trendDiffData` | count/ratio | 总量与增量按日期分开；9104 30=15,674/0.04%，90=636,509/1.73% |
| 达人指数 | `starRadarGraphVO.starIndexCurrent/starIndexAvg`、`starTrendGraphVO.starIndexRank/starIndexPercent/starIndexHistory` | number/ratio | 9104 综合 81.6；排名 30538/64；超越 78.3%；趋势全 0 |
| 个人/聚星作品 | `starWorksInfo.personLiveWorks/adSocialLiveWorks` | structured[] | 9104 19/57；451066 35/0；`personWorks`/`adSocialWorks` 为空且为视频口径，不使用 |
| 最近15个直播 | `starWorksInfo.recentLiveWorks` | structured[] | 9104 15 条，chart 最高 236.7万/最低 1万 |
| 作品字段 | `streamId/caption/coverUrl/url/releaseTimeMillis/durationTimeMillis/viewCnt/peakCnt/commentCnt/forwardCnt/likeCnt/hasSkuInfo/orderId` | mixed | `streamId` 唯一标识；`url` 是带 auth_key 的有时效播放地址 |
| 只看电商带货 | 页面客户端按 `hasSkuInfo` | bool | 9104 个人 4/19；聚星 0/57 |
| 直播频次分布 | `queryVideoPlayCnt.data.starWorkPlayMonthInfo/WeekInfo/HourInfo` | count dict | 9104 月=[33,48,9]；周 0=周日；时=小时；近三个月 |
| 观众/粉丝画像 | `listPortrait.data.viewerPortrait/fansPortrait.*` | structured | 比例 0-1，TGI 整数；两侧独立 |
| 城市等级/城市 | `cityPercentage` / `cityLevelPercentage` | structured | **平台命名相反**：前者是城市等级，后者是城市名 |
| 设备类型 | `mobilePercentage` | structured | 两样本为空；仅 `viewerDeviceTag` 文字摘要 |
| 兴趣/九大人群 | `interestPercentage/nineMajorGroupsPercentage` | structured | 观众兴趣为空；粉丝兴趣 10 项；九大人群空 → NO_DATA |
| 带货 7/30/90 | `commerce/live.data` | structured | 9104 7 日全 0→NO_DATA；30=4/2313723/45708/14；90=12/2893961/52297/35；`goodsGraph` 为价格区间/带货量 |
| 热销品牌/优势类目 | `starProfile.hotBrandInfo/hotChannelInfo` | structured | 9104 王者荣耀/其他100%；451066 无 |
| 评价汇总 | `evaluation/star/score.data` | structured | 9104 4.8/4.8/4.8/4.8；451066 total=0 → 页面空态，score 5.0 不展示为有效评分 |
| 评价明细 | `evaluation/star/list.data.data/total` | structured | 9104 total=18、10+8 两页；无平台评价 ID；`pageNum/pageSize` 返回 0 |

## 6. 页面行为（真实核验）

- **Tab**：详情页 6 个 Tab 的数据在初始加载时已由接口返回；真实验收通过登记响应直取，不依赖点击 Tab。页面切换周期/作品类型/画像侧不会产生新的详情接口请求（commerce 周期切换会重新请求 `commerce/live`，`starProfile` 也会被页面重复请求一次；Adapter 按 duration 分开请求，不依赖页面状态）。
- **作品轮播**：`人物作品` 1/5（9104，19 条）、1/9（451066，35 条）；`聚星作品` 1/15（9104，57 条）由前端分页，接口一次返回全量。`只看电商带货` 是客户端过滤 `hasSkuInfo`。
- **直播频次**：`queryVideoPlayCnt type=4` 返回月/周/时三个字典；页面默认按月，可切按周/按时。周 key `0..6` 对应 `周日..周六`（页面 JS 常量 `{0:"日",...,6:"六"}`）。
- **评价分页**：`size=10`；9104 第 1 页 10 行、第 2 页 8 行、第 3 页空；`pageNum/pageSize` 均为 0，不能用于分页判断。
- **页面隐藏评价**：`hiddenName=true` 时页面显示“匿名评论”；不能保存原始 `productName`（可能含订单/客户信息）。
- **时间范围**：合作数据“时间范围”由页面按观测日推导（9104 近30天 2026-10-06~2026-11-04，近90天 2026-08-07~2026-11-04），接口不返回起止日期。
- **达人指数雷达**：6 维当前值；同粉段均值只有 5 维，无综合指数均值；趋势选择器暴露 6 个维度（达人指数/涨粉指数/性价比/影响力/商业活跃度/合作指数），响应另含 4 条未暴露序列。
- **指数趋势**：9104/451066 的 10 条月度序列均返回 0.0；页面显示 0，已保留并标记 `all_zero`，不伪造。

## 7. 空值/0/失败的真实样本

| 场景 | 样本 | 平台页面 | 本次处理 |
|---|---|---|---|
| 信用分为空 | 9104/451066 `creditScore=null` | `-` | NO_DATA，保留 raw null |
| 合作 30/90 为空 | 451066 `*Data=null/0` | `-` | NO_DATA，保留 raw |
| 带货 7 日全 0 | 9104/451066 `liveCnt=0,...` | `-` + 暂无分析 | NO_DATA，保留 raw 0 |
| 评价 total=0 | 451066 | 暂无评价空态 | summary/reviews NO_DATA；total=0 COLLECTED |
| 内容形式为空 | 9104 `contentFormTag=[]` | 无内容形式标签 | NO_DATA |
| 认证信息为空 | 451066 `verifiedInfo=""` | 页面无认证 | NO_DATA |
| 设备类型为空 | 两样本 `mobilePercentage=[]` | 仅“安卓设备为主”摘要 | 画像维度 SUMMARY_ONLY + 摘要文本 |
| 九大人群为空 | 两样本 `[]` | 不展示 | NO_DATA |
| 指数趋势全 0 | 两样本 | 0 折线 | COLLECTED + all_zero |
| 作品媒体 URL | 带 auth_key | “详情”弹层播放 | 保存原值，标注有时效，不伪造公开作品页 |

## 8. 数据差异（附件 vs 当前真实值）

- 9104 当前：粉丝 37,388,604（3,739万）、预期观看 1,734,393、最高在线 129,037、预期CPM 17、周均 10、预期最高在线 52,357、指数 81.6/30538/64、合作 30=56.4/72/18、90=73.6/84.5/60、评价 18 条。
- 451066 当前：个人作品 35、聚星 0、粉丝趋势 30=230,664/1.37%、指数 85.25/13776/6387、合作/带货/评价多为空；评价 total=0。
- 附件中的 182万/16/55400/+23.1万 等数值是更早时刻或另一达人的值；**采集与验收以本次快照观测值 + 观测时间为准**，不按附件数字硬编码。

## 9. 证据与限制

- 详情原始响应：`.runtime/live03-investigation/detail-9104-full/raw/`、`.runtime/live02/juxing-detail-data/`（私有不提交）。
- 真实任务：9104 `397b46dc-0cb4-4f8f-ae90-5d5bffd017d4`、451066 `0e1e01c3-3293-4469-8934-2fdf5f0cb56a`、9104 手动更新 `56592cc0-f56f-4b99-aa39-befd07e14e3e`。
- 截图：`.runtime/live03-investigation/ui-real2/`；脱敏副本见 `docs/evidence/assets/LIVE-02G/`（若写入）。
- 限制：附件为混合样本；指数趋势全 0 是平台返回；设备类型/九大人群/部分兴趣为空；作品 URL 有时效；评价无平台 ID；page 7+ 与真实终点沿用 LIVE-02 未验证；本次未重跑 70 位全量。

## 10. 结论

附件列出的业务模块均找到了真实来源；新增字段可以通过已登记详情接口采集，且 9104/451066 两位样本覆盖了“有完整数据”“部分字段暂无数据”“评价为空”三种情况。未发现必须改动核心架构或新增数据库表才能完成的字段。
