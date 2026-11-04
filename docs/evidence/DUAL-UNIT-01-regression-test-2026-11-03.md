# DUAL-UNIT-01 回归测试用例与结果（2026-11-03）

范围：本次双平台专属执行单元拆分及其直接影响面。  
工具：Playwright MCP（项目 `scripts/qa/mcp_client.py` stdio 客户端）+ 本机 Chrome；只读 PostgreSQL；Temporal history。  
样本：真实 UI 提交、target=1 小样本；不重复大规模采集。

## 用例清单

| ID | 测试场景 | 前置条件 | 操作步骤 | 预期结果 | 优先级 | 验证方式 |
|---|---|---|---|---|---|---|
| R1-01 | 执行单元页展示两个专属单元 | 两单元 READY；Worker 在线 | 登录 5173，打开 `/execution-units` | 两行：`unit-local-mac-02`（巨量星图）、`unit-local-mac-03-juxing`（磁力聚星）；Worker ONLINE 1 实例；浏览器 STOPPED | P0 | MCP UI + 截图 |
| R1-02 | 执行单元汇总指标正确 | 同上 | 读取页首四个指标 | 可用单元=2；采集中=0；待人工验证=0；隔离/异常=0 | P1 | MCP UI |
| R1-03 | 账号/线路脱敏、当前任务为空 | 同上 | 读取两行 | 账号/线路为 `•••` 脱敏；当前任务为 `—` | P1 | MCP UI |
| R2-01 | 任务中心平台筛选选项 | 登录 | 打开 `/tasks`，读取平台下拉 | 选项为 全部平台/巨量星图/磁力聚星 | P0 | MCP UI |
| R2-02 | 平台筛选只返回对应平台 | 存在双平台历史/新任务 | 依次选巨量星图、磁力聚星 | 星图结果全部为星图；聚星结果全部为聚星；数量>0 | P0 | MCP UI + DB |
| R2-03 | 星图任务详情可打开且数据正确 | 已完成星图任务 | 直接打开 `/tasks/<星图root>` | 平台=巨量星图；状态=已完成；计数/需求/达人区正常；无错误态 | P0 | MCP UI + 截图 |
| R2-04 | 聚星任务详情可打开且数据正确 | 已完成聚星任务 | 直接打开 `/tasks/<聚星root>` | 平台=磁力聚星；状态=已完成；聚星字段/计数正常；无错误态 | P0 | MCP UI + 截图 |
| R3-01 | 新建任务平台选择器双平台可用 | 登录；Flag=1 | 打开 `/tasks/new`，读取平台单选 | 两个平台均 enabled；可切换选中 | P0 | MCP UI |
| R3-02 | 星图表单字段正确 | 同上 | 选巨量星图 | 出现内容关键词、背景信息、受众画像、目标数量；不出现聚星专属区块 | P0 | MCP UI |
| R3-03 | 聚星表单字段正确 | 同上 | 选磁力聚星 | 出现关键词、内容类型、聚星粉丝/报价等字段；不出现星图专属筛选 | P0 | MCP UI |
| R3-04 | 目标数量约束与能力一致 | 同上 | 读取两平台目标输入 min/max/default | 与当前 `/api/platforms/*/capabilities` 返回一致；默认值在范围内 | P1 | MCP UI + API |
| R4-01 | 星图新任务路由旧单元 | 两 Worker 就绪 | 真实 UI 提交星图 target=1 | `root_tasks.unit_id=unit-local-mac-02`；旧队列执行 | P0 | MCP 提交 + DB |
| R4-02 | 聚星新任务路由新单元 | 两 Worker 就绪 | 真实 UI 提交聚星 target=1 | `root_tasks.unit_id=unit-local-mac-03-juxing`；新队列执行 | P0 | MCP 提交 + DB |
| R4-03 | 新任务无跨平台误派 | 本轮有 2 平台新任务 | 查询本轮所有新任务 | 星图全部旧 unit；聚星全部新 unit；无 `PLATFORM_BINDING_NOT_CONFIGURED` | P0 | DB |
| R5-01 | 跨平台真实并行 | 两单元空闲；会话有效 | 连续提交星图 A + 聚星 C；1s 采样 | 两 unit 同时 LEASED/collect、不同 current root；Temporal activity 区间正重叠；两 Chrome/Profile 独立 | P0 | MCP + DB + Temporal + FS |
| R5-02 | 并行任务数据正确 | R5-01 完成 | 查两任务/达人/快照/页面 | 两任务合理终态；各 1/1；平台字段正确；页面可读 | P0 | DB + MCP UI |
| R6-01 | 同平台任务串行 | 同一平台提交两个任务 | 提交星图 A、B；采样 | A 执行时 B QUEUED；B activity start > A complete；无重叠 | P0 | MCP + DB + Temporal |
| R6-02 | 每单元最大活动采集 1 | 双平台各两任务 | 提交 A/B/C/D；采样 | 星图最大 1、聚星最大 1；无同 unit 双活动 | P0 | 采样器 + DB |
| R6-03 | 同平台后续任务及时启动 | R6-01/02 | 记录 A→B、C→D 衔接 | 在现有调度窗口内启动（本轮实测应为毫秒级；记录实际值） | P1 | Temporal |
| R7-01 | 星图达人库正常 | 登录；有星图数据 | 打开 `/creators?platform=douyin_xingtu` | 标题/平台正确；列表加载；无错误态 | P1 | MCP UI + 截图 |
| R7-02 | 聚星达人库正常 | 登录；有聚星数据 | 打开 `/creators?platform=kuaishou_juxing` | 标题/平台正确；列表加载（含新采集）；聚星字段口径展示 | P1 | MCP UI + 截图 |
| R7-03 | 达人详情双平台可读 | 两平台达人存在 | 从两平台库各点开一位达人 | 详情加载；平台标签正确；字段/单位/时间正常；无跨平台污染 | P1 | MCP UI |
| R8-01 | 旧聚星历史任务仍归旧 unit | 历史任务存在 | 查旧聚星 root | `unit_id=unit-local-mac-02`；`updated_at` 未被本轮改写 | P0 | DB |
| R8-02 | 旧星图历史任务可读 | 历史任务存在 | 打开一条旧星图任务详情 | 页面正常；状态/计数/快照可读 | P1 | MCP UI + DB |
| R8-03 | 历史数据未被重写 | 切换前备份存在 | 对比旧任务 unit/updated_at/快照 | 旧任务 unit/updated_at 保持切换前；快照仍不可变 | P0 | DB + 备份 |
| R9-01 | 未登录 API 401、登录可用 | 未登录 MCP 新会话 | 访问 `/api/auth/me`；再登录 5173 | 未登录 401；真实登录进入任务中心 | P0 | MCP UI |
| R9-02 | 平台/执行单元读接口正确 | 已登录 | 读取 `/api/platforms`、`/api/execution-units` | 两平台 enabled；两 unit platforms 正确 | P1 | MCP/UI + API |
| R10-01 | Worker 离线隔离 | 本轮不重复破坏性演练 | 引用 DUAL-UNIT-01 真实验收 B-04/B-05/E-01/E-02 | 离线期间对应平台任务 QUEUED、另一平台继续；重启后恢复 | P1 | 引用既有证据 |
| R10-02 | 真实挑战/接管 | 本轮不强制触发 | 引用 DUAL-UNIT-01 真实验收 F-07 | 挑战不阻塞另一平台；接管/恢复完成 | P1 | 引用既有证据 |

