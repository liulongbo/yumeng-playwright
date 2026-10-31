# KJX-01 阶段 B：磁力聚星产品业务闭环证据

验证日期：2026-10-28（Asia/Shanghai）  
验证范围：隔离 PostgreSQL 随机 Schema、Temporal 本地测试服务器、真实 FastAPI（TestClient 与回环 Uvicorn）、真实 Chromium、合成 LLM/Adapter/浏览器边界。  
明确未做：真实平台访问、正式业务库迁移或写入、生产 Feature Flag 启用、Windows 实机、超过 3 位的真实采集、Git 提交。

## 1. 结论

阶段 B 的“前端创建 → API → Intake → Temporal → ExecutionUnit/Worker → 聚星 Adapter → 持久化 → 任务中心 / 统一达人库 / 详情”产品链路，已在隔离环境通过。阶段 B 可判定为 GO（合成/隔离口径）；真实平台经 Temporal、Windows 与「母婴 / 母婴亲子 / 10 位」仍属阶段 C，本轮未验证。

| 能力 | 结论 | 证据 |
|---|---|---|
| 聚星达人库列表、平台筛选、详情 | PASS | 集成测试、Playwright、隔离全栈 UI |
| 任务中心/任务详情/任务内达人的平台化 | PASS | 组件测试、Playwright、隔离全栈 UI |
| 聚星任务 API → Intake → Temporal → Worker → DB → API | PASS（合成浏览器边界） | `tests/e2e/test_juxing_temporal_e2e.py` |
| 数据隔离、真实 0 值 vs 未采集、快照/投影 | PASS | `backend/tests/integration/test_juxing_creator_library.py`、`test_juxing_persistence.py` |
| 星图既有行为 | PASS（自动回归） | 单元/合同/集成/前端全套；真实星图回归属阶段 C |
| 真实聚星 Temporal 全链路 | PARTIAL / 阶段 C | 本轮使用假 BrowserHost + 合成 Adapter，不启动 Chrome/Profile |
| Windows 实机、10 位真实验收 | BLOCKED / 未授权 | 沿用任务卡边界 |

## 2. 本轮定位并修复的阻塞缺陷

1. **`requirements.schema_version` 未允许 `requirement_form.v3`**：迁移 013 只放开 v1/v2，迁移 020 未同步，导致隔离库迁移后经 FastAPI 创建聚星任务直接 `CheckViolation`（此前 1 位冒烟绕过 API，故未暴露）。经用户授权，仅在未应用的 `migrations/020_multi_platform_juxing.sql` 中重建该约束为 v1/v2/v3；不新增表/列，不触正式库。
2. **Intake 把星图字段清单套到聚星**：`IntakeProcessor` 原对任何平台都传递星图 `profile_requirements.json`，聚星任务会因缺少 `commercial/fans/creation...` 永远 `PARTIAL_COMPLETED`。现按 `requirement_form.platform` 选择：星图保持原清单，聚星 P0 由自身 verified registry 四模块决定完整性；可显式注入平台清单。新增单元回归。
3. **聚星完成判定/任务展示的星图语义泄漏**：前端任务详情固定显示“精选完整 / F06 双集合”、任务内达人固定显示 CPM/CPE 与深用户；现按平台切换计数卡、状态文案、指标组与章节，聚星不显示 F06/精选。

## 3. 实现摘要

### 3.1 后端统一达人库读模型（无 Schema 变更）

- `ProductQueries.list_creator_library(platform=...)`：星图分支保持原 SQL；聚星分支以 `platform_creators.projection` + 最近一条 `creator_snapshots` 读取，支持省/市/粉丝区间/仅看完整与 `updated_at|followers` 排序；星图专属筛选显式 `KUAISHOU_JUXING_LIBRARY_FILTER_UNSUPPORTED`。
- `get_creator_library`：按 `platform_creators.platform` 分流；聚星返回 `profile_payload`、`module_statuses`、`field_sources`、收集/失败计数、最近快照标识；无快照返回 `CREATOR_NOT_FOUND`，不伪造投影。
- 聚星专属字段不与星图字段强行等同：列表仅映射昵称/头像/地区/内容类型/粉丝/月涨粉率/完整性/更新时间；CPM、深用户、互动等星图语义字段保持空 metric。
- `CreatorSummary.platform` 随任务结果返回；`content_theme_labels` 上移到 summary（详情形状不变）。
- 聚星不适用子资源显式失败：报价/历史/作品观测/精选集合 → `KUAISHOU_JUXING_LIBRARY_<SCOPE>_NOT_APPLICABLE`；手动更新 → `KUAISHOU_JUXING_UPDATE_NOT_SUPPORTED`。
- 字段目录端点改为 `/api/platforms/{platform}/profile-field-catalog`，星图旧 URL 仍可用。

### 3.2 前端平台化

- 达人库：平台切换（巨量星图/磁力聚星）、平台专属筛选隐藏与 URL 清理、平台徽标、聚星行指标（粉丝/月涨粉率/完整性）、空状态说明。
- 聚星达人详情：`快手ID`、粉丝/近30天涨粉/月涨粉率/作品数、内容类型；章节为 `基础资料 / 传播表现 / 代表作品 / 受众画像`；报价展示平台原值与“整数÷1000=元”；作品只展示文本与计数；画像展示平台原始结构与统计窗口；不请求星图 F06/作品观测/报价/更新端点。
- 任务中心：聚星不显示“精选”计数；任务详情隐藏“精选完整/F06 双集合”，状态文案按平台（磁力聚星/星图）；任务内达人按平台选择指标组。
- 字段目录按平台加载，星图原有渲染与用例保持不变。

