# DEC-008：两组默认精选集合与受控封面存储

- 日期：2026-09-27
- 状态：已采纳并实现（离线部分）；真实平台契约与对象存储服务仍待核验（U05/U09）

## 待解决问题

技术方案第 7 章要求新增 `collect_featured_collections`、两组默认集合的独立观测与覆盖状态、集合变化恢复，以及"受控下载 → 校验 → 才允许引用"的封面存储；第 13—15 章要求集合/卡片/作品身份/快照关联的数据模型；第 14.3 节要求根任务在 F05+F06 全部步骤完成时才为 `COMPLETED`。改造前：Adapter 只有搜索与主页模块协议，`Candidate` 没有集合观测，`TaskRecord.featured_status` 固定 `NOT_ATTEMPTED`、`pipeline_complete` 固定 `False`，`Engine.finish` 固定返回 `PARTIAL_COMPLETED`；`S3EvidenceStore` 只写脱敏证据，不能作为封面下载器。

## 选择

1. **集合契约独立于主页模块**：新增 `FeaturedCollectionSpec`（入口/动作/就绪与必须消失的加载提示/请求契约/`cards_path`/身份与链接与周期与集合标识与终点路径/卡片字段字典/模块级缺失证据/检查点版本）。非空 `featured` 必须恰好包含 `excellent_reach` 与 `excellent_seeding`；卡片范围只由 `cards_path` 决定，同一响应中的其他作品（如 `other_works`）永不进入结果。`entry` 必须留在已核验主页路径范围内，避免跳到全量作品列表。契约中没有作品时间窗口或 Top X 参数。
2. **卡片字段按行/按索引读取**：响应来源的卡片字段路径相对卡片行解析；DOM 来源取注册定位器的第 n 个节点。字段状态、单位、报价、分布、标签、缺失取值、回退与来源冲突沿用 F05 规则；新增 `FieldSpec.truncate_marker`，命中时保存原文并标记 `truncated`。
3. **模块内增量加载**：`RequestSpec.repeats`（默认 `false`）允许同一请求在一次模块操作中返回多个响应体，收集器保留全部已关联响应体，卡片按 `cards_path` 合并、按经验证身份或局部键在组内去重并计数 `reload_count`；终点取**最后一次**加载的终点字段。`repeats=false` 时仍保持"重复响应即 `RESPONSE_UNCORRELATED`"的严格性。
4. **两组独立判定**：Adapter 逐组采集，`MODULE_COLLECTION_FAILED` 转换为该组 `FAILED` 观测，另一组结果不受影响；全局错误（会话、契约、限流、挑战）继续向任务中心传播。
5. **追加式数据模型**：迁移 003 新增 `contents`、`featured_collections`、`featured_cards`、`snapshot_collections`、`media_objects`；集合与卡片表由触发器拒绝 UPDATE/DELETE。同作品跨组复用一条 `contents`，但两组各自保存位置、文本与指标；身份为空时保留局部卡片（`local_key` 或位置），不按标题或封面相似度合并。
6. **恢复与集合变化**：重采后仅当契约提供稳定集合标识、且集合标识与有序指纹都与已提交的完成观测一致时复用原观测（保留 ID 与观测时间）；其余情况生成新观测并保留旧观测。读取失败的重采只记入历史，绝不清空已提交观测。
7. **封面管道**：`CoverPipeline` 先按 `CoverSpec` 校验主机/协议/端口，再经**页面自身的会话**（`page.evaluate` + `fetch`，`credentials: include`）下载，因此复用绑定线路与登录 Cookie，不存在独立直连；逐跳复核主机、显式计数重定向、超时中止、类型与大小上限；对象写入后读回校验（本地文件哈希 / S3 `head_object` 元数据），校验通过才允许 `CoverRef(object_id=...)`；失败只记录状态与原因，文本字段保留，可重试补采；`cleanup_unreferenced` 只删除没有任何卡片引用的封面对象。
8. **任务终态**：`Engine.finish` 在"达到目标数"且每位有效达人 F05 与 F06 全部完整时为 `COMPLETED`，否则 `PARTIAL_COMPLETED`（原因区分模块失败、精选不完整、未注册 F06、搜索耗尽）。`refresh_counts` 同时统计 `profile_complete_count`、`featured_complete_count` 与 `featured_status`。

## 主要替代方案与否决理由

- 用 `browser_context.request` 抓封面：无法被上下文路由拦截因而不易在离线契约测试中验证，且与页面会话的 Cookie/线路关系不够直接；改为页面内 `fetch`，同时显式实现重定向计数与逐跳主机校验（Playwright 的 `max_redirects` 无法在页面内复用）。
- 把增量加载建模为多个请求键（`cards`、`cards_more`…）：契约随页数膨胀，且无法表达"同一请求多次触发"；`repeats` 更贴近平台行为。
- 允许修改 `featured_collections`/`featured_cards` 行：与 §14.4"发布快照不可修改"冲突；追加式表 + 新观测更安全。
- 无稳定集合标识时也复用旧观测：无法证明集合未变化，会伪造同一时点列表；规范明确此时不得承诺跨重试冻结。
- 未取得封面时直接把集合标为完成：违反"链接或封面取得失败不得伪装完整"。
- 把两组集合的完成度并入 `profile_complete`：会掩盖 F06 缺口；保持两个计数并在 `pipeline_complete` 汇总。

## 兼容性与影响

- 迁移 003 仅新增对象，已在既有 `xingtu_local_dev` 上顺序应用且幂等。
- 新增字段均有默认值，旧检查点/任务 `payload` 仍可反序列化；旧语义（`NOT_ATTEMPTED`/`pipeline_complete=false`）保持不变。
- `Repository.create` 的幂等摘要新增两组集合类型与版本，纳入同键同内容判定。
- `Engine.finish` 不再固定 `PARTIAL_COMPLETED`；未注册 F06 时行为与改造前一致（仍为部分完成），F05 的既有离线用例无回归。
- 恢复到与检查点不一致的两组集合注册表时按 `FEATURED_REGISTRY_CHANGED` 停止。

## 最小验证

- 单元 35 项：领域状态与顺序、指纹、封面引用与管道分支、注册表发布与 18 项拒绝原因。
- 浏览器契约 3 项：真实 Chromium 上两组模块的增量加载、去重、越界不采集、跨组身份与独立指标、截断、终点/空态/无权限、单组失败隔离、封面对真实页面会话抓取。
- 集成 3 项：完整度与终态、集合/卡片/身份/快照落库、封面认证访问与孤儿清理、失败补采与集合变化生成新观测、相同集合复用。
- E2E 1 项：真实 Activity + Workflow 的 `COMPLETED` 传播与历史回放。
- 全量四层共 129 项通过；命令记录见 [F06 离线验证证据](../evidence/F06-offline-verification.md)。

## 限制

真实两组默认集合的边界、稳定集合标识、终点、作品 ID/链接、完整标题/副标题与封面 CDN 白名单仍未核验（U05），随包注册表 `featured` 保持 `[]`；`S3CoverStore`、MinIO、认证图片访问的实机验证与备份/告警运维仍属 U09，未通过前不得宣称封面存储已生产就绪。
