# DEPLOY-WIN-01：Windows 部署与 ExecutionUnit 验收

状态：进行中（Windows 已部署；本轮先审计星图账号绑定与会话持久化，不操作 Windows 主机）
建立时间：2026-10-28T23:55:00+08:00  
更新时间：2026-10-31T22:41:24+08:00（Asia/Shanghai）
关联：[KJX-01](KJX-01.md)（macOS 阶段 C 已通过）、[F10](F10.md)（Windows 仍为 NOT TESTED）。

## 目标

在 Windows 实机完成 KJX-01 的部署与执行单元验收，证明 macOS 已通过的聚星/星图能力不依赖 POSIX 路径、Profile 锁或浏览器进程语义。Windows 验收不属于本轮 macOS 阶段 C，未获授权前不开始。

## 范围

- Windows Python/Node/Playwright/Chrome 运行环境与仓库路径；
- 独立 `.runtime` 私有根、星图/聚星 Profile 目录、Profile 锁与 `lockfile` 停止证明；
- 双平台账号/Profile/registry 绑定，`unit_id`、worker generation、lease/heartbeat；
- 隔离测试 DB、Temporal、API、Vite、真实 Chrome 冷启动与会话恢复；
- 至少一条聚星 1 位真实闭环与一条星图 1 位回归（若 Windows 采集另需授权）；
- Windows 实机限制与 macOS 行为差异记录。

## 验收门槛

- [ ] Windows 配置路径/Profile 绑定不依赖 POSIX 专属语义。
- [ ] Chrome Stable 发现、Profile 独占、正常关闭、锁文件停止证明在 Windows 成立。
- [ ] 隔离 DB + Temporal + API + Worker 启动，双平台绑定与 worker generation 正确。
- [ ] 真实会话冷启动可恢复；账号不匹配/挑战/登录页均 fail closed。
- [ ] 聚星/星图至少各一条真实任务达到任务级验收，平台、账号、Profile、数据隔离成立。
- [ ] 生产 Feature Flag、正式业务库与平台写操作明确不在默认授权内。

## 前置与授权

- Windows 实机可用，Chrome、Python、Node、Playwright 已安装；
- 独立测试库、Temporal 与私有运行目录；
- 真实采集须用户单独授权，明确样本、平台、目标和只读边界；
- 生产库迁移 020、生产 Flag 开启、平台写操作须另行批准。

## 当前结论

macOS 阶段 C 的 C1—C4 已通过，证据见 [KJX-01 阶段 C 验收](../evidence/KJX-01-stage-c-acceptance.md)。
用户已把项目部署到 Windows，且提供了 Windows 主站只读状态和星图真实冷启动失败证据；本仓库会话未直接
连接 Windows 主机复核。当前星图结果为 **NO-GO**：历史 `VALID` 不能覆盖当前登录页事实，必须完成
同一绑定下的受控登录、快照生成和双冷启动恢复后才能继续第 4—8 页探测。

## 本轮记录（2026-10-31）

- 用户报告项目已经部署到 Windows，但巨量星图 Profile 的真实冷启动探测返回
  `NO_REGISTERED_SESSION_SIGNAL`，页面跳转到 `/?redirect_uri=/ad/creator/market` 并显示登录；数据库中的
  历史 `last_session_status=VALID` 已被真实探测推翻。
- 本轮获授权范围是审计仓库中的账号／执行单元／Profile／会话快照绑定，并形成 Windows 可执行方案；
  未获授权远程操作 Windows、重新登录、重启服务、修改生产配置、执行真实采集或写主库业务数据。
- 已核对 `UnitConfig`、`execution_units`、`execution_unit_platform_bindings`、`BrowserRuntime`、
  Windows 启动手册与当前私有配置。浏览器实际绑定来自 Worker 的 `--config` JSON，不来自数据库旧
  `profile_ref`；正式 Worker 的星图快照路径为
  `<repo>\.runtime\profiles\storage-state\<unit_id>.json`。
- 已补充 Windows 配置示例、快照元数据只读检查、同一 BrowserContext 受控登录和双冷启动验收步骤：
  [Windows 星图账号绑定与会话持久化审计](../evidence/DEPLOY-WIN-01-xingtu-session-persistence-review-2026-10-31.md)。
- 已更新 [F10 本机运行手册](../F10-local-macos-windows.md)，明确旧
  `.runtime\storage-state\` 不是正式 Worker 的读取位置，且数据库历史 `READY/VALID` 不能跳过新进程核验。

## 验证证据

- 2026-10-31，本机 macOS、当前 `快手_1026@c7d12cd`，只读审计代码、文档及私有配置的非敏感绑定／
  快照元数据；未读取或输出 Cookie 值。
- `PYTHONPATH=backend/src .venv/bin/pytest backend/tests/unit/test_session_snapshot.py
  backend/tests/unit/test_local_network_mode.py backend/tests/unit/test_platform_runtime.py -q` →
  **32 passed in 0.14s**，exit 0。覆盖混合快照导出／恢复、平台 Profile 隔离、Windows 私有路径／锁分类。
- `git diff --check` → 通过，exit 0。

## 阻塞与下一步

1. 需要 Windows 操作者按审计报告确认实际 Worker 的绝对 `--config`、`unit_id`、Profile、registry 和快照
   路径属于同一绑定；只核对元数据，不发送快照或 Cookie。
2. 需要在 Worker 持有的登录维护上下文中人工登录星图并形成账号精确匹配；短信／设备验证必须由用户完成。
3. 正常关闭后做两次独立冷启动诊断，均须 `VALID`、账号一致、受保护页可用、
   `restored_before_navigation=true`。完成前本卡不勾选真实会话验收。
4. 双冷启动通过后，仅重跑星图第 4—8 页只读探测；合同更新、服务重启、真实 100 位采集仍分别授权。

## 状态历史

- 2026-10-31T22:40:09+08:00：未开始 → 进行中。用户确认 Windows 已完成部署并提供星图冷启动登录失效证据；
  开始只读审计当前绑定和混合会话持久化链路。Windows 实机操作、登录、重启及真实采集仍未授权。
- 2026-10-31T22:41:24+08:00：保持进行中。完成绑定／快照路径审计和 Windows 落地手册，定向离线测试
  32 passed、`git diff --check` 通过；Windows 双冷启动尚未执行，星图会话保持 NO-GO，不改变合同或运行态。
