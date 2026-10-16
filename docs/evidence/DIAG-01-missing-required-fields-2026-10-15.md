# DIAG-01-A3 达人必需字段缺失专项诊断报告

- 日期：2026-10-15（Asia/Shanghai）
- 关联：[DIAG-01 卡片](../tasks/DIAG-01.md)、[诊断报告](DIAG-01-request-diagnosis-2026-10-15.md)、[修复报告](DIAG-01-fix-issue001-2026-10-15.md)、[合并前核查](DIAG-01-pre-merge-review-2026-10-15.md)
- 本轮性质：**只测试、只分析、只给方案**；未修改任何代码、Schema、调度、执行单元与会话策略；未执行任何真实采集
- 代码/环境：分支 `llb_1013`，HEAD `ee11254`，工作区 118 项（含 DIAG-01 既有产物）；执行单元 `unit-local-mac-02`，`local_development`，真实 Chrome；契约 `xingtu-ad-creator-featured-v10`
- 证据来源（**全部为既有运行 + 数据库，未新增平台访问**）：任务 `f74f43bf`、`1e7a02ff`（10-13）、`381d628b`（A+C1 修复前）、`bc393088`（修复后）、`2111c8f5`、`efb257a6` 等历史快照；`bc393088` 的请求级普查 `fixreg-20261015T143623Z.jsonl`；数据库 `creator_snapshots`、`creator_snapshots.payload`、`raw_evidence`

---

## 第一部分：执行摘要

**问题样本（达人 2，`7282701602991898661`）的必需字段缺失是稳定、确定且达人特有的，不是偶发，也不是 A+C1 修复引入的。**

- **稳定性：5 次独立采集（2026-10-13 至 10-15，跨 4 个任务、2 天）结果逐字段完全一致** —— 每次都是 `seeding` 失败 6、`conversion` 失败 9、`fulfillment` 失败 4，无一例外、无一次成功。因此**本轮不需要、也不应该再做真实复测**：历史证据已足以判定"非偶发"，且用户已明确"如历史证据已经能够确定具体代码缺陷，可直接报告并停止相关复测，不应为重复证明而额外访问平台"。
- **对照样本（达人 1，`7503176021160493065`）在 9 次快照中这些字段 `FAILED` 次数为 0**（其中 1 次是上游中断导致的 `NOT_ATTEMPTED`，不是采集失败）→ **问题只发生在特定达人**。
- **数字口径已核准（并更正一处）**：达人 2 共 81 个字段 = `COLLECTED 59` + `FAILED 19` + `NO_DATA 3`。
  - **19 = 唯一"模块.字段"数 = 19 条 `FIELD_INCOMPLETE` 缺口（1:1，无重复统计）**
  - **19 = `MODULE_TIMEOUT` 16 + `MISSING_SOURCE` 3**（**更正**：合并前核查报告中写的"17 个 MODULE_TIMEOUT"有误，实为 **16**）
  - **`NO_DATA` 3 个是独立计数**，属合法缺失，**不计入** 19，也**不产生**缺口
- **根因分两类，均已有请求级证据：**
  1. **16 个字段（`MODULE_TIMEOUT`）**：其来源请求在**模块采集窗口内根本没有发出**。普查实证：达人 2 的资料窗口（14:38:17–14:39:31，超时 60 s）内，`seed_base`（→ seeding 6 字段）与 `conversion`（→ conversion 9 字段）**均未出现**；而达人 1 的同名请求在页面加载后约 1 秒内全部 200。更关键的是：**这两个请求在达人 2 的"精选阶段"（点击「达人概览」「商业能力」后，14:39:34）确实发出了并返回 200** —— 即**数据请求是"标签页交互触发"而非"页面加载预取"**，而这三个模块声明的是 `capture_on_profile_load=true`、`actions=null`，因此**在模块阶段望不到它们**；等到精选阶段它们才出现，而那时采集器只登记 `cards`/`cover_signs`，**这些响应被丢弃**。另有 1 个字段（`cooperation_industry_distribution` ← `order_experience`）**在任何阶段都未发出**。
  2. **3 个字段（`MISSING_SOURCE`）**：来源请求 `contract_base` **确实 200 且被成功关联与解析**（同模块 5 个字段 `COLLECTED`），但响应中**缺少 3 个已登记路径**（`max_process_order_cnt`、`industry_order_distribution`、`industry_vv_distribution`）。
- **仍未确定（唯一开放点）**：`contract_base` 的响应是"**根本不含这 3 个键**"（→ 平台真实无数据，属合法缺失）还是"**含键但值为空/键名不同**"（→ Schema 漂移或解析问题）。**现有证据无法回答**：`raw_evidence` 对这两次运行均为 **0 行**，且字段级"来源缺失"**不产生任何请求级证据**（只写字段状态），因此必须依赖一次**定向响应结构捕获**。这是唯一还需要的平台访问，见第八部分。
- **业务影响**：缺失集中在**转化能力（9 项：GPM/销售额/组件点击/CPC/带货商品与视频等）**与**种草效果（6 项：看后搜、搜索词点击率、A3 增量）**，另有**履约（4 项：最大承接订单数、行业订单/播放分布、合作行业分布）**。这些是媒介做**报价与投放评估**最依赖的数据；缺 19 项会使该达人的商业判断可信度明显下降，但**不影响本轮已交付的资料主体（59 项已采）与精选作品**。
- **是否属于平台无数据？** 分三种情形，必须分开对待：**3 个 `NO_DATA`（basic 省份/MCN/行业标签）是合法缺失**；**15 个字段（seed_base/conversion 来源）数据显示可获取但被时机错过**（中等置信度，因未核对响应内容）；**3 个 `MISSING_SOURCE` + 1 个 `order_experience` 未定**。
- **是否需要改采集实现？** **需要，但不是本轮**。属"模块触发方式对部分达人失效"的实现假设问题，方案见第七部分。
- **与 A+C1 修复的关系：无关。** 达人 2 的字段结果在修复前（`381d628b`）与修复后（`bc393088`）**逐字段完全一致**，且该模式**早于修复 2 天**即稳定存在（10-13 起）。

