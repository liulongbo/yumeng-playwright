# 直播达人采集扩展技术设计方案

状态：已批准（2026-11-04），第二阶段开发中  
版本：v0.1（2026-11-04）  
分支：`1104-llb`（起点 `origin/main@2ee5d1f`）  
关联：[PRD](../prd/LIVE-02-live-square-collection.md)、[真实页面调查证据](../evidence/LIVE-02-live-square-investigation.md)、[影响分析](LIVE-02-compatibility-impact.md)、[测试用例](../evidence/LIVE-02-test-cases.md)

## 1. 当前架构调查结果

### 1.1 现有链路（以当前代码为准）

```text
前端 NewTaskPage
  → POST /api/tasks (RequirementForm)
  → requirements + root_tasks(product_intake) + intake_dispatches
  → P1 Intake Worker：按 requirement_form.platform 选 registry
  → DeepSeek 生成 FilterPlan + 确定性校验
  → promote_intake：按 platform 选 collection unit；写 filter_plans/root_tasks/payload
  → Temporal CollectionWorkflow → collect_segment_v1 Activity
  → Worker：config.for_platform(platform) 读 registry；校验 plan；浏览器/会话/契约门禁
  → Adapter.search / profile / collect_module / featured
  → Repository.persist_creators：platform_creators + task_creators + creator_snapshots
      + platform_creators.projection + (星图) douyin_xingtu_creator_current
  → 任务终态/计数
  → 达人库/任务内达人读模型
```

关键代码位置：

| 关注点 | 位置 | 现状 |
|---|---|---|
| 根任务/平台 | `backend/src/xingtu/domain.py:99-116`、`TaskRecord.platform`（`domain.py:1083-1150`） | 任务只区分 platform；无 scene |
| 计划 | `domain.py:296-350` | `FilterPlan` 只含 platform/filters/target；无 scene |
| 单元/契约 | `runtime.py:56-230`、`worker.py:328-378` | 每个平台一个 registry；无场景选择 |
| 契约加载 | `worker.py:351-378`、`intake_worker.py:27-120` | 按 platform 选 verified registry |
| P1 | `intake.py:237-460`、`intake_worker.py:107-120` | 表单→计划；按 platform 选能力 |
| 持久化 | `repository.py:1812-1990` | projection + snapshots；星图另写 current |
| 聚星读模型 | `product_queries.py:1493-1720` | 直接读 `platform_creators.projection` + 最近任意快照 |
| 更新 | `creator_update.py:381-470`、`product_api.py:940-970` | 星图专属，依赖 `creator_update_schedule` |
| 任务中心 | `product_queries.py:316-701`、`frontend/src/pages.tsx:117-176` | 有 platform 筛选；无 scene |
| 达人库 | `product_queries.py:1211-1720`、`frontend/src/pages.tsx:1141-1301` | 平台分支；无 scene |
| 快照 | `migrations/001_initial.sql:36-44` | `creator_snapshots` 无 scene；不可变触发器 |
| 单元绑定 | `migrations/020_multi_platform_juxing.sql` | `(unit_id, platform)` 绑定；无 scene |

### 1.2 本次必须处理的既有耦合

1. **聚星短视频库直接读共享 projection/最近快照**：直播若写 projection 或产生同 creator 的最新快照，会把直播数据显示到短视频库。必须场景化写入与读取。
2. **星图 current 表只服务短视频**：直播需要独立 current，不能复用。
3. **更新服务硬编码星图 + schedule 表**：直播更新必须独立，不能写 schedule，不能改 scheduler。
4. **`pipeline_complete` 对星图默认要求两组精选**：直播若没有精选会永远部分完成；需把「精选仅当本契约注册了集合才要求」一般化，并回归星图/聚星短视频。
5. **适配器硬编码**：星图筛选执行器、聚星请求体/详情端点均为短视频；直播需要独立适配路径。

## 2. 扩展方式总览

采用「场景维度 + 每平台每场景一份契约 + 独立直播数据 + 复用任务/单元/快照基础设施」的增量方案。

