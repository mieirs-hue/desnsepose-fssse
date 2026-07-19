#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$ROOT_DIR/Start here"
VENV_DIR="${SENTRY_VENV_DIR:-$ROOT_DIR/.venv}"
PYTHON_BIN="$VENV_DIR/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  python3 -m venv "$VENV_DIR"
fi

if ! "$PYTHON_BIN" -c "import serial, websockets, aiohttp" >/dev/null 2>&1; then
  if ! "$VENV_DIR/bin/pip" install --no-index --find-links="$HOME/.cache/pip" pyserial websockets aiohttp; then
    "$VENV_DIR/bin/pip" install pyserial websockets aiohttp
  fi
fi

pkill -f "sentry_daemon.py" 2>/dev/null || true
cd "$APP_DIR"
export SENTRY_PORTS="/dev/ttyACM0,/dev/ttyACM1"
exec "$PYTHON_BIN" sentry_daemon.py

