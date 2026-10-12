# APP-01：产品应用基础与登录会话

状态：待验收
更新时间：2026-10-10T22:45:00+08:00
是否验收：否；后端认证、React 产品壳/登录页和合成 API 浏览器 E2E 已完成；生产 HTTPS/域名/Secure Cookie 环境尚未验收。

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
- [ ] 生产 HTTPS/域名、精确允许 Origin、初始用户清单和 Secure Cookie 参数完成环境验收。

## 验证证据

- 2026-09-27：静态盘点依据见 [项目基线证据](../evidence/PROJECT-BASELINE-2026-09-27.md)。
- 2026-10-10：[M3 本地产品控制台启动与真实数据联调证据](../evidence/M3-local-console-startup-2026-10-10.md)。在真实 Chromium 上对本地 API（`127.0.0.1:8000`，`XINGTU_SECURE_COOKIE=0`，Origin 白名单为 5173）完成登录、会话、刷新保持、退出后直达受保护 URL 回登录；受保护封面无会话 401、跨任务 404；两位本地账号审计身份可区分。生产 HTTPS/精确 Origin/Secure Cookie/初始用户清单仍未验收，最后一项保持未勾选。
- 2026-10-10：[M3 后端实现与回归证据](../evidence/M3-backend-implementation-2026-10-10.md)。`make check` 为 155 单测通过；产品认证/API PostgreSQL 集成用例通过。
- 2026-10-10：[M3 产品前端与浏览器证据](../evidence/M3-product-frontend-2026-10-10.md)。TypeScript/组件/生产构建通过，真实 Chromium + 合成 API 2 passed；已验证未登录回跳、登录后恢复原 URL 和共享任务入口。
- 2026-10-10：[M3 真实 DeepSeek 与产品闭环证据](../evidence/M3-real-product-acceptance-2026-10-10.md)。两位本地媒介用户在真实开发库与 Chromium 中完成登录、退出、旧 Cookie 401、重登恢复和共享任务读取；仍不代替生产 HTTPS 验收。
- 未执行生产域名/HTTPS 和真实产品账号环境验收；合成 API E2E 不代替生产验收。

## 交接信息

产品认证与 React 入口已可交给 INTAKE-01、CONSOLE-01 复用。剩余 APP-01 工作只是部署验收：正式域名、HTTPS、精确 Origin、初始用户清单和 Secure Cookie。

## 状态历史

- 2026-10-10T22:45:00+08:00：待验收 → 待验收；Playwright MCP 独立冒烟复核通过本地登录、会话保持、退出与未登录保护；生产 HTTPS/域名/Secure Cookie 仍未验收。报告见[核心冒烟测试报告](../testing/smoke-test-f04-f05-f06-m3.md)。

- 2026-10-10T14:43:53+08:00：进行中 → 待验收；本地产品实环的两媒介登录/退出/重登、会话保护、共享任务和封面授权全部通过。实现已结束，仅等待本轮明确不进入的生产 HTTPS/域名/Secure Cookie 环境验收，故按状态规则改为待验收。
- 2026-10-10T14:21:22+08:00：进行中 → 进行中；用户授权继续使用本地开发数据库和两个媒介账号完成验收。预检确认迁移 008 已应用，不重复执行；本轮仍为本地 HTTP 环境，生产 HTTPS/Secure Cookie 验收边界不变。
- 2026-10-10T14:08:00+08:00：进行中 → 进行中；在真实开发库上应用迁移 008、创建本地开发账号并启动产品 API 与前端，浏览器实测登录/会话/刷新/退出与受保护封面授权。仅本地 HTTP 开发参数，生产 HTTPS 验收边界不变。
- 2026-10-10T13:52:36+08:00：进行中 → 进行中；最终全仓 `make check` 通过（155 后端单测、2 前端组件测试、TypeScript strict 和生产构建），Chromium 合成 API 闭环 2/2 再次通过。生产 HTTPS 验收边界不变。
- 2026-10-10T10:54:01+08:00：进行中 → 进行中；Lazyweb 检索/定稿、React 产品壳/登录页、会话回跳与 Chromium 合成 API E2E 完成。仍因生产 HTTPS/域名/Secure Cookie 环境未验收保持进行中。
- 2026-10-10T10:25:46+08:00：阻塞 → 进行中；用户提供本地 Lazyweb skill 仓库，MCP 健康检查与实时工作流读取成功，启动 React 产品壳、登录页及浏览器验证实施。
- 2026-10-10T09:04:02+08:00：进行中 → 阻塞；后端认证、安全 API、运维命令和自动化验证完成，但 Lazyweb MCP 在本会话工具清单中为 0。按仓库强制 UI 流程不能手工替代，恢复 Lazyweb 工具后可继续 React 产品壳与登录页。
- 2026-10-09T19:50:53+08:00：待办 → 进行中；用户确认完整 M3 开发计划，启动 APP-01 实施。Lazyweb MCP 工具当前未暴露，仅阻塞前端视觉设计与页面落地，后端认证、迁移和测试继续推进。
- 2026-09-27T09:51:41+08:00：建立 → 待办；依据完整技术方案及代码盘点补齐一期任务规划，未改变业务范围。
