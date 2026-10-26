# IPPOOL-02 施工手册：OpenWrt 3 路蜂窝出口 + tinyproxy（2026-10-24 更新；初稿 2026-10-23）

- 状态：进行中；Phase 0 部分完成（系统/拓扑已确认，DHCP/租约/USB 待补）
- 目标：在 J1900 OpenWrt 上建立 3 个独立蜂窝出口，每个出口固定一个局域网 IP:6001，通过 HTTP BasicAuth 提供给 Mac（以及可选的第二台电脑）
- 当前硬件：J1900/OpenWrt、3 张 SIM、3 台 USB 随身 WiFi、带供电 HUB、Mac
- 当前账号：3 个独立星图账号（已有，未登录验证）
- 当前授权：只做网络搭建与网络层验证；**不做真实星图采集**（用户明确当前不需要）
- 重要：本手册的命令基于 OpenWrt 24.x + `ip-full` + `tinyproxy` + `dnsmasq` 的通用行为；**未在你的 J1900 实机上执行过**。每个阶段都有检查点，未通过不要进入下一步。
- **console 限制：** 本机没有 LuCI，只能逐条输入短命令；本手册的整段代码**不要直接粘贴**到 console。日常盘点请用[短命令清单](IPPOOL-02-short-commands-2026-10-24.md)；复杂配置由 Mac 生成脚本，J1900 用 `wget`/`scp` 拉取后执行。
- **2026-10-24 实机修正（必读）：** 当前 J1900 是**路由器**：WAN `eth2 192.168.0.178/24` → `192.168.0.1`；LAN `br-lan 192.168.1.1/24`；Mac 网线接 LAN。**不要执行 §0/§2 的 `192.168.3.2` 旁路主机改法。** 不改 LAN/DHCP；netns 用 `192.168.1.201–203:6001`。OpenWrt 25.12.5 使用 **apk**，不是 opkg。实际步骤以[实际环境短命令清单](IPPOOL-02-short-commands-2026-10-24.md)为准；本手册中所有 `192.168.3.x` 段落仅作通用参考。

---

## 0. 先明确目标拓扑

### 0.1 推荐拓扑：J1900 作为“旁路代理主机”

```text
主路由 192.168.3.1（继续做网关/DHCP）
  │
  ├─ Mac 192.168.3.132
  ├─ J1900 192.168.3.2（旁路主机，DHCP 关闭）
  │    ├─ netns ns-sim1 → veth 192.168.3.201:6001 → SIM1/随身WiFi1
  │    ├─ netns ns-sim2 → veth 192.168.3.202:6001 → SIM2/随身WiFi2
  │    └─ netns ns-sim3 → veth 192.168.3.203:6001 → SIM3/随身WiFi3
  └─ 可选：第二台电脑（加入 tinyproxy Allow）
```

- J1900 不作为主路由，不改主路由的网关/DHCP；
- J1900 的 LAN 口接主 LAN，管理地址 `192.168.3.2/24`，默认网关 `192.168.3.1`；
- J1900 自己的 DHCP 服务关闭，避免和主路由冲突；
- 主路由 DHCP 池必须避开 `.2` 和 `.201–.203`（例如池是 `.100–.200`，或给这四个地址做静态保留）；
- 每个 netns 只有一条默认路由（对应 USB 网卡），没有主 LAN 默认路由，所以断线时不会回落宽带；
- tinyproxy 只监听 netns 的 LAN IP，Mac 直接访问，不做 DNAT/端口转发。

### 0.2 如果你现在不是这个拓扑

先不要改，先执行 §1 盘点，把 `ip -br addr`、`ip route`、`uci show network`、`uci show dhcp` 发回来。以下情况需要调整：

