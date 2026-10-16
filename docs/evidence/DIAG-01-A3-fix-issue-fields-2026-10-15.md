# DIAG-01 / A3 修复报告：达人必需字段缺失（触发式最小修复）

- 日期：2026-10-15（Asia/Shanghai）
- 分支 / HEAD：`llb_1013` / `ee11254`（**未 commit、未 push、未 merge**）
- 关联：[诊断报告](DIAG-01-missing-required-fields-2026-10-15.md)｜[A+C1 修复报告](DIAG-01-fix-issue001-2026-10-15.md)｜[卡片](../tasks/DIAG-01.md)
- 修复后指纹（sha256）：`adapter.py` `028eedff…`／`contracts.py` `7a534ef1…`／`douyin_xingtu.verified.json` `24679b6a…`／`test_module_wakeup.py` `3b899fd9…`
- 改动范围：**1 个源文件新增 1 个私有方法**（+1 行调用）、**1 个校验守卫收窄**、**注册表 2 个模块登记已核验交互**、**新增 12 个离线测试**。未改 Schema、未改迁移、未改 API、未改调度、未改执行单元/会话策略、未改身份校验。

---

## 一、产品负责人摘要

### 1.1 19 个失败字段恢复了多少

达人 2（`7282701602991898661`）：**FAILED 19 → 10**（−9，−47%）。

| 变化 | 数量 | 明细 |
|---|---|---|
| **→ `COLLECTED`** | **8** | 种草 2（看后搜人数 `10 - 100`、看后搜比例 `<0.02%`，**真实数据**）＋ 转化 6（GPM/销售额/组件点击数/组件点击率/相关 CPC/商品价格区间，**值为平台占位符 `-`**） |
| **→ `NO_DATA`** | **1** | 种草「搜索词点击率」：请求已到、平台未下发该路径，命中契约既有 `missing_source_status=NO_DATA` 声明 |
| **`MODULE_TIMEOUT` → `MISSING_SOURCE`（仍 FAILED，但状态更真实）** | **6** | 种草 3（A3 增量及同行排名、看后搜人数/比例… 实为 `a3_increment`、`search_after_view`、`search_after_view_rate`）＋ 转化 3（推荐商品数、相关视频数、相关视频播放中位数）——**请求已到达，平台确实未下发这些路径** |
| **仍 `MISSING_SOURCE`** | **3** | 履约：最大承接订单数、行业订单分布、行业播放分布（修复前即如此，平台对该达人返回 7 个键而非 10 个） |
| **仍 `MODULE_TIMEOUT`** | **1** | 履约「合作行业分布」← `order_experience`：**任何交互下平台都未请求该接口**（见 §四，已停止该子项） |

**关键诚实说明**：8 个转为 `COLLECTED` 的字段里，**只有 2 个带真实业务数据**；其余 6 个的值是平台返回的字面占位符 `-`（原始 `raw_value` 实测为 `'-'`）。同一达人 `local_sales_overview` 全部为 `0`（`gpm:"0"`、`order_cnt:"0"`）——即**平台认定该达人没有转化/带货数据**。因此本次修复的收益不是"凭空多出 6 个可用指标"，而是"**不再把平台无数据误报成采集失败**"，并取回 2 个真实种草指标。

### 1.2 哪些仍然失败、为什么

- **6 个新增 `MISSING_SOURCE`**：来源请求均已 `200` 到达（见 §二证据），但响应里没有契约登记的路径 → **平台未下发**，非解析缺陷。
- **3 个履约 `MISSING_SOURCE`**：同上，且修复前即如此（探针实测：该达人 `contract_base` 返回 7 个顶层键，达人 1 返回 10 个，缺的正是这 3 个）。
- **1 个 `order_experience`**：达人 2 在**裸加载、点「达人概览+商业能力」、点「创作能力」、点「履约能力」、点「连接用户」**全部情况下都未发出该请求（达人 1 在裸加载即发出）→ 平台不会为无合作经历的达人请求该端点。**触发条件无法在现有证据下确定，已按授权停止该子项**（不扩大访问范围）。

### 1.3 达人数据完整率改善

