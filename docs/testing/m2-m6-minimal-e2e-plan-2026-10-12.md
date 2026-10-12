# M2–M6 最小真实端到端回归 — 测试计划（待费用与范围确认）

状态：**待用户确认费用上限与采集范围后执行**（未执行）
创建时间：2026-10-12T15:40:00+08:00
授权依据：用户 2026-10-12「M2–M6：有条件授权…在我确认费用上限与采集范围后再执行真实任务」
关联：`docs/testing/regression-f04-m3-2026-10-12.md`（档位 A 已执行：M0/M1/F1 PASS）

> 本文件是**计划**。所有真实动作在用户确认下方 §7 的预算与范围之前**不会执行**。

---

## 1. 目标链路

```
MCP 前端登录 → 创建任务 → DeepSeek P1 转换 → 持久派发
→ 巨量星图采集（F04 发现 + F05 详情 + F06 精选/封面）
→ PostgreSQL 落库 → 前端结果展示
```

## 2. 测试对象与参数

| 项 | 取值 | 依据 |
|---|---|---|
| 测试账号 | `media-a`（真实产品用户，已确认可登录） | 档位 A M1 已用该账号登录成功 |
| 关键词 | **宠物** | 项目历史已验证关键词（`7620fb83`/`02c81708` 均为「宠物」） |
| 筛选条件 | 仅 `keyword:eq`（**契约当前唯一已登记能力**） | `capabilities.fields` |
| 排序 | `score`（契约 `sorts`） | `capabilities.sorts` |
| 目标达人数量 | **1** | 最小规模；与已验证任务 `7620fb83`(1/1) 可比 |
| 预计创建任务数 | **1 个根任务**（不重复提交） | 用户要求"预计创建的任务数量" |
| 采集规模 | 1 位有效达人 × (8 个资料模块 + 2 组精选集合)；历史实测约 **45 请求 / 45 响应** | FIX-01 证据 `7620fb83` |

> 如你希望改为 **2**（与 `acd929aa` 可比）或 **5**（与 F04 档位 B 一致），请在确认时说明；
> 数量增加会线性增加星图请求量、Argon2 无关但会增加 **DeepSeek 仅 1 次**（P1 只跑一次）。

## 3. 费用估算与上限

### DeepSeek（**唯一付费项**）

P1 只调用**一次** `/responses`（失败时最多重试至 `max_attempts=3`，见 §5）。

| 项 | 历史实测值（证据来源） | 估算 |
|---|---|---|
| 输入 tokens | 1126（`M3-intake-worker-fix-2026-10-11.md` 真实 `model_runs`） | ≤ 2000 |
| 输出 tokens | 88（同上） | ≤ 400 |
| 模型 | `deepseek-flash`（`GET /models` 已核可用） | — |
| 单次成功调用成本 | **约 ¥0.01 量级**（按 flash 档公开单价折算，非账户实价） | — |

**建议费用上限（请你核定）**：

| 项 | 建议上限 |
|---|---|
| 模型调用次数 | **≤ 3 次**（1 次正常 + 最多 2 次修复重试，由既有 `max_attempts=3` 约束） |
| 总输入 tokens | **≤ 6000** |
| 总输出 tokens | **≤ 1200** |
| **金额上限** | **≤ ¥0.10**（远低于按量计费风险阈值；若你的账户单价不同请直接改写此值） |

> **停止条件**：任一次调用后累计 tokens 超过上表 → **立即停止并报告**，不再重试。

其他外部服务（`GET /models`、Temporal、PostgreSQL、MinIO 本地）**无费用**。

## 4. 外部写入与副作用

| 目标 | 写入内容 | 可逆性 |
|---|---|---|
| **PostgreSQL `xingtu_development`**（本地开发库 `127.0.0.1:55432`） | `root_tasks`、`requirements`、`intake_dispatches`、`model_runs`、`filter_plans`、`task_dispatches`、`tasks`、`creator_snapshots`、`task_creators`、`featured_collections`、`featured_cards`、`collection_observations`、`media_objects`、`audit_logs` | 追加式，**不修改既有行**；已发布快照受 DB 触发器保护不可变 |
| **巨量星图（真实平台）** | 仅**读取**类请求（搜索/主页/精选/封面下载）；**不产生任何平台侧写入** | 不可逆的是"访问行为本身"（可能计入平台风控观测） |
| **DeepSeek** | 1 次 `/responses`（付费） | 不可逆 |
| **本地** | `.runtime/` 下证据、日志、封面对象（MinIO/本地目录） | 可清理 |
| **生产数据** | **不触碰** | — |
| **契约文件** | **不修改** | 用户明确"暂不允许修改 `page_fetch_max_verified`" |

