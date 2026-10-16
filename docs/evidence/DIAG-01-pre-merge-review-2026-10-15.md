# DIAG-01 合并前核查与产品负责人决策报告

- 日期：2026-10-15（Asia/Shanghai）
- 分支 / HEAD：`llb_1013` / `ee1125412a181e4df13fbe32ea0242a18ab02622`（远端存在 `origin/main`、`origin/10.9`；本地另有 `main`）
- 本轮**未执行 Commit / Push / Merge**，未修改无关代码
- 关联证据：[诊断报告](DIAG-01-request-diagnosis-2026-10-15.md)、[修复报告](DIAG-01-fix-issue001-2026-10-15.md)、[DIAG-01 卡片](../tasks/DIAG-01.md)

---

## 一、修复的独立性核查

### 1.1 分支与工作区

- 分支 `llb_1013`，HEAD `ee11254`（`Merge pull request #1 from liulongbo/10.9`）。
- 工作区：**116 项**（77 未跟踪 + 39 已修改），其中约 114 项在本轮修复之前就已存在，属用户未提交成果。

### 1.2 属于本 DIAG-01 工作的文件

| 文件 | 状态 | 说明 |
|---|---|---|
| `backend/src/xingtu/adapter.py` | 已修改 | **本轮 A + C1 修复**（8 个 hunk，+84/−8） |
| `backend/tests/unit/test_identity_confirmation.py` | 新增 | 本轮 39 例回归测试 |
| `backend/src/xingtu/runtime.py` | 已修改 | 上一阶段：默认关闭的普查挂载点（3 个 hunk，我方为约 11 行） |
| `backend/src/xingtu/request_census.py` | 新增 | 上一阶段：普查实现 |
| `backend/tests/unit/test_request_census.py` | 新增 | 上一阶段：普查 7 例 |
| `scripts/diag/manual_request_census.py` | 新增 | 上一阶段：人工基线只读脚本 |
| `docs/evidence/DIAG-01-request-diagnosis-2026-10-15.md` | 新增 | 诊断报告 |
| `docs/evidence/DIAG-01-fix-issue001-2026-10-15.md` | 新增 | 修复报告 |
| `docs/tasks/DIAG-01.md` | 新增 | 任务卡 |
| `docs/tasks/README.md`、`docs/项目任务进度总览.md` | 已修改 | 追加 DIAG-01 条目 |

### 1.3 是否混入其他任务的未提交修改 —— **是，且混在同一文件内**

按 hunk 级分离（`git diff -U0` 解析）：

| 文件 | 总 hunk | 我方 hunk | 用户既有 hunk |
|---|---|---|---|
| `adapter.py` | 27（+497/−13） | **8（+84/−8）** | **19（+413/−5）** |
| `runtime.py` | 8（+50/−1） | **3（约 +11 为我方普查行）** | **5（+22/−1）** |

`docs/tasks/README.md` 与 `docs/项目任务进度总览.md` 在本轮之前就已是 `M`（用户未提交改动），我的追加与其混在同一文件。

### 1.4 敏感信息

- 对 `adapter.py`（含我方 diff）、`request_census.py`、两个测试文件、人工基线脚本做凭据扫描：**未发现口令、令牌、Cookie 明文、私钥或 API Key**。
- 唯一命中 `SECRET` 字样的位置是 `test_request_census.py`——它用字面量 `token=SECRET` 作为**待丢弃的查询串**，断言普查产物中**不含**该值，属隐私验证用例。
- 普查模块只记录 method/资源类型/host/path/状态/耗时与 URL 的 HMAC，**不记录**查询串、Header、Cookie 与消息体（模块文档与单测均覆盖）。

### 1.5 能否安全、独立地提交本轮修复

- **新文件**（测试 + 3 份证据/卡片）彼此独立，可安全单独 `git add`。
- **`adapter.py` 不能单独"只提交本轮修复"**：同一文件里还有用户 19 个 hunk 的未提交改动；直接 `git add adapter.py` 会把用户未完成的工作一并提交。`runtime.py` 同理。
- 若要一个**只含 A + C1 的最小提交**，需使用部分暂存（`git add -p` / `git apply --cached`）挑出这 8 个 hunk + 新测试文件；否则应**整文件提交并明确说明同时包含用户既有未提交改动**。
- 另需注意：`migrations/010–013`（含 013）**均为未跟踪文件**；本轮修复**不依赖任何新迁移**。