- J1900 就是主路由（192.168.3.1）：不能把它改成旁路主机，否则全家断网；需要另定方案；
- J1900 当前是 192.168.1.1/24，且 LAN 口接在主 LAN 上：需要先把 LAN 改成 192.168.3.2 或加地址别名，并关 DHCP；
- J1900 只有 WAN 口接主 LAN、LAN 是另一个网段：Mac 无法直接访问 netns IP，需要路由/DNAT；先发拓扑再定；
- 主路由开了 AP/客户端隔离：Mac 可能 ping 不通 `192.168.3.201`，需要关隔离或 Mac 走网线。

### 0.3 IP 规划（按当前 Mac 网段）

| 用途 | IP | 说明 |
|---|---|---|
| 主路由 | `192.168.3.1` | 现有网关，不改 |
| Mac | `192.168.3.132` | 当前实测；建议在主路由做 DHCP 保留 |
| J1900 管理 | `192.168.3.2` | 旁路主机地址；需主路由池外/保留 |
| 出口 1 代理 | `192.168.3.201:6001` | netns `ns-sim1` |
| 出口 2 代理 | `192.168.3.202:6001` | netns `ns-sim2` |
| 出口 3 代理 | `192.168.3.203:6001` | netns `ns-sim3` |

> 如果主路由 DHCP 池包含 `.201–.203`，先改成池外或做静态保留；否则地址冲突会让代理随机失效。

---

## 1. Phase 0：只读盘点（先做这个，不改配置）

### 1.1 进入 J1900

任选一种：

- 接显示器和键盘，登录 OpenWrt console；
- 从主路由 DHCP 客户端列表找到 J1900 的 IP，然后 `ssh root@<J1900_IP>`；
- 如果不知道 IP：在 J1900 console 执行 `ip -br addr` / `uci get network.lan.ipaddr`。

> 不要把 root 密码、Wi-Fi 密码、IMEI、ICCID、手机号发到聊天里。需要贴输出时，MAC 可只保留前 3 段，其余用 `xx` 代替。

### 1.2 系统/网络/包盘点（复制整段执行）

```sh
cat /etc/openwrt_release
uname -a
cat /proc/cpuinfo | sed -n '1,30p'
free -m
df -h
ip -br link
ip -br addr
ip route show table all
uci show network
uci show dhcp
uci show firewall
cat /etc/resolv.conf
opkg list-installed | grep -E 'tinyproxy|ip-full|kmod-veth|dnsmasq|usb|rndis|cdc|qmi|mbim|option|usb-modeswitch|socat'
```

重点看：

- OpenWrt 版本/内核、是否 x86_64；
- `ip -br addr` 里 LAN 是不是 `br-lan`、当前 IP 是多少；
- `ip route` 默认网关是不是 `192.168.3.1`；
- `uci show dhcp` 里 LAN DHCP 是否开启；
- `opkg` 是否已有 `tinyproxy`、`ip-full`、`kmod-veth`；
- `/etc/resolv.conf` 是不是 `nameserver 127.0.0.1`（这会影响 tinyproxy 的 DNS 路径）。

### 1.3 USB 设备盘点（先只插 1 台随身 WiFi + 1 张 SIM）

```sh
lsusb
lsusb -t
dmesg | grep -iE 'usb|rndis|cdc|qmi|mbim|option|ttyUSB|over-current|reset|disconnect' | tail -80
ip -br link
ip -br addr
```

重点看：

- `lsusb` 是否看到随身 WiFi 的 VID:PID；
- 是否先出现 CD-ROM/存储设备（需要 `usb_modeswitch`）；
- 是否出现 `usb0`/`eth1`/`wwan0` 等网络接口；
- `dmesg` 是否有 over-current、枚举失败、反复 disconnect；
- 接口是否有 MAC 冲突/重复（多台同型号常见）。

### 1.4 网络命名空间/工具自检（只读/临时测试）

