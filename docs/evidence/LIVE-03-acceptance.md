# LIVE-03 验收记录

执行日期：2026-11-05（Asia/Shanghai）  
环境：本机开发栈；API `127.0.0.1:8000`、Web `127.0.0.1:5173`；schema=21；Temporal `127.0.0.1:57233`。  
执行单元：`unit-local-mac-02`（巨量星图）；未新增单元/队列/迁移。  
真实浏览器：Playwright MCP + 系统 Chrome；产品 UI 创建任务，采集 Worker 使用单元真实 Chrome profile。

## 1. 强制「时尚」真实任务

| 项 | 值 |
|---|---|
| 任务 ID | `803e59eb-2deb-460e-b1e7-ed70db5663a2` |
| 平台/场景 | 巨量星图 / 直播广场（live_square） |
| 筛选条件 | 内容类型 = 时尚（`live_content_type=["fashion"]`，请求映射 `live_tag_content_v2_level_one=[10719]`，见 LIVE-02F 调查） |
| 关键词/达人 ID | 空（仅筛选条件创建） |
| 目标数量 | 2 |
| 发现候选 | 20 |
| 有效入库 | 2 / 2 |
| 资料完整 | 2（`pipeline_complete=true`） |
| 快照 | 2 位达人各 1 份 `creator_scene=live_square` 快照 |
| 最终状态 | **COMPLETED**，failure_reason=null |
| 创建方式 | Playwright MCP 操作产品 UI：登录 → 创建任务 → 巨量星图 → 直播广场 → 勾选时尚 → 目标 2 → 提交 |
| 任务页证据 | 内容类型「时尚」、目标 2、有效 2、资料完整 2；截图 `assets/LIVE-03/fashion-task.png` |

首轮任务 `863ae3c5-7905-4ebb-b318-bc356da39393` 也为 COMPLETED 2/2；该轮直播间列表在类型切换后仅取到 11 场，暴露了列表状态问题。修复为「进入直播分析后先采集默认列表，再切换类型」后，用 `803e59eb…` 重跑，列表取得 **96 场/10 页**（与真实页面一致）。

## 2. 字段核对（样本 `7620474284346966052` 倩倩美丽课堂）

真实页面值来自 `.runtime/live03/` 的只读调查（2026-11-05）；DB 值来自 `creator_snapshots`；API 来自 `GET /api/creator-library/{id}?creator_scene=live_square`；UI 来自直播详情截图。

### 2.1 基本资料

| 字段 | 源平台/页面 | DB 快照 | API | UI | 结论 |
|---|---|---|---|---|---|
| 昵称 | 倩倩美丽课堂 | `basic.nickname` | 同 | 同 | PASS |
| 头像 | 抖音头像 URL | `basic.avatar_uri` | 同 | 头像显示 | PASS |
| 性别 | 页面未显示（无值） | `basic.gender=NO_DATA` | NO_DATA | 暂无数据 | PASS（缺失去向正确） |
| 地域 | 暂无地域信息 | province/city NO_DATA | NO_DATA | 暂无数据 | PASS |
| 粉丝数 | 21w | `basic.followers` 210000（近似） | 210000 | 210,000 | PASS（近似语义保留） |
| 内容类型 | 时尚 | `basic.content_type=时尚` | 同 | 时尚 | PASS |
| 内容标签 | live_labels_v2 值 | `content_tags` | 同 | 内容标签 | PASS |
| 商单类型 | 内衣裤袜/婴童用品/彩妆… | `business_order_types` 3 项 | 同 | 同 | PASS |
| 抖音号 | 51307191014 | `douyin_id=51307191014` | 同 | 同 | PASS |
| 星图 ID | 7620474284346966052 | `platform_creator_id` | 同 | 同 | PASS |
| 介绍 | 页面/接口无（self_intro 空） | `introduction=NO_DATA` | null | 暂无介绍 | PASS（另一达人 `7507927976575664191` 有介绍并 COLLECTED） |

### 2.2 直播服务报价

| 服务 | 源页面 | DB | API/UI | 结论 |
|---|---|---|---|---|
| 品牌营销专场（按天） | ￥6,000 | `per_day`, price=6000, unit=元/天, CNY | 同 | PASS |
| 品牌营销专场（按小时） | ￥1,000 | `per_hour`, price=1000 | 同 | PASS |
| 电商带货专场/拼场 | 该达人未返回 | 未生成 | 空态 | PASS（不补造） |
| 附件达人四类服务 | 品牌营销按天/按小时、电商带货专场、电商带货拼场 | 任务 `49edcc08…`：`per_day/per_hour/per_hour/per_goods`，单位 元/天/小时/商品 | 同 | PASS（附件达人补充） |

