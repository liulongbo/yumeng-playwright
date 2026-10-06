# 巨量星图采集效果测试报告（宠物 · 22 位 · 2026-10-06）

## 1. 测试目的与结论摘要

| 验收问题 | 结论 | 证据 |
|---|---|---|
| 是否正常爬取到达人 | ✅ **是**。搜索"宠物"发现 **40 位候选**，完成 **22 位有效达人**采集（目标 22，`valid_count=22`） | 根任务 `d43abe35-9a42-4cf0-814d-acbba096e352`，`PARTIAL_COMPLETED` |
| 爬取到的字段是否符合代码要求 | ⚠️ **部分符合**。6 个主页模块全部返回 `COLLECTED`，字段级覆盖率 **74.2%**（996/1342 采集成功），但 **0/22 达人满足"主页完整"口径** | 见 §4 |
| 是否可以正常翻页爬取 | ✅ **是**。`visited_cursors=[None,"2"]`，第 1、2 页共扫描 40 位，两页 ID 无重复 | 见 §5 |

**一句话结论**：在"清除旧身份 + 改绑单子账号 + 混合持久化（持久目录 + storage-state 注入）"之后，**采集链路首次在新账号下端到端跑通**；发现能力与翻页能力已验证，字段采集存在**明确、可分类的缺口**（超时/口径未登记），尚未达到"主页完整"验收标准。

## 2. 环境与版本

| 项 | 值 |
|---|---|
| 日期时间 | 2026-10-06 17:47–17:57（+08:00） |
| 执行单元 | `unit-local-mac-02`，绑定 `expected_account_id = ID: 1807978499337419`（当日新登录身份） |
| 网络模式 | `local_development`（本地出口，**不代表生产线路验收**） |
| 浏览器 | 真实 Google Chrome 154.0.8037.98，`headless=false`，`macos_system_keychain=true` |
| 契约 | `xingtu-ad-creator-profile-v2`（`capabilities.version = xingtu-ad-creator-square-v1`），6 模块 / 61 字段 |
| 采集计划 | `.runtime/plans/pet-22-20261006.json`：`keyword=宠物`、`target_count=22`、`sort=score` |
| 运行载体 | `scripts/local_smoke.py`（真实 `Activities.collect` + `CollectionWorkflow`，Temporal 本地测试服务器 v1.9.1） |
| 数据库 | 本地 PostgreSQL 18.3 `xingtu_local_dev` |

## 3. 本轮前置修复（否则采集无法开始）

`SESSION-01` 的账号漂移已在 2026-10-06 通过"清除旧身份 + 改绑单子账号"解决，但采集仍无法进入后台。本轮定位并修复两个独立缺陷：

**修复 A：冷启动会话引导（`adapter.prepare`）**
- 现象：worker 路径下第一次进业务页后被平台重定向，`inspect_session` 一直轮询到 `session_boot_timeout_seconds=180s` 才返回 `INDETERMINATE`，期间重试窗口被耗尽 → 任务反复 `WAITING_FOR_RESOURCE`、候选恒为 0。
- 修复：引导改为**有界重试**（最多 4 次，轮流使用契约登记的 `session.business_urls`），每次探测使用独立的短窗口 `bootstrap_probe_seconds=15s`；最终判定仍由 `check_session` 给出。
- 代码：`adapter._bootstrap_session`、新配置 `session.business_urls`（[contracts.py](../../backend/src/xingtu/contracts.py)、[douyin_xingtu.verified.json](../../contracts/douyin_xingtu.verified.json)）。

