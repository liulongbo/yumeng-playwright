# F06 主页精选作品采集与封面存储：离线验证证据（2026-09-27）

> 结论先行：**F06 的领域契约、两组默认集合 Adapter、集合/卡片/作品身份/快照迁移、模块内加载与覆盖证据、检查点与集合变化恢复、受控封面管道、Engine 完整度与终态均已实现并通过四层离线测试（129 项通过）**。
> **未执行**：真实星图登录与 U05 真实默认集合边界/终点/字段/封面来源核验、U09 对象存储服务（MinIO/S3）与认证图片访问的实机验收。因此本卡不能标为“已完成”，保持**待验收**。
> 命令原始记录见 [F06-offline-verification.log](F06-offline-verification.log)。

## 1. 执行环境（本轮实测）

| 项目 | 实际值 | 核实方式 |
|---|---|---|
| 操作系统 | macOS 26.5.2 | `sw_vers -productVersion` |
| Python | 3.13.5（`.venv`） | `.venv/bin/python -V` |
| Playwright | 1.63.0 | `importlib.metadata.version("playwright")` |
| 随包 Chromium | `chromium-1243`（`PLAYWRIGHT_BROWSERS_PATH=.runtime/browsers`） | 契约测试实际启动 |
| PostgreSQL | 18.3，`127.0.0.1:55439`，角色 `xingtu_test`；测试库 `xingtu_test_f04f05`、开发库 `xingtu_local_dev` | `psql`、`schema_migrations` |
| Temporal | Python SDK 1.33.0 本地测试服务器（`.runtime/temporal-test/temporal-v1.9.1`） | E2E 实际运行 |
| Docker / 对象存储服务 | 守护进程不可用；无 MinIO/S3 实例 | 未执行项见 §6 |
| 会话 MCP | 本会话无已接入的自动测试 MCP；`cordis_inspect_list` 的 Tool 目录中不存在测试类工具 | Harness 工具目录实测 |

## 2. 本轮实现落点

| 内容 | 落点 |
|---|---|
| 两组默认集合与封面领域类型：`CollectionType`/`CollectionStatus`/`CoverStatus`/`CoverRef`/`FeaturedCard`/`FeaturedCollectionObservation`（顺序、身份、截断、覆盖缺口与备注、集合指纹、封面结果折叠） | `backend/src/xingtu/domain.py` |
| 卡片字段截断标记 | `domain.py`（`FieldObservation.truncated`） |
| 检查点扩容：`featured_collection_types`、`featured_card_fields`、`featured_checkpoint_versions`；候选扩容：`collections`/`collection_history` | `domain.py` |
| 任务记录：`featured_status`、`featured_complete_count`、`pipeline_complete`（不再固定 false） | `domain.py` |
| 契约：`FeaturedCollectionSpec`（入口、动作、就绪与加载提示、请求契约、`cards_path`、身份/链接/周期/集合标识/终点路径、卡片字段、模块级缺失证据、检查点版本）、`CoverSpec`（主机/类型/大小/超时/重定向上限）、`RequestSpec.repeats` | `backend/src/xingtu/contracts.py` |
| 发布门槛：两组默认集合只能同时注册、卡片字段与请求引用校验、链接与封面主机范围校验、featured `entry` 必须留在已核验主页路径范围内 | `contracts.py`（`_check_featured`） |
| 受控封面：下载（页面会话内、逐跳主机复核、显式重定向计数、超时/类型/大小）、对象写入后读回校验、`STORAGE_UNAVAILABLE` 失败语义、未引用对象清理 | `backend/src/xingtu/covers.py` |
| 迁移 003：`contents`、`featured_collections`、`featured_cards`、`snapshot_collections`、`media_objects`，集合与卡片表为追加式（触发器拒绝 UPDATE/DELETE） | `migrations/003_featured_collections.sql` |
| 仓储：集合/卡片/身份/快照关联的追加式持久化、`featured_complete`、`pipeline_complete`、`retryable`（含两组集合）、`cover_reference`（任务内认证访问） | `backend/src/xingtu/repository.py` |
| Adapter：`collect_featured_collections`（每组独立判定、单组失败不丢另一组）、模块内增量加载合并、组内去重与 `reload_count`、跨组身份复用、终点与覆盖证据、卡片字段解析（响应行内路径 / DOM 第 n 个节点）、`fetch_cover` | `backend/src/xingtu/adapter.py` |
| Engine：精选采集编排、复用/新观测规则、封面先校验后引用、失败不清空已提交观测、F05+F06 全步骤完整度与 `COMPLETED`/`PARTIAL_COMPLETED` | `backend/src/xingtu/engine.py` |
| 执行单元配置：`covers`（`local`/`s3`）与 Worker 装配 | `runtime.py`、`worker.py` |
| CLI：`xingtu cover-gc`、`doctor`/`status` 输出两组集合与封面状态、`start` 传两组契约版本 | `backend/src/xingtu/cli.py` |
| 测试：35 项单元、3 项浏览器契约、3 项集成、1 项 E2E | `backend/tests/unit/test_featured.py`、`backend/tests/contract/test_featured_browser.py`、`backend/tests/integration/test_featured.py`、`tests/e2e/test_temporal.py` |
| 合成数据与夹具（明确标注人工构造，不进入生产代码） | `backend/tests/synthetic.py` |