| 口径 | 修复前 | 修复后 | 变化 |
|---|---|---|---|
| 达人 2 `COLLECTED / 81` | 59（72.8%） | **67（82.7%）** | **+9.9pp** |
| 达人 2 `FAILED` | 19 | **10** | −47% |
| 达人 2 `NO_DATA` | 3 | 4 | +1（语义更准） |
| 两达人合计 `COLLECTED / 162` | 138（85.2%） | **146（90.1%）** | +4.9pp |
| 达人 1（对照） | 79 `COLLECTED` + 2 `NO_DATA` | **完全相同** | **0 变化** |

### 1.4 对媒介商业评估能力的提升

- **真实新增可用数据 2 项**：种草「个人页看后搜人数」「个人页看后搜比例」（P1 级：主页种草外溢效果）——此前完全缺失，现在有值。
- **数据可信度提升（最大收益）**：此前 16 个字段显示"采集失败（超时）"，会让人误以为系统/网络有问题并触发无意义补采；现在其中 6 个明确显示"平台未下发"，1 个显示"平台无数据"，6 个显示平台占位符值 → 媒介能正确区分"我们没有采到"与"平台本来就没有"。
- **报价能力提升有限**：达人 2 的 GPM/销售额/CPC 等报价锚点虽从"失败"变为"有值"，但值是 `-`（平台无数据），**报价时仍不能使用**；这批达人的报价评估依旧依赖其他模块。
- **未改善项**：`max_processing_order_count`（最大承接订单数，P0 产能判断）仍缺失，原因是平台未下发。

### 1.5 是否有新风险

**未发现新风险。** 对照达人在 81 个字段上**零变化**；请求总量 +1.2%（3924 → 3970，仅达人 2 的 2 个请求及其渲染连带）；**页面加载次数完全不变（6 次达人主页 / 7 次平台文档）**；`duplicate_request_count=0`、`failure_counts={}`、`challenge_count=0`、`rescan_reasons=[]`；Temporal 仍为 **1 次 Activity、0 个定时器**；精选链路 4 行/11 卡/11 封面不变。

---

## 二、技术修复报告

### 2.1 修改文件与位置

| 文件 | 位置 | 改动 |
|---|---|---|
| [`backend/src/xingtu/adapter.py`](../../backend/src/xingtu/adapter.py) | `profile()` 1204 行调用 + 新增 `_wake_unresolved_modules`（1218-1245） | 在同一个已登记窗口内，为「必需响应尚未到达」的模块执行其自身登记的 `actions` |
| [`backend/src/xingtu/contracts.py`](../../backend/src/xingtu/contracts.py) | `_check_module` 539 行 | 守卫由 `capture_on_profile_load and (entry or actions)` 收窄为 `capture_on_profile_load and entry`，错误码改为 `PROFILE_LOAD_MODULE_HAS_ENTRY`（仍禁止离开达人主页） |
| [`contracts/douyin_xingtu.verified.json`](../../contracts/douyin_xingtu.verified.json) | `modules[seeding]`、`modules[conversion]` | 登记 2 个**已核验**交互：点击「达人概览」→「商业能力」；`evidence_refs` 增加本报告 |
| [`backend/tests/unit/test_module_wakeup.py`](../../backend/tests/unit/test_module_wakeup.py) | 新增 | 12 个离线用例（门控语义 + 注册表不变量） |

### 2.2 根因（含请求级证据）

**原问题**：达人 2 有 16 个必需字段报 `MODULE_TIMEOUT`，5 次采集（跨 2 天）完全一致。

**根因**：`profile()` 为所有「页面加载即采集」模块打开**一个**登记窗口，但**只执行 `modules[0]` 的 `actions`**；而 `modules[0]` 是 `basic`，其 `actions` 为 `[]` → **整个初始窗口不执行任何交互**。`seeding`/`conversion` 声明 `capture_on_profile_load=true`、`actions` 为空，即**假定平台会在主页加载时自行发出这些请求**。该假定对达人 1 成立、对达人 2 不成立。

**证据（本轮定向只读探针，脱敏）**：

