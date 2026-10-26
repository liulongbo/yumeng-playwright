# IPPOOL-02 短命令清单（实际环境版，2026-10-24）

- 适用：当前这台 J1900 OpenWrt，**没有 LuCI，只能键盘逐条输入，不能复制，结果拍照**
- 原则：一次一条；每条尽量 <60 字符；不要整段粘贴；复杂配置后续用 `wget`/`scp` 拉脚本
- 不要发：root 密码、Wi-Fi 密码、IMEI、ICCID、手机号、代理密码

---

## 一、从照片确认的实机情况（以此为准）

| 项 | 实际值 |
|---|---|
| 系统 | OpenWrt **25.12.5**，x86_64，r33051-f5dae5ece4 |
| 包管理器 | **apk**（25.12 起替代 opkg，不要再用 opkg） |
| J1900 角色 | **路由器**，不是旁路主机 |
| WAN | `eth2`，`192.168.0.178/24`，默认网关 `192.168.0.1` |
| LAN | `br-lan`，`192.168.1.1/24` |
| Mac | `en6`（“USB 10/100/1000 LAN”）拿到 `169.254.74.217`（DHCP 失败的自分配地址）；LAN2 黄灯闪、链路通；无 `192.168.1.x` |
| DHCP | `dhcp.lan.ignore` 未设置（默认开启）；`start=100`，`limit=150` → 池 `.100–.249`；`/tmp/dhcp.leases` 为空 |
| DNS | `/etc/resolv.conf`：`127.0.0.1`、`::1`；dnsmasq 在运行，但 `nslookup openwrt.org` → **REFUSED** |
| 外网 | `ping 223.5.5.5` 0% 丢包，RTT 41–258 ms |
| `ip` 命令 | BusyBox 版，**不支持 `-br`**，也没有 `ip netns add`；需装 `ip-full` |
| 可用包 | `tinyproxy 1.11.1-r3`、`ip-full 6.18.0-r2`、`kmod-veth` 在 25.12.5 feed 中可用 |

**重要修正：**

- 不改 J1900 的 LAN IP，也不关它的 DHCP；它现在是 Mac 的网关，改了会断网。
- 代理出口使用池外 **`192.168.1.250 / .251 / .252:6001`**；当前 DHCP 池 `.100–.249`，ARP 中没有这三个地址的有效条目，计划使用；若 Mac 确认后出现冲突再调整。
- 之前手册里“J1900 改成 192.168.3.2 旁路主机”的步骤**不适用当前拓扑，不要执行**。
- `ip -br addr` 报 Usage 不是系统坏，是 BusyBox `ip` 不支持 `-br`；装 `ip-full` 后可用。

---

## 二、第二轮结果（2026-10-24）

已确认：

- `cat /proc/net/arp`：有一条 `192.168.1.210`，但 **Flags=0x0、HW=00:00:00:00:00:00**，是未完成 ARP，不能确认 Mac IP；`.250–.252` 没有有效条目。
- `ps | grep dnsmasq`：dnsmasq 在运行。
- `ping -c 2 223.5.5.5`：0% 丢包，RTT 41–258 ms，WAN 出网正常。
- `nslookup openwrt.org`：**REFUSED**，本机 dnsmasq 的上游 DNS 异常；`apk update` 会受影响。
- `/tmp/dhcp.leases` 为空：Mac 可能是静态 IP，不影响；代理用 `.250–.252`。

## Mac 已通 LAN1（2026-10-24 22:16）

- `en6` = “USB 10/100/1000 LAN”，`192.168.1.210/24`。
- 网线从 **LAN2 换到 LAN1** 后，`ping 192.168.1.1`：0% 丢包，0.66–0.77 ms。
- 结论：**LAN1 通，LAN2 不通；后续固定用 LAN1**，不要再用 LAN2。
- Mac 的 Wi-Fi/VPN 可以继续用；`192.168.1.210` 只加在 `en6` 上，访问 `192.168.1.250` 会走网线。

下一步回 J1900 执行：

```sh
cat /proc/net/arp
```

期望 `192.168.1.210` 显示真实 MAC。确认后进入 DNS 修复。

## 现在只做 DNS 修复（4 条，会改 dnsmasq 上游）

已确认：

