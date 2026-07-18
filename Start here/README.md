# Sentry Matrix (RF-Only)

## Files
- `sentry_daemon.py`: Reads RSSI from COM5/COM10 and broadcasts telemetry on `ws://127.0.0.1:8765`.
- `index.html`: 3D isometric dashboard for live tracking visualization.
- `requirements.txt`: Python dependencies.

## Setup
1. Open a terminal in this folder.
2. Install packages:

```powershell
pip install -r requirements.txt
```

3. Start the telemetry daemon:

```powershell
python sentry_daemon.py
```

4. Open `index.html` in a browser.

## Data Format Expected from ESP32-S3 Nodes
The daemon looks for lines containing `rssi` and parses the first number. Example accepted lines:
- `RSSI: -67`
- `node_a_rssi=-72.4 dBm`

If a node is offline, the daemon automatically switches that node to simulation mode so the UI stays active.