```text
RequirementForm(platform, creator_scene)
  → 选择 (platform, scene) registry/capabilities
  → FilterPlan(platform, creator_scene, capability_version)
  → root_tasks(platform, creator_scene)
  → 现有任务中心/执行单元/Workflow
  → Worker 按 (platform, scene) 选 live registry
  → 直播 Adapter（星图 BrowserAdapter 子类 / 聚星 Live Adapter）
  → creator_snapshots(creator_scene=live_square)
      + creator_live_current（新表）
      + 不写 platform_creators.projection / 星图短视频 current
  → 达人库 scene=live_square / 直播详情
  → 直播手动更新：新服务 + 新接口，不写 schedule
```

### 2.1 契约与配置

- 新增两份直播契约（阶段二真实验证后 `VERIFIED`）：
  - `contracts/douyin_xingtu.live.verified.json`
  - `contracts/kuaishou_juxing.live.verified.json`
- 阶段一只产出 `contracts/*.live.observed.json`（`status=observed`，不被运行配置引用）。
- 单元配置增加可选 `live_registry_path`：
  - 单平台星图单元：`UnitConfig.live_registry_path`；
  - 平台绑定：`PlatformBindingConfig.live_registry_path`。
- 新增 `UnitConfig.for_scene(platform, scene)`：live 返回 registry_path 指向 live 契约；缺失时 fail closed（`RESOURCE_UNAVAILABLE/LIVE_CONTRACT_NOT_CONFIGURED`），**绝不回退短视频契约**。
- 产品配置增加：
  - `XINGTU_LIVE_REGISTRY_PATH`
  - `XINGTU_JUXING_LIVE_REGISTRY_PATH`
  - `XINGTU_ENABLE_LIVE_SQUARE`（默认 0）
- `/api/platforms` 返回 `scenes[]`：scene/label/enabled/capability_status/contract_version/disabled_reason。只有 Flag + VERIFIED 契约 + 可执行 Adapter 三者齐全才 enabled。

### 2.2 领域模型

```python
class CreatorScene(StrEnum):
    VIDEO_SQUARE = "video_square"
    LIVE_SQUARE = "live_square"
```

- `FilterPlan.creator_scene: CreatorScene = VIDEO_SQUARE`
- `RequirementForm.creator_scene: CreatorScene = VIDEO_SQUARE`
- `TaskRecord.creator_scene: CreatorScene = VIDEO_SQUARE`
  - collection：必须等于 plan.creator_scene；
  - update：显式设置；
  - 旧 payload 默认 video。
- `TaskSummary.creator_scene` / `TaskDetail.creator_scene`
- `CreatorLibraryDetail.creator_scene` + `available_scenes`
- `CreatorRef` 不增加 scene（任务级单场景）；直播详情 URL 放在 `verified_homepage`。

### 2.3 两平台采集实现差异

| 维度 | 巨量星图直播 | 磁力聚星直播 |
|---|---|---|
| 入口 | `/ad/creator/market/live` | `#/star_plaza/live` |
| 检索 | 同一 `search_for_author_square`，`scene_param.search_scene=2/display_scene=5` 等 | 同一 `/rest/web/star/list`，`taskType=4`、`pathSource=no_filter_live|search_live` |
| 身份 | `authors[].star_id` | `starList[].userId`（`starId` 另存） |
| 详情 | `author/douyin/{star_id}/{video_type}` | `live-promotion/star/{starId}` |
| 详情接口 | `get_author_live_statistics` 等 | `star/starProfile`、`commerce/live`、`star/listPortrait` 等 |
| Adapter | 新增 `XingtuLiveAdapter(BrowserAdapter)`，复用 generic actions/profile/module | 新增 `KuaishouJuxingLiveAdapter(KuaishouJuxingAdapter)`，重写搜索体/详情端点 |
| 筛选 | 首版不实现；关键词/ID + 目标数 | 首版不实现；关键词/ID + 目标数 |
| 默认条件 | 需清空「达人报价：品牌营销专场(按小时)」 | 无默认条件 |
| 精选 | 不注册 featured；pipeline_complete 只要求 modules | 同左 |

> 适配器实现以真实 observed 契约为输入；本文不猜测未验证选择器/端点。星图通用动作路径是否足够，阶段二用真实页面小样本先验证 `prepare/search/profile` 再定稿；若不足，再在 `XingtuLiveAdapter` 内补动作，不修改短视频适配器。

### 2.4 场景化目标数量（D6）

