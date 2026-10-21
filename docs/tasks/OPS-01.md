# OPS-01：生产运行、资源调度与运维恢复

状态：进行中
更新时间：2026-10-20T20:32:00+08:00
是否验收：否；中心服务、正式入口、Tailnet 与 Mac Worker 已实机接入，但备份恢复、移动线路、真实采集和完整故障演练尚未完成。

## 目标与范围

**目的**：把已有采集组件组装为可持续运行、可隔离故障、可备份恢复的一期系统。

**任务内容**：补齐产品 FIFO 等待与可用单元分配、资源健康与排空、进程监督/失联隔离及节点迁移；完整应用部署、凭据/profile 保护、资源限额、监控告警、对象生命周期、异机备份恢复、发布/回滚手册。底层账号/线路绑定和真实网络核验继续由 UNIT-01 主责。

**不包含**：不采购第二组硬件作为一期强制条件，不引入 Celery/Kafka/RabbitMQ，不把完整监控集群当必须项；生产发布另按授权执行。

## 关联与依赖

F11 的产品资源调度与部署；技术方案第 12、14、17 章及附录 A。T12/T13/T18—T20/T22/T42，U07/U08/U09。

前置：[BASE-01](BASE-01.md)、[UNIT-01](UNIT-01.md)；部署集成依赖 APP-01、INTAKE-01、F06、CONSOLE-01、F09、F10 的对应服务产物，见 [总览](../项目任务进度总览.md)。可提前开展基础运维工作。

## 当前开发状态与实现记录

2026-10-18 已按用户批准的混合部署方案启动第一阶段：生产容器、宝塔 Nginx、中心配置解耦、Worker 在线状态、Mac launchd 与最小备份/日志/回滚手册。腾讯云、Tailscale、COS 恢复及真实移动线路均不在本轮实机执行。

本轮仅核对代码并建立卡片；下列现有文件是复用依据，不代表本卡已开发完成：[部署](../../deploy/compose.yaml)、[Worker](../../backend/src/xingtu/worker.py)、[运行时](../../backend/src/xingtu/runtime.py)、[证据](../../backend/src/xingtu/evidence.py)。

## 验收清单

- [ ] 提交时无需媒介选执行单元；可用资源按 FIFO 服务，继续任务按恢复提交时刻重排；每单元并发 1，无资源等待可恢复。
- [ ] 与 UNIT-01 联合验证线路/DNS/隧道断开不直连，旧节点先停止或撤销访问后重分配，无法确认则隔离；模拟第二单元并在条件具备后实机验证。
- [ ] 完整部署包含应用、P1/工作流 Worker、浏览器 Worker 及依赖，版本可复现、资源隔离、内部端点不公开；API 重启不影响已持久任务。
- [ ] 密钥与业务备份分离，凭据/profile 受保护；摘要90天/失败证据30天/审计至少1年，业务快照及引用封面持续保留，清理不会破坏历史。
- [ ] 结构化日志、指标、健康检查及告警覆盖数据库/存储/单元失联/登录/契约/备份；不以达人 ID 等高基数字段作指标标签。
- [ ] 异机恢复同时核对业务库、Temporal、对象引用、配置/profile 与旧节点隔离，实测记录 RPO/RTO。
- [ ] 迁移与工作流历史兼容、排空、发布/回滚演练及第17.4节全部故障手册有可执行记录；U07/U08/U09 运维相关项关闭。

## 验证证据

