# OPS-05：启动磁力聚星隔离全栈供页面完整体验

状态：已完成  
更新时间：2026-10-31T01:08:00+08:00  
是否验收：是（本轮范围：聚星隔离栈启动、聚星入口/表单/达人库/队列可用；真实任务由用户在页面提交）

## 目标与范围

**目的**：用户要求启动磁力聚星（快手聚星）的爬取等服务，使网站上可以完整体验聚星采集流程。当前主站 `http://127.0.0.1:5173/` 的聚星 Feature Flag 关闭，且主业务库没有聚星执行单元绑定；为不向主业务库写入聚星数据，本轮启动项目既有的**聚星隔离全栈**：

- Temporal `57235`（独立 DB 文件）；
- 产品 API `4192`；
- Intake Worker、Collection Worker（执行单元 `unit-local-mac-02-kjx-full`）；
- 前端 `4193`（同一产品前端，`/api` 代理到 `4192`）；
- 测试库 `xingtu_test_kjx_regression`（PostgreSQL `55439`，与主库 `xingtu_development` 隔离）。

包含：

- 新增本机可复用启停入口 `.runtime/kjx-full/stack.sh`（`up|stop|restart|status`，gitignored）；
- 修复该入口的 `no_proxy` 方括号 IPv6 问题（httpx 0.28 会以 `Invalid port: ':1]'` 失败）；
- 修复主站 `scripts/dev.sh` 的 Worker 识别：按 `UNIT_CONFIG` 限定，避免双栈并存时把聚星 Worker 误判为重复并被 `up/restart` 结束；同步 `.runtime/dev-no-upd.sh`；
- 校验聚星平台开关、能力契约、任务表单、达人库、队列消费者与历史数据。

不做：

- 不改主站 `8000/5173` 的配置或 Feature Flag；不向 `xingtu_development` 写入聚星任务/达人；
- 不改采集业务代码、契约或迁移；仅为多栈并存调整 `scripts/dev.sh` 的 Worker 识别；
- 不启动定时更新调度器；
- 不代替用户提交新的真实采集任务（现有 T1/T2/T3 真实验收证据见 KJX-01）。

## 关联与依赖

- 前置：[KJX-01](KJX-01.md)（聚星 P0 实现与阶段 C/D-0 真实验收）、[OPS-04](OPS-04.md)（主站启动，聚星保持关闭）。
- 运行配置：`.runtime/kjx-full/regression/env`（独立 DSN/Redis DB15/Temporal 57235/Flag 开）、`.runtime/units/local-dev-mac-02.kjx-full.json`（聚星绑定 `60821564`、独立 Profile）、`contracts/kuaishou_juxing.verified.json`。
- 启停入口：`.runtime/kjx-full/stack.sh`（未提交，见证据）。

## 验收清单

- [x] Temporal 57235、API 4192、前端 4193、Intake/Collection Worker 均运行；`stack.sh status` 全绿。
- [x] `GET /api/auth/me` 401；前端 `http://127.0.0.1:4193/` 200。
- [x] `/api/platforms` 返回 `kuaishou_juxing.enabled=true`，契约 `juxing-video-creator-stage-c-v3`。
- [x] `/api/platforms/kuaishou_juxing/capabilities` 200，`juxing-video-square-stage-c-v2`，关键词/38 类目/粉丝/地域/三档报价可用。
- [x] 达人库 `?platform=kuaishou_juxing` 200，页面「磁力聚星达人 · 20 位已加载」，库内共 37 位聚星达人。
- [x] 任务中心显示既有聚星任务（4 条），任务表单可选择「磁力聚星 · 已验证可用」。
- [x] `xingtu-intake` 与 `xingtu-unit-local-mac-02-kjx-full` 各 1 个新鲜消费者；collection `generation=6`。
- [x] 聚星平台会话最近观测为 `VALID`（2026-10-30 22:52，`PROTECTED_PAGE_AND_URL_ACCOUNT_VERIFIED`），无未处理验证事件。
- [x] 主站 8000/5173 四进程保持不变，定时更新仍未运行。
- [x] 双栈并存时，`./dev.sh status` 与 `.runtime/dev-no-upd.sh status` 只识别主站 `unit-local-mac-02` 的 Worker，不再把聚星栈 Worker 误判为重复。

