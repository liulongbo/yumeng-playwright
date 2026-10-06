# AUTO-01 达人完整资料与连续分页实施证据

日期：2026-10-06（Asia/Shanghai）。范围：AUTO-01 主卡，联动 F04/F05。

## 产品结果与当前状态

- 已将达人资料从 9 个基础字段扩展为 6 个业务模块、61 个结构化字段：基础身份、商业报价、传播能力、种草能力、履约能力、转化与本地销售。
- 已实现主页打开前同时注册多模块响应观察，解决“页面已返回，但模块观察器安装太晚”造成的丢字段。
- 已新增 `structured` 字段值，多条报价、区间、分布、层级和复合指标保持 JSON 结构；`0`/`false`/空数组不会在解析时丢失或被改写成“无数据”。
- 已实现连续页码请求能力，可在真实证据开启后不再使用固定最大页码；正式合约仍保留第 2 页上限，因为第 3 页真实复核被账号偏移中断，未伪造证据开启。
- 已增加正常扫描连续两页无新 ID 停止保护，停止原因为 `SEARCH_NO_PROGRESS`，不会写成“平台已耗尽”。游标过期后的已知前缀重扫予以受控例外，到达旧前沿后恢复正常判定。

## Creator Field Matrix（实施版）

| 业务模块 | 巨量星图原始来源 → 系统字段 | 当前实现 | 产品口径待核对 |
|---|---|---|---|
| 基础身份 | `id/nick_name/avatar_uri/follower/gender/city/province/mcn_name/content_theme_labels` → 既有 9 字段 | 已采集并持久化 | 性别编码展示名 |
| 基础身份 | `creator_type/author_type/industry_list/tags_author_style/sec_uid/unique_id` → `creator_type_raw/author_type_raw/industry_labels_raw/content_style_labels_raw/douyin_sec_uid/douyin_unique_id` | 已登记、结构化保存 | 类型编码、行业层级与风格标签口径 |
| 商业报价 | `get_author_marketing_info.price_info[]` → `cooperation_offers` | 每条报价的价格、原价、折扣、开放/在线状态、视频/任务类型整体保存，不互相覆盖 | 币种、`video_type/task_category` 页面名称 |
| 商业行业 | `industry_tags` → `marketing_industry_tags` | 已结构化保存 | 行业层级含义 |
| 传播能力 | `play_mid/interact_rate/play_over_rate/avg_duration/like_avg/comment_avg/share_avg` → 播放中位数、互动率、完播率、平均时长/赞/评/享 | 已登记原值及同行超越结构 | 周期、比例缩放、时长单位 |
| 传播成本 | `expect_cpm/expect_cpe/sales_expect_cpm` → 预期 CPM/CPE | 区分视频时长的平台结构已保留 | 币种、周期、视频时长口径 |
| 商业传播 | `vv/sn_vv/cpm_20_60/cpm_60/cpe_20_60/cpe_60` → 6 个商业指标 | 已分字段保存 | `sn_*` 平台展示名与成本单位 |
| 种草能力 | `avg_a3_incr_cnt` → `a3_increment`；看后搜人数/比例、个人页看后搜、`search_word_ctr` → 6 个指标 | 已登记并保留原值 | 周期与比例缩放 |
| 种草链路 | `author_link_struct.link_struct` → `seeding_link_structure` | 层级值、占比、同行中位数及排名保持原结构 | 1—5 层级的业务名称 |
| 履约能力 | `credit_score/new_credit_score/order_cnt/process_order_cnt/max_process_order_cnt/message_reply_rate` → 6 个履约字段 | 已分字段保存 | 新旧信用分口径、回复率缩放、订单周期 |
| 合作行业 | `industry_order_distribution/industry_vv_distribution/order_experience_industries` → 3 个行业分布 | 数组/多层对象不转文本 | 平台分布字符串编码 |
| 转化能力 | `gpm_range/avg_sales_amount_range/component_click_cnt_range/component_click_rate_range/related_cpc_range/rec_product_cnt/rec_product_price_range` → 7 个区间/计数字段 | 已按平台原值保存，未猜测枚举 | 区间枚举、币种、周期 |
| 相关视频 | `related_video_cnt/video_vv_median` → 相关视频数/播放中位数 | 已结构化保存 | 周期 |
| 本地销售 | `author_local_sales_performance.overview` → `local_sales_overview` | 订单、销量、GPM 等整体保存，真实 0 保持为 0 | 周期、币种 |
| 个人介绍 | 未找到可靠来源 | 未实现，明确标记待确认 | 不用 `mcn_introduction` 伪造 |
| 粉丝性别/年龄/地域 | 尚未取得画像分布响应 | 全局 coverage gap | 数据源待确认 |
| 创作能力 | 创作能力页未完整触发 | 全局 coverage gap | 数据源待确认 |