### 3.3 隔离 E2E

- `tests/e2e/test_juxing_temporal_e2e.py`：真实 FastAPI + 真实 PostgreSQL + 真实 Temporal 测试服务器 + 真实 `Activities.collect`；合成 LLM 计划、假 BrowserHost（保留真实租约/会话表流程）与合成聚星 Adapter。断言平台/合同/账号/Profile/Adapter 选择、四模块完成、`COMPLETED`、计数、快照、星图投影为 0、API 与达人库回读、跨平台隔离、Flag 关闭拒绝。
- `tests/e2e/test_juxing_frontend.py`：真实 Chromium + 路由拦截，验证聚星库/详情/任务/任务内达人；同时断言不请求星图专属子资源。
- `tests/e2e/test_juxing_frontend_fullstack.py`：真实 Uvicorn API（回环） + 随机隔离 Schema + 真实登录 + 真实 Vite + Chromium，验证聚星库/详情/任务/任务内达人读取真实数据库；结束后删除 Schema。

## 4. 测试结果

环境：macOS；隔离 PostgreSQL `xingtu_test_m3`（127.0.0.1:55439，随机 Schema）；Temporal CLI 1.9.1（`.runtime/local-main/bin/temporal`）；Chromium（`PLAYWRIGHT_BROWSERS_PATH=.runtime/browsers`）；隔离 API `127.0.0.1:4181` + Vite `127.0.0.1:4180`。

| 层级 | 命令 | 结果 |
|---|---|---|
| 后端单元 + 合同 | `pytest backend/tests/unit backend/tests/contract -q` | 384 passed |
| PostgreSQL 集成 | `pytest backend/tests/integration -q -rs` | 113 passed / 1 skipped（MinIO S3 环境未配置） |
| Temporal 隔离全链路 | `pytest tests/e2e/test_juxing_temporal_e2e.py -q` | 2 passed |
| 前端组件 | `npm --prefix frontend test` | 98 passed |
| 前端类型/构建 | `npm --prefix frontend run lint` / `run build` | PASS |
| Playwright 产品页 | `pytest tests/e2e/test_juxing_frontend.py -q` | 2 passed |
| Playwright 隔离全栈 | `pytest tests/e2e/test_juxing_frontend_fullstack.py -q` | 1 passed |
| 既有 Temporal E2E | `pytest tests/e2e/test_temporal.py -q` | 5 passed |
| 全量 E2E | `pytest tests/e2e -q` | 14 passed |
| 静态检查 | Ruff（本卡范围）、Ruff format（本卡范围）、Mypy strict、`git diff --check` | PASS |

`make check` 仍被 `scripts/acceptance/` 既有 11 个 `UP031` 阻断（与交接记录一致，本轮未修改验收脚本）。

## 5. 证据路径

- 后端测试输出：本轮命令输出保存在会话记录；关键新增用例：
  - [test_juxing_temporal_e2e.py](../../tests/e2e/test_juxing_temporal_e2e.py)
  - [test_juxing_creator_library.py](../../backend/tests/integration/test_juxing_creator_library.py)
  - [test_juxing_frontend.py](../../tests/e2e/test_juxing_frontend.py)
  - [test_juxing_frontend_fullstack.py](../../tests/e2e/test_juxing_frontend_fullstack.py)
- UI 截图（本机私有，不入 Git）：
  - `.runtime/test-artifacts/kjx-stage-b/juxing-library-list.png`
  - `.runtime/test-artifacts/kjx-stage-b/juxing-library-detail-basic.png`
  - `.runtime/test-artifacts/kjx-stage-b/juxing-library-detail-chapters.png`
  - `.runtime/test-artifacts/kjx-stage-b/juxing-task-detail.png`
  - `.runtime/test-artifacts/kjx-stage-b/juxing-task-creator-detail.png`
  - `.runtime/test-artifacts/kjx-stage-b/fullstack-juxing-library.png`
  - `.runtime/test-artifacts/kjx-stage-b/fullstack-juxing-library-detail.png`
  - `.runtime/test-artifacts/kjx-stage-b/fullstack-juxing-task-creator.png`
- 阶段 B 真实 1 位样本证据仍为：[KJX-01-stage-b-live-sample-2026-10-27.md](KJX-01-stage-b-live-sample-2026-10-27.md)。

## 6. 尚未验证 / 阶段 C 前置

1. **真实浏览器边界**：本轮 Temporal E2E 用假 BrowserHost + 合成 Adapter，未证明真 Chrome、聚星 Profile、账号校验在 Temporal Worker 内工作；需阶段 C 在授权环境执行。
2. **真实 DeepSeek 调用**：E2E 使用确定性计划 + 合成 LLM，未产生付费调用；真实模型 + Temporal 组合属阶段 C。
3. **Windows 实机**：路径、ACL、锁、Chrome/Profile 仍未验证。
4. **「母婴 / 母婴亲子 / 10 位」**：未授权，未执行；服务端仍硬限制 3 位，需另行授权并评估分页合同。
5. **真实星图回归**：自动回归通过；真实星图采集回归属阶段 C。
6. **聚星历史/性能**：聚星未建 current/snapshot-index 表；列表使用 `creator_snapshots` 的侧向最近快照连接，当前数据量下通过，若阶段 C 数据量增大需评估索引（Schema 变更需单独授权）。
