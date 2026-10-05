# 项目进度基线：2026-09-27

## 核查方法与范围

- 本轮在现有macOS工作区读取规范、完整技术方案、四张历史卡片、开发说明、历史证据；使用 `rg --files`、`rg -n`、`cat`、`sed` 定向检查源码、迁移和测试。
- 未发现 `.code-review-graph/graph.db`，本会话也无可用code-review-graph工具，因此按规范使用文件级盘点。未声称做过代码图分析或全面缺陷审计。
- 这是静态进度盘点，不是重新执行全部功能测试。未读取密钥/profile内容，未启动真实平台采集。
- 2026-09-27用户确认：设备齐全、真实账号已有；先本机IP+Chrome+账号本地验证核心检索与采集，再落地蜂窝线路。此为资源与优先级说明，不是设备/平台实测报告。

## 已核对的关键代码证据

| 结论 | 文件与定位依据 | 边界 |
|---|---|---|
| 有明确计划/能力/字段/检查点契约 | [domain.py](../../backend/src/xingtu/domain.py)：FilterPlan、Capabilities.validate_plan、FieldObservation、Checkpoint、TaskRecord | 无原表单到模型转换实现；featured_status限定NOT_ATTEMPTED |
| 真实平台启用门槛存在 | [contracts.py](../../backend/src/xingtu/contracts.py)：PlatformRegistry.require_enabled；[注册表](../../contracts/douyin_xingtu.unverified.json) | session/search为空、modules为空，UNVERIFIED不能用于live采集 |
| 浏览器搜索/主页及响应关联已有 | [adapter.py](../../backend/src/xingtu/adapter.py)：prepare/search/profile/collect_module；[observer.py](../../backend/src/xingtu/observer.py)：ResponseCollector | 真实定位与字段字典尚无已启用配置 |
| 候选、游标重扫、预算与主页恢复已有 | [engine.py](../../backend/src/xingtu/engine.py)：run/collect/rescan/finish | finish固定PARTIAL_COMPLETED；没有F06或指定达人刷新分支 |
| 事务、围栏、快照与内部命令已有 | [repository.py](../../backend/src/xingtu/repository.py)：create/edit/command/persist_creators/results | create接受已校验计划并绑定单元；results读取发布快照；产品幂等API和草稿查询需补 |
| 数据模型只覆盖当前交付 | [001_initial.sql](../../migrations/001_initial.sql) | 无users/sessions/requirements/model_runs、精选集合/卡片/封面表；filter_plans.source仅internal_acceptance |
| 有工作流与固定单元Worker | [workflow.py](../../backend/src/xingtu/workflow.py)、[worker.py](../../backend/src/xingtu/worker.py) | max_concurrent_activities=1，队列按unit_id；不等于可用单元FIFO产品调度完成 |
| 本地验证模式需要显式补齐 | [runtime.py](../../backend/src/xingtu/runtime.py)：UnitConfig、ensure_line、BrowserRuntime | 当前必填proxy_server与线路证明，不能通过伪造生产证明来启用本机IP |
| 有本地人工登录基础 | [cli.py](../../backend/src/xingtu/cli.py)：login | 必须已有session入口，终端回车确认；无远程浏览器产品会话 |
| 有脱敏证据存储 | [evidence.py](../../backend/src/xingtu/evidence.py)：S3EvidenceStore/FileEvidenceStore | 非封面下载器；登记expires_at不代表清理任务存在 |
| 无完整产品应用部署 | [pyproject.toml](../../pyproject.toml)、[compose.yaml](../../deploy/compose.yaml) | 无FastAPI依赖/frontend目录；Compose仅依赖服务，无API/前端/采集应用容器 |
| 已有E2E是离线编排验证 | [test_temporal.py](../../tests/e2e/test_temporal.py) | 使用SyntheticAdapter及自定义测试Activity，无真实Activities.collect或产品全链路 |
| smoke-live是启动入口 | [commands.py](../../scripts/commands.py)：smoke-live | 检查1—3位并调用start；成功提交不能当作任务完成验收 |

## 历史证据与已知遗留

[2026-09-26验证报告](F04-F05-offline-verification.md)与[日志](F04-F05-offline-verification.log)记录74项测试通过。本轮只核对报告与测试实现，未重跑，不把其覆盖扩展为T01—T42全部通过。

- 历史证据明确：make dev因Docker守护进程不可用失败；make setup/stop/smoke-live未执行，S3/MinIO未实测。本轮未重新检测Docker状态，不能把历史环境故障称为当前事实。
- F05卡保留入口页面跳转后DOM字段身份复核缺口；本轮检查collect_module确认跳转前核对身份、跳转后检查URL和会话，未再次调用verify_identity。由F05核验并处理，不在本次规划中静默修复或删除。
- 既有agent.md对命令“可用”表述宽泛，以BASE-01和实际历史证据的逐项执行结论为准；本轮补充了基线说明。
- 原UNIT-01的资源未到位原因已被用户本轮说明更新；仍保留2026-09-26历史记录。U07/U08实测未关闭。

## 本轮文档验证

验证范围：新增/更新Markdown的本地链接、12个交付ID唯一性、卡片必需字段、看板状态一致性、F01—F11/U01—U09/T01—T42覆盖、原四卡历史及验收勾选保留。

- 2026-09-27T09:52:49+08:00：执行 `python3 /tmp/check_project_plan.py`，退出码0。检查12个交付ID、每卡必需字段、卡片与索引状态、总览卡片入口和167个本地Markdown引用，全部通过，断链0。
- 状态统计校验：待验收3、进行中1、待办8；PLAN-01独立于产品12项。
- 人工对照确认：F01—F11、U01—U09及T01—T42分组覆盖完整；原四卡勾选项与历史记录保留，新增本地验证清单未预先勾选。
- 纯文档交付未重跑应用测试，也未将任何业务验收项由未通过改为通过。临时检查脚本仅用于本次文档交付，不新增工程命令契约。
