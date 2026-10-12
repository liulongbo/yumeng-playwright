# M3 本地产品控制台启动与真实数据联调证据（2026-10-10）

> 范围：以仓库既有实现启动 M3 产品后端与前端，并在**真实开发库 + 真实 Chromium** 上完成只读联调。
> 边界：本轮未修改任何代码；未执行真实 DeepSeek、未创建真实产品任务、未运行真实星图采集；生产 HTTPS/域名未验收。合成数据不参与本证据，页面展示的数据来自开发库真实采集结果。

## 1. 环境与既有依赖

| 项 | 实际值 |
|---|---|
| 时间（+08:00） | 2026-10-10 14:05—14:08 |
| 主机 | 本机 macOS，工作目录为仓库根 |
| 业务库 | Compose 容器 `xingtu-f04-f05-app-postgres-1`，`127.0.0.1:55432 / xingtu_development`（非测试库，含真实采集数据） |
| 依赖服务 | 既有 Compose 栈（启动前已在运行）：PostgreSQL `55432`、Redis `56379`、MinIO `59000/59001`、Temporal `57233` |
| 后端 | `.venv/bin/xingtu-api`（uvicorn，`127.0.0.1:8000`，Python 3.13.5） |
| 前端 | `npm --prefix frontend run dev`（Vite 7.3.7，`127.0.0.1:5173`，`/api` 代理到 `127.0.0.1:8000`） |
| 浏览器 | `.runtime/browsers` 中的 Playwright Chromium，真实渲染页面并驱动登录 |
| 迁移 | `migrations/008_m3_product_app.sql` 本轮首次应用到该开发库，`applied_at=2026-10-10 06:06:02Z` |

## 2. 执行动作与实际结果

### 2.1 数据保护与迁移

| 动作 | 命令 | 结果 |
|---|---|---|
| 迁移前备份 | `docker exec xingtu-f04-f05-app-postgres-1 pg_dump -U xingtu_app -d xingtu_development > .runtime/backups/xingtu_development-before-008-20261010-140559.sql` | 17,916,071 字节备份文件生成 |
| 应用迁移 | `XINGTU_DATABASE_URL=… .venv/bin/xingtu migrate --environment development` | 退出码 0，输出 `all pending migrations applied or already present`；`schema_migrations` 新增 `8`；新增 `users`、`sessions`、`intake_dispatches`、`model_runs` 等产品表 |

迁移为既有已审查的追加迁移（仅放宽 `root_tasks.unit_id` 非空与 `filter_plans.source` 约束），未删除列或历史数据；既有 11 个 `internal_acceptance` 根任务、20 份达人快照与 145 张精选卡片在迁移后仍可读（见 2.4）。

### 2.2 本地运行环境与登录账号

- 新建私有运行环境文件 `.runtime/m3-app.env`（`0600`，位于被 `.gitignore` 忽略的 `.runtime/` 内），内容为：开发库 DSN、`XINGTU_REDIS_URL=redis://127.0.0.1:56379/0`、随机 `XINGTU_LOGIN_HMAC_KEY`（48 字节）、`XINGTU_ALLOWED_ORIGINS=http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:4173`、`XINGTU_SECURE_COOKIE=0`（仅本地 HTTP）、运行根/封面目录/注册表/API 监听地址。文件内不含任何前端或业务代码改动。
- 创建两位本地开发媒介账号（`media-a` / 媒介 A、`media-b` / 媒介 B），命令为 `.venv/bin/xingtu-product create-user`。口令由操作者在会话内设定，**未写入仓库、卡片或本文**。
- 说明：这是本地开发用户，不是生产初始用户清单；APP-01 的生产部署验收边界不变。

### 2.3 服务启动与端到端校验

| 校验 | 实际命令/动作 | 结果 |
|---|---|---|
| 未登录保护 | `GET /api/auth/me` | 401（符合预期） |
| 登录 | `POST /api/auth/login`（带 `Origin: http://127.0.0.1:5173`） | 200，返回用户与 `csrf_token` |
| 会话 | `GET /api/auth/me` | 200 |
| 能力查询 | `GET /api/platforms/douyin_xingtu/capabilities` | 200；能力版本 `xingtu-ad-creator-square-v1`，当前仅开放 1 项已核验条件（`keyword`），目标数默认 20、范围 1—200、固定排序 |
| 任务列表 | `GET /api/tasks?limit=100` | 200；11 条真实任务（`COMPLETED` 3、`PARTIAL_COMPLETED` 7、`CANCELLED` 1），来源均为 `internal_acceptance`；无下一页 |
| 认证代理链路 | 经 `http://127.0.0.1:5173/api/auth/login` 登录并读取 `/api/tasks` | 200；确认 Vite 代理、Origin 白名单与 Cookie 链路可用 |
| 任务详情/达人/作品 | `GET /api/tasks/{id}`、`/creators`、`/creators/{cid}/contents?collection_type=excellent_reach` | 均 200；作品 `view_kind=published`，4 张卡片 `cover_status=STORED` |
| 封面读取 | `GET /api/tasks/{id}/covers/{object_id}` | 已登录 200（`image/webp`，52,262 字节）；无会话 401；任务范围不匹配 404 |
| 两媒介共享 | `media-b` 读取同一任务详情/达人/作品 | 200，未因操作者不同被拒绝（共享任务权限） |

