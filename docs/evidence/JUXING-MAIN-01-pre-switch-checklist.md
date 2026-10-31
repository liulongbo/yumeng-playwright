# JUXING-MAIN-01 主站切换前检查清单（授权门 B）

状态：**历史文档**。授权门 B 已于 2026-10-31 02:21 批准，P4–P6 已执行完成（GO）；本文记录切换前实测状态，最新结果见 [JUXING-MAIN-01 验收](JUXING-MAIN-01-acceptance.md)。  
生成时间：2026-10-31T02:18+08:00  
关联：[任务卡](../tasks/JUXING-MAIN-01.md)、[整合方案](../design/JUXING-MAIN-01-integration-plan.md)、[测试用例](JUXING-MAIN-01-test-cases.md)。

> 切换前实测（历史）：主站当时仍为星图 only——主库没有聚星绑定、聚星 Flag 未开启、主站未重启、4193 未停止、未发起真实主站采集。以下为当时的切换条件与授权请求；P4–P6 已在此后执行并验收。

## 1. 已完成的代码与自动测试

| 项 | 结果 |
|---|---|
| 任务中心平台筛选（后端） | `GET /api/tasks?platform=`；`ProductQueries.list_tasks(platform=...)`；SQL `r.platform=%s`；cursor scope 纳入 platform；非法值 422 |
| 任务中心平台筛选（前端） | 任务中心「全部平台 / 巨量星图 / 磁力聚星」下拉；切换重置 cursor；原有搜索/状态/类型/日期筛选不变 |
| 后端单元 + 合同 | **409 passed**（52–53s） |
| 隔离集成（全新空库 `xingtu_test_juxing_main`） | **121 passed / 1 skipped**（S3 未配置）；新增 3 条本轮测试 |
| E2E | **14 passed**（30.73s，含聚星 Temporal/全栈） |
| 前端 | **105 passed** + lint + build |
| Mypy | backend/src 38 files，无问题 |
| 定向 Ruff/format | 本轮改动文件全部通过 |
| 全仓 Ruff | 仍有 **38 个既有错误**（`scripts/acceptance/*` 11×UP031、`scripts/qa/kjx_full_mcp.py` E501/F841），与本轮无关，未掩盖 |

新增文件：`scripts/juxing_main_switch.py`、`backend/tests/integration/test_task_platform_filter.py`、`backend/tests/integration/test_juxing_main_baseline.py`、`backend/tests/unit/test_juxing_main_switch.py`。  
修改文件：`backend/src/xingtu/product_queries.py`、`backend/src/xingtu/product_api.py`、`backend/tests/unit/test_product_api.py`、`frontend/src/pages.tsx`、`frontend/src/App.test.tsx`。  
说明：前端源码已更新，5173 的 Vite 会热更新显示平台下拉；但 8000 API 未重启，服务端筛选在 P4 重启后才生效。当前不影响星图任务读取。

## 2. 主库当前 Schema 与历史数据基线

| 项 | 实测 |
|---|---|
| `schema_migrations` | 20（020 已应用；**本轮无需迁移**） |
| `root_tasks` | 117 全 `douyin_xingtu`；CANCELLED 23 / COMPLETED 19 / FAILED 11 / FAILED_VALIDATION 1 / PARTIAL_COMPLETED 63 |
| `platform_creators` | 138 星图；聚星 0 |
| 关联/快照 | `task_creators` 293、`creator_snapshots` 355、`task_dispatches` 129、`requirements` 80、`filter_plans` 84 |
| 精选/素材 | `featured_collections` 585、`featured_cards` 1964、`media_objects` 5655、`raw_evidence` 40 |
| 更新资格 | `creator_update_schedule` 90（调度器未运行） |
| 执行单元 | `unit-local-mac-02` READY；owner/lease/current_task 空；browser_stopped=true |
| 平台绑定 | 仅 `(unit-local-mac-02, douyin_xingtu)`；无聚星行 |
| 在途/验证 | 非终态任务 0；OPEN/ACKNOWLEDGED 验证 0；REQUESTED/ACTIVE/VERIFYING 接管 0 |

内容哈希基线（`md5(string_agg(md5(row::text)))`，UTC 会话，按 baseline ID 列表）：

