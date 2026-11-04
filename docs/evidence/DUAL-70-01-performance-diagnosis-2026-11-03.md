# 巨量星图 70 位采集任务性能诊断报告

状态：**诊断完成；P0 修复（唤醒 + featured 局部化）已获授权并实施；星图 70 位最终 70/70（`PARTIAL_COMPLETED`，资料完整 22/70），聚星 70 位 `COMPLETED` 70/70**  
任务：`51dfca56-54c9-4d02-a5e4-da29f0f7d719`（巨量星图，target=70；00:01:22 `FAILED 32/70`，00:21/00:42 两次前端“继续采集”，02:33 达 70/70）  
诊断快照：2026-11-03T23:40—23:52 +08:00（快照时有效 27—28，`COLLECTING`）；00:01:22 任务因同一路径的浏览器动作超时失败，终态 `FAILED / PLATFORM_PAGE_CHANGED:BROWSER_ACTION_FAILED`  
关联任务卡：[DUAL-70-01](../tasks/DUAL-70-01.md)

## 0. 00:01 失败事件（诊断过程中发生，非诊断干预）

- 00:01:22 worker 日志：`TimeoutError: Locator.click: Timeout 90000ms exceeded. waiting for locator(".el-tabs__item:has-text('商业能力')")`；任务随即 `FAILED`，failure_reason=`PLATFORM_PAGE_CHANGED:BROWSER_ACTION_FAILED`。
- 失败位置：`position 32` 的 `_wake_unresolved_modules` 初始主页唤醒路径（`adapter.py:1464-1493`），不在 `collect_module` 的模块级局部化保护内。
- 数据没有丢失：`valid_count=32`，`task_creators` distinct=32，`creator_snapshots` distinct=32，重复=0，平台污染=0，单元已释放；`task_checkpoints` 保留 40 候选、`visited_cursors=[null,"2"]`、`active_seconds=6429.8`。
- 本轮**没有**暂停、取消、重启、重试或继续该任务；失败由平台页面动作超时触发，诊断只做只读查询。是否使用“继续采集”恢复，等待你的授权。

## 1. 核心结论（给产品负责人）

1. **当前慢速是真实的，但不是“第 2 页有另一套慢逻辑”**。详情页采集代码对第 1/2 页完全相同；第 2 页变慢主要由**两个异常达人**触发同一条**初始主页唤醒路径**造成，搜索页码不是直接原因。
2. **第 2 页确实比第 1 页慢，但中位数和均值要分开看**：
   - 第 1 页 20 位完整样本：达人周期（上一位完成→下一位 basic 完成）中位数 **110.9s**，均值 136.5s。
   - 第 2 页快照时 7 位有效/6 位完成：周期中位数 **213.8s**，均值 486.6s；均值被两个 **943s / 931s** 的异常样本拉高。
   - 第 2 页正常达人（position 20/21/23/24/26）的模块采集跨度仅 **27.9—35.8s**，与第 1 页正常达人同量级。故“第 2 页整体代码变慢”不成立；**异常个体是主要矛盾**。
3. **主要时间不在 60/90 秒模块等待里**：
   - 第 1 页每位达人模块采集跨度中位数 **22.0s**，第 2 页正常达人约 **28—36s**；精选两组中位数约 **36—41s**；每位的“尾部”（精选→下一位 basic，含页面导航/初始模块/落库）中位数第 1 页 **51.3s**、第 2 页 **84.3s**。
   - 两个异常达人的 `fans` 观测间隔 **735.86s / 738.16s**，`creation` **207.3s / 193.1s**；但它们最终都是**成功采集**（字段齐全、`failure_counts={}`），不是模块失败/超时重试。
   - **关键更正**：735s 不在 `collect_module(fans)` 内（`module_seconds.fans` 全任务累计仅 441s，小于单个 735s）；它在 `fans` 观测之前，属于 `profile` 的 `_wake_unresolved_modules` 初始唤醒路径。该路径串行执行 seeding/conversion 的“商业能力”点击与就绪等待，每步可由 Playwright 默认 **90s** 超时，多次串行叠加即可到 **540—735s**；00:01 的失败日志正是同一 locator 的 90s 超时，证明这条路径真实存在且可导致任务级失败。