## 3. 实际执行的验证与结果

### 3.1 静态检查

| 命令 | 结果 |
|---|---|
| `ruff check backend conftest.py tests scripts` | 通过，exit 0 |
| `ruff format --check backend conftest.py tests scripts` | 30 files already formatted，exit 0 |
| `mypy backend/src` | Success: no issues found in 15 source files |

### 3.2 四层测试（合成数据；不含真实平台流量）

| 命令 | 结果 |
|---|---|
| `pytest backend/tests/unit -q` | **87 passed**（基线 52 + F06 新增 35） |
| `pytest backend/tests/contract -q` | **13 passed**（真实 Chromium + 合成路由；基线 10 + 3） |
| `pytest backend/tests/integration -q` | **26 passed**（真实 PostgreSQL；基线 23 + 3） |
| `pytest tests/e2e -q` | **3 passed**（真实 Temporal 本地测试服务器；基线 2 + 1） |
| 合计 | **129 项通过**（基线 87 项，全部无回归） |

新增用例覆盖：

- 单元（`test_featured.py`）：`COMPLETE` 需已证明终点且无缺口；空态/无权限/不提供/失败/未执行各自的证据要求；卡片位置唯一且从 0 连续；截断标记与字段状态一致；集合指纹随有序集合变化；封面失败使集合不得为完成；`CoverRef` 只有校验通过才携带对象引用；封面管道的主机/重定向/类型/大小/空响应/非 200/存储校验失败/缺源/传输失败分支；两组默认集合注册表可发布与 18 项不可发布原因（缺一组、重复组、契约不全、重复卡片字段、未声明请求、缺单位、缺链接字段/范围、封面字段未声明、封面范围非法、空定位符、非法入口、越界主机、歧义缺失证据、缺回退触发、入口越出主页范围）。
- 浏览器契约（`test_featured_browser.py`，真实 Chromium + 合成路由）：两组模块默认集合与模块内增量加载（同组重复加载去重并计数）、响应中越界作品不采集、跨组同作品身份复用但指标独立、标题截断标记、真实零/近似值（`1.2万`→12000 approximate）、无链接标记、封面经真实页面会话抓取并写入对象存储、未证明终点→`INCOMPLETE`、无权限→`NO_PERMISSION`、单组读取失败不影响另一组、模块周期标签只在页面提供时保存（缺失时不补造）。
- 集成（`test_featured.py`，真实 PostgreSQL）：完整运行 →`COMPLETED` 且 `pipeline_complete`；两组集合/卡片/身份/快照关联落库；同作品一条 `contents` + 两组独立卡片；封面对象被任务引用可访问、跨任务不可访问；未引用对象清理只删孤儿且保留已发布封面；单组失败保留另一组并报 `PARTIAL_COMPLETED`/`FEATURED_COLLECTION_INCOMPLETE`；封面失败→重试补采生成新观测且旧观测与卡片原样保留；集合变化→新观测、历史追加不覆盖；相同已验证集合与集合键→复用原观测 ID。
- E2E（`test_temporal.py`）：真实 Activity + `CollectionWorkflow` 下 F05+F06 完成态传播为 `COMPLETED`、工作流历史可回放、同作品跨组仅一个封面对象。

### 3.3 迁移与 CLI（本地开发库实测）

| 命令 | 结果 |
|---|---|
| `xingtu migrate --environment development`（`xingtu_local_dev`） | 成功；`schema_migrations` = {1,2,3} |
| 再次 `xingtu migrate` | `all pending migrations applied or already present`（幂等） |
| `psql` 表清单 | `contents`、`featured_cards`、`featured_collections`、`media_objects`、`snapshot_collections` 均存在 |
| `xingtu doctor` | `featured_collections: []`、`featured_status: NOT_ATTEMPTED`——未核验注册表未启用 F06，门槛未被削弱 |
| `xingtu cover-gc --config .runtime/units/gate-check.json` | `{"removed": [], "count": 0}`（本地实现；无孤儿对象） |

## 4. 验收清单与证据映射

