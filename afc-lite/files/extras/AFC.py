# Originally from the Extended Firmware overlay 31-feature-afc-lite (paxx12), GPL-3.0.
# Modified by the Bespok3d project on 2026-07-28: extended with Bespok3d lane state, filament-name
# decoding and the g-code surface this plugin needs.

# ruff: noqa: N802  Klipper registers g-code handlers by method name; they must be cmd_UPPERCASE.
import base64
import re
import string

# The printer holds up to five colours per reel (FILAMENT_COLOR_NUMS_MAX in its print_task_config).
REEL_COLORS_MAX = 5
HEX_DIGITS = frozenset(string.hexdigits)
RGB_HEX_LENGTH = 6
RGBA_HEX_LENGTH = 8
# Snapmaker documents no meaning for MULTI_MODE; every known sender of a multi-colour reel sends 0.
MULTI_COLOR_MODE = 0
# What the printer holds for a field no tag and no user has set.
NOTHING_SET = "NONE"
# The printer's print_task_config counts an empty material as no material too.
NO_MATERIAL = (NOTHING_SET, "")
# An empty brand names no brand either.
NO_VENDOR = (NOTHING_SET, "")
# The slicer's name for a reel of no known brand.
GENERIC_VENDOR = "Generic"
# A ' closes the quotes around a value sent to the printer, Klipper cuts a command line at # * or ;
# whether quoted or not, and a line break starts another command. Fluidd sends a \ doubled and
# Klipper never undoes that, so the printer would store it doubled.
CHARACTERS_THAT_CUT_A_COMMAND = frozenset("#*;")
CHARACTERS_THAT_BREAK_A_COMMAND = CHARACTERS_THAT_CUT_A_COMMAND | {"'", "\n", "\\"}
QUOTES = ('"', "'")
CUT_CHARACTER = re.compile("[" + re.escape("".join(sorted(CHARACTERS_THAT_CUT_A_COMMAND))) + "]")
# One parameter as Klipper's splitter reads it: split on space and tab only, outside quotes, with a
# quote left open running to the end of the line.
TYPED_PARAMETER = re.compile(r"""(?:[^ \t"']|"[^"]*(?:"|$)|'[^']*(?:'|$))+""")
QUOTED_PART = re.compile(r""""([^"]*)"?|'([^']*)'?""")
# The command that sets each stored field anew, named in full because LANE defaults to E0, and
# keeping the lane's other fields since SET_MATERIAL clears a sub-type left out. Values go in
# quotes because they may hold a space; a stored one holds no ' since a ' is refused.
COMMAND_THAT_SETS = {"brand": "SET_VENDOR LANE={lane} VENDOR=",
                     "material": "SET_MATERIAL LANE={lane}{kept_subtype} MATERIAL=",
                     "sub-type": "SET_MATERIAL LANE={lane} MATERIAL='{material}' SUBTYPE="}
NEW_VALUE_PLACE = '"..."'


def _decode_name(raw: str) -> str:
    """Base64-decode a pushed filament name (encoded so spaces survive Klipper's gcode parser)."""
    try:
        return base64.b64decode(raw).decode('utf-8', 'replace') if raw else ''
    except ValueError:
        return ''


def _is_hex_color(color: str, hex_length: int) -> bool:
    return len(color) == hex_length and set(color) <= HEX_DIGITS


def reel_colors(color_list: str) -> list[str]:
    """The colours of a multi-colour reel from a `COLORS=a,b` list, 6-digit hex each. Raises
    ValueError saying what is wrong, so the console tells the user why nothing changed."""
    colors = [color.strip().upper() for color in color_list.split(",")]
    if len(colors) > REEL_COLORS_MAX:
        raise ValueError(
            f"a reel holds at most {REEL_COLORS_MAX} colours, COLORS lists {len(colors)}")
    bad_colors = ", ".join(repr(color) for color in colors
                           if not _is_hex_color(color, RGB_HEX_LENGTH))
    if bad_colors:
        raise ValueError(f"COLORS takes 6-digit hex colours without '#', not {bad_colors}")
    return colors


