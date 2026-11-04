# LIVE-02F 直播广场筛选验收结果

执行日期：2026-11-05  
环境：本机开发栈，API `http://127.0.0.1:8000`，Web `http://127.0.0.1:5173`；两平台执行单元复用 LIVE-02。  
工具：Playwright MCP + 系统 Chrome（真实平台 UI）；真实产品 UI 由同一 MCP 驱动。  
原始证据：`.runtime/live02filters/`（gitignored）；公开证据只保留脱敏摘要与截图。

## 1. 强制闭环

| 平台 | 任务 ID | 创建方式 | 筛选 | 目标 | 状态 | 有效/完整 | 源平台核对 |
|---|---|---|---:|---:|---|---:|---|
| 巨量星图 | `593cd747-6ff9-4710-b409-7f76c9e41d78` | 真实产品 UI | 内容类型「时尚」，关键词空 | 2 | COMPLETED | 2/2 | 任务达人 `7620474284346966052`、`7507927976575664191`，与真实时尚首屏 star_id 一致 |
| 磁力聚星 | `472e7739-da7e-4db2-ad4d-baea9c926a79` | 真实产品 UI | 内容分类「时尚」，关键词空 | 2 | COMPLETED | 2/2 | 任务达人 `648737405`、`1143547446`，与真实时尚首屏 userId 一致 |

截图：[星图表单](../evidence/assets/LIVE-02/phase4-xingtu-form.png)、[星图任务](../evidence/assets/LIVE-02/phase4-xingtu-task.png)、[聚星表单](../evidence/assets/LIVE-02/phase4-juxing-form.png)、[聚星任务](../evidence/assets/LIVE-02/phase4-juxing-task.png)、[星图源筛选](../evidence/assets/LIVE-02/phase4-xingtu-fashion-source.png)、[聚星源筛选](../evidence/assets/LIVE-02/phase4-juxing-fashion-source.png)。

## 2. 其他筛选真实任务/请求证据

| 平台 | 任务 ID | 条件 | 结果 |
|---|---|---|---|
| 星图 | `cafc1ce5-0d21-41ce-80a5-26ecc933f5ff` | 时尚，target 1（API） | COMPLETED 1/1；checkpoint 20 个候选与时尚源列表一致 |
| 星图 | `446e7a91-4fb1-493c-9885-0a8ecb7b9bfd` | 时尚 + 直播间观众画像 18-23，target 1（UI） | COMPLETED 1/1 |
| 星图 | `032badb3-ca90-4113-b28f-e73f5ebdccfd` | 时尚 + 女性 + 粉丝 100w-300w + 个人 + 广东省，target 1 | COMPLETED 1/1；候选仅 9，组合真实收窄 |
| 星图 | `9c2fa9d3-d847-48b5-9570-efb0bf6b1400` | 时尚 + 深圳市，target 1 | COMPLETED 1/1 |
| 星图 | `d8a801be-5f29-4793-b6e8-67fc112a0eca` | 时尚 + 场次 7-25 + 平均观看 100-500 + ACU 5-10 + PCU 21-50，target 1 | COMPLETED 1/1 |
| 聚星 | `ad5a4749-3ed8-42d7-88e8-110df90913da` | 时尚，target 1（API） | COMPLETED 1/1；20 个候选与时尚源列表一致 |
| 聚星 | `e5966e90-5e95-4db5-9a72-f87c001c2ad1` | 时尚 + 粉丝画像 18-23，target 1（UI） | COMPLETED 1/1；详情显示粉丝年龄 18-23 |
| 聚星 | `2d3e9b38-ba98-41cd-9e9b-c5521c2072f3` | 时尚 + 粉丝年龄/性别/设备 + 预期观看 10-100万 + CPM 5-10，target 1 | COMPLETED 1/1；候选仅 1 |
| 聚星 | `bed7239a-2856-4421-9869-a549078d15ba` | 时尚 + 粉丝九大人群 精致妈妈，target 1 | COMPLETED 1/1 |
| 聚星 | `46cba027-072e-4850-9dc8-ecf9f36659e1` | 时尚 + 粉丝地域（实验值） | PARTIAL 0；地域维度已移除，不冒充可用 |
| 星图 | `51008bd8-b284-41e1-a1fe-44122790e282` | 关键词「美妆」+ 时尚，target 1 | COMPLETED 1/1；关键词与筛选联合生效 |
| 聚星 | `d1cf040a-ca92-4805-89af-aa7d3b1a8378` | 关键词「美妆」+ 时尚，target 1 | COMPLETED 1/1；关键词与筛选联合生效 |
| 聚星 | `bdde3849-b385-463c-9c43-d46043dc9198` | 内容分类 美妆+美食，target 1 | COMPLETED 1/1；两个 tag 同时发送 |
| 聚星 | `e702afb9-1f4d-46ee-a115-d5f4290d0fae` | 时尚 + 观众画像 24-30/女/安卓/Z时代，target 1 | PARTIAL 0，`SEARCH_EXHAUSTED`；body 被平台接受，未回退 |
| 星图 | `f4da0b95-3f44-4d16-92f4-c1ed8035667c` | 时尚 + 粉丝量级自定义 150w-250w，target 1 | COMPLETED 1/1；自定义区间生效 |

