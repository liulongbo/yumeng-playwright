# LIVE-02G 磁力聚星直播达人详情字段补全验收

日期：2026-11-05（Asia/Shanghai）
分支：`1105-live02g`
结论：**CONDITIONAL GO（字段补全范围通过；遗留条件见 §8）**

## 1. 验收范围

验证附件列出的业务模块能够：

真实平台请求 → 解析/标准化 → 快照与 current 存储 → 详情 API → `/creators/:id/live` 前端展示 → 直播手动更新。

样本：

| 样本 | userId | starId | 用途 |
|---|---|---|---|
| 王者荣耀王小贱（福利主播） | 52022133 | 9104 | 基础/概览/指数/合作/评价/带货全量 |
| 桐桐就酱🐑. | 1633604095 | 451066 | 作品 35 条、粉丝趋势、受众画像、评价为空 |

## 2. 真实任务与状态

| 类型 | 根任务 | 达人 | 终态 | 结果 |
|---|---|---|---|---|
| 直播采集 | `397b46dc-0cb4-4f8f-ae90-5d5bffd017d4` | 9104 | COMPLETED | 1/1 有效，profile/pipeline complete，8 模块 COLLECTED，62 字段 COLLECTED，0 FAILED |
| 直播采集 | `0e1e01c3-3293-4469-8934-2fdf5f0cb56a` | 451066 | COMPLETED | 1/1 有效，8 模块 COLLECTED，49 字段 COLLECTED，0 FAILED（多数字段为平台 NO_DATA） |
| 直播手动更新 | `56592cc0-f56f-4b99-aa39-befd07e14e3e` | 9104 | COMPLETED | 新快照 `81863e94-2fdb-43eb-90ee-3bd985c44610`；`creator_update_schedule` 0 行 |

9104 快照：`4dfa3792-3136-4265-a22b-6127eb2bbec7`（首次）→ `81863e94-2fdb-43eb-90ee-3bd985c44610`（手更）。旧快照保持不可变；current 指针指向新快照。

## 3. 源平台 → DB → API → 前端核对

### 3.1 9104 关键字段

| 业务字段 | 源平台/接口值 | DB（快照/current） | API 详情 | 前端显示 |
|---|---|---|---|---|
| 昵称/ID/starId | 王者荣耀王小贱 / 52022133 / 9104 | 同值 | 同值 | 同值 |
| 地域/机构/认证 | 广东-广州 / 胡子家族 / 快手2025百大主播 | 广东/广州/胡子家族/认证 COLLECTED | 同值 | 同值 |
| 粉丝数 | 37,388,604 | count 37,388,604 | 同值 | 3,738.9万 |
| 内容分类/行业 | 游戏、多人在线战术竞技游戏；通信-号卡… | tags 完整 | 同值 | 标签完整 |
| 三类报价 | 29,100 / 75,450 / 45,400 | quote_details 3 档 + 旧 quote_* 3 字段 | 同值 | ¥29,100 / ¥75,450 / ¥45,400，业务类型/单位分别展示 |
| 预期观看/最高在线/预期CPM/周均 | 1,734,393 / 129,037 / 17 / 10 | 同值 | 同值 | 173.4万 / 12.9万 / 17 / 10 |
| 近30天信用分 | null（页面 `-`） | NO_DATA，raw null | 同值 | 平台暂无数据 |
| 预期最高在线人数 | 52,357 | COLLECTED | 同值 | 52,357 |
| 历史合作行业 | 10 个行业 | tags 10 项 | 同值 | 10 个标签 |
| 观众摘要 | 男性76.6%、18-23 38.3%、安卓67.5%、价格1000-2000 39.4%、三线29.6%、广东/河南/山东 | 3 个 tag 字段 | 同值 | 三个摘要行 |
| 达人指数 | 81.6；30538/78.3%；64/低于50% | score 81.6；rank 30538/64；percent 0.7832/0.3905 | 同值 | 81.6；30,538/78.3%；64/低于50% |
| 雷达 | 6 维当前 + 5 维均值 | 完整 | 同值 | 雷达 + 均值列表；注明无综合均值 |
| 指数趋势 | 202606–202611 全 0 | 10 条序列，all_zero=true | 同值 | 6 维选择；0 折线 + 提示 |
| 个人作品 | 19 条，1/5 | 19 条 | 完整数组 | 19 条，4/页，1/5 |
| 聚星作品 | 57 条，1/15 | 57 条 | 完整数组 | 57 条，15 页 |
| 只看电商带货 | 个人 4/19；聚星 0/57 | `has_sku_info` | 同值 | 过滤正常；聚星空态 |
| 最近15个直播 | 15 条；最高236.7万/最低1万 | 15 条 | 完整 | 15 条柱状，切指标 |
| 直播频次 | 月[33,48,9]；周 7 项；时 8 项 | 完整 | 同值 | 月/周/时切换 |
| 粉丝趋势 | 30天 +15,674/0.0%；90天 +636,509/1.7% | 30/90 独立结构，日期点完整 | 同值 | 1.6万/0.0%；63.7万/1.7%，总量/增量切换 |
| 观众画像 | 性别/年龄/品牌/价格/活跃/城市等级/省市/TGI | 完整；device_type=SUMMARY_ONLY；interest/九大人群 NO_DATA | 同值 | 分布条 + 省份/城市/占比/渗透；设备类型摘要 |
| 粉丝画像 | 独立性别/年龄/设备/价格/活跃/兴趣 | 独立结构；兴趣 10 项 | 同值 | 粉丝画像独立展示 |
| 带货 7日 | 全 0，页面 `-` | `live.commerce_7d` NO_DATA，raw 0 | 同值 | 暂无数据 + 说明 |
| 带货 30日 | 4 / 2,313,723 / 45,708 / 14 + graph | COLLECTED | 同值 | 切换近30日显示 |
| 带货 90日 | 12 / 2,893,961 / 52,297 / 35 + graph | COLLECTED | 同值 | 切换近90日显示 |
| 热销品牌/类目 | 王者荣耀 / 其他100% | COLLECTED | 同值 | 显示 |
| 合作 30天 | 56.41% / 72% / 18 | 0.5641 / 0.72 / 18 | 同值 | 56.4% / 72.0% / 18；时间范围 2026-10-06~2026-11-04 |
| 合作 90天 | 73.63% / 84.51% / 60 | 0.7363 / 0.8451 / 60 | 同值 | 73.6% / 84.5% / 60；时间范围 2026-08-07~2026-11-04 |
| 评价汇总 | 4.8/4.8/4.8/4.8；18 条 | summary + total 18 | 同值 | 4.8；共 18 条 |
| 评价明细 | 18 条；10+8 两页 | 18 条，pages=2，complete=true | 完整 | 10/页，1/2→2/2，第二条页含“棒棒棒”等 |
| 隐藏评价 | 页面“匿名评论” | `reviewer_label=匿名评论`，不存 productName | 同值 | 匿名评论 |

