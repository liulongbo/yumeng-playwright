# DIAG-01：巨量星图采集请求行为与验证触发专项诊断

状态：待验收（ISSUE-001 与 A3 均已实施并通过真实回归；等待用户审阅、合并决定与 5 项 C 级语义事项授权）
是否验收：否
更新时间：2026-10-16T00:05:00+08:00
关联功能：F05、F06、CHALLENGE-01、SESSION-01、UNIT-01、FILTER-01

## 目标与范围

回答一个业务问题：**为什么 Playwright 自动采集巨量星图达人数据时，比正常人工访问更容易遇到滑块验证或其他风控提示？**

本轮只做诊断与归因，产出有真实运行证据的问题清单与产品视角优化方案，**不实施任何修复**。

包含：

- 一次经用户授权的真实采集（产品前端提交，关键词「汽车」，目标 2 位，仅提交一次）。
- 全量请求分层普查（页面资源／已登记业务请求／埋点监控／心跳会话／重复／失败／重试），与既有计数器交叉校验。
- 八大维度分析（请求行为、访问路径、浏览器环境、交互过程、Temporal 调度与恢复、网络与接口异常、账号与会话生命周期、数据完整性与效率）。
- 历史线索复核（159 关联请求、69–84ms 异常恢复、ExecutionUnit 互斥）。
- 人工基线对照（用户手工走一遍同关键词、同场景，只读普查）。

明确不做：

- 不修改采集主链路语义（`adapter.py`、`engine.py`、`worker.py`、`workflow.py`、`observer.py`、`challenge.py`、`browser_host.py` 未改动）。
- 不破解或绕过验证码／滑块，不模拟人类轨迹，不伪造指纹，不轮换账号或代理。
- 不为获取验证样本反复触发风控；不扩大采集范围。
- 不实施任何优化；不提交、推送或合并 Git。

## 关联与依赖

- 前置：[F05](F05.md)、[CHALLENGE-01](CHALLENGE-01.md)、[FIX-01](FIX-01.md)、[UNIT-01](UNIT-01.md)、[FILTER-01](FILTER-01.md)。
- 执行单元：`unit-local-mac-02`；绑定账号 `ID: 1807978499337419`（`media-a`）；网络模式 `local_development`（数据库不可变）。
- 诊断代码版本：分支 `llb_1013`，HEAD `ee1125412a181e4df13fbe32ea0242a18ab02622`，工作区含用户未提交改动；逐文件 sha256 见 `.runtime/diag01/revision-sha256.txt`。
- 用户授权（2026-10-15）：① 真实采集 target=2／关键词「汽车」／仅提交一次；② 产品前端真实提交；③ 新增默认关闭的请求普查钩子；④ 做人工基线；⑤ 应用迁移 013、重启 API 与两个 worker。

## 验收清单

- [x] DIAG-01A 只读前置核对：Git 状态、服务状态、执行单元唯一控制者、`make m3-check`。
- [x] DIAG-01B 复核历史线索：159 关联请求口径与可复现性；69–84ms 恢复间隔；ExecutionUnit 互斥。
- [x] DIAG-01C 落地默认关闭的请求普查能力，并证明未设环境变量时零行为变化。
- [x] DIAG-01D 一次真实采集（产品前端提交 `381d628b-e6e8-4d0e-865e-ed4aab98c11c`，target=2，仅提交一次）。
- [x] DIAG-01E 全量请求分层统计与分类口径（L0=2698、L1=49、跨操作重复 1966）。
- [x] DIAG-01F 八大维度分析（含 Temporal 调度与异常恢复、网络与接口异常、数据完整性）。
- [x] DIAG-01G 人工基线对照（同一单元/profile/账号，同两位达人；对照窗口已对齐）。
- [x] DIAG-01H 问题清单（11 项，含证据/业务影响/严重程度/置信度）与产品优化方案（P0/P1/P2）。
- [x] DIAG-01I 未改动采集主链路；未实施任何修复；未提交 Git。

## 实现记录

- 2026-10-15T21:19+08:00：按用户授权重启 collection worker 并挂载普查（pid 86172）；重启脚本在执行前校验执行单元无租约，校验失败即拒绝重启（首次运行即因 `Repository()` 缺少 dsn 而安全中止，未影响在跑 worker）。
- 新增 `backend/src/xingtu/request_census.py`（仅新增文件）与 `runtime.py` 中一处默认关闭挂载点：仅当 `XINGTU_REQUEST_CENSUS` 指向文件时才挂载 Context 级 `request`/`response`/`requestfailed` 监听；未设置时行为与改动前一致。不记录查询串、Header、Cookie 或消息体；同 URL 只存 HMAC 短键用于重复识别。
- 新增 `scripts/diag/manual_request_census.py`（人工基线只读脚本，自身不导航、不点击）与 `backend/tests/unit/test_request_census.py`（7 例）。
- 新增 `.runtime/diag01/` 诊断脚本与产物（普查 jsonl、Temporal history、历史任务快照、UI 提交驱动）。
- 2026-10-15T21:22+08:00：`scripts/dev.sh up` 启动 API／intake worker／前端，并**接管**（未重启）已挂普查的 collection worker。前置自检 `PREFLIGHT_OK`。
- 2026-10-15T21:23+08:00：第一次提交因选择器错误（`input[type="number"]` 命中的是「连接用户」最小值而非「目标达人数量」）提交成 `target_count=20` 并附带一个非预期筛选。该任务在 30s 内自行以 `PLATFORM_PAGE_CHANGED:SEARCH_RESPONSE_FAILED` 失败，**采集 0 位达人**，未造成范围扩张。已如实记录，并在后续提交中加入**发送前硬校验**（拦截 `POST /api/tasks`，正文不符合授权参数即 `route.abort()`）。
- 2026-10-15T21:26+08:00：在硬校验通过后提交授权范围内的任务 `381d628b-e6e8-4d0e-865e-ed4aab98c11c`（`keyword=汽车`、`target_count=2`、无任何附加筛选、`requirement_form.v2`）。

