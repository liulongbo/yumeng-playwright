# 开发任务索引

# 2026-10-21 LIVE-01：前端「户外 / 10 位」真实采集验收（待验收／部分通过）

[LIVE-01](LIVE-01.md) 使用 Playwright MCP + 真实 Chrome，从「星采」前端以 `media-a` 登录并一次性提交「户外、目标 10 位」（任务 `b94d146b-98f5-41ee-8041-77f2b042d9d2`），真实跑通 P1 DeepSeek 转换、Temporal 排队、巨量星图检索（20 位候选）、F05/F06 采集、PostgreSQL 持久化与前端展示。终态 **`PARTIAL_COMPLETED`**：`valid_count=10/10`，10 位达人均有已发布快照；`profile_complete_count=5`、`featured_complete_count=9`、`failure_reason=PROFILE_SCOPE_INCOMPLETE`，页面如实显示「资料完整 5 / 精选完整 9 / 失败步骤 0」。达人详情展示真实星图 ID、粉丝、月深度用户、内容数据、CPM/CPE 与两组精选视频，封面 9/9 加载、控制台 0 错误。过程中修复 ①HTTP 504 被误判为 `PLATFORM_PAGE_CHANGED` 导致 9 位后整任务失败（改为模块级 `MODULE_COLLECTION_FAILED:PLATFORM_HTTP_5XX` + 契约测试）②API/Worker 封面目录不一致导致 404（对齐运行配置）。回归：单元 303、契约 34、观察器 17 通过；`ruff`/`mypy` 通过。遗留：带 `connection_users` 筛选的真实检索失败根因未确认；lease 丢失根因未证实（已自动恢复）；F05/F06 字段完整度未达 10/10。**未提交、未推送、未合并。** 证据：[LIVE-01 真实端到端验收证据](../evidence/LIVE-01-live-e2e-2026-10-21.md)。

# 2026-10-21 SESSION-01：当前执行单元巨量星图登录状态有效（进行中）

对当前唯一开发执行单元 `unit-local-mac-02` 执行真实 Chrome 只读冷启动核验：`xingtu session-diagnostics` 成功 exit `0`，进程内观测为 **`VALID / PROTECTED_PAGE_AND_ACCOUNT_VERIFIED`**；受保护业务页可用，未出现登录页或安全挑战，实测账号与绑定账号 `ID: 1807978499337419` 精确一致，私有会话快照在首次导航前成功恢复，Chrome `156.0.8078.47` 正常关闭。结论：**当前登录有效，无需重新登录**。应用户追加要求，已再用该单元专属 profile 打开 Chrome 供人工查看，窗口预计保持 30 分钟；期间不得并发启动采集，查看完成后需 `Command-Q` 完全退出。本轮未搜索、未采集、未重登、未写业务库；首次受限沙箱尝试的 macOS Crashpad/Mach 权限失败发生在访问平台前，不是会话失效证据。完整脱敏证据见[实时只读核验](../evidence/SESSION-01-session-live-check-2026-10-21.md)；[SESSION-01](SESSION-01.md) 仍为**进行中／未验收**，会话存活上界与历史漂移根因仍未闭合。

# 2026-10-16 CD-08 / DATA-02：作品封面与传播量中位数修复 + 7 指标/11 作品字段结构化（CD-08 待验收 / DATA-02 已完成）

[CD-08](CD-08.md) 修复达人详情「创作能力作品封面」与「商业能力播放量中位数」；[DATA-02](DATA-02.md) 完成 7 项内容数据指标与 11 个作品字段的 JSONB 拆分、历史回填与读写链路。要点：①播放量中位数原读顶层 `spread.play_mid`（`1399516`），线上实测该卡片是 `spread.item_rate_metrics.play_mid`（`766187`＝`76.6w`、优于 `99.23%`），修复后页面与平台一致且另六项不变；②作品 `item_cover` 是不透明对象存储 key，改用已登记的 `get_sign_image`（含实测必需的 `format=webp`）与既有 CDN 白名单签名、受控入库并按平台 key 登记，作品列表 15/15 与 14/14 显示真实封面且与作品一一对应（柱序/链接/封面/播放量/标题逐条核对）；③迁移 015/016/017 新增 5 指标列、追加式作品观测表、`media_objects.source_key`，回填 3064 条作品行与 51 位达人的指标值（缺失保持 NULL、未填 0，副标题/收藏数标注 `NOT_PROVIDED`），JSONB 与快照 md5 未变化；④契约升版 `xingtu-ad-creator-featured-v11`（新增 `cover_signs` 请求与 `item_cover` 规范），`adapter_version` 不变；⑤实现中修复签名回声未校验、`text_value(None)` 变 `"None"`、任务入口封面 404、空 `canonical_link` 冲突、`field_sources` 描述空值共 5 个真实缺陷。验证：后端 `403 passed, 1 skipped`、前端 `82 passed`、`ruff`/`format`/`mypy --strict` 与 lint/build 全部通过；两入口真实 Chrome 验收通过。历史封面全量回填已完成（去重 `1590/1591` key，唯一未解析为平台拒签）；仍待验收的一项为「新采集数据按现有业务流程写入」（采集侧封面链路未做真实新采集回归，用户本轮要求不为此单独触发采集）。详见[验收证据](evidence/CD-08-DATA-02-acceptance-2026-10-16.md)。


# 2026-10-15 DIAG-01：巨量星图采集请求行为与验证触发专项诊断（待验收）

[DIAG-01](DIAG-01.md) 只做诊断与归因，**未实施任何修复**，未改动采集主链路（`adapter.py`/`engine.py`/`worker.py`/`workflow.py`/`observer.py`/`challenge.py`/`browser_host.py` 零改动）。为回答"为什么自动采集比人工更容易遇到滑块/风控"，新增**默认关闭**的 Context 级请求普查（`request_census.py` + `runtime.py` 一处挂载点，未设 `XINGTU_REQUEST_CENSUS` 时行为与改动前一致）与人工基线只读脚本，并以**产品前端一次提交**（关键词「汽车」、目标 2 位、发送前硬校验正文、仅提交一次）取得真实样本 `381d628b`。**核心量化结论**：该次**零验证、零失败、零重跑**的健康运行仍产生 **2698 条网络请求**，其中静态资源 1743（64.6%）、平台 API 542、埋点监控安全 SDK 183，而系统自有的"关联请求"计数器只记 **49 条（1.8%）**；跨操作完全重复请求实测 **1966 条**（静态资源占 1345 条）而计数器恒为 **0**（`duplicate_request_count` 只在单操作内计数）——同一个 30 秒失败运行甚至可以同时是"计数器 0 条"与"普查 542 条"。**共登记 11 项问题**，两项 P0：①精选集合整段未采集——两位达人 4 组精选全部 `NOT_ATTEMPTED`、`featured_collections` **0 行**、封面 **0 个**，`verify_identity` 在精选重载后判 `IDENTITY_MISMATCH`，而普查 `url_key` 证明重载加载的确是同一位达人（达人 1 为 13/13、达人 2 为 14/14 完全重合，两位达人之间零重合）；②`WAITING_FOR_RESOURCE`/`RETRY_WAIT` 不在 workflow 显式唤醒集合，Temporal 历史实证**每个 segment 各有 2 次 `collect_segment_v1` 执行、中间各一个 30 秒定时器**（`01a13e24`：0.15→92.5s，TimerStarted 30s，122.5→263.0s），叠加 `resume_supported=false` 每次重跑都清游标重扫第 1 页，使单达人耗时 77s→263s、请求约翻倍。历史线索复核：**159 关联请求不可复现**（全仓仅 DEC-015 一处、无口径无任务 ID，该任务 checkpoint 现为 `observed_requests=201`，`task_checkpoints` 单行可变无历史版本）；**69–84ms 异常恢复完全可复现**（`audit_logs` 五组 84/73/76/69/81 ms）；另有真实自然挑战检测→放行仅 **5.740s** 且等待期 `challenge_samples=0`（15 秒观测窗未生效）、失败证据被固定标注 `network_mode=production_line`（`evidence.py:28` 默认值未被覆盖）等。回归：新增普查单测 7 例通过；`backend/tests/unit` 220 passed、`contract` 33 passed、`integration` 81 passed/1 skipped（1 项为迁移 013 后既有测试期望未同步，非本轮引入）；`ruff`/`format`/`mypy`（strict，32 files）通过。**人工基线已完成**（同两位达人：自动化 1.46× 总请求、2× 主页加载、2.06× 完全重复，业务 API 仅 1.21×）。**ISSUE-001 根因已确认并经用户授权修复（A + C1）**：精选重载后平台 SPA hydration 会令 `div.author-info span.copy-text` 出现约 45–60 ms 的空文本窗口，而 `read_locator` 只拒绝 `None`，空串被当作成功读取 → `'' != creator_id` → `CREATOR_INVALID: IDENTITY_MISMATCH` → 两组精选全中止且零落库。修复为 `adapter.py` 4 处（`read_locator` 可选 `require_non_empty`、`verify_identity` 5s 有界确认、`featured_spec_local_reason` 极窄白名单），未改 Schema/API/调度/执行单元/会话策略。**真实回归（同参数、同一对达人）**：`featured_status` NOT_ATTEMPTED → **COMPLETED**、精选 0 → **4 行**、卡片 0 → **11（全 STORED）**、封面 0 → **11**，零失败/零挑战/零重试、8 模块无退化；单元 **259 passed**、契约 **33 passed**、集成 **81 passed + 1 skipped**（另 1 项既有迁移版本断言失败，与本轮无关）。**未 commit/push/merge**，等待用户审阅。**A3（达人必需字段缺失）已修复并通过真实回归**：根因为 `profile()` 只执行 `modules[0]` 的 `actions`，导致 `seeding`/`conversion` 声明的`capture_on_profile_load=true` 在**不会预取该端点的达人**上永远等不到请求（16 个 `MODULE_TIMEOUT`）。修复为**加法式门控**：同一已登记窗口内，仅当某模块仍有 `required` 响应未到达时才执行其**已核验**的标签交互（选择器全部取自 featured 既有集合），并收窄校验守卫（仍禁止加载型模块 `entry`）。实测达人 2 **`FAILED` 19 → 10、`COLLECTED` 59 → 67、完整率 72.8% → 82.7%**，**达人 1 零字段变化**（预取达人零额外点击），请求 +1.2%、**页面加载次数不变**、无重复/无重试/无挑战；单元 **271 passed**、契约 **33 passed**、集成 **81 passed + 1 skipped**（另 1 项既有迁移断言失败，与本次无关）。**未 commit/push/merge**；5 项 C 级语义事项（`-` 占位值、履约 3 个 `MISSING_SOURCE`、`order_experience`、`contract_version` 是否升版、既有集成断言）已停止待授权。详见[诊断报告](../evidence/DIAG-01-request-diagnosis-2026-10-15.md)、[修复报告](../evidence/DIAG-01-fix-issue001-2026-10-15.md)、[A3 诊断](../evidence/DIAG-01-missing-required-fields-2026-10-15.md)与[A3 修复报告](../evidence/DIAG-01-A3-fix-issue-fields-2026-10-15.md)。