- ARP `192.168.1.210` → `00:e0:4c:68:03:dc`（br-lan）。
- DNS 修复已执行：`uci add_list dhcp.@dnsmasq[0].server=223.5.5.5` + `uci commit dhcp` + dnsmasq restart。
- `nslookup openwrt.org` 现在返回 `64.226.122.113`/IPv6，DNS 已通。
- restart 时出现 `udhcpc: no lease, failing`，但不阻塞：`ip route` 默认路由仍在（eth1 `192.168.3.1` / eth2 `192.168.0.1`）。
- 已重跑 `ping -c 2 223.5.5.5`：**0% 丢包，23.6–24.4 ms**，WAN 正常。
- 之前照片里的 `ping 233.5.5.5` 是错地址，已确认不影响。

现在进入 `apk` 安装：

```sh
apk update
```

```sh
apk add ip-full
```

```sh
apk add tinyproxy
```

> 这次只改 DNS 上游，不改 LAN IP、不改 DHCP 池、不关 DHCP。  
> 回滚：`uci del_list dhcp.@dnsmasq[0].server=223.5.5.5`，再 `uci commit dhcp`、重启 dnsmasq。

**拍照方式**：命令和输出拍在同一张画面；一条一屏；不用抄。

---

## 三、下一步（DNS 修好后）

### 3.1 工具安装（已完成）

已执行并成功：

- `apk update`：11250 packages；
- `apk add ip-full`：`ip-full 6.18.0-r2`，`/sbin/ip -> /usr/libexec/ip-full`；
- `apk add tinyproxy`：`tinyproxy 1.11.1-r3`；
- `ip -br addr` 已能运行。

### 3.2 确认 IPv4 接口/网桥（已完成）

- `br-lan` = `192.168.1.1/24`（Mac 的 LAN 网关）
- `eth1` = `192.168.3.66/24`
- `eth2` = `192.168.0.178/24`
- `ls /sys/class/net/br-lan/brif` → `eth0`，LAN1 在 `br-lan` 网桥内
- `tinyproxy -v` → `1.11.1`

### 3.3 USB 已识别但没有网络接口

当前 `lsusb`：

```text
19d2:1405 ZTE WCDMA Technologies MSM
```

USB ID 库把 `19d2:1405` 记为 ZTE MF823D，DD-WRT 表把它归为 **ECM**。

已执行：

```sh
apk add kmod-usb-net-cdc-ether
```

现在 `lsusb -t` 显示 `19d2:1405` If 0/1 `Driver=cdc_ether`；`lsmod` 有 `cdc_ether`/`usbnet`；`dmesg` 显示设备从 `19d2:1225` 存储模式切到 `19d2:1405`，并注册：

```text
cdc_ether ... eth2: register 'cdc_ether' ... ZTE CDC Ethernet Device
```

已确认 `eth2` 就是 Modem：

- MAC：`34:4b:50:00:00:00`
- device：`2-2.1:1.0`（USB）
- 但它同时有 `192.168.0.178/24` 和默认路由 `via 192.168.0.1`：**Modem 抢了 WAN 的接口名，netifd 又把 WAN 静态 IP 配到了它上面**。

Host 目前仍有 `default via 192.168.3.1 dev eth1`，所以管理/装包不受影响；但 Modem 拿的不是蜂窝 IP，不能直接做代理。

现在把 Modem 移入 netns（这是第一次真正的网络拓扑改动）：

```sh
ip netns add ns-sim1
```

```sh
ip link set eth2 netns ns-sim1
```

```sh
ip -n ns-sim1 link set eth2 name wwan0
```

```sh
ip -n ns-sim1 link set wwan0 up
```

查看 netns：

```sh
ip -n ns-sim1 addr
```

```sh
ip -n ns-sim1 route
```

然后回 host 检查：

```sh
ip -4 -br addr
```

```sh
ip route
```

```sh
ping -c 2 223.5.5.5
```

- 期望 host 仍能 ping 通（走 `eth1 192.168.3.1`）。
- 如果 host 断网，回滚：
  ```sh
  ip -n ns-sim1 link set wwan0 netns 1
  ip link set wwan0 name eth2
  ```

> 移动后 host 的 `192.168.0.178`/`default via 192.168.0.1` 会消失；这是预期，因为那个 IP 本来就被 Modem 误占了。  
> 不要现在启动 tinyproxy；Modem 还没有自己的 DHCP 地址。

### 3.4 netns 内 DHCP（已完成）

结果：

