# JUXING-MAIN-01 主站双平台整合与真实验收证据

状态：**GO（macOS 本机 5173 主站双平台整合范围）**  
验收时间：2026-10-31 02:22—02:35（Asia/Shanghai）  
目标环境：`http://127.0.0.1:5173` 主站 + `xingtu_development` 主业务库 + 同一个 `unit-local-mac-02` 执行单元。  
关联：[任务卡](../tasks/JUXING-MAIN-01.md)、[整合方案](../design/JUXING-MAIN-01-integration-plan.md)、[测试用例](JUXING-MAIN-01-test-cases.md)、[切换前检查清单](JUXING-MAIN-01-pre-switch-checklist.md)、[独立 QA 回归](JUXING-MAIN-01-post-integration-regression.md)。

## 1. 结论

**GO**。5173 主站已真正同时支持巨量星图与磁力聚星：

- 两平台各 1 位真实采集任务均 `COMPLETED`，有效/资料完整/目标均 1/1/1；
- 两个任务都由同一个 `unit-local-mac-02` 领取，真实出现「聚星执行、星图排队、聚星结束后星图执行」的串行场景；
- 两平台账号、Chrome Profile、会话、registry、数据严格隔离；
- 任务中心、达人库、达人详情、执行单元页均正确展示两个平台；
- 星图 117 条历史任务及历史快照/JSONB/精选/更新资格内容一致；唯一变化是授权星图任务对 1 位既有达人的正常更新；
- 聚星数据只写入主库 1 位真实达人，未导入 4193 的 8 条任务/39 位达人；
- 关闭聚星 Flag 的运行时行为已用临时 API 验证：新入口/新任务被拒绝，既有聚星任务/达人仍可读，不删除数据；
- 主站用正常启动脚本重启后仍自动启用双平台，不依赖临时测试脚本。

边界：30/200 位目标未验证，第 3 页起仍未开放；无 Windows 验收；无真实聚星子账号选择/平台安全验证场景（本次会话 VALID，未触发）。

## 2. 主站整合前后架构与配置

| 项 | 整合前 | 整合后 |
|---|---|---|
| 平台入口 | 仅巨量星图 | 巨量星图 + 磁力聚星 |
| Feature Flag | 无/关闭 | `XINGTU_ENABLE_KUAISHOU_JUXING=1` |
| 目标上限 | — | `XINGTU_KUAISHOU_JUXING_MAX_TARGET_COUNT=30`（长期目标 200，未验收） |
| 执行单元 | `unit-local-mac-02` 仅星图绑定 | 同一单元双绑定：星图 + `60821564` 聚星 |
| 数据库 | `xingtu_development`（迁移 20） | 同库；新增 1 聚星任务/1 达人，未导入 4193 |
| 任务中心 | 星图 only | 双平台混排 + 平台筛选 |
| 达人库 | 星图 only | 双平台切换 + 平台化详情 |
| 4193 | 运行中 | 停止（数据/配置/Profile/证据保留） |
| update-scheduler | 未运行 | 未运行（语义不变） |

数据流：5173 UI → FastAPI 8000 → AI Intake（DeepSeek）→ Temporal 57233 → Collection Worker（`unit-local-mac-02`）→ `config.for_platform()` 选择账号/Profile/registry → Adapter → Engine → PostgreSQL → 任务中心/达人库/详情。

## 3. Git 与运行环境基线

- 分支 `快手_1026`，HEAD `1cfbb6d`；未切分支、未 reset/clean、未 commit/push/merge。
- 工作区：40 个已跟踪文件有未提交修改、47 个未跟踪文件、0 staged。本轮新增/修改见第 14 节。
- 主站：前端 5173、API 8000、PG 55432 `xingtu_development`、Temporal 57233、Redis 56379 DB0。
- 4193：API 4192/Vite 4193/Temporal 57235 已停止；测试 PG 55439 保留；8 条任务（5 聚星/3 星图）、39 位聚星达人。
- Chrome 156.0.8078.76；`@playwright/mcp@0.0.77`；macOS 本机。

## 4. 数据库迁移、备份与恢复

