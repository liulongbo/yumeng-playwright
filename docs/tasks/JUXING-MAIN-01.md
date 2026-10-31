# JUXING-MAIN-01：5173 主站双平台整合与真实验收

状态：**已完成（GO，macOS 本机 5173 主站双平台整合范围）；独立 QA 回归 GO**  
建立时间：2026-10-31T02:00:00+08:00  
最近更新：2026-10-31T02:36:00+08:00  
是否验收：**是**。两平台各 1 位真实采集完成，同单元串行/隔离/任务中心/达人库/历史一致性/Flag 回退/重启持久性均有证据；2026-10-31 独立 QA 回归 69 用例 68 PASS/1 N/A、0 FAIL。  
验收证据：[JUXING-MAIN-01 验收](JUXING-MAIN-01-acceptance.md)  
切换前清单：[JUXING-MAIN-01 切换前检查清单](JUXING-MAIN-01-pre-switch-checklist.md)

## 目标与范围

在**不重开**巨量星图/磁力聚星采集器、不做无必要架构重构的前提下，把已经验证的磁力聚星能力接入现有 5173 主站，使用户在同一个网站同时使用两个平台，并共享现有任务中心、业务数据库 `xingtu_development`、达人库和同一个 `unit-local-mac-02` 执行单元。两平台保留各自账号、Chrome Profile、会话、Adapter、合同和平台字段；同一单元同一时刻只执行一个任务。

范围：主站启用聚星所需的最小配置、执行单元平台绑定、Profile/会话核对、任务中心平台筛选（唯一产品代码改动）、主库/4193 数据边界、备份/恢复演练、主站真实双平台采集、统一任务中心/达人库/详情、星图历史与 F04/F05/F06 回归、Flag 回退与重启持久性。

不在范围：新迁移、4193 数据导入、聚星更新/补采/精选/报价历史、第 3 页+、200 位容量、星图 F04/F05/F06/完成判定/更新语义改动、Windows（[DEPLOY-WIN-01](DEPLOY-WIN-01.md)）、Git 提交/推送/合并。

## 关联与依赖

- 前置：[KJX-01](KJX-01.md)（聚星能力/阶段 C/D-0）、[OPS-04](OPS-04.md)（主库迁移 020）、[OPS-05](OPS-05.md)（4193 隔离栈）。
- 方案：[JUXING-MAIN-01 整合方案](../design/JUXING-MAIN-01-integration-plan.md)。
- 依据：[完整技术方案 §19](../AI达人智能发现与采集系统-完整技术方案.md)、[开发运行说明](../development.md)。
- 用户决定（2026-10-31）：长期目标上限 200；当前主站配置 30；不得把 30/200 写成已验证；P4–P5 期间停止 4193 整栈并保留；授权 1 位真实聚星 + 1 位真实星图。

## 验收清单

### P1–P3：代码、隔离测试、主站只读预检

- [x] 任务中心平台筛选：`/api/tasks?platform=` + `ProductQueries.list_tasks(platform=...)` + cursor scope。
- [x] 前端任务中心「全部平台/巨量星图/磁力聚星」下拉。
- [x] 新增 API/集成/前端/切换工具测试。
- [x] 后端单元+合同 409 passed；集成 121/1 skip；E2E 14；前端 105 + lint + build；Mypy 通过。
- [x] 主站预检 48 项 0 失败；候选配置只加聚星绑定、账号 60821564、Profile/快照/锁、registry live、无绑定冲突。
- [x] 内容基线（117 任务/138 达人/293 关联/355 快照/90 更新资格）+ UTC count/md5。
- [x] 主库新备份 + 隔离恢复演练内容一致；临时库删除。
- [x] 4193 实测修正为 8 条任务（5 聚星/3 星图）/39 位聚星达人，不导入主库。
- [x] 独立记录 `test_migrations_020.py` schema 限定缺陷。

### P4：主站切换

- [x] 再次确认主库无在途、无租约、无接管，备份/恢复证据有效。
- [x] 停止 4193 整栈（02:22:00—04），数据/配置/Profile/证据保留（文件 sha 未变、测试库 8 任务/39 达人）。
- [x] 备份并更新 `.runtime/m3-app.env`：Flag=1、聚星 registry、max=30。
- [x] 备份并更新单元配置：只增加聚星 `platform_bindings`，星图字段不变。
- [x] 主站安全重启（02:22:16—02:23:15），`update-scheduler` 保持关闭。
- [x] Collection Worker 幂等注册聚星 binding（`unit-local-mac-02` × 60821564）。
- [x] `/api/platforms` 双平台 enabled、聚星能力 max=30、执行单元双平台、Temporal 两队列新鲜消费者。

