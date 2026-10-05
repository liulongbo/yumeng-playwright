# AUTO-01 有界浏览器宿主实施交接

日期：2026-09-28（Asia/Shanghai）  
状态：**本批已实现，并在真实账号上通过维护→采集交接**（2026-09-28 后续会话完成；见[真实运行证据](../evidence/AUTO-01-bounded-host-real-run-2026-09-28.md)）。第八节验收标准中"同一上下文交接 / 单事务带 fencing 可审计 / 空闲关闭回 `NEEDS_LOGIN`"已满足；"登录成功后原 root task 和检查点继续（经 Temporal 幂等唤醒）"**尚未取得证据**——本轮由 `make smoke-local` 直接启动工作流，未走 `dispatch`/`queue_login_resumes` 路径。第七节第 7 步与第八节该项仍是下一步工作。
任务卡：[AUTO-01](../tasks/AUTO-01.md)

## 一、用户授权与本批目标

用户已明确同意：按“**每执行单元一个有界浏览器宿主、同一 Chrome 上下文完成登录维护到采集交接**”继续实现。

本批目标是解决真实平台实验证明的会话生命周期问题：人工在 Chrome 完成短信／账号密码登录后，不关闭该 Chrome，不把 BrowserContext 跨进程传递；在同一宿主内验证账号、受保护业务能力和线路，再通过带 fencing 的状态切换让原 Temporal 任务继续采集。

允许修订原技术方案。原方案中的“暂不重构跨任务常驻浏览器服务”已被真实证据否定；应替换为“每执行单元一个有租约、空闲超时和隔离边界的浏览器宿主”。这不是无边界、多账号、永久驻留服务。

## 二、用户确认的范围

- 继续使用 Chrome + Playwright。
- 继续使用 Chrome 的正常短信／账号密码登录入口。
- 本期不开发自动短信收码或验证码代填。
- 人机挑战只检测、暂停和人工处理，不自动求解。
- 不接官方 API，不采购第三方付费数据。
- 不以全量签名逆向作为交付依赖。
- 不做账号轮换、代理轮换或通过更换请求路径绕过挑战／权限拒绝。
- 可以修改原技术实现方案，以真实证据和当前最佳方案为准；必须同步技术方案、决策记录和任务卡。

## 三、必须继承的真实证据

1. 人工登录后的同一 Chrome 上下文可以进入 `/ad/creator/index` 和 `/ad/creator/market`。
2. 同一上下文可以完成关键词搜索和主页业务响应观察。
3. 关闭 Chrome 后，即使复用相同 profile，也不能恢复星图受保护业务会话：直达后台回到公开页，从“客户”入口进入 SSO。
4. 因此“登录 CLI 关闭浏览器，再由 Worker 重开 profile”不是可用恢复方案。

> **2026-09-29 更正（历史交接文档，保留原文）**：第 3 条的"不能恢复"**证据不足，已撤回为"未经证实"**。当时的复核**未比对账号 ID**（只判断受保护元素可见），可能是测量假象；用户日常 Chrome 实测可 7-8 天免登录，而项目独立 profile 约 45 分钟失效。见 [SESSION-01](../tasks/SESSION-01.md) 与 [DEC-012](../decisions/DEC-012-session-persistence.md)。第 4 条**仍然有效**：对象不跨进程传递，登录维护与采集必须由同一宿主在同一上下文交接。
5. 关键词“美妆”第一页真实返回 20 位，`has_more=true`、`total_count=2000`。
6. UI 滚动到底没有产生第 2 页请求，也没有下一页控件。
7. 同一页面上下文以内存复用原生请求体和必要请求头后，第 2 页真实成功；两页身份集合摘要不同。
8. 当前生产契约只开放到第 2 页；第 3 页及分页终点未验证，超过边界必须返回 `SEARCH_CAPABILITY_LIMIT`，不能报告平台耗尽。
9. 已观察主页基础、报价、传播、种草、履约、转化／本地销售数据面；画像、创作能力和精选作品尚未完整验证。
10. 主页出现过 `rmc.bytedance.com/verifycenter/captcha/v2` 挑战 iframe；即使部分接口仍返回成功，也必须停止并等待人工维护。
11. 历史真实业务码 `10003` 已登记为 `PLATFORM_PERMISSION_DENIED`。

证据文件：

- [阶段一验证记录](../evidence/AUTO-01-stage1-2026-09-28.md)
- [当前账号能力与字段盘点](../evidence/AUTO-01-current-account-inventory-2026-09-28.md)
- [历史真实采集记录](../evidence/UNIT-01-real-collection-2026-09-27.md)

