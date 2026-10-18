#!/usr/bin/env bash
#
# 一键启停「星采」本地全栈（后端 API + 两个 Worker + 前端页面）。
#
# 由谁使用：在本机终端手动唤起服务、然后打开页面体验的人。
#
#   ./dev.sh           # 等于 ./dev.sh up
#   ./dev.sh up        # 依赖服务 → 前置自检 → 启动 API / Intake / 采集 / 前端
#   ./dev.sh status    # 查看进程、端口、健康与消费者新鲜度
#   ./dev.sh logs [名称]
#   ./dev.sh stop      # 只停止本脚本启动的进程（含 API、前端）
#   ./dev.sh restart
#
# 与既有入口的关系：进程本身仍由 Makefile 里登记的入口启动（xingtu-api /
# xingtu-product intake-worker / xingtu worker / npm run dev），前置自检直接复用
# scripts/m3_up.py，本脚本只补齐三件缺失的事：
#   1. 一条命令覆盖全部四个进程（make m3-up 默认不带采集与前端）；
#   2. 记录 PID，使 stop 能停掉 API 与前端（否则只能留后台游离进程）；
#   3. 启动后给出中文就绪状态与登录地址。
#
# 配置不重复：环境仍读 .runtime/m3-app.env 与 .runtime/deepseek.env，单元仍读
# .runtime/units/local-dev-mac-02.json。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

UNIT_CONFIG="${UNIT_CONFIG:-$ROOT/.runtime/units/local-dev-mac-02.json}"
M3_ENV="$ROOT/.runtime/m3-app.env"
MODEL_ENV="$ROOT/.runtime/deepseek.env"
LOG_DIR="$ROOT/.runtime/logs"
RUN_DIR="$ROOT/.runtime/dev"
PID_FILE="$RUN_DIR/pids.tsv"

API_PORT="${XINGTU_API_PORT:-8000}"
FRONTEND_PORT=5173

usage() {
  cat <<'EOF'
用法：./dev.sh [up|stop|restart|status|logs [名称]|check|help]

  up      启动依赖 → 前置自检 → API、Intake Worker、采集 Worker、前端页面
  stop    停止本脚本启动的进程（保留数据库、对象、profile 与浏览器数据）
  restart 先 stop 再 up
  status  查看进程 / 端口 / API 健康 / 队列消费者新鲜度
  logs    跟踪全部日志；logs api / intake-worker / collection-worker / update-scheduler / frontend 看单个
  check   只做前置自检，不启动任何进程

环境变量：UNIT_CONFIG 可覆盖执行单元配置（默认 .runtime/units/local-dev-mac-02.json）。
EOF
}

log() { printf '%s %s\n' "$(date '+%H:%M:%S')" "$*"; }
fail() { printf '错误：%s\n' "$*" >&2; exit 1; }

# --- PID 记录 ---------------------------------------------------------------
# 只记录本脚本启动或确认复用的进程；stop 绝不触碰未记录的进程。
# 注意：本函数必须始终以 0 退出，否则 set -e 会在 pid="$(pid_of x)" 处终止脚本。
pid_of() {
  if [ -f "$PID_FILE" ]; then
    awk -F'\t' -v n="$1" '$1==n{print $2}' "$PID_FILE" || true
  fi
  return 0
}
record_pid() {
  mkdir -p "$RUN_DIR"
  [ -f "$PID_FILE" ] || : >"$PID_FILE"
  { grep -v "^$1	" "$PID_FILE" 2>/dev/null || true; printf '%s\t%s\n' "$1" "$2"; } >"$PID_FILE.tmp"
  mv "$PID_FILE.tmp" "$PID_FILE"
}
alive_pid() { local p="${1:-}"; [ -n "$p" ] && kill -0 "$p" 2>/dev/null; }
listener_pid() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -1; }
port_open() { [ -n "$(listener_pid "$1")" ]; }

# --- 环境与就绪检查 ----------------------------------------------------------
sanitise_no_proxy() {
  # httpx 0.28 无法解析 no_proxy 中的方括号 IPv6（[::1]），会在任何请求前抛
  # InvalidURL；去掉方括号项、保留 ::1（与 scripts/m3_up.py 行为一致）。
  local v
  v="$(printf '%s' "${no_proxy:-}" | tr ',' '\n' | grep -v '^\[' | paste -sd, - || true)"
  export no_proxy="$v" NO_PROXY="$v"
}