**修复 B：混合持久化（持久目录 + storage-state 显式注入）**
- 现象：平台业务会话载体 `.xingtu.cn/star_sessionid` 是**会话级 Cookie**（`is_persistent=0`、`has_expires=0`），关闭浏览器后落盘不确定；表现为同一 profile"有时在登录态、有时被踢回登录页"。
- 修复：会话有效时导出 `context.storage_state()` 到 `.runtime/storage-state/<unit>.json`（`0600`），下次启动**在首次导航前**注入全部 Cookie 与 localStorage；仅在页面出现契约登记的保护页标志、或达人详情页上账号定位器**唯一匹配且等于绑定身份**时才覆盖快照，避免把坏状态写回去（也保证采集成功后的新会话能刷新快照）。
- **对照实验（决定性）**：

| 条件 | 同一 profile 冷启动结果 |
|---|---|
| 注入 storage-state | ✅ 账号 `ID: 1807978499337419`、受保护页可见、URL 正常 |
| 移走快照（其余完全相同） | ❌ 被打回 `/?redirect_uri=...`、账号读不到 |

- 代码：[runtime.py](../../backend/src/xingtu/runtime.py)（`export_session_snapshot` / `_restore_session_snapshot` / `_on_frame_navigated`）、新配置 `capture_session_snapshot`（默认开启）、6 项单元回归 [test_session_snapshot.py](../../backend/tests/unit/test_session_snapshot.py)。

## 4. 达人采集结果

### 4.1 总量

| 指标 | 值 |
|---|---|
| 根任务状态 | `PARTIAL_COMPLETED` |
| `failure_reason` | `PROFILE_SCOPE_INCOMPLETE`（"主页完整"口径未满足） |
| 目标数量 | 22 |
| **有效达人** | **22** |
| 候选发现 | 40（第 1 页 20 + 第 2 页 20） |
| 已扫描 ID | 40 |
| 主页完整 | **0 / 22** |
| 落库快照 | **67 条**（覆盖 22 位达人，`creator_snapshots`） |
| 已观测请求/响应 | 255 / 251 |
| 掉线/挑战计数 | `PLATFORM_SECURITY_CHALLENGE × 4` |

22 位有效达人的主页模块**全部完成采集**（模块状态 `COLLECTED` 131 次、`FAILED` 1 次），但字段级有缺口，因此按契约的"主页完整"判定为不完整。

### 4.2 字段覆盖率（关键）

| 指标 | 值 |
|---|---|
| 字段实例总数（22 达人 × 61 字段） | 1342 |
| `COLLECTED`（成功） | **996（74.2%）** |
| `FAILED`（失败） | 305 |
| `NO_DATA`（平台无数据） | 41 |

失败原因分类：

| 失败原因 | 数量 | 含义 | 性质 |
|---|---|---|---|
| `MODULE_TIMEOUT` | 128 | 单模块采集超时 | **可优化**：模块级超时预算偏紧（观测到模块耗时约 2 秒/正常案例） |
| `RESPONSE_UNCORRELATED` | 114 | 响应与请求条件无法关联（模块内分页/多次请求） | **需修观察器**：模块内增量加载的关联规则 |
| `MISSING_SOURCE` | 63 | 契约声明的字段在当前页面/响应中不存在 | **需登记确认**：部分指标该账号下确实无数据或口径未复核 |

按模块（以一位典型达人为例，字段状态）：

| 模块 | 字段数 | 成功 | 失败 | 说明 |
|---|---|---|---|---|
| `basic` | 15 | 14 | 1（`NO_DATA`：个人介绍无可靠来源） | 昵称/粉丝数/城市/性别等核心字段正常 |
| `spread` | 18 | 13 | 5（`MISSING_SOURCE`） | `play_median`、`average_duration` 等缺源 |
| `seeding` | 7 | 7 | 0 | 全部成功（区间型结构化值） |
| `commercial` | 2 | 2 | 0 | 报价与合作行业正常 |
| `conversion` | 10 | 10 | 0 | 多数字段为 `-`，属平台真实返回值，已无损保留 |
| `fulfillment` | 9 | 9 | 0 | 信用分/订单/回复率正常 |

**字段质量样例**（均来自真实平台响应，结构化保留原值）：

