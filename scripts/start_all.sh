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

mkdir -p .runtime

pid_on_port() {
  local port="$1"
  ss -ltnp 2>/dev/null | awk -v port=":${port}" '$4 ~ port "$" { if (match($0, /pid=[0-9]+/)) { print substr($0, RSTART + 4, RLENGTH - 4); exit } }'
}

start_service() {
  local name="$1"
  local port="$2"
  shift
  shift
  local pid_file=".runtime/${name}.pid"
  local log_file=".runtime/${name}.log"

  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
      echo "$name already running: pid=$pid"
      return 0
    fi
    rm -f "$pid_file"
  fi

  local port_pid
  port_pid="$(pid_on_port "$port" || true)"
  if [[ -n "$port_pid" ]]; then
    echo "$port_pid" >"$pid_file"
    echo "$name already running on port $port: pid=$port_pid"
    return 0
  fi

  nohup "$@" >"$log_file" 2>&1 &
  echo "$!" >"$pid_file"
  echo "$name started: pid=$(cat "$pid_file") log=$log_file"
}

start_service vision "$PORT" python3 -m uvicorn app.main:app --host "$HOST" --port "$PORT"
start_service text "$TEXT_PORT" python3 -m uvicorn text_service.main:app --host "$TEXT_HOST" --port "$TEXT_PORT"
start_service audio "$AUDIO_PORT" python3 -m uvicorn audio_service.main:app --host "$AUDIO_HOST" --port "$AUDIO_PORT"
start_service management "$MANAGEMENT_PORT" python3 app.py "$MANAGEMENT_PORT"

echo "profile=$TOBACCO_PROFILE"
echo "management=http://127.0.0.1:${MANAGEMENT_PORT}"
echo "vision=${VISION_SERVICE_URL}"
echo "text=${TEXT_SERVICE_URL}"
echo "audio=${AUDIO_SERVICE_URL}"
