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


def test_a_spool_taken_off_a_lane_stays_off_it(monkeypatch, tmp_path):
    """Clear all spools empties the lane even while the tagged spool is still sitting in it: the
    tag file is the RFID reader's and no clear ever rewrites it, so a fallback to it would put the
    spool the user just cleared straight back on the panel."""
    rfid = tmp_path / "rfid.json"
    rfid.write_text(json.dumps({"0": {"SPOOL_ID": "77"}}))
    monkeypatch.setattr(AFC_lane, "RFID_DATA_FILE", str(rfid))
    lane = make_lane(0)
    lane.spool_id = 77
    lane.filament_name = "ELEGOO RAPID PETG Black"
    lane.spool_id = None
    assert lane._resolve_spool_id({"loaded": True}) is None
    assert lane.filament_name == ""


def test_a_tagged_lane_nobody_cleared_still_shows_its_spool(monkeypatch, tmp_path):
    rfid = tmp_path / "rfid.json"
    rfid.write_text(json.dumps({"0": {"SPOOL_ID": "77"}}))
    monkeypatch.setattr(AFC_lane, "RFID_DATA_FILE", str(rfid))
    lane = make_lane(0)
    assert lane._resolve_spool_id({"loaded": True}) == 77


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


class FakePrintTaskConfig:
    """The printer's own tag read, one entry per lane, as print_task_config publishes it."""

    def __init__(self, vendors, types, subtypes, present=(True, True, True, True)):
        self._status = {
            "filament_vendor": list(vendors),
            "filament_type": list(types),
            "filament_sub_type": list(subtypes),
            "filament_exist": list(present),
        }

    def get_status(self, eventtime=None):
        return self._status


def lane_reading_its_tag(lane_index, vendors, types, subtypes, present=(True, True, True, True)):
    lane = make_lane(lane_index)
    lane.print_task_config = FakePrintTaskConfig(vendors, types, subtypes, present)
    return lane


TAGS_ON_FOUR_LANES = (
    ("QIDI", "ELEGOO", "Jayo", "eSun"),
    ("PLA", "PLA+", "PLA", "PETG"),
    ("Matte", "Rapid", "Basic", "Basic"),
)


def test_the_tag_names_the_lane_with_no_spoolman_bridge_installed(monkeypatch, tmp_path):
    """Without the bridge nothing pushed a name, so the card showed whatever bare name Spoolman
    had, or nothing at all. The three words the printer already read off the reel name it."""
    monkeypatch.setattr(AFC_lane, "RFID_DATA_FILE", str(tmp_path / "absent.json"))
    lane = lane_reading_its_tag(0, *TAGS_ON_FOUR_LANES)
    assert lane.get_status()["filament_name"] == "QIDI PLA Matte"


def test_each_lane_is_named_from_its_own_reel(monkeypatch, tmp_path):
    monkeypatch.setattr(AFC_lane, "RFID_DATA_FILE", str(tmp_path / "absent.json"))
    lane = lane_reading_its_tag(3, *TAGS_ON_FOUR_LANES)
    assert lane.get_status()["filament_name"] == "eSun PETG Basic"


def test_the_bridge_name_wins_over_the_tag(monkeypatch, tmp_path):
    """The bridge reads the whole spool record and the tag holds three words, so a lane the user
    linked to a Spoolman spool keeps the name that spool gives it."""
    monkeypatch.setattr(AFC_lane, "RFID_DATA_FILE", str(tmp_path / "absent.json"))
    lane = lane_reading_its_tag(2, *TAGS_ON_FOUR_LANES)
    lane.filament_name = "JAYO PLA High Speed"
    assert lane.get_status()["filament_name"] == "JAYO PLA High Speed"


def test_a_lane_reports_no_weight_because_nothing_on_the_printer_weighs_one(monkeypatch, tmp_path):
    """Every card read 1000 g whatever was on the lane, because the lane reported a made up full
    roll. With no weight reported the card shows nothing, and a lane on a Spoolman spool still
    shows what Spoolman has left, which the panel reads from Spoolman itself."""
    monkeypatch.setattr(AFC_lane, "RFID_DATA_FILE", str(tmp_path / "absent.json"))
    lane = lane_reading_its_tag(0, *TAGS_ON_FOUR_LANES)
    assert "weight" not in lane.get_status()


