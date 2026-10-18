# DATA-02：达人指标与作品字段 JSONB 结构化（迁移 015、历史回填与写入链路）

状态：已完成
更新时间：2026-10-18T10:01:22+08:00
是否验收：是；本卡范围为「结构拆分 + 历史回填 + 写入/读取链路」，验收项全部满足（作品封面对象的全量回填属 [CD-08](CD-08.md)，不在本卡范围）。

## 目标与范围

按用户本轮明确要求，把「商业能力 → 内容数据」的 7 个指标与「创作能力 → 最新视频表现」的 11 个作品字段，从已有 JSONB 采集数据中拆分为可独立查询的数据库字段，并提供历史数据迁移方案与后续正常采集的同步写入。

预期结果：

1. 7 指标可在 `douyin_xingtu_creator_current` 与 `douyin_xingtu_creator_snapshot_index` 上直接查询，语义与单位明确。
2. 11 个作品字段形成独立作品观测表，作品与作者/达人/快照的关联正确，不产生重复作品记录。
3. 历史数据从已有快照 JSONB 回填，**不重新采集**、不覆盖已有正确数据、不删除或重写原始 JSONB。
4. 新采集经现有业务流程自动写入上述字段。

包含：

- 迁移 `015`：新增 5 个指标列（互动率/完播率已存在，不重建）、新增作品观测表、新增 `media_objects.source_key`、（任务 1 需要的）封面按平台原始 key 解析的定位能力。
- `CreatorLibraryWriter` 写入链路扩展与 API 读模型扩展。
- 历史数据回填 SQL（幂等、只增不改）。
- 文档同步：`docs/达人数据字段字典.md` 与 `docs/达人数据JSONB结构化与多平台兼容改造方案.md` 加注本轮授权的设计变更。

明确不做：

- 不新增采集能力去补平台未返回的字段（副标题、收藏数）。
- 不改动 P1/P2 无关模块、不改精选集合既有表结构与接口。
- 不新增与本轮无关的表、索引或基础设施。
- 不删除或重写任何已发布快照、不删除 JSONB。

## 关联与依赖

- 前置：[DATA-01](DATA-01.md)（只读审计与改造方案，本卡是其授权的实施卡）、[LIB-01](LIB-01.md)（current / snapshot-index / quote 三张读模型的建立者）。
- 关联本轮卡片：[CD-08](CD-08.md)（作品封面修复复用本卡的作品表与 `media_objects.source_key`；传播量中位数修复复用本卡的 `play_median_value_raw`）。
- 依据：[开发规范](../agent.md) 第 4、5、7 章；[技术方案](../AI达人智能发现与采集系统-完整技术方案.md) 第 13—16、18 章。

## 已记录的既有设计冲突（本卡显式变更，不是疏漏）

- `docs/达人数据字段字典.md:155-156` 原文：「`recent_video_performance` … **J；不拆入通用作品表**」。
- `docs/达人数据JSONB结构化与多平台兼容改造方案.md:137` 原文：只物化明确进入列表/筛选/趋势的字段，「…**创作作品**…继续 JSONB/既有专表」。

本轮用户明确要求拆分作品字段与作品表，属**已授权的设计变更**；上述两份文档已按本卡加注变更依据，不静默改写。

## 字段清单（盘点结论，全部来自真实库与真实快照）

### 7 指标（`creator_snapshots.payload.modules.spread.fields[]`，同一投影见 `platform_creators.projection`）

