# KJX-01 阶段 C macOS 真实环境验收证据

状态：**macOS 阶段 C 验收通过（C1 / C2 / C3 / C4 全部 GO）**  
验收时间：2026-10-28 23:04—23:55 +08:00（15:04—15:55 UTC）  
平台：macOS；隔离 Stage C 栈；生产业务库、生产 Feature Flag、Windows 均未改动。  
关联卡片：[KJX-01](../tasks/KJX-01.md)。

## 1. 结论

| 阶段 | 结果 | 关键结论 |
|---|---|---|
| C1 真实环境与前置 | **GO** | 隔离 DB/API/Vite/Temporal/Worker、真实 DeepSeek、真实 Chrome、聚星/星图 Profile 会话、合同、Flag、任务/达人库 API 均可用；迁移 020 升级路径通过 |
| C2 聚星 1 位真实闭环 | **GO** | 前端提交 → 真实 DeepSeek → FastAPI → Temporal → Worker → 聚星 Chrome/Profile → Adapter → PostgreSQL → 任务中心/达人库/详情全部通过；`COMPLETED`，目标/有效/资料完整 = 1/1/1 |
| C3 聚星 10 位真实闭环 | **GO** | 「母婴 / 母婴亲子 / 10 位」`COMPLETED`，有效 10、资料完整 10、快照 10、平台身份唯一 10；仅使用第一页 20 位候选，未开发/未调用第二页 |
| C4 星图真实回归与双平台隔离 | **GO（含一次真实重试）** | 星图「宠物 / 目标 1」重试任务 `COMPLETED`，资料完整 1、F06 双集合完整 1；同单元跨平台严格串行、账号/Profile/数据隔离成立 |

阶段 C 的真实回归发现并修复了聚星 SPA 偶发 `Page.goto` 超时导致的误判；C2 前两次失败、第三次成功，C3/C4 在修复后的导航回退上通过。C4 第一次真实任务因候选自身字段缺口/单个画像响应不可解析为 `PARTIAL_COMPLETED`，同一授权样本重试后通过；两次结果均保留，不把第一次伪装成通过。

## 2. 隔离环境（C1）

| 组件 | 值 |
|---|---|
| 数据库 | 本机测试 PostgreSQL `127.0.0.1:55439`，独立库 `xingtu_test_stage_c`，迁移到 20 |
| Temporal | `127.0.0.1:57234`（dev server headless，独立 SQLite `.runtime/juxing-stage-c/temporal.db`） |
| API | `127.0.0.1:4190`，真实 Uvicorn / FastAPI |
| 前端 | `127.0.0.1:4191`，真实 Vite 7.3.7 |
| Redis | 本机 `127.0.0.1:6379` DB 14 |
| 执行单元 | `unit-local-mac-02`，worker generation 2；平台绑定双行 |
| 浏览器 | 系统 Chrome `156.0.8078.49`，Playwright `1.63.0` |
| DeepSeek | `deepseek-flash`，真实 `/models` 与 `/responses` 200；prompt `m3-filter-plan-v2` |
| 聚星合同 | `contracts/kuaishou_juxing.verified.json` / `juxing-video-creator-stage-b-v1` |
| 星图合同 | `contracts/douyin_xingtu.verified.json` / `xingtu-ad-creator-featured-v13`，能力 `xingtu-ad-creator-square-v3` |
| Flag | `XINGTU_ENABLE_KUAISHOU_JUXING=1`；`XINGTU_KUAISHOU_JUXING_MAX_TARGET_COUNT=10` |
| 旧运行栈 | API `8000`、Vite `5173`、Temporal `57233` 未停止、未改配置；Stage C 使用独立端口/库 |

旧栈开工前任务队列 backlog 为 0；Stage C 全部任务只写入隔离库 `xingtu_test_stage_c`。生产业务库只读检查因目标 `100.86.124.51:5432` 网络超时未执行，未写入任何生产数据。

### C1 验证结果

