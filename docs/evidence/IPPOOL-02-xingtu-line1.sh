#!/bin/sh
# IPPOOL-02 line 1 bootstrap / recovery.
# ns-sim1: USB modem (CDC ECM) + veth 192.168.1.250/24 + dnsmasq + tinyproxy.
# Safe to re-run: it reuses the netns/veth, flushes the modem IP, renews DHCP,
# and restarts dnsmasq/tinyproxy. It never falls back to the host default route.

set -u

NS=ns-sim1
VH=veth-lan1
VN=veth-ns1
LANIP=192.168.1.250/24
MODEM_MAC=34:4b:50:00:00:00
MODEM_PATH=2-2.1:1.0
PROXY_PORT=6001
PROXY_USER=${PROXY_USER:-xingtu}
PROXY_PASS=${PROXY_PASS:-xingtu}
LOG=/tmp/xingtu-line1.log

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >>"$LOG"; }
die() { log "ERROR: $*"; echo "ERROR: $*" >&2; exit 1; }

cleanup_pid() {
    f="$1"
    [ -f "$f" ] || return 0
    p=$(cat "$f" 2>/dev/null || true)
    if [ -n "$p" ]; then
        kill "$p" 2>/dev/null || true
    fi
    rm -f "$f"
}

[ "$(id -u)" = 0 ] || die "must run as root"

# Wait briefly for br-lan to exist after boot.
i=0
while [ ! -e /sys/class/net/br-lan ] && [ "$i" -lt 30 ]; do
    i=$((i + 1))
    sleep 1
done
[ -e /sys/class/net/br-lan ] || die "br-lan not found"

# Netns.
if ! ip netns list | grep -q "^$NS "; then
    ip netns add "$NS" || die "ip netns add $NS failed"
fi

# veth pair: host side in br-lan, peer inside ns.
if ! ip link show "$VH" >/dev/null 2>&1; then
    ip link add "$VH" type veth peer name "$VN" || die "veth add failed"
fi
if ip link show "$VN" >/dev/null 2>&1; then
    ip link set "$VN" netns "$NS" || die "move $VN to $NS failed"
fi
ip link set "$VH" master br-lan || die "attach $VH to br-lan failed"
ip link set "$VH" up || die "bring up $VH failed"

ip -n "$NS" link set lo up || die "bring up lo in $NS failed"
if ! ip -n "$NS" link show "$VN" >/dev/null 2>&1; then
    die "$VN missing in $NS"
fi
ip -n "$NS" addr replace "$LANIP" dev "$VN" || die "assign $LANIP failed"
ip -n "$NS" link set "$VN" up || die "bring up $VN failed"

# Find the USB modem: prefer the USB path, then the known MAC.
if ip -n "$NS" link show wwan0 >/dev/null 2>&1; then
    log "modem already in $NS as wwan0"
else
    modem_found=0
    i=0
    while [ "$i" -lt 60 ]; do
        for d in /sys/class/net/*; do
            dev=${d##*/}
            case "$dev" in
                lo|br-*|veth*) continue ;;
            esac
            [ -e "$d/device" ] || continue
            addr=$(cat "$d/address" 2>/dev/null || true)
            path=$(readlink -f "$d/device" 2>/dev/null || readlink "$d/device" 2>/dev/null || true)
            match=0
            if [ -n "$MODEM_PATH" ] && echo "$path" | grep -q "$MODEM_PATH"; then
                match=1
            elif [ "$addr" = "$MODEM_MAC" ]; then
                match=1
            fi
            [ "$match" = 1 ] || continue
            log "moving modem $dev ($addr, $path) to $NS"
            ip link set "$dev" netns "$NS" || die "move $dev to $NS failed"
            if ip -n "$NS" link show wwan0 >/dev/null 2>&1; then
                die "wwan0 already exists in $NS"
            fi
            ip -n "$NS" link set "$dev" name wwan0 || die "rename $dev to wwan0 failed"
            modem_found=1
            break
        done
        [ "$modem_found" = 1 ] && break
        i=$((i + 1))
        sleep 2
    done
    [ "$modem_found" = 1 ] || die "modem not found (path=$MODEM_PATH mac=$MODEM_MAC)"
fi

ip -n "$NS" link set wwan0 up || die "bring up wwan0 failed"

# The modem may have inherited the old WAN 192.168.0.178 when it stole eth2.
# Always clear it and renew from the portable Wi-Fi.
ip -n "$NS" addr flush dev wwan0 || true
ip -n "$NS" route flush dev wwan0 || true

cat >/tmp/xingtu-udhcpc.sh <<'EOF'
#!/bin/sh
[ -n "$ip" ] || exit 0
[ -n "$router" ] || exit 0
case "$mask" in
    255.255.255.0) p=24 ;;
    255.255.254.0) p=23 ;;
    255.255.0.0) p=16 ;;
    255.0.0.0) p=8 ;;
    *) p=24 ;;
esac
ip addr replace "$ip/$p" dev "$interface"
ip route replace default via "$router" dev "$interface"
EOF
chmod +x /tmp/xingtu-udhcpc.sh

ip netns exec "$NS" udhcpc -i wwan0 -t 5 -T 3 -n -q -s /tmp/xingtu-udhcpc.sh || die "DHCP on wwan0 failed"
ip -n "$NS" -4 addr show dev wwan0 | grep -q "inet " || die "wwan0 has no IPv4"
ip -n "$NS" route | grep -q "^default " || die "no default route in $NS"

# DNS: one private dnsmasq inside the netns. /etc/resolv.conf stays 127.0.0.1
# and is shared, but each netns has its own loopback resolver.
cleanup_pid /tmp/dnsmasq-ns1.pid
cleanup_pid /tmp/xingtu-dnsmasq.pid
ip netns exec "$NS" dnsmasq -C /dev/null --no-resolv --server=223.5.5.5 \
    --listen-address=127.0.0.1 --pid-file=/tmp/xingtu-dnsmasq.pid \
    --dhcp-leasefile=/tmp/xingtu-dnsmasq.leases || die "dnsmasq start failed"
sleep 1
ip netns exec "$NS" nslookup openwrt.org 127.0.0.1 >/tmp/xingtu-dnscheck 2>&1 \
    || die "DNS check failed"

# tinyproxy: HTTP BasicAuth, only the Mac. PidFile/LogFile must be quoted.
cleanup_pid /tmp/tinyproxy-ns1.pid
cleanup_pid /tmp/xingtu-tinyproxy.pid
cat >/tmp/xingtu-tinyproxy.conf <<EOF
Port $PROXY_PORT
Listen 192.168.1.250
Allow 192.168.1.210
BasicAuth $PROXY_USER $PROXY_PASS
Timeout 600
PidFile "/tmp/xingtu-tinyproxy.pid"
LogFile "/tmp/xingtu-tinyproxy.log"
EOF
ip netns exec "$NS" tinyproxy -c /tmp/xingtu-tinyproxy.conf || die "tinyproxy start failed"
sleep 1
[ -f /tmp/xingtu-tinyproxy.pid ] || die "tinyproxy pid missing"

log "OK ns=$NS veth=$LANIP proxy=192.168.1.250:$PROXY_PORT"
exit 0