## 验证证据

### 环境与前置

- Git：分支 `llb_1013`，HEAD `ee11254`；`git status --porcelain` 109 项（用户未提交改动，本轮只读保护）。
- `make m3-check`：`PREFLIGHT_OK`（12 项 ok；迁移 `applied=13 expected>=13`）。修复前为 `MIGRATIONS_APPLIED applied=12 expected>=13`。
- 唯一控制者：Temporal 任务队列各 1 个 poller（`xingtu-unit-local-mac-02`、`xingtu-intake`）；第二 checkout（`…/予梦/01-定向爬取+定时更新/`）无 collection worker 日志、api/intake 日志停在 2026-10-12，判定休眠。

### 历史线索复核（只读 SQL）

- **159 关联请求**：全仓仅 1 处（[DEC-015:7](../decisions/DEC-015-security-challenge-orchestration.md)），**无统计口径定义、无任务 ID、无证据路径**。所涉任务 `f47eb1cf` 当前 checkpoint 为 `observed_requests=201`，`task_checkpoints` 单行可变且无历史版本，故 **159 不可复现**，本轮按"来源不明的历史时点值"处理，不编造其分类。
- **69–84ms 异常恢复**：**完全可复现**。`audit_logs` 中 5 组 `transition_collect_to_maintenance` → `promote_maintenance_to_collect` 间隔为 84／73／76／69／81 ms（2026-10-10 06:26:18–06:27:13 UTC，actor 均为 `browser-host:5958ccac-…`）。该机制已由 `ChallengeHandler` 稳定窗口取代。
- **口径定位**：`observed_requests` 的定义是"仅命中已登记操作关联的请求，不是全部浏览器／网络流量"（[domain.py:956](../backend/src/xingtu/domain.py)）。且 `duplicate_request_count` 只在单个 `ResponseCollector` 实例内计数（[observer.py:205](../backend/src/xingtu/observer.py)），跨操作重复不计入 —— 历史"重复请求 0"不能证明无跨操作重复。

### 今日（2026-10-15）真实运行 `50c8edf4`（用户运行，只读复核）

- checkpoint：`observed_requests=62`、`navigation_count=9`、`duplicate_request_count=0`、`cover_request_count=8`、`featured_load_count=2`、`challenge_count=1`、`challenge_recovery_count=1`、`failure_counts={"LEASE_LOST":1,"SESSION_INDETERMINATE":1,"PLATFORM_SECURITY_CHALLENGE":1}`、`rescan_reasons=["CURSOR_INVALID"]`、`active_seconds=201.95`；20 候选、1 位有效达人。
- Temporal history（只读）：**两个 segment 各自出现 2 次 `collect_segment_v1` 执行，中间由 30s 定时器分隔**（run `01a13e24…`：activity 0.15s→92.5s，TimerStarted 30s，TimerFired 122.5s，第二次 activity 122.5s→263.0s；run `01a13f51…` 同型）。`WAITING_FOR_RESOURCE` 不在 workflow 显式唤醒集合内，因此走 30s 超时重跑整段 Activity。
- 真实验证事件（自然触发）：2026-10-15 14:00:04.967 检测到 `PLATFORM_SECURITY_CHALLENGE` → 14:00:10.707 恢复，间隔 5.740s。worker 日志原文：`challenge declared clear: stable_window=5.162s observed_for=5.162s since_last_challenge_visible=None challenge_samples=0 clean_samples=20` —— 即**本次等待期内从未观测到挑战（`challenge_samples=0`），因此新增的 15s 观测窗口未生效**，仅凭 5s 稳定窗判清。检测后采集继续并成功，未能区分"闪烁"与"iframe 尚未重新渲染"两种解释。

### 普查能力验证

- 新增单测 `backend/tests/unit/test_request_census.py`：7 passed（默认关闭、分类规则、不泄露查询串、跨请求 HMAC 一致性、失败请求、溢出上报、幂等关闭）。
- 回归：`backend/tests/unit` 220 passed；`backend/tests/contract` 33 passed；`backend/tests/integration` 81 passed / 1 skipped（1 项 `test_network_mode_is_persisted_and_immutable` 失败，为迁移 013 后测试期望未同步，非本轮改动引入）。`ruff check`、`ruff format --check`、`mypy backend/src`（strict，32 files）通过。
- 离线 Playwright 冒烟：真实事件下正确记录 1 条 200 响应与 1 条 `net::ERR_FAILED`，`url_key` 可区分参数，产物不含查询串。

### 首次误配提交的普查（L0 首份真实分层数据）

- 任务 `fc5fb419…` 30s 内失败（0 位达人）却产生 **542 条请求**：静态资源 313（57.7%）、平台 API 112（20.7%）、第三方 API 62（11.4%）、图片 28、未识别第三方 25、平台文档 **1**（仅 1 次导航）。
- 主机分布：`lf-star-static.bytetos.com` 339、`www.xingtu.cn` 113、`mcs.zijieapi.com` 19（埋点）、`mon.zijieapi.com` 16、`security.zijieapi.com` 10、封面 CDN 13。
- 状态：200×520、204×14、307×1、无终态 7；失败 6×`net::ERR_ABORTED`、1×`NO_TERMINAL_EVENT`；重复 `url_key` 21 个。
- **同一逻辑搜索产生 5 次 `POST /gw/api/gsearch/search_for_author_square`**，其中第一次 `net::ERR_ABORTED`；随后失败原因为 `SEARCH_RESPONSE_FAILED`。该次提交含非预期筛选，尚不能单独归因，已作为候选证据并标注不确定性。

