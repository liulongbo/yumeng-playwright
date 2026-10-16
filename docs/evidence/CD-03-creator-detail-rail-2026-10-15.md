# CD-03 验收证据：达人详情左侧信息模块调整（2026-10-15）

本轮交付 [CD-03 任务卡片](../tasks/CD-03.md) 的 11 项需求。所有结论基于实际运行中的本机开发栈、真实开发库数据与真实 Chrome，不含模拟数据或伪造结果。

## 1. 环境与代码版本

| 项目 | 值 |
|---|---|
| 日期/时区 | 2026-10-15（本地 UTC+8） |
| 分支 | `llb_1013`（未提交、未切换、未合并） |
| 工作区 | 存在其他任务的未提交改动（SESSION-01、FIX-01、LIB-01、UI-01、FILTER-01、CD-01/02 等），本轮未覆盖、未还原、未清理 |
| 前端 | `http://127.0.0.1:5173`（Vite dev，pid 22490） |
| 后端 API | `http://127.0.0.1:8000`，本轮**重启**为 pid 68131（该 API 无热加载且先于本次改代码启动） |
| 数据库 | `xingtu_development`（127.0.0.1:55432，开发库，只读查询 + 既有 API 读取） |
| 账号 | `media-a`（口令取自 `.runtime/qa-credentials.env`，未写入证据文件） |
| 参照达人 | `700ca5b0-f0c8-4436-86fe-624dfeb0f151`（甄选聊车，星图ID `7503176021160493065`，达人库入口） |
| 参照任务 | `efb257a6-476b-47ee-aff4-807795bb61a0`（既有真实采集任务，任务入口；**本轮未发起任何新采集**） |
| 本轮改动文件 | `frontend/src/format.ts`(+test)、`profile/CreatorProfile.tsx`、`profile/views.ts`、`profile/ProvenanceDrawer.test.tsx`(新)、`pages.tsx`、`types.ts`、`snapshotCreator.ts`、`styles.css`、`App.test.tsx`、`profile/CreatorProfile.test.tsx`；`backend/src/xingtu/product_models.py`、`product_queries.py`、`backend/tests/unit/test_product_models.py`；`scripts/acceptance/run_cd03_acceptance.py`(新)、`run_cd02_acceptance.py`(回归基线跟进) |

## 2. 字段核实（只读数据库，先证据后实现）

| 待确认 | 核查方式 | 结论 |
|---|---|---|
| 星图ID 是哪个字段 | `contracts/douyin_xingtu.verified.json` 的 `basic.platform_creator_id`，契约名「星图ID」、`kind: text`；与参考图 C位小师妹 对照 | 参考图 `7360610271510921225` = 库内 `douyin_xingtu_creator_current.platform_creator_id`，逐字一致；内部 `creator_id` 是 UUID，显然不是星图ID |
| 性别是否有数据 | 23 位达人最新快照的 `basic.gender` | 全部 `COLLECTED`：`1`×12、`2`×10、`0`×1；`douyin_xingtu_creator_current` **无** gender 列（在 JSONB 投影中） |
| 性别编码含义 | 项目内线上证据 | `2 = 女` 已由 [CD-02 平台口径核对](CD-02-platform-parity-2026-10-14.md) 于 2026-10-14 确证；`1`/`0` 无项目内线上证据（按用户决策 A 展示并标注） |
| 介绍字段 | `basic.introduction`（`path_ref=self_intro`）→ `creator_current.introduction` → API `CreatorLibraryDetail.introduction` | 已采集、已投影、API 已返回；本轮只缺前端展示 |
| 三项数量指标存的是原值还是换算值 | 库内 `followers_count=1351784`、`monthly_connected_users_count=23439854`、`monthly_deep_users_count=11580000`；`monthly_deep_users_raw='1,158w'` | 存的是**原始人数**，单位换算必须只在展示层做 |
| 平台自身如何展示这三项 | [CD-02 平台口径核对](CD-02-platform-parity-2026-10-14.md) | 平台按「万」展示：月连接用户 `2,376.6w`、月深度用户 `1,167.5w`、粉丝 `135.2w`（粉丝到 0.1w） |
| 已有 k/w 格式化函数 | 全仓检索 | 无。新增 `countUnitText`，未改动既有 `countText` 的语义与调用方 |