## 四、当前代码与运行状态

已实现：

- 搜索能力限制和平台耗尽分离。
- 任务要求字段及版本化覆盖，完整度不再由已注册模块反推。
- 登录、挑战、权限、额度、网络和契约异常分类。
- 请求／响应、模块耗时、失败和人工等待等指标基础。
- Chrome 关闭 20 秒确认上限；关闭未确认不能报告 `browser_stopped=true`。
- CLI 登录在关闭后重新打开 Chrome 复核受保护业务页；失败保持 `NEEDS_LOGIN`。
- `Repository.invalidate_session`：只允许浏览器已停止且单元无人持有时失效会话，并写审计。
- 搜索请求的同源、同路径、POST、请求体游标绑定和内存请求头复用。
- live 契约 `next_page_mode=page_fetch`、`page_fetch_max_verified=2`、`single_page_only=false`。

本地执行单元已经审计纠正为：

```text
unit-local-mac-02
state=NEEDS_LOGIN
browser_stopped=true
session_version=5
failure_reason=SESSION_NOT_PERSISTED_AFTER_RESTART
audit_actor=AUTO-01
```

不要把该单元直接改回 `READY`；只有同一上下文内完成受保护能力验证和原子交接后才能增加 session_version 并开始采集。

最终验证基线：

```text
ruff check: passed
ruff format --check: passed (29 files)
mypy: passed (15 source files)
pytest backend/tests tests/e2e: 153 passed in 150.69s
```

完整命令和两轮租约测试失败／修复历史在阶段一证据中，不能删除失败记录或只报告最终成功。

## 五、原方案必须如何修订

原方案中以下假设必须撤销：

```text
人工登录完成 → 关闭维护 Chrome → Worker 用持久 profile 重开 → 自动续跑
```

修订后的流程：

```text
任务等待登录
  → 浏览器宿主持有单元租约、profile 锁和 Chrome
  → 在当前上下文打开登录维护页
  → 用户正常登录
  → 同一上下文验证账号、受保护页面和线路
  → Repository 原子 maintenance → collect
  → 增加 session_version
  → 幂等唤醒原 Temporal 任务
  → 同一上下文执行搜索与主页采集
  → 挑战时暂停并切回维护
  → 空闲／维护超时后确认关闭并回到 NEEDS_LOGIN
  → 关闭未确认则 QUARANTINED
```

持久 profile 仍用于隔离浏览器环境，但不能作为跨 Chrome 重启仍然有效的业务会话承诺。

已同步修订：

- [调研与实施建议](../research/巨量星图自动化采集技术调研与实施建议.md)
- [DEC-011](../decisions/DEC-011-automation-optimization.md)
- [完整技术方案](../AI达人智能发现与采集系统-完整技术方案.md)
- [开发文档](../development.md)
- F04、F05、UNIT-01 和项目进度总览

新窗口开始时必须复核这些文件，不要恢复已经被证据否定的旧方案。

## 六、推荐技术设计

### 1. 进程与所有权

每个 execution unit 只有一个 BrowserHost。BrowserHost 持有：

- Chrome 进程和 BrowserContext；
- profile 文件锁；
- execution unit 的 owner、generation 和租约；
- 当前模式：`maintenance` 或 `collect`；
- 当前 session_version；
- 空闲／维护截止时间；
- 当前原任务标识和可幂等唤醒意图。

BrowserContext 不跨进程传递。若使用本机控制端点，只能绑定 loopback 或 Unix domain socket，运行目录权限必须受限，不能记录 CDP 地址、Cookie、令牌、验证码或请求头值。

### 2. 仓储状态转换

新增带行锁和 fencing 的原子操作，语义建议为：

```text
promote_maintenance_to_collect(
  unit_id,
  owner,
  generation,
  expected_session_version,
  verified_account_id,
  actor
) -> new_session_version
```

必须同时校验：

- 单元存在；
- owner 和 generation 一致；
- 当前 state 为 `LEASED`；
- mode 为 `maintenance`；
- lease 尚未过期；
- browser_stopped=false；
- expected_session_version 未被其他所有者修改；
- 账号、受保护能力和线路校验已经由同一上下文完成。

事务内：mode 改为 `collect`、session_version 增加、failure_reason 清除并写审计。任何校验失败都不能部分提交。

需要同时设计反向转换：挑战或明确登录失效时，从 collect 安全回到 maintenance／等待状态；权限或额度问题不能切换登录模式并反复重登。

### 3. Temporal 与任务恢复

