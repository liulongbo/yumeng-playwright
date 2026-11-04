# DUAL-UNIT-01：巨量星图与磁力聚星专属执行单元拆分

状态：**待验收**  
建立时间：2026-11-03T12:00:00+08:00  
最近更新：2026-11-03T21:35:00+08:00  
是否验收：**否（核心目标 GO，待你验收）**

## 目标与范围

把当前共享单元 `unit-local-mac-02`（巨量星图 + 磁力聚星双绑定、单 Worker、`max_concurrent_activities=1`）拆为两个专属执行单元：

- `unit-local-mac-02`：巨量星图专属，保留原账号、Profile、登录态、历史任务与 Temporal 队列。
- `unit-local-mac-03-juxing`：磁力聚星专属，新增独立账号引用、复制独立 Profile、独立快照、独立 Temporal 队列与独立 Collection Worker。

目标行为：

- 不同平台任务可同时进入真实采集执行；同一平台内部仍严格串行（每单元并发 1）。
- 平台任务只进入对应平台专属单元，不跨平台误派。
- 一个单元/Worker/Chrome 故障不无故终止另一个单元。
- 两单元共用当前本机 IP/网络出口；不新增代理或线路。

范围：

- 最小路由/兼容代码：按平台解析执行单元、平台专属单元注册、历史任务重试/继续重解析、单平台聚星释放状态修正、Intake 加载已声明但执行禁用的平台 registry。
- 运行配置：新增聚星单元配置；星图单元配置把聚星 binding 置为 `enabled=false`；复制聚星 Profile 并核验会话。
- 启动脚本：`scripts/dev.sh` 与 `scripts/m3_up.py` 支持双单元、双 Collection Worker、双队列就绪检查。
- 测试与证据：离线单元/集成测试；真实 5173 双平台小样本并行/串行验收；失败隔离；历史兼容与回滚核对。

明确不做：

- 不提高单平台并发；不新增 IP/代理；不重构数据库；不新增调度系统。
- 不改采集逻辑、Adapter、契约、字段解析、筛选转换、任务中心/达人库业务、前端业务页面。
- 不重写历史任务/快照；不删除旧执行单元；不覆盖旧 Profile/登录态。
- 不做 Git commit/push/merge（除非另行授权）。

## 关联与依赖

- 方案与调研：本轮第一阶段输出（现状调研、PRD、技术方案、测试用例）。
- 决策记录：[DEC-020 双平台专属执行单元拆分](../decisions/DEC-020-two-platform-dedicated-execution-units.md)。
- 前置事实：[JUXING-MAIN-01](JUXING-MAIN-01.md)（同一单元双平台串行验收）、[OPS-04](OPS-04.md)（本机原生栈启动）。
- 相关代码：
  - `backend/src/xingtu/worker.py`（队列、并发、派发）
  - `backend/src/xingtu/product_repository.py` / `intake_worker.py`（P1→P2 单元分配）
  - `backend/src/xingtu/browser_host.py` / `runtime.py`（租约、BrowserHost、Profile）
  - `backend/src/xingtu/repository.py` / `product_queries.py`（单元选择、命令/重试）
  - `scripts/dev.sh` / `scripts/m3_up.py`（启动与就绪）
- 不适用：F04/F05/F06 采集实现、聚星 Adapter/契约、前端任务中心。

## 验收清单

### A. 执行单元初始化

- [x] 新增 `unit-local-mac-03-juxing` 单元并注册成功。
- [x] 旧 `unit-local-mac-02` 保留星图账号/Profile/绑定/历史任务；仅聚星 binding 禁用。
- [x] 新单元仅聚星 binding；账号 `60821564`；新 Profile/快照路径。
- [x] 两单元各自 1 个 Collection Worker、各自 1 条 Temporal 队列新鲜消费者。
- [x] 两 Chrome/Profile/实例/租约独立；无 `PROFILE_IN_USE`、无调试端口冲突。
- [x] 两单元会话分别 VALID 且账号精确匹配；登录态未被覆盖。
- [x] 执行单元管理页正确展示两个单元。

### B. 任务路由

