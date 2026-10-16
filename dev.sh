#!/usr/bin/env bash
# 根目录便捷入口：等价于 ./scripts/dev.sh "$@"
# 用法见 ./dev.sh help
exec "$(cd "$(dirname "$0")" && pwd)/scripts/dev.sh" "$@"
