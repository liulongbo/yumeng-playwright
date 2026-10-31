# KJX-01 巨量星图 vs 磁力聚星：功能差距与字段字典

状态：真实平台只读调查已完成（2026-10-29）；合同 v2/v3、Adapter、前端、读模型与账号选择专项已实现；真实 T1/T2/T3 全部通过（2026-10-30，阶段 D-0 GO）。  
关联卡片：[KJX-01](../tasks/KJX-01.md)  
关联证据：[首轮测试用例](../evidence/KJX-01-full-test-cases.md)、私有调查目录 `.runtime/kjx-full/probe/`。

## 1. 方法与证据边界

- 星图侧：读取已验证合同 `contracts/douyin_xingtu.verified.json`、现有 Adapter/Reader/前端与阶段 C 证据；本轮不改星图合同与采集逻辑。
- 聚星侧：使用已授权子账号 `60821564` 的独立 Profile 会话（Playwright MCP + 系统 Chrome，plaintext storage-state 注入，避免系统 Keychain 解密限制），只读访问搜索页与达人详情；不采集、不下单、不写平台、不导出 Cookie。
- 聚星页面调查覆盖：
  - 搜索第 1/2/3 页（关键词）、关键词+内容类型、关键词+粉丝、关键词+地域、关键词+报价的第 1/2 页；
  - 内容类型完整 tag API（38 个一级类目、子 tag）、地域 address API（34 个省级、352 个城市）、三档报价控件；
  - 达人详情页 `#/promotion/star/{starId}?openBy=user` 的五个章节及其 12 个页面内部请求；
  - 作品公开页尝试、达人主页公开 URL 尝试。
- 证据只保留字段路径、标签、单位、计数、请求体形状；不把达人昵称、ID、Cookie、Token 或响应正文写入文档。私有原始响应在 `.runtime/kjx-full/probe/`（0700/0600）。

## 2. 结论摘要

| 维度 | 巨量星图 | 磁力聚星（本轮前） | 聚星真实平台 | 本轮处理 |
|---|---|---|---|---|
| 搜索分页 | `page_fetch`，已验证到第 3 页；第 4 页起 fail closed | 仅第 1 页；第 2 页 `SEARCH_CAPABILITY_LIMIT` | 页面为 20 条/页、231—250 页；`currentPage/total` 有效；**页面自身分页会丢失关键词筛选**，但显式带完整筛选体的第 2 页请求可正确筛选 | 合同改 `page_fetch`，`page_fetch_max_verified=2`（第 2 页有真实证据；第 3 页只读观察，不进入执行合同）；Adapter 每页重建筛选体；真实 T2 验证 |
| 筛选 | 10 项：关键词/性别/地域/学历/黄V/连接用户/粉丝/观众画像/粉丝画像 | live 合同仅关键词+母婴亲子；模型与 Adapter 已有粉丝/地域/报价字段但未开放 | 页面有内容关键词、昵称找人、内容类型（38 类）、内容形式、营销目标、目标人群、粉丝数量、达人报价（三档）、达人性别、达人地域（省/市）、达人指数、达人人设、出镜风格、星标推荐、近30日粉丝上升、微信建联、活跃度、商单经验、历史合作、CPS、对公、机构、出镜人物、内容主题、粉丝/观众画像、CPM/CPE/播放/互动/完播、限时折扣等 | 开放关键词、内容类型（38 类）、粉丝量级、地域（省/市全量）、三档报价；其余只记录不启用 |
| 详情模块 | 8 模块 81 字段：basic/commercial/spread/seeding/fulfillment/conversion/fans/creation | 4 模块 25 字段：basic/spread/works/audience | 页面章节：看数据 / 看作品 / 看受众 / 看履约 / 看带货；除既有四模块外还有履约（接单率/完单率/订单数）与带货（曝光/访问/转化率/GMV/订单/GPM/客单价） | 只扩展既有四模块；不新增必填模块；履约/带货进入后续方案 |
| 完成判定 | 资料完整 + F06 两集合 | 四模块完整即流水线完整；无 F06 | 无 F06；履约/带货非 P0 | 保持聚星“四模块完整”语义；新字段缺失发 NO_DATA，不改变完成判定 |
| 更新/补采/定时 | 支持 | 手动/定时 422/不入册；continue/retry 平台无关但补数量受单页限制 | 平台可采集；本轮不做更新 | 分页后 retry 可继续补数量；更新/定时后续 |
| 历史快照 | 有读模型 | 快照已落库，无库级历史 UI | 可采集 | 本轮只验证不可变快照；库级 history/quotes/videos UI 后续 |
| 执行单元/会话 | 已验证 | 已验证 | — | 只回归，不改 |

