# JUXING-MAIN-01 主站双平台整合与真实验收：测试用例清单

状态：P1–P6 已执行并回填；2026-10-31 独立 QA 回归（QAR-*）已执行，详细报告见 [post-integration regression](JUXING-MAIN-01-post-integration-regression.md)。  
建立时间：2026-10-31（Asia/Shanghai）  
关联：[JUXING-MAIN-01 任务卡](../tasks/JUXING-MAIN-01.md)、[整合方案](../design/JUXING-MAIN-01-integration-plan.md)。  
执行原则：先写用例再执行；真实平台只使用授权聚星子账号 `60821564` 与小样本；不点重试/取消/写操作（除明确授权的采集提交）；不用模拟结果冒充真实结果。

## 1. 测试目的与边界

1. 验证 5173 主站同时提供巨量星图与磁力聚星，且两平台共享任务中心、主业务库、达人库和同一个 `unit-local-mac-02` 执行单元。
2. 验证星图原有采集、更新资格、F04/F05/F06、历史数据与达人库不受影响。
3. 验证聚星在主站真实完成 1 位采集，数据只写聚星身份，任务/达人库/详情可查。
4. 验证同单元串行、租约释放、Profile/会话隔离、异常提醒与回退。
5. 不验证聚星更新/补采/精选/报价历史、第 3 页+、200 位容量、Windows。

## 2. 环境与工具

| 项 | 值 |
|---|---|
| 操作系统 | macOS |
| 分支/HEAD | `快手_1026` / `1cfbb6d`（工作区有既有未提交改动，本轮不提交） |
| 主站 | 前端 `http://127.0.0.1:5173`；API `127.0.0.1:8000`；主库 `xingtu_development`（PG 55432）；Temporal 57233；Redis 56379 DB0 |
| 执行单元 | `unit-local-mac-02`（唯一逻辑单元，并发=1） |
| 隔离测试库 | `xingtu_test_juxing_main`（集成/E2E，全新空库） |
| 4193 隔离站 | 测试库 `xingtu_test_kjx_regression`，8 条任务/39 位聚星达人；P4 停止，不导入主库 |
| 产品账号 | `media-a`（口令仅从 `.runtime/qa-credentials.env` 读取） |
| 聚星账号 | 子账号 `60821564`；Profile `.runtime/profiles/unit-local-mac-02-juxing` |
| 星图账号 | `ID: 1807978499337419`；Profile `.runtime/profiles/unit-local-mac-02` |
| 浏览器 | 系统 Chrome 156.0.8078.76 |
| MCP | `@playwright/mcp@0.0.77`（stdio JSON-RPC；`browser_*` 工具，非 Playwright Python 页面自动化） |
| 当前聚星配置 | Flag 未开启；上限候选 30；long-term 200 未验收 |

## 3. 状态与类型定义

状态：`PASS` / `FAIL` / `BLOCKED` / `NOT_RUN` / `PENDING`。  
类型：

- **自动/单元**：纯逻辑、组件或合同测试，不访问真实平台。
- **隔离集成**：真实 PostgreSQL 随机 schema，不访问真实平台。
- **隔离全栈**：真实 API/Vite/DB，不访问真实平台。
- **真实平台端到端**：真实 5173 + 真实账号/Profile/平台页面 + 真实采集。
- **只读检查**：DB/文件/脚本检查。

## 4. 用例矩阵

### A. 环境与基线

| ID | 模块 | 前置 | 步骤 | 预期 | 类型 | 状态 |
|---|---|---|---|---|---|---|
| JXM-ENV-01 | 主站进程 | 切换前 | `dev-no-upd.sh status`；检查 8000/5173 | API 401、前端 200、两队列各 1 新鲜消费者；`update-scheduler` 未运行 | 只读 | PASS |
| JXM-ENV-02 | 主库迁移 | 切换前 | 只读查询 `schema_migrations` | 最大版本 20；不重复迁移 | 只读 | PASS |
| JXM-ENV-03 | 主库基线 | 切换前 | `juxing_main_switch.py baseline` | 117 星图任务、138 达人、293 task_creators、355 快照、90 更新资格 | 只读 | PASS |
| JXM-ENV-04 | 执行单元 | 切换前 | 查 `execution_units` | READY；owner/lease/current_task 空；browser_stopped=true | 只读 | PASS |
| JXM-ENV-05 | 绑定 | 切换前 | 查 `execution_unit_platform_bindings` | 仅 `douyin_xingtu` 一行；无聚星行 | 只读 | PASS |
| JXM-ENV-06 | 在途/验证 | 切换前 | 查非终态任务、OPEN 验证、ACTIVE 接管 | 均为 0 | 只读 | PASS |
| JXM-ENV-07 | Chrome/Profile | 切换前 | 预检锁与 SingletonLock | 星图与聚星 Profile 均 FREE；无 Chrome 占用 | 只读 | PASS |
| JXM-ENV-08 | 4193 数据 | 切换前 | 只读查测试库 | 8 条任务（5 聚星/3 星图）、39 位聚星达人；主库聚星 0 条 | 只读 | PASS |

### B. 平台启用与 Feature Flag

| ID | 模块 | 前置 | 步骤 | 预期 | 类型 | 状态 |
|---|---|---|---|---|---|---|
| JXM-ACT-01 | 平台目录 | 授权门 B 后 | `GET /api/platforms` | 星图/聚星均 enabled=true；合同版本正确 | 真实 API | PASS |
| JXM-ACT-02 | 能力目录 | 同上 | `GET /api/platforms/kuaishou_juxing/capabilities` | 7 项条件、38 内容类目、34 省、3 档报价、target max=30 | 真实 API | PASS |
| JXM-ACT-03 | 绑定注册 | 同上 | 启动 collection worker 后查绑定 | 新增 `(unit-local-mac-02, kuaishou_juxing, 60821564)`；星图行不变 | 只读 | PASS |
| JXM-ACT-04 | 单元页 | 同上 | 打开执行单元页 | `unit-local-mac-02` 显示巨量星图/磁力聚星；无在途 | 真实 UI | PASS |
| JXM-ACT-05 | Flag 关闭 | 任意 | 独立 API 进程 Flag=0 读目录/建聚星任务 | 聚星 disabled；创建被 `KUAISHOU_JUXING_FEATURE_DISABLED` 拒绝；星图不变 | 自动/隔离 | PASS |
| JXM-ACT-06 | Flag 开启 | 任意 | Flag=1 读目录/能力 | 聚星可用；星图合同/能力不变 | 自动/隔离 | PASS |

