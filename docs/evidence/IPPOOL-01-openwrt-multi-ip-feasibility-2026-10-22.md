# 巨量星图项目——OpenWrt 多 IP 池建设与接入可行性评估报告

- 评估日期：2026-10-22
- 评估人：DSH（技术负责人视角）
- 评估范围：项目真实代码、现有执行单元架构、本机网络环境、OpenWrt/代理技术资料、官方包索引、Playwright 代理行为实测
- 本轮边界：**只调研、只读检查、技术可行性分析、方案比较与实施规划；未修改项目代码、网络配置、执行单元配置，未安装依赖，未发起任何真实巨量星图采集**
- 关联任务卡：[IPPOOL-01](../tasks/IPPOOL-01.md)
- 结论标签：**技术方向可行；参考方案的具体实现不可直接照搬；多出口并发受“独立星图账号数量”硬约束；性能与设备兼容性尚未实测**

---

## 0. 执行摘要（给产品经理）

### 0.1 一句话结论

**可以做，但它不是一个“买 5 张 SIM 卡就能把采集速度提高 5 倍”的项目。** 当前系统已经支持“一个账号走一条指定线路”的生产线路模式；真正缺的是“多个独立账号 + 多个执行单元 + 多出口调度”的运维与少量调度代码。最大的限制不是 OpenWrt，而是**独立星图账号数量**和**蜂窝出口的公网 IP 是否真的独立**。

### 0.2 五个关键判断

1. **一个执行单元只能绑定一个账号、一条线路/代理、一个持久 profile，并发为 1。** 这是当前代码和数据库的硬约束，不是建议值。  
   因此：**要让 N 个蜂窝出口同时服务采集，至少需要 N 个执行单元，并且需要 N 个独立星图账号**。只增加 SIM 卡、代理端口或执行单元数量，都不能绕过账号约束。
2. **“新增一个 IP 出口”不等于“新增一个执行单元”，但在当前架构下，新增一个可并发使用的出口必须新增一个执行单元（以及对应账号/profile）。** 出口是线路资源，执行单元是“账号 + 线路 + profile”的消费绑定；两者不是同一个东西，但当前实现只允许通过执行单元来消费线路。
3. **参考方案的 3proxy 具体写法不能照抄。** 3proxy 的 `external` 参数是**IP 地址**，不是接口名；`external wwanX` 不是标准 3proxy 语法。按接口绑定在较新版本的 3proxy 中是 `-De <iface>`，按 netns 是 `-ne <path>`；而且我们查到的 OpenWrt 24.10.0 x86_64 官方包索引中**没有 3proxy**，需要自行编译或第三方 feed。  
   我们推荐替代方案：**OpenWrt 网络命名空间（netns）+ 官方 tinyproxy（HTTP 代理，BasicAuth）+ 每个 netns 独立 dnsmasq + veth 接入局域网，每个出口一个固定局域网 IP:6001**。
4. **Playwright/Chrome 的代理认证有明确边界：HTTP 代理可用用户名/密码；SOCKS5 不能带认证。** 本轮实测：HTTP 代理在 407 挑战后会发送 `Proxy-Authorization: Basic ...`；配置 SOCKS5 用户名/密码时，浏览器直接以 `Browser does not support socks5 proxy authentication` 启动失败。因此生产代理应选 **HTTP 代理**，不要选“需要认证的 SOCKS5”。
5. **当前项目已经具备“失败关闭”的浏览器行为。** 本轮用死代理实测：HTTP/SOCKS5 死代理都会得到 `ERR_PROXY_CONNECTION_FAILED`，不会回退到本机宽带。真正需要补的是：**浏览器代理之外的健康探针、DNS 绑定验证、公网 IP 可观测性、多单元调度**。

### 0.3 推荐路径

**先做单出口，再做多出口；先验证账号，再谈扩容。**

> **2026-10-22 用户决策：** 3 个独立星图账号已确认；当前目标为 **3 个出口/3 个单元**（不是 5–10）；优先级 **P0 吞吐 > P1 独立 IP > P2 冗余**；真实采集暂不授权；J1900 访问与 SIM 尚未就绪；代理仅本机/另一台电脑使用；接受“单出口 ≤1.5×、3 出口 ≥1.8×”门槛。详见 §11。

- **Phase 0（决策/基线）**：确认独立星图账号数量、J1900 实机信息、SIM 运营商与流量套餐、真实采集测试授权；建立干净的本机基线。
- **Phase 1（单 SIM + 单代理 + 单执行单元）**：新开一个 `production_line` 执行单元，绑定一个新账号和新 profile，通过 OpenWrt 单出口代理登录并跑小样本；验证独立 IP、DNS 绑定、断线失败关闭、性能。
- **Phase 2（多 SIM + 多代理）**：在 OpenWrt 上用 netns 做 3 个出口，确认 3 个不同的公网 IP、互不影响、单条断线不影响其他出口。
- **Phase 3（单执行单元接入）**：用实际产品流程（P1 + P2）跑一个小任务，确认任务状态、数据、代理映射都正确。
- **Phase 4（多执行单元/多任务）**：只有在前三步 PASS 且**至少 2 个独立账号**时，才做 `promote_intake` 的单元池选择 + 多 Worker 启动器，验证并发不串线、吞吐有实际收益。用户已确认 3 个账号，账号条件满足；仍需 Phase 1–3 PASS。
- **Phase 5（扩容到 5–10）**：按实测结果决定，不预设 10 个出口都能在一台 J1900 + 一台 Mac 上稳定运行；当前不启动 5–10。

### 0.4 预计使用效果（估算/目标，不是承诺）

| 账号/出口配置 | 可并发任务上限 | 预计吞吐（相对当前单单元） | 关键前提 |
|---|---:|---|---|
| 1 个账号 + 1 条出口 | 1 | 约 1×（可能因蜂窝变慢） | 单出口性能达标 |
| 3 个账号 + 3 条出口 | 3 | 目标 1.8–2.2×；低于 1.8× 不建议扩 | 3 个独立公网 IP；调度改动；Mac/J1900 资源足够 |
| 5 个账号 + 5 条出口 | 5 | 估算 2.5–3.5×，需实测 | 供电/USB/散热/平台限流/数据套餐；不保证线性 |
| 5 张 SIM + 1 个账号 | 1 | 约 1×，无并发收益 | 只能作为单出口备用；当前不支持自动切换 |

> 这些数字是从当前单单元基线（20–30 有效达人/小时）和“每单元并发 1”推导的量级，不是实测承诺。若平台按账号/主体限流，增加出口可能完全不提升总吞吐。

### 0.5 现在不能下的结论

以下事项**没有实测证据**，本报告不会把它们写成“已通过”：

- J1900 的实际 OpenWrt 版本、内核、内存、USB 控制器、USB 供电能力；
- 中兴 MF79U 在 OpenWrt 下能否稳定识别、拨号、并发多台；
- 3 张 SIM（当前 3 账号）是否能拿到 3 个**不同的公网 IP**（运营商 CGNAT、动态 IP、同池复用都可能让多张卡共用一个公网 IP）；
- 蜂窝线路上的页面加载、单达人采集耗时、超时/重试、每小时成功采集数；
- 多出口并发时平台是否限流、是否增加验证码/挑战；
- 3 个账号的登录/并发是否可用、是否符合平台与运营商条款；
- 多执行单元调度改动后的真实吞吐。

这些必须在 Phase 0–3 用实机与可控小样本验证。

---

## 1. 调查方法与证据分级

### 1.1 本轮做了什么

| 类别 | 实际动作 |
|---|---|
| 项目代码 | 阅读 `runtime.py`、`worker.py`、`browser_host.py`、`repository.py`、`product_repository.py`、`intake_worker.py`、`adapter.py`、`covers.py`、`challenge.py`、迁移与 CLI；核对执行单元、代理、租约、调度、会话、封面下载路径 |
| 项目文档 | 阅读技术方案 F11、任务中心架构、DEC-006、DEC-009、UNIT-01/OPS-01 卡片与现有证据 |
| 数据基线 | 对本地 PostgreSQL 做只读查询（任务终态、目标数、有效数、墙钟时间、封面对象体积），未写入 |
| 本机网络 | `route`/`ifconfig`/`arp`/`scutil`/`ping`/`curl` 只读探测；对比直连与系统代理出口；记录当前 LAN、DNS、公网出口区域与延迟 |
| Playwright 代理 | 用项目 `.venv` 的 Playwright 1.63.0 + 系统 Chrome 156，临时 profile（`/tmp`），访问中立页面 `https://myip.ipip.net`；测试 HTTP 代理、SOCKS5、死代理、407 认证、SOCKS5 认证 |
| 官方资料 | 3proxy 官方手册与安全建议、tinyproxy 1.11.1 官方 man page、Playwright 网络文档、OpenWrt 24.10.0 x86_64 官方 Packages 索引、hev-socks5-server/microsocks README、OpenWrt issue #23637 |
| 未做 | 未登录/未访问 J1900；未安装任何 OpenWrt 包；未改任何项目配置/代码；未发起真实星图采集；未采购 |

### 1.2 证据分级

| 级别 | 含义 | 本报告中的例子 |
|---|---|---|
| **A：命令/设备实测** | 在本机实际执行并取得输出 | 本机 LAN/DNS/公网区域、DB 任务基线、Playwright 代理行为 |
| **B：代码/官方文档可确认** | 代码路径、Schema、官方手册、官方包索引 | 执行单元模型、并发 1、账号唯一、代理注入点、3proxy/tinyproxy 文档、Playwright SOCKS5 认证限制 |
| **C：推断/需实测** | 基于架构或通用行为的判断，未在目标设备验证 | MF79U 模式、J1900 多 USB 供电、蜂窝性能、运营商 CGNAT |
| **D：不可访问/未验证** | 没有权限或没有授权 | J1900 实机、SIM 独立公网 IP、3 账号登录/并发、真实蜂窝采集 |

### 1.3 环境事实

| 项 | 实测值 |
|---|---|
| 本机 | Apple M4，10 核，16 GB 内存，根盘可用约 103 GB（2026-10-22 23:46） |
| 本机 LAN | `192.168.3.132/24`，默认网关 `192.168.3.1`，Wi-Fi `en0` |
| DNS | `223.5.5.5`，到 DNS 的 3 次 ping 平均 28.3 ms，0% 丢包 |
| 到网关 | 3 次 ping 平均 4.7 ms，0% 丢包 |
| 公网出口 | IPv4 为中国移动湖南长沙；IPv6 存在（`curl -6` 到 IP 回显站点曾连接重置，Cloudflare 可返回 IPv6） |
| 系统代理 | macOS 系统代理 `127.0.0.1:7897`（HTTP/HTTPS/SOCKS 均启用） |
| 直连 vs 系统代理 | 实测出口 IPv4 与地区相同；但系统代理仍是性能对比的混杂变量 |
| 项目数据库 | 本地 PostgreSQL；当前只有 `unit-local-mac-02` 一个执行单元，`local_development`，`READY` |
| 当前运行单元 | 绑定一个星图账号、一个本地 profile；`network_mode=local_development`，禁止配置代理 |
| J1900 | **未访问**；无 IP/SSH/console 凭据；本报告不假设其版本、内存、USB 能力 |

> **重要基线说明**：当前 `local_development` 单元不设置 Playwright 代理，Chrome 默认会使用 macOS 系统代理；系统代理的规则可能随本机 Clash/代理软件变化。因此历史采集数据不是“纯直连宽带”的受控基线。Phase 0 必须先固定这一变量（关闭系统代理，或用显式代理做基线），否则蜂窝与宽带的对比不成立。

---

## 2. 当前项目架构调查结果

### 2.1 ExecutionUnit：当前的真实对象与边界

**代码结论：一个执行单元 = 一个星图账号 + 一条线路/代理端点 + 一个独立持久 profile，并发为 1。**

证据：

| 事实 | 代码/文档证据 |
|---|---|
| 单元配置包含 `unit_id`、`account_ref`、`expected_account_id`、`line_id`、`profile_directory`、`network_mode` | `backend/src/xingtu/runtime.py:47-128`（`UnitConfig`） |
| `production_line` 必须配置 `proxy_server`、`network_evidence_path`、`network_probe_command` | `runtime.py:104-113`；`ensure_line` 在 `runtime.py:173-217` |
| `local_development` 明确禁止代理、线路证明与探针，避免本地单元被伪装成生产线路 | `runtime.py:113-120`；DEC-006 |
| 浏览器通过 `launch_persistent_context(proxy=proxy)` 在启动时绑定代理 | `runtime.py:427-520`，尤其是 `:443-460`、`:473-479` |
| 代理用户名/密码只通过环境变量引用，不写入配置/日志 | `runtime.py:447-459` |
| profile 使用项目私有目录、`0700`、`flock` 独占，禁止多进程同时打开 | `runtime.py:430-442`；`browser_host.py:114-168` |
| 每单元一个 Temporal 队列 `xingtu-<unit_id>`，`max_concurrent_activities=1` | `backend/src/xingtu/worker.py:668-691`；`docs/任务中心架构.md:162-166` |
| 单元独占租约、单调递增 generation、心跳续租、旧代次拒绝 | `repository.py:570-648`；`browser_host.py:114-168` |
| 数据库 `account_ref` 全局唯一；生产线路 `line_ref` 部分唯一 | `migrations/001_initial.sql:2-3`；`migrations/004_local_line_sharing.sql` |
| `network_mode` 入库且不可变；本地单元不能通过改配置变成生产单元 | `migrations/002_unit_network_mode.sql`；`docs/development.md` 第 4 节 |

