# AFC Lite (Automated Filament Changer)

Lightweight multi-material support for the Snapmaker U1's four toolheads, ported from the extended
firmware. It installs three Klipper extras (`AFC`, `AFC_unit`, `AFC_lane`) and a config that wires
the four lanes to the U1's extruders and filament motion sensors, then exposes gcode macros for
tracking and changing filament.

## What it installs

- **Klipper extras** into `klippy/extras/`: `AFC.py`, `AFC_unit.py`, `AFC_lane.py`.
- **`afc-lite.cfg`**: one `[AFC]`, one `[AFC_unit U1]`, and four `[AFC_lane E0..E3]` mapped to
  `extruder`/`extruder1..3` and the `e0..e3_filament` motion sensors.
- **`afc-toolmap.cfg`**: the print-start hold below. Installed always, silent unless you turn it
  on.

## Holding a print until the lane-to-tool map is made

Off by default. Turn it on with the plugin's **Hold a print until the lane-to-tool map is made**
setting.

A print sent from the slicer with "start printing after upload" begins on the printer with no browser
involved, so neither web interface gets a chance to open its lane assignment dialog and the file runs
with whatever map was left over. With this on, the print does not start at all: the printer keeps
the request and raises a flag. Fluidd and Mainsail each already carry that dialog, one row per tool
the file uses, with the filament type and weight checks; each opens it on the flag, and its print
button sets the map and then starts the print. The printer refuses to set the map on a print that
has started, which is why it is held back rather than started and stopped.

Needs the matching Bespok3d Fluidd or Mainsail plugin installed: those carry the piece that opens the
dialog. Without one of them the print is held and nothing asks.

A held print never starts on its own. It waits as long as it takes, and dismissing the dialog drops
it without printing. From the console, `AFC_TOOLMAP_GO` starts a held print by hand and
`AFC_TOOLMAP_CANCEL` drops it.

Nothing you wrote is touched. `PRINT_START` is left exactly as it is, so an edited `PRINT_START` and
the print-start hooks ported from the extended firmware keep working. The hold hangs off the command
the web interface and the slicer use to start a print, and a print started from the printer's screen
is not affected at all: the screen asks for the map itself.

## A print that uses more tools than the printer has lanes

The U1 feeds 32 logical tools from its 4 lanes, so a file sliced for 6 tools prints by putting two
of them on a lane that already feeds another tool. Both tools then draw the same filament, which is
what you want when two of the file's colours are the same material. Assign each tool its lane in the
lane assignment dialog; a lane can be picked for as many tools as you like, and picking it for one
tool no longer takes it away from another.

## Macros

`SET_COLOR`, `SET_MATERIAL`, `SET_VENDOR`, `SET_MAP`, `SET_SPOOL_ID`, `SET_WEIGHT`,
`AFC_TOOLS_IN_PLAY`, `CHANGE_TOOL`, `LANE_UNLOAD`, `TOOL_UNLOAD`. Per-lane state is pushed into the U1's `SET_PRINT_FILAMENT_CONFIG`, so
the screen and the slicer see what is loaded in each lane. The screen shows it exactly. The slicer's
**Sync Filament Information** only matches filaments it ships itself and falls back to
`Generic <material>` for everything else; that is the slicer's behaviour, and the Spoolman Bridge doc
covers it under "Limits worth knowing about".

- `CHANGE_TOOL` (Load button) loads filament.
- `TOOL_UNLOAD` (Unload button) unloads filament.
- `LANE_UNLOAD` (Eject button) docks (parks) the tool via `PARK_EXTRUDER`. It moves no filament.
- `AFC_TOOLS_IN_PLAY COUNT=<n>` says how many of the printer's 32 logical tools the file about to
  print uses. The web interface sends it when it opens the lane assignment dialog, because only the
  browser has the file. Without it a lane cannot tell a tool the print does not use from one mapped
  to it, and the panel lists every unused tool on the first lane.

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
