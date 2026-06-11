# ruff: noqa: PLR2004  Tests assert against literal spool ids and colors.
"""Regression tests for the local Spoolman-API stand-in's synthesis."""
from local_spoolman import (
    CHANNEL_SPOOL_BASE,
    _filament_name,
    _normalized_path,
    load_print_task,
    synthesize_spools,
)


def test_filament_name_joins_non_none_parts():
    assert _filament_name("Generic", "PLA", "Basic") == "Generic PLA Basic"


def test_filament_name_skips_none_tokens():
    assert _filament_name("Generic", "PLA", "NONE") == "Generic PLA"


def test_filament_name_unknown_when_all_none():
    assert _filament_name("NONE", "NONE", "NONE") == "Unknown"


def test_synthesize_only_loaded_extruders():
    print_task = {
        "filament_exist": [True, False, True, False],
        "filament_vendor": ["Acme", "X", "Globex", "Y"],
        "filament_type": ["PLA", "PLA", "PETG", "PLA"],
        "filament_sub_type": ["Basic", "", "CF", ""],
        "filament_color_rgba": ["112233FF", "", "445566FF", ""],
    }
    spools = synthesize_spools(print_task)
    assert [spool["id"] for spool in spools] == [CHANNEL_SPOOL_BASE, CHANNEL_SPOOL_BASE + 2]
    assert spools[0]["filament"]["name"] == "Acme PLA Basic"
    assert spools[0]["filament"]["color_hex"] == "112233"
    assert spools[1]["filament"]["name"] == "Globex PETG CF"


def test_synthesize_empty_when_nothing_loaded():
    assert synthesize_spools({"filament_exist": [False, False]}) == []


def test_load_print_task_missing_file_returns_empty(tmp_path):
    assert load_print_task(str(tmp_path / "absent.json")) == {}


def test_normalized_path_strips_api_prefix():
    assert _normalized_path("/api/v1/spool") == "/v1/spool"
    assert _normalized_path("/v1/spool") == "/v1/spool"
