# Sentry Matrix (Terminal Truth Mode)

This mode removes the browser dashboard and prints raw proximity state directly to the terminal.

## Output States
- `NEAR_A`: Node A RSSI is stronger than Node B and above `-60 dBm`.
- `NEAR_B`: Node B RSSI is stronger than Node A and above `-60 dBm`.
- `MID`: all other conditions.

## Files
- `sentry_daemon.py`: Reads RSSI from both ESP32-S3 nodes and prints state changes.
- `requirements.txt`: Python dependency list (`pyserial`).

## Setup
1. Open terminal in this folder.
2. Install dependencies:

```bash
./.venv/bin/python -m pip install -r requirements.txt
```

3. Run daemon:

```bash
./.venv/bin/python sentry_daemon.py
```

## Ports
- Linux defaults: `/dev/ttyACM0` and `/dev/ttyACM1`
- Windows defaults: `COM5` and `COM10`

Override with environment variables:
- `SENTRY_PORT_A`
- `SENTRY_PORT_B`

Example:

```bash
SENTRY_PORT_A=/dev/ttyACM1 SENTRY_PORT_B=/dev/ttyACM0 ./.venv/bin/python sentry_daemon.py
```