- 2026-09-27：静态盘点依据见 [项目基线证据](../evidence/PROJECT-BASELINE-2026-09-27.md)。
- 2026-10-19：第一阶段产物与命令见[混合部署手册](../deployment/hybrid-production-runbook.md)。Compose 解析、应用镜像构建、Nginx 语法、前端 build、Mac plist/shell 静态检查通过；后端 309 单测、33 契约测试、25 项相关 PostgreSQL 集成测试及前端 83 测试通过；本轮改动文件 Ruff/format、全后端 mypy strict 通过。
- 2026-10-19：用户授权启动阶段 A 腾讯云实机部署。开始前复核分支为 `lln_1018`、HEAD 为 `5182c09d0fb212eaad5b01b994d2676792efb395`；第一阶段未提交文件保持原状，未清理、覆盖或提交。当前先执行服务器访问权限与生产配置前置条件审计。
- 2026-10-19：阶段 A 独立完成 `linux/amd64` 镜像构建与运行时校验：`xingtu-app:stage-a-amd64`，镜像 ID `sha256:a2b3e0d5e88252e2b6a235be9a67ed4ae3b7b266be27d386ae0988b898348133`，大小 448,080,389 bytes；CLI 可直接启动，以非 root 用户 `xingtu` 运行，未包含 `/ms-playwright` 浏览器包。一次 `sh -lc` 检查因登录 shell 重置 PATH 失败，经与 Compose 一致的直接命令复核为检查方式假阳性，无需修改代码。
- 2026-10-19：对 `101.42.14.225:22` 的只读 SSH 探测可到达主机，但 `root` 公钥认证被拒；本机也不存在 `deploy/production.env`、`deploy/application.env`（只保留样例）。因此未读取或修改服务器、未启动容器、未执行 Migration、未发布前端，资源/端口/持久化均不能宣称实机通过。阶段 A 保持进行中，等待受控 SSH 权限、服务器端生产配置和数据库迁移单独确认。
- 2026-10-19：公网侧固定端口初筛显示 22/80/443/5432/6379/7233/9000/9001 均可完成 TCP 握手，但 Redis PING 被关闭、PostgreSQL SSLRequest 无协议响应，且未使用的控制端口 49152 同样可握手；因此该结果受统一接入层或探测路径影响，不能证明数据库等服务实际公网暴露。必须登录服务器后用 `ss`、Docker 端口映射及安全组规则完成权威核验。
- 2026-10-19：用户改为授权部署目标 `119.91.210.100:22`。只读握手确认 OpenSSH 9.3，服务器 ED25519 主机指纹为 `SHA256:NpRG3kFYA8r3QgzLCv1Tgkb5+FchFfnAt5mV4cw8Q9k`，支持 publickey/password 等认证；当前本机无已有身份。因自动化环境没有安全的交互密码输入通道，未把用户密码写入命令、环境、日志或文件。按用户指定方案生成本机专用密钥 `~/.ssh/yumeng_xingtu_tencent_ed25519`（私钥 0600），公钥指纹 `SHA256:gIjokRgfn2Uu//Zyz4k+k4/kpHe4W2D90HfUvr7ivzo`；等待用户在服务器侧授权公钥后继续只读环境检查。
- 2026-10-19：用户后续明确改为仅使用既有 SSH 密码认证，不采用公钥授权。已生成的本地专用密钥从未安装到服务器，后续不使用、不新增、不修改服务器 SSH 认证。当前自动化终端不能把交互式密码提示安全转交给用户；通过工具填写会使密码进入调用记录，因此未尝试 `sshpass`、AskPass、环境变量或其他非交互绕过。等待用户在本机终端建立受控 SSH ControlMaster 会话，或提供等价的安全交互入口后继续 OPS-01。
- 2026-10-19：用户建立 ControlMaster 后完成腾讯云只读基线。目标为 TencentOS Server 4 / x86_64 / 2C / 3.5 GiB RAM / 2 GiB Swap / 50GB（已用 18%），Docker 29.7.2、Compose 5.4.0；Docker 原先无容器和 Volume。主机已有另一套 `dev.yumeng.live` 原生应用：宝塔 Nginx、MySQL、Redis、`/www/wwwroot/yumeng-dev-platform` 的 Uvicorn 占用 8000，故全部保留并隔离部署到 `/opt/yumeng-xingtu/releases/20261019-5182c09-wip`，新 API 改用回环 18000。现有 firewalld 放行 8000/3306 且 MySQL 监听全地址，属既有环境风险，未擅自改防火墙或旧业务。
- 2026-10-19：服务器 Docker Hub 直连超时；备份 `/etc/docker/daemon.json` 为 `/etc/docker/daemon.json.pre-yumeng-20261019` 后配置腾讯云官方内网加速 `https://mirror.ccs.tencentyun.com`，校验并重启当时无容器的 Docker。为保持锁定依赖，在 Dockerfile 中参数化 uv/PyPI 获取源和锁文件下载基址；腾讯云镜像的 Playwright wheel 长度与锁记录一致，`uv sync --frozen` 继续验证原 SHA256。服务器原生构建镜像 `xingtu-app:20261019-5182c09-wip` 成功，ID `sha256:b611ac13b47c9c56345cbb7d2963d0efca22da636e784a9ab5ca990fb0a6be5e`，amd64、非 root `xingtu`、CLI 正常、无 `/ms-playwright`。PostgreSQL/Redis/MinIO/Temporal 官方镜像已拉取；生产配置文件仅存服务器共享目录且为 0600，不输出密钥。
- 2026-10-19：依赖镜像拉取完成后 ControlMaster socket 意外消失。随后 `docker compose up` 在认证阶段失败，命令未执行；截至此证据点仍未创建项目 Volume/容器、未执行 Migration。等待用户重新建立 `/tmp/yumeng-ops01.sock` 后从基础服务启动继续。
- 2026-10-19：ControlMaster 恢复后完成中心服务首次部署。创建的 `xingtu-production_*` Volume 均为本项目新 Volume；启动 PostgreSQL 18.3、Temporal PostgreSQL 16.10、Redis 7.4.5、MinIO、Temporal 1.28.1、API 与更新调度器，未启动 Chrome。首次 Migration 因安装后 CLI 将项目根误判为 `.venv/lib` 而安全失败且未落表；为容器显式设置 `XINGTU_PROJECT_ROOT=/app` 后，18 个迁移全部成功，迁移版本为 18，复核 `users=0`、`root_tasks=0`。API `127.0.0.1:18000/api/health/live` 返回 200；最终 amd64 应用镜像为 `sha256:c54a4be6ee1caaa5eb5c2bb704feffa11fa2d8f466990922ae1857818dcc24a0`。
- 2026-10-19：端口绑定经 Docker inspect 复核：业务 PostgreSQL `127.0.0.1:5432`、Temporal `127.0.0.1:7233`、MinIO S3 `127.0.0.1:9000`、MinIO Console `127.0.0.1:9001`、API `127.0.0.1:18000`；Redis 无 Docker Host 端口。资源快照为主机内存已用约 1.8 GiB/3.5 GiB、可用约 1.7 GiB，Swap 已用约 750 MiB/2 GiB，磁盘 14/50GB（27%）；本项目运行容器内存合计约 625 MiB，未见 OOM 或重启，Intake 尚未启动，需继续观测峰值。
- 2026-10-19：TencentOS 不被 Tailscale 官方安装脚本识别，改用官方稳定静态包 `tailscale_1.104.1_amd64.tgz`，校验官方 SHA256 后安装。`tailscaled` 已由 systemd 启用并运行，处于 `NeedsLogin`；等待用户通过一次性网页登录把服务器节点 `yumeng-xingtu-cloud` 加入 Tailnet。Mac 尚未安装 Tailscale，跨机端口仍保持回环绑定，未提前开放。
- 2026-10-19：Intake Worker 尚未启动。原因是生产配置中的 `DEEPSEEK_API_KEY` 为空，启动逻辑会强制验证模型；本机已有受保护的 `.runtime/deepseek.env`，但将现有凭据复制到服务器属于具体凭据传输，已请求用户明确授权，在授权前不传输、不输出密钥。
- 2026-10-20：实机重启验收发现 Docker 29 对“仅连接 `internal: true` 网络”的容器保留 HostConfig 端口声明但不创建实际宿主监听。为 PostgreSQL、Temporal、MinIO 增加独立 `private-access` 网络后无删除 Volume 地重建三个容器；`127.0.0.1:5432/7233/9000/9001` 均出现真实监听，迁移版本仍为 18，API 继续健康，未发生 OOM。该地址将在 Tailscale 节点就绪后改绑服务器 Tailscale IP，仍不得绑定公网地址。
- 2026-10-20：Mac 启动脚本原先固定执行 `production-preflight`，会正确拒绝本轮明确授权的 `local_development` Wi-Fi 测试单元。新增统一 `worker-preflight`：生产单元仍强制 NetworkProof 与实时线路探测；本地单元仅返回 `test_only=true`/`not_applicable_test_only`，且 `UnitConfig` 继续拒绝代理和生产证明字段，未放宽 `production_line`。`unit-local-mac-02` 实机静态预检通过；新增回归与既有配置测试共 5 passed，相关 Ruff/format、zsh、plist、Compose 解析均通过。SSH ControlMaster 随后再次失效，服务器容器不受影响，等待恢复后继续 Tailnet、Intake 和 Nginx。
- 2026-10-20：用户完成 Mac 官方 Tailscale Standalone 客户端安装与登录。通过已安装 CLI 在宿主权限下实测 `BackendState=Running`、节点 `longbo`、`Online=true`，IPv4 为 `100.67.64.110`；沙箱内无法读取 GUI Preferences 属执行环境权限限制，不是 Tailscale 断线。服务器 ControlMaster 仍未恢复，尚不能生成新的服务器入网授权链接或改绑服务端私网端口。
- 2026-10-20：Mac Tailnet 节点列表仅有本机，服务器尚未加入。客户端最初报告 Tailnet DNS 不可达与 Screen Time 内容过滤冲突；按最小权限将 Mac 设为 `accept-dns=false`、`accept-routes=false`、`shields-up=true` 后 DNS 警告消失，但 Screen Time 警告仍在，`tailscale netcheck` 为 `UDP=false`、无公网 IPv4 观测、DERP 无响应。依官方指引需把网页内容访问设为不受限并重启 Mac，修复前不将 Connected 控制面状态当作私网数据面验收通过。
- 2026-10-20：用户重启 Mac、恢复 ControlMaster，并明确授权复制现有 DeepSeek 密钥。服务器节点 `yumeng-xingtu-cloud` 已加入同一 Tailnet，IPv4 `100.86.124.51`；Mac 为 `100.67.64.110`。服务器 UDP/公网 IPv4/DERP 正常；Mac 到服务器 `tailscale ping` 经 DERP(sfo) 成功但未建立直连，往返约 376–752ms。Mac 侧 `5432/7233/9000` TCP、Temporal gRPC `GetSystemInfo`、MinIO HTTP health、PostgreSQL 协议握手均成功，证明数据面可用；直连与 Screen Time 客户端警告仍需后续排查，不阻断当前协议验证。
- 2026-10-20：生产依赖改绑服务器 Tailscale IP，PostgreSQL `100.86.124.51:5432`、Temporal `100.86.124.51:7233`、MinIO S3 `100.86.124.51:9000`；MinIO Console 继续仅 `127.0.0.1:9001`，API 继续仅 `127.0.0.1:18000`。无删除 Volume 地重建三个服务后迁移版本仍为 18，均 healthy。双网络使 Temporal 原先只监听 data 网卡而健康检查解析到 private-access 网卡；显式 `BIND_ON_IP=0.0.0.0` 后 Temporal `WorkflowService: SERVING`，未修改 Temporal PostgreSQL。
- 2026-10-20：DeepSeek 密钥仅经 SSH stdin 写入服务器 0600 `application.env`，未输出内容；Intake Worker 启动后对 DeepSeek `/models` 返回 200 并轮询 `xingtu-intake`，Temporal taskqueue 显示新鲜 workflow poller。启用 Intake 后宿主仍约 1.8/3.5GiB 已用、1.7GiB available，Swap 约 747MiB，所有项目容器均未 OOM。数据库与 MinIO Worker 凭据复制到 Mac 仍待用户对这组具体凭据明确授权。
- 2026-10-20：用户要求先审阅 Tailnet 最小权限策略、不直接修改后台。只读复核实际监听：业务 PostgreSQL `100.86.124.51:5432`、Temporal `100.86.124.51:7233`、MinIO S3 `100.86.124.51:9000`；MinIO Console `127.0.0.1:9001`、API `127.0.0.1:18000`。OpenSSH 监听 `*:22`，当前 ControlMaster 目标仍为公网 `119.91.210.100:22`；既有 MySQL 监听 `*:3306`，在默认 Tailnet allow-all 下可从 Mac 连接。拟提交完整 Grants 仅允许 `100.67.64.110` 到 `100.86.124.51` 的 TCP 22/5432/7233/9000，并以内置 policy tests 断言 3306/6379/9001/18000 均拒绝；等待用户保存后实测，尚未修改管理后台。
- 2026-10-20：用户保存完整最小 Grants 后实测：Mac 到云端 TCP 22/5432/7233/9000 全部允许，旧 MySQL 3306、Redis 6379、MinIO Console 9001、API 18000 全部拒绝；公网 SSH ControlMaster 继续 `Master running`。用户随后明确授权数据库与 MinIO Worker 凭据复制；只选取必要字段写入 Git 忽略的 `.runtime/cloud-worker.env`（0600），不包含 DeepSeek/HMAC。PostgreSQL 鉴权查询返回迁移 18、用户 0、任务 0；Temporal gRPC 成功；MinIO 临时对象写/读/删成功且已清理。
- 2026-10-20：`unit-local-mac-02` 保持 `local_development`、无代理/NetworkProof，仅将 covers 改为云端 S3 并保留本地配置备份。注册云端后状态为 `NEEDS_LOGIN`、线路 `local-mac-02`、generation 0、无 owner、browser_stopped=true，允许三类任务；未冒充生产 READY。Mac launchd 已安装并运行，私有 env/config/plist 均 0600，Worker 轮询 `xingtu-unit-local-mac-02`。无任务条件下 `kickstart -k` 验证 PID 2947→2996、旧进程退出且单实例恢复；Temporal 看到新 poller，未打开 Chrome 或访问巨量星图。
- 2026-10-20：HYB-01 断线收敛实测：先确认新 PID 2996 poller 仅 8 秒、旧 PID 2947 已 201 秒并按 180 秒阈值排除；随后在云端 `root_tasks=0` 时卸载 launchd，PID 2996 退出且 poller 时间戳不再刷新，199 秒后被系统判定离线。按原 plist 恢复后唯一真实 Worker PID 3238 启动并出现新 poller。执行单元始终保持 `NEEDS_LOGIN/local_development/browser_stopped=true/generation=0`，未取得租约、未启动业务任务；Temporal 的 TTL 缓存条目不会被误计为多个在线 Worker。
- 2026-10-20：产品入口前置复核：生产 Origin 已配置为 `https://xingtu.yumeng.live` 且 Secure Cookie 开启，但该域名当前无 A/AAAA 记录，服务器无对应证书/站点配置；既有 `dev.yumeng.live` 属另一应用并保持不变。已在确认目标不存在后把本版本 `frontend/dist` 发布到新目录 `/www/wwwroot/xingtu.yumeng.live`（`index.html` 与两项哈希资源），尚未启用 Nginx，HTTP/HTTPS 不宣称可用。业务库仍无产品用户，需用户通过交互式密码入口创建首个账号。
- 2026-10-20：用户已创建首个生产产品用户，数据库只读复核账号 `admin`/显示名“管理员”/给定用户 ID 一致且启用，未重建账号或接触密码。API 健康正常；Intake poller 与 Mac PID 3238 collection poller 均新鲜，执行单元仍为 `NEEDS_LOGIN/local_development/browser_stopped=true/generation=0`，任务数 0。DNS 管理权限审计确认域名由阿里云托管，但本机、服务器和宝塔均无已配置的阿里云凭据，故未修改 DNS；需用户手工添加单一 A 记录或提供受限阿里云 DNS 授权后继续证书/Nginx。
- 2026-10-20：A 记录生效后安装系统仓库 Certbot 2.8.0，并建立不影响旧站点的独立 HTTP-01 临时 Nginx 站点；回环、公网及 Let’s Encrypt 到项目 Nginx 的请求均有 200 日志。CA 多视角验证同时遭腾讯云网络层 `webblock.html` 重定向，正式与 staging HTTP-01 失败，项目 Nginx 无该重定向。当前已启动标准 DNS-01 流程并等待用户添加一次性 TXT；未加载不存在的证书、未启用 443，`dev.yumeng.live` 持续 200。
- 2026-10-20：DNS-01 证书签发及独立正式 Nginx 站点启用成功，HTTP/HTTPS/SPA/API 实测通过，旧站点未受影响。证书为手工 DNS 验证，当前无自动续期 hook。Mac 浏览器默认系统代理 `127.0.0.1:7897` 会关闭新域名连接；不更改全局代理，产品验收浏览器以独立 Profile + `--no-proxy-server` 运行，执行单元 Profile 未触碰。登录后会话验收正等待用户在该窗口输入密码。
- 2026-10-20：用户授权重置既有 `admin` 密码并存入本机 Keychain 后，正式 HTTPS 真实 Chrome 登录与刷新会话保持通过；会话 Cookie 为 `Secure/HttpOnly/SameSite=Lax`，登录后用户、Worker、ExecutionUnit、任务 API 均返回 200，控制台错误和失败请求为 0。Intake 与 `xingtu-unit-local-mac-02` 各有 1 个新鲜 poller；单元仍为 `NEEDS_LOGIN/UNAVAILABLE/LOCAL_DEVELOPMENT`、浏览器租约 `IDLE`，任务数 0，未访问巨量星图或伪造生产线路。Mac launchd 复核 PID 3238 仍运行。验收末尾 `/tmp/yumeng-ops01.sock` 已不存在，因此未补采新的 `docker compose ps` 与资源快照；此前容器/资源实测证据继续有效，但不能把本次 API/poller 检查表述为新的宿主资源检查。
- 2026-10-20：公网收尾探针中，HTTPS 首页与 API health 持续为 200，`dev.yumeng.live` 仍为 200；纯 HTTP 首次请求短暂被腾讯网络层 302 到 `dnspod.qcloud.com/static/webblock.html`，数秒后重试恢复项目 Nginx 301→HTTPS。该现象与此前 HTTP-01 多视角失败一致，说明 80 端口路径存在外部间歇性拦截；不影响显式 HTTPS 访问，但不能宣称公网 HTTP 自动跳转在所有视角稳定，需后续向腾讯云核查域名接入/备案拦截。
- 2026-10-20：只读复核域名与入口拓扑（未修改 DNS、Nginx、证书或容器）：`yumeng.live` 权威 NS 为阿里云 `dns9/10.hichina.com`；`dev.yumeng.live` A 指向 `119.91.210.100`，宝塔站点创建于 2026-09-21，Nginx 仅监听 80/8080 并反代 `127.0.0.1:8000`，无 443/证书；`xingtu.yumeng.live` 权威查询为 NXDOMAIN，本机 Nginx 无站点/证书，前端已暂存 `/www/wwwroot/xingtu.yumeng.live`。公网另见 `boss/kb/bot.yumeng.live` 指向阿里云 `120.79.249.241`（Let's Encrypt 证书），`cop.yumeng.live` 指向腾讯云 `43.139.4.9`；本机与腾讯云主机无阿里云 CLI/AccessKey，宝塔 `AliyunDns` 未配置且未安装 DNS 管理插件。结论：此前自动化边界是应用/Nginx/证书，DNS 记录创建需阿里云账号侧授权；星图最少需人工新增一条 `xingtu` A 记录后才能继续 Nginx/HTTPS。
- 全仓 Ruff 仍命中 `scripts/acceptance/run_cd05/06/07_acceptance.py` 的 11 项既有 UP031 及格式问题，与部署变更无关，按用户已批准边界暂缓。腾讯云、Tailnet、Mac launchd 与产品账号环境已经分阶段实测；尚未执行 COS 真实上传/隔离恢复、移动线路、远程 F10 成功接管及真实端到端采集。
- 本卡仍不能标记完成：产品入口和 Worker 接入通过不等于备份恢复、移动线路或真实采集通过；后续证据继续按对应阶段追加。
- 开发时在本节记录实际环境、契约/Adapter/模型版本、命令、结果和脱敏证据链接；真实平台项不得用合成样本勾选。