| 场景 | 默认 | 最大 | 校验点 |
|---|---|---|---|
| 短视频（现有） | 20 | 保持现状（本次不调整） | 现有表单/DTO/计划校验不变 |
| 直播（新增） | 20 | **70** | `RequirementForm`、`FilterPlan`、`POST /api/tasks`、`CapabilityDTO`、前端输入、P1 expected plan、任务记录 |

实现要求：

- `CapabilityDTO` 增加场景参数：live 返回 `target_count_default=20`、`target_count_max=70`；video 保持现有值。
- `RequirementForm`/`FilterPlan` 的模型校验按 `creator_scene` 分支：live ≤70，video 走原规则。
- `POST /api/tasks` 在 live 场景显式拒绝 >70（`LIVE_TARGET_ABOVE_LIMIT` 或等价可读错误），不能只依赖前端。
- 前端直播表单 `max=70`；短视频表单 `max` 保持服务端返回的现有值。
- P1 `build_expected_plan`/capability 校验必须保留 target；不得因场景切换丢失或扩大目标数。
- 历史任务/短视频任务目标数不受影响。

## 3. 模块与代码改动清单

> 原则：短视频路径零行为变化；直播全部走新分支；新增列/表只增量；共享逻辑仅做必要的场景化。

| # | 修改位置 | 修改原因 | 预期行为 | 对现有功能影响 | 验证方式 |
|---|---|---|---|---|---|
| 1 | `domain.py`：新增 `CreatorScene`；`FilterPlan/RequirementForm/TaskRecord` 增加 `creator_scene` | 任务/计划/表单需要区分场景 | 旧 payload 默认 video；collection 计划与任务一致 | 旧数据默认值兼容 | 单元：旧 payload 反序列化、默认值、非法组合 |
| 2 | `migrations/021_live_square.sql`：`root_tasks.creator_scene`、`creator_snapshots.creator_scene`、`creator_live_current` | 直播数据独立、历史可追溯 | 增量迁移；旧行默认 video | 不改旧表语义/不重写数据 | 迁移集成测试；历史任务/快照查询不变 |
| 3 | `runtime.py`：`UnitConfig.for_scene`、`live_registry_path` | 同一单元按场景选契约 | live 缺契约 fail closed；不回落 video | 现有 `for_platform` 保持 | 单元：绑定/缺失/禁用分支 |
| 4 | `product_api.py`：`/api/platforms` scenes、capabilities scene、tasks scene、library scene、live-update 路由 | 前端场景化 API；旧客户端默认 video | additive，默认不变 | 不传 scene 的旧请求行为不变 | API 单元/契约测试 |
| 4A | 场景化目标上限：`CapabilityDTO`/`RequirementForm`/`FilterPlan`/`POST /api/tasks`/前端 max | D6：直播最大 70，两平台统一 | live 1—70；video 保持现状；71 拒绝 | 短视频目标/分页不变 | 单元/API/前端 + 真实 70 任务 |
| 5 | `intake_worker.py`/`intake.py`：按 `(platform, scene)` 选 registry；计划携带 scene | P1 直播能力/版本正确 | 直播计划校验直播能力；视频不变 | 视频路径不受影响 | 单元：场景 registry 选择、版本校验 |
| 6 | `worker.py`：按 `task.creator_scene` 选 live registry；checkpoint 版本 | 直播任务加载直播契约 | 缺契约等待资源；不静默降级 | 视频任务仍走原 registry | 单元/集成：worker 分支 |
| 7 | `adapter_factory.py` + 新 `XingtuLiveAdapter`/`KuaishouJuxingLiveAdapter` | 直播检索/详情与短视频不同 | 直播只调用直播端点/字段 | 短视频 Adapter 不改行为 | 单元/契约：请求体/身份/字段；真实小样本 |
| 8 | `repository.persist_creators`：按 scene 分支 | 直播不得写短视频 projection/current | live 写 live current + scene snapshot；video 原路径 | 视频写入不变 | 集成：两场景并发/先后写入；DB 断言 |
| 9 | `repository` 完整性：`pipeline_complete` 一般化精选条件 | 直播无精选也能完成 | 有精选才要求；无精选只看 modules | 星图视频仍要求两组；聚星视频同现状 | 集成：星图/聚星/直播三种 |
| 10 | `product_queries.py`：直播读模型；聚星短视频读模型加 `creator_scene='video_square'` | 防止直播-only 达人出现在短视频库 | 直播/短视频列表互不污染 | 星图视频读模型不变；聚星视频只读视频快照 | 集成：A/B/C 场景 + 读接口 |
| 11 | `creator_update.py` + 新 `live_update.py`：直播更新服务 | 现有更新仅星图/视频 | 新接口创建 live manual_update；无 schedule 行 | 视频更新零改动 | 单元/集成：幂等/在途/失败不清空 |
| 12 | 前端 `types.ts/api.ts/pages.tsx/App.tsx/fieldCatalog.ts` | 场景选择、任务中心、达人库、详情、更新 | 默认短视频；直播独立视图 | 短视频页面默认不变 | 前端 vitest + 真实浏览器回归 |
| 13 | 契约/配置：两份 live verified（阶段二）、Flag、单元 live path | 直播能力门禁 | 未启用时禁用，不创建任务 | 现有平台开关不变 | 契约/配置/API 测试 |
| 14 | 测试：单元/契约/集成/E2E/前端 | 覆盖新增场景与回归 | 直播闭环 + 视频回归 | — | 第 8 节 |

