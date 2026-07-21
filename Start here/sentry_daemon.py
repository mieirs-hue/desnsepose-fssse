import asyncio
import json
import os
import random
import re
import sys
import time
import math
from typing import Any, Dict, Optional, Tuple

import serial
from serial.tools import list_ports
import websockets
from websockets.exceptions import ConnectionClosed
from aiohttp import web

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DASHBOARD_PATH = os.path.join(BASE_DIR, "golf_green_interface.html")

TELEMETRY_SCHEMA_VERSION = "1.0"
MAC_RE = re.compile(r"^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$")

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

# 3D spatial anchors in feet (room centered at 0,0).
NODE_POSITIONS = {
    "NORTH": (0.0, 5.0, 9.0),
    "SOUTH": (0.0, -5.0, 9.0),
    "EAST": (10.0, 0.0, 9.0),
    "WEST": (-10.0, 0.0, 9.0),
}
TARGET_HEIGHT = 3.5
TRACK_WINDOW_SECONDS = 1.5
TRACK_DEFAULT_ID = "__ambient__"

def rssi_to_distance(rssi: int, tx_power: int = -45, path_loss_exponent: float = 2.5) -> float:
    if rssi == 0:
        return -1.0
    distance_meters = 10 ** ((tx_power - rssi) / (10 * path_loss_exponent))
    return distance_meters * 3.28084

def calculate_target_coordinates(active_rssi_readings: Dict[str, int]) -> Dict[str, Any]:
    total_weight = 0.0
    weighted_x = 0.0
    weighted_y = 0.0

    for node, rssi in active_rssi_readings.items():
        if node not in NODE_POSITIONS:
            continue

        slant_distance = rssi_to_distance(rssi)
        x, y, z = NODE_POSITIONS[node]
        dz = z - TARGET_HEIGHT
        if slant_distance > dz:
            floor_distance = math.sqrt(slant_distance ** 2 - dz ** 2)
        else:
            floor_distance = 0.1

        weight = 1.0 / (floor_distance ** 2)
        weighted_x += x * weight
        weighted_y += y * weight
        total_weight += weight

    if total_weight == 0:
        return {"x": 0.0, "y": 0.0, "status": "LOST"}

    return {
        "x": round(weighted_x / total_weight, 2),
        "y": round(weighted_y / total_weight, 2),
        "status": "LOCKED",
    }

def update_spatial_track(
    track_id: str,
    node_id: str,
    rssi: int,
    now_ts: float,
    track_store: Dict[str, Dict[str, Dict[str, Any]]],
) -> Dict[str, Any]:
    node_state = track_store.setdefault(track_id, {})
    node_state[node_id] = {"rssi": rssi, "ts": now_ts}

    active_rssi: Dict[str, int] = {}
    stale_nodes = []
    for key, value in node_state.items():
        age = now_ts - float(value.get("ts", 0.0))
        if age > TRACK_WINDOW_SECONDS or key not in NODE_POSITIONS:
            stale_nodes.append(key)
            continue
        active_rssi[key] = int(value["rssi"])

    for stale in stale_nodes:
        node_state.pop(stale, None)

    estimate = calculate_target_coordinates(active_rssi)
    contributors = sorted(active_rssi.keys())
    if not contributors:
        estimate["status"] = "LOST"
    elif len(contributors) < 2 and estimate.get("status") == "LOCKED":
        estimate["status"] = "ACQUIRING"

    estimate["contributors"] = contributors
    estimate["track_id"] = track_id
    return estimate

# Global set to hold connected WebSocket clients
CONNECTED_CLIENTS = set()

# Runtime ingest/health state
PORT_HEALTH: Dict[str, Dict[str, Any]] = {}
NODE_HEALTH: Dict[str, Dict[str, Any]] = {}
INGEST_STATS: Dict[str, Any] = {
    "lines_total": 0,
    "json_ok": 0,
    "events_emitted": 0,
    "invalid_json": 0,
    "schema_rejected": 0,
    "unknown_node": 0,
    "last_error": None,
}


