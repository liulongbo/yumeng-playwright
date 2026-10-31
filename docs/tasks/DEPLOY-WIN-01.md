# DEPLOY-WIN-01：Windows 部署与 ExecutionUnit 验收

状态：未开始（等待 Windows 实机与用户单独授权）  
建立时间：2026-10-28T23:55:00+08:00  
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

macOS 阶段 C 的 C1—C4 已通过，证据见 [KJX-01 阶段 C 验收](../evidence/KJX-01-stage-c-acceptance.md)。Windows 尚未执行任何实机验证；不将 macOS 结论外推为 Windows GO。