## 4. 任务类型、调度与执行单元

- 不新增 `TaskKind`；直播采集复用 `collection`，直播更新复用 `manual_update`。
- `scheduled_update` 永不用于直播；直播不创建 `creator_update_schedule` 行，`scheduler_tick` 零改动。
- 根任务仍带 `platform`，新增 `creator_scene`；任务中心筛选/展示基于这两列。
- 单元选择继续 `select_collection_unit(platform)`；同平台直播/短视频共用单元、并发 1、串行；跨平台并行不变。
- Worker `config.for_scene(platform, scene)` 只切换 registry 路径；账号/Profile/线路/浏览器/租约机制不变。
- checkpoint 的 `profile_module_keys`/versions、`featured_collection_types` 来自 live registry；历史任务 checkpoint 不变。
- continue/backfill/retry：沿用现有语义；直播无精选时 `featured_status=NOT_ATTEMPTED`，前端隐藏精选。
- `pipeline_complete` 由「星图固定要求两组」改为「当 `featured_collection_types` 非空时要求两组全部完成」；星图直播契约 `featured=[]` 时只看 modules；星图/聚星短视频契约仍注册原有精选，行为不变。

## 5. 数据库设计

### 5.1 ER 关系

```text
platform_creators (creator_id, platform, platform_creator_id, projection)
  1 ── N creator_snapshots (snapshot_id, creator_id, root_task_id, creator_scene, payload)
  1 ── 1 creator_live_current (creator_id, platform, platform_creator_id,
                              latest_snapshot_id, live_metrics jsonb, ...)
  1 ── N task_creators (root_task_id, creator_id, first_position, valid, latest_snapshot_id)
root_tasks (root_task_id, platform, creator_scene, task_kind, state, ...)
```

- 身份仍由 `(platform, platform_creator_id)` 唯一。
- 短视频 current（`douyin_xingtu_creator_current`）与 `platform_creators.projection` 保持原语义。
- 直播 current 新表，只存直播；不重复存短视频字段。
- `creator_snapshots` 增加场景列；历史行默认 `video_square`；不可变触发器不变。

### 5.2 迁移草案（021，阶段二才执行）