**这意味着什么：**

- 当前一个单元在任一时刻只能服务一个浏览器任务；这是**有意设计**，不是性能缺陷。它保证同一账号/profile 不会被两个进程同时使用。
- 不能把一个单元“改成多代理”或“每个任务换一个代理”而不破坏账号、会话与 profile 的一致性。当前代码没有、也不建议有这种热切换。
- 要并发使用 N 条蜂窝线路，必须创建 N 个单元；而每个单元需要独立账号（`account_ref` 唯一）和独立 profile。

### 2.2 多个执行单元能不能同时运行？

**能，但当前产品调度不会平均分配正常采集任务。**

证据：

| 事实 | 代码/文档证据 |
|---|---|
| 每个单元有独立 Temporal 队列，可以同时启动多个 `xingtu worker --config <unit>.json` 进程 | `worker.py:668-691`；`Makefile` 的 `collection-worker` 目标 |
| 数据库/租约/队列支持多单元；没有“只能有一个单元”的硬限制 | `execution_units`、`task_dispatches`、`xingtu-<unit>` |
| 正常采集（`collection`）在 P1 晋级时被直接写到 **Intake Worker 配置的那个单元**；只有该单元不具备 `collection` 能力时，才回退到“第一个可用单元” | `backend/src/xingtu/product_repository.py:473-519`；`intake_worker.py:81-84` |
| `Repository.select_execution_unit()` 存在，但**未被产物晋级路径调用**；注释明确“no load balancing in MVP” | `repository.py:433-442`；全仓检索只在该文件出现 |
| 更新任务（手动/定时）在 `unit_id IS NULL` 时由各单元通过 `claim_unassigned_update` 争抢，具备池化行为 | `repository.py:500-543`；`worker.py:687` |
| `root_tasks.unit_id` 从迁移 008 起可为空，但正常采集仍在晋级时写死单元 | `migrations/008_m3_product_app.sql:5`；`product_repository.py:574-583` |

**结论：**

- 多单元“进程级”可以跑，但**正常采集不会自动分给多个单元**；所有新采集仍会堆到 Intake Worker 配置的那个单元。
- 如果要让 3–5 个单元并行承接正常采集，必须做一处最小调度改动：在 `promote_intake` 里按池选择单元（过滤能力、状态、租约/负载），而不是固定使用传入的 `unit_id`。
- 更新任务已经有池化认领逻辑，可以作为参考，但不能直接复用到正常采集，因为正常采集的 `unit_id` 在插入时非空，且 `task_dispatches` 依赖 root 的 `unit_id` 来匹配队列。

### 2.3 Playwright / Chrome 的代理能力与边界

**代码结论：代理在 BrowserContext 启动时注入，覆盖该上下文的所有浏览器请求（HTTP/HTTPS/WebSocket/Service Worker），并带有防直连参数。**

证据：

| 事实 | 代码/文档证据 |
|---|---|
| `playwright.chromium.launch_persistent_context(..., proxy=proxy, ...)` | `runtime.py:473-479` |
| 代理为 `http://` 或 `socks5://` 由 `proxy_server` 决定；用户名/密码分别来自 `proxy_username_env`/`proxy_password_env` | `runtime.py:443-460` |
| 启动参数包含 `--disable-quic`、`--force-webrtc-ip-handling-policy=disable_non_proxied_udp` | `runtime.py:257-266` |
| 封面下载通过当前页面的 `fetch`/图片请求完成，复用浏览器会话与线路 | `adapter.py:2136` 起；`covers.py` 文件头注释 |
| P1 模型调用使用 `httpx`，不访问星图；它不是采集线路流量 | `intake.py:9`、`:97-115` |
| `ensure_line` 只校验线路证明文件和外部探针；探针是独立子进程，不是浏览器内的出口校验 | `runtime.py:173-217` |

**本轮实测（Playwright 1.63.0 + Chrome 156.0.8078.47，临时 profile，中立页面）：**

| 场景 | 结果 | 说明 |
|---|---|---|
| 不配置代理 | 页面加载成功 | 可能走 macOS 系统代理，不能当作纯直连 |
| HTTP 代理 `127.0.0.1:7897` | 页面加载成功 | HTTP 代理可用于浏览器 |
| SOCKS5 代理 `127.0.0.1:7897`（无认证） | 页面加载成功 | 无认证 SOCKS5 可用 |
| HTTP 死代理 `127.0.0.1:9` | `net::ERR_PROXY_CONNECTION_FAILED` | **失败关闭，没有回退直连** |
| SOCKS5 死代理 `127.0.0.1:9` | `net::ERR_PROXY_CONNECTION_FAILED` | 同上 |
| HTTP 代理 + 用户名/密码，收到 407 后 | 观察到 `Proxy-Authorization: Basic ...` | **HTTP 代理认证可用** |
| SOCKS5 + 用户名/密码 | 启动失败：`Browser does not support socks5 proxy authentication` | **SOCKS5 认证不可用** |

**重要技术结论：**

- **生产代理必须选 HTTP/HTTPS 代理。** 需要使用认证时，SOCKS5 不能作为 Playwright 的认证代理；如果坚持 SOCKS5，只能“无认证 + 防火墙源限制”，不满足“必须认证”的安全要求，或者额外加 HTTP→SOCKS5 桥（多一个组件，不推荐）。
- Chrome 在代理模式下会发出若干后台请求（本轮观察到 `clients2.google.com`、`www.gstatic.com`、`update.googleapis.com` 等），这些请求也会走代理。它们不访问星图，但会消耗蜂窝流量；可选加 `--disable-component-update`、`--disable-background-networking` 等参数，但必须先做回归，不能影响平台会话/Service Worker。
- 代理死掉时浏览器失败关闭，这是“不自动回落普通宽带”的关键证据。但**探针进程本身**如果配置错误（例如 `curl` 用了本机默认路由），仍可能给出“健康”的假象；探针必须显式使用代理并禁用环境代理。
- 代码中的 `NetworkProof.dns_bound`、`disconnect_blocks_direct`、`worker_egress_enforced` 目前是**人工证明字段**，不是代码自动验证的运行时事实；生产前必须用实际 DNS/断线测试生成证据，不能只写 `true`。

**采集链路是否存在“浏览器流量之外”的星图请求？**

- **主采集链路没有。** 搜索、达人主页、精选作品、封面下载都由当前 BrowserContext 发起；封面通过页面 `fetch`/图片请求完成（`adapter.py:2136` 起），因此都走同一个代理和同一条线路。
- **P1 模型调用是 `httpx` 直连，但它访问的是 DeepSeek，不是星图**（`intake.py:9`、`:97-115`）；不需要、也不应该为它配置蜂窝代理。
- **产品 API、数据库、Temporal、MinIO 都是本地/私有流量**，不访问星图；不需要走蜂窝。
- **浏览器内的协议覆盖：** HTTPS 由 HTTP 代理的 `CONNECT` 隧道承载；WSS/WebSocket 同样走 `CONNECT`；QUIC 已由 `--disable-quic` 关闭；WebRTC 的非代理 UDP 已由 `--force-webrtc-ip-handling-policy=disable_non_proxied_udp` 关闭；Chrome 的后台请求（本轮实测）也走代理。目标域名的 DNS 由 HTTP 代理在 OpenWrt 侧解析，因此必须用 netns 的 dnsmasq 保证 DNS 走蜂窝。
- **回退风险：** 浏览器层已实测失败关闭；但“探针进程”和“OS 级强制”不是同一件事。当前代码没有 OS 级 egress 强制，`worker_egress_enforced` 是人工证明；如果要求“即使 Chrome 有 bug 也不能直连”，需要把 Worker 放进 netns/容器并只保留代理出口，这属于后续加固，不是 MVP 必需。

### 2.4 任务调度、会话与代理的映射

当前正常采集链路：

```text
前端提交
  → P1 Intake Worker（固定 unit_config）
  → promote_intake：root_tasks.unit_id = 该固定单元
  → task_dispatches（sent=false）
  → 该单元的 Collection Worker 每 2s 扫描并启动 CollectionWorkflow
  → Activities.collect：max_concurrent_activities=1
  → BrowserHost 获取该单元租约 + profile 锁
  → BrowserRuntime 用该单元配置的 proxy_server 启动 Chrome
  → Engine/Adapter 采集
```

| 问题 | 当前答案 |
|---|---|
| 一个任务如何选择执行单元？ | 正常采集：P1 晋级时固定到 Intake Worker 配置的单元；更新任务：池化认领。没有负载均衡。 |
| 能否为任务指定 IP 出口？ | 只能通过“选择哪个单元”间接指定；任务本身没有出口字段。 |
| 多个任务是否共用浏览器登录状态？ | 同一单元内串行复用同一持久 profile；不同单元各自独立 profile；不共享。 |
| 不同任务/上下文是否复用会话？ | 同一单元是同一 profile 的连续任务；不同单元不共享 Cookie/Profile。 |
| 同一账号绑定不同出口会怎样？ | 当前数据库不允许同一 `account_ref` 出现在两个单元；即使强行绕过，两个并发会话很可能互相踢下线，平台风控风险高。**不要这样做。** |
| 并发时 Cookie/Profile 是否互相干扰？ | 当前架构用独立 profile + 进程锁 + 单元租约避免；同一单元并发 1，不同单元不共享目录。 |
| 代理切换是否安全？ | 当前不支持单元内热切换；切换线路应新建单元/新 profile/重新登录，不能复用已登录 profile 直接换 IP。 |

### 2.5 能力矩阵（当前项目）

| 能力 | 状态 | 证据 | 缺口 |
|---|---|---|---|
| 执行单元对象与绑定 | 已实现 | `UnitConfig`、`execution_units` | 无 |
| 每单元并发 1 | 已实现 | `worker.py:675-681`；`host_lock` | 无 |
| 多单元进程并存 | 架构支持，运维未封装 | 每单元队列 | 无多 Worker 启动器、无健康编排 |
| 正常采集池化调度 | **未实现** | `promote_intake` 固定单元；`select_execution_unit` 未使用 | 必须补池选择 |
| 更新任务池化认领 | 已实现 | `claim_unassigned_update` | 仅更新任务 |
| 生产线路代理 | 已实现 | `ensure_line` + `BrowserRuntime` | 需要证明文件/探针/新单元 |
| 代理认证 | HTTP 可用 | 本轮实测 | SOCKS5 认证不可用 |
| 失败关闭（浏览器） | 已实现 | 本轮死代理实测 | 探针/OS 级仍非强制 |
| DNS 绑定 | 只有人工证明字段 | `NetworkProof.dns_bound` | 无自动 DNS 泄漏测试 |
| 公网 IP 可观测 | **未实现** | `NetworkProbe` 只有 line_id/healthy/egress_enforced/observed_at | 无 observed_ip；需外部探针/清单 |
| 线路健康与单出口隔离 | 部分 | `ensure_line` + 单元状态 | 无独立线路健康表/看板 |
| 线路故障自动换线 | **不做（有意）** | 技术方案 §12 | 任务会等待/需人工处理 |
| 同账号跨单元 | **禁止** | `account_ref UNIQUE` | 正确，不应放宽 |
| profile/会话隔离 | 已实现 | 独立 profile、锁、快照 | 无 |
| 封面下载走线路 | 已实现 | `adapter.fetch_cover` | 无 |
| 前端执行单元列表 | 已实现 | `ExecutionUnitView`/API | 无池管理 UI，非必需 |

### 2.6 对核心问题的直接回答

#### 问题 1：新增一个 IP 出口，是否就应该新增一个 ExecutionUnit？

**不是概念上“一个 IP = 一个单元”，而是当前架构下“一个可并发消费的出口必须由一个单元来承载”。**

- 出口是**线路资源**；执行单元是**账号 + 线路 + profile 的绑定**。
- 当前一个单元只能配置一个 `proxy_server`，只能打开一个持久 profile，并发为 1；没有“一个单元管理多个出口”的能力。
- 所以：
  - 如果只是**备用/手动替换**：可以不新增单元，但当前代码不能热切换线路；实际仍要重建单元/重新登录；
  - 如果要**同时使用 N 个出口**：需要 N 个单元，并且需要 N 个独立账号；
  - 如果只有 1 个账号：**只能有 1 个生产单元**；额外 SIM 不能提升并发，最多作为备用（而备用切换在当前代码里也不是自动的）。

#### 问题 2：能否不新增执行单元，仅新增代理出口？

- **不能获得并发收益。** 新增代理出口但没有新单元/新账号，只会多出一些无法被当前调度使用的代理端点。
- 当前正常采集固定在一个单元；即使手工把端口加进 OpenWrt，项目也不会自动使用。
- 如果只是想给现有单元换一条线路：当前 `network_mode`/线路绑定不可变，且 profile 已经绑定账号；安全做法是新建单元/新 profile/重新登录，而不是改现有单元。

