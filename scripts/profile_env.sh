#!/usr/bin/env bash
set -euo pipefail

profile="${TOBACCO_PROFILE:-${1:-dev}}"

case "$profile" in
  dev)
    export TOBACCO_PROFILE=dev
    export USE_MOCK_MODEL="${USE_MOCK_MODEL:-true}"
    export TEXT_USE_MOCK_MODEL="${TEXT_USE_MOCK_MODEL:-true}"
    export ASR_ENGINE="${ASR_ENGINE:-mock}"
    export ALLOW_ASR_FALLBACK="${ALLOW_ASR_FALLBACK:-true}"
    export USE_MOCK_TRANSCRIPT="${USE_MOCK_TRANSCRIPT:-false}"
    ;;
  demo)
    export TOBACCO_PROFILE=demo
    export USE_MOCK_MODEL="${USE_MOCK_MODEL:-true}"
    export TEXT_USE_MOCK_MODEL="${TEXT_USE_MOCK_MODEL:-true}"
    export ASR_ENGINE="${ASR_ENGINE:-mock}"
    export ALLOW_ASR_FALLBACK="${ALLOW_ASR_FALLBACK:-true}"
    export USE_MOCK_TRANSCRIPT="${USE_MOCK_TRANSCRIPT:-true}"
    export MOCK_TRANSCRIPT="${MOCK_TRANSCRIPT:-刚到一批，需要的看主页，私聊安排。}"
    ;;
  real)
    export TOBACCO_PROFILE=real
    export USE_MOCK_MODEL="${USE_MOCK_MODEL:-false}"
    export TEXT_USE_MOCK_MODEL="${TEXT_USE_MOCK_MODEL:-false}"
    export ASR_ENGINE="${ASR_ENGINE:-whisper}"
    export ALLOW_ASR_FALLBACK="${ALLOW_ASR_FALLBACK:-false}"
    export USE_MOCK_TRANSCRIPT="${USE_MOCK_TRANSCRIPT:-false}"
    ;;
  *)
    echo "Unknown TOBACCO_PROFILE: $profile" >&2
    echo "Expected one of: dev, demo, real" >&2
    exit 2
    ;;
esac

export MANAGEMENT_HOST="${MANAGEMENT_HOST:-0.0.0.0}"
export MANAGEMENT_PORT="${MANAGEMENT_PORT:-8000}"
export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-9000}"
export TEXT_HOST="${TEXT_HOST:-0.0.0.0}"
export TEXT_PORT="${TEXT_PORT:-8010}"
export AUDIO_HOST="${AUDIO_HOST:-0.0.0.0}"
export AUDIO_PORT="${AUDIO_PORT:-8020}"
export VISION_SERVICE_URL="${VISION_SERVICE_URL:-http://127.0.0.1:${PORT}}"
export TEXT_SERVICE_URL="${TEXT_SERVICE_URL:-http://127.0.0.1:${TEXT_PORT}}"
export AUDIO_SERVICE_URL="${AUDIO_SERVICE_URL:-http://127.0.0.1:${AUDIO_PORT}}"
