#!/usr/bin/env bash
# Starts the Brand Risk Index API + dashboard with the live news feed (macOS / Linux).
set -euo pipefail
cd "$(dirname "$0")/backend"
export REFRESH_MINUTES=${REFRESH_MINUTES:-15}
export LOOKBACK_HOURS=${LOOKBACK_HOURS:-48}
echo "Dashboard: http://127.0.0.1:${PORT:-8000}   API docs: http://127.0.0.1:${PORT:-8000}/docs"
exec ../.venv/bin/python api.py
