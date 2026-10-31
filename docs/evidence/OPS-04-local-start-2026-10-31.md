# OPS-04 本机前后端启动与可达性验证（2026-10-31）

- 时间：2026-10-31 00:44—00:53（Asia/Shanghai）
- 代码状态：分支 `快手_1026`，工作区含既有未提交改动（本轮未提交、未改动业务代码）
- 运行模式：本机原生栈；PostgreSQL 55432、Redis 56379、Temporal 57233、MinIO 59000 保持运行
- 用户要求：启动前后端服务供体验，**不启动定时更新达人**
- 任务卡：[OPS-04](../tasks/OPS-04.md)

## 1. 前置状态与迁移

启动前主栈（8000/5173）与上一轮聚星隔离回归栈（4192/4193/57235）同时在跑；主库 `xingtu_development` 的 `schema_migrations` 只到 19，而当前代码需要迁移 020（`execution_unit_platform_bindings`）。采集 Worker 日志持续报 `UndefinedTable`（每 2 秒一次）。

处理：

```bash
# 迁移前备份（34 MB，可读）
mkdir -p .runtime/backups/ops04-20261031
pg_dump -Fc -f .runtime/backups/ops04-20261031/xingtu_development-pre-migration020.dump "$XINGTU_DATABASE_URL"

# 应用追加式迁移
.venv/bin/xingtu migrate --environment development
# all pending migrations applied or already present
```

迁移后只读核对：

| 项 | 结果 |
|---|---|
| `schema_migrations` | 20 条，最大版本 20 |
| `execution_unit_platform_bindings` | 已建表 |
| `root_tasks` 平台回填 | 116 条全部 `douyin_xingtu` |
| 重启前非终态根任务 | 0 |
| 迁移前备份 | `.runtime/backups/ops04-20261031/xingtu_development-pre-migration020.dump` |

## 2. 停止旧进程并启动

停止主栈旧进程（API 48345、intake 48699、collection 48700、Vite 48429），并停止上一轮聚星隔离回归栈（API 59888、intake 44490、collection 60376、Vite 44447/44460、Temporal 44374/44375）。两侧业务库均无在途任务（主库非终态 0；回归库 3 COMPLETED + 3 PARTIAL_COMPLETED）。

启动入口：`.runtime/dev-no-upd.sh up`（`scripts/dev.sh` 的本地变体，故意跳过 `update-scheduler`；gitignored，仓库代码未改）。

前置自检 13 项全部 `ok`：

```
M3_ENV_FILE / MODEL_ENV_FILE / NO_PROXY_SANITISED / DATABASE_URL / DATABASE_REACHABLE
MIGRATIONS_APPLIED (applied=20) / TEMPORAL_REACHABLE / REGISTRY_VERIFIED_LIVE (v3)
UNIT_CONFIG / EXECUTION_UNIT_REGISTERED / EXECUTION_UNIT_READY (READY)
DEEPSEEK_API_KEY / MODEL_AVAILABLE (deepseek-flash)
PREFLIGHT_OK
```

collection 首次启动（pid 69718）撞上旧 Worker 45 秒心跳窗口，以 `DUPLICATE_WORKER_FOR_UNIT` 退出（预期竞态）；等待窗口后补起成功（pid 70064，generation 11）。随后为对齐封面存储再次重启 collection（pid 71225，generation 12）。

## 3. 最终进程与 HTTP

| 服务 | PID | 结果 |
|---|---|---|
| API `xingtu-api` | 69676 | `GET /api/auth/me` → 401（未登录，预期） |
| 前端 Vite | 69749 | `http://127.0.0.1:5173/` → 200 |
| P1 intake-worker | 69701 | 队列 `xingtu-intake` 在线，1 个新鲜消费者 |
| P2 collection-worker | 71225 | 队列 `xingtu-unit-local-mac-02` 在线，1 个新鲜消费者（entry 2 中含 1 条已停旧 Worker 的 TTL 残留） |
| update-scheduler | — | **未运行**（`pgrep` 无匹配） |

`.runtime/dev/pids.tsv` 与上述四个 PID 一致。

## 4. 登录与业务读接口

真实登录（`media-a`，口令只从 `.runtime/qa-credentials.env` 读取，未打印）：

| 请求 | 结果 |
|---|---|
| `POST /api/auth/login`（Origin `http://127.0.0.1:5173`） | 200，返回 `media-a` 与 CSRF token |
| `GET /api/auth/me` | 200 |
| `GET /api/tasks?limit=5` | 200，返回既有任务（如 `6dff3c73…` `PARTIAL_COMPLETED`） |
| `GET /api/tasks/{id}` | 200，含计数、平台、允许操作 |
| `GET /api/tasks/{id}/creators?limit=2` | 200，含快照 payload |
| `GET /api/creator-library?limit=3` | 200，达人库列表 |
| `GET /api/execution-units` | 200，`unit-local-mac-02` `READY` |
| `GET /api/platforms` | 200；巨量星图 `enabled=true`，磁力聚星 `enabled=false`（Feature Flag 未开） |

## 5. 浏览器页面冒烟

Playwright + 项目 Chromium（headless，1440×960）：

- `/login` 标题「星采 · 媒介工作台」，登录表单渲染正常；
- 使用 `media-a` 从页面「安全登录」→ 跳转 `/tasks`，任务中心渲染（截图）；
- 直接访问 `/creators`，达人库渲染「20 位已加载」及筛选项（截图）；
- 控制台唯一错误是登录前的预期 `401 /api/auth/me`，登录后无失败 API。

截图（私有，未入 Git）：`.runtime/evidence/ops04-login.png`、`.runtime/evidence/ops04-tasks.png`、`.runtime/evidence/ops04-library.png`。

## 6. 封面存储配置修复（运行态）

启动前单元 `local-dev-mac-02.json` 的 `covers` 为远端 S3 `http://100.86.124.51:9000`，该地址 5 秒超时不可达；产品 API 的 `XINGTU_COVER_KIND=local` 读取 `.runtime/covers`。两者不一致会导致新采集任务的封面上传卡在连接超时、且即使写入也不被页面读取。

处理：

- 备份当前配置：`.runtime/units/local-dev-mac-02.s3-pre-ops04.json`（0600）；
- 按迁移前同目录备份 `local-dev-mac-02.pre-cloud-20261020.json` 恢复 `covers.kind=local`、目录 `.runtime/covers`；
- `load_unit()` 校验通过（`network_mode=local_development`，`covers=local`），文件权限仍为 0600；
- 重启 collection worker 使配置生效（generation 12）。

现状：`.runtime/covers` 内已有 5486 个本地封面对象可继续由 API 提供。远端 S3 仍不可达，但不再参与本地采集写路径。

## 7. 未执行与遗留

- 未发起任何真实采集任务（未打开星图页面、未提交产品任务）；登录、读接口与页面冒烟均未访问平台。
- 未运行测试套件（本轮无代码改动）。
- 未验证星图会话是否仍有效；如新建任务时提示登录/挑战，按既有维护流程处理。
- 磁力聚星 Feature Flag 在当前主栈保持关闭；其隔离回归栈已停止，测试库 `xingtu_test_kjx_regression` 保留。
- `update-scheduler` 按用户要求保持关闭；启动后会立即处理到期达人并占用唯一执行单元。
- 工作区既有未提交改动未纳入本轮，也未提交。
