# KJX-01 磁力聚星功能补齐与双平台全量回归：测试用例清单

状态：首轮真实用户冒烟已完成（2026-10-29）；用例先于执行编写，实际结果与证据已回填  
建立时间：2026-10-29（Asia/Shanghai）  
关联卡片：[KJX-01](../tasks/KJX-01.md)  
关联证据：[阶段 C 验收](KJX-01-stage-c-acceptance.md)

## 1. 测试目的与边界

本清单覆盖两轮：

1. **首轮真实用户冒烟**：在阶段 C 隔离栈（API 4190 / Vite 4191 / Temporal 57234 / PostgreSQL 55439 `xingtu_test_stage_c`）上，用 Playwright MCP + 系统 Chrome 从真实用户视角读取已有任务、达人库和达人详情，验证阶段 C 已交付能力，并记录分页、筛选、详情字段的基线缺口。
2. **最终全量回归**：本轮功能补齐后，在新隔离栈与授权小样本真实任务上重跑全部用例，并追加分页、筛选、字段、星图回归和真实任务用例。

首轮边界：

- **不提交新的真实采集任务**；任务创建中的“提交”、AI 转换真实调用和真实平台访问标 `BLOCKED`，留到最终回归或按授权执行。
- 首轮只读已有阶段 C 数据；不修改数据库、不点重试/取消、不触发平台访问。
- 平台只读调查与本轮开发后的真实任务在后续阶段执行，不在本文件首轮用例中冒充通过。

## 2. 测试环境与工具

| 项 | 值 |
|---|---|
| 操作系统 | macOS |
| 分支 / HEAD | `快手_1026` / `1cfbb6d`（工作区有既有未提交改动，本轮不提交） |
| API | `http://127.0.0.1:4190`（真实 Uvicorn） |
| 前端 | `http://127.0.0.1:4191`（真实 Vite 7.3.7） |
| Temporal | `127.0.0.1:57234`（Temporal 1.9.1 / Server 1.32.0） |
| PostgreSQL | `127.0.0.1:55439`，`xingtu_test_stage_c`，迁移 20 |
| Redis | `127.0.0.1:6379` DB14 |
| 执行单元 | `unit-local-mac-02`，双平台绑定，worker generation 3 |
| 浏览器 | 系统 Chrome 156.0.8078.49 |
| MCP | `@playwright/mcp` 0.0.77，stdio JSON-RPC；`browser_*` 工具驱动；不是 Playwright Python 页面自动化 |
| 产品账号 | 阶段 C 私有凭据（不写入本文） |
| 聚星账号 | 子账号 `60821564` 绑定；首轮不访问平台 |
| 星图账号 | 阶段 C 已绑定账号；首轮不访问平台 |

Playwright MCP 说明：本会话工具目录未直接暴露 MCP 工具，沿用项目已验证的 [stdio 客户端](../../scripts/qa/mcp_client.py) 驱动同一 `@playwright/mcp` 服务器与系统 Chrome；产品 UI 使用隔离上下文，所有交互经 `browser_navigate/snapshot/click/type/evaluate/take_screenshot/network_requests/console_messages` 执行。

## 3. 用例状态与类型定义

状态：`PASS` / `FAIL` / `BLOCKED` / `NOT_RUN` / `NOT_APPLICABLE`。  
类型：

- **UI 交互**：真实浏览器、真实前端、真实 API。
- **Mock/合成集成**：合成适配器、路由 Mock、合同夹具，不访问真实平台。
- **真实 API/数据库**：真实 FastAPI + 隔离 PostgreSQL 读取/校验。
- **真实平台端到端**：真实 Chrome/Profile/平台页面与真实采集任务。

## 4. 首轮真实用户冒烟用例矩阵

> 预期结果列写“应该发生什么”；实际结果/状态/证据在首轮执行后回填。基线缺口允许出现 `FAIL`，它正是本轮开发输入；不得把基线缺口标成 PASS。

### A. 登录与平台选择

| 用例 ID | 业务模块 | 前置条件 | 用户操作步骤 | 预期结果 | 测试类型 | 实际结果 | 状态 | 证据 |
|---|---|---|---|---|---|---|---|---|
| KJX-SMK-A01 | 登录 | 栈已启动 | 打开 `/login` | 显示产品账号、密码、安全登录；无平台入口 | UI 交互 | 登录页显示产品账号/密码/安全登录 | PASS | login-page |
| KJX-SMK-A02 | 登录 | 已打开登录页 | 输入产品账号密码并登录 | 跳转 `/tasks`；显示当前用户 | UI 交互 | 登录后 path=/tasks，显示当前用户 | PASS | after-login |
| KJX-SMK-A03 | 平台选择 | 已登录 | 打开 `/tasks/new` | 平台选择显示巨量星图/磁力聚星两个选项，均可用（Flag 开） | UI 交互 | 平台选项 2 个且均可用 | PASS | tasks-new |
| KJX-SMK-A04 | 平台选择 | 新建任务页 | 选择磁力聚星 | 表单只显示已核验关键词、内容类型和目标数；能力版本为聚星合同 | UI 交互 | 聚星表单仅显示合同开放的关键词/内容类型 | PASS | new-juxing |
| KJX-SMK-A05 | 平台选择 | 已选聚星 | 切换到巨量星图 | 表单切换为星图筛选，不出现聚星内容类型/目标上限文案 | UI 交互 | 切回星图后显示星图筛选 | PASS | new-xingtu |
| KJX-SMK-A06 | 平台选择 | 已在星图填过条件 | 切回聚星 | 星图条件不泄漏到聚星表单；聚星只显示自身条件 | UI 交互 | 切换到聚星后星图关键词未泄漏到聚星表单 | PASS | new-juxing |
| KJX-SMK-A07 | 平台能力 | 已选聚星 | 读取能力横幅与字段 | 显示聚星 capability version；字段数量与合同一致 | UI 交互 | 聚星能力版本与字段数显示正确 | PASS | new-juxing |