# 2026-10-15 CD-07：达人详情「报价与历史」移除「系统采集历史」模块展示（已完成）

[CD-07](CD-07.md) 按用户要求去掉「达人详情 → 报价与历史」章节内「系统采集历史」小模块的页面展示，**只改前端展示，未改任何流程**（`backend/**`、`contracts/**`、`migrations/**` 零改动）。移除内容：该模块的标题、「N/N 次已入索引」计数、快照时间线列表，以及仅供它使用的 LIB-01 索引缺口提示；同时解除页面取数消费——`CreatorLibraryDetailPage` 不再请求 `GET /api/creator-library/{id}/history`（去掉 `history` 查询与 `indexed`/`totalSnapshots`/`missingIndex` 派生值），并删除随之失效的 `.history-list`/`.gap-note` 样式。**保留边界（重要）**：同一章节的「报价历史」照常展示真实报价观察（实测 8 行）；该历史**端点与数据本身未删除、未做破坏性变更**（实测仍返回 200：`items=5 / indexed=5 / total=7`，LIB-01 索引缺口事实仍在库中，只是不再有页面入口）；`api.creatorLibraryHistory` 与 `CreatorLibraryHistory` DTO 仍保留在代码中（当前无调用方，未擅自删除）。验证：真实 Chrome（项目 Playwright MCP `1.62.0-alpha-2026-06-29` + 本机 Chrome）**14/14** 通过（含"页面不再请求 /history"与"端点仍可用"双向核对、四章回归、任务入口、390px、Console Errors 0 / 失败 API 0）；前端 **71 passed**、后端单测 **213 passed**、lint/build/`ruff`/`mypy`/`git diff --check` 通过；**CD-06 回归 27/27**、**CD-05 回归 38/38**、**CD-04 回归 52/52**（其中 CD-04 的 `BIZ-22` 原断言要求该系统采集历史模块出现，已按本轮新范围改写为"报价历史仍在"并注明原因，未削弱其余断言）。遗留：`api.creatorLibraryHistory`/DTO 暂无调用方（需清理请单独确认）；LIB-01 历史索引数据未删未回填。本轮未引入 P0 问题。详见[验收证据](../evidence/CD-07-quote-history-removal-2026-10-15.md)。


# 2026-10-15 CD-06：达人详情「履约能力」精简与「连接用户」双轴趋势合并（待验收）

[CD-06](CD-06.md) 按用户本轮两项要求调整达人详情页，**只改前端展示与字段联调，未改任何流程**（`backend/**`、`contracts/**`、`migrations/**` 零改动）。**需求一「履约能力」**：移除「行业订单分布」「行业播放分布」「合作行业分布」三个模块的页面展示，该章节只剩「履约与合作表现」；三个字段的数据、API 与字段观测**均未删除**（实测 API 仍返回且状态为 `COLLECTED`，仍可在字段来源抽屉查看），页面也不再输出其 JSON 字符串叶子。**需求二「连接用户」**：①移除「连接用户规模与粉丝增长」面板；②移除「近 30 日粉丝日增量」；③把「近 30 日粉丝总数」与「近 30 日连接用户（平台窗口口径）」**合并为一张双轴趋势图**——左轴连接用户数、右轴粉丝数、X 轴时间、顶部图例，鼠标移到任一时间点同时查看两个口径的值（竖向参考线 + 两个高亮点 + 浮层）。新增可复用 `DualAxisTrend` 组件（内联 SVG/CSS，未引入图表依赖）。实现中处理两个真实约束：①两个日序列窗口**相差一天**（`fans_daily_trend` 09-14→10-13、`connection_daily_trend` 09-13→10-12），因此按**日期并集**对齐、各画自己有值的点，缺失日期**留空而不补造**；②两者量纲相差约 17 倍（连接用户 2344.0万 vs 粉丝 135.4万），必须**左右轴独立刻度**，否则粉丝线会被压平；两条线各自取值、不相加、不归一化。验证：真实 Chrome（项目 Playwright MCP `1.62.0-alpha-2026-06-29` + 本机 Chrome）**27/27** 通过（含 API 逐点核对、真实鼠标 Hover 与移出、两入口一致性、390px、Console Errors 0 / 失败 API 0）；前端 **71 passed**、后端单测 **213 passed**、lint/build/`ruff`/`mypy`/`git diff --check` 通过；**CD-05 回归 38/38**、**CD-04 回归 52/52**。未完成/遗留：未做像素级视觉对比（参考图 Y 轴刻度为整千取整风格，当前取实际最小/最大值）；参考图为平台自身页面且数值与库内不同（1.4 亿级 vs 2,344 万级），本轮按库内真实数据绘制；参考图「连接用户分布」5 个指标块属本项目「连接用户分层与同行业对比」模块，不在本轮点名范围故未改动。本轮未引入 P0 问题。详见[验收证据](../evidence/CD-06-fulfillment-and-dual-axis-trend-2026-10-15.md)。


# 2026-10-15 CD-05：达人详情 Tab 调整与「创作能力 · 最新视频表现」图表/作品优化（待验收）

