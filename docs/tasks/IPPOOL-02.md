# IPPOOL-02：OpenWrt 3 路蜂窝出口搭建与单出口验证

状态：进行中  
更新时间：2026-10-31T13:32:00+08:00
是否验收：否；Phase 0/1 完成、Phase 2 line1 单出口通过、Phase 4 line1 持久化通过（重启自恢复）；line2 因 SIM/随身 WiFi 无蜂窝数据暂停、line3 未开始；尚未创建 Chrome profile/ExecutionUnit。

## 目标与范围

**目的**：按 IPPOOL-01 推荐的方案 C，在 J1900 OpenWrt 上建立 3 个独立蜂窝出口，每个出口固定一个局域网 IP:6001，通过 HTTP BasicAuth 提供给 Mac（以及可选的第二台电脑），并完成独立 IP、DNS 绑定、失败关闭、互不影响验证。

包含：

- J1900 只读盘点（OpenWrt 版本/内存/USB/网卡/已装包/路由/DHCP/防火墙）；
- J1900 旁路主机地址与主路由 DHCP 池确认；
- 单台随身 WiFi 的 netns + veth + dnsmasq + tinyproxy；
- 单出口代理连通、失败关闭、DNS 绑定验证；
- 复制到 3 条出口，验证 3 个公网 IP、互不影响、断线重连；
- 持久化脚本（验证后）；
- Mac 侧代理凭据、`NetworkProof`/探针、`production_line` 单元与 3 个 Chrome profile（需账号 ID/手机验证人）。

不包含：

- 真实巨量星图采集（用户当前不授权）；
- 修改现有采集主链路、业务数据库、前端；
- 自动切卡/故障任务自动迁移（P2 只做故障隔离）；
- 云端/Tailscale/WAN 暴露。

## 关联与依赖

- 方案依据：[IPPOOL-01](IPPOOL-01.md) 与[可行性评估报告](../evidence/IPPOOL-01-openwrt-multi-ip-feasibility-2026-10-22.md)。
- 施工手册：[IPPOOL-02 施工手册](../evidence/IPPOOL-02-openwrt-build-runbook-2026-10-24.md)。
- 短命令清单（无 GUI console 专用）：[IPPOOL-02 短命令清单](../evidence/IPPOOL-02-short-commands-2026-10-24.md)。
- 技术方案 §12（F11）；T18/T20；U07/U08。
- 前置：J1900 实机访问、3 台 USB 随身 WiFi、3 张 SIM、带供电 HUB、Mac 与 J1900 同一 LAN。
- 账号：3 个独立星图账号（已确认）；平台 ID/手机验证人待补充。

## 施工阶段与验收

### Phase 0：只读盘点（部分完成）

- [x] OpenWrt **25.12.5** x86_64；包管理器 **apk**（不是 opkg）；
- [x] J1900 是 **路由器**：WAN `eth2 192.168.0.178/24`，默认网关 `192.168.0.1`；LAN `br-lan 192.168.1.1/24`；
- [x] Mac 通过网线接 J1900 LAN；不改 LAN IP，不关 J1900 DHCP；
- [x] BusyBox `ip` 不支持 `-br`，也没有 `ip netns add`；需安装 `ip-full`；
- [x] DHCP/租约/DNS：`dhcp.lan.ignore` → `Entry not found`（默认开启）；`start=100`、`limit=150` → 池 `.100–.249`；`/tmp/dhcp.leases` 为空；`/etc/resolv.conf` = `127.0.0.1`/`::1`；
- [x] `cat /proc/net/arp`：`192.168.1.210` → 真实 MAC `00:e0:4c:68:03:dc`，设备 `br-lan`；LAN1 链路正常；`.250–.252` 计划使用；
- [x] Mac `en6` 已设为 `192.168.1.210/24`；**换到 LAN1 后 `ping 192.168.1.1` 0% 丢包、0.66–0.77 ms**，二层链路正常；LAN2 不通，后续固定用 LAN1；
- [x] `ps | grep dnsmasq`：dnsmasq 在运行；`ping -c 2 223.5.5.5` 0% 丢包（41–258 ms）；`nslookup openwrt.org 223.5.5.5` 可解析（`64.226.122.113`）；
- [x] 修复 dnsmasq 上游：`uci add_list dhcp.@dnsmasq[0].server=223.5.5.5` + `uci commit dhcp` + restart；`nslookup openwrt.org` 已返回 `64.226.122.113`/IPv6；
- [x] WAN 确认：`ip route` 默认路由在（eth1 `192.168.3.1` / eth2 `192.168.0.1`）；`ping -c 2 223.5.5.5` 0% 丢包（23.6–24.4 ms）；`udhcpc: no lease` warning 不阻塞；
- [x] `apk update` 成功（11250 packages）；`apk add ip-full` 装好 `ip-full 6.18.0-r2`（`/sbin/ip -> /usr/libexec/ip-full`）；`apk add tinyproxy` 装好 `tinyproxy 1.11.1-r3`；`ip -br addr` 已能运行；
- [x] `ip -4 -br addr` 确认：`br-lan 192.168.1.1/24`（Mac 的 LAN 网关）、`eth1 192.168.3.66/24`、`eth2 192.168.0.178/24`、`lo`；LAN1 已通；
- [x] `ls /sys/class/net/br-lan/brif` → `eth0`，LAN1 确实在 `br-lan` 网桥内；
- [x] `tinyproxy -v` → `1.11.1`；
- [x] `eth2` 已确认是 Modem：MAC `34:4b:50:00:00:00`，device `2-2.1:1.0`（USB）；但 `eth2` 同时有 `192.168.0.178/24` 和默认路由 `via 192.168.0.1`，说明 **Modem 抢了 WAN 的接口名并继承了 WAN 静态配置**；
- [x] Host 仍有默认路由 `via 192.168.3.1 dev eth1 src 192.168.3.66`，`ping 223.5.5.5` 可通；管理/装包不依赖被占用的 eth2；
- [x] 已把 Modem 移入 `ns-sim1`，改名 `wwan0`，`addr flush` 清掉 `192.168.0.178`；netns 内 `wwan0` UP、无 IP、route 为空；host `eth2` 消失；
- [x] 移动后 host 仍有 `default via 192.168.3.1 dev eth1`，`ping -c 2 223.5.5.5` 0% 丢包（24.08–24.34 ms），host 未断网；
- [x] `wwan0` DHCP 成功：租约 `192.168.0.179/24`，server `192.168.0.1`；netns route `default via 192.168.0.1 dev wwan0`；`ip netns exec ns-sim1 ping -c 2 223.5.5.5` 0% 丢包（53.0/153.5/253.9 ms）；host DNS 已从 `/tmp/r.bak` 恢复；
- [x] `veth-lan1` 在 host，`master br-lan`、`NO-CARRIER`、`link-netns ns-sim1`；`ip netns list`/`ls /run/netns` 均显示 `ns-sim1`；`veth-ns1` 已在 netns 内（host 上 show 不到是正常）；此前 `ip -n` 报错是 `ns-sim1` 的 `1`/字母 `l` 打混；
- [x] `ip -n ns-sim1 addr add 192.168.1.250/24 dev veth-ns1` 报 `Address already assigned`（说明地址已在）；`ip -n ns-sim1 link set veth-ns1 up` 成功，内核日志 `br-lan: port 2(veth-lan1) entered forwarding state`；
- [x] 验证通过：`ip -n ns-sim1 route` 显示 `default via 192.168.0.1 dev wwan0`、`192.168.0.0/24 dev wwan0 src 192.168.0.179`、`192.168.1.0/24 dev veth-ns1 src 192.168.1.250`；Mac `ping 192.168.1.250` 收到 `1.023 ms` 回复；`ip n ns-sim1 addr` 是少打 `-` 的无效命令，不影响；
- [x] netns dnsmasq 已用 `--server=223.5.5.5` 启动；`ip netns exec ns-sim1 nslookup openwrt.org 127.0.0.1` 返回 `64.226.122.113`/IPv6；DNS 走 `wwan0`；
- [x] 配置已重写：`Port 6001`、`Listen 192.168.1.250`、`Allow 192.168.1.210`、`BasicAuth xingtu xingtu`、`PidFile "/tmp/tinyproxy-ns1.pid"`、`LogFile "/tmp/tinyproxy-ns1.log"`；`tinyproxy -c` 启动成功，`cat /tmp/tinyproxy-ns1.pid` → `13566`；`netstat-ltn` 是少空格的命令错误，不是进程问题；
- [x] Mac 代理 HTTP 验证成功：`curl -x http://192.168.1.250:6001 -U xingtu:xingtu http://myip.ipip.net` → `当前 IP：223.160.113.88 来自于：中国 湖南 chinabtn.com`；蜂窝出口链路已通；
- [x] Mac 直连：`curl --noproxy '*' http://myip.ipip.net` → `120.228.1.191`（中国湖南长沙 chinamobile.com）；代理为 `223.160.113.88`（chinabtn.com），两者网络出口不同；
- [x] HTTPS CONNECT：`curl -x http://192.168.1.250:6001 -U xingtu:xingtu https://ifconfig.me/ip` → `223.160.112.88`（HTTP/HTTPS 出口在运营商池内不同属正常；行尾 `%` 是 shell 提示符，不是 IP）；TLS/443 正常；

