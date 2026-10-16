# CD-02 实现与验收证据：达人详情分析工作台

时间：2026-10-14（Asia/Shanghai）  
范围：达人详情页的信息架构、字段呈现与只读字段目录端点；不发起采集、不改 JSONB/迁移/采集契约。

## 实现结论

- 新增只读端点 `GET /api/platforms/douyin_xingtu/profile-field-catalog`，直接从已加载的 `PlatformRegistry` 投影 8 模块 81 字段的 `name`/`kind`/`unit`/`period_label`/`empty_values`/`missing_source_status`，不访问数据库、不含业务值；4 个 `fans.*` 字段按实测证据给出修正显示名并标记 `name_source=evidence_correction`。
- 详情页改为"左栏身份资料卡 + 达人概览／商业能力／创作能力／履约能力／连接用户"；达人库入口另有"报价与历史"。任务入口保留精选作品，达人库入口保留报价与历史，二者取数语义不变（快照 vs 当前资料）。
- 81 字段全部有归属：概览（basic 其余项、商业传播、主题集中度、商业行业标签）、商业能力（报价明细、互动/完播、CPM/CPE、商业播放成本、种草价值、转化价值、精选作品）、创作能力（视频柱+表、内容类型分布、评论热词、口径对照）、履约能力（信用分/订单/回复率、行业订单与播放分布、合作行业分布）、连接用户（分层与同行对比、规模与增长、三组趋势、8 类画像）、来源抽屉（81 字段状态/单位/周期/观测时间/来源）。
- 复杂结构按真实关系呈现：分层堆叠（阶段 1–4 + 合计，含同行业中位/超越比例原值）、画像占比条、区间胶囊、JSON 字符串解析后的分布、报价表、精选作品指标。
- `CreatorLibraryHistory` 增加 `indexed_snapshots`/`total_snapshots`，页面据此显示"5/7 次已入索引"与缺口提示，不用空点补齐。

## 只读数据核对（开发库 `xingtu_development`）

| 项目 | 实测 |
|---|---|
| 平台达人 / 不可变快照 / 任务达人 | 23 / 78（2026-10-07~10-14）/ 54 |
| 8 模块业务字段 | 81（`profile_requirements.json` 一致；`fans.__module_failure__` 为诊断项） |
| `douyin_xingtu_creator_current` | 23 行；`interaction/completion` 19、`province` 15、`mcn_name` 10、`creator_type_label/introduction` 20 |
| `douyin_xingtu_creator_snapshot_index` | 58 行（缺 20）；本卡达人 甄选聊车 5/7 |
| `douyin_xingtu_creator_quote_observations` | 320 行、12 种合作形式 |
| `featured_cards` | 384 行，`cover.status` = STORED 29 / FAILED 15 / NOT_ATTEMPTED 6（样本 50） |

四项被本卡固定下来的实测语义（详细推导见 [CD-02 任务卡](../tasks/CD-02.md) 与 [81 字段字典](../达人数据字段字典.md)）：

1. `fans_daily_trend` = 每日粉丝总数，`fans_daily_delta` = 每日粉丝净增（来源接口 `get_author_daily_fans`，叶键 `fans_cnt`；末值 1,353,611 ≈ `followers` 1,351,784，相邻差与 `delta` 相等）。
2. `connection_funnel` / `seeding_link_structure` 的阶段 1–4 之和**恰好等于**阶段 5（67/67 快照），阶段 5 = `monthly_connected_users`（49/49 相等）→ 互斥分层 + 合计，不是漏斗。
3. `connection_daily_trend` 末点等于月连接用户数，30 点求和无业务含义。
4. `interaction_rate`/`completion_rate` 有 4 种实测形态（`{value,overtake}`、`{label,value,overtake}`、仅 `{label}` 8/78、`{value:null}`）；比例尺度未登记，保持原值。

## 自动化与静态验证

| 检查 | 结果 |
|---|---|
| `pytest backend/tests/unit` | 195 passed（新增 6 例字段目录规则） |
| `ruff check backend/src backend/tests scripts` | 通过 |
| `ruff format --check backend/src backend/tests scripts` | 74 files already formatted |
| `mypy product_queries.py product_models.py product_api.py profile_catalog.py` | Success |
| `npm --prefix frontend run lint` | 通过 |
| `npm --prefix frontend run build` | 通过（dist 405.23 kB / gzip 126.24 kB） |
| `npm --prefix frontend test -- --run` | 45 passed（4 文件） |
| `git diff --check` | 通过 |

## 真实 Chrome 验收（`scripts/acceptance/run_cd02_acceptance.py`）