### 3.2 451066 空数据/部分数据

| 字段 | 源平台 | DB/API | 前端 |
|---|---|---|---|
| 个人作品 | 35 条/1/9 | 35 条 | 35 条，9 页 |
| 聚星作品 | 0 | NO_DATA | 暂无数据 |
| 粉丝趋势 | 30天约 +230,664/1.37% | 完整 | 23.1万/1.4% |
| 合作 30/90 | null/0，页面 `-` | NO_DATA，raw null/0 | 平台暂无数据 |
| 带货 7/30/90 | 空/0 | NO_DATA | 暂无数据 |
| 信用分 | null | NO_DATA | 平台暂无数据 |
| 评价 | total=0；score 接口仍返回 5.0 | total=0 COLLECTED；summary/reviews NO_DATA | 暂无客户评价 / 共 0 条，不展示 5.0 为有效评分 |
| 认证 | 空 | NO_DATA | 平台暂无数据 |
| 达人指数 | 85.25；13776；6387 | 同值 | 85.25；13,776；6,387 |

## 4. API/读模型检查

- 列表 `GET /api/creator-library?platform=kuaishou_juxing&creator_scene=live_square`：
  - 9104 的 `live_metrics` 含 33 个键；**不含** `live.personal_live_works`、`live.evaluation_reviews`、画像/趋势/带货结构等详情大字段；
  - 详情 `GET /api/creator-library/{id}?creator_scene=live_square` 含 49 个键，包含作品/画像/趋势/评价/带货结构；
  - `profile_payload` 含 8 个模块；9104 快照约 295KB（含完整作品/画像/评价），详情可接受；列表被裁剪。
- `module_statuses`：8 模块均 COLLECTED；`field_sources` 包含新字段路径/周期。
- 510 项旧字段均保留；`content_theme_labels` 从 `content_type_labels` 回退成功（9104=`游戏/MOBA`，451066=`颜值达人/颜值综合`）。
- 直播数据隔离：两个新达人 `platform_creators.projection={}`；`douyin_xingtu_creator_current` 0 行；`creator_update_schedule` 0 行。
- 71 位直播任务仍 422：`live target_count exceeds 70`。

## 5. 手动更新验收

- 9104 直播更新任务 `56592cc0-f56f-4b99-aa39-befd07e14e3e` COMPLETED。
- 快照由 1 份变 2 份；新快照 8 模块全部 COLLECTED；`live.evaluation_reviews`、`live.personal_live_works`、`live.commerce_30d` 等字段仍 COLLECTED；`live.credit_score` 仍 NO_DATA。
- `creator_live_current.latest_snapshot_id` 指向新快照；`creator_update_schedule` 0 行（直播手更不写定时更新）。
- 旧快照仍可查询，未重写；更新后页面前端展示正常。

## 6. 真实 UI 验收（Playwright MCP + Chrome）

页面：`http://127.0.0.1:5173/creators/{creator_id}/live`。

