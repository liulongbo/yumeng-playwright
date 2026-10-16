# CD-06 证据：履约能力精简与连接用户双轴趋势合并

- 日期：2026-10-15（+08:00）
- 卡片：[CD-06](../tasks/CD-06.md)
- 环境：本机真实运行栈——前端 `http://127.0.0.1:5173`（Vite dev）、API `http://127.0.0.1:8000`、
  真实开发库 `xingtu_development`（PostgreSQL 18.3，只读查询）。
- 被测达人：甄选聊车，`creator_id=700ca5b0-f0c8-4436-86fe-624dfeb0f151`。
- 浏览器自动化：项目登记的 Playwright MCP server（`@playwright/mcp` 1.62.0，`--browser chrome` + 项目独立 profile），
  经 `scripts/acceptance/mcp_client.py` 以 MCP **stdio** 调用。**本会话工具列表未暴露 `mcp__playwright__*`，
  因此这是 stdio 客户端代调，不是工具直调**；如实记录。
- 报告原文：[CD-06-acceptance-2026-10-15.json](CD-06-acceptance-2026-10-15.json)

## 1. 执行命令与结果

| 检查 | 结果 |
|---|---|
| 前端 `tsc -b`（= `npm run lint`） | 通过，无输出 |
| 前端 `vitest run` | **71 passed**（5 文件；CD-06 新增 4 例、改写 3 例） |
| 前端 `npm run build` | 通过 |
| 后端 `pytest backend/tests/unit` | **213 passed** |
| `ruff check` / `mypy` | All checks passed / no issues |
| `git diff --check` | 干净 |
| **真实浏览器验收（本轮）** | **27/27 通过**；Console Errors **0**、失败 API **0** |
| **CD-05 回归** | **38/38 通过** |
| **CD-04 回归** | **52/52 通过** |

## 2. 需求一：履约能力

| 编号 | 检查 | 结果 |
|---|---|---|
| CD06-FUL-01 | 三个模块文案不再出现 | 通过 —— 正文不含「行业订单分布」「行业播放分布」「合作行业分布」 |
| CD06-FUL-02 | 只剩一个模块 | 通过 —— `headings=['履约与合作表现']` |
| CD06-FUL-03 | 无原始 JSON 泄漏 | 通过 —— 被移除的 JSON 字符串叶子（`'[{"key":"1916",...}]'`）不再输出 |
| CD06-FUL-04 | **数据未被删除** | 通过 —— API 仍返回三个字段且状态均为 `COLLECTED`：`['credit_score',…,'industry_order_distribution','industry_play_distribution','cooperation_industry_distribution']` |

## 3. 需求二：连接用户

| 编号 | 检查 | 结果 |
|---|---|---|
| CD06-AUD-01 | 「连接用户规模与粉丝增长」移除 | 通过 |
| CD06-AUD-02 | 「近 30 日粉丝日增量」移除 | 通过（标题不存在，`.delta-bar` 数量 0） |
| CD06-AUD-03 | 两个趋势模块合并 | 通过 —— 旧标题不再单独出现，改为「近 30 日连接用户与粉丝趋势」 |
| CD06-AUD-04 | 一张图两条线 | 通过 —— `['trend-line tone-blue', 'trend-line tone-crimson']` |
| CD06-AUD-05 | 左轴连接用户数 / 右轴粉丝数 | 通过 —— `axisTitles=['连接用户数','粉丝数']` |
| CD06-AUD-06 | X 轴为时间 | 通过 —— 日期刻度 `2026-09-13 / 09-19 / 09-25 / 10-01 / 10-07 / 10-13` |
| CD06-AUD-07 | 轴刻度按「万」 | 通过 —— `['5027.6万','2344.0万','135.4万','132.7万']` |
| CD06-AUD-08 | 两条线均来自真实平台序列 | 通过 —— API 连接用户 30 点 + 粉丝 30 点，图上 60 个点 |
| CD06-AUD-09 | 末值与 API 逐字一致 | 通过 —— 图注「连接用户数 末值 23,439,854（2026-10-12）· 粉丝数 末值 1,353,611（2026-10-13）」 |
| CD06-AUD-10 | 图例 | 通过 —— `['连接用户数','粉丝数']` |
| CD06-AUD-11 | Hover 同时显示两值 | 通过 —— 真实鼠标悬停 `2026-10-12`，浮层内容 `连接用户数23,439,854 粉丝数1,352,027` |
| CD06-AUD-12 | 浮层可用且不被裁剪 | 通过 —— `withinViewport=True`、竖向参考线存在、两个高亮点 |
| CD06-AUD-13 | 移出后关闭 | 通过 —— 真实鼠标移到 (10,10) 后浮层消失 |

