# M3 产品前端与浏览器验证证据（2026-10-10）

> 范围：APP-01 产品入口、INTAKE-01 能力驱动表单、CONSOLE-01 任务中心与任务内结果。  
> 证据边界：前端自动化使用合成 API 响应；它验证真实 Chromium 中的产品交互，但不等于真实 DeepSeek、真实星图或生产域名验收。

## 1. Lazyweb 设计证据

- 使用用户提供的本地 Lazyweb skill 仓库，MCP 健康检查通过。
- 按 `objective=create` 读取实时工作流，先检索桌面任务工作台，再补充高级筛选、任务进度、表格/详情、工作流观测、异常处置与多阶段状态参考。
- 首轮“operations dashboard task status”覆盖度为 strong，最终从 Rune、Asana、Wrike、Smartsheet、Mixpanel、Retool、Databricks、Incident.io、Better Stack 和 Attio 等引用中选取 12 项。
- 安全定稿只上传 Lazyweb 已返回的公开引用编号，未上传项目内部需求、字段、账号或实现细节。
- 已定稿的私有参考集：[Desktop operations dashboard UI references](https://www.lazyweb.com/agentic-search/bf6ff6da-4fa9-4090-b059-3d9a7760d875)。

设计结论：

- 以高密度“任务工作台”为主，不做泛化 BI 大屏。
- 稳定侧边导航，任务状态、阶段、计数与主操作同屏。
- 用进度轨道表达需求接收、转换校验、排队、发现、采集、发布；错误以可行动提示呈现，不暴露原始日志。
- 达人结果采用高密度列表及独立详情，草稿、发布快照、字段状态和双作品集合有显式标识。

## 2. 实现范围

新增 `frontend/` React + TypeScript + Vite 应用：

- `/login`：产品账号登录、统一错误、会话恢复与原访问 URL 回跳。
- `/tasks`：共享任务、状态/时间筛选、服务端游标、四类计数与失败数。
- `/tasks/new`：从 capabilities 动态渲染已核验条件；稳定提交幂等键；修改重提保留来源任务。
- `/tasks/:id`：5 秒活跃轮询、15 秒长等待轮询、终态停止；进度轨道、计数、错误、`allowed_actions`、操作版本/幂等与 409 刷新；达人游标分页。
- `/tasks/:id/creators/:creatorId`：草稿/快照标识、F05 模块与字段状态、F06 优秀传播/优秀种草独立分页、封面失败降级和真实链接。
- 未展示 capabilities 未返回的筛选项；当前 live 注册表仍只向 P0 开放内容关键词。

主要实现：

- `frontend/src/App.tsx`
- `frontend/src/pages.tsx`
- `frontend/src/api.ts`
- `frontend/src/AuthContext.tsx`
- `frontend/src/styles.css`
- `tests/e2e/test_product_frontend.py`

## 3. 自动化与视觉验证

| 层级 | 命令 | 结果 | 边界 |
|---|---|---|---|
| TypeScript | `npm --prefix frontend run lint` | 通过 | strict 类型检查 |
| 组件/数据交互 | `npm --prefix frontend test` | 2 passed | jsdom + 合成 API |
| 生产构建 | `npm --prefix frontend run build` | 通过；1734 modules | Vite 生产 bundle |
| 产品浏览器 E2E | `make test-product-e2e` | 2 passed | 真实 Chromium + 合成 API，不访问星图 |
| 全仓门禁 | `make check` | 通过 | 155 后端单测 + 2 前端测试 + 前端构建 |

Chromium 用例已验证：

1. 未登录直达 `/tasks` 被导向登录，登录成功后恢复原 URL。
2. 任务列表可进入任务详情，阶段和发现/有效/资料/精选/失败计数同时可见。
3. 任务详情可进入达人发布快照，查看 F05 字段状态和 F06 精选作品。
4. 新建页只出现关键词能力；提交包含稳定 `Idempotency-Key`，目标数默认 20，202 后进入返回的根任务。

视觉截图在测试运行时写入 `.runtime/test-artifacts/m3-frontend/`，不提交到仓库；本轮已人工检查 `login.png`、`tasks.png`、`creator-detail.png`。

## 4. 未完成的真实验收

- 未提供 `DEEPSEEK_API_KEY`/配额/数据处理确认，故未运行真实 DeepSeek Responses JSON Schema 小样本。
- 未通过产品页面发起真实星图关键词 1—3 位任务。
- 未提供生产 HTTPS 域名、精确 Origin 与初始用户清单；Secure Cookie 生产环境尚未验收。
- 因此 APP-01、INTAKE-01、CONSOLE-01 仍保持“进行中／未验收”，不将合成产品 E2E 表述为真实平台闭环。