### 授权真实采集（任务 `381d628b`，干净样本：零验证、零失败、零重扫、单次 Activity）

- 终态 `PARTIAL_COMPLETED`，`failure_reason=PROFILE_SCOPE_INCOMPLETE`，墙钟 124s、`active_seconds=119.76`。
- 计数：`discovered_count=20`、`valid_count=2`、`profile_complete_count=1`、`featured_complete_count=0`、`failed_count=2`；`allowed_actions=["retry"]`。
- **分层口径**：L0 全部网络请求 **2698**（静态资源 1743=64.6%、平台 API 542=20.1%、埋点监控安全 SDK 183=6.8%、未识别第三方 129、图片 72）；L1 已登记业务请求 **49（1.8%）**；L2′ 跨操作完全重复 **1966 条/551 组**（其中静态资源 1345 条）；L3 失败/无终态 63（47 无终态、10 `ERR_ABORTED`、6 `ERR_CONNECTION_CLOSED`）。
- **精选集合整段未采集（ISSUE-001，P0）**：2 位达人的 4 组精选全部 `NOT_ATTEMPTED`，快照 `failure_reason=IDENTITY_MISMATCH`，`featured_collections` **0 行**、`featured_cards` 0 行、`media_objects` **0**；而普查 `url_key` 显示精选重载加载的是同一位达人的同一批请求（达人 1 为 13/13、达人 2 为 14/14，两位达人之间零重合）。**根因已于 2026-10-15 用只读 DOM 探针确认（2/2 达人复现）**，见下。
- **主页重复整页加载（ISSUE-003）**：5 次平台主页文档请求（1 bootstrap + 每达人 profile/featured 各 1 次）；每次整页加载约 270 条网络请求。
- **Temporal 每 30 秒整段重跑（ISSUE-002，P0）**：同日用户运行 `50c8edf4` 的 Temporal history 显示两个 segment **各有 2 次 `collect_segment_v1` 执行、中间各一个 30 秒定时器**（run `01a13e24`：0.15→92.5s，TimerStarted 30s，122.5→263.0s；run `01a13f51` 同型）；对应 `failure_counts` 含 `LEASE_LOST`/`SESSION_INDETERMINATE`，`rescan_reasons=["CURSOR_INVALID"]`。
- **挑战放行过早（ISSUE-005）**：同日自然触发一次挑战，检测 14:00:04.967 → 放行 14:00:10.707（**5.740s**）；worker 日志 `observed_for=5.162s ... challenge_samples=0`，即 15s 观测窗口未生效。
- **口径失真（ISSUE-004）**：误配提交那次 30s 失败运行，计数器 `observed_requests=0` 而普查实录 **542** 条请求。
- **证据被误标网络模式（ISSUE-008）**：两份 failure 证据均写 `network_mode=production_line`，而单元为 `local_development`（`evidence.py:28` 默认值未被 `engine.py:107` 覆盖）。

### 冷启动重定向实机复现（排除"登录态失效/执行单元选错"）

- 用户报告打开的项目 profile Chrome 里星图不是登录状态。排查后结论：**执行单元没有选错，登录态也没有失效**。同一 profile 上重新执行 `xingtu session-diagnostics`（2026-10-15T13:59:10Z）→ `status=VALID`、`observed_account_id=ID: 1807978499337419`（与 expected 一致）、`protected_page_verified=true`、`login_page_verified=false`、`challenge_verified=false`、快照首个导航前恢复。
- 真因是 `adapter.py` 已记录的**冷启动重定向**，本轮实机逐字复现：尝试 1 `/ad/creator/index` → 302 到 `https://www.xingtu.cn/?redirect_uri=/ad/creator/index`；尝试 2 经登记 SSO 入口交接后再导航 `/ad/creator/market` → **受保护业务页就绪**。
- 处理方式：不换单元，改用采集适配器同款的**有界冷启动**（`scripts/diag/manual_request_census.py --bootstrap`，只用注册表登记的 URL 与选择器，不点击、不填表），窗口已落到已登录的达人广场。
- 旁证成本（并入 ISSUE-002/ISSUE-003）：一次冷启动落地需要 3 次文档导航，**首次导航必然浪费一整轮页面加载**。
- 队列元数据不一致补充（ISSUE-010）：DB 行 `account_ref=xingtu-account-02`/`line_ref=local-dev-macos`/`profile_ref=…予梦/01-定向爬取+定时更新/…` 与本机配置 `media-a`/`local-mac-02`/`…YUMENG/…` 全不同；该行由另一 checkout 写入，运行时使用配置文件的 profile 路径，故不影响本次判定；绑定不可变导致 `register-unit` 无法纠正。

### ISSUE-001 根因已确认（只读 DOM 探针，2/2 达人复现）

- 探针（`.runtime/diag01/identity_probe.py`、`identity_probe_b.py`，均位于 gitignored `.runtime/`，**未改动任何项目代码**）重放生产顺序（资料加载 → 已登记的粉丝/创作 tab 点击 → 重载同一 URL），并以约 15 ms 间隔密集采样从而捕获瞬态：
  - 达人 1：重载后 `+0ms` `div.author-info` 计数 0；**`+375ms` `div.author-info span.copy-text` 计数 1、文本为 `''`**；`+435ms` 文本恢复为 `7503176021160493065`。
  - 达人 2：`+315ms` 读到 `''`；`+360ms` 恢复为 `7282701602991898661`。
