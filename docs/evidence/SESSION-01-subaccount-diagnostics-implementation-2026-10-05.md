# SESSION-01 子账号诊断链实施证据（2026-10-05）

## 实施边界

本轮主要修复诊断探针、增加脱敏请求—响应—会话证据和浏览器 A/B 载体。正式 Adapter/BrowserHost **未启用自动选号**；只有真实 A/B 证明 Playwright 下可稳定选号后才允许进入该实现门槛。现场又发现维护窗口无条件先打开 SSO 登录入口会造成“看起来未登录”的误导，因此同步修正了页面进入顺序，但没有放宽登录成功判据。

## 实现结果

- 点击事件通过 Playwright binding 在 `pointerdown`/`click` 时立即持久到 Python 进程内，页面导航或销毁不再丢失最后一次点击。
- 修正了旧 `add_init_script`只注入“函数表达式但没有执行”的缺陷；新页面会真正安装记录器。
- 自动诊断点击由 DOM `element.click()` 改为 Playwright `locator.click()`，并拒绝 0 个或多个精确目标。
- 选号交互后记录 1/3/5/15/30 秒账号、受保护页及身份载体 HMAC。
- 网络证据只保留方法、host/path、HTTP 状态、Content-Type、JSON 字段结构及 `code/status/success/errno/err_no`；不保存 query、header、请求正文、Cookie/Token 明文或完整响应。
- 增加仅允许 `local_development` 的 `--profile-directory-override` 与 `--omit-project-network-args` A/B 开关；诊断阶段先不改生产行为。B2 证实钥匙串根因后，才将只忽略 `--use-mock-keychain` 的显式、fail-closed 配置落到 `BrowserRuntime`；全程不做 stealth。
- A/B 操作步骤见 [SESSION-01 浏览器 A/B 手册](../handoffs/SESSION-01-browser-ab-runbook.md)。

## 自动验证

环境：macOS / Python 3.13.5 / Playwright 1.63.0 / 系统 Google Chrome 154.0.8037.93。合成浏览器用例通过受控 route，不访问真实星图。

```text
.venv/bin/python scripts/account_drift_probe.py --self-test
→ 退出码 0；10 项判定 + 2 项载体/人工窗口用例通过

.venv/bin/ruff check scripts/account_drift_probe.py backend/tests/contract/test_account_drift_probe.py
→ 退出码 0

.venv/bin/ruff format --check scripts/account_drift_probe.py backend/tests/contract/test_account_drift_probe.py
→ 退出码 0

.venv/bin/pytest -q backend/tests/contract/test_account_drift_probe.py
→ 退出码 0；2 passed in 1.05s
```

合成浏览器覆盖：目标 0/1/多匹配、locator 点击、点击后立即发请求并导航、导航后点击仍存在、响应结构/业务码存在、Cookie 和响应秘密值不出现在序列化报告。

## 真实 A/B 状态

