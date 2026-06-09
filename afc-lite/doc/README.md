# AFC Lite (Automated Filament Changer)

Lightweight multi-material support for the Snapmaker U1's four toolheads, ported from the extended
firmware. It installs three Klipper extras (`AFC`, `AFC_unit`, `AFC_lane`) and a config that wires
the four lanes to the U1's extruders and filament motion sensors, then exposes gcode macros for
tracking and changing filament.

## What it installs

- **Klipper extras** into `klippy/extras/`: `AFC.py`, `AFC_unit.py`, `AFC_lane.py`.
- **`afc-lite.cfg`**: one `[AFC]`, one `[AFC_unit U1]`, and four `[AFC_lane E0..E3]` mapped to
  `extruder`/`extruder1..3` and the `e0..e3_filament` motion sensors.

## Macros

`SET_COLOR`, `SET_MATERIAL`, `SET_VENDOR`, `SET_MAP`, `SET_SPOOL_ID`, `SET_WEIGHT`, `CHANGE_TOOL`,
`LANE_UNLOAD`, `TOOL_UNLOAD`. Per-lane state is pushed into the U1's `SET_PRINT_FILAMENT_CONFIG`, so
the screen and slicer stay in sync with what is loaded in each lane.

## Notes

- Snapmaker U1 only: the lane-to-extruder map and the filament-sensor names are U1 specific.
- Restarts Klipper on install so the new extras and config load.

> Not yet verified on a physical U1.
