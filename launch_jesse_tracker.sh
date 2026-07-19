#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"
/usr/bin/gnome-terminal -- bash -lc './run_live.sh; exec bash' &
/usr/bin/xdg-open 'http://127.0.0.1:8080/?v=2' >/dev/null 2>&1 &
