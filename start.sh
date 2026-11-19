#!/usr/bin/env bash
# Starts the NSE Brand Risk Monitor: dashboard + API + hourly live re-scoring (macOS / Linux).
set -euo pipefail
cd "$(dirname "$0")/backend"
export REFRESH_MINUTES=${REFRESH_MINUTES:-60}
echo "Dashboard: http://127.0.0.1:${PORT:-8000}   API docs: http://127.0.0.1:${PORT:-8000}/docs"
exec ../.venv/bin/python api.py
