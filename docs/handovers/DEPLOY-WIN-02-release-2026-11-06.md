# Windows 部署发布交接（2026-11-06）

> 用途：把 GitHub `main` 的最新代码部署到甲方 Windows 电脑时使用。
> 本文只记录**已验证的事实**与**必须执行的步骤**；未验证的兼容性会显式标注。

## 1. 发布版本

| 项 | 值 |
|---|---|
| 仓库 | <https://github.com/liulongbo/yumeng-playwright> |
| 来源分支 | `1104-llb`（注意：实际分支名是 `1104-llb`，不是 `llb-1104`） |
| `1104-llb` 代码最终 commit | `2206b94`（`style(live): 格式化 adapter_factory…`） |
| `main` 合并 commit | `2c03c7d`（`Merge branch '1104-llb'…`） |
| 合并方式 | 本地 `git merge --no-ff` 后推送 `main`；仓库无 PR 模板、无分支保护、无 CI，故未走 PR |
| 发布日期 | 2026-11-06 |
| 发布批次 commit 数 | 5 个新增 commit（另含此前未推送的 LIVE-02/02F 4 个 commit） |
| 主要变更目录 | `backend/src/xingtu/`、`backend/tests/`、`frontend/src/`、`contracts/`、`migrations/`、`scripts/`、`docs/` |

发布分支提交序列（`1104-llb`）：

```
2206b94 style(live): 格式化 adapter_factory
694c1e1 docs(evidence): 任务卡、验收证据与进度索引
22ec75e feat(ui): 直播达人详情面板与定时更新管理页
16f21e7 feat(update): UPD-06 四场景定时更新服务与迁移 022
5417c34 feat(live): 补齐双平台直播达人详情字段与筛选契约
d9f263e docs(live-02f) / f963cc7 / 66f8be0 / 3502c92  ← LIVE-02、LIVE-02F（此前未推送）
```

## 2. 功能变更（按实际 Git 差异）

### 新增

- 巨量星图直播达人详情：`live_overview` / `live_analysis` / `live_audience` /
  `live_pricing` 四个模块 + 基础资料扩展（抖音号、内容标签、商单类型、介绍、微信）。
- 磁力聚星直播达人详情：基础/报价/概览/指数/代表作品/粉丝趋势/受众画像/带货数据/
  合作数据/客户评价 十个模块（`juxing_live_fields.py`）。
- 定时更新四场景：`(douyin_xingtu|kuaishou_juxing) × (video_square|live_square)`
  独立开关、调度器心跳、管理 API 与 `/settings` 页面（UPD-06）。
- 直播详情前端页面：星图/聚星两套板块、月历、趋势图、画像分布。
- 迁移 `021_live_square_creator_scene.sql`（直播快照场景）与
  `022_creator_update_services.sql`（计划场景维度、四组开关、心跳、聚星详情定位）。
- `scripts/backfill_video_homepage.py`：聚星短视频详情定位一次性回填（默认只读）。

### 修改

- 直播筛选契约：星图直播「粉丝画像 + 观众画像」改为互斥（`incompatible_with`），
  P1 直接字段级拒绝。
- 重试策略：候选缺少 checkpoint 预期模块时视为可重试（修复预算中断后无法恢复）。
- 达人库直播读取：作品标签支持 `content_type_labels`；列表载荷裁剪、失败模块回退。
- 聚星短视频手动/定时更新：详情页缺失时自建广场页，替代 `JUXING_SEARCH_PAGE_MISSING`。

### 修复

- 兼容 LIVE-03 之前采集的星图直播快照：新详情页原本只读四个新模块，会把旧快照渲染成
  「平台未返回…」并隐藏已采集指标；现按快照内容回退到平台原生指标条并标注原因。
- 测试中的真实达人微信值替换为合成值（发布前移除，未进入 Git 历史）。
- 时间戳越界/毫秒值不再抛出 `ValueError`/`OverflowError` 使整任务失败。
- 可选模块 schema 不匹配只降级该模块，不再中断整个直播任务。
- 评价摘要不再因评价列表失败而丢弃已采集的评分。