## 3. 筛选条件矩阵

星图侧以 `contracts/douyin_xingtu.verified.json` 的 `capabilities.fields` 为准（10 项）。聚星侧状态：

| 聚星页面条件 | 页面标签/控件 | 真实请求映射（只读验证） | 状态 | 本轮是否启用 |
|---|---|---|---|---|
| 内容关键词 | “内容找人”搜索框 | `userName`、`searchSourceType:10`、`pathSource:"precise_content_search_video"`（仅关键词） | 已验证；第 1/2/3 页真实返回 | **是** |
| 昵称找人 | “昵称找人”radio | 独立搜索模式（未作为 P0 字段注册） | 平台存在；未接入模型 | 否（后续） |
| 内容类型 | 38 个一级类目 | `contentTagIdList:[{id, subIds, selectFirstLevelId:true}]`；如母婴亲子 `676/740-743`、美妆 `670/707-712` | 已验证；`starTagV2` 返回全量 38 类 | **是**（38 类一级类目） |
| 内容形式 | 22 个形式 tag | `contentFormIdList`（页面请求字段；未进入 P0 模型） | 平台存在 | 否（后续） |
| 粉丝数量 | 不限 / 1000万以上 / 500万-1000万 / 300万-500万 / 100万-300万 / 10万-100万 / 10万以下 + 自定义万区间 | `fansMinNum`、`fansMaxNum`（count，整数） | 已验证（10万-100万 → 100000/1000000；组合结果 1153） | **是**（预设+自定义） |
| 达人报价 | 报价类型 1-20秒/21-60秒/60秒以上 + 报价区间 5,000以下/…/10万以上 + 自定义 | `priceType` 11/12/13；`starMinPrice/starMaxPrice`（平台整数=元×1000） | 已验证（21-60秒 max 1万 → total 4508；min/max 组合 → 4392） | **是**（三档，单档生效） |
| 达人地域 | 省级/城市 multi-tree（34 省、352 市） | `cityCodeList`（平台 cityCode 数组；省级=全部城市 code；如北京 1101、河北 12 个 city code、石家庄 1301） | 已验证（北京 53、河北 272/271、石家庄 64） | **是**（全量省市；按 address API） |
| 达人性别 | 达人性别 | 页面有控件；P0 v3 模型不接受 gender | 平台存在；P0 范围外 | 否（后续） |
| 营销目标 | 用户触达/品牌种草/购买转化 | 页面请求 `marketingGoal`（1/2/3）；当前 Adapter 固定 1 | 平台存在；P0 固定默认 | 否（后续） |
| 目标人群/匹配度 | 自定义人群包/匹配度 | 页面请求字段未注册 | 平台存在 | 否 |
| 达人指数/人设/出镜风格/星标/微信建联/活跃度/商单/历史合作/CPS/对公/机构/出镜人物/内容主题 | 达人信息折叠项 | 页面控件与请求字段未逐项核验 | 平台存在；权限/口径未完整验证 | 否（后续） |
| 受众人群（粉丝/观众画像） | 粉丝画像/观众画像 | `fansCityPercentage/viewerCityPercentage` 等；P0 未建模 | 平台存在 | 否 |
| 内容表现/预期CPM/CPE/播放/互动/完播 | 性价比折叠项 | 页面控件；未逐项核验组合 | 平台存在 | 否（后续） |
| 限时折扣 | 限时折扣 | 未核验 | 平台存在 | 否 |
| 排序 | 页面固定/默认 | `starOrderTag:3`、`starOrderType:0`（默认） | 已验证默认 | 保持平台默认 |
| 关键词+多筛选组合 | 页面自动叠加 | 已验证关键词+内容类型、+粉丝、+地域、+报价的第 1/2 页均保持条件；第 2 页由显式请求体重建 | 已验证 | **是**（受支持组合） |

