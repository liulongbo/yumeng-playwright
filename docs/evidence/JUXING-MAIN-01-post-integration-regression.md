# JUXING-MAIN-01 整合后独立 QA 回归报告

状态：**已完成**  
执行时间：2026-10-31 02:42—02:55（Asia/Shanghai）  
测试对象：`http://localhost:5173` 双平台主站（巨量星图 + 磁力聚星）  
关联：[任务卡](../tasks/JUXING-MAIN-01.md)、[验收证据](JUXING-MAIN-01-acceptance.md)、[测试用例](JUXING-MAIN-01-test-cases.md)、[开发运行说明](../development.md)。

## 1. 执行摘要

- **测试已完成**：69 条 QA 用例全部评估，68 PASS、1 NOT_APPLICABLE、0 FAIL、0 BLOCKED、0 NOT_RUN。
- **未发现阻塞性产品 Bug**。双平台主站可正常登录、选择平台、创建/查看任务、按平台筛选、查看两平台达人库与详情、查看共享执行单元。
- **发现并修复 2 个测试脚本断言问题**（非产品 Bug）：平台切换后表单重置的预期写反；console 错误统计把汇总行误计为错误。
- **发现 3 个非阻塞 UX 观察项**：任务中心筛选未 URL 持久化、指标条按当前页统计、执行单元“最近心跳”是单元/浏览器心跳而非 Worker 心跳。均未扩大开发范围。
- **数据/历史一致性通过**：与切换前基线相比，历史任务/快照/需求/检查点/精选/更新资格无变化；5 处差异全部归因于 P5 授权的星图任务更新 1 位既有达人。
- **自动化回归通过**：unit+contract 409、integration 121/1 skip、E2E 14、前端 105、Mypy 38 files、lint/build 通过。
- **真实采集说明**：本轮未新增真实平台任务；真实业务可用性判断部分依赖 P5 已验收的聚星 `b9517e8b` 与星图 `c30b7622`（均 COMPLETED 1/1/1）。

## 2. 测试范围

| 维度 | 覆盖 |
|---|---|
| UI 冒烟 | 登录/失败登录、四页导航、刷新、控制台、API 网络 |
| 双平台功能 | 平台选择、星图/聚星表单、字段隔离、目标上限、空表单校验、合同版本 |
| 任务中心 | 混排、平台筛选、状态/类型/日期组合、分页/cursor、刷新行为、历史任务 |
| 任务详情 | 聚星/星图真实任务、历史任务、失败任务 |
| 达人库/详情 | 两平台列表、切换、筛选/空态、聚星四章节、星图 F06、任务内一致性、跨平台同名 |
| 执行单元 | 同一单元双平台、ONLINE/READY、租约、Profile/账号隔离、串行证据、数据隔离 |
| 数据库 | 历史基线 compare、授权变化归因、聚星数据、身份隔离、更新资格 |
| 自动化 | unit/contract、integration、E2E、前端、Mypy、lint/build |
| 未授权/未执行 | 新增真实采集、停止/重启主站、主站 Flag 变更、4193 启停、Windows |

## 3. 测试用例统计

用例总数：**69**（`QAR-*`，见 [测试用例 §9](JUXING-MAIN-01-test-cases.md)）。

| 模块 | 用例数 | PASS | FAIL | BLOCKED | NOT_RUN | N/A |
|---|---:|---:|---:|---:|---:|---:|
| 环境与基线 | 6 | 6 | 0 | 0 | 0 | 0 |
| 登录/导航/UX | 8 | 7 | 0 | 0 | 0 | 1 |
| 平台选择/表单 | 8 | 8 | 0 | 0 | 0 | 0 |
| 统一任务中心 | 12 | 12 | 0 | 0 | 0 | 0 |
| 任务详情 | 4 | 4 | 0 | 0 | 0 | 0 |
| 达人库/详情 | 9 | 9 | 0 | 0 | 0 | 0 |
| 共享执行单元 | 6 | 6 | 0 | 0 | 0 | 0 |
| 异常/接管 | 3 | 3 | 0 | 0 | 0 | 0 |
| Flag/配置/恢复 | 4 | 4 | 0 | 0 | 0 | 0 |
| 数据/历史 | 5 | 5 | 0 | 0 | 0 | 0 |
| 自动化 | 4 | 4 | 0 | 0 | 0 | 0 |
| **合计** | **69** | **68** | **0** | **0** | **0** | **1** |

