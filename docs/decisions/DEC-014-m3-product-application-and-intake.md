# DEC-014：M3 产品应用、可靠受理与 P1 状态图

- 日期：2026-10-09
- 状态：已采纳，实施中

## 问题

现有系统从合法 `FilterPlan` 和指定执行单元开始，仅提供内部 CLI。产品任务需要在 P1
转换前取得稳定根任务 ID、保存原始需求、通过模型和确定性校验，再把同一根任务交给现有
F04/F05/F06。现有 `root_tasks.unit_id NOT NULL`、`filter_plans.source` 约束和 P2
`TaskRecord` 载荷无法表示该前置阶段。

## 决策

1. 新增 FastAPI 产品边界与 React 客户端；业务 API 使用独立产品用户和服务端会话，不复用
   巨量星图账号、浏览器 Profile 或 Cookie。
2. 使用 Argon2id 密码哈希；Cookie 中保存高熵原始会话令牌，PostgreSQL 只保存 SHA-256
   摘要；写请求同时校验同源 `Origin` 和会话绑定 CSRF 令牌。
3. 登录限流使用 Redis 的账号 HMAC 与 IP 两个桶；Redis 不可用时登录失败关闭，不能绕过。
4. 新增 `requirements`、`intake_dispatches`、`model_runs`，并把 `root_tasks.unit_id` 改为可空。
   产品提交在一个事务中写 requirement、root、P1 task/checkpoint、dispatch 与幂等响应。
5. P1 使用 LangGraph `StateGraph` 表达显式节点和条件边；模型仅生成候选 JSON，Pydantic
   与确定性字段对照拥有最终决定权。总模型调用预算为三次，不启用 Agent、工具调用、RAG、
   多模型或 LangGraph 独立 Checkpointer。
6. DeepSeek 通过独立 `LLMAdapter` 接入 Responses JSON Schema；Prompt、请求模型、响应模型、
   用量、耗时、输出或错误逐次记录。供应商凭据、平台响应和 Cookie 永不进入 Prompt 或日志。
7. P1 成功后在原 `root_task_id` 上原子替换为现有 P2 `TaskRecord` 载荷，创建 P2 task、attempt、
   checkpoint 与 `task_dispatches`。现有 `Repository.create` 和内部 CLI 保持原行为。
8. 产品查询读取 PostgreSQL 投影；Redis 不是任务事实源。历史无 requirement 的任务以系统任务
   兼容展示，不伪造表单。

## 兼容性与回滚

- 迁移 008 采用新增表、可空列和放宽枚举约束，不修改既有快照、候选或集合表。
- P1 未成功前不写 `task_dispatches`，旧 Collection Worker 不会误读产品 Intake 载荷。
- 旧代码回滚时停止新受理并保留新增表；已转换为 P2 的任务仍是原 `TaskRecord` 格式。
- 不提供破坏性 down migration。迁移后必须验证内部 CLI 创建、旧任务读取和 Workflow replay。

## 被否决的替代方案

- API 直接调用 `Repository.create`：会丢失原始需求与模型追溯，且无法在分配执行单元前返回
  同一根任务。
- FastAPI 内存后台任务：进程退出会丢失受理意图。
- 为 P1 和 P2 创建两个根任务：破坏用户看到的统一任务身份与幂等语义。
- 让模型输出直接进入 F04：无法阻止漏字段、加条件或修改用户值。
- 引入 ORM 或 LangGraph Checkpointer：会与当前 psycopg 仓储、Temporal 和 task_checkpoints
  形成第二套事实源。

## 验证要求

- 迁移、旧数据兼容与事务回滚集成测试。
- Auth/Cookie/CSRF/限流与会话生命周期集成测试。
- P1 节点、条件边、三次上限和恶意候选确定性拒绝测试。
- 同键同内容、同键异内容、并发提交、P1→P2 单派发测试。
- 现有 F04/F05/F06 单元、Browser Contract、PostgreSQL、Temporal 与 MinIO 回归。
