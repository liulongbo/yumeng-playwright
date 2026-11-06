# LIVE-02I：星图直播观众/粉丝画像互斥导致筛选任务失败修复

状态：**已完成（PASS）**
建立时间：2026-11-06T19:22:00+08:00
最近更新：2026-11-06T19:45:00+08:00
是否验收：是（本次范围通过；全量回归干净环境通过）
关联：[LIVE-02F](LIVE-02F.md)（CONDITIONAL GO）、[LIVE-02](LIVE-02.md)、[调查证据](../evidence/LIVE-02-live-filter-investigation.md)

## 目标与范围

修复用户任务 `39c37496-84b3-4a55-81da-9c1e8f349c7d` 的失败根因：巨量星图直播「直播间观众画像」与「粉丝画像」为同一组件的二选一条件，但当前契约、前端和后端计划允许同时选择，平台只保留最后选择的画像，导致 Adapter 请求校验缺少另一画像字段并失败。

本次目标：

1. 在星图直播契约中登记两画像互斥，P1/Adapter/前端三层生效。
2. 前端选择其中一个画像时清除另一个，并提示互斥规则；加载旧混合条件时不静默删除，提交时明确报错。
3. 改善画像缺失/值不匹配的错误信息，区分粉丝/观众字段。
4. 排查聚星双画像及其他相关筛选组合，确认不误伤。
5. 真实 UI 和真实任务回归；失败历史任务保持原状，不自动重试或篡改。

不包含：

- 支持星图两画像同时使用，或自动替用户选择。
- 修改历史任务、数据库迁移、任务引擎/执行单元/队列/并发。
- 聚星地域能力、短视频逻辑、其他无关筛选器。
- 升能力版本（本次仅补登已有单选约束，不改变请求映射）。

## 根因与证据

### 失败任务

| 项 | 值 |
|---|---|
| root task | `39c37496-84b3-4a55-81da-9c1e8f349c7d` |
| 平台/场景 | `douyin_xingtu` / `live_square` |
| 状态/时间 | `FAILED`；2026-11-06 17:21:22 创建，17:23:22 失败 |
| 计划 | 个人认证；粉丝画像 age_24_30；观众画像 age_24_30 + female_50 |
| failure_reason | `PLATFORM_CONDITION_MISMATCH:PLATFORM_CONDITION_MISMATCH:LIVE_PROFILE_MISSING:age` |
| 失败证据 | `.runtime/evidence/failure/39c37496-84b3-4a55-81da-9c1e8f349c7d/448c7845bb3c98ac9c713bd8fed2399a1cf717d81a49a3dbd0bd0551f4bb2955.json` |

### 真实 UI 复现

先选粉丝画像年龄 24-30 并确认，再选观众画像年龄 24-30 + 女性占比 >50% 并确认：

- chip 从「粉丝画像：粉丝年龄-24-30岁居多」变为仅「直播间观众画像：观众年龄-24-30岁居多、观众性别-女性占比大于50%」；
- 真实请求 `attribute_filter` 只含：

```json
[
  {"field": {"field_name": "watcher_age_rate_most"}, "field_value": "[22]"},
  {"field": {"field_name": "live_watcher_gender_female_rate__ge"}, "field_value": "0.5"}
]
```

缺少 `fans_age_rate_most`。因此不是认证/选项/网络问题，而是画像单选覆盖。

## 双平台排查

| 平台 | 组合 | 结论 |
|---|---|---|
| 星图 | 粉丝画像 + 观众画像 | **不允许**；本次修复互斥 |
| 星图 | 仅粉丝画像 / 仅观众画像 | 允许；回归 |
| 星图 | 认证 + 单画像 / 单画像 + 表现 | 独立字段；本轮真实回归 |
| 星图 | 内容+性别+粉丝量级+认证+地域、地域省市、关键词+筛选、表现组合 | 既有真实任务通过；不改 |
| 聚星 | 粉丝画像 + 观众画像 | **允许**；本次真实 UI 验证请求同时含 `fansGender` 与 `viewerGender`，不改 |
| 聚星 | 内容+画像+预期观看+CPM、内容多选 | 既有真实任务通过；不改 |
| 聚星 | 预期观看+最高在线+CPM | 独立字段；回归矩阵检查 |
| 聚星 | 粉丝/观众地域 | 契约未登记；维持不展示 |

