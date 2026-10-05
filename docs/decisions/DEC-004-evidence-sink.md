# DEC-004：脱敏证据的写入与保留

- 日期：2026-09-26
- 状态：已采纳并实现

## 待解决问题

技术方案 5.2.2 要求搜索保存"实际已选条件与必要页面证据"，6.2.2 要求模块失败保留证据，17.1 规定失败证据 30 天、必要摘要 90 天且凭据不得进入日志或对象存储，15.3 要求业务快照的元数据不依赖临时证据。原实现的 `EvidenceStore`（S3 + `raw_evidence`）从未被调用，`FieldObservation.evidence_refs` 只是 `operation:field` 形式的本地字符串，没有可追溯的证据制品。

## 选择

1. 抽出 `EvidenceSink` 协议与 `EvidenceSummary`（允许列表结构：根任务/子任务/尝试、执行单元、`operation_id`、契约版本、结构键、HTTP 状态、失败原因），明确不接受正文、请求头、URL、Cookie 或令牌。
2. 提供两种实现：`S3EvidenceStore`（S3 兼容，先上传校验再引用再登记）与 `FileEvidenceStore`（本地 `0600` 文件，目录限制在运行根目录内，同样先写后校验再登记）。`EvidenceConfig.kind` 默认 `local`，配置为 `s3` 时必须提供 `endpoint` 与 `bucket`。
3. `Engine` 在三处写入证据并引用：
   - 搜索终点/空结果：`kind=summary`，其对象键追加到 `exhaustion_evidence_refs`（先上传再在检查点事务中引用）。
   - 模块级失败（`MODULE_COLLECTION_FAILED`）：`kind=failure`，键写入失败观测的 `evidence_refs`。
   - 任务级诊断类错误（页面契约、条件不一致、需登录、安全挑战、限流、模块失败）：`record_error` 写 `kind=failure`。
4. 存储失败抛 `STORAGE_UNAVAILABLE`，不静默丢弃证据（对应附录 B"不虚报落库成功"）。

## 主要替代方案与否决理由

- 继续不接入：搜索耗尽与模块失败将没有可追溯证据，5.2.2/6.2.2 无法满足。
- 只保留 S3 实现：离线与本地验证无法覆盖证据路径，且 MinIO 未运行时 F04/F05 无法验证。
- 把响应正文或 HAR 存入证据：规范禁止（凭据与正文不得进入对象存储）。
- 在证据失败时继续并静默降级：属于吞异常，且会让"已记录耗尽证据"变成假陈述。

## 兼容性与影响

- `raw_evidence` 表与保留策略沿用迁移 001，无新迁移。
- 本地实现写入 `.runtime/evidence/<kind>/<root_task_id>/<sha256>.json`，与 profile 一样要求 `0700/0600` 权限，不进入版本库。
- 证据是辅助制品：业务字段、单位、周期与状态元数据随快照长期保存，证据过期不影响历史结果解释。

## 最小验证

- `test_evidence_records_exhaustion_and_module_failure`：一次合成运行产生 1 个摘要 + 1 个失败证据，`record_error` 再产生 1 个失败证据；文件数量与 `raw_evidence` 分组计数一致，文件权限不含 `0o077`；耗尽引用包含对象键，模块失败观测携带证据键。

## 限制

MinIO/S3 路径未在本地实测（Docker 守护进程未运行），仅覆盖本地实现与接口；`S3EvidenceStore` 需在具备对象存储的环境补验证（U09）。
