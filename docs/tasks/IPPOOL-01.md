# IPPOOL-01：OpenWrt 多 IP 池建设与采集接入可行性评估

状态：待验收  
更新时间：2026-10-23T00:19:00+08:00  
是否验收：否；本轮只交付评估报告，未执行实机网络、蜂窝性能或真实采集验收。

## 用户决策（2026-10-22/23）

| 项 | 决策 |
|---|---|
| 独立星图账号 | **3 个**可独立登录、可授权采集的账号，每个有独立手机号/归属人 |
| 优先级 | **P0 总吞吐/采集效率；P1 IP 多样性/独立出口；P2 线路冗余** |
| 真实采集测试 | **当前不授权**；P0 性能/业务验收保持 BLOCKED |
| J1900 访问 | **当前不确认**；需要 LAN IP/SSH/console 或只读命令输出 |
| SIM 采购 | **尚未购买，可按要求购买**；先买 3 张（对应 3 账号），先验证 1 台设备 |
| 代理范围 | 只给本机/另一台电脑使用；**不上云** |
| 性能门槛 | **接受**“单出口 ≤1.5× 基线、3 出口 ≥1.8× 单出口” |
| Chrome profile | 需要创建 **3 个新 profile**；待对应代理就绪后逐个创建/登录 |

**由此确定：** 当前目标为 **3 个账号 → 3 条出口 → 3 个执行单元**，不是 5–10；P2 按“故障隔离”实现，不做自动切卡。

## 目标与范围

**目的**：基于项目真实代码、现有执行单元架构和已购买的 J1900/OpenWrt 条件，判断“多 USB 蜂窝出口 + 本地代理网关”能否以最小改动接入巨量星图采集系统，并给出可执行的阶段计划。

包含：

- 调查 ExecutionUnit、Collection Worker、Temporal、Playwright/Chrome、任务调度、会话/profile、代理接入的真实实现；
- 核验参考方案中的 OpenWrt/3proxy/接口绑定/策略路由/认证/防火墙等技术点；
- 对比方案 A（3proxy + 策略路由）、方案 B（netns + 通用代理）、方案 C（netns + 官方 tinyproxy），给出推荐；
- 设计多 SIM 独立出口验证、IP 池性能/吞吐量评估、分阶段实施与采购清单；
- 明确需要用户决策的问题。

不包含：

- 不修改项目代码、网络配置、执行单元配置、数据库或前端；
- 不安装依赖、不部署 OpenWrt/代理、不采购；
- 不发起真实巨量星图采集（本轮无授权）；
- 不把未实测的 J1900/MF79U/SIM/蜂窝性能写成已通过。

## 关联与依赖

- 功能：F11（蜂窝代理池与 Worker 资源管理）、F10（人工登录/维护）的线路侧前置；技术方案 §12。
- 验收项：T18（线路断开/出口变化不直连）、T20（第二执行单元隔离）；U07/U08 相关。
- 前置卡片：[UNIT-01](UNIT-01.md)（执行单元/线路/本地模式）、[OPS-01](OPS-01.md)（产品调度/部署）；本卡不替代它们。
- 决策记录：[DEC-006](../decisions/DEC-006-local-network-mode.md)（本地/生产网络模式）、[DEC-009](../decisions/DEC-009-crawl-strategy-and-anti-bot.md)（不轮换代理/不绕过风控）。
- 报告：[IPPOOL-01 OpenWrt 多 IP 池建设与接入可行性评估](../evidence/IPPOOL-01-openwrt-multi-ip-feasibility-2026-10-22.md)。

## 验收清单

### 本轮已完成的评估项

- [x] 调查执行单元真实机制：一个单元 = 账号 + 线路/代理 + 独立持久 profile，并发 1；每单元独立 Temporal 队列。
  - 证据：`backend/src/xingtu/runtime.py:47-128`（`UnitConfig`）、`:427-520`（代理注入）、`backend/src/xingtu/worker.py:668-691`（每单元队列/并发 1）、`migrations/001_initial.sql:2-3`（`account_ref` 唯一）、`migrations/004_local_line_sharing.sql`（生产线路独占）。
- [x] 调查正常采集/更新任务的调度差异：正常采集固定到 Intake Worker 配置的单元；`select_execution_unit` 未被使用；更新任务才池化认领。
  - 证据：`backend/src/xingtu/product_repository.py:473-519`、`backend/src/xingtu/intake_worker.py:81-84`、`backend/src/xingtu/repository.py:433-442`、`:500-543`。
