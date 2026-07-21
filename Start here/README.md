# Jesse Security Office Blueprint v1.0

This document defines the live operator design for the two-node baseline (today) and the expansion path to a four-node grid.

## Mission Profile

- Track one moving target in a 20ft x 10ft office footprint.
- Keep target lock stable during normal movement.
- Hold static target line when motion is not detected.
- Preserve service continuity if one board drops temporarily.

## Physical Layout

- Anchor A: ESP32-S3 Nano mounted high on one side of the room.
- Anchor B: ESP32-S3 Nano mounted high on the opposite side of the room.
- Mounting orientation: vertical, USB-C connector at bottom.
- Current baseline geometry in config: room 20ft x 10ft x 10ft.

## Runtime Architecture

- Launcher: `./run_live.sh`
- Backend daemon: `sentry_daemon.py`
- HTTP dashboard: `http://127.0.0.1:8080`
- Live data channel: `ws://127.0.0.1:8765`

### Backend responsibilities

- Read RSSI streams from both serial ports.
- Parse and normalize node telemetry.
- Broadcast live motion data over WebSocket.
- Serve dashboard and runtime state endpoints.
- Persist operator control settings.
- Handle stale WebSocket clients gracefully.

## Telemetry-First Milestones (M1-M5)

Use these milestones before adding any advanced rendering:

1. M1 - Ingestion Contract
 - Require `rssi` on every packet.
 - Validate payload types and ranges before forwarding.
 - Reject malformed packets without crashing the daemon.

2. M2 - Identity Normalization
 - Resolve incoming `node`/`node_id` aliases to canonical node IDs.
 - Support explicit `mac_mappings` in `config.json` for deterministic routing.
 - Keep fallback routing per-port when identity is missing.

3. M3 - Health Telemetry
 - Track ingest counters (`lines_total`, `events_emitted`, rejections).
 - Track per-port status, line quality, and last-seen timestamps.
 - Track per-node packet counts, last RSSI, sequence continuity.

4. M4 - Runtime Introspection APIs
 - `GET /runtime/schema` for packet contract and active alias maps.
 - `GET /runtime/health` for ingest + port + node health snapshots.
 - `GET /runtime/state` includes schema version and ingest summary.

5. M5 - Pre-Visualization Verification
 - Verify stable `events_emitted` growth under live load.
 - Verify `schema_rejected` remains near zero.
 - Verify each physical board appears as a healthy node before enabling any 3D canvas.

### Telemetry Packet Contract (Current)

- Required fields:
 - `rssi` (integer, range `-120..-1`)

- Optional fields:
 - `node` or `node_id` (string)
 - `mac` (`aa:bb:cc:dd:ee:ff`)
 - `seq` (integer)
 - `ie` (string)
 - `node_label` (string)
 - `status` (string)

### Identity Mapping in config.json

- `node_aliases`: maps incoming names to canonical node IDs.
- `mac_mappings`: maps device MACs to canonical node IDs.

Example:

```json
{
	"node_aliases": {
		"NORTH": "A",
		"SOUTH": "B"
	},
	"mac_mappings": {
		"28:84:85:46:d8:cc": "A",
		"e0:72:a1:ce:d8:58": "B"
	}
}
```

### Frontend responsibilities

- Render live office map and target lock.
- Render persistent overlapping signal fields from both anchors.
- Apply static-hold behavior until motion evidence arrives.
- Expose operator controls and view modes.
- Display telemetry for quick calibration passes.

## Operator Controls

- Frequency Strength: update cadence and stale-reading timeout behavior.
- Sensitivity: proximity threshold aggressiveness.
- Perimeter Radius: hard geofence cap (up to 20ft).
- Inside Movement Accuracy: smoothing and continuity weighting.
- View Modes: Topside, First-person, Outside Perspective.

## Tracking Logic (Two-Node Baseline)

- Dual-node mode:
	- Uses two strongest fresh anchors.
	- Solves floor position with bounded weighted search.
	- Applies smoothing for jitter resistance.
- Single-node fallback:
	- Maintains lock continuity from strongest available anchor.
	- Constrains movement to configured perimeter.
- Motion policy:
	- No synthetic path generation.
	- Maintain static lock when no fresh motion indicators are present.

## Calibration Workflow (Live Pass)

Use this exact pass each tuning cycle:

1. Move to front-left edge and hold still for 3 to 5 seconds.
2. Move to center and hold still for 3 to 5 seconds.
3. Move to back-right edge and hold still for 3 to 5 seconds.
4. Record on-screen telemetry at each point:
	 - Position X
	 - Position Y
	 - Signal Estimate A
	 - Signal Estimate B
5. Adjust sensitivity and inside movement accuracy.
6. Repeat until position deltas match physical movement pattern.

## Validation Checklist

- Dashboard opens and stays connected.
- Both nodes report live data.
- Target remains stable while standing still.
- Target moves directionally with physical motion.
- Signal fields from both anchors overlap across the workspace.
- No daemon crashes or broadcast exception floods.

## Near-Term Upgrade Path (Four Nodes)

- Add two additional ESP32-S3 nodes to reduce blind zones.
- Extend solver from 2-anchor baseline to 3-to-4 anchor weighting.
- Increase confidence scoring and edge stability.
- Preserve the same operator controls and calibration procedure.

## Quick Start

From repository root:

```bash
./run_live.sh
```

Then open:

- `http://127.0.0.1:8080`

Health checks:

- `http://127.0.0.1:8080/runtime/schema`
- `http://127.0.0.1:8080/runtime/health`