**结论：技术上可独立提交，但需要部分暂存；否则会连带提交用户的未完成工作。**

---

## 二、未通过的集成测试核查

### 2.1 迁移 013 的来源与合法性

- 文件：`migrations/013_requirement_form_v2.sql`，由用户在 **2026-10-15 08:55** 创建（当前**未跟踪**，与 010/011/012 相同状态）。
- 来源可溯：FILTER-01 卡片记载"M3 PostgreSQL 集成测试发现原 `requirements_schema_version_check` 只允许 `requirement_form.v1`；…已增加 `013_requirement_form_v2.sql`，仅将约束放宽为 v1/v2，不新增列、不改写历史 payload"。
- 内容仅为：`DROP CONSTRAINT` + 重建为 `CHECK (schema_version IN ('requirement_form.v1','requirement_form.v2'))` + `INSERT INTO schema_migrations(version) VALUES(13)`。**追加式、无破坏性 down、无数据改写**，与 001–012 的迁移纪律一致。
- 实测已应用：`schema_migrations = [1..13]`。

### 2.2 失败确实来自旧测试断言

- 断言（`backend/tests/integration/test_repository.py:164`）：
  `assert [row["version"] for row in versions] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]`
- 实际：`[1..13]` → **唯一差异是多了 13**。测试自身的注释也说明其意图是"把集合写死，以便捕获某个迁移悄悄不再被应用"——是**期望值未随新迁移更新**，而非迁移或代码错误。

### 2.3 与 A + C1 修复无关

- 该测试文件导入的是 `backend.tests.synthetic.SyntheticAdapter`，**从不 import 生产 `xingtu.adapter`**；断言本身只读取 `schema_migrations`。
- 逻辑上也无关：本轮只改身份读取与精选失败分类，不触碰迁移与网络模式持久化。
- 该失败在本次修复之前即已存在（我在修复前的集成运行中同样观测到同一条失败）。

### 2.4 最小修复建议（**未授权，未修改**）

- **方案 A（最小，1 行）**：把期望列表补为 `[..., 13]`，并在上方注释补一句 013 的作用（放宽 `requirements.schema_version` 到 v1/v2）。
- **方案 B（可选，更耐久）**：改为与磁盘上的 `migrations/*.sql` 版本集合比较，使以后新增迁移无需再改测试期望；改动略大，建议单独排期。

推荐 **A**：改动面最小、意图最清晰，且不改变该测试"穷尽校验"的初衷。

### 2.5 全仓 lint / format

- `ruff check` 11 项、`ruff format --check` 3 个文件，**全部位于用户未跟踪的 `scripts/acceptance/run_cd05_acceptance.py`、`run_cd06_acceptance.py`、`run_cd07_acceptance.py`**（UP031 百分号格式化 + 行宽）。
- **本轮未触碰**；仅记录。建议由这些脚本的作者在各自卡内处理。

---

## 三、PARTIAL_COMPLETED 原因确认（**仅分析，未改状态逻辑**）

### 3.1 具体缺少哪些字段

- **达人 1 `700ca5b0`：`profile_complete=True`**。仅 2 个 `NO_DATA`（`basic.mcn_name`、`basic.industry_labels_raw`）——`NO_DATA` 是"已完成的检查、平台确无数据"，**不阻断完整**。
- **达人 2 `8ace9ea4`：`profile_complete=False`**，19 个必需字段**`FAILED`**：
  - `seeding` 6 个（`a3_increment`、`search_after_view`、`search_after_view_rate`、`personal_search_after_view`、`personal_search_after_view_rate`、`search_word_ctr`）
  - `conversion` 10 个（`gpm_range`、`sales_amount_range`、`component_click_count_range`、`component_click_rate_range`、`related_cpc_range`、`recommended_product_count`、`product_price_range`、`related_video_count`、`related_video_play_median`）
  - `fulfillment` 3 个（`max_processing_order_count`、`industry_order_distribution`、`industry_play_distribution`、`cooperation_industry_distribution` —— 合计 4 项，其中 3 项为 `MISSING_SOURCE`）
  - 另有 3 个 `NO_DATA`：`basic.province`、`basic.mcn_name`、`basic.industry_labels_raw`
