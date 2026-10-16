# MAINT-01：本机资源与同步残留排查及安全清理

状态：阻塞
更新时间：2026-10-13T14:39:07+08:00
是否验收：否；正在进行只读盘点，尚未执行删除。

## 目标与范围

定位导致 Docker 与本项目数据库无法稳定运行的本机内存、磁盘和缓存压力；识别可安全删除的其他项目依赖、构建缓存与 iCloud 中断同步残留。用户已授权直接删除其他项目的依赖；任何个人文档、照片、项目源代码、数据库数据或其他非依赖内容，在删除前必须逐项征得确认。

包含：macOS 内存／swap／磁盘检查，Docker 状态与可回收空间检查，开发工具及其他项目依赖缓存盘点，iCloud Drive 同步与缓存盘点。

不包含：删除个人文档、照片、iCloud Drive 文件、项目源代码、数据库卷或凭据；升级 macOS 或 Docker；擅自重启、重装 Docker Desktop。

## 关联与依赖

- 适用：技术方案 §17.2（Docker Compose 资源隔离与磁盘占用监控）、§17.3（数据库持久化与恢复）。
- 前置任务：无。本机维护任务，不改变产品功能卡的验收结论。
- 依赖：用户对涉及个人文件的候选项逐项授权。

## 验收清单

- [ ] 记录内存、swap、磁盘和 Docker 可用性现状，并区分当前压力与历史压力。
- [ ] 枚举大容量候选项，明确路径、体积、类别和删除授权状态。
- [ ] 清理用户已授权的其他项目依赖／可再生成缓存，并记录实际释放空间。
- [ ] 对 iCloud 中断同步残留给出证据支持的处理建议；个人文件处理前取得确认。
- [ ] 核对 Docker 与项目数据库的持久化位置和恢复风险，不删除数据库数据。
- [ ] 回写本卡、任务索引和项目总览，保留执行命令与结果。

## 实现记录

- 2026-10-13 开始只读排查；尚未删除任何内容。
- 初始主机快照：物理内存 16 GiB；`memory_pressure` 显示当前系统空闲比例 51%，无 throttled page，但历史 `Swapouts=317738`，表明此前发生过内存压力，不能据此断言当前仍为内存不足。
- 磁盘更紧急：APFS Data 卷实际占用 217.2 GB、容器仅余约 3.3 GB（1.4%）。不存在 Data 卷 APFS snapshot。Docker socket 不存在，守护进程当前未运行／不可达，故还不能取得 `docker system df` 的镜像、容器和卷统计。
- Docker Desktop 数据目录的实际已分配空间约 3.0 GB；其中 `Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw` 的逻辑容量为 228 GB，`stat`／`du` 均证明其当前实占约 3.0 GB。此前将 `%k` 错用于 `st_blocks` 的乘数，得到约 24 GB 的中间结论已撤回：POSIX `st_blocks` 单位为 512 B。Docker.raw 的逻辑容量几乎与 APFS Data 容器总量一致，可能造成 macOS 存储分类误导，但不能单独证明它占满了物理空间。该文件可能包含 PostgreSQL 等持久卷，按本卡边界不删除。
- iCloud 的 `brctl status` 观测到容器均为 `client:idle`，前台容器显示 `caught-up`，最近同步为 2026-10-13 11:29+08:00，未见仍在中断重试的同步；权限生效后实测 CloudDocs 仅约 43 MB、iCloud Drive group container 约 5.4 MB，排除其为大容量“系统数据”主因。
- 可访问的容量：用户目录统计约 11.1 GB；`/Library` 约 10.9 GB（CoreSimulator cache 约 3.0 GB、CommandLineTools 约 2.2 GB）；`/private/var` 约 7.2 GB（当前用户临时目录约 2.7 GB，其中 Chrome code-sign clone 约 2.1 GB）。可读根目录合计仍不足以解释 Data 卷的约 217 GB 占用；受 SIP／系统服务保护的 `private/var/db` 等路径仍无法用普通权限完整统计。
- 依赖候选：在 Documents / iCloud Trash 发现 14 个其他项目的 `.venv`／`node_modules` 路径，但它们本地实占均为 0 B（云端按需下载占位或空目录），删除不会释放本机空间，未作无收益删除。YUMENG 自身依赖未动。
- 已清理：Google Updater 的 `crx_cache` 下载缓存，实测 748 MB，属于可再生成更新包；删除后 Data 卷可用空间从约 2.7 GiB 增至约 3.3 GiB。尝试删除 root 所有的 `/Library/Developer/CoreSimulator/Caches`（3.0 GB、无活跃模拟器进程）被系统权限拒绝，未发生部分删除。
- Docker 直接根因：启动日志在 2026-10-13 11:20+08:00 记录 `write .../Data/log/vm/init.log: no space left on device`，随后引擎退出；不是内存 OOM。设置快照：10 CPU、8,092 MiB VM 内存、1,024 MiB swap、233,752 MiB 磁盘上限。清理 748 MB 后重试仍未出现 Docker socket。

