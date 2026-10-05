# 平台契约登记说明

本目录保存平台（一期：`douyin_xingtu`）的能力、请求、字段与页面契约。契约由**真实账号调研**产生，不允许用推测值填充未核验路径。

## 文件

| 文件 | 说明 |
|---|---|
| `douyin_xingtu.unverified.json` | 随包模板，`status=UNVERIFIED`，`session/search=null`、`modules=[]`、`featured=[]`。`require_enabled()` 必然拒绝，新执行也会在 `require_contract` 阶段被拒。 |
| `douyin_xingtu.verified.json` | **2026-09-27 已建立**（`contract_version=xingtu-ad-creator-square-v1`、`adapter_version=browser-v2`）：会话入口/账号/受保护页/主页身份、达人广场搜索请求与回读、`basic` 主页模块字段，均由真实账号交互登记并通过 `require_enabled(live=True)`。仍属部分核验：只登记 `basic` 模块，分页声明 `single_page_only`。 |
| `<platform>.verified.json` | 核验通过后的注册表，`status=VERIFIED`；live 运行还要求 `sample_kind=live`、`verified_at`、`account_permission_type` 与非空 `evidence_refs`。 |

> 2026-09-27：契约登记使用 `xingtu research`（仅 `network_mode=local_development` 单元，主机须在 `research_allowed_hosts` 内）。它打开真实页面、等待人工登录，并记录结构化观察（请求方法/主机/路径/查询键/响应键路径、DOM 轮廓），**不记录**请求头、Cookie、令牌或响应正文；原始件写入 `.runtime/research/`（`0700`、未纳入版本库），经审阅的脱敏摘要才写入 `docs/evidence/`。由观察得到的注册表仍必须通过下方发布门槛，研究工具本身不能产生 `VERIFIED` 能力。详见[DEC-007](../docs/decisions/DEC-007-contract-research-tooling.md)。

脱敏正反样本与回归引用放在 `docs/evidence/`，**不得**在本目录粘贴可用 Cookie、令牌、签名或未脱敏个人数据。

## 结构（`PlatformRegistry`，schema `platform_registry.v1`）

- 版本与状态：`contract_version`、`adapter_version`、`status`、`sample_kind`、`verified_at`、`account_permission_type`、`evidence_refs`、`coverage_gaps`。
- 范围：`allowed_hosts`、`homepage_path_prefixes`、`action_interval_seconds`、`operation_timeout_seconds`、`response_body_max_bytes`。
- 能力：`capabilities`（字段、枚举、单位、币种、合作形式、排序、**显式列出的组合**、验证状态与版本）。
- 会话：`session`（入口 URL、账号标识定位、受保护页面就绪、错误页选择器、达人身份定位）。
- 搜索：`search`（入口、重置/填写/翻页动作、就绪与必须消失的加载提示、回读定位、请求契约、结果请求键、候选/身份/主页/下一页/终点 JSON 路径、分页方式、游标续用与初值）。
- 主页模块：`modules[]`，按执行顺序排列，第一个为 `basic` 并必须包含 `platform_creator_id` 与 `nickname`。
- 搜索补充字段（2026-09-27 起）：`homepage_path` 与 `homepage_template` **恰好登记其一**（模板必须含 `{platform_creator_id}` 且落在 `homepage_path_prefixes` 内）；`fixed_sort`（平台排序固定，计划只允许该值，免除 sort 回读绑定）；`single_page_only`（只核验首页，此时 `next_actions` 可为空但必须给出 `coverage_gaps`）；`binding_values`（计划取值→平台字面量，如关键词模式 `content`→`3`）；检索级 `coverage_gaps`。`LocatorSpec.property` 支持读取表单控件的 DOM property（如输入框 `value`），平台不保证 `value` 属性存在。
- 注册表级 `session_boot_timeout_seconds`：会话入口握手（SSO→应用壳）的有界等待，默认 120 秒。每个模块包含入口页面、模块级默认条件、动作、就绪与加载提示、逐模块超时、请求契约、字段字典、周期来源、模块级缺失证据、检查点版本与覆盖缺口。
- 精选集合（F06）：`featured[]`，为空表示本次不采集作品；非空必须**恰好**包含 `excellent_reach` 与 `excellent_seeding`。每个集合包含模块名称、入口（必须是已核验主页路径范围内的标签页）、动作（含模块内加载触发）、就绪与必须消失的加载提示、请求契约（模块内增量加载把对应请求标为 `repeats=true`）、卡片响应路径、卡片字段字典（键 `platform_content_id`/`link`/`local_key` 分别承载作品 ID、作品链接与经验证的模块局部键）、链接主机范围、模块默认口径路径、稳定集合标识路径、终点路径与终值、模块级空态/无权限/平台不提供取值、封面契约 `cover`（字段键、CDN 主机白名单、允许的内容类型、字节上限、超时与重定向上限）、检查点版本与覆盖缺口。作品时间窗口、Top X 与全量作品分页参数一律不存在。

