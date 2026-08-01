# ruff: noqa: PLR2004  Tests assert against literal spool ids and colors.
"""Regression tests for the AFC lane spool-id resolution."""
import json
import os

import AFC_lane
from AFC_lane import AFCLane, coerce_spool_id


class FakePrinter:
    def register_event_handler(self, *args):
        pass

    def lookup_object(self, *args, **kwargs):
        return None


class FakeConfig:
    def __init__(self, lane_index):
        self._lane = lane_index

    def get_printer(self):
        return FakePrinter()

    def get_name(self):
        return f"AFC_lane E{self._lane}"

    def get(self, key, default=None):
        return default

    def getint(self, key, default=0):
        return self._lane if key == "lane" else default


def make_lane(lane_index=0):
    return AFCLane(FakeConfig(lane_index))


class FakeToolCountMacro:
    def __init__(self, tools_in_play):
        self._tools_in_play = tools_in_play

    def get_status(self, eventtime=None):
        return {"count": self._tools_in_play}


class ToolCountPrinter(FakePrinter):
    """A printer whose web interface has declared how many of the 32 logical tools the file about
    to print uses."""

    def __init__(self, tools_in_play):
        self._tool_count_macro = FakeToolCountMacro(tools_in_play)

    def lookup_object(self, name, default=None):
        return self._tool_count_macro if name == AFC_lane.TOOL_COUNT_MACRO else default


def test_coerce_rejects_zero_empty_and_junk():
    assert coerce_spool_id("0") is None
    assert coerce_spool_id(0) is None
    assert coerce_spool_id("") is None
    assert coerce_spool_id(None) is None
    assert coerce_spool_id("abc") is None


def test_coerce_accepts_numbers():
    assert coerce_spool_id("42") == 42
    assert coerce_spool_id(42) == 42


def test_explicit_spool_id_wins_over_everything():
    lane = make_lane(0)
    lane.spool_id = 55
    assert lane._resolve_spool_id({"loaded": True}) == 55


def test_no_synthetic_id_when_no_real_source(monkeypatch, tmp_path):
    """A loaded lane with no real id (no SET_SPOOL_ID / RFID / tool-macro pick) resolves to None.
    The dropped 0.1.3 shim emitted a synthetic 9M+index id here; a screen pick's NAME now rides
    filament_name, so the lane must never invent a spool id that resolves to nothing."""
    monkeypatch.setattr(AFC_lane, "RFID_DATA_FILE", str(tmp_path / "absent.json"))
    lane = make_lane(2)
    assert lane._resolve_spool_id({"loaded": True}) is None
    assert lane._resolve_spool_id({"loaded": False}) is None


def test_rfid_tag_id_used_when_present(monkeypatch, tmp_path):
    rfid = tmp_path / "rfid.json"
    rfid.write_text(json.dumps({"0": {"SPOOL_ID": "77"}}))
    monkeypatch.setattr(AFC_lane, "RFID_DATA_FILE", str(rfid))
    lane = make_lane(0)
    assert lane._resolve_spool_id({"loaded": False}) == 77


class FakeMacro:
    def __init__(self, spool_id):
        self.variables = {"spool_id": spool_id}


class MacroPrinter:
    def __init__(self, tool, macro):
        self._tool, self._macro = tool, macro

    def register_event_handler(self, *args):
        pass

    def lookup_object(self, name, default=None):
        return self._macro if name == f"gcode_macro {self._tool}" else default


def test_panel_picked_spool_used_when_no_rfid(monkeypatch, tmp_path):
    monkeypatch.setattr(AFC_lane, "RFID_DATA_FILE", str(tmp_path / "absent.json"))
    lane = make_lane(3)
    lane.printer = MacroPrinter("T3", FakeMacro(99))
    assert lane._resolve_spool_id({"loaded": True, "map": ["T3"]}) == 99


def test_panel_pick_loses_to_rfid_tag(monkeypatch, tmp_path):
    rfid = tmp_path / "rfid.json"
    rfid.write_text(json.dumps({"3": {"SPOOL_ID": "77"}}))
    monkeypatch.setattr(AFC_lane, "RFID_DATA_FILE", str(rfid))
    lane = make_lane(3)
    lane.printer = MacroPrinter("T3", FakeMacro(99))
    assert lane._resolve_spool_id({"loaded": True, "map": ["T3"]}) == 77


class FakeExtruder:
    def __init__(self, state):
        self._state = state

    def get_park_detector_status(self, eventtime=None):
        return {"state": self._state}