**页面分页行为的重要发现**：点击页面自身的第 2 页时，页面发出的 `/rest/web/star/list` 请求体是“无筛选”的通用体（`pickList:[]`、无 `userName`），结果从 1000+ 母婴变为 5000 条混合结果；即**平台 UI 的分页会丢筛选**。而在同一已登录页面上下文中，显式带 `userName`/`contentTagIdList`/`fansMinNum`/`cityCodeList`/`priceType` 的 `currentPage=2` 请求返回的仍是筛选后的结果（total 不变、逐行满足条件）。因此 Adapter 必须**每页重建完整筛选体**，不能依赖页面点击分页。这是本轮分页实现的关键设计依据。

## 4. 分页能力分析

### 4.1 星图

- `pagination:"page"`、`next_page_mode:"page_fetch"`、`page_fetch_max_verified:3`、`continus_verified:false`。
- 页面点击/滚动不产生下一页请求；已核验同一页面上下文复用原生请求头/请求体可取得 page=2/3。
- 第 4 页起 fail closed，以 `SEARCH_CAPABILITY_LIMIT` 停止，不报告平台耗尽。

### 4.2 聚星（本轮调查）

| 项 | 观察 |
|---|---|
| 每页数量 | 20（请求 `pageSize:20`；页面 UI 也按 20） |
| 页码字段 | `currentPage`；响应回显 `currentPage` |
| 总数 | 响应 `total`；关键词“母婴”=4604；关键词+母婴亲子=2319；关键词+粉丝10万-100万=1153；关键词+河北=272/271；关键词+21-60秒≤1万=4508 |
| 页面 UI | Ant Design 分页，1/2/3/4/5/…/231—250；上一页/下一页/跳页 |
| 页面 UI 翻页 | **丢失关键词/筛选**（请求体变为无筛选通用体，total 变 5000，结果混合） |
| 显式第 2 页 | 带完整筛选体时 total 不变、逐行满足条件；关键词第 1/2/3 页均返回 20 条不同身份；关键词+内容类型/粉丝/地域/报价的第 2 页也已验证 |
| 终点 | `currentPage*20 >= total`；第 231/250 页；未见 `has_more` 字段 |
| 空页/结构异常 | 页面正常分页下未观察到；实现按“空页但 total 未到终点”显式失败，不伪装耗尽 |
| 登录/账号 | URL 外层+hash `__accountId__=60821564`；详情页在搜索页存活时回查账号；分页请求在已登录搜索页上下文执行 |
| 重复 | 第 1/2 页抽样无重复；实现由 Engine `scanned_ids/candidates` 去重；跨页重复仍需合成测试 |
| 本轮合同边界 | `page_fetch_max_verified=2`（第 3 页只读观察，不进入可执行合同）；第 3 页起 `SEARCH_CAPABILITY_LIMIT`；隔离环境目标上限 30，T2 target=22 只需第 2 页 |

## 5. 字段字典（聚星，按本轮处理）

状态定义：**已验证**=页面/响应/单位/窗口均有证据；**已采集**=Adapter 已写入 projection/snapshot；**本轮补齐**=本轮新增；**未采集**=平台存在但本轮不采；**不适用**=平台无此语义；**权限受限**=当前账号不可用；**暂无法确认**=证据不足。

### 5.1 基础资料 `basic`

