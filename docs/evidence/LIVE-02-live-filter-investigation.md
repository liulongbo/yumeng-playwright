# LIVE-02F 直播广场筛选真实调查

状态：进行中（2026-11-05）  
环境：本机开发栈，Playwright MCP + 系统 Chrome，隔离 storage_state；星图账号 `ID: 1807978499337419`，聚星子账号 `60821564`。  
原始证据：`.runtime/live02filters/`（gitignored，私有原件）；本文只保留脱敏摘要与真实请求字段。

## 1. 巨量星图 `/ad/creator/market/live`

### 1.1 入口与默认条件

- 页面标题 `直播广场 - 巨量星图`；默认已选条件「达人报价：品牌营销专场(按小时)」。
- 「清空」按钮可清除默认条件；清除后请求 `attribute_filter` 为 `null`。
- 筛选控件位于「匹配度」「性价比」分组；受众画像和个人认证控件带 `disabled` 样式类，但实际可打开并操作（不能仅凭类名判定不可用）。

### 1.2 内容类型「时尚」

- 点击「内容类型」行内「时尚」会打开该分类的子菜单：`全选`、`时尚推荐`。
- 选择 `全选` 后 chip 显示 `内容类型：时尚-全部`；请求新增：
  - `attribute_filter[].field.field_name = live_tag_content_v2_level_one`
  - `field_value = "[10719]"`
- 选择前后列表首屏 `star_id` 完全不同；`total_count` 仍为平台上限 `10000`。
- 已核验：`时尚` 可作为一级分类整体筛选；子分类 `时尚推荐` 存在，但本次不单独展开。

### 1.3 达人画像

| 页面标签 | 真实选项 | 请求映射（已核验） | 状态 |
|---|---|---|---|
| 达人性别 | 全部/男性/女性 | `gender` = `1`（男）/`2`（女） | 已核验男/女 |
| 粉丝量级 | 全部/1000w以上/500w-1000w/300w-500w/100w-300w/10w-100w/10w以下/自定义 w-w/重置/确定 | `follower__ge`/`follower__le`，单位 w × 10000；100w-300w → `1000000`/`3000000` | 已核验预设；自定义待验证 |
| 个人认证 | 全部/个人/企业/机构/经营/特殊 | `cert_types` = `0`/`1`/`3`/`4`（个人/企业机构/经营/特殊；未观察到 2） | 已核验 0/1/3/4 |
| 所在地域 | 省/市多选级联；省份选择 chip「共21项」，请求只发 `province` | `province` = `["广东省"]`；城市选择 `city` = `["深圳市"]`（JSON 数组字符串） | 已核验省、市 |

### 1.4 受众画像

| 页面标签 | 弹窗维度/选项 | 请求映射（已核验） | 状态 |
|---|---|---|---|
| 直播间观众画像 | 观众年龄：18-23/24-30/31-40/41-50/大于50岁居多；观众性别：男性/女性占比大于50/60/70/80%；观众设备品牌：苹果/华为/小米/VIVO/OPPO；观众地域：一线/二线/三线/四线/五线城市居多；另有默认「观众八大人群-全部」chip | 年龄 `watcher_age_rate_most`=`[21]`；设备 `watcher_system_rate_most`=`[10]`；地域 `watcher_city_level_most`=`[13]`；男性占比>50% `live_watcher_gender_male_rate__ge`=`0.5` | 已核验四个维度首项；其余选项值/女性字段待补 |
| 粉丝画像 | 粉丝年龄/性别/设备品牌/地域，选项同上「粉丝」口径；默认「粉丝八大人群-全部」chip | 年龄 `fans_age_rate_most`=`[21]`；设备 `fans_system_rate_most`=`[10]`；地域 `fans_city_level_most`=`[13]`；男性占比>50% `fans_gender_male_rate_v2__ge`=`0.5` | 已核验四个维度首项；其余选项值/女性字段待补 |

说明：`直播间观众画像` 弹窗实际可打开并含四个维度；`disabled` 类名不代表功能不可用。`八大人群` 只作为默认「全部」chip 出现，未在弹窗中发现可操作控件，待二次确认。

### 1.5 直播间表现