**通过标准**：Mac 的网线接口有确认的 `192.168.1.x` IP（ARP 有效）；DHCP 池范围已知；`.250–.252` 未被占用；单台 USB 网卡已出现；`ip-full`/`tinyproxy` 可安装。**不修改 J1900 LAN IP/DHCP。**

### Phase 1：安装工具（不改 LAN/DHCP）

- [x] 保持 J1900 LAN `192.168.1.1/24` 与 DHCP 不变（它是 Mac 的网关）；
- [x] `apk update`；
- [x] `apk add ip-full`；
- [x] `apk add tinyproxy`；
- [x] 如 veth 创建失败，`apk add kmod-veth`；
- [x] `ip -br addr` 和 `ip netns` 可用；`tinyproxy` 可执行。

### Phase 2：单出口（ns-sim1）

- [x] 创建 netns/veth/固定 `192.168.1.250`；
- [ ] 禁用 veth IPv6/RA；
- [x] USB 网卡移入 netns，`udhcpc` 取得蜂窝 IP 和默认路由；
- [x] netns 内 `ping 223.5.5.5` 通；
- [x] dnsmasq 监听 `127.0.0.1:53`，解析测试通过；
- [x] tinyproxy 监听 `192.168.1.250:6001`，BasicAuth/Allow Mac；
- [x] Mac `curl` 出口 IP 与宽带不同（HTTP `223.160.113.88`、HTTPS `223.160.112.88`；直连 `120.228.1.191`）；
- [x] 停 tinyproxy → Mac 连接失败（无直连）：`kill 13566` 后 `curl -x ...` 返回 `(7) Failed to connect ... 6001`，未返回任何 IP；重启 tinyproxy 后恢复；
- [ ] tcpdump 确认目标 DNS 走 `usb0`，不走 `br-lan`/宽带。

### Phase 3：3 条出口

- [ ] `ns-sim2`/`192.168.1.251`/`usb1`、`ns-sim3`/`192.168.1.252`/`usb2`；
- [ ] 3 个出口得到 3 个不同公网 IP（多点、双回显服务）；
- [ ] 停/拔 1 条，其他 2 条继续正常；
- [ ] 单条重连后端口/IP 映射仍正确；
- [ ] J1900 CPU/内存/USB 无异常（无 over-current/枚举失败）。

### Phase 4：持久化

- [x] 已生成 line1 持久化脚本：[xingtu-line1.sh](../evidence/IPPOOL-02-xingtu-line1.sh) + [init](../evidence/IPPOOL-02-xingtu-line1.init)；含 netns/veth、Modem 查找、flush 旧 WAN IP、DHCP、dnsmasq、tinyproxy、失败退出；
- [x] J1900 已用无选项 `wget` 下载 `/root/xingtu-line1.sh`（5318 B）与 `/etc/init.d/xingtu-line1`（704 B）；`chmod +x`、`sh -n` 通过；
- [x] 手工运行成功：日志 `2026-10-24 18:21:06 modem already in ns-sim1 as wwan0`、`18:21:11 OK ns=ns-sim1 veth=192.168.1.250/24 proxy=192.168.1.250:6001`；重启前 Mac 代理返回 `223.160.113.88`；
- [x] `/etc/init.d/xingtu-line1 enable` 已执行；
- [x] 重启后验证通过：J1900 启动到 `Please press Enter...`，LAN1 灯正常；Mac en6 `status: active`、`192.168.1.210/24`；`ping 192.168.1.1` 0% 丢包（0.42–0.97 ms）、`ping 192.168.1.250` 0% 丢包（0.44–1.13 ms）；代理返回 `223.160.112.88`（中国湖南 chinabtn.com）；无需手工重建，line1 持久化成功；
- [x] line1 再次验证（2026-10-25 22:34）：`ping .1` 0% 丢包（0.583–0.729 ms）、`ping .250` 0% 丢包（0.721–0.795 ms）、代理 `223.160.114.4`；line1 正常；
- [x] Mac 路由修正完成：Wi-Fi 服务顺序置于 USB 网卡前；`route -n get default` → gateway `192.168.3.1`、interface `en0`；`route -n get 192.168.1.250` → interface `en6`；en6 启用时普通上网正常，代理直连正常；
- [x] line2 设备确认：`usb0` path `1-2.3.2:1.0`、MAC `ba:7b:bb:ec:28:c0`、当前 DOWN/无 IP；与 line1 的 MAC/path 均不同；
- [x] line2 脚本/init 已生成并通过 `sh -n`：[xingtu-line2.sh](../evidence/IPPOOL-02-xingtu-line2.sh)、[init](../evidence/IPPOOL-02-xingtu-line2.init)；已用 Mac HTTP `8765` 提供；
- [ ] line2 手工运行：J1900 配置已通——`usb0` 移入 `ns-sim2` 改名 `wwan0`，DHCP 成功 `192.168.0.106`；`ping 192.168.0.1` 0% 丢包；但 `ping 223.5.5.5` 100% 丢包、`nslookup 223.5.5.5` 超时，tinyproxy 未启动。**结论：新 SIM/随身 WiFi 没有蜂窝数据**（未激活/未注册/APN/信号），不是脚本/DNS 问题；先处理 SIM 数据，恢复后重跑 line2 即可；暂不装 init；

### Phase 5：项目接入与 Chrome profile

