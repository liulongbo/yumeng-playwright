# LIB-01「汽车、5 位达人」真实采集与页面验收

时间：2026-10-14（Asia/Shanghai）。环境为本机开发库 `xingtu_development`（migration 11）、真实 Chrome 和已授权星图会话；不是生产线路。本文不记录 Cookie、密码、平台响应正文或可识别达人资料。

## 真实任务

在星采产品页面完成登录、填写关键词“汽车”和目标数 5，并提交根任务 `efb257a6-476b-47ee-aff4-807795bb61a0`；`POST /api/tasks` 返回 202。`make m3-check` 的数据库、迁移、Temporal、live contract、执行单元和模型预检均通过。

任务终态为 `PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE`，有效达人 5/5、不可变快照 5、两组精选集合观测 10。该不完整状态来自真实资料范围缺口，不是写入错误。

## JSONB 与读模型只读对账

| 项目 | 结果 |
| --- | ---: |
| `task_creators` / 快照 | 5 / 5 |
| 星图平台身份、current 最新快照指针、snapshot-index 匹配 | 5 / 5、5 / 5、5 / 5 |
| payload 为 8 模块且含两个完整度标志 | 5 / 5 |
| `field_sources`、module/metric 状态元数据存在 | 5 / 5、5 / 5 |
| 报价数组与 quote-observations 对应 | 5 / 5；共 26 条 |
| followers、CPM、CPE 原始值及 followers 状态与 snapshot-index 一致 | 均 5 / 5 |

5 份快照的 81 个注册字段状态汇总：`COLLECTED=373`、`NO_DATA=13`、`FAILED=19`。缺失/失败没有被写为 0；`creator_snapshots.payload` 和 `platform_creators.projection` 仍是权威 JSONB，三张巨量星图专属表只作当前/历史/报价读取投影，符合[结构化方案](../达人数据JSONB结构化与多平台兼容改造方案.md)。

首次汇总查询误用了本机 PostgreSQL 不提供的 `jsonb_object_length`，未产出断言；随即改用 `jsonb_object_keys` 等价计数重跑并得到上表结果，没有写库或修改断言。

## 真实 Chrome 页面验收

真实 Chrome 登录后复核 `/creators`：

- 列表加载 20 条当前资料（分页上限），显示原始指标、近似/缺失和完整度。
- 在“粉丝数下限”控件输入 `0` 后，URL 含 `followers_min=0`、控件保留 `0`、列表加载 20 条；API 日志记录 `GET /api/creator-library?followers_min=0&limit=20` 200。
- 本次任务的一位达人详情显示“商业合作报价”“数据质量与来源”“历史快照”；页面报价 3 条、历史 1 条，分别与该达人读模型计数一致；来源区块含字段来源/模块状态展开入口。

截图位于被忽略的 `.runtime/mcp-artifacts/mcp-ui-20261013/`。控制台只有登录前 401 与静态资源 404 两条开发期资源消息，未见页面异常或业务 API 错误。

结论：用户指定的真实采集、JSONB/读模型一致性，以及达人库列表、筛选、详情、报价、来源与历史均已验收。F09 指定达人刷新是独立任务，未冒充完成。