### B. 任务创建

| 用例 ID | 业务模块 | 前置条件 | 用户操作步骤 | 预期结果 | 测试类型 | 实际结果 | 状态 | 证据 |
|---|---|---|---|---|---|---|---|---|
| KJX-SMK-B01 | 关键词 | 聚星表单 | 输入“母婴” | 输入保留原文；条件摘要显示关键词 | UI 交互 | 关键词输入并进入条件摘要 | PASS | new-juxing-keyword |
| KJX-SMK-B02 | 内容分类 | 聚星表单 | 查看内容类型下拉 | 只出现合同已验证的“母婴亲子”；无未验证选项 | UI 交互 | 内容类型仅含母婴亲子 | PASS | new-juxing |
| KJX-SMK-B03 | 目标数量 | 聚星表单 | 查看目标数量输入 | 最小值 1、最大值来自服务端隔离配置 10、默认 3 | UI 交互 | 目标数 min/max/value={'type': 'number', 'placeholder': None, 'aria': None, 'value': '3', 'min': '1', 'max': '10', 'valid': True} | PASS | new-juxing |
| KJX-SMK-B04 | 非法参数 | 聚星表单为空 | 直接提交 | 客户端提示“请至少设置一项业务筛选条件”，不发请求 | UI 交互 | 空表单提交被客户端校验拦截 | PASS | new-juxing-empty |
| KJX-SMK-B05 | 非法参数 | 聚星表单 | 目标数输入 0 或 11 | 浏览器/服务端约束阻止非法值；不创建任务 | UI 交互 | 目标数 11 触发浏览器范围约束: {'min': '1', 'max': '10', 'valid': False, 'overflow': True} | PASS | target-11 |
| KJX-SMK-B06 | AI 转换 | 已填聚星条件 | 提交并观察任务转换 | 真实 DeepSeek 生成 filter_plan.v3，条件与输入一致 | 真实平台端到端 | 首轮不提交真实任务；AI 转换在最终回归 T1/T2 验证 | BLOCKED | round1-policy |
| KJX-SMK-B07 | 任务创建 | 已填聚星条件 | 提交任务 | 返回任务详情；平台为聚力聚星；任务进入 RECEIVED/QUEUED | 真实平台端到端 | 首轮不提交真实任务；前端提交在最终回归 T1/T2/T3 验证 | BLOCKED | round1-policy |
| KJX-SMK-B08 | Feature Flag 关闭 | 独立 API 进程（Flag=0） | 读取 `/api/platforms` 并尝试创建聚星任务 | 聚星入口 disabled；创建被 `KUAISHOU_JUXING_FEATURE_DISABLED` 拒绝；星图不变 | Mock/合成集成 | Flag 关闭由独立 API 进程/单测在 Phase 5 验证；首轮不重启隔离栈 | NOT_RUN | round1-policy |
| KJX-SMK-B09 | 平台切换幂等 | 聚星表单 | 切换平台后返回并提交 | 切换平台生成新的幂等键；旧条件不跨平台提交 | UI 交互 | 平台切换时前端重新生成幂等键属内部行为，首轮不提交任务无法端到端观察；由前端组件测试覆盖 | NOT_RUN | new-juxing-back |

### C. 任务中心

| 用例 ID | 业务模块 | 前置条件 | 用户操作步骤 | 预期结果 | 测试类型 | 实际结果 | 状态 | 证据 |
|---|---|---|---|---|---|---|---|---|
| KJX-SMK-C01 | 任务列表 | 已登录 | 打开任务中心 | 真实任务列表加载，无接口错误 | UI 交互 | 任务中心已加载真实任务列表 | PASS | tasks |
| KJX-SMK-C02 | 平台标识 | 任务中心 | 查看聚星/星图任务行 | 每行显示正确平台；聚星行不显示星图专属文案 | UI 交互 | 任务行包含两个平台标签 | PASS | tasks |
| KJX-SMK-C03 | 聚星任务 | 任务中心 | 查找阶段 C 聚星任务 | 可见 C2/C3 等聚星任务及状态 | UI 交互 | 阶段 C 聚星任务可见 | PASS | tasks |
| KJX-SMK-C04 | 任务状态 | 任务中心 | 查看聚星完成/失败任务 | 状态与阶段 C 证据一致：完成/失败/部分完成 | 真实 API/数据库 | 完成/失败/部分完成状态可见 | PASS | tasks |
| KJX-SMK-C05 | 计数 | 聚星任务行 | 读取发现/资料/失败计数 | 计数来自真实任务；聚星不显示“精选”计数 | UI 交互 | 聚星任务不显示精选计数，失败步骤 1 可见 | PASS | task-c3 |
| KJX-SMK-C06 | 进度 | 任务详情 | 查看进度轨/执行状态 | 聚星文案按平台切换；无 F06 文案 | UI 交互 | 任务详情显示平台能力版本与完成状态 | PASS | task-c3 |
| KJX-SMK-C07 | 任务详情 | 聚星任务 | 打开任务详情 | 显示平台、能力版本、目标/有效/资料完整/失败计数、任务内达人 | 真实 API/数据库 | 任务详情显示发现/有效/资料/失败计数 | PASS | task-c3 |
| KJX-SMK-C08 | 失败任务 | 阶段 C 失败聚星任务 | 打开失败任务详情 | 显示失败原因与重试入口；不显示伪造成功 | 真实 API/数据库 | 页面未出现 actual failure_reason（仅显示“任务需要关注/已采到 0/1 位…”）；API 返回 PLATFORM_PAGE_CHANGED:BROWSER_ACTION_FAILED | FAIL | task-failed |
| KJX-SMK-C09 | 允许操作 | 聚星完成/失败任务 | 查看可用按钮 | 完成无 retry；失败显示 retry；按钮不误用于不适用操作 | UI 交互 | 完成聚星任务无 retry；失败聚星任务显示“继续采集（还差 1 位）”（C09b PASS） | PASS | task-c3；task-failed |