- [ ] 双执行单元可行性（2026-10-31 核对）：**现有 `unit-local-mac-02` 是 `local_development`，已在跑真实采集任务**（worker `xingtu-unit-local-mac-02`，日志 `COLLECTING`/`PARTIAL_COMPLETED`），是本机 IP 的正当本地单元。新增 cellular B 因使用代理，必须是 `production_line` + `proxy_server` + `NetworkProof`/probe。**用户已验证平台允许同一星图账号从多个 IP 使用**；但当前项目 schema 是 `execution_units.account_ref` UNIQUE、平台绑定 `(platform, account_ref)` UNIQUE，所以“同账号两个执行单元”需要显式产品决策 + migration/代码变更，不是只加配置；且平台多 IP 已验证不等于两个并发浏览器会话稳定，需先做同账号 A/B 同时在线、只读、无采集的并发验证。`IntakeWorker` 固定 `execution_unit_id`，B 还需独立 collection worker + intake 任务路由；proxy 在 unit JSON；local 直连与 line1 同为移动湖南，IP 多样性弱；未创建 Chrome/profile、未改代码。
- [ ] `.runtime/cellular.env` 0600（3 组 user/pass）；
- [ ] `NetworkProof` + `network_probe_command`（显式代理、禁用环境代理、输出四字段 JSON）；
- [ ] `unit-cellular-01` 配置 + `register-unit` + `production-preflight`；
- [ ] `login` 通过代理启动 Chrome，账号归属人完成短信，ID 精确匹配；
- [ ] `browser-check`/`session-diagnostics` → `READY`；
- [ ] 再复制 02/03；
- [ ] 不启动真实采集。

## 实现记录

- line1（ns-sim1/`192.168.1.250:6001`）已完成并持久化：[xingtu-line1.sh](../evidence/IPPOOL-02-xingtu-line1.sh) 与 [init](../evidence/IPPOOL-02-xingtu-line1.init) 已在 J1900 安装、`enable`，硬关机再上电后自动恢复（`wwan0: renamed from eth2`、`br-lan: port 2(veth-lan1) forwarding`），Mac `en6` 启用时不重跑脚本即可代理出网。2026-10-31 复测：`ping .1/.250` 0% 丢包，代理 `223.160.113.73`（中国移动湖南）。
- 现有本地单元（2026-10-31 核对）：`.runtime/local-main/units/unit-local-mac-02.json` 为 `network_mode=local_development`、`account_ref=xingtu-account-02`、`line_id=local-dev-macos`、profile `.runtime/profiles/unit-local-mac-02`；worker 日志 `collection worker polling xingtu-unit-local-mac-02`，任务到 `COLLECTING`/`PARTIAL_COMPLETED`。**这是可用执行单元，不需要改成 production_line。**
- 双单元结论（2026-10-31）：A 保持 `unit-local-mac-02`/`local_development`；B 必须是**另一个平台账号**（不能复用 A 的 account_ref），并用 `unit-cellular-01`/`production_line` + `proxy_server` + `NetworkProof`/probe + 独立账号/profile。网络层已有两条出口；项目层还需 B 的 unit JSON/注册、B collection worker，以及 intake 任务路由（当前 intake worker 固定 A，直接起两个会争抢同一 intake 队列，需独立队列/调度/显式 unit 分配）。本机与 line1 同为移动湖南，IP 多样性弱。
- line2（ns-sim2/`.251`）脚本/init 已生成并通过 `sh -n`：[xingtu-line2.sh](../evidence/IPPOOL-02-xingtu-line2.sh)、[init](../evidence/IPPOOL-02-xingtu-line2.init)；netns/veth/DHCP 正常，但新 SIM/随身 WiFi 无蜂窝数据（`ping 223.5.5.5` 100% 丢包），tinyproxy 未启动、init 未安装。
- 脚本默认 `PROXY_USER/PROXY_PASS=xingtu`（临时，可用环境变量覆盖），`MODEM_PATH=2-2.1:1.0`、`MODEM_MAC=34:4b:50:00:00:00`；Modem 需插回同一 USB 口，否则按 MAC 兜底。line2/3 复制时需改 NS/veth/LANIP/Modem 标识/端口。
- 已编写施工手册：[IPPOOL-02 施工手册](../evidence/IPPOOL-02-openwrt-build-runbook-2026-10-24.md)。
- 已编写 console 短命令清单：[IPPOOL-02 短命令清单](../evidence/IPPOOL-02-short-commands-2026-10-24.md)；J1900 无 GUI、**只能键盘输入、不能复制、结果拍照**，后续按“一条一条短命令/脚本拉取”执行，不手打长配置。
- 当前拓扑（实机确认）：OpenWrt **25.12.5** x86_64，包管理器 **apk**；J1900 是路由器，WAN `eth2 192.168.0.178/24` → `192.168.0.1`，LAN `br-lan 192.168.1.1/24`；Mac `en6` = `192.168.1.210/24`（LAN1 通、LAN2 不通）。**未改 LAN IP/DHCP**；DHCP 池 `.100–.249`，代理使用池外 `192.168.1.250/251/252:6001`。
- 未改业务代码、执行单元配置与数据库，未创建 Chrome profile，未发起真实采集；上述网络的完整时序见“状态历史”。
- 代理选型：OpenWrt 官方 `tinyproxy`（HTTP BasicAuth），不用 3proxy、不用 SOCKS5 认证。
- P2：netns 故障隔离；不做自动切卡。

## 验证证据

已取得（2026-10-24，用户照片，未复制到仓库）：

