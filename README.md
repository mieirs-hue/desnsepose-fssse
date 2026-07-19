# Sentry Matrix (Terminal Truth Mode)

RF-only proximity classification using two ESP32-S3 anchors and a Python terminal daemon.

## Project Layout
- `Start here/sentry_daemon.py` - serial RSSI ingest and terminal-only state output (`NEAR_A`, `NEAR_B`, `MID`).
- `Start here/requirements.txt` - Python dependencies.

## Anchor Mounting Rule
- ESP32-S3 anchors must be mounted vertically.
- USB-C connector faces downward for both boards.
- Keep this orientation consistent when calibrating or comparing A/B RSSI.

## Quick Start
1. Open a terminal in `Start here`.
2. Install dependencies:
   - `./.venv/bin/python -m pip install -r requirements.txt`
3. Run daemon:
   - `./.venv/bin/python sentry_daemon.py`
4. Watch terminal state changes (no browser UI).
