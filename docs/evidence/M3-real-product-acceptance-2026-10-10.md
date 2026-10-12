# M3 真实 DeepSeek 与产品闭环验收证据（2026-10-10）

> 范围：INTAKE-01 真实 DeepSeek/P1，CONSOLE-01 真实产品任务、星图小样本、两媒介共享读取与任务内结果，以及 M3 全量回归。
> 边界：本轮是 localhost 开发环境，不是生产 HTTPS 验收；凭据与密码未写入仓库、证据或日志。

## 1. 环境与预检

| 项目 | 结果 |
|---|---|
| PostgreSQL | `127.0.0.1:55432 / xingtu_development`，PostgreSQL 18.3，迁移 1—8 已存在 |
| 隔离测试库 | 同一实例新建 `xingtu_test_m3`，用于可删除 Schema 的集成测试，不在开发库运行测试夹具 |
| Redis | `PONG` |
| Temporal | `127.0.0.1:57233` 可连接 |
| 执行单元 | `unit-local-mac-02`，`READY`，`local_development`，启动前无租约占用 |
| 产品用户 | `media-a` / `media-b` 均为 active；文档不记录密码 |
| live capabilities | `xingtu-ad-creator-square-v1`，只允许 `keyword:eq`，唯一组合为 `[keyword]` |

数据库已有迁移 008，本轮未重复应用。开始和结束时执行单元均为 `READY`、无 owner/租约、`browser_stopped=true`。

## 2. 真实 DeepSeek 验收

1. `GET /models` 验证配置模型可用，`deepseek-flash` 通过。
2. 使用脱敏最小表单（内容关键词“游戏剧情”、目标 2）执行 Responses JSON Schema 调用。
3. 返回模型为 `deepseek-flash`，用量为 1128 input tokens / 89 output tokens。
4. 返回 `FilterPlan v1`与确定性期望完全一致：关键词没有改写，目标仍为 2，能力版本一致，固定排序映射为 `score`，没有新增条件。
5. 产品任务的 `model_runs` 持久记录：1 次尝试、`succeeded/received`、Prompt `m3-filter-plan-v1`、耗时 1111 ms、同样的 1128/89 token 用量。

API key 只通过临时进程环境使用，未写入数据库、任务卡、本证据或仓库文件；验收结束后已清除相关进程环境和临时会话文件。

## 3. 真实产品任务

| 字段 | 值 |
|---|---|
| 根任务 | `f47eb1cf-f038-4f9f-ae3d-e02aa8a995d3` |
| 提交用户 | `media-a` |
| 原始需求 | 内容关键词“游戏剧情”，目标 2 |
| 能力版本 | `xingtu-ad-creator-square-v1` |
| 状态序列 | `RECEIVED → PARSING → QUEUED → COLLECTING → PARTIAL_COMPLETED` |
| 最终计数 | discovered=20, valid=2, profile_complete=0, featured_complete=2, failed=0 |
| 最终原因 | `PROFILE_SCOPE_INCOMPLETE` |

事实链路核对：

- 1 requirement、1 intake dispatch、1 model run、1 model FilterPlan、1 collection dispatch、1 task attempt。
- 同一 `Idempotency-Key` 重提返回同一 `root_task_id`；数据库仍只有一份 requirement/派发/模型运行。
- 同一根任务下有 P1、P2-1、search 和 profile 任务，没有创建第二个业务根任务。
- 20 位候选中有 5 次 `PLATFORM_SECURITY_CHALLENGE`，现有维护恢复链处理后继续，最终达到 2 位有效达人。
- 2 位达人均有任务关联发布快照。最新快照的 `basic/commercial/conversion/creation/fulfillment/seeding/spread` 模块均为 `COLLECTED`；`fans` 一位 `COLLECTED`、一位因 `RESPONSE_SCHEMA_MISMATCH` 为 `FAILED`，因此根任务如实收口为部分完成。
- 两位达人共有 `excellent_reach` 8 张卡片、`excellent_seeding` 6 张卡片，14/14 封面为 `STORED`。

这一结果证明 M3 产品闭环会保留 F04/F05/F06 真实部分完成语义，不会因达到有效数而伪报 `COMPLETED`。

