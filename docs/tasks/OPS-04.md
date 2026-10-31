# OPS-04：本机前后端服务启动（跳过自动更新）

状态：已完成  
更新时间：2026-10-31T00:53:00+08:00  
是否验收：是（本轮范围：四个应用进程启动、迁移与可达性；业务体验由用户执行）

## 目标与范围

**目的**：按用户要求启动本机「星采」后端 API、P1 需求转换 Worker、P2 采集 Worker 与前端页面，供用户直接体验；**不启动定时更新达人（`update-scheduler`）**。

包含：

- 停止上一轮遗留的主栈进程与聚星隔离回归测试栈（API 4192 / Vite 4193 / Temporal 57235 及其 Worker）；
- 对 `xingtu_development` 先 `pg_dump` 备份，再应用待执行的迁移 020（KJX-01 多平台，追加式）；
- 恢复本机单元封面存储为本地目录（原远端 S3 不可达，且与 API 的本地读取配置不一致）；
- 启动 API、Intake Worker、采集 Worker、前端四个进程，并校验进程、端口、HTTP、Temporal 队列消费者与登录入口；
- 保留 PostgreSQL/Redis/Temporal/MinIO 依赖与全部业务数据，不重建、不清库。

不做：

- 不启动定时更新调度器（`xingtu-product update-scheduler`）；
- 不改业务代码、契约与迁移内容；除封面存储恢复本地外，不改其他执行单元配置；
- 不发起真实采集任务；不启停依赖服务；不迁移或写入生产业务库。

## 关联与依赖

- 前置：[OPS-03](OPS-03.md)（同一运行栈的上一轮重启）、[DEV-01](DEV-01.md)（`./dev.sh` 启停入口）、[KJX-01](KJX-01.md)（迁移 020）。
- 本次入口：`.runtime/dev-no-upd.sh`（`scripts/dev.sh` 的本地变体：跳过 `update-scheduler`；gitignored，未改仓库代码）。
- 命令契约：[开发规范](../agent.md)第 3.1 节；运行事实：[开发与运维说明](../development.md)。

## 验收清单

- [x] API、intake-worker、collection-worker、frontend 各 1 个进程运行，`.runtime/dev/pids.tsv` 与实际 PID 一致（69676 / 69701 / 71225 / 69749）。
- [x] `GET /api/auth/me` → 401；`http://127.0.0.1:5173/` → 200。
- [x] `xingtu-intake` 与 `xingtu-unit-local-mac-02` 各 1 个新鲜消费者（collection 的 `poller_entries=2` 中有 1 条为已停旧 Worker 的 TTL 残留，非运行进程）。
- [x] `update-scheduler` 启动前后均未运行。
- [x] 迁移 020 已应用（`schema_migrations` 最大版本 20），迁移前备份存在且可读（约 34 MB）。
- [x] 重启前主库非终态根任务为 0；依赖服务未重启；业务数据未删除（`root_tasks` 116 条保持原状态）。
- [x] 登录页可访问，`media-a` 账号可用（口令只存于 `.runtime/qa-credentials.env`，未在文档或回复中打印）。
- [x] 页面级冒烟：真实 Chromium 从登录页登录后任务中心与达人库均渲染；无登录后失败 API。
- [x] 封面存储恢复为本地目录，采集 Worker 已用新配置重启（generation 12）。

## 实现记录

1. 读取规范、开发说明、OPS-03/DEV-01/KJX-01 卡；确认主栈（8000/5173）与遗留聚星回归栈（4192/4193/57235）同时在跑。
2. 迁移前对 `xingtu_development` 执行 `pg_dump -Fc`，备份至 `.runtime/backups/ops04-20261031/xingtu_development-pre-migration020.dump`。
3. `xingtu migrate --environment development` 应用迁移 020；`schema_migrations` 20 条，`execution_unit_platform_bindings` 已建表，116 条历史任务回填为 `douyin_xingtu`。
4. 停掉主栈旧进程（API 48345、intake 48699、collection 48700、Vite 48429）与聚星回归栈（API 59888、intake 44490、collection 60376、Vite 44447/44460、Temporal 44374/44375）；重启前主库非终态根任务为 0，回归库任务全为终态。
5. 执行 `.runtime/dev-no-upd.sh up`：前置自检 13 项全部 `ok`；启动 API 69676、Intake 69701、采集 70064、前端 69749；**跳过 update-scheduler**。
6. collection 首次因旧 Worker 45 秒心跳窗口以 `DUPLICATE_WORKER_FOR_UNIT` 退出（预期竞态），等待窗口后补起成功。
7. 发现单元 `covers` 指向不可达的远端 S3，且与 API 的 `XINGTU_COVER_KIND=local` 不一致；备份为 `.runtime/units/local-dev-mac-02.s3-pre-ops04.json`，按迁移前备份恢复 `covers.kind=local`，`load_unit()` 校验通过、权限保持 0600，重启 collection 为 generation 12。
8. 用 `media-a` 完成 API 登录与任务/达人库/执行单元读接口校验；再用真实 Chromium 走登录 → 任务中心 → 达人库页面冒烟。

## 验证证据

- 时间与环境：2026-10-31 00:44—00:53（Asia/Shanghai），本机原生栈，分支 `快手_1026`（工作区含既有未提交改动），未发起真实采集。
- 迁移前备份：`.runtime/backups/ops04-20261031/xingtu_development-pre-migration020.dump`（34 MB）。
- 前置自检：13 项 `ok`，`PREFLIGHT_OK`。
- 进程与 HTTP：四进程各 1；API 401（未登录）、前端 200；两队列各 1 个新鲜消费者。
- 登录与读接口：`POST /api/auth/login` 200；`/api/auth/me`、`/api/tasks`、任务详情、任务内达人、`/api/creator-library`、`/api/execution-units` 均 200；`/api/platforms` 显示巨量星图启用、磁力聚星关闭。
- 页面冒烟：Playwright + 项目 Chromium 登录后 `/tasks` 与 `/creators` 渲染正常；截图 `.runtime/evidence/ops04-*.png`（私有）。
- update-scheduler：`pgrep` 无匹配，日志未新增。
- 详细记录：[OPS-04 启动与可达性验证](../evidence/OPS-04-local-start-2026-10-31.md)。

## 交接信息

- 页面 `http://127.0.0.1:5173/`；登录 `media-a`，口令见 `.runtime/qa-credentials.env`。停止：`./dev.sh stop`；状态：`./dev.sh status`。
- 定时更新保持关闭；需要时按 [OPS-02](OPS-02.md) 的交接命令启动，启动后会立即处理到期达人并占用唯一执行单元。
- 磁力聚星 Feature Flag 在当前主栈保持关闭（`/api/platforms` 返回 `enabled=false`）；其隔离回归栈已停止，测试库 `xingtu_test_kjx_regression` 保留。
- 未验证星图会话是否仍有效；如新建任务提示登录/挑战，按既有维护流程处理。
- 未运行测试套件（本轮无代码改动）；未发起真实采集。
- 回退封面配置：用 `.runtime/units/local-dev-mac-02.s3-pre-ops04.json` 覆盖当前单元文件并重启 collection（远端 S3 当前不可达，不建议在本地体验期间回退）。

## 状态历史

- 2026-10-31 00:45 新建：接用户「启动前后端服务、不要定时更新达人、需要体验功能」请求；建立本卡并进入进行中。
- 2026-10-31 00:53 进行中 → 已完成：四进程、HTTP、登录、页面冒烟与队列消费者验证通过；迁移 020 已备份后应用；`update-scheduler` 保持未运行。