| 页面字段 | 业务含义 | 来源/响应路径 | 原始类型 | 单位/窗口 | 状态 | 标准/专属 | 本轮 |
|---|---|---|---|---|---|---|---|
| ID / userId | 达人唯一身份 | `baseInfo.data.userId` | int→text | — | 已验证/已采集 | 标准（平台身份） | 保持 |
| 昵称 | 名称 | `data.name` | text | — | 已验证/已采集 | 标准 | 保持 |
| 头像 | 头像 URL | `data.headUrl` | text | — | 已验证/已采集 | 标准 | 保持 |
| 性别 | 达人性别 | `data.gender` | text（男/女） | — | 已验证 | 标准 | **补齐** |
| 地区 | 省/市 | `data.address` `省-市` | text | — | 已验证/已采集 | 标准 | 保持 |
| 内容类型 | 一级/二级内容类型 | `data.contentTypeTag.firstTagName/secondTagName` | tags | — | 已验证/已采集 | 平台分类 | 保持 |
| 内容形式 | 推荐/配音/… | `data.contentFormTag[].firstTagName/secondTagName` | tags | — | 已验证 | 平台分类 | **补齐** |
| 主页地址 | 快手公开主页 | `data.profileUrl`（`www.kuaishou.com/profile/...`，无 scheme） | text | — | 已验证（公开页可打开）；展示需补 `https://` | 标准（需归一化） | **补齐**（只读链接） |
| 平台身份 | 平台达人身份标签 | `data.platformTargetIdentityInfo.name` | text | — | 页面可见（如“潜力达人”）；页面“达人类型”另有空值 | 专属 | **补齐**（平台原值） |
| 出镜风格 | 风格原值 | `data.styleDetail` | text | — | 已验证（基础响应）；页面筛选有同名条件 | 平台分类 | **补齐**（平台原值） |
| 对公结算 | 是否支持对公 | `data.publicSettlement` | bool | — | 已验证 | 商业 | **补齐**（是/否） |
| MCN | 所属机构 | `data.mcnName` | text | — | 已验证/已采集；空→NO_DATA | 标准 | 保持 |
| 介绍 | 简介（联系方式脱敏） | `data.introduction` | text | — | 已验证/已采集 | 标准 | 保持 |
| 粉丝数 | 粉丝数 | `data.fansNumber` | int | count | 已验证/已采集 | 标准 | 保持 |
| 近30天涨粉数 | 粉丝增量 | `fans/fluctuation.data.fansIncreaseNum` | int | 近30天 | 已验证/已采集；缺失 NO_DATA | 标准（平台窗口） | 保持 |
| 近30天涨粉率 | 粉丝增长率 | `fans/fluctuation.data.fansIncreaseRate` | decimal | 近30天 | 已验证/已采集 | 标准（平台窗口） | 保持 |
| 三档报价 | 1-20/21-60/60+ 视频报价 | `data.priceShowInfo[]`（businessLine=1） | int（元×1000） | CNY | 已验证/已采集 | 标准（平台原值） | 保持；**补齐**原价/有效期 |
| 报价原价/有效期 | 原价、开始/结束时间 | `priceShowInfo[].originalPrice/priceStartTimeMs/priceEndTimeMs` | int/ms | CNY/时间戳 | 已验证字段存在；样本多为空 | 平台专属 | **补齐**（空→NO_DATA） |
| 星图式达人类型/行业标签 | 星图 taxonomy | — | — | — | **不适用**（聚星无同义字段） | — | 不映射 |
| 联系方式 | 电话/微信 | 简介/页面 | — | — | **不适用**（P0 禁止采集；简介已脱敏） | — | 不做 |

### 5.2 传播表现 `spread`

