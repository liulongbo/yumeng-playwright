# MAC-01：Mac Collection Worker 服务化

状态：待验收
更新时间：2026-10-20T20:32:00+08:00
是否验收：否；Tailscale、launchd、系统 Chrome 空白页与 Worker 断线恢复已实测，真实账号会话、采集及移动线路仍待后续阶段。

## 目标与范围

提供 macOS launchd 模板、启动前检查、日志轮转与异常重启说明；使用原生 Python、Playwright、Chrome 和独立 Profile，不绕过线路校验、文件锁或执行单元互斥。

## 验收清单

- [x] plist 与启动脚本静态检查通过。
- [x] 明确要求已登录 Aqua 图形会话和 Headful Chrome。
- [x] 生产线路预检失败时 Worker 不启动，不回落家庭宽带。
- [x] 本地凭据和 Profile 不进入版本库。

## 验证证据

- 2026-10-18：开始实施；本轮禁止启动真实采集。
- 2026-10-19：`plutil -lint`、`zsh -n` 通过；模板提供 KeepAlive、Aqua session、私有文件权限检查、`production-preflight`、`caffeinate` 与 newsyslog。UnitConfig 仅含占位符，不生成 NetworkProof。
- 2026-10-20：为本轮已授权的 Wi-Fi 隔离测试增加 `worker-preflight` 并由启动脚本调用。生产单元仍执行真实 NetworkProof/probe；`local_development` 仅以 `test_only` 身份通过，携带代理会被配置模型拒绝。当前 `unit-local-mac-02` 静态预检通过，新增回归与相关配置测试共 5 passed；尚未 `launchctl bootstrap` 或连接云端。
- 2026-10-20：Mac `100.67.64.110` 与云端 `100.86.124.51` 已加入同一 Tailnet；Mac 到云端 PostgreSQL/Temporal/MinIO 三端口 TCP、Temporal gRPC、MinIO health 与 PostgreSQL 协议握手通过，公网 IP 上相同内部端口均不可达。连接当前经 DERP(sfo)，未建立直连。已生成并校验指向 `unit-local-mac-02` 与 `.runtime/cloud-worker.env` 的私有 launchd plist；数据库/MinIO 凭据尚待具体复制授权，故未加载服务。
- 2026-10-20：用户保存最小 Grants 并授权必要 Worker 凭据后，PostgreSQL 鉴权、Temporal gRPC、MinIO S3 临时对象写读删通过；凭据文件、UnitConfig 与 launchd plist 均为 0600。`unit-local-mac-02` 保持 `local_development/test_only`、无代理/NetworkProof，covers 使用云端 MinIO；云端注册状态真实为 `NEEDS_LOGIN`。launchd 实际加载成功并轮询 `xingtu-unit-local-mac-02`；无任务 `kickstart -k` 后 PID 2947→2996、旧进程退出、唯一 Worker 自动恢复。尚未打开 Chrome、验证 Profile 登录或执行真实采集。
- 2026-10-20：系统 Chrome 155.0.8059.85 + Playwright 1.63.0 使用隔离 Profile 完成 headless 空白页兼容检查，`launch_ok/page_opened/browser_stopped=true`；未导航巨量星图、未读取账号或改变单元状态。随后在云端任务数为 0 的前提下 `launchctl bootout`：PID 2996 退出，poller 最后访问固定为 `03:50:14Z`，在 `03:53:33Z` 已陈旧 199 秒并按 180 秒阈值判定离线；按原 plist 恢复后唯一真实 Worker PID 3238 启动，新 poller 出现。数据库仍为 `NEEDS_LOGIN/local_development/browser_stopped=true/generation=0`，任务数 0。
- 2026-10-20：正式产品登录后的 `/api/health/workers` 再次确认 `xingtu-unit-local-mac-02` 有 1 个新鲜 poller（age 约 37 秒）；`/api/execution-units` 同时显示 `worker_status=ONLINE`，但资源状态严格保持 `NEEDS_LOGIN/UNAVAILABLE/LOCAL_DEVELOPMENT`、浏览器 `STOPPED`、租约 `IDLE`。本机 `launchctl print` 复核 PID 3238 仍运行且无历史退出；未创建任务、未启动 Chrome 或访问巨量星图。
- 未验收：未进行真实账号当前进程会话核验、Headful 人工登录、真实采集或移动线路测试；这些步骤不得由空白页兼容检查替代。

## 状态历史

- 2026-10-18：待办 → 进行中。
- 2026-10-19：进行中 → 待验收；配置开发完成，实机服务化待后续阶段。
- 2026-10-20：待验收 → 待验收；补齐本地测试单元的模式安全预检，等待 Tailscale 和 launchd 实机验收。
- 2026-10-20：待验收 → 待验收；Tailscale、云端依赖鉴权、launchd 启动与无任务重启恢复通过；Chrome/Profile、离线 185 秒收敛及真实采集待后续授权验收。
- 2026-10-20：待验收 → 待验收；系统 Chrome/Profile 空白页启动退出和 Worker 停止 199 秒后的离线判定、launchd 恢复均通过；真实平台会话、采集与移动线路仍未验收。