---

### 补充（用户重点追问）：缺失字段是本次会话改动引入的，还是**一直如此**？

**结论：一直如此，与本次会话的任何改动无关。** 四条独立证据：

1. **时间线**：达人 2 的问题字段在 **2026-10-13 12:19 / 12:28（任务 `f74f43bf`）与 2026-10-13 13:46（任务 `1e7a02ff`）** 三次采集中就已缺失；而本次会话对该仓库的**首次写入是 2026-10-15 21:07**（`runtime.py`），A+C1 修复为 10-15 22:30（`adapter.py`）。**问题比本次会话早 2 天出现。**
2. **逐字段集合完全一致**：把 5 次采集的 FAILED 字段做**集合比对**（非仅比数量）——`identical_to_first=True, extra=[], missing=[]`，即**同一批 19 个字段、同一批 `failure_reason`**，跨 2 天、跨 4 个任务、跨修复前后，**无一次偏差**。原因聚合也与之一致：达人 2 历次 `MODULE_TIMEOUT` 合计 **80 = 16×5**、`MISSING_SOURCE` 合计 **15 = 3×5**。
3. **代码路径逐字节比对（HEAD vs 工作区）**：`collect_module`、`parse_module`、`source`、`wait_ready`、`_collect_featured`、`profile`、`locator` **全部完全相同**——即**模块请求登记与字段解析这条链路没有任何未提交改动**（既无我的、也无用户既有的）。本次会话的改动只落在 5 个函数：`BrowserAdapter.__init__`（新增 2 个参数）、`read_locator`（新增可选 `require_non_empty`）、`verify_identity` / `_confirm_identity`（有界确认）、`featured_spec_local_reason`（新增）以及 `collect_featured_collections` 的 **except 分支**（C1）。这些**都不参与**模块请求的发出、关联或字段取值。
4. **请求级独立证据**：`MODULE_TIMEOUT` 的成因是**请求根本没上过线**，而该判断来自 **Context 级普查**（独立于 `ResponseCollector`，且对 10-13 的运行同样不适用）——达人 2 资料窗口内 `seed_base`/`conversion` 未出现，`order_experience` 全库仅达人 1 的 1 个 `url_key`。此外，用户未提交的 `observer.py`（`on_request` 新增"属性筛选门控"）对这些模块**完全惰性**：**契约中 20 个请求的 `attribute_filter_match` 全部为 `None`**，且达人 2 历次快照中 **`RESPONSE_UNCORRELATED` 出现 0 次**——即该门控从未对任何模块请求生效。

> 因此：**"缺失了哪些字段"是稳定事实（见 3.1 表），"是否本次会话导致"的答案是明确的否**。可证明的边界是"至少自 2026-10-13 起即如此"；更早无数据可查（该达人最早快照即 10-13），但这不影响"非本次会话引入"的判定。

## 第二部分：测试环境与范围，以及"本轮不做真实复测"的决定

| 项 | 值 |
|---|---|
| 代码版本 | `llb_1013` / `ee11254`（与 A+C1 回归完全一致，未改动） |
| 浏览器 / Playwright | 真实 Google Chrome（`browser_executable_path` 固定），Playwright 环境与回归一致 |
| 执行单元 / 账号会话 | `unit-local-mac-02`，`last_session_status=VALID`，未改绑定、未写 Cookie |
| 网络 / 契约 / 超时 / 调度 | 均未调整：`local_development`、`xingtu-ad-creator-featured-v10`、模块 `timeout_seconds=60`、Temporal 调度未动 |
| 样本 | 达人 2（问题样本）、达人 1（对照样本）——与 A+C1 回归同一对达人 |
| 本轮采集次数 | **0 次**（依据见下） |

**为什么本轮不做真实复测（依据用户既定条件）**

用户规定："如果历史证据仍无法区分随机性与稳定性问题，请…进行一次受控真实复测"；同时规定："如历史证据已经能够确定具体代码缺陷，可直接报告并停止相关复测，不应为重复证明而额外访问平台。"

实测结论：**历史证据已经能够判定稳定性与机制**——

- 达人 2 在该问题上的**独立采集次数 = 5**（2026-10-13 10:19 / 10:28、10-13 13:46、10-15 13:28、10-15 14:40），**逐字段结果 5/5 完全一致**；
- 达人 1 的**独立快照 = 9**，同名问题字段 `FAILED` **0 次**。

因此"是否偶发""是否只发生在特定达人"两个问题已被历史证据**确定回答**，再做一次真实采集只会第 6 次得到同一结果，属于用户明确禁止的"为重复证明而额外访问平台"。**本轮据此停止复测**，未增加任何平台访问。