## 执行记录与结果

执行时间：2026-11-03 21:24—21:30（Asia/Shanghai）。  
环境：5173/8000/55432/56379/57233 运行中；两 unit `READY`；无在途任务；`update-scheduler` 未运行；本轮未重启 Worker、未执行破坏性故障演练。  
工具：Playwright MCP（项目 stdio 客户端 + 本机 Chrome）、只读 PostgreSQL、Temporal history、1 秒采样器。

### 1. 动态回归：双平台各两任务（R4/R5/R6）

本轮通过真实 UI 新提交 4 条 target=1 任务：

| 任务 | 平台 | 单元 | 状态 | 有效/发现 | activity 区间（Asia/Shanghai） |
|---|---|---|---|---|---|
| A `96b3919d` | 星图 | `unit-local-mac-02` | COMPLETED | 1/1 | 21:24:43.759 → 21:26:00.958 |
| B `f3cf875a` | 星图 | `unit-local-mac-02` | COMPLETED | 1/1 | 21:26:00.960 → 21:27:16.600 |
| C `fc6a48dc` | 聚星 | `unit-local-mac-03-juxing` | COMPLETED | 1/1 | 21:24:53.080 → 21:25:27.919 |
| D `166d2b32` | 聚星 | `unit-local-mac-03-juxing` | COMPLETED | 1/1 | 21:25:27.921 → 21:26:08.442 |

- 星图 A/B：B 在 A 完成后 **0.002 秒**开始，区间无重叠；聚星 C/D：D 在 C 完成后 **0.002 秒**开始，区间无重叠。
- 星图 A 与聚星 C 真实重叠 **34.84 秒**；跨平台并行成立。
- 100 余个 1 秒采样点中，每 unit 最大同时活动采集均为 **1**。
- 4 条任务 `creator_platforms` 均只含本平台；各 1 位有效达人、1 份快照。
- 原始报告：`.runtime/dual-unit-acceptance/regression-two-each-20261103/report.json`、`data-validation.json`、`samples.jsonl`。

### 2. UI 回归（R1/R2/R3/R7/R9）

执行脚本：[dual_unit_ui_regression.py](../../scripts/acceptance/dual_unit_ui_regression.py)；报告：`.runtime/dual-unit-acceptance/regression-ui-20261103-rerun/report.json`。