| 页面字段 | 业务含义 | 响应路径 | 单位/窗口 | 状态 | 本轮 |
|---|---|---|---|---|---|
| 播放量中位数 | 个人视频播放中位数 | `natureStatistics.pplayMedian` | count / 近30天+流量7天 | 已采集 | 保持 |
| 播放中位数优于同类 | 分位 | `natureStatistics.pplayMedianPowerPercent` | ratio / 同上 | 已验证 | **补齐** |
| 预估播放量 | 预期播放 | `businessStatistics.beplayCnt` | count / 同上 | 已采集 | 保持 |
| 预估播放环比 | 播放变化 | `businessStatistics.beplayCntMOM` | ratio / 同上 | 已验证 | **补齐** |
| 预期 CPM | 预期千次曝光成本 | `businessStatistics.beCPM` | CNY/千次 / 同上 | 已采集 | 保持 |
| 预期 CPM 环比 | CPM 变化 | `businessStatistics.beCpmMOM` | ratio / 同上 | 已验证 | **补齐** |
| 近期 CPM | 近期千次曝光成本 | `businessStatistics.bcpm` | CNY/千次 / 同上 | 已验证（样本空） | **补齐**（空→NO_DATA） |
| 近期 CPE | 近期单次互动成本 | `businessStatistics.bcpe` | CNY/action / 同上 | 已验证（样本空） | **补齐**（空→NO_DATA） |
| 互动率 | 互动率 | `natureStatistics.pinteractionRate` | ratio / 同上 | 已采集 | 保持 |
| 互动率优于同类 | 分位 | `natureStatistics.pinteractionRatePowerPercent` | ratio / 同上 | 已验证 | **补齐** |
| 完播率 | 完播率 | `natureStatistics.pcompletePlayRate` | ratio / 同上 | 已采集 | 保持 |
| 完播率优于同类 | 分位 | `natureStatistics.pcompletePlayRatePowerPercent` | ratio / 同上 | 已验证 | **补齐** |
| 平均分享/点赞/评论（统计接口） | 个人视频平均 | `natureStatistics.pavg*` | count / 同上 | 已采集；缺失 NO_DATA | 保持 |
| 视频数量 | 个人视频数 | `natureStatistics.preleaseCnt` | count / 同上 | 已采集 | 保持 |
| 平均时长 | 个人视频平均时长 | `natureStatistics.pavgVideoDurationData` | seconds / 同上 | 已采集 | 保持 |
| 连接用户数 | 连接用户 | `data.visitorNum` | count / 同上 | 已验证 | **补齐** |
| 深度连接用户数 | 深度连接用户 | `data.deepVisitorNum` | count / 同上 | 已验证 | **补齐** |
| 聚星视频播放中位数 | 商业视频中位数 | `businessStatistics.bplayMedian` | count / 同上 | 已验证（样本空） | **补齐**（空→NO_DATA） |
| 聚星视频播放分位 | 商业视频分位 | `businessStatistics.bplayMedianPowerPercent` | ratio | 已验证（样本空） | **补齐** |
| 聚星视频数 | 商业视频数 | `businessStatistics.breleaseCnt` | count | 已验证（样本空） | **补齐** |
| 聚星视频完播/互动率 | 商业视频率值 | `bcompletePlayRate/binteractionRate` + 分位 | ratio | 已验证（样本空） | **补齐** |
| 聚星视频平均时长/点赞/评论/分享 | 商业视频均值 | `bavg*` | seconds/count | 已验证（样本空） | **补齐** |
| 转化点击率 | 商业转化点击率 | `businessStatistics.bavgConversionClickRate` | ratio | 已验证（样本空） | **补齐** |
| 作品波动（前15平均） | 播放/赞/评/享均值 | 由 works 前 15 派生 | count | 页面展示 | 保持前端派生（不新增合同字段） |
| 星图两档 CPM/CPE | 星图 21-60/60+ 商业指标 | — | — | **不适用**（聚星无同义两档） | 不映射 |

### 5.3 代表作品 `works`

`works` 是结构化数组；本轮不新增模块字段，只扩充 item 键与前端展示。

