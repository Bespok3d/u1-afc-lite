# ruff: noqa: PLR2004  Tests assert against literal spool ids and colors.
"""Regression tests for the g-code commands AFC.py registers."""
import base64
import shlex

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
    def __init__(self, params, raw_params=None):
        """raw_params is the line as typed, for when Klipper cut it before reading the params."""
        self._params = params
        self._raw_params = raw_params
        if raw_params is None:
            self._raw_params = " ".join(f"{key}={value}" for key, value in params.items())

    def get_command_parameters(self):
        return self._params

    def get_raw_command_parameters(self):
        return self._raw_params

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


def test_a_material_on_a_lane_with_an_empty_brand_goes_as_generic():
    afc = afc_with_tagged_lane(1)
    afc.lanes["E1"].filament_held["vendor"] = ""
    afc.cmd_AFC_SET_LANE_MATERIAL(FakeGcmd({"LANE": "E1", "MATERIAL": "PETG"}))
    assert afc.gcode.scripts_run == [
        "SET_PRINT_FILAMENT_CONFIG CONFIG_EXTRUDER=1 "
        "FILAMENT_TYPE='PETG' FILAMENT_SUBTYPE='' VENDOR='Generic' FORCE=1"]


@pytest.mark.parametrize("vendor_params, raw_line", [
    ({"LANE": "E1"}, "LANE=E1"),
    ({"LANE": "E1", "VENDOR": ""}, "LANE=E1 VENDOR="),
    ({"LANE": "E1", "VENDOR": ""}, 'LANE=E1 VENDOR=""'),
    ({"LANE": "E1", "VENDOR": "NONE"}, "LANE=E1 VENDOR=NONE"),
])
def test_setting_no_brand_is_refused_and_nothing_written(vendor_params, raw_line):
    """A missing brand used to be written as NONE, wiping the lane's brand without a word."""
    afc = afc_with_tagged_lane(1)
    with pytest.raises(ValueError, match=(
            "SET_VENDOR: no brand given for lane E1; give one with VENDOR=; NONE names no brand")):
        afc.cmd_AFC_SET_LANE_VENDOR(FakeGcmd(vendor_params, raw_line))
    assert afc.gcode.scripts_run == []


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


@pytest.mark.parametrize("no_material", ["NONE", ""])
def test_a_brand_for_a_lane_with_no_material_is_refused_and_nothing_written(no_material):
    """The brand went out with the material 'NONE', which the printer then stored as real."""
    afc = afc_with_lane(2)
    afc.lanes["E2"].filament_held = {"vendor": "NONE", "type": no_material, "subtype": "NONE"}
    with pytest.raises(ValueError, match="no material"):
        afc.cmd_AFC_SET_LANE_VENDOR(FakeGcmd({"LANE": "E2", "VENDOR": "Elegoo"}))
    assert afc.gcode.scripts_run == []


@pytest.mark.parametrize("breaking_character", ["'", "#", "*", ";", "\n", "\\"])
def test_a_brand_the_printer_holds_that_it_cannot_take_back_is_refused(breaking_character):
    """A ' closed the quotes and dropped FORCE; # * ; and a line break cut the command short."""
    afc = afc_with_tagged_lane(1)
    afc.lanes["E1"].filament_held["vendor"] = f"Snap{breaking_character}maker"
    with pytest.raises(ValueError, match="SET_MATERIAL: lane E1 holds the brand"):
        afc.cmd_AFC_SET_LANE_MATERIAL(FakeGcmd({"LANE": "E1", "MATERIAL": "PETG"}))
    assert afc.gcode.scripts_run == []


@pytest.mark.parametrize("typed", ['LANE=E1 MATERIAL="PLA#CF"', "LANE=E1 MATERIAL=PLA;CF",
                                   "LANE=E1 MATERIAL=PLA*CF", 'LANE=E1 MATERIAL="PLA ;CF"',
                                   'LANE=E1 MATERIAL="PLA;CF" ; MATERIAL=PLA',
                                   "LANE=E1 MATERIAL='PLA#CF'",
                                   "LANE=E1 MATERIAL=PLA MATERIAL=PLA#CF",
                                   'LANE=E1 "MATERIAL=PLA#CF"'])
def test_a_material_klipper_cut_short_is_refused_and_nothing_written(typed):
    """Klipper hands the command only "PLA", which was written as the whole material."""
    afc = afc_with_tagged_lane(1)
    with pytest.raises(ValueError, match="SET_MATERIAL: Klipper read MATERIAL as 'PLA'"):
        afc.cmd_AFC_SET_LANE_MATERIAL(FakeGcmd({"LANE": "E1", "MATERIAL": "PLA"}, typed))
    assert afc.gcode.scripts_run == []


@pytest.mark.parametrize("typed", ["LANE=E1 MATERIAL=PETG ; spare reel",
                                   'LANE=E1 MATERIAL="PETG";spare reel', "lane=E1 material=PETG",
                                   "LANE=E1\tMATERIAL='PETG'", 'LANE=E1 "MATERIAL=PETG"',
                                   "LANE=E1 'material=PETG';spare reel"])
