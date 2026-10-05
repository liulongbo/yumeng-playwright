# DEC-003：无身份搜索行的诊断记录

- 日期：2026-09-26
- 状态：已采纳并实现

## 待解决问题

技术方案 5.2.2 要求：搜索每批候选必须规范化平台身份与真实主页链接；"节点缺少已验证身份时不得按昵称去重或拼接主页"，"无效身份留诊断记录，不增加有效数"，并明确"唯一身份候选按原扫描预算计量，无身份且持续无进展由契约异常和主动时间预算限制，不能无限循环"。同一节的停止条件表又要求"结构不符 → `PLATFORM_PAGE_CHANGED`"。

原实现遇到任一行缺少平台 ID 或无有效主页即抛 `PLATFORM_PAGE_CHANGED`，整任务失败且禁用契约：既没有"留诊断记录"，也把局部脏行升级为全局契约失效，同时把可继续的搜索变成不可恢复失败。

## 选择

1. `SearchPage` 增加 `unidentified: list[CandidateDiagnostic]`（原因、结构路径、操作/来源引用、`operation_id`），`Checkpoint` 增加 `diagnostics` 持久化诊断。
2. 适配器对每行判定：平台 ID 缺失/非法 → `CANDIDATE_IDENTITY_UNREADABLE`；主页缺失或不在已验证主机/路径范围 → `UNVERIFIED_HOMEPAGE`。两种情况都跳过该行、记诊断、不计入候选，其他行照常处理。
3. 不新增去重或拼接：无效行不按昵称归并，也不构造主页。
4. 循环保护依赖既有机制：重复游标 → `CURSOR_LOOP`；持续无新身份 → 扫描预算（`PAUSED_BUDGET`）与主动时间预算（见 DEC-002）。

## 主要替代方案与否决理由

- 保持现状（立即 `PLATFORM_PAGE_CHANGED`）：与 5.2.2"留诊断记录，不增加有效数"直接冲突，并把局部脏行误报为页面改版。
- 按昵称或标题自动归并无效行：规范明确禁止。
- 把无效行计为扫描数但不计有效数：会占用扫描预算并掩盖契约问题；当前按身份去重计量，无效行不进入 `scanned_ids`。

## 兼容性与影响

- 诊断条目只包含结构路径与原因，不含平台正文、URL 或凭据，可安全持久化在 `task_checkpoints`，并随 CLI `status` 的 `unidentified_rows` 输出。
- `SearchPage` 新增字段有默认值：既有构造点与反序列化数据保持兼容。
- `xingtu status` 的输出结构扩展了字段，不删除既有字段。

## 最小验证

- 契约测试 `test_unreadable_rows_become_diagnostics_not_candidates`：真实适配器在合成路由来源上遇到"缺 id"和"越界主页"两行 → 候选只剩合法行，诊断原因按顺序为 `CANDIDATE_IDENTITY_UNREADABLE`、`UNVERIFIED_HOMEPAGE`。
- 集成测试 `test_unreadable_rows_are_persisted_as_diagnostics`：诊断写入检查点，有效数只统计合法候选。

## 限制

真实平台的 `id_path`/`homepage_path` 仍属 U04，未核验前注册表保持 `UNVERIFIED`；诊断只说明"本行不可用"，不代表平台字段缺失。
