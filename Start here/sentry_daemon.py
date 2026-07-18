import asyncio
import json
import math
import re
from dataclasses import dataclass

import serial
import websockets

# Explicit hardware mapping from your port audit
SERIAL_PORTS = {
    "A": "COM5",   # Left wall anchor at (0, 5, 9)
    "B": "COM10",  # Right wall anchor at (20, 5, 9)
}

BAUD_RATE = 115200
WS_HOST = "127.0.0.1"
WS_PORT = 8765


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
        # Office volume model: 20ft x 10ft x 18ft.
        norm_a = max(0.0, min(1.0, (self.signal_a + 100.0) / 60.0))
        norm_b = max(0.0, min(1.0, (self.signal_b + 100.0) / 60.0))

        x = 10.0 + (norm_a - norm_b) * 10.0
        y = 5.0 + math.sin((norm_a + norm_b) * math.pi) * 2.0
        z = (norm_a + norm_b) * 9.0

        return {
            "x": round(max(0.0, min(20.0, x)), 2),
            "y": round(max(0.0, min(10.0, y)), 2),
            "z": round(max(0.0, min(18.0, z)), 2),
        }


state = SignalState()


def parse_rssi(line: str) -> float | None:
    if "rssi" not in line.lower():
        return None

    # Accept values like: "RSSI: -67.5 dBm"
    match = re.search(r"(-?\d+(?:\.\d+)?)", line)
    if not match:
        return None

    try:
        return float(match.group(1))
    except ValueError:
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