#### 问题 3：多个 IP 能否真正提升可同时运行的采集任务数量？

- **只有在“多个独立账号 + 多个单元 + 调度改动”同时满足时，才能。**
- 理论上限 = 单元数（每个单元并发 1）；实际受平台每账号限流、Mac CPU/内存、OpenWrt 代理/USB、蜂窝质量、数据套餐限制。
- 当前单账号时，多 IP 对并发任务数**没有帮助**。

#### 问题 4：当前执行单元并发能力是否会限制 IP 池价值？

- **会，而且是第一限制。** 一个单元一次只能跑一个任务；15 秒/达人的节奏、90 秒操作超时、页面/模块加载与重试进一步限制单单元吞吐。
- 增加 IP 但不增加单元，等于给一辆车修了五个加油站，但车一次只能在一个站加油。

#### 问题 5：是否需要新增代理池管理模块？

- **MVP 不需要。** 现有“每单元一个代理”的绑定已经足够；只需要：
  1. 多份单元配置；
  2. 一个单元池选择 SQL（最小改动）；
  3. 一个多 Worker 启动器；
  4. 一个线路健康/公网 IP 探针（运维脚本，不是业务模块）。
- 不建议做“动态代理池/轮换服务”：它会绕过现有的线路/账号/profile 绑定，增加串线和风控风险，也违背 DEC-009 的“不轮换代理”原则。

#### 问题 6：如果需要改代码，最小改动涉及哪些文件和组件？

| 优先级 | 文件/组件 | 改动目的 |
|---|---|---|
| 必须（多单元时） | `backend/src/xingtu/product_repository.py` 的 `promote_intake` | 从“固定 Intake 单元”改为“按池选择”：过滤 `network_mode='production_line'`、`allowed_task_kinds`、非 `QUARANTINED`/`NEEDS_LOGIN`/`ACCOUNT_MISMATCH`、未过期租约，按当前排队/运行任务数最少选择 |
| 必须（多单元时） | `backend/tests/integration/`（新增或扩展） | 覆盖多单元选择、排除不健康单元、无可用单元报 `NO_COLLECTION_UNIT`、并发分配不重复 |
| 必须（运维） | `scripts/` 或 `Makefile` | 一键启动 N 个 `xingtu worker --config <unit>`，每个独立日志/PID；加载每单元代理凭据环境文件 |
| 必须（网络） | OpenWrt 配置/脚本（不在本仓库） | netns、veth、tinyproxy、dnsmasq、hotplug、防火墙/ACL、健康检查 |
| 必须（接入） | 新单元 JSON + `NetworkProof` + `network_probe_command` | 每个生产单元一个账号、一条线路、一个 profile、一个代理；不修改现有本地单元 |
| 可选 | `runtime.py`/`product_models.py` | 给 `NetworkProbe` 增加 `observed_ip`/地址族，或增加线路健康表；便于原生可观测性 |
| 可选 | `worker.py`/CLI | 增加“排队任务改派”管理命令；线路故障时人工把任务移到其他单元 |
| 不需要 | `engine.py`、`adapter.py`、`covers.py`、`workflow.py`、`browser_host.py` 的租约逻辑、前端任务中心 | 当前代理/会话/采集逻辑已足够；不要为了多 IP 重构采集主链路 |

#### 问题 7：如何确保不同账号/浏览器会话不会因代理切换而状态混乱？

**硬规则：**

1. **一个账号只出现在一个执行单元**；不放宽 `account_ref UNIQUE`。
2. **一个单元只配置一个代理、一个 profile**；不在运行中切换。
3. **新线路 = 新单元 + 新 profile + 重新登录**；不复用已登录 profile 直接换 IP。
4. **同一单元同一时间只允许一个 Worker/一个浏览器**；继续使用现有租约、generation、profile `flock`。
5. **不共享 Chrome 日常 profile**；继续使用项目私有目录。
6. **线路故障时不自动切到其他账号/线路**；任务等待或人工处理，保持失败关闭。
7. **维护/登录按单元进行**；F10 的维护入口不跨单元。

---

## 3. OpenWrt 网络可行性分析

### 3.1 参考方案逐项核验

| 参考方案的说法 | 判定 | 依据与修正 |
|---|---|---|
| OpenWrt 识别多个 USB 蜂窝设备 | **条件成立，需实测** | 取决于设备呈现为 RNDIS/CDC/NCM/QMI/MBIM 中的哪一种；MF79U 未实测 |
| 通过 RNDIS 建立独立网络接口 | **可能，但不能假设** | 有些设备是 RNDIS，有些是 CDC-ECM/NCM、QMI、MBIM，甚至先以 CD-ROM 出现；必须看 `lsusb`/`dmesg`/`ip link` |
| 多个 USB 设备可同时拨号/出网 | **未验证** | 受供电、USB 总线、驱动、运营商、设备 NAT 影响；必须逐台加 |
| 3proxy 暴露 6001/6002/6003 | **技术上可以，但本环境不推荐直接采用** | 3proxy 是通用代理，能开多端口；但 OpenWrt 官方 24.10 x86_64 包索引中没有 3proxy，需要编译/第三方 feed；且认证/绑定细节要按版本核对 |
| `external wwanX` 绑定接口 | **写法错误** | 3proxy 的 `external <ipaddr>` 是外部 IP；按接口绑定是 `-De <iface>`（较新手册），按 netns 是 `-ne <path>`。老版本可能没有这些选项 |
| 用接口绑定/策略路由实现端口→出口 | **可行但脆弱** | 源 IP/接口策略路由在“多台设备同网段/同网关/IP 变化”时容易串线；netns 更稳 |
| 防火墙限制代理来源 | **应做** | 但 veth 桥接到 LAN 时，OpenWrt 三层防火墙未必能过滤桥内流量；tinyproxy 的 `Allow` + BasicAuth 是应用层控制，必要时加独立 VLAN/网桥 |
| 日志与健康检查 | **应做** | 项目侧有 `ensure_line`，但没有公网 IP/线路健康表；需要外部探针/清单 |
| `192.168.1.1:6001` | **不适用于当前 LAN** | 当前 Mac 在 `192.168.3.0/24`，网关 `192.168.3.1`；且很多随身 WiFi 默认就是 `192.168.1.1`，照抄会冲突。必须按实际 LAN 规划 |
| 3–5 个出口 | **条件成立** | 取决于账号数、独立公网 IP、性能、供电/散热；不能只看端口数 |

### 3.2 3proxy 的具体问题（为什么不能照抄）

3proxy 官方 `3proxy.cfg(5)` 手册（当前版本）明确：

- `external <ipaddr>`：设置所有出站连接的源 IP；**参数是 IP，不是接口名**。
- `-e`：单个服务的 external 地址；`-De <iface>`：按 `SO_BINDTODEVICE` 绑定外部接口；`-ne <path>`：为出站连接切换 netns。
- 这些 `-De`/`-ne` 是较新的能力；**不能假设 OpenWrt 旧包/旧版本支持**。
- 3proxy 需要正确的 ACL、认证、`nserver`、`nscache`；安全建议明确要求“总是指定 internal/external、限制来源、配置文件仅服务账号可读”。

同时，官方 OpenWrt 24.10.0 x86_64 `Packages` 索引中**没有 `Package: 3proxy`**（2026-10-22 抓取）。这意味着：

- `opkg install 3proxy` 很可能失败；
- 要么自行交叉编译（需要 SDK、版本锁定、后续升级维护），要么用第三方 feed（供应链/兼容性风险）；
- 参考方案的“3proxy + `external wwanX`”不能作为已证实可执行的配置。

**因此：本报告不推荐把 3proxy 作为首选。** 如果坚持 3proxy，必须先完成：实际固件包可用性、版本、`-De`/`-ne` 支持、认证、DNS、断线测试，再锁定版本。

### 3.3 设备与驱动：MF79U 的不确定性

公开资料中，ZTE MF79U 多为 4G USB 随身 WiFi/调制解调器，常见形态是“USB 网卡 + 内置 WiFi AP + Web 管理页”。但没有找到权威的 OpenWrt 兼容性声明。必须实测：

- `lsusb` 的 VID:PID；
- 插入后是否先出现 CD-ROM/存储设备，需要 `usb_modeswitch`；
- 是否出现 `usb0`/`eth1` 等网络接口，还是 `wwan0` + QMI/MBIM；
- 接口的 MAC 地址是否与其他同型号设备相同；
- 设备内部 DHCP 网段/网关（常见 `192.168.0.1`、`192.168.1.1`）；
- 是否可关闭内置 WiFi AP、是否可改 LAN 网段、是否可禁用 PIN；
- 同时插多台时，`dmesg` 是否出现枚举失败、掉线、over-current；
- 实际 APN、SIM 状态、信号强度（RSRP/SINR）、IPv4/IPv6。

**结论：MF79U 是“候选设备”，不是“已验证设备”。** 在 Phase 1 单台通过前，不应按 3–5 台批量采购。

### 3.4 为什么推荐 netns，而不是“3proxy + 策略路由”

多台同型号随身 WiFi 最常见的问题不是“代理软件不会配”，而是：

1. **相同内网网段/相同网关**：两台设备都默认 `192.168.1.1`，在同一路由表里会冲突；
2. **相同/随机 MAC**：CDC/RNDIS 设备可能出现重复 MAC、IPv6 EUI-64 冲突（OpenWrt issue #23637 有同类报告）；
3. **默认路由只有一个**：`ip route` 只能有一个默认路由，多个设备会互相覆盖；
4. **DNS 解析走错接口**：代理进程用 `getaddrinfo` 时，DNS 查询可能走主机默认路由，而不是蜂窝接口；
5. **断线后回落**：如果策略路由表里还有主机默认路由，代理可能悄悄走宽带；
6. **接口名变化**：`usb0`/`eth1` 在重插/重启后可能变，按名字写死会串线。

**netns 把这些风险从“配置纪律”变成“结构保证”：**

- 每个 netns 只有一张上行网卡（对应一台随身 WiFi）和一张 LAN veth；
- netns 内只有该随身 WiFi 的默认路由，没有宽带默认路由；设备断线时天然失败关闭；
- 每个 netns 有独立路由表、独立 loopback、独立 dnsmasq；
- 设备重连/IP 变化只影响该 netns，不影响其他出口；
- 代理监听在固定的 LAN veth IP 上，端口映射稳定，不依赖设备内部 IP；
- 不依赖 3proxy 的 `-De`/`-ne` 版本能力。

### 3.5 推荐网络架构：netns + 官方 tinyproxy + 独立 dnsmasq + veth 接入 LAN

**拓扑（每个出口一份）：**

```text
Mac 192.168.3.132
  │  HTTP proxy  http://192.168.3.201:6001  (BasicAuth)
  ▼
OpenWrt br-lan / 交换机
  │
  ├─ veth-lan1 ── br-lan
  │     │
  │   netns ns-sim1
  │     ├─ veth-ns1  192.168.3.201/24   （固定 LAN IP，代理监听在这里）
  │     ├─ usb0      由 MF79U 提供，DHCP/静态获取运营商内网地址
  │     ├─ 默认路由 → usb0 网关（唯一默认路由）
  │     ├─ dnsmasq  127.0.0.1:53 → 223.5.5.5/119.29.29.29（经 usb0）
  │     └─ tinyproxy 192.168.3.201:6001（BasicAuth + Allow Mac）
  │
  └─ 其他 ns-sim2/3/... 同理，各自 192.168.3.202/203...
        │
        ▼
     移动蜂窝网络
        │
        ▼
     巨量星图
```

**关键设计点：**

| 设计点 | 做法 | 目的 |
|---|---|---|
| 一出口一 netns | `ip netns add ns-simN`，把对应 USB 网卡移入 | 隔离路由、网段、DNS、断线 |
| 固定 LAN IP | 每个 netns 的 veth 分配 `192.168.3.201/24` 等 | 端口/IP 与出口确定性映射；设备 IP 变化不影响 |
| veth 接入 br-lan | `veth-lanN` 作为 `br-lan` 端口 | Mac 可直接访问，无需 DNAT/额外路由 |
| 唯一默认路由 | netns 内只保留 USB 网卡的默认路由 | 断线/代理失败时无宽带可回落 |
| 独立 DNS | netns 内 dnsmasq 监听 `127.0.0.1:53`，上游公共 DNS | 代理解析目标域名时走蜂窝，不泄漏到 LAN/宽带 |
| HTTP 代理 | tinyproxy 1.11.1（OpenWrt 官方包），`Listen` 固定 LAN IP，`Port 6001` | 与 Playwright HTTP 代理认证兼容 |
| 认证 | `BasicAuth <user> <password>`；`Allow 192.168.3.132`；`ConnectPort 443`（可按需 80,443） | 有认证、有限来源、有限 CONNECT 端口 |
| 不绑定设备 IP | tinyproxy 不写 `Bind`，依赖 netns 默认路由 | 设备重连/IP 变化不需要改代理配置 |
| 禁用 IPv6/RA | veth 上 `disable_ipv6=1` 或 `accept_ra=0`；按需禁用 USB 网卡 IPv6 | 防止 veth 从 LAN 获得 IPv6 默认路由，绕过蜂窝 |
| 热插拔按 USB 路径映射 | 用 `DEVPATH`/物理端口映射到 netns，不按 `usb0` 名字 | 重插/重启不串线 |
| 失败关闭 | netns 没有第二默认路由；代理停/设备断 → 连接失败 | 不回落宽带、不换其他 SIM |
| 管理 | procd 启动 dnsmasq/tinyproxy；每 netns 独立日志/PID | 单出口重启不影响其他出口 |

