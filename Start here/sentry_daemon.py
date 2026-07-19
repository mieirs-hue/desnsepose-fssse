import asyncio
import json
import os
import random
import sys
import time
from typing import Any, Dict

import serial
from serial.tools import list_ports
import websockets
from aiohttp import web

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DASHBOARD_PATH = os.path.join(BASE_DIR, "golf_green_interface.html")

def get_serial_ports():
    """Get configured default serial ports for known nodes."""
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


def discover_candidate_ports(default_ports: dict):
    """Build a unique candidate list from env/default ports and live USB serial devices."""
    ports = []
    seen = set()

    # Explicit overrides have highest priority.
    explicit = os.getenv("SENTRY_PORTS", "").strip()
    if explicit:
        for raw in explicit.split(","):
            port = raw.strip()
            if port and port not in seen:
                ports.append(port)
                seen.add(port)

    # Add node default ports next.
    for port in default_ports.values():
        if port and port not in seen:
            ports.append(port)
            seen.add(port)

    # Finally append discovered USB serial devices only.
    try:
        discovered = []
        for port_info in list_ports.comports():
            device = port_info.device or ""
            if sys.platform.startswith("win"):
                if device.upper().startswith("COM"):
                    discovered.append(device)
            elif sys.platform == "darwin":
                base = os.path.basename(device)
                if base.startswith("cu.usb") or base.startswith("tty.usb"):
                    discovered.append(device)
            else:
                base = os.path.basename(device)
                if base.startswith("ttyACM") or base.startswith("ttyUSB"):
                    discovered.append(device)
        for port in discovered:
            if port and port not in seen:
                ports.append(port)
                seen.add(port)
    except Exception as exc:
        print(f"[WARN] Port discovery failed: {exc}")

    return ports

BAUD_RATE = 115200

# Global set to hold connected WebSocket clients
CONNECTED_CLIENTS = set()