| 业务字段 | 已独立列 | 原始 JSON 路径 | 类型 / 单位 | 处理 |
|---|---|---|---|---|
| 传播量中位数（平台卡片「播放量中位数」） | 无 | `spread.item_rate_metrics.data.play_mid.value`（同行超越 `…overtake`，万分比） | numeric（次） | 新增 `play_median_value_raw` |
| 完播率 | 有 `completion_rate_value_raw` | `spread.completion_rate.data.value` | numeric 万分比 | 复用，不重建 |
| 互动率 | 有 `interaction_rate_value_raw` | `spread.interaction_rate.data.value` | numeric 万分比 | 复用，不重建 |
| 平均时长 | 无 | `spread.average_duration.data` | numeric 秒×100 | 新增 `average_duration_value_raw` |
| 平均点赞 | 无 | `spread.average_likes.data` | numeric 次 | 新增 `average_likes_value_raw` |
| 平均评论 | 无 | `spread.average_comments.data` | numeric 次 | 新增 `average_comments_value_raw` |
| 平均转发 | 无 | `spread.average_shares.data` | numeric 次 | 新增 `average_shares_value_raw` |

**重要口径登记**：同一 `spread` 响应里另有**顶层** `play_mid`（契约字段 `play_median`，`contracts/douyin_xingtu.verified.json:3821-3832`）。线上实测（2026-10-16，达人 `6639192346380468227`）平台「商业能力 → 内容数据 → 播放量中位数」显示 `76.6w / 优于 99.23%`，等于 `item_rate_metrics.play_mid`（766187 / 9923），**不等于**顶层 `play_mid`（1399516，线上无对应展示）。顶层 `play_mid` 仍作为原始观测保留，`play_median_value_raw` **只取** `item_rate_metrics.play_mid.value`。

另：`conversion.related_video_play_median`（`video_vv_median` = 1331347 ≈ 133.1w）对应平台「转化能力」中另一张真正的「播放中位数」卡片，映射本就正确，本卡不动。

### 11 个作品字段（`creation.recent_video_performance` / `recent_xingtu_video_performance` 的 `value.data[]`）

全库 123 份快照共 **3064 条**作品记录的键并集已实测（本卡证据），结论：

| 业务字段 | 实测 JSON 键 | 存在率 | 存储列 | 空值规则 |
|---|---|---|---|---|
| 作品 ID（本平台自定义） | 无平台「文案」字段 | — | `content_id uuid`（复用 `contents` 表，由本平台 `uid()` 生成） | 平台标识缺失时为 NULL |
| 平台作品 ID | `item_id` | 3064/3064 | `platform_item_id text` | 不回填猜测值 |
| 平台视频 ID | `video_id` | 2974/3064 非空 | `platform_video_id text` | 缺失为 NULL |
| 作品封面（平台原始 key） | `item_cover`（= `head_image_uri` = `item_animated_cover`） | 2974/3064 非空 | `cover_source_uri text` | 平台返回空串时为 NULL，状态 `NOT_PROVIDED` |
| 作品标题 | `title`（回落 `item_title`） | 2955/3064 非空 | `title text` | 缺失为 NULL |
| 作品副标题 | **全库不存在该键** | 0/3064 | `subtitle text` | 恒 NULL，`field_statuses.subtitle='NOT_PROVIDED'` |
| 作品作者 ID | `core_user_id` | 3064/3064 | `platform_author_id text` | 缺失为 NULL |
| 播放数 | `play` | 3064/3064 | `play_count numeric` | 真实 0 保留为 0；缺失才 NULL |
| 点赞数 | `like` | 3064/3064 | `like_count numeric` | 同上 |
| 评论数 | `comment` | 3064/3064 | `comment_count numeric` | 同上 |
| 收藏数 | **全库不存在该键** | 0/3064 | `favorite_count numeric` | 恒 NULL，`field_statuses.favorite_count='NOT_PROVIDED'` |
| 分享数 | `share` | 3064/3064 | `share_count numeric` | 同上 |
| 发布时间 | `item_date`（回落 Unix 秒 `create_time`/`create_timestamp`） | 3064/3064 | `published_at timestamptz` + `published_raw text` | 保留平台原文，转换失败则 NULL |

表粒度（用户 2026-10-16 选定 A）：追加式历史观测，主键 `(snapshot_id, module_key, position)`，与 `creator_snapshots` / `featured_cards` 的不可变先例一致；同一作品同时出现在两组模块时各自保留独立次序与指标，另建 `(creator_id, platform_item_id)` 索引支持「同一作品最新值」查询。

