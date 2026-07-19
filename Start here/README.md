# Jesse Security Office Blueprint v1.0

Two-node DensePose FSSS office tracker with live operator dashboard, ESP32-S3 anchor ingest, and room-scale motion lock for Jesse.

## Mission Profile
- Detect and track Jesse inside the office footprint.
- Maintain usable contact even if one ESP32 anchor temporarily drops signal.
- Give a live tactical operator view with fast access to sensitivity, range, and perspective controls.
- Preserve the current two-node baseline while leaving a clean path to a four-node expansion.

## Current System Layout
- Room model: `20 ft x 15 ft`
- Active anchors: `ESP32-S3 Node A` and `ESP32-S3 Node B`
- Transport: USB serial from boards into Python daemon
- UI transport: HTTP on `:8080` and WebSocket on `:8765`
- Dashboard: `golf_green_interface.html`
- Runtime: `sentry_daemon.py`

## Operator Views
### Topside
- Primary tactical map.
- Best for testing room coverage, dual-board lock, and edge behavior.

### First-person (Jesse)
- Tilted view intended to feel more like being inside the room.
- Useful when validating whether movement feels responsive and natural.

### Outside Perspective
- Angled external overview.
- Useful for reading perimeter behavior and single-board fallback drift.

## Control Panel
### Frequency Strength
- Range: `1-20 Hz`
- Function: changes how quickly stale sensor readings are discarded.
- Higher values make the system react faster to disappearing or changing signals.

### Sensitivity
- Range: `10-100%`
- Function: changes occupancy trigger strength and daemon proximity thresholds.
- Higher values make the room lock onto weaker proximity evidence sooner.

### Perimeter Radius
- Range: `1-20 ft`
- Current design limit: `20 ft`
- Function: caps the fallback tracking radius so the system stays constrained to office-scale space.

### Inside Movement Accuracy
- Range: `10-100%`
- Function: adjusts smoothing versus responsiveness.
- Higher values produce tighter reticle response.
- Lower values produce steadier motion with less apparent jitter.

## FSSS Range Behavior
### Dual-board lock
- This is the preferred mode.
- The system selects the two strongest active anchors.
- RSSI from each board is converted to an estimated distance.
- The dashboard solves a floor position from the pair and stabilizes it with smoothing.

### Single-board fallback
- If only one board is fresh, the system does not drop Jesse immediately.
- It projects movement from the last known direction and constrains that projection inside the configured perimeter.
- This preserves continuity during temporary signal loss.

### Practical range notes
- In the current office model, `20 ft` perimeter covers the intended room without encouraging bleed-through from outside walls.
- RSSI is an estimate, not true tape-measure distance.
- Anchor orientation, body blocking, reflections, and BLE advertisement density all affect accuracy.

## ESP32-S3 Anchor Rules
- Mount both anchors vertically.
- Keep the USB-C connector facing downward on both units.
- Maintain consistent orientation between A and B during all testing.
- Keep anchor placement fixed while tuning sensitivity and smoothing.

## Two-Node Baseline Test Plan
### Test 1: Under Node A
- Move close to Node A.
- Expected result: stronger A beam influence and reticle bias toward A.

### Test 2: Under Node B
- Move close to Node B.
- Expected result: stronger B beam influence and reticle bias toward B.

### Test 3: Centerline walk
- Walk the middle of the room between anchors.
- Expected result: reticle should travel smoothly without hard snapping unless sensitivity and accuracy are set very high.

### Test 4: Edge sweep
- Move along office walls.
- Expected result: target remains bounded inside room geometry and does not drift beyond perimeter cap.

### Test 5: Brief occlusion
- Turn body between beacon path and one anchor.
- Expected result: system may drop to single-board fallback briefly, but should preserve general continuity.

## Four-Node Upgrade Path
- Add two more ESP32-S3 anchors to fill blind spots.
- Expand the node map in `config.json`.
- Allow the solver to choose the best pair set or evolve to multi-node least-error position solving.
- Expected gain: tighter corner resolution, fewer ambiguity zones, and reduced fallback reliance.

## Runtime Commands
### Launch live system
```bash
cd /home/unclejesse/desnsepose-fssse
./run_live.sh
```

### Launch simulation mode
```bash
cd "/home/unclejesse/desnsepose-fssse/Start here"
SIMULATE=1 ../.venv/bin/python sentry_daemon.py --simulate
```

## Files That Define The System
- `config.json`: office dimensions, nodes, and persisted UI control state
- `golf_green_interface.html`: tactical operator dashboard and live controls
- `sentry_daemon.py`: serial ingest, WebSocket feed, HTTP endpoints, runtime control persistence
- `requirements.txt`: Python dependencies
- `../run_live.sh`: preferred launcher for live hardware

## Operator Notes
- If the dashboard is open and moving, the browser should appear as one WebSocket client in daemon logs.
- Best baseline tuning order: perimeter first, sensitivity second, accuracy third, frequency last.
- During early tests, prioritize stable dual-board lock before chasing fine-grain reticle behavior.