```sh
command -v ip
ip netns list
ip netns add nstest && ip netns del nstest && echo NETNS_OK
ip link add vtest type veth peer name vtest2 && ip link del vtest && echo VETH_OK
command -v tinyproxy || echo NO_TINYPROXY
command -v dnsmasq || echo NO_DNSMASQ
command -v udhcpc || echo NO_UDHCPC
```

- `ip netns` 报错 → 安装 `ip-full`；
- `VETH_OK` 失败 → 安装 `kmod-veth`；
- `NO_TINYPROXY` → `opkg update && opkg install tinyproxy`；
- `NO_DNSMASQ` → 通常 OpenWrt 自带，检查 `opkg install dnsmasq`。

### 1.5 盘点通过标准

- [ ] 知道 J1900 的管理 IP、LAN 接口名、默认网关、DHCP 是否开启；
- [ ] 知道主路由 DHCP 池，`.2/.201/.202/.203` 不在池内或有保留；
- [ ] 知道 OpenWrt 版本、`ip-full`/`kmod-veth`/`tinyproxy`/`dnsmasq` 可用；
- [ ] 单台随身 WiFi 已出现网络接口（记录接口名/MAC/驱动）；
- [ ] `/etc/resolv.conf` 内容已记录；
- [ ] 没有 over-current/反复枚举。

**未通过不要继续改网络。** 把 §1.2–§1.4 输出（脱敏）发回，我按实际接口名给下一步命令。

---

## 2. Phase 1：J1900 旁路主机与依赖

> 只有确认 J1900 是“旁路主机”、不是主路由，才做本节。改 LAN IP 可能断开 SSH，请用 console 或确认能回滚。

### 2.1 备份并设置管理地址

```sh
cp /etc/config/network /etc/config/network.bak.$(date +%s)
cp /etc/config/dhcp /etc/config/dhcp.bak.$(date +%s)

uci set network.lan.ipaddr='192.168.3.2'
uci set network.lan.netmask='255.255.255.0'
uci set network.lan.gateway='192.168.3.1'
uci set network.lan.dns='223.5.5.5'
uci commit network

uci set dhcp.lan.ignore='1'
uci commit dhcp

/etc/init.d/network restart
/etc/init.d/dnsmasq restart
```

- 如果 `uci show network` 显示 LAN 不是 `br-lan` 或还有 WAN 占用同一网段，先不要执行；
- 改完用 Mac `ping 192.168.3.2`、`ssh root@192.168.3.2` 确认；
- 如果 SSH 断了，用 console 回滚：`cp /etc/config/network.bak.<时间> /etc/config/network && reboot`。

### 2.2 确认 J1900 能上网/装包

```sh
ping -c 3 192.168.3.1
ping -c 3 223.5.5.5
opkg update
opkg install tinyproxy ip-full
# 如果 VETH_OK 失败：
opkg install kmod-veth
```

- 如果 `opkg` 找不到 tinyproxy：`opkg search tinyproxy`，检查 feed；没有就停止，不要用 3proxy 替代本手册；
- 如果 `ip-full` 与系统 `ip` 冲突：OpenWrt 的 `ip-full` 会替换 BusyBox `ip`，正常；
- 安装完重新执行 §1.4 自检。

---

## 3. Phase 2：第一条出口（ns-sim1 + tinyproxy）

> 先只做 1 条。不要一上来做 3 条；先证明单条能出网、能认证、DNS 不泄漏、断线不回落。

以下假设：

- J1900 LAN 接口/网桥：`br-lan`；
- 单台随身 WiFi 网络接口：`usb0`（实际以 `ip -br link` 为准，替换所有 `usb0`）；
- 出口 1：`ns-sim1`、`veth-lan1`/`veth-ns1`、`192.168.3.201`、端口 `6001`；
- Mac：`192.168.3.132`。

### 3.1 建立目录和 udhcpc 脚本

