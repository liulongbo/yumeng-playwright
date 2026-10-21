# APP-01：产品应用基础与登录会话

状态：已完成
更新时间：2026-10-20T20:32:00+08:00
是否验收：是；本地功能验证与腾讯云生产域名、HTTPS、精确 Origin、初始用户、Secure Cookie 和真实浏览器会话验收均已完成。

## 2026-10-10 F04/F05/F06/M3 核心冒烟复核

本轮通过 Playwright MCP 对真实产品 UI 执行登录与会话冒烟，报告见 [F04/F05/F06/M3 核心冒烟测试报告](../testing/smoke-test-f04-f05-f06-m3.md)。未登录访问 `/tasks` 回跳 `/login`；临时本地 QA 用户 `smoke-qa-20261010` 登录成功并进入任务中心；刷新与任务详情路由保持会话；退出后直达受保护任务 URL 再次回跳登录，Network 中 `/api/auth/me` 返回 401 符合预期。Console 仅有预期的未登录 401 与 `favicon.ico` 404，未发现业务 JavaScript 异常。

结论：APP-01 的本地开发环境登录/会话/退出保护在本轮真实 UI 冒烟中 PASS；生产 HTTPS/域名、精确 Origin 和 Secure Cookie 仍未执行，状态保持待验收。

## 目标与范围

**目的**：让媒介通过独立账号安全进入共享后台，为所有产品 API 和页面建立统一入口。

**任务内容**：完成前端与会话选型及决策记录、FastAPI 应用、前端壳与登录页、users/sessions 迁移、认证中间件、安全 Cookie、跨站写请求保护、登录限流、审计身份和部署初始用户流程。提供 login/logout/me 接口及供后续封面接口复用的认证能力。

**不包含**：不增加注册、多角色、用户管理页面；不把平台账号当作产品会话。后续页面由对应业务卡负责。

## 关联与依赖

F01；技术方案第 2、16、17 章。T12/T30，U01。

前置：[BASE-01](BASE-01.md) 的现有工程基础可复用；开发不必等待真实平台核验。

## 当前开发状态与实现记录

2026-10-10 后端阶段已实现：FastAPI 应用、`users/sessions` 向前迁移、Argon2id、服务端会话、令牌哈希、空闲/绝对过期、登录/退出/`me`、Origin + CSRF、Redis 登录双维度限流、统一错误和用户审计；并提供创建用户、禁用/启用和重置密码运维命令。认证能力已覆盖全部 M3 API 与封面入口。

实现依据：[产品 API](../../backend/src/xingtu/product_api.py)、[认证服务](../../backend/src/xingtu/product_auth.py)、[产品仓储](../../backend/src/xingtu/product_repository.py)、[迁移 008](../../migrations/008_m3_product_app.sql)、[React 入口](../../frontend/src/App.tsx)、[页面实现](../../frontend/src/pages.tsx)、[DEC-014](../decisions/DEC-014-m3-product-application-and-intake.md)。Lazyweb 本地 MCP 检索和安全定稿已完成，见 [M3 产品前端证据](../evidence/M3-product-frontend-2026-10-10.md)。

## 验收清单

- [x] 合法用户登录/退出/会话过期与撤销正确，错误提示不泄露账号是否存在；密码不明文保存或记录。
- [x] 无会话不能访问业务 API 和受保护资源；Cookie、跨站写请求、登录限流有自动化验证。
- [x] 两位媒介共享任务权限且审计可区分操作人；退出只撤销产品会话，不触碰后台任务。
- [x] 完成 U01 后端选型、初始用户/禁用/重置运维命令，记录实际依赖和可运行命令。
- [x] 按仓库 Lazyweb 流程完成 React + TypeScript + Vite 产品壳、登录页及合成 API 浏览器 E2E。
- [x] 生产 HTTPS/域名、精确允许 Origin、初始用户清单和 Secure Cookie 参数完成环境验收。

## 验证证据

