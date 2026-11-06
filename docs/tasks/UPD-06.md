# UPD-06：巨量星图/磁力聚星短视频与直播定时更新及独立开关

状态：已完成  
更新时间：2026-11-06T15:58:00+08:00  
是否验收：是（隔离库 `xingtu_test_upd06` 真实四组/开关/双场景/取消/重启/回归）；主站 scheduler 按现状保持关闭；生产持续运行、Windows 实机与平台级故障注入列为条件。

## 目标与范围

**目的**：复用现有巨量星图短视频定时更新机制，让两平台短视频/直播四组已入库达人按 `(platform, creator_scene)` 独立建立更新计划、独立启停、独立结算，且不影响现有采集、手动更新、任务中心、执行单元与历史快照。

**包含**：迁移 022（场景维度、四组开关、心跳、聚星短视频定位列）；按 scope 的调度器与组级隔离；worker 启动闸门；所有更新场景的终态 reconcile；聚星定位回填脚本；管理 API 与 `/settings` 页面；全部自动化与真实隔离验收。

**不包含**：四套调度器、独立执行单元/队列/Temporal 工作流、聚星短视频手动更新产品功能、管理后台重做、70 位全量重跑、生产部署/Windows 实机验收、Git 合并。

## 关联与依赖

- 复用：UPD-01/02/04/05、DEC-017/018、DEC-022。
- 平台能力：LIVE-02、LIVE-02G、LIVE-03、KJX-01、DUAL-UNIT-01。
- 设计：[UPD-06 设计](../design/UPD-06-scheduled-update-services.md)；决策：[DEC-022](../decisions/DEC-022-scheduled-update-services.md)。
- 证据：[现状调查](../evidence/UPD-06-investigation.md)、[测试用例与结果](../evidence/UPD-06-test-cases.md)、[真实验收报告](../evidence/UPD-06-acceptance.md)。

## 验收清单

- [x] 迁移 022 保留旧计划行并解释为 `video_square`；复合主键允许同达人双场景、拒绝同场景重复；四组默认值正确。
- [x] 四组 scope 的 target 与 registry 正确：星图直播 6 模块、聚星直播 8 模块、聚星短视频 4 模块、星图短视频原有契约。
- [x] 组内单活跃批次、组间互不阻塞；关闭组不建任务，其他组继续。
- [x] 同达人双场景计划、in-flight、终态推进、快照互不覆盖；真实准备并验证（星图 star_id `7480355375695265829`）。
- [x] `UPDATE_SERVICE_DISABLED` 取消只释放 in-flight，不计失败、不推进 `next_due_at`；重新开启恢复。
- [x] 聚星短视频无定位不纳入；回填脚本 81/81、幂等、不覆盖已有值。
- [x] 管理读模型正确报告开关、心跳、契约可用、统计、最近批次与缺少定位数；无来源字段不虚构。
- [x] API 认证/CSRF/非法场景；前端四行、开关 PUT、离线/生效、最近任务、错误态；真实浏览器 UI 验收。
- [x] 四组真实「到期 → scheduler 建任务 → 对应单元 → 新快照/当前数据 → next_due」全部 PASS。
- [x] 单独关闭星图短视频/聚星直播不影响其他组；关闭时手动更新与普通采集正常；重启开关保持。
- [x] 重复 tick/重启不重复；运行中取消后历史/投影保留且退避符合既有策略。
- [x] 现有单元 449、集成 149（1 skipped）、契约 43、前端 127、构建、mypy 通过；改动文件 ruff 通过。
- [x] 主库备份、迁移 022、回填 81/81；主站应用恢复（API/前端/两 Worker），scheduler 保持关闭。

## 实现记录