执行覆盖率：69/69 已评估（100%）。其中 1 条 N/A（无停用账号，未创建账号）。  
说明：异常/接管 3 条与 Flag/恢复 1 条使用自动测试/既有历史证据，未在真实平台触发选择页/验证；测试方式列已区分，不把自动测试冒充真实平台场景。

## 4. Bug 清单

### 4.1 产品 Bug

**无阻塞性产品 Bug。**

### 4.2 测试脚本问题（已修复，非产品缺陷）

| ID | 发现方式 | 复现/根因 | 修复 | 回归 |
|---|---|---|---|---|
| QA-HARNESS-01 | MCP 平台切换用例 | 脚本预期“切回聚星保留关键词”；实际产品在切换平台时重置表单，这是有意的跨平台隔离行为 | 调整断言为“切回后表单重置、不保留跨平台值”，并保留主用例 PLT-04 | 复跑 QA MCP 37/37 PASS |
| QA-HARNESS-02 | MCP console 统计 | 把 console 工具输出的汇总行（Total messages/Returning）计为错误；实际唯一错误是登录前 `/api/auth/me` 401 | 只统计 `[ERROR]/[WARNING]` 行并排除预期 401 | 复跑 console 相关错误 0 |

文件：`scripts/qa/juxing_main_qa.py`（仅验收工具）。

### 4.3 UX 观察（非阻塞，未修改）

| ID | 观察 | 影响 | 建议 |
|---|---|---|---|
| UX-OBS-01 | 任务中心平台/状态/日期筛选保存在组件 state，刷新页面后重置为「全部平台」 | 无数据丢失；筛选后刷新需重选 | 后续可把筛选写入 URL query |
| UX-OBS-02 | 指标条按当前页统计（如“需要关注 16/17”），不是全局总数 | 标签“当前列表”已提示，但易被误读为全局 | 后续可区分“当前页/全部筛选结果” |
| UX-OBS-03 | 执行单元“最近心跳”显示单元/浏览器心跳；空闲时可能早于 WORKER 心跳 | 不阻塞；可能让人误以为 Worker 不新鲜 | 后续可增加“Worker 最近心跳”列 |

这些均为既有界面行为，不是本次整合引入的阻塞问题。

## 5. Playwright MCP + Chrome 证据

- 工具：`@playwright/mcp@0.0.77` + 系统 Chrome 156，stdio MCP；真实登录与页面操作，不是 Playwright Python 页面自动化。
- 报告：`.runtime/qa-round/mcp/report.json`（37 cases，0 failed）；`.runtime/qa-round/mcp/console-errors.txt`；`.runtime/qa-round/mcp/network-api.txt`。
- 失败登录：`.runtime/qa-round/mcp-invalid-login/result.json`（停留 `/login`，提示“用户名或密码错误”；主站会话仍 200；限流键已清理）。

| 场景 | 证据 |
|---|---|
| 登录页/错误提示 | [qa-invalid-login](assets/juxing-main/qa-invalid-login.png) |
| 双平台选择/表单 | [qa-form-xingtu](assets/juxing-main/qa-form-xingtu.png)、[qa-form-juxing](assets/juxing-main/qa-form-juxing.png) |
| 任务中心双平台混排 | [qa-task-center](assets/juxing-main/qa-task-center.png) |
| 任务中心平台筛选 | [qa-task-filter-juxing](assets/juxing-main/qa-task-filter-juxing.png)、[qa-task-filter-xingtu](assets/juxing-main/qa-task-filter-xingtu.png) |
| 任务中心分页 | [qa-task-pagination](assets/juxing-main/qa-task-pagination.png) |
| 执行单元双平台 | [qa-units](assets/juxing-main/qa-units.png) |
| 聚星/星图任务详情、达人库/详情 | 私有 `.runtime/qa-round/mcp/qa-detail-*.png`、`qa-lib-*.png`（含达人正文，未入 Git） |