### P5：真实主站验收

- [x] 聚星会话只读探测：VALID、60821564 匹配、受保护页验证；无需人工登录/选择子账号。
- [x] 5173 真实聚星任务：母婴/母婴亲子/target=1，`b9517e8b-a342-484f-980d-39137f95ff25`，**COMPLETED 1/1/1**。
- [x] 5173 真实星图任务：宠物/target=1，`c30b7622-a054-4a0d-9969-e150512e4479`，**COMPLETED 1/1/1**，F06 双集合完成。
- [x] 同单元串行：聚星执行时星图 QUEUED；聚星完成后单元 current 切到星图；每轮最多一个执行态。
- [x] 租约释放：结束 READY、无 owner/lease/current_task、browser STOPPED。
- [x] Profile/账号隔离：聚星/星图各自 Profile 与 binding 观测，任务结束后锁均 FREE。
- [x] 任务中心双平台混排 + 平台筛选；聚星无精选，星图保留精选。
- [x] 达人库/详情双平台正确；聚星缺失显示无数据；星图 F06/详情保留。
- [x] 数据只写平台身份；聚星 creator 在星图 current/index 为 0；未导入 4193。

### P6：全量回归与收尾

- [x] 切换后自动回归：409 unit+contract、121/1 skip 集成、14 E2E、105 前端 + lint + build、Mypy 通过。
- [x] MCP 验收 20/20 + setup 5/5 + 重启后 5/5；真实 UI 证据。
- [x] 历史一致性：历史任务/快照/需求/检查点/任务关联/精选/更新资格无变化；唯一变化归因于授权星图任务更新 1 位既有达人。
- [x] Flag=0 运行时验证：新入口/新任务拒绝，既有任务/达人可读，不删数据；Flag 不是 worker kill switch。
- [x] 正常重启后双平台仍启用、绑定存在、计数不变（generation 14）。
- [x] 4193 未启动，数据库/配置/证据保留。
- [x] 文档更新：验收证据、测试用例、development、任务索引/总览。
- [x] 独立 QA 回归：69 用例（68 PASS/1 N/A/0 FAIL）；MCP 37/37；自动测试 409/121+1/14/105；见 [post-integration regression](JUXING-MAIN-01-post-integration-regression.md)。

## 实现记录

- 2026-10-31T02:00：方案获批准，P1–P3 授权；P4–P6 暂不授权。
- 2026-10-31T02:05：任务中心平台筛选（query/API/前端）实现；cursor scope 纳入 platform。
- 2026-10-31T02:08：新增平台筛选/基线/切换工具测试。
- 2026-10-31T02:10：新增 `scripts/juxing_main_switch.py`；固定 UTC 避免跨库 timestamptz 假差异。
- 2026-10-31T02:12：主站只读预检 48 项全部通过。
- 2026-10-31T02:13：主库新备份 + 配置/Profile 备份；恢复演练通过。
- 2026-10-31T02:14：后端单元+合同 409；前端 105 + lint/build；Mypy 通过。
- 2026-10-31T02:16：隔离集成 121/1 skip；E2E 14；共享库测试缺陷独立记录。
- 2026-10-31T02:18：P1–P3 完成，提交切换前检查清单（授权门 B）。
- 2026-10-31T02:21：用户批准授权门 B。
- 2026-10-31T02:22：再次预检，停止 4193，应用主站 env/单元配置；02:22:16—02:23:15 安全重启主站；聚星 binding 注册；generation 13。
- 2026-10-31T02:23：聚星会话探测 VALID（60821564）。
- 2026-10-31T02:25：MCP 从 5173 提交聚星 `b9517e8b` 与星图 `c30b7622`；真实出现聚星执行、星图排队。
- 2026-10-31T02:26：聚星 COMPLETED 1/1/1；02:27 星图 COMPLETED 1/1/1。
- 2026-10-31T02:27：MCP 任务中心/筛选/详情/达人库/执行单元证据；20/20 PASS。
- 2026-10-31T02:29：历史内容 compare，5 处差异全部归因于授权星图任务对既有达人的正常更新。
- 2026-10-31T02:30：临时 Flag=0 API 验证回退行为；未创建任务、数据可读。
- 2026-10-31T02:31—02:32：正常重启主站，双平台仍启用，generation 14。
- 2026-10-31T02:33：切换后全量自动回归与重启后 MCP setup 5/5。
- 2026-10-31T02:35：验收证据、测试用例、development、索引/总览更新；GO。