## 实现记录

1. 检查确认主站聚星 Flag 关闭、主库无聚星绑定；聚星测试库仍有 6 条任务（4 聚星 / 2 星图）、37 位聚星达人、独立 Profile 与快照。
2. 新增 `.runtime/kjx-full/stack.sh`：加载隔离 env + DeepSeek 凭据，启动 Temporal、API、Intake、Collection、Vite；记录 PID；提供 `status` 与 `stop`；队列检查复用 `worker_health`。
3. 首次启动时 Intake 因 `no_proxy` 含 `[::1]` 抛 `httpx.InvalidURL: Invalid port: ':1]'` 退出；在脚本 `load_env` 中加入与 `scripts/dev.sh` 相同的清理后重启。
4. 停止部分启动的栈，等待旧 Worker 45 秒心跳窗口后重新 `up`；最终 collection `generation=6`，两队列各 1 个新鲜消费者。
5. API 登录 `kjx-regression-media`，验证平台/能力/达人库/任务；Playwright 真实 Chromium 登录 `4193`，选择聚星并渲染表单与达人库。
6. 发现主站 `./dev.sh status` 把两栈同名 Worker 误判为「重复运行」，且 `up/restart` 会把聚星 Worker 当成重复进程结束；把 `worker_pattern` 按 `UNIT_CONFIG` 限定为当前执行单元，并同步 gitignored 的 `.runtime/dev-no-upd.sh`。`bash -n` 与两栈 `status` 验证通过，主站仍各 1 个 Worker。

## 验证证据

- 时间与环境：2026-10-31 01:02—01:08（Asia/Shanghai），本机隔离栈，测试库 `xingtu_test_kjx_regression`。
- 进程：Temporal `75877`、API `75897`、Intake `75916`、Collection `75925`、Vite `75953`。
- 页面：`http://127.0.0.1:4193/`；登录账号 `kjx-regression-media`，口令见 `.runtime/kjx-full/regression/credentials`（未打印）。
- API：`/api/platforms` 聚星 `enabled=true`；`/api/creator-library?platform=kuaishou_juxing` 200；`/api/tasks?limit=5` 返回聚星任务 `56efbba5…` `COMPLETED 22/22/22`。
- UI 截图（私有）：`.runtime/kjx-full/regression/ops05/01-tasks.png`、`02-juxing-form.png`、`03-juxing-library.png`。
- 多栈 Worker 识别：`bash -n scripts/dev.sh`、`bash -n .runtime/dev-no-upd.sh` 通过；`./dev.sh status` 与 `.runtime/dev-no-upd.sh status` 均只显示主站 `intake-worker` 69701 / `collection-worker` 71225，未把聚星栈 75916/75925 计为重复。
- 详细记录：[OPS-05 聚星隔离栈启动验证](../evidence/OPS-05-juxing-stack-2026-10-31.md)。

## 交接信息

- 聚星体验入口：`http://127.0.0.1:4193/`；主站 `http://127.0.0.1:5173/` 仍是星图，不受影响。
- 双栈并存已安全：`./dev.sh up/restart` 不再结束聚星 Worker；主站保持「不启动定时更新」时继续用 `.runtime/dev-no-upd.sh`（两者均已按单元配置识别 Worker）。
- 启停：`./.runtime/kjx-full/stack.sh status|stop|restart`。停止不影响主站与数据库。
- 未代替用户提交真实任务；页面表单已可用。若首单提示子账号选择/登录/挑战，按页面或既有维护流程处理（聚星绑定子账号 `60821564` / cpg果汁）。
- 聚星栈使用测试库与测试账号，达人/任务数据与主站隔离；如需把聚星入口并入主站，需要主库绑定与 Feature Flag 变更（会向 `xingtu_development` 写入聚星数据），应另行确认。
- 本轮未改业务代码、契约、迁移；未运行测试套件。

## 状态历史

- 2026-10-31 01:02 新建：接用户「启动磁力聚星爬取等服务、网站需要完整体验」请求；建立隔离栈启动入口并进入进行中。
- 2026-10-31 01:08 进行中 → 已完成：聚星栈五进程、页面/表单/达人库/队列/会话验证通过；主站保持不变。
