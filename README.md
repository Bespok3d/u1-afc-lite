# u1-afc-lite

A single-plugin Bespok3d repo: lightweight Automated Filament Changer support for the Snapmaker U1's
four toolheads, ported from the extended firmware's `31-feature-afc-lite`.

- `afc-lite`: ships the `AFC`, `AFC_unit` and `AFC_lane` Klipper extras plus a config that maps the
  four lanes (E0-E3) to the U1 extruders and filament motion sensors, and adds gcode macros for
  color, material, vendor, map, spool id, weight, tool change and lane/tool unload. Per-lane state
  feeds the U1's `SET_PRINT_FILAMENT_CONFIG`.

Klipper restarts on install so the extras and config load.

> Not yet verified on a physical U1.
## Maintainership

These plugins are published and maintained by the Bespok3d org, and several of them repackage or
build on upstream source material. If you own the source material a plugin is based on and would
rather manage it yourself, you are welcome to contact the org to claim it back. The one condition is
that it stays actively maintained: a claimed plugin left to rot will be reclaimed so users are never
stranded on an abandoned package.