```sql
-- 021_live_square.sql
ALTER TABLE root_tasks
  ADD COLUMN creator_scene text NOT NULL DEFAULT 'video_square'
  CHECK (creator_scene IN ('video_square','live_square'));
CREATE INDEX root_tasks_platform_scene_state_created
  ON root_tasks(platform, creator_scene, state, created_at DESC, root_task_id DESC);

ALTER TABLE creator_snapshots
  ADD COLUMN creator_scene text NOT NULL DEFAULT 'video_square'
  CHECK (creator_scene IN ('video_square','live_square'));
CREATE INDEX creator_snapshots_scene_history
  ON creator_snapshots(creator_id, creator_scene, created_at DESC, snapshot_id DESC);

CREATE TABLE creator_live_current (
  creator_id uuid PRIMARY KEY REFERENCES platform_creators(creator_id),
  platform text NOT NULL CHECK (platform IN ('douyin_xingtu','kuaishou_juxing')),
  platform_creator_id text NOT NULL,
  platform_star_id text,
  latest_snapshot_id uuid REFERENCES creator_snapshots(snapshot_id),
  display_name text,
  avatar_uri text,
  gender text,
  province text,
  city text,
  creator_type_label text,
  industry_labels jsonb NOT NULL DEFAULT '[]',
  content_theme_labels jsonb NOT NULL DEFAULT '[]',
  mcn_name text,
  followers_count numeric,
  followers_raw text,
  followers_is_approximate boolean NOT NULL DEFAULT false,
  live_metrics jsonb NOT NULL DEFAULT '{}',
  profile_complete boolean NOT NULL DEFAULT false,
  pipeline_complete boolean NOT NULL DEFAULT false,
  collected_field_count integer NOT NULL DEFAULT 0,
  failed_field_count integer NOT NULL DEFAULT 0,
  field_sources jsonb NOT NULL DEFAULT '{}',
  data_updated_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(platform, platform_creator_id)
);
CREATE INDEX creator_live_current_updated
  ON creator_live_current(platform, data_updated_at DESC NULLS LAST, creator_id);
CREATE INDEX creator_live_current_followers
  ON creator_live_current(platform, followers_count);

INSERT INTO schema_migrations(version) VALUES(21);
```

说明：

- `live_metrics` 保存平台原生字段 envelope：`{field_key, value, raw_value, unit, period_label, status, source_kind, source_contract, path_ref, observed_at, scope}`。
- 列表/详情所需的高频数值（粉丝、近期场次、ACU/PCU、预期观看/最高在线/CPM）可以在阶段二按真实 PRD 需要增加显式列；不在阶段一预建未验证列。
- `platform_star_id` 供聚星 `live-promotion/star/{starId}` 详情/更新使用；星图可为空（star_id = platform_creator_id）。
- 迁移只加列/表/索引，不重写历史业务数据；回滚 = 回退代码 + 保留新表（旧代码不读）。
- 备份：执行前 `pg_dump`；与 020 相同的增量审查流程。

### 5.3 数据隔离与身份关联

| 场景 | 写入 | 读取 | 更新 |
|---|---|---|---|
| A 只有短视频 | 原路径 | 原短视频库/详情 | 原视频更新 |
| B 只有直播 | `platform_creators` + live snapshot + `creator_live_current` | 直播库/直播详情 | 直播更新 |
| C 两种都有 | 同一 `creator_id`；两套 snapshot/current；不写 projection | 两个场景各自列表/详情；`available_scenes` 切换 | 两套独立更新接口 |
| D 跨平台同 ID/昵称 | `(platform, platform_creator_id)` 隔离 | 平台筛选隔离 | 平台隔离 |

**写入分支（`persist_creators`）**：

```text
if task.creator_scene == LIVE_SQUARE:
    insert snapshot(creator_scene=live_square)
    update task_creators
    write creator_live_current (via LiveCreatorLibraryWriter)
    # 跳过 platform_creators.projection 更新
    # 跳过 douyin_xingtu_creator_current 同步
else:
    existing path unchanged
```

**读取分支**：

- 星图视频库：`douyin_xingtu_creator_current`（不变）。
- 聚星视频库：`platform_creators.projection` + **`creator_scene='video_square'` 的最新快照**（必须加）。
- 直播库：`creator_live_current` + `creator_scene='live_square'` 的最新快照。
- 任务内达人：`task_creators.latest_snapshot_id`（任务单场景，天然隔离）。
- 报价/精选/作品/历史：继续只读短视频表；直播详情不调用这些接口。

## 6. 采集与解析设计

### 6.1 星图直播

- 新增 `XingtuLiveAdapter(BrowserAdapter)`：
  - `prepare`：进入 `/ad/creator/market/live`；校验会话；清空默认条件（「清空」按钮）；填写关键词/ID；触发搜索；`_search_operation` 复用。
  - `search`：复用基类 page_fetch 逻辑；live 契约注册 `search_for_author_square` 请求与 `pagination.*`。
  - `profile`/`collect_module`：复用基类；live 契约注册详情 URL 模板、模块选择器/请求。
  - 不调用 `apply_xingtu_filters`（首版无筛选）。
