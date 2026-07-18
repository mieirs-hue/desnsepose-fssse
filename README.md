# Sentry Matrix V3D

RF-only spatial tracking dashboard using two ESP32-S3 anchors and a Python telemetry daemon.

## Project Layout
- `Start here/sentry_daemon.py` - serial RSSI ingest from COM5/COM10 and websocket broadcast.
- `Start here/index.html` - tactical multi-view dashboard with zoom and run controls.
- `Start here/requirements.txt` - Python dependencies.

## Quick Start
1. Open a terminal in `Start here`.
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Run daemon:
   - `python sentry_daemon.py`
4. Open `Start here/index.html`.
