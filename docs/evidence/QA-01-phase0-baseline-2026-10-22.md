# QA-01 Phase 0 基线与只读核验（2026-10-22）

> 范围：只读环境/服务/会话/数据库核验。未创建真实采集任务，未修改业务代码、配置、数据库或历史任务。

## 1. 代码与环境

| 项 | 值 |
|---|---|
| 日期时间 | 2026-10-22 11:45—11:50 +08:00 |
| Git HEAD | ae600ec |
| 部署 | 单机原生 local-main；本机进程 + Docker 依赖；无云端 Worker |
| API | 127.0.0.1:8000；/api/auth/me 401（未登录预期） |
| 前端 | 127.0.0.1:5173；/ 200 |
| 队列 | xingtu-intake、xingtu-unit-local-mac-02 均有新鲜消费者 |
| update-scheduler | 未运行；22 位达人已到期，测试期间保持关闭 |
| 数据库 | 127.0.0.1:55432 / xingtu_development；PostgreSQL 18.3 |
| 契约 | xingtu-ad-creator-featured-v11；browser-v9；能力 xingtu-ad-creator-square-v2 |
| 执行单元 | unit-local-mac-02；local_development；READY |
| Chrome | 156.0.8078.47；unit profile .runtime/profiles/unit-local-mac-02 |

## 2. 服务状态

./dev.sh status：API、前端、intake-worker、collection-worker 运行中；update-scheduler 未运行；端口 8000/5173/55432/56379/59000/57233 监听；API /api/auth/me 401、前端 / 200；两队列消费者在线（新鲜消费者各 1）。

## 3. 当前平台会话

xingtu session-diagnostics --config .runtime/local-main/units/unit-local-mac-02.json exit 0：

- status: VALID
- observed_account_id == expected_account_id == ID: 1807978499337419
- protected_page_verified: true
- login_page_verified: false
- challenge_verified: false
- evidence_reason: PROTECTED_PAGE_AND_ACCOUNT_VERIFIED
- session_snapshot.restored_before_navigation: true
- Chrome 156.0.8078.47；normal_close_confirmed: true
- 报告：.runtime/qa/phase0-session.json/unit-local-mac-02-20261022T034808Z.json（脱敏，不含明文令牌）

## 4. 数据库只读基线

| 项 | 值 |
|---|---|
| root_tasks | 85：PARTIAL_COMPLETED 40 / CANCELLED 21 / COMPLETED 17 / FAILED 6 / FAILED_VALIDATION 1 |
| task_kind | collection 61 / scheduled_update 21 / manual_update 3 |
| platform_creators | 74 |
| creator_snapshots | 234 |
| task_creators | 199 |
| featured_collections | 397 |
| featured_cards | 1372 |
| media_objects | 4860 |
| v1 requirements | 26 |
| 在途任务 | 无 |
| search 健康 | v11 search ENABLED；consecutive_failures=0 |

原始只读结果：.runtime/qa/phase0-db.json。

## 5. 本轮只读确认的关键事实

1. 5 个 connection_users 产品任务：fc5fb419、6d075c00、1f2ffe33、a20c487f 为 PLATFORM_PAGE_CHANGED:SEARCH_RESPONSE_FAILED；ac2a63e5 为 CONTRACT_SCOPE_DISABLED:search。失败检查点 0 候选、0 相关请求、约 19 秒。
2. FILTER-01 两边界五区间直接实测 PASS；失败任务均为单边界（connected.min=2/10，max 为空）。
3. F04 条件回读缺口：adapter.py 911-929 在 dynamic_filter_executor 下只回读 keyword/mode；_assert_selected 只查标签，不查区间值/残留。
4. 历史分页：2026-10-06 宠物·22 位（旧契约 v2/旧库/Activity 路径）取得 40 候选、22 有效、visited_cursors=[None,"2"]、两页无重复；当前产品 DB 无 scanned_ids > 20 的任务。
5. 目标 30 的 61572cc8 在 page=2 之前因旧 504/HTML 分类失败；该分类已在 LIVE-01 修复。
6. 第 3 页及以后未验证；契约 page_fetch_max_verified=2，41 必为 SEARCH_CAPABILITY_LIMIT。
7. v1 重提路径：pages.tsx 181-190 的 upgradeRequirement 未映射 creator_regions；当前 26 条 v1 需求，属 P3 风险。

## 6. 本轮未执行

- 未创建真实采集任务；未发起平台搜索；未写入业务数据。
- 未修改 backend/frontend/contracts/migrations 任何文件。
- 未修改数据库、Cookie、Profile、账号；未重置契约熔断器。
- 未提交 Git。

## 7. 下一步

Phase 1：离线映射检查 + 只读真机探针，重点验证 connection_users 单边界 vs 两边界、五维顺序、学历/黄 V 同名条目、viewer/fan 五维；探针前停止 Collection Worker，完成后恢复。