| 范围 | count | md5 |
|---|---:|---|
| root_tasks | 117 | `5c6042685de5f7e0d84f1e53e5bad968` |
| platform_creators | 138 | `eecc5e247445d495b301d8cff0806f30` |
| task_creators | 293 | `41f42afe54d63917df94beb8f995f27f` |
| creator_snapshots | 355 | `1bf6601153348562fba69fb2e6bea2f8` |
| douyin_xingtu_creator_current | 138 | `32316dab1cf021ff2428cd790acd029b` |
| requirements | 80 | `5b7ec3d918b17184d8930b3519384967` |
| featured_collections | 585 | `fb44e098171ddb1f5daf3cc2217d689c` |
| featured_cards | 1964 | `64ae2b8ce8a1b8ae936bf3f604fbae31` |

完整 17 组哈希、单元/绑定不可变字段与基线 ID 列表见 `.runtime/juxing-main/baseline.json`（0600）；空闲复核 `compare-idle.json` 为 PASS。

> 内容口径：`row::text` 已包含 JSONB 原文（`platform_creators.projection`、`creator_snapshots.payload`、`requirements.payload`、`filter_plans.payload`、精选 collection/card payload）与历史快照；compare 还会单独比对 `execution_units` 与 `douyin_xingtu` 绑定的不可变字段（账号/Profile/registry/enabled），并固定 UTC 会话，避免时区导致假差异。

**4193 测试库数量修正**：实测 **8 条任务**（聚星 5：COMPLETED 3 / PARTIAL_COMPLETED 2；星图 3：COMPLETED 2 / PARTIAL_COMPLETED 1）、**39 位聚星达人**、3 位星图达人。OPS-05 的“6 条”是当时快照；方案初稿把总数写成 6 与明细合计 8 是笔误，以本表为准。4193 数据不导入主库。

**独立记录的测试缺陷**：`backend/tests/integration/test_migrations_020.py` 的 `information_schema.columns` 查询未限定 `table_schema`，在 public schema 已有迁移表的共享测试库会误报 `1 == 0`；全新空库通过。本轮不修改该测试，改用全新空库运行，并保留记录（后续应补 `table_schema = current_schema()`）。

## 3. 备份与恢复演练

| 项 | 结果 |
|---|---|
| 主库备份 | `.runtime/backups/juxing-main-20261031T021309/xingtu_development-pre-juxing-main.dump`（35,539,606 bytes，Custom/gzip，TOC 231，0600） |
| 校验和 | `sha256 055a98ba41838d914a25912cf00f254ac1a48fd3a0894d4afcbc046e8576d521` |
| 配置备份 | `m3-app.env.pre-switch`、`local-dev-mac-02.json.pre-switch`（0600） |
| Profile/快照备份 | `juxing-profile-and-snapshot.tar.gz`（0600，172,661,570 bytes） |
| 恢复演练 | 测试集群建 `xingtu_test_restorecheck_*` → `pg_restore --no-owner --no-privileges` 成功 → 与 baseline 同口径 count+md5 对比 **全部一致** → 临时库已删除 |
| 演练发现 | 首次对比出现差异，根因是 `row::text` 按会话时区渲染 timestamptz（主库 Asia/Shanghai，测试库 UTC）；工具已固定 UTC，重采 baseline 后复验 PASS。不是数据损坏 |
| 主库空闲复核 | baseline 后 `compare` 无漂移，主库未被改动 |

## 4. 执行单元与 Profile 是否满足切换条件

| 检查 | 结果 |
|---|---|
| 单元 | `unit-local-mac-02` READY；无 owner/lease/current_task；browser_stopped=true |
| 星图 Profile | `.runtime/profiles/unit-local-mac-02` 存在；项目锁 **FREE**；无 Chrome 占用 |
| 聚星 Profile | `.runtime/profiles/unit-local-mac-02-juxing` 存在、0700；项目锁 **FREE**；无 Chrome 占用 |
| Profile 隔离 | 两目录不同；不共享 Cookie/登录状态 |
| 聚星账号 | 候选绑定 `60821564`，与已验证子账号一致 |
| 聚星合同 | `juxing-video-creator-stage-c-v3`，`require_enabled(live=True)` 通过；第 3 页 fail closed |
| 聚星快照 | `.runtime/storage-state/unit-local-mac-02.kuaishou_juxing.json` 存在、0600、192,248 bytes、`unit_id=unit-local-mac-02`、captured 2026-10-28T08:03:59Z、23 个 Cookie（仅统计，未打印值） |
| 绑定冲突 | 主库无 `(unit-local-mac-02, kuaishou_juxing)`、无同 `account_ref`、无同 `profile_ref`；0 冲突 |
| 预检 | **48 项 0 失败**（`.runtime/juxing-main/preflight-pre-switch.json`） |
| 尚未验证 | 主站聚星会话的**实时有效性**（快照采集于 2026-10-28；P5 前需只读探测） |