def load_config():
    """Loads configuration from config.json."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[ERROR] Could not load or parse {CONFIG_PATH}: {e}", file=sys.stderr)
        # Fallback to default values
        return {
            "sensitivity": {"rssi_threshold_near": -60, "rssi_threshold_mid": -80}
        }


def save_config(config: Dict[str, Any]) -> None:
    """Persists config to disk atomically."""
    tmp_path = f"{CONFIG_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    os.replace(tmp_path, CONFIG_PATH)

async def broadcast_message(message: str):
    """Broadcasts a message to all connected WebSocket clients."""
    if CONNECTED_CLIENTS:
        # Create a task to send messages to all clients concurrently
        await asyncio.gather(*[client.send(message) for client in CONNECTED_CLIENTS])

def parse_and_forward_rssi(line: str, fallback_node_id: str, thresholds: dict, known_node_ids: set):
    """
    Parses a line for JSON RSSI data and forwards it as a motion event.
    """
    try:
        data = json.loads(line)
        if "rssi" in data and isinstance(data["rssi"], int):
            inferred_node = str(data.get("node_id") or data.get("node") or fallback_node_id).strip().upper()
            node_id = inferred_node if inferred_node in known_node_ids else fallback_node_id
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
        parse_and_forward_rssi(fake_line, node_id, thresholds, {node_id})
        await asyncio.sleep(0.3)


async def read_serial_port(port_name: str, thresholds: dict, known_node_ids: set) -> None:
    """
    Connects to a serial port and reads data line by line.
    Node identity is inferred from each JSON payload when possible.
    """
    fallback_node_id = "A"
    print(f"[INIT] Listening on {port_name}")
    while True:
        ser = None
        try:
            # Use asyncio.to_thread for the blocking serial connection
            ser = await asyncio.to_thread(serial.Serial, port_name, BAUD_RATE, timeout=1)
            print(f"[ONLINE] Serial connected on {port_name}")
            while True:
                # Run the blocking readline call in a thread to avoid stalling the event loop
                line_bytes = await asyncio.to_thread(ser.readline)
                if line_bytes:
                    line = line_bytes.decode("utf-8", errors="ignore").strip()
                    if line:
                        parse_and_forward_rssi(line, fallback_node_id, thresholds, known_node_ids)
        except Exception as exc:
            print(f"[WARN] Serial offline on {port_name}: {exc}")
            if ser and ser.is_open:
                ser.close()
            await asyncio.sleep(1.0)

async def websocket_handler(websocket):
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
    ui_controls = config.get("ui_controls", {
        "frequency_hz": 10,
        "sensitivity_pct": 42,
        "perimeter_ft": 20,
        "accuracy_pct": 72,
        "view_mode": "topside",
    })

    # --- HTTP Server Setup ---
    async def handle_index(request):
        return web.FileResponse(DASHBOARD_PATH)

    async def handle_config(request):
        return web.FileResponse(CONFIG_PATH)

    async def handle_runtime_state(request):
        payload = {
            "environment": config.get("environment", {}),
            "nodes": config.get("nodes", {}),
            "sensitivity": sensitivity_thresholds,
            "ui_controls": ui_controls,
        }
        return web.json_response(payload)

    async def handle_runtime_controls_update(request):
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)

        def clamp_int(value, low, high, fallback):
            try:
                n = int(value)
            except Exception:
                return fallback
            return max(low, min(high, n))

        next_controls = {
            "frequency_hz": clamp_int(payload.get("frequency_hz"), 1, 20, int(ui_controls.get("frequency_hz", 10))),
            "sensitivity_pct": clamp_int(payload.get("sensitivity_pct"), 10, 100, int(ui_controls.get("sensitivity_pct", 42))),
            "perimeter_ft": clamp_int(payload.get("perimeter_ft"), 1, 20, int(ui_controls.get("perimeter_ft", 20))),
            "accuracy_pct": clamp_int(payload.get("accuracy_pct"), 10, 100, int(ui_controls.get("accuracy_pct", 72))),
            "view_mode": str(payload.get("view_mode") or ui_controls.get("view_mode") or "topside").strip().lower(),
        }

        if next_controls["view_mode"] not in {"topside", "firstperson", "outside"}:
            next_controls["view_mode"] = "topside"

        ui_controls.update(next_controls)

        # Keep RSSI proximity thresholds in sync with sensitivity slider.
        sensitivity_pct = ui_controls["sensitivity_pct"]
        sensitivity_thresholds["rssi_threshold_near"] = int(-76 + (sensitivity_pct - 10) * (20 / 90))
        sensitivity_thresholds["rssi_threshold_mid"] = int(-90 + (sensitivity_pct - 10) * (18 / 90))

        config["ui_controls"] = dict(ui_controls)
        config["sensitivity"] = dict(sensitivity_thresholds)
        try:
            save_config(config)
        except Exception as exc:
            return web.json_response({"ok": False, "error": f"save_failed: {exc}"}, status=500)

        return web.json_response({
            "ok": True,
            "ui_controls": ui_controls,
            "sensitivity": sensitivity_thresholds,
        })

    app = web.Application()
    app.add_routes([
        web.get('/', handle_index),
        web.get('/config.json', handle_config),
        web.get('/runtime/state', handle_runtime_state),
        web.post('/runtime/controls', handle_runtime_controls_update),
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
        known_node_ids = {str(k).upper() for k in config.get("nodes", {}).keys()}
        candidate_ports = discover_candidate_ports(serial_ports)
        if not candidate_ports:
            # Keep default behavior if discovery yields nothing.
            candidate_ports = list(serial_ports.values())
        print(f"[SYSTEM] Candidate serial ports: {', '.join(candidate_ports)}")
        serial_tasks = [
            asyncio.create_task(read_serial_port(port, sensitivity_thresholds, known_node_ids))
            for port in candidate_ports
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