- 因此 `profile_complete_count=1`，任务以 `PROFILE_SCOPE_INCOMPLETE` 收口。

### 3.2 缺失原因 —— **不是"平台未提供"，而是我们没拿到**

- **17 个 `MODULE_TIMEOUT`**：该模块已登记请求在 settle 窗口内**没有产生可关联响应**（`ResponseCollector.read()` 对未 settled 的必需请求记 `MODULE_TIMEOUT`）。
- **3 个 `MISSING_SOURCE`**：响应到了，但契约声明的取数路径在响应中缺失。
- 这与 `NO_DATA`/`NOT_PROVIDED`（平台明确无此数据）**语义完全不同**——若为后者，字段会是 `NO_DATA` 而**不会**产生 `FIELD_INCOMPLETE` 缺口。

### 3.3 是否属于 MCN 媒介核心业务字段

- 19 个字段**全部在必需清单内**（`profile_requirement.version = full-homepage-inventory-v4-six-fields-live-verified`，`inventory_verified=true`）。
- 业务含义：`conversion.*` 是转化能力（GPM、销售额区间、组件点击、CPC、带货商品数）——**报价与投放评估直接依赖**；`fulfillment.*` 是履约与合作行业分布——**交付能力判断依赖**；`seeding.*` 是种草效果（看后搜、搜索词点击率）——**种草类商单评估依赖**。**属核心业务字段，不是可忽略的可选项。**
- 但影响是**达人特定**的：同一批次达人 1 这些字段全部 `COLLECTED`，说明契约与选择器本身可用。

### 3.4 为什么模块全部 COLLECTED 却仍为部分完成

- 这里需要区分两个不同层级：
  - 模块 **`status = COLLECTED`**：该模块操作已走到一个**已登记结论**（已尝试、已收口）。
  - 模块 **`complete = False`**：其**必需字段未全部 `COLLECTED`**。
- 实测：达人 2 的 `seeding` / `conversion` / `fulfillment` 三个模块 `status=COLLECTED` 但 **`complete=False`**（分别 6/9/4 个字段 `FAILED`）。
- 完整性判定用的是**字段级**结果：`coverage.registered_complete=false`、`complete=false`，并显式列出 19 条 `FIELD_INCOMPLETE:*`。

> 更正说明：我在修复报告中"8 个模块全部 `COLLECTED`"的表述指的是**模块状态与字段总数**（如 conversion 有 10 个字段）；准确说法是"**模块状态全部 COLLECTED，但达人 2 的 3 个模块未 complete**，因为其中 19 个必需字段为 `FAILED`"。此处更正，避免误读为"字段全部采到"。

### 3.5 是否符合当前状态契约

**符合。** 按既有优先级 `SEARCH_CAPABILITY_LIMIT > PROFILE_SCOPE_INCOMPLETE > MODULE_COLLECTION_FAILED > …`，存在有效达人但资料未齐时，`PROFILE_SCOPE_INCOMPLETE` 正是应当给出的原因；系统**没有伪报完成**，并把缺口逐字段记录在快照中。

### 3.6 是否需要后续补采

- **建议补采**（如果媒介需要达人 2 的种草/转化/履约字段）。依据：这些模块 `complete=False`，既有 `retry` 会重新尝试未 complete 的模块（已 complete 的模块会被跳过），因此补采具备正确入口。
- **但需注意**：达人 2 的失败在**修复前与修复后完全一致**（见 §3.7），说明它不是本轮修复引入、也不会被本轮修复解决；补采是否必然成功**无法先行保证**，需实测；若稳定复现，应按新的独立问题（可能是该达人页面的模块懒加载/超时窗口）单独诊断，**不在本轮范围**。

