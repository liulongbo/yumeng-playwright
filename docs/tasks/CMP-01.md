# CMP-01：main 单机基线部署与混合架构对比

状态：进行中
更新时间：2026-10-21T11:40:00+08:00
是否验收：否；本地 main 已跑通控制台，服务器部署等待 SSH 授权。

## 目标与范围

把 `origin/main`（不含混合架构）以单机容器化方式部署到独立服务器，与 `lln_1018` 的混合架构（腾讯云中心 + Mac Collection Worker + Tailscale）做对照：同一套业务代码，比较部署复杂度、资源占用、可维护性与真实采集可行性。

包含：独立 Compose 工程（`deploy/single-node.compose.yaml`）、独立镜像（app/web/worker）、独立目录与端口；服务器既有两个应用不改动。

不包含：合并到 `main`；替换现有混合部署；在服务器上创建真实采集任务（会话注入需单独授权）；TLS/域名（先 IP + 端口验收）。

## 关联与依赖

前序：[DEP-01](DEP-01.md)（生产容器化）、[DEP-02](DEP-02.md)、[OPS-01](OPS-01.md)（生产运行）、[HYB-01](HYB-01.md)（Worker 在线状态）。对比基准分支：`lln_1018`（远程同名分支，HEAD `188cb53`）。

## 验收清单

- [ ] `docker compose config` 解析通过，且只发布 `18080` 与回环 `18000`。
- [ ] app/web/worker 三个镜像在目标服务器构建成功。
- [ ] `migration` 一次性成功，`api`、`web`、`intake-worker`、`update-scheduler`、`collection-worker` 启动且健康。
- [ ] `http://101.42.14.225:18080/` 返回控制台页面，`/api/health/live` 返回 200。
- [ ] 服务器既有两个应用的端口/进程/站点未被改动。
- [ ] 记录各容器内存与宿主余量，给出可否长期保留 Chrome 的结论。
- [ ] 形成与混合架构的对比结论（部署步骤数、资源、网络依赖、真实采集可行性）。

## 实现记录

2026-10-21：从 `origin/main`（`5182c09`）新建分支 `deploy/main-single-node`，只新增部署脚手架，不改业务代码：

- `deploy/single-node.compose.yaml`：单机拓扑，`data` 内部网络 + `egress`；仅 `web` 对外，API 绑回环。
- `deploy/Dockerfile.app`：复用 `lln_1018` 的通用应用镜像。
- `deploy/Dockerfile.web`：Vite 构建静态包，Nginx 提供页面并代理 `/api/`。
- `deploy/Dockerfile.worker`：应用镜像 + Playwright Chromium（`headless`），采集 Worker 容器。
- `deploy/single-node.env.example`、`deploy/single-node.application.env.example`、`deploy/units/unit-server-01.json.example`。
- `docs/deployment/main-baseline-runbook.md`：部署、验证、隔离与已知限制。

与 `main` 的差异点：`main` 的 `migrate` 只接受 `--environment development|test`（生产名称为 `lln_1018` 才支持），`intake-worker`/`update-scheduler` 使用 `--unit-config` 而非 `--execution-unit-id`；Compose 已按 `main` 的真实 CLI 编写。

## 验证证据

- 2026-10-21：`git archive`/部署文件静态检查完成；实机验证被 SSH 授权阻塞（`ubuntu@101.42.14.225` 返回 `Permission denied (publickey)`），未在服务器执行任何变更。
- 2026-10-21 本地：`main` 本地快进到 `5182c09` 后用原生进程（无 Docker）跑通：PostgreSQL 18 `55432`、Redis `56379`、Temporal dev 1.9.1 `57233`、API `8000`、Vite `5173`；迁移成功，`create-user` 建 `admin`，经 Vite 代理登录 200、`/api/auth/me` 200、`/api/tasks` 200（空）。步骤见 [本地 main 运行手册](../deployment/local-main-runbook.md)。
- 2026-10-21：发现 `main` 没有 `/api/health/live`（该路由仅在 `lln_1018`），Compose 的 API healthcheck 已改为 TCP 探活，避免 api 被误判 unhealthy 而 web 永不启动。

## 交接信息

阻塞项：目标服务器 `ubuntu` 用户尚未安装部署公钥（`yumeng_xingtu_tencent_ed25519`），无法登录。
下一步：授权后先只读盘点（端口、内存、Docker、既有两应用），再按 runbook 部署并采集证据。
