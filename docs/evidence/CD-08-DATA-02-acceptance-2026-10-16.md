# CD-08 / DATA-02 验收证据：作品封面、传播量中位数与指标/作品字段结构化（2026-10-16）

> 对象：达人详情「创作能力 → 最新视频表现 → 作品列表」封面、「商业能力 → 内容数据 → 播放量中位数」，以及 7 项内容数据指标与 11 个作品字段的 JSONB 拆分。
> 代码范围：`migrations/015–017`、`backend/src/xingtu/{contracts,adapter,covers,engine,creator_library,product_models,product_queries,product_api,video_covers,cli}.py`、`frontend/src/**`、`contracts/douyin_xingtu.verified.json`。
> 未涉及：P1 需求转换、精选集合既有接口行为、其它六项内容数据指标的口径、任何快照重写。

## 1. 线上取证（只读，Playwright MCP 1.62.0-alpha-2026-06-29 + 本机 Chrome）

对象：达人 `6639192346380468227`（库内 `6f13771f-b62a-4b6f-b5a4-c3aa85c86edd`，最新快照 `8366cf58-9f68-4cdf-bb73-5bb0c23438dd`，采集于 `2026-10-16T01:43:32Z`）。

| 项 | 线上显示 | 库内叶子 | 结论 |
|---|---|---|---|
| 商业能力 → 内容数据 → **播放量中位数** | `76.6w`，`优于 99.23% 同类型达人`，tooltip「所选数据范围内视频播放量中位数（仅统计公开可见视频）」 | `spread.item_rate_metrics.data.play_mid = {value 766187, overtake 9923}` | 一致；顶层 `spread.play_mid`（`1399516`）线上无对应展示 |
| 商业能力 → 转化 → 播放中位数 | `133.1w` | `conversion.related_video_play_median = 1331347` | 另一张卡片，映射本就正确 |
| 创作能力 → 最新视频表现 → 作品列表封面 | 页面自身请求 `GET /gw/api/fe_common_service/tools/get_sign_image?uri=tos-cn-i-0813c001%2FosvAyCE5GFDA9ggqRvAqFnfAf7NAFqQAlUIpK3&durationTS=86400&format=webp` → `200`，渲染 `p26-star-fe-sign.byteimg.com/…~tplv-9hvokabxw2-image.webp`（734×978） | 该 key 即库内该达人首条最新视频的 `item_cover` | 平台用**已登记**的签名端点把不透明 key 换成短时外链 |

签名端点参数实测（同一浏览器会话内直接 GET）：`?uri=<key>` 返回 `200` 但 `mainURL` 为 `.jpeg`（`image/jpeg`，不在已登记内容类型内）；加 `&format=webp` 得到 `.webp` 且落在已登记主机 `p3/p26-star-fe-sign.byteimg.com`。**故 `format=webp` 为必需项**，已登记为契约 `item_cover.query_defaults`。

其余六项逐卡片核对（2026-10-16）：完播率 `2.5%`/`96.93%`、互动率 `3.1%`/`78.56%`、平均时长 `191.1s`、平均点赞 `3.3w`、平均评论 `1,636`、平均转发 `550`，与库内 `253/9693`、`305/7853`、`19112`、`32600`、`1619`、`549` 一致（评论/转发的微小差异为窗口时间漂移）。

## 2. 数据库变更与回填（开发库 `55432/xingtu_development`）

| 迁移 | 内容 |
|---|---|
| `015_creator_video_and_metric_fields.sql` | `douyin_xingtu_creator_current` / `douyin_xingtu_creator_snapshot_index` 各新增 5 个 `*_value_raw numeric`；新增 `douyin_xingtu_creator_video_observations`（追加式，主键 `(snapshot_id, module_key, position)`，含 BEFORE UPDATE/DELETE 触发器）；`media_objects` 新增 `source_key` + 部分索引；回填 5 项指标、`contents` 作品身份与 3064 条作品观测行 |
| `016_creator_metric_field_sources.sql` | 从快照字段信封回填 5 列的 `field_sources` 字段级来源（observed_at / source_kind / source_contract / path_ref / unit / period_label） |
| `017_creator_metric_provenance_cleanup.sql` | 删除「列值为 NULL 却仍有来源条目」的 8 条 `play_median_value_raw` 记录（平台返回 `{"label": ""}` 无 `value` 成员） |