### 3.7 与修复的关系（关键证据）

对同一对达人的**修复前**与**修复后**快照逐模块比对，字段级结果**完全一致**：

| 达人 2 `8ace9ea4` | 修复前 `381d628b` | 修复后 `bc393088` |
|---|---|---|
| `seeding` | `COLLECTED` / complete=False / FAILED 6 + COLLECTED 1 | **完全相同** |
| `conversion` | `COLLECTED` / complete=False / FAILED 9 + COLLECTED 1 | **完全相同** |
| `fulfillment` | `COLLECTED` / complete=False / COLLECTED 5 + FAILED 4 | **完全相同** |

→ **`PARTIAL_COMPLETED` 与 A + C1 修复无关，是既有的、达人特定的资料采集问题。**

---

## 四、修复后额外采集成本的来源

> **口径前提**：以下三个数字**不可混用**。L0 = 浏览器发出的每一请求；平台 API = `xingtu.cn` 的 xhr/fetch（**仍包含平台自身 SPA 发起的调用**）；业务请求（L1）= **命中已登记规格且参数关联成功**的请求，才是"我们自己的业务动作"。

| 口径 | 修复前 `381d628b` | 修复后 `bc393088` | 增量 |
|---|---|---|---|
| **L0 全部网络请求** | 2698 | **3924** | **+1226** |
| 平台域请求（`xingtu.cn`） | 555 | 847 | +292 |
| 平台 API（xhr/fetch） | 542 | 826 | +284 |
| 静态资源 | 1743（64.6%） | 2417（61.6%） | **+674** |
| 图片（含封面 CDN） | 72 | 130 | +58 |
| 埋点/监控/安全 SDK | 138 | 246 | +108 |
| **业务请求 L1（`observed_requests`）** | **49** | **83** | **+34** |
| L1 / L0 | 1.8% | **2.1%** | — |
| L1 / 平台 API | 9.0% | **10.0%** | — |
| 平台文档导航 | 5 | **7** | **+2** |
| 达人主页整页加载 | 4 | **6** | **+2** |
| 完全重复请求（同方法+同路径+同参数） | 1966 | 3134 | +1168 |
| 失败/无终态请求 | 63 | 39 | −24 |

### 4.1 按"每次整页加载"归因（实测逐窗口）

每次平台文档加载的成本高度一致：**约 500–600 条 L0**，其中静态资源约 350、平台 API 约 70–156、埋点约 17–43、图片约 9–25。

| 修复后加载序列 | 窗口内 L0 | 静态 | 平台API | 埋点 | 图片 |
|---|---|---|---|---|---|
| #1 `/ad/creator/market`（冷启动） | 507 | 313 | 99 | 31 | 20 |
| #2 达人1 资料 | 595 | 351 | 144 | 30 | 24 |
| #3 达人1 精选①重载 | 564 | 351 | 120 | 38 | 15 |
| #4 达人1 精选②重载 | 585 | 351 | 120 | 39 | 25 |
| #5 达人2 资料 | 570 | 351 | 127 | 37 | 15 |
| #6 达人2 精选①重载 | 546 | 350 | 108 | 34 | 14 |
| #7 达人2 精选②重载 | 557 | 350 | 108 | 37 | 17 |

### 4.2 三类归因结论

1. **成功采集精选所必需**：
   - 修复前每达人只走到"精选①"就因身份误判中止（每达人 2 次加载）；修复后每达人走满"资料 + 精选① + 精选②"共 **3 次加载**，这正是注册表 `reload_homepage=true` 为两个精选规格声明的设计路径。
   - 由此新增的**业务请求仅 +34 条**（49 → 83），即精选卡片与封面签名的登记请求——这是"精选真正被采集"的直接成本。
   - 封面相关请求 +58（图片）与 `media_objects` 0 → 11 一致，属**必需的取数**。
