#!/bin/sh
# IPPOOL-02 line 2 bootstrap / recovery.
# ns-sim2: second USB modem (CDC ECM) + veth 192.168.1.251/24 + dnsmasq + tinyproxy.
# Safe to re-run: reuses netns/veth, flushes the modem IP, renews DHCP,
# and restarts dnsmasq/tinyproxy. It never falls back to the host default route.

set -u

NS=ns-sim2
VH=veth-lan2
VN=veth-ns2
LANIP=192.168.1.251/24
MODEM_MAC=ba:7b:bb:ec:28:c0
MODEM_PATH=1-2.3.2:1.0
PROXY_PORT=6001
PROXY_USER=${PROXY_USER:-xingtu}
PROXY_PASS=${PROXY_PASS:-xingtu}
LOG=/tmp/xingtu-line2.log
TP_PID=/tmp/xingtu-line2-tinyproxy.pid
DNS_PID=/tmp/xingtu-line2-dnsmasq.pid
TP_CONF=/tmp/xingtu-line2-tinyproxy.conf
UDHCPC=/tmp/xingtu-udhcpc2.sh

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

i=0
while [ ! -e /sys/class/net/br-lan ] && [ "$i" -lt 30 ]; do
    i=$((i + 1))
    sleep 1
done
[ -e /sys/class/net/br-lan ] || die "br-lan not found"

if ! ip netns list | grep -q "^$NS "; then
    ip netns add "$NS" || die "ip netns add $NS failed"
fi

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

ip -n "$NS" addr flush dev wwan0 || true
ip -n "$NS" route flush dev wwan0 || true

cat >"$UDHCPC" <<'EOF'
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
chmod +x "$UDHCPC"

ip netns exec "$NS" udhcpc -i wwan0 -t 5 -T 3 -n -q -s "$UDHCPC" || die "DHCP on wwan0 failed"
ip -n "$NS" -4 addr show dev wwan0 | grep -q "inet " || die "wwan0 has no IPv4"
ip -n "$NS" route | grep -q "^default " || die "no default route in $NS"

cleanup_pid "$DNS_PID"
ip netns exec "$NS" dnsmasq -C /dev/null --no-resolv --server=223.5.5.5 \
    --listen-address=127.0.0.1 --pid-file="$DNS_PID" \
    --dhcp-leasefile=/tmp/xingtu-line2-dnsmasq.leases || die "dnsmasq start failed"
sleep 1
ip netns exec "$NS" nslookup openwrt.org 127.0.0.1 >/tmp/xingtu-line2-dnscheck 2>&1 \
    || die "DNS check failed"

cleanup_pid "$TP_PID"
cat >"$TP_CONF" <<EOF
Port $PROXY_PORT
Listen 192.168.1.251
Allow 192.168.1.210
BasicAuth $PROXY_USER $PROXY_PASS
Timeout 600
PidFile "$TP_PID"
LogFile "/tmp/xingtu-line2-tinyproxy.log"
EOF
ip netns exec "$NS" tinyproxy -c "$TP_CONF" || die "tinyproxy start failed"
sleep 1
[ -f "$TP_PID" ] || die "tinyproxy pid missing"

log "OK ns=$NS veth=$LANIP proxy=192.168.1.251:$PROXY_PORT"
exit 0
