# FILTER-01 验收记录（脱敏）

日期：2026-10-15  
执行单元：`unit-local-mac-02`  
能力版本：`xingtu-ad-creator-square-v2`

本记录不包含 Cookie、令牌、请求头、完整响应或个人信息。截图存放于受限运行目录 `.runtime/test-artifacts/FILTER-01/`，不纳入 Git。

## 自动化回归

| 编号 | 范围 | 实际 | 结果 |
|---|---|---|---|
| AT-01 | 后端单元 | `pytest backend/tests/unit -q`：213 passed | PASS |
| AT-02 | FILTER-01 浏览器契约 | 筛选控件、画像选择、请求观察：21 passed | PASS |
| AT-03 | 产品 M3 集成 | `pytest backend/tests/integration/test_product_m3.py -q`：17 passed | PASS |
| AT-04 | 前端 | 61 tests passed；生产构建通过 | PASS |
| AT-05 | 静态检查 | Ruff check、Ruff format check、mypy `backend/src` 均通过 | PASS |
| AT-06 | 全量集成入口 | 未提供 `XINGTU_TEST_DATABASE_URL`，80 项在 fixture 初始化阶段拒绝运行、3 项通过；非断言失败 | BLOCKED |
| AT-07 | `make check` | FILTER-01 相关检查通过；被工作区既有 `scripts/acceptance/run_cd02_acceptance.py:252` 的 F841 阻断 | BLOCKED |

## 真实 Chrome 最小用例

| 编号 | 步骤/条件 | 预期 | 实际 | 结果 |
|---|---|---|---|---|
| LT-01 | Keyword-only：`汽车`，目标 1–2 | 一条最终相关请求，页面回显搜索词 | 20 候选；最终窗口 1 request/1 response | PASS |
| LT-02 | 性别、北京整省、硕士、科技黄 V | 背景四项映射到最终请求 | 与 Keyword、连接、粉丝量级及画像共同出现；同名 `persona_tag_level_one` 多重集匹配 | PASS |
| LT-03 | 北京市/朝阳区 | 二级地域写入 `city` | 请求为 `city=["朝阳区"]`；20 候选 | PASS |
| LT-04 | 连接、了解、兴趣、喜欢、追随五个区间（含 0–100w） | 十个上下界均关联 | 十项均在最终请求，1 request/1 response | PASS |
| LT-05 | 粉丝量级预设及自定义 12.5–25.5w | 预设/自定义换算并提交 | 两种路径均通过 | PASS |
| LT-06 | 观众画像五维 | 多选与性别阈值写入 watcher 字段 | 最终请求与回显一致，1 request/1 response | PASS |
| LT-07 | 粉丝画像五维 | 多选与性别阈值写入 fans 字段 | 最终请求与回显一致，1 request/1 response | PASS |
| LT-08 | 先观众后粉丝、先粉丝后观众 | 两类画像互斥 | 最终请求仅保留后选画像 | PASS |
| LT-09 | Keyword + 背景四项 + 连接 + 粉丝量级 + 一种画像 | 全部条件可共存 | 页面回显和最终请求均包含计划条件；筛选结果 0 位达人 | PASS |
| LT-10 | 从星采创建任务：`汽车` + 北京/朝阳区，目标 1 | 任务完成、JSONB 入库、结果展示 | 筛选/M3/候选和资料快照均已写入；任务终态为 `PARTIAL_COMPLETED` | PARTIAL |
| LT-11 | 对 LT-10 的“重试失败步骤” | 已有完整资料时完成 | 再次采集后仍为 `PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE` | BLOCKED |
| LT-12 | 人为控件/选项漂移 | 返回 `PLATFORM_PAGE_CHANGED`，不静默降级 | Adapter 契约测试覆盖并通过 | PASS |

## LT-10/LT-11 脱敏持久化证据

- `requirement_form.v2`、`filter_plan.v2` 和能力版本 `xingtu-ad-creator-square-v2` 已持久化；计划字段为 `keyword`、`region`。
- 模型记录：`m3-filter-plan-v2`，执行成功；检查点为 `browser-v9` / `xingtu-ad-creator-featured-v10`。
- 重试后最终检查点：62 observed requests、62 observed responses、0 duplicate requests、20 candidates、1 valid creator。
- 已有三份资料快照。根任务的 `profile_complete_count=0` 是既有资料范围判定所致：`seeding` 6 项与 `conversion` 9 项为 `MODULE_TIMEOUT`，`fulfillment` 3 项为 `MISSING_SOURCE`、1 项为 `MODULE_TIMEOUT`；状态机因此维持 `PROFILE_SCOPE_INCOMPLETE`。该问题发生在筛选已完成之后，重试未改变结果。
- UI 验收截图：`FILTER-01-E2E-task.png`、`FILTER-01-E2E-creator.png`。任务页显示 v2 能力与部分完成状态，达人页显示已入库资料。

## 结论

FILTER-01 的新增筛选功能、计划生成、请求相关性和真实页面执行均通过。用户已确认本卡仅验收新增背景信息与受众画像筛选；既有主页资料范围导致的 `PROFILE_SCOPE_INCOMPLETE` 保留为独立后续项，不阻断 FILTER-01 完成。
