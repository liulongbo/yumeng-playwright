# 巨量星图一期混合部署手册

更新时间：2026-10-19
适用范围：腾讯云中心服务 + Mac 原生 Collection Worker + OpenWrt 后续移动线路。

## 1. 已确认边界

- 腾讯云运行 Nginx/前端、API、Intake Worker、更新调度器、PostgreSQL、Temporal、Redis、MinIO；不运行 Chrome、Playwright 或 Collection Worker。
- Mac 运行 `unit-mac-cell-01` 的原生 Python Worker、Playwright、Headful Chrome、独立 Profile 和本地 F10 人工处理。首期不声明远程 noVNC 已验收。
- 云端与 Mac 只通过 Tailscale 私网访问 PostgreSQL `5432`、Temporal `7233`、MinIO API `9000`。Redis、Temporal PostgreSQL、MinIO Console 均不开放给 Mac 或公网。
- OpenWrt/移动卡作为独立第六阶段接入。没有真实、未过期的 NetworkProof 与实时 probe 时，生产 Worker 启动失败；不得回落家庭宽带。

## 2. 文件与密钥

服务器复制以下样例，填值后均执行 `chmod 600`：

```sh
cp deploy/production.env.example deploy/production.env
cp deploy/application.env.example deploy/application.env
cp deploy/ops/cos-backup.env.example /root/.config/yumeng/cos-backup.env
```

`production.env` 只供 Compose 插值，包含基础设施 root 凭据；`application.env` 只注入应用容器。不得把填值文件提交 Git。数据库 URL 中的特殊字符必须 URL 编码。

Mac 将 `worker.env.example`、`unit-mac-cell-01.json.example` 复制到项目外的私有目录并设为 `600`。`NetworkProof` 必须由真实移动线路验收产生，样例不会生成或伪造它。

## 3. 腾讯云部署顺序

以下命令在仓库根目录运行，第一阶段本地开发不会实际执行这些云端命令。

```sh
docker compose --env-file deploy/production.env -f deploy/production.compose.yaml config
docker compose --env-file deploy/production.env -f deploy/production.compose.yaml build
docker compose --env-file deploy/production.env -f deploy/production.compose.yaml up -d app-postgres temporal-postgres redis objects
docker compose --env-file deploy/production.env -f deploy/production.compose.yaml up -d temporal objects-init
docker compose --env-file deploy/production.env -f deploy/production.compose.yaml up migration
docker compose --env-file deploy/production.env -f deploy/production.compose.yaml up -d api intake-worker update-scheduler
```

Migration Job 成功退出是应用启动前置条件。先按 `API_BIND_PORT` 检查 `curl http://127.0.0.1:${API_BIND_PORT:-8000}/api/health/live`，再在宝塔安装 `deploy/nginx/baota-xingtu.conf.template`，并将 `CHANGE_ME_API_PORT` 替换为同一个端口。前端发布：

```sh
npm --prefix frontend ci --no-audit --no-fund
npm --prefix frontend run build
```

只把 `frontend/dist/` 发布到 Nginx 站点目录。宝塔负责证书与续期；`XINGTU_ALLOWED_ORIGINS` 必须与唯一 HTTPS Origin 完全一致。`/api/` 同时覆盖 HTTP API 与 F10 WebSocket Upgrade。

## 4. Mac Worker 安装

前置条件：Mac 已登录图形用户会话、关闭系统自动休眠、项目虚拟环境与 Playwright 已安装、Tailscale ACL 允许该 Mac 到云端三个私网端口。

1. 配好私有 UnitConfig、Worker 环境文件和真实线路 probe；注册单元：`xingtu register-unit --config <unit.json>`。
2. 将 plist 模板中的四个占位符替换为绝对路径，用 `plutil -lint` 检查后放入 `~/Library/LaunchAgents/`。
3. 通过 `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.yumeng.xingtu.collection-worker.plist` 加载。
4. 用 `launchctl print gui/$(id -u)/com.yumeng.xingtu.collection-worker` 与日志检查状态。

启动包装器先检查私有文件权限、Aqua 会话、已核验 Registry 与单元网络模式。`production_line` 必须通过 NetworkProof 和实时线路 probe；`local_development` 只能输出 `test_only` 标记，且其 UnitConfig 不允许代理或生产线路证明。任一适用检查失败均不启动 Worker。`caffeinate` 仅在 Worker 存活期间防止 Mac 休眠，不改变 Profile 锁、浏览器租约或代次 fencing。

