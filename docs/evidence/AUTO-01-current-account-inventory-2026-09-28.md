# AUTO-01 当前账号能力与主页字段盘点（第一轮）

日期：2026-09-28（Asia/Shanghai）。环境：本项目独立 Chrome 154、`unit-local-mac-02`、本地开发网络。原始结构报告位于项目私有 `.runtime/research/auto01-live-inventory/`，不提交请求头、Cookie、令牌或原始响应正文。

## 已确认能力

- 用户在同一浏览器上下文完成正常登录后，可进入客户后台 `/ad/creator/index` 和达人广场 `/ad/creator/market`。
- 内容关键词“美妆”搜索成功；请求条件为 `seach_type=3`、`page=1`、`limit=20`，业务码为 0，返回 20 位、`has_more=true`、`total_count=2000`。
- 普通页面滚动、`.search-result`／`.base-author-list`／`.search-content-panel` 内部滚动及 `End` 键均未产生第 2 页搜索请求。实际主滚动容器 `#star-layout-content-wrapper` 已到达底部（`scroll_top=3489`、`client_height=633`、`scroll_height=4122`），页面渲染约 20 位，但没有下一页控件。因此 UI 路径暂不能登记分页推进；已转入单次页面内 `page=2` 请求等价性实验。
- 第一次页面内请求实验复用第一页 JSON 请求体，仅把 `page=1` 改为 `page=2`，结果为 HTTP 400；第一页同期仍为 HTTP 200、业务码 0、20 位。由此证明共享 Cookie 与请求体不足以复现分页，请求还依赖页面附加头或动态上下文。
- 最终实验在同一页面上下文中仅以内存复用原生请求头（报告只保存头名称），`page=2` 返回 HTTP 200、业务码 0、20 位、`pagination.page=2/has_more=true/total_count=2000`。第 1、2 页达人身份集合 SHA-256 摘要不同，证明不是重复第一页。必要头包括 `x-login-source`、`x-secsdk-csrf-token` 与 `agw-js-conv`；值未写入文件。
- 生产契约据此启用 `next_page_mode=page_fetch`，但 `page_fetch_max_verified=2`。第 3 页及以后和真实终点未核验，最多取得前 40 位后以 `SEARCH_CAPABILITY_LIMIT` 停止，不能报告平台耗尽。
- 已验证达人主页加载成功，基础、报价、传播、种草、履约、转化等结构化响应均出现 HTTP 200／业务成功；同时出现 `rmc.bytedance.com/verifycenter/captcha/v2` 验证 iframe。挑战出现时部分数据返回成功，仍不得视为完整采集成功。
- 浏览器正常关闭并报告 `browser_stopped=true`；本轮开始前发现的关闭挂起已增加固定上限并以隔离状态处理。
- 关闭后重启的受保护会话复核失败；本地单元已从遗留 `READY` 带审计纠正为 `NEEDS_LOGIN / SESSION_NOT_PERSISTED_AFTER_RESTART`。这不是账号或权益结论，而是当前进程交接模型不可用的证据。

## 当前主页数据面草案

此表是“观察到的候选数据面”，不是已发布采集契约。字段单位、周期、空值、权限与页面展示需逐项对照后才能登记。

| 业务分组 | 已观察来源 | 已观察的字段类型／页面内容 | 当前结论 |
|---|---|---|---|
| 基础身份 | `get_author_base_info` | 星图 ID、昵称、头像、粉丝、性别、地区、MCN、内容标签 | 既有 9 字段已登记；本轮身份绑定再次出现 |
| 服务报价 | `get_author_marketing_info` | 6 类报价记录、价格、原价、视频类型、任务分类、上下线状态；页面展示植入／定制／短直种草等报价 | 数据面真实存在；需登记每类报价语义与金额单位 |
| 传播能力 | `get_author_spread_info`、`get_author_commerce_spread_info` | 播放中位数、互动率、完播率、点赞／评论／分享均值、预期 CPM/CPE、商业播放指标 | 需核对页面周期、比例单位及同行超越口径 |
| 种草能力 | `get_author_commerce_seed_base_info`、`author_link_struct` | 搜后行为、A3 增量、搜索词指标、链路层级分布及同行中位数 | 需核对默认周期和层级枚举 |
| 履约能力 | `get_author_contract_base_info`、`get_author_order_experience` | 信用分、订单数、进行中订单、最大承接数、回复率、合作行业分布 | 需核对权限、计数周期和分布单位 |
| 转化／本地销售 | `get_author_convert_ability`、`author_local_sales_performance` | GPM、订单／销量、组件点击、商品价格区间、相关视频、播放中位数 | 当前样本含正常零值与区间值；必须区分无数据和真实零 |
| 连接用户／画像 | 页面存在“连接用户”标签；本轮仅观察到 `get_fans_text_switch` | 具体画像响应尚未触发或未确认 | 未覆盖，不能标记完整 |
| 创作能力与精选作品 | 页面存在“创作能力”标签；本轮未完成标签切换 | 默认周期、两组精选作品及封面仍待实测 | 未覆盖，F06 继续待验收 |

## 已登记的异常语义

- 真实挑战 iframe 登记为 `PLATFORM_SECURITY_CHALLENGE`；Adapter 在会话、搜索和模块就绪检查中会立即停止，人工维护清除后再续跑。
- 历史真实业务码 `10003` 登记为 `PLATFORM_PERMISSION_DENIED`；不再误判为页面 Schema 变化或触发重新登录。
- 额度限制业务码尚无真实样本，保留领域错误类型但不猜测平台码。

## 未满足的验收

真实第 2 页已通过。第 3 页及以后、分页终点、5 位完整主页、20 位连续任务、画像／创作／精选模块、挑战清除后的完整数据面、跨重启会话恢复、真实等待任务续跑及 7 天容量观察均未完成。
