# DEV-01：星采本地全栈一键启停入口

状态：已完成  
更新时间：2026-10-14T10:10:00+08:00  
是否验收：是（本轮范围内全部验收项均有证据；不涉及平台新能力核验）

## 目标与范围

让操作者在本机终端用**一条命令**唤起「星采」前后端并访问页面体验，用一条命令干净停止。

包含：

- 新增根目录入口 `./dev.sh`（实现 `scripts/dev.sh`），提供 `up` / `stop` / `restart` / `status` / `logs` / `check`。
- `up`：确保依赖服务 → 复用 `scripts/m3_up.py --check` 做前置自检 → 启动/接管后端 API、P1 Intake Worker、P2 采集 Worker、前端 Vite 页面 → 校验 HTTP 与队列消费者新鲜度 → 打印中文就绪信息（页面地址、后端地址、登录、日志与停止方式）。
- `stop`：只停止本脚本记录（含接管）的进程，并连同 `npm run dev` 的子进程一起结束；绝不结束未记录的进程。
- `status`：进程、端口、HTTP、Temporal 队列消费者新鲜度与各日志末行。

不做：

- 不改变 `Makefile`、`scripts/m3_up.py` 的既有契约与行为，不新增第二套启动真相。
- 不绕过前置自检（`EXECUTION_UNIT_READY` 等门槛保持原样）。
- 不停止 Docker 依赖服务（仍由 `make stop` / `./.runtime/dev-up.sh stop` 负责）。
- 不改前端页面、API、契约、迁移或采集逻辑。

## 关联与依赖

- 命令契约：[开发规范](../agent.md)第 3.1 节；启动事实来源：[开发与运维说明](../development.md)「2026-10-11 M3 完整运行链路启动」。
- 前置：BASE-01（工程与命令入口）、INTAKE-01（`make m3-up` 与 Intake Worker 修复）、CONSOLE-01（产品前端）。
- 复用：`scripts/m3_up.py`（前置自检与就绪判据）、`.runtime/m3-app.env`、`.runtime/deepseek.env`、`.runtime/units/local-dev-mac-02.json`。
- 关联：LIB-01（本轮页面体验对象为「星采 · 媒介工作台」的任务中心与达人库）。

## 验收清单

- [x] `./dev.sh up` 能在依赖已就绪、前置自检通过后启动 API、两个 Worker 与前端，并给出可访问地址（首次实跑即全部就绪）。
- [x] `./dev.sh stop` 能停止全部四个进程（含 API 与前端 `npm run dev` 的子进程），且不停数据库/对象/profile；端口释放。
- [x] `./dev.sh status` 正确显示进程、端口、HTTP 与队列消费者新鲜度，不把「脚本自身进程」误报为重复 worker。
- [x] `./dev.sh up` 可重复执行：已在运行的进程被接管而非叠加，重复 worker 会被清理为每账号一个。
- [x] 真实浏览器（Playwright + 本机 Chrome）登录 `media-a` 后，任务中心与达人库页面可访问、数据可加载。
- [x] 不回归既有命令：`scripts/m3_up.py --check` 仍为 `PREFLIGHT_OK`；`Makefile` 未改动。

## 实现记录

2026-10-14：新增 [scripts/dev.sh](../../scripts/dev.sh) 与根目录转发入口 [dev.sh](../../dev.sh)（`chmod +x`）。

关键实现点：

