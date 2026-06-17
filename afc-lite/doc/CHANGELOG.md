# Changelog

## 0.1.6

- Lanes can now carry a resolved vendor+name display label (`filament_name`), set by the
  Spoolman bridge via the new `SET_LANE_FILAMENT_NAME EXTRUDER=<n> NAME_B64=<base64>` command
  (addressed by extruder index; the name is base64-encoded so it survives Klipper's gcode
  parser). The field is emitted only when enriched, so the panel keeps falling back to its own
  `spool.filament.name` when no bridge is present (default display preserved).

## 0.1.5

- Each lane now reports a `mounted` boolean in its status, read from that lane's own
  park detector (ACTIVATE = mounted on the carrier). The AFC panel uses it to auto-detect
  toolchanger mode per lane, so Eject enables for the mounted lane without depending on the
  global `current_lane` name match. Buffer-fed setups (no park detector) omit the field and
  keep the original tool-loaded gating.

## 0.1.4

- Eject greys out unless the lane's tool is mounted on the carrier. `AFC.current_lane`
  now reports the extruder whose park detector reads ACTIVATE (mounted) and None
  when every tool is parked, so a parked lane's Eject is correctly disabled. Falls
  back to the live extruder on setups without park detectors.

## 0.1.3

- Clear button roles in the AFC panel: Load loads filament, Unload unloads
  filament, and Eject docks (parks) the tool. Eject calls the per-tool
  PARK_EXTRUDER command, and the Mainsail panel is patched (in the mainsail
  plugin) so Eject is enabled only when that lane's tool is mounted on the
  carrier, regardless of filament. Load and Unload no longer move the toolhead.
- Lanes report a Spoolman spool id (direct SET_SPOOL_ID, RFID tag, the spool
  picked for the lane's tool in the Spoolman panel, or a synthetic per-lane id),
  so the AFC panel shows each filament's name even for a spool selected by hand
  with no RFID.
- Experimental: not yet verified on physical hardware.

## 0.1.0

- First release. Ports the extended-firmware AFC Lite multi-material control
  (Box Turtle style) to stock firmware as drop-in Klipper extras plus config.
- Experimental: not yet verified on physical hardware.