**环境一致性声明**：因未执行新采集，不存在"为让字段成功而临时调整配置"的风险；所有证据均来自既有运行的原始记录。

---

## 第三部分：历史证据复核（字段级对照表）

### 3.1 达人 2（`7282701602991898661`）—— 问题样本，5 次采集逐字段一致

下表列出**非 COLLECTED** 的 22 个字段（19 FAILED + 3 NO_DATA）；为完整起见同时给出 3 个受影响模块中**成功**的字段数量。字段名与来源路径均取自实际契约 `contracts/douyin_xingtu.verified.json` 与数据库快照，未自行假设。

| 模块 | 字段（契约 key） | 中文名 | 来源（请求.路径） | 历史 10-13 ① | 历史 10-13 ② | 历史 10-13 ③ | 修复前 10-15 | 修复后 10-15 | 结论 |
|---|---|---|---|---|---|---|---|---|---|
| seeding | `a3_increment` | A3 增量及同行排名 | `seed_base.avg_a3_incr_cnt` | FAILED | FAILED | FAILED | FAILED | FAILED | **A 类**（16 之一） |
| seeding | `search_after_view` | 看后搜人数 | `seed_base.avg_search_after_view_cnt` | FAILED | FAILED | FAILED | FAILED | FAILED | A 类 |
| seeding | `search_after_view_rate` | 看后搜比例 | `seed_base.avg_search_after_view_rate` | FAILED | FAILED | FAILED | FAILED | FAILED | A 类 |
| seeding | `personal_search_after_view` | 个人页看后搜人数 | `seed_base.personal_avg_search_after_view_cnt` | FAILED | FAILED | FAILED | FAILED | FAILED | A 类 |
| seeding | `personal_search_after_view_rate` | 个人页看后搜比例 | `seed_base.personal_avg_search_after_view_rate` | FAILED | FAILED | FAILED | FAILED | FAILED | A 类 |
| seeding | `search_word_ctr` | 搜索词点击率 | `seed_base.search_word_ctr` | FAILED | FAILED | FAILED | FAILED | FAILED | A 类 |
| seeding | `seeding_link_structure` | （种草链路结构） | `link_structure.link_struct` | COLLECTED | COLLECTED | COLLECTED | COLLECTED | COLLECTED | 正常（对照） |
| conversion | `gpm_range` | GPM 区间 | `conversion.gpm_range` | FAILED | FAILED | FAILED | FAILED | FAILED | A 类 |
| conversion | `sales_amount_range` | 销售额区间 | `conversion.avg_sales_amount_range` | FAILED | FAILED | FAILED | FAILED | FAILED | A 类 |
| conversion | `component_click_count_range` | 组件点击数区间 | `conversion.component_click_cnt_range` | FAILED | FAILED | FAILED | FAILED | FAILED | A 类 |
| conversion | `component_click_rate_range` | 组件点击率区间 | `conversion.component_click_rate_range` | FAILED | FAILED | FAILED | FAILED | FAILED | A 类 |
| conversion | `related_cpc_range` | 相关 CPC 区间 | `conversion.related_cpc_range` | FAILED | FAILED | FAILED | FAILED | FAILED | A 类 |
| conversion | `recommended_product_count` | 推荐商品数 | `conversion.rec_product_cnt` | FAILED | FAILED | FAILED | FAILED | FAILED | A 类 |
| conversion | `product_price_range` | 商品价格区间 | `conversion.rec_product_price_range` | FAILED | FAILED | FAILED | FAILED | FAILED | A 类 |
| conversion | `related_video_count` | 相关视频数 | `conversion.related_video_cnt` | FAILED | FAILED | FAILED | FAILED | FAILED | A 类 |
| conversion | `related_video_play_median` | 相关视频播放中位数 | `conversion.video_vv_median` | FAILED | FAILED | FAILED | FAILED | FAILED | A 类 |
| conversion | `local_sales_overview` | （本地销售概览） | `local_sales.overview` | COLLECTED | COLLECTED | COLLECTED | COLLECTED | COLLECTED | 正常（对照） |
| fulfillment | `max_processing_order_count` | 最大承接订单数 | `contract_base.max_process_order_cnt` | FAILED | FAILED | FAILED | FAILED | FAILED | **A 类（MISSING_SOURCE）** |
| fulfillment | `industry_order_distribution` | 行业订单分布 | `contract_base.industry_order_distribution` | FAILED | FAILED | FAILED | FAILED | FAILED | A 类（MISSING_SOURCE） |
| fulfillment | `industry_play_distribution` | 行业播放分布 | `contract_base.industry_vv_distribution` | FAILED | FAILED | FAILED | FAILED | FAILED | A 类（MISSING_SOURCE） |
| fulfillment | `cooperation_industry_distribution` | 合作行业分布 | `order_experience.order_experience_industries` | FAILED | FAILED | FAILED | FAILED | FAILED | A 类（请求从未发出） |
| fulfillment | `credit_score` / `new_credit_score` / `historical_order_count` / `processing_order_count` / `message_reply_rate` | 信用分等 5 项 | `contract_base.*` | COLLECTED×5 | COLLECTED×5 | COLLECTED×5 | COLLECTED×5 | COLLECTED×5 | 正常（对照） |
| basic | `province` | 省份 | `base.province` | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | **C 类**（合法缺失） |
| basic | `mcn_name` | MCN 公司 | `base.mcn_name` | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | C 类 |
| basic | `industry_labels_raw` | 行业标签（平台结构） | `base.industry_list` | NO_DATA | NO_DATA | NO_DATA | NO_DATA | NO_DATA | C 类 |