- `wwan0` 拿到 `192.168.0.179/24`，server `192.168.0.1`；
- route：`default via 192.168.0.1 dev wwan0`、`192.168.0.0/24 dev wwan0`；
- `ping 223.5.5.5`：0% 丢包（53.0/153.5/253.9 ms）；
- host DNS 已从 `/tmp/r.bak` 恢复。

### 3.5 veth 接 br-lan（下一步）

先建 veth、挂到 `br-lan`，并给 netns 侧 `192.168.1.250/24`。

先装 veth 模块（首次执行报 `Error: unknown device type`，说明内核缺模块）：

```sh
apk add kmod-veth
```

```sh
lsmod | grep veth
```

确认有 `veth` 后，再执行：

```sh
ip link add veth-lan1 type veth peer name veth-ns1
```

```sh
ip link set veth-lan1 master br-lan
```

```sh
ip link set veth-lan1 up
```

```sh
ip link set veth-ns1 netns ns-sim1
```

```sh
ip -n ns-sim1 addr add 192.168.1.250/24 dev veth-ns1
```

```sh
ip -n ns-sim1 link set veth-ns1 up
```

查看 netns：

```sh
ip -n ns-sim1 addr
```

```sh
ip -n ns-sim1 route
```

已确认并完成：

- `ip netns list` / `ls /run/netns` 都有 `ns-sim1`；
- `veth-lan1` 在 host、`master br-lan`、`link-netns ns-sim1`；
- `veth-ns1` 已在 netns 内，host 上 `ip link show veth-ns1` 显示不存在是正常的；
- `addr add 192.168.1.250/24` 报 `Address already assigned`，说明地址已经在；
- `link set veth-ns1 up` 成功，内核日志 `br-lan: port 2(veth-lan1) entered forwarding state`，veth 已开始转发。

现在只需确认 `veth-ns1` 地址/默认路由，然后 Mac ping。

期望：

- `veth-ns1` 有 `192.168.1.250/24`；
- route 仍有 `default via 192.168.0.1 dev wwan0`；
- 多出 `192.168.1.0/24 dev veth-ns1`。

然后**在 Mac 上** ping：

```sh
ping -c 2 192.168.1.250
```

- 通 → 下一步做 netns DNS + tinyproxy。
- 不通 → 拍照发我；先查 `br-lan` 端口/防火墙，不要起 tinyproxy。

> 如果 `ip link add ... type veth` 报错，先：
> ```sh
> apk add kmod-veth
> ```
> 再重试。
>
> 这一步只通二层，不起代理；netns 的 DNS 仍是 host 的 127.0.0.1，下一节再处理。

### 3.6 netns DNS（已完成）

`ip netns exec ns-sim1 nslookup openwrt.org 127.0.0.1` 返回：

```text
Address: 64.226.122.113
Address: 2a03:b0c0:3:d0::1a51:c001
```

说明 netns 的 dnsmasq 已生效，DNS 走 `wwan0`。

### 3.7 tinyproxy（下一步）

