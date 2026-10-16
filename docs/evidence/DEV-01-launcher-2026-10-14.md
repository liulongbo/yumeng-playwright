# DEV-01 证据：星采本地全栈一键启停入口（2026-10-14）

> 对应卡片：[DEV-01](../tasks/DEV-01.md)。  
> 环境：macOS 本机开发，真实开发库（Compose PostgreSQL 18.3 @55432、Redis @56379、MinIO @59000、Temporal @57233），
> 执行单元 `unit-local-mac-02`（`local_development`，真实本机 Chrome 154.0.8037.57）。
> 代码版本：工作区未提交状态；本轮新增 `dev.sh`、`scripts/dev.sh`（2026-10-14 09:45–09:56 +08:00），无 Git 提交号。

## 1. 交付物

| 文件 | 作用 |
|---|---|
| [dev.sh](../../dev.sh) | 根目录便捷入口，转发到 `scripts/dev.sh` |
| [scripts/dev.sh](../../scripts/dev.sh) | `up` / `stop` / `restart` / `status` / `logs` / `check` 实现 |

## 2. 前置自检（复用既有入口，未放宽门槛）

`./dev.sh up` 内部调用 `.venv/bin/python scripts/m3_up.py --check --with-collection --with-frontend`，2026-10-14 09:53:06 输出：

```text
=== M3 preflight ===
  [ok ] M3_ENV_FILE                      .runtime/m3-app.env
  [ok ] MODEL_ENV_FILE                   .runtime/deepseek.env loaded
  [ok ] NO_PROXY_SANITISED               removed 1 bracketed IPv6 entry from no_proxy
  [ok ] DATABASE_URL                     XINGTU_DATABASE_URL present
  [ok ] DATABASE_REACHABLE               connected; schema_migrations read
  [ok ] MIGRATIONS_APPLIED               applied=11 expected>=11
  [ok ] TEMPORAL_REACHABLE               127.0.0.1:57233
  [ok ] REGISTRY_VERIFIED_LIVE           douyin_xingtu.verified.json capabilities=xingtu-ad-creator-square-v1
  [ok ] UNIT_CONFIG                      unit_id=unit-local-mac-02
  [ok ] EXECUTION_UNIT_REGISTERED        unit-local-mac-02 state=READY
  [ok ] EXECUTION_UNIT_READY             READY
  [ok ] DEEPSEEK_API_KEY                 present
  [ok ] MODEL_AVAILABLE                  deepseek-flash (available=['deepseek-flash', 'deepseek-v4-pro'])

PREFLIGHT_OK: all required prerequisites are satisfied.
```

## 3. 完整停启（`./dev.sh restart`，2026-10-14 09:55:28 → 09:55:36）

```text
09:55:28 停止 intake-worker (pid 18211)…
09:55:29 停止 collection-worker (pid 18222)…
09:55:29 停止 frontend (pid 18252 及子进程 18254)…
09:55:30 停止 api (pid 18193)…
09:55:30 已停止本脚本启动的进程（数据库、对象、profile 与浏览器数据均保留）
09:55:32 已启动 api (pid 18965) -> .runtime/logs/api.log
09:55:34 就绪：后端 API (http://127.0.0.1:8000/api/auth/me -> 401)
09:55:34 已启动 intake-worker (pid 18989)
09:55:34 已启动 collection-worker (pid 19006)
09:55:34 已启动 frontend (pid 19015) -> .runtime/logs/frontend.log
09:55:36 就绪：前端页面 (http://127.0.0.1:5173/ -> 200)
09:55:36 等待队列消费者注册（Temporal）…
  队列 xingtu-intake                在线  新鲜消费者=4  最老刷新=7.099404s
  队列 xingtu-unit-local-mac-02     在线  新鲜消费者=4  最老刷新=7.844507s
```

停止复核（`kill -0`）：旧 PID `11949/11954/12114/16188/17809/17814/18211/18222/18193` 全部不存在；端口 5173 的监听者由旧 Vite 变为新 Vite（PID 19035），8000 的监听者为新 API（PID 18965）。

