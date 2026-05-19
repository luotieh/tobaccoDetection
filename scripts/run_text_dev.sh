#!/usr/bin/env bash
set -euo pipefail
uvicorn text_service.main:app --host "${TEXT_HOST:-0.0.0.0}" --port "${TEXT_PORT:-8010}" --reload
