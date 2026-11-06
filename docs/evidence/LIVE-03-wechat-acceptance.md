# LIVE-03-WECHAT 验收记录

日期：2026-11-06  
结论：**PASS（字段级；产品登录边界）**  
卡片：[LIVE-03-wechat](../tasks/LIVE-03-wechat.md)  
调查：[LIVE-03-wechat-investigation](LIVE-03-wechat-investigation.md)

## 1. 字段与存储

| 项 | 值 |
|---|---|
| 字段名 | `basic.wechat`（平台「达人微信」） |
| 数据源 | 「联系」hover → 联系方式 popover →「查看微信」→ `el-dialog[aria-label="达人微信"] .wechat` |
| 快照 | `creator_snapshots.payload.modules.basic.fields[field_key=wechat]` |
| API | 已登录详情 `GET /api/creator-library/{id}?creator_scene=live_square` 的 `profile_payload.modules.basic.fields` |
| 任务单达人 | 返回完整 payload；任务达人列表显式移除 `wechat` |
| current | 不写入 `creator_live_current.live_metrics`（避免列表/摘要暴露；无迁移） |
| 其他平台 | 视频/聚星契约、Adapter、快照均未改 |

契约：`xingtu-live-square-v4` / `xingtu-live-browser-v4`；`basic` 14 字段；筛选 capabilities 不变。

## 2. 修改文件

- `contracts/douyin_xingtu.live.verified.json`：新增 `wechat`（DOM dialog source），v4。
- `backend/src/xingtu/xingtu_live_adapter.py`：profile 阶段 hover「联系」→「查看微信」→读 `.wechat`→关闭；无入口/无权限/无数据返回 None；不点复制/不点联系授权确认。
- `backend/src/xingtu/xingtu_live_detail.py`：`clean_wechat` 精确校验（排除图标/空值/标签）。
- `backend/src/xingtu/product_queries.py`：任务列表 basic 移除 `wechat`；单达人详情保留。
- `frontend/src/liveXingtuDetail.tsx`：基本资料新增「达人微信」行；无数据「暂无数据」；说明授权边界。
- `frontend/src/liveDetail.test.ts`：wechat 解析/展示断言。
- `backend/tests/unit/test_xingtu_live_detail.py`：`clean_wechat` 正反例。
- `backend/tests/integration/test_live_library.py`：详情返回 wechat、任务列表不返回。
- 文档/证据/卡片。无迁移、无新表/列。

## 3. 真实测试

### 3.1 有微信达人

| 项 | 结果 |
|---|---|
| 达人 | `7594043730697388068`（内部 `9654aba4-…`） |
| 手动更新任务 | `edc50b13-4a85-4b62-84db-66e576bbd529` |
| 状态 | **COMPLETED 1/1**；profile/pipeline complete；failed 0 |
| 快照 | `e9e81bfc-9922-4642-85c1-68215830c301` |
| `basic.wechat` | **COLLECTED**，长度 11，SHA-256 前 8 位 `64862f5b` |
| 其他 basic 字段 | 14 字段；原抖音号/内容类型/标签/商单类型/介绍等未丢失 |
| 模块 | live/basic/live_pricing/live_analysis/live_audience/live_overview 均 COLLECTED |
| 源核对 | 页面弹窗 hash `64862f5b` = DB = API = 前端行 hash |
| 前端 | 详情行「达人微信」存在，hash 一致；脱敏截图 [wechat-masked-basic.png](assets/LIVE-03-wechat/wechat-masked-basic.png) |

### 3.2 无微信达人

| 项 | 结果 |
|---|---|
| 达人 | `7620474284346966052`（内部 `9d13d41b-…`） |
| 手动更新任务 | `2e2ae8f0-5006-4ff7-8e2f-1fd82a8ea6a0` |
| 状态 | **COMPLETED 1/1**；profile/pipeline complete；0 FAILED |
| 快照 | `b1f64f4f-2275-4779-ad9e-d4e934a8fafd` |
| `basic.wechat` | **NO_DATA**（contact popover 无「查看微信」） |
| 其他字段 | basic 14 字段，原字段完整；6 模块完整 |
| 前端 | 「达人微信」行显示「暂无数据」；其他字段正常 |

### 3.3 权限/暴露面

- 未登录详情 API：**401**。
- 任务达人列表：`wechat` 不在 `payload.modules.basic.fields`；单达人详情返回 `COLLECTED`。
- 前端详情页需产品登录；任务列表不展示该字段。
- 当前产品没有独立字段级角色；本次以**产品登录会话**作为授权边界，未新增角色模型（超出本次范围）。若要求“仅特定角色/人员可见”，需另行授权权限模型任务。

### 3.4 日志与复制

- 检查 `worker-wechat.log`、`api-wechat.log`、两次手动更新日志：**不含微信号明文**。
- 实现不点击 `.star-icon-copy`；不调用复制 API。
- 临时调查原件已清理，仅保留脱敏 hash/截图。

## 4. 回归

| 项 | 结果 |
|---|---|
| 后端 unit + contract | **495 passed** |
| 后端 integration | **149 passed / 1 skipped** |
| 前端 | **128 passed** + `tsc -b` + `vite build` 通过 |
| mypy | 46 files，通过 |
| 短视频 | 未改 Adapter/契约/字段；契约 v4 仅 live；回归通过 |
| 磁力聚星 | 未改 Adapter/契约；integration 通过 |
| 分页/去重/70/执行单元/Temporal/任务中心 | 未改 |
| 数据库 | 无迁移/新表/新列；旧 v3 快照只读，旧详情无该字段显示暂无数据 |
| 手动更新 | 同一链路采集/更新；无微信时 NO_DATA，不阻断其他字段 |

## 5. 残余与风险

1. 字段级权限：现有产品无角色模型；本实现以登录+任务列表隐藏为边界。若要按具体人员/角色限制，需另立权限任务。
2. 平台入口/页面可能变化；当前依赖「联系」→「查看微信」→ dialog；无入口即 NO_DATA，不绕过。
3. 微信属联系信息：快照/API/前端授权用户可见；日志/公开导出不包含；报告/证据已脱敏。
4. 旧快照（v3 之前）没有 `wechat` 字段，前端显示暂无数据；手动更新后生成 v4 快照。
5. 未运行 70 位全量（按用户要求）；本次为 2 个真实达人的字段级验收。

## 6. 结论

**PASS**：字段通过真实页面最小交互采集，按契约写入直播快照，详情 API 返回，前端基本资料授权展示，手动更新兼容；无微信样本 NO_DATA 且不影响其他字段；其他业务回归通过。