### C. 登录、平台选择与表单

| ID | 模块 | 前置 | 步骤 | 预期 | 类型 | 状态 |
|---|---|---|---|---|---|---|
| JXM-UI-01 | 登录 | 主站运行 | 打开 5173 `/login`，media-a 登录 | 跳转 `/tasks`；无平台入口泄漏 | 真实 UI | PASS |
| JXM-UI-02 | 任务中心 | 已登录 | 打开 `/tasks` | 既有 117 条星图任务可查；平台徽标正确 | 真实 UI | PASS |
| JXM-UI-03 | 平台选择 | 新建任务页 | 查看平台选择 | 巨量星图/磁力聚星均可用 | 真实 UI | PASS |
| JXM-UI-04 | 表单隔离 | 新建任务页 | 聚星↔星图切换 | 条件不串平台；星图表单不出现聚星字段 | 真实 UI | PASS |
| JXM-UI-05 | 聚星能力 | 选聚星 | 查看表单 | 只出现合同开放字段；能力版本/目标上限正确 | 真实 UI | PASS |
| JXM-UI-06 | 目标上限 | 聚星表单 | 输入 30/31 | 30 可提交；31 被客户端/服务端拒绝 | 真实 UI/API | PASS（能力/前端 input max=30、API 上限测试；未实际提交 31） |
| JXM-UI-07 | 功能边界 | 聚星详情 | 查看按钮/文案 | 无聚星更新/补采/精选/报价历史入口 | 真实 UI | PASS |
| JXM-UI-08 | 星图不变 | 星图表单 | 对比基线 | 筛选字段、文案、目标范围与既有版本一致 | 真实 UI | PASS |

### D. 聚星真实单达人采集（主站）

| ID | 模块 | 前置 | 步骤 | 预期 | 类型 | 状态 |
|---|---|---|---|---|---|---|
| JXM-JX-01 | 创建 | 授权门 B 后 | `/tasks/new`：磁力聚星，关键词“母婴”，内容类型“母婴亲子”，目标 1，提交一次 | 返回 root task；平台 kuaishou_juxing；状态 RECEIVED/QUEUED | 真实平台端到端 | PASS |
| JXM-JX-02 | AI 转换 | 同上 | 查任务详情/requirements | v3 requirement；filter_plan v3 与输入一致；capability 版本正确 | 真实 API/DB | PASS |
| JXM-JX-03 | 调度 | 同上 | 查 Temporal/queue/任务 | intake workflow → task dispatch → `xingtu-unit-local-mac-02`；单元 local-mac-02 | 真实 Temporal | PASS |
| JXM-JX-04 | 账号/Profile | 同上 | 查日志/绑定/Chrome | 使用聚星 Profile 与账号 60821564；不打开星图 Profile | 真实平台 | PASS |
| JXM-JX-05 | 终态 | 同上 | 等待任务 | `COMPLETED`；valid/profile_complete/snapshot 均 1；failed 0 | 真实平台 | PASS |
| JXM-JX-06 | 持久化 | 同上 | 查 `platform_creators`/`creator_snapshots`/`task_creators` | 聚星身份行；四模块快照；无 `douyin_xingtu_creator_current` 新行 | 只读 DB | PASS |
| JXM-JX-07 | 任务中心 | 同上 | 打开任务详情 | 平台徽标、条件摘要、计数正确；无 F06/精选 | 真实 UI | PASS |
| JXM-JX-08 | 达人库 | 同上 | `/creators?platform=kuaishou_juxing` | 出现新达人；指标原单位；缺失不显示 0 | 真实 UI | PASS |
| JXM-JX-09 | 详情 | 同上 | 打开聚星达人详情 | 基础/传播/作品/受众四模块；原始单位/窗口；无星图专属指标 | 真实 UI | PASS |
| JXM-JX-10 | 条件核对 | 同上 | 对照快照与源页面（只读） | 关键词/内容类型/目标一致；无越权条件 | 真实平台 | PASS（UI/DB 条件一致；未做平台源页面逐字段对照） |
| JXM-JX-11 | 不扩大 | 同上 | 查任务数/样本数 | 只新增 1 位聚星有效达人，无额外任务 | 只读 | PASS |
| JXM-JX-12 | 数据来源 | 同上 | 对比 4193 测试库 | 主库聚星达人数=1（非 39）；未导入测试数据 | 只读 DB | PASS |

### E. 星图真实回归（主站）

| ID | 模块 | 前置 | 步骤 | 预期 | 类型 | 状态 |
|---|---|---|---|---|---|---|
| JXM-XT-01 | 创建 | 授权门 B 后 | `/tasks/new`：巨量星图，关键词“宠物”，目标 1，提交一次 | root task platform=douyin_xingtu；状态 RECEIVED/QUEUED | 真实平台端到端 | PASS |
| JXM-XT-02 | AI 转换 | 同上 | 查任务详情 | 星图 requirement v2；filter_plan 与输入一致 | 真实 API/DB | PASS |
| JXM-XT-03 | 账号/Profile | 同上 | 查日志/绑定 | 星图账号 1807978499337419 与星图 Profile；不使用聚星 Profile | 真实平台 | PASS |
| JXM-XT-04 | 采集/F05 | 同上 | 等待任务 | 按既有规则终态；资料模块完整；计数正确 | 真实平台 | PASS |
| JXM-XT-05 | F06 精选 | 同上 | 查任务详情 | 两组精选集合按既有规则；无聚星字段混入 | 真实 UI/DB | PASS |
| JXM-XT-06 | 达人库/详情 | 同上 | 切到星图达人库/详情 | 138 位既有数据 + 本次授权新增；原有详情/F06 不变 | 真实 UI | PASS |
| JXM-XT-07 | 历史任务 | 同上 | 抽查既有任务 6dff3c73/8013a009 等 | 状态/计数/区段/快照与基线一致 | 真实 UI/DB | PASS |
| JXM-XT-08 | 更新资格 | 同上 | 查 `creator_update_schedule`/手动更新入口 | 90 条资格不变；调度器仍未运行；聚星更新仍显式不支持 | 只读/UI | PASS |
| JXM-XT-09 | 安全验证 | 同上 | 若出现验证 | 按既有 15 分钟流程；不绕过；不自动重试 | 真实平台 | NOT_RUN（本次未出现平台安全验证） |
| JXM-XT-10 | 完成判定 | 同上 | 对照基线 | 星图 F04/F05/F06 完成判定语义不变 | 只读/自动 | PASS |

