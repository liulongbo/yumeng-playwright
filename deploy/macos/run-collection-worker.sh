#!/bin/zsh
set -euo pipefail

if (( $# != 3 )); then
  print -u2 "usage: $0 PROJECT_ROOT UNIT_CONFIG ENV_FILE"
  exit 64
fi

project_root="$1"
unit_config="$2"
env_file="$3"

for required in "$project_root/.venv/bin/xingtu" "$unit_config" "$env_file"; do
  if [[ ! -e "$required" ]]; then
    print -u2 "required path missing: $required"
    exit 66
  fi
done

for private_file in "$unit_config" "$env_file"; do
  permissions="$(/usr/bin/stat -f '%Lp' "$private_file")"
  if (( 8#$permissions & 8#077 )); then
    print -u2 "private file must not be group/world accessible: $private_file"
    exit 77
  fi
done

if ! /bin/launchctl print "gui/$(/usr/bin/id -u)" >/dev/null 2>&1; then
  print -u2 "headful Chrome requires an active logged-in Aqua user session"
  exit 69
fi

set -a
source "$env_file"
set +a
export PYTHONPATH="$project_root/backend/src"
export PLAYWRIGHT_BROWSERS_PATH="$project_root/.runtime/browsers"

cd "$project_root"
"$project_root/.venv/bin/xingtu" worker-preflight --config "$unit_config"

# caffeinate prevents system/idle sleep while the long-running collection poller owns work.
# Browser profile locking and ExecutionUnit fencing remain inside the application runtime.
exec /usr/bin/caffeinate -dimsu "$project_root/.venv/bin/xingtu" worker --config "$unit_config"
