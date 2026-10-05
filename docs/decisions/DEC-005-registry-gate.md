# DEC-005：注册表补齐与发布门槛

- 日期：2026-09-26
- 状态：已采纳并实现

## 待解决问题

技术方案 6.2.2 要求 `ProfileModuleSpec` 至少包含：模块标识、顺序、基础/可选标记、入口页面、标签页及展开动作、就绪条件、请求契约集合、DOM 契约、字段字典、模块缺失/权限/空态证据、超时和检查点版本。6.2.4 要求"整体空态、无权限或不提供在证据成立时可完成检查"，即模块级缺失必须能与读取失败区分。13.5 要求未验证路径填 `null` 并标记 `UNVERIFIED`，"不得当作可执行配置发布"。

原实现缺少入口页面、模块级缺失证据、逐模块超时、检查点版本与模块级默认条件；模块整体无权限只能表现为每个字段 `FAILED`，与读取失败无法区分；`require_enabled` 不校验引用完整性，字段引用未声明的请求键要等到运行时才逐个失败。

## 选择

1. `ProfileModuleSpec` 增加：`entry`（入口页面，相对路径或平台主机内的绝对 URL）、`default_bindings`（模块级默认条件，如页面默认统计口径）、`ready_hidden`（必须消失的加载提示）、`timeout_seconds`（缺省回落到注册表的 `operation_timeout_seconds`）、`checkpoint_version`、`absence`（`ModuleAbsenceSpec`：探针来源 + 空态/无权限/平台不提供的登记取值）。未核验项默认 `null`/`1`。
2. `SearchSpec` 增加 `ready_hidden`，与模块共用同一就绪判定（加载提示消失 → 就绪定位可见）。
3. 模块级缺失证据成立时，该模块全部应检查字段以对应状态（`NO_DATA`/`NO_PERMISSION`/`NOT_PROVIDED`）加证据引用写入，并按 6.2.4 判定"检查已完成"；探针不可读时**不**判缺失，回落到字段级解析，读取失败永远不会被当成空数据。
4. `require_enabled` 增加 `_validate_references()`：请求键唯一且主机在 `allowed_hosts` 内、`result_request_key` 必须已声明、搜索契约路径与回读定位齐全且分页必须有已注册的推进动作、字段来源引用的请求必须已声明、`fallback` 必须同时声明 `fallback_on`、数值字段必须有单位、报价必须有币种与合作形式、分布必须有维度、字段与模块的缺失取值不得跨状态歧义、`entry`/入口 URL 必须在平台主机范围内、业务错误码必须属于附录 B。
5. 检查点记录 `profile_checkpoint_versions`；恢复时与适配器版本不一致即停止并记 `MODULE_CHECKPOINT_CHANGED`（6.2.4"恢复遇到能力变化…无法兼容则停止并记录版本问题"）。

## 主要替代方案与否决理由

- 不扩展 schema、只做行为修复：模块整体无权限与读取失败无法区分，T07/T09 无法满足。
- 把模块级缺失实现为"字段定位不到就算空态"：规范明确"元素未找到本身不足以判定"，会伪造平台未提供。
- 在运行时逐字段发现引用错误：错误定位晚、且会把配置错误伪装成平台契约变化；发布门槛更合适。

## 兼容性与影响

- 全部新字段都有默认值，既有已核验注册表不受影响；`douyin_xingtu.unverified.json` 仍为 `session/search = null`、`modules = []`，保持不可发布。
- `Repository.create` 增加可选的 `module_checkpoint_versions` 并纳入幂等摘要；未传时行为与摘要保持稳定。
- `ExecutionConfig.budget`（见附录 A 默认值）与 `UnitConfig.budget` 使"预算引用"可配置，Engine 不再硬编码预算。

## 最小验证

- 单测 `test_referenced_registry_is_publishable` 与 21 项 `test_unpublishable_registries_are_rejected` 覆盖上述每条引用校验及其失败原因码。
- 契约测试在合成路由来源上验证模块 `entry` 跳转、`default_bindings` 参与请求关联、`ready_hidden`、逐模块超时与模块级 `NO_PERMISSION`（`complete=True`）。
- 集成测试 `test_module_checkpoint_version_change_stops_the_attempt` 覆盖检查点版本不兼容停止。
- 集成测试 `test_budget_reference_comes_from_execution_context` 覆盖执行上下文预算被采用。

## 限制

所有真实路径仍为 `null`：入口页面、选择器、请求契约与缺失取值必须在 U02/U04 用真实账号核验后才能填入并标记 `VERIFIED`。