- 2026-09-27：静态盘点依据见 [项目基线证据](../evidence/PROJECT-BASELINE-2026-09-27.md)。
- 2026-10-10：[M3 本地产品控制台启动与真实数据联调证据](../evidence/M3-local-console-startup-2026-10-10.md)。在真实 Chromium 上对本地 API（`127.0.0.1:8000`，`XINGTU_SECURE_COOKIE=0`，Origin 白名单为 5173）完成登录、会话、刷新保持、退出后直达受保护 URL 回登录；受保护封面无会话 401、跨任务 404；两位本地账号审计身份可区分。生产 HTTPS/精确 Origin/Secure Cookie/初始用户清单仍未验收，最后一项保持未勾选。
- 2026-10-10：[M3 后端实现与回归证据](../evidence/M3-backend-implementation-2026-10-10.md)。`make check` 为 155 单测通过；产品认证/API PostgreSQL 集成用例通过。
- 2026-10-10：[M3 产品前端与浏览器证据](../evidence/M3-product-frontend-2026-10-10.md)。TypeScript/组件/生产构建通过，真实 Chromium + 合成 API 2 passed；已验证未登录回跳、登录后恢复原 URL 和共享任务入口。
- 2026-10-10：[M3 真实 DeepSeek 与产品闭环证据](../evidence/M3-real-product-acceptance-2026-10-10.md)。两位本地媒介用户在真实开发库与 Chromium 中完成登录、退出、旧 Cookie 401、重登恢复和共享任务读取；仍不代替生产 HTTPS 验收。
- 2026-10-20：腾讯云生产库已由用户通过交互式密码入口创建首个产品用户 `admin`（显示名“管理员”，用户 ID `a1598139-34e9-4e2c-baf4-711feedf8ea3`），只读数据库复核 `active=true`；未重建或重置密码。API 回环健康端点返回 `{"status":"ok"}`，业务库任务数为 0。生产配置保持 `XINGTU_ALLOWED_ORIGINS=https://xingtu.yumeng.live`、`XINGTU_SECURE_COOKIE=1`。
- 2026-10-20：DNS 权限审计确认 `yumeng.live` 由阿里云云解析托管（权威 NS 为 `dns9/10.hichina.com`），当前 `xingtu.yumeng.live` 无 A/AAAA 记录；本机和服务器无阿里云 CLI/凭据，宝塔 `AliyunDns` 配置为未配置，因此未擅自创建记录或修改其他域名。前端静态文件已发布到独立新目录 `/www/wwwroot/xingtu.yumeng.live`，但 Nginx/证书尚未启用，不能据此宣称生产页面或 HTTPS 已通过。
- 2026-10-20：用户添加 A 记录后，两个权威 DNS、本机、服务器及公共解析器均确认 `xingtu.yumeng.live → 119.91.210.100`。独立 HTTP-01 Nginx 站点已加载且公网探针 200；Let’s Encrypt 多视角验证中部分节点从项目 Nginx取得 200，但另一视角被腾讯云网络层重定向至 `dnspod.qcloud.com/static/webblock.html`，故 HTTP-01 正式及 staging 均失败。已切换标准 DNS-01 并等待用户添加一次性 TXT；HTTPS 尚未签发，生产登录仍未验收。
- 2026-10-20：用户添加一次性 TXT 后，两台权威 DNS、Google 与阿里公共 DNS 均验证精确值，DNS-01 成功签发 `xingtu.yumeng.live` Let’s Encrypt 证书（有效期至 2027-01-18）。独立 Nginx 正式站点语法检查与 reload 成功：HTTP 301→HTTPS、首页 200、API health 200、证书链/主机名验证通过，`dev.yumeng.live` 保持 200。手工 DNS 证书无法自动续期，需后续配置阿里云 DNS API hook 或到期前人工续签。
- 2026-10-20：本机 Chrome 默认走系统代理 `127.0.0.1:7897`，该代理会对新域名产生 `ERR_CONNECTION_CLOSED`；不修改全局代理，独立临时 Chrome 使用 `--no-proxy-server` 后真实加载通过。无登录验收：根路径 200 并回 `/login`、受保护 `/tasks` 回登录、密码框存在、同源 health 200、未认证 WebSocket 握手 403；两个 `/me` 401 为预期门禁。已打开仅回环 CDP 的独立临时浏览器等待用户输入产品密码，未使用采集 Profile。
- 2026-10-20：经用户明确授权重置既有 `admin` 密码；数据库仅保存 Argon2 哈希，无法反查原密码，因此生成随机密码并只存入本机 macOS Keychain（service `com.yumeng.xingtu.product.admin`），未写入仓库、服务器文件、命令输出或验收日志。使用独立临时 Chrome（非采集 Profile、`--no-proxy-server`）登录 `https://xingtu.yumeng.live` 成功并进入 `/tasks`，刷新后仍停留 `/tasks`；页面标题为“星采 · 媒介工作台”，控制台错误与失败请求均为 0。
- 2026-10-20：登录后 `/api/auth/me`、`/api/health/workers`、`/api/execution-units`、`/api/tasks` 均返回 200；用户 ID、用户名及显示名与已创建用户一致，CSRF token 已签发。会话 Cookie 仅记录属性：`HttpOnly=true`、`Secure=true`、`SameSite=Lax`、`Path=/`、作用域为正式域名，未输出 Cookie 值。Intake 与 Mac Collection 两条队列均有 1 个新鲜 poller；任务数为 0，未触发真实采集。WebSocket 路由的未认证拒绝已验证，但因当前无活动 F10 takeover，未制造接管状态来冒充成功的 101/VNC 会话；该项属于 F10 的远程接管验收，不阻断 APP-01 的登录会话验收。