```text
basic.nickname        = 娱乐课代表孙小寒
basic.followers       = {"kind":"number","amount":"4266970","bound":"exact"}
basic.gender          = 2                      # 平台原值，枚举含义待复核
commercial.cooperation_offers = [{"desc":"植入视频", ...}]
seeding.search_after_view     = "<5" / "10 - 100"   # 区间值未被压平成数字
fulfillment.credit_score      = "100" / new_credit_score = 70
```

## 5. 翻页验证

| 项 | 值 | 结论 |
|---|---|---|
| 已访问游标 | `[None, "2"]` | ✅ 第 1 页与第 2 页均实际抓取 |
| 两页候选 | 20 + 20 = 40 | ✅ 无重复 ID（`scanned_ids` 40 且去重） |
| `search_generation` | 1 | 期间发生过一次游标失效重扫（`rescan_reasons=["CURSOR_INVALID"]`），重扫后恢复正常 |
| `exhausted` / `search_stop_reason` | `false` / `null` | 目标数达成即停止，**未验证到平台终点** |
| 契约分页上限 | `page_fetch_max_verified = 2` | 第 3 页及以后**仍不可用**（这正是 AUTO-01 保留的上限） |

## 6. 未达标与遗留

1. **"主页完整"= 0/22**：直接原因是上述 305 个字段失败；在字段口径未收口前不能宣称"完整资料采集可用"。
2. **第 3 页仍是契约上限**：AUTO-01 的 `page_fetch_continuous_verified` 未开启，本轮**未**产生第 3 页真实证据。
3. **一次 `RESPONSE_SCHEMA_MISMATCH` 运行**（17:45，任务 `6708d938`）：某次主页模块响应不满足登记口径即整轮 `FAILED`（该轮已发现 20 位、采到 1 位）。同一代码在 17:47 重跑成功（22 位），说明该失败属**间歇性平台响应**，但当前设计会把它升级为整任务失败，建议改为**模块级降级**并记录缺口。
4. **会话稳定性收益已生效但未做长期验证**：本轮全程未再出现"被踢回登录页"导致的空转；但快照注入属于**凭证复用**，平台若进一步收紧仍需重新评估（对应 SESSION-01 的存活上界未测）。
5. **证据边界**：单次运行、单关键词、单账号、`local_development`；21 位有效达人来自第 1–2 页，未覆盖更长尾与第 3 页以后。

## 7. 结论

- **好消息**：账号不稳定问题（漂移 + 会话被踢）在本轮已用"改绑单子账号 + 混合持久化"压住，采集链路**首次在新账号下端到端跑通**：40 位候选、22 位有效达人、67 条落库快照、两页翻页成功。
- **待办**：字段完整度（74.2% → 目标 100%）需要三项具体修复（模块超时预算、响应关联规则、缺源字段口径登记），并把 `RESPONSE_SCHEMA_MISMATCH` 从整任务失败降级为模块级缺口。
- **不能宣称**：真实平台"完整主页采集可用"、第 3 页及以后可用、无人值守长期运行可用。

## 8. 复现命令

```bash
export XINGTU_DATABASE_URL=postgresql://xingtu_test@127.0.0.1:55439/xingtu_local_dev
export XINGTU_TEMPORAL_TEST_BINARY="$PWD/.runtime/temporal-test/temporal-v1.9.1"
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.runtime/browsers"

.venv/bin/xingtu start --plan .runtime/plans/pet-22-20261006.json \
  --config .runtime/units/local-dev-mac-02.json --key pet22 --actor user-yaoyao
.venv/bin/python scripts/local_smoke.py --config .runtime/units/local-dev-mac-02.json \
  --root-task-id <ROOT_TASK_ID> --timeout-seconds 2700
```

原始运行日志：`.runtime/evidence-run/pet22-final/smoke7.log`；本轮失败证据：`.runtime/evidence-local/failure/6708d938-.../`；根任务：`d43abe35-9a42-4cf0-814d-acbba096e352`。