## 4. 可重复执行（幂等，2026-10-14 09:55:47）

```text
09:55:47 接管已在 8000 监听的 API（pid 18965）
09:55:47 接管已在运行的 intake-worker (pid 18989)
09:55:47 接管已在运行的 collection-worker (pid 19006)
09:55:47 接管已在 5173 监听的前端（pid 19035）
```

未新增进程，未出现重复 worker。

### 4.1 重复 Worker 清理（09:52:25）

启动器首次上线时，工作区存在多轮历史遗留的游离 Worker（同一单元 2 个 Intake、3 个采集，其中 `16188` 的 profile 指向已迁移的旧目录）。`up` 的接管逻辑只保留一个并报告其余：

```text
09:52:25 结束重复的 intake-worker (pid 11949)，保持每账号一个
09:52:25 接管 intake-worker (pid 17809)，已清理 1 个重复进程
09:52:25 结束重复的 collection-worker (pid 11954)，保持每账号一个
09:52:25 结束重复的 collection-worker (pid 16188)，保持每账号一个
09:52:25 接管 collection-worker (pid 17814)，已清理 2 个重复进程
```

### 4.2 修正的误报

初次实现用 `pgrep -f 'xingtu-product intake-worker'` 清点进程，把「命令行里含同一字符串」的自身包装 shell 也计入，`status` 曾误报「重复运行 2 个」。改为 `worker_pids()`（`pgrep -f` 与 `lsof -c Python -F p` 取交集）后，同一时刻稳定显示每类一个 PID。此为工具误报，不是真的重复 worker。

## 5. 最终状态快照（`./dev.sh status`，2026-10-14 09:56:11）

```text
== 进程 ==
  api                运行中   pid 18965（本脚本启动）
  frontend           运行中   pid 19035（本脚本启动）
  intake-worker      运行中   pid 18989
  collection-worker  运行中   pid 19006
== 端口 ==
  8000 监听中 / 5173 监听中 / 55432 监听中 / 56379 监听中 / 59000 监听中 / 57233 监听中
== HTTP ==
  API   /api/auth/me        -> 401（期望 401）
  前端  /                   -> 200（期望 200）
== 队列消费者 ==
  队列 xingtu-intake                在线  新鲜消费者=3  最老刷新=23.620457s
  队列 xingtu-unit-local-mac-02     在线  新鲜消费者=3  最老刷新=22.237223s
```

Temporal 的 `poller_entries` 在停止 Worker 后的数分钟内仍保留旧条目（既有事实，`worker_health.DEFAULT_FRESHNESS_SECONDS = 180`），因此 `status` 的判据是「新鲜消费者」而非条目数。

## 6. 页面验收（Playwright + 本机 Chrome，headless，2026-10-14 09:56）

流程：打开 `http://127.0.0.1:5173/` → 以 `media-a` 登录（口令取自 `.runtime/qa-credentials.env`，不打印）→ 访问任务中心 → 访问达人库。

```text
after login url: http://127.0.0.1:5173/tasks
nav: 任务中心 | 创建任务 | 达人库
task rows: 21
creators url: http://127.0.0.1:5173/creators
loaded: 20 位已加载
first rows: 20
console errors: ['Failed to load resource: the server responded with a status of 401 (Unauthorized)']
```

`401` 为登录页首次调用 `GET /api/auth/me` 的预期响应（未登录），非缺陷。

截图：

- [任务中心](assets/DEV-01-task-center-2026-10-14.png)
- [达人库](assets/DEV-01-creator-library-2026-10-14.png)

## 7. 未覆盖与限制

- `./dev.sh stop` 单独执行后的端口释放未做独立复核（`restart` 已隐含覆盖停止路径）；`./dev.sh logs` 未单独实测。
- `dev.sh` 不启停 Docker 依赖服务；依赖未起时由前置自检的 `DATABASE_REACHABLE` / `TEMPORAL_REACHABLE` 报错。
- 本轮为**工具入口**验证，不构成平台能力、采集完整性或生产就绪的新证据；相关结论仍以 UNIT-01 / F04 / F05 / F06 / LIB-01 卡片为准。
