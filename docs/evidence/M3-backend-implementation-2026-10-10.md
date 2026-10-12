# M3 后端实现与回归证据（2026-10-10）

> 范围：APP-01、INTAKE-01、CONSOLE-01 的后端、数据库、异步编排与测试实现。  
> 明确不包含：React 产品页面、真实 DeepSeek 调用、真实巨量星图新任务。本文不把 Mock、合成浏览器或本地依赖服务写成真实平台验收。
> 同日后续已完成 React 产品页面及合成 API 浏览器 E2E，见 [M3 产品前端证据](M3-product-frontend-2026-10-10.md)；本文保留后端阶段的原始验证边界。

## 1. 本轮实现

- 新增 FastAPI 产品 API：产品登录/退出/会话、能力查询、可靠任务提交、任务列表/详情/操作、任务内达人/作品及受保护封面。
- 新增 Argon2id 产品密码、服务端会话、令牌哈希、空闲/绝对过期、Origin + CSRF、Redis 登录双维度限流和用户审计。
- 新增 `RequirementForm v1`、产品任务事务、`intake_dispatches`、`model_runs` 及提交/操作幂等。
- 新增 LangGraph `StateGraph` P1：加载上下文、无损标准化、确定性约束、候选生成、Pydantic 校验、业务校验、最多三次有界修复及结构化失败。
- 新增 DeepSeek Responses API Adapter；业务层只依赖 `LLMAdapter`，真实 Worker 启动前校验配置模型。
- 新增 Temporal Intake Workflow/Worker；P1 成功后在同一个 `root_task_id` 上原子创建现有 P2-1 结构，P1 失败不申请浏览器单元。
- 新增任务产品投影：稳定游标、阶段/四类计数、`allowed_actions`、409 当前版本、草稿/发布快照区分、F06 两组集合独立分页及任务范围校验。
- 新增迁移 `008_m3_product_app.sql`，采用追加/可空兼容；保留内部 CLI、`internal_acceptance` 计划、旧任务和不可变快照。

关键实现入口：

- `backend/src/xingtu/product_api.py`
- `backend/src/xingtu/product_auth.py`
- `backend/src/xingtu/product_repository.py`
- `backend/src/xingtu/product_queries.py`
- `backend/src/xingtu/intake.py`
- `backend/src/xingtu/intake_workflow.py`
- `backend/src/xingtu/intake_worker.py`
- `migrations/008_m3_product_app.sql`
- `docs/decisions/DEC-014-m3-product-application-and-intake.md`

## 2. 验证结果

| 层级 | 命令/环境 | 结果 | 证据边界 |
|---|---|---|---|
| 静态与单元 | `make check` | Ruff、format-check、mypy strict 通过；155 passed | 纯逻辑/合成输入 |
| PostgreSQL Integration | `pytest backend/tests/integration -q`，本机隔离 `xingtu_test` | 64 passed、1 skipped、1 failed；失败为既有首个 Engine 用例在整套慢速运行中租约超过 120 秒 | M3 新增 9 个集成用例全部通过；未把该次整套运行写成全绿 |
| 租约失败复核 | 单独复跑 `test_order_dedup_invalid_topup_and_snapshots` | 1 passed in 0.88s | 证明是整套耗时相关波动；租约时长问题仍应在后续测试基座中治理，未修改 F04/F05 规则 |
| Temporal E2E | `PYTHONPATH=. pytest tests/e2e/test_temporal.py -q` | 5 passed | 本地 Temporal 测试服务；合成 Adapter |
| Browser Contract | `pytest backend/tests/contract -q`，Chromium + 合成路由 | 28 passed | 不访问真实星图 |
| MinIO 专项 | `pytest backend/tests/integration/test_s3_covers.py -q`，本机隔离 MinIO | 1 passed | 验证桶创建、写后读回、校验与清理；不是生产对象存储 |

新增 M3 测试重点覆盖：

- 登录错误统一、会话过期/撤销、CSRF、Origin、限流失败关闭。
- 目标数和业务条件校验；同键同内容复用、同键异内容冲突、事务回滚。
- P1 合法输出、漏/改字段拒绝、最多三次、失败无 P2、失败后新重试周期。
- 同根任务 P1→P2 只晋级一次，取消后的 Intake 不调用模型、不申请浏览器。
- 两用户共享读取、审计身份区分、操作版本冲突返回当前版本/合法操作。
- 运行中草稿、终态不可变快照、两组精选集合顺序/分页/游标范围、跨任务拒绝。

## 3. 未完成与阻塞

1. **产品前端阻塞已在同日后续解除。** 用户提供本地 Lazyweb skill 仓库后，已完成检索、参考集定稿、`frontend/` 产品页面和 Chromium 合成 API E2E；详细证据另见前端证据文档。
2. **真实 DeepSeek 未验证。** 当前环境没有 `DEEPSEEK_API_KEY`，未执行 `/models` 或 Responses JSON Schema 小样本。Mock 结果只证明工作流、Adapter 契约和确定性门槛。
3. **真实星图 M3 闭环未执行。** 本轮没有提交真实关键词任务；F04 的既有能力边界保持不变。
4. **整套 PostgreSQL 集成单次非全绿。** 65 个非跳过用例中仅既有租约用例因整套运行超过租约而失败，隔离复跑通过；这不能表述为“全量 Integration 通过”。
5. **生产参数未验收。** 正式 HTTPS 域名、`XINGTU_ALLOWED_ORIGINS`、Secure Cookie、初始用户清单、DeepSeek 配额/数据安排仍需部署前提供。

## 4. 结论

M3 的后端产品契约、认证、可靠提交、P1 有界转换、同根任务晋级、任务/结果查询和操作能力已形成可测试实现，且没有修改 F04/F05/F06 的 Adapter、Parser 或 Engine 业务逻辑。同日前端阻塞已解除，APP-01、INTAKE-01、CONSOLE-01 转为“进行中/未验收”。真实 DeepSeek、小样本真实星图和生产配置仍未验收，不能据本证据标记里程碑完成。