## 4. 回归

| 编号 | 检查 | 结果 |
|---|---|---|
| CD06-REG-01 | 任务入口双轴图一致 | 通过 —— `seriesCount=2`、轴标题相同 |
| CD06-REG-02/03 | 任务入口同样移除两处模块 | 通过 —— 连接用户两模块与履约三模块均不在页面 |
| CD06-REG-04 | 未触碰章节正常 | 通过 —— 商业能力（内容数据）、创作能力（最新视频表现）、报价与历史（报价）均正常渲染 |
| CD06-REG-05 | 390px 无横向溢出 | 通过 —— `scrollWidth==innerWidth==390`，图表宽 356px |
| CD06-NO-* | Console / API | 通过 —— Console 错误 0、失败 API 0 |
| CD-05 回归 | 上一轮 38 项 | **38/38 通过** |
| CD-04 回归 | 商业能力 52 项 | **52/52 通过** |

## 5. 字段核对

| 字段 | JSONB 路径 | API 字段 | 前端使用位置 | 真实数据示例 | 联通 |
|---|---|---|---|---|---|
| 粉丝总数日序列 | `modules.fans.fields[]` `fans_daily_trend.value.data[] = {date, fans_cnt}` | `profile_payload` 原样下发 | `DualAxisTrend` 右轴 + 图注 | `{date:"2026-10-13", fans_cnt:"1353611"}` → `135.4万` | 已完成 |
| 连接用户日序列 | `modules.fans.fields[]` `connection_daily_trend.value.data[] = {date, value}` | 同上 | `DualAxisTrend` 左轴 + 图注 | `{date:"2026-10-12", value:23439854}` → `2344.0万` | 已完成 |
| 行业订单分布 | `modules.fulfillment.fields[]` `industry_order_distribution` | 同上 | **展示已下架**（数据/端点未改） | `'[{"key":"1916","rate":"1.0","value":"6"}]'` | 展示移除 |
| 行业播放分布 | `modules.fulfillment.fields[]` `industry_play_distribution` | 同上 | 同上 | 同形状 | 展示移除 |
| 合作行业分布 | `modules.fulfillment.fields[]` `cooperation_industry_distribution` | 同上 | 同上 | 含 `industry`/`first_category`/`second_category` | 展示移除 |

**两个序列的窗口差异（实现中的关键约束）**：`fans_daily_trend` 为 2026-09-14 → 10-13，
`connection_daily_trend` 为 2026-09-13 → 10-12，**相差一天**。因此按日期并集对齐，每条序列只绘制自己有值的
日期，缺失日期在图上留空而不补造数值（不 interpolate、不填充 0）。

## 6. 截图证据

| 用途 | 文件 |
|---|---|
| 履约能力（只剩「履约与合作表现」） | [CD06-library-fulfillment](assets/cd06/CD06-library-fulfillment.png) |
| 连接用户（双轴趋势图） | [CD06-library-audience](assets/cd06/CD06-library-audience.png) |
| Hover 同一时间点显示两个口径 | [CD06-library-audience-hover](assets/cd06/CD06-library-audience-hover.png) |
| 390px 窄屏 | [CD06-library-audience-390](assets/cd06/CD06-library-audience-390.png) |

## 7. 遗留差异与未完成项（如实记录）

1. **未做像素级视觉对比**：按参考图的结构实现（双轴/双线/图例/时间轴/Hover 同时看两值），
   未逐像素比对。参考图的 Y 轴刻度取整风格（`16,000w / 12,000w / 8,000w / 4,000w / 0`）与当前
   「取实际最小/最大值」不同；当前刻度为 `5027.6万 / 2344.0万`（左）与 `135.4万 / 132.7万`（右）。
   如需按整千/整万取整，请说明后单独调整。
2. **参考图数值与库内不同**：参考图为平台自身页面（连接用户数 1.4 亿级、粉丝 572w 级），
   本项目该达人为连接用户 2,344 万级、粉丝 135 万级；本轮按**库内真实数据**绘制，未照搬参考图数值。
3. **参考图「连接用户分布」5 个指标块未改造**：该模块对应本项目「连接用户分层与同行业对比」，
   不在本轮点名范围（本轮只点名规模与趋势相关模块），因此未改动。如需按参考图改造成
   环形指标块（连接用户数 / 了解 / 兴趣 / 喜欢 / 追随 + 30 天环比），请单独确认。