- 9104：
  - 基础信息/报价/概览/指数/作品/粉丝趋势/受众画像/带货/合作/评价 10 个区块全部出现；
  - 作品个人 19（1/5）→聚星 57（1/15）；勾选“只看电商带货”聚星空态、个人 4 条；
  - 作品指标切到“评论数”、频次切“按周”正常；
  - 带货切“近30日”显示 2,313,723 / 45,708 / 14；切“近90日”正常；
  - 合作切“近90天”显示 73.6% / 84.5% / 60；
  - 受众画像切“粉丝画像”显示粉丝兴趣；省份/城市、占比/渗透切换可用；
  - 评价下一页到 2/2，显示第 11–18 条。
- 451066：
  - 35 条个人作品、1/9；指数 85.25/13,776/6,387；
  - 合作/带货/信用/认证/评价为空态；评价“共 0 条”、不显示 5.0；
  - 作品/粉丝趋势/受众画像正常。
- 兼容性页面：
  - 磁力聚星短视频详情 `/creators/{juxing_video_id}` 正常加载，基础资料/报价/传播/作品/画像均显示；
  - 星图直播详情 `/creators/{xingtu_live_id}/live` 正常加载（该页面同时受并发 LIVE-03 工作影响，LIVE-02G 未改星图组件/契约）；
  - 任务中心 `/tasks` 正常加载。

## 7. 自动化测试

| 检查 | 结果 |
|---|---|
| `pytest backend/tests/unit` | **442 passed** |
| `pytest backend/tests/contract` | **43 passed** |
| `pytest backend/tests/integration`（`xingtu_test` 库） | **133 passed, 1 skipped** |
| `npm test`（frontend） | **119 passed / 10 files** |
| `npm run build`（frontend） | **通过**（bundle >500KB 警告，非失败） |
| `mypy backend/src` | **44 files, no issues** |
| 变更文件 `ruff check` / `ruff format --check` | 通过 |
| 全仓 `ruff check` / `format --check` | 仍有既有 `scripts/acceptance/*` E501/UP031/格式问题（非本任务新增；见 `docs/tasks/LIVE-02F.md` 既有记录），本任务未改这些脚本 |
| `pytest tests/e2e` | **6 passed / 8 failed**：失败均为 Temporal ephemeral server 下载 `https://temporal.download/...` 被环境网络阻止，非代码断言失败 |

新增测试：

- `backend/tests/unit/test_juxing_live_fields.py`：14 条解析/状态/分页/去重/隐私。
- `backend/tests/unit/test_juxing_live_adapter_detail.py`：7 条 Adapter 模块编排/失败局部化/分页/周期请求。
- `backend/tests/integration/test_live_library.py`：+列表裁剪/详情完整/content labels。
- `frontend/src/liveJuxingDetail.test.tsx`：6 条模型/渲染/切换/旧快照/回退。

## 8. 遗留与限制

1. **未重跑 70 位全量**（按用户要求）；沿用 LIVE-02 70 位真实证据 + 本次自动化/小样本（71 拒绝、合同/单元/集成回归）。
   - 2026-11-06 后续 [LIVE-02H](LIVE-02H-acceptance.md) 已完成磁力聚星直播「时尚」单任务 70/70 COMPLETED、资料完整 70/70、0 FAILED。
2. **指数趋势两样本全 0**：平台返回 0，已保存并标 `all_zero`，不是采集失败。
3. **设备类型**：`mobilePercentage` 样本为空，仅 `viewerDeviceTag` 文字摘要；已标 `SUMMARY_ONLY`。
4. **九大人群/观众兴趣**：样本为空；按 NO_DATA。
5. **作品播放 URL 有时效签名**；封面不进入对象存储；没有稳定公开作品页。
6. **评价无平台 ID**：组合哈希去重；隐藏评价不保存 order/productName。
7. **page 7+**：沿用 LIVE-02 未验证结论。
8. **E2E**：Temporal ephemeral server 下载被网络阻止，8 条 BLOCKED；不是本次代码失败。已有本地 Temporal 服务但测试使用 ephemeral server。
9. **并发工作区**：同一 worktree 同时存在 `docs/tasks/LIVE-03.md`、`xingtu_live_detail.py`、`liveXingtuDetail.tsx` 等星图直播字段补全改动（另一会话）。本报告不把星图新增功能计为 LIVE-02G 成果；兼容性只确认聚星改动未改星图 Adapter/契约，星图页面可加载。
10. **未新增数据库表/迁移**；作品/评价/画像/趋势保存在 JSONB 快照与 current，符合最小改动决策。旧 `live.commerce_*` 字段的 `period_label` 修正为近7天（值本来就是 duration=7），旧快照 label 不变。

## 9. 结论

- 附件要求的聚星直播详情字段，在真实平台可获取范围内已完成：基础/报价/概览/指数/作品/粉丝趋势/画像/带货/合作/评价 10 个模块。
- 9104 全量数据、451066 空数据/部分数据两种特征均通过源→DB→API→前端核对。
- 首次采集和手动更新均完成，旧快照保留、schedule 未写入、视频/星图数据未受影响。
- 综合判定：**CONDITIONAL GO**。条件为上述 §8 的 70 全量未重跑、E2E 环境阻塞、平台抽样空字段/全 0 趋势、签名 URL 与 page 7+ 限制；这些均有明确记录，不影响 LIVE-02G 字段补全范围。
