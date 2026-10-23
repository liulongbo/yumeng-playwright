# OPS-02：本机全栈服务重启（前端体验验收环境）

状态：已完成
更新时间：2026-10-22T11:12:00+08:00
是否验收：是；本次范围为「重启本机全部应用服务并确认前端可访问」，重启后 HTTP、登录、任务/达人库读接口、封面与队列消费者均已实测通过。用户在本页面进行的业务体验验收由其本人执行，不在本卡。

## 目标与范围

**目的**：用户要在前端页面做体验验收，需把本机 `local-main` 运行栈的全部应用服务重启为当前代码版本并确认访问链路可用。

包含：

- 停止并重启后端 API、P1 Intake Worker、P2 采集 Worker、前端 Vite 页面四个应用进程。
- 保留 PostgreSQL/Redis/Temporal/MinIO 依赖与全部业务数据（不重建、不迁移、不清库）。
- 重启后校验 HTTP、产品登录、任务与达人库读接口、受保护封面、Temporal 队列消费者。
- 记录 PID 到 `.runtime/dev/pids.tsv`，让 `./dev.sh status` / `./dev.sh stop` 与真实运行栈一致。

不做：

- 不改业务代码、契约、迁移、调度与采集逻辑；不发起真实采集。
- 不启停依赖服务（`make dev` / `.runtime/dev-up.sh` 边界不变）。
- **不启动定时更新调度器**：用户确认验收期间不启动，避免 22 位到期达人的周期更新自动抢占执行单元（见交接信息）。

## 关联与依赖

- 运行事实来源：[LIVE-01 真实端到端验收证据](../evidence/LIVE-01-live-e2e-2026-10-21.md)（单机原生 `local-main` 部署形态）。
- 一键启停入口：[DEV-01](DEV-01.md)（`./dev.sh`）；命令契约：[开发规范](../agent.md)第 3.1 节；底层启动顺序：[开发与运维说明](../development.md)。
- 配置来源：`.runtime/local-main/env`、`.runtime/deepseek.env`、`.runtime/local-main/units/unit-local-mac-02.json`。
- 页面验收对象：[CONSOLE-01](CONSOLE-01.md)、[UI-01](UI-01.md)、[LIB-01](LIB-01.md)。

## 验收清单

- [x] 停止后 8000/5173 无监听，无残留 API/Worker/前端进程；停止前确认全部任务为终态、无在途采集。
- [x] API 以 `local-main` 配置重启，`GET /api/auth/me` → 401（未登录预期）。
- [x] `intake-worker`、`collection-worker` 各 1 个进程，日志分别显示 polling `xingtu-intake` 与 `xingtu-unit-local-mac-02`。
- [x] 前端 Vite 重启，`http://127.0.0.1:5173/` → 200，`/api` 代理 → 401。
- [x] `media-a` 产品登录 200（`127.0.0.1` 与 `localhost` 两种 Origin）；`GET /api/tasks` 20 条、`GET /api/creator-library?limit=5` 5 条。
- [x] 受保护封面端点返回 200 `image/webp`（148,526 bytes），封面目录与 API 配置一致。
- [x] Temporal 两个队列消费者在线且每个 Worker 仅 1 个进程，无重复消费者。
- [x] `./dev.sh status` 正确显示四个进程、端口、HTTP 与消费者新鲜度（PID 已记录）。
- [x] 无头 Chromium 渲染 `/tasks`、`/creators` 成功，无 JS 异常（仅预登录 401 资源日志）。

## 实现记录（执行记录）

1. 基线核对：确认全部 `root_tasks` 为终态（`PARTIAL_COMPLETED` 40 / `CANCELLED` 21 / `COMPLETED` 17 / `FAILED` 6 / `FAILED_VALIDATION` 1），停止不会中断采集；依赖 PG `55432`、Redis `56379`、Temporal `57233`、MinIO `59000` 均健康。
2. `./dev.sh stop` 停止记录内进程（intake-worker `46336`、frontend `1545` 及 Vite 子进程）；两个未记录的游离进程（API `88838`、collection-worker `84897`）经命令行核对为本项目进程后显式停止，8000/5173 释放。
3. 以 `local-main` 配置重启：API `82777`、intake-worker `82802`、collection-worker `82805`、前端 npm `82885`。日志写入 `.runtime/logs/`（与 `dev.sh logs` 入口一致）。
4. 运行态配置两处（不纳入 Git）：
   - `.runtime/local-main/env` 的 `XINGTU_ALLOWED_ORIGINS` 增加 `http://localhost:5173`（重启前日志有登录 403，白名单只含 `127.0.0.1`）。
   - `.runtime/dev/pids.tsv` 重写为本次实际 PID。
