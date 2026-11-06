# LIVE-03：巨量星图直播达人详情字段补全与「时尚」真实回归

状态：**已完成（CONDITIONAL GO，2026-11-05）**  
建立时间：2026-11-05T21:40:00+08:00  
最近更新：2026-11-05T23:10:00+08:00  
是否验收：是（核心验收通过；2 项受限见末尾）


> 2026-11-06 增补：达人微信作为唯一显式联系方式字段，单独实现于 [LIVE-03-WECHAT](LIVE-03-wechat.md)；原“不包含联系方式”指介绍/电话/邮箱等，不适用于该专项。


## 目标与范围

在 LIVE-02/02F 已完成的巨量星图直播广场采集之上，补全直播达人详情业务字段，并保证短视频、磁力聚星、任务中心、执行单元与 70 位上限零回退：

1. 基本资料补充：抖音号、内容标签、商单类型、达人介绍（联系方式脱敏）。
2. 直播服务报价：品牌营销专场（按天/按小时）、电商带货专场（按小时）、电商带货拼场（按商品）分别采集服务类型、计价方式、金额、币种与平台属性。
3. 数据概览：不限/游戏直播/电商带货/其他直播分别采集；近 30/90 天、排除营销流量、只看星图商单作为显式口径；直播间数据、带货表现、转化表现与解读。
4. 直播分析：直播月历、近 15 场直播表现、直播间列表/场次明细；当前月（空则上月）时间范围明确。
5. 受众画像：按直播类型 × 粉丝/观众采集性别、年龄、地域、TOP10、城市等级、兴趣、八大人群、设备完整分布。
6. 真实「巨量星图 + 直播广场 + 内容类型：时尚」任务闭环，以及手动更新、失败不清空旧数据、必要回归。
7. 前端直播达人详情完整展示新增模块；API 沿用现有详情 `profile_payload`，不新增大规模读模型。

不包含：短视频 Adapter/契约/详情/更新行为变更；磁力聚星 Adapter/契约变更；新执行单元/队列/Profile；Temporal/任务中心/70 位上限变更；新增定时更新；直接 API；Canvas OCR；联系方式；投放表现 `live_aa_statistics`。

## 正式裁决

| 编号 | 裁决 |
|---|---|
| L3-D1 | 沿用快照存储，不新增迁移；新模块写入 `creator_snapshots.payload.modules`，`creator_live_current` 仅保留既有标量。 |
| L3-D2 | 口径扫描有界：类型 × UI 周期全采；排除营销流量/只看星图商单只对默认类型扫描；未采组合写入 `overview.meta.not_captured`。 |
| L3-D3 | 真实回归必须用「内容类型：时尚」；附件达人只作补充核验，不替代。 |
| L3-D4 | 观众画像/flow=0 若受 UI 切换限制，如实记 NO_DATA/not_captured，不伪造通过。 |

## 关联与依赖

- 规范：[AGENTS.md](../../AGENTS.md)、[docs/agent.md](../agent.md)。
- 前置卡片：[LIVE-02](LIVE-02.md)（已完成，CONDITIONAL GO）、[LIVE-02F](LIVE-02F.md)（进行中，筛选能力）。
- 设计：[LIVE-03 技术方案](../design/LIVE-03-live-detail-fields.md)、[DEC-021](../decisions/DEC-021-live-detail-snapshot-storage.md)。
- 证据：[调查](../evidence/LIVE-03-live-detail-investigation.md)、[字段差异](../evidence/LIVE-03-field-diff.md)、[测试用例](../evidence/LIVE-03-test-cases.md)、[验收](../evidence/LIVE-03-acceptance.md)。
- 执行单元：`unit-local-mac-02`（巨量星图）、`unit-local-mac-03-juxing`（聚星，仅回归）；工具 `scripts/qa/mcp_client.py`。

## 验收清单

- [x] 阶段 0：真实契约调查完成（端点/参数/响应键/类型与口径映射/DOM 控件/分页/月份范围）。
- [x] 契约：星图 live v3 新增 4 模块与 `basic` 4 字段；视频/聚星契约未变。
- [x] Adapter/解析：报价、分类型概览、月历/近15场/场次列表、受众画像真实采集；缺失六态可区分。
- [x] 存储：快照新模块/字段独立入库；`creator_live_current` 不混合；无迁移；失败不清空旧数据。
- [x] API：直播详情返回新模块；列表 payload 裁剪；`introduction` 投影；失败模块读时回退。
- [x] 前端：五模块、类型/周期/口径切换、图表、明细表、空态、手动更新。
- [x] 真实「时尚」任务：`803e59eb-2deb-460e-b1e7-ed70db5663a2`，target 2，COMPLETED 2/2，20 候选，2 快照，96/4 场列表。
- [x] 手动更新：`b334d954-3fd0-4cd9-b245-7c2df538cdd1` 等新快照、再次采集、旧数据保留、不写 schedule/短视频。
- [x] 回归：71 拒绝、70 接受；短视频/聚星自动化与既有真实证据；任务中心/执行单元不变。
- [x] 文档/证据/索引/总览回写；最终报告 GO/CONDITIONAL GO。
- [~] 受限：观众画像 `live_crowd_type=1` 在持久 profile UI 切换不稳定，`audience.*.user=NO_DATA`；flow=0 替代口径未保存，`not_captured` 披露。均未伪造。

