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

- `CHANGE_TOOL` (Load button) loads filament.
- `TOOL_UNLOAD` (Unload button) unloads filament.
- `LANE_UNLOAD` (Eject button) docks (parks) the tool via `PARK_EXTRUDER`. It moves no filament.

## Filament names

The AFC panel shows a lane's filament name only when the lane reports a Spoolman `spool_id` that the
Spoolman store can resolve. A lane resolves its id, in order, from: a direct `SET_SPOOL_ID`, then an
RFID tag, then the spool you pick for the lane's tool in the Spoolman panel's "Change spool"
dropdown, then a synthetic per-lane id when stock firmware reports the lane loaded. So a spool you
select by hand (no RFID) shows up in AFC too.

## Panel button behavior

Each lane has two controls: a left button that toggles between Load and Unload, and a right Eject
button.

- The left button is driven by the toolhead filament sensor (`tool_loaded`): it shows **Load**
  (`CHANGE_TOOL`) when no filament is at the tool and **Unload** (`TOOL_UNLOAD`) when filament is
  present. Same button, relabelled. Load loads filament; Unload unloads it.
- The **Eject** button (`LANE_UNLOAD`) docks the tool. It is enabled only when that lane's tool is the
  one currently mounted on the carrier (`AFC.current_lane`), regardless of filament state. When the
  lane's tool is not mounted, Eject is greyed out.

> Heads up for maintainers: upstream Mainsail hardcodes the Eject button to disable on filament state
> (`tool_loaded`), which is wrong for a toolchanger (Eject would grey out exactly when a tool is
> mounted and loaded). The mainsail plugin patches the AFC panel so Eject keys off the mounted tool
> (`laneActive`) instead. That patch lives in the Mainsail JS bundle and must be re-applied if Mainsail
> is re-vendored. A regression test (`tests/test_afc_config.py::test_mainsail_eject_gated_on_mounted_tool`)
> guards it.

## Notes

- Snapmaker U1 only: the lane-to-extruder map and the filament-sensor names are U1 specific.
- Restarts Klipper on install so the new extras and config load.

> Installed on a Snapmaker U1. The lane behaviour is not exercised until a real AFC unit is
> attached.