```sh
mkdir -p /etc/xingtu
cat >/etc/xingtu/udhcpc.script <<'EOF'
#!/bin/sh
case "$1" in
  deconfig)
    ip addr flush dev "$interface"
    ;;
  bound|renew)
    ip addr flush dev "$interface"
    ifconfig "$interface" "$ip" netmask "$subnet" up 2>/dev/null || ip addr add "$ip/24" dev "$interface"
    [ -n "$router" ] && ip route replace default via "$router" dev "$interface"
    ;;
esac
exit 0
EOF
chmod 755 /etc/xingtu/udhcpc.script
```

- 这个脚本只设置 IP/默认路由，**不写 DNS**，避免污染主机 `/etc/resolv.conf`；
- 如果 `ifconfig` 不存在，会回退到 `/24`；RNDIS 随身 WiFi 通常就是 /24。

### 3.2 创建 netns 和 veth

```sh
ip netns add ns-sim1
ip link add veth-lan1 type veth peer name veth-ns1
ip link set veth-lan1 master br-lan
ip link set veth-lan1 up
ip link set veth-ns1 netns ns-sim1
ip netns exec ns-sim1 ip link set lo up
ip netns exec ns-sim1 ip link set veth-ns1 up
ip netns exec ns-sim1 ip addr add 192.168.3.201/24 dev veth-ns1
ip netns exec ns-sim1 sh -c 'echo 1 > /proc/sys/net/ipv6/conf/all/disable_ipv6'
ip netns exec ns-sim1 sh -c 'echo 1 > /proc/sys/net/ipv6/conf/default/disable_ipv6'
ip netns exec ns-sim1 sh -c 'echo 1 > /proc/sys/net/ipv6/conf/veth-ns1/disable_ipv6'
```

- 禁用 IPv6 是为了防止 veth 从主 LAN 收到 IPv6 RA，导致出现第二条默认路由、绕开蜂窝；
- 如果 `ip link add` 报 `Operation not supported` → 装 `kmod-veth`；
- 如果 `master br-lan` 报错 → `ip -br link` 确认 LAN 网桥名。

### 3.3 把 USB 网卡移入 netns 并拨号

先确认接口没有被 netifd 管理：

```sh
ubus call network.interface dump | grep -i usb || true
```

如果被管理，先在 `/etc/config/network` 里把对应接口 `option auto '0'` 或删除，避免两个 DHCP 客户端抢。然后：

```sh
ip link set usb0 down
ip link set usb0 netns ns-sim1
ip netns exec ns-sim1 ip link set usb0 up
ip netns exec ns-sim1 udhcpc -i usb0 -q -n -t 10 -T 3 -s /etc/xingtu/udhcpc.script
ip netns exec ns-sim1 ip -4 addr show dev usb0
ip netns exec ns-sim1 ip route
ip netns exec ns-sim1 ping -c 3 223.5.5.5
```

期望：

- `usb0` 获得运营商内网 IP（常见 `192.168.x.x`/`10.x`）；
- `ip route` 里有 `default via <modem-gateway> dev usb0`，且**没有** `default via 192.168.3.1`；
- `ping 223.5.5.5` 通。

失败处理：

- 没有 IP：检查 SIM 是否识别、APN、设备是否在 CD-ROM 模式、`udhcpc.script` 是否可执行；
- 默认路由不对：检查 netns 里是否有多余默认路由；`ip netns exec ns-sim1 ip route del default via 192.168.3.1`（如果存在）；
- 接口被 netifd 重建：先停 netifd 对该接口的管理，再重试。

### 3.4 在 netns 内启动 dnsmasq

先确认主机 `/etc/resolv.conf`：

```sh
cat /etc/resolv.conf
```

如果是 `nameserver 127.0.0.1`，继续；如果不是，先停下（tinyproxy 会走主机的 resolver，可能泄漏 DNS），把内容发回。