- 保留现有 workflow ID 和幂等 wake signal。
- 登录等待期间不重复创建 root task，不重置候选和检查点。
- 只有原子交接成功后登记／发送 wake intention。
- 重复确认或重复 wake 不得产生第二个 owner、第二个浏览器或重复计数。
- 历史 workflow replay 必须继续通过。
- Activity 结束不能隐式关闭仍由 BrowserHost 使用的上下文；明确界定宿主和 Activity 的生命周期所有权。

### 4. 超时、关闭与隔离

- 维护入口有明确截止时间；到期后任务保持等待，不假设登录态可迁移。
- 空闲超时可关闭 Chrome；关闭成功后设置 `browser_stopped=true` 和 `NEEDS_LOGIN`。
- 关闭没有确认时保持 `browser_stopped=false`，单元进入 `QUARANTINED`。
- 宿主进程异常退出后，不能由新进程直接抢占过期租约；先执行现有隔离核验和 recover 流程。

### 5. 后台衔接

本批先实现领域／仓储／宿主／Worker 的可测试闭环，不另外开发第二套采集器。后续 APP-01、INTAKE-01、CONSOLE-01、F10、OPS-01 调用同一套维护和恢复能力。

后台最终应展示：等待登录、维护中、已验证待交接、采集中、等待挑战、无权限、额度限制、隔离等明确状态，以及维护剩余时间和原任务续跑结果。

## 七、实施顺序

1. 读取 `docs/agent.md`、完整技术方案相关章节、AUTO-01、DEC-011 和本交接文件。
2. 检查当前源码，不假定文档中的建议类名或命令已存在。
3. 先形成最小设计和状态转换表，检查 Workflow 历史兼容与租约 blast radius。
4. 实现 Repository 原子交接、反向维护转换及审计；先完成并发／过期／重复调用测试。
5. 实现每单元 BrowserHost 生命周期，复用现有 BrowserRuntime、BrowserAdapter、profile 锁和关闭确认。
6. 调整 login／worker 协作，移除“关闭后重启才算成功”的最终交接路径；保留失败关闭和隔离保护。
7. 接入 Temporal 幂等 wake，验证同一 root task、同一检查点继续。
8. 完成 synthetic 和本地 Browser 契约测试。
9. 再申请一次真实 Chrome 验证：由用户正常登录，在同一上下文跑一个有界小任务；不要让用户在聊天发送密码或验证码。
10. 实测通过后再继续完整主页字段和第 3 页研究。

## 八、本批验收标准

> 2026-09-29 更正：下列“空闲关闭后状态为 `NEEDS_LOGIN`”是本 handoff 当时的历史标准，已由 [DEC-013](../decisions/DEC-013-structured-session-and-scoped-contract-health.md) 取代。当前规则是：本进程实测 `VALID` 且正常关闭回 `READY`；明确登录失效回 `NEEDS_LOGIN`；账号错误回 `ACCOUNT_MISMATCH`；不可判定回 `SESSION_UNVERIFIED`；关闭未确认进 `QUARANTINED`。

- 一个执行单元同时最多一个 BrowserHost、一个 profile owner、一个有效租约。
- 登录维护和采集使用同一 BrowserContext；没有关闭再重开的隐含步骤。
- 同一上下文完成账号、受保护业务页和线路校验。
- `maintenance → collect` 为单事务、带 fencing、可审计、重复调用幂等或明确拒绝。
- 登录成功后原 root task 和检查点继续，不新建任务、不重复计数。
- 挑战出现时停止业务访问，保留上下文等待人工；权限／额度不触发重新登录循环。
- 空闲关闭后状态为 `NEEDS_LOGIN`；关闭未确认进入 `QUARANTINED`。
- Cookie、令牌、验证码、请求头值和 CDP 控制地址不进入日志、模型、证据或快照。
- 现有 153 项测试保持通过，并增加宿主所有权、并发、租约失效、重复 wake、超时关闭和 Workflow replay 测试。
- 任务卡、技术方案、决策、开发文档和证据同步；未通过真实任务前 AUTO-01 保持“进行中／未验收”。

## 九、完成本批后仍不自动视为完成的事项

- 第 3 页及以后和真实分页终点；
- 画像、创作能力、精选作品；
- 所有主页字段的单位、周期、权限与空值语义；
- 5 位完整主页、20 位连续任务；
- 单日逐步最多 200 位和连续 7 天观察；
- 产品后台全部页面与通知闭环。

本批目标是先把登录维护到采集的生命周期做正确，不能通过缩减字段或跳过异常提高无人值守完成率。