### F. 统一任务中心

| ID | 模块 | 前置 | 步骤 | 预期 | 类型 | 状态 |
|---|---|---|---|---|---|---|
| JXM-TC-01 | 混排 | 两平台任务存在 | 打开 `/tasks` | 两平台任务混排；平台徽标正确 | 真实 UI | PASS |
| JXM-TC-02 | 平台筛选 | 同上 | 选“全部平台/巨量星图/磁力聚星” | 列表只显示对应平台；切换重置 cursor | 真实 UI | PASS |
| JXM-TC-03 | 筛选不影响数据 | 同上 | 切换筛选后刷新/返回 | 任务数据不变；底层不修改 | 真实 UI/DB | PASS |
| JXM-TC-04 | 计数 | 聚星任务 | 查看聚星行 | 无“精选”计数；失败/资料计数正确 | 真实 UI | PASS |
| JXM-TC-05 | 星图计数 | 星图任务 | 查看星图行 | 保留精选计数；F06 信息正常 | 真实 UI | PASS |
| JXM-TC-06 | 历史任务 | 同上 | 查看旧星图任务 | 平台/状态/计数与基线一致 | 真实 UI | PASS |
| JXM-TC-07 | 分页 | 117+ 任务 | 查看更早任务 | cursor 正常；平台筛选下分页仍正确 | 真实 UI | PASS（平台筛选+分页 API；未逐页点击更早任务） |
| JXM-TC-08 | 失败原因 | 有失败/等待任务 | 查看详情 | failure_reason 与平台语义正确；聚星不显示星图文案 | 真实 UI | PASS |

### G. 统一达人库与详情

| ID | 模块 | 前置 | 步骤 | 预期 | 类型 | 状态 |
|---|---|---|---|---|---|---|
| JXM-LIB-01 | 平台切换 | 已登录 | 打开 `/creators`，切星图/聚星 | 列表按平台切换；筛选不串平台 | 真实 UI | PASS |
| JXM-LIB-02 | 星图保留 | 同上 | 切星图 | 138 位既有达人可查；筛选/排序正常 | 真实 UI | PASS |
| JXM-LIB-03 | 聚星新数据 | 聚星任务完成 | 切聚星 | 出现新达人；计数与 DB 一致 | 真实 UI/DB | PASS |
| JXM-LIB-04 | 身份隔离 | 两平台各有数据 | 同名/同 ID 对照 | `(platform, platform_creator_id)` 隔离；不自动合并 | 真实 UI/DB | PASS |
| JXM-LIB-05 | 聚星详情模块 | 同上 | 打开聚星详情 | 基础/传播/作品/受众；报价原值/单位/窗口 | 真实 UI | PASS |
| JXM-LIB-06 | 缺失语义 | 同上 | 查看无数据字段 | 显示无数据，不显示 0 | 真实 UI | PASS |
| JXM-LIB-07 | 星图详情 | 同上 | 打开既有星图详情 | 8 模块/商业能力/F06 与基线一致 | 真实 UI | PASS |
| JXM-LIB-08 | 字段目录 | 同上 | 打开字段来源 | 按平台字段目录；不把聚星字段映射成星图指标 | 真实 UI | PASS |
| JXM-LIB-09 | 子资源 | 同上 | 聚星请求报价/历史/作品观测 | 显式 not-applicable；不伪装成功 | 真实 UI/API | PASS |
| JXM-LIB-10 | 封面/作品 | 同上 | 查看聚星作品 | 平台封面/文本；不使用过期签名外链 | 真实 UI | PASS（works 快照存在；未逐张核对封面 URL） |

### H. 共享执行单元与串行

| ID | 模块 | 前置 | 步骤 | 预期 | 类型 | 状态 |
|---|---|---|---|---|---|---|
| JXM-EU-01 | 同一单元 | 两平台任务 | 查 `root_tasks.unit_id` | 两任务均为 `unit-local-mac-02` | 只读 DB | PASS |
| JXM-EU-02 | 并发=1 | 两任务重叠 | 查 worker/日志/lease | 同一时刻只有一个活动任务；无第二个 Chrome/上下文 | 真实平台/DB | PASS |
| JXM-EU-03 | 排队 | 两任务背靠背提交 | 查后到任务状态 | QUEUED/WAITING_FOR_RESOURCE，原因正确 | 真实 UI/DB | PASS |
| JXM-EU-04 | 串行完成 | 同上 | 等两任务终态 | 先到先执行；后到在前者释放后执行 | 真实平台 | PASS |
| JXM-EU-05 | 租约释放 | 每任务结束 | 查 unit owner/lease | 释放；无残留 owner/current_task | 只读 DB | PASS |
| JXM-EU-06 | Profile 独立 | 同上 | 查 Chrome 进程/Profile | 星图/聚星各用独立目录；不混用 | 只读 OS | PASS |
| JXM-EU-07 | 登录隔离 | 同上 | 查 binding 观测 | 聚星登录异常只影响聚星 binding；星图 binding 不被改写 | 只读 DB/自动 | PASS |
| JXM-EU-08 | 无污染 | 同上 | 对比两平台数据 | 聚星不写星图投影；星图不写聚星投影 | 只读 DB | PASS |
| JXM-EU-09 | 资源占用 | 同上 | 查队列/心跳 | 一个 collection worker；无重复 worker 争用 | 只读 | PASS |
| JXM-EU-10 | 未重叠补充 | 若无真实重叠 | 隔离 Temporal 并发测试 | 用隔离证据补充；报告标注“非真实重叠” | 隔离集成 | NOT_APPLICABLE（真实排队重叠已出现） |

### I. 数据库、历史数据与备份