## 验收清单

- [x] 星图契约登记 `live_viewer_profile`/`live_fan_profile` 双向 `incompatible_with` 与 `combination_policy.incompatible`。
- [x] P1 `build_expected_plan` 对双画像返回 `INVALID_FORM`；真实任务 `fdb68678…` FAILED_VALIDATION、0 浏览器资源。
- [x] 前端选择第二画像时清除第一画像并显示互斥提示；正反方向真实 UI 验证；策略校验保留。
- [x] 画像缺失/值错误信息包含 `live_fan_profile`/`live_viewer_profile` 字段。
- [x] 星图粉丝单画像真实任务 `43d0405e…` COMPLETED 1/1。
- [x] 星图观众单画像真实任务 `9fa50b63…` COMPLETED 1/1。
- [x] 星图认证+单画像 `29001a9b…`、单画像+表现 `afe3da51…` 均 COMPLETED 1/1。
- [x] 聚星双画像真实任务 `948b046c…` COMPLETED 1/1；任务详情同时显示粉丝/观众画像。
- [x] 失败任务 `39c37496…` 保持 FAILED，未修改；文档说明需新建单画像任务。
- [x] 目标单元 28、全量 unit 452、契约 43、集成 149/1 skip、E2E 14、前端 128、mypy 46、Ruff 通过。
- [x] 证据、索引、总览、LIVE-02F 残留说明回写。

## 实现记录

- 2026-11-06T19:22：建立卡片；完成日志/DB/真实 UI 根因定位；聚星双画像真实 UI 验证通过（不互斥）。
- 2026-11-06T19:25：星图契约增加双向 `incompatible_with` 与 policy pair；后端错误信息含字段；前端自动清除/提示。
- 2026-11-06T19:26–19:41：真实任务 `fdb68678…` 被 P1 拒绝；`43d0405e…`/`9fa50b63…` 单画像、`29001a9b…` 认证+画像、`afe3da51…` 画像+表现、`948b046c…` 聚星双画像均通过。
- 2026-11-06T19:41：前端真实 UI 正反方向自动清除验证、任务详情/证据截图完成。

## 验证证据

- 验收：[LIVE-02I 验收](../evidence/LIVE-02I-live-filter-compatibility.md)
- 失败任务证据：见上及 `.runtime/evidence/failure/39c…`。
- 真实 UI：[自动清除](../evidence/assets/LIVE-02I/xingtu-profile-auto-clear.png)、[平台实际覆盖](../evidence/assets/LIVE-02I/xingtu-platform-profile-replaced.png)、[仅粉丝任务](../evidence/assets/LIVE-02I/xingtu-fan-only-task.png)、[仅观众任务](../evidence/assets/LIVE-02I/xingtu-viewer-only-task.png)、[双画像拒绝](../evidence/assets/LIVE-02I/xingtu-invalid-both.png)、[聚星双画像](../evidence/assets/LIVE-02I/juxing-both-profiles-task.png)。
- 自动化：目标单元 28、全量 unit 452、契约 43、集成 149/1 skip、E2E 14、前端 128、mypy 46、Ruff 通过。

## 交接信息

- 当前阶段：已完成（PASS）；**本次未提交 Git**。工作区含并发 LIVE-02G/LIVE-03 未提交改动，本任务只修改自身文件，不 reset/checkout/stash。
- 约束：不升能力版本；不修改历史任务；不改聚星。
- 后续：如果并发工作区提交，需协调本任务改动；历史双画像任务不可原样重试，需新建单画像任务。

## 状态历史

- 2026-11-06T19:22：待办 → 进行中；完成根因定位与聚星排查。
- 2026-11-06T19:25：契约/后端/前端实现完成。
- 2026-11-06T19:41：真实 UI/真实任务/自动化完成；目标范围通过。
- 2026-11-06T19:50：证据、卡片、索引/总览回写；已完成（PASS）。