1. **一条命令覆盖四个进程**：`make m3-up` 默认只启动 API + Intake Worker，采集 Worker 与前端需额外 `M3_UP_FLAGS`；`dev.sh` 默认全部启动，缺 P2 时任务会停在 `QUEUED`，缺前端则没有页面。
2. **接管而非叠加**：`up` 对 API/前端按监听端口接管并记录 PID；对 Worker 按进程签名清点，0 个则启动、1 个则接管、多个则保留被记录的一个并明确报告后结束其余。Worker 必须「每账号一个」：重复的 Intake Worker 会重复派发，重复的采集 Worker 会在同一 profile 上互斥打架。
3. **精确识别 Worker**：仅用 `pgrep -f` 会匹配到命令行含同一字符串的其它进程（本脚本自身的 bash 曾把自己误报成重复 worker）。`worker_pids` 再用 `lsof -c Python -F p` 交集确认该 PID 确实在跑本项目的 Python 解释器。
4. **stop 处理子进程树**：`npm run dev` 会把真正的 Vite 生成为子进程，只 kill npm 会留下继续占用 5173 的孤儿。`stop_pid` 递归收集子进程一并结束；只停止本脚本记录过的进程，端口被外部进程占用时明确提示而不擅自 kill。
5. **环境处理沿用既有做法**：加载 `.runtime/m3-app.env` 与 `.runtime/deepseek.env`，沿用 `no_proxy` 方括号 IPv6 清理（httpx 0.28 会抛 `InvalidURL`），沿用 `.runtime/units/local-dev-mac-02.json`。
6. **就绪判据复用**：前置自检直接调用 `scripts/m3_up.py --check`；队列消费者新鲜度复用 `xingtu.worker_health.check_queues`，不新增阈值。

## 验证证据

证据汇总：[DEV-01 启停入口验证证据](../evidence/DEV-01-launcher-2026-10-14.md)。

- 2026-10-14 09:51～09:56（本地 macOS，真实开发库 + Compose 依赖 + 真实 Chrome 采集 Worker）：`./dev.sh status` 报全部在线；`./dev.sh up` 首次实跑 5 秒内四进程全部就绪；`./dev.sh restart` 完整停启一次，旧 PID（12114/3442/17861 等）全部退出，新 PID 接管；`./dev.sh up` 重复执行仅接管不叠加。
- 前置自检：`PREFLIGHT_OK`，13 项全 ok（迁移 v11、Temporal、注册表 live、单元 `READY`、`deepseek-flash` 可用）。
- 队列消费者：`xingtu-intake` 与 `xingtu-unit-local-mac-02` 均 `在线`，最老刷新秒级。
- 页面验收（Playwright + 本机 Chrome）：登录 `media-a` 后 `/tasks` 显示 21 行、`/creators` 显示「20 位已加载」，截图见证据；控制台仅一条 `401`（登录页初始调用 `/api/auth/me`，预期）。
- 本轮未执行：`./dev.sh stop` 后端口释放的独立复核（`restart` 隐含验证）；`logs` 子命令未单独实测。
- 2026-10-16 08:35～08:37（本地 macOS，真实开发库 + Compose 依赖，Git `ee11254` + 未提交改动 120 项）：按用户要求做**全栈重启**。`./dev.sh stop` → 人工结束 4 个游离进程 → `./.runtime/dev-up.sh down && up`（五个依赖容器重建，healthy）→ `./dev.sh up`：`PREFLIGHT_OK` 12 项、四进程新 PID（api 93446 / frontend 93496 / intake 93470 / collection 93487）5 秒内就绪、两个 Temporal 队列消费者均在线。业务只读抽查：`login(media-a)` 200、`/api/auth/me` 200、`/api/tasks` 20 条、`/api/creator-library` 20 条、`/api/platforms/douyin_xingtu/capabilities` 200、`/api/health/workers` 200、前端 `/` 200。**未运行测试套件、未做浏览器页面级验收**。**新发现（未修，属实现变更需先确认）**：`dev.sh stop` 存在 PID 记录盲区——重启前 API 真实监听者 92119 与另一终端启动的前端（16198/16219）均非脚本记录者，`stop` 按设计只打印端口占用提示、不结束它们，需人工清理。详见[重启证据](../evidence/DEV-01-restart-2026-10-16.md)。
- 2026-10-16 09:00～09:04（本地 macOS，Git `ee11254` + 未提交改动 121 项）：用户**再次要求重启**（供测试验收）。起始状态与上一轮不同：四个应用进程全部不存在、六个端口全部空闲、**Docker 守护进程 UNAVAILABLE**（Docker Desktop 被退出）。执行：`open -a Docker` → 轮询 `docker info` **30 秒内就绪**（server 29.1.3）→ `./.runtime/dev-up.sh up`（五个容器，两个 postgres healthy）→ `./dev.sh up`：`PREFLIGHT_OK` 12 项、四进程新 PID（api 94968 / intake 94992 / collection 95009 / frontend 95018）就绪、两个 Temporal 队列在线。**本轮专项核对**：`pids.tsv` 四个 PID 与真实进程逐一对应且全部存活（上一轮登记的记录盲区未复现），5174 未监听、前端稳定在 5173。业务只读抽查：`login(media-a)` 200（不带 `Origin` 头时为 403，属 `require_origin` 预期防护）、`/api/auth/me` 200、`/api/tasks` 20 条、`/api/creator-library` 20 条、`/api/health/workers` 200、`capabilities` 200，四进程日志末 3 行 0 条错误。**仍未运行测试套件、未做浏览器页面级验收**。