## 3. 验收工具与调用方式（如实说明）

- 本会话的工具注册表**未暴露** `mcp__playwright__*` 工具，因此**不是"MCP 工具直调"**。沿用本项目 CD-01/CD-02/UI-01 已登记的做法：用同一 Playwright MCP server 的 **stdio 协议客户端**（`scripts/acceptance/mcp_client.py`）驱动 `@playwright/mcp` + 本机 Chrome。
- MCP server 版本 `1.62.0-alpha-2026-06-29`，握手返回 **23** 个 `browser_*` 工具（报告中 `CD03-MCP` 检查项记录该事实）。
- 浏览器为**真实 Chrome**；profile 与 `--no-sandbox/--disable-gpu` 参数与本项目既有验收一致（外层文件沙箱限制）。

复现命令：

```bash
# 0) 若 API 进程早于本次改动启动（无热加载），重启本地 API
kill <api_pid> && (set -a; . .runtime/m3-app.env; set +a; nohup .venv/bin/xingtu-api >> .runtime/logs/api.log 2>&1 &)
# 1) 用项目绑定的 Chrome 登录一次
XINGTU_QA_PASSWORD="$(awk -F= '/^QA_MEDIA_A_PASSWORD=/{print substr($0,index($0,"=")+1)}' .runtime/qa-credentials.env)" .venv/bin/python scripts/acceptance/seed_auth.py
# 2) CD-03 验收（38 项）
XINGTU_QA_PASSWORD="$(awk -F= '/^QA_MEDIA_A_PASSWORD=/{print substr($0,index($0,"=")+1)}' .runtime/qa-credentials.env)" .venv/bin/python scripts/acceptance/run_cd03_acceptance.py
# 3) CD-02 既有回归（31 项，2 项 SKIPPED）
XINGTU_QA_PASSWORD="$(awk -F= '/^QA_MEDIA_A_PASSWORD=/{print substr($0,index($0,"=")+1)}' .runtime/qa-credentials.env)" .venv/bin/python scripts/acceptance/run_cd02_acceptance.py
```

## 4. 逐项验收结果（真实 Chrome）

机器可读结果：[CD-03-acceptance-2026-10-15.json](CD-03-acceptance-2026-10-15.json)，**38/38 通过**（退出码 0）。下表为其中与 11 项需求直接对应的断言；两入口（达人库 / 任务快照）断言完全相同。