| ID | 模块 | 前置 | 步骤 | 预期 | 类型 | 状态 |
|---|---|---|---|---|---|---|
| JXM-DB-01 | 计数 | 切换前后 | 对比 baseline counts | 星图 117/138/293/355/90 等保持（除授权新增） | 只读 | PASS |
| JXM-DB-02 | 内容哈希 | 切换前后 | `compare` | 历史星图 count+md5 全部一致 | 只读 | PASS |
| JXM-DB-03 | 聚星写入 | 聚星任务后 | 查平台化表 | 聚星行只在 `platform_creators`/快照等；无星图专表新行 | 只读 | PASS |
| JXM-DB-04 | 身份唯一 | 同上 | 查唯一约束 | `(platform, platform_creator_id)` 唯一 | 只读 | PASS |
| JXM-DB-05 | 快照不可变 | 同上 | 查快照/触发器 | 旧快照未被改写；新快照只追加 | 只读 | PASS |
| JXM-DB-06 | 更新资格 | 同上 | 查 90 条 schedule | 不变；聚星不在更新调度 | 只读 | PASS |
| JXM-DB-07 | 无导入 | 同上 | 对比 4193 | 主库聚星达人数=1，非 39 | 只读 | PASS |
| JXM-DB-08 | 审计 | 同上 | 查 audit_logs/验证事件 | 登录/绑定/任务动作有记录；无敏感值 | 只读 | PASS |
| JXM-DB-09 | 备份 | P3 | dump + sha256 | 完成；文件可读 | 只读 | PASS |
| JXM-DB-10 | 恢复演练 | P3 | 恢复临时库 + compare | 成功；内容一致；临时库删除 | 隔离 | PASS |

### J. 子账号选择、登录失效与提醒

| ID | 模块 | 前置 | 步骤 | 预期 | 类型 | 状态 |
|---|---|---|---|---|---|---|
| JXM-ACC-01 | 正常识别 | 聚星任务 | 观察会话检查 | 账号 60821564 精确匹配；不误判 | 真实平台 | PASS |
| JXM-ACC-02 | 选择页提醒 | 若出现选择页 | 查任务中心/单元页 | 明显提醒“需要选择子账号”；不静默等待 | 真实 UI | NOT_RUN（未出现选择页） |
| JXM-ACC-03 | 人工接管 | 同上 | 按现有接管流程完成选择 | 只选择 60821564；不自动选其他子账号 | 真实平台 | NOT_RUN（未出现选择页） |
| JXM-ACC-04 | ACCOUNT_MISMATCH | 任意 | 只读/自动测试 | 不自动改绑；任务等待/失败原因明确 | 自动/只读 | PASS |
| JXM-ACC-05 | 超时原因 | 任意 | 自动测试 | `ACCOUNT_SELECTION_TIMEOUT` 等终态原因清晰 | 自动 | PASS |
| JXM-ACC-06 | 未出现说明 | 真实任务 | 若未出现选择页 | 记录 NOT_RUN 并引用自动测试，不虚报真实场景 | 证据 | PASS |

### K. 回退与运维

| ID | 模块 | 前置 | 步骤 | 预期 | 类型 | 状态 |
|---|---|---|---|---|---|---|
| JXM-OPS-01 | Flag 回退 | 授权门 B 后 | Flag=0 + 重启 API | 聚星入口关闭；星图正常 | 真实运维 | PASS |
| JXM-OPS-02 | 绑定回退 | 同上 | 单元配置 enabled=false + 重启 collection | 绑定禁用；星图行不变；不删数据 | 真实运维 | NOT_RUN（未执行绑定禁用；代码路径已审查） |
| JXM-OPS-03 | 配置回退 | 同上 | 用 `.pre-switch` 覆盖 | 恢复原配置；进程可启动 | 真实运维 | NOT_RUN（未执行配置回滚；备份已就绪） |
| JXM-OPS-04 | 4193 恢复 | 同上 | `stack.sh up` | 4193 可恢复；数据/配置保留 | 隔离运维 | PASS（数据/配置/Profile/证据保留；未重启 4193） |
| JXM-OPS-05 | 启动文档 | 同上 | 按 docs 启动 5173 | 双平台配置可复现，不再被错误关闭 | 文档/只读 | PASS |

### L. 自动与隔离测试（P1–P3 已执行）

| ID | 范围 | 命令/范围 | 结果 |
|---|---|---|---|
| JXM-AUTO-01 | 后端单元+合同 | `pytest backend/tests/unit backend/tests/contract -q` | **409 passed** |
| JXM-AUTO-02 | 平台筛选 API | `test_product_api.py` | 15 passed（含新增） |
| JXM-AUTO-03 | 平台筛选集成 | `test_task_platform_filter.py` | 2 passed |
| JXM-AUTO-04 | 基线/对比 | `test_juxing_main_baseline.py` | 1 passed |
| JXM-AUTO-05 | 切换工具 | `test_juxing_main_switch.py` | 4 passed |
| JXM-AUTO-06 | 前端 | `npm --prefix frontend run lint/test/build` | 105 passed + lint + build |
| JXM-AUTO-07 | 静态 | Ruff / format / Mypy | 通过（Mypy 38 files） |
| JXM-AUTO-08 | 全量集成 | 全新 `xingtu_test_juxing_main` | **121 passed / 1 skipped**（S3） |
| JXM-AUTO-09 | E2E | `tests/e2e` | **14 passed**（30.73s） |
| JXM-AUTO-10 | 共享库缺陷 | 共享 `xingtu_test_kjx_regression` | `test_migrations_020.py` schema 限定缺陷，独立记录；不视为产品失败 |

## 5. 执行规则与证据

1. 真实平台只使用授权账号/子账号与小样本；单任务单平台；不并发打开两个平台任务。
2. 不绕过登录、验证、账号选择；失败按既有状态与原因收口。
3. 每个真实用例保存：任务 ID、平台、条件、状态流转、计数、截图、网络/控制台断言、DB 只读核对。
4. 私密证据放 `.runtime/juxing-main/evidence/`（0700）；脱敏截图可放 `docs/evidence/assets/juxing-main/`。
5. 未执行/阻塞必须标 `NOT_RUN`/`BLOCKED` 并说明原因；不得用自动测试冒充真实平台结果。
6. 结果回填后，同步任务卡与验收证据；最终给出 GO / CONDITIONAL GO / NO-GO。

## 6. 证据索引（P1–P3）

