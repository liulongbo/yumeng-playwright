# FILTER-01 巨量星图筛选字段与能力证据（脱敏）

日期：2026-10-14（页面读取与交互）  
执行单元：`unit-local-mac-02`  
绑定账号：`ID: 1807978499337419`  
入口：`https://www.xingtu.cn/ad/creator/market`

本证据不保存 Cookie、请求头、鉴权令牌、完整响应体或个人身份信息。会话以 `.runtime/profiles/unit-local-mac-02` 打开；私有快照根为 `.runtime/profiles`。

## 控件与选项

背景信息：达人性别（男性/女性）、所在地域（二级多选级联）、学历（大学生/硕士生/博士/留学生）、黄 v 认证（美妆创作者/体育创作者/媒体人或主持人/科技创作者/运动员）。受众画像：连接用户数（连接、了解、兴趣、喜欢、追随五个独立区间，`0–100w`）、粉丝量级（六个预设及 `0–5000w` 自定义）、观众画像、粉丝画像。两类画像均含年龄、性别、设备品牌、城市级别、八大人群；观众与粉丝画像双向互斥。

画像枚举及平台值已写入 `contracts/douyin_xingtu.verified.json` 的 `xingtu-ad-creator-square-v2`：年龄 `21–25`，设备 `10/26/27/28/29`，城市级别 `13–17`，八大人群 `58/60/55/53/57/59/56/54`。性别阈值为男女各 `50%/60%/70%/80%`。

## 地域树

通过可见“所在地域”控件对应的 Vue 级联组件只读取得：34 个省级节点、452 个二级节点。注册表保存页面当时返回的完整树，不以通用行政区划包推测。香港、澳门无二级节点；台湾为台北市、新北市、桃园市、台中市、台南市、高雄市、其他。复核断言：`province_count=34`、`child_count=452`、北京市二级节点 16 个且包含朝阳区。

## 最终请求字段

- 达人性别：`gender=1/2`。
- 地域：整省为 `province`，具体市/区为 `city`，值为 JSON 数组字符串。
- 学历与黄 v：分别生成独立的 `persona_tag_level_one` 条目；值为 `110213/110211/110212/110214` 与 `110201/110203/110207/110210/110220`。
- 连接五阶段：`link_link/l/i/n/k_cnt_by_industry__ge/le`；页面 `w` 换算为实际人数。
- 粉丝量：`follower__ge/le`；页面 `w` 换算为实际人数。
- 观众画像：`watcher_age_most_new`、`watcher_gender_male/female_rate_v2__ge`、`watcher_device_brand_most_new`、`watcher_city_level_most_new`、`link_crowd_profile`。
- 粉丝画像：`fans_age_rate_most`、`fans_gender_male/female_rate_v2__ge`、`fans_system_rate_most`、`fans_city_level_most`、`fans_crowd_profile`。

页面每次选择都会发起中间搜索。代表性组合（关键词、四项背景信息、连接区间、粉丝量级、一种画像）最终请求共存；因此实现只在最后统一关键词搜索时建立响应捕获窗口。平台固定 `price_by_video_type__ge=0` 可存在，其他未计划业务筛选必须拒绝。

## 已知差异与边界

连接用户输入框占位文本出现 `99999`，但实时组件 `maxNumber` 与原生 `max` 均为 `100`，本能力版本按有效组件约束 `100w`。粉丝自定义上限实测为 `5000w`。页面或枚举漂移时必须发布新能力版本，不静默沿用。