- live 契约必须登记：
  - `search.entry_url`、`session.business_urls`、`search.reset_actions`（清空默认条件）、`search.apply_actions`（填关键词+搜索）、`search.readback`（关键词回读）、`search.requests`（live 请求匹配，含 scene_param/搜索参数）、`search.candidates_path=authors`、`id_path=star_id`、`homepage_template`、`pagination`；
  - `modules`（`basic` + `live_performance` 等）与字段路径；
  - 不注册 `featured`；
  - `page_fetch_max_verified=6`：阶段一已验证 page 2；阶段二真实核验 page 5/6（各 20 条、0 重复）。真实数据存在无效/无直播候选人，6 页（120 位候选）才足以稳定凑满 70 位有效达人；page 7+ 仍未验证并在契约 coverage_gaps 披露。
- 列表级 `live_sn_*` 与详情级「不限」口径分别登记 source/scope；首版详情页以详情接口为准，列表列显示对应详情字段或明确标注口径。

### 6.2 聚星直播

- 新增 `KuaishouJuxingLiveAdapter(KuaishouJuxingAdapter)`：
  - `_build_search_body`：`taskType=4`，`pathSource=no_filter_live`（默认）或 `search_live`（`userName`），`currentPage/pageSize`；首版只支持关键词/ID，无其他筛选。
  - `CreatorRef`：`platform_creator_id=userId`，`verified_homepage=.../live-promotion/star/{starId}?openBy=user`。
  - `search`：复用基类 `_post_json`/响应解析，但 `starList[].userId` 身份；校验 `result=1`、`currentPage`、`total`。
  - `profile`：进入 live-promotion 详情；校验身份（userId/starId）与会话。
  - `collect_module`：live 端点：
    - `basic`：`/rest/web/star/starProfile` + `/rest/web/star/starWorksInfo`（基础+重点数据）；
    - `live_performance`：`starProfile`/`starWorkReport` live 字段；
    - `commerce`：`/rest/web/commerce/live`；
    - `audience`：`/rest/web/star/listPortrait`；
    - `index`：`/rest/web/starIndex/*`、`/rest/web/evaluation/star/*`（可选）。
  - 不改 `KuaishouJuxingAdapter` 的视频路径；共享 `_post_json`/`_field`/`_numeric`/`_module` 通过继承复用。
- 零值/空对象语义：
  - `commerce/live` 全 0 → `NO_DATA`（页面显示 -），不是真实 0；
  - `liveAvgLikeRate=null` → NO_DATA；
  - `starProfile.liveAvgPeopleNum` 与列表 `liveAvgPeopleNum` 分别登记，不默认相等。

### 6.3 字段与完整性

- 每个字段保留原文/单位/周期/source/path/observed_at。
- `profile_complete` = live registry 注册模块全部完成；`pipeline_complete` = profile_complete（无 featured）。
- 失败/无权限/空态分别记录；不因单字段失败清空旧值。
- 封面：直播详情未验证封面存储，首版不下载直播封面；头像可复用现有 URI（不新增下载）。
- 联系方式：星图介绍/名片接口、聚星名片/介绍中的联系方式一律不采集。

## 7. 数据流

### 7.1 直播采集

```text
用户提交 (platform, live_square, keyword/ID, target)
→ capability_version = live registry capabilities.version
→ requirements.payload + root_tasks(platform, creator_scene)
→ P1: 选 live capabilities，生成 FilterPlan(creator_scene=live_square)
→ promote: unit = select_collection_unit(platform)
→ Worker: config.for_scene(platform, live_square) → live registry
→ live adapter: 入口/清空默认条件/关键词/搜索/详情
→ persist: snapshot(scene=live) + creator_live_current
→ 任务计数/终态
→ 达人库 scene=live_square / 直播详情
```

### 7.2 直播手动更新

```text
达人详情（直播场景）[手动更新直播资料]
→ POST /api/creator-library/{creator_id}/live-updates (Idempotency-Key)
→ CreatorLiveUpdateService：校验身份/直播 current；advisory lock；查在途
→ root_tasks(task_kind=manual_update, creator_scene=live_square, targets)
→ 现有任务中心/单元/Worker
→ live adapter.profile + collect_module（不 search）
→ snapshot(scene=live) + live current
→ 状态/最近成功/失败；不写 schedule
```