## 交接信息

APP-01 已完成：产品认证、React 入口与生产 HTTPS 会话均可供 INTAKE-01、CONSOLE-01 复用。运维遗留不改变本卡结论：手工 DNS-01 证书尚无自动续期 hook；Mac 系统代理需为正式域名配置绕过，当前验收使用独立直连 Chrome；远程 F10 WebSocket/VNC 的成功会话由 F10 卡继续验收。

## 状态历史

- 2026-10-10T22:45:00+08:00：待验收 → 待验收；Playwright MCP 独立冒烟复核通过本地登录、会话保持、退出与未登录保护；生产 HTTPS/域名/Secure Cookie 仍未验收。报告见[核心冒烟测试报告](../testing/smoke-test-f04-f05-f06-m3.md)。
- 2026-10-20T12:51:00+08:00：待验收 → 待验收；生产初始用户与 API 已实机确认，DNS 因无阿里云管理授权尚未创建，HTTPS/Cookie/Origin/WebSocket/真实浏览器验收继续等待域名解析。
- 2026-10-20T15:45:00+08:00：待验收 → 待验收；A 记录已生效，HTTP-01 受腾讯云多视角 webblock 重定向阻塞，改用 DNS-01 并等待一次性 TXT 生效后继续。
- 2026-10-20T16:15:00+08:00：待验收 → 待验收；DNS-01、正式 HTTPS/Nginx 与无登录浏览器门禁通过，等待用户在独立浏览器安全输入密码后完成 Secure Cookie/会话/登录后页面验收。
- 2026-10-20T20:32:00+08:00：待验收 → 已完成；用户授权密码重置并安全存入 Keychain后，正式域名真实 Chrome 登录、刷新保持、Secure/HttpOnly/SameSite Cookie、CSRF 与登录后 API 全部通过，APP-01 最后一项生产环境验收关闭。

- 2026-10-10T14:43:53+08:00：进行中 → 待验收；本地产品实环的两媒介登录/退出/重登、会话保护、共享任务和封面授权全部通过。实现已结束，仅等待本轮明确不进入的生产 HTTPS/域名/Secure Cookie 环境验收，故按状态规则改为待验收。
- 2026-10-10T14:21:22+08:00：进行中 → 进行中；用户授权继续使用本地开发数据库和两个媒介账号完成验收。预检确认迁移 008 已应用，不重复执行；本轮仍为本地 HTTP 环境，生产 HTTPS/Secure Cookie 验收边界不变。
- 2026-10-10T14:08:00+08:00：进行中 → 进行中；在真实开发库上应用迁移 008、创建本地开发账号并启动产品 API 与前端，浏览器实测登录/会话/刷新/退出与受保护封面授权。仅本地 HTTP 开发参数，生产 HTTPS 验收边界不变。
- 2026-10-10T13:52:36+08:00：进行中 → 进行中；最终全仓 `make check` 通过（155 后端单测、2 前端组件测试、TypeScript strict 和生产构建），Chromium 合成 API 闭环 2/2 再次通过。生产 HTTPS 验收边界不变。
- 2026-10-10T10:54:01+08:00：进行中 → 进行中；Lazyweb 检索/定稿、React 产品壳/登录页、会话回跳与 Chromium 合成 API E2E 完成。仍因生产 HTTPS/域名/Secure Cookie 环境未验收保持进行中。
- 2026-10-10T10:25:46+08:00：阻塞 → 进行中；用户提供本地 Lazyweb skill 仓库，MCP 健康检查与实时工作流读取成功，启动 React 产品壳、登录页及浏览器验证实施。
- 2026-10-10T09:04:02+08:00：进行中 → 阻塞；后端认证、安全 API、运维命令和自动化验证完成，但 Lazyweb MCP 在本会话工具清单中为 0。按仓库强制 UI 流程不能手工替代，恢复 Lazyweb 工具后可继续 React 产品壳与登录页。
- 2026-10-09T19:50:53+08:00：待办 → 进行中；用户确认完整 M3 开发计划，启动 APP-01 实施。Lazyweb MCP 工具当前未暴露，仅阻塞前端视觉设计与页面落地，后端认证、迁移和测试继续推进。
- 2026-09-27T09:51:41+08:00：建立 → 待办；依据完整技术方案及代码盘点补齐一期任务规划，未改变业务范围。