def _normalize_mac(value: Any) -> Optional[str]:
    if value is None:
        return None
    mac = str(value).strip().lower()
    if MAC_RE.match(mac):
        return mac
    return None


def build_node_aliases(config: Dict[str, Any]) -> Tuple[set, Dict[str, str], Dict[str, str], Dict[str, str]]:
    """Build known-node set, alias lookup, labels, and MAC-to-node mappings."""
    nodes_cfg = config.get("nodes", {}) or {}
    known_node_ids = {str(node_id).strip().upper() for node_id in nodes_cfg.keys() if str(node_id).strip()}

    aliases: Dict[str, str] = {}
    labels: Dict[str, str] = {}

    for node_id, node_cfg in nodes_cfg.items():
        canonical = str(node_id).strip().upper()
        if not canonical:
            continue

        display_label = str(
            (node_cfg or {}).get("label")
            or (node_cfg or {}).get("name")
            or node_id
        ).strip()
        labels[canonical] = display_label

        candidate_aliases = {canonical, display_label.upper()}
        for alias in (node_cfg or {}).get("aliases", []) or []:
            alias_text = str(alias).strip().upper()
            if alias_text:
                candidate_aliases.add(alias_text)

        for alias_text in candidate_aliases:
            aliases[alias_text] = canonical

    for alias, mapped_node in (config.get("node_aliases") or {}).items():
        alias_text = str(alias).strip().upper()
        mapped_text = str(mapped_node).strip().upper()
        if alias_text and mapped_text:
            aliases[alias_text] = mapped_text

    mac_to_node: Dict[str, str] = {}
    for mac, mapped_node in (config.get("mac_mappings") or {}).items():
        norm_mac = _normalize_mac(mac)
        mapped_text = str(mapped_node).strip().upper()
        if norm_mac and mapped_text:
            mac_to_node[norm_mac] = mapped_text

    return known_node_ids, aliases, labels, mac_to_node


def update_port_health(port_name: str, *, connected: Optional[bool] = None, line_ok: Optional[bool] = None, error: Optional[str] = None) -> None:
    state = PORT_HEALTH.setdefault(port_name, {
        "connected": False,
        "last_connect_ts": None,
        "last_seen_ts": None,
        "last_error": None,
        "lines_ok": 0,
        "lines_bad": 0,
    })
    now = time.time()

    if connected is True:
        state["connected"] = True
        state["last_connect_ts"] = now
    elif connected is False:
        state["connected"] = False

    if line_ok is True:
        state["lines_ok"] += 1
        state["last_seen_ts"] = now
    elif line_ok is False:
        state["lines_bad"] += 1

    if error:
        state["last_error"] = error


def update_node_health(node_id: str, *, rssi: int, seq: Optional[int], mac: Optional[str]) -> None:
    state = NODE_HEALTH.setdefault(node_id, {
        "packets": 0,
        "last_seen_ts": None,
        "last_rssi": None,
        "last_seq": None,
        "duplicate_seq": 0,
        "last_mac": None,
    })
    state["packets"] += 1
    state["last_seen_ts"] = time.time()
    state["last_rssi"] = rssi
    if mac:
        state["last_mac"] = mac
    if seq is not None:
        if state["last_seq"] == seq:
            state["duplicate_seq"] += 1
        state["last_seq"] = seq