### 2.3 数据概览（分类型/周期/口径）

| 指标 | 源页面 30 天（不限，排除营销） | DB `period_30_flow_1_star_0` | 源页面 90 天 | DB `period_90_flow_1_star_0` | 结论 |
|---|---:|---|---:|---|---|
| room_cnt | 30 | 30 | 96 | 96 | PASS |
| 平均观看人数 | 7,455 | 7455 | 1.3w | 13087 | PASS |
| 平均观看人次 | 8,302 | 8302 | 1.5w | 14524 | PASS（与人数分开） |
| ACU | 270 | 270 | 539 | 539 | PASS |
| PCU | 1,099 | 1099 | 3,948 | 3948 | PASS |
| 粉丝观看占比 | 10.1% | 0.101 | 9% | 0.0896 | PASS |
| 场均涨粉数 | 231 | 231 | 528 | 528 | PASS |
| 场均评论率 | 1.4% | 0.0138 | 1.7% | 0.0165 | PASS |
| 场均点赞率 | 0.7% | 0.0067 | 1% | 0.0104 | PASS |
| 平均看播时长 | 1分22秒 | 82s | 1分35秒 | 95s | PASS |
| 场均 CTR | 13.9% | 0.1392 | 13.3% | 0.1326 | PASS |
| 小风车 CTR | 13.9% | 0.1392 | 13.3% | 0.1326 | PASS |
| 小手柄/小雪花 CTR/CVR | 页面 `-` | 缺少键 → NOT_PROVIDED | 同 | 同 | PASS（不伪造） |
| 带货表现 | 3 / 0 / 0 / 0 | 同（区间/值） | 同 | 同 | PASS |
| 游戏直播 | 不可用（candidates=false，页签 disabled） | `overview.game=NO_DATA` | 同 | 同 | PASS（不请求） |
| 电商/其它 | 有数据 | `overview.ecom/other` 独立 | 有数据 | 独立 | PASS |

- 周期：`overview.general/ecom/other` 均有 30/90 两个 period；修复前默认 90 导致只采 90，已修复为两周期。
- 口径：`flow_type=1`（排除营销流量开）为默认；`only_star_order=true` 口径在样本中另存为 `period_30_flow_1_star_1`（room_cnt=28、ACU=283 等，见 DB）。
- 替代 flow=0 口径：手动更新 `b334d954-3fd0-4cd9-b245-7c2df538cdd1` 仍未使持久 profile 的开关产生可关联的 flow=0 响应；最终代码在未取得 flow=0 时写入 `overview.meta.not_captured=flow:0:alternate-not-captured`；本次最终快照 `b334d954…` 产生于该披露补丁之前，meta 仅列出 ecom/other 的未采组合。平台参数映射已在调查中实测（开关开=1、关=0），但本系统未保存 flow=0 数值；列为**受限项**，不伪造。
- 区间：`avg_gmv_range`/`avg_ecom_product_price_range`/`avg_gpm_range` 保存 raw + min/max + bound，未取平均。

### 2.4 直播分析

| 项 | 源页面 | DB/API | 结论 |
|---|---|---|---|
| 直播月历 | 2026-11：1 场；无场次时上月 | `analysis.general.calendar` 月份/日期/room_count | PASS |
| 当前月最高场观/最近一场 | 11-01 05:33，观看人次 5,522，ACU 108，PCU 186，评论率 1% | `highest_room/latest_room` 同 | PASS |
| 近15场 | 15 个原始点 | `analysis.general.latest.window=15`，series 原始值 | PASS |
| 直播间列表 | 近90天 96 场、10 页 | `analysis.rooms` 96 行，pages 1–10，total 96 | PASS |
| 场次字段 | 标题/开播/时长/观看人数/人次/ACU/PCU/评论/点赞/CTR/GMV | rows 内 metrics 全量 | PASS |
| 逐场类型 | 列表接口不提供 | latest 同 room_id 命中时登记；其余 NOT_PROVIDED + 原因 | PASS（限制披露） |
| 非星图商单 CTR | 「非星图商单，不做统计」 | NOT_PROVIDED + reason | PASS |
| 非带货直播 GMV | 「非带货直播，不做统计」 | NOT_PROVIDED + reason | PASS |
| 真实 0 | 页面 0% | COLLECTED 0 | PASS |

### 2.5 受众画像