## 交接信息

- `dev.sh` 不负责依赖服务（Docker）的启停，仍需 `make stop`；依赖未起时由 `m3-up --check` 的 `DATABASE_REACHABLE` / `TEMPORAL_REACHABLE` 明确报错。
- **前置条件（2026-10-16 补记）**：依赖容器要求 **Docker 守护进程已运行**。本机 Docker Desktop 被退出时 `docker info` 报 `dial unix .../docker.sock: no such file`，此时须先 `open -a Docker` 并等待 `docker info` 成功（实测约 30 秒），再执行 `./.runtime/dev-up.sh up` 与 `./dev.sh up`；否则前置自检会在 `DATABASE_REACHABLE` / `TEMPORAL_REACHABLE` 失败收口。
- 若改用交互式终端前台运行 `npm run dev`，Vite 与 npm 可能不在同一进程组；本脚本用子进程树递归处理，但外部终端遗留的 Vite 不会被自动接管（`stop` 会提示端口占用者 PID）。
- **已知盲区（2026-10-16 记录，未修）**：若 API/前端/Worker 由 `dev.sh` 以外的方式启动（或换过启动方式），`.runtime/dev/pids.tsv` 里的 PID 会与真实监听者不一致，此时 `stop` 只打印端口占用提示而不结束该进程。规避方式：重启前先用 `./dev.sh status`（会显示「非本脚本启动」）或 `lsof -nP -iTCP:8000 -sTCP:LISTEN -t` 核对真实监听者，必要时人工结束后再 `./dev.sh up`。是否需要让脚本自动纠正记录，需单独确认。
- 遗留（非本卡）：LIB-01 的 F09 指定达人刷新仍无入口；LIB-01 页面级验收本轮借 `dev.sh` 提供了可访问环境，验收结论由 LIB-01 卡片维护。

## 状态历史

- 2026-10-14T09:45:00+08:00：建立 → 进行中；用户要求可在终端自行唤起前后端并访问「星图」网页体验。
- 2026-10-14T10:05:00+08:00：进行中 → 已完成；入口实现、真实停启与浏览器页面验收完成，证据见 `docs/evidence/DEV-01-launcher-2026-10-14.md`。
- 2026-10-16T08:40:00+08:00：保持已完成；追加本轮全栈重启与就绪复核证据（四进程 + 依赖容器 + 只读业务抽查），并登记 `stop` PID 记录盲区为已知问题（未改代码，未影响原验收）。证据见 `docs/evidence/DEV-01-restart-2026-10-16.md`。
- 2026-10-16T09:05:00+08:00：保持已完成；追加第二轮重启证据（含 Docker Desktop 恢复步骤、PID 记录一致性专项核对、只读业务抽查），并在交接信息补记「依赖容器要求 Docker 守护进程已运行」这一前置条件。未改代码。
