# DEC-002：游标失效恢复与"无进展"判定

- 日期：2026-09-26
- 状态：已采纳并实现

## 待解决问题

技术方案 5.2.3 要求：游标失效时在原条件下从起点重新扫描，用持久化已见身份去重，不重新分配已有候选的首次位置，并记录搜索代次与重扫原因。5.2.2 的停止条件表同时要求"游标循环、持续无进展、结构不符 → `PLATFORM_PAGE_CHANGED`"和"滚动高度不变、当批无新 ID → 先核查加载状态、容器和终点；单独出现不算耗尽"。

原实现存在两个缺陷：

1. 注册表声明了 `cursor_invalid_codes`，观察器也按契约抛出 `PLATFORM_PAGE_CHANGED:SEARCH_CURSOR_INVALID`，但 Engine 只在 `prepare()` 返回 `False` 时重扫。搜索中途游标失效会直接冒泡到 Activity，任务判为 `FAILED`，并且 `record_error` 会把整个 `contract_version` 置为 `disabled`，屏蔽后续所有新任务。这是可恢复状态被误判为契约改版。
2. `no_progress_pages >= 3` 即抛 `NO_PROGRESS`。重扫必然连续经过若干"已见身份"的页面（5.2.3 明确要求用已见身份去重），因此该规则会杀掉合法的重扫：目标 200、每页 50 时重扫前 3 页即失败。

## 选择

1. Engine 捕获 `SEARCH_CURSOR_INVALID`：计入本段主动时间 → `rescan()`（代次 +1、游标清空、`rescan_reasons` 追加 `CURSOR_INVALID`、已见身份与首次位置保留）→ 重新 `prepare()` 回读条件 → 继续扫描。**不禁用契约**。
2. 删除 3 次即失败的 `NO_PROGRESS` 规则，保留 `no_progress_pages` 作为无新身份的观测计数。重复游标仍由 `CURSOR_LOOP` 拒绝；持续无新身份的扫描由扫描预算（`PAUSED_BUDGET`）与主动时间预算限制，不把"无新 ID"本身当作耗尽或契约失效。

## 主要替代方案与否决理由

- 保持现状（中途游标失效即失败）：违反 5.2.3，且把可恢复状态升级为全局契约失效。
- 保留 3 次 `NO_PROGRESS` 但重扫时豁免：豁免范围难以界定，且重扫本身就是"连续无新身份"，等于永不触发。
- 为 `NO_PROGRESS` 另设重扫窗口计数：需要引入文档未定义的阈值，属于自行扩张规则。

## 最小验证

- `test_mid_scan_cursor_expiry_rescans_and_keeps_contract_enabled`：第 2 次搜索抛 `SEARCH_CURSOR_INVALID` → 任务达目标、`search_generation=1`、`rescan_reasons=["CURSOR_INVALID"]`、`contract_health` 无记录。
- `test_rescan_over_known_identities_is_not_a_contract_failure`：目标 5，第 5 次搜索失效，重扫连续经过 4 个已见身份后补足 → 正常完成，`scanned_ids` 每个身份只占一个槽位。
- `test_invalid_cursor_rescans_and_preserves_first_positions`、`test_looping_cursor_fails_not_exhausted` 保持通过。

## 限制

- 平台若在每次重扫后立刻再次使游标失效，循环由主动时间预算终止（`PAUSED_BUDGET`，可继续），不设人为重扫次数上限。
- 真实游标形态与失效码仍属 U04，未核验前注册表保持 `UNVERIFIED`。
