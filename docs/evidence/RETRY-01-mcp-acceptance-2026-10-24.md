# RETRY-01 Playwright MCP + Chrome 验收报告（2026-10-24）

- 验收时间：2026-10-24 15:43—15:58（Asia/Shanghai）
- 验收方式：**Playwright MCP 0.0.77**（本地已安装 `@playwright/mcp`），通过 MCP stdio 协议启动服务，全部页面动作与断言经由 `browser_navigate` / `browser_snapshot` / `browser_click` / `browser_type` / `browser_handle_dialog` / `browser_evaluate` / `browser_network_requests` / `browser_take_screenshot` 工具完成；浏览器为 **系统 Google Chrome 156.0.8078.47**。
- 驱动脚本：[scripts/qa/retry01_mcp_acceptance.py](../../scripts/qa/retry01_mcp_acceptance.py) + [mcp_client.py](../../scripts/qa/mcp_client.py)
- 证据目录：[assets/retry01-mcp/](assets/retry01-mcp/)（10 张截图 + 16 份 JSON）
- 结论：**MCP 验收已真实执行**。5 项 UI 标签/文案、2 项接口负向、继续采集、补采缺失字段、正常首次采集均通过 MCP 驱动完成；继续采集的“0 次重访、0 份重复快照”与补采的“0 次搜索、只重读失败模块”得到实证。仍存在 F1/F2/F3 三个待修项，并新发现 F5（执行单元隔离后需人工重启 Worker 才能恢复）。

---

## 1. 为什么可以直接使用 MCP

本会话的工具目录没有暴露 MCP 工具，但全局搜索发现：

- 已安装 `@playwright/mcp 0.0.77`：`/Users/yaoyao/.local/lib/node_modules/@playwright/mcp/cli.js`；
- 系统中已有两个正在运行的 MCP 服务进程（`--browser chrome --isolated --output-dir /tmp/dsh-playwright-mcp`），说明该版本可用；
- 本报告通过 **stdio 启动同一个 Playwright MCP 服务**，握手成功：
  `serverInfo = {"name":"Playwright","version":"1.62.0-alpha-2026-06-29"}`，`tools/list` 返回 **23 个工具**。

启动参数：`--browser chrome --executable-path <系统 Chrome> --isolated --headless --no-sandbox --viewport-size 1440x1000`。
其中 `--no-sandbox` 是外层 DSH 沙箱环境所必需：否则 Chrome 自身 sandbox 初始化失败（`sandbox initialization failed: Operation not permitted`）导致 `Target crashed`；`--executable-path` 与写工作区内的 `HOME`/缓存目录用于避免沙箱外写。

> 这是**测试执行环境**的限制，不是产品代码问题；记录于此保证可复现。

---

## 2. MCP 验收用例与结果