- 2026-10-05T14:39:09+08:00：已确认项目 profile 无 Worker/探针占用，已直接用系统 Google Chrome（不经 Playwright）打开 A 组。
- 2026-10-05T15:04:01+08:00：对该项目 profile 的 Cookie 数据库只读检查（仅 host/name/过期信息，不读取或记录值）确认：没有父账号 SSO 认证 Cookie，也没有 `.xingtu.cn/star_sessionid`。因此当前窗口是**真实未登录**，不是只有界面显示为未登录；它从受保护业务 URL 被平台重定向到登录页属于正确行为。
- 2026-10-05T15:09:25+08:00：操作者确认人工登录后已显示星图首页；随即再次只读检查同一 profile，确认 OceanEngine SSO 认证 Cookie 与 `.xingtu.cn/star_sessionid` 均已出现（仍不读取或记录值）。这与 15:04 的未登录基线形成前后对照，证明“真实未登录展示登录页、登录完成展示业务首页”的显示链路成立。
- 2026-10-05T15:13:17+08:00：A 组第三账号对照通过。操作者在不经过 Playwright 的项目 profile 中选择 `1831973402720484`，选择后、刷新后、进入达人广场后三个检查点均保持 `1831973402720484`。据此排除“项目独立 profile 会把所有非默认账号统一回退到 `1832740070238347`”；项目 profile 和自然 Chrome 交互至少对该第三账号可用。
- 2026-10-05T15:17:47+08:00：A 组目标账号也通过。操作者从第三账号切到 `1865332309937515` 后，点击后立即即为目标账号且全程未短暂回退；等待 10 秒、刷新、进入达人广场后仍均为目标账号。据此同时排除“目标账号当前不可用”和“项目 profile 自身导致回退”。原故障现收敛到 Playwright 控制环境，或旧探针的交互/观测缺陷；下一步在完全退出自然 Chrome、释放 profile 锁后，用同一 profile 进入 Playwright B 组。
- 2026-10-05T15:25:30+08:00：B 组当前 Playwright 环境首次只读冷启动完成（报告 `.runtime/drift-probe/drift-unit-local-mac-02-20261005T072530Z.json`）。探针第一跳已先修正为受保护业务首页，不再先访问 SSO；结果 7/7 检查点账号不可读，业务 URL 均被重定向到 `/?redirect_uri=...`，受保护页标记为 false，且所有检查点均没有 OceanEngine SSO Cookie 和 `star_sessionid`。
- B 组启动前（自然 Chrome 尚在运行时）的只读 Cookie 名称检查明确存在完整 SSO 认证 Cookie 与 `star_sessionid`；B 组退出后，同一 Cookie 数据库只剩匿名统计/CSRF Cookie。项目代码没有 `clear_cookies()`、Cookie 注入或 storage state 覆盖。因此故障发生在 Playwright 启动并读取持久 profile 的阶段，早于子账号点击和平台账号回退。
- 2026-10-05T15:36:47+08:00：B2 证实 macOS 钥匙串后端不一致。重新登录并选定目标、关闭自然 Chrome 后，启动参数只忽略 Playwright 默认 `--use-mock-keychain`；父账号 SSO Cookie 全程保留，业务页可用，不再复现 B1 的“认证 Cookie 被清除”。因此这一项是“Playwright 启动后又显示未登录”的直接根因。
- B2 同时显示第二层独立问题：自然 Chrome 关闭前的 `star_sessionid` 是 session Cookie；Playwright 新进程冷启动时该 Cookie 缺失，首次业务引导重新签发后，账号稳定为默认 `1832740070238347`。首页、达人广场、第二标签页均一致，判定 `PERSISTENT_ACCOUNT_MISMATCH`。
- 2026-10-05T15:49:24+08:00：B3 在系统钥匙串模式下由操作者真实点击目标。进程侧记录到可信 `pointerdown/click`，实际触发 `POST /u/api/demander/switch_collaboration_account`，HTTP 200/application/json，并发生后续导航；但 1/3/5/15/30 秒检查点、刷新和达人广场始终为 `1832740070238347`，`star_sessionid` HMAC完全不变。由此排除“未点中”“点击记录随导航丢失”“请求未发送”和“只是异步生效慢”。报告：`.runtime/drift-probe/drift-unit-local-mac-02-20261005T074924Z.json`。
- 2026-10-05T16:01:58+08:00：参数 C 复验完成。保留系统钥匙串修复，只移除项目自定义 `--disable-quic` 与 `--force-webrtc-ip-handling-policy=disable_non_proxied_udp`；4 次目标点击均产生可信事件和 4 次选号 POST（HTTP 200），但 54 个选后检查点没有一次出现目标账号，`star_sessionid` HMAC只有一个值。故两个项目网络参数不是原因。报告：`.runtime/drift-probe/drift-unit-local-mac-02-20261005T080158Z.json`。
- 最终分层结论：① mock keychain 导致父账号认证丢失，是可修复的本地执行环境缺陷；②修复后，新 Playwright 进程仍按默认子账号重建业务会话，且平台不让真实目标点击在该控制环境中生效。现有证据不能区分平台主动限制自动化会话与其内部其他环境判定，但已足以判定“自动选号在当前 Playwright 环境中不可靠”。按批准边界，不实施 stealth、Cookie 注入、日常 profile 复用或无限重试。
- 已将系统 Keychain 兼容正式落到 `BrowserRuntime` 的显式配置 `macos_system_keychain`，当前 `local-dev-mac-02` 启用；只忽略 `--use-mock-keychain`，环境哈希包含 keychain 策略，非 macOS 或没有固定可执行文件时 fail-closed。正式 Adapter 自动选号保持关闭。

## 登录页与业务页显示修复

- `BrowserHost.maintain_and_promote()` 在未传入现成页面时，第一跳由 SSO `session.entry_url` 改为受保护的 `search.entry_url`。有效业务会话会留在登录后的星图页面；确实无会话时，由平台重定向到登录页。
- `BrowserAdapter.prepare()` 同样优先访问业务页并形成结构化 `SessionHealth`。只有首次结果为 `INDETERMINATE` 时，才执行一次有界的 SSO 握手并回到业务页复核；不会把“SSO 页面存在”本身当成退出登录证据。
- 诊断探针的冷启动第一跳也已同步改为从已登记的受保护首页开始，避免 B 组继续被旧 SSO-first 顺序污染。
- 登录成功门槛不变：仍需账号精确匹配和受保护页可用；本次没有依赖 URL 或 Cookie 单独提升 `session_version`。
- 合成浏览器契约验证了有效会话第一跳为业务页且不会访问登录入口；BrowserHost 集成用例新增相同顺序断言。最终 `make check` 通过（107 单元测试），完整 Browser Contract `21 passed`；BrowserHost 定向集成测试因本机专用 PostgreSQL `127.0.0.1:55439` 未运行而在 fixture 建立前连接失败，未发生业务断言失败。

## 正式处理决定

- 已实施：业务页优先；macOS 系统 Keychain 兼容；结构化账号校验；失败时维持 `ACCOUNT_MISMATCH/WAITING_FOR_ACCOUNT`；诊断点击/请求/会话证据。
- 未实施：正式自动选号。它没有满足“Playwright 环境中通过正确交互可稳定选号”的前置门槛。
- 当前可行方案按优先级为：在星图侧把目标账号设为该登录身份的默认业务账号；为目标账号使用独立、默认即落到目标的登录身份；经业务审计改绑执行单元；或采用同一自然 Chrome/同一长生命周期 Context 的人工维护交接。进程重启后仍必须重新验证，不宣称无人值守恢复。
- 不建议：Cookie 注入、复制日常 profile、自动化伪装、反复点击。前两项破坏安全边界，后两项不能修复服务端/平台环境判定并会增加风控风险。
