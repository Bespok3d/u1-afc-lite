# ruff: noqa: PLR2004  Tests assert against literal spool ids and colors.
"""Regression tests for the g-code commands AFC.py registers."""
import base64

import pytest
from AFC import AFC


def _b64(text):
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


class FakeGcode:
    def __init__(self):
        self.scripts_run = []

    def register_command(self, *args, **kwargs):
        pass

    def run_script_from_command(self, script):
        self.scripts_run.append(script)


class FakePrinter:
    def __init__(self):
        self._gcode = FakeGcode()

    def lookup_object(self, name, default=None):
        return self._gcode if name == "gcode" else default

    def register_event_handler(self, *args):
        pass


class FakeConfig:
    def get_printer(self):
        return FakePrinter()

    def get(self, key, default=None):
        return default


REQUIRED = object()


class FakeGcmd:
    def __init__(self, params):
        self._params = params

    def get(self, key, default=REQUIRED):
        if key in self._params:
            return self._params[key]
        if default is REQUIRED:
            raise self.error(f"missing {key}")
        return default

    def get_int(self, key, default=None):
        value = self._params.get(key, default)
        return None if value is None else int(value)

    def error(self, message):
        return ValueError(message)


class FakeLane:
    def __init__(self, lane_index=0):
        self.spool_id = None
        self.name = f"E{lane_index}"
        self.lane_index = lane_index
        self.filament_name = ""
        self.color = "#FFFFFF"
        self.filament_held = {"vendor": "NONE", "type": "NONE", "subtype": "NONE"}

    def get_status(self, eventtime=None):
        return {"color": self.color}

    def filament(self):
        return self.filament_held


def make_afc():
    return AFC(FakeConfig())


def test_set_spool_id_assigns_to_named_lane():
    afc = make_afc()
    lane = FakeLane()
    afc.lanes = {"E0": lane}
    afc.cmd_SET_SPOOL_ID(FakeGcmd({"LANE": "E0", "SPOOL_ID": "42"}))
    assert lane.spool_id == 42


def test_set_spool_id_unknown_lane_raises():
    afc = make_afc()
    afc.lanes = {}
    with pytest.raises(ValueError):
        afc.cmd_SET_SPOOL_ID(FakeGcmd({"LANE": "E9", "SPOOL_ID": "1"}))


def test_set_lane_filament_name_targets_lane_by_extruder():
    afc = make_afc()
    lane = FakeLane(lane_index=3)
    afc.lanes = {"E3": lane}
    afc.cmd_SET_LANE_FILAMENT_NAME(FakeGcmd({"EXTRUDER": "3", "NAME_B64": _b64("ZIRO Silk Gold")}))
    assert lane.filament_name == "ZIRO Silk Gold"


def test_set_lane_filament_name_unknown_extruder_raises():
    afc = make_afc()
    afc.lanes = {"E0": FakeLane(lane_index=0)}
    with pytest.raises(ValueError):
        afc.cmd_SET_LANE_FILAMENT_NAME(FakeGcmd({"EXTRUDER": "9", "NAME_B64": _b64("x")}))


def afc_with_lane(lane_index):
    afc = make_afc()
    afc.lanes = {f"E{lane_index}": FakeLane(lane_index=lane_index)}
    return afc


def test_one_picked_colour_sets_the_lane_to_that_colour_over_a_tag():
    """The Fluidd and Mainsail lane dialogs send one COLOR. Without FORCE the printer refused the
    pick on a lane it read off an official tag."""
    afc = afc_with_lane(2)
    afc.cmd_AFC_SET_LANE_COLOR(FakeGcmd({"LANE": "E2", "COLOR": "ee5911"}))
    assert afc.gcode.scripts_run == [
        "SET_PRINT_FILAMENT_CONFIG CONFIG_EXTRUDER=2 "
        "COLOR_NUMS=1 COLORS=EE5911 MULTI_MODE=0 FORCE=1"]


def test_a_colour_with_its_own_transparency_replaces_the_lanes():
    afc = afc_with_lane(0)
    afc.cmd_AFC_SET_LANE_COLOR(FakeGcmd({"LANE": "E0", "COLOR": "EE591180"}))
    assert afc.gcode.scripts_run == [
        "SET_PRINT_FILAMENT_CONFIG CONFIG_EXTRUDER=0 FILAMENT_COLOR_RGBA=EE591180 FORCE=1"]


def test_the_dialog_sending_back_the_first_colour_keeps_a_multi_colour_reel():
    """Clearing a lane's spool in the dialog resends the lane's colour, the first of the reel's."""
    afc = afc_with_lane(1)
    afc.lanes["E1"].color = "#30D68B"
    afc.cmd_AFC_SET_LANE_COLOR(FakeGcmd({"LANE": "E1", "COLOR": "30d68b"}))
    assert afc.gcode.scripts_run == []