[CD-05](CD-05.md) 按用户本轮四项要求，在**不改采集流程、不改数据库结构、不改快照与字段观测选择规则**的前提下调整达人详情页。**任务一**：移除「达人概览」章节（Tab 入口与页面内容），最终只保留 **商业能力 → 创作能力 → 履约能力 → 连接用户 → 报价与历史**，默认进入**商业能力**；`ChapterKey` 去掉 `overview` 并新增 `normaliseLegacySection()` + `hashchange` 监听，使旧 `#overview` 标识（整页加载与页内改 hash 两条路径）都归一落到默认章节，不产生空白页——这正是本轮实现中发现并修复的真实缺陷（原先只在挂载时归一化，页内跳转不会重新挂载组件）。**任务二**：最新视频表现柱状图改为**每根柱子默认可见地展示该视频真实播放量**（`countUnitText`：≥1万→`万` 1 位小数、1千–1万→`k`、<1千原数；`915,520→91.6万`，仅展示层换算，原始 `play` 未被覆盖），**X 轴由数组序号改为平台真实发布时间**（`item_date`，回落 Unix 秒 `create_time`），新增 **Hover 浮层**（`position:fixed` 定位以脱离 `.video-bars` 横向滚动盒，故再高的柱子也不会被容器裁剪；鼠标从柱子移入浮层不会异常消失）展示真实封面占位/标题/播放量与作品链接，柱子、浮层与卡片**点击均在新标签页打开该记录的真实抖音作品链接**（`href` 与 API `url` 逐字相等，`target=_blank`，停留详情页）。**任务三**：图表下方作品区域改为封面+标题+播放量+日期的卡片网格，与图表**共用同一份 `buildVideoItems()` 规范化数据**，因此两处播放量/日期/标题/链接严格同源（实测柱子与卡片链接 15 vs 15 顺序与地址完全相同，15 条链接两两不同且各自含自身 `item_id`）。**任务四**：移除「视频表现口径对照」模块的页面展示（`CompareRows` 公共组件保留未删）。**无数据库 Schema 变更、无迁移、无回填、未改任何后端文件**（`backend/**`、`contracts/**`、`migrations/**` 零改动）。验证：真实 Chrome（项目 Playwright MCP `1.62.0-alpha-2026-06-29` + 本机 Chrome）**38/38** 通过（含 API 逐条核对、真实鼠标 Hover、点击跳转与链接唯一性、390px、刷新、两入口一致性、Console Errors 0 / 失败 API 0）；前端 **68 passed**、后端单测 **213 passed**、lint/build/`ruff`/`mypy`/`git diff --check` 通过。**未完成 2 项**：①视频封面无法渲染——JSONB 中 `item_cover`/`head_image_uri` 是平台对象存储的**不透明 key**（全库 1845 条非空封面中 **0 条**是完整 URL），精选卡片能显示封面是因其契约字段返回 `p3-star-fe-sign.byteimg.com` 已签名外链并由 `CoverPipeline` 入库，最近视频记录无等价字段；本轮**不构造未经验证的 CDN 地址**，按现有占位降级并如实标注，故 CRE-14 以"降级正确"通过但"显示真实封面"未达成；②**参考图片未提供**，CRE-21 未执行。详见[验收证据](../evidence/CD-05-creator-detail-tabs-and-video-chart-2026-10-15.md)。


# 2026-10-15 CD-04：达人详情「商业能力」模块重构与字段联通（已完成）

[CD-04](CD-04.md) 把「达人详情 → 商业能力」从字段分区堆叠重构为业务结构：**传播价值**（内容数据 7 项 + 性价比/效果预估 6 项 + 优秀传播视频）、**种草价值**（6 项指标 + 优秀种草视频）、**转化价值**（5 项）；按用户第 2 轮调整**去掉「报价明细」与「历史合作行业」**两个模块（纯展示层移除，数据与 API 未删；任务入口的报价改由该入口自己的「报价与历史」章节承载，达人库入口原章节保留）。关键落地：①两处平台口径换算按线上确证执行——`interaction_rate`/`completion_rate` 的 `value` 与 `overtake` 都是**万分比整数**（`112`→`1.12%`、`7493`→**优于** `74.9%` 同类型达人），`average_duration` 为**秒×100**（`10140`→`101.4 秒`）；②数量单位按用户确认的 **w/k** 规则（≥1万→`93.0w`、1千–1万→`9.7k`、<1千原数，四舍五入 1 位，新增 `countWanText`）；③种草/转化共 9 项区间字段**原值直出**（`5,000 - 15,000`、`500以下`、`3万-3万`），不取中值、不换算、不推断币种，上下限相同也保留两段；④6 处改名（商单视频平均看后搜次数/看后搜率/小蓝词点击率、个人视频平均看后搜次数/看后搜率、A3增长数、视频播放中位数、组件点击量/点击率、CPC）经用户确认执行，并明确标注"名称与平台统计口径不完全一致"与"未拆分为单条视频均值"；⑤视频卡片抽成共享组件，两组集合仅数据源不同，展示真实封面（走项目对象存储授权端点）、真实标题、真实播放/点赞/评论与平台作品链接（`target=_blank`）。**新增两条只读端点**（`GET /api/creator-library/{cid}/contents`、`.../covers/{object_id}`）使达人库入口也能看到真实精选视频，并按达人归属校验（越权实测 404）；**无数据库 Schema 变更、无迁移、无回填、未删改既有 API 字段**。验证：真实 Chrome（Playwright MCP `1.62.0-alpha-2026-06-29` + 本机 Chrome，两入口 × BIZ-01…BIZ-24 + 逐张封面字节校验 + 封面缺口如实呈现 + 空值/刷新/390px）**52/52** 通过；前端 **61 passed**、后端单测 **213 passed**、lint/build/`ruff`/`mypy`/`git diff --check` 通过；CD-02 回归 **31/31**、CD-03 回归 **38/38**。另按第 3 轮反馈核查并修复：经用户提供的 404 证据逐行核对，确认**封面记录与封面文件不一致**——`media_objects` 有 310 条 `kind='cover'` 记录，但对象存储里只有 155 个文件；页面读取的最新快照 153 张引用中 **81 张缺文件**（C位小师妹等 13 位达人首页全缺），缺失内容无同 checksum 副本、平台签名 URL 实测全部 403，**本卡范围内不可恢复，需重新采集**（已在卡片列为待用户决策项）。前端改为**区分「封面文件缺失（需重新采集）」与瞬时加载失败**、失败自动重试最多 2 次、并按用户要求**移除卡片右上角分享 icon**（跳转仍由封面覆盖层承担）；新增 `BIZ-23-share-icon-removed`、`BIZ-09-BIZ-13-cover-delivery`（必须 200 + `image/*` + 字节数 > 1000）、`BIZ-24-cover-file-gap` 三项机器校验。实现中发现并修复 3 个真实缺陷：达人库卡片行形状（字段在 `payload` 内）未解包、视频互动数据是 `FieldObservation` 数值封套被当数字串、`FieldView.state` 无法区分"已采集但无值"。未完成/未验证：进店成本/预期播放量/爆文率本项目未采集（需采集授权）；预期 CPM/CPE 与商业 CPM/CPE 的刻度关系仍未线上确证（按原值展示）；隔离 PostgreSQL 集成测试库 `55439` 仍不可连接；未实际打开抖音外链播放。本轮未引入 P0 问题。详见[验收证据](../evidence/CD-04-creator-commercial-workspace-2026-10-15.md)。

# 2026-10-15 CD-03：达人详情页面左侧信息模块调整与字段联通（已完成）

[CD-03](CD-03.md) 按用户本轮要求，只调整达人详情「左侧信息模块」：①去掉左栏的「采集完整／数据不完整」标识、②「观测时间」、③「完整性」状态、④达人库入口的指定说明文案、⑤左栏「数据来源」展示区域；⑥昵称下方新增真实**星图ID**（`basic.platform_creator_id`，与参考图 C位小师妹 `7360610271510921225` 同源，非内部 UUID）；⑦四项指标改为 **月连接用户 → 月深度用户 → 粉丝 → 月涨粉率**；⑧三项数量指标按用户确认的 **万/k** 规则展示（`2,344.0万`／`≈1,158.0万`／`135.2万`，只作用于展示层）；⑨「内容主题」与「行业标签」互换位置；⑩新增**性别**（读真实 `basic.gender` 编码，`2=女` 有线上确证并标注，`1/0` 按确认的常规编码展示并注明未复核）；⑪新增**介绍**（读真实 `basic.introduction`，支持换行与长文本折行）。字段联通坚持最小改动：`gender` 由达人详情 API 从**已有** JSONB 投影读取并新增 1 个只读响应字段（**无数据库 Schema 变更、无迁移、无回填**），`introduction` 早已在 API 中、本轮首次在左栏展示。为不丢失 CD-02 的字段来源能力，左栏之外保留一个文字入口打开原「数据质量与字段来源」抽屉（81 字段仍可查看）。验证：前端 **55 passed**（新增 `countUnitText` 边界 5 例与左栏 2 例）、后端单测 **210 passed**（新增 1 例性别映射）、lint/build/`ruff`/`mypy`/`git diff --check` 通过；真实 Chrome（项目 Playwright MCP `1.62.0-alpha-2026-06-29` + 本机 Chrome，两入口 × 11 项 + 空值/长文本/刷新/路由/API/390px）**38/38** 通过，并复跑 CD-02 既有回归 **31/31**（其中 2 项因 4.10 移除入口如实记为 SKIPPED，未记为通过）。发现并修复 2 个真实问题：单位小数位应为四舍五入而非截断（平台 `1,351,784 → 135.2w`）、直接删入口会让字段来源能力不可达。未完成/未验证：性别 `1/0` 缺线上复核；隔离 PostgreSQL 集成测试库 `55439` 仍不可连接（沿用 CD-01/CD-02 项）；未做像素级视觉对比。详见[验收证据](../evidence/CD-03-creator-detail-rail-2026-10-15.md)。

# 2026-10-14 CD-02：达人详情页面数据展示与 UI/UX 优化（待验收）