> 说明：历史三次（10-13）分别来自任务 `f74f43bf`（2 个快照）与 `1e7a02ff`（1 个快照），均为**修复前 2 天**的独立运行。

### 3.2 达人 1（`7503176021160493065`）—— 对照样本，9 次快照

- 上述同一批字段在 9 次快照中 **`FAILED` 次数 = 0**；8 次为 `COLLECTED`，1 次为 `NOT_ATTEMPTED`（原因是任务被上游中断 `UPSTREAM_INTERRUPTED`，即该模块**根本没被尝试**，而不是采集失败）。
- `profile_complete` 在 8 次中为 `true`（1 次上游中断为 `false`）。
- **结论：这些字段在契约与实现层面是可采的，达人 1 全部成功。**

### 3.3 数量口径核对（回答"是否存在重复统计"）

| 指标 | 数值 | 含义 |
|---|---|---|
| 达人 2 全部字段 | 81 | 契约注册的 8 模块全量字段 |
| `COLLECTED` | 59 | 成功采集 |
| `FAILED` | **19** | **唯一"模块.字段"数** |
| `NO_DATA` | **3** | 独立计数，**不计入** 19，**不产生缺口** |
| `FIELD_INCOMPLETE` 缺口 | **19** | 与 `FAILED` **1:1 对应**，**无重复统计** |
| `MODULE_TIMEOUT` | **16** | 16 个**不同字段**各计 1 次（无同一字段多次计数） |
| `MISSING_SOURCE` | **3** | 3 个不同字段各计 1 次 |
| 16 + 3 | 19 | 与 `FAILED` 一致 ✔ |
| `NOT_PROVIDED` / `NO_PERMISSION` / `NOT_ATTEMPTED` | 0 | — |

**更正**：合并前核查报告曾表述为"17 个 `MODULE_TIMEOUT`"，经逐一核对为 **16**（seeding 6 + conversion 9 + fulfillment 1），另 3 个为 `MISSING_SOURCE`。其余数字（19 / 3 / 3）经核对无误。

---

## 第四部分：字段级差异分析与分类

| 模块 | 字段 | 历史第 1 次（10-13） | 历史第 2 次（10-13） | 本次复测（**未执行**） | 结论 |
|---|---|---|---|---|---|
| 种草 | `a3_increment`、`search_after_view`、`search_after_view_rate`、`personal_search_after_view`、`personal_search_after_view_rate`、`search_word_ctr` | FAILED（MODULE_TIMEOUT） | FAILED（同） | — | **A 类：持续失败**（根因=A1 请求未在窗口内发出） |
| 转化 | `gpm_range`、`sales_amount_range`、`component_click_count_range`、`component_click_rate_range`、`related_cpc_range`、`recommended_product_count`、`product_price_range`、`related_video_count`、`related_video_play_median` | FAILED（MODULE_TIMEOUT） | FAILED（同） | — | **A 类**（根因=A1） |
| 履约 | `cooperation_industry_distribution` | FAILED（MODULE_TIMEOUT） | FAILED（同） | — | **A 类**（根因=A1，`order_experience` 从未发出） |
| 履约 | `max_processing_order_count`、`industry_order_distribution`、`industry_play_distribution` | FAILED（MISSING_SOURCE） | FAILED（同） | — | **A 类**（根因=A2 响应到达但路径缺失）→ 子类待定 C 或 D |
| 基础 | `province`、`mcn_name`、`industry_labels_raw` | NO_DATA | NO_DATA | — | **C 类：真实无数据**（合法缺失，不入缺口） |

**分类统计**

| 类别 | 字段数 | 判定依据 |
|---|---|---|
| **A 类 持续失败** | **19** | 5/5 次独立采集逐字段一致，无任何一次成功；且有请求级证据区分两种机制 |
| **B 类 结果不稳定** | **0** | 达人 2 无任何一次出现不同结果；达人 1 的 1 次 `NOT_ATTEMPTED` 属上游中断，非本问题不稳定 |
| **C 类 真实无数据** | **3**（basic 三项） | `NO_DATA` 语义正确；无缺口；不阻断完整 |
| **D 类 有数据但未解析** | **0 已确认** | 未发现"响应含目标数据但解析失败"的确证；A2 的 3 个字段**可能**属此类，待响应结构捕获后判定 |
| **E 类 证据不足** | **4 个字段的最终归因** | A2 的 3 个（缺 `contract_base` 响应结构证据）+ A1 中 `order_experience` 的 1 个（缺"是否需特定标签页触发"的证据） |

---

## 第五部分：三大技术问题排查

### 5.1 `MODULE_TIMEOUT`（16 个字段）

