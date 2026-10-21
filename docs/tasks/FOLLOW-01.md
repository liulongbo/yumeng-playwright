# FOLLOW-01：部署后遗留问题跟踪（HTTP 80 / 证书 / P2-P3 / 安全头）

状态：待办
更新时间：2026-10-20T21:45:00+08:00
是否验收：否；仅登记，不在 P1 修复轮扩大范围。

## 目标与范围

承接 [QA-01](QA-01.md) 与 [P1FIX-01](P1FIX-01.md) 的遗留项，按优先级逐项处理；不改变 P1 修复边界。

## 待办项

| ID | 问题 | 优先级 | 建议动作 |
|---|---|---|---|
| F-01 | `http://xingtu.yumeng.live` 3/3 被腾讯云 DNSPod 备案页拦截，未到项目 Nginx | P2 | 向腾讯云核查域名接入/备案；保留显式 HTTPS；确认 80 端口策略 |
| F-02 | Let's Encrypt 证书为手工 DNS-01 签发，未见自动续期 hook，2027-01-18 到期 | P2 | 配置 DNS-01 自动续期（certbot hook + systemd timer）与到期告警；演练一次续期 |
| F-03 | 失败页直接显示 `AI_AUTH_OR_QUOTA` 等内部码与英文供应商消息 | P2 | 建立错误码→中文用户文案映射；`request_id` 保留给支持；本轮 P1FIX 已细化后端分类 |
| F-04 | 执行单元页英文枚举、“验证 正常”与“最近心跳 —”语义混淆 | P3 | 状态中文化；区分 Worker poller、DB 心跳与接管验证；无事件显示“未接管” |
| F-05 | 缺少 HSTS/CSP/X-Frame-Options/X-Content-Type-Options/Referrer-Policy | P3 | 在宝塔/Nginx 增加安全响应头；HSTS 待确认全子域 HTTPS；CSP 先 report-only |
| F-06 | 服务端 PyPI 访问慢，完整 `deploy/Dockerfile.app` 构建 13 分钟未完成 | P2 | 配置可用镜像源/构建缓存；在低峰期重建镜像、记录 digest；避免长期使用派生镜像 |
| F-07 | 管理员密码曾在 DSH 工具输出中出现明文（未写入仓库/证据） | P1（安全） | 用户授权后轮换密码、更新 Keychain、撤销旧会话、清理相关日志；不在本轮执行 |
| F-08 | DSH 直连 SSH 公钥 `yumeng-deploy-2026-10-19` 仍被拒绝；本轮仅用现有 ControlMaster | P2 | 用户将公钥加入服务器授权，或提供受控运维通道；不修改现有认证策略 |
| F-09 | 部署产物未提交 Git，后端运行版本目前靠源文件哈希对齐 | P2 | 审阅后提交部署文件；镜像 tag 使用提交 SHA；记录 digest/compose 哈希 |

## 验收方式

每项单独建立实施/验收证据；F-07 的轮换操作必须使用不输出明文的交互方式，并保留脱敏记录。
F-01/F-02 需要腾讯云/阿里云账号侧操作时，先报告所需授权，不擅自修改 DNS/防火墙。

## 关联

- [QA-01](QA-01.md) 冒烟报告：[deployment-smoke-test-2026-10-20.md](../evidence/deployment-smoke-test-2026-10-20.md)
- [P1FIX-01](P1FIX-01.md) 及 [修复报告](../evidence/P1-intake-fix-2026-10-20.md)

## 状态历史

- 2026-10-20：待办 → 待办；登记 QA-01/P1FIX-01 遗留项，等待排期与授权。