| 页面标签 | 真实预设 | 请求映射（已核验） |
|---|---|---|
| 近期直播场次 | 全部/25以上/7-25/2-6/0-1/自定义/重置/确定 | `live_room_cnt_30d__ge` / `__le`；7-25 → `7`/`25` |
| 平均观看人数 | 全部/2500以上/500-2500/100-500/60-100/30-60/0-30/自定义/重置/确定 | `live_sn_watch_ucnt_avg_30d__ge` / `__le`；100-500 → `100`/`500` |
| 平均观看人次 | 全部/3000以上/500-3000/100-500/50-100/0-50/自定义/重置/确定 | `live_sn_watch_cnt_avg_30d__ge` / `__le`；100-500 → `100`/`500`（真实结果可为 0） |
| ACU | 全部/40以上/11-40/5-10/1-4/自定义/重置/确定 | `acu__ge` / `acu__le`；11-40 → `11`/`40` |
| PCU | 全部/200以上/51-200/21-50/11-20/1-10/自定义/重置/确定 | `live_pcu_30d__ge` / `live_pcu_30d__le`；21-50 → `21`/`50` |

重要：平均观看人数/人次使用 `live_sn_*`（星图商单口径），不能与详情「不限」口径混用；ACU/PCU 是独立指标，字段不同。

## 2. 磁力聚星 `#/star_plaza/live`

入口需带子账号：`https://k.kuaishou.com/?__accountId__=60821564#/star_plaza/live?__accountId__=60821564`。

### 2.1 内容分类

点击标签后 chip 显示 `内容分类：美妆-全部`；请求体新增 `contentTagIdList`，并切换 `pathSource=has_filter_live`。多选会追加数组项。

| 分类 | `contentTagIdList` 项 |
|---|---|
| 美妆 | `{"id":"670","subIds":["707","708","709","710","711","712"],"selectFirstLevelId":true}` |
| 美食 | `{"id":"673","subIds":["718","719","720","721","722","723","724"],"selectFirstLevelId":true}` |
| 时尚 | `{"id":"675","subIds":["735","736","737","738","739"],"selectFirstLevelId":true}` |

### 2.2 受众人群

前端配置（`/rest/web/conf/get` 的 `STAR_PLAZA_OPTIONS`）给出真实控件与选项：

| 页面标签 | 字段 | 选项来源 | 值 |
|---|---|---|---|
| 粉丝年龄 | `fansAgeList` | `FANS_AGE` | `18-23/24-30/31-40/41-49/50+`，对象含 `queryName/from/to` |
| 粉丝性别 | `fansGender` | `FANS_GENDER` | `MALE`/`FEMALE` |
| 粉丝设备 | `fansMobile` | `FANS_MOBILE` | `IOS`/`ANDROID` |
| 粉丝地域 | `fansCityPercentage` | `FANS_AREA` | 平台支持，但两级面板/占比映射本轮未完成，不登记 |
| 粉丝九大人群 | `fansNineMajorGroupsList` | `PORTRAIT_NINE_MAJOR_GROUPS` | 小镇青年/小镇中年/小镇老年/Z时代/都市蓝领/精致妈妈/新锐白领/资深中产/都市银发 |
| 观众年龄 | `viewerAgeList` | `PORTRAIT_AGE` | 同上年龄区间 |
| 观众性别 | `viewerGender` | `PORTRAIT_GENDER` | `男`/`女` |
| 观众设备 | `viewerMobileType` | `PORTRAIT_MOBILET_TYPE` | `IOS`/`ANDROID` |
| 观众地域 | `viewerCityPercentage` | `PORTRAIT_AREA_LEVEL` | 平台支持，但两级面板/占比映射本轮未完成，不登记 |
| 观众九大人群 | `viewNineMajorGroupsList` | `PORTRAIT_NINE_MAJOR_GROUPS` | 同上 |

界面弹窗还包含「占比：居多 / 自定义数值」。真实 UI 请求体已交叉验证：

- 粉丝年龄 `fansAgeList`：`[{"queryName":"18-23","from":"0.50","to":"1.00"}]`
- 粉丝性别 `fansGender`：`{"queryName":"FEMALE","from":"0.00","to":"1.00"}`
- 粉丝设备 `fansMobile`：`{"queryName":"IOS","from":"0.00","to":"1.00"}`
- 粉丝九大人群 `fansNineMajorGroupsList`：数组对象（同 `queryName/from/to`）

**限制**：粉丝地域/观众地域在真实页面上是「按省市 / 按城市等级 + 占比」的两级面板，不是简单下拉；本轮没有完成其请求体映射与可用性验证，因此契约**不登记** `area` 维度，前端不展示，避免把未验证能力呈现为可用。该限制在最终报告中标记「未完成/平台支持但本轮未实现」。

### 2.3 内容表现