4. **60—90 秒是配置的超时/等待上限，不是主动延迟**。代码中明确的主动等待只有：
   - `action_interval_seconds=2.0`：每次模块动作后的访问节奏 sleep（设计为访问保护/节奏控制，平台限流阈值尚未实测）；
   - `response_settle_seconds=3`（creation）/`5`（featured）：为懒加载封面等预留的固定窗口。
   其余 60/90 秒来自 `operation_timeout_seconds=90`、模块 `timeout_seconds=60`、页面默认超时、`ResponseCollector.read` 60s、`wait_ready` 90s 等**超时/就绪等待**。
5. **735s 的机制已可解释为“串行唤醒等待”，而不是单模块超时或纯持久化**：
   - `_wake_unresolved_modules` 对 `seeding`/`conversion` 各执行 2 个动作（均为点击“商业能力”），并对每个尚未收到 required 响应的模块执行 `wait_ready`；
   - 这些动作**不在** `collect_module` 的 `PlaywrightTimeoutError` 局部化 try/except 内，超时会直接冒泡到 worker 的通用 `BROWSER_ACTION_FAILED`；
   - 快照中页面停留在“商业能力”与“登录后子页”状态，和唤醒 locator 一致；
   - 正常达人首次加载已返回 required 响应，`_wake_unresolved_modules` 直接跳过，故 fans/creation 只需 13—20s；异常达人首次加载缺失响应，串行点击/等待被放大。
6. **是否存在优化空间：有，而且根因明确**。最小修复是把 `_wake_unresolved_modules` 的动作/就绪超时**局部化到模块**（与 `collect_module` 一致，记为 `MODULE_ACTION_TIMEOUT`/`MODULE_READY_TIMEOUT`），并对同一 tab 的重复唤醒做去重/短路；这样既不会因一个 tab 超时杀死整个任务，也能把长尾压回可控范围。**本轮不修复**，等待授权。
7. **任务已失败，32/70，38 位未完成**；已采 32 位唯一有效数据已持久化，未丢失。是否继续同一任务需你授权；修复前不建议直接重跑 70。

## 2. 性能耗时分析

### 2.1 样本与口径

- 使用运行中任务的 `task_checkpoints.payload` 只读分析；不写数据库、不触碰采集浏览器。
- “模块跨度”= 该候选第一个模块观测时间 → 最后一个模块观测时间；“周期”= 上一候选 basic 观测 → 下一候选 basic 观测；“尾部”= 上一候选最后观测（含精选）→ 下一候选 basic 观测。
- 观测时间来自 `ModuleObservation.observed_at` / `FeaturedCollectionObservation.observed_at`；它们是**观测写入时间**，不是模块内部每个子步骤的精确开始时间。因此下表是**可审计的近似**，不是每个内部操作的精确耗时。
- 第 1 页：20 位全部完成；第 2 页：快照时 7 位有效、6 位完成，剩余候选仍在采集。第 2 页样本小，结论标注为阶段性。

### 2.2 页级对比（快照）

| 指标 | 第 1 页 | 第 2 页 | 差异/说明 |
|---|---|---|---|
| 已完成/有效达人 | 20 / 20 | 6 / 7（快照） | 第 2 页未采完 |
| 模块跨度中位数 | 22.0s | 35.4s | 正常第 2 页达人 27.9—35.8s |
| 模块跨度均值 | 36.2s | 333.8s | 被 943s / 931s 异常拉高 |
| 模块跨度最大值 | 245.3s（第 1 位初始达人） | 943.2s | 异常个体 |
| 周期中位数 | 110.9s | 213.8s | 第 2 页样本仅 6 |
| 周期均值 | 136.5s | 486.6s | 异常个体主导 |
| 尾部中位数 | 51.3s | 84.3s | 含精选/导航/落库 |
| 精选两组中位数 | 36.2s | 40.9s | 无实质差异 |
| `module_seconds` 聚合（快照） | — | — | fans 441s、creation 1008s、其余约 189s/模块 |