| 需求 | 检查项 | 实测 |
|---|---|---|
| UI-01 页面打开 | `CD03-{LIB,TASK}-UI01-page` | 两入口昵称均为「甄选聊车」，左右分栏与 6/5 个分区正常 |
| 4.1 采集完整 | `…-UI02-UI08-UI09-UI10-removed` | 左栏文本不含「采集完整/数据不完整/字段采集完整/存在待补齐字段」；`rail-actions` 为空 |
| 4.2 星图ID | `…-UI03-star-id`、`…-UI03-internal-id-absent` | 昵称下方 `星图ID 7503176021160493065`（库内逐字一致）；内部 `700ca5b0-…` UUID 不出现 |
| 4.3 指标顺序 | `…-UI04-order` | `['月连接用户','月深度用户','粉丝','月涨粉率']` |
| 4.4 数量单位 | `…-UI05-units` | `['2,344.0万','≈1,158.0万','135.2万']` + 月涨粉率 `1.97%`；`≈` 来自平台 `is_approximate` |
| 4.5 主题/行业顺序 | `…-UI06-tag-order`、`…-UI06-tag-content` | `['达人类型','内容主题','行业标签']`；内容主题 10 项、行业标签 `金融业/美妆/游戏`（内容未被改动） |
| 4.6 性别 | `…-UI07-gender` | 值 `女`，`title='平台编码 2（2026-10-14 线上确证）'` |
| 4.7 观测时间 | 同 removed 项 | 左栏无「观测/观测时间」 |
| 4.8 完整性状态 | 同 removed 项 | 左栏无「完整性」行 |
| 4.9 指定文案 | 同 removed 项（`copy=False`） | 达人库入口页面不含「商业与表现指标均为平台原始值」 |
| 4.10 数据来源区域 | 同 removed 项、`CD03-UI11-source-drawer-retained` | 左栏已无「数据来源」按钮/区域；**字段来源数据未删**：`CD03-UI11-drawer-81` = 81 字段 / 8 模块，`CD03-UI11-drawer-provenance` = 名称修正标记 + 81 处观测时间 |
| 4.11 介绍 | `…-UI12-introduction` | `关注我，带你每日了解一个汽车知识🚗`；`white-space=pre-wrap`、`overflow-wrap=anywhere` |
| UI-13 空值 | `CD03-UI13-empty-state` | DOM 夹具把 性别/介绍 置空后：左栏存活、无错误态、显示「平台暂无数据」、无 `null` 文本 |
| UI-14 长文本 | `CD03-UI14-long-text-no-overflow` | 超长多行介绍：`rail=false`、`page=false`（无横向溢出） |
| UI-15 刷新 | `CD03-UI15-reload` | 刷新前后 KPI 值完全一致 |
| UI-16 路由 | `CD03-UI16-back-link/back-navigation` | 「返回达人库」→ `/creators`，实际跳转成功 |
| UI-17 字段联通 | `CD03-UI17-api-fields`、`CD03-UI17-raw-metrics` | `GET /api/creator-library/700ca5b0-…`：`platform_creator_id=7503176021160493065`、`gender="2"`、`introduction=关注我，…`；`monthly_connected_users.value=23439854`、`monthly_deep_users.value=11580000`、`followers.value=1351784`、`unit=count` |
| UI-18 整体布局 | `CD03-library-rail.png`、`CD03-library-mobile-390.png` | 与参考图信息层级/顺序一致；390px 下 KPI 两列、无横向溢出 |
| UI-19 回归 | `…-regression-no-raw-json`、`…-UI19-chapters` + CD-02 回归 31/31 | 无原始 JSON 泄漏；分区与图表/分层/趋势/报价/历史均复现 |

截图（`docs/evidence/assets/cd03/`）：`CD03-library-rail.png`（达人库入口桌面）、`CD03-task-rail.png`（任务入口桌面）、`CD03-library-mobile-390.png`（390px 移动端）、`CD03-library-provenance.png`（保留的字段来源抽屉，81 字段）、`CD03-long-intro-dom-fixture.png`（超长介绍）、`CD03-back-to-library.png`（返回路由）。

控制台：脚本在浏览器会话中未捕获到 JS 异常（`console_errors` 记录为空数组；页面级 `pageerror` 无输出）。

## 5. 静态与单元验证

| 层 | 命令 | 结果 |
|---|---|---|
| 前端类型 | `npm --prefix frontend run lint`（`tsc -b`） | 通过（exit 0） |
| 前端构建 | `npm --prefix frontend run build` | 通过（1742 modules，dist 产出正常） |
| 前端测试 | `npx --prefix frontend vitest run` | **55 passed / 5 files**（`format.test.ts` 24、`profile/views.test.ts` 11、`profile/ProvenanceDrawer.test.tsx` 1、`profile/CreatorProfile.test.tsx` 9、`App.test.tsx` 10） |
| 后端单测 | `.venv/bin/python -m pytest backend/tests/unit -q` | **210 passed** |
| 后端静态 | `ruff check`（相关文件）、`mypy product_queries.py product_models.py` | 通过（`Success: no issues found in 2 source files`） |
| 格式/差异 | `git diff --check` | 通过（exit 0） |
| 未被要求且未执行 | `ruff format --check` 全量 | 有 6 个文件的**既有**漂移（非本卡引入，见下），未执行全量格式化以免改动无关文件 |