| 内容 | 位置 |
|---|---|
| 预检 48 项 | `.runtime/juxing-main/preflight-pre-switch.json` |
| 主站基线 | `.runtime/juxing-main/baseline.json` |
| 空闲复核 | `.runtime/juxing-main/compare-idle.json` |
| 恢复演练 | `.runtime/juxing-main/restore-compare.json` |
| 备份 | `.runtime/backups/juxing-main-20261031T021309/` |
| 候选配置/环境增量 | `.runtime/juxing-main/local-dev-mac-02.candidate.json`、`juxing-main.env.additions` |
| 方案/卡片 | [整合方案](../design/JUXING-MAIN-01-integration-plan.md)、[任务卡](../tasks/JUXING-MAIN-01.md) |

## 7. 执行结果与偏差（2026-10-31 P4–P6）

| 项 | 结果 |
|---|---|
| 真实聚星任务 | `b9517e8b-a342-484f-980d-39137f95ff25`，COMPLETED 1/1/1，unit=unit-local-mac-02 |
| 真实星图任务 | `c30b7622-a054-4a0d-9969-e150512e4479`，COMPLETED 1/1/1，unit=unit-local-mac-02 |
| MCP | 验收 20/20 + setup 5/5 + 重启后 5/5 |
| 自动测试 | unit+contract 409、集成 121/1 skip、E2E 14、前端 105、Mypy 通过 |
| 历史一致性 | 历史任务/快照/需求/检查点/任务关联/精选/更新资格无变化；5 处差异全部归因于授权星图任务更新既有达人 |
| Flag 回退 | 临时 API（8001，同一主库/Redis 会话）Flag=0：入口/能力/创建拒绝，既有任务/达人可读，不删数据 |
| 重启持久性 | 正常 stop/up 后双平台仍启用、绑定存在、计数不变（generation 14） |

偏差/未执行说明：

1. **JXM-OPS-01** 使用临时 API 验证 Flag=0，而不是关闭主站 Flag 后重启主 API；主站最终保持 Flag=1，避免两次额外重启与验收后误配置。
2. **JXM-OPS-02**（单元绑定 `enabled=false`）与 **JXM-OPS-03**（配置回滚）未在真实主站执行；备份与操作步骤已就绪，未执行以避免额外中断。它们的分支逻辑不在本轮产品代码改动范围。
3. **JXM-XT-09**（平台安全验证）本次未触发；**JXM-ACC-02/03**（子账号选择/人工接管）本次未出现，会话直接 VALID；以上标 NOT_RUN，不用自动测试冒充真实场景。
4. **JXM-EU-10** 不适用：真实任务已出现「聚星执行、星图 QUEUED、聚星完成后星图执行」的重叠排队。
5. **JXM-TC-07** 未逐页点击「查看更早任务」；平台筛选 + 分页 API/cursor 已由自动测试覆盖。
6. **JXM-JX-10** 未做平台源页面逐字段二次对照；条件一致性与数据正确性由 UI 条件摘要、filter_plan、快照和 DB 核对支持。
7. 30/200 位容量、第 3 页+、聚星更新/补采/精选/报价历史、Windows 不在本轮验收范围。

## 9. 2026-10-31 独立 QA 回归测试用例（执行前编写）

范围：JUXING-MAIN-01 整合后的 5173 主站双平台真实用户回归。默认不新增真实批量采集；真实平台任务读取 P5 已授权的 2 条任务及历史数据。**2026-10-31 已执行并回填**；完整报告见 [post-integration regression](JUXING-MAIN-01-post-integration-regression.md)。

### 9.1 环境与基线

| 用例 ID | 模块 | 优先级 | 前置条件 | 用户操作步骤 | 预期结果 | 测试方式 | 实际结果 | 状态 | 证据 |
|---|---|---|---|---|---|---|---|---|---|
| QAR-ENV-01 | 环境 | P0 | 本机 | 打开 5173，检查 8000/API | 前端 200；API 未登录 401 | 只读/真实 UI | 5173 前端 200；未登录 /api/auth/me 401 | PASS | qa-round/platforms.json |
| QAR-ENV-02 | 环境 | P0 | 已登录会话 | 读取 `/api/platforms` | 星图/聚星均 enabled | UI+真实 API | 双平台 enabled=true；合同版本正确 | PASS | qa-round/platforms.json |
| QAR-ENV-03 | 执行单元 | P0 | 主站运行 | 读取 `/api/execution-units` | unit-local-mac-02 READY、ONLINE、双平台、无当前任务 | 真实 API/DB | unit-local-mac-02 READY/ONLINE/双平台/current=None | PASS | qa-round/units.json |
| QAR-ENV-04 | 任务 | P0 | 主站运行 | 查非终态任务、OPEN 验证、ACTIVE 接管 | 均为 0 | 只读 DB | 非终态 0；OPEN 验证 0；ACTIVE 接管 0 | PASS | db-baseline.json |
| QAR-ENV-05 | Profile | P0 | 主站空闲 | 检查两平台 Profile 锁/绑定 | 两绑定存在；锁 FREE | 只读 | 两平台绑定存在；两 Profile 锁 FREE | PASS | db-baseline.json |
| QAR-ENV-06 | 4193 | P1 | 主站运行 | 检查 4192/4193/57235 与测试库 | 端口关闭；测试库 8 任务/39 聚星达人保留 | 只读 | 4192/4193/57235 端口 0；测试库 8 任务/39 聚星达人保留 | PASS | db-baseline.json |

### 9.2 登录、导航与用户体验

