# KJX-01 阶段 B：磁力聚星真实小样本证据

验证日期：2026-10-27—2026-10-28（Asia/Shanghai）  
范围：已授权账号、专用 Playwright 聚星会话、只读页面请求、1 位达人详情、独立 PostgreSQL 测试库。  
明确未做：平台写操作、批量采集、业务库写入、生产 Feature Flag 启用、Cookie/Token/请求头导出。

## 可执行能力结论

- 短视频找达人入口、关键词“母婴”和内容类型“母婴亲子”已完成页面操作、请求回读和结果回读；阶段 B 可执行合同仅开放这两个筛选条件。
- 搜索结果同时返回 `userId` 与 `starId`。详情页正文显示 `ID {userId}`，详情路由使用 `starId`；因此统一身份采用 `platform= kuaishou_juxing + platform_creator_id=userId`，`starId` 只作为详情导航参数。
- 当前证据只覆盖搜索第一页。Adapter 在需要第二页时返回 `SEARCH_CAPABILITY_LIMIT`，不把未经验证的分页行为伪装为搜索耗尽。
- 页面内部请求只在已登录的 `k.kuaishou.com` 页面通过 `fetch(..., credentials=include)` 执行；它不是公开 API，Python 侧不读取或保存 Cookie、Token 与账号凭据。
- 当前主账号下存在两个均可访问找达人和详情的子账号；本次执行单元明确绑定 `60821564`。找达人 URL 的外层查询和 SPA hash 查询均携带 `__accountId__`，合同只在受保护页面成立且该值唯一、精确匹配时接受会话；另一个子账号会得到 `ACCOUNT_MISMATCH`。

## 真实详情小样本

为减少个人数据扩散，证据不记录昵称、头像、简介、账号标识或联系方式；代码夹具也使用脱敏文案。2026-10-28 再次只读回读结果如下：

| 模块 | 页面内部路径 | HTTP/业务结果 | 脱敏核对结果 |
|---|---|---|---|
| 基础资料 | `/rest/web/star/match/starPage/baseInfo` | `200 / result=1` | 页面身份与 `userId` 一致；粉丝 21,686,076；地域、内容类型、机构可见；三档报价存在 |
| 粉丝变化 | `/rest/web/post/video/portrait/fans/fluctuation/get` | `200 / result=1` | 近 30 天涨粉 268,703，涨粉率 0.0125 |
| 视频表现 | `/rest/web/post/video/works/statistics/get` | `200 / result=1` | 播放中位数 13,092,269；预期播放 10,355,427；预期 CPM 20；互动率 0.03911；完播率 0.22881；视频数 15 |
| 代表作品 | `/rest/web/post/video/representative/works/info/list` | `200 / result=1` | 当前响应 33 条；代码保留作品 ID、标题、媒体地址、封面、播放/互动、发布时间等原始来源路径；未把媒体地址冒充作品落地页链接 |
| 受众画像 | `/rest/web/star/listPortrait` | `200 / result=1` | 粉丝画像与观众画像均存在，统计窗口记录为近 30 天 |

报价单位已通过页面与响应交叉核对：平台响应整数除以 1000 后等于页面人民币报价；标准字段保存元，`raw_value` 保存平台原始整数。相似名称指标仍保留平台来源、单位、统计窗口与合同版本，不与星图指标直接等同。

## Adapter 与持久化验证

- `KuaishouJuxingAdapter` 实现关键词/内容类型搜索映射、`userId` 身份、严格详情 URL、基础/视频表现/作品/画像模块以及联系方式脱敏。
- 单元测试使用上述真实响应形状，验证身份、粉丝、涨粉率、报价缩放、原始值和隐私脱敏。
- 临时容器 `yumeng-juxing-test-postgres` 仅绑定 `127.0.0.1:55439`，数据库为 `xingtu_test_m3`；集成夹具在其中创建并删除随机 Schema。
- 聚星真实样本形状成功写入共享 `platform_creators`、当前投影与不可变快照；同一 `creator_id` 在 `douyin_xingtu_creator_current` 中为 0 行，证明平台隔离成立。
- 专用快照冷启动无需再次人工登录，结果为 `VALID / PROTECTED_PAGE_AND_URL_ACCOUNT_VERIFIED / account_match=true`。搜索页保留作为子账号实时证据，详情页只负责达人身份和模块数据校验。
- 2026-10-28 真实只读闭环通过：目标 1、有效 1、资料完整 1、快照 1、星图当前投影 0，任务终态 `COMPLETED`；使用 `xingtu_test_m3` 随机 Schema，核对后已删除。私有报告只包含身份哈希与计数，不包含达人正文。
- 冒烟结束后只读查询 `information_schema.schemata`，`kjx_stage_b_%` 残留数为 0。
- 自动验证结果：后端单元测试 339；浏览器合同测试 43；隔离 PostgreSQL 集成测试 110 passed / 1 skipped；前端测试沿用 90；Ruff、Mypy 与 `git diff --check` 通过。
- `make check` 仍只被 `scripts/acceptance/run_cd05_acceptance.py`、`run_cd06_acceptance.py`、`run_cd07_acceptance.py` 中 11 个既有 Ruff `UP031` 阻断；本卡代码范围静态检查通过。

## 尚未完成

- 本轮证明的是 BrowserHost/Adapter/Engine/Repository 真实小样本闭环；尚未运行 Temporal Worker 端到端，因此不能宣称 Temporal 全链路通过。
- 搜索第二页、粉丝/地域/报价筛选、定时更新和字段级补采仍未进入本次可执行合同。
- “母婴 / 母婴亲子 / 10 位”属于阶段 C 真实验收；本次授权和服务端门禁均限制为最多 3 位。
- Windows 配置路径、Profile 锁和本地 Chrome 绑定仍需在甲方 Windows 环境验证。