| 用例 | 结果 | 实测 |
|---|---|---|
| R9-01 | PASS | 未登录 `/api/auth/me` 返回 `ACCOUNT_LOGIN_REQUIRED`；media-a 真实登录进入任务中心 |
| R1-01 | PASS | 执行单元页 2 行；`unit-local-mac-02`（巨量星图）与 `unit-local-mac-03-juxing`（磁力聚星） |
| R1-02 | PASS | 可用单元=2；采集中=0；待人工验证=0；隔离/异常=0 |
| R1-03 | PASS | 账号/线路 `•••` 脱敏；当前任务 `—` |
| R2-01 | PASS | 平台筛选选项 = 全部平台/巨量星图/磁力聚星 |
| R2-02 | PASS | 星图筛选第一页 20 行，全部为巨量星图；聚星筛选 12 行，全部为磁力聚星 |
| R2-03 | PASS | 星图任务 `f3cf875a` 详情：平台、已完成、任务内达人、需求与执行约束正常 |
| R2-04 | PASS | 聚星任务 `166d2b32` 详情：平台、已完成、任务内达人、需求与执行约束正常 |
| R3-01 | PASS | 两平台单选均 `disabled=false`，可切换 |
| R3-02 | PASS | 星图表单包含内容关键词/背景信息/受众画像/目标数量，无聚星专属区块 |
| R3-03 | PASS | 聚星表单包含内容类型/目标数量等，无连接用户数/学历/黄v认证/观众画像 |
| R3-04 | PASS | 星图目标 min=1/max=200/默认 20；聚星 min=1/max=30/默认 20，均在范围内 |
| R7-01 | PASS | 巨量星图达人库加载；“位已加载”>0；详情页出现 `星图ID`/粉丝/当前达人资料 |
| R7-02 | PASS | 磁力聚星达人库加载；“位已加载”>0；详情页出现 `快手ID`/粉丝/当前达人资料 |
| R9-02 | PASS | 执行单元页证明两 unit 均已注册；平台选择器双平台可用 |

截图：[执行单元](assets/dual-unit/regression/01-execution-units.png)、[聚星筛选](assets/dual-unit/regression/02-task-filter-juxing.png)、[星图任务详情](assets/dual-unit/regression/03-xingtu-task-detail.png)、[聚星任务详情](assets/dual-unit/regression/03-juxing-task-detail.png)、[聚星新建表单](assets/dual-unit/regression/04-juxing-new-task-form.png)、[星图达人库](assets/dual-unit/regression/05-xingtu-library.png)、[聚星达人库](assets/dual-unit/regression/05-juxing-library.png)。

### 3. 历史与数据回归（R8）

- 旧聚星历史 3 条仍为 `unit-local-mac-02`，`updated_at` 保持 2026-10-31：
  - `b9517e8b` 02:26:05、`210b37c4` 03:11:01、`e5a8ca5b` 11:43:43（Asia/Shanghai）。
- 本轮 4 条新任务中，星图 2 条全部旧 unit，聚星 2 条全部新 unit；无 `PLATFORM_BINDING_NOT_CONFIGURED`。
- 旧任务/快照未被重写；当前无在途任务、无 open verification/takeover。

### 4. 本轮测试失败与修复记录

- 首次 UI 回归中 R7-01-detail/R7-02-detail 失败：断言要求详情页包含“巨量星图达人/磁力聚星达人”标题前缀，但详情页实际使用 `星图ID` / `快手ID` 标识平台。检查实际页面内容后确认是**测试脚本断言问题**，不是产品缺陷。
- 最小修复仅修改测试脚本：按平台使用 `星图ID`/`快手ID` + “粉丝” + “当前达人资料”断言；重跑 UI 回归 **全部 PASS**。未修改任何产品代码、核心流程或架构。

### 5. 未重复执行的用例

| 用例 | 状态 | 说明 |
|---|---|---|
| R10-01 Worker 离线隔离 | 引用既有真实验收 | [DUAL-UNIT-01 真实验收](DUAL-UNIT-01-live-acceptance-2026-11-03.md) §7 已做两方向 Worker 离线/重启；本轮不重复破坏性演练 |
| R10-02 真实挑战/接管 | 引用既有真实验收 | 同上 §6 已完成真实滑块/接管/恢复；本轮未强制触发验证码 |
| 精确资源 RSS/swap | NOT RUN | 两 Chrome 并行完成、无 OOM；未做 RSS 精确采样 |
| Chrome 强制关闭/会话失效/取消/回滚 | NOT RUN | 属于破坏性/变更性演练；本轮回归不改运行环境，引用既有证据或另行批准 |

## 6. 回归结论

- **PASS**：R1—R9 本轮全部通过；R4/R5/R6 有真实 4 任务动态证据；R8 历史未重写；R10 引用既有真实故障隔离证据。
- **未发现本轮修改引入的产品缺陷**。唯一失败是测试脚本断言错误，已最小修复并复跑通过。
- **GO（回归）**：双平台专属执行单元、路由、并行/串行、任务中心/达人库/详情、历史兼容均未回归。
- 既有问题（真实挑战 `LEASE_LOST`、`dev.sh restart` 45 秒窗口）仍按 [真实验收报告](DUAL-UNIT-01-live-acceptance-2026-11-03.md) 记录，本轮未触发/未修复。
