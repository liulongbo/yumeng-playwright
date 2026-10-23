# OPS-02：本机全栈服务重启与前端可达性验证（2026-10-22）

> 任务卡：[OPS-02](../tasks/OPS-02.md)。范围仅为「重启本机应用服务并验证前端可访问」，不包含业务功能验收与真实采集。

## 1. 结论

按单机原生 `local-main` 运行配置重启全部应用服务后，前端 **`http://127.0.0.1:5173/` 可访问（200）**，后端 API 存活（未登录 `GET /api/auth/me` → 401），`media-a` 产品登录 200，任务中心 20 条、达人库可读，封面端点返回真实 `image/webp`，Temporal `xingtu-intake` 与 `xingtu-unit-local-mac-02` 两个队列消费者在线、无重复 Worker。**定时更新调度器按用户决定不启动**（见第 6 节），因此验收期间不会自动产生非用户发起的采集任务。

## 2. 环境

| 项 | 值 |
|---|---|
| 时间 | 2026-10-22 11:02—11:06（Asia/Shanghai） |
| 代码版本 | `main` @ `ae600ec`，开始时工作区干净 |
| 运行形态 | 单机原生进程（同 [LIVE-01](LIVE-01-live-e2e-2026-10-21.md)），非 Compose、非混合部署 |
| 应用配置 | `.runtime/local-main/env` + `.runtime/deepseek.env`（模型凭据） |
| 执行单元 | `.runtime/local-main/units/unit-local-mac-02.json`（`unit-local-mac-02`，`local_development`） |
| 依赖服务 | PostgreSQL `127.0.0.1:55432`（pid 1511）、Redis `127.0.0.1:56379`（需密码）、Temporal `127.0.0.1:57233`（pid 1523）、MinIO `59000`，均为重启前已运行且未重启 |
| 日志 | `.runtime/logs/{api,intake-worker,collection-worker,frontend}.log` |

## 3. 重启前状态（实际观测）

| 服务 | 重启前 |
|---|---|
| API | pid `88838`，**未记录**在 `.runtime/dev/pids.tsv`（记录中的 `46162` 已不存在） |
| intake-worker | pid `46336`（与记录一致） |
| collection-worker | pid `84897`，**未记录**（记录中的 `62960` 已不存在） |
| update-scheduler | 未运行 |
| 前端 | pid `1545`（记录一致，`npm run dev` + Vite 子进程） |
| 业务任务 | 全部为终态（`PARTIAL_COMPLETED` 40、`CANCELLED` 21、`COMPLETED` 17、`FAILED` 6、`FAILED_VALIDATION` 1），**无在途采集**，可安全停止 |

## 4. 执行操作

```bash
# 1) 停止脚本记录的进程（含前端子进程树）
./dev.sh stop

# 2) 停止两个游离进程（已用 lsof/pgrep 核对其命令行确为本项目 xingtu-api / xingtu worker）
kill 88838 84897          # 确认退出，8000 与 5173 均无监听

# 3) 以 local-main 配置重启（等价于 development.md 记录的底层入口）
set -a; . ./.runtime/local-main/env; . ./.runtime/deepseek.env; set +a
export PYTHONPATH="$PWD/backend/src" PLAYWRIGHT_BROWSERS_PATH="$PWD/.runtime/browsers"
nohup .venv/bin/xingtu-api                                  >>.runtime/logs/api.log 2>&1 &
nohup .venv/bin/xingtu-product intake-worker --unit-config .runtime/local-main/units/unit-local-mac-02.json >>.runtime/logs/intake-worker.log 2>&1 &
nohup .venv/bin/xingtu worker --config .runtime/local-main/units/unit-local-mac-02.json >>.runtime/logs/collection-worker.log 2>&1 &
nohup npm --prefix frontend run dev                          >>.runtime/logs/frontend.log 2>&1 &

# 4) 记录 PID，使 ./dev.sh status/stop 覆盖该运行栈
#    .runtime/dev/pids.tsv: api 82777 / intake-worker 82802 / collection-worker 82805 / frontend 82885
```

未执行：`make dev`（Compose）与 `./dev.sh up` 的依赖启动步骤——现有原生依赖已在运行，启动 Compose 会与 `55432/56379` 端口冲突，且不属于本次「重启应用服务」范围。

## 5. 验证结果

