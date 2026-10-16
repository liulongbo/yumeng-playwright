# FILTER-01：巨量星图背景信息与受众画像筛选

状态：已完成  
更新时间：2026-10-15T14:35:00+08:00

## 目标与范围

在现有 M3 产品入口、F04 搜索与采集链路上增加巨量星图已实测的八个业务控件：达人性别、所在地域、学历、黄 V 认证、连接用户数、粉丝量级、观众画像、粉丝画像，并保留 Keyword 与目标达人数。新增 `requirement_form.v2`、`filter_plan.v2`、结构化能力 DTO、局部页面筛选执行器及 `attribute_filter` 多重集相关性校验；历史 v1 数据继续可读，现有 JSONB 列不变。

本卡不重构 Scheduler、Temporal Workflow 图拓扑、达人解析、去重、数据库写入或任务状态机；不提交、推送或合并 Git。

## 关联与依赖

- 前置：[F04](F04.md)、[INTAKE-01](INTAKE-01.md)、[UNIT-01](UNIT-01.md)。
- 正确执行单元：`unit-local-mac-02`；绑定账号 `ID: 1807978499337419`；Chrome Profile `.runtime/profiles/unit-local-mac-02`。
- 会话快照私有根：`.runtime/profiles`。不得以 `.runtime` 或隔离浏览器的状态判定该执行单元失效。
- 实现方案：用户于 2026-10-14 批准的《星采新增巨量星图背景信息与受众画像筛选条件功能实现方案》。

## 验收清单

- [x] FILTER-01A：固化脱敏字段字典、34/452 地域树、请求字段映射、控件与账号证据。
- [x] FILTER-01B：RequirementForm v2、FilterPlan v2、复合值、范围／地域／互斥校验完成；v1 历史数据仍可读。
- [x] FILTER-01C：M3 机械映射、`m3-filter-plan-v2` Prompt 与嵌套 exact-diff 完成；不改变图节点和边。
- [x] FILTER-01D：能力 API 发布结构化控件；前端完成两个分区、八个控件、二选一提示和提交摘要。
- [x] FILTER-01E：浏览器执行器支持文本、单选、级联、区间／区间组、画像组；准备动作与最终响应捕获分离；定位漂移 fail closed。
- [x] FILTER-01F：`attribute_filter` 按字段名、可选 `rel_id`、值作条件数组精确多重集匹配；支持两个 `persona_tag_level_one`，拒绝残留业务条件。
- [x] FILTER-01G：Schema、M3、能力、Adapter、相关性、API/持久化、前端及回归自动化通过；全量集成环境另有前置缺失。
- [x] 真实 Chrome 最小用例已记录步骤、预期、实际、PASS/FAIL/BLOCKED、截图、脱敏请求与任务/数据库证据；筛选验收通过。根任务的资料范围状态另按既有 F05/F06 范围追踪，不阻断本卡。

## 实现记录

