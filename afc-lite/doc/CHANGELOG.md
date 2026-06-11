# Changelog

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
