#!/bin/sh
set -eu

echo "host memory"
free -h
echo "host swap"
swapon --show || true
echo "filesystem"
df -h / /var/lib/docker 2>/dev/null || df -h /
echo "container snapshot"
docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.PIDs}}'
echo "docker disk"
docker system df