```sh
cat >/etc/xingtu/dnsmasq-ns1.conf <<'EOF'
port=53
listen-address=127.0.0.1
bind-interfaces
no-resolv
no-hosts
server=223.5.5.5
server=119.29.29.29
cache-size=1000
pid-file=/var/run/dnsmasq-ns1.pid
log-facility=/var/log/dnsmasq-ns1.log
EOF

ip netns exec ns-sim1 dnsmasq -C /etc/xingtu/dnsmasq-ns1.conf
sleep 1
ip netns exec ns-sim1 nslookup myip.ipip.net 127.0.0.1
```

- 期望解析出 IP；
- 失败：看 `/var/log/dnsmasq-ns1.log`、`ps | grep dnsmasq`、netns 内 `netstat -ltnp | grep :53`；
- 如果 53 被占用，检查 netns 内是否有其他 dnsmasq。

### 3.5 启动 tinyproxy

先生成一个强密码（只含字母数字，避免配置转义问题）：

```sh
PROXY_PASS=$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 24)
echo "用户名 xingtu1"
echo "密码 $PROXY_PASS"
```

把密码记到安全位置（不要发聊天）。然后：

```sh
cat >/etc/xingtu/tinyproxy-ns1.conf <<EOF
Port 6001
Listen 192.168.3.201
Timeout 600
MaxClients 100
BasicAuth xingtu1 $PROXY_PASS
Allow 192.168.3.132
ConnectPort 443
LogLevel Warning
Syslog On
PidFile /var/run/tinyproxy-ns1.pid
EOF
chmod 600 /etc/xingtu/tinyproxy-ns1.conf

ip netns exec ns-sim1 tinyproxy -c /etc/xingtu/tinyproxy-ns1.conf
sleep 1
ip netns exec ns-sim1 netstat -ltn 2>/dev/null | grep ':6001' || true
```

- 如果 tinyproxy 报 `User/Group` 错误，且你没有加 User/Group，通常不会；如果加了，删掉这两行再试；
- 如果 `Listen` 失败，确认 `192.168.3.201` 已在 netns 的 veth 上；
- 如果 `BasicAuth` 后面的密码含特殊字符，重新生成字母数字密码。

### 3.6 从 Mac 验证

在 Mac 上执行（不要把密码写进 shell history；用 `read -s`）：

```sh
read -s PROXY_PASS
curl -x "http://xingtu1:$PROXY_PASS@192.168.3.201:6001" -sS https://myip.ipip.net
curl -x "http://xingtu1:$PROXY_PASS@192.168.3.201:6001" -sS https://ifconfig.me/ip
curl -x "http://xingtu1:$PROXY_PASS@192.168.3.201:6001" -sS -o /dev/null -w '%{http_code}\n' https://www.xingtu.cn/
```

期望：

- 返回蜂窝出口 IP，且**不同于**当前宽带 IPv4；
- 星图首页 HTTP 200（只是连通性检查，不是采集）；
- 如果 407：密码/用户名不对；
- 如果 403/502：`Allow`/网络/DNS；
- 如果连接拒绝：tinyproxy 没监听/端口/IP 不对；
- 如果超时：Mac 到 `192.168.3.201` 不通（主路由隔离、J1900 防火墙、veth 未在 br-lan）。

### 3.7 失败关闭测试

```sh
# OpenWrt
ip netns exec ns-sim1 pkill tinyproxy || true
```

Mac 再执行一次 `curl -x ...`，应该连接失败（`Connection refused`/`Could not connect`），**不能**返回宽带页面。然后重启：

```sh
ip netns exec ns-sim1 tinyproxy -c /etc/xingtu/tinyproxy-ns1.conf
```

### 3.8 DNS 绑定测试

在 OpenWrt 开两个 tcpdump（或一个 `any`）：

```sh
tcpdump -ni any udp port 53 &
```

Mac 通过代理访问一个域名：

```sh
curl -x "http://xingtu1:$PROXY_PASS@192.168.3.201:6001" -sS -o /dev/null https://myip.ipip.net
```

观察 DNS 查询：