def validate_payload_schema(data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    if not isinstance(data, dict):
        return False, "payload_not_object"

    if "rssi" not in data:
        return False, "missing_rssi"

    if not isinstance(data.get("rssi"), int):
        return False, "invalid_rssi_type"

    rssi = data["rssi"]
    if rssi < -120 or rssi > -1:
        return False, "rssi_out_of_range"

    if "seq" in data and data["seq"] is not None and not isinstance(data["seq"], int):
        return False, "invalid_seq_type"

    if "mac" in data and data["mac"] is not None and _normalize_mac(data["mac"]) is None:
        return False, "invalid_mac_format"

    return True, None

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
    if not CONNECTED_CLIENTS:
        return

    stale_clients = []
    for client in tuple(CONNECTED_CLIENTS):
        try:
            await client.send(message)
        except (ConnectionClosed, TimeoutError, RuntimeError):
            stale_clients.append(client)
        except Exception as exc:
            print(f"[WS] Send failure: {exc}")
            stale_clients.append(client)

    for client in stale_clients:
        CONNECTED_CLIENTS.discard(client)

def parse_and_forward_rssi(
    line: str,
    fallback_node_id: str,
    thresholds: dict,
    known_node_ids: set,
    node_aliases: Dict[str, str],
    node_labels: Dict[str, str],
    mac_to_node: Dict[str, str],
    port_name: Optional[str] = None,
):
    """
    Parses a line for JSON RSSI data and forwards it as a motion event.
    """
    INGEST_STATS["lines_total"] += 1
    try:
        data = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        INGEST_STATS["invalid_json"] += 1
        if port_name:
            update_port_health(port_name, line_ok=False)
        return

    INGEST_STATS["json_ok"] += 1

    ok, reason = validate_payload_schema(data)
    if not ok:
        INGEST_STATS["schema_rejected"] += 1
        INGEST_STATS["last_error"] = reason
        if port_name:
            update_port_health(port_name, line_ok=False, error=reason)
        return

    raw_node = str(data.get("node_id") or data.get("node") or "").strip()
    raw_node_upper = raw_node.upper()
    mac = _normalize_mac(data.get("mac"))

    mapped_from_alias = node_aliases.get(raw_node_upper)
    mapped_from_mac = mac_to_node.get(mac) if mac else None
    inferred_node = mapped_from_alias or mapped_from_mac or fallback_node_id
    node_id = inferred_node if inferred_node in known_node_ids else fallback_node_id
    if inferred_node not in known_node_ids:
        INGEST_STATS["unknown_node"] += 1

    rssi = int(data["rssi"])
    seq = data.get("seq") if isinstance(data.get("seq"), int) else None

    if rssi > thresholds.get("rssi_threshold_near", -60):
        proximity = "near"
    elif rssi > thresholds.get("rssi_threshold_mid", -80):
        proximity = "mid"
    else:
        proximity = "far"

    motion_event = {
        "timestamp": time.time(),
        "schema_version": TELEMETRY_SCHEMA_VERSION,
        "node_id": node_id,
        "node_label": node_labels.get(node_id, node_id),
        "raw_node": raw_node or None,
        "source_port": port_name,
        "rssi": rssi,
        "proximity": proximity,
        "seq": seq,
        "mac": mac,
        "ie": data.get("ie") if isinstance(data.get("ie"), str) else None,
    }

    if port_name:
        update_port_health(port_name, line_ok=True)
    update_node_health(node_id, rssi=rssi, seq=seq, mac=mac)

    INGEST_STATS["events_emitted"] += 1
    asyncio.create_task(broadcast_message(json.dumps(motion_event)))


async def simulate_node(
    node_id: str,
    thresholds: dict,
    known_node_ids: set,
    node_aliases: Dict[str, str],
    node_labels: Dict[str, str],
    mac_to_node: Dict[str, str],
) -> None:
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
        parse_and_forward_rssi(
            fake_line,
            node_id,
            thresholds,
            known_node_ids,
            node_aliases,
            node_labels,
            mac_to_node,
            port_name=f"SIM:{node_id}",
        )
        await asyncio.sleep(0.3)


async def read_serial_port(
    port_name: str,
    fallback_node_id: str,
    thresholds: dict,
    known_node_ids: set,
    node_aliases: Dict[str, str],
    node_labels: Dict[str, str],
    mac_to_node: Dict[str, str],
) -> None:
    """
    Connects to a serial port and reads data line by line.
    Node identity is inferred from each JSON payload when possible.
    """
    print(f"[INIT] Listening on {port_name}")
    update_port_health(port_name, connected=False)
    while True:
        ser = None
        try:
            # Use asyncio.to_thread for the blocking serial connection
            ser = await asyncio.to_thread(serial.Serial, port_name, BAUD_RATE, timeout=1)
            print(f"[ONLINE] Serial connected on {port_name}")
            update_port_health(port_name, connected=True)
            while True:
                # Run the blocking readline call in a thread to avoid stalling the event loop
                line_bytes = await asyncio.to_thread(ser.readline)
                if line_bytes:
                    line = line_bytes.decode("utf-8", errors="ignore").strip()
                    if line:
                        parse_and_forward_rssi(
                            line,
                            fallback_node_id,
                            thresholds,
                            known_node_ids,
                            node_aliases,
                            node_labels,
                            mac_to_node,
                            port_name=port_name,
                        )
        except Exception as exc:
            print(f"[WARN] Serial offline on {port_name}: {exc}")
            update_port_health(port_name, connected=False, error=str(exc))
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
        CONNECTED_CLIENTS.discard(websocket)
        print(f"[WS] Client disconnected. Total clients: {len(CONNECTED_CLIENTS)}")

async def main() -> None:
    """
    Initializes and runs the serial reader tasks.
    """
    config = load_config()
    known_node_ids, node_aliases, node_labels, mac_to_node = build_node_aliases(config)

    if not known_node_ids:
        known_node_ids = {"A", "B"}
        node_aliases.update({"A": "A", "B": "B"})
        node_labels.update({"A": "A", "B": "B"})
    sensitivity_thresholds = config.get("sensitivity", {
        "rssi_threshold_near": -60,
        "rssi_threshold_mid": -80,
    })
    ui_controls = config.get("ui_controls", {
        "frequency_hz": 10,
        "sensitivity_pct": 42,
        "perimeter_ft": 20,
        "accuracy_pct": 72,
        "board_a_boost_db": 0,
        "board_b_boost_db": 0,
        "motion_scale_pct": 140,
        "motion_deadband_ft": 0.9,
        "view_mode": "topside",
    })

    # --- HTTP Server Setup ---
    async def handle_index(request):
        return web.FileResponse(DASHBOARD_PATH)

    async def handle_config(request):
        return web.FileResponse(CONFIG_PATH)

    async def handle_runtime_health(request):
        now = time.time()
        node_health = {}
        for node_id, state in NODE_HEALTH.items():
            age_s = None
            if state.get("last_seen_ts"):
                age_s = round(now - float(state["last_seen_ts"]), 3)
            node_health[node_id] = {
                **state,
                "stale": age_s is None or age_s > 3.5,
                "age_s": age_s,
            }

        port_health = {}
        for port_name, state in PORT_HEALTH.items():
            age_s = None
            if state.get("last_seen_ts"):
                age_s = round(now - float(state["last_seen_ts"]), 3)
            port_health[port_name] = {
                **state,
                "age_s": age_s,
            }

        return web.json_response({
            "ok": True,
            "timestamp": now,
            "ingest": dict(INGEST_STATS),
            "ports": port_health,
            "nodes": node_health,
        })

    async def handle_runtime_schema(request):
        return web.json_response({
            "ok": True,
            "schema_version": TELEMETRY_SCHEMA_VERSION,
            "required": ["rssi"],
            "optional": ["node", "node_id", "mac", "seq", "ie", "node_label", "status"],
            "constraints": {
                "rssi": "int in [-120, -1]",
                "mac": "lowercase aa:bb:cc:dd:ee:ff",
                "seq": "int (optional)",
            },
            "node_aliases": node_aliases,
            "known_node_ids": sorted(known_node_ids),
            "mac_mappings": mac_to_node,
        })

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
            "board_a_boost_db": clamp_int(payload.get("board_a_boost_db"), -12, 12, int(ui_controls.get("board_a_boost_db", 0))),
            "board_b_boost_db": clamp_int(payload.get("board_b_boost_db"), -12, 12, int(ui_controls.get("board_b_boost_db", 0))),
            "motion_scale_pct": clamp_int(payload.get("motion_scale_pct"), 60, 220, int(ui_controls.get("motion_scale_pct", 140))),
            "view_mode": str(payload.get("view_mode") or ui_controls.get("view_mode") or "topside").strip().lower(),
        }

        try:
            next_controls["motion_deadband_ft"] = float(payload.get("motion_deadband_ft", ui_controls.get("motion_deadband_ft", 0.9)))
        except Exception:
            next_controls["motion_deadband_ft"] = float(ui_controls.get("motion_deadband_ft", 0.9))
        next_controls["motion_deadband_ft"] = max(0.1, min(3.0, next_controls["motion_deadband_ft"]))

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

    async def handle_baseline_capture(request):
        """Capture current telemetry as baseline."""
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)

        baseline_data = {
            "rssi_a": payload.get("rssi_a"),
            "rssi_b": payload.get("rssi_b"),
            "estimate_a": payload.get("estimate_a"),
            "estimate_b": payload.get("estimate_b"),
            "timestamp": time.time(),
        }

        if "baseline" not in config:
            config["baseline"] = {}
        config["baseline"] = baseline_data

        try:
            save_config(config)
        except Exception as exc:
            return web.json_response({"ok": False, "error": f"save_failed: {exc}"}, status=500)

        return web.json_response({
            "ok": True,
            "baseline": baseline_data,
        })

    async def handle_baseline_clear(request):
        """Clear the baseline."""
        if "baseline" in config:
            del config["baseline"]

        try:
            save_config(config)
        except Exception as exc:
            return web.json_response({"ok": False, "error": f"save_failed: {exc}"}, status=500)

        return web.json_response({"ok": True, "baseline": None})

    async def handle_runtime_state(request):
        """Return full runtime state including baseline."""
        payload = {
            "environment": config.get("environment", {}),
            "nodes": config.get("nodes", {}),
            "sensitivity": sensitivity_thresholds,
            "ui_controls": ui_controls,
            "baseline": config.get("baseline"),
            "schema_version": TELEMETRY_SCHEMA_VERSION,
            "ingest": {
                "events_emitted": INGEST_STATS.get("events_emitted", 0),
                "schema_rejected": INGEST_STATS.get("schema_rejected", 0),
                "invalid_json": INGEST_STATS.get("invalid_json", 0),
            },
        }
        return web.json_response(payload)

    app = web.Application()
    app.add_routes([
        web.get('/', handle_index),
        web.get('/config.json', handle_config),
        web.get('/runtime/state', handle_runtime_state),
        web.get('/runtime/health', handle_runtime_health),
        web.get('/runtime/schema', handle_runtime_schema),
        web.post('/runtime/controls', handle_runtime_controls_update),
        web.post('/runtime/baseline/capture', handle_baseline_capture),
        web.post('/runtime/baseline/clear', handle_baseline_clear),
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
        node_ids = [str(n).strip().upper() for n in config.get("nodes", {"A": None, "B": None}).keys()]
        serial_tasks = [
            asyncio.create_task(simulate_node(
                node_id,
                sensitivity_thresholds,
                known_node_ids,
                node_aliases,
                node_labels,
                mac_to_node,
            ))
            for node_id in node_ids
        ]
    else:
        serial_ports = get_serial_ports()
        candidate_ports = discover_candidate_ports(serial_ports)
        if not candidate_ports:
            # Keep default behavior if discovery yields nothing.
            candidate_ports = list(serial_ports.values())
        print(f"[SYSTEM] Candidate serial ports: {', '.join(candidate_ports)}")

        ordered_nodes = sorted(known_node_ids)
        if not ordered_nodes:
            ordered_nodes = ["A", "B"]

        port_fallbacks: Dict[str, str] = {}
        for idx, port in enumerate(candidate_ports):
            port_fallbacks[port] = ordered_nodes[idx % len(ordered_nodes)]

        serial_tasks = [
            asyncio.create_task(read_serial_port(
                port,
                port_fallbacks.get(port, ordered_nodes[0]),
                sensitivity_thresholds,
                known_node_ids,
                node_aliases,
                node_labels,
                mac_to_node,
            ))
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