2. **页面重复加载造成的重复**：
   - 增量的**主体是静态资源 +674**（占 L0 增量 1226 的 **55%**），以及随之重复的平台 SPA 自身 API 调用。它们的成因是**对同一达人主页额外做了 2 次整页加载**；每次都重新下载同一批 SPA 资源。
   - 全量重复请求由 1966 → **3134**，与"多 2 次相同加载"完全一致。
   - **旁证（重要）**：人工基线在**同两位达人**上只做了 **2 次**主页整页加载（每位 1 次）就完成了"8 模块 + 2 组精选"的业务阅读。这说明**增量中的整页加载并非业务结果所必需**，而是当前自动化实现方式带来的冗余（即 ISSUE-003）。
3. **来自异常重试或其他冗余操作**：
   - **0**。修复后 `failure_counts={}`、`challenge_count=0`、`duplicate_request_count=0`、`rescan_reasons=[]`；Temporal history **1 次 Activity 执行、0 个定时器**；`SEARCH_RESPONSE_FAILED` 之类整段失败也未出现。**本次增量无一来自重试。**
4. **目前无法准确归因的部分**：
   - 每次加载之间的平台侧波动（修复前 483–606、修复后 507–595）——取决于平台当时下发多少资源与埋点批次。
   - 平台 API 增量（+284）中，"平台自身 SPA 在 hydration 时本就会发起的调用"与"我们登记请求"的精确切分：**只有 34 条可归给我们**（L1），其余约 250 条是**平台因页面加载而自行发起的调用**，无法进一步归因到某一具体动作。
   - 耗时增量 124 s → 197 s（+73 s）可部分解释为：2 次额外整页加载（各约 10–17 s 窗口）、精选每规格 `response_settle_seconds=5` 多执行 2 次（+10 s）、精选动作（2 次点击 + 3 次滚动，每次间隔 2 s）多执行 2 组；剩余部分为平台响应快慢导致的波动，**未逐秒精确归因**。

**一句话结论**：增量中**只有 34 条是"我们的业务请求"**（L1，占增量 2.8%）；**增量的 55% 是同一主页重复整页加载导致的静态资源重复下载**；**0% 来自重试**；其余为平台因页面加载自行产生的流量与平台侧波动。

---

## 五、ISSUE-002 与 ISSUE-003 的优先级说明（**仅解释，不授权修改**）

### 5.1 ISSUE-002：`WAITING_FOR_RESOURCE` 触发每 30 秒整段重跑

- **发生在哪个执行阶段**：P2 采集段的 **Temporal Activity 之间**。当 Activity 返回 `WAITING_FOR_RESOURCE`（由 `LEASE_LOST` / `SESSION_INDETERMINATE` / `RESOURCE_UNAVAILABLE` 映射）或 `RETRY_WAIT` 时。
- **触发条件**：上述任一错误码出现，且该状态**不在** `workflow.py` 的显式唤醒集合（只含 `WAITING_FOR_LOGIN` / `WAITING_FOR_ACCOUNT` / `WAITING_FOR_VERIFICATION` / `PAUSED_BUDGET`）内 → 落入 30 秒 `wait_condition` 超时分支 → 再次 `execute_activity`。
- **会重复执行哪些操作**：**整段 Activity**，包括：重新获取执行单元租约、**重新启动 Chrome**、`rebuild_conditions()` → `_bootstrap_session`（最多 4 次业务页导航 + SSO 交接）、重做筛选与**重新发起搜索**；并且由于契约 `resume_supported=false`，`prepare()` 对非空游标直接返回 False → `rescan()` **清空游标、从第 1 页重扫**。已完成模块会被跳过（`old.complete`），但**页面加载与搜索会重来**。
- **对效率与数据正确性的影响**：
  - 效率：Temporal 历史实测同型任务**每个 segment 有 2 次 Activity、中间 1 个 30 秒定时器**；单达人耗时从 **77 s 膨胀到 263 s**、业务请求约 **31 → 62**。
  - 数据正确性：**未发现数据错误**——已提交结果被保留、快照不可变、写入有三重栅栏；重复执行主要造成**重复的页面访问与请求**，不产生错误数据。
- **为什么判 P0**：它是**唯一被实测证明、且量级最大的"系统自身放大量"**（请求近翻倍、耗时近三倍），并且它**每次重跑都会重新整页访问平台**——这正是用户最初提问"为什么自动化比人工更容易遇到验证"的最强候选自因。它不破坏数据，但直接放大风控暴露与成本，因此按"影响核心采集稳定性与正确性"的标准列入 P0。