[CD-02](CD-02.md) 按用户批准的《达人详情页面数据展示与 UI/UX 优化方案》完成第二轮重构：新增只读字段目录端点（8 模块 / 81 字段的中文名、kind、单位、周期、空值语义，含 4 处带实测证据的 `fans.*` 显示名修正），详情页改为"左栏身份资料卡 + 达人概览／商业能力／创作能力／履约能力／连接用户（达人库另有报价与历史）"。首次把此前完全未展示的 `creation.video_content_distribution`/`hot_comment_tokens`/`content_theme_density`/`performance_descriptions` 与精选作品的播放/点赞/评论呈现出来；连接用户分层按"阶段 1–4 互斥 + 阶段 5 合计"渲染并显示一致性结论（不画漏斗图），三组平台内置趋势分别标注口径，互动率/完播率保持平台原值 + 同行超越原值。后端单测 195、前端 45 例、lint/build、`ruff`/`mypy`/`git diff --check` 通过；真实 Chrome（Playwright MCP + 本机 Chrome）**30/30** 检查通过，含 390px 移动端无横向溢出。（2026-10-15 由 [CD-03](CD-03.md) 复跑为 **31/31**，其中 2 项 provenance 检查因 CD-03 需求 4.10 移除左栏入口记为 SKIPPED。）未改采集契约、写入路径与数据库结构；`snapshot_index` 缺 20 条历史索引与达人库精选作品封面授权按方案默认保持待确认，页面已如实提示缺口。随后按要求完成**数据准确性核对**：库内→API→页面逐字段保真 121/121、真实 Chrome 31/31、库内 vs 巨量星图线上逐项判定 same 17 / time-shift 16 / note 2 / **different 0**（未发现虚造或改写），并据线上证据确证 7 项口径（互动率/完播率 ÷100、超越值 ÷100、平均时长=秒×100、报价币种￥、性别编码 2=女、连接用户分层名称 了解/兴趣/喜欢/追随），同时修复 4 个真实缺陷（含 19 位星图ID 被数字格式化丢精度的严重问题）。详见[实现与验收证据](../evidence/CD-02-creator-detail-workspace-2026-10-14.md)与[数据准确性核对](../evidence/CD-02-platform-parity-2026-10-14.md)。

# 2026-10-14 FILTER-01：巨量星图背景信息与受众画像筛选（已完成）

[FILTER-01](FILTER-01.md) 已完成 RequirementForm/FilterPlan v2、结构化能力 API、背景信息与受众画像八个控件、M3 确定性映射、局部页面筛选执行器和 `attribute_filter` 多重集精确关联；保留 v1 历史读取，Workflow 图拓扑不变。真实 Chrome 以 `unit-local-mac-02` 的受控 Profile 验证背景四项、地域、五段区间、粉丝量级、两类画像、互斥与完整组合。任务终态曾为 `PROFILE_SCOPE_INCOMPLETE`，已确认是既有 F05/F06 资料字段采集问题，不阻断本卡；详见[验收报告](../evidence/FILTER-01-acceptance-2026-10-15.md)。

# 2026-10-14 SESSION-01：登录状态核验有效 + “快速失效”根因记录（进行中）

用户要求核验执行单元星图登录状态、必要时唤起 Chrome 人工登录，并记录“登录态为什么很快失效”。只读核验结论**有效**：`xingtu session-diagnostics`（`15:49:46 → 15:49:53+08:00`，exit 0）得到 `VALID`、`observed == expected == ID: 1807978499337419`、受保护页 `true`、登录页／挑战 `false`、私有快照在首个导航前恢复（这是快照路径首次在账号 DOM 可读条件下的 `VALID`）；未搜索、未采集、未写业务库。存活下界更新为**约 29 小时且跨越 3 次冷启动**，上界仍未测。根因记录：业务会话 `.xingtu.cn/star_sessionid` 是**会话级 Cookie**，跨重启完全依赖私有 `storage-state` 快照，而 **2026-10-13 16:48 之前从未产出过快照**（身份不可读，门槛不满足），因此那时每次关闭 Chrome 都会真的丢会话；`--use-mock-keychain` 与子账号漂移是次级放大器，**无证据表明平台会话本身只有几十分钟寿命**。同时登记 5 项待优化缺口（快照写入触发过窄、与身份门槛耦合、恢复失败不可观测、无阶段巡检、H1 跨客户端互踢未排除）。已按用户要求以专属 profile 打开受保护业务页供人工查看（无需重新登录）。证据：[登录状态核验与快速失效根因记录](../evidence/SESSION-01-login-lifetime-root-cause-2026-10-14.md)。[SESSION-01](SESSION-01.md) 保持**进行中／未验收**。

# 2026-10-14 CD-01：达人详情数据展示与 UI/UX 优化（待验收）

[CD-01](CD-01.md) 已实现统一任务快照与达人库当前资料的详情框架，并在第二轮将首屏升级为身份/数据范围 Hero 与商业决策 KPI 带，保留基础/商业/内容与视频/连接用户/种草转化/履约/报价历史/数据来源及 81 个字段的状态、原始口径和数据关系。Lazyweb 公共 MCP 已实际调用两次但查询结果为空，未伪称获得设计参考；真实 Chrome 已回归两入口和 390px 移动端，前端 9 例与构建通过。隔离 PostgreSQL 集成测试库 `55439` 仍拒绝连接，故卡片待验收；详情 UI 不改变采集流程，LIB-01 数据治理仍独立评估。

# 2026-10-14 UI-01：前端页面优化（待验收）

[UI-01](tasks/UI-01.md) 按用户需求完成 5 项前端页面优化：①登录页密码显示/隐藏切换（默认隐藏、切换不清空、登录不受影响）；②主导航移除与任务中心重复的「创建任务」入口并新增「工作台」分区标签，任务中心页内入口保留；③「任务内达人」按达人库口径补齐头像、昵称、标签、粉丝、月深度用户、互动/完播原始值、CPM/CPE（21–60 秒与 60 秒以上两档），取值全部来自任务不可变快照的真实字段；④核实「最近更新」= `root_tasks.updated_at`（最后写入审计值，不等于完成时间），经用户明确授权新增迁移 012 的 `completed_at`，仅在进入终态时写入，终态页面展示「完成时间」；⑤抽出共享 `CreatorDetailView`，任务入口与达人库入口的同一达人详情字段名、取值与 KPI 区逐项一致（任务入口保留精选作品、达人库入口保留报价与历史快照，按各自真实数据来源）。真实 Chrome 页面级验收 **38/38 通过**（含控制台与网络记录、8 张截图），`ruff`/`mypy`/单元 189/集成 81+1 skipped/前端 9 例与构建全部通过。**未发起任何真实采集**（复用既有真实任务 `efb257a6` 的数据），因此真实采集链路上的 `completed_at` 写入与 Playwright MCP 工具直调仍未验证，卡片保持**待验收**。详见[验收证据](evidence/UI-01-frontend-optimisation-2026-10-14.md)。

# 2026-10-14 DEV-01：星采本地全栈一键启停入口（已完成）

[DEV-01](tasks/DEV-01.md) 新增 `./dev.sh`（实现 `scripts/dev.sh`），把「确保依赖 → 前置自检 → API + P1 Intake Worker + P2 采集 Worker + 前端页面 → 就绪校验」收敛为一条 `up` 命令，并提供 `stop` / `restart` / `status` / `logs` / `check`。`up` 采用接管而非叠加（已在监听/运行的进程记录 PID 复用，重复 Worker 清理为每账号一个），`stop` 只结束本脚本记录过的进程并连同 `npm run dev` 的子进程树一并结束。2026-10-14 实跑：`PREFLIGHT_OK`（13 项）、`restart` 完整停启（旧 PID 全部退出、新 PID 5 秒内就绪）、`up` 幂等，Playwright + 本机 Chrome 登录 `media-a` 后任务中心 21 行与达人库「20 位已加载」渲染正常（[证据](evidence/DEV-01-launcher-2026-10-14.md)）。**2026-10-16 追加**：按用户要求做全栈重启（`stop` → 人工清理游离进程 → Compose 依赖 down/up → `up`），`PREFLIGHT_OK` 12 项、四进程新 PID 就绪、两个 Temporal 队列在线，只读抽查 login/tasks(20)/creator-library(20)/capabilities/health 均 200；同时登记**未修**的 `stop` PID 记录盲区（API 与另一终端的前端非脚本记录者，需人工结束）（[重启证据](evidence/DEV-01-restart-2026-10-16.md)）。**同日第二轮**：用户再次要求重启，起始时应用进程与 **Docker 守护进程**均已停止——先 `open -a Docker`（30 秒内就绪，server 29.1.3）、再 `./.runtime/dev-up.sh up` 与 `./dev.sh up`，`PREFLIGHT_OK` 12 项、四进程新 PID（94968/94992/95009/95018）就绪，`pids.tsv` 与真实进程逐一对应（上一轮盲区未复现）、5174 未监听，只读抽查全部 200。属工具入口验证，不构成平台能力或生产就绪证据。**2026-10-17 第三轮**：用户要求重启所有服务；起始四进程均在运行，但 `./dev.sh check` 因单元 `SESSION_UNVERIFIED` 拒绝启动。先用产品 API 提交最小任务让 P2 实测会话、把单元恢复为 `READY` 后取消任务，再标准 `./dev.sh restart`：`PREFLIGHT_OK` 12 项、四进程新 PID（25515/25539/25556/25565）就绪、单元重启后仍 `READY`/`VALID`，只读抽查全部 200（[重启证据](evidence/DEV-01-restart-2026-10-17.md)）。

