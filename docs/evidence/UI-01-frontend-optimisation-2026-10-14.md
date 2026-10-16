# UI-01 前端页面优化验收证据（2026-10-14）

本轮交付[UI-01 任务卡片](../tasks/UI-01.md)的五项前端页面优化，并已用真实浏览器完成页面级验收。所有结论基于实际运行中的本机开发栈与真实开发库数据，不含模拟数据或伪造结果。

## 1. 环境与代码版本

| 项目 | 值 |
|---|---|
| 日期/时区 | 2026-10-14（本地 UTC+8） |
| 分支 | `llb_1013`（未提交、未切换、未合并） |
| 工作区 | 存在其他任务的未提交改动（SESSION-01、FIX-01、LIB-01 等），本轮未覆盖、未还原 |
| 前端 | `http://127.0.0.1:5173`（Vite dev，`./dev.sh up`，pid 由脚本记录） |
| 后端 API | `http://127.0.0.1:8000`（uvicorn，`./dev.sh up`） |
| 数据库 | `xingtu_development`（127.0.0.1:55432，Docker `xingtu-f04-f05-app-postgres-1`） |
| 迁移 | 已应用到 version 12（本轮新增 012） |
| 账号 | `media-a`（口令取自 `.runtime/qa-credentials.env`，未写入任何证据文件） |
| 参照任务 | `efb257a6-476b-47ee-aff4-807795bb61a0`（关键词「汽车」、目标 5、`PARTIAL_COMPLETED`、`valid_count=5/5`） |
| 参照达人 | `700ca5b0-f0c8-4436-86fe-624dfeb0f151`（甄选聊车，平台 ID 7503176021160493065，任务内 first_position=0） |

本轮的浏览器验收对象是 `efb257a6`：它是既有的**真实星图采集**产品任务（LIB-01 已记录其 5 份快照与两组精选），因此不需要为本轮 UI 改动发起新的真实采集。**本轮未创建任何新的采集任务，未访问巨量星图，未执行 P1 需求转换。**

## 2. 验收工具与调用方式（如实说明）

- 项目已配置 Playwright MCP：`~/.codex/config.toml` 的 `[mcp_servers.playwright]`，`@playwright/mcp 0.0.77`，`--browser chrome --isolated --output-dir /tmp/dsh-playwright-mcp`；该 server 能正常握手并返回 23 个 `browser_*` 工具（版本 `1.62.0-alpha-2026-06-29`）。
- **但本会话的工具注册表没有暴露 `mcp__playwright__*` 工具**，无法以“MCP 工具直调”的方式执行。经用户明确确认后，本轮改用**同一个 MCP server 的 stdio 协议客户端**驱动它：`scripts/acceptance/mcp_client.py` 实现 initialize / tools/list / tools/call，`scripts/acceptance/run_acceptance.py` 是验收脚本。**这仍然不是“MCP 工具直调”，特此标注，不冒充。**
- 浏览器是**真实 Chrome**（`--browser chrome`，Google Chrome 155.0.8059.40）；因外层文件沙箱拒绝 Chrome 自身沙箱与 GPU 辅助进程，启动参数追加 `--no-sandbox`，profile 使用项目运行目录 `.runtime/acceptance-chrome-profile`（`~/Library/Application Support/Google/Chrome` 对当前会话不可写）。除这两项环境必需参数外，未改变浏览器或 MCP server 的其它选型。

复现命令：

```bash
# 1) 启动/恢复本机全栈（API、P1 Intake Worker、P2 采集 Worker、前端）
./dev.sh up

# 2) 用项目绑定的 Chrome 登录一次（口令来自 .runtime/qa-credentials.env，不落盘）
XINGTU_QA_PASSWORD="$(awk -F= '/^QA_MEDIA_A_PASSWORD=/{print substr($0,index($0,"=")+1)}' .runtime/qa-credentials.env)" \
  .venv/bin/python scripts/acceptance/seed_auth.py

# 3) 执行 T01—T05 与回归验收（脚本末尾会用退出登录 + 重新登录完成 T01）
XINGTU_QA_PASSWORD="$(awk -F= '/^QA_MEDIA_A_PASSWORD=/{print substr($0,index($0,"=")+1)}' .runtime/qa-credentials.env)" \
  .venv/bin/python scripts/acceptance/run_acceptance.py
```