def test_a_reel_the_tag_says_nothing_about_names_no_lane(monkeypatch, tmp_path):
    """A brand on its own tells nobody what is in the lane, and the material is what a slicer
    matches on, so a tag with no material leaves the panel its own display."""
    monkeypatch.setattr(AFC_lane, "RFID_DATA_FILE", str(tmp_path / "absent.json"))
    lane = lane_reading_its_tag(
        1, ("QIDI", "ELEGOO", "Jayo", "eSun"), ("PLA", "NONE", "PLA", "PETG"),
        ("Matte", "NONE", "Basic", "Basic"),
    )
    assert "filament_name" not in lane.get_status()


def test_an_unbranded_reel_is_still_named_by_its_material(monkeypatch, tmp_path):
    monkeypatch.setattr(AFC_lane, "RFID_DATA_FILE", str(tmp_path / "absent.json"))
    lane = lane_reading_its_tag(
        0, ("NONE", "ELEGOO", "Jayo", "eSun"), ("PETG", "PLA+", "PLA", "PETG"),
        ("NONE", "Rapid", "Basic", "Basic"),
    )
    assert lane.get_status()["filament_name"] == "PETG"


def test_an_empty_lane_is_not_named_by_the_reel_that_left_it(monkeypatch, tmp_path):
    """The tag data the printer holds outlives the reel, so naming a lane with no filament in it
    would put a spool back on the card the user had just taken out."""
    monkeypatch.setattr(AFC_lane, "RFID_DATA_FILE", str(tmp_path / "absent.json"))
    lane = lane_reading_its_tag(
        0, *TAGS_ON_FOUR_LANES, present=(False, True, True, True)
    )
    assert "filament_name" not in lane.get_status()


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


def test_with_no_print_in_play_a_lane_reports_no_tool():
    """Between prints the printer holds its default map, so the panel showed T0 on the first lane,
    T1 on the second and so on, a map no print had asked for."""
    lane = make_lane(3)
    assert lane._mapped_tools({"extruder_map_table": [0, 1, 2, 3] + [0] * 28}) == []


def test_the_spool_of_a_lane_feeding_several_tools_is_the_first_one_picked(monkeypatch, tmp_path):
    monkeypatch.setattr(AFC_lane, "RFID_DATA_FILE", str(tmp_path / "absent.json"))
    lane = make_lane(3)
    lane.printer = MacroPrinter("T5", FakeMacro(42))
    assert lane._resolve_spool_id({"loaded": True, "map": ["T3", "T5"]}) == 42


class FakeVirtualSdcard:
    def __init__(self, file_path):
        self._file_path = file_path

    def file_path(self):
        return self._file_path


class ObjectsPrinter(FakePrinter):
    """A printer holding the named Klipper objects, None for every other lookup."""

    def __init__(self, objects):
        self._objects = objects

    def lookup_object(self, name, default=None):
        return self._objects.get(name, default)


class FakeGcodeMacro:
    def __init__(self, **variables):
        self.variables = variables

    def get_status(self, eventtime=None):
        return self.variables


def gcode_file(tmp_path, header_lines, name="print.gcode"):
    path = tmp_path / name
    header = "".join(f"{line}\n" for line in header_lines)
    path.write_text(f"; HEADER_BLOCK_START\n{header}G28\n")
    return str(path)


class FakePrintStats:
    def __init__(self, state):
        self.state = state


def lane_printing(lane_index, file_path, objects=None, print_state="printing"):
    lane = make_lane(lane_index)
    lane.printer = ObjectsPrinter({**(objects or {}), "print_stats": FakePrintStats(print_state)})
    lane.virtual_sdcard = FakeVirtualSdcard(file_path)
    return lane


def test_the_header_lists_tools_from_filament_numbers():
    two_tool_header = "; filament_density: 1.24,1.27\n; filament: 2,1\n"
    assert AFC_lane.tools_the_header_lists(two_tool_header) == [0, 1]
    assert AFC_lane.tools_the_header_lists("; filament: 2,3,4,5,6,1\r\n") == [0, 1, 2, 3, 4, 5]


