# DEC-007：真实契约登记的研究采集工具与本地验证载体

- 日期：2026-09-27
- 状态：已采纳并实现；真实契约登记未完成

## 待解决问题

技术方案 13.5 要求"使用授权账号手动操作，结合 Network/DevTools 与必要 DOM 证据登记实际请求"，且"不确定的选择器、接口、硬件协议和供应商配置明确留空，不用推测补齐"。§13.4 要求"先分类会话/网络/契约"，"接口调用默认关闭"。

同时存在两个工程缺口：

1. **先有鸡先有蛋**：`xingtu login` 要求 `registry.session` 已登记，但没有会话入口就无法登录取得登记所需证据。
2. **无验证载体**：本机 Docker 守护进程不可用，`make dev` 无法启动 Compose 的 Temporal 服务，因此真实采集无法通过 `xingtu worker` + `xingtu dispatch` 跑通。

## 选择

1. 新增 `xingtu research`（`backend/src/xingtu/research.py`），定位为**开发期研究工具**，不是采集路径：
   - 仅 `network_mode=local_development` 可用，且只允许打开 `research_allowed_hosts` 中显式列出的主机；
   - 使用项目独立持久 profile（同一把 profile 文件锁与 `0700/0600` 权限），不触碰日常 Chrome profile；
   - 记录内容为结构：请求索引（方法/主机/路径/**查询键**、POST 键名、状态码、内容类型、字节数）与响应 JSON 的**键路径**，以及逐 frame 的 DOM 轮廓（标签/`id`/class/`name`/`type`/`role`/`aria`/`data-*`/`href` 路径/文本长度/叶子文本）；
   - **不记录**请求/响应头、Cookie、令牌、响应正文整体；查询值按"形状"脱敏（数字位数、枚举 token、字符串长度）；
   - 原始采集写入 `.runtime/research/`（项目私有、`.gitignore` 覆盖、`0700`），仅把经审阅的**脱敏摘要**写入 `docs/evidence/`；登记完成后原始件按临时件处理；
   - 交互由显式 `--steps` JSON 驱动（goto/wait/wait_for/click/fill/press/scroll/capture/screenshot），选择器来自已观察的 DOM，不由模型自由点击或执行任意代码。
2. 登录窗口改为**证据驱动**：`login` 与 `research` 都在有界时间内等待真实登录，判定依据是"受保护定位可见 + 账号身份可读"（`login` 还会校验 `expected_account_id`），不再依赖终端回车；TTY 下仍可用回车提前结束，`research` 另支持 `--login-done-file` 由人工信号提前结束。
3. 新增 `xingtu browser-check`：真实启动一次配置的浏览器，记录可执行路径、`--version`、Playwright 报告版本、UA、profile 目录与是否已停止，用于 §1.3 要求的"Chrome 实际可执行路径及与 Playwright 兼容性须实测"。
4. 新增 `scripts/local_smoke.py` + `make smoke-local`：本地阶段验证载体，使用官方 Python SDK 的 Temporal 本地测试服务器运行**真实** `Activities.collect` 与 `CollectionWorkflow`，一次性等待终态后退出。它是验证工具，不替代 OPS-01 的生产编排，也不改变 `xingtu worker` 的生产路径。
5. 未在本会话接入 Playwright MCP：当前 Harness 没有已连接的 MCP 客户端，安装会改动用户全局 profile；项目自带 Playwright 已能产出可复现的证据文件，故先用项目内工具，MCP 作为后续可选调研手段。

## 主要替代方案与否决理由

- 用 Playwright MCP 做交互式调研：可交互性更好，但需要改动用户 Harness profile，且证据不可复现；本轮以项目内工具替代并记录该缺口。
- 先手工填一份"看起来合理"的注册表再验证：违反"不得猜测选择器/接口"，且会把配置错误伪装成平台契约变化。
- 直接把 `login` 改成不需要 `session` 即可运行：会跳过会话入口登记，违反 UNIT-01"session=null 时不能跳过登记直接运行 CLI"。
- 用 HAR/Trace 记录后分析：方案明确 raw HAR/Trace 默认关闭；本轮以结构键路径 + DOM 轮廓满足登记需要。

## 兼容性与影响

- `login` 的等待方式改变但证据校验更严（增加了 `expected_account_id` 的显式比对与错误页优先判定）；`--wait-seconds` 有默认值，旧调用方式仍可用。
- `xingtu research` 与 `xingtu browser-check`、`xingtu production-preflight`、`make smoke-local` 为新增入口；既有命令语义不变。
- 平台契约发布门槛（`require_enabled(live=True)`）与 `contracts/` 目录规则不变：research 只能产生"待审阅的观察"，不能产生 `VERIFIED` 能力。

## 最小验证

- 单测：research 对非本地模式返回 `RESEARCH_REQUIRES_LOCAL_DEVELOPMENT_MODE`、对白名单外主机返回 `RESEARCH_HOST_NOT_ALLOWED`（均在启动浏览器前拒绝）。
- 真实执行：`xingtu browser-check` 成功启动系统 Chrome 并记录版本；`xingtu research` 成功按 `local_development` + 独立 profile 打开 `https://www.xingtu.cn/`，创建 `.runtime/research/r01-login/` 与 profile 目录。
- E2E：新增 `test_activities_refuse_unverified_registry_and_stop_terminal`，用真实 `Activities.collect` 证明 live 门槛不可绕过，并同时验证本地验证载体的编排通路。

## 限制

- 真实会话、搜索分页、主页字段契约**未登记**：人工登录未完成（用户手机不在身边，无法接收平台验证码），因此 `.runtime/research/r01-login/` 内只有打开动作，没有登录后证据；不得据此填写任何注册表字段。
- `research` 只能在 `local_development` 单元上运行；生产环境不得启用该入口。

## 2026-09-27 真实登记结果补充

研究采集工具在真实账号上完成了契约登记，并补充两项实证：

1. **受控业务消息诊断**：`--capture-status-message` 只记录平台自身的 `base_resp.status_message`/`msg`（截断 200 字符），据此定位了账号一搜索被拒的真实原因（`10003 您的客户权益等级过低`）。这证明「只保留允许列表标量」的脱敏设计足以支撑真实排障，无需保存响应正文。
2. **URL-ID 绑定诊断**：`--bind-check` 记录「响应中哪些键路径的取值等于当前页面 URL 末段」，据此证明主页 URL 的 19 位 ID 来自 `author_get_base_info.id`，从而可以登记 `homepage_template` 而不是猜测主页地址。
3. **登记产物**：`contracts/douyin_xingtu.verified.json`（`contract_version=xingtu-ad-creator-square-v1`、`adapter_version=browser-v2`）通过 `require_enabled(live=True)`；搜索响应不含主页 URL，因此登记 `homepage_template` + `id_path`，发布门槛要求二者恰好登记其一。
4. **覆盖缺口显式化**：研究未找到分页控件，契约因此声明 `single_page_only=true` 且必须附带 `search.coverage_gaps`；适配器在需要第 2 页时直接判为契约内耗尽（fail-closed），不重发相同条件、不谎报平台耗尽。

> 2026-09-28 后续证据修订：以上为当时的首页研究结论。AUTO-01 已通过同一页面上下文的请求复用验证真实第 2 页，当前 live 契约改为 `page_fetch` 且只开放到 `page_fetch_max_verified=2`；页 3+ 与终点仍按能力限制处理，不报告平台耗尽。最新依据见 [DEC-011](DEC-011-automation-optimization.md)。
5. **原始件清理**：登记完成后原始研究目录（含页面轮廓与截图）已删除，仅保留 `docs/evidence/` 中的脱敏结论与命令记录。

未接入 Playwright MCP 的结论不变：本会话无 MCP 客户端，项目内 Playwright 工具已能产出可复现证据。