- 迁移：`pytest backend/tests/integration/test_migrations_020.py` → **2 passed**；覆盖 001–019 旧星图库 → 020：旧 `root_tasks` 回填 `douyin_xingtu`、旧单元回填平台绑定/会话观察、`requirement_form.v1/v2/v3` 均可写入、重复运行不重复应用。
- API：登录 200；`/api/platforms` 返回两平台均为 `verified`；聚星能力 `target_count_max=10`，星图仍为 20/200。
- Temporal：`temporal operator cluster health` = `SERVING`；`xingtu-intake` 与 `xingtu-unit-local-mac-02` 均有 activity/workflow poller。
- DeepSeek：启动即真实 `GET /models` 200；C2/C3/C4 的 intake 均 `POST /responses` 200，`model_runs.status=succeeded`，`deepseek-flash`。
- 聚星只读探针：`session_status=VALID`、`account_match=true`、受保护页已验证；搜索第一页 **20** 位、`total=2311`、`first_page_supports_10=true`；关键词「母婴」与 `maternal_child` 均进入请求体。
- 星图会话诊断：`VALID / PROTECTED_PAGE_AND_ACCOUNT_VERIFIED`，账号匹配，快照首次导航前恢复，Chrome 正常关闭；诊断报告不保存明文 Cookie。
- 浏览器兼容检查：Chrome 156、Playwright 1.63.0、启动/开页/关闭均通过；聚星独立 Profile 的完整冷启动由真实探针与 C2/C3 验证。
- 任务/达人库 API：登录后 `/api/tasks`、`/api/creator-library?platform=kuaishou_juxing` 可读；前端真实登录截图见私有 `.runtime/juxing-stage-c/c1-ui-home.png`。

## 3. C2：聚星 1 位真实闭环

- 任务：`ed5de9dc-bd99-4d10-abca-01379cd6e51c`（前端「聚星 / 母婴 / 母婴亲子 / 目标 1」提交）
- 计划：真实 DeepSeek 生成 `filter_plan.v3`，仅 `keyword=母婴` + `content_type=[maternal_child]`，`target_count=1`，无第二页能力。
- 结果：`COMPLETED`；`discovered_count=20`、`valid_count=1`、`profile_complete_count=1`、`featured_complete_count=0`、`failed_count=0`。
- 快照：4 模块 `basic / spread / works / audience` 全部 `COLLECTED`，`profile_complete=true`，`pipeline_complete=true`；`douyin_xingtu_creator_current` 中该平台为 0 行。
- 真实源对照：同一达人详情只读回读与快照逐组一致（身份、粉丝、月涨粉数/率、内容类型、三档报价、播放中位数、预估播放、预期 CPM、互动率、完播率、视频数、作品数、受众两块）；对照报告私有 `.runtime/juxing-stage-c/c2-source-comparison.json`，全部 `match=true`。
- UI：任务中心/任务详情/任务内达人/达人库列表/达人库详情/传播表现/代表作品/受众画像均从真实 API 读取；截图在 `.runtime/juxing-stage-c/c2c-*.png`。
- 已知口径：平台「作品波动」卡的点赞/评论/分享是**前 15 个作品均值**，与统计接口 `pavg*` 字段口径不同。阶段 C 已在聚星详情同时保留两者：统计接口字段加「（统计接口）」标签，作品卡新增「作品波动（最近15个作品平均）」派生展示，避免把两种口径混为一个值。
- 显示修正：聚星任务内达人和达人库的「月涨粉率」原显示裸比例（如 `-0.0012`），已按比例格式化为 `-0.12%`，与详情页一致；前端 99 用例包含该断言。
- 真实失败/重试：前两次前端任务 `3c2cec80…`、`c38afd5b…` 在聚星入口 `Page.goto` 等待 `domcontentloaded` 30 秒超时，终态 `FAILED / PLATFORM_PAGE_CHANGED:BROWSER_ACTION_FAILED`，未写入达人；第三次 `c2c` 在同一环境成功；随后新增平台专用导航回退，并由 C3/C4 真实任务验证。失败证据保留在隔离库与 `.runtime/evidence/failure/`。

### 导航回退修复

- 文件：`backend/src/xingtu/juxing_adapter.py`。
- 行为：首次 `goto(domcontentloaded)` 超时后，若页面已在聚星域且注册的就绪面可见，按晚到加载继续；否则用 `wait_until=commit` 重试并等待同一注册就绪面；仍失败才抛 `PLATFORM_PAGE_CHANGED:JUXING_NAVIGATION_TIMEOUT`。登录/挑战/账号仍由 `check_session` 校验，不放宽合同。
- 测试：`backend/tests/unit/test_juxing_adapter.py` 新增 2 条导航回退用例，**6 passed**。

## 4. C3：聚星 10 位真实闭环