- **未执行任何新迁移**；`schema_migrations` 最大版本 20（020 已由 OPS-04 应用）。
- 切换前新备份（0600）：`.runtime/backups/juxing-main-20261031T021309/xingtu_development-pre-juxing-main.dump`，35,539,606 bytes，TOC 231，sha256 `055a98ba41838d914a25912cf00f254ac1a48fd3a0894d4afcbc046e8576d521`。
- 配置/Profile 备份：`m3-app.env.pre-switch`、`local-dev-mac-02.json.pre-switch`、`juxing-profile-and-snapshot.tar.gz`。
- 恢复演练：测试集群临时库 `xingtu_test_restorecheck_*` → `pg_restore --no-owner --no-privileges` 成功 → 与 baseline 同口径 count+md5 **全部一致** → 临时库删除。
- 恢复演练曾发现跨库 timestamptz 时区导致的哈希假差异；工具固定 UTC 后复验通过，不是数据损坏。
- 本轮未执行整库恢复，未删除业务数据。

## 5. ExecutionUnit 双平台绑定

主库 `execution_unit_platform_bindings`：

| platform | account_ref | expected_account_id | profile_ref | registry_ref | enabled | 最近观测 |
|---|---|---|---|---|---|---|
| douyin_xingtu | xingtu-account-02 | ID: 1807978499337419 | `.runtime/profiles/unit-local-mac-02`（旧绝对路径展示值） | douyin_xingtu.verified.json | true | VALID 02:27:26 |
| kuaishou_juxing | juxing-account-02 | 60821564 | `.runtime/profiles/unit-local-mac-02-juxing` | kuaishou_juxing.verified.json | true | VALID 02:26:05 |

- 由 Collection Worker 启动时按现有幂等机制注册，未手写 SQL、未修改星图绑定行。
- 单元 `unit-local-mac-02`：READY、无 owner/lease/current_task、browser_stopped=true；worker generation 13→14（两次正常重启）。
- 星图 binding 的 `profile_ref` 仍为旧仓库绝对路径，运行时以单元配置为准；本轮不改不可变字段。

## 6. Profile、账号与会话隔离

- 星图 Profile `.runtime/profiles/unit-local-mac-02`；聚星 Profile `.runtime/profiles/unit-local-mac-02-juxing`；两个目录不同、均 0700，任务结束后项目锁均 FREE。
- 聚星会话只读探测（切换后、真实任务前）：`VALID`、`PROTECTED_PAGE_AND_URL_ACCOUNT_VERIFIED`、`observed_account_id=60821564`、`account_match=true`。
- 真实任务时 Chrome 进程只出现一个 Profile：聚星执行阶段为 `unit-local-mac-02-juxing`，星图执行阶段为 `unit-local-mac-02`；没有同时打开两个 Profile。
- 聚星任务结束时只刷新聚星 binding 的最近观测（02:26:05）；星图 binding 未被聚星任务改写，随后星图任务才刷新为 02:27:26。登录失效/账号状态按平台隔离。
- 未触发子账号选择页；未自动选择任何子账号，未绕过账号校验。

## 7. 5173 平台启用结果

- `GET /api/platforms`：`douyin_xingtu enabled=true`（`xingtu-ad-creator-featured-v13`）、`kuaishou_juxing enabled=true`（`juxing-video-creator-stage-c-v3`）。
- `GET /api/platforms/kuaishou_juxing/capabilities`：200，能力 `juxing-video-square-stage-c-v2`，7 项条件，`target_count_max=30`。
- `GET /api/execution-units`：`unit-local-mac-02` platforms=`[douyin_xingtu,kuaishou_juxing]`，READY，worker ONLINE。
- Temporal：`xingtu-intake` 与 `xingtu-unit-local-mac-02` 均有新鲜消费者。
- 前端：平台选择两项均 `disabled=false`、显示「已验证可用」；任务中心/达人库/执行单元页均可见双平台。
- 主站重启后（API 98149/intake 98173/collection 98190/frontend 98200，generation 14）再次验证双平台启用、绑定仍存在、任务/达人计数不变。
- 最终入口 `http://localhost:5173`：前端 200、真实登录 200、`/api/platforms` 双平台 enabled；不依赖 4193 或临时脚本。

## 8. 统一任务中心

- 任务中心真实显示两个新任务：`宠物 #c30b7622 · 巨量星图`（已完成 1/1，20 发现，1 资料，1 精选）与 `母婴 #b9517e8b · 磁力聚星`（已完成 1/1，20 发现，1 资料，无精选）。
- 平台筛选「全部平台 / 巨量星图 / 磁力聚星」选项正确；聚星筛选只返回 1 条聚星任务，星图筛选只返回星图任务；切换不修改数据。
- 历史星图任务（如 `#6dff3c73`）仍可查，状态/计数为 `PARTIAL_COMPLETED 4/4`，与基线一致。
- 聚星任务详情不显示 F06/精选；星图任务详情保留精选计数（1）。
- 平台筛选 API：`/api/tasks?platform=`，cursor scope 纳入 platform；新增测试覆盖。