### 5.2 ISSUE-003：同一达人主页被重复整页加载

- **为什么每达人要加载 3 次**：注册表对 `excellent_reach` 与 `excellent_seeding` 两个精选规格都声明了 `reload_homepage=true`，因此流程是：①`profile()` 打开主页采集 8 个模块；②精选① 重载主页并采集；③精选② 再重载主页并采集。合计 1 + 2 = **3 次/达人**。
- **哪些是必要的**：①资料加载（8 模块必需）；②精选各自的**取数**是业务必需的，但"必须通过整页重载"这一点**不是**——它是当前实现选择。
- **哪些可能存在冗余**：**第 2、3 次整页加载**。人工基线在每人**仅 1 次**加载的情况下完成了相同的 8 模块 + 2 组精选阅读；而每次额外整页加载带来约 **500–600 条 L0**（其中静态资源约 350 条为重复下载）。
- **能否通过现有状态复用来减少**：**可行方向存在但需验证**。现有代码已有复用判定：`engine.collect_featured` 对 `previous.complete` 的规格 `continue`（跳过已完成），`engine.reusable()` 按 `set_key` + 指纹判定同集合复用；因此"精选②复用精选①已加载的页面"在**状态层**有基础。**但风险点明确**：登记请求的响应关联依赖"重载后的干净捕获窗口"，若在已加载页面上直接取数，可能命中上一次操作的残留响应——这与 ISSUE-007（响应交错）同源。因此**必须单独验证**，不能直接改。
- **优化可能影响哪些业务流程**：①精选两组的**请求-响应关联正确性**（最大风险）；②精选的 `set_key`/指纹复用语义与"已存在观测"的判定；③封面采集与卡片落库时序；④若改为"只重载一次"，会改变现有 `featured_load_count`/`navigation_count` 口径，进而影响既有验收指标的可比性。
- **为什么判 P1**：它**不导致数据错误或任务失败**（数据正确性已由本轮与历史回归验证），但直接决定了"自动化比人工多发多少流量"（本轮增量中 55% 来自此），属"明显影响效率与风控暴露"的等级；相较 ISSUE-002 的"整段重跑 + Chrome 重启"，它的触发是**常态**（每次都发生）但**每次代价更小**，故列 P1。

---

## 六、产品负责人决策报告