def test_a_material_klipper_read_whole_is_written(typed):
    afc = afc_with_tagged_lane(1)
    afc.cmd_AFC_SET_LANE_MATERIAL(FakeGcmd({"LANE": "E1", "MATERIAL": "PETG"}, typed))
    assert afc.gcode.scripts_run == [
        "SET_PRINT_FILAMENT_CONFIG CONFIG_EXTRUDER=1 "
        "FILAMENT_TYPE='PETG' FILAMENT_SUBTYPE='' VENDOR='Snapmaker' FORCE=1"]


def test_a_sub_type_klipper_cut_short_is_refused_and_nothing_written():
    afc = afc_with_tagged_lane(1)
    with pytest.raises(ValueError, match="SET_MATERIAL: Klipper read SUBTYPE as 'Matte'"):
        afc.cmd_AFC_SET_LANE_MATERIAL(
            FakeGcmd({"LANE": "E1", "MATERIAL": "PLA", "SUBTYPE": "Matte"},
                     "LANE=E1 MATERIAL=PLA SUBTYPE=Matte#2"))
    assert afc.gcode.scripts_run == []


def test_a_brand_whose_unquoted_apostrophe_klipper_dropped_is_refused():
    """Klipper reads a bare ' as an opening quote and drops it, so "Jayos" was written."""
    afc = afc_with_tagged_lane(1)
    with pytest.raises(ValueError, match="SET_VENDOR: Klipper read VENDOR as 'Jayos'"):
        afc.cmd_AFC_SET_LANE_VENDOR(FakeGcmd({"LANE": "E1", "VENDOR": "Jayos"},
                                             "LANE=E1 VENDOR=Jayo's"))
    assert afc.gcode.scripts_run == []


def test_a_brand_klipper_cut_short_is_refused_and_nothing_written():
    afc = afc_with_tagged_lane(1)
    with pytest.raises(ValueError, match="SET_VENDOR: Klipper read VENDOR as 'Elegoo'"):
        afc.cmd_AFC_SET_LANE_VENDOR(FakeGcmd({"LANE": "E1", "VENDOR": "Elegoo"},
                                             "LANE=E1 VENDOR=Elegoo#2"))
    assert afc.gcode.scripts_run == []


def test_a_brand_the_printer_cannot_take_is_refused_and_nothing_written():
    afc = afc_with_tagged_lane(1)
    with pytest.raises(ValueError, match="SET_VENDOR: the brand \"Jayo's\" holds \"'\""):
        afc.cmd_AFC_SET_LANE_VENDOR(FakeGcmd({"LANE": "E1", "VENDOR": "Jayo's"},
                                             "LANE=E1 VENDOR=\"Jayo's\""))
    assert afc.gcode.scripts_run == []


def test_a_brand_with_a_backslash_fluidd_doubled_is_refused_and_nothing_written():
    """Fluidd sends a typed backslash doubled and Klipper keeps both, so the printer stores two."""
    afc = afc_with_tagged_lane(1)
    with pytest.raises(ValueError, match="SET_VENDOR: the brand"):
        afc.cmd_AFC_SET_LANE_VENDOR(FakeGcmd({"LANE": "E1", "VENDOR": "Snap\\\\maker"},
                                             'LANE=E1 VENDOR="Snap\\\\maker"'))
    assert afc.gcode.scripts_run == []


def test_a_sub_type_the_printer_holds_that_it_cannot_take_back_is_refused():
    """SET_VENDOR sends the lane's own sub-type, which a tag or the screen may have set."""
    afc = afc_with_tagged_lane(1)
    afc.lanes["E1"].filament_held["subtype"] = "Matte;Silk"
    with pytest.raises(ValueError, match="SET_VENDOR: lane E1 holds the sub-type"):
        afc.cmd_AFC_SET_LANE_VENDOR(FakeGcmd({"LANE": "E1", "VENDOR": "Elegoo"}))
    assert afc.gcode.scripts_run == []


@pytest.mark.parametrize("set_filament, stored_field, stored_value, fix", [
    ("cmd_AFC_SET_LANE_MATERIAL", "vendor", "Snap;maker",
     'Set a new brand by sending SET_VENDOR LANE=E1 VENDOR="..." with the new brand in the quotes'),
    ("cmd_AFC_SET_LANE_VENDOR", "type", "PLA#CF",
     "Set a new material by sending SET_MATERIAL LANE=E1 SUBTYPE='Matte' MATERIAL=\"...\""
     " with the new material in the quotes"),
    ("cmd_AFC_SET_LANE_VENDOR", "subtype", "Matte;Silk",
     "Set a new sub-type by sending SET_MATERIAL LANE=E1 MATERIAL='PLA' SUBTYPE=\"...\""
     " with the new sub-type in the quotes"),
])
def test_a_stored_value_refusal_says_how_to_fix_it(set_filament, stored_field, stored_value, fix):
    afc = afc_with_tagged_lane(1)
    afc.lanes["E1"].filament_held[stored_field] = stored_value
    with pytest.raises(ValueError) as refusal:
        getattr(afc, set_filament)(FakeGcmd({"LANE": "E1", "MATERIAL": "PETG", "VENDOR": "Elegoo"}))
    assert f"{fix}, on the printer screen, or by reading the reel's tag again" in str(refusal.value)
    assert afc.gcode.scripts_run == []