- [x] 星图任务全部进入 `unit-local-mac-02`。
- [x] 聚星任务全部进入 `unit-local-mac-03-juxing`。
- [x] 无跨平台误派；单元不可用时任务按既有规则等待/失败。
- [ ] 手动/定时更新仍由星图单元认领；聚星单元不误领（真实手动更新未执行）。
- [x] 历史聚星任务 retry/continue 重新解析到新单元（隔离集成测试；真实历史任务未点击）。

### C. 并行与串行

- [x] 星图单任务独立采集通过。
- [x] 聚星单任务独立采集通过。
- [x] 星图与聚星任务真实采集 activity 区间重叠（非仅页面显示运行中）。
- [x] 星图两个任务串行；聚星两个任务串行。
- [x] 双平台各两个任务：跨平台并行、平台内串行、无跨平台阻塞。
- [x] 一个任务结束后，同平台后续任务按既有调度规则启动。

### D. 数据与状态

- [x] P1 需求转换、任务谱系、dispatch、状态机正确。
- [x] 两平台达人数据/快照/精选/达人库/详情正确，无跨平台混写。
- [x] 无重复入库、无状态错乱；失败/重试语义不变（挑战恢复出现一次既有 LEASE_LOST，已记录）。
- [x] 数据库无死锁/长等待；租约/Worker/审计收尾正确。

### E. 异常与隔离

- [x] 一个 Worker 停止时，另一个单元任务继续。
- [ ] 一个 Chrome 关闭时，另一个单元任务继续（未执行强制关闭演练）。
- [ ] 一个单元会话失效/隔离不阻塞另一个单元（未执行会话失效/QUARANTINED 演练；真实滑块挑战期间另一平台未受影响）。
- [x] 两 Profile/登录态/验证/接管互不干扰。
- [x] 共享网络/Temporal/DB 故障边界明确记录。

### F. 历史与回归

- [x] 既有星图历史任务/快照/精选/达人库不变。
- [x] 既有聚星历史任务可读、不重写。
- [x] 自动回归：后端 lint/format/typecheck/unit/contract/integration/e2e、前端 lint/test/build（lint/format 仅既有 scripts/acceptance 11 个 UP031/4 个未格式化文件）。
- [x] 全栈重启后两单元/两 Worker/两队列持久恢复（首次 restart 撞既有 45 秒去重窗口，等待后 up 成功）。
- [ ] 回滚核对（恢复旧配置→单 Worker→旧串行）通过（未执行完整回滚演练；备份完整）。
- [x] 文档、命令、证据一致；无凭据/未脱敏平台正文进入仓库。

## 实现记录

- 2026-11-03T12:00：建立卡片；方案获用户批准；进入第二阶段实现（代码/脚本/离线测试）。尚未执行真实切换与采集。
- 2026-11-03：完成最小代码改动：
  - `runtime.py`：`enabled_platforms`、`is_multi_platform`；平台专属配置不再借用旧星图身份。
  - `browser_host.py`：按“另一平台 binding 是否启用”决定释放 disposition；单平台聚星使用真实状态。
  - `repository.py`：`select_collection_unit(platform)`；`register_unit(..., register_xingtu_binding=False)`；`_save` 同步写 `root_tasks.unit_id`；`command` retry/continue 重解析。
  - `intake_worker.py`：P1 晋级按 `plan.platform` 解析专属单元。
  - `product_cli.py`：Intake 加载已声明但 `enabled=false` 的平台 registry（损坏时仅告警）。
  - `product_queries.py`：API 侧 retry/continue 重解析并写回 `root_tasks.unit_id`。
  - `cli.py`：`register-unit` 按 `active_platform` 跳过隐式星图 binding。
  - `scripts/dev.sh`：双单元配置、双 Collection Worker、双队列状态/停止/就绪检查、`SKIP_UPDATE_SCHEDULER`。
  - `scripts/m3_up.py`：默认改为主站星图配置；`--extra-unit-config`；额外单元预检/启动/就绪；任一 Collection Worker 退出不终止另一单元。
- 2026-11-03：完成独立回归测试（Playwright MCP + Chrome）：
  - UI 回归：执行单元两行/汇总/脱敏、任务中心平台筛选（星图 20 行、聚星 12 行）、两平台任务详情、新建任务双平台表单/目标约束、两平台达人库/达人详情、未登录 401 + 真实登录；全部 PASS。
  - 动态回归：4 条真实 target=1 任务（星图 A/B、聚星 C/D）全部 COMPLETED 1/1；A/B、C/D 串行（衔接 0.002 秒）；A/C 真实 activity 重叠 34.84 秒；每 unit 最大活动采集 1；平台字段正确。
  - 历史回归：旧聚星 3 条历史仍为 `unit-local-mac-02`、`updated_at` 未变；无重写。
  - 首次 UI 回归唯一失败为测试脚本断言错误（详情页用 `星图ID`/`快手ID` 而非标题前缀），仅修测试脚本后复跑全部 PASS；未改产品代码/核心流程。