| 排查项 | 实测证据 | 判定 |
|---|---|---|
| 请求是否真的发出？ | 达人 2 资料窗口（14:38:17–14:39:31）内，`seed_base` 与 `conversion` **未出现**；`order_experience` **全程会话内仅出现 3 次且只有 1 个不同的 `url_key`——全部属于达人 1** | **未发出**（不是"发了没收到"） |
| 是否有实际响应？ | 资料窗口内无请求，故无响应；对照达人 1 同请求 200、耗时 110–260 ms | 无响应 |
| 响应是否晚于 settle 窗口？ | **是**：达人 2 的 `seed_base`、`conversion` 于 **14:39:34** 才出现（200），而资料窗口的模块超时为 **60 s**（14:38:17 → 约 14:39:17）→ **晚约 17 s** | 晚于窗口 |
| 是否被错误关联到其他模块？ | 它们出现在**精选阶段**（14:39:31 的整页加载 + 点击「达人概览」「商业能力」之后）；该阶段采集器只登记 `cards`/`cover_signs`，因此这些响应**未被任何模块关联、直接被忽略** | 非误关联，而是**无人登记** |
| 是否存在响应已到达但监听未捕获？ | 普查（Context 级监听）记录到了这些请求；而模块级 `ResponseCollector` 当时并未注册，属**设计性未捕获**，不是监听失效 | 监听正常 |
| 是否达人特定接口行为？ | 达人 1 在加载后约 1 s 内 6 个请求全部 200；达人 2 在 60 s 内仅 3 个（`link_structure`、`contract_base`、`local_sales`）出现 | **是，达人特定** |
| 当前超时判断是否符合业务实际？ | 该模块声明 `capture_on_profile_load=true` 且 `actions=null`（不做任何标签页点击），即**假定平台会在页面加载时预取这些请求**。达人 2 证伪了该假定：请求需**标签页交互**才触发 | **不符合**：不是"超时太短"，而是**触发方式**问题 |

**结论**：16 个 `MODULE_TIMEOUT` 的本质是 **"模块依赖平台预取，但部分达人不会预取"**。**不应用"延长 timeout"来掩盖**——延长到 300 s 也无效，因为在这条路径上请求永远不会来；请求只在**另一阶段（精选）的点击之后**才发出。这是一个**触发时机 + 响应归属**的设计缺陷，而非性能参数问题。

### 5.2 `MISSING_SOURCE`（3 个字段）

| 排查项 | 实测证据 | 判定 |
|---|---|---|
| 是否收到目标响应？ | **是**：`contract_base` 于 14:38:17.972 返回 **200**（217 ms），达人 2 的 `url_key=86cc3b28b8f0d1fc` 与达人 1 的 `ee8b8a705b543a70` 不同（参数含各自达人 ID，符合预期） | 已收到 |
| 响应结构是否符合已登记契约？ | 响应被**接受并通过 Schema 校验**（同请求的另外 5 个字段成功解析为 `COLLECTED`，含 `credit_score`、`historical_order_count` 等） | **整体结构符合**；仅个别路径缺失 |
| 目标字段是否真实存在？ | **无法判定（关键证据缺口）**。`raw_evidence` 对 `bc393088` 与 `381d628b` 均为 **0 行**；字段级"来源缺失"**不产生请求级证据**（不写 `RequestDiagnostic`，因为响应未被拒绝） | **证据不足** |
| 是数据路径不匹配，还是平台未返回？ | 两种解释都与现有证据相容：①平台对该达人**不下发**这 3 个键（合法缺失）；②平台下发了但**键名/结构不同**（Schema 漂移）。达人 1 同请求能取到这 3 个值 | **待定（C 或 D）** |
| 是否不同达人返回不同结构？ | **是，已证明存在达人差异**：同一契约、同一请求，达人 1 有值、达人 2 无对应路径 | 结构随达人而异 |
| 是否存在数据结构版本差异？ | 无版本字段证据；契约只有一份（`xingtu-ad-creator-featured-v10`） | 无证据 |

**附带发现的机制缺陷**：`personal_search_after_view`、`personal_search_after_view_rate`、`search_word_ctr` 三个字段**契约中已声明 `missing_source_status=NO_DATA`**（即"来源缺失＝合法缺失"），但它们因**请求超时**而落到 `MODULE_TIMEOUT`——说明**"合法缺失"映射只在响应到达时生效，超时路径会绕过它**，把本可判为 `NO_DATA` 的字段升级为 `FAILED`。

### 5.3 `NO_DATA`（3 个字段）

| 排查项 | 实测证据 | 判定 |
|---|---|---|
| 是否符合平台实际数据情况？ | `province`、`mcn_name`、`industry_labels_raw` 来源于 `base` 请求（该请求在两位达人上均成功）；3 次以上历史快照稳定为 `NO_DATA` | 符合 |
| 是否合法缺失？ | 是：`NO_DATA` 的契约语义是"已完成的检查、平台确无数据" | **合法** |
| 是否被错误计入必需字段失败？ | **否**：`failed_count`/`FIELD_INCOMPLETE` **不含**它们；达人 2 的 19 条缺口里没有这 3 项 | 未误计 |
| 是否影响达人最终完整性状态？ | **不影响**：`profile_coverage.observed_field_status_counts.NO_DATA=3` 与 `complete` 判定解耦；达人 1 也有 2 个 `NO_DATA` 但 `profile_complete=true` | 不影响 |

**结论**：`NO_DATA` 处理**符合契约**，无需改动。需要区分的恰恰相反：**应把 A1/A2 中"平台根本不发"的情形也纳入合法缺失语义，而不是一律记为 `FAILED`。**

---

## 第六部分：产品视角的原因分析与优先级

### 6.1 缺失数据对 MCN 媒介实际工作的影响

