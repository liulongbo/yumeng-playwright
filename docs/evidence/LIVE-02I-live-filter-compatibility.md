# LIVE-02I 星图直播画像互斥修复验收

日期：2026-11-06
环境：本机 `1105-live02g` 工作区（含并发 LIVE-02G/LIVE-03 未提交改动）；API `127.0.0.1:8000`，前端 `127.0.0.1:5173`；真实星图/聚星账号。
证据原件：`.runtime/live02i/`、`.runtime/live02filters/probe/exclusive-proof/`（gitignored）。

## 1. 根因

失败任务：

| 项 | 值 |
|---|---|
| root task | `39c37496-84b3-4a55-81da-9c1e8f349c7d` |
| 平台/场景 | `douyin_xingtu` / `live_square` |
| 状态 | `FAILED` |
| 计划 | `live_certification=personal`、`live_fan_profile.age=age_24_30`、`live_viewer_profile.age=age_24_30`+`female_50` |
| failure_reason | `PLATFORM_CONDITION_MISMATCH:PLATFORM_CONDITION_MISMATCH:LIVE_PROFILE_MISSING:age` |
| 失败证据 | `.runtime/evidence/failure/39c37496-84b3-4a55-81da-9c1e8f349c7d/448c7845bb3c98ac9c713bd8fed2399a1cf717d81a49a3dbd0bd0551f4bb2955.json` |

真实星图 UI 复现（2026-11-06）：

1. 先选粉丝画像年龄 24-30 并确认；
2. 再选观众画像年龄 24-30 + 女性占比 >50% 并确认；
3. 已选条件只剩观众画像；
4. 实际请求只含 `watcher_age_rate_most`、`live_watcher_gender_female_rate__ge`，不含 `fans_age_rate_most`。

截图：[平台实际只剩观众画像](../evidence/assets/LIVE-02I/xingtu-platform-profile-replaced.png)。

结论：星图直播「粉丝画像 / 直播间观众画像」是单选组件；当前契约错误地允许两者同时选择。第二个画像覆盖第一个，Adapter 按计划同时要求两个画像，因此请求校验失败。与个人认证、选项 ID、网络、账号无关。

## 2. 代码修复

- 星图直播契约：
  - `live_viewer_profile.incompatible_with=["live_fan_profile"]`
  - `live_fan_profile.incompatible_with=["live_viewer_profile"]`
  - `combination_policy.incompatible=[["live_viewer_profile","live_fan_profile"]]`
- `Capabilities.validate_plan`：互斥错误包含字段名。
- `validate_xingtu_live_request`：画像缺失/值错误包含画像字段，如
  `LIVE_PROFILE_MISSING:live_fan_profile:age`。
- 前端 `LiveFilterFields`：选中一侧时按 `incompatible_with` 清除另一侧，并显示互斥提示。
- 不升能力版本、无迁移、未改请求映射；聚星与短视频不变。

## 3. 前端真实 UI

| 操作 | 结果 |
|---|---|
| 先选粉丝画像 24-30，再选观众画像 24-30 | 粉丝画像 checkbox 被清除；摘要只显示观众画像；提示可见 |
| 先选观众画像 24-30，再选粉丝画像 24-30 | 观众画像 checkbox 被清除；摘要只显示粉丝画像 |

截图：[先观众后粉丝清空反向验证](../evidence/assets/LIVE-02I/xingtu-profile-auto-clear-reverse.png)、[正向自动清除](../evidence/assets/LIVE-02I/xingtu-profile-auto-clear.png)。

## 4. 服务端拒绝与真实任务