| 用例 | 对应 PRD | MCP 操作 | 结果 |
|---|---|---|---|
| MCP-01 | FR-3/FR-4 | 登录后打开 5 个真实任务，读取 `browser_snapshot` | ✅ 5/5：继续采集/补采/已完成/安全验证/更新任务文案全部正确 |
| MCP-02 | AC-4/§6.1 | `browser_evaluate` 带 CSRF + **Idempotency-Key** 调 `/retry` | ✅ 已完成任务与安全验证任务均返回 **409 ACTION_NOT_ALLOWED** |
| MCP-03 | FR-3 | 点击「继续采集」→ 读取弹窗文案 → `browser_handle_dialog(accept=false)` | ✅ 弹窗文案正确；取消后 `browser_network_requests` **无 `/retry` 请求** |
| MCP-04 | FR-1 | 再次点击 → `browser_handle_dialog(accept=true)` → 轮询终态 | ✅ 1 次 POST；2 位已入库达人的 8 模块 + 2 精选观测 ID 全部不变；快照 **4→4**；`processed_operations 1→1`；有效数 2→2 |
| MCP-05 | §6.1/D3 | 继续采集后重读按钮 | ❌ 仍为「继续采集（还差 1 位）」（F2 复现：搜索耗尽后死循环） |
| MCP-06 | FR-3 | 点击「补采缺失字段」→ 弹窗 → 取消→确认 | ✅ 弹窗文案正确；取消无请求；确认 1 次 POST |
| MCP-07 | FR-2 | 补采并等待终态 | ⚠️ 过程中执行单元被隔离（F5），任务 `WAITING_FOR_RESOURCE`；重启 Worker 恢复后自动续跑完成；**0 次搜索批次**、仅 `basic` 模块重读、其余 7 模块不变 |
| MCP-08 | FR-8 | 恢复后重开任务详情 | ✅ 终态 `PARTIAL_COMPLETED`；仍待补采 1 位；按钮仍「补采缺失字段（1 位）」（F3） |
| MCP-09 | 非功能 | `browser_console_messages` | ✅ 仅登录前 `/api/auth/me` 401（预期），无功能错误 |
| MCP-10 | AC-10 | 通过产品表单新建「宠物 / 1 位」任务并等待终态 | ✅ 新任务 `8b0f0393`：RECEIVED→PARSING→QUEUED→COLLECTING→PARTIAL，有效 1/1、快照 1、导航 4、请求 68；创建与首次采集无回归（终态部分完成由 F3 封面存储导致） |

---

## 3. 关键实证

### 3.1 继续采集：0 次重访、0 份重复快照

MCP 驱动「继续采集」后（[continue.json](assets/retry01-mcp/continue.json)、[continue-before.png](assets/retry01-mcp/continue-before.png)、[continue-after.png](assets/retry01-mcp/continue-after.png)）：

- 弹窗文案：`本次只补足剩余 1 位有效达人，不会补采已入库达人的缺失资料。是否继续？`
- 取消：`cancel_sent_no_request = true`（无 `/retry` 请求）；确认：`accept_sent_request = true`（恰好 1 次）。
- 2 位有效达人：模块观测 ID 全部相同、精选观测 ID 全部相同、`module_history 8→8`；
- `creator_snapshots 4→4`，`changed_since_last_retry = 0`；
- `processed_operations 1→1`（无搜索批次），`navigation_count 9→10`（既有条件重建），`observed_requests 127→128`。

### 3.2 补采缺失字段：0 次搜索、只补失败模块

MCP 驱动「补采缺失字段」后（[backfill.json](assets/retry01-mcp/backfill.json)、[backfill-final.json](assets/retry01-mcp/backfill-final.json)、[backfill-final.png](assets/retry01-mcp/backfill-final.png)）：

- 弹窗文案：`本次只为 1 位已入库达人补采缺失资料，不会搜索或新增达人。是否继续？`
- 取消无请求，确认 1 次 POST；审计 `retry:backfill` 15:49:43。
- 运行中执行单元进入 `QUARANTINED / browser_stopped=false`，任务 `WAITING_FOR_RESOURCE: old browser requires isolation`；按 DIAG-02 恢复路径重启 Collection Worker（generation 7），15:54:01 自动回收 `RECOVERED_AFTER_UNCONFIRMED_EXIT`，任务自动续跑完成。
- 终态数据（before → final）：
  - `processed_operations 1→1`、`cursor` 不变 → **没有搜索批次**；
  - `basic` 模块观测 ID 变化（唯一失败模块），其余 **7 个模块观测 ID 全部不变**；
  - 两组精选因 `cover_failed` 仍 INCOMPLETE 而重读（F3）；
  - 快照 `2→3`（内容确有变化，新增 1 份；旧快照保留）；有效数 1→1；
  - 终态 `PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE`，按钮仍「补采缺失字段（1 位）」。

### 3.3 正常首次采集：创建与首次采集无回归

