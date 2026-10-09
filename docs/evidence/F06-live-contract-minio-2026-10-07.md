# F06 真实集合契约、MinIO 与根任务终态验收证据（2026-10-07）

> 状态：通过。本证据关闭 F06 的 U05、F06 范围内 U09、F05 完整度前置及真实根任务终态；不替代 UNIT-01 的生产线路证明，也不替代 OPS-01 的备份、告警和异机恢复验收。

## 1. 安全与证据边界

- 本文只记录契约路径、数量、状态、脱敏任务标识和测试结论，不记录账号 ID、达人 ID、作品 ID、Cookie、Token、请求头值、签名 URL 或未脱敏响应正文。
- 原始研究产物只保存在被忽略的 `.runtime/research/`；研究工具对 URL、业务值和图片响应执行结构化脱敏。
- “真实”指 2026-10-07 在同一已绑定本地执行单元和真实巨量星图会话中的观察；合成浏览器契约、隔离 PostgreSQL 和本地 MinIO 测试均单独标注。

## 2. U05：两组默认精选集合真实契约

两组默认集合均位于达人主页商业能力总览，不进入全量作品页：

| 集合 | 真实请求 | 唯一卡片数组 | 样本 A | 样本 B | 终点/空态 |
|---|---|---|---:|---:|---|
| 优秀传播视频 `excellent_reach` | `GET /gw/api/data_sp/author_spread_videos` | `spread_videos` | 4 | 4 | `base_resp.status_code=0` 表示本次默认集合响应完成 |
| 优秀种草视频 `excellent_seeding` | `GET /gw/api/data_sp/author_shopping_videos` | `shopping_videos` | 4 | 0 | 样本 B 同时出现页面空态“该达人近30天内暂无商单数据” |

核验结论：

- 卡片顺序来自各集合数组，不固定四条；“四条”只是本次非空样本的返回数量，不形成 Top X 规则。
- 两组请求以当前达人参数关联；完整快照重复时使用显式 `latest`。封面签名响应为逐对象分片，使用 `all` 并按真实 `cover_uri == img.uri` 关联。
- 页面懒加载未触发个别签名请求时，只允许重放本操作已经观察到的同源 GET 模板，且仅替换契约登记的 `uri` 参数；响应仍须通过业务成功、大小、类型和 join 值相等校验。
- 作品身份优先使用真实作品 ID、规范链接和真实局部键；不按标题或封面相似度合并。相同作品跨组复用底层身份，但两组位置、指标与文本独立。
- 接口不提供标题或副标题时登记 `NOT_PROVIDED`，不通过 OCR、模型或 URL 拼接补值；没有发布时间过滤，也不下载视频。
- 封面签名请求为 `GET /gw/api/fe_common_service/tools/get_sign_image`。实测 CDN 主机为 `p3-star-fe-sign.byteimg.com`、`p9-star-fe-sign.byteimg.com`、`p26-star-fe-sign.byteimg.com`，内容类型为 `image/webp`，契约大小上限为 5 MiB。
- 集合外响应行不得进入集合；未证明成功终点时保持 `INCOMPLETE`。成功空数组和页面空态同时成立时为 `EMPTY`，表示该模块检查完成。
- 正式注册表最终版本为 `xingtu-ad-creator-featured-v8` / `browser-v7`；两组 checkpoint 均为 v4。全局 live 门槛及 `featured:excellent_reach`、`featured:excellent_seeding` 两个能力范围均已审计启用。

## 3. F05 完整度前置

- 主页清单由 6 模块/61 字段扩展并实机核验为 8 模块/75 字段，补齐粉丝画像与创作能力；`profile_requirements.json` 为 `full-homepage-inventory-v3-live-verified`，`inventory_verified=true`。
- 对重复完整快照登记 `repeat_result_mode=latest`；对增量分片使用 `all`。同路径响应仍必须满足当前达人和模块的请求/响应关联条件。
- Observer 修复了必需响应完成后的 lost-notify 竞态；缺失的可选请求不再强迫操作等待全局超时。
- `spread` 中真实成功响应未提供的 5 个字段有明确缺源证据，登记为 `NO_DATA`，没有伪造成零值或读取成功。
- 非基础可选模块 Schema 异常被隔离为模块失败观测与 scoped contract health；主页身份和基础门槛继续严格失败。
- 两位达人真实根任务中 `profile_complete_count=2`；每位 8 个模块均完成，75 个必需字段无 `FAILED` 或 `NOT_ATTEMPTED`。

## 4. U09：本地 MinIO 功能闭环