def single_color_settings(color: str) -> str:
    """A 6-digit colour goes as a one-colour list, so the lane keeps its own transparency; only an
    8-digit colour, which carries its own, replaces it."""
    hex_color = color.strip().upper()
    if _is_hex_color(hex_color, RGB_HEX_LENGTH):
        return _multi_color_settings([hex_color])
    if _is_hex_color(hex_color, RGBA_HEX_LENGTH):
        return f"FILAMENT_COLOR_RGBA={hex_color}"
    raise ValueError(f"COLOR takes a 6 or 8-digit hex colour without '#', not {color!r}")


def _multi_color_settings(colors: list[str]) -> str:
    """No ALPHA: the printer then keeps the lane's own transparency."""
    return f"COLOR_NUMS={len(colors)} COLORS={','.join(colors)} MULTI_MODE={MULTI_COLOR_MODE}"


def reel_color_settings(color_list: str) -> str:
    return _multi_color_settings(reel_colors(color_list))


def color_settings(color: str, color_list: str) -> str:
    """The SET_PRINT_FILAMENT_CONFIG colour arguments for one colour (COLOR, what the Fluidd and
    Mainsail lane dialogs send) or every colour of a multi-colour reel (COLORS). The one-colour
    form sets the lane to that single colour, since that is what the user picked."""
    if color and color_list:
        raise ValueError("give COLOR or COLORS, not both")
    if color_list:
        return reel_color_settings(color_list)
    if color:
        return single_color_settings(color)
    raise ValueError("give COLOR=<hex> for one colour or COLORS=<hex>,<hex> for a multi-colour"
                     " reel, without '#': Klipper drops everything after a '#'")


def is_the_lanes_own_color(color: str, lane_color: str) -> bool:
    """The lane dialogs send the lane's colour back when only its spool changed, and for a
    multi-colour reel that is its first colour: writing it would flatten the reel to one colour."""
    return color.strip().upper() == lane_color.lstrip("#").upper()


def is_the_lanes_own_material(material: str, subtype: str | None, filament: dict) -> bool:
    """The Fluidd lane dialog sends the lane's material back when only its spool is cleared, and
    writing it would make the printer forget the reel came off a Snapmaker tag."""
    return material == filament['type'] and subtype in (None, filament['subtype'])


def vendor_for_material(lane_vendor: str) -> str:
    return GENERIC_VENDOR if lane_vendor in NO_VENDOR else lane_vendor


def breaking_character(value: str) -> str | None:
    return next((character for character in value
                 if character in CHARACTERS_THAT_BREAK_A_COMMAND), None)


def first_breaking_value(named_values: dict[str, str]) -> tuple[str, str, str] | None:
    return next(((name, value, character) for name, value in named_values.items()
                 if (character := breaking_character(value))), None)


def stored_brand(filament: dict[str, str]) -> dict[str, str]:
    return {"brand": filament['vendor']}


def stored_material_and_subtype(filament: dict[str, str]) -> dict[str, str]:
    return {"material": filament['type'], "sub-type": filament['subtype']}


def brand_can_be_set(filament: dict[str, str]) -> bool:
    return (filament['type'] not in NO_MATERIAL
            and first_breaking_value(stored_material_and_subtype(filament)) is None)


def material_can_be_set(filament: dict[str, str]) -> bool:
    return first_breaking_value(stored_brand(filament)) is None


COMMAND_CAN_SET = {"brand": brand_can_be_set, "material": material_can_be_set,
                   "sub-type": material_can_be_set}


def kept_subtype_parameter(subtype: str) -> str:
    if subtype in NO_MATERIAL or breaking_character(subtype):
        return ""
    return f" SUBTYPE='{subtype}'"