5. 未改动任何 `backend/**`、`frontend/**`、`contracts/**`、`migrations/**` 文件，无 Schema 与迁移影响。

## 验证证据

- 2026-10-22 11:02—11:06，环境 `main@ae600ec`、单机原生 `local-main`、真实依赖（PostgreSQL 18 / Redis / Temporal / MinIO），无头 Chromium `chromium-1243` + Playwright 渲染校验。
- 实际命令与逐项结果：[OPS-02 本机全栈服务重启与前端可达性验证](../evidence/OPS-02-local-restart-2026-10-22.md)。
- 关键结果：`/api/auth/me` 401、前端 200、登录 200（双 Origin）、任务 20 条、达人库 5 条、任务内达人 10 条、封面 200 `image/webp`、两队列消费者在线、`./dev.sh status` 全绿。
- 由于本次未发起真实采集，**未验证**新任务从提交到终态的链路；该链路归属 LIVE-01 / CONSOLE-01 的验收记录。
- 截图（运行态，未入库）：`.runtime/logs/acceptance-tasks.png`、`.runtime/logs/acceptance-creators.png`。
- 2026-10-22 11:20 补充口令核对：`media-a`（口令来源 `.runtime/qa-credentials.env`）登录 **200**；`media-b` 同文件口令登录 **422 `INVALID_FORM`（用户名或密码错误）**，账号存在且启用，需重置口令（口令值只存于 `.runtime`，不写入文档）。详见证据第 5 节补充表。

## 交接信息

- **定时更新调度器未启动（用户 2026-10-22 明确选择）**：`creator_update_schedule` 有 22 位达人已到期（1 天档 10 / 3 天档 4 / 5 天档 8，最早 2026-10-21 20:49）。需要时执行：
  `nohup .venv/bin/xingtu-product update-scheduler --unit-config .runtime/local-main/units/unit-local-mac-02.json >>.runtime/logs/update-scheduler.log 2>&1 &`
- **`./dev.sh up` 默认配置仍与当前运行态不一致**：脚本默认读 `.runtime/m3-app.env`（Redis 无密码、默认单元封面为 S3），而当前栈使用 `.runtime/local-main/env`（Redis 有密码、本地封面目录）。因此本轮以底层入口手工重启并记录 PID，未执行 `./dev.sh up/restart`；统一入口配置需另立任务（承接 LIVE-01 遗留第 5 项）。
- 依赖服务未重启；若后续重启 Redis，需同步 `.runtime/local-main/env` 中 `XINGTU_REDIS_URL` 的口令，或在 Redis 侧恢复与之匹配的 `requirepass`（口令值只存于 `/.runtime`，不写入文档；LIVE-01 已记录同型风险）。
- **`media-b` 口令不可用**：`.runtime/qa-credentials.env` 中的 media-b 口令登录返回 422，账号存在且启用。若验收需要「两媒介共享读取」（CONSOLE-01 / F07），先执行 `.venv/bin/xingtu-product reset-password --username media-b --actor ops`（交互输入新口令）并同步该文件；仅单账号体验验收可直接用 `media-a`。
- 无阻塞项。

## 状态历史

- 2026-10-22 11:00 新建：接用户「重启所有服务，需在前端页面做体验验收」请求；读规范、LIVE-01 证据与当前运行栈后建立本卡。
- 2026-10-22 11:02 进行中：开始停止并重启应用服务。
- 2026-10-22 11:12 已完成：四个应用进程重启并逐项验证通过；调度器按用户决定不启动，记入交接信息。
- 2026-10-22 11:20 补充（状态不变）：按用户索取核对登录口令，`media-a` 200、`media-b` 422；媒体 B 重置需求记入交接信息。