回填结果（迁移后实测）：

| 检查 | 结果 |
|---|---|
| `douyin_xingtu_creator_current` 达人数 / 5 列非空 | `59` / 各 `51`（8 位达人平台返回 label-only 信封，如实为 NULL） |
| 被填成 0 的指标 | 0 处伪造；实测 3 位达人的 `average_comments`（及 1 位 `average_shares`）为**平台真实 0**，原始 JSONB `raw_value` 即 `"0"` |
| `douyin_xingtu_creator_snapshot_index` | `103` 行，其中 `89` 行有 `play_median_value_raw` |
| `field_sources` 与列值一致性 | 5 列来源条目数 = 各列非空数（`51/51/51/51/51`），`prov_without_value = 0` |
| 作品观测行数 | `3064`，与历史 JSONB 作品记录数逐条相等；`(snapshot_id, module_key, position)` 无重复 |
| 作品与作者/身份关联 | `content_id` 非空 3064/3064；`contents.platform_content_id` 与 `platform_item_id` 不一致 0 处；`creator_id` 与快照不一致 0 处 |
| 副标题 / 收藏数 | 两列全为 NULL（0/3064 非空），`field_statuses` 全部标注 `NOT_PROVIDED` |
| 原始 JSONB 未被修改 | `md5(string_agg(payload::text …))` 迁移前后均为 `b14051a6aa2b5abd0ac23a2788e77b1b` |

## 3. 封面回填（`xingtu video-covers`）

- 命令：`.venv/bin/xingtu video-covers --config .runtime/units/local-dev-mac-02.json [--creator <id>] [--limit N] [--dry-run]`。
- 语义：只用**已存的**平台不透明 key 调用已登记签名端点，经 `Adapter.fetch_cover`（页内、复用执行单元会话与线路、主机/内容类型/大小/超时受控）下载，再经 `CoverPipeline` 校验后入库，并按平台 key 登记到 `media_objects.source_key`。**不采集达人数据、不写快照、不写指标**。
- 去重后待回填 key 总数 `1591`（`--dry-run` 实测）。
- 单达人实测：`6f13771f-…`（就叫Roxy）`candidates=26, stored=26, already_stored=3, unsigned=0, failed=0`，其后该达人 `29/29` 作品封面均为 `STORED`；`700ca5b0-…`（甄选聊车）`candidates=9, stored=9, already_stored=15, unsigned=0, failed=0`。
- **全量扫描已完成**：`{"candidates":1322, "stored":1321, "already_stored":269, "unsigned":1, "failed":0}`。
- 最终覆盖率（SQL 实测）：

| 口径 | 数量 |
|---|---|
| 去重后平台封面 key 总数 / 已解析 | `1591` / **`1590`**（99.94%） |
| 当前（最新快照）引用的 key / 已解析 | `1535` / **`1534`** |
| 作品行总数 / 平台未返回封面 key / 仍未解析 | `3064` / `90` / **`4`** |

- 唯一未解析 key：`tos-cn-i-0629/os1ADII2CoBIkATg8AAqJEaYCXJqEw6iA3isv`（平台拒签 `SIGN_UNSIGNED`），被 1 位达人的 4 条作品观测引用；这些作品页面显示「封面未生成」，**未用其它作品封面替代**。
- 幂等与可续跑：已登记的 key 会在下一次运行中被 `NOT EXISTS` 跳过；同一图片重复下载命中同一内容寻址 object id。本次会话即在中断后按同一命令续跑完成。
- **经全量扫描解析的达人同样端到端可用**：对未做单达人回填的 `6669292655366635524`（`df96aee4-…`）复跑逐作品核对，两模块各 15 条全部通过（含封面 src 与 `cover_object_id` 逐条相等、封面互不相同、`all_covers_stored`）。

## 4. 后端验证

命令与结果（2026-10-16）：

```
export PLAYWRIGHT_BROWSERS_PATH=$PWD/.runtime/browsers
export HOME=$PWD/.runtime/acceptance-home
export XINGTU_TEST_DATABASE_URL='postgresql://…@127.0.0.1:55432/xingtu_test'
PYTHONPATH=$PWD/backend/src .venv/bin/pytest backend/tests/unit backend/tests/contract backend/tests/integration -q
→ 403 passed, 1 skipped（迁移 015/016/017 与 §2 断言均在其中）
PYTHONPATH=$PWD/backend/src .venv/bin/pytest backend/tests/unit backend/tests/contract -q
→ 318 passed（不含需要 PostgreSQL 的集成层）
```