停止时先确保没有活动任务/人工接管，再运行：

```sh
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.yumeng.xingtu.collection-worker.plist
```

## 5. 健康、端口与资源

生产 Compose 的宿主端口应只有：公网 `80/443`（宝塔 Nginx）、回环 `127.0.0.1:${API_BIND_PORT:-8000}`（API，默认 8000）、回环 `127.0.0.1:9001`（MinIO Console）、Tailscale IP 上的 `5432/7233/9000`。安全组不得开放后三者到公网；Tailscale ACL 只授权指定 Mac。

Temporal poller 是 TTL 信号：当前代码以 180 秒 freshness + 5 秒监控周期识别 `xingtu-unit-mac-cell-01`，因此离线状态最迟约 185 秒收敛；Temporal 不可达时显示 `UNKNOWN`，不会伪报 OFFLINE。数据库单元状态、线路验证、浏览器租约分别展示。中心端尚无新鲜 NetworkProbe 持久事实时，线路状态明确显示 `UNKNOWN`；不拿 READY、会话或 Worker 在线冒充线路健康。

资源预算是估算而非实测：常驻容器默认上限合计约 3.1 GiB，另需给 TencentOS、Docker、宝塔/Nginx 留约 0.4–0.8 GiB；Migration 与对象初始化为短时进程。2C/3.5 GiB + 2 GiB Swap 适合单用户、单单元试运行，但余量很小。部署后每 5 分钟采集一次 `deploy/ops/resource-check.sh` 输出，至少观察 24 小时。

扩容触发条件：连续 15 分钟宿主可用内存低于 350 MiB、Swap 持续增长或超过 512 MiB、任一容器 OOM/restart、CPU 连续 15 分钟高于 80%、磁盘使用超过 75% 或预计 14 天内超过 85%。先按实测定位容器，再决定调整限额或扩容；不在当前服务器启动 Chrome。

## 6. 备份、停止与回滚

安装 AWS CLI 与 MinIO `mc` 后，用 `backup-to-cos.sh` 备份应用库、Temporal 库和对象到 COS 的时间戳目录。首次部署必须在隔离数据库/桶完成一次恢复演练，未经恢复验证不声明 RPO/RTO。

Mac Profile、Keychain 凭据和生产 UnitConfig 不进入上述服务端脚本：它们必须在 Mac 侧用设备加密/受控加密备份单独保护，恢复时仍需重新执行账号、Profile、线路和单元绑定核验；不得把明文 Profile 或 Cookie 直接上传 COS。

停止顺序：先停止 Intake（阻止新任务），确认无活动 Workflow/租约，再停止 Scheduler/API，最后停止依赖：

```sh
docker compose --env-file deploy/production.env -f deploy/production.compose.yaml stop intake-worker update-scheduler api
docker compose --env-file deploy/production.env -f deploy/production.compose.yaml stop temporal redis objects app-postgres temporal-postgres
```

版本回滚：保留上一个不可变 `XINGTU_APP_IMAGE` tag 和前端目录；先备份，切回镜像 tag 与 Nginx `current` 软链接，再 `up -d --no-build`。若新迁移不向后兼容，禁止仅回滚应用镜像，必须按已验证的数据库恢复方案在隔离环境演练后执行。不得删除 named volume 作为回滚手段。

## 7. 分阶段验收

1. 本地配置：Compose 解析、镜像构建、前端构建、相关测试、plist/shell 静态检查通过。
2. 云端基础服务：健康检查通过、端口只绑定回环/Tailscale、资源基线已记录。
3. 中心应用：Migration 成功，HTTPS 登录/API/WS 同源验证，Intake/Scheduler 日志健康。
4. Mac 私网：Tailscale ACL、DB/Temporal/MinIO 最小连通，launchd 重启恢复，Worker queue 从 UNKNOWN/OFFLINE 变 ONLINE。
5. 非真实线路跨机验证：仅验证注册、调度可见性、状态/离线恢复，不启动生产采集，不制造 NetworkProof。
6. OpenWrt/移动出口：真实 egress/DNS/断线 fail-closed/proxy 健康通过后生成受控 NetworkProof。
7. 真实端到端：单任务采集、数据/快照/对象、状态、幂等、Mac 断线重连及异常恢复；F10 首期只验 Mac 本机原浏览器人工处理，远程 noVNC 另卡验收。