截图：[任务中心](assets/juxing-main/07-task-center.png)、[聚星筛选](assets/juxing-main/08-task-filter-juxing.png)、[星图筛选](assets/juxing-main/09-task-filter-xingtu.png)。

## 9. 统一达人库与详情

- 聚星达人库：`1 位已加载`，显示真实聚星达人；指标按聚星原始口径（粉丝 171,296、月涨粉率 -0.12%、互动/完播 1.42%/7.76%、播放中位数 163）。
- 聚星详情：`基础资料 / 传播表现 / 代表作品 / 受众画像` 四章节；`快手ID 1344496241`；近 30 天涨粉显示「平台暂无数据」而非 0；报价保留原值与单位；无星图专属指标。
- 星图达人库：既有 138 位保留；详情保留 `商业能力 / 创作能力 / 履约能力 / 连接用户 / 报价与历史`，F06 两组精选（优秀传播视频/优秀种草视频）正常。
- 跨平台身份不合并；聚星 creator 在主库星图 current/index 中行数均为 0。

实现截图：聚星达人库、聚星详情、星图详情保留在私有 `.runtime/juxing-main/mcp/11-juxing-library.png`、`14-juxing-creator-detail.png`、`15-xingtu-creator-detail.png`（含达人正文，未入 Git）；脱敏的任务中心/平台选择/筛选/单元页截图见 `docs/evidence/assets/juxing-main/`。

## 10. 聚星真实单达人结果

| 项 | 值 |
|---|---|
| 任务 ID | `b9517e8b-a342-484f-980d-39137f95ff25` |
| 平台/条件 | `kuaishou_juxing`；关键词 母婴、内容类型 母婴亲子、目标 1 |
| requirement | `requirement_form.v3`，platform=kuaishou_juxing |
| 提交方式 | 5173 真实前端，Playwright MCP + Chrome |
| 创建/完成 | 02:25:32 / 02:26:05 |
| 终态 | **COMPLETED**，valid 1、profile_complete 1、featured 0、failure None |
| 执行单元 | `unit-local-mac-02` |
| 账号/Profile | 60821564 / `unit-local-mac-02-juxing`；binding 观测 VALID |
| 达人 | creator `fce791f2-b8bc-4adb-b672-0122eefe68ca`，platform_creator_id `1344496241` |
| 快照 | `c312e607-d9a9-44be-aeb5-956ff1ed487b`；basic/spread/works/audience 均 COLLECTED、complete；pipeline_complete=true |
| 投影 | 4 模块、34 个 `module.field`；无星图 current/index 行 |
| 任务关联 | `task_creators` 1 条有效；`task_dispatches` sent=true、workflow 已启动 |

## 11. 星图真实回归结果

| 项 | 值 |
|---|---|
| 任务 ID | `c30b7622-a054-4a0d-9969-e150512e4479` |
| 平台/条件 | `douyin_xingtu`；关键词 宠物、目标 1 |
| requirement | `requirement_form.v2`，platform=douyin_xingtu |
| 提交方式 | 5173 真实前端，Playwright MCP + Chrome |
| 创建/完成 | 02:25:37 / 02:27:26 |
| 终态 | **COMPLETED**，valid 1、profile_complete 1、featured 1、failure None |
| 执行单元 | `unit-local-mac-02` |
| 账号/Profile | ID: 1807978499337419 / `unit-local-mac-02`；binding 观测 VALID |
| 达人 | creator `6300acc0-7505-43a7-a4f7-3a362741b922`（既有达人） |
| 快照 | `1ecd6c6c-7cd8-4899-93f4-5ac9e04ffe1b`（02:27:26） |
| F06 | `excellent_reach`/`excellent_seeding` 两集合 COMPLETE，8 张卡片 |
| 更新资格 | `creator_update_schedule` 仍 90 行；该达人 next_due/tier 保留；调度器仍未运行 |

星图 F04/F05/F06、完成判定和更新语义未改动。

## 12. 历史业务数据完整性

基线：切换前 117 星图任务、138 达人、293 task_creators、355 快照、90 更新资格；count+md5 存于 `.runtime/juxing-main/baseline.json`（UTC 固定会话）。

compare 结果（`.runtime/juxing-main/db-acceptance.json`）：