| 观测 | 达人 2 | 达人 1（对照） |
|---|---|---|
| 裸加载 20 s 内出现的登记端点 | `local_sales`、`link_structure`、`contract_base` | **全部 6 个**（含 `seed_base`、`conversion`、`order_experience`） |
| 点击「达人概览」+「商业能力」后 | **`seed_base`（+2.2 s）、`conversion`（+2.3 s）均 200** | 同样再次 200 |
| 页面上的标签 | 达人概览 / 商业能力 / 创作能力 / 履约能力 / 连接用户 | 同 |
| 点击「履约能力」后 | 仅 `contract_base` 再次 200（**`order_experience` 始终不出现**） | 同 |

→ 结论：`seed_base`/`conversion` **可经已核验的标签交互触发**；达人 2 的 16 个字段是**触发时机**问题，**不是超时太短**。
（对照证据：`read()` 本身已有有界 settle 等待——它等待所有 `required` 规格 settle，超时才记 `MODULE_TIMEOUT`；因此延长 timeout 无效。）

### 2.3 修复方法（最小、加法式）

1. **注册表**：把**已经核验过的**featured 交互（`达人概览`→`商业能力`，同一页面、同一契约、同样选择器）登记为 `seeding`/`conversion` 自身的 `actions`。**未新增任何选择器**（测试断言这两个选择器必须已存在于 featured 的已核验交互集合中）。
2. **代码**：`profile()` 在共享就绪等待之后，遍历同一批初始模块，**仅当该模块仍有 `required` 响应未到达时**才执行它自己的 `actions`，并再次 `wait_ready`（其登记的就绪选择器，本例为 `div.author-info`）。
3. **校验守卫收窄**：原守卫禁止「加载采集模块 + 交互」，其依据（"必须在导航前登记观察，事后登记会丢数据"）在本实现下不再成立——观察仍**先于导航**登记，交互在**同一个窗口内、`read()` 之前**执行。守卫保留对 `entry` 的禁止。

**为什么这样做而不是"改成长度更长的超时"**：请求在裸加载路径上**永远不会到来**，延长超时只会延长失败时间。

**为什么保留 `capture_on_profile_load`**：达人 1 这类会预取的达人仍走原来的"加载即得"路径，**门控使其完全不产生额外点击与额外请求**（见 §2.4 实测）。

### 2.4 请求关联与数据正确性验证

| 验收点 | 证据 | 结果 |
|---|---|---|
| 请求/响应属于当前达人 | 契约 `request_match: {o_author_id: $creator_id}`，`ResponseCollector.on_request` 按参数绑定匹配；本次新增请求出现在**该达人自己的资料窗口**（15:44:53 窗口，达人 2） | ✔ |
| 未跨达人/跨模块串数据 | 达人 1 的资料窗口请求集合与修复前**逐项相同**（`seed_base 1 / conversion 1 / order_experience 1 / contract_base 1 / local_sales 1 / link_structure 2`）；达人 2 仅多出 `seed_base 1 / conversion 1` | ✔ |
| 恢复值来自正确来源 | 8 个恢复字段的 `source_kind=response`、`source_contract=xingtu-ad-creator-featured-v10`，来源请求与路径与契约一致（如 `personal_search_after_view ← seed_base.personal_avg_search_after_view_cnt`） | ✔ |
| 对照达人不回归 | 达人 1 字段级 **0 变化**（79 `COLLECTED` + 2 `NO_DATA`，`profile_complete=True`，`gaps=0`） | ✔ |
| 模块完成状态准确 | 达人 2 `seeding` `FAILED 6→3`（+`NO_DATA 1`）、`conversion` `FAILED 9→3`；`complete` 仍为 `False`（仍有缺口）——与字段结果一致 | ✔ |
| 任务终态与完整性一致 | 仍 `PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE`，`gaps 19→10`，未伪报完成 | ✔ |
| 数据入库 | 精选 4 行 / 卡片 11 / 封面 11 不变；快照含新字段值与来源 | ✔ |
| 请求与加载未异常增长 | L0 3924 → **3970（+1.2%）**；达人主页加载 **6→6**；平台文档导航 **7→7** | ✔ |
| 无新重复/重试/异常 | `duplicate_request_count=0`、`failure_counts={}`、`challenge_count=0`、`rescan_reasons=[]`、Temporal **1 Activity / 0 定时器** | ✔ |

### 2.5 自动化测试结果