| 用例 ID | 模块 | 优先级 | 前置条件 | 用户操作步骤 | 预期结果 | 测试方式 | 实际结果 | 状态 | 证据 |
|---|---|---|---|---|---|---|---|---|---|
| QAR-UI-01 | 登录 | P0 | 未登录 | 打开 `/login` | 登录页正常、字段/按钮可见 | 真实 UI | 登录页渲染产品账号、密码、安全登录 | PASS | qa-login |
| QAR-UI-02 | 登录 | P0 | 登录页 | media-a 正确登录 | 跳转 `/tasks`，显示媒介 A | 真实 UI | media-a 登录进入任务中心 | PASS | qa-after-login |
| QAR-UI-03 | 导航 | P0 | 已登录 | 依次进入任务中心/创建任务/达人库/执行单元 | 四页均可到达且无白屏 | 真实 UI | 任务中心/创建任务/达人库/执行单元四页可达 | PASS | qa-nav-* |
| QAR-UI-04 | 刷新 | P1 | 任务中心 | 刷新页面 | 页面恢复、任务加载、无异常 | 真实 UI | 刷新任务中心后页面恢复并加载任务 | PASS | qa-refresh-rows |
| QAR-UI-05 | 控制台 | P1 | 已登录 | 采集 console error | 登录后无本轮相关未处理错误 | 真实 UI | 登录后 console 相关错误数=0 | PASS | console-errors |
| QAR-UI-06 | 网络 | P1 | 已登录 | 采集 API 请求 | 无未处理 5xx/失败请求 | 真实 UI | API 请求无 5xx（检测到 0） | PASS | network-api |
| QAR-UI-07 | 登录失败 | P1 | 隔离 API+Vite | 输入错误密码 | 明显错误提示；不进入系统；主站限流不受影响 | 隔离 UI | 错误密码后停留 /login，页面提示“用户名或密码错误”；主站会话仍 200；测试限流键已清理 | PASS | mcp-invalid-login |
| QAR-UI-08 | 权限不足 | P2 | 无停用账号 | 尝试停用账号 | 明确拒绝；无可用测试账号 | 隔离 | 无停用/权限不足测试账号；未创建用户 | NOT_APPLICABLE | — |

### 9.3 平台选择与筛选表单

| 用例 ID | 模块 | 优先级 | 前置条件 | 用户操作步骤 | 预期结果 | 测试方式 | 实际结果 | 状态 | 证据 |
|---|---|---|---|---|---|---|---|---|---|
| QAR-PLT-01 | 平台选择 | P0 | 创建任务页 | 查看两平台选项 | 两项均可用、disabled=false | 真实 UI | 平台选项=[{'text': '巨量星图\n已验证可用', 'disabled': False, 'checked': 'true'}, {'text': '磁力聚星\n已验证可用', 'disabled': False, 'checked': 'false'}] | PASS | qa-platforms |
| QAR-PLT-02 | 星图表单 | P0 | 选择星图 | 查看筛选字段与能力版本 | 星图字段完整；能力版本正确 | 真实 UI | 星图表单字段与能力版本正确 | PASS | qa-form-xingtu |
| QAR-PLT-03 | 聚星表单 | P0 | 选择聚星 | 查看筛选字段/类目/目标上限 | 只出现合同字段；38 类目；目标上限 30 | 真实 UI | 聚星表单合同字段/38 类目/上限 30 正确 | PASS | qa-form-juxing |
| QAR-PLT-04 | 平台切换 | P0 | 聚星已填关键词 | 切到星图再切回 | 星图表单不出现聚星值；聚星条件不串平台 | 真实 UI | 切换平台后不携带聚星筛选值/字段 | PASS | qa-xingtu-values |
| QAR-PLT-05 | 目标上限 | P1 | 聚星表单 | 目标输入 31 | 浏览器 range 校验拒绝；不提交 | 真实 UI | 聚星目标 31 触发浏览器范围校验：{'value': '31', 'valid': False, 'overflow': True, 'max': '30'} | PASS | qa-target-31 |
| QAR-PLT-06 | 空表单 | P1 | 星图/聚星表单 | 直接提交 | 客户端提示“请至少设置一项业务筛选条件”，不发请求 | 真实 UI | 聚星/星图空表单均被客户端拦截，未发请求、未创建任务 | PASS | MCP:qa-empty-submit |
| QAR-PLT-07 | 功能边界 | P1 | 聚星任务详情 | 查看操作/章节 | 无聚星更新/补采/精选/报价历史入口 | 真实 UI | 聚星任务详情无精选；聚星达人详情无“手动更新/报价与历史”；四章节正常 | PASS | MCP:qa-detail-b9517e8b / qa-lib-juxing-detail |
| QAR-PLT-08 | AI 合同 | P1 | 创建任务页 | 查看能力横幅 | 平台/合同版本正确（星图/聚星各一） | 真实 UI+API | 星图 xingtu-ad-creator-square-v3；聚星 juxing-video-square-stage-c-v2；真实任务 requirement v2/v3 已入库 | PASS | MCP:qa-form-* + DB |

### 9.4 统一任务中心

| 用例 ID | 模块 | 优先级 | 前置条件 | 用户操作步骤 | 预期结果 | 测试方式 | 实际结果 | 状态 | 证据 |
|---|---|---|---|---|---|---|---|---|---|
| QAR-TC-01 | 全部任务 | P1 | 任务中心 | 默认列表 | 20 条首屏、状态/平台标识、计数正确 | 真实 UI | 任务中心首屏混排两平台任务与计数 | PASS | qa-task-center |
| QAR-TC-02 | 星图筛选 | P0 | 任务中心 | 选巨量星图 | 只显示星图任务；聚星不出现 | 真实 UI+API | 星图筛选返回 20 条且无聚星 | PASS | qa-tc-xingtu-rows |
| QAR-TC-03 | 聚星筛选 | P0 | 任务中心 | 选磁力聚星 | 只显示聚星任务；1 条 | 真实 UI+API | 聚星筛选返回 1 条 | PASS | qa-tc-juxing-rows |
| QAR-TC-04 | 平台标识 | P0 | 全部列表 | 查看两平台新任务行 | `#c30b7622 巨量星图` / `#b9517e8b 磁力聚星` | 真实 UI | 两平台真实任务行标识正确 | PASS | qa-tc-rows |
| QAR-TC-05 | 分页 | P1 | 任务中心（星图） | 点击“查看更早任务” | 加载更早 20 条；无报错/重复 | 真实 UI+API | 点击更早任务后命中第二页任务 ['d348e1af', '2df0fd1d', 'c37ee17b'] | PASS | qa-tc-older-rows |
| QAR-TC-06 | 切换重置 | P1 | 已分页到第 2 页 | 切到聚星/全部 | cursor 重置；列表正确 | 真实 UI+API | 切换平台后 cursor 重置为聚星 1 条 | PASS | qa-tc-reset-rows |
| QAR-TC-07 | 组合筛选 | P1 | 任务中心 | 平台+状态（已完成） | 只显示已完成且对应平台 | 真实 UI+API | 平台+状态组合筛选（聚星+已完成）行数=1 | PASS | qa-tc-completed-rows |
| QAR-TC-08 | 组合筛选 | P1 | 任务中心 | 平台+类型+日期 | 组合生效、无报错 | 真实 UI+API | 平台/日期组合筛选生效（未来日期空态） | PASS | qa-tc-future |
| QAR-TC-09 | 刷新行为 | P2 | 已选聚星 | 刷新页面 | 页面恢复；筛选重置可接受；数据不丢 | 真实 UI | 刷新后页面恢复、筛选重置为全部平台、数据完整 | PASS | qa-tc-refresh |
| QAR-TC-10 | 跨平台 cursor | P1 | 已有星图 cursor | 用星图 cursor 请求聚星列表 | 422 INVALID_CURSOR；不串平台数据 | 真实 API | 星图 cursor 请求聚星列表 → 422 INVALID_CURSOR | PASS | api-supplementary.json |
| QAR-TC-11 | 非法平台 | P1 | 已登录 | `platform=unknown` | 422；不返回任务 | 真实 API | platform=unknown → 422 query.platform | PASS | api-supplementary.json |
| QAR-TC-12 | API 组合 | P1 | 已登录 | 平台+状态+类型组合 | 返回项全部匹配；计数一致 | 真实 API | 星图+COMPLETED+collection → 16 条全部匹配 | PASS | api-supplementary.json |

