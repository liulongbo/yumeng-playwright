# 现有功能影响范围及兼容性分析（LIVE-02）

状态：已批准（2026-11-04），第二阶段开发中
版本：v0.1（2026-11-04）
关联：[PRD](../prd/LIVE-02-live-square-collection.md)、[技术方案](LIVE-02-live-square-technical-design.md)、[测试用例](../evidence/LIVE-02-test-cases.md)

## 1. 结论摘要

| 结论 | 说明 |
|---|---|
| 总体影响 | **可控、增量**；短视频路径默认 `video_square`，无行为变化；直播走新分支 |
| 必须修改的共享点 | ① `pipeline_complete` 的精选条件一般化；② 聚星短视频读模型的最近快照加 `creator_scene='video_square'` 过滤 |
| 不需要改的点 | 任务中心架构、Temporal Workflow、执行单元/队列/并发、账号/Profile/线路、定时更新调度 |
| 数据风险 | 只加列/表/索引；旧行默认值；不重写历史；迁移前备份 |
| 兼容策略 | API 全部 additive，不传 `scene` 默认短视频；旧客户端/旧页面不变 |
| 最大技术不确定 | 星图直播通用动作路径是否足够、聚星直播详情字段/端点完整性、直播列表与详情口径差异 |
| 建议 | 阶段二按「MVP 最小闭环 + 严格回归」推进；阶段三真实浏览器验收后给 GO/CONDITIONAL GO/NO-GO |

## 2. 十项保护能力逐项分析

| # | 现有能力 | 影响级别 | 影响说明 | 缓解/兼容措施 | 回归方式 |
|---|---|---|---|---|---|
| 1 | 巨量星图短视频筛选与采集 | **无行为变化** | 默认 scene=video_square；短视频 registry/Adapter/请求体/字段不变 | 不改 `BrowserAdapter` 视频路径；live 用新子类 | 全量单元/契约/集成 + 星图短视频 1 位小样本 |
| 2 | 磁力聚星短视频筛选与采集 | **无行为变化** | 视频请求体/详情端点/字段不变；仅读模型最近快照加 scene 过滤（视频数据本来满足） | 过滤条件对旧数据无影响；新增 live 子类不改视频类 | 聚星短视频 1 位小样本 + 读模型集成 |
| 3 | 现有达人库及短视频详情 | **无行为变化** | 达人库默认短视频；短视频 current/详情查询不变 | API 默认 scene；前端默认短视频；直播数据不写短视频 current | 达人库/详情基线对比 + 隔离集成 |
| 4 | 现有短视频手动更新 | **无行为变化** | `CreatorUpdateService`/schedule/接口不变；直播更新新服务/新接口 | 不修改 `creator_update.py` 现有路径；新服务不写 schedule | 星图视频更新 1 次真实回归 + 单元 |
| 5 | 现有短视频定时更新 | **无行为变化** | `scheduler_tick`/`creator_update_schedule` 零改动；直播不创建 schedule 行 | 直播更新服务不引用 schedule；代码审查 + DB 无直播行 | 代码/配置审查 + DB 只读 + 受控 tick |
| 6 | 统一任务中心 | **增量兼容** | 任务中心增加 scene 字段/筛选/展示；状态机/Workflow/操作不变 | `TaskSummary/TaskDetail` additive；默认视频；旧任务 scene 默认 video | 任务中心/详情/操作 E2E + 旧任务读取 |
| 7 | 执行单元及平台绑定 | **无架构变化** | 不新增单元/队列/Profile；仅单元配置增加 live registry 路径；同平台互斥不变 | `for_scene` 只切 registry；缺失 fail closed | 单元/绑定测试 + 同平台串行/跨平台并行 |
| 8 | 任务状态同步 | **无行为变化** | 状态机、计数、失败分类、Temporal 信号不变 | 直播沿用同一状态机；仅新增 scene 字段 | 任务状态 E2E + 旧任务回放/读取 |
| 9 | 数据库历史数据及快照 | **增量兼容** | 只加列/表/索引；旧快照默认 video；不重写；不可变触发器不变 | 迁移 021 前备份；回滚保留新表 | 迁移测试 + 历史任务/快照对比 + 恢复演练 |
| 10 | 双平台任务并发策略 | **无行为变化** | 不新增单元；同平台串行、跨平台并行不变；同平台直播/视频共用单元 | 不修改 acquire/release/队列/租约 | 双平台并发/同平台串行真实回归 |

## 2A. 场景化数量上限（D6）