| 检查 | 命令 | 结果 |
|---|---|---|
| 新增离线用例 | `pytest backend/tests/unit/test_module_wakeup.py` | **12 passed** |
| 单元 | `pytest backend/tests/unit` | **271 passed**（修复前 259，新增 12，无回归） |
| 契约 | `pytest backend/tests/contract`（需 `PLAYWRIGHT_BROWSERS_PATH`） | **33 passed** |
| 集成 | `pytest backend/tests/integration` | **81 passed / 1 skipped / 1 failed** |
| 类型 | `mypy backend/src`（strict） | **Success: no issues found in 32 source files** |
| 规范 | `ruff check backend conftest.py tests` | **All checks passed** |
| 格式 | `ruff format --check backend conftest.py tests` | **79 files already formatted** |

- 集成唯一失败仍是**既有** `test_network_mode_is_persisted_and_immutable`（断言迁移集合恰为 `[1..12]`，而迁移 013 已应用）。该测试只断言迁移版本、导入 `SyntheticAdapter`，与本修复无关；**未修改**（C 级待确认，见 §四）。
- 单元用例覆盖：必需响应缺失→唤醒；已到达→**不重复交互**；部分到达→仍唤醒；仅可选响应缺失→不唤醒；无 `actions` 的模块不被触碰；`modules[0]` 不被重复执行；注册表层面「新增交互必须是已核验选择器」「原本正常的模块不得新增交互」「请求与字段契约不得变化」「加载模块仍禁止 `entry`」。

### 2.6 真实采集回归结果

- 任务 `28371a91-ccea-483e-931f-c58a173e8505`，产品前端一次提交（发送前硬校验：`keyword=汽车`、`target_count=2`、无附加筛选、`requirement_form.v2`）。
- 达人：`7282701602991898661`（问题样本）、`7503176021160493065`（对照），**与诊断阶段同一对达人**。
- 环境与诊断阶段一致：同代码分支、同 Chrome/Playwright、同执行单元与会话、同网络、同契约超时、同调度；worker 与 API 均重启以加载新契约与新代码。
- 结果：`PARTIAL_COMPLETED`，墙钟 **191.5 s**，`observed_requests=88`/`observed_responses=88`，`navigation_count=7`，`featured_status=COMPLETED`，`featured_complete_count=2`，`valid_count=2`。
- 字段级：达人 2 `FAILED 19→10`、`COLLECTED 59→67`；达人 1 **零变化**。

---

## 三、修复前后对比

| 指标 | 修复前（`bc393088`） | 修复后（`28371a91`） |
|---|---|---|
| 达人 2 必需字段 `FAILED` | 19 | **10** |
| ├ `MODULE_TIMEOUT` | 16 | **1** |
| ├ `MISSING_SOURCE` | 3 | **9** |
| ├ `NO_DATA` | 3 | 4 |
| └ `COLLECTED` | 59 | **67** |
| 达人 2 字段完整率 | 72.8% | **82.7%** |
| 达人 1 `FAILED` / `COLLECTED` / 字段变化 | 0 / 79 / — | **0 / 79 / 0 变化** |
| 两达人合计完整率 | 85.2% | **90.1%** |
| 任务终态 | `PARTIAL_COMPLETED`／`PROFILE_SCOPE_INCOMPLETE` | 不变（`gaps 19→10`） |
| 任务 `gaps` | 19 | **10** |
| 业务请求（L1 `observed_requests`） | 83 | 88（+6.0%） |
| L0 全部请求 | 3924 | 3970（+1.2%） |
| 达人主页整页加载 | 6 | **6（不变）** |
| `duplicate_request_count` | 0 | **0** |
| `challenge_count` / `failure_counts` | 0 / `{}` | **0 / `{}`** |
| 精选行 / 卡片 / 封面 | 4 / 11 / 11 | **4 / 11 / 11** |
| Temporal Activity / 定时器 | 1 / 0 | **1 / 0** |
| 墙钟耗时 | 191.2 s | 191.5 s（不变） |

---

## 四、C 级事项（**已停止，等待授权**）