聚星 Adapter 实际请求体（任务 `2d3e9b38…`，日志脱敏摘要）：

```json
{
  "contentTagIdList": [{"id": "675", "subIds": ["735","736","737","738","739"], "selectFirstLevelId": true}],
  "expectCpmMinNum": 5,
  "expectCpmMaxNum": 10,
  "liveExpectViewer": {"min": 100000, "max": 1000000},
  "fansAgeList": [{"queryName": "18-23", "from": "0.50", "to": "1.00"}],
  "fansGender": {"queryName": "FEMALE", "from": "0.00", "to": "1.00"},
  "fansMobile": {"queryName": "IOS", "from": "0.00", "to": "1.00"},
  "pathSource": "has_filter_live"
}
```

星图 Adapter 对每个成功请求执行 attribute_filter 多重集校验；任一缺失/多余/值不符即 `PLATFORM_CONDITION_MISMATCH`，不继续。

## 3. 多页 / 70 兼容

- 两平台 target 25「时尚」任务：`ae9aecce-8b5c-4b21-8d86-686f990f2904`（星图）、`3fd7228b-2749-46f0-a838-2cc110f593b6`（聚星）；在 8/6 位时因恢复实验导致 Worker 中断/隔离，任务已取消；checkpoint 显示仍在第 1 页候选收集（cursor=2，visited=[null]），**未完成 25/25**。
- 为验证“翻页不丢筛选”，单独用真实平台 UI 应用时尚并翻到第 2 页：
  - 星图第 2 页请求 `page_param.page=2` 仍含 `live_tag_content_v2_level_one=[10719]`；第 2 页 star_id 与第 1 页不同。
  - 聚星第 2 页请求 `currentPage=2` 仍含 `contentTagIdList[{id:675,...}]`；第 2 页 userId 与第 1 页不同。
  - 生产 Adapter 对每一页重复同一校验（单元/契约测试覆盖），因此“筛选在翻页中保留”有平台请求与 Adapter 代码双重证据；任务级 25 位全量仍未完成。
- 既有真实 70 位直播任务（LIVE-02 阶段三）继续有效：星图 `065d36d8…`、聚星 `f6003e46…`，均 70/70、0 重复、跨页。本次未修改目标/分页/去重/有效判定。
- 恢复测试：中断采集 Worker 后，Temporal 活动重试进入 `WAITING_FOR_RESOURCE`，平台/执行单元要求隔离旧浏览器；真实恢复未完成（BLOCKED）。筛选条件未丢失：DB 计划与 checkpoint 保留；但“重启后继续采集”的端到端证据不足，不作为 PASS。

## 4. 空结果与失败关闭

- 聚星粉丝地域实验任务 `46cba027…`：真实返回 0 候选，终态 PARTIAL/SEARCH_EXHAUSTED，未回退为不限条件，未凑数。
- 星图请求校验、聚星未映射字段、非法枚举/单位/组合均有单元测试；不支持的字段不会被静默忽略。
- 聚星地域维度因真实控件是两级占比面板，未登记，前端不显示；避免虚假可用。

## 5. 短视频回归

- 后端单元 409 passed、契约 43 passed、集成 132 passed/1 skipped（筛选改动后）；前端 113 passed；mypy 42 files；新代码 Ruff 通过。
- 短视频契约/Adapter/表单未改；真实短视频小样本沿用 LIVE-02 阶段三证据（星图 `183b72f4…`、聚星 `468089a0…`，均 COMPLETED 1/1）。
- 本轮未重跑短视频 70 位全量。

## 6. 自动化计数

| 检查 | 结果 |
|---|---|
| `pytest backend/tests/unit` | 409 passed |
| `pytest backend/tests/contract` | 43 passed |
| `pytest backend/tests/integration`（`xingtu_test`） | 132 passed / 1 skipped |
| `npm --prefix frontend test -- --run` | 113 passed |
| `npm --prefix frontend run lint` / `build` | passed |
| `mypy backend/src` | 42 files, 0 error |
| `ruff check backend/src backend/tests` | All checks passed |
| E2E | 14 passed（含阶段二旧夹具修复） |

## 7. 结论

**CONDITIONAL GO**：

- 强制项：两平台「时尚」真实 UI 任务均 COMPLETED、入库、任务详情可展示；源平台身份核对一致。
- 已真实验证：星图内容时尚/性别/粉丝量级/个人认证/地域省/地域市/观众画像年龄/直播间表现组合；聚星内容时尚/美妆/美食映射、粉丝画像年龄/性别/设备/九大人群、预期观看/最高在线/CPM。
- 条件/未完成：聚星粉丝/观众地域未实现（不展示）；筛选任务恢复端到端 BLOCKED；target 25 多页任务到第 2 页后取消（8/6 位，未完成 25）；聚星观众画像主要靠映射/自动化而非任务；自定义区间未建真实任务；未重跑短视频 70 全量。