### 9.5 任务详情

| 用例 ID | 模块 | 优先级 | 前置条件 | 用户操作步骤 | 预期结果 | 测试方式 | 实际结果 | 状态 | 证据 |
|---|---|---|---|---|---|---|---|---|---|
| QAR-TD-01 | 聚星详情 | P0 | 聚星真实任务 | 打开 `b9517e8b` | 平台/条件/1/1/1 正确；无 F06/精选 | 真实 UI+DB | b9517e8b 详情校验 | PASS | qa-detail-b9517e8b |
| QAR-TD-02 | 星图详情 | P0 | 星图真实任务 | 打开 `c30b7622` | 平台/条件/1/1/1；F06 保留 | 真实 UI+DB | c30b7622 详情校验 | PASS | qa-detail-c30b7622 |
| QAR-TD-03 | 历史任务 | P1 | 历史任务 | 打开 `6dff3c73` | 状态/计数与历史一致 | 真实 UI+DB | 6dff3c73 详情校验 | PASS | qa-detail-6dff3c73 |
| QAR-TD-04 | 失败任务 | P1 | 历史失败任务 | 打开失败任务 | 失败状态与原因可理解；无自动重试 | 真实 UI | 失败任务 076edee2 详情显示失败状态/原因 | PASS | qa-detail-failed |

### 9.6 统一达人库与详情

| 用例 ID | 模块 | 优先级 | 前置条件 | 用户操作步骤 | 预期结果 | 测试方式 | 实际结果 | 状态 | 证据 |
|---|---|---|---|---|---|---|---|---|---|
| QAR-LIB-01 | 星图库 | P0 | 已登录 | 打开星图达人库 | 20 位首屏、138 位总、筛选项正常 | 真实 UI+API | 星图达人库可读 | PASS | qa-lib-xingtu |
| QAR-LIB-02 | 聚星库 | P0 | 已登录 | 打开聚星达人库 | 1 位、聚星指标/原单位 | 真实 UI+API | 聚星达人库可读（1 位） | PASS | qa-lib-juxing |
| QAR-LIB-03 | 平台切换 | P0 | 达人库 | 切换平台 | 列表/文案/筛选项随平台变化 | 真实 UI | 平台切换后列表/文案切换 | PASS | qa-lib-juxing |
| QAR-LIB-04 | 聚星详情 | P0 | 聚星库 | 打开聚星达人详情 | 四章节/快手ID/缺失无 0/报价原值 | 真实 UI | 聚星达人详情四章节/无星图专属操作 | PASS | qa-lib-juxing-detail |
| QAR-LIB-05 | 星图详情 | P0 | 星图库 | 打开星图达人详情 | 既有章节/F06 保留 | 真实 UI | 星图达人详情/F06 保留 | PASS | qa-lib-xingtu-detail |
| QAR-LIB-06 | 筛选排序 | P1 | 聚星库 | 省份=山东/北京/清空 | 山东命中、北京空态、清空恢复 | 真实 UI+API | 聚星省份筛选（山东）命中 1 位 | PASS | qa-lib-shandong |
| QAR-LIB-07 | 空态 | P2 | 聚星库 | 筛选无结果 | 显示可理解空态，不显示 0 数据 | 真实 UI | 聚星库无结果时显示空态 | PASS | qa-lib-empty |
| QAR-LIB-08 | 一致性 | P1 | 任务详情/达人库 | 对比任务内达人与达人库 | 同一 creator/字段一致 | 真实 UI+DB | 聚星任务内达人与达人库一致 | PASS | qa-juxing-task-consistency |
| QAR-LIB-09 | 跨平台同名 | P1 | 主库 | 查两平台同名/同 ID | 不自动合并；真实数据无同名；隔离测试支持 | 只读 DB/隔离 | 真实数据无跨平台同名；身份唯一约束与聚星/星图表隔离成立 | PASS | db-baseline.json |

### 9.7 共享执行单元与隔离

