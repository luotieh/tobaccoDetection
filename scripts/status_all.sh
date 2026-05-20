#!/usr/bin/env bash
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

status_pid() {
  local name="$1"
  local pid_file=".runtime/${name}.pid"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
      printf "%-12s pid=%-8s running\n" "$name" "$pid"
      return 0
    fi
    printf "%-12s pid=%-8s stale\n" "$name" "$pid"
    return 1
  fi
  printf "%-12s pid=%-8s untracked\n" "$name" "-"
}

health() {
  local name="$1"
  local url="$2"
  local body
  if body="$(curl -fsS --max-time 2 "$url" 2>/dev/null)"; then
    printf "%-12s ok       %s\n" "$name" "$body"
  else
    printf "%-12s failed   %s\n" "$name" "$url"
  fi
}

echo "profile=${TOBACCO_PROFILE}"
status_pid management || true
status_pid vision || true
status_pid text || true
status_pid audio || true
health management "http://127.0.0.1:${MANAGEMENT_PORT}/api/dashboard"
health vision "${VISION_SERVICE_URL}/health"
health text "${TEXT_SERVICE_URL}/health"
health audio "${AUDIO_SERVICE_URL}/health"