## 验证证据

- 验收：[JUXING-MAIN-01 验收](JUXING-MAIN-01-acceptance.md)。
- 独立 QA 回归：[JUXING-MAIN-01 post-integration regression](JUXING-MAIN-01-post-integration-regression.md)。
- 测试用例：[JUXING-MAIN-01 测试用例](JUXING-MAIN-01-test-cases.md)。
- 切换前清单：[JUXING-MAIN-01 切换前清单](JUXING-MAIN-01-pre-switch-checklist.md)。
- 方案：[JUXING-MAIN-01 整合方案](../design/JUXING-MAIN-01-integration-plan.md)。
- 私有证据：`.runtime/juxing-main/`（0700）——preflight、baseline、compare、restore、session probe、MCP 报告/截图、DB 验收、验收汇总。
- 备份：`.runtime/backups/juxing-main-20261031T021309/`。
- 公开脱敏截图：`docs/evidence/assets/juxing-main/`。

## 已知问题与边界

1. **30/200 未验收**：当前配置 30，长期 200；已验证 22/22/22 与第 2 页，30 位以上/200 位仍需后续分页与实测。
2. **聚星更新/补采/精选/报价历史未开发**：UI 已按平台隐藏/标记；不得让聚星执行星图专属功能。
3. **真实子账号选择/安全验证未触发**：本次会话 VALID；提醒/接管由现有代码与自动测试覆盖，真实场景 NOT_RUN。
4. **主库星图 binding 的旧 `profile_ref`**：历史遗留展示值，运行时以单元配置为准；本轮未改不可变字段。
5. **`test_migrations_020.py` schema 限定缺陷**：测试层问题，独立记录；全新空库通过。
6. **4193 处于停止状态**：数据/配置/Profile/证据保留，可 `./.runtime/kjx-full/stack.sh up` 恢复。
7. **未做 Windows**；本轮未做 Git 提交，代码已由 [JUXING-DELIVERY-01](JUXING-DELIVERY-01.md) 提交（`5795889`/`f992021`/`ab39b28`）并合并到 `main`（`24e3606`）。
8. **2026-10-31 实测：长星图任务后的排队聚星任务 activity 启动延迟**。星图 `d34a665f` 于 03:03:46 完成并释放单元；聚星 `210b37c4` 的 activity 在 02:56:04 已调度，但 03:09:44 才启动（约 5m58s 额外等待），03:11:01 完成 3/3/3。Temporal history 显示不是租约占用；属 Worker activity 调度/轮询停顿，非阻塞但待定位修复。详见 [独立 QA 回归 §10](JUXING-MAIN-01-post-integration-regression.md)。

## 交接信息

5173 主站现在默认双平台：启动入口为 `./dev.sh up` 或 `./.runtime/dev-no-upd.sh up`（本机当前使用后者，跳过自动更新调度器）。聚星配置在 `.runtime/m3-app.env`（Flag=1、registry、max=30）与 `.runtime/units/local-dev-mac-02.json`（聚星 binding）。主站单元 `unit-local-mac-02` 同时绑定星图/聚星；`update-scheduler` 保持关闭。4193 已停止，数据/脚本/证据保留。关闭聚星：Flag=0 + 重启 API；撤销绑定：单元配置 `enabled=false` + 重启 collection；Flag 不会停止已入队任务，也不会删除数据。

## 状态历史

- 2026-10-31T02:00：建立 → 进行中；P1–P3 授权。
- 2026-10-31T02:18：P1–P3 完成；等待授权门 B。
- 2026-10-31T02:21：授权门 B 批准，P4–P6 授权。
- 2026-10-31T02:35：P4–P6 完成；真实双平台 1/1/1、同单元串行、历史一致、Flag 回退、重启持久性通过；**GO**。
- 2026-10-31T02:55：独立 QA 回归完成；69 用例 68 PASS/1 N/A/0 FAIL，MCP 37/37，自动回归通过；**GO（质量回归）**。
- 2026-10-31T03:11：实测发现长任务后 activity 启动约 6 分钟延迟（非阻塞）；已记录为已知问题，待定位/修复。
- 2026-10-31T14:31：代码由 [JUXING-DELIVERY-01](JUXING-DELIVERY-01.md) 交付：审查 GO（修复 2 P1/3 前端 P2）、回归 411/121+1/14/106 通过，提交并合并到 GitHub `main`（`24e3606`）。
