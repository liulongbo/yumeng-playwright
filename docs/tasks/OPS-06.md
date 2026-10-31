# OPS-06：聚星体验站登录限流解除与重启

状态：已完成  
更新时间：2026-10-31T01:18:00+08:00  
是否验收：是（本轮范围：重启聚星隔离栈、清除登录限流键、API/浏览器登录恢复）

## 目标与范围

**目的**：用户登录聚星体验站时收到「尝试次数过多，请稍后再试」，要求重启体验站。实际原因是 Redis 登录限流器已封禁来源 IP（同时有账号桶计数），仅重启进程不会清除限流状态。

包含：

- 确认限流实现（`RedisLoginLimiter`：5 次失败 / 900 秒，IP 与账号 HMAC 双桶）；
- 重启聚星隔离栈（Temporal `57235`、API `4192`、前端 `4193`、Intake、Collection）；
- 清除该栈专用 Redis DB15 的 `xingtu:login:*` 限流键；
- 验证 API 登录 200、浏览器登录进入任务中心、页面不再显示限流提示。

不做：

- 不改登录限流阈值/窗口，不改代码；
- 不清除主站 Redis DB0 的键（主站未受影响）；
- 不修改账号、密码或数据库；
- 不启动定时更新调度器。

## 关联与依赖

- 前置：[OPS-05](OPS-05.md)（聚星隔离栈启动）、[KJX-01](KJX-01.md)。
- 限流代码：`backend/src/xingtu/product_auth.py` 的 `RedisLoginLimiter`（默认 5 次 / 900 秒）。
- 隔离配置：`.runtime/kjx-full/regression/env` 的 `XINGTU_REDIS_URL=redis://127.0.0.1:6379/15`。

## 验收清单

- [x] 聚星栈五进程重启成功：Temporal `79006`、API `79033`、Intake `79050`、Collection `79059`、Vite `79084`。
- [x] Redis DB15 的 `xingtu:login:*` 键由 3 个（IP 桶 5 次、账号桶 3/2 次）清为 0。
- [x] `POST /api/auth/login` 使用正确凭据返回 200，用户 `kjx-regression-media`。
- [x] 真实 Chromium 登录后进入 `/tasks`，页面不再出现「尝试次数过多」。
- [x] 两队列各 1 个新鲜消费者；重启前聚星任务均为终态（3 COMPLETED / 3 PARTIAL_COMPLETED），无在途任务被打断。
- [x] 主站 8000/5173 四进程与定时更新状态未变。

## 实现记录

1. 读取 `RedisLoginLimiter`：`max_failures=5`、`window_seconds=900`，`check()` 在密码校验前执行；IP 或账号任一桶达到 5 即返回 429 `PLATFORM_RATE_LIMITED`。
2. 检查 Redis DB15：`xingtu:login:ip:*` 计数 5、TTL 约 617s；两个账号桶计数 3/2。确认仅重启进程无效。
3. 执行 `./.runtime/kjx-full/stack.sh restart`：等待旧 Worker 45 秒心跳窗口后重启；API/前端/两 Worker 就绪，两队列各 1 个新鲜消费者。
4. 删除 DB15 的 `xingtu:login:*` 键（3 个），复查为 0。
5. 用正确凭据请求 `POST /api/auth/login`（Origin `http://127.0.0.1:4193`）返回 200；Playwright 真实 Chromium 登录后进入 `/tasks`，无「尝试次数过多」文案。

## 验证证据

- 时间与环境：2026-10-31 01:14—01:18（Asia/Shanghai），聚星隔离栈，测试库 `xingtu_test_kjx_regression`。
- 限流键：清理前 `xingtu:login:ip:* count=5 ttl=617s`、`xingtu:login:account:* count=3/2`；清理后 `0`。
- API 登录：HTTP 200，`username=kjx-regression-media`。
- 浏览器：登录后 URL `/tasks`，任务中心渲染，页面无「尝试次数过多」；控制台仅登录前的预期 401 `/api/auth/me`。
- 详细记录：[OPS-06 聚星登录限流处置](../evidence/OPS-06-juxing-login-rate-limit-2026-10-31.md)。

## 交接信息

- 聚星体验入口：`http://127.0.0.1:4193/`；账号 `kjx-regression-media`，密码见 `.runtime/kjx-full/regression/credentials`。
- 连续输错 5 次会再次触发 15 分钟限流；请确认密码无多余空格/引号。若再次被限流，可等待 15 分钟，或执行：
  `redis-cli -p 6379 -n 15 --scan --pattern 'xingtu:login:*' | xargs -r redis-cli -p 6379 -n 15 del`
- 重启命令：`./.runtime/kjx-full/stack.sh restart`（会等待旧 Worker 心跳窗口约 50 秒）。
- 本次未改代码、契约、迁移；未运行测试套件；未提交。

## 状态历史

- 2026-10-31 01:14 新建：接用户「登录提示尝试次数过多，重启体验站」请求；确认根因为 Redis 登录限流而非进程故障。
- 2026-10-31 01:18 已完成：重启聚星栈、清除 DB15 限流键；API 与浏览器登录均恢复。