## 4. 产品 API 与真实 Chromium

已验证：

- `media-a` 登录、创建任务、轮询到终态、读取 2 位发布快照。
- 同 key 重复提交返回原根任务。
- 第一位达人两组精选各 4 张，集合状态均为 `COMPLETE`，8 张均有真实链接和 `STORED` 封面。
- 认证封面返回 HTTP 200/45018 bytes；替换根任务后返回 404。
- `media-b` 能读取同一任务和 2 位达人，与 `media-a` 是不同用户 ID。
- `media-a` 退出返回 204，旧 Cookie 访问任务返回 401；重新登录后恢复该任务的 `PARTIAL_COMPLETED / 2 / 2`。
- 真实 Chromium 从受保护任务 URL 登录回跳，查看“游戏剧情”任务、2 位达人、不可变快照和优秀传播集合；退出后换 `media-b` 重新登录，同一任务仍可见。
- 截图保存在 `.runtime/test-artifacts/m3-real-acceptance/`，不提交仓库。

首次 Chromium 验收脚本将实际 tab 名“优秀传播视频”误写为“优秀传播”，因选择器不匹配失败；修正临时验收脚本后通过，未修改产品代码或降低页面断言。

## 5. 未登记筛选条件的 fail-closed 证据

用户给出的“达人类型：游戏-游戏剧情、粉丝 10—100w、互动率≥2%”不在当前 live capabilities 中，本轮没有伪造支持：

- `interaction_rate` 不属于 `RequirementForm v1`，API 返回 422，字段路径为 `body.interaction_rate`，未创建任务。
- 只提交预留 Schema 内的 `creator_types=[游戏-游戏剧情]` 和 followers 100000—1000000 时，根任务 `9c9246a7-68ac-4fd8-9d71-24df5662f10b` 终态为 `FAILED_VALIDATION / UNSUPPORTED_FILTER`，discovered=0。
- 该失败任务的 `model_runs=0`、`collection_dispatches=0`：在付费模型和浏览器资源前即被确定性能力门拦截。

因此 M3 P0 仍只验收内容关键词；要在产品中启用上述三个条件，必须先完成 U02/F04 真实填写、回读、枚举、单位和组合核验。

## 6. 最终回归

| 命令/层级 | 结果 |
|---|---|
| `make check` | 通过；155 后端单测、2 前端组件测试、TypeScript strict、Vite 生产构建 |
| `make test-integration` | 65 passed, 1 skipped，206.56 s；在 `xingtu_test_m3` 上运行，此次全量组合无租约超时失败 |
| MinIO 专项 | 1 passed, 2.49 s；专用 bucket 写入、读回、篡改检测与清理 |
| `make test-contract` | 28 passed, 11.13 s；真实 Chromium + 合成路由，不是平台流量 |
| `make test-e2e` | 7 passed, 5.69 s；Temporal E2E + 产品 Chromium 合成 API E2E |
| 真实 DeepSeek | 模型检查、结构化生成、用量与持久追溯通过 |
| 真实星图产品任务 | 有效 2 位，2 份发布快照，两组精选14 张，14 个封面；因一位 fans 模块结构变化如实为 `PARTIAL_COMPLETED` |

`make test-integration` 中的 1 项 skip 是显式 MinIO endpoint 未在该命令进程中设置；同轮随后配置专用本地 MinIO endpoint 单独执行该项，结果 1 passed。

## 7. 验收结论与剩余边界

- INTAKE-01 的 M3 P0 范围（当前已核验 keyword 能力）完成真实 DeepSeek 和 P1→P2 同根任务验收。
- CONSOLE-01 完成真实任务、两媒介、刷新/重登恢复、发布快照、双集合和封面验收。
- APP-01 的本地产品会话已通过，但本轮明确不进入生产环境；正式 HTTPS/域名/精确 Origin/Secure Cookie 仍为待验收。
- 达人类型、粉丝量和互动率不因本轮成功任务而视为已支持；它们仍属 U02/F04 覆盖缺口。
- 真实任务发现一位达人 `fans` 响应 Schema 不匹配，当前结果和错误呈现正确；如需让同类任务达到全量 `COMPLETED`，应单独开启 F05 契约变化调研，未在 M3 中自动修改。