### 7.3 读取

```text
/api/creator-library?scene=live_square&platform=...
→ creator_live_current + live snapshot
→ 平台原生 field labels/units（live field catalog / contract modules）
→ 前端 LiveCreatorDetailView
```

## 8. API 变更（additive）

| 接口 | 变更 | 兼容性 |
|---|---|---|
| `GET /api/platforms` | 增加 `scenes[]`（scene/label/enabled/capability_status/contract_version/disabled_reason） | 旧字段保留 |
| `GET /api/platforms/{platform}/capabilities?scene=` | 默认 `video_square`；live 走 live registry；live `target_count_max=70` | 旧请求不变 |
| `POST /api/tasks` | `RequirementForm.creator_scene` 默认 video；直播校验 live capability | 旧表单不变 |
| `GET /api/tasks?scene=` | 可选过滤；`TaskSummary.creator_scene` | 旧请求默认全部/旧任务 video |
| `GET /api/tasks/{id}` | `TaskDetail.creator_scene` | additive |
| `GET /api/creator-library?scene=` | 默认 video；live 走直播读模型 | 旧请求不变 |
| `GET /api/creator-library/{id}?scene=` | 默认 video；返回 `creator_scene/available_scenes` 与直播字段 | 旧响应字段保留 |
| `GET /api/creator-library/{id}/update` | 不变（视频更新状态） | 不变 |
| `POST /api/creator-library/{id}/updates` | 不变（视频更新） | 不变 |
| `POST /api/creator-library/{id}/live-updates` | 新增直播更新 | 新 |
| `GET /api/creator-library/{id}/live-update` | 新增直播更新状态 | 新 |
| `GET /api/platforms/{platform}/profile-field-catalog?scene=` | 默认 video；live 返回直播字段显示名/单位 | 旧请求不变 |

说明：直播详情不使用 `quotes/contents/videos/history`（视频专属）；前端在 live 场景不请求这些接口。

## 9. 前端设计

| 文件/组件 | 改动 | 说明 |
|---|---|---|
| `frontend/src/types.ts` | `CreatorScene`、`scenes`、`creator_scene`、直播 detail metrics、live update 类型 | additive |
| `frontend/src/api.ts` | capabilities/platforms/tasks/library 加 scene 参数；live update 调用 | 默认 video |
| `frontend/src/pages.tsx` NewTaskPage | 平台后增加场景选择；直播表单（关键词/目标数）；场景切换重置幂等键/条件 | 短视频表单不变 |
| `pages.tsx` TasksPage | 场景徽标/筛选 | 默认全部 |
| `pages.tsx` TaskDetailPage | 场景展示；直播计数隐藏精选；达人列表进入对应详情 | 视频不变 |
| `pages.tsx` CreatorLibraryPage | 业务数据切换（短视频/直播）；直播行指标/完整度 | 默认短视频 |
| `pages.tsx` CreatorLibraryDetailPage | scene 参数/路由；直播布局 `LiveCreatorDetailView`；available_scenes 切换 | 视频详情不变 |
| `pages.tsx` CreatorDetailPage（任务内） | 根据任务场景渲染直播/视频快照详情 | 快照 payload 不变 |
| `pages.tsx` 更新面板 | 新增直播更新按钮/状态；保留视频更新 | 两按钮独立 |
| `frontend/src/liveFieldCatalog.ts`（新） | 两平台直播字段显示名/单位/分组 | 依据 observed 契约 |
| `frontend/src/App.tsx` | 新增 `/creators/:creatorId/live`（显式直播详情）；任务内详情沿用原路由 | 旧路由不变 |
| `styles.css` | 复用现有 panel/section/badge；只加少量直播分组样式 | 不新设计系统 |

## 10. 影响分析摘要

详见[影响范围与兼容性分析](LIVE-02-compatibility-impact.md)。关键点：

- 短视频采集/筛选/快照/详情/更新/定时更新：**零行为变化**（默认 video；旧读模型不变）。
- 聚星短视频库：唯一必要的共享读模型修改是「最近快照必须限定 video_square」，否则直播-only 达人会污染短视频库。
- `pipeline_complete`：一般化精选条件；星图/聚星短视频仍注册原精选，回归必须通过。
- 执行单元：不新增、不改并发；仅增加 live registry 路径。
- API：全部 additive，默认 video。
- 数据：只加列/表；不删除/重写历史。