| # | 决策项 | 结论 |
|---|---|---|
| 1 | **A + C1 是否满足合并条件** | **满足技术合并条件**。改动面极小且隔离（`adapter.py` 8 个 hunk + 1 个新测试文件）、未触碰 Schema/API 契约/Temporal/执行单元/会话策略；自动化检查通过（新增 39 例、单元 259、契约 33、`mypy` strict）；真实回归在同参数、同一对达人上从 `NOT_ATTEMPTED` 恢复为 `COMPLETED`（精选 0→4、卡片 0→11、封面 0→11），零失败/零挑战/零重试，8 模块无退化。**唯一操作前提见第 2 项。** |
| 2 | **尚未通过的检查是否会阻碍合并** | **不会阻碍功能成立，但会阻碍"全绿"合并。** ① 集成 1 项失败 = `test_network_mode_is_persisted_and_immutable` 的**期望值过时**（`[1..12]` vs 已应用 `[1..13]`），与修复无关，建议 1 行修正后合并；② 全仓 lint/format 的 11 + 3 处问题全部位于**用户未跟踪的 `scripts/acceptance/run_cd0{5,6,7}_acceptance.py`**，与本轮无关。③ **提交方式**：`adapter.py` / `runtime.py` 内混有用户既有未提交改动，若要"只提交本轮修复"必须**部分暂存**；否则会连带提交用户未完成的工作。 |
| 3 | **PARTIAL_COMPLETED 是否属于需优先处理的业务问题** | **属于真实业务缺口，但不是本轮修复引入，也不阻塞本轮合并。** 达人 2 有 **19 个必需字段 `FAILED`**（17 `MODULE_TIMEOUT` + 3 `MISSING_SOURCE`），覆盖**转化能力、履约能力、种草效果**——都是报价与投放评估会用到的核心字段，而非"平台未提供"。证据显示 `NO_DATA` 与 `FAILED` 语义严格区分，系统未伪报完成。**建议：提高到 P1，单独立项诊断**（重点：为何该达人的 seeding/conversion/fulfillment 请求超时/取数路径缺失），并在产品上让"失败字段"可被媒介一眼看到。 |
| 4 | **本轮新增耗时与请求的实际来源** | 增量 **L0 +1226**、**耗时 +73 s**、**整页加载 +2**。归因：**+34 条（2.8%）是我们的业务请求**（精选真正被采集）；**+674 条静态资源（55%）与 2 次整页加载**来自"对同一主页重复整页加载"（ISSUE-003）；**+58 图片/+284 平台 API** 中主要是平台因页面加载自行发起的调用与封面取数；**0 来自重试**（无失败、无定时器、1 次 Activity）；其余为平台侧波动，**无法精确归因**。口径差异务必区分：**L0 3924 ≠ 平台 API 826 ≠ 业务请求 83**。 |
| 5 | **ISSUE-002/003 的优先级与推荐实施顺序** | **ISSUE-002 = P0**（每 30 秒整段重跑：重启 Chrome、重新 bootstrap、重新搜索、清游标重扫；实测耗时 ×3.4、业务请求 ×2；是最大自因）。**ISSUE-003 = P1**（每达人 3 次整页加载；人工用 1 次即可完成同样业务；增量流量 55% 出自此）。**推荐顺序**：先 ISSUE-002（消除"无上限放大"，收益最确定、改动集中在 workflow 的等待/退避语义），再 ISSUE-003（需先验证"复用已加载页面"不破坏请求关联），随后 ISSUE-004（补请求口径指标，使降幅可度量）。 |
| 6 | **下一步建议与需授权事项** | 见下方清单。 |

### 6.1 建议的下一步（按顺序）

1. **修正集成测试期望**（1 行 + 注释）：不授权则维护者自行处理，会持续显示 1 项失败。
2. **决定提交方式**：① 只提交本轮 A + C1（需部分暂存 8 个 adapter hunk + 新测试）；或 ② 连同用户既有未提交改动一起提交（需你确认）。
3. **单独立项 P1**：达人 2 的 19 个字段 `FAILED`（转化/履约/种草）——本轮**未**授权、**未**修改。
4. **P0 方案设计**：ISSUE-002 的有界退避 + 显式唤醒（含 `patched` 历史重放保护）。
5. **P1 方案设计 + 验证计划**：ISSUE-003 的"减少重复整页加载"（必须先证明请求关联不被破坏）。
6. **P1**：ISSUE-004 新增跨操作重复指标与"业务请求/总流量"双视图，使"重复请求下降 ≥50%"首次可度量。

### 6.2 需要你授权的具体事项

| 编号 | 事项 | 我的建议 |
|---|---|---|
| A1 | 是否修正 `test_network_mode_is_persisted_and_immutable` 的期望列表（加 13） | 建议授权，1 行改动，恢复集成全绿 |
| A2 | 本轮修复的提交方式（部分暂存 vs 整文件） | 建议**部分暂存**，保证提交只含 A + C1 |
| A3 | 是否将"达人 2 资料字段 FAILED（转化/履约/种草）"单独立项为 P1 | 建议立项，它与本轮合并无关但影响业务可用性 |
| A4 | 是否授权 ISSUE-002（P0）进入方案设计与实施 | 建议授权，收益最确定 |
| A5 | 是否授权 ISSUE-003（P1）先做"请求关联安全性"验证再谈实现 | 建议先验证、后实现 |
| A6 | 是否授权 ISSUE-004（P1）新增指标（不改既有字段语义） | 建议授权，为后续量化提供依据 |
| A7 | 是否接受合并后"耗时 197 s / L0 3924 / 每达人 3 次整页加载"的现状作为新基线 | 需你确认；这是"精选真正执行"的必然结果 |