## 实现记录

- 2026-11-05T21:40：建立卡片，阶段 0 调查。
- 2026-11-05T22:05：星图 live 契约 v3（`live_pricing/live_analysis/live_audience/live_overview` + basic 4 字段）；新增 `xingtu_live_detail.py` 纯解析器。
- 2026-11-05T22:10：`xingtu_live_adapter.py` 新增响应记录器/类型/周期/口径/月历/场次列表/画像交互；`product_queries.py` 新增详情读时回退、introduction 投影、任务列表裁剪。
- 2026-11-05T22:20：前端 `liveDetail.ts`/`liveXingtuDetail.tsx` 五模块；`liveCreator.tsx` 仅平台分支接入，保留 LIVE-02G 聚星组件。
- 2026-11-05T22:36：首轮真实时尚任务 `863ae3c5…` COMPLETED 2/2；发现列表受类型切换影响仅 11 场。
- 2026-11-05T22:45：修复为进入直播分析先采默认列表；重跑 `803e59eb…` COMPLETED 2/2，列表 96/10 页。
- 2026-11-05T22:56：修复粉丝数显示与退化区间显示（`0` 不显示 `0~0`）。
- 2026-11-05T23:01：附件达人首轮 `61e661e9…` 验证四类型/游戏；修复电商报价计价方式后重跑 `49edcc08…`，四类报价 per_day/per_hour/per_hour/per_goods。
- 2026-11-05T23:05：手动更新 `b334d954…` 新快照；flow=0 未取得；随后代码加入 not_captured 披露（快照早于补丁）。
- 2026-11-05T23:10：文档/证据/索引/总览回写。

## 验证证据

- 真实时尚任务：`803e59eb-2deb-460e-b1e7-ed70db5663a2`（表单 `assets/LIVE-03/fashion-form.png`、任务 `fashion-task.png`、详情 `live-detail.png`）。
- 手动更新：`b334d954-3fd0-4cd9-b245-7c2df538cdd1`（96 场/10 页、30/90 双周期）。
- 补充附件达人：`49edcc08-aa00-4d0a-a369-0fa5ff3105e1`（四类型含游戏、四类报价、介绍、转化）。
- 自动化：unit/contract 485 passed；integration 135 passed/1 skipped；frontend 123 passed + build；mypy/Ruff 通过。
- 原始私有响应：`.runtime/live03/`（gitignored，不含凭据）。

## 兼容性

- 未改视频/聚星 Adapter/契约；仅新增星图 live 模块与 live 专用解析。
- 无迁移；`creator_live_current` 既有列/语义不变；历史快照只读。
- 合同/Adapter 版本升级；完成旧任务/快照不变；无进行中旧 live 任务。
- 任务列表裁剪只影响 live 列表现；单达人详情完整。
- LIVE-02G 并发改动（聚星详情）未被覆盖：`liveCreator.tsx` 保留 `JuxingLiveSections` 分支，新增 `XingtuLiveSections` 独立文件。

## 残余问题

1. 观众画像 `live_crowd_type=1` 在单元持久 profile 的受众页下拉中未能稳定切换；粉丝画像按类型已完整采集。状态：**受限**，不是平台无数据。
2. flow=0 替代口径未取得；默认 flow=1（排除营销流量开）已按类型/周期采集；最终代码在未取得 flow=0 时写入 `overview.meta.not_captured=flow:0:alternate-not-captured`；最终快照 `b334d954…` 早于该披露补丁，meta 仅列 ecom/other 未采组合。状态：**受限**。
3. 逐场直播类型列表接口不带；仅 latest 同 room_id 命中时登记，其余 NOT_PROVIDED + 原因。状态：**平台限制，已披露**。
4. 游戏直播在时尚样本不可用；附件达人补充任务已验证游戏数据。状态：**补充验证**。
5. 未重跑 70 全量；71 拒绝/70 接受 + LIVE-02 既有 70 证据 + 自动化回归。

## 交接信息

- 当前阶段：已完成（CONDITIONAL GO）；未提交 Git（工作树含 LIVE-02G 并发改动，避免误提交他人工作）。
- 下一步（若有条件）：在稳定 UI/选择器上补观众画像与 flow=0；评估详情 payload 375–560KB 的独立详情接口/字段瘦身；真实 70 任务性能。

## 状态历史

- 2026-11-05T21:40：待办 → 进行中；阶段 0。
- 2026-11-05T22:36：首轮时尚任务通过；列表问题修复。
- 2026-11-05T22:51：最终时尚任务 `803e59eb` COMPLETED 2/2；96 场列表。
- 2026-11-05T23:10：文档/证据回写；CONDITIONAL GO（2 项受限）。
