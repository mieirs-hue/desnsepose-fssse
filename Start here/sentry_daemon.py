import asyncio
import json
import os
import random
import sys
import time

import serial
import websockets
from aiohttp import web

def get_serial_ports():
    """Get serial ports from environment variables or use defaults."""
    if sys.platform.startswith("win"):
        default_port_a = "COM5"
        default_port_b = "COM10"
    else:
        default_port_a = "/dev/ttyACM0"
        default_port_b = "/dev/ttyACM1"

    return {
        "A": os.getenv("SENTRY_PORT_A", default_port_a),
        "B": os.getenv("SENTRY_PORT_B", default_port_b),
    }

BAUD_RATE = 115200

# Global set to hold connected WebSocket clients
CONNECTED_CLIENTS = set()

def load_config():
    """Loads configuration from config.json."""
    try:
        with open("config.json", "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[ERROR] Could not load or parse config.json: {e}", file=sys.stderr)
        # Fallback to default values
        return {
            "sensitivity": {"rssi_threshold_near": -60, "rssi_threshold_mid": -80}
        }

async def broadcast_message(message: str):
    """Broadcasts a message to all connected WebSocket clients."""
    if CONNECTED_CLIENTS:
        # Create a task to send messages to all clients concurrently
        await asyncio.gather(*[client.send(message) for client in CONNECTED_CLIENTS])

def parse_and_forward_rssi(line: str, node_id: str, thresholds: dict):
    """
    Parses a line for JSON RSSI data and forwards it as a motion event.
    """
    try:
        data = json.loads(line)
        if "rssi" in data and isinstance(data["rssi"], int):
            rssi = data["rssi"]
            # Proximity logic based on configurable thresholds
            if rssi > thresholds.get("rssi_threshold_near", -60):
                proximity = "near"
            elif rssi > thresholds.get("rssi_threshold_mid", -80):
                proximity = "mid"
            else:
                proximity = "far"

            motion_event = {
                "timestamp": time.time(),
                "node_id": node_id,
                "rssi": rssi,
                "proximity": proximity,
            }
            # Broadcast JSON motion events to WebSocket clients
            asyncio.create_task(broadcast_message(json.dumps(motion_event)))

    except (json.JSONDecodeError, TypeError):
        # Ignore lines that are not valid JSON
        pass


async def simulate_node(node_id: str, thresholds: dict) -> None:
    """Generates fake RSSI data for UI testing without hardware."""
    print(f"[SIM] Node {node_id} simulation started")
    # Walk RSSI up and down realistically
    rssi = random.randint(-80, -50)
    direction = 1
    while True:
        rssi += direction * random.randint(1, 4)
        if rssi > -40:
            direction = -1
        elif rssi < -90:
            direction = 1
        rssi = max(-95, min(-35, rssi))
        fake_line = json.dumps({"rssi": rssi, "node": node_id})
        parse_and_forward_rssi(fake_line, node_id, thresholds)
        await asyncio.sleep(0.3)


async def read_serial_node(node_id: str, port_name: str, thresholds: dict) -> None:
    """
    Connects to a serial port and reads data line by line.
    """
    print(f"[INIT] Node {node_id} on {port_name}")
    while True:
        ser = None
        try:
            # Use asyncio.to_thread for the blocking serial connection
            ser = await asyncio.to_thread(serial.Serial, port_name, BAUD_RATE, timeout=1)
            print(f"[ONLINE] Node {node_id} connected on {port_name}")
            while True:
                # Run the blocking readline call in a thread to avoid stalling the event loop
                line_bytes = await asyncio.to_thread(ser.readline)
                if line_bytes:
                    line = line_bytes.decode("utf-8", errors="ignore").strip()
                    if line:
                        parse_and_forward_rssi(line, node_id, thresholds)
        except Exception as exc:
            print(f"[WARN] Node {node_id} offline on {port_name}: {exc}")
            if ser and ser.is_open:
                ser.close()
            await asyncio.sleep(1.0)

async def websocket_handler(websocket: websockets.WebSocketServerProtocol):
    """Handles a new WebSocket connection."""
    CONNECTED_CLIENTS.add(websocket)
    print(f"[WS] Client connected. Total clients: {len(CONNECTED_CLIENTS)}")
    try:
        # Keep the connection open until the client disconnects
        await websocket.wait_closed()
    finally:
        CONNECTED_CLIENTS.remove(websocket)
        print(f"[WS] Client disconnected. Total clients: {len(CONNECTED_CLIENTS)}")

async def main() -> None:
    """
    Initializes and runs the serial reader tasks.
    """
    config = load_config()
    sensitivity_thresholds = config.get("sensitivity", {
        "rssi_threshold_near": -60,
        "rssi_threshold_mid": -80,
    })

    # --- HTTP Server Setup ---
    async def handle_index(request):
        return web.FileResponse('golf_green_interface.html')

    async def handle_config(request):
        return web.FileResponse('config.json')

    app = web.Application()
    app.add_routes([
        web.get('/', handle_index),
        web.get('/config.json', handle_config),
    ])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    print("[SYSTEM] 'Invisible Thesis' dashboard active at http://0.0.0.0:8080")

    # --- Serial Port / Simulation Tasks ---
    simulate = "--simulate" in sys.argv or os.getenv("SIMULATE", "").lower() in ("1", "true", "yes")
    if simulate:
        print("[SYSTEM] Running in SIMULATION mode — no hardware required.")
        node_ids = list(config.get("nodes", {"A": None, "B": None}).keys())
        serial_tasks = [
            asyncio.create_task(simulate_node(node_id, sensitivity_thresholds))
            for node_id in node_ids
        ]
    else:
        serial_ports = get_serial_ports()
        serial_tasks = [
            asyncio.create_task(read_serial_node(node_id, port, sensitivity_thresholds))
            for node_id, port in serial_ports.items()
        ]

    # --- WebSocket Server Task ---
    ws_server_task = websockets.serve(websocket_handler, "0.0.0.0", 8765)

    print("[SYSTEM] WebSocket server active on ws://0.0.0.0:8765")
    print("[SYSTEM] Dual DensePose FSSS daemon is fully operational.")
    await asyncio.gather(ws_server_task, *serial_tasks)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[SYSTEM] Daemon shut down by user.")
        sys.exit(0)