def test_a_colour_list_starting_with_the_lanes_colour_is_still_sent():
    afc = afc_with_lane(1)
    afc.lanes["E1"].color = "#30D68B"
    afc.cmd_AFC_SET_LANE_COLOR(FakeGcmd({"LANE": "E1", "COLORS": "30D68B"}))
    assert afc.gcode.scripts_run == [
        "SET_PRINT_FILAMENT_CONFIG CONFIG_EXTRUDER=1 "
        "COLOR_NUMS=1 COLORS=30D68B MULTI_MODE=0 FORCE=1"]


def test_a_colour_list_reaches_a_lane_with_no_colour_yet():
    """Only a COLOR can be the dialog sending the lane's colour back; a missing COLOR is not."""
    afc = afc_with_lane(3)
    afc.lanes["E3"].color = "#"
    afc.cmd_AFC_SET_LANE_COLOR(FakeGcmd({"LANE": "E3", "COLORS": "30D68B,E736D4"}))
    assert afc.gcode.scripts_run == [
        "SET_PRINT_FILAMENT_CONFIG CONFIG_EXTRUDER=3 "
        "COLOR_NUMS=2 COLORS=30D68B,E736D4 MULTI_MODE=0 FORCE=1"]


def test_every_colour_of_a_multi_colour_reel_reaches_the_printer():
    """SET_COLOR used to send only FILAMENT_COLOR_RGBA, which flattens a reel to one colour. No
    ALPHA is sent, so the printer keeps the lane's own transparency."""
    afc = afc_with_lane(1)
    afc.cmd_AFC_SET_LANE_COLOR(FakeGcmd({"LANE": "E1", "COLORS": "30d68b,E736D4,a8c70c"}))
    assert afc.gcode.scripts_run == [
        "SET_PRINT_FILAMENT_CONFIG CONFIG_EXTRUDER=1 "
        "COLOR_NUMS=3 COLORS=30D68B,E736D4,A8C70C MULTI_MODE=0 FORCE=1"]


def test_a_reel_takes_up_to_five_colours():
    afc = afc_with_lane(0)
    five_colours = "111111,222222,333333,444444,555555"
    afc.cmd_AFC_SET_LANE_COLOR(FakeGcmd({"LANE": "E0", "COLORS": five_colours}))
    assert "COLOR_NUMS=5 COLORS=111111,222222,333333,444444,555555" in afc.gcode.scripts_run[0]


@pytest.mark.parametrize("colour_params", [
    {"COLORS": "111111,222222,333333,444444,555555,666666"},
    {"COLORS": "30D68B,GG0000"},
    {"COLORS": "30D68B,FF00"},
    {"COLORS": "30D68B,"},
    {"COLOR": "EE59"},
    {"COLOR": "EE5911F"},
    {"COLOR": "orange"},
    {"COLOR": "EE5911", "COLORS": "30D68B,E736D4"},
    {},
])
def test_a_wrong_colour_is_refused_and_the_lane_left_alone(colour_params):
    afc = afc_with_lane(0)
    with pytest.raises(ValueError, match="SET_COLOR"):
        afc.cmd_AFC_SET_LANE_COLOR(FakeGcmd({"LANE": "E0", **colour_params}))
    assert afc.gcode.scripts_run == []


def test_set_color_unknown_lane_raises():
    afc = afc_with_lane(0)
    with pytest.raises(ValueError):
        afc.cmd_AFC_SET_LANE_COLOR(FakeGcmd({"LANE": "E9", "COLOR": "EE5911"}))
    assert afc.gcode.scripts_run == []


def afc_with_tagged_lane(lane_index):
    """A lane holding a reel the printer read off a Snapmaker tag."""
    afc = afc_with_lane(lane_index)
    afc.lanes[f"E{lane_index}"].filament_held = {
        "vendor": "Snapmaker", "type": "PLA", "subtype": "Matte"}
    return afc


def test_a_new_material_reaches_a_tagged_lane_and_keeps_its_brand():
    """Without FORCE the printer refused the new material on a lane it read off an official tag."""
    afc = afc_with_tagged_lane(2)
    afc.cmd_AFC_SET_LANE_MATERIAL(FakeGcmd({"LANE": "E2", "MATERIAL": "PETG"}))
    assert afc.gcode.scripts_run == [
        "SET_PRINT_FILAMENT_CONFIG CONFIG_EXTRUDER=2 "
        "FILAMENT_TYPE='PETG' FILAMENT_SUBTYPE='' VENDOR='Snapmaker' FORCE=1"]


def test_a_material_on_a_lane_of_no_known_brand_goes_as_generic():
    afc = afc_with_lane(0)
    afc.cmd_AFC_SET_LANE_MATERIAL(FakeGcmd({"LANE": "E0", "MATERIAL": "PLA", "SUBTYPE": "Silk"}))
    assert afc.gcode.scripts_run == [
        "SET_PRINT_FILAMENT_CONFIG CONFIG_EXTRUDER=0 "
        "FILAMENT_TYPE='PLA' FILAMENT_SUBTYPE='Silk' VENDOR='Generic' FORCE=1"]


def test_the_dialog_sending_back_the_lanes_material_leaves_the_tag_read_alone():
    """Clearing a lane's spool in the Fluidd dialog resends the lane's material unchanged."""
    afc = afc_with_tagged_lane(1)
    afc.cmd_AFC_SET_LANE_MATERIAL(FakeGcmd({"LANE": "E1", "MATERIAL": "PLA"}))
    assert afc.gcode.scripts_run == []