| 页面标签 | 预设 | 请求字段（已核验） |
|---|---|---|
| 预期观看人数 | 不限/1000万以上/500万-1000万/300万-500万/100万-300万/10万-100万/10万以下/自定义万-万/重置/确认 | `liveExpectViewer: {min,max}`；100万-300万 → `1000000`/`3000000` |
| 最高在线人数 | 同上 | `liveMaxViewerMinNum` / `liveMaxViewerMaxNum`；100万-300万 → `1000000`/`3000000` |
| 预期CPM | 不限/100以上/50-100/30-50/10-30/5-10/5以下/自定义/重置/确认 | `expectCpmMinNum` / `expectCpmMaxNum`；30-50 → `30`/`50` |

`pathSource` 在有筛选时为 `has_filter_live`；无关键词且无筛选时为 `no_filter_live`；关键词+筛选的真实值待验证。

## 3. 当前限制 / 待补

1. 星图受众画像/粉丝画像除首项外的选项 → 请求值（年龄/设备/地域的 ID、性别女性字段）待补；当前实现可先按字段族 + chip 校验，选项枚举来自真实控件。
2. 星图粉丝量级「自定义」与各指标「自定义」边界、空边界处理待补。
3. 聚星 profile 请求体需要用一次真实 UI 选择交叉验证 `fansAgeList` 等对象结构（`queryName/from/to`）。
4. 聚星关键词+筛选组合的 `pathSource` 与 `userName` 兼容性待验证。
5. 星图「时尚推荐」子分类不单独支持；如后续需要再扩展。
6. 聚星粉丝/观众地域维度本轮未登记，前端不展示；不为不可用能力制造开关。

## 4. 真实请求与任务证据（2026-11-05）

| 平台 | 任务 ID | 条件 | 结果 |
|---|---|---|---|
| 星图 | `cafc1ce5-0d21-41ce-80a5-26ecc933f5ff` | 时尚，target 1，API | COMPLETED 1/1；checkpoint 首屏 20 个 star_id 与源平台时尚列表完全一致 |
| 星图 | `593cd747-6ff9-4710-b409-7f76c9e41d78` | 时尚，target 2，真实产品 UI | COMPLETED 2/2；任务详情显示「内容类型 时尚」，关键词空 |
| 星图 | `446e7a91-4fb1-493c-9885-0a8ecb7b9bfd` | 时尚 + 直播间观众画像 18-23，target 1，UI | COMPLETED 1/1；请求校验通过 |
| 星图 | `032badb3-ca90-4113-b28f-e73f5ebdccfd` | 时尚 + 女性 + 100w-300w + 个人 + 广东省，target 1 | COMPLETED 1/1；候选 9（组合真实收窄） |
| 星图 | `9c2fa9d3-d847-48b5-9570-efb0bf6b1400` | 时尚 + 深圳市，target 1 | COMPLETED 1/1 |
| 星图 | `d8a801be-5f29-4793-b6e8-67fc112a0eca` | 时尚 + 场次 7-25 + 平均观看 100-500 + ACU 5-10 + PCU 21-50，target 1 | COMPLETED 1/1 |
| 聚星 | `ad5a4749-3ed8-42d7-88e8-110df90913da` | 时尚，target 1，API | COMPLETED 1/1；首屏 20 个 userId 与源平台时尚列表完全一致 |
| 聚星 | `472e7739-da7e-4db2-ad4d-baea9c926a79` | 时尚，target 2，真实产品 UI | COMPLETED 2/2；任务详情显示「内容分类 时尚」，关键词空 |
| 聚星 | `e5966e90-5e95-4db5-9a72-f87c001c2ad1` | 时尚 + 粉丝画像 18-23，target 1，UI | COMPLETED 1/1；任务详情显示「粉丝画像 粉丝年龄-18-23岁居多」 |
| 聚星 | `2d3e9b38-ba98-41cd-9e9b-c5521c2072f3` | 时尚 + 粉丝年龄/性别/设备 + 预期观看 + CPM，target 1 | COMPLETED 1/1；Adapter 实际 body 见验收报告 |
| 聚星 | `bed7239a-2856-4421-9869-a549078d15ba` | 时尚 + 粉丝九大人群 精致妈妈，target 1 | COMPLETED 1/1 |
| 聚星 | `46cba027-072e-4850-9dc8-ecf9f36659e1` | 时尚 + 粉丝地域（旧实验值） | PARTIAL 0；地域维度已从契约移除，保留为限制证据 |
