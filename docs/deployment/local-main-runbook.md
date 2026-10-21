# 本地体验 main 分支（无 Docker、无混合架构）

用途：在一台 Mac 上直接以原生进程跑 `main`（`5182c09`）的控制台，比较"单机全部在本机"的形态；不需要 Docker，也不涉及 Tailscale/Mac 远程 Worker。此文档记录 2026-10-21 实际跑通的步骤。

## 组件与端口

| 组件 | 来源 | 端口 |
|---|---|---|
| PostgreSQL 18 | `postgresql@18`（Homebrew） | `55432`（数据目录 `.runtime/local-main/pg`） |
| Redis | `redis`（Homebrew） | `56379`，密码 `localdevredis` |
| Temporal dev server | `temporal` CLI v1.9.1（Server 1.32.0），下载到 `.runtime/local-main/bin` | `57233`（数据库文件 `.runtime/local-main/temporal.db`） |
| API | 仓库 `.venv/bin/xingtu-api` | `127.0.0.1:8000` |
| 控制台 | `npm --prefix frontend run dev` | `127.0.0.1:5173`（`/api` 代理到 8000） |

封面存储用本地目录（`XINGTU_COVER_KIND=local`），因此不需要 MinIO。

## 启动顺序

```sh
R=.runtime/local-main
# 1) 数据库只初始化一次
/opt/homebrew/opt/postgresql@18/bin/initdb -D $R/pg -U postgres -A trust
/opt/homebrew/opt/postgresql@18/bin/pg_ctl -D $R/pg -l $R/logs/pg.log \
  -o "-p 55432 -k $PWD/$R/sock -c listen_addresses=127.0.0.1" start
/opt/homebrew/opt/postgresql@18/bin/psql -h 127.0.0.1 -p 55432 -U postgres \
  -c "CREATE ROLE xingtu_app LOGIN PASSWORD 'localdevpass';" \
  -c "CREATE DATABASE xingtu_development OWNER xingtu_app;"

# 2) Redis
/opt/homebrew/bin/redis-server --port 56379 --requirepass localdevredis \
  --save '' --appendonly no --daemonize yes --logfile "$R/logs/redis.log"

# 3) Temporal dev server（--headless 关闭自带的 Web UI）
nohup $R/bin/temporal server start-dev --db-filename "$R/temporal.db" \
  --port 57233 --ui-port 8233 --headless > $R/logs/temporal.log 2>&1 &

# 4) 迁移 + API（环境变量见 .runtime/local-main/env）
set -a && . $R/env && set +a
.venv/bin/xingtu migrate --environment development
nohup .venv/bin/xingtu-api > $R/logs/api.log 2>&1 &

# 5) 控制台
XINGTU_FRONTEND_API_TARGET=http://127.0.0.1:8000 \
  nohup npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173 > $R/logs/vite.log 2>&1 &
```

`main` 的 `migrate` 只接受 `--environment development|test`（`lln_1018` 才支持 `production`）。

## 账号与会话

```sh
printf '%s\n%s\n' "$PW" "$PW" | .venv/bin/xingtu-product create-user \
  --username admin --display-name 管理员 --actor local-setup
```

首次登录（`http://127.0.0.1:5173`）密码为创建时输入的值。API 校验 `Origin`，脚本调用必须带 `Origin: http://127.0.0.1:5173`，否则返回 `ORIGIN_CHECK_FAILED`。

## 已验证

2026-10-21：`main`@`5182c09` 迁移成功；`/api/auth/login` 返回 200 并下发会话；`/api/auth/me` 200；`/api/tasks` 200 空列表；Vite 页面 200。

## 尚未具备

- **Intake（任务需求 → 采集计划）**：`xingtu-product intake-worker` 需要 `DEEPSEEK_API_KEY`；未配置时不会启动。
- **采集 Worker**：需要注册执行单元并完成星图登录（`xingtu login --config <unit.json>` 打开有头 Chrome）。这是"单机全部在本机"的形态；与混合架构的区别只是浏览器跑在本机而非云端。
- **健康检查**：`main` 没有 `/api/health/live` 路由（该路由只在 `lln_1018` 上），容器化部署时用 TCP 探活代替。

## 停止

```sh
/opt/homebrew/opt/postgresql@18/bin/pg_ctl -D .runtime/local-main/pg stop
/opt/homebrew/bin/redis-cli -p 56379 -a localdevredis shutdown nosave
pkill -f 'temporal server start-dev'; pkill -f xingtu-api; pkill -f 'vite'
```