load_env() {
  [ -f "$M3_ENV" ] || fail "缺少 $M3_ENV；请先执行 make setup"
  sanitise_no_proxy
  set -a
  # shellcheck disable=SC1090
  . "$M3_ENV"
  [ -f "$MODEL_ENV" ] && . "$MODEL_ENV"
  set +a
  export PYTHONPATH="$ROOT/backend/src"
  export PLAYWRIGHT_BROWSERS_PATH="$ROOT/.runtime/browsers"
  mkdir -p "$LOG_DIR" "$RUN_DIR"
}

preflight() {
  load_env
  "$ROOT/.venv/bin/python" "$ROOT/scripts/m3_up.py" --check \
    --with-collection --with-frontend --unit-config "$UNIT_CONFIG"
}

wait_http() {
  local url="$1" want="$2" name="$3" attempts="${4:-45}"
  for _ in $(seq 1 "$attempts"); do
    if [ "$(curl -s -o /dev/null -w '%{http_code}' "$url" || true)" = "$want" ]; then
      log "就绪：$name ($url -> $want)"
      return 0
    fi
    sleep 2
  done
  return 1
}

tail_log() { tail -n 20 "$LOG_DIR/$1.log" 2>/dev/null || echo "（无 $1 日志）"; }

# --- 启动各进程 --------------------------------------------------------------
start_bg() {
  local name="$1"; shift
  nohup "$@" >>"$LOG_DIR/$name.log" 2>&1 &
  local pid=$!
  disown "$pid" 2>/dev/null || true
  record_pid "$name" "$pid"
  log "已启动 $name (pid $pid) -> .runtime/logs/$name.log"
}

# Worker 必须「每账号一个」：重复的 intake worker 会重复派发，重复的采集 worker 会在
# 同一 profile 上打架。因此 up 采用接管而不是叠加：
#   0 个 → 启动；1 个未记录 → 接管并记录 PID；被记录且存活 → 沿用；
#   多个 → 只保留被记录（或最先存在的）一个，其余明确报告后结束。
worker_pattern() {
  case "$1" in
    intake-worker) printf 'xingtu-product intake-worker' ;;
    collection-worker) printf 'xingtu worker --config' ;;
    update-scheduler) printf 'xingtu-product update-scheduler' ;;
  esac
}

# `pgrep -f` 会匹配到「命令行里含同一字符串」的别的进程（例如正在执行本脚本的 bash
# 自身、tail / grep 等），曾把一次正常的自检误报成“重复 worker”。这里再用 lsof 确认
# 该 PID 确实在跑本项目的 Python 解释器，只有真正的 worker 才会被返回。
worker_pids() {
  local pattern py_pids pid
  pattern="$(worker_pattern "$1")"
  py_pids="$(lsof -c Python -F p 2>/dev/null | sed -n 's/^p//p' | sort -u || true)"
  for pid in $(pgrep -f "$pattern" 2>/dev/null || true); do
    if printf '%s\n' "$py_pids" | grep -qx "$pid"; then printf '%s\n' "$pid"; fi
  done
  return 0
}

reconcile_worker() {
  local name="$1" pids keep recorded
  pids="$(worker_pids "$name")"
  local count; count="$(printf '%s\n' "$pids" | grep -c . || true)"

  if [ "$count" -eq 0 ]; then
    case "$name" in
      intake-worker)
        start_bg intake-worker "$ROOT/.venv/bin/xingtu-product" intake-worker --unit-config "$UNIT_CONFIG" ;;
      collection-worker)
        start_bg collection-worker "$ROOT/.venv/bin/xingtu" worker --config "$UNIT_CONFIG" ;;
      update-scheduler)
        start_bg update-scheduler "$ROOT/.venv/bin/xingtu-product" update-scheduler --unit-config "$UNIT_CONFIG" ;;
    esac
    return 0
  fi
  recorded="$(pid_of "$name")"
  keep=""
  if [ -n "$recorded" ] && printf '%s\n' "$pids" | grep -qx "$recorded"; then
    keep="$recorded"
  else
    keep="$(printf '%s\n' "$pids" | head -1)"
  fi

  local pid
  for pid in $pids; do
    if [ "$pid" != "$keep" ]; then
      log "结束重复的 $name (pid $pid)，保持每账号一个"
      kill "$pid" 2>/dev/null || true
    fi
  done
  record_pid "$name" "$keep"
  if [ "$count" -gt 1 ]; then
    log "接管 $name (pid $keep)，已清理 $((count - 1)) 个重复进程"
  else
    log "接管已在运行的 $name (pid $keep)"
  fi
}