### 2.4 真实 Chromium 页面校验

脚本：`.runtime/verify-m3-ui.py`、`.runtime/verify-m3-creator-view.py`、`.runtime/verify-m3-newtask-view.py`、`.runtime/verify-m3-session-view.py`（验证用临时脚本，非项目代码）。截图：`.runtime/test-artifacts/m3-live-ui/`。

| 用例 | 结果 |
|---|---|
| 未登录直达 `/tasks` | 前端路由跳转到 `/login`；登录成功后回到原 URL `/tasks` |
| 任务中心 `/tasks` | 渲染 11 条真实任务，头部统计 11 / 0 / 0 / 7；状态、计数、时间正常 |
| 任务详情 `/tasks/{id}` | 展示进度轨道、5 类计数（发现 20、有效 1、资料 1、精选 1、失败 0）、需求与执行约束（关键词、目标 1 位、平台默认排序、来源：系统内部任务） |
| 达人详情 `/tasks/{id}/creators/{cid}` | 标记“不可变任务快照”；F05 模块与字段状态（含 `COLLECTED` 结构字段）；F06「优秀传播视频」4 张真实卡片与封面缩略图渲染 |
| 新建任务 `/tasks/new` | 只渲染 capability 返回的 `keyword` 字段；目标数默认 20；显示「重复点击或网络重试不会创建第二个任务」 |
| 页面刷新 | 刷新后仍在 `/tasks`，仍渲染 11 条（服务端会话有效） |
| 退出 | 点击退出 → `/login`；随后直达 `/tasks` 仍回到 `/login` |
| 前端运行错误 | 浏览器 `pageerror` 无记录 |

`creator-detail` 整页高度 19,360px，原因是 F05 快照按模块原样展示 `fans_daily_trend` 等长结构字段（真实数据），不是渲染缺陷；同页 `article.content-card` 计数为 4，与 API 返回一致。

## 3. 未执行与缺口

1. **未启动 P1 Intake Worker**：当前环境没有 `DEEPSEEK_API_KEY`，`.venv/bin/xingtu-product intake-worker` 会在校验阶段以 `DEEPSEEK_API_KEY_REQUIRED` 退出。因此在页面上提交新任务只会落入 `RECEIVED`，不会被转换与派发；本轮也**未提交任何新任务**，避免在真实开发库留下无法推进的记录。
2. **未启动真实采集 Worker**：`xingtu worker` 会打开真实 Chrome 并访问巨量星图，需按仓库规则单独显式授权；本轮只启动 API 与前端。
3. **未执行真实星图新任务与真实 DeepSeek 调用**：INTAKE-01 的相应验收项保持未勾选。
4. **未执行生产 HTTPS/域名/Secure Cookie 验收**：本轮 `XINGTU_SECURE_COOKIE=0` 仅为 localhost HTTP 开发，APP-01 生产验收项保持未勾选。
5. 本轮服务以会话级后台进程启动（随会话结束而停止）；长期运行需由操作者在自己终端按第 4 节命令重启。

## 4. 可复现命令

```bash
# 0) 依赖服务（本轮启动前已在运行）
make dev                       # = docker compose --env-file .runtime/development.env -f deploy/compose.yaml up -d

# 1) 业务库迁移（只读确认 + 追加迁移）
set -a; . ./.runtime/m3-app.env; set +a
.venv/bin/xingtu migrate --environment development

# 2) 本地开发用户（仅首次；口令交互输入，不落盘）
.venv/bin/xingtu-product create-user --username media-a --display-name "媒介 A" --actor bootstrap

# 3) 后端产品 API
set -a; . ./.runtime/m3-app.env; set +a
.venv/bin/xingtu-api                 # http://127.0.0.1:8000

# 4) 前端页面（另一个终端）
npm --prefix frontend run dev        # http://127.0.0.1:5173
```

## 5. 结论

M3 的产品后端、认证、任务中心/结果页已能在真实开发库与真实浏览器上完整打开并只读联调，F05/F06 真实快照、双集合与受保护封面均可通过页面查看。真实 DeepSeek、真实产品任务链路、真实星图采集与生产 HTTPS 仍未验收，APP-01/INTAKE-01/CONSOLE-01 继续保持“进行中/未验收”。
