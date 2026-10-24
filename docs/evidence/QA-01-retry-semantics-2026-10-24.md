# QA-01 重试语义核验：第一位资料不完整时是否从头重爬（2026-10-24）

## 1. 问题

目标 2 位达人；采到第 1 位时任务中断，且第 1 位主页资料不完整。重试任务时，是否会从零重新爬第 1 位？

## 2. 结论

**不会把第 1 位当成新任务从头全量重爬；会从检查点恢复，并优先补采第 1 位未完成的模块。**

但有三点必须区分：

1. 搜索页可能从 page=1 重扫。当前契约 resume_supported=false，重试后搜索可能重新取第一页；已有候选按 platform_creator_id 去重，不会重复创建第 1 位，也不会把 valid_count 归零。
2. 达人主页会重新打开第 1 位；但 _collect_once 会跳过 modules[key].complete 的模块，只采集缺失模块（[engine.py](../../backend/src/xingtu/engine.py#L453-L467)）。
3. 旧快照不覆盖；补采产生新的观测/快照，历史快照保持不变。

如果第 1 位的 basic 模块本身没有完成，则会重新采 basic（因为它属于缺失模块）；如果 basic 已完成、只是 fans/commercial 等模块失败，则只补那些失败模块。这不是“整任务从头重采”。

## 3. 数据与状态

重试前任务 2ff8ad00-1436-4be6-850f-c2129881849b（target=1，已有 valid=1、快照=1，PROFILE_SCOPE_INCOMPLETE）：
- task_creators：1；
- creator_snapshots：1（12:02:43）；
- 第 1 位候选 state=done，valid=true；
- checkpoint navigation_count=4，processed_operations=1。

通过 Playwright MCP 从任务页点击「重试失败步骤」后：
- 第 1 位候选 state 从 done 变为 pending；
- valid_count 仍为 1，快照仍为 1，未被删除或重建；
- 任务进入 WAITING_FOR_VERIFICATION，PLATFORM_SECURITY_CHALLENGE；平台安全验证阻止了后续主页模块补采。

因此，本轮真实重试只完成了“选中第 1 位并准备补采”，没有完成最终模块补采；未把未完成补采伪报为成功。为避免占用执行单元，测试任务已取消，最终状态 CANCELLED（version=109）；原有 1 位有效达人/1 份快照保留。

## 4. 代码与现有集成测试

仓库已有集成测试 backend/tests/integration/test_engine.py::test_optional_failure_keeps_basic_and_retry_new_observation，构造 2 位 valid 达人、fans 模块失败，重试后断言：

- 只有 fans 模块被重新采集（all(key == "fans" for _, key in repaired.modules)）；
- 第 1 位 basic 的 observation ID 不变；
- 重试前快照与重试后读取的旧快照完全一致；
- profile_complete_count 从 0 补到 2。

该测试需要隔离 PostgreSQL（XINGTU_TEST_DATABASE_URL），本次未在当前工作区执行；它是对该行为的脚本级证据。

## 5. 目标 2 的推演

目标数只决定何时停止，不改变重试的候选选择：

1. 重试保留 valid_count=1、task_creators 和已有快照；
2. Repository.retryable 把第 1 位（valid + 模块不完整）置 pending；
3. Engine.run 先选 valid+pending 的第 1 位（[engine.py](../../backend/src/xingtu/engine.py#L239-L254)）；
4. 补完第 1 位后才继续第 2 位；
5. 搜索页若从第 1 页重扫，按平台 ID 去重，不会把第 1 位重复计为第 2 位。

## 6. 结论边界

- 如果第 1 位只有“发现”身份、basic 未完成：重试会从 basic 开始采第 1 位；
- 如果第 1 位 basic 已完成、部分模块失败：只补缺失模块；
- 如果进程在终态收口前被硬杀：已有 task_creators/checkpoint 保留，快照可能尚未发布，恢复后补发布；
- 如果用户新建任务而不是重试原任务：新任务会重新搜索，已入库达人可复用，但这是新 root task，不属于“重试”。