- [x] 调查 Playwright/Chrome 代理能力：BrowserContext 启动时注入代理；HTTP/SOCKS5 均支持无认证；HTTP 代理认证可用；SOCKS5 认证不可用；死代理失败关闭。
  - 证据：`runtime.py:443-479`；本轮临时 profile 实测（Playwright 1.63.0 + Chrome 156.0.8078.47，中立页面，未访问星图）。
- [x] 核验参考方案：`external wwanX` 不是标准 3proxy 语法；`external` 参数是 IP；按接口是 `-De`，按 netns 是 `-ne`；OpenWrt 24.10.0 x86_64 官方包索引无 3proxy。
  - 证据：[3proxy 配置手册](https://3proxy.org/doc/man5/3proxy.cfg.5.html)、[OpenWrt 24.10.0 x86_64 Packages](https://downloads.openwrt.org/releases/24.10.0/packages/x86_64/packages/)。
- [x] 核验替代方案：OpenWrt 24.10.0 x86_64 官方索引有 `tinyproxy 1.11.1-r3`；其 man page 支持 `Listen`/`Bind`/`BasicAuth`/`Allow`/`ConnectPort`。
  - 证据：[tinyproxy 1.11.1 man page](https://manpages.debian.org/bookworm/tinyproxy/tinyproxy.conf.5.en.html)。
- [x] 建立当前采集基线：10 位约 17–32 min（19–35 有效/h）、20 位约 38.7 min（31/h）、21 位约 83.2 min（15.1/h，含 lease 丢失/重扫）；封面约 23–50 MB/任务。
  - 证据：本地 PostgreSQL 只读查询；详见报告 §10.1。
- [x] 本机网络基线：网关 4.7 ms、DNS 28.3 ms、星图 TTFB 热 87–95 ms/冷 235–280 ms（3 次样本，不代表 P50/P95）；系统代理 127.0.0.1:7897，直连/代理出口同为中国移动湖南。
- [x] 方案对比与推荐：推荐方案 C（netns + 官方 tinyproxy + 每 netns dnsmasq + veth 接入 LAN）；拒绝照抄 3proxy `external wwanX`、拒绝 SOCKS5 认证、拒绝单账号多出口并发。
- [x] 输出最终架构图、任务/账号/会话/代理映射、失败关闭路径。
- [x] 输出项目改造清单（必须/可选/不需要/禁止）、五阶段实施计划、采购/依赖清单、7 个决策问题。
- [x] 输出《多 SIM 独立出口验证》与《IP 池采集性能与吞吐量评估》两个补充章节，明确 PASS/FAIL/BLOCKED 与待测指标。

### 未完成/待实机验收项

- [ ] **J1900 实机信息**：OpenWrt 版本/内核/CPU/内存/USB 控制器/供电/网口/已装包/路由/防火墙/DNS。
  - 当前状态：**BLOCKED**；未获得 J1900 的 LAN IP/SSH/console 访问，未执行只读命令。
  - 解除条件：用户提供访问方式，或用户执行报告 §12.1 的只读命令并脱敏贴回。
- [ ] **MF79U 单台兼容性**：USB 模式（RNDIS/CDC/NCM/QMI/MBIM/CD-ROM）、驱动、拨号、DNS、公网 IP、稳定性。
  - 当前状态：**BLOCKED**；无设备接入；公开资料无权威 OpenWrt 兼容性声明。
- [ ] **多设备并发**：多台同时识别、同网段/同 MAC、USB 供电/总线、单台断线不影响其他。
  - 当前状态：**BLOCKED**；依赖单台 PASS 与实际到货数量。
- [ ] **多 SIM 独立公网 IP**：3 张卡（对应 3 账号）是否得到 3 个不同公网 IP；CGNAT/动态 IP/同池复用。
  - 当前状态：**BLOCKED**；未接入 SIM；建议至少 2 家运营商以提高独立 IP 概率。
- [ ] **单出口/多出口性能**：页面加载、单达人耗时、每小时成功数、成功率、超时率、重试、总流量、Mac/J1900 资源。
  - 当前状态：**BLOCKED**；无蜂窝样本、无真实采集授权。
- [ ] **项目单单元接入**：新 `production_line` 单元 + 新账号 + 新 profile + 代理 + `NetworkProof` + 探针，实际跑小样本。
  - 当前状态：**未开始**；本轮未创建/注册任何单元，未改配置。
- [ ] **Chrome profile 创建（3 个）**：`unit-cellular-01/02/03` 的独立持久 profile；需对应代理就绪、平台 ID、手机验证人。
  - 当前状态：**未创建**；不能在宽带先登录再换蜂窝（会把会话绑定到错误 IP）；待 Phase 1 逐台创建。
- [ ] **采购**：3 张 SIM（建议至少 2 家运营商）+ 1 台先验证设备 + 带独立供电 HUB；验证通过再补 2 台。
  - 当前状态：**未采购**；用户已授权按需购买，但需先确认设备型号/套餐。
- [ ] **多单元调度改动**：`promote_intake` 池选择 + 多 Worker 启动器 + 集成测试。
  - 当前状态：**未开始**；仅在报告中列为必须改动；未经授权不实施。

## 实现记录

- 本轮只新增/修改文档，未修改 `backend/**`、`frontend/**`、`contracts/**`、`migrations/**`、`deploy/**`、`Makefile`、`scripts/**`。
- 新增评估报告：[docs/evidence/IPPOOL-01-openwrt-multi-ip-feasibility-2026-10-22.md](../evidence/IPPOOL-01-openwrt-multi-ip-feasibility-2026-10-22.md)。
- 新增本卡片；同步 `docs/tasks/README.md` 与 `docs/项目任务进度总览.md` 的入口说明。
- 未创建/注册执行单元；未修改 `unit-local-mac-02`；未改 OpenWrt；未安装任何依赖。
- 技术判断（供后续实施卡引用）：
  1. 一个可并发使用的出口 = 一个执行单元 + 一个独立账号 + 一个独立 profile + 一个固定代理；账号数量是并发上限。
  2. 单出口接入现有代码即可，无需改采集主链路；多单元并发必须补 `promote_intake` 池选择。
  3. 生产代理选 HTTP（tinyproxy/BasicAuth），不选需要认证的 SOCKS5。
  4. OpenWrt 推荐 netns + 官方 tinyproxy + 每 netns dnsmasq + veth 接入 LAN；不采用 3proxy `external wwanX`。
  5. 必须实测独立公网 IP、DNS 绑定、断线失败关闭、单出口/多出口性能；未达标不扩容。

## 验证证据

| 日期 | 环境/动作 | 结果 | 证据 |
|---|---|---|---|
| 2026-10-22 | 本地 PostgreSQL 只读查询（任务终态/目标/有效/封面体积） | 取得 §10.1 基线；未写库 | 报告 §10.1、§12.3；本地 DB |
| 2026-10-22 | 本机网络只读探测（route/ifconfig/ping/curl/scutil） | LAN `192.168.3.0/24`；网关 4.7 ms；DNS 28.3 ms；星图 TTFB 87–95 ms（热）；系统代理 `127.0.0.1:7897`；出口中国移动湖南 | 报告 §1.3、§10.2 |
| 2026-10-22 | Playwright 1.63.0 + Chrome 156.0.8078.47；临时 profile；中立页面 `https://myip.ipip.net` | 无代理/HTTP/SOCKS5（无认证）成功；HTTP/SOCKS5 死代理 `ERR_PROXY_CONNECTION_FAILED`；HTTP 407 后发送 `Proxy-Authorization`；SOCKS5+认证启动失败 | 报告 §2.3、§12.2 |
| 2026-10-22 | 官方资料/包索引核验 | 3proxy 无官方 24.10 x86_64 包；tinyproxy 1.11.1-r3 有；3proxy `external` 是 IP、`-De`/`-ne` 是接口/netns；Playwright 只支持 HTTP 代理认证 | 报告 §3.2、§3.5、§12.4 |
| 2026-10-22 | 项目代码/迁移/文档核对 | 执行单元模型、并发 1、账号唯一、固定单元调度、代理注入、封面走浏览器会话均已确认 | 报告 §2、§6 |
| 2026-10-22 | J1900/MF79U/SIM/蜂窝性能 | **未执行/BLOCKED**；无访问/无硬件/无授权 | 报告 §3.8、§12.5 |

## 交接信息

**当前结论**：

- 方案技术方向可行；推荐方案 C；但**多出口并发受独立账号数量硬约束**，单账号只能单出口。
- 参考方案的 3proxy `external wwanX` 不可照抄；SOCKS5 认证不可用；OpenWrt 官方 24.10 x86_64 无 3proxy。
- 单出口接入不需要改采集主链路；多单元并发需要 `promote_intake` 池选择 + 多 Worker 启动器。
- 当前性能基线只是本地历史任务量级，蜂窝性能未测；不能承诺“多 IP 一定更快”。

**已决策**（详见报告 §11）：

- 3 个独立账号；P0 吞吐 > P1 独立 IP > P2 冗余；真实采集暂不授权；J1900 访问未确认；SIM 未购买但可按需购买；代理仅本机/另一台电脑；接受 1.5×/1.8× 门槛。
- 当前目标：3 个账号 → 3 条出口 → 3 个执行单元；不做 5–10。
- P2 按 netns 故障隔离实现；不做故障任务自动切卡。

**仍需补充**：

1. 3 个账号的平台 `ID: ...`、账号标签/归属人、谁负责手机验证。
2. J1900 的 LAN IP/SSH/console，或报告 §12.1 只读命令输出。
3. 采购确认：3 张 SIM 的运营商/套餐；先验证的 1 台设备型号；带独立供电 HUB 规格。
4. 真实采集授权（后续 Phase 1/3/4）；当前不授权，P0 性能项保持 BLOCKED。
5. 第二台电脑的 LAN IP（如果它也要使用代理；否则仅允许 Mac）。

**下一步（Phase 1，尚未开始）**：

1. 采购/接入 1 台设备 + 1 张 SIM；在 J1900 上验证识别/拨号/出口 IP/DNS/失败关闭。
2. 建第一个 netns + tinyproxy（`192.168.3.201:6001`）+ `NetworkProof`/探针。
3. 创建 `unit-cellular-01` 配置（新账号/新 profile/代理/证明/探针），`register-unit` → `production-preflight` → `login`（人工短信）→ `browser-check`/`session-diagnostics` → `READY`。
4. **Chrome profile 创建顺序**：代理验证 → 单元配置 → 注册 → `production-preflight` → `login`（Chrome 通过代理启动，账号归属人完成手机验证）→ 账号 ID 精确匹配 → `READY`。3 个 profile 逐个做，不在宽带先登录再换蜂窝。
5. Phase 1 PASS 后补 2 台设备/2 张 SIM；再做 3 出口/3 单元和 `promote_intake` 池选择。当前不建 `IPPOOL-02`，待 J1900/SIM 到位后另建实施卡。

**3 个单元/Profile 映射（待填账号 ID/手机验证人；代理 IP 为规划值）**：

| 单元 | Profile 路径 | 账号 | 规划代理 | 当前状态 |
|---|---|---|---|---|
| `unit-cellular-01` | `.runtime/profiles/unit-cellular-01` | `account-01`（待填 `ID: ...`） | `http://192.168.3.201:6001` | 待创建（等代理+ID+SMS） |
| `unit-cellular-02` | `.runtime/profiles/unit-cellular-02` | `account-02`（待填 `ID: ...`） | `http://192.168.3.202:6001` | 待创建（等代理+ID+SMS） |
| `unit-cellular-03` | `.runtime/profiles/unit-cellular-03` | `account-03`（待填 `ID: ...`） | `http://192.168.3.203:6001` | 待创建（等代理+ID+SMS） |

> 说明：当前没有创建空 profile 目录，也没有注册任何 `unit-cellular-*`。仅创建空目录并不等于可用 Chrome profile；可用 profile 必须在对应代理就绪后通过 `xingtu login` 初始化并完成账号验证。

**阻塞**：

- J1900/MF79U/SIM 实机不可访问；真实蜂窝性能与采集授权未获得；3 个账号的平台 ID/手机验证人未提供。评估交付不因此阻塞，但 Phase 1 与 Chrome profile 创建无法开始。

## 状态历史

- 2026-10-22T23:53:00+08:00：新建 → 待验收；完成项目架构、参考方案、Playwright 代理行为、基线数据、方案对比、实施计划与两个补充章节；未改代码/网络/配置，未做实机蜂窝验收。
- 2026-10-23T00:19:00+08:00：待验收（不变）；记录用户决策：3 个独立账号、P0 吞吐 > P1 独立 IP > P2 冗余、真实采集暂不授权、J1900 访问未确认、SIM 未购买但可按需购买、代理仅本机/另一台电脑、接受 1.5×/1.8× 门槛、需创建 3 个 Chrome profile。计划调整为 3 出口；Chrome profile 待代理就绪后逐个创建；未创建 profile、未采购、未改代码/网络。
