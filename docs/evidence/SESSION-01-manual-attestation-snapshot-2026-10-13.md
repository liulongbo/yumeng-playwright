# SESSION-01：唯一子账号人工确认与会话快照核验

> 日期：2026-10-13（Asia/Shanghai）。环境：`unit-local-mac-02`，`local_development`，专属 Chrome profile。关联：[SESSION-01](../tasks/SESSION-01.md)、[DEC-016](../decisions/DEC-016-manual-identity-attestation.md)。

## 授权与边界

用户确认该登录身份只有绑定子账号 `ID: 1807978499337419`，并明确授权带审计、时限 30 天的人工身份确认。该确认只在受保护业务页可见、登录页与安全挑战均不可见、旧账号定位器不可读时使用；不同账号、登录页和挑战页仍强制拒绝。

## 实测

执行三次受控 `xingtu session-diagnostics --config .runtime/units/local-dev-mac-02.json` 冷启动；最后一次报告为 `.runtime/session-diagnostics/unit-local-mac-02-20261013T084837Z.json`，其脱敏摘要为：

- `SessionHealth=VALID`，`evidence_reason=MANUALLY_ATTESTED_UNIQUE_ACCOUNT`；受保护页为真，登录页和挑战页均为假。
- `expected_account_id` 与人工确认的 `observed_account_id` 同为绑定 ID。
- `session_snapshot.restored_before_navigation=true`：前一次保存的快照已在本次首个导航前注入；本次正常关闭确认完成。
- 再次导出的私有快照为 `.runtime/profiles/storage-state/unit-local-mac-02.json`，包含 42 个 Cookie、2 个 origin、1 个会话 Cookie；目录权限 `0700`、文件权限 `0600`。

报告仅保留 Cookie/Storage 值的本地 HMAC，本文不记录 Cookie、Token 或 Storage 明文。未执行搜索、采集或业务数据库写入。

## 结论与限制

当前登录会话已保存且已经过一次新的 Chrome 冷启动复用验证；后续任务可先复用该私有 snapshot，不应要求每次人工登录。该结论不是平台服务端会话的永久保证：平台主动失效、登录页、安全挑战、人工确认到期（2026-11-12T16:39:32+08:00）或未来可读到的身份不一致时，系统仍会停止并要求维护。