### D. 达人库

| 用例 ID | 业务模块 | 前置条件 | 用户操作步骤 | 预期结果 | 测试类型 | 实际结果 | 状态 | 证据 |
|---|---|---|---|---|---|---|---|---|
| KJX-SMK-D01 | 达人库 | 已登录 | 打开 `/creators` | 默认星图列表加载；无接口错误 | UI 交互 | 默认星图列表 2 位（Xingtu 基线） | PASS | library-xingtu |
| KJX-SMK-D02 | 平台切换 | 达人库 | 平台下拉选择磁力聚星 | URL 带 `platform=kuaishou_juxing`；列表切为聚星 | UI 交互 | URL 带平台参数；平台下拉切换后 URL/列表同步 | PASS | library-juxing；library-switched |
| KJX-SMK-D03 | 聚星列表 | 已切聚星 | 查看列表行 | 显示聚星昵称/地区/内容类型/粉丝/月涨粉率；无星图专属筛选 | 真实 API/数据库 | 聚星列表 12 位，显示粉丝/月涨粉率 | PASS | library-juxing |
| KJX-SMK-D04 | 星图列表 | 已切星图 | 查看列表行 | 星图列表与阶段 C 一致；行业/互动/CPM 等字段仍在 | 真实 API/数据库 | 星图列表与阶段 C 基线一致 | PASS | library-xingtu |
| KJX-SMK-D05 | 聚星筛选 | 已切聚星 | 输入省/市、粉丝区间、仅看完整 | 请求携带平台参数；服务端只接受聚星已支持筛选 | 真实 API/数据库 | 聚星筛选仅省/市/粉丝/完整，无星图专属；省份=山东筛选后仅山东行 | PASS | library-juxing；library-juxing-province |
| KJX-SMK-D06 | 排序 | 已切聚星 | 切换更新时间/粉丝排序 | 请求 `sort` 合法；非法排序被拒绝 | UI 交互 | 聚星排序仅更新时间/粉丝 | PASS | library-juxing |
| KJX-SMK-D07 | 字段准确性 | 聚星列表 | 与快照比对粉丝/地区/内容类型 | 列表值与快照投影一致；缺失显示“暂无数据”而非 0 | 真实 API/数据库 | 列表值与快照一致；缺失地区显示暂无数据 | PASS | library-juxing |
| KJX-SMK-D08 | 详情入口 | 聚星列表 | 点击一位达人 | 进入聚星详情；URL/平台正确；无星图子资源请求 | UI 交互 | 进入聚星达人详情 | PASS | creator-juxing-base |

### E. 达人详情

