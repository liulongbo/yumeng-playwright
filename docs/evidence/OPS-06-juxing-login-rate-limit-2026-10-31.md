# OPS-06 聚星体验站登录限流解除与重启（2026-10-31）

- 时间：2026-10-31 01:14—01:18（Asia/Shanghai）
- 环境：聚星隔离栈，测试库 `xingtu_test_kjx_regression`，Redis DB15
- 任务卡：[OPS-06](../tasks/OPS-06.md)
- 用户现象：登录 `http://127.0.0.1:4193/` 提示「尝试次数过多，请稍后再试」

## 1. 根因

`backend/src/xingtu/product_auth.py` 的 `RedisLoginLimiter`：

- `max_failures=5`、`window_seconds=900`；
- 同时维护 IP 桶与账号 HMAC 桶；
- `check()` 在密码校验之前执行，任一桶 `>= 5` 即返回 `429 PLATFORM_RATE_LIMITED`。

检查 Redis DB15（聚星栈专用，主站用 DB0）：

```
xingtu:login:account:2a81… count=3 ttl=617s
xingtu:login:account:3903… count=2 ttl=526s
xingtu:login:ip:8623…      count=5 ttl=617s
```

IP 桶已达 5，因此即使输入正确密码也会被拒绝。**仅重启进程不会清除 Redis 限流状态**。

## 2. 处置

```bash
# 重启聚星隔离栈（等待旧 Worker 45 秒心跳窗口）
./.runtime/kjx-full/stack.sh restart

# 清除该栈专用 Redis DB15 的登录限流键
redis-cli -p 6379 -n 15 --scan --pattern 'xingtu:login:*' \
  | xargs -r redis-cli -p 6379 -n 15 del
```

结果：3 个键被删除，复查剩余 0 个。

重启后进程：

| 服务 | PID |
|---|---|
| Temporal | 79006 |
| API | 79033 |
| Intake Worker | 79050 |
| Collection Worker | 79059 |
| 前端 Vite | 79084 |

队列：`xingtu-intake` 与 `xingtu-unit-local-mac-02-kjx-full` 各 1 个新鲜消费者。重启前测试库任务均为终态（3 COMPLETED / 3 PARTIAL_COMPLETED），无在途任务。

## 3. 登录验证

API：

```bash
curl -s -o /tmp/kjx-login.json -w '%{http_code}' \
  -H 'Content-Type: application/json' \
  -H 'Origin: http://127.0.0.1:4193' \
  -d "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}" \
  http://127.0.0.1:4192/api/auth/login
```

结果：`HTTP 200`，返回 `username=kjx-regression-media`。

浏览器（Playwright + 项目 Chromium，headless）：

- 打开 `4193/login`，填入正确凭据，点击「安全登录」；
- URL 进入 `/tasks`，任务中心渲染；
- 页面文本不含「尝试次数过多」；
- 控制台仅有登录前的预期 `401 /api/auth/me`。

## 4. 主站影响

- 主站 8000/5173 四进程保持不变；`update-scheduler` 未运行。
- 本次只清理 Redis DB15；主站使用的 DB0 未触碰。
- 未改登录限流阈值、代码、账号或数据库；未运行测试套件。

## 5. 复发处理

连续输错 5 次会再次触发 15 分钟限流。确认密码无多余空格或引号；再次被限流时可等待窗口结束，或重复上面的 DB15 清理命令。完整重启使用 `./.runtime/kjx-full/stack.sh restart`。