### 不受影响

- 巨量星图短视频采集链路（适配器选择仅对 `live_square` 生效）。
- 聚星短视频采集主链路（仅新增定位回填与自建广场页恢复路径）。
- 任务状态机、分页、并发与执行单元池未改语义。

## 3. Windows 部署前必须处理

### 3.1 数据库迁移（顺序不可颠倒）

1. **先备份**业务库。
2. 停止 API、intake worker、collection worker、update scheduler。
3. 应用 `021`、`022`：

   ```bat
   .venv\Scripts\xingtu.exe migrate --environment <环境名>
   ```

4. 校验 022 已生效（**必须全新应用，不能沿用草稿库**）：

   ```sql
   SELECT version FROM schema_migrations WHERE version IN (21,22);
   SELECT column_name FROM information_schema.columns
    WHERE table_name='platform_creators' AND column_name='video_homepage';
   SELECT platform, creator_scene, enabled FROM creator_update_service ORDER BY 1,2;
   ```

   预期四行开关：仅 `douyin_xingtu/video_square` 为 `true`，其余三组为 `false`。

5. 回填聚星短视频详情定位（先只读，确认后再写）：

   ```bat
   .venv\Scripts\python.exe scripts\backfill_video_homepage.py
   .venv\Scripts\python.exe scripts\backfill_video_homepage.py --apply
   ```

> ⚠️ 新代码在**每一次非直播采集发布**时都会写 `platform_creators.video_homepage`。
> 未应用 022 就启动新代码会导致所有采集落库失败。

### 3.2 环境变量

| 变量 | 用途 | 说明 |
|---|---|---|
| `XINGTU_DATABASE_URL` | 业务库 | scheduler 缺失会以 `STORAGE_UNAVAILABLE` 退出 |
| `XINGTU_REDIS_URL` | 登录限流 | 缺失时登录报 `LOGIN_LIMITER_UNAVAILABLE` |
| `PYTHONUTF8=1` | **Windows 必须** | 契约 JSON 含中文；中文 Windows 默认 cp936 会导致启动解码失败 |
| `XINGTU_REGISTRY_PATH` | 星图短视频契约 | 可由 unit config `registry_path` 提供 |
| `XINGTU_LIVE_REGISTRY_PATH` | 星图直播契约 | 同上 `live_registry_path` |
| `XINGTU_JUXING_REGISTRY_PATH` | 聚星短视频契约 | — |
| `XINGTU_JUXING_LIVE_REGISTRY_PATH` | 聚星直播契约 | — |

四个 registry 路径缺失只会**静默停用对应更新组**（心跳里留 `scope_error`），不会阻止其它组。
每个可能接收定时更新的执行单元配置都必须配置 `live_registry_path`，否则直播组任务会停在
`WAITING_FOR_RESOURCE` 并长期占住该组。

### 3.3 依赖

- **无新增 Python / 前端依赖**：`pyproject.toml`、`uv.lock`、`package.json`、`package-lock.json`
  本次均未改动。Windows 侧仍按 `uv sync --frozen` 与 `npm ci` 安装。
- `tzdata` 通过 `psycopg` 在 Windows 上间接提供 `ZoneInfo("Asia/Shanghai")`；若改用精简环境，
  需显式安装 `tzdata`。

### 3.4 服务与启动参数

```bat
:: API
.venv\Scripts\xingtu-api.exe

:: 采集 worker
.venv\Scripts\xingtu.exe worker --config <unit-config.json>

:: intake worker
.venv\Scripts\xingtu-product.exe intake-worker --unit-config <unit-config.json>

:: 定时更新调度器（新增 --tick-seconds）
.venv\Scripts\xingtu-product.exe update-scheduler --unit-config <unit-config.json> --batch-size 5 --tick-seconds 60
```