## 验证证据

- 2026-10-13T14:14:13+08:00，本机只读：`sysctl -n hw.memsize`、`memory_pressure`、`vm_stat`、`df -h`、`diskutil apfs list`／`listSnapshots disk3s5`、`docker version`／`docker system df -v`、`du` 专项检查、`brctl status`、`lsof +L1`。Docker 命令均因 `~/.docker/run/docker.sock` 不存在失败；Data 卷无 APFS snapshot；未执行删除、重启或 iCloud 操作。
- 2026-10-13T14:19:17+08:00，用户表示已开启权限后复测 `du -sh CloudDocs / iCloudDrive group container`；两处仍为 `Operation not permitted`。本进程链为 `Cursor Helper (Plugin): extension-host` → Cursor 内 `openai.chatgpt` 扩展的 `codex` 可执行文件，故需确认开启的是 **Cursor.app** 的完全磁盘访问权限，并彻底退出后重启 Cursor 才能让新进程取得权限。
- 2026-10-13T14:39:07+08:00，Cursor 权限生效后完成用户目录、Library、CloudDocs、iCloud Drive、Docker raw／日志和删除文件占用盘点；无 APFS snapshot、无大容量 deleted-but-open 文件。已删除 `~/Library/Application Support/Google/GoogleUpdater/crx_cache`（748 MB），`df` 可用空间约 +0.6 GiB；尝试清理 root 所有的 3.0 GB CoreSimulator cache 被权限拒绝。启动 Docker Desktop 复现日志中的 `no space left on device`，守护进程未就绪；未执行 prune、reset 或任何 Docker 数据删除。

## 交接信息

- 阻塞：可无损清理的用户缓存已不足以解决问题；剩余可观候选是 root 所有的 3.0 GB CoreSimulator cache，当前工具不能取得 macOS 管理员权限。Docker 磁盘上限若通过 UI 降低，官方行为是删除现有 `Docker.raw`（本地容器、镜像及卷），包含潜在数据库数据，必须由用户明确确认后才可做。
- 下一步：用户可在本机 Terminal 执行 `sudo rm -rf /Library/Developer/CoreSimulator/Caches`（只删除已核验的无活跃模拟器缓存，预计释放约 3 GB），或明确授权 Docker Desktop 数据重置／缩小磁盘上限。空间恢复后，重新启动 Docker 并立即执行只读 `docker system df -v`、`docker volume ls`，核对数据库持久卷。任何文档、照片、数据库数据或 iCloud 文件仍逐项确认。
- 风险：磁盘余量极低；需要先验证数据库／Docker 持久卷位置，避免将业务数据误当缓存。

## 状态历史

- 2026-10-13T00:00:00+08:00：待办 → 进行中；用户授权排查并允许删除其他项目依赖。
- 2026-10-13T14:16:01+08:00：进行中 → 阻塞；关键的 CloudDocs／iCloud Drive 与其他受保护目录无法读取，需用户授予运行 Codex 的宿主「完全磁盘访问权限」后才能安全量化和处理“系统数据”大户。
- 2026-10-13T14:19:17+08:00：阻塞 → 进行中；Cursor 的完全磁盘访问权限生效，CloudDocs／iCloud Drive 缓存可读。
- 2026-10-13T14:39:07+08:00：进行中 → 阻塞；Docker 确认因 Data 卷空间耗尽退出；剩余无损大容量候选为 root 所有的 CoreSimulator cache，需管理员权限，缩小 Docker 磁盘上限则需要对现有容器／卷数据作破坏性确认。
