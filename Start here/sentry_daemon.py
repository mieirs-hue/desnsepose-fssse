import asyncio
import json
import math
import os
import re
import sys
from dataclasses import dataclass

import serial
import websockets

if sys.platform.startswith("win"):
    default_port_a = "COM5"
    default_port_b = "COM10"
else:
    default_port_a = "/dev/ttyACM0"
    default_port_b = "/dev/ttyACM1"

# Allow overriding from environment for flexible deployment.
SERIAL_PORTS = {
    "A": os.getenv("SENTRY_PORT_A", default_port_a),
    "B": os.getenv("SENTRY_PORT_B", default_port_b),
}

BAUD_RATE = 115200
WS_HOST = "127.0.0.1"
WS_PORT = 8765

# Hardware assumption: both ESP32-S3 anchors are mounted vertically,
# with USB-C connectors facing downward.


@dataclass
class SignalState:
    signal_a: float = -80.0
    signal_b: float = -80.0

    def set_signal(self, node_id: str, value: float) -> None:
        if node_id == "A":
            self.signal_a = value
        elif node_id == "B":
            self.signal_b = value

    def calculate_spatial_vector(self) -> dict:
        # Office volume model: 20ft x 10ft x 9ft (single story).
        norm_a = max(0.0, min(1.0, (self.signal_a + 100.0) / 60.0))
        norm_b = max(0.0, min(1.0, (self.signal_b + 100.0) / 60.0))

        # Differential model: avoid periodic trajectories from trig-based mapping.
        # balance < 0 means stronger B, balance > 0 means stronger A.
        balance = norm_a - norm_b
        strength = (norm_a + norm_b) * 0.5

        x = 10.0 + balance * 9.0
        y = 5.0 + (strength - 0.5) * 4.0 + balance * 1.2
        z = 1.5 + strength * 6.0

        return {
            "x": round(max(0.0, min(20.0, x)), 2),
            "y": round(max(0.0, min(10.0, y)), 2),
            "z": round(max(0.0, min(9.0, z)), 2),
        }


state = SignalState()


def parse_rssi(line: str) -> float | None:
    lowered = line.lower()
    if "rssi" not in lowered:
        return None

    # Prefer values explicitly tied to RSSI labels.
    labeled = re.search(r"rssi\s*[:=]\s*(-?\d+(?:\.\d+)?)", lowered)
    if labeled:
        try:
            value = float(labeled.group(1))
            if -120.0 <= value <= 20.0:
                return value
        except ValueError:
            return None

    # Fallback: first realistic dBm-like negative number in the line.
    match = re.search(r"(-\d+(?:\.\d+)?)", lowered)
    if match:
        try:
            value = float(match.group(1))
            if -120.0 <= value <= -20.0:
                return value
        except ValueError:
            return None

    return None


async def read_serial_node(node_id: str, port_name: str) -> None:
    print(f"[INIT] Tethering lighthouse node {node_id} on {port_name}...")

    try:
        with serial.Serial(port_name, BAUD_RATE, timeout=1) as ser:
            while True:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
                value = parse_rssi(line)
                if value is not None:
                    state.set_signal(node_id, value)
                await asyncio.sleep(0.01)
    except Exception as exc:
        print(f"[WARN] Node {node_id} offline ({exc}). Entering simulation for node {node_id}.")

        while True:
            t = asyncio.get_running_loop().time()
            if node_id == "A":
                state.signal_a = -62.0 + math.sin(t * 0.8) * 12.0
            else:
                state.signal_b = -64.0 + math.cos(t * 0.5) * 10.0
            await asyncio.sleep(0.05)


async def broadcast_telemetry(websocket) -> None:
    print("[SOCKET] Frontend connected.")
    try:
        while True:
            payload = {
                "vector": state.calculate_spatial_vector(),
                "node_a_dbm": round(state.signal_a, 1),
                "node_b_dbm": round(state.signal_b, 1),
                "timestamp": round(asyncio.get_running_loop().time(), 3),
            }
            await websocket.send(json.dumps(payload))
            await asyncio.sleep(0.09)
    except websockets.exceptions.ConnectionClosed:
        print("[SOCKET] Frontend disconnected.")


async def main() -> None:
    asyncio.create_task(read_serial_node("A", SERIAL_PORTS["A"]))
    asyncio.create_task(read_serial_node("B", SERIAL_PORTS["B"]))

    server = await websockets.serve(broadcast_telemetry, WS_HOST, WS_PORT)
    print(f"[ONLINE] Matrix daemon active at ws://{WS_HOST}:{WS_PORT}")
    await server.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