| 缺失字段（中文名） | 媒介用途 | 缺失影响 | 建议业务优先级 |
|---|---|---|---|
| `conversion.gpm_range`（GPM 区间） | 报价与投放效率核心指标 | **无法评估带货效率**，报价缺少锚点 | **P0** |
| `conversion.sales_amount_range`（销售额区间） | 历史带货规模 | 无法判断体量与议价空间 | **P0** |
| `conversion.recommended_product_count`（推荐商品数）、`product_price_range`（商品价格区间） | 选品匹配度、客单价匹配 | 商品匹配判断缺失 | **P1** |
| `conversion.component_click_count_range`/`component_click_rate_range`/`related_cpc_range`（组件点击与 CPC） | 转化漏斗与成本预估 | 投放成本预估缺失 | **P1** |
| `conversion.related_video_count`/`related_video_play_median`（相关视频数与播放中位数） | 内容转化基线 | 内容效果基线缺失 | **P2** |
| `seeding.a3_increment`（A3 增量及同行排名） | 种草效果与同行对比 | **无法做种草效果横向比较** | **P0** |
| `seeding.search_after_view`/`search_after_view_rate`（看后搜人数/比例） | 种草外溢效果 | 种草说服力证据缺失 | **P1** |
| `seeding.personal_search_after_view(_rate)`（个人页看后搜） | 主页引流效果 | 主页种草力评估缺失 | **P2** |
| `seeding.search_word_ctr`（搜索词点击率） | 搜索转化 | 搜索侧转化缺失 | **P2** |
| `fulfillment.max_processing_order_count`（最大承接订单数） | **产能与是否吃得下商单** | 可能接到超出产能的商单 | **P0** |
| `fulfillment.industry_order_distribution`/`industry_play_distribution`（行业订单/播放分布） | 行业匹配与经验判断 | 行业匹配判断缺失 | **P1** |
| `fulfillment.cooperation_industry_distribution`（合作行业分布） | 合作经验 | 合作履历判断缺失 | **P1** |
| `basic.province`（省份）、`mcn_name`（MCN）、`industry_labels_raw`（行业标签） | 地域筛选项、机构归属 | 仅影响筛选便利性 | **P2**（且属合法缺失） |

### 6.2 对三个业务动作的影响

1. **达人筛选**：`province`/`mcn_name` 缺失使**地域与机构维度的筛选**不可用（P2，且属平台合法缺失）；`conversion.*` 缺失使**按转化能力筛选**实质上失效（P0）。
2. **报价/投放评估**：**受影响最重**——GPM、销售额区间、CPC 是报价的直接输入（P0）。
3. **种草与转化能力判断**：A3 增量与看后搜是**种草能力的核心证据**（P0/P1）；转化区间缺失使"能否带货"无法量化（P0）。

### 6.3 可以接受缺失的字段

- 3 个 `NO_DATA`（省份/MCN/行业标签）：平台确无数据，**可接受**，但应在产品上显示为"平台未提供"而非"采集失败"，避免误导。
- `related_video_count`、`related_video_play_median`、`personal_search_after_view(_rate)`、`search_word_ctr`：属**加分项**，缺失不阻断决策。

### 6.4 必须优先保证的数据（结论）

**先保 P0（5 项）**：`conversion.gpm_range`、`conversion.sales_amount_range`、`seeding.a3_increment`、`fulfillment.max_processing_order_count`、以及"是否能把 A1 的 15 个字段稳定拿到"本身（因为 A1 一旦修好，这些字段会与 conversion/seeding 一起回来）。

> 说明：本优先级**按媒介实际决策价值排序**，未因契约标记为 `required` 就自动置顶；例如 `related_video_play_median` 虽为必需字段，业务上仅 P2。

---

## 第七部分：优化方案

### 方案组 1 —— A1：模块依赖"平台预取"，部分达人不预取（16 个字段中的 15 个）

- **当前问题**：`seeding`/`conversion`（及 `fulfillment` 的 1 个字段）声明 `capture_on_profile_load=true`、`actions=null`，即假定平台在主页加载时会预取这些请求。达人 2 证伪：请求需**标签页交互**（「达人概览」「商业能力」等）才发出。
- **真实证据**：达人 2 资料窗口内 `seed_base`/`conversion` 未出现；同会话精选阶段（点击后）14:39:34 两者均 200；达人 1 加载后约 1 s 内全部 200。5/5 次跨 2 天稳定复现。
- **问题稳定性**：**稳定**（5/5）。
- **可能根因**：模块级"触发方式"假设对部分达人不成立；同时"精选阶段收到但未登记"造成**已到达的数据被丢弃**。
- **业务影响**：15 个字段（含 P0 的 GPM/销售额/A3 增量）长期缺失。
- **最小优化方案（三选一，可组合）**：
  - **1A（推荐，最贴合现有机制）**：为这三个模块登记**已核验的标签页动作**（`actions`）以主动触发请求——现有契约已证明这些点击可用（精选规格 `reload_homepage` 后正是靠点击「达人概览」「商业能力」拿到 `seed_base`/`conversion` 的 200 响应）。改动集中在注册表 `modules[].actions` 与必要的 `wait_ready`，**不新增接口、不猜测参数**。
  - **1B**：把模块采集改为"加载后若必需请求未出现，则在**同一模块窗口内**执行登记好的唤醒动作并等待"（等价于 1A 的通用化），需要新增"缺失触发→有界唤醒"逻辑。
  - **1C（不推荐单独使用）**：延长 `timeout_seconds`——**无效**，因为该路径上请求永不到达。