| 用例 ID | 业务模块 | 前置条件 | 用户操作步骤 | 预期结果 | 测试类型 | 实际结果 | 状态 | 证据 |
|---|---|---|---|---|---|---|---|---|
| KJX-SMK-E01 | 基础资料 | 聚星详情 | 查看左栏与基础资料 | 昵称/快手ID/头像/粉丝/涨粉/地区/内容类型/MCN/介绍可见 | 真实 API/数据库 | 基础资料/粉丝/涨粉/地区/内容类型可见 | PASS | creator-juxing-base |
| KJX-SMK-E02 | 商业报价 | 聚星详情 | 查看视频报价 | 三档报价显示平台原值、人民币换算、币种；0 元保留为 0 | UI 交互 | 三档报价原值/人民币/币种；0 保留 | PASS | creator-juxing-base |
| KJX-SMK-E03 | 传播表现 | 聚星详情 | 打开传播表现 | 播放中位数/预期播放/CPM/互动率/完播率/平均互动/视频数/时长显示单位与窗口 | 真实 API/数据库 | 传播表现字段可见 | PASS | creator-juxing-spread |
| KJX-SMK-E04 | 代表作品 | 聚星详情 | 打开代表作品 | 作品标题/发布时间/播放/点赞/评论/转发来自快照；不构造未验证链接 | 真实 API/数据库 | 作品元数据/计数可见 | PASS | creator-juxing-works |
| KJX-SMK-E05 | 受众画像 | 聚星详情 | 打开受众画像 | 粉丝/观众画像存在；当前基线为原始 JSON 折叠展示 | UI 交互 | 粉丝/观众画像存在，各 18 维度 | PASS | creator-juxing-audience |
| KJX-SMK-E06 | 缺失数据 | 含 NO_DATA 字段的达人 | 查看缺失字段 | 显示“平台暂无数据/未采集”，不显示 0、不推测 | UI 交互 | NO_DATA 显示平台暂无数据，不写 0 | PASS | creator-juxing-base |
| KJX-SMK-E07 | 单位/窗口 | 传播表现 | 读取字段备注 | 单位与统计窗口来自合同；不把两种口径混成一个值 | UI 交互 | 单位与统计窗口显示 | PASS | creator-juxing-spread |
| KJX-SMK-E08 | 字段来源 | 聚星详情 | 打开“字段来源”抽屉 | 显示字段状态/来源/快照 ID，不含 Cookie/请求正文 | UI 交互 | 字段来源按钮与抽屉可见，显示字段状态/单位/周期/来源/快照 | PASS | creator-juxing-base；creator-juxing-provenance |
| KJX-SMK-E09 | 合同版本 | 聚星详情 | 查看页面/API 合同 | 合同版本与能力版本一致；旧任务显示其快照合同 | 真实 API/数据库 | 合同 juxing-video-creator-stage-b-v1，字段 25 | PASS | profile-catalog |
| KJX-SMK-E10 | 更多字段 | 聚星详情 | 检查阶段 C 未采集字段 | 应补齐平台真实存在、账号可见且有业务价值的更多字段；未登记字段不得编造 | UI 交互 | 聚星当前仅 25 字段；更多平台字段待 Phase 3 调查后补齐（field_count=25） | FAIL | profile-catalog |
| KJX-SMK-E11 | 作品封面/链接 | 代表作品 | 查看作品封面/跳转 | 应展示平台可验证的作品封面/链接；不可验证时不构造地址并明确说明 | UI 交互 | 作品封面图片数=0；基线不加载封面且未提供可验证作品页 | FAIL | creator-juxing-works |
| KJX-SMK-E12 | 画像可读性 | 受众画像 | 展开画像 | 应将已入库画像解析为维度表（占比/TGI），保留原始结构作权威来源 | UI 交互 | 基线只展示原始 JSON，无维度表/占比/TGI 解读 | FAIL | creator-juxing-audience |

### F. 跨平台兼容

| 用例 ID | 业务模块 | 前置条件 | 用户操作步骤 | 预期结果 | 测试类型 | 实际结果 | 状态 | 证据 |
|---|---|---|---|---|---|---|---|---|
| KJX-SMK-F01 | 平台切换 | 达人库 | 聚星↔星图切换 | 列表/筛选/URL 同步；星图专属筛选不带到聚星 | UI 交互 | 平台切换 URL/列表同步 | PASS | library-xingtu |
| KJX-SMK-F02 | 任务中心 | 任务中心 | 查看双平台任务 | 平台标识、计数、文案按平台切换 | UI 交互 | 任务行显示两个平台标签（C02 证据） | PASS | tasks |
| KJX-SMK-F03 | F06 隐藏 | 聚星任务详情 | 查找精选 | 聚星不显示 F06/精选计数或卡片 | UI 交互 | 聚星任务详情不显示星图 F06/精选 | PASS | task-c3 |
| KJX-SMK-F04 | F06 保留 | 星图任务详情 | 查找精选 | 星图 F06 双集合仍显示 | UI 交互 | 星图任务详情仍显示精选 | PASS | task-xingtu |
| KJX-SMK-F05 | 身份隔离 | 数据库只读 | 查询 `(platform, platform_creator_id)` | 平台身份唯一；同名/同 ID 不跨平台合并 | 真实 API/数据库 | platform_creators 身份重复 0；聚星达人写入星图 current=0 | PASS | db-baseline |
| KJX-SMK-F06 | 账号/Profile | 执行单元页 | 查看绑定 | 两平台绑定独立账号/Profile；单元同一时刻只有一个任务 | 真实 API/数据库 | 执行单元显示双平台绑定/账号校验 | PASS | units |
| KJX-SMK-F07 | 星图不回归 | 星图任务/详情 | 打开星图完成任务的达人详情 | 星图 8 模块/商业指标/F06 与阶段 C 一致 | 真实 API/数据库 | 星图详情 8 模块/商业指标仍可用 | PASS | creator-xingtu-base |

### G. 环境、Flag 与安全