在 host 上写配置（用单引号 `'`，不是反引号 `` ` ``）：

```sh
echo 'Port 6001' >/tmp/tp.conf
```

```sh
echo 'Listen 192.168.1.250' >>/tmp/tp.conf
```

```sh
echo 'Allow 192.168.1.210' >>/tmp/tp.conf
```

```sh
echo 'BasicAuth xingtu xingtu' >>/tmp/tp.conf
```

```sh
echo 'Timeout 600' >>/tmp/tp.conf
```

```sh
echo 'PidFile "/tmp/tinyproxy-ns1.pid"' >>/tmp/tp.conf
```

```sh
echo 'LogFile "/tmp/tinyproxy-ns1.log"' >>/tmp/tp.conf
```

> **`PidFile` / `LogFile` 的路径必须加双引号 `"..."`。**  
> 如果不加，tinyproxy 会报 `Syntax error on line 5`（第 5 行是 PidFile）。  
> 当前文件里已有未加引号的旧行时，最稳妥是重写整个文件：第一条用 `>`，后面都用 `>>`。

检查：

```sh
cat /tmp/tp.conf
```

启动：

```sh
ip netns exec ns-sim1 tinyproxy -c /tmp/tp.conf
```

已启动成功：`cat /tmp/tinyproxy-ns1.pid` → `13566`。

检查监听/进程（`netstat` 和 `-ltn` 之间必须有空格；写成 `netstat-ltn` 会被当成一个命令）：

```sh
ip netns exec ns-sim1 netstat -ltn | grep 6001
```

```sh
cat /tmp/tinyproxy-ns1.pid
```

然后**在 Mac 上**测试：

```sh
curl -x http://192.168.1.250:6001 -U xingtu:xingtu http://myip.ipip.net
```

- 返回公网 IP/归属地 → 代理通；与 Mac 直连的出口 IP 不同，才算独立出口。
- `407` → BasicAuth 配置/密码不对。
- `403` → `Allow`/来源 IP 不对。
- `502`/超时 → netns DNS 或 `wwan0` 出网问题。

实测已通过：

```text
当前 IP：223.160.113.88  来自于：中国 湖南   chinabtn.com
```

再对比 Mac 直连（`--noproxy '*'` 确保不走终端代理）：

```sh
curl --noproxy '*' http://myip.ipip.net
```

再测 HTTPS CONNECT（Playwright/星图必须）：

```sh
curl -x http://192.168.1.250:6001 -U xingtu:xingtu https://ifconfig.me/ip
```

- 代理 IP 与直连不同 → 第 1 个出口独立；
- HTTPS 也返回 IP → CONNECT/TLS 正常，可以做 Chrome profile。

实测结果：

```text
HTTP 代理：223.160.113.88（中国湖南 chinabtn.com）
Mac 直连：120.228.1.191（中国湖南长沙 chinamobile.com）
HTTPS 代理：223.160.112.88（CONNECT/TLS 正常）
```

HTTP/HTTPS 代理地址在运营商池内不同属正常；与直连不同即出口独立。

“无直连回退”验证已通过：

```sh
kill 13566
```

Mac 上：

```sh
curl -x http://192.168.1.250:6001 -U xingtu:xingtu http://myip.ipip.net
```

返回：

```text
curl: (7) Failed to connect to 192.168.1.250 port 6001 ... Couldn't connect to server
```

没有返回任何 IP，说明不会回退直连。重新启动后恢复：

```sh
ip netns exec ns-sim1 tinyproxy -c /tmp/tp.conf
```

> `BasicAuth xingtu xingtu` 是临时本地账号密码；先验证链路，后续再换强密码。  
> 看到 IP 后再创建 Chrome profile；不要先登录平台。

### 3.8 line1 持久化（下一步）

脚本已生成：

- `docs/evidence/IPPOOL-02-xingtu-line1.sh`
- `docs/evidence/IPPOOL-02-xingtu-line1.init`

Mac 临时 HTTP：`http://192.168.1.210:8765/`

> **以下拉取/安装命令都在 J1900 上执行，不是在 Mac 上。**  
> Mac 没有 `wget`/`uclient-fetch`；在 Mac 上执行会报 `command not found`。Mac 只用 `curl` 测代理。

在 J1900 上拉取（**不要用 `-O`**，避免 `O/0` 歧义）：

> URL 的 `8765` 后面必须是 **`/`**，不是 `?`：  
> `http://192.168.1.210:8765/xingtu-line1.sh`  
> 写成 `?xingtu-line1.sh` 会报 `Failed to send request: Operation not permitted`。  
> 若改成 `/` 后仍 EPERM，先在 J1900 `ping 192.168.1.210`，再查 Mac 防火墙是否允许 Python 8765 入站。

```sh
cd /root
```

```sh
wget http://192.168.1.210:8765/xingtu-line1.sh
```

```sh
cd /etc/init.d
```

```sh
wget http://192.168.1.210:8765/xingtu-line1.init
```

```sh
mv xingtu-line1.init xingtu-line1
```

确认文件存在：

```sh
ls -l /root/xingtu-line1.sh /etc/init.d/xingtu-line1
```

```sh
chmod +x /root/xingtu-line1.sh /etc/init.d/xingtu-line1
```

```sh
sh -n /root/xingtu-line1.sh
```

实测已通过：`/root/xingtu-line1.sh` 5318 B、`/etc/init.d/xingtu-line1` 704 B；`chmod +x`、`sh -n` 均正常。

先手工跑一次（会重启 dnsmasq/tinyproxy，Mac 代理会短暂断开）：

```sh
/root/xingtu-line1.sh
```

```sh
cat /tmp/xingtu-line1.log
```

手工运行日志已确认：

```text
2026-10-24 18:21:06 modem already in ns-sim1 as wwan0
2026-10-24 18:21:11 OK ns=ns-sim1 veth=192.168.1.250/24 proxy=192.168.1.250:6001
```