- 应出现于 `usb0`（蜂窝）方向；
- 不应出现于 `br-lan`/主 LAN 方向的目标域名查询；
- 如果只在 `br-lan` 出现，说明 `/etc/resolv.conf` 不是 127.0.0.1 或 tinyproxy 用了主机 resolver，停止并修正。

### 3.9 记录

```sh
ip netns exec ns-sim1 ip -4 addr show dev usb0
ip netns exec ns-sim1 ip route
ip netns exec ns-sim1 cat /var/run/tinyproxy-ns1.pid
```

记录：出口编号、USB 接口名、蜂窝 IP、默认网关、代理 IP/端口、测试时间、蜂窝公网 IP、DNS 测试结果。**不要记录 IMEI/ICCID/密码。**

---

## 4. Phase 3：复制到 3 条出口

### 4.1 逐台插入并映射接口

- 不要一次插 3 台再猜接口名；一次插 1 台，记录 `lsusb -t` 的 USB 端口和 `ip -br link` 的新接口；
- 常见接口名：`usb0`、`usb1`、`usb2`，也可能是 `eth1`/`eth2`；以实际为准；
- 把物理 HUB 端口贴上标签（1/2/3），避免以后插错；
- 如果多台同型号的 MAC 相同，netns 隔离后不影响，但要在 `lines.conf` 里按 USB 物理端口固定映射。

### 4.2 出口 2/3 参数

| 出口 | netns | veth 对 | LAN IP | 端口 | USB 接口 | 用户名 |
|---|---|---|---|---|---|---|
| 1 | `ns-sim1` | `veth-lan1`/`veth-ns1` | `192.168.3.201` | 6001 | `usb0` | `xingtu1` |
| 2 | `ns-sim2` | `veth-lan2`/`veth-ns2` | `192.168.3.202` | 6001 | `usb1` | `xingtu2` |
| 3 | `ns-sim3` | `veth-lan3`/`veth-ns3` | `192.168.3.203` | 6001 | `usb2` | `xingtu3` |

把 §3.1–§3.8 的 `ns-sim1`/`192.168.3.201`/`usb0`/`xingtu1`/`6001` 替换为对应值，重复执行。每个出口用**不同强密码**。

### 4.3 三出口验证

**A. 代理连通**

```sh
read -s PASS1; read -s PASS2; read -s PASS3
curl -x "http://xingtu1:$PASS1@192.168.3.201:6001" -sS https://myip.ipip.net
curl -x "http://xingtu2:$PASS2@192.168.3.202:6001" -sS https://myip.ipip.net
curl -x "http://xingtu3:$PASS3@192.168.3.203:6001" -sS https://myip.ipip.net
```

**B. 公网 IP 独立性**

每个出口在 0/5/10 分钟各测 2 个回显服务（`myip.ipip.net`、`ifconfig.me/ip`），记录 IPv4。判定：

- 3 个出口得到 **3 个不同公网 IP** → PASS；
- 任意两个相同 → 该组“独立出口”FAIL；不要用端口数量伪装独立；
- 记录运营商/地区；同运营商同池概率高，必要时换异网 SIM。

**C. 互不影响**

```sh
ip netns exec ns-sim1 pkill tinyproxy
```

Mac 测 201 应失败；202/203 应继续正常。恢复 201 后再测。

**D. 断线/重连**

拔掉出口 1 的 USB/停用其网卡，确认 202/203 正常；恢复后确认 201 仍监听 `192.168.3.201:6001`，新请求走蜂窝。设备重连后 IP 可能变化，属正常；端口映射不变。

**E. 资源**

```sh
top -bn1 | head -20
free -m
dmesg | tail -50
logread | tail -100
```

确认没有 over-current、枚举失败、CPU/内存打满。

---

## 5. Phase 4：持久化（先验证，再开机自启）

> 手工命令重启后会消失。先让 3 条出口手工跑通，再做持久化；不要一开始就写 rc.local。