| 项 | 实测 |
|---|---|
| OpenWrt | `25.12.5 r33051-f5dae5ece4`，target `x86/64` |
| WAN/默认路由 | `eth2 192.168.0.178/24`，`default via 192.168.0.1` |
| LAN | `br-lan 192.168.1.1/24`；`uci get network.lan.ipaddr` = `192.168.1.1/24` |
| `ip -br addr` | BusyBox `ip` 不支持 `-br`，打印 Usage；需 `ip-full` |
| DHCP/租约 | `dhcp.lan.ignore` → `Entry not found`（默认开启）；`start=100`、`limit=150` → 池 `.100–.249`；`/tmp/dhcp.leases` 为空；`/etc/resolv.conf` = `127.0.0.1`/`::1` |
| Mac IP | `en6` = `192.168.1.210/24`；**换 LAN1 后 `ping 192.168.1.1` 0% 丢包、0.66–0.77 ms**；LAN2 不通，固定用 LAN1；ARP `.210` → 真实 MAC `00:e0:4c:68:03:dc`（br-lan） |
| DNS | `nslookup openwrt.org` 已恢复（`64.226.122.113`/IPv6）；`ip route` 默认路由在（eth1 192.168.3.1 / eth2 192.168.0.1）；`ping 223.5.5.5` 0% 丢包（23.6–24.4 ms）；`udhcpc no lease` warning 不阻塞 |
| 包可用性 | 25.12.5 feed 有 `tinyproxy 1.11.1-r3`、`ip-full 6.18.0-r2`、`kmod-veth 6.12.94-r1` |
| 安装/接口 | `apk update` 成功（11250 packages）；`ip-full 6.18.0-r2`；`tinyproxy 1.11.1`；`br-lan` 端口 `eth0`；ZTE `19d2:1405` `Driver=cdc_ether`；`eth2` MAC `34:4b:50:00:00:00`、USB `2-2.1:1.0`，曾误持 WAN `192.168.0.178`；已移入 `ns-sim1` 改名 `wwan0`；`wwan0` DHCP `192.168.0.179/24`、default via `192.168.0.1`；netns `ping 223.5.5.5` 0% 丢包（53–254 ms）；`veth-ns1 192.168.1.250/24`、`veth-lan1` master `br-lan`、port 2 forwarding；`ip -n ns-sim1 route` 默认仍走 `wwan0`；Mac `ping 192.168.1.250` 1.023 ms；netns dnsmasq `--server=223.5.5.5` 启动，`nslookup openwrt.org 127.0.0.1` 返回 `64.226.122.113`/IPv6；tinyproxy 配置修正 `PidFile "..."`/`LogFile "..."` 后启动成功，pid `13566`；Mac 代理 HTTP `223.160.113.88`（chinabtn.com）、HTTPS `223.160.112.88`；直连 `120.228.1.191`（chinamobile.com）；代理与直连不同，TLS/443 正常；`kill 13566` 后 Mac `curl -x ...` 返回 `(7) Failed to connect ... 6001`，无 IP；重启 tinyproxy 后恢复 |
| 持久化安装 | 下载/`chmod`/`sh -n` 通过；手工日志 `18:21:11 OK`；`enable` 后 `reboot`；硬关机再上电后 J1900 启动，LAN1 灯正常；启动日志见 `wwan0: renamed from eth2`、`br-lan: port 2(veth-lan1) forwarding`；Mac `en6`=`status: active`、`192.168.1.210/24`；`ping 192.168.1.1` 0% 丢包（0.42–0.97 ms）、`ping 192.168.1.250` 0% 丢包（0.44–1.13 ms）；代理 `223.160.112.88`；line1 持久化通过。2026-10-25 22:34 再次验证 `ping .1` 0.583–0.729 ms、`ping .250` 0.721–0.795 ms、代理 `223.160.114.4`；Mac Wi-Fi 服务顺序置顶后 `route default` en0/192.168.3.1、`route .250` en6，普通上网/代理均正常 |
| line2 发现 | `lsusb` 两个 ZTE `19d2:1405`；新接口 **`usb0`** path `1-2.3.2:1.0`、MAC `ba:7b:bb:ec:28:c0`；line2 脚本/init 已生成并通过 `sh -n`。首次运行：`usb0` 移入 `ns-sim2` 改名 `wwan0`，DHCP 成功 `192.168.0.106`；`ping 192.168.0.1` 0% 丢包，但 `ping 223.5.5.5` 100% 丢包、`nslookup 223.5.5.5` 超时；结论新 SIM/随身 WiFi 无蜂窝数据，tinyproxy 未启动 |
| 双单元评估 | 2026-10-31 line1 复测：`ping .1` 0% 丢包（3.567–7.266 ms）、`ping .250` 0% 丢包（0.609–0.903 ms）、代理 `223.160.113.73`（中国移动湖南）。现有 A：`unit-local-mac-02`/`local_development`/`xingtu-account-02`/profile，worker 日志 `COLLECTING`/`PARTIAL_COMPLETED`；A 是有效本地单元。用户已验证平台允许同账号多 IP；但当前 schema `execution_units.account_ref` UNIQUE、`(platform, account_ref)` UNIQUE，同账号两单元需产品决策 + migration/代码变更；并发会话稳定性/任务路由未验证。B 需 production_line + proxy + proof/probe + profile + collection worker；本机与 line1 同为移动湖南，IP 多样性弱；未创建 Chrome/profile |

尚无出口代理实机证据。当前只有文档与上述实机照片记录：

- [IPPOOL-01 可行性评估](../evidence/IPPOOL-01-openwrt-multi-ip-feasibility-2026-10-22.md)（方案 C、Playwright 代理行为、官方包索引核验）。
- [IPPOOL-02 短命令清单](../evidence/IPPOOL-02-short-commands-2026-10-24.md)（实际环境版）。
- 后续每完成一个 Phase，在本节记录：日期、命令、实际输出摘要、PASS/FAIL/BLOCKED、脱敏日志/截图。不得把“命令执行成功”当成“出口独立/性能达标”。

## 交接信息

**当前状态/暂停**：

1. 用户 2026-10-25 23:50 今日暂停，J1900 可 `poweroff`；line1 已持久化，开机自动恢复。
2. line2 的 J1900 配置/脚本已完成，但新 SIM/随身 WiFi 无蜂窝数据（`ping 223.5.5.5` 100% 丢包）；line2 init **未安装/未 enable**，明天不会自动启动。
3. line3、Chrome profile/ExecutionUnit 未开始；真实采集未授权。

**下一步（恢复时）**：

1. J1900 上电，等 60–120 秒；Mac `en6` 若丢失 `192.168.1.210/24`，重设静态；验证 `.1`/`.250` + line1 代理。
2. 先让第 2 台随身 WiFi 自己恢复蜂窝数据（SIM 激活/APN/信号）；手机连它 WiFi 能上网后，再在 J1900 跑 `/root/xingtu-line2.sh`，查 `/tmp/xingtu-line2.log`，Mac 测 `.251:6001`。
3. line2 手工通过后再安装 init/enable/重启；然后按同法 line3 `.252`；不要重跑 line1，不要一次插两台。
4. 3 出口都验证后再做 Chrome profile/ExecutionUnit；真实采集需另行授权。

**硬件选型建议（2026-10-25）**：

- line2/3 优先继续用 **ZTE MF79U 同款/相近固件**，兼容性风险最低；核心条件是 `19d2:1405` + `cdc_ether` + USB tethering 可用。
- 若换型号，先单台验证 `lsusb`/`lsusb -t`/新接口/DHCP/出网，再批量买；不要买纯 USB Wi-Fi 网卡。
- IP 多样性由 **SIM/运营商/APN/位置**决定，不由随身 WiFi 型号决定；优先不同运营商，同运营商同池可能拿到相邻 IP。
- 多台设备用**带供电 USB HUB**；每台标签记录 SIM/运营商、USB 口、MAC、netns；同型号也可能同默认 MAC，必须按 USB path 区分。
- 当前 line2 设备已枚举为 `19d2:1405`/`cdc_ether`，兼容性已证明；无数据是 SIM 侧问题，不是型号不兼容。

**安全提醒**：

- 不把 root 密码、Wi-Fi 密码、代理密码、IMEI/ICCID/手机号发聊天；
- 代理只监听 LAN IP，BasicAuth + Allow Mac/第二台电脑，不做 WAN；
- 改 LAN IP 前备份，确保有 console 回滚。

## 状态历史