`contracts/profile_requirements.json` 已与 6 个已登记模块的 61 个字段对齐，但 `inventory_verified=false`。这表示开发清单已补齐，不表示含义/单位/周期已经当前账号实测验收。

## 自动化验证

- `make lint && make format-check && make typecheck`：通过（ruff 无问题，38 个文件格式正确，mypy 17 个源文件无错误）。
- `pytest backend/tests/unit backend/tests/contract`（沙箱外本地 Chromium）：首轮 130 项中 129 通过，暴露初始多模块的默认绑定未合并；修复后全量 **130 passed in 32.67s**。
- PostgreSQL 集成首轮在沙箱内因本地 TCP 被拒绝，未进入断言；沙箱外运行 52 项，50 通过。其中 1 项是本次新增的无进展阈值与既有游标过期重扫语义冲突，已修复；另 1 项为本轮未修改的 BrowserHost 历史导航次数断言，不扩大范围修复。最终对范围内用例复跑：**52 passed, 1 deselected in 118.12s**。
- 新增的 Page 2 单达人失败 → Page 3 继续用例：目标 4 位，每页 2 位；Page 2 一位失败后，最终保存 Page 1 两位、Page 2 一位和 Page 3 一位，4 份快照均存在，定向复测 1 passed。

## 真实平台复核

1. 首次运行中，脱敏结构报告显示页面为目标子账号 `ID: 1865332309937515`；Page 1 和 Page 2 均返回 20 位、`pagination.page=1/2`、`has_more=true`，两页 ID 集合 SHA-256 摘要不同。
2. 首轮的 Page 3 未发出：研究工具把 Page 2 的请求覆盖了内存中的 Page 1 模板，已修复为只保留 Page 1 模板。该工具失败不能作为 Page 3 平台证据。
3. 同轮主页观察再次看到基础、报价、传播、种草、履约、转化与本地销售端点均为 HTTP 200，证明新模块来源仍存在；该轮是结构调研，不是新合约的数据库落库验收。
4. 修复工具后重启项目独立 Chrome，账号门槛返回 `ACCOUNT_MISMATCH:WRONG_ACCOUNT`。测试已立即停止，没有修改子账号选择、Cookie 或登录逻辑。

## 未完成项与解除条件

- 需人工在项目独立 Chrome 中选择/登录 `ID: 1865332309937515`。
- 随后重跑 Page 1→2→3，Page 3 真实成功后才可将正式合约从 `page_fetch_max_verified=2` 切换为 `page_fetch_continuous_verified=true`。
- 用新合约采集一位资料较完整达人，核对页面名称、单位、周期、编码后查询数据库快照。
- 粉丝画像、创作能力和个人介绍仍为“数据源待确认”，未伪造。

## 合约版本兼容性

- 新任务在合约启用后使用 `xingtu-ad-creator-profile-v2`。
- 已经启动且固定在旧版 `xingtu-ad-creator-square-v1` 的任务不会被静默改写为 v2；若其检查点与新合约不兼容，系统按既有 fail-closed 规则停止，并在目标账号恢复后以新任务重试。
- 本轮沿用现有 JSONB 主档投影与不可变快照，因此不需要新增数据库表或迁移；61 字段的结构化持久化已由 PostgreSQL 集成测试覆盖，真实平台值仍需完成上述实机对照。