## 3. 验收结果

机器可读结果：`docs/evidence/ui01-browser-acceptance.json`（38 项检查、逐步断言明细、控制台与网络记录、截图清单）。

**38 / 38 通过**（退出码 0）。

### T01 登录密码显示 / 隐藏

| 检查 | 结果 | 实测 |
|---|---|---|
| 登录页可达 | PASS | 登出后落在 `/login` |
| 默认隐藏 | PASS | `input.type=password`，切换按钮 `aria-label="显示密码"`、`aria-pressed="false"` |
| 输入保留 | PASS | 键入 24 位口令后切换前长度 24 |
| 点击显示 | PASS | `type=text`、`aria-label="隐藏密码"` |
| 再次隐藏 | PASS | `type=password`、`aria-label="显示密码"` |
| 切换不清空 | PASS | 显示/隐藏后长度均为 24 |
| 登录不受影响 | PASS | 点击「安全登录」跳转 `/tasks`，标题「任务中心」 |

注意：`type` 改变后 DOM 是**同一个 input 节点**（受控组件），密码经 `window` 中转注入以避免进入源码或表达式文本。

### T02 首页导航菜单

| 检查 | 结果 | 实测 |
|---|---|---|
| 无重复入口 | PASS | 主导航链接 = `['任务中心', '达人库']`，不含「创建任务」 |
| 保留两项 | PASS | 同上 |
| 间距正常 | PASS | 两项垂直间距 4px，分区标签「工作台」存在 |
| 任务中心内入口保留 | PASS | `/tasks` 页内「创建任务」链接 = `['/tasks/new']` |

### T03 任务内达人展示

任务内达人列表（5 行）逐字段与数据库真值对照：

| 指标 | 页面展示 | 数据来源真值 |
|---|---|---|
| 头像 | 已渲染 `<img>` | 快照 `basic.avatar_uri` |
| 昵称 | 甄选聊车 | 快照 `basic.nickname` |
| 标签 | 汽车 · 金融业 · 美妆 · 游戏 | 快照 `basic.creator_type_label` + `basic.industry_labels` |
| 粉丝 | 1,351,784 | `douyin_xingtu_creator_current.followers_count=1351784` |
| 月深度用户 | ≈1,158w | `monthly_deep_users_raw='1,158w'`、`is_approximate=true` |
| 互动 / 完播原始值 | 112 / 551 | `interaction_rate_value_raw=112`、`completion_rate_value_raw=551` |
| CPM / CPE 原始值 | 2969 / 246 | `expected_cpm_21_60_raw=2969`、`expected_cpe_21_60_raw=246` |
| CPM/CPE 第二档可见 | 21–60 秒 · 60 秒以上 2969 / 246（`clipped=false`, `hidden=false`） | `expected_cpm_60_plus_raw=2969`、`expected_cpe_60_plus_raw=246` |

其它检查：行内无溢出（`scrollWidth==clientWidth==579`，视口 1200 无横向滚动）；点击达人行可进入详情（`/tasks/<task>/creators/<creator>`，标题「甄选聊车」，无错误态）。

指标名称与单位**逐字复用达人库**：`粉丝`、`月深度用户`、`互动 / 完播原始值`、`CPM / CPE 原始值`，取值走同一套 `rawMetric` 规则（平台原始值优先、平台标注近似时加 `≈`、缺失显示「暂无数据」）。

### T04 任务完成时间

`/tasks/efb257a6-...` 的页面事实区标签 = `['创建人', '创建时间', '最近更新', '完成时间', '能力版本']`。