def test_a_file_without_a_filament_list_names_no_tools():
    unlisted_header = "; filament_density: 1.24\n; filament_diameter: 1.75\n"
    assert AFC_lane.tools_the_header_lists(unlisted_header) is None


def test_a_print_started_from_the_screen_shows_its_tool_on_the_lane_feeding_it(tmp_path):
    """A screen or slicer print declares no tool count, so every lane fell back to its own tool and
    the panel showed T0 on the first lane while the printer fed T0 from the second."""
    single_tool_file = gcode_file(tmp_path, ["; filament: 1"])
    t0_on_the_second_lane = {"extruder_map_table": [1, 1, 2, 3] + [0] * 28}
    lanes = [lane_printing(lane_index, single_tool_file) for lane_index in range(4)]
    assert [lane._mapped_tools(t0_on_the_second_lane) for lane in lanes] == [[], ["T0"], [], []]


def test_every_lane_shows_the_tool_a_four_tool_print_feeds_from_it(tmp_path):
    four_tool_file = gcode_file(tmp_path, ["; filament: 1,2,3,4"])
    shuffled_map = {"extruder_map_table": [2, 3, 1, 0] + [0] * 28}
    lanes = [lane_printing(lane_index, four_tool_file) for lane_index in range(4)]
    assert [lane._mapped_tools(shuffled_map) for lane in lanes] == [["T3"], ["T2"], ["T0"], ["T1"]]


def test_the_file_wins_over_a_count_declared_for_another_print(tmp_path):
    single_tool_file = gcode_file(tmp_path, ["; filament: 1"])
    count_for_another_print = {AFC_lane.TOOL_COUNT_MACRO: FakeGcodeMacro(count=4)}
    lane = lane_printing(0, single_tool_file, count_for_another_print)
    assert lane._mapped_tools({"extruder_map_table": [0, 0, 0, 0] + [0] * 28}) == ["T0"]


def test_a_file_that_lists_no_tools_falls_back_to_the_declared_count(tmp_path):
    unlisted_file = gcode_file(tmp_path, ["; filament_density: 1.24"])
    lane = lane_printing(1, unlisted_file, {AFC_lane.TOOL_COUNT_MACRO: FakeGcodeMacro(count=2)})
    assert lane._mapped_tools({"extruder_map_table": [1, 1] + [0] * 30}) == ["T0", "T1"]


def test_the_file_is_read_once_per_print(tmp_path, monkeypatch):
    single_tool_file = gcode_file(tmp_path, ["; filament: 1"])
    lane = lane_printing(1, single_tool_file)
    reads = []
    real_read = AFC_lane.read_tools_the_file_uses

    def counted_read(file_path):
        reads.append(file_path)
        return real_read(file_path)

    monkeypatch.setattr(AFC_lane, "read_tools_the_file_uses", counted_read)
    status = {"extruder_map_table": [1] + [0] * 31}
    assert lane._mapped_tools(status) == lane._mapped_tools(status) == ["T0"]
    assert len(reads) == 1


def test_a_finished_print_forgets_the_tool_count_it_declared():
    """The count outlived the print, so after a browser print every idle lane claimed tools again
    off the printer's default map."""
    count_macro = FakeGcodeMacro(count=3)
    lane = make_lane(0)
    lane.printer = ObjectsPrinter({AFC_lane.TOOL_COUNT_MACRO: count_macro})
    lane._forget_declared_tools()
    assert count_macro.variables == {"count": 0}
    assert lane._mapped_tools({"extruder_map_table": [0, 1, 2, 3] + [0] * 28}) == []


def test_an_idle_lane_still_owns_the_spool_picked_for_its_own_tool(monkeypatch, tmp_path):
    monkeypatch.setattr(AFC_lane, "RFID_DATA_FILE", str(tmp_path / "absent.json"))
    lane = make_lane(3)
    lane.printer = MacroPrinter("T3", FakeMacro(99))
    assert lane._resolve_spool_id({"loaded": True, "map": []}) == 99