**重试策略（硬约束）**：
- P1 修复重试：由既有 `max_attempts=3` 约束，**不额外增加**
- 采集层：不手工重试；若收口为 `PARTIAL_COMPLETED`，**如实记录**，是否 `retry` 由你另行决定
- **禁止无限重试**；任何阶段连续 2 次同类失败 → 停止并报告

## 5. 每阶段通过标准与失败停止条件

| 阶段 | 动作 | 通过标准（三方证据） | 失败停止条件 |
|---|---|---|---|
| **M2** 创建 | MCP 在 `/tasks/new` 填关键词「宠物」+ 目标 1 → 提交 | API `202` 且返回 `root_task_id`；DB 出现 `root_tasks(state=RECEIVED)` + `requirements` + `intake_dispatches(sent=false)` | 提交 4xx/5xx；或 DB 无对应行 → **停止** |
| **M3-a** P1 | 等待 intake worker 消费 | DB：`intake_dispatches.sent=true`；`model_runs` 有 `provider/requested_model/input_tokens/output_tokens/latency_ms`；`filter_plans(source='model')` 新增 1 行；任务进入 `PARSING → QUEUED` | 累计模型调用 > 3 次，或 tokens 超上限，或任务停留 `PARSING` > 5 分钟 → **停止** |
| **M3-b** 采集 | collection worker 消费（已运行） | DB：`task_dispatches.workflow_started_at` 非空；Temporal 有 `collect/<root>` workflow；任务进入 `COLLECTING` | 队列无新鲜消费者，或任务停留 `RECEIVED`/`QUEUED` > 10 分钟 → **停止并报告** |
| **M5** 终态 | 不干预，观察 | DB：终态为 `COMPLETED`；`profile_complete_count=1`；8 模块全 `COLLECTED`；`failure_reason=null` | 收口 `PARTIAL_COMPLETED`/`FAILED` → **不重试**，如实记录并报告 |
| **M6** 展示 | MCP 打开任务详情 | UI 渲染达人列表/详情/两组精选/封面；API `/creators`、`/contents`、`/covers/...` 与 **DB 计数三者一致** | 三方任一处不一致，或封面 404/403 → **记录为缺陷**（不阻断其它证据） |
| **M4** 编排 | Temporal + 日志 | `check_queues` 双队列 `alive=True`；worker 日志含 `dispatched N intake task(s)`（脱敏） | 派发失败审计持续增长 → **停止** |

**会话前提**：采集单元当前 `state=READY`、`verified_account_id=NULL` → 首次采集可能要求
**人工**在可见 Chrome 完成账号/会话验证。此时任务应如实进入 `WAITING_FOR_LOGIN`（或
`WAITING_FOR_VERIFICATION`），**需人工配合**；**不注入 Cookie、不绕过验证**。

## 6. 分阶段执行与人工配合点

| 阶段 | 自动化 | 需人工配合 |
|---|---|---|
| M2 创建 | ✅ MCP 全自动 | — |
| M3-a P1 | ✅ 自动（等待 + DB 轮询） | 若模型输出被拒 3 次 → 需人工判断是否终止 |
| M3-b/M5 采集 | ✅ 自动观察 | **若触发登录/安全验证** → 人工在可见 Chrome 处理 |
| M6 展示 | ✅ MCP + API + DB | — |

## 7. 待你确认（确认后我才执行）

1. **目标达人数量**：1（建议，最小）／2／5？
2. **费用上限**：是否接受 §3 的「≤3 次调用 / ≤6000 输入 tokens / ≤¥0.10」？
3. **是否允许在触发登录或安全验证时由你人工介入**（否则该情形只能收口为 `PARTIAL_COMPLETED`）？
4. **是否允许采集过程中出现 `PARTIAL_COMPLETED` 时保持不重试**（建议：允许，如实记录）？

## 8. 不执行的项

- 不修改契约（含 `page_fetch_max_verified`）
- 不修改生产数据
- 不新增业务代码
- 不扩大采集范围（不加关键词、不加筛选、不重复提交）
- 不做无限重试