| item 字段 | 业务含义 | 响应路径 | 状态 | 本轮 |
|---|---|---|---|---|
| platform_content_id | 作品 ID | `detailList[].photoId` | 已采集 | 保持 |
| title | 标题 | `caption` | 已采集 | 保持 |
| cover_url | 封面 | `coverUrl`（可渲染图片 URL） | 已采集 | **前端展示** |
| media_url | 媒体地址 | `webpUrl`（当前；短链打开返回 JSON error） | 已采集；**非公开作品页** | 保持，不构造链接 |
| play/like/comment/share | 计数 | `viewCnt/likeCnt/commentCnt/forwardCnt` | 已采集 | 保持 |
| published_at_ms | 发布时间 | `releaseTimeMillis`（ms） | 已采集 | 保持 |
| rank_type | 作品类型 | `worksRankType` | 已采集 | 保持 |
| product_name | 带货商品 | `productName` | 已验证 | **补齐**（卡片显示） |
| contains_paid | 是否含付费 | `containsPaid` | 已验证 | **补齐** |
| quality_hot/quantity_hot/quality_and_quantity_hot | 优质/高量标签 | 同名字段 | 已验证 | **补齐** |
| first_industry_name | 一级行业 | `firstIndustryName` | 已验证（样本“未知”） | **补齐**（原值） |
| 公开作品页 | 可点击作品页 | `webpUrl` → `video.kuaishou.com/short-video/...` 打开为 `{"result":2}` | **暂无法确认/不提供** | 不构造、不展示跳转 |
| 视频文件地址 | `url`（mp4 CDN） | 可播放文件，不是公开作品页 | **平台专属** | 不展示为作品页；原始 JSONB 保留 |

### 5.4 受众画像 `audience`

原始 `fansPortrait`/`viewerPortrait` 已完整落库；维度（18）由前端解析，不新增合同字段。

| 原始维度 | 页面含义/展示 | 状态 | 本轮 |
|---|---|---|---|
| `sexPercentage` | 性别分布（占比/TGI） | 已入库 | **前端维度表** |
| `agePercentage` | 年龄分布 | 已入库 | **前端维度表** |
| `areaPercentage` | 地域分布（省份） | 已入库 | **前端维度表** |
| `cityPercentage` | 城市分布 | 已入库 | **前端维度表** |
| `interestPercentage` | 兴趣分布 | 已入库 | **前端维度表** |
| `activityPercentage` | 活跃度 | 已入库 | **前端维度表** |
| `mobileBrandPercentage` | 手机品牌 | 已入库 | **前端维度表** |
| `mobilePricePercentage` | 手机价格 | 已入库 | **前端维度表** |
| `nineMajorGroupsPercentage` | 九大人群 | 已入库 | **前端维度表** |
| `areaTopWithRadio` | 地域 TOP 占比 | 已入库 | **前端维度表** |
| `areaTopWithPermeation` | 地域 TOP 渗透 | 已入库 | **前端维度表** |
| `cityLevelPercentage` | 页面“城市等级”相邻字段；原值标签为城市名，语义未完全确认 | 已入库 | 暂按平台原字段展示，不强行命名为“城市等级” |
| `mobilePercentage` | 设备分布（样本空） | 已入库 | 空→暂无数据 |
| `trend/trendData/trendDiff/trendDiffData/minFansNumberOfTrend` | 趋势结构（样本空） | 已入库 | 原样保留，不展示 |
| 星图 `audience_distributions` | 星图连接用户画像 | — | **不适用**（不同口径） | 不映射 |

### 5.5 履约与带货（本轮只调查，不采集）

| 页面章节 | 字段/路径 | 业务含义 | 状态 | 本轮 |
|---|---|---|---|---|
| 看履约 | `post/video/business/report/get`: `acceptOrderRate`、`completeOrderRate`、`completeOrderCnt`、`workedIndustriesOrderProps/ViewProps` | 接单率/完单率/订单数/行业分布 | 平台存在、账号可见 | **不启用**：需新增模块与完成判定策略；后续卡片 |
| 看带货 | `star/queryCommerceInfo`: `starCommerceInfo30.videoCnt/videoGpm/videoOrderCnt/videoGmv/videoAvgUnitPrice/videoItemVisitCnt/videoItemImpressionCnt/videoCvr` + `starCommercePhotoInfos[]` | 商品曝光/访问/转化率/GMV/订单/GPM/客单价/带货作品 | 平台存在、账号可见 | **不启用**：同上 |
| 信用分 | `baseInfo.data.starCreditScore` | 信用分 | 平台存在（样本空） | 后续（履约模块） |
| 风险等级 | `starRiskLevel` | 风险 | 平台存在 | 不采集 |

## 6. 生命周期能力矩阵