| 检查 | 结果 | 实测 |
|---|---|---|
| 存在「完成时间」 | PASS | 仅在任务进入终态后渲染 |
| 「最近更新」仍独立存在 | PASS | 未被改名或替换 |
| 完成时间与库一致 | PASS | 页面 `10/14 10:02`；库 `completed_at=2026-10-14T02:02:10.551872Z`（UTC+8 → 10:02） |
| 语义提示 | PASS | 「最近更新」的 `title` 说明它是「服务端最后一次改动这条任务记录的时间（状态推进、进度保存或人工操作），不代表任务完成时刻」 |

### T05 达人详情统一

同一达人（`700ca5b0-…`）两个入口对比：

| 检查 | 结果 | 实测 |
|---|---|---|
| 任务入口可进入 | PASS | `/tasks/efb257a6-…/creators/700ca5b0-…`，标题「甄选聊车」，无错误态 |
| 达人库入口可进入 | PASS | `/creators/700ca5b0-…`，标题「甄选聊车」，无错误态 |
| 核心字段名一致 | PASS | 两侧 `.library-fields dt` 完全相同（含「预期 CPM（21–60 秒）」等 15 项） |
| 核心字段值一致 | PASS | 两侧 `.library-fields dd` 完全相同（含 `≈1,158w`、`0.01969004266000137`、`2969`、`246`、「暂无数据」等） |
| KPI 区一致 | PASS | 两侧 `.library-metrics .metric` 完全相同（粉丝/月深度用户/互动原始值/完播原始值） |
| 基础面板一致 | PASS | 两侧均含「基础与传播表现」「数据质量与来源」 |
| 无 ID 错位 | PASS | 两个入口解析到同一 creator_id 与同一昵称 |

两入口差异（数据来源客观不同，不属不一致）：任务入口读**任务不可变快照**，保留任务特有的「精选作品」与草稿提示；达人库入口读**当前投影**，保留该入口独有的「商业合作报价」「历史快照」。任务快照中不存在报价观测与历史索引，因此任务入口不渲染这两块，而不是用空值伪造。

### 回归

| 检查 | 结果 | 实测 |
|---|---|---|
| 任务中心 | PASS | `/tasks` 渲染 20 行任务，无错误态 |
| 达人库列表 | PASS | `/creators` 渲染 20 行，无错误态 |
| 创建任务入口 | PASS | `/tasks/new` 标题「创建采集任务」，无错误态 |

### 控制台与网络

- 控制台：整个流程仅 1 条 ERROR，为 `/api/auth/me` 在**未登录时的 401**（预期行为，前端据此显示登录页）；另有 React DevTools 的 INFO 提示。无 JS 异常。
- 网络：问题请求仅上述 401；页面内未出现 5xx 或失败的业务请求。
- 巨量星图请求：0（本轮未触发任何采集）。

## 4. 截图证据

| 文件 | 内容 |
|---|---|
| `assets/ui01/T01-login-password-toggle.png` | 登出后的登录页：账号已填、密码为掩码态、输入框右侧眼睛图标 |
| `assets/ui01/T02-sidebar-navigation.png` | 任务中心：主导航仅「工作台 / 任务中心 / 达人库」，页头「创建任务」按钮保留 |
| `assets/ui01/T03-task-creator-metrics.png` | 任务详情「任务内达人」5 行：头像、昵称、标签、粉丝、月深度用户、互动/完播、CPM/CPE（两档） |
| `assets/ui01/T04-task-completion-time.png` | 任务详情事实区：「最近更新」与「完成时间」并列 |
| `assets/ui01/T05-task-entry-creator-detail.png` | 任务入口的达人详情 |
| `assets/ui01/T05-library-entry-creator-detail.png` | 达人库入口的同一达人详情（含报价与历史快照） |
| `assets/ui01/REG-creator-library-list.png` | 达人库列表回归 |
| `assets/ui01/REG-create-task-entry.png` | 创建任务入口回归 |

## 5. 自动化检查