- **预期收益**：修好后达人 2 的 15 个字段可望与达人 1 一致（**+15 项**，含 2 个 P0）；同时消除"精选阶段丢数据"的浪费。
- **修改范围**：契约（`contracts/douyin_xingtu.verified.json` 的 `modules` 段）+（若选 1B）`adapter.py` 的模块采集流程；**不改 Schema、不改调度**。
- **潜在风险**：新增点击会改变页面状态与请求时序，**必须重新核验**响应关联（不得误收他模块响应）；契约变更需按既有 `VERIFIED`/证据流程登记；可能略微增加请求与耗时。
- **置信度**：**中高**——"请求未在窗口内发出"已确证（高）；"点击可稳定触发且响应含目标字段"为**中等**（我们只确认了 200 响应，未核对内容）。

### 方案组 2 —— A2：`contract_base` 响应缺少 3 个登记路径（3 个字段）

- **当前问题**：响应 200 且被接受，但 `max_process_order_cnt`、`industry_order_distribution`、`industry_vv_distribution` 取不到。
- **真实证据**：达人 2 `contract_base` 200（217 ms），同响应 5 个字段成功；达人 1 同请求这 3 个字段成功；5/5 稳定。
- **问题稳定性**：稳定。
- **可能根因（未定）**：①平台对该达人**不下发**这些键（合法缺失）→ 应把 `missing_source_status` 声明为 `NO_DATA`；②平台下发了但**键名/结构不同**（Schema 漂移）→ 应更新契约路径；③平台下发**空值**→ 应视为 `NO_DATA`。
- **业务影响**：产能判断（P0）与行业匹配（P1）缺失。
- **最小优化方案**：**先取得证据，再决定**。若为①/③ → 仅需为这 3 个字段补 `missing_source_status=NO_DATA`（契约字段级改动，最小）；若为② → 更新 `path`（同样最小，但需证据支撑）。**在拿到响应结构前不应改动契约**。
- **预期收益**：3 个字段从 `FAILED` 变为"语义正确的状态"（合法缺失或正确取值）。
- **修改范围**：仅契约字段级声明（若为①/③），或 `path` 值（若为②）。
- **潜在风险**：若误判为"合法缺失"而实际是解析缺陷，会**掩盖真实数据**——因此必须先有响应结构证据。
- **置信度**：根因**低**（证据不足）；优化方向明确但需前置证据。

### 方案组 3 —— 超时路径绕过"合法缺失"声明（机制缺陷，影响 3 个已声明 NO_DATA 的字段）

- **当前问题**：`personal_search_after_view(_rate)`、`search_word_ctr` 已声明 `missing_source_status=NO_DATA`，但因请求超时被记为 `MODULE_TIMEOUT`（`FAILED`）。
- **真实证据**：字段状态 `FAILED / MODULE_TIMEOUT`（5/5）；契约中三者 `missing_source_status=NO_DATA`。
- **问题稳定性**：稳定。
- **可能根因**：`missing_source_status` 只在"响应到达但路径缺失"时生效；`MODULE_TIMEOUT` 走的是另一条失败分支，未考虑"该请求对该达人可能本就不发"。
- **业务影响**：把可能的**合法缺失**误报为采集失败，污染 `failed_count` 与媒介对数据质量的判断。
- **最小优化方案**：为**已声明 `missing_source_status` 的字段**引入"请求未发出 ⇒ 该字段按声明状态收口"的判定（与 MISSING_SOURCE 同源处理）。**这属于语义修正，不是放宽校验**——它不放宽 Schema、不忽略错误，只是把同一"无数据"结论应用到第二条证据路径。
- **预期收益**：减少误报，使 `failed_count` 反映真实采集缺陷；对达人 2 可望把 3 个字段从 FAILED 转为 NO_DATA。
- **修改范围**：`adapter.py` 模块解析的失败分类（**极小**）。
- **潜在风险**：若把"平台本应发但没发"也判为合法缺失，会掩盖真实缺陷——必须只在**契约明确声明** `missing_source_status` 时生效，且保留原始证据（请求未出现）以便审计。
- **置信度**：中高。

### 方案组 4 —— `order_experience` 从未发出（1 个字段）

- **当前问题**：`cooperation_industry_distribution` ← `order_experience`，该请求在**任何阶段**都未出现（全库仅达人 1 的 1 个 `url_key`）。
- **问题稳定性**：稳定（5/5）。
- **可能根因**：①该达人无合作订单经历 → 平台不渲染该区块、不发请求（合法缺失）；②该区块需要**另一个标签页**（如「履约能力」）才触发，而我们从未点击。
- **业务影响**：合作行业分布缺失（P1）。
- **最小优化方案**：与方案 1A 合并处理——若登记适当的标签页动作后请求出现，则为②；若仍不出现，则可判为①并声明 `missing_source_status=NO_DATA`。
- **修改范围**：契约 `actions`（与 1A 同批）。
- **潜在风险**：无额外风险（与 1A 同一批核验）。
- **置信度**：中。

### 方案组 5 —— 可观测性缺口（支撑上述所有方案的判据）