- 2026-10-14T21:28:44+08:00：用户批准完整方案，创建任务卡并开始实施。已确认只在现有 MVP 上局部扩展，不新增数据库迁移；工作区原有大量未提交修改均视为用户所有，不整理或覆盖无关变更。
- 页面调研结论：学历与黄 V 会生成两个同名 `persona_tag_level_one`；地域整省写 `province`、子级写 `city`；连接用户和粉丝量由页面 `w` 换算为人数；观众画像与粉丝画像双向互斥；每次选择均会触发中间搜索，最终请求必须在独立捕获窗口中关联。
- 2026-10-15：以正确执行单元重新只读导出地域树并复核为 34/452；`xingtu-ad-creator-square-v2` 已写入完整树、九个含 Keyword 的产品字段、选项/平台值、范围、画像维度、请求映射、定位元数据、互斥策略及 v1 Keyword 兼容版本。证据见[字段字典](../evidence/FILTER-01-live-filter-dictionary-2026-10-14.md)。
- 2026-10-15T08:55:27+08:00：M3 PostgreSQL 集成测试发现原 `requirements_schema_version_check` 只允许 `requirement_form.v1`。方案中“无需迁移”的判断只覆盖 JSONB 列形状，遗漏了 discriminator CHECK；已增加 `013_requirement_form_v2.sql`，仅将约束放宽为 v1/v2，不新增列、不改写历史 payload。
- 2026-10-15：完成 v2 Schema/计划/M3、能力 API 与前端、页面筛选执行器和 `attribute_filter` 多重集匹配；修复 `m3-up` 前端工作目录，使本地 M3 监督器可正常启动。开发库已执行 `013_requirement_form_v2.sql`。
- 2026-10-15：在正确单元的真实 Chrome 完成 Keyword-only、背景信息、地域省/市、五段连接区间、粉丝预设/自定义、两类画像及互斥、完整组合验收。星采真实任务已验证 v2 JSONB 入库、M3 计划、请求捕获、候选和前端结果；失败步骤重试一次后仍为 `PROFILE_SCOPE_INCOMPLETE`。完整记录见[验收报告](../evidence/FILTER-01-acceptance-2026-10-15.md)。
- 2026-10-15T14:35:00+08:00：用户确认本卡的交付范围是新增筛选能力；`PROFILE_SCOPE_INCOMPLETE` 由已有达人详情资料字段采集导致，与背景信息和受众画像无关。保留失败证据，不改业务代码，将本卡收口为已完成。

## 验证证据

- 地域树只读复核脚本 exit 0：`province_count=34`、`child_count=452`；注册表反序列化通过，能力字段 9 个。
- Keyword-only 真实适配器：PASS，正确 Profile、候选 20、最终窗口严格 1 request/1 response，页面回显“搜索词：汽车”。
- 完整组合真实适配器：PASS，最终窗口严格 1 request/1 response；页面回显 Keyword、四项背景、连接用户、粉丝量级与粉丝画像，两个同名 `persona_tag_level_one` 均完成多重集关联；本组筛选结果为 0 位达人。
- 迁移后 `backend/tests/integration/test_product_m3.py`：17 passed；后端 unit：213 passed；FILTER-01 浏览器契约：21 passed；前端：61 tests passed 且 build 通过；Ruff 与 mypy 通过。
- 真实端到端重试后：检查点 62 request / 62 response / 0 duplicate、20 candidates、1 valid；筛选请求与候选链路通过。任务终态的 `PARTIAL_COMPLETED / PROFILE_SCOPE_INCOMPLETE` 由已有资料范围字段失败导致，详见验收报告。

## 后续观察（不阻断本卡）

- 平台选项与行政区树可能漂移；注册表必须版本化，任何未知值或选择器漂移均失败关闭。
- 连接用户组件占位文本与实时 `max` 不一致，按已实测有效约束 `0–100w` 实现并保留证据。
- 真实浏览器用例会产生平台搜索流量；只按本卡最小样本执行，不扩大目标人数。
- 本次真实任务的 `PROFILE_SCOPE_INCOMPLETE` 来自既有主页资料采集：`seeding` 6 项及 `conversion` 9 项为 `MODULE_TIMEOUT`，`fulfillment` 3 项为 `MISSING_SOURCE`、1 项为 `MODULE_TIMEOUT`。后续应在独立资料采集任务中分别诊断页面等待/请求条件与字段来源/契约映射；不得以此反推新增筛选失败。
- 全量集成命令仍需显式隔离 `XINGTU_TEST_DATABASE_URL`；这是测试环境前置，未影响本卡的专项或真实筛选验收。

## 状态历史

- 2026-10-14T21:28:44+08:00：建立 → 进行中；开发授权已给出，开始 FILTER-01A—G。
- 2026-10-15T14:10:00+08:00：进行中 → 部分完成／验收受阻；实现和专项验收完成，等待资料范围完成计数问题与隔离集成环境处理。
- 2026-10-15T14:35:00+08:00：部分完成／验收受阻 → 已完成；用户确认资料范围字段失败属于既有 F05/F06 问题，新增背景信息与受众画像筛选已经完成并通过真实 Chrome 验收。