## 验收清单

- [x] 迁移 `015`（及后续 `016`/`017`）在开发库单事务应用成功，`schema_migrations` 记录版本 15/16/17。
- [x] `douyin_xingtu_creator_current` / `douyin_xingtu_creator_snapshot_index` 各新增 5 个指标列；互动率/完播率既有列未被重建或改名（010 原列沿用）。
- [x] 5 个新指标列的历史回填值与快照 JSONB 逐条一致；缺失保持 NULL，**没有一列被填 0**。
      证据：59 位达人中各列非空 51；8 位为平台 `{"label":""}`（无 `value` 成员）→ NULL；实测 3 处 `0` 均为平台原值 `"0"`。
- [x] 作品观测表按 `(snapshot_id, module_key, position)` 唯一；行数等于历史 JSONB 作品记录数。
      证据：`3064` 行，与全库作品记录数逐条相等，无重复。
- [x] 副标题与收藏数两列确认全 NULL，`field_statuses` 标注 `NOT_PROVIDED`。
      证据：`3064/3064` 两列均为 NULL 且状态为 `NOT_PROVIDED`（全库 3064 条记录无该键）。
- [x] 作品行与作者关联正确。
      证据：`content_id` 非空 `3064/3064`；`contents.platform_content_id` 与 `platform_item_id` 不一致 0 处；`creator_id` 与快照不一致 0 处。
- [x] 原始 `creator_snapshots.payload` JSONB 未被修改。
      证据：迁移前后 `md5(string_agg(payload::text))` 均为 `b14051a6aa2b5abd0ac23a2788e77b1b`。
- [x] `CreatorLibraryWriter` 在新采集路径上写入 7 指标与作品行（集成测试覆盖，含真实零值与缺失状态）。
- [x] API 暴露新增指标与作品读取，历史达人可读（不依赖重新采集）。
      证据：`/api/creator-library/{id}` 的 `play_median` 等 5 个 `LibraryMetric` 均带 `observed_at`；`/videos` 两入口返回历史快照作品行。
- [x] 迁移脚本与回滚方式记录在卡片与迁移注释；回滚不删除快照与 JSONB。
- [x] 同步 `backend/tests/integration/test_repository.py` 的迁移版本断言（`1…17`）。
- [x] 适用检查通过：`ruff check` / `ruff format --check` / `mypy --strict`（33 文件）；后端 `403 passed, 1 skipped`；前端 `lint` 通过、`82 passed`、`build` 通过。

## 实现记录

2026-10-16：完成盘点（见上「字段清单」）。确认真实库中 7 指标只有互动率/完播率已物化；无任何作品表；平台对「副标题」「收藏数」从未返回字段。用户确认：作品表粒度取追加式历史观测；「作品 ID」指**本平台自定义新增**的标识（复用 `contents.content_id`，不复用平台 ID 作为本平台 ID）。

2026-10-16 实施：