MCP 通过产品表单新建「宠物 / 1 位」任务 `8b0f0393`（[create.json](assets/retry01-mcp/create.json)、[create-after.png](assets/retry01-mcp/create-after.png)）：`RECEIVED→PARSING→QUEUED→COLLECTING→PARTIAL_COMPLETED`，有效 1/1、快照 1、导航 4、关联请求 68；页面按钮随后变为「补采缺失字段（1 位）」。终态为部分完成是 F3（封面存储不可达）导致，不是创建/采集回归。

### 3.4 接口负向：状态守卫真实生效

首次直连检查未带 `Idempotency-Key`，返回 422 只能证明请求头缺失（已在[前一份报告](RETRY-01-real-e2e-2026-10-24.md)中更正）。本轮 MCP 通过 `browser_evaluate` 带上 CSRF 与幂等键：

- 已完成 `666114c3` → **409**，`message = ACTION_NOT_ALLOWED`；
- 安全验证终态 `5542896c` → **409**，`message = ACTION_NOT_ALLOWED`。

---

## 4. 本轮复现/新增的问题

### F1（P1，未修复）：旧快照的首轮重发问题仍在
MCP 继续采集是「第二次及以后」的重试，因此表现为 `4→4`、`changed=0`；这正好证明 F1 是**首次**比较时 `content_id: null → "..."` 的一次性不一致。首次触发条件仍存在，修复方案不变（见 §5）。

### F2（P1，未修复）：搜索耗尽后仍永久推荐「继续采集」
MCP-05 复现：`search_exhausted=true`、`discovered=2/target=3`，继续采集完成后按钮仍为「继续采集（还差 1 位）」，关注区仍承诺“数量补足后单独补采”。

### F3（P1，环境+产品）：封面存储不可达导致补采无法收敛
两组精选均为 `cover_failed`；补采重读精选后再次失败，任务保持部分完成、按钮永久保留。MCP-08 复现。

### F5（P1，新发现，执行资源）：执行单元隔离后任务停摆，必须人工重启 Worker
- 现象：补采已受理并进入 `COLLECTING` 前，单元变为 `QUARANTINED / browser_stopped=false`，任务 `WAITING_FOR_RESOURCE: old browser requires isolation`，状态停留超过 2 分钟；`failure_counts` 累计 `RESOURCE_UNAVAILABLE: 2`。
- 现场：单元 `owner=NULL/lease=NULL`，SingletonLock 为 `longboliuMacBook-Air.local-20432`（该 PID 已不存在）；Worker 心跳仍在线（generation 6）。
- 恢复：重启 Collection Worker → 启动时隔离证明通过 → 15:54:01 自动回收为 `RECOVERED_AFTER_UNCONFIRMED_EXIT`，任务无需重新点击即自动续跑完成。
- 影响：任何任务都可能停在“等待执行资源”，页面没有可操作入口；媒介人员无法自助恢复，只能依赖运维重启 Worker。DIAG-02 的启动回收只在 Worker 启动时执行，**运行中不会自动回收**。
- 定位：与 RETRY-01 的重试逻辑无关（任务受理、取消、确认均正常），属执行单元/浏览器宿主释放路径的既有问题；触发时机与上一段继续采集后的浏览器释放未确认有关。
- 修复建议：
  - 运维最小方案：在任务详情/执行单元页出现 `old browser requires isolation` 时给出明确提示与恢复步骤；Worker 增加周期性（如每 60s）隔离单元回收，复用 `reconcile_quarantined_unit`，仍以隔离证明为前提；
  - 根因修复：排查 `BrowserHost` 在正常结束后为何留下 `browser_stopped=false`（释放未确认），修复释放路径；
  - 验收：恢复后任务可自动续跑（本轮已实证）。

### 其他观察
- 单元 `profile_ref` 仍指向旧 checkout（`/Users/yaoyao/Documents/...`），与当前配置路径不一致（DIAG-01 已记录的环境不一致），本轮未修改。
- MCP 服务 stdout/stderr 与 Chrome 崩溃日志显示外层沙箱限制；测试侧已用 `--no-sandbox` 解决，不影响产品结论。