新增/更新的测试：

- `backend/tests/unit/test_creator_video_fields.py`（新增，7 例）：传播量中位数取嵌套 `item_rate.play_mid` 而非顶层 decoy；label-only 信封保持 NULL 不变 0；真实 0 保留为 0；`published_at` 优先 Unix 秒并回落 `item_date`；副标题/收藏数标注 `NOT_PROVIDED`。
- `backend/tests/unit/test_video_covers.py`（新增，6 例）：只发已观察签名；未观察时用登记 `query_defaults` 补齐；**回声不一致的签名响应被拒绝**；签名失败记为覆盖缺口；无 `item_cover` 的行不发起任何请求。该测试在实现过程中发现并固定了两个真实缺陷（见 §6）。
- `backend/tests/integration/test_creator_library.py`：新增写入链路投影测试、作品观测读取与封面授权测试（含越权 404）、任务入口作品读取与任务级封面归属测试。
- `backend/tests/integration/test_repository.py`：迁移版本断言同步至 `1…17`。
- 契约/单元既有用例（含 `test_featured*`）：全部通过，未削弱任何断言。

静态检查：本轮触及的 `backend/src`、`backend/tests`、`migrations` 下 `ruff check` / `ruff format --check` 全部通过；`mypy backend/src`（strict，33 个源文件）通过。

**`make lint` / `make format-check` 的既有失败（非本轮引入、未修改）**：仓库级 `ruff check backend conftest.py tests scripts` 仍报 11 处 `UP031`，`ruff format --check` 报 3 个文件需重排，全部位于 `scripts/acceptance/run_cd05_acceptance.py`、`run_cd06_acceptance.py`、`run_cd07_acceptance.py`。这三个文件与 `HEAD` **逐字节相同**（`git diff --quiet HEAD -- <file>` 通过），因此该失败在本轮改动前即存在；按「不修无关代码」的约束未改动，如实记录。前端 `lint` / `build` / `test`（`82 passed`）通过。

## 5. 前端与页面验收（真实 Chrome + MCP）

命令：`npm --prefix frontend run lint`（通过）、`npm --prefix frontend test`（`82 passed`）、`npm --prefix frontend run build`（通过）。

页面验收脚本：`.runtime/recon/accept_cd08.py`、`.runtime/recon/accept_correspondence.py`（登录本地媒介账号，两入口各走一遍）。

**逐作品对应核对**（`accept-correspondence`，两模块全部通过）：

| 检查 | 最新视频 | 最新星图视频 |
|---|---|---|
| API 行数 / 柱数 / 卡片数 | 15 / 15 / 15 | 14 / 14 / 14 |
| 柱顺序 = API 顺序（`platform_item_id`） | ✅ | ✅ |
| 柱链接 = 卡片链接（同序） | ✅ | ✅ |
| 链接 = API `work_url`、且互不相同 | ✅ | ✅ |
| 卡片封面 src = 该作品自己的 `cover_object_id` 授权端点、且互不相同 | ✅ | ✅ |
| 卡片播放量 = API `play_count` | ✅ | ✅ |
| 卡片标题 = API `title`（仅空白折叠差异） | ✅ | ✅ |
| 全部 `cover_status = STORED` | ✅ | ✅ |

**商业能力 → 内容数据**（页面实测，修复前后对比）：

| 指标 | 修复前页面 | 修复后页面 | 巨量星图 |
|---|---|---|---|
| 播放量中位数 | `140.0w`（读顶层 `play_median`） | **`76.6w`，优于 `99.2%` 同类型达人，平台原值 766187 / 超越原值 9923** | `76.6w`，优于 `99.23%` |
| 完播率 | `2.53%` / 96.9% | `2.53%` / 96.9%（未变） | `2.5%` / 96.93% |
| 互动率 | `3.05%` / 78.5% | `3.05%` / 78.5%（未变） | `3.1%` / 78.56% |
| 平均时长 | `191.1 秒` | 未变 | `191.1s` |
| 平均点赞 | `3.3w` | 未变 | `3.3w` |
| 平均评论 | `1.6k` | 未变 | `1,636` |
| 平均转发 | `549` | 未变 | `550` |