# 2026-10-13 LIB-01：抖音星图达人库（进行中）

[LIB-01](LIB-01.md) 的真实采集、JSONB/三张读模型一致性及页面功能均已通过；但严格对照改造方案后，读模型缺数据库级追加式保护、字段级来源快照/metric sources、部分规划索引和当前报价语义，故重新打开，不签发“完全符合方案”。详见[符合性复核](../evidence/LIB-01-scheme-conformance-review-2026-10-14.md)。

# 2026-10-13 DATA-01：达人 JSONB 结构化与平台隔离设计（已完成）

[DATA-01](DATA-01.md) 已完成只读数据库、采集契约和持久化路径审计：当前开发库有 11 个巨量星图平台达人、39 份不可变快照；`platform_creators.projection` 是当前成功字段投影，`creator_snapshots.payload` 是完整历史载荷。用户确认一期严格隔离平台账号、不识别同一自然人、报价按合作形式处理、指标不跨平台换算。交付[改造方案](../达人数据JSONB结构化与多平台兼容改造方案.md)、[81 字段字典](../达人数据字段字典.md)及[脱敏审计证据](../evidence/DATA-01-database-audit-2026-10-13.md)。本卡不含迁移或代码实施。

# 2026-10-13 SESSION-01：受限人工确认已启用，快照复用已核验（进行中）

用户授权对唯一绑定子账号 `ID: 1807978499337419` 作最长 31 天的本机开发人工确认；仅在受保护页存在、登录／挑战页不存在且账号 DOM 不可读时生效。真实 Chrome 三次冷启动确认 `VALID / MANUALLY_ATTESTED_UNIQUE_ACCOUNT`，私有 `storage-state` 已保存并在下一次首个导航前恢复；没有执行采集。平台会话寿命、账号漂移根因与长期观测仍未完成，详见 [SESSION-01](SESSION-01.md) 与[证据](../evidence/SESSION-01-manual-attestation-snapshot-2026-10-13.md)。

# 2026-10-13 本机资源与同步残留排查（进行中）

[MAINT-01](MAINT-01.md) 当前**阻塞**于系统管理员权限／Docker 数据保护决策：Data 卷只余约 **3.3 GB**；Docker 启动日志已确认 `no space left on device`，而非内存 OOM。Cursor 权限已生效并证实 iCloud 缓存不足 50 MB、不是主因；已删除 748 MB 的 Google Updater 下载缓存。Docker.raw 实占约 3.0 GB且可能含数据库卷，未删除；其磁盘上限调整会销毁所有本地 Docker 数据。无活跃模拟器的 3.0 GB CoreSimulator cache 可无损再生成但由 root 所有，需管理员权限。Documents 下其他项目依赖均为 0 B 本地占用，未作无收益删除。

# 2026-10-12 当前执行单元星图登录状态实时核验（只读）

用户询问"当前执行单元内巨量星图的登录状态是失效还是有效"。先固定对象：开发库只有 `unit-local-mac-02` 一个执行单元（`.runtime/units/local-dev-mac-02.json`，绑定账号 `ID: 1807978499337419`，profile `.runtime/profiles/unit-local-mac-02`）。库中 `last_session_status=VALID` 的时间是 `2026-10-12T01:12:41+08:00`（14.4 小时前），而项目契约明确"持久化状态不构成活动会话证明，只有当前进程观测可产生 `VALID`"，故用户授权后补做只读进程内观测：`xingtu session-diagnostics`（`15:36:53 → 15:37:01+08:00`，exit 0）→ **`SessionHealthStatus.VALID`**，账号精确等于绑定账号，受保护页可见，无登录页、无安全挑战。**结论：有效**；未搜索、未采集、未写业务库。新增 SESSION-01 存活时长下界数据点（≥14.4 小时且跨冷启动，账号无漂移），上界仍未测。证据：[会话实时只读核验证据](../evidence/UNIT-01-session-live-check-2026-10-12.md)。[UNIT-01](UNIT-01.md) 保持**待验收**、[SESSION-01](SESSION-01.md) 保持**进行中／未验收**。

# 2026-10-11 MCP 原生工具 UI 端到端复跑

以已注册到 profile 的原生 `mcp__playwright__*` 工具 + 真实 Chrome 复跑「发起 → 需求转换 → 状态流转 → 任务中心 → 取消」：13 条用例 12 PASS / 1 FAIL。PASS：登录门禁、发起「露营/3」→ `QUEUED` v3（2.67 s，真实 1126/88 tokens）、阻塞面板（`t+140 s`，且此时 `consumer_alive=true` 仍被判阻塞）、`RECEIVED` 阶段取消 → `CANCELLED` v1（0 次模型调用）、会话跨 API 重启、控制台无 JS 异常。FAIL：**DEF-01** 已 `QUEUED` 任务取消停在 `CANCELLING`（需 P2 收尾，P1）。另有 3 条低级问题（Vite 代理在 API 停机窗口返回 500、`browser_wait_for` 长等待提前返回、主动取消被显示为「需要关注」）。报告见 [MCP UI 端到端测试报告](../testing/mcp-ui-e2e-2026-10-11.md)。

# 2026-10-11 RECEIVED 永久停留缺陷修复（本轮）

用户 UI 提交的产品任务长期停在 `RECEIVED`。真实样本 `3c96c78a-77f8-4e11-8081-953b12deae91`（media-a / 关键词「户外」/ 目标 4）停留 **7 小时 8 分**，`intake_dispatches.sent=false` 且 `updated_at == created_at`，`model_runs`/`filter_plans` 均为 0。

根因（已验证，两个独立条件）：① 产品入口独有的常驻 P1 Intake Worker 没有运行；② 缺少 `DEEPSEEK_API_KEY`，该 Worker 启动即 `DEEPSEEK_API_KEY_REQUIRED` 退出。原 `docs/development.md` §5 启动步骤只含 API 与前端，`make dev` 也只起 Compose，因此按文档操作必然复现；缺消费者时系统没有任何失败面。

本轮最小修复：`make m3-check`（13 项只读前置自检）与 `make m3-up`（启动 API + Intake Worker 并在出现**新鲜消费者**后才 READY，新增 `collection-worker` 目标）；派发循环异常隔离 + 派发失败留痕；`TaskDetail.intake` 三态可见性（`INTAKE_WORKER_UNAVAILABLE` / `INTAKE_DISPATCH_FAILING`）与 `GET /api/health/workers`；`promote_intake` 失败终态化；`no_proxy` 中 `[::1]` 导致 httpx `InvalidURL` 的环境缺陷修复。

复核：真实 DeepSeek + 隔离 schema 下 `RECEIVED`（无消费者）→ `QUEUED`（+1.71 s），真实 `model_runs` 1126/88 tokens、1262 ms，`filter_plans` 与确定性期望完全相等。分层回归：`make check` exit 0（单元 178 passed）、集成 69 passed/1 skipped、契约 28 passed、e2e 9 passed。证据见 [M3 Intake Worker 修复证据](../evidence/M3-intake-worker-fix-2026-10-11.md)；[INTAKE-01](INTAKE-01.md) 已回到**已完成**：2026-10-11 23:08 用真实 Playwright MCP + 真实 Chrome 完成完整 UI 复跑（登录 → 发起「户外/4」→ `QUEUED` v3 @ t+1.61 s → 无 Worker 时阻塞面板 @ t+120.5 s → UI 取消 → `CANCELLED` v1、0 次模型调用），浏览器控制台无 JS 异常；P2 采集段仍需单独采集授权。

机制修正：Temporal poller 的 `last_access_time` 是粗粒度信号（健康 Worker 实测刷新间隔 58/58/121 s，停止后条目仍保留数分钟），“无人接管”判定改为任务级 120 s + 无派发失败记录，poller 阈值 180 s 仅作诊断元数据。

# 2026-10-11 完整新任务闭环修复复核（历史）

本轮继续处理“完整端到端闭环未成功”的问题。首次冒烟的新任务 `b12b5785-f90a-42c2-8c4f-67c54ab690e4` 停在 `RECEIVED`，原因是当时只运行 API/前端，没有运行 Intake Worker/Collection Worker，且没有 `DEEPSEEK_API_KEY`。本轮启动本地受控 Intake/Collection Worker，并使用 localhost-only DeepSeek-compatible Fixture，不把 Fixture 误报为真实 DeepSeek。