- 直播：默认 20、最大 70（两平台统一）；71 必须由前端与后端同时拒绝。
- 短视频：**不调整**现有上限、分页逻辑、有效达人判定和 70 位已验证能力；本次只新增 live 分支。
- 历史任务/既有短视频任务：目标数、进度、快照、继续/重试语义不变。
- 风险：若把 live 70 上限错误地套到 `RequirementForm/FilterPlan` 全局，会缩小短视频现有能力；实现必须按 `creator_scene` 分支，并用单元测试锁定 video 默认规则。

## 3. 代码级影响

| 文件/模块 | 影响 | 风险 | 处理 |
|---|---|---|---|
| `domain.py` | 新增 scene 枚举/字段；`pipeline_complete` 条件 | 旧 payload 反序列化；终态回归 | 默认值 + 单元测试 + 三平台回归 |
| `runtime.py` | 新增 live registry path/for_scene | 选错契约/回落视频 | 缺失 fail closed；逐场景测试 |
| `worker.py` | 按 scene 选 registry；校验 | 直播任务误用视频契约 | 断言 scene/contract 版本 |
| `intake.py`/`intake_worker.py` | 按 (platform, scene) 选能力 | P1 生成视频计划 | 直播 capability 版本校验；单元 |
| `adapter_factory.py` + 新 Adapter | 直播采集/解析 | 视频 Adapter 被误改 | 新类 + 视频类零改动；代码审查 |
| `repository.py` persist | scene 分支；不写 projection/星图 current | 直播污染视频库 | DB 断言；A/B/C 集成测试 |
| `repository.py` 完整性 | 精选条件一般化 | 星图/聚星视频终态变化 | 全量短视频回归 |
| `product_queries.py` | 直播读模型；聚星视频 scene 过滤 | 直播-only 进入视频库；视频详情混数据 | 集成 + 真实页面 |
| `creator_update.py` + 新 live update | 直播更新；视频零改动 | 在途/幂等/失败覆盖 | 单元/集成 + 真实更新 |
| 前端 `pages.tsx/types.ts/api.ts` | 场景选择/任务中心/达人库/详情/更新 | 短视频页面回归 | 前端 vitest + 真实浏览器基线对比 |

## 4. API 兼容性

| 变更 | 兼容性 | 说明 |
|---|---|---|
| `POST /api/tasks` 新增可选 `creator_scene` | 向后兼容 | 缺省 video；旧表单不变 |
| `GET /api/platforms` 增加 `scenes[]` | 向后兼容 | 旧字段保留；旧前端忽略新增字段 |
| `GET /api/platforms/{platform}/capabilities?scene=` | 向后兼容 | 缺省 video |
| `GET /api/tasks?scene=` / `TaskSummary.creator_scene` | 向后兼容 | 缺省不过滤/video；旧客户端忽略 |
| `GET /api/creator-library?scene=` / detail scene | 向后兼容 | 缺省 video；旧页面不变 |
| 新增 `POST/GET .../live-updates` | 新增 | 不影响现有 `/updates` |
| `profile-field-catalog?scene=` | 向后兼容 | 缺省 video |
| 响应新增字段 | additive | 旧客户端可忽略；无删除/重命名 |

## 5. 数据库与数据兼容

### 5.1 变更

- `root_tasks.creator_scene`（NOT NULL DEFAULT `video_square`，CHECK）。
- `creator_snapshots.creator_scene`（NOT NULL DEFAULT `video_square`，CHECK）。
- 新表 `creator_live_current`（直播专用）。
- 索引：任务平台/场景/状态/时间；快照 creator/scene/时间；live current 平台/更新时间/粉丝。
- 不修改现有列类型/约束/触发器；不重写历史行。

### 5.2 兼容性

- 旧任务：`creator_scene=video_square`，读取/展示/更新行为不变。
- 旧快照：默认 video；短视频读模型只看/仍匹配视频数据。
- 旧达人：`platform_creators.projection` 不变；星图 current 不变。
- 聚星视频读模型：新增 scene 过滤后，旧数据（video）仍匹配；直播数据被排除。
- 直播-only 达人：不进入短视频库（无视频快照/current）。
- 同达人两场景：共享 `creator_id`，数据分离。

### 5.3 迁移与回滚

- 迁移 021 只加列/表/索引；执行前 `pg_dump`；在隔离库先跑迁移 + 历史查询回归。
- 回滚：回退代码即可；新表/列保留不影响旧代码；不执行 `DROP`（除非单独授权）。
- 迁移失败：事务回滚；不修改历史数据。
- 备份/恢复演练：沿用 OPS/JUXING-MAIN-01 的 `pg_dump` + 隔离恢复流程。

