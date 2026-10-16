# LIB-01 对《达人数据 JSONB 结构化与多平台兼容改造方案》的符合性复核

时间：2026-10-14（Asia/Shanghai）。方法：代码、迁移和本机开发库只读元数据查询；结合“汽车、5 位达人”真实任务 `efb257a6-476b-47ee-aff4-807795bb61a0` 的对账结果。本文不含凭据、平台响应或达人可识别数据。

## 验收结论

**结论：核心业务语义符合，但严格按方案验收为“部分符合，暂不建议签发完全符合结论”。**

真实任务证明：5/5 不可变 JSONB 快照、current、snapshot-index 与报价观察一致；缺失状态未写 0；报价保留数组顺序和原始元素；没有跨平台身份合并。该部分满足方案的轻量混合存储主线。

| 方案要求 | 结论 | 证据/说明 |
| --- | --- | --- |
| JSONB 继续作为权威历史与当前字段依据 | 符合 | `creator_snapshots.payload`、`platform_creators.projection` 未被改写；真实任务 5/5 对账一致。 |
| 平台隔离、无自然人自动合并、原始口径 | 符合（巨量星图范围） | `(platform, platform_creator_id)` 身份边界和 `douyin_xingtu_*` 专属读模型存在；CPM/CPE 等未赋币种或换算。第二平台尚未实施，不能据此证明跨平台运行时兼容性。 |
| current / history / quote 三类查询模型和同事务发布 | 符合 | `CreatorLibraryWriter` 在快照插入后的同一持久化事务执行；真实任务的 5/5 指针、历史索引和报价数组均匹配。 |
| 失败/缺失不清空当前成功值 | 符合（代码审查与真实字段状态） | current 写入使用 `COALESCE`，真实任务保留 `NO_DATA` / `FAILED`，没有零值伪造。 |
| 历史与报价读模型的追加式保护 | **不符合** | `creator_snapshots` 有 `snapshot_immutable` 触发器；`douyin_xingtu_creator_snapshot_index` 与 `douyin_xingtu_creator_quote_observations` 均无触发器。应用写入为 `ON CONFLICT DO NOTHING`，但数据库层仍允许直接 UPDATE/DELETE，未满足方案“追加式保护”。 |
| 字段级来源能定位到来源快照 | **部分符合** | current `field_sources` 有观测时间、状态、来源类型、契约和路径，但没有每字段 `snapshot_id`。`latest_snapshot_id` 只是行级最新快照，不能证明一个未在最新快照成功的字段来自哪份旧快照。 |
| 快照索引保存字段来源/周期 | **部分符合** | 实现了 `module_statuses`、`metric_statuses`，但没有方案定义的 `metric_sources`（字段级 observed_at、period、source）。完整来源仍在 payload，读模型自身不能独立完成该追溯。 |
| 规划的筛选索引 | **部分符合** | 有 current 复合筛选索引和 `industry_labels` GIN；缺少方案指定的 `content_theme_labels` GIN、CPM/CPE 索引及 followers DESC 索引。功能正确性不受影响，但大数据量筛选/排序性能没有按方案保证。 |
| 报价结构化字段 | **部分符合** | 合作形式、价格、原价、结算描述和完整 `offer_raw` 已保留；方案列出的 settlement/task/video 原始编码未拆成类型列。完整信息仍可从 `offer_raw` 取得，但不能直接结构化筛选。 |
| 当前报价语义 | **部分符合** | 表保留全历史观察；现有 quotes API 按时间返回全部观察，未显式提供“每合作形式最新 `COLLECTED` 观察”的 current 视图/标识，UI 也未区分当前与历史报价。 |

## 必须关闭项

1. 为 snapshot-index 和 quote-observations 加与历史表一致的数据库级 UPDATE/DELETE 禁止触发器，并补迁移/回归。
2. 给 current `field_sources` 补字段级 `snapshot_id`；给 snapshot-index 补 `metric_sources`，保留 `observed_at`、周期、来源和契约信息。
3. 落实方案中的 content-theme、CPM/CPE 与粉丝排序索引，使用真实/代表性数据做 `EXPLAIN` 验证。
4. 将报价 API/UI 明确分为当前报价（每合作形式最新成功观察）和历史报价，或在响应中标明其历史语义；若要按 settlement/task/video 查询，物化方案列出的原始编码列。
5. 新增第二平台时，执行实际的平台隔离、同 ID 不冲突、无自动合并回归，届时才能验收“多平台兼容”的运行时结论。

在上述项关闭前，LIB-01 可作为“当前巨量星图达人库功能验收通过”，但不应被表述为“完全符合改造方案”或“多平台兼容已验证”。