| 目的 | 任务 ID | 条件 | 结果 |
|---|---|---|---|
| 双画像规划拒绝 | `fdb68678-af95-4814-b221-3ce1a6e82afe` | 粉丝 24-30 + 观众 24-30/女>50% | `FAILED_VALIDATION`；`INVALID_FORM`；field_errors：`incompatible filters: live_viewer_profile, live_fan_profile`；`valid=0`，未申请浏览器资源 |
| 星图仅粉丝画像 | `43d0405e-0947-4113-b7c1-fa3cca38ecd3` | 粉丝 24-30 | COMPLETED 1/1；任务详情「粉丝画像 粉丝年龄-24-30岁居多」 |
| 星图仅观众画像 | `9fa50b63-8cc6-48ff-bbf6-8af49584e51b` | 观众 24-30 + 女>50% | COMPLETED 1/1；任务详情「直播间观众画像 观众年龄/性别」 |
| 星图认证 + 单画像 | `29001a9b-d80b-425a-9952-aec211915993` | 个人认证 + 粉丝 24-30 | COMPLETED 1/1 |
| 星图单画像 + 表现 | `afe3da51-e4b1-42d5-b375-b55b54b36d3f` | 观众 24-30/女>50% + 场次 7-25 | COMPLETED 1/1 |
| 聚星双画像不误伤 | `948b046c-b37b-40bf-a6a8-16489999e6e2` | 时尚 + 粉丝性别女 + 观众性别男 | COMPLETED 1/1；任务详情同时显示粉丝画像/观众画像 |

截图：[仅粉丝任务](../evidence/assets/LIVE-02I/xingtu-fan-only-task.png)、[仅观众任务](../evidence/assets/LIVE-02I/xingtu-viewer-only-task.png)、[双画像拒绝](../evidence/assets/LIVE-02I/xingtu-invalid-both.png)、[聚星双画像任务](../evidence/assets/LIVE-02I/juxing-both-profiles-task.png)。

原始失败任务 `39c37496…` 保持 `FAILED`，未修改、未自动重试；需新建单画像任务。

## 5. 双平台排查

| 平台 | 条件 | 结论 |
|---|---|---|
| 星图 | 粉丝画像 + 观众画像 | 互斥；已修复 |
| 星图 | 仅粉丝 / 仅观众 | 允许；真实任务通过 |
| 星图 | 认证 + 单画像；单画像 + 表现 | 允许；真实任务通过 |
| 星图 | 内容+性别+粉丝量级+认证+地域、地域省市、关键词+筛选、表现组合 | 既有真实任务通过；未改 |
| 聚星 | 粉丝画像 + 观众画像 | 允许；真实任务 `948b046c…` COMPLETED 1/1 |
| 聚星 | 内容多选 + 画像 + 预期观看 + CPM | 既有真实任务通过；未改 |
| 聚星 | 最高在线 + 预期观看 + CPM | 字段独立；本轮未重跑真实任务 |
| 聚星 | 粉丝/观众地域 | 契约未登记；维持不展示 |

## 6. 自动化

| 检查 | 结果 |
|---|---|
| `pytest backend/tests/unit/test_live_filters.py test_live_square.py` | 28 passed |
| `pytest backend/tests/unit` | 452 passed（在不注入 `.runtime/m3-app.env` 的 registry 路径下；若注入产品启动环境，`test_update_scopes` 会因测试期望“无 registry”而失败，属测试环境差异，非代码断言） |
| `pytest backend/tests/contract` | 43 passed |
| `pytest backend/tests/integration` | 149 passed / 1 skipped |
| `pytest tests/e2e` | 14 passed |
| `npm --prefix frontend test -- --run` | 128 passed |
| `npm --prefix frontend run lint` | tsc 通过 |
| `npm --prefix frontend run build` | 通过 |
| `mypy backend/src` | 46 files，0 error |
| `ruff check backend/src backend/tests` | All checks passed |

## 7. 残留

- 不升能力版本；历史双画像任务不可原样成功，需新建单画像任务。
- 聚星「最高在线+预期观看+CPM」组合仍以映射/单测为主，本轮未单独创建真实任务。
- 工作区含并发 LIVE-02G/LIVE-03 未提交改动；本次不覆盖、不提交其改动。
- 全量 unit 在干净环境（不注入 `.runtime/m3-app.env`）452 全通过；产品启动环境注入 `XINGTU_*_REGISTRY_PATH` 时 `test_update_scopes` 的期望会失败，这是测试夹具环境差异，需在 CI/命令中区分。
