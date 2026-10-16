# DATA-01：达人 JSONB 数据库只读审计证据

日期：2026-10-13（Asia/Shanghai）  
环境：本机 Docker Compose `app-postgres`，PostgreSQL 18.3，`xingtu_development/public`。  
边界：所有语句在 `BEGIN READ ONLY` 事务中运行；没有执行迁移、DML、采集或导出原始达人内容。

## 已核验事实

| 项目 | 结果 |
|---|---|
| Schema 版本 | `schema_migrations` 为 1—9 |
| 平台身份 | `platform_creators` 的唯一约束为 `(platform, platform_creator_id)` |
| 真实样本 | 11 个巨量星图平台达人、39 份 `creator_snapshots`，快照时间范围 2026-10-07 至 2026-10-12 |
| 当前投影 | 每个达人 72—80 个 `projection` 字段路径；共观察到 80 条当前成功路径 |
| 历史载荷 | 每份快照均有 `modules`、`collections`、完整度和失败状态；8 个模块都有观测 |
| 不可变性 | `creator_snapshots` 已有 `snapshot_immutable` 触发器；精选集合/卡片已有追加式触发器 |
| 嵌套结构 | 报价为对象数组，元素含 `field`、`price`、`origin_price`、`settlement_type` 等；CPM/CPE 为带时长键的数字字符串；互动/完播为 `label/value/overtake` 对象 |

## 字段状态结论

- 注册表为 8 模块/81 业务字段；快照额外的 `fans.__module_failure__` 仅是失败诊断。
- `basic.industry_labels_raw` 在当前样本均为 `NO_DATA`，所以不在 current projection；其余已采集字段根据 `COLLECTED` 和 `observed_at` 写入 projection。
- `fans`、`creation`、部分 `spread`/`seeding`/`fulfillment` 字段存在 `NOT_ATTEMPTED`、`FAILED` 或 `NO_DATA`，证明当前/历史设计必须以字段状态处理，不能用空值或零值替代。
- 未在日志或本证据中保存达人 ID、昵称、头像 URL、报价、作品标题或具体指标数值。

## 复现实验动作

通过 `docker compose ... exec -T app-postgres psql` 依次读取：数据库/Schema/迁移；相关表列、约束、索引；身份/快照/作品计数；`projection` 与 `payload` 的键、模块、字段状态、单位、周期与 JSON 类型；报价、CPM/CPE、互动/完播的嵌套键和值类型。所有查询使用只读事务且输出仅保留聚合计数、键名、类型与脱敏格式。