## 6. 契约兼容性

- 现有 `contracts/douyin_xingtu.verified.json`、`contracts/kuaishou_juxing.verified.json` **不改**（除非阶段二发现必须修正的既有缺口，另立任务）。
- 新增两份 live 契约；阶段一仅 observed（不加载、不启用）。
- live 契约独立 `contract_version/capability_version/adapter_version`；checkpoint 记录对应版本。
- 旧任务 checkpoint 版本不变；升级 live 契约不重写旧任务。
- 契约发布门槛沿用 `require_enabled(live=True)`：必须有真实 live 证据；observed 不得执行。

## 7. 执行单元、并发与资源

| 项 | 现状 | 本次 |
|---|---|---|
| 单元 | `unit-local-mac-02`（星图）、`unit-local-mac-03-juxing`（聚星） | 不新增 |
| 队列 | `xingtu-unit-<unit>` | 不新增 |
| 并发 | 每单元 1 | 不变 |
| 同平台 | 串行、互斥 | 直播/视频共用单元，仍串行 |
| 跨平台 | 并行 | 不变 |
| Profile/账号/线路 | 各单元独立 | 不变 |
| 定时更新调度 | update-scheduler | 不变；直播不进入 |

## 8. 任务、检查点与工作流兼容

- 根任务仍是 `root_task_id` + `TaskRecord` payload；新增 scene 字段默认 video，旧 payload 可反序列化。
- Temporal Workflow `CollectF04F05V1` 不改；Activity 输入仍是 root_task_id；scene 从 DB 任务读取。
- Checkpoint 结构不新增必需字段；live registry 的 module/featured 版本写入已有字段。
- 旧 workflow 历史重放不需要新字段；新代码在旧历史上按旧数据读取。
- 失败/重试/继续/取消语义不变；直播无精选时 `featured_status=NOT_ATTEMPTED`，不阻挡完成。

## 9. 读模型兼容

| 读模型 | 变更 | 兼容性 |
|---|---|---|
| 星图短视频库/详情 | 不改 | 旧数据/页面一致 |
| 聚星短视频库/详情 | 最近快照加 `creator_scene='video_square'` | 旧视频数据仍匹配；直播数据被排除 |
| 任务内达人 | `task_creators.latest_snapshot_id` 不变 | 任务单场景，天然隔离 |
| 短视频历史/报价/精选/作品 | 不改 | 旧接口不变 |
| 直播库/详情 | 新增 | 新接口/新视图 |
| 任务中心 | 增加 scene 字段/筛选 | 默认兼容 |

## 10. 前端兼容

- 短视频页面默认行为不变；新增场景选择仅在新建任务页，默认短视频。
- 达人库默认短视频；直播是显式切换/路由。
- 任务中心默认全部；增加场景筛选/徽标。
- 视频详情/更新按钮/精选/报价不变；直播详情是独立视图。
- 旧 URL（`/creators/:id`、`/tasks/:id/creators/:id`）保持视频语义；新增 `/creators/:id/live`。
- 真实浏览器回归必须覆盖：登录、短视频新建、短视频任务/详情、达人库、视频更新、任务中心。

## 11. 定时更新专项

- `creator_update_schedule` 结构不改；`scheduler_tick`/`update-scheduler` 不改。
- 直播采集/更新服务不插入 schedule 行；不设置 `next_due_at`。
- 直播手动更新不进入定时池；未来如要支持直播定时更新，另立任务、另做迁移/调度设计。
- 验证：代码审查 + DB 查询（无直播 schedule）+ 受控视频 tick 回归。

## 12. 风险与待确认

| 风险 | 可能性 | 影响 | 处理 |
|---|---|---|---|
| 星图直播动作路径无法复用 | 中 | 延期 | 阶段二先小样本验证；必要时扩子类 |
| 聚星直播详情端点/字段缺失 | 中 | 部分字段不可用 | 以 observed + 小样本为准；NO_DATA；PRD 缩减字段 |
| 直播列表/详情口径差异 | 高 | 指标误用 | 字段级 scope/period/source；不合并；UI 标注 |
| 空值/0 混淆 | 中 | 错误展示 | 显式状态；真实 0 才显示 0 |
| 直播数据污染短视频库 | 中 | 数据错误 | scene 过滤 + 不写 projection；DB 断言 |
| 精选规则一般化回归 | 中 | 短视频终态变化 | 全量短视频回归；必要时直播专用分支 |
| 迁移/回滚 | 低 | 数据风险 | 备份 + 隔离验证 + 增量迁移 |
| 真实平台权限/挑战 | 中 | 验收阻塞 | 如实 BLOCKED；不绕过；必要时用户提供授权账号 |
| 时间/配额 | 中 | 验收不完整 | 小样本、分阶段、记录覆盖缺口 |