| 用例 ID | 业务模块 | 前置条件 | 用户操作步骤 | 预期结果 | 测试类型 | 实际结果 | 状态 | 证据 |
|---|---|---|---|---|---|---|---|---|
| KJX-SMK-G01 | 服务健康 | 栈已启动 | 检查 API/Vite/Temporal | 401/200/SERVING；无 5xx | 真实 API/数据库 | API 4190 /api/auth/me=401、Vite 4191=200、Temporal=SERVING、两队列 fresh poller、backlog 0 | PASS | round1-health |
| KJX-SMK-G02 | Flag | 隔离栈 | 读取平台目录 | 聚星 enabled=true、capability_status=verified、contract_version 正确 | 真实 API/数据库 | 聚星目录 enabled/verified；contract=juxing-video-creator-stage-b-v1 | PASS | platforms |
| KJX-SMK-G03 | 执行单元 | 隔离栈 | 读取 `/api/execution-units` | 单元 READY、双平台、worker ONLINE、browser STOPPED | 真实 API/数据库 | Worker ONLINE、浏览器 STOPPED | PASS | units |
| KJX-SMK-G04 | Temporal | 隔离栈 | 查看队列与 poller | `xingtu-intake` 与 `xingtu-unit-local-mac-02` 有 fresh poller；backlog 0 | 真实 API/数据库 | Temporal xingtu-intake 与 xingtu-unit-local-mac-02 均有 14 秒内 fresh poller，backlog 0 | PASS | round1-health |
| KJX-SMK-G05 | 前端质量 | 全流程 | 检查控制台/失败请求 | 无未处理异常；无因前端错误触发的 5xx；已知平台查询除外 | UI 交互 | 控制台错误（预期 401 已排除）unexpected=['Total messages: 3 (Errors: 0, Warnings: 0)', 'Returning 1 messages for level "error"']; raw='Total messages: 3 (Errors: 0, Warnings: 0)\nReturning 1 messages for level "error"\n\n[ERROR] Failed to load resource: the server responded with a status of 401 (Unauthorized) @ http://127.0.0.1:4191/api/auth/me:0' | PASS | console-errors |

## 5. 首轮执行记录

- 执行时间：2026-10-29 22:57–23:05（Asia/Shanghai）。
- 执行工具：Playwright MCP `0.0.77`（stdio JSON-RPC，`browser_*` 工具）+ 系统 Chrome 156.0.8078.49；不是 Playwright Python 页面自动化。
- 执行环境：API 4190 / Vite 4191 / Temporal 57234 / PostgreSQL 55439 `xingtu_test_stage_c`（迁移 20）；单元 `unit-local-mac-02`，worker generation 3。
- 执行方式：登录真实产品会话；只读打开任务中心、创建页、任务详情、达人库、聚星/星图详情、执行单元；不提交真实任务、不点 retry/cancel、不访问平台。
- 证据目录：`.runtime/kjx-full/round1/mcp/`（报告、截图、DOM JSON、控制台）；`.runtime/kjx-full/round1/db-baseline.json`；`.runtime/kjx-full/round1/health.txt`。

### 5.1 首轮结果汇总

| 指标 | 数量 |
|---|---:|
| 用例总数 | 57 |
| PASS | 49 |
| FAIL | 4 |
| BLOCKED | 2 |
| NOT_RUN | 2 |
| 覆盖模块 | A–G 全部组 |

首轮 PASS 覆盖：登录与两平台入口、聚星表单现有两项条件与目标上限、客户端空条件/越界校验、任务列表与两平台任务、聚星完成/失败任务详情、聚星/星图达人库切换与聚星省/市/粉丝/完整筛选、聚星详情基础/报价/传播/作品/画像存在性、NO_DATA 与 0 的区分、字段来源抽屉、星图任务 F06/详情、执行单元双平台绑定、Flag/目录、Temporal 队列与控制台（仅登录前 401 属预期）。

### 5.2 首轮失败用例

| 用例 | 实际结果 | 归因 | 本轮处理 |
|---|---|---|---|
| KJX-SMK-C08 | 失败任务页只显示“任务需要关注 / 已采到 0/1 位…”，不显示 API 已有的 `failure_reason=PLATFORM_PAGE_CHANGED:BROWSER_ACTION_FAILED` | 任务详情 UI 未渲染 `failure_reason`（后端已返回） | 最小前端修复：失败/部分完成任务显示失败原因；补组件测试；不影响星图业务 |
| KJX-SMK-E10 | 聚星字段目录仅 25 字段，更多平台可见字段未采集 | 阶段 B live 合同只开放四模块 25 字段 | Phase 3 只读盘点 + Phase 4 在既有四模块内补齐已验证字段 |
| KJX-SMK-E11 | 作品列表无封面图片（`workImages=0`），页面也不提供可验证公开作品页 | 阶段 B 决策“不加载外链封面/不构造链接” | Phase 3 验证封面 URL 与作品页真实性；可验证才展示，否则保留说明 |
| KJX-SMK-E12 | 受众画像只显示“查看平台原始结构”折叠 JSON，无维度表/占比/TGI | 阶段 B 只存原始结构，前端未解析 | Phase 4 前端解析为性别/年龄/地域/兴趣等维度表；保留原始 JSON 作权威来源 |

### 5.3 首轮阻塞与未运行

| 用例 | 状态 | 原因 |
|---|---|---|
| KJX-SMK-B06 | BLOCKED | 首轮不提交真实任务；AI 转换在最终回归 T1/T2 验证 |
| KJX-SMK-B07 | BLOCKED | 首轮不提交真实任务；前端提交在最终回归 T1/T2/T3 验证 |
| KJX-SMK-B08 | NOT_RUN | Flag 关闭需独立 API 进程/单测；首轮不重启隔离栈，Phase 5 补 |
| KJX-SMK-B09 | NOT_RUN | 幂等键重生成属内部行为，首轮不提交无法端到端观察；前端组件测试覆盖 |

### 5.4 首轮缺陷与必须修复项

**必须修复（与本轮三项重点直接相关）**

