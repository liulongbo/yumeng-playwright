# F10 原浏览器人工接管部署

F10 的远程会话不是另起 Chrome 或导出 Cookie：每个 ExecutionUnit 容器只启动一个 Xvfb、一个 x11vnc 和一个 Collection Worker，Playwright 与人工均操作这一 Chromium/BrowserContext。

使用 [`f10-remote-browser.compose.yaml`](../deploy/f10-remote-browser.compose.yaml) 作为私有环境的 Compose overlay。每个单元必须使用独立的 profile 卷、私有 `UNIT_CONFIG`、容器名和 `XINGTU_REMOTE_VNC_TARGETS_JSON` 映射；不使用 Compose 的 `--scale` 来复制账号单元。

部署前必须完成：

- Worker 镜像包含固定版本的 Chromium/Playwright、Xvfb、x11vnc 和该仓库的 `xingtu` CLI；镜像 digest 记录到部署清单。
- 将 `f10-remote-viewer.html` 与固定版本 noVNC 资源（`core/rfb.js`）发布到产品同源的 `/remote-viewer/`。该静态页只连接 `/api/takeovers/{id}/viewer`。
- 产品 API 同时加入 `browser-private` 网络；VNC 服务没有 `ports:`，宿主机、公网、其他业务网络均不可路由到 `5900`。禁止 CDP 调试端口。
- 配置精确 HTTPS Origin；WebSocket 仅在登录用户、对应接管人、`ACTIVE` 状态和未过期时可建立。提交“我已完成验证”后接管变为 `VERIFYING`，API 在最多一秒内关闭 WebSocket，再进行只读稳定检查。

`XINGTU_REMOTE_VNC_TARGETS_JSON` 仅是 API 进程的私有配置，格式为 `{"unit-01":"browser-unit-01:5900"}`，不进入 API 响应、浏览器页面、日志或审计记录。浏览器实例 ID、租约代次与产品用户绑定由数据库接管会话校验。

部署配置只是可复现的承载入口；必须在授权测试账号自然触发验证后，记录“同一浏览器实例、同一 Context、过期/撤销、错误账号、线路异常、任务取消和 Worker 崩溃”的脱敏验收证据，才能宣称 U06 已验收。
