#!/usr/bin/env bash
# 一键重启全部服务：停止 -> 等待端口释放 -> 启动 -> 状态。
# 部署后改了 .py 必须重启对应进程才生效（static/ 前端文件免重启）。
# 用法：bash scripts/restart_all.sh [profile]
#   profile 默认取 .env 的 TOBACCO_PROFILE，再退回 dev
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
# shellcheck disable=SC1091
source scripts/profile_env.sh "${1:-${TOBACCO_PROFILE:-dev}}"
PROFILE="$TOBACCO_PROFILE"

echo "==> 停止全部服务"
bash scripts/stop_all.sh || true

port_in_use() {
  ss -ltn 2>/dev/null | awk -v p=":$1" '$4 ~ p"$" { found = 1 } END { exit found ? 0 : 1 }'
}

# 等待端口释放，最多 ~12s；仍占用则强制结束占用进程，避免 start_all 误判“已在运行”
wait_ports_free() {
  local deadline=$(( $(date +%s) + 12 ))
  for port in "$@"; do
    while port_in_use "$port"; do
      if (( $(date +%s) >= deadline )); then
        echo "  端口 $port 仍被占用，强制结束占用进程"
        local pids
        pids="$(ss -ltnp 2>/dev/null | grep -oE ":$port\b[^|]*pid=[0-9]+" | grep -oE 'pid=[0-9]+' | grep -oE '[0-9]+' | sort -u || true)"
        for pid in $pids; do kill -9 "$pid" 2>/dev/null || true; done
        break
      fi
      sleep 0.3
    done
  done
}

echo "==> 等待端口释放 (${MANAGEMENT_PORT}, ${PORT}, ${TEXT_PORT}, ${AUDIO_PORT})"
wait_ports_free "$MANAGEMENT_PORT" "$PORT" "$TEXT_PORT" "$AUDIO_PORT"

echo "==> 启动全部服务 (profile=$PROFILE)"
bash scripts/start_all.sh "$PROFILE"

echo "==> 服务状态"
sleep 2
bash scripts/status_all.sh "$PROFILE" || true