def how_to_set_anew(field_name: str, lane_name: str, filament: dict[str, str]) -> str:
    # A command that would refuse in turn is left out, so the user is never sent back and forth.
    if not COMMAND_CAN_SET[field_name](filament):
        return f"Set a new {field_name} on the printer screen or by reading the reel's tag again."
    command = COMMAND_THAT_SETS[field_name].format(
        lane=lane_name, material=filament['type'],
        kept_subtype=kept_subtype_parameter(filament['subtype']))
    return (f"Set a new {field_name} by sending {command}{NEW_VALUE_PLACE} with the new"
            f" {field_name} in the quotes, on the printer screen, or by reading the reel's tag"
            " again.")


def refuse_breaking_characters(named_values: dict[str, str]) -> None:
    broken = first_breaking_value(named_values)
    if broken is None:
        return
    name, value, character = broken
    raise ValueError(f"the {name} {value!r} holds {character!r}, which the printer cannot take."
                     " Nothing was changed.")


def key_klipper_reads(typed_parameter: str) -> str:
    return QUOTED_PART.sub(r"\1\2", typed_parameter).split("=", 1)[0].upper()


def is_wrapped_in_quotes(typed_text: str) -> bool:
    """True for "KEY=value" typed inside one pair of quotes, which Klipper reads as KEY=value."""
    opening = typed_text[:1]
    return (opening in QUOTES and typed_text[1:].endswith(opening)
            and opening not in typed_text[1:-1])


def typed_whole(typed_parameter: tuple[str, bool] | None, value: str) -> bool:
    """True when the value Klipper read is all the user typed: bare and ended by a space or the
    line's end, or wrapped whole in one pair of quotes."""
    if typed_parameter is None:
        return False
    typed_text, ends_at_the_cut = typed_parameter
    if is_wrapped_in_quotes(typed_text):
        return typed_text[1:-1].split("=", 1)[-1] == value
    typed_value = typed_text.split("=", 1)[-1]
    quoted_forms = {f"{quote}{value}{quote}" for quote in QUOTES}
    return typed_value in quoted_forms or (typed_value == value and not ends_at_the_cut)


def last_typed_parameters(read_text: str, is_cut: bool) -> dict[str, tuple[str, bool]]:
    """Each key's last parameter as typed, the one Klipper keeps, and whether the cut ends it."""
    return {key_klipper_reads(typed.group()):
            (typed.group(), is_cut and typed.end() == len(read_text))
            for typed in TYPED_PARAMETER.finditer(read_text)}


def value_klipper_changed(raw_params: str, params: dict[str, str]) -> tuple[str, str] | None:
    """Klipper reads a command only up to its first # * or ; and drops every quote mark, so a
    value it changed no longer shows whole in the line as typed."""
    cut = CUT_CHARACTER.search(raw_params)
    read_text = raw_params if cut is None else raw_params[:cut.start()]
    last_typed = last_typed_parameters(read_text, cut is not None)
    return next(((key, value) for key, value in params.items()
                 if not typed_whole(last_typed.get(key), value)), None)


def filament_settings(vendor: str, material: str, subtype: str) -> str:
    """The printer takes a brand only together with a material and a sub-type."""
    refuse_breaking_characters({"brand": vendor, "material": material, "sub-type": subtype})
    return f"FILAMENT_TYPE='{material}' FILAMENT_SUBTYPE='{subtype}' VENDOR='{vendor}'"


class AFCState:
    IDLE = "idle"
    LOADING = "loading"
    UNLOADING = "unloading"
    TOOL_CHANGE = "tool_change"
    ERROR = "error"