**为什么用 tinyproxy，而不是 3proxy/SOCKS5：**

- tinyproxy 在 OpenWrt 24.10.0 x86_64 官方包索引中存在：`tinyproxy 1.11.1-r3`，安装体积约 100 KB；
- 它是 HTTP/HTTPS 代理，正好匹配 Playwright 的 HTTP 代理认证能力；
- 官方 man page 支持 `Listen`、`Port`、`BasicAuth`、`Allow`/`Deny`、`ConnectPort`、`MaxClients`、`Timeout`、`LogLevel`；
- 配置简单，适合 J1900；每个 netns 一个进程，故障隔离；
- 不需要 3proxy 的编译/版本风险，也不需要 SOCKS5 认证（Playwright 不支持）。

**为什么不是“一个 OpenWrt IP + 6001/6002/6003 端口”：**

- 当前 LAN 是 `192.168.3.0/24`，不是参考方案的 `192.168.1.0/24`；
- 一个出口一个 LAN IP 更直观：IP 本身标识出口，端口可以都用 6001；不需要 DNAT/端口转发；
- 如果业务坚持“一个 IP + 多端口”，也可以在 netns 内用不同端口并做 DNAT，但会多一层映射和排错成本，MVP 不需要。

### 3.6 安全设计

| 要求 | 方案 |
|---|---|
| 不能无认证暴露 | tinyproxy `BasicAuth`，每出口独立强密码；`Allow` 只允许 Mac 的固定 IP |
| 不能暴露到 WAN | 代理只监听 LAN veth IP；不做 WAN 端口转发/UPnP；检查 `uci show firewall` |
| 凭据不落库/不打印 | `.runtime/cellular.env` 0600；单元配置只存环境变量名；`NetworkProof` 不含密码；日志不记录请求正文/Cookie |
| 代理配置不可被普通用户读 | tinyproxy 配置 0600；运行用户降权（如 `nobody`）；`LogLevel Warning` 避免记录完整 URL |
| DNS 不泄漏 | 每 netns dnsmasq + 唯一默认路由；用 `tcpdump` 验证 LAN/宽带接口没有目标 DNS 查询 |
| 断线不回落 | netns 无第二默认路由；代理停/网卡断 → 浏览器 `ERR_PROXY_CONNECTION_FAILED`；项目任务进入等待/失败，不换线 |
| 局域网嗅探 | HTTP BasicAuth 是 base64，不是加密；在**可信局域网**内可接受；若 LAN 有不可信设备，使用独立 VLAN/直连网线，或加 TLS 代理（会增加组件） |
| 日志保留 | 只保留连接级日志；不记录 Cookie/Authorization/请求体；按需轮转 |

**安全边界说明：** 当 veth 桥接到 `br-lan` 时，Mac 与 netns 代理在同一二层网络，OpenWrt 的三层防火墙不一定是主要控制点；主要控制是 tinyproxy 的 `Allow` + `BasicAuth`。如果要求“防火墙级”源限制，需把代理 veth 放到独立网桥/VLAN，或在网桥上加 nft bridge 规则；这会增加配置，建议在 Phase 2 根据 LAN 可信度决定。

### 3.7 硬件条件与容量

| 项 | 当前事实 | 判断 |
|---|---|---|
| J1900 | 4 核 x86_64（具体主板/内存/网口/USB 以实机为准） | 跑 5 个 tinyproxy/dnsmasq/netns 足够；CPU 不是首要瓶颈 |
| J1900 内存 | 未验证（常见 2/4 GB） | 5 个轻量进程 + conntrack 预计 <200 MB；需 `free -m` 确认 |
| USB | 未验证（USB 2.0/3.0 取决于主板） | 5 台 4G 设备总带宽通常 <100 Mbps，USB 2.0 理论足够；供电/枚举是主要风险 |
| 供电 | 计划用带独立供电 HUB | **必须**；J1900 端口供电不足以带 5 台；HUB 需 5V/足额电流、每口保护 |
| 随身 WiFi | MF79U 未验证 | 可能 RNDIS/CDC/NCM/QMI/MBIM；可能同网段/同 MAC；需逐台实测 |
| SIM | 数量/运营商/套餐未确认 | 公网 IP 独立性未知；流量/限速/是否允许热点/代理未知 |
| Mac | M4/10 核/16 GB，当前空闲约 82% | 3 个 Chrome 预计可行；5 个需实测内存/CPU；`ps` 被沙箱拒绝，未取得进程级内存 |
| 网络 | 当前宽带为中国移动湖南，延迟低 | 蜂窝若同运营商，IP 多样性可能有限；不同运营商可能更好但增加采购/APN 复杂度 |

**容量结论：** 3 个出口是合理的第一目标；5 个需要实测 USB 供电、枚举稳定性、J1900 CPU/内存、Mac Chrome 内存和平台限流；10 个不建议在单台 J1900 + 单台 Mac 上直接假设可行，可能需要第二台代理主机/Worker 主机（但仍是本地，不上云）。

### 3.8 三种状态清单

| 状态 | 事项 |
|---|---|
| **已通过命令/设备确认** | Mac 硬件/LAN/DNS/公网区域；当前 DB 基线；Playwright HTTP 认证/死代理失败关闭/SOCKS5 认证不可用；当前执行单元为单账号本地模式；官方包索引中 tinyproxy/socat 存在、3proxy 不存在 |
| **已通过代码/官方文档确认** | 执行单元 = 账号+线路+profile、并发 1；`account_ref` 唯一；正常采集固定单元；代理在 BrowserContext 注入；封面走浏览器会话；3proxy `external` 是 IP、`-De`/`-ne` 是接口/netns；tinyproxy 支持 BasicAuth/Allow/ConnectPort；Playwright HTTP 代理认证可用、SOCKS5 认证不可用 |
| **未验证/需实测** | J1900 版本/内存/USB/供电；MF79U 模式/驱动/多台并发；同网段/同 MAC；3 张 SIM 的公网 IP 独立性；蜂窝页面/采集性能；**3 个账号（已确认，未登录/未并发验证）**；平台限流/验证码变化；OpenWrt netns/tinyproxy 实机行为；Mac 5 Chrome 资源 |
| **不可访问** | J1900 SSH/console；SIM/套餐合同；真实蜂窝采集授权；3 个账号的登录凭据/手机验证人 |

---

## 4. 技术方案对比及最终推荐

### 4.1 方案 A：3proxy + 多 WAN 策略路由

**做法：** 一个 3proxy 进程开多个端口；每个端口用 `external`/`-De` 绑定不同出口；配合 `ip rule`/路由表或 `mwan3` 做源地址/接口策略路由。

**优点：**

- 单进程、资源占用低；
- 3proxy 功能成熟，HTTP/SOCKS5 都支持；
- 如果所有设备网段唯一、IP 稳定，配置相对短。

**缺点/风险：**

- OpenWrt 24.10 官方 x86_64 索引无 3proxy，需要编译/第三方 feed；
- `external wwanX` 写法错误；`-De`/`-ne` 是新版本能力，旧包可能不支持；
- 多台同型号随身 WiFi 常同网段/同网关；源 IP/接口策略路由容易串线；
- 设备 IP 变化需要更新 `external`/路由规则，代理可能重启；
- DNS 绑定需要额外 `nserver`/策略路由验证，否则 DNS 可能走宽带；
- 断线后如果策略表里还有默认路由，存在回落风险；
- `mwan3` 是负载均衡/故障切换工具，不是“端口→出口”的确定性绑定器，不能作为主机制。

**判定：不作为首选。** 只在“设备网段唯一、IP 稳定、3proxy 版本已验证”的小规模场景考虑。

### 4.2 方案 B：netns + 通用代理（3proxy 或同类）

**做法：** 每个出口一个 netns；netns 内跑 3proxy/其他 HTTP 代理；veth 接 LAN 或 DNAT 暴露端口。

**优点：**

- 路由/DNS/断线隔离最好；
- 端口与出口映射稳定；
- 设备 IP 变化不影响代理监听；
- 失败关闭由结构保证。

**缺点/风险：**

- 仍然要解决 3proxy 包/版本/认证/维护问题；
- 如果代理不支持 HTTP 认证或需要额外桥，Playwright 兼容性要验证；
- netns/veth/热插拔脚本比 A 多，但比“排障串线”更可控。

**判定：方向正确；把代理换成官方 tinyproxy 后成为方案 C。**

### 4.3 方案 C（推荐）：netns + 官方 tinyproxy + 每 netns dnsmasq + veth 接入 LAN

**做法：** 如 3.5 所述；每个出口一个 netns、一个固定 LAN IP、一个 tinyproxy、一个 dnsmasq；Mac 直接用 `http://192.168.3.20N:6001`。

**优点：**

- 官方包，无需编译 3proxy；J1900 资源占用低；
- HTTP 代理认证与 Playwright 实测兼容；
- 每个出口固定 IP/端口，不依赖设备内部 IP；
- 设备断线/IP 变化不影响其他出口；netns 无第二默认路由，天然失败关闭；
- DNS 走 netns dnsmasq，不泄漏到 LAN/宽带；
- 同网段/同 MAC 设备也能隔离；
- 与现有项目“每单元一个 proxy_server”完全兼容，项目代码不需要改代理层。

**缺点/风险：**

- 需要写 netns/veth/热插拔/procd 脚本；比“装个 3proxy”多；
- 每个出口一个 tinyproxy + 一个 dnsmasq 进程（仍很轻）；
- veth 桥接 LAN 时，OpenWrt 三层防火墙对桥内流量控制有限，需要 tinyproxy `Allow` + BasicAuth；如 LAN 不可信，需独立 VLAN/直连；
- 需要处理 `/etc/resolv.conf` 共享、udhcpc 不改写主机 DNS、IPv6 RA 等细节；
- 实际 tinyproxy/netns 行为必须在 OpenWrt 实机验证，本报告未实机安装。

**判定：推荐。** 它用官方组件解决了 3proxy 不可用、SOCKS5 认证不可用、同网段串线、DNS 泄漏、断线回落五个关键问题。

### 4.4 方案对比表

| 维度 | A：3proxy + 策略路由 | B：netns + 3proxy | C：netns + tinyproxy（推荐） |
|---|---|---|---|
| 固定端口→独立出口 | 可行，依赖版本/规则 | 可行 | 可行，结构保证 |
| 项目兼容性 | HTTP 代理可接；认证/版本需验证 | 同 A | HTTP 代理 + BasicAuth 与 Playwright 实测兼容 |
| 部署复杂度 | 中（3proxy 编译/规则） | 中高（netns + 3proxy） | 中（netns + 官方 tinyproxy） |
| 维护复杂度 | 规则/设备 IP 变化需更新 | 中 | 中；每出口独立，故障隔离 |
| 断线行为 | 可能回落默认路由 | 失败关闭 | 失败关闭 |
| DNS 绑定 | 需额外验证 | 可做 | netns dnsmasq，结构上绑定 |
| 同网段/同 MAC | 容易冲突 | 隔离 | 隔离 |
| 安全性 | 取决于 ACL/认证 | 取决于代理 | BasicAuth + Allow + 无 WAN |
| 扩展性 | 3–5 可以，10 需大量规则 | 3–10 可以 | 3–10 可以；受硬件/账号限制 |
| 成本 | 现有硬件 + 编译成本 | 现有硬件 | 现有硬件 + 官方包 |
| 改造范围 | 不改业务；改网络 | 不改业务；改网络 | 不改业务；改网络 |
| 结论 | 不推荐首选 | 可行但多一层 3proxy 风险 | **推荐** |

### 4.5 最终推荐

**推荐方案 C：OpenWrt netns + 官方 tinyproxy（HTTP 代理）+ 每个 netns 独立 dnsmasq + veth 接入 LAN。**

理由排序：

1. **与 Playwright 的真实能力匹配**：HTTP 代理认证可用；SOCKS5 认证不可用；tinyproxy 正好是 HTTP 代理。
2. **不依赖 3proxy 的包/版本**：官方 OpenWrt 24.10 x86_64 有 tinyproxy；3proxy 没有。
3. **确定性映射**：出口 = netns = 固定 LAN IP:6001；不依赖设备内部 IP 或接口名。
4. **失败关闭**：netns 只有蜂窝默认路由；断线/代理停不会回落宽带。
5. **DNS 绑定**：每 netns dnsmasq + 唯一默认路由。
6. **项目改动最小**：现有 `BrowserRuntime` 已支持每单元一个 `proxy_server`；单出口接入不需要改采集主链路。