> 结论：**第 2 页中位数确实更高**（周期 213.8s vs 110.9s），但不能据此认定“第 2 页触发了特殊慢逻辑”。详情页模块代码与第 1 页相同；第 2 页的均值由两个异常个体主导，正常个体与第 1 页同量级。

### 2.3 异常个体（第 2 页）

| 位置 | 状态 | 有效 | 模块跨度 | fans 间隔 | creation 间隔 | 精选合计 |
|---|---|---|---|---|---|---|
| position 20 | done | 是 | 35.05s | 14.27s | 20.78s | 38.8s |
| position 21 | done | 是 | 27.95s | 14.83s | 13.12s | 39.3s |
| **position 22** | done | 是 | **943.16s** | **735.86s** | **207.30s** | 130.4s |
| position 23 | done | 是 | 29.60s | 16.51s | 13.09s | 40.9s |
| position 24 | done | 是 | 35.80s | 18.57s | 17.23s | 40.9s |
| **position 25** | done | 是 | **931.25s** | **738.16s** | **193.09s** | 132.1s |
| position 26 | done/收尾 | 是 | 19.82s+ | 19.82s | 进行中 | 42.0s |

- position 22/25 的 `fans` 观测**最终成功**，9 个字段齐全；`failure_counts={}`、`challenge_count=0`。所以这不是“fans 模块失败后等待下一次重试”，而是一次**成功但极慢**的模块间/页面间等待。
- `module_seconds.fans` 全任务累计 441s，**小于** position 22 单独的 735s 间隔；说明这 735s **不是** `collect_module(fans)` 的采集耗时，而是发生在它开始之前的引擎处理/落库或浏览器调用卡顿。
- position 22/25 的 `creation` 约 193—207s，明显高于正常的 13—21s；同一页面的精选也约 130s（正常约 19—20s 的第二组）。这说明异常达人的**页面整体响应/渲染**或**该页面产生的数据量**比正常达人大，但 checkpoint 中该候选的 JSON 体积（约 360—500KB）**并不显著高于正常达人**，因此“字段体积”不足以单独解释。

## 3. 根因证据

### 3.1 60—90 秒来源（源码与契约）