---

## 5. 修复方案（在上一份报告基础上补充 F5）

| 缺陷 | 最小修复 | 影响范围 | 验证 |
|---|---|---|---|
| F1 | 快照序列化前解析卡片 `content_id`（`Repository.persist_creators`），使首份快照与 checkpoint 一致 | 单函数；无迁移 | 带精选卡片的无变化重试不新增快照；MCP 继续重试 `4→4` |
| F2 | `decide_retry_scope` 增加 `can_add_creators`：搜索耗尽且无可补候选时转 BACKFILL，并提示剩余无法补足 | `retry_policy` + 前端文案 | 383 类任务按钮变「补采缺失字段」；MCP-05 重跑 |
| F3 | 恢复/改指封面对象存储；产品侧对存储类失败停止推荐并提示 | 运行配置 + 只读判定 | 存储恢复后补采应 COMPLETED；不可达时按钮不再无限出现 |
| F5 | Worker 运行期周期性回收隔离单元（复用启动回收逻辑，仍以本地隔离证明为前提）；页面给出可操作提示 | `worker.py` / `browser_host` / 任务详情文案 | 模拟 `browser_stopped=false` 后无需重启即可恢复；或至少显示明确恢复入口 |

> F1/F2 修复后必须用 **Playwright MCP** 重跑 MCP-01—MCP-08，作为最终验收。

---

## 6. 未覆盖与限制

2. **100/99/80 规模**：真实数据未做；由隔离 PostgreSQL 集成测试覆盖（103 passed / 1 skipped）。
3. **“继续采集新增 1 位”**：当前任务搜索耗尽，MCP 只能验证“不重访”；新增 1 位的路径由集成测试覆盖。
4. **执行单元隔离**：F5 使补采在第一次 MCP 运行中停摆 2 分钟，恢复后完成；若要求无人值守验收，需先实现 F5 的周期回收。
5. **MCP 工具暴露**：DSH 会话未直接暴露 MCP 工具，本轮通过 stdio 启动同版本 MCP 服务；所有动作仍是 MCP `browser_*` 工具，可复跑脚本见 §7。

---

## 7. 复跑方式

```bash
# 需要本地全栈已启动，且 Playwright MCP 已安装
.venv/bin/python scripts/qa/retry01_mcp_acceptance.py preflight
.venv/bin/python scripts/qa/retry01_mcp_acceptance.py api
.venv/bin/python scripts/qa/retry01_mcp_acceptance.py continue
.venv/bin/python scripts/qa/retry01_mcp_acceptance.py backfill
.venv/bin/python scripts/qa/retry01_mcp_acceptance.py create
.venv/bin/python scripts/qa/retry01_mcp_acceptance.py status
```

输出：`.runtime/qa/retry01-mcp/*.json` 与 `docs/evidence/assets/retry01-mcp/*.png`。

---

## 8. 附件

- 截图（11 张）：`preflight-continue/backfill/completed/challenge/update`、`continue-before/after`、`backfill-before/after/final`、`create-after`
- JSON：`preflight.json`、`api.json`、`api-completed.json`、`api-challenge.json`、`continue.json`、`backfill.json`、`backfill-final.json`、`create.json`、`create-detail.json`、`detail-*.json`、`status-*.json`、`units-final.json`
- 审计：`383474a1` 的 `retry:continue`（15:48:57）；`2cf27cbe` 的 `retry:backfill`（15:49:43）
- Worker 恢复：`.runtime/logs/collection-worker.log` 15:54:01 `recovered quarantined unit ... after local isolation proof`
- 脚本：[retry01_mcp_acceptance.py](../../scripts/qa/retry01_mcp_acceptance.py)、[mcp_client.py](../../scripts/qa/mcp_client.py)
