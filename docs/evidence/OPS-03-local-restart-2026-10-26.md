# OPS-03：本机全栈服务重启（跳过自动更新，2026-10-26）

> 任务卡：[OPS-03](../tasks/OPS-03.md)。范围仅限重启四个应用进程并验证基础可达性；不含业务功能验收、真实采集与依赖服务启停。

## 1. 结论

按用户要求重启 API、P1 Intake Worker、P2 采集 Worker 与前端 Vite，**不启动定时更新调度器**。最终四个进程各 1 个、端口正常、`GET /api/auth/me` 401、前端 200、两个 Temporal 队列各 1 个新鲜消费者。依赖服务与业务数据未重启/未清理，未发起真实采集，未改代码、配置、契约或迁移。只读核对确认 **112 条 `root_tasks` 全为终态、重启前后无在途任务**。

## 2. 环境

| 项 | 值 |
|---|---|
| 时间 | 2026-10-26 19:59—20:02（Asia/Shanghai） |
| 代码版本 | `main` @ `f52b7fb`；工作区已有 IPPOOL-02 文档改动（本次未触碰） |
| 运行形态 | 单机原生进程（非 Compose） |
| 应用配置 | `.runtime/m3-app.env` + `.runtime/deepseek.env` |
| 执行单元 | `.runtime/units/local-dev-mac-02.json`（`unit-local-mac-02`） |
| 依赖 | PostgreSQL 55432、Redis 56379、Temporal 57233 均在运行；MinIO 59000 空闲 |
| 入口 | `.runtime/dev-no-upd.sh`（`scripts/dev.sh` 的本地变体：跳过 `update-scheduler`，前置自检 FAIL 时告警继续；gitignored） |

## 3. 重启前状态

| 服务 | 重启前 |
|---|---|
| API | pid 12680 |
| intake-worker | pid 27814 |
| collection-worker | pid 21368 |
| frontend | pid 27861 |
| update-scheduler | 未运行 |

依赖端口 55432/56379/57233 监听中，59000 空闲；两队列各 1 个新鲜消费者。

## 4. 执行记录

```bash
./.runtime/dev-no-upd.sh restart   # 19:59:15
./.runtime/dev-no-upd.sh up        # 20:00:12，补起采集 Worker
```

1. `restart` 停止记录内 4 个进程；依赖启动步骤因 Docker 不可用告警，但未影响 native 依赖。
2. 前置自检 12 项全部 `ok`：数据库连接、迁移 19、Temporal、注册表 live、单元 READY、DeepSeek 模型可用。
3. 启动 API `24614`、intake `24651`、collection `24668`、前端 npm `24678`；`update-scheduler` 按用户要求跳过。
4. `collection 24668` 启动即退出，日志（stderr，无时间戳）为 `{"error_code":"RESOURCE_UNAVAILABLE","reason":"DUPLICATE_WORKER_FOR_UNIT"}`。根因：`Repository.register_worker_instance` 以 45 秒心跳窗口判定重复 Worker；旧 Worker 虽已停止，但其 `execution_unit_workers.last_heartbeat_at` 仍在窗口内。
5. 等待超过 45 秒后执行 `up`：API/intake/frontend 被接管，collection `25026` 启动并以 `generation=8` 轮询 `xingtu-unit-local-mac-02`；`update-scheduler` 再次跳过。
6. 20:02:41 复核：四个进程稳定，队列各 1 个新鲜消费者。

## 5. 验证结果

| 检查 | 方式 | 结果 |
|---|---|---|
| API | `./.runtime/dev-no-upd.sh status` / `curl /api/auth/me` | pid 24614，**401** |
| 前端 | `curl http://127.0.0.1:5173/` | pid 24698，**200** |
| intake | `status` + 日志 | pid 24651，轮询 `xingtu-intake` |
| collection | `status` + 日志 | pid 25026，`generation=8`，轮询 `xingtu-unit-local-mac-02` |
| 自动更新 | `pgrep -fl update-scheduler` | **未运行**（重启前后一致） |
| 队列 | `worker_health.check_queues` | 两队列在线，各 **1** 个新鲜消费者（20:02:41） |
| 在途任务 | 只读查询 `root_tasks` / `execution_units` | 112 条全终态，最后更新 2026-10-24 15:58，19:55 后 **0** 条变更；单元 `READY`、无 owner/lease、`browser_stopped=true` |
| 依赖 | 端口检查 | 55432/56379/57233 监听，59000 空闲；未重启 |
| PID 记录 | `.runtime/dev/pids.tsv` | api 24614 / intake 24651 / collection 25026 / frontend 24698 |

说明：`restart` 后约 3 分钟内队列曾显示 2 个新鲜消费者，是 Temporal poller 的 TTL 残留（`worker_health` 文档说明 >2 分钟），不是重复进程；进程列表中两 Worker 各 1 个，20:02:41 已回落为各 1。

## 6. 未验证 / 未执行

- 未执行 `media-a` 登录、`GET /api/tasks`、达人库、封面与页面渲染复测；本次只验证基础可达性。
- 未发起真实采集，未打开 Chrome 采集 profile。
- 未运行测试套件：本次无代码/配置改动。
- 未修改 `scripts/dev.sh`；若需“一条命令重启”避免上述 45 秒竞态，应另行修改入口并补验证。

## 7. 交接

- `update-scheduler` 保持未运行。需要时按 OPS-02 交接命令启动（会立即处理到期达人）。
- 业务体验验收由用户执行；如登录或数据读取异常，先查 `.runtime/logs/{api,intake-worker,collection-worker,frontend}.log`。