- Compose 使用固定版本 MinIO 服务镜像，并复用镜像内固定 `mc` 完成幂等私有 bucket 初始化；重复初始化不清空已有对象。
- `S3CoverStore` 上传后执行 `head_object` 的 checksum、内容类型、大小校验，并通过 `get_object` 全量读回重算 SHA-256；校验成功前不登记 `media_objects` 或卡片引用。
- MinIO 对 metadata header 的大小写差异按键名大小写不敏感处理，但 checksum 值仍严格比较。
- 服务重启前后同一对象的字节数和 SHA-256 一致，证明本地卷持久性。
- 真实两达人任务写入 12 个去重封面对象，全部为非空 `image/webp`；12/12 S3 读回校验通过，任务内引用 12/12 可取得，另一任务 0/12 可取得。
- 人工创建 1 个无卡片引用的对象后，`cover-gc` 只删除该 1 个孤儿；12 个已发布快照引用的对象仍全部可读。
- 本轮没有新增产品级图片 HTTP API；验收的是 F06 的任务级授权引用边界。产品登录态图片入口仍归 APP-01/CONSOLE-01。

## 5. 真实根任务 `COMPLETED`

真实两达人根任务 `e3905149-9aa5-4873-9c3a-cea888b7f611`：

- 搜索、两位身份核验、F05 主页、F06 两组集合和 MinIO 封面全部完成。
- `valid_count=2`、`profile_complete_count=2`、`featured_complete_count=2`。
- 两位达人均 `pipeline_complete=true`。
- 根任务为 `COMPLETED`，`failure_reason=null`。
- 两组各产生 2 条 `COMPLETE` 观测；传播组共 8 张卡片、种草组共 8 张卡片。两组跨达人共形成 12 条去重媒体对象和 4 条快照集合关联。

该结果证明完整度来自 F05+F06 全部步骤，而不是仅由有效达人数触发。

## 6. 封面失败与恢复补采

使用不可达 S3 endpoint 创建目标为 1 的受控任务 `a8fe67b4-ab20-44da-9a34-804cd44e7add`：

1. 修复前的单独历史任务证明 SDK `ClientError` 会击穿 Activity；代码随后把 S3 写入、读回和删除错误转换为稳定 `CollectorError`，并新增回归测试。
2. 修复后的第一轮准确结束为 `PARTIAL_COMPLETED / FEATURED_COLLECTION_INCOMPLETE`：`profile_complete_count=1`、`featured_complete_count=0`。传播组保留 4 张卡片、种草组保留 3 张卡片，7 张卡片文本/指标均保留，只有封面为 `FAILED`。
3. 恢复正常 MinIO 后，对同一根任务发出带版本校验的审计 `retry`。结果升级为 `COMPLETED`：两组仍为 4/3 张，7 个封面全部 `STORED`，`pipeline_complete=true`。
4. 数据库保留 4 条追加式集合观测：第一轮两条 `INCOMPLETE`（0 个存储封面、7 个失败封面），第二轮两条 `COMPLETE`（7 个存储封面、0 个失败封面）。
5. 同一根任务保留 2 份不可变达人快照和 4 条集合关联；前一份快照的两条失败关联没有被恢复轮覆盖。

## 7. 最终自动化验证

最终版本执行结果：

- `make check`：Ruff、format-check、mypy 全通过；单元测试 **120 passed**。
- `make test-contract`：真实 Chromium + 合成路由 **26 passed**。
- `make test-integration`：隔离 PostgreSQL、顺序迁移 001—007 及专用 MinIO bucket **57 passed，0 skipped**。
- `make test-e2e`：Temporal 工作流、信号、恢复和回放 **4 passed**。
- 四层测试合计 **207 passed**。
- `git diff --check` 通过；证据与待提交文件不包含明文 Cookie、Token、密码、请求头值或未脱敏响应正文。

覆盖重点包括：重复响应 `all/latest`、GET 重放的精确 join、迟到/非当前达人响应、两组独立顺序和跨组身份、真实空态、未知终点、可选主页模块异常隔离、MinIO 写后读回、任务内/跨任务引用、失败恢复、追加式观测、不可变快照和孤儿清理。

## 8. 验收结论与保留边界

F06 的 U05、F06 范围内 U09、真实小样本、失败恢复与根任务终态全部通过，F06 可标记“已完成”。F05 的真实字段清单和 `COMPLETED` 前置也已通过，可同步关闭 F05。

以下事项不属于本卡，状态保持不变：F04 第三页、产品前端/API、手动刷新、蜂窝生产线路、远程维护、MinIO 生产备份/告警/生命周期及异机恢复、产品级登录态图片入口。