- 2026-11-03：完成真实切换与双平台验收：
  - Gate B 获用户确认；备份业务库/配置/快照；复制聚星 Profile 到独立路径；`session-diagnostics` 确认新单元 `VALID`、账号 `60821564`、快照恢复；`register-unit` 新单元无隐式星图 binding；启动双 Worker 后旧聚星 binding 禁用、新 binding 启用。
  - 13 条真实任务全部 `COMPLETED`、各 1/1、平台字段正确；新星图任务 6 条全部旧 unit，新聚星任务 7 条全部新 unit。
  - 干净并行对 `c847f162`（星图）与 `c68f54ff`（聚星）activity 重叠 **65.99s**，66 个 1 秒采样点两 unit 同时 collecting；两 Profile 同时 BUSY、Singleton PID 38271/38358 不同。
  - 双平台各两任务：A `817e0fcc` / B `2165d3ff` 串行（B 在 A 完成后 0.002s 开始），C `8d326bd4` / D `aec4f5c1` 串行（D 在 C 完成后 0.003s 开始）；A 与 C 真实重叠；每 unit 最大活动采集 1。
  - 两方向 Worker 离线/重启：离线期间对应平台任务 QUEUED、另一平台任务持续；重启后任务执行完成。
  - 真实星图滑块挑战：接管 ACTIVE → 用户完成 → RESUMED/事件 RESOLVED；任务出现一次既有 `WAITING_FOR_RESOURCE: LEASE_LOST`，Workflow 30s 重试后完成。
  - 全栈 restart 首次撞 45s 去重窗口（既有），等待后 up 成功；两单元/两 Worker/两队列恢复。
  - 报告：[DUAL-UNIT-01 真实切换与验收证据](../evidence/DUAL-UNIT-01-live-acceptance-2026-11-03.md)。
- 2026-11-03：只读预检本机开发库（服务为原生 PostgreSQL 18.3，schema 20）：
  - 当前唯一单元 `unit-local-mac-02`：`READY`、无 owner/lease、`browser_stopped=true`、`allowed_task_kinds` 三项、`generation=164`。
  - 旧 binding：星图 `enabled=true`、聚星 `enabled=true`；旧聚星 binding 字段与 `.runtime/units/local-dev-mac-02.json` 完全一致。
  - 无在途任务；无 takeover/verification event；聚星历史任务 3 条（均终态）。
  - 本阶段未注册新单元、未复制 Profile、未启动应用 Worker、未执行真实采集。

## 验证证据

- 离线实施与回归报告：[DUAL-UNIT-01 离线实施与回归证据](../evidence/DUAL-UNIT-01-offline-verification-2026-11-03.md)。
- 2026-11-03 离线回归（本机，macOS；PostgreSQL 18.3 `xingtu_test`；未启动应用 Worker）：
  - 后端单元：`.venv/bin/pytest backend/tests/unit -q` → **375 passed**。
  - 后端合同：`.venv/bin/pytest backend/tests/contract -q` → **43 passed**。
  - 隔离 PostgreSQL 集成：`XINGTU_TEST_DATABASE_URL=...xingtu_test` + `.venv/bin/pytest backend/tests/integration -q` → **122 passed / 4 skipped**。
  - E2E（真实 Temporal 测试服务器 + 本地 `temporal` 二进制 + Redis 6379 + 测试库）：`PYTHONPATH=... XINGTU_TEMPORAL_TEST_BINARY=.runtime/local-main/bin/temporal .venv/bin/pytest tests/e2e -q` → **14 passed**。
  - 前端：`npm --prefix frontend run lint`（tsc）通过；`npm --prefix frontend test -- --run` → **106 passed**；`npm --prefix frontend run build` 通过。
  - Mypy：`.venv/bin/mypy backend/src` → **Success: no issues found in 38 source files**。
  - Ruff（本轮改动文件）通过；仓库 `scripts/acceptance` 仍有既有 11 个 UP031 与 4 个未格式化文件，非本轮引入，未改动。