| 范围 | 变化 | 归因 |
|---|---|---|
| root_tasks / task_creators / creator_snapshots（按基线 root ID） | **无变化** | 历史任务/快照未被修改 |
| requirements / filter_plans / task_checkpoints / task_dispatches / featured_collections / featured_cards / media_objects / raw_evidence | **无变化** | 历史数据完整 |
| creator_update_schedule | **无变化（90）** | 更新资格未被改动 |
| platform_creators | 138，md5 变化 | 授权星图任务更新既有达人 `6300acc0` 的投影 |
| douyin_xingtu_creator_current | 138，md5 变化 | 同一达人 latest_snapshot 指向新快照 |
| douyin_xingtu_creator_snapshot_index | 335→336 | 仅新增该达人 1 条快照索引 |
| douyin_xingtu_creator_quote_observations | 1717→1720（+3） | 仅新快照的报价观测 |
| douyin_xingtu_creator_video_observations | 8731→8761（+30） | 仅新快照的作品观测 |

归因证据：基线之后只新增 2 个快照（分别属于两个授权任务）；只有 1 条 `douyin_xingtu_creator_current` 指向基线后的快照（`6300acc0`）；新增索引/报价/作品行全部引用该快照；只有 2 个 root task 在基线后创建；juxing creator 在星图 current/index 中为 0。因此上述差异均为**本轮授权的星图真实任务对既有达人的正常更新**，不是删除、覆盖或越权修改。

## 13. 共享执行单元、串行与隔离证据

- 两个任务 `root_tasks.unit_id` 均为 `unit-local-mac-02`。
- 15 轮轮询中每轮最多一个平台处于执行态。
- 真实重叠：02:25:38—02:26:03 聚星 `COLLECTING`、星图 `QUEUED`，单元 current=`b9517e8b`；02:26:11 聚星 `COMPLETED`、单元 current 切到 `c30b7622`；02:26:19 起星图 `COLLECTING`；02:27:33 两任务均 COMPLETED、单元 current=None。
- 结束时单元 READY、无 owner/lease/current_task、browser_stopped=true；无 OPEN 验证/ACTIVE 接管。
- Chrome 只在聚星阶段出现 `unit-local-mac-02-juxing`，在星图阶段出现 `unit-local-mac-02`；任务结束后两个 Profile 锁 FREE。
- 聚星/星图 binding 最近观测分别在其任务结束时刷新，未互相覆盖。
- 由于真实重叠已出现，**未额外发起隔离并发测试**，也未额外发起真实采集。

## 14. 自动化测试与 Playwright MCP + Chrome 证据

### 14.1 自动测试（切换后复跑）

| 层 | 结果 |
|---|---|
| 后端单元 + 合同 | **409 passed** |
| 隔离集成（全新 `xingtu_test_juxing_main`） | **121 passed / 1 skipped**（S3 未配置） |
| E2E | **14 passed** |
| 前端 | **105 passed** + lint + build |
| Mypy | backend/src 38 files 通过 |
| 全仓 Ruff | 38 个既有错误（`scripts/acceptance` UP031、`scripts/qa/kjx_full_mcp.py` E501/F841），与本轮无关 |

### 14.2 Playwright MCP + Chrome

- `@playwright/mcp@0.0.77`，系统 Chrome，stdio MCP；真实登录 5173，真实表单提交与页面读取，不是 Playwright Python 页面自动化。
- 验收报告：`.runtime/juxing-main/mcp/report.json`（20 cases，0 failed）；setup `mcp-setup/report.json`（5/5）；重启后 `mcp-post-restart/report.json`（5/5）。
- 关键用例：登录、平台筛选、两平台表单、两任务 1/1/1、同单元串行、任务中心混排/筛选、聚星详情无精选、达人库/详情、星图 F06、执行单元双平台。
- 截图：`docs/evidence/assets/juxing-main/`（任务中心、平台选择、两平台筛选、执行单元）；含达人的聚星/星图详情截图保留在私有 `.runtime/juxing-main/mcp/`（0700），未提交。

### 14.3 Feature Flag 关闭运行时验证

临时 API（8001，Flag=0，同一主库/Redis 会话，不影响主站进程/Flag）：

- `/api/platforms` 聚星 `enabled=false`，原因「磁力聚星功能开关当前关闭」；
- 聚星 capabilities 422 `KUAISHOU_JUXING_FEATURE_DISABLED`；
- 创建聚星任务 422 `KUAISHOU_JUXING_FEATURE_DISABLED`，未创建任务（幂等键记录 0）；
- 既有聚星任务详情、任务列表筛选、达人库均 200 可读；数据未被删除/隐藏；
- Flag 只存在于 API 产品层，worker 不读取；已入队/执行中的任务不会被 Flag 停止，需取消或停 worker。

### 14.4 重启持久性