- `migrations/015_creator_video_and_metric_fields.sql`：5 个指标列（current + snapshot-index）；`douyin_xingtu_creator_video_observations`（追加式，主键 `(snapshot_id, module_key, position)`，含不可变触发器与 4 个索引）；`media_objects.source_key` + 部分索引；回填 5 指标、`contents` 作品身份、3064 条作品观测行。回填 SQL 使用正则守卫的 `::numeric` 转换，缺失一律 NULL。
- `migrations/016_creator_metric_field_sources.sql`：从快照字段信封回填 5 列的 `field_sources`（7 键白名单）。
- `migrations/017_creator_metric_provenance_cleanup.sql`：删除「列值为 NULL 却仍有来源条目」的 8 条记录。
- `backend/src/xingtu/creator_library.py`：新增 `_structured_scalar`（`data` 直接是值的形态）与 `_structured_member`（`item_rate.play_mid.value`）；`_source_fields` 增 5 项；`_upsert_current`/`_insert_snapshot_index` 增列（`COALESCE` 保护旧成功值）；新增 `_insert_video_observations`（与 015 回填同构，`ON CONFLICT DO NOTHING`）与作品字段状态构造 `_work_field_statuses`、发布时间解析 `_work_published`、平台/本平台作品身份解析 `_content_id`。
- `backend/src/xingtu/product_models.py` / `product_queries.py` / `product_api.py`：`CreatorLibrarySummary` 新增 5 个 `LibraryMetric`；新增 `CreatorVideoObservation`/`CreatorVideoPage` 与两入口只读端点。
- 文档：`docs/达人数据字段字典.md` 与 `docs/达人数据JSONB结构化与多平台兼容改造方案.md` 已按本卡的授权变更加注（原「作品不拆入通用作品表」结论被本轮用户要求取代）。

## 验证证据

- 2026-10-16，环境：开发库 `55432/xingtu_development`、测试库 `55432/xingtu_test`、迁移 `1→17` 全部应用。备份：`.runtime/xingtu-pre-data02-20261016T153124.dump`。
- 迁移应用：`XINGTU_DATABASE_URL=… xingtu migrate --environment development` → `all pending migrations applied or already present`。
- 回填核对（SQL 实测）：`current` 59 行 / 各列非空 51 / 伪造 0 值 0；`snapshot_index` 103 行 / 89 行有 `play_median`；作品 3064 行；`content_id` 覆盖 3064/3064；副标题与收藏数 0 非空且状态均为 `NOT_PROVIDED`；JSONB md5 迁移前后一致（`b14051a6aa2b5abd0ac23a2788e77b1b`）。
- 测试：`backend/tests/unit/test_creator_video_fields.py`（7 例，新增）、`backend/tests/integration/test_creator_library.py`（6 例，含新增的写入链路与作品/封面读取与越权用例）、`backend/tests/unit/test_video_covers.py`（6 例，属 CD-08 但复用本卡契约）；全量 `pytest backend/tests/{unit,contract,integration}` → `403 passed, 1 skipped`。
- 2026-10-18 合并前回归：修复任务作品接口接受其他任务同达人 `snapshot_id` 的越界读取；补充跨任务同达人快照用例，与手动更新幂等回归合计 `2 passed`。
- 静态检查：`ruff check`、`ruff format --check`、`mypy backend/src`（strict，33 文件）全部通过。
- 详细逐项结论见 [CD-08 / DATA-02 验收证据](../evidence/CD-08-DATA-02-acceptance-2026-10-16.md)。

## 回滚方式

三个迁移都只做加法（新列、新表、新索引、新列上的登记）。回滚步骤：①停止写入新字段的应用版本并回退应用；②新增列/表/索引保留供审计（改造方案约定），不删除 JSONB、不删除快照、不删除 `contents` 行；③只有另行授权的数据治理任务才能删除新表或历史数据。已在迁移文件头注明同一约定。

## 交接信息

阻塞：无。未完成事项：无（本卡范围）。范围外、由 CD-08 负责的剩余项见 [CD-08](CD-08.md) 交接信息；其中「历史作品封面对象全量回填」不影响本卡的结构化、回填与读写链路结论。

回滚方式见上节。

## 状态历史

- 2026-10-16T20:30:00+08:00：建立 → 进行中；用户本轮要求把 7 项内容数据指标与 11 个作品字段从 JSONB 拆为独立字段，并明确作品 ID 为本平台自定义标识。
- 2026-10-16T16:05:00+08:00：进行中 → 已完成；迁移 015/016/017 应用并回填完成、写入与读取链路接通、数据一致性逐项核对、测试与静态检查通过、文档已同步。
- 2026-10-18T10:01:22+08:00：合并前审查发现并修复任务作品接口的跨任务快照读取缺陷；定向回归通过，状态保持已完成。
