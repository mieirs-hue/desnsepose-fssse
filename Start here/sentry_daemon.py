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

ROOM_WIDTH = 20.0
ROOM_DEPTH = 10.0
ROOM_HEIGHT = 9.0
NODE_A_POS = (ROOM_WIDTH, ROOM_DEPTH)
NODE_B_POS = (0.0, 0.0)

# Hardware assumption: both ESP32-S3 anchors are mounted vertically,
# with USB-C connectors facing downward.


@dataclass
class SignalState:
    signal_a: float = -80.0
    signal_b: float = -80.0
    last_x: float = 10.0
    last_y: float = 5.0
    last_z: float = 4.5

    def set_signal(self, node_id: str, value: float) -> None:
        if node_id == "A":
            self.signal_a = value
        elif node_id == "B":
            self.signal_b = value

    @staticmethod
    def _rssi_to_distance(dbm: float) -> float:
        # Calibrated to ~15ft practical overlap while still spanning room extremes.
        tx_power_at_1m = -50.0
        path_loss = 2.0
        distance = math.pow(10.0, (tx_power_at_1m - dbm) / (10.0 * path_loss))
        return max(0.6, min(25.0, distance))

    def calculate_spatial_vector(self) -> dict:
        r_a = self._rssi_to_distance(self.signal_a)
        r_b = self._rssi_to_distance(self.signal_b)

        x1, y1 = NODE_A_POS
        x2, y2 = NODE_B_POS
        d = math.hypot(x2 - x1, y2 - y1)

        a = (r_a * r_a - r_b * r_b + d * d) / (2.0 * d)
        a = max(0.0, min(d, a))
        h_sq = max(0.0, r_a * r_a - a * a)
        h = math.sqrt(h_sq)

        px = x1 + a * (x2 - x1) / d
        py = y1 + a * (y2 - y1) / d

        rx = -(y2 - y1) * (h / d)
        ry = (x2 - x1) * (h / d)

        candidates = [(px + rx, py + ry), (px - rx, py - ry)]

        def candidate_score(candidate: tuple[float, float]) -> float:
            cx, cy = candidate
            continuity = math.hypot(cx - self.last_x, cy - self.last_y)
            out_penalty = 0.0
            if cx < 0.0 or cx > ROOM_WIDTH:
                out_penalty += 20.0
            if cy < 0.0 or cy > ROOM_DEPTH:
                out_penalty += 20.0
            return continuity + out_penalty

        best_x, best_y = min(candidates, key=candidate_score)
        best_x = max(0.0, min(ROOM_WIDTH, best_x))
        best_y = max(0.0, min(ROOM_DEPTH, best_y))

        norm_a = max(0.0, min(1.0, (self.signal_a + 100.0) / 60.0))
        norm_b = max(0.0, min(1.0, (self.signal_b + 100.0) / 60.0))
        strength = (norm_a + norm_b) * 0.5
        z = 1.2 + strength * 6.5
        z = max(0.0, min(ROOM_HEIGHT, z))

        # Light temporal smoothing to remove jumpiness while preserving motion.
        alpha = 0.38
        self.last_x += (best_x - self.last_x) * alpha
        self.last_y += (best_y - self.last_y) * alpha
        self.last_z += (z - self.last_z) * alpha

        return {
            "x": round(self.last_x, 2),
            "y": round(self.last_y, 2),
            "z": round(self.last_z, 2),
        }


state = SignalState()


def parse_rssi(line: str) -> float | None:
    lowered = line.lower()
    # Prefer values explicitly tied to RSSI/dBm labels, but tolerate bare numeric lines too.
    labeled = re.search(r"(?:rssi|dbm|signal)\s*[:=]\s*(-?\d+(?:\.\d+)?)", lowered)
    if labeled:
        try:
            value = float(labeled.group(1))
            if -120.0 <= value <= -1.0:
                return value
        except ValueError:
            return None

    # Fallback: first realistic signed number in the line.
    match = re.search(r"(-?\d+(?:\.\d+)?)", lowered)
    if match:
        try:
            value = float(match.group(1))
            if -120.0 <= value <= -1.0:
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