| 能力 | 星图 | 聚星现状 | 本轮 |
|---|---|---|---|
| 创建/取消 | 支持 | 支持 | 回归 |
| 继续/重试/补采 | 支持 | 命令平台无关；补数量受单页限制 | 分页后合成/历史证据；不重写 |
| 手动更新 | 支持 | 422 `KUAISHOU_JUXING_UPDATE_NOT_SUPPORTED`；缺 homepage 模板 | 后续 |
| 定时更新 | 支持 | 不入册 | 后续 |
| 历史快照 | 有读模型 | 不可变快照写入；无库级历史 UI | 本轮验证快照；UI 后续 |
| 库级报价/作品观测/精选 | 支持 | 422 not-applicable（数据部分在 JSONB） | 后续 |
| F06 精选 | 支持 | 合同级不适用 | 保持不适用 |
| 执行单元/账号/Profile | 已验证 | 已验证 | 只回归 |

## 7. 本轮实施决策与影响

1. **合同 v2**：`juxing-video-creator-stage-c-v2` / `juxing-video-square-stage-c-v2` / `juxing-browser-v2`。旧 v1 任务只读、不再续跑（现有版本边界）；阶段 C GO 继续针对 v1 证据有效。
2. **分页边界=2**：第 2 页真实证据充分；第 3 页只读观察但不写入可执行边界；target 22 只需第 2 页。`page_fetch_continuous_verified=false`。
3. **筛选开放**：关键词、内容类型 38 一级类目、粉丝量级、地域 34 省/352 市、三档报价（单档）。其余平台条件只记录。
4. **地域映射**：以 `address/list` 的 `provinceCode/cityCode` 为合同 `region_tree` 的 value；省级选择展开为全部 cityCode；城市选择为单 cityCode。北京 1101、河北 12 个 code、石家庄 1301 已核验。
5. **报价映射**：`priceType` 11/12/13；`starMinPrice/starMaxPrice` 平台整数=元×1000；三档互斥。
6. **内容类型映射**：`starTagV2` 38 个一级类目；`contentTagIdList` 使用父 id + 全部 subIds；母婴亲子 676/740-743、美妆 670/707-712 已核验；其余按同一结构生成。
7. **不新增模块**：履约/带货数据虽可用，但新增模块会改变完成判定；本轮按批准范围只扩展既有四模块，新增字段全部允许 NO_DATA。
8. **前端**：画像维度表、作品封面/标签、主页链接、失败原因、任务条件摘要；不把聚星指标塞进星图 CPM/CPE 语义。
9. **无数据库 Schema 变更**：全部复用 `platform_creators.projection` + `creator_snapshots.payload`；不新增表/列/迁移。

## 8. 实施顺序

1. 合同 v2（分页/筛选/字段/checkpoint_version）→ 合同与 Adapter 单测；
2. Adapter 分页与筛选映射（合同驱动）→ 合成/Engine 测试；
3. 详情字段（四模块）→ 合同字段完整性测试；
4. 前端表单/详情/画像/作品/失败原因/条件摘要 → 组件测试；
5. 达人库读模型新指标 → 集成测试；
6. 全量自动回归 → 新隔离栈 MCP 回归 → T1/T2/T3 真实任务；
7. 回填本文件“本轮结果”与最终回归报告。

## 9. 本轮结果

### 9.1 分页

- 合同已开放第 2 页（`page_fetch_max_verified=2`），第 3 页起 fail closed；旧 v1 任务只读、不续跑。
- Adapter 每页重建完整筛选体，保留 cursor；`prepare` 对已有第 2 页 cursor 返回可续跑，`search` 校验页号/范围/会话；空页与 total 不一致抛页面契约异常，不伪装耗尽。
- 自动化：新增 15 条 adapter v2 专项（含第 2 页、空页、超界、续跑、筛选映射），全部通过；T1 只使用第 1 页（五项筛选后 10 个候选，耗尽）。
- 真实分页：T2 最终任务 `56efbba5-...`（keyword+content type，target=22）**COMPLETED 22/22/22**；`visited_cursors=[None,"2"]`，40 个候选（两页各 20），22 creators/snapshots，无第 3 页。T2-偏差 16/22 只到第 1 页，仅透明历史记录。
- 结论：第 2 页代码、单测、只读真实请求与真实端到端 22/22/22 **全部通过**；阶段 D-0 的分页条件关闭。
- 子账号选择：首次 T2 的 0/22 定位为「正常子账号选择页 + 过期星图 verification 状态未清理 + 账号选择未识别/未通知」，已最小修复并补齐 `ACCOUNT_SELECTION_REQUIRED` 提醒/人工接管/超时；见专项诊断。