关键断言：

- 聚星真实任务 `b9517e8b`：已完成、平台磁力聚星、条件母婴/母婴亲子、有效入库 1/资料完整 1、无精选。
- 星图真实任务 `c30b7622`：已完成、平台巨量星图、宠物、1/1/1、精选保留。
- 历史任务 `6dff3c73`：部分完成、4 位有效，与历史一致；失败任务 `076edee2` 显示执行失败。
- 平台筛选：星图只显示星图、聚星只显示 1 条；第二页可加载；切换平台 cursor 重置；平台+状态/日期组合生效。
- 聚星库：1 位、山东筛选命中、北京市空态、详情四章节/快手ID/无更新与报价历史；星图库/详情 F06 保留。
- 执行单元：`unit-local-mac-02` 双平台、ONLINE、空闲、无当前任务。
- 控制台：登录后相关错误 0（唯一 401 是登录前 `/api/auth/me`）；API 请求无 5xx。

## 6. 自动化测试结果

| 命令/范围 | 结果 |
|---|---|
| `pytest backend/tests/unit backend/tests/contract -q` | **409 passed**（54.28s） |
| `pytest backend/tests/integration -q -rs`（全新 `xingtu_test_juxing_main`） | **121 passed / 1 skipped**（S3 未配置；222.31s） |
| `pytest tests/e2e -q` | **14 passed**（29.97s） |
| `npm --prefix frontend run lint` | 通过 |
| `npm --prefix frontend test -- --run` | **105 passed** |
| `npm --prefix frontend run build` | 构建通过 |
| `mypy backend/src` | **38 files**，无问题 |
| `ruff check backend conftest.py tests scripts` | **38 个既有错误**：`scripts/acceptance` 11×UP031、`scripts/qa/kjx_full_mcp.py` 27×E501/F841；本轮 QA 脚本无新增 |
| `git diff --check` | 通过 |

## 7. 数据与历史兼容性

- 主库：`schema_migrations` 20；星图 118 任务、聚星 1 任务；星图 138 达人、聚星 1 达人；`creator_update_schedule` 90；非终态 0。
- 执行单元：READY、无 owner/lease/current_task、browser_stopped=true；generation 14；两绑定 VALID；两 Profile 锁 FREE。
- 与切换前 baseline 的 compare：
  - 117 历史任务、历史快照、需求、检查点、任务关联、精选、证据/媒体、更新资格 **无变化**；
  - 5 处差异（platform_creators / xingtu current / snapshot_index +1 / quote +3 / video +30）全部归因于 P5 授权的星图任务更新既有达人 `6300acc0`；仅 1 条 current 指向基线后快照。
- 聚星 creator 在星图 current/index 中均为 0；主库聚星仅 1 位，未导入 4193 的 8 任务/39 达人。
- 4193：端口 4192/4193/57235 关闭，测试库 8 任务/39 聚星达人保留；主站未使用 4193。
- 本轮未新增任务、未删除/修改历史数据、未执行整库恢复。

## 8. 未完成及风险