### 5.1 建议的临时脚本

把单条设置写成 `/etc/xingtu/start-line.sh <1|2|3>`，读取：

`/etc/xingtu/lines.conf`：

```text
1 ns-sim1 192.168.3.201 6001 usb0 veth-lan1 veth-ns1
2 ns-sim2 192.168.3.202 6001 usb1 veth-lan2 veth-ns2
3 ns-sim3 192.168.3.203 6001 usb2 veth-lan3 veth-ns3
```

`/etc/xingtu/passwords.conf`（0600）：

```text
1 xingtu1 <PASS1>
2 xingtu2 <PASS2>
3 xingtu3 <PASS3>
```

脚本逻辑：创建 netns/veth（若不存在）→ 禁用 IPv6 → 移入 USB → `udhcpc` → 启动 dnsmasq → 启动 tinyproxy。**这部分命令就是 §3 的自动化，先手工验证再脚本化。**

### 5.2 开机自启（临时）

`/etc/xingtu/start-lines.sh`：

```sh
#!/bin/sh
for n in 1 2 3; do
  /etc/xingtu/start-line.sh "$n" || echo "line $n failed" >&2
done
```

在 `/etc/rc.local` 的 `exit 0` 前加：

```sh
sleep 15
/etc/xingtu/start-lines.sh
```

- USB 枚举可能晚于 rc.local；失败就加重试/改用 hotplug；
- 最终建议改成 procd + `/etc/hotplug.d/usb`，按 USB 物理路径触发；先不要在没有验证的情况下写死；
- 每次重启后检查 3 个代理端口和出口 IP。

---

## 6. Phase 5：Mac 侧项目接入与 Chrome profile

> 前提：3 条代理已验证，且至少第 1 条能稳定出网。以下需要 3 个账号的平台 ID 和手机验证人；当前不创建“已登录但走宽带”的 profile。

### 6.1 保存代理凭据

在 Mac 项目根目录：

```sh
cat >.runtime/cellular.env <<'EOF'
XINGTU_PROXY_01_USER=xingtu1
XINGTU_PROXY_01_PASS=<PASS1>
XINGTU_PROXY_02_USER=xingtu2
XINGTU_PROXY_02_PASS=<PASS2>
XINGTU_PROXY_03_USER=xingtu3
XINGTU_PROXY_03_PASS=<PASS3>
EOF
chmod 600 .runtime/cellular.env
```

不要把该文件提交 Git；不要发到聊天。

### 6.2 线路证明与探针

`production_line` 单元要求：

- `proxy_server` = `http://192.168.3.201:6001` 等；
- `network_evidence_path` = 一份 `NetworkProof` JSON（0600）；
- `network_probe_command` = 一个能输出 `NetworkProbe` JSON 的探针（stdout 四字段，exit 0/非 0）。

探针必须：

- 显式使用代理、禁用环境代理（`httpx trust_env=False` 或 curl `--noproxy ""`）；
- 查询公网 IP 回显，检查不是宽带、不是其他出口；
- 输出 `{"line_id":...,"healthy":true,"egress_enforced":true,"observed_at":"...Z"}`；
- 公网 IP 写独立清单，不塞进 `NetworkProbe`（当前模型 `extra="forbid"`）。

> 这一步需要写一个小型运维脚本；等第一条代理通过后，我再按实际环境给你脚本和 proof 模板，不在没有测试的情况下先写 `true`。

### 6.3 第一条 Chrome profile

1. 创建 `unit-cellular-01` 配置（新账号、新 profile、代理 201、proof、probe）；
2. `xingtu register-unit --config ...`；
3. `xingtu production-preflight --config ...`；
4. `xingtu login --config ...`：Chrome 通过代理启动，账号归属人完成手机验证；
5. 校验 `expected_account_id` 精确匹配；
6. `xingtu browser-check` / `session-diagnostics`，确认 `READY`；
7. 第 1 条稳定后，再做 02/03。