注意：主库 `execution_units` 与星图 binding 的 `profile_ref` 仍是旧仓库绝对路径（`/Users/yaoyao/Documents/...`），运行时以单元配置为准；本轮不改不可变字段，记录为剩余风险。

## 5. 需要修改的配置与数据库记录

### 5.1 私有环境（未应用）

文件：`.runtime/m3-app.env`（先备份；已准备候选增量 `.runtime/juxing-main/juxing-main.env.additions`）

```text
XINGTU_ENABLE_KUAISHOU_JUXING=1
XINGTU_JUXING_REGISTRY_PATH=/Users/Longbo/Developer/YUMENG/contracts/kuaishou_juxing.verified.json
XINGTU_KUAISHOU_JUXING_MAX_TARGET_COUNT=30
```

### 5.2 单元配置（未应用）

文件：`.runtime/units/local-dev-mac-02.json`（先备份；候选 `.runtime/juxing-main/local-dev-mac-02.candidate.json` 已通过预检“只增加绑定、不改星图字段”）

```json
"platform_bindings": [
  {
    "platform": "kuaishou_juxing",
    "account_ref": "juxing-account-02",
    "expected_account_id": "60821564",
    "profile_directory": "/Users/Longbo/Developer/YUMENG/.runtime/profiles/unit-local-mac-02-juxing",
    "registry_path": "/Users/Longbo/Developer/YUMENG/contracts/kuaishou_juxing.verified.json",
    "enabled": true
  }
]
```

### 5.3 主库绑定（未写入）

collection worker 启动时由 `register_unit_platform_binding()` 幂等写入：

```text
(unit-local-mac-02, kuaishou_juxing, juxing-account-02, 60821564,
 /Users/Longbo/Developer/YUMENG/.runtime/profiles/unit-local-mac-02-juxing,
 /Users/Longbo/Developer/YUMENG/contracts/kuaishou_juxing.verified.json, enabled=true)
```

不修改星图绑定行、不修改 `execution_units` 行、不改表结构、不新增迁移。

### 5.4 进程与执行顺序（未执行）

1. `./.runtime/kjx-full/stack.sh stop` 停止 4193 整栈（保留数据/配置/证据）。
2. `./.runtime/dev-no-upd.sh stop` 停止主站 4 进程（确认无在途任务；`update-scheduler` 保持关闭）。
3. 应用 5.1/5.2；等待 >45s 心跳窗口。
4. `./.runtime/dev-no-upd.sh up` 启动 API/intake/collection/前端。
5. 验证：`/api/platforms` 双平台、聚星 binding 行、两队列消费者、执行单元页两平台标签。
6. 聚星会话只读探测 → 通过后从 5173 发起真实任务。

### 5.5 预期新增数据（授权范围内）

- 1 条聚星 root task、1 位聚星达人、对应 `task_creators`/`creator_snapshots`/`audit_logs`；
- 1 条星图 root task；若命中既有达人则星图达人仍 138，否则 139；
- 不导入 4193 的 8 条任务/39 位达人。

## 6. 是否存在正在执行的任务

**没有**：主库非终态 root task 0；单元无 owner/lease/current_task；无 OPEN/ACKNOWLEDGED 验证；无 REQUESTED/ACTIVE/VERIFYING 接管。4193 当前也无在途任务（8 条均终态）。

## 7. 预计对现有星图功能的影响

- 不改星图代码、合同、Adapter、F04/F05/F06、完成判定、更新/定时语义；不改星图任务/达人/快照数据。
- 影响仅为：主站 4 进程重启期间 API/前端短暂不可用（约 1 分钟，无在途任务）；worker 重启后 generation+1；`update-scheduler` 继续关闭。
- 主站新增聚星入口与聚星绑定；星图仍是默认平台，历史任务/达人/更新资格不变。
- 前端平台下拉已热更新但服务端筛选在 API 重启后生效；不影响星图读取。
- 如果回退 Flag，聚星入口关闭，星图保持正常。