- **机制**：`read_locator` 仅以 `count()!=1` 与 `value is None` 判失败，**空串被当作一次成功读取**返回；`verify_identity` 随即比较 `'' != platform_creator_id` → 抛 `CREATOR_INVALID: IDENTITY_MISMATCH`。空窗约 45–60 ms；`check_session` 依赖账号定位符返回，而账号定位符与该空身份节点在 hydration 中几乎同时出现，故两位达人**稳定复现**（非偶发）。
- **次生后果**：`collect_featured_collections` 对非 `MODULE_COLLECTION_FAILED` 异常直接上抛 → 第二个精选集合也不再尝试、且**零 `FeaturedCollectionObservation` 落库** → `featured_collections` 0 行 / 封面 0 个 / `featured_status=NOT_ATTEMPTED`；`_collect_once` 保留 `valid=True` 并把状态置 `failed` → 出现"有效 2 + 失败 2"（ISSUE-006）。
- **为何资料阶段不失败**：资料阶段从业务页进入、应用外壳已预热，身份文本早于 `check_session` 返回即已填充，竞态被赢下；精选重载阶段被输掉。
- 证据：`.runtime/diag01/identity-probe.json`、`identity-probe-b.json`。**未确认项**：空窗精确宽度（受 CDP 往返影响，仅能给出"数十毫秒"量级）。
- **本轮未据此改动任何代码**；修复方向待用户确认。

### 人工 ↔ 自动化对照（已取得，同两位达人）

- 人工基线：用户在同一单元/profile/账号手工完成同一任务，访问的两位达人与自动化**完全一致**（`7503176021160493065`、`7282701602991898661`）。普查 `manual-20261015T140212Z.jsonl` 共 **2442** 条记录（0 丢弃），会话 14:02:14–14:07:02 UTC。
- 对照窗口对齐为"首次打开达人主页 → 会话结束"（人工 131s；自动化 109s）：

| 对照维度 | 人工 | 自动化 | 比值 |
|---|---|---|---|
| 总请求（L0） | 1519 | 2215 | **1.46×** |
| 每位达人均摊 | 760 | 1108 | 1.46× |
| 静态资源 | 822（54.1%） | 1430（64.6%） | **1.74×** |
| 平台域 / 平台 API | 412 / 370 | 459 / 447 | 1.11× / 1.21× |
| 图片 | 68 | 63 | 0.93× |
| 完全重复（多余条数） | 751 | 1548 | **2.06×** |
| 其中静态资源重复 | 397 | 1063 | **2.68×** |
| **达人主页整页加载** | **2（每位 1 次）** | **4（每位 2 次；精选正常完成将达 3 次）** | **2.00×** |
| 失败/无终态 | 70（4.6%） | 62（2.8%） | 0.89× |

- **结论**：自动化确实存在人工没有的多余请求，且多出来的是**页面加载开销**（静态资源与完全重复）而非业务请求；机制是**同一达人主页被重复整页加载**。自动化失败率反而更低，故"自动化因重试多请求"在本样本不成立。对照明细见 `.runtime/diag01/human-vs-auto-symmetric.txt`。

### 产物

- 报告：[DIAG-01 诊断报告](../evidence/DIAG-01-request-diagnosis-2026-10-15.md)（十部分）。
- 普查原始：`.runtime/diag01/census/auto-20261015T131920Z.jsonl`（session 1=误配提交 542 条；session 2=授权采集 2698 条）。
- 分析：`.runtime/diag01/{census-analysis,census-windows,final-metrics}.txt`、`run-evidence.json`、`wf-history-collect.json`、`prior-run-50c8edf4.json`、`revision-sha256.txt`。

## 修复实施与真实回归（2026-10-15，用户授权 A + C1）

**修复报告**：[DIAG-01 / F05 修复报告：身份读取竞态（A）与精选故障隔离（C1）](../evidence/DIAG-01-fix-issue001-2026-10-15.md)

