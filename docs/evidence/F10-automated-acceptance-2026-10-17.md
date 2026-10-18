# F10 自动化验收报告（Playwright MCP + Chrome）

日期：2026-10-17（Asia/Shanghai）  
结论：**本机隔离合成风控验收通过；Linux/noVNC 与自然平台风控仍未验收。**

## 1. 范围与安全边界

- 固定业务输入：关键词 **“户外”**，目标达人 **21**。
- 使用 Playwright MCP `1.62.0-alpha-2026-06-29` 的 Chrome channel 操作真实产品页面。
- API、前端和数据完全隔离：随机 PostgreSQL schema、API `127.0.0.1:8100`、前端 `127.0.0.1:5273`、专用产品账号和非星图验收 Chrome profile。
- 未启动验收 Collection Worker，未打开 `.runtime/profiles/unit-local-mac-02`，未访问巨量星图，未操作滑块、Cookie、CDP、代理或当前星图登录态。
- 合成脚本只替代“平台发出风控”和“Worker 的三项校验结果”；接管、事件、租约、代次、会话版本和任务状态均调用生产 Repository/API。

## 2. 最终结果

最终运行：`20261017_121741_2d6bc6d8`；合成根任务 `cb8e14e6-97d1-4222-b63c-12662cb1dd11`。

| 层级 | 结果 |
|---|---:|
| Playwright MCP + Chrome UI/API/状态机 | **33/33 通过** |
| 后端单元测试 | **285 通过** |
| 前端 Vitest | **82 通过（6 files）** |
| 前端 TypeScript / production build | **通过** |
| PostgreSQL 接管互斥专项集成测试 | **1 通过** |
| 浏览器控制台 | **Errors: 0** |
| 浏览器失败 HTTP 请求 | **0** |

机器可读结果：[acceptance-results.json](assets/f10/acceptance-results.json)。

## 3. 流程验证

1. 任务详情准确显示“户外”、目标 21 和 `WAITING_FOR_VERIFICATION`。
2. 执行单元页显示 1 条未解决通知、等待人工验证、脱敏账号/线路和可行动原因。
3. 页面发起接管后依次准确显示 `REQUESTED → ACTIVE`。
4. ACTIVE 工作区显示自动操作暂停提示及最多 3 位人工探测达人；系统没有自动导航或写业务采集结果。
5. 人工上报“滑块再次出现”后，后端 `reappearance_count: 0 → 1`。
6. 首次提交完成后显示 `VERIFYING`；模拟稳定检查仍有挑战时返回 `FAILED / SECURITY_CHALLENGE_STILL_PRESENT`，计数增至 2，任务没有错误恢复。
7. 同一维护窗口可再次请求接管并重新进入 ACTIVE，不占用一次成功恢复次数。
8. 第二次提交后模拟账号、受保护页、线路三项均通过：接管进入 `RESUMED`，任务恢复 `COLLECTING`，单元回到 `mode=collect`，`session_version: 0 → 1`，验证事件变为 `RESOLVED`。

页面证据：

- [任务等待验证](assets/f10/01-task-waiting-verification.png)
- [执行单元等待状态](assets/f10/02-unit-waiting.png)
- [人工接管 ACTIVE](assets/f10/03-takeover-active.png)
- [系统校验中](assets/f10/04-system-verifying.png)
- [验证仍存在](assets/f10/05-challenge-still-present.png)
- [任务恢复](assets/f10/06-resumed.png)

## 4. 测试期间发现并修复的问题

1. 验收隔离的首版 DSN 使用 `search_path=<test>,public`，迁移探测会回退读取开发库的 `schema_migrations`，导致两个早期失败运行各写入一组带唯一 `f10-accept-*` 标识的合成行。已改为仅 `search_path=<test>`，并按根任务、单元和全部外键依赖精确清理两组记录；最终开发库 `f10-accept-*` 单元与 `actor=f10-acceptance` 幂等记录均为 0。
2. 合成 Worker 初版未心跳，租约超过 120 秒后恢复被后端以 `LEASE_LOST` 正确拒绝。模拟器已补用生产 `heartbeat()`，没有放宽租约栅栏。
3. 前端没有 favicon，Chrome 控制台出现 `/favicon.ico` 404。已在 `frontend/index.html` 加入内联 favicon；复测控制台 `Errors: 0`。
4. 控制台断言最初把摘要文本 `Errors: 0` 中的单词 `Errors` 误判为错误；已改为解析错误计数并完整复跑。

以上失败均保留在本报告，不作为平台能力通过证据；最终 33/33 来自修复后的全新随机 schema 完整复跑。

## 5. 清理与“不影响核心流程”证明

最终清理结果：

- 随机 `f10_accept_*` schema：`0`
- 开发库 `f10-accept-*` 执行单元：`0`
- 开发库 `actor=f10-acceptance` 幂等记录：`0`
- `.runtime/f10-acceptance/state.json`：已删除
- 专用端口 `8100 / 5273`：均已关闭
- 核心单元只读复核：`unit-local-mac-02 = READY`、`mode = null`、`browser_stopped = true`、`last_session_status = VALID`
- 原应用仍在 `8000 / 5173` 运行，Intake 和 Collection 两个 Temporal 消费者在线。

本轮没有主动打开核心星图 profile；因此“登录态未被验收代码读取或改写”有结构性隔离保证，但本报告不把数据库中的旧 `VALID` 当成一次新的平台会话实测。

## 6. Linux 服务器与剩余验收

已对用户提供的 `101.42.14.225` 做无密码、无持久主机记录的只读 SSH 探测；`root`、`ubuntu`、`lighthouse` 均返回 `Permission denied (publickey)`，本机 SSH agent 没有已加载 identity，也没有该实例的私钥或 SSH 配置。因此本轮**未推送项目、未修改服务器、未部署 Xvfb/x11vnc/noVNC**。

仍需提供该实例的 SSH 用户和私钥（或将对应密钥加载到本机 agent），再执行：

- Linux 固定镜像、Xvfb/x11vnc、私网 VNC 与同源 noVNC 网关部署；
- 同一真实浏览器实例/Context 的 ACTIVE viewer 验证；
- viewer 断线、票据过期/撤销、错误账号、线路异常、Worker 崩溃与旧进程隔离；
- 授权测试账号自然出现风控后的真实人工恢复。

因此本报告证明的是 **F10 产品/API/状态机的隔离合成自动验收通过**，不替代 U06 的 Linux 远程承载和自然平台风控验收。