**创作能力 → 最新视频表现**：作品列表 15/15 展示真实封面（修复前 15/15 为「平台未提供封面地址」）；柱状图播放量与日期、卡片标题、跳转链接均与作品一一对应。截图：[内容数据面板](assets/cd08/01-commercial-content-data.png)、[作品列表封面](assets/cd08/02-creation-works-with-covers.png)。

**任务入口**：`/tasks/59f14291-…/creators/6f13771f-…` 同章节 15/15 封面，且封面地址全部走**按任务授权**的 `/api/tasks/{task_id}/covers/{object_id}`；同一对象在无关任务下返回 `404`。

**回归**：两入口四章节渲染正常；优秀传播视频 4 张封面仍正常显示；浏览器控制台错误 `0`。

## 6. 实现过程中发现并修复的真实缺陷

1. **封面签名回声未校验**（`adapter.replay_row_cover_sign`）：初次实现直接采用签名响应里的 `mainURL`，未校验响应回显的对象 key 是否等于请求的 key；一旦平台返回其它对象的地址，作品就会显示**另一个作品的封面**。已按精选集合的等值连接先例加入回声校验，并由 `test_video_covers.py` 固定。
2. **`text_value(None)` 生成字符串 `"None"`**（`adapter.emit_row_covers`）：缺失 `item_cover` 的作品会被当成 key 为 `None` 的对象去签名（多发一次请求，且在极端情况下可能落库错误对象）。已改为在原始值上判定缺失（`_signed_pair`），缺 key 的作品不发起任何请求。
3. **任务入口封面 404**（`Repository.cover_reference`）：任务级封面授权只认 `featured_cards`，不认识作品封面，导致任务入口作品列表全部降级为「封面未生成」。已扩展为第二条归属路径（`media_objects.source_key` → 作品观测 → 快照 `root_task_id`），并补越权 404 集成测试。
4. **迁移 015 回填 `canonical_link` 空串冲突**：空分享链接写成 `''` 会让 `contents` 的 `UNIQUE(platform, canonical_link)` 冲突，7 个作品身份被静默跳过。已改为 `NULLIF(url,'')`，回填后 `content_id` 覆盖 3064/3064。
5. **`field_sources` 描述空值**：8 条 `play_median_value_raw` 来源条目对应 NULL 列，已由迁移 017 清理。

## 7. 未完成 / 未验证事项

- **1 个 key 平台拒签**：`tos-cn-i-0629/os1ADII2CoBIkATg8AAqJEaYCXJqEw6iA3isv`（`SIGN_UNSIGNED`），影响 4 条作品观测；保持 `UNRESOLVED`（页面「封面未生成」），已如实登记，未用其它封面替代。
- **采集侧封面链路的真实新采集回归未做**：`emit_row_covers` / `store_row_cover`（采集时签名→入库→按平台 key 登记）目前只有单元与契约级验证（使用真实契约与真实签名参数），未在真实采集任务中跑通。用户本轮明确要求「没有必要不得为测试重新触发真实采集」，故按用户指令顺延到下一次正常采集任务后复核（判据：`media_objects.source_key` 是否随该任务新增）。此项对应验收清单「新采集数据能够按现有业务流程正常写入对应字段」，因此 CD-08 状态为**待验收**而非已完成。
- **同行超越展示精度**：平台显示 `99.23%`，本系统按既有 CD-02 约定显示一位小数 `99.2%`。该约定同时作用于完播率/互动率，本轮未改动，以免影响已确认的其它指标展示。
- **作品副标题 / 收藏数**：平台响应中从未出现该键（全库 3064 条记录 0 命中），本轮按用户要求不新增采集能力，列保持 NULL 并在 `field_statuses` 标注 `NOT_PROVIDED`。
- **`spread.play_median`（顶层 `play_mid`）**：线上未发现对应展示位，本轮保留其为原始观测但不再用于「播放量中位数」卡片；其业务口径（统计窗口或口径差异）仍**未确认**。
- **契约版本升级副作用**：`contract_version` 由 `v10` 升为 `v11`（新增 `cover_signs` 请求与 `item_cover` 字段级封面规范）。升级会新建能力健康计数行；升级前实测 `v10` 下无 `SUSPECTED`/`DISABLED` 能力（仅 1 条 `ENABLED` 记录），故不存在静默重新启用已禁用能力的风险。`adapter_version` 保持 `browser-v9`（checkpoint/适配器协议未变）。