- 任务：`430eaabf-927b-4a72-81e9-94255747569a`（前端「聚星 / 母婴 / 母婴亲子 / 目标 10」）
- 结果：`COMPLETED`；`discovered_count=20`、`valid_count=10`、`profile_complete_count=10`、`featured_complete_count=0`、`failed_count=1`。
- 数据：`task_creators=10`、`creator_snapshots=10`、平台身份唯一 10、全部 `kuaishou_juxing`；1 个候选因 `IDENTITY_UNREADABLE` 未计入有效。
- 边界：只读第一页 20 位即满足 10；**未实现、未调用第二页**，合同第二页仍 fail closed（`JUXING_PAGE_2_NOT_VERIFIED`）。
- 真实源对照（前 2 位有效达人）：第 2 位 12 项关键字段全等；第 1 位 11/12 全等，`monthly_follower_growth_count` 在采集时为 `NO_DATA`，但月涨粉率与其后页面源值 `-0.12%` 一致；采集后页面回读出现 `-208` 的涨粉数，属于实时计数/采集时响应缺口，未写成错误值。报告私有 `.runtime/juxing-stage-c/c3-source-comparison.json`。
- UI 截图：`.runtime/juxing-stage-c/c3-task.png`、`c3-task-creator-*.png`、`c3-library*.png`。
- 私有诊断任务 `4e9d7fee…` 由 BrowserHost 导航诊断脚本创建，集合 worker 自动认领并完成 1 位，未用于 C2/C3 验收计数；它解释了隔离库额外的 1 位聚星达人和库总数，不影响 C3 任务内 10 位唯一性。

## 5. C4：星图真实回归与双平台隔离

### 5.1 第一次真实任务（保留为失败证据）

- 任务：`b333b030-176a-4aad-b8f2-f8073a00780e`（前端「星图 / 宠物 / 目标 1」，在 C3 运行期间提交）
- 结果：`PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE`；`valid_count=1`、`profile_complete_count=0`、`featured_complete_count=1`、`failed_count=2`。
- 缺口：`fans` 模块 `PLATFORM_PAGE_CHANGED:RESPONSE_SCHEMA_MISMATCH`（`daily_link` 返回 200 JSON 但 JSON 解析失败）；`seeding / conversion / fulfillment` 存在 `MISSING_SOURCE` 缺字段。
- 结论：真实任务正确返回部分完成，未把不完整达人算作资料完整；不能据此判 C4 GO。

### 5.2 重试任务（C4 通过证据）

- 任务：`664d94b4-b5b2-4ab1-8be8-64c0c98016eb`（同一授权样本：星图 / 宠物 / 目标 1）
- 结果：`COMPLETED`；目标 1、有效 1、资料完整 1、精选完整 1、失败步骤 0。
- 快照：8 个资料模块全部 `COLLECTED / complete=true`；`profile_coverage` 记录 `COLLECTED=80`、`NO_DATA=1`、`FAILED=0`，`gaps=[]`。
- F06：`collections.excellent_reach` 与 `collections.excellent_seeding` 均 `COMPLETE`，各 4 张卡片（共 8 张），`featured_complete=true`。
- 真实页面关键值对照（UI 截图 `.runtime/juxing-stage-c/c4b-library-detail.png`）：
  - 粉丝 `5,699,586` ↔ 页面 `570.0万`；
  - 预期 CPM `9,556 / 11,945`（两档）↔ 页面 `9,556 / 11,945`；
  - 完播率 `75.32%`、互动率 `2.01%` ↔ 页面 `75.32% / 2.01%`；
  - 优秀传播视频 4 条、优秀种草视频 4 条 ↔ 页面两卡各 4 条。
- UI：任务详情显示「资料完整 1 / 精选完整 1（F06 双集合）/ 失败步骤 0」，达人库详情展示两组精选与真实封面；截图 `.runtime/juxing-stage-c/c4b-*.png`。

### 5.3 同单元串行与隔离

- C3 创建于 `15:26:51 UTC`，`15:31:47 UTC` 完成；C4 第一次任务在 `15:27:49 UTC` 创建，处于 `QUEUED` 时单元 `current_root_task_id` 仍为 C3，C3 完成后才执行；C4 重试在 C3 完成后创建并执行。
- 执行单元始终只有一个 `current_root_task_id`；collection worker 同一时刻只处理一个任务，未出现双平台并发采集。
- 平台绑定两行，账号/Profile/registry 独立（证据中脱敏）：
  - 星图：`ID: 1807…19`，Profile `.runtime/profiles/unit-local-mac-02`；
  - 聚星：`6082…64`，Profile `.runtime/profiles/unit-local-mac-02-juxing`。