## 交接信息

中心容器、正式 HTTPS 产品入口、Tailnet 最小权限、Mac 到三项私有依赖、Intake Worker 与 Mac Collection Worker 已完成实机接入；APP-01 已完成生产登录会话验收。下一步在恢复 SSH ControlMaster 后补采容器与资源快照，并继续 COS 隔离恢复演练；真实平台账号/Profile 会话、移动线路与最小真实采集仍需各自授权。现有 Worker 在线、产品登录和 Chrome 空白页检查不能当作真实采集验收。

本卡当前为进行中；DEP-01、DEP-02、CFG-01 与 APP-01 已完成，HYB-01 的 Worker 在线/离线识别与 MAC-01 的跨机服务化已有实机证据但仍未完成真实平台验收。未完成事项为 COS 恢复演练、移动线路 fail-closed、真实端到端采集、完整故障/发布回滚演练与上线验收；证书自动续期和 Mac 代理绕过也需运维收尾。

## 状态历史

- 2026-10-18：待办 → 进行中；启动 DEP-01、DEP-02、CFG-01、HYB-01、MAC-01 第一阶段开发与本地验证。
- 2026-10-19：进行中 → 进行中；第一阶段开发与本地验证结束，等待用户验收后才可进入腾讯云部署。
- 2026-10-19：进行中 → 进行中；用户授权阶段 A，启动腾讯云访问审计、x86_64 构建及中心服务实机部署验收。
- 2026-10-19：进行中 → 进行中；x86_64 镜像验证通过；腾讯云 SSH 公钥认证及生产密钥前置条件未满足，阶段 A 在服务器操作前安全停止。
- 2026-10-19：进行中 → 进行中；切换至用户确认的新腾讯云主机并生成项目专用 SSH 密钥，等待服务器侧授权，不使用明文密码自动化。
- 2026-10-19：进行中 → 进行中；按用户最新要求停止公钥路径；密码认证受当前工具无安全交互输入通道限制，服务器尚未登录或修改。
- 2026-10-19：进行中 → 进行中；服务器基线、隔离发布目录、生产配置、官方镜像加速与 amd64 镜像构建完成；ControlMaster 失效，暂停在首次容器启动之前。
- 2026-10-20：进行中 → 进行中；中心服务、Tailnet 私有依赖、Intake/Mac Worker 与 199 秒离线收敛已实测，等待产品入口和真实平台分阶段授权。
- 2026-10-20T20:32:00+08:00：进行中 → 进行中；正式 HTTPS、初始用户真实登录、Secure Cookie 与登录后 API/Worker 状态通过；真实采集、COS 恢复、移动线路和完整故障演练仍未验收。
- 2026-09-27T09:51:41+08:00：建立 → 待办；依据完整技术方案及代码盘点补齐一期任务规划，未改变业务范围。