- 回归测试文档：[DUAL-UNIT-01 回归测试用例与结果](../evidence/DUAL-UNIT-01-regression-test-2026-11-03.md)；UI 报告 `.runtime/dual-unit-acceptance/regression-ui-20261103-rerun/report.json`；动态报告 `.runtime/dual-unit-acceptance/regression-two-each-20261103/report.json`；公开截图 `docs/evidence/assets/dual-unit/regression/`。
- 真实切换与验收报告：[DUAL-UNIT-01 真实切换与验收证据](../evidence/DUAL-UNIT-01-live-acceptance-2026-11-03.md)；原始 sampler/report/screenshots 在 `.runtime/dual-unit-acceptance/`，公开脱敏截图在 `docs/evidence/assets/dual-unit/`。
- 结论：**核心目标 GO**；未执行的 P1/可选演练（Chrome 强制关闭、会话失效、取消、手动更新、完整回滚、资源 RSS）见报告 §10。

## 已知风险与边界

- 切换窗口内必须排空非终态任务；否则可能出现在途任务停留旧单元。
- 聚星 Profile 复制后会话可能仍有效，也可能需要人工登录/选择子账号；以只读诊断结果为准，不得伪造。
- 两单元共用本机网络出口；网络/DB/Temporal/Redis 故障会同时影响两平台，这是明确共同依赖，不是单元隔离缺陷。
- `dev.sh up` 是完整栈启动：主单元 `LEASED` 时会被前置自检的 `EXECUTION_UNIT_READY` 拒绝，不能直接用于“只重启另一个单元”；本轮用 CLI 单独启动缺失 Worker 验证隔离。后续可增加单 Worker 启停入口。
- `dev.sh restart` 首次可能撞上一代 Worker 45 秒心跳去重窗口；等待后再次 `up` 已成功。
- 已知“长任务后 activity 启动延迟”问题作为观察项，不宣称本轮修复。
- 执行单元页对 `NEEDS_LOGIN/SESSION_UNVERIFIED` 显示原始状态枚举；本轮不强制修改前端，只验证平台/账号/Worker 展示正确。

## 交接信息

- 当前阶段：真实切换与核心验收完成，状态 `待验收`。两单元当前 `READY`；星图 Worker generation 17、聚星 Worker generation 3；三条队列新鲜；`update-scheduler` 保持关闭；前端/API 运行中。
- 核心 GO：跨平台真实并行、同平台串行、无错误路由、两平台数据/页面正确、历史不重写、两方向 Worker 离线/重启隔离。
- 未完成/待你决定：Chrome 强制关闭、会话失效、单任务取消、手动更新真实回归、完整回滚演练、精确资源测量；真实星图挑战恢复的一次既有 `LEASE_LOST` 是否另立任务修复；执行单元页中文状态映射是否纳入后续。
- 回归测试已补：UI 24 项检查 PASS；动态 4 任务并行/串行/数据 PASS；历史未重写。测试文档见 `docs/evidence/DUAL-UNIT-01-regression-test-2026-11-03.md`。
- 未提交 Git；工作区既有未提交文档未被覆盖。**注意：工作区另有并发任务 DUAL-70-01 的未提交改动（`product_api.py`/`product_models.py`/新卡片等），非本轮修改，未回退、未纳入本轮证据。**

## 状态历史

- 2026-11-03T12:00：待办 → 进行中；方案获批准，开始最小代码/配置/测试改造。
- 2026-11-03T20:40：进行中 → 进行中；代码/脚本改造与离线回归完成，未执行真实切换；等待 Gate B（停机窗口、两会话/人工登录、Playwright MCP）。
- 2026-11-03T21:20：进行中 → 待验收；Gate B 获确认，完成真实切换、13 条真实任务、跨平台并行 65.99s、同平台串行、两方向 Worker 离线隔离、真实挑战/接管、全栈重启；核心目标 **GO**。未执行项见报告 §10，等待用户验收。
- 2026-11-03T21:35：待验收 → 待验收（回归补充）；独立 UI + 动态回归全部 PASS，未发现本轮修改引入的产品缺陷；唯一失败为测试脚本断言错误并已修正。