`enable` 已执行并 `reboot`。

重启后注意：**Mac 的以太网口可能暂时没有恢复 `192.168.1.210/24`**。如果 `ping 192.168.1.250` 的源地址显示 `192.168.3.132`（Wi-Fi），不要判持久化失败；先确认：

```sh
ifconfig | grep "inet "
```

还应确认 en6 有载波：

```sh
ifconfig en6
```

必须是 `status: active`。如果是 `status: inactive`、`media: autoselect (none)`，说明**没有网线载波**；先检查 J1900 是否已上电/启动、网线是否插在 LAN1、LAN1 灯是否亮，重插 USB-C 网卡/网线。

已确认：硬关机再上电后，J1900 启动到 `Please press Enter to activate this console.`，LAN1 绿灯+黄灯闪；启动日志已见 `wwan0: renamed from eth2`、`br-lan: port 2(veth-lan1) forwarding`。

按一下回车进入 console，然后查启动脚本日志：

```sh
cat /tmp/xingtu-line1.log
```

应看到新的 `OK`；如果最后是 `ERROR`，先发日志，不要重跑。

Mac 端实测已恢复：`en6` `status: active`、`media: 1000baseT full-duplex`、`inet 192.168.1.210/24`。现在在 Mac 跑：

```sh
ping -c 2 192.168.1.1
```

```sh
ping -c 2 192.168.1.250
```

```sh
curl -x http://192.168.1.250:6001 -U xingtu:xingtu http://myip.ipip.net
```

如果 `.1` 通、`.250`/curl 也通，line1 持久化成功。

实测已通过：重启后 `ping .1` 0% 丢包（0.42–0.97 ms）、`ping .250` 0% 丢包（0.44–1.13 ms）、代理 `223.160.112.88`。

2026-10-25 22:34 再次验证：`ping .1` 0.583–0.729 ms、`ping .250` 0.721–0.795 ms、代理 `223.160.114.4`。

**Mac 路由注意**：启用 en6 后，如果它的网关 `192.168.1.1` 成为默认路由，Mac 普通上网会断。处理：

- 系统设置 → 网络 → 服务顺序，把 **Wi-Fi 拖到 USB 10/100/1000 LAN 前面**；或
- 移除 en6 的网关，只保留 `192.168.1.210/24` 直连。

确认：

```sh
route -n get default
```

默认应走 Wi-Fi；实测已确认：

```text
default → gateway 192.168.3.1, interface en0
192.168.1.250 → interface en6
```

再看：

```sh
route -n get 192.168.1.250
```

应走 `en6`。这样普通上网和代理互不影响。

**2026-10-25 23:50 今日暂停**：J1900 可正常 `poweroff`。line1 已持久化；line2 配置/脚本已就绪，但新 SIM/随身 WiFi 无蜂窝数据（`ping 223.5.5.5` 100% 丢包），line2 init **未安装**。

恢复时：

1. J1900 上电，等 60–120 秒；
2. Mac 检查 `en6` 是否恢复 `192.168.1.210/24`，没有就重设；
3. `ping .1`、`ping .250`、line1 代理 curl；
4. 先让第 2 台随身 WiFi 自己恢复数据（手机连它 WiFi 能上网）；
5. 再跑 `/root/xingtu-line2.sh`，查 `/tmp/xingtu-line2.log`，Mac 测 `.251:6001`；
6. line2 手工通过后再安装 init/enable。

> `poweroff` 到 `[sda] Stopping disk` 后屏幕仍亮是正常的（halt 未切电源/显示）；磁盘已停止，可长按电源键 5–10 秒断电。

下一步 line2（只插第 2 台，不要动 line1，不要重跑 line1 脚本）：

```sh
lsusb -t
```

```sh
ls /sys/class/net
```

```sh
readlink -f /sys/class/net/eth*/device
```

```sh
ip -4 -br addr
```

记录新接口的 USB path（例如 `2-2.2:1.0`），再建 `ns-sim2` / `192.168.1.251`。ZTE MAC 可能相同，line2 必须按 USB path 区分。

实测新接口是 **`usb0`**，没有 IPv4，也没有抢 `eth2`；`readlink -f /sys/class/net/eth*/device` 因 BusyBox 一次只接受一个文件而报 Usage。改用单文件：

```sh
readlink -f /sys/class/net/usb0/device
```

