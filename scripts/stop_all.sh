#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

stop_pid_file() {
  local name="$1"
  local pid_file=".runtime/${name}.pid"
  if [[ ! -f "$pid_file" ]]; then
    echo "$name not tracked"
    return 0
  fi

  local pid
  pid="$(cat "$pid_file")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
    echo "$name stopped: pid=$pid"
  else
    echo "$name not running: pid=$pid"
  fi
  rm -f "$pid_file"
}

stop_pid_file management
stop_pid_file vision
stop_pid_file text
stop_pid_file audio
