# LIB-01 真实 Chrome 采集与达人库写入验收（2026-10-13）

任务卡：[LIB-01](../tasks/LIB-01.md)。环境为本机开发运行时（非生产线路）；数据库为本项目 `xingtu_development`，迁移版本为 11。凭据、Cookie、会话快照、平台响应正文均未写入本文。

## 工具边界

用户要求使用 Playwright MCP + Chrome。开始前检查当前会话可调用工具，**没有暴露 Playwright MCP/Chrome MCP**，不能将其他工具标为 MCP 验收。项目绑定的非无头 Chrome 采集 Worker 可用，因此以下真实任务使用该 Worker 完成实际星图搜索、主页模块和两组精选采集；它不是网页交互层的 Playwright MCP 验收。

会话诊断工具另外缺少 `XINGTU_DIAGNOSTIC_HMAC_KEY`，按 fail-closed 规则在打开浏览器前退出，未伪造该密钥。实际 Worker 已通过既有受保护会话进入采集，任务状态和请求计数是本轮 Chrome 运行证据。

## 运行时预检与 API

`make m3-check`（获授权的本机连接）通过：PostgreSQL、Temporal、迁移 `11`、已验证 live contract、单元 `unit-local-mac-02`（`READY`）和真实 DeepSeek 模型均可用。

发现原 `127.0.0.1:8000` API 没有加载 `/api/creator-library`，因此只重启该本地旧 API 进程并启动当前代码的 API、Intake Worker、Collection Worker；consumer readiness 对 `xingtu-intake` 与 `xingtu-unit-local-mac-02` 均为 `alive=true`。重启后 `/openapi.json` 包含以下认证保护接口：

- `GET /api/creator-library`
- `GET /api/creator-library/{creator_id}`
- `GET /api/creator-library/{creator_id}/history`
- `GET /api/creator-library/{creator_id}/quotes`

未在没有用户凭据和 MCP 的情况下伪造产品网页登录或会话。

## 真实受控采集

创建内部验收根任务 `d5fe36f3-4dca-4cce-a6ae-87dcd9b16099`：已验证条件仅为关键词「宠物」，`target_count=1`，固定平台排序。真实 Worker 结果：

| 项目 | 结果 |
| --- | --- |
| 状态 | `PARTIAL_COMPLETED` / `PROFILE_SCOPE_INCOMPLETE` |
| 发现 / 有效 | 20 / 1 |
| 真实请求 / 响应 | 33 / 33 |
| 采集活跃时间 | 67.39 秒 |
| 精选集合 | `excellent_reach=COMPLETE`（3 卡）、`excellent_seeding=COMPLETE`（1 卡） |
| 封面 | 4 / 4 `STORED` |
| 资料字段 | `COLLECTED=70`、`NO_DATA=8`、`FAILED=3` |

该达人在 `conversion` 模块的 `recommended_product_count`、`related_video_count`、`related_video_play_median` 均为平台 `MISSING_SOURCE`，因此任务没有伪报资料完整；这不是达人库索引写入失败。

## JSONB 与达人库索引交叉核对

所选达人以脱敏 ID `c1a54190-…` / 平台 ID `6763••••9188` 记录。`douyin_xingtu_creator_current` 的本轮数据包括：粉丝 `1,157,508`、月深度用户 `25,367,000`（原始显示 `≈2,536.7w`）、月连接用户 `39,989,961`、月涨粉原始值 `-0.002788173733284524`、CPM 原始值 `18,290 / 23,777`、CPE 原始值 `1,230 / 1,599`、`profile_complete=false`、`pipeline_complete=false`、字段来源 17 项。

只读 SQL 验证：

- `creator_snapshots` 新增本轮不可变快照；current 的 `latest_snapshot_id` 指向此快照。
- `douyin_xingtu_creator_snapshot_index` 有对应的 1 行，完整度标志为 `false / false`，与任务收口一致。
- `douyin_xingtu_creator_quote_observations` 有 7 条本轮报价观测（包括植入视频、定制视频及其他平台合作形式）；不推断币种。
- `projection.basic.followers.raw_value = current.followers_raw`、`projection.basic.monthly_deep_users.raw_value = current.monthly_deep_users_raw`、`projection.spread.expected_cpm` 的 21–60 秒值等于 current 的结构化原始值，三项比对均为 `true`。

## 结论与未覆盖项

真实 Chrome 采集 → 不可变快照 / projection → LIB-01 三张查询读模型的发布同步通过；不完整字段保持缺失/失败语义，未覆盖或清空成功值。

本轮**未能完成**以下用户要求，不能标为通过：

1. 当前环境没有 Playwright MCP + Chrome MCP，无法完成要求的 MCP 页面级交互验收。
2. [F09](../tasks/F09.md) 的“指定达人刷新”尚未实现；系统没有允许不搜索、只更新指定达人并保留来源快照的 API/工作流。此次真实任务选择到的是新达人，不能冒充为指定已有达人更新。

后续应先实现 F09，然后用已存在达人执行一次刷新，并在可用的 Playwright MCP 中登录产品页核对 `/creators` 列表、详情、报价、来源和历史。