### 9.2 筛选

- 38 个内容类目、6 个粉丝预设/自定义、34 省/352 市、三档报价（单档互斥）全部进入合同；Adapter 从合同映射，无硬编码猜测。
- 前端全部可操作，表单条件摘要与任务详情摘要显示内容类型/粉丝/地域/报价；星图表单/摘要不受影响。
- 真实 T1 使用「母婴 + 母婴亲子 + 10万–100万 + 北京 + 21-60秒上限10000元」完成 3/3，3 位粉丝均在区间、条件摘要五项完整；这是本轮最强的组合筛选证据。
- 自动化覆盖合同/Adapter/Engine/前端；纯关键词、内容类型、粉丝、地域、报价的请求体均有单测，未知筛选显式 `UNSUPPORTED_FILTER`，报价互斥显式 `INVALID_FORM`。

### 9.3 详情字段

- 既有四模块扩展为 basic 18、spread 31、works 1 个结构化项（item 增加 6 个键）、audience 2 个原始画像；未新增模块、未改完成判定、无 Schema 变更。
- 真实 T1 三位达人四模块均为 18/31/1/2，profile/pipeline complete；gender、profile_url、content_form_labels、platform_identity、public_settlement、分位数、环比、访客/深度访客、作品封面等有真实值；recent CPM/CPE、商业作品字段为 NO_DATA，未伪 0。
- 前端展示：性別/主页/内容形式、报价原价/有效期、传播新字段、作品封面/标签、受众维度表（label/占比/TGI）+ 原始结构；`cityLevelPercentage` 原始标签实为城市名，未误标为城市等级。
- 巨量星图字段/详情/F06 未改；真实 T3 待终态确认。

### 9.4 未启用/受限

- 履约/带货模块：平台可读，但新增模块会改变完成判定；本轮按批准范围不新增，字段/路径见 5.5。
- 第 3 页及以后：只读观察，不进入执行合同。
- 聚星更新/补采/定时：不在本轮范围；continue/backfill 平台无关语义保留，页级停止受合同边界保护。
- 库级历史/报价/作品观测 UI：未新增；快照/投影已落库。
- Windows、生产 Flag、正式业务库：未执行/未变更。

### 9.5 证据

- 合同：`contracts/kuaishou_juxing.verified.json`（v2，`require_enabled(live=True)` 通过）。
- 自动化：后端单元+合同 403；隔离集成 118/1 skipped；E2E 14；前端 103 + lint/build；adapter v2 15。
- 真实 T1：`f1f62c78-c0e9-495c-8863-08a8d56a6e0f` COMPLETED 3/3/3，四模块 18/31/1/2；私有截图/报告 `.runtime/kjx-full/regression/mcp/`。
- 真实 T2 最终：`56efbba5-...` **COMPLETED 22/22/22**，第 2 页。
- 真实 T2-偏差：`7ec6a121-...` PARTIAL_COMPLETED 16/22，`SEARCH_EXHAUSTED`；不作分页证据。
- 真实 T2-批准历史：`50cccb72-...` 0/22，专项定位后修复；见专项诊断。
- 真实 T3：首次 `516a9e3b-...` 平台安全验证超时；同范围重试 `ef1ed66e-...` **COMPLETED 1/1/1**。
- 最终 MCP 回归：**19 PASS / 0 FAIL**；后端单元+合同 404、前端 104。
- 文档：[功能完成证据](../evidence/KJX-01-feature-completion.md)、[全量回归报告](../evidence/KJX-01-full-regression.md)、[全量测试用例](../evidence/KJX-01-full-test-cases.md)。