def test_a_paused_print_keeps_its_tools_on_the_lanes(tmp_path):
    single_tool_file = gcode_file(tmp_path, ["; filament: 1"])
    lane = lane_printing(1, single_tool_file, print_state="paused")
    assert lane._mapped_tools({"extruder_map_table": [1] + [0] * 31}) == ["T0"]


def test_a_failed_print_leaves_the_lanes_with_no_tool(tmp_path):
    """A failed print keeps its file loaded, so idle lanes went on showing its tools until the next
    print started."""
    single_tool_file = gcode_file(tmp_path, ["; filament: 1"])
    lane = lane_printing(0, single_tool_file, print_state="error")
    assert lane._mapped_tools({"extruder_map_table": [0] * 32}) == []


def test_a_lane_feeding_no_tool_of_a_print_shows_no_tool_pick(monkeypatch, tmp_path):
    """The lane fell back to the pick on its own tool, so with T0 fed from the second lane the
    first lane showed T0's spool too."""
    monkeypatch.setattr(AFC_lane, "RFID_DATA_FILE", str(tmp_path / "absent.json"))
    single_tool_file = gcode_file(tmp_path, ["; filament: 1"])
    t0_spool_pick = {"gcode_macro T0": FakeGcodeMacro(spool_id=42)}
    lanes = [lane_printing(lane_index, single_tool_file, t0_spool_pick) for lane_index in range(2)]
    t0_on_the_second_lane = {"extruder_map_table": [1] + [0] * 31}
    states = [{"loaded": True, "map": lane._mapped_tools(t0_on_the_second_lane)} for lane in lanes]
    assert [lane._resolve_spool_id(state) for lane, state in zip(lanes, states)] == [None, 42]


class ColorPrintTaskConfig:
    def __init__(self, color_multi, rgba):
        self._status = {"filament_color_multi": color_multi, "filament_color_rgba": rgba,
                        "filament_exist": [True] * 4}

    def get_status(self, eventtime=None):
        return self._status


def test_a_multi_colour_reel_shows_all_its_colours(monkeypatch, tmp_path):
    """The lane reported only the first colour of a reel the printer knows has four."""
    monkeypatch.setattr(AFC_lane, "RFID_DATA_FILE", str(tmp_path / "absent.json"))
    four_colours = {"nums": 4, "alpha": 255, "mode": 0,
                    "colors": ["30D68B", "E736D4", "A8C70C", "CC580A"]}
    single = {"nums": 1, "alpha": 255, "mode": 0, "colors": ["FFFFFF"]}
    lane = make_lane(1)
    lane.print_task_config = ColorPrintTaskConfig([single, four_colours, single, single],
                                                  ["FFFFFFFF", "30D68BFF", "FFFFFFFF", "FFFFFFFF"])
    status = lane.get_status()
    assert status["colors"] == ["#30D68B", "#E736D4", "#A8C70C", "#CC580A"]
    assert status["color"] == "#30D68B"


def test_a_single_colour_reel_reports_its_one_colour(monkeypatch, tmp_path):
    monkeypatch.setattr(AFC_lane, "RFID_DATA_FILE", str(tmp_path / "absent.json"))
    lane = make_lane(0)
    orange_on_the_first_lane = ["EE5911FF", "FFFFFFFF", "FFFFFFFF", "FFFFFFFF"]
    lane.print_task_config = ColorPrintTaskConfig([], orange_on_the_first_lane)
    assert lane.get_status()["colors"] == ["#EE5911"]


def test_a_lane_gives_the_brand_material_and_sub_type_the_printer_holds(monkeypatch, tmp_path):
    monkeypatch.setattr(AFC_lane, "RFID_DATA_FILE", str(tmp_path / "absent.json"))
    lane = lane_reading_its_tag(1, ["NONE", "Snapmaker", "NONE", "NONE"],
                                ["NONE", "PLA", "NONE", "NONE"],
                                ["NONE", "Matte", "NONE", "NONE"])
    assert lane.filament() == {"vendor": "Snapmaker", "type": "PLA", "subtype": "Matte"}


def test_a_lane_without_the_printers_filament_table_holds_nothing():
    assert make_lane(0).filament() == {"vendor": "NONE", "type": "NONE", "subtype": "NONE"}
