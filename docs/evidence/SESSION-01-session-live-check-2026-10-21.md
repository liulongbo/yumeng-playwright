# SESSION-01 当前执行单元会话实时只读核验（2026-10-21）

## 结论

当前唯一执行单元 `unit-local-mac-02` 的巨量星图登录状态为 **`VALID`（有效）**。

- 绑定账号：`ID: 1807978499337419`
- 实测账号：`ID: 1807978499337419`
- 受保护业务页：已验证
- 登录页：未出现
- 安全挑战：未出现
- 会话快照：首次导航前已恢复，核验后成功刷新
- 身份判定：`PROTECTED_PAGE_AND_ACCOUNT_VERIFIED`，未使用人工确认降级

该结论是 `2026-10-21T16:58:54+08:00` 的进程内观测，不是复读数据库历史状态。

## 执行与证据

环境：macOS 本机开发单元，项目专属 profile，系统 Chrome `156.0.8078.47`。

实际命令：

```bash
XINGTU_DIAGNOSTIC_HMAC_KEY="<本机私有密钥>" \
PYTHONPATH=backend/src \
.venv/bin/xingtu session-diagnostics \
  --config .runtime/units/local-dev-mac-02.json
```

1. `2026-10-21T16:58:33+08:00` 首次在受限沙箱中启动，Chrome 因 macOS Crashpad/Mach 端口权限被拒而在访问平台前退出（exit 1）。该结果不是会话失效证据。
2. 以同一只读命令在允许 Chrome 正常启动的环境重试，exit `0`；脱敏报告为 `.runtime/session-diagnostics/unit-local-mac-02-20261021T085856Z.json`（权限 `0600`，不纳入版本库）。
3. 报告返回 `session_health.status=VALID`，账号精确一致，受保护页为真，登录页与挑战页为假，`browser.normal_close_confirmed=true`。
4. 报告明确 `session_snapshot.restored_before_navigation=true`；私有快照 `.runtime/profiles/storage-state/unit-local-mac-02.json` 在 `2026-10-21T16:58:56+08:00` 刷新，权限 `0600`。
5. 诊断结束后 profile 无 `Singleton*` 锁，Chrome 已正常关闭。

## 边界

- 本轮未搜索、未采集、未重新登录，未写业务数据库。
- 诊断报告仅保存 Cookie/Storage 的 HMAC 摘要，命令输出明确 `contains_plaintext_tokens=false`；本文未复制任何 Cookie、Token 或 Storage 原值。
- `VALID` 只证明本次观测时点的登录状态；平台后续仍可使会话失效，本轮不用单点观测宣称已测出会话存活上界。
- `./dev.sh status` 显示当时采集 Worker 未运行；这不影响会话诊断结论，但不能由本次核验推导任务采集链路就绪。

## 人工查看窗口（同日追加）

`2026-10-21T17:03:05+08:00` 应用户要求，使用同一单元配置与 `BrowserRuntime` 打开 `https://www.xingtu.cn/ad/creator/index`，私有快照依旧在首次导航前恢复。Chrome PID `61698` 已持有专属 profile 的 `SingletonLock`，命令进入 1800 秒人工查看等待，证明窗口已成功启动。本轮未启动采集、未自动点击或搜索；窗口存续期间该 profile 不可被 Worker 并发使用。用户查看完成后应完全退出该 Chrome（macOS `Command-Q`），不只关闭窗口。
