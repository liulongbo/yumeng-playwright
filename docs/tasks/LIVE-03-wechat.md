# LIVE-03-WECHAT：巨量星图直播达人微信字段

状态：**已完成（PASS，2026-11-06）**  
建立时间：2026-11-06T11:35:00+08:00  
最近更新：2026-11-06T19:45:00+08:00  
关联：[LIVE-03](LIVE-03.md)、[LIVE-03-70](LIVE-03-70.md)  
验收：[LIVE-03-wechat-acceptance](../evidence/LIVE-03-wechat-acceptance.md)  
调查：[LIVE-03-wechat-investigation](../evidence/LIVE-03-wechat-investigation.md)

## 目标

仅补充巨量星图直播广场达人详情的「达人微信」字段：真实采集、快照入库、详情 API 返回、前端基本资料授权展示、手动更新兼容。不修改其他业务。

## 范围与边界

- 平台 `douyin_xingtu`，场景 `live_square`；不写短视频/聚星。
- 复用 `creator_snapshots.payload`；不新增表/物理列/迁移；不写 `creator_live_current.live_metrics`（避免任务列表/摘要暴露）。
- 不修改分页/去重、执行单元、Temporal/任务中心、70 上限、筛选、定时更新、视频/聚星 Adapter。
- 微信属联系信息：不写日志/公开导出；任务达人列表不返回，仅登录后的单达人详情返回。
- 无微信/无权限时 NO_DATA，不绕过权限、不点复制、不伪造。

## 真实获取方式

- 详情「联系」hover → 联系方式 popover（查看微信/在线沟通/项目邀约/电话沟通）。
- 点击「查看微信」→ `el-dialog[aria-label="达人微信"] .wechat`，只读文本；不点复制，不点「获取达人联系方式」授权确认。
- 无「查看微信」入口即 NO_DATA；不影响其他字段。
- 真实样本 `7594043730697388068`：值长度 11，hash 前 8 位 `64862f5b`（报告脱敏）；源/DB/API/前端 hash 一致。

## 验收清单

- [x] 契约 basic 增加 `wechat`（v4），视频/聚星契约不变。
- [x] Adapter 在 profile 阶段最小 hover/click/read/close；无微信/无权限不失败。
- [x] 快照 basic.wechat；详情 API 返回；任务列表不返回；无迁移。
- [x] 前端基本资料显示，无数据「暂无数据」；不改其他字段。
- [x] 手动更新采集/更新，失败不清空其他字段。
- [x] 真实样本（有微信/无微信）DB/API/前端 hash 一致；日志无明文。
- [x] 回归 unit/contract/integration/frontend；视频/聚星不变。

## 真实测试

| 达人 | 任务 | 快照 | 结果 |
|---|---|---|---|
| 7594043730697388068（有微信） | `edc50b13-4a85-4b62-84db-66e576bbd529` | `e9e81bfc…` | COMPLETED 1/1；wechat COLLECTED len11/hash `64862f5b`；6 模块；14 basic 字段；0 FAILED |
| 7620474284346966052（无微信） | `2e2ae8f0-5006-4ff7-8e2f-1fd82a8ea6a0` | `b1f64f4f…` | COMPLETED 1/1；wechat NO_DATA；其他字段完整；0 FAILED |

- API 未登录 401；任务列表无 `wechat`，单达人详情有。
- 前端脱敏截图：[wechat-masked-basic.png](../evidence/assets/LIVE-03-wechat/wechat-masked-basic.png)
- 日志检查：worker/API/两次手动更新日志均无微信号明文。

## 修改文件

- `contracts/douyin_xingtu.live.verified.json`（v4 + `wechat`）
- `backend/src/xingtu/xingtu_live_adapter.py`（读取弹窗）
- `backend/src/xingtu/xingtu_live_detail.py`（`clean_wechat`）
- `backend/src/xingtu/product_queries.py`（任务列表移除 wechat）
- `frontend/src/liveXingtuDetail.tsx`、`frontend/src/liveDetail.test.ts`
- `backend/tests/unit/test_xingtu_live_detail.py`、`backend/tests/integration/test_live_library.py`
- 文档/证据/卡片；无迁移。

## 回归

- 后端 unit+contract **495 passed**；integration **149 passed/1 skipped**。
- 前端 **128 passed** + `tsc -b` + `vite build`；mypy 46 files。
- 短视频/聚星 Adapter/契约未改；分页/去重/70/执行单元/Temporal/任务中心未改。
- 旧 v3 快照只读；旧详情无 wechat 显示暂无数据；手动更新生成 v4 快照。

## 残余

1. 现有产品无独立字段级角色；本次以产品登录会话为授权边界，任务列表隐藏；若需按角色/人员细分，需另立权限任务。
2. 平台入口/页面可能变化；无入口即 NO_DATA，不绕过。
3. 微信属联系信息；快照/API/前端授权用户可见，日志/公开导出不含；证据已脱敏。
4. 未重跑 70 位全量（按用户要求）；本次为 2 个真实达人字段级验收。

## 状态历史

- 2026-11-06T11:35：建立卡片；真实页面定位弹窗。
- 2026-11-06T19:30：完成采集/存储/API/前端；有微信样本手动更新成功。
- 2026-11-06T19:40：无微信样本成功 NO_DATA；回归/证据完成；PASS。
