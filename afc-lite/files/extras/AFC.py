# Originally from the Extended Firmware overlay 31-feature-afc-lite (paxx12), GPL-3.0.
# Modified by the Bespok3d project on 2026-07-28: extended with Bespok3d lane state, filament-name
# decoding and the g-code surface this plugin needs.

# ruff: noqa: N802  Klipper registers g-code handlers by method name; they must be cmd_UPPERCASE.
import base64
import string

# The printer holds up to five colours per reel (FILAMENT_COLOR_NUMS_MAX in its print_task_config).
REEL_COLORS_MAX = 5
HEX_DIGITS = frozenset(string.hexdigits)
RGB_HEX_LENGTH = 6
RGBA_HEX_LENGTH = 8
# Snapmaker documents no meaning for MULTI_MODE; every known sender of a multi-colour reel sends 0.
MULTI_COLOR_MODE = 0
DEFAULT_MATERIAL = "PLA"
# What the printer holds for a field no tag and no user has set.
NOTHING_SET = "NONE"
# The slicer's name for a reel of no known brand.
GENERIC_VENDOR = "Generic"


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
    return GENERIC_VENDOR if lane_vendor == NOTHING_SET else lane_vendor


def filament_settings(vendor: str, material: str, subtype: str) -> str:
    """The printer takes a brand only together with a material and a sub-type."""
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

    def cmd_AFC_SET_LANE_MATERIAL(self, gcmd):
        lane = self._lane_named(gcmd)
        material = gcmd.get('MATERIAL', DEFAULT_MATERIAL)
        subtype = gcmd.get('SUBTYPE', None)
        filament = lane.filament()
        if is_the_lanes_own_material(material, subtype, filament):
            return
        vendor = vendor_for_material(filament['vendor'])
        self._force_filament_config(lane, filament_settings(vendor, material, subtype or ''))

    def cmd_AFC_SET_LANE_VENDOR(self, gcmd):
        lane = self._lane_named(gcmd)
        vendor = gcmd.get('VENDOR', NOTHING_SET)
        filament = lane.filament()
        if vendor == filament['vendor']:
            return
        if filament['type'] == NOTHING_SET:
            raise gcmd.error(f"SET_VENDOR: lane {lane.name} has no material yet; set it with"
                             " SET_MATERIAL first. Nothing was changed.")
        self._force_filament_config(
            lane, filament_settings(vendor, filament['type'], filament['subtype']))

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