class AFC:
    def __init__(self, config):
        self.printer = config.get_printer()
        config.get("enabled", "True")
        self.gcode = self.printer.lookup_object("gcode")

        self.units = {}
        self.lanes = {}

        self.gcode.register_command("SET_SPOOL_ID", self.cmd_SET_SPOOL_ID,
                                    desc="Assign a Spoolman spool id to an AFC lane")
        self.gcode.register_command("AFC_SET_LANE_COLOR", self.cmd_AFC_SET_LANE_COLOR,
                                    desc="Set the colour or colours of the reel in an AFC lane")
        self.gcode.register_command("AFC_SET_LANE_MATERIAL", self.cmd_AFC_SET_LANE_MATERIAL,
                                    desc="Set the material of the reel in an AFC lane")
        self.gcode.register_command("AFC_SET_LANE_VENDOR", self.cmd_AFC_SET_LANE_VENDOR,
                                    desc="Set the brand of the reel in an AFC lane")
        self.gcode.register_command("SET_LANE_FILAMENT_NAME", self.cmd_SET_LANE_FILAMENT_NAME,
                                    desc="Set a lane filament display name by extruder")
        self.printer.register_event_handler("klippy:connect", self._handle_connect)

    def cmd_SET_SPOOL_ID(self, gcmd):
        lane_name = gcmd.get('LANE')
        spool_id = gcmd.get_int('SPOOL_ID', None)
        lane = self.lanes.get(lane_name)
        if lane is None:
            raise gcmd.error(f"unknown AFC lane: {lane_name}")
        lane.spool_id = spool_id

    def _lane_named(self, gcmd):
        lane_name = gcmd.get('LANE', 'E0')
        lane = self.lanes.get(lane_name)
        if lane is None:
            raise gcmd.error(f"unknown AFC lane: {lane_name}")
        return lane

    def _force_filament_config(self, lane, settings: str) -> None:
        # FORCE: the printer refuses any change to a lane it read off an official tag, and what the
        # user sets by hand is meant to win over the tag.
        self.gcode.run_script_from_command(
            f"SET_PRINT_FILAMENT_CONFIG CONFIG_EXTRUDER={lane.lane_index} {settings} FORCE=1")

    def _write_filament(self, gcmd, command_name: str, lane,
                        brand_material_subtype: tuple[str, str, str]) -> None:
        try:
            settings = filament_settings(*brand_material_subtype)
        except ValueError as reason:
            raise gcmd.error(f"{command_name}: {reason}") from reason
        self._force_filament_config(lane, settings)

    def cmd_AFC_SET_LANE_COLOR(self, gcmd):
        lane = self._lane_named(gcmd)
        color = gcmd.get('COLOR', '')
        try:
            settings = color_settings(color, gcmd.get('COLORS', ''))
        except ValueError as reason:
            raise gcmd.error(f"SET_COLOR: {reason}") from reason
        if color and is_the_lanes_own_color(color, lane.get_status()['color']):
            return
        self._force_filament_config(lane, settings)

    def _refuse_values_klipper_changed(self, gcmd, command_name: str) -> None:
        changed = value_klipper_changed(gcmd.get_raw_command_parameters(),
                                        gcmd.get_command_parameters())
        if changed is None:
            return
        key, value = changed
        raise gcmd.error(f"{command_name}: Klipper read {key} as {value!r}, not as typed: it ends a"
                         " command at # * or ; and drops quote marks. Nothing was changed.")

    def _refuse_stored_values_the_printer_cannot_take(self, gcmd, command_name: str, lane,
                                                      filament: dict[str, str],
                                                      stored_values: dict[str, str]) -> None:
        broken = first_breaking_value(stored_values)
        if broken is None:
            return
        name, value, character = broken
        raise gcmd.error(
            f"{command_name}: lane {lane.name} holds the {name} {value!r}, and its {character!r}"
            f" cannot go back to the printer. {how_to_set_anew(name, lane.name, filament)}"
            " Nothing was changed.")

    def cmd_AFC_SET_LANE_MATERIAL(self, gcmd):
        self._refuse_values_klipper_changed(gcmd, "SET_MATERIAL")
        lane = self._lane_named(gcmd)
        material = gcmd.get('MATERIAL', '')
        if material in NO_MATERIAL:
            raise gcmd.error(f"SET_MATERIAL: no material given for lane {lane.name}; give one"
                             " with MATERIAL=; NONE names no material. Nothing was changed.")
        subtype = gcmd.get('SUBTYPE', None)
        filament = lane.filament()
        if is_the_lanes_own_material(material, subtype, filament):
            return
        self._refuse_stored_values_the_printer_cannot_take(
            gcmd, "SET_MATERIAL", lane, filament, stored_brand(filament))
        vendor = vendor_for_material(filament['vendor'])
        self._write_filament(gcmd, "SET_MATERIAL", lane, (vendor, material, subtype or ''))

    def cmd_AFC_SET_LANE_VENDOR(self, gcmd):
        self._refuse_values_klipper_changed(gcmd, "SET_VENDOR")
        lane = self._lane_named(gcmd)
        vendor = gcmd.get('VENDOR', '')
        if vendor in NO_VENDOR:
            raise gcmd.error(f"SET_VENDOR: no brand given for lane {lane.name}; give one with"
                             " VENDOR=; NONE names no brand. Nothing was changed.")
        filament = lane.filament()
        if vendor == filament['vendor']:
            return
        if filament['type'] in NO_MATERIAL:
            raise gcmd.error(f"SET_VENDOR: lane {lane.name} has no material yet; set it with"
                             " SET_MATERIAL first. Nothing was changed.")
        self._refuse_stored_values_the_printer_cannot_take(
            gcmd, "SET_VENDOR", lane, filament, stored_material_and_subtype(filament))
        self._write_filament(
            gcmd, "SET_VENDOR", lane, (vendor, filament['type'], filament['subtype']))

    def cmd_SET_LANE_FILAMENT_NAME(self, gcmd):
        extruder = gcmd.get_int('EXTRUDER')
        lane = self._lane_for_extruder(extruder)
        if lane is None:
            raise gcmd.error(f"no AFC lane for extruder index: {extruder}")
        lane.filament_name = _decode_name(gcmd.get('NAME_B64', ''))

    def _lane_for_extruder(self, extruder):
        return next((lane for lane in self.lanes.values()
                     if getattr(lane, 'lane_index', None) == extruder), None)

    def _handle_connect(self):
        for name, obj in self.printer.lookup_objects("AFC_unit"):
            unit_name = name.replace("AFC_", "", 1)
            self.units[unit_name] = obj

        for name, obj in self.printer.lookup_objects("AFC_lane"):
            lane_name = name.split(None, 1)[1] if " " in name else name
            self.lanes[lane_name] = obj

    def _lane_park_states(self):
        states = {}
        for lane_name, lane in self.lanes.items():
            extruder = self.printer.lookup_object(lane.extruder_name, None)
            read_state = getattr(extruder, "get_park_detector_status", None)
            states[lane_name] = read_state() if read_state else None
        return states

    def _toolhead_lane(self):
        try:
            mounted = self.printer.lookup_object('toolhead').get_extruder().get_name()
        except Exception:
            return None
        for lane_name, lane in self.lanes.items():
            if lane.extruder_name == mounted:
                return lane_name
        return None

    def _get_current_lane(self):
        """The lane whose tool is mounted on the carrier. With park detectors that is the extruder
        reporting ACTIVATE; if none is ACTIVATE nothing is mounted, so return None (no active lane,
        every Eject greys out). Without detectors, fall back to the live extruder."""
        try:
            states = self._lane_park_states()
        except Exception:
            return None
        active = [name for name, state in states.items()
                  if state and state.get('state') == 'ACTIVATE']
        if active:
            return active[0]
        has_detectors = any(state is not None for state in states.values())
        return None if has_detectors else self._toolhead_lane()

    def get_status(self, eventtime=None):
        return {
            'current_load': None,
            'current_lane': self._get_current_lane(),
            'next_lane': None,
            'current_state': AFCState.IDLE,
            'current_toolchange': 0,
            'number_of_toolchanges': 0,
            'spoolman': True,
            'td1_present': False,
            'lane_data_enabled': False,
            'error_state': False,
            'bypass_state': False,
            'quiet_mode': False,
            'position_saved': False,
            'units': list(self.units.keys()),
            'lanes': list(self.lanes.keys()),
            'extruders': [],
            'hubs': [],
            'buffers': [],
            'message': "",
            'led_state': "",
        }

def load_config(config):
    return AFC(config)