1. **6 个字段的 `-` 占位值应为 `NO_DATA`？** 平台对达人 2 返回字面 `'-'`（`raw_value='-'`），且 `local_sales_overview` 全为 `0`。现有机制 [`FieldSpec.empty_values`](../../backend/src/xingtu/contracts.py) 正是为此设计（`empty_values → NO_DATA`）。**未实施**：这会改变 `COLLECTED/NO_DATA` 的业务语义与统计口径 → 需要你确认。授权后改动仅为契约字段级声明（`empty_values: ["-"]`），无代码改动。
2. **3 个履约 `MISSING_SOURCE` 是否声明 `missing_source_status=NO_DATA`？** 证据：平台对该达人返回 7 个顶层键（达人 1 为 10），缺失的正是这 3 个（`max_process_order_cnt`、`industry_order_distribution`、`industry_vv_distribution`）。同样**未实施**（语义变更）。契约中已有 3 个种草字段使用该声明，属既有机制。
3. **`order_experience` 子项已停止**：裸加载、5 个标签逐一尝试后**平台均未请求该端点**（达人 1 裸加载即发出）。判断为"平台不为无合作经历的达人请求该端点"，但**无法在现有证据下证明**，且进一步验证需要扩大访问范围 → 按授权停止并报告。
4. **`contract_version` 是否按流程升级？** **我未升级**（仍 `xingtu-ad-creator-featured-v10`），理由：本次未改动任何请求、路径、字段、单位或 Schema，升级只会新建 `contract_health`/`contract_capability_health` 行并**重置既有能力健康计数**（可能静默重新启用已自动禁用的能力），而数据语义完全不变。如团队规范要求"交互变更也须升版"，这是一处一行改动，请指示。
5. **集成既有失败测试**（`test_network_mode_is_persisted_and_immutable` 期望值补 `13`）：**未修改**，待授权。

---

## 五、Git 工作区边界（§七要求）

- 开工前快照：`.runtime/a3/git-baseline.txt`（`llb_1013` / `ee11254`；工作区 116 项 = 77 未跟踪 + 39 已修改）。
- **本轮 A3 新增**：`backend/tests/unit/test_module_wakeup.py`（新文件）、`docs/evidence/DIAG-01-A3-fix-issue-fields-2026-10-15.md`（本文件）、以及三方文件中的**本轮增量**（`adapter.py` 的 `_wake_unresolved_modules`；`contracts.py` 的守卫收窄；契约 JSON 的 2 段 `actions` + 1 条 `evidence_ref`）。
- **必须注意**：`adapter.py`、`contracts.py`、`contracts/douyin_xingtu.verified.json`、`observer.py`、`challenge.py`、`browser_host.py` 等**同时包含你既有的未提交改动**（例如契约 JSON 相对 HEAD 已有 3248 行未提交变更）。因此若要"只提交 A3"，必须**部分暂存**；`observer.py` 我**完全未改动**（其未提交改动属你的 FILTER-01 工作，且经核实其新增的属性筛选门控对本次涉及的 20 个请求全部惰性——`attribute_filter_match` 均为 `None`、历史快照中 `RESPONSE_UNCORRELATED` 出现 0 次）。
- 未执行任何破坏性 Git 操作；**未 commit / 未 push / 未 merge**。A3 与 A+C1 应分属不同提交。

---

## 附：探针证据（脱敏摘要）

- 脚本：`.runtime/a3/tab_trigger_probe.py`（gitignored；只读：仅导航 + 点击**契约已登记**的标签）。
- 原始结果：`.runtime/a3/tab-trigger-probe.json`。
- 仅记录：method / host / path / HTTP 状态 / content-type / 耗时 / **响应顶层键名**。**不含**取值、正文、查询串、Header、Cookie。
- 关键原始行（达人 2）：`contract_base` `top_keys=7`，缺 `max_process_order_cnt`、`industry_order_distribution`、`industry_vv_distribution`；达人 1 同请求 `top_keys=10`，三者齐备。
- 已知瑕疵（如实记录）：探针 `KEY_BEARING` 中 `seed_base` 的路径误写为 `data_sp`（实际为 `aggregator`），导致未采集到 `seed_base` 的键名；该字段的真实下发情况由本次真实回归的字段级结果确定（A3 增量/看后搜人数/看后搜比例 = `MISSING_SOURCE`，个人页看后搜两项 = `COLLECTED`）。
