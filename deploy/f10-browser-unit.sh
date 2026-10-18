#!/bin/sh
# Runs inside one already-built collection-worker image. The image must include Xvfb, x11vnc,
# Chromium/Playwright and the `xingtu` CLI. This script publishes no VNC or Chrome debug port.
set -eu

: "${UNIT_CONFIG:?UNIT_CONFIG must name the private unit config file}"
: "${DISPLAY:=:99}"

Xvfb "$DISPLAY" -screen 0 "${XINGTU_VNC_GEOMETRY:-1440x960x24}" -nolisten tcp &
xvfb_pid=$!
x11vnc -display "$DISPLAY" -forever -nopw -rfbport 5900 \
  -noxrecord -noxfixes -noxdamage &
vnc_pid=$!
worker_pid=""

cleanup() {
  if [ -n "$worker_pid" ]; then
    kill "$worker_pid" 2>/dev/null || true
  fi
  kill "$vnc_pid" "$xvfb_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

xingtu worker --config "$UNIT_CONFIG" &
worker_pid=$!
while kill -0 "$worker_pid" 2>/dev/null \
  && kill -0 "$vnc_pid" 2>/dev/null \
  && kill -0 "$xvfb_pid" 2>/dev/null; do
  sleep 1
done
if kill -0 "$worker_pid" 2>/dev/null; then
  exit 1
fi
wait "$worker_pid"
