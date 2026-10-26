# OPS-03：本机全栈服务重启（跳过自动更新）

状态：已完成  
更新时间：2026-10-26T20:03:00+08:00  
是否验收：是（本轮范围：四个应用进程重启与基础可达性；业务体验验收由用户执行）

## 目标与范围

**目的**：按用户要求重启本机「星采」全部应用服务，便于继续在前端操作，**不启动自动更新**。

包含：

- 停止并重启 API、P1 Intake Worker、P2 采集 Worker、前端 Vite 四个应用进程；
- 保留 PostgreSQL/Redis/Temporal 依赖与全部业务数据，不重建、不迁移、不清库；
- 重启后校验进程、端口、HTTP、Temporal 队列消费者与 PID 记录。

不做：

- 不启动定时更新调度器（`xingtu-product update-scheduler`）；
- 不改业务代码、契约、迁移、单元配置与调度逻辑；不发起真实采集；
- 不启停依赖服务（`make dev` / `.runtime/dev-up.sh` 边界不变）。

## 关联与依赖

- 前置：[OPS-02](OPS-02.md)（同一运行栈的历史重启记录）、[DEV-01](DEV-01.md)（`./dev.sh` 启停入口）。
- 命令契约：[开发规范](../agent.md)第 3.1 节；运行事实来源：[开发与运维说明](../development.md)。
- 本次入口：`.runtime/dev-no-upd.sh`（`scripts/dev.sh` 的本地变体：跳过 `update-scheduler`，前置自检 FAIL 时告警继续；gitignored，未改仓库代码）。本次自检实际为全部 `ok`，未使用该放行分支。

## 验收清单

- [x] API、intake-worker、collection-worker、前端各 1 个进程运行；`.runtime/dev/pids.tsv` 记录实际 PID。
- [x] `GET /api/auth/me` → 401；`http://127.0.0.1:5173/` → 200。
- [x] `xingtu-intake` 与 `xingtu-unit-local-mac-02` 各 1 个新鲜消费者；日志显示对应 Worker 轮询。
- [x] `update-scheduler` 重启前后均未运行。
- [x] 重启未影响在途任务：112 条 `root_tasks` 全为终态（CANCELLED 23 / COMPLETED 19 / FAILED 11 / FAILED_VALIDATION 1 / PARTIAL_COMPLETED 59），最后更新 2026-10-24 15:58；19:55 后 0 条状态变更；单元 `READY`、无 owner/lease、`browser_stopped=true`。
- [x] PostgreSQL/Redis/Temporal 依赖未重启；业务数据未改动；MinIO 59000 保持空闲。
- [x] 未改代码、契约、迁移、单元配置；未发起真实采集。
- [x] 重启后队列消费者的短暂 TTL 残留已核实并回落，不把旧 poller 当成重复 Worker。

## 实现记录（执行记录）

1. 19:59:15 执行 `./.runtime/dev-no-upd.sh restart`。停止 API 12680、intake 27814、collection 21368、前端 27861；前置自检 12 项全 `ok`。
2. 启动 API 24614、intake 24651、collection 24668、前端 npm 24678；`update-scheduler` 跳过。
3. collection 24668 因旧 Worker 45 秒心跳窗口以 `DUPLICATE_WORKER_FOR_UNIT` 退出（旧进程已停止，属启动竞态）。
4. 20:00:12 执行 `./.runtime/dev-no-upd.sh up`：接管 API/intake/前端，collection 25026 启动，`generation=8` 正常轮询。
5. 20:02:41 复核：四进程稳定，两队列各 1 个新鲜消费者；`update-scheduler` 仍未运行。
6. 只读核对业务库：`root_tasks` 112 条全部终态，最后更新 2026-10-24 15:58，19:55 后无变更；`execution_units` 中 `unit-local-mac-02` 为 `READY`、owner/lease 为空、`browser_stopped=true`。

## 验证证据

- 2026-10-26 19:59—20:02（Asia/Shanghai），`main@f52b7fb`，单机原生运行栈，真实依赖，未发起采集。
- 命令与逐项结果：[OPS-03 重启与可达性验证](../evidence/OPS-03-local-restart-2026-10-26.md)。
- 关键结果：API 401、前端 200、四进程各 1、两队列在线且各 1 个新鲜消费者、`update-scheduler` 未运行。
- 未执行：`media-a` 登录、业务读接口、封面与页面渲染复测；未运行测试套件（无代码改动）。

## 交接信息

- 业务体验验收由用户执行；异常先查 `.runtime/logs/` 对应日志。
- `update-scheduler` 保持关闭：需要时按 [OPS-02](OPS-02.md) 交接命令启动，启动后会立即处理到期达人并占用执行单元。
- 已知入口竞态：`restart` 后立即启动 collection 会撞上 45 秒旧心跳窗口；本次通过再次 `up` 恢复。若需一键稳定重启，应修改入口增加等待/重试并补验证（本次未改）。
- `.runtime/dev-no-upd.sh` 在前置自检 FAIL 时只告警继续；严格自检仍用 `./dev.sh check` 或 `scripts/m3_up.py --check`，不要把它当作放宽门槛的依据。本次自检 12 项全部 `ok`。
- 无阻塞项。

## 状态历史

- 2026-10-26 19:59 新建：接用户「重启服务，除了自动更新」请求；读取规范与 OPS-02 后建立本卡。
- 2026-10-26 20:00 进行中：四个应用进程重启；collection 首次因心跳窗口退出，补起成功。
- 2026-10-26 20:03 已完成：四进程、HTTP、队列与 PID 记录复核通过；调度器保持未运行。
- 2026-10-26T22:40：卡片与证据随本轮审查提交 `5607ed0`，经 merge `bb29801` 合入 `main` 并推送；
  运行状态与验收结论未变化。
