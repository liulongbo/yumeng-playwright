# DEP-01：生产应用容器化

状态：已完成
更新时间：2026-10-19
是否验收：是；仅指第一阶段开发与本地验证，不代表腾讯云实机部署通过。

## 目标与范围

为 API、Intake Worker、更新调度器和数据库迁移提供同版本应用镜像及生产 Compose；云端不运行 Collection Worker、Playwright 或 Chrome。

## 验收清单

- [x] 生产 Compose 可解析，持久化、健康检查、依赖和内部网络正确。
- [x] 同一应用镜像可分别启动 API、Intake、Scheduler、Migration。
- [x] 数据库、Redis、Temporal 与 MinIO Console 不暴露公网。
- [x] 应用镜像本地构建通过，环境样例不含真实密钥。

## 验证证据

- 2026-10-18：确认基线 `5182c09`，工作区干净；现有 `deploy/compose.yaml` 仅含开发依赖。
- 2026-10-19：`docker compose config --quiet` 通过；生产服务清单不含 Collection Worker/Chrome。最终应用镜像构建成功（本机 arm64，`sha256:d3e9471f…`），四类 CLI 入口来自同一镜像；镜像内无 `/ms-playwright` 浏览器目录。
- 端口静态核对：API/MinIO Console 仅回环；PostgreSQL/Temporal/MinIO API 仅 Tailscale IP；Redis、Temporal PostgreSQL 无宿主端口。真实 x86_64 云端启动留待第二阶段。

## 状态历史

- 2026-10-18：待办 → 进行中；用户授权第一阶段开发与本地验证。
- 2026-10-19：进行中 → 已完成；第一阶段开发与本地构建验收通过。