**不推荐：** 3proxy `external wwanX` 照抄、mwan3 作为主绑定、SOCKS5 认证、单账号多出口并发、单元内热切换代理。

---

## 5. 最终架构图

### 5.1 拓扑

```text
┌────────────────────────────── Mac 192.168.3.132 ──────────────────────────────┐
│                                                                              │
│  前端 / FastAPI / P1 Intake Worker / PostgreSQL / Temporal / Redis / MinIO     │
│                                                                              │
│  Collection Worker(unit-cellular-01) ── Chrome(profile-01) ──┐                │
│  Collection Worker(unit-cellular-02) ── Chrome(profile-02) ──┼─ HTTP proxy    │
│  Collection Worker(unit-cellular-03) ── Chrome(profile-03) ──┘   (BasicAuth)  │
│                                                                              │
└───────────────────────────────┬──────────────────────────────────────────────┘
                                │ LAN 192.168.3.0/24
                                ▼
┌────────────────────────── J1900 OpenWrt ──────────────────────────────────────┐
│                                                                              │
│  br-lan                                                                      │
│   ├─ veth-lan1 ── ns-sim1: veth-ns1 192.168.3.201/24                         │
│   │                  ├─ tinyproxy 192.168.3.201:6001  (BasicAuth)            │
│   │                  ├─ dnsmasq 127.0.0.1:53 → 223.5.5.5                     │
│   │                  └─ usb0 (MF79U #1) ── default route (唯一)               │
│   │                                                                          │
│   ├─ veth-lan2 ── ns-sim2: 192.168.3.202:6001 ── usb1 (MF79U #2)             │
│   └─ veth-lan3 ── ns-sim3: 192.168.3.203:6001 ── usb2 (MF79U #3)             │
│                                                                              │
│  防火墙：不做 WAN 端口转发；tinyproxy Allow 仅 Mac；配置 0600                 │
│                                                                              │
└───────────────────────────────┬──────────────────────────────────────────────┘
                                │ 移动蜂窝网络（每台设备独立 SIM）
                                ▼
                          巨量星图 www.xingtu.cn
```

### 5.2 任务、账号、会话、代理的映射

```text
P1 Intake Worker
  │  promote_intake（多单元时必须改为池选择；单单元可先用固定单元）
  ▼
unit-cellular-01 ── account-01 ── profile-01 ── proxy http://192.168.3.201:6001
unit-cellular-02 ── account-02 ── profile-02 ── proxy http://192.168.3.202:6001
unit-cellular-03 ── account-03 ── profile-03 ── proxy http://192.168.3.203:6001
  │
  ▼
Temporal 队列 xingtu-unit-cellular-01/02/03（每单元一个 Worker）
  │
  ▼
Activities.collect（每单元 max_concurrent_activities=1）
  │
  ▼
BrowserHost 租约 + profile 锁
  │
  ▼
Chrome BrowserContext（启动时注入 proxy）
  │
  ▼
对应 netns 的 tinyproxy → 对应 USB 设备 → 对应 SIM → 蜂窝出口 → 星图
```

**硬映射：**

- 一个账号只能出现在一个单元；
- 一个单元只能有一个 profile、一个 proxy；
- 一个 proxy 只属于一个 netns/一个出口；
- 一个出口只对应一台随身 WiFi + 一张 SIM；
- 同一单元同一时刻只有一个任务；
- 任务不携带“出口”字段，出口通过单元选择间接确定。

### 5.3 失败关闭路径

```text
tinyproxy 停止 / 设备断线 / netns 无默认路由
  → Mac 浏览器连接代理失败（ERR_PROXY_CONNECTION_FAILED）
  → Playwright 报错 / 任务进入 WAITING_FOR_RESOURCE 或失败
  → 不尝试其他 SIM、不尝试宽带、不切换账号
  → 运维修复该 netns 后，任务重试/继续
```

---

## 6. 项目改造清单

### 6.1 必须修改（按阶段）

| 阶段 | 改动 | 文件/组件 | 目的 |
|---|---|---|---|
| 单出口接入 | 新 `production_line` 单元配置 + `NetworkProof` + `network_probe_command` | `.runtime/units/unit-cellular-01.json`、`.runtime/network/*.proof.json`、探针脚本 | 让现有 `BrowserRuntime` 使用代理；不改采集主链路 |
| 单出口接入 | 新星图账号 + 新 profile + 重新登录 | 账号/profile 运维 | 不污染现有 `unit-local-mac-02`；避免同账号双会话 |
| 多出口网络 | OpenWrt netns/veth/tinyproxy/dnsmasq/hotplug/firewall | OpenWrt 配置/脚本（不在本仓库） | 一出口一 netns，固定 LAN IP/端口 |
| 多出口运维 | 线路健康探针 + 公网 IP 清单 | `scripts/` 或 OpenWrt 脚本 | 检测独立 IP、延迟/丢包、断线、重复 IP |
| 多单元调度 | `promote_intake` 池选择 | `backend/src/xingtu/product_repository.py` | 正常采集不再堆在单个单元 |
| 多单元调度 | 多 Worker 启动器 | `scripts/` 或 `Makefile` | 一单元一进程、独立日志/PID、代理凭据环境 |
| 多单元调度 | 集成测试 | `backend/tests/integration/` | 覆盖选择、排除不健康单元、无单元、并发分配 |
| 多单元调度 | 运行手册/卡片 | `docs/` | 运维可复现，不靠聊天记录 |

### 6.2 可选优化

| 优化 | 目的 | 代价 |
|---|---|---|
| `NetworkProbe` 增加 `observed_ip`/地址族 | 原生记录公网 IP，检测变化/重复 | 小代码改动 + Schema/模型 |
| 线路健康表/API | 前端/运维看到每线 IP、延迟、最近成功 | 新表/查询/页面 |
| 排队任务改派 | 单元线路故障时人工移到其他单元 | 新管理命令/审计 |
| Chrome 后台流量参数 | 减少蜂窝流量/噪声 | 需回归平台会话/Service Worker |
| 浏览器级出口自检 | 登录后在同一 Context 验证出口 IP | 需本地回显服务/代码改动 |
| 独立 VLAN/直连链路 | 代理流量与办公 LAN 隔离 | 交换机/网卡/布线 |
| 第二台代理/Worker 主机 | 10 出口或 Mac 资源不足 | 额外硬件/运维 |

### 6.3 完全不需要修改

- `BrowserRuntime` 的代理注入、profile 锁、会话快照、浏览器启动参数；
- `Engine`/`Adapter` 的采集流程、契约、字段解析；
- 封面下载路径（已走浏览器会话/代理）；
- `BrowserHost` 的租约、generation、维护交接；
- 任务状态机、幂等、检查点、快照、数据库业务表；
- 前端任务中心/达人库（执行单元列表已有，不需要为多 IP 做新 UI）；
- P1 模型调用（httpx 直连，不访问星图，不需要走蜂窝）；
- 反爬节奏（2s 动作间隔、15s 达人间隔、90s 操作超时）；不要为了速度降低。

### 6.4 明确禁止

| 禁止项 | 原因 |
|---|---|
| 同一账号配置到多个并发单元 | 会话互踢、风控、profile 冲突；`account_ref UNIQUE` 已禁止 |
| 放宽 `account_ref` 唯一约束来“复用账号” | 破坏账号/线路/profile 隔离，风险不可控 |
| 单元内热切换代理/线路 | 当前 profile/会话绑定线路；切换会破坏会话与审计 |
| 自动回落到宽带或其他 SIM | 违背“失败关闭”，平台会看到非预期出口 |
| 代理轮换/随机 IP | DEC-009 明确禁止；会破坏会话与证据 |
| 无认证、0.0.0.0 暴露代理 | 安全要求；必须 BasicAuth + Allow + 无 WAN |
| 把 `NetworkProof` 三个布尔直接写 `true` 而无测试证据 | 证明字段是人工 attestation；必须有 DNS/断线/出口测试 |
| 照抄 `external wwanX` | 语法错误；3proxy 版本/包也不一定可用 |

---

## 7. 分阶段实施计划

> 每个阶段都必须有明确 PASS/FAIL/BLOCKED 和可复核证据；未通过不得进入下一阶段。以下“人日”仅为量级，不是承诺。

### Phase 0：决策与基线（0.5–1 人日）

**工作：**

1. 确认独立星图账号数量、每个账号的登录手机号/归属人、是否允许用于采集。
2. 确认目标优先级：吞吐、IP 多样性、冗余，还是三者组合。
3. 确认 J1900 的 IP/SSH/console 访问方式；采集只读硬件信息。
4. 确认 MF79U/SIM/HUB 的实际数量与购买状态（用户表格中部分是“计划/参考型号”，不能当作已到货）。
5. 确认 SIM 运营商、套餐、流量上限、是否允许热点/代理、IPv4/IPv6。
6. 固定本机基线变量：关闭 macOS 系统代理（或记录其规则），确认浏览器实际出口；记录当前公网 IPv4/IPv6。
7. 若用户授权，跑一次受控小样本（关键词固定、目标 3–5、无重试）作为基线；未授权则只做网络/中立页面测试。

**前提：** 用户提供账号/J1900/SIM 信息与授权。

**验收：**

- [ ] 账号数量与可用性有书面结论（≥2 才能进入 Phase 4）。
- [ ] J1900 只读信息完整（版本、内核、CPU、内存、USB、网卡、已装包、路由、防火墙、DNS）。
- [ ] MF79U/SIM/HUB 实际数量与状态确认。
- [ ] 本机基线网络数据（延迟、丢包、TTFB、出口 IP）有记录。
- [ ] 真实采集基线（若授权）有记录；未授权则标记 BLOCKED，不编造。

**失败处理：** 账号不足 2 个 → 停止多出口并发规划；J1900 无法访问 → 标记 BLOCKED，先解决访问；MF79U 未到货 → 先做单台验证计划，不采购批量。

### Phase 1：单 SIM + 单代理 + 单执行单元（1–2 人日）

**工作：**

1. 在 OpenWrt 上验证单台 MF79U：`lsusb`/`dmesg`/`ip link`/DHCP/默认路由/公网 IP。
2. 安装/确认 `tinyproxy`、`ip-full`、`kmod-veth`、`dnsmasq`；先做一个 netns（或先不 netns，仅单台）验证 tinyproxy。
3. 配置 tinyproxy：`Listen <OpenWrt LAN IP>`、`Port 6001`、`BasicAuth`、`Allow <Mac IP>`、`ConnectPort 443`、`LogLevel Warning`；不做 WAN 暴露。
4. 在 Mac 上用 `curl -x http://user:pass@<OpenWrt>:6001` 验证出口 IP；用 Playwright 通过代理访问中立页面。
5. 停止 tinyproxy / 断开 USB，验证浏览器 `ERR_PROXY_CONNECTION_FAILED`，不直连。
6. 用 `tcpdump` 验证目标 DNS 只走蜂窝接口，不在 LAN/宽带接口出现。
7. 创建新 `production_line` 单元配置（新账号、新 profile、`proxy_server`、`network_evidence_path`、`network_probe_command`、代理凭据 env）；`register-unit`；`production-preflight`；`xingtu login`（人工登录）；`browser-check`。
8. 若用户授权，跑 3–5 位小样本；记录任务墙钟、单达人耗时、成功/超时/重试、出口 IP。

**前提：** Phase 0 完成；至少 1 个可用于测试的账号（不能是现有本地账号，除非用户明确接受风险）；J1900 可操作；真实采集授权。

**验收（PASS/FAIL/BLOCKED）：**

- [ ] MF79U 被识别、能拨号、能出网（PASS/FAIL）。
- [ ] tinyproxy 可被 Mac 访问，BasicAuth 生效；错误密码 407/拒绝。
- [ ] 代理出口 IP 与宽带 IP 不同（或至少属于蜂窝），且 DNS 绑定测试 PASS。
- [ ] 代理停/设备断 → 浏览器失败关闭，无直连（PASS/FAIL）。
- [ ] 新单元 `READY`，`production-preflight` PASS，`browser-check` 成功。
- [ ] 小样本任务完成/部分完成，任务状态/数据/代理映射正确；性能在阈值内。
- [ ] 未通过：不得进入 Phase 2。

**失败处理：**

- MF79U 不识别：检查 USB 模式（CD-ROM/RNDIS/QMI/MBIM）、`usb_modeswitch`、内核模块；换 USB 口/供电 HUB；仍不行则更换已验证型号，不批量采购。
- tinyproxy 认证/代理不通：检查 `Listen`/`Allow`/`BasicAuth`/防火墙/Mac IP；用 `curl -v` 看 407。
- DNS 泄漏：检查 `/etc/resolv.conf`、netns dnsmasq、IPv6 RA、udhcpc 是否改写 DNS。
- 性能超阈值：先查信号/运营商/供电/代理 CPU；不要降低反爬节奏；仍不达标则暂停方案。

### Phase 2：多 SIM + 多代理（2–4 人日）

**工作：**

