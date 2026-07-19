#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$ROOT_DIR/Start here"
VENV_DIR="${SENTRY_VENV_DIR:-/tmp/sentry-venv}"
PYTHON_BIN="$VENV_DIR/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  python3 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/pip" install --no-index --find-links="$HOME/.cache/pip" pyserial websockets aiohttp
fi

pkill -f "sentry_daemon.py" 2>/dev/null || true
cd "$APP_DIR"
exec "$PYTHON_BIN" sentry_daemon.py