用正常 `.runtime/dev-no-upd.sh stop → up` 重启主站（API 98149/intake 98173/collection 98190/frontend 98200，generation 14），未启动 update-scheduler；`/api/platforms` 双平台仍 enabled，绑定仍存在，任务/达人计数不变；重启后 MCP setup 5/5 PASS。

## 15. 剩余风险、边界与授权事项

1. **30/200 未验收**：当前配置 30，长期目标 200；已验证第 2 页与真实 22/22/22，30 位以上/200 位仍需后续分页能力与实测，不得写成已支持。
2. **聚星更新/补采/精选/报价历史未开发**：界面已按平台隐藏/标记；不得让聚星执行星图专属功能。
3. **真实子账号选择/安全验证未触发**：本次会话 VALID、账号匹配；相关提醒/接管由现有代码与自动测试覆盖，真实场景 NOT_RUN。
4. **主库星图 binding 的旧 `profile_ref`**：历史遗留展示值，运行时以单元配置为准；未改不可变字段。
5. **`test_migrations_020.py` schema 限定缺陷**：测试层问题，已独立记录；全新空库通过。
6. **4193 处于停止状态**：数据/配置/Profile/证据保留，可 `./.runtime/kjx-full/stack.sh up` 恢复；本轮未再启动。
7. **未做 Windows**（DEPLOY-WIN-01）、未做 Git 提交。
8. 若需关闭聚星，Flag=0 + 重启 API；若要撤销绑定，单元配置 `enabled=false` + 重启 collection；不得删除已入库数据。Flag 不是在途任务 kill switch。

## 16. 修改文件与配置清单

代码/测试/脚本：

- `backend/src/xingtu/product_queries.py`：`list_tasks(platform=...)`、SQL 条件、cursor scope。
- `backend/src/xingtu/product_api.py`：`GET /api/tasks` platform 参数。
- `frontend/src/pages.tsx`：任务中心平台下拉。
- `backend/tests/unit/test_product_api.py`、`frontend/src/App.test.tsx`：平台筛选测试。
- `backend/tests/integration/test_task_platform_filter.py`、`test_juxing_main_baseline.py`、`backend/tests/unit/test_juxing_main_switch.py`。
- `scripts/juxing_main_switch.py`（baseline/preflight/compare/session-check）、`scripts/qa/juxing_main_mcp.py`（MCP 验收驱动）。

私有运行配置（未入 Git）：

- `.runtime/m3-app.env`：+3 个聚星键（0600）；备份 `.runtime/juxing-main/m3-app.env.pre-apply`。
- `.runtime/units/local-dev-mac-02.json`：+聚星 `platform_bindings`（0600）；备份 `.runtime/juxing-main/local-dev-mac-02.json.pre-apply`。
- 主库：新增聚星 binding 行、1 聚星任务/1 达人/快照、1 星图任务及其正常更新数据；无 Schema 变更。
- 备份：`.runtime/backups/juxing-main-20261031T021309/`；证据：`.runtime/juxing-main/`（0700）。

文档：`docs/tasks/JUXING-MAIN-01.md`、`docs/design/JUXING-MAIN-01-integration-plan.md`、`docs/evidence/JUXING-MAIN-01-test-cases.md`、`docs/evidence/JUXING-MAIN-01-pre-switch-checklist.md`、本文件、`docs/development.md`、任务索引与总览。

## 17. 当前 Git 工作区

- 分支 `快手_1026`，HEAD `1cfbb6d`，0 staged，40 已跟踪修改、48 未跟踪（含本卡新增文件与既有 KJX/OPS 成果）。
- 本轮未 commit/push/merge/reset/clean；未切分支。
- 需要提交时请另行授权，并按单一任务整理提交。

## 18. 最终判定

**GO（macOS 本机 5173 主站双平台整合范围）。** 2026-10-31 独立 QA 回归 69 用例 68 PASS/1 N/A/0 FAIL、MCP 37/37、自动回归通过，结论同为 GO，见 [独立 QA 回归](JUXING-MAIN-01-post-integration-regression.md)。

满足：真实双平台采集、同单元串行、账号/Profile/数据隔离、统一任务中心/达人库/详情、星图历史与 F04/F05/F06/更新资格不受影响、历史数据内容一致（仅授权星图任务正常更新 1 位既有达人）、Flag 关闭行为、正常重启后双平台可复现、4193 保留。

条件/边界：30/200 与第 3 页+ 未验收；聚星更新/补采/精选/报价历史未开发；真实子账号选择/安全验证未触发；Windows 未验收。