1. **更多详情字段**（E10）：按 Phase 3 页面/响应证据，在既有 `basic/spread/works/audience` 四模块内补齐；不新增必填模块。
2. **画像可读性**（E12）：前端把已入库的 18 维画像解析为维度表（label/占比/TGI）；保留原始 JSON。
3. **作品封面/链接**（E11）：先验证平台封面 URL 与真实作品页；只展示可验证来源，不构造 URL。
4. **分页与筛选**：首轮基线无第二页、无粉丝/地域/报价表单（A04/B02 的能力边界即证据）；按 Phase 3/4 补齐。
5. **失败原因展示**（C08）：失败/部分完成任务显示后端 `failure_reason`；这是任务中心既有信息的展示缺口，修复范围小，双平台共享。

**首轮观察（非本轮必须，记录以免遗忘）**

- 任务详情的“需求与执行约束”摘要只显示关键词，未显示内容类型；点“查看最终执行计划”可见完整 `filter_plan.v3`（含 `content_type`）。本轮补筛选后应同步摘要，避免用户以为条件未生效。
- 聚星左栏“作品数 25”来自传播统计 `video_count`（近 30 天），作品列表 17 条（平台代表/近期作品），两个口径不同；页面已有统计窗口说明，后续可加更直白的标签。
- 平均时长显示 `10.476`（秒），未按展示精度格式化；不影响数值正确性。
- 登录页控制台唯一错误是登录前 `/api/auth/me` 401（预期）；登录后无未处理异常。

### 5.5 首轮证据路径

| 证据 | 路径 |
|---|---|
| MCP 报告（58 条执行记录） | `.runtime/kjx-full/round1/mcp/report.json` |
| 任务中心 | `.runtime/kjx-full/round1/mcp/tasks.png` |
| 聚星/星图新建任务页 | `.runtime/kjx-full/round1/mcp/new-juxing.png`、`new-xingtu.png` |
| 聚星完成/失败任务详情 | `.runtime/kjx-full/round1/mcp/task-c3.png`、`task-failed.png` |
| 星图任务详情（F06） | `.runtime/kjx-full/round1/mcp/task-xingtu.png` |
| 聚星/星图达人库与省筛选 | `.runtime/kjx-full/round1/mcp/library-juxing.png`、`library-juxing-province.png`、`library-xingtu.png` |
| 聚星详情四章 | `.runtime/kjx-full/round1/mcp/creator-juxing-{base,spread,works,audience}.png` |
| 星图详情 | `.runtime/kjx-full/round1/mcp/creator-xingtu-base.png` |
| 执行单元 | `.runtime/kjx-full/round1/mcp/units.png` |
| DOM/字段目录 JSON | `.runtime/kjx-full/round1/mcp/*.json` |
| 控制台错误 | `.runtime/kjx-full/round1/mcp/console-errors.txt` |
| DB 基线 | `.runtime/kjx-full/round1/db-baseline.json` |
| 服务健康 | `.runtime/kjx-full/round1/health.txt` |

## 6. 最终回归用例（本轮开发后追加）

> 最终回归在补齐后执行，覆盖首轮全部用例 + 下列新增用例；实测结果与证据在最终回归报告中回填。首轮已通过的用例必须重跑，不能只跑新增项。

### 6.1 分页

| 用例 ID | 前置 | 步骤 | 预期 | 类型 |
|---|---|---|---|---|
| KJX-REG-P01 | 第 1 页 20 位、target=22 | 提交聚星任务 | 请求第 2 页；有效 22；COMPLETED；不再请求第 3 页 | 真实平台端到端 |
| KJX-REG-P02 | 第 1 页已满足 target=10 | 提交任务 | 只请求第 1 页；不请求第 2 页 | 合成/真实 API+DB |
| KJX-REG-P03 | 第 1/2 页含重复身份 | 合成适配器跨页 | 重复身份只计一次；无重复 task_creators/snapshot | Mock/合成集成 |
| KJX-REG-P04 | 第 2 页不足且 total 结束 | 合成适配器 | PARTIAL_COMPLETED/SEARCH_EXHAUSTED，不伪报完整 | Mock/合成集成 |
| KJX-REG-P05 | 第 2 页请求失败 | 合成适配器 | 明确失败原因；不报告平台耗尽 | Mock/合成集成 |
| KJX-REG-P06 | 第 2 页空但 total 有更多 | 合成适配器 | 明确页面契约异常；不伪装 exhausted | Mock/合成集成 |
| KJX-REG-P07 | 超过已核验页数 | 合成适配器 | SEARCH_CAPABILITY_LIMIT + PARTIAL_COMPLETED | Mock/合成集成 |
| KJX-REG-P08 | 第 1/2 页筛选条件 | 对比请求体 | 除 currentPage 外请求体一致；条件摘要一致 | Mock/合成集成 |
| KJX-REG-P09 | 断点 cursor=2 | 合成 Engine 重启 | 从第 2 页继续；不重扫第 1 页 | Mock/合成集成 |
| KJX-REG-P10 | 会话失效/挑战 | 合成适配器 | 进入等待/明确会话错误；不误判为候选失败 | Mock/合成集成 |

### 6.2 筛选