- 数据隔离：跨平台任务-达人错配 **0**；聚星达人出现在星图当前投影 **0**；聚星/星图任务各自只关联本平台达人；两平台各自合同/能力版本独立。
- Flag 开启时只启用聚星入口；Flag 关闭的门禁由阶段 B 自动回归与本次单元/合同回归覆盖，未另起生产 API。

## 6. 回归与静态检查

| 项目 | 结果 |
|---|---|
| 后端单元 + 合同 | **388 passed**（57.43s） |
| 隔离 PostgreSQL 集成 | **118 passed / 1 skipped**（242.19s；MinIO 未配置为既有跳过） |
| 迁移 020 专项 | **2 passed** |
| 聚星导航回退专项 | **6 passed** |
| 前端 | **99 passed**；lint/tsc 通过；Vite build 通过 |
| E2E | **14 passed**（30.26s，设置 `XINGTU_TEMPORAL_TEST_BINARY` 后） |
| Ruff（本卡改动文件） | 通过 |
| Ruff format（本卡改动文件） | 通过 |
| Mypy strict（5 个核心后端文件） | `Success: no issues found in 5 source files` |
| `git diff --check` | 通过 |

已知既有问题：`scripts/acceptance` 的 11 个 `UP031` 仍使全仓 `make check` 失败，与本卡改动无关；未在本轮修改。

## 7. 边界、未做与残余

- **未**应用迁移 020 到正式业务库；**未**开启生产 Feature Flag；**未**写生产数据。
- **未**做 Windows 实机/配置验收；Windows 移交独立 `DEPLOY-WIN-01`。
- **未**实现/调用聚星第二页；第一页 20 位已满足 10 位，第二页继续 fail closed。
- **未**执行直播、电商/履约深层、联系方式、平台下单/导出等 P0 外能力。
- 生产业务库只读检查因网络超时未完成；本证据不声称已核对生产库版本/备份。
- C4 第一次任务为 `PARTIAL_COMPLETED`；同一授权样本重试后通过。C3 抽样第 1 位有 1 个可选的近 30 天涨粉数采集时 `NO_DATA`，未伪造为 0。
- 聚星「统计接口平均值」与「页面作品波动前 15 均值」口径已在 UI 明确区分；没有把两者强行合并。
- 私有证据目录 `.runtime/juxing-stage-c/` 权限 `0700`，环境/凭据/驱动脚本 `0600`；文中不包含 Cookie、Token、DSN、快照原文、达人昵称/头像。

## 8. 证据索引（本机私有）

| 文件 | 内容 |
|---|---|
| `.runtime/juxing-stage-c/c1-juxing-probe.json` | 聚星会话、账号、第一页 20 位、total、关键词/内容类型请求 |
| `.runtime/session-diagnostics/unit-local-mac-02-20261028T150649Z.json` | 星图会话 VALID、快照恢复、非明文 Cookie 摘要 |
| `.runtime/juxing-stage-c/c2c-run.json` / `c2c-*.png` | C2 任务结果与 UI |
| `.runtime/juxing-stage-c/c2-source-comparison.json` / `c2-source-detail.png` | C2 真实源对照与详情页截图 |
| `.runtime/juxing-stage-c/c3-run.json` / `c3-*.png` | C3 任务结果与 UI |
| `.runtime/juxing-stage-c/c3-source-comparison.json` | C3 两位抽样源对照 |
| `.runtime/juxing-stage-c/c4b-run.json` / `c4b-*.png` | C4 重试任务结果与 UI |
| `.runtime/juxing-stage-c/logs/` | API、intake、worker、Temporal、Vite、驱动日志 |
| `.runtime/evidence/failure/` | C2 导航失败与 C4 第一次部分完成的失败证据（无正文秘密） |

## 9. 验收结论

macOS 阶段 C 的 C1—C4 均已取得真实、可复核证据：真实 DeepSeek、Temporal、Worker、Chrome/Profile、Adapter、PostgreSQL 与前端 UI 形成闭环；聚星 1 位与 10 位任务均 `COMPLETED`，星图 1 位重试任务 `COMPLETED` 且 F06 双集合完整；同单元跨平台串行和账号/Profile/数据隔离成立。

因此 **KJX-01 的 macOS P0 / 阶段 C 可标记通过**；KJX-01 总体仍保留“进行中/待验收”，仅因 Windows 验收已按用户要求移出本轮，交由 [DEPLOY-WIN-01](../tasks/DEPLOY-WIN-01.md) 单独跟踪。生产业务库、生产 Flag 与平台写操作仍未变更。