- **当前问题**：字段级"来源缺失"**不产生任何请求级证据**（`raw_evidence` 0 行），使"合法缺失 vs 解析缺陷"无法回溯判定。
- **最小优化方案**：让字段级 `MISSING_SOURCE` 也落一条**脱敏**的结构证据（沿用既有白名单：请求 key、HTTP 状态、content-type 类别、业务码、响应顶层 key 名——**不含**正文/URL/query/Cookie）。既有 `RequestDiagnostic` 已具备该能力，只需在字段级来源缺失时也调用一次。
- **预期收益**：未来同类问题**无需再访问平台**即可判定，直接避免"为证明而重复采集"。
- **修改范围**：`adapter.py` 字段解析处的证据登记（小）。
- **风险**：证据体量增加（受既有 30/90 天保留策略约束）。
- **置信度**：高。

### 方案优先级与实施顺序建议

| 顺序 | 方案 | 优先级 | 理由 |
|---|---|---|---|
| 1 | **方案 5（可观测性）** | **P0（工程）** | 一切归因的前提；成本最小；可避免未来重复访问平台 |
| 2 | **方案 1A（登记标签页动作）** | **P0（业务）** | 一次修复可望恢复 15 个字段（含 2 个 P0 业务字段） |
| 3 | **方案 3（超时路径的合法缺失语义）** | **P1** | 消除误报；改动极小 |
| 4 | **方案 2（`contract_base` 3 个路径）** | **P1** | 需先取证据；若确为合法缺失则仅需字段级声明 |
| 5 | **方案 4（`order_experience`）** | **P2** | 与 1A 同批验证即可 |

---

## 第八部分：待确认问题

### Q1（关键，决定下一步）—— 是否授权**一次定向、只读**的响应结构捕获？

1. **当前已知事实**：`contract_base` 对达人 2 返回 200 且被接受，但响应中缺少 3 个已登记路径；同一请求对达人 1 可取到这 3 个值；5/5 稳定。系统**没有**存储该响应的任何结构证据（`raw_evidence` 0 行）。
2. **不确定的地方**：这 3 个键是"不存在"（合法缺失）、"存在但为空"（合法缺失）还是"键名不同"（Schema 漂移）。
3. **可选方案**：
   - **A（推荐）**：授权一次**只读定向捕获**——用项目自身 `BrowserRuntime` 打开达人 2 主页（同一 profile/账号/契约），仅记录 6 个已登记端点的**是否发出**与 `contract_base` 响应的**顶层键名列表**（不含值、不含正文、不含 query/Cookie）；**不执行采集、不写业务库、不点击**（或仅在必要时执行契约已登记的标签页点击）。
   - **B**：使用本轮已授权的"一次受控真实复测"名额，跑一次 target=2 的常规采集。**缺点**：只会第 6 次得到完全相同的字段结果（稳定性已由 5/5 证明），**无法**回答响应结构问题，属"为重复证明而额外访问平台"。
   - **C**：不授权任何平台访问，则方案 2 只能停在"证据不足"，并建议**先实施方案 5**（可观测性）后再自然取得该证据。
4. **推荐方案**：**A**（若你希望本轮就闭合 A2 的 C/D 判定）；否则 **C + 先做方案 5**。
5. **推荐理由**：A 是唯一能以最小平台访问回答该问题的方式，且完全只读；B 已被证明无信息增量且违背你设定的边界。
6. **需你确认的具体事项**：是否授权 A；若授权，是否允许在探针中执行**契约已登记**的标签页点击（用于验证 `order_experience` 的触发条件）。

### Q2 —— A1 的修复形态（授权修复后）

- 事实：三个模块当前 `actions=null`，依赖平台预取；部分达人不预取。
- 可选：**1A 登记标签页动作**（推荐）／**1B 通用"缺失触发→有界唤醒"**／两者结合。
- 需确认：是否接受**契约变更**（`modules[].actions`），以及是否同意**必须重新核验响应关联**（避免误收他模块响应）。

### Q3 —— 是否接受把"平台不发请求"视为合法缺失

- 事实：`missing_source_status` 已为 3 个字段声明 `NO_DATA`，但超时路径绕过它。
- 可选：**只在契约显式声明时**才把"请求未发出"判为声明状态（推荐）／保持现状全部 FAILED。
- 需确认：是否同意该语义修正（属"不放宽校验、只对齐语义"）。

### Q4 —— 达人 2 是否需要在产品上单独标注

- 事实：该达人 19 个必需字段长期缺失，但系统未在任务级区分"哪些达人字段不可用"。
- 可选：**在达人详情标注缺失字段与原因**（推荐 P2）／维持现状。
- 需确认：是否列入 P2 体验项。

### Q5 —— 本轮报告结构的补充

- 你的消息在"### 第九部分：最终交付 → 第一部分：执行摘要（用产品负责…）"处被**截断**，我按消息中已明确的章节（一～八）组织本报告，并自行补齐了"第二部分：测试环境与范围""第三部分：历史证据复核""第四部分：字段级差异分析""第五部分：三大技术问题""第六部分：产品视角""第七部分：优化方案""第八部分：待确认"。
- 如你原本要求的十部分/九部分结构与此不同，请把剩余要求发我，我会**只重排报告结构**（不改结论、不再访问平台）。

---

## 附：本轮未做与未改（边界声明）

- **未执行任何真实采集**（0 次）；未修改任何代码、Schema、迁移、调度、执行单元与会话策略。
- **未提交、未推送、未合并**；HEAD 仍 `ee11254`。
- 唯一开放的技术动作是 Q1 的定向只读捕获（**待授权**）。
