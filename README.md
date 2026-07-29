# u1-afc-lite

[![licence](https://img.shields.io/badge/licence-GPL--3.0-blue)](LICENSE)
[![release](https://img.shields.io/github/v/release/Bespok3d/u1-afc-lite)](https://github.com/Bespok3d/u1-afc-lite/releases)
[![version](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2FBespok3d%2Fu1-afc-lite%2Fmain%2Fafc-lite%2Fmanifest.json&query=%24.version&label=version&color=blue)](afc-lite/manifest.json)
![printer](https://img.shields.io/badge/printer-Snapmaker%20U1-informational)
![stock firmware](https://img.shields.io/badge/stock%20firmware-no%20flashing-brightgreen)

A single-plugin Bespok3d repo: lightweight Automated Filament Changer support for the Snapmaker U1's
four toolheads, ported from the extended firmware's `31-feature-afc-lite`.

- `afc-lite`: ships the `AFC`, `AFC_unit` and `AFC_lane` Klipper extras plus a config that maps the
  four lanes (E0-E3) to the U1 extruders and filament motion sensors, and adds gcode macros for
  color, material, vendor, map, spool id, weight, tool change and lane/tool unload. Per-lane state
  feeds the U1's `SET_PRINT_FILAMENT_CONFIG`.

Klipper restarts on install so the extras and config load.

> Installed on a Snapmaker U1. The lane behaviour is not exercised until a real AFC unit is
> attached.

## Build locally

Needs Node.js 20+. Builds run through the shared `Bespok3d/b3-builder` tool:

```sh
npm install github:Bespok3d/b3-builder
npx b3-builder build --source ./afc-lite --atom-repo Bespok3d/u1-afc-lite
# -> dist/afc-lite-<ver>.b3 + dist/afc-lite.atom.json
```

Drop `--source` to build every plugin in the repo at once.

## Releasing

Bump a plugin's `manifest.json` `version` and push to `main`. CI runs the `Bespok3d/b3-builder`
Action over the whole repo, which packs each `.b3`, cuts a release per plugin, assembles this repo's
`index.json` sub-list as `U1 AFC Lite`, and registers it in `Bespok3d/main-index`
(`lists/<repo>.json`). Secrets: `MAIN_INDEX_TOKEN` (contents:write on main-index) and
`REGISTRY_SIGNING_KEY` (the org registry key the `b3-builder` Action signs each `.b3` and atom with).

## Maintainership

These plugins are published and maintained by the Bespok3d org, and several of them repackage or
build on upstream source material. If you own the source material a plugin is based on and would
rather manage it yourself, you are welcome to contact the org to claim it back. The one condition is
that it stays actively maintained: a claimed plugin left to rot will be reclaimed so users are never
stranded on an abandoned package.

## Licence

Copyright (C) 2026 unlucio and the Bespok3d contributors

This repo ships code from other projects offered under version 3 of the GNU General Public License,
with no option to use a later version, so version 3 of that licence covers every file in this repo.

This program is free software: you can redistribute it and/or modify it under the terms of version 3
of the GNU General Public License as published by the Free Software Foundation.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without
even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General
Public License for more details.

You should have received a copy of the GNU General Public License along with this program. If not,
see <https://www.gnu.org/licenses/>. The full text is in [LICENSE](LICENSE).

Bespok3d's own code elsewhere is AGPL-3.0-or-later. One licence covering this whole repo is a clarity
choice, so that nobody has to work out which file carries which terms. Version 3 of the GPL and
version 3 of the AGPL may be combined in a single work, and section 13 of each licence says so; what
cannot happen is code offered under version 3 of the GPL alone being re-offered under the AGPL.

Bespok3d is a project of the Bespok3d Organisation, which is not a legal entity. Copyright is held by
the individual authors named above.