### 7.1 关闭聚星 Feature Flag 对在途任务的实际影响（代码核实）

- **入口/新建任务**：Flag=0 时 `/api/platforms` 聚星 `enabled=false`，`/api/platforms/kuaishou_juxing/capabilities` 与 `POST /api/tasks` 的聚星请求被 `KUAISHOU_JUXING_FEATURE_DISABLED` 拒绝；不会产生新的聚星任务。
- **已入队/执行中的任务**：Flag 只存在于 API 产品层，**Intake Worker 与 Collection Worker 不读取该 Flag**；任务分配依据 `execution_unit_platform_bindings` 与平台 registry。因此关闭 Flag **不会取消或暂停**已经 QUEUED/COLLECTING 的聚星任务，它仍会继续执行到终态。Flag 不是 worker kill switch。
- **数据**：关闭 Flag 不删除、不回滚任何任务/达人/快照；任务中心列表、任务详情、达人库聚星读接口都不以 Flag 为门禁，已入库聚星数据仍可查询。聚星入口按钮会因 `/api/platforms` 变为 disabled。
- **要停止在途工作**：只能使用既有任务取消动作，或停止 collection worker/单元（需单独授权），不能把“关 Flag”描述成“停止任务”。
- **回退建议**：若只需关闭新入口，Flag=0 即可；若要确保没有聚星任务继续执行，先确认无在途，再按第 8 节处理，不直接删除已入库数据。


## 8. 回退步骤

| 场景 | 步骤 |
|---|---|
| 只关闭聚星 | Flag=0（或移除）→ 重启 API；星图不变；**不会停止已入队/执行中的聚星任务**，如需停止另用取消/停 worker |
| 撤销聚星绑定 | 单元配置 `enabled=false`（或移除）→ 重启 collection；只允许改 enabled，不删星图行 |
| 配置写错/启动失败 | 用 `.runtime/backups/juxing-main-20261031T021309/*.pre-switch` 覆盖 → 重启 |
| 真实任务异常但数据可接受 | 保留任务/快照，按 `PARTIAL_COMPLETED` + `failure_reason` 记录；重试需单独授权 |
| 数据损坏 | 停写 → 用切换前 dump 恢复（需单独授权）；本轮聚星行可按 ID 精确删除（需授权） |
| 恢复 4193 | `./.runtime/kjx-full/stack.sh up`（数据/脚本保留） |

## 9. 剩余风险

1. 主站聚星会话未实时验证；快照为 2026-10-28。失效时按方案：先备份，再复制 4193 已验证快照（4193 已停、同账号），仍失败则请用户人工登录；不自动选子账号。
2. 星图真实 1 位任务可能触发安全验证；按既有 15 分钟流程，不绕过；超时如实部分完成，**同范围重试需再次授权**。
3. 真实队列可能未出现跨平台重叠（任务耗时差）；若未出现，用隔离并发测试补充，报告明确标注“非真实重叠”，不虚报。
4. 主库星图 binding 的旧 `profile_ref` 为历史遗留展示字段，不影响运行但审计时需说明。
5. `test_migrations_020.py` 的 schema 限定缺陷仍在（测试层，不影响产品）；本轮不修。
6. 4193 在 P4–P5 期间离线；数据/配置保留，可随时恢复。
7. 当前工作区有 84 个既有/本轮未提交改动；本轮不 commit/push/merge。

## 10. 请求授权的 P4–P6 事项

1. 停止 4193 整栈（保留数据）。
2. 应用 5.1/5.2 私有配置。
3. 重启主站 API/intake/collection/前端（`update-scheduler` 保持关闭）。
4. 由 collection worker 在主库注册聚星绑定（5.3）。
5. 对主站聚星会话做一次只读探测（打开聚星找达人受保护页，不采集）；失效时按第 9 节处理。
6. 从 5173 UI 发起 **1 位真实聚星**（母婴/母婴亲子/target=1）与 **1 位真实星图**（宠物/target=1）采集。
7. 允许使用 Playwright MCP + Chrome 执行测试用例并采集脱敏证据。
8. 更新运行文档、验收证据与任务卡，给出 GO/CONDITIONAL GO/NO-GO。

不请求授权：Schema 迁移（不需要）、4193 数据导入、Git commit/push/merge、Windows、扩大真实样本、分页新能力、修改星图/聚星已验证业务规则。