def test_a_new_sub_type_of_the_same_material_is_sent():
    afc = afc_with_tagged_lane(1)
    afc.cmd_AFC_SET_LANE_MATERIAL(FakeGcmd({"LANE": "E1", "MATERIAL": "PLA", "SUBTYPE": "Silk"}))
    assert afc.gcode.scripts_run == [
        "SET_PRINT_FILAMENT_CONFIG CONFIG_EXTRUDER=1 "
        "FILAMENT_TYPE='PLA' FILAMENT_SUBTYPE='Silk' VENDOR='Snapmaker' FORCE=1"]


def test_the_lanes_own_material_and_sub_type_leave_the_tag_read_alone():
    afc = afc_with_tagged_lane(1)
    afc.cmd_AFC_SET_LANE_MATERIAL(FakeGcmd({"LANE": "E1", "MATERIAL": "PLA", "SUBTYPE": "Matte"}))
    assert afc.gcode.scripts_run == []


def test_a_new_brand_reaches_a_tagged_lane_and_keeps_its_material():
    """The printer ignores a brand sent without a material, so the lane's own goes with it."""
    afc = afc_with_tagged_lane(3)
    afc.cmd_AFC_SET_LANE_VENDOR(FakeGcmd({"LANE": "E3", "VENDOR": "Elegoo"}))
    assert afc.gcode.scripts_run == [
        "SET_PRINT_FILAMENT_CONFIG CONFIG_EXTRUDER=3 "
        "FILAMENT_TYPE='PLA' FILAMENT_SUBTYPE='Matte' VENDOR='Elegoo' FORCE=1"]


def test_the_lanes_own_brand_leaves_the_tag_read_alone():
    afc = afc_with_tagged_lane(3)
    afc.cmd_AFC_SET_LANE_VENDOR(FakeGcmd({"LANE": "E3", "VENDOR": "Snapmaker"}))
    assert afc.gcode.scripts_run == []


def test_a_brand_for_a_lane_with_no_material_is_refused_and_nothing_written():
    """The brand went out with the material 'NONE', which the printer then stored as real."""
    afc = afc_with_lane(2)
    with pytest.raises(ValueError, match="no material"):
        afc.cmd_AFC_SET_LANE_VENDOR(FakeGcmd({"LANE": "E2", "VENDOR": "Elegoo"}))
    assert afc.gcode.scripts_run == []


@pytest.mark.parametrize("set_filament", ["cmd_AFC_SET_LANE_MATERIAL", "cmd_AFC_SET_LANE_VENDOR"])
def test_setting_the_filament_of_an_unknown_lane_raises(set_filament):
    afc = afc_with_tagged_lane(0)
    with pytest.raises(ValueError):
        getattr(afc, set_filament)(FakeGcmd({"LANE": "E9", "MATERIAL": "PETG", "VENDOR": "Elegoo"}))
    assert afc.gcode.scripts_run == []


class FakeExtruder:
    def __init__(self, state):
        self._state = state

    def get_park_detector_status(self):
        return {"state": self._state} if self._state else None


class FakeLaneObj:
    def __init__(self, extruder_name):
        self.extruder_name = extruder_name


class FakeNamed:
    def __init__(self, name):
        self._name = name

    def get_name(self):
        return self._name


class FakeToolhead:
    def __init__(self, mounted):
        self._mounted = mounted

    def get_extruder(self):
        return FakeNamed(self._mounted)


class CarrierPrinter:
    def __init__(self, objects):
        self._objects = objects

    def lookup_object(self, name, default=None):
        return self._objects.get(name, default)


def make_afc_with_lanes(objects, lanes):
    afc = make_afc()
    afc.printer = CarrierPrinter(objects)
    afc.lanes = lanes
    return afc


def test_current_lane_is_the_activated_extruder():
    objects = {"extruder": FakeExtruder("PARKED"), "extruder3": FakeExtruder("ACTIVATE")}
    lanes = {"E0": FakeLaneObj("extruder"), "E3": FakeLaneObj("extruder3")}
    afc = make_afc_with_lanes(objects, lanes)
    assert afc._get_current_lane() == "E3"


def test_current_lane_none_when_all_parked():
    objects = {"extruder": FakeExtruder("PARKED"), "extruder3": FakeExtruder("PARKED")}
    lanes = {"E0": FakeLaneObj("extruder"), "E3": FakeLaneObj("extruder3")}
    afc = make_afc_with_lanes(objects, lanes)
    assert afc._get_current_lane() is None


def test_current_lane_falls_back_to_toolhead_without_detectors():
    objects = {
        "extruder": FakeExtruder(None),
        "extruder3": FakeExtruder(None),
        "toolhead": FakeToolhead("extruder3"),
    }
    lanes = {"E0": FakeLaneObj("extruder"), "E3": FakeLaneObj("extruder3")}
    afc = make_afc_with_lanes(objects, lanes)
    assert afc._get_current_lane() == "E3"