## 6. `countUnitText` 边界（用户确认的 A 方案）

单测 `frontend/src/format.test.ts` 锁定：

| 输入 | 输出 | 说明 |
|---|---|---|
| `23439854` | `2,344.0万` | 实际页面值（月连接用户数） |
| `11580000` + approximate | `≈1,158.0万` | 实际页面值（平台近似值） |
| `1351784` | `135.2万` | 实际页面值；与平台 `135.2w` 一致（四舍五入） |
| `10000` / `9999999` | `1.0万` / `1,000.0万` | 万的下边界 |
| `9999` / `1000` / `7540` | `10.0k` / `1.0k` / `7.5k` | k 分支（真实数据不会触发，规则完整性由单测覆盖） |
| `999` / `0` | `999` / `0` | 千以下保留原数 |
| `null`/`""`/`"-"`/`"20,000 - 100,000"`/`true` | `—` | 平台空值与区间不臆造数字 |
| `-2688009` | `-268.8万` | 负值（月涨粉率走 ratio 路径，不经过此函数） |

## 7. 未执行 / 未验证事项（不记为通过）

1. **隔离 PostgreSQL 集成测试库 `55439` 拒绝连接**：`127.0.0.1:55439` 与 `55440` 均未监听，`backend/tests/integration/test_creator_library.py`、`test_repository.py` 未复跑。本卡 API 改动（新增只读 `gender`）已由真实 API + 真实开发库 + 单元测试覆盖映射规则，但**集成层未验证**，沿用 CD-01/CD-02 既有缺口。
2. **性别编码 `1`（男）/ `0`（未知）未经本项目线上复核**：仅 `2=女` 有 2026-10-14 线上确证记录。当前按用户决策 A 展示并在 `title` 与代码注释中标注"常规编码，未经本项目线上复核"。
3. **CD-02 报告中的 2 个 provenance 检查项**：因 4.10 移除左栏入口，在 CD-02 脚本中记为 `SKIPPED`（详情字符串明确写"未在此验证"）；对应数据与组件能力由 CD-03 的 `CD03-UI11-drawer-81`/`-provenance` 覆盖。
4. **未验证真实采集链路**：本轮未发起采集、未访问巨量星图、未执行 P1 转换；不据此宣称采集/调度/Worker/入库链路已端到端回归。
5. **未做视觉像素级对比**：参考图是巨量星图移动端页面的局部截图且数据为另一时点，本轮的"布局一致"是结构/层级/顺序一致性判断，不是像素对比；平台原生的虚线标签下划线等局部装饰未逐像素复刻。

## 8. 遗留问题

| 级别 | 问题 | 归属 |
|---|---|---|
| P2 | `ruff format --check backend conftest.py tests scripts` 有 **6 个文件**既有格式漂移；本轮未做全量格式化以免波及无关文件（`git diff` 未含无关改动） | 项目原有（此前未提交工作） |
| P2 | `frontend/src/profilePresentation.tsx` 早已不被引用（CD-01/CD-02 记录在案），是否删除待用户决定 | 项目原有 |
| P2 | 左栏标签未做「+N」折叠：参考图中内容主题只显示 2 个标签 + `8+`，本项目按完整标签展示。用户未提出折叠需求，且折叠会隐藏真实数据，故未实现 | 本轮范围外/待确认 |
| P1 | 性别 `1`/`0` 的线上确证缺失（见第 7 节第 2 条） | 本轮引入展示、证据不足 |
| P1 | 集成测试库不可用导致集成层未复跑 | 项目原有（CD-01 起） |

本轮**未引入 P0 问题**；未发现与本轮改动相关的失败项。
