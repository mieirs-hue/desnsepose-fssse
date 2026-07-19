# Sentry Matrix V3D

RF-only spatial tracking dashboard using two ESP32-S3 anchors and a Python telemetry daemon.

## Project Layout
- `Start here/sentry_daemon.py` - serial RSSI ingest from /dev/ttyACM0 and /dev/ttyACM1 (Linux) or COM5/COM10 (Windows), then websocket broadcast.
- `Start here/index.html` - tactical multi-view dashboard with zoom and run controls.
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
4. Open `Start here/index.html`.