**不要在宽带先登录再换蜂窝**；不要把 3 个账号同时登录到同一个 profile；不要共享 profile。

---

## 7. 故障排查

| 现象 | 优先检查 | 处理 |
|---|---|---|
| Mac ping 不通 `192.168.3.201` | veth 是否在 `br-lan`、主路由 AP 隔离、J1900 防火墙 | `ip -br link`、`bridge link`；关 AP 隔离/换网线 |
| tinyproxy 连接拒绝 | 是否监听 `192.168.3.201:6001`、进程是否存活 | `ip netns exec ns-sim1 netstat -ltnp`；看日志 |
| 407 | 用户名/密码 | 重新设置 BasicAuth，Mac 重新 `read -s` |
| 403/502 | `Allow` 的 Mac IP、DNS/上游 | 确认 Mac IP；看 tinyproxy 日志、netns DNS |
| 没有 DHCP | SIM/APN/CD-ROM 模式、netifd 抢占 | `dmesg`、`lsusb`、`udhcpc` 脚本；禁用 netifd 管理 |
| DNS 失败 | 主机 `/etc/resolv.conf` 是否 127.0.0.1、dnsmasq 是否跑 | 修 resolv.conf 或做 mount namespace；看 dnsmasq 日志 |
| 公网 IP 相同 | CGNAT/同运营商同池 | 换异网/APN；不能解决就减少并发出口，不伪装独立 |
| 设备反复掉线 | 供电/HUB/线材/过热 | 带供电 HUB、换口、散热；`dmesg` 看 over-current |
| 重启后代理消失 | 手工配置未持久化 | 先手工恢复；验证后再做 procd/hotplug |
| `ip netns` 不可用 | 未装 `ip-full` | `opkg install ip-full` |
| `tinyproxy` 找不到 | feed/版本 | `opkg search tinyproxy`；没有就停止，不换 3proxy |

---

## 8. 每个阶段要回传什么

**Phase 0：**

- §1.2 的 `ip -br addr`、`ip route`、`uci show network`、`uci show dhcp`、`opkg list-installed | grep ...`、`cat /etc/resolv.conf`；
- §1.3 的 `lsusb`、`lsusb -t`、`dmesg | grep ...`、`ip -br link`（脱敏）；
- 主路由 DHCP 池、J1900 是否主路由、Mac 是否 `192.168.3.132`。

**Phase 2：**

- netns 内 `ip -4 addr`、`ip route`；
- Mac `curl` 出口 IP（可只发后两段）；
- 失败关闭结果；
- DNS tcpdump 摘要（哪个接口出现查询）。

**Phase 3：**

- 3 个出口 IP（可只发后两段）；
- 互不影响/重连结果；
- `top`/`free`/`dmesg` 摘要。

不要发：root 密码、Wi-Fi 密码、代理密码、IMEI、ICCID、手机号、Cookie。

---

## 9. 当前检查点

- [ ] Phase 0 只读盘点完成，输出已回传；
- [ ] 确认 J1900 旁路主机拓扑/IP 规划；
- [ ] 单台随身 WiFi 已识别并取得蜂窝 IP；
- [ ] 单条 tinyproxy 从 Mac 可访问，出口 IP 与宽带不同；
- [ ] 单条失败关闭 PASS；
- [ ] 单条 DNS 绑定 PASS；
- [ ] 3 条出口建立，3 个公网 IP 独立性 PASS；
- [ ] 互不影响/重连 PASS；
- [ ] 再做持久化；
- [ ] 再做项目单元/Chrome profile（需账号 ID/手机验证人）。

**当前状态：Phase 0 未执行。设备已就绪，但 J1900 的实机信息、USB 接口名、OpenWrt 版本和主路由 DHCP 池尚未确认；不要直接照抄命令，先完成 §1 盘点。**