| 检查 | 命令 | 结果 |
|---|---|---|
| 后端 lint | `.venv/bin/ruff check backend conftest.py tests scripts` | All checks passed |
| 后端 format | `.venv/bin/ruff format --check backend conftest.py tests scripts` | 76 files already formatted |
| 后端 typecheck | `.venv/bin/mypy backend/src` | Success: no issues found in 30 source files |
| 后端单元 | `.venv/bin/pytest backend/tests/unit -q` | 189 passed |
| 后端集成 | `XINGTU_TEST_DATABASE_URL=…xingtu_test_m3 .venv/bin/pytest backend/tests/integration -q` | 81 passed, 1 skipped |
| 前端类型 | `frontend: npx tsc -b` | exit 0 |
| 前端测试 | `frontend: npx vitest run` | 9 passed |
| 前端构建 | `frontend: npm run build` | 构建成功（`dist/assets/index-*.js` 364.92 kB） |

本轮新增/修改的测试：

- `backend/tests/integration/test_repository.py::test_completed_at_only_moves_on_the_transition_into_a_terminal_state`：验证采集侧写入路径只在进入终态时写入 `completed_at`，非终态推进不写、后续重开不移除。
- `backend/tests/integration/test_product_m3.py::test_completed_at_is_recorded_once_a_task_reaches_a_terminal_state`：验证进行中任务 `completed_at` 为 `null`、取消后写入且 API 与库一致、后续 `updated_at` 刷新不覆盖。
- `frontend/src/App.test.tsx` 新增 5 例（登录密码切换与提交、导航菜单、任务内达人指标、完成时间、两入口达人详情一致），把 `completed_at` 补进任务夹具，并修正 1 处既有的**脆弱断言**（`findByText("等待安全验证")` 会同时命中状态徽标与标题，此前还要靠上一个用例遗留的 DOM 才能通过；改为 `findAllByText`、新增 `cleanup()` 隔离渲染树，并补齐登录后 `/tasks` 的 mock）。该修正属测试代码改动，未修改任何业务行为。

## 6. 数据库与接口影响

- 迁移 `012_root_task_completed_at.sql`：`root_tasks` 新增可空 `completed_at timestamptz`，不改写已有列；存量终态行以 `updated_at` 回填（**回填值是推定值**，因为历史行没有记录终态转换时刻，卡片与本文均标注该限制）。
- 写入点：`Repository._save`、`ProductRepository.fail_intake`、`ProductQueries.command`（取消早退与 P2 重开两条路径）。`updated_at` 语义与写入点**未改变**。
- 读取：`GET /api/tasks`、`GET /api/tasks/{id}` 的 `TaskSummary`/`TaskDetail` 新增 `completed_at`（新增可空字段，向后兼容；旧客户端忽略即可）。
- 未新增/修改任何采集、解析、标准化、去重、持久化业务逻辑、Workflow、Scheduler、Worker、Queue、ExecutionUnit 实现；未改动达人数据与达人库读模型。

## 7. 已知限制与未覆盖项

1. **`completed_at` 存量回填是推定值**：迁移用 `updated_at` 回填历史终态任务。仅当「最后一次写入恰好是把任务置为终态的那次」时两者相等（参照任务确实如此），不能作为历史任务完成时刻的原始证据。
2. **任务重开后 `completed_at` 保留首次终态时刻**：任务进入终态后再 `retry`/`continue`，`completed_at` 不会清空也不会重写。页面仅在任务处于终态时展示该字段，且 `updated_at` 仍可反映最新活动。
3. **本轮未执行真实采集**：T01—T05 与回归只读取既有真实任务/达人数据。若需验证「新任务从创建到终态的完成时间写入」，需另行授权发起真实星图采集（本轮未发起）。
4. **Playwright MCP 调用方式**：见第 2 节，本会话无 `mcp__playwright__*` 工具，改用同一 MCP server 的 stdio 客户端；该偏差已获用户确认并在此标注。
5. **Chrome 启动参数**：因外层沙箱限制追加 `--no-sandbox`、使用项目运行目录 profile；与生产/常规 MCP 启动参数的差异如实记录。
6. **任务详情右栏较窄**：`任务内达人` 位于窄侧栏时，CPM/CPE 第二档说明会换行（改动前会被裁切）。已改为换行显示并加断言保证不被裁切；如需更宽展示，属后续布局调整，本轮未扩大改动。