| 检查 | 命令/方式 | 结果 |
|---|---|---|
| API 存活 | `curl -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/api/auth/me` | **401**（未登录预期） |
| 前端页面 | `curl http://127.0.0.1:5173/` | **200** |
| 前端代理 | `curl http://127.0.0.1:5173/api/auth/me` | **401**（代理到 API 正常） |
| 产品登录（127.0.0.1 Origin） | `POST /api/auth/login`，`media-a` | **200**，返回 `csrf_token` |
| 产品登录（localhost Origin） | 同上，`Origin: http://localhost:5173` | **200**（运行态已补该 Origin，见第 6 节） |
| 任务列表 | `GET /api/tasks` | **200**，20 条；首条 `276208a3…` `PARTIAL_COMPLETED`，`completed_at` 有值 |
| 达人库 | `GET /api/creator-library?limit=5` | **200**，5 条（如 `瓜小兔` / `7201315409155342395`） |
| 任务内达人 | `GET /api/tasks/b94d146b…/creators` | **200**，10 条（LIVE-01 验收任务） |
| 封面端点 | `GET /api/tasks/b94d146b…/covers/cover/b94d146b…/a8e917…` | **200**，`image/webp`，148,526 bytes（`file` 识别为 WebP） |
| 队列消费者 | `./dev.sh status` → Temporal 队列检查 | `xingtu-intake` 在线、`xingtu-unit-local-mac-02` 在线，各 1 个 Worker 进程（无重复） |
| Worker 日志 | `.runtime/logs/intake-worker.log`、`collection-worker.log` | `intake worker polling xingtu-intake`、`collection worker polling xingtu-unit-local-mac-02`；intake 启动时 `GET https://api.deepseek.com/models 200` |
| 页面渲染（无头 Chromium） | Playwright + `chromium-1243`，登录后访问 `/tasks`、`/creators` | 标题「星采 · 媒介工作台」；任务中心渲染 20 条、达人库加载；控制台仅 1 条预登录 `401`（预期），无 JS 异常 |

截图（运行态，未纳入版本库）：`.runtime/logs/acceptance-tasks.png`、`.runtime/logs/acceptance-creators.png`。

`./dev.sh status` 重启后输出：API/前端「运行中（本脚本启动）」，两个 Worker「运行中」，`update-scheduler`「未运行」，端口 8000/5173/55432/56379/59000/57233 均监听，HTTP 401/200 符合预期。

**2026-10-22 11:20 补充：登录口令核对（用户索取账号口令时实测）**

| 账号 | 来源 | 结果 |
|---|---|---|
| `media-a` | `.runtime/qa-credentials.env` | **200**，可正常登录（`password_changed_at=2026-10-13 17:24`，与文件写入时间一致） |
| `media-b` | 同上 | **422 `INVALID_FORM`：用户名或密码错误**；库中账号存在且 `active=true`，`password_changed_at` 仍为 2026-10-10 创建时刻，说明**文件中记录的 media-b 口令从未生效或已过期**，需重置后使用 |

两账号均为启用状态；`users` 表另有 `smoke-qa-20261010`、`f10-operator`、`admin`（口令不在本文件，未核对）。

## 6. 运行态配置变更（不纳入 Git）

1. `.runtime/local-main/env`：`XINGTU_ALLOWED_ORIGINS` 由 `http://127.0.0.1:5173` 扩展为 `http://127.0.0.1:5173,http://localhost:5173`。原因：重启前 `api.log` 出现过 `POST /api/auth/login 403`，Origin 白名单只含 `127.0.0.1`；用户若用 `localhost:5173` 访问会被拒绝。两种 Origin 登录均已实测 200。
2. `.runtime/dev/pids.tsv`：重写为本次实际 PID，使 `./dev.sh status` / `./dev.sh stop` 覆盖该运行栈（此前的游离 API 与采集 Worker 无法被 stop 管理）。

## 7. 未做与遗留

1. **定时更新调度器未启动（用户明确选择）**。当前 `creator_update_schedule` 有 **22 位达人已到期**（1 天档 10、3 天档 4、5 天档 8，最早到期 2026-10-21 20:49），启动后会立即创建真实周期更新任务并占用唯一执行单元，干扰体验验收。需要时执行：`nohup .venv/bin/xingtu-product update-scheduler --unit-config .runtime/local-main/units/unit-local-mac-02.json >>.runtime/logs/update-scheduler.log 2>&1 &`。
2. **依赖服务未重启**：PG/Redis/Temporal/MinIO 重启前已健康，本轮按「应用服务」范围保留，未纳入 `dev.sh` 的启停边界。
3. **`./dev.sh up` 的默认配置仍与当前运行态不一致**：脚本默认读 `.runtime/m3-app.env`（Redis 无密码、默认单元封面为 S3 `100.86.124.51:9000`），直接 `up` 会接管已运行进程，但补齐缺失进程时会用另一套配置。本轮通过手工重启 + PID 记录绕过，未改脚本；统一入口配置需另立任务（承接 [LIVE-01](LIVE-01-live-e2e-2026-10-21.md) 遗留第 5 项）。
4. 本卡只验证「服务可用、页面可达」，**不代表业务功能通过验收**；F01/F07/F08 等页面功能验收仍以对应用户验收与卡片为准。