1. 为每台 MF79U 建 netns + veth + 固定 LAN IP + dnsmasq + tinyproxy；按 USB 物理路径做 hotplug 映射。
2. 禁用 veth IPv6/RA；确认 netns 只有蜂窝默认路由；udhcpc 不改写主机 DNS。
3. 每出口分配独立 `192.168.3.20N:6001`；Mac 用 curl/Playwright 逐一验证。
4. 每出口记录 3 次公网 IP（不同时间、两个回显服务），比较是否重复。
5. 断开其中一台设备/停一个 tinyproxy，确认只有该出口失败，其他出口不受影响；恢复后确认端口/IP 映射仍正确。
6. 让一台设备重连/更换 IP，确认其他出口不受影响，代理监听不变。
7. 监测 J1900 CPU/内存/USB 错误、温度/供电；监测 Mac 资源。

**前提：** Phase 1 PASS；至少 2–3 台 MF79U + SIM + 供电 HUB；J1900 资源可接受。

**验收：**

- [ ] N 个出口对应 N 个不同公网 IP（按选定地址族；重复即 FAIL）。
- [ ] 每个端口固定绑定一个 netns/设备；设备 IP 变化后端口仍正确。
- [ ] 单出口断线/重启不影响其他出口；无跨出口串线。
- [ ] 每出口 BasicAuth/Allow 生效；无 WAN 暴露。
- [ ] DNS 绑定测试逐出口 PASS；断线失败关闭 PASS。
- [ ] J1900 CPU/内存/USB 在阈值内；无 over-current/枚举失败。
- [ ] 1 小时稳定性探针成功率达到阈值。

**失败处理：**

- 公网 IP 重复：标记该出口不可用于“独立 IP”；尝试不同 APN/运营商/设备；不能解决则减少并发出口数，不伪造独立。
- 同网段/同 MAC：确认 netns 隔离；禁用 IPv6；必要时改设备 LAN 网段。
- 供电/USB 不稳：换带独立供电 HUB、换口、加散热；减少设备数。
- J1900 资源不足：减少出口/换更强主机；不要在过载下继续。

### Phase 3：项目单执行单元接入（1–2 人日）

**工作：**

1. 用 Phase 1 的 `production_line` 单元，通过实际产品流程（前端提交 → P1 → P2）跑一个小任务；不使用 `smoke-local` 绕过生产编排。
2. 核对任务状态、单元 ID、代理、出口 IP、快照/结果、失败原因；确认没有走本地宽带。
3. 重复一次“代理停/设备断”的故障注入，确认任务进入等待/失败而不是换线；恢复后确认可重试/继续。
4. 记录任务墙钟、单达人耗时、成功/超时/重试、网络错误、数据量。

**前提：** Phase 1 PASS；真实采集授权；产品 API/Temporal/Worker 正常；新账号可用。

**验收：**

- [ ] 任务实际使用指定代理/出口；DB/日志/出口 IP 三方一致。
- [ ] 任务状态与数据管理逻辑不受影响（P1/P2/快照/任务中心）。
- [ ] 代理故障时失败关闭；不切换到其他出口/宽带。
- [ ] 性能在单出口阈值内；否则暂停。
- [ ] 不污染现有 `unit-local-mac-02` 的账号/profile/任务。

**失败处理：** 若任务实际出口与配置不一致，立即停止，检查 `proxy_server`、`ensure_line`、系统代理、Chrome 启动参数；不要用“看起来能用”掩盖。

### Phase 4：多任务/多执行单元接入（3–5 人日）

**工作：**

1. 实现 `promote_intake` 池选择（按 `network_mode='production_line'`、能力、健康状态、当前任务负载）；加集成测试。
2. 增加多 Worker 启动器：每单元一个 `xingtu worker --config`，独立日志/PID，加载代理凭据 env。
3. 为 3 个单元配置 3 个独立账号/线路/profile；`register-unit`、`login`、`production-preflight` 逐单元通过。
4. 同时提交 3 个同规模小任务；核对每个任务落到哪个单元/代理/出口，是否串线。
5. 停一个出口，确认只有该单元的任务等待，其他任务继续；恢复后重试。
6. 测量 1×/3× 的吞吐、错误率、平台挑战、Mac/J1900 资源。

**前提：** Phase 2/3 PASS；≥3 个独立账号；调度改动通过测试；用户授权真实并发小样本。

**验收：**

- [ ] 正常采集按池分配，不再全部堆到一个单元。
- [ ] 每任务实际出口 = 其单元绑定出口；无串线。
- [ ] 单出口故障隔离；不自动换线/不直连。
- [ ] 3 出口总吞吐 ≥1.8× 单出口（目标 ≥2.2×）；每出口 ≥80% 单出口。
- [ ] 平台挑战/错误率不显著高于基线；Mac/J1900 资源在阈值内。
- [ ] 任务状态/前端/数据不回退。

**失败处理：** 若调度改动风险高，先回滚到单单元，保留网络能力；若多出口 <1.8×，先查平台限流/Mac/J1900，不盲目加卡；若出现串线/失败关闭失败，立即停止并修复。

### Phase 5：按结果扩容到 5–10（3–10 人日，视硬件）

**工作：**

1. 每次只加 1 个出口，重复 Phase 2/4 的验证；不一次性加满。
2. 监测 USB 供电/总线、J1900 CPU/内存、Mac Chrome 内存、蜂窝信号/温度、数据用量。
3. 5 个出口稳定后，评估 10 个是否需要第二台代理/Worker 主机；仍保持本地部署。
4. 24 小时稳定性 + 真实小样本 + 数据套餐成本核算。

**验收：**

- [ ] 每个新增出口独立公网 IP、固定映射、失败关闭。
- [ ] 24 小时无 cross-talk、无 over-current、无任务串线。
- [ ] 吞吐按新增出口线性/次线性增长，达到业务阈值。
- [ ] 数据套餐/成本可接受；平台无异常挑战增长。

**失败处理：** 达到稳定上限就停，不强行 10 个；若 5 个已影响稳定性/性能，回退到 3 个；若平台限流，停止扩容。

---

## 8. 采购及额外依赖清单

> 用户 2026-10-22 已确认：**3 个独立星图账号**；J1900 访问尚未确认；MF79U/USB HUB/SIM 尚未购买或未确认到货。以下按“**先做 3 个出口**、先验证 1 台设备”的最保守假设列出；不要一次买 5 台/5 张。

### 8.1 必须补充/确认

| 项 | 说明 | 何时买 |
|---|---|---|
| 带独立供电 USB HUB | 5V/足额电流、每口保护、**4–7 口**（3 个出口 + 余量）；J1900 端口供电不足以带多台 | Phase 1 前 |
| MF79U 或替代 4G USB 设备 | **先买/借 1 台验证**；确认 OpenWrt 模式/驱动/多台兼容后再补到 **3 台**（当前 3 账号，不需要 5 台） | Phase 1 前 1 台，Phase 2 再补 2 台 |
| SIM 数据卡 + 套餐 | **3 张**（对应 3 账号），确认流量、限速、热点/代理条款、IPv4/IPv6；**优先至少 2 家运营商**以增加 IP 多样性 | Phase 1 前 1 张，Phase 2 再补 2 张 |
| USB 延长线/天线/散热 | 信号、供电、散热；避免金属遮挡 | Phase 1/2 |
| 网线/交换机口 | J1900 与 Mac 同 LAN；确保有足够端口 | Phase 1 前 |
| 可选：第二台代理/Worker 主机 | 10 出口或 Mac 资源不足时；仍本地，不上云 | Phase 5 评估（当前不需要） |

### 8.2 软件依赖（OpenWrt）

| 包 | 用途 | 可用性 |
|---|---|---|
| `tinyproxy` | HTTP/HTTPS 代理 + BasicAuth | OpenWrt 24.10.0 x86_64 官方索引有 `1.11.1-r3` |
| `ip-full` | `ip netns`/veth/路由 | 需在实际固件确认（可能在 base feed） |
| `kmod-veth` | veth | 需在匹配内核的 kmods feed 确认 |
| `dnsmasq` | 每 netns DNS | OpenWrt 通常已内置 |
| `socat`（可选） | 如果不用 veth 直连而做端口转发 | 官方索引有 `1.8.0.3-r2` |
| `usb-modeswitch`（按需） | 设备先以 CD-ROM 出现时切换 | 需在实际固件确认 |
| `kmod-usb-net-rndis`/`cdc-ether`/`qmi-wwan` 等（按设备模式） | USB 网卡驱动 | 需在匹配内核的 kmods feed 确认 |
| **不需要** `3proxy` | 本方案用 tinyproxy | 官方 24.10 x86_64 索引无 3proxy |

### 8.3 不需要购买

- 云服务器、Tailscale/VPN、远程网络组件；
- 5G 设备（先验证 4G 是否满足；4G 通常够文本/API/封面）；
- 5–10 张 SIM（当前只需 3 张；先 1 张验证，再补 2 张，最后按结果扩）；
- 多 WAN 企业路由器（J1900 做代理聚合即可）；
- 额外的 Mac/服务器（先测 3 个出口；10 个再评估）；
- 3proxy 商业授权/第三方编译服务（除非明确选择 3proxy 路线）。

### 8.4 数据/成本提示

- 本轮基线任务 10 位达人产生 259 个封面对象、约 23.3 MB；21 位达人 570 个封面、约 50.0 MB；封面平均约 92–94 KB/张，约 25 张/达人。
- 页面/API/静态资源流量另计；DIAG-01 观测到一次 2 位达人任务有 2698 条请求，但未统计总字节。**不要用“封面 50 MB”当作全部流量**；Phase 1 必须实测每任务总流量。
- **3 个出口** × 每任务 100–300 MB × 每天任务数，可能很快达到套餐上限；先算清单价再扩容；5–10 出口只在 3 出口稳定后评估。

---

## 9. 多 SIM 独立出口验证（补充章节）

### 9.1 结论先行

**3 套 SIM + 随身 WiFi（对应 3 个已确认账号）能否稳定提供 3 个不同的公网出口 IP：目前不能下结论，必须实测。**  
技术上可以做到“每条线路独立路由、独立代理、独立端口”，但**运营商 CGNAT、动态 IP、同池复用**都可能让多张 SIM 共享同一个公网 IP；这不是 OpenWrt 能控制的。

### 9.2 资源模型

```text
SIM 1 + 随身 WiFi 1 → netns 1 → tinyproxy 192.168.3.201:6001 → 出口 1
SIM 2 + 随身 WiFi 2 → netns 2 → tinyproxy 192.168.3.202:6001 → 出口 2
SIM 3 + 随身 WiFi 3 → netns 3 → tinyproxy 192.168.3.203:6001 → 出口 3
```

- 一个 netns 只放一台设备的网络接口；一台设备只对应一张 SIM；
- 一个出口只对应一个固定 LAN IP:端口；
- 代理端口不随机、不轮换、不自动切换；
- 一个出口故障不影响其他 netns。

### 9.3 验证方法（可执行）

**准备：**

- 每出口一个可访问的 HTTP 代理（BasicAuth）；
- 两个独立的公网 IP 回显服务（例如 `https://myip.ipip.net`、`https://ifconfig.me/ip`；以实际可达为准）；
- 记录时间、出口编号、SIM/设备编号（不要记录 ICCID/IMEI 到公开文档）。

**步骤：**

1. 对每个出口，在 0/5/10 分钟各请求两个回显服务，记录 IPv4、IPv6（如启用）、地区/ASN、时间。
2. 比较同一出口多次结果：动态 IP 是否变化；变化是否影响端口映射。
3. 比较不同出口结果：是否出现重复公网 IP。
4. 在 OpenWrt 上对每个 netns 记录 `ip route`、`ip addr`、默认网关；确认只有该设备默认路由。
5. 断开局域网宽带（或断开主机默认路由）后，重复代理请求：应仍然只走蜂窝；若失败，说明代理依赖了宽带，FAIL。
6. 断开一个出口的 USB/停 tinyproxy：其他出口应正常；该出口应失败关闭；恢复后端口映射不变。
7. 让一个出口重连/更换 IP：其他出口不受影响；该出口代理监听不变，新的出站使用新 IP。
8. 用 `tcpdump` 在 LAN/宽带接口抓 DNS：目标域名解析不应出现在 LAN/宽带；应出现在对应 USB 接口。
9. 记录 1 小时探针成功率、RTT、丢包。

**判定：**

| 结果 | 判定 |
|---|---|
| N 个出口得到 N 个不同公网 IPv4（选定地址族），重复采样仍不同，其他隔离/失败关闭 PASS | **PASS** |
| 有任意两个出口公网 IP 相同 | **FAIL（独立 IP 不成立）** |
| 部分出口拿不到 IP/频繁断线 | **FAIL/BLOCKED**，修设备/供电/运营商 |
| 断线后代理走宽带或其他 SIM | **FAIL（安全）**，立即停止 |
| 硬件未到/无授权 | **BLOCKED** |

### 9.4 如果不同公网 IP 少于设备数量

1. **先确认不是测试误差**：换回显服务、换时间、换 DNS；排除代理缓存/回显站点 CDN。
2. **确认地址族**：IPv4 重复但 IPv6 不同，或反之；目标平台实际用哪个族？不要用“另一个族不同”来宣称独立。
3. **尝试不同 APN/运营商**：同一运营商同池概率高；不同运营商更可能不同，但增加采购/配置复杂度。
4. **接受现实并减少并发**：只把真正独立的出口分配给并发单元；重复的出口标记不可用，不继续分配新任务。
5. **不要用“多个端口”伪装独立**：多个端口共用同一个上游出口，平台看到的还是同一个 IP；用户明确不接受这种方案。
6. **记录并报告**：把重复 IP 的出口、时间、运营商、设备记录到运维清单；不要静默继续。