| 用例 ID | 模块 | 优先级 | 前置条件 | 用户操作步骤 | 预期结果 | 测试方式 | 实际结果 | 状态 | 证据 |
|---|---|---|---|---|---|---|---|---|---|
| QAR-EU-01 | 双平台单元 | P0 | 执行单元页 | 查看单元 | 同一 unit-local-mac-02 显示双平台 | 真实 UI+API | 执行单元页显示同一单元双平台 | PASS | qa-units |
| QAR-EU-02 | 状态/心跳 | P1 | 执行单元页 | 查看状态/Worker/当前任务 | ONLINE、READY/空闲、无当前任务 | 真实 UI+API | 执行单元 ONLINE/空闲、无当前任务 | PASS | qa-units |
| QAR-EU-03 | 租约 | P2 | 主站空闲 | 查 DB 单元 | 无 owner/lease/current_task；browser_stopped | 只读 DB | READY；无 owner/lease/current_task；browser_stopped=true | PASS | db-baseline.json |
| QAR-EU-04 | Profile | P0 | 主站空闲 | 查 Profile 锁/绑定 | 两 Profile 独立、锁 FREE、账号正确 | 只读 | 星图/聚星 Profile 独立、锁 FREE；账号分别 1807978499337419 / 60821564 | PASS | db-baseline.json |
| QAR-EU-05 | 串行 | P0 | P5 证据 | 复核 polls/任务时间线 | 聚星执行时星图 QUEUED；同单元切换 | 真实证据/DB | P5 polls：聚星执行时星图 QUEUED；聚星完成后单元 current 切到星图 | PASS | P5 证据/DB |
| QAR-EU-06 | 数据隔离 | P0 | 主库 | 查跨平台身份/表 | 聚星 creator 不在星图表；星图不写聚星 | 只读 DB | 聚星 creator 在星图 current/index 均为 0 | PASS | db-baseline.json |

### 9.8 异常与人工接管

| 用例 ID | 模块 | 优先级 | 前置条件 | 用户操作步骤 | 预期结果 | 测试方式 | 实际结果 | 状态 | 证据 |
|---|---|---|---|---|---|---|---|---|---|
| QAR-ERR-01 | 子账号选择 | P1 | 真实未触发 | 查现有提醒/自动化测试 | 有明确提醒/接管；不静默 | 自动/只读 | 现有 ACCOUNT_SELECTION_REQUIRED 提醒/接管代码与自动测试通过；真实选择页本轮未触发 | PASS | 自动/只读；真实未触发 |
| QAR-ERR-02 | 账号不匹配 | P1 | 自动测试 | 复核 ACCOUNT_MISMATCH | 不自动改绑；原因明确 | 自动 | ACCOUNT_MISMATCH 不自动改绑；原因明确（自动测试） | PASS | 自动测试 |
| QAR-ERR-03 | 登录失效/验证 | P1 | 真实未触发 | 复核现有流程 | 任务等待+通知；超时原因 | 自动/历史 | 登录失效/安全验证等待与超时原因（自动/历史证据） | PASS | 自动/历史 |

### 9.9 Feature Flag、配置与恢复

| 用例 ID | 模块 | 优先级 | 前置条件 | 用户操作步骤 | 预期结果 | 测试方式 | 实际结果 | 状态 | 证据 |
|---|---|---|---|---|---|---|---|---|---|
| QAR-CFG-01 | 正常运行 | P0 | 主站 | 读双平台目录/绑定 | 均 enabled，无临时脚本依赖 | 真实 API/只读 | 正常配置双平台 enabled；绑定存在；无临时脚本依赖 | PASS | qa-round/platforms.json |
| QAR-CFG-02 | Flag=0 | P1 | 临时 API 8001 | 读目录/能力/创建聚星 | 入口/能力/创建拒绝；星图正常 | 隔离 API | 临时 API 8001 Flag=0：目录关闭，能力/创建 422；星图正常 | PASS | qa-round/flagoff-*.json |
| QAR-CFG-03 | Flag=0 数据 | P1 | 临时 API 8001 | 读既有聚星任务/达人库 | 仍可读，不删除 | 隔离 API | 既有聚星任务/筛选/达人库 200 可读；未创建新任务 | PASS | qa-round/flagoff-*.json |
| QAR-CFG-04 | 重启持久性 | P1 | 主站 | 复核 P6 重启证据/当前配置 | 重启后双平台仍启用 | 历史证据/只读 | 引用 P6 正常重启后双平台证据；本轮未重启主站 | PASS | JUXING-MAIN-01 验收 §14.4 |

### 9.10 数据库与历史兼容性

| 用例 ID | 模块 | 优先级 | 前置条件 | 用户操作步骤 | 预期结果 | 测试方式 | 实际结果 | 状态 | 证据 |
|---|---|---|---|---|---|---|---|---|---|
| QAR-DB-01 | 历史任务 | P0 | 主库 | compare 基线 | 历史任务/快照/精选/需求/更新资格无变化 | 只读 DB | compare：历史任务/关联/快照/需求/检查点/精选/更新资格无变化 | PASS | db-baseline.json |
| QAR-DB-02 | 授权变化 | P0 | 主库 | 归因 5 处差异 | 仅授权星图任务更新既有达人 | 只读 DB | 5 处差异全部归因于授权星图任务更新既有达人 6300acc0 | PASS | db-baseline.json/验收 §12 |
| QAR-DB-03 | 聚星数据 | P0 | 主库 | 查聚星行/4193 | 仅 1 位聚星达人；无 4193 导入 | 只读 DB | 主库聚星 1 位；4193 的 8 任务/39 达人均未导入 | PASS | db-baseline.json |
| QAR-DB-04 | 身份隔离 | P0 | 主库 | 查唯一约束/交叉表 | 跨平台不合并；无交叉行 | 只读 DB | 平台身份唯一；聚星 creator 不在星图 current/index；真实无同名 | PASS | db-baseline.json |
| QAR-DB-05 | 更新资格 | P1 | 主库 | 查 schedule | 90 行不变；聚星不在更新调度 | 只读 DB | creator_update_schedule 90 行不变；聚星无更新调度 | PASS | db-baseline.json |

### 9.11 自动化回归

| 用例 ID | 模块 | 优先级 | 前置条件 | 用户操作步骤 | 预期结果 | 测试方式 | 实际结果 | 状态 | 证据 |
|---|---|---|---|---|---|---|---|---|---|
| QAR-AUTO-01 | 后端 | P0 | 仓库 | unit+contract | 全部通过 | 自动 | backend unit+contract 409 passed | PASS | pytest |
| QAR-AUTO-02 | 集成 | P0 | 测试库 | integration | 全部通过（S3 可 skip） | 自动 | integration 121 passed / 1 skipped（S3 未配置） | PASS | pytest |
| QAR-AUTO-03 | E2E | P1 | 测试库/Temporal | e2e | 全部通过 | 自动 | E2E 14 passed | PASS | pytest |
| QAR-AUTO-04 | 前端 | P1 | 仓库 | lint/test/build | 全部通过 | 自动 | frontend 105 passed + lint + build；Mypy 38 files | PASS | npm/pytest |