| 验收项 | 离线证据 | 状态 |
|---|---|---|
| 两组集合独立顺序/指标/口径/观测时间/覆盖状态；模块内加载完整，不采集越界作品 | 单元 `test_featured_registry_is_publishable`/领域用例；契约 `test_two_modules_incremental_load_identity_and_bounds` | 离线满足；真实边界待 U05 |
| 同作品身份复用但不合并两组指标；无身份用局部键保留、不按标题合并；不按发布时间排除 | 集成 `test_full_run_is_complete_and_persists_identity_snapshots_and_covers`；契约 `link`/身份断言；契约中不存在时间筛选参数 | 离线满足 |
| 空态/无权限/不提供/截断/字段失败/未执行有依据；终点不可确认即不完整 | 契约 `test_absence_incomplete_and_endpoint_evidence`；单元状态用例 | 离线满足 |
| 封面主机/重定向/类型/大小/超时与线路；校验成功才引用；失败可恢复；认证访问与未引用清理 | 单元封面分支；契约真实抓取；集成 `cover_reference`/`cleanup_unreferenced`；`xingtu cover-gc` | 离线满足；S3/MinIO 与真实 CDN 待 U09 |
| 中断/重试后集合变化产生新观测、旧快照与归属保持；单组失败不丢另一组 | 集成 `test_collection_reuse_change_recovery_and_cover_retry`、`test_single_collection_failure_keeps_the_other_and_reports_partial` | 离线满足 |
| 完整数、`COMPLETED`/`PARTIAL_COMPLETED` 按 F05+F06 全部步骤判断；兼容原有任务/快照/检查点 | 集成完整度用例；E2E 终态与回放；迁移 003 已应用于既有库 | 离线满足 |
| U05 真实默认集合与封面来源核验、U09 对象服务验证 | 未执行 | **未满足（待验收）** |
| 通过本卡 T 用例 | T08—T10/T24—T29/T41/T42 的离线部分见上；示例：T24 跨组身份/指标、T25 无发布时间筛选、T26 未证明终点、T27 集合变化、T28 截断/缺链接、T29 周期只随来源模块、T41 越界不扩大、T42 证据脱敏 | 离线满足；真实账号项未执行 |

## 5. 兼容性与迁移影响

- 迁移 003 只新增表与触发器，不修改既有表；已在既有 `xingtu_local_dev` 上顺序应用且可重复执行。
- 检查点与任务记录新增字段均有默认值，既有 `payload` 可反序列化；旧任务的 `pipeline_complete=false`、`featured_status=NOT_ATTEMPTED` 语义保持。
- 语义变化：`Engine.finish` 不再固定 `PARTIAL_COMPLETED`。未注册两组集合时仍为 `PARTIAL_COMPLETED`（原因 `FEATURED_NOT_ATTEMPTED`），注册并全部完成且达到目标时为 `COMPLETED`。
- 契约变化：`PlatformRegistry.featured` 为空表示本次不执行 F06；非空必须恰好是 `excellent_reach` 与 `excellent_seeding`。未核验注册表仍为空。
- 恢复到 `featured_collection_types` 与 Adapter 不一致的旧任务时按 `FEATURED_REGISTRY_CHANGED` 停止，不静默改变采集范围。

## 6. 未执行项与影响（不计为通过）

| 未执行 | 原因 | 影响 |
|---|---|---|
| U05：真实两组默认集合边界、模块内加载终点、稳定集合标识、作品 ID/链接、完整标题/副标题、封面来源 | 真实星图登录未完成（用户手机不在身边，无法接收验证码） | `contracts/douyin_xingtu.unverified.json` 的 `featured` 仍为 `[]`；真实默认集合与封面 CDN 白名单未登记；本卡不能标为已完成 |
| U09：对象存储服务（MinIO/S3）写入、认证图片访问、备份与告警 | 本机 Docker 守护进程不可用，无对象存储实例 | 仅本地文件实现被验证；`S3CoverStore` 未实测 |
| 真实账号小样本封面抓取与失败补采 | 依赖已核验注册表与会话 | 无真实封面证据 |
| 真实 `make smoke-local`/`smoke-live` 的 F06 正向运行 | 依赖已核验注册表 | 未取得真实采集证据 |
| 生产线路下的封面下载线路证明 | 生产阶段未开始 | 本地页内会话抓取不构成生产线路证据 |

## 7. 脱敏与隐私处理

- 测试与证据中不含真实平台数据：契约测试使用 `synthetic.invalid` 合成主机与人工构造 HTML/JSON；封面为人工字节。
- 封面下载不记录请求头、Cookie 或令牌；`media_objects` 只保存校验和、类型、大小与来源 URL。
- 证据日志位于 `docs/evidence/`，仅含命令与聚合结果，不含凭据、profile 或平台正文。
