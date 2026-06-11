"""Regression tests for the AFC g-code macro wiring in afc-lite.cfg.

The AFC web panel maps its lane buttons to gcode:
    Load   -> CHANGE_TOOL LANE=E{n}   (load filament)
    Unload -> TOOL_UNLOAD LANE=E{n}   (unload filament)
    Eject  -> LANE_UNLOAD LANE=E{n}   (dock the tool; panel patched to enable only
                                       when the lane is mounted on the carrier)

Eject docks the tool via PARK_EXTRUDER; Load and Unload only move filament.
"""
import re
from pathlib import Path

import pytest

AFC_CFG = Path(__file__).resolve().parent.parent / "files" / "cfg" / "klipper" / "afc-lite.cfg"
PLUGINS_DIR = Path(__file__).resolve().parents[3]
# The AFC panel ships in BOTH frontends (independent codebases), each with its own copy of the eject
# logic, so the patch lives in both bundles.
FRONTEND_ASSETS = {
    "mainsail": PLUGINS_DIR / "mainsail-plugin" / "mainsail" / "files" / "html" / "assets",
    "fluidd": PLUGINS_DIR / "fluidd-plugin" / "fluidd" / "files" / "fluidd" / "assets",
}


def macro_body(macro_name):
    text = AFC_CFG.read_text()
    pattern = rf"\[gcode_macro {re.escape(macro_name)}\](.*?)(?=\n\[|\Z)"
    match = re.search(pattern, text, re.DOTALL)
    if match is None:
        raise AssertionError(f"macro {macro_name} not found in afc-lite.cfg")
    return match.group(1)


def test_eject_docks_the_tool_without_moving_filament():
    body = macro_body("LANE_UNLOAD")
    assert "PARK_EXTRUDER" in body
    assert "AUTO_FEEDING" not in body


def test_unload_moves_filament_without_docking():
    body = macro_body("TOOL_UNLOAD")
    assert "AUTO_FEEDING" in body
    assert "UNLOAD=1" in body
    assert "PARK_EXTRUDER" not in body


def test_load_moves_filament_without_docking():
    body = macro_body("CHANGE_TOOL")
    assert "AUTO_FEEDING" in body
    assert "LOAD=1" in body
    assert "PARK_EXTRUDER" not in body


def test_eject_differs_from_unload():
    assert macro_body("LANE_UNLOAD") != macro_body("TOOL_UNLOAD")


def _afc_bundle_text(assets_dir):
    if not assets_dir.is_dir():
        pytest.skip("frontend sibling not present (standalone afc-lite checkout)")
    for path in assets_dir.glob("*.js"):
        text = path.read_text(encoding="utf-8")
        if "ejectLane" in text and "laneActive" in text:
            return text
    raise AssertionError(f"AFC panel bundle not found under {assets_dir}")


@pytest.mark.parametrize("frontend", sorted(FRONTEND_ASSETS))
def test_frontend_eject_gated_on_mounted_tool(frontend):
    text = _afc_bundle_text(FRONTEND_ASSETS[frontend])
    assert "disabled:!e.laneActive" in text
    assert "e.toolLoaded||!e.laneRunout&&e.toolLoaded" not in text