1. **本轮未新增真实采集**：真实执行维度依赖 P5 的聚星/星图各 1 位任务；本轮只对既有真实结果与当前 UI/DB 做回归。
2. **异常场景未真实触发**：聚星子账号选择页、ACCOUNT_MISMATCH、平台安全验证在本轮未出现；相关提醒/接管由自动测试与历史证据覆盖，标记为自动/只读，不冒充真实触发。
3. **未重启主站/未改主站 Flag**：本轮无重启与主站 Flag 变更授权；Flag=0 用临时 API 8001 验证，重启持久性引用 P6 证据。
4. **容量边界**：30/200 位、第 3 页+ 未验证；聚星更新/补采/精选/报价历史未开发。
5. **已知遗留**：主库星图 binding 旧 `profile_ref` 展示值；`test_migrations_020.py` schema 限定缺陷；全仓 Ruff 既有错误。
6. **4193** 保持停止，按需可恢复；Windows 仍由 DEPLOY-WIN-01 承担。
7. 本轮未 commit/push/merge；工作区 40 已跟踪修改、49 未跟踪、0 staged。
8. **2026-10-31 追加实测发现：长任务后的 Worker activity 启动延迟**，详见 §10；非阻塞，待定位/修复。

## 9. 最终结论

**GO（整合后独立 QA 回归范围）**。

从真实媒介用户角度：

**当前 `http://localhost:5173` 可以正常、清晰、可靠地使用巨量星图与磁力聚星两个平台。** 两平台入口、筛选表单、任务中心、平台筛选、任务详情、达人库/详情、执行单元页面均可用；两平台数据、账号、Profile 隔离；历史星图数据未被破坏；P5 的两条真实任务均为 COMPLETED 1/1/1。

说明：本轮未新增真实采集，真实业务可用性的执行维度部分依赖 P5 验收证据；本轮未真实触发子账号选择/安全验证。以上为已知边界，不是阻塞缺陷。


## 10. 2026-10-31 追加实测：长任务后的 activity 启动延迟

用户实测任务对：

| 时间（+08） | 事件 |
|---|---|
| 02:55:33 | 星图任务 `d34a665f-2f47-465e-88d4-71d9b8bb0e15` 创建 |
| 02:55:36 | 星图 activity 启动 |
| 02:56:02 | 聚星任务 `210b37c4-6107-4c63-8047-c80d6f631b73` 创建（排队） |
| 02:56:04 | 聚星 workflow 启动，activity 已调度 |
| 03:03:46 | 星图 activity/workflow 完成并释放单元（任务 `PARTIAL_COMPLETED`，4/4 有效、资料完整 0） |
| **03:09:44** | **聚星 activity 才实际启动（比星图释放晚 5m58s）** |
| 03:11:01 | 聚星任务完成（3/3/3） |

结论：

- 聚星在星图执行期间排队属于**单执行单元串行**的预期行为；星图本次运行约 8m10s。
- 星图完成后，聚星 activity **没有**在正常的秒级/30 秒内启动，额外等待约 6 分钟。Temporal history 证明聚星 activity 在 02:56:04 已调度、03:09:44 才启动；星图 activity 03:03:46 已结束。期间没有更新任务、验证事件或接管，当前单元 READY，因此**不是执行单元租约未释放**。
- 对照 P5：聚星 activity 结束后，星图 activity 在 **7ms** 内启动；正常串行交接是即时的。本次 5m58s 属异常。
- 最可能原因：单 Worker 的 `max_concurrent_activities=1` 在长任务后 activity 槽位/轮询未及时恢复（Temporal matching 日志显示 03:09:44 才出现 activity 队列 poll），或 Worker 事件循环被同步 DB/清理工作阻塞。**不是数据/租约问题，但不能排除 Worker/SDK 调度缺陷。**
- 不需要手动“释放执行单元”；当时租约已释放，手动释放不会解决且可能破坏租约安全。若复现，先查 `execution_units`（READY/无 owner）与 `temporal workflow describe`；仅在无在途任务且经授权时重启 collection worker 作为临时恢复。
- 建议后续最小任务：增加 activity scheduled→started 时延日志/告警（READY 时 >60s）；隔离环境复现长任务后双任务切换；将 dispatch 的同步 DB 轮询移出 Temporal worker 事件循环或拆分独立进程；补回归测试。不改变采集语义。