- **改动面**：`backend/src/xingtu/adapter.py` 4 处（新增 `identity_read_cap_seconds=5.0` / `identity_poll_seconds=0.1`；`read_locator` 新增可选 `require_non_empty`，默认行为不变；`verify_identity` 改为有界确认；新增 `featured_spec_local_reason` 并以其替换原有的 ad-hoc 判断）+ 新增 `backend/tests/unit/test_identity_confirmation.py`（39 例）。**未修改** Schema、API 契约、Temporal 调度、ExecutionUnit、登录与会话策略、P1/P2 无关模块。
- **A 的实现要点**：`read_locator` 默认仍接受空串（其他调用方零变化）；仅身份读取启用非空校验。`verify_identity` 读取到 **== 期望值即立即通过**（正常路径只读 1 次、零额外延迟）；**空白**继续轮询；**非空但不符合预期**需**再读一次确认**，两次相同才判 `IDENTITY_MISMATCH`；整个读取+确认过程由 `asyncio.wait_for` **硬上限 5s**，超时按既有 `PLATFORM_PAGE_CHANGED: IDENTITY_UNREADABLE` 收口（交由既有达人级 ≤3 次有界重试）。任务取消照常传播，未动心跳/租约。
- **C1 的实现要点**：显式白名单，仅 `MODULE_COLLECTION_FAILED` 与 `PLATFORM_PAGE_CHANGED: PAGE_READY_TIMEOUT`（全场唯一生产者 `wait_ready`，只针对调用方自己的 `ready` 选择器）计为本精选局部失败并继续下一个；会话/挑战/租约/身份及一切未列入的 `PLATFORM_PAGE_CHANGED` **仍然中止**。按用户指示**未扩展** `RESPONSE_CONTENT_TYPE`/`RESPONSE_SCHEMA_MISMATCH`/`RESPONSE_TOO_LARGE`。
- **自动化检查**：新增 39 例全通过；单元 **259 passed**（修复前 220，无回归）；契约 **33 passed**；集成 **81 passed / 1 skipped / 1 failed**（唯一失败为**既有** `test_network_mode_is_persisted_and_immutable`：断言迁移版本恰为 `[1..12]` 而用户已应用迁移 013，与本轮无关，未修）；`mypy backend/src` strict 通过；我改动的文件 `ruff check`/`format --check` 通过（全仓 lint 的 11 项失败全部位于用户未跟踪的 `scripts/acceptance/run_cd05/06/07_acceptance.py`，既有且未触碰）。
- **真实回归**：任务 `bc393088-82e4-4822-b8b7-9970c06f2c97`（产品前端一次提交，`keyword=汽车`、`target_count=2`、无附加筛选、发送前硬校验），达人 `7503176021160493065` 与 `7282701602991898661`（与修复前、与人工基线**同一对达人**）。collection worker 与 API **均已重启加载修复后代码**。
- **回归结果**：`featured_status` `NOT_ATTEMPTED` → **`COMPLETED`**；`featured_complete_count` 0 → **2**；`featured_collections` 0 → **4 行**；`featured_cards` 0 → **11（全 `STORED`）**；`media_objects` 0 → **11（11 个不同 checksum）**；`failure_counts={}`、`challenge_count=0`、`duplicate_request_count=0`、`rescan_reasons=[]`；Temporal history **1 次 Activity、0 个定时器**（无新增重试）；请求/响应 **83/83**（修复前 48/49）；两达人**各 8 个模块全部 `COLLECTED`**（basic 20、spread 18、fans 9、conversion 10、fulfillment 9、seeding 7、creation 6、commercial 2 字段）。任务终态 `PARTIAL_COMPLETED`、`failure_reason=PROFILE_SCOPE_INCOMPLETE`（既有可选字段缺口，与精选无关）。
- **代价（如实记录）**：墙钟 124 s → 197 s、L0 请求 2698 → 3924，全部来自"精选终于真正执行"——达人主页整页加载由 4 次（修复前精选早退）恢复为设计值 **6 次（每达人 3 次）**；未出现新的请求类型或主机。
- **数据去重与历史观测核查**：一次逻辑采集产生 **4 行 = 2 达人 × 2 类型，每 (达人,类型) 恰好 1 行**；全库 `featured_collections` **115 行 / 115 个不同 `collection_observation_id`**（无重复行）；每达人 `snapshot_collections` **恰好 2 行**链到最新观测、`creator_snapshots` **恰好 1 行**；append-only 与迁移 003 设计一致；失败重读**只追加历史、不覆盖已提交成功观测**（`engine.collect_featured` 路径已核对）。**未改动任何 Schema 或迁移。**
- **ISSUE-006**：按用户判断**不改状态机**；本轮候选状态为 `done=2`、`failed=0`，修复前"有效 2 + 失败 2"的矛盾不再出现；"失败步骤归因不清晰"作为 P2 产品体验建议记录，本轮未改前端。

## 合并前核查（2026-10-15，用户要求，未提交未改无关代码）

**核查报告**：[DIAG-01 合并前核查与产品负责人决策报告](../evidence/DIAG-01-pre-merge-review-2026-10-15.md)

- **分支/HEAD**：`llb_1013` / `ee11254`；工作区 116 项（77 未跟踪 + 39 已修改），其中约 114 项在本轮之前已存在（用户未提交成果）。
- **独立性**：按 hunk 分离，`adapter.py` 共 27 hunk（+497/−13）中**我方 8 个（+84/−8）**、用户既有 **19 个（+413/−5）**；`runtime.py` 共 8 hunk 中我方 3 个（普查钩子约 11 行）。**同一文件内混有用户未提交改动**，因此"只提交本轮修复"必须**部分暂存**（`git add -p` / `git apply --cached`）；新文件可独立添加。`migrations/010–013` 均未跟踪，本轮修复**不依赖任何新迁移**。
- **敏感信息**：未发现口令/令牌/Cookie 明文/私钥/API Key；`test_request_census.py` 中的 `SECRET` 是"断言不被记录"的隐私用例。
- **集成 1 项失败核查**：`test_network_mode_is_persisted_and_immutable:164` 断言 `schema_migrations == [1..12]`，实际 `[1..13]`（用户 FILTER-01 的 `013_requirement_form_v2.sql`，仅放宽一个 CHECK、无数据改写、追加式）。该测试导入 `synthetic.SyntheticAdapter`、**从不 import 生产 adapter**，且修复前即失败 → **确为期望值过时，与 A+C1 无关**。最小修复建议：期望列表补 `13` 并补注释（**未授权，未修改**）。全仓 lint/format 的 11+3 处问题全部位于用户未跟踪的 `scripts/acceptance/run_cd0{5,6,7}_acceptance.py`，仅记录。
- **PARTIAL_COMPLETED 原因（新发现，重要更正）**：达人 2 `8ace9ea4` 有 **19 个必需字段 `FAILED`**（17 个 `MODULE_TIMEOUT` + 3 个 `MISSING_SOURCE`），覆盖 `seeding` 6 / `conversion` 9~10 / `fulfillment` 3~4——**不是"平台未提供"**（那会是 `NO_DATA`）。原因：模块 `status=COLLECTED` 但 `complete=False`（必需字段未全 `COLLECTED`），完整性判定用**字段级**结果。**先前"8 个模块全部 COLLECTED"的表述应更正为"模块状态全部 COLLECTED，但达人 2 的 3 个模块未 complete"**。**与修复无关的证据**：该达人逐模块字段级结果在修复前后**完全一致**（seeding FAILED 6、conversion FAILED 9、fulfillment FAILED 4）。是否符合契约：**符合**，`PROFILE_SCOPE_INCOMPLETE` 属既有优先级规则，未伪报完成。**建议单独立项 P1 诊断**，并让前端可一眼看到失败字段（本轮未改前端、未改状态逻辑）。
- **额外成本归因（口径必须分层）**：修复后 **L0 3924**、平台 API 826、**业务请求 83**；增量 L0 +1226 中**仅 +34 是我们的业务请求（2.8%）**，**+674（55%）是同主页重复整页加载导致的静态资源重复下载**，**0 来自重试**（`failure_counts={}`、0 定时器、1 次 Activity），其余为平台因页面加载自行发起的调用与平台侧波动，无法精确归因。耗时 +73 s 部分来自 2 次额外整页加载与多执行 2 组 5 s settle 与精选动作。