| 机制 | 位置 | 数值/行为 | 性质 |
|---|---|---|---|
| 全局操作超时 | [contracts/douyin_xingtu.verified.json:3280](../../contracts/douyin_xingtu.verified.json#L3280) | `operation_timeout_seconds=90` | 超时上限 |
| 页面默认超时 | [adapter.py:577-578](../../backend/src/xingtu/adapter.py#L577-L578)、`profile`/`collect_module` 设置 | 90s | 超时上限 |
| 模块响应读取 | [observer.py:413-438](../../backend/src/xingtu/observer.py#L413-L438) | 每模块 `timeout_seconds=60`（fans/creation 等） | 等响应超时 |
| `wait_ready` | [adapter.py:580-596](../../backend/src/xingtu/adapter.py#L580-L596) | 90s 截止，0.25s 轮询 | DOM 就绪等待 |
| 模块动作 | [adapter.py:650-663](../../backend/src/xingtu/adapter.py#L650-L663) | Playwright 默认 90s + `action_interval_seconds=2` sleep | 动作 + 主动节奏 |
| 会话检查 | [adapter.py:932-970](../../backend/src/xingtu/adapter.py#L932-L970) | 最长 90s | 等待受保护页/账号可见 |
| 身份确认 | [adapter.py:1495-1510](../../backend/src/xingtu/adapter.py#L1495-L1510) | 5s cap | 有界等待 |
| featured 读取 | [adapter.py:1751-1790](../../backend/src/xingtu/adapter.py#L1751-L1790) | 60s + `response_settle_seconds=5` | 等响应 + 固定窗口 |
| 访问节奏 | 契约 `action_interval_seconds=2.0` | 每个动作后主动 sleep 2s | **主动访问节奏** |
| creation settle | 契约模块 `response_settle_seconds=3` | 固定 3s | 主动等待封面/懒加载 |
| 封面抓取 | [adapter.py:2208-2300](../../backend/src/xingtu/adapter.py#L2208-L2300) | `CoverSpec.timeout_seconds`，JS AbortController/`expect_response` | 有界超时 |

**回答问题：**

- **是主动等待还是超时？** 60/90s 主体是**超时/就绪等待**；明确的主动 sleep 只有动作后 2s 与 creation/featured 的 3/5s settle。没有发现随机延迟或代码级限流器。
- **请求是否已发出、响应是否返回？** 正常达人：动作/请求发出，`capture.read` 在 required 响应到达后提前返回，不会等满 60s。异常达人：`fans` 最终 9 字段齐全，说明响应**最终返回**；735s 不是“响应未返回一直等到超时”的 60s read。
- **是否存在多次串行等待叠加？** 是。单模块最坏路径可叠加：`check_session` 90s + `verify_identity` 5s + action 90s + `wait_ready` 90s + settle 3/5s + `read` 60s；8 个模块 + 2 组精选会放大最坏情况。但正常达人不会命中这些上限。
- **creation 60—90s 的实际来源？** `creation` 的 `fans`/`creation` 模块 timeout=60、全局 90、动作/就绪 90；正常 creation 13—21s，异常 193—207s，符合“动作/就绪等待 + 60s read + settle/解析/封面”的组合，但**无法仅凭配置判定具体命中了哪一个**；需要单模块开始/结束埋点。
- **为什么失败后要很久才进入下一个模块？** 本次两个异常达人**没有模块失败**（`failure_counts={}`）；735s 发生在 `fans` 观测之前，且 `module_seconds.fans` 累计值小于该间隔，说明主要耗时**不在 fans 模块内部**，而在模块之间的引擎/落库/浏览器协议路径。把 735s 直接解释成“fans 超时失败”与证据不符。

### 3.2 为什么 735s 超出配置上限（已定位到 `_wake_unresolved_modules`）

**已确认（源码 + 运行证据）：**
- 735s/738s 间隔发生在 position 22/25 的初始 6 个模块观测（同一时间戳）之后、`fans` 观测之前；`module_seconds.fans` 全任务累计仅 441s，**无法包含**单个 735s，因此该间隔不在 `collect_module(fans)` 内。
- `profile` 在初始主页加载后调用 `_wake_unresolved_modules`（[adapter.py:1464-1493](../../backend/src/xingtu/adapter.py#L1464-L1493)）：对 `seeding`/`conversion` 各执行 2 个动作（均为点击 `.el-tabs__item:has-text('商业能力')`），并对每个尚未收到 required 响应的模块执行 `wait_ready`。
- 这 4 个动作 + 2 次就绪等待**不在** `collect_module` 的 `PlaywrightTimeoutError` 局部化 try/except 内；每个动作/就绪按 Playwright/`wait_ready` 的 **90s** 上限串行执行，4×90 + 2×90 = **540s**，再叠加页面/接口等待即可达到 **735s**。这解释了“恰好两个异常达人”和“页面停留在商业能力”的观察。
- 00:01:22 的真实失败日志与上述路径完全一致：
  - `TimeoutError: Locator.click: Timeout 90000ms exceeded. waiting for locator(".el-tabs__item:has-text('商业能力')")`
  - failure_reason=`PLATFORM_PAGE_CHANGED:BROWSER_ACTION_FAILED`
  - 失败候选 position 32，`state=collecting`，尚未写入任何模块；即**初始唤醒动作超时直接冒泡为任务级失败**，而不是模块级失败。
- 失败证据：`.runtime/evidence/failure/51dfca56-.../c82dd33d....json`；worker 日志 `browser action failure attempt=1`。
- 数据未丢失：`task_creators` distinct=32、`creator_snapshots` distinct=32、`failure_counts={"PLATFORM_PAGE_CHANGED":1}`、单元已释放。

**机制结论：**
- 735s 不是单个模块的 60s read，也不是 90s 的 `wait_ready`，而是**初始主页唤醒路径中多次串行 90s 动作/就绪等待的叠加**；它不在 `module_seconds`，因为 `module_seconds` 只统计 `collect_module`。
- 该路径的失败语义有缺口：`collect_module` 已把可选模块动作超时降级为 `MODULE_COLLECTION_FAILED`，但 `_wake_unresolved_modules` 没有；因此一次 tab 点击超时可以直接把整个任务变成 `FAILED`。
- 同一 tab “商业能力”被 seeding 和 conversion 重复点击；如果首次点击已失败/页面已切换，后续重复点击只会继续消耗 90s，没有去重/短路。
- 第 2 页两个异常达人很可能是首次加载未收到 seeding/conversion 的 required 响应，触发完整唤醒路径；正常达人首次加载已拿到响应，唤醒被跳过，所以只有 13—21s。
- 进程 `sample` 中的 psycopg/Pydantic/GC 是任务背景开销，**不是 735s 的主要解释**；此前“整份 checkpoint 落库导致 735s”的假设降级为次要因素。checkpoint 11MB 的事实仍值得后续优化，但不能替代本次已定位的唤醒路径。

**仍需补充的证据：**
- 每个唤醒动作/就绪的单次耗时（需埋点；本轮未改代码）。
- 为什么 00:01 的“商业能力”locator 在 90s 内不可点击（页面状态/挑战/加载慢）；但无论原因，该动作都不应升级为任务级失败。

### 3.3 第一页 vs 第二页是否有实际耗时差异

- **有，但差异主要来自个体与尾部，不是分页后的特殊代码。**
- 第 1 页周期中位数 110.9s，第 2 页 213.8s；第 2 页样本仅 6 位完成，且包含两个 15 分钟级异常。
- 正常第 2 页达人模块跨度 27.9—35.8s，与第 1 页正常达人（中位数 22s、常见 65—90s 周期）同量级；**模块内部没有系统性变慢**。
- 第 2 页尾部中位数 84.3s vs 第 1 页 51.3s；包含精选/页面导航/初始主页收集与落库；其中异常个体会触发 `_wake_unresolved_modules` 的串行唤醒，是尾部/周期升高的主要已定位来源；其余候选数增长带来的落库/序列化是待量化的次要因素。
- 第 1 页第 1 位达人 245s（初始化/首次页面）与 position 22/25 的 931—943s 都是**离群值**；用均值会误导，需同时看中位数与离群值。

## 4. 优化方案（仅建议，不执行）

| 优先级 | 问题 | 根因证据 | 推荐优化 | 预期收益（估算，未实测） | 风险 |
|---|---|---|---|---|---|
| **P0** | `_wake_unresolved_modules` 的 tab 点击/就绪超时会串行叠加（735s），且可直接把任务打成 FAILED | 00:01:22 `Locator.click` 商业能力 90s 超时；`_wake_unresolved_modules` 在 `collect_module` 局部化保护之外；seeding/conversion 各 2 动作 | **把该路径的动作/就绪超时局部化到模块**（与 `collect_module` 一致，转成 `MODULE_COLLECTION_FAILED:MODULE_ACTION_TIMEOUT`/`MODULE_READY_TIMEOUT`，记录并继续），并**按 tab/模块去重**，同一“商业能力”点击最多一次、已激活则跳过 | 防止任务级失败；把 540—735s 长尾压回单模块上限；提升可预测性 | 中低；模块失败会降低该达人资料完整度（已有语义），不会丢已采数据；需回归模块/精选完整度 |
| P1 | 735s 无法拆分到每个动作/就绪的具体耗时 | 已定位路径但无单次埋点；`module_seconds` 不含唤醒路径 | **无行为变更的耗时埋点**：`_wake_unresolved_modules` 每个动作/就绪 start/end、`repo.edit` 落库耗时、`wait_ready` 单次耗时；写日志/证据，不改 schema | 为 P0 的阈值和去重策略提供依据；可量化剩余尾部 | 低；控制日志量 |
| P1 | 每个初始模块各写一次整份 11MB checkpoint（6 次/达人） | `_save` 写整份 payload；40 候选 11MB；6 模块 6 次 | 合并初始 6 模块为一次 edit/落库（同一 `profile` 窗口已一次性解析），保持观测/去重语义 | 减少 5 次/达人整份写；次要收益，需实测 | 中；崩溃恢复粒度变粗；需测试失败恢复/重试 |
| P2 | `wait_ready` 每 0.25s 调多个 `is_visible`/`check_page_errors` | `wait_ready` 轮询；正常 14—20s 的 fans/creation | 用 `page.wait_for_selector` 等有界等待替代高频轮询，或减少 `ready_hidden` 检查 | 降低协议调用与重页面卡顿概率（估算） | 中；可能改变就绪/错误页时序 |
| P2 | 精选两组每次 reload 主页并顺序加载 | `_collect_featured` `reload_homepage=True`；每组 60s + settle 5s；正常 36—41s | 在不改变卡片身份/去重前提下，复用已加载主页/已有集合观测 | 可能减少尾部 10—30s/达人（估算） | 高；影响精选完整性/卡片身份，需平台证据；不建议先做 |
| P3 | `action_interval_seconds=2.0`、`response_settle_seconds=3/5` | 契约设计 | **保留**；访问节奏/懒加载保护，平台限流阈值未实测 | 不建议优化 | 高（平台保护） |

**收益说明：** 上表收益均为基于当前样本的**估算**，没有做修复后实测，不能承诺百分比。正常达人的中位数已经接近可接受范围；优化重点应是**异常达人的长尾**与**可预测性**，而不是普遍缩短正常路径。

## 5. 对现有功能的影响（若未来实施）

| 优化 | 采集完整性 | 模块成功率 | 解析/入库 | 状态与恢复 | 执行单元/主流程 |
|---|---|---|---|---|---|
| 埋点 | 无影响 | 无影响 | 无影响 | 无影响 | 无影响 |
| 唤醒路径局部化 + 去重（P0） | 可能把个别极端慢达人的对应模块判为失败（字段完整度下降），但不再杀死任务 | 极端 tab 超时提前结束该模块，任务继续 | 模块失败仍按现有失败语义落库；已采数据保留 | 新增 `MODULE_ACTION_TIMEOUT`/`MODULE_READY_TIMEOUT` 归类；需回归 retry/continue | 无影响 |
| 合并初始模块落库 | 无影响 | 无影响 | 事务粒度变化，需验证 payload/观测顺序 | 崩溃恢复粒度变粗；需测试 | 无影响 |
| 减少 `wait_ready` 轮询 | 无影响（需验证） | 可能改变就绪时序 | 无影响 | 无影响 | 无影响 |
| 精选复用/去 reload | 有风险（精选卡片完整性） | 有风险 | 有风险 | 无影响 | 无影响 |

**不应做**：并行采集模块、删除 2s 动作节奏/3/5s settle、跳过可选模块、用候选数替代有效数、为了速度改超时但不保留失败语义。

## 6. 是否建议修复

**建议进入最小修复阶段，但必须先由你授权；本轮未修复、未恢复任务。** 当前任务已经 `FAILED`（32/70），不是“仍在运行”；修复建议如下：

1. **P0 最小修复（推荐）**：把 `_wake_unresolved_modules` 的动作/就绪超时局部化到模块：
   - 捕获 `PlaywrightTimeoutError` / `PAGE_READY_TIMEOUT`，转换为 `MODULE_COLLECTION_FAILED:MODULE_ACTION_TIMEOUT:<module>` / `MODULE_READY_TIMEOUT`；
   - 只对非 basic 的可选模块降级，basic/session/identity/lease 仍 fatal；
   - 同一 tab（“商业能力”）的 seeding/conversion 唤醒去重：已点击/已激活则跳过；避免 4 次重复 90s 点击。
   - 预期：00:01 这类任务级失败变为单个模块失败、任务继续；735s 长尾压回单模块上限级别（估算，需实测）。
2. **P0 配套**：无行为变更的耗时埋点（每个唤醒动作/就绪 start/end），用于验证收益和剩余尾部。
3. **P1（可选，按 P0 结果）**：合并初始 6 模块落库、减少 `wait_ready` 轮询；这些是次要优化，不应与 P0 混在一起。
4. **任务恢复**：修复并回归后，优先对同一 root task 使用现有“继续采集”（保留 32 位已入库数据，不重采），而不是新建 70 位任务；本次失败不等于 32 位数据丢失。
5. **不推荐**：删除 2s 访问节奏/3/5s settle、并行采集、跳过可选模块、用候选数替代有效数。

**仍需要额外证据的部分：**
- 00:01 的“商业能力”locator 为何 90s 不可点击（页面状态/加载慢/挑战）；但无论原因，该动作都不应升级为任务级失败。
- 每个唤醒动作的单次耗时（修复前埋点）。
- 第 2 页中位数升高在排除异常个体后的剩余差异（样本仅 6—7 位）。
- 浏览器内存/CPU 是否随任务时间持续增长（本轮未做高负载监控）。

## 6.1 授权后的 P0 修复与验证状态（2026-11-04T00:18—00:21）

- 授权：用户确认“P0 最小修复 + 5 位验证 + 同一任务继续”。
- 代码：`backend/src/xingtu/adapter.py` 的 `_wake_unresolved_modules`：
  - 捕获 `PlaywrightTimeoutError` → `WAKE_ACTION_TIMEOUT`，捕获 `PAGE_READY_TIMEOUT` → `WAKE_READY_TIMEOUT`，仅标记该模块仍缺失的 required 响应为失败，任务继续；
  - session/challenge/identity/lease 等非可选错误仍 fatal；
  - 同一 click selector 在一次 profile 唤醒中只尝试一次；第二个模块（conversion）缺失响应显式失败，不再重复 90s。
- 测试：`backend/tests/unit/test_module_wakeup.py` 15 例通过；unit **380 passed**、contract **43 passed**、isolated integration **128 passed / 1 skipped**、Mypy 38 files。
- 5 位回归：任务 `3fd596d1-efba-41ff-9546-4b658e8aae8e`，target=5、有效 5、快照 5、失败 0，`PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE`（资料完整 2/5）；正常路径与修复前一致。
- 失败任务恢复：原任务 `51dfca56…` 通过 5173 前端点击“继续采集（还差 38 位）”，`retry` 进入 segment 1；状态 `QUEUED → COLLECTING`，有效保留 32，未新建任务。后续若 7200s 预算暂停，使用前端“继续任务”同一 root task 分段。
- 修复期只重启了星图 Collection Worker（generation 19）；API/Intake/聚星 Worker/前端未重启，采集浏览器只在任务恢复后由该 Worker 打开。
- **第二次失败（00:27）与 featured 修复**：segment 1 在 position 32 再次 `FAILED / BROWSER_ACTION_FAILED`，同一“商业能力”locator；该候选 8 个资料模块齐全、`collections` 为空，说明唤醒路径已通过，失败落在 **featured 精选交互** `_collect_featured` 的 `actions/wait_ready`。新增 `_run_featured_interaction`：`PlaywrightTimeoutError` → `FEATURED_ACTION_TIMEOUT:<collection>`、`PAGE_READY_TIMEOUT` → `FEATURED_READY_TIMEOUT:<collection>`；`featured_spec_local_reason` 已能把 `MODULE_COLLECTION_FAILED` 降级为该 collection 的失败观测，任务继续。新增 `backend/tests/unit/test_featured_localization.py` 3 例；unit **383 passed**、contract **43 passed**、isolated integration **128 passed / 1 skipped**、Mypy 38 files；worker generation 20。
- **任务恢复现状**：`51dfca56…` 第二次失败时有效 33/70；修复后先做第二次 5 位回归，再通过 5173 前端“继续采集”补足剩余 37 位。若出现新的未局部化 Playwright 路径，停止并重新诊断，不盲目重跑。

## 7. 本轮边界与合规

- **诊断阶段（直到 00:01 失败）**：未暂停、取消、重启、重试或继续任务；未重启 API/Worker/Temporal/Redis/PostgreSQL；未修改业务代码、配置、数据库结构或超时参数；未接管采集浏览器、未点击/跳转/刷新采集页；未创建额外真实任务；未重采已有达人。
- **授权后（00:18 起）**：按用户授权实施 P0 最小修复（唤醒路径 + featured 路径），仅重启星图 Collection Worker（generation 19→20）；通过 5173 前端对原失败任务执行“继续采集”并二次恢复，未新建任务、未重采已入库达人；这是用户明确授权的修复/恢复，不是诊断动作。
- 只读使用：任务 checkpoint 查询、`task_checkpoints`/`root_tasks`/PG 统计、进程 `sample`、屏幕截图、现有 MCP 任务状态轮询；诊断操作均在 `.runtime/acceptance/dual-70-20261103/` 私有目录留证（`perf-xingtu-70.json`、`perf_analyze.py`、`db-xingtu-70-failed.json`）。
- 任务在 00:01:22 由平台页面动作超时自行失败；不是诊断操作导致。失败后至授权前未执行任何恢复/重试；已采 32 位数据保留。
- 诊断中曾尝试 `py-spy`（macOS 需 root，未成功），已卸载；未改变业务运行环境。
- 未提交/推送 Git。
- 5 位修复验证任务 `3fd596d1…` 与恢复后的 `51dfca56…` 的最终数据/前端结果在验收报告中回写。

## 8. 证据索引

- 私有耗时明细：`.runtime/acceptance/dual-70-20261103/perf-xingtu-70.json`
- 失败任务核验：`.runtime/acceptance/dual-70-20261103/db-xingtu-70-failed.json`
- 失败证据：`.runtime/evidence/failure/51dfca56-54c9-4d02-a5e4-da29f0f7d719/c82dd33d....json`
- 分页探针：`.runtime/acceptance/dual-70-20261103/pagination-{xingtu,juxing}-{research,contract}.json`
- 任务状态轮询：`.runtime/acceptance/dual-70-20261103/xingtu-70/state.json`
- 源码：
  - [adapter.py:577-596](../../backend/src/xingtu/adapter.py#L577-L596)（超时/就绪）
  - [adapter.py:650-663](../../backend/src/xingtu/adapter.py#L650-L663)（动作 + 2s 节奏）
  - [adapter.py:932-970](../../backend/src/xingtu/adapter.py#L932-L970)（会话检查）
  - [adapter.py:1464-1493](../../backend/src/xingtu/adapter.py#L1464-L1493)（`_wake_unresolved_modules`，本次失败点）
  - [adapter.py:1495-1510](../../backend/src/xingtu/adapter.py#L1495-L1510)（身份确认 5s）
  - [adapter.py:1555-1690](../../backend/src/xingtu/adapter.py#L1555-L1690)（模块采集；已有局部化）
  - [adapter.py:1751-1790](../../backend/src/xingtu/adapter.py#L1751-L1790)（featured）
  - [observer.py:413-438](../../backend/src/xingtu/observer.py#L413-L438)（响应读取 60s）
  - [repository.py:1674-1700](../../backend/src/xingtu/repository.py#L1674-L1700)（整份 checkpoint 落库）
  - [contracts/douyin_xingtu.verified.json:3279-3280](../../contracts/douyin_xingtu.verified.json#L3279-L3280)（2s / 90s）
  - [contracts/douyin_xingtu.verified.json:4034](../../contracts/douyin_xingtu.verified.json#L4034)（seeding 唤醒 locator）
  - [contracts/douyin_xingtu.verified.json:4287](../../contracts/douyin_xingtu.verified.json#L4287)（conversion 唤醒 locator）