## 发布门槛（`require_enabled`）

1. `status=VERIFIED`、`session`/`search` 存在、范围内参数齐全。
2. live 运行必须有 live 样本与证据（合成样本永远不能通过）。
3. 引用完整性：请求键唯一且主机在范围内；搜索结果请求键已声明；字段来源引用的请求键必须已声明；`fallback` 必须声明 `fallback_on`；数值字段必须有单位；报价必须有关联币种与合作形式；分布必须有维度；字段与模块的缺失取值不得跨状态歧义；`entry` 与入口 URL 必须在平台主机范围内；分页必须有已注册的推进动作；业务错误码必须属于附录 B。
4. 能力字典 `status=VERIFIED` 且版本与 `FilterPlan.capability_version` 一致。
5. 搜索主页来源唯一（`homepage_path`/`homepage_template` 二选一且模板合法）、`single_page_only` 必须声明覆盖缺口、未声明但 `next_actions` 为空仍拒绝。

未通过的注册表不得发布，也不得通过修改门槛代码绕过。

## 核验交付清单（U02/U04/U05/U06）

沿用技术方案 13.5 的登记项；每项都要给出真实账号、日期、账号权限类型与脱敏样本：

| 交付物 | 必须回答 |
|---|---|
| 会话契约（U06） | 入口 URL 模式、账号标识读取方式、受保护页面就绪条件、错误页特征、登录成功判定与会话版本更新 |
| 搜索契约（U02/U04） | 每项筛选的重置/填写/回读定位与取值映射、内容关键词模式、合作形式与单位、排序、分页方式与终点证据、虚拟列表或"加载更多"行为、无进展样本 |
| 主页模块契约（U04） | 逐模块入口/标签页/展开动作、就绪条件、必需与可选响应、字段 JSON 路径或 DOM 定位、单位与默认统计口径、缺失/权限/空态证据、来源冲突样本、恢复用例 |
| 精选集合契约（U05） | 两组模块的独立边界、局部稳定键、加载终点、标题/副标题/作品链接/封面来源、集合变化恢复 |

启用前须通过正常、空态/缺失、权限与适用错误/恢复样本回归，并完成真实账号小样本核验；无法取得的变体记录为测试缺口，留 `UNVERIFIED`。

## AUTO-01 业务需求清单

`profile_requirements.json` 是 CLI 新任务默认的业务完整度要求，与已验证平台执行注册表分开。当前 `inventory_verified=false`，非基础模块名称为业务盘点分组、空字段表代表尚未核验，不是已登记的平台模块。即使基础资料全部成功，新任务也不会报告完整主页。验证清单需要逐字段来源与证据后才能设为 true。历史任务未携带此清单时仍按原注册范围显示，快照的 `profile_coverage.scope` 标识口径，不回写历史快照。

`SEARCH_CAPABILITY_LIMIT` 表示实现能力边界，保留非耗尽游标；只有已验证平台终点才能设置耗尽。`PLATFORM_PERMISSION_DENIED` 与 `PLATFORM_QUOTA_EXHAUSTED` 不触发反复登录。请求/响应计数仅覆盖当前登记操作匹配到的请求，不是全站流量或权益消费量。