## A3 达人必需字段缺失专项诊断（2026-10-15，**未改代码、未做真实复测**）

**诊断报告**：[DIAG-01-A3 达人必需字段缺失专项诊断报告](../evidence/DIAG-01-missing-required-fields-2026-10-15.md)

- **稳定性已由历史证据判定，故本轮按用户既定条件「停止复测、不额外访问平台」**：达人 2 `7282701602991898661` 在 **5 次独立采集**（2026-10-13 至 10-15，跨 4 个任务、2 天）中逐字段结果**完全一致**（每次 seeding 失败 6 / conversion 失败 9 / fulfillment 失败 4）；达人 1 `7503176021160493065` 在 **9 次快照**中这些字段 `FAILED` **0 次**（1 次为上游中断的 `NOT_ATTEMPTED`）。→ **非偶发、达人特有、与 A+C1 无关**（该模式早于修复 2 天）。
- **数字口径核准并更正一处**：达人 2 共 81 字段 = COLLECTED 59 + **FAILED 19** + NO_DATA 3；**19 条 `FIELD_INCOMPLETE` 缺口与 19 个 FAILED 字段 1:1，无重复统计**；19 = **`MODULE_TIMEOUT` 16** + `MISSING_SOURCE` 3（**更正合并前核查报告中的 17 个 MODULE_TIMEOUT，实为 16**）；3 个 `NO_DATA` 为独立计数、属合法缺失、不入缺口。
- **根因（请求级证据）**：
  - 16 个 `MODULE_TIMEOUT`：来源请求在**模块窗口内根本没发出**。普查实证达人 2 资料窗口（14:38:17–14:39:31，超时 60s）内 `seed_base`（→seeding 6 字段）与 `conversion`（→conversion 9 字段）**均未出现**，而达人 1 在加载后约 1s 内 6 个请求全部 200。**关键**：这两个请求在达人 2 的**精选阶段**（点击「达人概览」「商业能力」后 14:39:34）**确实 200**，证明这些请求是**标签页交互触发**而非页面加载预取，而三模块声明 `capture_on_profile_load=true` + `actions=null`，因此在模块阶段望不到；等到精选阶段出现时，采集器只登记 `cards`/`cover_signs`，**这些响应被直接丢弃**。另有 1 个字段（`cooperation_industry_distribution` ← `order_experience`）**任何阶段都未发出**。
  - 3 个 `MISSING_SOURCE`：`contract_base` **确实 200 且被接受**（同响应 5 个字段 COLLECTED），但响应缺少 3 个已登记路径（`max_process_order_cnt`、`industry_order_distribution`、`industry_vv_distribution`）。**平台不下发 vs 键名漂移仍待定**——`raw_evidence` 对两次运行均 **0 行**，字段级来源缺失**不产生请求级证据**（可观测性缺口）。
- **机制缺陷（新发现）**：`personal_search_after_view`、`personal_search_after_view_rate`、`search_word_ctr` 已声明 `missing_source_status=NO_DATA`，但因**请求超时**走另一分支被记为 `MODULE_TIMEOUT`(FAILED) → **合法缺失声明被超时路径绕过**。
- **`NO_DATA` 语义正确**：3 项（basic 省份/MCN/行业标签）属合法缺失，**未误计入失败、不产生缺口、不影响完整性**。
- **产品优先级（按媒介决策价值，非按契约 required）**：P0 = GPM 区间、销售额区间、A3 增量、最大承接订单数（+ 恢复 A1 的 15 字段本身）；P1 = 商品价格/推荐商品/组件点击/CPC、看后搜、行业分布、合作行业分布；P2 = 相关视频数/播放中位数、个人页看后搜、搜索词点击率、省份/MCN/行业标签（合法缺失）。→ **19 项全部为契约必需字段，但业务优先级并不相等**。
- **优化方案（5 组，均待授权）**：①可观测性（字段级 MISSING_SOURCE 也落脱敏结构证据，P0 工程）；②为三模块登记**已核验的标签页动作**以主动触发请求（P0 业务，可望恢复 15 字段）；③超时路径对齐合法缺失声明（P1，极小）；④`contract_base` 3 个路径（P1，需先取证据）；⑤`order_experience`（P2，与②同批验证）。
- **唯一开放动作（待授权）**：一次**定向只读**响应结构捕获（仅记录 6 个端点是否发出 + `contract_base` 响应顶层键名，不含值/正文/query/Cookie），用于判定 A2 属合法缺失还是 Schema 漂移。**未授权则不访问平台**，建议先实施方案①后再自然取得该证据。

