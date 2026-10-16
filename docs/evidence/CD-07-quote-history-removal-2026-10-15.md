# CD-07 证据：报价与历史移除「系统采集历史」模块展示

- 日期：2026-10-15（+08:00）
- 卡片：[CD-07](../tasks/CD-07.md)
- 环境：本机真实运行栈——前端 `http://127.0.0.1:5173`（Vite dev）、API `http://127.0.0.1:8000`、
  真实开发库 `xingtu_development`（PostgreSQL 18.3，只读查询）。
- 被测达人：甄选聊车，`creator_id=700ca5b0-f0c8-4436-86fe-624dfeb0f151`。
- 浏览器自动化：项目登记的 Playwright MCP server（`@playwright/mcp` 1.62.0，`--browser chrome` + 项目独立 profile），
  经 `scripts/acceptance/mcp_client.py` 以 MCP **stdio** 调用。**本会话工具列表未暴露 `mcp__playwright__*`，
  因此这是 stdio 客户端代调，不是工具直调**；如实记录。
- 报告原文：[CD-07-acceptance-2026-10-15.json](CD-07-acceptance-2026-10-15.json)

## 1. 执行命令与结果

| 检查 | 结果 |
|---|---|
| 前端 `tsc -b`（= `npm run lint`） | 通过，无输出 |
| 前端 `vitest run` | **71 passed**（5 文件；本轮在该用例内新增 5 项 CD-07 断言） |
| 前端 `npm run build` | 通过 |
| 后端 `pytest backend/tests/unit` | **213 passed** |
| `ruff check` / `mypy` | All checks passed / no issues |
| `git diff --check` | 干净 |
| **真实浏览器验收（本轮）** | **14/14 通过**；Console Errors **0**、失败 API **0** |
| **CD-06 回归** | **27/27 通过** |
| **CD-05 回归** | **38/38 通过** |
| **CD-04 回归** | **52/52 通过**（其 `BIZ-22` 断言按本轮新范围改写） |

## 2. 逐项验收

| 编号 | 检查 | 结果 |
|---|---|---|
| CD07-QH-01 | 「系统采集历史」模块移除 | 通过 —— 标题不在页面、`.history-list` 与 `.history-panel` 都不存在 |
| CD07-QH-02 | 同章节「报价历史」保留 | 通过 —— 面板为 `['报价历史']`，真实报价观察 **8 行** |
| CD07-QH-03 | 页面不再请求 `/history` | 通过 —— 本次加载中 `/history` 资源请求 **0**、`/quotes` **1**（已解除消费） |
| CD07-QH-04 | 接口与数据未删除 | 通过 —— `GET /api/creator-library/{id}/history` 仍返回 200，`items=5`、`indexed=5`、`total=7`（**未做破坏性变更**） |
| CD07-QH-05 | 无空壳容器、无原始 JSON | 通过 —— 空 `section` 数 0、索引缺口提示（`.gap-note`）不再残留 |
| CD07-REG-01 | 其余四章正常 | 通过 —— 商业能力（内容数据）、创作能力（最新视频表现）、履约能力（履约与合作表现）、连接用户（近 30 日连接用户与粉丝趋势）均正常 |
| CD07-REG-02 | 任务入口「报价与历史」正常 | 通过 —— `active='报价与历史'`、内容长度 246、本身不含该模块 |
| CD07-REG-03 | 390px 无横向溢出 | 通过 —— `scrollWidth == innerWidth == 390` |
| CD07-NO-* | Console / API | 通过 —— Console 错误 0、失败 API 0 |

## 3. 保留与移除的边界（本轮关键）

| 对象 | 处理 | 证据 |
|---|---|---|
| 页面「系统采集历史」模块 | **移除展示** | QH-01（标题/列表/容器都不存在） |
| `GET /api/creator-library/{id}/history` | **保留**（未删端点、未改 DTO） | QH-04（仍 200 且返回真实数据） |
| #LIB-01 历史索引数据（`douyin_xingtu_creator_snapshot_index`） | **保留**（未删、未回填、未改） | QH-04 的 `indexed=5 / total=7` 仍如实反映索引缺口 |
| `CreatorLibraryHistory` DTO 与 `api.creatorLibraryHistory` | **保留在代码中**（当前无调用方） | 属 API 客户端公共面，删除会扩大改动面 |
| 同一章节「报价历史」 | **保留** | QH-02（8 行真实观察） |
| 左栏底部「字段来源」入口 | **保留** | 截图可见，本轮未触碰 |

**未执行任何数据库 Schema 修改、迁移或数据回填；`backend/**`、`contracts/**`、`migrations/**` 零改动。**

## 4. 截图证据

| 用途 | 文件 |
|---|---|
| 报价与历史（只剩「报价历史」） | [CD07-library-quote-history](assets/cd07/CD07-library-quote-history.png) |
| 任务入口同章节 | [CD07-task-quote-history](assets/cd07/CD07-task-quote-history.png) |
| 390px 窄屏 | [CD07-library-quote-history-390](assets/cd07/CD07-library-quote-history-390.png) |

## 5. 遗留问题（如实记录）

1. `frontend/src/api.ts` 的 `api.creatorLibraryHistory` 与 `types.ts` 的 `CreatorLibraryHistory`
   在当前前端**已无调用方**（本轮只解除页面消费，故未删除）。它们仍对应一个真实可用端点，
   如需清理请单独确认。
2. 本轮**未删除** LIB-01 的历史索引表或数据；`indexed=5 / total=7` 的索引缺口依然存在于数据库中，
   只是不再有页面入口展示它（缺口事实本身未被掩盖，可由 API 直接读取）。