```sh
cat /sys/class/net/usb0/address
```

```sh
ip link show usb0
```

实测：path `1-2.3.2:1.0`、MAC `ba:7b:bb:ec:28:c0`、`usb0` DOWN/无 IP。line2 脚本已生成并通过 `sh -n`：

- [xingtu-line2.sh](IPPOOL-02-xingtu-line2.sh)
- [xingtu-line2.init](IPPOOL-02-xingtu-line2.init)
- Mac HTTP：`http://192.168.1.210:8765/xingtu-line2.sh`

J1900 下载并手工运行：

```sh
cd /root
```

```sh
wget http://192.168.1.210:8765/xingtu-line2.sh
```

```sh
chmod +x /root/xingtu-line2.sh
```

```sh
sh -n /root/xingtu-line2.sh
```

```sh
/root/xingtu-line2.sh
```

```sh
cat /tmp/xingtu-line2.log
```

期望最后：

```text
OK ns=ns-sim2 veth=192.168.1.251/24 proxy=192.168.1.251:6001
```

首次实测：`usb0` 移入 `ns-sim2`、DHCP 成功 `192.168.0.106`，但随后 `ERROR: DNS check failed`，tinyproxy 未启动。先定位：

```sh
cat /tmp/xingtu-line2-dnscheck
```

```sh
ip netns exec ns-sim2 ping -c 3 192.168.0.1
```

```sh
ip netns exec ns-sim2 ping -c 3 223.5.5.5
```

```sh
ip netns exec ns-sim2 nslookup openwrt.org 223.5.5.5
```

- `192.168.0.1` 通、`223.5.5.5` 不通 → 新 SIM 没有注册/数据，查随身 WiFi 的信号/APN/激活状态；
- `223.5.5.5` 通、`nslookup 223.5.5.5` 失败 → DNS 被拦或 SIM 仅允许部分流量；
- `223.5.5.5` 和 `nslookup 223.5.5.5` 都通、只有 `127.0.0.1` 失败 → ns 内 dnsmasq 没起来/没监听。

实测（2026-10-25 23:04）：

```text
ping 192.168.0.1      0% packet loss
ping 223.5.5.5        100% packet loss
nslookup ... 223.5.5.5  connection timed out
```

结论：J1900 的 line2 netns/veth/DHCP 都正常，**新 SIM/随身 WiFi 没有蜂窝数据**。先处理 SIM 激活/注册/APN/信号；恢复后重跑 `/root/xingtu-line2.sh` 即可，不需要改脚本。

Mac 验证：

```sh
ping -c 2 192.168.1.251
```

```sh
curl -x http://192.168.1.251:6001 -U xingtu:xingtu http://myip.ipip.net
```

同时再测 line1，确认两个公网 IP 不同。line2 通过前不要装 init/enable，也不要在 line2 运行时重跑 line1。

如果 J1900 启动完成、Mac 以太网也正常，但代理仍失败，再查 J1900：

```sh
cat /tmp/xingtu-line1.log
```

> 若 `wget` 不可用，用 `uclient-fetch -O <目标> <URL>`。  
> 脚本默认 `xingtu/xingtu`，Modem 需插回同一 USB 口（脚本也会按 MAC 兜底）。  
> 脚本失败会退出，不会启动代理或回退直连。

### 3.9 单条出口（等接口确认后）

```text
netns ns-sim1
veth veth-lan1 / veth-ns1
192.168.1.250:6001
usb0（以实际接口名为准）
tinyproxy BasicAuth
```

配置不手打：由我在 Mac 生成 `xingtu-line1.sh`，J1900 用两条短命令拉取：

```sh
wget -O /tmp/l1.sh http://<Mac_IP>:8000/xingtu-line1.sh
sh /tmp/l1.sh
```

或：

```sh
scp xingtu-line1.sh root@192.168.1.1:/tmp/l1.sh
```

> 脚本先在 Mac 上审阅，再执行；不要在 console 里手打几十行 tinyproxy/dnsmasq 配置。

---

## 四、现在不要做的事

- 不要改 `network.lan.ipaddr`；
- 不要关 `dhcp.lan`（Mac 还要靠它）；
- 不要用 `opkg`（25.12 用 `apk`）；
- 不要用 `192.168.3.x`；
- 不要一次插 3 台随身 WiFi；
- 不要发密码/IMEI/ICCID。

**当前未修改任何配置；上面 5 条都是只读。**