## A3 修复实施与真实回归（2026-10-15，用户授权 A 级 + B 级自主修复）

**修复报告**：[DIAG-01 / A3 修复报告：达人必需字段缺失（触发式最小修复）](../evidence/DIAG-01-A3-fix-issue-fields-2026-10-15.md)

- **根因（请求级证据）**：`profile()` 为所有「页面加载即采集」模块只打开一个登记窗口，但**仅执行 `modules[0]` 的 `actions`**，而 `modules[0]=basic` 的 `actions` 为空 → **整个初始窗口不执行任何交互**。`seeding`/`conversion` 声明 `capture_on_profile_load=true` 且无 `actions`，即假定平台会在加载时自行发出请求——该假定对达人 1 成立、**对达人 2 不成立**（定向只读探针：达人 2 裸加载 20s 内 `seed_base`/`conversion` 不出现，点击「达人概览+商业能力」后均 200；达人 1 裸加载即全部出现）。`read()` 本身已有有界 settle 等待，故**延长 timeout 无效**，问题是触发时机。
- **修复（加法式，4 处）**：①[`adapter.py`](../../backend/src/xingtu/adapter.py) 新增 `_wake_unresolved_modules`——在同一已登记窗口内，**仅对该模块仍有 `required` 响应未到达时**执行其自身登记的 `actions`；②[`contracts.py`](../../backend/src/xingtu/contracts.py) 守卫由 `(entry or actions)` 收窄为 `entry`（仍禁止离开主页），错误码 `PROFILE_LOAD_MODULE_HAS_ENTRY`；③注册表为 `seeding`/`conversion` 登记**已核验**交互（点击「达人概览」→「商业能力」，选择器全部取自 featured 既有已核验集合，**未新增任何选择器**）；④新增 12 个离线用例。**未改 Schema/迁移/API/调度/执行单元/会话策略/身份校验。**
- **门控的实际效果（实测）**：达人 1（会预取）的资料窗口请求集合与修复前**逐项相同** → **零额外点击、零额外请求**；达人 2 窗口仅多出 `seed_base 1` + `conversion 1`。
- **自动化检查**：新增 12 例通过；单元 **271 passed**（修复前 259）；契约 **33 passed**；集成 **81 passed / 1 skipped / 1 failed**（唯一失败为**既有**的迁移版本断言，与本修复无关，未改）；`mypy backend/src` strict 通过；`ruff check`/`format --check` 通过。
- **真实回归**：任务 `28371a91-ccea-483e-931f-c58a173e8505`（同参数 `汽车`/`target_count=2`/无筛选，**同一对达人**）。达人 2 **`FAILED` 19 → 10**（`MODULE_TIMEOUT` 16 → 1、`MISSING_SOURCE` 3 → 9）、`COLLECTED` 59 → **67**、完整率 **72.8% → 82.7%**；达人 1 **零字段变化**。任务 `gaps` 19 → **10**，仍 `PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE`（未伪报完成）。L0 3924 → 3970（+1.2%）、**达人主页加载 6 → 6 不变**、`duplicate_request_count=0`、`challenge_count=0`、`failure_counts={}`、Temporal **1 Activity / 0 定时器**、精选 4 行/11 卡/11 封面不变。
- **诚实说明**：8 个转为 `COLLECTED` 的字段中**只有 2 个带真实数据**（个人页看后搜人数 `10 - 100`、比例 `<0.02%`），另 6 个是平台字面占位符 `-`（`raw_value='-'`，同达人 `local_sales_overview` 全为 `0`）→ 最大收益是**不再把"平台无数据"误报为"采集失败"**，而非凭空多出 6 个可用指标。
- **探针瑕疵（如实记录）**：探针 `KEY_BEARING` 中 `seed_base` 路径误写为 `data_sp`（实为 `aggregator`），未采到其键名；该字节点的真实下发情况由回归结果确定。

## 未完成与风险

- **ISSUE-001 与 A3 均已修复并通过真实回归**，等待用户审阅与合并决定（本轮**未 commit / push / merge**）。
- **A3 的 5 项 C 级事项待授权（已停止，未自行实施）**：① 6 个 `-` 占位字段是否用既有 `FieldSpec.empty_values` 声明为 `NO_DATA`（改变 `COLLECTED/NO_DATA` 语义）；② 3 个履约 `MISSING_SOURCE`（平台对该达人只返回 7/10 个键）是否声明 `missing_source_status=NO_DATA`；③ `order_experience` 已停止（裸加载与 5 个标签逐一尝试后平台均未请求该端点，进一步验证需扩大访问范围）；④ `contract_version` **未升版**（本次未改请求/路径/字段/单位/Schema，升版会重置能力健康计数），如流程要求升版请指示；⑤ 集成既有失败测试是否授权补 `13`。
- **既有、与本轮无关但需用户决定的两项检查异常**：① 集成 `test_network_mode_is_persisted_and_immutable` 仍失败（断言迁移版本恰为 `[1..12]`，而用户已应用迁移 013 → 期望过时）；② 全仓 lint/format 的 11+3 处问题全部位于用户未跟踪的 `scripts/acceptance/run_cd05/06/07_acceptance.py`。两者均**未修**（不属本轮授权范围）。
- **仍未解决的诊断问题（未授权，未改）**：ISSUE-002（30 秒整段重跑，P0）、ISSUE-003（重复整页加载，P1）、ISSUE-004（请求口径，P1）、ISSUE-005（挑战放行，P1）、ISSUE-007（单次响应异常放大，P1）、ISSUE-008/009/010/011（P2）。
- **ISSUE-003 的成本因修复而如实显现**：达人主页整页加载 4 → 6 次、L0 请求 2698 → 3924、耗时 124 → 197 s；属"恢复功能应有的成本"，建议作为紧接的 P1 优化项。
- **首次误配提交已如实记录**（历史）：带 `target_count=20` 与非预期筛选的任务 30 s 内以 `SEARCH_RESPONSE_FAILED` 失败且采集 0 位达人，未造成范围扩张。
- 第二 checkout 与共享数据库的环境不一致（`execution_units` 行三项绑定字段均指向另一 checkout）已记录为风险，本轮不改绑定。
- 新增文件保留在工作区（未提交）：`request_census.py`、`runtime.py` 默认关闭挂载点、`scripts/diag/manual_request_census.py`、`tests/unit/test_request_census.py`、`tests/unit/test_identity_confirmation.py`。