| 用例 ID | 前置 | 步骤 | 预期 | 类型 |
|---|---|---|---|---|
| KJX-REG-S01 | 聚星合同 | 单独设关键词 | 请求体 user_name/searchSourceType 正确；结果匹配 | 合成/真实平台 |
| KJX-REG-S02 | 聚星合同 | 单独设内容类型 | contentTagIdList 与页面一致；结果匹配 | 合成/真实平台 |
| KJX-REG-S03 | 聚星合同 | 单独设粉丝区间 | fansMinNum/fansMaxNum 与页面一致；结果匹配 | 合成/真实平台 |
| KJX-REG-S04 | 聚星合同 | 单独设地域 | cityCodeList 与页面一致；结果匹配；无映射则 FAIL/BLOCKED | 合成/真实平台 |
| KJX-REG-S05 | 聚星合同 | 三档报价分别设上限 | priceType/starMinPrice/starMaxPrice 正确；档位互斥 | 合成/真实平台 |
| KJX-REG-S06 | 聚星表单 | 关键词+内容类型+粉丝 | AI 转换与输入一致；服务端通过；Adapter 请求一致 | 真实平台端到端 |
| KJX-REG-S07 | 聚星表单 | 三档报价同时选择 | 前端/服务端/Adapter 明确拒绝互斥组合 | UI + 合成 |
| KJX-REG-S08 | 聚星表单 | 边界值 0/最大值/反向区间 | 非法值阻止；合法边界正确提交 | UI + 合成 |
| KJX-REG-S09 | 聚星表单 | 未支持筛选 | 前端不显示；AI 不生成；Adapter 拒绝；服务端不静默忽略 | UI + 合成 |
| KJX-REG-S10 | 平台切换 | 星图填条件后切聚星 | 条件不泄漏；提交体只含聚星字段 | UI |
| KJX-REG-S11 | 真实结果 | T1 完成后核对粉丝 | 3 位有效达人粉丝均在所选区间 | 真实平台端到端 |
| KJX-REG-S12 | Flag 关闭 | 独立进程 | 聚星入口/创建被拒绝；星图正常 | 真实 API/配置 |

### 6.3 详情字段

| 用例 ID | 前置 | 步骤 | 预期 | 类型 |
|---|---|---|---|---|
| KJX-REG-F01 | 新合同 | 核对四模块 expected_fields 与 Adapter 输出 | 每个字段都有 observation；无意外/缺失 | 合成/合同 |
| KJX-REG-F02 | 真实快照 | 核对单位/窗口/原始值 | 与合同一致；统计窗口保留 | 真实平台+DB |
| KJX-REG-F03 | 含 0/缺失的样本 | 查看报价/平均评论 | 0 保留为 0；缺失为 NO_DATA/“暂无数据” | 真实平台+UI |
| KJX-REG-F04 | 新报价字段 | 查看原价/有效期 | 平台有则展示；无则不造 | 真实平台+UI |
| KJX-REG-F05 | 作品数据 | 查看封面/链接 | 仅平台可验证 URL；失败回退占位；不伪造公开作品页 | 真实平台+UI |
| KJX-REG-F06 | 受众画像 | 查看粉丝/观众维度 | 维度表显示 label/占比/TGI；空维度“暂无数据” | 真实平台+UI |
| KJX-REG-F07 | 源对照 | 3 位达人逐字段对照 | 新字段与平台源值一致；差异有解释 | 真实平台端到端 |
| KJX-REG-F08 | DB | 查询 projection/snapshot | 新字段入库；历史快照不可变；旧快照不回溯改写 | 真实 API+DB |
| KJX-REG-F09 | UI | 字段目录/详情 | 标签/单位/窗口/缺失状态正确；星图不显示聚星字段 | UI |
| KJX-REG-F10 | 隐私 | 检查简介/联系方式 | 电话/微信被脱敏；新字段无联系方式 | 真实 API+DB |
| KJX-REG-F11 | 跨平台 | 查询星图投影 | 聚星达人 0 行写入星图 current；星图字段不映射为聚星 | 真实 API+DB |
| KJX-REG-F12 | 完成判定 | T1/T2 任务 | 新字段 NO_DATA 不影响 profile_complete；无新增必填模块 | 真实平台端到端 |

### 6.4 星图回归

| 用例 ID | 前置 | 步骤 | 预期 | 类型 |
|---|---|---|---|---|
| KJX-REG-X01 | 星图合同 | 加载并校验 | 合同版本/能力/F06 未变；page_fetch 仍为 3 页边界 | 合同 |
| KJX-REG-X02 | 星图真实任务 | 从 UI 提交“宠物/target=1” | COMPLETED；有效/资料完整/精选完整 1 | 真实平台端到端 |
| KJX-REG-X03 | 星图详情 | 8 模块/商业指标 | 与阶段 C 基线一致 | 真实平台+UI |
| KJX-REG-X04 | 星图 F06 | 两集合卡片 | excellent_reach/excellent_seeding 均完整 | 真实平台+UI |
| KJX-REG-X05 | 星图任务中心 | 计数/文案 | 不出现聚星专属切换；F06 正常显示 | UI |
| KJX-REG-X06 | 星图达人库 | 平台筛选/详情 | 星图筛选/字段/历史/报价仍可用 | 真实 API+DB |
| KJX-REG-X07 | 跨平台隔离 | 双平台任务 | 同一单元串行；账号/Profile/数据隔离 | 真实 API+DB |
| KJX-REG-X08 | 自动回归 | 星图专项 | 合同/集成/前端用例全通过 | Mock/合成 + 真实 API+DB |

### 6.5 真实任务与共享功能