浏览器：Playwright MCP `1.62.0-alpha-2026-06-29`（项目 stdio 配置 + 本机 Chrome，1440×900 与 390×844）；前端 `http://127.0.0.1:5173`、API `http://127.0.0.1:8000`（本机重启后加载本轮后端改动）；对象为真实任务 `efb257a6-476b-47ee-aff4-807795bb61a0` 的达人 `700ca5b0-f0c8-4436-86fe-624dfeb0f151`（甄选聊车）。

**30/30 通过**，关键结果：

| 检查 | 结果 |
|---|---|
| 左栏 KPI 标签/取值 | `粉丝 1,351,784` / `月连接用户 23,439,854` / `月深度用户 ≈11,580,000` / `月涨粉率 1.97%` |
| 分区 | 任务入口 5 个；达人库入口 6 个（含报价与历史） |
| 字段中文名 | 基础资料标签为 `星图ID/性别/城市/省份/MCN公司/…`，无英文键泄漏（目录不可用时回退为 `field_key`，见单测） |
| 无原始 JSON | `pre` 0 个，正文无 `{"`/`"kind"`/`"structured"` |
| 报价明细 | 2 项（植入视频/定制视频，报价/原价/有效期/状态） |
| 互动率原值 | `112` + `同行超越 7493 平台原值`（未换算百分比） |
| 精选作品 | 4 张卡片，标题为真实作品标题，指标 `播放 1,944,275 · 点赞 28,260 · 评论 1,156` |
| 最新视频 | 柱 15 + 表 15 行；发布时间 `2026-10-12`（不再是 Unix 秒） |
| 创作能力面板 | 视频内容类型分布 / 评论热词 / 视频表现口径对照均渲染 |
| 连接用户分层 | 5 行（4 层 + 合计），`各层合计 23,439,854，与合计值一致`，含同行业中位 466,345 等；文本不含"漏斗" |
| 三组趋势 | 3 个面板，caption 分别为"平台每日粉丝总数"/"平台每日粉丝净增"/"平台窗口口径（末点=月连接用户数）" |
| 画像 | 8 个标签页，含平台描述与占比 |
| 来源抽屉 | 81 字段 / 8 模块，含"单位未登记/周期未登记"与"名称按实测数据源修正" |
| 达人库历史 | 头部 `5/7 次已入索引`，缺口提示"还有 2 次采集没有索引行"；报价历史 10 行 |
| 移动端 390px | 无横向溢出，KPI 两列，分区导航可横向滚动 |

截图：`docs/evidence/assets/cd02/`（overview / commercial / creation / fulfillment / audience / provenance / library-history / mobile-390）。完整断言明细见 [CD-02-acceptance-2026-10-14.json](CD-02-acceptance-2026-10-14.json)。

## 实现中发现并修复的缺陷

1. 左栏月深度用户显示为空：原实现优先取平台格式化原值 `1,158w`，数值解析失败 → 改为优先取已解析数值、原值仅作回退。浏览器检查已锁定 `≈11,580,000`。
2. 精选作品卡片标题与三项指标缺失：卡片字段是 `FieldObservation` 封套（`{kind,amount,bound}`），直接 `Number()` 得 NaN → 增加封套解包，标题与指标恢复。
3. 口径对照表把平台 `0.0191` 压成 `0.019`：`toLocaleString` 默认 3 位小数 → 改为整数分组、小数最多 4 位。
4. 平台以字符串返回的整数（商业播放量等）未分组 → 整数串统一分组，小数串与非数字串保持原样（不重排平台值）。

## 未完成验证

- 隔离 PostgreSQL 测试库 `postgresql://xingtu_test@127.0.0.1:55439/xingtu_test_creator_library` 仍拒绝连接，`backend/tests/integration/test_creator_library.py` 与 `test_repository.py` 未运行至断言（沿用 CD-01 未完成项，本卡未使用开发库替代）。
- Lazyweb 设计检索不可用：公共端点 `lazyweb_search` 返回 `result_count: 0`；`lazyweb_ask_anything` 明确回答截图检索 `lazyweb_search_screens` 需要认证；认证端点 `https://www.lazyweb.com/mcp` 返回 `401 invalid_token`。本轮设计参考来自项目内真实星图页面截图（`docs/assets/xingtu-featured-*.png`、`.runtime/profiles/research/filter-audit-screens/`）与契约登记的平台 UI 结构（`h3:has-text('最新15个视频表现柱状图')`、`h2:has-text('连接用户分布')`），未将 Lazyweb 结果伪称为设计参考。
- 本轮未发起任何真实采集；验收复用既有真实任务与快照数据。
