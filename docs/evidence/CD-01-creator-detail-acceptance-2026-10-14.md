# CD-01 达人详情实现与验收证据

时间：2026-10-14（Asia/Shanghai）  
范围：任务快照详情与达人库当前资料详情；不发起采集、不修改 JSONB、迁移或采集契约。

## 实现结论

- 后端详情响应新增 `profile_payload`。任务入口直接使用不可变 `creator_snapshots.payload`；达人库入口以最新快照保留模块结构、以 `platform_creators.projection` 覆盖每个成功字段的当前观察，故单字段的 `observed_at` 不会被行级更新时间伪装。
- 前端统一使用 `CreatorDetailView`，并按基础/传播、内容视频、连接用户、种草转化、履约商业、报价与历史、来源质量分区呈现。原始 JSON `pre` 输出已删除。
- 视频集合保留同一视频记录的柱与表；三组带日期集合明确标为单次采集内的星图平台趋势；画像按平台返回类型分页；阶段仅显示“平台阶段 1–5”，未擅自命名漏斗业务阶段。
- 报价分为每合作形式的最新成功观察（当前合作报价）及更早观察（报价历史）；系统采集历史另列，不与平台内置趋势混合。

## 自动化与静态验证

| 检查 | 结果 |
|---|---|
| `make test-unit` | 189 passed |
| `npm --prefix frontend run lint` | 通过 |
| `npm --prefix frontend run build` | 通过 |
| `npm --prefix frontend test -- --run` | 9 passed |
| `ruff check backend/src/xingtu/product_queries.py backend/src/xingtu/product_models.py` | 通过 |
| `mypy backend/src/xingtu/product_queries.py backend/src/xingtu/product_models.py` | 通过 |
| `git diff --check` | 通过 |
| Playwright MCP（stdio 连接同一项目 MCP 服务，隔离 Chrome） | 任务快照和达人库当前资料均通过 DOM 复验 |

## 真实 Chrome DOM 复验

对象：既有真实任务 `efb257a6-476b-47ee-aff4-807795bb61a0` 中达人 `700ca5b0-f0c8-4436-86fe-624dfeb0f151`（甄选聊车）。

两条入口都获得：12 个业务面板、66 个直接字段事实项、15 条视频明细（含表头共 16 行）、三组各 30 点的平台内置趋势、8 个画像标签、5 个未命名平台阶段，以及数据来源抽屉；页面不存在原始 JSON `pre`。达人库入口额外确认“当前合作报价”“报价历史”“系统采集历史”三块均存在。

用户反馈首屏仍容易被旧的长基础字段区占据后，已移除该重复区并将新模块移至页内导航之后。复验确认两入口均满足 `profileBeforeSource=true`；即新版模块先于数据质量/历史区显示。对应前端类型检查、Vitest 9/9 和生产构建已在布局调整后重跑通过。

先前既有 UI 回归脚本也通过 38/38 项，结果见 `ui01-browser-acceptance.json`；本轮因当前会话没有原生 `mcp__playwright__*` 注入，使用项目内 `scripts/acceptance/mcp_client.py` 连接同一 Playwright MCP stdio 服务，未将其表述为工具直调。

后续当前会话已加载原生 `mcp__playwright__*`：已直接确认 MCP Chrome 能启动、导航并执行未登录访问门禁。该原生工具实例与验收 profile 隔离，安全策略拒绝将 QA 明文口令作为浏览器输入参数；因此已登录详情页断言继续由同一 MCP 服务、同一 Chrome 通道的本地 stdio 验收客户端执行，未伪称为原生工具直调。

## 第二轮 Lazyweb 调研与视觉验收

- Lazyweb MCP：实际初始化公开端点、取得工具清单，并调用 `lazyweb_search` 两次。查询分别覆盖“达人/创作者营销/活动分析详情”和“分析看板 KPI、图表、表格”；两次均返回 `result_count: 0`。因此没有把 Lazyweb 结果写成“同类产品页面参考”。本会话的认证端点仍返回 `AUTH_INVALID`；凭据没有写入仓库或证据。
- 实现：共享详情的普通页头改为深色身份与数据范围 Hero；显示真实头像或占位、真实标签、地域、MCN、平台 ID、观测时间和完整性，明确“本任务采集快照”或“当前达人资料”。6 个既有真实 KPI 变成有商业/内容/用户层级的决策带，仍只显示平台原始值。
- Playwright MCP + Chrome（Playwright `1.62.0-alpha-2026-06-29`，本机 `127.0.0.1:5173` / `:8000`）：任务入口验证 Hero、6 KPI、6 个页内导航、12 个业务面板、16 个视频表行（1 表头 + 15 条）、无 raw JSON；达人库入口验证“当前达人资料”语义、Hero、字段来源、当前合作报价/报价历史/系统采集历史。1440px 常规桌面 KPI 为 3×2（3 个 288px 列，大数值无断词）；390px viewport 验证 `scrollWidth == clientWidth`、KPI 为两列、Hero 宽 358px、页内导航横向滚动正常。

## 未完成验证

`XINGTU_TEST_DATABASE_URL=postgresql://xingtu_test@127.0.0.1:55439/xingtu_test_creator_library` 的 `backend/tests/integration/test_creator_library.py` 与 `test_repository.py` 未运行至断言：隔离 PostgreSQL 的 55439 端口拒绝连接，31 项均在 fixture 建连阶段报错。开发库没有被作为替代测试库使用。待恢复隔离测试库后需复跑该命令，再关闭 CD-01。
