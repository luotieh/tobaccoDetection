#!/usr/bin/env bash
set -euo pipefail
uvicorn audio_service.main:app --host "${AUDIO_HOST:-0.0.0.0}" --port "${AUDIO_PORT:-8020}" --reload