## 11. 风险与最小化处理

| 风险 | 影响 | 规避/处理 |
|---|---|---|
| 星图直播通用动作不足 | live 采集无法复用基类 | 阶段二先用真实小样本验证 `prepare/search/profile`；必要时只扩 `XingtuLiveAdapter`，不改基类 |
| 聚星 live 详情端点/字段与 observed 不一致 | 解析失败/部分完成 | 以 observed 契约 + 小样本先验证；未知字段留 NO_DATA；失败不清空 |
| 直播列表/详情口径不同（live_sn_*） | 指标误用 | 字段级 scope/period/source；UI 标注「星图商单」/「不限」；不合并 |
| 空对象/0 值混淆 | 显示假 0 | 平台空对象/页面 `-` → NO_DATA；仅有真实值时显示 0 |
| 同一达人两场景写入顺序 | 短视频库被污染 | scene 过滤 + live 不写 projection/星图 current；DB 集成断言 |
| 精选必填规则回归 | 短视频终态变化 | 一般化条件 + 星图/聚星短视频全回归 |
| 直播更新与视频更新并发 | 浏览器/任务互斥 | 同一单元串行；两服务独立幂等；不写同一 schedule |
| 直播-only 达人进入短视频库 | 数据错误 | 聚星视频读模型加 scene 过滤；星图 current 不写 |
| 平台默认条件遗漏 | 采集结果偏差 | 星图 live 清空默认条件；契约登记 reset/readback；阶段二验证 |
| 数据库迁移 | 旧数据风险 | 增量列/表；备份；迁移集成测试；回滚方案 |

## 12. 每项改动的验证方式（摘要）

| 改动 | 离线验证 | 真实验证（阶段三） |
|---|---|---|
| 场景模型/契约选择 | 单元：默认值/旧 payload/缺契约 fail closed | 前端场景切换、任务平台/场景正确 |
| 迁移 | 集成：迁移 021 + 历史查询 | 真实库迁移后旧任务/达人库/详情不变 |
| 适配器 | 单元/契约：请求体、身份、字段映射 | 两平台各 1 位真实直播采集 |
| 持久化隔离 | 集成：A/B/C/D 写入 + DB 断言 | 真实直播任务后 DB 无投影污染 |
| 读模型 | 集成：live 列表/详情；聚星视频不出现直播-only | 达人库切换/详情字段与平台一致 |
| 更新 | 单元/集成：幂等、在途、失败不清空、无 schedule | 两平台真实手动更新；视频更新回归 |
| 任务中心 | 单元/E2E：scene 过滤/展示 | 真实任务中心/详情 |
| 执行单元 | 集成/现有 E2E | 同平台串行、跨平台并行、无新增单元 |
| 短视频回归 | 全量单元/契约/集成/E2E/前端 | 两平台短视频小样本采集/详情/更新 |
| 定时更新 | 代码/配置/DB 只读检查 | 确认无直播 schedule/不运行直播定时任务 |

## 附录 A：observed 契约与字段清单

- [巨量星图直播 observed 契约](../../contracts/douyin_xingtu.live.observed.json)
- [磁力聚星直播 observed 契约](../../contracts/kuaishou_juxing.live.observed.json)
- [真实页面调查证据](../evidence/LIVE-02-live-square-investigation.md)（字段路径/单位/已验证状态）

## 附录 B：阶段二实施顺序建议

1. 迁移 021 + 领域 scene 模型 + 单元/产品 registry 选择（离线）。
2. 两平台 live 契约草案 + 适配器/解析（离线 + 真实小样本逐平台）。
3. 持久化/读模型/API/前端（离线 + 隔离集成）。
4. 直播更新服务/接口/前端（离线 + 隔离集成）。
5. 短视频全回归（离线）。
6. 真实浏览器端到端与回归（阶段三）。
7. 证据/卡片/索引/报告。

> 阶段二开始前必须由用户确认 PRD 的待裁决项（筛选范围、目标/分页、更新入口、详情形态、身份策略等）。