- `migrations/022_creator_update_services.sql`：`creator_update_schedule.creator_scene` + 复合主键；`creator_update_service`；`creator_update_scheduler_heartbeat`；`platform_creators.video_homepage`。
- `backend/src/xingtu/creator_update.py`：`UpdateScope`；四组 enrollment/due/target；scene 化 reconcile/status/manual；组级 SAVEPOINT；heartbeat；`enroll_group`；`UPDATE_SERVICE_DISABLED` 释放语义。
- `backend/src/xingtu/creator_update_services.py`：管理读模型、开关写入、审计、effective/available 计算、`target_count` 从 update_targets 推导。
- `backend/src/xingtu/creator_update_backfill.py` + `scripts/backfill_video_homepage.py`：checkpoint 定位回填（dry-run/apply、幂等）。
- `backend/src/xingtu/product_models.py` / `product_api.py`：管理模型与 `GET/PUT /api/update-services`。
- `backend/src/xingtu/product_cli.py`：四 scope registry 解析（主 unit config + binding + env）、单进程多组调度、心跳。
- `backend/src/xingtu/worker.py`：scheduled_update 启动闸门（手动/采集不受影响）。
- `backend/src/xingtu/repository.py`：`scheduled_update_enabled`；终态 reconcile 全场景；`video_homepage` 发布写入。
- `backend/src/xingtu/juxing_adapter.py`：`_ensure_search_page()`，补齐聚星短视频无 plan 定向更新的 search page（真实 A3 首次暴露 `JUXING_SEARCH_PAGE_MISSING` 后最小修复）。
- `frontend/src/updateServices.tsx`、`App.tsx`、`api.ts`、`types.ts`、`styles.css`：管理页、`/settings` 路由、侧栏「自动更新」、四行开关与状态。
- 测试：`test_creator_update_scopes.py`（12）、`test_migrations_022.py`、`test_creator_update_backfill.py`、`test_worker_update_gate.py`、`test_juxing_adapter_v2.py` 新增、`test_product_api.py` 新增、`updateServices.test.tsx`（4），并扩展 `test_creator_update.py`/`test_juxing_persistence.py`。
- 验收脚本：`scripts/acceptance/upd06_isolated_setup.py`（克隆库准备）、`scripts/acceptance/upd06_ui.py`（真实浏览器管理页）。

## 现状调查事实

- 现有调度器代码完整但调查时进程未运行；主库 schema 21、`creator_update_schedule` 201 行/148 到期；两执行单元 READY；聚星 81 位短视频达人定位可从 checkpoint 解析。
- 调查时无双场景达人；通过真实星图直播采集（star_id 关键词）为星图短视频达人补出直播场景，得到同一 `creator_id` 双场景后验证计划/快照隔离。
- 主库迁移后：schema 22；四组开关（星图短视频 on，其余 off）；`video_homepage` 81/81；heartbeat 0 行；scheduler 未启动；主站页面显示 1/4 开启、0 生效、148 到期、无虚构状态。

## 验证证据

- 自动化：unit **449 passed**；integration **149 passed, 1 skipped**（221.59s）；contract **43 passed**；frontend **127 passed**；build 通过；mypy 46 files 通过；改动文件 ruff/format 通过。仓库级 `ruff check scripts` 仍有 3 个未改动的既有 `run_cd05/06/07_acceptance.py` 的 UP031/格式问题，记录为既有缺口。
- 真实 A1–A4、B1–B7、C1–C4、D1–D4、UI1–UI4、F1–F6 的 PASS/任务 ID/数据变化/截图见[真实验收报告](../evidence/UPD-06-acceptance.md)。
- 四组任务：`c8a2f16a…`（星图短视频）、`c278ba50…`（星图直播）、`f39722b3…`（聚星短视频，含同 root 重试）、`ffcd2a5e…`（聚星直播）。
- 双场景：`3502f932…`（只直播）、`7845da9a…`（只短视频）；开关/取消/回归任务 ID 见报告。
- 主库备份 `.runtime/backups/upd06-20261106/xingtu_development.dump`（68MB/498 TOC）。
- 截图：[隔离管理页](../evidence/assets/UPD-06/ui-services.png)、[任务详情](../evidence/assets/UPD-06/ui-scheduled-task-detail.png)、[主站交付态](../evidence/assets/UPD-06/main-ui-services-scheduler-off.png)。

## 交接信息

- 主站 scheduler 未启动，保留调查时行为；需要持续自动更新时由运营启动并逐组开启。启动命令：
  `nohup .venv/bin/xingtu-product update-scheduler --unit-config .runtime/units/local-dev-mac-02.json --batch-size 5 >>.runtime/logs/update-scheduler.log 2>&1 &`
- 三组新增服务默认关闭；完成真实测试后可分别开启；星图短视频开关为 on 但 scheduler 未运行，因此实际未生效。
- 聚星短视频新采集自动写 `video_homepage`；历史行已回填 81/81。
- 未执行：真实平台故障注入（受控取消 + 集成失败用例替代）、Windows 实机、70 位全量重跑（引用既有证据）。
- Git：**未提交、未合并 main、未切换分支、未覆盖**其他会话 LIVE-02G/02H/03 未提交改动。
- 既有 lint 缺口不属于本卡：`scripts/acceptance/run_cd05/06/07_acceptance.py`。

## 状态历史

- 2026-11-06T15:30:00+08:00：建立 → 进行中；现状调查、迁移、后端、管理页与自动化测试完成，等待隔离栈真实验收。
- 2026-11-06T15:58:00+08:00：进行中 → 已完成；四组真实定时更新、开关、双场景、取消/重启、回归、UI 验收通过；主库迁移/回填完成；scheduler 按现状保持关闭。