- `Makefile`、`dev.sh`、`nohup` 均为 POSIX 写法，**不要**在 Windows 使用；用服务包装器或
  「任务计划程序」托管，并开启自动重启与日志轮转。
- 迁移 022 默认只开启「星图短视频」一组；其余三组需在 `/settings` 页面逐组验收后开启。

### 3.5 调度与时间

- 到期判断使用数据库 `now()`，失败退避与心跳存活判断使用主机 `utcnow()`；
  **必须开启 NTP 时间同步**，否则会出现「显示未运行」或提前重试。

### 3.6 Chrome / Playwright

- 浏览器安装方式与启动参数本次未改；仍为 `playwright install chromium` + 项目独立 profile。
- 直播详情页访问显著增加：聚星达人最多 50 页评价、星图达人月历/近 15 场/90 天场次/多口径
  概览。**未在 70 位任务上验证 Windows 端耗时**，首次部署建议先用 1—2 位达人试跑。

### 3.7 macOS 相关代码

- 生产代码（`backend/src`）未发现 macOS 专属 API、绝对路径或 shell 调用。
- 仅存在 macOS 属地的运维脚本/配置：`Makefile`、`dev.sh`、`.runtime/units/*.json` 中的
  `/Users/...` 路径。这些**不入库**，需在 Windows 重新生成指向 Windows 路径的 unit config。

## 4. 本次验证结论（Windows 之前）

在 macOS 本机、真实 PostgreSQL 18 隔离库上执行：

| 检查 | 结果 |
|---|---|
| `make test-unit` | 456 passed |
| `make test-contract` | 43 passed |
| `make test-integration` | 149 passed, 1 skipped（含迁移 021/022 全新应用） |
| 前端 `tsc -b` | 通过 |
| 前端 `vitest` | 132 passed |
| 前端 `vite build` | 通过 |
| 改动文件 ruff check / format / mypy | 全部通过 |
| `make test-e2e` | 6 passed / 8 failed：全部因本机缺少 Temporal dev server 二进制（离线无法下载），非代码缺陷 |

**未执行**：双平台 70 位全量真实采集复跑；Windows 实机验证。因此**不得**把 Windows 兼容性记为
「已通过」。

## 5. 已知风险与遗留

1. **仓库当前为公开（public）**：未认证即可读取。`contracts/` 与 `docs/evidence/assets/`
   包含真实平台达人昵称、平台 ID 与验收截图。若甲方要求保密，应先转为私有仓库。
2. 定时更新组内「单条坏定位」会让整组目标构造失败：目前无逐行跳过/隔离，需人工修正
   `video_homepage`。默认三组关闭，风险受限。
3. 管理页 `registry_available` 反映的是注入的 scope 列表，调度失败原因不会回写为
   `unavailable_reason`；开启新组后需监控心跳与 `last_result.errors`。
4. 直播组任务可能长期停在 `WAITING_FOR_RESOURCE`（unit 未配 `live_registry_path`）或
   `WAITING_FOR_LOGIN`，不会自动终结。
5. 若某环境曾用「022 草稿」写入过 `schema_migrations(22)`，`make migrate` 会跳过 022，
   必须按 §3.1 手工核对表结构。
6. 星图直播房详情指标按请求录制序号关联，极端时序下可能漏配为 NO_DATA；本次未改。
7. 星图直播交互层（分页、选择器、口径遍历）缺少自动化测试，仅有真实任务验证。
8. 仓库级 `make lint` / `make format-check` 仍因三个历史验收脚本
   （`run_cd05/06/07_acceptance.py`）失败，与本次发布无关，未在本次修复。

## 6. 回滚

1. 停止所有服务。
2. `git revert` 合并提交 `2c03c7d`（或部署上一版本代码）。
3. 恢复备份数据库。**不要**让旧版本二进制连到 schema 22：旧的更新对账按 `creator_id`
   写入，会在双场景计划表上写错行。
4. 022 本身不重写历史业务数据；必要时可删除 `live_square` 计划行并恢复
   `creator_update_schedule` 原主键。