class ExtruderPrinter(FakePrinter):
    def __init__(self, extruder_name, extruder):
        self._extruder_name, self._extruder = extruder_name, extruder

    def lookup_object(self, name, default=None):
        return self._extruder if name == self._extruder_name else default


def lane_with_park_detector(park_state):
    lane = make_lane(1)
    lane.extruder_name = "extruder1"
    lane.printer = ExtruderPrinter("extruder1", FakeExtruder(park_state))
    return lane


def test_mounted_true_when_park_detector_active():
    lane = lane_with_park_detector("ACTIVATE")
    assert lane._mounted() is True
    assert lane.get_status()["mounted"] is True


def test_mounted_false_when_park_detector_parked():
    lane = lane_with_park_detector("PARKED")
    assert lane._mounted() is False
    assert lane.get_status()["mounted"] is False


def test_mounted_absent_without_park_detector():
    lane = make_lane(0)
    assert lane._mounted() is None
    assert "mounted" not in lane.get_status()


def test_filament_name_emitted_only_when_enriched():
    lane = make_lane(0)
    assert "filament_name" not in lane.get_status()
    lane.filament_name = "ZIRO Silk Gold"
    assert lane.get_status()["filament_name"] == "ZIRO Silk Gold"


def test_missing_rfid_file_is_not_a_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(AFC_lane, "RFID_DATA_FILE", str(tmp_path / "nope.json"))
    lane = make_lane(0)
    assert lane._rfid_data() == {}


def test_rfid_read_is_mtime_cached(monkeypatch, tmp_path):
    rfid = tmp_path / "rfid.json"
    rfid.write_text(json.dumps({"0": {"SPOOL_ID": "1"}}))
    os.utime(rfid, (1000, 1000))
    monkeypatch.setattr(AFC_lane, "RFID_DATA_FILE", str(rfid))
    lane = make_lane(0)
    assert lane._rfid_spool_id() == 1

    rfid.write_text(json.dumps({"0": {"SPOOL_ID": "2"}}))
    os.utime(rfid, (1000, 1000))
    assert lane._rfid_spool_id() == 1  # mtime unchanged -> cached value reused

    os.utime(rfid, (2000, 2000))
    assert lane._rfid_spool_id() == 2  # mtime bumped -> re-read


def test_a_lane_reports_every_tool_the_printer_feeds_from_it():
    """A file using more tools than the printer has lanes puts several logical tools on one lane.
    Reporting only the first left the rest showing in the web UI as fed by no lane at all."""
    lane = make_lane(2)
    lane.printer = ToolCountPrinter(6)
    printer_map = {"extruder_map_table": [0, 1, 2, 3, 2, 2]}
    assert lane._mapped_tools(printer_map) == ["T2", "T4", "T5"]


def test_a_lane_none_of_the_files_tools_are_fed_from_reports_none():
    """Falling back to the lane's own tool put that tool back on a lane the user had just moved it
    off, so the whole file could never be put on one lane and moving a second tool onto a lane
    looked like it pushed the first tool away."""
    lane = make_lane(0)
    lane.printer = ToolCountPrinter(4)
    every_tool_on_the_second_lane = [1, 1, 1, 1]
    assert lane._mapped_tools({"extruder_map_table": every_tool_on_the_second_lane}) == []


def test_the_first_lane_does_not_claim_the_tools_the_file_never_uses():
    """The map table is always 32 entries long and every entry a file never set still reads as
    lane 0, so reading the whole table made the first lane report T0 through T30 for a six-tool
    print."""
    lane = make_lane(0)
    lane.printer = ToolCountPrinter(6)
    six_tools_over_four_lanes = [0, 1, 2, 3, 0, 1] + [0] * 26
    assert lane._mapped_tools({"extruder_map_table": six_tools_over_four_lanes}) == ["T0", "T4"]


def test_with_no_file_in_play_a_lane_reports_its_own_tool():
    """Nothing declared means no file is being started, so a lane says what it always says rather
    than reading a stale table."""
    lane = make_lane(3)
    assert lane._mapped_tools({"extruder_map_table": [0] * 32}) == ["T3"]


def test_the_spool_of_a_lane_feeding_several_tools_is_the_first_one_picked(monkeypatch, tmp_path):
    monkeypatch.setattr(AFC_lane, "RFID_DATA_FILE", str(tmp_path / "absent.json"))
    lane = make_lane(3)
    lane.printer = MacroPrinter("T5", FakeMacro(42))
    assert lane._resolve_spool_id({"loaded": True, "map": ["T3", "T5"]}) == 42