COMMAND_METHODS = {"SET_VENDOR": "cmd_AFC_SET_LANE_VENDOR",
                   "SET_MATERIAL": "cmd_AFC_SET_LANE_MATERIAL"}


@pytest.mark.parametrize("refused_command, stored_filament, new_value, written_filament", [
    ("cmd_AFC_SET_LANE_MATERIAL", {"vendor": "Snap;maker", "type": "PLA", "subtype": "Matte"},
     "Bambu Lab", ("PLA", "Matte", "Bambu Lab")),
    ("cmd_AFC_SET_LANE_VENDOR", {"vendor": "Snapmaker", "type": "PLA#CF", "subtype": "Matte"},
     "PLA Plus", ("PLA Plus", "Matte", "Snapmaker")),
    ("cmd_AFC_SET_LANE_VENDOR", {"vendor": "Snapmaker", "type": "PLA#CF", "subtype": "Matte;Silk"},
     "PETG", ("PETG", "", "Snapmaker")),
    ("cmd_AFC_SET_LANE_VENDOR",
     {"vendor": "Snapmaker", "type": "PLA Plus", "subtype": "Matte;Silk"},
     "Silk Matte", ("PLA Plus", "Silk Matte", "Snapmaker")),
])
def test_the_command_a_refusal_names_sets_only_that_field(refused_command, stored_filament,
                                                          new_value, written_filament):
    """The hint once named a command that refused in turn, or cleared a sub-type it kept."""
    afc = afc_with_lane(1)
    afc.lanes["E1"].filament_held = stored_filament
    with pytest.raises(ValueError) as refusal:
        getattr(afc, refused_command)(
            FakeGcmd({"LANE": "E1", "MATERIAL": "PETG", "VENDOR": "Elegoo"}))
    hinted_command = str(refusal.value).split("by sending ")[1].split(" with the new")[0]
    command_name, typed_parameters = hinted_command.replace("...", new_value).split(" ", 1)
    parsed = dict(word.split("=", 1) for word in shlex.split(typed_parameters))
    getattr(afc, COMMAND_METHODS[command_name])(FakeGcmd(parsed, typed_parameters))
    material, subtype, vendor = written_filament
    assert afc.gcode.scripts_run == [
        f"SET_PRINT_FILAMENT_CONFIG CONFIG_EXTRUDER=1 FILAMENT_TYPE='{material}'"
        f" FILAMENT_SUBTYPE='{subtype}' VENDOR='{vendor}' FORCE=1"]


@pytest.mark.parametrize("set_filament, stored_filament", [
    ("cmd_AFC_SET_LANE_MATERIAL", {"vendor": "Snap;maker", "type": "NONE", "subtype": "NONE"}),
    ("cmd_AFC_SET_LANE_MATERIAL", {"vendor": "Snap;maker", "type": "PLA", "subtype": "Matte;Silk"}),
    ("cmd_AFC_SET_LANE_VENDOR", {"vendor": "Snap;maker", "type": "PLA#CF", "subtype": "Matte"}),
    ("cmd_AFC_SET_LANE_VENDOR", {"vendor": "Snap;maker", "type": "PLA", "subtype": "Matte;Silk"}),
])
def test_a_stored_value_no_command_can_fix_names_only_the_screen_and_the_tag(
        set_filament, stored_filament):
    """The command the message named refused in turn, sending the user back and forth."""
    afc = afc_with_lane(1)
    afc.lanes["E1"].filament_held = stored_filament
    with pytest.raises(ValueError) as refusal:
        getattr(afc, set_filament)(FakeGcmd({"LANE": "E1", "MATERIAL": "PETG", "VENDOR": "Elegoo"}))
    assert "on the printer screen or by reading the reel's tag again" in str(refusal.value)
    assert "by sending" not in str(refusal.value)
    assert afc.gcode.scripts_run == []


@pytest.mark.parametrize("material_params, raw_line", [
    ({"LANE": "E1"}, "LANE=E1"),
    ({"LANE": "E1", "MATERIAL": ""}, "LANE=E1 MATERIAL="),
    ({"LANE": "E1", "MATERIAL": ""}, 'LANE=E1 MATERIAL=""'),
    ({"LANE": "E1", "MATERIAL": "NONE"}, "LANE=E1 MATERIAL=NONE"),
])
def test_setting_no_material_is_refused_and_nothing_written(material_params, raw_line):
    afc = afc_with_tagged_lane(1)
    with pytest.raises(ValueError, match=(
            "SET_MATERIAL: no material given for lane E1; give one with MATERIAL=;"
            " NONE names no material")):
        afc.cmd_AFC_SET_LANE_MATERIAL(FakeGcmd(material_params, raw_line))
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