通过 Playwright MCP 创建并完成新任务 `acd929aa-874e-4de8-8fb1-6a9295cf07ff`：`RECEIVED → PARSING → QUEUED → COLLECTING → COMPLETED`，最终发现 20、有效 1、资料完整 1、精选完整 1、失败 0。另修复任务终态后达人列表未刷新问题，页面最终显示“1 位可查看 / 已发布快照”。完整证据见[冒烟报告](../testing/smoke-test-f04-f05-f06-m3.md)。

当前边界：真实 DeepSeek 新任务现场调用、真实自然安全验证恢复、生产 HTTPS/Secure Cookie/正式域名仍未验收；相关卡片不得因本地 Fixture 闭环通过而拔高状态。

# 2026-10-10 F04/F05/F06/M3 核心冒烟复核

2026-10-10T23:15+08:00 修复追记：冒烟后继续修复既有真实产品任务 `f47eb1cf-f038-4f9f-ae3d-e02aa8a995d3`。最小改动为在 verified contract 中显式登记 `seeding.search_word_ctr` 与 `fulfillment.message_reply_rate` 的成功响应缺源口径为 `NO_DATA`；随后启动 P2 Worker 并 retry，同一 root 已达到 `COMPLETED`，`profile_complete_count=2`、`featured_complete_count=2`、`pipeline_complete=true`。前端/API/DB 已复核一致。详见[冒烟报告修复追记](../testing/smoke-test-f04-f05-f06-m3.md#2026-10-10-修复追记既有真实产品闭环已补齐到-completed)。新建任务当场创建并执行到完成仍依赖重新提供 `DEEPSEEK_API_KEY` 并运行 Intake Worker。

高级 QA 冒烟测试已执行并生成完整报告：[F04/F05/F06/M3 核心冒烟测试报告](../testing/smoke-test-f04-f05-f06-m3.md)。本轮完成 Git/服务/MCP 基线、现有脚本盘点、后端四层回归、MinIO 专项、Playwright MCP 真实 UI 登录/创建/取消/结果查看/退出，以及 API/DB/前端跨层一致性验证。结果：F04 核心冒烟 PASS 但完整新任务执行受 worker 未启动阻塞；F05 自动化 PASS、真实样本为 `PARTIAL_COMPLETED` 且展示一致；F06 PASS；M3 本地 UI/API/DB 冒烟 PASS；CHALLENGE-01 合成回归 PASS 但真实自然挑战仍待验收。

本轮新建受控任务 `b12b5785-f90a-42c2-8c4f-67c54ab690e4` 已通过 UI 取消，避免后续真实平台采集；既有真实结果任务 `f47eb1cf-f038-4f9f-ae3d-e02aa8a995d3` 用于结果读取一致性验证。当前状态不拔高：F04、APP-01、CHALLENGE-01 仍待验收；F05、F06、INTAKE-01、CONSOLE-01 保持已完成。

# 2026-10-10 F05 安全验证托管实施

[CHALLENGE-01](CHALLENGE-01.md) 已完成后端托管主链路、产品查询摘要、旧检查点兼容、恢复减量入口、官方开放能力字段矩阵，以及任务详情页等待安全验证展示。续作回归：164 项单元、28 项 Browser Contract、67 项后端集成（1 skipped）、7 项 E2E、前端类型/3 项单测/构建均通过；挑战专项集成 2 项通过。当前状态为**待验收／未验收**：真实平台自然挑战、同页真实恢复、一次恢复只增加一次 `session_version` 及重复请求下降 50% 仍待补证。详见[实施证据](../evidence/CHALLENGE-01-implementation-2026-10-10.md)与[DEC-015](../decisions/DEC-015-security-challenge-orchestration.md)。

# 2026-10-10 M3 真实 DeepSeek 与产品闭环验收

在 localhost 开发环境中，使用真实 DeepSeek Flash、PostgreSQL、Temporal、现有 `unit-local-mac-02` 和已核验星图关键词能力完成产品闭环：`media-a` 提交“游戏剧情”、目标 2，任务按 `RECEIVED → PARSING → QUEUED → COLLECTING → PARTIAL_COMPLETED` 执行，最终发现 20 位、有效 2 位、发布 2 份任务快照，并保存优秀传播 8 张、优秀种草 6 张卡片及 14/14 个封面。真实 Chromium 完成两媒介共享读取、退出后旧 Cookie 失效、重登恢复与任务内结果查看；真实 DeepSeek `model_runs`、幂等提交和 P1→P2 同根晋级均已核对。任务因一位达人 `fans` 模块响应 Schema 变化如实保持部分完成，未修改 F04/F05/F06 采集逻辑。详见[真实产品闭环证据](../evidence/M3-real-product-acceptance-2026-10-10.md)。[INTAKE-01](INTAKE-01.md) 与 [CONSOLE-01](CONSOLE-01.md) 已完成；[APP-01](APP-01.md) 仅剩本轮明确不执行的生产 HTTPS/域名/Secure Cookie 环境验收，状态为待验收。

# 2026-10-10 M3 本地产品控制台启动与真实数据联调

应用迁移 008 后，以 `.venv/bin/xingtu-api`（`127.0.0.1:8000`）+ `npm --prefix frontend run dev`（`127.0.0.1:5173`）启动 M3 产品页面，并在**真实开发库**（`127.0.0.1:55432 / xingtu_development`，迁移前已 `pg_dump` 备份）与**真实 Chromium** 上完成只读联调：11 条真实任务列表、任务详情四类计数、达人 F05 字段与 F06 双集合、4 张 `STORED` 封面经认证 HTTP 200（无会话 401、跨任务 404）、两媒介账号共享读取、页面刷新保持会话与退出回登录；浏览器无运行错误。该阶段未提交新任务、未推进任务状态，且当时环境没有 DeepSeek 凭据，因此三张 M3 卡仍为进行中；后续真实闭环及最新状态见上一节。详见[本地控制台启动联调证据](../evidence/M3-local-console-startup-2026-10-10.md)。

# 2026-10-08 F05 六字段补采完成

[F05](F05.md) 已按指定达人 `6963508724337999903` 补齐介绍、月连接用户数、月深度用户数、月涨粉率、达人类型和行业标签。正式主页清单由 75 字段升级为 81 字段；两次真实重采后开发库仍只有 1 条达人主记录、不可变快照由 2 份增至 4 份，最终任务 `COMPLETED / profile_complete_count=1`。`make check`（122 单元）、28 项 Browser Contract、56 项 PostgreSQL 集成（另 1 项专用 MinIO endpoint 未配置而跳过）和 4 项 Temporal E2E 通过。详见[六字段验收证据](../evidence/F05-six-fields-2026-10-08.md)。

# 2026-10-07 F05/F06 真实闭环验收完成

[F06](F06.md) 与其 [F05 前置](F05.md) 均已完成并验收：真实账号核验 F05 的 8 模块/75 字段，以及优秀传播/优秀种草两组默认集合；两位契约样本覆盖 4/4 与 4/0 真实空态。MinIO 幂等初始化、写后读回、重启持久性、任务内授权、跨任务拒绝、孤儿清理和同根任务失败恢复全部通过；真实两达人根任务达到 `COMPLETED`，`profile_complete_count=2`、`featured_complete_count=2`。最终回归为 120 单元、26 浏览器契约、57 PostgreSQL + MinIO 集成、4 Temporal E2E，共 207 项通过且无跳过。详见[证据](../evidence/F06-live-contract-minio-2026-10-07.md)。

# 2026-10-06 达人完整资料与连续分页实施

[AUTO-01](AUTO-01.md) 已完成当前可离线实施部分：主页从 9 个基础字段扩展为 6 模块/61 个结构化字段，新增首页加载多模块响应捕获、连续分页能力门槛、连续两页无新 ID 保护，并通过 130 项单元/浏览器合约与 52 项范围内 PostgreSQL 集成测试。真实 Page 1/Page 2 仍返回各 20 位且 ID 摘要不同，主页业务端点仍存在。修复研究工具后重启 Chrome 出现 `ACCOUNT_MISMATCH`，按既定范围停止真实测试；需人工选择/登录 `ID: 1865332309937515`后继续 Page 3 与 61 字段数据库对照。AUTO-01 为**阻塞/未验收**，F04/F05 仍为**待验收**。详见[2026-10-06 实施证据](../evidence/AUTO-01-profile-pagination-implementation-2026-10-06.md)。

# 2026-10-05 子账号回退诊断链修复 + 真实 A/B 进行中

2026-10-06 发布前复核：本地与 `origin/main` 无分叉，明文凭据扫描通过，`make check`（107 单测）、21 项 Browser Contract 及探针 10+2 项自检通过。本轮仅发布已记录的安全修复和诊断证据；SESSION-01 状态仍为进行中／未验收。

[诊断链实施证据](../evidence/SESSION-01-subaccount-diagnostics-implementation-2026-10-05.md)：已修正页面跳转丢失最后点击与 `add_init_script` 未真正执行的缺陷，新增 Python binding、脱敏请求—响应—会话检查点、Playwright `locator.click()` 及受限 A/B 开关；最终 `make check`（107 单测）和 21 项 Browser Contract 通过。正式 Adapter 自动选号保持关闭，见 [A/B 手册](../handoffs/SESSION-01-browser-ab-runbook.md)。

登录页／业务页逻辑已闭合：维护和采集优先进入受保护业务页，有效会话展示登录后页面，真实失效才由平台跳登录；首次不可判定仅做一次有界 SSO 握手后回业务页复核。B1/B2 进一步证实 macOS Playwright 默认 mock keychain 会让自然 Chrome profile 的认证 Cookie 不可用并被清除；已用执行单元显式 `macos_system_keychain` 修复，只忽略 `--use-mock-keychain`，不改 UA、`navigator.webdriver`，不做 stealth。

A 组第三账号对照已通过：不经过 Playwright 的项目 profile 选择 `1831973402720484` 后，在选择后、刷新后、达人广场三个检查点均保持该账号。因此不是“所有非默认账号都会在项目 profile 中回退”。

A 组目标账号也已通过：从第三账号切到 `1865332309937515` 后，点击后立即、等待 10 秒、刷新和达人广场均稳定保持目标，且未曾短暂回退。由此排除目标账号当前不可用及项目 profile 自身异常。

B3/C 最终证明自动选号在当前 Playwright 环境中不可靠：目标条目收到可信点击，实际选号 POST 返回 HTTP 200并导航，但账号和 `star_sessionid` HMAC均不变；移除 `--disable-quic` 与 WebRTC UDP 参数后，4 次请求／54 个检查点仍相同。因此项目网络参数排除，不实施自动选号、Cookie 注入、自动化伪装或无限重试；优先在平台设置目标为默认账号，或为目标使用独立登录身份。

# 2026-10-05 账号漂移专项检测

新增只读探针 [account_drift_probe.py](../../scripts/account_drift_probe.py)（不点击／不登录／不切换账号，凭证只记 HMAC）。它把过去混为一谈的三种现象拆开判定：`DRIFT_WITHIN_PAGE`（同页反复读就变）、`DRIFT_WITHIN_PROCESS`（同进程跨页面/标签页变）、`DRIFT_ACROSS_RESTART`（重启 Chrome 后变，与 run 3→run 4 同型），并记录定位器匹配数、iframe 内匹配数、单页内不同 `ID:` 数量（H-A 直接判据）与凭证指纹做载体定位。人工登录期间不导航，人工窗口观测不计入漂移判定。离线自检 7 项判定 + 2 项载体/人工窗口用例通过，`ruff`/`format` 通过。

**本轮已确认**：

1. 用户现场确认目标子账号 `ID: 1865332309937515` 在平台子账号列表中**可见且可选** → 排除"父账号无权访问目标子账号"，问题指向**自动化缺少"选定目标子账号"步骤**（契约 `session` 段无任何选号动作）。`子账号` 概念在 `docs/` 与 `backend/` **全仓零命中**，技术方案 U06 要求账号识别却未定义选号流程，属**文档/PRD 缺口，需产品侧补需求**。
2. **漂移真实复现**（[证据](../evidence/account-drift-probe-2026-10-05.md)）：人工登录并选定目标子账号后，间隔约 3 分钟重启 Chrome，生效账号由 `1865332309937515` 变为 `1832740070238347`（与 run 4 一致），判定 `IDENTITY_CHANGED_WHILE_UNREADABLE`（退出码 1）。同一进程内跨页面/同页反复读/第二标签页均为目标账号，排除页面差异与多标签页解释。
3. **缺陷 D1 与漂移同源**：漂移后受保护壳不渲染 → 账号定位器匹配数 0、受保护页不可见 → 系统只得 `SESSION_INDETERMINATE`。D1 是"错误账号"被误分类为"会话不可判定"。
4. **载体收敛**到唯一变化的身份 Cookie `star_sessionid`；`possess_scene_star_id`、`session_tlb_tag` 逐字节未变，原推测被否定。

**未完成**：H-A 与 H-B 仍未区分（只证明"生效账号改变"）；漂移属"重启触发"还是"时间触发"未测；长期存活仍未取得。[SESSION-01](SESSION-01.md)、[AUTO-01](AUTO-01.md) 相应验收项保持未勾选。

**2026-10-05 最小验证**（[证据](../evidence/account-drift-probe-2026-10-05-minimal-verification.md)）：① 客户端**未持久保存子账号**（`localStorage` 的 STAR 键为空数组）；② 重启后**确实落到默认子账号** `1832740070238347`，且冷启动时 SSO 登录在而 `star_sessionid` 缺失、**停在 SSO 入口页永不签发业务会话**；③ **自动选号尚未成功**——已排除"账号信息弹层"，真正选号入口未定位，按规范不猜选择器；④ **选中不跨重启保持**。漂移第二次复现且本次导航栏正常渲染、系统自身给出 `ACCOUNT_MISMATCH` → **D1 与 `WRONG_ACCOUNT` 是同一次漂移的两种表现**。**结论**：自动选号由"可选"变为**必需且每个新 Chrome 进程都要执行**；"往 Cookie 里加子账号"不可行。**阻塞**：定位选号入口需操作者提供人工切换路径。

# 2026-09-29 F04/F05 真实核心流程测试轮

独立测试角色复核 F04/F05 核心流程，证据见 [F04/F05 真实核心流程证据](../evidence/F04-F05-real-core-flow-2026-09-29.md)：离线 `ruff`/`format-check`/`mypy` 通过、**178 项测试全通过**（105/18/51/4）；真实 `target=2` 关键词搜索 + 2 位达人主页采集**通过**（`valid=2`、`discovered=20`、`search_exhausted=false`，`basic` 9 字段逐项带来源），真实 `target=25` 在单进程内连续采集 **7 位**后中断。

本轮登记三个未修复缺陷：**D1** 新 Chrome 进程账号元素不可读（任务内 5 次 + 独立诊断 1 次，`observed_account_id=null`）、**D2** 该 `SESSION_INDETERMINATE` 不打开登录窗口、**D3** 采集中途 `LEASE_LOST`（2 次，根因未定位）。三者叠加使真实 20/200 位与恢复验收不可达；F04/F05 因实机核验项（筛选枚举、访问节奏、分页、其余主页模块）仍未完成而保持**待验收**。

# 2026-09-29 会话寿命更正

[SESSION-01](SESSION-01.md)：**进行中／未验收**，不计入一期 12 项。原载“实测证明星图业务会话不能跨 Chrome 重启恢复”的结论因证据不足已撤回；当前代码与状态机以 [DEC-013](../decisions/DEC-013-structured-session-and-scoped-contract-health.md) 为准。

**2026-09-29 首次两段式真实验收（4 次运行）**，完整证据见[两段式验收证据](../evidence/SESSION-01-acceptance-2026-09-29.md)：

- ✅ **会话跨任务复用机制成立（历史四轮实测）**：单元为 `READY` 时以 `collect` 模式复用 Profile，`session_version` 不变、**未发生 promote、未要求人工登录**。该证据来自 DEC-012 时期；当前代码必须在新 Chrome 进程内重新得到 DEC-013 的 `VALID` SessionHealth，不能仅信任旧 `READY`。
- ❌ **发现账号在同一 profile 内漂移**：run 3 与 run 4 间隔约 3 分钟、无人工登录，实际账号却从 `1865332309937515`（绑定）变为 `1832740070238347`。这是 run 2／run 4 失败的直接原因。
- 已修复：账号不匹配独立为 `ACCOUNT_MISMATCH/WAITING_FOR_ACCOUNT`；旧 READY 不再提前证明当前 Session；过期租约可单步回收且不依赖 `/bin/ps`。账号漂移根因和长期寿命仍待单账号真实实验。

核验完成前不得以任一方向结论作为设计前提；"登录一次存活 1 个月"仍未达成。

结构性修复见 [DEC-013](../decisions/DEC-013-structured-session-and-scoped-contract-health.md) 与[实施证据](../evidence/SESSION-01-implementation-2026-09-29.md)：五态 SessionHealth、显式 ReleaseDisposition、HMAC 诊断、首次身份失败后的 Session 复核、达人级重试/跳过及 scoped breaker/回滚开关已实现；**178 项离线/合成测试通过**（105/18/51/4）。真实单账号清理、5/10/20 和 30 天长测未执行，故仍未验收。

# 2026-09-28 自动化优化补充

[AUTO-01](AUTO-01.md)：**进行中／未验收**，为跨现有功能卡的优化跟踪项，不计入原 12 个一期交付单元。2026-09-29 已实现单达人 `IDENTITY_UNREADABLE` 三次尝试后跳过续跑、按能力 scope 的 Contract breaker，并通过合成 20/200 位连续任务；旧“任务结束必回 NEEDS_LOGIN”已被 DEC-013 取代。未验收：真实全字段、第 3 页及终点、真实 5/10/20、50/100 与 7 天观察。


> 更新时间：2026-10-17T12:20:00+08:00。具体实现与验收事实只在各卡片及其证据维护；本表同步ID、标题、状态和链接。

**先看[项目任务进度总览](../项目任务进度总览.md)**：当前进度、推荐顺序、F/T/U覆盖、依赖及AI执行方式。

## 一期交付（12项）

| ID | 标题 | 状态 | 卡片 |
|---|---|---|---|
| BASE-01 | 必要工程基础 | 待验收 | [BASE-01.md](BASE-01.md) |
| UNIT-01 | 执行单元与平台核验（先本地后蜂窝） | 待验收 | [UNIT-01.md](UNIT-01.md) |
| F04 | 平台筛选、搜索与候选发现 | 待验收 | [F04.md](F04.md) |
| F05 | 达人主页资料采集 | 已完成 | [F05.md](F05.md) |
| APP-01 | 产品应用基础与登录会话 | 待验收 | [APP-01.md](APP-01.md) |
| INTAKE-01 | 筛选表单、P1转换与可靠提交 | 已完成 | [INTAKE-01.md](INTAKE-01.md) |
| F06 | 主页精选作品采集与封面存储 | 已完成 | [F06.md](F06.md) |
| CONSOLE-01 | 任务中心与任务内达人结果 | 已完成 | [CONSOLE-01.md](CONSOLE-01.md) |
| F09 | 手动更新达人（达人库入口，UPD-03） | 待验收 | [F09.md](F09.md) |
| F10 | 执行单元状态与远程登录维护 | 进行中 | [F10.md](F10.md) |
| F12 | 达人周期性更新（UPD-04） | 待验收 | [F12.md](F12.md) |
| OPS-01 | 生产运行、资源调度与运维恢复 | 待办 | [OPS-01.md](OPS-01.md) |
| RELEASE-01 | 一期全链路联调与上线验收 | 待办 | [RELEASE-01.md](RELEASE-01.md) |

## 2026-10-17 达人手动/周期性更新（UPD）

| ID | 标题 | 状态 | 卡片 |
|---|---|---|---|
| UPD-01 | 更新任务模型、迁移与执行单元能力配置 | 已完成 | [UPD-01.md](UPD-01.md) |
| UPD-02 | 统一执行单元池匹配、优先级与更新执行分支 | 待验收 | [UPD-02.md](UPD-02.md) |
| UPD-03 | 单达人手动更新闭环 | 待验收 | [UPD-03.md](UPD-03.md) |
| UPD-04 | 达人周期性更新调度器 | 待验收 | [UPD-04.md](UPD-04.md) |
| UPD-05 | 任务中心统一展示、文档与验收 | 待验收 | [UPD-05.md](UPD-05.md) |

## 2026-10-14 前端优化任务

| ID | 标题 | 状态 | 卡片 |
|---|---|---|---|
| UI-01 | 前端页面优化（登录密码可见性、导航菜单、任务内达人、完成时间、达人详情统一） | 待验收（真实采集链路完成时间写入未验证） | [UI-01.md](UI-01.md) |

## 2026-10-15 采集请求行为专项诊断

| ID | 标题 | 状态 | 卡片 |
|---|---|---|---|
| DIAG-01 | 巨量星图采集请求行为与验证触发专项诊断 | 待验收（人工基线对照未完成） | [DIAG-01.md](DIAG-01.md) |

## 2026-10-14 筛选能力扩展任务

| ID | 标题 | 状态 | 卡片 |
|---|---|---|---|
| FILTER-01 | 巨量星图背景信息与受众画像筛选 | 已完成 | [FILTER-01.md](FILTER-01.md) |

## 本轮修复任务（2026-10-12）

| ID | 标题 | 状态 | 卡片 |
|---|---|---|---|
| MAINT-01 | 本机资源与同步残留排查及安全清理 | 阻塞（待完全磁盘访问权限） | [MAINT-01.md](MAINT-01.md) |
| FIX-01 | 真实采集闭环修复（fans 模块 / 取消终态 / 采集 Worker 稳定性 / 取消展示） | 已完成 | [FIX-01.md](FIX-01.md) |

依据 2026-10-11～10-12 两轮 Playwright MCP + 真实 Chrome 实测建立。四类问题：**P0-A** F05 `fans` 模块读取失败导致真实采集永远收口为「部分完成」；**P1-B** 已 `QUEUED` 任务取消停在 `CANCELLING`；**P1-C** 采集 Worker 派发崩溃（已修、已补测试）；**P3-D** 主动取消被显示成「需要关注」。

**2026-10-12 收口结果（已完成）**：P0-A 用真实探针证明 `fans` 的 4 个请求全部 HTTP 200 / `base_resp.status_code=0`、契约字段路径全部存在，失败属**平台瞬时响应被拒绝**而非契约漂移或解析缺陷；为被拒绝响应补齐请求级脱敏诊断（请求 key / HTTP 状态 / content-type 类别 / 业务码 / 响应顶层 key），**未修改 verified contract、未放宽任何断言**。P1-B 经迁移 009（`task_dispatches.workflow_started_at`）+ `Activities.collect` 终态短路 + 取消分支判定，实现「从未启动采集 → 一步 `CANCELLED`；已启动 → 维持 `CANCELLING` 交 P2」。P1-C 补齐采集 Worker 5 例与 intake 等价 1 例单元测试。P3-D 中性文案与中性徽标落地。

**真实验收**：全新提交、不干预的任务 `7620fb83-019a-45c5-a547-1c42e2b12080`（宠物 / 目标 1）达 `COMPLETED`、`profile_complete_count=1`、8 模块全 `COLLECTED`（`fans` 9/9 字段）、2 组精选 `COMPLETE`、5 张卡片全 `STORED`，页面无「需要关注」；`QUEUED` 取消（`91a112ed-5dfe-488c-856d-c70e3109eecf`）一次 API 调用直达 `CANCELLED` v4。`make check` / 契约 28 / 集成 71+1 skipped / e2e 9 全通过。证据见 [FIX-01 真实采集闭环修复证据](../evidence/FIX-01-real-collection-close-2026-10-12.md)。

## 管理文档任务（不计入产品进度）

| ID | 标题 | 状态 | 卡片 |
|---|---|---|---|
| PLAN-01 | 项目进度基线与完整任务规划 | 已完成 | [PLAN-01.md](PLAN-01.md) |
| PLAN-02 | 开发与自动测试后强制回写任务进度 | 已完成 | [PLAN-02.md](PLAN-02.md) |

开发或MCP／工具测试结束后，由负责的AI按[开发规范第4.5节](../agent.md)自动回写原卡片，并同步本索引及项目总览，无需用户提醒。

## 依据

- [完整技术方案](../AI达人智能发现与采集系统-完整技术方案.md)
- [开发与运维说明](../development.md)
- [本轮静态基线证据](../evidence/PROJECT-BASELINE-2026-09-27.md)
- [本轮 UNIT-01 本地阶段证据](../evidence/UNIT-01-local-stage-2026-09-27.md)
- [本轮 UNIT-01 真实采集证据](../evidence/UNIT-01-real-collection-2026-09-27.md)
- [F06 离线验证证据](../evidence/F06-offline-verification.md)
- [历史离线验证证据](../evidence/F04-F05-offline-verification.md)
- [平台契约登记说明](../../contracts/README.md)

2026-09-27 本轮（F06）：两组默认精选集合与封面存储已完成离线实现并通过四层测试，迁移 003 已在既有本地开发库应用；F06 由"待办"改为**待验收**（真实 U05/U09 核验未执行）。

2026-09-27 本轮（最新，UNIT-01 本地阶段真实采集）：用户可接收验证码后，完成**真实登录 + 真实搜索 + 2 位达人主页采集与落库核对**；平台契约 `xingtu-ad-creator-square-v1` 已由真实交互登记并通过 live 门槛发布（[真实采集证据](../evidence/UNIT-01-real-collection-2026-09-27.md)）。迁移 004（本地出口共享）随之落地。状态统计更新为：**待验收 5**（BASE-01、UNIT-01、F04、F05、F06）、阻塞 0、待办 7、已完成 0。UNIT-01 由"阻塞"改为**待验收**：分页仅核验首页、主页只登记 `basic` 模块、筛选枚举与访问节奏未核验、生产线路与远程维护（U06/U07/U08）未执行，整卡不得标为已完成。两组精选集合契约（F06）仍未登记。