### 9.5 断线/IP 变化对其他出口的影响

- netns 结构下：**不影响**。每个 netns 独立路由/DNS/代理；一台设备断线只影响该出口。
- 项目侧：该单元的任务进入 `WAITING_FOR_RESOURCE`/失败；不会自动切到其他单元/线路；恢复后可重试。
- 如果使用单命名空间 + 策略路由：设备断线/重连可能改默认路由，影响其他出口；这是不推荐方案 A 的原因之一。
- IP 变化：端口映射不变（监听在 LAN IP）；出口 IP 变化由外部探针记录；项目当前 `NetworkProbe` 不记录 IP，需要外部清单/可选代码扩展。

### 9.6 当前状态

**BLOCKED**：未访问 J1900，未接入 MF79U/SIM，未做真实蜂窝测试。以上为验证方案，不是已通过结论。

---

## 10. IP 池采集性能与吞吐量评估（补充章节）

### 10.1 已观测的本地基线（真实 DB，非受控实验）

| 任务（短 ID） | 日期 | 目标 | 有效 | 墙钟（`updated_at`） | 有效/小时 | 备注 |
|---|---|---:|---:|---:|---:|---|
| `59f14291` | 2026-10-16 | 20 | 20 | 38.7 min | 31.0 | 部分完成；历史契约/关键词与当前不同 |
| `a00a3bce` | 2026-10-16 | 11 | 11 | 18.6 min | 35.5 | 部分完成 |
| `b94d146b` | 2026-10-21 | 10 | 10 | 32.3 min | 18.6 | 含 504 重试 + lease 丢失；`completed_at` 是首次失败时间，故用 `updated_at` |
| `829d4568` | 2026-10-22 | 21 | 21 | 83.2 min | 15.1 | 含一次 LEASE_LOST/重扫；分页 page2 |
| `1e7a02ff` | 2026-10-13 | 10 | 10 | 17.0 min | 35.3 | 部分完成 |
| `f74f43bf` | 2026-10-13 | 10 | 10 | 25.5 min | 23.5 | 部分完成 |
| `efb257a6` | 2026-10-14 | 5 | 5 | 6.4 min | 46.9 | 小样本 |

**读法：**

- 这不是同一关键词、同一契约、同一重试策略的受控实验；只能作为“量级参考”。
- 任务级墙钟包含浏览器启动、登录/会话检查、搜索、逐达人采集、封面、重试/等待；小任务（1 位）也要 2–3.5 分钟，说明**任务固定开销明显**。
- 15 秒/达人的 `ChallengePolicy.creator_interval_seconds` 是下限：20 位至少 5 分钟；实际 17–39 分钟，说明主要时间在页面/模块/封面/重试，而不是这个间隔。
- 单单元规划可用 **20–30 有效达人/小时**作为保守量级；实际受平台、重试、目标数影响。

### 10.2 本机网络基线（实测）

| 指标 | 实测 | 说明 |
|---|---|---|
| 到网关 RTT | 平均 4.7 ms，0% 丢包 | 3 次 ping，样本很小 |
| 到 DNS `223.5.5.5` RTT | 平均 28.3 ms，0% 丢包 | 3 次 ping |
| 到 `www.xingtu.cn` TTFB | 热 DNS 87–95 ms；冷启动 235–280 ms | 3 次 curl，HTTP 200；不是 P50/P95 |
| 公网 IPv4 | 中国移动湖南 | 直连与系统代理相同 |
| 公网 IPv6 | 存在，但 `curl -6` 曾连接重置 | 浏览器可能走 IPv6；测试需固定地址族 |
| 系统代理 | `127.0.0.1:7897` | 当前 Chrome 基线可能使用；必须固定变量 |

### 10.3 用户要求的指标表（当前状态）

| 指标 | 当前网络 | 单蜂窝 IP | 多蜂窝 IP 并发 |
|---|---|---|---|
| 页面加载耗时 P50/P95 | **待测**（只有 3 次 TTFB，不足以算 P50/P95） | 待测 | 待测 |
| 单达人采集耗时 P50/P95 | **待测**（任务级 10 位 17–32 min；无逐达人计时） | 待测 | 待测 |
| 每小时成功采集达人数 | 19–35/h（10 位任务）、31/h（20 位任务） | 待测 | 待测 |
| 任务成功率 | 历史 DB 混合，不能当受控基线；**待测** | 待测 | 待测 |
| 网络超时率 | **待测** | 待测 | 待测 |
| 重试次数 | 历史任务有 504/LEASE_LOST；**待测** | 待测 | 待测 |

**不能编造 P50/P95。** 当前没有逐达人计时、没有足够的同口径样本、没有蜂窝样本；必须按 Phase 0/1 的受控测试补齐。

### 10.4 单出口性能测试设计

**网络层（不需要星图采集授权）：**

1. 通过代理对中立 HTTPS 页面做 100 次 HEAD/GET，记录 P50/P95、丢包、TLS 握手、DNS 时间。
2. 通过代理下载 5 MB 测试文件，记录吞吐（下行/上行）。
3. 连续 60 分钟，每 60 秒探测一次出口 IP/延迟，记录抖动、断线、IP 变化。
4. 与宽带同口径对比（关闭系统代理/直连），记录差值。

**浏览器层（中立页面，不需要星图采集授权）：**

1. Playwright + Chrome 通过代理打开中立页面，记录 `domcontentloaded`/`load`/资源数/总字节。
2. 连续 10 次冷/热加载，记录 P50/P95。
3. 确认出口 IP、DNS 路径、无直连（死代理测试）。

**业务层（需要用户授权）：**

1. 同一关键词、同一目标数（3–5 位）、同一契约、同一重试策略，宽带 vs 单蜂窝各跑 1 次；最好各跑 2 次。
2. 记录任务墙钟、有效数、资料完整、精选完整、超时、重试、挑战、封面数/字节、总流量。
3. 计算：单达人耗时、每小时有效数、成功率、超时率、重试次数。

### 10.5 单出口建议阈值（待业务确认）

这些不是行业标准，是从当前基线 + 业务可用性推导的**建议门槛**；Phase 1 后可调整。

| 指标 | 建议通过线 | 说明 |
|---|---|---|
| 同目标数任务墙钟 | ≤ 本地基线 × 1.5 | 例如 20 位本地 39 min → 蜂窝 ≤58 min |
| 单达人 P95 耗时 | ≤ 本地 P95 × 2 | 需要先有本地 P95 |
| 任务成功率 | ≥ 本地基线 − 5 个百分点 | 不能因蜂窝显著增加失败 |
| 网络超时率 | ≤ 本地基线 × 2 | 且绝对值可控 |
| 重试次数 | 不高于本地同口径 +1 次/任务 | 不能靠无限重试“看起来成功” |
| 出口独立性 | 与宽带/其他出口不同 IP | 重复即 FAIL |
| 断线行为 | 失败关闭，无直连/无换线 | 任何直连即 FAIL |
| 1 小时探针 | 成功率 ≥99%，丢包 <1%，RTT P95 <300 ms | 运营目标，按实测调整 |

### 10.6 多出口并发测试设计

**前提：** ≥3 个独立账号、3 个单元、3 条独立出口；每个单元并发 1。

**方法：**

1. 3 个同规模小任务（3–5 位）同时提交；记录每个任务落到哪个单元/出口。
2. 记录 1× 单出口基线（同任务）与 3× 并发的总墙钟/有效数/错误。
3. 同时监测 Mac CPU/内存（3 个 Chrome + 3 Worker + DB/Temporal）、J1900 CPU/内存/USB、每出口 RTT/丢包、平台挑战/错误。
4. 停一个出口，确认只有该单元任务等待；其他任务继续；恢复后重试。
5. 重复 2–3 轮，避免单次偶然。

**建议阈值：**

| 指标 | 建议通过线 | 说明 |
|---|---|---|
| 3 出口总吞吐 | ≥1.8× 单出口（目标 ≥2.2×） | 低于 1.8× 说明扩容收益不足 |
| 每出口吞吐 | ≥80% 单出口 | 不能因并发互相拖垮 |
| 串线 | 0 | 任何任务走错出口即 FAIL |
| 失败关闭 | 100% | 任何直连/换线即 FAIL |
| 平台挑战/错误 | 不显著高于基线（建议 ≤+5 个百分点） | 超过则暂停 |
| Mac 资源 | 无持续 swap/内存压力；CPU 可接受 | 具体阈值按实测 |
| J1900 资源 | CPU <70% 平均、<90% 峰值；内存充足；无 USB 错误 | 运营目标 |
| 数据量 | 在套餐预算内 | 每任务实测 |

### 10.7 瓶颈分层

| 层 | 可能瓶颈 | 判断方法 | 处理 |
|---|---|---|---|
| 蜂窝/运营商 | 信号弱、限速、CGNAT、丢包、动态 IP | RSRP/SINR、speedtest、ping/丢包、IP 变化 | 换位置/天线/运营商/5G；不行则停 |
| 随身 WiFi/USB | 供电不足、枚举失败、USB 总线、设备发热 | `dmesg`、`lsusb -t`、over-current、温度 | 带供电 HUB、换口、散热、减少设备 |
| J1900/代理 | CPU、内存、conntrack、tinyproxy 进程 | `top`/`free`/`vmstat`/日志 | 减出口、优化配置、换主机 |
| Mac/Chrome | 内存、CPU、Chrome 实例数 | `memory_pressure`、Chrome 内存、swap | 3 个先测；5 个需扩容/减实例 |
| 项目调度 | 单单元并发 1、固定单元分配 | 队列/任务分配/墙钟 | 池选择 + 多 Worker |
| 平台 | 限流、验证码、接口慢 | 挑战计数、错误码、同账号/不同账号对比 | 降速/暂停/人工处理；不绕过 |

### 10.8 如果性能不达标

1. **先修网络/硬件**：信号、天线、位置、供电、USB 口、运营商、设备型号；不要先改代码。
2. **区分瓶颈**：用网络层/浏览器层/业务层三段测试，确认是蜂窝、代理、Mac 还是平台。
3. **不要降低反爬节奏**：2s/15s/90s 是风险控制，不是性能开关；降低会放大风控。
4. **不要绕开线路**：封面/接口/静态资源不能为了速度走宽带；这会破坏“所有平台流量走绑定线路”的约束。
5. **考虑 5G/不同运营商**：如果 4G 延迟/丢包是瓶颈，5G 或异网可能更好；但先小规模验证。
6. **减少并发/目标数**：如果平台限流，增加 IP 不会解决；保持小任务、分时执行。
7. **暂停方案**：如果单出口 >2× 慢、或多出口 <1.8×、或出现失败关闭失败/重复 IP，停止扩容，保留本地宽带采集。

### 10.9 继续/暂停决策规则

| 条件 | 决策 |
|---|---|
| ≥2 个独立账号；单出口性能 ≤1.5×；独立 IP/失败关闭/DNS 全 PASS；3 出口 ≥1.8× | **继续**到 Phase 4/5 |
| 独立账号少于 2 个（当前已确认 3 个，不触发） | **暂停多出口并发**；最多单出口/备用 |
| 公网 IP 重复且无法解决 | **暂停该出口**；不伪装独立 |
| 单出口 >2× 慢，或 3 出口 <1.8× | **暂停扩容**，先查瓶颈 |
| 出现直连/换线/串线 | **立即停止**，修复安全边界 |
| 平台挑战/错误显著增加 | **暂停**，小样本复核；不绕过 |
| J1900/USB 不稳定、数据套餐超预算 | **减出口/换硬件** |

> 用户已确认 3 个独立账号，因此按 3 出口规划；“独立账号少于 2 个”这一行保留为通用门槛，当前不触发。

---

## 11. 用户决策与仍需补充的信息（2026-10-22）

### 11.1 已决策

| 问题 | 你的决策 | 对方案的影响 |
|---|---|---|
| 独立星图账号 | **3 个**可独立登录、可授权采集的账号，每个有独立手机号/归属人 | 可做 3 出口并发；当前目标 3 个单元，不再按“只有 1 个账号”设限 |
| 优先级 | **P0 总吞吐/采集效率；P1 IP 多样性/独立出口；P2 线路冗余** | 先保证 3 单元并发与单任务 ≤1.5×；每出口独立 IP 必须实测；冗余按“故障隔离”实现，不做自动切卡 |
| 真实采集测试 | **当前不需要/未授权** | P0 性能与业务验收 **BLOCKED**；只能做网络层与中立页面测试，不能宣称采集效率达标 |
| J1900 访问 | **当前不确认** | Phase 1 阻塞；需要 LAN IP/SSH/console 或只读命令输出 |
| SIM 采购 | **尚未购买，可按要求购买** | 先买 3 张（对应 3 账号）；建议至少 2 家运营商；先验证 1 台设备，再补 2 台 |
| 代理使用范围 | **只给本机/另一台电脑使用，不上云** | LAN + BasicAuth + `Allow` 指定 IP；不做 WAN 暴露/云端/Tailscale |
| 性能门槛 | **接受**“单出口 ≤1.5× 基线、3 出口 ≥1.8× 单出口” | 记录为继续/暂停门槛；未实测前不宣称达标 |
| Chrome profile | 需要创建 **3 个新 profile** | 必须在对应代理就绪后逐个创建/登录；需要平台 ID/手机验证人；**不能在宽带先登录再换蜂窝** |

