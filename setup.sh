#!/usr/bin/env bash
# One-time setup on macOS / Linux: creates .venv and installs everything.
# Needs Python 3.10+.
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
"$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
if [[ "$(uname)" == "Darwin" ]]; then
  .venv/bin/python -m pip install torch
else
  .venv/bin/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
fi
.venv/bin/python -m pip install -r backend/requirements.txt
echo
echo "Setup complete. Run ./start.sh, then open http://localhost:8000"
echo "(FinBERT, about 440 MB, downloads automatically on the first run.)"