| 用例 ID | 前置 | 步骤 | 预期 | 类型 |
|---|---|---|---|---|
| KJX-REG-T01 | 授权 T1 | 前端提交聚星 target=3 过滤任务 | COMPLETED；3/3/3；筛选满足；新字段完整 | 真实平台端到端 |
| KJX-REG-T02 | 授权 T2 | 前端提交聚星 target=22 | COMPLETED；22/22/22；使用第 2 页；无第 3 页；重复 0 | 真实平台端到端 |
| KJX-REG-T03 | 授权 T3 | 前端提交星图 target=1 | COMPLETED；F06 双集合完整；不回归 | 真实平台端到端 |
| KJX-REG-T04 | T1/T2/T3 | DB/Temporal 对账 | 状态/计数/快照/投影/dispatch/workflow 一致 | 真实 API+DB |
| KJX-REG-T05 | 共享 | 登录/任务中心/单元/Flag/隔离 | 双平台共用能力正常；Flag 门禁有效 | UI + 真实 API |
| KJX-REG-T06 | 失败处理 | 历史失败任务/合成 retry | 失败原因/重试范围正确；不重写重试系统 | Mock/合成 + 历史证据 |

## 7. 执行环境与证据索引（首轮 + 最终）

| 阶段 | 目录/文件 | 内容 |
|---|---|---|
| 首轮 | `.runtime/kjx-full/round1/` | MCP 截图、JSON 观察、控制台/网络摘要 |
| 首轮 | `.runtime/kjx-full/round1/logs/` | API/Vite/Temporal/Worker 日志 |
| 平台调查 | `.runtime/kjx-full/probe/` | 分页/筛选/详情只读证据（脱敏） |
| 最终回归 | `.runtime/kjx-full/regression/` | MCP 回归、真实任务、DB/Temporal 对账 |
| 真实任务 | `.runtime/kjx-full/regression/real-tasks/` | T1/T2/T3 任务 ID、截图、计数 |
| 文档 | `docs/evidence/KJX-01-full-regression.md` | 最终 13 项报告与结论 |

> 私有证据目录权限 0700；不在文档中写入 Cookie、Token、DSN、达人昵称/ID 正文或平台响应正文。

## 8. 阶段 D-0 开发后回归结果（2026-10-30）

> 真实栈：DB `xingtu_test_kjx_regression`、API 4192、Vite 4193、Temporal 57235、Redis DB15、单元 `unit-local-mac-02-kjx-full`；所有 UI 操作经 Playwright MCP + Chrome 真实用户路径。详细证据与最终判定见 [全量回归报告](KJX-01-full-regression.md)。

### 8.1 首轮 4 个 FAIL 的修复核对

| 首轮用例 | 首轮现象 | 本轮处理 | 本轮结果 |
|---|---|---|---|
| C08 | 任务详情有 `failure_reason` 但被重试范围文案覆盖 | `attentionDetail` 在重试范围文案后追加服务端原因 | 前端用例「shows the actual failure reason alongside the retry scope」PASS；100+ 前端回归通过 |
| E10 | 详情只有 25 个字段 | basic 18 / spread 31，新增字段全部有 observation | 真实 T1 三位均 18/31/1/2；合同/单测/API 回读 PASS |
| E11 | 作品无封面 | works item 增 `cover_url`，前端渲染封面与标签 | 真实 T1 作品封面存在；前端 fixture 断言封面 URL PASS |
| E12 | 受众只有原始 JSON | 增加 label/占比/TGI 维度表，原始结构保留 | 真实 T1 数据维度表可读；组件测试 PASS |

### 8.2 自动化与 MCP

| 项 | 结果 |
|---|---|
| 后端单元 + 合同 | 403 passed |
| 隔离 PostgreSQL 集成 | 118 passed / 1 skipped |
| E2E | 14 passed |
| 前端 | 103 passed + tsc + build |
| Adapter v2 专项 | 15 passed |
| MCP 设置 | 6 PASS |
| T1 真实任务 | 3 PASS；COMPLETED 3/3/3；四模块 18/31/1/2 |
| T2 最终任务 | **COMPLETED 22/22/22**；`visited_cursors=[None,"2"]`；40 候选；22 creators/snapshots |
| T2-偏差 | 3 PASS（提交/终态）；PARTIAL_COMPLETED 16/22，`SEARCH_EXHAUSTED`；不当分页证据 |
| T3 首次 | 1 valid 后平台 `PLATFORM_SECURITY_CHALLENGE`，`WAITING_FOR_VERIFICATION`；超时 `PARTIAL_COMPLETED`，不绕过验证 |
| T3 同范围重试 | 3 PASS；COMPLETED 1/1/1，profile/pipeline complete |
| 最终双平台 MCP | **19 PASS / 0 FAIL** |

### 8.3 判定

- 聚星分页/筛选/字段的代码、15 条专项与 T1 五项筛选证据成立；T2 最终任务 `56efbba5...` **COMPLETED 22/22/22**，真实第 2 页（`visited_cursors=[None,"2"]`），40 候选、22 creators/snapshots，无第 3 页。
- 星图首次 T3 被平台安全验证阻塞；授权的一次同范围重试 **COMPLETED 1/1/1**，不绕过验证。
- **最终判定：GO**。CONDITIONAL 条件已关闭：T2 最终 22/22/22、第 2 页证据、T3 重试、T1、账号选择提醒与 19/0 MCP 回归全部通过。
- 额外真实样本：T2-偏差 16 位（不用于分页验收）；T3 重试 1 位；T2 最终 22 位；累计有效样本仍在批准 worst-case 49 位内。
- 详情见 [全量回归报告](KJX-01-full-regression.md)。