## 13. 回归矩阵（必做）

| 回归项 | 离线 | 真实浏览器 | 通过标准 |
|---|---|---|---|
| 星图短视频采集（1 位小样本） | 单元/契约/集成 | 是 | 任务完成/部分完成；字段/详情一致 |
| 聚星短视频采集（1 位小样本） | 单元/契约/集成 | 是 | 同上 |
| 短视频达人库/详情 | 集成/前端 | 是 | 与基线一致 |
| 星图视频手动更新 | 单元/集成 | 是 | 更新/快照/状态一致 |
| 任务中心（旧任务/筛选/详情） | 集成/前端 | 是 | 旧任务可读；操作正常 |
| 执行单元并发/互斥 | 集成/E2E | 是 | 同平台串行、跨平台并行 |
| 定时更新 | 代码/DB 只读 | 否（受控只读） | 无直播 schedule；视频调度不变 |
| 历史快照/旧任务读取 | 集成 | 只读 | 数据不变 |

## 14. 上线/验收门槛

- 阶段二离线检查（unit/contract/integration/E2E/frontend/mypy/ruff）通过。
- 迁移 021 在隔离库通过，并在真实库执行前备份。
- 阶段三两平台直播采集/更新真实闭环通过；两平台短视频小样本回归通过。
- 无直播数据污染短视频库；无直播 schedule 行；无新增执行单元/队列。
- 未验证项、失败项、跳过项如实记录；输出 GO / CONDITIONAL GO / NO-GO。

## 15. 结论

本方案对现有短视频能力的影响集中在两处共享逻辑（精选完成条件、聚星视频读模型的 scene 过滤），均可通过回归覆盖；其余为新增列/表/接口/页面和独立直播分支。**在阶段二先验证共享逻辑与真实小样本、阶段三完成双平台真实闭环与短视频回归之前，不宣称生产就绪。**

---

## 附录：LIVE-02F 筛选扩展影响（2026-11-05）

| 范围 | 影响 | 回归 |
|---|---|---|
| 短视频契约/Adapter/请求映射 | 未改 | 单元/契约/集成/E2E/前端全通过；阶段三真实小样本继续有效 |
| 短视频 RequirementForm | 新增可选 `live_filters`，video 场景非空即拒绝；旧 payload 默认空 | 现有表单/接口测试通过 |
| 直播契约 | 升级到 v2，新增筛选字段/映射/禁用原因 | 两平台真实筛选任务通过 |
| 直播 FilterPlan | 新增 live_square 分支；未改视频校验 | 单元/集成通过 |
| 直播 Adapter | 星图 UI 应用/请求校验；聚星 body 构造 | 真实任务通过 |
| 持久化 | 无迁移；计划/checkpoint/快照结构未改 | 集成 DB 验证 |
| 目标/分页/去重 | 未改 | 既有 70 证据 + 本次筛选多页到第 2 页 |
| 旧直播任务 | 契约版本升级；历史只读；升级时无运行中直播任务 | 历史任务查看正常 |
| 聚星地域 | 未登记，前端不展示 | 不产生虚假能力 |

---

## 附录：LIVE-02I 画像互斥修复（2026-11-06）

| 范围 | 影响 | 回归 |
|---|---|---|
| 星图直播契约 | 仅新增 `incompatible_with`/policy pair；请求映射、选项、能力版本不变 | 契约 43、目标单元 28 |
| P1/Adapter | 双画像计划在 P1/Adapter 前置拒绝；错误信息含字段名 | `fdb68678…` FAILED_VALIDATION、0 浏览器 |
| 前端 | 选一侧清空另一侧；历史混合条件提交时策略报错 | 正反向真实 UI 验证 |
| 聚星 | 未改；双画像仍允许 | `948b046c…` COMPLETED 1/1 |
| 历史任务 | `39c37496…` 保持 FAILED；不自动重试/篡改 | DB 重查 |
| 数据库 | 无迁移 | 不适用 |
| 版本 | 不升能力版本，避免历史直播任务版本失效 | 契约/任务版本一致 |