- 2026-10-24T20:44:00+08:00：新建 → 进行中；编写施工手册，等待 J1900 Phase 0 只读盘点；未改网络/代码/配置，未创建 Chrome profile。
- 2026-10-24T20:50:00+08:00：补充 console 短命令约束与[短命令清单](../evidence/IPPOOL-02-short-commands-2026-10-24.md)；J1900 无 GUI，后续按“一条一条短命令/脚本拉取”执行；仍未改网络/代码/配置。
- 2026-10-24T20:54:00+08:00：进一步确认 J1900 只能键盘输入、不能复制、结果需拍照；短命令清单增加“第一阶段只做 5 条只读命令”（版本/接口/路由/LAN IP/DHCP），减少输入与回传负担。
- 2026-10-24T21:13:00+08:00：Phase 0 部分完成（照片实测）：OpenWrt 25.12.5 x86_64、apk；J1900 是路由器，WAN `eth2 192.168.0.178`→`192.168.0.1`，LAN `br-lan 192.168.1.1/24`；Mac 网线接 LAN；`ip -br` 不支持；DHCP 命令少打 `dhcp`。计划修正为 **不改 LAN/DHCP**，netns 使用 `192.168.1.201–203:6001`。仍未修改配置。
- 2026-10-24T21:23:00+08:00：DHCP/租约/DNS 输出确认：`dhcp.lan.ignore` 未设置（默认开启），`start=100`、`limit=150` → 池 `.100–.249`；`/tmp/dhcp.leases` 为空（Mac 可能静态 IP）；`/etc/resolv.conf` = `127.0.0.1`/`::1`。`.201–.203` 与池冲突，待用 ARP 找 Mac IP 后改用池外地址/静态保留。仍未修改配置。
- 2026-10-24T21:27:00+08:00：ARP/DNS 输出确认：`192.168.1.210` 的 ARP 为 **Flags=0x0、HW=00:00:00:00:00:00**，是未完成条目，**不能据此确认 Mac IP**；`.250–.252` 无有效 ARP 条目；dnsmasq 在运行；`ping 223.5.5.5` 0% 丢包（41–258 ms）；`nslookup openwrt.org` → `REFUSED`，host DNS 上游异常，需先修 DNS 再 `apk update`。代理 IP 计划改为 `192.168.1.250/251/252:6001`。仍未修改配置。
- 2026-10-24T21:29:00+08:00：修正：Mac IP 尚未确认，需要在 Mac 上执行 `ifconfig | grep "inet "`，确认网线接口是否有 `192.168.1.x`；若没有，先设 DHCP 或静态 `192.168.1.210/24`、网关 `192.168.1.1`，再继续。
- 2026-10-24T21:37:00+08:00：Mac 输出确认：`192.168.3.132`（Wi-Fi）、`11.11.183.81`（VPN/点对点），**没有 `192.168.1.x`**；J1900 ARP `.210` 仍为未完成。结论：以太网口未配置或网线插在 WAN 口/未连通；下一步在 Mac 确认 LAN 口并给以太网设 DHCP/静态 `.210`，再回 J1900 看 ARP。仍未修改配置。
- 2026-10-24T21:51:00+08:00：Mac 网卡/服务确认：`en6` = “USB 10/100/1000 LAN”，拿到 `169.254.74.217`（DHCP 失败的自分配地址）；LAN2 黄灯闪，物理链路通。下一步给 `en6` 设静态 `192.168.1.210/24`、网关 `192.168.1.1`，`ping 192.168.1.1`；若不通，检查 LAN2 是否在 `br-lan`（`uci show network | grep ports`）。仍未修改配置。
- 2026-10-24T22:04:00+08:00：Mac 已设 `192.168.1.210`，但掩码为 `255.255.0.0`（/16，`ifconfig` 0xffff0000），需改为 `255.255.255.0`（/24）；J1900 上执行的是 `ping 192.168.11.1`（多一个 1），不是 `192.168.1.1`，故不能证明 Mac→J1900 LAN 通。下一步：改掩码，Mac ping 192.168.1.1，J1900 看 ARP。仍未修改 J1900 配置。
- 2026-10-24T22:12:00+08:00：Mac 掩码已改为 `255.255.255.0`，`ifconfig` 显示 `192.168.1.210/24`、`broadcast 192.168.1.255`；但 `ping 192.168.1.1` 返回 `Host is down`、100% 丢包。结论：二层链路未通，疑 `en6` link 或 LAN2 未加入 `br-lan`。下一步先换 LAN1；仍不通则查 `ifconfig en6 | grep status`、`route -n get 192.168.1.1`、`uci show network | grep ports`、`ls /sys/class/net`。仍未修改 J1900 配置。
- 2026-10-24T22:16:00+08:00：换到 **LAN1** 后 `ping 192.168.1.1` 0% 丢包（0.66/0.72/0.77 ms），Mac→J1900 LAN 二层已通；LAN2 不通，后续固定 LAN1。Mac `en6` = `192.168.1.210/24`。下一步：J1900 `cat /proc/net/arp` 确认真实 MAC；然后修 DNS 上游、装 `apk` 包、插单台 USB。仍未修改 J1900 配置。
- 2026-10-24T22:24:00+08:00：ARP 确认 `192.168.1.210` → `00:e0:4c:68:03:dc`（br-lan）；`nslookup openwrt.org 223.5.5.5` 可解析（`64.226.122.113`/IPv6），说明外网 DNS 可用；本机 dnsmasq 仍 `REFUSED`。下一步给 dnsmasq 加 `223.5.5.5` 上游，验证后 `apk update`/`ip-full`/`tinyproxy`。仍未修改 J1900 配置。
- 2026-10-24T22:31:00+08:00：已执行第一次配置修改：`uci add_list dhcp.@dnsmasq[0].server=223.5.5.5` + `uci commit dhcp` + dnsmasq restart；`nslookup openwrt.org` 现返回 `64.226.122.113`/IPv6。restart 时出现 `udhcpc: no lease, failing`，需先确认 `ip route` 仍有默认路由、`ping 223.5.5.5` 仍通，再 `apk update`/`apk add ip-full`/`apk add tinyproxy`。
- 2026-10-24T22:34:00+08:00：`ip route` 确认仍有默认路由（eth1 `192.168.3.1`、eth2 `192.168.0.1`），默认优先 eth1；J1900 同时接 192.168.3.0/24（eth1）和 192.168.0.0/24（eth2）。照片三处显示 `ping 233.5.5.5`，用户认为输入是 `223.5.5.5`；不再用该 ping 判断，直接以 `apk update` 作为联网/仓库验证。
- 2026-10-24T22:38:00+08:00：用户重跑 `ping -c 2 223.5.5.5` 0% 丢包（23.6–24.4 ms），WAN/默认路由正常；`udhcpc no lease` warning 不阻塞。下一步 `apk update`、`apk add ip-full`、`apk add tinyproxy`，然后插单台 USB 随身 WiFi 验证接口。仍未安装工具。
- 2026-10-24T22:43:00+08:00：工具安装完成：`apk update` 成功（11250 packages）；`ip-full 6.18.0-r2`；`tinyproxy 1.11.1-r3`；`ip -br addr` 可用。但 IPv6 换行使 `eth1`/`br-lan`/`eth2` 归属不清；下一步 `ip -4 -br addr` 确认 LAN/WAN 后再建 netns/veth；同时插单台 USB 随身 WiFi 看接口。
- 2026-10-24T22:48:00+08:00：`ip -4 -br addr` 确认 `br-lan 192.168.1.1/24`（Mac LAN 网关）、`eth1 192.168.3.66/24`、`eth2 192.168.0.178/24`；`tinyproxy 1.11.1`。`bridge` 命令不存在，下一步用 `ls /sys/class/net/br-lan/brif` 确认 LAN1 端口，再插单台 USB 随身 WiFi。未建 netns/veth。
- 2026-10-24T22:54:00+08:00：`br-lan/brif` → `eth0`，LAN1 在网桥内；`tinyproxy 1.11.1`。插入 ZTE `19d2:1405`（USB ID 库 MF823D；DD-WRT 表归 ECM），但 `ls /sys/class/net` 无新增接口，说明缺 CDC ECM 驱动；下一步 `apk add kmod-usb-net-cdc-ether`，再看新接口；若仍无，再评估 cdc-ncm/qmi-wwan/usb-modeswitch。未建 netns/veth。
- 2026-10-24T22:59:00+08:00：`apk add kmod-usb-net-cdc-ether` 成功，但仍无 `usb0/eth3/wwan0`；`dmesg | tail -20` 只有 r8169 eth0/eth1 link 事件。下一步查 `lsusb -t`、`lsmod | grep cdc`、`dmesg | grep -i usb | tail -30`；若模块未加载再 `modprobe cdc_ether`；不要盲装其他驱动。
- 2026-10-24T23:17:00+08:00：`lsusb -t` 确认 ZTE `19d2:1405` If 0/1 `Driver=cdc_ether`；`lsmod` 有 `cdc_ether`/`usbnet`；`dmesg` 显示 `19d2:1225` 存储 → `19d2:1405` ECM，并注册 **`cdc_ether ... eth2`**；不是没有接口，而是接口名为 `eth2`，与 WAN 冲突。dmesg 另有多次 disconnect/re-register（9757s/9768s），需观察。下一步先确认 `eth2` 是 Modem 还是 WAN（`ip -4 -br addr`、`ip route`、`cat /sys/class/net/eth2/address`、`readlink /sys/class/net/eth2/device`），确认前不要重命名/移动。未建 netns/veth。
- 2026-10-24T23:23:00+08:00：确认 `eth2` 为 USB Modem：MAC `34:4b:50:00:00:00`、device `2-2.1:1.0`；但 `eth2` 同时拥有 WAN 的 `192.168.0.178/24` 和 `default via 192.168.0.1`，说明 Modem 抢名后继承了 WAN 静态配置。Host 默认仍有 `via 192.168.3.1 dev eth1`，上网不依赖被占用的 eth2。下一步把 `eth2` 移入 `ns-sim1`、改名 `wwan0`、DHCP；移动后确认 host 仍能 `ping 223.5.5.5`，若断则回滚。未建 netns。
- 2026-10-24T23:35:00+08:00：已建 `ns-sim1`，把 `eth2` 移入并改名 `wwan0`、up、flush；netns `wwan0` UP 无 IP、route 空。Host `eth2` 消失，仍 `default via 192.168.3.1 dev eth1`，`ping 223.5.5.5` 0% 丢包（24.08–24.34 ms）。下一步 `lo up` + `wwan0` DHCP（最小脚本，不覆盖 host resolv.conf）；未起 tinyproxy。
- 2026-10-24T23:55:00+08:00：首次自定义 DHCP 脚本失败：用户输入了反引号 `` ` `` 而非单引号 `'`，shell 执行了反引号内容，`printf` 报 usage，`/tmp/u.sh` 为空。改为不写脚本：备份 `/etc/resolv.conf` 后直接跑默认 `udhcpc`，再恢复；随后 `ip -n ns-sim1 addr/route`、`ping 223.5.5.5` 验证。未起 tinyproxy。
- 2026-10-25T00:09:00+08:00：`wwan0` DHCP 成功：租约 `192.168.0.179/24`，server `192.168.0.1`，default via `192.168.0.1 dev wwan0`；netns 内 `ping 223.5.5.5` 0% 丢包（53.0/153.5/253.9 ms）；host DNS 已从 `/tmp/r.bak` 恢复。下一步建 veth `192.168.1.250/24` 接 `br-lan`，确认 Mac 可 ping 通，再起 dnsmasq/tinyproxy。
- 2026-10-25T00:12:00+08:00：`ip link add veth-lan1 type veth peer name veth-ns1` 报 `Error: unknown device type`；判断内核缺 `veth` 模块。下一步 `apk add kmod-veth`，`lsmod | grep veth` 确认后重试；未创建 veth，未起 tinyproxy。
- 2026-10-25T00:25:00+08:00：`veth-lan1` 创建成功并已 `master br-lan`（内核日志 `br-lan: port 2(veth-lan1)`）；但 `ip -n ns-sim1 ...` 报 `Cannot open network namespace "ns-sim1": No such file or directory`。疑似 `ns-sim1` 的 `1` 与字母 `l` 打混，或 netns 已消失。下一步先查 `ip netns list`、`ls /run/netns`、`ip -4 -br addr`、`ip link show veth-lan1/veth-ns1`，不要重建/删除 veth。
- 2026-10-25T00:28:00+08:00：确认 `ns-sim1` 存在（`ip netns list`/`ls /run/netns`）；`veth-lan1` 在 host、`master br-lan`、`NO-CARRIER`、`link-netns ns-sim1`；`veth-ns1` 已在 netns 内，host 上 show 不到正常；此前 `ip -n` 报错是 `1`/`l` 打混。下一步 netns 内给 `veth-ns1` 加 `192.168.1.250/24` 并 up，Mac ping 验证。未起 tinyproxy。
- 2026-10-25T00:34:00+08:00：`ip -n ns-sim1 addr add 192.168.1.250/24 dev veth-ns1` 报 `Address already assigned`（地址已在）；`ip -n ns-sim1 link set veth-ns1 up` 成功；内核日志 `br-lan: port 2(veth-lan1) entered forwarding state`。下一步 `ip -n ns-sim1 addr/route` 确认默认路由仍走 `wwan0`，Mac `ping 192.168.1.250`。未起 tinyproxy。
- 2026-10-25T00:38:00+08:00：`ip -n ns-sim1 route` 确认 `default via 192.168.0.1 dev wwan0`、`192.168.0.0/24 dev wwan0 src 192.168.0.179`、`192.168.1.0/24 dev veth-ns1 src 192.168.1.250`；Mac `ping 192.168.1.250` 收到 `1.023 ms` 回复。`ip n ns-sim1 addr` 是少打 `-` 的无效命令。下一步 netns 内起 dnsmasq（127.0.0.1:53 → 223.5.5.5），再起 tinyproxy。未起代理。
- 2026-10-25T00:45:00+08:00：检查 dnsmasq 命令，结构正确，但截图 `--server=233.5.5.5` 是错地址，应为 `223.5.5.5`；尚未确认是否执行。若已误启动，用 `/tmp/dnsmasq-ns1.pid` kill 后重跑；改正后再 `nslookup openwrt.org 127.0.0.1`。未起 tinyproxy。
- 2026-10-25T00:48:00+08:00：dnsmasq 已用 `--server=223.5.5.5` 启动；`ip netns exec ns-sim1 nslookup openwrt.org 127.0.0.1` 返回 `64.226.122.113`/IPv6，netns DNS 走 `wwan0`。下一步写 tinyproxy 配置（Port 6001/Listen 192.168.1.250/Allow 192.168.1.210/BasicAuth）并在 ns-sim1 启动；从 Mac 验证出口 IP。
- 2026-10-25T01:08:00+08:00：`/tmp/tp.conf` 已有 `Port 6001`、`listen 192.168.1.250`、`Allow 192.168.1.210`、`BasicAuth xingtu xingtu`、`pidFile /tmp/tinyproxy-ns1.pid`；`LogFile` 行因把路径写成 `/tmp/tp/conf` 未写入（BasicAuth 首次失败后重跑成功，无重复）。下一步补 `LogFile`、启动 tinyproxy、Mac curl 验证；未启动代理。
- 2026-10-25T01:16:00+08:00：tinyproxy 启动报 `ERROR: Syntax error on line 5`；第 5 行 `pidFile /tmp/tinyproxy-ns1.pid` 未加双引号。根据 tinyproxy 配置解析，`PidFile`/`LogFile` 的路径必须是 `"..."`。下一步重写配置为 `PidFile "/tmp/tinyproxy-ns1.pid"`、`LogFile "/tmp/tinyproxy-ns1.log"`，再启动并验证。
- 2026-10-25T01:30:00+08:00：配置已重写并启动成功，`/tmp/tinyproxy-ns1.pid` → `13566`；`netstat-ltn` 少空格导致 `exec of "netstat-ltn" failed`，不是进程问题。下一步从 Mac `curl -x http://192.168.1.250:6001 -U xingtu:xingtu http://myip.ipip.net`，与直连 IP 对比；未创建 Chrome profile。
- 2026-10-25T01:32:00+08:00：Mac 代理 HTTP 验证成功：`curl -x http://192.168.1.250:6001 -U xingtu:xingtu http://myip.ipip.net` → `当前 IP：223.160.113.88 来自于：中国 湖南 chinabtn.com`；说明 veth/tinyproxy/dnsmasq/wwan0 全链路通。下一步 `curl --noproxy '*' http://myip.ipip.net` 对比直连，并测 HTTPS CONNECT；未创建 Chrome profile。
- 2026-10-25T01:34:00+08:00：直连 `curl --noproxy '*' http://myip.ipip.net` → `120.228.1.191`（中国湖南长沙 chinamobile.com）；代理 HTTPS `https://ifconfig.me/ip` → `223.160.112.88`，CONNECT/TLS 正常；代理与直连出口不同，第 1 个蜂窝出口网络层完成。下一步做“停 tinyproxy → Mac 连接失败（无直连回退）”和持久化；再确认第 2/3 台设备。
- 2026-10-25T01:42:00+08:00：无直连回退验证通过：`kill 13566` 后 Mac `curl -x http://192.168.1.250:6001 -U xingtu:xingtu http://myip.ipip.net` 返回 `curl: (7) Failed to connect ... port 6001`，未返回任何 IP；重新 `ip netns exec ns-sim1 tinyproxy -c /tmp/tp.conf` 后代理恢复 `223.160.113.88`、HTTPS `223.160.112.88`。第 1 个出口网络层完成；下一步持久化脚本 + 确认第 2/3 台随身 WiFi/SIM。
- 2026-10-25T01:47:00+08:00：已生成 line1 持久化脚本/init（`docs/evidence/IPPOOL-02-xingtu-line1.sh`、`.init`，`sh -n` 通过）；Mac 临时 HTTP `http://192.168.1.210:8765/` 已可拉取。脚本覆盖 netns/veth、Modem 查找、flush 旧 WAN IP、DHCP、dnsmasq、tinyproxy，失败即退出。下一步 J1900 拉取、手工跑通、enable、重启验证；用户确认另有 2 台随身 WiFi+SIM，line1 持久化后复制 line2/3。
- 2026-10-25T02:03:00+08:00：J1900 首次拉取失败：`wget` 的 `-O` 被输入成数字 `-0`，报 `unrecognized option: 0`；两个脚本均未下载，`chmod`/`sh -n` 因文件不存在失败。下一步用大写 `-O` 重试，并先用 `ls -l /root/xingtu-line1.sh /etc/init.d/xingtu-line1` 确认文件存在。
- 2026-10-25T02:09:00+08:00：第二次 `wget -O` 仍被识别为 `-0`，报同样错误，文件仍未下载。改用无选项 `wget`：`cd /root` 后 `wget http://192.168.1.210:8765/xingtu-line1.sh`；`cd /etc/init.d` 后 `wget .../xingtu-line1.init`，再 `mv xingtu-line1.init xingtu-line1`；随后 `ls -l` 确认再 chmod/`sh -n`。
- 2026-10-25T02:12:00+08:00：无选项 `wget` 的 URL 写成 `http://192.168.1.210:8765?xingtu-line1.sh`（`?` 而非 `/`），报 `Failed to send request: Operation not permitted`，文件未下载。下一步用正确 `/` 重试；若仍失败，先从 J1900 `ping 192.168.1.210`，再查 Mac 防火墙/Python 8765 入站。
- 2026-10-25T02:20:00+08:00：校正 URL 后下载成功：`/root/xingtu-line1.sh` 5318 B、`/etc/init.d/xingtu-line1` 704 B；`chmod +x`、`sh -n` 通过。下一步手工运行脚本，检查 `/tmp/xingtu-line1.log` 的 `OK` 和 Mac 代理；通过后再 enable/重启验证。
- 2026-10-25T02:23:00+08:00：用户报告手工运行/日志/Mac 代理 1–3 步正常（日志末尾和代理 IP 待补存证）。下一步在 J1900 `/etc/init.d/xingtu-line1 enable`，再 `reboot`；重启后等 60–120 秒，从 Mac ping/curl 验证自动恢复。
- 2026-10-25T02:33:00+08:00：手工运行日志确认 `18:21:06 modem already in ns-sim1 as wwan0`、`18:21:11 OK ns=ns-sim1 veth=192.168.1.250/24 proxy=192.168.1.250:6001`；`enable` 已执行并 `reboot`。重启后 Mac ping 的源地址是 `192.168.3.132`（Wi-Fi），不是 `en6 192.168.1.210`，报 `192.168.1.3 Destination Host Unreachable`；这是 Mac 以太网口未恢复，不是持久化结论。下一步等 J1900 启动完成、Mac 恢复 `192.168.1.210/24` 后重测；若 J1900 启动完成仍失败，再看 `/tmp/xingtu-line1.log`。
- 2026-10-25T02:35:00+08:00：Mac `ifconfig | grep "inet "` 只有 `192.168.3.132`（Wi-Fi）/`11.11.183.81`（VPN），en6 无 `192.168.1.210`；确认不是 J1900 代理失败，而是 Mac 网线口未恢复。下一步重新给“USB 10/100/1000 LAN”设 `192.168.1.210/24`、网关 `192.168.1.1`，先 ping `192.168.1.1`，再 ping `.250`/curl；仍失败再查 J1900 启动日志。
- 2026-10-25T02:36:00+08:00：`ifconfig en6` 显示 `media: autoselect (none)`、`status: inactive`，说明无网线载波；`networksetup -setmanual` 虽成功，但链路 down 时 IP 不生效。下一步检查 J1900 是否上电/启动、网线是否在 LAN1、LAN1 灯是否亮，重插 USB-C 网卡/网线；链路 active 后再设静态并测 `.1`/`.250`。
- 2026-10-25T02:40:00+08:00：用户确认 J1900 **LAN1 绿灯不亮**，物理链路未建立；Mac en6 仍 inactive。下一步：确认 J1900 电源/屏幕是否已启动；检查网线两端、USB-C 网卡指示灯、换线；可把网线插 LAN2 仅看链路灯（LAN2 尚未加入 br-lan，不能直接上网）；LAN1 灯亮且 en6 active 后，再设静态/ping。
- 2026-10-25T02:44:00+08:00：照片确认 J1900 屏幕仍停在 `reboot` 的关机日志（`EXT4-fs ... unmounting filesystem`），没有启动/登录提示；电源灯亮但系统未回来，LAN1 无 link。LAN1/LAN2 都插了线。下一步硬关机再上电，等 OpenWrt 启动；确认 Mac 在 LAN1、上游在 LAN2；启动后 LAN1 灯亮、en6 active 再测。
- 2026-10-25T02:51:00+08:00：硬关机再上电后 J1900 已启动到 `Please press Enter to activate this console.`（正常）；LAN1 绿灯+黄灯闪，`r8169 eth0: Link is Up`；启动日志见 `cdc_ether ... wwan0: renamed from eth2`、`br-lan: port 2(veth-lan1) entered forwarding state`，说明开机脚本已执行。下一步按回车进 console，`cat /tmp/xingtu-line1.log` 查新 `OK`/`ERROR`；Mac en6 应 active，设 `192.168.1.210/24` 后测 `.1`/`.250`/curl。
- 2026-10-25T02:56:00+08:00：Mac `en6` 已 `status: active`、`media: 1000baseT full-duplex`、`inet 192.168.1.210/24`；J1900 LAN1 灯正常；下一步在 Mac 跑 `ping 192.168.1.1`、`ping 192.168.1.250`、代理 `curl`，并回 J1900 看 `/tmp/xingtu-line1.log` 新 `OK`。
- 2026-10-25T02:58:00+08:00：line1 持久化验证通过：重启后 Mac `en6` active/`192.168.1.210`；`ping .1` 0% 丢包（0.418–0.973 ms）、`ping .250` 0% 丢包（0.440–1.128 ms）；代理返回 `223.160.112.88`。下一步 line2：保持 line1 不动，只插第 2 台到不同 USB 口，记录 USB path；不重跑 line1 脚本；再建 `ns-sim2`/`.251`。
- 2026-10-25T03:00:00+08:00：用户今日暂停，新增设备明天继续；J1900 可正常 `poweroff`，line1 自启已保留。明日恢复：上电等 60–120 秒、Mac en6 重设 `.210`、验证 line1；再只插第 2 台，记录 USB path 后建 `ns-sim2`/`.251`；仍不启动真实采集。
- 2026-10-25T03:05:00+08:00：J1900 `poweroff` 日志到 `EXT4-fs (sda1): unmounting filesystem`、`[sda] Stopping disk`；磁盘已停止，屏幕仍亮是 halt 后未切电源/显示输出。可长按电源键 5–10 秒断电，文件系统已安全卸载；今日结束，明日按交接恢复。
- 2026-10-25T22:34:00+08:00：恢复后 line1 再次验证通过：`ping .1` 0% 丢包（0.583–0.729 ms）、`ping .250` 0% 丢包（0.721–0.795 ms）、代理 `223.160.114.4`。发现启用 en6 时因其网关 `192.168.1.1` 成为默认路由，Mac 普通上网断；停用 en6 即恢复。下一步调整 Mac 服务顺序/网关，使默认走 Wi-Fi、仅 192.168.1.0/24 走 en6；第 2 台随身 WiFi 已插入扩展坞（黄灯待适配），随后做 line2 发现。
- 2026-10-25T22:40:00+08:00：Mac 服务顺序已把 Wi-Fi 置顶；`route -n get default` → `192.168.3.1`/`en0`，`route -n get 192.168.1.250` → `en6`；en6 启用时普通上网和代理均正常。下一步 J1900 跑 `lsusb`/`lsusb -t`/`ls /sys/class/net`/`readlink`/`ip -4 -br addr` 做 line2 发现，记录 USB path；不要重跑 line1。
- 2026-10-25T22:45:00+08:00：line2 发现：`lsusb` 见两个 ZTE `19d2:1405`（Dev 012/018），`lsusb -t` 两个 `cdc_ether`；新接口为 `usb0`（无 IPv4，未抢 eth2）；`readlink -f /sys/class/net/eth*/device` 因 BusyBox 只接受单文件报 Usage。下一步 `readlink -f /sys/class/net/usb0/device`、`cat /sys/class/net/usb0/address`、`ip link show usb0` 记录路径，再建 `ns-sim2`/`.251`；不重跑 line1。
- 2026-10-25T22:51:00+08:00：line2 path/MAC 确认：`usb0` path `1-2.3.2:1.0`、MAC `ba:7b:bb:ec:28:c0`、state DOWN/无 IP；与 line1 不同。已生成 line2 脚本/init（`ns-sim2`/`192.168.1.251`/tinyproxy），`sh -n` 通过，Mac HTTP `8765` 已提供；下一步 J1900 下载并手工运行，查 `/tmp/xingtu-line2.log`，Mac 验证 `.251` 和两个不同公网 IP。
- 2026-10-25T22:58:00+08:00：line2 首次运行：脚本下载 4759 B、`sh -n` 通过；`usb0` 移入 `ns-sim2` 改名 `wwan0`，DHCP 成功 `192.168.0.106`（server `192.168.0.1`）；随后 `ERROR: DNS check failed`，tinyproxy 未启动。下一步在 ns-sim2 内测 `ping 192.168.0.1`、`ping 223.5.5.5`、`nslookup 223.5.5.5`，区分 SIM 无数据 vs dnsmasq；不装 init/不重启。
- 2026-10-25T23:04:00+08:00：line2 定位完成：`ping 192.168.0.1` 0% 丢包；`ping 223.5.5.5` 100% 丢包；`nslookup ... 223.5.5.5` 超时。结论：J1900 line2 配置/ DHCP 正常，新 SIM/随身 WiFi 无蜂窝数据（未激活/未注册/APN/信号）；不装 init，先处理 SIM 数据，恢复后重跑 line2。
- 2026-10-25T23:50:00+08:00：用户今日暂停；J1900 可 `poweroff`。line1 已持久化；line2 配置/脚本就绪但 SIM 无数据，line2 init 未安装；line3/Chrome/采集未开始。恢复时先开机验证 line1，再让第 2 台随身 WiFi 恢复数据后手工跑 line2。
- 2026-10-25T23:55:00+08:00：硬件选型建议：line2/3 优先同款 ZTE MF79U（`19d2:1405`/`cdc_ether`）；换型号先单台验证再批量；IP 多样性由 SIM/运营商决定，不由型号决定；多台用带供电 HUB，按 USB path/MAC 标签区分。
- 2026-10-26T22:40:00+08:00：文档随本轮审查提交 `2b0275e`，经 merge `bb29801` 合入 `main` 并推送；网络/设备状态未变化（line1 已持久化、line2 待 SIM 恢复数据），保持进行中。
- 2026-10-31T12:15:00+08:00：line1 复测：`ping .1` 0% 丢包（3.567–7.266 ms）、`ping .250` 0% 丢包（0.609–0.903 ms）、代理 `223.160.113.73`（中国移动湖南），正常。双单元评估：网络层两条独立出口可用；代码 `UnitConfig` 支持 `production_line` proxy/NetworkProof/Playwright 代理认证，但 `local_development` 仅本地验证，`IntakeWorker` 固定 unit，`register_unit` 不存 proxy，双单元需双 worker/调度；本机与 line1 同为移动湖南，IP 多样性弱。未改代码/配置，未创建 Chrome。
- 2026-10-31T12:35:00+08:00：按用户说明核对现有部署：`unit-local-mac-02` 配置为 `network_mode=local_development`、`account_ref=xingtu-account-02`、`line_id=local-dev-macos`；worker `xingtu-unit-local-mac-02` 日志有 `COLLECTING`/`PARTIAL_COMPLETED`。确认本机 IP 的 local_development 是当前有效执行单元，不是临时占位；之前“仅本地验证、不能作为执行单元”的表述不准确。A 保持不动；B 用 production_line + 代理 + 独立 worker，intake 需任务路由。
- 2026-10-31T13:29:00+08:00：用户目标确认：B = line1 蜂窝 IP + Chrome B + 账号 a（与 A 相同）。核对 schema：`execution_units.account_ref` UNIQUE、`execution_unit_platform_bindings(platform, account_ref)` UNIQUE；当前代码不能直接建同账号 B，需显式改模型。
- 2026-10-31T13:32:00+08:00：用户补充已实测“同一星图账号可被多个 IP 使用”。更正判断：平台侧不禁止多 IP；项目侧仍是 account_ref 唯一约束，同账号两单元必须走产品决策 + migration/代码变更。平台多 IP ≠ 两个并发浏览器会话稳定；需先做同账号 A/B 同时在线、只读、无采集的并发验证，再决定是否解除唯一约束；当前未改代码/未创建 Chrome。