## 状态历史

- 2026-10-16T00:05:00+08:00：待验收（保持）；用户授予 A 级+B 级自主修复。已实现触发式最小修复（`adapter.py` 新增 `_wake_unresolved_modules` 门控、`contracts.py` 守卫收窄、注册表为 `seeding`/`conversion` 登记已核验交互、新增 12 例测试），自动化检查通过（单元 271 / 契约 33 / 集成 81+1skip+1 既有失败 / mypy strict / ruff 通过），并在**同一对达人**上完成受控真实回归：达人 2 `FAILED` 19 → 10、`COLLECTED` 59 → 67、完整率 72.8% → 82.7%，达人 1 **零字段变化**，请求 +1.2%、页面加载次数不变、无重复/无重试/无挑战。**未改 Schema/API/调度/执行单元/会话策略**，未 commit/push/merge。5 项 C 级语义事项已停止并报告。
- 2026-10-15T23:30:00+08:00：待验收（保持）；用户将 A3 升级为『先复核历史证据 + 必要时受控复测』的专项诊断。经复核：达人 2 的字段缺失在 **5 次独立采集（跨 2 天）中 100% 一致**、达人 1 的 9 次快照中同名字段 FAILED 为 0 → **稳定性已判定，按用户既定条件停止复测、未新增任何平台访问**；核准数字口径（**更正为 16 个 MODULE_TIMEOUT + 3 个 MISSING_SOURCE = 19，另有 3 个独立 NO_DATA，缺口与 FAILED 1:1 无重复统计**）、定位两类根因（请求未在窗口内发出／响应缺 3 个登记路径）、发现『合法缺失声明被超时路径绕过』的机制缺陷，输出字段级诊断报告与 5 组优化方案。**未改代码、未改 Schema、未做真实采集、未提交**。唯一开放动作＝待授权的定向只读响应结构捕获。
- 2026-10-15T23:05:00+08:00：待验收（保持）；用户要求合并前最小范围核查。已完成独立性（hunk 级分离、敏感信息、可独立提交性）、集成失败归因（迁移 013 期望过时，与修复无关）、PARTIAL_COMPLETED 原因（达人 2 共 19 个必需字段 FAILED：17 MODULE_TIMEOUT + 3 MISSING_SOURCE，修复前后完全一致）、额外成本归因（L0 +1226 中业务请求仅 +34，55% 为重复整页加载的静态资源，0 来自重试）与 ISSUE-002/003 优先级说明，并输出产品负责人决策报告。**未提交、未合并、未改无关代码**。
- 2026-10-15T22:45:03+08:00：待验收（保持）；用户授权 A + C1 修复。已实施（`adapter.py` 4 处 + 新增 39 例测试），自动化检查通过（单元 259 / 契约 33 / 集成 81 + 1 skipped + 1 项既有失败；`mypy` strict 通过），并在**同一对达人**上完成受控真实回归：`featured_status` NOT_ATTEMPTED → COMPLETED、精选行 0 → 4、卡片 0 → 11、封面 0 → 11，零失败/零挑战/零重试、8 模块无退化。数据去重与历史观测核查通过（115 行 / 115 个不同观测 id、每达人每类型恰 1 行、链接正确、失败不覆盖成功）。**未 commit/push/merge**，等待用户决定。
- 2026-10-15T22:16:00+08:00：待验收（保持）；用户要求先确认 ISSUE-001 根因、明确前不得改代码。已用只读 DOM 探针 2/2 达人复现并确认根因（精选重载后 `div.author-info span.copy-text` 有约 45–60 ms 空文本窗口，而 `read_locator` 接受空串 → `'' != creator_id` → `CREATOR_INVALID: IDENTITY_MISMATCH`），报告与卡片已回写。**未改动任何项目代码**（`git status` 仍 114 项，探针均位于 gitignored `.runtime/`）；环境已复原（collection worker 运行中、单元 `owner=NULL`）。
- 2026-10-15T22:08:00+08:00：进行中 → 待验收；人工基线对照已取得并写入报告（同两位达人，自动化 1.46× 总请求、2× 主页加载、2.06× 完全重复，业务 API 仅 1.21×）。DIAG-01 全部执行项完成，等待用户审阅报告并决定 D01–D06 与是否进入修复阶段。
- 2026-10-15T21:45:00+08:00：进行中 → 待验收；诊断报告（十部分）、问题清单（11 项）与产品优化方案已产出；真实采集与八大维度分析完成；仅剩人工基线对照（DIAG-01G）未取得数据。
- 2026-10-15T21:27:00+08:00：待办 → 进行中；用户批准诊断方案并授权真实采集、普查埋点、人工基线与环境前置操作。已完成只读前置核对、历史线索复核、普查能力落地与首次提交（含一次误配提交的如实记录与纠正）。