cmd_up() {
  load_env
  if [ -f "$ROOT/.runtime/dev-up.sh" ]; then
    log "确保依赖服务（PostgreSQL / Redis / MinIO / Temporal）…"
    "$ROOT/.runtime/dev-up.sh" up >/dev/null 2>&1 || log "依赖启动有告警，继续用前置自检判定"
  else
    log "未找到 .runtime/dev-up.sh，跳过依赖启动（用前置自检判定）"
  fi

  log "运行前置自检（scripts/m3_up.py --check）…"
  if ! preflight; then
    fail "前置自检未通过：未启动任何进程。按上面的 FAIL 项修复后重试。"
  fi

  # 1) 后端 API
  if port_open "$API_PORT"; then
    record_pid api "$(listener_pid "$API_PORT")"
    log "接管已在 $API_PORT 监听的 API（pid $(listener_pid "$API_PORT")）"
  else
    start_bg api "$ROOT/.venv/bin/xingtu-api"
    wait_http "http://127.0.0.1:$API_PORT/api/auth/me" 401 "后端 API" || {
      echo "--- api.log ---"; tail_log api; fail "API 未在预期时间内就绪"; }
  fi

  # 2) P1 需求转换 Worker（缺它任务会停在 RECEIVED）
  reconcile_worker intake-worker
  # 3) P2 采集 Worker（缺它任务会停在 QUEUED；采集时会打开真实 Chrome）
  reconcile_worker collection-worker
  # 4) 定时更新调度器（只读写数据库；不运行则仅定时更新暂停，不影响采集）
  reconcile_worker update-scheduler

  # 5) 前端页面
  if port_open "$FRONTEND_PORT"; then
    record_pid frontend "$(listener_pid "$FRONTEND_PORT")"
    log "接管已在 $FRONTEND_PORT 监听的前端（pid $(listener_pid "$FRONTEND_PORT")）"
  else
    start_bg frontend npm --prefix "$ROOT/frontend" run dev
    wait_http "http://127.0.0.1:$FRONTEND_PORT/" 200 "前端页面" || {
      echo "--- frontend.log ---"; tail_log frontend; fail "前端未在预期时间内就绪"; }
  fi

  log "等待队列消费者注册（Temporal）…"
  sleep 6
  check_consumers || true

  cat <<EOF

============================================================
  星采 · 媒介工作台已就绪
  页面： http://127.0.0.1:$FRONTEND_PORT/
  后端： http://127.0.0.1:$API_PORT   （healthcheck：GET /api/auth/me -> 401）
  登录： media-a / media-b（口令见 .runtime/qa-credentials.env）
  日志： tail -f .runtime/logs/*.log     停止： ./dev.sh stop
  说明： 「达人库」页数据来自已采集的抖音星图达人；新建采集任务会调用真实
         星图（打开 Chrome，需已登录的执行单元账号）。
============================================================
EOF
}

check_consumers() {
  local dsn addr
  dsn="$(awk -F= '/^XINGTU_DATABASE_URL=/{print substr($0,index($0,"=")+1)}' "$M3_ENV")"
  addr="$(awk -F= '/^XINGTU_TEMPORAL_ADDRESS=/{print substr($0,index($0,"=")+1)}' "$M3_ENV")"
  XINGTU_DATABASE_URL="$dsn" "$ROOT/.venv/bin/python" - "$addr" <<'PY' || return 1
import asyncio, sys
sys.path.insert(0, "backend/src")
from xingtu.worker_health import check_queues

async def main() -> int:
    addr = sys.argv[1]
    queues = ["xingtu-intake", "xingtu-unit-local-mac-02"]
    results = await check_queues(addr, queues)
    ok = True
    for queue, health in results.items():
        state = "在线" if health.alive else "未就绪"
        print(f"  队列 {queue:<28} {state}  新鲜消费者={health.fresh_pollers}  "
              f"最老刷新={health.freshest_age_seconds}s  {health.error or ''}")
        ok = ok and health.alive
    return 0 if ok else 1

raise SystemExit(asyncio.run(main()))
PY
}

# --- 查看状态 ----------------------------------------------------------------
svc_line() {
  local name="$1" port="$2" pid
  pid="$(pid_of "$name")"
  if alive_pid "$pid"; then
    printf '  %-18s 运行中   pid %s（本脚本启动）\n' "$name" "$pid"
  elif [ -n "$port" ] && port_open "$port"; then
    printf '  %-18s 运行中   pid %s（端口 %s，非本脚本启动）\n' "$name" "$(listener_pid "$port")" "$port"
  elif [ -n "$pid" ]; then
    printf '  %-18s 已退出   （记录 pid %s 不存在，日志见下）\n' "$name" "$pid"
  else
    printf '  %-18s 未运行\n' "$name"
  fi
}

# Worker 没有端口可查，只能按进程签名统计；数量 >1 本身就是需要修复的状态。
worker_line() {
  local name="$1" pids count
  pids="$(worker_pids "$name")"
  count="$(printf '%s\n' "$pids" | grep -c . || true)"
  case "$count" in
    0) printf '  %-18s 未运行\n' "$name" ;;
    1) printf '  %-18s 运行中   pid %s\n' "$name" "$(printf '%s\n' "$pids" | head -1)" ;;
    *) printf '  %-18s 重复运行 %s 个 pid：%s（需修复，./dev.sh restart）\n' \
         "$name" "$count" "$(printf '%s' "$pids" | tr '\n' ' ')" ;;
  esac
}

cmd_status() {
  load_env
  echo "== 进程 =="
  svc_line api "$API_PORT"
  svc_line frontend "$FRONTEND_PORT"
  worker_line intake-worker
  worker_line collection-worker
  worker_line update-scheduler

  echo "== 端口 =="
  local p
  for p in "$API_PORT" "$FRONTEND_PORT" 55432 56379 59000 57233; do
    if port_open "$p"; then echo "  $p 监听中"; else echo "  $p 空闲"; fi
  done

  echo "== HTTP =="
  printf '  API   /api/auth/me        -> %s（期望 401）\n' \
    "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$API_PORT/api/auth/me" || echo '无响应')"
  printf '  前端  /                   -> %s（期望 200）\n' \
    "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$FRONTEND_PORT/" || echo '无响应')"

  echo "== 队列消费者 =="
  check_consumers || echo "  （存在未就绪队列：缺少消费者时任务会停在 RECEIVED/QUEUED）"

  echo "== 最近日志 =="
  local f
  for f in "$LOG_DIR"/*.log; do
    [ -f "$f" ] || continue
    printf '  %-34s %s\n' ".runtime/logs/$(basename "$f")" "$(tail -n 1 "$f" 2>/dev/null | cut -c1-90)"
  done
}

# --- 停止 --------------------------------------------------------------------
descendants_of() {
  # 递归列出子进程；`npm run dev` 会把真正的 Vite 进程生成为子进程，只 kill npm
  # 会留下继续占用 5173 的孤儿。
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    descendants_of "$child"
    printf '%s\n' "$child"
  done
  return 0
}

stop_pid() {
  local name="$1" pid kids; pid="$(pid_of "$name")"
  if ! alive_pid "$pid"; then
    [ -n "$pid" ] && log "$name 未在运行（记录 pid $pid 已不存在）"
    return 0
  fi
  kids="$(descendants_of "$pid")"
  log "停止 $name (pid $pid${kids:+ 及子进程 $(printf '%s' "$kids" | tr '\n' ' ')})…"
  kill $kids "$pid" 2>/dev/null || true
  local _; for _ in $(seq 1 12); do alive_pid "$pid" || break; sleep 0.5; done
  if alive_pid "$pid"; then log "$name 未响应 TERM，发送 KILL"; kill -9 $kids "$pid" 2>/dev/null || true; fi
  for pid in $kids; do kill -9 "$pid" 2>/dev/null || true; done
}

cmd_stop() {
  mkdir -p "$RUN_DIR"
  if [ -f "$PID_FILE" ]; then
    # 先停消费者与前端，最后停 API，避免页面先断连。
    stop_pid intake-worker
    stop_pid collection-worker
    stop_pid update-scheduler
    stop_pid frontend
    stop_pid api
    : >"$PID_FILE"
  else
    log "没有本脚本记录的进程（.runtime/dev/pids.tsv 不存在）"
  fi

  # 兜底：端口仍被占用时明确告知，绝不擅自 kill 外部进程。
  local p
  for p in "$API_PORT" "$FRONTEND_PORT"; do
    if port_open "$p"; then
      printf '注意：端口 %s 仍被 pid %s 占用，且不是本脚本启动的；未自动结束它。\n' \
        "$p" "$(listener_pid "$p")" >&2
    fi
  done
  log "已停止本脚本启动的进程（数据库、对象、profile 与浏览器数据均保留）"
  log "依赖服务如需停止：make stop（或 ./.runtime/dev-up.sh stop）"
}

# --- 主入口 ------------------------------------------------------------------
case "${1:-up}" in
  up) cmd_up ;;
  stop) cmd_stop ;;
  restart) cmd_stop; cmd_up ;;
  status) cmd_status ;;
  check) preflight ;;
  logs)
    if [ -n "${2:-}" ]; then
      [ -f "$LOG_DIR/$2.log" ] || fail "没有日志 $LOG_DIR/$2.log"
      tail -f -n 40 "$LOG_DIR/$2.log"
    else
      tail -f -n 15 "$LOG_DIR"/*.log
    fi
    ;;
  -h|--help|help) usage ;;
  *) usage; exit 2 ;;
esac