### 11.2 仍需补充

1. **3 个账号的平台 ID**（页面上的 `ID: ...`）、账号标签/归属人、谁负责接收手机验证码。
2. **J1900 访问方式**：LAN IP / SSH / console，或执行报告 §12.1 的只读命令并脱敏贴回。
3. **采购确认**：3 张 SIM 的运营商/套餐；先验证的 1 台设备型号（MF79U 或替代）；带独立供电 HUB 的规格。
4. **真实采集授权**（后续 Phase 1/3/4）。当前不授权，性能项保持 BLOCKED；网络/中立页面测试不受影响。
5. **第二台电脑的 LAN IP**（如果它也要使用代理；否则只允许 Mac）。

### 11.3 决策后的计划调整

- **当前目标：3 个账号 → 3 条出口 → 3 个执行单元**，不是 5–10。5–10 只在 3 出口稳定、且有新增账号/硬件后评估。
- **采购：先买 3 张 SIM（建议至少 2 家运营商）+ 1 台设备验证**；验证通过再补 2 台；不要一次买 5 台/5 张。
- **P0：** Phase 1 单出口 ≤1.5×；Phase 4 3 出口 ≥1.8×。未授权真实采集前不能测 P0，只能做网络/中立浏览器测试；不得用“端口能通”代替性能验收。
- **P1：** 每出口公网 IP 必须实测不同；重复 IP 的出口标记不可用；同运营商同池概率高，异网优先。
- **P2：** netns 隔离保证“一张卡断网不影响其他出口对应的任务”；**不做“故障任务自动切到另一张卡”**，那会破坏账号/线路/profile 绑定。当前代码也不支持自动切卡。
- **Chrome：** 3 个 profile 在 Phase 1/2 代理就绪后逐个创建；顺序 = 代理验证 → 单元配置 → `register-unit` → `production-preflight` → `login`（人工短信）→ `browser-check`/`session-diagnostics` → `READY`。**当前不创建“已登录但走宽带”的 profile**，否则换到蜂窝后 IP 变化会带来会话/风控问题。
- **代理范围：** 只允许 Mac（以及可选的第二台电脑）访问；`Allow` 写固定 IP；BasicAuth；不做 WAN 端口转发。

**规划映射（账号 ID/手机验证人待填；代理 IP 为规划值）：**

| 单元 | Profile 路径 | 规划代理 | 当前状态 |
|---|---|---|---|
| `unit-cellular-01` | `.runtime/profiles/unit-cellular-01` | `http://192.168.3.201:6001` | 待创建（等代理+账号 ID+SMS） |
| `unit-cellular-02` | `.runtime/profiles/unit-cellular-02` | `http://192.168.3.202:6001` | 待创建（等代理+账号 ID+SMS） |
| `unit-cellular-03` | `.runtime/profiles/unit-cellular-03` | `http://192.168.3.203:6001` | 待创建（等代理+账号 ID+SMS） |

> 当前没有创建空 profile 目录，也没有注册任何 `unit-cellular-*`。空目录不等于可用 Chrome profile；可用 profile 必须在对应代理就绪后通过 `xingtu login` 初始化并完成账号验证。

---

## 12. 附录

### 12.1 J1900 只读检查命令（请勿修改配置）

> 建议在维护窗口执行；只读命令不需要 `opkg update`/`install`。输出中如含 IMEI/ICCID/手机号/MAC，请先脱敏再贴回。

```sh
cat /etc/openwrt_release
uname -a
cat /proc/cpuinfo | sed -n '1,40p'
free -m
df -h
lsusb
lsusb -t
dmesg | grep -iE 'usb|rndis|cdc|qmi|mbim|option|ttyUSB|over-current|disconnect|reset'
ip -br link
ip -br addr
ip route show table all
ubus call system board
uci show network
uci show firewall
opkg list-installed | grep -E 'usb|rndis|cdc|qmi|mbim|option|3proxy|tinyproxy|hev|microsocks|dnsmasq|ip-full|socat|veth'
cat /etc/resolv.conf
logread | tail -100
```

**判读重点：**

- `OpenWrt` 版本/内核；是否 x86_64；内存是否 ≥2 GB；
- `lsusb` 是否看到 MF79U 的 VID:PID；是否 CD-ROM；
- 插入后是否出现 `usb0`/`eth1`/`wwan0`；`dmesg` 是否有枚举/over-current；
- 当前 LAN 网段/网关/DNS；是否与随身 WiFi 默认网段冲突；
- 已装 `tinyproxy`/`ip-full`/`kmod-veth`/`usb` 相关包；
- firewall 是否有 WAN 暴露/UPnP。

### 12.2 Playwright 代理行为实测记录

- 环境：macOS，Apple M4，16 GB；Playwright `1.63.0`；Chrome `156.0.8078.47`；临时 profile；中立页面 `https://myip.ipip.net`；未访问星图。
- 结果：
  - 无代理：加载成功；
  - HTTP `127.0.0.1:7897`：加载成功；
  - SOCKS5 `127.0.0.1:7897`（无认证）：加载成功；
  - HTTP 死代理 `127.0.0.1:9`：`net::ERR_PROXY_CONNECTION_FAILED`；
  - SOCKS5 死代理 `127.0.0.1:9`：`net::ERR_PROXY_CONNECTION_FAILED`；
  - HTTP 代理 + 407：观察到 `Proxy-Authorization: Basic ...`；
  - SOCKS5 + 用户名/密码：`Browser does not support socks5 proxy authentication`；
  - 代理模式下观察到 Chrome 后台请求（`clients2.google.com`、`www.gstatic.com`、`update.googleapis.com` 等）也走代理。
- 说明：这是对 Playwright/Chrome 行为的实测，不是对 tinyproxy 实机的测试；tinyproxy 行为依据 1.11.1 官方 man page。

#### 12.2.1 线路证明/探针 JSON 形状（供后续实施卡使用）

`NetworkProof` 文件（`0600`，不含密码/Cookie）示例：

```json
{
  "line_id": "cellular-sim1",
  "unit_id": "unit-cellular-01",
  "proxy_server": "http://192.168.3.201:6001",
  "dns_bound": true,
  "disconnect_blocks_direct": true,
  "worker_egress_enforced": true,
  "verified_at": "2026-10-23T00:00:00Z",
  "valid_until": "2026-10-30T00:00:00Z",
  "evidence_refs": ["docs/evidence/IPPOOL-02-phase1-2026-10-23.md"]
}
```

`network_probe_command` 的 stdout 必须是**恰好**下面四个字段的 JSON（`extra="forbid"`；日志写 stderr；exit 0 表示健康，非 0 表示失败）：

```json
{
  "line_id": "cellular-sim1",
  "healthy": true,
  "egress_enforced": true,
  "observed_at": "2026-10-23T00:00:00Z"
}
```

说明：

- `observed_at` 必须是带时区的 UTC，且与当前时间差 ≤30 秒；探针必须每次真实请求代理，不能读旧文件。
- 探针必须显式使用代理、禁用环境代理（curl `--noproxy ""` 或 httpx `trust_env=False`），否则可能验证到宽带。
- 当前 `NetworkProbe` 不允许额外字段，所以**公网 IP 不要塞进这个 JSON**；写到独立清单（如 `.runtime/network/ips.json`），由探针比较重复/变化。若要原生记录 IP，需另做小代码改动。
- `dns_bound`/`disconnect_blocks_direct`/`worker_egress_enforced` 必须有实际测试证据支撑，不能只写 `true`。

### 12.3 基线 SQL（只读）

```sql
-- 任务墙钟/目标/有效/完整度（示例）
SELECT r.root_task_id, r.state, r.task_kind, r.created_at, r.updated_at, r.completed_at,
       (f.payload->>'target_count')::int AS target,
       (SELECT count(*) FROM task_creators tc
         WHERE tc.root_task_id=r.root_task_id AND tc.valid) AS valid_rows,
       round(extract(epoch from (r.updated_at-r.created_at))/60,1) AS wall_min,
       r.payload->>'failure_reason' AS reason
FROM root_tasks r LEFT JOIN filter_plans f USING(root_task_id)
WHERE r.task_kind='collection'
  AND r.state IN ('COMPLETED','PARTIAL_COMPLETED','FAILED')
ORDER BY r.created_at DESC;

-- 封面对象体积
SELECT root_task_id, count(*) AS n, round(sum(byte_size)/1024.0/1024.0,1) AS mb,
       round(avg(byte_size)) AS avg_bytes
FROM media_objects GROUP BY root_task_id ORDER BY max(created_at) DESC;
```

### 12.4 参考资料

- 3proxy 配置手册（`external`/`-De`/`-ne`）：<https://3proxy.org/doc/man5/3proxy.cfg.5.html>
- 3proxy 安全建议：<https://3proxy.org/doc/securityen.html>
- tinyproxy 1.11.1 配置手册（`Listen`/`Bind`/`BasicAuth`/`Allow`/`ConnectPort`）：<https://manpages.debian.org/bookworm/tinyproxy/tinyproxy.conf.5.en.html>
- Playwright Python 网络/代理文档：<https://playwright.dev/python/docs/network>
- Playwright `ProxySettings` API：<https://playwright.dev/python/docs/api/class-browser#browser-new-context-option-proxy>
- OpenWrt 24.10.0 x86_64 官方包索引：<https://downloads.openwrt.org/releases/24.10.0/packages/x86_64/packages/>
- hev-socks5-server README（认证/`bind-interface`）：<https://github.com/heiher/hev-socks5-server>
- microsocks README（SOCKS5/认证/`-b`）：<https://github.com/rofl0r/microsocks>
- OpenWrt issue #23637（cdc_ether 相同 MAC / EUI-64 冲突）：<https://github.com/openwrt/openwrt/issues/23637>
- OpenWrt 防火墙配置：<https://openwrt.org/docs/guide-user/firewall/firewall_configuration>
- OpenWrt DHCP/DNS（dnsmasq）：<https://openwrt.org/docs/guide-user/base-system/dhcp_configuration>
- Linux `ip-netns(8)`：<https://man7.org/linux/man-pages/man8/ip-netns.8.html>

### 12.5 本轮未执行/未验证清单

- 未登录/未访问 J1900；未取得 OpenWrt 版本、内存、USB、驱动、防火墙、已装包信息。
- 未接入任何 MF79U/SIM；未验证 USB 模式、拨号、并发、供电、信号、公网 IP。
- 未安装 tinyproxy/ip-full/kmod-veth；未在 OpenWrt 实机验证 netns/tinyproxy/dnsmasq。
- 未做蜂窝性能测试；未做真实星图采集；未做 3 账号/多单元并发。
- 未修改项目代码、配置、数据库、执行单元、网络；未安装依赖；未提交 Git。
- 未验证平台当前限流/验证码阈值；未验证 3 个账号的登录/并发及合规性。
- Mac 进程级内存因沙箱拒绝 `ps` 未取得；只有硬件规格与系统空闲比例。

---

## 13. 最终结论（再次给产品经理）

**推荐做，但按“单出口 → 多出口 → 多单元”的顺序做，且先把账号和实测数据拿到。**

- **技术可行性：可行。** 当前项目已经具备代理绑定、会话/profile 隔离、并发 1、失败关闭的基础；OpenWrt 用 netns + tinyproxy 可以提供固定、独立、可认证的 HTTP 出口。
- **参考方案：部分正确、关键实现需修正。** 多 USB + 多代理 + 防火墙 + 健康检查的方向对；但 3proxy 的 `external wwanX` 写法错误、OpenWrt 官方包索引没有 3proxy、SOCKS5 认证不可用、同网段/同 MAC/DNS/断线回落需要 netns 处理。
- **业务适配性：取决于账号和性能。** 一个账号只能安全对应一个单元；没有多账号，多 IP 不能提高并发。单出口若明显拖慢采集，或多出口没有 1.8 倍收益，就不值得扩容。
- **最小落地方式：** 每个蜂窝出口一个 netns + tinyproxy + 固定 LAN IP；每个生产单元一个新账号 + 新 profile + 一个代理；单出口接入不改采集主链路；多单元只改 `promote_intake` 的池选择和加一个多 Worker 启动器。
- **现在应做的下一步：** 第 11 节决策已确认 **3 个独立账号**，当前按 **3 个出口/3 个单元** 规划；先做 Phase 0/1。**先买 3 张 SIM（建议至少 2 家运营商）+ 1 台设备验证**，验证通过再补 2 台；不要买 5 套/5 张。J1900 访问和 SIM 到位前，不修改代码、不上多出口并发；真实采集未授权，P0 性能项保持 BLOCKED。