| 项 | 源页面（粉丝画像） | DB/API | 结论 |
|---|---|---|---|
| 性别 | 男 19.6% / 女 80.4% | count 9588/39372，computed 19.58/80.42 | PASS |
| 年龄 | 完整体验 5 段 | `age` 5 项 | PASS |
| 全国省份 | 34 省份 | `province` 34 项 + top10 | PASS |
| 城市 | TOP50 | `city` 50 项 + top10 | PASS |
| 城市等级 | 6 类 | `city_level` 6 项 | PASS |
| 兴趣 | 40 类 | `interest` 40 项 | PASS |
| 八大人群 | 8 类 | `eight_crowds` 8 项 | PASS |
| 设备 | 品牌分布 | `device` 7 项 | PASS |
| 分类型 | 不限/电商/其它 | 独立字段，计数不同 | PASS |
| 观众画像 | 页面可选；单元持久 profile 下切换控件不稳定 | `audience.*.user=NO_DATA` | **受限**（非平台无数据；未伪造） |

## 3. 手动更新与失败回退

- 对已采集达人 `9d13d41b-e337-4741-b99c-f8e9aaf6f9ec`（7620474284346966052）执行直播手动更新：
  - `6aa27e15-9633-4241-aafc-95b2ffd2829c`：COMPLETED；新快照；所有模块 COLLECTED。
  - `b334d954-3fd0-4cd9-b245-7c2df538cdd1`（时尚任务后）：COMPLETED；新快照 561KB；直播间列表 96 场/10 页；30/90 双周期；flow=0 未取得（该快照早于 not_captured 披露补丁，meta 未列 flow:0）。
- 验证：新快照追加、旧快照保留、`creator_live_current` 更新、不写 `creator_update_schedule`、不写视频 projection/current。
- 失败回退：集成测试 `test_live_detail_reads_back_older_module_when_latest_failed` 通过；最新快照模块 FAILED 时详情返回旧模块 + `module_fallbacks`。

## 4. 兼容性回归

| 项 | 结果 |
|---|---|
| 71 位直播目标 | API 返回 422 `live target_count exceeds 70` |
| 70 位目标 | 接受为 202（测试后立即取消，未执行 70 全量） |
| 短视频 | 未修改短视频 Adapter/契约；后端 620 passed/1 skipped、前端 123 passed；复用 LIVE-02 阶段三真实短视频证据 |
| 聚星直播 | 未修改聚星 Adapter/契约；集成测试（含聚星 live）通过；读时回退同样适用 |
| 任务中心/执行单元 | 未修改；任务状态与列表正常 |
| 历史快照 | 只读保留；新模块只追加新快照 |

## 5. 自动化结果

- 后端单元 + 契约：485 passed。
- 后端集成：135 passed / 1 skipped（需要 `XINGTU_TEST_DATABASE_URL=xingtu_test`）。
- 前端：123 passed；`tsc -b` 通过；`vite build` 通过（chunk 体积警告为既有）。
- 真实任务：见 §1。

## 6. 证据文件

- 表单/任务页：`docs/evidence/assets/LIVE-03/fashion-form.png`、`fashion-task.png`
- 直播详情整页：`docs/evidence/assets/LIVE-03/live-detail.png`
- 调查：`docs/evidence/LIVE-03-live-detail-investigation.md`
- 字段差异：`docs/evidence/LIVE-03-field-diff.md`
- 原始私有响应：`.runtime/live03/`（gitignored，不含凭据）
- 任务 ID：`803e59eb-2deb-460e-b1e7-ed70db5663a2`（时尚强制）、`b334d954-3fd0-4cd9-b245-7c2df538cdd1`（手动更新）、`49edcc08-aa00-4d0a-a369-0fa5ff3105e1`（附件达人补充）、`863ae3c5…`（首轮时尚）

## 7. 结论

当前为 **CONDITIONAL GO**：

- 核心字段、分类型/周期/口径（默认排除营销口径）、真实时尚任务、入库/API/前端链路已验证。
- 受限项：观众画像（`live_crowd_type=1`）在单元持久 profile 下切换控件不稳定，`audience.*.user` 为 NO_DATA；粉丝画像按类型已完整采集。逐场直播类型仅 latest/detail 可见时登记，其余 NOT_PROVIDED 并披露。
- 受限项：flow=0 替代口径未保存（`not_captured` 已披露）；观众画像 `live_crowd_type=1` 未保存（粉丝画像按类型已完整采集）。两项均属采集/UI 切换限制，不是平台无数据，未伪造通过。
